#!/usr/bin/env python3
"""
analisar_io_scripts.py

Analisa estaticamente (via AST, sem executar nada) todos os scripts .py de um
repositório e suas subpastas, usando o arquivo AUTO_SERE_MAPA.txt como
referência/contexto, e gera um relatório Markdown descrevendo, para cada
script: possíveis ENTRADAS (o que ele lê/recebe) e SAÍDAS (o que ele
produz/escreve/retorna).

USO (sem nenhum argumento):
    1. Coloque este arquivo na pasta raiz do repositório (onde também deve
       estar o AUTO_SERE_MAPA.txt).
    2. Rode:
           python3 analisar_io_scripts.py
    3. O relatório será gerado em RELATORIO_IO.md, na mesma pasta.

O script sempre usa a pasta atual (de onde é executado) como raiz do
repositório, sempre procura "AUTO_SERE_MAPA.txt" nessa raiz, e sempre grava
o resultado em "RELATORIO_IO.md" na mesma pasta.

IMPORTANTE: análise 100% estática (módulo `ast`). Nenhum script analisado é
executado. Isso significa que o resultado é uma aproximação heurística baseada
em padrões de código (chamadas conhecidas, imports, decorators, etc.), não uma
garantia absoluta do comportamento em tempo de execução.
"""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuração de padrões conhecidos (heurísticas)
# ---------------------------------------------------------------------------

# Funções/métodos cujo primeiro argumento string geralmente indica um
# caminho de arquivo sendo lido ou escrito.
FUNCOES_ARQUIVO = {
    "open": "generico",
    "read_csv": "leitura",
    "read_excel": "leitura",
    "read_json": "leitura",
    "read_pickle": "leitura",
    "read_sql": "leitura",
    "read_parquet": "leitura",
    "to_csv": "escrita",
    "to_excel": "escrita",
    "to_json": "escrita",
    "to_pickle": "escrita",
    "to_parquet": "escrita",
    "load": "leitura",       # json.load, pickle.load, yaml.load
    "loads": "leitura",
    "dump": "escrita",       # json.dump, pickle.dump, yaml.dump
    "dumps": "escrita",
}

# Chamadas que indicam ENTRADA de dados (usuário, CLI, ambiente, rede, etc.)
CHAMADAS_ENTRADA = {
    "input": "Entrada interativa do usuário via input()",
    "getpass": "Entrada interativa (senha) via getpass",
    "get": "Possível requisição HTTP GET (requests/urllib) ou leitura de dict/env",
    "getenv": "Leitura de variável de ambiente",
    "environ.get": "Leitura de variável de ambiente",
}

# Chamadas que indicam SAÍDA (tela, rede, log)
CHAMADAS_SAIDA = {
    "print": "Saída de texto no console (stdout)",
    "post": "Possível requisição HTTP POST (envio de dados)",
    "put": "Possível requisição HTTP PUT (envio de dados)",
    "write_message": "Escrita de mensagem (framework específico)",
}

# Módulos de automação de navegador — comuns em scripts de SERE/RCO
MODULOS_BROWSER = {"selenium", "playwright", "webdriver"}

# Módulos de GUI comuns no projeto (CustomTkinter, tkinter)
MODULOS_GUI = {"tkinter", "customtkinter", "PyQt5", "PySide6"}


@dataclass
class InfoScript:
    caminho: Path
    entradas: list = field(default_factory=list)
    saidas: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    docstring: str = ""
    funcoes: list = field(default_factory=list)
    tem_main: bool = False
    argparse_args: list = field(default_factory=list)
    erro: str = ""


def obter_nome_chamada(node: ast.Call) -> str:
    """Extrai um nome legível para a função/método chamado (ex: 'open',
    'pd.read_csv', 'requests.get')."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        partes = []
        atual = func
        while isinstance(atual, ast.Attribute):
            partes.append(atual.attr)
            atual = atual.value
        if isinstance(atual, ast.Name):
            partes.append(atual.id)
        return ".".join(reversed(partes))
    return ""


def primeiro_arg_str(node: ast.Call) -> str:
    """Se o primeiro argumento posicional for uma string literal, retorna."""
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return ""


def modo_open(node: ast.Call) -> str:
    """Detecta o modo ('r', 'w', 'a', etc.) passado para open(), seja
    posicional ou via kwarg 'mode'."""
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        return str(node.args[1].value)
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r"  # default do open()


def formato_por_extensao(caminho_arq: str) -> str:
    """Deduz um rótulo de formato a partir da extensão do arquivo, quando
    possível (usado para deixar claro '.json', '.csv', etc. no relatório)."""
    if not caminho_arq or caminho_arq.startswith("<"):
        return ""
    sufixo = Path(caminho_arq).suffix.lower().lstrip(".")
    rotulos = {
        "json": "JSON", "csv": "CSV", "xlsx": "Excel", "xls": "Excel",
        "txt": "texto", "yaml": "YAML", "yml": "YAML", "xml": "XML",
        "pkl": "Pickle", "pickle": "Pickle", "db": "banco de dados",
        "sqlite": "SQLite", "log": "log", "ini": "config (INI)",
        "cfg": "config",
    }
    return rotulos.get(sufixo, "")


def nome_variavel_alvo(node) -> str:
    """Para uma atribuição simples (x = ...) ou 'with ... as x', devolve o
    nome da variável, se for um ast.Name simples."""
    if isinstance(node, ast.Name):
        return node.id
    return ""


class VisitanteIO(ast.NodeVisitor):
    """Percorre a árvore mantendo, por função/escopo, um mapa
    variável -> (caminho_arquivo, modo) para os handles criados por open(),
    permitindo casar corretamente `with open("x.json") as f:` com o
    `json.load(f)` / `json.dump(dados, f)` que vem em seguida — em vez de
    reportar as duas ocorrências como fatos desconectados.
    """

    def __init__(self, info):
        self.info = info
        # pilha de escopos: cada um é um dict var -> (caminho, modo)
        self.pilha_handles = [{}]

    # -- utilidades de escopo -------------------------------------------------
    def _handle_de(self, node):
        """Resolve um nó (geralmente um ast.Name) para (caminho, modo) se ele
        corresponder a uma variável que guarda um handle de open() conhecido
        no escopo atual (ou em escopos externos)."""
        nome_var = nome_variavel_alvo(node)
        if not nome_var:
            return ("", "")
        for escopo in reversed(self.pilha_handles):
            if nome_var in escopo:
                return escopo[nome_var]
        return ("", "")

    def _registrar_handle(self, nome_var, caminho_arq, modo):
        if nome_var:
            self.pilha_handles[-1][nome_var] = (caminho_arq, modo)

    # -- escopos de função ------------------------------------------------
    def visit_FunctionDef(self, node):
        self.info.funcoes.append(node.name)
        if node.name == "main":
            self.info.tem_main = True
        self.pilha_handles.append({})
        self.generic_visit(node)
        self.pilha_handles.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    # -- with open(...) as f: ------------------------------------------------
    def visit_With(self, node):
        for item in node.items:
            self._talvez_registrar_open(item.context_expr, item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    # -- f = open(...) (sem 'with') ----------------------------------------
    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call):
            for alvo in node.targets:
                self._talvez_registrar_open(node.value, alvo)
        self.generic_visit(node)

    def _talvez_registrar_open(self, expr, alvo_var):
        if isinstance(expr, ast.Call):
            nome_chamada = obter_nome_chamada(expr)
            if nome_chamada == "open" or nome_chamada.endswith(".open"):
                caminho_arq = primeiro_arg_str(expr) or "<caminho dinâmico>"
                modo = modo_open(expr)
                nome_var = nome_variavel_alvo(alvo_var) if alvo_var is not None else ""
                if nome_var:
                    self._registrar_handle(nome_var, caminho_arq, modo)

    # -- imports ------------------------------------------------------------
    def visit_Import(self, node):
        for alias in node.names:
            self.info.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.info.imports.append(node.module)
        self.generic_visit(node)

    # -- sys.argv -------------------------------------------------------
    def visit_Attribute(self, node):
        if node.attr == "argv":
            self.info.entradas.append("Leitura de `sys.argv` (argumentos de linha de comando)")
        self.generic_visit(node)

    # -- return -----------------------------------------------------------
    def visit_Return(self, node):
        if node.value is not None:
            self.info.saidas.append("Função retorna um valor (`return ...`)")
        self.generic_visit(node)

    # -- chamadas -----------------------------------------------------------
    def visit_Call(self, node):
        nome = obter_nome_chamada(node)
        ultimo_termo = nome.split(".")[-1] if nome else ""
        info = self.info

        if nome.endswith("add_argument"):
            arg_nome = primeiro_arg_str(node)
            if arg_nome:
                info.argparse_args.append(arg_nome)
                info.entradas.append(f"Argumento de linha de comando: `{arg_nome}` (argparse)")

        # open() isolado (registro de handle já foi feito em visit_With /
        # visit_Assign; aqui só reportamos quando NÃO está sendo capturado
        # em variável, ex: open("x.json").read() encadeado direto)
        if nome == "open" or nome.endswith(".open"):
            caminho_arq = primeiro_arg_str(node) or "<caminho dinâmico>"
            modo = modo_open(node)
            fmt = formato_por_extensao(caminho_arq)
            rotulo_fmt = f" ({fmt})" if fmt else ""
            if "w" in modo or "a" in modo or "x" in modo:
                info.saidas.append(f"Escrita em arquivo{rotulo_fmt}: `{caminho_arq}` (modo `{modo}`)")
            else:
                info.entradas.append(f"Leitura de arquivo{rotulo_fmt}: `{caminho_arq}` (modo `{modo}`)")

        # json.load(f) / pickle.load(f) / yaml.safe_load(f) etc. usando um
        # handle rastreado -> funde com o arquivo real em vez de reportar
        # "objeto dinâmico"
        if ultimo_termo in ("load", "loads") and node.args:
            caminho_arq, modo = self._handle_de(node.args[0])
            fmt = "JSON" if "json" in nome.lower() else ("YAML" if "yaml" in nome.lower() else formato_por_extensao(caminho_arq))
            if caminho_arq:
                rotulo_fmt = f" {fmt}" if fmt else ""
                info.entradas.append(f"Leitura de dados{rotulo_fmt}: `{caminho_arq}` (via `{nome}(...)`)")
            elif ultimo_termo == "load":
                info.entradas.append(f"Leitura de dados via `{nome}(...)`: `<arquivo/objeto dinâmico>`")
            # 'loads' sem handle reconhecido normalmente opera sobre uma
            # string já em memória (ex: resposta HTTP) — não é um arquivo,
            # então não reportamos como leitura de arquivo genérica.

        # json.dump(dados, f) / pickle.dump(dados, f) -> idem para escrita
        if ultimo_termo in ("dump", "dumps") and node.args:
            alvo = node.args[1] if len(node.args) > 1 else None
            caminho_arq, modo = self._handle_de(alvo) if alvo is not None else ("", "")
            fmt = "JSON" if "json" in nome.lower() else ("YAML" if "yaml" in nome.lower() else formato_por_extensao(caminho_arq))
            if caminho_arq:
                rotulo_fmt = f" {fmt}" if fmt else ""
                info.saidas.append(f"Escrita de dados{rotulo_fmt}: `{caminho_arq}` (via `{nome}(...)`)")
            elif ultimo_termo == "dump":
                info.saidas.append(f"Escrita de dados via `{nome}(...)`: `<arquivo/objeto dinâmico>`")

        # pandas/etc: read_csv, read_excel, read_json, to_csv, to_excel...
        if ultimo_termo in FUNCOES_ARQUIVO and ultimo_termo not in ("open", "load", "loads", "dump", "dumps"):
            tipo = FUNCOES_ARQUIVO[ultimo_termo]
            caminho_arq = primeiro_arg_str(node) or "<caminho/objeto dinâmico>"
            fmt = formato_por_extensao(caminho_arq)
            rotulo_fmt = f" ({fmt})" if fmt else ""
            if tipo == "leitura":
                info.entradas.append(f"Leitura de dados{rotulo_fmt} via `{nome}(...)`: `{caminho_arq}`")
            else:
                info.saidas.append(f"Escrita de dados{rotulo_fmt} via `{nome}(...)`: `{caminho_arq}`")

        if ultimo_termo in ("get", "post", "put", "delete", "patch") and any(
            m in info.imports for m in ("requests", "httpx", "urllib.request")
        ):
            url = primeiro_arg_str(node) or "<url dinâmica>"
            if ultimo_termo == "get":
                info.entradas.append(f"Requisição HTTP GET: `{url}`")
            else:
                info.saidas.append(f"Requisição HTTP {ultimo_termo.upper()} (envio de dados): `{url}`")

        if ultimo_termo == "input":
            prompt = primeiro_arg_str(node)
            info.entradas.append(f"Entrada interativa do usuário (input): \"{prompt}\"" if prompt else "Entrada interativa do usuário (input)")

        if ultimo_termo == "print":
            info.saidas.append("Saída impressa no console (print)")

        if ultimo_termo in ("getenv",) or nome == "os.environ.get":
            chave = primeiro_arg_str(node) or "<variável dinâmica>"
            info.entradas.append(f"Leitura de variável de ambiente: `{chave}`")

        if "logging" in info.imports or "logger" in nome.lower():
            if ultimo_termo in ("info", "warning", "error", "debug", "critical"):
                info.saidas.append(f"Log ({ultimo_termo}) via logging")

        self.generic_visit(node)


def analisar_arquivo(caminho: Path) -> InfoScript:
    info = InfoScript(caminho=caminho)
    try:
        codigo = caminho.read_text(encoding="utf-8", errors="replace")
        arvore = ast.parse(codigo, filename=str(caminho))
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        info.erro = f"Não foi possível analisar o arquivo: {e}"
        return info

    info.docstring = ast.get_docstring(arvore) or ""

    visitante = VisitanteIO(info)
    visitante.visit(arvore)

    # Detecta uso de bibliotecas de automação de navegador / GUI, que contam
    # como "entrada" (interação com página/usuário) e "saída" (ações na tela)
    if any(m.split(".")[0] in MODULOS_BROWSER for m in info.imports):
        info.entradas.append("Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página")
        info.saidas.append("Ações no navegador automatizado (cliques, preenchimento de formulários)")

    if any(m.split(".")[0] in MODULOS_GUI for m in info.imports):
        info.entradas.append("Entrada via interface gráfica (GUI) — campos preenchidos pelo usuário")
        info.saidas.append("Saída via interface gráfica (GUI) — telas, mensagens, widgets atualizados")

    # Deduplicação preservando ordem
    info.entradas = list(dict.fromkeys(info.entradas))
    info.saidas = list(dict.fromkeys(info.saidas))
    info.imports = sorted(set(info.imports))

    return info


def carregar_mapa(caminho_mapa: Path) -> str:
    """Carrega o conteúdo do AUTO_SERE_MAPA.txt, se existir, para incluir como
    contexto de referência no topo do relatório."""
    if caminho_mapa.exists():
        try:
            return caminho_mapa.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"(Não foi possível ler {caminho_mapa.name}: {e})"
    return ""


def encontrar_scripts(raiz: Path) -> list:
    """Encontra todos os .py do repositório, ignorando pastas comuns de
    ambiente virtual, cache e controle de versão."""
    ignorar = {".git", "__pycache__", "venv", ".venv", "env", "node_modules", "build", "dist", ".mypy_cache"}
    scripts = []
    for caminho in sorted(raiz.rglob("*.py")):
        if any(parte in ignorar for parte in caminho.parts):
            continue
        scripts.append(caminho)
    return scripts


def gerar_relatorio_markdown(raiz: Path, mapa_texto: str, infos: list) -> str:
    linhas = []
    linhas.append(f"# Relatório de Entrada/Saída dos Scripts — {raiz.name}\n")
    linhas.append(
        "> Gerado por análise estática (AST), sem executar nenhum script. "
        "Os itens listados são heurísticos: baseiam-se em padrões de código "
        "reconhecidos (chamadas conhecidas, imports, decorators). Revise "
        "casos de entrada/saída dinâmica ou indireta manualmente.\n"
    )

    if mapa_texto:
        linhas.append("## Referência: AUTO_SERE_MAPA.txt\n")
        linhas.append("```")
        linhas.append(mapa_texto.strip())
        linhas.append("```\n")

    linhas.append(f"## Scripts analisados: {len(infos)}\n")

    # Índice
    linhas.append("## Índice\n")
    for info in infos:
        rel = info.caminho.relative_to(raiz)
        ancora = str(rel).lower().replace("/", "").replace(".", "").replace(" ", "-").replace("_", "-")
        linhas.append(f"- [{rel}](#{ancora})")
    linhas.append("")

    for info in infos:
        rel = info.caminho.relative_to(raiz)
        linhas.append(f"## {rel}\n")

        if info.erro:
            linhas.append(f"⚠️ **{info.erro}**\n")
            continue

        if info.docstring:
            primeira_linha_doc = info.docstring.strip().splitlines()[0]
            linhas.append(f"**Descrição (docstring):** {primeira_linha_doc}\n")

        if info.imports:
            principais = [m for m in info.imports if not m.startswith("_")][:12]
            linhas.append(f"**Principais imports:** `{', '.join(principais)}`\n")

        if info.funcoes:
            linhas.append(f"**Funções definidas:** `{', '.join(info.funcoes)}`" + (" (possui `main()`)" if info.tem_main else "") + "\n")

        linhas.append("**Entradas:**")
        if info.entradas:
            for e in info.entradas:
                linhas.append(f"- {e}")
        else:
            linhas.append("- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._")
        linhas.append("")

        linhas.append("**Saídas:**")
        if info.saidas:
            for s in info.saidas:
                linhas.append(f"- {s}")
        else:
            linhas.append("- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._")
        linhas.append("")

    return "\n".join(linhas)


def main():
    # Sem argumentos: a raiz do repositório é sempre a pasta atual (de onde o
    # script é executado). Basta colocar este arquivo dentro do repositório
    # (ou rodar com o terminal já posicionado nele) e executar:
    #     python3 analisar_io_scripts.py
    raiz = Path.cwd().resolve()

    NOME_MAPA = "AUTO_SERE_MAPA.txt"
    NOME_SAIDA = "RELATORIO_IO.md"

    caminho_mapa = raiz / NOME_MAPA
    mapa_texto = carregar_mapa(caminho_mapa)
    if not mapa_texto:
        print(f"Aviso: arquivo de mapa '{caminho_mapa}' não encontrado ou vazio. Continuando sem ele.", file=sys.stderr)

    scripts = encontrar_scripts(raiz)
    # Não analisa o próprio script de análise nem o relatório gerado
    scripts = [s for s in scripts if s.name != Path(__file__).name]
    if not scripts:
        print(f"Nenhum arquivo .py encontrado em '{raiz}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Encontrados {len(scripts)} scripts .py. Analisando...", file=sys.stderr)
    infos = [analisar_arquivo(caminho) for caminho in scripts]

    relatorio = gerar_relatorio_markdown(raiz, mapa_texto, infos)

    caminho_saida = raiz / NOME_SAIDA
    caminho_saida.write_text(relatorio, encoding="utf-8")

    print(f"Relatório gerado em: {caminho_saida}", file=sys.stderr)


if __name__ == "__main__":
    main()
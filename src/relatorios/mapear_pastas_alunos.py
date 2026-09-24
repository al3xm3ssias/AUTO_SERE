"""
mapear_pastas_alunos.py — Índice fuzzy nome de aluno ↔ pasta de digitalização
=============================================================================

RESUMO ESTRUTURAL (funções principais):
   - normalizar() / normalizar_nome_pasta(): normalização de texto tolerante
     a acentos/pontuação/prefixo numérico de pasta.
   - carregar_turmas(): lê turmas.json, separa matriculados de transferidos.
   - indexar_pastas() / indexar_pastas_transferidos(): varre recursivamente
     a pasta de digitalização coletando as pastas-folha (pastas de aluno).
   - encontrar_pasta(): match exato normalizado, com fallback fuzzy
     (rapidfuzz, se disponível; senão difflib) acima de LIMIAR_SIMILARIDADE.
   - main(): orquestra tudo, gera alunos_pastas.json e nao_encontrados.json.

Portado de AUTO_SERE/mapear_pastas_alunos.py para
src/relatorios/mapear_pastas_alunos.py.

Cruza a lista de alunos de turmas.json com as pastas físicas de
digitalização, produzindo alunos_pastas.json (cada aluno com o caminho da
pasta encontrada e o percentual de similaridade do match) e
nao_encontrados.json (alunos sem pasta correspondente). Trata matriculados
e transferidos separadamente — transferidos são buscados preferencialmente
dentro de subpastas TRANSFERIDOS, com fallback para o índice geral se essas
subpastas não existirem.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. detectar_caminho_base() REMOVIDA — o original detectava o caminho por
   duas fontes (argumento de linha de comando, ou detecção automática por
   SO com CAMINHO_WINDOWS/CAMINHO_LINUX fixos). Decisão do usuário
   (02/09/2026): usar exclusivamente
   src.comum.configuracao.pasta_digitalizacao() — a mesma fonte única já
   usada por todo o projeto (definida pelo usuário no setup inicial), em
   vez de detecção por SO ou argumento de CLI.

2. Caminhos: ARQUIVO_TURMAS, ARQUIVO_SAIDA_ALUNOS, ARQUIVO_NAO_ENCONTRADOS
   (antes relativos, dependiam do diretório de execução) agora vêm de
   src.comum.paths.dados_ano_atual() — mesma arquitetura dos outros
   scripts já portados.

3. main() ajustada para não usar sys.exit() em caso de erro — levanta
   exceção normalmente (FileNotFoundError, ValueError,
   NotADirectoryError), para que quem chamar (outro script, ou uma futura
   GUI) decida como tratar, em vez do processo inteiro terminar.

Toda a lógica de normalização, indexação e matching fuzzy (normalizar,
normalizar_nome_pasta, carregar_turmas, indexar_pastas,
indexar_pastas_transferidos, encontrar_pasta) é idêntica ao original —
nenhuma regra de negócio foi alterada.

Uso:
    from src.relatorios.mapear_pastas_alunos import main
    main()
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

from src.comum import paths as _paths
from src.comum.configuracao import pasta_digitalizacao

# ---------------------------------------------------------------------------
# Tentativa de importar rapidfuzz (preferencial) ou fallback para difflib
# ---------------------------------------------------------------------------
try:
    from rapidfuzz import fuzz as _fuzz

    def similaridade(a: str, b: str) -> float:
        """Retorna 0–100 usando token_sort_ratio (rapidfuzz).
        token_sort_ratio é robusto a palavras fora de ordem."""
        return _fuzz.token_sort_ratio(a, b)

    FUZZY_LIB = "rapidfuzz"
except ImportError:
    import difflib

    def similaridade(a: str, b: str) -> float:
        """Retorna 0–100 usando SequenceMatcher (difflib) — fallback."""
        return difflib.SequenceMatcher(None, a, b).ratio() * 100

    FUZZY_LIB = "difflib"

# ---------------------------------------------------------------------------
# Constantes de configuração
# ---------------------------------------------------------------------------
LIMIAR_SIMILARIDADE = 82  # % mínimo para aceitar um match fuzzy

_DADOS = _paths.dados_ano_atual()

ARQUIVO_TURMAS          = _DADOS / "turmas.json"
ARQUIVO_SAIDA_ALUNOS    = _DADOS / "alunos_pastas.json"
ARQUIVO_NAO_ENCONTRADOS = _DADOS / "nao_encontrados.json"

# Regex que remove prefixo numérico "N - " ou "N. " antes do nome
# Ex.: "1 - ALICE SILVA"  →  "ALICE SILVA"
#      "12. JOAO"          →  "JOAO"
REGEX_PREFIXO_NUMERICO = re.compile(r'^\d+\s*[-–.]\s*')


# ===========================================================================
# 1. NORMALIZAÇÃO
# ===========================================================================

def normalizar(texto: str) -> str:
    """
    Normaliza texto para comparação tolerante:
      1. Remove acentos via decomposição NFD + remoção de combining chars
      2. Converte para maiúsculas
      3. Remove caracteres não alfanuméricos (substitui por espaço)
      4. Colapsa espaços múltiplos
    """
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    limpo = "".join(c if c.isalnum() or c == " " else " " for c in sem_acento)
    return " ".join(limpo.upper().split())


def normalizar_nome_pasta(nome_pasta: str) -> str:
    """
    Normaliza o nome de uma pasta, removendo primeiro o prefixo numérico
    padrão da escola (ex.: "3 - ", "12 - ").
    Depois aplica normalização padrão.
    """
    sem_prefixo = REGEX_PREFIXO_NUMERICO.sub("", nome_pasta.strip())
    return normalizar(sem_prefixo)


# ===========================================================================
# 2. LEITURA DO turmas.json
# ===========================================================================

def carregar_turmas(caminho: Path) -> tuple[list[dict], list[dict]]:
    """
    Lê o turmas.json e retorna dois grupos:

      - matriculados : alunos com Situação != "Transferido"
      - transferidos : alunos com Situação == "Transferido"

    Cada dict contém: {nome, cgm, turma, _norm}
    O campo "_norm" contém o nome normalizado para comparação.

    Lança exceção com mensagem amigável em caso de erro.
    """
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    try:
        with caminho.open(encoding="utf-8") as f:
            dados = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"turmas.json inválido: {e}") from e

    if not isinstance(dados, dict):
        raise ValueError("turmas.json deve ser um objeto JSON com turmas como chaves.")

    matriculados: list[dict] = []
    transferidos: list[dict] = []

    for turma, lista in dados.items():
        if not isinstance(lista, list):
            continue
        for aluno in lista:
            nome     = aluno.get("Nome", "").strip()
            cgm      = str(aluno.get("CGM", "")).strip()
            situacao = aluno.get("Situação", "").strip()
            if not nome:
                continue

            entrada = {
                "nome"  : nome,
                "cgm"   : cgm,
                "turma" : turma,
                "_norm" : normalizar(nome),
            }

            if "transferido" in situacao.lower():
                transferidos.append(entrada)
            else:
                matriculados.append(entrada)

    return matriculados, transferidos


# ===========================================================================
# 3. INDEXAÇÃO DAS PASTAS
# ===========================================================================

def indexar_pastas(raiz: Path) -> list[dict]:
    """
    Percorre recursivamente o diretório raiz e coleta as pastas-folha
    (pastas que não contêm subpastas), correspondendo às pastas individuais
    dos alunos.

    Retorna lista de dicts:
      {pasta: Path, nome_pasta: str, norm: str}
    """
    if not raiz.exists():
        raise FileNotFoundError(f"Diretório base não encontrado: {raiz}")
    if not raiz.is_dir():
        raise NotADirectoryError(f"O caminho não é um diretório: {raiz}")

    index: list[dict] = []
    visitadas: set[Path] = set()

    print(f"\n📂 Varrendo recursivamente: {raiz}")
    total = 0

    try:
        for pasta in raiz.rglob("*"):
            if not pasta.is_dir():
                continue

            try:
                pasta_real = pasta.resolve()
            except OSError:
                continue
            if pasta_real in visitadas:
                continue
            visitadas.add(pasta_real)

            try:
                tem_subpasta = any(p.is_dir() for p in pasta.iterdir())
            except PermissionError:
                print(f"  ⚠ Sem permissão para listar: {pasta}")
                continue
            except OSError as e:
                print(f"  ⚠ Erro ao acessar {pasta}: {e}")
                continue

            if not tem_subpasta:
                index.append({
                    "pasta"     : pasta,
                    "nome_pasta": pasta.name,
                    "norm"      : normalizar_nome_pasta(pasta.name),
                })
                total += 1
                if total % 100 == 0:
                    print(f"  … {total} pastas indexadas")

    except PermissionError as e:
        print(f"  ⚠ Permissão negada na raiz: {e}")

    print(f"  ✔ Total de pastas-folha indexadas: {total}")
    return index


def indexar_pastas_transferidos(caminho_base: Path) -> list[dict]:
    """
    Indexa especificamente as pastas dentro de subdiretórios TRANSFERIDOS.

    Cada turma pode ter uma subpasta "TRANSFERIDOS" com pastas individuais
    dos alunos transferidos. Esta função varre todos os caminhos do padrão:
      <caminho_base>/<turma>/TRANSFERIDOS/<aluno>/

    Retorna lista de dicts:
      {pasta: Path, nome_pasta: str, norm: str, turma_pasta: str}

    O campo "turma_pasta" registra o nome da turma pai para auditoria.
    """
    index: list[dict] = []
    visitadas: set[Path] = set()
    total = 0

    print(f"\n📂 Varrendo pastas TRANSFERIDOS em: {caminho_base}")

    for pasta_transferidos in caminho_base.rglob("TRANSFERIDOS"):
        if not pasta_transferidos.is_dir():
            continue

        turma_pasta = pasta_transferidos.parent.name

        try:
            for subpasta in pasta_transferidos.iterdir():
                if not subpasta.is_dir():
                    continue

                try:
                    real = subpasta.resolve()
                except OSError:
                    continue
                if real in visitadas:
                    continue
                visitadas.add(real)

                index.append({
                    "pasta"      : subpasta,
                    "nome_pasta" : subpasta.name,
                    "norm"       : normalizar_nome_pasta(subpasta.name),
                    "turma_pasta": turma_pasta,
                })
                total += 1

        except (PermissionError, OSError) as e:
            print(f"  ⚠ Erro ao acessar {pasta_transferidos}: {e}")

    print(f"  ✔ Total de pastas de transferidos indexadas: {total}")
    return index


# ===========================================================================
# 4. COMPARAÇÃO / MATCH
# ===========================================================================

def encontrar_pasta(
    nome_norm: str,
    index_pastas: list[dict],
) -> Optional[tuple[dict, float]]:
    """
    Tenta encontrar a pasta correspondente ao aluno em duas etapas:

    1. Exact match (normalizado) → score 100.0
    2. Fuzzy match via token_sort_ratio → retorna se score >= LIMIAR_SIMILARIDADE

    Retorna (dict_pasta, score) ou None.
    """
    for item in index_pastas:
        if item["norm"] == nome_norm:
            return item, 100.0

    melhor_score = 0.0
    melhor_item  = None
    for item in index_pastas:
        score = similaridade(nome_norm, item["norm"])
        if score > melhor_score:
            melhor_score = score
            melhor_item  = item

    if melhor_score >= LIMIAR_SIMILARIDADE and melhor_item is not None:
        return melhor_item, melhor_score

    return None


# ===========================================================================
# 5. EXPORTAÇÃO DOS RESULTADOS
# ===========================================================================

def exportar_json(dados: list[dict], caminho: Path) -> None:
    """Salva uma lista de dicts como JSON UTF-8 indentado."""
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        print(f"  💾 Salvo: {caminho}  ({len(dados)} registros)")
    except OSError as e:
        print(f"  ❌ Erro ao salvar {caminho}: {e}")


def formatar_caminho_saida(pasta: Path) -> str:
    """
    Retorna o caminho em formato Windows (barras invertidas),
    mantendo consistência com o padrão de saída esperado.
    """
    return str(pasta).replace("/", "\\")


# ===========================================================================
# 6. FLUXO PRINCIPAL
# ===========================================================================

def main() -> dict:
    """
    Cruza turmas.json com a pasta de digitalização configurada pelo
    usuário (src.comum.configuracao.pasta_digitalizacao), gera
    alunos_pastas.json e nao_encontrados.json.

    Levanta FileNotFoundError/ValueError/NotADirectoryError em caso de
    erro (em vez de sys.exit(), como no original) — quem chamar decide
    como tratar. Retorna um resumo (dict) com as contagens finais.
    """
    inicio = time.perf_counter()

    print("=" * 62)
    print("  MAPEAMENTO DE PASTAS DE ALUNOS")
    print("=" * 62)
    print(f"  Biblioteca fuzzy : {FUZZY_LIB}")
    print(f"  Limiar            : {LIMIAR_SIMILARIDADE}%")

    # ------------------------------------------------------------------
    # 6.1 Resolve a pasta de digitalização configurada pelo usuário
    # ------------------------------------------------------------------
    caminho_base = pasta_digitalizacao()
    if caminho_base is None:
        raise FileNotFoundError(
            "A pasta de digitalização ainda não foi configurada "
            "(ver src.comum.configuracao.pasta_digitalizacao). "
            "Rode o setup inicial antes de mapear as pastas."
        )

    # ------------------------------------------------------------------
    # 6.2 Carrega turmas.json — já separado em matriculados e transferidos
    # ------------------------------------------------------------------
    print(f"\n📄 Lendo {ARQUIVO_TURMAS} …")
    matriculados, transferidos = carregar_turmas(ARQUIVO_TURMAS)

    turmas_unicas = len(set(a["turma"] for a in matriculados + transferidos))
    print(f"  ✔ {len(matriculados)} matriculados | {len(transferidos)} transferidos | {turmas_unicas} turmas")

    # ------------------------------------------------------------------
    # 6.3 Indexa pastas — alunos regulares e transferidos separadamente
    # ------------------------------------------------------------------
    index_pastas = indexar_pastas(caminho_base)

    if not index_pastas:
        print("\n⚠ Nenhuma pasta-folha encontrada. Verifique o diretório.")
        return {"erro": "nenhuma_pasta_encontrada"}

    # Indexação das pastas TRANSFERIDOS (não-fatal se não existirem)
    index_transferidos: list[dict] = []
    try:
        index_transferidos = indexar_pastas_transferidos(caminho_base)
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"  ⚠ Pastas TRANSFERIDOS não encontradas ou inacessíveis: {e}")

    # ------------------------------------------------------------------
    # 6.4 Cruzamento: matriculados × pastas regulares
    # ------------------------------------------------------------------
    print(f"\n🔍 Cruzando {len(matriculados)} matriculados × {len(index_pastas)} pastas …")

    encontrados    : list[dict] = []
    nao_encontrados: list[dict] = []
    cgms_vistos    : set[str]   = set()
    matches_fuzzy  : int        = 0

    for i, aluno in enumerate(matriculados, 1):
        cgm = aluno["cgm"]

        if cgm in cgms_vistos:
            print(f"  ⚠ CGM duplicado ignorado: {cgm} ({aluno['nome']})")
            continue
        cgms_vistos.add(cgm)

        if i % 50 == 0 or i == len(matriculados):
            print(f"  … {i}/{len(matriculados)} alunos processados")

        resultado = encontrar_pasta(aluno["_norm"], index_pastas)

        if resultado is not None:
            item, score = resultado
            if score < 100.0:
                matches_fuzzy += 1
            encontrados.append({
                "nome"            : aluno["nome"],
                "cgm"             : cgm,
                "turma"           : aluno["turma"],
                "transferido"     : False,
                "pasta"           : formatar_caminho_saida(item["pasta"]),
                "similaridade_pct": round(score, 1),
            })
        else:
            nao_encontrados.append({
                "nome" : aluno["nome"],
                "cgm"  : cgm,
                "turma": aluno["turma"],
            })

    # ------------------------------------------------------------------
    # 6.5 Cruzamento: transferidos × pastas TRANSFERIDOS
    #     Fallback: se não houver pasta TRANSFERIDOS, busca no índice geral
    # ------------------------------------------------------------------
    print(f"\n🔍 Cruzando {len(transferidos)} transferidos …")

    resultado_transferidos : list[dict] = []
    transferidos_nao_encontrados: list[dict] = []
    matches_fuzzy_transf   : int = 0

    # Escolhe o índice preferencial: pastas TRANSFERIDOS; fallback: geral
    usar_indice_transf = index_transferidos if index_transferidos else index_pastas
    fonte_indice = "TRANSFERIDOS" if index_transferidos else "geral (fallback)"
    print(f"  ↳ Índice utilizado: {fonte_indice} ({len(usar_indice_transf)} pastas)")

    for aluno in transferidos:
        cgm = aluno["cgm"]

        if cgm in cgms_vistos:
            print(f"  ⚠ CGM duplicado ignorado: {cgm} ({aluno['nome']})")
            continue
        cgms_vistos.add(cgm)

        resultado = encontrar_pasta(aluno["_norm"], usar_indice_transf)

        if resultado is not None:
            item, score = resultado
            if score < 100.0:
                matches_fuzzy_transf += 1
            entrada = {
                "nome"            : aluno["nome"],
                "cgm"             : cgm,
                "turma"           : aluno["turma"],
                "transferido"     : True,
                "pasta"           : formatar_caminho_saida(item["pasta"]),
                "similaridade_pct": round(score, 1),
            }
            if "turma_pasta" in item:
                entrada["turma_pasta"] = item["turma_pasta"]
            encontrados.append(entrada)
        else:
            transferidos_nao_encontrados.append({
                "nome" : aluno["nome"],
                "cgm"  : cgm,
                "turma": aluno["turma"],
            })

    # ------------------------------------------------------------------
    # 6.6 Exporta resultados
    # ------------------------------------------------------------------
    print("\n💾 Exportando resultados …")
    exportar_json(encontrados, ARQUIVO_SAIDA_ALUNOS)

    todos_nao_encontrados = nao_encontrados + transferidos_nao_encontrados
    exportar_json(todos_nao_encontrados, ARQUIVO_NAO_ENCONTRADOS)

    # ------------------------------------------------------------------
    # 6.7 Resumo final
    # ------------------------------------------------------------------
    duracao = time.perf_counter() - inicio
    total   = len(cgms_vistos)

    encontrados_transf = [e for e in encontrados if e.get("transferido")]
    encontrados_matr   = [e for e in encontrados if not e.get("transferido")]

    print("\n" + "=" * 62)
    print("  RESUMO FINAL")
    print("=" * 62)
    print(f"  Total de alunos processados  : {total}")
    print(f"  ── Matriculados ─────────────────────────────")
    print(f"  ✅ Encontrados               : {len(encontrados_matr)}")
    print(f"     ↳ Matches exatos          : {len(encontrados_matr) - matches_fuzzy}")
    print(f"     ↳ Matches fuzzy           : {matches_fuzzy}")
    print(f"  ❌ Não encontrados           : {len(nao_encontrados)}")
    print(f"  ── Transferidos ─────────────────────────────")
    print(f"  ✅ Encontrados               : {len(encontrados_transf)}")
    print(f"     ↳ Matches exatos          : {len(encontrados_transf) - matches_fuzzy_transf}")
    print(f"     ↳ Matches fuzzy           : {matches_fuzzy_transf}")
    print(f"     ↳ Índice usado            : {fonte_indice}")
    print(f"  ❌ Não encontrados           : {len(transferidos_nao_encontrados)}")
    print(f"  ─────────────────────────────────────────────")
    print(f"  ⏱  Tempo de execução         : {duracao:.2f}s")
    print("=" * 62)

    if todos_nao_encontrados:
        print(f"\n⚠ Alunos sem pasta — veja: {ARQUIVO_NAO_ENCONTRADOS}")
        for a in todos_nao_encontrados[:5]:
            print(f"   • {a['nome']} ({a['turma']})")
        if len(todos_nao_encontrados) > 5:
            print(f"   … e mais {len(todos_nao_encontrados) - 5} outros.")

    return {
        "total": total,
        "matriculados_encontrados": len(encontrados_matr),
        "matriculados_nao_encontrados": len(nao_encontrados),
        "transferidos_encontrados": len(encontrados_transf),
        "transferidos_nao_encontrados": len(transferidos_nao_encontrados),
        "duracao_s": round(duracao, 2),
    }


if __name__ == "__main__":
    main()

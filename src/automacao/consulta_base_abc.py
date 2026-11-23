"""
consulta_base_abc.py — "Consulta Aluno na Base ABC" do SERE: de que escolas o aluno veio
═══════════════════════════════════════════════════════════════════════════════════════════
Adaptação do script antigo consulta_transferidos_ano_anterior.py. Para cada aluno consultado, abre o cadastro na Base ABC, lê
o histórico escolar e grava, em  dados/<ano>/buscas_base.json  (uma lista, um registro por aluno):

    {"data_busca": "08/11/2026 14:30", "nome": "...", "possui_cgm": true, "cgm": "...",
     "data_nascimento": "12/03/2015", "nome_mae": "...",
     "escolas": {"1": {"ano","municipio","escola","curso","serie","resultado","turma"}, "2": {...}},   (todas as linhas do histórico; a "1" é a escola ATUAL: no ano mais novo, a linha "Matriculado"; sem ela, a última linha do ano; "turma" = equivalente da pré-matrícula, ex. EDUC INFANTIL série 5 = Infantil V)
     "situacao": "encontrado" | "nao_encontrado" | "ambiguo" | "erro",
     "conferido_por": "nome + data de nascimento + nome da mãe" | "nome + data de nascimento" | "nome + nome da mãe" |
                      "nome + responsável (= mãe)" | "CGM" | "só o nome",
     "observacao": "...",                    o motivo, quando não é "encontrado"
     "encontrados_parecidos": [...],         o que a Base ABC mostrou e NÃO foi aceito (outra data/mãe) ou os candidatos do ambíguo
     "pedido": {"nome", "data_nascimento", "nome_mae", "cgm", "responsavel", "origem"}}   o que foi pedido (origem: "digitado" ou "pre_matricula")

Vínculo (campo "vinculo", só de quem foi encontrado): amarra o CGM ao aluno e à turma/escola DE ONDE ELE VEM, a linha do histórico
do ano letivo vigente (dados/<ano>):
    {"periodo": "ano_vigente" | "pre_matricula", "ano_referencia": 2026, "nome", "cgm", "turma", "escola",
     "situacao": "Matriculado" | "Transferido" | "Desistente" | "Reprovado" | (o que o SERE mostrou),
     "status": "ok" | "verificar", "motivo": "..."}                      (motivo só quando status = "verificar")
  • ano letivo vigente (consulta digitada): situações aceitas Matriculado / Transferido;
  • período de pré-matrícula do ano seguinte (consulta vinda da pré-matrícula): Matriculado / Transferido / Desistente / Reprovado;
  • qualquer outra situação, ano sem linha no histórico, mais de uma matrícula em curso ou aluno sem CGM CONFLITA: o vínculo é
    gravado mesmo assim, com status "verificar" e o motivo, para conferir à mão. As listas estão em SITUACOES_VINCULO.

Aluno que não está na Base ABC NÃO é erro: o registro sai com o que foi pedido, possui_cgm false, escolas vazia e o que
tiver sido achado de parecido. Um registro "encontrado" nunca é substituído por um "nao_encontrado"/"erro" de uma busca
posterior (ela só aparece no resumo).

Como o aluno é indicado — uma linha por aluno (a ordem dos dados não importa quando há rótulo):

    Claudio Alex Mendes de Souza 12/03/2015 mãe: Maria Aparecida de Souza
    Claudio Alex Mendes de Souza; 12/03/2015; Maria Aparecida de Souza        (campos separados por ; | ou tab: nome; data; mãe)
    1025059227                                                                CGM (como no script antigo)
    1025059227 Claudio Alex 12/03/2015                                        os dois (o cadastro achado precisa bater)

Lista vinda da pré-matrícula (opcional, na tela): lê dados/<ano>/pre_matricula.json (cadastros: nome do aluno, DATA DE
NASCIMENTO e nome do responsável) e consulta quem você escolher (matriculados, aguardando…). A data de nascimento é a
chave que separa homônimos (na prática bate em ~98% dos casos). O responsável (geralmente a mãe) ajuda a desempatar quando
o nome dele é o da mãe no cadastro da Base ABC; nunca derruba um candidato, porque pode ser o pai. Cadastros antigos, coletados
antes de a pré-matrícula guardar a data, entram só com nome + responsável (busca mais fraca). O registro diz em
"conferido_por" como o aluno foi confirmado ("só o nome" é o mais fraco: confira esses).

Homônimos — a data de nascimento e o nome da mãe é que separam um aluno do outro:
  • o nome vale por palavras (acentos e maiúsculas não importam; "CLAU" vale para "CLAUDIO");
  • entre os de mesmo nome, só fica quem tem a mesma data de nascimento E o mesmo nome da mãe, quando esses dados foram
    informados e o SERE os mostra (se o cadastro não mostra o dado, ele não derruba o candidato);
  • sobrou mais de um → NÃO escolhe: registra "ambiguo" com os candidatos. Informe a mãe ou a data para separar.
  • a tabela de resultados traz CGM, Nome, Nome da Mãe e Data Nasc.: são lidos pelo cabeçalho e já descartam quem tem outra
    data ou outra mãe; entre os que sobram, se só um tem o nome IGUAL ao pedido, é ele;
  • se a tabela de resultados não mostra a data, abre o cadastro de cada candidato da tabela (todos os que aparecem na página, sem limite) e confere lá;
  • a busca começa só com o NOME COMPLETO; se não achar o aluno OU se achar homônimos que a tabela/cadastro não separam
    (ambíguo), repete com o nome completo + a DATA DE NASCIMENTO no formulário (quando a data foi informada) e, depois,
    com o nome encurtado (tirando uma palavra do fim de cada vez até as duas primeiras: "João Maria dos Santos" →
    "João Maria") e primeiro + último nome, sempre com a data. A mãe não vai para o formulário (a Base ABC não tem esse
    campo): é conferida no cadastro (e, na tabela, quando ela mostra a coluna).

Formulário da Base ABC (conferido no HTML da tela): campos cgm, nome e dataNasc (mascarados dd/mm/aaaa) e os botões
"Pesquisar ABC" e "Pesquisar SERE"; a tabela de resultados é list_tabela (CGM | Nome | Nome da Mãe | Data Nasc.). Os nomes
tentados ficam em CAMPOS_NOME / CAMPOS_NASCIMENTO / CAMPOS_MAE e os rótulos do cadastro em ROTULOS_*. Se o campo Nome não
for achado, a execução PARA com a lista dos campos que existem na página, para ajustar as constantes.
Nada aqui grava no SERE: só lê e escreve o arquivo local.
═══════════════════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
import unicodedata
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

from src.comum import paths
from src.comum import previsao as _previsao
from src.comum.arquivos_json import carregar_json, salvar_json_atomico
from src.comum import navegador as _navegador

ARQUIVO_PRE_ATUAL = "pre_matricula.json"      # alvo "atual" da coleta (ano vigente); o do próximo ano é previsao_alunos_<ano+1>.json
NOME_ARQUIVO = "buscas_base.json"
CAMPOS_REGISTRO = ("ano", "municipio", "escola", "curso", "serie", "resultado")   # colunas da tabela de histórico do SERE

# Nomes tentados no formulário da Base ABC (id ou name). Ajustar aqui se o SERE usar outros.
CAMPOS_CGM = ("cgm",)
CAMPOS_NOME = ("nome", "nomeAluno", "nome_aluno", "txtNome", "nmAluno", "aluno")
CAMPOS_NASCIMENTO = ("dataNascimento", "data_nascimento", "dtNascimento", "dt_nascimento", "nascimento", "dataNasc", "dtNasc")
CAMPOS_MAE = ("nomeMae", "nome_mae", "mae", "nomeMãe", "nmMae", "filiacao", "nomeFiliacao")
ROTULOS_NOME = ("Nome",)
ROTULOS_NASCIMENTO = ("Data de Nascimento", "Data Nascimento", "Nascimento", "Dt. Nascimento")
ROTULOS_MAE = ("Nome da Mãe", "Nome da Mae", "Mãe", "Mae", "Filiação 1", "Filiação")

_RE_DATA = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)")
_RE_CGM_SOZINHO = re.compile(r"(?i)^\s*(?:cgm\s*[:\-]?\s*)?(\d{8,12})\s*$")
_RE_CGM_NA_LINHA = re.compile(r"(?<![\d/.\-])\d{8,12}(?![\d/.\-])")
_RE_MAE = re.compile(r"(?i)\b(?:nome\s+da\s+m[aã]e|m[aã]e|filia[cç][aã]o)\b\s*[:\-]?\s*")
# Rótulos de campo a tirar do nome. "nascimento", "nasc.", "d.n." e "nome" só valem com os dois-pontos ("Nasc.: 12/03/2015"),
# porque também podem ser sobrenome ("João Maria dos Santos Nascimento").
_PALAVRAS_DE_ROTULO = re.compile(r"(?i)\b(?:data\s+de\s+nascimento|data\s+nasc\.?|cgm)\b\s*[:\-]?"
                                 r"|\b(?:nascimento|nasc\.?|d\.?n\.?|nome)\s*:\s*")


class FormularioDesconhecido(RuntimeError):
    """Não foi possível achar um campo do formulário da Base ABC; a mensagem lista o que existe na página."""


# ───────────────────────────── entrada: nome + data de nascimento + nome da mãe ─────────────────────────────

def normalizar(texto) -> str:
    """MAIÚSCULAS, sem acentos nem pontuação, espaços únicos: para comparar nomes."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9\s]", " ", t)).upper().strip()


def parse_data(texto) -> Optional[date]:
    """dd/mm/aaaa (também com - ou .). None se não há data; ValueError se há mas não existe (31/02/2015)."""
    m = _RE_DATA.search(str(texto or ""))
    if not m:
        return None
    dia, mes, ano = (int(g) for g in m.groups())
    try:
        return date(ano, mes, dia)
    except ValueError as exc:
        raise ValueError(f"data de nascimento inválida: {m.group(0)}") from exc


def formatar_data(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _limpar_nome(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[;,|\t]+", " ", texto)).strip(" -–—:.")


@dataclass(frozen=True)
class Consulta:
    nome: str = ""
    nascimento: Optional[date] = None
    cgm: str = ""
    mae: str = ""
    responsavel: str = ""                 # só vem da pré-matrícula: pode ser a mãe, o pai ou outro; ajuda a desempatar, nunca filtra
    origem: str = "digitado"              # "digitado" | "pre_matricula"
    # Onde gravar o vínculo de volta (só pré-matrícula): (arquivo, "cadastros"|"turmas_intencao", chave, turma, periodo).
    # Fora do repr/rótulo/comparação: a chave é o CPF, que não pode aparecer em log nem entrar na deduplicação.
    destinos: tuple = field(default=(), repr=False, compare=False)
    # ID da matrícula (ponte turmas_relacional.json) do período que originou a consulta; hoje só os transferidos o têm (o ID
    # da SAÍDA). Vai no vínculo e no registro e protege a gravação: se o registro de origem já é de OUTRA saída, nada é gravado.
    id_matricula: str = field(default="", repr=False, compare=False)

    @property
    def rotulo(self) -> str:
        partes = [self.cgm] if self.cgm else []
        if self.nome:
            partes.append(self.nome)
        if self.nascimento:
            partes.append(formatar_data(self.nascimento))
        if self.mae:
            partes.append(f"(mãe: {self.mae})")
        if self.responsavel:
            partes.append(f"(responsável: {self.responsavel})")
        return " ".join(partes)

    @property
    def chave(self) -> tuple:
        return (self.cgm, normalizar(self.nome), self.nascimento, normalizar(self.mae), normalizar(self.responsavel))


def _validar_consulta(c: Consulta) -> Consulta:
    if not c.cgm:
        if len(c.nome.split()) < 2:
            raise ValueError("escreva o nome e pelo menos um sobrenome (ou o CGM)")
        if c.nascimento is None and not c.mae:
            raise ValueError("faltou a data de nascimento (dd/mm/aaaa) ou o nome da mãe depois do nome")
    return c


def _de_campos(campos: list[str]) -> Consulta:
    """Linha de planilha: campos separados por ; | ou tab. Data e CGM são reconhecidos pelo formato; o 1º texto é o nome
    do aluno e o 2º é o da mãe (ou o que vier depois do rótulo "mãe:")."""
    nascimento, cgm, textos, mae = None, "", [], ""
    for campo in campos:
        campo = campo.strip()
        if not campo:
            continue
        achou_mae = _RE_MAE.match(campo)
        if achou_mae:
            mae = _limpar_nome(campo[achou_mae.end():])
        elif _RE_DATA.search(campo):
            nascimento = parse_data(campo)
        elif _RE_CGM_SOZINHO.match(campo):
            cgm = _RE_CGM_SOZINHO.match(campo).group(1)
        else:
            textos.append(_limpar_nome(_PALAVRAS_DE_ROTULO.sub(" ", campo)))
    nome = textos[0] if textos else ""
    if not mae and len(textos) > 1:
        mae = textos[1]
    return Consulta(nome=nome, nascimento=nascimento, cgm=cgm, mae=mae)


def interpretar_linha(linha: str) -> Consulta:
    """Uma linha → Consulta. ValueError com a mensagem pronta se faltar algo."""
    texto = str(linha or "").strip().strip("•·*").strip()
    texto = re.sub(r"^\d{1,3}\s*[).]\s+(?=\D)", "", texto)                 # "3) Fulano…": numeração de lista
    if not texto:
        raise ValueError("linha vazia")
    so_cgm = _RE_CGM_SOZINHO.match(texto)
    if so_cgm:
        return Consulta(cgm=so_cgm.group(1))
    if re.search(r"[;|\t]", texto):
        return _validar_consulta(_de_campos(re.split(r"[;|\t]", texto)))

    nascimento = None
    ocorrencias = list(_RE_DATA.finditer(texto))
    if ocorrencias:
        nascimento = parse_data(ocorrencias[-1].group(0))
        texto = texto[:ocorrencias[-1].start()] + " " + texto[ocorrencias[-1].end():]
    mae = ""
    marcador = _RE_MAE.search(texto)
    if marcador:
        mae = _limpar_nome(texto[marcador.end():])
        texto = texto[:marcador.start()]
    cgm = ""
    achado = _RE_CGM_NA_LINHA.search(texto)
    if achado:
        cgm = achado.group(0)
        texto = texto[:achado.start()] + " " + texto[achado.end():]
    nome = _limpar_nome(_PALAVRAS_DE_ROTULO.sub(" ", texto))
    if cgm and not nome and nascimento is None and not mae:
        return Consulta(cgm=cgm)
    return _validar_consulta(Consulta(nome=nome, nascimento=nascimento, cgm=cgm, mae=mae))


def interpretar_texto(texto: str) -> tuple[list[Consulta], list[tuple[str, str]]]:
    """Várias linhas → (consultas sem repetição, [(linha, motivo)] das que não deram para entender)."""
    consultas, erros, vistas = [], [], set()
    for bruta in str(texto or "").splitlines():
        if not bruta.strip():
            continue
        try:
            c = interpretar_linha(bruta)
        except ValueError as exc:
            erros.append((bruta.strip(), str(exc)))
            continue
        if c.chave not in vistas:
            vistas.add(c.chave)
            consultas.append(c)
    return consultas, erros


def consultas_do_arquivo(caminho: Path) -> list[Consulta]:
    """
    Lista do formato do script antigo (transferidos-<ano anterior>.json): {"alunos": [{"CGM","Nome"}]}, ou lista simples de
    CGMs / de objetos. Aceita também "Nascimento"/"DataNascimento" e "Mae"/"NomeMae" quando o arquivo tiver.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de entrada não encontrado: {caminho}")
    bruto = carregar_json(caminho, list)
    itens = bruto.get("alunos", []) if isinstance(bruto, dict) else bruto if isinstance(bruto, list) else []
    saida, vistos = [], set()
    for item in itens:
        if isinstance(item, str):
            cgm, nome, nasc, mae = item.strip(), "", None, ""
        elif isinstance(item, dict):
            cgm = str(item.get("CGM") or item.get("cgm") or "").strip()
            nome = str(item.get("Nome") or item.get("nome") or "").strip()
            mae = str(item.get("Mae") or item.get("Mãe") or item.get("NomeMae") or item.get("nome_mae") or "").strip()
            try:
                nasc = parse_data(item.get("Nascimento") or item.get("DataNascimento") or item.get("nascimento") or "")
            except ValueError:
                nasc = None
        else:
            continue
        if not cgm and not (nome and (nasc or mae)):
            continue
        c = Consulta(nome=nome, nascimento=nasc, cgm=cgm, mae=mae)
        if c.chave not in vistos:
            vistos.add(c.chave)
            saida.append(c)
    return saida


# ───────────────────────────── lista vinda da pré-matrícula ─────────────────────────────

SITUACOES_PRE_MATRICULA = {
    "matriculados": ("matriculado",),
    "pendentes": ("pendente",),
    "matriculados_e_pendentes": ("matriculado", "pendente"),
    "todos": ("matriculado", "pendente", "cancelado"),
}


def _situacao_pre_matricula(opcoes: list) -> str:
    """Mesma regra da tela de cadastros: matriculado = alguma opção com situação que não seja cancelada; cancelado = todas
    as opções preenchidas canceladas; sem situação = pendente."""
    com_situacao = [o for o in opcoes if isinstance(o, dict) and str(o.get("situacao") or "").strip()]
    if not com_situacao:
        return "pendente"
    if any(not str(o["situacao"]).upper().startswith("CANCELADO") for o in com_situacao):
        return "matriculado"
    return "cancelado"


def consultas_da_pre_matricula(dados: dict, quais: str = "matriculados", arquivo: str = ARQUIVO_PRE_ATUAL,
                               periodo: Optional[str] = None) -> list[Consulta]:
    """
    Alunos do pre_matricula.json (cadastros por CPF; quem só está na fila, sem cadastro, entra só com o nome) cuja situação
    está em `quais` ("matriculados", "pendentes", "matriculados_e_pendentes", "todos"). Só o nome do aluno, a data de nascimento
    e o nome do responsável são usados: CPF, telefone e e-mail não saem do arquivo da pré-matrícula.
    Cada consulta leva em `destinos` o lugar de `arquivo` onde o vínculo será gravado de volta.
    """
    periodo = periodo or (PERIODO_ANO_VIGENTE if arquivo == ARQUIVO_PRE_ATUAL else PERIODO_PRE_MATRICULA)
    if quais not in SITUACOES_PRE_MATRICULA:
        raise ValueError(f"Opção de pré-matrícula inválida: '{quais}'. Use: {', '.join(SITUACOES_PRE_MATRICULA)}.")
    aceitas = SITUACOES_PRE_MATRICULA[quais]
    dados = dados if isinstance(dados, dict) else {}
    cadastros = dados.get("cadastros") if isinstance(dados.get("cadastros"), dict) else {}
    saida, vistos, com_cadastro = [], {}, set()

    def juntar(nome: str, responsavel: str, nascimento: Any = None, destino: tuple = (), mae: Any = "") -> None:
        nome = re.sub(r"\s+", " ", str(nome or "")).strip()
        if len(nome.split()) < 2:
            return                                          # só um nome: homônimos demais para procurar
        try:
            nasc = parse_data(nascimento)                   # cadastro antigo não tem a data: None
        except ValueError:
            nasc = None                                     # data impossível (31/02): busca sem ela
        c = Consulta(nome=nome, nascimento=nasc, mae=re.sub(r"\s+", " ", str(mae or "")).strip(),
                     responsavel=re.sub(r"\s+", " ", str(responsavel or "")).strip(),
                     origem="pre_matricula", destinos=(destino,) if destino else ())
        if c.chave not in vistos:
            vistos[c.chave] = len(saida)
            saida.append(c)
        elif destino:                                       # mesma pessoa duas vezes: uma busca só, gravando nos dois lugares
            i = vistos[c.chave]
            saida[i] = replace(saida[i], destinos=saida[i].destinos + (destino,))

    for cid, c in cadastros.items():
        if not isinstance(c, dict):
            continue
        com_cadastro.update({str(cid), str(c.get("cpf") or ""), str(c.get("tr_id") or "")} - {""})
        escolhas = c.get("escolas_escolhidas") if isinstance(c.get("escolas_escolhidas"), dict) else {}
        opcoes = [o for o in (escolhas.get("opcoes") or []) if isinstance(o, dict)]
        if _situacao_pre_matricula(opcoes) in aceitas:
            juntar(c.get("nome_aluno"), c.get("nome_responsavel"), c.get("data_nascimento"),
                   (arquivo, "cadastros", str(cid), "", periodo), mae=c.get("nome_mae"))
    if "pendente" in aceitas:                                # quem está na fila e ainda não tem cadastro coletado
        turmas = dados.get("turmas_intencao") if isinstance(dados.get("turmas_intencao"), dict) else {}
        for turma, lista in turmas.items():
            for item in lista if isinstance(lista, list) else []:
                if not isinstance(item, dict) or item.get("substituido_por_nova_tentativa"):
                    continue
                if {str(item.get("cpf") or ""), str(item.get("tr_id") or "")} - {""} & com_cadastro:
                    continue
                if str(item.get("situacao") or "").strip():
                    continue
                chave_item = str(item.get("cpf") or item.get("tr_id") or item.get("nome") or "").strip()
                juntar(item.get("nome"), "", None, (arquivo, "turmas_intencao", chave_item, str(turma), periodo))
    return saida


def _mesclar_consultas(listas: list[list[Consulta]]) -> list[Consulta]:
    """Junta as consultas de vários arquivos sem repetir a pessoa; os destinos de quem aparece em mais de um se somam."""
    saida, onde = [], {}
    for lista in listas:
        for c in lista:
            if c.chave in onde:
                i = onde[c.chave]
                saida[i] = replace(saida[i], destinos=saida[i].destinos + c.destinos)
            else:
                onde[c.chave] = len(saida)
                saida.append(c)
    return saida


def _pasta_e_ano(ano: Optional[str]) -> tuple[Path, int]:
    return ((paths.DADOS_DIR / str(ano)) if ano else paths.dados_ano_atual()), int(ano or paths.ano_atual())


def consultas_da_pre_matricula_arquivo(quais: str = "matriculados", ano: Optional[str] = None) -> list[Consulta]:
    """
    Lê dados/<ano>/pre_matricula.json (alvo "atual": regra do ano vigente) e dados/<ano>/previsao_alunos_<ano+1>.json (alvo
    "proximo": regra de pré-matrícula do ano seguinte; um pre_matricula_<ano+1>.json de antes é renomeado antes de ler).
    Basta um dos dois existir. ValueError com a mensagem pronta se nenhum existe ou se algum não pode ser lido.
    """
    pasta, ano_n = _pasta_e_ano(ano)
    _previsao.migrar_nome_antigo(pasta, ano_n + 1)
    listas = []
    for nome_arq in (ARQUIVO_PRE_ATUAL, _previsao.nome_arquivo(ano_n + 1)):
        caminho = pasta / nome_arq
        if not caminho.exists():
            continue
        try:
            dados = carregar_json(caminho, dict, dict)
        except Exception as exc:                             # noqa: BLE001 — arquivo ilegível: a mensagem diz qual
            raise ValueError(f"Não foi possível ler {caminho.name}: {exc}") from exc
        listas.append(consultas_da_pre_matricula(dados, quais, arquivo=nome_arq))
    if not listas:
        raise ValueError(f"Não há pre_matricula.json em {pasta}. Rode antes a coleta da pré-matrícula.")
    return _mesclar_consultas(listas)


ARQUIVO_TRANSFERIDOS = "transferidos.json"


def consultas_dos_transferidos(dados: dict, arquivo: str = ARQUIVO_TRANSFERIDOS) -> list[Consulta]:
    """
    Alunos de transferidos.json ({CGM: registro}) que ainda estão fora da escola (quem voltou, `retorno` preenchido, fica de
    fora). Busca pelo CGM, que é a chave do arquivo; nome e data de nascimento só acompanham o rótulo. O vínculo (escola
    para onde foi, situação) volta gravado no próprio registro, em "vinculo_base_abc". Regra do ano letivo vigente.
    """
    saida = []
    for cgm, reg in (dados if isinstance(dados, dict) else {}).items():
        if not isinstance(reg, dict) or reg.get("retorno") or not re.fullmatch(r"\d{8,12}", str(cgm).strip()):
            continue
        try:
            nasc = parse_data(reg.get("data_nascimento"))
        except ValueError:
            nasc = None
        saida.append(Consulta(nome=re.sub(r"\s+", " ", str(reg.get("nome") or "")).strip(), nascimento=nasc, cgm=str(cgm).strip(),
                              origem="transferidos", id_matricula=str(reg.get("id_matricula") or ""),
                              destinos=((arquivo, "transferidos", str(cgm).strip(), "", PERIODO_ANO_VIGENTE),)))
    return saida


def consultas_dos_transferidos_arquivo(ano: Optional[str] = None) -> list[Consulta]:
    """Lê dados/<ano>/transferidos.json. ValueError com a mensagem pronta se não existe, não lê ou ninguém precisa consultar."""
    pasta, _ = _pasta_e_ano(ano)
    caminho = pasta / ARQUIVO_TRANSFERIDOS
    if not caminho.exists():
        raise ValueError(f"Não há {ARQUIVO_TRANSFERIDOS} em {pasta}. Rode antes a coleta de turmas.")
    try:
        dados = carregar_json(caminho, dict, dict)
    except Exception as exc:                                 # noqa: BLE001
        raise ValueError(f"Não foi possível ler {caminho.name}: {exc}") from exc
    consultas = consultas_dos_transferidos(dados)
    if not consultas:
        raise ValueError(f"{caminho.name} não tem nenhum transferido com CGM que ainda esteja fora da escola.")
    return consultas


def gravar_vinculos_pre_matricula(vinculos: list, ano: Optional[str] = None,
                                  log: Callable[[str], None] = print, gravados_out: Optional[set] = None) -> int:
    """
    Grava cada vínculo de volta no arquivo da pré-matrícula de onde o aluno veio, na chave "vinculo_base_abc":
    cadastros[cpf] (quem tem cadastro) ou o item da turma em turmas_intencao (quem só está na fila). `vinculos` = lista de
    (destino, vinculo). Uma leitura e uma gravação atômica por arquivo, no fim da rodada (janela mínima contra a coleta);
    arquivo ilegível nunca é sobrescrito; nada além de "vinculo_base_abc" é tocado (nem "atualizado_em"). Devolve quantos gravou.
    """
    pasta, _ = _pasta_e_ano(ano)
    por_arquivo: dict[str, list] = {}
    for destino, vinculo in vinculos:
        por_arquivo.setdefault(destino[0], []).append((destino, vinculo))
    gravados = 0
    agora = datetime.now().isoformat(timespec="seconds")
    for nome_arq, itens in por_arquivo.items():
        caminho = pasta / nome_arq
        try:
            dados = carregar_json(caminho, dict, dict)
        except Exception as exc:                             # noqa: BLE001 — ilegível ou sumiu: não escreve por cima
            log(f"    ⚠️  Vínculos não gravados em {nome_arq}: {exc}")
            continue
        n = 0
        candidatos: set = set()
        for (_, secao, chave, turma, _periodo), vinculo in itens:
            alvo = None
            if secao == "transferidos":                      # transferidos.json é {CGM: registro}, sem seção
                alvo = dados.get(chave)
                esperado = str(vinculo.get("id_matricula") or "")
                if isinstance(alvo, dict) and esperado and alvo.get("id_matricula") and str(alvo["id_matricula"]) != esperado:
                    log("    ⚠️  Vínculo de um transferido não gravado: o registro dele já é de OUTRA saída (o aluno saiu de novo "
                        "depois que a consulta começou). Consulte de novo.")
                    alvo = None
            elif secao == "cadastros":
                alvo = (dados.get("cadastros") or {}).get(chave)
            else:
                lista = (dados.get("turmas_intencao") or {}).get(turma)
                for item in lista if isinstance(lista, list) else []:
                    if isinstance(item, dict) and not item.get("substituido_por_nova_tentativa") \
                            and chave in {str(item.get("cpf") or ""), str(item.get("tr_id") or ""), str(item.get("nome") or "")}:
                        alvo = item
            if isinstance(alvo, dict):
                alvo["vinculo_base_abc"] = {**vinculo, "consultado_em": agora}
                n += 1
                candidatos.add((nome_arq, secao, chave, turma))
        if n:
            salvar_json_atomico(caminho, dados, indent=2)
            gravados += n
            if gravados_out is not None:
                gravados_out |= candidatos
            log(f"    💾 {n} vínculo(s) gravado(s) em {nome_arq}")
    return gravados


# ───────────────────────────── conferir o aluno achado ─────────────────────────────

@dataclass(frozen=True)
class Candidato:
    """Uma linha da tabela de resultados."""
    indice: int
    celulas: tuple = ()
    nascimento: Optional[date] = None
    cgm: str = ""
    mae: str = ""                         # coluna "Nome da Mãe" da tabela (vazia se a tabela não tiver)
    nome: str = ""                        # coluna "Nome" da tabela (vazia se não deu para identificar o cabeçalho)

    @property
    def texto(self) -> str:
        return " ".join(self.celulas)

    @property
    def nome_para_conferir(self) -> str:
        """Só a coluna Nome, quando a tabela tem cabeçalho (não mistura o nome da mãe); senão a linha inteira."""
        return self.nome or self.texto


def _coluna(cabecalho: list[str], cel: list[str], *chaves: str) -> str:
    for i, h in enumerate(cabecalho):
        if i < len(cel) and any(h == k or h.startswith(k) for k in chaves):
            return cel[i]
    return ""


def candidato_da_linha(indice: int, celulas: list[str], cabecalho: Optional[list[str]] = None) -> Candidato:
    """Linha da tabela → Candidato. Com `cabecalho` (CGM | Nome | Nome da Mãe | Data Nasc.) lê cada coluna pelo nome dela."""
    bruto = [str(c or "").strip() for c in celulas]
    cab = [normalizar(h) for h in (cabecalho or [])]
    if cab:
        nome = _coluna(cab, bruto, "NOME")
        mae = _coluna(cab, bruto, "NOME DA MAE", "MAE")
        cgm_col = _coluna(cab, bruto, "CGM")
        try:
            nasc_col = parse_data(_coluna(cab, bruto, "DATA"))
        except ValueError:
            nasc_col = None
        if nome:
            return Candidato(indice, tuple(c for c in bruto if c), nasc_col, cgm_col if re.fullmatch(r"\d{5,20}", cgm_col) else "", mae, nome)
    celulas = tuple(c for c in bruto if c)
    nasc = None
    for c in celulas:
        try:
            nasc = parse_data(c)
        except ValueError:
            nasc = None
        if nasc:
            break
    cgm = next((c for c in celulas if re.fullmatch(r"\d{8,12}", c)), "")
    return Candidato(indice, celulas, nasc, cgm)


def nome_confere(nome_busca: str, nome_candidato: str) -> bool:
    """
    Toda palavra do que foi escrito aparece no nome achado, inteira ou (com 3+ letras) como começo de palavra. Sem acentos
    nem maiúsculas. "Claudio Alex" confere com "CLAUDIO ALEX MENDES DE SOUZA".
    """
    busca = normalizar(nome_busca).split()
    cand = normalizar(nome_candidato).split()
    return bool(busca) and all(any(c == b or (len(b) >= 3 and c.startswith(b)) for c in cand) for b in busca)


def cadastro_confere(consulta: Consulta, cad: dict) -> bool:
    """
    O cadastro aberto é o aluno pedido? Nome por palavras; data de nascimento igual e nome da mãe por palavras, quando foram
    informados. Dado que o cadastro não mostra não derruba o aluno (não dá para provar que é outro).
    """
    if consulta.nome and cad.get("nome") and not nome_confere(consulta.nome, cad["nome"]):
        return False
    if consulta.nascimento and cad.get("nascimento") and cad["nascimento"] != consulta.nascimento:
        return False
    if consulta.mae and cad.get("mae") and not nome_confere(consulta.mae, cad["mae"]):
        return False
    return True


def unir_tabela_e_cadastro(c: Candidato, cad: dict) -> dict:
    """O que o cadastro não mostra (CGM, nascimento, mãe) completa-se com o que a tabela de resultados mostrou."""
    return {**cad, "cgm": cad.get("cgm") or c.cgm, "nascimento": cad.get("nascimento") or c.nascimento, "mae": cad.get("mae") or c.mae}


def _parecido(c: Candidato) -> dict:
    return {"nome": c.nome_para_conferir, "cgm": c.cgm, "data_nascimento": formatar_data(c.nascimento), "nome_mae": c.mae}


def _parecido_do_cadastro(cad: dict) -> dict:
    return {"nome": cad.get("nome", ""), "cgm": cad.get("cgm", ""), "data_nascimento": formatar_data(cad.get("nascimento")),
            "nome_mae": cad.get("mae", "")}


def filtrar_candidatos(candidatos: list[Candidato], consulta: Consulta) -> tuple[list[Candidato], list[Candidato]]:
    """(a conferir no cadastro, parecidos descartados). Descarta o que a TABELA prova ser outro: nome diferente (nem entra),
    data de nascimento diferente ou nome da mãe diferente. Dado que a tabela não mostra é conferido no cadastro."""
    por_nome = [c for c in candidatos if nome_confere(consulta.nome, c.nome_para_conferir)]

    def serve(c: Candidato) -> bool:
        if consulta.nascimento and c.nascimento and c.nascimento != consulta.nascimento:
            return False
        if consulta.mae and c.mae and not nome_confere(consulta.mae, c.mae):
            return False
        return True
    ficam = [c for c in por_nome if serve(c)]
    return ficam, [c for c in por_nome if c not in ficam]


def variantes_de_busca(nome: str) -> list[str]:
    """O que digitar no campo Nome, do mais específico ao mais aberto (sem repetir): o nome completo; o nome tirando uma
    palavra do fim de cada vez, até as duas primeiras (\"João Maria dos Santos Nascimento\" → \"João Maria dos Santos\" →
    \"João Maria dos\" → \"João Maria\"); primeiro + último nome; e o nome completo sem acento."""
    palavras = nome.split()
    todas = [" ".join(palavras)]
    todas += [" ".join(palavras[:n]) for n in range(len(palavras) - 1, 1, -1)]
    if len(palavras) > 2:
        todas.append(f"{palavras[0]} {palavras[-1]}")
    sem_acento = normalizar(nome)
    if sem_acento and sem_acento != todas[0].upper():
        todas.append(sem_acento)
    vistos, saida = set(), []
    for v in todas:
        if v and v not in vistos:
            vistos.add(v)
            saida.append(v)
    return saida


def tentativas_de_busca(consulta: Consulta) -> list[tuple[str, bool]]:
    """
    (texto do campo Nome, enviar a data de nascimento?) na ordem em que a Base ABC é consultada:
      1. nome completo, sem data;
      2. nome completo + data de nascimento (só se a data foi informada);
      3. primeiro + último nome e os dois primeiros (e o nome sem acento), com a data quando houver.
    """
    variantes = variantes_de_busca(consulta.nome)
    if not variantes:
        return []
    completo, resto = variantes[0], variantes[1:]
    tentativas = [(completo, False)]
    if consulta.nascimento:
        tentativas.append((completo, True))
    tentativas += [(v, bool(consulta.nascimento)) for v in resto]
    return tentativas


# ───────────────────────────── resultado ─────────────────────────────

def _em_curso(r: dict) -> bool:
    """A linha do histórico é a matrícula vigente (Resultado "Matriculado")? Transferido/Aprovado/Reprovado não são."""
    return normalizar(r.get("resultado")).startswith(("MATRICULAD", "CURSANDO"))


_ROMANOS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


def turma_equivalente(curso: str, serie) -> str:
    """Série do histórico do SERE → turma da pré-matrícula: EDUC INFANTIL série 5 = "Infantil V", série 4 = "Infantil IV";
    ensino fundamental série 4 = "4º Ano do Ensino Fundamental". Vazio se não der para saber."""
    c = normalizar(curso)
    m = re.search(r"\d+", str(serie or ""))
    n = int(m.group(0)) if m else 0
    if c.startswith("EDUC INFANTIL") and n in _ROMANOS:
        return f"Infantil {_ROMANOS[n]}"
    if "FUND" in c and 1 <= n <= 9:
        return f"{n}º Ano do Ensino Fundamental"
    return ""


def _escolas(historico: list[dict]) -> dict:
    """
    {"1": {...}, "2": {...}} com todas as linhas do histórico. A "1" é a escola ATUAL: do ano mais novo, a linha com Resultado
    "Matriculado" (o aluno pode ter várias linhas no mesmo ano: transferências); se nenhuma está matriculada, a última linha
    daquele ano na tabela. Depois vêm as outras do mesmo ano (da última para a primeira) e os anos anteriores, do mais novo
    ao mais antigo, com a mesma regra.
    """
    linhas = [(i, r) for i, r in enumerate(historico) if isinstance(r.get("ano"), int)]
    linhas.sort(key=lambda t: (-t[1]["ano"], 0 if _em_curso(t[1]) else 1, -t[0]))
    return {str(n): {"ano": r["ano"], "municipio": r.get("municipio", ""), "escola": r.get("escola", ""), "curso": r.get("curso", ""),
                     "serie": r.get("serie", ""), "resultado": r.get("resultado", ""),
                     "turma": turma_equivalente(r.get("curso", ""), r.get("serie", ""))}
            for n, (_, r) in enumerate(linhas, 1)}


@dataclass
class Resultado:
    """O que a procura devolveu. estado: "encontrado" | "nao_encontrado" | "ambiguo" | "erro"."""
    estado: str
    cadastro: Optional[dict] = None
    motivo: str = ""
    parecidos: list = field(default_factory=list)
    conferido_por: str = ""


def responsavel_confere_com_mae(consulta: Consulta, cad: dict) -> bool:
    """O responsável da pré-matrícula é a mãe do cadastro? (as palavras de um nome estão no outro; pode ser o pai: aí não prova nada)"""
    mae, resp = cad.get("mae", ""), consulta.responsavel
    return bool(mae and resp and (nome_confere(resp, mae) or nome_confere(mae, resp)))


def como_foi_conferido(consulta: Consulta, cad: dict, por_responsavel: bool = False) -> str:
    """O quanto o aluno achado foi confirmado: serve para você saber quais registros conferir à mão."""
    if consulta.cgm:
        return "CGM"
    partes = ["nome"]
    if consulta.nascimento and cad.get("nascimento") == consulta.nascimento:
        partes.append("data de nascimento")
    if consulta.mae and cad.get("mae") and nome_confere(consulta.mae, cad["mae"]):
        partes.append("nome da mãe")
    elif por_responsavel and responsavel_confere_com_mae(consulta, cad):
        partes.append("responsável (= mãe)")
    return " + ".join(partes) if len(partes) > 1 else "só o nome"


PERIODO_ANO_VIGENTE = "ano_vigente"
PERIODO_PRE_MATRICULA = "pre_matricula"
# Situações do histórico que o vínculo aceita sem pedir conferência, por período. Qualquer outra vira status "verificar".
SITUACOES_VINCULO = {
    PERIODO_ANO_VIGENTE: ("Matriculado", "Transferido"),
    PERIODO_PRE_MATRICULA: ("Matriculado", "Transferido", "Desistente", "Reprovado"),
}
_SITUACAO_POR_PREFIXO = (("MATRICULAD", "Matriculado"), ("CURSANDO", "Matriculado"), ("TRANSFERID", "Transferido"),
                         ("DESISTENT", "Desistente"), ("REPROVAD", "Reprovado"))


def periodo_da_consulta(consulta: Consulta) -> str:
    """Pelo arquivo de onde veio (pre_matricula.json = ano vigente; previsao_alunos_<ano+1>.json = pré-matrícula do próximo ano);
    sem arquivo: aluno da pré-matrícula = período de pré-matrícula; digitado = ano letivo vigente."""
    if consulta.destinos:
        return consulta.destinos[0][4]
    return PERIODO_PRE_MATRICULA if consulta.origem == "pre_matricula" else PERIODO_ANO_VIGENTE


def situacao_do_historico(resultado) -> str:
    """Resultado do SERE → nome padrão (\"MATRICULADO\" → \"Matriculado\"). Outros textos voltam como vieram; vazio fica vazio."""
    t = normalizar(resultado)
    for prefixo, nome in _SITUACAO_POR_PREFIXO:
        if t.startswith(prefixo):
            return nome
    return str(resultado or "").strip().capitalize()


def _chave_escola(nome) -> frozenset:
    """Palavras que identificam a escola, só para saber se duas linhas do histórico são a MESMA escola (letras soltas e o
    que vem depois da vírgula — \"NOME,E M PROFA-EI EF\" — não contam)."""
    base = unicodedata.normalize("NFKD", str(nome or "").split(",")[0]).encode("ascii", "ignore").decode("ascii").lower()
    return frozenset(p for p in re.findall(r"[a-z0-9]+", base) if len(p) > 1)


def _mesma_escola(a, b) -> bool:
    """Duas linhas do histórico são da mesma escola: palavras iguais, ou as de uma contidas na outra (nome abreviado x completo)."""
    texto = lambda n: re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", str(n or "").split(",")[0]).encode("ascii", "ignore").decode("ascii").lower()).strip()
    if texto(a) and texto(a) == texto(b):                 # escrita igual (as letras soltas distinguem \"ESC A\" de \"ESC B\")
        return True
    ka, kb = _chave_escola(a), _chave_escola(b)
    menor, maior = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    return len(menor) >= 2 and menor <= maior


def montar_vinculo(consulta: Consulta, nome: str, cgm: str, historico: list[dict], ano_referencia: int,
                   periodo: Optional[str] = None) -> dict:
    """
    CGM + aluno + turma/escola de origem + situação, a partir da linha do histórico do ano letivo vigente (`ano_referencia`).
    Com mais de uma linha no ano (transferências), vale a \"Matriculado\"; sem ela, a última. Nunca levanta: o que não
    fecha vira status \"verificar\" + motivo, e o vínculo é gravado assim mesmo.

    `escola_anterior`/`turma_anterior`/`ano_anterior`: a linha mais recente do histórico de OUTRA escola. Serve quando o
    aluno já entrou na nossa escola (a linha do ano é a nossa): o pedido de transferência vai para a escola anterior.
    """
    periodo = periodo or periodo_da_consulta(consulta)
    linhas = [(i, r) for i, r in enumerate(historico) if r.get("ano") == ano_referencia]
    linhas.sort(key=lambda t: (0 if _em_curso(t[1]) else 1, -t[0]))
    motivos: list[str] = []
    turma = escola = situacao = ""
    if linhas:
        r = linhas[0][1]
        turma = turma_equivalente(r.get("curso", ""), r.get("serie", "")) or str(r.get("serie") or "")
        escola = str(r.get("escola") or "")
        situacao = situacao_do_historico(r.get("resultado"))
        if sum(1 for _, x in linhas if _em_curso(x)) > 1:
            motivos.append(f"mais de uma matrícula em curso em {ano_referencia}")
        if not situacao:
            motivos.append(f"a linha de {ano_referencia} está sem resultado")
        elif situacao not in SITUACOES_VINCULO[periodo]:
            motivos.append(f"situação '{situacao}' fora do esperado ({', '.join(SITUACOES_VINCULO[periodo])})")
    else:
        motivos.append(f"o histórico não tem linha de {ano_referencia}")
    if not cgm:
        motivos.append("aluno sem CGM")
    anterior: dict = {}
    if linhas:
        escolhida, atual = linhas[0][0], linhas[0][1].get("escola")
        for i in range(len(historico) - 1, -1, -1):
            x = historico[i]
            if i == escolhida or not x.get("escola") or (x.get("ano") or 0) > ano_referencia:
                continue
            if not _mesma_escola(x.get("escola"), atual):
                anterior = {"escola_anterior": str(x["escola"]), "ano_anterior": x.get("ano"),
                            "turma_anterior": turma_equivalente(x.get("curso", ""), x.get("serie", "")) or str(x.get("serie") or "")}
                break
    vinculo = {"periodo": periodo, "ano_referencia": ano_referencia, "nome": nome, "cgm": cgm, "turma": turma,
               "escola": escola, "situacao": situacao, "status": "verificar" if motivos else "ok"}
    vinculo.update(anterior)
    if consulta.id_matricula:
        vinculo["id_matricula"] = consulta.id_matricula
    if motivos:
        vinculo["motivo"] = "; ".join(motivos)
    return vinculo


def montar_registro(consulta: Consulta, resultado: Resultado, historico: Optional[list[dict]] = None,
                    ano_referencia: Optional[int] = None) -> dict:
    encontrado = resultado.estado == "encontrado" and resultado.cadastro is not None
    cad = resultado.cadastro or {}
    cgm = (cad.get("cgm") or consulta.cgm) if encontrado else ""
    nome_final = (cad.get("nome") or consulta.nome) if encontrado else consulta.nome
    registro = {
        "data_busca": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "nome": (cad.get("nome") or consulta.nome) if encontrado else consulta.nome,
        "possui_cgm": bool(cgm),
        "cgm": cgm,
        "data_nascimento": formatar_data(cad.get("nascimento") or consulta.nascimento) if encontrado else formatar_data(consulta.nascimento),
        "nome_mae": (cad.get("mae") or consulta.mae) if encontrado else consulta.mae,
        "escolas": _escolas(historico or []) if encontrado else {},
        "situacao": resultado.estado,
        "conferido_por": resultado.conferido_por if encontrado else "",
        "observacao": resultado.motivo,
        "encontrados_parecidos": list(resultado.parecidos),
        "pedido": {"nome": consulta.nome, "data_nascimento": formatar_data(consulta.nascimento), "nome_mae": consulta.mae,
                   "cgm": consulta.cgm, "responsavel": consulta.responsavel, "origem": consulta.origem},
    }
    if consulta.id_matricula:
        registro["id_matricula"] = consulta.id_matricula
    if encontrado:
        registro["vinculo"] = montar_vinculo(consulta, nome_final, cgm, historico or [],
                                             int(ano_referencia or paths.ano_atual()))
    return registro


def arquivo_consolidado(ano: Optional[str] = None) -> Path:
    return (paths.DADOS_DIR / str(ano)) / NOME_ARQUIVO if ano else paths.dados_ano_atual() / NOME_ARQUIVO


def _mesmo_aluno(a: dict, b: dict) -> bool:
    if a.get("cgm") and b.get("cgm"):
        return str(a["cgm"]) == str(b["cgm"])
    pa, pb = a.get("pedido") or {}, b.get("pedido") or {}
    if not pa or not pb:
        return False
    chave = lambda p: (normalizar(p.get("nome")), normalizar(p.get("nome_mae")), p.get("cgm", ""), normalizar(p.get("responsavel")))  # noqa: E731
    if chave(pa) != chave(pb):
        return False
    da, db = pa.get("data_nascimento", ""), pb.get("data_nascimento", "")
    if da == db:
        return True
    # pré-matrícula: o registro de antes de a data existir (sem data) é do mesmo aluno que o novo (com data)
    return pa.get("origem") == pb.get("origem") == "pre_matricula" and (not da or not db)


def atualizar_consolidado(registro: dict, ano: Optional[str] = None) -> tuple[Path, bool]:
    """
    Troca o registro do mesmo aluno (mesmo CGM; sem CGM, mesmo pedido) ou acrescenta. Nunca duplica. Um registro
    "encontrado" não é substituído por um que não achou (a busca nova só aparece no resumo). Devolve (arquivo, gravou).
    """
    caminho = arquivo_consolidado(ano)
    atual = carregar_json(caminho, list, list)
    iguais = [r for r in atual if _mesmo_aluno(r, registro)]
    if registro.get("situacao") != "encontrado" and any(r.get("situacao") == "encontrado" for r in iguais):
        return caminho, False
    salvar_json_atomico(caminho, [r for r in atual if r not in iguais] + [registro], indent=4)
    return caminho, True


def podar_consolidado(registros: list, ano: Optional[str] = None) -> int:
    """
    Tira de buscas_base.json os registros que já foram vinculados (gravados) ao cadastro de origem — pré-matrícula ou
    transferidos. Quem foi digitado, ou cujo vínculo não pôde ser gravado, continua lá. Devolve quantos saíram.
    """
    if not registros:
        return 0
    caminho = arquivo_consolidado(ano)
    atual = carregar_json(caminho, list, list)
    restantes = [r for r in atual if not any(_mesmo_aluno(r, x) for x in registros)]
    if len(restantes) != len(atual):
        salvar_json_atomico(caminho, restantes, indent=4)
    return len(atual) - len(restantes)


@dataclass
class ResumoBaseAbc:
    total: int = 0
    encontrados: list = field(default_factory=list)       # rótulos
    nao_encontrados: list = field(default_factory=list)   # (rótulo, motivo): registrados, não são erro
    ambiguos: list = field(default_factory=list)          # (rótulo, descrição dos candidatos): registrados
    erros: list = field(default_factory=list)             # (rótulo, motivo): falha técnica; também registrada
    mantidos: list = field(default_factory=list)          # rótulos cujo registro "encontrado" anterior foi preservado
    verificar: list = field(default_factory=list)         # (rótulo, motivo): achado, mas o vínculo (turma/escola/situação) pede conferência manual
    vinculos: list = field(default_factory=list)         # (destino, vínculo) a gravar de volta nos arquivos da pré-matrícula
    vinculos_gravados: int = 0
    com_destino: list = field(default_factory=list)       # (registro, destinos) de quem veio de pré-matrícula/transferidos
    podados: int = 0                                      # registros tirados de buscas_base.json por já estarem vinculados
    arquivo: str = ""

    def como_dict(self) -> dict:
        return {"total": self.total, "encontrados": list(self.encontrados), "nao_encontrados": list(self.nao_encontrados),
                "ambiguos": list(self.ambiguos), "erros": list(self.erros), "mantidos": list(self.mantidos), "verificar": list(self.verificar), "vinculos_gravados": self.vinculos_gravados, "podados": self.podados, "arquivo": self.arquivo}


# ───────────────────────────── orquestração (independe do navegador) ─────────────────────────────

async def _abrir_e_ler(nav, pesquisa: dict, candidato: Candidato) -> dict:
    """Refaz a pesquisa (a tabela some ao fechar o cadastro), abre o candidato e devolve o que o cadastro mostra."""
    if not await nav.pesquisar(**pesquisa):
        raise RuntimeError("a pesquisa não devolveu resultado ao reabrir o cadastro")
    await nav.abrir(candidato)
    return await nav.cadastro()


async def _avaliar_nome(nav, consulta: Consulta, pesquisa: dict) -> Resultado:
    """Com a tabela de resultados na tela: escolhe o aluno (deixa o cadastro dele aberto), ou diz por que não."""
    a_conferir, descartados = filtrar_candidatos(await nav.candidatos(), consulta)
    parecidos = [_parecido(c) for c in descartados]
    if not a_conferir:
        motivo = "há alunos com esse nome, mas com outra data de nascimento" if descartados else "nenhum aluno com esse nome"
        return Resultado("nao_encontrado", motivo=motivo, parecidos=parecidos)

    com_data_da_tabela = unir_tabela_e_cadastro

    if len(a_conferir) == 1:
        await nav.abrir(a_conferir[0])
        cad = await nav.cadastro()
        if cadastro_confere(consulta, cad):
            cad = com_data_da_tabela(a_conferir[0], cad)
            return Resultado("encontrado", cad, conferido_por=como_foi_conferido(consulta, cad, True))
        await nav.fechar()
        return Resultado("nao_encontrado", motivo="o aluno com esse nome tem outra data de nascimento ou outra mãe",
                         parecidos=parecidos + [_parecido_do_cadastro(cad)])

    confirmados, rejeitados = [], []
    for c in a_conferir:
        cad = await _abrir_e_ler(nav, pesquisa, c)
        await nav.fechar()
        (confirmados if cadastro_confere(consulta, cad) else rejeitados).append((c, cad))
    parecidos += [_parecido_do_cadastro(cad) for _, cad in rejeitados]
    if len(confirmados) == 1:
        c, cad = confirmados[0]
        return Resultado("encontrado", com_data_da_tabela(c, await _abrir_e_ler(nav, pesquisa, c)), parecidos=parecidos,
                         conferido_por=como_foi_conferido(consulta, com_data_da_tabela(c, cad), True))
    if len(confirmados) > 1 and consulta.responsavel and not consulta.mae:
        # pré-matrícula: sem data nem mãe, o nome do responsável desempata se for o da mãe no cadastro
        pelo_responsavel = [(c, cad) for c, cad in confirmados if responsavel_confere_com_mae(consulta, cad)]
        if len(pelo_responsavel) == 1:
            c, cad = pelo_responsavel[0]
            outros = [_parecido_do_cadastro(x) for _, x in confirmados if x is not cad]
            return Resultado("encontrado", com_data_da_tabela(c, await _abrir_e_ler(nav, pesquisa, c)), parecidos=parecidos + outros,
                             conferido_por=como_foi_conferido(consulta, com_data_da_tabela(c, cad), True),
                             motivo=f"{len(confirmados)} homônimos: escolhido o de mãe = responsável da pré-matrícula")
    if len(confirmados) > 1:
        # desempate: "Joao Pedro" também confere com "JOAO PEDROSO"; se só um tem o nome IGUAL ao pedido, é ele
        exatos = [(c, cad) for c, cad in confirmados if normalizar(cad.get("nome") or c.nome_para_conferir) == normalizar(consulta.nome)]
        if len(exatos) == 1:
            c, cad = exatos[0]
            outros = [_parecido_do_cadastro(x) for _, x in confirmados if x is not cad]
            return Resultado("encontrado", com_data_da_tabela(c, await _abrir_e_ler(nav, pesquisa, c)), parecidos=parecidos + outros,
                             conferido_por=como_foi_conferido(consulta, com_data_da_tabela(c, cad), True),
                             motivo=f"{len(confirmados)} alunos serviam: escolhido o de nome idêntico ao pedido")
    if len(confirmados) > 1:
        falta = [x for x, tem in (("a data de nascimento", consulta.nascimento), ("o nome da mãe", consulta.mae)) if not tem]
        faltam = f"informe {' e '.join(falta)} para separá-los" if falta else "têm o mesmo nome, data de nascimento e mãe"
        return Resultado("ambiguo", motivo=f"{len(confirmados)} alunos servem para o pedido: {faltam}",
                         parecidos=[_parecido_do_cadastro(cad) for _, cad in confirmados])
    return Resultado("nao_encontrado", motivo=f"há alunos com esse nome, mas nenhum com essa data de nascimento e essa mãe",
                     parecidos=parecidos)


async def completar_pela_base_abc(nav, consulta: Consulta, cad: dict, log: Callable[[str], None] = print) -> dict:
    """
    Aluno achado, mas sem CGM (e/ou sem mãe): procura o mesmo aluno em "Pesquisar ABC" (tabela CGM | Nome | Nome da Mãe |
    Data Nasc.) e devolve {"cgm", "mae", "nascimento"} do que for achado — só aceita se for UM aluno com o nome idêntico
    (e a mesma data/mãe, quando conhecidas). Nunca levanta: sem confirmação devolve {}.
    """
    nome = cad.get("nome") or consulta.nome
    nasc = cad.get("nascimento") or consulta.nascimento
    alvo = Consulta(nome=nome, nascimento=nasc, mae=cad.get("mae") or consulta.mae, responsavel=consulta.responsavel)
    for termo, com_data in ((nome, False), (nome, True)) if nasc else ((nome, False),):
        try:
            log(f"    sem CGM no cadastro: procurando em Pesquisar ABC — {termo}" + (f" + {formatar_data(nasc)}" if com_data else ""))
            if not await nav.pesquisar_abc(nome=termo, nascimento=nasc if com_data else None):
                continue
            a_conferir, _ = filtrar_candidatos(await nav.candidatos_abc(), alvo)
        except FormularioDesconhecido:
            raise
        except Exception as exc:                          # noqa: BLE001 — o plano B nunca derruba o registro
            log(f"    ⚠️  Pesquisar ABC falhou: {exc}")
            return {}
        exatos = [c for c in a_conferir if normalizar(c.nome_para_conferir) == normalizar(nome)] or a_conferir
        if len(exatos) > 1 and consulta.responsavel:
            exatos = [c for c in exatos if c.mae and (nome_confere(consulta.responsavel, c.mae) or nome_confere(c.mae, consulta.responsavel))] or exatos
        if len(exatos) == 1 and exatos[0].cgm:
            c = exatos[0]
            log(f"    CGM {c.cgm} achado em Pesquisar ABC")
            return {"cgm": c.cgm, "mae": c.mae, "nascimento": c.nascimento}
    return {}


async def localizar_e_abrir(nav, consulta: Consulta, log: Callable[[str], None] = print) -> Resultado:
    """Pesquisa e, se achar, deixa aberto o cadastro do aluno (estado "encontrado"). Nunca levanta por não achar."""
    if consulta.cgm:
        if not await nav.pesquisar(cgm=consulta.cgm, nome="", nascimento=None, mae=""):
            return Resultado("nao_encontrado", motivo="CGM não encontrado na Base ABC")
        candidatos = await nav.candidatos()
        alvo = next((c for c in candidatos if c.cgm == consulta.cgm), candidatos[0] if candidatos else None)
        if alvo is None:
            return Resultado("nao_encontrado", motivo="CGM não encontrado na Base ABC")
        await nav.abrir(alvo)
        cad = await nav.cadastro()
        if cadastro_confere(consulta, cad):
            return Resultado("encontrado", cad, conferido_por="CGM")
        await nav.fechar()
        return Resultado("nao_encontrado", motivo=f"o CGM {consulta.cgm} é de outro aluno ({cad.get('nome', '')}, "
                                                  f"nascido em {formatar_data(cad.get('nascimento')) or '?'})",
                         parecidos=[_parecido_do_cadastro(cad)])

    tentativas = tentativas_de_busca(consulta)
    ultimo = Resultado("nao_encontrado", motivo="nenhum aluno com esse nome")
    parecidos: list = []
    ambiguo: Optional[Resultado] = None                  # homônimos achados na busca sem a data: guardados enquanto se tenta com a data
    for termo, com_data in tentativas:
        pesquisa = {"cgm": "", "nome": termo, "nascimento": consulta.nascimento if com_data else None, "mae": ""}
        log(f"    pesquisando por nome: {termo}" + (f" + data de nascimento {formatar_data(consulta.nascimento)}" if com_data else ""))
        if not await nav.pesquisar(**pesquisa):
            continue
        r = await _avaliar_nome(nav, consulta, pesquisa)
        if r.estado == "encontrado":
            return r
        if r.estado == "ambiguo":
            if com_data or consulta.nascimento is None:
                return r                                 # já foi com a data (ou não há data para usar): não dá para separar
            ambiguo = ambiguo or r
            log("    homônimos: repetindo a busca com o nome + a data de nascimento")
            continue
        ultimo = r
        for p in r.parecidos:
            if p not in parecidos:
                parecidos.append(p)
    if ambiguo is not None:                              # nem com a data apareceu um aluno só: continua ambíguo
        return ambiguo
    ultimo.parecidos = parecidos
    return ultimo


async def processar_consulta(nav, consulta: Consulta, resumo: ResumoBaseAbc, ano: Optional[str] = None,
                             log: Callable[[str], None] = print) -> None:
    rotulo = consulta.rotulo
    historico: list = []
    try:
        resultado = await localizar_e_abrir(nav, consulta, log)
        if resultado.estado == "encontrado":
            historico = await nav.historico()
            if not historico:
                log("    ⚠️  Histórico vazio")
    except FormularioDesconhecido:
        raise                                                    # não adianta tentar os outros: o formulário é que não foi entendido
    except Exception as exc:                                     # noqa: BLE001 — um aluno com problema não derruba os outros
        resultado = Resultado("erro", motivo=str(exc)[:200])
        historico = []
    if resultado.estado == "encontrado" and resultado.cadastro is not None:
        try:
            await nav.fechar()                                   # a tela do formulário volta antes de procurar em Pesquisar ABC
        except Exception as exc:                                 # noqa: BLE001
            log(f"    ⚠️  Não foi possível fechar o cadastro: {exc}")
        cad = resultado.cadastro
        if not (cad.get("cgm") or consulta.cgm):
            extra = await completar_pela_base_abc(nav, consulta, cad, log)
            if extra:
                resultado.cadastro = {**cad, "cgm": extra["cgm"], "mae": cad.get("mae") or extra.get("mae") or "",
                                      "nascimento": cad.get("nascimento") or extra.get("nascimento")}
            else:
                resultado.motivo = (resultado.motivo + "; " if resultado.motivo else "") + "aluno achado, mas o CGM não apareceu no cadastro nem em Pesquisar ABC"
    registro = montar_registro(consulta, resultado, historico, ano_referencia=int(ano) if ano else None)
    arquivo, gravou = atualizar_consolidado(registro, ano)
    resumo.arquivo = str(arquivo)
    if resultado.estado == "encontrado":
        resumo.encontrados.append(rotulo)
        escolas = registro["escolas"]
        recente = escolas.get("1", {}).get("escola") or "(sem histórico)"
        log(f"    ✅ {registro['nome']} (CGM {registro['cgm'] or 'sem CGM'}) — {recente}; {len(escolas)} escola(s) no histórico")
        v = registro["vinculo"]
        if v["status"] == "ok":
            log(f"    🔗 vínculo: CGM {v['cgm']} · {v['turma']} · {v['escola']} · {v['situacao']}")
        else:
            resumo.verificar.append((rotulo, v["motivo"]))
            log(f"    🔗 vínculo a VERIFICAR: {v['turma'] or '?'} · {v['escola'] or '?'} · {v['situacao'] or '?'} — {v['motivo']}")
        if consulta.destinos:
            resumo.com_destino.append((registro, consulta.destinos))
        for destino in consulta.destinos:                        # um vínculo por arquivo: cada um tem a sua regra de período
            resumo.vinculos.append((destino, montar_vinculo(consulta, v["nome"], v["cgm"], historico,
                                                            v["ano_referencia"], periodo=destino[4])))
        return
    lista = {"nao_encontrado": resumo.nao_encontrados, "ambiguo": resumo.ambiguos, "erro": resumo.erros}[resultado.estado]
    lista.append((rotulo, resultado.motivo))
    if not gravou:
        resumo.mantidos.append(rotulo)
    simbolo = {"nao_encontrado": "➖ Não encontrado", "ambiguo": "⚠️  Ambíguo — nenhum foi escolhido", "erro": "❌ Erro"}[resultado.estado]
    log(f"    {simbolo}: {resultado.motivo}" + (f" ({len(resultado.parecidos)} parecido(s) registrado(s))" if resultado.parecidos else "")
        + (" — o registro anterior, que achou o aluno, foi mantido" if not gravou else " — registrado em " + NOME_ARQUIVO))


async def consultar(nav, consultas: list[Consulta], ano: Optional[str] = None,
                    sessao_valida: Optional[Callable] = None, refazer_sessao: Optional[Callable] = None,
                    log: Callable[[str], None] = print, limpar_vinculados: bool = False) -> ResumoBaseAbc:
    resumo = ResumoBaseAbc(total=len(consultas))
    for i, c in enumerate(consultas, 1):
        log(f"\n  [{i:02d}/{len(consultas)}] {c.rotulo}")
        if sessao_valida is not None and not await sessao_valida():
            log("    sessão expirou: entrando de novo")
            await refazer_sessao()
        await processar_consulta(nav, c, resumo, ano, log)
    if resumo.vinculos:
        try:
            gravados: set = set()
            resumo.vinculos_gravados = gravar_vinculos_pre_matricula(resumo.vinculos, ano, log, gravados_out=gravados)
            if resumo.vinculos_gravados:                     # um CGM novo pode ligar um aluno da pré-matrícula à matrícula dele
                from src.comum.matriculas import ligar_pre_matricula_sem_falhar
                ligar_pre_matricula_sem_falhar(_pasta_e_ano(ano)[0])
            if limpar_vinculados and gravados:
                # só sai de buscas_base.json quem teve TODOS os destinos gravados: o vínculo já está no cadastro de origem
                saem = [reg for reg, destinos in resumo.com_destino
                        if all((d[0], d[1], d[2], d[3]) in gravados for d in destinos)]
                resumo.podados = podar_consolidado(saem, ano)
                if resumo.podados:
                    log(f"    🧹 {resumo.podados} registro(s) já vinculado(s) saíram de {NOME_ARQUIVO} (ficaram no cadastro de origem)")
        except Exception as exc:                                 # noqa: BLE001 — a busca já está salva em buscas_base.json
            log(f"    ⚠️  Não foi possível gravar os vínculos nos cadastros de origem: {exc}")
    return resumo


# ───────────────────────────── navegador (Playwright) ─────────────────────────────

class NavegadorBaseAbc:
    """Faz no navegador o que o script antigo fazia; as decisões ficam em `localizar_e_abrir`."""

    def __init__(self, page, log: Callable[[str], None] = print):
        self.page = page
        self.log = log
        self._descrito = False

    async def _campo(self, nomes: tuple, rotulos: tuple = ()):
        for n in nomes:
            for seletor in (f"#{n}", f"input[name='{n}']"):
                loc = self.page.locator(seletor)
                if await loc.count() > 0:
                    return loc.first
        for r in rotulos:
            loc = self.page.locator(f"//td[contains(normalize-space(.), '{r}')]/following-sibling::td[1]//input[not(@type='hidden')]")
            if await loc.count() > 0:
                return loc.first
        return None

    async def descrever_formulario(self) -> str:
        campos = await self.page.evaluate("""() => Array.from(document.querySelectorAll('input,select,textarea'))
            .filter(e => e.type !== 'hidden').map(e => (e.id || '') + '|' + (e.name || '') + '|' + (e.type || e.tagName.toLowerCase()))""")
        return "; ".join(campos) or "(nenhum campo encontrado na página)"

    async def pesquisar(self, *, cgm: str, nome: str, nascimento: Optional[date], mae: str = "") -> bool:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        c_cgm = await self._campo(CAMPOS_CGM)
        c_nome = await self._campo(CAMPOS_NOME, ROTULOS_NOME)
        c_nasc = await self._campo(CAMPOS_NASCIMENTO, ROTULOS_NASCIMENTO)
        c_mae = await self._campo(CAMPOS_MAE, ROTULOS_MAE)
        if cgm:
            if c_cgm is None:
                raise FormularioDesconhecido(f"campo CGM não encontrado. Campos da página (id|name|tipo): {await self.descrever_formulario()}")
        elif c_nome is None:
            raise FormularioDesconhecido("campo Nome não encontrado na Consulta Aluno na Base ABC. Ajuste CAMPOS_NOME em "
                                         f"consulta_base_abc.py. Campos da página (id|name|tipo): {await self.descrever_formulario()}")
        if not self._descrito:
            self._descrito = True
            self.log(f"    campos do formulário: {await self.descrever_formulario()}")
        for campo in (c_cgm, c_nome, c_nasc, c_mae):
            if campo is not None:
                await campo.fill("")
        if cgm:
            await c_cgm.fill(cgm)
        else:
            await c_nome.fill(nome)
            if nascimento and c_nasc is not None:
                await c_nasc.fill(formatar_data(nascimento))
            if mae and c_mae is not None:
                await c_mae.fill(mae)
        botao = self.page.locator("input[value='Pesquisar SERE']")
        if await botao.count() == 0:
            botao = self.page.locator("input.form_botao")
        await botao.first.click()
        try:
            await self.page.wait_for_selector("#lista_alunos_div #list_tabela", timeout=8000)
        except PlaywrightTimeoutError:
            return False
        return await self.page.locator("#lista_alunos_div a").count() > 0

    async def pesquisar_abc(self, *, nome: str, nascimento: Optional[date]) -> bool:
        """Botão "Pesquisar ABC": o resultado vem em #lista_alunos_ABC_div (CGM | Nome | Nome da Mãe | Data Nasc.)."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        c_nome = await self._campo(CAMPOS_NOME, ROTULOS_NOME)
        c_nasc = await self._campo(CAMPOS_NASCIMENTO, ROTULOS_NASCIMENTO)
        if c_nome is None:
            raise FormularioDesconhecido("campo Nome não encontrado para Pesquisar ABC. Campos da página (id|name|tipo): "
                                         f"{await self.descrever_formulario()}")
        for campo in (await self._campo(CAMPOS_CGM), c_nome, c_nasc):
            if campo is not None:
                await campo.fill("")
        await c_nome.fill(nome)
        if nascimento and c_nasc is not None:
            await c_nasc.fill(formatar_data(nascimento))
        botao = self.page.locator("input[value='Pesquisar ABC']")
        if await botao.count() == 0:
            return False
        await botao.first.click()
        try:
            await self.page.wait_for_selector("#lista_alunos_ABC_div #list_tabela", timeout=8000)
        except PlaywrightTimeoutError:
            return False
        return await self.page.locator("#lista_alunos_ABC_div #list_tabela tr:has(a)").count() > 0

    async def candidatos_abc(self) -> list[Candidato]:
        return await self.candidatos("#lista_alunos_ABC_div")

    async def candidatos(self, div: str = "#lista_alunos_div") -> list[Candidato]:
        ths = self.page.locator(f"{div} #list_tabela th")
        cabecalho = [(await ths.nth(j).inner_text()).strip() for j in range(await ths.count())]     # CGM | Nome | Nome da Mãe | Data Nasc.
        linhas = self.page.locator(f"{div} #list_tabela tr:has(a)")
        saida = []
        for i in range(await linhas.count()):
            tds = linhas.nth(i).locator("td")
            celulas = [(await tds.nth(j).inner_text()).strip() for j in range(await tds.count())]
            saida.append(candidato_da_linha(i, celulas, cabecalho))
        return saida

    async def abrir(self, candidato: Candidato) -> None:
        linhas = self.page.locator("#lista_alunos_div #list_tabela tr:has(a)")
        await linhas.nth(candidato.indice).locator("a").first.click()
        await self.page.wait_for_timeout(1000)

    async def _valor_do_rotulo(self, rotulos: tuple) -> str:
        """Texto da célula ao lado do rótulo: primeiro o rótulo exato ("Nome" ou "Nome:"), depois o que começa com ele."""
        for exato in (True, False):
            for r in rotulos:
                condicao = (f"normalize-space(translate(., ':', ''))='{r}'" if exato else f"starts-with(normalize-space(.), '{r}')")
                loc = self.page.locator(f"//td[@class='texto_form' and {condicao}]/following-sibling::td")
                if await loc.count() > 0:
                    texto = (await loc.first.inner_text()).strip()
                    if texto:
                        return texto
        return ""

    async def cadastro(self) -> dict:
        nasc = None
        try:
            nasc = parse_data(await self._valor_do_rotulo(ROTULOS_NASCIMENTO))
        except ValueError:
            pass
        return {"nome": await self._valor_do_rotulo(ROTULOS_NOME), "cgm": await self._valor_do_rotulo(("CGM",)),
                "nascimento": nasc, "mae": await self._valor_do_rotulo(ROTULOS_MAE)}

    async def historico(self) -> list[dict]:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        registros: list[dict] = []
        try:
            await self.page.wait_for_selector("table tr", timeout=5000)
        except PlaywrightTimeoutError:
            return registros
        linhas = self.page.locator("//table//tr[td]")
        for i in range(await linhas.count()):
            colunas = linhas.nth(i).locator("td")
            if await colunas.count() < 6:
                continue
            textos = [(await colunas.nth(j).inner_text()).strip() for j in range(6)]
            if textos[0].isdigit():
                registros.append({"ano": int(textos[0]), **dict(zip(CAMPOS_REGISTRO[1:], textos[1:]))})
        return registros

    async def fechar(self) -> None:
        botao = self.page.locator("input[value='Fechar']")
        if await botao.count() == 0:
            botao = self.page.locator("input[name='btnVoltar']")
        if await botao.count() > 0:
            await botao.first.click()
        else:
            await self.page.go_back()
        await self.page.wait_for_timeout(300)

    async def sessao_valida(self) -> bool:
        conteudo = (await self.page.content()).lower()
        return not any(i in conteudo for i in ("sessão expirou", "sessao expirou", "faça login novamente", "login.jsp"))


async def _entrar_e_ir_para_a_consulta(page) -> None:
    from src.automacao import sere_2026 as s
    await page.goto(s.URL)
    await page.fill("#CHAVE", s.LOGIN)
    await page.fill("#CHAVE_ENCRIPT", s.SENHA)
    await page.click("//input[@value='Entrar']")
    await page.wait_for_timeout(3_000)
    menu = await page.query_selector("#divoCMenu0_0")
    if not menu:
        raise RuntimeError("Não encontrou o menu principal do SERE depois do login")
    await menu.evaluate("(el) => el.dispatchEvent(new MouseEvent('mouseover', {view: window, bubbles: true, cancelable: true}))")
    await page.wait_for_timeout(500)
    await page.click("//div[contains(text(),'Consulta Aluno na Base ABC')]")
    await page.wait_for_timeout(500)


@asynccontextmanager
async def _sessao_sere(mostrar_navegador: bool = False):
    from src.automacao import sere_2026 as s
    async with s.async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True, forcar_mostrar=mostrar_navegador)
        page = await browser.new_page()
        try:
            await _entrar_e_ir_para_a_consulta(page)
            yield page
        finally:
            await browser.close()


async def consultar_base_abc_via_login(consultas: list, modo_teste: bool = False, mostrar_navegador: bool = False,
                                       sessao=_sessao_sere, log: Callable[[str], None] = print,
                                       limpar_vinculados: bool = False) -> dict:
    """
    Abre o SERE, vai a "Consulta Aluno na Base ABC" e consulta cada aluno. Devolve o resumo
    {"total","encontrados","nao_encontrados","ambiguos","erros","mantidos","arquivo"}. Aluno que não está na base não é erro.
    """
    consultas = list(consultas)
    if not consultas:
        raise ValueError("Nenhum aluno para consultar.")
    if modo_teste:
        consultas = consultas[:1]
        log("⚠️  MODO TESTE — só o primeiro aluno")
    log(f"{'=' * 60}\n  Consulta Aluno na Base ABC — {len(consultas)} aluno(s)\n{'=' * 60}")
    async with sessao(mostrar_navegador) as page:
        nav = NavegadorBaseAbc(page, log)

        async def refazer():
            await _entrar_e_ir_para_a_consulta(page)

        resumo = await consultar(nav, consultas, sessao_valida=nav.sessao_valida, refazer_sessao=refazer, log=log,
                                 limpar_vinculados=limpar_vinculados)
    log(f"\n{'=' * 60}\n  RESUMO: {len(resumo.encontrados)} encontrado(s), {len(resumo.nao_encontrados)} não encontrado(s) "
        f"(registrados), {len(resumo.ambiguos)} ambíguo(s) (registrados), {len(resumo.erros)} com erro técnico")
    for titulo, lista in (("Vínculo a verificar à mão", resumo.verificar), ("Não encontrados", resumo.nao_encontrados), ("Ambíguos (nada foi escolhido)", resumo.ambiguos), ("Erros", resumo.erros)):
        if lista:
            log(f"  {titulo}:")
            for rotulo, motivo in lista:
                log(f"    • {rotulo}: {motivo}")
    if resumo.arquivo:
        log(f"  Arquivo: {resumo.arquivo}")
    log("=" * 60)
    return resumo.como_dict()
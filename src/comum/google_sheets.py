"""
google_sheets.py — criar, consultar e atualizar planilhas do Google Sheets
=============================================================================
Funções INDEPENDENTES e reutilizáveis (nenhuma conhece alunos, turmas ou o SERE; isso fica em
src/automacao/sincroniza_sheets.py). Quem autentica é src/comum/google_auth.py.

    from src.comum import google_sheets as gs
    servico = gs.abrir_servico()                                   # autentica uma vez e reaproveita
    gs.verificar_planilha(url_ou_id, servico=servico)              # existe? tenho acesso? quais abas?
    gs.criar_planilha("Turmas 2026", {"1º ANO": ["Nº", "Nome"]})   # → {"id", "url", "titulo", "abas"}
    gs.atualizar_intervalo(id, "'1º ANO'!E12", [["MARIA"]])        # só aquela célula
    gs.anexar_linhas(id, "1º ANO", [[...], [...]])                 # novas linhas no fim da aba

Regras que estas funções garantem:
  • Escrita SEMPRE com intervalo explícito: nunca regrava a aba/planilha inteira. Valores que não cabem no
    intervalo pedido são recusados ANTES de enviar (nada é escrito fora dele).
  • Dados validados antes do envio (só texto, número, verdadeiro/falso ou vazio; limite de tamanho da célula).
  • Texto que começaria uma fórmula (= + @) é gravado como texto, salvo `permitir_formulas=True`.
  • Todo erro vira uma exceção da família GoogleErro com mensagem pronta para o usuário em português
    (autenticação, acesso/permissão, pedido inválido, cota, sem conexão). Falhas temporárias (cota, 5xx,
    conexão) são repetidas pela própria biblioteca do Google (`num_retries`).
  • Nada sensível em log: o ID da planilha aparece abreviado.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Iterable, Optional

from .google_auth import (ESCOPOS_PADRAO, GoogleErro, MODO_CONTA_SERVICO, detectar_modo, obter_credenciais)

log = logging.getLogger(__name__)

TENTATIVAS = 5                                  # repetições automáticas em cota (429), 5xx e queda de conexão
LIMITE_CELULA = 50000                           # caracteres por célula no Google Sheets
LIMITE_TITULO_ABA = 100
_PREFIXOS_FORMULA = ("=", "+", "@")


class SheetsErro(GoogleErro):
    """Erro ao falar com o Google Sheets (base dos três abaixo)."""


class SheetsAutenticacaoErro(SheetsErro):
    """O Google recusou as credenciais (401)."""


class SheetsAcessoErro(SheetsErro):
    """Planilha inexistente ou sem permissão de acesso (403/404)."""


class SheetsValidacaoErro(SheetsErro, ValueError):
    """Dados, intervalo ou nome inválidos (detectado aqui ou recusado pelo Google com 400).
    É também ValueError: para a tela e a linha de comando isso significa "pedido inválido" (mensagem pronta)."""


# ───────────────────────────── endereços A1 ────────────────────────────────────

_RE_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_RE_URL = re.compile(r"/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]+)")
_RE_A1 = re.compile(
    r"^(?:(?:'(?P<aba_q>(?:[^']|'')+)'|(?P<aba>[^'!]+))!)?"
    r"(?P<c1>[A-Za-z]{1,3})(?P<r1>\d+)?(?::(?P<c2>[A-Za-z]{1,3})(?P<r2>\d+)?)?$")


def extrair_id_planilha(url_ou_id: str) -> str:
    """Aceita o link completo da planilha ou só o ID e devolve o ID."""
    texto = str(url_ou_id or "").strip()
    achado = _RE_URL.search(texto)
    candidato = achado.group(1) if achado else texto
    if not _RE_ID.match(candidato):
        raise SheetsValidacaoErro(
            "Planilha não reconhecida: informe o link completo (https://docs.google.com/spreadsheets/d/…) "
            "ou só o ID, a parte longa entre /d/ e /edit.")
    return candidato


def _id_curto(planilha_id: str) -> str:
    return f"{planilha_id[:5]}…{planilha_id[-3:]}" if len(planilha_id) > 10 else planilha_id


def indice_para_coluna(indice: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    if indice < 0:
        raise ValueError("indice negativo")
    letras = ""
    n = indice + 1
    while n:
        n, resto = divmod(n - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def coluna_para_indice(coluna: str) -> int:
    """A → 0, Z → 25, AA → 26."""
    n = 0
    for letra in coluna.upper():
        n = n * 26 + (ord(letra) - ord("A") + 1)
    return n - 1


def intervalo_a1(aba: str, inicio: str, fim: str | None = None) -> str:
    """'1º ANO' + 'E12' → "'1º ANO'!E12"  (aspas na aba; aspas simples dentro do nome são dobradas)."""
    nome = str(aba).replace("'", "''")
    return f"'{nome}'!{inicio}" + (f":{fim}" if fim else "")


def _dimensoes(intervalo: str) -> tuple[Optional[int], int]:
    """(linhas, colunas) do intervalo; linhas None = sem limite (ex.: A2:C). Recusa intervalo sem células."""
    m = _RE_A1.match(str(intervalo or "").strip())
    if not m:
        raise SheetsValidacaoErro(f"Intervalo inválido: '{intervalo}'. Use o formato 'Aba'!A1 ou 'Aba'!A1:C10.")
    c1, r1, c2, r2 = m["c1"], m["r1"], m["c2"], m["r2"]
    if c2 is None:
        if r1 is None:
            raise SheetsValidacaoErro(f"Intervalo inválido: '{intervalo}' não indica células.")
        return 1, 1
    colunas = coluna_para_indice(c2) - coluna_para_indice(c1) + 1
    if colunas < 1:
        raise SheetsValidacaoErro(f"Intervalo inválido: '{intervalo}' (a coluna final vem antes da inicial).")
    if r1 is not None and r2 is not None:
        linhas = int(r2) - int(r1) + 1
        if linhas < 1:
            raise SheetsValidacaoErro(f"Intervalo inválido: '{intervalo}' (a linha final vem antes da inicial).")
        return linhas, colunas
    return None, colunas


# ───────────────────────────── validação dos dados ─────────────────────────────

def validar_valores(valores, *, permitir_formulas: bool = False) -> list[list]:
    """
    Confere e normaliza o que será enviado: lista de linhas (listas) de células texto/número/booleano/vazio.
    None vira "" (limpa a célula). Devolve uma cópia pronta; nunca altera a lista recebida.
    """
    if not isinstance(valores, (list, tuple)) or not valores:
        raise SheetsValidacaoErro("Nada para enviar: informe ao menos uma linha de valores.")
    saida: list[list] = []
    for i, linha in enumerate(valores, start=1):
        if not isinstance(linha, (list, tuple)):
            raise SheetsValidacaoErro(f"Linha {i} inválida: cada linha deve ser uma lista de células.")
        nova = []
        for j, celula in enumerate(linha, start=1):
            if celula is None:
                celula = ""
            elif isinstance(celula, bool) or isinstance(celula, (int, float)):
                pass
            elif isinstance(celula, str):
                if len(celula) > LIMITE_CELULA:
                    raise SheetsValidacaoErro(f"Célula {j} da linha {i} passa de {LIMITE_CELULA} caracteres.")
                if not permitir_formulas and celula.startswith(_PREFIXOS_FORMULA):
                    celula = "'" + celula                       # o apóstrofo força texto no USER_ENTERED
            else:
                raise SheetsValidacaoErro(
                    f"Célula {j} da linha {i} tem tipo não suportado ({type(celula).__name__}); use texto, número ou vazio.")
            nova.append(celula)
        saida.append(nova)
    return saida


def validar_escrita(intervalo: str, valores, *, permitir_formulas: bool = False) -> list[list]:
    """Valida os valores E confere se cabem no intervalo (garante que nada vaza para fora dele)."""
    limpos = validar_valores(valores, permitir_formulas=permitir_formulas)
    linhas, colunas = _dimensoes(intervalo)
    largura = max(len(l) for l in limpos)
    if largura > colunas or (linhas is not None and len(limpos) > linhas):
        raise SheetsValidacaoErro(
            f"Os dados ({len(limpos)} linha(s) × {largura} coluna(s)) não cabem no intervalo {intervalo}"
            + (f" ({linhas} × {colunas})." if linhas is not None else f" (até {colunas} coluna(s))."))
    return limpos


def resolver_aba(nome: str, abas: Iterable[str]) -> str:
    """Nome EXATO da aba a partir do que foi pedido (sem diferenciar maiúsculas, acentos e espaços nas pontas)."""
    abas = list(abas)

    def chave(t: str) -> str:
        sem = "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn")
        return " ".join(sem.casefold().split())

    if nome in abas:
        return nome
    achadas = [a for a in abas if chave(a) == chave(nome)]
    if len(achadas) == 1:
        return achadas[0]
    motivo = "há mais de uma com esse nome" if achadas else "não existe"
    raise SheetsValidacaoErro(f"Aba '{nome}' {motivo}. Abas da planilha: {', '.join(abas) or '(nenhuma)'}.")


# ───────────────────────────── conexão e erros ─────────────────────────────────

def abrir_servico(*, interativo: bool = True):
    """Autentica e devolve o recurso `spreadsheets()` da API. Reaproveite-o em várias chamadas (`servico=`)."""
    from googleapiclient.discovery import build
    creds = obter_credenciais(ESCOPOS_PADRAO, interativo=interativo)
    return build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()


def _mensagem_do_google(exc) -> str:
    try:
        return str(json.loads(exc.content.decode("utf-8"))["error"]["message"])[:300]
    except Exception:                                                     # noqa: BLE001 — corpo ausente ou fora do padrão
        return ""


def _traduzir(exc, contexto: str) -> SheetsErro:
    status = getattr(getattr(exc, "resp", None), "status", None)
    detalhe = _mensagem_do_google(exc)
    baixo = detalhe.lower()
    if status == 401:
        return SheetsAutenticacaoErro(
            "O Google recusou as credenciais (401). Refaça a autorização: apague o arquivo do token "
            "(google_token.json em credenciais/) e execute de novo, ou confira a chave da conta de serviço.")
    if status == 403:
        if "has not been used" in baixo or "is disabled" in baixo or "accessnotconfigured" in baixo.replace(" ", ""):
            return SheetsAcessoErro("A Google Sheets API não está ativada no projeto do Google Cloud das suas credenciais. "
                                    "Ative em APIs e serviços → Biblioteca → Google Sheets API.")
        if "quota" in baixo or "rate" in baixo:
            return SheetsErro("Limite de uso da API do Google atingido. Aguarde alguns minutos e tente de novo.")
        try:
            conta = detectar_modo() == MODO_CONTA_SERVICO
        except GoogleErro:
            conta = False
        quem = "o e-mail da conta de serviço (campo client_email do JSON)" if conta else "a conta Google que autorizou o programa"
        return SheetsAcessoErro(f"Sem permissão para {contexto}. Compartilhe a planilha, com permissão de edição, com {quem}.")
    if status == 404:
        return SheetsAcessoErro(f"Planilha não encontrada ao {contexto}: confira o ID/link e se a conta tem acesso a ela.")
    if status == 400:
        return SheetsValidacaoErro(f"O Google recusou o pedido ao {contexto}: {detalhe or 'intervalo ou dados inválidos'}.")
    if status == 429:
        return SheetsErro("Limite de uso da API do Google atingido (429). Aguarde alguns minutos e tente de novo.")
    return SheetsErro(f"Erro do Google ao {contexto} (HTTP {status}){': ' + detalhe if detalhe else ''}.")


def _executar(pedido, contexto: str):
    from googleapiclient.errors import HttpError
    try:
        return pedido.execute(num_retries=TENTATIVAS)
    except HttpError as exc:
        raise _traduzir(exc, contexto) from None
    except GoogleErro:
        raise
    except OSError as exc:
        raise SheetsErro(f"Sem conexão com o Google ao {contexto} ({type(exc).__name__}). Confira a internet e tente de novo.") from None


def _servico(servico):
    return servico if servico is not None else abrir_servico()


# ───────────────────────────── consulta ────────────────────────────────────────

def verificar_planilha(planilha: str, *, servico=None) -> dict:
    """
    A planilha existe e a conta tem acesso? Devolve {"id", "titulo", "url", "abas": [...]}.
    Levanta SheetsAcessoErro (não existe / sem permissão) ou SheetsAutenticacaoErro.
    """
    pid = extrair_id_planilha(planilha)
    meta = _executar(_servico(servico).get(spreadsheetId=pid, fields="spreadsheetId,spreadsheetUrl,properties.title,sheets.properties.title"),
                     "abrir a planilha")
    abas = [s["properties"]["title"] for s in meta.get("sheets", [])]
    log.info("Planilha %s acessível (%d aba(s)).", _id_curto(pid), len(abas))
    return {"id": pid, "titulo": meta.get("properties", {}).get("title", ""),
            "url": meta.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{pid}/edit", "abas": abas}


def listar_abas(planilha: str, *, servico=None) -> list[str]:
    return verificar_planilha(planilha, servico=servico)["abas"]


def ler_intervalo(planilha: str, intervalo: str, *, formatado: bool = False, servico=None) -> list[list]:
    """
    Lê um intervalo (células vazias no fim de cada linha são omitidas pela API). Por padrão números vêm como número e
    datas como o texto que aparece na célula (dd/mm/aaaa); `formatado=True` devolve tudo como aparece na tela.
    """
    pid = extrair_id_planilha(planilha)
    if not str(intervalo or "").strip():
        raise SheetsValidacaoErro("Informe o intervalo a ler.")
    extra = {"valueRenderOption": "FORMATTED_VALUE"} if formatado else {
        "valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"}
    r = _executar(_servico(servico).values().get(spreadsheetId=pid, range=intervalo, **extra), "ler a planilha")
    return r.get("values", [])


# ───────────────────────────── criação ─────────────────────────────────────────

def criar_planilha(nome: str, estrutura: dict[str, list[str]] | None = None, *, servico=None) -> dict:
    """
    Cria uma planilha NOVA. `estrutura` = {nome_da_aba: [cabeçalhos]} (cabeçalhos vão na linha 1; lista vazia = aba sem
    cabeçalho). Sem `estrutura`, o Google cria uma aba padrão. Devolve {"id", "url", "titulo", "abas"}.
    Com conta de serviço a planilha pertence ao "robô" (veja google_auth.py).
    """
    nome = str(nome or "").strip()
    if not nome:
        raise SheetsValidacaoErro("Informe o nome da planilha a criar.")
    if len(nome) > 250:
        raise SheetsValidacaoErro("Nome da planilha muito longo (máximo 250 caracteres).")
    estrutura = dict(estrutura or {})
    vistos: set[str] = set()
    for aba in estrutura:
        titulo = str(aba).strip()
        if not titulo or len(titulo) > LIMITE_TITULO_ABA:
            raise SheetsValidacaoErro(f"Nome de aba inválido: '{aba}' (vazio ou acima de {LIMITE_TITULO_ABA} caracteres).")
        if titulo.casefold() in vistos:
            raise SheetsValidacaoErro(f"Nome de aba repetido: '{aba}'.")
        vistos.add(titulo.casefold())
    cabecalhos = {aba: validar_valores([lista], permitir_formulas=False) for aba, lista in estrutura.items() if lista}

    svc = _servico(servico)
    corpo: dict = {"properties": {"title": nome}}
    if estrutura:
        corpo["sheets"] = [{"properties": {"title": str(aba).strip()}} for aba in estrutura]
    criada = _executar(svc.create(body=corpo, fields="spreadsheetId,spreadsheetUrl,properties.title,sheets.properties.title"),
                       "criar a planilha")
    pid = criada["spreadsheetId"]
    if cabecalhos:
        dados = [{"range": intervalo_a1(aba, "A1", f"{indice_para_coluna(len(linha[0]) - 1)}1"), "values": linha}
                 for aba, linha in cabecalhos.items()]
        _executar(svc.values().batchUpdate(spreadsheetId=pid, body={"valueInputOption": "USER_ENTERED", "data": dados}),
                  "gravar os cabeçalhos")
    abas = [s["properties"]["title"] for s in criada.get("sheets", [])]
    log.info("Planilha criada (%s) com %d aba(s).", _id_curto(pid), len(abas))
    return {"id": pid, "url": criada.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{pid}/edit",
            "titulo": criada.get("properties", {}).get("title", nome), "abas": abas}


# ───────────────────────────── atualização ─────────────────────────────────────

def atualizar_intervalos(planilha: str, atualizacoes: dict[str, list[list]], *, permitir_formulas: bool = False,
                         servico=None) -> int:
    """
    Grava vários intervalos numa só chamada: {"'Aba'!E12": [["MARIA"]], "'Aba'!I12:J12": [["T", ""]]}.
    Só as células desses intervalos são tocadas. Tudo é validado antes de enviar qualquer coisa.
    Devolve o total de células atualizadas.
    """
    if not atualizacoes:
        return 0
    pid = extrair_id_planilha(planilha)
    dados = [{"range": intervalo, "values": validar_escrita(intervalo, valores, permitir_formulas=permitir_formulas)}
             for intervalo, valores in atualizacoes.items()]
    r = _executar(_servico(servico).values().batchUpdate(
        spreadsheetId=pid, body={"valueInputOption": "USER_ENTERED", "data": dados}), "atualizar a planilha")
    return int(r.get("totalUpdatedCells", 0))


def atualizar_intervalo(planilha: str, intervalo: str, valores: list[list], *, permitir_formulas: bool = False,
                        servico=None) -> int:
    """Grava UM intervalo (ex.: "'1º ANO'!E12:F12"). Devolve o número de células atualizadas."""
    return atualizar_intervalos(planilha, {intervalo: valores}, permitir_formulas=permitir_formulas, servico=servico)


def anexar_linhas(planilha: str, aba: str, linhas: list[list], *, permitir_formulas: bool = False, servico=None) -> int:
    """Acrescenta linhas novas no fim da tabela da aba (não mexe nas linhas existentes). Devolve quantas foram inseridas."""
    if not linhas:
        return 0
    pid = extrair_id_planilha(planilha)
    limpas = validar_valores(linhas, permitir_formulas=permitir_formulas)
    r = _executar(_servico(servico).values().append(
        spreadsheetId=pid, range=intervalo_a1(aba, "A1"), valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS", body={"values": limpas}), "acrescentar linhas")
    return int(r.get("updates", {}).get("updatedRows", 0))


# ───────────────────────────── teste de acesso (tela) ──────────────────────────

def testar_autenticacao() -> str:
    """
    Autentica de verdade (abre o navegador na 1ª vez, se for OAuth) e informa o resultado. Usada pelo passo
    'Google API' da primeira execução; não lê nem grava planilha.
    """
    modo = detectar_modo()
    abrir_servico()
    texto = "conta de serviço" if modo == MODO_CONTA_SERVICO else "conta Google autorizada (OAuth)"
    print(f"✓ Google autenticado: {texto}.")
    return texto

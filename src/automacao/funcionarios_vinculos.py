"""
funcionarios_vinculos.py — Vínculos dos funcionários da escola (SERE × RH da Prefeitura × holerite)
=============================================================================
Pedido do usuário (21/10/2026): FUNDIR em uma só coisa os scripts que relacionam os funcionários da escola:

  servidores.py (já no projeto)  quem trabalha na escola segundo o SERE         → funcionarios.json
  coleta_servidores.py           todos os servidores da Prefeitura (site do RH)  → coleta_servidores.json
  capturar_matriculas.py         cruza SERE × RH por NOME e acha a matrícula     → funcionarios_matriculas.json
  mapa_escriturarios.py          prova o LOCAL DE TRABALHO pelo holerite

Detalhe do usuário: há funcionários TERCEIRIZADOS na escola, que não são servidores concursados e portanto NÃO
estão na lista de servidores do RH. Eles recebem a flag `terceirizado`. E, como comprovação, vale o que o
mapa_escriturarios faz com o holerite: os nomes do SERE que BATEM com o RH têm o holerite consultado para
confirmar que a pessoa está mesmo NESTA escola.

FLUXO (uma automação só, "Vínculos dos funcionários")
  1. Lista do SERE: usa funcionarios.json; se não existe (ou se pedir para atualizar) roda antes a coleta
     básica do SERE (servidores.py).
  2. Lista do RH: baixa os servidores da Prefeitura (reusa o arquivo se tem menos de 24 h).
  3. Cruza por NOME (igual, ou abreviado: "DE OLIVEIRA" → "O"). Nome que não está entre os servidores:
       - consta em RH estagiários  → vínculo "estagiario";
       - consta em RH terceirizados → "terceirizado" (terceirizado_origem = "lista_rh");
       - não consta em lugar nenhum → "terceirizado" (terceirizado_origem = "nao_consta_no_rh", é uma INFERÊNCIA:
         confira a lista de revisão, pode ser nome escrito diferente).
  4. Comprovação: para cada servidor casado, consulta o holerite do mês e compara o LOCAL DE TRABALHO com o nome
     da escola (Configurações → Dados da escola):
       na_escola=True   o holerite diz que trabalha aqui (comprovacao="holerite");
       na_escola=False  o holerite aponta outro lugar (pode ser homônimo: revisar);
       na_escola=None   não deu para comprovar (sem holerite, layout diferente, rubrica 256 "Estouro do Mês").
     Terceirizados e estagiários não têm holerite na Prefeitura: valem pelo SERE (comprovacao="sere").
     Quando o nome casa com VÁRIAS matrículas (homônimos), o holerite desempata: fica só a que trabalha aqui.
  5. Grava funcionarios_matriculas.json — o MESMO formato do capturar_matriculas.py (os termos de ciência já o
     leem), com os campos novos: vinculo, terceirizado, terceirizado_origem, na_escola, comprovacao,
     local_trabalho_holerite, holerite_mes, revisar, ajuste_manual.

MODOS DE CONSULTA (campo `modo`; 21/10/2026, pedido do usuário)
  sere        1. Consultar o SERE: refaz a lista de funcionários (funcionarios.json) e para. Não fala com o RH.
  vincular    2. Vincular com o RH: cruza os nomes do SERE com os servidores da Prefeitura e grava matrícula, NOME DO
              CARGO (titcar) e DATA DE ADMISSÃO (datadm) de cada matrícula. Não consulta holerite (rápido).
  homonimos   3. Verificar homônimos: só para quem tem MAIS DE UMA matrícula com o nome (ou só para o nome/CPF dado em
              `so_nome`), consulta o holerite de cada matrícula e vê qual está lotada nesta escola:
                - só uma lotada aqui → fica ela; as outras vão para `vinculos_descartados` (com o local do holerite);
                - duas ou mais lotadas aqui → DOIS CONCURSOS (ex.: professor 20h + 20h): ficam TODAS, com cargo e
                  admissão de cada uma, e a pessoa NÃO vai para a lista de revisão;
                - nenhuma lotada aqui → nada é descartado sem prova (fica para revisão).
              Quem não é verificado herda o resultado já gravado em funcionarios_matriculas.json.
  completo    Tudo: vincular + holerite de todos os servidores casados (o comportamento de sempre; é o padrão).

AJUSTES MANUAIS (funcionarios_ajustes.json, na pasta de dados do ano; é você quem edita):
    {"12345678900": {"terceirizado": false, "na_escola": true, "observacao": "nome grafado diferente no RH"}}
  A chave é o CPF (só números) — ou, sem CPF, o nome. Vale a cada nova execução e tira a pessoa da lista de revisão.

MUDANÇAS EM RELAÇÃO AOS SCRIPTS ORIGINAIS
  - Os quatro scripts viram um módulo; caminhos vêm de src.comum.paths (antes: pasta onde se rodava o script).
  - coleta_servidores.py: igual (requests + endpoint DataTables), só que a função devolve os dados e reusa o arquivo.
  - capturar_matriculas.py: o casamento por nome (exato e abreviado) e as regras de "Outras funções" são as mesmas.
    RH estagiários e terceirizados agora são lidos por HTTP simples (o original abria o Firefox); se o site exigir
    navegador, essas duas listas são puladas com aviso e o nome vira "terceirizado / nao_consta_no_rh".
    O endpoint de estagiários (…/estagiarios/1) foi deduzido por analogia com o de servidores: NÃO confirmado.
  - mapa_escriturarios.py: a leitura do holerite por posição (top/left) é a mesma; saiu a regra da rubrica 1681
    (era só do cargo de escriturário). O holerite NÃO é guardado em disco (tem valores de salário): o cache guarda
    só local, cargo e se tem a rubrica 256. A pausa de 5 s entre consultas ao RH foi mantida.
  - Cancelável a qualquer momento; as esperas e as chamadas de rede não travam a interface.
"""
from __future__ import annotations

import asyncio
import datetime
import difflib
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

from src.comum import escola, paths
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json, salvar_json_atomico
from src.comum.logger import get_logger

log = get_logger(__file__)

# ─────────────────────────────── configuração ───────────────────────────────

RH_BASE = "https://rh.pontagrossa.pr.gov.br/estatisticas"
URL_SERVIDORES = f"{RH_BASE}/servidores"
URL_ESTAGIARIOS = f"{RH_BASE}/estagiarios"
URL_TERCEIRIZADOS = f"{RH_BASE}/terceirizados"
HOLERITE_URL_TMPL = f"{RH_BASE}/holerite/1/{{matricula}}/{{mes}}"
NUMEMP_LISTA = (1,)                       # 1 = Prefeitura Municipal de Ponta Grossa
PAGE_LENGTH = 100
PAUSA_LISTA_RH_S = 0.4                    # entre páginas da lista do RH
PAUSA_HOLERITE_S = 5.0                    # cortesia ao servidor do RH (a mesma do mapa_escriturarios.py)
REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 3
RETRY_SLEEP_S = 6
HORAS_CACHE_LISTAS = 24
MAX_CANDIDATOS_HOLERITE = 5               # homônimos: acima disso não gasta consulta, vai para revisão
LIMITE_LINHAS_LOG = 40

FUNCAO_OUTRAS = "outras funcoes"

MODO_SERE, MODO_VINCULAR, MODO_HOMONIMOS, MODO_COMPLETO = "sere", "vincular", "homonimos", "completo"
MODOS = (MODO_SERE, MODO_VINCULAR, MODO_HOMONIMOS, MODO_COMPLETO)
MODOS_COM_HOLERITE = (MODO_HOMONIMOS, MODO_COMPLETO)

HEADERS_XHR = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": URL_SERVIDORES,
}
HEADERS_PAGINA = {"User-Agent": HEADERS_XHR["User-Agent"]}

# Holerite: spans posicionados por CSS (ver mapa_escriturarios.py). A LOTAÇÃO fica à esquerda (~145 px) e o LOCAL
# DE TRABALHO à direita (~470 px); só aceitamos como local o que está na metade direita.
TOLERANCIA_TOP_PX = 3
LEFT_MIN_LOCAL_TRABALHO_PX = 400

STOPWORDS_NOME = {"DE", "DO", "DA", "DOS", "DAS"}
STOPWORDS_ESCOLA = {"escola", "municipal", "de", "do", "da", "dos", "das", "e", "cmei", "centro", "educacao",
                    "infantil", "em", "ext", "professor", "professora", "profa", "prof"}
SUFIXOS_IGNORAR = [r"\(em ext\.?\)", r"\(ext\.?\)", r"\bfundeb\b.*", r"\bpmpg[- ]?sme.*", r"\d+%"]
TOKENS_POUCO_DISTINTIVOS = {"sao", "santa", "santo", "nossa", "senhora", "dom", "padre", "frei", "irma", "irmao",
                            "dr", "dra", "jardim", "vila", "nova", "novo", "jose", "maria", "joao", "ana", "antonio",
                            "luiz", "luis", "silva", "junior", "filho", "neto"}
PADROES_LOCAL_NAO_ESCOLAR = [
    r"\bSEDE\b", r"JULIA\s+[WV]AN[DT]ERLE", r"\bPACO\s+MUNICIPAL\b", r"\bPREFEITURA\b",
    r"\bSECRETARIA\s+MUNICIPAL\b", r"\bDEPARTAMENTO\b", r"\bSINDICATO\b", r"\bVIVEIRO\b", r"\bCAPELA\b",
    r"\bALMOXARIFADO\b", r"\bNAO\s+INFORMADO\b", r"\bCEDAL\b", r"\bCEMADI\b", r"\bCIAC\b", r"\bCAC\b",
    r"\bSMFDS\b", r"\bVM\b\s*-",
]
RE_LOCAL_NAO_ESCOLAR = re.compile("|".join(PADROES_LOCAL_NAO_ESCOLAR))
LIMIAR_SIMILARIDADE = 0.72

RE_MES = re.compile(r"^(0[1-9]|1[0-2])-\d{4}$")
RE_MATRICULA = re.compile(r"^\d{4,7}$")
RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
SPAN_RE = re.compile(r'<span[^>]*style="([^"]*)"[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL)
TOP_RE = re.compile(r"top\s*:\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
LEFT_RE = re.compile(r"left\s*:\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
RE_RUBRICA_ESTOURO = re.compile(r"256\D{0,40}Estouro\s*d[oe]\s*M[eê]s|Estouro\s*d[oe]\s*M[eê]s", re.IGNORECASE)


# ─────────────────────────────── arquivos ───────────────────────────────

def _dados() -> Path:
    return paths.dados_ano_atual()


def arquivo_sere() -> Path: return _dados() / "funcionarios.json"
def arquivo_rh_servidores() -> Path: return _dados() / "coleta_servidores.json"
def arquivo_rh_estagiarios() -> Path: return _dados() / "rh_estagiarios.json"
def arquivo_rh_terceirizados() -> Path: return _dados() / "rh_terceirizados.json"
def arquivo_cache_holerites() -> Path: return _dados() / "cache_holerites.json"
def arquivo_ajustes() -> Path: return _dados() / "funcionarios_ajustes.json"
def arquivo_saida() -> Path: return _dados() / "funcionarios_matriculas.json"


# ─────────────────────────────── texto e nomes ───────────────────────────────

def remover_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto or "")) if not unicodedata.combining(c))


def normalizar_texto(txt) -> str:
    return re.sub(r"\s+", " ", remover_acentos(str(txt or "")).strip()).lower()


def normalizar_nome(nome) -> str:
    """Sem acento, só letras, maiúsculo e espaços colapsados (comparação de nomes de pessoas)."""
    n = re.sub(r"[^a-zA-Z\s]", " ", remover_acentos(str(nome or "").strip()))
    return re.sub(r"\s+", " ", n).strip().upper()


def _so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _tokens_compativeis_abreviado(tokens_abrev: list[str], tokens_completo: list[str]) -> bool:
    """`tokens_abrev` é uma versão abreviada válida de `tokens_completo` (inicial no lugar do nome; preposições podem sumir)."""
    i = j = 0
    while i < len(tokens_abrev) and j < len(tokens_completo):
        a, c = tokens_abrev[i], tokens_completo[j]
        if a == c:
            i += 1
            j += 1
        elif len(a) == 1 and c.startswith(a):
            i += 1
            j += 1
        elif c in STOPWORDS_NOME:
            j += 1
        else:
            return False
    while j < len(tokens_completo) and tokens_completo[j] in STOPWORDS_NOME:
        j += 1
    return i == len(tokens_abrev) and j == len(tokens_completo)


def nomes_compativeis_abreviado(a_normalizado: str, b_normalizado: str) -> bool:
    ta, tb = a_normalizado.split(), b_normalizado.split()
    if not ta or not tb or ta == tb:
        return False
    return _tokens_compativeis_abreviado(ta, tb) or _tokens_compativeis_abreviado(tb, ta)


def construir_indice(registros: list[dict]) -> dict[str, list[dict]]:
    """nome normalizado → registros do RH (campo 'nomfun')."""
    indice: dict[str, list[dict]] = {}
    for r in registros:
        chave = normalizar_nome(r.get("nomfun"))
        if chave:
            indice.setdefault(chave, []).append(r)
    return indice


def buscar_por_nome(nome: str, indice: dict[str, list[dict]]) -> tuple[str, list[dict]]:
    """('exato' | 'abreviado' | 'nenhum', registros). O abreviado só é tentado quando o exato falha."""
    chave = normalizar_nome(nome)
    if not chave:
        return "nenhum", []
    if chave in indice:
        return "exato", list(indice[chave])
    achados = [r for k, regs in indice.items() if nomes_compativeis_abreviado(chave, k) for r in regs]
    return ("abreviado", achados) if achados else ("nenhum", [])


# ─────────────────────────────── escola × local de trabalho ───────────────────────────────

def normalizar_nome_escola(bruto: str) -> str:
    """Forma canônica de uma escola/local: sem acento, minúsculo, sem sufixos de verba e sem 'Escola Municipal', 'CMEI'…"""
    texto = str(bruto or "").strip()
    for padrao in SUFIXOS_IGNORAR:
        texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"[^a-z0-9\s]", " ", remover_acentos(texto).lower())
    return " ".join(p for p in texto.split() if p and p not in STOPWORDS_ESCOLA)


def tokens_distintivos(normalizado: str) -> set[str]:
    return {t for t in normalizado.split() if len(t) >= 4 and t not in TOKENS_POUCO_DISTINTIVOS}


def avaliar_par(alvo: str, oficial: str) -> float:
    """
    Casamento entre o LOCAL DE TRABALHO e o nome da escola, ambos normalizados. 0.0 = não casa. 1.0 idêntico; 0.95
    um contém o outro (com token distintivo); senão similaridade ≥ 0.72 e ao menos um token distintivo em comum
    (impede 'CAPELA SAO JOSE' × 'ESCOLA SAO JORGE').
    """
    if not alvo or not oficial:
        return 0.0
    if alvo == oficial:
        return 1.0
    ta, to = set(alvo.split()), set(oficial.split())
    menor, maior = (ta, to) if len(ta) <= len(to) else (to, ta)
    if len(menor) >= 2 and menor <= maior and tokens_distintivos(" ".join(menor)):
        return 0.95
    if not (tokens_distintivos(alvo) & tokens_distintivos(oficial)):
        return 0.0
    ratio = difflib.SequenceMatcher(None, alvo, oficial).ratio()
    return ratio if ratio >= LIMIAR_SIMILARIDADE else 0.0


def local_nao_escolar(local: Optional[str]) -> bool:
    """Sede da SME, Paço, secretarias, depósitos, 'NÃO INFORMADO'…"""
    return bool(local) and bool(RE_LOCAL_NAO_ESCOLAR.search(remover_acentos(local).upper()))


def local_confere(local: Optional[str], nome_escola: str) -> bool:
    """O local de trabalho do holerite é ESTA escola?"""
    if not local or local_nao_escolar(local):
        return False
    return avaliar_par(normalizar_nome_escola(local), normalizar_nome_escola(nome_escola)) > 0


# ─────────────────────────────── holerite ───────────────────────────────

def _limpar_span(bruto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", bruto)).strip()


def extrair_spans(html: str) -> list[tuple[float, float, str]]:
    """(top, left, texto) de cada <span> posicionado com texto."""
    spans = []
    for estilo, texto_bruto in SPAN_RE.findall(html):
        t, l = TOP_RE.search(estilo), LEFT_RE.search(estilo)
        texto = _limpar_span(texto_bruto)
        if t and l and texto:
            spans.append((float(t.group(1)), float(l.group(1)), texto))
    return spans


def _agrupar_por_linha(spans: list[tuple[float, float, str]]) -> list[list[tuple[float, float, str]]]:
    if not spans:
        return []
    ordenados = sorted(spans, key=lambda s: (s[0], s[1]))
    linhas, atual, topo = [], [ordenados[0]], ordenados[0][0]
    for s in ordenados[1:]:
        if abs(s[0] - topo) <= TOLERANCIA_TOP_PX:
            atual.append(s)
        else:
            linhas.append(sorted(atual, key=lambda x: x[1]))
            atual, topo = [s], s[0]
    linhas.append(sorted(atual, key=lambda x: x[1]))
    return linhas


def _linha_ancora(linhas: list) -> Optional[int]:
    """Linha 'matrícula | nome | nível | admissão': tem um span só de dígitos (4-7) e mais uma data ou um nome."""
    for idx, linha in enumerate(linhas):
        if not any(RE_MATRICULA.match(s[2]) for s in linha):
            continue
        tem_data = any(RE_DATA.match(s[2]) for s in linha)
        tem_nome = any(len(s[2]) >= 6 and re.search(r"[A-ZÀ-Ú]{3,}", s[2].upper()) for s in linha if not RE_MATRICULA.match(s[2]))
        if tem_data or tem_nome:
            return idx
    return None


def extrair_local_trabalho(html: str) -> tuple[Optional[str], Optional[str]]:
    """(local_de_trabalho, cargo) por geometria; None em qualquer caso duvidoso, nunca um chute."""
    linhas = _agrupar_por_linha(extrair_spans(html))
    ancora = _linha_ancora(linhas)
    if ancora is None:
        return None, None
    local = cargo = None
    if ancora - 1 >= 0:
        direita = [s for s in linhas[ancora - 1] if s[1] >= LEFT_MIN_LOCAL_TRABALHO_PX]
        if direita:
            local = min(direita, key=lambda s: s[1])[2]
    if ancora + 1 < len(linhas):
        candidatos = [s for s in linhas[ancora + 1] if s[2]]
        if candidatos:
            cargo = min(candidatos, key=lambda s: s[1])[2]
    return local, cargo


def extrair_admissao(html: str) -> Optional[str]:
    """Data de admissão (dd/mm/aaaa) da linha 'matrícula | nome | nível | admissão' do holerite; None se duvidoso."""
    linhas = _agrupar_por_linha(extrair_spans(html))
    ancora = _linha_ancora(linhas)
    if ancora is None:
        return None
    datas = [s[2] for s in linhas[ancora] if RE_DATA.match(s[2])]
    return datas[0] if len(datas) == 1 else None


def analisar_holerite(html: str) -> dict:
    """{"local","cargo","estouro","admissao","erro"} de um holerite. Só isso: valores de salário nunca saem daqui."""
    local, cargo = extrair_local_trabalho(html)
    estouro = bool(RE_RUBRICA_ESTOURO.search(_limpar_span(html)))
    erro = None if local else "não foi possível localizar o LOCAL DE TRABALHO por posição no holerite (layout inesperado?)"
    return {"local": local, "cargo": cargo, "estouro": estouro, "admissao": extrair_admissao(html), "erro": erro}


def mes_anterior_padrao() -> str:
    """Mês anterior ao atual, 'MM-AAAA' (o holerite do mês corrente ainda pode não existir)."""
    ultimo = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
    return ultimo.strftime("%m-%Y")


def validar_mes(mes: str) -> str:
    mes = str(mes or "").strip() or mes_anterior_padrao()
    if not RE_MES.match(mes):
        raise ValueError("Mês do holerite inválido: use MM-AAAA (ex.: 09-2026) ou deixe em branco para o mês anterior.")
    return mes


def consultar_holerite(session: requests.Session, matricula: str, mes: str) -> dict:
    """Baixa e analisa o holerite. Devolve {"local","cargo","estouro","erro"}; erro de rede/404 vai em "erro"."""
    url = HOLERITE_URL_TMPL.format(matricula=matricula, mes=mes)
    ultimo_erro = None
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=HEADERS_PAGINA, timeout=REQUEST_TIMEOUT_S)
            if resp.status_code == 404:
                return {"local": None, "cargo": None, "estouro": None, "admissao": None,
                        "erro": f"matrícula {matricula} não encontrada (404) para {mes}"}
            resp.raise_for_status()
            return analisar_holerite(resp.text)
        except requests.RequestException as exc:
            ultimo_erro = str(exc)
            if tentativa < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_S * tentativa)
    return {"local": None, "cargo": None, "estouro": None, "admissao": None,
            "erro": f"falha de conexão após {MAX_RETRIES} tentativas: {ultimo_erro}"}


# ─────────────────────────────── listas do RH ───────────────────────────────

def _cache_buster() -> str:
    return str(int(time.time() * 1000) + random.randint(0, 999))


def _get_json(session: requests.Session, url: str) -> dict:
    resp = session.get(url, headers=HEADERS_XHR, timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _aadata(dados: dict) -> list:
    return dados.get("aadata") or dados.get("aaData") or []


def coletar_lista_rh_xhr(session: requests.Session, base_url: str, numemp: int = 1) -> tuple[str, list[dict]]:
    """
    Endpoint DataTables do RH (…/<lista>/<numemp>?_=<timestamp>): devolve (título, registros), paginando se o
    servidor indicar mais registros do que mandou (iDisplayStart/iDisplayLength). Igual ao coleta_servidores.py.
    """
    dados = _get_json(session, f"{base_url}/{numemp}?_={_cache_buster()}")
    titulo, registros = dados.get("titulo", ""), list(_aadata(dados))
    total = dados.get("iTotalRecords") or dados.get("iTotalDisplayRecords") or dados.get("recordsTotal")
    if not total or int(total) <= len(registros):
        return titulo, registros
    while len(registros) < int(total):
        time.sleep(PAUSA_LISTA_RH_S)
        pagina = _aadata(_get_json(
            session, f"{base_url}/{numemp}?_={_cache_buster()}&iDisplayStart={len(registros)}&iDisplayLength={PAGE_LENGTH}"))
        if not pagina:
            break
        registros.extend(pagina)
    return titulo, registros


def coletar_terceirizados_rh(session: requests.Session) -> list[dict]:
    """Tabela HTML de /terceirizados (Razão Social, Nome, Dt. Início, Dt. Fim, Função) → registros com 'nomfun'."""
    resp = session.get(URL_TERCEIRIZADOS, headers=HEADERS_PAGINA, timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    tabela = BeautifulSoup(resp.text, "html.parser").find("table")
    if tabela is None:
        raise ValueError("a página de terceirizados do RH não traz a tabela (talvez precise de navegador)")
    registros = []
    for tr in (tabela.find("tbody") or tabela).find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) >= 5:
            registros.append({"razao_social": cols[0], "nomfun": cols[1], "dt_inicio": cols[2], "dt_fim": cols[3], "titcar": cols[4]})
    return registros


def _cache_valido(caminho: Path, forcar: bool) -> bool:
    if forcar or not caminho.exists():
        return False
    return (time.time() - caminho.stat().st_mtime) < HORAS_CACHE_LISTAS * 3600


def _ler_cache(caminho: Path) -> list[dict]:
    try:
        dados = carregar_json(caminho, list, tipo_esperado=(dict, list))
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    if isinstance(dados, dict):                                 # coleta_servidores.json: {"empresas":[{"servidores":[...]}]}
        return [s for emp in dados.get("empresas", []) for s in emp.get("servidores", [])]
    return dados


def obter_servidores_rh(forcar: bool = False, session: Optional[requests.Session] = None) -> list[dict]:
    """Servidores da Prefeitura. Reusa coleta_servidores.json se tem menos de 24 h; senão baixa e regrava (mesmo formato)."""
    caminho = arquivo_rh_servidores()
    if _cache_valido(caminho, forcar):
        registros = _ler_cache(caminho)
        print(f"Lista de servidores do RH reaproveitada ({len(registros)}), baixada há menos de {HORAS_CACHE_LISTAS} h.")
        return registros
    session = session or requests.Session()
    print("Baixando a lista de servidores do RH da Prefeitura...")
    empresas, total = [], 0
    for numemp in NUMEMP_LISTA:
        try:
            titulo, regs = coletar_lista_rh_xhr(session, URL_SERVIDORES, numemp)
        except (requests.RequestException, ValueError) as exc:          # ValueError: JSON inválido
            raise RuntimeError(f"Não consegui baixar a lista de servidores do RH (numemp={numemp}): {exc}") from exc
        empresas.append({"numemp": numemp, "titulo": titulo, "total_servidores": len(regs), "servidores": regs})
        total += len(regs)
    if not total:
        raise RuntimeError("A lista de servidores do RH veio vazia: o site pode ter mudado.")
    salvar_json_atomico(caminho, {"fonte": URL_SERVIDORES, "coletado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "empresas": empresas, "total_geral_servidores": total})
    print(f"{total} servidor(es) no RH.")
    return _ler_cache(caminho)


def obter_lista_extra(nome: str, forcar: bool = False, session: Optional[requests.Session] = None) -> tuple[list[dict], Optional[str]]:
    """RH estagiários ('estagiarios') ou terceirizados ('terceirizados'): (registros, erro). Erro NÃO derruba o fluxo."""
    caminho = arquivo_rh_estagiarios() if nome == "estagiarios" else arquivo_rh_terceirizados()
    if _cache_valido(caminho, forcar):
        return _ler_cache(caminho), None
    session = session or requests.Session()
    try:
        registros = (coletar_lista_rh_xhr(session, URL_ESTAGIARIOS)[1] if nome == "estagiarios"
                     else coletar_terceirizados_rh(session))
    except (requests.RequestException, ValueError) as exc:
        return [], str(exc)
    salvar_json_atomico(caminho, registros)
    return registros, None


# ─────────────────────────────── classificação ───────────────────────────────

def _nome_do_funcionario(func: dict) -> str:
    return str(func.get("nome") or func.get("nome_completo") or "").strip()


def _vinculo_de(reg_rh: dict, score: float, tipo: str) -> dict:
    return {"numcad": reg_rh.get("numcad"), "numemp": reg_rh.get("numemp"), "nomemp": reg_rh.get("nomemp"),
            "nomloc": reg_rh.get("nomloc"), "titcar": reg_rh.get("titcar"), "datadm": reg_rh.get("datadm"),
            "dessit": reg_rh.get("dessit"), "forma_ingresso": reg_rh.get("forma_ingresso"),
            "match_score": score, "match_tipo": tipo, "match_nome_api": reg_rh.get("nomfun")}


_CAMPOS_VINCULO = ("numcad", "numemp", "nomemp", "nomloc", "titcar", "datadm", "dessit", "forma_ingresso",
                   "match_score", "match_tipo", "match_nome_api")


def _aplicar_vinculo_principal(reg: dict, v: Optional[dict]) -> None:
    for campo in _CAMPOS_VINCULO:
        reg[campo] = v.get(campo) if v else None


def precisa_listas_extras(funcionarios: list[dict], idx_servidores: dict) -> bool:
    """Só vale baixar RH estagiários/terceirizados se alguém não casou com os servidores ou tem 'Outras funções'."""
    for f in funcionarios:
        if normalizar_texto(f.get("funcao")) == FUNCAO_OUTRAS or not buscar_por_nome(_nome_do_funcionario(f), idx_servidores)[1]:
            return True
    return False


def classificar(funcionarios: list[dict], idx_servidores: dict, idx_estagiarios: Optional[dict] = None,
                idx_terceirizados: Optional[dict] = None) -> list[dict]:
    """
    Cruza cada funcionário do SERE com o RH e define o vínculo. Sem consulta de rede nem de holerite.
    `idx_estagiarios`/`idx_terceirizados` = None quando essas listas não puderam ser lidas.
    """
    registros = []
    for func in funcionarios:
        nome, funcao = _nome_do_funcionario(func), str(func.get("funcao") or "")
        outras = normalizar_texto(funcao) == FUNCAO_OUTRAS
        revisar: list[str] = []
        reg = {
            "cpf": func.get("cpf", ""), "nome": nome, "funcao": funcao,
            "nome_curto_risco_homonimo": len(normalizar_nome(nome).split()) <= 2,
            "matricula_encontrada": False,
            **{c: None for c in _CAMPOS_VINCULO},
            "origem_vinculo": None, "dados_originais": func,
            "vinculos_servidores": [], "multiplas_matriculas": False,
            "vinculo": None, "terceirizado": False, "terceirizado_origem": None,
            "na_escola": None, "comprovacao": "nenhuma", "local_trabalho_holerite": None,
            "holerite_mes": None, "revisar": revisar, "ajuste_manual": False,
        }

        tipo, achados = buscar_por_nome(nome, idx_servidores)
        if achados:
            score = 100.0 if tipo == "exato" else 90.0
            vinculos = [_vinculo_de(r, score, tipo) for r in achados]
            _aplicar_vinculo_principal(reg, vinculos[0])
            reg.update({"matricula_encontrada": True, "origem_vinculo": "servidores", "vinculo": "servidor",
                        "vinculos_servidores": vinculos, "multiplas_matriculas": len(vinculos) > 1})
            if tipo == "abreviado":
                reg["aviso_match_abreviado"] = (f"Match só por nome abreviado (heurística): '{nome}' vs '{vinculos[0]['match_nome_api']}'. "
                                                "Confira antes de confiar 100%.")
                revisar.append("nome casou só por abreviação")
            if len(vinculos) > 1:
                revisar.append(f"{len(vinculos)} matrículas com esse nome (homônimos?)")
        else:
            reg["match_tipo"] = "nenhum"

        est = ter = None
        if (outras or not achados) and (idx_estagiarios is not None or idx_terceirizados is not None):
            est = buscar_por_nome(nome, idx_estagiarios or {})
            ter = buscar_por_nome(nome, idx_terceirizados or {})
            if outras:                                          # regra do capturar_matriculas.py: mostrar o que achou
                reg["estagiario_encontrado"] = ({"match": True, "match_tipo": est[0], "dados": est[1][0]} if est[1] else {"match": False})
                reg["terceirizado_encontrado"] = ({"match": True, "match_tipo": ter[0], "dados": ter[1][0]} if ter[1] else {"match": False})
                if achados and (est[1] or ter[1]):
                    revisar.append("'Outras funções': também consta em RH estagiários/terceirizados")

        if not achados:
            if est and est[1] and not (ter and ter[1]):
                reg.update({"vinculo": "estagiario", "origem_vinculo": "estagiarios"})
            else:
                reg.update({"vinculo": "terceirizado", "terceirizado": True, "na_escola": True, "comprovacao": "sere"})
                if ter and ter[1]:
                    reg.update({"origem_vinculo": "terceirizados", "terceirizado_origem": "lista_rh"})
                    if est and est[1]:
                        revisar.append("nome bateu em estagiários E terceirizados (homônimo?)")
                else:
                    reg["terceirizado_origem"] = "nao_consta_no_rh"
                    revisar.append("não consta no RH: marcado como terceirizado por inferência")
            if reg["vinculo"] == "estagiario":
                reg.update({"na_escola": True, "comprovacao": "sere"})
        if reg["nome_curto_risco_homonimo"] and achados:
            revisar.append("nome com até 2 palavras: maior risco de homônimo")
        registros.append(reg)
    return registros


# ─────────────────────────────── comprovação pelo holerite ───────────────────────────────

def _descrever_matricula(v: dict) -> str:
    partes = [str(v.get("numcad") or "?")]
    if v.get("titcar"):
        partes.append(str(v["titcar"]))
    if v.get("datadm"):
        partes.append(f"admissão {v['datadm']}")
    return " - ".join(partes)


def _anotar_vinculo(v: dict, r: Optional[dict], nome_escola: str) -> None:
    """Guarda na própria matrícula o que o holerite disse (local, cargo, admissão) e se ela está lotada aqui."""
    if r is None or r.get("erro") or r.get("estouro"):
        v["na_escola"] = None
    else:
        v["na_escola"] = local_confere(r.get("local"), nome_escola)
    if r is None:
        return
    v["local_holerite"] = r.get("local")
    v["cargo_holerite"] = r.get("cargo")
    if not v.get("titcar") and r.get("cargo"):                  # o cadastro do RH veio sem cargo: vale o do holerite
        v["titcar"] = r["cargo"]
    if not v.get("datadm") and r.get("admissao"):               # idem para a data de admissão
        v["datadm"] = r["admissao"]


def aplicar_comprovacao(reg: dict, resultados: dict[str, dict], nome_escola: str, mes: str) -> None:
    """
    Decide `na_escola` de um servidor a partir do holerite de cada matrícula candidata (`resultados`:
    matrícula → {"local","cargo","estouro","admissao","erro"}).
      - uma matrícula lotada aqui e outras não → fica só ela (homônimos); as outras vão para `vinculos_descartados`;
      - DUAS OU MAIS lotadas aqui → dois concursos (ex.: professor 20h + 20h): ficam todas, sem pedir revisão;
      - nenhuma lotada aqui → nada é descartado sem prova.
    """
    vinculos = reg["vinculos_servidores"]
    confirmados, divergentes, inconclusivos = [], [], []
    motivos: list[str] = []
    for v in vinculos:
        r = resultados.get(str(v.get("numcad")))
        _anotar_vinculo(v, r, nome_escola)
        if r is None:
            inconclusivos.append(v)
            motivos.append(f"matrícula {v.get('numcad')} não consultada")
        elif r.get("erro"):
            inconclusivos.append(v)
            motivos.append(f"holerite {v.get('numcad')}: {r['erro']}")
        elif r.get("estouro"):
            inconclusivos.append(v)
            motivos.append(f"holerite {v.get('numcad')}: rubrica 256 'Estouro do Mês' (cargo em comissão em outro lugar)")
        elif v["na_escola"]:
            confirmados.append(v)
        else:
            divergentes.append((v, r.get("local")))

    reg["holerite_mes"] = mes
    locais = [r.get("local") for r in resultados.values() if r.get("local")]
    reg["local_trabalho_holerite"] = locais[0] if locais else None
    reg.pop("observacao_vinculo", None)
    reg.pop("vinculos_descartados", None)

    if confirmados:
        if len(confirmados) < len(vinculos):
            reg["vinculos_descartados"] = [dict(v, motivo=("holerite aponta outro local de trabalho" if v.get("na_escola") is False
                                                           else "não deu para comprovar no holerite"))
                                           for v in vinculos if v not in confirmados]
            reg["vinculos_servidores"] = confirmados
            reg["revisar"] = [m for m in reg["revisar"] if "matrículas com esse nome" not in m]
            _aplicar_vinculo_principal(reg, confirmados[0])
            fora = "; ".join(f"{_descrever_matricula(v)} ({v.get('local_holerite') or 'sem local'})" for v in reg["vinculos_descartados"])
            reg["observacao_vinculo"] = (f"Fica a matrícula {_descrever_matricula(confirmados[0])}; descartada(s): {fora}. "
                                         "Homônimo ou segundo concurso em outro local.")
        reg["multiplas_matriculas"] = len(confirmados) > 1
        if len(confirmados) > 1:                                # 20h + 20h: duas matrículas, a mesma pessoa, a mesma escola
            reg["revisar"] = [m for m in reg["revisar"] if "matrículas com esse nome" not in m]
            reg["observacao_vinculo"] = (f"{len(confirmados)} matrículas lotadas nesta escola (dois concursos, ex.: 20h + 20h): "
                                         + "; ".join(_descrever_matricula(v) for v in confirmados) + ".")
            if reg.get("nome_curto_risco_homonimo"):            # nome curto: pode ser homônimo mesmo, então pede conferência
                reg["revisar"].append("duas matrículas lotadas aqui, mas o nome tem até 2 palavras: confira se é a mesma pessoa")
        local_ok = next((resultados[str(v["numcad"])]["local"] for v in confirmados), None)
        reg.update({"na_escola": True, "comprovacao": "holerite", "local_trabalho_holerite": local_ok})
    elif divergentes and not inconclusivos:
        reg.update({"na_escola": False, "comprovacao": "holerite"})
        reg["revisar"].append("o holerite aponta outro local de trabalho: " + "; ".join(f"{l or 'sem local'}" for _, l in divergentes)
                              + " (pode ser homônimo)")
    else:
        reg.update({"na_escola": None, "comprovacao": "nenhuma"})
        reg["revisar"].extend(motivos or ["sem holerite para comprovar"])


# ─────────────────────────────── ajustes manuais ───────────────────────────────

def carregar_ajustes() -> dict:
    try:
        ajustes = carregar_json(arquivo_ajustes(), dict, tipo_esperado=dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    return {(_so_digitos(k) or normalizar_nome(k)): v for k, v in ajustes.items() if isinstance(v, dict)}


def aplicar_ajustes(registros: list[dict], ajustes: dict) -> int:
    """Aplica os ajustes manuais (chave = CPF só com números, ou o nome). Devolve quantas pessoas foram ajustadas."""
    n = 0
    for reg in registros:
        aj = ajustes.get(_so_digitos(reg.get("cpf"))) or ajustes.get(normalizar_nome(reg.get("nome")))
        if not aj:
            continue
        n += 1
        reg["ajuste_manual"] = True
        if "terceirizado" in aj:
            reg["terceirizado"] = bool(aj["terceirizado"])
            if reg["terceirizado"]:
                reg["vinculo"] = "terceirizado"
                reg["terceirizado_origem"] = reg.get("terceirizado_origem") or "ajuste_manual"
            elif reg["vinculo"] == "terceirizado":
                reg["vinculo"], reg["terceirizado_origem"] = "outro", None
        if "na_escola" in aj:
            reg["na_escola"] = bool(aj["na_escola"])
            reg["comprovacao"] = "manual"
        if aj.get("observacao"):
            reg["observacao"] = str(aj["observacao"])
        reg["revisar"] = []                                     # a pessoa já foi revisada
    return n


# ─────────────────────────────── resumo ───────────────────────────────

def resumir(registros: list[dict]) -> dict:
    return {
        "total": len(registros),
        "servidores": sum(1 for r in registros if r["vinculo"] == "servidor"),
        "estagiarios": sum(1 for r in registros if r["vinculo"] == "estagiario"),
        "terceirizados": sum(1 for r in registros if r["terceirizado"]),
        "confirmados_na_escola": sum(1 for r in registros if r["na_escola"] is True),
        "fora_da_escola": sum(1 for r in registros if r["na_escola"] is False),
        "sem_comprovacao": sum(1 for r in registros if r["na_escola"] is None),
        "a_revisar": sum(1 for r in registros if r["revisar"]),
    }


def _imprimir_relatorio(registros: list[dict], resumo: dict) -> None:
    print(f"\n{resumo['total']} funcionário(s): {resumo['servidores']} servidor(es), {resumo['estagiarios']} estagiário(s), "
          f"{resumo['terceirizados']} terceirizado(s).")
    print(f"Na escola (comprovado): {resumo['confirmados_na_escola']} | outro local no holerite: {resumo['fora_da_escola']} | "
          f"sem comprovação: {resumo['sem_comprovacao']}")
    terc = [r["nome"] for r in registros if r["terceirizado"]]
    if terc:
        print("Terceirizados:")
        for n in terc[:LIMITE_LINHAS_LOG]:
            print(f"  - {n}")
    rev = [r for r in registros if r["revisar"]]
    if rev:
        print(f"Para revisar ({len(rev)}):")
        for r in rev[:LIMITE_LINHAS_LOG]:
            print(f"  - {r['nome']}: " + "; ".join(r["revisar"]))
        if len(rev) > LIMITE_LINHAS_LOG:
            print(f"  … e mais {len(rev) - LIMITE_LINHAS_LOG} (veja o arquivo).")
        print(f"Para resolver um caso à mão, edite {arquivo_ajustes().name} (veja a explicação no topo de funcionarios_vinculos.py).")


# ─────────────────────────────── ponto de entrada ───────────────────────────────

def normalizar_modo(modo: Optional[str], comprovar: bool = True) -> str:
    """Sem `modo` vale o comportamento antigo: `comprovar` False = só vincular; True = completo."""
    if modo is None or not str(modo).strip():
        return MODO_COMPLETO if comprovar else MODO_VINCULAR
    m = str(modo).strip().lower()
    if m not in MODOS:
        raise ValueError(f"Modo '{modo}' desconhecido: use " + ", ".join(f"'{x}'" for x in MODOS) + ".")
    return m


def validar_pedido(mes: str = "", modo: str = MODO_COMPLETO) -> str:
    """Confere o que dá para conferir antes de abrir qualquer conexão. Devolve o mês normalizado."""
    modo = normalizar_modo(modo)
    if modo == MODO_SERE:                                       # só lê o SERE: não usa mês, escola do holerite nem ajustes
        return ""
    mes = validar_mes(mes)
    if modo in MODOS_COM_HOLERITE and not escola.nome():
        raise ValueError("Informe o nome da escola em Configurações → Dados da escola: é com ele que o holerite é comparado.")
    carregar_ajustes()                                          # ajustes ilegíveis aparecem já, não no fim
    return mes


def _carregar_funcionarios_sere() -> list[dict]:
    try:
        dados = carregar_json(arquivo_sere(), list, tipo_esperado=list)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    return [d for d in dados if isinstance(d, dict) and _nome_do_funcionario(d)]


def _chave_pessoa(reg: dict) -> str:
    return _so_digitos(reg.get("cpf")) or normalizar_nome(reg.get("nome"))


def _carregar_saida_anterior() -> dict[str, dict]:
    """funcionarios_matriculas.json já gravado (por CPF ou nome); arquivo ruim ou ausente = nada a herdar."""
    try:
        dados = carregar_json(arquivo_saida(), list, tipo_esperado=list)
    except ArquivoJsonCorrompidoError:
        return {}
    return {_chave_pessoa(r): r for r in dados if isinstance(r, dict) and _chave_pessoa(r)}


_CAMPOS_HERDADOS = (*_CAMPOS_VINCULO, "vinculos_servidores", "vinculos_descartados", "multiplas_matriculas", "na_escola",
                    "comprovacao", "local_trabalho_holerite", "holerite_mes", "observacao_vinculo", "revisar")


def _herdar_comprovacao(reg: dict, anterior: Optional[dict]) -> bool:
    """
    Quem não foi verificado agora guarda o resultado da última verificação, desde que seja da MESMA pessoa nas MESMAS
    matrículas do RH (se o RH mudou, o resultado antigo não vale). Devolve True se herdou.
    """
    if not anterior or anterior.get("comprovacao") not in ("holerite", "manual"):
        return False
    antigas = {str(v.get("numcad")) for k in ("vinculos_servidores", "vinculos_descartados") for v in anterior.get(k) or []}
    atuais = {str(v.get("numcad")) for v in reg["vinculos_servidores"]}
    if not atuais or antigas != atuais:
        return False
    for campo in _CAMPOS_HERDADOS:
        if campo in anterior:
            reg[campo] = anterior[campo]
        elif campo in ("vinculos_descartados", "observacao_vinculo"):
            reg.pop(campo, None)                                # campos opcionais: se a rodada anterior não tinha, não ficam
    return True


def escolher_alvos_homonimos(registros: list[dict], so_nome: str = "") -> list[dict]:
    """
    Quem o modo 'homonimos' verifica no holerite: com `so_nome` (parte do nome ou CPF) só quem bate, mesmo com uma matrícula;
    sem ele, todos que casaram com MAIS DE UMA matrícula do RH.
    """
    filtro_cpf, filtro_nome = _so_digitos(so_nome), normalizar_nome(so_nome)
    if filtro_cpf or filtro_nome:
        achados = [r for r in registros if r["vinculos_servidores"] and (
            (filtro_cpf and _so_digitos(r.get("cpf")) == filtro_cpf) or (filtro_nome and filtro_nome in normalizar_nome(r.get("nome"))))]
        if not achados:
            raise ValueError(f"Ninguém da lista do SERE com vínculo no RH bate com '{so_nome}'.")
        return achados
    return [r for r in registros if len(r["vinculos_servidores"]) > 1]


def _imprimir_homonimos(alvos: list[dict]) -> None:
    if not alvos:
        print("Nenhum funcionário com mais de uma matrícula com o mesmo nome: nada a verificar.")
        return
    print(f"\nVerificação de homônimos / duas matrículas ({len(alvos)} pessoa(s)):")
    for r in alvos[:LIMITE_LINHAS_LOG]:
        if r.get("observacao_vinculo"):
            print(f"  - {r['nome']}: {r['observacao_vinculo']}")
        else:
            print(f"  - {r['nome']}: " + ("; ".join(r["revisar"]) or "sem decisão"))
    if len(alvos) > LIMITE_LINHAS_LOG:
        print(f"  … e mais {len(alvos) - LIMITE_LINHAS_LOG} (veja o arquivo).")


def _resumo_homonimos(alvos: list[dict]) -> dict:
    return {"verificados": len(alvos),
            "duas_matriculas_na_escola": sum(1 for r in alvos if r["multiplas_matriculas"] and r["na_escola"] is True),
            "desempatados": sum(1 for r in alvos if r.get("vinculos_descartados")),
            "sem_decisao": sum(1 for r in alvos if r["na_escola"] is not True)}


async def _consultar_sere() -> dict:
    """Modo 'sere': refaz funcionarios.json (coleta básica) e devolve só um resumo (sem dados pessoais)."""
    print("Consultando a lista de funcionários no SERE...")
    from src.automacao.servidores import coletar_servidores_via_login
    await coletar_servidores_via_login("basico")
    funcionarios = _carregar_funcionarios_sere()
    if not funcionarios:
        raise ValueError("A lista de funcionários do SERE veio vazia: confira as credenciais do SERE.")
    por_funcao: dict[str, int] = {}
    for f in funcionarios:
        chave = str(f.get("funcao") or "(sem função)").strip() or "(sem função)"
        por_funcao[chave] = por_funcao.get(chave, 0) + 1
    print(f"{len(funcionarios)} funcionário(s) no SERE:")
    for funcao, n in sorted(por_funcao.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>3}  {funcao}")
    print(f"\nArquivo salvo: {arquivo_sere()}")
    return {"modo": MODO_SERE, "total": len(funcionarios), "por_funcao": por_funcao, "arquivo": str(arquivo_sere())}


async def vincular_funcionarios_da_escola(comprovar: bool = True, mes: str = "", forcar_coleta: bool = False,
                                          atualizar_sere: bool = False, modo: Optional[str] = None,
                                          so_nome: str = "") -> dict:
    """
    Faz o fluxo do `modo` escolhido (ver o topo do módulo) e, nos modos que cruzam com o RH, grava
    funcionarios_matriculas.json. Devolve um RESUMO (os dados pessoais ficam no arquivo, não na resposta da tela).
    Sem `modo`, `comprovar` decide: True = completo, False = vincular (como antes dos modos existirem).
    """
    modo = normalizar_modo(modo, comprovar)
    mes = validar_pedido(mes, modo)
    if modo == MODO_SERE:
        return await _consultar_sere()
    nome_escola = escola.nome()
    usa_holerite = modo in MODOS_COM_HOLERITE

    # 1) lista do SERE
    funcionarios = [] if atualizar_sere else _carregar_funcionarios_sere()
    if atualizar_sere or not funcionarios:
        print("Coletando a lista de funcionários no SERE..." if atualizar_sere
              else "Ainda não há funcionarios.json: coletando a lista de funcionários no SERE primeiro...")
        from src.automacao.servidores import coletar_servidores_via_login
        await coletar_servidores_via_login("basico")
        funcionarios = _carregar_funcionarios_sere()
    if not funcionarios:
        raise ValueError("A lista de funcionários do SERE está vazia: confira a coleta e as credenciais do SERE.")
    print(f"{len(funcionarios)} funcionário(s) no SERE.")

    # 2) RH
    session = requests.Session()
    servidores_rh = await asyncio.to_thread(obter_servidores_rh, forcar_coleta, session)
    idx_serv = construir_indice(servidores_rh)

    idx_est = idx_ter = None
    if precisa_listas_extras(funcionarios, idx_serv):
        est, erro_est = await asyncio.to_thread(obter_lista_extra, "estagiarios", forcar_coleta, session)
        ter, erro_ter = await asyncio.to_thread(obter_lista_extra, "terceirizados", forcar_coleta, session)
        for rotulo, erro in (("estagiários", erro_est), ("terceirizados", erro_ter)):
            if erro:
                print(f"Aviso: não consegui ler a lista de {rotulo} do RH ({erro}); seguindo sem ela.")
        idx_est = construir_indice(est) if not erro_est else None
        idx_ter = construir_indice(ter) if not erro_ter else None

    # 3) cruzamento por nome
    registros = classificar(funcionarios, idx_serv, idx_est, idx_ter)
    casados = [r for r in registros if r["vinculos_servidores"]]
    print(f"Cruzamento por nome: {len(casados)} servidor(es) casado(s), "
          f"{sum(1 for r in registros if r['terceirizado'])} terceirizado(s), "
          f"{sum(1 for r in registros if r['vinculo'] == 'estagiario')} estagiário(s).")

    # 4) comprovação no holerite (completo: todos; homônimos: só os alvos, os demais herdam o que já estava gravado)
    alvos: list[dict] = []
    if modo == MODO_COMPLETO and casados:
        await _comprovar_no_holerite(casados, mes, nome_escola, session)
    elif modo == MODO_HOMONIMOS:
        alvos = escolher_alvos_homonimos(registros, so_nome)
        anteriores = _carregar_saida_anterior()
        ids_alvos = {id(r) for r in alvos}
        herdados = sum(1 for r in casados if id(r) not in ids_alvos and _herdar_comprovacao(r, anteriores.get(_chave_pessoa(r))))
        if herdados:
            print(f"{herdados} servidor(es) fora da verificação mantêm o resultado da última rodada.")
        if alvos:
            await _comprovar_no_holerite(alvos, mes, nome_escola, session)
    elif casados:
        print("Comprovação pelo holerite pulada (modo sem holerite).")

    # 5) ajustes manuais e saída
    ajustados = aplicar_ajustes(registros, carregar_ajustes())
    if ajustados:
        print(f"{ajustados} pessoa(s) com ajuste manual aplicado.")
    salvar_json_atomico(arquivo_saida(), registros)
    resumo = resumir(registros)
    if modo == MODO_HOMONIMOS:
        _imprimir_homonimos(alvos)
    _imprimir_relatorio(registros, resumo)
    print(f"\nArquivo salvo: {arquivo_saida()}")
    saida = {**resumo, "modo": modo, "arquivo": str(arquivo_saida()), "holerite_mes": mes if usa_holerite else None,
             "comprovou": usa_holerite and bool(alvos if modo == MODO_HOMONIMOS else casados)}
    if modo == MODO_HOMONIMOS:
        saida.update(_resumo_homonimos(alvos))
    return saida


def _carregar_cache_holerites() -> dict:
    try:
        return carregar_json(arquivo_cache_holerites(), dict, tipo_esperado=dict)
    except ArquivoJsonCorrompidoError:
        return {}                                               # cache ruim não impede nada: refaz as consultas


async def _comprovar_no_holerite(casados: list[dict], mes: str, nome_escola: str, session: requests.Session,
                                 consultar: Optional[Callable] = None) -> None:
    consultar = consultar or consultar_holerite                 # resolvido na chamada (e não na definição)
    cache = _carregar_cache_holerites()
    pendentes = sum(1 for r in casados for v in r["vinculos_servidores"][:MAX_CANDIDATOS_HOLERITE]
                    if f"{v.get('numcad')}_{mes}" not in cache)
    print(f"Comprovando no holerite de {mes}: {pendentes} consulta(s) ao RH"
          + (f" (cerca de {max(1, round(pendentes * PAUSA_HOLERITE_S / 60))} min)" if pendentes and PAUSA_HOLERITE_S else "") + "...")
    total = len(casados)
    for i, reg in enumerate(casados, 1):
        candidatos = reg["vinculos_servidores"]
        resultados: dict[str, dict] = {}
        if len(candidatos) > MAX_CANDIDATOS_HOLERITE:
            reg["revisar"].append(f"{len(candidatos)} matrículas com esse nome: muitas para consultar")
        for v in candidatos[:MAX_CANDIDATOS_HOLERITE]:
            matricula = _so_digitos(v.get("numcad"))
            if not matricula:
                continue
            chave = f"{matricula}_{mes}"
            if chave in cache:
                resultados[matricula] = cache[chave]
                continue
            r = await asyncio.to_thread(consultar, session, matricula, mes)
            resultados[matricula] = r
            if not r.get("erro"):                               # só resultado bom entra no cache; o holerite em si não é guardado
                cache[chave] = {k: r.get(k) for k in ("local", "cargo", "estouro", "admissao")}
                salvar_json_atomico(arquivo_cache_holerites(), cache)
            if PAUSA_HOLERITE_S:
                await asyncio.sleep(PAUSA_HOLERITE_S)
        aplicar_comprovacao(reg, resultados, nome_escola, mes)
        marca = {True: "na escola", False: "OUTRO LOCAL", None: "sem comprovação"}[reg["na_escola"]]
        print(f"  [{i}/{total}] {reg['nome']}: {marca}" + (f" ({reg['local_trabalho_holerite']})" if reg["local_trabalho_holerite"] else ""))

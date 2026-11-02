"""
Calendário letivo — API do Auto SERE
=====================================
Períodos letivos, recessos e feriados municipais (cadastrados pelo usuário)
combinados com os feriados nacionais da BrasilAPI.

Rotas (registradas em src/web/app.py com url_prefix="/web/api/calendario"):

    GET    /web/api/calendario/dados            eventos + períodos
    GET    /web/api/calendario/feriados/<ano>   feriados nacionais (cache em disco)
    GET    /web/api/calendario/fixos/<ano>      feriados fixos de Ponta Grossa + datas comemorativas
    POST   /web/api/calendario/eventos          cria recesso/feriado municipal
    DELETE /web/api/calendario/eventos/<id>
    POST   /web/api/calendario/periodos         cria período letivo
    DELETE /web/api/calendario/periodos/<id>

Persistência (fora do controle de versão junto com o resto de dados/):

    dados/<ano letivo>/calendario.json     eventos e períodos do ANO LETIVO em uso (um arquivo por ano)
    dados/calendario/feriados_cache/AAAA.json   cache dos feriados nacionais (por ano civil, comum a todos)

O calendário acompanha o ano letivo escolhido em Configurações → Ano letivo, como os demais dados: voltando para
2025, aparece o calendário de 2025 (em modo somente consulta, como o resto). Cadastros novos vão para o arquivo do
ano letivo em uso.

Como o calendário atravessa anos (ex.: férias de 19/12/2025 a 03/02/2026), a tela mostra os itens do ano em uso e,
dos arquivos do ano anterior e do seguinte, só os que tocam o ano civil mostrado (as férias de dezembro continuam
aparecendo em janeiro). Um item é sempre gravado no arquivo do ano letivo em que foi cadastrado.

O arquivo antigo, único para todos os anos (dados/calendario/calendario.json), é dividido por ano na primeira vez
(pelo ano da data de início de cada item) e guardado como calendario.json.antes-da-migracao.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, request

from src.comum import paths as _paths

calendario_bp = Blueprint("calendario", __name__)

BRASILAPI_URL = "https://brasilapi.com.br/api/feriados/v1/{ano}"
CACHE_VALIDADE = 30 * 24 * 3600  # 30 dias
# Tipos de evento cadastrável (cor na tela):
#   municipal -> vermelho | recesso, emenda -> azul claro | htpc -> verde-limão | outro -> cinza
TIPOS_EVENTO = {"municipal", "recesso", "emenda", "htpc", "outro"}
# Tipos de período: letivo (sem cor, conta dias letivos) | ferias (amarelo)
TIPOS_PERIODO = {"letivo", "ferias"}

# --- Datas fixas de Ponta Grossa (valem todo ano; edite aqui se mudar) -------
# (mês, dia, nome). Entram como FERIADO (vermelho) e tiram o dia letivo.
FERIADOS_MUNICIPAIS_FIXOS = [
    (7, 26, "Padroeira da cidade"),
    (9, 15, "Aniversário da cidade"),
]
# Dia do Servidor Público (28/10) fica de fora de propósito: a data é alterada
# por decreto quase todo ano. Se for decretado, cadastre como evento.

# Datas comemorativas: aparecem com estrela roxa e NÃO tiram o dia letivo.
DATAS_COMEMORATIVAS = [
    (5, 30, "Dia do Assistente de Educação"),
    (8, 22, "Dia da Pedagoga"),
    (9, 30, "Dia do Escriturário"),
    (10, 15, "Dia do Professor"),
    (10, 30, "Dia da Merendeira"),
    (10, 31, "Dia da Servente Escolar"),
    (11, 12, "Dia do Diretor Escolar"),
]

_lock = threading.Lock()


# ---------------------------------------------------------------- persistência
def _pasta() -> Path:
    """Pasta comum do calendário (só o cache de feriados; função, para os testes poderem trocar)."""
    return _paths.DADOS_DIR / "calendario"


def _pasta_cache() -> Path:
    return _pasta() / "feriados_cache"


def _garantir_pastas() -> None:
    _pasta_cache().mkdir(parents=True, exist_ok=True)


def _ano_ativo() -> int:
    """Ano letivo em uso (Configurações → Ano letivo; senão o ano do calendário)."""
    try:
        return int(_paths.ano_atual())
    except (TypeError, ValueError):
        return date.today().year


def _arquivo_dados(ano: int | None = None) -> Path:
    """dados/<ano letivo>/calendario.json (do ano em uso se `ano` não for dado)."""
    return _paths.DADOS_DIR / str(ano if ano is not None else _ano_ativo()) / "calendario.json"


def _normalizar(dados) -> dict:
    if not isinstance(dados, dict):
        dados = {}
    dados.setdefault("eventos", [])
    dados.setdefault("periodos", [])
    # Períodos gravados antes de existir o campo "tipo": "férias" no nome -> ferias.
    for p in dados["periodos"]:
        if p.get("tipo") not in TIPOS_PERIODO:
            nome = (p.get("nome") or "").upper().replace("É", "E")
            p["tipo"] = "ferias" if "FERIAS" in nome else "letivo"
    return dados


def _ler_ano(ano: int) -> dict:
    """Eventos e períodos gravados no arquivo desse ano letivo (vazio se não existir). Levanta ValueError se o JSON for inválido."""
    arquivo = _arquivo_dados(ano)
    if not arquivo.exists():
        return {"eventos": [], "periodos": []}
    with open(arquivo, encoding="utf-8") as f:
        return _normalizar(json.load(f))


def _salvar_ano(ano: int, dados: dict) -> None:
    """Grava de forma atômica para não corromper o JSON se o processo cair."""
    arquivo = _arquivo_dados(ano)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=arquivo.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, arquivo)


def salvar_dados(dados: dict, ano: int | None = None) -> None:
    _salvar_ano(ano if ano is not None else _ano_ativo(), dados)


def _migrar_legado() -> None:
    """
    Divide o arquivo antigo (dados/calendario/calendario.json, um só para todos os anos) em dados/<ano>/calendario.json,
    pelo ano da data de início de cada item (sem data válida, vai para o ano em uso). Não repete itens que já estejam
    no arquivo do ano (mesmo id) e guarda o arquivo antigo como calendario.json.antes-da-migracao.
    """
    legado = _pasta() / "calendario.json"
    if not legado.exists():
        return
    with open(legado, encoding="utf-8") as f:
        antigo = _normalizar(json.load(f))
    por_ano: dict[int, dict] = {}
    for chave in ("eventos", "periodos"):
        for item in antigo[chave]:
            d = _data_iso(item.get("inicio"))
            ano = d.year if d else _ano_ativo()
            por_ano.setdefault(ano, {"eventos": [], "periodos": []})[chave].append(item)
    for ano, itens in por_ano.items():
        atual = _ler_ano(ano)
        for chave in ("eventos", "periodos"):
            ids = {x.get("id") for x in atual[chave]}
            atual[chave] += [x for x in itens[chave] if x.get("id") not in ids]
        _salvar_ano(ano, atual)
    destino = legado.with_name("calendario.json.antes-da-migracao")
    if destino.exists():
        destino = legado.with_name(f"calendario.json.antes-da-migracao-{int(time.time())}")
    os.replace(legado, destino)


def _toca_o_ano(item: dict, ano: int) -> bool:
    """O item (inicio/fim ISO) tem algum dia dentro do ano civil `ano`?"""
    inicio, fim = str(item.get("inicio") or ""), str(item.get("fim") or item.get("inicio") or "")
    return bool(inicio) and inicio <= f"{ano}-12-31" and fim >= f"{ano}-01-01"


def carregar_dados() -> dict:
    """
    O que a tela mostra: tudo do arquivo do ano letivo em uso + os itens dos arquivos do ano anterior e do seguinte
    que tocam este ano (férias que atravessam a virada). Cada id aparece uma vez.
    """
    _migrar_legado()
    ano = _ano_ativo()
    resultado = {"eventos": [], "periodos": []}
    vistos: dict[str, set] = {"eventos": set(), "periodos": set()}
    for y in (ano, ano - 1, ano + 1):
        dados = _ler_ano(y)
        for chave in ("eventos", "periodos"):
            for item in dados[chave]:
                if item.get("id") in vistos[chave]:
                    continue
                if y == ano or _toca_o_ano(item, ano):
                    vistos[chave].add(item.get("id"))
                    resultado[chave].append(item)
    resultado["ano_letivo"] = str(ano)
    return resultado


def _remover_item(chave: str, id_: str) -> bool:
    """Apaga o item `id_` ("eventos"/"periodos") do arquivo do ano em uso ou dos vizinhos. False se não achou."""
    _migrar_legado()
    ano = _ano_ativo()
    for y in (ano, ano - 1, ano + 1):
        dados = _ler_ano(y)
        antes = len(dados[chave])
        dados[chave] = [x for x in dados[chave] if x.get("id") != id_]
        if len(dados[chave]) != antes:
            _salvar_ano(y, dados)
            return True
    return False


# ---------------------------------------------------------------- datas fixas
def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anônimo / Meeus-Jones-Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def datas_fixas(ano: int) -> list[dict]:
    """Feriados fixos da cidade (+ Quarta-feira de Cinzas) e datas comemorativas do ano."""
    itens = [
        {"date": date(ano, m, d).isoformat(), "name": nome, "tipo": "municipal"}
        for m, d, nome in FERIADOS_MUNICIPAIS_FIXOS
    ]
    cinzas = pascoa(ano) - timedelta(days=46)  # móvel, segue o calendário católico
    itens.append({"date": cinzas.isoformat(), "name": "Quarta-feira de Cinzas", "tipo": "municipal"})
    itens += [
        {"date": date(ano, m, d).isoformat(), "name": nome, "tipo": "comemorativa"}
        for m, d, nome in DATAS_COMEMORATIVAS
    ]
    return sorted(itens, key=lambda x: x["date"])


# ------------------------------------------------------------------ validação
def _data_iso(valor):
    try:
        d = date.fromisoformat(str(valor))
    except ValueError:
        return None
    return d if 1900 <= d.year <= 2100 else None


def _erro(msg: str, codigo: int = 400):
    # Chave "erro": é a que o frontend (apiPost / calendario.js) já lê.
    return jsonify({"erro": msg}), codigo


# ---------------------------------------------------------------------- rotas
@calendario_bp.get("/dados")
def obter_dados():
    with _lock:
        try:
            return jsonify(carregar_dados())
        except (OSError, ValueError):
            return _erro("Não foi possível ler o arquivo do calendário (JSON inválido?).", 500)


@calendario_bp.get("/feriados/<int:ano>")
def feriados_nacionais(ano: int):
    """Feriados nacionais via BrasilAPI, com cache em disco (evita CORS e reduz chamadas)."""
    if not 1900 <= ano <= 2100:
        return _erro("Ano fora do intervalo suportado (1900–2100).")

    _garantir_pastas()
    cache = _pasta_cache() / f"{ano}.json"
    cache_valido = cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_VALIDADE
    if cache_valido:
        return jsonify(json.loads(cache.read_text(encoding="utf-8")))

    try:
        req = urllib.request.Request(
            BRASILAPI_URL.format(ano=ano), headers={"User-Agent": "auto-sere-calendario/1.0"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            lista = json.loads(resp.read().decode("utf-8"))
        cache.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
        return jsonify(lista)
    except (urllib.error.URLError, TimeoutError, ValueError):
        # Sem internet ou API fora do ar: usa o cache antigo, se existir.
        if cache.exists():
            return jsonify(json.loads(cache.read_text(encoding="utf-8")))
        return _erro("Não foi possível consultar a BrasilAPI e não há cache para este ano.", 502)


@calendario_bp.get("/fixos/<int:ano>")
def fixos(ano: int):
    if not 1900 <= ano <= 2100:
        return _erro("Ano fora do intervalo suportado (1900–2100).")
    return jsonify(datas_fixas(ano))


@calendario_bp.post("/eventos")
def criar_evento():
    d = request.get_json(silent=True) or {}
    nome = (d.get("nome") or "").strip()
    tipo = d.get("tipo", "municipal")
    inicio = _data_iso(d.get("inicio"))
    fim = _data_iso(d.get("fim")) if d.get("fim") else inicio

    if not nome:
        return _erro("Informe o nome.")
    if tipo not in TIPOS_EVENTO:
        return _erro("Tipo inválido.")
    if not inicio or not fim:
        return _erro("Data inválida.")
    if fim < inicio:
        return _erro("A data final não pode ser anterior à inicial.")

    evento = {
        "id": uuid.uuid4().hex[:8],
        "nome": nome,
        "tipo": tipo,
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
    }
    with _lock:
        _migrar_legado()
        ano = _ano_ativo()
        dados = _ler_ano(ano)
        dados["eventos"].append(evento)
        _salvar_ano(ano, dados)
    return jsonify(evento), 201


@calendario_bp.delete("/eventos/<id_>")
def excluir_evento(id_: str):
    with _lock:
        if not _remover_item("eventos", id_):
            return _erro("Registro não encontrado.", 404)
    return jsonify({"ok": True})


@calendario_bp.post("/periodos")
def criar_periodo():
    d = request.get_json(silent=True) or {}
    nome = (d.get("nome") or "").strip()
    tipo = d.get("tipo", "letivo")
    inicio = _data_iso(d.get("inicio"))
    fim = _data_iso(d.get("fim"))

    if not nome:
        return _erro("Informe o nome do período.")
    if tipo not in TIPOS_PERIODO:
        return _erro("Tipo de período inválido.")
    if not inicio or not fim:
        return _erro("Informe as datas de início e fim.")
    if fim < inicio:
        return _erro("A data final não pode ser anterior à inicial.")

    periodo = {
        "id": uuid.uuid4().hex[:8],
        "nome": nome,
        "tipo": tipo,
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
    }
    with _lock:
        _migrar_legado()
        ano = _ano_ativo()
        dados = _ler_ano(ano)
        dados["periodos"].append(periodo)
        _salvar_ano(ano, dados)
    return jsonify(periodo), 201


@calendario_bp.delete("/periodos/<id_>")
def excluir_periodo(id_: str):
    with _lock:
        if not _remover_item("periodos", id_):
            return _erro("Registro não encontrado.", 404)
    return jsonify({"ok": True})

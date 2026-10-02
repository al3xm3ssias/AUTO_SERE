"""
Testes da API do calendário letivo (src/web/api/calendario.py).

Não acessam a internet: o cache de feriados é pré-populado e a BrasilAPI é
simulada nos casos de falha. Os dados vão para uma pasta temporária.
"""

import json
import sys
import urllib.error
from pathlib import Path

import pytest
from flask import Flask

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from src.web.api import calendario as cal  # noqa: E402

PREFIXO = "/web/api/calendario"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "_pasta", lambda: tmp_path / "calendario")
    app = Flask(__name__)
    app.register_blueprint(cal.calendario_bp, url_prefix=PREFIXO)
    return app.test_client()


def test_dados_vazios_na_primeira_vez(client):
    r = client.get(f"{PREFIXO}/dados")
    assert r.status_code == 200
    assert r.get_json() == {"eventos": [], "periodos": []}


def test_criar_e_excluir_evento(client):
    r = client.post(f"{PREFIXO}/eventos", json={"nome": " Recesso ", "tipo": "recesso", "inicio": "2026-10-13"})
    assert r.status_code == 201
    ev = r.get_json()
    assert ev["nome"] == "Recesso" and ev["fim"] == "2026-10-13"

    assert len(client.get(f"{PREFIXO}/dados").get_json()["eventos"]) == 1
    assert client.delete(f"{PREFIXO}/eventos/{ev['id']}").status_code == 200
    assert client.get(f"{PREFIXO}/dados").get_json()["eventos"] == []
    assert client.delete(f"{PREFIXO}/eventos/{ev['id']}").status_code == 404


@pytest.mark.parametrize(
    "corpo",
    [
        {"nome": "", "inicio": "2026-10-13"},
        {"nome": "X", "tipo": "inexistente", "inicio": "2026-10-13"},
        {"nome": "X", "inicio": "13/10/2026"},
        {"nome": "X", "inicio": "2026-10-13", "fim": "2026-10-01"},
    ],
)
def test_evento_invalido(client, corpo):
    r = client.post(f"{PREFIXO}/eventos", json=corpo)
    assert r.status_code == 400
    assert "erro" in r.get_json()


def test_criar_e_excluir_periodo(client):
    r = client.post(f"{PREFIXO}/periodos", json={"nome": "1º bimestre", "inicio": "2026-02-04", "fim": "2026-04-17"})
    assert r.status_code == 201
    p = r.get_json()
    assert client.get(f"{PREFIXO}/dados").get_json()["periodos"][0]["id"] == p["id"]
    assert client.delete(f"{PREFIXO}/periodos/{p['id']}").status_code == 200
    assert client.delete(f"{PREFIXO}/periodos/{p['id']}").status_code == 404


def test_periodo_com_fim_antes_do_inicio(client):
    r = client.post(f"{PREFIXO}/periodos", json={"nome": "X", "inicio": "2026-05-10", "fim": "2026-05-01"})
    assert r.status_code == 400


def test_feriados_usa_cache_sem_internet(client, tmp_path, monkeypatch):
    cache = tmp_path / "calendario" / "feriados_cache"
    cache.mkdir(parents=True)
    (cache / "2026.json").write_text(json.dumps([{"date": "2026-01-01", "name": "Confraternização mundial"}]), encoding="utf-8")

    def sem_rede(*a, **k):
        raise AssertionError("não deveria consultar a BrasilAPI com cache válido")

    monkeypatch.setattr(cal.urllib.request, "urlopen", sem_rede)
    r = client.get(f"{PREFIXO}/feriados/2026")
    assert r.status_code == 200 and r.get_json()[0]["date"] == "2026-01-01"


def test_feriados_sem_cache_e_sem_internet_retorna_502(client, monkeypatch):
    def falha(*a, **k):
        raise urllib.error.URLError("sem rede")

    monkeypatch.setattr(cal.urllib.request, "urlopen", falha)
    r = client.get(f"{PREFIXO}/feriados/2030")
    assert r.status_code == 502 and "erro" in r.get_json()


def test_feriados_ano_fora_do_intervalo(client):
    assert client.get(f"{PREFIXO}/feriados/1800").status_code == 400
    assert client.get(f"{PREFIXO}/feriados/2500").status_code == 400


# ----------------------------------------------------------- padrão de cores
@pytest.mark.parametrize("tipo", ["municipal", "recesso", "emenda", "htpc", "outro"])
def test_tipos_de_evento_aceitos(client, tipo):
    r = client.post(f"{PREFIXO}/eventos", json={"nome": "X", "tipo": tipo, "inicio": "2026-10-13"})
    assert r.status_code == 201 and r.get_json()["tipo"] == tipo


def test_periodo_tipo_padrao_letivo_e_ferias(client):
    r = client.post(f"{PREFIXO}/periodos", json={"nome": "1º bim", "inicio": "2026-02-04", "fim": "2026-04-17"})
    assert r.get_json()["tipo"] == "letivo"
    r = client.post(f"{PREFIXO}/periodos", json={"nome": "Férias", "tipo": "ferias", "inicio": "2026-07-13", "fim": "2026-07-27"})
    assert r.status_code == 201 and r.get_json()["tipo"] == "ferias"
    r = client.post(f"{PREFIXO}/periodos", json={"nome": "X", "tipo": "xyz", "inicio": "2026-07-13", "fim": "2026-07-27"})
    assert r.status_code == 400


def test_periodo_antigo_sem_tipo_infere_ferias(client, tmp_path):
    pasta = tmp_path / "calendario"
    pasta.mkdir()
    (pasta / "calendario.json").write_text(json.dumps({"eventos": [], "periodos": [
        {"id": "a", "nome": "FÉRIAS ESCOLARES", "inicio": "2026-07-13", "fim": "2026-07-27"},
        {"id": "b", "nome": "1º bimestre", "inicio": "2026-02-04", "fim": "2026-04-17"},
    ]}), encoding="utf-8")
    tipos = {p["id"]: p["tipo"] for p in client.get(f"{PREFIXO}/dados").get_json()["periodos"]}
    assert tipos == {"a": "ferias", "b": "letivo"}


# ------------------------------------------------- datas fixas (Ponta Grossa)
def test_pascoa_conhecidas():
    assert cal.pascoa(2025).isoformat() == "2025-04-20"
    assert cal.pascoa(2026).isoformat() == "2026-04-05"
    assert cal.pascoa(2027).isoformat() == "2027-03-28"


def test_fixos_2026(client):
    itens = client.get(f"{PREFIXO}/fixos/2026").get_json()
    por_data = {i["date"]: i for i in itens}
    # feriados da cidade + Cinzas (móvel) => municipal (vermelho)
    assert por_data["2026-09-15"]["tipo"] == "municipal"
    assert por_data["2026-07-26"]["tipo"] == "municipal"
    assert por_data["2026-02-18"]["name"] == "Quarta-feira de Cinzas"
    # 7 datas comemorativas (estrela roxa)
    com = {i["date"] for i in itens if i["tipo"] == "comemorativa"}
    assert com == {"2026-05-30", "2026-08-22", "2026-09-30", "2026-10-15", "2026-10-30", "2026-10-31", "2026-11-12"}
    # Dia do Servidor (28/10) fica de fora de propósito
    assert "2026-10-28" not in por_data


def test_cinzas_muda_conforme_o_ano(client):
    cinzas = {a: next(i["date"] for i in client.get(f"{PREFIXO}/fixos/{a}").get_json() if i["name"].startswith("Quarta"))
              for a in (2026, 2027)}
    assert cinzas == {2026: "2026-02-18", 2027: "2027-02-10"}


def test_fixos_ano_invalido(client):
    assert client.get(f"{PREFIXO}/fixos/1800").status_code == 400

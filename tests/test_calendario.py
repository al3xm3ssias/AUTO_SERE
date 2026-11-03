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
def ano_letivo(monkeypatch):
    """Ano letivo em uso nos testes; `ano_letivo["ano"] = "2025"` simula voltar o ano em Configurações."""
    estado = {"ano": "2026"}
    monkeypatch.setattr(cal._paths, "ano_atual", lambda: estado["ano"])
    return estado


@pytest.fixture
def client(tmp_path, monkeypatch, ano_letivo):
    monkeypatch.setattr(cal._paths, "DADOS_DIR", tmp_path)       # dados/<ano>/calendario.json e dados/calendario/ (cache)
    app = Flask(__name__)
    app.register_blueprint(cal.calendario_bp, url_prefix=PREFIXO)
    return app.test_client()


def test_dados_vazios_na_primeira_vez(client):
    r = client.get(f"{PREFIXO}/dados")
    assert r.status_code == 200
    assert r.get_json() == {"eventos": [], "periodos": [], "ano_letivo": "2026"}


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


# ------------------------------------------- um calendário por ano letivo (dados/<ano>/calendario.json)
def _evento(client, nome, inicio, fim=None):
    corpo = {"nome": nome, "tipo": "recesso", "inicio": inicio}
    if fim:
        corpo["fim"] = fim
    r = client.post(f"{PREFIXO}/eventos", json=corpo)
    assert r.status_code == 201
    return r.get_json()


def _nomes(client, chave="eventos"):
    return sorted(x["nome"] for x in client.get(f"{PREFIXO}/dados").get_json()[chave])


def test_o_calendario_e_gravado_na_pasta_do_ano_letivo(client, tmp_path, ano_letivo):
    _evento(client, "Recesso 2026", "2026-10-13")
    assert json.loads((tmp_path / "2026" / "calendario.json").read_text(encoding="utf-8"))["eventos"][0]["nome"] == "Recesso 2026"
    assert not (tmp_path / "calendario" / "calendario.json").exists()          # não usa mais o arquivo único


def test_voltar_o_ano_letivo_volta_o_calendario_daquele_ano(client, tmp_path, ano_letivo):
    _evento(client, "Recesso 2026", "2026-10-13")
    ano_letivo["ano"] = "2025"
    assert _nomes(client) == []                                                # 2025 ainda não tem nada
    assert client.get(f"{PREFIXO}/dados").get_json()["ano_letivo"] == "2025"
    _evento(client, "Recesso 2025", "2025-10-14")                              # (a trava de somente consulta fica no app)
    assert _nomes(client) == ["Recesso 2025"]
    assert client.post(f"{PREFIXO}/periodos", json={"nome": "1º bim 2025", "inicio": "2025-02-03", "fim": "2025-04-17"}).status_code == 201
    ano_letivo["ano"] = "2026"
    assert _nomes(client) == ["Recesso 2026"] and _nomes(client, "periodos") == []
    assert (tmp_path / "2025" / "calendario.json").exists() and (tmp_path / "2026" / "calendario.json").exists()


def test_ferias_que_atravessam_a_virada_aparecem_nos_dois_anos(client, ano_letivo):
    _evento(client, "Natal", "2026-12-21", "2027-01-04")                       # cadastrado no ano letivo 2026
    ano_letivo["ano"] = "2027"
    assert _nomes(client) == ["Natal"]                                         # janeiro de 2027 ainda mostra
    ano_letivo["ano"] = "2026"
    assert _nomes(client) == ["Natal"]


def test_item_do_ano_vizinho_que_nao_toca_o_ano_nao_aparece(client, ano_letivo):
    ano_letivo["ano"] = "2025"                                                 # cadastrados no ano letivo 2025
    _evento(client, "Só em 2025", "2025-05-02")
    _evento(client, "Vira o ano", "2025-12-22", "2026-01-05")
    ano_letivo["ano"] = "2026"
    assert _nomes(client) == ["Vira o ano"]


def test_exclui_item_que_esta_no_arquivo_do_ano_vizinho(client, ano_letivo):
    ev = _evento(client, "Vira o ano", "2026-12-22", "2027-01-05")
    ano_letivo["ano"] = "2027"
    assert client.delete(f"{PREFIXO}/eventos/{ev['id']}").status_code == 200
    assert _nomes(client) == []
    ano_letivo["ano"] = "2026"
    assert _nomes(client) == []                                                # saiu do arquivo de 2026


def test_arquivo_antigo_unico_e_dividido_por_ano_e_guardado(client, tmp_path, ano_letivo):
    legado = tmp_path / "calendario"
    legado.mkdir()
    (legado / "calendario.json").write_text(json.dumps({
        "eventos": [{"id": "a", "nome": "Recesso 25", "tipo": "recesso", "inicio": "2025-10-14", "fim": "2025-10-14"},
                    {"id": "b", "nome": "Recesso 26", "tipo": "recesso", "inicio": "2026-10-13", "fim": "2026-10-13"}],
        "periodos": [{"id": "c", "nome": "Férias", "tipo": "ferias", "inicio": "2025-12-19", "fim": "2026-02-03"}],
    }), encoding="utf-8")
    assert _nomes(client) == ["Recesso 26"]                                    # visão de 2026
    assert _nomes(client, "periodos") == ["Férias"]                            # as férias de 19/12/2025 chegam a 2026
    por_ano = {a: json.loads((tmp_path / a / "calendario.json").read_text(encoding="utf-8")) for a in ("2025", "2026")}
    assert [e["id"] for e in por_ano["2025"]["eventos"]] == ["a"] and [p["id"] for p in por_ano["2025"]["periodos"]] == ["c"]
    assert [e["id"] for e in por_ano["2026"]["eventos"]] == ["b"]
    assert not (legado / "calendario.json").exists() and (legado / "calendario.json.antes-da-migracao").exists()
    ano_letivo["ano"] = "2025"
    assert _nomes(client) == ["Recesso 25"]                                    # e o de 2025 está lá
    assert _nomes(client, "periodos") == ["Férias"]


def test_migracao_nao_duplica_item_que_ja_esta_no_arquivo_do_ano(client, tmp_path):
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "calendario.json").write_text(json.dumps({"eventos": [
        {"id": "b", "nome": "Recesso 26", "tipo": "recesso", "inicio": "2026-10-13", "fim": "2026-10-13"}], "periodos": []}), encoding="utf-8")
    (tmp_path / "calendario").mkdir()
    (tmp_path / "calendario" / "calendario.json").write_text(json.dumps({"eventos": [
        {"id": "b", "nome": "Recesso 26", "tipo": "recesso", "inicio": "2026-10-13", "fim": "2026-10-13"}], "periodos": []}), encoding="utf-8")
    assert _nomes(client) == ["Recesso 26"]


def test_o_cache_de_feriados_continua_comum_a_todos_os_anos(client, tmp_path, ano_letivo):
    cache = tmp_path / "calendario" / "feriados_cache"
    cache.mkdir(parents=True)
    (cache / "2026.json").write_text(json.dumps([{"date": "2026-01-01", "name": "Confraternização Universal"}]), encoding="utf-8")
    assert client.get(f"{PREFIXO}/feriados/2026").status_code == 200
    ano_letivo["ano"] = "2025"
    assert client.get(f"{PREFIXO}/feriados/2026").status_code == 200           # mesmo cache, não depende do ano letivo

"""Configurações → login e senha do RCO (RCO_LOGIN / RCO_SENHA), com fallback para o SERE."""
import importlib
import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import paths  # noqa: E402
from src.web.app import create_app  # noqa: E402

URL = "/web/api/configuracoes/rco"
VARS = ("SERE_LOGIN", "SERE_SENHA", "RCO_LOGIN", "RCO_SENHA", "RCDIG_LOGIN", "RCDIG_SENHA")


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path)
    for v in VARS:
        monkeypatch.setenv(v, "")
    import src.comum.credenciais as cred
    importlib.reload(cred)
    yield create_app().test_client()
    for f in tmp_path.glob(".env"):
        f.unlink()
    for v in VARS:
        os.environ.pop(v, None)
    importlib.reload(cred)


def _salvar_sere(tmp_path, login="12345678900", senha="senha-sere"):
    (tmp_path / ".env").write_text(f"SERE_LOGIN='{login}'\nSERE_SENHA='{senha}'\n", encoding="utf-8")
    from dotenv import load_dotenv
    load_dotenv(tmp_path / ".env", override=True)
    import src.comum.credenciais as cred
    importlib.reload(cred)


def test_estado_inicial(cliente):
    d = cliente.get(URL).get_json()
    assert d["usa_sere"] is True and d["sere_configurado"] is False and d["configurada"] is False


def test_por_padrao_usa_as_credenciais_do_sere(cliente, tmp_path):
    _salvar_sere(tmp_path)
    d = cliente.get(URL).get_json()
    assert d["usa_sere"] is True and d["configurada"] is True
    from src.comum import credenciais
    assert credenciais.LOGIN_RCO == "12345678900" and credenciais.SENHA_RCO == "senha-sere"


def test_salva_credenciais_proprias_e_aplica(cliente, tmp_path):
    _salvar_sere(tmp_path)
    r = cliente.post(URL, json={"login": "rco.user", "senha": "s3 nh#a"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["usa_sere"] is False and d["configurada"] is True and d["login"] == "rco.user" and "senha" not in d
    g = dotenv_values(tmp_path / ".env")
    assert g["RCO_LOGIN"] == "rco.user" and g["RCO_SENHA"] == "s3 nh#a"
    assert g["SERE_LOGIN"] == "12345678900"          # SERE intocado
    from src.comum import credenciais
    assert credenciais.LOGIN_RCO == "rco.user" and credenciais.SENHA_RCO == "s3 nh#a"
    assert credenciais.LOGIN == "12345678900"


def test_voltar_a_usar_as_do_sere(cliente, tmp_path):
    _salvar_sere(tmp_path)
    cliente.post(URL, json={"login": "rco.user", "senha": "x1"})
    r = cliente.post(URL, json={"mesmas_do_sere": True})
    assert r.status_code == 200 and r.get_json()["usa_sere"] is True
    g = dotenv_values(tmp_path / ".env")
    assert g["RCO_LOGIN"] == "" and g["RCO_SENHA"] == ""
    from src.comum import credenciais
    assert credenciais.LOGIN_RCO == "12345678900" and credenciais.SENHA_RCO == "senha-sere"


def test_mesmas_do_sere_avisa_se_sere_nao_configurado(cliente):
    d = cliente.post(URL, json={"mesmas_do_sere": True}).get_json()
    assert "SERE ainda não estão salvas" in d["mensagem"]


def test_get_nao_vaza_a_senha(cliente):
    cliente.post(URL, json={"login": "u", "senha": "segredo-rco"})
    d = cliente.get(URL).get_json()
    assert d["senha_salva"] is True and "segredo-rco" not in str(d)


def test_trocar_so_login_ou_so_senha(cliente, tmp_path):
    cliente.post(URL, json={"login": "a", "senha": "p1"})
    assert cliente.post(URL, json={"login": "b", "senha": ""}).status_code == 200
    g = dotenv_values(tmp_path / ".env")
    assert g["RCO_LOGIN"] == "b" and g["RCO_SENHA"] == "p1"
    assert cliente.post(URL, json={"login": "", "senha": "p2"}).status_code == 200
    g = dotenv_values(tmp_path / ".env")
    assert g["RCO_LOGIN"] == "b" and g["RCO_SENHA"] == "p2"


def test_aceita_nomes_do_script_original(cliente, monkeypatch):
    monkeypatch.setenv("RCDIG_LOGIN", "orig")
    monkeypatch.setenv("RCDIG_SENHA", "origpw")
    import src.comum.credenciais as cred
    importlib.reload(cred)
    assert cred.LOGIN_RCO == "orig" and cred.SENHA_RCO == "origpw"


@pytest.mark.parametrize("corpo", [
    {},
    {"login": "", "senha": "x"},
    {"login": "u", "senha": ""},
])
def test_entradas_invalidas(cliente, tmp_path, corpo):
    assert cliente.post(URL, json=corpo).status_code == 400
    assert not (tmp_path / ".env").exists()


def test_sem_proprias_nao_da_para_so_trocar_a_senha(cliente, tmp_path):
    """Usando o SERE, mandar só senha não vale: falta o login próprio."""
    _salvar_sere(tmp_path)
    assert cliente.post(URL, json={"login": "", "senha": "x"}).status_code == 400


def test_tela_tem_o_formulario():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert "/configuracoes/rco" in js and "cfg-rco-mesmas" in js

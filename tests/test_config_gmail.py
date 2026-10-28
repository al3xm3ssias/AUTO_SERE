"""Configurações → salvar e-mail e senha de app do Gmail (EMAIL_REMETENTE / EMAIL_SENHA_APP)."""
import importlib
import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import paths  # noqa: E402
from src.web.app import create_app  # noqa: E402

URL = "/web/api/configuracoes/gmail"
EMAIL = "escola@gmail.com"


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path)
    monkeypatch.setenv("EMAIL_REMETENTE", "")
    monkeypatch.setenv("EMAIL_SENHA_APP", "")
    import src.comum.credenciais as cred
    importlib.reload(cred)
    yield create_app().test_client()
    for f in tmp_path.glob(".env"):
        f.unlink()
    os.environ.pop("EMAIL_REMETENTE", None)
    os.environ.pop("EMAIL_SENHA_APP", None)
    importlib.reload(cred)


def test_estado_inicial(cliente):
    assert cliente.get(URL).get_json() == {"email": "", "senha_salva": False, "configurada": False}


def test_salva_remove_espacos_e_aplica(cliente, tmp_path):
    r = cliente.post(URL, json={"email": EMAIL, "senha": "btxq abcd efgh ijkl"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["configurada"] is True and d["email"] == EMAIL and "senha" not in d
    gravado = dotenv_values(tmp_path / ".env")
    assert gravado["EMAIL_REMETENTE"] == EMAIL
    assert gravado["EMAIL_SENHA_APP"] == "btxqabcdefghijkl"
    from src.comum import credenciais
    assert credenciais.EMAIL_SENHA_APP == "btxqabcdefghijkl"
    assert credenciais.EMAIL_REMETENTE == EMAIL


def test_aceita_espaco_nao_separavel_ao_colar(cliente, tmp_path):
    r = cliente.post(URL, json={"email": EMAIL, "senha": "btxq\u00a0abcd\u00a0efgh\u00a0ijkl"})
    assert r.status_code == 200
    assert dotenv_values(tmp_path / ".env")["EMAIL_SENHA_APP"] == "btxqabcdefghijkl"


def test_get_nao_vaza_senha(cliente):
    cliente.post(URL, json={"email": EMAIL, "senha": "btxq abcd efgh ijkl"})
    d = cliente.get(URL).get_json()
    assert d["senha_salva"] is True and "btxq" not in str(d)


def test_trocar_so_a_senha_ou_so_o_email(cliente, tmp_path):
    cliente.post(URL, json={"email": EMAIL, "senha": "btxq abcd efgh ijkl"})
    assert cliente.post(URL, json={"email": "", "senha": "zzzz yyyy xxxx wwww"}).status_code == 200
    g = dotenv_values(tmp_path / ".env")
    assert g["EMAIL_REMETENTE"] == EMAIL and g["EMAIL_SENHA_APP"] == "zzzzyyyyxxxxwwww"
    assert cliente.post(URL, json={"email": "outro@gmail.com", "senha": ""}).status_code == 200
    g = dotenv_values(tmp_path / ".env")
    assert g["EMAIL_REMETENTE"] == "outro@gmail.com" and g["EMAIL_SENHA_APP"] == "zzzzyyyyxxxxwwww"


def test_preserva_outras_linhas(cliente, tmp_path):
    (tmp_path / ".env").write_text("SERE_LOGIN='cpf1'\n", encoding="utf-8")
    cliente.post(URL, json={"email": EMAIL, "senha": "btxq abcd efgh ijkl"})
    assert dotenv_values(tmp_path / ".env")["SERE_LOGIN"] == "cpf1"


@pytest.mark.parametrize("corpo", [
    {},
    {"email": "", "senha": "btxq abcd efgh ijkl"},          # sem e-mail salvo antes
    {"email": "sem-arroba", "senha": "btxq abcd efgh ijkl"},
    {"email": "email@exemplo.com", "senha": "btxq abcd efgh ijkl"},
    {"email": EMAIL, "senha": ""},                          # sem senha salva antes
    {"email": EMAIL, "senha": "btxq abcd efgh"},            # curta
    {"email": EMAIL, "senha": "btxq abcd efgh ijkl mnop"},  # longa
    {"email": EMAIL, "senha": "minhaSenha123456!"},         # senha normal, não de app
])
def test_entradas_invalidas(cliente, tmp_path, corpo):
    assert cliente.post(URL, json=corpo).status_code == 400
    assert not (tmp_path / ".env").exists()


def test_tela_tem_o_formulario():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert "/configuracoes/gmail" in js and "cfg-gmail-senha" in js

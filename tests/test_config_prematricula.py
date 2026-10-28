"""Configurações → salvar login e senha da pré-matrícula (PREMATRICULA_LOGIN / PREMATRICULA_SENHA)."""
import importlib
import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import paths  # noqa: E402
from src.web.app import create_app  # noqa: E402

URL = "/web/api/configuracoes/prematricula"


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path)
    # Registra o estado original das variáveis para o monkeypatch desfazer no fim.
    monkeypatch.setenv("PREMATRICULA_LOGIN", "")
    monkeypatch.setenv("PREMATRICULA_SENHA", "")
    import src.comum.credenciais as cred
    importlib.reload(cred)
    yield create_app().test_client()
    # Limpa o que o teste gravou e devolve o módulo de credenciais ao normal.
    for f in tmp_path.glob(".env"):
        f.unlink()
    os.environ.pop("PREMATRICULA_LOGIN", None)
    os.environ.pop("PREMATRICULA_SENHA", None)
    importlib.reload(cred)


def test_estado_inicial_nao_configurado(cliente):
    d = cliente.get(URL).get_json()
    assert d == {"login": "", "senha_salva": False, "configurada": False}


def test_salva_no_env_e_aplica_em_runtime(cliente, tmp_path):
    r = cliente.post(URL, json={"login": "12345", "senha": "s3 nh#a'x"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok" and d["configurada"] is True and d["login"] == "12345"
    assert "senha" not in d   # a senha nunca volta na resposta

    gravado = dotenv_values(tmp_path / ".env")
    assert gravado["PREMATRICULA_LOGIN"] == "12345"
    assert gravado["PREMATRICULA_SENHA"] == "s3 nh#a'x"   # caracteres especiais preservados

    from src.comum import credenciais
    assert credenciais.MATRICULA_PREMATRICULA == "12345"
    assert credenciais.SENHA_PREMATRICULA == "s3 nh#a'x"


def test_get_nao_vaza_a_senha(cliente):
    cliente.post(URL, json={"login": "12345", "senha": "segredo-xyz"})
    d = cliente.get(URL).get_json()
    assert d["senha_salva"] is True and d["login"] == "12345"
    assert "segredo-xyz" not in str(d)


def test_trocar_so_o_login_mantem_a_senha(cliente, tmp_path):
    cliente.post(URL, json={"login": "111", "senha": "senha-antiga"})
    r = cliente.post(URL, json={"login": "222", "senha": ""})
    assert r.status_code == 200
    gravado = dotenv_values(tmp_path / ".env")
    assert gravado["PREMATRICULA_LOGIN"] == "222"
    assert gravado["PREMATRICULA_SENHA"] == "senha-antiga"


def test_preserva_outras_linhas_do_env(cliente, tmp_path):
    (tmp_path / ".env").write_text("SERE_LOGIN='cpf1'\nSERE_SENHA='abc'\n", encoding="utf-8")
    cliente.post(URL, json={"login": "999", "senha": "pp"})
    gravado = dotenv_values(tmp_path / ".env")
    assert gravado["SERE_LOGIN"] == "cpf1" and gravado["SERE_SENHA"] == "abc"
    assert gravado["PREMATRICULA_LOGIN"] == "999"


@pytest.mark.parametrize("corpo", [
    {"login": "", "senha": "x"},
    {"login": "   ", "senha": "x"},
    {"login": "123", "senha": ""},          # sem senha salva antes
    {"login": "matricula", "senha": "x"},   # placeholder
    {"login": "123", "senha": "senha_prematricula"},
    {},
])
def test_entradas_invalidas_dao_400_e_nao_gravam(cliente, tmp_path, corpo):
    assert cliente.post(URL, json=corpo).status_code == 400
    assert not (tmp_path / ".env").exists()


def test_tela_de_configuracoes_tem_o_item():
    html = (Path(__file__).resolve().parent.parent / "src/web/templates/configuracoes.html").read_text(encoding="utf-8")
    js = (Path(__file__).resolve().parent.parent / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'data-config="senha_prematricula"' in html
    assert "senha_prematricula:" in js and "/configuracoes/prematricula" in js

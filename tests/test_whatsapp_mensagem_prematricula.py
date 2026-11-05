"""Botão "Mandar mensagem" da fila da pré-matrícula: o texto sugerido é o Comunicado de Matrícula (o do modelo HTML)."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.comum import configuracao, escola, paths  # noqa: E402
from src.web.api import rotas, whatsapp  # noqa: E402
from src.web.app import create_app  # noqa: E402

ITEM = {"id": "111", "nome": "ISAAC DAVID ORTEGA", "turma": "Infantil V", "telefone_responsavel": "(41) 99733-9856"}


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "carregar_configuracao", lambda: {})
    monkeypatch.setattr(escola, "carregar", lambda: {"nome": "ESCOLA JUDITH MACEDO SILVEIRA", "nome_abreviado": "JUDITH"})
    monkeypatch.setattr(rotas, "_fila_prematricula", lambda: [dict(ITEM)])
    return create_app().test_client()


def _texto(cliente):
    r = cliente.get("/web/api/whatsapp/modelo-prematricula?id=111")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_texto_sugerido_e_o_comunicado_de_matricula(cliente):
    corpo = _texto(cliente)
    t = corpo["texto"]
    assert corpo["telefone"] == "(41) 99733-9856"
    assert "surgiu uma vaga" not in t
    assert t.startswith("🌟 Olá, tudo bem?\nMe chamo Claudio, sou escriturário da Escola Judith.")
    assert "a matrícula de Isaac David Ortega para o ano letivo de 2026 foi aprovada" in t
    assert "📄 Documentos necessários" in t and "https://chat.whatsapp.com/" in t
    assert "$" not in t                                           # nenhum marcador sobrou


def test_prazo_e_hoje_mais_oito_dias(cliente):
    from datetime import timedelta
    fim = date.today() + timedelta(days=8)
    assert f"Prazo final: {fim.strftime('%d/%m/%Y')}" in _texto(cliente)["texto"]


def test_cabe_no_limite_de_envio(cliente):
    assert len(_texto(cliente)["texto"]) <= whatsapp.LIMITE_TEXTO_MENSAGEM


def test_config_errada_vira_mensagem_na_tela(cliente, monkeypatch):
    monkeypatch.setattr(configuracao, "carregar_configuracao",
                        lambda: {"comunicado_matricula": {"escriturario": " "}})
    r = cliente.get("/web/api/whatsapp/modelo-prematricula?id=111")
    assert r.status_code == 400 and "escriturario" in r.get_json()["erro"]

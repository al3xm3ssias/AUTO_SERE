"""Executar a pré-matrícula pela API (o plano certo, sem abrir navegador de verdade)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402

CHAVE = "prematricula_completa"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    return create_app().test_client()


@pytest.fixture()
def planos(monkeypatch):
    """Captura o plano em vez de executá-lo (executar de verdade abriria o navegador e o site)."""
    capturados = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: capturados.append((chave, plano)))
    return capturados


def test_componentes_expoem_modo_analise_e_pular_pendentes(c):
    r = c.get(f"/web/api/automacoes/{CHAVE}/componentes").get_json()
    assert r["registrado"] and r["recursos"] == ["debug"] and not r["confirmar"]
    assert [e["nome"] for e in r["extras"]] == ["pular_pendentes", "enviar_google_contatos", "simular_google_contatos"]
    assert r["ajuda_debug"]


def test_executar_sem_opcoes_roda_o_processo_completo(c, planos):
    resp = c.post(f"/web/api/automacoes/{CHAVE}/executar", json={})
    assert resp.status_code == 200 and resp.get_json()["status"] == "executando"
    chave, plano = planos[0]
    assert chave == CHAVE and plano.tipo == "coroutine" and plano.funcao.__name__ == "processo_completo_via_login"
    assert plano.kwargs == {"analise": False, "pular_pendentes": False}


def test_executar_repassa_modo_analise_e_pular_pendentes(c, planos):
    c.post(f"/web/api/automacoes/{CHAVE}/executar", json={"debug": True, "pular_pendentes": True})
    assert planos[0][1].kwargs == {"analise": True, "pular_pendentes": True}


def test_nao_inicia_duas_vezes_ao_mesmo_tempo(c, planos, monkeypatch):
    monkeypatch.setitem(rotas._EXECUCOES, CHAVE, {"status": "executando", "logs": [], "erro": None,
                                                 "iniciado_em": "x", "resultado": None, "execucao": None})
    resp = c.post(f"/web/api/automacoes/{CHAVE}/executar", json={})
    assert resp.status_code == 409 and "já está em execução" in resp.get_json()["mensagem"] and planos == []

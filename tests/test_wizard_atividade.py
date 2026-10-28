"""Painel 'Registro de atividades' do wizard (backend e interface)."""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import configuracao  # noqa: E402
from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def estado_limpo(tmp_path, monkeypatch):
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
        rotas._EVENTOS_WIZARD.clear()
    monkeypatch.setattr(rotas, "_WIZARD_LIMPO_T", 0.0)
    yield


@pytest.fixture()
def cliente():
    return create_app().test_client()


def _esperar(cliente, passo, ate="concluido", limite=10):
    fim = time.time() + limite
    while time.time() < fim:
        d = cliente.get("/web/api/wizard/atividade").get_json()
        if d["passos"].get(passo, {}).get("status") == ate:
            return d
        time.sleep(0.05)
    pytest.fail(f"passo {passo} não chegou a {ate}")


def test_feed_vazio(cliente):
    d = cliente.get("/web/api/wizard/atividade").get_json()
    assert d == {"entradas": [], "passos": {}, "executando": []}


def test_passo_em_segundo_plano_aparece_em_ordem(cliente):
    def trabalho():
        print("Coletando turmas...")
        print("[INFO] 5 turmas encontradas")

    rotas._rodar_funcao_sincrona_em_thread("wizard_turmas", trabalho)
    d = _esperar(cliente, "turmas")
    textos = [e["texto"] for e in d["entradas"]]
    assert textos[0] == "▶ Iniciando: Turmas"
    assert "Coletando turmas..." in textos
    assert "5 turmas encontradas" in textos              # prefixo [INFO] removido
    assert textos[-1] == "✓ Concluído: Turmas"
    assert d["entradas"][-1]["nivel"] == "ok" and d["executando"] == []
    assert all(len(e["hora"]) == 8 for e in d["entradas"])   # HH:MM:SS


def test_passo_em_execucao_e_listado(cliente):
    liberar = threading.Event()
    rotas._rodar_funcao_sincrona_em_thread("wizard_alunos", liberar.wait)
    try:
        d = cliente.get("/web/api/wizard/atividade").get_json()
        assert d["executando"] == ["alunos"]
    finally:
        liberar.set()
    _esperar(cliente, "alunos")


def test_erro_do_passo_vira_linha_de_erro(cliente):
    def quebra():
        raise RuntimeError("login recusado")

    rotas._rodar_funcao_sincrona_em_thread("wizard_funcionarios", quebra)
    d = _esperar(cliente, "funcionarios", ate="erro")
    ultima = d["entradas"][-1]
    assert ultima["nivel"] == "erro" and "login recusado" in ultima["texto"]


def test_eventos_dos_passos_rapidos_sem_dados_sensiveis(cliente, monkeypatch):
    monkeypatch.setattr(rotas, "_persistir_env", lambda d: None)
    monkeypatch.setattr(rotas, "_recarregar_credenciais_em_runtime", lambda: True)

    cliente.post("/web/api/wizard/escola/executar", json={"nome": "Escola Y", "cep": "84016630", "logradouro": "Rua A"})
    cliente.post("/web/api/wizard/escola/executar", json={"nome": "X", "cep": "1"})
    cliente.post("/web/api/wizard/credenciais_sere/executar", json={"login": "12345678900", "senha": "segredo-123"})

    d = cliente.get("/web/api/wizard/atividade").get_json()
    por_nivel = {(e["passo"], e["nivel"]): e["texto"] for e in d["entradas"]}
    assert "Escola Y" in por_nivel[("escola", "ok")] and "84016-630" in por_nivel[("escola", "ok")]
    assert ("escola", "aviso") in por_nivel
    assert ("credenciais_sere", "ok") in por_nivel
    bruto = str(d)
    assert "segredo-123" not in bruto and "12345678900" not in bruto


def test_limpar_esconde_o_passado_mas_nao_o_novo(cliente):
    cliente.post("/web/api/wizard/escola/executar", json={"nome": "X", "cep": "1"})
    assert cliente.get("/web/api/wizard/atividade").get_json()["entradas"]
    assert cliente.post("/web/api/wizard/atividade/limpar").status_code == 200
    assert cliente.get("/web/api/wizard/atividade").get_json()["entradas"] == []
    time.sleep(0.01)
    cliente.post("/web/api/wizard/escola/executar", json={"nome": "X", "cep": "1"})
    assert len(cliente.get("/web/api/wizard/atividade").get_json()["entradas"]) == 1


@pytest.mark.parametrize("linha,nivel", [
    ("[ERROR] falhou", "erro"), ("[ERRO] boom", "erro"), ("[CANCELANDO] Pedido", "aviso"), ("Traceback (most recent call last):", "erro"), ("Erro ao salvar", "erro"),
    ("Erros encontrados: 0", "info"), ("[WARNING] lento", "aviso"), ("Concluído com sucesso", "ok"),
    ("Processando aluno 3", "info"),
])
def test_nivel_da_linha(linha, nivel):
    assert rotas._nivel_da_linha(linha) == nivel


def test_nao_altera_o_status_das_automacoes_existentes(cliente):
    rotas._rodar_funcao_sincrona_em_thread("wizard_turmas", lambda: print("oi"))
    _esperar(cliente, "turmas")
    r = cliente.get("/web/api/automacoes/wizard_turmas/status").get_json()
    assert r["logs"] == ["oi", "[CONCLUÍDO]"] and r["status"] == "concluido"   # contrato antigo intacto
    textos = [e["texto"] for e in cliente.get("/web/api/wizard/atividade").get_json()["entradas"]]
    assert textos.count("✓ Concluído: Turmas") == 1 and "[CONCLUÍDO]" not in textos   # sem duplicar

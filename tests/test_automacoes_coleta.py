"""Automações Turmas e Alunos (modo básico → alunos.py, modo completo → alunos_completo.py)."""
import threading
import time

import pytest

from src.web.api import rotas
from src.web.app import create_app


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    """Cliente + fakes das três coletas (sem SERE, sem navegador). `chamadas` registra o que foi executado."""
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
        rotas._EVENTOS_WIZARD.clear()
    chamadas = []

    import src.automacao.alunos as alunos_mod
    import src.automacao.alunos_completo as completo_mod
    import src.automacao.turmas as turmas_mod

    async def fake_turmas():
        print("turmas: coletando")
        chamadas.append(("turmas",))

    async def fake_alunos():
        print("alunos básico: coletando")
        chamadas.append(("alunos_basico",))

    async def fake_completo(modo_rapido=False):
        print(f"alunos completo: coletando (rápido={modo_rapido})")
        chamadas.append(("alunos_completo", modo_rapido))

    monkeypatch.setattr(turmas_mod, "coletar_turmas_e_alunos_via_login", fake_turmas)
    monkeypatch.setattr(alunos_mod, "coletar_alunos_via_login", fake_alunos)
    monkeypatch.setattr(completo_mod, "coletar_cadastro_completo_via_login", fake_completo)
    return create_app().test_client(), chamadas, tmp_path


def _esperar(c, chave, ate=("concluido", "erro", "cancelado"), limite=10):
    fim = time.time() + limite
    while time.time() < fim:
        s = c.get(f"/web/api/automacoes/{chave}/status").get_json()
        if s["status"] in ate:
            return s
        time.sleep(0.03)
    pytest.fail(f"{chave} não terminou")


def _executar(c, chave, **payload):
    return c.post(f"/web/api/automacoes/{chave}/executar", json=payload)


def test_lista_tem_turmas_e_alunos_no_topo(ctx):
    c, _, _ = ctx
    itens = c.get("/web/api/automacoes/lista").get_json()["itens"]
    assert [i["chave"] for i in itens[:2]] == ["turmas", "alunos"]
    assert "alunos.py" in itens[1]["descricao"] and "alunos_completo.py" in itens[1]["descricao"]
    assert len({i["chave"] for i in itens}) == len(itens)           # sem chaves repetidas


def test_turmas_executa_turmas_py(ctx):
    c, chamadas, _ = ctx
    r = _executar(c, "turmas")
    assert r.status_code == 200 and r.get_json()["status"] == "executando"
    s = _esperar(c, "turmas")
    assert s["status"] == "concluido" and chamadas == [("turmas",)]
    assert "turmas: coletando" in "\n".join(s["logs"])


def test_alunos_sem_modo_e_basico(ctx):
    c, chamadas, _ = ctx
    assert _executar(c, "alunos").status_code == 200
    _esperar(c, "alunos")
    assert chamadas == [("alunos_basico",)]


def test_alunos_modo_basico_explicito_ignora_rapido(ctx):
    c, chamadas, _ = ctx
    assert _executar(c, "alunos", modo="basico", rapido=True).status_code == 200
    _esperar(c, "alunos")
    assert chamadas == [("alunos_basico",)]                          # "rápido" só existe no completo


@pytest.mark.parametrize("rapido", [False, True])
def test_alunos_modo_completo_chama_alunos_completo(ctx, rapido):
    c, chamadas, tmp = ctx
    (tmp / "turmas.json").write_text('{"5A": []}', encoding="utf-8")
    assert _executar(c, "alunos", modo="completo", rapido=rapido).status_code == 200
    s = _esperar(c, "alunos")
    assert s["status"] == "concluido" and chamadas == [("alunos_completo", rapido)]


def test_modo_completo_sem_turmas_json_explica_o_que_fazer(ctx):
    c, chamadas, _ = ctx
    r = _executar(c, "alunos", modo="completo")
    assert r.status_code == 400 and "Turmas" in r.get_json()["mensagem"]
    assert chamadas == []


def test_modo_desconhecido_e_recusado(ctx):
    c, chamadas, _ = ctx
    r = _executar(c, "alunos", modo="turbo")
    assert r.status_code == 400 and "basico" in r.get_json()["mensagem"]
    assert chamadas == []


def test_mesma_automacao_duas_vezes_continua_dando_409(ctx):
    c, _, _ = ctx
    liberar = threading.Event()
    rotas._rodar_funcao_sincrona_em_thread("alunos", liberar.wait)
    try:
        assert _executar(c, "alunos").status_code == 409
    finally:
        liberar.set()
    _esperar(c, "alunos")


def test_coleta_do_wizard_em_andamento_bloqueia_a_equivalente(ctx):
    c, chamadas, _ = ctx
    liberar = threading.Event()
    rotas._rodar_funcao_sincrona_em_thread("wizard_turmas", liberar.wait)
    try:
        r = _executar(c, "turmas")
        assert r.status_code == 409 and "wizard_turmas" in r.get_json()["mensagem"]
    finally:
        liberar.set()
    _esperar(c, "wizard_turmas")
    assert _executar(c, "turmas").status_code == 200                  # liberou → roda
    _esperar(c, "turmas")
    assert chamadas == [("turmas",)]


def test_automacao_em_andamento_bloqueia_o_passo_equivalente_do_wizard(ctx):
    c, chamadas, _ = ctx
    liberar = threading.Event()
    rotas._rodar_funcao_sincrona_em_thread("alunos", liberar.wait)
    try:
        r = c.post("/web/api/wizard/alunos/executar", json={})
        assert r.status_code == 409
        feed = c.get("/web/api/wizard/atividade").get_json()["entradas"]
        assert any(e["nivel"] == "aviso" and "Não iniciado" in e["texto"] for e in feed)   # aparece no painel
    finally:
        liberar.set()
    _esperar(c, "alunos")
    assert chamadas == []


def test_completo_espera_a_coleta_de_turmas_terminar_mas_basico_nao(ctx):
    c, chamadas, tmp = ctx
    (tmp / "turmas.json").write_text('{"5A": []}', encoding="utf-8")
    liberar = threading.Event()
    rotas._rodar_funcao_sincrona_em_thread("turmas", liberar.wait)
    try:
        r = _executar(c, "alunos", modo="completo")
        assert r.status_code == 409 and "Turmas" in r.get_json()["mensagem"]
        assert _executar(c, "alunos", modo="basico").status_code == 200       # básico não lê turmas.json
        _esperar(c, "alunos")
    finally:
        liberar.set()
    _esperar(c, "turmas")
    assert chamadas == [("alunos_basico",)]


def test_wizard_continua_iniciando_turmas_e_alunos(ctx):
    c, chamadas, _ = ctx
    assert c.post("/web/api/wizard/turmas/executar", json={}).status_code == 200
    _esperar(c, "wizard_turmas")
    assert c.post("/web/api/wizard/alunos/executar", json={}).status_code == 200
    _esperar(c, "wizard_alunos")
    assert chamadas == [("turmas",), ("alunos_basico",)]

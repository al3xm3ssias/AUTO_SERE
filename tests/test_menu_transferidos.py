"""Menu lateral dos transferidos: registro, formulários, simulação e DATA_CORTE vindos da interface."""
import json
import re
from pathlib import Path

import pytest

from src.comum import configuracao, paths
from src.comum import registro_scripts as reg
from src.web.api import rotas
from src.web.app import create_app

NOVAS = ("transferidos_fila", "transferidos_gerar", "transferidos", "pareceres_transferidos")
RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps({"A": [{"CGM": "1", "Nome": "X", "Situação": "Matriculado"}]}), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    planos = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: planos.append((chave, plano)))
    return create_app().test_client(), planos


def _post(c, chave, **payload):
    return c.post(f"/web/api/automacoes/{chave}/executar", json=payload)


def _kwargs(planos):
    assert len(planos) == 1
    return planos[0][1].kwargs


# ── consistência: registro, catálogo, menu lateral ──────────────────────

def test_as_quatro_automacoes_estao_no_registro_no_catalogo_e_no_menu():
    catalogo = {i["chave"]: i for i in rotas.AUTOMACOES_DISPONIVEIS}
    menu = set(re.findall(r'data-auto="([a-z_]+)"', (RAIZ / "src/web/templates/base.html").read_text(encoding="utf-8")))
    for chave in NOVAS:
        assert chave in reg.REGISTRO and chave in catalogo and chave in menu, chave


def test_icones_das_automacoes_novas_no_js():
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    for chave in ("transferidos_fila", "transferidos_gerar", "pareceres_transferidos"):
        assert re.search(rf"^\s*{chave}:\s*\"", js, re.M), chave


def test_campo_de_texto_aceita_valor_padrao_no_js():
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    trecho = js[js.index('<input type="text" id="${campo.id}"'):][:300]
    assert "campo.padrao" in trecho


# ── formulários ──────────────────────────────────────────────────────────

def _extras(c, chave):
    r = c.get(f"/web/api/automacoes/{chave}/componentes").get_json()
    return {e["nome"]: e for e in r["extras"]}


def test_formularios_trazem_data_de_corte_ja_preenchida(ctx):
    c, _ = ctx
    for chave in NOVAS:
        assert _extras(c, chave)["data_corte"]["padrao"] == "22/06/2026", chave


def test_a_data_de_corte_do_formulario_reflete_a_configuracao(ctx):
    c, _ = ctx
    configuracao.definir_data_corte_transferidos("01/09/2026")
    assert _extras(c, "transferidos_gerar")["data_corte"]["padrao"] == "01/09/2026"


def test_simulacao_ja_vem_marcada_nas_telas_que_mexem_no_sere(ctx):
    c, _ = ctx
    assert _extras(c, "transferidos_fila")["simulacao"]["padrao"] is False        # só gera um JSON local
    for chave in ("transferidos_gerar", "transferidos", "pareceres_transferidos"):
        assert _extras(c, chave)["simulacao"]["padrao"] is True, chave


def test_telas_que_podem_agir_pedem_confirmacao(ctx):
    c, _ = ctx
    for chave in ("transferidos_gerar", "transferidos", "pareceres_transferidos"):
        r = c.get(f"/web/api/automacoes/{chave}/componentes").get_json()
        assert r["confirmar"] is True and "Simulação" in r["aviso_confirmacao"], chave
    assert c.get("/web/api/automacoes/transferidos_fila/componentes").get_json()["confirmar"] is False


# ── fila ─────────────────────────────────────────────────────────────────

def test_fila_executa_com_e_sem_simulacao(ctx):
    c, planos = ctx
    assert _post(c, "transferidos_fila", simulacao=True).status_code == 200
    assert _kwargs(planos) == {"simulacao": True}
    planos.clear()
    _post(c, "transferidos_fila")
    assert _kwargs(planos) == {"simulacao": False}
    assert planos[0][1].tipo == "sync"


# ── gerar guia e histórico ───────────────────────────────────────────────

def test_gerar_usa_as_8_etapas_por_padrao(ctx):
    from src.automacao import processo_transferidos as pr
    c, planos = ctx
    _post(c, "transferidos_gerar")
    kw = _kwargs(planos)
    assert kw == {"etapas": pr.GRUPOS_ETAPAS["todas"], "simulacao": False, "pular_retornados": False, "modo_teste": False}
    assert planos[0][1].tipo == "coroutine" and planos[0][1].funcao is pr.processar_transferencias


@pytest.mark.parametrize("grupo", ["historico", "guia"])
def test_gerar_so_historico_ou_so_guia(ctx, grupo):
    from src.automacao import processo_transferidos as pr
    c, planos = ctx
    _post(c, "transferidos_gerar", o_que_gerar=grupo, simulacao=True, pular_retornados=True, modo_teste=True)
    assert _kwargs(planos) == {"etapas": pr.GRUPOS_ETAPAS[grupo], "simulacao": True, "pular_retornados": True, "modo_teste": True}


def test_gerar_rejeita_opcao_invalida(ctx):
    c, planos = ctx
    r = _post(c, "transferidos_gerar", o_que_gerar="tudo-errado")
    assert r.status_code == 400 and "Escolha o que gerar" in r.get_json()["mensagem"] and planos == []


# ── envio ao SERE ────────────────────────────────────────────────────────

def test_envio_mantem_o_contrato_antigo_e_acrescenta_a_simulacao(ctx):
    c, planos = ctx
    _post(c, "transferidos", modo_teste=True)
    assert _kwargs(planos) == {"modo_teste": True}                               # contrato antigo intacto
    planos.clear()
    _post(c, "transferidos", simulacao=True)
    assert _kwargs(planos) == {"modo_teste": False, "simulacao": True}


# ── pareceres ────────────────────────────────────────────────────────────

def test_pareceres_plano_padrao_e_simulado(ctx):
    from src.automacao import pareceres_transferidos as pp
    from src.comum.compressao import LIMITE_SERE_MB
    c, planos = ctx
    _post(c, "pareceres_transferidos")
    assert _kwargs(planos) == {"simulacao": False, "enviar": True, "limite_mb": LIMITE_SERE_MB, "modo_teste": False}
    assert planos[0][1].funcao is pp.executar_pareceres_transferidos
    planos.clear()
    _post(c, "pareceres_transferidos", simulacao=True, enviar=False, limite_mb="0,8", modo_teste=True)
    assert _kwargs(planos) == {"simulacao": True, "enviar": False, "limite_mb": 0.8, "modo_teste": True}


def test_pareceres_rejeita_limite_invalido(ctx):
    c, planos = ctx
    r = _post(c, "pareceres_transferidos", limite_mb="muito")
    assert r.status_code == 400 and "Tamanho inválido" in r.get_json()["mensagem"] and planos == []


# ── DATA_CORTE digitada na tela ──────────────────────────────────────────

@pytest.mark.parametrize("chave", NOVAS)
def test_data_de_corte_digitada_fica_gravada(ctx, chave):
    c, _ = ctx
    assert _post(c, chave, data_corte="01/09/2026").status_code == 200
    assert configuracao.data_corte_transferidos().strftime("%d/%m/%Y") == "01/09/2026"


def test_data_de_corte_em_branco_nao_muda_nada(ctx):
    c, _ = ctx
    configuracao.definir_data_corte_transferidos("01/09/2026")
    _post(c, "transferidos_gerar", data_corte="")
    assert configuracao.data_corte_transferidos().strftime("%d/%m/%Y") == "01/09/2026"


@pytest.mark.parametrize("chave", NOVAS)
def test_data_de_corte_invalida_e_recusada_sem_gravar(ctx, chave):
    c, planos = ctx
    r = _post(c, chave, data_corte="31/02/2026")
    assert r.status_code == 400 and "dd/mm/aaaa" in r.get_json()["mensagem"]
    assert planos == [] and not configuracao.data_corte_transferidos_configurada()


def test_turmas_py_registra_a_fila_depois_de_gravar_o_turmas_json():
    """O gancho está no lugar certo: depois de gravar o turmas.json e antes de encerrar a coleta."""
    fonte = (RAIZ / "src/automacao/turmas.py").read_text(encoding="utf-8")
    gravar = fonte.index("Salvando JSON em")
    gancho = fonte.index("registrar_fila_sem_falhar(resultado")
    fim = fonte.index("Coleta geral finalizada")
    assert gravar < gancho < fim

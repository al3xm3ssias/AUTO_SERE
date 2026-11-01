"""Tela "Gerar guia e histórico" no Chromium: as 5 ações, a caixa de texto do Alterar e o que é enviado."""
import json
import threading

import pytest
from werkzeug.serving import make_server

from src.comum import configuracao, paths
from src.web.api import rotas
from src.web.app import create_app

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def pagina(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps({"A": []}), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    executados = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: executados.append(plano.kwargs))

    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page()
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        pg.executados = executados
        yield pg
        nav.close()
    srv.shutdown()


def _abrir_gerar(pg):
    pg.click("#toggle-automacoes")
    pg.click('#sub-automacoes .nav-subitem[data-auto="transferidos_gerar"]')
    pg.wait_for_selector("#automacoes-execucao", state="visible")
    pg.wait_for_selector("#campo-acao-alterar")


def _executar(pg):
    with pg.expect_response("**/automacoes/transferidos_gerar/executar") as resp:   # espera o servidor processar
        pg.click("#btn-executar-tarefa")
        pg.click("#conf-sim")                                   # confirmação
    assert resp.value.status == 200
    return resp.value.request.post_data_json


def test_as_cinco_acoes_aparecem_marcadas(pagina):
    _abrir_gerar(pagina)
    for chave in ("gravar", "alterar", "emitir", "assinar", "imprimir"):
        assert pagina.is_checked(f"#campo-acao-{chave}"), chave
    assert pagina.is_checked("#campo-simulacao")                # simulação já marcada


def test_a_caixa_de_texto_aparece_e_some_com_o_alterar(pagina):
    _abrir_gerar(pagina)
    assert pagina.is_visible("#campo-observacao")                # Alterar marcado → mostra a caixa
    pagina.uncheck("#campo-acao-alterar")
    assert not pagina.is_visible("#campo-observacao")
    pagina.check("#campo-acao-alterar")
    assert pagina.is_visible("#campo-observacao")


def test_envia_so_o_que_foi_marcado_e_o_texto(pagina):
    _abrir_gerar(pagina)
    for chave in ("gravar", "emitir", "imprimir"):
        pagina.uncheck(f"#campo-acao-{chave}")                   # fica só Alterar e Assinar
    pagina.fill("#campo-observacao", "Aluno transferido para outra escola.")
    corpo = _executar(pagina)
    assert (corpo["gravar"], corpo["alterar"], corpo["emitir"], corpo["assinar"], corpo["imprimir"]) == \
           (False, True, False, True, False)
    assert corpo["observacao"] == "Aluno transferido para outra escola." and corpo["documentos"] == "ambos"
    assert pagina.executados[-1]["etapas"] == ["Alterar/Excluir (adicionar obs.)", "Assinar Históricos", "Assinar Guias"]


def test_so_assinar_nao_pede_texto(pagina):
    _abrir_gerar(pagina)
    for chave in ("gravar", "alterar", "emitir", "imprimir"):
        pagina.uncheck(f"#campo-acao-{chave}")
    corpo = _executar(pagina)
    assert corpo["assinar"] is True and pagina.executados[-1]["etapas"] == ["Assinar Históricos", "Assinar Guias"]
    assert pagina.executados[-1]["observacao"] is None


def test_alterar_sem_texto_e_recusado_antes_de_confirmar(pagina):
    _abrir_gerar(pagina)                                         # Alterar marcado, caixa vazia
    with pagina.expect_response("**/automacoes/transferidos_gerar/previa") as resp:
        pagina.click("#btn-executar-tarefa")
    assert resp.value.status == 400
    assert "texto da observação" in json.dumps(resp.value.json(), ensure_ascii=False)     # a mensagem (qualquer que seja a chave)
    assert pagina.locator("#conf-sim").count() == 0 and pagina.executados == []     # nem chega a pedir confirmação


def test_o_texto_usado_volta_preenchido(pagina):
    _abrir_gerar(pagina)
    pagina.fill("#campo-observacao", "Texto que deve voltar.")
    _executar(pagina)
    pagina.reload()
    _abrir_gerar(pagina)
    assert pagina.input_value("#campo-observacao") == "Texto que deve voltar."

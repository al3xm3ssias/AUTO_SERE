"""Home no Chromium: o cartão de avisos da rotina diária (só aparece com aviso; passos; marcar como resolvido)."""
import threading

import pytest
from werkzeug.serving import make_server

from src.comum import painel_avisos
from src.web.api import rotas
from src.web.app import create_app

playwright_sync = pytest.importorskip("playwright.sync_api")

EV = {"cgm": "1001", "nome": "Bia Souza", "turma": "5º Ano A", "motivo": "situacao_mudou", "data_transferencia": "10/11/2026"}


@pytest.fixture()
def abrir_home(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")

        def abrir():
            pg = nav.new_page()
            pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
            pg.wait_for_selector("#metrics-principais")
            return pg
        yield abrir, tmp_path
        nav.close()
    srv.shutdown()


def test_sem_aviso_o_cartao_fica_escondido(abrir_home):
    abrir, _ = abrir_home
    pg = abrir()
    pg.wait_for_timeout(500)
    assert not pg.locator("#painel-avisos").is_visible()


def test_aviso_de_transferencia_aparece_com_os_passos_e_resolve(abrir_home):
    abrir, pasta = abrir_home
    painel_avisos.registrar_da_comparacao([EV], pasta)
    pg = abrir()
    pg.wait_for_selector("#painel-avisos", state="visible")
    texto = pg.inner_text("#painel-avisos-lista")
    assert "Aluno transferido: Bia Souza" in texto and "5º Ano A" in texto
    assert "☐ Gerar os documentos do aluno transferido" in texto and "☐ Enviar os documentos à escola de destino" in texto
    pg.click("[data-aviso-resolver]")
    pg.wait_for_selector("#painel-avisos", state="hidden")
    assert painel_avisos.listar_abertos(pasta) == []


def test_nome_com_html_nao_e_interpretado(abrir_home):
    abrir, pasta = abrir_home
    painel_avisos.registrar_da_comparacao([{**EV, "nome": "<img src=x onerror=window.__xss=1>"}], pasta)
    pg = abrir()
    pg.wait_for_selector("#painel-avisos", state="visible")
    assert pg.evaluate("window.__xss") is None
    assert "<img src=x" in pg.inner_text("#painel-avisos-lista")

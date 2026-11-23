"""'Ver quem já recebeu' (Mandar avisos) no Chromium, com registros gerados pelo PRÓPRIO envio real (não escritos à mão)."""
import json
import threading

import pytest
from werkzeug.serving import make_server

from src.comum import paths
from src.web.app import create_app
from tests.test_avisos import amb, chegando, smtp, sem_espera, _simular_e_enviar  # noqa: F401

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def pagina(amb):
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page(viewport={"width": 1400, "height": 1300})
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        yield pg
        nav.close()
    srv.shutdown()


def _abrir_avisos(pg):
    pg.click("#toggle-automacoes")
    pg.locator('#sub-automacoes .nav-subitem[data-auto="avisos"]').dispatch_event("click")
    pg.wait_for_selector("#campo-enviados-ver")


def _arquivo():
    return paths.dados_ano_atual() / "AVISOS" / "enviados.json"


def test_ver_quem_ja_recebeu_com_registros_do_envio_real(pagina, chegando, smtp, sem_espera):
    _simular_e_enviar()                                                   # grava o enviados.json de verdade (2 e-mails)
    dados = json.loads(_arquivo().read_text(encoding="utf-8"))
    dados["envios"]["antigo"] = {"para": "velho@pg.gov.br", "nome": "Escola Antiga", "assunto": "Aviso antigo",     # formato de versões antigas
                                 "enviado_em": "2020-01-01T09:00:00"}
    _arquivo().write_text(json.dumps(dados), encoding="utf-8")

    pg = pagina
    _abrir_avisos(pg)
    assert not pg.is_visible("#campo-enviados-painel")                    # fechado até clicar
    pg.click("#campo-enviados-ver")
    pg.wait_for_selector("#campo-enviados-lista .checklist-item")
    assert pg.inner_text("#campo-enviados-resumo") == "3 de 3 envio(s)." and pg.inner_text("#campo-enviados-ver") == "Esconder"
    itens = pg.locator("#campo-enviados-lista .checklist-item")
    assert itens.count() == 3
    assert "Escola Antiga" in itens.nth(2).inner_text() and " · escola de" not in itens.nth(2).inner_text()        # o mais antigo por último, sem público
    primeiro = itens.nth(0).inner_text()                                  # o envio real grava o público "escolas" (= escola de origem)
    assert "escola de origem" in primeiro and "aluno ANA LIMA" in primeiro and "Transferência de ANA LIMA" in primeiro and "<ana@pg.gov.br>" in primeiro
    pg.screenshot(path="/tmp/avisos_enviados.png")

    pg.fill("#campo-enviados-busca", "sao jose")                          # sem acento e sem caixa
    assert pg.inner_text("#campo-enviados-resumo") == "1 de 3 envio(s) com a busca." and pg.locator("#campo-enviados-lista .checklist-item").count() == 1
    assert "sj@pg.gov.br" in pg.inner_text("#campo-enviados-lista")
    pg.fill("#campo-enviados-busca", "ninguem assim")
    assert pg.inner_text("#campo-enviados-resumo") == "0 de 3 envio(s) com a busca." and pg.locator("#campo-enviados-lista .checklist-item").count() == 0
    pg.fill("#campo-enviados-busca", "")

    dados["envios"]["novo"] = {"para": "novo@pg.gov.br", "nome": "Escola Nova", "assunto": "Outro", "enviado_em": "2099-01-01T09:00:00", "publico": "pais"}
    _arquivo().write_text(json.dumps(dados), encoding="utf-8")            # alguém enviou enquanto a tela estava aberta
    pg.click("#campo-enviados-atualizar")
    pg.wait_for_selector("#campo-enviados-resumo:has-text('4 de 4')")
    assert "Escola Nova" in pg.locator("#campo-enviados-lista .checklist-item").nth(0).inner_text()   # o mais recente vai para o topo
    assert "responsável" in pg.locator("#campo-enviados-lista .checklist-item").nth(0).inner_text()

    pg.click("#campo-enviados-ver")                                       # esconder
    assert not pg.is_visible("#campo-enviados-painel") and pg.inner_text("#campo-enviados-ver") == "Ver quem já recebeu"
    assert json.loads(_arquivo().read_text(encoding="utf-8")) == dados     # a tela só lê: o registro ficou intacto


def test_sem_nenhum_envio_e_com_registro_corrompido(pagina):
    pg = pagina
    _abrir_avisos(pg)
    pg.click("#campo-enviados-ver")
    pg.wait_for_selector("#campo-enviados-resumo:has-text('Nenhum e-mail foi enviado de verdade ainda.')")
    _arquivo().parent.mkdir(parents=True, exist_ok=True)
    _arquivo().write_text("{quebrado", encoding="utf-8")
    pg.click("#campo-enviados-atualizar")
    pg.wait_for_selector("#campo-enviados-resumo:has-text('Registro de envios')")
    assert pg.locator("#campo-enviados-lista .checklist-item").count() == 0

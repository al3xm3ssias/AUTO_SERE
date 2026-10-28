"""Calendário no Chromium real: abre no mês atual, carrega os dados e não depende da internet."""
import sys
import threading
import time
import urllib.error
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import calendario as cal  # noqa: E402
from src.web.app import create_app  # noqa: E402

playwright_sync = pytest.importorskip("playwright.sync_api")
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
         "Setembro", "Outubro", "Novembro", "Dezembro"]


@pytest.fixture()
def pagina(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "_pasta", lambda: tmp_path / "calendario")
    # Sem internet e LENTO: a BrasilAPI demora 3 s para falhar (o pior caso para a tela).
    def lento(*a, **k):
        time.sleep(3)
        raise urllib.error.URLError("sem rede")
    monkeypatch.setattr(cal.urllib.request, "urlopen", lento)

    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page()
        yield pg, f"http://127.0.0.1:{srv.server_port}"
        nav.close()
    srv.shutdown()


def _abrir_calendario(pg, url):
    pg.goto(url + "/web")
    pg.click('.nav-item[data-view="calendario"]')


def test_abre_no_mes_atual_com_a_grade_desenhada(pagina):
    pg, url = pagina
    hoje = date.today()
    _abrir_calendario(pg, url)
    # A grade tem de aparecer RÁPIDO, sem esperar a internet (que aqui leva 3 s para falhar).
    pg.wait_for_selector("#cal-vista .cal-cell[data-d]", timeout=2000)
    assert pg.inner_text("#cal-titulo") == f"{MESES[hoje.month - 1]} de {hoje.year}"
    assert pg.locator("#cal-vista .cal-cell[data-d]").count() == (
        (date(hoje.year + (hoje.month == 12), hoje.month % 12 + 1, 1) - date(hoje.year, hoje.month, 1)).days)
    assert pg.locator("#cal-vista .cal-cell.hoje").count() == 1
    assert "topbar" and pg.inner_text("#topbar-title") == "Calendário letivo"


def test_eventos_existentes_aparecem_automaticamente(pagina):
    pg, url = pagina
    hoje = date.today()
    inicio = hoje.replace(day=10).isoformat()
    cal.salvar_dados({"eventos": [{"id": "e1", "nome": "Conselho de classe", "tipo": "htpc",
                                   "inicio": inicio, "fim": inicio}], "periodos": []})
    _abrir_calendario(pg, url)
    pg.wait_for_selector(f'#cal-vista .cal-cell[data-d="{inicio}"] .cal-chip', timeout=2000)
    assert "Conselho de classe" in pg.inner_text(f'#cal-vista .cal-cell[data-d="{inicio}"]')


def test_datas_fixas_aparecem_sem_internet(pagina):
    pg, url = pagina
    hoje = date.today()
    _abrir_calendario(pg, url)
    pg.wait_for_selector("#cal-vista .cal-cell[data-d]", timeout=2000)
    # vai até setembro do ano atual (aniversário da cidade, 15/09, é data fixa)
    for _ in range(14):
        if pg.inner_text("#cal-titulo") == f"Setembro de {hoje.year}":
            break
        pg.click("#cal-prev" if date(hoje.year, 9, 1) < hoje.replace(day=1) else "#cal-next")
        pg.wait_for_timeout(120)
    assert pg.inner_text("#cal-titulo") == f"Setembro de {hoje.year}"
    celula = pg.locator(f'#cal-vista .cal-cell[data-d="{hoje.year}-09-15"]')
    assert "Aniversário da cidade" in celula.inner_text()


def test_navegacao_entre_meses(pagina):
    pg, url = pagina
    hoje = date.today()
    _abrir_calendario(pg, url)
    pg.wait_for_selector("#cal-vista .cal-cell[data-d]", timeout=2000)
    pg.click("#cal-next")
    mes = hoje.month % 12 + 1
    ano = hoje.year + (hoje.month == 12)
    pg.wait_for_function(f"document.getElementById('cal-titulo').textContent === '{MESES[mes - 1]} de {ano}'", timeout=2000)
    pg.click("#cal-hoje")
    pg.wait_for_function(f"document.getElementById('cal-titulo').textContent === '{MESES[hoje.month - 1]} de {hoje.year}'", timeout=2000)

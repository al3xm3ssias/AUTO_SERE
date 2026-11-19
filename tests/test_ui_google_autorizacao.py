"""Interface (Chromium real): janela 'Autorizar acesso ao Google' com o link para copiar e o painel Conta Google."""
import json
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.serving import make_server  # noqa: E402

from src.comum import configuracao, google_auth as ga, google_navegador as gn  # noqa: E402
from src.web.app import create_app  # noqa: E402

playwright_sync = pytest.importorskip("playwright.sync_api")

URL = "https://accounts.google.com/o/oauth2/auth?client_id=abc&redirect_uri=http%3A%2F%2Flocalhost%3A5555%2F&state=ST1&login_hint=escola%40gmail.com"


@pytest.fixture()
def servidor(tmp_path, monkeypatch):
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    (tmp_path / "config_usuario.json").write_text(json.dumps({"setup_concluido": True}), encoding="utf-8")
    for v in ("GOOGLE_OAUTH_CONTA", "GOOGLE_OAUTH_NAVEGADOR", "GOOGLE_OAUTH_PERFIL", "GOOGLE_OAUTH_ABRIR_NAVEGADOR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(ga, "_pendente", None)
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture()
def pagina(servidor):
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:                                         # noqa: BLE001
            pytest.skip(f"Chromium indisponível: {exc}")
        ctx = nav.new_context(permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        yield pg, servidor
        nav.close()


def test_janela_mostra_o_link_copia_abre_e_fecha_sozinha(pagina, monkeypatch):
    pg, url = pagina
    pg.goto(url + "/web")
    pg.wait_for_selector("#toast", state="attached")
    ga._registrar_pendente(URL, {"conta": "escola@gmail.com"}, False, "")

    pg.wait_for_selector("#mdl-gaut-link", timeout=8000)                      # o monitor acha a autorização sozinho
    assert pg.input_value("#mdl-gaut-link") == URL
    texto = pg.inner_text(".modal-card")
    assert "escola@gmail.com" in texto and "não foi aberto sozinho" in texto

    pg.click("#mdl-gaut-copiar")
    assert pg.evaluate("navigator.clipboard.readText()") == URL                # o botão realmente copia o link

    abertos = []
    monkeypatch.setattr(gn, "abrir_url", lambda u, **kw: abertos.append(u) or (True, "Google Chrome"))
    pg.click("#mdl-gaut-abrir")
    pg.wait_for_function("document.getElementById('toast-msg').textContent.includes('Aberto em: Google Chrome')")
    assert abertos == [URL]

    ga._limpar_pendente()                                                      # autorização concluída → a janela some
    pg.wait_for_selector(".modal-overlay", state="detached", timeout=8000)


def test_janela_fechada_pelo_usuario_nao_reabre_para_a_mesma_tentativa(pagina):
    pg, url = pagina
    pg.goto(url + "/web")
    ga._registrar_pendente(URL, {"conta": ""}, True, "Google Chrome")
    pg.wait_for_selector("#mdl-gaut-link", timeout=8000)
    assert "Google Chrome" in pg.inner_text(".modal-card")
    pg.click("#mdl-gaut-fechar")
    pg.wait_for_selector(".modal-overlay", state="detached")
    pg.wait_for_timeout(6000)                                                   # passa mais de um ciclo do monitor
    assert pg.locator(".modal-overlay").count() == 0


def test_painel_conta_google_salva_e_recarrega(pagina, tmp_path, monkeypatch):
    pg, url = pagina
    base = tmp_path / "chrome_dados"
    base.mkdir()
    (base / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Profile 2": {"name": "Escola", "user_name": "escola@gmail.com"}}}}), encoding="utf-8")
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(gn, "_pasta_dados_chromium", lambda n: base if n == "chrome" else None)
    monkeypatch.setattr(gn, "localizar_navegador", lambda n: exe if n == "chrome" else None)

    pg.goto(url + "/web")
    pg.click('.nav-item[data-view="configuracoes"]')
    pg.click('.config-row[data-config="google_conta"]')
    pg.wait_for_selector("#cfg-gconta-email")
    pg.wait_for_function("document.querySelector('#cfg-gconta-nav').options.length > 1")
    pg.fill("#cfg-gconta-email", "escola@gmail.com")
    pg.select_option("#cfg-gconta-nav", "chrome")
    assert "Escola — escola@gmail.com" in pg.inner_text("#cfg-gconta-perfil")   # lista de perfis com o e-mail de cada um
    pg.select_option("#cfg-gconta-perfil", "Profile 2")
    pg.fill("#cfg-gconta-email", "escola@gmail.com")      # e-mail editado por último: o clique em Salvar tira o foco dele
    pg.click("#cfg-gconta-salvar")
    pg.wait_for_function("document.getElementById('cfg-gconta-status').textContent.includes('Salvo')")
    assert configuracao.google_oauth_preferencias() == {"conta": "escola@gmail.com", "navegador": "chrome",
                                                        "perfil": "Profile 2", "abrir": True}
    pg.fill("#cfg-gconta-email", "isso não é e-mail")
    pg.click("#cfg-gconta-salvar")
    pg.wait_for_function("document.getElementById('cfg-gconta-status').textContent.includes('e-mail completo')")

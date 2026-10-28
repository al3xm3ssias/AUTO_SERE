"""Teste de interface (Chromium real): wizard de escola + CEP e credenciais mascaradas."""
import json
import sys
import threading
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.serving import make_server  # noqa: E402

from src.comum import configuracao  # noqa: E402
from src.web.app import create_app  # noqa: E402

playwright_sync = pytest.importorskip("playwright.sync_api")


def _zerar_estado_do_wizard(monkeypatch):
    """O painel de registros guarda estado em memória (processo único): isola cada teste."""
    from src.web.api import rotas

    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
        rotas._EVENTOS_WIZARD.clear()
    monkeypatch.setattr(rotas, "_WIZARD_LIMPO_T", 0.0)


@pytest.fixture()
def servidor(tmp_path, monkeypatch):
    _zerar_estado_do_wizard(monkeypatch)
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", tmp_path
    srv.shutdown()


@pytest.fixture()
def pagina(servidor):
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:  # Chromium não instalado neste ambiente
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page()
        yield pg, servidor
        nav.close()


def _abrir_wizard(pg, url):
    pg.goto(url + "/web")
    pg.click('.nav-item[data-view="primeira-execucao"]')
    pg.wait_for_selector("#wizard-lista .wizard-step")


def test_wizard_escola_com_cep(pagina, monkeypatch):
    pg, (url, cfg_dir) = pagina

    chamadas = []
    original = requests.get

    class R:
        status_code = 200
        def json(self): return {"logradouro": "Avenida Antônio Saad", "bairro": "Jardim Carvalho",
                                "localidade": "Ponta Grossa", "uf": "PR"}
        def raise_for_status(self): pass

    def falso(u, **k):
        if "viacep" in u:
            chamadas.append(u)
            return R()
        return original(u, **k)
    monkeypatch.setattr(requests, "get", falso)

    _abrir_wizard(pg, url)
    primeiro = pg.locator("#wizard-lista .wizard-step").first
    assert "Dados da escola" in primeiro.inner_text()
    primeiro.locator("[data-wizard-run]").click()

    pg.wait_for_selector(".modal-card #esc-nome")
    pg.fill("#esc-nome", "Escola Municipal Teste")
    pg.fill("#esc-cep", "84016630")
    assert pg.input_value("#esc-cep") == "84016-630"          # máscara
    pg.click("#esc-buscar-cep")
    pg.wait_for_function("document.querySelector('#esc-cidade').value !== ''")
    assert pg.input_value("#esc-logradouro") == "Avenida Antônio Saad"
    assert pg.input_value("#esc-cidade") == "Ponta Grossa" and pg.input_value("#esc-uf") == "PR"
    assert chamadas and chamadas[0].endswith("/84016630/json/")

    pg.fill("#esc-numero", "935")
    pg.click("#esc-salvar")
    pg.wait_for_selector(".modal-card", state="detached")

    salvo = json.loads((cfg_dir / "config_usuario.json").read_text(encoding="utf-8"))["unidade_escolar"]
    assert salvo["nome"] == "Escola Municipal Teste" and salvo["cep"] == "84016630"
    assert salvo["endereco"] == "Avenida Antônio Saad, 935" and salvo["uf"] == "PR"
    pg.wait_for_selector("#wizard-lista .wizard-step.done")    # passo vira "Concluído"


def test_wizard_escola_erro_de_validacao_mantem_modal(pagina):
    pg, (url, cfg_dir) = pagina
    _abrir_wizard(pg, url)
    pg.locator("#wizard-lista [data-wizard-run]").first.click()
    pg.wait_for_selector("#esc-nome")
    pg.fill("#esc-cep", "123")
    pg.click("#esc-salvar")
    pg.wait_for_selector("#toast.show")
    assert "CEP" in pg.inner_text("#toast-msg")
    assert pg.locator(".modal-card").count() == 1              # não fechou: nada foi perdido
    assert not (cfg_dir / "config_usuario.json").exists()


def test_credenciais_do_sere_usam_campo_mascarado(pagina):
    pg, (url, _) = pagina
    _abrir_wizard(pg, url)
    pg.locator('[data-wizard-run="credenciais_sere"]').click()
    pg.wait_for_selector("#mdl-sere-senha")
    assert pg.get_attribute("#mdl-sere-senha", "type") == "password"
    pg.click("#mdl-cancelar")
    pg.wait_for_selector(".modal-card", state="detached")


def test_painel_de_configuracoes_da_escola(pagina):
    pg, (url, _) = pagina
    pg.goto(url + "/web")
    pg.click('.nav-item[data-view="configuracoes"]')
    pg.click('.config-row[data-config="escola"]')
    pg.wait_for_selector("#cfg-escola-form #esc-nome")
    pg.wait_for_function("document.querySelector('#esc-status').textContent.includes('Pendente')")
    pg.fill("#esc-nome", "Escola X")
    pg.fill("#esc-cep", "84016630")
    pg.fill("#esc-logradouro", "Rua A")
    pg.click("#esc-salvar")
    pg.wait_for_function("document.querySelector('#esc-status').textContent.includes('salvos')")


def test_assistente_abre_sozinho_quando_escola_nao_configurada(pagina):
    pg, (url, _) = pagina
    pg.goto(url + "/web")
    pg.wait_for_selector("#sec-primeira-execucao.active")


def test_assistente_nao_abre_se_escola_ja_configurada(pagina):
    pg, (url, _) = pagina
    r = requests.post(url + "/web/api/configuracoes/escola",
                      json={"nome": "Escola Y", "cep": "84016630", "logradouro": "Rua A"})
    assert r.status_code == 200
    pg.goto(url + "/web")
    pg.wait_for_selector("#sec-painel.active")
    pg.wait_for_timeout(800)   # tempo para a checagem assíncrona rodar
    assert pg.locator("#sec-primeira-execucao.active").count() == 0


def test_painel_de_registros_acompanha_um_passo_em_tempo_real(pagina, monkeypatch):
    import asyncio

    import src.automacao.turmas as turmas_mod

    async def falso():
        print("Entrando no SERE...")
        await asyncio.sleep(1.2)
        print("12 turmas coletadas")

    from src.web.api import rotas

    monkeypatch.setattr(turmas_mod, "coletar_turmas_e_alunos_via_login", falso)
    pg, (url, cfg_dir) = pagina
    monkeypatch.setattr(rotas, "_dados_dir", lambda: cfg_dir)   # não depender de dados reais do projeto
    _abrir_wizard(pg, url)

    pg.wait_for_selector("#wizard-log-corpo .wl-vazio")                # estado vazio amigável
    pg.locator('[data-wizard-run="turmas"]').click()
    pg.wait_for_selector('text=▶ Iniciando: Turmas')
    pg.wait_for_selector('#wizard-lista [data-wizard-cancel="turmas"]')   # mostra Cancelar enquanto roda
    pg.wait_for_function("document.querySelector('#wizard-log-status').textContent.includes('Executando')")
    pg.wait_for_selector("text=12 turmas coletadas")
    pg.wait_for_selector("text=✓ Concluído: Turmas")
    pg.wait_for_selector('#wizard-lista [data-wizard-cancel="turmas"]', state="detached")
    pg.wait_for_function("document.querySelector('#wizard-log-status').textContent.includes('Nada em execução')")

    pg.click("#wizard-log-limpar")
    pg.wait_for_selector("#wizard-log-corpo .wl-vazio")

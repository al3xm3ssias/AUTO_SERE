"""Configurações → "Turmas do QR antigo" no Chromium: cadastrar pares, testar, salvar e ver a lista de volta."""
import json
import threading

import pytest
from werkzeug.serving import make_server

from src.web.api import rotas
from src.web.app import create_app

playwright_sync = pytest.importorskip("playwright.sync_api")

TURMAS = ["3º Ano Integral A", "INFANTIL 4 Integral A", "INFANTIL 5 Integral A"]


@pytest.fixture()
def pagina(tmp_path, monkeypatch):
    from src.comum import configuracao
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    # a tela grava configurações: nunca no config/config_usuario.json de verdade
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    (tmp_path / "turmas.json").write_text(json.dumps({t: [] for t in TURMAS}, ensure_ascii=False), encoding="utf-8")
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page()
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        yield pg
        nav.close()
    srv.shutdown()


def _abrir_painel(pg):
    pg.locator('.nav-item[data-view="configuracoes"]').dispatch_event("click")
    pg.locator('.config-row[data-config="mapeamento_turmas_qr"]').click()
    pg.wait_for_selector("#cfg-qr-linhas")
    pg.wait_for_selector("#cfg-qr-linhas:has-text('Nenhum par'), #cfg-qr-linhas .cfg-qr-linha")


def test_cadastrar_testar_salvar_e_reabrir(pagina):
    from src.comum import configuracao
    pg = pagina
    _abrir_painel(pg)
    assert "Nenhum par cadastrado" in pg.inner_text("#cfg-qr-linhas")

    pg.click("#cfg-qr-add")
    assert pg.locator(".cfg-qr-linha").count() == 1
    assert pg.locator(".cfg-qr-linha select option").count() == len(TURMAS) + 1               # + "— escolha a turma —"
    pg.fill(".cfg-qr-linha .cfg-qr-texto", "sala do meio")
    pg.select_option(".cfg-qr-linha .cfg-qr-turma", "INFANTIL 5 Integral A")

    pg.fill("#cfg-qr-teste", "SALA DO MEIO")                                                    # linha ainda não salva já vale no teste
    pg.click("#cfg-qr-testar")
    pg.wait_for_selector("#cfg-qr-resultado:has-text('INFANTIL 5 Integral A')")
    assert "ainda não salva" in pg.inner_text("#cfg-qr-resultado")
    assert configuracao.mapeamento_turmas_qr() == {}

    pg.fill("#cfg-qr-teste", "INF 4 A")                                                         # o sistema já resolve esta
    pg.click("#cfg-qr-testar")
    pg.wait_for_selector("#cfg-qr-resultado:has-text('INFANTIL 4 Integral A')")
    pg.fill("#cfg-qr-teste", "turma que ninguém conhece")
    pg.press("#cfg-qr-teste", "Enter")
    pg.wait_for_selector("#cfg-qr-resultado:has-text('Nenhuma turma encontrada')")

    pg.click("#cfg-qr-salvar")
    pg.wait_for_selector("#cfg-qr-status:has-text('1 par(es) salvo(s)')")
    assert configuracao.mapeamento_turmas_qr() == {"SALA DO MEIO": "INFANTIL 5 Integral A"}

    pg.locator('.config-row[data-config="mapeamento_turmas_qr"]').click()                       # reabre: vem do arquivo
    pg.wait_for_selector(".cfg-qr-linha")
    assert pg.input_value(".cfg-qr-linha .cfg-qr-texto") == "SALA DO MEIO"
    assert pg.input_value(".cfg-qr-linha .cfg-qr-turma") == "INFANTIL 5 Integral A"

    pg.click(".cfg-qr-remover")                                                                 # remover + salvar esvazia
    assert "não salvas" in pg.inner_text("#cfg-qr-status")
    pg.click("#cfg-qr-salvar")
    pg.wait_for_selector("#cfg-qr-linhas:has-text('Nenhum par cadastrado')")
    assert configuracao.mapeamento_turmas_qr() == {}


def test_linha_pela_metade_e_recusada_e_turma_que_sumiu_aparece_marcada(pagina):
    from src.comum import configuracao
    configuracao.definir_mapeamento_turmas_qr([("ANTIGA", "Turma que sumiu")])
    pg = pagina
    _abrir_painel(pg)
    assert "Turma que sumiu (não existe mais)" in pg.inner_text(".cfg-qr-linha select")
    pg.click("#cfg-qr-add")
    pg.fill(".cfg-qr-linha:last-child .cfg-qr-texto", "SO O TEXTO")                             # falta a turma
    pg.click("#cfg-qr-salvar")
    pg.wait_for_selector("#toast.show:has-text('Linha 2')")
    assert configuracao.mapeamento_turmas_qr() == {"ANTIGA": "Turma que sumiu"}                 # nada foi alterado


def test_turmas_nao_reconhecidas_aparecem_e_um_clique_abre_a_linha(pagina, tmp_path):
    from src.comum import configuracao
    from src.comum import qr_turmas_nao_reconhecidas as anotados
    for texto, arquivo in (("SALA DO MEIO", "scan 01.pdf"), ("SALA DO MEIO", "scan 02.pdf"), ("LEITURA RUIM", "scan 03.pdf")):
        anotados.registrar(tmp_path, texto, arquivo)
    pg = pagina
    _abrir_painel(pg)
    pg.wait_for_selector(".cfg-qr-sugestao")
    quadro = pg.inner_text("#cfg-qr-sugestoes")
    assert "não reconheceu" in quadro and "SALA DO MEIO" in quadro and "2 pareceres" in quadro and "scan 01.pdf, scan 02.pdf" in quadro
    assert pg.locator(".cfg-qr-sugestao").count() == 2
    pg.screenshot(path="/tmp/painel_qr_sugestoes.png")

    pg.click('.cfg-qr-ignorar[data-texto="LEITURA RUIM"]')                                      # leitura ruim: sai da lista (e do arquivo)
    pg.wait_for_function("document.querySelectorAll('.cfg-qr-sugestao').length === 1")
    assert [i["texto"] for i in anotados.listar(tmp_path)] == ["SALA DO MEIO"]

    pg.click('.cfg-qr-usar[data-texto="SALA DO MEIO"]')                                         # abre a linha com o texto; falta a turma
    assert pg.input_value(".cfg-qr-linha .cfg-qr-texto") == "SALA DO MEIO" and pg.input_value(".cfg-qr-linha .cfg-qr-turma") == ""
    assert "Escolha a turma" in pg.inner_text("#cfg-qr-status")
    pg.click('.cfg-qr-usar[data-texto="SALA DO MEIO"]')                                         # de novo: não duplica a linha
    assert pg.locator(".cfg-qr-linha").count() == 1

    pg.select_option(".cfg-qr-linha .cfg-qr-turma", "INFANTIL 5 Integral A")
    pg.click("#cfg-qr-salvar")
    pg.wait_for_selector("#cfg-qr-status:has-text('1 par(es) salvo(s)')")
    assert configuracao.mapeamento_turmas_qr() == {"SALA DO MEIO": "INFANTIL 5 Integral A"}
    assert pg.locator(".cfg-qr-sugestao").count() == 0 and "não reconheceu" not in pg.inner_text("#cfg-qr-sugestoes")   # resolvido: o quadro some
    assert anotados.listar(tmp_path) == []

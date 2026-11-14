"""Tela de Automações no Chromium: Turmas e Alunos (modo básico/completo)."""
import threading
from pathlib import Path

import pytest

from werkzeug.serving import make_server

from src.web.api import rotas
from src.web.app import create_app

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def pagina(tmp_path, monkeypatch):
    from src.comum import configuracao
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    # a tela grava configurações (navegador, flags...): nunca no config/config_usuario.json de verdade
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    (tmp_path / "turmas.json").write_text('{"5A": []}', encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
        rotas._EVENTOS_WIZARD.clear()

    import src.automacao.alunos as alunos_mod
    import src.automacao.alunos_completo as completo_mod
    import src.automacao.turmas as turmas_mod

    async def fake_turmas():
        print("LINHA-TURMAS coleta simulada")

    async def fake_alunos():
        print("LINHA-BASICO coleta simulada")

    async def fake_completo(modo_rapido=False):
        print(f"LINHA-COMPLETO rapido={modo_rapido}")

    monkeypatch.setattr(turmas_mod, "coletar_turmas_e_alunos_via_login", fake_turmas)
    monkeypatch.setattr(alunos_mod, "coletar_alunos_via_login", fake_alunos)
    monkeypatch.setattr(completo_mod, "coletar_cadastro_completo_via_login", fake_completo)

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


def _abrir(pg, chave):
    pg.click("#toggle-automacoes")                                    # abre o grupo "Automações" do menu
    # dispatch_event: o item pode estar rolado para baixo de outro grupo do menu em janelas baixas; o clique do usuário
    # chega ao mesmo handler.
    pg.locator(f'#sub-automacoes .nav-subitem[data-auto="{chave}"]').dispatch_event("click")
    pg.wait_for_selector("#automacoes-execucao", state="visible")


def _executar_e_capturar(pg, chave):
    with pg.expect_request(f"**/automacoes/{chave}/executar") as req:
        pg.click("#btn-executar-tarefa")
    return req.value.post_data_json


def test_turmas_e_alunos_sao_os_primeiros_itens_do_menu(pagina):
    pg = pagina
    pg.click("#toggle-automacoes")
    todas = pg.locator("#sub-automacoes .nav-subitem").evaluate_all("els => els.map(e => e.dataset.auto)")
    assert todas[:2] == ["turmas", "alunos"]
    # automações que antes só abriam pela lista de automações agora têm item no menu
    assert {"aluno", "validar", "espec", "limpeza", "prematricula_completa"} <= set(todas)
    assert len(todas) == len(set(todas))
    rotulos = pg.locator("#sub-automacoes .nav-subitem .nav-item-label").evaluate_all("els => els.slice(0, 2).map(e => e.textContent.trim())")
    assert rotulos == ["Turmas", "Alunos"]


def test_aparecem_tambem_na_lista_de_automacoes(pagina):
    pg = pagina
    _abrir(pg, "turmas")
    pg.click("#btn-voltar-automacoes")                                       # volta para a lista
    pg.wait_for_selector('.automation-row[data-auto="turmas"]')
    assert pg.locator('.automation-row[data-auto="alunos"]').count() == 1
    assert "alunos_completo.py" in pg.inner_text('.automation-row[data-auto="alunos"]')


def test_turmas_nao_pede_parametros_e_executa(pagina):
    pg = pagina
    _abrir(pg, "turmas")
    pg.wait_for_function("document.getElementById('campos-automacao').textContent.includes('não precisa de parâmetros')")
    assert _executar_e_capturar(pg, "turmas") == {"automacao": "turmas"}
    pg.wait_for_function("document.getElementById('exec-log')?.textContent.includes('LINHA-TURMAS')")


def test_alunos_modo_basico_e_o_padrao_e_explica_cada_modo(pagina):
    pg = pagina
    _abrir(pg, "alunos")
    assert pg.input_value("#campo-modo") == "basico"
    assert pg.locator("#campo-modo option").evaluate_all("els => els.map(e => e.textContent)") == [
        "Básico (alunos.py)", "Completo (alunos_completo.py)"]                # sem opção vazia "Selecione..."
    assert "tela de consulta" in pg.inner_text("#campo-modo-ajuda")
    assert not pg.locator("#campo-rapido").is_visible()                       # "Modo rápido" é só do completo
    assert _executar_e_capturar(pg, "alunos") == {"automacao": "alunos", "modo": "basico", "rapido": False}
    pg.wait_for_function("document.getElementById('exec-log')?.textContent.includes('LINHA-BASICO')")


def test_alunos_modo_completo_mostra_o_modo_rapido_e_envia_as_escolhas(pagina):
    pg = pagina
    _abrir(pg, "alunos")
    pg.select_option("#campo-modo", "completo")
    assert "tela de edição" in pg.inner_text("#campo-modo-ajuda") and "Turmas" in pg.inner_text("#campo-modo-ajuda")
    assert pg.locator("#campo-rapido").is_visible()
    assert pg.locator("#campo-rapido").is_checked() is False
    pg.check("#campo-rapido")
    assert _executar_e_capturar(pg, "alunos") == {"automacao": "alunos", "modo": "completo", "rapido": True}
    pg.wait_for_function("document.getElementById('exec-log')?.textContent.includes('LINHA-COMPLETO rapido=True')")


def test_voltar_ao_basico_esconde_o_modo_rapido_de_novo(pagina):
    pg = pagina
    _abrir(pg, "alunos")
    pg.select_option("#campo-modo", "completo")
    assert pg.locator("#campo-rapido").is_visible()
    pg.select_option("#campo-modo", "basico")
    assert not pg.locator("#campo-rapido").is_visible()
    assert "tela de consulta" in pg.inner_text("#campo-modo-ajuda")


def test_modo_completo_sem_turmas_json_mostra_a_orientacao(pagina, tmp_path):
    pg = pagina
    (tmp_path / "turmas.json").unlink()
    _abrir(pg, "alunos")
    pg.select_option("#campo-modo", "completo")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "Turmas" in pg.inner_text("#toast-msg")


def test_backup_nao_pede_mais_uma_pasta_que_era_ignorada(pagina):
    pg = pagina
    _abrir(pg, "backup")
    pg.wait_for_function("document.getElementById('campos-automacao').textContent.includes('não precisa de parâmetros')")
    assert pg.locator("#btn-escolher-pasta").count() == 0


def _visivel(pg, campo_id):
    return pg.evaluate("(id) => { const el = document.getElementById(id).closest('.field'); return el.style.display !== 'none'; }", campo_id)


def test_funcionarios_e_vinculos_estao_no_menu_e_vinculos_mostra_os_campos_de_cada_modo(pagina):
    pg = pagina
    pg.click("#toggle-automacoes")
    for chave, rotulo in (("funcionarios", "Funcionários / Servidores"), ("vinculos", "Vínculos dos funcionários")):
        assert pg.locator(f'#sub-automacoes .nav-subitem[data-auto="{chave}"] .nav-item-label').inner_text().strip() == rotulo
    _abrir(pg, "vinculos")
    pg.wait_for_selector("#campo-modo-vinc")
    assert pg.eval_on_selector("#campo-modo-vinc", "e => e.value") == "completo"
    estado = lambda: {c: _visivel(pg, c) for c in ("campo-so-nome", "campo-pular-holerite", "campo-mes-holerite", "campo-atualizar-sere", "campo-forcar-rh")}
    assert estado() == {"campo-so-nome": False, "campo-pular-holerite": True, "campo-mes-holerite": True, "campo-atualizar-sere": True, "campo-forcar-rh": True}
    pg.select_option("#campo-modo-vinc", "sere")
    assert estado() == {"campo-so-nome": False, "campo-pular-holerite": False, "campo-mes-holerite": False, "campo-atualizar-sere": False, "campo-forcar-rh": False}
    pg.select_option("#campo-modo-vinc", "vincular")
    assert estado() == {"campo-so-nome": False, "campo-pular-holerite": False, "campo-mes-holerite": False, "campo-atualizar-sere": True, "campo-forcar-rh": True}
    pg.select_option("#campo-modo-vinc", "homonimos")
    assert estado() == {"campo-so-nome": True, "campo-pular-holerite": False, "campo-mes-holerite": True, "campo-atualizar-sere": True, "campo-forcar-rh": True}


def test_vinculos_envia_o_modo_e_o_nome_escolhidos(pagina, monkeypatch):
    from src.comum import escola
    monkeypatch.setattr(escola, "nome", lambda: "Escola Municipal Teste")          # sem o nome da escola a prévia recusa (holerite)
    pg = pagina
    _abrir(pg, "vinculos")
    pg.wait_for_selector("#campo-modo-vinc")
    pg.select_option("#campo-modo-vinc", "homonimos")
    pg.fill("#campo-so-nome", "Carla Dias")
    pg.fill("#campo-mes-holerite", "09-2026")
    corpo = _executar_e_capturar(pg, "vinculos")
    assert corpo["modo"] == "homonimos" and corpo["so_nome"] == "Carla Dias" and corpo["mes"] == "09-2026"


def test_pareceres_digitalizados_mostra_os_campos_de_e_mail_so_quando_ha_e_mail(pagina):
    pg = pagina
    _abrir(pg, "pareceres_digitalizados")
    pg.wait_for_selector("#campo-email-modo")
    assert pg.eval_on_selector("#campo-email-modo", "e => e.value") == "nao"                 # padrão: não manda e-mail
    assert pg.is_checked("#campo-simulacao") and not pg.is_checked("#campo-enviar-sere")      # padrão seguro: simulação, sem SERE
    estado = lambda: {c: _visivel(pg, c) for c in ("campo-email-teste", "campo-email-assunto", "campo-email-mensagem")}
    assert estado() == {"campo-email-teste": False, "campo-email-assunto": False, "campo-email-mensagem": False}
    pg.select_option("#campo-email-modo", "teste")
    assert estado() == {"campo-email-teste": True, "campo-email-assunto": True, "campo-email-mensagem": True}
    pg.select_option("#campo-email-modo", "enviar")
    assert estado() == {"campo-email-teste": False, "campo-email-assunto": True, "campo-email-mensagem": True}
    assert "Parecer descritivo de $ALUNO" in pg.eval_on_selector("#campo-email-assunto", "e => e.value")
    assert "$RESPONSAVEL" in pg.eval_on_selector("#campo-email-mensagem", "e => e.value")


# ───────────────── tela única: sem abas, com configurações do script e histórico ─────────────────

def test_tela_da_automacao_nao_tem_abas_e_mostra_configuracoes_e_historico(pagina):
    _abrir(pagina, "transferidos_gerar")
    assert pagina.locator("#automacoes-execucao .tab-btn").count() == 0
    assert pagina.locator("#automacoes-execucao .tabs").count() == 0
    pagina.wait_for_selector("#cfg-sistema .cfg-linha")
    assert pagina.locator("#secao-config-script").is_visible()
    texto = pagina.inner_text("#secao-config-script").casefold()          # os subtítulos são exibidos em maiúsculas (CSS)
    for esperado in ("Escolhido a cada execução", "Login do SERE", "Data de corte dos transferidos",
                     "Pasta de digitalização", "Modo de teste"):
        assert esperado.casefold() in texto, esperado
    pagina.wait_for_selector("#historico-script-corpo .script-vazio")
    assert "Ainda não há execuções" in pagina.inner_text("#historico-script-corpo")
    assert pagina.locator("#btn-executar-tarefa").is_visible()              # o Executar continua na mesma tela


def test_opcoes_guardadas_do_script_ficam_dentro_das_configuracoes(pagina):
    _abrir(pagina, "analisa_sere")
    pagina.wait_for_selector("#cfg-flags:not([hidden]) input[data-flag]")
    assert pagina.locator("#secao-config-script #flags-automacao").count() == 1
    # a próxima automação não tem flags guardadas: o bloco some
    pagina.click("#btn-voltar-automacoes")
    pagina.locator('#sub-automacoes .nav-subitem[data-auto="turmas"]').dispatch_event("click")
    pagina.wait_for_selector("#cfg-sistema .cfg-linha")
    assert pagina.locator("#cfg-flags").is_hidden()


def test_historico_mostra_o_que_deu_certo_e_o_que_deu_errado(pagina, monkeypatch):
    import src.automacao.turmas as turmas_mod

    async def coleta_com_falha():
        print("✅ 5A coletada")
        print("❌ 5B não abriu")

    monkeypatch.setattr(turmas_mod, "coletar_turmas_e_alunos_via_login", coleta_com_falha)
    _abrir(pagina, "turmas")
    pagina.click("#btn-executar-tarefa")
    pagina.wait_for_selector("#historico-script-corpo .hist-item", timeout=15000)
    item = pagina.locator("#historico-script-corpo .hist-item").first
    assert "Concluída com erros" in item.inner_text()
    item.locator("summary").click()
    pagina.wait_for_selector("#historico-script-corpo .hist-col.certo li")
    assert "5A coletada" in pagina.inner_text("#historico-script-corpo .hist-col.certo")
    assert "5B não abriu" in pagina.inner_text("#historico-script-corpo .hist-col.errado")

    pagina.once("dialog", lambda d: d.accept())
    pagina.click("#btn-historico-limpar")
    pagina.wait_for_selector("#historico-script-corpo .script-vazio")
    assert pagina.locator("#historico-script-corpo .hist-item").count() == 0


# ───────────────── navegador: padrão global (Configurações) e "ver a janela" por script ─────────────────

def test_ver_janela_do_script_e_salvo_e_volta_marcado(pagina):
    from src.comum import configuracao
    _abrir(pagina, "turmas")
    pagina.wait_for_selector("#cfg-navegador:not([hidden]) #cfg-ver-janela")
    assert "Chrome" in pagina.inner_text("#cfg-navegador") and not pagina.is_checked("#cfg-ver-janela")
    pagina.check("#cfg-ver-janela")
    pagina.wait_for_function("() => !document.getElementById('cfg-ver-janela').disabled")
    assert configuracao.mostrar_janela_script("turmas") is True
    pagina.click("#btn-voltar-automacoes")
    pagina.locator('#sub-automacoes .nav-subitem[data-auto="turmas"]').dispatch_event("click")
    pagina.wait_for_selector("#cfg-ver-janela")
    assert pagina.is_checked("#cfg-ver-janela")                      # a escolha ficou salva


def test_script_que_nao_abre_navegador_nao_mostra_o_bloco(pagina):
    _abrir(pagina, "backup")
    pagina.wait_for_selector("#cfg-sistema .cfg-linha")
    assert pagina.locator("#cfg-navegador").is_hidden()


def test_navegador_padrao_se_escolhe_em_configuracoes(pagina):
    from src.comum import configuracao
    pagina.locator('.nav-item[data-view="configuracoes"]').dispatch_event("click")
    pagina.locator('.config-row[data-config="navegador"]').click()
    pagina.wait_for_selector('input[name="cfg-nav"]')
    assert pagina.locator('input[name="cfg-nav"]').count() == 3
    assert pagina.locator('input[name="cfg-nav"][value="automatico"]').is_checked()
    pagina.check('input[name="cfg-nav"][value="firefox"]')
    pagina.click("#cfg-nav-salvar")
    pagina.wait_for_selector("#cfg-nav-status:has-text('Salvo'), #cfg-nav-status:has-text('salvo')")
    assert configuracao.navegador_padrao() == "firefox"

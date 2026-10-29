"""Componentes compartilhados na tela de Automações (Chromium real)."""
import json
import threading

import pytest
from werkzeug.serving import make_server

from src.web.api import rotas
from src.web.app import create_app

playwright_sync = pytest.importorskip("playwright.sync_api")


def _al(cgm, nome, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": sit}


TURMAS = {
    "3º Ano Integral A": [_al("3000000001", "Ana"), _al("3000000002", "Beto", "Transferido")],
    "3º Ano Integral B": [_al("3000000003", "Caio")],
    "5º Ano Integral A": [_al("5000000001", "Duda")],
}


@pytest.fixture()
def tela(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    planos = []

    def captura(chave, plano):                    # não executa nada de verdade; registra o plano e finge terminar
        planos.append((chave, plano))
        rotas._rodar_funcao_sincrona_em_thread(chave, lambda: None)

    monkeypatch.setattr(rotas, "_executar_plano", captura)
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page()
        pg.set_default_timeout(6000)              # falha rápido em vez de esperar 30 s por seletor
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        yield pg, planos, tmp_path
        nav.close()
    srv.shutdown()


def abrir(pg, chave, esperar="#comp-previa"):
    """Abre a automação como o usuário: pelo menu lateral, se tiver item, ou pela lista de automações."""
    item = pg.locator(f'#sub-automacoes .nav-subitem[data-auto="{chave}"]')
    if item.count():
        if not pg.locator("#sub-automacoes.open").count():   # o clique no grupo alterna: só expande se estiver fechado
            pg.click("#toggle-automacoes")
        item.click()
    else:
        pg.evaluate("irPara('automacoes')")
        pg.click(f'.automation-row[data-auto="{chave}"]')
    pg.wait_for_selector("#automacoes-execucao", state="visible")
    pg.wait_for_selector(esperar, state="attached")


def previa(pg):
    pg.wait_for_function("document.getElementById('comp-previa') && document.getElementById('comp-previa').textContent.length > 0")
    return pg.inner_text("#comp-previa")


def esperar_previa(pg, trecho):
    pg.wait_for_function("(t) => document.getElementById('comp-previa').textContent.includes(t)", arg=trecho)


def aguardar(planos, n=1, limite=5.0):
    """O Playwright resolve quando a requisição é ENVIADA; espera o servidor registrar o plano."""
    import time
    fim = time.time() + limite
    while len(planos) < n and time.time() < fim:
        time.sleep(0.02)
    assert len(planos) >= n, "o servidor não recebeu a execução"
    return planos


def executar(pg, chave):
    with pg.expect_request(f"**/automacoes/{chave}/executar") as req:
        pg.click("#btn-executar-tarefa")
    return req.value.post_data_json


# ───────────── turma + situação + teste ─────────────

def test_componentes_do_validar(tela):
    pg, _, _ = tela
    abrir(pg, "validar")
    assert pg.locator("#comp-turma option").first.inner_text() == "Todas as turmas"
    assert pg.locator("#comp-turma optgroup").evaluate_all("els => els.map(e => e.label)") == ["Por ano", "Turma específica"]
    assert "3º Ano Integral (todas as turmas)" in pg.locator("#comp-turma optgroup").first.inner_text()
    assert pg.locator("#comp-matriculados").is_checked() and not pg.locator("#comp-transferidos").is_checked()
    assert pg.locator("#comp-cgm").count() == 0 and pg.locator("#comp-erros").count() == 0
    assert "PRIMEIRO aluno" in pg.inner_text("#campos-automacao") and "não é simulação" in pg.inner_text("#campos-automacao")


def test_previa_acompanha_as_escolhas(tela):
    pg, _, _ = tela
    abrir(pg, "validar")
    assert previa(pg) == "Prévia: 3 aluno(s) — 3 matriculado(s) — em 3 turma(s)."
    pg.check("#comp-transferidos")
    esperar_previa(pg, "4 aluno(s) — 3 matriculado(s) e 1 transferido(s)")
    pg.select_option("#comp-turma", "g:3º Ano Integral")
    esperar_previa(pg, "3 aluno(s) — 2 matriculado(s) e 1 transferido(s) — em 2 turma(s)")
    pg.uncheck("#comp-matriculados")
    esperar_previa(pg, "1 aluno(s) — 1 transferido(s) — em 1 turma(s)")
    pg.uncheck("#comp-transferidos")                                              # nada marcado: erro, não prévia
    esperar_previa(pg, "Matriculados ou Transferidos")
    assert pg.locator("#comp-previa.aviso").count() == 1


def test_payload_enviado_pelo_componente_de_turma_e_situacao(tela):
    pg, planos, _ = tela
    abrir(pg, "analisa_sere")
    pg.select_option("#comp-turma", "g:3º Ano Integral")
    pg.check("#comp-transferidos")
    esperar_previa(pg, "3 aluno(s)")
    body = executar(pg, "analisa_sere")
    assert body["turmas"] == ["3º Ano Integral A", "3º Ano Integral B"]
    assert body["matriculados"] is True and body["transferidos"] is True and body["automacao"] == "analisa_sere"
    assert aguardar(planos)[0][1].kwargs["args_extras"] == ["--turma", "3º Ano Integral A", "3º Ano Integral B", "--matriculados", "--transferidos"]


def test_turma_especifica(tela):
    pg, _, _ = tela
    abrir(pg, "analisa_sere")
    pg.select_option("#comp-turma", "t:5º Ano Integral A")
    esperar_previa(pg, "1 aluno(s) — 1 matriculado(s) — em 1 turma(s)")
    assert executar(pg, "analisa_sere")["turmas"] == ["5º Ano Integral A"]


def test_sem_turmas_json_orienta_a_rodar_turmas_primeiro(tela):
    pg, _, tmp = tela
    (tmp / "turmas.json").unlink()
    abrir(pg, "validar")
    assert "execute primeiro a automação Turmas" in pg.inner_text("#campos-automacao")
    assert pg.locator("#comp-turma").count() == 0


# ───────────── confirmação antes de alterar o SERE ─────────────

def test_confirmacao_mostra_aviso_e_previa_e_cancelar_nao_executa(tela):
    pg, planos, _ = tela
    abrir(pg, "limpeza")
    previa(pg)
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector(".modal-card")
    texto = pg.inner_text(".modal-card")
    assert "Confirmar execução" in texto and "REMOVE TODOS os arquivos" in texto and "3 aluno(s)" in texto
    assert "Modo de teste" in texto                                                   # dica para testar com 1 antes
    pg.click("#conf-nao")
    pg.wait_for_selector(".modal-card", state="detached")
    pg.wait_for_timeout(300)
    assert planos == []                                                               # nada foi executado


def test_confirmar_executa(tela):
    pg, planos, _ = tela
    abrir(pg, "limpeza")
    previa(pg)
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector(".modal-card")
    with pg.expect_request("**/automacoes/limpeza/executar") as req:
        pg.click("#conf-sim")
    assert req.value.post_data_json["modo_teste"] is False
    assert aguardar(planos)[0][0] == "limpeza"


def test_modo_de_teste_dispensa_a_confirmacao(tela):
    pg, planos, _ = tela
    abrir(pg, "limpeza")
    pg.check("#comp-teste")
    body = executar(pg, "limpeza")
    assert body["modo_teste"] is True and pg.locator(".modal-card").count() == 0


def test_script_de_leitura_nao_pede_confirmacao(tela):
    pg, _, _ = tela
    abrir(pg, "analisa_sere")
    previa(pg)
    executar(pg, "analisa_sere")
    assert pg.locator(".modal-card").count() == 0


def test_erro_de_preenchimento_nao_abre_confirmacao_e_mostra_a_mensagem(tela):
    pg, planos, _ = tela
    abrir(pg, "limpeza")
    pg.uncheck("#comp-matriculados")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "Matriculados ou Transferidos" in pg.inner_text("#toast-msg")
    assert pg.locator(".modal-card").count() == 0 and planos == []


# ───────────── CGM ─────────────

def test_cgm_confere_ao_vivo_e_aceita_varios_formatos(tela):
    pg, planos, _ = tela
    abrir(pg, "analisa_sere")
    assert "opcional" in pg.inner_text("#campos-automacao")
    pg.fill("#comp-cgm", "3000000001, 5000000001;\n3000000001 abc\n9999999999")
    pg.wait_for_function("document.getElementById('comp-cgm-previa').textContent.includes('inválido')")
    t = pg.inner_text("#comp-cgm-previa")
    assert "3 CGM(s) válido(s)" in t and "1 inválido(s): abc" in t and "1 repetido(s)" in t and "1 não está(ão) em turmas.json" in t
    pg.fill("#comp-cgm", "3000000001, 5000000001;\n3000000001\n3000000003")
    esperar_previa(pg, "3 de 3 CGM(s) encontrado(s)")
    body = executar(pg, "analisa_sere")
    assert body["cgms_texto"] == "3000000001, 5000000001;\n3000000001\n3000000003"
    assert aguardar(planos)[0][1].kwargs["args_extras"] == ["--cgm", "3000000001", "5000000001", "3000000003"]


def test_alunos_por_cgm_exige_cgm_e_nao_pede_confirmacao_antes_do_erro(tela):
    pg, planos, _ = tela
    abrir(pg, "aluno")
    assert pg.locator("#comp-turma").count() == 0 and pg.locator("#comp-transferidos").count() == 0
    assert pg.locator("#comp-cgm").count() == 1 and "opcional" not in pg.inner_text("#campos-automacao")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "ao menos um CGM" in pg.inner_text("#toast-msg")
    assert pg.locator(".modal-card").count() == 0 and planos == []


def test_alunos_por_cgm_fluxo_completo(tela):
    pg, planos, _ = tela
    abrir(pg, "aluno")
    pg.fill("#comp-cgm", "3000000001\n3000000002")
    esperar_previa(pg, "2 de 2 CGM(s) encontrado(s)")
    pg.check("#campo-faltando")
    pg.check("#comp-erros")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector(".modal-card")
    assert "documentos da pasta de digitalização só destes alunos" in pg.inner_text(".modal-card")
    with pg.expect_request("**/automacoes/aluno/executar") as req:
        pg.click("#conf-sim")
    body = req.value.post_data_json
    assert body["cgms_texto"] == "3000000001\n3000000002" and body["faltando"] is True and body["erros"] is True
    assert aguardar(planos)[0][1].kwargs == {"modo_teste": False, "modo_erros": True, "modo_faltando": True,
                                             "cgms": ["3000000001", "3000000002"]}


# ───────────── campos próprios (extras), erros, debug ─────────────

def test_documentos_pede_o_tipo_e_valida_antes_de_confirmar(tela):
    pg, planos, _ = tela
    abrir(pg, "documentos", esperar="#campo-idtipo")
    assert pg.locator("#campo-idtipo option").count() > 5
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "tipo de documento" in pg.inner_text("#toast-msg") and planos == []         # antes: a tela nem pedia o tipo
    escolhido = pg.locator("#campo-idtipo option").nth(2).get_attribute("value")
    pg.select_option("#campo-idtipo", escolhido)
    esperar_previa(pg, "3 aluno(s)")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector(".modal-card")
    assert "REMOVE do SERE o tipo de documento" in pg.inner_text(".modal-card")


def test_erros_aparece_no_analisa_e_no_aluno_mas_nao_no_validar(tela):
    pg, _, _ = tela
    abrir(pg, "analisa_sere")
    assert pg.locator("#comp-erros").count() == 1
    assert "turma e situação são ignoradas" in pg.inner_text("#campos-automacao")
    assert executar_com(pg, "analisa_sere", lambda: pg.check("#comp-erros"))["erros"] is True


def executar_com(pg, chave, preparar):
    preparar()
    return executar(pg, chave)


def test_prematricula_tem_debug_e_pular_pendentes(tela):
    pg, planos, _ = tela
    abrir(pg, "prematricula_completa", esperar="#comp-debug")
    assert pg.locator("#comp-turma").count() == 0 and pg.locator("#comp-teste").count() == 0
    assert "captura de tela de cada etapa" in pg.inner_text("#campos-automacao")
    pg.check("#comp-debug")
    pg.check("#campo-pular")
    body = executar(pg, "prematricula_completa")
    assert body["debug"] is True and body["pular_pendentes"] is True
    assert aguardar(planos)[0][1].kwargs == {"analise": True, "pular_pendentes": True}


def test_rematricula_lista_as_turmas_proprias_do_script(tela):
    pg, planos, _ = tela
    abrir(pg, "rematricula", esperar="#comp-turma")
    opcoes = pg.locator("#comp-turma option").all_inner_texts()
    assert "INFANTIL 4" in opcoes and not any("Integral" in o for o in opcoes)       # nomes-base da rematrícula, não de turmas.json
    assert pg.locator("#comp-transferidos").count() == 0
    assert "1 aluno por turma" in pg.inner_text("#campos-automacao")
    pg.select_option("#comp-turma", "t:INFANTIL 4")
    esperar_previa(pg, "Turmas: INFANTIL 4.")


def test_transferidos_so_tem_teste(tela):
    pg, _, _ = tela
    abrir(pg, "transferidos", esperar="#comp-teste")
    assert pg.locator("#comp-turma").count() == 0 and pg.locator("#comp-cgm").count() == 0
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector(".modal-card")
    assert "Envia ao SERE" in pg.inner_text(".modal-card")      # aviso novo do fluxo de transferidos (antes citava transferidos.json)


def test_trocar_de_automacao_nao_mistura_componentes(tela):
    pg, _, _ = tela
    abrir(pg, "validar")
    assert pg.locator("#comp-turma").count() == 1
    pg.click("#btn-voltar-automacoes")
    abrir(pg, "aluno", esperar="#comp-cgm")
    assert pg.locator("#comp-turma").count() == 0 and pg.locator("#comp-cgm").count() == 1


# ───────────── automações migradas por último ─────────────

def test_todas_as_telas_de_automacao_abrem_sem_erro_de_javascript(tela):
    pg, _, _ = tela
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    chaves = pg.evaluate("fetch('/web/api/automacoes/lista').then(r => r.json()).then(d => d.itens.map(i => i.chave))")
    assert len(chaves) >= 20
    for chave in chaves:
        abrir(pg, chave, esperar="#campos-automacao")
        pg.wait_for_function("!document.getElementById('campos-automacao').textContent.includes('Carregando')")
        assert pg.inner_text("#campos-automacao").strip(), f"{chave}: tela vazia"
        pg.click("#btn-voltar-automacoes")
    assert erros == [], erros


def test_termos_pede_o_tema_e_grava_a_pasta_de_modelos(tela):
    pg, planos, _ = tela
    abrir(pg, "termos", esperar="#campo-tema")                                       # antes: a tela nem pedia o tema
    assert pg.get_attribute("#btn-escolher-pasta", "data-destino") == "modelos"
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "tema do termo" in pg.inner_text("#toast-msg") and planos == []
    pg.fill("#campo-tema", "Uso de imagem")
    body = executar(pg, "termos")
    assert body["tema"] == "Uso de imagem"
    assert aguardar(planos)[0][1].kwargs["tema"] == "Uso de imagem"


def test_cep_pede_o_raio_e_recusa_valor_invalido(tela):
    pg, planos, _ = tela
    abrir(pg, "cep", esperar="#campo-raio")
    pg.fill("#campo-raio", "abc")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "Raio inválido" in pg.inner_text("#toast-msg") and planos == []
    pg.fill("#campo-raio", "2,5")
    executar(pg, "cep")
    assert aguardar(planos)[0][1].kwargs == {"raio_km": 2.5}


def test_sus_agora_aceita_turma_e_situacao(tela):
    pg, planos, _ = tela
    abrir(pg, "sus")
    assert pg.locator("#comp-turma").count() == 1 and pg.locator("#comp-matriculados").count() == 1
    pg.select_option("#comp-turma", "g:3º Ano Integral")
    pg.check("#comp-transferidos")
    esperar_previa(pg, "3 aluno(s)")
    executar(pg, "sus")
    assert aguardar(planos)[0][1].kwargs == {"cgms": ["3000000001", "3000000002", "3000000003"]}


def test_telas_sem_parametros_dizem_isso(tela):
    pg, _, _ = tela
    for chave in ("turmas", "gerar_pastas", "cruzamento", "coleta_emails", "mascara"):
        abrir(pg, chave, esperar="#campos-automacao")
        pg.wait_for_function("document.getElementById('campos-automacao').textContent.includes('não precisa de parâmetros')")
        pg.click("#btn-voltar-automacoes")


def test_o_submenu_de_automacoes_mostra_todos_os_itens_sem_cortar(tela):
    """O CSS limitava a altura do submenu; com muitos itens o fim da lista ficava escondido."""
    pg, _, _ = tela
    pg.click("#toggle-automacoes")
    pg.wait_for_timeout(500)                                   # fim da animação de abrir
    r = pg.evaluate("""() => { const s = document.getElementById('sub-automacoes');
        return {conteudo: s.scrollHeight, visivel: s.clientHeight}; }""")
    assert r["visivel"] >= r["conteudo"], r


# ───────────── Comprimir documentos ─────────────

def test_comprimir_tem_turma_teste_e_os_tres_campos(tela):
    pg, _, _ = tela
    abrir(pg, "comprimir", esperar="#campo-limite")
    assert pg.locator("#comp-turma").count() == 1 and pg.locator("#comp-teste").count() == 1
    assert pg.locator("#comp-situacao-matriculados").count() == 0                       # compressão não escolhe situação
    assert pg.locator("#campo-calcular").count() == 1 and pg.locator("#campo-descartar").count() == 1
    texto = pg.inner_text("#campos-automacao")
    assert "Só calcular quanto vai economizar" in texto and "Não guardar cópia dos originais" in texto
    assert "substituído de verdade" in texto                                            # aviso do modo de teste


def test_comprimir_pede_confirmacao_e_envia_as_escolhas(tela):
    pg, planos, _ = tela
    abrir(pg, "comprimir", esperar="#campo-limite")
    pg.fill("#campo-limite", "2,5")
    pg.check("#campo-calcular")
    pg.check("#campo-descartar")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector(".modal-card")
    assert "SUBSTITUI os PDFs e imagens" in pg.inner_text(".modal-card")
    with pg.expect_request("**/automacoes/comprimir/executar") as req:
        pg.click("#conf-sim")
    corpo = req.value.post_data_json
    assert corpo["limite_mb"] == "2,5" and corpo["somente_calcular"] is True and corpo["descartar_originais"] is True
    assert aguardar(planos)[0][1].kwargs == {"turmas": [], "limite_mb": 2.5, "guardar_originais": False,
                                             "somente_calcular": True, "modo_teste": False}


def test_comprimir_limite_invalido_nao_abre_confirmacao(tela):
    pg, planos, _ = tela
    abrir(pg, "comprimir", esperar="#campo-limite")
    pg.fill("#campo-limite", "muito")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "Tamanho inválido" in pg.inner_text("#toast-msg") and pg.locator(".modal-card").count() == 0 and planos == []


# ───────────── Compara anos ─────────────

def _dois_anos(tmp_path, monkeypatch):
    from src.comum import paths
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path)
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2026")
    for ano in ("2024", "2025", "2026"):
        (tmp_path / ano).mkdir(exist_ok=True)
        (tmp_path / ano / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")


def test_compara_anos_lista_os_anos_existentes_e_envia_a_escolha(tela, monkeypatch):
    pg, planos, tmp_path = tela
    _dois_anos(tmp_path, monkeypatch)
    abrir(pg, "compara_anos", esperar="#campo-ano-base")
    assert pg.locator("#comp-turma").count() == 0 and pg.locator("#comp-teste").count() == 0    # só compara JSONs: sem turma/teste
    assert pg.eval_on_selector_all("#campo-ano-base option", "os => os.map(o => o.value)") == ["2024", "2025", "2026"]
    assert pg.input_value("#campo-ano-base") == "2025" and pg.input_value("#campo-ano-comparado") == "2026"   # padrão: anterior e atual
    pg.select_option("#campo-ano-base", "2024")
    corpo = executar(pg, "compara_anos")
    assert corpo["ano_base"] == "2024" and corpo["ano_comparado"] == "2026"
    assert aguardar(planos)[0][1].kwargs == {"ano_base": "2024", "ano_comparado": "2026"}


def test_compara_anos_com_anos_invertidos_mostra_o_motivo(tela, monkeypatch):
    pg, planos, tmp_path = tela
    _dois_anos(tmp_path, monkeypatch)
    abrir(pg, "compara_anos", esperar="#campo-ano-base")
    pg.select_option("#campo-ano-base", "2026")
    pg.select_option("#campo-ano-comparado", "2025")
    pg.click("#btn-executar-tarefa")
    pg.wait_for_selector("#toast.show")
    assert "anterior ao ano comparado" in pg.inner_text("#toast-msg") and planos == []

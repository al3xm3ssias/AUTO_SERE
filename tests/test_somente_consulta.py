"""Voltar a um ano letivo anterior = SOMENTE CONSULTA: selo no topo, faixa de aviso, tela de carregamento e trava de escrita."""
import json
import re
import threading
from pathlib import Path

import pytest

from src.comum import backup, configuracao, dados_ficticios as df, escola, paths
from src.web.api import rotas
from src.web.app import create_app, mensagem_somente_consulta

URL = "/web/api/configuracoes/ano-letivo"
ESCRITA = ("POST", "PUT", "PATCH", "DELETE")


def _montar(tmp_path, monkeypatch, ano_configurado):
    """Árvore temporária: calendário em 2026; `ano_configurado` é o ano em uso (já 'congelado', como após reiniciar)."""
    dados = tmp_path / "dados"
    (dados / "calendario").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "DADOS_DIR", dados)
    monkeypatch.setattr(paths, "DADOS_BACKUP_DIR", dados / "backup")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(escola, "nome", lambda: "Escola Municipal Profª Judith Macedo Silveira")
    monkeypatch.setattr(rotas, "_dados_dir", lambda: paths.dados_ano_atual())
    (tmp_path / "config" / "config_usuario.json").write_text(json.dumps({"ano_letivo": ano_configurado}), encoding="utf-8")
    df.gerar_dados_ficticios(2025)
    (dados / "2026").mkdir()
    (dados / "2026" / "alunos.json").write_text('[{"Nome": "REAL DE 2026"}]', encoding="utf-8")
    paths.recarregar_ano_do_processo()
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()


@pytest.fixture()
def consulta(tmp_path, monkeypatch):
    """Voltado a 2025 (o calendário está em 2026): somente consulta."""
    _montar(tmp_path, monkeypatch, "2025")
    assert paths.ano_atual() == "2025"
    yield tmp_path
    paths.recarregar_ano_do_processo()


@pytest.fixture()
def normal(tmp_path, monkeypatch):
    """Ano atual (2026): modo normal."""
    _montar(tmp_path, monkeypatch, None)
    assert paths.ano_atual() == "2026"
    yield tmp_path
    paths.recarregar_ano_do_processo()


@pytest.fixture()
def web(consulta):
    return create_app().test_client()


# ───────────── quando é "somente consulta" ─────────────

@pytest.mark.parametrize("configurado,calendario,esperado", [
    ("2025", 2026, True), ("2024", 2026, True), ("2026", 2026, False), (None, 2026, False), ("2027", 2026, False)])
def test_somente_consulta_depende_do_ano_em_uso(tmp_path, monkeypatch, configurado, calendario, esperado):
    _montar(tmp_path, monkeypatch, configurado)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: calendario)
    assert paths.somente_consulta() is esperado
    paths.recarregar_ano_do_processo()


def test_ambiente_fixando_o_ano_nao_e_consulta(consulta, monkeypatch):
    """Quem fixa o ano pela variável (ex.: janeiro, com o ano anterior ainda aberto no SERE) precisa poder trabalhar."""
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2025")
    assert paths.ano_atual() == "2025" and paths.somente_consulta() is False
    r = create_app().test_client().post("/web/api/configuracoes/gmail", json={})
    assert not _barrada(r)                                                    # a rota respondeu por conta própria


def test_ano_ilegivel_nao_trava(consulta, monkeypatch):
    monkeypatch.setattr(paths, "ano_atual", lambda: "abc")
    assert paths.somente_consulta() is False


# ───────────── o guarda: nenhuma escrita passa ─────────────

def _barrada(resposta, ano="2025") -> bool:
    """A requisição foi recusada PELO GUARDA (e não por outro motivo qualquer da rota)."""
    corpo = resposta.get_json(silent=True) or {}
    return resposta.status_code == 403 and corpo.get("somente_consulta") is True and corpo.get("erro") == mensagem_somente_consulta(ano)


def _caminho(rule: str) -> str:
    return re.sub(r"<[^>]+>", "x", re.sub(r"<int:[^>]+>", "1", rule))


def _rotas_de_escrita(app):
    achadas = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/web/api/"):
            continue
        for metodo in sorted(set(rule.methods) & set(ESCRITA)):
            achadas.append((metodo, _caminho(rule.rule), rule.rule))
    return achadas


PERMITIDAS = [
    re.compile(r"^/web/api/configuracoes/ano-letivo$"),
    re.compile(r"^/web/api/configuracoes/ano-letivo/(backup|restaurar)$"),      # restaurar: só com aplicar=false
    re.compile(r"^/web/api/automacoes/[^/]+/(previa|cancelar)$"),
    re.compile(r"^/web/api/whatsapp/webhook$"),
    re.compile(r"^/web/api/planilhas(/[^/]+)?$"),      # cadastro de planilhas do Drive: atravessa os anos, não é dado de um ano
    re.compile(r"^/web/api/google/autorizacao/(abrir|colar)$"),      # login do Google em andamento: não grava dado do ano
]


def test_toda_rota_que_escreve_e_barrada_em_consulta(web):
    """Percorre TODAS as rotas de escrita do aplicativo (inclusive as que alguém criar depois) com o corpo vazio."""
    barradas, liberadas = [], []
    for metodo, caminho, regra in _rotas_de_escrita(web.application):
        r = web.open(caminho, method=metodo, json={})
        corpo = r.get_json(silent=True) or {}
        permitida = any(p.match(caminho) for p in PERMITIDAS)
        if permitida:
            assert not _barrada(r), f"{metodo} {regra} devia estar liberada em consulta"
            liberadas.append(regra)
        else:
            assert _barrada(r), f"{metodo} {regra} escreve e NÃO foi barrada"
            assert corpo["ano"] == "2025" and corpo["erro"] == corpo["mensagem"]
            barradas.append(regra)
    assert len(barradas) >= 25 and len(liberadas) >= 4                          # garante que o teste realmente percorreu as rotas
    assert any("calendario" in b for b in barradas) and any("whatsapp" in b for b in barradas) and any("wizard" in b for b in barradas)


def test_a_mensagem_manda_voltar_ao_ano_atual(web):
    r = web.post("/web/api/automacoes/turmas/executar", json={})
    assert r.status_code == 403
    assert r.get_json()["erro"] == mensagem_somente_consulta("2025")
    assert "Configurações → Ano letivo" in r.get_json()["erro"]


def test_o_guarda_nao_deixa_nenhum_arquivo_mudar(consulta, web):
    pasta = consulta / "dados" / "2025"
    antes = {p.name: p.read_bytes() for p in pasta.iterdir()}
    cred = consulta / "credenciais"
    for caminho, corpo in [("/web/api/automacoes/turmas/executar", {}), ("/web/api/configuracoes/gmail", {"email": "a@b.com", "senha": "abcd abcd abcd abcd"}),
                           ("/web/api/configuracoes/prematricula", {"login": "1", "senha": "2"}),
                           ("/web/api/configuracoes/modelos-parecer", {}), ("/web/api/escola", {"nome": "X"})]:
        assert web.post(caminho, json=corpo).status_code in (403, 404, 405)
    assert {p.name: p.read_bytes() for p in pasta.iterdir()} == antes
    assert not cred.exists() or not (cred / ".env").exists()


def test_o_que_continua_liberado(web, consulta):
    # backup só copia
    assert web.post(URL + "/backup", json={"ano": "2025"}).status_code == 200
    nome = web.get(URL).get_json()["backups"][0]["nome"]
    # conferir um backup (aplicar=false) é leitura
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": False})
    assert r.status_code == 200 and r.get_json()["resultado"]["aplicado"] is False
    # prévia e cancelar não são barradas (respondem como sempre: aqui, 'não encontrado')
    for rota in ("previa", "cancelar"):
        assert not _barrada(web.post(f"/web/api/automacoes/turmas/{rota}", json={}))
    # trocar de ano é o caminho de volta — e vale na hora, saindo do modo consulta
    assert paths.somente_consulta() is True
    r = web.post(URL, json={"ano": "2026"})
    assert r.status_code == 200 and r.get_json()["configurado"] == "2026" and r.get_json()["ativo"] == "2026"
    assert paths.somente_consulta() is False


def test_restaurar_de_verdade_e_dados_ficticios_ficam_barrados(web, consulta):
    web.post(URL + "/backup", json={"ano": "2025"})
    nome = web.get(URL).get_json()["backups"][0]["nome"]
    antes = (consulta / "dados" / "2025" / "alunos.json").read_bytes()
    (consulta / "dados" / "2025" / "alunos.json").write_text("[]", encoding="utf-8")
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 403 and r.get_json()["somente_consulta"] is True
    assert (consulta / "dados" / "2025" / "alunos.json").read_text(encoding="utf-8") == "[]"        # nada foi restaurado
    assert web.post(URL + "/dados-ficticios", json={"ano": "2024"}).status_code == 403
    assert not (consulta / "dados" / "2024").exists()
    (consulta / "dados" / "2025" / "alunos.json").write_bytes(antes)


def test_ver_continua_funcionando_e_mostra_os_dados_do_ano(web):
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 57
    assert web.get("/web/api/painel/resumo").status_code == 200
    func = web.get("/web/api/funcionarios/lista").get_json()
    assert len(func["funcionarios"]) == 14
    assert web.get(URL).get_json()["somente_consulta"] is True


def test_em_modo_normal_o_guarda_nao_atrapalha(normal):
    c = create_app().test_client()
    assert not _barrada(c.post("/web/api/automacoes/turmas/previa", json={}), "2026")
    r = c.post("/web/api/configuracoes/prematricula", json={"login": "", "senha": ""})
    assert r.status_code == 400 and not _barrada(r, "2026")                       # a rota respondeu por conta própria


# ───────────── contexto e página ─────────────

def test_contexto_do_ano(web, consulta):
    d = web.get("/web/api/ano-letivo/contexto").get_json()
    assert d == {"ativo": "2025", "proximo": "2025", "pendente_reinicio": False, "somente_consulta": True,
                 "ano_do_calendario": "2026", "fixado_por_ambiente": False}
    (consulta / "config" / "config_usuario.json").write_text(json.dumps({"ano_letivo": "2026"}), encoding="utf-8")   # editado à mão
    d = web.get("/web/api/ano-letivo/contexto").get_json()
    assert d["ativo"] == "2025" and d["proximo"] == "2026" and d["pendente_reinicio"] is True and d["somente_consulta"] is True
    web.post(URL, json={"ano": "2026"})                                           # "Aplicar agora": a troca é imediata
    d = web.get("/web/api/ano-letivo/contexto").get_json()
    assert d["ativo"] == "2026" and d["proximo"] == "2026" and d["pendente_reinicio"] is False and d["somente_consulta"] is False


def test_contexto_em_modo_normal(normal):
    d = create_app().test_client().get("/web/api/ano-letivo/contexto").get_json()
    assert d["ativo"] == "2026" and d["somente_consulta"] is False and d["pendente_reinicio"] is False


def test_pagina_traz_o_selo_com_o_ano_em_consulta(web):
    html = web.get("/web").get_data(as_text=True)
    assert '<body class="modo-consulta" data-ano-letivo="2025">' in html
    assert 'class="ano-badge consulta" id="ano-badge"' in html
    assert "Ano letivo 2025 · somente consulta" in html
    assert 'id="sidebar-ano">2025<' in html                                       # a lateral mostra o ano em uso, não o do calendário
    assert 'id="ano-overlay"' in html and 'id="ano-banner"' in html


def test_pagina_em_modo_normal(normal):
    html = create_app().test_client().get("/web").get_data(as_text=True)
    assert '<body class="" data-ano-letivo="2026">' in html
    assert 'class="ano-badge" id="ano-badge"' in html and "Ano letivo 2026<" in html and "somente consulta" not in html.split('id="ano-badge-texto"')[1][:60]


def test_estado_do_painel_ano_letivo_informa_a_consulta(web):
    assert web.get(URL).get_json()["somente_consulta"] is True


# ───────────── linha de comando ─────────────

def test_cli_recusa_executar_em_consulta_mas_simula(consulta, capsys):
    from src.comum import cli
    assert cli.main(["turmas", "--simular"]) == 0                                 # simular só mostra
    capsys.readouterr()
    assert cli.main(["turmas"]) == 2
    err = capsys.readouterr().err
    assert "Somente consulta" in err and "2025" in err


# ───────────── estáticos ─────────────

def test_arquivos_da_tela_tem_o_necessario():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    css = (raiz / "src/web/static/css/styles.css").read_text(encoding="utf-8")
    for trecho in ("function mostrarTelaAno", "function aplicarContextoAno", "async function iniciarContextoAno", "/ano-letivo/contexto",
                   "ano-consulta-visto-", "restaurado", "emConsulta()", "avisarMudancaDeAno", "iniciarContextoAno();",
                   "async function trocarAnoLetivo", "ano-banner-aplicar"):
        assert trecho in js, trecho
    for seletor in (".ano-badge.consulta", ".ano-banner", ".ano-overlay", ".ano-spinner"):
        assert seletor in css, seletor


# ───────────── no navegador de verdade ─────────────

playwright_sync = pytest.importorskip("playwright.sync_api")


def _servir(app):
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def navegador():
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:                                                  # noqa: BLE001
            pytest.skip(f"Chromium indisponível: {exc}")
        yield nav
        nav.close()


def test_navegador_em_consulta_mostra_selo_faixa_e_tela_de_carregamento(consulta, navegador):
    srv = _servir(create_app())
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        # selo perto do perfil, com o ano
        pg.wait_for_selector("#ano-badge.consulta")
        assert pg.inner_text("#ano-badge-texto") == "Ano letivo 2025 · somente consulta"
        selo, perfil = pg.locator("#ano-badge").bounding_box(), pg.locator(".topbar-user").bounding_box()
        assert selo["x"] < perfil["x"] and abs(selo["y"] - perfil["y"]) < 40         # na mesma barra, à esquerda do perfil
        # tela de carregamento: aparece avisando que o ano foi restaurado e some sozinha
        pg.wait_for_selector("#ano-overlay.visivel", timeout=4000)
        assert pg.inner_text("#ano-overlay-titulo") == "Ano letivo 2025 restaurado"
        assert "somente consulta" in pg.inner_text("#ano-overlay-texto")
        pg.wait_for_selector("#ano-overlay", state="hidden", timeout=6000)
        # faixa de aviso com o botão de voltar
        assert pg.is_visible("#ano-banner") and "Somente consulta" in pg.inner_text("#ano-banner")
        assert "2025" in pg.inner_text("#ano-banner")
        # só uma vez por sessão: recarregando, a tela de carregamento não volta
        pg.reload()
        pg.wait_for_selector("#ano-badge.consulta")
        pg.wait_for_timeout(600)
        assert not pg.is_visible("#ano-overlay")
        # os dados do 2025 aparecem na tela
        pg.click('.nav-item[data-view="alunos"]')
        pg.wait_for_function("document.querySelectorAll('#alunos-tbody tr').length > 5", timeout=8000)
        # o botão de executar automação fica bloqueado
        pg.click("#toggle-automacoes")
        pg.click('#sub-automacoes .nav-subitem[data-auto="turmas"]')
        pg.wait_for_selector("#automacoes-execucao", state="visible")
        assert pg.is_disabled("#btn-executar-tarefa")
        assert "Somente consulta" in pg.get_attribute("#btn-executar-tarefa", "title")
        # "Voltar ao ano atual…" leva às configurações do ano
        pg.click("#ano-banner-voltar")
        pg.wait_for_selector("#cfg-ano-status", timeout=5000)
        assert "Em uso agora: 2025" in pg.inner_text("#cfg-ano-status")
        assert pg.is_disabled("#cfg-ano-restaurar") and pg.is_disabled("#cfg-ano-gerar")
        assert "Somente consulta" in pg.inner_text("#cfg-ano-aviso")
        # e o botão "Usar este ano" de 2026 continua ativo (é o caminho de volta)
        assert pg.is_enabled('#cfg-ano-anos button[data-acao="usar"][data-ano="2026"]')
    finally:
        srv.shutdown()


def test_navegador_em_modo_normal_nao_tem_faixa_nem_tela(normal, navegador):
    srv = _servir(create_app())
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        pg.wait_for_selector("#ano-badge")
        pg.wait_for_function("document.getElementById('ano-badge-texto').textContent.trim() === 'Ano letivo 2026'")
        assert not pg.eval_on_selector("#ano-badge", "e => e.classList.contains('consulta')")
        pg.wait_for_timeout(800)
        assert not pg.is_visible("#ano-banner") and not pg.is_visible("#ano-overlay")
        assert not pg.eval_on_selector("body", "b => b.classList.contains('modo-consulta')")
        pg.click("#toggle-automacoes")
        pg.click('#sub-automacoes .nav-subitem[data-auto="turmas"]')
        pg.wait_for_selector("#automacoes-execucao", state="visible")
        assert pg.is_enabled("#btn-executar-tarefa")
    finally:
        srv.shutdown()


def _texto_meta(pg):
    return pg.inner_text("#t-meta")


def test_navegador_trocar_para_2025_e_imediato_e_vira_consulta(normal, navegador):
    """Sem reiniciar: tela de carregamento, a página recarrega e já mostra os dados de 2025 em modo consulta."""
    srv = _servir(create_app())
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        pg.wait_for_function("document.getElementById('ano-badge-texto').textContent.trim() === 'Ano letivo 2026'")
        pg.click('.nav-item[data-view="configuracoes"]')
        pg.click('.config-row[data-config="ano_letivo"]')
        pg.wait_for_selector('#cfg-ano-anos button[data-acao="usar"][data-ano="2025"]')
        pg.click('#cfg-ano-anos button[data-acao="usar"][data-ano="2025"]')
        # 1) enquanto o servidor troca: tela de carregamento, sem botão
        pg.wait_for_selector("#ano-overlay.visivel", timeout=5000)
        # 2) depois: "restaurado" + recarga
        pg.wait_for_function("document.getElementById('ano-overlay-titulo').textContent.includes('2025')", timeout=5000)
        # 3) a página recarrega e já está em 2025, em consulta, sem repetir a tela de carregamento
        pg.wait_for_function("document.body.classList.contains('modo-consulta')", timeout=10000)
        pg.wait_for_function("document.getElementById('ano-badge-texto').textContent.includes('2025 · somente consulta')", timeout=5000)
        pg.wait_for_function("document.getElementById('t-meta').textContent.includes('54 alunos')", timeout=8000)
        pg.wait_for_timeout(500)
        assert not pg.is_visible("#ano-overlay")
        assert pg.is_visible("#ano-banner") and "Somente consulta" in pg.inner_text("#ano-banner")
        assert "reinici" not in pg.inner_text("#ano-banner").lower()
    finally:
        srv.shutdown()


def test_navegador_voltar_ao_ano_atual_sem_reiniciar(consulta, navegador):
    """Do modo consulta (2025) volta a 2026 pelo botão da faixa → painel de ano → 'Usar este ano': tudo se recarrega."""
    srv = _servir(create_app())
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        pg.wait_for_function("document.getElementById('t-meta').textContent.includes('54 alunos')", timeout=8000)
        pg.wait_for_selector("#ano-overlay", state="hidden", timeout=6000)
        pg.click("#ano-banner-voltar")
        pg.wait_for_selector('#cfg-ano-anos button[data-acao="usar"][data-ano="2026"]')
        pg.click('#cfg-ano-anos button[data-acao="usar"][data-ano="2026"]')
        pg.wait_for_function("!document.body.classList.contains('modo-consulta') && document.getElementById('ano-badge-texto').textContent.trim() === 'Ano letivo 2026'", timeout=12000)
        pg.wait_for_function("document.getElementById('t-meta').textContent.includes('0 alunos')", timeout=8000)
        assert not pg.is_visible("#ano-banner") and not pg.eval_on_selector("#ano-badge", "e => e.classList.contains('consulta')")
        assert paths.ano_atual() == "2026"                                             # o servidor também está em 2026
        # e agora os botões de escrita voltam a funcionar: executar automação habilitado
        pg.click("#toggle-automacoes")
        pg.click('#sub-automacoes .nav-subitem[data-auto="turmas"]')
        pg.wait_for_selector("#automacoes-execucao", state="visible")
        assert pg.is_enabled("#btn-executar-tarefa")
    finally:
        srv.shutdown()


def test_navegador_troca_recusada_com_automacao_rodando_mostra_o_motivo(normal, navegador):
    srv = _servir(create_app())
    try:
        with rotas._EXECUCOES_LOCK:
            rotas._EXECUCOES["turmas"] = {"status": "executando"}
        pg = navegador.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        pg.click('.nav-item[data-view="configuracoes"]')
        pg.click('.config-row[data-config="ano_letivo"]')
        pg.wait_for_selector('#cfg-ano-anos button[data-acao="usar"][data-ano="2025"]')
        pg.click('#cfg-ano-anos button[data-acao="usar"][data-ano="2025"]')
        pg.wait_for_selector("#toast.show, #toast.visible, #toast[class*=show]", timeout=5000)
        pg.wait_for_selector("#ano-overlay", state="hidden", timeout=5000)               # a tela de carregamento não fica presa
        assert "automação em execução" in pg.inner_text("#toast")
        assert paths.ano_atual() == "2026"
    finally:
        srv.shutdown()


def test_rotas_da_autorizacao_do_google_em_consulta(web):
    """Abrir/colar o link do Google mexem só na tentativa em andamento (liberadas); salvar a conta e testar escrevem config (barradas)."""
    for caminho in ("/web/api/google/autorizacao/abrir", "/web/api/google/autorizacao/colar"):
        assert not _barrada(web.post(caminho, json={})), caminho
    for caminho in ("/web/api/configuracoes/google-conta", "/web/api/configuracoes/google-conta/testar"):
        assert _barrada(web.post(caminho, json={})), caminho
    assert web.get("/web/api/google/autorizacao").status_code == 200          # leitura sempre liberada

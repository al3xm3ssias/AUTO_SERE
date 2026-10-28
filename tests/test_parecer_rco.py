"""parecer_rco: portado de gerar_pareceres_infantil.py — preparação, login com 2FA, laço de alunos e rotas."""
import asyncio
import json
import time
from pathlib import Path

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.automacao import parecer_rco as pr
from src.comum import credenciais, entrada_usuario as eu, paths
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app


def _al(cgm, nome, n, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "N": n, "Situação": sit}


TURMAS = {
    "Infantil IV A": [_al("101", "Ana Lima", 1), _al("102", "Beto Souza", 2, "Transferido"), _al("", "Sem CGM", 3)],
    "INFANTIL 5 B": [_al("201", "Caio/Dias", 1)],
    "Infantil III": [_al("301", "Nao Entra", 1)],
    "Infantil VI": [_al("302", "Tambem Nao", 1)],
    "3º Ano A": [_al("401", "Fundamental", 1)],
}


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path / "dados" / "2026")
    (tmp_path / "dados" / "2026").mkdir(parents=True)
    (tmp_path / "dados" / "2026" / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    monkeypatch.setattr(credenciais, "LOGIN_RCO", "12345678900")
    monkeypatch.setattr(credenciais, "SENHA_RCO", "senha-rco")
    monkeypatch.delenv("AUTO_SERE_PARECERES_INFANTIL_DIR", raising=False)
    eu.usar_terminal(False)
    eu._PENDENTES.clear()
    return tmp_path


# ───────────── preparação ─────────────

@pytest.mark.parametrize("entrada,esperado", [("2", "2º Bimestre"), ("4", "4º Bimestre"), (" 4 ", "4º Bimestre"),
                                              ("2º", "2º Bimestre"), ("4º Bimestre", "4º Bimestre")])
def test_rotulo_bimestre(entrada, esperado):
    assert pr.rotulo_bimestre(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", None, "1", "3", "24", "dois", "5º"])
def test_rotulo_bimestre_invalido(entrada):
    with pytest.raises(ValueError, match="2º ou 4º"):
        pr.rotulo_bimestre(entrada)


def test_periodo_letivo(amb):
    assert pr.periodo_letivo_atual() == "261"


def test_pasta_destino_padrao_e_com_override(amb, monkeypatch):
    assert pr.pasta_destino("2026", "2º Bimestre") == amb / "dados" / "2026" / "PARECERES INFANTIL" / "2º Bimestre"
    monkeypatch.setenv("AUTO_SERE_PARECERES_INFANTIL_DIR", str(amb / "rede"))
    assert pr.pasta_destino("2026", "4º Bimestre") == amb / "rede" / "4º Bimestre"


def test_alunos_alvo_so_infantil_iv_v_matriculados_com_cgm(amb):
    alunos = pr.carregar_alunos_alvo(TURMAS)
    assert [(a["cgm"], a["turma"], a["n_chamada"]) for a in alunos] == [("101", "Infantil IV A", 1), ("201", "INFANTIL 5 B", 1)]


def test_alunos_alvo_aceita_chaves_de_situacao_alternativas():
    t = {"Infantil V": [{"CGM": "1", "Nome": "A", "N": 1, "Situacao": "matriculado"}]}
    assert len(pr.carregar_alunos_alvo(t)) == 1


def test_caminho_do_parecer(tmp_path):
    base = tmp_path / "2º Bimestre"
    assert pr.caminho_do_parecer(base, "Infantil IV A", "Ana Lima", "101", 7) == base / "Infantil_IV_A" / "7 - Ana_Lima.pdf"
    assert pr.caminho_do_parecer(base, "Infantil V", "Caio/Dias", "201", None).name == "201 - Caio_Dias.pdf"
    assert pr.caminho_do_parecer(base, "Infantil V", "", "201", "").name == "201 - 201.pdf"


def test_credenciais_rco(amb, monkeypatch):
    assert pr.credenciais_rco() == ("12345678900", "senha-rco")
    monkeypatch.setattr(credenciais, "LOGIN_RCO", "cpf")
    with pytest.raises(ValueError, match="Credenciais do RCO não configuradas"):
        pr.credenciais_rco()
    monkeypatch.setattr(credenciais, "LOGIN_RCO", "123")
    monkeypatch.setattr(credenciais, "SENHA_RCO", "senha_sere")
    with pytest.raises(ValueError, match="Credenciais do RCO"):
        pr.credenciais_rco()


def test_carregar_turmas_sem_arquivo(amb):
    (amb / "dados" / "2026" / "turmas.json").unlink()
    with pytest.raises(ValueError, match="execute primeiro a automação 'Turmas'"):
        pr.carregar_turmas()


def test_validar_pedido(amb):
    pr.validar_pedido("2")
    with pytest.raises(ValueError, match="2º ou 4º"):
        pr.validar_pedido("")
    (amb / "dados" / "2026" / "turmas.json").write_text(json.dumps({"3º Ano A": [_al("1", "A", 1)]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Nenhum aluno Matriculado"):
        pr.validar_pedido("4")


def test_codigo_aceita_espacos_e_recusa_lixo():
    pr._validar_codigo("123 456")
    pr._validar_codigo("AbC123")
    for ruim in ["12", "12-34-56", "123456789012345", "é23456"]:
        with pytest.raises(ValueError, match="4 a 12"):
            pr._validar_codigo(ruim)


# ───────────── login com 2FA (navegador falso) ─────────────

class _Locator:
    def __init__(self, pagina, seletor):
        self.p, self.s = pagina, seletor

    async def wait_for(self, **_):
        if self.s in self.p.ausentes:
            raise PlaywrightTimeout("sem campo")

    async def fill(self, valor):
        self.p.preenchidos[self.s] = valor


class _Contexto:
    async def cookies(self):
        return [{"name": "JSESSIONID", "domain": "rcomunicipios.pr.gov.br", "value": "SEGREDO-DA-SESSAO"}]


class _Pagina:
    """Só o suficiente do Playwright para o fluxo do login."""

    def __init__(self, url_final="https://www.rcomunicipios.pr.gov.br/rcdig/entrada.do", ausentes=()):
        self.url = "https://auth-cs.identidadedigital.pr.gov.br/centralautenticacao/login.html?code=XYZ"
        self.url_final, self.ausentes = url_final, set(ausentes)
        self.preenchidos, self.cliques, self.listeners = {}, [], {}
        self.context = _Contexto()

    def on(self, evento, fn): self.listeners[evento] = fn
    def remove_listener(self, evento, fn): self.listeners.pop(evento, None)
    async def goto(self, url, **_): pass
    async def click(self, seletor, **_):
        self.cliques.append(seletor)
        if seletor == "#confirmarTokenEmail":
            self.url = self.url_final
    async def fill(self, seletor, valor): self.preenchidos[seletor] = valor
    async def wait_for_selector(self, seletor, **_):
        if seletor in self.ausentes:
            raise PlaywrightTimeout("não apareceu")
    def locator(self, seletor): return _Locator(self, seletor)
    async def wait_for_url(self, *_a, **_k): pass
    async def wait_for_load_state(self, *_a, **_k): pass
    async def screenshot(self, **_): pass
    async def content(self): return "<html>login</html>"


def _responder_quando_perguntar(codigo):
    async def tarefa():
        for _ in range(400):
            p = eu.pergunta_pendente(pr.CHAVE)
            if p:
                return p, eu.responder(pr.CHAVE, p["id"], codigo)
            await asyncio.sleep(0.01)
    return tarefa()


def test_login_pede_o_codigo_ao_usuario_e_usa_a_resposta(amb):
    pagina = _Pagina()

    async def cenario():
        resp = asyncio.create_task(_responder_quando_perguntar("123 456"))
        await pr.fazer_login(pagina, "12345678900", "senha-rco")
        return await resp
    pergunta, (ok, _) = asyncio.run(cenario())
    assert ok and "Código de verificação" in pergunta["titulo"] and pergunta["segredo"] is False
    assert pagina.preenchidos["#attribute_central"] == "12345678900" and pagina.preenchidos["#password"] == "senha-rco"
    assert pagina.preenchidos["#codigoSegurancaEmail"] == "123456"       # espaços removidos
    assert "#btnEnviarEmailToken2FA" in pagina.cliques and "#confirmarTokenEmail" in pagina.cliques
    assert not pagina.listeners                                          # ouvinte de rede removido
    assert not (amb / "dados" / "2026" / "debug_rco").exists()           # sem falha, sem arquivos de diagnóstico


def test_login_codigo_ruim_e_recusado_na_pergunta(amb):
    pagina = _Pagina()

    async def cenario():
        async def usuario():
            for _ in range(400):
                p = eu.pergunta_pendente(pr.CHAVE)
                if p:
                    ruim = eu.responder(pr.CHAVE, p["id"], "12")
                    bom = eu.responder(pr.CHAVE, p["id"], "654321")
                    return ruim, bom
                await asyncio.sleep(0.01)
        resp = asyncio.create_task(usuario())
        await pr.fazer_login(pagina, "l", "s")
        return await resp
    ruim, bom = asyncio.run(cenario())
    assert ruim[0] is False and "4 a 12" in ruim[1] and bom[0] is True
    assert pagina.preenchidos["#codigoSegurancaEmail"] == "654321"


def test_login_sem_tela_2fa_da_erro_claro_e_guarda_diagnostico(amb):
    pagina = _Pagina(ausentes={"#btnEnviarEmailToken2FA"})
    with pytest.raises(RuntimeError, match="login e a senha do RCO estão corretos"):
        asyncio.run(pr.fazer_login(pagina, "l", "s"))
    pasta = amb / "dados" / "2026" / "debug_rco"
    assert (pasta / "sem_tela_2fa.html").exists() and (pasta / "network_log.txt").exists()
    nomes = (pasta / "cookies_nomes.json").read_text(encoding="utf-8")
    assert "JSESSIONID" in nomes and "SEGREDO-DA-SESSAO" not in nomes   # só nome e domínio, nunca o valor


def test_login_que_volta_para_a_tela_de_login_falha(amb):
    pagina = _Pagina(url_final="https://auth-cs.identidadedigital.pr.gov.br/centralautenticacao/login.html?force_login=true")

    async def cenario():
        resp = asyncio.create_task(_responder_quando_perguntar("111111"))
        try:
            await pr.fazer_login(pagina, "l", "s")
        finally:
            await resp
    with pytest.raises(RuntimeError, match="voltou para a tela de login"):
        asyncio.run(cenario())
    assert (amb / "dados" / "2026" / "debug_rco" / "voltou_login.html").exists()


def test_log_de_rede_nao_guarda_a_query():
    assert pr._sem_query("https://x/rcdig?code=ABC&state=1") == "https://x/rcdig"


def test_login_sem_resposta_do_usuario_termina_com_erro(amb, monkeypatch):
    async def ninguem_respondeu(chave, titulo, mensagem="", rotulo="", **kw):
        raise eu.PedidoExpirou("Ninguém respondeu")
    monkeypatch.setattr(eu, "perguntar", ninguem_respondeu)
    with pytest.raises(eu.PedidoExpirou):
        asyncio.run(pr.fazer_login(_Pagina(), "l", "s"))


# ───────────── laço de alunos (tudo o que toca o site é trocado por falsos) ─────────────

class _Browser:
    fechado = False
    async def new_context(self, **_):
        class C:
            async def add_init_script(self, *_): pass
            async def new_page(self): return object()
        return C()
    async def close(self): _Browser.fechado = True


class _Playwright:
    lancado = {}
    async def __aenter__(self):
        class P:
            class chromium:
                @staticmethod
                async def launch(**kw):
                    _Playwright.lancado = kw
                    return _Browser()
        return P()
    async def __aexit__(self, *a): return False


@pytest.fixture()
def site_falso(amb, monkeypatch):
    chamadas = {"login": 0, "solicitar": [], "baixar": []}
    _Browser.fechado = False
    monkeypatch.setattr(pr, "async_playwright", lambda: _Playwright())

    async def login(page, l, s, chave=pr.CHAVE): chamadas["login"] += 1
    async def periodo(page, v): pass
    async def navegar(page, v): pass
    async def solicitar(page, cgm, nome):
        chamadas["solicitar"].append(cgm)
        return cgm != "201"                                   # o 201 não tem parecer
    async def baixar(page, cgm, nome, n, turma, destino_base):
        chamadas["baixar"].append(cgm)
        return None if cgm == "999" else destino_base / f"{cgm}.pdf"
    monkeypatch.setattr(pr, "fazer_login", login)
    monkeypatch.setattr(pr, "selecionar_periodo", periodo)
    monkeypatch.setattr(pr, "navegar_para_consultar_aluno", navegar)
    monkeypatch.setattr(pr, "solicitar_parecer", solicitar)
    monkeypatch.setattr(pr, "aguardar_e_baixar_parecer", baixar)
    return chamadas


def test_gera_pareceres_e_resume(site_falso, amb):
    r = asyncio.run(pr.gerar_pareceres_infantil_via_login("2"))
    assert r["total"] == 2 and r["baixados"] == 1
    assert r["falhas"] == [{"cgm": "201", "nome": "Caio/Dias", "motivo": "sem parecer no RCO"}]
    assert r["pasta"].endswith("2º Bimestre") and Path(r["pasta"]).is_dir()
    assert site_falso["login"] == 1 and site_falso["baixar"] == ["101"]
    assert _Browser.fechado and _Playwright.lancado["headless"] is True


def test_modo_teste_processa_so_o_primeiro_e_mostrar_navegador(site_falso):
    r = asyncio.run(pr.gerar_pareceres_infantil_via_login("4", modo_teste=True, mostrar_navegador=True))
    assert r["total"] == 1 and site_falso["solicitar"] == ["101"] and r["pasta"].endswith("4º Bimestre")
    assert _Playwright.lancado["headless"] is False


def test_erro_em_um_aluno_nao_para_os_demais(site_falso, monkeypatch):
    async def solicitar(page, cgm, nome):
        site_falso["solicitar"].append(cgm)
        if cgm == "101":
            raise RuntimeError("tela mudou")
        return True
    monkeypatch.setattr(pr, "solicitar_parecer", solicitar)
    r = asyncio.run(pr.gerar_pareceres_infantil_via_login("2"))
    assert site_falso["solicitar"] == ["101", "201"] and r["baixados"] == 1
    assert r["falhas"][0]["cgm"] == "101" and "tela mudou" in r["falhas"][0]["motivo"]


def test_arquivo_que_nao_aparece_vira_falha(site_falso, monkeypatch):
    async def baixar(page, *a, **k): return None
    monkeypatch.setattr(pr, "aguardar_e_baixar_parecer", baixar)
    r = asyncio.run(pr.gerar_pareceres_infantil_via_login("2"))
    assert r["baixados"] == 0 and {f["motivo"] for f in r["falhas"]} == {"o arquivo não apareceu na fila", "sem parecer no RCO"}


def test_falha_do_login_fecha_o_navegador(site_falso, monkeypatch):
    async def login(page, l, s, chave=pr.CHAVE): raise RuntimeError("senha errada")
    monkeypatch.setattr(pr, "fazer_login", login)
    with pytest.raises(RuntimeError, match="senha errada"):
        asyncio.run(pr.gerar_pareceres_infantil_via_login("2"))
    assert _Browser.fechado


def test_pedidos_invalidos_nem_abrem_o_navegador(site_falso, monkeypatch):
    with pytest.raises(ValueError, match="2º ou 4º"):
        asyncio.run(pr.gerar_pareceres_infantil_via_login("3"))
    monkeypatch.setattr(credenciais, "LOGIN_RCO", "cpf")
    with pytest.raises(ValueError, match="Credenciais do RCO"):
        asyncio.run(pr.gerar_pareceres_infantil_via_login("2"))
    assert site_falso["login"] == 0 and not _Browser.fechado


def test_cancelamento_interrompe_o_laco(site_falso, monkeypatch):
    from src.comum.execucao_gui import CancelamentoSolicitado
    chamadas = []
    def cancelar():
        chamadas.append(1)
        if len(chamadas) == 2:
            raise CancelamentoSolicitado()
    monkeypatch.setattr(pr, "verificar_cancelamento", cancelar)
    with pytest.raises(CancelamentoSolicitado):
        asyncio.run(pr.gerar_pareceres_infantil_via_login("2"))
    assert site_falso["solicitar"] == ["101"] and _Browser.fechado


# ───────────── registro, rotas e tela ─────────────

@pytest.fixture()
def web(amb, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: amb / "dados" / "2026")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


def test_registrada_e_fora_da_lista_de_nao_implementadas():
    assert reg.obter("parecer_rco") is not None
    assert "parecer_rco" not in rotas.AUTOMACOES_NAO_IMPLEMENTADAS
    assert any(i["chave"] == "parecer_rco" for i in rotas.AUTOMACOES_DISPONIVEIS)


def test_extras_da_tela(amb):
    extras = reg.obter("parecer_rco").extras()
    sel = next(e for e in extras if e["tipo"] == "select")
    assert sel["nome"] == "bimestre" and [o["valor"] for o in sel["opcoes"]] == ["2", "4"]
    assert any(e["tipo"] == "caixa" and e["nome"] == "mostrar_navegador" for e in extras)
    assert reg.obter("parecer_rco").recursos == ("teste",)


def test_plano(amb):
    plano = reg.obter("parecer_rco").planejar(Opcoes(modo_teste=True), {"bimestre": "4", "mostrar_navegador": True}, {}, {})
    assert plano.tipo == "coroutine" and plano.funcao is pr.gerar_pareceres_infantil_via_login
    assert plano.kwargs == {"bimestre": "4", "modo_teste": True, "mostrar_navegador": True, "chave": "parecer_rco"}


def test_componentes_da_tela(web):
    d = web.get("/web/api/automacoes/parecer_rco/componentes").get_json()
    assert "bimestre" in json.dumps(d)


def test_executar_sem_bimestre_da_400(web):
    r = web.post("/web/api/automacoes/parecer_rco/executar", json={})
    assert r.status_code == 400 and "2º ou 4º" in r.get_json()["mensagem"]


def test_executar_sem_credenciais_da_400(web, monkeypatch):
    monkeypatch.setattr(credenciais, "LOGIN_RCO", "cpf")
    r = web.post("/web/api/automacoes/parecer_rco/executar", json={"bimestre": "2"})
    assert r.status_code == 400 and "Credenciais do RCO" in r.get_json()["mensagem"]


def test_fluxo_completo_pela_web_com_pergunta_e_resposta(web, monkeypatch):
    """Executar → /status mostra a pergunta → /resposta → a automação segue e conclui."""
    async def falso(bimestre, *, modo_teste=False, mostrar_navegador=False, chave="parecer_rco"):
        codigo = await eu.perguntar(chave, "Código de verificação do RCO", "msg", "Código", intervalo=0.01)
        return {"codigo": codigo, "bimestre": bimestre, "teste": modo_teste}
    monkeypatch.setattr(pr, "gerar_pareceres_infantil_via_login", falso)

    r = web.post("/web/api/automacoes/parecer_rco/executar", json={"bimestre": "2", "modo_teste": True})
    assert r.status_code == 200 and r.get_json()["status"] == "executando"

    pergunta = None
    for _ in range(300):
        s = web.get("/web/api/automacoes/parecer_rco/status").get_json()
        if s.get("pergunta"):
            pergunta = s["pergunta"]
            break
        time.sleep(0.02)
    assert pergunta and pergunta["titulo"] == "Código de verificação do RCO" and "resposta" not in pergunta

    erro = web.post("/web/api/automacoes/parecer_rco/resposta", json={"id": "velho", "valor": "1"})
    assert erro.status_code == 400
    vazio = web.post("/web/api/automacoes/parecer_rco/resposta", json={"id": pergunta["id"], "valor": ""})
    assert vazio.status_code == 400
    ok = web.post("/web/api/automacoes/parecer_rco/resposta", json={"id": pergunta["id"], "valor": "246810"})
    assert ok.status_code == 200

    for _ in range(300):
        s = web.get("/web/api/automacoes/parecer_rco/status").get_json()
        if s["status"] != "executando":
            break
        time.sleep(0.02)
    assert s["status"] == "concluido" and s["pergunta"] is None and s["tem_resultado"] is True
    assert rotas._EXECUCOES["parecer_rco"]["resultado"] == {"codigo": "246810", "bimestre": "2", "teste": True}


def test_cancelar_com_pergunta_aberta(web, monkeypatch):
    async def falso(bimestre, *, modo_teste=False, mostrar_navegador=False, chave="parecer_rco"):
        await eu.perguntar(chave, "Código", intervalo=0.01)
    monkeypatch.setattr(pr, "gerar_pareceres_infantil_via_login", falso)
    web.post("/web/api/automacoes/parecer_rco/executar", json={"bimestre": "4"})
    for _ in range(300):
        if web.get("/web/api/automacoes/parecer_rco/status").get_json().get("pergunta"):
            break
        time.sleep(0.02)
    assert web.post("/web/api/automacoes/parecer_rco/cancelar").status_code == 200
    for _ in range(300):
        s = web.get("/web/api/automacoes/parecer_rco/status").get_json()
        if s["status"] != "executando":
            break
        time.sleep(0.02)
    assert s["status"] == "cancelado" and s["pergunta"] is None


def test_resposta_sem_pergunta_aberta(web):
    r = web.post("/web/api/automacoes/parecer_rco/resposta", json={"id": "x", "valor": "1"})
    assert r.status_code == 400 and "Não há nenhuma pergunta" in r.get_json()["mensagem"]


def test_tela_tem_a_caixa_de_pergunta_e_nao_tem_mais_o_formulario_legado():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert "_execPerguntar(chave, s.pergunta)" in js and "/resposta" in js
    legado = js[js.index("const CAMPOS_AUTOMACAO"):js.index("const CAMPOS_PADRAO")]
    assert "parecer_rco" not in legado


# ───────────── linha de comando ─────────────

def test_cli_simular(amb, capsys):
    from src.comum import cli
    assert cli.main(["parecer_rco", "--bimestre", "4", "--teste", "--simular"]) == 0
    saida = capsys.readouterr().out
    assert "gerar_pareceres_infantil_via_login" in saida and "bimestre='4'" in saida and "modo_teste=True" in saida


def test_cli_sem_bimestre_da_erro(amb, capsys):
    from src.comum import cli
    assert cli.main(["parecer_rco", "--simular"]) == 2
    assert "2º ou 4º" in capsys.readouterr().err


def test_cli_liga_o_modo_terminal_so_durante_a_execucao(amb, monkeypatch):
    from src.comum import cli
    visto = []
    monkeypatch.setattr(cli, "_executar_plano", lambda plano: visto.append(eu._MODO_TERMINAL) or 0)
    assert cli.main(["parecer_rco", "--bimestre", "2"]) == 0
    assert visto == [True] and eu._MODO_TERMINAL is False

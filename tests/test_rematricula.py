"""Testes de src/automacao/rematricula.py.

Os trechos de JavaScript rodam num Chromium real sobre HTML local (pulados se
o navegador não estiver instalado); o restante usa páginas simuladas.
"""

import asyncio
import json

import pytest

from src.automacao import rematricula as rem
from src.comum import arquivos_json, credenciais, paths

# A fixture abaixo troca asyncio.sleep por um no-op no processo todo; as pausas
# reais que o teste do Chromium precisa usam esta referência guardada antes.
_SLEEP_REAL = asyncio.sleep


# ----------------------------------------------------------
# infraestrutura
# ----------------------------------------------------------

@pytest.fixture(autouse=True)
def dados_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)
    monkeypatch.setattr(paths, "ano_atual", lambda: 2026)

    async def _sem_espera(*_a, **_k):
        return None

    monkeypatch.setattr(rem.asyncio, "sleep", _sem_espera)
    return tmp_path


def rodar(coro):
    return asyncio.run(coro)


def aluno(cgm, nome=None, nasc="01/01/2019"):
    return {"cgm": str(cgm), "Nome": nome or f"Aluno {cgm}", "Data Nasc.": nasc}


def ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


# ----------------------------------------------------------
# funções puras
# ----------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("", ""), (None, ""),
    ("2º Ano – B", "2o ano - b"),        # NFKC + traço unificado + sem acento
    ("  INFANTIL   4 ", "infantil 4"),
    ("Ação\u00a0Ñandú", "acao nandu"),
])
def test_normalize_text(entrada, esperado):
    assert rem.normalize_text(entrada) == esperado


@pytest.mark.parametrize("texto,href,esperado", [
    ("B", "javascript:AoClicarTurma('1','2','3','4','5','B ','2º Ano','x')", ("2º Ano", "2º Ano - B")),
    ("X", "javascript:AoClicarTurma('1','2','3','4','5','','2º Ano','x')", ("2º Ano", "2º Ano")),
    ("Texto", "javascript:AoClicarTurma('1','2')", ("", "Texto")),
    ("", "javascript:AoClicarTurma('1','2')", ("", "javascript:AoClicarTurma('1','2')")),
    ("Texto", "", ("", "Texto")),
])
def test_label_da_secao(texto, href, esperado):
    assert rem._label_da_secao(texto, href) == esperado


# ----------------------------------------------------------
# registrar_resultado
# ----------------------------------------------------------

def test_registrar_sucesso_remove_erro_e_nao_duplica():
    sucessos, erros, hist = [], [{"cgm": "1", "nome": "A", "turma": "T", "tentativas": 2}], []
    rem.registrar_resultado(sucessos, erros, hist, aluno(1), "T", True)
    rem.registrar_resultado(sucessos, erros, hist, aluno(1), "T", True)  # repetido
    assert len(sucessos) == 1 and erros == [] and len(hist) == 2
    assert hist[0]["sucesso"] is True and "erro" not in sucessos[0]


def test_registrar_falha_acumula_tentativas_e_substitui_entrada():
    sucessos, erros, hist = [], [], []
    r1 = rem.registrar_resultado(sucessos, erros, hist, aluno(1), "T", False, "erro a")
    r2 = rem.registrar_resultado(sucessos, erros, hist, aluno(1), "T", False, "erro b")
    assert r1["tentativas"] == 1 and r2["tentativas"] == 2
    assert len(erros) == 1 and erros[0]["erro"] == "erro b"
    assert [h["sucesso"] for h in hist] == [False, False]


def test_registrar_erro_critico_soma_incremento_e_nao_duplica():
    erros = [{"cgm": "1", "nome": "A", "turma": "T", "tentativas": 1}]
    rem.registrar_resultado([], erros, [], aluno(1), "T", False, "crit", incremento_tentativas=3)
    assert len(erros) == 1 and erros[0]["tentativas"] == 4
    novo = []
    rem.registrar_resultado([], novo, [], aluno(9), "T", False, "crit", incremento_tentativas=3)
    assert novo[0]["tentativas"] == 3   # igual ao original quando não havia erro anterior


# ----------------------------------------------------------
# persistência
# ----------------------------------------------------------

def test_arquivos_inexistentes_viram_listas_vazias():
    assert rem.carregar_sucessos_anteriores() == []
    assert rem.carregar_erros_anteriores() == []
    assert rem.carregar_historico_anterior() == []


def test_salvar_resultados_grava_os_tres_arquivos_na_pasta_de_dados(dados_tmp):
    rem.salvar_resultados([{"cgm": "1"}], [{"cgm": "2"}], [{"cgm": "3"}])
    assert ler(dados_tmp / rem.ARQUIVO_SUCESSO) == [{"cgm": "1"}]
    assert ler(dados_tmp / rem.ARQUIVO_ERROS) == [{"cgm": "2"}]
    assert ler(dados_tmp / rem.ARQUIVO_HISTORICO) == [{"cgm": "3"}]
    assert [p for p in dados_tmp.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.parametrize("carregar,arquivo", [
    (rem.carregar_sucessos_anteriores, rem.ARQUIVO_SUCESSO),
    (rem.carregar_erros_anteriores, rem.ARQUIVO_ERROS),
    (rem.carregar_historico_anterior, rem.ARQUIVO_HISTORICO),
])
def test_arquivo_corrompido_levanta_erro_e_nao_e_alterado(dados_tmp, carregar, arquivo):
    lixo = b'[{"cgm": "1", "nome"'
    (dados_tmp / arquivo).write_bytes(lixo)
    with pytest.raises(rem.RematriculaCorrompidaError):
        carregar()
    assert (dados_tmp / arquivo).read_bytes() == lixo


def test_arquivo_com_tipo_errado_e_tratado_como_corrompido(dados_tmp):
    (dados_tmp / rem.ARQUIVO_ERROS).write_text('{"nao": "e lista"}', encoding="utf-8")
    with pytest.raises(rem.RematriculaCorrompidaError):
        rem.carregar_erros_anteriores()


def test_falha_ao_salvar_preserva_versao_anterior(dados_tmp, monkeypatch):
    rem.salvar_resultados([{"cgm": "ok"}], [], [])
    antes = (dados_tmp / rem.ARQUIVO_SUCESSO).read_bytes()

    def quebra(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(arquivos_json.json, "dump", quebra)
    with pytest.raises(OSError):
        rem.salvar_resultados([{"cgm": "novo"}], [], [])
    assert (dados_tmp / rem.ARQUIVO_SUCESSO).read_bytes() == antes


# ----------------------------------------------------------
# JavaScript das páginas (Chromium real)
# ----------------------------------------------------------

HTML_SERE = """<html><body>
<a href="javascript:AoClicarTurma('1','2','3','4','5','A ','2º Ano','x')">A</a>
<a href="javascript:AoClicarTurma('1','2','3','4','5','B ','2º Ano','x')">  B  </a>
<a href="javascript:AoClicarTurma('1','2','3','4','5','A ','INFANTIL 4','x')">Infantil   4 A</a>
<a href="javascript:AoClicarAluno('10')">10</a>
<table>
<tr><th>n</th></tr>
<tr><td>1</td><td><a href="javascript:AoClicarAluno('10')">10</a></td><td>  Maria   da   Silva </td><td>01/01/2019</td><td>7</td><td>F</td><td>Matriculado</td><td>01/02/2026</td></tr>
<tr><td>2</td><td><a href="javascript:AoClicarAluno('11')">11</a></td><td>Joao</td><td>02/02/2019</td><td>7</td><td>M</td><td>Transferido</td><td>01/02/2026</td></tr>
<tr><td>3</td><td>12</td><td>Linha curta</td></tr>
</table>
<table><tr><td class="texto_normal">CPF do Responsável : 12345678901</td></tr></table>
<script>
window.__clicado = null;
function AoClicarTurma(){ window.__clicado = Array.from(arguments).join('|'); }
function AoClicarAluno(){}
</script>
</body></html>"""


def _chromium_ok():
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


CHROMIUM = _chromium_ok()
precisa_chromium = pytest.mark.skipif(not CHROMIUM, reason="Chromium do Playwright não instalado")


def com_pagina(html, teste):
    """Roda `teste(page)` numa página real com o HTML dado (esperas do script viram ~0)."""
    from playwright.async_api import async_playwright

    async def main():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(html)

                async def espera_curta(_ms):
                    await _SLEEP_REAL(0.05)

                page.wait_for_timeout = espera_curta
                return await teste(page)
            finally:
                await browser.close()

    return asyncio.run(main())


@precisa_chromium
def test_js_listar_secao_turmas():
    async def t(page):
        return (
            await rem.listar_secao_turmas(page, "2º Ano"),
            await rem.listar_secao_turmas(page, "infantil 4"),   # sem depender de caixa/acento
            await rem.listar_secao_turmas(page, "9º Ano"),
        )
    dois, inf4, nenhum = com_pagina(HTML_SERE, t)
    assert dois == ["2º Ano - A", "2º Ano - B"]
    assert inf4 == ["INFANTIL 4 - A"]
    assert nenhum == []


@precisa_chromium
def test_js_obter_alunos_matriculados_filtra_situacao_e_colapsa_espacos():
    alunos = com_pagina(HTML_SERE, rem.obter_alunos_matriculados)
    assert alunos == [{
        "n": "1", "cgm": "10", "Nome": "Maria da Silva", "Data Nasc.": "01/01/2019",
        "Idade": "7", "Sexo": "F", "Situação": "Matriculado", "Data Matricula": "01/02/2026",
    }]


@precisa_chromium
def test_js_obter_cpf_responsavel():
    assert com_pagina(HTML_SERE, rem.obter_cpf_responsavel) == "12345678901"
    assert com_pagina("<html><body><p>nada</p></body></html>", rem.obter_cpf_responsavel) is None


@precisa_chromium
def test_selecionar_turma_exata_parcial_e_inexistente():
    async def t(page):
        # navegação "javascript:" é assíncrona no Chromium: dá um respiro antes de ler o efeito
        exata = await rem.selecionar_turma(page, "2º Ano - B")
        await _SLEEP_REAL(0.3)
        clicado_exata = await page.evaluate("window.__clicado")
        await page.evaluate("window.__clicado = null")
        parcial = await rem.selecionar_turma(page, "infantil 4")
        await _SLEEP_REAL(0.3)
        clicado_parcial = await page.evaluate("window.__clicado")
        await page.evaluate("window.__clicado = null")
        nao = await rem.selecionar_turma(page, "8º Ano - Z")
        await _SLEEP_REAL(0.3)
        return exata, clicado_exata, parcial, clicado_parcial, nao, await page.evaluate("window.__clicado")

    exata, c1, parcial, c2, nao, c3 = com_pagina(HTML_SERE, t)
    assert exata is True and c1 == "1|2|3|4|5|B |2º Ano|x"        # clicou na seção B, não na A
    assert parcial is True and c2 == "1|2|3|4|5|A |INFANTIL 4|x"
    assert nao is False and c3 is None


@precisa_chromium
def test_gerar_chave_acesso_sucesso_e_timeout():
    ok_html = """<button onclick="document.getElementById('chaveAcesso').value='ABC123'">Gerar Chave</button>
                 <input id="chaveAcesso" value="">"""
    mudo_html = """<button>Gerar Chave</button><input id="chaveAcesso" value="">"""

    assert com_pagina(ok_html, rem.gerar_chave_acesso) == "ABC123"

    async def t(page):
        with pytest.raises(rem.ErroReiniciarNavegador):
            await rem.gerar_chave_acesso(page)
        return True
    assert com_pagina(mudo_html, t)


# ----------------------------------------------------------
# páginas simuladas para os fluxos
# ----------------------------------------------------------

class PaginaFake:
    def __init__(self, links=()):
        self.links, self.fechada = list(links), False

    async def wait_for_selector(self, *_a, **_k):
        return None

    async def query_selector_all(self, *_a, **_k):
        return self.links

    async def wait_for_timeout(self, *_a):
        return None

    async def go_back(self):
        return None

    async def goto(self, *_a, **_k):
        return None

    async def close(self):
        self.fechada = True


class LinkFake:
    def __init__(self, cgm):
        self.cgm, self.clicado = cgm, False

    async def inner_text(self):
        return f" {self.cgm} "

    async def click(self):
        self.clicado = True


class NavegadorFake:
    def __init__(self):
        self.paginas = []

    async def new_page(self):
        p = PaginaFake()
        self.paginas.append(p)
        return p


def _passos(monkeypatch, chave="K", cpf="123", login_area=True, acesso=True, confirmar=True):
    async def gerar(_p):
        if isinstance(chave, Exception):
            raise chave
        return chave

    async def obter_cpf(_p):
        return cpf

    async def entrar(_p, _c, _k):
        return login_area

    async def acessar(_p, _n):
        return acesso

    async def confirmar_(_p):
        if isinstance(confirmar, Exception):
            raise confirmar
        return confirmar

    monkeypatch.setattr(rem, "gerar_chave_acesso", gerar)
    monkeypatch.setattr(rem, "obter_cpf_responsavel", obter_cpf)
    monkeypatch.setattr(rem, "fazer_login_area_aluno", entrar)
    monkeypatch.setattr(rem, "acessar_matricula_online", acessar)
    monkeypatch.setattr(rem, "confirmar_matricula", confirmar_)


# ----------------------------------------------------------
# processar_aluno
# ----------------------------------------------------------

def test_processar_aluno_fluxo_feliz_clica_no_aluno_certo_e_fecha_pagina(monkeypatch):
    _passos(monkeypatch)
    links = [LinkFake("9"), LinkFake("10")]
    sere, nav = PaginaFake(links), NavegadorFake()
    assert rodar(rem.processar_aluno(sere, nav, aluno(10))) == (True, None)
    assert [l.clicado for l in links] == [False, True]
    assert all(p.fechada for p in nav.paginas) and len(nav.paginas) == 1


def test_processar_aluno_ja_matriculado_conta_como_sucesso(monkeypatch):
    _passos(monkeypatch, confirmar="JA_MATRICULADO")
    assert rodar(rem.processar_aluno(PaginaFake([LinkFake("1")]), NavegadorFake(), aluno(1))) == (True, None)


@pytest.mark.parametrize("kw,msg", [
    (dict(cpf=None), "CPF do responsável não encontrado"),
    (dict(login_area=False), "Erro ao fazer login na Área do Aluno"),
    (dict(acesso=False), "Erro ao acessar matrícula online"),
    (dict(confirmar=False), "Erro ao confirmar matrícula"),
])
def test_processar_aluno_falhas_de_etapa(monkeypatch, kw, msg):
    _passos(monkeypatch, **kw)
    assert rodar(rem.processar_aluno(PaginaFake([LinkFake("1")]), NavegadorFake(), aluno(1))) == (False, msg)


def test_processar_aluno_nao_encontrado_na_lista(monkeypatch):
    _passos(monkeypatch)
    ok, msg = rodar(rem.processar_aluno(PaginaFake([LinkFake("2")]), NavegadorFake(), aluno(1)))
    assert (ok, msg) == (False, "Aluno não encontrado na lista")


def test_processar_aluno_propaga_erro_de_reinicio_e_fecha_pagina_da_area(monkeypatch):
    _passos(monkeypatch, chave=rem.ErroReiniciarNavegador("sem chave"))
    with pytest.raises(rem.ErroReiniciarNavegador):
        rodar(rem.processar_aluno(PaginaFake([LinkFake("1")]), NavegadorFake(), aluno(1)))

    _passos(monkeypatch, confirmar=rem.ErroReiniciarNavegador("caiu"))
    nav = NavegadorFake()
    with pytest.raises(rem.ErroReiniciarNavegador):
        rodar(rem.processar_aluno(PaginaFake([LinkFake("1")]), nav, aluno(1)))
    assert nav.paginas and all(p.fechada for p in nav.paginas)   # finally fechou


def test_processar_aluno_excecao_inesperada_vira_falha_com_mensagem(monkeypatch):
    _passos(monkeypatch, confirmar=RuntimeError("boom"))
    ok, msg = rodar(rem.processar_aluno(PaginaFake([LinkFake("1")]), NavegadorFake(), aluno(1)))
    assert ok is False and msg == "boom"


# ----------------------------------------------------------
# processar_turma
# ----------------------------------------------------------

def _turma(monkeypatch, *, abrir=None, selecionar=True, resultados=None):
    """
    Simula a sessão. `abrir`: lista de True/False (login+navegação por chamada;
    esgotada => True). `resultados`: {cgm: [efeito, ...]} onde efeito é uma
    tupla (sucesso, msg) ou uma exceção a levantar; esgotado => (True, None).
    """
    estado = {"aberturas": 0, "chamadas": []}
    abrir = list(abrir or [])
    resultados = {k: list(v) for k, v in (resultados or {}).items()}

    async def _abrir(_b, _l, _s):
        estado["aberturas"] += 1
        ok = abrir.pop(0) if abrir else True
        return PaginaFake() if ok else None

    async def _selecionar(_p, _t):
        return selecionar

    async def _processar(_p, _b, al, chaves=None):
        estado["chamadas"].append(al["cgm"])
        fila = resultados.get(al["cgm"], [])
        efeito = fila.pop(0) if fila else (True, None)
        if isinstance(efeito, BaseException):
            raise efeito
        return efeito

    async def _navegar(_p):
        estado["navegacoes"] += 1
        return True

    estado["navegacoes"] = 0
    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "navegar_para_por_turmas", _navegar)
    monkeypatch.setattr(rem, "selecionar_turma", _selecionar)
    monkeypatch.setattr(rem, "processar_aluno", _processar)
    return estado


def _rodar_turma(alunos, sucessos=None, erros=None, historico=None, ja_na_secao=False):
    sucessos = [] if sucessos is None else sucessos
    erros = [] if erros is None else erros
    historico = [] if historico is None else historico
    sessao = rem.SessaoSere(NavegadorFake(), "l", "s")
    r = rodar(asyncio.wait_for(
        rem.processar_turma(sessao, "2º Ano - A", alunos, sucessos, erros, historico, ja_na_secao=ja_na_secao), 5
    ))
    return r, sucessos, erros, historico


def test_turma_tudo_certo_registra_e_salva_a_cada_aluno(monkeypatch, dados_tmp):
    chamadas_salvar = []
    original = rem.salvar_resultados
    monkeypatch.setattr(rem, "salvar_resultados", lambda *a: (chamadas_salvar.append(1), original(*a))[1])
    _turma(monkeypatch)
    r, suc, err, hist = _rodar_turma([aluno(1), aluno(2), aluno(3)])
    assert r is True and [s["cgm"] for s in suc] == ["1", "2", "3"] and err == []
    assert len(hist) == 3 and len(chamadas_salvar) == 3
    assert [x["cgm"] for x in ler(dados_tmp / rem.ARQUIVO_SUCESSO)] == ["1", "2", "3"]


def test_turma_falha_comum_registra_erro_e_segue_para_o_proximo(monkeypatch):
    _turma(monkeypatch, resultados={"1": [(False, "CPF do responsável não encontrado")]})
    r, suc, err, hist = _rodar_turma([aluno(1), aluno(2)])
    assert r is True and [e["cgm"] for e in err] == ["1"] and err[0]["tentativas"] == 1
    assert [s["cgm"] for s in suc] == ["2"]


def test_login_sempre_falhando_nao_fica_em_loop_infinito(monkeypatch):
    """Original: `continue` sem contador => tentava para sempre."""
    est = _turma(monkeypatch, abrir=[False] * 50)
    r, suc, err, hist = _rodar_turma([aluno(1), aluno(2)])
    assert r is False
    assert est["aberturas"] == rem.MAX_FALHAS_SESSAO
    assert suc == err == hist == [] and est["chamadas"] == []   # nada registrado: retoma na próxima execução


def test_falha_transitoria_de_login_se_recupera(monkeypatch):
    est = _turma(monkeypatch, abrir=[False, False])       # falha 2x e depois abre
    r, suc, _e, _h = _rodar_turma([aluno(1)])
    assert r is True and [s["cgm"] for s in suc] == ["1"] and est["aberturas"] == 3


def test_turma_nao_encontrada_abandona_sem_registrar(monkeypatch):
    est = _turma(monkeypatch, selecionar=False)
    r, suc, err, hist = _rodar_turma([aluno(1)])
    assert r is False and suc == err == hist == [] and est["chamadas"] == []


def test_erro_critico_uma_vez_reinicia_e_conclui_o_mesmo_aluno(monkeypatch):
    est = _turma(monkeypatch, resultados={"1": [rem.ErroReiniciarNavegador("caiu")]})
    r, suc, err, _h = _rodar_turma([aluno(1), aluno(2)])
    assert r is True and err == [] and [s["cgm"] for s in suc] == ["1", "2"]
    assert est["chamadas"] == ["1", "1", "2"] and est["aberturas"] == 2   # sessão reiniciada uma vez


def test_erro_critico_tres_vezes_registra_erro_permanente_e_avanca(monkeypatch):
    crit = rem.ErroReiniciarNavegador("caiu")
    est = _turma(monkeypatch, resultados={"1": [crit, crit, crit]})
    r, suc, err, hist = _rodar_turma([aluno(1), aluno(2)])
    assert r is True and est["chamadas"] == ["1", "1", "1", "2"]
    assert len(err) == 1 and err[0]["cgm"] == "1" and err[0]["tentativas"] == rem.MAX_TENTATIVAS_NAVEGADOR
    assert err[0]["erro"].startswith("Erro crítico após 3 tentativas")
    assert [s["cgm"] for s in suc] == ["2"]


def test_erro_critico_permanente_nao_duplica_erro_ja_existente(monkeypatch):
    crit = rem.ErroReiniciarNavegador("caiu")
    _turma(monkeypatch, resultados={"1": [crit, crit, crit]})
    anteriores = [{"cgm": "1", "nome": "Aluno 1", "turma": "2º Ano - A", "tentativas": 2, "erro": "velho"}]
    _r, _s, err, _h = _rodar_turma([aluno(1)], erros=anteriores)
    assert len(err) == 1 and err[0]["tentativas"] == 5   # 2 anteriores + 3 reinícios


def test_excecao_inesperada_persistente_tambem_tem_limite(monkeypatch):
    est = _turma(monkeypatch, resultados={"1": [RuntimeError("x")] * 20})
    r, suc, err, _h = _rodar_turma([aluno(1)])
    assert r is False and len(est["chamadas"]) == rem.MAX_FALHAS_SESSAO


def test_contador_de_falhas_de_sessao_zera_a_cada_aluno(monkeypatch):
    # 2 exceções no aluno 1, sucesso; 2 exceções no aluno 2, sucesso: sem abandonar
    _turma(monkeypatch, resultados={"1": [RuntimeError("a"), RuntimeError("b")],
                                    "2": [RuntimeError("c"), RuntimeError("d")]})
    r, suc, _e, _h = _rodar_turma([aluno(1), aluno(2)])
    assert r is True and [s["cgm"] for s in suc] == ["1", "2"]


# ----------------------------------------------------------
# rematricular_via_login (orquestração)
# ----------------------------------------------------------

class _Lancador:
    def __init__(self, navegador):
        self.nav, self.headless = navegador, None

    async def launch(self, headless=True):
        self.headless = headless
        return self.nav


class _NavegadorFechavel(NavegadorFake):
    fechado = False

    async def close(self):
        self.fechado = True


class _PW:
    def __init__(self, nav):
        self.chromium = _Lancador(nav)
        self.firefox = _Lancador(nav)


class _PWCtx:
    def __init__(self, nav):
        self.pw = _PW(nav)

    async def __aenter__(self):
        return self.pw

    async def __aexit__(self, *_a):
        return False


def _orquestrar(monkeypatch, secoes, alunos_por_secao, resultados=None, abrir_ok=True):
    """secoes: {turma_base: [secoes]}; alunos_por_secao: {secao: [alunos]}."""
    nav = _NavegadorFechavel()
    ctx = _PWCtx(nav)
    monkeypatch.setattr(rem, "async_playwright", lambda: ctx)
    estado = {"secao_aberta": None, "processados": [], "logins": [], "ctx": ctx}

    async def _abrir(_b, login, senha):
        estado["logins"].append((login, senha))
        return PaginaFake() if abrir_ok else None

    async def _listar(_p, turma):
        return secoes.get(turma, [])

    async def _selecionar(_p, secao):
        estado["secao_aberta"] = secao
        return True

    async def _obter(_p):
        return alunos_por_secao.get(estado["secao_aberta"], [])

    async def _navegar(_p):
        estado["navegacoes"] += 1
        return True

    estado["navegacoes"] = 0
    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "navegar_para_por_turmas", _navegar)
    monkeypatch.setattr(rem, "listar_secao_turmas", _listar)
    monkeypatch.setattr(rem, "selecionar_turma", _selecionar)
    monkeypatch.setattr(rem, "obter_alunos_matriculados", _obter)

    res = {k: list(v) for k, v in (resultados or {}).items()}

    async def _processar(_p, _b, al, chaves=None):
        estado["processados"].append(al["cgm"])
        fila = res.get(al["cgm"], [])
        return fila.pop(0) if fila else (True, None)

    monkeypatch.setattr(rem, "processar_aluno", _processar)
    return nav, estado


def _semear(dados_tmp, sucessos=(), erros=(), historico=()):
    rem.salvar_resultados(list(sucessos), list(erros), list(historico))


def _reg(cgm, turma, **extra):
    return {"cgm": str(cgm), "nome": f"Aluno {cgm}", "turma": turma, "timestamp": "2026-01-01T00:00:00", **extra}


def test_producao_carrega_erros_acumula_tentativas_e_preserva_o_que_nao_visitou(monkeypatch, dados_tmp):
    _semear(
        dados_tmp,
        sucessos=[_reg(1, "2º Ano - A")],
        erros=[_reg(2, "2º Ano - A", erro="velho", tentativas=1),
               _reg(50, "3º Ano - A", erro="de outra seção", tentativas=2)],
        historico=[_reg(1, "2º Ano - A", sucesso=True)],
    )
    nav, est = _orquestrar(
        monkeypatch,
        secoes={"2º Ano": ["2º Ano - A"]},                         # 3º Ano não tem seção nesta execução
        alunos_por_secao={"2º Ano - A": [aluno(1), aluno(2), aluno(3)]},
        resultados={"2": [(False, "de novo")]},
    )
    r = rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano", "3º Ano"], login="l", senha="s"))

    assert est["processados"] == ["2", "3"]                        # 1 já feito: pulado
    por_cgm = {e["cgm"]: e for e in r["erros"]}
    assert por_cgm["2"]["tentativas"] == 2 and por_cgm["2"]["erro"] == "de novo"   # acumulou (original: 1)
    assert por_cgm["50"]["tentativas"] == 2                        # seção não visitada: preservado (original: apagado)
    assert {s["cgm"] for s in ler(dados_tmp / rem.ARQUIVO_SUCESSO)} == {"1", "3"}
    hist = ler(dados_tmp / rem.ARQUIVO_HISTORICO)
    assert len(hist) == 3 and r["novos_no_historico"] == 2         # 1 antigo + 2 novos (original: só os 2 novos)
    assert r["total_sucessos"] == 2 and r["total_erros"] == 2
    assert nav.fechado


def test_producao_sucesso_remove_o_erro_anterior(monkeypatch, dados_tmp):
    _semear(dados_tmp, erros=[_reg(2, "2º Ano - A", erro="velho", tentativas=3)])
    _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(2)]})
    r = rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert r["erros"] == [] and ler(dados_tmp / rem.ARQUIVO_ERROS) == []
    assert [s["cgm"] for s in ler(dados_tmp / rem.ARQUIVO_SUCESSO)] == ["2"]


def test_apenas_erros_processa_so_quem_esta_na_lista_de_erros_da_secao(monkeypatch, dados_tmp):
    _semear(dados_tmp, erros=[_reg(2, "2º Ano - A", erro="x", tentativas=1),
                              _reg(9, "2º Ano - B", erro="x", tentativas=1)])
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]},
                         {"2º Ano - A": [aluno(1), aluno(2), aluno(9)]})
    rodar(rem.rematricular_via_login(apenas_erros=True, turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == ["2"]      # 1 nunca errou; 9 é erro de OUTRA seção


def test_modo_teste_processa_um_aluno_pendente_por_secao(monkeypatch, dados_tmp):
    _semear(dados_tmp, sucessos=[_reg(1, "2º Ano - A")])
    _, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"]},
        {"2º Ano - A": [aluno(1), aluno(2), aluno(3)], "2º Ano - B": [aluno(7), aluno(8)]},
    )
    rodar(rem.rematricular_via_login(modo_teste=True, turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == ["2", "7"]


def test_um_aluno_processa_so_um_no_total_e_nao_abre_as_outras_secoes(monkeypatch, dados_tmp):
    _semear(dados_tmp, sucessos=[_reg(1, "2º Ano - A")])
    _, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"], "3º Ano": ["3º Ano - A"]},
        {"2º Ano - A": [aluno(1), aluno(2), aluno(3)], "2º Ano - B": [aluno(7)], "3º Ano - A": [aluno(9)]},
    )
    res = rodar(rem.rematricular_via_login(um_aluno=True, turmas_alvo=["2º Ano", "3º Ano"], login="l", senha="s"))
    assert est["processados"] == ["2"]          # o 1 já estava em sucesso; só o 2 foi tentado
    assert res["total_sucessos"] == 2           # o anterior + o de teste
    assert est["secao_aberta"] == "2º Ano - A"  # nem selecionou a seção B nem a turma 3º Ano


def test_um_aluno_com_falha_tambem_encerra(monkeypatch, dados_tmp):
    _, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"]},
        {"2º Ano - A": [aluno(1), aluno(2)], "2º Ano - B": [aluno(7)]},
        resultados={"1": [(False, "falhou")]},
    )
    res = rodar(rem.rematricular_via_login(um_aluno=True, turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == ["1"]
    assert res["total_erros"] == 1 and res["total_sucessos"] == 0


def test_um_aluno_pula_secao_sem_pendentes_e_pega_o_da_proxima(monkeypatch, dados_tmp):
    _semear(dados_tmp, sucessos=[_reg(1, "2º Ano - A")])
    _, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"]},
        {"2º Ano - A": [aluno(1)], "2º Ano - B": [aluno(7), aluno(8)]},
    )
    rodar(rem.rematricular_via_login(um_aluno=True, turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == ["7"]


def test_um_aluno_com_apenas_erros_reprocessa_so_o_primeiro_com_erro(monkeypatch, dados_tmp):
    _semear(dados_tmp, erros=[_reg(2, "2º Ano - A", tentativas=1), _reg(3, "2º Ano - A", tentativas=1)])
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1), aluno(2), aluno(3)]})
    rodar(rem.rematricular_via_login(um_aluno=True, apenas_erros=True, turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == ["2"]


def test_um_aluno_desligado_mantem_o_comportamento_de_producao(monkeypatch, dados_tmp):
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"]},
                         {"2º Ano - A": [aluno(1), aluno(2)], "2º Ano - B": [aluno(7)]})
    rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == ["1", "2", "7"]


# ---- BUG-REM-001: confirmar_matricula só devolve True se a página provar a confirmação ----

class _PaginaConfirmar:
    """Página mínima para confirmar_matricula: o conteúdo muda conforme o clique final."""

    def __init__(self, antes="<p>formulário</p>", depois="<p>formulário</p>", final_ok=True, content_falha_antes=0):
        self.antes, self.depois, self.final_ok = antes, depois, final_ok
        self.final_clicado, self.cliques, self.consultas_depois = False, [], 0
        self._falhas_restantes = content_falha_antes

    async def content(self):
        if self.final_clicado:
            self.consultas_depois += 1
            if self._falhas_restantes > 0:
                self._falhas_restantes -= 1
                raise RuntimeError("Execution context was destroyed (navegação em curso)")
            return self.depois
        return self.antes

    async def click(self, seletor, timeout=None):
        self.cliques.append(seletor)
        if "j_idt147" in seletor or seletor == "//button[span[contains(text(),'Confirmar')]]":
            if not self.final_ok:
                raise RuntimeError("botão final não encontrado")
            self.final_clicado = True

    async def query_selector_all(self, _sel):
        return []

    async def wait_for_timeout(self, _ms):
        return None


def test_confirmar_sucesso_so_quando_a_pagina_mostra_a_confirmacao():
    pg = _PaginaConfirmar(depois="<h2>Matrícula realizada com sucesso</h2>")
    assert rodar(rem.confirmar_matricula(pg)) is True and pg.final_clicado


def test_confirmar_aceita_o_comprovante_como_prova():
    pg = _PaginaConfirmar(depois="<a>Imprimir Comprovante</a>")
    assert rodar(rem.confirmar_matricula(pg)) is True


def test_confirmar_clique_sem_efeito_devolve_false_e_nao_fica_em_laco(monkeypatch):
    monkeypatch.setattr(rem, "ESPERA_CONFIRMACAO_MS", 2000)
    pg = _PaginaConfirmar(depois="<p>Erro de validação</p>")
    assert rodar(rem.confirmar_matricula(pg)) is False
    assert pg.final_clicado and pg.consultas_depois == 4  # 2000 // 500 consultas, depois desiste


def test_confirmar_espera_a_confirmacao_aparecer_apos_navegacao(monkeypatch):
    pg = _PaginaConfirmar(depois="<p>Matrícula realizada com sucesso</p>", content_falha_antes=2)
    assert rodar(rem.confirmar_matricula(pg)) is True
    assert pg.consultas_depois == 3  # 2 falhas de navegação + 1 leitura boa


def test_confirmar_ja_matriculado_nao_clica_em_nada():
    for texto in ("<p>MATRÍCULA REALIZADA COM SUCESSO</p>", "<a>imprimir comprovante</a>"):
        pg = _PaginaConfirmar(antes=texto)
        assert rodar(rem.confirmar_matricula(pg)) == "JA_MATRICULADO" and pg.cliques == []


def test_confirmar_botao_final_inexistente_devolve_false():
    pg = _PaginaConfirmar(final_ok=False)
    assert rodar(rem.confirmar_matricula(pg)) is False and not pg.final_clicado


# ---- UMA sessão no SERE: sem login repetido, continuando da tela atual ----

def test_varias_turmas_e_secoes_usam_uma_unica_sessao_do_sere(monkeypatch, dados_tmp):
    """Bug: 3 logins por seção — a janela fechava e reabria sozinha, e o SERE derrubava a sessão."""
    _, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"], "3º Ano": ["3º Ano - A"]},
        {"2º Ano - A": [aluno(1)], "2º Ano - B": [aluno(2)], "3º Ano - A": [aluno(3)]},
    )
    res = rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano", "3º Ano"], login="l", senha="s"))
    assert est["logins"] == [("l", "s")]                      # um único login na execução inteira
    assert est["processados"] == ["1", "2", "3"] and res["total_sucessos"] == 3
    assert est["navegacoes"] >= 2                              # entre turmas/seções volta pelo menu, na mesma página


def test_a_pagina_so_fecha_no_fim_da_execucao(monkeypatch, dados_tmp):
    paginas = []

    async def abrir(_b, _l, _s):
        paginas.append(PaginaFake())
        return paginas[-1]

    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"]},
                         {"2º Ano - A": [aluno(1)], "2º Ano - B": [aluno(2)]})
    monkeypatch.setattr(rem, "_abrir_por_turmas", abrir)
    rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert len(paginas) == 1 and paginas[0].fechada


def test_ja_na_secao_continua_da_tela_atual_sem_logar_nem_selecionar_de_novo(monkeypatch):
    est = _turma(monkeypatch)
    r, suc, _e, _h = _rodar_turma([aluno(1), aluno(2)], ja_na_secao=True)
    assert r is True and [s["cgm"] for s in suc] == ["1", "2"]
    assert est["aberturas"] == 0 and est["navegacoes"] == 0


def test_erro_critico_com_ja_na_secao_reinicia_a_sessao_e_reposiciona(monkeypatch):
    est = _turma(monkeypatch, resultados={"1": [rem.ErroReiniciarNavegador("caiu")]})
    r, suc, err, _h = _rodar_turma([aluno(1), aluno(2)], ja_na_secao=True)
    assert r is True and err == [] and [s["cgm"] for s in suc] == ["1", "2"]
    assert est["chamadas"] == ["1", "1", "2"] and est["aberturas"] == 1   # só o reinício logou de novo


# ---- SessaoSere: como a página volta para a lista de turmas ----

class _ElFake:
    def __init__(self, pagina, nome):
        self.pagina, self.nome = pagina, nome

    async def click(self):
        self.pagina.cliques.append(self.nome)
        if self.nome == "voltar":
            self.pagina.na_lista = True


class _PaginaSessao(PaginaFake):
    """Página de SERE simulada: tela de login, lista de turmas e botão Voltar configuráveis."""

    def __init__(self, login=False, na_lista=False, voltar=False):
        super().__init__()
        self.login, self.na_lista, self.tem_voltar, self.cliques = login, na_lista, voltar, []

    async def query_selector(self, seletor):
        if seletor == "#CHAVE":
            return _ElFake(self, "chave") if self.login else None
        if "AoClicarTurma" in seletor:
            return _ElFake(self, "turma") if self.na_lista else None
        if "Voltar" in seletor:
            return _ElFake(self, "voltar") if self.tem_voltar else None
        return None


def _sessao_com(monkeypatch, pagina, navegar=True):
    chamadas = {"abrir": 0, "login": 0, "navegar": 0}

    async def _abrir(_b, _l, _s):
        chamadas["abrir"] += 1
        return _PaginaSessao(na_lista=True)

    async def _login(page, _l, _s):
        chamadas["login"] += 1
        page.login = False
        return True

    async def _navegar(_p):
        chamadas["navegar"] += 1
        return navegar

    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "fazer_login_sere", _login)
    monkeypatch.setattr(rem, "navegar_para_por_turmas", _navegar)
    sessao = rem.SessaoSere(NavegadorFake(), "l", "s")
    sessao.page = pagina
    return sessao, chamadas


def test_sessao_sem_pagina_abre_uma_logada(monkeypatch):
    sessao, c = _sessao_com(monkeypatch, None)
    assert rodar(sessao.ir_para_lista_de_turmas()) is True and sessao.page is not None
    assert c == {"abrir": 1, "login": 0, "navegar": 0}


def test_sessao_ja_na_lista_de_turmas_nao_faz_nada(monkeypatch):
    sessao, c = _sessao_com(monkeypatch, _PaginaSessao(na_lista=True))
    assert rodar(sessao.ir_para_lista_de_turmas()) is True
    assert c == {"abrir": 0, "login": 0, "navegar": 0}


def test_sessao_usa_o_botao_voltar_antes_do_menu(monkeypatch):
    pg = _PaginaSessao(voltar=True)
    sessao, c = _sessao_com(monkeypatch, pg)
    assert rodar(sessao.ir_para_lista_de_turmas()) is True
    assert pg.cliques == ["voltar"] and c == {"abrir": 0, "login": 0, "navegar": 0}


def test_sessao_sem_voltar_vai_pelo_menu_na_mesma_pagina(monkeypatch):
    pg = _PaginaSessao()
    sessao, c = _sessao_com(monkeypatch, pg)
    assert rodar(sessao.ir_para_lista_de_turmas()) is True and sessao.page is pg
    assert c == {"abrir": 0, "login": 0, "navegar": 1}


def test_sessao_que_caiu_loga_de_novo_na_mesma_pagina(monkeypatch):
    pg = _PaginaSessao(login=True)
    sessao, c = _sessao_com(monkeypatch, pg)
    assert rodar(sessao.ir_para_lista_de_turmas()) is True and sessao.page is pg and not pg.fechada
    assert c == {"abrir": 0, "login": 1, "navegar": 1}


def test_falha_ao_navegar_descarta_a_pagina_para_a_proxima_tentativa_abrir_uma_limpa(monkeypatch):
    pg = _PaginaSessao()
    sessao, c = _sessao_com(monkeypatch, pg, navegar=False)
    assert rodar(sessao.ir_para_lista_de_turmas()) is False
    assert sessao.page is None and pg.fechada
    assert rodar(sessao.ir_para_lista_de_turmas()) is True and c["abrir"] == 1


# ---- localizar o aluno na lista (como o alunos.py) ----

class _LinkLinha(LinkFake):
    """Link de CGM numa linha da tabela; `situacao` é a coluna Situação dessa linha."""

    def __init__(self, cgm, situacao):
        super().__init__(cgm)
        self.situacao = situacao

    async def evaluate(self, _js):
        return self.situacao


def test_mesmo_cgm_em_duas_linhas_clica_na_linha_matriculado(monkeypatch):
    """Aluno que voltou: Transferido + Matriculado com o mesmo CGM — o clique tem de ir na linha Matriculado."""
    _passos(monkeypatch)
    velha, atual, outro = _LinkLinha("10", "Transferido"), _LinkLinha("10", "Matriculado"), _LinkLinha("11", "Matriculado")
    chave, cpf, erro = rodar(rem._abrir_ficha_gerar_chave(PaginaFake([velha, atual, outro]), aluno(10)))
    assert erro is None and (velha.clicado, atual.clicado, outro.clicado) == (False, True, False)


def test_cgm_sem_informacao_de_situacao_clica_no_primeiro_link_do_cgm(monkeypatch):
    _passos(monkeypatch)
    links = [LinkFake("9"), LinkFake("10"), LinkFake("10")]
    rodar(rem._abrir_ficha_gerar_chave(PaginaFake(links), aluno(10)))
    assert [l.clicado for l in links] == [False, True, False]


def test_sessao_caida_na_hora_de_abrir_a_ficha_pede_reinicio(monkeypatch):
    _passos(monkeypatch)
    with pytest.raises(rem.ErroReiniciarNavegador, match="sessão do SERE caiu"):
        rodar(rem._abrir_ficha_gerar_chave(_PaginaSessao(login=True), aluno(10)))


def test_secao_sem_pendentes_e_turma_sem_secoes_nao_quebram(monkeypatch, dados_tmp):
    _semear(dados_tmp, sucessos=[_reg(1, "2º Ano - A")])
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1)]})
    r = rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano", "Inexistente"], login="l", senha="s"))
    assert est["processados"] == [] and r["total_sucessos"] == 1


def test_login_do_sere_falhando_pula_turmas_e_ainda_grava_e_fecha(monkeypatch, dados_tmp):
    nav, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {}, abrir_ok=False)
    r = rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert est["processados"] == [] and r["total_erros"] == 0 and nav.fechado
    assert (dados_tmp / rem.ARQUIVO_SUCESSO).exists()


def test_arquivo_de_controle_corrompido_aborta_antes_de_abrir_o_navegador(monkeypatch, dados_tmp):
    (dados_tmp / rem.ARQUIVO_ERROS).write_bytes(b"[{ruim")

    def nao_deveria(*_a, **_k):
        raise AssertionError("não devia abrir o navegador")

    monkeypatch.setattr(rem, "async_playwright", nao_deveria)
    with pytest.raises(rem.RematriculaCorrompidaError):
        rodar(rem.rematricular_via_login(login="l", senha="s"))
    assert (dados_tmp / rem.ARQUIVO_ERROS).read_bytes() == b"[{ruim"


def test_credenciais_padrao_vem_de_comum_credenciais(monkeypatch, dados_tmp):
    # Fixa as credenciais no teste (antes dependia de um stub do ambiente de quem escreveu).
    monkeypatch.setattr(credenciais, "LOGIN", "login_sere")
    monkeypatch.setattr(credenciais, "SENHA", "senha_sere")
    _nav, est = _orquestrar(monkeypatch, {}, {})
    rodar(rem.rematricular_via_login(turmas_alvo=["X"]))
    assert est["logins"][0] == ("login_sere", "senha_sere")


def test_navegador_e_headless_configuraveis_com_padrao_igual_ao_original(monkeypatch, dados_tmp):
    _nav, est = _orquestrar(monkeypatch, {}, {})
    pw = est["ctx"].pw
    rodar(rem.rematricular_via_login(turmas_alvo=["X"], login="l", senha="s"))
    assert pw.chromium.headless is False and pw.firefox.headless is None   # padrão: Chromium visível

    rodar(rem.rematricular_via_login(turmas_alvo=["X"], login="l", senha="s", navegador="firefox", headless=True))
    assert pw.firefox.headless is True


# ----------------------------------------------------------
# chaves salvas (chave_responsavel.json)
# ----------------------------------------------------------

from src.automacao import chaves_responsavel as cr  # noqa: E402


def _salva(cgm, chave="SALVA", cpf="111", turma="2º Ano - A"):
    return {"cgm": str(cgm), "nome": f"Aluno {cgm}", "turma": turma, "cpf_responsavel": cpf, "chave": chave,
            "timestamp": "2026-11-02T10:00:00"}


def _passos_chave(monkeypatch, *, aceita=("SALVA", "NOVA"), chave_nova="NOVA", cpf_ficha="222", confirmar=True):
    """Área do Aluno só aceita as chaves em `aceita`; registra o que foi usado em cada etapa."""
    uso = {"gerou": 0, "logins": [], "acessos": 0}

    async def gerar(_p):
        uso["gerou"] += 1
        return chave_nova

    async def obter_cpf(_p):
        return cpf_ficha

    async def entrar(_p, cpf, chave):
        uso["logins"].append((cpf, chave))
        return chave in aceita

    async def acessar(_p, _n):
        uso["acessos"] += 1
        return True

    async def confirmar_(_p):
        return confirmar

    monkeypatch.setattr(rem, "gerar_chave_acesso", gerar)
    monkeypatch.setattr(rem, "obter_cpf_responsavel", obter_cpf)
    monkeypatch.setattr(rem, "fazer_login_area_aluno", entrar)
    monkeypatch.setattr(rem, "acessar_matricula_online", acessar)
    monkeypatch.setattr(rem, "confirmar_matricula", confirmar_)
    return uso


def test_chave_salva_pula_a_ficha_do_sere_e_entra_direto(monkeypatch, dados_tmp):
    uso = _passos_chave(monkeypatch)
    link = LinkFake("10")
    chaves = [_salva(10)]
    assert rodar(rem.processar_aluno(PaginaFake([link]), NavegadorFake(), aluno(10), chaves=chaves)) == (True, None)
    assert uso["gerou"] == 0 and uso["logins"] == [("111", "SALVA")] and not link.clicado
    assert not (dados_tmp / cr.ARQUIVO_CHAVES).exists()          # nada foi regravado


def test_chave_salva_recusada_gera_nova_atualiza_o_arquivo_e_conclui(monkeypatch, dados_tmp):
    uso = _passos_chave(monkeypatch, aceita=("NOVA",))
    link = LinkFake("10")
    chaves = [_salva(10, chave="VENCIDA"), _salva(11)]
    assert rodar(rem.processar_aluno(PaginaFake([link]), NavegadorFake(), aluno(10), chaves=chaves)) == (True, None)
    assert uso["gerou"] == 1 and link.clicado
    assert uso["logins"] == [("111", "VENCIDA"), ("222", "NOVA")]
    gravado = {c["cgm"]: c for c in ler(dados_tmp / cr.ARQUIVO_CHAVES)}
    assert gravado["10"]["chave"] == "NOVA" and gravado["10"]["cpf_responsavel"] == "222" and gravado["10"]["turma"] == "2º Ano - A"
    assert gravado["11"]["chave"] == "SALVA"                      # o resto do arquivo é preservado


def test_chave_salva_recusada_e_nova_tambem_recusada_falha_sem_laco(monkeypatch):
    uso = _passos_chave(monkeypatch, aceita=())
    ok, msg = rodar(rem.processar_aluno(PaginaFake([LinkFake("10")]), NavegadorFake(), aluno(10), chaves=[_salva(10)]))
    assert (ok, msg) == (False, "Erro ao fazer login na Área do Aluno")
    assert uso["gerou"] == 1 and len(uso["logins"]) == 2           # uma tentativa com a salva, uma com a nova


def test_falha_na_confirmacao_com_chave_salva_nao_gera_chave_nova(monkeypatch):
    uso = _passos_chave(monkeypatch, confirmar=False)
    ok, msg = rodar(rem.processar_aluno(PaginaFake([LinkFake("10")]), NavegadorFake(), aluno(10), chaves=[_salva(10)]))
    assert (ok, msg) == (False, "Erro ao confirmar matrícula") and uso["gerou"] == 0 and len(uso["logins"]) == 1


def test_chave_salva_ja_matriculado_conta_como_sucesso(monkeypatch):
    _passos_chave(monkeypatch, confirmar="JA_MATRICULADO")
    assert rodar(rem.processar_aluno(PaginaFake(), NavegadorFake(), aluno(10), chaves=[_salva(10)])) == (True, None)


def test_aluno_sem_chave_salva_gera_na_hora_e_nao_grava(monkeypatch, dados_tmp):
    uso = _passos_chave(monkeypatch)
    chaves = [_salva(99)]
    assert rodar(rem.processar_aluno(PaginaFake([LinkFake("10")]), NavegadorFake(), aluno(10), chaves=chaves)) == (True, None)
    assert uso["gerou"] == 1 and uso["logins"] == [("222", "NOVA")] and chaves == [_salva(99)]
    assert not (dados_tmp / cr.ARQUIVO_CHAVES).exists()


@pytest.mark.parametrize("salva", [_salva(10, cpf=None), _salva(10, chave="")])
def test_registro_salvo_incompleto_e_ignorado(monkeypatch, salva):
    uso = _passos_chave(monkeypatch)
    assert rodar(rem.processar_aluno(PaginaFake([LinkFake("10")]), NavegadorFake(), aluno(10), chaves=[salva])) == (True, None)
    assert uso["gerou"] == 1 and uso["logins"] == [("222", "NOVA")]


def test_erro_ao_gravar_a_chave_nova_nao_derruba_a_rematricula(monkeypatch):
    _passos_chave(monkeypatch, aceita=("NOVA",))

    def quebra(_c):
        raise OSError("disco cheio")

    monkeypatch.setattr(cr, "salvar_chaves", quebra)
    assert rodar(rem.processar_aluno(PaginaFake([LinkFake("10")]), NavegadorFake(), aluno(10), chaves=[_salva(10)])) == (True, None)


def test_orquestracao_carrega_as_chaves_e_repassa_para_cada_aluno(monkeypatch, dados_tmp):
    cr.salvar_chaves([_salva(2)])
    vistos = []
    _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(2)]})

    async def _processar(_p, _b, al, chaves=None):
        vistos.append(chaves)
        return (True, None)

    monkeypatch.setattr(rem, "processar_aluno", _processar)
    rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert vistos == [[_salva(2)]]


def test_ignorar_chaves_salvas_nao_le_o_arquivo(monkeypatch, dados_tmp):
    (dados_tmp / cr.ARQUIVO_CHAVES).write_bytes(b"[{ruim")       # nem seria lido
    vistos = []
    _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(2)]})

    async def _processar(_p, _b, al, chaves=None):
        vistos.append(chaves)
        return (True, None)

    monkeypatch.setattr(rem, "processar_aluno", _processar)
    rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s", usar_chaves_salvas=False))
    assert vistos == [None]


def test_arquivo_de_chaves_ilegivel_nao_impede_a_rematricula_e_nao_e_tocado(monkeypatch, dados_tmp):
    (dados_tmp / cr.ARQUIVO_CHAVES).write_bytes(b"[{ruim")
    vistos = []
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(2)]})

    async def _processar(_p, _b, al, chaves=None):
        vistos.append(chaves)
        return (True, None)

    monkeypatch.setattr(rem, "processar_aluno", _processar)
    r = rodar(rem.rematricular_via_login(turmas_alvo=["2º Ano"], login="l", senha="s"))
    assert vistos == [None] and r["total_sucessos"] == 1
    assert (dados_tmp / cr.ARQUIVO_CHAVES).read_bytes() == b"[{ruim"

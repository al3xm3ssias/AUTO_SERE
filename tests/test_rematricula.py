"""Testes de src/automacao/rematricula.py.

Os trechos de JavaScript rodam num Chromium real sobre HTML local (pulados se
o navegador não estiver instalado); o restante usa páginas simuladas.
"""

import asyncio
import json

import pytest

from automacao import rematricula as rem
from comum import arquivos_json, paths

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

    async def _processar(_p, _b, al):
        estado["chamadas"].append(al["cgm"])
        fila = resultados.get(al["cgm"], [])
        efeito = fila.pop(0) if fila else (True, None)
        if isinstance(efeito, BaseException):
            raise efeito
        return efeito

    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "selecionar_turma", _selecionar)
    monkeypatch.setattr(rem, "processar_aluno", _processar)
    return estado


def _rodar_turma(alunos, sucessos=None, erros=None, historico=None):
    sucessos = [] if sucessos is None else sucessos
    erros = [] if erros is None else erros
    historico = [] if historico is None else historico
    r = rodar(asyncio.wait_for(
        rem.processar_turma(NavegadorFake(), "2º Ano - A", alunos, sucessos, erros, historico, "l", "s"), 5
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

    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "listar_secao_turmas", _listar)
    monkeypatch.setattr(rem, "selecionar_turma", _selecionar)
    monkeypatch.setattr(rem, "obter_alunos_matriculados", _obter)

    res = {k: list(v) for k, v in (resultados or {}).items()}

    async def _processar(_p, _b, al):
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
    _nav, est = _orquestrar(monkeypatch, {}, {})
    rodar(rem.rematricular_via_login(turmas_alvo=["X"]))
    assert est["logins"][0] == ("login_sere", "senha_sere")     # stub de comum.credenciais do sandbox


def test_navegador_e_headless_configuraveis_com_padrao_igual_ao_original(monkeypatch, dados_tmp):
    _nav, est = _orquestrar(monkeypatch, {}, {})
    pw = est["ctx"].pw
    rodar(rem.rematricular_via_login(turmas_alvo=["X"], login="l", senha="s"))
    assert pw.chromium.headless is False and pw.firefox.headless is None   # padrão: Chromium visível

    rodar(rem.rematricular_via_login(turmas_alvo=["X"], login="l", senha="s", navegador="firefox", headless=True))
    assert pw.firefox.headless is True

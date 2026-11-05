"""Testes de src/automacao/chaves_responsavel.py (persistência pura e gerador com sessão simulada)."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from src.automacao import chaves_responsavel as cr
from src.automacao import rematricula as rem
from src.comum import paths


@pytest.fixture(autouse=True)
def dados_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)

    async def _sem_espera(*_a, **_k):
        return None

    monkeypatch.setattr(cr.asyncio, "sleep", _sem_espera)
    return tmp_path


def rodar(coro):
    return asyncio.run(asyncio.wait_for(coro, 5))


def aluno(cgm, nome=None):
    return {"cgm": str(cgm), "Nome": nome or f"Aluno {cgm}", "Data Nasc.": "01/01/2019"}


def ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


# ----------------------------------------------------------
# persistência e regras puras
# ----------------------------------------------------------

def test_arquivo_inexistente_vira_lista_vazia_e_nome_e_o_do_script_avulso(dados_tmp):
    assert cr.carregar_chaves() == []
    assert cr.caminho_chaves() == dados_tmp / "chave_responsavel.json"


def test_salvar_e_carregar_ida_e_volta_sem_temporarios(dados_tmp):
    cr.salvar_chaves([{"cgm": "1", "chave": "K"}])
    assert cr.carregar_chaves() == [{"cgm": "1", "chave": "K"}]
    assert [p for p in dados_tmp.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.parametrize("conteudo", [b"[{ruim", b'{"nao": "lista"}'])
def test_arquivo_ilegivel_ou_com_tipo_errado_levanta_e_nao_e_alterado(dados_tmp, conteudo):
    (dados_tmp / cr.ARQUIVO_CHAVES).write_bytes(conteudo)
    with pytest.raises(cr.ChavesCorrompidasError):
        cr.carregar_chaves()
    assert (dados_tmp / cr.ARQUIVO_CHAVES).read_bytes() == conteudo


def test_arquivo_do_script_avulso_e_lido_como_esta(dados_tmp):
    legado = [{"cgm": "123", "nome": "Ana", "turma": "2º Ano - A", "data_nascimento": "01/01/2019",
               "cpf_responsavel": "12345678901", "chave": "ABC", "timestamp": "2026-11-02T10:00:00"}]
    (dados_tmp / cr.ARQUIVO_CHAVES).write_text(json.dumps(legado), encoding="utf-8")
    assert cr.chave_utilizavel(cr.buscar_chave(cr.carregar_chaves(), "123"))


def test_buscar_ignora_lixo_e_compara_cgm_como_texto():
    chaves = ["lixo", None, {"sem": "cgm"}, {"cgm": 55, "chave": "K", "cpf_responsavel": "1"}]
    assert cr.buscar_chave(chaves, " 55 ")["chave"] == "K"
    assert cr.buscar_chave(chaves, "56") is None
    assert cr.buscar_chave(None, "1") is None


@pytest.mark.parametrize("registro,esperado", [
    ({"chave": "K", "cpf_responsavel": "123"}, True),
    ({"chave": "K", "cpf_responsavel": None}, False),      # sem CPF não dá para entrar na Área do Aluno
    ({"chave": "", "cpf_responsavel": "123"}, False),
    ({"chave": "  ", "cpf_responsavel": "123"}, False),
    (None, False),
    ("texto", False),
])
def test_chave_utilizavel_exige_chave_e_cpf(registro, esperado):
    assert cr.chave_utilizavel(registro) is esperado


def test_validade_em_horas():
    agora = datetime(2026, 11, 3, 12, 0)
    base = {"chave": "K", "cpf_responsavel": "1"}
    recente = {**base, "timestamp": (agora - timedelta(hours=2)).isoformat()}
    velha = {**base, "timestamp": (agora - timedelta(hours=30)).isoformat()}
    assert cr.chave_utilizavel(recente, 24, agora) and not cr.chave_utilizavel(velha, 24, agora)
    assert cr.chave_utilizavel(velha, None, agora)                       # sem prazo informado: idade não é conferida
    assert not cr.chave_utilizavel({**base, "timestamp": "ontem"}, 24, agora)   # timestamp ilegível: conservador
    assert not cr.chave_utilizavel(base, 24, agora)


def test_registrar_chave_substitui_por_cgm_e_preserva_o_resto():
    chaves = ["lixo", {"cgm": "1", "chave": "velha"}, {"cgm": "2", "chave": "outra"}]
    r = cr.registrar_chave(chaves, aluno(1), "2º Ano - A", "nova", "999", agora=datetime(2026, 11, 3, 9, 0))
    assert r == {"cgm": "1", "nome": "Aluno 1", "turma": "2º Ano - A", "data_nascimento": "01/01/2019",
                 "cpf_responsavel": "999", "chave": "nova", "timestamp": "2026-11-03T09:00:00"}
    assert [c["chave"] for c in chaves if isinstance(c, dict)] == ["outra", "nova"] and "lixo" in chaves


# ----------------------------------------------------------
# _gerar_chave_do_aluno
# ----------------------------------------------------------

def test_gerar_chave_do_aluno_volta_para_a_lista_so_quando_deu_certo(monkeypatch):
    voltou = []

    async def voltar(_p):
        voltou.append(1)

    monkeypatch.setattr(rem, "voltar_para_turma", voltar)

    async def ok(_p, _a):
        return "K", "123", None

    monkeypatch.setattr(rem, "_abrir_ficha_gerar_chave", ok)
    assert rodar(cr._gerar_chave_do_aluno(object(), aluno(1))) == ("K", "123", None) and voltou == [1]

    async def falha(_p, _a):
        return None, None, "CPF do responsável não encontrado"   # a própria função já voltou

    monkeypatch.setattr(rem, "_abrir_ficha_gerar_chave", falha)
    assert rodar(cr._gerar_chave_do_aluno(object(), aluno(1)))[2] == "CPF do responsável não encontrado"
    assert voltou == [1]


# ----------------------------------------------------------
# _processar_secao (recuperação de sessão)
# ----------------------------------------------------------

class PaginaFake:
    fechada = False

    async def close(self):
        self.fechada = True


def _secao(monkeypatch, *, abrir=None, selecionar=True, efeitos=None):
    """efeitos: {cgm: [(chave, cpf, erro) | exceção, ...]}; esgotado => ('K<cgm>', 'CPF', None)."""
    estado = {"aberturas": 0, "chamadas": []}
    abrir = list(abrir or [])
    efeitos = {k: list(v) for k, v in (efeitos or {}).items()}

    async def _abrir(_b, _l, _s):
        estado["aberturas"] += 1
        return PaginaFake() if (abrir.pop(0) if abrir else True) else None

    async def _selecionar(_p, _t):
        return selecionar

    async def _gerar(_p, al):
        estado["chamadas"].append(al["cgm"])
        fila = efeitos.get(al["cgm"], [])
        efeito = fila.pop(0) if fila else (f"K{al['cgm']}", "CPF", None)
        if isinstance(efeito, BaseException):
            raise efeito
        return efeito

    async def _navegar(_p):
        return True

    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "navegar_para_por_turmas", _navegar)
    monkeypatch.setattr(rem, "selecionar_turma", _selecionar)
    monkeypatch.setattr(cr, "_gerar_chave_do_aluno", _gerar)
    return estado


def _rodar_secao(alunos, chaves=None, ja_na_secao=False):
    resumo = {"geradas": 0, "falhas": []}
    chaves = [] if chaves is None else chaves
    sessao = rem.SessaoSere(object(), "l", "s")
    r = rodar(cr._processar_secao(sessao, "2º Ano - A", alunos, chaves, resumo, ja_na_secao=ja_na_secao))
    return r, chaves, resumo


def test_secao_grava_a_cada_chave_gerada(monkeypatch, dados_tmp):
    _secao(monkeypatch)
    r, chaves, resumo = _rodar_secao([aluno(1), aluno(2)])
    assert r is True and resumo["geradas"] == 2 and resumo["falhas"] == []
    assert [c["cgm"] for c in ler(dados_tmp / cr.ARQUIVO_CHAVES)] == ["1", "2"]
    assert chaves[0]["turma"] == "2º Ano - A" and chaves[0]["chave"] == "K1" and chaves[0]["cpf_responsavel"] == "CPF"


def test_falha_comum_vai_para_o_resumo_nao_salva_chave_e_segue(monkeypatch, dados_tmp):
    _secao(monkeypatch, efeitos={"1": [(None, None, "CPF do responsável não encontrado")]})
    r, chaves, resumo = _rodar_secao([aluno(1), aluno(2)])
    assert r is True and [c["cgm"] for c in chaves] == ["2"]
    assert resumo["falhas"] == [{"cgm": "1", "nome": "Aluno 1", "turma": "2º Ano - A",
                                 "erro": "CPF do responsável não encontrado"}]


def test_erro_critico_uma_vez_reinicia_e_conclui_o_mesmo_aluno(monkeypatch):
    est = _secao(monkeypatch, efeitos={"1": [rem.ErroReiniciarNavegador("travou")]})
    r, chaves, resumo = _rodar_secao([aluno(1), aluno(2)])
    assert r is True and est["chamadas"] == ["1", "1", "2"] and est["aberturas"] == 2
    assert [c["cgm"] for c in chaves] == ["1", "2"] and resumo["falhas"] == []


def test_erro_critico_tres_vezes_desiste_do_aluno_e_avanca(monkeypatch):
    est = _secao(monkeypatch, efeitos={"1": [rem.ErroReiniciarNavegador("x")] * 3})
    r, chaves, resumo = _rodar_secao([aluno(1), aluno(2)])
    assert r is True and est["chamadas"] == ["1", "1", "1", "2"] and [c["cgm"] for c in chaves] == ["2"]
    assert "Erro crítico após 3 tentativas" in resumo["falhas"][0]["erro"]


def test_login_sempre_falhando_nao_fica_em_loop_infinito(monkeypatch):
    est = _secao(monkeypatch, abrir=[False] * 50)
    r, chaves, _ = _rodar_secao([aluno(1)])
    assert r is False and chaves == [] and est["aberturas"] == rem.MAX_FALHAS_SESSAO


def test_turma_nao_encontrada_abandona_a_secao(monkeypatch):
    est = _secao(monkeypatch, selecionar=False)
    r, chaves, _ = _rodar_secao([aluno(1)])
    assert r is False and chaves == [] and est["chamadas"] == []


# ----------------------------------------------------------
# gerar_chaves_via_login (orquestração)
# ----------------------------------------------------------

class _Nav:
    fechado = False

    async def close(self):
        self.fechado = True


class _Lancador:
    def __init__(self, nav):
        self.nav, self.headless = nav, None

    async def launch(self, headless=True):
        self.headless = headless
        return self.nav


class _PW:
    def __init__(self, nav):
        self.chromium = _Lancador(nav)


class _Ctx:
    def __init__(self, nav):
        self.pw = _PW(nav)

    async def __aenter__(self):
        return self.pw

    async def __aexit__(self, *_a):
        return False


def _orquestrar(monkeypatch, secoes, alunos_por_secao, falhar=()):
    nav = _Nav()
    ctx = _Ctx(nav)
    monkeypatch.setattr(cr, "async_playwright", lambda: ctx)
    est = {"aberta": None, "geradas": [], "ctx": ctx, "aberturas": 0}

    async def _abrir(_b, _l, _s):
        est["aberturas"] += 1
        return PaginaFake()

    async def _navegar(_p):
        return True

    async def _listar(_p, turma):
        return secoes.get(turma, [])

    async def _selecionar(_p, secao):
        est["aberta"] = secao
        return True

    async def _obter(_p):
        return alunos_por_secao.get(est["aberta"], [])

    async def _secao(_sessao, secao, alunos, chaves, resumo, ja_na_secao=False):
        est["ja_na_secao"] = ja_na_secao
        for a in alunos:
            est["geradas"].append(a["cgm"])
            if a["cgm"] in falhar:
                resumo["falhas"].append({"cgm": a["cgm"], "nome": a["Nome"], "turma": secao, "erro": "x"})
                continue
            cr.registrar_chave(chaves, a, secao, f"K{a['cgm']}", "CPF")
            cr.salvar_chaves(chaves)
            resumo["geradas"] += 1
        return True

    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    monkeypatch.setattr(rem, "navegar_para_por_turmas", _navegar)
    monkeypatch.setattr(rem, "listar_secao_turmas", _listar)
    monkeypatch.setattr(rem, "selecionar_turma", _selecionar)
    monkeypatch.setattr(rem, "obter_alunos_matriculados", _obter)
    monkeypatch.setattr(cr, "_processar_secao", _secao)
    return nav, est


def _gerar(**kw):
    return rodar(cr.gerar_chaves_via_login(login="l", senha="s", **kw))


def test_gera_so_para_quem_nao_tem_chave_utilizavel_nem_ja_rematriculou(monkeypatch, dados_tmp):
    cr.salvar_chaves([{"cgm": "1", "chave": "K1", "cpf_responsavel": "CPF"},       # tem chave: pula
                      {"cgm": "2", "chave": "K2", "cpf_responsavel": None}])        # sem CPF: não vale, gera de novo
    rem.salvar_resultados([{"cgm": "3", "nome": "x", "turma": "T"}], [], [])        # já rematriculado: pula
    nav, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1), aluno(2), aluno(3), aluno(4)]})
    r = _gerar(turmas_alvo=["2º Ano"])
    assert est["geradas"] == ["2", "4"] and r["geradas"] == 2 and r["falhas"] == []
    por_cgm = {c["cgm"]: c for c in ler(dados_tmp / cr.ARQUIVO_CHAVES)}
    assert set(por_cgm) == {"1", "2", "4"} and por_cgm["1"]["chave"] == "K1" and por_cgm["2"]["chave"] == "K2"
    assert r["total_chaves"] == 3 and r["arquivo"] == dados_tmp / cr.ARQUIVO_CHAVES and nav.fechado


def test_regenerar_gera_de_novo_para_quem_ja_tem_chave(monkeypatch):
    cr.salvar_chaves([{"cgm": "1", "chave": "velha", "cpf_responsavel": "CPF"}])
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1), aluno(2)]})
    _gerar(turmas_alvo=["2º Ano"], regenerar=True)
    assert est["geradas"] == ["1", "2"]
    assert {c["cgm"]: c["chave"] for c in cr.carregar_chaves()} == {"1": "K1", "2": "K2"}


def test_validade_gera_de_novo_a_chave_vencida(monkeypatch):
    velho = (datetime.now() - timedelta(hours=48)).isoformat()
    novo = datetime.now().isoformat()
    cr.salvar_chaves([{"cgm": "1", "chave": "K", "cpf_responsavel": "C", "timestamp": velho},
                      {"cgm": "2", "chave": "K", "cpf_responsavel": "C", "timestamp": novo}])
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1), aluno(2)]})
    _gerar(turmas_alvo=["2º Ano"], validade_horas=24)
    assert est["geradas"] == ["1"]


def test_modo_teste_gera_so_o_primeiro_pendente_de_cada_secao(monkeypatch):
    cr.salvar_chaves([{"cgm": "1", "chave": "K", "cpf_responsavel": "C"}])
    _, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"]},
        {"2º Ano - A": [aluno(1), aluno(2), aluno(3)], "2º Ano - B": [aluno(7), aluno(8)]},
    )
    _gerar(turmas_alvo=["2º Ano"], modo_teste=True)
    assert est["geradas"] == ["2", "7"]


def test_secao_sem_pendentes_e_turma_sem_secoes_nao_quebram(monkeypatch):
    cr.salvar_chaves([{"cgm": "1", "chave": "K", "cpf_responsavel": "C"}])
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1)]})
    r = _gerar(turmas_alvo=["2º Ano", "Inexistente"])
    assert est["geradas"] == [] and r["total_chaves"] == 1


def test_falhas_aparecem_no_resumo(monkeypatch):
    _, est = _orquestrar(monkeypatch, {"2º Ano": ["2º Ano - A"]}, {"2º Ano - A": [aluno(1), aluno(2)]}, falhar={"2"})
    r = _gerar(turmas_alvo=["2º Ano"])
    assert r["geradas"] == 1 and [f["cgm"] for f in r["falhas"]] == ["2"]


@pytest.mark.parametrize("arquivo", [cr.ARQUIVO_CHAVES, rem.ARQUIVO_SUCESSO])
def test_arquivo_ilegivel_aborta_antes_de_abrir_o_navegador(monkeypatch, dados_tmp, arquivo):
    (dados_tmp / arquivo).write_bytes(b"[{ruim")

    def nao_deveria(*_a, **_k):
        raise AssertionError("não devia abrir o navegador")

    monkeypatch.setattr(cr, "async_playwright", nao_deveria)
    with pytest.raises(Exception, match="ilegível"):
        _gerar()
    assert (dados_tmp / arquivo).read_bytes() == b"[{ruim"


def test_credenciais_padrao_e_navegador_headless_configuraveis(monkeypatch):
    from src.comum import credenciais
    monkeypatch.setattr(credenciais, "LOGIN", "login_sere")
    monkeypatch.setattr(credenciais, "SENHA", "senha_sere")
    _, est = _orquestrar(monkeypatch, {}, {})
    logins = []

    async def _abrir(_b, login, senha):
        logins.append((login, senha))
        return PaginaFake()

    monkeypatch.setattr(rem, "_abrir_por_turmas", _abrir)
    rodar(cr.gerar_chaves_via_login(turmas_alvo=["X"]))
    assert logins == [("login_sere", "senha_sere")] and est["ctx"].pw.chromium.headless is False   # padrão: visível
    rodar(cr.gerar_chaves_via_login(turmas_alvo=["X"], login="l", senha="s", headless=True))
    assert est["ctx"].pw.chromium.headless is True


def test_gerar_chaves_usa_uma_unica_sessao_e_continua_da_secao_aberta(monkeypatch, dados_tmp):
    nav, est = _orquestrar(
        monkeypatch, {"2º Ano": ["2º Ano - A", "2º Ano - B"], "3º Ano": ["3º Ano - A"]},
        {"2º Ano - A": [aluno(1)], "2º Ano - B": [aluno(2)], "3º Ano - A": [aluno(3)]},
    )
    _gerar(turmas_alvo=["2º Ano", "3º Ano"])
    assert est["aberturas"] == 1 and est["geradas"] == ["1", "2", "3"]   # um login só, 3 seções
    assert est["ja_na_secao"] is True                                    # já na lista de alunos: sem logar nem selecionar de novo


def test_secao_ja_na_secao_nao_loga_nem_seleciona_de_novo(monkeypatch, dados_tmp):
    est = _secao(monkeypatch)
    r, chaves, resumo = _rodar_secao([aluno(1), aluno(2)], ja_na_secao=True)
    assert r is True and resumo["geradas"] == 2 and est["aberturas"] == 0

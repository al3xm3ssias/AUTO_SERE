"""Testes de src/automacao/pre_matricula.py (sem rede: Playwright é simulado)."""

import asyncio
import csv
import json

import pytest

from automacao import pre_matricula as pm
from comum import paths

ESCOLA = "ESCOLA MUNICIPAL PROFª JUDITH MACEDO SILVEIRA"
OUTRA = "ESCOLA MUNICIPAL OUTRA"


# ----------------------------------------------------------
# infraestrutura de teste
# ----------------------------------------------------------

@pytest.fixture(autouse=True)
def dados_tmp(tmp_path, monkeypatch):
    """Toda a pasta de dados do ano aponta para tmp_path; sleeps viram no-op."""
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)
    monkeypatch.setattr(paths, "ano_atual", lambda: 2026)

    async def _sem_espera(*_a, **_k):
        return None

    monkeypatch.setattr(pm.asyncio, "sleep", _sem_espera)
    return tmp_path


def rodar(coro):
    return asyncio.run(coro)


def opcao(n, escola, situacao="", motivo="", obs=""):
    return {
        "opcao": n, "escola": escola, "situacao": situacao,
        "motivo_cancelamento": motivo, "observacao": obs,
    }


def cadastro(cpf, opcoes, resp="RESP FULANO", tel="(42) 99999-0000", end=None):
    return {
        "cpf": cpf,
        "nome_aluno": "ALUNO " + cpf[-2:],
        "nome_responsavel": resp,
        "telefone": tel,
        "email": "r@x.com",
        "endereco": end or "RUA A 10 CENTRO PONTA GROSSA PR 84000-000",
        "criterios": [],
        "escolas_escolhidas": {"turma": "1º ANO", "opcoes": opcoes},
    }


class _Item:
    def __init__(self, text=None, attrs=None, tds=None, page=None, on_click=None):
        self.text, self.attrs, self.tds = text, attrs or {}, tds or []
        self._on_click = on_click

    async def inner_text(self):
        return self.text

    async def get_attribute(self, k):
        return self.attrs.get(k)

    async def query_selector_all(self, _sel):
        return self.tds

    def locator(self, _sel):
        return self

    async def click(self):
        if self._on_click:
            self._on_click()


class _Loc:
    def __init__(self, page, sel):
        self.p, self.sel = page, sel

    async def count(self):
        return self.p._count(self.sel)

    async def inner_text(self):
        v = self.p._text(self.sel)
        if v is None:
            raise RuntimeError("sem elemento " + self.sel)
        return v

    async def is_visible(self):
        return self.p._count(self.sel) > 0

    async def is_disabled(self):
        return False

    async def wait_for(self, **_k):
        return None

    async def click(self):
        return None

    async def all_inner_texts(self):
        rec = self.p.cad.get(self.p.cpf_atual, {})
        return rec.get("_criterios", []) if self.sel == "div#dCriterios0 li" else []

    def nth(self, i):
        return self.p._escola_item(i)


class _Kb:
    def __init__(self, page):
        self.p = page

    async def press(self, _k):
        if self.p.url == pm.LOGIN_URL:
            self.p.logado = self.p.login_ok


class FakePage:
    """
    Simula o portal de pré-matrícula.
      cad:    {cpf: {seletor: texto, "_criterios": [...]}}  (consulta por CPF)
      turmas: {label: [ {pos,nome,cpf,tipo,pontuacao,id}, ... ]}
    """

    def __init__(self, cad=None, turmas=None, login_ok=True, escolas=("Judith Macedo Silveira",)):
        self.cad, self.turmas = cad or {}, turmas or {}
        self.login_ok, self.logado = login_ok, False
        self.escolas = list(escolas)
        self.url = ""
        self.cpf_atual = None
        self.turma_atual = None
        self.escola_ok = False
        self.keyboard = _Kb(self)
        self.shots = []
        self.consultas = []

    # navegação
    async def goto(self, url, **_k):
        self.url = url

    async def wait_for_load_state(self, *_a, **_k):
        return None

    async def fill(self, sel, val):
        if sel == "input#cpfAluno":
            self.cpf_atual = val
            self.consultas.append(val)

    async def type(self, *_a, **_k):
        return None

    async def click(self, *_a, **_k):
        return None

    async def screenshot(self, path, **_k):
        from pathlib import Path
        Path(path).write_bytes(b"png")
        self.shots.append(path)

    async def wait_for_selector(self, sel, **_k):
        if sel == "div#divCadastros":
            if self.cpf_atual in self.cad:
                return
            raise pm.PWTimeout("sem resultado")
        if sel == "table#tableIntencoes tbody tr":
            if self.turmas.get(self.turma_atual):
                return
            raise pm.PWTimeout("sem linhas")
        return None

    async def select_option(self, _sel, val):
        self.turma_atual = val

    async def eval_on_selector_all(self, _sel, _js):
        return [{"value": "", "label": "Selecione"}] + [
            {"value": t, "label": t} for t in self.turmas
        ]

    async def query_selector_all(self, _sel):
        rows = []
        for r in self.turmas.get(self.turma_atual, []):
            tds = [_Item(text=str(r[k])) for k in ("pos", "nome", "cpf", "tipo", "pontuacao")]
            rows.append(_Item(attrs={"id": r.get("id")}, tds=tds))
        return rows

    def locator(self, sel):
        return _Loc(self, sel)

    # helpers do locator
    def _escola_item(self, i):
        def marca():
            self.escola_ok = True
        return _Item(text=self.escolas[i], on_click=marca)

    def _count(self, sel):
        if sel == "#matricula":
            return 1 if (self.url == pm.LOGIN_URL and not self.logado) else 0
        if sel == "#listaEscolas a":
            return len(self.escolas)
        if sel.startswith("span#e") and sel.endswith("0") and len(sel) == 8:
            return 1 if sel in self.cad.get(self.cpf_atual, {}) else 0
        return 0

    def _text(self, sel):
        return self.cad.get(self.cpf_atual, {}).get(sel)


def pagina_cad(cpf, opcoes, nome="ALUNO X", resp="Resp Fulano"):
    """Monta o dict de seletores que consultar_cpf lê, a partir das opções."""
    d = {
        "h5#dNomeAluno": nome, "span#dNomeResponsavel0": resp,
        "span#dTelefoneResponsavel0": "(42) 99999-0000", "span#dEmailResponsavel0": "R@X.com",
        "span#dLogradouro0": "Rua A", "span#dNumero0": "10", "span#dBairro0": "Centro",
        "span#dMunicipio0": "Ponta Grossa", "span#dUF0": "PR", "span#dCEP0": "84000-000",
        "span#turma0": "1º Ano",
    }
    for n, (escola, sit) in enumerate(opcoes, start=1):
        d[f"span#e{n}0"] = escola
        if sit:
            d[f"span#status{n}0"] = sit
    return d


# ----------------------------------------------------------
# mesclar_turmas_intencao
# ----------------------------------------------------------

def test_mesclar_novo_existente_e_ausente_com_presuncao():
    antigas = {
        "1º Ano": [
            {"cpf": "111", "nome": "Velho", "pontuacao": 1, "presente_na_ultima_coleta": True},
            {"cpf": "222", "nome": "Some", "presente_na_ultima_coleta": True},
        ],
        "2º Ano": [{"cpf": "333", "nome": "Turma ausente", "presente_na_ultima_coleta": True}],
    }
    novas = {"1º Ano": [
        {"cpf": "111", "nome": "Velho Atualizado", "pontuacao": 9},
        {"cpf": "444", "nome": "Novo"},
    ]}

    r = pm.mesclar_turmas_intencao(antigas, novas)
    por_cpf = {a["cpf"]: a for a in r["1º Ano"]}

    assert por_cpf["111"]["nome"] == "Velho Atualizado" and por_cpf["111"]["pontuacao"] == 9
    assert por_cpf["111"]["presente_na_ultima_coleta"] is True
    assert por_cpf["444"]["presente_na_ultima_coleta"] is True
    # quem sumiu é mantido e ganha a situação PRESUNTIVA
    assert por_cpf["222"]["presente_na_ultima_coleta"] is False
    assert por_cpf["222"]["situacao"] == "Cancelado"
    assert por_cpf["222"]["motivo_cancelamento"] == pm.MOTIVO_PRESUNTIVO
    # turma que nem veio na coleta é preservada intacta
    assert r["2º Ano"][0]["presente_na_ultima_coleta"] is True
    assert "situacao" not in r["2º Ano"][0]


def test_mesclar_nao_sobrescreve_situacao_real_nem_repete_presuncao():
    antigas = {"T": [
        {"cpf": "1", "presente_na_ultima_coleta": True, "situacao": "MATRICULADO."},
        {"cpf": "2", "presente_na_ultima_coleta": False, "situacao": "CANCELADO. MOTIVO: X"},
    ]}
    r = pm.mesclar_turmas_intencao(antigas, {"T": []})
    por = {a["cpf"]: a for a in r["T"]}
    assert por["1"]["situacao"] == "MATRICULADO."
    assert por["2"]["situacao"] == "CANCELADO. MOTIVO: X"
    assert "motivo_cancelamento" not in por["1"]


def test_mesclar_sem_cpf_usa_tr_id_ou_nome():
    r = pm.mesclar_turmas_intencao({}, {"T": [{"cpf": "", "tr_id": "r7", "nome": "A"}, {"cpf": "", "nome": "B"}]})
    assert len(r["T"]) == 2


# ----------------------------------------------------------
# persistência: atômica e sem apagar histórico
# ----------------------------------------------------------

def test_carregar_inexistente_devolve_base_vazia():
    d = pm.carregar_pre_matricula()
    assert d["turmas_intencao"] == {} and d["cadastros"] == {}


def test_salvar_e_recarregar_e_sem_temporarios(dados_tmp):
    d = pm.carregar_pre_matricula()
    d["cadastros"]["1"] = {"nome_aluno": "É Ção"}
    pm.salvar_pre_matricula(d)
    assert pm.carregar_pre_matricula()["cadastros"]["1"]["nome_aluno"] == "É Ção"
    assert pm.carregar_pre_matricula()["atualizado_em"]
    assert [p.name for p in dados_tmp.iterdir() if p.name.endswith(".tmp")] == []


def test_json_corrompido_levanta_erro_e_nao_toca_no_arquivo(dados_tmp):
    arq = pm.caminho_pre_matricula()
    lixo = b'{"turmas_intencao": {"1": [ {"cpf": "1"'  # truncado
    arq.write_bytes(lixo)
    with pytest.raises(pm.PreMatriculaCorrompidaError):
        pm.carregar_pre_matricula()
    assert arq.read_bytes() == lixo  # byte a byte


def test_falha_na_gravacao_preserva_arquivo_anterior(dados_tmp, monkeypatch):
    d = pm.carregar_pre_matricula()
    d["cadastros"]["1"] = {"x": 1}
    pm.salvar_pre_matricula(d)
    antes = pm.caminho_pre_matricula().read_bytes()

    def quebra(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(pm.json, "dump", quebra)
    with pytest.raises(OSError):
        pm.salvar_pre_matricula({"cadastros": {}, "turmas_intencao": {}})

    assert pm.caminho_pre_matricula().read_bytes() == antes
    assert [p.name for p in dados_tmp.iterdir() if p.name.endswith(".tmp")] == []


def test_etapa_coleta_nao_apaga_historico_se_arquivo_corrompido(dados_tmp):
    arq = pm.caminho_pre_matricula()
    arq.write_bytes(b"{ruim")
    page = FakePage(turmas={"1º Ano": [{"pos": 1, "nome": "A", "cpf": "1", "tipo": "", "pontuacao": 1, "id": "r1"}]})
    with pytest.raises(pm.PreMatriculaCorrompidaError):
        rodar(pm.etapa_coleta(page))
    assert arq.read_bytes() == b"{ruim"


# ----------------------------------------------------------
# escolha da opção da escola (correção da etapa 4)
# ----------------------------------------------------------

def test_opcao_da_escola_pega_a_da_escola_e_nao_a_primeira():
    ops = [
        opcao(1, OUTRA, "CANCELADO. MOTIVO: DESISTIU"),
        opcao(2, ESCOLA, "MATRICULADO. OBSERVAÇÃO:"),
    ]
    assert pm.opcao_da_escola_alvo(ops)["opcao"] == 2


def test_opcao_da_escola_aguardando_devolve_none_e_nao_a_de_outra_escola():
    ops = [opcao(1, OUTRA, "CANCELADO. MOTIVO: X"), opcao(2, ESCOLA, "")]
    assert pm.opcao_da_escola_alvo(ops) is None


def test_opcao_da_escola_ausente_cai_no_comportamento_antigo():
    ops = [opcao(1, OUTRA, ""), opcao(2, "OUTRA 2", "MATRICULADO")]
    assert pm.opcao_da_escola_alvo(ops)["opcao"] == 2
    assert pm.opcao_da_escola_alvo([]) is None


def test_etapa4_confirma_matriculado_aqui_mesmo_cancelado_em_outra_escola(dados_tmp):
    """Cenário real: opção 1 cancelada (outra escola), opção 2 matriculada aqui."""
    base = pm.carregar_pre_matricula()
    base["turmas_intencao"] = {"3º Ano": [
        {"cpf": "100", "nome": "Aluno 100", "presente_na_ultima_coleta": False,
         "situacao": "Cancelado", "motivo_cancelamento": pm.MOTIVO_PRESUNTIVO},
        {"cpf": "200", "nome": "Aluno 200", "presente_na_ultima_coleta": False,
         "situacao": "Cancelado", "motivo_cancelamento": pm.MOTIVO_PRESUNTIVO},
        {"cpf": "300", "nome": "Aluno 300", "presente_na_ultima_coleta": True},   # não é pendente
    ]}
    pm.salvar_pre_matricula(base)

    page = FakePage(cad={
        "100": pagina_cad("100", [(OUTRA, "Cancelado. Motivo: Desistiu (obs A)"),
                                  (ESCOLA, "Matriculado. Observação:")]),
        "200": pagina_cad("200", [(ESCOLA, "Cancelado. Motivo: Responsável desistiu da vaga (fica onde está)")]),
    })
    resumo = rodar(pm.etapa_verificar_pendentes(page))

    assert resumo == {"total_pendentes": 2, "confirmados": 2, "sem_resposta": []}
    assert page.consultas == ["100", "200"]  # 300 não foi reconsultado

    d = pm.carregar_pre_matricula()
    a100, a200, a300 = d["turmas_intencao"]["3º Ano"]
    assert a100["situacao"].startswith("MATRICULADO")
    assert a100["motivo_cancelamento"] == "" and a100["observacao"] == ""  # não herda o motivo da outra escola
    assert a200["situacao"].startswith("CANCELADO")
    assert a200["motivo_cancelamento"] == "RESPONSÁVEL DESISTIU DA VAGA"
    assert a200["observacao"] == "FICA ONDE ESTÁ"
    assert "situacao" not in a300
    assert set(d["cadastros"]) == {"100", "200"}


def test_etapa4_sem_resposta_mantem_presuncao(dados_tmp):
    base = pm.carregar_pre_matricula()
    base["turmas_intencao"] = {"T": [
        {"cpf": "1", "presente_na_ultima_coleta": False, "situacao": "Cancelado",
         "motivo_cancelamento": pm.MOTIVO_PRESUNTIVO},   # CPF sem resultado no site
        {"cpf": "2", "presente_na_ultima_coleta": False, "situacao": "Cancelado",
         "motivo_cancelamento": pm.MOTIVO_PRESUNTIVO},   # aguardando (sem situação)
        {"cpf": "", "presente_na_ultima_coleta": False},  # sem CPF: nem é consultado
    ]}
    pm.salvar_pre_matricula(base)
    page = FakePage(cad={"2": pagina_cad("2", [(ESCOLA, "")])})

    resumo = rodar(pm.etapa_verificar_pendentes(page))
    assert resumo["total_pendentes"] == 2 and resumo["confirmados"] == 0
    assert sorted(resumo["sem_resposta"]) == ["1", "2"]
    d = pm.carregar_pre_matricula()
    assert all(a.get("situacao") == "Cancelado" for a in d["turmas_intencao"]["T"][:2])


def test_etapa4_sem_pendentes_nao_abre_o_site():
    page = FakePage()
    assert rodar(pm.etapa_verificar_pendentes(page)) == {
        "total_pendentes": 0, "confirmados": 0, "sem_resposta": []
    }
    assert page.consultas == []


# ----------------------------------------------------------
# reconciliar_situacoes
# ----------------------------------------------------------

def _base_com_erro_antigo():
    return {
        "turmas_intencao": {"3º Ano": [
            # gravado pelo critério antigo (1ª opção com situação)
            {"cpf": "1", "nome": "A", "situacao": "CANCELADO. MOTIVO: X", "motivo_cancelamento": "X"},
            {"cpf": "2", "nome": "B", "situacao": "MATRICULADO. OBSERVAÇÃO:"},      # já correto
            {"cpf": "3", "nome": "C", "presente_na_ultima_coleta": True},           # aguardando
            {"cpf": "4", "nome": "D"},                                              # sem cadastro
        ]},
        "cadastros": {
            "1": cadastro("1", [opcao(1, OUTRA, "CANCELADO. MOTIVO: X"), opcao(2, ESCOLA, "MATRICULADO. OBSERVAÇÃO:")]),
            "2": cadastro("2", [opcao(1, ESCOLA, "MATRICULADO. OBSERVAÇÃO:")]),
            "3": cadastro("3", [opcao(1, ESCOLA, "")]),
        },
    }


def test_reconciliar_so_relata_por_padrao():
    base = _base_com_erro_antigo()
    div = pm.reconciliar_situacoes(base)
    assert [(d["cpf"], d["situacao_correta"]) for d in div] == [("1", "MATRICULADO. OBSERVAÇÃO:")]
    assert base["turmas_intencao"]["3º Ano"][0]["situacao"].startswith("CANCELADO")  # intocado


def test_reconciliar_aplicar_corrige_sem_mexer_nos_outros():
    base = _base_com_erro_antigo()
    pm.reconciliar_situacoes(base, aplicar=True)
    a1, a2, a3, a4 = base["turmas_intencao"]["3º Ano"]
    assert a1["situacao"].startswith("MATRICULADO") and a1["motivo_cancelamento"] == ""
    assert a2["situacao"].startswith("MATRICULADO")
    assert "situacao" not in a3 and "situacao" not in a4
    assert pm.reconciliar_situacoes(base) == []  # idempotente


# ----------------------------------------------------------
# consultar_cpf / etapa_cadastro
# ----------------------------------------------------------

def test_consultar_cpf_extrai_e_normaliza_caixa():
    page = FakePage(cad={"111": pagina_cad("111", [(ESCOLA, "Cancelado. Motivo: Sem vaga (obs)"), (OUTRA, "")],
                                            nome="Maria Souza")})
    d = rodar(pm.consultar_cpf(page, "111"))
    assert d["nome_aluno"] == "MARIA SOUZA"
    assert d["email"] == "r@x.com"                      # e-mail em minúscula
    assert d["endereco"].endswith("84000-000") and d["endereco"].startswith("RUA A")
    ops = d["escolas_escolhidas"]["opcoes"]
    assert len(ops) == 2 and ops[0]["motivo_cancelamento"] == "SEM VAGA" and ops[0]["observacao"] == "OBS"


def test_consultar_cpf_sem_resultado_devolve_none_e_salva_screenshot_de_erro(dados_tmp):
    page = FakePage()
    assert rodar(pm.consultar_cpf(page, "999")) is None
    assert any("ERRO" in s for s in page.shots)
    assert (dados_tmp / "screenshots").exists()


def test_screenshot_de_sucesso_so_no_modo_analise(dados_tmp):
    page = FakePage(cad={"1": pagina_cad("1", [(ESCOLA, "")])})
    rodar(pm.consultar_cpf(page, "1", analise=False))
    assert page.shots == []
    rodar(pm.consultar_cpf(page, "1", analise=True))
    assert page.shots and all("_ok_" in s for s in page.shots)


def test_etapa_cadastro_mescla_sem_apagar_cadastros_anteriores(dados_tmp):
    base = pm.carregar_pre_matricula()
    base["cadastros"]["ANTIGO"] = {"nome_aluno": "MANTIDO"}
    pm.salvar_pre_matricula(base)

    page = FakePage(cad={"1": pagina_cad("1", [(ESCOLA, "")])})
    res = rodar(pm.etapa_cadastro(page, {"turmas": {"T": [{"cpf": "1"}, {"cpf": "2"}, {"cpf": ""}]}}))

    assert set(res) == {"1"}  # CPF 2 sem resultado; vazio ignorado
    assert set(pm.carregar_pre_matricula()["cadastros"]) == {"ANTIGO", "1"}


# ----------------------------------------------------------
# login
# ----------------------------------------------------------

def test_login_ok_e_falha():
    assert rodar(pm.fazer_login(FakePage(login_ok=True), "m", "s")) is True
    assert rodar(pm.fazer_login(FakePage(login_ok=False), "m", "s")) is False


# ----------------------------------------------------------
# Etapa 1 (coleta)
# ----------------------------------------------------------

def test_etapa_coleta_grava_e_mescla_com_historico(dados_tmp):
    base = pm.carregar_pre_matricula()
    base["turmas_intencao"] = {"1º Ano": [
        {"cpf": "SUMIU", "nome": "Saiu da lista", "presente_na_ultima_coleta": True},
    ]}
    pm.salvar_pre_matricula(base)

    page = FakePage(turmas={
        "1º Ano": [{"pos": 1, "nome": "Ana", "cpf": "111", "tipo": "Normal", "pontuacao": 5, "id": "r1"}],
        "2º Ano": [],
    })
    res = rodar(pm.etapa_coleta(page))

    assert page.escola_ok  # a escola alvo foi clicada
    assert res["turmas"]["1º Ano"][0]["tr_id"] == "r1" and res["turmas"]["2º Ano"] == []
    d = pm.carregar_pre_matricula()["turmas_intencao"]["1º Ano"]
    por = {a["cpf"]: a for a in d}
    assert por["111"]["presente_na_ultima_coleta"] is True
    assert por["SUMIU"]["presente_na_ultima_coleta"] is False
    assert por["SUMIU"]["motivo_cancelamento"] == pm.MOTIVO_PRESUNTIVO


# ----------------------------------------------------------
# planilhas .xlsx
# ----------------------------------------------------------

def _xlsx(caminho, turmas_blocos, aba="Judith Macedo Silveira"):
    """Cria uma planilha em grade: linha 1 = títulos, linha 2 = cabeçalhos."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Escolas"
    ws = wb.create_sheet(aba)
    col = 1
    for titulo, cab, linhas in turmas_blocos:
        ws.cell(row=1, column=col, value=titulo)
        for j, h in enumerate(cab):
            ws.cell(row=2, column=col + j, value=h)
        for i, linha in enumerate(linhas):
            for j, v in enumerate(linha):
                ws.cell(row=3 + i, column=col + j, value=v)
        col += len(cab) + 1  # coluna vazia separa os blocos
    wb.save(caminho)


def test_planilha_intencoes_filtra_opcao_1_e_ignora_bloco_de_contato(tmp_path):
    arq = tmp_path / "Relatorio_Intencoes_Vaga_x.xlsx"
    _xlsx(arq, [
        ("Infantil IV", ["Nome", "CPF", "Opção", "Pontuação"],
         [["Ana", "111", 1, 10], ["Bia", "222", 2, 5], ["Caio", "333", "1", 7], ["Duda", "444", None, 1]]),
        ("Alunos - Contato", ["Nome do Aluno", "Telefone"], [["Ana", "999"]]),
    ])
    r = pm.extrair_turmas_de_planilha(str(arq), aplicar_filtro_opcao=True, origem="planilha_intencoes")
    assert list(r) == ["Infantil IV"]
    assert [a["cpf"] for a in r["Infantil IV"]] == ["111", "333"]
    assert r["Infantil IV"][0]["origem"] == "planilha_intencoes"
    assert [a["pos"] for a in r["Infantil IV"]] == ["1", "2"]


def test_planilha_matriculados_mantem_todos_e_guarda_extras(tmp_path):
    arq = tmp_path / "Relatorio_Alunos_Matriculados_x.xlsx"
    _xlsx(arq, [("1º Ano", ["Nome", "CPF", "Pontuação", "Opção", "Matriculado Por", "Matriculado Em"],
                 [["Ana", "111", 3, 1, 30627, "05/02/2026"], ["Bia", "222", 4, 2, 1, "06/02/2026"]])])
    r = pm.extrair_turmas_de_planilha(str(arq), aplicar_filtro_opcao=False, origem="planilha_matriculados")
    assert [a["cpf"] for a in r["1º Ano"]] == ["111", "222"]
    assert r["1º Ano"][0]["extra"] == {"matriculado_por": 30627, "matriculado_em": "05/02/2026"}


def test_planilha_inexistente_ou_sem_layout(tmp_path):
    assert pm.extrair_turmas_de_planilha(str(tmp_path / "nao.xlsx"), False, "x") == {}
    import openpyxl
    vazio = tmp_path / "vazio.xlsx"
    openpyxl.Workbook().save(vazio)
    assert pm.extrair_turmas_de_planilha(str(vazio), False, "x") == {}


def test_arquivo_mais_recente_e_completar_json_de_ponta_a_ponta(dados_tmp):
    import os
    velho = dados_tmp / "Relatorio_Alunos_Matriculados_velho.xlsx"
    novo = dados_tmp / "Relatorio_Alunos_Matriculados_novo.xlsx"
    _xlsx(velho, [("1º Ano", ["Nome", "CPF"], [["Velho", "000"]])])
    _xlsx(novo, [("1º Ano", ["Nome", "CPF"], [["Ana", "111"]])])
    os.utime(velho, (1, 1))
    assert pm.arquivo_mais_recente("Relatorio_Alunos_Matriculados*.xlsx") == str(novo)
    assert pm.arquivo_mais_recente("Nada*.xlsx") is None

    page = FakePage(cad={"111": pagina_cad("111", [(ESCOLA, "Matriculado. Observação:")])})
    res = rodar(pm.completar_json_a_partir_de_planilhas(page, str(novo), None))
    assert set(res) == {"111"}
    d = pm.carregar_pre_matricula()
    assert d["turmas_intencao"]["1º Ano"][0]["origem"] == "planilha_matriculados"
    assert "111" in d["cadastros"]


# ----------------------------------------------------------
# contatos / CSV
# ----------------------------------------------------------

@pytest.mark.parametrize("endereco,esperado", [
    ("RUA A 10 CENTRO PONTA GROSSA PR 84000-000", "84000-000"),
    ("RUA A 10 9999-9999 CENTRO PONTA GROSSA PR 84010-123", "84010-123"),   # antes: "9999-9999"
    ("RUA A 10 CENTRO PONTA GROSSA PR 84010123", "84010-123"),
    ("RUA A 10 CENTRO PONTA GROSSA PR", ""),
    ("", ""),
    (None, ""),
])
def test_extrair_cep(endereco, esperado):
    assert pm.extrair_cep(endereco) == esperado


def _base_contatos():
    turmas = {"3º Ano do Ensino Fundamental": [
        {"cpf": "1", "nome": "IRMAO UM"}, {"cpf": "2", "nome": "IRMAO DOIS"}, {"cpf": "3", "nome": "SOZINHA"},
    ], "1º Ano do Ensino Fundamental": [{"cpf": "4", "nome": "SEM RESP"}]}
    cads = {
        "1": cadastro("1", [], resp="MAE", tel="111"),
        "2": cadastro("2", [], resp="MAE", tel="111"),      # mesmo telefone -> mesmo contato
        "3": cadastro("3", [], resp="OUTRA", tel=""),        # sem telefone -> agrupa por nome
        "4": cadastro("4", [], resp=""),                      # sem responsável -> descartado
    }
    return cads, {"turmas_intencao": turmas}


def test_processar_contatos_agrupa_por_telefone_e_descarta_sem_responsavel():
    cads, base = _base_contatos()
    contatos = pm.processar_contatos(cads, base)
    assert len(contatos) == 2
    nomes = {c["First Name"] for c in contatos}
    assert "3º Ano - 2026 - RESPONSAVEL DO IRMAO UM E DO IRMAO DOIS" in nomes
    assert all(c["Address 1 - Postal Code"] == "84000-000" for c in contatos)
    assert all(c["Labels - 2026"] == "2026" for c in contatos)


def test_processar_contatos_aceita_lista_e_registro_unico():
    cads, base = _base_contatos()
    assert len(pm.processar_contatos(list(cads.values()), base)) == 2
    assert len(pm.processar_contatos(cads["1"], base)) == 1
    assert pm.processar_contatos(None, base) == []
    assert pm.processar_contatos({"1": {"cpf": "1", "nome_responsavel": None}}, base) == []  # None não quebra


def test_etapa_contatos_gera_csv_com_colunas_padrao_sem_template(dados_tmp):
    cads, base = _base_contatos()
    caminho = pm.etapa_contatos(cads, base)
    assert caminho and caminho.exists() and caminho.parent == dados_tmp
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f))
    assert len(linhas) == 2 and list(linhas[0].keys()) == pm.COLUNAS_CONTATOS_PADRAO


def test_etapa_contatos_usa_colunas_do_template_quando_existe(dados_tmp):
    pm.caminho_template().write_text("First Name,Phone 1 - Value,Coluna Extra\n", encoding="utf-8")
    cads, base = _base_contatos()
    caminho = pm.etapa_contatos(cads, base)
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        linhas = list(r)
        assert r.fieldnames == ["First Name", "Phone 1 - Value", "Coluna Extra"]
    assert linhas[0]["Coluna Extra"] == ""


def test_etapa_contatos_sem_dados_nao_gera_arquivo(dados_tmp):
    assert pm.etapa_contatos({}, {"turmas_intencao": {}}) is None
    assert not list(dados_tmp.glob("TEMPLATE_PREENCHIDO_*.csv"))


# ----------------------------------------------------------
# pontos de entrada (navegador simulado)
# ----------------------------------------------------------

class _FakeContext:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page


class _FakeBrowser:
    def __init__(self, page):
        self.page, self.fechado = page, False

    async def new_context(self):
        return _FakeContext(self.page)

    async def close(self):
        self.fechado = True


class _FakeLauncher:
    def __init__(self, page):
        self.page, self.browser, self.headless = page, None, None

    async def launch(self, headless=True):
        self.headless = headless
        self.browser = _FakeBrowser(self.page)
        return self.browser


class _FakePW:
    def __init__(self, page):
        self.chromium = self.firefox = _FakeLauncher(page)
        self.parado = False

    async def stop(self):
        self.parado = True


def _instalar_playwright(monkeypatch, page):
    pw = _FakePW(page)

    class _Starter:
        async def start(self):
            return pw

    monkeypatch.setattr(pm, "async_playwright", lambda: _Starter())
    return pw


def test_processo_completo_de_ponta_a_ponta(dados_tmp, monkeypatch):
    # histórico: um aluno que vai sumir da lista e cuja situação real está no site
    base = pm.carregar_pre_matricula()
    base["turmas_intencao"] = {"1º Ano do Ensino Fundamental": [
        {"cpf": "222", "nome": "SUMIU", "presente_na_ultima_coleta": True},
    ]}
    pm.salvar_pre_matricula(base)

    page = FakePage(
        turmas={"1º Ano do Ensino Fundamental": [
            {"pos": 1, "nome": "ANA", "cpf": "111", "tipo": "", "pontuacao": 5, "id": "r1"}]},
        cad={
            "111": pagina_cad("111", [(ESCOLA, "")], nome="ana"),
            "222": pagina_cad("222", [(OUTRA, "Cancelado. Motivo: X"), (ESCOLA, "Matriculado. Observação:")]),
        },
    )
    pw = _instalar_playwright(monkeypatch, page)

    r = rodar(pm.processo_completo_via_login(matricula="m", senha="s"))

    assert r["ok"] is True
    assert r["resumo_pendentes"] == {"total_pendentes": 1, "confirmados": 1, "sem_resposta": []}
    assert r["arquivo_contatos"] and r["arquivo_contatos"].exists()
    d = pm.carregar_pre_matricula()
    por = {a["cpf"]: a for a in d["turmas_intencao"]["1º Ano do Ensino Fundamental"]}
    assert por["222"]["situacao"].startswith("MATRICULADO")   # não "CANCELADO" da outra escola
    assert por["111"]["presente_na_ultima_coleta"] is True
    assert set(d["cadastros"]) == {"111", "222"}
    assert pw.chromium.browser.fechado and pw.parado


def test_processo_completo_pular_pendentes(dados_tmp, monkeypatch):
    page = FakePage(turmas={"T": [{"pos": 1, "nome": "A", "cpf": "1", "tipo": "", "pontuacao": 1, "id": "r"}]},
                    cad={"1": pagina_cad("1", [(ESCOLA, "")])})
    _instalar_playwright(monkeypatch, page)
    r = rodar(pm.processo_completo_via_login(matricula="m", senha="s", pular_pendentes=True))
    assert r["ok"] and r["resumo_pendentes"] is None


def test_processo_completo_login_falho_aborta_e_fecha_navegador(dados_tmp, monkeypatch):
    page = FakePage(login_ok=False)
    pw = _instalar_playwright(monkeypatch, page)
    r = rodar(pm.processo_completo_via_login(matricula="m", senha="s"))
    assert r == {"ok": False, "resumo_pendentes": None, "arquivo_contatos": None}
    assert pw.chromium.browser.fechado and pw.parado
    assert not pm.caminho_pre_matricula().exists()  # nada gravado


def test_verificar_pendentes_via_login_e_navegador_configuravel(dados_tmp, monkeypatch):
    page = FakePage()
    pw = _instalar_playwright(monkeypatch, page)
    resumo = rodar(pm.verificar_pendentes_via_login(matricula="m", senha="s", navegador="firefox", headless=False))
    assert resumo["total_pendentes"] == 0
    assert pw.firefox.headless is False


def test_completar_json_via_login_sem_planilhas_nao_abre_navegador(dados_tmp, monkeypatch):
    def nao_deveria(*_a, **_k):
        raise AssertionError("não devia abrir o navegador")
    monkeypatch.setattr(pm, "async_playwright", nao_deveria)
    assert rodar(pm.completar_json_via_login(matricula="m", senha="s")) is None


def test_credenciais_padrao_vem_de_comum_credenciais(dados_tmp, monkeypatch):
    usados = {}

    async def fake_login(page, matricula, senha, analise=False):
        usados["cred"] = (matricula, senha)
        return True

    monkeypatch.setattr(pm, "fazer_login", fake_login)
    _instalar_playwright(monkeypatch, FakePage())
    rodar(pm.verificar_pendentes_via_login())
    assert usados["cred"] == ("000", "senha")  # stub de credenciais do sandbox

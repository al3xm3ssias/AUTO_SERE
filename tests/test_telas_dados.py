"""Dados das telas Encaminhamentos do SUS, Alunos fora do raio, Funcionários e contadores do painel."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402


@pytest.fixture()
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def c(dados):
    return create_app().test_client()


def gravar(pasta, nome, conteudo):
    (pasta / nome).write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")


TURMAS = {
    "5º Ano A": [{"CGM": "111", "Nome": "João da Silva", "Situação": "Matriculado", "Sexo": "M"}],
    "3º Ano B": [{"CGM": "222", "Nome": "Maria Conceição", "Situação": "Matriculado", "Sexo": "F"}],
}

# ───────────── fora do raio ─────────────

def test_fora_do_raio_formato_atual_ordenado_e_com_turma(dados, c):
    gravar(dados, "turmas.json", TURMAS)
    gravar(dados, "alunos_fora_raio.json", {
        "metadados": {"raio_km": 2.0, "total_alunos_processados": 200, "data_analise": "2026-10-01 10:00:00"},
        "alunos": [
            {"nome": "Maria Conceição", "cgm": "222", "cep": "84000000", "distancia_km": 2.5},
            {"nome": "João da Silva", "cgm": "111", "cep": "84010000", "distancia_km": 7.123},
        ],
    })
    r = c.get("/web/api/fora-do-raio/lista").get_json()
    assert [l["nome"] for l in r["linhas"]] == ["João da Silva", "Maria Conceição"]      # mais distante primeiro
    assert r["linhas"][0]["distancia"] == "7,12 km" and r["linhas"][0]["turma"] == "5º Ano A"
    assert "Raio de 2,0 km" in r["resumo"] and "200 aluno(s)" in r["resumo"]
    assert r["total"] == 2


def test_fora_do_raio_aceita_lista_antiga_e_vazio(dados, c):
    gravar(dados, "alunos_fora_raio.json", [{"nome": "X", "cgm": "9", "cep": "1", "distancia_km": 3}])
    r = c.get("/web/api/fora-do-raio/lista").get_json()
    assert r["total"] == 1 and r["linhas"][0]["turma"] == "—"
    (dados / "alunos_fora_raio.json").unlink()
    r = c.get("/web/api/fora-do-raio/lista").get_json()
    assert r["total"] == 0 and "ainda não executada" in r["resumo"]


# ───────────── encaminhamentos do SUS ─────────────

ENCAM = [
    {"nome": "João da Silva", "cgm": "111", "cpf": "11111111111", "encaminhamentos": [
        {"data_solicitacao": "01/03/2026", "procedimento": "Oftalmologia", "data_nascimento": "x", "posicao_fila": "12"},
        {"data_solicitacao": "05/04/2026", "procedimento": "Fonoaudiologia", "data_nascimento": "x", "posicao_fila": "3"}]},
    {"nome": "Sem CPF", "cpf": "", "encaminhamentos": [], "erro": "CPF inválido"},
    {"nome": "MARIA CONCEICAO", "cpf": "22222222222", "encaminhamentos": [          # sem cgm, nome sem acento
        {"data_solicitacao": "10/02/2026", "procedimento": "Cardiologia", "data_nascimento": "x", "posicao_fila": "8"}]},
]


def test_encaminhamentos_uma_linha_por_encaminhamento_sem_cpf_invalido(dados, c):
    gravar(dados, "turmas.json", TURMAS)
    gravar(dados, "alunos_encaminhamento.json", ENCAM)
    r = c.get("/web/api/encaminhamentos/lista").get_json()
    assert r["total"] == 3
    assert {l["nome"] for l in r["linhas"]} == {"João da Silva", "MARIA CONCEICAO"}   # "Sem CPF" não é encaminhamento
    turmas = {l["nome"]: l["turma"] for l in r["linhas"]}
    assert turmas["João da Silva"] == "5º Ano A"            # por CGM
    assert turmas["MARIA CONCEICAO"] == "3º Ano B"          # por nome, sem diferenciar acento/caixa
    assert "2 aluno(s) com encaminhamento" in r["resumo"] and "1 sem CPF válido" in r["resumo"]
    corpo = json.dumps(r)
    assert "11111111111" not in corpo and "22222222222" not in corpo                  # CPF completo não vai para a tela
    assert {a["cpf"] for a in r["alunos"] if a["cpf"]} == {"***.111.111-**", "***.222.222-**"}   # só o mascarado


def test_encaminhamentos_vazio(dados, c):
    r = c.get("/web/api/encaminhamentos/lista").get_json()
    assert r["total"] == 0 and "ainda não executada" in r["resumo"]


# ───────────── painel ─────────────

def _metricas(c):
    r = c.get("/web/api/painel/resumo").get_json()
    return {m["chave"]: m["valor"] for m in r["principais"] + r["secundarias"]}


def test_painel_conta_alunos_fora_do_raio_e_nao_o_tamanho_do_objeto(dados, c):
    gravar(dados, "alunos_fora_raio.json", {"metadados": {"raio_km": 2}, "alunos": [{"nome": "A"}, {"nome": "B"}, {"nome": "C"}]})
    assert _metricas(c)["fora_do_raio"] == 3          # antes devolvia 2 (as duas chaves do objeto)


def test_painel_encaminhamentos_nao_conta_cpf_invalido(dados, c):
    gravar(dados, "alunos_encaminhamento.json", ENCAM)
    assert _metricas(c)["encaminhamentos"] == 2


# ───────────── funcionários ─────────────

def test_funcionarios_usa_os_campos_que_o_coletor_realmente_grava(dados, c):
    gravar(dados, "funcionarios.json", [
        {"nome": "Zélia Souza", "funcao": "Professor", "email": "z@x.com", "curso_superior": "Pedagogia",
         "turmas": [{"descricao": "- 5º A", "disciplinas": []}, {"descricao": "- 5º B", "disciplinas": []}], "cpf": "999"},
        {"nome": "Ana Lima", "funcao": "Servente", "email": "", "curso_superior": "", "turmas": []},
    ])
    r = c.get("/web/api/funcionarios/lista").get_json()
    assert [l["nome"] for l in r["linhas"]] == ["Ana Lima", "Zélia Souza"]
    z = r["linhas"][1]
    assert z["funcao"] == "Professor" and z["formacao"] == "Pedagogia" and z["turmas"] == "2"   # "Cargo" antes saía vazio
    assert r["linhas"][0]["turmas"] == "—"
    assert "999" not in json.dumps(r)                  # CPF não é exibido


def test_funcionarios_aceita_chaves_antigas(dados, c):
    gravar(dados, "funcionarios.json", [{"Nome": "Velho", "Cargo": "Diretor"}])
    l = c.get("/web/api/funcionarios/lista").get_json()["linhas"][0]
    assert l["nome"] == "Velho" and l["funcao"] == "Diretor"


# ───────────── pré-matrícula: tentativa substituída não conta duas vezes ─────────────

def test_fila_da_prematricula_ignora_a_tentativa_substituida(dados, c):
    gravar(dados, "pre_matricula.json", {
        "turmas_intencao": {
            "5º Ano A": [{"nome": "Ana", "cpf": "111", "pos": "1", "substituido_por_nova_tentativa": True,
                          "turma_da_tentativa_atual": "5º Ano B", "presente_na_ultima_coleta": False}],
            "5º Ano B": [{"nome": "Ana", "cpf": "111", "pos": "2", "presente_na_ultima_coleta": True}],
        },
        "cadastros": {},
    })
    r = c.get("/web/api/prematricula/lista").get_json()
    assert r["total"] == 1 and r["linhas"][0]["turma"] == "5º Ano B"


def test_painel_nao_conta_duas_vezes_quem_mudou_de_turma(dados, c):
    gravar(dados, "pre_matricula.json", {"turmas_intencao": {
        "A": [{"nome": "Ana", "cpf": "1", "substituido_por_nova_tentativa": True}, {"nome": "Beto", "cpf": "2"}],
        "B": [{"nome": "Ana", "cpf": "1"}]}, "cadastros": {}})
    assert _metricas(c)["fila_prematricula"] == 2


# ───────────── pré-matrícula: matriculado e cancelado saem da fila ─────────────
# pre_matricula.json guarda TODOS que já passaram pela fila; quem é chamado some da lista do site, mas fica no arquivo
# (presente_na_ultima_coleta=False + situação). Eles não são mais fila: a situação deles aparece em Cadastros.

PRESUNTIVO = {"situacao": "Cancelado", "motivo_cancelamento": "CANCELADO VIA SISTEMA/RESPONSAVEL"}


def _fila(c, **params):
    return c.get("/web/api/prematricula/fila", query_string=params).get_json()["itens"]


def _gravar_turma(dados, alunos, cadastros=None):
    gravar(dados, "pre_matricula.json", {"turmas_intencao": {"1º Ano": alunos}, "cadastros": cadastros or {}})


def test_matriculado_nao_fica_na_fila(dados, c):
    _gravar_turma(dados, [
        {"nome": "Ana Matriculada", "cpf": "1", "pos": "1", "situacao": "MATRICULADO.", "presente_na_ultima_coleta": False},
        {"nome": "Beto Aguardando", "cpf": "2", "pos": "2", "presente_na_ultima_coleta": True},
    ])
    assert [i["nome"] for i in _fila(c)] == ["Beto Aguardando"]


def test_cancelado_real_nao_fica_na_fila(dados, c):
    _gravar_turma(dados, [
        {"nome": "Cris Cancelada", "cpf": "1", "pos": "1", "situacao": "CANCELADO. MOTIVO: X", "presente_na_ultima_coleta": False},
        {"nome": "Beto Aguardando", "cpf": "2", "pos": "2", "presente_na_ultima_coleta": True},
    ])
    assert [i["nome"] for i in _fila(c)] == ["Beto Aguardando"]


def test_cancelado_presumido_que_sumiu_da_lista_nao_fica_na_fila(dados, c):
    _gravar_turma(dados, [
        {"nome": "Davi Sumiu", "cpf": "1", "pos": "1", "presente_na_ultima_coleta": False, **PRESUNTIVO},
        {"nome": "Beto Aguardando", "cpf": "2", "pos": "2", "presente_na_ultima_coleta": True},
    ])
    assert [i["nome"] for i in _fila(c)] == ["Beto Aguardando"]


def test_quem_sumiu_da_lista_sai_mesmo_sem_situacao_gravada(dados, c):
    _gravar_turma(dados, [{"nome": "Eva", "cpf": "1", "pos": "1", "presente_na_ultima_coleta": False}])
    assert _fila(c) == []


def test_situacao_preenchida_tira_da_fila_mesmo_com_marca_de_presente(dados, c):
    """Foi como os dados fictícios de demonstração (e o painel do usuário) mostravam matriculado como se aguardasse."""
    _gravar_turma(dados, [
        {"nome": "Fabi", "cpf": "1", "pos": "1", "situacao": "Matriculado", "presente_na_ultima_coleta": True},
        {"nome": "Gil", "cpf": "2", "pos": "2", "situacao": "Cancelado. Motivo: desistiu", "presente_na_ultima_coleta": True},
        {"nome": "Hugo", "cpf": "3", "pos": "3", "situacao": "", "presente_na_ultima_coleta": True},
    ])
    assert [i["nome"] for i in _fila(c)] == ["Hugo"]


def test_widget_do_painel_mostra_os_que_aguardam_a_partir_da_posicao_real(dados, c):
    """Com 3 já chamados à frente, o painel mostra quem de fato é o próximo da fila (e respeita o limite)."""
    _gravar_turma(dados, [
        *[{"nome": f"Chamado {p}", "cpf": str(p), "pos": str(p), "situacao": "MATRICULADO",
           "presente_na_ultima_coleta": False} for p in (1, 2, 3)],
        *[{"nome": f"Aguarda {p}", "cpf": str(p), "pos": str(p), "presente_na_ultima_coleta": True} for p in (4, 5, 6, 7)],
    ])
    itens = _fila(c, limit=2)
    assert [(i["nome"], i["posicao"]) for i in itens] == [("Aguarda 4", "4"), ("Aguarda 5", "5")]


def test_contador_do_painel_lista_e_widget_concordam(dados, c):
    _gravar_turma(dados, [
        {"nome": "A", "cpf": "1", "pos": "1", "situacao": "MATRICULADO", "presente_na_ultima_coleta": False},
        {"nome": "B", "cpf": "2", "pos": "2", "presente_na_ultima_coleta": False, **PRESUNTIVO},
        {"nome": "C", "cpf": "3", "pos": "3", "presente_na_ultima_coleta": True},
        {"nome": "D", "cpf": "4", "pos": "4", "presente_na_ultima_coleta": True},
    ])
    assert _metricas(c)["fila_prematricula"] == 2
    assert c.get("/web/api/prematricula/lista").get_json()["total"] == 2
    assert len(_fila(c, limit=50)) == 2


def _cadastro(cpf, situacoes, tr_id=""):
    return {"cpf": cpf, "tr_id": tr_id, "nome_aluno": f"Aluno {cpf}", "escolas_escolhidas": {
        "turma": "1º Ano", "opcoes": [{"escola": "Judith Macedo Silveira", "situacao": s} for s in situacoes]}}


def test_arquivo_antigo_sem_marca_confere_o_cadastro(dados, c):
    """Entradas sem presente_na_ultima_coleta (arquivo anterior à marca): vale a situação do cadastro."""
    _gravar_turma(dados, [
        {"nome": "Matric", "cpf": "1", "pos": "1"},
        {"nome": "Cancel", "cpf": "2", "pos": "2"},
        {"nome": "Aguarda", "cpf": "3", "pos": "3"},
        {"nome": "SemCadastro", "cpf": "4", "pos": "4"},
        {"nome": "PeloTrId", "cpf": "", "tr_id": "T9", "pos": "5"},
    ], cadastros={
        "1": _cadastro("1", ["MATRICULADO"]),
        "2": _cadastro("2", ["CANCELADO. MOTIVO: X", "CANCELADO"]),
        "3": _cadastro("3", [""]),
        "9": _cadastro("9", ["MATRICULADO"], tr_id="T9"),
    })
    assert sorted(i["nome"] for i in _fila(c, limit=50)) == ["Aguarda", "SemCadastro"]    # PeloTrId: cadastro achado pelo tr_id


def test_cadastro_antigo_cancelado_nao_esconde_quem_voltou_a_aguardar(dados, c):
    """BUG-PRE-001: o cadastro pode ser a tentativa antiga (cancelada). Se o site ainda lista o aluno, ele aguarda."""
    _gravar_turma(dados, [{"nome": "Voltou", "cpf": "1", "pos": "1", "presente_na_ultima_coleta": True}],
                  cadastros={"1": _cadastro("1", ["CANCELADO. MOTIVO: X"])})
    assert [i["nome"] for i in _fila(c)] == ["Voltou"]


def test_a_tela_cadastros_continua_mostrando_matriculados_e_cancelados(dados, c):
    _gravar_turma(dados, [
        {"nome": "Ana", "cpf": "1", "pos": "1", "situacao": "MATRICULADO", "presente_na_ultima_coleta": False},
        {"nome": "Beto", "cpf": "2", "pos": "2", "presente_na_ultima_coleta": True},
    ], cadastros={"1": _cadastro("1", ["MATRICULADO"]), "2": _cadastro("2", [""])})
    r = c.get("/web/api/prematricula/cadastros").get_json()
    assert r["contagem"] == {"matriculado": 1, "cancelado": 0, "pendente": 1, "analise": 0}
    assert _fila(c) and [i["nome"] for i in _fila(c)] == ["Beto"]


def test_mudou_de_turma_continua_contando_uma_vez(dados, c):
    gravar(dados, "pre_matricula.json", {"turmas_intencao": {
        "5º Ano A": [{"nome": "Ana", "cpf": "1", "pos": "1", "substituido_por_nova_tentativa": True,
                      "presente_na_ultima_coleta": False}],
        "5º Ano B": [{"nome": "Ana", "cpf": "1", "pos": "2", "presente_na_ultima_coleta": True}]}, "cadastros": {}})
    assert [(i["nome"], i["turma"]) for i in _fila(c)] == [("Ana", "5º Ano B")]


# ───────────── cards de resumo (Fora do raio / Encaminhamentos) ─────────────

def _cartoes(r):
    return {c["label"]: c for c in r["cartoes"]}


def test_fora_do_raio_cartoes_mapa_e_comprovante_de_endereco(dados, c):
    gravar(dados, "turmas.json", TURMAS)
    gravar(dados, "alunos_fora_raio.json", {
        "metadados": {"raio_km": 2.0, "total_alunos_processados": 200, "data_analise": "2026-10-01 10:00:00",
                      "cep_escola": "84010-000", "coordenadas_escola": {"latitude": -25.05, "longitude": -50.15}},
        "alunos": [
            {"nome": "Maria Conceição", "cgm": "222", "cep": "84000000", "distancia_km": 2.5},
            {"nome": "João da Silva", "cgm": "111", "cep": "84010000", "distancia_km": 7.123},
        ],
    })
    gravar(dados, "documentos-alunos-pc.json", [
        {"CGM": "111", "Nome": "João da Silva", "Documentos": ["RG_20260101_1.pdf", {"nome": "Conta Copel.pdf"}]},
        {"CGM": "222", "Nome": "Maria Conceição", "Documentos": ["CPF.pdf"]},
    ])
    r = c.get("/web/api/fora-do-raio/lista").get_json()
    cards = _cartoes(r)
    assert cards["Processados"]["valor"] == 200 and cards["Fora do raio"]["valor"] == 2
    assert cards["Com comp. endereço"]["valor"] == 1 and cards["Sem comp. endereço"]["valor"] == 1
    assert cards["Máx. distância"]["valor"] == "7,12 km" and cards["CEP da escola"]["valor"] == "84010-000"
    assert r["mapa"] == {"latitude": -25.05, "longitude": -50.15} and r["tem_docs_pc"] is True
    joao, maria = r["linhas"]
    assert joao["tem_comprovante"] is True and joao["comprovante"] == "Sim — 1 doc(s)" and joao["docs_endereco"] == ["Conta Copel.pdf"]
    assert maria["tem_comprovante"] is False and maria["comprovante"] == "Não encontrado"


def test_fora_do_raio_sem_documentos_do_pc_nao_afirma_falta_de_comprovante(dados, c):
    gravar(dados, "alunos_fora_raio.json", {
        "metadados": {"raio_km": 2.0, "total_alunos_processados": 10, "data_analise": "x"},
        "alunos": [{"nome": "X", "cgm": "9", "cep": "1", "distancia_km": 3}]})
    r = c.get("/web/api/fora-do-raio/lista").get_json()
    assert r["tem_docs_pc"] is False and r["linhas"][0]["tem_comprovante"] is None and r["linhas"][0]["comprovante"] == "—"
    assert "Com comp. endereço" not in _cartoes(r) and r["mapa"] is None


def test_fora_do_raio_sem_analise_nao_tem_cartoes(dados, c):
    r = c.get("/web/api/fora-do-raio/lista").get_json()
    assert r["cartoes"] == [] and r["mapa"] is None


def test_encaminhamentos_cartoes_e_ranking_de_procedimentos(dados, c):
    gravar(dados, "turmas.json", TURMAS)
    gravar(dados, "alunos_encaminhamento.json", ENCAM + [
        {"nome": "Pedro", "cgm": "333", "cpf": "33333333333", "encaminhamentos": [
            {"data_solicitacao": "x", "procedimento": "Oftalmologia", "data_nascimento": "x", "posicao_fila": "1"}]}])
    r = c.get("/web/api/encaminhamentos/lista").get_json()
    cards = _cartoes(r)
    assert cards["Com Encaminhamentos"]["valor"] == 3 and cards["CPF Inválido/Erro"]["valor"] == 1
    assert cards["Total Procedimentos"]["valor"] == r["total"]
    assert cards["Alunos Pesquisados"]["valor"] == 4 and len(r["alunos"]) == 4 and any(a["erro"] for a in r["alunos"])
    itens = r["grafico"]["itens"]
    assert itens[0]["valor"] == max(i["valor"] for i in itens) and len({i["label"] for i in itens}) == len(itens)


def test_encaminhamentos_sem_consulta_nao_tem_cartoes(dados, c):
    r = c.get("/web/api/encaminhamentos/lista").get_json()
    assert r["cartoes"] == [] and r["grafico"]["itens"] == []


# ───────────── Funcionários / Pré-matrícula / Transferidos (cards + registros completos) ─────────────

def test_funcionarios_unifica_basico_e_completo_pelo_cpf_com_cpf_mascarado(dados, c):
    gravar(dados, "funcionarios.json", [
        {"nome": "Zélia Souza", "cpf": "111.222.333-44", "funcao": "Docente", "email": "z@x.com", "curso_superior": "Pedagogia", "turmas": [{"descricao": "- 5º A"}]},
        {"nome": "Ana Lima", "cpf": "55566677788", "funcao": "Gestor - Diretor(a)", "turmas": []}])
    gravar(dados, "funcionarios_completo.json", [
        {"cpf": "11122233344", "nome_completo": "ZÉLIA DE SOUZA", "telefone": "42999998888", "sexo": "F", "escolaridade": "Superior", "rg": "123"}])
    r = c.get("/web/api/funcionarios/lista").get_json()
    ana, zelia = r["funcionarios"]
    assert zelia["cpf"] == "***.222.333-**" and zelia["telefone"] == "42999998888" and zelia["sexo"] == "F"
    assert zelia["formacao"] == "Superior" and zelia["tem_cadastro_completo"] and zelia["detalhe"]["rg"] == "123"
    assert "cpf" not in zelia["detalhe"] and "11122233344" not in json.dumps(r)               # CPF completo não sai do servidor
    assert zelia["grupo"] == "Docente" and ana["grupo"] == "Direção" and not ana["tem_cadastro_completo"]
    assert {c_["label"]: c_["valor"] for c_ in r["cartoes"]}["Total Funcionários"] == 2
    assert [x["chave"] for x in r["colunas"]] == ["nome", "funcao", "email", "formacao", "turmas"] and r["total"] == 2


def test_funcionarios_so_no_completo_tambem_aparece(dados, c):
    gravar(dados, "funcionarios.json", [])
    gravar(dados, "funcionarios_completo.json", [{"cpf": "11122233344", "nome_completo": "Só Completo", "sexo": "M"}])
    r = c.get("/web/api/funcionarios/lista").get_json()
    assert [f["nome"] for f in r["funcionarios"]] == ["Só Completo"]


def test_prematricula_cadastros_deriva_situacao_e_ignora_tentativa_antiga(dados, c):
    gravar(dados, "pre_matricula.json", {
        "atualizado_em": "2026-10-01 09:00",
        "turmas_intencao": {
            "5º Ano A": [{"nome": "Ana", "cpf": "1", "pos": "1", "substituido_por_nova_tentativa": True},
                         {"nome": "Beto", "cpf": "2", "pos": "2"}],
            "5º Ano B": [{"nome": "Ana", "cpf": "1", "pos": "3"}, {"nome": "Caio", "cpf": "3", "pos": "4"}]},
        "cadastros": {
            "1": {"nome_aluno": "Ana", "nome_responsavel": "Mãe", "escolas_escolhidas": {"turma": "5º Ano B", "opcoes": [{"escola": "Esc X", "situacao": "MATRICULADO"}]}},
            "2": {"nome_aluno": "Beto", "escolas_escolhidas": {"opcoes": [{"escola": "Esc X", "situacao": "CANCELADO", "motivo_cancelamento": "Mudou"}]}}}})
    r = c.get("/web/api/prematricula/cadastros").get_json()
    por_nome = {x["nome_aluno"]: x for x in r["cadastros"]}
    assert set(por_nome) == {"Ana", "Beto", "Caio"}                                   # Caio: na fila, sem cadastro coletado
    assert por_nome["Ana"]["situacao"] == "matriculado" and por_nome["Ana"]["turma_matriculada"] == "5º Ano B"
    assert [i["turma"] for i in por_nome["Ana"]["intencoes"]] == ["5º Ano B"]            # a tentativa antiga não conta
    assert por_nome["Beto"]["situacao"] == "cancelado" and por_nome["Beto"]["motivo_cancelamento"] == "Mudou"
    assert por_nome["Caio"]["situacao"] == "pendente" and por_nome["Caio"].get("sem_cadastro")
    assert r["contagem"] == {"matriculado": 1, "cancelado": 1, "pendente": 1, "analise": 0} and r["atualizado_em"] == "2026-10-01 09:00"


def test_prematricula_cadastros_vazio(dados, c):
    r = c.get("/web/api/prematricula/cadastros").get_json()
    assert r["cadastros"] == [] and r["cartoes"] == [] and r["total"] == 0


def _cadastro_com_3_opcoes(cpf, nome, situacoes=("", "", "")):
    escolas = ("Esc Primeira", "Judith Macedo Silveira", "Esc Terceira")
    return {"nome_aluno": nome, "nome_responsavel": "Mãe", "telefone": "42999990000",
            "escolas_escolhidas": {"turma": "Infantil IV", "opcoes": [
                {"escola": e, "situacao": sit} for e, sit in zip(escolas, situacoes)]}}


def test_prematricula_cadastros_por_ano_le_a_previsao_do_proximo_ano_com_as_3_opcoes(dados, c):
    ano = int(rotas._paths.ano_atual())
    gravar(dados, "pre_matricula.json", {"turmas_intencao": {}, "cadastros": {"1": _cadastro_com_3_opcoes("1", "Do Ano Atual")}})
    gravar(dados, f"previsao_alunos_{ano + 1}.json", {
        "turmas_intencao": {"Infantil IV": [{"nome": "Ana Futura", "cpf": "7", "pos": "3"}]},
        "cadastros": {"7": _cadastro_com_3_opcoes("7", "Ana Futura")}})
    atual = c.get("/web/api/prematricula/cadastros").get_json()
    assert atual["ano"] == ano and atual["somente_leitura"] is False and [x["nome_aluno"] for x in atual["cadastros"]] == ["Do Ano Atual"]
    prox = c.get(f"/web/api/prematricula/cadastros?ano={ano + 1}").get_json()
    assert prox["ano"] == ano + 1 and prox["somente_leitura"] is True and prox["arquivo"] == f"previsao_alunos_{ano + 1}.json"
    assert [a["ano"] for a in prox["anos"]] == [ano, ano + 1] and prox["existe"] is True
    ana = prox["cadastros"][0]
    assert ana["nome_aluno"] == "Ana Futura" and [o["opcao"] for o in ana["opcoes"]] == [1, 2, 3]
    assert [o["escola"] for o in ana["opcoes"]] == ["Esc Primeira", "Judith Macedo Silveira", "Esc Terceira"]
    assert [o["nossa"] for o in ana["opcoes"]] == [False, True, False]                 # nossa escola marcada (aqui, a 2ª opção)
    assert ana["intencoes"][0]["pos"] == "3"


def test_prematricula_cadastros_ano_sem_arquivo_e_ano_invalido(dados, c):
    ano = int(rotas._paths.ano_atual())
    vazio = c.get(f"/web/api/prematricula/cadastros?ano={ano + 1}").get_json()
    assert vazio["cadastros"] == [] and vazio["existe"] is False and vazio["somente_leitura"] is True
    assert c.get(f"/web/api/prematricula/cadastros?ano={ano + 2}").status_code == 400
    assert c.get(f"/web/api/prematricula/cadastros?ano={ano - 1}").status_code == 400


def test_prematricula_opcao_numero_vem_do_site_quando_existe(dados, c):
    gravar(dados, "pre_matricula.json", {"turmas_intencao": {}, "cadastros": {"1": {
        "nome_aluno": "X", "escolas_escolhidas": {"opcoes": [{"escola": "B", "opcao": 2}, {"escola": "A", "opcao": 1}]}}}})
    ops = c.get("/web/api/prematricula/cadastros").get_json()["cadastros"][0]["opcoes"]
    assert [(o["opcao"], o["escola"]) for o in ops] == [(1, "A"), (2, "B")]


def test_transferidos_status_pelos_6_passos_da_guia_e_historico(dados, c):
    d = "2026-03-01T10:00:00"
    gravar(dados, "transferidos.json", {
        "111": {"nome": "João", "turma": "5º A", "guia": {"emitido_em": d, "assinado_secretario": d, "assinado_diretor": d},
                "historico": {"emitido_em": d, "assinado_secretario": d, "assinado_diretor": d}, "parecer": {"digitalizado_em": d}},
        "222": {"nome": "Maria", "turma": "3º B", "guia": {"emitido_em": d}, "historico": {}},
        "333": {"nome": "Pedro", "turma": "1º C", "guia": {}, "historico": {}}})
    r = c.get("/web/api/transferidos/lista").get_json()
    st = {x["nome"]: x for x in r["transferidos"]}
    assert st["João"]["status"] == "completo" and st["Maria"]["status"] == "parcial" and st["Pedro"]["status"] == "pendente"
    assert st["Maria"]["feitos"] == 1 and st["João"]["parecer"]["digitalizado_em"] == d
    assert r["contagem"] == {"completo": 1, "parcial": 1, "pendente": 1}
    assert {c_["label"]: c_["valor"] for c_ in r["cartoes"]}["Total"] == 3


def test_transferidos_vazio(dados, c):
    r = c.get("/web/api/transferidos/lista").get_json()
    assert r["transferidos"] == [] and r["cartoes"] == []


def test_transferidos_mostra_ciclos_anteriores(dados, c):
    d = "2026-03-01T10:00:00"
    ciclo = {"chamada": 7, "turma": "5º A", "data_transferencia": "05/03/2026",
             "retorno": {"chamada": 31, "turma": "5º A", "data": "20/04/2026"},
             "guia": {"emitido_em": d, "assinado_secretario": d}, "historico": {"emitido_em": d},
             "parecer": {"digitalizado_em": d}, "id_matricula": "M-1",
             "arquivos": {"guia": "Ana (saída 05-03-2026).pdf", "historico": "Ana (saída 05-03-2026).pdf"},
             "destino_manual": {"escola": "Escola Modelo", "status": "automatico"}, "arquivado_em": "2026-10-01T09:00:00"}
    gravar(dados, "transferidos.json", {
        "55": {"nome": "Ana", "turma": "5º A", "data_transferencia": "10/10/2026", "guia": {}, "historico": {},
               "ciclos_anteriores": [ciclo, "lixo"]},          # item que não é dict é ignorado
        "66": {"nome": "Beto", "turma": "3º B", "guia": {}, "historico": {}}})
    r = c.get("/web/api/transferidos/lista").get_json()
    por = {x["nome"]: x for x in r["transferidos"]}
    assert por["Beto"]["n_ciclos"] == 0 and por["Beto"]["ciclos_anteriores"] == []
    ana = por["Ana"]
    assert ana["n_ciclos"] == 1 and ana["data_transferencia"] == "10/10/2026"
    (cic,) = ana["ciclos_anteriores"]
    assert cic["data_transferencia"] == "05/03/2026" and cic["retorno_em"] == "20/04/2026" and cic["id_matricula"] == "M-1"
    assert cic["feitos"] == 3 and cic["guia"]["assinado_secretario"] == d and cic["parecer"]["digitalizado_em"] == d
    assert cic["arquivos"]["guia"].startswith("Ana (saída") and cic["destino"] == {"escola": "Escola Modelo", "fonte": "manual"}
    assert ana["status"] == "pendente"                       # o status da linha é o da saída ATUAL, não o do ciclo


def _fila_aluno(nome, data, retorno=None, **extra):
    return {"nome": nome, "turma": "5º A", "chamada": 1, "data_transferencia": data, "retornou": retorno is not None,
            "retorno": retorno, "situacao_fila": "x", "processar": False, **extra}


def test_transferidos_junta_a_fila_e_mostra_a_situacao_no_processo(dados, c, monkeypatch):
    from datetime import date
    monkeypatch.setattr(rotas._config, "data_corte_transferidos", lambda: date(2026, 6, 22))
    d = "2026-08-01T10:00:00"
    completo = {"emitido_em": d, "assinado_secretario": d, "assinado_diretor": d}
    gravar(dados, "transferidos.json", {
        "111": {"nome": "João", "turma": "5º A", "data_transferencia": "01/08/2026", "guia": completo, "historico": completo},
        "666": {"nome": "Fábio", "turma": "5º A", "data_transferencia": "10/07/2026", "guia": {"emitido_em": d}, "historico": {}}})
    gravar(dados, "fila_transferidos.json", {"gerado_em": "2026-11-20 10:00:00", "data_corte": "01/01/2000", "alunos": {
        "111": _fila_aluno("João", "01/08/2026"),
        "222": _fila_aluno("Ana", "10/03/2026"),                                                  # antes do corte
        "333": _fila_aluno("Caio", "01/08/2026", {"chamada": 9, "turma": "5º A", "data": "20/08/2026"}),   # voltou, sem registro
        "444": _fila_aluno("Duda", ""),                                                           # sem data válida
        "555": _fila_aluno("Edu", "01/09/2026"),                                                  # entra, ainda sem registro
        "666": _fila_aluno("Fábio", "10/07/2026", {"chamada": 3, "turma": "5º A", "data": "30/07/2026"}),  # tem registro e voltou
        "lixo": "não é dict"}})
    r = c.get("/web/api/transferidos/lista").get_json()
    por = {x["nome"]: x for x in r["transferidos"]}
    assert r["total"] == 6 and r["total_fora"] == 4                       # a data de corte vale a de agora, não a que a fila gravou
    assert r["fila"] == {"gerado_em": "2026-11-20 10:00:00", "data_corte": "22/06/2026"}
    assert {n: (x["situacao"], x["no_processo"]) for n, x in por.items()} == {
        "João": ("concluido", True), "Fábio": ("retornou", True), "Ana": ("antes_do_corte", False),
        "Caio": ("retornou", False), "Duda": ("sem_data", False), "Edu": ("a_processar", False)}
    assert por["Ana"]["status"] == "fora" and por["Ana"]["destino"] is None and por["Ana"]["feitos"] == 0
    assert por["Caio"]["retornou"] and por["Caio"]["retorno_em"] == "20/08/2026" and por["Caio"]["data_transferencia"] == "01/08/2026"
    assert por["Fábio"]["status"] == "parcial" and por["Fábio"]["guia"]["emitido_em"] == d      # quem voltou mantém os documentos
    assert r["contagem"] == {"completo": 1, "parcial": 1, "pendente": 0}                         # só quem tem registro
    cartoes = {x["label"]: x for x in r["cartoes"]}
    assert cartoes["Total"]["valor"] == 6 and cartoes["Total"]["sub"] == "transferidos da escola"
    assert cartoes["Fora do processo"]["valor"] == 4


def test_transferidos_sem_fila_continua_so_com_o_controle(dados, c):
    gravar(dados, "transferidos.json", {"111": {"nome": "João", "turma": "5º A", "guia": {}, "historico": {}}})
    r = c.get("/web/api/transferidos/lista").get_json()
    (j,) = r["transferidos"]
    assert j["no_processo"] and j["situacao"] == "a_processar" and j["retornou"] is False
    assert r["total_fora"] == 0 and r["fila"] == {} and "Fora do processo" not in {x["label"] for x in r["cartoes"]}
    gravar(dados, "fila_transferidos.json", {"alunos": "quebrada"})                  # fila ilegível não derruba a tela
    assert c.get("/web/api/transferidos/lista").get_json()["total"] == 1

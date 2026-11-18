"""Edição manual do pre_matricula.json: módulo, rotas GET/POST da tela e sobrevivência à próxima coleta."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import paths  # noqa: E402
from src.comum import pre_matricula_edicao as ed  # noqa: E402
from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402

ESCOLA = "JUDITH MACEDO SILVEIRA"
OUTRA = "ESCOLA MUNICIPAL OUTRA"


def base():
    return {
        "atualizado_em": "2026-11-01T08:00:00",
        "turmas_intencao": {
            "1º Ano": [
                {"cpf": "111", "nome": "MARIA SOZA", "pos": "1", "presente_na_ultima_coleta": True},
                {"cpf": "222", "nome": "JOAO", "pos": "2", "presente_na_ultima_coleta": True},
            ],
            "2º Ano": [{"cpf": "111", "nome": "MARIA SOZA", "pos": "3", "substituido_por_nova_tentativa": True}],
        },
        "cadastros": {
            "111": {"cpf": "111", "nome_aluno": "MARIA SOZA", "nome_mae": "ANA SOUZA", "email": "a@x.com",
                    "telefone": "(42) 99999-0000", "data_nascimento": "01/02/2020",
                    "escolas_escolhidas": {"opcoes": [{"opcao": 1, "escola": ESCOLA, "situacao": ""}]}},
        },
    }


# ───────────── módulo ─────────────

def test_corrigir_nome_atualiza_cadastro_e_todas_as_turmas_e_guarda_o_original():
    d = base()
    mudou = ed.corrigir(d, "111", {"nome_aluno": "  maria   souza "}, agora=datetime(2026, 11, 17, 10, 0))
    assert mudou == ["nome_aluno"]
    assert d["cadastros"]["111"]["nome_aluno"] == "MARIA SOUZA"                    # normaliza: espaços e caixa alta
    assert [a["nome"] for t in d["turmas_intencao"].values() for a in t if a["cpf"] == "111"] == ["MARIA SOUZA"] * 2
    assert d["turmas_intencao"]["1º Ano"][1]["nome"] == "JOAO"                    # outro aluno não muda
    assert d[ed.CHAVE]["111"]["nome_aluno"] == {
        "valor": "MARIA SOUZA", "original": "MARIA SOZA", "editado_em": "2026-11-17T10:00:00"}


def test_segunda_correcao_mantem_o_original_do_site():
    d = base()
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUSA"})
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUZA"})
    assert d[ed.CHAVE]["111"]["nome_aluno"]["original"] == "MARIA SOZA"


def test_voltar_ao_valor_original_apaga_a_correcao():
    d = base()
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUZA"})
    ed.corrigir(d, "111", {"nome_aluno": "maria soza"})
    assert ed.CHAVE not in d and d["cadastros"]["111"]["nome_aluno"] == "MARIA SOZA"


def test_sem_mudanca_nao_registra_nada():
    d = base()
    assert ed.corrigir(d, "111", {"nome_aluno": "Maria Soza"}) == []
    assert ed.CHAVE not in d


def test_normaliza_email_e_valida_campos():
    d = base()
    ed.corrigir(d, "111", {"email": "  MAE@Exemplo.COM "})
    assert d["cadastros"]["111"]["email"] == "mae@exemplo.com"
    for campo, valor, msg in [("email", "sem-arroba", "E-mail inválido"),
                              ("data_nascimento", "2020-02-01", "dd/mm/aaaa"),
                              ("data_nascimento", "31/02/2020", "inexistente"),
                              ("nome_aluno", "   ", "em branco"),
                              ("cpf", "999", "não pode ser editado"),
                              ("escolas_escolhidas", "x", "não pode ser editado")]:
        with pytest.raises(ed.EdicaoInvalidaError, match=msg):
            ed.corrigir(d, "111", {campo: valor})


def test_valor_invalido_nao_altera_nada_do_que_veio_junto():
    d = base()
    with pytest.raises(ed.EdicaoInvalidaError):
        ed.corrigir(d, "111", {"nome_aluno": "NOVO NOME", "email": "ruim"})
    assert d["cadastros"]["111"]["nome_aluno"] == "MARIA SOZA" and ed.CHAVE not in d


def test_aluno_inexistente_ou_sem_cpf():
    d = base()
    with pytest.raises(ed.EdicaoInvalidaError, match="não encontrado"):
        ed.corrigir(d, "999", {"nome_aluno": "X"})
    with pytest.raises(ed.EdicaoInvalidaError, match="sem CPF"):
        ed.corrigir(d, "", {"nome_aluno": "X"})


def test_aluno_sem_cadastro_so_pode_corrigir_o_nome():
    d = base()
    ed.corrigir(d, "222", {"nome_aluno": "JOÃO DA SILVA"})
    assert d["turmas_intencao"]["1º Ano"][1]["nome"] == "JOÃO DA SILVA"
    with pytest.raises(ed.EdicaoInvalidaError, match="só o nome"):
        ed.corrigir(d, "222", {"telefone": "1"})


def test_desfazer_um_campo_e_todos():
    d = base()
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUZA", "nome_mae": "ANA SOUSA"})
    assert ed.desfazer(d, "111", ["nome_aluno"]) == ["nome_aluno"]
    assert d["cadastros"]["111"]["nome_aluno"] == "MARIA SOZA" and d["turmas_intencao"]["1º Ano"][0]["nome"] == "MARIA SOZA"
    assert d["cadastros"]["111"]["nome_mae"] == "ANA SOUSA" and "nome_mae" in d[ed.CHAVE]["111"]
    assert ed.desfazer(d, "111") == ["nome_mae"]
    assert d["cadastros"]["111"]["nome_mae"] == "ANA SOUZA" and ed.CHAVE not in d
    assert ed.desfazer(d, "111") == []


def test_ler_registro_mostra_valor_atual_original_e_turmas():
    d = base()
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUZA"})
    r = ed.ler_registro(d, "111")
    assert r["tem_cadastro"] and r["turmas"] == ["1º Ano", "2º Ano"]
    nome = r["campos"]["nome_aluno"]
    assert nome["valor"] == "MARIA SOUZA" and nome["corrigido"] and nome["original"] == "MARIA SOZA"
    assert r["campos"]["email"]["corrigido"] is False
    assert r["ordem"][0] == "nome_aluno" and r["ordem"] == list(r["campos"])        # a API não preserva a ordem das chaves
    sem = ed.ler_registro(d, "222")
    assert sem["tem_cadastro"] is False and list(sem["campos"]) == ["nome_aluno"]
    assert ed.ler_registro(d, "999") is None


def test_aplicar_correcoes_espera_o_aluno_voltar_ao_arquivo():
    d = base()
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUZA"})
    d["turmas_intencao"] = {}
    d["cadastros"] = {}
    assert ed.aplicar_correcoes_manuais(d) == 0 and "111" in d[ed.CHAVE]       # a correção não se perde


# ───────────── a correção sobrevive à próxima coleta (o motivo de existir) ─────────────

def test_correcao_sobrevive_a_nova_coleta_e_ao_cadastro_regravado(tmp_path, monkeypatch):
    from src.automacao import pre_matricula as pm

    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)
    monkeypatch.setattr(paths, "ano_atual", lambda: 2026)
    d = base()
    ed.corrigir(d, "111", {"nome_aluno": "MARIA SOUZA"})
    pm.salvar_pre_matricula(d)

    # coleta nova: o site ainda traz o nome errado, e o cadastro é regravado por inteiro
    carregado = pm.carregar_pre_matricula()
    carregado["turmas_intencao"] = pm.mesclar_turmas_intencao(
        carregado["turmas_intencao"], {"1º Ano": [{"cpf": "111", "nome": "MARIA SOZA", "pos": "1"}]})
    carregado["cadastros"]["111"] = {"cpf": "111", "nome_aluno": "MARIA SOZA", "nome_mae": "ANA SOUZA"}
    pm.salvar_pre_matricula(carregado)

    final = pm.carregar_pre_matricula()
    assert final["cadastros"]["111"]["nome_aluno"] == "MARIA SOUZA"
    assert [a["nome"] for a in final["turmas_intencao"]["1º Ano"] if a["cpf"] == "111"] == ["MARIA SOUZA"]
    assert final[ed.CHAVE]["111"]["nome_aluno"]["original"] == "MARIA SOZA"


# ───────────── rotas ─────────────

@pytest.fixture()
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def c(dados):
    return create_app().test_client()


def gravar(pasta, conteudo):
    (pasta / "pre_matricula.json").write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")


def ler(pasta):
    return json.loads((pasta / "pre_matricula.json").read_text(encoding="utf-8"))


def test_get_registro(dados, c):
    gravar(dados, base())
    r = c.get("/web/api/prematricula/registro/111")
    assert r.status_code == 200
    assert r.get_json()["campos"]["nome_aluno"]["valor"] == "MARIA SOZA"
    assert c.get("/web/api/prematricula/registro/999").status_code == 404


def test_get_registro_sem_arquivo_e_arquivo_corrompido(dados, c):
    assert c.get("/web/api/prematricula/registro/111").status_code == 404
    (dados / "pre_matricula.json").write_text("{ruim", encoding="utf-8")
    r = c.get("/web/api/prematricula/registro/111")
    assert r.status_code == 500 and "ilegível" in r.get_json()["erro"]
    assert (dados / "pre_matricula.json").read_text(encoding="utf-8") == "{ruim"       # nunca é alterado


def test_post_corrige_grava_backup_e_nao_mexe_na_data_da_coleta(dados, c):
    gravar(dados, base())
    r = c.post("/web/api/prematricula/registro/111", json={"campos": {"nome_aluno": "maria souza"}})
    assert r.status_code == 200 and r.get_json()["mudou"] == ["nome_aluno"]
    assert r.get_json()["registro"]["campos"]["nome_aluno"]["corrigido"] is True

    novo = ler(dados)
    assert novo["cadastros"]["111"]["nome_aluno"] == "MARIA SOUZA"
    assert novo["atualizado_em"] == "2026-11-01T08:00:00"
    antes = json.loads((dados / "pre_matricula.json.antes_da_edicao").read_text(encoding="utf-8"))
    assert antes["cadastros"]["111"]["nome_aluno"] == "MARIA SOZA"


def test_post_invalido_devolve_400_e_nao_grava(dados, c):
    gravar(dados, base())
    antes = (dados / "pre_matricula.json").read_text(encoding="utf-8")
    assert c.post("/web/api/prematricula/registro/111", json={"campos": {"email": "ruim"}}).status_code == 400
    assert c.post("/web/api/prematricula/registro/111", json={"campos": {"cpf": "1"}}).status_code == 400
    assert c.post("/web/api/prematricula/registro/111", json={}).status_code == 400
    assert c.post("/web/api/prematricula/registro/999", json={"campos": {"nome_aluno": "X"}}).status_code == 400
    assert (dados / "pre_matricula.json").read_text(encoding="utf-8") == antes
    assert not (dados / "pre_matricula.json.antes_da_edicao").exists()


def test_post_sem_mudanca_nao_regrava(dados, c):
    gravar(dados, base())
    r = c.post("/web/api/prematricula/registro/111", json={"campos": {"nome_aluno": "MARIA SOZA"}})
    assert r.status_code == 200 and r.get_json()["mudou"] == []
    assert not (dados / "pre_matricula.json.antes_da_edicao").exists()


def test_post_desfazer(dados, c):
    gravar(dados, base())
    c.post("/web/api/prematricula/registro/111", json={"campos": {"nome_aluno": "MARIA SOUZA"}})
    r = c.post("/web/api/prematricula/registro/111", json={"desfazer": []})
    assert r.status_code == 200 and r.get_json()["mudou"] == ["nome_aluno"]
    d = ler(dados)
    assert d["cadastros"]["111"]["nome_aluno"] == "MARIA SOZA" and ed.CHAVE not in d


def test_post_bloqueado_enquanto_uma_automacao_roda(dados, c, monkeypatch):
    gravar(dados, base())
    monkeypatch.setitem(rotas._EXECUCOES, "prematricula_completa", {"status": "executando"})
    r = c.post("/web/api/prematricula/registro/111", json={"campos": {"nome_aluno": "X"}})
    assert r.status_code == 409 and "prematricula_completa" in r.get_json()["erro"]
    assert ler(dados)["cadastros"]["111"]["nome_aluno"] == "MARIA SOZA"
    monkeypatch.setitem(rotas._EXECUCOES, "prematricula_completa", {"status": "concluido"})
    assert c.post("/web/api/prematricula/registro/111", json={"campos": {"nome_aluno": "X"}}).status_code == 200


def test_lista_marca_o_aluno_corrigido(dados, c):
    gravar(dados, base())
    c.post("/web/api/prematricula/registro/111", json={"campos": {"nome_aluno": "MARIA SOUZA"}})
    por = {x["cpf"]: x for x in c.get("/web/api/prematricula/cadastros").get_json()["cadastros"]}
    assert por["111"]["nome_aluno"] == "MARIA SOUZA" and por["111"]["corrigidos"] == ["nome_aluno"]
    assert por["222"]["corrigidos"] == []


# ───────────── lista: fila de análise e "não é a 1ª opção" ─────────────

def _com_fila(nossa_situacao=""):
    return {
        "turmas_intencao": {"1º Ano": [
            {"cpf": "1", "nome": "NAO PRIMEIRA", "pos": "1", "nao_e_primeira_opcao": True,
             "situacao": "Cancelado", "motivo_cancelamento": "CADASTRO REFEITO: NOSSA ESCOLA NÃO É A 1ª OPÇÃO"},
            {"cpf": "2", "nome": "FILA", "pos": "2", "fila_analise": True,
             "encaminhado_de": [{"opcao": 1, "escola": OUTRA, "situacao": "A ESCOLA NÃO DISPÕE DE VAGA"}]},
        ]},
        "cadastros": {"2": {"nome_aluno": "FILA", "escolas_escolhidas": {"opcoes": [
            {"opcao": 1, "escola": OUTRA, "situacao": "A ESCOLA NÃO DISPÕE DE VAGA"},
            {"opcao": 2, "escola": ESCOLA, "situacao": nossa_situacao}]}}},
    }


def test_lista_nao_primeira_opcao_aparece_como_cancelado_com_motivo(dados, c):
    gravar(dados, _com_fila())
    r = c.get("/web/api/prematricula/cadastros").get_json()
    por = {x["nome_aluno"]: x for x in r["cadastros"]}
    assert por["NAO PRIMEIRA"]["situacao"] == "cancelado"
    assert por["NAO PRIMEIRA"]["motivo_cancelamento"] == "CADASTRO REFEITO: NOSSA ESCOLA NÃO É A 1ª OPÇÃO"


def test_lista_fila_de_analise_nao_vira_matriculado_por_causa_do_texto_de_outra_escola(dados, c):
    gravar(dados, _com_fila())
    r = c.get("/web/api/prematricula/cadastros").get_json()
    fila = next(x for x in r["cadastros"] if x["nome_aluno"] == "FILA")
    assert fila["situacao"] == "analise" and fila["encaminhado_de"][0]["escola"] == OUTRA
    assert r["contagem"] == {"matriculado": 0, "cancelado": 1, "pendente": 0, "analise": 1}
    assert {k["label"]: k["valor"] for k in r["cartoes"]}["Fila de análise"] == 1


@pytest.mark.parametrize("situacao,esperada", [("Matriculado. Observação:", "matriculado"),
                                                ("Cancelado. Motivo: Desistiu", "cancelado")])
def test_lista_aluno_sai_da_fila_quando_a_nossa_escola_decide(dados, c, situacao, esperada):
    gravar(dados, _com_fila(situacao))
    r = c.get("/web/api/prematricula/cadastros").get_json()
    fila = next(x for x in r["cadastros"] if x["nome_aluno"] == "FILA")
    assert fila["situacao"] == esperada and r["contagem"]["analise"] == 0

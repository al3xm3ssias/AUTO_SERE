"""Visão conjunta de alunos.json (básico) + alunos_completo.json (completo) na tela de Alunos."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import alunos_unificados as au  # noqa: E402
from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402


# ───────────── módulo: regras de junção ─────────────

def test_indexar_aceita_dict_por_cgm_e_lista_e_ignora_lixo():
    assert set(au.indexar_completo({"111": {"nome": "A"}, "222": {"cgm": "333", "nome": "B"}, "9": "x"})) == {"111", "333"}
    assert set(au.indexar_completo([{"cgm": "7", "nome": "C"}, {"nome": "sem cgm"}, "x"])) == {"7"}
    assert au.indexar_completo(None) == {} and au.indexar_completo("texto") == {}


def test_sem_cadastro_completo_o_aluno_fica_como_basico_e_intacto():
    aluno = {"Nome": "Ana", "CGM": "1"}
    r = au.unificar(aluno, None)
    assert r is aluno and r["_cadastro"] == "basico" and "_extras" not in r


def test_campo_vazio_no_basico_e_completado_pelo_completo():
    aluno = {"Nome": "Ana", "CGM": "1", "CPF": "", "Mãe": "—"}
    r = au.unificar(aluno, {"cpf": "123.456.789-09", "nome_mae": "Maria", "timestamp_coleta": "2026-10-30T10:00:00"})
    assert r["CPF"] == "123.456.789-09" and r["Mãe"] == "Maria"
    assert set(r["_preenchido_completo"]) == {"CPF", "Mãe"}
    assert r["_cadastro"] == "completo" and r["_coleta_completo"] == "2026-10-30T10:00:00" and r["_divergencias"] == []


def test_valores_diferentes_nao_sao_sobrescritos_e_viram_divergencia():
    aluno = {"Nome": "Ana", "CGM": "1", "Bairro": "Centro", "Telefone Residencial": "(42) 3222-1111"}
    r = au.unificar(aluno, {"bairro": "Nova Rússia", "fone_residencial": "4232221111"})
    assert r["Bairro"] == "Centro"                                               # o básico continua valendo
    assert r["_divergencias"] == [{"rotulo": "Bairro", "basico": "Centro", "completo": "Nova Rússia"}]
    # pontuação e acento não contam como diferença; telefone igual não diverge
    assert all(d["rotulo"] != "Telefone Residencial" for d in r["_divergencias"])


def test_abreviacao_nao_e_divergencia():
    r = au.unificar({"Nome": "Ana", "Sexo": "F"}, {"sexo": "Feminino"})
    assert r["_divergencias"] == []


def test_extras_agrupados_formatam_listas_e_deficiencias_e_pulam_vazios():
    r = au.unificar({"Nome": "Ana"}, {
        "tipo_certidao": "Nascimento", "numero_certidao": "", "folha_certidao": "—",
        "servicos_moradia": ["Água", "Luz"], "itens_moradia": [],
        "deficiencias": [{"nome": "Visual", "requer_atendimento": "Sim", "diagnostico": "Baixa visão"}, {"nome": "TDAH"}],
        "recursos_prova": ["Prova ampliada"], "observacao": "  Alérgico a dipirona  ",
    })
    por_rotulo = {e["rotulo"]: e for e in r["_extras"]}
    assert por_rotulo["Tipo da certidão"]["grupo"] == "Documentação"
    assert "Nº da certidão" not in por_rotulo and "Folha" not in por_rotulo and "Itens na moradia" not in por_rotulo
    assert por_rotulo["Serviços na moradia"]["valor"] == "Água; Luz"
    assert por_rotulo["Deficiências"]["valor"] == "Visual (requer atendimento: Sim; diagnóstico: Baixa visão); TDAH"
    assert por_rotulo["Recursos para prova"]["valor"] == "Prova ampliada"
    assert por_rotulo["Observação"]["valor"] == "Alérgico a dipirona"


def test_aluno_so_com_cadastro_completo_ganha_os_rotulos_do_basico():
    r = au.aluno_so_completo("555", {"nome": "Bia", "cgm": "", "nome_mae": "Carla", "cep": "84000-000", "cod_inep": "999"})
    assert r["Nome"] == "Bia" and r["CGM"] == "555" and r["Mãe"] == "Carla" and r["CEP"] == "84000-000"
    assert r["_cadastro"] == "so_completo" and r["_preenchido_completo"] == []
    assert [e["rotulo"] for e in r["_extras"]] == ["Código INEP"]
    # sem o campo nome, usa o nome que veio de turmas.json
    assert au.aluno_so_completo("6", {"nome_turmas_json": "Caio"})["Nome"] == "Caio"


# ───────────── rota /web/api/alunos/lista ─────────────

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
    "5º Ano A": [
        {"CGM": "111", "Nome": "João da Silva", "Situação": "Matriculado", "N": 1},
        {"CGM": "333", "Nome": "Bia Souza", "Situação": "Matriculado", "N": 2},
    ],
    "3º Ano B": [{"CGM": "222", "Nome": "Maria Conceição", "Situação": "Transferido", "N": 1}],
}
BASICO = [
    {"Nome": "João da Silva", "CGM": "111", "CPF": "", "Bairro": "Centro"},
    {"Nome": "Maria Conceição", "CGM": "222", "CPF": "111.222.333-44"},
]
COMPLETO = {
    "111": {"cgm": "111", "nome": "João da Silva", "cpf": "529.982.247-25", "bairro": "Uvaranas",
            "tipo_moradia": "Própria", "timestamp_coleta": "2026-10-30T09:15:00"},
    "333": {"cgm": "333", "nome": "Bia Souza", "nome_mae": "Carla", "cod_inep": "123"},
}


def test_sem_alunos_completo_json_a_lista_e_a_de_antes_com_o_aviso(dados, c):
    gravar(dados, "turmas.json", TURMAS)
    gravar(dados, "alunos.json", BASICO)
    r = c.get("/web/api/alunos/lista").get_json()
    assert r["total"] == 2 and r["completo"]["gerado"] is False and r["completo"]["total"] == 0
    assert all(a["_cadastro"] == "basico" for a in r["alunos"])
    assert [a["_turma"] for a in r["alunos"]] == ["5º Ano A", "3º Ano B"]
    assert "Nome" in r["campos"] and not any(k.startswith("_") for k in r["campos"])


def test_une_os_dois_cadastros_pelo_cgm_e_inclui_quem_so_tem_completo(dados, c):
    gravar(dados, "turmas.json", TURMAS)
    gravar(dados, "alunos.json", BASICO)
    gravar(dados, "alunos_completo.json", COMPLETO)
    r = c.get("/web/api/alunos/lista").get_json()
    por_cgm = {a["CGM"]: a for a in r["alunos"]}
    assert r["total"] == 3 and set(por_cgm) == {"111", "222", "333"}

    joao = por_cgm["111"]
    assert joao["_cadastro"] == "completo" and joao["CPF"] == "529.982.247-25"      # estava vazio no básico
    assert joao["Bairro"] == "Centro"                                               # básico não é sobrescrito
    assert joao["_divergencias"][0]["completo"] == "Uvaranas"
    assert {"rotulo": "Tipo de moradia", "grupo": "Perfil socioeconômico", "valor": "Própria"} in joao["_extras"]
    assert joao["_coleta_completo"] == "2026-10-30T09:15:00"

    assert por_cgm["222"]["_cadastro"] == "basico"
    bia = por_cgm["333"]
    assert bia["_cadastro"] == "so_completo" and bia["Nome"] == "Bia Souza" and bia["Mãe"] == "Carla"
    assert bia["_turma"] == "5º Ano A" and bia["_situacao"] == "Matriculado"        # turmas.json também vale para ele

    assert r["completo"]["gerado"] is True and r["completo"]["total"] == 2
    assert r["completo"]["so_completo"] == 1 and r["completo"]["com_divergencia"] == 1
    assert r["completo"]["atualizado_em"]


def test_arquivo_completo_corrompido_nao_derruba_a_tela(dados, c):
    gravar(dados, "alunos.json", BASICO)
    (dados / "alunos_completo.json").write_text("{ não é json", encoding="utf-8")
    r = c.get("/web/api/alunos/lista")
    assert r.status_code == 200 and r.get_json()["total"] == 2


def test_so_o_completo_existe_e_a_tela_ainda_lista(dados, c):
    gravar(dados, "alunos_completo.json", COMPLETO)
    r = c.get("/web/api/alunos/lista").get_json()
    assert r["total"] == 2 and all(a["_cadastro"] == "so_completo" for a in r["alunos"])

"""Aluno que retorna após transferência: mesmo CGM, dois cadastros (transferido + matriculado)."""
from src.comum.registros_aluno import chave_registro, consolidar_registros

# Trecho real da turma (N, CGM, Nome, Nasc, Idade, Sexo, Situação, Data)
LISTAGEM = """\
1\t1028996272\tALICIA BEATRIZ RAMOS SOARES\t10/07/2019\t7\tFeminino\tMatriculado\t04/02/2026
2\t1031702476\tANNA BEATRIZ CAETANO DIAS\t29/02/2020\t6\tFeminino\tTransferido\t13/05/2026
21\t1027953952\tMIKELY TAMIRIS ARRUDA MACOPPI\t26/04/2019\t7\tFeminino\tTransferido\t19/03/2026
24\t1034793642\tSAMUEL LUCCAS OLIVEIRA NASCIMENTO\t11/12/2019\t6\tMasculino\tTransferido\t20/05/2026
30\t1027644747\tBERNARDO HENRIQUE DOS SANTOS DOS REIS\t06/06/2019\t7\tMasculino\tMatriculado\t03/07/2026
31\t1031702476\tANNA BEATRIZ CAETANO DIAS\t29/02/2020\t6\tFeminino\tMatriculado\t16/10/2026
32\t1031708598\tGABRIELLY MICHAILIW DE MATOS\t10/07/2019\t7\tFeminino\tMatriculado\t19/10/2026
"""


def _alunos(txt=LISTAGEM):
    out = []
    for linha in txt.strip().splitlines():
        n, cgm, nome, nasc, idade, sexo, sit, data = linha.split("\t")
        out.append({"N": int(n), "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Idade": int(idade),
                    "Sexo": sexo, "Situação": sit, "Data Matricula": data})
    return out


def test_retorno_mantem_transferido_e_matriculado():
    res = consolidar_registros(_alunos())
    anna = [a for a in res if a["CGM"] == "1031702476"]
    assert len(res) == 7 and len(anna) == 2
    assert {a["Situação"] for a in anna} == {"Transferido", "Matriculado"}
    mat = next(a for a in anna if a["Situação"] == "Matriculado")
    tra = next(a for a in anna if a["Situação"] == "Transferido")
    assert mat["Data Matricula"] == "16/10/2026" and mat["N"] == 31 and mat.get("Retorno") is True
    assert tra["Data Matricula"] == "13/05/2026" and tra["N"] == 2 and "Retorno" not in tra


def test_demais_alunos_nao_sao_marcados():
    res = consolidar_registros(_alunos())
    assert [a["CGM"] for a in res if a.get("Retorno")] == ["1031702476"]


def test_leitura_repetida_e_descartada():
    dados = _alunos()
    res = consolidar_registros(dados + [dict(dados[1])])  # mesma linha lida 2x (retry)
    assert len(res) == len(dados)


def test_mesmo_cgm_mesma_situacao_mas_n_diferente_mantem_ambos():
    a = {"N": 5, "CGM": "9", "Nome": "X", "Situação": "Matriculado", "Data Matricula": "04/02/2026"}
    b = dict(a, N=40)
    assert len(consolidar_registros([a, b])) == 2


def test_ordem_preservada_e_chave_inclui_n():
    res = consolidar_registros(_alunos())
    assert [a["N"] for a in res] == [1, 2, 21, 24, 30, 31, 32]
    assert chave_registro(res[1]) != chave_registro(res[5])


def test_retorno_com_n_nao_posterior_avisa_mas_mantem():
    tra = {"N": 10, "CGM": "7", "Nome": "Y", "Situação": "Transferido", "Data Matricula": "01/03/2026"}
    mat = {"N": 3, "CGM": "7", "Nome": "Y", "Situação": "Matriculado", "Data Matricula": "01/09/2026"}
    res = consolidar_registros([tra, mat])
    assert len(res) == 2 and mat.get("Retorno") is True


# ── cruzamento alunos.json × turmas.json (tela Alunos) ──────────────────
from src.comum.registros_aluno import casar_com_turmas, registro_principal


def _cands(cgm):
    return [dict(a, _turma="1º Ano Integral A") for a in consolidar_registros(_alunos()) if a["CGM"] == cgm]


def test_alunos_json_antigo_casa_por_ordem():
    """alunos.json sem Situação/Data: 1ª ocorrência → transferido, 2ª → matriculado."""
    cands, usados = _cands("1031702476"), set()
    antigo = {"CGM": "1031702476", "Nome": "ANNA BEATRIZ CAETANO DIAS"}
    r1 = casar_com_turmas(dict(antigo), cands, usados)
    r2 = casar_com_turmas(dict(antigo), cands, usados)
    assert (r1["Situação"], r2["Situação"]) == ("Transferido", "Matriculado")
    assert casar_com_turmas(dict(antigo), cands, usados) is None


def test_alunos_json_novo_casa_por_situacao_data_independente_da_ordem():
    cands, usados = _cands("1031702476"), set()
    mat = {"CGM": "1031702476", "Situação": "Matriculado", "Data Matricula": "16/10/2026", "N": 31}
    tra = {"CGM": "1031702476", "Situação": "Transferido", "Data Matricula": "13/05/2026", "N": 2}
    assert casar_com_turmas(mat, cands, usados)["Situação"] == "Matriculado"
    assert casar_com_turmas(tra, cands, usados)["Situação"] == "Transferido"


def test_registro_principal_prefere_matriculado_vigente():
    assert registro_principal(_cands("1031702476"))["Situação"] == "Matriculado"

"""Opções compartilhadas: CGM, turmas, matriculados/transferidos, teste e linha de comando."""
import argparse

import pytest

from src.comum import opcoes_execucao as oe
from src.comum.opcoes_execucao import Opcoes

NOMES = ["INFANTIL 4 Integral A", "INFANTIL 5 Integral A", "1º Ano Integral A", "3º Ano Integral A",
         "3º Ano Integral B", "5º Ano Integral A", "5º Ano Integral B", "10º Ano A"]


def aluno(cgm, nome, situacao="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": situacao}


TURMAS = {
    "3º Ano Integral A": [aluno("3000000001", "Ana"), aluno("3000000002", "Beto", "Transferido")],
    "3º Ano Integral B": [aluno("3000000003", "Caio")],
    "5º Ano Integral A": [aluno("5000000001", "Duda"), aluno("5000000002", "Edu", "transferido"),   # caixa baixa
                          aluno("3000000001", "Ana (repetida)")],                                   # CGM repetido noutra turma
    "5º Ano Integral B": [aluno("5000000003", "Fabi", "Transferido")],
    "1º Ano Integral A": [],
}


# ───────────── CGM ─────────────

@pytest.mark.parametrize("texto", [
    "123456789\n987654321\n456789123",
    "123456789,987654321,456789123",
    "123456789;987654321;456789123",
    "123456789 , 987654321 ;  456789123",
    "123456789, 987654321;\n456789123\n",
    "  123456789\r\n987654321;456789123,  ",
])
def test_cgm_aceita_os_formatos_pedidos(texto):
    r = oe.analisar_cgms(texto)
    assert r.validos == ("123456789", "987654321", "456789123") and r.invalidos == () and r.repetidos == 0


def test_cgm_mistura_de_formatos_do_exemplo():
    r = oe.analisar_cgms("123456789, 987654321;\n456789123\n111222333")
    assert r.validos == ("123456789", "987654321", "456789123", "111222333")


def test_cgm_remove_repetidos_mantendo_a_ordem_e_conta():
    r = oe.analisar_cgms("222222222, 111111111;222222222\n111111111 333333333")
    assert r.validos == ("222222222", "111111111", "333333333") and r.repetidos == 2


@pytest.mark.parametrize("ruim", ["abc", "1234", "12345678901234", "12a45678", "123-456-789"])
def test_cgm_formato_invalido_e_separado(ruim):
    r = oe.analisar_cgms(f"123456789, {ruim}")
    assert r.validos == ("123456789",) and r.invalidos == (ruim,)


@pytest.mark.parametrize("vazio", [None, "", "   ", ",;\n ,", []])
def test_cgm_vazio(vazio):
    r = oe.analisar_cgms(vazio)
    assert r == oe.ResultadoCgm((), (), 0)


def test_cgm_aceita_lista_de_numeros():
    assert oe.analisar_cgms([1234567890, "1234567891", 1234567890]).validos == ("1234567890", "1234567891")


# ───────────── turmas ─────────────

def test_agrupa_por_ano():
    g = oe.agrupar_turmas(NOMES)
    assert g["3º Ano Integral"] == ["3º Ano Integral A", "3º Ano Integral B"]
    assert g["INFANTIL 4 Integral"] == ["INFANTIL 4 Integral A"] and g["10º Ano"] == ["10º Ano A"]


@pytest.mark.parametrize("pedido,esperado", [
    ([], NOMES), (["todas"], NOMES), (["Todas"], NOMES),
    (["5º Ano Integral A"], ["5º Ano Integral A"]),
    (["5º ano integral a"], ["5º Ano Integral A"]),                       # sem diferenciar caixa
    (["5º Ano Integral"], ["5º Ano Integral A", "5º Ano Integral B"]),    # o ano inteiro
    (["5"], ["5º Ano Integral A", "5º Ano Integral B"]),                  # início do nome
    (["1"], ["1º Ano Integral A"]),                                       # "1" NÃO pega "10º"
    (["10"], ["10º Ano A"]),
    (["infantil 4"], ["INFANTIL 4 Integral A"]),
    (["3", "1"], ["3º Ano Integral A", "3º Ano Integral B", "1º Ano Integral A"]),
    (["5", "5º Ano Integral A"], ["5º Ano Integral A", "5º Ano Integral B"]),   # sem repetir
])
def test_resolver_turmas(pedido, esperado):
    assert sorted(oe.resolver_turmas(pedido, NOMES)) == sorted(esperado)


def test_resolver_turmas_desconhecida_levanta_com_o_valor():
    with pytest.raises(ValueError, match="Turma não encontrada: 9º"):
        oe.resolver_turmas(["9º"], NOMES)


# ───────────── seleção de alunos ─────────────

def test_padrao_e_so_matriculados_de_todas_as_turmas():
    s = oe.selecionar_alunos(TURMAS)
    assert [a["CGM"] for a in s.alunos] == ["3000000001", "3000000003", "5000000001"]
    assert (s.matriculados, s.transferidos) == (3, 0)


def test_so_transferidos():
    s = oe.selecionar_alunos(TURMAS, matriculados=False, transferidos=True)
    assert [a["CGM"] for a in s.alunos] == ["3000000002", "5000000002", "5000000003"]   # "transferido" em minúsculas conta
    assert all(a["Situacao"] == "Transferido" for a in s.alunos)


def test_matriculados_e_transferidos():
    s = oe.selecionar_alunos(TURMAS, matriculados=True, transferidos=True)
    assert s.total == 6 and (s.matriculados, s.transferidos) == (3, 3)


def test_por_turma_e_por_ano():
    # a "Ana (repetida)" (mesmo CGM de uma aluna do 3º A) está listada também no 5º A: filtrando só o 5º A, é a 1ª vez que ela aparece
    assert [a["Nome"] for a in oe.selecionar_alunos(TURMAS, turmas=["5º Ano Integral A"]).alunos] == ["Duda", "Ana (repetida)"]
    s = oe.selecionar_alunos(TURMAS, turmas=["3º Ano Integral"], matriculados=True, transferidos=True)
    assert [a["Nome"] for a in s.alunos] == ["Ana", "Beto", "Caio"]
    assert s.turmas == ["3º Ano Integral A", "3º Ano Integral B"]


def test_cgm_repetido_em_duas_turmas_conta_uma_vez_na_primeira():
    s = oe.selecionar_alunos(TURMAS, turmas=["3", "5"], matriculados=True, transferidos=True)
    ana = [a for a in s.alunos if a["CGM"] == "3000000001"]
    assert len(ana) == 1 and ana[0]["Turma"] == "3º Ano Integral A"


def test_modo_cgm_ignora_turma_e_situacao_e_avisa_dos_que_nao_existem():
    s = oe.selecionar_alunos(TURMAS, cgms=["3000000002", "5000000003", "9999999999"], turmas=["1"], matriculados=True)
    assert [a["CGM"] for a in s.alunos] == ["3000000002", "5000000003"]            # transferidos entram: foram pedidos
    assert s.cgms_nao_encontrados == ["9999999999"]


def test_turma_vazia_nao_quebra():
    assert oe.selecionar_alunos(TURMAS, turmas=["1º Ano Integral A"]).total == 0


def test_filtrar_turmas_por_situacao_mantem_todas_as_turmas():
    so_transf = oe.filtrar_turmas_por_situacao(TURMAS, matriculados=False, transferidos=True)
    assert list(so_transf) == list(TURMAS)
    assert [a["CGM"] for a in so_transf["3º Ano Integral A"]] == ["3000000002"]
    assert so_transf["3º Ano Integral B"] == [] and so_transf["1º Ano Integral A"] == []
    assert TURMAS["3º Ano Integral A"][0]["CGM"] == "3000000001"                 # original intacto


# ───────────── payload da interface ─────────────

def test_payload_completo():
    o = oe.opcoes_do_payload(
        {"turmas": ["5º Ano Integral"], "matriculados": True, "transferidos": True, "modo_teste": True, "erros": True},
        {"turma", "situacao", "teste", "erros"}, NOMES)
    assert o == Opcoes(("5º Ano Integral A", "5º Ano Integral B"), True, True, (), True, True)


def test_payload_ignora_o_que_o_script_nao_declarou():
    o = oe.opcoes_do_payload({"turmas": ["5"], "transferidos": True, "modo_teste": True, "cgms_texto": "abc"}, set(), NOMES)
    assert o == Opcoes()                          # nada de teste/turma/situação/cgm: não valida nem aplica


def test_payload_padrao_e_so_matriculados():
    o = oe.opcoes_do_payload({}, {"situacao"})
    assert (o.matriculados, o.transferidos) == (True, False)


def test_payload_sem_nenhuma_situacao_e_recusado():
    with pytest.raises(ValueError, match="Matriculados ou Transferidos"):
        oe.opcoes_do_payload({"matriculados": False, "transferidos": False}, {"situacao"})


def test_payload_cgm_obrigatorio_e_validado():
    with pytest.raises(ValueError, match="ao menos um CGM"):
        oe.opcoes_do_payload({"cgms_texto": " "}, {"cgm"}, cgm_obrigatorio=True)
    with pytest.raises(ValueError, match="formato inválido: 12ab"):
        oe.opcoes_do_payload({"cgms_texto": "123456789, 12ab"}, {"cgm"})
    o = oe.opcoes_do_payload({"cgms_texto": "123456789, 987654321;123456789"}, {"cgm"}, cgm_obrigatorio=True)
    assert o.cgms == ("123456789", "987654321")


def test_payload_cgm_opcional_em_branco_nao_e_erro():
    """No analisa_sere o CGM é uma alternativa: em branco vale turma/situação."""
    assert oe.opcoes_do_payload({"cgms_texto": "  "}, {"cgm", "turma"}).cgms == ()
    assert oe.opcoes_do_payload({}, {"cgm"}).cgms == ()


def test_payload_turma_desconhecida():
    with pytest.raises(ValueError, match="Turma não encontrada"):
        oe.opcoes_do_payload({"turmas": ["99"]}, {"turma"}, NOMES)


# ───────────── linha de comando ─────────────

def _parser(**k):
    p = argparse.ArgumentParser()
    oe.adicionar_argumentos(p, **k)
    return p


def test_cli_exemplos_do_pedido():
    p = _parser()
    o = oe.opcoes_do_argparse(p.parse_args(["--turma", "5", "--matriculados"]))
    assert o.turmas == ("5",) and o.matriculados and not o.transferidos
    o = oe.opcoes_do_argparse(p.parse_args(["--turma", "5", "--matriculados", "--transferidos"]))
    assert o.turmas == ("5",) and o.matriculados and o.transferidos


def test_cli_compatibilidade_sem_flags_e_so_matriculados():
    o = oe.opcoes_do_argparse(_parser().parse_args([]))
    assert (o.turmas, o.matriculados, o.transferidos, o.cgms) == ((), True, False, ())


def test_cli_transferidos_sozinho_nao_inclui_matriculados():
    o = oe.opcoes_do_argparse(_parser().parse_args(["--transferidos"]))
    assert (o.matriculados, o.transferidos) == (False, True)


def test_cli_turma_sem_valor_continua_sendo_o_modo_interativo():
    ns = _parser().parse_args(["--turma"])
    assert ns.turma == []                               # "flag presente, sem valor" (antes era store_true)
    assert _parser().parse_args([]).turma is None       # flag ausente


def test_cli_turma_com_nome_de_varias_palavras_e_varias_turmas():
    ns = _parser().parse_args(["--turma", "5º Ano Integral A", "3º Ano Integral", "--transferidos"])
    assert ns.turma == ["5º Ano Integral A", "3º Ano Integral"] and ns.transferidos


def test_cli_cgm_em_varios_formatos():
    o = oe.opcoes_do_argparse(_parser().parse_args(["--cgm", "123456789,987654321;456789123", "111222333"]))
    assert o.cgms == ("123456789", "987654321", "456789123", "111222333")
    with pytest.raises(ValueError, match="inválido"):
        oe.opcoes_do_argparse(_parser().parse_args(["--cgm", "xyz"]))


def test_cli_teste_e_erros_so_existem_se_pedidos():
    with pytest.raises(SystemExit):
        _parser().parse_args(["--teste"])
    o = oe.opcoes_do_argparse(_parser(teste=True, erros=True).parse_args(["--teste", "--erros"]))
    assert o.modo_teste and o.erros


@pytest.mark.parametrize("opcoes,recursos,esperado", [
    (Opcoes(("5º Ano",), True, False), {"turma", "situacao"}, ["--turma", "5º Ano", "--matriculados"]),
    (Opcoes(("5",), True, True), {"turma", "situacao"}, ["--turma", "5", "--matriculados", "--transferidos"]),
    (Opcoes(cgms=("123456789", "987654321")), {"cgm"}, ["--cgm", "123456789", "987654321"]),
    (Opcoes(modo_teste=True, erros=True), {"teste", "erros"}, ["--teste", "--erros"]),
    (Opcoes(("5",), True, True, ("1234567890",), True, True), set(), []),                  # nada declarado: nada vai
    (Opcoes(), {"turma", "situacao"}, ["--matriculados"]),
])
def test_argv_cli(opcoes, recursos, esperado):
    assert oe.argv_cli(opcoes, recursos) == esperado


def test_ida_e_volta_interface_para_linha_de_comando():
    """O que a tela monta como argv é lido de volta, pelo parser da CLI, nas mesmas opções."""
    recursos = {"turma", "situacao", "cgm", "teste", "erros"}
    original = Opcoes(("5º Ano Integral A", "3º Ano Integral"), True, True, ("123456789", "987654321"), True, False)
    lido = oe.opcoes_do_argparse(_parser(teste=True, erros=True).parse_args(oe.argv_cli(original, recursos)))
    assert lido == original

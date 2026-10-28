"""Executor de linha de comando (src/comum/cli.py): as mesmas opções, validação e prévia da tela."""
import sys

import pytest

from src.comum import cli, opcoes_execucao as oe, registro_scripts as reg
from src.comum.execucao_gui import ExecucaoEmBackground
from src.web.api import rotas


def _al(cgm, nome, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": sit}


TURMAS = {
    "3º Ano Integral A": [_al("3000000001", "Ana"), _al("3000000002", "Beto", "Transferido")],
    "3º Ano Integral B": [_al("3000000003", "Caio")],
    "5º Ano Integral A": [_al("5000000001", "Duda")],
}


@pytest.fixture()
def turmas(monkeypatch):
    monkeypatch.setattr(cli, "carregar_turmas", lambda: TURMAS)
    return TURMAS


class Capturador:
    """Troca as funções reais por falsas e anota o que foi chamado."""

    def __init__(self, monkeypatch):
        self.mp, self.chamadas = monkeypatch, []

    def plano(self, chave, plano):
        script = reg.REGISTRO[chave]
        self.mp.setitem(reg.REGISTRO, chave, reg.Script(**{**script.__dict__, "planejar": lambda o, p, tj, c: plano}))


def _gui(chamadas, linhas=("linha do script",), falha=False, nome="executar_validar"):
    def funcao(callback=None, **kw):
        chamadas.append(kw)
        ex = ExecucaoEmBackground(callback=callback)

        async def coro():
            for l in linhas:
                print(l)
            if falha:
                raise RuntimeError("deu ruim")
        ex.iniciar(coro())
        return ex
    funcao.__name__ = nome
    return funcao


# ───────────── listar e ajuda ─────────────

def test_listar_mostra_todas_as_automacoes_registradas(capsys):
    assert cli.main(["listar"]) == 0
    saida = capsys.readouterr().out
    for chave in reg.REGISTRO:
        assert chave in saida
    assert "[pede confirmação]" in saida


def test_nomes_vem_da_lista_da_tela():
    da_tela = {i["chave"]: i["nome"] for i in rotas.AUTOMACOES_DISPONIVEIS}
    for chave in reg.REGISTRO:
        assert cli.NOMES[chave] == da_tela[chave], chave


def test_ajuda_mostra_so_as_opcoes_do_script(capsys):
    for argv, tem, nao_tem in [
        (["termos", "--ajuda"], ["--tema"], ["--turma", "--cgm", "--teste"]),
        (["aluno", "--ajuda"], ["--cgm", "--teste", "--erros", "--faltando"], ["--turma", "--transferidos"]),
        (["validar", "--ajuda"], ["--turma", "--matriculados", "--transferidos", "--teste", "--confirmo"], ["--cgm", "--tema"]),
        (["backup", "--ajuda"], ["--simular"], ["--turma", "--confirmo"]),
        (["prematricula_completa", "--ajuda"], ["--debug", "--pular-pendentes"], ["--turma", "--teste"]),
    ]:
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 0
        saida = capsys.readouterr().out
        assert all(t in saida for t in tem), (argv, saida)
        assert not any(n in saida for n in nao_tem), (argv, saida)


def test_script_desconhecido_e_recusado_com_a_lista(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["nao_existe"])
    assert e.value.code == 2 and "validar" in capsys.readouterr().err


# ───────────── validação: o mesmo que a tela ─────────────

@pytest.mark.parametrize("argv,trecho", [
    (["validar", "--turma", "99"], "Turma não encontrada: 99"),
    (["validar", "--turma"], "ao menos um valor"),
    (["aluno"], "ao menos um CGM"),
    (["aluno", "--cgm", "123456789,xx"], "formato inválido: xx"),
    (["documentos"], "tipo de documento"),
    (["documentos", "--idtipo", "999999"], "Valor inválido"),
    (["alunos", "--modo", "turbo"], "Valor inválido"),
    (["cep", "--raio-km", "abc"], "Raio inválido"),
    (["termos"], "tema do termo"),
])
def test_pedido_invalido_sai_com_codigo_2_e_mensagem(turmas, capsys, argv, trecho):
    try:
        codigo = cli.main(argv + ["--simular"])
    except SystemExit as e:                     # argparse recusa valores fora das opções
        codigo = e.code
    err = capsys.readouterr().err
    assert codigo == 2 and trecho in err, err


def test_sem_turmas_json_orienta(monkeypatch, capsys):
    monkeypatch.setattr(cli, "carregar_turmas", lambda: {})
    assert cli.main(["validar", "--simular"]) == 2
    assert "cli turmas" in capsys.readouterr().err


# ───────────── prévia e simulação ─────────────

def test_simular_mostra_a_previa_e_o_que_executaria_sem_executar(turmas, monkeypatch, capsys):
    chamadas = []
    import src.automacao.executar_validar as ev
    monkeypatch.setattr(ev, "executar_validar", _gui(chamadas))
    assert cli.main(["validar", "--turma", "3º Ano Integral", "--matriculados", "--transferidos", "--simular"]) == 0
    saida = capsys.readouterr().out
    assert "Prévia:    3 aluno(s) — 2 matriculado(s) e 1 transferido(s) — em 2 turma(s)." in saida
    assert "executar_validar(" in saida and "turmas_selecionadas=['3º Ano Integral A', '3º Ano Integral B']" in saida
    assert "turmas=<3 itens>" in saida and "simulação: nada foi executado" in saida
    assert chamadas == []


def test_simular_por_cgm_avisa_dos_que_nao_existem(turmas, capsys):
    assert cli.main(["aluno", "--cgm", "3000000001,9999999999", "--simular"]) == 0
    assert "1 de 2 CGM(s)" in capsys.readouterr().out


def test_padrao_sem_flags_de_situacao_e_so_matriculados(turmas, capsys):
    assert cli.main(["validar", "--simular"]) == 0
    assert "3 aluno(s) — 3 matriculado(s) — em 3 turma(s)." in capsys.readouterr().out
    assert cli.main(["validar", "--transferidos", "--simular"]) == 0
    assert "1 aluno(s) — 1 transferido(s)" in capsys.readouterr().out


def test_o_plano_da_linha_de_comando_e_igual_ao_da_tela(turmas):
    """Mesmo script, mesmas escolhas: o plano que a CLI monta é o que a tela monta pelo JSON."""
    ns = cli.montar_parser().parse_args(["analisa_sere", "--turma", "3º Ano Integral", "--matriculados", "--transferidos"])
    script = reg.REGISTRO["analisa_sere"]
    p_cli = cli._payload_do_namespace(script, ns)
    p_tela = {"turmas": ["3º Ano Integral"], "matriculados": True, "transferidos": True, "cgms_texto": "", "erros": False}
    assert p_cli == p_tela
    o = oe.opcoes_do_payload(p_cli, script.recursos, list(TURMAS))
    assert script.planejar(o, p_cli, TURMAS, {"args_flags": []}).kwargs["args_extras"] == \
        ["--turma", "3º Ano Integral A", "3º Ano Integral B", "--matriculados", "--transferidos"]


# ───────────── confirmação ─────────────

@pytest.fixture()
def validar_falso(monkeypatch):
    chamadas = []
    import src.automacao.executar_validar as ev
    monkeypatch.setattr(ev, "executar_validar", _gui(chamadas))
    return chamadas


def test_sem_terminal_e_sem_confirmo_nao_executa(turmas, validar_falso, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert cli.main(["validar", "--turma", "5"]) == 2
    err = capsys.readouterr()
    assert "--confirmo" in err.err and "ATENÇÃO" in err.out and validar_falso == []


def test_confirmo_executa(turmas, validar_falso, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert cli.main(["validar", "--turma", "5", "--confirmo"]) == 0
    assert len(validar_falso) == 1 and "linha do script" in capsys.readouterr().out


def test_teste_dispensa_a_confirmacao(turmas, validar_falso, monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert cli.main(["validar", "--turma", "5", "--teste"]) == 0
    assert validar_falso[0]["modo_teste"] is True


class _Tty:
    def isatty(self):
        return True


@pytest.mark.parametrize("resposta,executa", [("SIM", True), ("sim", True), ("nao", False), ("", False)])
def test_pergunta_no_terminal(turmas, validar_falso, monkeypatch, resposta, executa):
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda *_: resposta)
    assert cli.main(["validar", "--turma", "5"]) == (0 if executa else 2)
    assert bool(validar_falso) is executa


def test_script_de_leitura_nao_pergunta_nada(turmas, monkeypatch, capsys):
    chamadas = []
    import src.automacao.executar_analisa as ea
    monkeypatch.setattr(ea, "executar_analisa", _gui(chamadas))
    monkeypatch.setattr(sys, "stdin", None)
    assert cli.main(["analisa_sere", "--turma", "5"]) == 0
    assert chamadas[0]["args_extras"] == ["--turma", "5º Ano Integral A", "--matriculados"]


# ───────────── execução de verdade dos três tipos de plano ─────────────

def test_plano_gui_mostra_o_log_e_devolve_1_se_falhar(turmas, monkeypatch, capsys):
    import src.automacao.executar_analisa as ea
    monkeypatch.setattr(ea, "executar_analisa", _gui([], linhas=("abrindo", "lendo 3 alunos"), falha=True))
    assert cli.main(["analisa_sere"]) == 1
    saida = capsys.readouterr()
    assert "abrindo" in saida.out and "lendo 3 alunos" in saida.out and "status: erro" in saida.err


def test_plano_coroutine_e_sync(turmas, monkeypatch, capsys):
    import src.automacao.turmas as turmas_mod
    import src.comum.backup as bk
    feito = []

    async def fake_turmas():
        feito.append("turmas"); print("coletando turmas")

    monkeypatch.setattr(turmas_mod, "coletar_turmas_e_alunos_via_login", fake_turmas)
    monkeypatch.setattr(bk, "executar_backup", lambda: feito.append("backup") or print("backup ok"))
    assert cli.main(["turmas"]) == 0 and cli.main(["backup"]) == 0
    assert feito == ["turmas", "backup"] and "coletando turmas" in capsys.readouterr().out


def test_excecao_no_script_vira_mensagem_e_codigo_1(turmas, monkeypatch, capsys):
    import src.comum.backup as bk
    def quebra():
        raise OSError("disco cheio")
    monkeypatch.setattr(bk, "executar_backup", quebra)
    assert cli.main(["backup"]) == 1
    assert "ERRO: OSError: disco cheio" in capsys.readouterr().err


def test_extras_viram_argumentos(turmas, monkeypatch):
    import src.automacao.alunos_completo as ac
    visto = {}

    async def fake(modo_rapido=False):
        visto["rapido"] = modo_rapido

    monkeypatch.setattr(ac, "coletar_cadastro_completo_via_login", fake)
    assert cli.main(["alunos", "--modo", "completo", "--rapido"]) == 0
    assert visto == {"rapido": True}

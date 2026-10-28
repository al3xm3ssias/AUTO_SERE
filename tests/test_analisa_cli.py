"""analisa_arquivos_sere: seleção por turma/situação/CGM na linha de comando (sem navegador)."""
import asyncio
import json
import sys

import pytest

import src.relatorios.analisa_arquivos_sere as an


class _Parou(Exception):
    def __init__(self, alunos):
        self.alunos = alunos


def _aluno(cgm, nome, situacao="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": situacao}


TURMAS = {
    "5º Ano Integral A": [_aluno("5000000001", "Duda"), _aluno("5000000002", "Edu", "Transferido")],
    "5º Ano Integral B": [_aluno("5000000003", "Fabi"), _aluno("5000000004", "Gil", "Transferido")],
    "3º Ano Integral A": [_aluno("3000000001", "Ana"), _aluno("3000000002", "Beto", "Transferido")],
}


@pytest.fixture()
def rodar(tmp_path, monkeypatch):
    """rodar("--turma", "5", ...) → lista de alunos que o script processaria (ou SystemExit)."""
    turmas = tmp_path / "turmas.json"
    alunos = tmp_path / "alunos.json"
    turmas.write_text(json.dumps(TURMAS), encoding="utf-8")
    alunos.write_text(json.dumps([{"CGM": c["CGM"], "Nome": c["Nome"]} for v in TURMAS.values() for c in v]), encoding="utf-8")
    monkeypatch.setattr(an, "TURMAS_JSON", str(turmas))
    monkeypatch.setattr(an, "ALUNOS_JSON", str(alunos))
    monkeypatch.setattr(an, "ERROS_JSON", str(tmp_path / "erros.json"))

    async def fake_executar(alunos_sel, gerenciador):
        raise _Parou(alunos_sel)

    monkeypatch.setattr(an, "executar", fake_executar)

    def _rodar(*argv):
        monkeypatch.setattr(sys, "argv", ["analisa", *argv])
        with pytest.raises(_Parou) as e:
            asyncio.run(an.main())
        return e.value.alunos

    return _rodar


def cgms(alunos):
    return sorted(a["CGM"] for a in alunos)


# ── o que já existia continua igual ──

def test_sem_flags_continua_sendo_so_matriculados_de_todas(rodar):
    assert cgms(rodar()) == ["3000000001", "5000000001", "5000000003"]


def test_todos_continua_sendo_matriculados_e_transferidos(rodar):
    assert len(rodar("--todos")) == 6


def test_transferidos_sozinho_continua_sendo_so_transferidos(rodar):
    assert cgms(rodar("--transferidos")) == ["3000000002", "5000000002", "5000000004"]


def test_parser_antigo_aceita_todas_as_flags_de_sempre():
    p = an.criar_parser()
    ns = p.parse_args(["--erros", "--rapido", "--alunos", "--todos", "--transferidos", "--turma"])
    assert ns.erros and ns.rapido and ns.alunos and ns.todos and ns.transferidos and ns.turma == []


# ── as combinações pedidas ──

def test_turma_5_matriculados(rodar):
    assert cgms(rodar("--turma", "5", "--matriculados")) == ["5000000001", "5000000003"]


def test_turma_5_matriculados_e_transferidos(rodar):
    assert cgms(rodar("--turma", "5", "--matriculados", "--transferidos")) == [
        "5000000001", "5000000002", "5000000003", "5000000004"]


def test_turma_5_so_transferidos_nao_traz_matriculados(rodar):
    # --transferidos + --turma: antes eram excludentes; agora combinam
    assert cgms(rodar("--turma", "5", "--transferidos")) == ["5000000002", "5000000004"]


def test_turma_especifica_pelo_nome_completo(rodar):
    assert cgms(rodar("--turma", "5º Ano Integral B", "--matriculados")) == ["5000000003"]


def test_duas_turmas_de_uma_vez(rodar):
    assert cgms(rodar("--turma", "5º Ano Integral A", "3º Ano Integral A", "--matriculados")) == ["3000000001", "5000000001"]


def test_so_matriculados_sem_turma_e_todas_as_turmas(rodar):
    assert cgms(rodar("--matriculados")) == ["3000000001", "5000000001", "5000000003"]


def test_turma_sem_flag_de_situacao_traz_so_matriculados(rodar):
    assert cgms(rodar("--turma", "3")) == ["3000000001"]


def test_cgm_pela_linha_de_comando(rodar):
    assert cgms(rodar("--cgm", "3000000001,5000000004", "5000000002")) == ["3000000001", "5000000002", "5000000004"]


# ── erros claros, sem travar ──

def test_turma_inexistente_sai_com_mensagem(rodar, capsys):
    monkeypatch_argv = ["--turma", "99", "--matriculados"]
    with pytest.raises(SystemExit) as e:
        rodar(*monkeypatch_argv)
    assert e.value.code == 1 and "Turma não encontrada: 99" in capsys.readouterr().out


def test_cgm_invalido_sai_com_mensagem(rodar, capsys):
    with pytest.raises(SystemExit) as e:
        rodar("--cgm", "abc")
    assert e.value.code == 1 and "formato inválido" in capsys.readouterr().out


def test_cgm_inexistente_sai_com_mensagem(rodar, capsys):
    with pytest.raises(SystemExit) as e:
        rodar("--cgm", "9999999999")
    assert e.value.code == 1 and "Nenhum dos CGMs" in capsys.readouterr().out


def test_turma_sem_valor_e_sem_terminal_nao_trava_nem_quebra(rodar, capsys):
    """Antes: input() sem console → EOFError (ou travava). Agora: mensagem pedindo --turma NOME."""
    with pytest.raises(SystemExit) as e:
        rodar("--turma")
    saida = capsys.readouterr().out
    assert e.value.code == 1 and "precisa de um terminal" in saida and "--turma" in saida

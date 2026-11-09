"""Testes de src/automacao/rotina_diaria.py (calendário em pasta temporária, sem internet, sem SERE)."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.automacao import rotina_diaria as rd  # noqa: E402
from src.web.api import calendario as cal  # noqa: E402


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(cal._paths, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(rd.paths, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(rd.paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(rd.paths, "dados_ano_atual", lambda: tmp_path / "2026")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    (tmp_path / "2026").mkdir()
    (tmp_path / "calendario" / "feriados_cache").mkdir(parents=True)
    (tmp_path / "calendario" / "feriados_cache" / "2026.json").write_text(
        json.dumps([{"date": "2026-04-21", "name": "Tiradentes"}]), encoding="utf-8")
    (tmp_path / "2026" / "calendario.json").write_text(json.dumps({
        "periodos": [{"id": "a", "nome": "1º semestre", "tipo": "letivo", "inicio": "2026-02-02", "fim": "2026-07-10"},
                     {"id": "b", "nome": "Férias", "tipo": "ferias", "inicio": "2026-07-11", "fim": "2026-07-31"},
                     {"id": "c", "nome": "2º semestre", "tipo": "letivo", "inicio": "2026-08-03", "fim": "2026-12-18"}],
        "eventos": [{"id": "e", "nome": "Conselho de classe", "tipo": "htpc", "inicio": "2026-03-10", "fim": "2026-03-10"}],
    }), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("dia,esperado", [
    (date(2026, 3, 9), True),      # segunda, período letivo
    (date(2026, 3, 7), False),     # sábado
    (date(2026, 4, 21), False),    # feriado nacional
    (date(2026, 3, 10), False),    # HTPC cadastrado
    (date(2026, 7, 15), False),    # férias
    (date(2026, 1, 20), False),    # antes do início das aulas
    (date(2026, 9, 15), False),    # aniversário da cidade (fixo)
    (date(2026, 11, 9), True),
])
def test_dia_letivo(ambiente, dia, esperado):
    assert rd.dia_letivo(dia)[0] is esperado


def _t(*alunos):
    return {"1º Ano": [{"CGM": c, "Nome": n, "Data Nasc.": "01/01/2015", "Situação": s, "Data Matricula": "01/02/2026"}
                       for c, n, s in alunos]}


def test_mudancas(ambiente):
    antes = _t(("1", "Ana", "Matriculado"), ("2", "Bia", "Matriculado"), ("3", "Cris", "Transferido"))
    depois = _t(("1", "Ana", "Matriculado"), ("2", "Bia", "Transferido"), ("3", "Cris", "Matriculado"),
                ("4", "Duda", "Matriculado"))
    r = rd.comparar_turmas(antes, depois)
    assert r["novos"] == ["4"] and r["transferidos"] == ["2"] and r["retornaram"] == ["3"]
    assert rd.comparar_turmas(antes, antes) == {"primeira_coleta": False, "novos": [], "transferidos": [], "retornaram": []}
    assert rd.comparar_turmas({}, depois)["primeira_coleta"] is True


def test_virada_de_ano_uma_vez_por_ano(ambiente, monkeypatch):
    chamadas = []
    from src.comum import ano_letivo
    monkeypatch.setattr(ano_letivo, "trocar_ano", lambda novo=None: chamadas.append(novo) or {"antigo": "2026", "novo": "2027"})
    monkeypatch.setattr(rd.paths, "garantir_diretorios_runtime", lambda: None)
    assert rd.garantir_ano_letivo(date(2026, 11, 9))["acao"] in ("nada", "novo_ano")
    assert chamadas == []
    assert rd.garantir_ano_letivo(date(2027, 2, 1))["acao"] == "virou"
    assert chamadas == [None]
    monkeypatch.setattr(rd.paths, "ano_atual", lambda: "2026")           # usuário voltou a 2026 de propósito
    assert rd.garantir_ano_letivo(date(2027, 2, 2))["acao"] == "voltado_de_proposito"
    assert len(chamadas) == 1


def test_ano_fixado_por_ambiente(ambiente, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2026")
    assert rd.garantir_ano_letivo(date(2027, 2, 1))["acao"] == "fixado_por_ambiente"


def test_alunos_pula_sem_mudanca_e_roda_com_mudanca(ambiente, monkeypatch):
    rodados = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: rodados.extend(cmds) or [0] * len(cmds))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._marcar(ctx, "turmas", ok=True, mudou=False)
    assert rd.etapa_alunos(ctx) == 0 and rodados == []
    rd._marcar(ctx, "turmas", ok=True, mudou=True)
    assert rd.etapa_alunos(ctx) == 0
    assert rodados == [["alunos", "--modo", "basico"], ["alunos", "--modo", "completo", "--rapido"]]


def test_consultas_em_simultaneo(ambiente, monkeypatch):
    lotes = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: lotes.append(cmds) or [0] * len(cmds))
    assert rd.etapa_consultas(rd.Ctx(hoje=date(2026, 11, 9))) == 0
    assert lotes == [[["cep"], ["sus"]]]            # um único lote = os dois ao mesmo tempo


def test_main_sem_aula_nao_executa(ambiente, monkeypatch):
    monkeypatch.setattr(rd, "_executar", lambda *a: pytest.fail("não deveria executar"))
    assert rd.main(["turmas", "--data", "2026-07-15"]) == 0

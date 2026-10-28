"""
test_gerar_pastas.py — Testes de src.automacao.gerar_pastas
=============================================================================
Portado de AUTO_SERE/gerar_pastas.py (classe _Testes, unittest.TestCase,
executada via `python gerar_pastas.py --teste`) para tests/test_gerar_pastas.py,
convertido para pytest puro — decisão do usuário em 01/09/2026, para
integrar com o pytest que o bootstrap (criar_projeto.py) já configura para
todo o projeto, em vez de manter --teste como um mecanismo à parte.

Os 18 casos de teste e suas asserções são idênticos ao original — apenas a
forma (unittest.TestCase → funções soltas com fixture `tmp_path` do pytest,
que substitui o setUp/tearDown com tempfile.mkdtemp()/shutil.rmtree()
manuais do original) mudou.

Rodar:
    pytest tests/test_gerar_pastas.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.automacao.gerar_pastas import (
    criar_pastas,
    extrair_alunos,
    nome_pasta,
    separar_alunos,
    verificar_transferidos,
)


def _pasta_aluno(tmp_path: Path, turma: str, nome_p: str) -> Path:
    p = tmp_path / turma.upper() / nome_p
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── extrair_alunos ──────────────────────────────────────────────────────────

def test_extrai_dicts():
    r = extrair_alunos([{"N": 1, "Nome": "Ana Lima"}, {"N": 2, "Nome": "Bruno"}])
    assert r == [(1, "ANA LIMA"), (2, "BRUNO")]


def test_extrai_strings():
    r = extrair_alunos(["Carlos", "Diana"])
    assert r == [(1, "CARLOS"), (2, "DIANA")]


def test_ignora_duplicatas():
    r = extrair_alunos([{"N": 1, "Nome": "Ana"}, {"N": 2, "Nome": "Ana"}])
    assert len(r) == 1


def test_ignora_nome_vazio():
    r = extrair_alunos([{"N": 1, "Nome": ""}, {"N": 2, "Nome": "Bruno"}])
    assert len(r) == 1


def test_ordena_por_n():
    r = extrair_alunos([{"N": 3, "Nome": "C"}, {"N": 1, "Nome": "A"}, {"N": 2, "Nome": "B"}])
    assert [n for n, _ in r] == [1, 2, 3]


def test_lista_vazia():
    assert extrair_alunos([]) == []


# ── nome_pasta ───────────────────────────────────────────────────────────────

def test_nome_pasta_formato():
    assert nome_pasta(1, "ANA LIMA") == "1 - ANA LIMA"


# ── separar_alunos ────────────────────────────────────────────────────────────

def test_separa_ativo_e_transferido():
    lista = [
        {"N": 1, "Nome": "Ana",   "Situação": "Matriculado"},
        {"N": 2, "Nome": "Bruno", "Situação": "Transferido"},
    ]
    ativos, transf = separar_alunos(lista)
    assert "1 - ANA" in ativos
    assert "2 - BRUNO" in transf
    assert "2 - BRUNO" not in ativos


def test_sem_situacao_vai_para_ativos():
    ativos, transf = separar_alunos([{"N": 1, "Nome": "Carla"}])
    assert "1 - CARLA" in ativos
    assert len(transf) == 0


# ── criar_pastas ───────────────────────────────────────────────────────────────

def test_cria_pasta_turma(tmp_path):
    criar_pastas({"6A": [{"N": 1, "Nome": "Ana"}]}, base_dir=tmp_path)
    assert (tmp_path / "6A").exists()


def test_cria_pasta_aluno(tmp_path):
    criar_pastas({"6A": [{"N": 1, "Nome": "Ana Lima"}]}, base_dir=tmp_path)
    assert (tmp_path / "6A" / "1 - ANA LIMA").exists()


def test_retorna_total_correto(tmp_path):
    turmas = {
        "6A": [{"N": 1, "Nome": "A"}, {"N": 2, "Nome": "B"}],
        "7B": [{"N": 1, "Nome": "C"}],
    }
    total = criar_pastas(turmas, base_dir=tmp_path)
    assert total == 3


def test_idempotente(tmp_path):
    t = {"6A": [{"N": 1, "Nome": "Ana"}]}
    criar_pastas(t, base_dir=tmp_path)
    criar_pastas(t, base_dir=tmp_path)   # segunda vez não deve explodir
    assert (tmp_path / "6A" / "1 - ANA").exists()


# ── verificar_transferidos ──────────────────────────────────────────────────────

def test_pasta_fantasma_vai_para_transferidos(tmp_path):
    _pasta_aluno(tmp_path, "6A", "1 - FANTASMA")
    verificar_transferidos(
        {"6A": [{"N": 2, "Nome": "Ana", "Situação": "Matriculado"}]},
        base_dir=tmp_path,
    )
    assert (tmp_path / "6A" / "TRANSFERIDOS" / "1 - FANTASMA").exists()


def test_transferido_no_json_vai_para_transferidos(tmp_path):
    _pasta_aluno(tmp_path, "6A", "1 - ANA LIMA")
    verificar_transferidos(
        {"6A": [{"N": 1, "Nome": "Ana Lima", "Situação": "Transferido"}]},
        base_dir=tmp_path,
    )
    assert (tmp_path / "6A" / "TRANSFERIDOS" / "1 - ANA LIMA").exists()


def test_ativo_nao_e_movido(tmp_path):
    _pasta_aluno(tmp_path, "6A", "1 - ANA LIMA")
    verificar_transferidos(
        {"6A": [{"N": 1, "Nome": "Ana Lima", "Situação": "Matriculado"}]},
        base_dir=tmp_path,
    )
    assert (tmp_path / "6A" / "1 - ANA LIMA").exists()
    assert not (tmp_path / "6A" / "TRANSFERIDOS").exists()


def test_duplicado_nao_move_se_ja_existe(tmp_path):
    _pasta_aluno(tmp_path, "6A", "1 - FANTASMA")
    (tmp_path / "6A" / "TRANSFERIDOS" / "1 - FANTASMA").mkdir(parents=True)
    # Não deve levantar exceção; pasta original permanece intocada
    verificar_transferidos(
        {"6A": [{"N": 2, "Nome": "Outro", "Situação": "Matriculado"}]},
        base_dir=tmp_path,
    )
    assert (tmp_path / "6A" / "1 - FANTASMA").exists()

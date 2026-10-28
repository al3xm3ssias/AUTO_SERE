"""gerar_pastas: cria na pasta de digitalização ESCOLHIDA pelo usuário (e não sempre na padrão)."""
import json

import pytest

from src.automacao import gerar_pastas as gp
from src.comum import configuracao, paths

TURMAS = {"5º Ano A": [{"N": 1, "Nome": "Ana Souza", "Situação": "Matriculado"}]}


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    padrao_ano = tmp_path / "dados_do_ano"
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: padrao_ano)
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "cfg" / "config_usuario.json")
    arq = tmp_path / "turmas.json"
    arq.write_text(json.dumps(TURMAS), encoding="utf-8")
    monkeypatch.setattr(gp, "ARQ_TURMAS", arq)
    return tmp_path, padrao_ano


def test_destino_e_a_pasta_escolhida(amb):
    tmp, padrao = amb
    escolhida = tmp / "minha_digitalizacao"
    configuracao.definir_pasta_digitalizacao(str(escolhida))
    assert gp.pasta_destino() == escolhida


def test_sem_escolha_usa_o_padrao_do_ano(amb):
    _, padrao = amb
    assert gp.pasta_destino() == padrao / "DIGITALIZAÇÃO"


def test_main_cria_as_pastas_na_pasta_escolhida_e_nao_na_padrao(amb):
    tmp, padrao = amb
    escolhida = tmp / "minha_digitalizacao"
    escolhida.mkdir()
    configuracao.definir_pasta_digitalizacao(str(escolhida))
    gp.main()
    assert (escolhida / "5º ANO A" / "1 - ANA SOUZA").is_dir()
    assert not (padrao / "DIGITALIZAÇÃO").exists()               # antes criava aqui, ignorando a escolha


def test_main_sem_escolha_continua_criando_no_padrao(amb):
    _, padrao = amb
    gp.main()
    assert (padrao / "DIGITALIZAÇÃO" / "5º ANO A" / "1 - ANA SOUZA").is_dir()

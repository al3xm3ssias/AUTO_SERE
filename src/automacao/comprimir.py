"""
comprimir.py — Comprime os documentos digitalizados que passam do limite do SERE
=============================================================================
Junta o motor (src.comum.compressao) com os caminhos do projeto:

    pasta de digitalização : src.comum.configuracao.pasta_digitalizacao() (a mesma do upload ao SERE)
    originais              : dados/<ano>/ORIGINAIS_ANTES_DA_COMPRESSAO
    registro do que já foi : dados/<ano>/compressao_registro.json

Sem turma = a pasta inteira (alunos + TRANSFERENCIAS: guias, históricos e pareceres).
A tela (Automações → Comprimir documentos) e a linha de comando (python -m src.comum.cli comprimir)
chamam executar_comprimir; ver a segurança em src/comum/compressao.py.
"""

from __future__ import annotations

from typing import Optional

from src.comum import compressao
from src.comum import paths as _paths
from src.comum.configuracao import pasta_digitalizacao


def executar_comprimir(
    turmas: Optional[list[str]] = None,
    limite_mb: float = compressao.LIMITE_SERE_MB,
    guardar_originais: bool = True,
    somente_calcular: bool = False,
    modo_teste: bool = False,
) -> compressao.Resumo:
    raiz = pasta_digitalizacao()
    if raiz is None or not raiz.is_dir():
        raise FileNotFoundError(
            "A pasta de digitalização ainda não existe. Rode 'Gerar pastas' (ou escolha a pasta em Configurações) primeiro.")
    dados = _paths.dados_ano_atual()
    return compressao.comprimir_documentos(
        raiz=raiz,
        pasta_originais=dados / compressao.PASTA_ORIGINAIS,
        registro_json=dados / "compressao_registro.json",
        turmas=list(turmas or []),
        limite_mb=limite_mb,
        guardar_originais=guardar_originais,
        somente_calcular=somente_calcular,
        modo_teste=modo_teste,
    )

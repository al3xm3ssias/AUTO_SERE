"""
paths.py — Caminhos centrais do projeto AUTO_SERE
=============================================================================
Módulo comum que resolve os diretórios do projeto de forma independente de
sistema operacional. Todos os outros módulos devem importar os caminhos
daqui, em vez de montar strings de caminho manualmente.

IMPORTANTE — modelo de instalação (definido pelo usuário em 28/08/2026):
O programa é distribuído como um instalável Windows. Os DADOS DE TRABALHO
(JSONs de alunos/turmas, relatórios, configuração) ficam sempre dentro da
pasta onde o programa foi instalado, organizados por ano letivo:

    <pasta_de_instalação>/Dados/<ano_atual>/turmas.json
    <pasta_de_instalação>/Dados/<ano_atual>/alunos.json
    <pasta_de_instalação>/Dados/<ano_atual>/relatorio_documentos-SERE.xlsx
    ...

Isso é DIFERENTE da pasta de DIGITALIZAÇÃO (os PDFs/imagens escaneados dos
alunos), que fica em um local escolhido livremente pelo usuário (C:\\, D:\\,
um HD externo, etc.) — ver src/comum/configuracao.py para como esse caminho
é perguntado ao usuário e persistido.

Uso:
    from src.comum.paths import DADOS_DIR, LOGS_DIR, LOCKS_DIR, RAIZ_PROJETO
    from src.comum.paths import dados_ano_atual, ano_atual
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# Raiz do projeto = pasta que contém este arquivo, subindo até a raiz
# (src/comum/paths.py -> src/comum -> src -> raiz do projeto)
# Em um executável instalado, isso corresponde à pasta de instalação.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent.parent

SRC_DIR = RAIZ_PROJETO / "src"
CONFIG_DIR = RAIZ_PROJETO / "config"
CREDENCIAIS_DIR = RAIZ_PROJETO / "credenciais"
DADOS_DIR = RAIZ_PROJETO / "dados"
DADOS_BACKUP_DIR = DADOS_DIR / "backup"
LOGS_DIR = RAIZ_PROJETO / "logs"
LOCKS_DIR = RAIZ_PROJETO / "locks"
DOCS_DIR = RAIZ_PROJETO / "docs"
SCRIPTS_DIR = RAIZ_PROJETO / "scripts"


def ano_atual() -> str:
    """
    Ano letivo corrente, usado para nomear a subpasta de dados
    (dados/<ano>/...). Calculado a partir da data do sistema — equivalente
    ao ANO_BASE calculado em sere_2026.py na primeira importação.
    Pode ser sobrescrito via variável de ambiente AUTO_SERE_ANO_BASE
    (útil em janeiro/fevereiro, quando o ano letivo do SERE ainda pode
    estar "atrasado" em relação ao calendário civil).
    """
    valor = os.getenv("AUTO_SERE_ANO_BASE")
    return valor if valor else str(datetime.now().year)


def dados_ano(ano: int | str) -> Path:
    """
    Pasta de dados de trabalho de um ano letivo ESPECÍFICO:
        <raiz_do_projeto>/dados/<ano>/
    Generalização de dados_ano_atual() (adicionada em 05/09/2026, a
    pedido do usuário, para src.relatorios.compara_transferido — que
    precisa comparar os dados de dois anos letivos diferentes, não só o
    atual). Cada ano letivo tem sua própria pasta (dados/2026/,
    dados/2027/, ...), a mesma organização já usada para o ano corrente.
    """
    return DADOS_DIR / str(ano)


def dados_ano_atual() -> Path:
    """
    Pasta de dados de trabalho do ano letivo corrente:
        <raiz_do_projeto>/dados/<ano>/
    Todos os JSONs (turmas, alunos, documentos, cruzamento) e relatórios
    Excel gerados pelos scripts de automação devem ficar aqui.
    """
    return dados_ano(ano_atual())


def workdir() -> Path:
    """
    Retorna o diretório de trabalho configurado via variável de ambiente
    AUTO_SERE_WORKDIR, se definida (equivalente ao WORKDIR usado nos
    scripts .sh originais). Caso não esteja definida, usa a raiz do projeto.
    """
    valor = os.getenv("AUTO_SERE_WORKDIR")
    return Path(valor) if valor else RAIZ_PROJETO


def garantir_diretorios_runtime() -> None:
    """
    Garante que os diretórios usados em runtime (logs, locks, dados/backup,
    dados do ano corrente) existam. Não apaga nem recria nada que já
    exista — apenas cria o que estiver faltando (mkdir com exist_ok=True é,
    por definição, seguro).
    """
    for diretorio in (LOGS_DIR, LOCKS_DIR, DADOS_DIR, DADOS_BACKUP_DIR, dados_ano_atual()):
        diretorio.mkdir(parents=True, exist_ok=True)
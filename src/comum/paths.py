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

import json
import os
import re
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


RE_ANO = re.compile(r"^(?:19|20)\d{2}$")
_ANO_NAO_LIDO = object()
_ano_do_processo = _ANO_NAO_LIDO


def _ano_do_arquivo_de_configuracao() -> str | None:
    """`ano_letivo` de config/config_usuario.json (lido direto: configuracao.py importa este módulo)."""
    try:
        dados = json.loads((CONFIG_DIR / "config_usuario.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ano = str(dados.get("ano_letivo") or "").strip() if isinstance(dados, dict) else ""
    return ano if RE_ANO.match(ano) else None


def ano_configurado() -> str | None:
    """Ano letivo escolhido na tela (Configurações → Ano letivo), lido AGORA do arquivo; None = automático."""
    return _ano_do_arquivo_de_configuracao()


def ano_fixado_por_ambiente() -> bool:
    """True se AUTO_SERE_ANO_BASE está definida: ela manda sobre a configuração da tela."""
    return bool(os.getenv("AUTO_SERE_ANO_BASE"))


def ano_do_proximo_inicio() -> str:
    """O ano que o programa vai usar quando for aberto de novo (pode diferir de ano_atual() até reiniciar)."""
    return os.getenv("AUTO_SERE_ANO_BASE") or ano_configurado() or str(datetime.now().year)


def definir_ano_do_processo(valor):
    """
    Muda o ano em uso NESTE processo (troca de ano sem reiniciar; ver src/comum/ano_letivo.py). `valor` None =
    automático (ano do calendário). Devolve o valor anterior, para poder desfazer.
    """
    global _ano_do_processo
    anterior = _ano_do_processo
    _ano_do_processo = valor
    return anterior


def recarregar_ano_do_processo() -> None:
    """Esquece o ano lido da configuração (só para testes: no uso normal ele vale até reiniciar)."""
    global _ano_do_processo
    _ano_do_processo = _ANO_NAO_LIDO


def ano_atual() -> str:
    """
    Ano letivo em uso, que nomeia a subpasta de dados (dados/<ano>/...). Ordem:
      1. variável de ambiente AUTO_SERE_ANO_BASE (útil em janeiro/fevereiro, quando o ano letivo do SERE
         ainda pode estar "atrasado" em relação ao calendário civil);
      2. ano escolhido em Configurações → Ano letivo (config/config_usuario.json, chave `ano_letivo`);
      3. ano do calendário (data do sistema).

    O ano da configuração é lido UMA VEZ por execução do programa e depois mantido: muitos módulos fixam
    dados/<ano> na importação (ex.: _DADOS = dados_ano_atual()), então mudar só este valor misturaria dois anos (a
    tela num, os scripts no outro). Por isso a troca com o programa aberto passa por src.comum.ano_letivo.trocar_ano(),
    que muda o ano E recarrega esses módulos; editar o arquivo de configuração à mão só vale ao reiniciar.
    """
    valor = os.getenv("AUTO_SERE_ANO_BASE")
    if valor:
        return valor
    global _ano_do_processo
    if _ano_do_processo is _ANO_NAO_LIDO:
        _ano_do_processo = _ano_do_arquivo_de_configuracao()
    return _ano_do_processo or str(datetime.now().year)


def ano_do_calendario() -> int:
    """Ano civil de hoje (referência para saber se o programa está 'voltado' a um ano anterior)."""
    return datetime.now().year


def somente_consulta() -> bool:
    """
    True quando o programa está VOLTADO a um ano letivo anterior, escolhido em Configurações → Ano letivo: o ano em
    uso é menor que o do calendário. Nesse modo tudo é só leitura (ver o guarda em src/web/app.py): o ano passado
    já foi fechado e não deve ser alterado sem querer.

    Não vale quando o ano é fixado pela variável AUTO_SERE_ANO_BASE: é o caminho de quem PRECISA trabalhar num ano
    "atrasado" em relação ao calendário (ex.: janeiro/fevereiro, com o ano letivo anterior ainda aberto no SERE).
    """
    if os.getenv("AUTO_SERE_ANO_BASE"):
        return False
    try:
        return int(ano_atual()) < ano_do_calendario()
    except (TypeError, ValueError):
        return False


def anos_disponiveis() -> list[str]:
    """Anos que têm pasta em dados/ (ex.: ["2026", "2025"]), do mais novo para o mais antigo."""
    if not DADOS_DIR.is_dir():
        return []
    return sorted((p.name for p in DADOS_DIR.iterdir() if p.is_dir() and RE_ANO.match(p.name)), reverse=True)


def dados_ano_atual() -> Path:
    """
    Pasta de dados de trabalho do ano letivo corrente:
        <raiz_do_projeto>/dados/<ano>/
    Todos os JSONs (turmas, alunos, documentos, cruzamento) e relatórios
    Excel gerados pelos scripts de automação devem ficar aqui.
    """
    return DADOS_DIR / ano_atual()


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
    Garante que os diretórios usados em runtime (credenciais, logs, locks,
    dados/backup, dados do ano corrente) existam. Não apaga nem recria nada que já
    exista — apenas cria o que estiver faltando (mkdir com exist_ok=True é,
    por definição, seguro).
    """
    for diretorio in (CREDENCIAIS_DIR, LOGS_DIR, LOCKS_DIR, DADOS_DIR, DADOS_BACKUP_DIR, dados_ano_atual()):
        diretorio.mkdir(parents=True, exist_ok=True)

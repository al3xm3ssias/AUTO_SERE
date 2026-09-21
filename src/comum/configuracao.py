"""
configuracao.py — Configuração persistida do usuário
=============================================================================
Módulo comum que centraliza a configuração definida pelo usuário na
primeira execução do programa, para ser lida por qualquer script depois.

CONTEXTO (definido pelo usuário em 28/08/2026):
O programa é instalado como qualquer programa Windows. Na primeira vez que
o usuário roda o AUTO_SERE, o fluxo esperado é:

    1. Configurar/salvar credenciais do SERE (login e senha)
    2. Rodar o carregamento de turmas (turmas.py)
    3. Escolher onde ficam os documentos digitalizados (PDF/imagem) —
       pasta livre, escolhida pelo usuário (C:\\, D:\\, HD externo, etc.)
    4. A partir daí, uso normal de rotina.

Este módulo é o ponto único de leitura/gravação dessa configuração. Ele
NÃO decide sozinho onde a pasta de digitalização fica — isso é responsa-
bilidade de um script de setup (ex.: gerar_pastas.py, ainda não portado)
que vai perguntar ao usuário e gravar aqui via `definir_pasta_digitalizacao`.
Até esse script existir, os scripts que precisam da pasta de digitalização
devem checar `pasta_digitalizacao_configurada()` e orientar o usuário a
configurá-la, em vez de assumir um caminho fixo.

Formato do arquivo (config/config_usuario.json):
    {
        "pasta_digitalizacao": "D:\\Documentos_Alunos_2026",
        "cgm_upload": [1025059715],
        "setup_concluido": false
    }

Uso:
    from src.comum.configuracao import (
        carregar_configuracao,
        pasta_digitalizacao,
        pasta_digitalizacao_configurada,
        definir_pasta_digitalizacao,
        cgm_upload,
        definir_cgm_upload,
    )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import CONFIG_DIR

ARQUIVO_CONFIG = CONFIG_DIR / "config_usuario.json"

_PADRAO: dict[str, Any] = {
    "pasta_digitalizacao": None,
    "cgm_upload": [],
    "setup_concluido": False,
}


def carregar_configuracao() -> dict[str, Any]:
    """
    Carrega config/config_usuario.json. Se o arquivo ainda não existir
    (primeira execução), retorna os valores padrão SEM criar o arquivo —
    a criação só acontece quando algo é efetivamente salvo (ver
    `_salvar_configuracao`), para não gerar arquivo vazio à toa.
    Chaves ausentes no arquivo (ex.: config antiga, de uma versão anterior
    do programa) são preenchidas com o valor padrão correspondente.
    """
    if not ARQUIVO_CONFIG.exists():
        return dict(_PADRAO)

    with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
        dados = json.load(f)

    configuracao = dict(_PADRAO)
    configuracao.update(dados)
    return configuracao


def _salvar_configuracao(configuracao: dict[str, Any]) -> None:
    """
    Grava config/config_usuario.json. Cria a pasta config/ se necessário
    (mkdir com exist_ok=True — não apaga nada existente). Escreve o
    arquivo inteiro de uma vez (json.dump), então esta função sempre deve
    receber a configuração COMPLETA (carregada antes via
    `carregar_configuracao`, alterada, e então salva) — nunca um
    fragmento parcial, para não perder chaves já configuradas.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(configuracao, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────
# Pasta de digitalização (documentos PDF/imagem dos alunos)
# ─────────────────────────────────────────────────────────────────────────

def pasta_digitalizacao() -> Path | None:
    """
    Retorna a pasta de digitalização configurada pelo usuário, ou None se
    ainda não foi configurada (setup inicial pendente).
    """
    valor = carregar_configuracao().get("pasta_digitalizacao")
    return Path(valor) if valor else None


def pasta_digitalizacao_configurada() -> bool:
    """
    True se o usuário já escolheu a pasta de digitalização e ela ainda
    existe no disco. Scripts que dependem dessa pasta devem checar isto
    antes de prosseguir, e orientar o usuário a rodar o setup caso False.
    """
    caminho = pasta_digitalizacao()
    return caminho is not None and caminho.is_dir()


def definir_pasta_digitalizacao(caminho: str | Path) -> None:
    """
    Salva a pasta de digitalização escolhida pelo usuário. Não valida se
    a pasta existe — quem escolhe o caminho (ex.: um diálogo do Windows
    Explorer no script de setup) é responsável por garantir isso antes
    de chamar esta função.
    """
    configuracao = carregar_configuracao()
    configuracao["pasta_digitalizacao"] = str(caminho)
    _salvar_configuracao(configuracao)


# ─────────────────────────────────────────────────────────────────────────
# CGM_UPLOAD (lista de CGMs para os modos --aluno / --alunos)
# ─────────────────────────────────────────────────────────────────────────
# Antes, este array vivia duplicado dentro de sere_2026.py, e
# analisa_arquivos_sere.py importava de lá (from sere_2026 import
# CGM_UPLOAD) — um acoplamento desnecessário entre os dois scripts.
# Agora é uma única fonte de verdade aqui, usada pelos dois.

def cgm_upload() -> list[int]:
    """
    Lista de CGMs configurada para os modos --aluno / --alunos. Vazia por
    padrão até o usuário configurar (equivalente a editar o array
    CGM_UPLOAD manualmente no topo do script original).
    """
    return list(carregar_configuracao().get("cgm_upload", []))


def definir_cgm_upload(cgms: list[int]) -> None:
    """Substitui a lista de CGMs configurada (equivalente a editar o array CGM_UPLOAD)."""
    configuracao = carregar_configuracao()
    configuracao["cgm_upload"] = list(cgms)
    _salvar_configuracao(configuracao)


# ─────────────────────────────────────────────────────────────────────────
# Setup inicial
# ─────────────────────────────────────────────────────────────────────────

def setup_concluido() -> bool:
    """True se o fluxo de primeira configuração (credenciais, turmas, pasta de digitalização) já foi concluído."""
    return bool(carregar_configuracao().get("setup_concluido", False))


def marcar_setup_concluido() -> None:
    configuracao = carregar_configuracao()
    configuracao["setup_concluido"] = True
    _salvar_configuracao(configuracao)
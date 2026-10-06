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
import unicodedata
from pathlib import Path
from typing import Any

from .paths import CONFIG_DIR, dados_ano_atual

ARQUIVO_CONFIG = CONFIG_DIR / "config_usuario.json"

_PADRAO: dict[str, Any] = {
    "pasta_digitalizacao": None,
    "pasta_modelos": None,
    "cgm_upload": [],
    "setup_concluido": False,
    "unidade_escolar": None,
    "flags_automacoes": {},
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

# Nome padrão da pasta de digitalização dentro de dados/<ano>/ (é o mesmo
# que src.automacao.gerar_pastas usa: DADOS/<ANO>/DIGITALIZAÇÃO/<TURMA>/...).
NOME_PASTA_DIGITALIZACAO = "DIGITALIZAÇÃO"


def _normalizar_nome(nome: str) -> str:
    """Minúsculas e sem acentos, para comparar 'Digitalização' com 'DIGITALIZAÇÃO'
    (em Linux o sistema de arquivos diferencia maiúsculas de minúsculas)."""
    decomposto = unicodedata.normalize("NFD", nome)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").lower()


def pasta_digitalizacao_padrao() -> Path:
    """
    Pasta de digitalização PADRÃO: dados/<ano atual>/DIGITALIZAÇÃO.

    Se já existir uma pasta com esse nome em dados/<ano>/ (qualquer
    combinação de maiúsculas/minúsculas e acentos), devolve a existente;
    senão devolve o caminho com o nome padrão (que pode ainda não existir).
    Muda sozinha na virada do ano, pois depende de dados_ano_atual().
    """
    base = dados_ano_atual()
    alvo = _normalizar_nome(NOME_PASTA_DIGITALIZACAO)
    if base.is_dir():
        for filho in sorted(base.iterdir()):
            if filho.is_dir() and _normalizar_nome(filho.name) == alvo:
                return filho
    return base / NOME_PASTA_DIGITALIZACAO


def pasta_digitalizacao_personalizada() -> bool:
    """True se o usuário escolheu uma pasta própria (em vez de usar a padrão)."""
    return bool(carregar_configuracao().get("pasta_digitalizacao"))


def pasta_digitalizacao() -> Path | None:
    """
    Retorna a pasta de digitalização em uso:
      1. a pasta que o usuário escolheu, se houver; senão
      2. a pasta padrão dados/<ano>/DIGITALIZAÇÃO, se ela já existir; senão
      3. None (setup pendente).
    """
    valor = carregar_configuracao().get("pasta_digitalizacao")
    if valor:
        return Path(valor)
    padrao = pasta_digitalizacao_padrao()
    return padrao if padrao.is_dir() else None


def pasta_digitalizacao_configurada() -> bool:
    """
    True se há uma pasta de digitalização em uso (escolhida pelo usuário ou
    a padrão do ano) e ela existe no disco. Scripts que dependem dessa pasta
    devem checar isto antes de prosseguir, e orientar o usuário a rodar o
    setup caso False.
    """
    caminho = pasta_digitalizacao()
    return caminho is not None and caminho.is_dir()


def definir_pasta_digitalizacao(caminho: str | Path) -> None:
    """
    Salva uma pasta de digitalização PERSONALIZADA escolhida pelo usuário.
    Não valida se a pasta existe — quem escolhe o caminho (ex.: a rota de
    Configurações, que valida antes) é responsável por garantir isso.
    """
    configuracao = carregar_configuracao()
    configuracao["pasta_digitalizacao"] = str(caminho)
    _salvar_configuracao(configuracao)


def usar_pasta_digitalizacao_padrao() -> None:
    """
    Volta a usar a pasta padrão (dados/<ano>/DIGITALIZAÇÃO): remove a pasta
    personalizada da configuração. Nada é gravado como caminho fixo, então
    na virada do ano a pasta em uso acompanha o novo ano automaticamente.
    """
    configuracao = carregar_configuracao()
    configuracao["pasta_digitalizacao"] = None
    _salvar_configuracao(configuracao)


# ─────────────────────────────────────────────────────────────────────────
# Pasta de modelos (documentos .docx a preencher — ex.: Termo de Ciência)
# ─────────────────────────────────────────────────────────────────────────
# Adicionada a pedido do usuário (02/09/2026) para src.automacao.termo_ciencia
# — antes o modelo era localizado subindo pastas até achar "ESCOLA JUDITH"
# (caminho fixo do servidor Linux), o que não faz sentido na nova
# arquitetura (instalação Windows). Configurável separadamente da pasta de
# digitalização, pois são conceitos diferentes (modelos de documento a
# preencher vs. documentos escaneados dos alunos).

def pasta_modelos() -> Path | None:
    """
    Retorna a pasta de modelos de documento configurada pelo usuário
    (ex.: onde fica "MODELO DE TERMO DE CIENCIA.docx"), ou None se ainda
    não foi configurada.
    """
    valor = carregar_configuracao().get("pasta_modelos")
    return Path(valor) if valor else None


def pasta_modelos_configurada() -> bool:
    """
    True se o usuário já escolheu a pasta de modelos e ela ainda existe
    no disco.
    """
    caminho = pasta_modelos()
    return caminho is not None and caminho.is_dir()


def definir_pasta_modelos(caminho: str | Path) -> None:
    """
    Salva a pasta de modelos de documento escolhida pelo usuário. Não
    valida se a pasta existe — mesma responsabilidade de quem escolhe o
    caminho, como em definir_pasta_digitalizacao.
    """
    configuracao = carregar_configuracao()
    configuracao["pasta_modelos"] = str(caminho)
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
# Flags das automações (opções de linha de comando ligadas/desligadas na
# aba "Configuração" de cada automação)
# ─────────────────────────────────────────────────────────────────────────

def flags_automacao(chave: str) -> list[str]:
    """Flags (ex.: ["--rapido"]) que o usuário deixou ligadas para esta automação."""
    todas = carregar_configuracao().get("flags_automacoes") or {}
    return list(todas.get(chave, []))


def definir_flags_automacao(chave: str, flags: list[str]) -> None:
    """Substitui as flags ligadas para a automação `chave` (as demais automações ficam como estão)."""
    configuracao = carregar_configuracao()
    todas = dict(configuracao.get("flags_automacoes") or {})
    todas[chave] = list(flags)
    configuracao["flags_automacoes"] = todas
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


# ─────────────────────────────────────────────────────────────────────────
# Unidade escolar (nome, endereço e CEP da escola do usuário)
# ─────────────────────────────────────────────────────────────────────────
# Adicionada a pedido do usuário (03/09/2026), para src.automacao.cep_api.
# Fluxo de setup decidido pelo usuário: src.automacao.coleta_emails roda
# primeiro (pré-requisito de instalação, raspa todas as escolas do
# município), depois o usuário escolhe a sua num seletor pesquisável
# populado por coleta_emails.listar_nomes_escolas(); nome e endereço vêm
# dessa escolha (via coleta_emails.buscar_escola_por_nome) — o CEP não é
# extraído do endereço raspado (é texto livre, não confiável para isso);
# o usuário digita o CEP manualmente para completar o cadastro.

def unidade_escolar() -> dict | None:
    """
    Retorna os dados da unidade escolar configurada (nome, endereço, cep),
    ou None se ainda não foi configurada.
    """
    return carregar_configuracao().get("unidade_escolar")


def unidade_escolar_configurada() -> bool:
    """
    True se a unidade escolar já foi configurada com nome, endereço e CEP
    (os três campos preenchidos — sem CEP não dá para usar
    src.automacao.cep_api).
    """
    dados = unidade_escolar()
    return bool(dados and dados.get("nome") and dados.get("endereco") and dados.get("cep"))


def definir_unidade_escolar(nome: str, endereco: str, cep: str) -> None:
    """
    Salva os dados da unidade escolar: `nome` e `endereco` vêm da escolha
    do usuário no seletor (populado a partir de
    src.automacao.coleta_emails), `cep` é digitado manualmente pelo
    usuário (decisão do usuário, 03/09/2026 — não é extraído do texto do
    endereço raspado).
    """
    configuracao = carregar_configuracao()
    configuracao["unidade_escolar"] = {
        "nome": nome,
        "endereco": endereco,
        "cep": cep,
    }
    _salvar_configuracao(configuracao)


def definir_unidade_escolar_completa(dados: dict) -> None:
    """
    Grava o bloco completo "unidade_escolar" (nome, nome_abreviado, cep,
    logradouro, numero, bairro, cidade, uf, endereco, codigo, inep,
    telefone, email, responsavel). Quem valida e monta os campos é
    src.comum.escola; use essa camada em vez de chamar esta função direto.
    """
    configuracao = carregar_configuracao()
    configuracao["unidade_escolar"] = dict(dados)
    _salvar_configuracao(configuracao)

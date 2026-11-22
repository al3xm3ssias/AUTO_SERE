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
import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from .paths import CONFIG_DIR, dados_ano_atual

ARQUIVO_CONFIG = CONFIG_DIR / "config_usuario.json"

_PADRAO: dict[str, Any] = {
    "pasta_digitalizacao": None,
    "pasta_modelos": None,
    "cgm_upload": [],
    "setup_concluido": False,
    "ano_letivo": None,
    "unidade_escolar": None,
    "flags_automacoes": {},
    "data_corte_transferidos": None,      # "dd/mm/aaaa"; None = 22/06 do ano letivo (ver data_corte_transferidos)
    "mapeamento_turmas_qr": {},           # {texto da turma no QR antigo (MAIÚSCULO): turma real do turmas.json} — ver mapeamento_turmas_qr
    "observacao_historico": None,         # último texto usado na etapa "Alterar" do histórico de transferidos
    "navegador_padrao": None,             # None = automático (cada script usa o seu); "chromium" (Chrome) ou "firefox" — ver comum/navegador.py
    "navegador_scripts": {},              # {chave_do_script: {"mostrar_janela": True/False}}; sem a chave = o padrão do script
    "google_sheets": None,                # {"mapa_abas"} (ver google_sheets_config); as planilhas ficam em planilhas_gerenciador
    "google_oauth": None,                 # {"conta","navegador","perfil","abrir"} — com qual conta/navegador/perfil abrir a autorização do Google (ver google_oauth_preferencias)
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
# Ano letivo (pedido do usuário, 24/10/2026)
# ─────────────────────────────────────────────────────────────────────────

ANO_LETIVO_MINIMO = 2000


def validar_ano_letivo(ano) -> str:
    """'2025' → '2025'. ValueError com mensagem pronta se não for um ano plausível (2000 até o ano que vem)."""
    texto = str(ano if ano is not None else "").strip()
    if not texto.isdigit() or len(texto) != 4:
        raise ValueError("Informe o ano letivo com 4 números (ex.: 2025).")
    from datetime import datetime
    if not ANO_LETIVO_MINIMO <= int(texto) <= datetime.now().year + 1:
        raise ValueError(f"Ano letivo fora do intervalo aceito ({ANO_LETIVO_MINIMO} a {datetime.now().year + 1}).")
    return texto


def ano_letivo_configurado() -> str | None:
    """Ano escolhido na tela, ou None (= automático, o do calendário)."""
    ano = str(carregar_configuracao().get("ano_letivo") or "").strip()
    return ano if ano.isdigit() and len(ano) == 4 else None


def definir_ano_letivo(ano) -> str:
    """Grava o ano letivo. Vale quando o programa for aberto de novo (ver paths.ano_atual)."""
    ano = validar_ano_letivo(ano)
    config = carregar_configuracao()
    config["ano_letivo"] = ano
    _salvar_configuracao(config)
    return ano


def usar_ano_letivo_automatico() -> None:
    """Volta para o ano do calendário (apaga a escolha)."""
    config = carregar_configuracao()
    config["ano_letivo"] = None
    _salvar_configuracao(config)


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
# DATA_CORTE dos transferidos (pedido do usuário, 27/10/2026)
# ─────────────────────────────────────────────────────────────────────────
# O processo automático de transferidos só começa para quem foi transferido A PARTIR desta data
# (inclusive). Antes dela, os documentos são considerados já tratados à mão.

DATA_CORTE_PADRAO_DIA, DATA_CORTE_PADRAO_MES = 22, 6


def validar_data_corte(texto) -> "date":
    """Converte 'dd/mm/aaaa' (ou 'aaaa-mm-dd') em date. ValueError com mensagem pronta se inválida."""
    from datetime import date, datetime
    bruto = str(texto or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(bruto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"Data de corte inválida: '{bruto}'. Use o formato dd/mm/aaaa (ex.: 22/06/2026).")


def data_corte_transferidos_configurada() -> bool:
    return bool(carregar_configuracao().get("data_corte_transferidos"))


def data_corte_padrao() -> "date":
    """22/06 do ano letivo (o corte que o projeto usava antes de ser configurável)."""
    from datetime import date
    from src.comum import paths as _paths
    return date(int(_paths.ano_atual()), DATA_CORTE_PADRAO_MES, DATA_CORTE_PADRAO_DIA)


def data_corte_transferidos() -> "date":
    """DATA_CORTE em vigor: a configurada, ou a padrão (22/06 do ano letivo)."""
    bruta = carregar_configuracao().get("data_corte_transferidos")
    return validar_data_corte(bruta) if bruta else data_corte_padrao()


def definir_data_corte_transferidos(texto) -> "date":
    """Grava a DATA_CORTE (valida antes). Texto vazio volta ao padrão. Retorna a data em vigor."""
    configuracao = carregar_configuracao()
    if not str(texto or "").strip():
        configuracao["data_corte_transferidos"] = None
        _salvar_configuracao(configuracao)
        return data_corte_transferidos()
    data = validar_data_corte(texto)
    configuracao["data_corte_transferidos"] = data.strftime("%d/%m/%Y")
    _salvar_configuracao(configuracao)
    return data


# ─────────────────────────────────────────────────────────────────────────
# Turmas do QR antigo dos pareceres (pedido do usuário, 21/11/2026)
# ─────────────────────────────────────────────────────────────────────────
# O QR antigo traz o NOME e a TURMA escritos à mão ("INF 4 A"); o turmas.json chama a turma de outro jeito
# ("INFANTIL 4 Integral A"). A leitura (pareceres_transferidos.resolver_turma) acha a maioria por palavras; o que ela
# não acha o usuário ensina aqui, e os pares valem ACIMA do mapeamento embutido no código.

MAPEAMENTO_QR_MAX_PARES = 300
MAPEAMENTO_QR_MAX_TEXTO = 80


def mapeamento_turmas_qr() -> dict:
    """Os pares que o usuário cadastrou: {texto da turma no QR (MAIÚSCULO, sem espaços nas pontas): turma do turmas.json}."""
    bruto = carregar_configuracao().get("mapeamento_turmas_qr")
    if not isinstance(bruto, dict):
        return {}
    return {str(k).strip().upper(): str(v).strip() for k, v in bruto.items() if str(k).strip() and str(v).strip()}


def definir_mapeamento_turmas_qr(pares) -> dict:
    """
    Grava os pares (SUBSTITUI os que existiam). `pares`: lista de (texto do QR, turma) ou um dict. Linhas totalmente
    vazias são ignoradas. ValueError com mensagem pronta se uma linha está pela metade, se o mesmo texto aparece duas
    vezes ou se passa do limite. A chave segue a regra da leitura (strip + MAIÚSCULO): é assim que ela é procurada.
    """
    itens = list(pares.items()) if isinstance(pares, dict) else list(pares or [])
    gravar: dict = {}
    for n, (qr, turma) in enumerate(itens, start=1):
        qr, turma = str(qr or "").strip(), str(turma or "").strip()
        if not qr and not turma:
            continue
        if not qr or not turma:
            raise ValueError(f"Linha {n}: preencha o texto do QR e a turma (ou apague a linha).")
        if len(qr) > MAPEAMENTO_QR_MAX_TEXTO:
            raise ValueError(f"Linha {n}: o texto do QR passa de {MAPEAMENTO_QR_MAX_TEXTO} caracteres.")
        chave = qr.upper()
        if chave in gravar:
            raise ValueError(f"O texto \"{qr}\" aparece mais de uma vez (maiúsculas e minúsculas contam igual).")
        gravar[chave] = turma
    if len(gravar) > MAPEAMENTO_QR_MAX_PARES:
        raise ValueError(f"São pares demais (o máximo é {MAPEAMENTO_QR_MAX_PARES}).")
    configuracao = carregar_configuracao()
    configuracao["mapeamento_turmas_qr"] = gravar
    _salvar_configuracao(configuracao)
    return dict(gravar)


def observacao_historico() -> str:
    """Último texto de observação usado na etapa "Alterar" do histórico (já vem preenchido na tela)."""
    return str(carregar_configuracao().get("observacao_historico") or "")


def definir_observacao_historico(texto) -> None:
    configuracao = carregar_configuracao()
    configuracao["observacao_historico"] = str(texto or "").strip() or None
    _salvar_configuracao(configuracao)


# ─────────────────────────────────────────────────────────────────────────
# Google Sheets (planilha das turmas)
# ─────────────────────────────────────────────────────────────────────────
# Só o que NÃO é segredo fica aqui: se o usuário quiser, um mapa
# {nome da turma no turmas.json: nome da aba na planilha} que complementa/substitui o padrão da escola
# (src/automacao/sincroniza_sheets.py). Credenciais e token ficam em credenciais/ (ver src/comum/google_auth.py).

def google_sheets_config() -> dict:
    bruto = carregar_configuracao().get("google_sheets")
    return dict(bruto) if isinstance(bruto, dict) else {}


def esquecer_planilha_google_legada() -> None:
    """
    Remove daqui o antigo "ID da última planilha usada". As planilhas (e a vigente de cada uso) vivem só no cadastro
    central (src/comum/planilhas_gerenciador.py → dados/planilhas/planilhas.json); este bloco guarda apenas o mapa
    de abas (`mapa_abas`). Chamado pela migração do gerenciador, depois de levar o ID para o cadastro.
    """
    configuracao = carregar_configuracao()
    bloco = dict(configuracao.get("google_sheets") or {})
    mudou = False
    for chave in ("planilha_id", "planilhas", "proximo_id"):
        if chave in bloco:
            bloco.pop(chave)
            mudou = True
    if mudou:
        configuracao["google_sheets"] = bloco
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


# ─────────────────────────────────────────────────────────────────────────
# Navegador das automações (pedido do usuário, 13/11/2026)
# ─────────────────────────────────────────────────────────────────────────

NAVEGADORES_ACEITOS = ("chromium", "firefox")      # "Chrome" na tela = o Chromium do Playwright


def navegador_padrao() -> str:
    """'chromium', 'firefox' ou '' (= automático: cada script abre o navegador para o qual foi feito)."""
    valor = str(carregar_configuracao().get("navegador_padrao") or "").strip().lower()
    return valor if valor in NAVEGADORES_ACEITOS else ""


def definir_navegador_padrao(valor) -> str:
    """Grava o navegador global. Vazio/'automatico' volta ao automático. ValueError se não for um aceito."""
    texto = str(valor or "").strip().lower()
    if texto in ("", "automatico", "automático", "auto"):
        novo = None
    elif texto in ("chrome", "chromium"):
        novo = "chromium"
    elif texto == "firefox":
        novo = "firefox"
    else:
        raise ValueError("Navegador inválido: escolha Automático, Chrome ou Firefox.")
    configuracao = carregar_configuracao()
    configuracao["navegador_padrao"] = novo
    _salvar_configuracao(configuracao)
    return novo or ""


def mostrar_janela_script(chave: str) -> bool | None:
    """True = abrir a janela do navegador neste script; False = escondida; None = não configurado (vale o padrão do script)."""
    dados = (carregar_configuracao().get("navegador_scripts") or {}).get(chave) or {}
    valor = dados.get("mostrar_janela")
    return valor if isinstance(valor, bool) else None


def definir_mostrar_janela_script(chave: str, mostrar: bool | None) -> None:
    """Grava a escolha do script. None apaga a escolha (volta ao padrão do script)."""
    configuracao = carregar_configuracao()
    todos = dict(configuracao.get("navegador_scripts") or {})
    if mostrar is None:
        todos.pop(chave, None)
    else:
        todos[chave] = {"mostrar_janela": bool(mostrar)}
    configuracao["navegador_scripts"] = todos
    _salvar_configuracao(configuracao)


# ─────────────────────────────────────────────────────────────────────────
# Autorização do Google: conta, navegador e perfil em que o link abre
# ─────────────────────────────────────────────────────────────────────────

def google_oauth_preferencias() -> dict[str, Any]:
    """
    {"conta": e-mail ou "", "navegador": ""|"chrome"|"edge"|"firefox"|caminho, "perfil": pasta do perfil ou "",
    "abrir": True/False (abrir o navegador sozinho)}. As variáveis GOOGLE_OAUTH_CONTA / _NAVEGADOR / _PERFIL /
    _ABRIR_NAVEGADOR (credenciais/.env) têm prioridade sobre o que foi salvo na tela.
    """
    salvo = carregar_configuracao().get("google_oauth")
    salvo = salvo if isinstance(salvo, dict) else {}

    def _texto(env: str, chave: str) -> str:
        return (os.getenv(env) or "").strip() or str(salvo.get(chave) or "").strip()

    abrir_env = (os.getenv("GOOGLE_OAUTH_ABRIR_NAVEGADOR") or "").strip().lower()
    if abrir_env:
        abrir = abrir_env not in ("0", "false", "nao", "não")
    else:
        abrir = salvo.get("abrir") if isinstance(salvo.get("abrir"), bool) else True
    return {"conta": _texto("GOOGLE_OAUTH_CONTA", "conta"), "navegador": _texto("GOOGLE_OAUTH_NAVEGADOR", "navegador"),
            "perfil": _texto("GOOGLE_OAUTH_PERFIL", "perfil"), "abrir": abrir}


def definir_google_oauth(conta: str = "", navegador: str = "", perfil: str = "", abrir: bool = True) -> dict[str, Any]:
    """Grava a escolha da tela. ValueError (mensagem pronta) se o e-mail ou o navegador forem inválidos."""
    conta = str(conta or "").strip()
    if conta and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", conta):
        raise ValueError("Informe o e-mail completo da conta Google (ex.: nome@gmail.com) ou deixe em branco.")
    navegador = str(navegador or "").strip()
    if navegador.lower() in ("", "padrao", "padrão", "automatico", "automático"):
        navegador = ""
    elif navegador.lower() in ("chrome", "edge", "firefox"):
        navegador = navegador.lower()
    elif not Path(navegador).expanduser().is_file():
        raise ValueError("Navegador inválido: escolha um da lista ou informe o caminho completo do programa (.exe).")
    perfil = str(perfil or "").strip()
    if len(perfil) > 80 or any(c in perfil for c in '\\/"\n\r'):
        raise ValueError("Nome de perfil inválido.")
    configuracao = carregar_configuracao()
    configuracao["google_oauth"] = {"conta": conta, "navegador": navegador, "perfil": perfil, "abrir": bool(abrir)}
    _salvar_configuracao(configuracao)
    return google_oauth_preferencias()

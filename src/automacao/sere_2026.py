"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              SERE — SCRIPT UNIFICADO DE GESTÃO DE DOCUMENTOS                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Este script centraliza todas as operações de documentos do SERE,           ║
║  unificando modos de limpeza, remoção, análise, upload e transferidos.       ║
║                                                                              ║
║  O ANO_BASE é detectado automaticamente pelo ano corrente do sistema.        ║
║  Não é necessário editar o script a cada virada de ano.                      ║
║                                                                              ║
║  USO GERAL:                                                                  ║
║      python -m src.automacao.sere_2026 [--modo] [opções]                    ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  MODOS DISPONÍVEIS (um por execução)                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  --limpeza                                                                   ║
║      Limpa TODOS os arquivos de TODOS os alunos até zerar, e depois          ║
║      consulta a API para ver o que restou, salvando em documentos-alunos.json║
║      Exemplos:                                                               ║
║        python -m src.automacao.sere_2026 --limpeza                          ║
║        python -m src.automacao.sere_2026 --limpeza --teste  (1 aluno)       ║
║        python -m src.automacao.sere_2026 --limpeza --turmas (interativo)    ║
║        python -m src.automacao.sere_2026 --limpeza --turmas 3A 3B           ║
║                                                                              ║
║  --documento <ID>                                                            ║
║      Remove apenas um tipo de documento (por ID) de todos os alunos.        ║
║      Se o ID não for informado, exibe o menu com todos os tipos disponíveis. ║
║      Exemplos:                                                               ║
║        python -m src.automacao.sere_2026 --documento        (exibe menu)    ║
║        python -m src.automacao.sere_2026 --documento 3      (remove tipo 3) ║
║        python -m src.automacao.sere_2026 --documento 3 --turma              ║
║                                                                              ║
║  --analisa                                                                   ║
║      Coleta os documentos de todos os alunos via API do SERE e gera          ║
║      relatório Excel e JSON (reutiliza src.relatorios.analisa_arquivos_sere).║
║      Exemplos:                                                               ║
║        python -m src.automacao.sere_2026 --analisa                          ║
║        python -m src.automacao.sere_2026 --analisa --turma                   ║
║                                                                              ║
║  --espec <ID>                                                                ║
║      Envia um tipo de documento da pasta de digitalização para todos os      ║
║      alunos. Sem o ID, mostra o menu de tipos.                               ║
║        python -m src.automacao.sere_2026 --espec 3 --turma 5                 ║
║                                                                              ║
║  --aluno                                                                     ║
║      Envia os documentos só dos CGMs de --cgm (ou da lista configurada).     ║
║      --erros: só os que falharam; --faltando: só quem tem pendência.         ║
║        python -m src.automacao.sere_2026 --aluno --cgm 3000000001 --teste    ║
║                                                                              ║
║  --transferidos                                                              ║
║      Envia os PDFs de transferidos.json (Guia, Histórico e Parecer).         ║
║        python -m src.automacao.sere_2026 --transferidos --teste              ║
║                                                                              ║
║  --validar                                                                   ║
║      Valida os documentos pendentes. Com --transferidos: só os transferidos. ║
║      --delay N muda a espera entre alunos (padrão 10 s).                     ║
║        python -m src.automacao.sere_2026 --validar --turma 5 --teste         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  OPÇÕES GLOBAIS (combinam com qualquer modo):                                ║
║    --teste     Processa apenas 1 aluno (modo de desenvolvimento)             ║
║    --turma     Ativa seleção interativa de turma (onde aplicável)            ║
║    --turmas    Seleção de múltiplas turmas (modo --limpeza)                  ║
║  --turma [NOME ...]  Turma(s): nome, ano ou início. Sem valor: menu          ║
║  --matriculados / --transferidos  Situação (padrão: só matriculados)         ║
║  --cgm N [N ...]     Só estes CGMs (aceita '123,456;789')                    ║
║  --simular           Só mostra o que seria processado; não executa           ║
║  --confirmo          Confirma sem perguntar (agendador de tarefas)           ║
║  Saída: 0 = concluído · 1 = falhou · 2 = pedido inválido/não confirmado      ║
╚══════════════════════════════════════════════════════════════════════════════╝

Portado de AUTO_SERE/sere_2026.py para src/automacao/sere_2026.py.

ESCOPO: todos os modos estão portados (--limpeza, --documento, --analisa,
--espec, --aluno, --transferidos e --validar) e a função main()/CLI (final do
arquivo) fecha a portabilidade. A interface web usa os mesmos modos pelo
registro (src.comum.registro_scripts); main() é o caminho "sere_2026 --modo"
da linha de comando, com as mesmas regras de turma, prévia e confirmação do
executor genérico (python -m src.comum.cli).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Funções que já existiam duplicadas em outros scripts (norm, navegação,
   API do SERE, remoção de slot) foram substituídas pelos módulos
   compartilhados já portados: src.comum.sere_utils, src.comum.sere_api,
   src.comum.sere_limpeza. Nenhuma regra de negócio mudou — ver os
   docstrings desses módulos para o detalhe de cada correção.

2. remover_slot_por_tipo() (usada só no modo --documento) tinha o MESMO bug
   de tupla que remover_slot() e fazia quase a mesma coisa com um filtro
   ligeiramente diferente (por idtipo OU nome, em vez de só nome). Unificada
   com remover_slot() de src.comum.sere_limpeza (parâmetro idtipo_alvo) —
   aprovado pelo usuário em 29/08/2026.

3. modo_documento() usava Firefox (p.firefox.launch) enquanato modo_limpeza()
   usava Chrome (p.chrome.launch) — inconsistência aparentemente acidental
   entre os dois modos. Padronizado para Firefox nos dois, conforme decisão
   do usuário em 29/08/2026.

4. modo_analisa() carregava analisa_arquivos_sere.py via caminho de arquivo
   (importlib.util.spec_from_file_location(Path(__file__).parent / "...")),
   o que funcionava apenas porque todos os scripts originais moravam na
   mesma pasta. Como agora sere_2026.py está em src/automacao/ e
   analisa_arquivos_sere.py está em src/relatorios/, isso quebraria.
   Trocado por um import de pacote Python normal — mesmo comportamento
   final (chama a main() do mesmo arquivo), sem depender de onde o .py
   fisicamente está no disco.

5. CGM_UPLOAD deixou de ser um array editado manualmente no topo do
   script — agora vem de src.comum.configuracao.cgm_upload(), a mesma
   fonte única já usada por src.relatorios.analisa_arquivos_sere.

6. BASE / DIR_DIGITALIZACAO / JSON_TURMAS / PATH_DOCUMENTOS_ALUNOS: antes
   fixos em Path.home()/Z:\\... (servidor Linux ou letra de unidade
   específica). Dados de trabalho (turmas.json, documentos-alunos.json)
   agora resolvidos via src.comum.paths.dados_ano_atual(); a pasta de
   digitalização agora vem de src.comum.configuracao.pasta_digitalizacao()
   (configurada pelo usuário no setup inicial, ver src/comum/configuracao.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from src.comum.credenciais import LOGIN, SENHA
from src.comum.logger import get_logger
from src.comum import paths as _paths
from src.comum.configuracao import cgm_upload as _cgm_upload_configurado, pasta_digitalizacao, pasta_digitalizacao_configurada
from src.comum.sere_normalizacao import IDTIPO_PARA_SLOT, SINONIMOS
from src.comum.sere_utils import norm, slot_para_idtipo
from src.comum.sere_api import (
    URL,
    esta_na_tela_login,
    navegar_por_aluno,
    navegar_pasta_virtual,
    buscar_documentos_api,
    excluir_arquivo_api,
)
from src.comum.sere_limpeza import remover_slot, limpar_aluno
from src.comum.sere_upload import (
    deve_pular_slot,
    obter_slots_api,
    obter_nomes_slots_api,
    excluir_slot_e_obter_hash,
    injetar_e_enviar,
)
from src.comum import navegador as _navegador

log = get_logger(__file__)

# ─────────────────────────────────────────────────────────────────────────────
# ANO DINÂMICO
# Detecta o ano corrente automaticamente — não é necessário editar a cada ano.
# Reaproveita src.comum.paths.ano_atual(), que já faz a mesma coisa (com a
# vantagem extra de poder ser sobrescrito por AUTO_SERE_ANO_BASE em janeiro/
# fevereiro, quando o ano letivo do SERE pode estar "atrasado" em relação
# ao calendário civil).
# ─────────────────────────────────────────────────────────────────────────────

ANO_BASE: str = _paths.ano_atual()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÕES GLOBAIS
# ─────────────────────────────────────────────────────────────────────────────

# Pasta de dados de trabalho do ano letivo corrente (turmas.json,
# documentos-alunos.json, etc.) — <pasta_de_instalação>/dados/<ano>/.
_DADOS = _paths.dados_ano_atual()
_DADOS.mkdir(parents=True, exist_ok=True)

# JSON com a estrutura de turmas e alunos (fonte principal)
JSON_TURMAS = _DADOS / "turmas.json"

# JSON com histórico de documentos por aluno (data de upload + validação)
PATH_DOCUMENTOS_ALUNOS = _DADOS / "documentos-alunos.json"

# JSON de controle de transferidos — antes fixo em BASE/"PYTHON/SERE"/ano
# (caminho diferente até dos outros dados de trabalho do original). Agora
# é dados de trabalho como qualquer outro (decisão do usuário, 29/08/2026).
PATH_TRANSFERIDOS = _DADOS / "transferidos.json"

# Máximo de tentativas de exclusão por slot (para versões empilhadas no SERE)
MAX_TENTATIVAS_SLOT = 15

# Máximo de tentativas de validação por documento (modo --validar)
MAX_TENTATIVAS_VALIDACAO = 30

# Espera padrão (segundos) entre cada clique de validação, antes de
# recarregar a página — dá tempo do SERE processar o clique.
DELAY_VALIDACAO_PADRAO = 10

# Após quantas falhas de recarga/navegação CONSECUTIVAS o modo --validar
# desiste e encerra o script (sinal de que a sessão do SERE travou/caiu).
MAX_RECARGAS_CONSECUTIVAS_FALHA = 3

# Slots protegidos — nunca são removidos pela limpeza
SLOTS_PROTEGIDOS_NORM = {
    "PARECER DESCRITIVO",
    "REQUERIMENTO DE MATRICULA",
    "DECLARACAO DE MATRICULA",
}

# Slots ativos — documentos que o script envia automaticamente (modos
# --espec e --aluno). Igual a SLOTS_ATIVOS no sere_2026.py original.
SLOTS_ATIVOS = [
    "Comprovante de residência",
    "Certidão de nascimento do aluno",
    "CPF Responsável",
    "Comprovante de Vacinação",
    "Declaração de vacina",
    "RG do aluno",
    "CPF do aluno",
    "CPF do Responsável",
]

# Extensões de arquivo aceitas pelo SERE
EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png"}

# Grupos de slots que compartilham o mesmo arquivo físico (ex.: o mesmo PDF
# de carteirinha de vacinação serve tanto para "Declaração de vacina"
# quanto para "Comprovante de Vacinação").
SLOTS_COMPARTILHAM_ARQUIVO: list[set[str]] = [
    {"Declaração de vacina", "Comprovante de Vacinação", "Carteira de vacinação"},
    {"RG do aluno", "RG"},
]

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÕES DO MODO --transferidos
# ─────────────────────────────────────────────────────────────────────────────
# Decisões de arquitetura (usuário, 29/08/2026):
#   - PATH_TRANSFERIDOS (transferidos.json): antes fixo em
#     BASE/"PYTHON/SERE"/ano — um caminho FIXO diferente até dos outros
#     dados de trabalho do próprio script original (que usavam BASE/ano).
#     Agora é dados de trabalho como qualquer outro — vai para
#     dados/<ano>/transferidos.json, junto de turmas.json e
#     documentos-alunos.json.
#   - DIR_GUIAS / DIR_HISTORICOS / DIR_PARECERES (pastas com os PDFs de
#     guia de transferência, histórico e parecer): antes fixas no caminho
#     do servidor Linux. Conceitualmente são pasta de digitalização — o
#     usuário escolhe onde ficam os documentos digitalizados/gerados.
#     Agora são subpastas dentro de configuracao.pasta_digitalizacao():
#         <pasta_digitalizacao>/TRANSFERENCIAS/GUIA DE TRANSFERENCIA
#         <pasta_digitalizacao>/TRANSFERENCIAS/HISTÓRICOS
#         <pasta_digitalizacao>/TRANSFERENCIAS/PARECERES
#     Resolvidas em runtime (dentro de modo_transferidos), pois a pasta de
#     digitalização pode não estar configurada ainda no momento do import.

# Data de corte: só processa transferidos com documentos APÓS essa data.
# Ajuste conforme necessário antes de rodar --transferidos.
def _corte_transferidos() -> datetime:
    """DATA_CORTE em vigor (Configurações; padrão 22/06 do ano letivo), lida a cada uso."""
    from src.comum.configuracao import data_corte_transferidos
    d = data_corte_transferidos()
    return datetime(d.year, d.month, d.day)



# Mapeamento dos três tipos de documento que o modo --transferidos trata.
# Os valores de "dir" são preenchidos em runtime dentro de modo_transferidos()
# a partir de configuracao.pasta_digitalizacao(), pois essa pasta pode ainda
# não estar configurada no momento em que este módulo é importado.
#
# CORREÇÃO DE BUG (aprovada pelo usuário em 29/08/2026, confirmada cruzando
# com processo_tranferidos.py — o script que gera/mantém transferidos.json):
# No original, "campo_data" de guia e histórico era "anexado_em" — o MESMO
# campo que só é preenchido DEPOIS que este próprio script (sere_2026.py)
# faz o upload com sucesso. Ou seja, na primeira execução nenhum documento
# seria processado, porque anexado_em sempre começa como None (confirmado
# em processo_tranferidos.py: _registro_vazio() inicializa anexado_em=None,
# e a única escrita nesse campo é a chamada marcar(cgm, tipo, "anexado_em")
# feita pelo próprio sere_2026.py após o upload). O campo que de fato
# sinaliza "documento pronto para anexar" é assinado_diretor — a última
# etapa do fluxo de assinatura antes do upload no SERE (ver
# InfoDocJSON.valido em processo_tranferidos.py, que checa
# assinado_secretario + assinado_diretor, nunca anexado_em). Corrigido para
# "campo_data": "assinado_diretor" em guia e histórico. "anexado_em"
# continua sendo usado (corretamente, como no original) para o skip duplo
# e para ser gravado após o sucesso do upload — ver modo_transferidos().
# "parecer" já usava "digitalizado_em" no original, que é o campo correto
# (confirmado: processo_tranferidos.py grava parecer.digitalizado_em numa
# etapa própria, distinta de parecer.anexado_em) — não precisou de ajuste.
TRANSFERIDOS_SLOTS: dict[str, dict] = {
    "guia": {
        "idtipo":     "10",
        "nome_slot":  "Guia de Transferência",
        "campo_json": "guia",
        "campo_data": "assinado_diretor",  # corrigido — era "anexado_em"
        "dir":        None,   # preenchido em runtime, subpasta "TRANSFERENCIAS/GUIA DE TRANSFERENCIA"
    },
    "historico": {
        "idtipo":     "9",
        "nome_slot":  "Histórico do Ensino Fundamental",
        "campo_json": "historico",
        "campo_data": "assinado_diretor",  # corrigido — era "anexado_em"
        "dir":        None,   # preenchido em runtime, subpasta "TRANSFERENCIAS/HISTÓRICOS"
    },
    "parecer": {
        "idtipo":     "38",
        "nome_slot":  "Parecer Descritivo 2026-1",
        "campo_json": "parecer",
        "campo_data": "digitalizado_em",
        "dir":        None,   # preenchido em runtime, subpasta "TRANSFERENCIAS/PARECERES"
    },
}


def _pasta_digitalizacao_ou_avisar() -> Path | None:
    """
    Resolve a pasta de digitalização configurada pelo usuário. Se ainda não
    foi configurada (setup inicial pendente), avisa e retorna None — quem
    chamar deve checar o retorno antes de prosseguir, em vez de assumir um
    caminho fixo que talvez não exista (ver src/comum/configuracao.py).
    """
    caminho = pasta_digitalizacao()
    if caminho is None:
        print("⚠️  A pasta de digitalização ainda não foi configurada.")
        print("    Rode o setup inicial (escolha da pasta de documentos digitalizados)")
        print("    antes de usar modos que dependem dela.")
    return caminho


# ─────────────────────────────────────────────────────────────────────────────
# CARREGAR / SALVAR documentos-alunos.json
# ─────────────────────────────────────────────────────────────────────────────

def carregar_documentos_alunos() -> dict[str, dict[str, dict]]:
    """
    Lê documentos-alunos.json e retorna índice por CGM:
        { "<cgm>": { "<tipo_norm>": { "data": "DD/MM/YYYY HH:MM", "validado": bool } } }
    Retorna dicionário vazio se o arquivo não existir.
    """
    if not PATH_DOCUMENTOS_ALUNOS.exists():
        log.warning(f"'{PATH_DOCUMENTOS_ALUNOS}' não encontrado — todos os docs serão tratados como novos")
        return {}
    try:
        with open(PATH_DOCUMENTOS_ALUNOS, encoding="utf-8") as f:
            lista = json.load(f)
        indice: dict[str, dict[str, dict]] = {}
        for aluno in lista:
            cgm = str(aluno.get("CGM", "")).strip()
            if not cgm:
                continue
            detalhes: dict[str, dict] = {}
            for det in aluno.get("Detalhes", []):
                tipo_norm = norm(det.get("tipo", ""))
                if tipo_norm:
                    detalhes[tipo_norm] = {
                        "data":     det.get("data", ""),
                        "validado": bool(det.get("validado", False)),
                    }
            indice[cgm] = detalhes
        log.info(f"documentos-alunos.json carregado: {len(indice)} aluno(s)")
        return indice
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"Erro ao ler '{PATH_DOCUMENTOS_ALUNOS}': {exc} — índice vazio")
        return {}


def atualizar_documentos_alunos_via_api(page_result_por_cgm: dict[str, list[dict]]) -> None:
    """
    Recebe um dicionário { cgm: [lista de documentos da API] } e atualiza
    (ou cria) o documentos-alunos.json. Sobrescreve os registros dos CGMs processados.
    """
    existentes: list[dict] = []
    if PATH_DOCUMENTOS_ALUNOS.exists():
        try:
            with open(PATH_DOCUMENTOS_ALUNOS, encoding="utf-8") as f:
                existentes = json.load(f)
        except (json.JSONDecodeError, OSError):
            existentes = []

    cgms_atualizados = set(page_result_por_cgm.keys())
    lista_final = [a for a in existentes if str(a.get("CGM", "")) not in cgms_atualizados]

    for cgm, docs_api in page_result_por_cgm.items():
        detalhes = []
        for doc in docs_api:
            nome_arquivo = doc.get("nomearquivo", "").strip()
            if not nome_arquivo:
                continue
            detalhes.append({
                "tipo":     doc.get("tipodocumento", "").strip(),
                "arquivo":  nome_arquivo,
                "data":     doc.get("datainclusao", "").strip(),
                "validado": _parse_validado(doc.get("tag")),
            })
        lista_final.append({
            "CGM":      cgm,
            "Detalhes": detalhes,
            "Total":    len(detalhes),
        })

    with open(PATH_DOCUMENTOS_ALUNOS, "w", encoding="utf-8") as f:
        json.dump(lista_final, f, ensure_ascii=False, indent=2)

    log.info(f"documentos-alunos.json atualizado — {len(lista_final)} aluno(s) no arquivo")
    print(f"  💾 documentos-alunos.json atualizado ({len(lista_final)} aluno(s))")


def _parse_validado(tag_raw) -> bool:
    """Verifica se o campo 'tag' da API indica validado=SIM."""
    if not tag_raw:
        return False
    try:
        tag_list = json.loads(tag_raw) if isinstance(tag_raw, str) else tag_raw
        return any(
            str(t.get("validado", "")).upper() == "SIM"
            for t in tag_list
            if isinstance(t, dict)
        )
    except (json.JSONDecodeError, TypeError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CARREGAR TURMAS
# ─────────────────────────────────────────────────────────────────────────────

def carregar_turmas() -> dict[str, list[dict]]:
    """Lê turmas.json e retorna { nome_turma: [lista de alunos] }."""
    log.info(f"Carregando turmas de: {JSON_TURMAS}")
    with open(JSON_TURMAS, encoding="utf-8") as f:
        dados = json.load(f)
    total_alunos = sum(len(v) for v in dados.values())
    log.info(f"Turmas: {len(dados)} | Alunos: {total_alunos}")
    return dados


# ─────────────────────────────────────────────────────────────────────────────
# MENUS INTERATIVOS
# ─────────────────────────────────────────────────────────────────────────────

def menu_selecionar_turma(turmas: dict) -> str | None:
    """
    Exibe menu numerado de turmas e retorna o nome da turma escolhida.
    Retorna None se o usuário cancelar (opção 0).
    """
    lista = sorted(turmas.keys())
    print("\n" + "═" * 55)
    print("  SELECIONE A TURMA")
    print("═" * 55)
    for i, nome in enumerate(lista, 1):
        print(f"  {i:>3}. {nome}  ({len(turmas[nome])} alunos)")
    print("─" * 55)
    print("    0. Cancelar")
    print("═" * 55)
    while True:
        try:
            entrada = input("\nDigite o número da turma: ").strip()
            if entrada == "0":
                print("Operação cancelada.")
                return None
            n = int(entrada)
            if 1 <= n <= len(lista):
                escolhida = lista[n - 1]
                print(f"\n✅ Turma selecionada: {escolhida}")
                return escolhida
            print(f"❌ Número inválido. Digite entre 1 e {len(lista)} (ou 0 para cancelar).")
        except ValueError:
            print("❌ Entrada inválida. Digite apenas o número.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperação cancelada.")
            return None


def menu_selecionar_multiplas_turmas(turmas: dict) -> list[str]:
    """
    Exibe menu de seleção múltipla de turmas.
    Suporta: '1', '1 2 3', '2-5', 'todas'.
    """
    nomes = sorted(turmas.keys())
    print(f"\n{'─'*55}")
    print("  SELEÇÃO DE TURMAS  (0 = todas)")
    print(f"{'─'*55}")
    for i, nome in enumerate(nomes, 1):
        print(f"  {i:>3}. {nome:<30} ({len(turmas[nome])} alunos)")
    print(f"{'─'*55}")
    print("  Use: '1', '1 2 3', '2-5', ou 'todas'")
    print(f"{'─'*55}")

    while True:
        entrada = input("  Turmas: ").strip()
        if not entrada:
            print("  ⚠️  Nenhuma entrada.")
            continue
        if entrada.lower() in ("todas", "all", "0"):
            return nomes

        indices: list[int] = []
        valido = True
        for parte in entrada.split():
            if "-" in parte:
                try:
                    ini, fim = map(int, parte.split("-", 1))
                    if not (1 <= ini <= len(nomes) and 1 <= fim <= len(nomes)):
                        raise ValueError
                    indices.extend(range(ini, fim + 1))
                except ValueError:
                    print(f"  ⚠️  Intervalo inválido: '{parte}'")
                    valido = False
                    break
            else:
                try:
                    n = int(parte)
                    if not (1 <= n <= len(nomes)):
                        raise ValueError
                    indices.append(n)
                except ValueError:
                    print(f"  ⚠️  Número inválido: '{parte}'")
                    valido = False
                    break
        if not valido:
            continue

        vistos: set[int] = set()
        unicos = [i for i in indices if not (i in vistos or vistos.add(i))]
        selecionadas = [nomes[i - 1] for i in unicos]

        total = sum(len(turmas[t]) for t in selecionadas)
        print(f"\n  ✅ {len(selecionadas)} turma(s) | {total} aluno(s)")
        for t in selecionadas:
            print(f"     • {t} ({len(turmas[t])} alunos)")
        print()
        return selecionadas


def menu_selecionar_tipo_documento() -> tuple[str, str] | None:
    """
    Exibe menu com todos os tipos de documento do SERE.
    Retorna (idtipo, nome_slot) ou None se cancelado.
    """
    tipos_disponiveis = {
        idtipo: nome
        for idtipo, nome in IDTIPO_PARA_SLOT.items()
        if "reservado" not in nome.lower()
    }
    lista = sorted(tipos_disponiveis.items(), key=lambda x: int(x[0]))

    print("\n" + "═" * 65)
    print("  TIPOS DE DOCUMENTO DISPONÍVEIS NO SERE")
    print("  Selecione o ID do tipo que deseja remover de todos os alunos")
    print("═" * 65)
    for idtipo, nome in lista:
        print(f"  [{idtipo:>2}] {nome}")
    print("─" * 65)
    print("  [  0] Cancelar")
    print("═" * 65)

    while True:
        try:
            entrada = input("\nDigite o ID do documento: ").strip()
            if entrada == "0":
                print("Operação cancelada.")
                return None
            if entrada in tipos_disponiveis:
                nome = tipos_disponiveis[entrada]
                print(f"\n✅ Selecionado: [{entrada}] {nome}")
                return entrada, nome
            print(f"❌ ID '{entrada}' não reconhecido. Tente novamente (ou 0 para cancelar).")
        except (KeyboardInterrupt, EOFError):
            print("\nOperação cancelada.")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# MODO --limpeza
# ─────────────────────────────────────────────────────────────────────────────

async def modo_limpeza(
    modo_teste: bool,
    turmas_selecionadas: list[str],
    turmas: dict,
) -> None:
    """Modo --limpeza: remove TODOS os arquivos de todos os alunos das turmas selecionadas."""
    lista_alunos: list[tuple[str, dict]] = [
        (nome_turma, aluno)
        for nome_turma in turmas_selecionadas
        for aluno in turmas[nome_turma]
    ]
    if modo_teste:
        lista_alunos = lista_alunos[:1]
        print("⚠️  MODO TESTE — processando apenas 1 aluno\n")

    print(f"\n{'='*65}")
    print(f"  LIMPEZA DE DOCUMENTOS — SERE {ANO_BASE}")
    print(f"  Remove TODOS os arquivos (exceto slots protegidos)")
    print(f"{'='*65}")
    print(f"  📋 Turmas            : {len(turmas_selecionadas)}")
    print(f"  👥 Alunos            : {len(lista_alunos)}")
    print(f"  🔁 Tentativas/slot   : {MAX_TENTATIVAS_SLOT}")
    print(f"  🔒 Slots protegidos  : {', '.join(SLOTS_PROTEGIDOS_NORM)}")
    if modo_teste:
        print("  🧪 MODO TESTE        : SIM (1 aluno)")
    print(f"{'='*65}\n")

    resultados: list[dict] = []
    completos:  list[dict] = []
    com_falha:  list[dict] = []
    docs_restantes_por_cgm: dict[str, list[dict]] = {}

    print("Entrou no Playwright")

    async with async_playwright() as p:
        # Padronizado para Firefox (decisão do usuário em 29/08/2026 — o
        # original usava Chrome aqui e Firefox em modo_documento, uma
        # inconsistência aparentemente acidental entre os dois modos).
        print("Vai abrir o Firefox")
        browser = await _navegador.lancar(p, "firefox", True)
        print("Firefox aberto")
        page    = await browser.new_page()
        await page.goto(URL)

        print("🔐 Fazendo login…")
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        print("✅ Login efetuado.\n")

        await navegar_por_aluno(page)

        total = len(lista_alunos)
        for idx, (nome_turma, aluno) in enumerate(lista_alunos, 1):
            cgm_aluno  = str(aluno.get("CGM", ""))
            nome_aluno = aluno.get("Nome", "SemNome")
            print(f"\n{'─'*65}")
            print(f"  [{idx:02d}/{total}] Processando…")

            try:
                res, docs_api = await limpar_aluno(page, aluno, nome_turma, SLOTS_PROTEGIDOS_NORM)
                resultados.append(res)
                docs_restantes_por_cgm[cgm_aluno] = docs_api

                if res["Status"] in ("Todos removidos", "Nenhum arquivo para remover"):
                    completos.append(res)
                elif "Ignorado" not in res["Status"]:
                    com_falha.append(res)

            except Exception as exc:
                msg = str(exc)
                log.exception(f"[{idx}/{total}] Erro inesperado: '{nome_aluno}': {msg}")
                print(f"     ❌ Erro inesperado: {msg}")
                res = {
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": f"Erro: {msg}", "Removidos": [], "Protegidos": [], "Falhas": [],
                }
                resultados.append(res)
                com_falha.append(res)

            try:
                voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                if voltar:
                    await voltar.click()
                else:
                    await page.go_back()
                await page.wait_for_timeout(1_500)
            except Exception as e:
                log.warning(f"Erro ao voltar: {e}")

        await browser.close()

    print("\n📄 Atualizando documentos-alunos.json com estado pós-limpeza…")
    atualizar_documentos_alunos_via_api(docs_restantes_por_cgm)

    sufixo     = "_TESTE" if modo_teste else ""
    path_ok    = _DADOS / f"limpeza-documentos_concluidos-{ANO_BASE}{sufixo}.json"
    path_falha = _DADOS / f"limpeza-documentos_falhas-{ANO_BASE}{sufixo}.json"
    for p in (path_ok, path_falha):
        if p.exists():
            p.unlink()

    with open(path_ok, "w", encoding="utf-8") as f:
        json.dump({
            "Total": len(completos), "Turmas": turmas_selecionadas,
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "Alunos": completos,
        }, f, ensure_ascii=False, indent=4)
    with open(path_falha, "w", encoding="utf-8") as f:
        json.dump({
            "Total": len(com_falha), "Turmas": turmas_selecionadas,
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "Alunos": com_falha,
        }, f, ensure_ascii=False, indent=4)

    print(f"\n{'='*65}")
    print(f"  ✅ LIMPEZA FINALIZADA{' (TESTE)' if modo_teste else ''}")
    print(f"     Concluídos : {len(completos)}")
    print(f"     Com falha  : {len(com_falha)}")
    print(f"     Total      : {len(resultados)}")
    print(f"  📄 OK          : {path_ok}")
    print(f"  ⚠️  Falhas      : {path_falha}")
    print(f"  💾 Docs JSON   : {PATH_DOCUMENTOS_ALUNOS}")
    print(f"{'='*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# MODO --documento
# ─────────────────────────────────────────────────────────────────────────────
# remover_slot_por_tipo() foi removida daqui — unificada com
# src.comum.sere_limpeza.remover_slot(idtipo_alvo=...), que reproduz o mesmo
# comportamento (bate por idtipo OU nome do slot) com o bug de tupla já
# corrigido. Ver o docstring de sere_limpeza.py para o detalhe.

async def modo_documento(
    idtipo: str,
    nome_slot: str,
    modo_teste: bool,
    turmas_selecionadas: list[str],
    turmas: dict,
) -> None:
    """Modo --documento: remove apenas o tipo de documento especificado de todos os alunos."""
    lista_alunos = [
        (nome_turma, aluno)
        for nome_turma in turmas_selecionadas
        for aluno in turmas[nome_turma]
    ]

    total_antes_situacao = len(lista_alunos)
    ignorados_situacao = [
        (nome_turma, aluno) for (nome_turma, aluno) in lista_alunos
        if norm(aluno.get("Situação", "")) != norm("Matriculado")
    ]
    lista_alunos = [
        (nome_turma, aluno) for (nome_turma, aluno) in lista_alunos
        if norm(aluno.get("Situação", "")) == norm("Matriculado")
    ]
    if ignorados_situacao:
        print(f"🎯 Filtro Situação=Matriculado: {len(lista_alunos)} de "
              f"{total_antes_situacao} aluno(s) serão processados "
              f"({len(ignorados_situacao)} ignorado(s) por situação diferente).")

    if modo_teste:
        lista_alunos = lista_alunos[:1]
        print("⚠️  MODO TESTE — processando apenas 1 aluno\n")

    print(f"\n{'='*65}")
    print(f"  REMOÇÃO POR TIPO — SERE {ANO_BASE}")
    print(f"  Tipo: [{idtipo}] {nome_slot}")
    print(f"{'='*65}")
    print(f"  👥 Alunos            : {len(lista_alunos)}")
    print(f"  🔁 Tentativas/slot   : {MAX_TENTATIVAS_SLOT}")
    if modo_teste:
        print("  🧪 MODO TESTE        : SIM")
    print(f"{'='*65}\n")

    resultados: list[dict] = []
    docs_restantes_por_cgm: dict[str, list[dict]] = {}

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True)
        page    = await browser.new_page()
        await page.goto(URL)

        print("🔐 Fazendo login…")
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        print("✅ Login efetuado.\n")

        await navegar_por_aluno(page)

        total = len(lista_alunos)
        for idx, (nome_turma, aluno) in enumerate(lista_alunos, 1):
            cgm_aluno  = str(aluno.get("CGM", ""))
            nome_aluno = aluno.get("Nome", "SemNome")
            print(f"\n{'─'*65}")
            print(f"  [{idx:02d}/{total}] {nome_aluno}  (CGM: {cgm_aluno})")

            try:
                ok = await navegar_pasta_virtual(page, cgm_aluno)
                if not ok:
                    print(f"     ❌ Não foi possível abrir a pasta virtual")
                    resultados.append({
                        "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                        "Status": "Falha ao abrir pasta virtual",
                    })
                    continue

                sucesso, msg = await remover_slot(
                    page, cgm_aluno, {"tipodocumento": nome_slot},
                    max_tentativas=MAX_TENTATIVAS_SLOT, idtipo_alvo=idtipo,
                )
                status_txt = "✅" if sucesso else "❌"
                print(f"     {status_txt} {nome_slot}: {msg}")

                docs_api = await buscar_documentos_api(page, cgm_aluno)
                docs_restantes_por_cgm[cgm_aluno] = docs_api

                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": "OK" if sucesso else "Falhou",
                    "Slot": nome_slot, "Mensagem": msg,
                })

            except Exception as exc:
                print(f"     ❌ Erro inesperado: {exc}")
                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": f"Erro: {exc}",
                })

            try:
                voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                if voltar:
                    await voltar.click()
                else:
                    await page.go_back()
                await page.wait_for_timeout(1_500)
            except Exception as e:
                log.warning(f"Erro ao voltar: {e}")

        await browser.close()

    print("\n📄 Atualizando documentos-alunos.json…")
    atualizar_documentos_alunos_via_api(docs_restantes_por_cgm)

    ok_count    = sum(1 for r in resultados if r.get("Status") == "OK")
    falha_count = sum(1 for r in resultados if r.get("Status") not in ("OK",))

    sufixo     = "_TESTE" if modo_teste else ""
    path_saida = _DADOS / f"remocao_tipo_{idtipo}{sufixo}.json"
    with open(path_saida, "w", encoding="utf-8") as f:
        json.dump({
            "Tipo_Removido": nome_slot, "ID_Tipo": idtipo,
            "Total": len(resultados), "OK": ok_count, "Falhas": falha_count,
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "Alunos": resultados,
        }, f, ensure_ascii=False, indent=4)

    print(f"\n{'='*65}")
    print(f"  ✅ REMOÇÃO POR TIPO FINALIZADA")
    print(f"     Tipo    : [{idtipo}] {nome_slot}")
    print(f"     OK      : {ok_count}")
    print(f"     Falhas  : {falha_count}")
    print(f"  📄 Resultado: {path_saida}")
    print(f"  💾 Docs JSON: {PATH_DOCUMENTOS_ALUNOS}")
    print(f"{'='*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# MODO --analisa
# ─────────────────────────────────────────────────────────────────────────────

def modo_analisa(args_extras: list[str]) -> None:
    """
    Modo --analisa: reutiliza o código de src.relatorios.analisa_arquivos_sere
    via import de pacote.

    Antes: importlib.util.spec_from_file_location(Path(__file__).parent /
    "analisa_arquivos_sere.py") — carregava o arquivo pelo caminho em disco,
    o que só funcionava porque os dois scripts moravam na mesma pasta.
    Como agora sere_2026.py está em src/automacao/ e analisa_arquivos_sere.py
    está em src/relatorios/, esse caminho relativo apontaria para um arquivo
    inexistente. Trocado por um import de pacote Python normal — mesmo
    resultado final (chama a main() do módulo), sem depender de onde o
    arquivo está fisicamente no disco.
    """
    print("\n" + "=" * 65)
    print("  MODO ANALISA — executando src.relatorios.analisa_arquivos_sere")
    print("=" * 65 + "\n")

    sys.argv = ["analisa_arquivos_sere"] + args_extras

    try:
        from src.relatorios import analisa_arquivos_sere as modulo
    except ModuleNotFoundError:
        print("❌ src.relatorios.analisa_arquivos_sere não encontrado.")
        sys.exit(1)

    if not hasattr(modulo, "main"):
        print("❌ analisa_arquivos_sere não possui função main().")
        sys.exit(1)

    asyncio.run(modulo.main())


# ─────────────────────────────────────────────────────────────────────────────
# LOCALIZAÇÃO DE PASTAS DE DIGITALIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def encontrar_pasta_aluno(pasta_turma: Path, numero: int, nome: str) -> Path | None:
    """Localiza a pasta do aluno dentro da pasta da turma pelo número ou nome."""
    nome_norm = norm(nome)
    for entry in pasta_turma.iterdir():
        if not entry.is_dir():
            continue
        entry_norm = norm(entry.name)
        partes     = entry_norm.split(" - ", 1)
        num_pasta  = partes[0].strip()
        nome_pasta = partes[1].strip() if len(partes) == 2 else ""

        if num_pasta.isdigit() and int(num_pasta) == numero:
            return entry
        if nome_pasta and nome_pasta == nome_norm:
            return entry
    return None


def encontrar_pasta_turma(nome_turma: str) -> Path | None:
    """
    Localiza a pasta física da turma dentro da pasta de digitalização
    configurada pelo usuário (ver src/comum/configuracao.py). Antes:
    DIR_DIGITALIZACAO era um caminho fixo (BASE / ANO_BASE / "DIGITALIZAÇÃO").
    Retorna None tanto se a pasta de digitalização ainda não foi configurada
    quanto se a turma não for encontrada dentro dela — quem chama já trata
    esse caso (ver processar_aluno_upload e modo_espec).
    """
    dir_digitalizacao = pasta_digitalizacao()
    if dir_digitalizacao is None or not dir_digitalizacao.exists():
        return None
    n = norm(nome_turma)
    variações = [n, n.replace("O ANO", "º ANO"), n.replace("º", "O").replace("ª", "A")]
    for entry in dir_digitalizacao.iterdir():
        if not entry.is_dir():
            continue
        entry_norm = norm(entry.name)
        for v in variações:
            if entry_norm == v or v in entry_norm or entry_norm in v:
                return entry
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MODO --espec
# ─────────────────────────────────────────────────────────────────────────────

async def modo_espec(
    idtipo_alvo: str,
    nome_slot: str,
    modo_teste: bool,
    turmas_selecionadas: list[str],
    turmas: dict,
) -> None:
    """Modo --espec: faz upload de um tipo específico para todos os alunos."""
    if _pasta_digitalizacao_ou_avisar() is None:
        return

    lista_alunos = [
        (nome_turma, aluno)
        for nome_turma in turmas_selecionadas
        for aluno in turmas[nome_turma]
    ]
    if modo_teste:
        lista_alunos = lista_alunos[:1]
        print("⚠️  MODO TESTE — processando apenas 1 aluno\n")

    indice_docs = carregar_documentos_alunos()

    print(f"\n{'='*65}")
    print(f"  UPLOAD ESPECÍFICO — SERE {ANO_BASE}")
    print(f"  Tipo: [{idtipo_alvo}] {nome_slot}")
    print(f"{'='*65}")
    print(f"  👥 Alunos : {len(lista_alunos)}")
    if modo_teste:
        print("  🧪 MODO TESTE : SIM")
    print(f"{'='*65}\n")

    resultados: list[dict] = []

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True)
        page    = await browser.new_page()
        await page.goto(URL)

        print("🔐 Fazendo login…")
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        print("✅ Login efetuado.\n")

        await navegar_por_aluno(page)

        total = len(lista_alunos)
        for idx, (nome_turma, aluno) in enumerate(lista_alunos, 1):
            cgm_aluno  = str(aluno.get("CGM", ""))
            nome_aluno = aluno.get("Nome", "SemNome")
            numero     = aluno.get("N", 0)
            print(f"\n{'─'*65}")
            print(f"  [{idx:02d}/{total}] {nome_aluno}  (CGM: {cgm_aluno})")

            pular, motivo = deve_pular_slot(indice_docs, cgm_aluno, nome_slot)
            if pular:
                print(f"     ⏭️  Pulado — {motivo}")
                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": f"Pulado — {motivo}",
                })
                continue

            pasta_turma = encontrar_pasta_turma(nome_turma)
            if not pasta_turma:
                print(f"     ❌ Pasta da turma não encontrada: {nome_turma}")
                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": "Pasta da turma não encontrada",
                })
                continue

            pasta_aluno = encontrar_pasta_aluno(pasta_turma, numero, nome_aluno)
            if not pasta_aluno:
                print(f"     ❌ Pasta do aluno não encontrada")
                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": "Pasta do aluno não encontrada",
                })
                continue

            arquivo_alvo: Path | None = None
            sinonimos_slot = SINONIMOS.get(nome_slot, [norm(nome_slot)])
            for arq in pasta_aluno.iterdir():
                if arq.suffix.lower() not in EXTENSOES_ACEITAS:
                    continue
                arq_norm = norm(arq.stem)
                for sinonimo in sinonimos_slot:
                    if norm(sinonimo) in arq_norm or arq_norm in norm(sinonimo):
                        arquivo_alvo = arq
                        break
                if arquivo_alvo:
                    break

            if not arquivo_alvo:
                print(f"     ⚠️  Arquivo do tipo '{nome_slot}' não encontrado em {pasta_aluno.name}")
                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": "Arquivo não encontrado na pasta",
                })
                continue

            try:
                ok = await navegar_pasta_virtual(page, cgm_aluno)
                if not ok:
                    print(f"     ❌ Falha ao abrir pasta virtual")
                    resultados.append({
                        "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                        "Status": "Falha ao abrir pasta virtual",
                    })
                    continue

                hash_upload, assinatura_existente = await obter_slots_api(page, cgm_aluno)

                if idtipo_alvo in assinatura_existente:
                    hash_doc = await excluir_slot_e_obter_hash(
                        page, cgm_aluno, nome_slot, idtipo_alvo,
                        assinatura_existente[idtipo_alvo]
                    )
                else:
                    hash_doc = hash_upload.get(idtipo_alvo)

                if not hash_doc:
                    print(f"     ❌ Hash não encontrado para [{idtipo_alvo}] {nome_slot}")
                    resultados.append({
                        "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                        "Status": "Hash não encontrado",
                    })
                else:
                    sucesso, msg = await injetar_e_enviar(page, hash_doc, arquivo_alvo)
                    status_txt = "✅" if sucesso else "❌"
                    print(f"     {status_txt} {nome_slot}: {msg}")
                    resultados.append({
                        "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                        "Arquivo": arquivo_alvo.name,
                        "Status": "OK" if sucesso else "Erro",
                        "Mensagem": msg,
                    })

            except Exception as exc:
                print(f"     ❌ Erro inesperado: {exc}")
                resultados.append({
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": f"Erro: {exc}",
                })

            try:
                voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                if voltar:
                    await voltar.click()
                else:
                    await page.go_back()
                await page.wait_for_timeout(1_500)
            except Exception as e:
                log.warning(f"Erro ao voltar: {e}")

        await browser.close()

    sufixo     = "_TESTE" if modo_teste else ""
    path_saida = _DADOS / f"upload_espec_{idtipo_alvo}{sufixo}.json"
    with open(path_saida, "w", encoding="utf-8") as f:
        json.dump({
            "Tipo": nome_slot, "ID_Tipo": idtipo_alvo,
            "Total": len(resultados),
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "Alunos": resultados,
        }, f, ensure_ascii=False, indent=4)

    ok_count = sum(1 for r in resultados if r.get("Status") == "OK")
    print(f"\n{'='*65}")
    print(f"  ✅ UPLOAD ESPECÍFICO FINALIZADO")
    print(f"     Tipo  : [{idtipo_alvo}] {nome_slot}")
    print(f"     OK    : {ok_count} / {len(resultados)}")
    print(f"  📄 Resultado: {path_saida}")
    print(f"{'='*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# MODO --aluno
# ─────────────────────────────────────────────────────────────────────────────

async def processar_aluno_upload(
    page, aluno: dict, nome_turma: str, pasta_turma: Path | None,
    indice_docs: dict, slots_reprocessar: set | None = None,
) -> dict:
    """Processa o upload dos documentos de um aluno específico."""
    cgm      = str(aluno["CGM"])
    nome     = aluno.get("Nome", "SemNome")
    numero   = aluno.get("N", 0)
    situacao = aluno.get("Situação", "")

    print(f"  🔎 {nome}  (CGM: {cgm}  |  Turma: {nome_turma})")

    resultado = {
        "CGM": cgm, "Nome": nome, "Turma": nome_turma,
        "Status": "Não processado", "Documentos": {},
        "Faltando": [],
        "Data_Processamento": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    }

    if "TRANSFER" in norm(situacao):
        resultado["Status"] = f"Ignorado (situação: {situacao})"
        return resultado

    if pasta_turma is None:
        resultado["Status"]   = "Pasta da turma não encontrada"
        resultado["Faltando"] = SLOTS_ATIVOS[:]
        return resultado

    pasta_aluno = encontrar_pasta_aluno(pasta_turma, numero, nome)
    if not pasta_aluno:
        resultado["Status"]   = "Pasta do aluno não encontrada"
        resultado["Faltando"] = SLOTS_ATIVOS[:]
        return resultado

    arquivos = [
        entry for entry in pasta_aluno.iterdir()
        if entry.is_file() and entry.suffix.lower() in EXTENSOES_ACEITAS
    ]
    if not arquivos:
        resultado["Status"]   = "Sem arquivos na pasta"
        resultado["Faltando"] = SLOTS_ATIVOS[:]
        return resultado

    mapeamento: dict[str, Path | None] = {}
    disponiveis = list(arquivos)

    for slot in SLOTS_ATIVOS:
        encontrado = None
        sinonimos_slot = SINONIMOS.get(slot, [norm(slot)])
        for arq in disponiveis:
            arq_norm = norm(arq.stem)
            for sinonimo in sinonimos_slot:
                s = norm(sinonimo) if isinstance(sinonimo, str) else sinonimo
                if (len(s.split()) == 1 and re.search(r'(?<![A-Z0-9])' + re.escape(s) + r'(?![A-Z0-9])', arq_norm)
                        or (len(s.split()) > 1 and s in arq_norm)):
                    encontrado = arq
                    break
            if encontrado:
                break
        mapeamento[slot] = encontrado
        if encontrado:
            grupo = next((g for g in SLOTS_COMPARTILHAM_ARQUIVO if slot in g), None)
            if grupo is None:
                disponiveis.remove(encontrado)

    for grupo in SLOTS_COMPARTILHAM_ARQUIVO:
        slots_grupo = [s for s in SLOTS_ATIVOS if s in grupo]
        arq_grupo   = next((mapeamento[s] for s in slots_grupo if mapeamento.get(s)), None)
        if arq_grupo:
            for slot in slots_grupo:
                if not mapeamento.get(slot):
                    mapeamento[slot] = arq_grupo

    disponiveis_para_upload: dict[str, Path] = {}
    faltando: list[str] = []

    for slot, arquivo in mapeamento.items():
        if arquivo is None:
            faltando.append(slot)
            continue
        if slots_reprocessar is not None and slot not in slots_reprocessar:
            continue
        pular, motivo = deve_pular_slot(indice_docs, cgm, slot)
        if pular:
            print(f"     ⏭️  '{slot}' pulado — {motivo}")
            continue
        disponiveis_para_upload[slot] = arquivo

    resultado["Faltando"] = faltando

    if not disponiveis_para_upload:
        resultado["Status"] = "Todos os slots já cobertos"
        return resultado

    print(f"     📂 Arquivos para upload: {len(disponiveis_para_upload)}/{len(SLOTS_ATIVOS)}")

    ok = await navegar_pasta_virtual(page, cgm)
    if not ok:
        resultado["Status"] = "Falha ao abrir pasta virtual"
        return resultado

    hash_upload, assinatura_existente = await obter_slots_api(page, cgm)

    slots_com_erro: list[str] = []

    for slot, arquivo in disponiveis_para_upload.items():
        print(f"\n     ▶ Slot: {slot}")

        idtipo = slot_para_idtipo(slot) or ""

        if idtipo in assinatura_existente:
            hash_doc = await excluir_slot_e_obter_hash(
                page, cgm, slot, idtipo, assinatura_existente[idtipo]
            )
        else:
            hash_doc = hash_upload.get(idtipo)

        if not hash_doc:
            print(f"     ❌ Hash não encontrado para '{slot}'")
            resultado["Documentos"][slot] = {
                "Arquivo": arquivo.name, "Status": "Hash não encontrado",
                "Data_Anexo": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            }
            slots_com_erro.append(slot)
            if slot not in resultado["Faltando"]:
                resultado["Faltando"].append(slot)
            continue

        sucesso, msg = await injetar_e_enviar(page, hash_doc, arquivo)
        resultado["Documentos"][slot] = {
            "Arquivo": arquivo.name, "Status": msg,
            "Data_Anexo": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        }
        status_txt = "✅" if sucesso else "❌"
        print(f"     {status_txt} {slot}: {msg}")

        if not sucesso:
            slots_com_erro.append(slot)
            if slot not in resultado["Faltando"]:
                resultado["Faltando"].append(slot)

    if slots_com_erro:
        resultado["Status"]     = "Erro"
        resultado["Slots_Erro"] = slots_com_erro
    elif faltando:
        resultado["Status"] = "Incompleto"
    else:
        resultado["Status"] = "Completo"

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(1_000)
    return resultado


async def modo_aluno(modo_teste: bool, modo_erros: bool, modo_faltando: bool, cgms=None) -> None:
    """
    Modo --aluno: processa apenas os CGMs configurados (ver
    src.comum.configuracao.cgm_upload — antes era o array CGM_UPLOAD editado
    manualmente no topo do script; ver decisão do usuário em 29/08/2026).
    """
    if _pasta_digitalizacao_ou_avisar() is None:
        return

    # `cgms` (vindo da tela ou da linha de comando) tem prioridade; sem ele, usa a lista configurada.
    cgm_alvo_lista = list(cgms) if cgms else _cgm_upload_configurado()
    if not cgm_alvo_lista:
        print("❌ Nenhum CGM configurado para o modo --aluno.")
        print("   Configure a lista de CGMs (ver src/comum/configuracao.py) antes de rodar com --aluno.")
        sys.exit(1)

    turmas = carregar_turmas()
    cgms_alvo = {str(c).strip() for c in cgm_alvo_lista}

    lista_alunos = [
        (nome_turma, aluno)
        for nome_turma, alunos in turmas.items()
        for aluno in alunos
        if str(aluno.get("CGM", "")).strip() in cgms_alvo
    ]

    cgms_encontrados = {str(a.get("CGM", "")) for _, a in lista_alunos}
    cgms_nao_encontrados = cgms_alvo - cgms_encontrados
    if cgms_nao_encontrados:
        print(f"⚠️  CGMs não encontrados no turmas.json: {sorted(cgms_nao_encontrados)}")

    if not lista_alunos:
        print("❌ Nenhum aluno encontrado para os CGMs informados.")
        sys.exit(1)

    indice_docs = carregar_documentos_alunos()
    slots_por_cgm: dict[str, set[str]] | None = None

    if modo_faltando:
        slots_por_cgm = {}
        for cgm in cgms_encontrados:
            faltando = {
                slot for slot in SLOTS_ATIVOS
                if not deve_pular_slot(indice_docs, cgm, slot)[0]
            }
            if faltando:
                slots_por_cgm[cgm] = faltando
        lista_alunos = [
            (t, a) for t, a in lista_alunos
            if str(a.get("CGM", "")) in slots_por_cgm
        ]
        print(f"📋 MODO --faltando: {len(lista_alunos)} aluno(s) com slots pendentes")

    if modo_erros:
        path_erro = _DADOS / "anexo_documento_sere_erro_EXC.json"
        if not path_erro.exists():
            path_erro = _DADOS / "anexo_documento_sere_erro.json"
        if not path_erro.exists():
            print(f"❌ Arquivo de erros não encontrado. Execute sem --erros primeiro.")
            sys.exit(1)
        with open(path_erro, encoding="utf-8") as f:
            dados_erro = json.load(f)
        cgms_com_erro = {str(a.get("CGM", "")) for a in dados_erro.get("Alunos", [])}
        lista_alunos  = [(t, a) for t, a in lista_alunos if str(a.get("CGM", "")) in cgms_com_erro]
        slots_por_cgm = {
            str(a.get("CGM", "")): set(SLOTS_ATIVOS)
            for a in dados_erro.get("Alunos", [])
        }
        print(f"⚠️  MODO --erros: {len(lista_alunos)} aluno(s) a reprocessar")

    if modo_teste:
        lista_alunos = lista_alunos[:1]
        print("⚠️  MODO TESTE — processando apenas 1 aluno\n")

    cache_pastas = {
        nome_turma: encontrar_pasta_turma(nome_turma)
        for nome_turma, _ in lista_alunos
    }

    print(f"\n{'='*65}")
    print(f"  UPLOAD EXCLUSIVO — SERE {ANO_BASE}")
    print(f"{'='*65}")
    print(f"  📋 CGMs alvo   : {sorted(cgms_alvo)}")
    print(f"  👥 Encontrados : {len(lista_alunos)} aluno(s)")
    print(f"  📌 Slots ativos: {', '.join(SLOTS_ATIVOS)}")
    if modo_faltando:
        print("  🔍 MODO --faltando : SIM")
    if modo_erros:
        print("  ⚠️  MODO --erros   : SIM")
    if modo_teste:
        print("  🧪 MODO TESTE      : SIM (1 aluno)")
    print(f"{'='*65}\n")

    resultados: list[dict] = []
    com_erro:   list[dict] = []

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True)
        page    = await browser.new_page()
        await page.goto(URL)

        print("🔐 Fazendo login…")
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        print("✅ Login efetuado.\n")

        await navegar_por_aluno(page)

        total = len(lista_alunos)
        for idx, (nome_turma, aluno) in enumerate(lista_alunos, 1):
            cgm_aluno  = str(aluno.get("CGM", ""))
            nome_aluno = aluno.get("Nome", "SemNome")
            print(f"\n{'─'*65}")
            print(f"  [{idx:02d}/{total}] Processando…")

            slots_reprocessar = slots_por_cgm.get(cgm_aluno) if slots_por_cgm else None

            try:
                pasta_turma = cache_pastas.get(nome_turma)
                res = await processar_aluno_upload(
                    page, aluno, nome_turma, pasta_turma,
                    indice_docs, slots_reprocessar=slots_reprocessar,
                )
                resultados.append(res)
                status = res["Status"]
                if "Ignorado" not in status and "Pulado" not in status \
                        and status not in ("Completo", "Incompleto", "Todos os slots já cobertos"):
                    com_erro.append(res)
            except Exception as exc:
                msg = str(exc)
                print(f"     ❌ Erro inesperado: {msg}")
                res = {
                    "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                    "Status": "Erro", "Slots_Erro": [f"Exceção: {msg}"],
                    "Documentos": {}, "Faltando": SLOTS_ATIVOS[:],
                    "Data_Processamento": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                }
                resultados.append(res)
                com_erro.append(res)

            try:
                voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                if voltar:
                    await voltar.click()
                else:
                    await page.go_back()
                await page.wait_for_timeout(1_500)
            except Exception as e:
                log.warning(f"Erro ao voltar: {e}")

        await browser.close()

    sufixo     = "_TESTE_EXC" if modo_teste else "_EXC"
    path_saida = _DADOS / f"anexo_documento_sere_erro{sufixo}.json"
    if path_saida.exists():
        path_saida.unlink()
    with open(path_saida, "w", encoding="utf-8") as f:
        json.dump({
            "Total": len(com_erro),
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "CGMs_Alvo": sorted(cgms_alvo),
            "Alunos": com_erro,
        }, f, ensure_ascii=False, indent=4)

    total_ok = sum(1 for r in resultados if r.get("Status") in ("Completo", "Incompleto"))
    print(f"\n{'='*65}")
    print(f"  ✅ UPLOAD EXCLUSIVO FINALIZADO")
    print(f"     Processados : {len(resultados)}")
    print(f"     OK          : {total_ok}")
    print(f"     Erros       : {len(com_erro)}")
    if com_erro:
        print(f"  ❌ Erros     : {path_saida}")
    print(f"{'='*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# MODO --transferidos
# ─────────────────────────────────────────────────────────────────────────────

def _carregar_transferidos() -> dict:
    """
    Carrega transferidos.json e retorna o dicionário CGM → dados.
    Aborta com mensagem amigável se o arquivo não existir.
    """
    if not PATH_TRANSFERIDOS.exists():
        # Não existe ainda: cria a partir do turmas.json (só quem foi transferido; ver fila_transferidos.py).
        from src.automacao.fila_transferidos import garantir_transferidos_json
        try:
            garantir_transferidos_json(PATH_TRANSFERIDOS.parent)
        except FileNotFoundError as exc:
            print(f"❌ {exc}")
    if not PATH_TRANSFERIDOS.exists():
        print(f"❌ Arquivo não encontrado: {PATH_TRANSFERIDOS}")
        print("   Carregue as turmas (gera o turmas.json) e execute este modo de novo.")
        sys.exit(1)
    with open(PATH_TRANSFERIDOS, encoding="utf-8") as f:
        return json.load(f)


def decidir_envio_slot(ja_no_sere: bool, nome_no_sere: Optional[str], registro_doc: dict,
                       arquivo: Path) -> tuple[str, str]:
    """
    Decide o que fazer com UM slot da pasta virtual do SERE. Retorna ("enviar"|"substituir"|"pular", motivo).

    O slot pode já conter um documento de transferência de OUTRA escola. Só se pula quando o que está lá é
    comprovadamente o nosso: já enviamos antes (anexado_em, gravado só após um envio), o nome do arquivo no
    SERE é o que o SERE nos devolveu naquele envio (nome_no_sere) ou, na falta dele, o nome do arquivo local,
    e o arquivo local não foi alterado depois do envio. Qualquer outra coisa no slot é substituída.
    """
    if not ja_no_sere:
        return "enviar", "Slot vazio no SERE — enviando."
    anexado = None
    try:
        anexado = datetime.fromisoformat(str(registro_doc.get("anexado_em") or ""))
    except ValueError:
        pass
    if anexado is None:
        return "substituir", (f"Slot ocupado por '{nome_no_sere or 'arquivo desconhecido'}', que esta escola não enviou "
                              f"(outra origem) — substituindo pelo documento desta escola.")
    esperado = norm(Path(str(registro_doc.get("nome_no_sere") or arquivo.name)).stem)
    if norm(Path(str(nome_no_sere or "")).stem) != esperado:
        return "substituir", (f"Slot ocupado por outro arquivo ('{nome_no_sere}'), diferente do que esta escola enviou "
                              f"— substituindo.")
    try:
        if datetime.fromtimestamp(arquivo.stat().st_mtime) > anexado:
            return "substituir", "O arquivo local foi alterado depois do envio — substituindo no SERE."
    except OSError:
        pass
    return "pular", "Documento desta escola já está no SERE — não sobrescreve."


def _salvar_transferidos(dados: dict) -> None:
    """Persiste o dicionário de transferidos de volta no JSON."""
    try:
        with open(PATH_TRANSFERIDOS, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        log.warning(f"Erro ao salvar transferidos.json: {exc}")


def _data_apos_corte(valor_iso: str | None) -> bool:
    """
    Retorna True se o valor ISO 8601 representa uma data POSTERIOR à DATA_CORTE.
    None ou inválido → False.
    """
    if not valor_iso:
        return False
    try:
        dt = datetime.fromisoformat(valor_iso)
        return dt > _corte_transferidos()
    except (ValueError, TypeError):
        return False


def _localizar_arquivo_transferido(
    pasta_raiz: Path,
    nome_turma: str,
    nome_aluno: str,
    cgm: str,
) -> Path | None:
    """
    Localiza o PDF de um transferido dentro de pasta_raiz.

    Busca tolerante: varre subpastas que casem com nome_turma e procura
    um PDF cujo nome contenha o nome do aluno ou o CGM.
    Aceita prefixos numéricos (ex.: '02-ANNA BEATRIZ…').
    """
    if not pasta_raiz.exists():
        return None

    nome_aluno_norm = norm(nome_aluno)
    cgm_str         = str(cgm)

    turma_norm = norm(nome_turma)
    turma_base = turma_norm.replace("INTEGRAL ", "").replace(" A", "").replace(" B", "").strip()

    candidatos_pasta: list[Path] = []
    for sub in pasta_raiz.iterdir():
        if not sub.is_dir():
            continue
        sub_norm = norm(sub.name)
        if (turma_norm in sub_norm or sub_norm in turma_norm
                or turma_base in sub_norm or sub_norm in turma_base):
            candidatos_pasta.append(sub)

    if not candidatos_pasta:
        candidatos_pasta = [s for s in pasta_raiz.iterdir() if s.is_dir()]

    for pasta in candidatos_pasta:
        for arq in pasta.iterdir():
            if arq.suffix.lower() not in EXTENSOES_ACEITAS:
                continue
            stem_norm = norm(arq.stem)
            stem_limpo = re.sub(r'^[\d\s\-]+', '', stem_norm).strip()
            stem_limpo = re.sub(r'^HISTORICO\s*[-–]\s*', '', stem_limpo).strip()

            if (nome_aluno_norm in stem_limpo
                    or stem_limpo in nome_aluno_norm
                    or cgm_str in stem_norm):
                return arq

    return None


async def modo_transferidos(modo_teste: bool = False, tipos: tuple[str, ...] | None = None,
                            simulacao: bool = False) -> None:
    """
    Modo --transferidos:
      Para cada aluno em transferidos.json cujo documento foi gerado/digitalizado
      APÓS a DATA_CORTE, faz upload do PDF correspondente no slot
      correto da pasta virtual do SERE.

      Documentos tratados:
        - Guia de Transferência  (idtipo 10) → campo guia.anexado_em
        - Histórico Escolar      (idtipo  9) → campo historico.anexado_em
        - Parecer Descritivo     (idtipo 38) → campo parecer.anexado_em

      Skip duplo: se o SERE já tem o slot E o JSON já tem anexado_em → pula.
      Após upload bem-sucedido: grava anexado_em no transferidos.json.
      Erros não interrompem — vai para a próxima tarefa.

    `tipos`: restringe aos tipos pedidos ("guia", "historico", "parecer"); None = os três.
    `simulacao`: faz só a varredura de pastas e mostra o que seria enviado — não abre o SERE e não grava.

    Pastas: dados/<ano>/TRANSFERENCIAS/{GUIA DE TRANSFERENCIA, HISTORICO, PARECERES} (ver
    src.comum.pastas_transferencias). Se o arquivo não está lá, procura também nas pastas antigas dentro
    da pasta de digitalização (TRANSFERENCIAS/HISTÓRICOS etc.), para não perder o que já estava guardado.
    """
    from src.comum import pastas_transferencias as _pastas_t

    slots = {k: v for k, v in TRANSFERIDOS_SLOTS.items() if tipos is None or k in tipos}
    if not slots:
        print(f"⚠️  Nenhum tipo válido em {tipos}. Válidos: {', '.join(TRANSFERIDOS_SLOTS)}.")
        return

    nome_pasta_do_slot = {"guia": _pastas_t.GUIA, "historico": _pastas_t.HISTORICO, "parecer": _pastas_t.PARECERES}
    dir_dig = pasta_digitalizacao() if pasta_digitalizacao_configurada() else None
    for tipo_doc, cfg in slots.items():
        nome_pasta = nome_pasta_do_slot[tipo_doc]
        cfg["dir"]     = _pastas_t.subpasta(nome_pasta, PATH_TRANSFERIDOS.parent)
        cfg["dirs_antigos"] = _pastas_t.pastas_antigas(nome_pasta, dir_dig)
    if not simulacao:
        _pastas_t.garantir_pastas(PATH_TRANSFERIDOS.parent)

    # ── Carrega transferidos ─────────────────────────────────────────────────
    dados = _carregar_transferidos()

    # ── PRÉ-VARREDURA: monta tarefas apenas onde o arquivo existe no disco ───
    # Só considera documentos com data_campo após o corte E com arquivo físico.
    tarefas: list[tuple[str, str, str, str, dict, Path]] = []
    sem_arquivo: list[tuple[str, str, str, str]] = []

    print(f"\n🔍 Varrendo pastas em busca de arquivos disponíveis…")
    for cgm, info in dados.items():
        nome  = info.get("nome", "SemNome")
        turma = info.get("turma", "")

        for tipo_doc, cfg in slots.items():
            bloco      = info.get(cfg["campo_json"], {})
            data_campo = bloco.get(cfg["campo_data"])

            if not _data_apos_corte(data_campo):
                continue  # documento anterior ao corte — ignora

            arquivo = None
            for pasta_raiz in [cfg["dir"], *cfg.get("dirs_antigos", [])]:
                arquivo = _localizar_arquivo_transferido(pasta_raiz, turma, nome, cgm)
                if arquivo:
                    break
            if arquivo:
                tarefas.append((cgm, nome, turma, tipo_doc, cfg, arquivo))
            else:
                sem_arquivo.append((cgm, nome, turma, tipo_doc))

    if sem_arquivo:
        print(f"  ⚠️  {len(sem_arquivo)} tarefa(s) sem arquivo no disco (serão ignoradas):")
        for cgm, nome, turma, tipo_doc in sem_arquivo:
            print(f"       • {nome} ({cgm}) — {tipo_doc} / {turma}")

    if not tarefas:
        print(
            f"\n⚠️  Nenhum arquivo encontrado após "
            f"{_corte_transferidos().strftime('%d/%m/%Y')}. "
            f"Verifique as pastas de transferência."
        )
        return

    if modo_teste:
        tarefas = tarefas[:1]
        print("⚠️  MODO TESTE — processando apenas 1 tarefa\n")

    if simulacao:
        print(f"\n{'='*65}\n  🧪 SIMULAÇÃO — nada será enviado ao SERE nem gravado\n{'='*65}")
        print(f"  Data de corte : {_corte_transferidos().strftime('%d/%m/%Y')}")
        print(f"  Seriam enviados {len(tarefas)} arquivo(s):")
        for cgm, nome, turma, tipo_doc, cfg, arquivo in tarefas:
            print(f"     • {cfg['nome_slot']:<32} {nome} (CGM {cgm}, {turma})  ←  {arquivo}")
        print(f"{'='*65}\n")
        return

    print(f"\n{'='*65}")
    print(f"  UPLOAD TRANSFERIDOS — SERE {ANO_BASE}")
    print(f"  Data de corte  : {_corte_transferidos().strftime('%d/%m/%Y')}")
    print(f"  Tarefas c/ arq : {len(tarefas)}")
    print(f"  Sem arquivo    : {len(sem_arquivo)}")
    if modo_teste:
        print(f"  🧪 MODO TESTE  : SIM")
    print(f"{'='*65}\n")

    resultados: list[dict] = []

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True)
        page    = await browser.new_page()
        await page.goto(URL)

        print("🔐 Fazendo login…")
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        print("✅ Login efetuado.\n")

        await navegar_por_aluno(page)

        total = len(tarefas)
        for idx, (cgm, nome, turma, tipo_doc, cfg, arquivo) in enumerate(tarefas, 1):
            idtipo     = cfg["idtipo"]
            nome_slot  = cfg["nome_slot"]
            campo_json = cfg["campo_json"]

            print(f"\n{'─'*65}")
            print(f"  [{idx:02d}/{total}] {nome}  (CGM: {cgm})")
            print(f"           Turma   : {turma}")
            print(f"           Tipo    : {nome_slot}  [idtipo={idtipo}]")
            print(f"           Arquivo : {arquivo.name}")

            try:
                ok = await navegar_pasta_virtual(page, cgm)
                if not ok:
                    msg = "Falha ao abrir pasta virtual"
                    print(f"     ❌ {msg}")
                    resultados.append({
                        "CGM": cgm, "Nome": nome, "Turma": turma,
                        "Tipo": tipo_doc, "Slot": nome_slot,
                        "Status": "Erro", "Mensagem": msg,
                    })
                    continue

                hash_upload, assinatura_existente = await obter_slots_api(page, cgm)

                # ── Skip duplo: SERE já tem o slot E JSON já registra anexado_em ──
                ja_no_sere = idtipo in assinatura_existente
                nome_no_sere = (await obter_nomes_slots_api(page, cgm)).get(idtipo) if ja_no_sere else None
                decisao_envio, motivo_envio = decidir_envio_slot(
                    ja_no_sere, nome_no_sere, dados.get(cgm, {}).get(campo_json, {}), arquivo)
                if ja_no_sere:
                    print(f"     ℹ️  {motivo_envio}")
                if decisao_envio == "pular":
                    print(f"     ⏭️  Já anexado no SERE e registrado no JSON — pulando")
                    resultados.append({
                        "CGM": cgm, "Nome": nome, "Turma": turma,
                        "Tipo": tipo_doc, "Slot": nome_slot,
                        "Arquivo": arquivo.name,
                        "Status": "Pulado", "Mensagem": "Já anexado (SERE + JSON)",
                    })
                    # Fecha modal caso esteja aberto
                    try:
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass
                    # Navega de volta antes de continuar
                    try:
                        voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                        if voltar:
                            await voltar.click()
                        else:
                            await page.go_back()
                        await page.wait_for_timeout(1_500)
                    except Exception as e:
                        log.warning(f"Erro ao voltar após skip: {e}")
                    continue

                # ── Obtém hash para upload (excluindo slot antigo se existir) ──
                if ja_no_sere:
                    hash_doc = await excluir_slot_e_obter_hash(
                        page, cgm, nome_slot, idtipo,
                        assinatura_existente[idtipo]
                    )
                else:
                    hash_doc = hash_upload.get(idtipo)

                if not hash_doc:
                    msg = f"Hash não encontrado para [{idtipo}] {nome_slot}"
                    print(f"     ❌ {msg}")
                    resultados.append({
                        "CGM": cgm, "Nome": nome, "Turma": turma,
                        "Tipo": tipo_doc, "Slot": nome_slot,
                        "Status": "Erro", "Mensagem": msg,
                    })
                else:
                    sucesso, msg = await injetar_e_enviar(page, hash_doc, arquivo)
                    icone = "✅" if sucesso else "❌"
                    print(f"     {icone} {nome_slot}: {msg}")

                    agora = datetime.now().isoformat(timespec="seconds")
                    resultados.append({
                        "CGM": cgm, "Nome": nome, "Turma": turma,
                        "Tipo": tipo_doc, "Slot": nome_slot,
                        "Arquivo": arquivo.name,
                        "Status": "OK" if sucesso else "Erro",
                        "Mensagem": msg,
                        "Anexado_em": agora if sucesso else None,
                    })

                    # ── Grava anexado_em no transferidos.json após sucesso ────
                    if sucesso:
                        try:
                            try:                  # como o SERE chama o arquivo agora: base para reconhecer o nosso depois
                                nome_final = (await obter_nomes_slots_api(page, cgm)).get(idtipo)
                                if nome_final:
                                    dados[cgm][campo_json]["nome_no_sere"] = nome_final
                            except Exception as exc_nome:
                                log.warning(f"Não foi possível ler o nome do arquivo no SERE: {exc_nome}")
                            dados[cgm][campo_json]["anexado_em"] = agora
                            _salvar_transferidos(dados)
                            print(f"     💾 transferidos.json atualizado — {campo_json}.anexado_em = {agora}")
                        except Exception as exc_save:
                            log.warning(f"Erro ao salvar transferidos.json: {exc_save}")

            except Exception as exc:
                msg = str(exc)
                print(f"     ❌ Erro inesperado: {msg}")
                resultados.append({
                    "CGM": cgm, "Nome": nome, "Turma": turma,
                    "Tipo": tipo_doc, "Slot": nome_slot,
                    "Status": "Erro", "Mensagem": msg,
                })

            try:
                voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                if voltar:
                    await voltar.click()
                else:
                    await page.go_back()
                await page.wait_for_timeout(1_500)
            except Exception as e:
                log.warning(f"Erro ao voltar: {e}")

        await browser.close()

    sufixo     = "_TESTE" if modo_teste else ""
    # Antes: Path(f"upload_transferidos{sufixo}.json") — caminho relativo
    # simples, gravava no diretório de onde o comando era executado.
    # Padronizado para usar _DADOS, como todos os outros modos (decisão do
    # usuário, 29/08/2026).
    path_saida = _DADOS / f"upload_transferidos{sufixo}.json"
    ok_count      = sum(1 for r in resultados if r.get("Status") == "OK")
    pulado_count  = sum(1 for r in resultados if r.get("Status") == "Pulado")
    erro_count    = sum(1 for r in resultados if r.get("Status") == "Erro")

    with open(path_saida, "w", encoding="utf-8") as f:
        json.dump({
            "Data_Corte": _corte_transferidos().strftime("%d/%m/%Y"),
            "Total": len(resultados),
            "OK": ok_count,
            "Pulados": pulado_count,
            "Erros": erro_count,
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "Tarefas": resultados,
        }, f, ensure_ascii=False, indent=4)

    print(f"\n{'='*65}")
    print(f"  ✅ UPLOAD TRANSFERIDOS FINALIZADO")
    print(f"     Data de corte : {_corte_transferidos().strftime('%d/%m/%Y')}")
    print(f"     OK            : {ok_count}")
    print(f"     Pulados       : {pulado_count}")
    print(f"     Erros         : {erro_count}")
    print(f"  📄 Resultado      : {path_saida}")
    print(f"{'='*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# MODO --validar
# ─────────────────────────────────────────────────────────────────────────────

class EncerramentoForcado(Exception):
    """
    Levantada quando o modo --validar detecta falhas de recarga/navegação
    consecutivos demais falhando (MAX_RECARGAS_CONSECUTIVAS_FALHA). Propaga
    até modo_validar, que encerra o modo por completo (não só o aluno atual)
    e relança para main() sinalizar código de saída != 0.
    """
    pass


def _carregar_cgms_com_pendencia(path_documentos_alunos: Path) -> set[str]:
    """
    Lê `documentos-alunos.json` e retorna o conjunto de CGMs (como string)
    de alunos que possuem PELO MENOS UM documento com "validado": false em
    "Detalhes". Usado para filtrar a fila do modo --validar: um aluno só
    entra na fila se aparecer neste conjunto — alunos com todos os
    documentos já validados (ou sem nenhum documento cadastrado) não são
    incluídos.
    """
    try:
        with open(path_documentos_alunos, encoding="utf-8") as f:
            dados = json.load(f)
    except FileNotFoundError:
        log.error(f"_carregar_cgms_com_pendencia: arquivo não encontrado: "
                  f"{path_documentos_alunos}")
        print(f"❌ Arquivo não encontrado: {path_documentos_alunos}")
        sys.exit(1)
    except (json.JSONDecodeError, OSError) as exc:
        log.error(f"_carregar_cgms_com_pendencia: erro ao ler "
                  f"{path_documentos_alunos}: {exc}")
        print(f"❌ Erro ao ler {path_documentos_alunos}: {exc}")
        sys.exit(1)

    cgms: set[str] = set()
    for registro in dados:
        cgm = str(registro.get("CGM", "")).strip()
        if not cgm:
            continue
        detalhes = registro.get("Detalhes", [])
        tem_pendente = any(not d.get("validado", False) for d in detalhes)
        if tem_pendente:
            cgms.add(cgm)
    return cgms


async def revalidar_navegacao(page, cgm: str) -> bool:
    """
    Reseta o estado do SERE entre cada validação, SEMPRE pelo caminho
    oficial da aplicação: MENU → Consulta Padrão → Por Aluno → CGM.

    Não usa F5/reload nem page.goto(page.url) — ambos causavam queda
    de sessão (F5 reenvia o último POST e dispara o diálogo nativo do
    navegador; goto(page.url) é uma navegação "crua" que o SERE não espera).
    Navegar pelo menu como um usuário faria é o único caminho que se mostrou
    estável para trocar de tela sem derrubar a sessão.

    Se a sessão tiver caído/expirado (tela de login detectada), o modo
    --validar NÃO tenta reconectar nem refazer login e NÃO repete
    tentativas: levanta EncerramentoForcado para encerrar o script
    imediatamente.
    """
    if await esta_na_tela_login(page):
        log.error(f"revalidar_navegacao: sessão do SERE expirou/login perdido "
                  f"| CGM={cgm} — encerrando imediatamente (sem reconectar).")
        raise EncerramentoForcado(
            f"Sessão do SERE expirou ou login foi perdido (CGM={cgm}). "
            f"Encerrando imediatamente, sem tentar reconectar ou relogar."
        )
    try:
        await navegar_por_aluno(page)
        return await navegar_pasta_virtual(page, cgm)
    except Exception as exc:
        log.warning(f"revalidar_navegacao: erro ao renavegar CGM={cgm}: {exc}")
        return False


async def voltar_para_menu_por_aluno(page) -> bool:
    """
    Ao finalizar a validação de TODOS os documentos de um aluno, volta para
    a tela 'Consulta Padrão → Por Aluno' SOMENTE pela navegação nativa da
    interface do SERE (clique no menu), para pesquisar o CGM do próximo
    aluno — usado entre alunos no modo --validar.

    Fluxo obrigatório e único (sem exceções, sem fallback):
        MENU → CONSULTA PADRÃO → POR ALUNO

    Reaproveita navegar_por_aluno(), que já implementa exatamente esse
    clique. Não usa page.goto/page.go_back/browser.back/history.back, não
    recarrega a URL, não refaz login e não tem qualquer navegação
    completa/fallback — é sempre este único caminho, do jeito que um
    usuário humano clicaria.

    Retorna True se a tela 'Por Aluno' (#cgm) ficou pronta para a próxima
    busca, False caso contrário.
    """
    try:
        await navegar_por_aluno(page)
        await page.wait_for_selector("#cgm", timeout=15_000)
        return True
    except Exception as exc:
        log.warning(f"voltar_para_menu_por_aluno: navegação MENU → CONSULTA PADRÃO → "
                    f"POR ALUNO falhou: {exc}")
        return False


async def validar_aluno(
    page, aluno: dict, nome_turma: str, delay_segundos: int, estado_falhas: dict,
    somente_transferidos: bool = False,
) -> tuple[dict, list[dict]]:
    """
    Valida (clica no ícone ✔ 'Validar') todos os documentos pendentes de um
    aluno, um por vez, aguardando e recarregando a página entre cada clique.

    `estado_falhas` é um dict compartilhado com modo_validar contendo a chave
    'consecutivas': o MESMO contador de falhas consecutivas é incrementado
    aqui (falha ao recarregar/confirmar) e em modo_validar (falha ao abrir
    pasta virtual / exceção inesperada), para que os dois pontos de falha do
    fluxo não "dobrem" a tolerância contando separadamente o mesmo problema
    de sessão caída no SERE.

    CORREÇÃO DE BUG (aprovada pelo usuário em 30/08/2026): no original,
    todo incremento/reset deste contador usava vírgula sobrando
    ("+= 1," / "= 0,"), fazendo estado_falhas["consecutivas"] virar uma
    TUPLA em vez de inteiro. Diferente do bug equivalente em remover_slot
    (que só produzia uma MENSAGEM errada), aqui o valor é comparado com
    ">= MAX_RECARGAS_CONSECUTIVAS_FALHA" (um inteiro) — tupla >= inteiro
    levanta TypeError em Python, confirmado por teste. Ou seja, o script
    original quebrava com uma exceção não tratada na primeira falha de
    recarga durante --validar, em vez de logar o aviso ou (no limite)
    encerrar de forma controlada via EncerramentoForcado. Todas as 8
    ocorrências (aqui e em modo_validar) foram corrigidas para inteiro
    comum — nenhuma outra regra de negócio (quando conta como falha,
    quando encerra) foi alterada.

    Por padrão (`somente_transferidos=False`), alunos Transferidos são
    ignorados — comportamento histórico do modo --validar. Quando
    `somente_transferidos=True` (flag --transferidos combinada com
    --validar), a lógica se inverte: SÓ os alunos Transferidos são
    processados, e os demais são ignorados. Isso permite validar
    especificamente os documentos (Guia, Histórico, Parecer) enviados pelo
    modo --transferidos.
    """
    cgm      = str(aluno["CGM"])
    nome     = aluno.get("Nome", "SemNome")
    situacao = aluno.get("Situação", "")

    log.info(f"{'─'*50}")
    log.info(f"Validando: '{nome}' | CGM={cgm} | Turma='{nome_turma}'")
    print(f"  🔎 {nome}  (CGM: {cgm}  |  Turma: {nome_turma})")

    resultado = {
        "CGM": cgm, "Nome": nome, "Turma": nome_turma,
        "Status": "Não processado", "Validados": [], "Falhas": [],
    }

    eh_transferido = "TRANSFER" in norm(situacao)
    if somente_transferidos and not eh_transferido:
        resultado["Status"] = f"Ignorado (não é transferido — situação: {situacao})"
        print(f"     ⏭️  Ignorado (não é transferido): situação '{situacao}'")
        return resultado, []
    if not somente_transferidos and eh_transferido:
        resultado["Status"] = f"Ignorado (situação: {situacao})"
        print(f"     ⏭️  Ignorado: situação '{situacao}'")
        return resultado, []

    ok = await navegar_pasta_virtual(page, cgm)
    if not ok:
        resultado["Status"] = "Falha ao abrir pasta virtual"
        return resultado, []

    documentos = await buscar_documentos_api(page, cgm)
    pendentes_inicial = [
        d for d in documentos
        if d.get("nomearquivo", "").strip() and not _parse_validado(d.get("tag"))
    ]
    print(f"     📊 Slots com arquivo: "
          f"{sum(1 for d in documentos if d.get('nomearquivo','').strip())} | "
          f"{len(pendentes_inicial)} a validar")

    if not pendentes_inicial:
        resultado["Status"] = "Nenhum documento para validar"
        return resultado, documentos

    for tentativa in range(1, MAX_TENTATIVAS_VALIDACAO + 1):
        docs_atuais = await buscar_documentos_api(page, cgm)
        pendentes = [
            d for d in docs_atuais
            if d.get("nomearquivo", "").strip() and not _parse_validado(d.get("tag"))
        ]
        if not pendentes:
            break

        doc          = pendentes[0]
        assinatura   = doc.get("assinaturaArquivo", "")
        nome_arquivo = doc.get("nomearquivo", "")
        slot         = doc.get("tipodocumento", "")

        print(f"     ✔️  Validando: {slot} — {nome_arquivo}")

        try:
            # Nota: o diálogo de confirmação (se houver) já é tratado pelo
            # handler global page.on("dialog", ...) registrado em
            # modo_validar — não registrar outro aqui (page.once) para não
            # ter dois handlers disputando o mesmo diálogo, o que gera
            # "Dialog.accept: Cannot accept dialog which is already handled!".
            await page.evaluate(f"validarDocumento('{assinatura}')")
        except Exception as exc:
            log.warning(f"Erro ao clicar em validar (assin={assinatura[:8]}…): {exc}")
            resultado["Falhas"].append({"Slot": slot, "Motivo": f"Erro ao clicar: {exc}"})
            continue

        print(f"       ⏳ Aguardando {delay_segundos}s e recarregando a página…")
        await page.wait_for_timeout(delay_segundos * 1_000)

        recarregou = await revalidar_navegacao(page, cgm)
        if not recarregou:
            estado_falhas["consecutivas"] += 1  # corrigido: era "+= 1," (tupla) no original
            resultado["Falhas"].append({
                "Slot": slot, "Motivo": "Falha ao recarregar/reabrir pasta virtual",
            })
            print(f"       ⚠️  Falha ao recarregar "
                  f"({estado_falhas['consecutivas']}/{MAX_RECARGAS_CONSECUTIVAS_FALHA})")
            if estado_falhas["consecutivas"] >= MAX_RECARGAS_CONSECUTIVAS_FALHA:
                raise EncerramentoForcado(
                    f"Página falhou ao recarregar {estado_falhas['consecutivas']}x seguidas "
                    f"(CGM={cgm}, aluno='{nome}'). SERE provavelmente travou ou a "
                    f"sessão caiu."
                )
            continue

        docs_conf = await buscar_documentos_api(page, cgm)
        doc_atual = next(
            (d for d in docs_conf if d.get("assinaturaArquivo") == assinatura), None
        )
        if doc_atual and _parse_validado(doc_atual.get("tag")):
            resultado["Validados"].append(slot)
            estado_falhas["consecutivas"] = 0  # corrigido: era "= 0," (tupla) no original
            print("       ✅ Validado com sucesso")
        else:
            estado_falhas["consecutivas"] += 1  # corrigido: era "+= 1," (tupla) no original
            resultado["Falhas"].append({
                "Slot": slot, "Motivo": "Não confirmado como validado após reload",
            })
            print(f"       ⚠️  Não confirmado "
                  f"({estado_falhas['consecutivas']}/{MAX_RECARGAS_CONSECUTIVAS_FALHA}) — tentando novamente")
            if estado_falhas["consecutivas"] >= MAX_RECARGAS_CONSECUTIVAS_FALHA:
                raise EncerramentoForcado(
                    f"{estado_falhas['consecutivas']}x seguidas sem confirmar validação após "
                    f"reload (CGM={cgm}, aluno='{nome}'). SERE provavelmente travou."
                )

    docs_finais = await buscar_documentos_api(page, cgm)
    ainda_pendentes = [
        d.get("tipodocumento", "") for d in docs_finais
        if d.get("nomearquivo", "").strip() and not _parse_validado(d.get("tag"))
    ]

    if not ainda_pendentes:
        resultado["Status"] = "Todos validados"
    elif resultado["Validados"]:
        resultado["Status"] = "Parcial — alguns documentos não foram validados"
    else:
        resultado["Status"] = "Falhou — nenhum documento validado"

    return resultado, docs_finais


async def modo_validar(
    modo_teste: bool,
    turmas_selecionadas: list[str],
    turmas: dict,
    delay_segundos: int = DELAY_VALIDACAO_PADRAO,
    somente_transferidos: bool = False,
) -> None:
    """
    Modo --validar: valida todos os documentos pendentes de todos os alunos.

    Com `somente_transferidos=True` (flag --transferidos combinada com
    --validar), processa SOMENTE os alunos com situação Transferido — útil
    para validar Guia, Histórico e Parecer logo após rodar --transferidos
    sozinho (upload). Por padrão, alunos Transferidos continuam sendo
    ignorados, como sempre foi.
    """
    lista_alunos: list[tuple[str, dict]] = [
        (nome_turma, aluno)
        for nome_turma in turmas_selecionadas
        for aluno in turmas[nome_turma]
    ]

    if somente_transferidos:
        total_antes_situacao = len(lista_alunos)
        lista_alunos = [
            (nome_turma, aluno) for (nome_turma, aluno) in lista_alunos
            if "TRANSFER" in norm(aluno.get("Situação", aluno.get("Situacao", "")))
        ]
        print(f"🎯 --validar --transferidos: {len(lista_alunos)} de "
              f"{total_antes_situacao} aluno(s) são transferidos.")

    # ── Filtro pela fila: usa documentos-alunos.json para incluir na fila
    # SOMENTE alunos com pelo menos um documento ainda não validado. Alunos
    # com todos os documentos já validados são ignorados (não entram na
    # fila), reduzindo automaticamente o tamanho dela.
    cgms_pendentes = set(_carregar_cgms_com_pendencia(PATH_DOCUMENTOS_ALUNOS))
    total_antes = len(lista_alunos)
    lista_alunos = [
        (nome_turma, aluno) for (nome_turma, aluno) in lista_alunos
        if str(aluno.get("CGM", "")) in cgms_pendentes
    ]
    ignorados_completos = total_antes - len(lista_alunos)
    print(f"📄 Fila filtrada por {PATH_DOCUMENTOS_ALUNOS}: "
          f"{len(lista_alunos)} aluno(s) com pendência "
          f"({ignorados_completos} já com todos os documentos validados — ignorado(s)).")
    log.info(f"Fila filtrada: {len(lista_alunos)} com pendência, "
             f"{ignorados_completos} ignorados (já completos).")

    if modo_teste:
        lista_alunos = lista_alunos[:1]
        print("⚠️  MODO TESTE — processando apenas 1 aluno\n")

    print(f"\n{'='*65}")
    print(f"  VALIDAÇÃO DE DOCUMENTOS — SERE {ANO_BASE}")
    print(f"  Valida (clica em ✔) todos os documentos pendentes")
    print(f"{'='*65}")
    print(f"  📋 Turmas            : {len(turmas_selecionadas)}")
    print(f"  👥 Alunos            : {len(lista_alunos)}")
    print(f"  ⏳ Espera entre docs : {delay_segundos}s (recarregando a página)")
    print(f"  🎯 Apenas transferidos : {'SIM' if somente_transferidos else 'NÃO (transferidos são ignorados)'}")
    if modo_teste:
        print("  🧪 MODO TESTE        : SIM (1 aluno)")
    print(f"{'='*65}\n")

    resultados: list[dict] = []
    completos:  list[dict] = []
    com_falha:  list[dict] = []
    docs_restantes_por_cgm: dict[str, list[dict]] = {}
    encerramento_forcado: EncerramentoForcado | None = None
    # Contador ÚNICO e compartilhado com validar_aluno — evita que a mesma
    # sessão-caída-no-SERE seja contada duas vezes em dois lugares diferentes
    # (uma "vida" só de MAX_RECARGAS_CONSECUTIVAS_FALHA para todo o modo).
    estado_falhas = {"consecutivas": 0}

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True)
        page    = await browser.new_page()

        # Proteção extra: aceita automaticamente qualquer diálogo nativo do
        # navegador (ex.: "esta página usou informações inseridas... quer
        # continuar?" ao recarregar após um POST). Sem isso o diálogo trava
        # a página esperando confirmação e todo wait_for_selector estoura
        # em timeout. Fica registrado durante TODO o modo --validar.
        # Único handler de dialog do fluxo (não registrar page.once em
        # paralelo) — try/except defensivo contra corrida caso o diálogo já
        # tenha sido tratado por algum outro motivo.
        async def _aceitar_dialog(dialog):
            try:
                await dialog.accept()
            except Exception as exc:
                log.warning(f"Dialog já tratado ou erro ao aceitar: {exc}")

        page.on("dialog", lambda d: asyncio.ensure_future(_aceitar_dialog(d)))

        try:
            await page.goto(URL)

            print("🔐 Fazendo login…")
            await page.fill("#CHAVE", LOGIN)
            await page.fill("#CHAVE_ENCRIPT", SENHA)
            await page.click("//input[@value='Entrar']")
            await page.wait_for_timeout(3_000)
            print("✅ Login efetuado.\n")

            await navegar_por_aluno(page)

            total = len(lista_alunos)
            for idx, (nome_turma, aluno) in enumerate(lista_alunos, 1):
                cgm_aluno  = str(aluno.get("CGM", ""))
                nome_aluno = aluno.get("Nome", "SemNome")
                print(f"\n{'─'*65}")
                print(f"  [{idx:02d}/{total}] Processando…")

                try:
                    res, docs_api = await validar_aluno(
                        page, aluno, nome_turma, delay_segundos, estado_falhas,
                        somente_transferidos=somente_transferidos,
                    )
                    resultados.append(res)
                    docs_restantes_por_cgm[cgm_aluno] = docs_api

                    if res["Status"] in ("Todos validados", "Nenhum documento para validar"):
                        completos.append(res)
                        estado_falhas["consecutivas"] = 0  # corrigido: era "= 0," (tupla) no original
                    elif "Ignorado" in res["Status"]:
                        pass  # ignorado (ex.: transferido) não conta como falha sistêmica
                    else:
                        com_falha.append(res)
                        # "Falha ao abrir pasta virtual" (timeout em #cgm) é o mesmo
                        # sinal de sessão/página caída que EncerramentoForcado detecta
                        # dentro de validar_aluno — por isso usa o contador compartilhado.
                        estado_falhas["consecutivas"] += 1  # corrigido: era "+= 1," (tupla) no original
                        print(f"     ⚠️  Falha consecutiva "
                              f"({estado_falhas['consecutivas']}/{MAX_RECARGAS_CONSECUTIVAS_FALHA})")
                        if estado_falhas["consecutivas"] >= MAX_RECARGAS_CONSECUTIVAS_FALHA:
                            encerramento_forcado = EncerramentoForcado(
                                f"{estado_falhas['consecutivas']}x seguidas com falha ao "
                                f"processar aluno (último: CGM={cgm_aluno}, "
                                f"aluno='{nome_aluno}', status='{res['Status']}'). "
                                f"SERE provavelmente travou ou a sessão caiu."
                            )
                            log.error(f"[{idx}/{total}] ENCERRAMENTO FORÇADO: {encerramento_forcado}")
                            print(f"\n{'!'*65}")
                            print(f"  🛑 ENCERRANDO — falhas consecutivas em excesso")
                            print(f"     {encerramento_forcado}")
                            print(f"{'!'*65}\n")
                            break

                    # ── Fim do processamento deste aluno (0, 1 ou vários
                    # documentos validados) — volta para "Consulta Padrão →
                    # Por Aluno" usando SOMENTE a navegação da interface do
                    # SERE, para que o próximo aluno comece sempre do mesmo
                    # lugar. Nada de goto/go_back/login automático aqui.
                    print("  Finalizada validação do aluno.")
                    print("  Navegando:")
                    print("    MENU")
                    print("    → CONSULTA PADRÃO")
                    print("    → POR ALUNO")
                    log.info(f"[{idx}/{total}] Finalizada validação do aluno "
                              f"CGM={cgm_aluno}. Navegando: MENU → CONSULTA PADRÃO → POR ALUNO")

                    ok_voltou = await voltar_para_menu_por_aluno(page)
                    if not ok_voltou:
                        log.warning(f"[{idx}/{total}] Falha ao navegar MENU → CONSULTA "
                                    f"PADRÃO → POR ALUNO — tentando mais uma vez")
                        ok_voltou = await voltar_para_menu_por_aluno(page)

                    if ok_voltou:
                        print("  Tela \"Consulta Padrão -> Por Aluno\" carregada.")
                        print("  Processando próximo aluno.")
                        log.info(f"[{idx}/{total}] Tela 'Consulta Padrão -> Por Aluno' "
                                  f"carregada. Processando próximo aluno.")
                    else:
                        log.warning(f"[{idx}/{total}] Segunda tentativa de navegação "
                                    f"MENU → CONSULTA PADRÃO → POR ALUNO também falhou.")
                        estado_falhas["consecutivas"] += 1  # corrigido: era "+= 1," (tupla) no original
                        print(f"     ⚠️  Falha consecutiva "
                              f"({estado_falhas['consecutivas']}/{MAX_RECARGAS_CONSECUTIVAS_FALHA})")
                        if estado_falhas["consecutivas"] >= MAX_RECARGAS_CONSECUTIVAS_FALHA:
                            encerramento_forcado = EncerramentoForcado(
                                f"{estado_falhas['consecutivas']}x seguidas com falha ao "
                                f"navegar MENU → CONSULTA PADRÃO → POR ALUNO (último: "
                                f"CGM={cgm_aluno}, aluno='{nome_aluno}'). SERE provavelmente "
                                f"travou ou a sessão caiu."
                            )
                            log.error(f"[{idx}/{total}] ENCERRAMENTO FORÇADO: {encerramento_forcado}")
                            print(f"\n{'!'*65}")
                            print(f"  🛑 ENCERRANDO — falhas consecutivas em excesso")
                            print(f"     {encerramento_forcado}")
                            print(f"{'!'*65}\n")
                            break

                except EncerramentoForcado as exc:
                    # Página recarregando e falhando demais em sequência —
                    # aborta o modo --validar por completo (não só este aluno).
                    log.error(f"[{idx}/{total}] ENCERRAMENTO FORÇADO: {exc}")
                    print(f"\n{'!'*65}")
                    print(f"  🛑 ENCERRANDO — recarregamentos falhando em excesso")
                    print(f"     {exc}")
                    print(f"{'!'*65}\n")
                    res = {
                        "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                        "Status": f"Abortado: {exc}", "Validados": [], "Falhas": [],
                    }
                    resultados.append(res)
                    com_falha.append(res)
                    encerramento_forcado = exc
                    break

                except Exception as exc:
                    msg = str(exc)
                    log.exception(f"[{idx}/{total}] Erro inesperado: '{nome_aluno}': {msg}")
                    print(f"     ❌ Erro inesperado: {msg}")
                    res = {
                        "CGM": cgm_aluno, "Nome": nome_aluno, "Turma": nome_turma,
                        "Status": f"Erro: {msg}", "Validados": [], "Falhas": [],
                    }
                    resultados.append(res)
                    com_falha.append(res)

                    estado_falhas["consecutivas"] += 1  # corrigido: era "+= 1," (tupla) no original
                    print(f"     ⚠️  Falha consecutiva "
                          f"({estado_falhas['consecutivas']}/{MAX_RECARGAS_CONSECUTIVAS_FALHA})")
                    if estado_falhas["consecutivas"] >= MAX_RECARGAS_CONSECUTIVAS_FALHA:
                        encerramento_forcado = EncerramentoForcado(
                            f"{estado_falhas['consecutivas']}x seguidas com erro inesperado "
                            f"(último: CGM={cgm_aluno}, aluno='{nome_aluno}', erro='{msg}'). "
                            f"SERE provavelmente travou ou a sessão caiu."
                        )
                        log.error(f"[{idx}/{total}] ENCERRAMENTO FORÇADO: {encerramento_forcado}")
                        print(f"\n{'!'*65}")
                        print(f"  🛑 ENCERRANDO — falhas consecutivas em excesso")
                        print(f"     {encerramento_forcado}")
                        print(f"{'!'*65}\n")
                        break

                    # Erro inesperado, mas ainda dentro da tolerância — tenta
                    # voltar para "Por Aluno" pela navegação normal antes de
                    # seguir para o próximo aluno (mesmo fluxo de sempre).
                    print("  Finalizada validação do aluno (com erro).")
                    print("  Navegando:")
                    print("    MENU")
                    print("    → CONSULTA PADRÃO")
                    print("    → POR ALUNO")
                    ok_voltou = await voltar_para_menu_por_aluno(page)
                    if not ok_voltou:
                        ok_voltou = await voltar_para_menu_por_aluno(page)
                    if ok_voltou:
                        print("  Tela \"Consulta Padrão -> Por Aluno\" carregada.")
                        print("  Processando próximo aluno.")
                    else:
                        log.warning(f"[{idx}/{total}] Navegação de recuperação também falhou "
                                    f"após erro inesperado.")
        finally:
            await browser.close()

    print("\n📄 Atualizando documentos-alunos.json com estado pós-validação…")
    atualizar_documentos_alunos_via_api(docs_restantes_por_cgm)

    sufixo     = "_TESTE" if modo_teste else ""
    sufixo    += "_ABORTADO" if encerramento_forcado else ""
    # Antes: Path(f"validacao-documentos_...-{ANO_BASE}{sufixo}.json") —
    # caminho relativo simples, gravava no diretório de onde o comando era
    # executado (mesma inconsistência já corrigida em modo_transferidos).
    # Padronizado para usar _DADOS, como todos os outros modos (decisão do
    # usuário, 30/08/2026).
    path_ok    = _DADOS / f"validacao-documentos_concluidos-{ANO_BASE}{sufixo}.json"
    path_falha = _DADOS / f"validacao-documentos_falhas-{ANO_BASE}{sufixo}.json"
    for p in (path_ok, path_falha):
        if p.exists():
            p.unlink()

    with open(path_ok, "w", encoding="utf-8") as f:
        json.dump({
            "Total": len(completos), "Turmas": turmas_selecionadas,
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "Alunos": completos,
        }, f, ensure_ascii=False, indent=4)
    with open(path_falha, "w", encoding="utf-8") as f:
        json.dump({
            "Total": len(com_falha), "Turmas": turmas_selecionadas,
            "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "Alunos": com_falha,
        }, f, ensure_ascii=False, indent=4)

    if encerramento_forcado:
        print(f"\n{'='*65}")
        print(f"  🛑 VALIDAÇÃO ABORTADA — recarregamentos falhando em excesso")
        print(f"     Motivo     : {encerramento_forcado}")
        print(f"     Processados até aqui:")
        print(f"     Concluídos : {len(completos)}")
        print(f"     Com falha  : {len(com_falha)}")
        print(f"     Total      : {len(resultados)} / {len(lista_alunos)}")
        print(f"  📄 OK          : {path_ok}")
        print(f"  ⚠️  Falhas      : {path_falha}")
        print(f"  💾 Docs JSON   : {PATH_DOCUMENTOS_ALUNOS}")
        print(f"{'='*65}\n")
        # Propaga para o main() encerrar o script com código de saída != 0.
        raise encerramento_forcado

    print(f"\n{'='*65}")
    print(f"  ✅ VALIDAÇÃO FINALIZADA{' (TESTE)' if modo_teste else ''}")
    print(f"     Concluídos : {len(completos)}")
    print(f"     Com falha  : {len(com_falha)}")
    print(f"     Total      : {len(resultados)}")
    print(f"  📄 OK          : {path_ok}")
    print(f"  ⚠️  Falhas      : {path_falha}")
    print(f"  💾 Docs JSON   : {PATH_DOCUMENTOS_ALUNOS}")
    print(f"{'='*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# LINHA DE COMANDO
# ─────────────────────────────────────────────────────────────────────────────

# Modo da linha de comando → chave no registro (src.comum.registro_scripts): de lá vêm o aviso de
# confirmação e a decisão "pede confirmação ou não", para a CLI e a tela nunca divergirem.
_CHAVE_DO_MODO = {
    "limpeza": "limpeza", "documento": "documentos", "espec": "espec",
    "aluno": "aluno", "transferidos": "transferidos", "validar": "validar",
}


class _PedidoInvalido(Exception):
    """Pedido que não dá para atender (flag faltando, turma inexistente...). Vira mensagem + código 2."""


class _Cancelado(Exception):
    """O usuário saiu de um menu interativo. Nada foi executado (código 2)."""


def _montar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m src.automacao.sere_2026",
        description="SERE — gestão de documentos dos alunos. Escolha UM modo; --analisa repassa o resto dos "
                    "argumentos ao relatório (src.relatorios.analisa_arquivos_sere).",
    )
    modos = ap.add_argument_group("modos (um por execução)")
    modos.add_argument("--limpeza", action="store_true", help="remove TODOS os arquivos dos alunos selecionados")
    modos.add_argument("--documento", nargs="?", const="", default=None, metavar="ID",
                       help="remove um tipo de documento de todos (sem ID: menu)")
    modos.add_argument("--analisa", action="store_true", help="coleta os documentos via API e gera o relatório")
    modos.add_argument("--espec", nargs="?", const="", default=None, metavar="ID",
                       help="envia um tipo de documento para todos (sem ID: menu)")
    modos.add_argument("--aluno", action="store_true", help="envia os documentos só dos CGMs de --cgm / configurados")
    modos.add_argument("--transferidos", action="store_true",
                       help="sozinho: envia os PDFs de transferidos.json. Com outro modo: só inclui alunos transferidos")
    modos.add_argument("--validar", action="store_true", help="valida os documentos pendentes")

    op = ap.add_argument_group("opções")
    op.add_argument("--teste", action="store_true", help="processa só o primeiro aluno (de verdade, não é simulação)")
    op.add_argument("--turma", nargs="*", default=None, metavar="NOME",
                    help="turma(s): nome, ano ('5º Ano') ou início ('5'). Sem valor: menu de uma turma")
    op.add_argument("--turmas", nargs="*", default=None, metavar="NOME",
                    help="como --turma; sem valor abre o menu de seleção múltipla")
    op.add_argument("--matriculados", action="store_true", help="inclui os alunos matriculados (padrão)")
    op.add_argument("--cgm", nargs="+", default=None, metavar="CGM", help="só estes CGMs (aceita '123,456;789')")
    op.add_argument("--erros", action="store_true", help="--aluno: reprocessa só os que falharam")
    op.add_argument("--faltando", action="store_true", help="--aluno: só quem ainda tem slot pendente")
    op.add_argument("--delay", type=int, default=DELAY_VALIDACAO_PADRAO, metavar="SEGUNDOS",
                    help=f"--validar: espera entre alunos (padrão {DELAY_VALIDACAO_PADRAO})")
    op.add_argument("--simular", action="store_true", help="mostra o que seria processado, sem executar")
    op.add_argument("--confirmo", action="store_true", help="confirma sem perguntar (para agendador de tarefas)")
    return ap


def _escolher_modo(ns: argparse.Namespace) -> str:
    modos = [nome for nome, ativo in (
        ("limpeza", ns.limpeza), ("documento", ns.documento is not None), ("espec", ns.espec is not None),
        ("aluno", ns.aluno), ("validar", ns.validar)) if ativo]
    if not modos and ns.transferidos:
        modos = ["transferidos"]              # --transferidos sozinho = modo de upload; combinado, é só filtro de situação
    if len(modos) != 1:
        raise _PedidoInvalido(
            "Escolha exatamente um modo: --limpeza, --documento, --analisa, --espec, --aluno, --transferidos ou --validar."
            if not modos else "Escolha só um modo por execução (vieram: " + ", ".join("--" + m for m in modos) + ").")
    return modos[0]


def _escolher_turmas(ns: argparse.Namespace, turmas: dict) -> tuple[list[str], dict, bool, bool]:
    """(turmas a processar, turmas.json filtrado pela situação, matriculados?, transferidos?)."""
    from src.comum import opcoes_execucao as oe
    valores = [*(ns.turma or []), *(ns.turmas or [])]
    if ns.turma is None and ns.turmas is None:
        selecionadas = list(turmas)                                  # sem --turma: todas, como sempre foi
    elif valores:
        try:
            selecionadas = oe.resolver_turmas(valores, list(turmas))
        except ValueError as exc:
            raise _PedidoInvalido(str(exc)) from exc
    elif ns.turmas is not None:
        selecionadas = menu_selecionar_multiplas_turmas(turmas)
    else:
        unica = menu_selecionar_turma(turmas)
        selecionadas = [unica] if unica else []
    if not selecionadas:
        raise _Cancelado()
    transferidos = bool(ns.transferidos)
    matriculados = bool(ns.matriculados) or not transferidos        # sem nenhuma das duas flags = só matriculados
    return selecionadas, oe.filtrar_turmas_por_situacao(turmas, matriculados=matriculados, transferidos=transferidos), \
        matriculados, transferidos


def _escolher_tipo_documento(valor: str) -> tuple[str, str]:
    if not valor:
        escolhido = menu_selecionar_tipo_documento()
        if escolhido is None:
            raise _Cancelado()
        return escolhido
    if valor not in IDTIPO_PARA_SLOT:
        raise _PedidoInvalido(f"Tipo de documento desconhecido: {valor}. Rode o modo sem o ID para ver o menu.")
    return valor, IDTIPO_PARA_SLOT[valor]


def _cgms_do_pedido(ns: argparse.Namespace) -> tuple[str, ...]:
    if not ns.cgm:
        return ()
    from src.comum.opcoes_execucao import analisar_cgms
    r = analisar_cgms(" ".join(ns.cgm))
    if r.invalidos:
        raise _PedidoInvalido("CGM com formato inválido: " + ", ".join(r.invalidos))
    return tuple(r.validos)


def _planejar(modo: str, ns: argparse.Namespace) -> tuple:
    """(função, kwargs, prévia) do modo pedido — as mesmas chamadas que a tela faz pelo registro."""
    from src.comum import opcoes_execucao as oe
    if modo == "transferidos":
        return modo_transferidos, {"modo_teste": ns.teste}, "Alunos de transferidos.json."
    if modo == "aluno":
        cgms = _cgms_do_pedido(ns)
        previa = f"{len(cgms)} CGM(s) informado(s)." if cgms else "CGMs da lista configurada."
        return modo_aluno, {"modo_teste": ns.teste, "modo_erros": ns.erros, "modo_faltando": ns.faltando,
                            "cgms": list(cgms)}, previa

    try:
        turmas = carregar_turmas()
    except (OSError, ValueError) as exc:
        raise _PedidoInvalido("Ainda não existe turmas.json: execute primeiro  python -m src.comum.cli turmas") from exc
    if not turmas:
        raise _PedidoInvalido("turmas.json está vazio: execute primeiro  python -m src.comum.cli turmas")
    selecionadas, filtradas, matr, transf = _escolher_turmas(ns, turmas)
    sel = oe.selecionar_alunos(turmas, turmas=selecionadas, matriculados=matr, transferidos=transf)
    previa = oe.descrever_selecao(sel)
    base = {"modo_teste": ns.teste, "turmas_selecionadas": selecionadas, "turmas": filtradas}

    if modo == "limpeza":
        return modo_limpeza, base, previa
    if modo == "validar":
        if ns.delay < 0:
            raise _PedidoInvalido("--delay não pode ser negativo.")
        return modo_validar, {**base, "delay_segundos": ns.delay, "somente_transferidos": transf and not matr}, previa
    idtipo, nome = _escolher_tipo_documento(ns.documento if modo == "documento" else ns.espec)
    if modo == "documento":
        return modo_documento, {"idtipo": idtipo, "nome_slot": nome, **base}, f"{previa} Tipo: [{idtipo}] {nome}."
    return modo_espec, {"idtipo_alvo": idtipo, "nome_slot": nome, **base}, f"{previa} Tipo: [{idtipo}] {nome}."


def _saida(exc: SystemExit) -> int:
    return exc.code if isinstance(exc.code, int) else (0 if exc.code in (None, "") else 1)


def main(argv: list[str] | None = None) -> int:
    """
    Executa um modo pela linha de comando. Códigos de saída: 0 = concluído · 1 = falhou ·
    2 = pedido inválido ou não confirmado · 130 = interrompido (Ctrl+C).
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    # --analisa repassa TODOS os outros argumentos ao relatório (que tem as suas próprias --turma, --erros...).
    if "--analisa" in argv:
        try:
            modo_analisa([a for a in argv if a != "--analisa"])
            return 0
        except SystemExit as exc:
            return _saida(exc)
        except KeyboardInterrupt:
            print("\nInterrompido.", file=sys.stderr)
            return 130

    try:
        ns = _montar_parser().parse_args(argv)
    except SystemExit as exc:                # --help (0) ou argumento desconhecido (2)
        return _saida(exc)

    try:
        modo = _escolher_modo(ns)
        funcao, kwargs, previa = _planejar(modo, ns)
    except _PedidoInvalido as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except _Cancelado:
        print("Cancelado: nada foi executado.", file=sys.stderr)
        return 2

    from src.comum import cli, registro_scripts as reg
    script = reg.obter(_CHAVE_DO_MODO[modo])
    print(f"Modo:   --{modo}")
    print(f"Prévia: {previa}")
    if ns.simular:
        print(f"Executaria: {funcao.__name__}({cli._resumo_kwargs(kwargs)})")
        print("(simulação: nada foi executado)")
        return 0
    if script is not None and script.confirmar and not ns.teste and not cli._confirmar(script, previa, ns):
        print("Cancelado: nada foi executado.", file=sys.stderr)
        return 2

    try:
        asyncio.run(funcao(**kwargs))
        return 0
    except EncerramentoForcado as exc:
        print(f"ERRO: execução abortada — {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:                # os modos usam sys.exit(1) quando falta pasta/configuração
        return _saida(exc)
    except KeyboardInterrupt:
        print("\nInterrompido.", file=sys.stderr)
        return 130
    except Exception as exc:                 # noqa: BLE001 — qualquer falha vira mensagem + código 1
        print(f"ERRO: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

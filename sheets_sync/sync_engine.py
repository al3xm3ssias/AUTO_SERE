# =============================================================================
#  sync_engine.py — Motor de sincronização JSON ↔ Google Sheets
# =============================================================================

import logging
from typing import Dict, List, Tuple

from qrcode import base

from config import (
    COL,
    DATA_START_ROW,
    HEADER_ROW,
    SITUACAO_MAP,
    STATUS_MATRICULADO,
    STATUS_TRANSFERIDO,
    TOTAL_COLS,
    SEXO_FEMININO,
    SEXO_MASCULINO,
    SEXO_MAP,

)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Helpers de linha
# ---------------------------------------------------------------------------

def _normalizar_linha(linha: List, tamanho: int = TOTAL_COLS) -> List:
    """Garante que a linha tem exatamente `tamanho` colunas."""
    linha = list(linha)
    if len(linha) < tamanho:
        linha.extend([""] * (tamanho - len(linha)))
    return linha[:tamanho]


def _montar_linha_aluno(aluno: dict, linha_existente: List = None) -> List:
    """
    Constrói a lista de valores para uma linha da planilha a partir de um aluno do JSON.

    Colunas ignoradas (CPF, SUS, Idade, Escola de Origem) preservam o valor
    existente na planilha quando houver, ou ficam vazias em novos registros.
    """
    base = _normalizar_linha(linha_existente or [])
    situacao = aluno.get("Situação", "")
    status   = SITUACAO_MAP.get(situacao, STATUS_MATRICULADO)
    is_transf = status == STATUS_TRANSFERIDO

    base[COL["numero"]]    = aluno.get("N", "")
    # COL["cpf"]           — preservado (não existe no JSON)
    base[COL["cgm"]]       = str(aluno.get("CGM", "")).strip()
    # COL["sus"]           — preservado (ignorado)
    base[COL["nome"]]      = aluno.get("Nome", "")
    base[COL["data_nasc"]] = aluno.get("Data Nasc.", "")
    base[COL["idade"]]     = aluno.get("Idade", "")     
    SEXO_MAP = {"Masculino": SEXO_MASCULINO, "Feminino": SEXO_FEMININO}
    base[COL["sexo"]] = "" if is_transf else SEXO_MAP.get(aluno.get("Sexo", ""), aluno.get("Sexo", "")) 
    base[COL["status"]]    = status
    base[COL["data_matricula"]]     = "" if is_transf else aluno.get("Data Matricula", "")
    # COL["escola_origem"] — preservado (ignorado)
    base[COL["data_transferencia"]] = aluno.get("Data Matricula", "") if is_transf else ""

    return base


def _linhas_sao_iguais(nova: List, existente: List) -> bool:
    """Compara apenas as colunas gerenciadas pelo script (ignora as preservadas)."""
    colunas_gerenciadas = [
        COL["numero"], COL["cgm"], COL["nome"], COL["data_nasc"],
        COL["sexo"], COL["status"], COL["data_matricula"], COL["data_transferencia"],
    ]
    nova      = _normalizar_linha(nova)
    existente = _normalizar_linha(existente)
    return all(str(nova[c]) == str(existente[c]) for c in colunas_gerenciadas)


# ---------------------------------------------------------------------------
#  Funções de range
# ---------------------------------------------------------------------------

def _range_linha(nome_aba: str, numero_linha: int) -> str:
    """Retorna o range A1-notation para uma linha inteira (ex: 'Turma X'!A3:L3)."""
    ultima_col = chr(ord("A") + TOTAL_COLS - 1)   # 'L' para 12 colunas
    return f"'{nome_aba}'!A{numero_linha}:{ultima_col}{numero_linha}"


# ---------------------------------------------------------------------------
#  Motor principal por aba
# ---------------------------------------------------------------------------

def sincronizar_aba(
    sheets,
    nome_aba: str,
    alunos_json: List[dict],
) -> Tuple[int, int, int]:
    """
    Sincroniza uma aba do Google Sheets com a lista de alunos do JSON.

    Retorna (adicionados, atualizados, transferidos).
    """
    from sheets_client import adicionar_linhas, ler_aba, escrever_lote

    # --- 1. Ler planilha atual -------------------------------------------------
    dados_planilha = ler_aba(sheets, nome_aba)

    # Ignorar linha de cabeçalho (índice 0 = linha 1 da planilha)
    linhas_dados = dados_planilha[HEADER_ROW:]   # lista de listas, pode estar vazia

    # Montar índice da planilha: CGM → (índice_na_lista, linha_planilha)
    # índice_na_lista começa em 0 = DATA_START_ROW na planilha
    cgm_para_idx: Dict[str, int] = {}
    for i, linha in enumerate(linhas_dados):
        linha_norm = _normalizar_linha(linha)
        cgm = str(linha_norm[COL["cgm"]]).strip()
        if cgm:
            cgm_para_idx[cgm] = i

    # --- 2. Processar alunos do JSON ------------------------------------------
    atualizacoes: List[dict] = []   # batch de updates para linhas existentes
    novas_linhas: List[List] = []   # linhas a anexar no final
    adicionados  = 0
    atualizados  = 0
    transferidos = 0

    for aluno in alunos_json:
        cgm = str(aluno.get("CGM", "")).strip()
        if not cgm:
            logger.warning("  ⚠  Aluno sem CGM ignorado: %s", aluno.get("Nome"))
            continue

        nova_linha = _montar_linha_aluno(aluno)
        situacao   = aluno.get("Situação", "")
        is_transf  = SITUACAO_MAP.get(situacao) == STATUS_TRANSFERIDO

        if cgm in cgm_para_idx:
            # Aluno já existe — verificar se algo mudou
            idx = cgm_para_idx[cgm]
            linha_existente = _normalizar_linha(linhas_dados[idx])
            nova_linha_completa = _montar_linha_aluno(aluno, linha_existente)

            if _linhas_sao_iguais(nova_linha_completa, linha_existente):
                continue  # nada mudou, pula sem consumir quota

            numero_linha_planilha = DATA_START_ROW + idx
            atualizacoes.append({
                "range":  _range_linha(nome_aba, numero_linha_planilha),
                "values": [nova_linha_completa],
            })

            if is_transf:
                transferidos += 1
                logger.info(
                    "  🔄 TRANSFERIDO  | %-40s | CGM: %s | Data: %s",
                    aluno.get("Nome"), cgm, aluno.get("Data Matricula"),
                )
            else:
                atualizados += 1
                logger.info(
                    "  ✏  ATUALIZADO   | %-40s | CGM: %s",
                    aluno.get("Nome"), cgm,
                )

        else:
            # Aluno novo — preparar para append
            novas_linhas.append(nova_linha)
            adicionados += 1

            if is_transf:
                transferidos += 1
                logger.info(
                    "  ➕ ADICIONADO (TRANSF) | %-40s | CGM: %s",
                    aluno.get("Nome"), cgm,
                )
            else:
                logger.info(
                    "  ➕ ADICIONADO   | %-40s | CGM: %s",
                    aluno.get("Nome"), cgm,
                )

    # --- 3. Enviar atualizações em lote ---------------------------------------
    if atualizacoes:
        celulas = escrever_lote(sheets, atualizacoes)
        logger.debug("  → %d célula(s) atualizada(s) em lote.", celulas)

    if novas_linhas:
        linhas_inseridas = adicionar_linhas(sheets, nome_aba, novas_linhas)
        logger.debug("  → %d nova(s) linha(s) inserida(s).", linhas_inseridas)

    return adicionados, atualizados, transferidos
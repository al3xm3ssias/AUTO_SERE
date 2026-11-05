#!/usr/bin/env python3
# =============================================================================
#  main.py — Ponto de entrada do sincronizador turmas.json ↔ Google Sheets
# =============================================================================
#
#  Uso:
#      python main.py                     # usa turmas.json no diretório atual
#      python main.py --json outro.json   # arquivo alternativo
#      python main.py --turma "1º Ano Integral A"  # sincroniza só uma turma
#      python main.py --dry-run           # simula sem escrever na planilha
#
# =============================================================================

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Dict

from config import TURMAS_JSON_PATH
from sheets_client import criar_servico, listar_abas
from sync_engine import sincronizar_aba
from turmas_reader import carregar_turmas


# Logo após os imports, antes de main()
ABA_MAP: Dict[str, str] = {
    "INFANTIL 4 Integral A": "INFANTIL IV",
    "INFANTIL 5 Integral A": "INFANTIL V",
    "1º Ano Integral A":     "1º ANO",
    "2º Ano Integral A":     "2º ANO",
    "3º Ano Integral A":     "3º ANO A",
    "3º Ano Integral B":     "3º ANO B",
    "4º Ano Integral A":     "4º ANO",
    "5º Ano Integral A":     "5º ANO",
}


# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------

def _configurar_logging(verbose: bool = False) -> None:
    nivel = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    data  = datetime.now().strftime("%Y%m%d")

    logging.basicConfig(
        level=nivel,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"sync_{data}.log", encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincroniza turmas.json com o Google Sheets."
    )
    parser.add_argument(
        "--json", dest="json_path", default=TURMAS_JSON_PATH,
        help="Caminho para o arquivo turmas.json (padrão: turmas.json)",
    )
    parser.add_argument(
        "--turma", dest="turma", default=None,
        help="Sincronizar apenas esta turma (nome exato da aba).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simula a sincronização sem escrever na planilha.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Ativa logs detalhados (DEBUG).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
#  Entrada principal
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _configurar_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    inicio = time.monotonic()
    logger.info("=" * 60)
    logger.info("  SINCRONIZADOR DE TURMAS — início: %s", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    if args.dry_run:
        logger.info("  ⚠  MODO DRY-RUN ativado — nenhuma alteração será gravada.")
    logger.info("=" * 60)

    # --- 1. Carregar JSON ------------------------------------------------------
    try:
        turmas = carregar_turmas(args.json_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Erro ao carregar turmas.json: %s", e)
        sys.exit(1)

    # --- 2. Conectar ao Google Sheets ------------------------------------------
    try:
        sheets = criar_servico()
    except Exception as e:
        logger.error("Falha na autenticação com o Google: %s", e)
        sys.exit(1)

    # --- 3. Validar abas existentes na planilha --------------------------------
    try:
        abas_planilha = listar_abas(sheets)
    except Exception as e:
        logger.error("Não foi possível listar as abas: %s", e)
        sys.exit(1)

    logger.info("Abas encontradas na planilha: %s", abas_planilha)

    # --- 4. Determinar quais turmas sincronizar --------------------------------
    if args.turma:
        turmas_para_sync = {args.turma: turmas.get(args.turma, [])}
        if not turmas.get(args.turma):
            logger.warning("Turma '%s' não encontrada no JSON.", args.turma)
    else:
        turmas_para_sync = turmas

    # --- 5. Sincronizar turma por turma ----------------------------------------
    total_adicionados  = 0
    total_atualizados  = 0
    total_transferidos = 0
    erros: list        = []

    for nome_turma, alunos in turmas_para_sync.items():
        logger.info("")
        logger.info("─── Turma: %s (%d aluno(s)) ───", nome_turma, len(alunos))
       
        nome_aba = ABA_MAP.get(nome_turma, nome_turma)
        if nome_aba not in abas_planilha:
            logger.warning(
                "  ⚠  Aba '%s' não existe na planilha — turma ignorada.", nome_turma
            )
            erros.append(f"Aba não encontrada: '{nome_turma}'")
            continue


        if args.dry_run:
            logger.info("  [DRY-RUN] Pulando escrita para '%s'.", nome_turma)
            continue

        try:
            add, upd, trf = sincronizar_aba(sheets, nome_aba, alunos)
            total_adicionados  += add
            total_atualizados  += upd
            total_transferidos += trf
        except Exception as e:
            logger.error("  ❌ Erro ao sincronizar '%s': %s", nome_aba, e)
            erros.append(f"Erro em '{nome_aba}': {e}")

    # --- 6. Resumo final -------------------------------------------------------
    duracao = time.monotonic() - inicio
    logger.info("")
    logger.info("=" * 60)
    logger.info("  RESUMO FINAL")
    logger.info("  ➕ Adicionados  : %d", total_adicionados)
    logger.info("  ✏  Atualizados  : %d", total_atualizados)
    logger.info("  🔄 Transferidos : %d", total_transferidos)
    if erros:
        logger.info("  ❌ Erros        : %d", len(erros))
        for err in erros:
            logger.warning("       %s", err)
    logger.info("  ⏱  Duração      : %.1fs", duracao)
    logger.info("=" * 60)

    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
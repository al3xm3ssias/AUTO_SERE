#!/usr/bin/env python3
# =============================================================================
#  extrair_sus.py — Extrai Cartão SUS da planilha Google Sheets → JSON
# =============================================================================
#
#  Lê todas as abas da planilha, coleta o CGM (col E) e o Cartão SUS (col D)
#  de cada aluno a partir da linha 11, e gera:
#
#      ~/compartilhado/ARQUIVOS/ESCOLA JUDITH/PYTHON/SERE/2026/sus_alunos.json
#
#  Uso:
#      python extrair_sus.py                        # extrai todas as turmas
#      python extrair_sus.py --turma "1º ANO"       # só uma aba
#      python extrair_sus.py --apenas-preenchidos   # ignora SUS vazio
#      python extrair_sus.py --verbose              # logs detalhados
#
# =============================================================================

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
#  Constantes locais (não dependem de config.py para o script ser portátil)
# ---------------------------------------------------------------------------

BASE           = Path.home() / "compartilhado/ARQUIVOS/ESCOLA JUDITH"
SAIDA_JSON     = BASE / "PYTHON/SERE/2026/sus_alunos.json"

# Layout da planilha (0-indexed)
COL_NUMERO = 0   # A — Nº de chamada
COL_CPF    = 1   # B — CPF
COL_CGM    = 2   # C — CGM
COL_SUS    = 3   # D — Cartão SUS
COL_NOME   = 4   # E — Nome do aluno

# Linha onde os dados dos alunos começam (1-indexed, conforme a planilha)
LINHA_INICIO_DADOS = 11

# Abas que existem na planilha e suas turmas de referência
ABAS_TURMAS = {
    "INFANTIL IV": "INFANTIL 4 Integral A",
    "INFANTIL V":  "INFANTIL 5 Integral A",
    "1º ANO":      "1º Ano Integral A",
    "2º ANO":      "2º Ano Integral A",
    "3º ANO A":    "3º Ano Integral A",
    "3º ANO B":    "3º Ano Integral B",
    "4º ANO":      "4º Ano Integral A",
    "5º ANO":      "5º Ano Integral A",
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
            logging.FileHandler(f"extrair_sus_{data}.log", encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai Cartão SUS da planilha Google Sheets e gera JSON."
    )
    parser.add_argument(
        "--turma", dest="turma", default=None,
        help="Nome exato da aba na planilha (ex: '1º ANO'). Padrão: todas.",
    )
    parser.add_argument(
        "--apenas-preenchidos", action="store_true",
        help="Inclui no JSON apenas alunos com SUS preenchido.",
    )
    parser.add_argument(
        "--saida", dest="saida", default=str(SAIDA_JSON),
        help=f"Caminho do JSON de saída. Padrão: {SAIDA_JSON}",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Ativa logs detalhados (DEBUG).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
#  Leitura da aba
# ---------------------------------------------------------------------------

def _ler_sus_da_aba(sheets, nome_aba: str, apenas_preenchidos: bool) -> list:
    """
    Lê a aba `nome_aba` a partir da linha LINHA_INICIO_DADOS e retorna
    lista de dicts  { turma, cgm, nome, sus }.

    `sheets` é o objeto já retornado por criar_servico() — que no
    sheets_client.py corresponde ao resultado de build(...).spreadsheets(),
    então NÃO chamamos .spreadsheets() novamente aqui.
    """
    from sheets_client import SPREADSHEET_ID

    # Range: coluna A até E, da linha de início até o fim da aba
    range_leitura = f"'{nome_aba}'!A{LINHA_INICIO_DADOS}:E"

    resultado = (
        sheets
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=range_leitura)
        .execute()
    )

    linhas = resultado.get("values", [])
    registros = []

    for i, linha in enumerate(linhas):
        # Garantir que a linha tem colunas suficientes
        while len(linha) <= max(COL_CGM, COL_SUS, COL_NOME):
            linha.append("")

        cgm  = str(linha[COL_CGM]).strip()
        sus  = str(linha[COL_SUS]).strip()
        nome = str(linha[COL_NOME]).strip()

        # Linha completamente vazia → fim da lista de alunos
        if not cgm and not nome:
            continue

        if apenas_preenchidos and not sus:
            continue

        registros.append({
            "turma": ABAS_TURMAS.get(nome_aba, nome_aba),
            "cgm":   cgm,
            "nome":  nome,
            "sus":   sus,
        })

    return registros


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _configurar_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    inicio = time.monotonic()
    logger.info("=" * 60)
    logger.info("  EXTRATOR DE CARTÃO SUS — %s", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    logger.info("=" * 60)

    # --- 1. Autenticar no Google Sheets ----------------------------------------
    try:
        from sheets_client import criar_servico, listar_abas
        sheets = criar_servico()
    except Exception as e:
        logger.error("Falha na autenticação com o Google: %s", e)
        sys.exit(1)

    # --- 2. Determinar quais abas processar ------------------------------------
    try:
        abas_disponiveis = listar_abas(sheets)
    except Exception as e:
        logger.error("Não foi possível listar as abas: %s", e)
        sys.exit(1)

    if args.turma:
        abas_para_ler = [args.turma] if args.turma in abas_disponiveis else []
        if not abas_para_ler:
            logger.error("Aba '%s' não encontrada na planilha.", args.turma)
            sys.exit(1)
    else:
        # Só processa as abas que estão no mapeamento conhecido
        abas_para_ler = [a for a in ABAS_TURMAS if a in abas_disponiveis]

    logger.info("Abas a processar: %s", abas_para_ler)

    # --- 3. Extrair dados de cada aba ------------------------------------------
    todos_registros = []
    erros = []

    for nome_aba in abas_para_ler:
        logger.info("")
        logger.info("─── Aba: %s ───", nome_aba)
        try:
            registros = _ler_sus_da_aba(sheets, nome_aba, args.apenas_preenchidos)
            com_sus   = sum(1 for r in registros if r["sus"])
            sem_sus   = sum(1 for r in registros if not r["sus"])
            logger.info(
                "  → %d aluno(s) | %d com SUS | %d sem SUS",
                len(registros), com_sus, sem_sus,
            )
            for r in registros:
                flag = "✔" if r["sus"] else "—"
                logger.debug("    [%s] %-40s | CGM: %-10s | SUS: %s", flag, r["nome"], r["cgm"], r["sus"])
            todos_registros.extend(registros)
        except Exception as e:
            logger.error("  ❌ Erro ao ler aba '%s': %s", nome_aba, e)
            erros.append(f"Erro em '{nome_aba}': {e}")

    # --- 4. Salvar JSON --------------------------------------------------------
    caminho_saida = Path(args.saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    with caminho_saida.open("w", encoding="utf-8") as f:
        json.dump(todos_registros, f, ensure_ascii=False, indent=2)

    # --- 5. Resumo -------------------------------------------------------------
    duracao   = time.monotonic() - inicio
    com_sus   = sum(1 for r in todos_registros if r["sus"])
    sem_sus   = sum(1 for r in todos_registros if not r["sus"])

    logger.info("")
    logger.info("=" * 60)
    logger.info("  RESUMO")
    logger.info("  📋 Total de alunos  : %d", len(todos_registros))
    logger.info("  ✔  Com SUS          : %d", com_sus)
    logger.info("  —  Sem SUS          : %d", sem_sus)
    logger.info("  💾 JSON salvo em    : %s", caminho_saida)
    if erros:
        logger.info("  ❌ Erros            : %d", len(erros))
        for err in erros:
            logger.warning("       %s", err)
    logger.info("  ⏱  Duração          : %.1fs", duracao)
    logger.info("=" * 60)

    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
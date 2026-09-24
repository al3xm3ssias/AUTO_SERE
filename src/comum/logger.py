""" === RESUMO ESTRUTURAL DO SCRIPT ===
Funções encontradas:
   - Função: get_logger()
       Retorna um logger configurado com saída em arquivo e console.
       Parâmetros
       ----------
       source        : caminho do script (__file__) ou nome livre ("relatorio")
       log_dir       : pasta onde salvar o .txt  (padrão: LOGS_DIR do projeto)
       level_file    : nível mínimo gravado no arquivo  (padrão: DEBUG)
       level_console : nível mínimo exibido no terminal (padrão: INFO)
       max_bytes     : tamanho máximo do arquivo antes de rotacionar
       backup_count  : quantos arquivos de backup manter
==================================== """

"""
logger.py — Módulo de log genérico e reutilizável
==================================================
Portado de AUTO_SERE/logger.py (original) para src/comum/logger.py.

Única mudança de comportamento em relação ao original: quando log_dir não é
informado, em vez de usar a pasta do próprio script (os.path.dirname do
arquivo chamador), usa a pasta central de logs do projeto (LOGS_DIR, definida
em src/comum/paths.py). Isso evita logs espalhados por várias pastas de
módulo e casa com a estrutura logs/ criada pelo bootstrap. Todo o resto —
formato de mensagem, rotação, níveis, nomes de arquivo — é idêntico ao
original.

Uso básico (qualquer script):
    from src.comum.logger import get_logger
    log = get_logger(__file__)          # nome do log = nome do script
    log.info("Mensagem")
    log.warning("Aviso")
    log.error("Erro")
    log.debug("Detalhe técnico")

Uso avançado (nome e pasta customizados):
    log = get_logger("meu_processo", log_dir="logs/")
"""
import logging
import os
from datetime import datetime

try:
    # Import relativo ao pacote do projeto (uso normal dentro de src/).
    from .paths import LOGS_DIR
    _LOG_DIR_PADRAO = str(LOGS_DIR)
except ImportError:
    # Fallback para quando o módulo é executado/importado fora do pacote
    # (ex.: script solto, teste isolado). Mantém o comportamento do
    # logger.py original: usa a pasta do próprio script chamador.
    _LOG_DIR_PADRAO = None


def get_logger(
    source: str = "app",
    log_dir: str = None,                 # None = LOGS_DIR do projeto (ou pasta do script, em fallback)
    level_file: int = logging.DEBUG,
    level_console: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,   # 5 MB antes de rotacionar
    backup_count: int = 3,               # mantém até 3 arquivos antigos
) -> logging.Logger:
    """
    Retorna um logger configurado com saída em arquivo e console.
    Parâmetros
    ----------
    source        : caminho do script (__file__) ou nome livre ("relatorio")
    log_dir       : pasta onde salvar o .txt  (padrão: LOGS_DIR do projeto)
    level_file    : nível mínimo gravado no arquivo  (padrão: DEBUG)
    level_console : nível mínimo exibido no terminal (padrão: INFO)
    max_bytes     : tamanho máximo do arquivo antes de rotacionar
    backup_count  : quantos arquivos de backup manter
    """
    from logging.handlers import RotatingFileHandler

    # ── nome do logger e do arquivo ──────────────────────────────────────────
    base_name = os.path.splitext(os.path.basename(source))[0]  # "main", "relatorio", …
    logger_name = f"sere.{base_name}"

    # Evita duplicar handlers se o mesmo logger for pedido duas vezes
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)  # o filtro fino fica nos handlers

    # ── pasta de saída ──────────────────────────────────────────────────────
    if log_dir is None:
        if _LOG_DIR_PADRAO is not None:
            log_dir = _LOG_DIR_PADRAO
        else:
            # Fallback idêntico ao comportamento do logger.py original.
            log_dir = os.path.dirname(os.path.abspath(source))

    os.makedirs(log_dir, exist_ok=True)
    log_filename = os.path.join(log_dir, f"{base_name}_log.txt")

    # ── formato das mensagens ─────────────────────────────────────────────────
    fmt = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── handler de arquivo (com rotação automática) ───────────────────────────
    fh = RotatingFileHandler(
        log_filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.setLevel(level_file)
    fh.setFormatter(fmt)

    # ── handler de console ────────────────────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(level_console)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    # ── linha de abertura no arquivo ──────────────────────────────────────────
    logger.debug(f"{'='*60}")
    logger.debug(f"Sessão iniciada — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    logger.debug(f"Script: {os.path.abspath(source)}")
    logger.debug(f"Log salvo em: {log_filename}")
    logger.debug(f"{'='*60}")

    return logger

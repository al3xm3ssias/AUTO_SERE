"""
sere_utils.py — Utilitários puros compartilhados entre scripts do SERE
=============================================================================
Portado de AUTO_SERE/sere_2026.py (seção "UTILITÁRIOS", linhas 394-436 do
original) para src/comum/sere_utils.py.

Estas são funções SEM efeito colateral (sem I/O de rede, sem Playwright) e
sem estado — por isso ficam num módulo comum, reutilizável por qualquer
script que precise normalizar texto, interpretar datas do SERE ou traduzir
entre nome de slot e idtipodocumento. A observação do usuário em 28/08/2026
foi que a maioria dos 38 scripts originais reimplementa lógica parecida —
este módulo é o primeiro passo para parar de duplicar isso.

MUDANÇA EM RELAÇÃO AO ORIGINAL:
slot_para_idtipo() no sere_2026.py original tinha uma linha morta/quebrada
(`slot_para_idtipo.__wrapped__ if hasattr(...) else None`, uma tentativa de
recursão que nunca funcionava de fato — __wrapped__ não existe numa função
comum sem decorator). O comportamento pretendido (achar o idtipo mesmo
quando o nome do slot bate com um SINÔNIMO, não só com o nome canônico) foi
reimplementado de forma direta e funcional abaixo, preservando a mesma
intenção. Nenhuma outra função foi alterada.

Uso:
    from src.comum.sere_utils import norm, parse_data_sere, data_dentro_do_prazo, slot_para_idtipo
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta

from .sere_normalizacao import IDTIPO_PARA_SLOT, SINONIMOS

# Prazo padrão (em meses) usado por data_dentro_do_prazo quando o chamador
# não especifica outro valor. Igual ao PRAZO_REENVIO_MESES do sere_2026.py
# original (linha 160).
PRAZO_REENVIO_MESES_PADRAO = 9


def norm(texto: str) -> str:
    """Remove acentos e converte para maiúsculas (usado em comparações de texto)."""
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return sem_acento.upper().strip()


def parse_data_sere(data_str: str) -> datetime | None:
    """Converte string 'DD/MM/YYYY HH:MM' para datetime. Retorna None se inválida."""
    if not data_str:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(data_str.strip(), fmt)
        except ValueError:
            continue
    return None


def data_dentro_do_prazo(data_str: str, meses: int = PRAZO_REENVIO_MESES_PADRAO) -> bool:
    """
    Retorna True se a data está dentro do prazo (mais recente que N meses atrás).
    True = upload recente = deve PULAR o reenvio.
    """
    dt = parse_data_sere(data_str)
    if dt is None:
        return False
    limite = datetime.now() - timedelta(days=meses * 30)
    return dt >= limite


def slot_para_idtipo(slot: str) -> str | None:
    """
    Retorna o idtipodocumento para um nome de slot (ou None se desconhecido).
    Primeiro tenta bater com o nome canônico (IDTIPO_PARA_SLOT); se não achar,
    tenta bater com qualquer sinônimo conhecido (SINONIMOS) do mesmo slot.
    """
    slot_norm = norm(slot)

    for idtipo, nome in IDTIPO_PARA_SLOT.items():
        if norm(nome) == slot_norm:
            return idtipo

    # slot_norm pode ser um SINÔNIMO em vez do nome canônico — procura a
    # chave canônica correspondente e resolve o idtipo dela.
    for nome_canonico, alias_list in SINONIMOS.items():
        if slot_norm in {norm(a) for a in alias_list}:
            for idtipo, nome in IDTIPO_PARA_SLOT.items():
                if norm(nome) == norm(nome_canonico):
                    return idtipo

    return None
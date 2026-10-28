"""
pastas_transferencias.py — as pastas de documentos dos transferidos (fonte única)
=============================================================================
    dados/<ano letivo>/TRANSFERENCIAS/
        PROCESSAMENTO DE PARECERES   pareceres digitalizados, ainda a processar (QR) e enviar ao SERE
        PARECERES                    pareceres já processados (<turma>/NN-NOME.pdf), enviados ao SERE e arquivados
        HISTORICO                    históricos escolares baixados do SERE e enviados à pasta virtual
        GUIA DE TRANSFERENCIA        guias de transferência baixadas do SERE e enviadas à pasta virtual

Quem gera os documentos (processo_transferidos) e quem os envia (sere_2026.modo_transferidos) usam ESTAS
funções, para nunca divergirem. As pastas antigas (<pasta de digitalização>/TRANSFERENCIAS/HISTÓRICOS etc.)
continuam sendo consultadas pelo envio, só para achar arquivos que já estavam lá (ver pastas_antigas).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.comum import paths as _paths

NOME_BASE = "TRANSFERENCIAS"
PROCESSAMENTO_PARECERES = "PROCESSAMENTO DE PARECERES"
PARECERES = "PARECERES"
HISTORICO = "HISTORICO"
GUIA = "GUIA DE TRANSFERENCIA"

SUBPASTAS = (PROCESSAMENTO_PARECERES, PARECERES, HISTORICO, GUIA)

# nomes que o projeto usava dentro da pasta de digitalização, antes de existir este módulo
_NOMES_ANTIGOS = {HISTORICO: "HISTÓRICOS", GUIA: "GUIA DE TRANSFERENCIA", PARECERES: "PARECERES"}


def pasta_transferencias(dados_dir: Optional[Path] = None) -> Path:
    """dados/<ano letivo>/TRANSFERENCIAS (não cria nada)."""
    return (Path(dados_dir) if dados_dir is not None else _paths.dados_ano_atual()) / NOME_BASE


def subpasta(nome: str, dados_dir: Optional[Path] = None) -> Path:
    if nome not in SUBPASTAS:
        raise ValueError(f"Subpasta desconhecida: {nome!r}. Válidas: {', '.join(SUBPASTAS)}")
    return pasta_transferencias(dados_dir) / nome


def garantir_pastas(dados_dir: Optional[Path] = None) -> list[Path]:
    """Cria a TRANSFERENCIAS e as 4 subpastas se faltarem (nunca apaga nem move nada). Retorna as criadas."""
    criadas = []
    for nome in SUBPASTAS:
        pasta = subpasta(nome, dados_dir)
        if not pasta.exists():
            criadas.append(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
    return criadas


def pastas_antigas(nome: str, pasta_digitalizacao: Optional[Path]) -> list[Path]:
    """Onde o projeto guardava esses documentos antes (só leitura, para achar arquivos já existentes)."""
    if pasta_digitalizacao is None or nome not in _NOMES_ANTIGOS:
        return []
    return [Path(pasta_digitalizacao) / NOME_BASE / _NOMES_ANTIGOS[nome]]

# =============================================================================
#  turmas_reader.py — Leitura e parsing do arquivo turmas.json
# =============================================================================

import json
import logging
from pathlib import Path
from typing import Dict, List

from config import TURMAS_JSON_PATH

logger = logging.getLogger(__name__)


def carregar_turmas(caminho: str = TURMAS_JSON_PATH) -> Dict[str, List[dict]]:
    """
    Carrega o arquivo turmas.json e retorna um dicionário:
        { "Nome da Turma": [ {aluno}, ... ], ... }

    Raises:
        FileNotFoundError: se o arquivo não existir.
        ValueError: se o JSON estiver mal-formado.
    """
    path = Path(caminho)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    with path.open(encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido em '{caminho}': {e}") from e

    if not isinstance(data, dict):
        raise ValueError("turmas.json deve ser um objeto JSON { turma: [alunos] }.")

    total = sum(len(v) for v in data.values())
    logger.info(
        "turmas.json carregado — %d turma(s), %d aluno(s) no total.",
        len(data), total,
    )
    return data


def indexar_por_cgm(turmas: Dict[str, List[dict]]) -> Dict[str, dict]:
    """
    Retorna um índice plano  { CGM: {aluno + 'turma': nome_turma} }
    para facilitar buscas O(1) por CGM.

    Registra aviso se encontrar CGMs duplicados no JSON.
    """
    indice: Dict[str, dict] = {}
    for turma, alunos in turmas.items():
        for aluno in alunos:
            cgm = str(aluno.get("CGM", "")).strip()
            if not cgm:
                logger.warning("Aluno sem CGM na turma '%s': %s", turma, aluno.get("Nome"))
                continue
            if cgm in indice:
                logger.warning(
                    "CGM duplicado '%s' — '%s' (turma '%s') sobrescreve entrada anterior.",
                    cgm, aluno.get("Nome"), turma,
                )
            indice[cgm] = {**aluno, "turma": turma}
    return indice
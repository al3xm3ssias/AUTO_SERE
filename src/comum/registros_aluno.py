"""
registros_aluno.py — Regra de consolidação de registros do mesmo aluno (CGM)
=============================================================================
Usado por src.automacao.turmas e src.automacao.alunos.

PROBLEMA
    Um aluno que foi transferido e depois voltou para a mesma escola aparece
    DUAS VEZES na listagem da turma com o mesmo CGM — um registro
    "Transferido" (data da saída) e outro "Matriculado" (data do retorno):

        2   1031702476  ANNA BEATRIZ CAETANO DIAS  ...  Transferido  13/05/2026
        31  1031702476  ANNA BEATRIZ CAETANO DIAS  ...  Matriculado  16/10/2026

    Tratar o CGM como chave única fazia um registro engolir o outro (e, no
    alunos.py, o clique por CGM abria sempre a primeira linha).

REGRA
    - A identidade de um REGISTRO é (CGM, Situação, Data da movimentação, N).
    - Situações diferentes + datas diferentes  → mesmo aluno, dois cadastros
      legítimos: MANTÉM os dois (um transferido, outro matriculado).
    - O nº da chamada (N) é o validador secundário: dois registros do mesmo
      CGM com (Situação, Data, N) idênticos são o mesmo registro lido duas
      vezes (retry/recarga da tabela) → descarta a repetição. O aluno que
      retorna entra no fim da chamada, então espera-se N maior que o do
      registro de transferência; se não for, mantém ambos e só avisa.
    - O registro "Matriculado" posterior a um "Transferido" recebe
      "Retorno": True.

Funções puras: não dependem de Playwright nem de credenciais, para poderem
ser testadas isoladamente.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Optional

from src.comum.logger import get_logger

log = get_logger(__file__)


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return sem_acento.strip().lower()


def eh_transferido(situacao: str) -> bool:
    return "transf" in _norm(situacao)


def eh_matriculado(situacao: str) -> bool:
    return _norm(situacao) == "matriculado"


def parse_data(texto: str) -> Optional[date]:
    """'dd/mm/aaaa' → date (None se vazio ou inválido)."""
    try:
        return datetime.strptime(str(texto or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _n(aluno: dict) -> Optional[int]:
    try:
        return int(aluno.get("N"))
    except (TypeError, ValueError):
        return None


def chave_registro(aluno: dict) -> tuple:
    """(CGM, situação normalizada, data da movimentação, N) — identidade do registro."""
    return (
        str(aluno.get("CGM", "")).strip(),
        _norm(aluno.get("Situação", aluno.get("Situacao", ""))),
        str(aluno.get("Data Matricula", "")).strip(),
        _n(aluno),
    )


def consolidar_registros(alunos: list[dict], rotulo: str = "") -> list[dict]:
    """
    Aplica a regra do módulo a uma lista de alunos (uma turma, por exemplo).
    Preserva a ordem original; devolve uma nova lista (os dicts são os mesmos
    objetos, apenas com "Retorno": True nos casos de retorno).
    """
    prefixo = f"[{rotulo}] " if rotulo else ""
    vistos: set[tuple] = set()
    resultado: list[dict] = []

    for aluno in alunos:
        chave = chave_registro(aluno)
        if chave[0] and chave in vistos:
            log.info(f"{prefixo}CGM {chave[0]}: registro repetido (mesma situação, data e N) descartado.")
            continue
        vistos.add(chave)
        resultado.append(aluno)

    por_cgm: dict[str, list[dict]] = {}
    for aluno in resultado:
        cgm = str(aluno.get("CGM", "")).strip()
        if cgm:
            por_cgm.setdefault(cgm, []).append(aluno)

    for cgm, regs in por_cgm.items():
        if len(regs) < 2:
            continue
        transferidos = [r for r in regs if eh_transferido(r.get("Situação", r.get("Situacao", "")))]
        matriculados = [r for r in regs if eh_matriculado(r.get("Situação", r.get("Situacao", "")))]
        nome = regs[0].get("Nome", "")

        retornos = 0
        for mat in matriculados:
            d_mat = parse_data(mat.get("Data Matricula", ""))
            for tra in transferidos:
                d_tra = parse_data(tra.get("Data Matricula", ""))
                if d_mat and d_tra and d_mat > d_tra:
                    mat["Retorno"] = True
                    retornos += 1
                    n_mat, n_tra = _n(mat), _n(tra)
                    if n_mat is not None and n_tra is not None and n_mat <= n_tra:
                        log.warning(
                            f"{prefixo}CGM {cgm} ({nome}): retorno com nº de chamada ({n_mat}) "
                            f"não posterior ao da transferência ({n_tra}) — mantidos os dois, confira no SERE."
                        )
                    break

        if retornos:
            log.info(
                f"{prefixo}CGM {cgm} ({nome}): aluno retornou após transferência — "
                f"mantidos {len(regs)} cadastros (transferido + matriculado)."
            )
        else:
            log.warning(
                f"{prefixo}CGM {cgm} ({nome}): {len(regs)} registros com o mesmo CGM sem padrão "
                f"transferência→retorno (situações/datas: "
                f"{[(r.get('Situação'), r.get('Data Matricula')) for r in regs]}) — mantidos todos."
            )

    return resultado


# ──────────────────────────────────────────────────────────────────────
# Cruzamento cadastro (alunos.json) × movimentação (turmas.json)
# ──────────────────────────────────────────────────────────────────────

def registro_principal(registros: list[dict]) -> Optional[dict]:
    """
    Entre vários registros do mesmo CGM, o vigente: o matriculado de data mais
    recente; se não houver matriculado, o de data mais recente. Usado onde a
    tela só comporta UMA situação por CGM (ex.: abas de documentos).
    """
    if not registros:
        return None

    def _data(r: dict) -> date:
        return parse_data(r.get("Data Matricula", "")) or date.min

    matriculados = [r for r in registros if eh_matriculado(r.get("Situação", r.get("Situacao", "")))]
    return max(matriculados or registros, key=_data)


def casar_com_turmas(aluno: dict, candidatos: list[dict], usados: set[int]) -> Optional[dict]:
    """
    Escolhe, entre os registros de turmas.json do mesmo CGM (`candidatos`), o que
    corresponde a ESTE cadastro de alunos.json, sem reaproveitar um já usado.

    1. Cadastro com Situação + Data Matricula (coleta nova): casa por
       (situação, data) e, se houver, por N (validador secundário).
    2. Cadastro sem esses campos (alunos.json antigo): usa a ordem — a 1ª
       ocorrência do CGM em alunos.json corresponde ao 1º registro do CGM em
       turmas.json, e assim por diante (ambos vêm da mesma listagem da turma).
    """
    livres = [c for c in candidatos if id(c) not in usados]
    if not livres:
        return None

    sit = _norm(aluno.get("Situação", aluno.get("Situacao", "")))
    data = str(aluno.get("Data Matricula", "")).strip()
    escolhido = None
    if sit and data:
        mesmos = [c for c in livres
                  if _norm(c.get("Situação", c.get("Situacao", ""))) == sit
                  and str(c.get("Data Matricula", "")).strip() == data]
        n = _n(aluno)
        escolhido = next((c for c in mesmos if n is not None and _n(c) == n), None) or (mesmos[0] if mesmos else None)
    if escolhido is None:
        escolhido = livres[0]
    usados.add(id(escolhido))
    return escolhido

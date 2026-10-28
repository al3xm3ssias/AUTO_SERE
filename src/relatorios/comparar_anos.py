"""
comparar_anos.py — Compara o turmas.json de dois anos letivos
=============================================================================
Só lê arquivos: dados/<ano>/turmas.json de cada ano (não acessa o SERE, não altera nada).
O CGM é o código permanente do aluno, então ele liga o mesmo aluno em anos diferentes.

CADA ALUNO CAI EM UMA SÓ CATEGORIA (A = ano base, B = ano comparado):
  Transferidos  em B com Situação "Transferido" (diz onde ele estava em A, se estava).
  Continuam     em A e em B (matriculado em B). Movimento: Promovido, Mesma série, Mudou de turma...
  Novos         em B (matriculado) e não estavam em A.
  Saíram        em A e não estão em B. O motivo provável é deduzido:
                  · "Concluiu a etapa"  → estava na última série que a escola tem (esperado sair);
                  · "Verificar"         → saiu antes de concluir (transferência, desistência...);
                  · "Já estava transferido no ano base" → não conta como novidade.

A "série" vem do nome da turma ("5º Ano Integral A" → 5). A última série da escola é a maior série
que aparece nos dois anos. Turma sem número (ex.: "Pré II") não entra nas regras de série.

Saída: dados/<ano comparado>/comparacao_turmas_<base>_<comparado>.xlsx (uma aba por categoria + Resumo).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.comum import paths
from src.comum.arquivos_json import carregar_json
from src.comum.opcoes_execucao import eh_transferido

_RE_SERIE = re.compile(r"(\d+)\s*[º°ªoOaA]?\s*ano", re.IGNORECASE)
_RE_ANO = re.compile(r"^\d{4}$")


def anos_com_turmas() -> list[str]:
    """Anos que têm dados/<ano>/turmas.json, do mais antigo ao mais novo."""
    base = Path(paths.DADOS_DIR)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and _RE_ANO.match(p.name) and (p / "turmas.json").is_file())


def serie_da_turma(nome: str) -> Optional[int]:
    achou = _RE_SERIE.search(str(nome))
    return int(achou.group(1)) if achou else None


def _indexar(turmas_json: dict) -> dict[str, dict]:
    """CGM → {cgm, nome, turma, situacao, transferido}. Se o CGM aparece mais de uma vez, vale o matriculado."""
    indice: dict[str, dict] = {}
    for turma, alunos in (turmas_json or {}).items():
        for a in alunos if isinstance(alunos, list) else []:
            cgm = str(a.get("CGM", "")).strip()
            if not cgm:
                continue
            reg = {"cgm": cgm, "nome": str(a.get("Nome", "")).strip(), "turma": turma,
                   "situacao": str(a.get("Situação", a.get("Situacao", ""))).strip(), "transferido": eh_transferido(a)}
            if cgm not in indice or (indice[cgm]["transferido"] and not reg["transferido"]):
                indice[cgm] = reg
    return indice


@dataclass
class Comparacao:
    ano_base: str
    ano_comparado: str
    ultima_serie: Optional[int] = None
    continuam: list[dict] = field(default_factory=list)
    novos: list[dict] = field(default_factory=list)
    sairam: list[dict] = field(default_factory=list)
    transferidos: list[dict] = field(default_factory=list)
    total_base: int = 0
    total_comparado: int = 0
    matriculados_base: int = 0
    matriculados_comparado: int = 0

    def contar(self, lista: str, campo: str, valor: str) -> int:
        return sum(1 for x in getattr(self, lista) if x[campo] == valor)


def _movimento(turma_a: str, turma_b: str, voltou: bool) -> str:
    sa, sb = serie_da_turma(turma_a), serie_da_turma(turma_b)
    if sa is not None and sb is not None:
        if sb == sa + 1:
            movimento = "Promovido (série seguinte)"
        elif sb == sa:
            movimento = "Mesma série (repetência? verificar)"
        elif sb < sa:
            movimento = "Série anterior (verificar)"
        else:
            movimento = "Avançou mais de uma série (verificar)"
    else:
        movimento = "Mesma turma" if turma_a == turma_b else "Mudou de turma"
    return movimento + (" — voltou: estava transferido no ano base" if voltou else "")


def comparar(turmas_base: dict, turmas_comparado: dict, ano_base: str = "base", ano_comparado: str = "comparado") -> Comparacao:
    a, b = _indexar(turmas_base), _indexar(turmas_comparado)
    r = Comparacao(ano_base, ano_comparado, total_base=len(a), total_comparado=len(b),
                   matriculados_base=sum(1 for x in a.values() if not x["transferido"]),
                   matriculados_comparado=sum(1 for x in b.values() if not x["transferido"]))
    series = [s for x in (*a.values(), *b.values()) if not x["transferido"] and (s := serie_da_turma(x["turma"])) is not None]
    r.ultima_serie = max(series) if series else None

    for cgm, nb in b.items():
        na = a.get(cgm)
        if nb["transferido"]:
            r.transferidos.append({"cgm": cgm, "nome": nb["nome"], "turma_b": nb["turma"], "situacao_b": nb["situacao"],
                                   "estava_em_a": "Sim" if na else "Não", "turma_a": na["turma"] if na else "",
                                   "situacao_a": na["situacao"] if na else ""})
        elif na:
            r.continuam.append({"cgm": cgm, "nome": nb["nome"] or na["nome"], "turma_a": na["turma"], "situacao_a": na["situacao"],
                                "turma_b": nb["turma"], "situacao_b": nb["situacao"],
                                "movimento": _movimento(na["turma"], nb["turma"], na["transferido"])})
        else:
            r.novos.append({"cgm": cgm, "nome": nb["nome"], "turma_b": nb["turma"], "situacao_b": nb["situacao"]})

    for cgm, na in a.items():
        if cgm in b:
            continue
        if na["transferido"]:
            motivo = "Já estava transferido no ano base"
        elif r.ultima_serie is not None and serie_da_turma(na["turma"]) == r.ultima_serie:
            motivo = "Concluiu a etapa (última série da escola)"
        else:
            motivo = "Verificar: saiu antes de concluir"
        r.sairam.append({"cgm": cgm, "nome": na["nome"], "turma_a": na["turma"], "situacao_a": na["situacao"], "motivo": motivo})

    for lista in (r.continuam, r.novos, r.sairam, r.transferidos):
        lista.sort(key=lambda x: (x["nome"].casefold(), x["cgm"]))
    return r


# ───────────────────────────── planilha ─────────────────────────────

def _resumo_linhas(r: Comparacao) -> list[tuple[str, object]]:
    linhas: list[tuple[str, object]] = [
        (f"Alunos em {r.ano_base} (no turmas.json)", r.total_base),
        (f"   matriculados em {r.ano_base}", r.matriculados_base),
        (f"Alunos em {r.ano_comparado} (no turmas.json)", r.total_comparado),
        (f"   matriculados em {r.ano_comparado}", r.matriculados_comparado),
        ("", ""),
        (f"Continuam ({r.ano_base} → {r.ano_comparado})", len(r.continuam)),
    ]
    for mov in sorted({x["movimento"] for x in r.continuam}):
        linhas.append((f"   {mov}", r.contar("continuam", "movimento", mov)))
    linhas += [(f"Novos em {r.ano_comparado}", len(r.novos)),
               (f"Saíram (estavam em {r.ano_base} e não estão em {r.ano_comparado})", len(r.sairam))]
    for mot in sorted({x["motivo"] for x in r.sairam}):
        linhas.append((f"   {mot}", r.contar("sairam", "motivo", mot)))
    linhas += [(f"Transferidos em {r.ano_comparado}", len(r.transferidos)),
               ("", ""),
               ("Última série da escola considerada", f"{r.ultima_serie}º ano" if r.ultima_serie else "não identificada")]
    return linhas


def gerar_planilha(r: Comparacao, caminho: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append([f"Comparação de turmas.json: {r.ano_base} → {r.ano_comparado}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    for rotulo, valor in _resumo_linhas(r):
        ws.append([rotulo, valor])
    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 18

    def aba(titulo: str, cabecalho: list[str], chaves: list[str], dados: list[dict]):
        w = wb.create_sheet(titulo)
        w.append(cabecalho)
        for c in w[1]:
            c.font = Font(bold=True)
        for linha in dados:
            w.append([linha.get(k, "") for k in chaves])
        for i, titulo_col in enumerate(cabecalho, 1):
            largura = max([len(str(titulo_col))] + [len(str(linha.get(chaves[i - 1], ""))) for linha in dados])
            w.column_dimensions[get_column_letter(i)].width = min(max(largura + 2, 10), 60)
        w.freeze_panes = "A2"
        w.auto_filter.ref = w.dimensions

    A, B = r.ano_base, r.ano_comparado
    aba("Continuam", ["CGM", "Nome", f"Turma {A}", f"Situação {A}", f"Turma {B}", f"Situação {B}", "Movimento"],
        ["cgm", "nome", "turma_a", "situacao_a", "turma_b", "situacao_b", "movimento"], r.continuam)
    aba("Saíram", ["CGM", "Nome", f"Turma {A}", f"Situação {A}", "Motivo provável"],
        ["cgm", "nome", "turma_a", "situacao_a", "motivo"], r.sairam)
    aba("Novos", ["CGM", "Nome", f"Turma {B}", f"Situação {B}"], ["cgm", "nome", "turma_b", "situacao_b"], r.novos)
    aba("Transferidos", ["CGM", "Nome", f"Turma {B}", f"Situação {B}", f"Estava em {A}?", f"Turma {A}", f"Situação {A}"],
        ["cgm", "nome", "turma_b", "situacao_b", "estava_em_a", "turma_a", "situacao_a"], r.transferidos)

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    wb.save(temporario)
    os.replace(temporario, caminho)                    # nunca deixa uma planilha pela metade
    return caminho


# ───────────────────────────── execução ─────────────────────────────

def _ler_turmas(ano: str) -> dict:
    caminho = Path(paths.DADOS_DIR) / ano / "turmas.json"
    return carregar_json(caminho, dict, dict)


def executar_compara_anos(ano_base: str, ano_comparado: str, log: Callable[[str], None] = print) -> Comparacao:
    """Compara dados/<ano_base>/turmas.json com dados/<ano_comparado>/turmas.json e grava a planilha."""
    r = comparar(_ler_turmas(ano_base), _ler_turmas(ano_comparado), ano_base, ano_comparado)
    destino = Path(paths.DADOS_DIR) / ano_comparado / f"comparacao_turmas_{ano_base}_{ano_comparado}.xlsx"
    gerar_planilha(r, destino)
    log("=" * 60)
    log(f"COMPARAÇÃO DE TURMAS: {ano_base} → {ano_comparado}")
    log("=" * 60)
    for rotulo, valor in _resumo_linhas(r):
        log(f"{rotulo}: {valor}" if rotulo.strip() else "")
    log(f"✅ Planilha salva: {destino}")
    return r

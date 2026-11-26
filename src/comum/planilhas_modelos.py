"""
planilhas_modelos.py — modelos padrão de planilha do sistema
=============================================================================
Um MODELO é a estrutura original (abas, colunas, fórmulas, listas suspensas) de uma planilha que a escola cria e o
sistema mantém: Chamada, Planilha das Turmas, Listagem dos Alunos e IMC. É diferente de uma PLANILHA CADASTRADA (o
arquivo em uso, em planilhas_registro.py) e de uma PLANILHA EXTERNA (recebida pronta da Secretaria, como a dos
pareceres do Infantil, que nunca nasce de um modelo).

O modelo é NEUTRO quanto à plataforma: `montar(contexto)` devolve abas (`Aba`) com valores e fórmulas em notação
universal (funções em inglês, argumentos separados por vírgula, referências A1). As plataformas (planilhas_plataformas.py)
traduzem as abas para Google Sheets, .xlsx e .ods mantendo estrutura, colunas e fórmulas iguais.

Como acrescentar um modelo novo SEM mexer nos módulos do sistema:
    • Python:  registrar_modelo(Modelo(chave=..., nome=..., finalidade=..., montar=minha_funcao))
    • ou, sem programar: um arquivo .json em config/modelos_planilha/ (formato em `_modelo_de_json`); o catálogo o
      encontra sozinho. Um modelo JSON com a mesma chave de um padrão o SUBSTITUI (a escola adapta o seu).

Reaproveita o que já existia: a Planilha das Turmas usa o layout (CABECALHOS, COLUNAS), os nomes de aba (mapa_abas) e a
regra de transferido de src/automacao/sincroniza_sheets.py — a mesma que a atualização do Google usa depois.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import paths as _paths

MESES_LETIVOS = ("Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")
CLASSIFICACOES_IMC = ("Magreza acentuada", "Magreza", "Eutrofia", "Sobrepeso", "Obesidade", "Obesidade grave")
LINHAS_EXTRAS = 5                        # linhas em branco depois do último aluno (aluno novo no meio do ano)


class ModeloDesconhecido(LookupError):
    """Não há modelo com essa chave."""


@dataclass
class Aba:
    nome: str
    linhas: list[list] = field(default_factory=list)            # matriz a partir de A1; texto que começa com "=" é fórmula
    larguras: list[int] = field(default_factory=list)           # largura de cada coluna, em caracteres
    formatos: list[tuple[str, str]] = field(default_factory=list)   # ("F5:F60", "0.0")
    listas: list[tuple[str, tuple]] = field(default_factory=list)   # ("C5:AG60", ("P", "F", "J")) = lista suspensa
    mesclar: list[str] = field(default_factory=list)
    negrito_linhas: list[int] = field(default_factory=list)     # nº das linhas (a partir de 1) em negrito
    congelar_linhas: int = 0
    congelar_colunas: int = 0


@dataclass
class Contexto:
    """O que o modelo precisa saber para se montar. `turmas` é o turmas.json do ano; `turma` só vale para modelo de uma turma."""
    ano: int
    turmas: dict = field(default_factory=dict)
    turma: str = ""
    escola: str = ""
    selecionadas: tuple = ()             # turmas escolhidas para modelos com uma aba por turma (vazio = todas)
    previsao: dict = field(default_factory=dict)   # só para modelos com usa_previsao: {"linhas": [...]} de previsao.alunos_para_planilha


@dataclass
class Modelo:
    chave: str
    nome: str
    finalidade: str                       # finalidade do cadastro (planilhas_registro.FINALIDADES) que o modelo atende
    montar: Callable[[Contexto], list[Aba]]
    descricao: str = ""
    versao: int = 1
    uma_turma: bool = False               # True = a planilha é de UMA turma (a turma é obrigatória na criação)
    origem: str = "sistema"               # "sistema" (padrão) | "escola" (arquivo .json)
    usa_previsao: bool = False            # True = os alunos vêm da Previsão do próximo ano (não do turmas.json)


_MODELOS: dict[str, Modelo] = {}


def registrar_modelo(modelo: Modelo) -> Modelo:
    _MODELOS[modelo.chave] = modelo
    return modelo


def _pasta_modelos_da_escola():
    """config/modelos_planilha/ (função: os testes trocam a pasta)."""
    return _paths.CONFIG_DIR / "modelos_planilha"


def modelos() -> dict[str, Modelo]:
    """Todos os modelos: os padrão + os .json da escola (que substituem os padrão de mesma chave)."""
    achados = dict(_MODELOS)
    pasta = _pasta_modelos_da_escola()
    if pasta.is_dir():
        for arquivo in sorted(pasta.glob("*.json")):
            try:
                modelo = _modelo_de_json(json.loads(arquivo.read_text(encoding="utf-8")), arquivo.name)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"Aviso: modelo de planilha ignorado ({arquivo.name}): {exc}")
                continue
            achados[modelo.chave] = modelo
    return achados


def modelo(chave: str) -> Modelo:
    try:
        return modelos()[str(chave).strip()]
    except KeyError:
        raise ModeloDesconhecido(f"Não existe o modelo '{chave}'. Modelos: {', '.join(modelos()) or '(nenhum)'}.") from None


def modelo_da_finalidade(finalidade: str) -> Optional[Modelo]:
    """O modelo que atende uma finalidade (None = finalidade só de planilha externa, como os pareceres do Infantil)."""
    return next((m for m in modelos().values() if m.finalidade == finalidade), None)


def listar() -> list[dict]:
    return [{"chave": m.chave, "nome": m.nome, "descricao": m.descricao, "finalidade": m.finalidade, "versao": m.versao,
             "uma_turma": m.uma_turma, "origem": m.origem, "usa_previsao": m.usa_previsao} for m in modelos().values()]


# ───────────────────────────── utilitários de montagem ──────────────────────────

def _coluna(indice: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    nome = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        nome = chr(65 + resto) + nome
    return nome


def _aspas(aba: str) -> str:
    return "'" + aba.replace("'", "''") + "'"


def nome_de_aba(texto: str, usados: set) -> str:
    """Nome de aba válido (até 31 caracteres, sem []:*?/\\) e único sem diferenciar maiúsculas."""
    limpo = re.sub(r"[\[\]:*?/\\]", " ", str(texto)).strip() or "Aba"
    limpo = " ".join(limpo.split())[:31]
    base, n = limpo, 2
    while limpo.casefold() in usados:
        sufixo = f" ({n})"
        limpo = base[:31 - len(sufixo)] + sufixo
        n += 1
    usados.add(limpo.casefold())
    return limpo


def _numero(aluno: dict) -> int:
    try:
        return int(str(aluno.get("N") or "").strip())
    except ValueError:
        return 10 ** 6


def _transferido(aluno: dict) -> bool:
    from .opcoes_execucao import eh_transferido            # a mesma regra do resto do sistema
    return eh_transferido(aluno)


def alunos_da_turma(ctx: Contexto, turma: str, incluir_transferidos: bool = False) -> list[dict]:
    lista = ctx.turmas.get(turma) if isinstance(ctx.turmas.get(turma), list) else []
    alunos = [a for a in lista if isinstance(a, dict) and str(a.get("Nome") or "").strip()
              and (incluir_transferidos or not _transferido(a))]
    return sorted(alunos, key=_numero)


def _turmas_do_contexto(ctx: Contexto) -> list[str]:
    escolhidas = list(ctx.selecionadas) if ctx.selecionadas else list(ctx.turmas)
    faltando = [t for t in escolhidas if t not in ctx.turmas]
    if faltando:
        raise ValueError(f"Turma(s) que não existem em turmas.json: {', '.join(faltando)}.")
    return escolhidas


def _exigir_turma(ctx: Contexto) -> str:
    if not ctx.turma:
        raise ValueError("Escolha a turma desta planilha.")
    if ctx.turma not in ctx.turmas:
        raise ValueError(f"A turma '{ctx.turma}' não existe em turmas.json.")
    return ctx.turma


# ───────────────────────────── modelo: Chamada ─────────────────────────────────

def _montar_chamada(ctx: Contexto) -> list[Aba]:
    turma = _exigir_turma(ctx)
    alunos = alunos_da_turma(ctx, turma)
    primeira, total = 5, max(len(alunos) + LINHAS_EXTRAS, 30)
    ultima = primeira + total - 1
    c_dia1, c_dia31 = _coluna(2), _coluna(32)                       # C … AG
    c_pres, c_falt, c_just, c_freq = (_coluna(33), _coluna(34), _coluna(35), _coluna(36))
    abas, usados = [], set()
    for mes in MESES_LETIVOS:
        linhas = [[f"Chamada — {turma} — {mes}/{ctx.ano}"], ["P = presente · F = falta · J = falta justificada"], [],
                  ["Nº", "Nome do aluno", *range(1, 32), "Presenças", "Faltas", "Justificadas", "% frequência"]]
        for i in range(total):
            r = primeira + i
            aluno = alunos[i] if i < len(alunos) else {}
            intervalo = f"{c_dia1}{r}:{c_dia31}{r}"
            linhas.append([aluno.get("N", "") if aluno else "", str(aluno.get("Nome") or "").strip(), *[""] * 31,
                           f'=COUNTIF({intervalo},"P")', f'=COUNTIF({intervalo},"F")', f'=COUNTIF({intervalo},"J")',
                           f'=IF({c_pres}{r}+{c_falt}{r}+{c_just}{r}=0,"",{c_pres}{r}/({c_pres}{r}+{c_falt}{r}+{c_just}{r}))'])
        abas.append(Aba(
            nome=nome_de_aba(mes, usados), linhas=linhas,
            larguras=[5, 38] + [4] * 31 + [10, 8, 12, 13],
            formatos=[(f"{c_freq}{primeira}:{c_freq}{ultima}", "0%")],
            listas=[(f"{c_dia1}{primeira}:{c_dia31}{ultima}", ("P", "F", "J"))],
            mesclar=[f"A1:{c_freq}1"], negrito_linhas=[1, 4], congelar_linhas=4, congelar_colunas=2))
    return abas


# ───────────────────────────── modelo: Planilha das Turmas ──────────────────────

def _montar_planilha_turmas(ctx: Contexto) -> list[Aba]:
    """Uma aba por turma, no layout A–L da sincronização com o Google (src/automacao/sincroniza_sheets.py)."""
    from src.automacao import sincroniza_sheets as sh
    letras = list(sh.COLUNAS.items())                                # [(campo, letra)] na ordem A…L
    mapa = sh.mapa_abas()
    abas, usados = [], set()
    for turma in _turmas_do_contexto(ctx):
        linhas = [list(sh.CABECALHOS)]
        for aluno in alunos_da_turma(ctx, turma, incluir_transferidos=True):
            valores = sh.valores_do_aluno(aluno)
            linhas.append([valores.get(campo, "") for campo, _letra in letras])
        abas.append(Aba(nome=nome_de_aba(mapa.get(turma, turma), usados), linhas=linhas,
                        larguras=[5, 15, 12, 18, 40, 12, 8, 7, 8, 16, 28, 20], negrito_linhas=[1],
                        listas=[(f"I2:I{max(len(linhas) + LINHAS_EXTRAS, 60)}", ("M", "T"))], congelar_linhas=1))
    return abas


# ───────────────────────────── modelo: Listagem dos Alunos ──────────────────────

def _montar_listagem(ctx: Contexto) -> list[Aba]:
    cabecalho = ["Nº", "CGM", "Nome do aluno", "Data de nascimento", "Sexo", "Situação", "Data de matrícula"]
    abas, usados, resumo = [], set(), [["Turma", "Alunos na lista"]]
    for turma in _turmas_do_contexto(ctx):
        nome = nome_de_aba(turma, usados)
        alunos = alunos_da_turma(ctx, turma, incluir_transferidos=True)
        linhas = [cabecalho] + [[a.get("N", ""), str(a.get("CGM") or ""), str(a.get("Nome") or "").strip(), a.get("Data Nasc.", ""),
                                 a.get("Sexo", ""), "Transferido" if _transferido(a) else "Matriculado", a.get("Data Matricula", "")]
                                for a in alunos]
        abas.append(Aba(nome=nome, linhas=linhas, larguras=[5, 12, 40, 18, 12, 14, 18], negrito_linhas=[1], congelar_linhas=1,
                        formatos=[(f"B2:B{max(len(linhas) + LINHAS_EXTRAS, 60)}", "@")]))
        resumo.append([turma, f"=COUNTA({_aspas(nome)}!C2:C1000)"])
    return [Aba(nome=nome_de_aba("Resumo", usados), linhas=resumo, larguras=[34, 18], negrito_linhas=[1], congelar_linhas=1)] + abas


# ───────────────────────────── modelo: IMC ─────────────────────────────────────

def _montar_imc(ctx: Contexto) -> list[Aba]:
    """
    Peso e altura digitados; o IMC (kg/m²) é calculado. A classificação é escolhida numa lista, e NÃO calculada: para
    crianças ela depende da idade e do sexo (curvas de IMC-para-idade da OMS), não de faixas fixas de adulto.
    """
    cabecalho = ["Nº", "Nome do aluno", "Data de nascimento", "Sexo", "Data da medição", "Peso (kg)", "Altura (cm)", "IMC (kg/m²)",
                 "Classificação (IMC-para-idade)", "Observações"]
    abas, usados = [], set()
    for turma in _turmas_do_contexto(ctx):
        alunos = alunos_da_turma(ctx, turma)
        total = len(alunos) + LINHAS_EXTRAS
        linhas = [cabecalho]
        for i in range(total):
            r, a = i + 2, (alunos[i] if i < len(alunos) else {})
            linhas.append([a.get("N", ""), str(a.get("Nome") or "").strip() if a else "", a.get("Data Nasc.", "") if a else "",
                           a.get("Sexo", "") if a else "", "", "", "", f'=IF(OR(F{r}="",G{r}="",G{r}=0),"",ROUND(F{r}/((G{r}/100)^2),1))', "", ""])
        abas.append(Aba(nome=nome_de_aba(turma, usados), linhas=linhas, larguras=[5, 38, 18, 10, 16, 11, 12, 13, 30, 30],
                        formatos=[(f"H2:H{total + 1}", "0.0"), (f"F2:F{total + 1}", "0.0")],
                        listas=[(f"I2:I{total + 1}", CLASSIFICACOES_IMC)], negrito_linhas=[1], congelar_linhas=1, congelar_colunas=2))
    return abas


# ───────────────────────────── modelo: Previsão do próximo ano ──────────────────

ORIGENS_PREVISAO = ("Rematriculado", "Novo (pré-matrícula)", "Direcionado GEO")


def _montar_previsao(ctx: Contexto) -> list[Aba]:
    """
    Aba "Resumo" + UMA ABA POR TURMA do ano que vem (Infantil IV, Infantil V, 1º Ano…), com os nomes de quem a Previsão
    espera nela: rematriculados, novos da pré-matrícula e direcionados GEO. A turma é a SÉRIE (a seção A/B ainda não existe).
    """
    linhas_previsao = [l for l in (ctx.previsao.get("linhas") or []) if isinstance(l, dict)]
    por_turma: dict[str, list[dict]] = {}
    for l in linhas_previsao:
        por_turma.setdefault(str(l.get("turma") or "Sem turma"), []).append(l)
    escolhidas = list(ctx.selecionadas) if ctx.selecionadas else list(por_turma)
    faltando = [t for t in escolhidas if t not in por_turma]
    if faltando:
        raise ValueError(f"Turma(s) que não existem na previsão: {', '.join(faltando)}.")
    cabecalho = ["Nº", "CGM", "Nome do aluno", "Data de nascimento", "Origem", "Situação", "Turma atual", "Responsável", "Telefone"]
    usados: set = set()
    resumo = [["Turma", "Total", *ORIGENS_PREVISAO]]
    abas = []
    for turma in escolhidas:
        alunos = por_turma[turma]
        nome = nome_de_aba(turma, usados)
        linhas = [cabecalho] + [[i, str(a.get("cgm") or "") or "-", str(a.get("nome") or "").strip(), a.get("nascimento", ""),
                                 a.get("origem", ""), a.get("situacao", ""), a.get("turma_atual", ""), a.get("responsavel", ""),
                                 a.get("telefone", "")] for i, a in enumerate(alunos, start=1)]
        abas.append(Aba(nome=nome, linhas=linhas, larguras=[5, 12, 40, 18, 22, 22, 24, 30, 18], negrito_linhas=[1], congelar_linhas=1,
                        formatos=[(f"B2:B{max(len(linhas) + LINHAS_EXTRAS, 60)}", "@")]))
        resumo.append([turma, f"=COUNTA({_aspas(nome)}!C2:C1000)",
                       *[f'=COUNTIF({_aspas(nome)}!E2:E1000,"{o}")' for o in ORIGENS_PREVISAO]])
    ultima = len(resumo)
    resumo.append(["Total", *[f"=SUM({_coluna(c)}2:{_coluna(c)}{ultima})" for c in range(1, 2 + len(ORIGENS_PREVISAO))]])
    resumo_aba = Aba(nome=nome_de_aba("Resumo", usados), linhas=resumo, larguras=[34, 10, 16, 22, 18],
                     negrito_linhas=[1, ultima + 1], congelar_linhas=1)
    return [resumo_aba] + abas


# ───────────────────────────── modelos feitos em .json ──────────────────────────

def _modelo_de_json(bruto: dict, origem_arquivo: str) -> Modelo:
    """
    Formato (config/modelos_planilha/*.json):
        {"chave": "merenda", "nome": "Controle da merenda", "finalidade": "listagem_alunos", "versao": 1,
         "descricao": "...", "uma_turma": false, "uma_aba_por_turma": true,
         "abas": [{"nome": "Resumo", "cabecalhos": ["A", "B"], "larguras": [10, 20], "linhas_vazias": 30,
                   "formulas": {"C": "=IF(A{linha}=\\"\\",\\"\\",A{linha}*2)"}, "listas": [["B2:B60", ["Sim", "Não"]]]}]}
    Com "uma_aba_por_turma", a 1ª aba do arquivo é repetida para cada turma (e com "preencher_alunos": true as colunas
    "Nº" e "Nome" são preenchidas). `{linha}` nas fórmulas vira o nº da linha.
    """
    chave, nome, finalidade = str(bruto["chave"]).strip(), str(bruto["nome"]).strip(), str(bruto["finalidade"]).strip()
    if not re.fullmatch(r"[a-z0-9_]+", chave):
        raise ValueError("chave só pode ter letras minúsculas, números e _.")
    definicoes = bruto["abas"]
    por_turma, uma_turma = bool(bruto.get("uma_aba_por_turma")), bool(bruto.get("uma_turma"))

    def aba_de(defn: dict, titulo: str, alunos: list[dict], usados: set) -> Aba:
        cab = [str(c) for c in defn.get("cabecalhos", [])]
        n_linhas = max(int(defn.get("linhas_vazias", 0)), len(alunos) + (LINHAS_EXTRAS if alunos else 0))
        linhas = [cab] if cab else []
        inicio = len(linhas) + 1
        for i in range(n_linhas):
            r = inicio + i
            linha = [""] * len(cab)
            if i < len(alunos):
                for j, c in enumerate(cab):
                    if c.strip().casefold() in ("nº", "n", "numero", "número"):
                        linha[j] = alunos[i].get("N", "")
                    elif c.strip().casefold().startswith("nome"):
                        linha[j] = str(alunos[i].get("Nome") or "").strip()
            for letra, formula in (defn.get("formulas") or {}).items():
                posicao = sum((ord(ch) - 64) * 26 ** k for k, ch in enumerate(reversed(letra.upper()))) - 1
                while len(linha) <= posicao:
                    linha.append("")
                linha[posicao] = str(formula).replace("{linha}", str(r))
            linhas.append(linha)
        return Aba(nome=nome_de_aba(titulo, usados), linhas=linhas, larguras=[int(x) for x in defn.get("larguras", [])],
                   listas=[(str(i), tuple(str(o) for o in op)) for i, op in defn.get("listas", [])],
                   negrito_linhas=[1] if cab else [], congelar_linhas=1 if cab else 0)

    def montar(ctx: Contexto) -> list[Aba]:
        usados: set = set()
        if por_turma:
            return [aba_de(definicoes[0], t, alunos_da_turma(ctx, t) if bruto.get("preencher_alunos") else [], usados)
                    for t in _turmas_do_contexto(ctx)]
        alunos = alunos_da_turma(ctx, _exigir_turma(ctx)) if uma_turma and bruto.get("preencher_alunos") else []
        return [aba_de(d, str(d.get("nome") or "Planilha"), alunos, usados) for d in definicoes]

    return Modelo(chave=chave, nome=nome, finalidade=finalidade, montar=montar, descricao=str(bruto.get("descricao") or ""),
                  versao=int(bruto.get("versao") or 1), uma_turma=uma_turma, origem="escola")


# ───────────────────────────── os modelos padrão ───────────────────────────────

registrar_modelo(Modelo("chamada", "Chamada", "chamada", _montar_chamada, uma_turma=True,
                        descricao="Uma aba por mês (fevereiro a dezembro), alunos da turma, P/F/J por dia e totais de frequência."))
registrar_modelo(Modelo("planilha_turmas", "Planilha das Turmas", "planilha_turmas", _montar_planilha_turmas,
                        descricao="Uma aba por turma no layout que a atualização automática dos alunos usa (CGM, nome, status…)."))
registrar_modelo(Modelo("listagem_alunos", "Listagem dos Alunos", "listagem_alunos", _montar_listagem,
                        descricao="Uma aba por turma com os dados dos alunos e uma aba Resumo com a contagem de cada turma."))
registrar_modelo(Modelo("imc", "IMC", "imc", _montar_imc,
                        descricao="Uma aba por turma com peso, altura, IMC calculado e classificação escolhida numa lista."))
registrar_modelo(Modelo("previsao", "Previsão do próximo ano", "previsao", _montar_previsao, usa_previsao=True,
                        descricao="Uma aba por turma do ano que vem com os nomes (rematriculados, novos da pré-matrícula e direcionados GEO) e uma aba Resumo com a contagem."))

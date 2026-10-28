"""
opcoes_execucao.py — opções compartilhadas pelos scripts do AUTO SERE
======================================================================
Em vez de cada script reimplementar "qual turma?", "matriculados/transferidos?", "quais CGMs?" e
"modo de teste", essas escolhas vivem aqui, em UM lugar, e servem à interface web e à linha de
comando ao mesmo tempo:

    Interface (payload JSON)  ─┐
                               ├─►  Opcoes  ─►  selecionar_alunos(...)  /  argv_cli(...)
    Linha de comando (argparse)┘

Tudo aqui é função pura (sem rede, sem navegador, sem Flask), por isso é fácil de testar.

Regra de "matriculado/transferido" (a mesma que o projeto já usava): em turmas.json, o campo
"Situação" == "Transferido" (sem diferenciar maiúsculas) é transferido; qualquer outro valor é
matriculado.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Recursos que um script pode declarar no registro (src/comum/registro_scripts.py).
RECURSO_TURMA = "turma"
RECURSO_SITUACAO = "situacao"
RECURSO_CGM = "cgm"
RECURSO_TESTE = "teste"
RECURSO_ERROS = "erros"
RECURSO_DEBUG = "debug"       # modo de análise: o script guarda screenshots/detalhes de cada etapa

_CGM_VALIDO = re.compile(r"\d{5,12}")      # os CGMs reais têm 10 dígitos; aceita 5 a 12 para não ser rígido demais
_SEPARADORES_CGM = re.compile(r"[,;\s]+")  # vírgula, ponto e vírgula, espaços e quebras de linha


# ───────────────────────────────────────── texto ───────────────────────────────

def sem_acento(texto) -> str:
    base = unicodedata.normalize("NFD", str(texto or ""))
    return re.sub(r"\s+", " ", "".join(c for c in base if unicodedata.category(c) != "Mn")).strip().lower()


# ───────────────────────────────────────── CGM ─────────────────────────────────

@dataclass(frozen=True)
class ResultadoCgm:
    validos: tuple[str, ...]            # na ordem em que apareceram, sem repetição
    invalidos: tuple[str, ...]          # pedaços que não parecem um CGM
    repetidos: int                      # quantos CGMs repetidos foram descartados


def analisar_cgms(entrada) -> ResultadoCgm:
    """
    Aceita texto (um CGM por linha, ou separados por vírgula, ponto e vírgula ou espaço — e qualquer
    mistura disso) ou uma lista. Tira espaços, remove repetidos e separa os que têm formato inválido.

        "123456789, 987654321;\\n456789123\\n111222333"  →  4 válidos
    """
    if entrada is None:
        pedacos: list[str] = []
    elif isinstance(entrada, (list, tuple, set)):
        pedacos = [str(x).strip() for x in entrada]
    else:
        pedacos = _SEPARADORES_CGM.split(str(entrada).strip())

    validos: list[str] = []
    invalidos: list[str] = []
    vistos: set[str] = set()
    repetidos = 0
    for p in pedacos:
        if not p:
            continue
        if not _CGM_VALIDO.fullmatch(p):
            if p not in invalidos:
                invalidos.append(p)
            continue
        if p in vistos:
            repetidos += 1
            continue
        vistos.add(p)
        validos.append(p)
    return ResultadoCgm(tuple(validos), tuple(invalidos), repetidos)


# ───────────────────────────────────────── turmas ──────────────────────────────

def rotulo_grupo(nome_turma: str) -> str:
    """Nome do "ano" a que a turma pertence: tira a letra final ("3º Ano Integral B" → "3º Ano Integral")."""
    return re.sub(r"\s+[A-Za-z]$", "", str(nome_turma).strip()).strip()


def agrupar_turmas(nomes: Iterable[str]) -> dict[str, list[str]]:
    """{"3º Ano Integral": ["3º Ano Integral A", "3º Ano Integral B"], ...} na ordem em que aparecem."""
    grupos: dict[str, list[str]] = {}
    for nome in nomes:
        grupos.setdefault(rotulo_grupo(nome), []).append(nome)
    return grupos


def resolver_turmas(valores: Iterable[str], nomes_turmas: Iterable[str]) -> list[str]:
    """
    Converte o que o usuário digitou/escolheu nos nomes reais das turmas. Lista vazia (ou "todas") = todas.
    Cada valor pode ser:
      • o nome completo da turma ("5º Ano A", sem diferenciar maiúsculas/acentos);
      • o nome do ano ("5º Ano" → todas as turmas do 5º ano);
      • o início do nome ("5" → todas as turmas que começam com 5; "infantil 4" idem).
    Levanta ValueError (com o valor) se algum não corresponder a nenhuma turma.
    """
    nomes = list(nomes_turmas)
    pedidos = [str(v).strip() for v in (valores or []) if str(v).strip()]
    if not pedidos or any(sem_acento(v) in ("todas", "todos", "*") for v in pedidos):
        return nomes

    grupos = {sem_acento(g): ts for g, ts in agrupar_turmas(nomes).items()}
    por_nome = {sem_acento(n): n for n in nomes}
    escolhidas: list[str] = []

    def somar(ts: Iterable[str]) -> None:
        for t in ts:
            if t not in escolhidas:
                escolhidas.append(t)

    for valor in pedidos:
        n = sem_acento(valor)
        if n in por_nome:
            somar([por_nome[n]])
        elif n in grupos:
            somar(grupos[n])
        else:
            # início do nome; o (?!\d) evita que "1" case com "10º..."
            achadas = [t for t in nomes if re.match(rf"{re.escape(n)}(?!\d)", sem_acento(t))]
            if not achadas:
                raise ValueError(f"Turma não encontrada: {valor}")
            somar(achadas)
    return escolhidas


# ───────────────────────────────────────── seleção de alunos ───────────────────

def eh_transferido(aluno: dict) -> bool:
    """Mesma regra do analisa_arquivos_sere: Situação == "Transferido" (sem diferenciar maiúsculas)."""
    return str(aluno.get("Situação", aluno.get("Situacao", ""))).strip().lower() == "transferido"


@dataclass
class Selecao:
    alunos: list[dict] = field(default_factory=list)       # {"CGM","Nome","Turma","Situacao"}, sem repetir CGM
    turmas: list[str] = field(default_factory=list)        # turmas efetivamente envolvidas
    matriculados: int = 0
    transferidos: int = 0
    cgms_nao_encontrados: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.alunos)


def selecionar_alunos(
    turmas_json: dict,
    *,
    turmas: Iterable[str] = (),
    matriculados: bool = True,
    transferidos: bool = False,
    cgms: Iterable[str] = (),
) -> Selecao:
    """
    Quem será processado, a partir do conteúdo de turmas.json.
      • Com `cgms`: só esses alunos (de qualquer turma/situação), como no modo --aluno;
        os que não existem em turmas.json vão em `cgms_nao_encontrados`.
      • Sem `cgms`: alunos das `turmas` (vazio = todas) cuja situação foi marcada.
    Nunca repete um CGM (vale a primeira turma em que aparece).
    """
    cgms = [str(c).strip() for c in cgms if str(c).strip()]
    alvo_turmas = resolver_turmas(turmas, turmas_json.keys())
    sel = Selecao()
    vistos: set[str] = set()
    turmas_usadas: list[str] = []

    for nome_turma, alunos_turma in turmas_json.items():
        if not cgms and nome_turma not in alvo_turmas:
            continue
        for aluno in alunos_turma:
            cgm = str(aluno.get("CGM", "")).strip()
            if not cgm or cgm in vistos:
                continue
            transferido = eh_transferido(aluno)
            if cgms:
                if cgm not in cgms:
                    continue
            elif transferido and not transferidos:
                continue
            elif not transferido and not matriculados:
                continue
            vistos.add(cgm)
            sel.alunos.append({
                "CGM": cgm,
                "Nome": aluno.get("Nome", ""),
                "Turma": nome_turma,
                "Situacao": "Transferido" if transferido else "Matriculado",
            })
            if transferido:
                sel.transferidos += 1
            else:
                sel.matriculados += 1
            if nome_turma not in turmas_usadas:
                turmas_usadas.append(nome_turma)

    sel.turmas = turmas_usadas
    sel.cgms_nao_encontrados = [c for c in dict.fromkeys(cgms) if c not in vistos]
    return sel


def descrever_selecao(sel: Selecao, cgms_pedidos: int = 0) -> str:
    """A frase da prévia ("181 aluno(s) — 181 matriculado(s) — em 8 turma(s).") — a mesma na tela e na linha de comando."""
    if cgms_pedidos:
        txt = f"{sel.total} de {cgms_pedidos} CGM(s) encontrado(s) em turmas.json"
        if sel.cgms_nao_encontrados:
            txt += "; não encontrado(s): " + ", ".join(sel.cgms_nao_encontrados[:8]) + (" …" if len(sel.cgms_nao_encontrados) > 8 else "")
        return txt + "."
    partes = []
    if sel.matriculados:
        partes.append(f"{sel.matriculados} matriculado(s)")
    if sel.transferidos:
        partes.append(f"{sel.transferidos} transferido(s)")
    return f"{sel.total} aluno(s) — {' e '.join(partes) or 'nenhum'} — em {len(sel.turmas)} turma(s)."


def filtrar_turmas_por_situacao(turmas_json: dict, *, matriculados: bool = True, transferidos: bool = False) -> dict:
    """
    Cópia de turmas.json só com os alunos da(s) situação(ões) marcada(s) — para os scripts que recebem o
    dicionário de turmas inteiro (validar, documentos, limpeza, espec). Mantém todas as turmas, mesmo vazias.
    """
    def serve(aluno: dict) -> bool:
        return transferidos if eh_transferido(aluno) else matriculados

    return {nome: [a for a in alunos if serve(a)] for nome, alunos in turmas_json.items()}


# ───────────────────────────────────────── opções ──────────────────────────────

@dataclass(frozen=True)
class Opcoes:
    turmas: tuple[str, ...] = ()        # vazio = todas
    matriculados: bool = True
    transferidos: bool = False
    cgms: tuple[str, ...] = ()
    modo_teste: bool = False
    erros: bool = False                 # reprocessar só o que falhou na última execução
    debug: bool = False                 # modo de análise (screenshots de cada etapa), onde o script tiver


def opcoes_do_payload(payload: dict, recursos: Iterable[str], nomes_turmas: Iterable[str] = (), *,
                      cgm_obrigatorio: bool = False) -> Opcoes:
    """
    Converte o JSON da tela em Opcoes, validando só o que o script declarou usar (`recursos`).
    Levanta ValueError com mensagem pronta para mostrar ao usuário.

    CGM: com o recurso "cgm", o campo pode ser opcional (em branco = vale turma/situação, como no
    analisa_sere) ou obrigatório (`cgm_obrigatorio=True`, como em "Alunos por CGM").
    """
    recursos = set(recursos)
    p = payload or {}

    turmas: tuple[str, ...] = ()
    if RECURSO_TURMA in recursos:
        pedidas = p.get("turmas") or []
        if isinstance(pedidas, str):
            pedidas = [pedidas]
        turmas = tuple(resolver_turmas(pedidas, nomes_turmas)) if pedidas else ()

    matriculados, transferidos = True, False
    if RECURSO_SITUACAO in recursos:
        matriculados = bool(p.get("matriculados", True))
        transferidos = bool(p.get("transferidos", False))
        if not matriculados and not transferidos:
            raise ValueError("Marque ao menos uma opção: Matriculados ou Transferidos.")

    cgms: tuple[str, ...] = ()
    if RECURSO_CGM in recursos:
        r = analisar_cgms(p.get("cgms_texto", p.get("cgms")))
        if r.invalidos:
            raise ValueError("CGM com formato inválido: " + ", ".join(r.invalidos[:5]) + (" …" if len(r.invalidos) > 5 else "")
                             + " (use só números, de 5 a 12 dígitos).")
        if not r.validos and cgm_obrigatorio:
            raise ValueError("Informe ao menos um CGM.")
        cgms = r.validos

    return Opcoes(
        turmas=turmas,
        matriculados=matriculados,
        transferidos=transferidos,
        cgms=cgms,
        modo_teste=bool(p.get("modo_teste", False)) if RECURSO_TESTE in recursos else False,
        erros=bool(p.get("erros", False)) if RECURSO_ERROS in recursos else False,
        debug=bool(p.get("debug", False)) if RECURSO_DEBUG in recursos else False,
    )


# ───────────────────────────────────────── linha de comando ────────────────────

def adicionar_argumentos(parser, *, turma=True, situacao=True, cgm=True, teste=False, erros=False, debug=False) -> None:
    """
    Declara no argparse as MESMAS opções que a interface monta:
      --turma [NOME ...]   (sem valor = menu interativo, como sempre foi)
      --matriculados  --transferidos  --cgm N [N ...]  --teste  --erros
    `--erros` só é declarado se o script ainda não tiver o dele (erros=True).
    """
    if turma:
        parser.add_argument("--turma", nargs="*", default=None, metavar="NOME",
                            help="Turma(s) a processar: nome completo, nome do ano ('5º Ano') ou início ('5'). "
                                 "Sem valor, abre um menu interativo.")
    if situacao:
        parser.add_argument("--matriculados", action="store_true", help="Inclui os alunos matriculados.")
        parser.add_argument("--transferidos", action="store_true", help="Inclui os alunos transferidos.")
    if cgm:
        parser.add_argument("--cgm", nargs="+", default=None, metavar="CGM",
                            help="Processa só estes CGMs (aceita também '123,456;789').")
    if teste:
        parser.add_argument("--teste", action="store_true", help="Modo de teste.")
    if erros:
        parser.add_argument("--erros", action="store_true", help="Reprocessa só os que falharam.")
    if debug:
        parser.add_argument("--debug", action="store_true", help="Modo de análise: salva screenshots de cada etapa.")


def opcoes_do_argparse(ns) -> Opcoes:
    """Opcoes a partir do resultado de parse_args() de um parser montado com adicionar_argumentos()."""
    cgm_bruto = getattr(ns, "cgm", None)
    cgms: tuple[str, ...] = ()
    if cgm_bruto:
        r = analisar_cgms(" ".join(cgm_bruto))
        if r.invalidos:
            raise ValueError("CGM com formato inválido: " + ", ".join(r.invalidos))
        cgms = r.validos
    m, t = bool(getattr(ns, "matriculados", False)), bool(getattr(ns, "transferidos", False))
    return Opcoes(
        turmas=tuple(getattr(ns, "turma", None) or ()),
        matriculados=m or not t,            # sem nenhuma das duas flags = só matriculados (padrão histórico)
        transferidos=t,
        cgms=cgms,
        modo_teste=bool(getattr(ns, "teste", False)),
        erros=bool(getattr(ns, "erros", False)),
        debug=bool(getattr(ns, "debug", False)),
    )


def argv_cli(opcoes: Opcoes, recursos: Iterable[str]) -> list[str]:
    """Os argumentos de linha de comando equivalentes às opções da tela (só dos recursos que o script usa)."""
    recursos = set(recursos)
    argv: list[str] = []
    if RECURSO_CGM in recursos and opcoes.cgms:
        argv += ["--cgm", *opcoes.cgms]
    if RECURSO_TURMA in recursos and opcoes.turmas:
        argv += ["--turma", *opcoes.turmas]
    if RECURSO_SITUACAO in recursos:
        if opcoes.matriculados:
            argv.append("--matriculados")
        if opcoes.transferidos:
            argv.append("--transferidos")
    if RECURSO_TESTE in recursos and opcoes.modo_teste:
        argv.append("--teste")
    if RECURSO_ERROS in recursos and opcoes.erros:
        argv.append("--erros")
    if RECURSO_DEBUG in recursos and opcoes.debug:
        argv.append("--debug")
    return argv

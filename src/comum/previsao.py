"""
previsao.py — "Previsão <ano letivo>": quem deve estar na escola no ano que vem
================================================================================

Dois assuntos, os dois do ano letivo SEGUINTE ao que está em uso:

1. NOME DO ARQUIVO. A coleta da pré-matrícula do próximo ano (alvo "proximo" de
   ``src.automacao.pre_matricula``) grava em ``dados/<ano em uso>/previsao_alunos_<ano+1>.json``
   (ex.: ``previsao_alunos_2027.json``). Antes se chamava ``pre_matricula_<ano+1>.json``; esse
   nome antigo é renomeado sozinho na primeira vez (``migrar_nome_antigo``), sem perder nada.
   O ``pre_matricula.json`` (ano em uso) NÃO muda de nome.

2. A PREVISÃO. ``montar_previsao()`` junta, numa lista só:
     * REMATRICULADOS — quem a rematrícula confirmou com sucesso (``rematriculas_sucesso.json``);
     * NOVOS — quem veio da pré-matrícula do próximo ano e ainda tem vaga: matriculado
       (vaga confirmada) ou pendente (aguardando). Cancelados ficam de fora.
   Quem aparece nas duas fontes conta UMA vez, como rematriculado (CGM ou nome + nascimento).

   A turma do rematriculado é a do PRÓXIMO ano: o ``rematriculas_sucesso.json`` guarda a turma em que o aluno está
   AGORA (ex.: \"1º Ano - A\"), então a previsão o promove à série seguinte (\"2º Ano\"); a seção (letra) não é
   prevista, pois as turmas do ano que vem ainda não foram formadas. A turma de hoje fica em ``turma_atual``.

3. QUEM FICOU DE FORA. ``analisar_fora_da_rematricula`` cruza ``turmas.json`` (alunos matriculados agora; transferidos
   durante o ano são ignorados) com a previsão e lista quem não está nela, com o motivo provável (erro na rematrícula,
   pré-matrícula em outra escola, pré-matrícula cancelada ou nenhum registro). Concluintes da última série da escola
   vêm à parte: não são esperados na rematrícula.

Só lê arquivos; não grava nada (exceto a renomeação única do nome antigo, pedida explicitamente
por ``carregar_previsao_alunos``).
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from src.comum.arquivos_json import carregar_json

PREFIXO_ARQUIVO = "previsao_alunos_"
PREFIXO_ARQUIVO_ANTIGO = "pre_matricula_"

ARQUIVO_REMATRICULADOS = "rematriculas_sucesso.json"
ARQUIVO_TURMAS = "turmas.json"

TIPO_REMATRICULADO = "rematriculado"
TIPO_NOVO = "novo"

SITUACAO_MATRICULADO = "matriculado"
SITUACAO_PENDENTE = "pendente"
SITUACAO_CANCELADO = "cancelado"


def nome_arquivo(ano_letivo) -> str:
    """``previsao_alunos_2027.json`` para o ano letivo 2027 (o ano da previsão, não o que está em uso)."""
    return f"{PREFIXO_ARQUIVO}{int(ano_letivo)}.json"


def nome_arquivo_antigo(ano_letivo) -> str:
    """Nome usado antes da mudança (``pre_matricula_2027.json``). Só para migrar/ler arquivos já gravados."""
    return f"{PREFIXO_ARQUIVO_ANTIGO}{int(ano_letivo)}.json"


def migrar_nome_antigo(pasta, ano_letivo) -> Optional[Path]:
    """
    Se existe ``pre_matricula_<ano>.json`` e ainda NÃO existe ``previsao_alunos_<ano>.json``, renomeia o antigo
    (``os.replace``: atômico, o conteúdo não é tocado). Se os dois existem, nada é feito e o novo vale: o antigo
    fica na pasta para conferência manual (nunca é apagado nem mesclado às cegas).

    Devolve o caminho do novo arquivo se renomeou, senão None. Falha de sistema de arquivos não derruba quem chamou.
    """
    pasta = Path(pasta)
    antigo, novo = pasta / nome_arquivo_antigo(ano_letivo), pasta / nome_arquivo(ano_letivo)
    if novo.exists() or not antigo.exists():
        return None
    try:
        os.replace(antigo, novo)
    except OSError:
        return None
    return novo


def caminho_previsao_alunos(pasta, ano_letivo) -> Path:
    return Path(pasta) / nome_arquivo(ano_letivo)


def carregar_previsao_alunos(pasta, ano_letivo) -> dict:
    """
    Lê ``previsao_alunos_<ano>.json`` (migrando o nome antigo antes). Arquivo inexistente -> {}. Arquivo ilegível ->
    ArquivoJsonCorrompidoError (o arquivo não é tocado).
    """
    migrar_nome_antigo(pasta, ano_letivo)
    return carregar_json(caminho_previsao_alunos(pasta, ano_letivo), dict, dict)


# ──────────────────────────────── utilidades de comparação ────────────────────────────────

def _sem_acento(texto: Any) -> str:
    base = unicodedata.normalize("NFD", str(texto or ""))
    return re.sub(r"\s+", " ", "".join(c for c in base if unicodedata.category(c) != "Mn")).strip().lower()


def _so_digitos(texto: Any) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _nascimento(texto: Any) -> str:
    """'05/03/2020', '2020-03-05' ou '05/03/2020 00:00' -> '05/03/2020' (vazio se não reconhecer)."""
    t = str(texto or "").strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return ""


def _chave_pessoa(nome: Any, nascimento: Any) -> str:
    """Nome sem acento + nascimento. Sem nome não há chave (nunca casa com ninguém)."""
    n = _sem_acento(nome)
    return f"{n}|{_nascimento(nascimento)}" if n else ""


def _ler_lista(pasta: Path, nome: str) -> list:
    """Lista de um JSON de trabalho; ausente -> []. Ilegível -> ArquivoJsonCorrompidoError."""
    dados = carregar_json(pasta / nome, list, list)
    return [d for d in dados if isinstance(d, dict)]


# ──────────────────────────────── série / turma do ano seguinte ────────────────────────────────

_RE_INFANTIL = re.compile(r"infantil\s*(iv|v|4|5)\b", re.IGNORECASE)
_RE_ANO = re.compile(r"(\d+)\s*[º°ªoO]?\s*ano\b", re.IGNORECASE)
ORDEM_DESCONHECIDA = 99


def _decompor_turma(nome: Any) -> Optional[tuple[int, bool]]:
    """
    (ordem da série, é integral) ou None se o nome não tem série reconhecível.
    Ordem: Infantil IV = -2, Infantil V = -1, N º Ano = N. A seção (letra) é descartada.
    """
    t = str(nome or "").strip()
    m = _RE_INFANTIL.search(t)
    if m:
        ordem = -2 if m.group(1).lower() in ("iv", "4") else -1
    else:
        m = _RE_ANO.search(t)
        if not m:
            return None
        ordem = int(m.group(1))
    return ordem, bool(re.search(r"integral", t[m.end():], re.IGNORECASE))


def _rotulo_serie(ordem: int, integral: bool = False) -> str:
    if ordem == -2:
        return "Infantil IV"
    if ordem == -1:
        return "Infantil V"
    return f"{ordem}º Ano" + (" Integral" if integral else "")


def rotulo_serie_da_turma(nome: Any) -> str:
    """'1º Ano - A' / '1º Ano do Ensino Fundamental' -> '1º Ano'; 'INFANTIL 4' -> 'Infantil IV'. Sem série: o texto como veio."""
    d = _decompor_turma(nome)
    return _rotulo_serie(*d) if d else str(nome or "").strip()


def proxima_turma(nome: Any) -> tuple[str, bool]:
    """
    Turma (série) do ano seguinte para quem hoje está em ``nome``, e se o nome foi reconhecido.
    Infantil IV -> Infantil V -> 1º Ano -> 2º Ano ... Mantém \"Integral\"; descarta a seção (A, B...).
    Nome sem série reconhecível volta igual, com False.
    """
    d = _decompor_turma(nome)
    if not d:
        return str(nome or "").strip(), False
    ordem, integral = d
    return _rotulo_serie(1 if ordem == -1 else ordem + 1, integral), True


def _ordem_turma(nome: Any) -> int:
    d = _decompor_turma(nome)
    return d[0] if d else ORDEM_DESCONHECIDA


# ──────────────────────────────── a previsão ────────────────────────────────

def situacao_da_pre_matricula(opcoes) -> str:
    """matriculado = alguma opção com situação que não é CANCELADO; cancelado = todas as preenchidas canceladas; senão pendente."""
    com_situacao = [o for o in (opcoes or []) if isinstance(o, dict) and str(o.get("situacao") or "").strip()]
    if not com_situacao:
        return SITUACAO_PENDENTE
    if any(not str(o["situacao"]).upper().startswith("CANCELADO") for o in com_situacao):
        return SITUACAO_MATRICULADO
    return SITUACAO_CANCELADO


def _indice_intencoes(turmas_intencao) -> dict[str, dict]:
    """{cpf ou tr_id: item mais válido da fila}. Tentativa antiga (substituída por outra) é ignorada: vale a última."""
    indice: dict[str, dict] = {}
    for turma, lista in (turmas_intencao.items() if isinstance(turmas_intencao, dict) else []):
        for item in lista if isinstance(lista, list) else []:
            if not isinstance(item, dict) or item.get("substituido_por_nova_tentativa"):
                continue
            for chave in {str(item.get("cpf") or "").strip(), str(item.get("tr_id") or "").strip()} - {""}:
                indice.setdefault(chave, {**item, "_turma": turma})
    return indice


def _novos_da_pre_matricula(previsao_alunos: dict) -> list[dict]:
    """
    Alunos da pré-matrícula do próximo ano que ainda contam (matriculado ou pendente), sem duplicar CPF.

    Fontes, nesta ordem de preferência: ``cadastros`` (dados completos + situação das escolhas) e, para quem está na
    fila mas ainda não teve o cadastro coletado, o item de ``turmas_intencao`` (situação pendente, só nome/CPF).
    """
    cadastros = previsao_alunos.get("cadastros") if isinstance(previsao_alunos.get("cadastros"), dict) else {}
    intencoes = _indice_intencoes(previsao_alunos.get("turmas_intencao"))
    saida: list[dict] = []
    vistos: set[str] = set()

    for cid, c in cadastros.items():
        if not isinstance(c, dict):
            continue
        cpf = str(c.get("cpf") or cid).strip()
        escolhas = c.get("escolas_escolhidas") if isinstance(c.get("escolas_escolhidas"), dict) else {}
        opcoes = [o for o in (escolhas.get("opcoes") or []) if isinstance(o, dict)]
        intencao = intencoes.get(cpf) or intencoes.get(str(c.get("tr_id") or "").strip()) or {}
        # O cadastro manda sobre a fila, inclusive quando decide EXCLUIR o aluno: marca como visto antes de qualquer descarte.
        vistos.update({cpf, str(c.get("tr_id") or "").strip()} - {""})
        if c.get("cadastro_refeito_outra_escola") or intencao.get("cadastro_refeito_outra_escola"):
            continue
        situacao = situacao_da_pre_matricula(opcoes)
        if situacao == SITUACAO_CANCELADO:
            continue
        # Saiu da lista do site na última coleta e a Etapa 4 ainda não confirmou o que houve (a situação gravada na
        # fila é só a presunção "Cancelado"): não dá para afirmar que ele fica, então não entra na previsão.
        if situacao == SITUACAO_PENDENTE and intencao.get("presente_na_ultima_coleta") is False:
            continue
        vinculo = c.get("vinculo_base_abc") if isinstance(c.get("vinculo_base_abc"), dict) else {}
        saida.append({
            "nome": str(c.get("nome_aluno") or intencao.get("nome") or "").strip(),
            "nascimento": _nascimento(c.get("data_nascimento")),
            "cgm": str(vinculo.get("cgm") or "").strip(),
            "cpf": cpf,
            "turma": str(escolhas.get("turma") or intencao.get("_turma") or c.get("turma_matriculada") or "").strip(),
            "situacao": situacao,
            "responsavel": str(c.get("nome_responsavel") or "").strip(),
            "telefone": str(c.get("telefone") or "").strip(),
            "escola_origem": str(vinculo.get("escola") or "").strip(),
            "turma_origem": str(vinculo.get("turma") or "").strip(),
            "posicao": str(intencao.get("pos") or "").strip(),
        })

    for chave, item in intencoes.items():
        cpf = str(item.get("cpf") or "").strip()
        tr_id = str(item.get("tr_id") or "").strip()
        if chave in vistos or cpf in vistos or tr_id in vistos:
            continue
        if item.get("cadastro_refeito_outra_escola"):
            continue
        situacao_registrada = str(item.get("situacao") or "").strip()
        saiu_da_fila = item.get("presente_na_ultima_coleta") is False
        if situacao_registrada.upper().startswith("CANCELADO"):
            continue            # cancelado (real ou presumido): fora
        if situacao_registrada:
            situacao = SITUACAO_MATRICULADO
        elif saiu_da_fila:
            continue            # saiu da fila sem situação confirmada: não dá para afirmar que ficou
        else:
            situacao = SITUACAO_PENDENTE
        vinculo = item.get("vinculo_base_abc") if isinstance(item.get("vinculo_base_abc"), dict) else {}
        saida.append({
            "nome": str(item.get("nome") or "").strip(), "nascimento": "", "cgm": str(vinculo.get("cgm") or "").strip(),
            "cpf": cpf, "turma": str(item.get("_turma") or "").strip(), "situacao": situacao, "responsavel": "",
            "telefone": "", "escola_origem": str(vinculo.get("escola") or "").strip(),
            "turma_origem": str(vinculo.get("turma") or "").strip(), "posicao": str(item.get("pos") or "").strip(),
        })
        vistos.update({chave, cpf, tr_id} - {""})
    return saida


def _alunos_atuais(pasta: Path) -> tuple[set[str], set[str]]:
    """(CGMs, chaves nome+nascimento) de quem está em turmas.json agora; serve para avisar 'já é aluno da escola'."""
    cgms: set[str] = set()
    chaves: set[str] = set()
    try:
        turmas = carregar_json(pasta / ARQUIVO_TURMAS, dict, dict)
    except Exception:                                    # noqa: BLE001 — é só um aviso extra; nunca derruba a previsão
        return cgms, chaves
    for alunos in turmas.values():
        for a in alunos if isinstance(alunos, list) else []:
            if not isinstance(a, dict):
                continue
            if str(a.get("CGM") or "").strip():
                cgms.add(str(a["CGM"]).strip())
            k = _chave_pessoa(a.get("Nome"), a.get("Data Nasc.") or a.get("Data Nascimento"))
            if k:
                chaves.add(k)
    return cgms, chaves


# ──────────────────────────────── quem ficou de fora da rematrícula ────────────────────────────────

ARQUIVO_ERROS_REMATRICULA = "rematriculas_erro.json"
ARQUIVO_ALUNOS_COMPLETO = "alunos_completo.json"

CAT_ERRO = "erro_rematricula"
CAT_OUTRA_ESCOLA = "outra_escola"
CAT_CANCELOU = "cancelou"
CAT_SEM_REGISTRO = "sem_registro"
CAT_CONCLUINTE = "concluinte"


def _registros_turmas(pasta: Path) -> Optional[list[dict]]:
    """
    Alunos de turmas.json como {cgm, nome, nascimento, turma, situacao, ativo}. None se o arquivo não existe ou está
    ilegível. ``ativo`` = Situação contém \"matriculado\" (mesma regra da tela Turmas); transferido nunca é ativo.
    """
    if not (pasta / ARQUIVO_TURMAS).exists():
        return None
    try:
        turmas = carregar_json(pasta / ARQUIVO_TURMAS, dict, dict)
    except Exception:                                    # noqa: BLE001 — informação extra; nunca derruba a previsão
        return None
    saida: list[dict] = []
    for turma, alunos in turmas.items():
        for a in alunos if isinstance(alunos, list) else []:
            if not isinstance(a, dict):
                continue
            sit = str(a.get("Situação", a.get("Situacao", "")) or "").strip()
            sit_l = sit.lower()
            saida.append({
                "cgm": str(a.get("CGM") or "").strip(), "nome": str(a.get("Nome") or "").strip(),
                "nascimento": _nascimento(a.get("Data Nasc.") or a.get("Data Nascimento")),
                "turma": str(turma).strip(), "situacao": sit, "ativo": "matriculado" in sit_l and "transf" not in sit_l,
            })
    return saida


def _contatos(pasta: Path) -> dict[str, dict]:
    """{cgm: {responsavel, telefone}} de alunos_completo.json, se existir (só ajuda a achar a família; nunca obrigatório)."""
    try:
        completo = carregar_json(pasta / ARQUIVO_ALUNOS_COMPLETO, dict, dict)
    except Exception:                                    # noqa: BLE001
        return {}
    saida: dict[str, dict] = {}
    for cgm, d in completo.items():
        if not isinstance(d, dict):
            continue
        saida[str(cgm).strip()] = {
            "responsavel": str(d.get("nome_responsavel") or d.get("nome_mae") or "").strip(),
            "telefone": str(d.get("cel_responsavel") or d.get("cel_mae") or d.get("fone_residencial") or "").strip(),
        }
    return saida


def _saidas_da_pre_matricula(previsao_alunos: dict) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """
    Quem pediu pré-matrícula do próximo ano mas NÃO ficou: ({cgm: (categoria, detalhe)}, {chave nome+nascimento: ...}).
    Categorias: outra escola (cadastro refeito em outra escola) e cancelou (cancelado ou saiu da fila sem confirmação).
    """
    por_cgm: dict[str, tuple[str, str]] = {}
    por_chave: dict[str, tuple[str, str]] = {}
    cadastros = previsao_alunos.get("cadastros") if isinstance(previsao_alunos.get("cadastros"), dict) else {}
    intencoes = _indice_intencoes(previsao_alunos.get("turmas_intencao"))

    def anotar(cgm: str, chave: str, par: tuple[str, str]) -> None:
        if cgm:
            por_cgm.setdefault(cgm, par)
        if chave:
            por_chave.setdefault(chave, par)

    for cid, c in cadastros.items():
        if not isinstance(c, dict):
            continue
        cpf = str(c.get("cpf") or cid).strip()
        intencao = intencoes.get(cpf) or intencoes.get(str(c.get("tr_id") or "").strip()) or {}
        escolhas = c.get("escolas_escolhidas") if isinstance(c.get("escolas_escolhidas"), dict) else {}
        situacao = situacao_da_pre_matricula([o for o in (escolhas.get("opcoes") or []) if isinstance(o, dict)])
        vinculo = c.get("vinculo_base_abc") if isinstance(c.get("vinculo_base_abc"), dict) else {}
        cgm = str(vinculo.get("cgm") or "").strip()
        chave = _chave_pessoa(c.get("nome_aluno") or intencao.get("nome"), c.get("data_nascimento"))
        if c.get("cadastro_refeito_outra_escola") or intencao.get("cadastro_refeito_outra_escola"):
            anotar(cgm, chave, (CAT_OUTRA_ESCOLA, "Refez o cadastro da pré-matrícula para outra escola"))
        elif situacao == SITUACAO_CANCELADO:
            anotar(cgm, chave, (CAT_CANCELOU, "Pré-matrícula cancelada"))
        elif situacao == SITUACAO_PENDENTE and intencao.get("presente_na_ultima_coleta") is False:
            anotar(cgm, chave, (CAT_CANCELOU, "Saiu da fila da pré-matrícula sem confirmação de vaga"))

    for item in intencoes.values():
        vinculo = item.get("vinculo_base_abc") if isinstance(item.get("vinculo_base_abc"), dict) else {}
        cgm = str(vinculo.get("cgm") or "").strip()
        if not cgm:
            continue                                      # sem CGM nem nascimento não dá para ligar com segurança a um aluno
        if item.get("cadastro_refeito_outra_escola"):
            anotar(cgm, "", (CAT_OUTRA_ESCOLA, "Refez o cadastro da pré-matrícula para outra escola"))
        elif str(item.get("situacao") or "").upper().startswith("CANCELADO"):
            anotar(cgm, "", (CAT_CANCELOU, "Pré-matrícula cancelada"))
    return por_cgm, por_chave


def _chave_ordem(l: dict) -> tuple:
    return (_ordem_turma(l.get("turma")), _sem_acento(l.get("turma")), _sem_acento(l.get("nome")))


def analisar_fora_da_rematricula(pasta: Path, linhas_previsao: list[dict], previsao_alunos: dict) -> dict:
    """
    Alunos MATRICULADOS hoje (turmas.json) que não estão na previsão: não rematricularam nem entraram pela pré-matrícula.
    Transferidos durante o ano ficam de fora da análise. Quem está na última série da escola (maior série entre os
    matriculados) é ``concluinte``: sai porque terminou a etapa, não por ter deixado de rematricular.

    Cada linha: {cgm, nome, nascimento, turma_atual, turma_prevista, categoria, motivo, tentativas, responsavel, telefone}.
    ``resumo_series``: por série de hoje, {serie, ativos, na_previsao, fora, concluintes}.
    """
    registros = _registros_turmas(pasta)
    if registros is None:
        return {"disponivel": False, "ultima_serie": None, "linhas": [], "resumo_series": [],
                "contagem": {"total": 0, "ativos": 0, CAT_ERRO: 0, CAT_OUTRA_ESCOLA: 0, CAT_CANCELOU: 0,
                             CAT_SEM_REGISTRO: 0, "concluintes": 0}}

    # uma pessoa conta uma vez (CGM, ou nome + nascimento sem CGM); o registro matriculado vale sobre o transferido
    pessoas: dict[str, dict] = {}
    for r in registros:
        id_ = r["cgm"] or _chave_pessoa(r["nome"], r["nascimento"])
        if not id_:
            continue
        if id_ not in pessoas or (r["ativo"] and not pessoas[id_]["ativo"]):
            pessoas[id_] = r
    ativos = [r for r in pessoas.values() if r["ativo"]]

    ordens = [o for o in (_ordem_turma(r["turma"]) for r in ativos) if o != ORDEM_DESCONHECIDA and o > 0]
    ultima = max(ordens) if ordens else None

    cgms_prev = {l["cgm"] for l in linhas_previsao if l.get("cgm")}
    chaves_prev = {k for l in linhas_previsao if (k := _chave_pessoa(l.get("nome"), l.get("nascimento")))}
    saidas_cgm, saidas_chave = _saidas_da_pre_matricula(previsao_alunos)
    try:
        erros = {str(e.get("cgm") or "").strip(): e for e in _ler_lista(pasta, ARQUIVO_ERROS_REMATRICULA)}
    except Exception:                                    # noqa: BLE001
        erros = {}
    contatos = _contatos(pasta)

    linhas: list[dict] = []
    series: dict[str, dict] = {}
    for r in ativos:
        chave = _chave_pessoa(r["nome"], r["nascimento"])
        serie = rotulo_serie_da_turma(r["turma"])
        resumo = series.setdefault(serie, {"serie": serie, "ordem": _ordem_turma(r["turma"]), "ativos": 0,
                                           "na_previsao": 0, "fora": 0, "concluintes": 0})
        resumo["ativos"] += 1
        if (r["cgm"] and r["cgm"] in cgms_prev) or (chave and chave in chaves_prev):
            resumo["na_previsao"] += 1
            continue

        ordem = _ordem_turma(r["turma"])
        erro = erros.get(r["cgm"]) if r["cgm"] else None
        tentativas = 0
        if ultima is not None and ordem == ultima:
            categoria, motivo = CAT_CONCLUINTE, f"Concluiu a etapa ({serie} é a última série da escola)"
        elif erro:
            tentativas = int(erro.get("tentativas") or 1) if str(erro.get("tentativas") or "1").isdigit() else 1
            categoria = CAT_ERRO
            motivo = f"Rematrícula deu erro ({tentativas} tentativa(s)): {str(erro.get('erro') or 'sem detalhe').strip()[:160]}"
        else:
            achado = saidas_cgm.get(r["cgm"]) if r["cgm"] else None
            achado = achado or (saidas_chave.get(chave) if chave else None)
            categoria, motivo = achado if achado else (CAT_SEM_REGISTRO, "Sem rematrícula e sem pré-matrícula para o próximo ano")

        resumo["concluintes" if categoria == CAT_CONCLUINTE else "fora"] += 1
        prevista = "" if categoria == CAT_CONCLUINTE else proxima_turma(r["turma"])[0]
        contato = contatos.get(r["cgm"], {})
        linhas.append({
            "cgm": r["cgm"], "nome": r["nome"], "nascimento": r["nascimento"], "turma_atual": r["turma"],
            "turma_prevista": prevista, "categoria": categoria, "motivo": motivo, "tentativas": tentativas,
            "responsavel": contato.get("responsavel", ""), "telefone": contato.get("telefone", ""),
        })

    linhas.sort(key=lambda l: (_ordem_turma(l["turma_atual"]), _sem_acento(l["turma_atual"]), _sem_acento(l["nome"])))
    resumo_series = sorted(series.values(), key=lambda x: x["ordem"])
    contagem = {c: sum(1 for l in linhas if l["categoria"] == c) for c in (CAT_ERRO, CAT_OUTRA_ESCOLA, CAT_CANCELOU, CAT_SEM_REGISTRO)}
    contagem["concluintes"] = sum(1 for l in linhas if l["categoria"] == CAT_CONCLUINTE)
    contagem["total"] = len(linhas) - contagem["concluintes"]
    contagem["ativos"] = len(ativos)
    return {"disponivel": True, "ultima_serie": ultima, "linhas": linhas, "resumo_series": resumo_series, "contagem": contagem}


def resumo_por_turma(linhas: list[dict]) -> list[dict]:
    """Uma entrada por turma da previsão (série do ano seguinte): totais e de quais turmas de hoje vêm os rematriculados."""
    grupos: dict[str, dict] = {}
    for l in linhas:
        g = grupos.setdefault(l["turma"] or "Sem turma", {
            "turma": l["turma"] or "Sem turma", "ordem": _ordem_turma(l["turma"]), "total": 0,
            "rematriculados": 0, "novos": 0, "novos_matriculados": 0, "novos_pendentes": 0, "origens": {}})
        g["total"] += 1
        if l["tipo"] == TIPO_NOVO:
            g["novos"] += 1
            g["novos_matriculados" if l["situacao"] == SITUACAO_MATRICULADO else "novos_pendentes"] += 1
        else:
            g["rematriculados"] += 1
            origem = rotulo_serie_da_turma(l.get("turma_atual") or l.get("turma_origem"))
            if origem:
                g["origens"][origem] = g["origens"].get(origem, 0) + 1
    return sorted(grupos.values(), key=lambda g: (g["ordem"], _sem_acento(g["turma"])))


def montar_previsao(pasta, ano_letivo) -> dict:
    """
    Previsão do ano letivo ``ano_letivo`` (o PRÓXIMO), a partir dos arquivos em ``pasta`` (dados/<ano em uso>).

    Devolve::

        {"ano": 2027, "arquivo": "previsao_alunos_2027.json", "arquivo_existe": bool, "atualizado_em": "...",
         "rematriculados_existe": bool,
         "linhas": [{"tipo","nome","nascimento","cgm","cpf","turma","situacao","responsavel","telefone",
                     "escola_origem","turma_origem","posicao","ja_e_aluno"}],
         "contagem": {"total","rematriculados","novos","novos_matriculados","novos_pendentes"},
         "avisos": [str]}

    Lança ArquivoJsonCorrompidoError se um dos arquivos existir e estiver ilegível (nada é alterado).
    """
    pasta = Path(pasta)
    ano_letivo = int(ano_letivo)
    avisos: list[str] = []

    previsao_alunos = carregar_previsao_alunos(pasta, ano_letivo)
    arquivo_existe = caminho_previsao_alunos(pasta, ano_letivo).exists()
    rematriculados_existe = (pasta / ARQUIVO_REMATRICULADOS).exists()
    if not arquivo_existe:
        avisos.append(f"Ainda não há {nome_arquivo(ano_letivo)}. Rode o processo de pré-matrícula para o próximo ano "
                      "(alvo \"proximo\") para trazer os alunos novos.")
    if not rematriculados_existe:
        avisos.append(f"Ainda não há {ARQUIVO_REMATRICULADOS}. Rode a rematrícula para trazer os rematriculados.")

    linhas: list[dict] = []
    cgms_re: set[str] = set()
    chaves_re: set[str] = set()
    registros_turmas = _registros_turmas(pasta) or []
    turma_hoje_por_cgm = {r["cgm"]: r["turma"] for r in registros_turmas if r["cgm"] and r["ativo"]}
    sem_serie = 0
    for r in _ler_lista(pasta, ARQUIVO_REMATRICULADOS):
        cgm = str(r.get("cgm") or "").strip()
        nasc = _nascimento(r.get("data_nascimento"))
        if cgm and cgm in cgms_re:
            continue                                      # o mesmo CGM nunca conta duas vezes
        if cgm:
            cgms_re.add(cgm)
        chave = _chave_pessoa(r.get("nome"), nasc)
        if chave:
            chaves_re.add(chave)
        # O arquivo guarda a turma de HOJE; a previsão mostra a do ano que vem (série seguinte).
        turma_atual = str(r.get("turma") or "").strip() or turma_hoje_por_cgm.get(cgm, "")
        turma_prevista, reconhecida = proxima_turma(turma_atual)
        if not reconhecida:
            sem_serie += 1
        linhas.append({
            "tipo": TIPO_REMATRICULADO, "nome": str(r.get("nome") or "").strip(), "nascimento": nasc, "cgm": cgm, "cpf": "",
            "turma": turma_prevista, "turma_atual": turma_atual, "situacao": "rematriculado", "responsavel": "",
            "telefone": "", "escola_origem": "", "turma_origem": turma_atual, "posicao": "", "ja_e_aluno": True,
        })

    atuais_cgm, atuais_chave = _alunos_atuais(pasta)
    repetidos = 0
    for n in _novos_da_pre_matricula(previsao_alunos):
        chave = _chave_pessoa(n["nome"], n["nascimento"])
        if (n["cgm"] and n["cgm"] in cgms_re) or (chave and chave in chaves_re):
            repetidos += 1
            continue                                      # já está como rematriculado
        n["tipo"] = TIPO_NOVO
        n["turma_pedida"] = n["turma"]                    # como veio da pré-matrícula; "turma" passa ao rótulo comum às duas fontes
        n["turma"] = rotulo_serie_da_turma(n["turma"])
        n["turma_atual"] = ""
        n["ja_e_aluno"] = bool((n["cgm"] and n["cgm"] in atuais_cgm) or (chave and chave in atuais_chave))
        linhas.append(n)
    if repetidos:
        avisos.append(f"{repetidos} aluno(s) estavam na pré-matrícula e também rematriculados; contados só como rematriculados.")

    novos = [l for l in linhas if l["tipo"] == TIPO_NOVO]
    ja_alunos = sum(1 for l in novos if l["ja_e_aluno"])
    if ja_alunos:
        avisos.append(f"{ja_alunos} aluno(s) novo(s) da pré-matrícula já constam como alunos da escola neste ano "
                      "(ainda sem rematrícula confirmada); confira se não são rematrículas pendentes.")

    if sem_serie:
        avisos.append(f"{sem_serie} rematriculado(s) estão numa turma sem série reconhecível (ex.: sem \"º Ano\" ou \"Infantil\" "
                      "no nome); ficaram na mesma turma de hoje. Confira.")
    linhas.sort(key=_chave_ordem)
    contagem = {
        "total": len(linhas),
        "rematriculados": len(linhas) - len(novos),
        "novos": len(novos),
        "novos_matriculados": sum(1 for l in novos if l["situacao"] == SITUACAO_MATRICULADO),
        "novos_pendentes": sum(1 for l in novos if l["situacao"] == SITUACAO_PENDENTE),
    }
    atualizado = str(previsao_alunos.get("atualizado_em") or "")
    return {
        "ano": ano_letivo, "arquivo": nome_arquivo(ano_letivo), "arquivo_existe": arquivo_existe,
        "rematriculados_existe": rematriculados_existe,
        "atualizado_em": "" if not atualizado or atualizado.lower().startswith("x") else atualizado,
        "linhas": linhas, "contagem": contagem, "avisos": avisos,
        "turmas": resumo_por_turma(linhas),
        "fora": analisar_fora_da_rematricula(pasta, linhas, previsao_alunos),
    }


def alunos_para_planilha(pasta, ano_letivo) -> dict:
    """
    Alunos da previsão do ``ano_letivo`` (o PRÓXIMO) prontos para virar planilha, uma lista só, por turma do ano que vem:
    rematriculados e novos (``montar_previsao``) + direcionados GEO presentes (sere_sisgea_<ano>.json) que ainda não
    estão na lista (mesmo CGM conta uma vez; a rematrícula e a pré-matrícula têm prioridade).

    Devolve {"ano", "linhas": [{"turma","nome","cgm","nascimento","origem","situacao","turma_atual","responsavel","telefone"}],
             "avisos": [str]}. ``origem``: "Rematriculado" | "Novo (pré-matrícula)" | "Direcionado GEO". Só lê arquivos.
    """
    from src.comum import direcionados_geo as _geo

    base = montar_previsao(pasta, ano_letivo)
    contatos = _contatos(Path(pasta))
    linhas: list[dict] = []
    cgms: set[str] = set()
    for l in base["linhas"]:
        cgm = str(l.get("cgm") or "").strip()
        if cgm:
            cgms.add(cgm)
        contato = contatos.get(cgm, {})
        linhas.append({
            "turma": l["turma"] or "Sem turma", "nome": l["nome"], "cgm": cgm, "nascimento": l.get("nascimento", ""),
            "origem": "Rematriculado" if l["tipo"] == TIPO_REMATRICULADO else "Novo (pré-matrícula)",
            "situacao": "Rematrícula confirmada" if l["tipo"] == TIPO_REMATRICULADO
            else ("Com vaga" if l["situacao"] == SITUACAO_MATRICULADO else "Aguardando vaga"),
            "turma_atual": l.get("turma_atual", ""),
            "responsavel": l.get("responsavel") or contato.get("responsavel", ""),
            "telefone": l.get("telefone") or contato.get("telefone", ""),
        })
    avisos = list(base["avisos"])
    geo = _geo.carregar_direcionados(pasta, ano_letivo)
    repetidos = 0
    for a in geo["alunos"]:
        if a["situacao_lista"] == "ausente":
            continue
        if a["cgm"] and a["cgm"] in cgms:
            repetidos += 1
            continue
        if a["cgm"]:
            cgms.add(a["cgm"])
        linhas.append({
            "turma": rotulo_serie_da_turma(a["turma"] or a["etapa"]) or "Sem turma", "nome": a["nome"], "cgm": a["cgm"],
            "nascimento": "", "origem": "Direcionado GEO", "situacao": "Matrícula confirmada" if a["matricula_confirmada"] else "Direcionado",
            "turma_atual": "", "responsavel": a["responsavel"], "telefone": a["telefone"],
        })
    if repetidos:
        avisos.append(f"{repetidos} direcionado(s) GEO já estavam na rematrícula/pré-matrícula; contados uma vez só.")
    linhas.sort(key=lambda l: (_ordem_turma(l["turma"]), _sem_acento(l["turma"]), _sem_acento(l["nome"])))
    return {"ano": int(ano_letivo), "linhas": linhas, "avisos": avisos}

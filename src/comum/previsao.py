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
        linhas.append({
            "tipo": TIPO_REMATRICULADO, "nome": str(r.get("nome") or "").strip(), "nascimento": nasc, "cgm": cgm, "cpf": "",
            "turma": str(r.get("turma") or "").strip(), "situacao": "rematriculado", "responsavel": "", "telefone": "",
            "escola_origem": "", "turma_origem": str(r.get("turma") or "").strip(), "posicao": "", "ja_e_aluno": True,
        })

    atuais_cgm, atuais_chave = _alunos_atuais(pasta)
    repetidos = 0
    for n in _novos_da_pre_matricula(previsao_alunos):
        chave = _chave_pessoa(n["nome"], n["nascimento"])
        if (n["cgm"] and n["cgm"] in cgms_re) or (chave and chave in chaves_re):
            repetidos += 1
            continue                                      # já está como rematriculado
        n["tipo"] = TIPO_NOVO
        n["ja_e_aluno"] = bool((n["cgm"] and n["cgm"] in atuais_cgm) or (chave and chave in atuais_chave))
        linhas.append(n)
    if repetidos:
        avisos.append(f"{repetidos} aluno(s) estavam na pré-matrícula e também rematriculados; contados só como rematriculados.")

    novos = [l for l in linhas if l["tipo"] == TIPO_NOVO]
    ja_alunos = sum(1 for l in novos if l["ja_e_aluno"])
    if ja_alunos:
        avisos.append(f"{ja_alunos} aluno(s) novo(s) da pré-matrícula já constam como alunos da escola neste ano "
                      "(ainda sem rematrícula confirmada); confira se não são rematrículas pendentes.")

    linhas.sort(key=lambda l: (_sem_acento(l["turma"]), _sem_acento(l["nome"])))
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
    }

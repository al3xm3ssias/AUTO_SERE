"""
Rotas de API do Auto SERE
==========================
Integração real com as automações de src/automacao, src/comum e
src/relatorios — sem dados fictícios. Cada endpoint lê os JSONs de
trabalho gerados pelos próprios scripts (src.comum.paths.dados_ano_atual())
ou dispara a automação correspondente via
src.comum.execucao_gui.ExecucaoEmBackground, que roda o modo assíncrono
(Playwright) em thread própria e repassa o progresso por callback.

Como o app.js atual só faz `await apiPost(...)` (sem consumir progresso
em tempo real), o fluxo de execução de automação é:

    1. POST /automacoes/<chave>/executar dispara a automação em
       background e retorna IMEDIATAMENTE {"status": "executando", ...}.
    2. GET  /automacoes/<chave>/status devolve o estado mais recente
       (linhas de log acumuladas, status, resultado/erro) — pronto para
       um futuro polling da interface, sem exigir mudança nenhuma no
       app.js hoje (ele já trata qualquer 200 como sucesso).

Automações cuja lógica de negócio ainda não existe no código-fonte
(ver AUTOMACOES_NAO_IMPLEMENTADAS) respondem 501 em vez de fingir
sucesso — é mais seguro que devolver um "ok" mentiroso.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from flask import Blueprint, jsonify, request

from src.comum import paths as _paths
from src.comum.execucao_gui import ExecucaoEmBackground, StatusExecucao
from src.comum import configuracao as _config
from src.comum import cep_consulta as _cep
from src.comum import escola as _escola
from src.comum import entrada_usuario as _entrada
from src.comum import opcoes_execucao as _opcoes
from src.comum import registro_scripts as _registro
from src.comum.registros_aluno import casar_com_turmas, registro_principal

api_bp = Blueprint("api", __name__)


# ============================================================
# LEITURA DOS DADOS DE TRABALHO (dados/<ano>/*.json)
# ============================================================
# Nenhuma automação é disparada para servir estas rotas de leitura — elas
# só refletem o estado dos JSONs já gerados pelas automações reais
# (src.automacao.turmas, src.automacao.funcionarios, prematricula, etc.).
# Se o arquivo ainda não existe (automação nunca rodou), a resposta vem
# vazia (lista/objeto vazio) em vez de dado inventado.

def _dados_dir() -> Path:
    return _paths.dados_ano_atual()


def _carregar_json(nome_arquivo: str, padrao):
    caminho = _dados_dir() / nome_arquivo
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return padrao


def _mtime_formatado(nome_arquivo: str) -> Optional[str]:
    caminho = _dados_dir() / nome_arquivo
    if not caminho.exists():
        return None
    return datetime.fromtimestamp(caminho.stat().st_mtime).strftime("%d/%m/%Y %H:%M")


# ============================================================
# PAINEL PRINCIPAL
# ============================================================

@api_bp.route("/painel/resumo")
def painel_resumo():
    """
    Números reais calculados a partir de turmas.json, documentos-alunos.json,
    pre_matricula.json e alunos_encaminhamento.json — nenhum é mockado.
    Um dado que depende de um arquivo ainda inexistente (automação nunca
    rodada) aparece como 0, não como um valor inventado.
    """
    turmas = _carregar_json("turmas.json", {})
    documentos_alunos = _carregar_json("documentos-alunos.json", [])
    pre_matricula = _carregar_json("pre_matricula.json", {})
    alunos_fora_raio, _meta_raio = _alunos_fora_do_raio()
    alunos_encaminhamento, _cpf_invalidos = _alunos_com_encaminhamento()
    transferidos = _carregar_json("transferidos.json", {})

    total_alunos = 0
    meninos = 0
    meninas = 0
    ativos = 0
    for lista_alunos in turmas.values():
        for aluno in lista_alunos:
            situacao = str(aluno.get("Situação", aluno.get("Situacao", ""))).strip().lower()
            if "transferido" in situacao:
                continue
            total_alunos += 1
            ativos += 1
            sexo = str(aluno.get("Sexo", "")).strip().upper()
            if sexo.startswith("M"):
                meninos += 1
            elif sexo.startswith("F"):
                meninas += 1

    pct_meninos = f"{(meninos / total_alunos * 100):.1f}%".replace(".", ",") if total_alunos else "—"
    pct_meninas = f"{(meninas / total_alunos * 100):.1f}%".replace(".", ",") if total_alunos else "—"

    # Mesma regra da tela da Pré-matrícula: a tentativa antiga de quem mudou de turma não conta duas vezes.
    fila_prematricula = sum(
        1
        for alunos in pre_matricula.get("turmas_intencao", {}).values()
        for aluno in alunos
        if not aluno.get("substituido_por_nova_tentativa")
    ) if isinstance(pre_matricula, dict) else 0

    docs_pendentes = 0
    for aluno in documentos_alunos:
        detalhes = aluno.get("Detalhes", [])
        if any(not d.get("validado") for d in detalhes):
            docs_pendentes += 1

    qtd_transferidos = sum(1 for v in transferidos.values() if isinstance(v, dict)) \
        if isinstance(transferidos, dict) else 0

    ultima_atualizacao = None
    for candidato in ("turmas.json", "documentos-alunos.json", "pre_matricula.json"):
        m = _mtime_formatado(candidato)
        if m:
            ultima_atualizacao = m
            break

    return jsonify({
        "atualizado_em": ultima_atualizacao or datetime.now().strftime("%d/%m/%Y %H:%M"),
        "principais": [
            {"chave": "total_alunos", "label": "Total de alunos", "valor": total_alunos},
            {"chave": "meninos", "label": "Meninos", "valor": meninos, "sub": pct_meninos},
            {"chave": "meninas", "label": "Meninas", "valor": meninas, "sub": pct_meninas},
            {"chave": "fila_prematricula", "label": "Fila da pré-matrícula", "valor": fila_prematricula},
            {"chave": "turmas", "label": "Turmas", "valor": len(turmas)},
        ],
        "secundarias": [
            {"chave": "docs_pendentes", "label": "Docs pendentes", "valor": docs_pendentes},
            {"chave": "fora_do_raio", "label": "Fora do raio da escola", "valor": len(alunos_fora_raio)},
            {"chave": "transferidos", "label": "Qtd. transferidos", "valor": qtd_transferidos},
            {"chave": "encaminhamentos", "label": "Qtd. encaminhamentos SUS", "valor": len(alunos_encaminhamento)},
        ],
    })


# ============================================================
# ENTIDADES (TURMAS / ALUNOS / PRÉ-MATRÍCULA / FUNCIONÁRIOS)
# ============================================================

def _resposta_lista_generica(colunas, linhas, resumo: Optional[str] = None, extras: Optional[dict] = None):
    corpo = {"colunas": colunas, "linhas": linhas, "total": len(linhas)}
    if resumo:
        corpo["resumo"] = resumo      # texto curto exibido acima da tabela (ex.: raio e data da análise)
    if extras:
        corpo.update(extras)          # ex.: "cartoes" (cards de resumo no topo da tela) e dados do gráfico/mapa
    return jsonify(corpo)


def _cartao(label: str, valor, sub: str = "", cor: str = "cyan", icone: str = "bolt") -> dict:
    """Um card de resumo (mesmo formato visual do .stat-card do painel) para o topo das telas."""
    return {"label": label, "valor": valor, "sub": sub, "cor": cor, "icone": icone}


def _sem_acento(texto) -> str:
    import unicodedata
    base = unicodedata.normalize("NFD", str(texto or ""))
    return re.sub(r"\s+", " ", "".join(c for c in base if unicodedata.category(c) != "Mn")).strip().lower()


def _mapas_de_turma() -> tuple[dict[str, str], dict[str, str]]:
    """(turma por CGM, turma por nome sem acento) a partir de turmas.json."""
    por_cgm: dict[str, str] = {}
    por_nome: dict[str, str] = {}
    turmas = _carregar_json("turmas.json", {})
    if isinstance(turmas, dict):
        for turma, alunos in turmas.items():
            for a in alunos if isinstance(alunos, list) else []:
                cgm = str(a.get("CGM", "")).strip()
                nome = _sem_acento(a.get("Nome", ""))
                if cgm:
                    por_cgm[cgm] = turma
                if nome:
                    por_nome.setdefault(nome, turma)
    return por_cgm, por_nome


def _alunos_fora_do_raio() -> tuple[list[dict], dict]:
    """
    Lê alunos_fora_raio.json (gerado por src.comum.cep_api). O formato atual é
    {"metadados": {...}, "alunos": [...]}; aceita também a lista simples antiga.
    """
    bruto = _carregar_json("alunos_fora_raio.json", {})
    if isinstance(bruto, list):
        return bruto, {}
    if isinstance(bruto, dict):
        alunos = bruto.get("alunos", [])
        return (alunos if isinstance(alunos, list) else []), (bruto.get("metadados") or {})
    return [], {}


_PALAVRAS_COMPROVANTE_ENDERECO = (
    "residencia", "residência", "endereço", "endereco", "sanepar", "copel", "compesa",
    "conta de água", "conta de agua", "conta de luz", "comprovante de end", "comprovante de resid",
)


def _eh_comprovante_endereco(nome_documento: str) -> bool:
    n = str(nome_documento).lower()
    return any(p in n for p in _PALAVRAS_COMPROVANTE_ENDERECO)


def _documentos_pc_por_cgm() -> tuple[dict[str, list[str]], bool]:
    """
    (CGM -> nomes dos documentos digitalizados no PC, o arquivo existe?).
    Vem de documentos-alunos-pc.json (src.relatorios.analisa_documentos_pc). Se o arquivo ainda não foi
    gerado, a tela não afirma "sem comprovante": ela mostra "—" (desconhecido).
    """
    if not (_dados_dir() / "documentos-alunos-pc.json").exists():
        return {}, False
    bruto = _carregar_json("documentos-alunos-pc.json", [])
    mapa: dict[str, list[str]] = {}
    for e in bruto if isinstance(bruto, list) else []:
        if not isinstance(e, dict):
            continue
        cgm = str(e.get("CGM", e.get("cgm", ""))).strip()
        if cgm:
            docs = [_nome_documento(d) for d in (e.get("Documentos") or e.get("documentos") or [])]
            mapa[cgm] = [d for d in docs if d]
    return mapa, True


def _cpf_mascarado(cpf) -> str:
    """CPF para exibir na tela: o número completo não sai do servidor (só os 6 dígitos do meio)."""
    d = re.sub(r"\D", "", str(cpf or ""))
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    return "***" if d else ""


def _alunos_com_encaminhamento() -> tuple[list[dict], int]:
    """
    (alunos que TÊM encaminhamento, quantidade de registros "CPF inválido").
    alunos_encaminhamento.json também guarda os CPFs inválidos para auditoria de
    cadastro; eles não são encaminhamentos e não podem entrar na contagem.
    """
    bruto = _carregar_json("alunos_encaminhamento.json", [])
    if not isinstance(bruto, list):
        return [], 0
    com = [r for r in bruto if isinstance(r, dict) and r.get("encaminhamentos")]
    invalidos = sum(1 for r in bruto if isinstance(r, dict) and r.get("erro"))
    return com, invalidos


def _situacao(aluno: dict) -> str:
    return str(aluno.get("Situação", aluno.get("Situacao", ""))).strip().lower()


def _sexo(aluno: dict) -> str:
    return str(aluno.get("Sexo", "")).strip().lower()


@api_bp.route("/turmas/lista")
def turmas_lista():
    """
    Lê turmas.json (gerado por src.automacao.turmas) e devolve um card por
    turma com estatísticas (matriculados/transferidos/masc/fem) e a lista
    COMPLETA de alunos — todos os campos originais do JSON, sem resumir —
    para a tela expansível de Turmas (mesma lógica de DATA.turma_stats +
    DATA.turmas do protótipo index.html: matriculado = contém "matriculado"
    na Situação, transferido = contém "transf").
    """
    turmas = _carregar_json("turmas.json", {})

    total_geral_matriculados = 0
    total_geral_transferidos = 0
    turmas_resp = []

    for nome_turma, lista_alunos in sorted(turmas.items(), key=lambda kv: kv[0]):
        masc = sum(1 for a in lista_alunos if _sexo(a).startswith("m"))
        fem = sum(1 for a in lista_alunos if _sexo(a).startswith("f"))
        transf = sum(1 for a in lista_alunos if "transf" in _situacao(a))
        matriculados = sum(1 for a in lista_alunos if "matriculado" in _situacao(a))

        total_geral_matriculados += matriculados
        total_geral_transferidos += transf

        turmas_resp.append({
            "nome": nome_turma,
            "total": len(lista_alunos),
            "matriculados": matriculados,
            "transf": transf,
            "masc": masc,
            "fem": fem,
            "alunos": lista_alunos,  # campos originais crus, ex.: N/CGM/Nome/Sexo/Situação
        })

    return jsonify({
        "turmas": turmas_resp,
        "total_turmas": len(turmas_resp),
        "total_matriculados": total_geral_matriculados,
        "total_transferidos": total_geral_transferidos,
    })


@api_bp.route("/alunos/lista")
def alunos_lista():
    """
    Lê alunos.json (cadastro completo — gerado por
    src.automacao.alunos.coletar_cadastro_completo_alunos: Nome, CGM, RG,
    CPF, endereço, responsável, etc.) cruzado com turmas.json (situação e
    turma mais atuais, já que alunos.json não é recoletado com a mesma
    frequência). Mesma lógica de DATA.alunos + DATA.turmas_cgm_map do
    protótipo index.html: por CGM, turmas.json vence para _turma/_situacao.

    Devolve os alunos com TODOS os campos originais do cadastro (para o
    detalhe expansível no front) mais _turma/_situacao já resolvidos.
    """
    alunos = _carregar_json("alunos.json", [])
    turmas = _carregar_json("turmas.json", {})

    # Um CGM pode ter MAIS DE UM registro em turmas.json (aluno transferido que
    # retornou: Transferido + Matriculado). Guarda todos e casa cada cadastro de
    # alunos.json com o seu — não um único por CGM, onde o último sobrescrevia.
    registros_por_cgm: dict[str, list[dict]] = {}
    for nome_turma, lista_alunos in turmas.items():
        for aluno in lista_alunos:
            cgm = str(aluno.get("CGM", aluno.get("cgm", ""))).strip()
            if not cgm:
                continue
            registros_por_cgm.setdefault(cgm, []).append({**aluno, "_turma": nome_turma})

    usados: set[int] = set()
    alunos_resp = []
    for aluno in alunos:
        cgm = str(aluno.get("CGM", aluno.get("cgm", ""))).strip()
        reg = casar_com_turmas(aluno, registros_por_cgm.get(cgm, []), usados)
        aluno_completo = dict(aluno)
        if reg:
            aluno_completo["_situacao"] = reg.get("Situação", reg.get("Situacao", "—"))
            aluno_completo["_turma"] = reg["_turma"]
            aluno_completo["_data_movimentacao"] = reg.get("Data Matricula", "")
            if reg.get("Retorno"):
                aluno_completo["_retorno"] = True
        else:
            aluno_completo["_situacao"] = "—"
            aluno_completo["_turma"] = "—"
        alunos_resp.append(aluno_completo)

    campos = list(alunos_resp[0].keys()) if alunos_resp else []
    # _situacao/_turma são metadados de cruzamento, não campos de cadastro —
    # não entram na lista de campos do cadastro (grupos de detalhe no front).
    campos = [c for c in campos if not c.startswith("_")]

    return jsonify({
        "alunos": alunos_resp,
        "campos": campos,
        "total": len(alunos_resp),
    })


# ============================================================
# ANÁLISE DE DOCUMENTOS (tela única com 3 abas internas)
# ============================================================
# Aba 1 "Documentos Digitalizados" -> documentos-alunos-pc.json
#       (src.relatorios.analisa_documentos_pc)
# Aba 2 "Documentos do PIVE"       -> documentos-alunos.json
#       (src.automacao.executar_analisa / analisa_sere)
# Aba 3 "Análise"                  -> cruzamento-documentos.json
#       (src.relatorios.cruzar_documentos)
# Cada aba é carregada sob demanda (os JSONs passam de 300 KB cada).
# Arquivo inexistente => resposta vazia + "gerado": false, para o front
# orientar qual automação rodar (nunca dado inventado).

def _turma_situacao_por_cgm() -> dict[str, dict]:
    """CGM -> {turma, situacao, nome} a partir de turmas.json.
    Mesma lógica de DATA.turmas_cgm_map do index.html: os JSONs de
    documentos vêm com Turma vazia, então turmas.json é a fonte da turma."""
    por_cgm: dict[str, list[dict]] = {}
    for nome_turma, lista in _carregar_json("turmas.json", {}).items():
        for aluno in lista:
            cgm = str(aluno.get("CGM", aluno.get("cgm", ""))).strip()
            if cgm:
                por_cgm.setdefault(cgm, []).append({**aluno, "_turma": nome_turma})
    mapa: dict[str, dict] = {}
    for cgm, regs in por_cgm.items():
        # CGM com mais de um registro (transferido + retorno): vale o vigente (matriculado mais recente).
        aluno = registro_principal(regs)
        mapa[cgm] = {
            "turma": aluno["_turma"],
            "situacao": aluno.get("Situação", aluno.get("Situacao", "—")),
            "nome": aluno.get("Nome", aluno.get("nome", "")),
        }
    return mapa


def _nome_documento(doc) -> str:
    """Documentos do PC podem vir como string ou como objeto
    {nome, nome_arquivo, extensao, nome_completo, data} — normaliza para
    texto (mesmo docName() do index.html)."""
    if isinstance(doc, dict):
        return str(doc.get("nome") or doc.get("nome_arquivo") or doc.get("nome_completo") or "")
    return str(doc or "")


@api_bp.route("/documentos/digitalizados")
def documentos_digitalizados():
    """Aba 1 — documentos digitalizados (pastas no PC), um registro por aluno."""
    bruto = _carregar_json("documentos-alunos-pc.json", [])
    por_cgm = _turma_situacao_por_cgm()

    alunos = []
    for e in bruto if isinstance(bruto, list) else []:
        cgm = str(e.get("CGM", e.get("cgm", ""))).strip()
        turma = e.get("Turma") or e.get("turma") or (por_cgm.get(cgm) or {}).get("turma") or "—"
        docs = [_nome_documento(d) for d in (e.get("Documentos") or e.get("documentos") or [])]
        alunos.append({
            "cgm": cgm,
            "nome": e.get("Nome") or e.get("nome") or "—",
            "turma": turma,
            "documentos": [d for d in docs if d],
        })

    return jsonify({
        "gerado": (_dados_dir() / "documentos-alunos-pc.json").exists(),
        "atualizado_em": _mtime_formatado("documentos-alunos-pc.json"),
        "alunos": alunos,
        "total": len(alunos),
    })


@api_bp.route("/documentos/pive")
def documentos_pive():
    """Aba 2 — documentos anexados no SERE/PIVE, com Detalhes (tipo, arquivo,
    data, validado). Turma e situação resolvidas por turmas.json."""
    bruto = _carregar_json("documentos-alunos.json", [])
    por_cgm = _turma_situacao_por_cgm()

    alunos = []
    for e in bruto if isinstance(bruto, list) else []:
        cgm = str(e.get("CGM", e.get("cgm", ""))).strip()
        if not cgm:
            continue
        info = por_cgm.get(cgm) or {}
        detalhes = e.get("Detalhes") or []
        alunos.append({
            "cgm": cgm,
            "nome": e.get("Nome") or e.get("nome") or info.get("nome") or "Sem nome",
            "turma": e.get("Turma") or info.get("turma") or "—",
            "situacao": e.get("Situacao") or e.get("Situação") or info.get("situacao") or "—",
            "total": e.get("Total") or len(detalhes),
            "detalhes": detalhes,
        })

    return jsonify({
        "gerado": (_dados_dir() / "documentos-alunos.json").exists(),
        "atualizado_em": _mtime_formatado("documentos-alunos.json"),
        "alunos": alunos,
        "total": len(alunos),
    })


@api_bp.route("/documentos/analise")
def documentos_analise():
    """Aba 3 — cruzamento PC x SERE (cruzamento-documentos.json), repassado
    como gerado por src.relatorios.cruzar_documentos (Total_Alunos, Data_Hora,
    Resumo_Geral, Alunos[])."""
    caminho = _dados_dir() / "cruzamento-documentos.json"
    cruz = _carregar_json("cruzamento-documentos.json", {})
    if not isinstance(cruz, dict):
        cruz = {}

    por_cgm = _turma_situacao_por_cgm()
    alunos = []
    for a in cruz.get("Alunos") or []:
        if not a.get("Turma"):
            a = dict(a)
            a["Turma"] = (por_cgm.get(str(a.get("CGM", "")).strip()) or {}).get("turma", "")
        alunos.append(a)

    return jsonify({
        "gerado": caminho.exists(),
        "atualizado_em": cruz.get("Data_Hora") or _mtime_formatado("cruzamento-documentos.json"),
        "total": cruz.get("Total_Alunos", len(alunos)),
        "resumo": cruz.get("Resumo_Geral") or {},
        "alunos": alunos,
    })


def _fila_prematricula() -> list[dict]:
    """
    Lê pre_matricula.json (gerado por src.automacao.prematricula_coleta /
    prematricula_cadastro) e devolve uma lista plana de alunos na fila.

    Formato real do arquivo (ver src.automacao.prematricula_coleta):
        {
            "atualizado_em": "...",
            "turmas_intencao": { "<turma>": [ {pos, nome, cpf, tipo,
                                                pontuacao, tr_id}, ... ] },
            "cadastros": { "<cpf>": {telefone, nome_responsavel, ...} },
        }
    O telefone do responsável não vem junto do registro da fila — só é
    conhecido depois da Etapa 2 (consulta de cadastro por CPF), então
    precisa ser cruzado aqui pelo CPF.
    """
    dados = _carregar_json("pre_matricula.json", {})
    if not isinstance(dados, dict):
        return []

    turmas_intencao = dados.get("turmas_intencao", {})
    cadastros = dados.get("cadastros", {})

    itens = []
    for turma, alunos in turmas_intencao.items():
        for aluno in alunos:
            if aluno.get("substituido_por_nova_tentativa"):
                continue          # tentativa antiga (aluno voltou noutra turma): não conta duas vezes
            cpf = (aluno.get("cpf") or "").strip()
            cadastro = cadastros.get(cpf, {}) if cpf else {}
            itens.append({
                "id": cpf or aluno.get("tr_id") or aluno.get("nome", ""),
                "nome": aluno.get("nome", ""),
                "turma": turma,
                "posicao": aluno.get("pos", ""),
                "tipo": aluno.get("tipo", ""),
                "pontuacao": aluno.get("pontuacao", ""),
                "telefone_responsavel": cadastro.get("telefone") or "—",
            })
    return itens


def _posicao_ordenavel(item: dict):
    try:
        return int(str(item["posicao"]).strip())
    except (ValueError, TypeError):
        return 10**9


@api_bp.route("/prematricula/lista")
def prematricula_lista():
    """Lê pre_matricula.json (gerado por src.automacao.prematricula_coleta)."""
    colunas = [
        {"chave": "nome", "label": "Nome do aluno"},
        {"chave": "turma", "label": "Turma"},
        {"chave": "posicao", "label": "Posição na fila"},
        {"chave": "tipo", "label": "Tipo"},
        {"chave": "telefone_responsavel", "label": "Número do pai"},
    ]
    linhas = sorted(_fila_prematricula(), key=lambda r: (r["turma"], _posicao_ordenavel(r)))
    return _resposta_lista_generica(colunas, linhas)


def _situacao_prematricula(opcoes: list) -> str:
    """matriculado = alguma opção com situação que não seja CANCELADO; cancelado = todas as preenchidas canceladas."""
    com_situacao = [o for o in opcoes if isinstance(o, dict) and str(o.get("situacao") or "").strip()]
    if not com_situacao:
        return "pendente"
    if any(not str(o["situacao"]).upper().startswith("CANCELADO") for o in com_situacao):
        return "matriculado"
    return "cancelado"


@api_bp.route("/prematricula/cadastros")
def prematricula_cadastros():
    """
    Um registro por cadastro da pré-matrícula (pre_matricula.json → "cadastros", por CPF), com a situação
    derivada das escolas escolhidas e as turmas de intenção (posição na fila, pontuação). Tentativas antigas
    substituídas por uma nova (aluno que voltou noutra turma) não entram: vale a última, como em BUGS_CONHECIDOS.md.
    """
    dados = _carregar_json("pre_matricula.json", {})
    dados = dados if isinstance(dados, dict) else {}
    cadastros = dados.get("cadastros") if isinstance(dados.get("cadastros"), dict) else {}
    turmas_intencao = dados.get("turmas_intencao") if isinstance(dados.get("turmas_intencao"), dict) else {}

    intencoes: dict[str, list[dict]] = {}
    so_na_fila: dict[str, dict] = {}        # quem está na fila mas ainda não tem cadastro coletado (Etapa 2)
    for turma, lista in turmas_intencao.items():
        for item in lista if isinstance(lista, list) else []:
            if not isinstance(item, dict) or item.get("substituido_por_nova_tentativa"):
                continue
            ints = {
                "turma": turma, "pos": item.get("pos", ""), "pontuacao": item.get("pontuacao", ""),
                "tipo": item.get("tipo", ""), "presente_na_ultima_coleta": item.get("presente_na_ultima_coleta"),
            }
            cpf_i, tr_i = str(item.get("cpf") or "").strip(), str(item.get("tr_id") or "").strip()
            for chave in {tr_i, cpf_i} - {""}:
                intencoes.setdefault(chave, []).append(ints)
            ident = cpf_i or tr_i or str(item.get("nome") or "")
            reg = so_na_fila.setdefault(ident, {"nome": item.get("nome") or "—", "cpf": cpf_i, "tr_id": tr_i, "ints": []})
            reg["ints"].append(ints)

    registros = []
    com_cadastro: set[str] = set()
    for cid, c in cadastros.items():
        if not isinstance(c, dict):
            continue
        cpf = str(c.get("cpf") or cid)
        com_cadastro.update({str(cid), cpf, str(c.get("tr_id") or "")} - {""})
        escolhas = c.get("escolas_escolhidas") if isinstance(c.get("escolas_escolhidas"), dict) else {}
        opcoes = [o for o in (escolhas.get("opcoes") or []) if isinstance(o, dict)]
        situacao = _situacao_prematricula(opcoes)
        turma_pedida = escolhas.get("turma") or c.get("turma_matriculada") or ""
        aceita = next((o for o in opcoes if str(o.get("situacao") or "").strip()
                       and not str(o["situacao"]).upper().startswith("CANCELADO")), None)
        if situacao == "cancelado":
            motivo = " | ".join(m for m in (str(o.get("motivo_cancelamento") or o.get("observacao") or "")
                                           for o in opcoes if str(o.get("situacao") or "").upper().startswith("CANCELADO")) if m)
        else:
            motivo = c.get("motivo_cancelamento") or ""
        ints = intencoes.get(str(cid)) or intencoes.get(cpf) or intencoes.get(str(c.get("tr_id") or "")) or []
        registros.append({
            "id": str(cid),
            "cpf": cpf,
            "nome_aluno": c.get("nome_aluno") or "—",
            "nome_responsavel": c.get("nome_responsavel") or "—",
            "telefone": c.get("telefone") or "—",
            "email": c.get("email") or "—",
            "endereco": c.get("endereco") or "—",
            "criterios": c.get("criterios") if isinstance(c.get("criterios"), list) else [],
            "situacao": situacao,
            "turma_pedida": turma_pedida,
            "turma_matriculada": turma_pedida if situacao == "matriculado" else (c.get("turma_matriculada") or ""),
            "escola_matriculada": (aceita or {}).get("escola", ""),
            "motivo_cancelamento": motivo,
            "opcoes": opcoes,
            "intencoes": ints,
        })
    for ident, info in so_na_fila.items():
        if ident in com_cadastro or info["cpf"] in com_cadastro or info["tr_id"] in com_cadastro:
            continue
        registros.append({
            "id": ident, "cpf": info["cpf"] or "—", "nome_aluno": info["nome"], "nome_responsavel": "—", "telefone": "—",
            "email": "—", "endereco": "—", "criterios": [], "situacao": "pendente", "turma_pedida": "",
            "turma_matriculada": "", "escola_matriculada": "", "motivo_cancelamento": "", "opcoes": [],
            "intencoes": info["ints"], "sem_cadastro": True,
        })
    registros.sort(key=lambda r: _sem_acento(r["nome_aluno"]))

    n = {s_: sum(1 for r in registros if r["situacao"] == s_) for s_ in ("matriculado", "cancelado", "pendente")}
    cartoes = []
    if registros:
        cartoes = [
            _cartao("Total de Cadastros", len(registros), "cadastros coletados", "cyan", "clipboard"),
            _cartao("Matriculados", n["matriculado"], "vaga confirmada", "lime", "student"),
            _cartao("Cancelados", n["cancelado"], "todas as opções canceladas", "rose", "mapPinOff"),
            _cartao("Pendentes", n["pendente"], "aguardando resposta", "amber", "clock"),
        ]
    atualizado = str(dados.get("atualizado_em") or "")
    return jsonify({
        "cadastros": registros,
        "cartoes": cartoes,
        "contagem": n,
        "total": len(registros),
        "atualizado_em": "" if not atualizado or atualizado.lower().startswith("x") else atualizado,
    })


@api_bp.route("/prematricula/fila")
def prematricula_fila():
    """Versão resumida usada no painel principal (widget da fila)."""
    limit = int(request.args.get("limit", 5))
    itens = sorted(_fila_prematricula(), key=_posicao_ordenavel)
    return jsonify({"itens": itens[:limit]})


def _grupo_funcao(funcao: str) -> str:
    """Agrupa a função do SERE nas categorias dos filtros/cards da tela (mesma ideia do index.html)."""
    f = _sem_acento(funcao)
    if "docente" in f or "professor" in f:
        return "Docente"
    if "gestor" in f or "diretor" in f:
        return "Direção"
    if "pedagog" in f:
        return "Pedagogos"
    if "auxiliar" in f or "assistente" in f or "secretari" in f:
        return "Auxiliares"
    return "Outros"


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _texto_matriculas(vinc: dict) -> str:
    """Uma linha com todas as matrículas lotadas na escola (só quando há mais de uma): número, cargo, admissão, local."""
    vs = [v for v in (vinc.get("vinculos_servidores") or []) if isinstance(v, dict)]
    if len(vs) < 2:
        return ""
    def uma(v: dict) -> str:
        partes = [str(v.get("numcad") or "?"), str(v.get("titcar") or "cargo não informado")]
        if v.get("datadm"):
            partes.append(f"admissão {v['datadm']}")
        if v.get("local_holerite"):
            partes.append(str(v["local_holerite"]))
        return " — ".join(partes)
    return " | ".join(uma(v) for v in vs)


@api_bp.route("/funcionarios/lista")
def funcionarios_lista():
    """
    Funcionários unificados: funcionarios.json (coletor básico: nome, cpf, funcao, email, curso_superior,
    turmas) + funcionarios_completo.json (cadastro individual, cruzado pelo CPF: telefone, sexo, documentos,
    endereço, filiação). Aceita também as chaves antigas (Nome, Cargo...). O CPF vai MASCARADO para a tela.
    Devolve os registros em "funcionarios" (tela com cards, filtros e detalhe) e, por compatibilidade,
    "colunas"/"linhas" simples (exportação CSV).
    """
    basico = _carregar_json("funcionarios.json", [])
    completo = _carregar_json("funcionarios_completo.json", [])
    basico = [f for f in basico if isinstance(f, dict)] if isinstance(basico, list) else []
    completo = [c for c in completo if isinstance(c, dict)] if isinstance(completo, list) else []
    por_cpf = {_digitos(c.get("cpf")): c for c in completo if _digitos(c.get("cpf"))}
    # Vínculo (funcionarios_matriculas.json, da automação "Vínculos dos funcionários"): terceirizado, matrícula, comprovação.
    matriculas = _carregar_json("funcionarios_matriculas.json", [])
    matriculas = [m for m in matriculas if isinstance(m, dict)] if isinstance(matriculas, list) else []
    vinc_por_cpf = {_digitos(m.get("cpf")): m for m in matriculas if _digitos(m.get("cpf"))}
    vinc_por_nome = {_sem_acento(m.get("nome")).upper(): m for m in matriculas if m.get("nome")}

    def _pega(f: dict, *chaves) -> str:
        for c in chaves:
            if f.get(c):
                return str(f[c]).strip()
        return ""

    registros = []
    vistos: set[str] = set()
    for f in basico + [c for c in completo if _digitos(c.get("cpf")) not in {_digitos(b.get("cpf")) for b in basico}]:
        cpf = _digitos(f.get("cpf"))
        if cpf and cpf in vistos:
            continue
        vistos.add(cpf)
        c = por_cpf.get(cpf, {})
        turmas = f.get("turmas") if isinstance(f.get("turmas"), list) else []
        nome = _pega(f, "nome", "Nome") or _pega(c, "nome_completo")
        funcao = _pega(f, "funcao", "Função", "Funcao", "cargo", "Cargo")
        formacao = _pega(c, "escolaridade") or _pega(f, "curso_superior", "Curso superior")
        sexo = (_pega(c, "sexo") or _pega(f, "sexo"))[:1].upper()
        detalhe = {k: v for k, v in c.items()
                   if k not in ("cpf", "data_consulta") and v not in (None, "", [])}
        if _pega(f, "curso_superior"):
            detalhe.setdefault("curso_superior", _pega(f, "curso_superior"))
        vinc = vinc_por_cpf.get(cpf) or vinc_por_nome.get(_sem_acento(nome).upper()) or {}
        vinculo = vinc.get("vinculo") or ("servidor" if vinc.get("matricula_encontrada") else "")
        na_escola = vinc.get("na_escola")
        info_vinculo = {}
        if vinc:
            info_vinculo = {
                "vinculo": {"servidor": "Servidor", "terceirizado": "Terceirizado", "estagiario": "Estagiário"}.get(vinculo, vinculo.capitalize()),
                "matricula": str(vinc.get("numcad") or ""),
                "situacao_na_escola": {True: {"holerite": "Confirmada pelo holerite", "manual": "Confirmada manualmente"}.get(
                                           vinc.get("comprovacao"), "Consta no SERE desta escola"),
                                       False: "O holerite aponta outro local de trabalho",
                                       None: "Ainda não comprovada"}.get(na_escola, "Ainda não comprovada"),
                "local_holerite": str(vinc.get("local_trabalho_holerite") or ""),
                "cargo_prefeitura": str(vinc.get("titcar") or ""),
                "data_admissao": str(vinc.get("datadm") or ""),
                "matriculas": _texto_matriculas(vinc),
                "observacao_vinculo": str(vinc.get("observacao_vinculo") or ""),
                "revisar": "; ".join(vinc.get("revisar") or []),
            }
        detalhe.update({k: v for k, v in info_vinculo.items() if v})
        registros.append({
            "nome": nome,
            "funcao": funcao,
            "grupo": _grupo_funcao(funcao),
            "vinculo": vinculo,
            "terceirizado": bool(vinc.get("terceirizado")),
            "na_escola": na_escola,
            "matricula": str(vinc.get("numcad") or ""),
            "multiplas_matriculas": bool(vinc.get("multiplas_matriculas")),
            "revisar": list(vinc.get("revisar") or []),
            "email": _pega(f, "email", "E-mail", "Email") or _pega(c, "email"),
            "telefone": _pega(c, "telefone") or _pega(f, "telefone"),
            "sexo": sexo if sexo in ("F", "M") else "",
            "cpf": _cpf_mascarado(cpf),
            "formacao": formacao,
            "turmas": str(len(turmas)) if turmas else "—",
            "lista_turmas": [str(t.get("descricao", t)).strip(" -") if isinstance(t, dict) else str(t) for t in turmas],
            "tem_cadastro_completo": bool(c),
            "detalhe": detalhe,
        })
    registros.sort(key=lambda r: _sem_acento(r["nome"]))

    contagem = {g: sum(1 for r in registros if r["grupo"] == g)
                for g in ("Docente", "Pedagogos", "Auxiliares", "Direção", "Outros")}
    cartoes = []
    if registros:
        cartoes = [
            _cartao("Total Funcionários", len(registros), "registros unificados", "cyan", "users"),
            _cartao("Docentes", contagem["Docente"], "professores em atividade", "blue", "school"),
            _cartao("Pedagogos(as)", contagem["Pedagogos"], "equipe pedagógica", "violet", "book"),
            _cartao("Auxiliares / Sec.", contagem["Auxiliares"], "apoio administrativo", "amber", "files"),
            _cartao("Direção", contagem["Direção"], "gestão escolar", "rose", "badge"),
            _cartao("Cadastro Completo", sum(1 for r in registros if r["tem_cadastro_completo"]),
                    "dados individuais coletados", "lime", "circleCheck"),
        ]
        if matriculas:
            cartoes += [
                _cartao("Terceirizados", sum(1 for r in registros if r["terceirizado"]),
                        "não constam entre os servidores do RH", "amber", "users"),
                _cartao("A revisar", sum(1 for r in registros if r["revisar"]),
                        "vínculo ou local de trabalho a conferir", "rose", "badge"),
                _cartao("Duas matrículas", sum(1 for r in registros if r["multiplas_matriculas"]),
                        "dois concursos (ex.: 20h + 20h) lotados aqui", "violet", "users"),
            ]

    colunas = [
        {"chave": "nome", "label": "Nome"},
        {"chave": "funcao", "label": "Função"},
        {"chave": "email", "label": "E-mail"},
        {"chave": "formacao", "label": "Formação"},
        {"chave": "turmas", "label": "Turmas"},
    ]
    return _resposta_lista_generica(colunas, [{k: r[k] for k in ("nome", "funcao", "email", "formacao", "turmas")}
                                              for r in registros],
                                    extras={"funcionarios": registros, "cartoes": cartoes, "contagem": contagem})


_DOCS_TRANSFERENCIA = (("guia", ("emitido_em", "assinado_secretario", "assinado_diretor")),
                       ("historico", ("emitido_em", "assinado_secretario", "assinado_diretor")))


@api_bp.route("/transferidos/lista")
def transferidos_lista():
    """
    Controle dos documentos dos alunos transferidos (transferidos.json, por CGM): guia de transferência,
    histórico escolar (emitido / assinado pela secretária / assinado pela diretora) e parecer
    (digitalizado / anexado). O status é a fração dos 6 passos da guia + histórico, como no index.html.
    """
    bruto = _carregar_json("transferidos.json", {})
    por_cgm = _turma_situacao_por_cgm()
    registros = []
    for cgm, r in (bruto.items() if isinstance(bruto, dict) else []):
        if not isinstance(r, dict):
            continue
        guia = r.get("guia") if isinstance(r.get("guia"), dict) else {}
        hist = r.get("historico") if isinstance(r.get("historico"), dict) else {}
        parecer = r.get("parecer") if isinstance(r.get("parecer"), dict) else {}
        feitos = sum(1 for doc in (guia, hist) for campo in ("emitido_em", "assinado_secretario", "assinado_diretor")
                     if doc.get(campo))
        registros.append({
            "cgm": str(cgm),
            "nome": r.get("nome") or (por_cgm.get(str(cgm)) or {}).get("nome") or "—",
            "turma": r.get("turma") or (por_cgm.get(str(cgm)) or {}).get("turma") or "—",
            "guia": {k: guia.get(k) or None for k in ("emitido_em", "assinado_secretario", "assinado_diretor", "anexado_em")},
            "historico": {k: hist.get(k) or None for k in ("emitido_em", "assinado_secretario", "assinado_diretor", "anexado_em")},
            "parecer": {k: parecer.get(k) or None for k in ("digitalizado_em", "anexado_em")},
            "feitos": feitos,
            "total_passos": 6,
            "status": "completo" if feitos == 6 else "pendente" if feitos == 0 else "parcial",
        })
    registros.sort(key=lambda r: _sem_acento(r["nome"]))

    n = {s_: sum(1 for r in registros if r["status"] == s_) for s_ in ("completo", "parcial", "pendente")}
    cartoes = []
    if registros:
        cartoes = [
            _cartao("Total", len(registros), "alunos transferidos", "rose", "transfer"),
            _cartao("Completos", n["completo"], "guia + histórico OK", "lime", "circleCheck"),
            _cartao("Parciais", n["parcial"], "documentação incompleta", "amber", "clock"),
            _cartao("Pendentes", n["pendente"], "nenhum documento emitido", "cyan", "alertFile"),
        ]
    return jsonify({
        "transferidos": registros,
        "cartoes": cartoes,
        "contagem": n,
        "total": len(registros),
        "atualizado_em": _mtime_formatado("transferidos.json"),
    })


@api_bp.route("/encaminhamentos/lista")
def encaminhamentos_lista():
    """
    Encaminhamentos do SUS (SISREG): uma linha por encaminhamento + cards de resumo e o ranking dos
    procedimentos mais comuns (mesmo conteúdo da tela "Encaminhamentos" do protótipo index.html).
    """
    alunos, cpf_invalidos = _alunos_com_encaminhamento()
    por_cgm, por_nome = _mapas_de_turma()
    colunas = [
        {"chave": "nome", "label": "Aluno"},
        {"chave": "turma", "label": "Turma"},
        {"chave": "procedimento", "label": "Procedimento"},
        {"chave": "data_solicitacao", "label": "Data da solicitação"},
        {"chave": "posicao_fila", "label": "Posição na fila"},
    ]
    linhas = []
    contagem: dict[str, int] = {}
    for a in alunos:
        turma = por_cgm.get(str(a.get("cgm", "")).strip()) or por_nome.get(_sem_acento(a.get("nome", ""))) or "—"
        for e in a.get("encaminhamentos", []):
            procedimento = str(e.get("procedimento", "")).strip()
            if procedimento:
                contagem[procedimento] = contagem.get(procedimento, 0) + 1
            linhas.append({
                "nome": a.get("nome", ""),
                "turma": turma,
                "procedimento": e.get("procedimento", ""),
                "data_solicitacao": e.get("data_solicitacao", ""),
                "posicao_fila": e.get("posicao_fila", ""),
            })
    linhas.sort(key=lambda r: (_sem_acento(r["nome"]), r["data_solicitacao"]))
    atualizado = _mtime_formatado("alunos_encaminhamento.json")
    partes = [f"{len(alunos)} aluno(s) com encaminhamento"]
    if cpf_invalidos:
        partes.append(f"{cpf_invalidos} sem CPF válido no cadastro (não consultados)")
    partes.append(f"consulta de {atualizado}" if atualizado else "consulta ainda não executada")

    # um registro por aluno pesquisado (com encaminhamento OU com erro de CPF), como na tela do protótipo
    bruto = _carregar_json("alunos_encaminhamento.json", [])
    registros = []
    for r in bruto if isinstance(bruto, list) else []:
        if not isinstance(r, dict) or not (r.get("encaminhamentos") or r.get("erro")):
            continue
        registros.append({
            "nome": r.get("nome", ""),
            "cgm": str(r.get("cgm", "")).strip(),
            "cpf": _cpf_mascarado(r.get("cpf")),
            "turma": por_cgm.get(str(r.get("cgm", "")).strip()) or por_nome.get(_sem_acento(r.get("nome", ""))) or "—",
            "erro": r.get("erro") or "",
            "encaminhamentos": r.get("encaminhamentos") or [],
        })
    registros.sort(key=lambda r: _sem_acento(r["nome"]))

    cartoes = []
    if registros:
        cartoes = [
            _cartao("Alunos Pesquisados", len(registros), "com encaminhamento ou erro de CPF", "cyan", "search"),
            _cartao("Com Encaminhamentos", len(alunos), "têm pendências", "rose", "heart"),
            _cartao("Total Procedimentos", len(linhas), "somando todos os alunos", "amber", "files"),
            _cartao("CPF Inválido/Erro", cpf_invalidos, "não puderam ser buscados", "muted", "alertFile"),
        ]
    ranking = sorted(contagem.items(), key=lambda kv: (-kv[1], _sem_acento(kv[0])))[:6]
    extras = {
        "cartoes": cartoes,
        "alunos": registros,
        "grafico": {
            "titulo": "Procedimentos Mais Comuns",
            "itens": [{"label": nome, "valor": qtd} for nome, qtd in ranking],
        },
    }
    return _resposta_lista_generica(colunas, linhas, " · ".join(partes), extras)


@api_bp.route("/fora-do-raio/lista")
def fora_do_raio_lista():
    """
    Alunos além do raio da escola. A regra (raio em km entre o CEP da escola e o CEP do aluno) é a de
    src.comum.cep_api; esta rota só mostra o resultado já gerado, com cards de resumo, o ponto da escola
    para o mapa e o cruzamento com os documentos digitalizados (comprovante de endereço no PC).
    """
    alunos, meta = _alunos_fora_do_raio()
    por_cgm, por_nome = _mapas_de_turma()
    docs_pc, tem_docs_pc = _documentos_pc_por_cgm()
    colunas = [
        {"chave": "nome", "label": "Aluno"},
        {"chave": "turma", "label": "Turma"},
        {"chave": "cgm", "label": "CGM"},
        {"chave": "cep", "label": "CEP"},
        {"chave": "distancia", "label": "Distância da escola"},
        {"chave": "comprovante", "label": "Comp. endereço"},
    ]
    linhas = []
    for a in alunos:
        cgm = str(a.get("cgm", "")).strip()
        turma = por_cgm.get(cgm) or por_nome.get(_sem_acento(a.get("nome", ""))) or "—"
        km = a.get("distancia_km")
        docs = docs_pc.get(cgm, [])
        docs_endereco = [d for d in docs if _eh_comprovante_endereco(d)]
        if not tem_docs_pc:
            tem_comprovante, comprovante = None, "—"          # documentos do PC ainda não analisados
        elif docs_endereco:
            tem_comprovante, comprovante = True, f"Sim — {len(docs_endereco)} doc(s)"
        else:
            tem_comprovante, comprovante = False, "Não encontrado"
        linhas.append({
            "nome": a.get("nome", ""),
            "turma": turma,
            "cgm": a.get("cgm", ""),
            "cep": a.get("cep", ""),
            "distancia": f"{km:.2f} km".replace(".", ",") if isinstance(km, (int, float)) else "",
            "comprovante": comprovante,
            "distancia_km": km if isinstance(km, (int, float)) else 0,
            "tem_comprovante": tem_comprovante,
            "docs_endereco": docs_endereco,
            "docs_pc": docs,
        })
    linhas.sort(key=lambda r: r["distancia_km"], reverse=True)
    maior_km = linhas[0]["distancia_km"] if linhas else 0

    if meta:
        raio = str(meta.get("raio_km", "")).replace(".", ",")
        resumo = (f"Raio de {raio} km a partir do CEP da escola · {meta.get('total_alunos_processados', '?')} "
                  f"aluno(s) analisados · análise de {meta.get('data_analise', '—')}")
    else:
        resumo = "Análise ainda não executada" if not alunos else None

    cartoes = []
    if alunos or meta:
        raio_txt = str(meta.get("raio_km", "")).replace(".", ",") if meta else ""
        cartoes.append(_cartao("Processados", meta.get("total_alunos_processados", "—") if meta else "—",
                               "alunos verificados", "cyan", "search"))
        cartoes.append(_cartao("Fora do raio", len(alunos), f"> {raio_txt} km" if raio_txt else "além do raio",
                               "rose", "mapPinOff"))
        if tem_docs_pc:
            com = sum(1 for r in linhas if r["tem_comprovante"] is True)
            cartoes.append(_cartao("Com comp. endereço", com, "têm comprovante no PC", "lime", "circleCheck"))
            cartoes.append(_cartao("Sem comp. endereço", len(linhas) - com, "pendente", "amber", "alertFile"))
        cartoes.append(_cartao("Máx. distância", f"{maior_km:.2f} km".replace(".", ","), "aluno mais distante",
                               "rose", "map"))
        cartoes.append(_cartao("CEP da escola", meta.get("cep_escola") or "—", "referência", "violet", "mapPin"))

    coord = (meta or {}).get("coordenadas_escola") or {}
    lat, lon = coord.get("latitude"), coord.get("longitude")
    extras = {
        "cartoes": cartoes,
        "maior_km": maior_km,
        "tem_docs_pc": tem_docs_pc,
        "mapa": {"latitude": lat, "longitude": lon}
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else None,
    }
    return _resposta_lista_generica(colunas, linhas, resumo, extras)


# ============================================================
# AUTOMAÇÕES — registro de execuções em background
# ============================================================
# Um dict global simples é suficiente aqui: o servidor Flask roda como um
# único processo local na máquina do usuário (mesmo modelo do restante do
# projeto — ver docstring de rotas/escolher-pasta sobre isso), então não
# há múltiplos workers disputando este estado.

_EXECUCOES: dict[str, dict[str, Any]] = {}
_EXECUCOES_LOCK = threading.Lock()


def _registrar_execucao(chave: str, execucao: Optional[ExecucaoEmBackground] = None) -> dict:
    """Cria (ou substitui) o registro de execução de uma automação."""
    registro = {
        "execucao": execucao,
        "logs": [],
        "status": StatusExecucao.EXECUTANDO.value,
        "resultado": None,
        "erro": None,
        "iniciado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        # Usados só pelo painel "Registro de atividades" do wizard (/wizard/atividade):
        "iniciado_t": time.time(),
        "terminou_t": None,
        "logs_t": [],          # hora (epoch) de cada linha de "logs", na mesma ordem
    }
    with _EXECUCOES_LOCK:
        _EXECUCOES[chave] = registro
    return registro


def _callback_para(chave: str):
    def _callback(linha: str) -> None:
        with _EXECUCOES_LOCK:
            registro = _EXECUCOES.get(chave)
            if registro is not None:
                registro["logs"].append(linha)
                registro["logs_t"].append(time.time())
    return _callback


def _observar_execucao(registro: dict, execucao: ExecucaoEmBackground) -> None:
    """Espera a execução terminar (em thread própria) e copia status/resultado/erro para o registro."""
    def _observar():
        execucao.aguardar()
        with _EXECUCOES_LOCK:
            registro["terminou_t"] = time.time()
            registro["status"] = execucao.status.value
            registro["resultado"] = execucao.resultado
            if execucao.erro:
                registro["erro"] = "".join(
                    traceback.format_exception_only(type(execucao.erro), execucao.erro)
                ).strip()

    threading.Thread(target=_observar, daemon=True).start()


def _rodar_funcao_sincrona_em_thread(chave: str, funcao, *args, **kwargs) -> None:
    """
    Para automações que ainda não têm wrapper executar_<modo> (ex.:
    gerar_pastas.main, cruzar_documentos.main, analisa_documentos_pc.main —
    funções síncronas). Roda num ExecucaoEmBackground, como as demais, para
    que TODAS tenham o mesmo comportamento: logs (print/log) capturados para
    o polling de status e cancelamento pelo botão "Cancelar".
    """
    registro = _registrar_execucao(chave)
    execucao = ExecucaoEmBackground(callback=_callback_para(chave))
    registro["execucao"] = execucao
    execucao.iniciar(lambda: funcao(*args, **kwargs))
    _observar_execucao(registro, execucao)


def _rodar_coroutine_em_thread(chave: str, coroutine_factory) -> None:
    """
    Para automações async sem wrapper dedicado (ex.:
    src.automacao.sisreg.consultar_encaminhamentos_sisreg,
    src.automacao.rematricula.executar_rematricula,
    src.automacao.pre_matricula.executar_processo_completo). Mesmo propósito
    de _rodar_funcao_sincrona_em_thread, mas para uma coroutine — o
    cancelamento aqui cancela a tarefa asyncio (os `finally` do script rodam).
    `coroutine_factory` é uma função zero-argumentos que RETORNA a coroutine.
    """
    registro = _registrar_execucao(chave)
    execucao = ExecucaoEmBackground(callback=_callback_para(chave))
    registro["execucao"] = execucao
    execucao.iniciar(coroutine_factory())
    _observar_execucao(registro, execucao)


def _iniciar_via_execucao_gui(chave: str, funcao_executar, log_inicial: str | None = None, **kwargs) -> None:
    """
    Para automações que JÁ têm um wrapper `executar_<modo>` pronto (ver
    src/automacao/executar_*.py) — estes retornam um ExecucaoEmBackground
    e o próprio módulo já cuida da thread e da captura de print/log.
    """
    registro = _registrar_execucao(chave)
    callback = _callback_para(chave)
    if log_inicial:
        callback(log_inicial)
    execucao = funcao_executar(callback=callback, **kwargs)
    registro["execucao"] = execucao
    _observar_execucao(registro, execucao)


AUTOMACOES_DISPONIVEIS = [
    {"chave": "turmas", "nome": "Turmas", "descricao": "Coleta no SERE as turmas e a lista de alunos de cada turma (turmas.json)."},
    {"chave": "alunos", "nome": "Alunos", "descricao": "Coleta o cadastro dos alunos no SERE: modo básico (alunos.py) ou completo (alunos_completo.py)."},
    {"chave": "funcionarios", "nome": "Funcionários / Servidores", "descricao": "Coleta no SERE a lista e o cadastro dos funcionários e servidores da escola: modo básico (só a lista) ou completo (cadastro de cada um, pelo CPF)."},
    {"chave": "vinculos", "nome": "Vínculos dos funcionários", "descricao": "Cruza os funcionários do SERE com o RH da Prefeitura (matrícula), comprova pelo holerite que trabalham nesta escola e marca os terceirizados (que não constam no RH)."},
    {"chave": "gerar_pastas", "nome": "Gerar pastas", "descricao": "Cria pastas dos alunos automaticamente."},
    {"chave": "analisa_pasta", "nome": "Analisa documentos da pasta", "descricao": "Analisa e organiza documentos diretamente da pasta."},
    {"chave": "analisa_sere", "nome": "Analisa documentos do SERE", "descricao": "Analisa documentos disponíveis no SERE."},
    {"chave": "documentos", "nome": "Documentos", "descricao": "Remove um tipo de documento de todos os alunos do SERE."},
    {"chave": "limpeza", "nome": "Limpeza total de documentos", "descricao": "Remove todos os arquivos de todos os alunos das turmas selecionadas."},
    {"chave": "aluno", "nome": "Alunos por CGM", "descricao": "Envia ao SERE os documentos da pasta de digitalização só dos alunos que você informar pelo CGM."},
    {"chave": "espec", "nome": "Upload de um tipo de documento", "descricao": "Envia ao SERE um tipo específico de documento (da pasta de digitalização) para os alunos escolhidos."},
    {"chave": "validar", "nome": "Validar documentos", "descricao": "Valida (✔) todos os documentos pendentes das turmas selecionadas."},
    {"chave": "cruzamento", "nome": "Cruzamento de docs", "descricao": "Cruza informações e valida documentações (SERE x pasta local)."},
    {"chave": "cep", "nome": "CEP", "descricao": "Consulta, valida e completa endereços via CEP; calcula distância aluno-escola."},
    {"chave": "sus", "nome": "Encaminhamentos do SUS", "descricao": "Consulta no SISREG (pelo CPF) os encaminhamentos dos alunos escolhidos; os demais alunos mantêm o resultado anterior."},
    {"chave": "transferidos_fila", "nome": "Fila de transferidos", "descricao": "Lista, a partir do turmas.json, todos os transferidos e marca quem entra no processo pela data de corte (fila_transferidos.json). É refeita sozinha cada vez que as turmas são coletadas."},
    {"chave": "transferidos_gerar", "nome": "Gerar guia e histórico", "descricao": "Emite, assina e baixa do SERE o histórico escolar e a guia de transferência dos alunos da fila, salvando em TRANSFERENCIAS."},
    {"chave": "transferidos", "nome": "Enviar transferidos ao SERE", "descricao": "Envia à pasta virtual do SERE a guia, o histórico e o parecer dos transferidos que estão nas pastas de TRANSFERENCIAS."},
    {"chave": "pareceres_transferidos", "nome": "Pareceres dos transferidos", "descricao": "Lê o QR dos pareceres digitalizados, arquiva em PARECERES, comprime se passar do limite e envia ao SERE, numa rotina só."},
    {"chave": "parecer_fund", "nome": "Pareceres fundamental", "descricao": "Gera o parecer de cada aluno do Fundamental a partir do modelo Word da turma (envie os modelos em Configurações → Modelos de parecer). Cada parecer leva um QR code no fim."},
    {"chave": "parecer_rco", "nome": "Pareceres infantil", "descricao": "Baixa do RCO os pareceres (PDF) dos alunos matriculados no Infantil IV e V. O RCO manda um código por e-mail: a tela pede para você digitar."},
    {"chave": "comprimir", "nome": "Comprimir documentos", "descricao": "Encolhe os PDFs e imagens (alunos, guias, históricos e pareceres) que passam do limite de 1,5 MB do SERE, guardando os originais."},
    {"chave": "coleta_emails", "nome": "Coleta e-mails", "descricao": "Coleta os e-mails de outras escolas da rede municipal."},
    {"chave": "agendador", "nome": "Criar rotinas no agendador", "descricao": "Cria rotinas automáticas no Agendador de Tarefas do Windows."},
    {"chave": "backup", "nome": "Backup dos dados", "descricao": "Realiza backup de toda base de dados e arquivos."},
    {"chave": "avisos", "nome": "Mandar avisos", "descricao": "Comunicados oficiais por e-mail: de escola para escolas de Ponta Grossa e de escola para os pais de alunos novos (pré-matrícula). Por enquanto só simula ou envia um e-mail de teste."},
    {"chave": "compara_anos", "nome": "Compara anos", "descricao": "Compara o turmas.json de dois anos e gera uma planilha: quem continua (e se foi promovido), quem saiu, quem entrou e os transferidos."},
    {"chave": "termos", "nome": "Gerar termos de ciência", "descricao": "Gera termos de ciência para os funcionários."},
    {"chave": "mapear_pastas", "nome": "Mapear pastas dos alunos", "descricao": "Mapeia e organiza caminhos das pastas dos alunos."},
    {"chave": "mascara", "nome": "Máscara de dados", "descricao": "Aplica máscara em dados sensíveis (LGPD)."},
    {"chave": "rematricula", "nome": "Rematrícula alunos no SERE", "descricao": "Realiza rematrícula dos alunos no SERE."},
    {"chave": "prematricula_completa", "nome": "Processo de pré-matrícula", "descricao": "Roda o processo completo de pré-matrícula (coleta, cadastro, pendentes, contatos)."},
]

# Automações que já aparecem na lista/menu mas cuja automação de fato
# (o script correspondente) ainda não existe no código-fonte do projeto —
# respondem 501 explicitamente em vez de fingir sucesso.
AUTOMACOES_NAO_IMPLEMENTADAS = {
    "agendador",
}


@api_bp.route("/automacoes/lista")
def automacoes_lista():
    itens = []
    for item in AUTOMACOES_DISPONIVEIS:
        script = _registro.obter(item["chave"])
        itens.append(dict(item, recursos=list(script.recursos)) if script else item)
    return jsonify({"itens": itens})


# Coletas que gravam o MESMO arquivo, ou que dependem dele, não podem rodar ao mesmo tempo
# (duas sessões no SERE escrevendo turmas.json/alunos.json, ou o modo completo lendo um
# turmas.json que ainda está sendo escrito). O wizard usa chaves próprias ("wizard_*").
_GRUPOS_EXCLUSIVOS = [
    {"turmas", "wizard_turmas"},
    {"alunos", "wizard_alunos"},
]
_DEPENDE_DE_TURMAS = {"alunos"}          # no modo completo a fila vem de turmas.json


def _conflito_em_execucao(chave: str, modo: str = "") -> Optional[str]:
    """Devolve uma mensagem se algo que conflita com `chave` está rodando agora; senão None."""
    def rodando(k: str) -> bool:
        return (_EXECUCOES.get(k) or {}).get("status") == StatusExecucao.EXECUTANDO.value

    with _EXECUCOES_LOCK:
        for grupo in _GRUPOS_EXCLUSIVOS:
            if chave in grupo:
                for outra in sorted(grupo - {chave}):
                    if rodando(outra):
                        return (f"A coleta equivalente ('{outra}') já está em execução e grava o mesmo arquivo. "
                                "Aguarde terminar ou cancele.")
        if chave in _DEPENDE_DE_TURMAS and modo == "completo" and (rodando("turmas") or rodando("wizard_turmas")):
            return "A coleta de Turmas está em execução; o modo completo lê o turmas.json dela. Aguarde terminar."
    return None


def _nomes_de_turma(script, turmas_json: dict) -> list[str]:
    return script.turmas_de() if script.turmas_de else list(turmas_json)


def _executar_plano(chave: str, plano) -> None:
    """Dispara o plano de um script registrado, no formato de execução que ele pediu."""
    if plano.tipo == "gui":
        _iniciar_via_execucao_gui(chave, plano.funcao, log_inicial=plano.log_inicial or None, **plano.kwargs)
    elif plano.tipo == "coroutine":
        if plano.log_inicial:
            _callback_para(chave)(plano.log_inicial)
        _rodar_coroutine_em_thread(chave, lambda: plano.funcao(**plano.kwargs))
    elif plano.tipo == "sync":
        if plano.log_inicial:
            _callback_para(chave)(plano.log_inicial)
        _rodar_funcao_sincrona_em_thread(chave, plano.funcao, **plano.kwargs)
    else:
        raise ValueError(f"Tipo de plano desconhecido: {plano.tipo}")


def _executar_registrado(script, chave: str, payload: dict, turmas_json: dict) -> None:
    """ValueError = pedido inválido (vira 400 com a mensagem, pronta para o usuário)."""
    if script.usa_turmas_json and not turmas_json:
        raise ValueError("Ainda não existe turmas.json: execute primeiro a automação 'Turmas'.")
    opcoes = _opcoes.opcoes_do_payload(payload, script.recursos, _nomes_de_turma(script, turmas_json),
                                       cgm_obrigatorio=script.cgm_obrigatorio)
    if script.validar_extras:
        script.validar_extras(payload)
    plano = script.planejar(opcoes, payload, turmas_json, {"args_flags": _args_das_flags(chave)})
    _executar_plano(chave, plano)


@api_bp.route("/automacoes/<string:chave>/componentes")
def automacoes_componentes(chave):
    """O que a tela precisa para montar os componentes compartilhados deste script."""
    script = _registro.obter(chave)
    if script is None:
        return jsonify({"registrado": False})
    turmas_json = _carregar_json("turmas.json", {})
    resposta = {
        "registrado": True,
        "recursos": list(script.recursos),
        "confirmar": script.confirmar,
        "aviso_confirmacao": script.aviso_confirmacao,
        "ajuda_teste": script.ajuda_teste,
        "ajuda_debug": script.ajuda_debug,
        "cgm_obrigatorio": script.cgm_obrigatorio,
        "extras": script.extras(),
        "tem_turmas": bool(turmas_json) or script.turmas_de is not None,
        "usa_turmas_json": script.usa_turmas_json,
        "turmas": None,
    }
    if _opcoes.RECURSO_TURMA in script.recursos:
        grupos = _opcoes.agrupar_turmas(_nomes_de_turma(script, turmas_json))
        resposta["turmas"] = [{"rotulo": g, "turmas": ts} for g, ts in grupos.items()]
    return jsonify(resposta)


@api_bp.route("/automacoes/<string:chave>/previa", methods=["POST"])
def automacoes_previa(chave):
    """"O que será processado": conta quem seria afetado com as escolhas atuais, sem executar nada."""
    script = _registro.obter(chave)
    if script is None:
        return jsonify({"erro": f"Automação '{chave}' não usa seleção compartilhada."}), 404
    payload = request.get_json(silent=True) or {}
    turmas_json = _carregar_json("turmas.json", {})
    try:
        opcoes = _opcoes.opcoes_do_payload(payload, script.recursos, _nomes_de_turma(script, turmas_json),
                                           cgm_obrigatorio=script.cgm_obrigatorio)
        if script.previa:                        # ex.: avisos — quantos destinatários; o texto só é cobrado ao executar
            return jsonify({"total": None, "texto": script.previa(payload) or None})
        if script.validar_extras:
            script.validar_extras(payload)       # ex.: tipo de documento — o erro aparece já na prévia
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    if script.turmas_de is not None:          # rematrícula: nomes-base de turma, não alunos
        alvo = list(opcoes.turmas) or script.turmas_de()
        return jsonify({"total": None, "turmas": alvo, "texto": "Turmas: " + ", ".join(alvo) + "."})
    if not script.tem_selecao_de_alunos:
        return jsonify({"total": None, "texto": None})
    if not turmas_json:
        return jsonify({"erro": "Ainda não existe turmas.json: execute primeiro a automação 'Turmas'."}), 400
    sel = _opcoes.selecionar_alunos(turmas_json, turmas=opcoes.turmas, matriculados=opcoes.matriculados,
                                    transferidos=opcoes.transferidos, cgms=opcoes.cgms)
    return jsonify({
        "total": sel.total, "matriculados": sel.matriculados, "transferidos": sel.transferidos,
        "turmas": sel.turmas, "cgms_nao_encontrados": sel.cgms_nao_encontrados,
        "texto": _opcoes.descrever_selecao(sel, len(opcoes.cgms)),
    })


@api_bp.route("/cgm/analisar", methods=["POST"])
def cgm_analisar():
    """Confere o texto digitado no campo de CGM: quais valem, quais não, e se existem em turmas.json."""
    payload = request.get_json(silent=True) or {}
    r = _opcoes.analisar_cgms(payload.get("texto"))
    turmas_json = _carregar_json("turmas.json", {})
    existentes = {str(a.get("CGM", "")).strip() for alunos in turmas_json.values() for a in alunos} if turmas_json else None
    nao_encontrados = [c for c in r.validos if existentes is not None and c not in existentes]
    partes = [f"{len(r.validos)} CGM(s) válido(s)"]
    if r.invalidos:
        partes.append(f"{len(r.invalidos)} inválido(s): " + ", ".join(r.invalidos[:5]))
    if r.repetidos:
        partes.append(f"{r.repetidos} repetido(s) removido(s)")
    if nao_encontrados:
        partes.append(f"{len(nao_encontrados)} não está(ão) em turmas.json")
    return jsonify({
        "validos": list(r.validos), "invalidos": list(r.invalidos), "repetidos": r.repetidos,
        "nao_encontrados": nao_encontrados, "texto": " · ".join(partes),
    })


@api_bp.route("/automacoes/<string:chave>/executar", methods=["POST"])
def automacoes_executar(chave):
    if chave in AUTOMACOES_NAO_IMPLEMENTADAS:
        return jsonify({
            "status": "erro",
            "mensagem": f"Automação '{chave}' ainda não foi implementada no código-fonte.",
        }), 501

    with _EXECUCOES_LOCK:
        em_andamento = (_EXECUCOES.get(chave) or {}).get("status") == StatusExecucao.EXECUTANDO.value
    if em_andamento:
        return jsonify({
            "status": "erro",
            "mensagem": "Esta automação já está em execução. Aguarde terminar ou cancele.",
        }), 409

    payload = request.get_json(silent=True) or {}
    turmas_selecionadas = payload.get("turmas") or []
    modo_teste = bool(payload.get("modo_teste", False))
    modo = str(payload.get("modo") or "").strip().lower()

    conflito = _conflito_em_execucao(chave, modo)
    if conflito:
        return jsonify({"status": "erro", "mensagem": conflito}), 409

    try:
        turmas_completas = _carregar_json("turmas.json", {})

        script = _registro.obter(chave)
        if script is None:
            return jsonify({"erro": f"Automação '{chave}' não encontrada"}), 404
        # Todas as automações passam pelo registro: opções compartilhadas + execução do plano.
        _executar_registrado(script, chave, payload, turmas_completas)

    except ImportError as exc:       # inclui ModuleNotFoundError e "cannot import name ..."
        return jsonify({
            "status": "erro",
            "mensagem": f"Módulo da automação '{chave}' não pôde ser carregado: {exc}",
        }), 500
    except ValueError as exc:
        # Pré-requisito de configuração faltando (ex.: pasta de digitalização,
        # unidade escolar, credenciais) — erro esperado, não um bug.
        return jsonify({"status": "erro", "mensagem": str(exc)}), 400

    return jsonify({
        "status": "executando",
        "mensagem": f"Automação '{chave}' iniciada em segundo plano.",
        "execucao_id": chave,
    })


@api_bp.route("/automacoes/<string:chave>/status")
def automacoes_status(chave):
    """
    Estado mais recente da última execução disparada para esta automação
    (logs acumulados, status, resultado/erro). Pronta para polling de uma
    futura barra de progresso na interface.
    """
    with _EXECUCOES_LOCK:
        registro = _EXECUCOES.get(chave)
        if registro is None:
            return jsonify({"status": "nunca_executado", "logs": []})
        execucao = registro.get("execucao")
        return jsonify({
            "status": registro["status"],
            "cancelando": bool(execucao is not None and execucao.cancelamento_solicitado
                               and registro["status"] == StatusExecucao.EXECUTANDO.value),
            "logs": registro["logs"][-200:],
            "erro": registro["erro"],
            "iniciado_em": registro["iniciado_em"],
            "tem_resultado": registro["resultado"] is not None,
            # Informação que a automação está esperando do usuário (ex.: código 2FA do RCO), ou null.
            "pergunta": (_entrada.pergunta_pendente(chave)
                         if registro["status"] == StatusExecucao.EXECUTANDO.value else None),
        })


@api_bp.route("/automacoes/<string:chave>/resposta", methods=["POST"])
def automacoes_resposta(chave):
    """
    Entrega ao script em execução a resposta a uma pergunta dele (ver src.comum.entrada_usuario).
    payload: {"id": "<id da pergunta, vindo do /status>", "valor": "texto"}
    Resposta recusada pela validação do script volta 400 com a mensagem; a pergunta continua aberta.
    """
    payload = request.get_json(silent=True) or {}
    ok, mensagem = _entrada.responder(chave, str(payload.get("id") or ""), str(payload.get("valor") or ""))
    if not ok:
        return jsonify({"status": "erro", "mensagem": mensagem}), 400
    return jsonify({"status": "ok", "mensagem": mensagem})


@api_bp.route("/automacoes/<string:chave>/cancelar", methods=["POST"])
def automacoes_cancelar(chave):
    """
    Pede o cancelamento da execução em andamento desta automação. Responde na
    hora; o término de fato (status "cancelado") aparece no /status — pode levar
    alguns segundos (ex.: a análise do SERE para no próximo aluno e fecha o
    navegador).
    """
    with _EXECUCOES_LOCK:
        registro = _EXECUCOES.get(chave)
        execucao = registro.get("execucao") if registro else None
        executando = bool(registro and registro["status"] == StatusExecucao.EXECUTANDO.value)

    if not executando or execucao is None:
        return jsonify({"status": "erro", "mensagem": "Nenhuma execução em andamento para cancelar."}), 409

    execucao.cancelar()
    _entrada.cancelar_pendente(chave)      # a caixa de pergunta (se aberta) deixa de valer
    return jsonify({"status": "ok", "mensagem": "Cancelamento solicitado. Encerrando…"})


# ============================================================
# FLAGS DAS AUTOMAÇÕES (aba "Configuração" de cada automação)
# ============================================================
# As flags NÃO são listadas à mão: são lidas do próprio script, procurando as
# chamadas parser.add_argument("--x", action="store_true", help="...") no
# código-fonte (via ast, sem importar o módulo — importar executaria código do
# script). Só automações cujo wrapper aceita argumentos entram aqui; hoje é a
# análise do SERE (executar_analisa recebe args_extras). Para incluir outra,
# basta mapear a chave ao módulo abaixo (e o wrapper dela repassar os args).

_MODULOS_COM_FLAGS = {
    "analisa_sere": "src.relatorios.analisa_arquivos_sere",
}

# Flags que são MODOS excludentes, na ordem de prioridade do script (um
# if/elif: a primeira que estiver ligada vence). Mostradas como escolha única.
_FLAGS_MODO = {
    "analisa_sere": ["--todos", "--transferidos", "--turma", "--rapido", "--alunos", "--erros"],
}

_ROTULOS_FLAGS = {
    "--todos": "Todos os alunos (matriculados e transferidos)",
    "--transferidos": "Somente transferidos",
    "--turma": "Escolher turmas",
    "--rapido": "Modo rápido (só os não completos)",
    "--alunos": "Somente os CGMs de CGM_ANALISE",
    "--erros": "Reprocessar só os que falharam",
}

_AVISOS_FLAGS = {
    "--turma": "Abre a escolha de turmas no terminal onde o servidor está rodando — responda lá.",
    "--alunos": "Usa a lista CGM_ANALISE definida no topo do script.",
}


def _flags_do_script(chave: str) -> list[dict]:
    """Lê do código-fonte do script as flags booleanas (store_true), na ordem em que aparecem."""
    import ast
    import importlib.util

    modulo = _MODULOS_COM_FLAGS.get(chave)
    if not modulo:
        return []
    try:
        spec = importlib.util.find_spec(modulo)
        if spec is None or not spec.origin:
            return []
        arvore = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    except (ImportError, OSError, SyntaxError, ValueError):
        return []

    achadas = []
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "add_argument"):
            continue
        nomes = [a.value for a in no.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("--")]
        kw = {k.arg: k.value for k in no.keywords}
        acao = kw.get("action")
        if not nomes or not (isinstance(acao, ast.Constant) and acao.value == "store_true"):
            continue
        ajuda = kw.get("help")
        achadas.append((no.lineno, nomes[0], ajuda.value if isinstance(ajuda, ast.Constant) else ""))

    grupo_modo = set(_FLAGS_MODO.get(chave, []))
    return [
        {
            "flag": flag,
            "rotulo": _ROTULOS_FLAGS.get(flag, flag),
            "descricao": ajuda,
            "aviso": _AVISOS_FLAGS.get(flag, ""),
            "grupo": "modo" if flag in grupo_modo else None,
        }
        for _, flag, ajuda in sorted(achadas)
    ]


def _args_das_flags(chave: str) -> list[str]:
    """Flags salvas para a automação, filtradas pelas que o script realmente tem; no
    máximo UM modo (o de maior prioridade, como o script faria)."""
    conhecidas = {f["flag"]: f for f in _flags_do_script(chave)}
    salvas = [f for f in _config.flags_automacao(chave) if f in conhecidas]
    modos = [f for f in _FLAGS_MODO.get(chave, []) if f in salvas]
    return [f for f in salvas if conhecidas[f]["grupo"] != "modo"] + modos[:1]


def _estado_flags(chave: str) -> dict:
    ativas = set(_args_das_flags(chave))
    flags = [dict(f, ativa=f["flag"] in ativas) for f in _flags_do_script(chave)]
    return {"chave": chave, "flags": flags}


@api_bp.route("/automacoes/<string:chave>/flags", methods=["GET"])
def automacoes_flags_obter(chave):
    """Flags do script desta automação e quais estão ligadas (lista vazia se não houver)."""
    return jsonify(_estado_flags(chave))


@api_bp.route("/automacoes/<string:chave>/flags", methods=["POST"])
def automacoes_flags_salvar(chave):
    """
    Salva as flags ligadas. payload: {"flags": ["--rapido"]}
    Rejeita flag que o script não tem e mais de um modo ao mesmo tempo.
    """
    conhecidas = {f["flag"]: f for f in _flags_do_script(chave)}
    if not conhecidas:
        return jsonify({"erro": "Esta automação não tem opções configuráveis."}), 400

    payload = request.get_json(silent=True) or {}
    pedidas = payload.get("flags")
    if not isinstance(pedidas, list) or not all(isinstance(f, str) for f in pedidas):
        return jsonify({"erro": "Envie 'flags' como uma lista de textos."}), 400

    desconhecidas = [f for f in pedidas if f not in conhecidas]
    if desconhecidas:
        return jsonify({"erro": f"Opção inexistente neste script: {', '.join(desconhecidas)}"}), 400
    if len([f for f in pedidas if conhecidas[f]["grupo"] == "modo"]) > 1:
        return jsonify({"erro": "Escolha apenas um modo de execução."}), 400

    _config.definir_flags_automacao(chave, list(dict.fromkeys(pedidas)))
    resposta = _estado_flags(chave)
    resposta["mensagem"] = "Opções salvas."
    return jsonify(resposta)


# ============================================================
# SISTEMA — seleção de pasta via janela nativa do Windows (PowerShell/WinForms)
# ============================================================
# Como o Flask roda localmente na mesma máquina Windows que tem o
# SERE, o jeito mais direto de escolher uma pasta é abrir a janela
# nativa do Explorer via tkinter.filedialog, no processo do backend.
# O navegador não participa da escolha — só dispara a requisição e
# recebe de volta o caminho absoluto (ex: C:\ARQUIVOS\ESCOLA JUDITH\...).
#
# IMPORTANTE: tkinter precisa rodar numa janela do sistema operacional,
# então isso só funciona quando o servidor Flask roda diretamente na
# máquina Windows do usuário (não em contêiner, WSL sem X server, ou
# servidor remoto/hospedado). Se a automação não puder abrir GUI,
# ela cai automaticamente num fallback simples (ver except abaixo).

@api_bp.route("/sistema/escolher-pasta", methods=["POST"])
def escolher_pasta():
    """
    Abre o diálogo nativo do Windows para escolher uma pasta e devolve
    o caminho absoluto selecionado. Se `payload["destino"]` vier
    preenchido com "digitalizacao" ou "modelos", o caminho escolhido já é
    persistido em config_usuario.json (src.comum.configuracao) — assim o
    wizard de 1ª execução e a tela de automações usam o mesmo endpoint.

    payload opcional: {"titulo": "Escolha a pasta raiz dos alunos", "destino": "digitalizacao"}
    """
    payload = request.get_json(silent=True) or {}
    titulo = payload.get("titulo", "Selecione a pasta")
    destino = payload.get("destino")

    try:
        from src.comum.dialogo_pasta import escolher_pasta as _dialogo_pasta

        # Windows: seletor nativo via PowerShell (sem depender do tkinter);
        # WSL/Linux: tkinter. Ver src/comum/dialogo_pasta.py.
        caminho = _dialogo_pasta(titulo)

        if not caminho:
            # Usuário cancelou o diálogo
            return jsonify({"caminho": None, "cancelado": True})

        if destino == "digitalizacao":
            _config.definir_pasta_digitalizacao(caminho)
        elif destino == "modelos":
            _config.definir_pasta_modelos(caminho)

        return jsonify({"caminho": caminho, "cancelado": False})

    except Exception as exc:
        # Ambiente sem suporte a GUI (ex.: servidor headless/remoto).
        # Devolve erro explícito em vez de mascarar com um caminho falso.
        return jsonify({
            "caminho": None,
            "erro": f"Não foi possível abrir o explorador de arquivos neste ambiente: {exc}",
        }), 500


# ============================================================
# CONFIGURAÇÕES — pasta de digitalização (GET lê, POST grava com validação)
# ============================================================

def _estado_pasta_digitalizacao() -> dict:
    """Estado completo da pasta de digitalização, usado por GET e POST."""
    em_uso = _config.pasta_digitalizacao()
    padrao = _config.pasta_digitalizacao_padrao()
    return {
        "caminho": str(em_uso) if em_uso else None,
        "configurada": _config.pasta_digitalizacao_configurada(),
        "usando_padrao": not _config.pasta_digitalizacao_personalizada(),
        "padrao": str(padrao),
        "padrao_existe": padrao.is_dir(),
    }


def _estado_data_corte() -> dict:
    return {"data_corte": _config.data_corte_transferidos().strftime("%d/%m/%Y"),
            "personalizada": _config.data_corte_transferidos_configurada(),
            "padrao": _config.data_corte_padrao().strftime("%d/%m/%Y")}


@api_bp.route("/configuracoes/data-corte", methods=["GET"])
def configuracao_data_corte_obter():
    """Data de corte do processo de transferidos (a partir dela, inclusive, o processo é automático)."""
    return jsonify(_estado_data_corte())


@api_bp.route("/configuracoes/data-corte", methods=["POST"])
def configuracao_data_corte_salvar():
    """payload: {"data_corte": "dd/mm/aaaa"} grava; {"usar_padrao": true} volta ao padrão (22/06 do ano letivo)."""
    payload = request.get_json(silent=True) or {}
    try:
        if payload.get("usar_padrao"):
            _config.definir_data_corte_transferidos("")
            mensagem = "Voltou à data padrão."
        else:
            if not str(payload.get("data_corte") or "").strip():
                return jsonify({"erro": "Informe a data de corte (dd/mm/aaaa)."}), 400
            _config.definir_data_corte_transferidos(payload["data_corte"])
            mensagem = "Data de corte salva."
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    resposta = _estado_data_corte()
    resposta.update({"status": "ok", "mensagem": mensagem})
    return jsonify(resposta)


@api_bp.route("/configuracoes/pasta-digitalizacao", methods=["GET"])
def configuracao_pasta_digitalizacao_obter():
    """
    Estado da pasta de digitalização. Sem escolha do usuário, vale a pasta
    padrão dados/<ano atual>/DIGITALIZAÇÃO (se existir).
    """
    return jsonify(_estado_pasta_digitalizacao())


@api_bp.route("/configuracoes/pasta-digitalizacao", methods=["POST"])
def configuracao_pasta_digitalizacao_salvar():
    """
    Define a pasta de digitalização.

    payload: {"usar_padrao": true}
        Volta para a pasta padrão dados/<ano>/DIGITALIZAÇÃO (cria a pasta se
        ainda não existir). Não grava caminho fixo: acompanha o ano.
    payload: {"caminho": "/home/usuario/.../DIGITALIZAÇÃO"}
        Pasta personalizada. Ao contrário de
        configuracao.definir_pasta_digitalizacao (que grava sem validar),
        aqui só é salva se for absoluta e existir como pasta NESTE
        computador.
    """
    payload = request.get_json(silent=True) or {}

    if payload.get("usar_padrao"):
        padrao = _config.pasta_digitalizacao_padrao()
        criada = not padrao.is_dir()
        try:
            padrao.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return jsonify({"erro": f"Não foi possível criar a pasta padrão {padrao}: {exc}"}), 500
        _config.usar_pasta_digitalizacao_padrao()
        resposta = _estado_pasta_digitalizacao()
        resposta.update({
            "status": "ok",
            "mensagem": ("Pasta padrão criada e em uso." if criada else "Usando a pasta padrão."),
        })
        return jsonify(resposta)

    bruto = str(payload.get("caminho") or "").strip().strip('"').strip("'")
    if not bruto:
        return jsonify({"erro": "Informe o caminho completo da pasta."}), 400

    # Caminho de Windows (C:\\...) num servidor que roda em Linux/WSL.
    if os.name != "nt" and len(bruto) > 2 and bruto[1] == ":" and bruto[0].isalpha():
        letra = bruto[0].lower()
        sugestao = "/mnt/" + letra + "/" + bruto[3:].replace("\\", "/")
        return jsonify({
            "erro": "Este servidor está rodando em Linux/WSL e não enxerga caminhos "
                    "no formato do Windows (letra de unidade). Use o formato Linux, por exemplo: " + sugestao,
        }), 400

    caminho = Path(os.path.abspath(os.path.expanduser(bruto)))
    if not caminho.is_dir():
        return jsonify({"erro": f"A pasta não existe neste computador: {caminho}"}), 400

    _config.definir_pasta_digitalizacao(caminho)
    resposta = _estado_pasta_digitalizacao()
    resposta.update({"status": "ok", "mensagem": "Pasta de digitalização salva."})
    return jsonify(resposta)


# ============================================================
# PRÉ-MATRÍCULA — login e senha do portal (credenciais/.env)
# ============================================================

# Valores que significam "ainda não configurado" (mesmos placeholders de
# src.comum.credenciais e de pre_matricula._PLACEHOLDERS_PREMATRICULA).
_PLACEHOLDERS_PREMATRICULA = {"", "matricula", "senha_prematricula"}


def _estado_credenciais_prematricula() -> dict:
    """
    Estado atual das credenciais da pré-matrícula. A senha NUNCA é devolvida:
    só se informa se existe uma salva. O login (matrícula) não é segredo e
    volta para preencher o formulário.
    """
    login = (os.getenv("PREMATRICULA_LOGIN") or "").strip()
    senha = os.getenv("PREMATRICULA_SENHA") or ""
    login_ok = login not in _PLACEHOLDERS_PREMATRICULA
    senha_ok = senha not in _PLACEHOLDERS_PREMATRICULA
    return {
        "login": login if login_ok else "",
        "senha_salva": senha_ok,
        "configurada": login_ok and senha_ok,
    }


@api_bp.route("/configuracoes/prematricula", methods=["GET"])
def configuracao_prematricula_obter():
    return jsonify(_estado_credenciais_prematricula())


@api_bp.route("/configuracoes/prematricula", methods=["POST"])
def configuracao_prematricula_salvar():
    """
    Salva PREMATRICULA_LOGIN e PREMATRICULA_SENHA em credenciais/.env e já as
    aplica no processo em execução (sem reiniciar).

    payload: {"login": "...", "senha": "..."}
        A senha pode vir vazia SE já houver uma salva — assim dá para trocar só
        o login sem redigitar a senha.
    """
    payload = request.get_json(silent=True) or {}
    login = str(payload.get("login") or "").strip()
    senha = str(payload.get("senha") or "")
    estado = _estado_credenciais_prematricula()

    if not login or login in _PLACEHOLDERS_PREMATRICULA:
        return jsonify({"erro": "Informe o login (matrícula) da pré-matrícula."}), 400
    if not senha and not estado["senha_salva"]:
        return jsonify({"erro": "Informe a senha da pré-matrícula."}), 400
    if senha in _PLACEHOLDERS_PREMATRICULA and senha:
        return jsonify({"erro": "Essa senha é um valor de exemplo. Informe a senha real."}), 400

    valores = {"PREMATRICULA_LOGIN": login}
    if senha:
        valores["PREMATRICULA_SENHA"] = senha
    try:
        _persistir_env(valores)
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível gravar credenciais/.env: {exc}"}), 500

    aplicado = _recarregar_credenciais_em_runtime()
    resposta = _estado_credenciais_prematricula()
    resposta["status"] = "ok"
    resposta["mensagem"] = (
        "Credenciais da pré-matrícula salvas e já aplicadas — pode usar agora, sem reiniciar."
        if aplicado else
        "Credenciais da pré-matrícula salvas em credenciais/.env. Reinicie o Auto SERE para aplicá-las."
    )
    return jsonify(resposta)


# ============================================================
# GMAIL — e-mail remetente e senha de app (credenciais/.env)
# ============================================================

_PLACEHOLDERS_EMAIL = {"", "email@exemplo.com"}
_PLACEHOLDERS_SENHA_APP = {"", "senha_app_email"}
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_SENHA_APP = re.compile(r"^[A-Za-z]{16}$")


def _normalizar_senha_app(bruta: str) -> str:
    """Tira TODO espaço (inclusive o não separável de quem copia da página do Google)."""
    return "".join(str(bruta).split())


def _estado_credenciais_gmail() -> dict:
    """A senha de app NUNCA é devolvida: só se informa se existe uma salva."""
    email = (os.getenv("EMAIL_REMETENTE") or "").strip()
    senha = os.getenv("EMAIL_SENHA_APP") or ""
    email_ok = email not in _PLACEHOLDERS_EMAIL
    senha_ok = senha not in _PLACEHOLDERS_SENHA_APP
    return {
        "email": email if email_ok else "",
        "senha_salva": senha_ok,
        "configurada": email_ok and senha_ok,
    }


@api_bp.route("/configuracoes/gmail", methods=["GET"])
def configuracao_gmail_obter():
    return jsonify(_estado_credenciais_gmail())


@api_bp.route("/configuracoes/gmail", methods=["POST"])
def configuracao_gmail_salvar():
    """
    Salva EMAIL_REMETENTE e EMAIL_SENHA_APP em credenciais/.env e já as aplica.

    payload: {"email": "...@gmail.com", "senha": "btxq xxxx xxxx xxxx"}
        A senha de app do Google tem 16 letras, mostradas em 4 grupos de 4
        separados por espaço; os espaços são removidos ao salvar. Pode vir
        vazia SE já houver uma salva (troca só o e-mail).
    """
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email") or "").strip()
    senha = _normalizar_senha_app(payload.get("senha") or "")
    estado = _estado_credenciais_gmail()

    if not email and estado["email"]:
        email = estado["email"]          # só trocando a senha
    if not email or email in _PLACEHOLDERS_EMAIL or not _RE_EMAIL.match(email):
        return jsonify({"erro": "Informe um e-mail válido (o Gmail que envia as mensagens)."}), 400
    if not senha and not estado["senha_salva"]:
        return jsonify({"erro": "Informe a senha de app do Gmail (16 letras, no formato abcd efgh ijkl mnop)."}), 400
    if senha and not _RE_SENHA_APP.match(senha):
        return jsonify({
            "erro": "Senha de app inválida: ela tem exatamente 16 letras, em 4 grupos de 4 "
                    "(ex.: abcd efgh ijkl mnop). Não é a senha normal da conta Google.",
        }), 400

    valores = {"EMAIL_REMETENTE": email}
    if senha:
        valores["EMAIL_SENHA_APP"] = senha
    try:
        _persistir_env(valores)
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível gravar credenciais/.env: {exc}"}), 500

    aplicado = _recarregar_credenciais_em_runtime()
    resposta = _estado_credenciais_gmail()
    resposta["status"] = "ok"
    resposta["mensagem"] = (
        "Credenciais do Gmail salvas e já aplicadas — pode usar agora, sem reiniciar."
        if aplicado else
        "Credenciais do Gmail salvas em credenciais/.env. Reinicie o Auto SERE para aplicá-las."
    )
    return jsonify(resposta)


# ============================================================
# RCO — login e senha do Registro de Classe Digital (credenciais/.env)
# ============================================================

_PLACEHOLDERS_SERE = {"", "cpf", "senha_sere"}


def _estado_credenciais_rco() -> dict:
    """
    Sem RCO_LOGIN/RCO_SENHA próprios o RCO usa o login e a senha do SERE (mesma
    Central de Segurança). A senha NUNCA é devolvida.
    """
    login = (os.getenv("RCO_LOGIN") or "").strip()
    senha = os.getenv("RCO_SENHA") or ""
    proprias = bool(login or senha)
    sere_ok = (
        (os.getenv("SERE_LOGIN") or "").strip() not in _PLACEHOLDERS_SERE
        and (os.getenv("SERE_SENHA") or "") not in _PLACEHOLDERS_SERE
    )
    return {
        "usa_sere": not proprias,
        "login": login,
        "senha_salva": bool(senha),
        "sere_configurado": sere_ok,
        "configurada": (bool(login) and bool(senha)) if proprias else sere_ok,
    }


@api_bp.route("/configuracoes/rco", methods=["GET"])
def configuracao_rco_obter():
    return jsonify(_estado_credenciais_rco())


@api_bp.route("/configuracoes/rco", methods=["POST"])
def configuracao_rco_salvar():
    """
    payload: {"mesmas_do_sere": true}
        O RCO passa a usar o login e a senha do SERE (apaga os valores próprios).
    payload: {"login": "...", "senha": "..."}
        Login (CPF ou Login Sentinela) e senha próprios do RCO. A senha pode vir
        vazia SE já houver uma própria salva (troca só o login).
    """
    payload = request.get_json(silent=True) or {}
    aviso = ""

    if payload.get("mesmas_do_sere"):
        valores = {"RCO_LOGIN": "", "RCO_SENHA": ""}
        if not _estado_credenciais_rco()["sere_configurado"]:
            aviso = " Atenção: as credenciais do SERE ainda não estão salvas."
        mensagem_ok = "O RCO vai usar o mesmo login e senha do SERE."
    else:
        estado = _estado_credenciais_rco()
        login = str(payload.get("login") or "").strip()
        senha = str(payload.get("senha") or "")
        if not login and not estado["usa_sere"]:
            login = estado["login"]            # só trocando a senha
        if not login:
            return jsonify({"erro": "Informe o login do RCO (CPF ou Login Sentinela)."}), 400
        if not senha and not (estado["senha_salva"] and not estado["usa_sere"]):
            return jsonify({"erro": "Informe a senha do RCO."}), 400
        valores = {"RCO_LOGIN": login}
        if senha:
            valores["RCO_SENHA"] = senha
        mensagem_ok = "Credenciais do RCO salvas"

    try:
        _persistir_env(valores)
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível gravar credenciais/.env: {exc}"}), 500

    aplicado = _recarregar_credenciais_em_runtime()
    resposta = _estado_credenciais_rco()
    resposta["status"] = "ok"
    resposta["mensagem"] = mensagem_ok + (
        " e já aplicadas — pode usar agora, sem reiniciar." if aplicado
        else ". Reinicie o Auto SERE para aplicá-las."
    ) + aviso
    return jsonify(resposta)


# ============================================================
# PARECERES DO FUNDAMENTAL — modelos Word por turma (MODELO/ + controle_modelos.json)
# ============================================================

def _estado_modelos_parecer() -> dict:
    from src.automacao import parecer_fund as pf
    controle = pf.carregar_controle()
    turmas_json = _carregar_json("turmas.json", {})
    linhas = []
    for turma in turmas_json:
        entrada = controle.get(turma)
        linhas.append({
            "turma": turma,
            "arquivo": entrada["arquivo"] if entrada else None,
            "arquivo_existe": pf.modelo_da_turma(turma, controle) is not None if entrada else False,
        })
    return {"turmas": linhas, "pasta": str(pf.pasta_modelos()), "controle": str(pf.arquivo_controle()),
            "limite_mb": pf.LIMITE_MODELO_MB}


@api_bp.route("/configuracoes/modelos-parecer", methods=["GET"])
def configuracao_modelos_parecer_obter():
    try:
        return jsonify(_estado_modelos_parecer())
    except ValueError as exc:                      # controle ilegível
        return jsonify({"erro": str(exc)}), 500


@api_bp.route("/configuracoes/modelos-parecer", methods=["POST"])
def configuracao_modelos_parecer_salvar():
    """
    Upload de um modelo de parecer (.docx) e ligação dele a uma ou mais turmas.
    multipart/form-data: arquivo (o .docx) + turmas (um campo por turma).
    """
    from src.automacao import parecer_fund as pf
    arquivo = request.files.get("arquivo")
    turmas = request.form.getlist("turmas")
    if arquivo is None or not arquivo.filename:
        return jsonify({"erro": "Escolha o arquivo do modelo (.docx)."}), 400
    if not arquivo.filename.lower().endswith(".docx"):
        return jsonify({"erro": "O modelo precisa ser um arquivo Word (.docx)."}), 400
    turmas_json = _carregar_json("turmas.json", {})
    if not turmas_json:
        return jsonify({"erro": "Ainda não existe turmas.json: execute primeiro a automação 'Turmas'."}), 400
    desconhecidas = [t for t in turmas if t not in turmas_json]
    if desconhecidas:
        return jsonify({"erro": "Turma(s) que não existem em turmas.json: " + ", ".join(desconhecidas)}), 400

    conteudo = arquivo.read(pf.LIMITE_MODELO_MB * 1024 * 1024 + 1)
    try:
        resultado = pf.salvar_modelo(arquivo.filename, conteudo, turmas)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível gravar o modelo: {exc}"}), 500

    aviso = ""
    if resultado["turmas_afetadas"]:
        aviso = (" Atenção: outras turmas que já usavam este arquivo passam a usar a versão nova: "
                 + ", ".join(resultado["turmas_afetadas"]) + ".")
    estado = _estado_modelos_parecer()
    estado["status"] = "ok"
    estado["mensagem"] = (f"Modelo \"{resultado['arquivo']}\" " + ("atualizado" if resultado["substituiu"] else "salvo")
                          + f" para {len(resultado['turmas'])} turma(s)." + aviso)
    return jsonify(estado)


# ============================================================
# ANO LETIVO — escolher o ano, voltar a um ano anterior, backup/restauração por ano e dados fictícios de teste
# ============================================================

_RE_NOME_BACKUP = re.compile(r"backup_[\w\-]+\.zip")


def _ha_automacao_em_execucao() -> bool:
    with _EXECUCOES_LOCK:
        return any(r.get("status") == StatusExecucao.EXECUTANDO.value for r in _EXECUCOES.values())


def _estado_ano_letivo() -> dict:
    from src.comum import backup as _backup, dados_ficticios as _fict
    ativo, proximo = str(_paths.ano_atual()), str(_paths.ano_do_proximo_inicio())
    backups = _backup.listar_backups()
    anos = sorted({*_paths.anos_disponiveis(), ativo, proximo, *(b["ano"] for b in backups if b["ano"])}, reverse=True)
    linhas = []
    for ano in anos:
        pasta = _paths.DADOS_DIR / ano
        linhas.append({
            "ano": ano, "ativo": ano == ativo, "proximo": ano == proximo,
            "arquivos": sum(1 for _ in _backup._arquivos_da_pasta(pasta)),
            "ficticio": _fict.pasta_e_ficticia(pasta),
            "backups": sum(1 for b in backups if b["ano"] == ano),
        })
    return {
        "ativo": ativo, "proximo": proximo, "configurado": _paths.ano_configurado(),
        "automatico": _paths.ano_configurado() is None, "ano_do_calendario": str(_paths.ano_do_calendario()),
        "fixado_por_ambiente": _paths.ano_fixado_por_ambiente(),
        "pendente_reinicio": proximo != ativo,
        "somente_consulta": _paths.somente_consulta(),
        "anos": linhas,
        "backups": [{"nome": b["nome"], "ano": b["ano"], "data": b["data"], "motivo": b["motivo"],
                     "tamanho": _backup._tamanho_legivel(b["tamanho"])} for b in backups],
    }


@api_bp.route("/configuracoes/ano-letivo", methods=["GET"])
def configuracao_ano_letivo_obter():
    return jsonify(_estado_ano_letivo())


@api_bp.route("/ano-letivo/contexto", methods=["GET"])
def ano_letivo_contexto():
    """Leve (sem listar backups): o que o topo da página precisa para mostrar o ano e o modo somente consulta."""
    ativo, proximo = str(_paths.ano_atual()), str(_paths.ano_do_proximo_inicio())
    return jsonify({
        "ativo": ativo, "proximo": proximo, "pendente_reinicio": proximo != ativo,
        "somente_consulta": _paths.somente_consulta(), "ano_do_calendario": str(_paths.ano_do_calendario()),
        "fixado_por_ambiente": _paths.ano_fixado_por_ambiente(),
    })


def _limpar_estado_em_memoria_do_ano() -> None:
    """
    Depois de trocar de ano: esquece o que a tela guardava do ano anterior (resultado e log das execuções, atividade
    do assistente). Só mexe no que não está rodando; os arquivos em disco não são tocados.
    """
    global _WIZARD_LIMPO_T
    with _EXECUCOES_LOCK:
        for chave in [k for k, r in _EXECUCOES.items() if r.get("status") != StatusExecucao.EXECUTANDO.value]:
            del _EXECUCOES[chave]
        _EVENTOS_WIZARD.clear()
        _WIZARD_LIMPO_T = time.time()


@api_bp.route("/configuracoes/ano-letivo", methods=["POST"])
def configuracao_ano_letivo_salvar():
    """
    payload: {"ano": "2025"}  → passa a usar esse ano;  {"automatico": true} → volta ao ano do calendário.

    A TROCA VALE NA HORA, sem reiniciar: grava a escolha (config/config_usuario.json), muda o ano do processo e
    recarrega os módulos que fixam dados/<ano> na importação (src.comum.ano_letivo.trocar_ano). Recusada (409) se
    houver automação em execução — ela está usando os dados do ano atual —, ou se o ano estiver fixado pela
    variável de ambiente AUTO_SERE_ANO_BASE.
    """
    from src.comum import ano_letivo as _troca
    payload = request.get_json(silent=True) or {}
    automatico = bool(payload.get("automatico"))
    if _paths.ano_fixado_por_ambiente():
        return jsonify({"erro": f"O ano está fixado pela variável de ambiente AUTO_SERE_ANO_BASE={os.getenv('AUTO_SERE_ANO_BASE')}, "
                                "que manda sobre esta configuração. Remova a variável para poder escolher o ano aqui."}), 409
    try:
        if not automatico:
            _config.validar_ano_letivo(payload.get("ano"))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    if _ha_automacao_em_execucao():
        return jsonify({"erro": f"Há uma automação em execução usando os dados do ano {_paths.ano_atual()}. Espere ela terminar "
                                "(ou cancele) antes de trocar de ano."}), 409
    try:
        r = _troca.trocar_ano(None if automatico else payload.get("ano"))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except _troca.TrocaDeAnoErro as exc:
        return jsonify({"erro": str(exc)}), 500
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível gravar a configuração: {exc}"}), 500
    if r["trocou"]:
        _limpar_estado_em_memoria_do_ano()
    estado = _estado_ano_letivo()
    estado["status"] = "ok"
    estado["trocou"] = r["trocou"]
    estado["antigo"] = r["antigo"]
    if r["trocou"]:
        estado["mensagem"] = (f"Ano letivo {r['novo']} carregado (antes: {r['antigo']}). As telas e as automações já usam os dados "
                              f"de {r['novo']}." + (" Modo somente consulta: dá para ver tudo, mas nada pode ser alterado."
                                                    if estado["somente_consulta"] else ""))
    else:
        estado["mensagem"] = f"O ano letivo {r['novo']} já é o que está em uso."
    return jsonify(estado)


@api_bp.route("/configuracoes/ano-letivo/backup", methods=["POST"])
def configuracao_ano_letivo_backup():
    """Backup dos dados de um ano (padrão: o ano em uso), sem trocar de ano."""
    from src.comum import backup as _backup
    payload = request.get_json(silent=True) or {}
    ativo = str(_paths.ano_atual())
    try:
        ano = _config.validar_ano_letivo(payload.get("ano") or ativo)
        arquivo = _backup.criar_backup(motivo="manual", ano=None if ano == ativo else ano)
    except _backup.BackupVazioError:
        return jsonify({"erro": f"Não há dados do ano {ano} para copiar."}), 400
    except (ValueError, _backup.BackupInvalidoError) as exc:
        return jsonify({"erro": str(exc)}), 400
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível gravar o backup: {exc}"}), 500
    estado = _estado_ano_letivo()
    estado["status"] = "ok"
    estado["mensagem"] = f"Backup dos dados de {ano} criado: {arquivo.name}."
    return jsonify(estado)


@api_bp.route("/configuracoes/ano-letivo/restaurar", methods=["POST"])
def configuracao_ano_letivo_restaurar():
    """
    Volta os dados de um ano a partir de um backup.
    payload: {"backup": "backup_....zip", "aplicar": false, "confirmar": false, "so_dados": true}
      aplicar=false  só extrai para uma pasta de conferência (nada do sistema muda);
      aplicar=true   exige confirmar=true; faz antes uma cópia de segurança do ano que será sobrescrito.
    Os dados vão para a pasta do ANO DO BACKUP, não do ano em uso. Restaurar o ano EM USO com uma automação
    rodando é recusado (ela está escrevendo nesses arquivos).
    """
    from src.comum import backup as _backup
    payload = request.get_json(silent=True) or {}
    nome = str(payload.get("backup") or "")
    if not _RE_NOME_BACKUP.fullmatch(nome) or Path(nome).name != nome:
        return jsonify({"erro": "Escolha um backup da lista."}), 400
    arquivo = _paths.DADOS_BACKUP_DIR / nome
    if not arquivo.is_file():
        return jsonify({"erro": "Esse backup não existe mais."}), 404
    aplicar, so_dados = bool(payload.get("aplicar")), bool(payload.get("so_dados", True))
    try:
        manifesto = _backup.verificar_backup(arquivo)
        ano_backup = str(manifesto.get("ano") or "")
        if aplicar:
            if not payload.get("confirmar"):
                return jsonify({"erro": "Confirme que quer substituir os dados do ano pelos do backup."}), 400
            if ano_backup == str(_paths.ano_atual()) and _ha_automacao_em_execucao():
                return jsonify({"erro": "Há uma automação em execução usando os dados do ano atual. Espere ela terminar (ou cancele) "
                                        "antes de restaurar."}), 409
        r = _backup.restaurar_backup(arquivo, aplicar=aplicar, so_dados=so_dados)
    except _backup.BackupInvalidoError as exc:
        return jsonify({"erro": f"Backup inválido: {exc}"}), 400
    except OSError as exc:
        return jsonify({"erro": f"Não foi possível restaurar: {exc}"}), 500
    estado = _estado_ano_letivo()
    estado["status"] = "ok"
    if aplicar:
        seguranca = Path(r["backup_de_seguranca"]).name if r["backup_de_seguranca"] else "nenhuma (a pasta do ano estava vazia)"
        extra = (" Recarregue as telas para ver os dados restaurados." if r["ano"] == estado["ativo"] else
                 f" O ano {r['ano']} não está em uso agora: escolha-o em 'Usar este ano' para trabalhar com ele.")
        estado["mensagem"] = (f"Dados de {r['ano']} restaurados ({r['arquivos']} arquivo(s)) em {r['pasta_destino']}. "
                              f"Cópia de segurança do estado anterior: {seguranca}.{extra}")
    else:
        estado["mensagem"] = f"Conteúdo do backup extraído para conferência em {r['pasta']}. Nada foi alterado no sistema."
    estado["resultado"] = {k: r[k] for k in ("aplicado", "arquivos", "ano", "backup_de_seguranca", "pasta", "pasta_destino")}
    return jsonify(estado)


@api_bp.route("/configuracoes/ano-letivo/dados-ficticios", methods=["POST"])
def configuracao_ano_letivo_ficticios():
    """Cria dados FALSOS de um ano (para testes). Recusa se a pasta do ano já tem dados reais."""
    from src.comum import dados_ficticios as _fict
    payload = request.get_json(silent=True) or {}
    try:
        ano = _config.validar_ano_letivo(payload.get("ano"))
        pasta = _paths.DADOS_DIR / ano
        if ano in (str(_paths.ano_atual()), str(_paths.ano_do_proximo_inicio())) and not _fict.pasta_e_ficticia(pasta):
            return jsonify({"erro": f"O ano {ano} é o que está em uso (ou será no próximo início): dados fictícios não são "
                                    "gerados nele para não misturar com o trabalho de verdade. Use um ano que não está em uso."}), 400
        r = _fict.gerar_dados_ficticios(ano, com_backup=bool(payload.get("backup", True)))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except (OSError, __import__("src.comum.backup", fromlist=["x"]).BackupInvalidoError) as exc:
        return jsonify({"erro": f"Não foi possível gerar os dados: {exc}"}), 500
    estado = _estado_ano_letivo()
    estado["status"] = "ok"
    estado["mensagem"] = (f"Dados fictícios de {r['ano']} criados: {r['turmas']} turmas, {r['alunos']} alunos, {r['funcionarios']} "
                          f"funcionários, {r['pre_matricula']} na pré-matrícula." + (f" Backup: {r['backup']}." if r["backup"] else ""))
    estado["resultado"] = r
    return jsonify(estado)


# ============================================================
# ESCOLA — nome, CEP, endereço e identificação (fonte única: src.comum.escola)
# ============================================================

@api_bp.route("/configuracoes/escola", methods=["GET"])
def escola_ler():
    return jsonify({"dados": _escola.carregar(), "configurada": _escola.configurada()})


@api_bp.route("/configuracoes/escola", methods=["POST"])
def escola_salvar():
    payload = request.get_json(silent=True) or {}
    try:
        _escola.salvar(payload)
    except _escola.ValidacaoErro as exc:
        return jsonify({"erro": exc.mensagem(), "campos": exc.erros}), 400
    return jsonify({
        "status": "ok",
        "mensagem": "Dados da escola salvos.",
        "dados": _escola.carregar(),
        "configurada": _escola.configurada(),
    })


@api_bp.route("/cep/<string:cep>", methods=["GET"])
def cep_consultar(cep):
    """Preenche logradouro/bairro/cidade/UF a partir do CEP (ViaCEP → BrasilAPI)."""
    try:
        return jsonify(_cep.consultar_cep(cep))
    except _cep.CepInvalido:
        return jsonify({"erro": "CEP inválido: informe 8 dígitos."}), 400
    except _cep.CepNaoEncontrado:
        return jsonify({"erro": "CEP não encontrado. Preencha o endereço manualmente."}), 404
    except _cep.ErroConsultaCep:
        return jsonify({"erro": "Não foi possível consultar o CEP agora (sem internet?). Preencha o endereço manualmente."}), 502


# ============================================================
# WIZARD — painel "Registro de atividades"
# ============================================================
# Junta, num só feed cronológico: (1) as linhas que cada passo em segundo plano
# (turmas, gerar pastas, funcionários, alunos) já registra em _EXECUCOES e
# (2) eventos dos passos rápidos (dados da escola, credenciais) e erros do
# próprio wizard. NUNCA registrar senhas, CPF ou outros dados pessoais aqui.

_WIZARD_ASSINCRONOS = {
    "turmas": ("wizard_turmas", "Turmas"),
    "gerar_pastas": ("wizard_gerar_pastas", "Gerar pastas"),
    "funcionarios": ("wizard_funcionarios", "Funcionários / Servidores"),
    "alunos": ("wizard_alunos", "Alunos"),
}
_EVENTOS_WIZARD: list[dict[str, Any]] = []
_WIZARD_LIMPO_T = 0.0


def _evento_wizard(passo: str, texto: str, nivel: str = "info") -> None:
    with _EXECUCOES_LOCK:
        _EVENTOS_WIZARD.append({"t": time.time(), "passo": passo, "nivel": nivel, "texto": texto})
        del _EVENTOS_WIZARD[:-500]          # limite de memória


# Marcadores que o próprio execucao_gui grava no fim de cada execução. O painel
# já mostra "Concluído"/"Cancelado" por conta própria, então não repete esses dois.
_MARCADORES_FINAIS = ("[CONCLUÍDO]", "[CANCELADO]")


def _nivel_da_linha(linha: str) -> str:
    baixa = linha.lower()
    if (baixa.startswith(("[error]", "[erro]", "[critical]")) or "traceback" in baixa
            or re.match(r"erro\b", baixa)):
        return "erro"
    if baixa.startswith(("[warning]", "[cancelando]", "aviso")):
        return "aviso"
    if "conclu" in baixa or baixa.startswith("✓") or baixa.startswith("[ok]"):
        return "ok"
    return "info"


def _limpar_linha(linha: str) -> str:
    return linha[7:] if linha.startswith("[INFO] ") else linha


@api_bp.route("/wizard/atividade")
def wizard_atividade():
    """Feed cronológico do painel + estado de cada passo em segundo plano."""
    entradas: list[tuple[float, str, str, str]] = []
    passos: dict[str, dict[str, Any]] = {}
    with _EXECUCOES_LOCK:
        limpo_t = _WIZARD_LIMPO_T
        for passo, (chave, rotulo) in _WIZARD_ASSINCRONOS.items():
            reg = _EXECUCOES.get(chave)
            if reg is None:
                continue
            execucao = reg.get("execucao")
            passos[passo] = {
                "status": reg["status"],
                "cancelando": bool(execucao is not None and execucao.cancelamento_solicitado
                                   and reg["status"] == StatusExecucao.EXECUTANDO.value),
            }
            entradas.append((reg["iniciado_t"], passo, "info", f"▶ Iniciando: {rotulo}"))
            horas = reg.get("logs_t", [])
            for i, linha in enumerate(reg["logs"]):
                if linha.strip() in _MARCADORES_FINAIS:
                    continue
                t = horas[i] if i < len(horas) else reg["iniciado_t"]
                entradas.append((t, passo, _nivel_da_linha(linha), _limpar_linha(linha)))
            if reg["status"] != StatusExecucao.EXECUTANDO.value:
                fim = reg.get("terminou_t") or time.time()
                if reg["status"] == StatusExecucao.CONCLUIDO.value:
                    entradas.append((fim, passo, "ok", f"✓ Concluído: {rotulo}"))
                elif reg["status"] == StatusExecucao.CANCELADO.value:
                    entradas.append((fim, passo, "aviso", f"■ Cancelado: {rotulo}"))
                else:
                    entradas.append((fim, passo, "erro", f"✗ Erro em {rotulo}: {reg.get('erro') or 'veja os registros acima'}"))
        for ev in _EVENTOS_WIZARD:
            entradas.append((ev["t"], ev["passo"], ev["nivel"], ev["texto"]))

    entradas = sorted((e for e in entradas if e[0] > limpo_t), key=lambda e: e[0])[-400:]
    return jsonify({
        "entradas": [
            {"t": t, "hora": datetime.fromtimestamp(t).strftime("%H:%M:%S"), "passo": passo, "nivel": nivel, "texto": texto}
            for t, passo, nivel, texto in entradas
        ],
        "passos": passos,
        "executando": [p for p, d in passos.items() if d["status"] == StatusExecucao.EXECUTANDO.value],
    })


@api_bp.route("/wizard/atividade/limpar", methods=["POST"])
def wizard_atividade_limpar():
    """Esconde do painel tudo o que aconteceu até agora (não apaga logs de arquivo nem execuções)."""
    global _WIZARD_LIMPO_T
    with _EXECUCOES_LOCK:
        _WIZARD_LIMPO_T = time.time()
        _EVENTOS_WIZARD.clear()
    return jsonify({"status": "ok"})


# ============================================================
# WIZARD — 1ª execução obrigatória
# ============================================================

def _whatsapp_conectado() -> bool:
    """Passo 'WhatsApp' do wizard: concluído só com sessão REAL conectada (o simulado não conta)."""
    from src.web.api.whatsapp import whatsapp_conectado_de_verdade   # import tardio: whatsapp.py importa este módulo
    return whatsapp_conectado_de_verdade()


@api_bp.route("/wizard/status")
def wizard_status():
    """
    Estado real de cada passo, lido de src.comum.configuracao
    (config_usuario.json) e da presença dos arquivos que cada automação
    gera — sem valores fixos.
    """
    credenciais_sere = bool(os.getenv("SERE_LOGIN")) and bool(os.getenv("SERE_SENHA"))
    turmas_ok = (_dados_dir() / "turmas.json").exists()
    funcionarios_ok = (_dados_dir() / "funcionarios.json").exists()
    alunos_ok = (_dados_dir() / "alunos.json").exists()

    return jsonify({
        "escola": _config.unidade_escolar_configurada(),
        "credenciais_sere": credenciais_sere,
        "turmas": turmas_ok,
        "gerar_pastas": _config.pasta_digitalizacao_configurada(),
        "funcionarios": funcionarios_ok,
        "alunos": alunos_ok,
        "google_api": bool(os.getenv("GOOGLE_API_CREDENTIALS")),
        "whatsapp": _whatsapp_conectado(),
    })


@api_bp.route("/wizard/<string:passo>/executar", methods=["POST"])
def wizard_executar_passo(passo):
    """Mapeia cada passo do wizard para a automação real correspondente."""
    payload = request.get_json(silent=True) or {}

    try:
        if passo in ("turmas", "alunos"):
            conflito = _conflito_em_execucao(f"wizard_{passo}")
            if conflito:
                _evento_wizard(passo, f"Não iniciado: {conflito}", "aviso")
                return jsonify({"status": "erro", "mensagem": conflito}), 409

        if passo == "turmas":
            from src.automacao.turmas import coletar_turmas_e_alunos_via_login
            _rodar_coroutine_em_thread("wizard_turmas", lambda: coletar_turmas_e_alunos_via_login())

        elif passo == "gerar_pastas":
            pasta = payload.get("pasta")
            if pasta:
                _config.definir_pasta_digitalizacao(pasta)
            if not _config.pasta_digitalizacao_configurada():
                _evento_wizard("gerar_pastas", "Pasta de digitalização não configurada: defina-a em Configurações → Pasta de digitalização.", "aviso")
                return jsonify({"erro": "Informe 'pasta' (pasta de digitalização) antes de gerar as pastas."}), 400
            from src.automacao.gerar_pastas import main as _gerar_pastas_main
            _rodar_funcao_sincrona_em_thread("wizard_gerar_pastas", _gerar_pastas_main)

        elif passo == "funcionarios":
            from src.automacao.servidores import coletar_servidores_via_login
            modo = payload.get("modo", "completo")
            _rodar_coroutine_em_thread(
                "wizard_funcionarios", lambda: coletar_servidores_via_login(modo=modo)
            )

        elif passo == "alunos":
            from src.automacao.alunos import coletar_alunos_via_login
            _rodar_coroutine_em_thread("wizard_alunos", lambda: coletar_alunos_via_login())

        elif passo == "credenciais_sere":
            login = payload.get("login")
            senha = payload.get("senha")
            if not login or not senha:
                return jsonify({"erro": "Informe 'login' e 'senha' do SERE."}), 400
            _persistir_env({"SERE_LOGIN": login, "SERE_SENHA": senha})
            aplicado_em_runtime = _recarregar_credenciais_em_runtime()
            _evento_wizard("credenciais_sere", "✓ Credenciais do SERE salvas.", "ok")
            if aplicado_em_runtime:
                mensagem = "Credenciais salvas e já aplicadas — pode usar agora, sem reiniciar."
            else:
                # Recarga em runtime é uma otimização; se falhar por algum
                # motivo (módulo com import diferente, erro inesperado), o
                # .env já está correto e um reinício normal resolve.
                mensagem = "Credenciais salvas em credenciais/.env. Reinicie o Auto SERE para aplicá-las."
            return jsonify({"status": "ok", "mensagem": mensagem})

        elif passo == "escola":
            try:
                dados = _escola.salvar(payload)
            except _escola.ValidacaoErro as exc:
                _evento_wizard("escola", f"Dados da escola não salvos: {exc.mensagem()}", "aviso")
                return jsonify({"erro": exc.mensagem(), "campos": exc.erros}), 400
            _evento_wizard("escola", f"✓ Dados da escola salvos: {dados['nome']} (CEP {_escola.formatar_cep(dados['cep'])}).", "ok")
            return jsonify({"status": "ok", "mensagem": "Dados da escola salvos."})

        elif passo == "whatsapp":
            # A conexão acontece na tela "WhatsApp" (QR Code); aqui só se pede o início da sessão.
            from src.servicos.whatsapp.gerenciador import obter_gerenciador
            r = obter_gerenciador().conectar()
            _evento_wizard("whatsapp", r["mensagem"], "ok" if r["ok"] else "aviso")
            if r.get("precisa_confirmar"):
                return jsonify({"status": "erro", "mensagem": r["mensagem"]}), 409
            return jsonify({"status": "ok" if r["ok"] else "erro", "mensagem": r["mensagem"]}), (200 if r["ok"] else 400)

        elif passo == "google_api":
            return jsonify({
                "status": "erro",
                "mensagem": f"Passo '{passo}' ainda não foi implementado no código-fonte.",
            }), 501

        else:
            return jsonify({"erro": f"Passo '{passo}' não reconhecido"}), 404

    except ModuleNotFoundError as exc:
        _evento_wizard(passo, f"✗ Módulo não encontrado: {exc}", "erro")
        return jsonify({"status": "erro", "mensagem": f"Módulo não encontrado: {exc}"}), 500
    except ValueError as exc:
        _evento_wizard(passo, f"✗ {exc}", "erro")
        return jsonify({"status": "erro", "mensagem": str(exc)}), 400

    return jsonify({
        "status": "executando",
        "mensagem": f"Passo '{passo}' iniciado em segundo plano.",
    })


def _formatar_valor_env(valor: str) -> str:
    """
    Escreve o valor entre aspas simples para o python-dotenv ler de volta
    exatamente o que foi digitado. Sem aspas, o dotenv corrompe valores com
    " #" (vira comentário), com aspas nas pontas, ou com espaços nas pontas —
    problema típico em senhas. Barra invertida e aspa simples são escapadas.
    (Limitação do próprio dotenv: um trecho ${NOME} ainda é interpolado.)
    """
    valor = str(valor)
    return "'" + valor.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _persistir_env(valores: dict[str, str]) -> None:
    """
    Atualiza (ou cria) credenciais/.env com os pares chave=valor
    informados, preservando as demais linhas já existentes no arquivo.
    """
    caminho_env = _paths.CREDENCIAIS_DIR / ".env"
    caminho_env.parent.mkdir(parents=True, exist_ok=True)

    linhas_existentes: list[str] = []
    if caminho_env.exists():
        with open(caminho_env, "r", encoding="utf-8") as f:
            linhas_existentes = f.readlines()

    chaves_pendentes = dict(valores)
    novas_linhas = []
    for linha in linhas_existentes:
        chave = linha.split("=", 1)[0].strip()
        if chave in chaves_pendentes:
            novas_linhas.append(f"{chave}={_formatar_valor_env(chaves_pendentes.pop(chave))}\n")
        else:
            novas_linhas.append(linha)

    for chave, valor in chaves_pendentes.items():
        novas_linhas.append(f"{chave}={_formatar_valor_env(valor)}\n")

    with open(caminho_env, "w", encoding="utf-8") as f:
        f.writelines(novas_linhas)


# Módulos que fazem `from src.comum.credenciais import LOGIN, SENHA` (ou as
# outras constantes do mesmo arquivo) NO NÍVEL DO MÓDULO — ou seja, copiam o
# valor da credencial para o próprio namespace no momento do import. Um
# reload isolado de src.comum.credenciais não muda essas cópias: é preciso
# reimportar também cada um destes módulos, depois do reload de
# credenciais.py, para que a cópia seja refeita com o valor novo.
#
# Nenhum destes módulos guarda estado mutável de execução em si (só
# constantes de configuração — paths, URLs, timeouts), então reimportá-los
# é seguro. Uma automação já em andamento não é afetada: a thread que a
# executa já capturou a função/objeto antigos no momento em que foi
# lançada — reimportar o módulo só muda o que uma PRÓXIMA chamada vai usar.
_MODULOS_QUE_IMPORTAM_CREDENCIAIS = [
    "src.relatorios.analisa_arquivos_sere",
    "src.automacao.servidores",
    "src.automacao.rematricula",
    "src.automacao.alunos_completo",
    "src.automacao.sere_2026",
    "src.automacao.alunos",
    "src.automacao.prematricula_api",
    "src.automacao.envia_email",
    "src.automacao.processo_transferidos",
    "src.automacao.turmas",
    "src.automacao.funcionarios",
]


def _recarregar_credenciais_em_runtime() -> bool:
    """
    Aplica um novo credenciais/.env sem exigir reiniciar o processo:

    1. Recarrega as variáveis de ambiente do .env por cima do ambiente
       atual (override=True — o valor do arquivo vence o que já estava
       no processo).
    2. Reimporta src.comum.credenciais, que reatribui LOGIN/SENHA/etc a
       partir das variáveis de ambiente já atualizadas.
    3. Reimporta, na sequência, cada módulo que fez
       `from src.comum.credenciais import LOGIN, SENHA` — só reimportar
       o passo 2 não basta, porque esse import copia o valor da string
       para dentro do módulo consumidor no momento em que roda.

    Só reimporta módulos que já estavam carregados (sys.modules) — um
    módulo que ainda não foi usado nesta execução do processo vai
    naturalmente pegar o valor certo no seu primeiro import, então não
    há necessidade de forçá-lo aqui.

    Retorna True se a recarga completou sem erros, False se algo falhou
    (nesse caso o .env em disco já está correto e um reinício normal do
    processo aplica as credenciais do jeito de sempre).
    """
    try:
        caminho_env = _paths.CREDENCIAIS_DIR / ".env"
        load_dotenv(dotenv_path=caminho_env, override=True)

        import src.comum.credenciais as _credenciais_mod
        importlib.reload(_credenciais_mod)

        for nome_modulo in _MODULOS_QUE_IMPORTAM_CREDENCIAIS:
            modulo_carregado = sys.modules.get(nome_modulo)
            if modulo_carregado is not None:
                importlib.reload(modulo_carregado)

        return True
    except Exception:
        # Não deixamos uma falha na recarga "ao vivo" derrubar o salvamento
        # em si — o arquivo .env já foi gravado corretamente antes desta
        # função ser chamada.
        return False
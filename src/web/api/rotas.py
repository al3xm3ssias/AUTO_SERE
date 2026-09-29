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
    alunos_fora_raio = _carregar_json("alunos_fora_raio.json", [])
    alunos_encaminhamento = _carregar_json("alunos_encaminhamento.json", [])
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

    fila_prematricula = sum(len(alunos) for alunos in pre_matricula.get("turmas_intencao", {}).values()) \
        if isinstance(pre_matricula, dict) else 0

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

def _resposta_lista_generica(colunas, linhas):
    return jsonify({"colunas": colunas, "linhas": linhas, "total": len(linhas)})


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

    turma_por_cgm: dict[str, dict] = {}
    for nome_turma, lista_alunos in turmas.items():
        for aluno in lista_alunos:
            cgm = str(aluno.get("CGM", aluno.get("cgm", ""))).strip()
            if not cgm:
                continue
            turma_por_cgm[cgm] = {
                "situacao": aluno.get("Situação", aluno.get("Situacao", "—")),
                "turma": nome_turma,
            }

    alunos_resp = []
    for aluno in alunos:
        cgm = str(aluno.get("CGM", aluno.get("cgm", ""))).strip()
        info_turma = turma_por_cgm.get(cgm)
        aluno_completo = dict(aluno)
        aluno_completo["_situacao"] = info_turma["situacao"] if info_turma else "—"
        aluno_completo["_turma"] = info_turma["turma"] if info_turma else "—"
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


@api_bp.route("/prematricula/fila")
def prematricula_fila():
    """Versão resumida usada no painel principal (widget da fila)."""
    limit = int(request.args.get("limit", 5))
    itens = sorted(_fila_prematricula(), key=_posicao_ordenavel)
    return jsonify({"itens": itens[:limit]})


@api_bp.route("/funcionarios/lista")
def funcionarios_lista():
    """Lê funcionarios.json (gerado por src.automacao.servidores/funcionarios)."""
    funcionarios = _carregar_json("funcionarios.json", [])
    colunas = [
        {"chave": "nome", "label": "Nome"},
        {"chave": "cargo", "label": "Cargo"},
        {"chave": "situacao", "label": "Situação"},
    ]
    linhas = [
        {
            "nome": f.get("Nome", f.get("nome", "")),
            "cargo": f.get("Cargo", f.get("cargo", "")),
            "situacao": f.get("Situação", f.get("Situacao", f.get("situacao", ""))),
        }
        for f in funcionarios
    ]
    linhas.sort(key=lambda r: r["nome"])
    return _resposta_lista_generica(colunas, linhas)


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
    return _callback


def _rodar_funcao_sincrona_em_thread(chave: str, funcao, *args, **kwargs) -> None:
    """
    Para automações que ainda não têm wrapper ExecucaoEmBackground (ex.:
    gerar_pastas.main, cruzar_documentos.main — funções síncronas que só
    imprimem no console) — roda numa thread própria e captura o resultado
    ou a exceção no mesmo formato de registro usado pelas demais,
    para que o polling de status funcione igual para todas as automações.
    """
    registro = _registrar_execucao(chave)

    def _alvo():
        try:
            resultado = funcao(*args, **kwargs)
            with _EXECUCOES_LOCK:
                registro["status"] = StatusExecucao.CONCLUIDO.value
                registro["resultado"] = resultado
        except BaseException as exc:  # noqa: BLE001 — reportar qualquer falha ao polling
            with _EXECUCOES_LOCK:
                registro["status"] = StatusExecucao.ERRO.value
                registro["erro"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                registro["logs"].append(f"[ERRO] {registro['erro']}")

    threading.Thread(target=_alvo, daemon=True).start()


def _rodar_coroutine_em_thread(chave: str, coroutine_factory) -> None:
    """
    Para automações async que não têm wrapper ExecucaoEmBackground dedicado
    (ex.: src.automacao.sisreg.consultar_encaminhamentos_sisreg,
    src.automacao.rematricula.executar_rematricula,
    src.automacao.prematricula.executar_processo_completo) — mesmo
    propósito de _rodar_funcao_sincrona_em_thread, mas para uma coroutine.
    `coroutine_factory` é uma função zero-argumentos que RETORNA a
    coroutine (ex.: `lambda: minha_funcao_async(x, y)`) — só é chamada
    dentro da thread de background, para não criar a coroutine antes de
    haver um event loop rodando.
    """
    registro = _registrar_execucao(chave)

    def _alvo():
        try:
            resultado = asyncio.run(coroutine_factory())
            with _EXECUCOES_LOCK:
                registro["status"] = StatusExecucao.CONCLUIDO.value
                registro["resultado"] = resultado
        except BaseException as exc:  # noqa: BLE001
            with _EXECUCOES_LOCK:
                registro["status"] = StatusExecucao.ERRO.value
                registro["erro"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                registro["logs"].append(f"[ERRO] {registro['erro']}")

    threading.Thread(target=_alvo, daemon=True).start()


def _iniciar_via_execucao_gui(chave: str, funcao_executar, **kwargs) -> None:
    """
    Para automações que JÁ têm um wrapper `executar_<modo>` pronto (ver
    src/automacao/executar_*.py) — estes retornam um ExecucaoEmBackground
    e o próprio módulo já cuida da thread e da captura de print/log.
    """
    registro = _registrar_execucao(chave)
    execucao = funcao_executar(callback=_callback_para(chave), **kwargs)
    registro["execucao"] = execucao

    def _observar():
        execucao.aguardar()
        with _EXECUCOES_LOCK:
            registro["status"] = execucao.status.value
            registro["resultado"] = execucao.resultado
            if execucao.erro:
                registro["erro"] = "".join(
                    traceback.format_exception_only(type(execucao.erro), execucao.erro)
                ).strip()

    threading.Thread(target=_observar, daemon=True).start()


AUTOMACOES_DISPONIVEIS = [
    {"chave": "gerar_pastas", "nome": "Gerar pastas", "descricao": "Cria pastas dos alunos automaticamente."},
    {"chave": "analisa_pasta", "nome": "Analisa documentos da pasta", "descricao": "Analisa e organiza documentos diretamente da pasta."},
    {"chave": "analisa_sere", "nome": "Analisa documentos do SERE", "descricao": "Analisa documentos disponíveis no SERE."},
    {"chave": "documentos", "nome": "Documentos", "descricao": "Remove um tipo de documento de todos os alunos do SERE."},
    {"chave": "limpeza", "nome": "Limpeza total de documentos", "descricao": "Remove todos os arquivos de todos os alunos das turmas selecionadas."},
    {"chave": "validar", "nome": "Validar documentos", "descricao": "Valida (✔) todos os documentos pendentes das turmas selecionadas."},
    {"chave": "cruzamento", "nome": "Cruzamento de docs", "descricao": "Cruza informações e valida documentações (SERE x pasta local)."},
    {"chave": "cep", "nome": "CEP", "descricao": "Consulta, valida e completa endereços via CEP; calcula distância aluno-escola."},
    {"chave": "sus", "nome": "Encaminhamentos do SUS", "descricao": "Consulta se o aluno possui encaminhamentos na fila pública do SISREG."},
    {"chave": "transferidos", "nome": "Processo transferidos", "descricao": "Gera histórico e guia de transferência."},
    {"chave": "parecer_fund", "nome": "Pareceres fundamental", "descricao": "Gera todos os pareceres do Fundamental."},
    {"chave": "parecer_rco", "nome": "Pareceres infantil", "descricao": "Gera parecer do RCO e parecer da planilha."},
    {"chave": "comprimir", "nome": "Comprimir documentos", "descricao": "Comprime todos os docs, pareceres e docs dos alunos."},
    {"chave": "coleta_emails", "nome": "Coleta e-mails", "descricao": "Coleta os e-mails de outras escolas da rede municipal."},
    {"chave": "agendador", "nome": "Criar rotinas no agendador", "descricao": "Cria rotinas automáticas no Agendador de Tarefas do Windows."},
    {"chave": "backup", "nome": "Backup dos dados", "descricao": "Realiza backup de toda base de dados e arquivos."},
    {"chave": "avisos", "nome": "Mandar avisos", "descricao": "Envia e-mails e mensagens automáticas."},
    {"chave": "compara_anos", "nome": "Compara transferidos entre anos", "descricao": "Compara transferidos entre anos diferentes."},
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
    "parecer_fund", "parecer_rco", "comprimir", "agendador", "backup",
    "avisos", "compara_anos",
}


@api_bp.route("/automacoes/lista")
def automacoes_lista():
    return jsonify({"itens": AUTOMACOES_DISPONIVEIS})


@api_bp.route("/automacoes/<string:chave>/executar", methods=["POST"])
def automacoes_executar(chave):
    if chave in AUTOMACOES_NAO_IMPLEMENTADAS:
        return jsonify({
            "status": "erro",
            "mensagem": f"Automação '{chave}' ainda não foi implementada no código-fonte.",
        }), 501

    payload = request.get_json(silent=True) or {}
    turmas_selecionadas = payload.get("turmas") or []
    modo_teste = bool(payload.get("modo_teste", False))

    try:
        turmas_completas = _carregar_json("turmas.json", {})

        if chave == "gerar_pastas":
            from src.automacao.gerar_pastas import main as _gerar_pastas_main
            _rodar_funcao_sincrona_em_thread(chave, _gerar_pastas_main)

        elif chave == "analisa_sere":
            from src.automacao.executar_analisa import executar_analisa
            args_extras = ["--turma"] if turmas_selecionadas else []
            _iniciar_via_execucao_gui(chave, executar_analisa, args_extras=args_extras)

        elif chave == "documentos":
            idtipo = payload.get("idtipo")
            nome_slot = payload.get("nome_slot", "")
            if not idtipo:
                return jsonify({"erro": "Informe 'idtipo' do documento a remover."}), 400
            from src.automacao.executar_documento import executar_documento
            _iniciar_via_execucao_gui(
                chave, executar_documento,
                idtipo=idtipo, nome_slot=nome_slot,
                turmas_selecionadas=turmas_selecionadas or list(turmas_completas.keys()),
                turmas=turmas_completas, modo_teste=modo_teste,
            )

        elif chave == "limpeza":
            # Só existe em src.comum — src.automacao não tem uma cópia
            # deste wrapper específico (ver src/comum/execucao_gui.py).
            from src.comum.executar_limpeza import executar_limpeza
            _iniciar_via_execucao_gui(
                chave, executar_limpeza,
                turmas_selecionadas=turmas_selecionadas or list(turmas_completas.keys()),
                turmas=turmas_completas, modo_teste=modo_teste,
            )

        elif chave == "validar":
            from src.automacao.executar_validar import executar_validar
            _iniciar_via_execucao_gui(
                chave, executar_validar,
                turmas_selecionadas=turmas_selecionadas or list(turmas_completas.keys()),
                turmas=turmas_completas, modo_teste=modo_teste,
                somente_transferidos=bool(payload.get("somente_transferidos", False)),
            )

        elif chave == "transferidos":
            from src.automacao.executar_transferidos import executar_transferidos
            _iniciar_via_execucao_gui(chave, executar_transferidos, modo_teste=modo_teste)

        elif chave == "cruzamento":
            from src.relatorios.cruzar_documentos import main as _cruzar_main
            _rodar_funcao_sincrona_em_thread(chave, _cruzar_main)

        elif chave == "analisa_pasta":
            from src.relatorios.analisa_documentos_pc import main as _analisa_pc_main
            _rodar_funcao_sincrona_em_thread(chave, _analisa_pc_main)

        elif chave == "cep":
            from src.comum.cep_api import executar_analise_distancia
            raio_km = float(payload.get("raio_km", 3.0))
            _rodar_funcao_sincrona_em_thread(chave, executar_analise_distancia, raio_km=raio_km)

        elif chave == "sus":
            from src.automacao.sisreg import consultar_encaminhamentos_sisreg
            _rodar_coroutine_em_thread(chave, lambda: consultar_encaminhamentos_sisreg())

        elif chave == "coleta_emails":
            from src.automacao.coleta_emails import coletar_escolas_municipais
            _rodar_funcao_sincrona_em_thread(chave, coletar_escolas_municipais)

        elif chave == "mapear_pastas":
            from src.relatorios.mapear_pastas_alunos import main as _mapear_main
            _rodar_funcao_sincrona_em_thread(chave, _mapear_main)

        elif chave == "mascara":
            from src.relatorios.mascarar import main as _mascarar_main
            _rodar_funcao_sincrona_em_thread(chave, _mascarar_main)

        elif chave == "termos":
            tema = payload.get("tema")
            if not tema:
                return jsonify({"erro": "Informe 'tema' do termo de ciência."}), 400
            from src.automacao.termo_ciencia import gerar_termo
            _rodar_funcao_sincrona_em_thread(chave, gerar_termo, tema=tema)

        elif chave == "rematricula":
            from src.automacao.rematricula import executar_rematricula
            _rodar_coroutine_em_thread(
                chave, lambda: executar_rematricula(modo_teste=modo_teste)
            )

        elif chave == "prematricula_completa":
            from src.automacao.prematricula import executar_processo_completo
            _rodar_coroutine_em_thread(chave, lambda: executar_processo_completo())

        else:
            return jsonify({"erro": f"Automação '{chave}' não encontrada"}), 404

    except ModuleNotFoundError as exc:
        return jsonify({
            "status": "erro",
            "mensagem": f"Módulo da automação '{chave}' não encontrado: {exc}",
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
        return jsonify({
            "status": registro["status"],
            "logs": registro["logs"][-200:],
            "erro": registro["erro"],
            "iniciado_em": registro["iniciado_em"],
            "tem_resultado": registro["resultado"] is not None,
        })


# ============================================================
# SISTEMA — seleção de pasta via janela nativa do Windows (tkinter)
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
        import tkinter as tk
        from tkinter import filedialog

        # Janela raiz invisível: existe só para o filedialog funcionar,
        # não deve aparecer na tela.
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)  # traz o diálogo para frente

        caminho = filedialog.askdirectory(title=titulo)
        root.destroy()

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
# WIZARD — 1ª execução obrigatória
# ============================================================

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
        "credenciais_sere": credenciais_sere,
        "turmas": turmas_ok,
        "gerar_pastas": _config.pasta_digitalizacao_configurada(),
        "funcionarios": funcionarios_ok,
        "alunos": alunos_ok,
        "google_api": bool(os.getenv("GOOGLE_API_CREDENTIALS")),
        "whatsapp": False,
    })


@api_bp.route("/wizard/<string:passo>/executar", methods=["POST"])
def wizard_executar_passo(passo):
    """Mapeia cada passo do wizard para a automação real correspondente."""
    payload = request.get_json(silent=True) or {}

    try:
        if passo == "turmas":
            from src.automacao.turmas import coletar_turmas_e_alunos_via_login
            _rodar_coroutine_em_thread("wizard_turmas", lambda: coletar_turmas_e_alunos_via_login())

        elif passo == "gerar_pastas":
            pasta = payload.get("pasta")
            if pasta:
                _config.definir_pasta_digitalizacao(pasta)
            if not _config.pasta_digitalizacao_configurada():
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
            if aplicado_em_runtime:
                mensagem = "Credenciais salvas e já aplicadas — pode usar agora, sem reiniciar."
            else:
                # Recarga em runtime é uma otimização; se falhar por algum
                # motivo (módulo com import diferente, erro inesperado), o
                # .env já está correto e um reinício normal resolve.
                mensagem = "Credenciais salvas em credenciais/.env. Reinicie o Auto SERE para aplicá-las."
            return jsonify({"status": "ok", "mensagem": mensagem})

        elif passo in ("google_api", "whatsapp"):
            return jsonify({
                "status": "erro",
                "mensagem": f"Passo '{passo}' ainda não foi implementado no código-fonte.",
            }), 501

        else:
            return jsonify({"erro": f"Passo '{passo}' não reconhecido"}), 404

    except ModuleNotFoundError as exc:
        return jsonify({"status": "erro", "mensagem": f"Módulo não encontrado: {exc}"}), 500
    except ValueError as exc:
        return jsonify({"status": "erro", "mensagem": str(exc)}), 400

    return jsonify({
        "status": "executando",
        "mensagem": f"Passo '{passo}' iniciado em segundo plano.",
    })


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
            novas_linhas.append(f"{chave}={chaves_pendentes.pop(chave)}\n")
        else:
            novas_linhas.append(linha)

    for chave, valor in chaves_pendentes.items():
        novas_linhas.append(f"{chave}={valor}\n")

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
"""
API do WhatsApp para a interface web  —  prefixo /web/api/whatsapp
===================================================================
    GET  /status         estado da conexão (a tela consulta a cada poucos segundos)
    GET  /qr             QR Code atual: SVG (blake) ou PNG (whatsplay); 404 se não há (/qr.svg é o mesmo)
    POST /conectar       pede ao gateway para iniciar a sessão (gera o QR Code)
    POST /verificar      confirma a conexão perguntando ao WhatsApp por um número
    POST /teste          envia UMA mensagem de teste (trava dupla: WHATSAPP_ENVIO_REAL + confirmo)
    GET  /modelo-prematricula?id=...   texto sugerido + telefone do responsável (fila da pré-matrícula)
    POST /enviar         envia UMA mensagem a um responsável (mesma trava dupla do /teste)
    POST /envio-real     liga/desliga a permissão de envio real
    GET  /fila           a fila de envio: estado, configuração, contagens, limite do dia e as mensagens (número mascarado)
    POST /fila/itens     põe mensagens na fila ({itens:[{numero,nome,texto}]})
    GET  /fila/prematricula          alunos de previsao_alunos_<ano+1>.json (próximo ano letivo), para filtrar por turma/posição
    POST /fila/da-prematricula       põe na fila os alunos escolhidos ({ids, modelo_id})
    GET  /fila/geo                   alunos de sere_sisgea_<ano+1>.json (Direcionados GEO), para filtrar por etapa/matrícula
    POST /fila/do-geo                põe na fila os alunos GEO escolhidos ({ids, modelo_id, texto})
    GET  /fila/geo/resumo            resumo dos Direcionados GEO que podem receber a mensagem em massa (Pré matrícula)
    POST /fila/geo/em-massa          põe na fila UMA mensagem por telefone ({modelo_id, texto, etapa, incluir_confirmados, confirmo})
    POST /fila/config    intervalo entre mensagens, limite por dia, continuar no dia seguinte
    POST /fila/iniciar | /fila/pausar | /fila/cancelar-pendentes | /fila/limpar-historico
    POST /fila/itens/<id>/cancelar | /fila/itens/<id>/repetir
    GET|POST /fila/modelos, DELETE /fila/modelos/<id>   modelos de mensagem da fila
    POST /provedor       escolhe o modo: simulado, whatsplay (sem Docker) ou blake (gateway Docker)
    POST /desconectar    logout no gateway
    GET|POST|DELETE /webhooks   registra/remove o webhook de mensagens recebidas no gateway
    POST /webhook?t=...  RECEBE as mensagens do gateway e as entrega aos módulos (eventos.py)

Nada aqui grava mensagens, números completos ou o QR em log.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
import time
from typing import Any

from flask import Blueprint, Response, jsonify, request

from src.comum import servidor as _servidor
from src.servicos.whatsapp import (EnvioNaoAutorizadoError, WhatsAppErro, envio_real_autorizado,
                                   mascarar_numero, normalizar_numero)
from src.servicos.whatsapp import eventos as _eventos
from src.servicos.whatsapp.fila import obter_fila
from src.servicos.whatsapp.gerenciador import obter_gerenciador, reiniciar_gerenciador
from src.web.api.rotas import _persistir_env

log = logging.getLogger(__name__)
whatsapp_bp = Blueprint("whatsapp", __name__)

COMANDO_SUBIR = "docker compose -f docker/whatsapp/docker-compose.yml up -d"
TEXTO_TESTE = "Teste do sistema AUTO SERE — pode ignorar esta mensagem."
LIMITE_TEXTO_TESTE = 500
INTERVALO_MIN_TESTE_S = 5.0
LIMITE_CORPO_WEBHOOK = 30 * 1024 * 1024

_ultimo_teste = 0.0
_trava_teste = threading.Lock()

LIMITE_TEXTO_MENSAGEM = 4000       # o comunicado de matrícula tem ~2.000 caracteres
INTERVALO_MIN_ENVIO_S = 2.0
_ultimo_envio = 0.0
_trava_envio = threading.Lock()


def _erro(mensagem: str, codigo: int = 400, **extra):
    return jsonify({"erro": mensagem, **extra}), codigo


def _gravar_env(valores: dict[str, str]) -> None:
    """Grava em credenciais/.env e já vale neste processo (sem reiniciar)."""
    _persistir_env(valores)
    os.environ.update(valores)


def _gerenciador():
    """(gerenciador, None) ou (None, mensagem) quando a configuração do WhatsApp está incompleta."""
    try:
        return obter_gerenciador(), None
    except WhatsAppErro as exc:
        return None, str(exc)


def whatsapp_conectado_de_verdade() -> bool:
    """Para o wizard da 1ª execução: só conta sessão real (o provedor simulado não conta)."""
    try:
        g, _ = _gerenciador()
        return bool(g and not g.simulado and g.estado().conectado)
    except Exception:
        return False


# ───────────────────────────── estado ─────────────────────────────
@whatsapp_bp.route("/status")
def status():
    ger, problema = _gerenciador()
    base: dict[str, Any] = {
        "provedor_configurado": (os.environ.get("WHATSAPP_PROVEDOR", "simulado").strip().lower() or "simulado"),
        "envio_real": envio_real_autorizado(),
        "comando_docker": COMANDO_SUBIR,
    }
    if ger is None:
        return jsonify({**base, "situacao": "config_incompleta", "conectado": False, "mensagem": problema,
                        "simulado": False, "tem_gateway": False, "tem_sessao": False, "tem_webhook": False,
                        "gateway_url": "", "qr_id": "", "texto_gateway": ""})
    est = ger.estado()
    return jsonify({
        **base,
        "provedor": ger.nome, "simulado": ger.simulado, "tem_gateway": ger.tem_gateway,
        "tem_sessao": ger.tem_sessao, "tem_webhook": ger.tem_webhook, "gateway_url": ger.url_gateway,
        "situacao": est.situacao or "desconhecido", "conectado": est.conectado, "mensagem": est.detalhe,
        "texto_gateway": ger.detalhe_extra(), "qr_id": ger.qr_id(),
    })


@whatsapp_bp.route("/qr")
@whatsapp_bp.route("/qr.svg")
def qr_imagem():
    ger, _ = _gerenciador()
    img = ger.qr_imagem() if ger else None
    if not img:
        return _erro("Não há QR Code no momento.", 404)
    resposta = Response(img[1], mimetype=img[0])
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


# ───────────────────────────── ações ─────────────────────────────
@whatsapp_bp.route("/conectar", methods=["POST"])
def conectar():
    ger, problema = _gerenciador()
    if ger is None:
        return _erro(problema or "WhatsApp não configurado.")
    corpo = request.get_json(silent=True) or {}
    r = ger.conectar(forcar=bool(corpo.get("forcar")))
    if r.get("precisa_confirmar"):
        return jsonify(r), 409
    return jsonify(r), (200 if r["ok"] else 400)


@whatsapp_bp.route("/verificar", methods=["POST"])
def verificar():
    ger, problema = _gerenciador()
    if ger is None:
        return _erro(problema or "WhatsApp não configurado.")
    numero = str((request.get_json(silent=True) or {}).get("numero") or "").strip() or None
    r = ger.verificar(numero)
    return jsonify(r), (200 if r["ok"] else 400)


@whatsapp_bp.route("/teste", methods=["POST"])
def teste():
    global _ultimo_teste
    ger, problema = _gerenciador()
    if ger is None:
        return _erro(problema or "WhatsApp não configurado.")
    corpo = request.get_json(silent=True) or {}
    try:
        alvo = normalizar_numero(corpo.get("numero"))
    except ValueError as exc:
        return _erro(str(exc))
    texto = str(corpo.get("texto") or "").strip() or TEXTO_TESTE
    if len(texto) > LIMITE_TEXTO_TESTE:
        return _erro(f"Mensagem de teste longa demais (máximo {LIMITE_TEXTO_TESTE} caracteres).")
    if not ger.simulado and not corpo.get("confirmo"):
        return _erro("Confirme que quer enviar uma mensagem de verdade.", codigo_erro="falta_confirmacao")
    with _trava_teste:
        agora = time.monotonic()
        if agora - _ultimo_teste < INTERVALO_MIN_TESTE_S:
            return _erro("Espere alguns segundos entre um teste e outro.", 429)
        _ultimo_teste = agora
    try:
        r = ger.provedor.enviar(alvo, texto)
    except EnvioNaoAutorizadoError as exc:
        return _erro(str(exc), 403, codigo_erro="envio_real_bloqueado")
    destino = mascarar_numero(alvo)
    if not r.ok:
        log.warning("whatsapp: teste para %s falhou: %s", destino, r.erro)
        return jsonify({"ok": False, "erro": r.erro, "destino": destino}), 502
    return jsonify({"ok": True, "simulado": r.simulado, "destino": destino, "id_mensagem": r.id_mensagem,
                    "mensagem": ("Simulado: nada foi enviado de verdade." if r.simulado
                                 else f"Mensagem de teste enviada para {destino}.")})


# ───────────────────── mensagem a um responsável (painel) ─────────────────────
def _modelo_texto_prematricula(item: dict) -> str:
    """
    Texto do botão "Mandar mensagem" da fila: o MESMO "Comunicado de Matrícula" do modelo HTML (prazo = hoje + 8 dias,
    documentos, horários, link do grupo da turma), montado por comunicado_matricula.montar_mensagem. Os ajustes
    (escriturário, dias de prazo, links) e o texto (config/comunicado_matricula.txt) são os mesmos do envio automático.
    ValueError se config_usuario.json ou o texto personalizado estiverem errados.
    """
    from datetime import date

    from src.automacao import comunicado_matricula as _comunicado
    return _comunicado.montar_mensagem([str(item.get("nome") or "")], date.today(),
                                       turmas=[str(item.get("turma") or "")], tipo="matriculado")


@whatsapp_bp.route("/modelo-prematricula")
def modelo_prematricula():
    from src.web.api.rotas import _fila_prematricula
    ident = str(request.args.get("id") or "").strip()
    if not ident:
        return _erro("Informe o aluno (id).")
    item = next((r for r in _fila_prematricula() if str(r.get("id")) == ident), None)
    if item is None:
        return _erro("Aluno não está mais na fila da pré-matrícula.", 404)
    telefone = item.get("telefone_responsavel")
    telefone = "" if not telefone or telefone == "—" else str(telefone)
    try:
        texto = _modelo_texto_prematricula(item)
    except ValueError as exc:
        return _erro(str(exc))
    return jsonify({"ok": True, "nome": item.get("nome", ""), "turma": item.get("turma", ""),
                    "telefone": telefone, "texto": texto})


@whatsapp_bp.route("/enviar", methods=["POST"])
def enviar():
    global _ultimo_envio
    ger, problema = _gerenciador()
    if ger is None:
        return _erro(problema or "WhatsApp não configurado.")
    corpo = request.get_json(silent=True) or {}
    try:
        alvo = normalizar_numero(corpo.get("numero"))
    except ValueError as exc:
        return _erro(str(exc))
    texto = str(corpo.get("texto") or "").strip()
    if not texto:
        return _erro("Escreva a mensagem antes de enviar.")
    if len(texto) > LIMITE_TEXTO_MENSAGEM:
        return _erro(f"Mensagem longa demais (máximo {LIMITE_TEXTO_MENSAGEM} caracteres).")
    if not ger.simulado and not corpo.get("confirmo"):
        return _erro("Confirme que quer enviar uma mensagem de verdade.", codigo_erro="falta_confirmacao")
    with _trava_envio:
        agora = time.monotonic()
        if agora - _ultimo_envio < INTERVALO_MIN_ENVIO_S:
            return _erro("Espere alguns segundos entre um envio e outro.", 429)
        _ultimo_envio = agora
    try:
        r = ger.provedor.enviar(alvo, texto)
    except EnvioNaoAutorizadoError as exc:
        return _erro(str(exc), 403, codigo_erro="envio_real_bloqueado")
    destino = mascarar_numero(alvo)
    if not r.ok:
        log.warning("whatsapp: envio para %s falhou: %s", destino, r.erro)
        return jsonify({"ok": False, "erro": r.erro, "destino": destino}), 502
    return jsonify({"ok": True, "simulado": r.simulado, "destino": destino, "id_mensagem": r.id_mensagem,
                    "mensagem": ("Simulado: nada foi enviado de verdade." if r.simulado
                                 else f"Mensagem enviada para {destino}.")})


@whatsapp_bp.route("/envio-real", methods=["POST"])
def envio_real():
    corpo = request.get_json(silent=True) or {}
    ativo = bool(corpo.get("ativo"))
    if ativo and not corpo.get("confirmo"):
        return _erro("Confirme que quer permitir o envio de mensagens reais.", codigo_erro="falta_confirmacao")
    _gravar_env({"WHATSAPP_ENVIO_REAL": "1" if ativo else "0"})
    return jsonify({"ok": True, "envio_real": envio_real_autorizado(),
                    "mensagem": "Envio real PERMITIDO." if ativo else "Envio real bloqueado."})


@whatsapp_bp.route("/provedor", methods=["POST"])
def provedor():
    corpo = request.get_json(silent=True) or {}
    escolhido = str(corpo.get("provedor") or "").strip().lower()
    if escolhido not in ("simulado", "whatsplay", "blake"):
        return _erro("Escolha 'simulado', 'whatsplay' ou 'blake'.")
    valores = {"WHATSAPP_PROVEDOR": escolhido}
    if escolhido == "blake":
        url = str(corpo.get("url") or "").strip()
        if url:
            if not url.startswith(("http://", "https://")):
                return _erro("O endereço do gateway precisa começar com http:// ou https://.")
            valores["WHATSAPP_API_URL"] = url.rstrip("/")
    _gravar_env(valores)
    reiniciar_gerenciador()
    nomes = {"blake": "Gateway Docker selecionado.", "whatsplay": "WhatsApp sem Docker (whatsplay) selecionado.",
             "simulado": "Modo simulado selecionado."}
    return jsonify({"ok": True, "mensagem": nomes[escolhido]})


@whatsapp_bp.route("/desconectar", methods=["POST"])
def desconectar():
    ger, problema = _gerenciador()
    if ger is None or not ger.tem_sessao:
        return _erro(problema or "Não há WhatsApp real para desconectar.")
    r = ger.provedor.sair()
    return jsonify({"ok": r.ok, "mensagem": r.detalhe}), (200 if r.ok else 502)



# ───────────────────────────── fila de envio (7b) ─────────────────────────────
COMUNICADO_ID = "comunicado"       # modelo especial: o "Comunicado de Matrícula" oficial do sistema (mesmo do botão "Mandar mensagem")


def _resposta_fila(**extra):
    return jsonify({**obter_fila().resumo(), **extra})


@whatsapp_bp.route("/fila")
def fila():
    try:
        return _resposta_fila()
    except ValueError as exc:
        return _erro(str(exc))


@whatsapp_bp.route("/fila/itens", methods=["POST"])
def fila_adicionar():
    corpo = request.get_json(silent=True) or {}
    itens = corpo.get("itens")
    if not isinstance(itens, list) or not itens:
        return _erro("Informe as mensagens a pôr na fila.")
    from src.comum import modelos_whatsapp as _modelos
    try:
        base, prontos = _modelos.contexto_base(), []
        for i in (i for i in itens if isinstance(i, dict)):
            nome = " ".join(str(i.get("nome") or "").split())
            texto = _modelos.renderizar(str(i.get("texto") or ""), {**base, "ALUNO": nome})
            sobra = _modelos.marcadores_sobrando(texto)
            if sobra:
                return _erro("Esta mensagem ainda tem " + ", ".join("$" + m for m in sobra) + ". Na mensagem avulsa só valem "
                             "$ESCOLA, $ANO, $PROXIMO_ANO_LETIVO e $DATA, e $ALUNO se você preencher o campo Nome; "
                             "para os demais, escreva o texto final (ou use a lista de alunos da pré-matrícula).")
            prontos.append({**i, "texto": texto})
        r = obter_fila().adicionar(prontos, origem="manual")
        return _resposta_fila(resultado=r)
    except ValueError as exc:
        return _erro(str(exc))


def _previsao_para_fila() -> dict:
    """
    Alunos da pré-matrícula do PRÓXIMO ano letivo (dados/<ano em uso>/previsao_alunos_<ano+1>.json, ex.: previsao_alunos_2027.json).
    Vêm todos os que ainda contam (matriculado ou aguardando vaga; cancelados e quem refez o cadastro em outra escola já ficam
    de fora). Quem será chamado quem decide na tela, por turma e até a posição N da lista (a situação do SERE não manda).
    Devolve {"ano", "arquivo", "alunos": [{id, nome, turma, posicao, telefone, responsavel, situacao}]}.
    ValueError (com o motivo) se o arquivo não existe ou está ilegível.
    """
    from src.comum import paths, previsao
    from src.comum.arquivos_json import ArquivoJsonCorrompidoError

    ano = int(paths.ano_atual()) + 1
    pasta = paths.dados_ano_atual()
    arquivo = previsao.nome_arquivo(ano)
    try:
        dados = previsao.carregar_previsao_alunos(pasta, ano)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(f"{arquivo}: {exc}") from exc
    if not dados:
        raise ValueError(f"Ainda não existe {arquivo} (ou está vazio). Rode a coleta da pré-matrícula para gerá-lo.")
    alunos = [{"id": str(n["cpf"] or n["nome"]), "nome": n["nome"], "turma": n["turma"], "posicao": n["posicao"],
               "telefone": n["telefone"], "responsavel": n["responsavel"], "situacao": n["situacao"]}
              for n in previsao._novos_da_pre_matricula(dados)]

    def _pos(a):
        try:
            return int(str(a["posicao"]).strip())
        except ValueError:
            return 10**9
    alunos.sort(key=lambda a: (a["turma"], _pos(a), a["nome"]))
    return {"ano": ano, "arquivo": arquivo, "alunos": alunos}


def _alunos_prematricula_para_fila() -> list[dict]:
    return _previsao_para_fila()["alunos"]


@whatsapp_bp.route("/fila/prematricula")
def fila_prematricula():
    try:
        p = _previsao_para_fila()
    except ValueError as exc:
        return _erro(str(exc))
    return jsonify({"ano": p["ano"], "arquivo": p["arquivo"],
                    "alunos": [{"id": a["id"], "nome": a["nome"], "turma": a["turma"], "posicao": a["posicao"],
                                "situacao": a["situacao"], "tem_telefone": bool(a["telefone"])} for a in p["alunos"]]})


@whatsapp_bp.route("/fila/da-prematricula", methods=["POST"])
def fila_da_prematricula():
    from src.comum import modelos_whatsapp as _modelos
    corpo = request.get_json(silent=True) or {}
    ids = {str(i) for i in (corpo.get("ids") or [])}
    modelo_id = str(corpo.get("modelo_id") or COMUNICADO_ID)
    texto_tela = str(corpo.get("texto") or "")              # o texto como está na tela (pode ter sido ajustado sem salvar o modelo)
    if not ids:
        return _erro("Marque pelo menos um aluno.")
    try:
        modelo = None
        if modelo_id != COMUNICADO_ID:
            achado = _modelos.obter(modelo_id)
            texto_base = texto_tela.strip() or (achado["texto"] if achado else "")
            if not texto_base.strip():
                return _erro("Escolha um modelo com texto (ou o comunicado de matrícula).")
            modelo = {"texto": texto_base}
        itens, sem_telefone, recusados = [], [], []
        for a in _alunos_prematricula_para_fila():
            if a["id"] not in ids:
                continue
            if not a["telefone"]:
                sem_telefone.append(a["nome"])
                continue
            if modelo is None:
                texto = _modelo_texto_prematricula(a)
            else:
                ctx = {**_modelos.contexto_base(), "ALUNO": a["nome"], "TURMA": a["turma"], "RESPONSAVEL": a["responsavel"] or "responsável"}
                texto = _modelos.renderizar(modelo["texto"], ctx)
            sobra = _modelos.marcadores_sobrando(texto)
            if sobra:
                recusados.append({"nome": a["nome"], "erro": "faltou o dado de " + ", ".join("$" + m for m in sobra)})
                continue
            itens.append({"numero": a["telefone"], "nome": a["nome"], "texto": texto})
        r = obter_fila().adicionar(itens, origem="prematricula") if itens else {"adicionados": 0, "duplicados": 0, "invalidos": []}
        r["invalidos"] = list(r.get("invalidos") or []) + recusados
        r["sem_telefone"] = sem_telefone
        return _resposta_fila(resultado=r)
    except ValueError as exc:
        return _erro(str(exc))


# ───────────── Direcionados GEO: perguntar aos pais se ainda querem a vaga ─────────────
MODELO_GEO_ID = "geo_confirmar_interesse"


def _geo_para_fila() -> dict:
    """Alunos de dados/<ano em uso>/sere_sisgea_<ano+1>.json (ValueError com o motivo se faltar/estiver ilegível)."""
    from src.comum import direcionados_geo as _geo
    from src.comum import paths
    return _geo.alunos_para_mensagem(paths.dados_ano_atual(), int(paths.ano_atual()) + 1)


@whatsapp_bp.route("/fila/geo")
def fila_geo():
    try:
        g = _geo_para_fila()
    except ValueError as exc:
        return _erro(str(exc))
    return jsonify({"ano": g["ano"], "arquivo": g["arquivo"], "modelo_padrao": MODELO_GEO_ID,
                    "alunos": [{"id": a["id"], "nome": a["nome"], "etapa": a["etapa"], "turma": a["turma"],
                                "matricula_confirmada": a["matricula_confirmada"], "tem_telefone": bool(a["telefone"])}
                               for a in g["alunos"]]})


@whatsapp_bp.route("/fila/do-geo", methods=["POST"])
def fila_do_geo():
    from src.comum import direcionados_geo as _geo
    from src.comum import modelos_whatsapp as _modelos
    corpo = request.get_json(silent=True) or {}
    ids = {str(i) for i in (corpo.get("ids") or [])}
    modelo_id = str(corpo.get("modelo_id") or MODELO_GEO_ID)
    if not ids:
        return _erro("Marque pelo menos um aluno.")
    if modelo_id == COMUNICADO_ID:
        return _erro("O comunicado de matrícula é para quem já tem vaga. Para os Direcionados GEO, escolha outro modelo.")
    try:
        achado = _modelos.obter(modelo_id)
        texto_base = str(corpo.get("texto") or "").strip() or (achado["texto"] if achado else "")
        if not texto_base.strip():
            return _erro("Escolha um modelo com texto.")
        itens, sem_telefone, recusados = [], [], []
        for a in _geo_para_fila()["alunos"]:
            if a["id"] not in ids:
                continue
            if not a["telefone"]:
                sem_telefone.append(a["nome"])
                continue
            ctx = {**_modelos.contexto_base(), "ALUNO": a["nome"], "TURMA": a["turma"],
                   "RESPONSAVEL": _geo.primeiro_nome(a["responsavel"]) or "responsável"}
            texto = _modelos.renderizar(texto_base, ctx)
            sobra = _modelos.marcadores_sobrando(texto)
            if sobra:
                recusados.append({"nome": a["nome"], "erro": "faltou o dado de " + ", ".join("$" + m for m in sobra)})
                continue
            itens.append({"numero": a["telefone"], "nome": a["nome"], "texto": texto})
        r = obter_fila().adicionar(itens, origem="geo") if itens else {"adicionados": 0, "duplicados": 0, "invalidos": []}
        r["invalidos"] = list(r.get("invalidos") or []) + recusados
        r["sem_telefone"] = sem_telefone
        return _resposta_fila(resultado=r)
    except ValueError as exc:
        return _erro(str(exc))


# ───────────────────── mensagem em massa aos Direcionados GEO ─────────────────────
GEO_MODELO_PADRAO = "confirmar_interesse_geo"


def _juntar_nomes(nomes: list[str]) -> str:
    """["ANA", "BETO", "CAIO"] -> "ANA, BETO e CAIO" (irmãos com o mesmo telefone recebem UMA mensagem só)."""
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _geo_contatos_massa(etapa: str = "", incluir_confirmados: bool = False) -> dict:
    """
    Direcionados GEO do PRÓXIMO ano letivo (dados/<ano em uso>/sere_sisgea_<ano+1>.json) prontos para a fila.
    Fica de fora: quem saiu da lista do SERE (ausente), quem já tem matrícula confirmada aqui (a menos que
    ``incluir_confirmados``), quem está sem telefone e quem tem telefone que não dá para o WhatsApp.
    Alunos com o MESMO telefone (irmãos) viram UM contato, com os nomes juntos em $ALUNO: o responsável não recebe duas mensagens.
    Devolve {"ano", "arquivo", "coletado_em", "coleta_completa", "contatos": [{numero, nomes, alunos, responsavel, turma, etapas}], "contagem": {...}}.
    ValueError (com o motivo) se o arquivo não existe ou está ilegível.
    """
    from src.comum import direcionados_geo as _geo
    from src.comum import paths
    from src.comum.arquivos_json import ArquivoJsonCorrompidoError

    ano = int(paths.ano_atual()) + 1
    try:
        g = _geo.carregar_direcionados(paths.dados_ano_atual(), ano)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(f"{_geo.nome_arquivo(ano)}: {exc}") from exc
    if not g["existe"] or not g["alunos"]:
        raise ValueError(f"Ainda não existe {_geo.nome_arquivo(ano)} (ou está vazio). Rode a automação \"Direcionados GEO\" para gerá-lo.")

    ausentes = confirmados = sem_telefone = invalidos = fora_da_etapa = 0
    por_numero: dict[str, dict] = {}
    for a in g["alunos"]:
        if a["situacao_lista"] == "ausente":
            ausentes += 1
            continue
        if etapa and a["etapa"] != etapa:
            fora_da_etapa += 1
            continue
        if a["matricula_confirmada"] and not incluir_confirmados:
            confirmados += 1
            continue
        if not a["telefone"]:
            sem_telefone += 1
            continue
        try:
            numero = normalizar_numero(a["telefone"])
        except ValueError:
            invalidos += 1
            continue
        c = por_numero.setdefault(numero, {"numero": numero, "alunos": [], "responsaveis": [], "turmas": [], "etapas": []})
        c["alunos"].append(a["nome"])
        for chave, valor in (("responsaveis", a["responsavel"]), ("turmas", a["turma"]), ("etapas", a["etapa"])):
            if valor and valor not in c[chave]:
                c[chave].append(valor)
    contatos = []
    for c in por_numero.values():
        contatos.append({"numero": c["numero"], "alunos": c["alunos"], "nomes": _juntar_nomes(c["alunos"]),
                         "responsavel": c["responsaveis"][0] if c["responsaveis"] else "",
                         "turma": c["turmas"][0] if len(c["turmas"]) == 1 else "", "etapas": c["etapas"]})
    contatos.sort(key=lambda c: (c["etapas"][0].lower() if c["etapas"] else "", c["alunos"][0].lower()))
    return {"ano": ano, "arquivo": g["arquivo"], "coletado_em": g["coletado_em"], "coleta_completa": g["coleta_completa"],
            "contatos": contatos,
            "contagem": {"mensagens": len(contatos), "alunos": sum(len(c["alunos"]) for c in contatos), "ausentes": ausentes,
                         "ja_confirmados": confirmados, "sem_telefone": sem_telefone, "telefone_invalido": invalidos,
                         "fora_da_etapa": fora_da_etapa}}


@whatsapp_bp.route("/fila/geo/resumo")
def fila_geo_resumo():
    etapa = str(request.args.get("etapa") or "").strip()
    incluir = str(request.args.get("incluir_confirmados") or "").lower() in ("1", "true", "sim")
    try:
        p = _geo_contatos_massa(etapa, incluir)
        from src.comum import direcionados_geo as _geo
        from src.comum import paths
        todas = _geo.carregar_direcionados(paths.dados_ano_atual(), p["ano"])["alunos"]
    except ValueError as exc:
        return _erro(str(exc))
    return jsonify({"ano": p["ano"], "arquivo": p["arquivo"], "coletado_em": p["coletado_em"], "coleta_completa": p["coleta_completa"],
                    "contagem": p["contagem"], "etapas": sorted({a["etapa"] for a in todas if a["etapa"]}),
                    "amostra": [{"nomes": c["nomes"], "responsavel": c["responsavel"], "numero": mascarar_numero(c["numero"])}
                                for c in p["contatos"][:8]]})


@whatsapp_bp.route("/fila/geo/em-massa", methods=["POST"])
def fila_geo_em_massa():
    """Põe na fila uma mensagem por telefone dos Direcionados GEO. Só ENFILEIRA: o envio é a fila (pausa, limite do dia, envio real)."""
    from src.comum import direcionados_geo as _geo
    from src.comum import modelos_whatsapp as _modelos
    corpo = request.get_json(silent=True) or {}
    modelo_id = str(corpo.get("modelo_id") or GEO_MODELO_PADRAO)
    if modelo_id == COMUNICADO_ID:
        return _erro("O comunicado de matrícula é para quem já tem vaga. Para os Direcionados GEO, escolha outro modelo.")
    texto_tela = str(corpo.get("texto") or "").strip()
    etapa = str(corpo.get("etapa") or "").strip()
    try:
        achado = _modelos.obter(modelo_id)
        base = texto_tela or (achado["texto"] if achado else "")
        if not base.strip():
            return _erro("Escolha um modelo com texto (ou escreva a mensagem).")
        _modelos.conferir_marcadores(base)
        p = _geo_contatos_massa(etapa, bool(corpo.get("incluir_confirmados")))
        if not p["contatos"]:
            return _erro("Nenhum direcionado GEO pode receber a mensagem (veja os motivos no resumo).", contagem=p["contagem"])
        if len(p["contatos"]) > 1 and not corpo.get("confirmo"):
            return _erro(f"Confirme que quer pôr {len(p['contatos'])} mensagens na fila.", codigo_erro="falta_confirmacao")
        base_ctx = _modelos.contexto_base()
        itens, recusados = [], []
        for c in p["contatos"]:
            ctx = {**base_ctx, "ALUNO": c["nomes"], "TURMA": c["turma"], "RESPONSAVEL": _geo.primeiro_nome(c["responsavel"]) or "responsável"}
            texto = _modelos.renderizar(base, ctx)
            sobra = _modelos.marcadores_sobrando(texto)
            if sobra:
                recusados.append({"nome": c["nomes"], "erro": "faltou o dado de " + ", ".join("$" + m for m in sobra)})
                continue
            itens.append({"numero": c["numero"], "nome": c["nomes"], "texto": texto})
        r = obter_fila().adicionar(itens, origem="geo") if itens else {"adicionados": 0, "duplicados": 0, "invalidos": []}
        r["invalidos"] = list(r.get("invalidos") or []) + recusados
        r["resumo_geo"] = p["contagem"]
        return _resposta_fila(resultado=r)
    except ValueError as exc:
        return _erro(str(exc))


@whatsapp_bp.route("/fila/config", methods=["POST"])
def fila_config():
    corpo = request.get_json(silent=True) or {}
    try:
        obter_fila().configurar(corpo.get("intervalo_s"), corpo.get("limite_diario"), corpo.get("continuar_no_dia_seguinte", True))
        return _resposta_fila()
    except ValueError as exc:
        return _erro(str(exc))


@whatsapp_bp.route("/fila/iniciar", methods=["POST"])
def fila_iniciar():
    ger, problema = _gerenciador()
    if ger is None:
        return _erro(problema or "WhatsApp não configurado.")
    if not ger.simulado and not (request.get_json(silent=True) or {}).get("confirmo"):
        return _erro("Confirme que quer enviar mensagens de verdade.", codigo_erro="falta_confirmacao")
    try:
        texto = obter_fila().iniciar()
        return _resposta_fila(mensagem_acao=texto)
    except ValueError as exc:
        return _erro(str(exc))


@whatsapp_bp.route("/fila/pausar", methods=["POST"])
def fila_pausar():
    obter_fila().pausar()
    return _resposta_fila()


@whatsapp_bp.route("/fila/cancelar-pendentes", methods=["POST"])
def fila_cancelar_pendentes():
    try:
        n = obter_fila().cancelar_pendentes()
        return _resposta_fila(mensagem_acao=f"{n} mensagem(ns) cancelada(s).")
    except ValueError as exc:
        return _erro(str(exc))


@whatsapp_bp.route("/fila/limpar-historico", methods=["POST"])
def fila_limpar_historico():
    try:
        n = obter_fila().limpar_historico()
        return _resposta_fila(mensagem_acao=f"{n} registro(s) removido(s) da lista.")
    except ValueError as exc:
        return _erro(str(exc))


@whatsapp_bp.route("/fila/itens/<string:id_item>/<string:acao>", methods=["POST"])
def fila_item(id_item, acao):
    if acao not in ("cancelar", "repetir"):
        return _erro("Ação desconhecida.", 404)
    try:
        (obter_fila().cancelar_item if acao == "cancelar" else obter_fila().repetir_item)(id_item)
        return _resposta_fila()
    except ValueError as exc:
        return _erro(str(exc))


def _modelos_fila(**extra):
    from src.comum import modelos_whatsapp as _modelos
    return jsonify({"modelos": _modelos.listar(), "marcadores": list(_modelos.MARCADORES), **extra})


@whatsapp_bp.route("/fila/modelos", methods=["GET", "POST"])
def fila_modelos():
    from src.comum import modelos_whatsapp as _modelos
    try:
        if request.method == "GET":
            return _modelos_fila()
        d = request.get_json(silent=True) or {}
        modelo = _modelos.salvar(d.get("nome"), d.get("texto"), d.get("id") or None)
        return _modelos_fila(modelo=modelo)
    except ValueError as exc:
        return _erro(str(exc))
    except OSError as exc:
        return _erro(f"Não foi possível gravar o modelo: {exc}", 500)


@whatsapp_bp.route("/fila/modelos/<string:id_modelo>", methods=["DELETE"])
def fila_modelo_excluir(id_modelo):
    from src.comum import modelos_whatsapp as _modelos
    try:
        return _modelos_fila(acao=_modelos.excluir(id_modelo))
    except ValueError as exc:
        return _erro(str(exc))
    except OSError as exc:
        return _erro(f"Não foi possível gravar a alteração: {exc}", 500)

# ───────────────────────────── webhooks ─────────────────────────────
def _token_webhook(criar: bool = False) -> str:
    token = os.environ.get("WHATSAPP_WEBHOOK_TOKEN", "").strip()
    if not token and criar:
        token = secrets.token_urlsafe(24)
        _gravar_env({"WHATSAPP_WEBHOOK_TOKEN": token})
    return token


def _url_webhook_local(token: str) -> str:
    base = (os.environ.get("WHATSAPP_WEBHOOK_URL_BASE", "").strip().rstrip("/")
            or f"http://host.docker.internal:{_servidor.servidor_porta()}")
    return f"{base}/web/api/whatsapp/webhook?t={token}"


@whatsapp_bp.route("/webhooks", methods=["GET", "POST", "DELETE"])
def webhooks():
    ger, problema = _gerenciador()
    if ger is None or not ger.tem_gateway:
        return _erro(problema or "Webhooks só existem no gateway Docker (provedor 'blake').")
    prov = ger.provedor
    if request.method == "GET":
        token = _token_webhook()
        lista = prov.webhooks_listar()
        if lista is None:
            return _erro("Não consegui ler os webhooks do gateway (ele está no ar?).", 502)
        local = bool(token) and _url_webhook_local(token) in lista
        return jsonify({"registrado": local, "total_no_gateway": len(lista)})   # nunca devolve as URLs (têm o token)
    if request.method == "POST":
        url = _url_webhook_local(_token_webhook(criar=True))
        r = prov.webhook_registrar(url)
    else:
        token = _token_webhook()
        if not token:
            return jsonify({"ok": True, "mensagem": "Nenhum webhook do sistema estava registrado."})
        r = prov.webhook_remover(_url_webhook_local(token))
    return jsonify({"ok": r.ok, "mensagem": r.detalhe}), (200 if r.ok else 502)


def _despachar_em_segundo_plano(payload: Any) -> None:
    """O gateway ESPERA a resposta do webhook antes de tratar a próxima mensagem: responder já e
    deixar os módulos trabalharem numa thread evita travá-lo."""
    threading.Thread(target=_eventos.despachar, args=(payload,), name="whatsapp-tratadores", daemon=True).start()


@whatsapp_bp.route("/webhook", methods=["POST"])
def webhook_receber():
    esperado = _token_webhook()
    enviado = request.args.get("t", "")
    if not esperado or not hmac.compare_digest(enviado.encode(), esperado.encode()):
        return _erro("Não autorizado.", 403)
    if (request.content_length or 0) > LIMITE_CORPO_WEBHOOK:
        return _erro("Corpo grande demais.", 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _erro("Corpo inválido.")
    _despachar_em_segundo_plano(payload)
    return jsonify({"ok": True})

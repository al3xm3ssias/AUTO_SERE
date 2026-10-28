"""
API do WhatsApp para a interface web  —  prefixo /web/api/whatsapp
===================================================================
    GET  /status         estado da conexão (a tela consulta a cada poucos segundos)
    GET  /qr             QR Code atual: SVG (blake) ou PNG (whatsplay); 404 se não há (/qr.svg é o mesmo)
    POST /conectar       pede ao gateway para iniciar a sessão (gera o QR Code)
    POST /verificar      confirma a conexão perguntando ao WhatsApp por um número
    POST /teste          envia UMA mensagem de teste (trava dupla: WHATSAPP_ENVIO_REAL + confirmo)
    POST /envio-real     liga/desliga a permissão de envio real
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

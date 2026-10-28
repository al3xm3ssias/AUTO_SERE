"""
Provedor HTTP genérico para um gateway de WhatsApp (formato do projeto wwebjs-api).

ATENÇÃO — duas coisas honestas:
  1. Foi escrito a partir da documentação pública desse formato de API e testado só com um
     servidor FALSO (nos testes). Ainda não foi conferido contra um gateway real.
  2. Gateways baseados em whatsapp-web.js são clientes NÃO oficiais: o WhatsApp não os autoriza e
     o número usado pode ser banido, mesmo com poucas mensagens. A alternativa oficial é a
     WhatsApp Business Cloud API (exige conta Meta e modelos de mensagem aprovados). Como o resto do
     sistema só enxerga ProvedorWhatsApp, trocar de provedor não exige mexer nos scripts.

Rotas usadas (padrão wwebjs-api; o prefixo vem de WHATSAPP_API_URL):
  GET  {url}/session/status/{sessao}        → estado da sessão (somente leitura)
  POST {url}/client/sendMessage/{sessao}    → envio (só com autorização explícita)
Autenticação: cabeçalho x-api-key.
"""
from __future__ import annotations

import os
from typing import Any

import requests

from .base import (EnvioNaoAutorizadoError, EstadoConexao, ResultadoEnvio, normalizar_numero)


def envio_real_autorizado() -> bool:
    """Envio real só acontece com WHATSAPP_ENVIO_REAL=1 no ambiente — nunca por padrão."""
    return os.environ.get("WHATSAPP_ENVIO_REAL", "").strip() in ("1", "true", "sim")


class ProvedorHttp:
    nome = "http"

    def __init__(self, url_base: str, api_key: str, sessao: str = "autosere", http: Any = requests, timeout: float = 10.0):
        self.url_base = url_base.rstrip("/")
        self.sessao = sessao
        self.timeout = timeout
        self._http = http
        self._cabecalhos = {"x-api-key": api_key, "Content-Type": "application/json"}

    def estado(self) -> EstadoConexao:
        try:
            r = self._http.get(f"{self.url_base}/session/status/{self.sessao}", headers=self._cabecalhos, timeout=self.timeout)
        except requests.RequestException as exc:
            return EstadoConexao(False, f"Gateway inacessível ({type(exc).__name__}). Ele está ligado e o endereço está certo?")
        if r.status_code in (401, 403):
            return EstadoConexao(False, "Gateway recusou a chave (WHATSAPP_API_KEY incorreta).")
        if r.status_code >= 400:
            return EstadoConexao(False, f"Gateway respondeu erro {r.status_code}.")
        try:
            corpo = r.json()
        except ValueError:
            return EstadoConexao(False, "Resposta inesperada do gateway (não é JSON).")
        conectado = bool(corpo.get("success")) and str(corpo.get("state", "")).upper() == "CONNECTED"
        detalhe = "Conectado." if conectado else f"Sessão não conectada ({corpo.get('state') or corpo.get('message') or 'sem estado'}); pode ser preciso ler o QR Code."
        return EstadoConexao(conectado, detalhe)

    def enviar(self, numero: str, texto: str) -> ResultadoEnvio:
        if not envio_real_autorizado():
            raise EnvioNaoAutorizadoError(
                "Envio real bloqueado: defina WHATSAPP_ENVIO_REAL=1 para autorizar. "
                "Nenhuma mensagem foi enviada."
            )
        alvo = normalizar_numero(numero)
        if not str(texto or "").strip():
            return ResultadoEnvio(False, False, erro="Mensagem vazia.")
        try:
            r = self._http.post(
                f"{self.url_base}/client/sendMessage/{self.sessao}",
                headers=self._cabecalhos, timeout=self.timeout,
                json={"chatId": f"{alvo}@c.us", "contentType": "string", "content": texto},
            )
            corpo = r.json() if r.content else {}
        except requests.RequestException as exc:
            return ResultadoEnvio(False, False, erro=f"Falha de rede: {type(exc).__name__}")
        except ValueError:
            return ResultadoEnvio(False, False, erro="Resposta inesperada do gateway.")
        if r.status_code >= 400 or not corpo.get("success", False):
            return ResultadoEnvio(False, False, erro=str(corpo.get("error") or corpo.get("message") or f"erro {r.status_code}"))
        msg = corpo.get("message") or {}
        id_msg = (msg.get("id") or {}).get("_serialized") if isinstance(msg, dict) and isinstance(msg.get("id"), dict) else None
        return ResultadoEnvio(True, False, id_mensagem=id_msg)

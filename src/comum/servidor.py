"""
servidor.py — host e porta do servidor local do AUTO SERE
==========================================================
Fonte única para o endereço do servidor Flask. É usada pelo servidor
(`src.web.app`), pelo launcher do Windows (`src.launcher`) e pelo atalho.

Ordem de precedência (a primeira que existir vence):
  1. variáveis de ambiente  AUTO_SERE_HOST / AUTO_SERE_PORT
  2. chave "servidor" em config/config_usuario.json
        {"servidor": {"host": "127.0.0.1", "porta": 8000}}
  3. padrão: 127.0.0.1:8000

IMPORTANTE: a PORTA DEVE SER FIXA. O Chrome associa o app instalado (PWA)
à origem http://127.0.0.1:<porta>; se a porta mudar, o app instalado deixa
de funcionar e precisa ser instalado de novo.
"""
from __future__ import annotations

import os

HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8000


def _bloco_config() -> dict:
    """Lê a chave 'servidor' de config_usuario.json; nunca levanta erro."""
    try:
        from src.comum import configuracao

        bloco = configuracao.carregar_configuracao().get("servidor")
        return bloco if isinstance(bloco, dict) else {}
    except Exception:
        return {}


def servidor_host() -> str:
    valor = os.environ.get("AUTO_SERE_HOST") or _bloco_config().get("host")
    return str(valor).strip() if valor else HOST_PADRAO


def servidor_porta() -> int:
    valor = os.environ.get("AUTO_SERE_PORT") or _bloco_config().get("porta")
    try:
        porta = int(valor)
    except (TypeError, ValueError):
        return PORTA_PADRAO
    return porta if 1 <= porta <= 65535 else PORTA_PADRAO


def url_base() -> str:
    """URL que o navegador deve abrir. 0.0.0.0 vira 127.0.0.1 no cliente."""
    host = servidor_host()
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    return f"http://{host}:{servidor_porta()}"


def modo_debug() -> bool:
    """Debug (auto-reload) só liga com AUTO_SERE_DEBUG=1 — nunca por padrão."""
    return os.environ.get("AUTO_SERE_DEBUG", "").strip() in ("1", "true", "True", "sim")

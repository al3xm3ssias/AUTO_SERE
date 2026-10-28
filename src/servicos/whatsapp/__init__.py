"""
Serviço de WhatsApp do AUTO SERE
================================
Os scripts falam só com `ProvedorWhatsApp` (estado/enviar). Por padrão o provedor é o
SIMULADO: nada sai do computador. Provedores:

  simulado  padrão; nunca acessa a rede
  whatsplay WhatsApp Web via Playwright, sem Docker (a opção para Windows; ver docs/WHATSAPP.md)
  blake     gateway Docker blakegt/whatsapp-web-api-rest (precisa de Docker)
  http      gateway no formato wwebjs-api (legado; só testado com servidor falso)

Para ENVIAR de verdade: WHATSAPP_ENVIO_REAL=1. Quem usa o WhatsApp dentro do sistema deve pegar o
provedor por `gerenciador.obter_gerenciador().provedor` (um por processo, com monitor de sessão).
"""
from __future__ import annotations

import os

from .base import (ConfiguracaoIncompletaError, ConsultaNumero, EnvioNaoAutorizadoError, EstadoConexao,
                   ProvedorWhatsApp, ResultadoAcao, ResultadoEnvio, WhatsAppErro, mascarar_numero,
                   normalizar_numero)
from .gateway_blake import ProvedorBlake
from .gateway_http import ProvedorHttp, envio_real_autorizado
from .provedor_whatsplay import ProvedorWhatsplay
from .simulado import ProvedorSimulado

__all__ = [
    "ConfiguracaoIncompletaError", "ConsultaNumero", "EnvioNaoAutorizadoError", "EstadoConexao",
    "ProvedorBlake", "ProvedorHttp", "ProvedorSimulado", "ProvedorWhatsApp", "ProvedorWhatsplay", "ResultadoAcao",
    "ResultadoEnvio", "WhatsAppErro", "criar_provedor", "envio_real_autorizado", "mascarar_numero",
    "normalizar_numero",
]


def criar_provedor() -> ProvedorWhatsApp:
    """Simulado, a menos que WHATSAPP_PROVEDOR=blake|http e a configuração esteja completa.
    (Sem monitor de sessão: para a interface/módulos use gerenciador.obter_gerenciador().)"""
    escolhido = os.environ.get("WHATSAPP_PROVEDOR", "simulado").strip().lower() or "simulado"
    if escolhido == "simulado":
        return ProvedorSimulado()
    if escolhido == "whatsplay":
        from .gerenciador import _provedor_whatsplay_do_ambiente
        return _provedor_whatsplay_do_ambiente()
    if escolhido == "blake":
        from .gateway_blake import NUMERO_SONDA, URL_PADRAO
        return ProvedorBlake(os.environ.get("WHATSAPP_API_URL", "").strip() or URL_PADRAO,
                             validar_numero=os.environ.get("WHATSAPP_VALIDAR_NUMERO", "1").strip().lower() in ("1", "true", "sim", "yes", ""),
                             numero_sonda=os.environ.get("WHATSAPP_NUMERO_SONDA", "").strip() or NUMERO_SONDA)
    if escolhido == "http":
        faltando = [v for v in ("WHATSAPP_API_URL", "WHATSAPP_API_KEY") if not os.environ.get(v, "").strip()]
        if faltando:
            raise ConfiguracaoIncompletaError(
                "Faltam variáveis para o provedor 'http': " + ", ".join(faltando) + " (veja .env.example)."
            )
        return ProvedorHttp(os.environ["WHATSAPP_API_URL"], os.environ["WHATSAPP_API_KEY"],
                            os.environ.get("WHATSAPP_SESSAO", "autosere") or "autosere")
    raise ConfiguracaoIncompletaError(f"WHATSAPP_PROVEDOR desconhecido: '{escolhido}' (use 'simulado', 'whatsplay', 'blake' ou 'http').")

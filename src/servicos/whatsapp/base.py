"""Contrato comum dos provedores de WhatsApp + utilidades (normalização e máscara de número)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol


class WhatsAppErro(Exception):
    """Erro genérico do serviço de WhatsApp."""


class ConfiguracaoIncompletaError(WhatsAppErro):
    """Falta alguma variável de ambiente para o provedor escolhido."""


class EnvioNaoAutorizadoError(WhatsAppErro):
    """Tentativa de enviar mensagem real sem a autorização explícita."""


@dataclass(frozen=True)
class EstadoConexao:
    conectado: bool
    detalhe: str
    numero: Optional[str] = None      # número da sessão, quando o provedor informa (sempre mascarado ao exibir)
    # Situação em uma palavra (ver Situacao em monitor.py). Vazia nos provedores que não informam.
    situacao: str = ""


@dataclass(frozen=True)
class ConsultaNumero:
    """Resultado de "esse número tem WhatsApp?" (gateway blake: GET /number/<n>)."""
    situacao: str                     # "existe" | "nao_existe" | "indisponivel"
    jid: Optional[str] = None         # identificador canônico devolvido pelo WhatsApp (já com o 9º dígito certo)
    detalhe: str = ""


@dataclass(frozen=True)
class ResultadoEnvio:
    ok: bool
    simulado: bool
    id_mensagem: Optional[str] = None
    erro: Optional[str] = None
    # Saiu (ok=True), mas o provedor não conseguiu ver a confirmação (tique) a tempo. Não é falha: a fila não conta isso
    # para pausar, só mostra o aviso no item.
    aviso: Optional[str] = None


@dataclass(frozen=True)
class ResultadoAcao:
    """Resultado de uma ação de administração do gateway (iniciar sessão, webhooks, sair...)."""
    ok: bool
    detalhe: str


class ProvedorWhatsApp(Protocol):
    """O que o resto do sistema espera de qualquer provedor (trocar o provedor não muda os scripts)."""

    nome: str

    def estado(self) -> EstadoConexao: ...
    def enviar(self, numero: str, texto: str) -> ResultadoEnvio: ...


def normalizar_numero(numero) -> str:
    """
    Telefone brasileiro → só dígitos com DDI: "(42) 99999-8888" → "5542999998888".
    Aceita 10 ou 11 dígitos (DDD + número) ou 12 ou 13 já com 55. Levanta ValueError se não servir.
    """
    d = re.sub(r"\D", "", str(numero or ""))
    if len(d) in (10, 11):
        d = "55" + d
    if len(d) not in (12, 13) or not d.startswith("55"):
        raise ValueError("Número inválido: informe DDD + telefone (ex.: 42 99999-8888).")
    if not 11 <= int(d[2:4]) <= 99:
        raise ValueError("Número inválido: DDD incorreto.")
    return d


def mascarar_numero(numero) -> str:
    """Para logs e telas: deixa só o DDD e os 2 últimos dígitos ("55 42 *****-**88")."""
    d = re.sub(r"\D", "", str(numero or ""))
    if len(d) < 6:
        return "***"
    return f"{d[:2]} {d[2:4]} {'*' * (len(d) - 6)}-**{d[-2:]}" if len(d) > 6 else "***"

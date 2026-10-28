"""
Mensagens recebidas — gancho para módulos futuros
=================================================
O gateway entrega cada mensagem recebida por POST nos webhooks registrados nele. Neste projeto
o destino é `POST /web/api/whatsapp/webhook?t=<token>` (src/web/api/whatsapp.py), que chama
`despachar()` aqui. Um módulo futuro (ex.: responder dúvidas da pré-matrícula, confirmar
recebimento de termos) só precisa se registrar:

    from src.servicos.whatsapp import eventos

    @eventos.registrar_tratador
    def meu_modulo(msg: eventos.MensagemRecebida) -> None:
        if msg.tipo == "text" and not msg.minha and msg.numero:
            ...

Regras:
  • cada tratador roda isolado: erro num não impede os outros nem derruba o webhook;
  • o texto das mensagens NÃO vai para log (dados de alunos/famílias);
  • `msg.numero` só existe para conversa individual com número de telefone (jid @s.whatsapp.net).
    Grupos (@g.us) e contatos "@lid" chegam com `numero == ""`;
  • AVISO de segurança: a versão do Baileys da imagem atual tem aviso de falsificação de mensagens
    recebidas. Não tome decisões irreversíveis (apagar, alterar cadastro) com base só no que chegou
    por aqui; trate como "pedido a confirmar".
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MensagemRecebida:
    de: str                                   # jid de origem (ex.: 5542999998888@s.whatsapp.net)
    numero: str                               # só dígitos, ou "" (grupo / @lid)
    id: str
    tipo: str                                 # text | image | video | audio | document | unknown
    texto: str
    nome_exibicao: str
    minha: bool                               # True = mensagem enviada por nós (eco)
    em_grupo: bool
    midia_mimetype: str = ""
    midia_legenda: str = ""
    midia_base64: str = field(default="", repr=False)    # pode ser grande; fora do repr/logs
    chave: dict = field(default_factory=dict, repr=False)   # key do Baileys (serve p/ POST /messages/read)


Tratador = Callable[[MensagemRecebida], None]
_tratadores: list[Tratador] = []


def registrar_tratador(func: Tratador) -> Tratador:
    """Pode ser usado como decorador. Registrar duas vezes a mesma função não duplica."""
    if func not in _tratadores:
        _tratadores.append(func)
    return func


def remover_tratador(func: Tratador) -> None:
    if func in _tratadores:
        _tratadores.remove(func)


def interpretar(payload: Any) -> Optional[MensagemRecebida]:
    """Converte o JSON do webhook do gateway. None se não for uma mensagem (ex.: evento de chamada)."""
    if not isinstance(payload, dict) or "from" not in payload:
        return None
    de = str(payload.get("from") or "")
    if not de:
        return None
    midia = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    numero = ""
    m = re.fullmatch(r"(\d{8,15})@s\.whatsapp\.net", de)
    if m:
        numero = m.group(1)
    chave = payload.get("key") if isinstance(payload.get("key"), dict) else {}
    return MensagemRecebida(
        de=de, numero=numero, id=str(payload.get("messageId") or ""),
        tipo=str(payload.get("type") or "unknown"), texto=str(payload.get("message") or ""),
        nome_exibicao=str(payload.get("pushName") or ""), minha=bool(payload.get("isMe")),
        em_grupo=de.endswith("@g.us"),
        midia_mimetype=str(midia.get("mimeType") or ""), midia_legenda=str(midia.get("caption") or ""),
        midia_base64=str(midia.get("base64") or ""), chave=dict(chave),
    )


def despachar(payload: Any) -> int:
    """Entrega a mensagem a todos os tratadores. Devolve quantos rodaram (0 se não era mensagem)."""
    msg = interpretar(payload)
    if msg is None:
        return 0
    rodaram = 0
    for tratador in list(_tratadores):
        try:
            tratador(msg)
            rodaram += 1
        except Exception:                                    # um tratador ruim não derruba os outros
            log.exception("whatsapp: tratador %s falhou (mensagem não registrada em log)",
                          getattr(tratador, "__name__", repr(tratador)))
    return rodaram

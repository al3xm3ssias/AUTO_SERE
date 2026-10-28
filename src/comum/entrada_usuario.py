"""
entrada_usuario.py — pedir uma informação ao usuário NO MEIO de uma automação
=============================================================================
Algumas automações precisam de algo que só o usuário tem na hora — o exemplo é o código de
verificação (2FA) que o RCO manda por e-mail. Nos scripts originais isso era um `input()` no
terminal, que não existe na interface web.

Como funciona (a interface web e a automação rodam no mesmo processo, em threads diferentes):

    automação  →  await perguntar("parecer_rco", "Código de verificação", "...")
                    registra o pedido e fica esperando (sem travar o navegador nem o cancelamento)
    interface  →  vê o pedido em GET /automacoes/<chave>/status ("pergunta"), abre uma caixa,
                  e envia a resposta em POST /automacoes/<chave>/resposta
    automação  →  recebe o texto e segue

Na linha de comando (`python -m src.comum.cli ...`) não há interface: a CLI liga o modo terminal
(`usar_terminal()`) e o pedido vira um `input()` normal.

Cancelar a automação (task do asyncio cancelada) interrompe a espera e apaga o pedido.
"""
from __future__ import annotations

import asyncio
import getpass
import threading
import time
import uuid
from typing import Callable, Optional

# Quanto tempo a automação espera pela resposta antes de desistir (o e-mail do código costuma chegar em segundos).
TIMEOUT_PADRAO_S = 600.0

_TRAVA = threading.Lock()
_PENDENTES: dict[str, dict] = {}        # chave da automação → pedido (um por vez)
_MODO_TERMINAL = False


class PedidoExpirou(TimeoutError):
    """O usuário não respondeu a tempo."""


def usar_terminal(ligado: bool = True) -> None:
    """Liga/desliga o modo terminal (linha de comando): os pedidos viram input()/getpass()."""
    global _MODO_TERMINAL
    _MODO_TERMINAL = bool(ligado)


def pergunta_pendente(chave: str) -> Optional[dict]:
    """O pedido em aberto desta automação, só com o que a tela precisa (nunca a resposta nem o validador)."""
    with _TRAVA:
        p = _PENDENTES.get(chave)
        if p is None or p["resposta"] is not None:
            return None
        return {"id": p["id"], "titulo": p["titulo"], "mensagem": p["mensagem"],
                "rotulo": p["rotulo"], "segredo": p["segredo"]}


def responder(chave: str, pedido_id: str, valor: str) -> tuple[bool, str]:
    """
    Entrega a resposta do usuário. Devolve (ok, mensagem).
    Resposta recusada pela validação NÃO encerra o pedido: a tela mostra a mensagem e o usuário tenta de novo.
    """
    valor = str(valor or "").strip()
    with _TRAVA:
        p = _PENDENTES.get(chave)
        if p is None or p["resposta"] is not None:
            return False, "Não há nenhuma pergunta aguardando resposta (ela pode ter expirado ou sido cancelada)."
        if str(pedido_id) != p["id"]:
            return False, "Esta pergunta já não está mais valendo. Feche a caixa e espere a próxima."
        validar = p["validar"]
        if not valor:
            return False, "Digite a resposta antes de enviar."
        if validar is not None:
            try:
                validar(valor)
            except ValueError as exc:
                return False, str(exc)
        p["resposta"] = valor
    return True, "Resposta enviada."


def cancelar_pendente(chave: str) -> None:
    """Apaga o pedido em aberto (usado ao cancelar a automação)."""
    with _TRAVA:
        _PENDENTES.pop(chave, None)


async def perguntar(
    chave: str,
    titulo: str,
    mensagem: str = "",
    rotulo: str = "",
    *,
    segredo: bool = False,
    validar: Optional[Callable[[str], None]] = None,
    timeout: float = TIMEOUT_PADRAO_S,
    intervalo: float = 0.25,
) -> str:
    """
    Pede um texto ao usuário e espera. `validar(valor)` levanta ValueError com uma mensagem pronta
    para recusar a resposta. Levanta PedidoExpirou se ninguém responder em `timeout` segundos.
    """
    if _MODO_TERMINAL:
        return await _perguntar_no_terminal(titulo, mensagem, rotulo, segredo, validar)

    pedido = {
        "id": uuid.uuid4().hex, "titulo": titulo, "mensagem": mensagem, "rotulo": rotulo,
        "segredo": segredo, "validar": validar, "resposta": None,
    }
    with _TRAVA:
        _PENDENTES[chave] = pedido
    limite = time.monotonic() + timeout
    try:
        while True:
            with _TRAVA:
                resposta = pedido["resposta"]
            if resposta is not None:
                return resposta
            if time.monotonic() >= limite:
                raise PedidoExpirou(f"Ninguém respondeu a \"{titulo}\" em {int(timeout // 60)} minuto(s).")
            await asyncio.sleep(intervalo)
    finally:
        with _TRAVA:
            if _PENDENTES.get(chave) is pedido:
                del _PENDENTES[chave]


async def _perguntar_no_terminal(titulo, mensagem, rotulo, segredo, validar) -> str:
    print(f"\n{titulo}" + (f"\n{mensagem}" if mensagem else ""))
    ler = getpass.getpass if segredo else input
    while True:
        valor = (await asyncio.to_thread(ler, f">> {rotulo or titulo}: ")).strip()
        try:
            if not valor:
                raise ValueError("Digite a resposta.")
            if validar is not None:
                validar(valor)
            return valor
        except ValueError as exc:
            print(f"   {exc}")

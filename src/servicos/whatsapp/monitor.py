"""
Monitor da sessão do gateway (blakegt/whatsapp-web-api-rest)
============================================================
O gateway NÃO tem endpoint de status. A única fonte de verdade sobre a sessão é o fluxo
SSE `GET /sse`, que emite `data: {"qr": "<texto do QR>", "text": "<mensagem>"}` quando algo
muda (QR novo, "Connected to WhatsApp!", "Reconnecting in ...", mensagem de erro...).
Esse fluxo NÃO repete eventos antigos: quem se conecta depois só vê o que vier em seguida.

Este módulo mantém uma conexão SSE aberta numa thread (daemon) e guarda o último estado:

    desconhecido  → o gateway está no ar, mas ainda não chegou nenhum evento (ver `ao_conectar`)
    iniciando     → pedimos ao gateway para iniciar a sessão (GET /); esperando o 1º evento
    aguardando_qr → há um QR Code para ler no celular (`foto().qr`)
    conectado     → "Connected to WhatsApp!"
    reconectando  → o gateway está tentando reconectar sozinho
    desconectado  → mensagem de erro/encerramento (`foto().texto`)
    gateway_offline → não consegui abrir o /sse (gateway desligado ou endereço errado)

Os textos reconhecidos foram conferidos no código-fonte do gateway (whatsapp.service.ts) e o
formato do SSE foi conferido rodando o gateway de verdade (sem WhatsApp). O QR é um segredo de
pareamento: nunca é gravado em log.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import requests

log = logging.getLogger(__name__)


class Situacao:
    VERIFICANDO = "verificando"      # ainda não terminou a 1ª tentativa de falar com o gateway
    DESCONHECIDO = "desconhecido"
    INICIANDO = "iniciando"
    AGUARDANDO_QR = "aguardando_qr"
    CONECTADO = "conectado"
    RECONECTANDO = "reconectando"
    DESCONECTADO = "desconectado"
    GATEWAY_OFFLINE = "gateway_offline"
    PARADO = "parado"                # whatsplay: o navegador ainda não foi aberto (ou foi fechado)
    SIMULADO = "simulado"


# Textos que o gateway emite (whatsapp.service.ts)
TEXTO_CONECTADO = ("Connected to WhatsApp!", "WhatsApp is already connected!")
TEXTO_RECONECTANDO = "Reconnecting"

INICIANDO_EXPIRA_S = 60.0     # "iniciando" sem nenhum evento por tanto tempo volta a "desconhecido"


@dataclass(frozen=True)
class Foto:
    situacao: str
    qr: str = ""                  # texto do QR atual (vazio se não há)
    texto: str = ""               # última mensagem do gateway (erro, "Reconnecting...", ...)
    gateway_online: bool = False
    atualizado_em: float = 0.0    # epoch do último evento que mudou a situação


FonteLinhas = Callable[[], Iterable[str]]


def fonte_sse_http(url_base: str, http=requests, timeout_conexao: float = 3.0, timeout_leitura: float = 70.0) -> FonteLinhas:
    """Fonte padrão: abre GET {url}/sse e entrega as linhas. Entrega ': conectado' assim que o
    gateway aceita a conexão (o SSE pode ficar minutos em silêncio e isso prova que está no ar)."""
    def abrir() -> Iterable[str]:
        resp = http.get(f"{url_base.rstrip('/')}/sse", stream=True, timeout=(timeout_conexao, timeout_leitura),
                        headers={"Accept": "text/event-stream"})
        try:
            if resp.status_code != 200:
                raise requests.RequestException(f"/sse respondeu {resp.status_code}")
            yield ": conectado"
            for linha in resp.iter_lines(decode_unicode=True):
                if linha is not None:
                    yield linha
        finally:
            resp.close()
    return abrir


class MonitorSessao:
    def __init__(self, fonte: FonteLinhas, *, esperas: tuple[float, ...] = (1, 2, 4, 8, 15),
                 relogio: Callable[[], float] = time.time,
                 ao_conectar: Optional[Callable[[], None]] = None) -> None:
        """
        fonte        : função que devolve um iterável de linhas SSE (ver fonte_sse_http).
        ao_conectar  : chamada (na thread do monitor) cada vez que o /sse (re)conecta e a situação é
                       "desconhecido" — o gerenciador usa isso para confirmar a sessão por consulta.
        """
        self._fonte, self._esperas, self._relogio, self._ao_conectar = fonte, esperas, relogio, ao_conectar
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._situacao, self._qr, self._texto = Situacao.DESCONHECIDO, "", ""
        self._online, self._em = False, 0.0
        self._verificado = False          # já houve ao menos um resultado (conectou ou falhou)
        self._iniciando_em = 0.0

    # ── ciclo de vida ──
    def iniciar(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._parar.clear()
            self._thread = threading.Thread(target=self._loop, name="whatsapp-monitor", daemon=True)
            self._thread.start()

    def parar(self) -> None:
        self._parar.set()

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── leitura ──
    def foto(self) -> Foto:
        with self._lock:
            sit = self._situacao
            if not self._online:
                sit = Situacao.GATEWAY_OFFLINE if self._verificado else Situacao.VERIFICANDO
            elif sit == Situacao.INICIANDO and self._relogio() - self._iniciando_em > INICIANDO_EXPIRA_S:
                sit = Situacao.DESCONHECIDO
            return Foto(sit, self._qr if sit == Situacao.AGUARDANDO_QR else "", self._texto, self._online, self._em)

    # ── escrita (usada pelo gerenciador) ──
    def marcar_iniciando(self, se_inalterado_desde: Optional[float] = None) -> None:
        """Com `se_inalterado_desde` (o `atualizado_em` visto antes do GET /), só marca se nenhum evento
        chegou nesse meio-tempo — senão sobrescreveria um QR/“conectado” que já chegou."""
        with self._lock:
            if se_inalterado_desde is not None and self._em != se_inalterado_desde:
                return
            self._situacao, self._qr, self._texto = Situacao.INICIANDO, "", ""
            self._iniciando_em = self._em = self._relogio()

    def marcar_conectado_por_consulta(self, texto: str = "Sessão confirmada por consulta ao WhatsApp.") -> None:
        with self._lock:
            self._situacao, self._qr, self._texto, self._em = Situacao.CONECTADO, "", texto, self._relogio()

    # ── internos ──
    def _definir(self, situacao: str, qr: str = "", texto: str = "") -> None:
        with self._lock:
            self._situacao, self._qr, self._texto, self._em = situacao, qr, texto, self._relogio()

    def _marcar_online(self, online: bool) -> None:
        with self._lock:
            mudou_para_online = online and not self._online
            self._online = online
            self._verificado = True
            if mudou_para_online:
                # Perdemos o fio da meada enquanto estávamos fora: o gateway pode ter reiniciado.
                self._situacao, self._qr, self._texto, self._em = Situacao.DESCONHECIDO, "", "", self._relogio()
        if mudou_para_online and self._ao_conectar:
            try:
                self._ao_conectar()
            except Exception:                                   # nunca derruba o monitor
                log.exception("whatsapp: falha no ao_conectar")

    def processar_linha(self, linha: str) -> None:
        """Interpreta UMA linha SSE. Público para facilitar os testes."""
        linha = (linha or "").strip()
        if not linha.startswith("data:"):
            return                                             # id:, comentários, linhas vazias
        try:
            evento = json.loads(linha[5:].strip())
        except ValueError:
            return
        if not isinstance(evento, dict):
            return
        qr = str(evento.get("qr") or "")
        texto = str(evento.get("text") or "")
        if qr:
            self._definir(Situacao.AGUARDANDO_QR, qr=qr)
        elif texto in TEXTO_CONECTADO:
            self._definir(Situacao.CONECTADO, texto=texto)
        elif texto.startswith(TEXTO_RECONECTANDO):
            self._definir(Situacao.RECONECTANDO, texto=texto)
        elif texto:
            self._definir(Situacao.DESCONECTADO, texto=texto)

    def _loop(self) -> None:
        falhas = 0
        while not self._parar.is_set():
            conectou = False
            try:
                for linha in self._fonte():
                    if self._parar.is_set():
                        return
                    if not conectou:
                        conectou, falhas = True, 0
                        self._marcar_online(True)
                    self.processar_linha(linha)
            except Exception as exc:                            # rede, timeout de leitura, gateway desligado...
                log.debug("whatsapp: /sse caiu (%s)", type(exc).__name__)
            if conectou:
                # O fluxo existia e acabou (timeout de leitura num SSE parado é normal): reconecta logo.
                # Se o gateway tiver caído de verdade, a próxima tentativa falha e cai no ramo abaixo.
                if self._parar.wait(0.5):
                    return
                continue
            self._marcar_online(False)                          # nem conectar conseguiu: gateway fora do ar
            espera = self._esperas[min(falhas, len(self._esperas) - 1)]
            falhas += 1
            if self._parar.wait(espera):
                return

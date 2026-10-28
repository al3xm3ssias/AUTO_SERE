"""
Provedor "whatsplay" — WhatsApp Web via Playwright, sem Docker
===============================================================
Usa a biblioteca `whatsplay` (PyPI, 1 mantenedor, cliente NÃO oficial): abre o WhatsApp Web num
Chromium com perfil persistente — o QR Code é lido uma vez e a sessão fica no perfil.

Escrito a partir da leitura do código da whatsplay 2.6.1. O que isso exige, e este módulo faz:

  • Thread própria com loop asyncio próprio: o Flask é síncrono e a biblioteca é assíncrona.
  • O construtor do Client registra handlers de sinal (`signal.signal`), que só funcionam na
    thread principal → subclasse que anula isso (senão o Client nem é criado numa thread).
  • A biblioteca sobe, por conta própria, um servidor de QR em 0.0.0.0:8000 SEM senha (o QR é
    uma chave de pareamento) → desligado aqui; o QR só sai pela tela do AUTO SERE.
  • `send_message("nome")` procura o contato pelo NOME (substring) e pode escrever para a pessoa
    errada → aqui o envio é sempre por NÚMERO (`open_via_url=True`: abre /send?phone=<dígitos>).
  • `send_message` devolve False também quando a mensagem pode ter saído sem o "tique" ser visto;
    `send_file` devolve True sem confirmar. Os resultados refletem isso (sem id de mensagem).
  • Handlers que lançam exceção atrapalham o loop da biblioteca → todos blindados.

Limites: depende do HTML do WhatsApp Web (seletores). Quando o WhatsApp mudar o site, pode parar
até sair uma versão nova da biblioteca (por isso a versão fica fixada em requirements.txt).
Não foi possível testar contra o WhatsApp Web real; os testes usam uma página de mentira local.

Envio real continua exigindo WHATSAPP_ENVIO_REAL=1.
"""
from __future__ import annotations

import asyncio
import atexit
import hashlib
import logging
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .base import EnvioNaoAutorizadoError, EstadoConexao, ResultadoAcao, ResultadoEnvio, normalizar_numero
from .gateway_http import envio_real_autorizado
from .monitor import Foto, Situacao

log = logging.getLogger(__name__)

AVISO_INSTALAR = ("A biblioteca whatsplay não está instalada. Execute: pip install whatsplay==2.6.1  e depois  "
                  "python -m playwright install chromium")
SEM_CARREGAR_APOS_S = 120.0       # sem estado reconhecido por tanto tempo → orienta a olhar a janela
TIMEOUT_ENVIO_S = 180.0
TIMEOUT_PARADA_S = 20.0
INTERVALO_MIN_ENVIO_S = 3.0       # espaçamento mínimo entre mensagens (estabilidade e menor risco de bloqueio)

_NUMEROS = re.compile(r"\d{8,15}")


class _MascararNumeros(logging.Filter):
    """A whatsplay escreve o número completo em log (ex.: "Sending message to '5542999998888'").
    Dados de alunos/famílias não vão para log: sequências longas de dígitos viram `***NN`."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            texto = record.getMessage()
        except Exception:
            return True
        mascarado = _NUMEROS.sub(lambda m: "***" + m.group(0)[-2:], texto)
        if mascarado != texto:
            record.msg, record.args = mascarado, ()
        return True


def proteger_log_da_biblioteca() -> None:
    """Silencia o INFO da whatsplay (ruído do poller) e mascara números no que restar. Idempotente."""
    raiz = logging.getLogger("whatsplay")
    raiz.setLevel(logging.WARNING)
    for h in raiz.handlers:                     # filtro no handler vale também para os submódulos
        if not any(isinstance(f, _MascararNumeros) for f in h.filters):
            h.addFilter(_MascararNumeros())


FabricaCliente = Callable[[], Any]
PrepararContexto = Callable[[Any], Awaitable[None]]


def fabricar_cliente(pasta_perfil: Path, headless: bool, preparar_contexto: Optional[PrepararContexto] = None) -> Any:
    """Cria o Client da whatsplay já blindado (ver cabeçalho). Importa a biblioteca só aqui."""
    from whatsplay import Client
    from whatsplay import state_manager as _sm
    from whatsplay import utils as _utils

    def _sem_servidor_de_qr(*_a: Any, **_k: Any) -> None:
        return None
    proteger_log_da_biblioteca()
    for modulo in (_sm, _utils):                      # o state_manager importa estes nomes direto de utils
        for nome in ("show_qr_window", "update_qr_code", "close_qr_window"):
            setattr(modulo, nome, _sem_servidor_de_qr)

    class ClienteAutoSere(Client):
        def _setup_signal_handlers(self) -> None:     # signal.signal só funciona na thread principal
            return None

        async def _configure_context(self) -> None:
            await super()._configure_context()
            if preparar_contexto:
                await preparar_contexto(self._context)

    pasta_perfil.mkdir(parents=True, exist_ok=True)
    return ClienteAutoSere(user_data_dir=str(pasta_perfil), headless=headless, auth=None)


class SessaoWhatsplay:
    """Mantém o Client rodando numa thread e expõe estado, QR e execução de tarefas nele."""

    def __init__(self, fabrica: FabricaCliente, relogio: Callable[[], float] = time.time) -> None:
        self._fabrica, self._relogio = fabrica, relogio
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Any = None
        self._qr_png: Optional[bytes] = None
        self._ultimo_erro, self._erro_fatal = "", ""
        self._iniciada_em = self._em = 0.0
        self._janela_fechada = False

    # ── ciclo de vida ──
    @property
    def ativa(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> ResultadoAcao:
        with self._lock:
            if self.ativa:
                return ResultadoAcao(True, "O WhatsApp já está sendo aberto/está aberto.")
            self._qr_png, self._ultimo_erro, self._erro_fatal, self._janela_fechada = None, "", "", False
            self._iniciada_em = self._em = self._relogio()
            self._thread = threading.Thread(target=self._rodar, name="whatsapp-whatsplay", daemon=True)
            self._thread.start()
        return ResultadoAcao(True, "Abrindo o WhatsApp Web. Se for a primeira vez, o QR Code aparece em instantes.")

    def parar(self, timeout: float = TIMEOUT_PARADA_S) -> None:
        loop, client, thread = self._loop, self._client, self._thread
        if loop and client and thread and thread.is_alive() and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(client.stop(), loop).result(timeout)
            except Exception:
                log.debug("whatsapp: erro ao parar o cliente", exc_info=True)
        if thread:
            thread.join(timeout)

    def _rodar(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._principal())
        except Exception as exc:
            self._erro_fatal = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("whatsapp: whatsplay encerrou com erro (%s)", type(exc).__name__)
        finally:
            self._em = self._relogio()
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                self._loop = None

    async def _principal(self) -> None:
        try:
            self._client = self._fabrica()
        except ImportError:
            self._erro_fatal = AVISO_INSTALAR
            return
        cli = self._client

        def blindado(func: Callable[..., None]) -> Callable[..., Awaitable[None]]:
            async def _h(*args: Any, **kw: Any) -> None:       # exceção em handler atrapalharia o loop da biblioteca
                try:
                    func(*args, **kw)
                except Exception:
                    log.debug("whatsapp: handler falhou", exc_info=True)
            return _h

        def _qr(dados: Any = None) -> None:
            if isinstance(dados, (bytes, bytearray)) and dados:
                self._qr_png, self._em = bytes(dados), self._relogio()

        def _logado() -> None:
            self._qr_png, self._em = None, self._relogio()

        def _erro(msg: Any = "") -> None:
            self._ultimo_erro = str(msg)[:300]

        cli.event("on_qr")(blindado(_qr))
        cli.event("on_qr_change")(blindado(_qr))
        cli.event("on_logged_in")(blindado(_logado))
        cli.event("on_error")(blindado(_erro))
        await cli.start()                                       # roda até parar

    # ── leitura ──
    def _estado_da_biblioteca(self) -> str:
        cli = self._client
        estado = getattr(cli, "current_state", None) if cli else None
        return getattr(estado, "name", "") or ""

    def _verificar_janela(self) -> None:
        """Se o usuário fechou a janela do navegador, a biblioteca fica "carregando" para sempre."""
        cli = self._client
        pagina = getattr(cli, "_page", None) if cli else None
        if pagina is not None and self.ativa and not self._janela_fechada:
            try:
                fechada = pagina.is_closed()
            except Exception:
                fechada = True
            if fechada and self._relogio() - self._iniciada_em > 5:
                self._janela_fechada = True
                loop = self._loop
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(cli.stop(), loop)

    def foto(self) -> Foto:
        self._verificar_janela()
        agora = self._relogio()
        if not self.ativa:
            if self._erro_fatal:
                return Foto(Situacao.DESCONECTADO, texto=self._erro_fatal, atualizado_em=self._em)
            if self._janela_fechada:
                return Foto(Situacao.PARADO, texto="A janela do navegador foi fechada.", atualizado_em=self._em)
            return Foto(Situacao.PARADO, atualizado_em=self._em)
        nome = self._estado_da_biblioteca()
        if nome == "LOGGED_IN":
            return Foto(Situacao.CONECTADO, gateway_online=True, atualizado_em=self._em)
        if nome == "QR_AUTH":
            return Foto(Situacao.AGUARDANDO_QR, qr=("png" if self._qr_png else ""), gateway_online=True,
                        atualizado_em=self._em)
        if nome == "ERROR":
            return Foto(Situacao.DESCONECTADO, texto=self._ultimo_erro, gateway_online=True, atualizado_em=self._em)
        texto = ""
        if agora - self._iniciada_em > SEM_CARREGAR_APOS_S:
            texto = ("O WhatsApp Web não chegou a uma tela conhecida. Olhe a janela do navegador: se pedir para "
                     "atualizar o Chrome ou mostrar outra tela, a biblioteca pode precisar de atualização.")
        return Foto(Situacao.INICIANDO, texto=texto, gateway_online=True, atualizado_em=self._em)

    def qr_png(self) -> Optional[bytes]:
        return self._qr_png if self._estado_da_biblioteca() == "QR_AUTH" else None

    def ultimo_erro(self) -> str:
        return self._ultimo_erro

    def limpar_erro(self) -> None:
        self._ultimo_erro = ""

    # ── tarefas ──
    def executar(self, fazer: Callable[[Any], Awaitable[Any]], timeout: float = TIMEOUT_ENVIO_S) -> Any:
        """Roda `fazer(client)` no loop da sessão e espera o resultado."""
        loop, cli = self._loop, self._client
        if not (self.ativa and loop and cli and loop.is_running()):
            raise RuntimeError("sessão não está ativa")
        return asyncio.run_coroutine_threadsafe(fazer(cli), loop).result(timeout)


class ProvedorWhatsplay:
    nome = "whatsplay"

    def __init__(self, sessao: SessaoWhatsplay, *, intervalo_min_s: float = INTERVALO_MIN_ENVIO_S,
                 relogio: Callable[[], float] = time.monotonic, dormir: Callable[[float], None] = time.sleep) -> None:
        self.sessao = sessao
        self._intervalo, self._relogio, self._dormir = intervalo_min_s, relogio, dormir
        self._trava_envio = threading.Lock()
        self._ultimo_envio = -1e9

    # ── estado ──
    def estado(self) -> EstadoConexao:
        f = self.sessao.foto()
        sit = f.situacao
        msgs = {
            Situacao.PARADO: f.texto or "O WhatsApp ainda não foi iniciado neste computador.",
            Situacao.INICIANDO: f.texto or "Abrindo o WhatsApp Web… aguarde.",
            Situacao.AGUARDANDO_QR: "Aguardando a leitura do QR Code no celular.",
            Situacao.CONECTADO: "Conectado.",
            Situacao.DESCONECTADO: f"Desconectado: {f.texto}" if f.texto else "Desconectado.",
        }
        return EstadoConexao(sit == Situacao.CONECTADO, msgs.get(sit, "Estado desconhecido."), situacao=sit)

    def qr_png(self) -> Optional[bytes]:
        return self.sessao.qr_png()

    # ── administração ──
    def iniciar_sessao(self) -> ResultadoAcao:
        return self.sessao.iniciar()

    def sair(self) -> ResultadoAcao:
        """Fecha o navegador. NÃO desvincula o aparelho: o perfil continua logado para a próxima vez."""
        self.sessao.parar()
        return ResultadoAcao(True, "WhatsApp fechado neste computador (o vínculo com o celular continua).")

    # ── envio ──
    @staticmethod
    def _exigir_autorizacao() -> None:
        if not envio_real_autorizado():
            raise EnvioNaoAutorizadoError(
                "Envio real bloqueado: defina WHATSAPP_ENVIO_REAL=1 para autorizar. Nenhuma mensagem foi enviada.")

    def _preparar(self) -> Optional[str]:
        """None se pode enviar; senão, o motivo."""
        if self.sessao.foto().situacao != Situacao.CONECTADO:
            return "O WhatsApp não está conectado. Abra a tela WhatsApp e inicie a conexão."
        return None

    def _esperar_intervalo(self) -> None:
        falta = self._intervalo - (self._relogio() - self._ultimo_envio)
        if falta > 0:
            self._dormir(falta)

    def _traduzir_falha(self) -> str:
        erro = self.sessao.ultimo_erro()
        if "Could not open chat" in erro:
            return "O WhatsApp não abriu a conversa: número sem WhatsApp ou inválido."
        return ("Não consegui confirmar o envio. A mensagem pode ou não ter saído: confira no WhatsApp antes de "
                "reenviar." + (f" ({erro})" if erro else ""))

    def enviar(self, numero: str, texto: str) -> ResultadoEnvio:
        self._exigir_autorizacao()
        alvo = normalizar_numero(numero)
        if not str(texto or "").strip():
            return ResultadoEnvio(False, False, erro="Mensagem vazia.")
        with self._trava_envio:
            motivo = self._preparar()
            if motivo:
                return ResultadoEnvio(False, False, erro=motivo)
            self._esperar_intervalo()
            self.sessao.limpar_erro()
            try:
                # open_via_url=True: sempre por NÚMERO. Sem isso a biblioteca procura o contato pelo nome.
                ok = self.sessao.executar(lambda c: c.send_message(alvo, texto, open_via_url=True))
            except Exception as exc:
                return ResultadoEnvio(False, False, erro=f"Falha ao enviar ({type(exc).__name__}).")
            finally:
                self._ultimo_envio = self._relogio()
        return ResultadoEnvio(True, False) if ok else ResultadoEnvio(False, False, erro=self._traduzir_falha())

    def enviar_midia(self, numero: str, tipo: str, dados: bytes, *, nome_arquivo: Optional[str] = None,
                     mimetype: Optional[str] = None, legenda: Optional[str] = None, voz: bool = False) -> ResultadoEnvio:
        """Envia SEMPRE como documento (é o que a biblioteca faz). Sem legenda. A biblioteca não confirma
        o envio de arquivos: o resultado só diz que o fluxo terminou sem erro."""
        self._exigir_autorizacao()
        alvo = normalizar_numero(numero)
        if not dados:
            return ResultadoEnvio(False, False, erro="Arquivo vazio.")
        if legenda:
            return ResultadoEnvio(False, False, erro="O provedor whatsplay não envia legenda. Envie o texto à parte.")
        nome = re.sub(r"[^\w.\- ]", "_", Path(nome_arquivo or "arquivo").name)[:80] or "arquivo"
        with self._trava_envio:
            motivo = self._preparar()
            if motivo:
                return ResultadoEnvio(False, False, erro=motivo)
            self._esperar_intervalo()
            self.sessao.limpar_erro()
            with tempfile.TemporaryDirectory(prefix="autosere_wa_") as pasta:
                caminho = Path(pasta) / nome
                caminho.write_bytes(dados)
                try:
                    ok = self.sessao.executar(lambda c: c.send_file(alvo, str(caminho), open_via_url=True))
                except Exception as exc:
                    return ResultadoEnvio(False, False, erro=f"Falha ao enviar ({type(exc).__name__}).")
                finally:
                    self._ultimo_envio = self._relogio()
        return ResultadoEnvio(True, False) if ok else ResultadoEnvio(False, False, erro=self._traduzir_falha())


def id_do_qr(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()[:12]


def criar_provedor_whatsplay(pasta_perfil: Path, headless: bool = False,
                             preparar_contexto: Optional[PrepararContexto] = None) -> ProvedorWhatsplay:
    sessao = SessaoWhatsplay(lambda: fabricar_cliente(pasta_perfil, headless, preparar_contexto))
    atexit.register(sessao.parar, 5)       # não deixa o Chromium órfão segurando o perfil
    return ProvedorWhatsplay(sessao)

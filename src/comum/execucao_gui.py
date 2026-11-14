"""
execucao_gui.py — Infraestrutura para expor modos assíncronos como funções
síncronas thread-safe, com progresso repassado via callback.
=============================================================================
Módulo comum criado a pedido do usuário em 30/08/2026, em preparação para
uma futura interface gráfica ("modo SERE") onde cada modo de sere_2026.py
(--limpeza, --documento, --analisa, --espec, --aluno, --transferidos,
--validar) vira um botão. Este módulo NÃO faz parte de nenhuma GUI — a GUI
em si ainda não existe e é etapa futura (confirmado com o usuário). O que
este módulo fornece é a ponte: como chamar uma função `async def modo_x(...)`
de dentro de código síncrono (que é o que qualquer framework de GUI —
Tkinter, PyQt, etc. — espera de um handler de botão), sem travar a interface
enquanto o Playwright roda, e sem que cada modo precise ser reescrito.

DECISÕES DE ARQUITETURA (usuário, 30/08/2026):
1. Threading: cada função `executar_*` sobe sua PRÓPRIA thread com um event
   loop asyncio interno e retorna IMEDIATAMENTE — quem chama (a futura GUI)
   nunca bloqueia esperando o modo terminar. O progresso chega via callback
   enquanto o modo roda em background; a conclusão (sucesso/erro) também é
   entregue via callback, não via valor de retorno (que já foi usado pelo
   identificador da execução).
2. Formato do callback: `callback(mensagem: str)` — uma função que recebe
   cada linha de progresso como texto simples. Esta é a escolha mais simples
   e universal (o usuário ainda não decidiu o design da GUI em si); serve
   igualmente bem para um handler que escreve num QTextEdit/Listbox, ou para
   uma função que apenas enfileira (`queue.put`) para consumo em outra
   thread. Se o formato precisar mudar quando a GUI for desenhada de fato
   (ex.: progresso estruturado com percentual), a mudança fica isolada
   neste módulo — os modos em sere_2026.py não precisam ser tocados de novo.
3. API por modo: cada modo mantém sua própria função `executar_<modo>` com
   os parâmetros específicos daquele modo (não uma função genérica
   despachando por nome) — ver src/automacao/executar_*.py.
4. Cada função `executar_<modo>` vive em seu PRÓPRIO arquivo dedicado
   (src/automacao/executar_limpeza.py, executar_documento.py, etc.), não
   agrupadas num único arquivo "GUI" — o usuário sinalizou que outros
   scripts do ecossistema (ainda não portados) reaproveitam essas mesmas
   funções de modo, então cada wrapper precisa poder ser importado
   isoladamente sem carregar os demais.

COMO O PROGRESSO É CAPTURADO:
Os modos em sere_2026.py comunicam progresso de duas formas: `print()` para
o terminal, e `log.info/warning/error(...)` (o logger de sere_2026.py,
"sere.sere_2026") para o arquivo de log. Em vez de reescrever cada modo para
aceitar um parâmetro de callback (o que tocaria em toda a lógica de negócio
já portada e testada), este módulo INTERCEPTA as duas fontes durante a
execução do modo:
  - stdout é redirecionado para um objeto que grava a linha no arquivo de
    log real (comportamento preservado) E repassa a mesma linha ao callback.
  - Um logging.Handler temporário é adicionado ao logger "sere" (o logger
    raiz de todos os módulos sere.* — sere_2026, sere_api, sere_limpeza,
    etc., ver src/comum/logger.py) e removido ao final da execução, então
    mensagens de log de QUALQUER módulo usado pelo modo (não só
    sere_2026.py) também chegam ao callback.
Isso mantém sere_2026.py e os módulos em src/comum/ inalterados — a captura
é inteiramente external ao código que já existe e já foi testado.

Uso (dentro de um dos arquivos executar_*.py — ver exemplos lá):

    from src.comum.execucao_gui import ExecucaoEmBackground

    def executar_limpeza(turmas_selecionadas, turmas, modo_teste=False, callback=None):
        from src.automacao.sere_2026 import modo_limpeza
        execucao = ExecucaoEmBackground(callback=callback)
        execucao.iniciar(modo_limpeza(modo_teste, turmas_selecionadas, turmas))
        return execucao
"""

from __future__ import annotations

import asyncio
import contextvars
import ctypes
import logging
import sys
import threading
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Coroutine, Optional


CallbackProgresso = Callable[[str], None]


class StatusExecucao(str, Enum):
    EXECUTANDO = "executando"
    CONCLUIDO  = "concluido"
    ERRO       = "erro"
    CANCELADO  = "cancelado"


class CancelamentoSolicitado(BaseException):
    """
    Levantada DENTRO da thread da execução quando o usuário pede para cancelar.
    Herda de BaseException (e não de Exception) de propósito: os scripts têm
    muitos blocos `except Exception:` que a engoliriam e o cancelamento
    simplesmente não aconteceria.
    """


# Execução associada à thread atual — permite que um script (que não recebe a
# ExecucaoEmBackground como parâmetro) pergunte "me pediram para cancelar?"
# com `verificar_cancelamento()`, sem mudar a assinatura de nenhuma função.
_contexto = threading.local()


def cancelamento_solicitado() -> bool:
    """True se a execução em andamento nesta thread recebeu pedido de cancelamento."""
    execucao = getattr(_contexto, "execucao", None)
    return bool(execucao is not None and execucao.cancelamento_solicitado)


def verificar_cancelamento() -> None:
    """
    Ponto de checagem cooperativa: chame nos pontos seguros de um laço longo
    (ex.: a cada aluno). Se o usuário pediu para cancelar, levanta
    CancelamentoSolicitado — os `finally` do script rodam normalmente (ex.:
    fechar o navegador) e a execução termina com status CANCELADO.
    Fora de uma ExecucaoEmBackground (ex.: rodando o script no terminal) não faz nada.
    """
    if cancelamento_solicitado():
        raise CancelamentoSolicitado()


def _injetar_cancelamento(thread: Optional[threading.Thread]) -> bool:
    """
    Último recurso para código síncrono que não chama verificar_cancelamento():
    injeta CancelamentoSolicitado na thread. Só é entregue quando a thread volta
    a executar bytecode Python (não interrompe uma chamada bloqueante, como um
    time.sleep longo). Confiável para código síncrono puro; para código asyncio
    prefira o cancelamento cooperativo.
    """
    if thread is None or thread.ident is None or not thread.is_alive():
        return False
    afetadas = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread.ident), ctypes.py_object(CancelamentoSolicitado)
    )
    if afetadas > 1:  # nunca deveria acontecer; desfaz por segurança
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident), None)
        return False
    return afetadas == 1


class _CallbackLogHandler(logging.Handler):
    """
    Handler de logging temporário: repassa cada registro do logger "sere"
    (e de todos os seus filhos — sere.sere_2026, sere.sere_api, etc.) para
    o callback de progresso, formatado como uma linha simples de texto.
    Adicionado/removido pela própria ExecucaoEmBackground, nunca fica
    registrado permanentemente no logger.
    """

    def __init__(self, callback: CallbackProgresso):
        super().__init__(level=logging.INFO)
        self._callback = callback
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record))
        except Exception:
            # Um callback que falha (ex.: widget de GUI já destruído) nunca
            # deve derrubar a execução do modo em si.
            pass


class _StdoutParaCallback:
    """
    Substitui sys.stdout durante a execução de um modo: cada chamada a
    print() continua indo para o stdout real (terminal/log capturado pelo
    processo, comportamento preservado) E é repassada ao callback, linha a
    linha (print() emite a string seguida de '\\n' em escritas separadas —
    aqui só repassamos linhas não vazias para não spammar o callback com
    quebras de linha soltas).
    """

    def __init__(self, stdout_original, callback: CallbackProgresso):
        self._original = stdout_original
        self._callback = callback

    def write(self, texto: str) -> int:
        n = self._original.write(texto)
        linha = texto.rstrip("\n")
        if linha:
            try:
                self._callback(linha)
            except Exception:
                pass
        return n

    def flush(self) -> None:
        self._original.flush()


@dataclass
class ExecucaoEmBackground:
    """
    Sobe uma thread dedicada e roda uma coroutine OU uma função síncrona
    (um dos modos de sere_2026.py) nela, repassando todo print()/log gerado
    durante a execução para `callback`, se fornecido.

    Aceita tanto uma coroutine (a maioria dos modos: modo_limpeza,
    modo_documento, modo_espec, modo_aluno, modo_transferidos, modo_validar
    — todos `async def`) quanto uma chamada síncrona equivalente a
    `functools.partial(funcao_sincrona, *args, **kwargs)` — usado
    especificamente por modo_analisa, que é `def` (não `async def`) porque
    ele mesmo gerencia seu próprio `asyncio.run()` internamente (delega
    para `analisa_arquivos_sere.main()`, que é async). Rodar uma função que
    já chama `asyncio.run()` por dentro de outro `loop.run_until_complete()`
    levanta RuntimeError ("asyncio.run() cannot be called from a running
    event loop") — testado e confirmado. Por isso o dispatch abaixo detecta
    o tipo e escolhe o caminho certo automaticamente; quem usa esta classe
    (ver src/automacao/executar_analisa.py) não precisa se preocupar com
    essa diferença.

    Não bloqueia a thread chamadora: `.iniciar(...)` retorna assim que a
    thread de background é criada. O status e o resultado/erro final ficam
    disponíveis nos atributos desta instância (status, resultado, erro) e
    também podem ser observados via o próprio callback, que recebe uma
    linha final "[CONCLUÍDO]" ou "[ERRO] ..." quando a execução termina.

    Atributos públicos, seguros para leitura de qualquer thread após o
    término (ver `.aguardar()` ou o evento `.concluida`):
        status:    StatusExecucao atual
        resultado: valor de retorno da execução, se houver e se concluiu com sucesso
        erro:      exceção capturada, se a execução terminou com erro
    """

    callback: Optional[CallbackProgresso] = None
    status: StatusExecucao = field(default=StatusExecucao.EXECUTANDO)
    resultado: object = None
    erro: Optional[BaseException] = None

    # Segundos de espera antes de forçar o cancelamento de código síncrono que
    # não faz checagem cooperativa (ver cancelar()).
    PRAZO_CANCELAMENTO_FORCADO = 8.0

    def __post_init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self.concluida = threading.Event()
        self.cancelamento_solicitado = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tarefa: Optional[asyncio.Task] = None
        self._trava = threading.Lock()

    def iniciar(self, alvo) -> "ExecucaoEmBackground":
        """
        Inicia a execução em uma thread nova e retorna imediatamente (self,
        para permitir encadeamento como
        `execucao = ExecucaoEmBackground(callback=cb).iniciar(modo_x(...))`).

        `alvo` é uma coroutine (resultado de chamar uma função `async def`,
        ex. `modo_limpeza(...)`) ou uma chamada zero-argumentos síncrona
        (ex. `lambda: modo_analisa(argv)` ou `functools.partial(modo_analisa, argv)`).
        """
        # A thread roda dentro de uma CÓPIA do contexto de quem iniciou: é assim que comum/navegador.py sabe de qual
        # script veio a chamada (só leitura de variável de contexto; o resto da execução não muda).
        self._thread = threading.Thread(
            target=contextvars.copy_context().run,
            args=(self._executar_na_thread, alvo),
            daemon=True,
        )
        self._thread.start()
        return self

    def aguardar(self, timeout: Optional[float] = None) -> bool:
        """
        Bloqueia até a execução terminar (ou o timeout expirar). Útil para
        testes/scripts — a futura GUI normalmente NÃO vai chamar isto (ela
        observa o progresso via callback e não deve travar esperando).
        Retorna True se a execução terminou dentro do timeout.
        """
        return self.concluida.wait(timeout=timeout)

    def cancelar(self) -> bool:
        """
        Pede o cancelamento da execução. Retorna False se ela já terminou.
        Não bloqueia: o término (status CANCELADO) chega pelo callback e pelo
        atributo `status`, assim que a execução parar.

          - Coroutine: cancela a tarefa asyncio (os `finally` rodam).
          - Código síncrono: marca o pedido; scripts que chamam
            `verificar_cancelamento()` param no próximo ponto seguro. Se ainda
            estiver rodando após PRAZO_CANCELAMENTO_FORCADO segundos, injeta
            CancelamentoSolicitado na thread como último recurso.
        """
        if self.concluida.is_set():
            return False
        with self._trava:
            if self.cancelamento_solicitado:
                return True
            self.cancelamento_solicitado = True
            loop, tarefa = self._loop, self._tarefa

        if self.callback:
            try:
                self.callback("[CANCELANDO] Pedido de cancelamento recebido…")
            except Exception:
                pass

        if loop is not None and tarefa is not None and not loop.is_closed():
            loop.call_soon_threadsafe(tarefa.cancel)
        elif loop is None:
            def _forcar() -> None:
                if not self.concluida.is_set():
                    _injetar_cancelamento(self._thread)
            temporizador = threading.Timer(self.PRAZO_CANCELAMENTO_FORCADO, _forcar)
            temporizador.daemon = True
            temporizador.start()
        return True

    def _executar_na_thread(self, alvo) -> None:
        handler_log: Optional[_CallbackLogHandler] = None
        stdout_original = sys.stdout
        logger_sere = logging.getLogger("sere")

        if self.callback:
            handler_log = _CallbackLogHandler(self.callback)
            logger_sere.addHandler(handler_log)
            sys.stdout = _StdoutParaCallback(stdout_original, self.callback)

        _contexto.execucao = self
        try:
            if asyncio.iscoroutine(alvo):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    tarefa = loop.create_task(alvo)
                    with self._trava:
                        self._loop, self._tarefa = loop, tarefa
                        pedido_antes = self.cancelamento_solicitado
                    if pedido_antes:  # cancelar() chegou antes da tarefa existir
                        tarefa.cancel()
                    self.resultado = loop.run_until_complete(tarefa)
                finally:
                    loop.close()
            else:
                # Chamada síncrona (ex.: modo_analisa, que já gerencia seu
                # próprio asyncio.run() internamente) — roda direto na
                # thread, sem event loop desta camada.
                verificar_cancelamento()
                self.resultado = alvo()

            self.status = StatusExecucao.CONCLUIDO
            if self.callback:
                self.callback("[CONCLUÍDO]")
        except (asyncio.CancelledError, CancelamentoSolicitado):
            self.status = StatusExecucao.CANCELADO
            if self.callback:
                self.callback("[CANCELADO]")
        except BaseException as exc:  # noqa: BLE001 — precisa capturar tudo para reportar à GUI
            self.erro = exc
            self.status = StatusExecucao.ERRO
            if self.callback:
                detalhe = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                self.callback(f"[ERRO] {detalhe}")
        finally:
            if handler_log:
                logger_sere.removeHandler(handler_log)
            sys.stdout = stdout_original
            _contexto.execucao = None
            self.concluida.set()

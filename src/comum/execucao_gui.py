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

    def __post_init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self.concluida = threading.Event()

    def iniciar(self, alvo) -> "ExecucaoEmBackground":
        """
        Inicia a execução em uma thread nova e retorna imediatamente (self,
        para permitir encadeamento como
        `execucao = ExecucaoEmBackground(callback=cb).iniciar(modo_x(...))`).

        `alvo` é uma coroutine (resultado de chamar uma função `async def`,
        ex. `modo_limpeza(...)`) ou uma chamada zero-argumentos síncrona
        (ex. `lambda: modo_analisa(argv)` ou `functools.partial(modo_analisa, argv)`).
        """
        self._thread = threading.Thread(
            target=self._executar_na_thread,
            args=(alvo,),
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

    def _executar_na_thread(self, alvo) -> None:
        handler_log: Optional[_CallbackLogHandler] = None
        stdout_original = sys.stdout
        logger_sere = logging.getLogger("sere")

        if self.callback:
            handler_log = _CallbackLogHandler(self.callback)
            logger_sere.addHandler(handler_log)
            sys.stdout = _StdoutParaCallback(stdout_original, self.callback)

        try:
            if asyncio.iscoroutine(alvo):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    self.resultado = loop.run_until_complete(alvo)
                finally:
                    loop.close()
            else:
                # Chamada síncrona (ex.: modo_analisa, que já gerencia seu
                # próprio asyncio.run() internamente) — roda direto na
                # thread, sem event loop desta camada.
                self.resultado = alvo()

            self.status = StatusExecucao.CONCLUIDO
            if self.callback:
                self.callback("[CONCLUÍDO]")
        except asyncio.CancelledError:
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
            self.concluida.set()

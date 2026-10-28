"""
executar_analisa.py — Wrapper de modo_analisa para uso por interface gráfica
=============================================================================
Ver docstring de executar_limpeza.py e src/comum/execucao_gui.py para o
contexto completo desta família de wrappers.

CASO ESPECIAL: modo_analisa (diferente de todos os outros modos) é uma
função SÍNCRONA (`def`, não `async def`) — ela mesma chama `asyncio.run()`
internamente para executar `analisa_arquivos_sere.main()`. Por isso este
wrapper passa a função para ExecucaoEmBackground.iniciar() SEM chamá-la
(nem usar `await`) — é `ExecucaoEmBackground` quem detecta que não é uma
coroutine e a executa como chamada síncrona direta na thread de background,
sem tentar rodar um segundo event loop por cima do que modo_analisa já
gerencia sozinho (isso quebraria com RuntimeError — ver o docstring de
ExecucaoEmBackground para o teste que confirmou isso).

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_analisa import executar_analisa

    def ao_clicar_botao_analisar():
        execucao = executar_analisa(
            args_extras=["--turma"],
            callback=lambda linha: self.log_widget.append(linha),
        )
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_analisa(
    args_extras: Optional[list[str]] = None,
    callback: Optional[CallbackProgresso] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --analisa (coleta documentos de todos os alunos via API
    do SERE e gera relatório Excel/JSON, reaproveitando
    src.relatorios.analisa_arquivos_sere) em background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso é repassado a `callback`, se fornecido.

    `args_extras`: lista de argumentos repassados para
    analisa_arquivos_sere (ex.: ["--turma"]) — ver
    src.automacao.sere_2026.modo_analisa e src.relatorios.analisa_arquivos_sere
    para as opções aceitas. Vazio por padrão.
    """
    from src.automacao.sere_2026 import modo_analisa

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(lambda: modo_analisa(args_extras or []))
    return execucao

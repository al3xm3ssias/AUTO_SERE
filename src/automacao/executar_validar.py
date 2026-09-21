"""
executar_validar.py — Wrapper de modo_validar para uso por interface gráfica
=============================================================================
Ver docstring de executar_limpeza.py e src/comum/execucao_gui.py para o
contexto completo desta família de wrappers.

NOTA SOBRE EncerramentoForcado: modo_validar pode levantar
src.automacao.sere_2026.EncerramentoForcado quando o SERE parece ter
travado (muitas falhas de recarga consecutivas — ver
MAX_RECARGAS_CONSECUTIVAS_FALHA). Isso não precisa de tratamento especial
aqui: ExecucaoEmBackground já captura QUALQUER exceção (inclusive esta),
marca `execucao.status` como ERRO, guarda a exceção em `execucao.erro`, e
envia uma linha "[ERRO] ..." ao callback — uma futura GUI só precisa checar
`execucao.status` (ou reagir à linha "[ERRO]") para saber que a validação
foi abortada, sem precisar importar ou tratar EncerramentoForcado
especificamente.

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_validar import executar_validar

    def ao_clicar_botao_validar():
        execucao = executar_validar(
            turmas_selecionadas=["3º ANO A"], turmas=turmas_carregadas,
            callback=lambda linha: self.log_widget.append(linha),
        )
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_validar(
    turmas_selecionadas: list[str],
    turmas: dict,
    modo_teste: bool = False,
    delay_segundos: Optional[int] = None,
    somente_transferidos: bool = False,
    callback: Optional[CallbackProgresso] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --validar (valida — clica em ✔ — todos os documentos
    pendentes de todos os alunos das turmas selecionadas) em background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso é repassado a `callback`, se fornecido. Se o
    SERE parecer ter travado, a execução termina com
    `execucao.status == StatusExecucao.ERRO` e
    `execucao.erro` sendo um EncerramentoForcado — ver nota acima.

    Parâmetros: ver src.automacao.sere_2026.modo_validar para o
    significado exato de cada um. `delay_segundos`, quando None, usa o
    padrão de sere_2026 (DELAY_VALIDACAO_PADRAO).
    """
    from src.automacao.sere_2026 import modo_validar, DELAY_VALIDACAO_PADRAO

    delay = delay_segundos if delay_segundos is not None else DELAY_VALIDACAO_PADRAO

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(
        modo_validar(
            modo_teste, turmas_selecionadas, turmas,
            delay_segundos=delay, somente_transferidos=somente_transferidos,
        )
    )
    return execucao

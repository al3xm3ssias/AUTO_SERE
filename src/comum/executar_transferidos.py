"""
executar_transferidos.py — Wrapper de modo_transferidos para uso por interface gráfica
=============================================================================
Ver docstring de executar_limpeza.py e src/comum/execucao_gui.py para o
contexto completo desta família de wrappers.

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_transferidos import executar_transferidos

    def ao_clicar_botao_transferidos():
        execucao = executar_transferidos(
            callback=lambda linha: self.log_widget.append(linha),
        )
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_transferidos(
    modo_teste: bool = False,
    callback: Optional[CallbackProgresso] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --transferidos (para cada aluno em transferidos.json com
    documento assinado pelo diretor após a data de corte, faz upload do
    PDF correspondente — Guia, Histórico ou Parecer — no slot certo do
    SERE) em background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso é repassado a `callback`, se fornecido.

    Pré-requisitos: a pasta de digitalização precisa estar configurada
    (ver src.comum.configuracao.pasta_digitalizacao), com as subpastas
    TRANSFERENCIAS/GUIA DE TRANSFERENCIA, TRANSFERENCIAS/HISTÓRICOS e
    TRANSFERENCIAS/PARECERES; e dados/<ano>/transferidos.json precisa
    existir (ver src.automacao.sere_2026.PATH_TRANSFERIDOS).

    Parâmetros: ver src.automacao.sere_2026.modo_transferidos.
    """
    from src.automacao.sere_2026 import modo_transferidos

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(modo_transferidos(modo_teste))
    return execucao

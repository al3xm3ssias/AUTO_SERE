"""
executar_aluno.py — Wrapper de modo_aluno para uso por interface gráfica
=============================================================================
Ver docstring de executar_limpeza.py e src/comum/execucao_gui.py para o
contexto completo desta família de wrappers.

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_aluno import executar_aluno

    def ao_clicar_botao_upload_alunos():
        execucao = executar_aluno(
            callback=lambda linha: self.log_widget.append(linha),
        )
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_aluno(
    modo_teste: bool = False,
    modo_erros: bool = False,
    modo_faltando: bool = False,
    callback: Optional[CallbackProgresso] = None,
    cgms: Optional[list] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --aluno (processa apenas os CGMs configurados via
    src.comum.configuracao.cgm_upload — não mais um array editado
    manualmente no script, ver decisão do usuário em 29/08/2026) em
    background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso é repassado a `callback`, se fornecido.

    Pré-requisitos: a pasta de digitalização precisa estar configurada
    (ver src.comum.configuracao.pasta_digitalizacao), e a lista de CGMs
    precisa ter sido definida (ver
    src.comum.configuracao.definir_cgm_upload) — sem isso, modo_aluno
    avisa via callback/print e encerra sem processar nada.

    `cgms`: lista de CGMs a processar (a tela de Automações e a linha de comando passam aqui);
    se omitida, usa a lista configurada em src.comum.configuracao.cgm_upload.

    Parâmetros: ver src.automacao.sere_2026.modo_aluno para o significado
    exato de cada um (modo_erros reprocessa a partir do último arquivo de
    erros salvo; modo_faltando filtra só quem ainda tem slot pendente).
    """
    from src.automacao.sere_2026 import modo_aluno

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(modo_aluno(modo_teste, modo_erros, modo_faltando, cgms=cgms))
    return execucao

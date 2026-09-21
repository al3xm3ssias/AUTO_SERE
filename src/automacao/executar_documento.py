"""
executar_documento.py — Wrapper de modo_documento para uso por interface gráfica
=============================================================================
Ver docstring de executar_limpeza.py e src/comum/execucao_gui.py para o
contexto completo desta família de wrappers (preparação para o futuro
"modo SERE" com interface gráfica, cada modo em seu próprio arquivo).

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_documento import executar_documento

    def ao_clicar_botao_remover_tipo():
        execucao = executar_documento(
            idtipo="8", nome_slot="RG do aluno",
            turmas_selecionadas=["3º ANO A"], turmas=turmas_carregadas,
            callback=lambda linha: self.log_widget.append(linha),
        )
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_documento(
    idtipo: str,
    nome_slot: str,
    turmas_selecionadas: list[str],
    turmas: dict,
    modo_teste: bool = False,
    callback: Optional[CallbackProgresso] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --documento (remove apenas o tipo de documento
    especificado de todos os alunos das turmas selecionadas) em background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso é repassado a `callback`, se fornecido.

    Parâmetros: ver src.automacao.sere_2026.modo_documento para o
    significado exato de cada um. `idtipo` e `nome_slot` normalmente vêm
    de src.automacao.sere_2026.menu_selecionar_tipo_documento() (ou, numa
    GUI, de um combobox populado a partir de
    src.comum.sere_normalizacao.IDTIPO_PARA_SLOT).
    """
    from src.automacao.sere_2026 import modo_documento

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(
        modo_documento(idtipo, nome_slot, modo_teste, turmas_selecionadas, turmas)
    )
    return execucao

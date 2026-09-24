"""
executar_espec.py — Wrapper de modo_espec para uso por interface gráfica
=============================================================================
Ver docstring de executar_limpeza.py e src/comum/execucao_gui.py para o
contexto completo desta família de wrappers.

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_espec import executar_espec

    def ao_clicar_botao_upload_especifico():
        execucao = executar_espec(
            idtipo_alvo="8", nome_slot="RG do aluno",
            turmas_selecionadas=["3º ANO A"], turmas=turmas_carregadas,
            callback=lambda linha: self.log_widget.append(linha),
        )
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_espec(
    idtipo_alvo: str,
    nome_slot: str,
    turmas_selecionadas: list[str],
    turmas: dict,
    modo_teste: bool = False,
    callback: Optional[CallbackProgresso] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --espec (upload de um tipo específico de documento para
    todos os alunos das turmas selecionadas, buscando o arquivo na pasta de
    digitalização configurada) em background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso é repassado a `callback`, se fornecido.

    Pré-requisito: a pasta de digitalização precisa estar configurada (ver
    src.comum.configuracao.pasta_digitalizacao) — se não estiver,
    modo_espec avisa via callback/print e retorna sem tentar fazer upload.

    Parâmetros: ver src.automacao.sere_2026.modo_espec para o significado
    exato de cada um.
    """
    from src.automacao.sere_2026 import modo_espec

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(
        modo_espec(idtipo_alvo, nome_slot, modo_teste, turmas_selecionadas, turmas)
    )
    return execucao

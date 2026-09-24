"""
executar_limpeza.py — Wrapper de modo_limpeza para uso por interface gráfica
=============================================================================
Criado a pedido do usuário em 30/08/2026, em preparação para o futuro "modo
SERE" (interface gráfica onde cada modo de sere_2026.py vira um botão). A
interface em si ainda não existe — este arquivo só prepara a função para
ser chamada por qualquer GUI futura (ou por outro script que precise do
mesmo modo, ver docstring de src/comum/execucao_gui.py sobre por que cada
modo tem seu próprio arquivo dedicado em vez de um único arquivo "GUI").

Uso típico (de dentro de um handler de botão, futuro):

    from src.automacao.executar_limpeza import executar_limpeza

    def ao_clicar_botao_limpeza():
        execucao = executar_limpeza(
            turmas_selecionadas=["3º ANO A", "3º ANO B"],
            turmas=turmas_carregadas,
            modo_teste=False,
            callback=lambda linha: self.log_widget.append(linha),
        )
        # execucao.status, execucao.resultado, execucao.erro ficam
        # disponíveis a qualquer momento; a chamada acima não bloqueia.
"""

from __future__ import annotations

from typing import Optional

from src.comum.execucao_gui import CallbackProgresso, ExecucaoEmBackground


def executar_limpeza(
    turmas_selecionadas: list[str],
    turmas: dict,
    modo_teste: bool = False,
    callback: Optional[CallbackProgresso] = None,
) -> ExecucaoEmBackground:
    """
    Dispara o modo --limpeza (remove TODOS os arquivos de todos os alunos
    das turmas selecionadas, exceto slots protegidos) em background.

    Retorna imediatamente um objeto ExecucaoEmBackground — não espera o
    modo terminar. Progresso (print/log de sere_2026.py e dos módulos que
    ele usa) é repassado a `callback`, se fornecido, linha a linha, junto
    com uma linha final "[CONCLUÍDO]" ou "[ERRO] ...".

    Parâmetros: ver src.automacao.sere_2026.modo_limpeza para o
    significado exato de cada um (idêntico — este wrapper não muda a
    lógica de negócio, só a forma de chamada).
    """
    from src.automacao.sere_2026 import modo_limpeza

    execucao = ExecucaoEmBackground(callback=callback)
    execucao.iniciar(modo_limpeza(modo_teste, turmas_selecionadas, turmas))
    return execucao

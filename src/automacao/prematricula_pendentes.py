"""
prematricula_pendentes.py — Etapa 4: Verificação de Pendentes
=============================================================================
Portado de AUTO_SERE/pre_matricula.py (_situacao_e_presuntiva,
listar_pendentes_para_verificar, etapa_verificar_pendentes) para
src/automacao/prematricula_pendentes.py.

Contexto: quando um aluno some da lista de intenção de vaga (Etapa 1, ver
src.automacao.prematricula_coleta), mesclar_turmas_intencao() não sabe o
motivo real e grava uma situação PRESUMIDA ("Cancelado" /
"CANCELADO VIA SISTEMA/RESPONSAVEL") só para não deixar o campo em branco.
Esta etapa fecha essa lacuna: para cada aluno nessa condição, re-consulta o
CPF dele (mesma lógica da Etapa 2) e, se a consulta trouxer uma situação
real (Matriculado, Cancelado com motivo verdadeiro, ou ainda Aguardando em
outra escola/opção), substitui a presunção pelo dado confirmado — tanto em
cadastros[cpf] quanto no próprio registro em turmas_intencao.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. consultar_cpf: REMOVIDA daqui — reaproveita
   src.comum.prematricula_api.consultar_cpf, já portada.

2. carregar_pre_matricula/salvar_pre_matricula: REMOVIDAS daqui —
   reaproveitam as de src.automacao.prematricula_coleta, mesmo arquivo,
   mesma lógica.

3. etapa_verificar_pendentes() RENOMEADA para verificar_pendentes(page,
   dados_pre_matricula=None, analise_codigo=False) — mesma lógica e mesma
   assinatura de entrada (dados_pre_matricula é opcional: se não
   informado, recarrega do disco — comportamento idêntico ao original).

4. NOVA: executar_prematricula_pendentes(analise_codigo=False) — ponto de
   entrada completo (abre navegador, login, verifica pendentes, fecha
   navegador). Pronta para um futuro botão de GUI (decisão do usuário,
   03/09/2026): sem argparse, sem input().

Toda a lógica de negócio (critério de "situação ainda presuntiva",
seleção de pendentes com CPF válido, extração da situação/motivo real a
partir de escolas_escolhidas.opcoes, e o tratamento de "consulta
respondeu mas sem situação clara" como sem_resposta) é idêntica ao
original — nenhuma regra foi alterada.

Uso:
    import asyncio
    from src.automacao.prematricula_pendentes import executar_prematricula_pendentes

    asyncio.run(executar_prematricula_pendentes())
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import async_playwright

from src.automacao.prematricula_coleta import (
    PREMATRICULA_FILE,
    carregar_pre_matricula,
    salvar_pre_matricula,
)
from src.comum.prematricula_api import consultar_cpf, fazer_login


# ==========================================================
# ETAPA 4 - VERIFICAÇÃO DE PENDENTES (matriculados/cancelados)
# ==========================================================

def _situacao_e_presuntiva(aluno: dict) -> bool:
    """
    Indica se a situação atualmente registrada em turmas_intencao para um
    aluno é a presunção automática gravada por mesclar_turmas_intencao()
    (motivo_cancelamento == "CANCELADO VIA SISTEMA/RESPONSAVEL"), e não uma
    situação real capturada por consulta de CPF.

    Um aluno sem "situacao" nenhuma também conta como pendente de
    verificação (nunca foi consultado depois de sumir da lista).
    """
    if not aluno.get("situacao"):
        return True
    return aluno.get("motivo_cancelamento") == "CANCELADO VIA SISTEMA/RESPONSAVEL"


def listar_pendentes_para_verificar(turmas_intencao: dict) -> list[tuple[str, str, dict]]:
    """
    Percorre turmas_intencao e retorna a lista de alunos que sumiram da
    última coleta (presente_na_ultima_coleta == False) e cuja situação
    registrada ainda é a presunção automática (ou está ausente) — ou seja,
    alunos que ficaram "pendentes" (aguardando) e cujo destino real
    (matriculado ou cancelado) ainda não foi confirmado por consulta de
    CPF.

    Retorna uma lista de tuplas (turma, chave, aluno) para permitir
    localizar e atualizar o registro exato depois da consulta.
    """
    pendentes = []
    for turma, alunos in (turmas_intencao or {}).items():
        for aluno in alunos:
            if aluno.get("presente_na_ultima_coleta") is False and _situacao_e_presuntiva(aluno):
                cpf = (aluno.get("cpf") or "").strip()
                if not cpf:
                    # Sem CPF não há como consultar o cadastro; permanece
                    # com a situação presumida.
                    continue
                chave = cpf
                pendentes.append((turma, chave, aluno))
    return pendentes


async def verificar_pendentes(
    page,
    dados_pre_matricula: Optional[dict] = None,
    analise_codigo: bool = False,
) -> dict:
    """
    Executa a Etapa 4: verifica os cadastros que estavam marcados como
    "pendentes" (aguardando, e depois ausentes da coleta mais recente) e
    descobre se foram efetivamente matriculados ou cancelados.

    `dados_pre_matricula`: se informado, usa esse dict diretamente
    (mutado in-place e salvo ao final); se None, recarrega
    pre_matricula.json do disco — mesmo comportamento do original.

    Assume que `page` já está autenticada no portal de pré-matrícula.

    Retorna um resumo (dict) com quantos pendentes foram encontrados,
    quantos foram confirmados e a lista de CPFs que continuam sem resposta
    do site (permanecem com a situação presumida até a próxima execução).
    """
    print("\n" + "=" * 60)
    print("ETAPA 4/4 - VERIFICAÇÃO DE PENDENTES (MATRICULADOS/CANCELADOS)")
    print("=" * 60)

    pre_matricula = dados_pre_matricula or carregar_pre_matricula()
    turmas_intencao = pre_matricula.get("turmas_intencao", {})

    pendentes = listar_pendentes_para_verificar(turmas_intencao)
    print(f"Total de pendentes a verificar: {len(pendentes)}")

    if not pendentes:
        print("Nenhum pendente para verificar. Nada a fazer.")
        return {"total_pendentes": 0, "confirmados": 0, "sem_resposta": []}

    confirmados = 0
    sem_resposta: list[str] = []
    cadastros = pre_matricula.setdefault("cadastros", {})

    for turma, cpf, aluno in pendentes:
        aluno_dados = await consultar_cpf(page, cpf, etapa="verificar_pendentes", analise_codigo=analise_codigo)

        if aluno_dados is None:
            sem_resposta.append(cpf)
            continue

        # Atualiza o cadastro completo com o dado mais recente.
        cadastros[cpf] = aluno_dados

        # Extrai a situação real (Matriculado/Cancelado/Aguardando) das
        # escolas escolhidas para refletir no próprio registro de
        # turmas_intencao, substituindo a presunção automática.
        opcoes = (aluno_dados.get("escolas_escolhidas") or {}).get("opcoes", [])
        situacao_real = next((op.get("situacao") for op in opcoes if op.get("situacao")), "")

        if situacao_real:
            aluno["situacao"] = situacao_real
            motivo_real = next(
                (op.get("motivo_cancelamento") for op in opcoes if op.get("motivo_cancelamento")),
                "",
            )
            observacao_real = next(
                (op.get("observacao") for op in opcoes if op.get("observacao")),
                "",
            )
            aluno["motivo_cancelamento"] = motivo_real
            aluno["observacao"] = observacao_real
            confirmados += 1
            print(f"✅ CPF {cpf} ({turma}): situação confirmada -> {situacao_real}")
        else:
            # Consulta respondeu, mas não trouxe nenhuma situação
            # reconhecível nas opções de escola; mantém a presunção.
            sem_resposta.append(cpf)
            print(f"⚠️ CPF {cpf} ({turma}): consulta não retornou situação clara.")

    salvar_pre_matricula(pre_matricula)

    print(f"\n✅ Etapa 4 concluída.")
    print(f"   Pendentes verificados: {len(pendentes)}")
    print(f"   Confirmados (matriculado/cancelado real): {confirmados}")
    print(f"   Sem resposta clara (mantidos como presumidos): {len(sem_resposta)}")
    print(f"   Arquivo salvo em: {PREMATRICULA_FILE}")

    return {
        "total_pendentes": len(pendentes),
        "confirmados": confirmados,
        "sem_resposta": sem_resposta,
    }


# ==========================================================
# ENTRY POINT (pronto para uma futura GUI)
# ==========================================================

async def executar_prematricula_pendentes(analise_codigo: bool = False) -> dict:
    """
    Ponto de entrada completo: abre o navegador, faz login no portal de
    pré-matrícula, executa a Etapa 4 (verificação de pendentes, lendo
    pre_matricula.json do disco) e fecha o navegador.

    Pronta para ser chamada por um futuro botão de GUI (decisão do
    usuário, 03/09/2026, mesmo padrão de src.automacao.sere_2026): sem
    argparse, sem input().

    Retorna o resumo (dict com total_pendentes/confirmados/sem_resposta),
    ou {"total_pendentes": 0, "confirmados": 0, "sem_resposta": []} se o
    login falhar.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        if not await fazer_login(page, analise_codigo=analise_codigo):
            print("❌ Falha no login. Encerrando.")
            await browser.close()
            return {"total_pendentes": 0, "confirmados": 0, "sem_resposta": []}

        resultado = await verificar_pendentes(page, analise_codigo=analise_codigo)

        await browser.close()
        return resultado


if __name__ == "__main__":
    asyncio.run(executar_prematricula_pendentes())

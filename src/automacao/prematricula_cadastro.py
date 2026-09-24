"""
prematricula_cadastro.py — Etapa 2: Consulta de Cadastro por CPF
=============================================================================
Portado de AUTO_SERE/pre_matricula.py (etapa_cadastro) para
src/automacao/prematricula_cadastro.py.

Para cada CPF encontrado na coleta de intenções de vaga (Etapa 1, ver
src.automacao.prematricula_coleta), consulta o cadastro completo do aluno
no portal de pré-matrícula (nome, responsável, contatos, endereço,
critérios, escolas escolhidas com situação e motivo) e grava tudo em
pre_matricula.json, na seção "cadastros" (por CPF) — sem apagar cadastros
de execuções anteriores que não tenham sido re-consultados desta vez
(update, não substituição total do dicionário).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. consultar_cpf: REMOVIDA daqui — reaproveita
   src.comum.prematricula_api.consultar_cpf (já portada, usada também
   pelas etapas 4 e --completar_json).

2. Caminhos/persistência: carregar_pre_matricula/salvar_pre_matricula
   REMOVIDAS daqui — reaproveitam as de
   src.automacao.prematricula_coleta (mesmo arquivo pre_matricula.json,
   mesma lógica de leitura/escrita) — evita duas fontes de verdade sobre
   como ler/gravar o mesmo arquivo.

3. etapa_cadastro() RENOMEADA para consultar_cadastros(page,
   dados_intencoes) — mesma lógica e mesma assinatura de entrada (recebe
   o resultado bruto da Etapa 1, com a chave "turmas", não o
   pre_matricula.json já persistido — confirmado no original: main()
   passa direto o retorno de etapa_coleta() para etapa_cadastro()).

4. NOVA: executar_prematricula_cadastro(dados_intencoes=None,
   analise_codigo=False) — ponto de entrada completo. Se
   `dados_intencoes` não for informado, roda a Etapa 1 primeiro (via
   src.automacao.prematricula_coleta.coletar_intencoes_vaga) dentro da
   mesma sessão logada, e usa o resultado dela — permite chamar só esta
   etapa isoladamente (ex.: reprocessar cadastros sem coletar de novo,
   passando `dados_intencoes` explicitamente) ou como parte do fluxo
   completo. Pronta para um futuro botão de GUI (decisão do usuário,
   03/09/2026): sem argparse, sem input().

Toda a lógica de negócio (extrair a lista de CPFs a partir de
dados_intencoes["turmas"], consultar um por um, agregar em "cadastros")
é idêntica ao original — nenhuma regra foi alterada.

Uso:
    import asyncio
    from src.automacao.prematricula_cadastro import executar_prematricula_cadastro

    asyncio.run(executar_prematricula_cadastro())
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import async_playwright

from src.automacao.prematricula_coleta import (
    PREMATRICULA_FILE,
    carregar_pre_matricula,
    coletar_intencoes_vaga,
    salvar_pre_matricula,
)
from src.comum.prematricula_api import consultar_cpf, fazer_login


# ==========================================================
# ETAPA 2 - CONSULTA DE CADASTRO POR CPF
# ==========================================================

async def consultar_cadastros(page, dados_intencoes: dict, analise_codigo: bool = False) -> dict:
    """
    Executa a Etapa 2: extrai todos os CPFs presentes em
    dados_intencoes["turmas"] (o resultado bruto da Etapa 1 — ver
    src.automacao.prematricula_coleta.coletar_intencoes_vaga), consulta o
    cadastro completo de cada um e grava o resultado em
    pre_matricula.json, seção "cadastros" (por CPF).

    Assume que `page` já está autenticada no portal de pré-matrícula —
    quem quer disparar o fluxo completo (login + etapa 1 + etapa 2) deve
    chamar executar_prematricula_cadastro() em vez desta função
    diretamente.

    Retorna o dict {cpf: dados_do_aluno} recém-consultado nesta execução
    (não o pre_matricula.json inteiro).
    """
    print("\n" + "=" * 60)
    print("ETAPA 2/4 - CONSULTA DE CADASTRO POR CPF")
    print("=" * 60)

    cpfs = []
    for turma, alunos in dados_intencoes.get("turmas", {}).items():
        for aluno in alunos:
            cpf = aluno.get("cpf")
            if cpf:
                cpfs.append(cpf)

    print(f"Total de CPFs encontrados: {len(cpfs)}")

    resultados: dict = {}

    for cpf in cpfs:
        aluno_dados = await consultar_cpf(page, cpf, etapa="cadastro", analise_codigo=analise_codigo)
        if aluno_dados is not None:
            resultados[cpf] = aluno_dados

    pre_matricula = carregar_pre_matricula()
    pre_matricula["cadastros"].update(resultados)
    salvar_pre_matricula(pre_matricula)

    print(f"\n✅ Etapa 2 concluída. Arquivo salvo em: {PREMATRICULA_FILE}")

    return resultados


# ==========================================================
# ENTRY POINT (pronto para uma futura GUI)
# ==========================================================

async def executar_prematricula_cadastro(
    dados_intencoes: Optional[dict] = None,
    analise_codigo: bool = False,
) -> dict:
    """
    Ponto de entrada completo: abre o navegador, faz login no portal de
    pré-matrícula e executa a Etapa 2 (consulta de cadastro por CPF).

    Se `dados_intencoes` não for informado, roda a Etapa 1 primeiro (na
    mesma sessão) e usa o resultado dela — equivalente ao fluxo original
    de main(), que sempre encadeava Etapa 1 → Etapa 2. Passar
    `dados_intencoes` explicitamente permite rodar só a Etapa 2 (ex.:
    reprocessar cadastros sem repetir a coleta de intenções).

    Pronta para ser chamada por um futuro botão de GUI (decisão do
    usuário, 03/09/2026, mesmo padrão de src.automacao.sere_2026): sem
    argparse, sem input().

    Retorna o dict {cpf: dados_do_aluno} recém-consultado, ou {} se o
    login falhar ou a Etapa 1 (quando necessária) falhar.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        if not await fazer_login(page, analise_codigo=analise_codigo):
            print("❌ Falha no login. Encerrando.")
            await browser.close()
            return {}

        if dados_intencoes is None:
            dados_intencoes = await coletar_intencoes_vaga(page, analise_codigo=analise_codigo)
            if dados_intencoes is None:
                print("❌ Etapa 1 falhou. Abortando Etapa 2.")
                await browser.close()
                return {}

        resultado = await consultar_cadastros(page, dados_intencoes, analise_codigo=analise_codigo)

        await browser.close()
        return resultado


if __name__ == "__main__":
    asyncio.run(executar_prematricula_cadastro())

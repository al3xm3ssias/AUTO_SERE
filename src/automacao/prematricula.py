"""
prematricula.py — Orquestrador do Processo de Pré-Matrícula
=============================================================================
Portado de AUTO_SERE/pre_matricula.py (parse_args, main) para
src/automacao/prematricula.py.

Amarra as 4 etapas já portadas em módulos próprios (decisão do usuário,
03/09/2026 — "fracione em códigos separados"):
    - Etapa 1 (coleta):    src.automacao.prematricula_coleta
    - Etapa 2 (cadastro):  src.automacao.prematricula_cadastro
    - Etapa 3 (contatos):  src.automacao.prematricula_contatos
    - Etapa 4 (pendentes): src.automacao.prematricula_pendentes

ORDEM REAL DE EXECUÇÃO (confirmada lendo main() do original com precisão —
não é a ordem numérica 1-2-3-4): login → Etapa 1 → Etapa 2 → Etapa 4
(ainda dentro da mesma sessão/browser logado) → fecha o navegador →
Etapa 3 (100% offline, não precisa mais do browser). A Etapa 4 roda por
padrão ao final do processo completo; pode ser pulada.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. parse_args()/argparse: REMOVIDO — decisão do usuário (03/09/2026, mesmo
   padrão de sere_2026.py e processo_transferidos.py): as flags do CLI
   original viram parâmetros de função:
       --a / --analise-codigo   → analise_codigo: bool
       --pular-pendentes        → pular_pendentes: bool
       --somente-pendentes      → ver executar_prematricula_somente_pendentes()
       --completar_json (+ --matriculados/--intencoes) → ver
           src.automacao.prematricula_planilhas (ainda não portado nesta
           etapa — modo de completar a partir de planilhas .xlsx; o
           usuário pretende MUDAR esse modo para baixar as planilhas
           automaticamente do site, em vez de só ler arquivo local, assim
           que o site de pré-matrícula voltar ao ar — ver o próprio
           módulo prematricula_planilhas quando existir).

2. Um único login por execução: cada etapa portada (prematricula_coleta,
   prematricula_cadastro, prematricula_pendentes) tem sua própria função
   "executar_*" que abre navegador + faz login + fecha navegador, pensada
   para poder ser chamada ISOLADAMENTE (ex.: um botão "Só coletar
   intenções" numa futura GUI). O orquestrador abaixo NÃO empilha essas
   funções de alto nível (isso faria 3 logins separados, diferente do
   original) — em vez disso, ele repete o mesmo padrão de
   abrir-navegador-uma-vez-só e chama as funções de ETAPA (não as de
   "executar_*"): coletar_intencoes_vaga(), consultar_cadastros(),
   verificar_pendentes() — replicando exatamente o fluxo de sessão única
   do main() original.

3. main() dividida em duas funções (mais claras que um único `if` cascata
   como no original):
     - executar_processo_completo(...): Etapas 1→2→4→3, equivalente ao
       fluxo padrão do main() original (sem nenhuma flag especial).
     - executar_prematricula_somente_pendentes(...): equivalente a
       --somente-pendentes (roda só a Etapa 4, usa
       src.automacao.prematricula_pendentes.verificar_pendentes com
       dados_pre_matricula=None, que já lê o pre_matricula.json do disco).

Toda a lógica de negócio de cada etapa já foi preservada nos módulos
individuais — este arquivo é só a orquestração/sequenciamento, idêntica ao
original.

Uso:
    import asyncio
    from src.automacao.prematricula import executar_processo_completo

    asyncio.run(executar_processo_completo())
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import async_playwright

from src.comum import paths as _paths
from src.comum.prematricula_api import fazer_login
from src.automacao.prematricula_coleta import coletar_intencoes_vaga
from src.automacao.prematricula_cadastro import consultar_cadastros
from src.automacao.prematricula_contatos import gerar_csv_contatos
from src.automacao.prematricula_pendentes import verificar_pendentes

ANO_ATUAL = _paths.ano_atual()


async def executar_processo_completo(
    analise_codigo: bool = False,
    pular_pendentes: bool = False,
) -> dict:
    """
    Executa o processo completo de pré-matrícula: Etapa 1 (coleta) →
    Etapa 2 (cadastro) → Etapa 4 (verificação de pendentes, a menos que
    `pular_pendentes=True`) → Etapa 3 (geração do CSV de contatos).

    Equivalente ao fluxo padrão de main() no original (sem nenhuma flag
    especial). `pular_pendentes` equivale à antiga flag --pular-pendentes.

    Retorna um dict com o resumo de cada etapa:
        {
            "dados_intencoes": {...} | None,
            "cadastros": {...},
            "resumo_pendentes": {...} | None,
            "contatos": [...],
        }
    Se o login ou a Etapa 1 falharem, retorna com "dados_intencoes": None
    e as demais chaves vazias — mesmo comportamento de abortar cedo do
    original.
    """
    resultado: dict = {
        "dados_intencoes": None,
        "cadastros": {},
        "resumo_pendentes": None,
        "contatos": [],
    }

    print("=" * 60)
    print(f"PROCESSO DE PRÉ-MATRÍCULA - {ANO_ATUAL}")
    if analise_codigo:
        print("Modo de análise ativo: screenshots de cada etapa serão salvos.")
    if pular_pendentes:
        print("Etapa 4 (pendentes) será pulada.")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        login_ok = await fazer_login(page, analise_codigo=analise_codigo)
        if not login_ok:
            print("❌ Login falhou. Abortando processo.")
            await browser.close()
            return resultado

        # Etapa 1: coleta de intenções de vaga
        dados_intencoes = await coletar_intencoes_vaga(page, analise_codigo=analise_codigo)
        if dados_intencoes is None:
            print("❌ Etapa 1 falhou. Abortando processo.")
            await browser.close()
            return resultado
        resultado["dados_intencoes"] = dados_intencoes

        # Etapa 2: consulta de cadastro por CPF
        cadastros = await consultar_cadastros(page, dados_intencoes, analise_codigo=analise_codigo)
        resultado["cadastros"] = cadastros

        # Etapa 4: verifica pendentes (matriculados/cancelados), ainda
        # dentro do mesmo browser/sessão de login. Roda por padrão; pode
        # ser pulada com pular_pendentes=True.
        if not pular_pendentes:
            resultado["resumo_pendentes"] = await verificar_pendentes(
                page, analise_codigo=analise_codigo
            )
        else:
            print("\n(Etapa 4 pulada)")

        await browser.close()

    # Etapa 3: geração do CSV (não precisa mais do browser)
    resultado["contatos"] = gerar_csv_contatos(cadastros, dados_intencoes)

    print("\n" + "=" * 60)
    print("✅ PROCESSO COMPLETO FINALIZADO")
    resumo_pendentes = resultado["resumo_pendentes"]
    if resumo_pendentes is not None:
        print(
            f"   Pendentes verificados: {resumo_pendentes['total_pendentes']} | "
            f"Confirmados: {resumo_pendentes['confirmados']} | "
            f"Sem resposta: {len(resumo_pendentes['sem_resposta'])}"
        )
    print("=" * 60)

    return resultado


async def executar_prematricula_somente_pendentes(analise_codigo: bool = False) -> dict:
    """
    Roda SOMENTE a Etapa 4 (verificação de pendentes), sem refazer as
    Etapas 1/2/3 — equivalente à antiga flag --somente-pendentes. Útil
    para rodar essa checagem isoladamente, sem re-coletar as intenções de
    vaga.

    Lê pre_matricula.json do disco (via
    src.automacao.prematricula_pendentes.verificar_pendentes com
    dados_pre_matricula=None).

    Retorna o resumo da Etapa 4 (dict com
    total_pendentes/confirmados/sem_resposta), ou o resumo vazio se o
    login falhar.
    """
    print("=" * 60)
    print(f"PROCESSO DE PRÉ-MATRÍCULA - {ANO_ATUAL}")
    print("Modo --somente-pendentes: roda apenas a Etapa 4.")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        login_ok = await fazer_login(page, analise_codigo=analise_codigo)
        if not login_ok:
            print("❌ Login falhou. Abortando processo.")
            await browser.close()
            return {"total_pendentes": 0, "confirmados": 0, "sem_resposta": []}

        resumo = await verificar_pendentes(page, analise_codigo=analise_codigo)

        await browser.close()

    print("\n" + "=" * 60)
    print("✅ --somente-pendentes FINALIZADO")
    print("=" * 60)

    return resumo


if __name__ == "__main__":
    asyncio.run(executar_processo_completo())

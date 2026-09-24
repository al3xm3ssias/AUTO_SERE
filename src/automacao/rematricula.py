"""
rematricula.py — Orquestrador do Processo de Rematrícula
=============================================================================
Portado de AUTO_SERE/rematricula.py (fazer_login_sere,
navegar_para_por_turmas, processar_aluno, processar_turma, main) para
src/automacao/rematricula.py.

Para cada turma-base em TURMAS_ALVO (ex.: "3º Ano"), lista as seções
existentes (ex.: "3º Ano - A", "3º Ano - B"), e para cada aluno
matriculado ainda não processado: gera uma chave de acesso e o CPF do
responsável no SERE (ver src.automacao.rematricula_sere), abre uma nova
aba no site da Área do Aluno e confirma a rematrícula lá (ver
src.automacao.rematricula_area_aluno), voltando por fim para a lista de
alunos do SERE para seguir com o próximo.

Este arquivo faz parte de uma portabilidade fracionada em 4 módulos
(decisão do usuário, 04/09/2026, mesmo padrão de pre_matricula.py):
    - rematricula_persistencia.py: JSONs de controle + normalização + ErroReiniciarNavegador
    - rematricula_sere.py:         operações na página do SERE
    - rematricula_area_aluno.py:   operações na página da Área do Aluno
    - rematricula.py (este):       processar_aluno/processar_turma + orquestrador

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. headless=False → headless=True — decisão do usuário (04/09/2026):
   padronizado com todos os outros scripts já portados (que sempre usam
   headless=True), diferente do original, que abria o navegador visível.

2. fazer_login_sere() REMOVIDA — reaproveita diretamente
   src.comum.sere_api.URL e src.comum.credenciais.LOGIN/SENHA, mesmo
   padrão de login usado pelos demais scripts SERE já portados.

3. navegar_para_por_turmas() REMOVIDA — comparada linha a linha com
   src.comum.sere_api.navegar_por_turma e confirmada funcionalmente
   idêntica (decisão do usuário, 04/09/2026): reaproveitada diretamente.

4. main() RENOMEADA para executar_rematricula(modo_teste=False,
   apenas_erros=False) — já eram parâmetros de função no original (não
   havia argparse de fato, só uma leitura direta de sys.argv em
   `if __name__ == "__main__":` para as flags --teste/-t e
   --erros/-e) — mantidos como parâmetros nomeados, sem sys.argv,
   consistente com o padrão de todos os outros orquestradores já
   portados.

Toda a lógica de negócio (dois níveis de página temporária por
turma-base — uma para listar seções, outra por seção para listar
alunos —, filtro de alunos já processados/com erro, o loop de recuperação
de processar_turma com até 3 tentativas de reiniciar o navegador por
ErroReiniciarNavegador, e a assinatura (bool, erro_detalhado) de
processar_aluno, incluindo o caso "JA_MATRICULADO") é idêntica ao
original — nenhuma regra foi alterada.

Uso:
    import asyncio
    from src.automacao.rematricula import executar_rematricula

    asyncio.run(executar_rematricula(modo_teste=True))
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from playwright.async_api import async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum.sere_api import URL, navegar_por_turma
from src.automacao.rematricula_persistencia import (
    ARQUIVO_ERROS,
    ARQUIVO_HISTORICO,
    ARQUIVO_SUCESSO,
    ErroReiniciarNavegador,
    aluno_ja_processado,
    carregar_erros_anteriores,
    carregar_sucessos_anteriores,
    salvar_resultados,
)
from src.automacao.rematricula_sere import (
    gerar_chave_acesso,
    listar_secao_turmas,
    obter_alunos_matriculados,
    obter_cpf_responsavel,
    selecionar_turma,
)
from src.automacao.rematricula_area_aluno import (
    acessar_matricula_online,
    confirmar_matricula,
    fazer_login_area_aluno,
    voltar_para_turma,
)

URL_AREA_ALUNO = "https://www.areadoaluno.seed.pr.gov.br/"

TURMAS_ALVO = [
    "INFANTIL 4",
    "INFANTIL 5",
    "1º Ano",
    "2º Ano",
    "3º Ano",
    "4º Ano",
]


async def _fazer_login_sere(page) -> bool:
    """Login no SERE — mesmo padrão usado por todos os outros scripts SERE já portados."""
    try:
        await page.goto(URL)
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print(f"❌ Erro ao fazer login no SERE: {e}")
        return False


async def processar_aluno(page_sere, browser, aluno: dict, turma_nome: str) -> tuple[bool, str | None]:
    """
    Processa a rematrícula de um único aluno: localiza o aluno na lista já
    aberta em `page_sere`, gera chave de acesso + obtém CPF do
    responsável (no SERE), abre uma nova aba (`page_aluno`) no site da
    Área do Aluno, faz login lá, seleciona o aluno certo e confirma a
    matrícula.

    Retorna (sucesso: bool, erro_detalhado: str | None). Quando a
    matrícula já existia anteriormente, retorna (True, None) da mesma
    forma que uma rematrícula nova — quem chama (processar_turma) não
    precisa distinguir os dois casos, mas o log deixa isso claro.

    Levanta ErroReiniciarNavegador (propagada de gerar_chave_acesso) para
    sinalizar que processar_turma deve reiniciar a página inteira do
    aluno atual.
    """
    page_aluno = None
    erro_detalhado = None

    try:
        print(f"\n{'='*70}")
        print(f"👤 Processando: {aluno['Nome']} (CGM: {aluno['cgm']})")
        print(f"{'='*70}")

        await page_sere.wait_for_selector("a[href*='AoClicarAluno']", timeout=20000)
        links_alunos = await page_sere.query_selector_all("a[href*='AoClicarAluno']")

        aluno_encontrado = False
        for link in links_alunos:
            cgm = (await link.inner_text()).strip()
            if cgm == aluno["cgm"]:
                print("🔗 Acessando perfil do aluno...")
                await link.click()
                await page_sere.wait_for_timeout(2000)
                aluno_encontrado = True
                break

        if not aluno_encontrado:
            erro_detalhado = "Aluno não encontrado na lista"
            print(f"❌ {erro_detalhado}")
            return False, erro_detalhado

        # gerar_chave_acesso pode levantar ErroReiniciarNavegador — deixa
        # propagar para processar_turma decidir se reinicia a página.
        chave = await gerar_chave_acesso(page_sere)

        cpf = await obter_cpf_responsavel(page_sere)
        if not cpf:
            erro_detalhado = "CPF do responsável não encontrado"
            print(f"❌ {erro_detalhado}")
            await voltar_para_turma(page_sere)
            return False, erro_detalhado

        page_aluno = await browser.new_page()
        await page_aluno.goto(URL_AREA_ALUNO)
        await page_aluno.wait_for_timeout(2000)

        if not await fazer_login_area_aluno(page_aluno, cpf, chave):
            erro_detalhado = "Erro ao fazer login na Área do Aluno"
            print(f"❌ {erro_detalhado}")
            await voltar_para_turma(page_sere)
            return False, erro_detalhado

        if not await acessar_matricula_online(page_aluno, aluno["Nome"]):
            erro_detalhado = "Erro ao acessar matrícula online"
            print(f"⚠️ {erro_detalhado}")
            await voltar_para_turma(page_sere)
            return False, erro_detalhado

        resultado = await confirmar_matricula(page_aluno)

        if resultado == "JA_MATRICULADO":
            await voltar_para_turma(page_sere)
            print(f"✅ {aluno['Nome']} - JÁ MATRICULADO")
            return True, None

        if not resultado:
            erro_detalhado = "Erro ao confirmar matrícula"
            print(f"⚠️ {erro_detalhado}")
            await voltar_para_turma(page_sere)
            return False, erro_detalhado

        await voltar_para_turma(page_sere)

        print(f"✅ {aluno['Nome']} - REMATRÍCULA PROCESSADA!")
        return True, None

    except ErroReiniciarNavegador:
        raise
    except Exception as e:
        erro_detalhado = str(e)
        print(f"❌ Erro ao processar aluno: {erro_detalhado}")
        return False, erro_detalhado

    finally:
        if page_aluno:
            await page_aluno.close()


async def processar_turma(
    browser, turma_nome: str, alunos_para_processar: list[dict],
    sucessos: list[dict], erros: list[dict], historico: list[dict],
) -> None:
    """
    Processa uma seção de turma completa (ex.: "3º Ano - A"), com
    recuperação automática: se processar_aluno levantar
    ErroReiniciarNavegador, a página inteira da turma é fechada e
    reaberta (novo login + nova navegação + nova seleção de turma),
    retomando do MESMO aluno onde parou — até 3 tentativas de reinício
    por aluno antes de desistir dele e registrar erro permanente.

    `sucessos`, `erros` e `historico` são mutados in-place (o mesmo
    padrão do original) e salvos em disco após cada aluno processado, via
    src.automacao.rematricula_persistencia.salvar_resultados — para não
    perder progresso se o processo cair no meio de uma turma longa.
    """
    indice_atual = 0
    max_tentativas_navegador = 3
    tentativa_navegador = 0

    while indice_atual < len(alunos_para_processar):
        page_turma = None

        try:
            page_turma = await browser.new_page()

            if not await _fazer_login_sere(page_turma):
                print("❌ Falha no login SERE, tentando novamente...")
                await page_turma.close()
                await asyncio.sleep(3)
                continue

            await navegar_por_turma(page_turma)

            if not await selecionar_turma(page_turma, turma_nome):
                print(f"❌ Não foi possível selecionar turma '{turma_nome}'")
                await page_turma.close()
                break

            while indice_atual < len(alunos_para_processar):
                aluno = alunos_para_processar[indice_atual]

                print(f"\n[{indice_atual + 1}/{len(alunos_para_processar)}]", end=" ")

                try:
                    sucesso, erro_msg = await processar_aluno(page_turma, browser, aluno, turma_nome)

                    timestamp = datetime.now().isoformat()

                    registro = {
                        "cgm": aluno["cgm"],
                        "nome": aluno["Nome"],
                        "turma": turma_nome,
                        "data_nascimento": aluno.get("Data Nasc.", ""),
                        "timestamp": timestamp,
                    }

                    if sucesso:
                        if not aluno_ja_processado(aluno, sucessos):
                            sucessos.append(registro)
                        erros[:] = [e for e in erros if e["cgm"] != aluno["cgm"]]
                    else:
                        registro["erro"] = erro_msg
                        registro["tentativas"] = 1

                        erro_anterior = next((e for e in erros if e["cgm"] == aluno["cgm"]), None)
                        if erro_anterior:
                            registro["tentativas"] = erro_anterior.get("tentativas", 1) + 1
                            erros[:] = [e for e in erros if e["cgm"] != aluno["cgm"]]

                        erros.append(registro)

                    historico.append({**registro, "sucesso": sucesso})

                    salvar_resultados(sucessos, erros, historico)

                    indice_atual += 1
                    tentativa_navegador = 0

                    if indice_atual < len(alunos_para_processar):
                        await asyncio.sleep(2)

                except ErroReiniciarNavegador as e:
                    print(f"\n🔄 ERRO CRÍTICO DETECTADO: {e}")
                    print(f"🔄 Fechando navegador e reiniciando do aluno atual...")

                    tentativa_navegador += 1

                    if tentativa_navegador >= max_tentativas_navegador:
                        print(f"❌ Máximo de tentativas ({max_tentativas_navegador}) atingido para este aluno")
                        print(f"⏭️  Pulando aluno: {aluno['Nome']}")

                        registro = {
                            "cgm": aluno["cgm"],
                            "nome": aluno["Nome"],
                            "turma": turma_nome,
                            "data_nascimento": aluno.get("Data Nasc.", ""),
                            "timestamp": datetime.now().isoformat(),
                            "erro": f"Erro crítico após {max_tentativas_navegador} tentativas: {str(e)}",
                            "tentativas": max_tentativas_navegador,
                        }

                        erros.append(registro)
                        historico.append({**registro, "sucesso": False})
                        salvar_resultados(sucessos, erros, historico)

                        indice_atual += 1
                        tentativa_navegador = 0

                    if page_turma:
                        await page_turma.close()
                        page_turma = None

                    await asyncio.sleep(5)
                    break

            if indice_atual >= len(alunos_para_processar):
                if page_turma:
                    await page_turma.close()
                break

        except Exception as e:
            print(f"❌ Erro inesperado ao processar turma: {e}")
            if page_turma:
                await page_turma.close()
            await asyncio.sleep(5)

        finally:
            if page_turma:
                try:
                    await page_turma.close()
                except Exception:
                    pass


async def executar_rematricula(modo_teste: bool = False, apenas_erros: bool = False) -> dict:
    """
    Ponto de entrada do processo completo de rematrícula. Renomeada de
    main() no original — já eram parâmetros de função (modo_teste,
    apenas_erros), só não havia argparse de fato: o original lia
    sys.argv diretamente em `if __name__ == "__main__":` para as flags
    --teste/-t e --erros/-e. Mantidos como parâmetros nomeados, sem
    sys.argv, consistente com todos os outros orquestradores já
    portados. Pronta para ser chamada por um futuro botão de GUI.

    `modo_teste`: processa apenas 1 aluno por seção de turma.
    `apenas_erros`: reprocessa somente os alunos que já falharam em
        execuções anteriores (por seção), ignorando quem nunca foi
        tentado.

    Retorna um resumo: {"sucessos": [...], "erros": [...], "historico": [...]}.
    """
    print("\n" + "=" * 70)

    if apenas_erros:
        print("🔄 MODO REPROCESSAMENTO - Apenas alunos com erro")
    elif modo_teste:
        print("🧪 MODO TESTE - 1 aluno por turma")
    else:
        print("▶️ MODO PRODUÇÃO")

    print("=" * 70)

    sucessos_anteriores = carregar_sucessos_anteriores()
    erros_anteriores = carregar_erros_anteriores()

    print(f"📊 Sucessos anteriores: {len(sucessos_anteriores)}")
    print(f"📊 Erros anteriores: {len(erros_anteriores)}")

    sucessos = list(sucessos_anteriores)
    erros: list[dict] = []
    historico: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        try:
            for turma_nome in TURMAS_ALVO:
                print(f"\n{'='*70}")
                print(f"📚 PROCESSANDO TURMA (base): {turma_nome}")
                print(f"{'='*70}")

                page_temp = await browser.new_page()

                if not await _fazer_login_sere(page_temp):
                    await page_temp.close()
                    continue

                await navegar_por_turma(page_temp)

                secoes = await listar_secao_turmas(page_temp, turma_nome)
                await page_temp.close()

                if not secoes:
                    print(f"\n⚠️ Nenhuma seção encontrada para '{turma_nome}'")
                    continue

                for secao_texto in secoes:
                    print(f"\n--- Iniciando seção: {secao_texto} ---")
                    page_temp2 = await browser.new_page()

                    if not await _fazer_login_sere(page_temp2):
                        await page_temp2.close()
                        continue

                    await navegar_por_turma(page_temp2)

                    if not await selecionar_turma(page_temp2, secao_texto):
                        print(f"\n⚠️ Seção '{secao_texto}' não encontrada ao tentar selecionar")
                        await page_temp2.close()
                        continue

                    alunos = await obter_alunos_matriculados(page_temp2)
                    await page_temp2.close()

                    if not alunos:
                        print(f"\n⚠️ Nenhum aluno matriculado em '{secao_texto}'")
                        continue

                    if apenas_erros:
                        cgms_com_erro = {e["cgm"] for e in erros_anteriores if e["turma"] == secao_texto}
                        alunos_para_processar = [a for a in alunos if a["cgm"] in cgms_com_erro]
                        print(f"🔄 {len(alunos_para_processar)} alunos com erro para reprocessar em {secao_texto}")
                    else:
                        alunos_para_processar = [a for a in alunos if not aluno_ja_processado(a, sucessos_anteriores)]
                        if modo_teste:
                            alunos_para_processar = alunos_para_processar[:1]

                    if not alunos_para_processar:
                        print(f"✅ Todos os alunos de '{secao_texto}' já foram processados!")
                        continue

                    await processar_turma(browser, secao_texto, alunos_para_processar, sucessos, erros, historico)

        finally:
            await browser.close()

    salvar_resultados(sucessos, erros, historico)

    print("\n\n" + "=" * 70)
    print("📊 RESUMO FINAL")
    print("=" * 70)
    print(f"✅ Total de sucessos: {len(sucessos)}")
    print(f"❌ Total com erro: {len(erros)}")
    print(f"📝 Registros no histórico: {len(historico)}")
    print("=" * 70)

    if erros:
        print("\n⚠️ Alunos com erro:")
        for e in erros:
            print(f"  - {e['nome']} (CGM: {e['cgm']}) - Tentativas: {e.get('tentativas', 1)}")
            print(f"    Erro: {e.get('erro', 'Não especificado')}")

    print(f"\n📁 Arquivos salvos:")
    print(f"  - {ARQUIVO_SUCESSO}")
    print(f"  - {ARQUIVO_ERROS}")
    print(f"  - {ARQUIVO_HISTORICO}")
    print("=" * 70 + "\n")

    return {"sucessos": sucessos, "erros": erros, "historico": historico}


if __name__ == "__main__":
    asyncio.run(executar_rematricula())

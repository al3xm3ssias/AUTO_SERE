"""
rematricula_area_aluno.py — Operações na Área do Aluno (site do Estado)
=============================================================================
Portado de AUTO_SERE/rematricula.py (fazer_login_area_aluno,
acessar_matricula_online, confirmar_matricula) para
src/automacao/rematricula_area_aluno.py.

Funções que operam exclusivamente no site do Estado do Paraná
(areadoaluno.seed.pr.gov.br/servicosaoaluno) — não confundir com
src.automacao.rematricula_sere, que opera na página do SERE. Login com
CPF do responsável + chave de acesso temporária (geradas no SERE, ver
src.automacao.rematricula_sere.gerar_chave_acesso/obter_cpf_responsavel),
seleção do aluno correto no formulário PrimeFaces de confirmação de
matrícula, e confirmação final em cascata de telas "Sim".

Nenhuma mudança de comportamento em relação ao original — os seletores
PrimeFaces (IDs com ":" escapado, ex.: "#Login\\:cpf"), a normalização de
espaços ao comparar nome do aluno no dropdown, e a sequência de cliques
"Sim" (com IDs alternativos) são preservados exatamente como estavam.

Uso:
    from src.automacao.rematricula_area_aluno import fazer_login_area_aluno, acessar_matricula_online, confirmar_matricula

    ok = await fazer_login_area_aluno(page_aluno, cpf, chave)
    ok = await acessar_matricula_online(page_aluno, "Ana Silva")
    ok = await confirmar_matricula(page_aluno)
"""

from __future__ import annotations


async def fazer_login_area_aluno(page, cpf: str, chave: str) -> bool:
    """
    Faz login na Área do Aluno usando o CPF do responsável e a chave de
    acesso temporária gerada no SERE (ver
    src.automacao.rematricula_sere.obter_cpf_responsavel/gerar_chave_acesso).
    """
    try:
        print("🔐 Fazendo login na Área do Aluno...")

        try:
            await page.click("//span[contains(text(), 'Matrícula ou Rematrícula')]", timeout=5000)
        except Exception:
            await page.click("//button[contains(text(), 'Matrícula')]", timeout=5000)

        await page.wait_for_timeout(1000)

        await page.fill("#Login\\:cpf", cpf)
        await page.wait_for_timeout(500)

        await page.fill("#Login\\:chaveAcessoResposavel", chave)
        await page.wait_for_timeout(500)

        await page.click("#Login\\:EntrarResponsavel", timeout=5000)
        await page.wait_for_timeout(3000)

        print("✅ Login Área do Aluno realizado!")
        return True

    except Exception as e:
        print(f"❌ Erro ao fazer login na Área do Aluno: {e}")
        return False


async def acessar_matricula_online(page, nome_aluno: str) -> bool:
    """
    Navega até a tela de confirmação de escola sugerida e seleciona, no
    dropdown PrimeFaces, o aluno cujo nome corresponda a `nome_aluno`
    (comparação tolerante a espaçamento — colapsa múltiplos espaços e
    ignora caixa).
    """
    try:
        print(f"🔍 Acessando matrícula online para {nome_aluno}...")

        try:
            await page.evaluate("""
                try { $(function(){ PF('modalEnvioDocumetos').hide(); }); } catch(e) {}
            """)
            print("✓ Modal fechado automaticamente via jQuery+PF")
            await page.wait_for_timeout(800)
        except Exception:
            pass

        print("➡️ Abrindo página de confirmação da matrícula...")

        try:
            await page.click("//a[contains(@href,'confirmacaoEscolaSugerida.jsf')]", timeout=4000)
        except Exception:
            await page.goto("https://www.areadoaluno.seed.pr.gov.br/servicosaoaluno/pages/v2/matriculaOnLine/confirmacaoEscolaSugerida.jsf")

        await page.wait_for_timeout(2000)

        print("🎯 Localizando select de aluno...")

        await page.click("#confirmacaoEscolaSugeridaForm\\:aluno_label", timeout=5000)
        await page.wait_for_timeout(600)

        print("🔎 Verificando se o aluno correto está no select...")

        itens = await page.query_selector_all("//li[contains(@id,'confirmacaoEscolaSugeridaForm:aluno_')]")

        # Normaliza nome do aluno para comparar (colapsa múltiplos espaços)
        nome_normalizado = " ".join(nome_aluno.split()).strip().upper()

        aluno_certo = None
        for item in itens:
            # Também normaliza o texto do item para evitar problemas de espaçamento
            texto_item = " ".join((await item.inner_text()).split()).strip().upper()
            if nome_normalizado in texto_item:
                aluno_certo = item
                break

        if not aluno_certo:
            print(f"❌ O aluno '{nome_aluno}' NÃO aparece no dropdown!")
            return False

        print(f"✅ Aluno encontrado no dropdown: {nome_aluno}")
        await aluno_certo.click()
        await page.wait_for_timeout(1000)

        print("🎉 Aluno selecionado com sucesso!")
        return True

    except Exception as e:
        print(f"❌ Erro no fluxo de matrícula online: {e}")
        return False


async def confirmar_matricula(page):
    """
    Confirma a matrícula do aluno selecionado.

    Antes de tentar confirmar, checa se a matrícula já foi realizada
    anteriormente (texto "MATRÍCULA REALIZADA COM SUCESSO" ou "IMPRIMIR
    COMPROVANTE" já presentes na página) — nesse caso retorna o marcador
    de string "JA_MATRICULADO" em vez de True/False, para que quem chamar
    (ver src.automacao.rematricula.processar_aluno) trate esse caso como
    sucesso sem reprocessar.

    Clica em "Confirmar Matrícula Nesta Instituição" (com fallback por
    texto), depois responde em cascata a QUALQUER quantidade de
    perguntas "SIM" que aparecerem (até 15 tentativas — o número de
    perguntas de confirmação pode variar por aluno/situação), e por fim
    clica no botão final de confirmação (por ID PrimeFaces, com fallback
    por texto).

    Retorna True em caso de sucesso, "JA_MATRICULADO" se a matrícula já
    existia, ou False em caso de erro.
    """
    try:
        try:
            texto = (await page.content()).upper()

            if "MATRÍCULA REALIZADA COM SUCESSO" in texto:
                print("🎉 Matrícula já realizada anteriormente – pulando aluno.")
                return "JA_MATRICULADO"

            if "IMPRIMIR COMPROVANTE" in texto:
                print("🎉 Comprovante disponível – matrícula já realizada.")
                return "JA_MATRICULADO"

        except Exception as e:
            print("⚠️ Erro ao verificar matrícula já realizada:", e)

        print("✔️ Confirmando matrícula...")

        try:
            await page.click("//button[contains(., 'Confirmar Matrícula Nesta Instituição')]", timeout=5000)
        except Exception:
            await page.click("//span[contains(text(), 'Confirmar Matrícula')]", timeout=5000)

        await page.wait_for_timeout(2000)

        sim_count = 0
        max_tentativas = 15

        while sim_count < max_tentativas:
            try:
                botoes_sim = await page.query_selector_all("//button[contains(., 'SIM')]")
                if not botoes_sim:
                    break

                await botoes_sim[0].click()
                sim_count += 1
                await page.wait_for_timeout(1500)

            except Exception:
                break

        if sim_count > 0:
            print(f"✅ {sim_count} perguntas respondidas com SIM")

        await page.wait_for_timeout(1500)

        print("➡️ Clicando no botão FINAL de Confirmar...")

        try:
            await page.click("#confirmacaoEscolaSugeridaForm\\:j_idt147", timeout=5000)
            print("🎉 Botão final 'Confirmar' clicado com sucesso!")
        except Exception:
            print("⚠️ Não achou pelo ID, tentando por texto...")

            try:
                await page.click("//button[span[contains(text(),'Confirmar')]]", timeout=5000)
                print("🎉 Botão final 'Confirmar' clicado pelo texto!")
            except Exception as e:
                print(f"❌ Erro ao clicar no botão final de Confirmar: {e}")
                return False

        await page.wait_for_timeout(2000)

        print("🎉 Matrícula processada COMPLETAMENTE!")
        return True

    except Exception as e:
        print(f"❌ Erro ao confirmar matrícula: {e}")
        return False


async def voltar_para_turma(page) -> None:
    """Volta para a página anterior (lista de alunos da turma no SERE)."""
    try:
        await page.go_back()
        await page.wait_for_timeout(1500)
    except Exception:
        pass

"""
alunos.py — Coleta de cadastro completo de alunos no SERE
=============================================================================
Portado de AUTO_SERE/alunos.py para src/automacao/alunos.py.

Percorre o SERE (Consulta Padrão → Por Turma) e extrai, para cada aluno de
cada turma, o cadastro individual COMPLETO (documentos pessoais, filiação,
endereço, contatos, informações socioeconômicas) — diferente de
src.automacao.turmas, que coleta só os dados básicos de turma (CGM, nome,
data de nascimento, situação). O resultado é salvo em alunos.json, uma
lista plana com o cadastro completo de todos os alunos.

Este é o script mais simples/antigo desta família — o usuário também pediu
a portabilidade de alunos_completo.py (versão com cache incremental, fila
filtrada por status e registro de erros persistente), que fica em um
arquivo separado (src/automacao/alunos_completo.py).

LIMITAÇÕES JÁ DOCUMENTADAS NO ORIGINAL (preservadas, não são bugs desta
portabilidade):
- Sem mecanismo de retry: qualquer falha ao processar um aluno é só
  capturada e logada, sem nova tentativa — pode resultar em cadastro
  parcial para aquele aluno.
- XPaths dependem de rótulos/estrutura literal do SERE (classes
  texto_form/texto_normal); mudanças no portal podem quebrar a extração de
  campos específicos silenciosamente (retornando string vazia).
- O campo "UF" do endereço é extraído via following-sibling do campo CEP —
  dependência posicional frágil.
- Sem tratamento de exceção ao redor do login: falhas nesse trecho
  interrompem o script sem recuperação.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. navigate_to_por_turma() REMOVIDA — reaproveita
   src.comum.sere_api.navegar_por_turma (decisão do usuário, 02/09/2026),
   já unificada com a navegação usada por src.automacao.turmas.

2. coletar_turmas_e_alunos() RENOMEADA para coletar_cadastro_completo_alunos()
   — decisão do usuário: o nome original colidia com a função de mesmo nome
   em src.automacao.turmas, que faz algo bem diferente (coleta só dados
   básicos de turma, não o cadastro individual completo). Manter os dois
   com o mesmo nome geraria confusão real entre os dois arquivos.

3. Caminhos: BASE_DIR fixo (servidor Linux, ano calculado dinamicamente
   via ano_atual() local) trocado por src.comum.paths.dados_ano_atual() —
   mesma fonte usada por todos os outros scripts já portados. A função
   ano_atual() local foi removida (já existe em src.comum.paths).

4. Credenciais e logger: imports trocados para src.comum.credenciais e
   src.comum.logger, como em todos os outros módulos já portados.

5. Import de timedelta (não utilizado em nenhum ponto do original, como o
   próprio docstring do script apontava) foi removido.

6. main() RENOMEADA para coletar_alunos_via_login(), no mesmo padrão de
   src.automacao.turmas.coletar_turmas_e_alunos_via_login() — pronta para
   ser chamada por um futuro botão de GUI (sem argparse, sem input()).

Toda a lógica de extração de campos (XPaths, tratamento do campo "Cor",
navegação por CGM, retorno para a lista de turmas) é idêntica ao original —
nenhuma regra de negócio foi alterada.

Uso:
    import asyncio
    from src.automacao.alunos import coletar_alunos_via_login

    asyncio.run(coletar_alunos_via_login())
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum.logger import get_logger
from src.comum import paths as _paths
from src.comum.sere_api import URL, navegar_por_turma

log = get_logger(__file__)

if not LOGIN or not SENHA:
    raise ValueError("Configure LOGIN e SENHA em credenciais/.env (ver .env.example)")

# Pasta de dados de trabalho do ano letivo corrente — antes fixo em
# BASE_DIR = f"/home/sambauser/.../SERE/{ANO_BASE}" com ano_atual() local
# (mesma lógica de src.comum.paths.ano_atual(), agora centralizada lá).
_DADOS = _paths.dados_ano_atual()

ALUNOS_JSON = _DADOS / "alunos.json"


async def get_turmas_validas(page) -> list[str]:
    """Coleta a lista de turmas válidas exibidas na tabela (ignora 'SEM SERIAÇÃO')."""
    turmas_validas: list[str] = []
    rows = await page.query_selector_all("//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]")

    for r in rows:
        colunas = await r.query_selector_all("td")
        if len(colunas) >= 4:
            serie = (await colunas[1].inner_text()).strip()
            turno = (await colunas[2].inner_text()).strip()
            letra = (await colunas[3].inner_text()).strip()
            turma_id = f"{serie} {turno} {letra}"
            if "SEM SERIAÇÃO" in turma_id.upper():
                log.info(f"Turma ignorada (SEM SERIAÇÃO): {turma_id}")
                continue
            if turma_id not in turmas_validas:
                turmas_validas.append(turma_id)

    return turmas_validas


async def get_dados_aluno(page, cgm: str) -> dict:
    """
    Abre a ficha cadastral do aluno (clicando no CGM) e extrai o cadastro
    completo campo a campo via XPath. Falha em um aluno é logada e não
    interrompe a coleta dos demais (sem retry — ver limitações no docstring
    do módulo).
    """
    aluno_data: dict = {}

    try:
        link = await page.query_selector(f"//td[a/text()='{cgm}']/a")
        if not link:
            print(f"[AVISO] CGM {cgm} não encontrado")
            return aluno_data

        await link.click()
        await page.wait_for_timeout(1000)

        async def get_text(xpath: str) -> str:
            el = await page.query_selector(xpath)
            if not el:
                return ""
            txt = await el.inner_text()
            return txt.strip().replace("\xa0", " ")

        aluno_data["Nome"] = await get_text("//td[@class='texto_form' and contains(text(),'Nome')]/following-sibling::td")
        aluno_data["CGM"] = await get_text("//td[@class='texto_form' and contains(text(),'CGM')]/following-sibling::td")

        log.info(f"Acessando aluno → CGM: {aluno_data.get('CGM', cgm)} | Nome: {aluno_data.get('Nome', 'N/A')}")

        aluno_data["Data Nascimento"] = await get_text("//td[@class='texto_form' and contains(text(),'Data de Nascimento')]/following-sibling::td")
        aluno_data["Sexo"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Sexo')]]")
        aluno_data["Estado Civil"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Estado Civil')]]")
        aluno_data["Município Nascimento"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Município de nascimento')]]")
        aluno_data["UF Nascimento"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'UF')]]")
        aluno_data["Nacionalidade"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Nacionalidade')]]")

        # Cor: pega só o text node, sem incluir "Povo Indígena"
        cor_raw = await get_text("//td[@class='texto_normal'][b[contains(text(),'Cor')]]")
        aluno_data["Cor"] = cor_raw.split("Povo Indígena")[0].replace("Cor :", "").strip()

        aluno_data["RG"] = await get_text("//td[@class='texto_form'][contains(text(),'RG')]/font")
        aluno_data["Data Expedição RG"] = await get_text("//td[@class='texto_form'][contains(text(),'Data de Expedição')]/font")
        aluno_data["Órgão Emissor"] = await get_text("//td[@class='texto_form'][contains(text(),'Órgão Emissor')]/font")
        aluno_data["UF RG"] = await get_text("//td[@class='texto_form'][contains(text(),'UF')]/font")
        aluno_data["CPF"] = await get_text("//td[@class='texto_form'][contains(text(),'CPF')]/font")

        aluno_data["Mãe"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Nome da Mãe')]]")
        aluno_data["Pai"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Nome do Pai')]]")
        aluno_data["Responsável"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Responsável')]]")
        aluno_data["Parentesco"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Parentesco do Respons')]]")
        aluno_data["CPF Responsável"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'CPF do Respons')]]")

        aluno_data["CEP"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'CEP')]]")
        aluno_data["UF"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'CEP')]]/following-sibling::td")
        aluno_data["Cidade"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Cidade')]]")
        aluno_data["Endereço"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Endere')]]")
        aluno_data["Número"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Número')]]")
        aluno_data["Complemento"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Complemento')]]")
        aluno_data["Bairro"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Bairro')]]")

        aluno_data["Celular Aluno"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Celular Aluno')]]")
        aluno_data["Celular Responsável"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Celular Respons')]]")
        aluno_data["Telefone Residencial"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Telefone Residencial')]]")
        aluno_data["Telefone Comercial"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Telefone Comercial')]]")
        aluno_data["Email Aluno"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Email aluno')]]")
        aluno_data["Email Responsável"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Email responsável')]]")
        aluno_data["Email Google"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Email Google Education')]]")

        aluno_data["Bolsa Família"] = await get_text("//td[@class='texto_form'][contains(text(),'Participa do Programa Bolsa Família')]/following-sibling::td")
        aluno_data["NIS Estudante"] = await get_text("//td[@class='texto_form'][contains(text(),'NIS do Estudante')]/font")
        aluno_data["NIS Responsável"] = await get_text("//td[@class='texto_form'][contains(text(),'NIS do Responsável')]/font")

        voltar = await page.query_selector("//input[@value='Voltar']")
        if voltar:
            await voltar.click()
        else:
            await page.go_back()
        await page.wait_for_timeout(500)

    except Exception as e:
        print(f"[ERRO] Falha ao coletar dados do CGM {cgm}: {e}")

    return aluno_data


async def get_alunos_da_turma(page, turma_id: str) -> tuple[str, list[dict]]:
    """
    Abre a turma pelo `turma_id` e coleta o cadastro completo de todos os
    seus alunos (um clique no CGM por aluno, retornando à lista de alunos
    da turma só depois de todos coletados).
    """
    alunos: list[dict] = []

    rows = await page.query_selector_all("//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]")
    target_row = None
    for r in rows:
        colunas = await r.query_selector_all("td")
        if len(colunas) >= 4:
            serie = (await colunas[1].inner_text()).strip()
            turno = (await colunas[2].inner_text()).strip()
            letra = (await colunas[3].inner_text()).strip()
            full_id = f"{serie} {turno} {letra}"
            if full_id == turma_id:
                target_row = r
                break

    if not target_row:
        print(f"[AVISO] Não encontrou a turma {turma_id}")
        return turma_id, alunos

    link = await target_row.query_selector("a[href^='javascript:AoClicarTurma']")
    if link:
        await link.click()
    else:
        print(f"[ERRO] Link não encontrado na linha da turma {turma_id}")
        return turma_id, alunos

    await page.wait_for_selector(
        "//table//tr[td/a[contains(@href,'javascript:AoClicarAluno')]]", timeout=5000
    )

    aluno_rows = page.locator("//table//tr[td/a[contains(@href,'javascript:AoClicarAluno')]]")
    count = await aluno_rows.count()

    for i in range(count):
        cgm_link = aluno_rows.nth(i).locator("a[href^='javascript:AoClicarAluno']")
        cgm = await cgm_link.inner_text()
        dados_aluno = await get_dados_aluno(page, cgm)
        alunos.append(dados_aluno)
        # NÃO volta aqui! só volta depois que acabar o loop

    voltar = await page.query_selector("//input[@value='Voltar']")
    if voltar:
        await voltar.click()
    else:
        await page.go_back()
    await page.wait_for_timeout(500)

    return turma_id, alunos


async def coletar_cadastro_completo_alunos(page, output_file: Path = ALUNOS_JSON) -> list[dict]:
    """
    Orquestra a coleta completa: navega até 'Por Turma', coleta a lista de
    turmas válidas, e para cada uma coleta o cadastro completo de todos os
    alunos, salvando o resultado consolidado (lista plana) em `output_file`
    (alunos.json, por padrão).

    Renomeada de coletar_turmas_e_alunos() no original — decisão do usuário
    (02/09/2026), para não colidir com a função de mesmo nome em
    src.automacao.turmas, que coleta algo bem diferente (dados básicos por
    turma, não cadastro individual completo).

    Assume que `page` já está autenticada no SERE — quem só quer disparar
    a coleta completa (login + coleta) deve chamar
    coletar_alunos_via_login() em vez desta função diretamente.
    """
    await navegar_por_turma(page)
    await page.wait_for_timeout(1000)

    alunos_data: list[dict] = []

    turmas = await get_turmas_validas(page)
    print(f"Encontradas {len(turmas)} turmas válidas")

    for turma_id in turmas:
        nome, alunos = await get_alunos_da_turma(page, turma_id)
        alunos_data.extend(alunos)
        print(f"Turma {nome} → {len(alunos)} alunos")

    log.info(f"Todas as turmas coletadas. Salvando JSON em '{output_file}'...")
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(alunos_data, f, ensure_ascii=False, indent=4)
        log.info(f"JSON salvo com sucesso em '{output_file}'.")
    except OSError as e:
        log.error(f"ERRO ao salvar JSON: {e}")
        raise

    log.info("=== Coleta geral finalizada ===")
    return alunos_data


async def coletar_alunos_via_login(output_file: Path = ALUNOS_JSON) -> list[dict]:
    """
    Ponto de entrada completo: abre o navegador, faz login no SERE, coleta
    o cadastro completo de todos os alunos, salva em `output_file` e fecha
    o navegador. Renomeada de main() no original — mesmo padrão de
    src.automacao.turmas.coletar_turmas_e_alunos_via_login(), pronta para
    ser chamada por um futuro botão de GUI (sem argparse, sem input()).
    """
    log.info("Iniciando Playwright...")
    async with async_playwright() as p:
        log.info("Playwright iniciado, abrindo browser...")
        browser = await p.chromium.launch(headless=True)
        log.info("Browser aberto, abrindo página...")
        page = await browser.new_page()
        log.info("Acessando URL...")
        await page.goto(URL)
        log.info("URL carregada, fazendo login...")
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        log.info("Login enviado, aguardando...")
        await page.wait_for_timeout(3000)
        log.info("Iniciando coleta...")

        resultado = await coletar_cadastro_completo_alunos(page, output_file=output_file)

        log.info("Coleta finalizada!")
        await browser.close()

    return resultado


if __name__ == "__main__":
    import asyncio
    asyncio.run(coletar_alunos_via_login())

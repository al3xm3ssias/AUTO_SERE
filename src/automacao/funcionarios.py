"""
funcionarios.py — Coleta de cadastro completo de funcionários no SERE
=============================================================================
Portado de AUTO_SERE/funcionarios.py para src/automacao/funcionarios.py.

Percorre o SERE (Censo Escolar → Funcionário/Docente → Consulta
Funcionários/Docentes) e extrai o cadastro individual completo de cada
funcionário — documentos pessoais, filiação, endereço, contatos —,
salvando em funcionarios.json. Análogo em espírito a src.automacao.alunos
(a versão simples de coleta de cadastro), mas para funcionários em vez de
alunos.

Este é o script mais simples desta família — o usuário também pediu a
portabilidade de src.automacao.servidores (versão mais completa, que
também gera funcionarios_completo.json e funcionarios_matriculas.json —
este último já esperado por src.automacao.termo_ciencia, portado
anteriormente).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. navigate_to_professores() REMOVIDA — reaproveita
   src.comum.sere_api.navegar_censo_escolar (decisão do usuário,
   02/09/2026), generalizada junto com navegar_relatorios via uma função
   interna comum (_navegar_menu_topo) — o padrão de navegação (mouseover
   + clique no item de topo + clique em cada item de uma rota) é o mesmo,
   só muda o item de topo clicado primeiro ("Censo Escolar" em vez de
   "Relatórios").

2. Caminhos: BASE_DIR fixo (servidor Linux) trocado por
   src.comum.paths.dados_ano_atual() — mesma arquitetura de todos os
   outros scripts já portados. FUNCIONARIOS_JSON deriva dali.

3. Credenciais e logger: imports trocados para src.comum.credenciais e
   src.comum.logger.

4. main() RENOMEADA para coletar_funcionarios_via_login(), no mesmo
   padrão de src.automacao.turmas/alunos — pronta para ser chamada por um
   futuro botão de GUI (sem argparse, sem input()).

Toda a lógica de extração de campos (XPaths idênticos aos de
src.automacao.alunos — mesma estrutura de tela texto_form/texto_normal do
SERE) é idêntica ao original — nenhuma regra de negócio foi alterada.

Uso:
    import asyncio
    from src.automacao.funcionarios import coletar_funcionarios_via_login

    asyncio.run(coletar_funcionarios_via_login())
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum.logger import get_logger
from src.comum import paths as _paths
from src.comum.sere_api import URL, navegar_censo_escolar
from src.comum import navegador as _navegador

log = get_logger(__file__)

if not LOGIN or not SENHA:
    raise ValueError("Configure LOGIN e SENHA em credenciais/.env (ver .env.example)")

_DADOS = _paths.dados_ano_atual()

FUNCIONARIOS_JSON = _DADOS / "funcionarios.json"


async def get_dados_funcionario(page, cgm: str) -> dict:
    """
    Abre a ficha cadastral do funcionário (clicando na matrícula/CGM) e
    extrai o cadastro completo campo a campo via XPath. Falha em um
    funcionário é logada e não interrompe a coleta dos demais (sem retry,
    mesmo comportamento de src.automacao.alunos).
    """
    dados: dict = {}

    try:
        link = await page.query_selector(f"//td[a/text()='{cgm}']/a")
        if not link:
            print(f"[AVISO] Matrícula {cgm} não encontrada")
            return dados

        await link.click()
        await page.wait_for_timeout(1000)

        async def get_text(xpath: str) -> str:
            el = await page.query_selector(xpath)
            if not el:
                return ""
            txt = await el.inner_text()
            return txt.strip().replace("\xa0", " ")

        dados["Nome"] = await get_text("//td[@class='texto_form' and contains(text(),'Nome')]/following-sibling::td")
        dados["Matricula"] = await get_text("//td[@class='texto_form' and contains(text(),'Matr')]/following-sibling::td")

        log.info(f"Acessando funcionário → Matrícula: {dados.get('Matricula', cgm)} | Nome: {dados.get('Nome', 'N/A')}")

        dados["Data Nascimento"] = await get_text("//td[@class='texto_form' and contains(text(),'Data de Nascimento')]/following-sibling::td")
        dados["Sexo"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Sexo')]]")
        dados["Estado Civil"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Estado Civil')]]")
        dados["Nacionalidade"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Nacionalidade')]]")

        dados["RG"] = await get_text("//td[@class='texto_form'][contains(text(),'RG')]/font")
        dados["Órgão Emissor"] = await get_text("//td[@class='texto_form'][contains(text(),'Órgão Emissor')]/font")
        dados["UF RG"] = await get_text("//td[@class='texto_form'][contains(text(),'UF')]/font")
        dados["CPF"] = await get_text("//td[@class='texto_form'][contains(text(),'CPF')]/font")

        dados["CEP"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'CEP')]]")
        dados["Cidade"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Cidade')]]")
        dados["Endereço"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Endere')]]")
        dados["Bairro"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Bairro')]]")

        dados["Celular"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Celular')]]")
        dados["Telefone Residencial"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Telefone Residencial')]]")
        dados["Email"] = await get_text("//td[@class='texto_normal'][b[contains(text(),'Email')]]")

        voltar = await page.query_selector("//input[@value='Voltar']")
        if voltar:
            await voltar.click()
        else:
            await page.go_back()
        await page.wait_for_timeout(500)

    except Exception as e:
        print(f"[ERRO] Falha ao coletar dados da matrícula {cgm}: {e}")

    return dados


async def get_funcionarios_da_lista(page) -> list[dict]:
    """
    Coleta o cadastro completo de todos os funcionários listados na tela
    de consulta (já navegada). Um clique por funcionário, retornando à
    lista só depois de todos coletados.
    """
    funcionarios: list[dict] = []

    await page.wait_for_selector(
        "//table//tr[td/a[contains(@href,'javascript:AoClicarFuncionario')]]",
        timeout=5000,
    )

    linhas = page.locator("//table//tr[td/a[contains(@href,'javascript:AoClicarFuncionario')]]")
    count = await linhas.count()

    for i in range(count):
        link_matricula = linhas.nth(i).locator("a[href^='javascript:AoClicarFuncionario']")
        matricula = await link_matricula.inner_text()
        dados = await get_dados_funcionario(page, matricula)
        funcionarios.append(dados)
        # NÃO volta aqui! só volta depois que acabar o loop

    return funcionarios


async def coletar_funcionarios(page, output_file: Path = FUNCIONARIOS_JSON) -> list[dict]:
    """
    Orquestra a coleta completa: navega até 'Censo Escolar → Funcionário/
    Docente → Consulta Funcionários/Docentes', coleta o cadastro completo
    de todos os funcionários listados, salvando o resultado (lista plana)
    em `output_file` (funcionarios.json, por padrão).

    Assume que `page` já está autenticada no SERE — quem só quer disparar
    a coleta completa (login + coleta) deve chamar
    coletar_funcionarios_via_login() em vez desta função diretamente.
    """
    await navegar_censo_escolar(page, ("Funcionário/ Docente", "Consulta Funcionários/Docentes"))
    await page.wait_for_timeout(1000)

    funcionarios_data = await get_funcionarios_da_lista(page)
    print(f"Coletados {len(funcionarios_data)} funcionários")

    log.info(f"Coleta concluída. Salvando JSON em '{output_file}'...")
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(funcionarios_data, f, ensure_ascii=False, indent=4)
        log.info(f"JSON salvo com sucesso em '{output_file}'.")
    except OSError as e:
        log.error(f"ERRO ao salvar JSON: {e}")
        raise

    log.info("=== Coleta geral finalizada ===")
    return funcionarios_data


async def coletar_funcionarios_via_login(output_file: Path = FUNCIONARIOS_JSON) -> list[dict]:
    """
    Ponto de entrada completo: abre o navegador, faz login no SERE, coleta
    o cadastro completo de todos os funcionários, salva em `output_file` e
    fecha o navegador. Renomeada de main() no original — mesmo padrão de
    src.automacao.turmas/alunos, pronta para ser chamada por um futuro
    botão de GUI (sem argparse, sem input()).
    """
    log.info("Iniciando Playwright...")
    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "chromium", True)
        page = await browser.new_page()
        await page.goto(URL)
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3000)
        log.info("Login efetuado, iniciando coleta...")

        resultado = await coletar_funcionarios(page, output_file=output_file)

        log.info("Coleta finalizada!")
        await browser.close()

    return resultado


if __name__ == "__main__":
    import asyncio
    asyncio.run(coletar_funcionarios_via_login())

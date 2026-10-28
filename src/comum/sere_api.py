"""
sere_api.py — Navegação e API do portal SERE (compartilhado)
=============================================================================
Portado de AUTO_SERE/sere_2026.py (linhas 723-925 do original) para
src/comum/sere_api.py.

Estas funções são a base de navegação/autenticação/comunicação com a API
interna do SERE, usada TANTO pelo fluxo de limpeza (sere_limpeza.py) quanto
pelo fluxo de upload (sere_upload.py) — e, no futuro, por outros scripts que
hoje reimplementam login/navegação de forma parecida (analisa_arquivos_sere.py,
por exemplo, tem seu próprio login Playwright semelhante a este).

Todas recebem `page` (uma Page do Playwright já aberta e navegada até o SERE)
como primeiro argumento — este módulo não abre navegador nem gerencia sessão
Playwright sozinho, isso continua sendo responsabilidade de quem orquestra
(o script principal / modo).

Uso:
    from src.comum.sere_api import (
        esta_na_tela_login, garantir_logado, navegar_por_aluno,
        navegar_pasta_virtual, buscar_documentos_api, excluir_arquivo_api,
    )
"""

from __future__ import annotations

import logging

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .sere_utils import norm

log = logging.getLogger("sere.sere_api")

# URL base do portal SERE.
URL = "https://www.sere.pr.gov.br/sere"

# Endpoints internos usados pelas funções de API abaixo.
URL_API_LISTAR = f"{URL}/gerenciarPastaVirtual.do?action=listarArquivos&cgmAluno="
URL_MUDAR_STATUS = f"{URL}/gerenciarPastaVirtual.do?action=mudarStatus"


async def esta_na_tela_login(page) -> bool:
    """
    Verifica se a página atual é a tela de login do SERE (existência do
    campo #CHAVE). Usado depois de um page.goto(URL) para saber se a sessão
    caiu — nesse caso o SERE exibe o formulário de login em vez do menu.
    """
    try:
        el = await page.query_selector("#CHAVE")
        return el is not None
    except Exception:
        return False


async def garantir_logado(page, login: str, senha: str) -> bool:
    """
    Garante que a página está autenticada no SERE. Se estiver na tela de
    login (sessão caiu/expirou), refaz o login com as credenciais informadas.
    Só então é seguro chamar navegar_por_aluno — chamá-lo direto na tela de
    login falha silenciosamente (o menu #divoCMenu0_0 não existe ali), o que
    antes fazia o script parecer "deslogado" no meio da validação.

    Retorna True se terminou autenticado (já estava ou logou de novo),
    False se a tentativa de relogin falhou.
    """
    if not await esta_na_tela_login(page):
        return True

    log.warning("garantir_logado: sessão caiu, refazendo login…")
    print("     🔑 Sessão caiu — refazendo login…")
    try:
        await page.fill("#CHAVE", login)
        await page.fill("#CHAVE_ENCRIPT", senha)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        if await esta_na_tela_login(page):
            log.error("garantir_logado: ainda na tela de login após tentativa de relogin.")
            return False
        return True
    except Exception as exc:
        log.error(f"garantir_logado: erro ao refazer login: {exc}")
        return False


async def _navegar_consulta_padrao(page, item_submenu: str) -> None:
    """
    Navega pelo menu do SERE até "Consulta Padrão → <item_submenu>".
    Função interna compartilhada por navegar_por_aluno() e
    navegar_por_turma() — o fluxo de menu (mouseover no menu principal
    seguido de dois cliques) é idêntico nos dois casos, só muda o texto do
    item final clicado.

    UNIFICAÇÃO (aprovada pelo usuário em 30/08/2026): turmas.py original
    tinha sua própria navegação quase idêntica (navigate_to_por_turma),
    com tempos de espera ligeiramente menores (500ms/300ms em vez de
    800ms/500ms). Unificado nos tempos mais conservadores de
    navegar_por_aluno (800ms/500ms) para os dois casos — decisão do
    usuário, priorizando robustez sobre velocidade.
    """
    log.info(f"Navegando para: Consulta Padrão → {item_submenu}")
    print(f"📂 Navegando para Consulta Padrão → {item_submenu}…")
    menu = await page.wait_for_selector("#divoCMenu0_0", timeout=15_000)
    await menu.evaluate(
        "el => el.dispatchEvent(new MouseEvent('mouseover', {view: window, bubbles: true, cancelable: true}))"
    )
    await page.wait_for_timeout(800)
    await page.click("//div[contains(text(),'Consulta Padr')]")
    await page.wait_for_timeout(500)
    await page.click(f"//div[contains(text(),'{item_submenu}')]")
    await page.wait_for_timeout(1_500)
    print("✅ Navegação concluída.\n")


async def navegar_por_aluno(page) -> None:
    """Navega pelo menu do SERE até a seção 'Consulta Padrão → Por Aluno'."""
    await _navegar_consulta_padrao(page, "Por Aluno")


async def navegar_por_turma(page) -> None:
    """
    Navega pelo menu do SERE até a seção 'Consulta Padrão → Por Turma'.
    Portado de turmas.py (navigate_to_por_turma) — ver
    src/relatorios/turmas.py para o fluxo completo que usa esta função.
    """
    await _navegar_consulta_padrao(page, "Por Turma")


async def _navegar_menu_topo(page, item_topo: str, rota: tuple[str, ...]) -> None:
    """
    Navega pelo menu do SERE a partir de qualquer item de topo (ex.:
    "Relatórios", "Censo Escolar"), percorrendo os itens de `rota` em
    sequência depois dele.

    Função interna compartilhada por navegar_relatorios() e
    navegar_censo_escolar() — generalizada a partir de navegar_relatorios
    (decisão do usuário, 02/09/2026): o padrão de navegação (mouseover no
    menu principal, clique no item de topo, depois clique em cada item da
    rota) é idêntico entre os menus "Relatórios" e "Censo Escolar" — só
    muda QUAL item de topo é clicado primeiro. Diferente de
    _navegar_consulta_padrao (que é sobre "Consulta Padrão" e tem seus
    próprios tempos de espera calibrados) — mantida separada dessa,
    porque são famílias de menu com histórico de calibração distintos.

    NOTA (20/10/2026): esta função e navegar_censo_escolar existiam só na cópia src/automacao/sere_api.py
    (sem uso); aqui, na cópia que todo o projeto importa, tinham sumido — por isso servidores.py e
    funcionarios.py davam ImportError e a coleta de funcionários nunca rodava. Portadas de volta.
    """
    menu = await page.query_selector("#divoCMenu0_0")
    if not menu:
        raise Exception("Menu principal não encontrado (#divoCMenu0_0)")
    await menu.evaluate(
        "el => el.dispatchEvent(new MouseEvent('mouseover', {view: window, bubbles: true, cancelable: true}))"
    )
    await page.wait_for_timeout(500)

    await page.click(f"//div[contains(text(),'{item_topo}')]")
    await page.wait_for_timeout(300)
    for item in rota:
        await page.click(f"//div[contains(text(),'{item}')]")
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(2_000)


async def navegar_relatorios(page, rota: tuple[str, ...]) -> None:
    """
    Navega pelo menu do SERE a partir de "Relatórios", percorrendo os
    itens de `rota` em sequência (ex.: ("Histórico Escolar", "Emitir") ou
    ("Documentos Oficiais", "Guia de Transferência")).

    Portado de processo_tranferidos.py (_hover_menu + navegar) — decisão do
    usuário em 01/09/2026: função NOVA e distinta de
    _navegar_consulta_padrao/navegar_por_aluno/navegar_por_turma, porque
    aqui o menu de topo é "Relatórios", não "Consulta Padrão" — são dois
    menus diferentes do SERE, então não devem compartilhar a mesma função
    interna. Reaproveitável por qualquer script futuro que precise navegar
    em "Relatórios" (ex.: os 4 atalhos que processo_tranferidos.py monta em
    cima dela: Histórico Escolar → Gravar/Alterar/Emitir, Documentos
    Oficiais → Guia de Transferência).

    Uso:
        await navegar_relatorios(page, ("Histórico Escolar", "Emitir"))
        await navegar_relatorios(page, ("Documentos Oficiais", "Guia de Transferência"))
    """
    await _navegar_menu_topo(page, "Relatórios", rota)


async def navegar_censo_escolar(page, rota: tuple[str, ...]) -> None:
    """
    Navega pelo menu do SERE a partir de "Censo Escolar", percorrendo os
    itens de `rota` em sequência (ex.: ("Funcionário/ Docente", "Consulta
    Funcionários/Docentes")).

    Portado de funcionarios.py (navigate_to_professores) — decisão do
    usuário (02/09/2026): generalizada junto com navegar_relatorios via
    _navegar_menu_topo, já que o padrão de navegação é idêntico, só muda
    qual item de topo é clicado primeiro.

    Uso:
        await navegar_censo_escolar(page, ("Funcionário/ Docente", "Consulta Funcionários/Docentes"))
    """
    await _navegar_menu_topo(page, "Censo Escolar", rota)


async def navegar_pasta_virtual(page, cgm: str) -> bool:
    """
    Abre a pasta virtual de um aluno pelo CGM.
    Retorna True se conseguiu abrir, False em caso de timeout.
    """
    try:
        await page.wait_for_selector("#cgm", timeout=10_000)
    except PlaywrightTimeoutError:
        # A tela de busca por CGM não estava pronta (ex.: ainda em transição
        # da tela anterior). Tenta reforçar a navegação uma vez antes de
        # desistir — evita abortar o modo --validar por uma simples demora
        # de renderização.
        log.warning(f"#cgm não apareceu em 10s, tentando renavegar | CGM={cgm}")
        try:
            await navegar_por_aluno(page)
            await page.wait_for_selector("#cgm", timeout=10_000)
        except PlaywrightTimeoutError:
            log.error(f"Timeout em #cgm mesmo após renavegar | CGM={cgm}")
            return False

    try:
        await page.fill("#cgm", cgm)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2_000)
    except Exception as exc:
        log.error(f"Erro ao preencher/enviar #cgm | CGM={cgm}: {exc}")
        return False

    try:
        turmas_links = await page.query_selector_all("a.texto_normal")
        linhas_turma = await page.query_selector_all(
            "table[bgcolor='#1E3B6D'] tr[bgcolor='#D6EBDF']"
        )
        if turmas_links and len(turmas_links) >= 4 and len(linhas_turma) > 1:
            txt = await turmas_links[0].inner_text()
            log.info(f"Múltiplas turmas — selecionando: '{txt}'")
            await turmas_links[0].click()
            await page.wait_for_timeout(2_000)
    except Exception as e:
        log.warning(f"Erro ao verificar/selecionar turma: {e}")

    try:
        btn = await page.wait_for_selector("input[value='Listar Arquivos']", timeout=8_000)
        await btn.click()
        await page.wait_for_timeout(2_000)
        await page.wait_for_selector("#div_pasta_virtual", timeout=15_000)
        return True
    except PlaywrightTimeoutError:
        log.error(f"Timeout em 'Listar Arquivos' | CGM={cgm}")
        return False


async def buscar_documentos_api(page, cgm: str) -> list[dict]:
    """Consulta listarArquivos e retorna a lista completa de documentos."""
    url = f"{URL_API_LISTAR}{cgm}"
    resultado = await page.evaluate(f"""
        async () => {{
            const resp = await fetch('{url}', {{credentials: 'include'}});
            if (!resp.ok) return null;
            return await resp.json();
        }}
    """)
    if resultado is None:
        log.error(f"API listarArquivos retornou null para CGM={cgm}")
        return []
    log.info(f"API: {len(resultado)} documentos para CGM={cgm}")
    return resultado


async def excluir_arquivo_api(page, cgm: str, assinatura: str) -> bool:
    """Exclui um arquivo via POST mudarStatus. Retorna True se HTTP 2xx."""
    url_listar = f"{URL_API_LISTAR}{cgm}"
    resultado = await page.evaluate(f"""
        async () => {{
            await fetch('{url_listar}', {{credentials: 'include'}});
            const resp = await fetch('{URL_MUDAR_STATUS}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                body: 'assinaturaArquivo={assinatura}&acao=EXCLUIR'
            }});
            return resp.ok;
        }}
    """)
    return bool(resultado)
"""
turmas.py — Coleta de turmas e alunos do SERE
=============================================================================
Portado de AUTO_SERE/turmas.py para src/automacao/turmas.py.

Responsável por percorrer o SERE (Consulta Padrão → Por Turma) e extrair,
para cada turma da escola, a lista de alunos matriculados com seus dados
básicos (CGM, nome, data de nascimento, idade, sexo, situação e data de
matrícula), consolidando tudo em turmas.json — a fonte de dados usada por
praticamente todos os outros scripts do ecossistema (analisa_arquivos_sere,
analisa_documentos_pc, sere_2026, etc.).

Este é o 2º passo do fluxo de primeira configuração descrito pelo usuário
em 29/08/2026: credenciais → CARREGAR TURMAS → escolher pasta de
digitalização → uso de rotina.

ESCOPO DESTA ETAPA (decidido com o usuário em 30/08/2026): só a lógica
principal, sem wrapper de execução-para-GUI ainda (diferente de
sere_2026.py, que já ganhou os wrappers executar_*.py) — mas a função
`coletar_turmas_e_alunos` já é escrita de forma pronta para ser chamada por
um futuro wrapper (ver src/comum/execucao_gui.py), sem argparse, sem
input() interativo, sem asyncio.run() solto fora de main().

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. navigate_to_por_turma() foi REMOVIDA daqui — unificada com
   navegar_por_aluno() em src.comum.sere_api como navegar_por_turma(),
   que reaproveita a mesma navegação de menu compartilhada (mouseover +
   dois cliques). Os tempos de espera (antes 500ms/300ms aqui, 800ms/500ms
   em navegar_por_aluno) foram unificados para os mais conservadores
   (800ms/500ms) — decisão do usuário, priorizando robustez sobre
   velocidade. Nenhuma outra lógica de navegação foi alterada.

2. BASE_DIR: antes fixo em
   "/home/sambauser/compartilhado/ARQUIVOS/ESCOLA JUDITH/PYTHON/SERE/2026"
   (hardcoded para o ano 2026, diferente até de outros scripts do mesmo
   projeto original que calculavam o ano dinamicamente). Agora resolvido
   via src.comum.paths.dados_ano_atual() — <pasta_de_instalação>/dados/<ano>/,
   com o ano calculado automaticamente (ver src.comum.paths.ano_atual()).

3. Credenciais e logger: antes `from credenciais import LOGIN, SENHA` e
   `from logger import get_logger` (imports de módulo solto na mesma
   pasta). Agora `from src.comum.credenciais import LOGIN, SENHA` e
   `from src.comum.logger import get_logger`.

4. main() foi RENOMEADA para coletar_turmas_e_alunos_via_login(), que
   também assumiu a responsabilidade de abrir e fechar o browser (que
   antes era feita separadamente dentro do antigo main()) — juntando as
   duas etapas do fluxo original (login e coleta) numa única função
   pronta para ser chamada de fora, sem precisar montar o browser
   manualmente antes de cada chamada. A função interna
   coletar_turmas_e_alunos(page, output_file) foi preservada com o mesmo
   nome e a mesma assinatura do original, para quem já orquestra o
   browser por conta própria (ex.: um fluxo que já tem uma `page` aberta,
   como os modos de sere_2026.py) poder chamá-la diretamente.

5. CORREÇÃO (22/10/2026) — aluno que retorna após transferência: o mesmo
   CGM aparece duas vezes na turma (Transferido + Matriculado, datas de
   movimentação diferentes). Cada turma passa por
   src.comum.registros_aluno.consolidar_registros(): mantém os dois
   cadastros, usa (CGM, Situação, Data Matricula, N) como identidade do
   registro (o nº da chamada é o validador secundário), descarta apenas
   leitura repetida e marca o matriculado posterior com "Retorno": True.

Toda a lógica de scraping em si (seletores, extração de colunas, retry de
3 tentativas por turma, filtro de turmas "sem seriação") é idêntica ao
original — nenhuma regra de negócio foi alterada.

Uso:
    import asyncio
    from src.automacao.turmas import coletar_turmas_e_alunos_via_login

    asyncio.run(coletar_turmas_e_alunos_via_login())
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum.logger import get_logger
from src.comum import paths as _paths
from src.comum.registros_aluno import consolidar_registros
from src.comum.sere_api import URL, navegar_por_turma
from src.comum import navegador as _navegador

log = get_logger(__file__)

if not LOGIN or not SENHA:
    raise ValueError("Configure LOGIN e SENHA em credenciais/.env (ver .env.example)")

# Pasta de dados de trabalho do ano letivo corrente — antes fixo em
# BASE_DIR = "/home/sambauser/.../SERE/2026" (hardcoded para 2026, mesmo
# diferindo de outros scripts do projeto original que já calculavam o ano
# dinamicamente). Ver decisão do usuário registrada no docstring acima.
_DADOS = _paths.dados_ano_atual()

TURMAS_JSON = _DADOS / "turmas.json"


# =========================
# TURMAS
# =========================
async def get_turmas_validas(page) -> list[str]:
    """Coleta a lista de turmas válidas exibidas na tabela (ignora 'SEM SERIA...')."""
    log.info("Buscando linhas de turmas na página...")
    turmas: list[str] = []

    rows = await page.query_selector_all(
        "//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]"
    )
    log.info(f"{len(rows)} linha(s) de turma encontrada(s) no DOM.")

    for i, r in enumerate(rows):
        cols = await r.query_selector_all("td")
        if len(cols) < 4:
            log.warning(f"Linha {i+1} ignorada: menos de 4 colunas ({len(cols)} encontradas).")
            continue

        serie = (await cols[1].inner_text()).strip()
        turno = (await cols[2].inner_text()).strip()
        letra = (await cols[3].inner_text()).strip()

        if "SEM SERIA" in serie.upper():
            log.info(f"[IGNORADO] Turma sem seriação: '{serie} {turno} {letra}'")
            continue

        turma_id = f"{serie} {turno} {letra}"
        if turma_id not in turmas:
            turmas.append(turma_id)
            log.info(f"Turma válida adicionada: '{turma_id}'")
        else:
            log.debug(f"Turma duplicada ignorada: '{turma_id}'")

    log.info(f"Total de turmas válidas encontradas: {len(turmas)}")
    return turmas


# =========================
# ALUNOS (ROBUSTO)
# =========================
async def get_alunos_da_turma(page, turma_id: str, tentativas: int = 3) -> tuple[str, list[dict]]:
    """
    Coleta os alunos de uma turma, com até `tentativas` novas tentativas em
    caso da tabela não carregar. Relocaliza a linha da turma a cada
    tentativa (a lista é recarregada após cada navegação — reaproveitar
    uma referência antiga de elemento causaria erro de "elemento
    destacado do DOM").
    """
    alunos: list[dict] = []

    for tentativa in range(1, tentativas + 1):
        log.info(f"[{turma_id}] Tentativa {tentativa}/{tentativas}: recarregando lista de turmas...")

        rows = await page.query_selector_all(
            "//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]"
        )
        log.info(f"[{turma_id}] {len(rows)} linha(s) de turma encontrada(s).")

        target = None
        for r in rows:
            cols = await r.query_selector_all("td")
            if len(cols) < 4:
                continue

            serie = (await cols[1].inner_text()).strip()
            turno = (await cols[2].inner_text()).strip()
            letra = (await cols[3].inner_text()).strip()

            if f"{serie} {turno} {letra}" == turma_id:
                target = r
                break

        if not target:
            log.error(f"[{turma_id}] Turma não encontrada na lista. Abortando coleta desta turma.")
            return turma_id, alunos

        log.info(f"[{turma_id}] Turma localizada. Buscando link e clicando...")
        link = await target.query_selector("td:nth-child(2) a")
        if not link:
            log.error(f"[{turma_id}] Link da turma não encontrado na linha.")
            return turma_id, alunos

        await link.click()
        log.info(f"[{turma_id}] Link clicado. Aguardando tabela de alunos (table#tb_alunos)...")

        try:
            await page.wait_for_selector("table#tb_alunos tbody tr", timeout=20_000)
            log.info(f"[{turma_id}] Tabela de alunos carregada.")
        except Exception:
            log.warning(f"[{turma_id}] Tabela não carregou na tentativa {tentativa}/{tentativas}. Voltando...")
            await page.go_back()
            await page.wait_for_timeout(1_500)
            continue

        linhas = await page.query_selector_all("table#tb_alunos tbody tr")
        log.info(f"[{turma_id}] {len(linhas)} linha(s) encontrada(s) na tabela de alunos.")

        alunos.clear()

        for idx, l in enumerate(linhas):
            cols = await l.query_selector_all("td")
            if len(cols) < 8:
                log.debug(f"[{turma_id}] Linha {idx+1} ignorada: apenas {len(cols)} coluna(s).")
                continue

            n = (await cols[0].inner_text()).strip()
            if not n.isdigit():
                log.debug(f"[{turma_id}] Linha {idx+1} ignorada: coluna N não é número ('{n}').")
                continue

            cgm_el = await cols[1].query_selector("a")
            if not cgm_el:
                log.debug(f"[{turma_id}] Linha {idx+1} ignorada: CGM sem link.")
                continue

            aluno = {
                "N":              int(n),
                "CGM":            (await cgm_el.inner_text()).strip(),
                "Nome":           (await cols[2].inner_text()).strip(),
                "Data Nasc.":     (await cols[3].inner_text()).strip(),
                "Idade":          int((await cols[4].inner_text()).strip()),
                "Sexo":           (await cols[5].inner_text()).strip(),
                "Situação":       (await cols[6].inner_text()).strip(),
                "Data Matricula": (await cols[7].inner_text()).strip(),
            }
            alunos.append(aluno)
            log.debug(f"[{turma_id}] Aluno {aluno['N']} adicionado: {aluno['Nome']} (CGM {aluno['CGM']})")

        # Aluno que foi transferido e voltou aparece 2x com o mesmo CGM (Transferido +
        # Matriculado, datas diferentes): mantém os dois cadastros, descarta só leitura
        # repetida e marca o retorno (ver src.comum.registros_aluno).
        alunos = consolidar_registros(alunos, rotulo=turma_id)

        log.info(f"[{turma_id}] {len(alunos)} aluno(s) coletado(s). Voltando para lista de turmas...")

        voltar = await page.query_selector("#btnVoltar")
        if voltar:
            log.info(f"[{turma_id}] Clicando em #btnVoltar...")
            await voltar.click()
        else:
            log.info(f"[{turma_id}] Botão #btnVoltar não encontrado, usando page.go_back()...")
            await page.go_back()

        await page.wait_for_timeout(1_500)

        if alunos:
            log.info(f"[{turma_id}] Coleta concluída com sucesso: {len(alunos)} aluno(s).")
            return turma_id, alunos

        log.warning(f"[{turma_id}] Lista de alunos voltou vazia. Repetindo tentativa {tentativa}/{tentativas}...")

    log.error(f"[{turma_id}] Todas as {tentativas} tentativas falharam. Retornando lista vazia.")
    return turma_id, alunos


# =========================
# COLETA GERAL
# =========================
async def coletar_turmas_e_alunos(page, output_file: Path = TURMAS_JSON) -> dict[str, list[dict]]:
    """
    Orquestra a coleta completa: navega até 'Por Turma', coleta a lista de
    turmas válidas, e para cada uma delas coleta os alunos, salvando o
    resultado consolidado em `output_file` (turmas.json, por padrão).

    Assume que `page` já está autenticada no SERE — quem só quer disparar
    a coleta completa (login + coleta) deve chamar
    coletar_turmas_e_alunos_via_login() em vez desta função diretamente.

    Retorna o dicionário { nome_turma: [alunos] } também em memória, além
    de salvá-lo em disco.
    """
    log.info("=== Iniciando coleta geral de turmas e alunos ===")
    await navegar_por_turma(page)

    turmas = await get_turmas_validas(page)
    log.info(f"Encontradas {len(turmas)} turma(s) válida(s). Iniciando coleta de alunos...")

    resultado: dict[str, list[dict]] = {}

    for i, turma in enumerate(turmas, start=1):
        log.info(f"--- Coletando turma {i}/{len(turmas)}: '{turma}' ---")
        nome, alunos = await get_alunos_da_turma(page, turma)
        resultado[nome] = alunos
        log.info(f"Turma '{nome}' finalizada → {len(alunos)} aluno(s).")

    log.info(f"Todas as turmas coletadas. Salvando JSON em '{output_file}'...")
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=4)
        log.info(f"JSON salvo com sucesso em '{output_file}'.")
    except OSError as exc:
        log.error(f"ERRO ao salvar JSON: {exc}")
        raise

    # Registra todos os transferidos em fila_transferidos.json (a base do processo de transferidos).
    # Nunca levanta exceção: a coleta já está salva e não pode ser afetada.
    from src.automacao.fila_transferidos import registrar_fila_sem_falhar
    registrar_fila_sem_falhar(resultado, dados_dir=output_file.parent)

    log.info("=== Coleta geral finalizada ===")
    return resultado


# =========================
# LOGIN + COLETA (ponto de entrada pronto para uma futura GUI)
# =========================
async def coletar_turmas_e_alunos_via_login(output_file: Path = TURMAS_JSON) -> dict[str, list[dict]]:
    """
    Ponto de entrada completo: abre o navegador, faz login no SERE, coleta
    todas as turmas e alunos, salva em `output_file` e fecha o navegador.

    Escrita para ser chamável diretamente por um futuro botão de interface
    gráfica (ex.: via src.comum.execucao_gui.ExecucaoEmBackground, do
    mesmo jeito que os modos de sere_2026.py) — não usa argparse, não lê
    sys.argv, não pede input() interativo. Ainda não tem um wrapper
    executar_turmas.py dedicado (escopo desta etapa foi só a lógica,
    conforme decisão do usuário em 30/08/2026), mas a função já está no
    formato certo para ganhar um quando for necessário.

    Retorna o dicionário { nome_turma: [alunos] } coletado.
    """
    log.info("=== Script iniciado ===")
    log.info("Iniciando Playwright...")
    async with async_playwright() as p:
        log.info("Playwright iniciado. Abrindo browser Chromium (headless)...")
        browser = await _navegador.lancar(p, "chromium", True)
        log.info("Browser aberto. Criando nova página...")
        page = await browser.new_page()
        log.info(f"Acessando URL: {URL}")
        await page.goto(URL)
        log.info("Página carregada. Preenchendo credenciais...")
        await page.fill("#CHAVE", LOGIN)
        log.info("Campo LOGIN preenchido.")
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        log.info("Campo SENHA preenchido. Clicando em 'Entrar'...")
        await page.click("//input[@value='Entrar']")
        log.info("Login enviado. Aguardando carregamento pós-login (3s)...")
        await page.wait_for_timeout(3_000)
        log.info("Carregamento concluído. Iniciando coleta...")

        resultado = await coletar_turmas_e_alunos(page, output_file=output_file)

        log.info("Coleta finalizada! Fechando browser...")
        await browser.close()
        log.info("Browser fechado. Script encerrado com sucesso.")

    return resultado


if __name__ == "__main__":
    import asyncio
    asyncio.run(coletar_turmas_e_alunos_via_login())

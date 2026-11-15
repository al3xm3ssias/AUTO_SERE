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

7. CORREÇÃO (22/10/2026) — aluno que retorna após transferência: o mesmo
   CGM aparece em duas linhas da turma (Transferido + Matriculado, datas
   diferentes). Antes, get_dados_aluno() localizava o link por CGM
   (//td[a/text()='<cgm>']/a) e SEMPRE clicava na primeira linha — o cadastro
   do aluno retornado saía duplicado a partir da linha antiga, e nada
   distinguia os dois. Agora o clique é feito na PRÓPRIA linha (por índice),
   cada cadastro recebe N, Situação e Data Matricula da linha de origem, e a
   lista da turma passa por src.comum.registros_aluno.consolidar_registros()
   (mantém transferido + matriculado, usa o nº da chamada como validador
   secundário, descarta só leitura repetida e marca "Retorno": True).

8. CORREÇÃO (10/11/2026) — Page.go_back: net::ERR_CACHE_MISS ao voltar da
   lista de alunos para a lista de turmas (ver _voltar_para_lista_turmas()):
   o botão correto da lista de alunos é #btnVoltar (a ficha continua com
   input Voltar — seletores separados por tela); o go_back() agora é só fallback e, se
   falhar por cache miss, a navegação até 'Por Turma' é refeita.

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

from playwright.async_api import Error as PlaywrightError, async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum.logger import get_logger
from src.comum import paths as _paths
from src.comum.registros_aluno import consolidar_registros
from src.comum.sere_api import URL, garantir_logado, navegar_por_turma
from src.comum import navegador as _navegador

log = get_logger(__file__)

if not LOGIN or not SENHA:
    raise ValueError("Configure LOGIN e SENHA em credenciais/.env (ver .env.example)")

# Pasta de dados de trabalho do ano letivo corrente — antes fixo em
# BASE_DIR = f"/home/sambauser/.../SERE/{ANO_BASE}" com ano_atual() local
# (mesma lógica de src.comum.paths.ano_atual(), agora centralizada lá).
_DADOS = _paths.dados_ano_atual()

ALUNOS_JSON = _DADOS / "alunos.json"


# Botões "Voltar" por tela — a ORDEM IMPORTA e não pode ser compartilhada:
# - ficha cadastral do aluno: <input value="Voltar"> volta para a lista de
#   alunos da turma. Ali o #btnVoltar (se existir) leva para a lista de
#   TURMAS, voltando "demais" e quebrando o restante do loop.
# - lista de alunos da turma: #btnVoltar volta para a lista de turmas
#   (mesmo seletor de src.automacao.turmas).
_VOLTAR_FICHA = ("//input[@value='Voltar']",)
_VOLTAR_LISTA_ALUNOS = ("#btnVoltar", "input[name='btnVoltar']", "//input[@value='Voltar']")


async def _clicar_voltar(page, seletores) -> bool:
    """Clica no primeiro botão 'Voltar' encontrado entre `seletores`. False se nenhum existir."""
    for seletor in seletores:
        botao = await page.query_selector(seletor)
        if botao:
            await botao.click()
            return True
    return False


async def _voltar_para_lista_turmas(page, turma_id: str) -> None:
    """
    Volta da lista de alunos da turma para a lista de turmas.

    CORREÇÃO (10/11/2026): o código antigo procurava só
    //input[@value='Voltar']; na lista de alunos o botão é #btnVoltar, então
    caía em page.go_back(). Como essa tela é resultado de um POST, o Chromium
    não tem a página em cache e go_back() estoura
    "net::ERR_CACHE_MISS". Agora: (1) tenta os botões Voltar conhecidos;
    (2) só então tenta go_back(); (3) se o go_back falhar por cache miss,
    refaz a navegação 'Consulta Padrão → Por Turma' em vez de abortar.
    """
    if await _clicar_voltar(page, _VOLTAR_LISTA_ALUNOS):
        await page.wait_for_timeout(500)
        return

    log.warning(f"[{turma_id}] Botão Voltar não encontrado; tentando page.go_back()...")
    try:
        await page.go_back()
        await page.wait_for_timeout(500)
        return
    except PlaywrightError as e:
        if "ERR_CACHE_MISS" not in str(e):
            raise
        log.warning(f"[{turma_id}] go_back() falhou (ERR_CACHE_MISS); refazendo navegação até 'Por Turma'...")

    try:
        await navegar_por_turma(page)
    except Exception as e:
        # A página pode ter ido para a tela de erro do navegador — recarrega o
        # SERE, garante o login e navega de novo.
        log.warning(f"[{turma_id}] Navegação direta falhou ({e}); recarregando o SERE...")
        await page.goto(URL)
        await garantir_logado(page, LOGIN, SENHA)
        await navegar_por_turma(page)
    await page.wait_for_timeout(1000)


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


async def get_dados_aluno(page, cgm: str, linha=None) -> dict:
    """
    Abre a ficha cadastral do aluno (clicando no CGM) e extrai o cadastro
    completo campo a campo via XPath. Falha em um aluno é logada e não
    interrompe a coleta dos demais (sem retry — ver limitações no docstring
    do módulo).

    `linha` é o locator da linha do aluno na tabela da turma. Quando
    informado, o clique é feito no link DESSA linha — necessário quando o
    mesmo CGM aparece em duas linhas (transferido + retorno). Sem `linha`,
    mantém o comportamento antigo (primeiro link com aquele CGM).
    """
    aluno_data: dict = {}

    try:
        if linha is not None:
            link = linha.locator("a[href^='javascript:AoClicarAluno']").first
            if await link.count() == 0:
                # Sem o link na linha a página não é a lista da turma: sinaliza
                # para o chamador reabrir a turma (ver get_alunos_da_turma).
                raise RuntimeError(f"CGM {cgm}: link não encontrado na linha")
        else:
            link = await page.query_selector(f"//td[a/text()='{cgm}']/a")
            if not link:
                print(f"[AVISO] CGM {cgm} não encontrado")
                return aluno_data

        await link.click(timeout=15_000)
        # Mesma espera do original (1s) — NÃO trocar por wait_for_selector de
        # um campo da ficha: o campo "Nome" já satisfaz a espera na página
        # antiga, antes da navegação terminar, e a leitura começa no meio da
        # troca de página ("Execution context was destroyed").
        await page.wait_for_timeout(1000)
        await page.wait_for_load_state("domcontentloaded")

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

        if not await _clicar_voltar(page, _VOLTAR_FICHA):
            await page.go_back()
        await page.wait_for_timeout(500)
        # Garante que voltou para a lista de alunos da turma antes do próximo aluno.
        await page.wait_for_selector(
            "//table//tr[td/a[contains(@href,'javascript:AoClicarAluno')]]", timeout=15_000
        )

    except Exception as e:
        # Não engole mais o erro: o chamador (get_alunos_da_turma) precisa saber
        # que a ficha falhou para refazer a navegação e tentar o aluno de novo.
        print(f"[ERRO] Falha ao coletar dados do CGM {cgm}: {e}")
        raise

    return aluno_data


async def _ler_meta_linha(linha) -> dict:
    """
    Lê da linha da tabela da turma os dados da MOVIMENTAÇÃO (N, Situação e
    Data Matricula) — mesmas colunas usadas em src.automacao.turmas
    (0=N, 6=Situação, 7=Data). Devolve {} se a linha não tiver as colunas.
    """
    tds = linha.locator("td")
    if await tds.count() < 8:
        return {}
    n_txt = (await tds.nth(0).inner_text()).strip()
    meta = {
        "Situação": (await tds.nth(6).inner_text()).strip(),
        "Data Matricula": (await tds.nth(7).inner_text()).strip(),
    }
    if n_txt.isdigit():
        meta["N"] = int(n_txt)
    return meta


_XPATH_LINHAS_ALUNOS = "//table//tr[td/a[contains(@href,'javascript:AoClicarAluno')]]"
_XPATH_LINHAS_TURMAS = "//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]"

# Tentativas por aluno antes de desistir dele e seguir para o próximo, e limite
# de falhas na turma inteira antes de abandoná-la (evita loop infinito).
MAX_TENTATIVAS_ALUNO = 3
MAX_FALHAS_TURMA = 12
MAX_TENTATIVAS_ABRIR_TURMA = 3


async def _abrir_turma(page, turma_id: str) -> bool:
    """
    Com a lista de turmas na tela, clica na turma `turma_id` e espera a lista
    de alunos aparecer. False se a turma não está na página; exceção se o
    clique ou a espera falharem.
    """
    rows = await page.query_selector_all(_XPATH_LINHAS_TURMAS)
    for r in rows:
        colunas = await r.query_selector_all("td")
        if len(colunas) < 4:
            continue
        serie = (await colunas[1].inner_text()).strip()
        turno = (await colunas[2].inner_text()).strip()
        letra = (await colunas[3].inner_text()).strip()
        if f"{serie} {turno} {letra}" != turma_id:
            continue
        link = await r.query_selector("a[href^='javascript:AoClicarTurma']")
        if not link:
            return False
        await link.click(timeout=15_000)
        await page.wait_for_selector(_XPATH_LINHAS_ALUNOS, timeout=20_000)
        return True
    return False


async def _reabrir_turma(page, turma_id: str) -> bool:
    """
    RECUPERAÇÃO: refaz Menu → Consulta Padrão → Por Turma e reabre a turma.
    Se o menu não estiver acessível (página de erro / sessão caída), recarrega
    o SERE, refaz o login se preciso e navega de novo.
    """
    log.warning(f"[{turma_id}] Recuperando: Menu → Consulta Padrão → Por Turma...")
    try:
        try:
            await navegar_por_turma(page)
        except Exception as e:
            log.warning(f"[{turma_id}] Menu indisponível ({type(e).__name__}); recarregando o SERE...")
            await page.goto(URL)
            await page.wait_for_timeout(1_500)
            await garantir_logado(page, LOGIN, SENHA)
            await navegar_por_turma(page)
        await page.wait_for_selector(_XPATH_LINHAS_TURMAS, timeout=20_000)
        return await _abrir_turma(page, turma_id)
    except Exception as e:
        log.error(f"[{turma_id}] Falha na recuperação: {type(e).__name__}: {e}")
        return False


async def _abrir_turma_com_recuperacao(page, turma_id: str) -> bool:
    """Abre a turma; na falha, refaz a navegação até 'Por Turma' e tenta de novo."""
    for tentativa in range(1, MAX_TENTATIVAS_ABRIR_TURMA + 1):
        if tentativa == 1:
            try:
                if await _abrir_turma(page, turma_id):
                    return True
                print(f"[AVISO] Não encontrou a turma {turma_id}")
            except Exception as e:
                log.warning(f"[{turma_id}] Falha ao abrir a turma ({type(e).__name__}): {e}")
        elif await _reabrir_turma(page, turma_id):
            return True
        log.warning(f"[{turma_id}] Abertura da turma falhou (tentativa {tentativa}/{MAX_TENTATIVAS_ABRIR_TURMA}).")
    return False


async def get_alunos_da_turma(page, turma_id: str) -> tuple[str, list[dict]]:
    """
    Abre a turma pelo `turma_id` e coleta o cadastro completo de todos os
    seus alunos (um clique no CGM por aluno, voltando à lista de alunos da
    turma a cada ficha e à lista de turmas só no fim).

    RECUPERAÇÃO (10/11/2026): se qualquer passo falhar (timeout, "Execution
    context was destroyed", ficha que não abre...), em vez de abortar o
    script refaz Menu → Consulta Padrão → Por Turma, reabre a turma e RETOMA
    do aluno em que parou (os já coletados são mantidos). Cada aluno tem até
    MAX_TENTATIVAS_ALUNO tentativas; esgotadas, ele é pulado (logado como
    erro) e a coleta segue. A turma é abandonada após MAX_FALHAS_TURMA falhas.
    """
    alunos: list[dict] = []

    if not await _abrir_turma_com_recuperacao(page, turma_id):
        log.error(f"[{turma_id}] Não foi possível abrir a turma. Pulando.")
        return turma_id, alunos

    i = 0
    tentativas_aluno = 0
    falhas_turma = 0

    while True:
        try:
            aluno_rows = page.locator(_XPATH_LINHAS_ALUNOS)
            await page.wait_for_selector(_XPATH_LINHAS_ALUNOS, timeout=15_000)
            if i >= await aluno_rows.count():
                break  # todos os alunos da turma processados

            linha = aluno_rows.nth(i)
            cgm_link = linha.locator("a[href^='javascript:AoClicarAluno']")
            cgm = (await cgm_link.inner_text(timeout=15_000)).strip()
            meta = await _ler_meta_linha(linha)  # lido ANTES do clique (a página muda depois)
            dados_aluno = await get_dados_aluno(page, cgm, linha=linha)
            if dados_aluno:
                dados_aluno.update(meta)
                alunos.append(dados_aluno)
            # NÃO volta à lista de turmas aqui — só depois que acabar o loop
            i += 1
            tentativas_aluno = 0

        except Exception as e:
            tentativas_aluno += 1
            falhas_turma += 1
            log.warning(
                f"[{turma_id}] Falha no aluno nº {i + 1} "
                f"(tentativa {tentativas_aluno}/{MAX_TENTATIVAS_ALUNO}): {type(e).__name__}: {e}"
            )
            if falhas_turma >= MAX_FALHAS_TURMA:
                log.error(f"[{turma_id}] {falhas_turma} falhas na turma — abandonando o restante dela.")
                break
            if tentativas_aluno >= MAX_TENTATIVAS_ALUNO:
                log.error(f"[{turma_id}] Aluno nº {i + 1} pulado após {MAX_TENTATIVAS_ALUNO} tentativas.")
                i += 1
                tentativas_aluno = 0
            if not await _reabrir_turma(page, turma_id):
                log.error(f"[{turma_id}] Não foi possível reabrir a turma — encerrando a coleta dela.")
                break
            log.info(f"[{turma_id}] Turma reaberta; retomando do aluno nº {i + 1}.")

    alunos = consolidar_registros(alunos, rotulo=turma_id)

    await _voltar_para_lista_turmas(page, turma_id)

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
        browser = await _navegador.lancar(p, "chromium", True)
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

    from src.comum import backup as _backup
    _backup.backup_apos_coleta("alunos", log.info)
    return resultado


if __name__ == "__main__":
    import asyncio
    asyncio.run(coletar_alunos_via_login())
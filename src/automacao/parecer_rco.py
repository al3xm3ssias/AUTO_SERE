"""
parecer_rco.py (portado de gerar_pareceres_infantil.py para src/automacao/)

Automatiza o RCDIG (Registro de Classe Digital — SEED/PR) para baixar os pareceres (PDF) de todos
os alunos com Situação == "Matriculado" nas turmas de Infantil IV e Infantil V.

Fluxo:
  1. Login na Central de Segurança (CPF/Login Sentinela + senha);
  2. o RCO envia um código de verificação (2FA) por e-mail → a interface abre uma caixa e pede o
     código ao usuário (no original era um input() no terminal);
  3. menu Estabelecimento > Relatórios > Consultar Aluno, com o período letivo;
  4. para cada aluno (CGM): solicita o parecer, espera o processamento, baixa o PDF.

Ponto de entrada (sem argparse/sys.argv; pronto para virar botão de GUI):

  gerar_pareceres_infantil_via_login(bimestre="2", modo_teste=False, mostrar_navegador=False)

    bimestre            "2" ou "4" — define a subpasta de destino (antes: pergunta no terminal)
    modo_teste=True     processa só o primeiro aluno
    mostrar_navegador   abre a janela do navegador (antigo --no-headless); padrão: escondido

Credenciais: src.comum.credenciais.LOGIN_RCO / SENHA_RCO — por padrão as mesmas do SERE; Configurações →
"Senha do RCO" permite salvar um login/senha próprios.

Destino dos PDFs: dados/<ano>/PARECERES INFANTIL/<N>º Bimestre/<turma>/<nº chamada> - <nome>.pdf
(o original gravava em M:\\ARQUIVOS\\ESCOLA JUDITH\\<ano>\\PARECERES INFANTIL\\<bimestre>; para voltar a
gravar numa pasta de rede, defina AUTO_SERE_PARECERES_INFANTIL_DIR — o bimestre vira uma subpasta dela).

Diferenças em relação ao script original:
  - O código do 2FA vem da tela (src.comum.entrada_usuario), não do terminal; sem resposta em 10 minutos
    a execução termina com uma mensagem clara. Na linha de comando continua sendo input().
  - Lê turmas.json de dados/<ano>/ (o original recebia --turmas); o ano vem de paths.ano_atual().
  - O destino dos PDFs é um parâmetro (o original usava a variável global DOWNLOAD_DIR).
  - Arquivos de diagnóstico (captura de tela, HTML, log de rede) só são gravados quando o login FALHA, em
    dados/<ano>/debug_rco/. O original gravava sempre, inclusive os cookies da sessão com os valores — que
    dão acesso à conta. Agora o log de rede não guarda a query das URLs (têm o code do OAuth) e a lista de
    cookies guarda só nome e domínio.
  - Tela do 2FA que não aparece (senha errada) e campo do código ausente viram erros claros em vez de timeout.
  - Devolve um resumo (baixados e falhas); o original só imprimia.
  - Cancelamento cooperativo a cada aluno; o navegador é sempre fechado.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.comum import entrada_usuario, paths
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.logger import get_logger
from src.comum import navegador as _navegador

log = get_logger(__file__)

CHAVE = "parecer_rco"          # chave da automação (liga o pedido do código à execução certa)

LOGIN_URL = (
    "https://auth-cs.identidadedigital.pr.gov.br/centralautenticacao/login.html?"
    "response_type=code&client_id=f340f1b1f65b6df5b5e3f94d95b11daf&"
    "redirect_uri=https%3A%2F%2Fwww.rcomunicipios.pr.gov.br%2Frcdig&"
    "scope=&state=1784033933391&urlCert=https://certauth-cs.identidadedigital.pr.gov.br&"
    "dnsCidadao=https://cidadao-cs.identidadedigital.pr.gov.br/centralcidadao&"
    "loginPadrao=btnCentral&labelCentral=CPF,Login%20Sentinela&"
    "modulosDeAutenticacao=btnSentinela,btnCpf,btnCentral&"
    "urlLogo=https%3A%2F%2Fwww.registrodeclasse.seed.pr.gov.br%2Frcdig%2Fimages%2Flogo_sistema.png&"
    "acesso=2113&tokenFormat=jwt&exibirLinkAutoCadastro=true&exibirLinkRecuperarSenha=true&"
    "exibirLinkAutoCadastroCertificado=false&exibirAviso=true&captcha=false"
)

PORTAL_URL = "https://www.rcomunicipios.pr.gov.br/rcdig/entrada.do?"

# aceita "Infantil IV", "Infantil 4", "INFANTIL V", "Infantil 5" etc.
PADRAO_TURMA_ALVO = re.compile(r"infantil\s*(iv|v|4|5)\b", re.IGNORECASE)

BIMESTRES = {"2": "2º Bimestre", "4": "4º Bimestre"}

_PLACEHOLDERS_LOGIN = {"", "cpf"}
_PLACEHOLDERS_SENHA = {"", "senha_sere"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# ───────────────────────────── preparação (sem navegador) ─────────────────────────────

def periodo_letivo_atual() -> str:
    """
    Value do <option> do período letivo a partir do ano (padrão do select: 2026-1 → 261).
    O ano vem de paths.ano_atual(), que respeita AUTO_SERE_ANO_BASE.
    """
    return f"{str(paths.ano_atual())[-2:]}1"


def rotulo_bimestre(valor) -> str:
    """'2' / '4' (também '2º', '4º Bimestre') → '2º Bimestre' / '4º Bimestre'. ValueError se for outro valor."""
    m = re.fullmatch(r"\s*([24])\s*[º°o]?\s*(?:bimestre)?\s*", str(valor or ""), flags=re.IGNORECASE)
    if not m:
        raise ValueError("Escolha o bimestre: 2º ou 4º.")
    return BIMESTRES[m.group(1)]


def pasta_destino(ano: str, bimestre_label: str) -> Path:
    """Pasta onde os pareceres do bimestre são salvos (ver a docstring do módulo)."""
    base = os.getenv("AUTO_SERE_PARECERES_INFANTIL_DIR", "").strip()
    if base:
        return Path(base) / bimestre_label
    return paths.DADOS_DIR / str(ano) / "PARECERES INFANTIL" / bimestre_label


def credenciais_rco() -> tuple[str, str]:
    """(login, senha) do RCO. ValueError com mensagem pronta se ainda não foram configuradas."""
    from src.comum import credenciais
    login, senha = str(credenciais.LOGIN_RCO or "").strip(), str(credenciais.SENHA_RCO or "")
    if login in _PLACEHOLDERS_LOGIN or senha in _PLACEHOLDERS_SENHA:
        raise ValueError(
            "Credenciais do RCO não configuradas: salve o login e a senha do SERE (o RCO usa os mesmos) "
            "ou os do RCO em Configurações → Senha do RCO."
        )
    return login, senha


def arquivo_turmas() -> Path:
    return paths.dados_ano_atual() / "turmas.json"


def carregar_turmas() -> dict:
    """turmas.json do ano ({turma: [alunos]}). ValueError se ainda não existir."""
    caminho = arquivo_turmas()
    if not caminho.exists():
        raise ValueError("Ainda não existe turmas.json: execute primeiro a automação 'Turmas'.")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Não consegui ler {caminho}: {exc}") from exc
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho} não está no formato esperado ({{turma: [alunos]}}).")
    return dados


def carregar_alunos_alvo(turmas: dict) -> list[dict]:
    """
    A partir de turmas.json ({"NOME DA TURMA": [aluno, ...]}), só os alunos de Infantil IV/V com
    Situação == Matriculado e CGM preenchido.
    """
    alunos = []
    for turma_nome, lista_alunos in turmas.items():
        if not PADRAO_TURMA_ALVO.search(turma_nome):
            continue
        for aluno in lista_alunos:
            situacao = str(aluno.get("Situação") or aluno.get("Situacao") or aluno.get("Situacão") or "").strip()
            if situacao.lower() != "matriculado":
                continue
            cgm = str(aluno.get("CGM", "")).strip()
            if not cgm:
                continue
            alunos.append({
                "cgm": cgm,
                "nome": aluno.get("Nome", ""),
                "turma": turma_nome,
                "n_chamada": aluno.get("N"),
            })
    return alunos


def validar_pedido(bimestre) -> None:
    """Tudo o que dá para conferir ANTES de abrir o navegador (ValueError = mensagem pronta)."""
    rotulo_bimestre(bimestre)
    credenciais_rco()
    if not carregar_alunos_alvo(carregar_turmas()):
        raise ValueError("Nenhum aluno Matriculado encontrado nas turmas de Infantil IV/V em turmas.json.")


# ───────────────────────────── diagnóstico do login ─────────────────────────────

def _sem_query(url: str) -> str:
    """A query das URLs do login traz o code/state do OAuth: não vai para arquivo."""
    return str(url).split("?", 1)[0]


def _pasta_debug() -> Path:
    return paths.dados_ano_atual() / "debug_rco"


async def _salvar_evidencias(page: Page, rede_log: list[str], prefixo: str) -> Path:
    pasta = _pasta_debug()
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(pasta / f"{prefixo}.png"), full_page=True)
        (pasta / f"{prefixo}.html").write_text(await page.content(), encoding="utf-8")
    except Exception:                                   # noqa: BLE001 — diagnóstico nunca derruba o fluxo
        pass
    (pasta / "network_log.txt").write_text("\n".join(rede_log), encoding="utf-8")
    try:
        cookies = await page.context.cookies()
        resumo = [{"name": c.get("name"), "domain": c.get("domain")} for c in cookies]   # sem os valores
        (pasta / "cookies_nomes.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass
    return pasta


def _validar_codigo(valor: str) -> None:
    limpo = "".join(str(valor).split())
    if not re.fullmatch(r"[A-Za-z0-9]{4,12}", limpo):
        raise ValueError("O código tem de 4 a 12 letras/números (normalmente 6 dígitos). Confira o e-mail.")


# ───────────────────────────── navegação no RCDIG ─────────────────────────────

async def fazer_login(page: Page, login: str, senha: str, chave: str = CHAVE) -> None:
    """Login + 2FA por e-mail. O código é pedido ao usuário (tela ou terminal). RuntimeError se falhar."""
    rede_log: list[str] = []

    def _log_response(response):
        try:
            rede_log.append(f"{response.status} {response.request.method} {_sem_query(response.url)}")
        except Exception:                               # noqa: BLE001
            pass

    page.on("response", _log_response)
    try:
        await _login_e_2fa(page, login, senha, chave, rede_log)
    finally:
        page.remove_listener("response", _log_response)


async def _login_e_2fa(page: Page, login: str, senha: str, chave: str, rede_log: list[str]) -> None:
    print("Acessando o RCDIG (ele redireciona para o login e cria a sessão local que aceita o code depois)...")
    await page.goto(PORTAL_URL, wait_until="domcontentloaded")

    # Se o rcdig não redirecionou sozinho para o login, cai para a LOGIN_URL fixa.
    if "centralautenticacao" not in page.url and "login.html" not in page.url:
        print("  (rcdig não redirecionou sozinho - indo direto para a tela de login)")
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    # Se a tela inicial mostrar as opções (Sentinela/CPF/Central), clica em "Central de Segurança".
    try:
        await page.click("#btnCentral", timeout=5000)
    except Exception:                                   # noqa: BLE001 — já pode vir aberto
        pass

    await page.fill("#attribute_central", login)
    await page.fill("#password", senha)
    await page.click("#btn-central-acessar")

    print("Aguardando a tela do segundo fator (2FA)...")
    try:
        await page.wait_for_selector("#btnEnviarEmailToken2FA", timeout=30000)
    except PlaywrightTimeout as exc:
        pasta = await _salvar_evidencias(page, rede_log, "sem_tela_2fa")
        raise RuntimeError(
            "A tela do código de verificação não apareceu. Confira se o login e a senha do RCO estão corretos "
            f"(Configurações → Senha do RCO). Capturas de diagnóstico em {pasta}."
        ) from exc
    await page.click("#btnEnviarEmailToken2FA")
    print("Código de verificação pedido: o RCO vai enviá-lo por e-mail. Digite-o na caixa que abriu na tela.")

    codigo = await entrada_usuario.perguntar(
        chave,
        "Código de verificação do RCO",
        "O RCO enviou um código por e-mail (confira também a caixa de spam). Digite-o abaixo; ele vale por pouco tempo.",
        "Código recebido por e-mail",
        validar=_validar_codigo,
    )
    codigo = "".join(codigo.split())

    campo_codigo = page.locator("#codigoSegurancaEmail")
    try:
        await campo_codigo.wait_for(state="visible", timeout=15000)
    except PlaywrightTimeout as exc:
        pasta = await _salvar_evidencias(page, rede_log, "sem_campo_codigo")
        raise RuntimeError(
            "Não encontrei o campo do código do token (#codigoSegurancaEmail): a tela do RCO pode ter mudado. "
            f"Capturas de diagnóstico em {pasta}."
        ) from exc
    await campo_codigo.fill(codigo)

    await page.wait_for_selector("#confirmarTokenEmail", timeout=15000)
    await page.click("#confirmarTokenEmail")

    # Espera SAIR da tela de login: a cadeia auth-cs → authorize/jwt → rcdig?code=... pode ter vários redirects.
    try:
        await page.wait_for_url(lambda url: "login.html" not in url, timeout=20000)
    except Exception:                                   # noqa: BLE001
        pass
    await page.wait_for_load_state("networkidle")

    if "login.html" in page.url:
        pasta = await _salvar_evidencias(page, rede_log, "voltou_login")
        raise RuntimeError(
            "Depois de confirmar o código o RCO voltou para a tela de login: o código pode estar errado ou "
            "vencido (peça outro e tente de novo) ou a sessão não foi aceita. "
            f"Capturas, log de rede e nomes dos cookies em {pasta}."
        )

    print("Login efetuado com sucesso.")


async def selecionar_periodo(page: Page, periodo_valor: str) -> None:
    """
    Navegação inicial até 'Consultar Aluno' (que já deixa o período letivo selecionado). Feita uma vez, no
    início, só para conferir que o login e a navegação estão OK antes do laço de alunos.
    """
    print("Acessando o RCDIG...")
    await page.goto(PORTAL_URL, wait_until="domcontentloaded")
    await navegar_para_consultar_aluno(page, periodo_valor)


async def navegar_para_consultar_aluno(page: Page, periodo_valor: str) -> None:
    """
    Estabelecimento > Relatórios > Consultar Aluno > seleciona o Período Letivo.

    "Relatórios" existe em dois lugares do menu, com papéis opostos:
      - clLevel0 (aba no topo): relatórios JÁ PROCESSADOS, prontos para download
        (ver ir_para_relatorios_processados);
      - clLevel1 (submenu de Estabelecimento): onde se SOLICITA a geração, incluindo "Consultar Aluno".
        É este que se usa aqui.

    O RCDIG não é uma SPA: a cada volta (a cada aluno) a tela recarrega e o <select id="codPeriodoLetivo">
    volta para "Selecione" — por isso o período é selecionado de novo AQUI, toda vez.
    """
    await page.get_by_text("Estabelecimento", exact=True).click()
    await page.locator(".clLevel1", has_text=re.compile(r"^Relatórios$")).click()
    # A partir da 2ª volta a tela "Consultar Aluno" já está aberta e tem um <h1> com o mesmo texto, o que
    # causaria "strict mode violation"; por isso restringe ao item de menu (.clLevel1).
    await page.locator(".clLevel1", has_text=re.compile(r"^Consultar Aluno$")).click()

    await page.wait_for_selector("#codPeriodoLetivo")
    await page.select_option("#codPeriodoLetivo", periodo_valor)


async def ir_para_relatorios_processados(page: Page) -> None:
    """Aba "Relatórios" do topo (clLevel0), onde ficam os PDFs já gerados."""
    await page.locator(".clLevel0", has_text=re.compile(r"^Relatórios$")).click()


async def solicitar_parecer(page: Page, cgm: str, nome: str) -> bool:
    """
    Na tela Consultar Aluno: busca o CGM e clica no ícone de PDF, que NÃO baixa na hora — dispara a geração
    assíncrona ("...enviada para fila de processamento..."). O arquivo só fica pronto uns 10 s depois, na aba
    de Relatórios Processados (ver aguardar_e_baixar_parecer). False = o aluno não tem parecer.
    """
    campo_cgm = page.locator("input[name='cgmAluno']")
    await campo_cgm.fill("")
    await campo_cgm.fill(cgm)
    await page.locator("input[value='Consultar']").click()
    await page.wait_for_load_state("networkidle")

    link_gerar = page.locator("a[href*='visualizarRelatorio']").first
    if await link_gerar.count() == 0:
        print(f"  [AVISO] Nenhum parecer encontrado para CGM {cgm} ({nome}) - pulando.")
        return False

    await link_gerar.click()
    # Confirma que entrou na fila: se a mensagem não aparecer, algo mudou no fluxo e é melhor falhar aqui do
    # que esperar um arquivo que nunca vai ser gerado.
    await page.get_by_text("fila de processamento", exact=False).wait_for(timeout=15000)
    return True


def _slug(texto: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(texto)).strip("_")


def caminho_do_parecer(destino_base: Path, turma: str, nome: str, cgm: str, numero_chamada) -> Path:
    """<destino>/<turma>/<nº da chamada> - <nome>.pdf (sem nº de chamada, usa o CGM)."""
    prefixo = str(numero_chamada).strip() if numero_chamada not in (None, "") else cgm
    return destino_base / (_slug(turma) or "SEM_TURMA") / f"{prefixo} - {_slug(nome) or cgm}.pdf"


async def aguardar_e_baixar_parecer(
    page: Page, cgm: str, nome: str, numero_chamada, turma: str, destino_base: Path,
    espera_inicial: float = 10.0, tentativas: int = 6, intervalo_retry: float = 5.0,
) -> Optional[Path]:
    """
    Troca para Relatórios Processados, espera o processamento (~10 s) e localiza a linha cujo link de download
    é 'RelatorioAluno<CGM>.pdf' — esse nome é o que garante casar o arquivo certo com o aluno certo, mesmo com
    outros relatórios (ex.: Registro de Classe da turma) na mesma tabela.

    A tabela só mostra os relatórios da sessão/login atual e o RCDIG não apaga nada; cada CGM gera um nome
    diferente, então não há colisão nem necessidade de limpar a fila.
    Devolve o caminho salvo, ou None se o arquivo não apareceu.
    """
    await ir_para_relatorios_processados(page)
    await page.wait_for_timeout(int(espera_inicial * 1000))

    nome_arquivo_alvo = f"RelatorioAluno{cgm}.pdf"
    link_download = page.get_by_text(nome_arquivo_alvo, exact=True)

    for tentativa in range(1, tentativas + 1):
        if await link_download.count() > 0:
            break
        print(f"  [INFO] {nome_arquivo_alvo} ainda não apareceu (tentativa {tentativa}/{tentativas}) - atualizando...")
        await page.get_by_role("button", name="Atualizar").click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(int(intervalo_retry * 1000))
    else:
        print(f"  [ERRO] {nome_arquivo_alvo} não apareceu após {tentativas} tentativas - pulando {nome} (CGM {cgm}).")
        return None

    async with page.expect_download() as download_info:
        await link_download.click()
    download = await download_info.value

    destino = caminho_do_parecer(destino_base, turma, nome, cgm, numero_chamada)
    destino.parent.mkdir(parents=True, exist_ok=True)
    await download.save_as(destino)

    # O balão de downloads do Chrome pode mostrar um nome temporário sem extensão: é só o arquivo bruto ANTES do
    # save_as acima, que sempre termina em ".pdf". O que importa é o CONTEÚDO ser um PDF (e não uma página de
    # erro salva sem querer): confere a assinatura "%PDF-".
    try:
        with open(destino, "rb") as f:
            assinatura = f.read(5)
        if assinatura != b"%PDF-":
            print(f"  [AVISO] {destino.name} não parece ser um PDF válido (não começa com %PDF-) - confira manualmente.")
    except OSError as exc:
        print(f"  [AVISO] Não foi possível validar o conteúdo de {destino}: {exc}")

    print(f"  [OK] Parecer salvo em: {destino}")
    return destino


# ───────────────────────────── ponto de entrada ─────────────────────────────

async def gerar_pareceres_infantil_via_login(
    bimestre,
    *,
    modo_teste: bool = False,
    mostrar_navegador: bool = False,
    chave: str = CHAVE,
    periodo: Optional[str] = None,
) -> dict:
    """
    Baixa os pareceres do Infantil IV/V (matriculados) do RCDIG. Devolve
    {"total", "baixados", "falhas": [{"cgm","nome","motivo"}], "pasta"}.
    ValueError se faltar algo (bimestre, credenciais, turmas.json); RuntimeError se o login falhar.
    """
    rotulo = rotulo_bimestre(bimestre)
    login, senha = credenciais_rco()
    periodo = periodo or periodo_letivo_atual()
    print(f"Período letivo: {periodo} | {rotulo}")

    alunos = carregar_alunos_alvo(carregar_turmas())
    if not alunos:
        raise ValueError("Nenhum aluno Matriculado encontrado nas turmas de Infantil IV/V em turmas.json.")
    print(f"{len(alunos)} aluno(s) encontrados (Infantil IV/V, Matriculado).")
    if modo_teste:
        alunos = alunos[:1]
        print(f"[MODO TESTE] Processando só o primeiro aluno: {alunos[0]['nome']} (CGM {alunos[0]['cgm']}).")

    destino_base = pasta_destino(paths.ano_atual(), rotulo)
    destino_base.mkdir(parents=True, exist_ok=True)
    print(f"Pareceres serão salvos em: {destino_base}")

    baixados = 0
    falhas: list[dict] = []

    async with async_playwright() as p:
        browser = await _navegador.lancar(
            p, "chromium", True, forcar_mostrar=mostrar_navegador,
            travar_motor=True,                      # usa um argumento exclusivo do Chromium: ignora o navegador padrão global
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                accept_downloads=True, user_agent=USER_AGENT,
                viewport={"width": 1366, "height": 768}, locale="pt-BR",
            )
            # O rcdig devolvia force_login=true sem criar cookie de sessão — sintoma típico de detecção de
            # automação. navigator.webdriver=true é o sinal mais óbvio do Playwright; esconder esse sinal
            # (mantido do script original) é a primeira defesa contra isso.
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = await context.new_page()

            await fazer_login(page, login, senha, chave)
            await selecionar_periodo(page, periodo)

            total = len(alunos)
            for i, aluno in enumerate(alunos, 1):
                verificar_cancelamento()
                print(f"[{i}/{total}] Processando {aluno['nome']} (CGM {aluno['cgm']})...")
                try:
                    # Refeito a cada aluno: a navegação não se mantém entre iterações porque o fluxo passa
                    # pela aba Relatórios do topo (clLevel0) para buscar o arquivo processado.
                    await navegar_para_consultar_aluno(page, periodo)
                    if not await solicitar_parecer(page, aluno["cgm"], aluno["nome"]):
                        falhas.append({"cgm": aluno["cgm"], "nome": aluno["nome"], "motivo": "sem parecer no RCO"})
                        continue
                    salvo = await aguardar_e_baixar_parecer(
                        page, aluno["cgm"], aluno["nome"], aluno.get("n_chamada"), aluno["turma"], destino_base)
                    if salvo is None:
                        falhas.append({"cgm": aluno["cgm"], "nome": aluno["nome"], "motivo": "o arquivo não apareceu na fila"})
                    else:
                        baixados += 1
                except Exception as exc:                # noqa: BLE001 — um aluno com problema não para os demais
                    print(f"  [ERRO] Falhou para CGM {aluno['cgm']}: {exc}")
                    falhas.append({"cgm": aluno["cgm"], "nome": aluno["nome"], "motivo": str(exc)[:200]})
        finally:
            await browser.close()

    print(f"\nConcluído: {baixados} de {len(alunos)} parecer(es) baixado(s), {len(falhas)} com problema.")
    for f in falhas:
        print(f"  - CGM {f['cgm']} | {f['nome']}: {f['motivo']}")
    return {"total": len(alunos), "baixados": baixados, "falhas": falhas, "pasta": str(destino_base)}

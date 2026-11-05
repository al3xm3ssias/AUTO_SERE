"""
rematricula.py (portado para src/automacao/)

Rematrícula automática: para cada turma/seção alvo, abre no SERE a lista de
alunos matriculados e, aluno por aluno, gera a chave de acesso do
responsável, entra na Área do Aluno com CPF + chave e confirma a matrícula
online na escola sugerida.

Ponto de entrada (sem argparse/sys.argv; pronto para virar botão de GUI):

  rematricular_via_login(modo_teste=False, apenas_erros=False, ...)

    modo_teste=True    1 aluno por seção (antigo --teste / -t)
    apenas_erros=True  reprocessa só quem está em rematriculas_erro.json
                       (antigo --erros / -e)

Arquivos de controle, em paths.dados_ano_atual():
  rematriculas_sucesso.json    quem já foi rematriculado (nunca é reprocessado)
  rematriculas_erro.json       quem falhou, com nº de tentativas acumulado
  rematriculas_historico.json  todas as tentativas, de todas as execuções

Diferenças em relação ao script original:
  - As listas de erros (e o histórico) agora são CARREGADAS do disco. O
    original começava cada execução com `erros = []` e `historico = []` e os
    gravava por cima: erros de seções não visitadas eram apagados, o contador
    de tentativas nunca passava de 1 entre execuções e o histórico só guardava
    a última execução.
  - processar_turma() tem limite de tentativas. Antes, falha de login ou de
    navegação (senha errada, SERE fora do ar) fazia `continue` sem contador e
    o script ficava tentando para sempre.
  - Arquivos gravados de forma atômica, na pasta de dados do ano (antes: na
    pasta atual) e nunca sobrescritos se ilegíveis.
  - Registro de sucesso/erro unificado em registrar_resultado() (a lógica
    estava copiada em dois lugares, e o registro de erro crítico não removia
    a entrada anterior do mesmo aluno, gerando duplicatas).
  - Login e navegação repetidos 3 vezes viraram _abrir_por_turmas().
  - Chaves salvas: se existir dados/<ano>/chave_responsavel.json (gerado por
    src.automacao.chaves_responsavel), o aluno que tem chave nele entra direto na Área do Aluno, sem abrir a
    ficha no SERE. Chave recusada -> gera nova na hora, atualiza o arquivo e tenta uma vez de novo.
  - O JavaScript das páginas está em strings raw (r\"\"\"...\"\"\"): `\\s` e
    `\\d` em string comum são "escape inválido" e viram SyntaxError em
    versões futuras do Python.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from src.automacao import chaves_responsavel
from src.comum import paths
from src.comum.arquivos_json import (
    ArquivoJsonCorrompidoError,
    carregar_json,
    salvar_json_atomico,
)


# ==========================================================
# CONSTANTES
# ==========================================================

URL_SERE = "https://www.sere.pr.gov.br/sere"
URL_AREA_ALUNO = "https://www.areadoaluno.seed.pr.gov.br/"
URL_CONFIRMACAO = (
    "https://www.areadoaluno.seed.pr.gov.br/servicosaoaluno/pages/v2/"
    "matriculaOnLine/confirmacaoEscolaSugerida.jsf"
)

TURMAS_ALVO = [
    "INFANTIL 4",
    "INFANTIL 5",
    "1º Ano",
    "2º Ano",
    "3º Ano",
    "4º Ano",
]

ARQUIVO_ERROS = "rematriculas_erro.json"
ARQUIVO_SUCESSO = "rematriculas_sucesso.json"
ARQUIVO_HISTORICO = "rematriculas_historico.json"

# Reinícios do navegador tolerados para o MESMO aluno antes de desistir dele.
MAX_TENTATIVAS_NAVEGADOR = 3
# Falhas seguidas de sessão (login, navegação, exceção inesperada) antes de
# desistir da turma/seção; zera a cada aluno concluído.
MAX_FALHAS_SESSAO = 3


class ErroReiniciarNavegador(Exception):
    """Exceção que força reinicialização do navegador."""


class RematriculaCorrompidaError(ArquivoJsonCorrompidoError):
    """Um arquivo de controle da rematrícula está ilegível. Ele NÃO é tocado."""


# ==========================================================
# CAMINHOS E PERSISTÊNCIA
# ==========================================================

def _pasta() -> Path:
    return Path(paths.dados_ano_atual())


def caminho_sucesso() -> Path:
    return _pasta() / ARQUIVO_SUCESSO


def caminho_erros() -> Path:
    return _pasta() / ARQUIVO_ERROS


def caminho_historico() -> Path:
    return _pasta() / ARQUIVO_HISTORICO


def _carregar_lista(caminho: Path) -> list:
    return carregar_json(caminho, list, tipo_esperado=list, erro=RematriculaCorrompidaError)


def carregar_erros_anteriores() -> list:
    """Alunos que deram erro antes. Arquivo ilegível -> RematriculaCorrompidaError."""
    return _carregar_lista(caminho_erros())


def carregar_sucessos_anteriores() -> list:
    """Alunos já rematriculados. Arquivo ilegível -> RematriculaCorrompidaError."""
    return _carregar_lista(caminho_sucesso())


def carregar_historico_anterior() -> list:
    """Todas as tentativas de execuções anteriores."""
    return _carregar_lista(caminho_historico())


def salvar_resultados(sucessos, erros, historico) -> None:
    """Grava os três arquivos de controle (cada um de forma atômica)."""
    salvar_json_atomico(caminho_sucesso(), sucessos, indent=4)
    salvar_json_atomico(caminho_erros(), erros, indent=4)
    salvar_json_atomico(caminho_historico(), historico, indent=4)


def aluno_ja_processado(aluno, lista_sucesso) -> bool:
    """True se o CGM do aluno já consta na lista de sucessos."""
    return any(item["cgm"] == aluno["cgm"] for item in lista_sucesso)


def registrar_resultado(
    sucessos, erros, historico, aluno, turma, sucesso, erro_msg=None, incremento_tentativas=1
):
    """
    Registra o resultado de UM aluno nas três listas (em memória) e devolve o
    registro criado.

      sucesso:  entra em `sucessos` (sem duplicar) e sai de `erros`.
      falha:    substitui a entrada anterior do mesmo CGM em `erros`, com
                tentativas = tentativas anteriores + incremento_tentativas
                (execuções anteriores contam).
      sempre:   acrescenta ao `historico`.
    """
    registro = {
        "cgm": aluno["cgm"],
        "nome": aluno["Nome"],
        "turma": turma,
        "data_nascimento": aluno.get("Data Nasc.", ""),
        "timestamp": datetime.now().isoformat(),
    }

    if sucesso:
        if not aluno_ja_processado(aluno, sucessos):
            sucessos.append(registro)
        erros[:] = [e for e in erros if e["cgm"] != aluno["cgm"]]
    else:
        anterior = next((e for e in erros if e["cgm"] == aluno["cgm"]), None)
        registro["erro"] = erro_msg
        registro["tentativas"] = (anterior.get("tentativas", 1) if anterior else 0) + incremento_tentativas
        erros[:] = [e for e in erros if e["cgm"] != aluno["cgm"]]
        erros.append(registro)

    historico.append({**registro, "sucesso": sucesso})
    return registro


def _credenciais_padrao() -> tuple[str, str]:
    """Credenciais do SERE (carregadas só quando necessárias)."""
    from src.comum.credenciais import LOGIN, SENHA
    return LOGIN, SENHA


# ==========================================================
# TEXTO E TURMAS
# ==========================================================

def normalize_text(s: str) -> str:
    """
    Normaliza texto para comparação: Unicode NFKC, NBSP -> espaço, traços
    unificados em '-', espaços colapsados, sem acentos, minúsculas.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[–—−]", "-", s)
    s = " ".join(s.split())
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = unicodedata.normalize("NFC", s)
    return s.lower()


def _label_da_secao(texto: str, href: str) -> tuple[str, str]:
    """
    (turma_arg, label) de um link AoClicarTurma('...','...','...','...','...',
    'B ','2º Ano',...). O texto do <a> pode ser só "B" enquanto o href traz
    "2º Ano"; o label preferencial é "2º Ano - B" (ou o texto/href se não der
    para extrair).
    """
    args = re.findall(r"'([^']*)'", href) if href else []
    letra = args[5].strip() if len(args) > 5 else ""
    turma_arg = args[6].strip() if len(args) > 6 else ""
    if turma_arg:
        return turma_arg, (f"{turma_arg} - {letra}" if letra else turma_arg)
    return "", (texto or href)


# ==========================================================
# SERE: LOGIN, NAVEGAÇÃO, TURMAS E ALUNOS
# ==========================================================

async def fazer_login_sere(page, login, senha):
    try:
        print("🔐 Fazendo login no SERE...")
        await page.goto(URL_SERE)
        await page.wait_for_timeout(2000)

        await page.fill("#CHAVE", login)
        await page.fill("#CHAVE_ENCRIPT", senha)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3000)
        print("✅ Login SERE realizado com sucesso!")
        return True
    except Exception as e:
        print(f"❌ Erro ao fazer login no SERE: {e}")
        return False


async def navegar_para_por_turmas(page):
    try:
        print("📂 Navegando para 'Por Turmas'...")
        menu = await page.wait_for_selector("#divoCMenu0_0", timeout=8000)
        await menu.evaluate(
            """
            (el)=> el.dispatchEvent(
                new MouseEvent('mouseover', {view: window, bubbles: true})
            )
            """
        )
        await page.wait_for_timeout(600)
        await page.click("//div[contains(text(),'Consulta Padrão')]")
        await page.wait_for_timeout(300)
        await page.click("//div[contains(text(),'Por Turma')]")
        await page.wait_for_timeout(2000)
        print("✅ Navegação para Por Turmas realizada!")
        return True
    except Exception as e:
        print(f"❌ Erro ao navegar: {e}")
        return False


async def _abrir_por_turmas(browser, login, senha):
    """Nova página já logada no SERE e em 'Por Turma'; None (página fechada) se falhar."""
    page = await browser.new_page()
    if not await fazer_login_sere(page, login, senha):
        await page.close()
        return None
    if not await navegar_para_por_turmas(page):
        await page.close()
        return None
    return page


async def _na_tela_de_login(page) -> bool:
    """True se a página está na tela de login do SERE (a sessão caiu)."""
    try:
        return await page.query_selector("#CHAVE") is not None
    except Exception:
        return False


async def _tem_links_de_turma(page) -> bool:
    try:
        return await page.query_selector("a[href*='AoClicarTurma']") is not None
    except Exception:
        return False


async def _clicar_voltar(page) -> bool:
    """Botão 'Voltar' do SERE (o mesmo que o alunos.py usa para sair da turma). False se não houver."""
    try:
        voltar = await page.query_selector("//input[@value='Voltar']")
        if not voltar:
            return False
        await voltar.click()
        await page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


class SessaoSere:
    """
    UMA página logada no SERE, reaproveitada na execução inteira: listar as seções, abrir a turma, ler
    os alunos e processar cada um, continuando da tela em que a página está (como o alunos.py).

    O SERE só aceita uma sessão por usuário. Antes, cada etapa abria uma página nova com login próprio
    (3 logins por seção): a janela fechava e reabria sozinha, no meio do trabalho. Agora só se loga de
    novo se a sessão cair de verdade ou depois de um erro crítico (reiniciar).
    """

    def __init__(self, browser, login, senha):
        self.browser, self.login, self.senha = browser, login, senha
        self.page = None

    async def _ir_para_lista_de_turmas(self) -> bool:
        if self.page is None:
            self.page = await _abrir_por_turmas(self.browser, self.login, self.senha)
            return self.page is not None

        if await _na_tela_de_login(self.page):
            print("🔑 A sessão do SERE caiu — entrando de novo, nesta mesma página...")
            if not await fazer_login_sere(self.page, self.login, self.senha):
                return False
            return await navegar_para_por_turmas(self.page)

        if await _tem_links_de_turma(self.page):
            return True  # já está na lista de turmas

        if await _clicar_voltar(self.page) and await _tem_links_de_turma(self.page):
            return True

        return await navegar_para_por_turmas(self.page)

    async def ir_para_lista_de_turmas(self) -> bool:
        """Deixa a página na lista de turmas ('Por Turma'). Se falhar, descarta a página: a próxima tentativa abre uma limpa."""
        ok = await self._ir_para_lista_de_turmas()
        if not ok:
            await self.fechar()
        return ok

    async def fechar(self):
        page, self.page = self.page, None
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass

    reiniciar = fechar  # erro crítico: descarta a página; a próxima etapa abre outra, logada do zero


async def listar_secao_turmas(page, nome_turma):
    """
    Labels das seções relacionadas a nome_turma (ex.: "2º Ano - A", "2º Ano - B").
    Busca no texto do link e nos argumentos do href (AoClicarTurma).
    """
    try:
        await page.wait_for_selector("a[href*='AoClicarTurma']", timeout=8000)
        raw = await page.evaluate(
            r"""() => {
                const links = Array.from(document.querySelectorAll("a[href*='AoClicarTurma']"));
                return links.map(l => ({
                    text: (l && l.textContent) ? l.textContent.trim().replace(/\s+/g,' ') : '',
                    href: l.getAttribute('href') || ''
                }));
            }"""
        )

        alvo_norm = normalize_text(nome_turma)
        secoes = []
        seen = set()

        for item in raw:
            texto = item.get("text", "")
            href = item.get("href", "")
            turma_arg, label = _label_da_secao(texto, href)

            if alvo_norm in normalize_text(texto) or alvo_norm in normalize_text(turma_arg):
                if label not in seen:
                    secoes.append(label)
                    seen.add(label)

        return secoes
    except Exception as e:
        print(f"❌ Erro ao listar seções da turma '{nome_turma}': {e}")
        return []


async def selecionar_turma(page, nome_turma):
    """
    Seleciona a turma por (1) correspondência exata normalizada com o texto ou
    o label ("2º Ano - B") e (2) correspondência parcial. Se não achar, imprime
    todos os links disponíveis para depuração.
    """
    try:
        print(f"📚 Selecionando turma: {nome_turma}...")
        await page.wait_for_selector("a[href*='AoClicarTurma']", timeout=20000)
        await page.wait_for_timeout(300)

        links_turmas = await page.query_selector_all("a[href*='AoClicarTurma']")
        alvo_norm = normalize_text(nome_turma)

        async def dados_do_link(link):
            texto = (await link.inner_text()).strip()
            href = await link.get_attribute("href") or ""
            turma_arg, label = _label_da_secao(texto, href)
            return texto, turma_arg, label, href

        for link in links_turmas:
            texto, _turma_arg, label, _href = await dados_do_link(link)
            if normalize_text(texto) == alvo_norm or normalize_text(label) == alvo_norm:
                await link.click()
                await page.wait_for_timeout(2000)
                print(f"✅ Turma '{nome_turma}' selecionada (correspondência exata)!")
                return True

        for link in links_turmas:
            texto, turma_arg, label, _href = await dados_do_link(link)
            if (
                alvo_norm in normalize_text(texto)
                or (turma_arg and alvo_norm in normalize_text(turma_arg))
                or alvo_norm in normalize_text(label)
            ):
                await link.click()
                await page.wait_for_timeout(2000)
                print(f"✅ Turma '{nome_turma}' selecionada (correspondência parcial)!")
                return True

        print("⚠️ Não encontrou a turma desejada. Links de turma disponíveis (texto | turma_arg | label):")
        for link in links_turmas:
            texto, turma_arg, label, _href = await dados_do_link(link)
            print(f"  - texto: {texto!r} | turma_arg: {turma_arg!r} | label: {label!r} | normalized: {normalize_text(label)!r}")

        print(f"❌ Turma '{nome_turma}' não encontrada")
        return False

    except Exception as e:
        print(f"❌ Erro ao selecionar turma: {e}")
        return False


async def obter_alunos_matriculados(page):
    """Alunos com situação 'Matriculado' na tabela da turma aberta."""
    try:
        print("👥 Obtendo alunos matriculados...")
        await page.wait_for_selector("a[href*='AoClicarAluno']", timeout=20000)
        await page.wait_for_timeout(1000)

        alunos = await page.evaluate(
            r"""
            () => {
                const linhas = Array.from(document.querySelectorAll('table tr'));
                const alunos = [];

                linhas.forEach((linha, idx) => {
                    if (idx === 0) return;

                    const colunas = linha.querySelectorAll('td');
                    if (colunas.length < 8) return;

                    const situacao = colunas[6].textContent.trim();

                    if (situacao === 'Matriculado') {
                        // Normaliza espaços em branco no nome
                        const nomeRaw = colunas[2].textContent || '';
                        const nome = nomeRaw.replace(/\s+/g, ' ').trim();

                        alunos.push({
                            n: colunas[0].textContent.trim(),
                            cgm: colunas[1].textContent.trim(),
                            Nome: nome,
                            'Data Nasc.': colunas[3].textContent.trim(),
                            Idade: colunas[4].textContent.trim(),
                            Sexo: colunas[5].textContent.trim(),
                            'Situação': situacao,
                            'Data Matricula': colunas[7].textContent.trim()
                        });
                    }
                });

                return alunos;
            }
            """
        )

        print(f"✅ {len(alunos)} alunos matriculados encontrados")
        return alunos

    except Exception as e:
        print(f"❌ Erro ao obter alunos: {e}")
        return []


# ==========================================================
# CHAVE DE ACESSO, ÁREA DO ALUNO E CONFIRMAÇÃO
# ==========================================================

async def gerar_chave_acesso(page):
    try:
        print("🔑 Gerando chave de acesso...")

        await page.click("//button[contains(., 'Gerar Chave')]", timeout=5000)

        for _tentativa in range(5):
            await page.wait_for_timeout(1500)
            chave = await page.input_value("#chaveAcesso")

            if chave:
                print(f"✅ Chave gerada: {chave}")
                return chave

        print("❌ Timeout ao gerar chave")
        raise ErroReiniciarNavegador("Não foi possível gerar chave após múltiplas tentativas")

    except PlaywrightTimeoutError as e:
        print("❌ Erro ao gerar chave: Timeout ao clicar no botão")
        raise ErroReiniciarNavegador(f"Timeout ao tentar gerar chave: {e}")
    except ErroReiniciarNavegador:
        raise
    except Exception as e:
        print(f"❌ Erro ao gerar chave: {e}")
        raise ErroReiniciarNavegador(f"Erro ao gerar chave: {e}")


async def obter_cpf_responsavel(page):
    try:
        cpf = await page.evaluate(
            r"""
            () => {
                const tds = Array.from(document.querySelectorAll('td.texto_normal'));

                for (let td of tds) {
                    if (td.textContent.includes('CPF do Responsável')) {
                        const texto = td.textContent;
                        const cpfText = texto.replace('CPF do Responsável :', '').trim();
                        const match = cpfText.match(/(\d{11,})/);
                        if (match) return match[1];
                    }
                }

                return null;
            }
            """
        )

        if cpf:
            print(f"👤 CPF Responsável: {cpf}")
            return cpf
        print("⚠️ CPF do responsável não encontrado")
        return None

    except Exception as e:
        print(f"❌ Erro ao obter CPF: {e}")
        return None


async def fazer_login_area_aluno(page, cpf, chave):
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


async def acessar_matricula_online(page, nome_aluno):
    try:
        print(f"🔍 Acessando matrícula online para {nome_aluno}...")

        try:
            await page.evaluate(
                """
                try { $(function(){ PF('modalEnvioDocumetos').hide(); }); } catch(e) {}
                """
            )
            print("✓ Modal fechado automaticamente via jQuery+PF")
            await page.wait_for_timeout(800)
        except Exception:
            pass

        print("➡️ Abrindo página de confirmação da matrícula...")

        try:
            await page.click("//a[contains(@href,'confirmacaoEscolaSugerida.jsf')]", timeout=4000)
        except Exception:
            await page.goto(URL_CONFIRMACAO)

        await page.wait_for_timeout(2000)

        print("🎯 Localizando select de aluno...")

        await page.click("#confirmacaoEscolaSugeridaForm\\:aluno_label", timeout=5000)
        await page.wait_for_timeout(600)

        print("🔎 Verificando se o aluno correto está no select...")

        itens = await page.query_selector_all("//li[contains(@id,'confirmacaoEscolaSugeridaForm:aluno_')]")

        nome_normalizado = " ".join(nome_aluno.split()).strip().upper()

        aluno_certo = None
        for item in itens:
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


# Textos que a página mostra quando a matrícula está realizada (a mesma checagem vale antes de confirmar,
# para o caso "já matriculado", e depois do clique final, para provar que a confirmação funcionou).
TEXTOS_MATRICULA_REALIZADA = ("MATRÍCULA REALIZADA COM SUCESSO", "IMPRIMIR COMPROVANTE")
ESPERA_CONFIRMACAO_MS = 15000   # quanto esperar a página mostrar a confirmação depois do clique final
INTERVALO_CONFIRMACAO_MS = 500


def _tem_texto_de_matricula_realizada(html):
    texto = (html or "").upper()
    return next((t for t in TEXTOS_MATRICULA_REALIZADA if t in texto), None)


async def _aguardar_matricula_realizada(page):
    """Espera (até ESPERA_CONFIRMACAO_MS) a página mostrar que a matrícula foi realizada. Devolve o texto achado ou None."""
    for _ in range(max(1, ESPERA_CONFIRMACAO_MS // INTERVALO_CONFIRMACAO_MS)):
        try:
            achado = _tem_texto_de_matricula_realizada(await page.content())
        except Exception:  # página em transição (navegação em curso): tenta de novo
            achado = None
        if achado:
            return achado
        await page.wait_for_timeout(INTERVALO_CONFIRMACAO_MS)
    return None


async def confirmar_matricula(page):
    """Devolve "JA_MATRICULADO", True (confirmada agora, com a página provando) ou False (falhou)."""
    try:
        try:
            achado = _tem_texto_de_matricula_realizada(await page.content())

            if achado == TEXTOS_MATRICULA_REALIZADA[0]:
                print("🎉 Matrícula já realizada anteriormente – pulando aluno.")
                return "JA_MATRICULADO"

            if achado:
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

        achado = await _aguardar_matricula_realizada(page)
        if not achado:
            print(
                f"❌ Cliquei em Confirmar, mas a página não mostrou a confirmação em {ESPERA_CONFIRMACAO_MS // 1000}s "
                "— não vou marcar como rematriculado."
            )
            return False

        print("🎉 Matrícula processada COMPLETAMENTE! (confirmação vista na página)")
        return True

    except Exception as e:
        print(f"❌ Erro ao confirmar matrícula: {e}")
        return False


async def voltar_para_turma(page):
    try:
        await page.go_back()
        await page.wait_for_timeout(1500)
    except Exception:
        pass


# ==========================================================
# PROCESSAMENTO
# ==========================================================

async def _abrir_ficha_gerar_chave(page_sere, aluno):
    """
    Abre a ficha do aluno no SERE, gera a chave de acesso e lê o CPF do responsável.
    Devolve (chave, cpf, erro). Com erro None a ficha continua aberta (quem chamou
    volta para a lista com voltar_para_turma). ErroReiniciarNavegador propaga.
    """
    if await _na_tela_de_login(page_sere):
        raise ErroReiniciarNavegador("A sessão do SERE caiu (tela de login)")

    await page_sere.wait_for_selector("a[href*='AoClicarAluno']", timeout=20000)
    links_alunos = await page_sere.query_selector_all("a[href*='AoClicarAluno']")

    # Como no alunos.py: o mesmo CGM pode aparecer em duas linhas (Transferido + Matriculado, aluno que
    # voltou). Clica na linha em que ele está Matriculado; sem essa informação, no primeiro link do CGM.
    candidatos = []
    for link in links_alunos:
        if (await link.inner_text()).strip() == aluno["cgm"]:
            candidatos.append(link)

    alvo = None
    for link in candidatos:
        try:
            situacao = await link.evaluate(
                "el => { const t = el.closest('tr')?.querySelectorAll('td')[6]; return t ? t.textContent.trim() : ''; }"
            )
        except Exception:
            situacao = ""
        if situacao == "Matriculado":
            alvo = link
            break
    if alvo is None and candidatos:
        alvo = candidatos[0]

    aluno_encontrado = alvo is not None
    if aluno_encontrado:
        print("🔗 Acessando perfil do aluno...")
        await alvo.click()
        await page_sere.wait_for_timeout(2000)

    if not aluno_encontrado:
        erro_detalhado = "Aluno não encontrado na lista"
        print(f"❌ {erro_detalhado}")
        return None, None, erro_detalhado

    chave = await gerar_chave_acesso(page_sere)

    cpf = await obter_cpf_responsavel(page_sere)
    if not cpf:
        erro_detalhado = "CPF do responsável não encontrado"
        print(f"❌ {erro_detalhado}")
        await voltar_para_turma(page_sere)
        return None, None, erro_detalhado

    return chave, cpf, None


async def _rematricular_na_area_aluno(browser, aluno, cpf, chave):
    """
    Entra na Área do Aluno com CPF + chave e confirma a matrícula online.
    Devolve (resultado, erro, chave_recusada): resultado True | "JA_MATRICULADO" | False;
    chave_recusada=True quando falhou no login ou ao abrir a matrícula online — os dois
    sintomas de chave inválida/expirada (o login não confere se a chave foi aceita).
    """
    page_aluno = None
    try:
        page_aluno = await browser.new_page()
        await page_aluno.goto(URL_AREA_ALUNO)
        await page_aluno.wait_for_timeout(2000)

        if not await fazer_login_area_aluno(page_aluno, cpf, chave):
            erro_detalhado = "Erro ao fazer login na Área do Aluno"
            print(f"❌ {erro_detalhado}")
            return False, erro_detalhado, True

        if not await acessar_matricula_online(page_aluno, aluno["Nome"]):
            erro_detalhado = "Erro ao acessar matrícula online"
            print(f"⚠️ {erro_detalhado}")
            return False, erro_detalhado, True

        resultado = await confirmar_matricula(page_aluno)

        if resultado == "JA_MATRICULADO":
            return resultado, None, False

        if not resultado:
            erro_detalhado = "Erro ao confirmar matrícula"
            print(f"⚠️ {erro_detalhado}")
            return False, erro_detalhado, False

        return True, None, False

    finally:
        if page_aluno:
            await page_aluno.close()


def _desfecho(aluno, resultado, erro):
    if resultado == "JA_MATRICULADO":
        print(f"✅ {aluno['Nome']} - JÁ MATRICULADO")
        return True, None
    if not resultado:
        return False, erro
    print(f"✅ {aluno['Nome']} - REMATRÍCULA PROCESSADA!")
    return True, None


async def processar_aluno(page_sere, browser, aluno, chaves=None):
    """
    Rematricula um aluno. Devolve (sucesso: bool, erro_detalhado: str | None).
    ErroReiniciarNavegador é propagado para o chamador reiniciar a sessão.

    chaves: lista de chave_responsavel.json (ver src.automacao.chaves_responsavel) ou None.
    Com chave salva utilizável para o aluno, entra direto na Área do Aluno, sem abrir a ficha no
    SERE. Se a chave salva for recusada (expirada, por ex.), gera uma nova no SERE, atualiza a lista
    e o arquivo, e tenta uma única vez de novo. Sem chave salva, gera na hora (e não grava).
    """
    try:
        print(f"\n{'='*70}")
        print(f"👤 Processando: {aluno['Nome']} (CGM: {aluno['cgm']})")
        print(f"{'='*70}")

        salvo = chaves_responsavel.buscar_chave(chaves, aluno["cgm"]) if chaves is not None else None
        regenerando = False

        if chaves_responsavel.chave_utilizavel(salvo):
            print("🗝️ Usando a chave salva...")
            resultado, erro, recusada = await _rematricular_na_area_aluno(
                browser, aluno, salvo["cpf_responsavel"], salvo["chave"]
            )
            if not recusada:
                return _desfecho(aluno, resultado, erro)
            print("⚠️ A chave salva não funcionou (expirada?). Gerando uma nova no SERE...")
            regenerando = True

        chave, cpf, erro = await _abrir_ficha_gerar_chave(page_sere, aluno)
        if erro:
            return False, erro

        if regenerando:
            try:
                chaves_responsavel.registrar_chave(chaves, aluno, salvo.get("turma", ""), chave, cpf)
                chaves_responsavel.salvar_chaves(chaves)
            except Exception as e:  # guardar a chave nova é auxiliar: não pode derrubar a rematrícula
                print(f"⚠️ Não consegui atualizar a chave salva: {e}")

        resultado, erro, _recusada = await _rematricular_na_area_aluno(browser, aluno, cpf, chave)
        await voltar_para_turma(page_sere)
        return _desfecho(aluno, resultado, erro)

    except ErroReiniciarNavegador:
        raise
    except Exception as e:
        erro_detalhado = str(e)
        print(f"❌ Erro ao processar aluno: {erro_detalhado}")
        return False, erro_detalhado


async def processar_alunos_da_secao(sessao, secao, alunos, tratar, ao_concluir, ao_desistir, ja_na_secao=False):
    """
    Percorre os alunos de uma seção na página da `sessao`, com recuperação automática. Usado pela
    rematrícula e pelo "Gerar chaves" (mesma sessão, mesma recuperação).

    tratar(page, aluno) -> resultado (pode levantar ErroReiniciarNavegador); ao_concluir(aluno, resultado)
    é chamado a cada aluno tratado; ao_desistir(aluno, erro) depois de MAX_TENTATIVAS_NAVEGADOR erros
    críticos seguidos no mesmo aluno. ja_na_secao=True: a página já está na lista de alunos da seção
    (continua dali, sem logar nem selecionar a turma de novo).

    Devolve True se todos os alunos foram tratados, False se a seção foi abandonada (turma não encontrada
    ou falhas de sessão repetidas). Quem ficou sem tratar não é registrado e será retomado na próxima execução.
    """
    indice = 0
    tentativa_navegador = 0   # reinícios seguidos para o MESMO aluno
    falhas_sessao = 0         # falhas seguidas de login/navegação/exceção
    reposicionar = not ja_na_secao

    while indice < len(alunos):
        try:
            if reposicionar:
                if not await sessao.ir_para_lista_de_turmas():
                    falhas_sessao += 1
                    if falhas_sessao >= MAX_FALHAS_SESSAO:
                        print(f"❌ {falhas_sessao} falhas seguidas de login/navegação. Abandonando '{secao}'.")
                        return False
                    print(f"❌ Falha no login/navegação (tentativa {falhas_sessao}/{MAX_FALHAS_SESSAO}), tentando novamente...")
                    await asyncio.sleep(3)
                    continue

                if not await selecionar_turma(sessao.page, secao):
                    print(f"❌ Não foi possível selecionar a seção '{secao}'")
                    return False
                reposicionar = False

            aluno = alunos[indice]
            print(f"\n[{indice + 1}/{len(alunos)}]", end=" ")

            try:
                resultado = await tratar(sessao.page, aluno)
            except ErroReiniciarNavegador as e:
                print(f"\n🔄 ERRO CRÍTICO DETECTADO: {e}")
                print("🔄 Reiniciando a sessão do SERE a partir do aluno atual...")

                tentativa_navegador += 1
                if tentativa_navegador >= MAX_TENTATIVAS_NAVEGADOR:
                    print(f"❌ Máximo de tentativas ({MAX_TENTATIVAS_NAVEGADOR}) atingido para este aluno")
                    print(f"⏭️  Pulando aluno: {aluno['Nome']}")
                    ao_desistir(aluno, e)
                    indice += 1
                    tentativa_navegador = 0

                await sessao.reiniciar()
                reposicionar = True
                await asyncio.sleep(5)
                continue

            ao_concluir(aluno, resultado)
            indice += 1
            tentativa_navegador = 0
            falhas_sessao = 0

            if indice < len(alunos):
                await asyncio.sleep(2)

        except Exception as e:
            print(f"❌ Erro inesperado ao processar a seção: {e}")
            falhas_sessao += 1
            if falhas_sessao >= MAX_FALHAS_SESSAO:
                print(f"❌ {falhas_sessao} falhas seguidas. Abandonando '{secao}'.")
                return False
            reposicionar = True  # não se sabe em que tela a página ficou: volta pela lista de turmas
            await asyncio.sleep(5)

    return True


async def processar_turma(sessao, turma_nome, alunos_para_processar, sucessos, erros, historico, chaves=None, ja_na_secao=False):
    """
    Rematricula os alunos de uma seção na página da `sessao` (ver processar_alunos_da_secao).
    Cada resultado é registrado e salvo na hora. Quem ficou sem tratar não vai para nenhuma lista.
    """

    def _concluir(aluno, resultado):
        sucesso, erro_msg = resultado
        registrar_resultado(sucessos, erros, historico, aluno, turma_nome, sucesso, erro_msg)
        salvar_resultados(sucessos, erros, historico)

    def _desistir(aluno, e):
        registrar_resultado(
            sucessos, erros, historico, aluno, turma_nome, False,
            erro_msg=f"Erro crítico após {MAX_TENTATIVAS_NAVEGADOR} tentativas: {e}",
            incremento_tentativas=MAX_TENTATIVAS_NAVEGADOR,
        )
        salvar_resultados(sucessos, erros, historico)

    async def _tratar(page, aluno):
        return await processar_aluno(page, sessao.browser, aluno, chaves=chaves)

    return await processar_alunos_da_secao(
        sessao, turma_nome, alunos_para_processar, _tratar, _concluir, _desistir, ja_na_secao=ja_na_secao
    )


async def rematricular_via_login(
    modo_teste=False,
    apenas_erros=False,
    turmas_alvo=None,
    login=None,
    senha=None,
    navegador="chromium",
    headless=False,
    usar_chaves_salvas=True,
    um_aluno=False,
):
    """
    Roda a rematrícula. Devolve um resumo:
      {"total_sucessos", "total_erros", "erros": [...], "novos_no_historico",
       "arquivos": {"sucesso", "erros", "historico"}}

    turmas_alvo: lista de nomes-base (padrão TURMAS_ALVO); cada nome pode
    corresponder a várias seções (ex.: "2º Ano" -> "2º Ano - A", "2º Ano - B").
    headless=False por padrão (o original abre o navegador visível).

    um_aluno: teste com UM ÚNICO aluno no total (ao contrário de modo_teste, que faz 1 por seção). Pega o
    primeiro aluno pendente da primeira seção que tiver algum e para assim que ele for tentado (sucesso ou
    erro), sem abrir as demais seções. Não é simulação: esse aluno é rematriculado de verdade. Vale também
    com apenas_erros (reprocessa só o primeiro com erro). Se o aluno não chegar a ser tentado (seção
    abandonada por falha de login/navegação), segue para a próxima seção até conseguir tentar um.

    usar_chaves_salvas: usa as chaves de dados/<ano>/chave_responsavel.json (gerar_chaves_via_login) para
    quem tiver; quem não tiver, ou cuja chave for recusada, gera na hora como sempre. Arquivo de chaves
    ilegível não impede a rematrícula: avisa e gera todas na hora (o arquivo não é tocado).
    """
    turmas_alvo = list(turmas_alvo) if turmas_alvo is not None else list(TURMAS_ALVO)

    if login is None or senha is None:
        login_padrao, senha_padrao = _credenciais_padrao()
        login = login_padrao if login is None else login
        senha = senha_padrao if senha is None else senha

    print("\n" + "=" * 70)
    if um_aluno:
        print("🧪 MODO TESTE - 1 ÚNICO aluno no total")
    elif apenas_erros:
        print("🔄 MODO REPROCESSAMENTO - Apenas alunos com erro")
    elif modo_teste:
        print("🧪 MODO TESTE - 1 aluno por turma")
    else:
        print("▶️ MODO PRODUÇÃO")
    print("=" * 70)

    sucessos_anteriores = carregar_sucessos_anteriores()
    erros_anteriores = carregar_erros_anteriores()
    historico_anterior = carregar_historico_anterior()

    print(f"📊 Sucessos anteriores: {len(sucessos_anteriores)}")
    print(f"📊 Erros anteriores: {len(erros_anteriores)}")

    chaves = None
    if usar_chaves_salvas:
        try:
            chaves = chaves_responsavel.carregar_chaves()
            print(f"🗝️ Chaves salvas disponíveis: {len(chaves)}")
        except chaves_responsavel.ChavesCorrompidasError as e:
            print(f"⚠️ {e}\n⚠️ Seguindo sem chaves salvas: todas serão geradas na hora.")

    sucessos = list(sucessos_anteriores)
    erros = list(erros_anteriores)          # carregados: o contador de tentativas acumula
    historico = list(historico_anterior)    # carregado: o histórico não é sobrescrito

    async with async_playwright() as p:
        browser = await getattr(p, navegador).launch(headless=headless)
        sessao = SessaoSere(browser, login, senha)  # UMA página logada no SERE para a execução inteira

        try:
            encerrar = False  # um_aluno: já tentou o aluno de teste, não abre mais nada

            for turma_nome in turmas_alvo:
                if encerrar:
                    break
                print(f"\n{'='*70}")
                print(f"📚 PROCESSANDO TURMA (base): {turma_nome}")
                print(f"{'='*70}")

                if not await sessao.ir_para_lista_de_turmas():
                    continue

                secoes = await listar_secao_turmas(sessao.page, turma_nome)

                if not secoes:
                    print(f"\n⚠️ Nenhuma seção encontrada para '{turma_nome}'")
                    continue

                for secao_texto in secoes:
                    if encerrar:
                        break
                    print(f"\n--- Iniciando seção: {secao_texto} ---")

                    if not await sessao.ir_para_lista_de_turmas():
                        continue

                    if not await selecionar_turma(sessao.page, secao_texto):
                        print(f"\n⚠️ Seção '{secao_texto}' não encontrada ao tentar selecionar")
                        continue

                    alunos = await obter_alunos_matriculados(sessao.page)

                    if not alunos:
                        print(f"\n⚠️ Nenhum aluno matriculado em '{secao_texto}'")
                        continue

                    if apenas_erros:
                        cgms_com_erro = {e["cgm"] for e in erros_anteriores if e["turma"] == secao_texto}
                        alunos_para_processar = [a for a in alunos if a["cgm"] in cgms_com_erro]
                        print(f"🔄 {len(alunos_para_processar)} alunos com erro para reprocessar em {secao_texto}")
                    else:
                        alunos_para_processar = [
                            a for a in alunos if not aluno_ja_processado(a, sucessos_anteriores)
                        ]
                        if modo_teste:
                            alunos_para_processar = alunos_para_processar[:1]

                    if um_aluno:
                        alunos_para_processar = alunos_para_processar[:1]

                    if not alunos_para_processar:
                        print(f"✅ Todos os alunos de '{secao_texto}' já foram processados!")
                        continue

                    tentativas_antes = len(historico)
                    # a página já está na lista de alunos da seção: continua dali, sem logar de novo
                    await processar_turma(
                        sessao, secao_texto, alunos_para_processar,
                        sucessos, erros, historico, chaves=chaves, ja_na_secao=True,
                    )

                    if um_aluno and len(historico) > tentativas_antes:
                        print("\n🧪 Aluno de teste tentado — encerrando (modo 1 aluno).")
                        encerrar = True

        finally:
            await sessao.fechar()
            await browser.close()

    salvar_resultados(sucessos, erros, historico)

    novos = len(historico) - len(historico_anterior)

    print("\n\n" + "=" * 70)
    print("📊 RESUMO FINAL")
    print("=" * 70)
    print(f"✅ Total de sucessos: {len(sucessos)}")
    print(f"❌ Total com erro: {len(erros)}")
    print(f"📝 Novos registros no histórico: {novos} (total: {len(historico)})")
    print("=" * 70)

    if erros:
        print("\n⚠️ Alunos com erro:")
        for e in erros:
            print(f"  - {e['nome']} (CGM: {e['cgm']}) - Tentativas: {e.get('tentativas', 1)}")
            print(f"    Erro: {e.get('erro', 'Não especificado')}")

    print("\n📁 Arquivos salvos:")
    print(f"  - {caminho_sucesso()}")
    print(f"  - {caminho_erros()}")
    print(f"  - {caminho_historico()}")
    print("=" * 70 + "\n")

    return {
        "total_sucessos": len(sucessos),
        "total_erros": len(erros),
        "erros": erros,
        "novos_no_historico": novos,
        "arquivos": {
            "sucesso": caminho_sucesso(),
            "erros": caminho_erros(),
            "historico": caminho_historico(),
        },
    }

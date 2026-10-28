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


async def confirmar_matricula(page):
    """Devolve "JA_MATRICULADO", True (confirmada agora) ou False (falhou)."""
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


async def voltar_para_turma(page):
    try:
        await page.go_back()
        await page.wait_for_timeout(1500)
    except Exception:
        pass


# ==========================================================
# PROCESSAMENTO
# ==========================================================

async def processar_aluno(page_sere, browser, aluno):
    """
    Rematricula um aluno. Devolve (sucesso: bool, erro_detalhado: str | None).
    ErroReiniciarNavegador é propagado para o chamador reiniciar a sessão.
    """
    page_aluno = None

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


async def processar_turma(browser, turma_nome, alunos_para_processar, sucessos, erros, historico, login, senha):
    """
    Processa uma turma/seção completa com recuperação automática.

    Devolve True se todos os alunos foram tratados, False se a seção foi
    abandonada (turma não encontrada ou falhas de sessão repetidas). Quem
    ficou sem tratar não é registrado em nenhuma lista e será retomado na
    próxima execução (não consta em sucessos).
    """
    indice_atual = 0
    tentativa_navegador = 0   # reinícios seguidos para o MESMO aluno
    falhas_sessao = 0         # falhas seguidas de login/navegação/exceção

    while indice_atual < len(alunos_para_processar):
        page_turma = None

        try:
            page_turma = await _abrir_por_turmas(browser, login, senha)

            if page_turma is None:
                falhas_sessao += 1
                if falhas_sessao >= MAX_FALHAS_SESSAO:
                    print(f"❌ {falhas_sessao} falhas seguidas de login/navegação. Abandonando '{turma_nome}'.")
                    return False
                print(f"❌ Falha no login/navegação (tentativa {falhas_sessao}/{MAX_FALHAS_SESSAO}), tentando novamente...")
                await asyncio.sleep(3)
                continue

            if not await selecionar_turma(page_turma, turma_nome):
                print(f"❌ Não foi possível selecionar turma '{turma_nome}'")
                return False

            while indice_atual < len(alunos_para_processar):
                aluno = alunos_para_processar[indice_atual]

                print(f"\n[{indice_atual + 1}/{len(alunos_para_processar)}]", end=" ")

                try:
                    sucesso, erro_msg = await processar_aluno(page_turma, browser, aluno)

                    registrar_resultado(sucessos, erros, historico, aluno, turma_nome, sucesso, erro_msg)
                    salvar_resultados(sucessos, erros, historico)

                    indice_atual += 1
                    tentativa_navegador = 0
                    falhas_sessao = 0

                    if indice_atual < len(alunos_para_processar):
                        await asyncio.sleep(2)

                except ErroReiniciarNavegador as e:
                    print(f"\n🔄 ERRO CRÍTICO DETECTADO: {e}")
                    print("🔄 Fechando navegador e reiniciando do aluno atual...")

                    tentativa_navegador += 1

                    if tentativa_navegador >= MAX_TENTATIVAS_NAVEGADOR:
                        print(f"❌ Máximo de tentativas ({MAX_TENTATIVAS_NAVEGADOR}) atingido para este aluno")
                        print(f"⏭️  Pulando aluno: {aluno['Nome']}")

                        registrar_resultado(
                            sucessos, erros, historico, aluno, turma_nome, False,
                            erro_msg=f"Erro crítico após {MAX_TENTATIVAS_NAVEGADOR} tentativas: {e}",
                            incremento_tentativas=MAX_TENTATIVAS_NAVEGADOR,
                        )
                        salvar_resultados(sucessos, erros, historico)

                        indice_atual += 1
                        tentativa_navegador = 0

                    await page_turma.close()
                    page_turma = None

                    await asyncio.sleep(5)
                    break  # reinicia a sessão a partir do aluno atual

            if indice_atual >= len(alunos_para_processar):
                return True

        except Exception as e:
            print(f"❌ Erro inesperado ao processar turma: {e}")
            falhas_sessao += 1
            if falhas_sessao >= MAX_FALHAS_SESSAO:
                print(f"❌ {falhas_sessao} falhas seguidas. Abandonando '{turma_nome}'.")
                return False
            await asyncio.sleep(5)

        finally:
            if page_turma:
                try:
                    await page_turma.close()
                except Exception:
                    pass

    return True


async def rematricular_via_login(
    modo_teste=False,
    apenas_erros=False,
    turmas_alvo=None,
    login=None,
    senha=None,
    navegador="chromium",
    headless=False,
):
    """
    Roda a rematrícula. Devolve um resumo:
      {"total_sucessos", "total_erros", "erros": [...], "novos_no_historico",
       "arquivos": {"sucesso", "erros", "historico"}}

    turmas_alvo: lista de nomes-base (padrão TURMAS_ALVO); cada nome pode
    corresponder a várias seções (ex.: "2º Ano" -> "2º Ano - A", "2º Ano - B").
    headless=False por padrão (o original abre o navegador visível).
    """
    turmas_alvo = list(turmas_alvo) if turmas_alvo is not None else list(TURMAS_ALVO)

    if login is None or senha is None:
        login_padrao, senha_padrao = _credenciais_padrao()
        login = login_padrao if login is None else login
        senha = senha_padrao if senha is None else senha

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
    historico_anterior = carregar_historico_anterior()

    print(f"📊 Sucessos anteriores: {len(sucessos_anteriores)}")
    print(f"📊 Erros anteriores: {len(erros_anteriores)}")

    sucessos = list(sucessos_anteriores)
    erros = list(erros_anteriores)          # carregados: o contador de tentativas acumula
    historico = list(historico_anterior)    # carregado: o histórico não é sobrescrito

    async with async_playwright() as p:
        browser = await getattr(p, navegador).launch(headless=headless)

        try:
            for turma_nome in turmas_alvo:
                print(f"\n{'='*70}")
                print(f"📚 PROCESSANDO TURMA (base): {turma_nome}")
                print(f"{'='*70}")

                page_temp = await _abrir_por_turmas(browser, login, senha)
                if page_temp is None:
                    continue

                secoes = await listar_secao_turmas(page_temp, turma_nome)
                await page_temp.close()

                if not secoes:
                    print(f"\n⚠️ Nenhuma seção encontrada para '{turma_nome}'")
                    continue

                for secao_texto in secoes:
                    print(f"\n--- Iniciando seção: {secao_texto} ---")

                    page_secao = await _abrir_por_turmas(browser, login, senha)
                    if page_secao is None:
                        continue

                    if not await selecionar_turma(page_secao, secao_texto):
                        print(f"\n⚠️ Seção '{secao_texto}' não encontrada ao tentar selecionar")
                        await page_secao.close()
                        continue

                    alunos = await obter_alunos_matriculados(page_secao)
                    await page_secao.close()

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

                    if not alunos_para_processar:
                        print(f"✅ Todos os alunos de '{secao_texto}' já foram processados!")
                        continue

                    await processar_turma(
                        browser, secao_texto, alunos_para_processar,
                        sucessos, erros, historico, login, senha,
                    )

        finally:
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

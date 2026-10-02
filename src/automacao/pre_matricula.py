"""
pre_matricula.py (portado para src/automacao/)

Processo de pré-matrícula, em 4 etapas que compartilham o mesmo login:

  ETAPA 1 - COLETA:      percorre as turmas no portal de pré-matrícula e coleta
                         os alunos com intenção de vaga -> pre_matricula.json
                         (chave "turmas_intencao", mesclada sem apagar histórico)
  ETAPA 2 - CADASTRO:    consulta o cadastro completo de cada CPF coletado
                         -> pre_matricula.json (chave "cadastros")
  ETAPA 3 - CONTATOS:    cruza as etapas 1 e 2 e gera o CSV de importação do
                         Google Contacts -> TEMPLATE_PREENCHIDO_<data>.csv
  ETAPA 4 - PENDENTES:   re-consulta o CPF de quem sumiu da lista de
                         "aguardando" com situação apenas PRESUMIDA, para
                         descobrir se foi matriculado ou cancelado de fato.

Pontos de entrada (sem argparse/input(); prontos para virar botões de GUI):

  processo_completo_via_login(...)     etapas 1 -> 2 -> 4 -> 3
  completar_json_via_login(...)        lê as planilhas .xlsx do SERE em vez da
                                       etapa 1 (antigo --completar_json)
  verificar_pendentes_via_login(...)   somente a etapa 4 (antigo
                                       --somente-pendentes)

Diferenças em relação ao script original:
  - Caminhos vêm de paths.dados_ano_atual() (nada de caminho fixo do Samba).
  - Credenciais e "modo análise" são parâmetros, não globais.
  - Screenshots ficam em <dados do ano>/screenshots (antes: relativo ao cwd).
  - pre_matricula.json é gravado de forma atômica e NUNCA é sobrescrito se
    estiver ilegível (antes, um JSON corrompido era tratado como "vazio" e o
    histórico inteiro era apagado na próxima gravação).
  - Etapa 4 usa a opção correspondente à ESCOLA ALVO, e não a 1ª opção da
    lista (antes, aluno cancelado em outra escola e matriculado aqui ficava
    registrado como cancelado).
  - extrair_cep() usa regex (antes pegava qualquer palavra com hífen com 8+
    caracteres, como "9999-9999", antes do CEP real).
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from glob import glob
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from comum import paths
from comum.arquivos_json import (
    ArquivoJsonCorrompidoError,
    carregar_json,
    salvar_json_atomico,
)


# ==========================================================
# CONSTANTES
# ==========================================================

LOGIN_URL = "https://web.pontagrossa.pr.gov.br/prematricula/login"
INTENCOES_URL = "https://web.pontagrossa.pr.gov.br/prematricula/intencoes_vaga"
CONSULTA_URL = "https://web.pontagrossa.pr.gov.br/prematricula/consulta_cpf"

NOME_ESCOLA_BUSCA = "Judith"
NOME_ESCOLA_ALVO = "Judith Macedo Silveira"

# Valor convencionado gravado quando o aluno some da lista de "aguardando".
# É uma PRESUNÇÃO (o site não informa o motivo), não uma confirmação.
SITUACAO_PRESUNTIVA = "Cancelado"
MOTIVO_PRESUNTIVO = "CANCELADO VIA SISTEMA/RESPONSAVEL"

COLUNAS_CONTATOS_PADRAO = [
    "Name Prefix", "First Name", "Middle Name", "Last Name", "Name Suffix",
    "Phonetic First Name", "Phonetic Middle Name", "Phonetic Last Name",
    "Nickname", "File As", "E-mail 1 - Label", "E-mail 1 - Value",
    "Phone 1 - Label", "Phone 1 - Value", "Address 1 - Label",
    "Address 1 - Country", "Address 1 - Street", "Address 1 - Extended Address",
    "Address 1 - City", "Address 1 - Region", "Address 1 - Postal Code",
    "Address 1 - PO Box", "Organization Name", "Organization Title",
    "Organization Department", "Birthday", "Event 1 - Label", "Event 1 - Value",
    "Relation 1 - Label", "Relation 1 - Value", "Website 1 - Label",
    "Website 1 - Value", "Custom Field 1 - Label", "Custom Field 1 - Value",
    "Notes", "Labels",
]


class PreMatriculaCorrompidaError(ArquivoJsonCorrompidoError):
    """pre_matricula.json existe mas não pôde ser lido. O arquivo NÃO é tocado."""


# ==========================================================
# CAMINHOS (resolvidos na hora do uso, não na importação)
# ==========================================================

def _ano() -> str:
    return str(paths.ano_atual())


def pasta_base() -> Path:
    return Path(paths.dados_ano_atual())


def caminho_pre_matricula() -> Path:
    return pasta_base() / "pre_matricula.json"


def caminho_template() -> Path:
    return pasta_base() / "Google Contacts Import Template.csv"


def caminho_contatos() -> Path:
    return pasta_base() / f"TEMPLATE_PREENCHIDO_{datetime.now().strftime('%Y-%m-%d')}.csv"


def pasta_screenshots() -> Path:
    return pasta_base() / "screenshots"


def arquivo_mais_recente(padrao: str) -> str | None:
    """Arquivo mais recente da pasta de dados do ano que casa com o glob, ou None."""
    arquivos = glob(str(pasta_base() / padrao))
    if not arquivos:
        return None
    return max(arquivos, key=os.path.getmtime)


def _credenciais_padrao() -> tuple[str, str]:
    """Credenciais do portal de pré-matrícula (carregadas só quando necessárias)."""
    from comum.credenciais import MATRICULA, SENHA_PRE
    return MATRICULA, SENHA_PRE


# ==========================================================
# PERSISTÊNCIA DO pre_matricula.json
# ==========================================================

def _base_vazia() -> dict:
    return {"atualizado_em": None, "turmas_intencao": {}, "cadastros": {}}


def carregar_pre_matricula() -> dict:
    """
    Carrega o pre_matricula.json (base unificada: turmas_intencao + cadastros).

    Arquivo inexistente -> base vazia. Arquivo existente mas ilegível ->
    PreMatriculaCorrompidaError (o arquivo permanece intacto para conserto
    manual). Nunca devolve "vazio" no lugar de um arquivo corrompido: isso
    faria a próxima gravação apagar todo o histórico.
    """
    dados = carregar_json(
        caminho_pre_matricula(), _base_vazia, tipo_esperado=dict, erro=PreMatriculaCorrompidaError
    )
    dados.setdefault("turmas_intencao", {})
    dados.setdefault("cadastros", {})
    return dados


def salvar_pre_matricula(dados: dict) -> None:
    """Grava o pre_matricula.json de forma atômica, atualizando o timestamp."""
    dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    salvar_json_atomico(caminho_pre_matricula(), dados, indent=2)


def mesclar_turmas_intencao(turmas_antigas, turmas_novas):
    """
    Mescla a coleta atual com o que já existe, SEM apagar ninguém.

    pre_matricula.json é o guia histórico de todos que já passaram pela
    intenção de vaga. O site só mostra quem está "aguardando" no momento;
    quem some da lista (matriculado ou cancelado) não pode sumir do arquivo.

      - Chave do aluno: CPF (ou tr_id/nome se o CPF vier vazio), dentro da turma.
      - Já existe: é atualizado com o dado mais recente do site.
      - Novo: é adicionado.
      - Estava no arquivo e não veio agora: é MANTIDO, com
        presente_na_ultima_coleta=False. Na PRIMEIRA vez que isso acontece,
        e só se ainda não houver situação registrada, grava a situação
        PRESUNTIVA (SITUACAO_PRESUNTIVA / MOTIVO_PRESUNTIVO). Isso não é
        confirmação — a Etapa 4 substitui pelo dado real.
      - Turmas que não vieram na coleta atual são mantidas intactas.
    """

    def chave_aluno(aluno):
        cpf = (aluno.get("cpf") or "").strip()
        if cpf:
            return cpf
        return (aluno.get("tr_id") or aluno.get("nome") or "").strip()

    turmas_mescladas = {}

    for turma, alunos_antigos in (turmas_antigas or {}).items():
        turmas_mescladas[turma] = {
            chave_aluno(a): dict(a) for a in alunos_antigos if chave_aluno(a)
        }

    for turma, alunos_novos in (turmas_novas or {}).items():
        existentes = turmas_mescladas.setdefault(turma, {})
        chaves_vistas_agora = set()

        for aluno_novo in alunos_novos:
            chave = chave_aluno(aluno_novo)
            if not chave:
                continue
            chaves_vistas_agora.add(chave)

            aluno_atualizado = dict(aluno_novo)
            aluno_atualizado["presente_na_ultima_coleta"] = True
            existentes[chave] = aluno_atualizado

        for chave, aluno_antigo in existentes.items():
            if chave not in chaves_vistas_agora:
                estava_presente_antes = aluno_antigo.get("presente_na_ultima_coleta", True)
                aluno_antigo["presente_na_ultima_coleta"] = False

                if estava_presente_antes and not aluno_antigo.get("situacao"):
                    aluno_antigo["situacao"] = SITUACAO_PRESUNTIVA
                    aluno_antigo["motivo_cancelamento"] = MOTIVO_PRESUNTIVO

    return {
        turma: list(alunos_por_chave.values())
        for turma, alunos_por_chave in turmas_mescladas.items()
    }


# ==========================================================
# NAVEGAÇÃO / LOGIN / SCREENSHOTS
# ==========================================================

async def navegar_com_retry(page, url, tentativas=3, wait_until="domcontentloaded", pausa_antes=0.0):
    """
    Navega até `url` com retry (ex.: net::ERR_ABORTED quando um
    redirecionamento anterior ainda está em andamento). "domcontentloaded" é
    mais tolerante que "networkidle" em sites com polling/analytics.
    """
    if pausa_antes:
        await asyncio.sleep(pausa_antes)

    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            await page.goto(url, wait_until=wait_until, timeout=30000)
            return True
        except Exception as e:
            ultimo_erro = e
            print(f"Aviso: falha ao navegar para {url} (tentativa {tentativa}/{tentativas}): {e}")
            await asyncio.sleep(1.5 * tentativa)

    print(f"❌ Não foi possível navegar para {url} após {tentativas} tentativas: {ultimo_erro}")
    return False


async def safe_text(page, selector):
    try:
        return (await page.locator(selector).inner_text()).strip()
    except Exception:
        return ""


def _nome_arquivo_seguro(texto):
    texto = texto.strip().lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_")[:80]


async def capturar_tela(page, etapa, descricao, erro=False, analise=False):
    """
    Salva screenshot em <dados do ano>/screenshots.

    Screenshots de sucesso só são salvos com analise=True (antigo --a);
    os de erro/timeout são SEMPRE salvos.
    """
    if not analise and not erro:
        return

    try:
        pasta = pasta_screenshots()
        pasta.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prefixo = "ERRO" if erro else "ok"
        caminho = pasta / f"{timestamp}_{prefixo}_{etapa}_{_nome_arquivo_seguro(descricao)}.png"

        await page.screenshot(path=str(caminho), full_page=True)

        marcador = "❌" if erro else "📸"
        print(f"{marcador} Screenshot salvo: {caminho}  (tentando acessar: {page.url} | {descricao})")
    except Exception as e:
        print(f"Aviso: não foi possível salvar screenshot ({descricao}): {e}")


async def fazer_login(page, matricula, senha, analise=False):
    """Login único, reaproveitado por todas as etapas."""
    if not await navegar_com_retry(page, LOGIN_URL):
        await capturar_tela(page, "login", "falha ao abrir tela de login", erro=True, analise=analise)
        return False

    await capturar_tela(page, "login", "tela de login", analise=analise)

    # Campo de código/captcha visível: não dá para logar às cegas.
    campo_codigo = page.locator("div#hpcd input[name='codigo']")
    if await campo_codigo.count() > 0 and await campo_codigo.is_visible():
        print("❌ Tela de login exige um código/captcha (#hpcd) que o script não sabe preencher.")
        await capturar_tela(page, "login", "campo codigo captcha exigido", erro=True, analise=analise)
        return False

    await page.fill("#matricula", matricula)
    await page.fill("#senha", senha)
    await page.keyboard.press("Enter")

    # wait_for_url("**/prematricula/**") não serve: a própria URL de login
    # já bate no padrão. Espera assentar e confere se o formulário sumiu.
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("Aviso: Timeout esperando a página assentar após o submit do login.")

    campo_matricula = page.locator("#matricula")
    ainda_na_tela_login = (
        await campo_matricula.count() > 0 and await campo_matricula.is_visible()
    )

    if ainda_na_tela_login:
        mensagem_erro = await safe_text(page, ".alert, .invalid-feedback, .text-danger")
        if mensagem_erro:
            print(f"❌ Login falhou: {mensagem_erro}")
        else:
            print("❌ Login falhou: formulário de login ainda presente após o submit.")
        await capturar_tela(page, "login", "falha no login credenciais ou captcha", erro=True, analise=analise)
        return False

    await capturar_tela(page, "login", "pos login", analise=analise)
    return True


# ==========================================================
# ETAPA 1 - COLETA DE INTENÇÕES DE VAGA
# ==========================================================

async def etapa_coleta(page, analise=False):
    print("\n" + "=" * 60)
    print(f"ETAPA 1/4 - COLETA DE INTENÇÕES DE VAGA ({_ano()})")
    print("=" * 60)

    if not await navegar_com_retry(page, INTENCOES_URL, pausa_antes=1.0):
        await capturar_tela(page, "coleta", "falha ao abrir tela de intencoes", erro=True, analise=analise)
        return None
    await capturar_tela(page, "coleta", "tela de intencoes de vaga", analise=analise)

    # Selecionar a escola
    try:
        await page.wait_for_selector("input#nomeEscola", timeout=7000)
        await page.click("input#nomeEscola")
        await page.type("input#nomeEscola", NOME_ESCOLA_BUSCA, delay=200)

        try:
            await page.wait_for_selector("#listaEscolas a", timeout=7000)
            await capturar_tela(page, "coleta", "lista de escolas", analise=analise)
            escolas = page.locator("#listaEscolas a")
            count = await escolas.count()
            encontrou = False

            for i in range(count):
                h5 = escolas.nth(i).locator("h5")
                try:
                    texto = await h5.inner_text()
                    if NOME_ESCOLA_ALVO in texto:
                        await escolas.nth(i).click()
                        print(f"Escola selecionada: {texto}")
                        encontrou = True
                        break
                except Exception:
                    continue

            if not encontrou:
                print(f"Escola '{NOME_ESCOLA_ALVO}' não encontrada na lista.")
                await capturar_tela(page, "coleta", "escola nao encontrada na lista", erro=True, analise=analise)

        except PWTimeout:
            print("Não encontrei a lista de escolas.")
            await capturar_tela(page, "coleta", "timeout lista de escolas", erro=True, analise=analise)

    except PWTimeout:
        print("Campo nomeEscola não encontrado.")
        await capturar_tela(page, "coleta", "timeout campo nomeEscola", erro=True, analise=analise)
        return None

    # Pesquisar. select#sTurma já vem populado desde o carregamento, então o
    # sinal real de que a pesquisa terminou é a tabela #tableIntencoes.
    try:
        botao_pesquisar = page.locator("#bPesquisar")
        await botao_pesquisar.wait_for(state="visible", timeout=10000)

        for _ in range(20):
            if not await botao_pesquisar.is_disabled():
                break
            await asyncio.sleep(0.5)

        await botao_pesquisar.click()

        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass

        await page.wait_for_selector("#tableIntencoes", timeout=15000)
        await capturar_tela(page, "coleta", "resultado pesquisa escola", analise=analise)
    except Exception as e:
        print(f"Falha ao clicar em Pesquisar: {e}")
        await capturar_tela(page, "coleta", "falha ao clicar em pesquisar", erro=True, analise=analise)

        # Recuperação: o 1º clique às vezes acontece cedo demais.
        try:
            await asyncio.sleep(1.5)
            await page.click("#bPesquisar")
            await page.wait_for_selector("#tableIntencoes", timeout=10000)
            print("✓ Recuperado após novo clique em Pesquisar.")
            await capturar_tela(page, "coleta", "resultado pesquisa escola apos retry", analise=analise)
        except Exception as e2:
            print(f"Aviso: não foi possível confirmar o bloco de resultado após pesquisar: {e2}")
            print("Prosseguindo mesmo assim, pois o select de turmas já está disponível.")

    try:
        await page.wait_for_selector("select#sTurma", timeout=7000)
    except PWTimeout:
        print("Select de turmas não encontrado.")
        await capturar_tela(page, "coleta", "timeout select de turmas", erro=True, analise=analise)
        return None

    options = await page.eval_on_selector_all(
        "select#sTurma option",
        "opts => opts.map(o => ({value: o.value, label: o.textContent.trim()}))",
    )

    resultado = {
        "meta": {"url": INTENCOES_URL, "coletado_em": datetime.now().isoformat()},
        "turmas": {},
    }

    for opt in options:
        val = opt["value"]
        label = opt["label"]

        if not val or val.isspace():
            continue

        print(f"\nProcessando turma: {label} (value={val})")

        try:
            await page.select_option("select#sTurma", val)
            await asyncio.sleep(2.5)
            await page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Falha ao selecionar turma {label}: {e}")
            await capturar_tela(page, "coleta", f"falha ao selecionar turma {label}", erro=True, analise=analise)
            continue

        try:
            await page.click("#bPesquisar")
            await asyncio.sleep(1.5)
            await page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Falha ao clicar em pesquisar para {label}: {e}")
            await capturar_tela(page, "coleta", f"falha ao pesquisar turma {label}", erro=True, analise=analise)

        try:
            await page.wait_for_selector("table#tableIntencoes tbody tr", timeout=5000)
            await capturar_tela(page, "coleta", f"turma {label}", analise=analise)
        except PWTimeout:
            print(f"Nenhum registro na turma '{label}'.")
            await capturar_tela(page, "coleta", f"sem registros turma {label}", analise=analise)
            resultado["turmas"][label] = []
            continue

        try:
            rows = await page.query_selector_all("table#tableIntencoes tbody tr")
            turma_lista = []

            for row in rows:
                tds = await row.query_selector_all("td")

                async def text_of(td_idx, tds=tds):
                    try:
                        if td_idx < len(tds):
                            return (await tds[td_idx].inner_text()).strip()
                        return ""
                    except Exception:
                        return ""

                turma_lista.append(
                    {
                        "pos": await text_of(0),
                        "nome": await text_of(1),
                        "cpf": await text_of(2),
                        "tipo": await text_of(3),
                        "pontuacao": await text_of(4),
                        "tr_id": await row.get_attribute("id"),
                    }
                )

            resultado["turmas"][label] = turma_lista
            print(f"✓ Coletados {len(turma_lista)} registros da turma '{label}'.")

        except Exception as e:
            print(f"Erro ao processar linhas da turma '{label}': {e}")
            await capturar_tela(page, "coleta", f"erro processando turma {label}", erro=True, analise=analise)
            resultado["turmas"][label] = []

    try:
        pre_matricula = carregar_pre_matricula()
        pre_matricula["turmas_intencao"] = mesclar_turmas_intencao(
            pre_matricula.get("turmas_intencao", {}), resultado["turmas"]
        )
        salvar_pre_matricula(pre_matricula)
        print(f"\n✅ Etapa 1 concluída. Resultado salvo em: {caminho_pre_matricula()}")
    except PreMatriculaCorrompidaError:
        raise
    except Exception as e:
        print(f"Erro ao salvar arquivo da etapa 1: {e}")
        return None

    return resultado


# ==========================================================
# ETAPA 2 - CONSULTA DE CADASTRO POR CPF
# ==========================================================

def _extrair_motivo_situacao(situacao):
    """
    Separa, do texto bruto de "Situação" (ex.: "Cancelado. Motivo: Responsável
    desistiu da vaga (A aluna permanecerá ...)"), o motivo e a observação
    entre parênteses. Sem "Motivo:" no texto -> ("", "").
    """
    if not situacao:
        return "", ""

    m = re.search(r"Motivo:\s*(.*?)(?:\s*\((.*?)\))?\s*$", situacao)
    if not m:
        return "", ""

    return (m.group(1) or "").strip(), (m.group(2) or "").strip()


async def _extrair_escolas_escolhidas(page):
    """
    Extrai o fieldset "Escolas Escolhidas": a turma pretendida (#turma0) e,
    para cada opção existente (1, 2 e 3 -> #e10/#status10, #e20/#status20,
    #e30/#status30), escola, situação bruta e motivo/observação.
    """
    turma = await safe_text(page, "span#turma0")

    opcoes = []
    for n in (1, 2, 3):
        seletor_escola = f"span#e{n}0"
        if await page.locator(seletor_escola).count() == 0:
            continue

        escola = await safe_text(page, seletor_escola)
        if not escola:
            continue

        situacao = await safe_text(page, f"span#status{n}0")
        motivo, observacao = _extrair_motivo_situacao(situacao)

        opcoes.append(
            {
                "opcao": n,
                "escola": escola,
                "situacao": situacao,
                "motivo_cancelamento": motivo,
                "observacao": observacao,
            }
        )

    return {"turma": turma, "opcoes": opcoes}


def _normalizar_maiusculas_aluno(aluno_dados):
    """Dados do aluno em MAIÚSCULA; e-mail em minúscula."""
    for campo in ("nome_aluno", "nome_responsavel", "endereco"):
        if aluno_dados.get(campo):
            aluno_dados[campo] = aluno_dados[campo].upper()

    if aluno_dados.get("email"):
        aluno_dados["email"] = aluno_dados["email"].strip().lower()

    if aluno_dados.get("criterios"):
        aluno_dados["criterios"] = [c.upper() for c in aluno_dados["criterios"] if c is not None]

    escolas = aluno_dados.get("escolas_escolhidas")
    if escolas:
        if escolas.get("turma"):
            escolas["turma"] = escolas["turma"].upper()
        for opcao in escolas.get("opcoes", []):
            for campo in ("escola", "situacao", "motivo_cancelamento", "observacao"):
                if opcao.get(campo):
                    opcao[campo] = opcao[campo].upper()


async def consultar_cpf(page, cpf, etapa="cadastro", analise=False):
    """
    Consulta um CPF na tela de consulta e devolve o dict de cadastro (mesmo
    formato de pre_matricula.json -> cadastros[cpf]), ou None se não houve
    resultado. `etapa` só rotula os screenshots.
    """
    print(f"\nConsultando CPF: {cpf}")
    if not await navegar_com_retry(page, CONSULTA_URL):
        await capturar_tela(page, etapa, f"falha ao abrir consulta cpf {cpf}", erro=True, analise=analise)
        return None
    await capturar_tela(page, etapa, f"tela de consulta cpf {cpf}", analise=analise)

    try:
        await page.wait_for_selector("input#cpfAluno", timeout=7000)
        await page.fill("input#cpfAluno", cpf)
        await page.keyboard.press("Enter")
    except PWTimeout:
        print(f"Campo CPF não encontrado para {cpf}")
        await capturar_tela(page, etapa, f"timeout campo cpf {cpf}", erro=True, analise=analise)
        return None

    try:
        await page.wait_for_selector("div#divCadastros", timeout=7000)
        await capturar_tela(page, etapa, f"resultado cpf {cpf}", analise=analise)

        aluno_dados = {
            "cpf": cpf,
            "nome_aluno": await safe_text(page, "h5#dNomeAluno")
            or await safe_text(page, "span#dNome0"),
            "nome_responsavel": await safe_text(page, "span#dNomeResponsavel0"),
            "telefone": await safe_text(page, "span#dTelefoneResponsavel0"),
            "email": await safe_text(page, "span#dEmailResponsavel0"),
            "endereco": " ".join(
                [
                    await safe_text(page, "span#dLogradouro0"),
                    await safe_text(page, "span#dNumero0"),
                    await safe_text(page, "span#dComplemento0"),
                    await safe_text(page, "span#dBairro0"),
                    await safe_text(page, "span#dMunicipio0"),
                    await safe_text(page, "span#dUF0"),
                    await safe_text(page, "span#dCEP0"),
                ]
            ),
            "criterios": await page.locator("div#dCriterios0 li").all_inner_texts(),
            "escolas_escolhidas": await _extrair_escolas_escolhidas(page),
        }

        _normalizar_maiusculas_aluno(aluno_dados)

        print(f"✅ Dados coletados para {cpf}")
        return aluno_dados

    except PWTimeout:
        print(f"Nenhum resultado encontrado para {cpf}")
        await capturar_tela(page, etapa, f"timeout resultado cpf {cpf}", erro=True, analise=analise)
        return None


async def etapa_cadastro(page, dados_prematricula, analise=False):
    print("\n" + "=" * 60)
    print("ETAPA 2/4 - CONSULTA DE CADASTRO POR CPF")
    print("=" * 60)

    cpfs = []
    for _turma, alunos in dados_prematricula.get("turmas", {}).items():
        for aluno in alunos:
            cpf = aluno.get("cpf")
            if cpf:
                cpfs.append(cpf)

    print(f"Total de CPFs encontrados: {len(cpfs)}")

    resultados = {}
    for cpf in cpfs:
        aluno_dados = await consultar_cpf(page, cpf, etapa="cadastro", analise=analise)
        if aluno_dados is not None:
            resultados[cpf] = aluno_dados

    pre_matricula = carregar_pre_matricula()
    pre_matricula["cadastros"].update(resultados)
    salvar_pre_matricula(pre_matricula)

    print(f"\n✅ Etapa 2 concluída. Arquivo salvo em: {caminho_pre_matricula()}")
    return resultados


# ==========================================================
# ETAPA 4 - VERIFICAÇÃO DE PENDENTES (matriculados/cancelados)
# ==========================================================

def _situacao_e_presuntiva(aluno):
    """
    True se a situação registrada em turmas_intencao é a presunção automática
    (motivo == MOTIVO_PRESUNTIVO) ou se não há situação nenhuma.
    """
    if not aluno.get("situacao"):
        return True
    return aluno.get("motivo_cancelamento") == MOTIVO_PRESUNTIVO


def listar_pendentes_para_verificar(turmas_intencao):
    """
    Lista (turma, cpf, aluno) de quem sumiu da última coleta
    (presente_na_ultima_coleta is False) e ainda tem situação presuntiva ou
    vazia. Sem CPF não há como consultar; fica com a situação presumida.
    """
    pendentes = []
    for turma, alunos in (turmas_intencao or {}).items():
        for aluno in alunos:
            if aluno.get("presente_na_ultima_coleta") is False and _situacao_e_presuntiva(aluno):
                cpf = (aluno.get("cpf") or "").strip()
                if not cpf:
                    continue
                pendentes.append((turma, cpf, aluno))
    return pendentes


def opcao_da_escola_alvo(opcoes, escola_alvo=NOME_ESCOLA_ALVO):
    """
    Devolve a opção de escola que corresponde à escola alvo (a situação que
    interessa a ESTA escola), ou None se ela existe mas ainda não tem
    situação (aluno "aguardando").

    Se a escola alvo nem aparece nas opções (formato inesperado), cai no
    comportamento antigo: primeira opção que tenha situação.

    O original sempre pegava a primeira opção com situação, qualquer que
    fosse a escola: aluno cancelado na opção 1 (outra escola) e matriculado
    aqui na opção 2 era gravado como cancelado.
    """
    alvo = escola_alvo.upper()
    da_escola = [op for op in (opcoes or []) if alvo in (op.get("escola") or "").upper()]

    if da_escola:
        return next((op for op in da_escola if op.get("situacao")), None)

    return next((op for op in (opcoes or []) if op.get("situacao")), None)


def _aplicar_opcao_no_aluno(aluno, opcao):
    """Copia situação, motivo e observação da MESMA opção para o registro."""
    aluno["situacao"] = opcao.get("situacao") or ""
    aluno["motivo_cancelamento"] = opcao.get("motivo_cancelamento") or ""
    aluno["observacao"] = opcao.get("observacao") or ""


async def etapa_verificar_pendentes(page, dados_pre_matricula=None, analise=False):
    """
    ETAPA 4/4 - Para cada aluno "pendente" (sumiu da lista e com situação
    presumida), re-consulta o CPF e, havendo situação real na opção desta
    escola, substitui a presunção em turmas_intencao e atualiza cadastros.

    Retorna {"total_pendentes", "confirmados", "sem_resposta": [cpfs]}.
    """
    print("\n" + "=" * 60)
    print("ETAPA 4/4 - VERIFICAÇÃO DE PENDENTES (MATRICULADOS/CANCELADOS)")
    print("=" * 60)

    pre_matricula = dados_pre_matricula or carregar_pre_matricula()
    turmas_intencao = pre_matricula.get("turmas_intencao", {})

    pendentes = listar_pendentes_para_verificar(turmas_intencao)
    print(f"Total de pendentes a verificar: {len(pendentes)}")

    if not pendentes:
        print("Nenhum pendente para verificar. Nada a fazer.")
        return {"total_pendentes": 0, "confirmados": 0, "sem_resposta": []}

    confirmados = 0
    sem_resposta = []
    cadastros = pre_matricula.setdefault("cadastros", {})

    for turma, cpf, aluno in pendentes:
        aluno_dados = await consultar_cpf(page, cpf, etapa="verificar_pendentes", analise=analise)

        if aluno_dados is None:
            sem_resposta.append(cpf)
            continue

        cadastros[cpf] = aluno_dados

        opcoes = (aluno_dados.get("escolas_escolhidas") or {}).get("opcoes", [])
        opcao = opcao_da_escola_alvo(opcoes)

        if opcao and opcao.get("situacao"):
            _aplicar_opcao_no_aluno(aluno, opcao)
            confirmados += 1
            print(f"✅ CPF {cpf} ({turma}): situação confirmada -> {opcao['situacao']}")
        else:
            sem_resposta.append(cpf)
            print(f"⚠️ CPF {cpf} ({turma}): consulta não retornou situação clara.")

    salvar_pre_matricula(pre_matricula)

    print("\n✅ Etapa 4 concluída.")
    print(f"   Pendentes verificados: {len(pendentes)}")
    print(f"   Confirmados (matriculado/cancelado real): {confirmados}")
    print(f"   Sem resposta clara (mantidos como presumidos): {len(sem_resposta)}")
    print(f"   Arquivo salvo em: {caminho_pre_matricula()}")

    return {"total_pendentes": len(pendentes), "confirmados": confirmados, "sem_resposta": sem_resposta}


def reconciliar_situacoes(pre_matricula, aplicar=False):
    """
    Confere, SEM acessar o site, a situação gravada em turmas_intencao contra
    a opção da escola alvo em cadastros[cpf] (dados já coletados).

    Serve para achar (e, com aplicar=True, corrigir) registros gravados pelo
    critério antigo da Etapa 4 (1ª opção com situação, qualquer escola).

    Só considera quem tem situação real na opção da escola alvo (aluno ainda
    "aguardando" não tem, e é ignorado). Retorna a lista de divergências:
      {"turma", "cpf", "nome", "situacao_atual", "situacao_correta"}

    aplicar=False (padrão) só relata; nada é alterado. Quem chama decide
    salvar (salvar_pre_matricula) depois de aplicar=True.
    """
    cadastros = pre_matricula.get("cadastros", {})
    divergencias = []

    for turma, alunos in pre_matricula.get("turmas_intencao", {}).items():
        for aluno in alunos:
            cpf = (aluno.get("cpf") or "").strip()
            cadastro = cadastros.get(cpf)
            if not cadastro:
                continue

            opcoes = (cadastro.get("escolas_escolhidas") or {}).get("opcoes", [])
            alvo = NOME_ESCOLA_ALVO.upper()
            opcao = next(
                (
                    op for op in opcoes
                    if alvo in (op.get("escola") or "").upper() and op.get("situacao")
                ),
                None,
            )
            if not opcao:
                continue

            if aluno.get("situacao") != opcao["situacao"]:
                divergencias.append(
                    {
                        "turma": turma,
                        "cpf": cpf,
                        "nome": aluno.get("nome", ""),
                        "situacao_atual": aluno.get("situacao"),
                        "situacao_correta": opcao["situacao"],
                    }
                )
                if aplicar:
                    _aplicar_opcao_no_aluno(aluno, opcao)

    return divergencias


# ==========================================================
# --completar_json: LEITURA DAS PLANILHAS (.xlsx) DO SERE
# ==========================================================
#
# Alternativa à Etapa 1: lê os relatórios exportados (Alunos Matriculados e
# Intenções de Vaga), que têm formato de grade: blocos lado a lado, um por
# turma, cada um com uma linha de título (turma) e logo abaixo o cabeçalho
# (Nome, CPF, Opção, Pontuação...). Um bloco só conta como "de turma" se
# tiver coluna CPF, o que descarta o bloco "Alunos - Contato".

def _normalizar_cabecalho(texto):
    """"Opção" -> "opcao", "Matriculado Em" -> "matriculado_em"."""
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", "_", texto)


def _detectar_layout_planilha(ws):
    """(linha_titulo, linha_cabecalho): a linha com a célula "Nome" e a de cima."""
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            valor = ws.cell(row=r, column=c).value
            if isinstance(valor, str) and valor.strip().lower() == "nome":
                return r - 1, r
    return None, None


def _extrair_blocos_planilha(ws, linha_titulo, linha_cabecalho):
    """
    Lista de blocos {"titulo": "Infantil IV", "colunas": [(col_idx, nome_norm), ...]}.
    Bloco novo = coluna com valor no título E no cabeçalho; suas colunas vão
    até a primeira célula de cabeçalho vazia.
    """
    blocos = []
    max_col = ws.max_column
    c = 1
    while c <= max_col:
        titulo = ws.cell(row=linha_titulo, column=c).value
        cabecalho = ws.cell(row=linha_cabecalho, column=c).value
        if titulo and cabecalho:
            colunas = []
            cc = c
            while cc <= max_col:
                h = ws.cell(row=linha_cabecalho, column=cc).value
                if h is None or str(h).strip() == "":
                    break
                colunas.append((cc, _normalizar_cabecalho(h)))
                cc += 1
            blocos.append({"titulo": str(titulo).strip(), "colunas": colunas})
            c = cc
        else:
            c += 1
    return blocos


def _selecionar_aba_dados(wb):
    """Aba com o nome da escola alvo; senão a 1ª que não seja "Escolas"."""
    if NOME_ESCOLA_ALVO in wb.sheetnames:
        return wb[NOME_ESCOLA_ALVO]
    for nome in wb.sheetnames:
        if nome.strip().lower() != "escolas":
            return wb[nome]
    return wb[wb.sheetnames[0]]


def extrair_turmas_de_planilha(caminho, aplicar_filtro_opcao, origem):
    """
    Lê um relatório .xlsx e devolve {turma: [aluno, ...]} no formato da
    Etapa 1 (pos, nome, cpf, tipo, pontuacao, tr_id) + "opcao", "origem" e
    "extra". aplicar_filtro_opcao=True mantém SOMENTE Opção == 1 (relatório
    de Intenções); False mantém todos (relatório de Matriculados).
    """
    import openpyxl

    if not caminho or not os.path.exists(caminho):
        print(f"Aviso: planilha não encontrada - {caminho}")
        return {}

    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = _selecionar_aba_dados(wb)

    linha_titulo, linha_cabecalho = _detectar_layout_planilha(ws)
    if linha_titulo is None:
        print(f"Aviso: não encontrei o layout esperado (cabeçalho 'Nome') em {caminho}")
        return {}

    blocos = _extrair_blocos_planilha(ws, linha_titulo, linha_cabecalho)

    resultado = {}
    total_ignorados_opcao = 0

    for bloco in blocos:
        nomes_colunas = dict(bloco["colunas"])
        if "cpf" not in nomes_colunas.values():
            continue
        if "nome" not in nomes_colunas.values():
            continue

        col_nome = next(c for c, h in bloco["colunas"] if h == "nome")
        alunos_turma = []
        pos = 0

        linha = linha_cabecalho + 1
        while linha <= ws.max_row:
            valor_nome = ws.cell(row=linha, column=col_nome).value
            if valor_nome not in (None, ""):
                registro_bruto = {
                    h: ws.cell(row=linha, column=c).value for c, h in bloco["colunas"]
                }

                opcao_valor = registro_bruto.get("opcao")
                if aplicar_filtro_opcao:
                    opcao_num = None
                    if opcao_valor not in (None, ""):
                        try:
                            opcao_num = int(float(str(opcao_valor).strip()))
                        except ValueError:
                            opcao_num = None
                    if opcao_num != 1:
                        total_ignorados_opcao += 1
                        linha += 1
                        continue

                pos += 1
                cpf_valor = registro_bruto.get("cpf")

                extras = {
                    k: v
                    for k, v in registro_bruto.items()
                    if k not in ("nome", "cpf", "opcao", "pontuacao") and v not in (None, "")
                }

                aluno = {
                    "pos": str(pos),
                    "nome": str(valor_nome).strip(),
                    "cpf": str(cpf_valor).strip() if cpf_valor not in (None, "") else "",
                    "tipo": None,
                    "pontuacao": registro_bruto.get("pontuacao"),
                    "tr_id": None,
                    "opcao": opcao_valor,
                    "origem": origem,
                }
                if extras:
                    aluno["extra"] = extras

                alunos_turma.append(aluno)

            linha += 1

        if alunos_turma:
            resultado[bloco["titulo"]] = alunos_turma

    if aplicar_filtro_opcao and total_ignorados_opcao:
        print(
            f"  (ignorados {total_ignorados_opcao} registros com Opção diferente de 1 "
            f"em {os.path.basename(caminho)})"
        )

    return resultado


def _mesclar_dicts_turmas(destino, novo):
    """Combina dois {turma: [alunos]} concatenando as listas."""
    for turma, alunos in (novo or {}).items():
        destino.setdefault(turma, [])
        destino[turma].extend(alunos)
    return destino


async def completar_json_a_partir_de_planilhas(page, caminho_matriculados, caminho_intencoes, analise=False):
    """
    1. Lê os dois .xlsx (filtro Opção = 1 só nas Intenções).
    2. Mescla em turmas_intencao (mesma regra da Etapa 1, sem apagar histórico).
    3. Reaproveita a Etapa 2 para consultar o cadastro de cada CPF.
    """
    print("\n" + "=" * 60)
    print("--completar_json - LENDO PLANILHAS (.xlsx)")
    print("=" * 60)

    print(f"\nLendo Matriculados: {caminho_matriculados}")
    turmas_matriculados = extrair_turmas_de_planilha(
        caminho_matriculados, aplicar_filtro_opcao=False, origem="planilha_matriculados"
    )
    print(f"✓ {sum(len(v) for v in turmas_matriculados.values())} alunos lidos do relatório de Matriculados.")

    print(f"\nLendo Intenções de Vaga: {caminho_intencoes}")
    turmas_intencoes = extrair_turmas_de_planilha(
        caminho_intencoes, aplicar_filtro_opcao=True, origem="planilha_intencoes"
    )
    print(f"✓ {sum(len(v) for v in turmas_intencoes.values())} alunos lidos do relatório de Intenções (somente Opção = 1).")

    if not turmas_matriculados and not turmas_intencoes:
        print("❌ Nenhum dado lido das planilhas. Abortando --completar_json.")
        return None

    turmas_combinadas = {}
    _mesclar_dicts_turmas(turmas_combinadas, turmas_matriculados)
    _mesclar_dicts_turmas(turmas_combinadas, turmas_intencoes)

    pre_matricula = carregar_pre_matricula()
    pre_matricula["turmas_intencao"] = mesclar_turmas_intencao(
        pre_matricula.get("turmas_intencao", {}), turmas_combinadas
    )
    salvar_pre_matricula(pre_matricula)
    print(f"\n✅ Turmas das planilhas mescladas em: {caminho_pre_matricula()}")

    dados_processados = await etapa_cadastro(page, {"turmas": turmas_combinadas}, analise=analise)

    print("\n" + "=" * 60)
    print("✅ --completar_json FINALIZADO")
    print("=" * 60)

    return dados_processados


# ==========================================================
# ETAPA 3 - GERAÇÃO DO CSV DE CONTATOS (Google Contacts)
# ==========================================================

def extrair_turma_e_aluno(dados_aluno_cpf, dados_prematricula):
    # A Etapa 1 devolve "turmas" em memória; o arquivo guarda "turmas_intencao".
    # Aceitar as duas evita 0 contatos se a Etapa 3 ler direto do arquivo.
    turmas = dados_prematricula.get("turmas") or dados_prematricula.get("turmas_intencao") or {}
    for turma, alunos in turmas.items():
        for aluno in alunos:
            if aluno.get("cpf") == dados_aluno_cpf or aluno.get("tr_id") == dados_aluno_cpf:
                turma_limpa = turma.replace(" do Ensino Fundamental", "").strip()
                return turma_limpa, aluno.get("nome", "")
    return None, None


_RE_CEP = re.compile(r"(?<!\d)(\d{5})-?(\d{3})(?!\d)")


def extrair_cep(endereco):
    """
    CEP (NNNNN-NNN) do endereço. O CEP é o último campo do endereço montado
    em consultar_cpf(), então vale a ÚLTIMA ocorrência (evita confundir com
    número de telefone/complemento, ex.: "9999-9999").
    """
    achados = _RE_CEP.findall(endereco or "")
    if not achados:
        return ""
    a, b = achados[-1]
    return f"{a}-{b}"


def processar_contatos(dados_alunos, dados_prematricula):
    # Aceita lista, {cpf: aluno} ou um único registro (dict com "cpf" direto).
    if isinstance(dados_alunos, list):
        alunos_list = dados_alunos
    elif isinstance(dados_alunos, dict):
        alunos_list = [dados_alunos] if "cpf" in dados_alunos else list(dados_alunos.values())
    else:
        alunos_list = []

    agrupados = defaultdict(list)

    for aluno in alunos_list:
        cpf = aluno.get("cpf", "")
        nome_responsavel = (aluno.get("nome_responsavel") or "").strip()
        telefone = (aluno.get("telefone") or "").strip()
        email = (aluno.get("email") or "").strip()
        endereco = (aluno.get("endereco") or "").strip()

        turma, nome_aluno = extrair_turma_e_aluno(cpf, dados_prematricula)
        if not turma or not nome_responsavel:
            continue

        chave = telefone if telefone else nome_responsavel.lower()

        agrupados[chave].append(
            {
                "turma": turma,
                "nome_aluno": nome_aluno,
                "nome_responsavel": nome_responsavel,
                "telefone": telefone,
                "email": email,
                "endereco": endereco,
            }
        )

    ano = _ano()
    contatos = []
    for _chave, registros in agrupados.items():
        turmas = sorted(set(r["turma"] for r in registros))
        alunos = [r["nome_aluno"] for r in registros]
        primeiro = registros[0]

        nome_prefix = f"{' E '.join(turmas)} - {ano} - RESPONSAVEL DO {' E DO '.join(alunos)}"

        contatos.append(
            {
                "First Name": nome_prefix,
                "E-mail 1 - Label": "Home",
                "E-mail 1 - Value": primeiro["email"],
                "Phone 1 - Label": "Mobile",
                "Phone 1 - Value": primeiro["telefone"],
                "Address 1 - Postal Code": extrair_cep(primeiro["endereco"]),
                "Relation 1 - Value": primeiro["nome_responsavel"],
                "Website 1 - Label": "Homepage",
                "Website 1 - Value": "",
                "Custom Field 1 - Label": "Endereço Completo",
                "Custom Field 1 - Value": primeiro["endereco"],
                "Labels - " + ano: ano,
            }
        )

    return contatos


def obter_colunas_template():
    template = caminho_template()
    try:
        with open(template, "r", encoding="utf-8") as f:
            return next(csv.reader(f))
    except FileNotFoundError:
        print(f"Aviso: Template não encontrado em {template}")
        print("Usando colunas padrão do Google Contacts...")
        return list(COLUNAS_CONTATOS_PADRAO)


def exportar_csv(contatos):
    """Grava o CSV de contatos e devolve o caminho (ou None se falhar)."""
    destino = caminho_contatos()
    try:
        colunas = obter_colunas_template()

        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=colunas, delimiter=",")
            writer.writeheader()
            for contato in contatos:
                writer.writerow({col: contato.get(col, "") for col in colunas})

        print("✓ Arquivo CSV criado com sucesso!")
        print(f"✓ Arquivo salvo em: {destino}")
        print(f"✓ Total de contatos exportados: {len(contatos)}")
        return destino

    except Exception as e:
        print(f"Erro ao criar arquivo CSV: {e}")
        return None


def etapa_contatos(dados_processados, dados_prematricula):
    print("\n" + "=" * 60)
    print("ETAPA 3/4 - GERAÇÃO DO CSV DE CONTATOS")
    print("=" * 60)

    contatos = processar_contatos(dados_processados, dados_prematricula)

    if not contatos:
        print("Nenhum contato foi processado. Verifique os dados coletados.")
        return None

    print(f"Total de contatos processados: {len(contatos)}\n")
    print("Preview dos contatos:")
    print("-" * 60)
    for i, contato in enumerate(contatos[:3], 1):
        print(f"{i}. {contato['First Name']}")
        print(f"   E-mail: {contato['E-mail 1 - Value']}")
        print(f"   Telefone: {contato['Phone 1 - Value']}")
        print(f"   CEP: {contato['Address 1 - Postal Code']}\n")
    if len(contatos) > 3:
        print(f"... e mais {len(contatos) - 3} contatos\n")

    print("Gerando arquivo CSV...")
    return exportar_csv(contatos)


# ==========================================================
# PONTOS DE ENTRADA (sessão de navegador + login)
# ==========================================================

class _Sessao:
    """Abre navegador + página, faz login e fecha ao sair. `ok` diz se logou."""

    def __init__(self, matricula, senha, analise, navegador, headless):
        if matricula is None or senha is None:
            m, s = _credenciais_padrao()
            matricula = m if matricula is None else matricula
            senha = s if senha is None else senha
        self.matricula, self.senha = matricula, senha
        self.analise, self.navegador, self.headless = analise, navegador, headless
        self.page = None
        self.ok = False
        self._pw = None
        self._browser = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        try:
            self._browser = await getattr(self._pw, self.navegador).launch(headless=self.headless)
            context = await self._browser.new_context()
            self.page = await context.new_page()
            self.ok = await fazer_login(self.page, self.matricula, self.senha, analise=self.analise)
            if not self.ok:
                print("❌ Login falhou. Abortando processo.")
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()
            self._browser = self._pw = None
        return False


async def processo_completo_via_login(
    matricula=None,
    senha=None,
    analise=False,
    pular_pendentes=False,
    navegador="chromium",
    headless=True,
):
    """
    Etapas 1 -> 2 -> 4 -> 3 numa única sessão. `analise=True` salva
    screenshot de cada etapa (antigo --a); `pular_pendentes=True` pula a
    Etapa 4 (antigo --pular-pendentes).

    Devolve dict {"ok", "resumo_pendentes", "arquivo_contatos"}; "ok" é False
    se o login ou a Etapa 1 falharem.
    """
    print("=" * 60)
    print(f"PROCESSO DE PRÉ-MATRÍCULA - {_ano()}")
    if analise:
        print("Modo de análise ativo: screenshots de cada etapa serão salvos.")
    print("=" * 60)

    resumo_pendentes = None

    async with _Sessao(matricula, senha, analise, navegador, headless) as sessao:
        if not sessao.ok:
            return {"ok": False, "resumo_pendentes": None, "arquivo_contatos": None}

        dados_prematricula = await etapa_coleta(sessao.page, analise=analise)
        if dados_prematricula is None:
            print("❌ Etapa 1 falhou. Abortando processo.")
            return {"ok": False, "resumo_pendentes": None, "arquivo_contatos": None}

        dados_processados = await etapa_cadastro(sessao.page, dados_prematricula, analise=analise)

        if not pular_pendentes:
            resumo_pendentes = await etapa_verificar_pendentes(sessao.page, analise=analise)
        else:
            print("\n(Etapa 4 pulada)")

    arquivo_contatos = etapa_contatos(dados_processados, dados_prematricula)

    print("\n" + "=" * 60)
    print("✅ PROCESSO COMPLETO FINALIZADO")
    if resumo_pendentes is not None:
        print(
            f"   Pendentes verificados: {resumo_pendentes['total_pendentes']} | "
            f"Confirmados: {resumo_pendentes['confirmados']} | "
            f"Sem resposta: {len(resumo_pendentes['sem_resposta'])}"
        )
    print("=" * 60)

    return {"ok": True, "resumo_pendentes": resumo_pendentes, "arquivo_contatos": arquivo_contatos}


async def completar_json_via_login(
    caminho_matriculados=None,
    caminho_intencoes=None,
    matricula=None,
    senha=None,
    analise=False,
    navegador="chromium",
    headless=True,
):
    """
    Antigo --completar_json: lê os relatórios .xlsx (padrão: o mais recente
    "Relatorio_Alunos_Matriculados*.xlsx" / "Relatorio_Intencoes_Vaga*.xlsx"
    na pasta de dados do ano) e consulta o cadastro de cada CPF no site.
    Requer openpyxl. Devolve {cpf: cadastro} ou None.
    """
    caminho_matriculados = caminho_matriculados or arquivo_mais_recente("Relatorio_Alunos_Matriculados*.xlsx")
    caminho_intencoes = caminho_intencoes or arquivo_mais_recente("Relatorio_Intencoes_Vaga*.xlsx")

    if not caminho_matriculados and not caminho_intencoes:
        print(
            "❌ Nenhuma planilha encontrada. Informe os caminhos, ou coloque os "
            f"arquivos em:\n   {pasta_base()}"
        )
        return None

    async with _Sessao(matricula, senha, analise, navegador, headless) as sessao:
        if not sessao.ok:
            return None
        return await completar_json_a_partir_de_planilhas(
            sessao.page, caminho_matriculados, caminho_intencoes, analise=analise
        )


async def verificar_pendentes_via_login(
    matricula=None,
    senha=None,
    analise=False,
    navegador="chromium",
    headless=True,
):
    """Antigo --somente-pendentes: roda só a Etapa 4. Devolve o resumo ou None."""
    async with _Sessao(matricula, senha, analise, navegador, headless) as sessao:
        if not sessao.ok:
            return None
        resumo = await etapa_verificar_pendentes(sessao.page, analise=analise)

    print("\n" + "=" * 60)
    print("✅ --somente-pendentes FINALIZADO")
    print("=" * 60)
    return resumo

"""
prematricula_api.py — Infraestrutura compartilhada do portal de Pré-Matrícula
=============================================================================
Portado de AUTO_SERE/pre_matricula.py (utilitários e login, reaproveitados
pelas 4 etapas) para src/comum/prematricula_api.py.

O portal de Pré-Matrícula (web.pontagrossa.pr.gov.br/prematricula) é um
site DIFERENTE do SERE (sere.pr.gov.br), com login próprio
(MATRICULA_PREMATRICULA/SENHA_PREMATRICULA — ver src.comum.credenciais) e
navegação/seletores próprios. Nenhuma função de src.comum.sere_api se
aplica aqui.

Funções aqui: fazer_login, navegar_com_retry, capturar_tela (screenshots
de diagnóstico), safe_text, e consultar_cpf — usada por 3 etapas
diferentes (cadastro, verificar_pendentes, e o modo --completar_json), por
isso vive aqui em vez de duplicada em cada arquivo de etapa.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Credenciais: MATRICULA/SENHA_PRE (import direto de um módulo
   "credenciais" solto) trocadas por
   src.comum.credenciais.MATRICULA_PREMATRICULA/SENHA_PREMATRICULA.

2. ANALISE_CODIGO: era uma variável global de módulo, setada por main() a
   partir da flag --a/--analise-codigo (argparse). Como argparse foi
   removido (decisão do usuário, 03/09/2026 — mesma decisão já tomada
   para outros scripts), capturar_tela() agora recebe `analise_codigo`
   como parâmetro explícito em vez de ler uma global — quem orquestra
   (ver src.automacao.prematricula) decide se quer o modo de análise
   ligado, sem precisar de estado global compartilhado entre módulos.
   Screenshots de ERRO continuam sempre salvos, independente do parâmetro
   — comportamento idêntico ao original.

3. PASTA_SCREENSHOTS: era relativa ao diretório de execução
   (Path("screenshots")). Agora é uma subpasta de
   src.comum.paths.dados_ano_atual() (dados/<ano>/screenshots) — mesma
   arquitetura dos demais scripts.

Toda a lógica de navegação/login/parse (retries, detecção de captcha,
verificação pós-submit de que o login realmente saiu da tela de login,
extração de escolas_escolhidas/motivo_cancelamento) é idêntica ao
original — nenhuma regra de negócio foi alterada.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import TimeoutError as PWTimeout

from src.comum.credenciais import MATRICULA_PREMATRICULA, SENHA_PREMATRICULA
from src.comum import paths as _paths

LOGIN_URL    = "https://web.pontagrossa.pr.gov.br/prematricula/login"
INTENCOES_URL = "https://web.pontagrossa.pr.gov.br/prematricula/intencoes_vaga"
CONSULTA_URL  = "https://web.pontagrossa.pr.gov.br/prematricula/consulta_cpf"

NOME_ESCOLA_BUSCA = "Judith"
NOME_ESCOLA_ALVO  = "Judith Macedo Silveira"

PASTA_SCREENSHOTS = _paths.dados_ano_atual() / "screenshots"


# ==========================================================
# NAVEGAÇÃO / DIAGNÓSTICO
# ==========================================================

async def navegar_com_retry(page, url, tentativas=3, wait_until="domcontentloaded", pausa_antes=0.0):
    """
    Navega até `url` com retry automático em caso de falha de navegação
    (ex: net::ERR_ABORTED, comum quando um redirecionamento anterior
    ainda está em andamento). Usa "domcontentloaded" por padrão, que é
    mais tolerante que "networkidle" em sites com recursos que ficam
    carregando em segundo plano (ex: analytics, polling).
    """
    import asyncio

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


def _nome_arquivo_seguro(texto):
    """Normaliza uma descrição para virar nome de arquivo seguro."""
    texto = texto.strip().lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_")[:80]


async def capturar_tela(page, etapa: str, descricao: str, erro: bool = False, analise_codigo: bool = False) -> None:
    """
    Salva um screenshot da página atual em dados/<ano>/screenshots,
    registrando o que o script está tentando acessar no momento (URL +
    descrição).

    etapa: nome curto da etapa (ex: "login", "coleta", "cadastro")
    descricao: o que está sendo tentado (ex: "turma 1A", "cpf 123...")
    erro: se True, marca o arquivo como erro/timeout para facilitar a busca
    analise_codigo: equivalente à antiga flag --a/--analise-codigo — se
        True, screenshots de SUCESSO (erro=False) também são salvos.
        Screenshots de erro são SEMPRE salvos, independente deste
        parâmetro, porque são essenciais para diagnosticar falhas mesmo
        numa execução "normal" — mesmo comportamento do original.
    """
    if not analise_codigo and not erro:
        return

    try:
        PASTA_SCREENSHOTS.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prefixo = "ERRO" if erro else "ok"
        nome_desc = _nome_arquivo_seguro(descricao)
        nome_arquivo = f"{timestamp}_{prefixo}_{etapa}_{nome_desc}.png"
        caminho = PASTA_SCREENSHOTS / nome_arquivo

        await page.screenshot(path=str(caminho), full_page=True)

        url_atual = page.url
        marcador = "❌" if erro else "📸"
        print(f"{marcador} Screenshot salvo: {caminho}  (tentando acessar: {url_atual} | {descricao})")

    except Exception as e:
        print(f"Aviso: não foi possível salvar screenshot ({descricao}): {e}")


async def safe_text(page, selector: str) -> str:
    try:
        return (await page.locator(selector).inner_text()).strip()
    except Exception:
        return ""


# ==========================================================
# LOGIN
# ==========================================================

async def fazer_login(page, analise_codigo: bool = False) -> bool:
    """Login único, reaproveitado por todas as etapas."""
    if not await navegar_com_retry(page, LOGIN_URL):
        await capturar_tela(page, "login", "falha ao abrir tela de login", erro=True)
        return False

    await capturar_tela(page, "login", "tela de login", analise_codigo=analise_codigo)

    # Se existir um campo de código/captcha visível, o login não pode ser
    # feito às cegas: melhor abortar com uma mensagem clara do que seguir
    # e falhar silenciosamente mais na frente.
    campo_codigo = page.locator("div#hpcd input[name='codigo']")
    if await campo_codigo.count() > 0 and await campo_codigo.is_visible():
        print("❌ Tela de login exige um código/captcha (#hpcd) que o script não sabe preencher.")
        await capturar_tela(page, "login", "campo codigo captcha exigido", erro=True)
        return False

    await page.fill("#matricula", MATRICULA_PREMATRICULA)
    await page.fill("#senha", SENHA_PREMATRICULA)
    await page.keyboard.press("Enter")

    # Não dá pra confiar em wait_for_url("**/prematricula/**"): a própria
    # URL de login já bate nesse padrão, então essa espera é satisfeita
    # mesmo quando o login falha e a página só recarrega o form de login.
    # Em vez disso, esperamos a página assentar e checamos explicitamente
    # se o formulário de login ainda está na tela.
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("Aviso: Timeout esperando a página assentar após o submit do login.")

    # Se o campo #matricula ainda estiver presente e visível, o login
    # não foi concluído (voltou pra mesma tela ou deu erro de credencial).
    campo_matricula = page.locator("#matricula")
    ainda_na_tela_login = (
        await campo_matricula.count() > 0 and await campo_matricula.is_visible()
    )

    if ainda_na_tela_login:
        # Tenta capturar alguma mensagem de erro visível na página
        # (ex: "matrícula ou senha inválida") para facilitar o diagnóstico.
        mensagem_erro = await safe_text(page, ".alert, .invalid-feedback, .text-danger")
        if mensagem_erro:
            print(f"❌ Login falhou: {mensagem_erro}")
        else:
            print("❌ Login falhou: formulário de login ainda presente após o submit.")
        await capturar_tela(page, "login", "falha no login credenciais ou captcha", erro=True)
        return False

    await capturar_tela(page, "login", "pos login", analise_codigo=analise_codigo)
    return True


# ==========================================================
# CONSULTA DE CPF (compartilhada por 3 etapas)
# ==========================================================

def _extrair_motivo_situacao(situacao: str) -> tuple[str, str]:
    """
    A partir do texto bruto de "Situação" (ex.: "Cancelado. Motivo:
    Responsável desistiu da vaga (A aluna permanecerá aonde encontra
    matriculada atualmente)"), separa o motivo em si da observação
    entre parênteses, quando houver.

    Retorna (motivo, observacao). Se não houver "Motivo:" no texto
    (ex.: aluno ainda "Aguardando" ou já "Matriculado"), devolve
    ("", "").
    """
    if not situacao:
        return "", ""

    m = re.search(r"Motivo:\s*(.*?)(?:\s*\((.*?)\))?\s*$", situacao)
    if not m:
        return "", ""

    motivo = (m.group(1) or "").strip()
    observacao = (m.group(2) or "").strip()
    return motivo, observacao


async def _extrair_escolas_escolhidas(page) -> dict:
    """
    Extrai o fieldset "Escolas Escolhidas" da tela de consulta de CPF:
    a turma pretendida (#turma0) e, para cada opção de escola que
    existir (Opção 1, 2 e 3 -> #e10/#status10, #e20/#status20,
    #e30/#status30), o nome da escola, a situação bruta e, quando a
    situação indicar cancelamento, o motivo extraído do texto.

    Funciona para todos os casos: alunos com 1, 2 ou 3 opções
    preenchidas (opções ausentes na página são simplesmente ignoradas),
    e qualquer situação (Aguardando, Matriculado, Cancelado etc.) — o
    motivo só é preenchido quando o texto da situação contiver
    "Motivo:".
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


def _normalizar_maiusculas_aluno(aluno_dados: dict) -> None:
    """
    Padroniza a caixa dos dados coletados na consulta por CPF: todos os
    dados do aluno (nome do aluno, nome do responsável, endereço,
    critérios, turma e escolas escolhidas/situação/motivo) em
    MAIÚSCULA; o e-mail, ao contrário, é normalizado para minúscula
    (e-mail não deve ser maiusculizado).
    """
    for campo in ("nome_aluno", "nome_responsavel", "endereco"):
        if aluno_dados.get(campo):
            aluno_dados[campo] = aluno_dados[campo].upper()

    if aluno_dados.get("email"):
        aluno_dados["email"] = aluno_dados["email"].strip().lower()

    if aluno_dados.get("criterios"):
        aluno_dados["criterios"] = [
            c.upper() for c in aluno_dados["criterios"] if c is not None
        ]

    escolas = aluno_dados.get("escolas_escolhidas")
    if escolas:
        if escolas.get("turma"):
            escolas["turma"] = escolas["turma"].upper()
        for opcao in escolas.get("opcoes", []):
            for campo in ("escola", "situacao", "motivo_cancelamento", "observacao"):
                if opcao.get(campo):
                    opcao[campo] = opcao[campo].upper()


async def consultar_cpf(page, cpf: str, etapa: str = "cadastro", analise_codigo: bool = False) -> Optional[dict]:
    """
    Consulta um único CPF na tela de consulta do portal de pré-matrícula e
    retorna o dicionário de dados do aluno (mesmo formato usado em
    pre_matricula.json -> cadastros[cpf]), ou None se não foi possível
    obter resultado.

    Função compartilhada por 3 etapas diferentes que precisam consultar
    CPFs pontualmente: src.automacao.prematricula_cadastro (etapa 2),
    src.automacao.prematricula_pendentes (etapa 4), e o modo
    --completar_json (src.automacao.prematricula_planilhas) — sem
    duplicar a lógica de navegação/parse.

    `etapa`: rótulo usado nos screenshots (capturar_tela), para
    diferenciar de qual etapa do processo veio a consulta.
    """
    print(f"\nConsultando CPF: {cpf}")
    if not await navegar_com_retry(page, CONSULTA_URL):
        await capturar_tela(page, etapa, f"falha ao abrir consulta cpf {cpf}", erro=True)
        return None
    await capturar_tela(page, etapa, f"tela de consulta cpf {cpf}", analise_codigo=analise_codigo)

    try:
        await page.wait_for_selector("input#cpfAluno", timeout=7000)
        await page.fill("input#cpfAluno", cpf)
        await page.keyboard.press("Enter")
    except PWTimeout:
        print(f"Campo CPF não encontrado para {cpf}")
        await capturar_tela(page, etapa, f"timeout campo cpf {cpf}", erro=True)
        return None

    try:
        await page.wait_for_selector("div#divCadastros", timeout=7000)
        await capturar_tela(page, etapa, f"resultado cpf {cpf}", analise_codigo=analise_codigo)

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
        await capturar_tela(page, etapa, f"timeout resultado cpf {cpf}", erro=True)
        return None

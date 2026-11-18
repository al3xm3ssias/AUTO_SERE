"""
pre_matricula.py (portado para src/automacao/)

Processo de pré-matrícula, em 4 etapas que compartilham o mesmo login:

  ETAPA 1 - COLETA:      percorre as turmas no portal de pré-matrícula e coleta
                         os alunos com intenção de vaga -> pre_matricula.json
                         (chave "turmas_intencao", mesclada sem apagar histórico)
  ETAPA 2 - CADASTRO:    consulta o cadastro completo de cada CPF coletado
                         -> pre_matricula.json (chave "cadastros"): aluno (nome,
                         data de nascimento, sexo), responsável (nome, CPF, telefones,
                         e-mail), endereço (texto corrido + CEP, logradouro, número,
                         complemento, bairro, município, UF), critérios, escolas
                         escolhidas e a data/hora da consulta
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

Períodos (ano letivo) do portal:
  O select#anoLetivo do site abre sempre no ÚLTIMO período cadastrado, então o
  código escolhe o período explicitamente. Há dois "alvos", com dados separados:

    "atual"   -> ano letivo corrente (ex.: 2026): o período contínuo, que é o
                 de data final mais tardia daquele ano (ex.: 01/12/2025 - 30/11/2026).
                 Os períodos curtos de 1ª chamada já encerrados são ignorados.
                 Dados em pre_matricula.json (nome antigo, mantido).
    "proximo" -> ano letivo seguinte (ex.: 2027): TODOS os períodos desse ano
                 (1ª chamada + o período aberto que o SME criar depois).
                 Dados em previsao_alunos_<ano>.json (ex.: previsao_alunos_2027.json; antes se
                 chamava pre_matricula_<ano>.json, renomeado sozinho na 1ª leitura/gravação).
                 É a base do módulo "Previsão <ano>" (rematriculados + alunos novos).

  Os pontos de entrada recebem alvo="atual" | "proximo" | "ambos".

Cadastro refeito para OUTRA escola:
  Se a consulta por CPF (…/prematricula/consulta_cpf/consultar) mostrar
  "Nenhum aluno cadastrado com esse CPF para as escolas que esse usuário tem
  acesso." (div#naoencontrado), o responsável refez o cadastro para outra escola.
    - Etapa 4: o aluno pendente é gravado como CANCELADO (motivo
      "CADASTRO REFEITO PARA OUTRA ESCOLA"), deixando de ser re-consultado.
    - Etapa 2: o CPF é apenas ignorado (não entra em "cadastros" nem nos contatos).

Posição da NOSSA escola no "Último cadastro" (cadastro refeito):
  Vale só o último cadastro (o da página, sufixo 0). Conforme a posição da nossa escola
  nas Escolas Escolhidas (ver classificar_posicao_da_escola):
    - Opção 1                                        -> fluxo normal.
    - Opção 2 ou 3 e alguma opção ANTERIOR ainda sem
      situação (ou já matriculado lá)                -> IGNORA: quem cancela ou matricula é
                                                        a escola da opção anterior. O aluno não
                                                        é registrado (sai de "cadastros" e dos
                                                        contatos) e fica marcado com
                                                        nao_e_primeira_opcao=True.
    - Opção 2 ou 3 e TODAS as anteriores já com
      situação (texto livre, ex.: "A escola não
      dispõe de vaga no momento", "Cancelado...")    -> FILA DE ANÁLISE: o aluno é registrado
                                                        normalmente e marcado com
                                                        fila_analise=True e encaminhado_de=[o que
                                                        cada escola anterior respondeu], para a
                                                        escola decidir se matricula ou confirma
                                                        com a Central de Matrícula.

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
  - O cadastro guarda TODOS os campos que a consulta por CPF mostra (antes só
    nome, responsável, telefone, e-mail, endereço corrido, critérios e escolas).
    Campos opcionais ausentes na página não travam a coleta (sem espera de 30 s).
"""

from __future__ import annotations

import asyncio
import contextvars
import csv
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from glob import glob
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from src.automacao.comunicado_matricula import avisar_apos_pre_matricula
from src.comum import paths
from src.comum import previsao as _previsao
from src.comum.arquivos_json import (
    ArquivoJsonCorrompidoError,
    carregar_json,
    salvar_json_atomico,
)
from src.comum import navegador as _navegador
from src.comum import pre_matricula_edicao as _edicao


# ==========================================================
# CONSTANTES
# ==========================================================

LOGIN_URL = "https://sme.pontagrossa.pr.gov.br/prematricula/login"
INTENCOES_URL = "https://sme.pontagrossa.pr.gov.br/prematricula/intencoes_vaga"
CONSULTA_URL = "https://sme.pontagrossa.pr.gov.br/prematricula/consulta_cpf"

NOME_ESCOLA_BUSCA = "Judith"
NOME_ESCOLA_ALVO = "Judith Macedo Silveira"

# Valor convencionado gravado quando o aluno some da lista de "aguardando".
# É uma PRESUNÇÃO (o site não informa o motivo), não uma confirmação.
SITUACAO_PRESUNTIVA = "Cancelado"
MOTIVO_PRESUNTIVO = "CANCELADO VIA SISTEMA/RESPONSAVEL"

# Mensagem do portal (div#naoencontrado em …/consulta_cpf/consultar) quando o
# responsável refez o cadastro para OUTRA escola. Aqui isso é cancelamento REAL.
MENSAGEM_SEM_CADASTRO = (
    "Nenhum aluno cadastrado com esse CPF para as escolas que esse usuário tem acesso."
)
_TRECHO_SEM_CADASTRO = "Nenhum aluno cadastrado com esse CPF"   # trecho usado na detecção por texto
SITUACAO_CANCELADO = "Cancelado"
MOTIVO_OUTRA_ESCOLA = "CADASTRO REFEITO PARA OUTRA ESCOLA"

# Cadastro refeito em que nossa escola é a Opção 2/3 e a escola anterior ainda não decidiu:
# o aluno não é nosso (a escola da opção anterior é quem cancela ou matricula).
MOTIVO_NAO_E_PRIMEIRA_OPCAO = "CADASTRO REFEITO: NOSSA ESCOLA NÃO É A 1ª OPÇÃO"

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

ALVO_ATUAL = "atual"
ALVO_PROXIMO = "proximo"
ALVOS_VALIDOS = (ALVO_ATUAL, ALVO_PROXIMO)

# Alvo em uso na execução corrente. ContextVar (e não global) para que cada
# execução assíncrona tenha o seu, sem precisar repassar o parâmetro por todas as funções.
_ALVO: contextvars.ContextVar[str] = contextvars.ContextVar("pre_matricula_alvo", default=ALVO_ATUAL)


def alvo_atual() -> str:
    return _ALVO.get()


def definir_alvo(alvo: str):
    """Define o alvo da execução corrente. Devolve o token para _ALVO.reset()."""
    if alvo not in ALVOS_VALIDOS:
        raise ValueError(f"alvo inválido: {alvo!r} (use {ALVOS_VALIDOS})")
    return _ALVO.set(alvo)


def _alvos(alvo: str) -> tuple[str, ...]:
    """'atual' | 'proximo' | 'ambos' -> tupla de alvos, na ordem de execução."""
    if alvo == "ambos":
        return (ALVO_PROXIMO, ALVO_ATUAL)
    if alvo in ALVOS_VALIDOS:
        return (alvo,)
    raise ValueError(f"alvo inválido: {alvo!r} (use 'atual', 'proximo' ou 'ambos')")


def _ano_alvo() -> int:
    """Ano letivo do alvo corrente: ano atual (alvo 'atual') ou ano atual + 1 ('proximo')."""
    return int(paths.ano_atual()) + (1 if alvo_atual() == ALVO_PROXIMO else 0)


def _ano() -> str:
    return str(_ano_alvo())


def pasta_base() -> Path:
    return Path(paths.dados_ano_atual())


def caminho_pre_matricula() -> Path:
    # Alvo "atual" mantém o nome antigo (não quebra o histórico já gravado).
    # Alvo "proximo" -> previsao_alunos_<ano>.json; um pre_matricula_<ano>.json de antes é renomeado aqui
    # (os.replace, conteúdo intacto) para que a coleta continue de onde parou em vez de começar do zero.
    if alvo_atual() == ALVO_PROXIMO:
        _previsao.migrar_nome_antigo(pasta_base(), _ano())
        return _previsao.caminho_previsao_alunos(pasta_base(), _ano())
    return pasta_base() / "pre_matricula.json"


def caminho_template() -> Path:
    return pasta_base() / "Google Contacts Import Template.csv"


def caminho_contatos() -> Path:
    data = datetime.now().strftime('%Y-%m-%d')
    if alvo_atual() == ALVO_PROXIMO:
        return pasta_base() / f"TEMPLATE_PREENCHIDO_{_ano()}_{data}.csv"
    return pasta_base() / f"TEMPLATE_PREENCHIDO_{data}.csv"


def pasta_screenshots() -> Path:
    return pasta_base() / "screenshots"


def arquivo_mais_recente(padrao: str) -> str | None:
    """Arquivo mais recente da pasta de dados do ano que casa com o glob, ou None."""
    arquivos = glob(str(pasta_base() / padrao))
    if not arquivos:
        return None
    return max(arquivos, key=os.path.getmtime)


_PLACEHOLDERS_PREMATRICULA = {"", "matricula", "senha_prematricula"}


def _credenciais_padrao() -> tuple[str, str]:
    """
    Credenciais do portal de pré-matrícula (carregadas só quando necessárias).

    Vêm de PREMATRICULA_LOGIN / PREMATRICULA_SENHA em credenciais/.env (ver
    .env.example). Se ainda estiverem com o valor de exemplo, para aqui com uma
    mensagem clara em vez de tentar logar com dados falsos no site.
    """
    from src.comum import credenciais

    matricula = credenciais.MATRICULA_PREMATRICULA
    senha = credenciais.SENHA_PREMATRICULA
    if matricula in _PLACEHOLDERS_PREMATRICULA or senha in _PLACEHOLDERS_PREMATRICULA:
        raise ValueError(
            "Credenciais da pré-matrícula não configuradas: defina PREMATRICULA_LOGIN e "
            "PREMATRICULA_SENHA em credenciais/.env (veja .env.example) e reinicie o sistema."
        )
    return matricula, senha


# ==========================================================
# PERÍODOS (select#anoLetivo)
# ==========================================================

# Rótulo das opções do site: "2027 (13/11/2026 - 22/11/2026)"
_RE_PERIODO = re.compile(r"^\s*(\d{4})\s*\(\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\s*\)")


def _data_br(texto: str):
    return datetime.strptime(texto, "%d/%m/%Y").date()


def parse_periodos(opcoes) -> list[dict]:
    """
    [{"value","label"}] do select#anoLetivo -> [{"value","rotulo","ano","inicio","fim"}].
    Opções fora do padrão "AAAA (dd/mm/aaaa - dd/mm/aaaa)" são ignoradas.
    """
    periodos = []
    for op in opcoes or []:
        m = _RE_PERIODO.match(op.get("label") or "")
        if not m or not (op.get("value") or "").strip():
            continue
        try:
            inicio, fim = _data_br(m.group(2)), _data_br(m.group(3))
        except ValueError:
            continue
        periodos.append(
            {
                "value": op["value"].strip(),
                "rotulo": op["label"].strip(),
                "ano": int(m.group(1)),
                "inicio": inicio,
                "fim": fim,
            }
        )
    return periodos


def escolher_periodos(opcoes, alvo: str, ano_base: int | None = None) -> list[dict]:
    """
    Períodos a coletar para o alvo, em ordem cronológica.

      "atual"   -> só UM: dentre os períodos do ano atual, o de data final mais
                   tardia (o período contínuo). 1ª chamadas já encerradas ficam de fora.
      "proximo" -> TODOS os períodos do ano atual + 1 (1ª chamada + o período aberto
                   que for criado depois).

    Lista vazia se o site ainda não tem período para esse ano.
    """
    ano_base = int(paths.ano_atual()) if ano_base is None else ano_base
    ano_ref = ano_base + (1 if alvo == ALVO_PROXIMO else 0)
    candidatos = [p for p in parse_periodos(opcoes) if p["ano"] == ano_ref]
    if not candidatos:
        return []
    if alvo == ALVO_PROXIMO:
        return sorted(candidatos, key=lambda p: (p["inicio"], p["fim"]))
    escolhido = max(candidatos, key=lambda p: (p["fim"], p["inicio"], int(p["value"]) if p["value"].isdigit() else 0))
    return [escolhido]


async def _selecionar_periodo(page, periodo, analise=False) -> bool:
    """Seleciona o período no select#anoLetivo e CONFIRMA que ele ficou selecionado."""
    try:
        await page.wait_for_selector("select#anoLetivo", timeout=7000)
        await page.select_option("select#anoLetivo", periodo["value"])
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass
        await asyncio.sleep(1.0)
        selecionado = await page.locator("select#anoLetivo").input_value()
        if selecionado != periodo["value"]:
            raise RuntimeError(f"o site manteve o valor {selecionado!r}")
    except Exception as e:
        print(f"❌ Não consegui selecionar o período {periodo['rotulo']}: {e}")
        await capturar_tela(page, "coleta", f"falha ao selecionar periodo {periodo['value']}", erro=True, analise=analise)
        return False
    print(f"✓ Período selecionado: {periodo['rotulo']} (value={periodo['value']})")
    await capturar_tela(page, "coleta", f"periodo {periodo['value']} selecionado", analise=analise)
    return True


# ==========================================================
# PERSISTÊNCIA DO pre_matricula.json
# ==========================================================

CHAVE_VINCULO = "vinculo_base_abc"      # gravada por consulta_base_abc.py; recoletar um aluno não pode apagá-la


def _herdar_vinculo(antigo, novo) -> None:
    """Leva o vínculo da Base ABC do registro antigo para o novo (a coleta troca o registro inteiro)."""
    if isinstance(antigo, dict) and isinstance(novo, dict) and antigo.get(CHAVE_VINCULO) and CHAVE_VINCULO not in novo:
        novo[CHAVE_VINCULO] = antigo[CHAVE_VINCULO]


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
    """
    Grava o pre_matricula.json de forma atômica, atualizando o timestamp.

    Reaplica antes as correções manuais (src.comum.pre_matricula_edicao): a coleta regrava nome e cadastro com o
    que está no site, e sem isso um nome corrigido à mão voltaria a ficar errado a cada execução.
    """
    _edicao.aplicar_correcoes_manuais(dados)
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
    coletado_em = datetime.now().isoformat(timespec="microseconds")   # um só carimbo para toda esta coleta; coletas diferentes nunca empatam

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
            aluno_atualizado["coletado_em"] = coletado_em      # permite decidir "a última tentativa" depois
            _herdar_vinculo(existentes.get(chave), aluno_atualizado)
            existentes[chave] = aluno_atualizado

        for chave, aluno_antigo in existentes.items():
            if chave not in chaves_vistas_agora:
                estava_presente_antes = aluno_antigo.get("presente_na_ultima_coleta", True)
                aluno_antigo["presente_na_ultima_coleta"] = False

                if estava_presente_antes and not aluno_antigo.get("situacao"):
                    aluno_antigo["situacao"] = SITUACAO_PRESUNTIVA
                    aluno_antigo["motivo_cancelamento"] = MOTIVO_PRESUNTIVO

    resultado = {
        turma: list(alunos_por_chave.values())
        for turma, alunos_por_chave in turmas_mescladas.items()
    }
    marcar_tentativas_substituidas(resultado)
    return resultado


def tentativa_substituida(aluno) -> bool:
    """True se este registro é de uma tentativa antiga, já substituída por outra (ver BUG-PRE-002)."""
    return bool(aluno.get("substituido_por_nova_tentativa"))


def marcar_tentativas_substituidas(turmas_intencao) -> None:
    """
    Regra de negócio (BUGS_CONHECIDOS.md): se o mesmo CPF aparece em mais de uma turma
    (aluno cancelou e voltou noutra turma), VALE A ÚLTIMA TENTATIVA; a turma não importa.
    Os registros antigos NÃO são apagados (ficam como histórico): recebem
    substituido_por_nova_tentativa=True e turma_da_tentativa_atual.

    Quem vale: quem está presente na última coleta; se nenhum (ou empate) decide o
    carimbo coletado_em mais recente. Registros antigos sem carimbo perdem para qualquer
    registro com carimbo; se continuar empatado, NADA é marcado (melhor não decidir).
    A marcação é recalculada a cada coleta, então se o aluno voltar para a turma
    anterior, os papéis se invertem.
    """
    por_cpf = defaultdict(list)
    for turma, alunos in (turmas_intencao or {}).items():
        for aluno in alunos:
            aluno.pop("substituido_por_nova_tentativa", None)
            aluno.pop("turma_da_tentativa_atual", None)
            cpf = (aluno.get("cpf") or "").strip()
            if cpf:
                por_cpf[cpf].append((turma, aluno))

    def peso(registro):
        aluno = registro[1]
        return (aluno.get("presente_na_ultima_coleta") is True, aluno.get("coletado_em") or "")

    for registros in por_cpf.values():
        if len(registros) < 2:
            continue
        melhor = max(peso(r) for r in registros)
        vencedores = [r for r in registros if peso(r) == melhor]
        if len(vencedores) != 1:
            continue
        turma_atual, aluno_atual = vencedores[0]
        for turma, aluno in registros:
            if aluno is not aluno_atual:
                aluno["substituido_por_nova_tentativa"] = True
                aluno["turma_da_tentativa_atual"] = turma_atual


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

async def _coletar_periodo(page, periodo, analise=False):
    """
    Coleta as turmas/alunos de UM período (abre a tela do zero, escolhe o período,
    depois a escola e percorre as turmas). Devolve {turma: [alunos]} ou None se falhar.
    """
    print(f"\n--- Coletando período {periodo['rotulo']} ---")
    if not await navegar_com_retry(page, INTENCOES_URL, pausa_antes=1.0):
        await capturar_tela(page, "coleta", "falha ao abrir tela de intencoes", erro=True, analise=analise)
        return None
    if not await _selecionar_periodo(page, periodo, analise=analise):
        return None

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

    return resultado["turmas"]


async def etapa_coleta(page, analise=False):
    alvo = alvo_atual()
    print("\n" + "=" * 60)
    print(f"ETAPA 1/4 - COLETA DE INTENÇÕES DE VAGA ({_ano()} - alvo: {alvo})")
    print("=" * 60)

    if not await navegar_com_retry(page, INTENCOES_URL, pausa_antes=1.0):
        await capturar_tela(page, "coleta", "falha ao abrir tela de intencoes", erro=True, analise=analise)
        return None
    await capturar_tela(page, "coleta", "tela de intencoes de vaga", analise=analise)

    try:
        await page.wait_for_selector("select#anoLetivo", timeout=7000)
    except PWTimeout:
        print("Select de ano letivo (anoLetivo) não encontrado.")
        await capturar_tela(page, "coleta", "timeout select anoLetivo", erro=True, analise=analise)
        return None
    opcoes_ano = await page.eval_on_selector_all(
        "select#anoLetivo option",
        "opts => opts.map(o => ({value: o.value, label: o.textContent.trim()}))",
    )

    periodos = escolher_periodos(opcoes_ano, alvo)
    if not periodos:
        # Não cai no período que o site carrega por padrão: seria coletar o ano errado.
        print(f"⚠️ O portal ainda não tem período cadastrado para {_ano()} (alvo '{alvo}'). Nada a coletar.")
        print("   Opções vistas no site: " + "; ".join(o["label"] for o in opcoes_ano if o.get("value")))
        return {
            "meta": {"url": INTENCOES_URL, "coletado_em": datetime.now().isoformat(), "alvo": alvo, "ano": _ano()},
            "turmas": {},
            "sem_periodo": True,
        }

    print("Períodos que serão coletados: " + "; ".join(p["rotulo"] for p in periodos))

    turmas_total = {}
    for periodo in periodos:
        turmas = await _coletar_periodo(page, periodo, analise=analise)
        if turmas is None:
            # Nada é gravado: uma coleta parcial faria quem estava no período que falhou
            # ser marcado como "cancelado" (presunção) na mesclagem.
            print(f"❌ Falha ao coletar o período {periodo['rotulo']}. Etapa 1 abortada sem gravar.")
            return None
        _mesclar_dicts_turmas(turmas_total, turmas)

    resultado = {
        "meta": {
            "url": INTENCOES_URL,
            "coletado_em": datetime.now().isoformat(),
            "alvo": alvo,
            "ano": _ano(),
            "periodos": [p["value"] for p in periodos],
        },
        "turmas": turmas_total,
    }

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


# Campos de texto do cadastro lidos na consulta por CPF:
#   chave gravada em cadastros[cpf] -> id(s) do <span> no portal.
# "{s}" é o sufixo do cadastro na página: "0" = 1º cadastro (dDataNasc0, dNomeResponsavel0...).
# O modal que abre ao clicar no nome, na lista de intenções de vaga, usa os mesmos ids sem sufixo.
# Mais de um id = alternativas (o 1º que existir e tiver texto vale).
SUFIXO_CADASTRO = "0"
CAMPOS_CADASTRO = {
    "data_nascimento": ("dDataNasc{s}",),
    "sexo": ("dSexo{s}",),
    # Nome da mãe do aluno (filiação). ⚠️ Os ids abaixo são tentativas: NÃO foram vistos no portal real. Se nenhum existir,
    # o campo fica "" (não custa tempo: _texto_se_existe confere com count()) e a Base ABC busca só por nome + nascimento.
    "nome_mae": ("dNomeMae{s}", "dMae{s}", "dNomeMaeAluno{s}", "dFiliacao1{s}", "dFiliacao{s}"),
    "nome_responsavel": ("dNomeResponsavel{s}",),
    "cpf_responsavel": ("dCPFResponsavel{s}",),
    "telefone": ("dTelefoneResponsavel{s}",),
    "telefone_2": ("dTelefoneResponsavel2{s}", "dTelefoneResponsavel{s}2"),
    "email": ("dEmailResponsavel{s}",),
    "cep": ("dCEP{s}",),
    "logradouro": ("dLogradouro{s}",),
    "numero": ("dNumero{s}",),
    "complemento": ("dComplemento{s}",),
    "bairro": ("dBairro{s}",),
    "municipio": ("dMunicipio{s}",),
    "uf": ("dUF{s}",),
}


async def _texto_se_existe(page, seletor):
    """
    Texto do elemento, ou "" se ele não existe na página.

    Ao contrário de safe_text(), confere antes com count(): inner_text() num
    elemento ausente espera o timeout padrão do Playwright (30 s) antes de
    falhar, e um campo opcional em branco (Complemento, Telefone 2) não pode
    custar isso a cada CPF consultado.
    """
    try:
        if await page.locator(seletor).count() == 0:
            return ""
        return (await page.locator(seletor).inner_text()).strip()
    except Exception:
        return ""


async def extrair_dados_cadastro(page, sufixo=SUFIXO_CADASTRO):
    """
    Lê todos os campos de texto do cadastro (CAMPOS_CADASTRO) do cadastro de
    sufixo `sufixo` na página. Campo inexistente ou em branco -> "".
    """
    dados = {}
    for chave, modelos in CAMPOS_CADASTRO.items():
        valor = ""
        for modelo in modelos:
            valor = await _texto_se_existe(page, "span#" + modelo.format(s=sufixo))
            if valor:
                break
        dados[chave] = valor
    return dados


# Campos gravados em MAIÚSCULA (nome, endereço e demais textos livres). Não entram:
# e-mail (minúscula), data de nascimento, números, telefones, CPF e CEP (formato do portal).
_CAMPOS_MAIUSCULA = (
    "nome_aluno", "nome_mae", "nome_responsavel", "endereco",
    "sexo", "logradouro", "complemento", "bairro", "municipio", "uf",
)


def _normalizar_maiusculas_aluno(aluno_dados):
    """Dados do aluno em MAIÚSCULA; e-mail em minúscula."""
    for campo in _CAMPOS_MAIUSCULA:
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


async def _ler_cadastro_da_pagina(page, cpf):
    """Lê o resultado já exibido (div#divCadastros) e devolve o dict de cadastro do aluno."""
    campos = await extrair_dados_cadastro(page)
    nome_aluno = (
        await _texto_se_existe(page, "h5#dNomeAluno")
        or await _texto_se_existe(page, f"span#dNome{SUFIXO_CADASTRO}")
    )

    aluno_dados = {
        "cpf": cpf,
        "nome_aluno": nome_aluno,
        "data_nascimento": campos["data_nascimento"],
        "sexo": campos["sexo"],
        "nome_mae": campos["nome_mae"],
        "nome_responsavel": campos["nome_responsavel"],
        "cpf_responsavel": campos["cpf_responsavel"],
        "telefone": campos["telefone"],
        "telefone_2": campos["telefone_2"],
        "email": campos["email"],
        # Texto corrido do endereço: mantido porque o CSV de contatos, extrair_cep()
        # e as telas leem este campo. Os mesmos dados, separados, vêm logo abaixo.
        "endereco": " ".join(
            [
                campos["logradouro"],
                campos["numero"],
                campos["complemento"],
                campos["bairro"],
                campos["municipio"],
                campos["uf"],
                campos["cep"],
            ]
        ),
        "cep": campos["cep"],
        "logradouro": campos["logradouro"],
        "numero": campos["numero"],
        "complemento": campos["complemento"],
        "bairro": campos["bairro"],
        "municipio": campos["municipio"],
        "uf": campos["uf"],
        "criterios": await page.locator(f"div#dCriterios{SUFIXO_CADASTRO} li").all_inner_texts(),
        "escolas_escolhidas": await _extrair_escolas_escolhidas(page),
        "consultado_em": datetime.now().isoformat(timespec="seconds"),
    }

    _normalizar_maiusculas_aluno(aluno_dados)
    return aluno_dados


def _normalizar_texto_busca(texto: str) -> str:
    """minúsculas, sem acento e com espaços colapsados (para achar a mensagem do portal)."""
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", texto).strip().lower()


_TRECHO_SEM_CADASTRO_NORM = _normalizar_texto_busca(_TRECHO_SEM_CADASTRO)


async def _aguardar_resultado_consulta(page, timeout=7.0):
    """
    Espera o resultado da consulta por CPF (após o Enter). Devolve:
      "cadastro"     -> div#divCadastros apareceu
      "outra_escola" -> o portal mostrou div#naoencontrado ("Nenhum aluno cadastrado
                        com esse CPF para as escolas que esse usuário tem acesso.")
      None           -> nada reconhecível apareceu no prazo
    """
    loop = asyncio.get_running_loop()
    limite = loop.time() + timeout
    while True:
        try:
            if await page.locator("div#divCadastros").is_visible():
                return "cadastro"

            # Mensagem do portal: <div id="naoencontrado"> ... <h4>Nenhum aluno cadastrado ...</h4>
            if await page.locator("div#naoencontrado").is_visible():
                return "outra_escola"

            # Reserva: se o id mudar, reconhece pelo texto visível da página
            # (inner_text ignora elementos escondidos).
            corpo = await page.locator("body").inner_text(timeout=1500)
            if _TRECHO_SEM_CADASTRO_NORM in _normalizar_texto_busca(corpo):
                return "outra_escola"
        except Exception:
            # Página navegando (contexto destruído) ou ainda sem body: tenta de novo.
            pass
        if loop.time() >= limite:
            return None
        await asyncio.sleep(0.25)


async def consultar_cpf_com_status(page, cpf, etapa="cadastro", analise=False):
    """
    Consulta um CPF na tela de consulta e devolve (cadastro | None, outra_escola: bool).

    cadastro: dict no mesmo formato de pre_matricula.json -> cadastros[cpf], ou None
    se não houve resultado. `etapa` só rotula os screenshots.

    outra_escola=True: em TODOS os períodos do alvo o portal respondeu que não há
    aluno com esse CPF para as escolas do usuário, ou seja, o responsável refez o
    cadastro para outra escola (o aluno deve ser tratado como cancelado).

    A tela de consulta também tem o campo "Abertura" (select#anoLetivo), que abre
    no período mais recente do portal. Por isso o período do alvo corrente é
    selecionado ANTES de consultar: "atual" -> o período contínuo do ano;
    "proximo" -> os períodos do ano seguinte, do mais novo para o mais antigo,
    parando no primeiro em que o CPF aparece. O período usado fica gravado em
    "periodo_abertura".
    """
    print(f"\nConsultando CPF: {cpf}")
    alvo = alvo_atual()
    periodos = None
    i = 0

    while True:
        if not await navegar_com_retry(page, CONSULTA_URL):
            await capturar_tela(page, etapa, f"falha ao abrir consulta cpf {cpf}", erro=True, analise=analise)
            return None, False

        try:
            await page.wait_for_selector("select#anoLetivo", timeout=7000)
            if periodos is None:
                opcoes = await page.eval_on_selector_all(
                    "select#anoLetivo option",
                    "opts => opts.map(o => ({value: o.value, label: o.textContent.trim()}))",
                )
                periodos = sorted(escolher_periodos(opcoes, alvo), key=lambda p: p["inicio"], reverse=True)
                if not periodos:
                    print(f"⚠️ Sem período de {_ano()} (alvo '{alvo}') na consulta; CPF {cpf} não consultado.")
                    return None, False
            periodo = periodos[i]
            await page.select_option("select#anoLetivo", periodo["value"])
            if await page.locator("select#anoLetivo").input_value() != periodo["value"]:
                raise RuntimeError("o site manteve outro valor no campo Abertura")
            await page.wait_for_selector("input#cpfAluno", timeout=7000)
            await page.fill("input#cpfAluno", cpf)
        except Exception as e:
            print(f"Não consegui preparar a consulta do CPF {cpf} (período/campo CPF): {e}")
            await capturar_tela(page, etapa, f"falha ao preparar consulta cpf {cpf}", erro=True, analise=analise)
            return None, False

        await capturar_tela(page, etapa, f"tela de consulta cpf {cpf} periodo {periodo['value']}", analise=analise)
        await page.keyboard.press("Enter")
        ultimo = i == len(periodos) - 1

        resultado = await _aguardar_resultado_consulta(page)

        if resultado == "cadastro":
            await capturar_tela(page, etapa, f"resultado cpf {cpf}", analise=analise)
            aluno_dados = await _ler_cadastro_da_pagina(page, cpf)
            if not aluno_dados.get("nome_aluno") and not ultimo:
                print(f"   CPF {cpf} sem dados no período {periodo['rotulo']}; tentando o próximo.")
                i += 1
                continue
            aluno_dados["periodo_abertura"] = periodo["rotulo"]
            print(f"✅ Dados coletados para {cpf} (período {periodo['rotulo']})")
            return aluno_dados, False

        if resultado == "outra_escola":
            if not ultimo:
                print(f"   CPF {cpf} sem cadastro no período {periodo['rotulo']}; tentando o próximo.")
                i += 1
                continue
            print(f"↪️ CPF {cpf}: cadastro refeito para OUTRA escola (portal: sem aluno para as escolas deste usuário).")
            await capturar_tela(page, etapa, f"outra escola cpf {cpf}", analise=analise)
            return None, True

        # resultado is None: nada reconhecível apareceu no prazo
        if not ultimo:
            print(f"   CPF {cpf} não encontrado no período {periodo['rotulo']}; tentando o próximo.")
            i += 1
            continue
        print(f"Nenhum resultado encontrado para {cpf}")
        await capturar_tela(page, etapa, f"timeout resultado cpf {cpf}", erro=True, analise=analise)
        return None, False


async def consultar_cpf(page, cpf, etapa="cadastro", analise=False):
    """
    Consulta um CPF e devolve o dict de cadastro (formato de pre_matricula.json ->
    cadastros[cpf]), ou None se não houve resultado (inclusive o caso "outra escola").
    Quem precisa distinguir "outra escola" usa consultar_cpf_com_status().
    """
    aluno_dados, _outra_escola = await consultar_cpf_com_status(page, cpf, etapa=etapa, analise=analise)
    return aluno_dados


# ----------------------------------------------------------
# Posição da NOSSA escola no "Último cadastro" (cadastro refeito)
# ----------------------------------------------------------

POSICAO_PRIMEIRA = "primeira"
POSICAO_ENCAMINHADO = "encaminhado"
POSICAO_IGNORAR = "ignorar"


def classificar_posicao_da_escola(opcoes, escola_alvo=NOME_ESCOLA_ALVO):
    """
    Olha as Escolas Escolhidas do ÚLTIMO cadastro e devolve (posicao, anteriores).

      "primeira"    -> nossa escola é a Opção 1 (ou o formato é inesperado: na dúvida
                       NÃO descarta o aluno). Fluxo normal.
      "encaminhado" -> nossa escola é a Opção 2 ou 3 e TODAS as opções anteriores já
                       têm situação (texto livre escrito por outras escolas: "Cancelado...",
                       "A escola não dispõe de vaga no momento"...) e nenhuma é matrícula.
                       Vai para a FILA DE ANÁLISE: a escola decide se matricula ou confirma
                       com a Central de Matrícula.
      "ignorar"     -> nossa escola é a Opção 2 ou 3 e alguma opção anterior ainda está sem
                       situação (ou o aluno já foi matriculado lá): quem cancela ou matricula
                       é a escola anterior. Não registrar.

    `anteriores` = [{"opcao", "escola", "situacao"}] das opções antes da nossa (vazio na
    "primeira"). Como o texto da situação é livre, a regra olha só se está preenchido.
    """
    opcoes = sorted(opcoes or [], key=lambda o: o.get("opcao") or 99)
    alvo = escola_alvo.upper()
    idx = next((i for i, op in enumerate(opcoes) if alvo in (op.get("escola") or "").upper()), None)
    if idx is None or idx == 0:
        return POSICAO_PRIMEIRA, []

    anteriores = [
        {
            "opcao": op.get("opcao"),
            "escola": op.get("escola") or "",
            "situacao": (op.get("situacao") or "").strip(),
        }
        for op in opcoes[:idx]
    ]
    if any(not a["situacao"] for a in anteriores):
        return POSICAO_IGNORAR, anteriores
    if any(a["situacao"].upper().startswith("MATRICULAD") for a in anteriores):
        return POSICAO_IGNORAR, anteriores          # já matriculado em outra escola: nada a analisar
    return POSICAO_ENCAMINHADO, anteriores


def _marcar_nao_e_primeira_opcao(aluno):
    """Nossa escola não é a 1ª opção e a anterior não decidiu: cancelado DE FATO para esta escola."""
    aluno["situacao"] = SITUACAO_CANCELADO
    aluno["motivo_cancelamento"] = MOTIVO_NAO_E_PRIMEIRA_OPCAO
    aluno["observacao"] = ""
    aluno["nao_e_primeira_opcao"] = True
    aluno.pop("fila_analise", None)
    aluno.pop("encaminhado_de", None)


def _marcar_fila_analise(aluno, anteriores):
    """Encaminhado por outra escola: entra na fila (matricular ou confirmar com a Central)."""
    aluno["fila_analise"] = True
    aluno["encaminhado_de"] = anteriores
    aluno.pop("nao_e_primeira_opcao", None)


def _limpar_marcas_posicao(aluno):
    """Voltou a ser Opção 1 (cadastro refeito de novo): tira as marcas antigas."""
    for chave in ("fila_analise", "encaminhado_de", "nao_e_primeira_opcao"):
        aluno.pop(chave, None)


def _aplicar_posicao_no_aluno(aluno, posicao, anteriores):
    if posicao == POSICAO_IGNORAR:
        _marcar_nao_e_primeira_opcao(aluno)
    elif posicao == POSICAO_ENCAMINHADO:
        _marcar_fila_analise(aluno, anteriores)
    else:
        _limpar_marcas_posicao(aluno)


def listar_fila_analise(pre_matricula):
    """
    Alunos na fila de análise (encaminhados por outra escola), sem acessar o site.
    Devolve [(turma, aluno)] ignorando tentativas antigas já substituídas.
    """
    fila = []
    for turma, alunos in (pre_matricula.get("turmas_intencao") or {}).items():
        for aluno in alunos:
            if tentativa_substituida(aluno):
                continue
            if aluno.get("fila_analise"):
                fila.append((turma, aluno))
    return fila


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
    posicoes = {}          # cpf -> (posicao, anteriores)
    for cpf in cpfs:
        aluno_dados, outra_escola = await consultar_cpf_com_status(
            page, cpf, etapa="cadastro", analise=analise
        )
        if outra_escola:
            print(f"   (CPF {cpf} ignorado: cadastro refeito para outra escola)")
            continue
        if aluno_dados is None:
            continue

        opcoes = (aluno_dados.get("escolas_escolhidas") or {}).get("opcoes", [])
        posicao, anteriores = classificar_posicao_da_escola(opcoes)
        posicoes[cpf] = (posicao, anteriores)

        if posicao == POSICAO_IGNORAR:
            print(f"   (CPF {cpf} ignorado: nossa escola não é a 1ª opção e a escola anterior ainda não decidiu)")
            continue
        if posicao == POSICAO_ENCAMINHADO:
            print(f"   ➡️ CPF {cpf}: encaminhado por outra escola -> fila de análise")

        resultados[cpf] = aluno_dados

    pre_matricula = carregar_pre_matricula()
    for cpf, novo in resultados.items():
        _herdar_vinculo(pre_matricula["cadastros"].get(cpf), novo)
    pre_matricula["cadastros"].update(resultados)

    for cpf, (posicao, anteriores) in posicoes.items():
        if posicao == POSICAO_IGNORAR:
            pre_matricula["cadastros"].pop(cpf, None)      # cadastro antigo deixa de valer
        for alunos in pre_matricula["turmas_intencao"].values():
            for aluno in alunos:
                if (aluno.get("cpf") or "").strip() == cpf:
                    _aplicar_posicao_no_aluno(aluno, posicao, anteriores)

    salvar_pre_matricula(pre_matricula)

    na_fila = sum(1 for p, _ in posicoes.values() if p == POSICAO_ENCAMINHADO)
    ignorados = sum(1 for p, _ in posicoes.values() if p == POSICAO_IGNORAR)
    print(f"\n✅ Etapa 2 concluída. Arquivo salvo em: {caminho_pre_matricula()}")
    print(f"   Na fila de análise (encaminhados por outra escola): {na_fila}")
    print(f"   Ignorados (nossa escola não é a 1ª opção): {ignorados}")
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
            if tentativa_substituida(aluno):
                continue          # a tentativa que vale é a outra; consultar o CPF de novo seria à toa
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


def _marcar_cancelado_outra_escola(aluno):
    """
    Responsável refez o cadastro em outra escola: cancelado DE FATO (deixa de ser
    presunção, então a Etapa 4 não volta a consultar este CPF).
    """
    aluno["situacao"] = SITUACAO_CANCELADO
    aluno["motivo_cancelamento"] = MOTIVO_OUTRA_ESCOLA
    aluno["observacao"] = MENSAGEM_SEM_CADASTRO
    aluno["cadastro_refeito_outra_escola"] = True


async def etapa_verificar_pendentes(page, dados_pre_matricula=None, analise=False):
    """
    ETAPA 4/4 - Para cada aluno "pendente" (sumiu da lista e com situação
    presumida), re-consulta o CPF e, havendo situação real na opção desta
    escola, substitui a presunção em turmas_intencao e atualiza cadastros.

    Se o portal responder "Nenhum aluno cadastrado com esse CPF para as escolas
    que esse usuário tem acesso.", o responsável refez o cadastro para outra
    escola: o aluno é gravado como CANCELADO (MOTIVO_OUTRA_ESCOLA).

    Se o último cadastro tem nossa escola como Opção 2/3 e a opção anterior ainda não
    decidiu, o aluno é gravado como CANCELADO (MOTIVO_NAO_E_PRIMEIRA_OPCAO) e sai de
    "cadastros". Se todas as anteriores já têm situação, segue o fluxo e entra na fila
    de análise (fila_analise=True).

    Retorna {"total_pendentes", "confirmados", "sem_resposta": [cpfs], "outra_escola": [cpfs]}.
    ("confirmados" inclui os cancelados por cadastro em outra escola ou por não ser a 1ª opção.)
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
        return {"total_pendentes": 0, "confirmados": 0, "sem_resposta": [], "outra_escola": []}

    confirmados = 0
    sem_resposta = []
    outra_escola_cpfs = []
    nao_primeira_cpfs = []
    cadastros = pre_matricula.setdefault("cadastros", {})

    for turma, cpf, aluno in pendentes:
        aluno_dados, outra_escola = await consultar_cpf_com_status(
            page, cpf, etapa="verificar_pendentes", analise=analise
        )

        if outra_escola:
            _marcar_cancelado_outra_escola(aluno)
            confirmados += 1
            outra_escola_cpfs.append(cpf)
            print(f"✅ CPF {cpf} ({turma}): cadastro refeito para outra escola -> {SITUACAO_CANCELADO}")
            continue

        if aluno_dados is None:
            sem_resposta.append(cpf)
            continue

        opcoes = (aluno_dados.get("escolas_escolhidas") or {}).get("opcoes", [])
        posicao, anteriores = classificar_posicao_da_escola(opcoes)

        if posicao == POSICAO_IGNORAR:
            cadastros.pop(cpf, None)
            _aplicar_posicao_no_aluno(aluno, posicao, anteriores)
            confirmados += 1
            nao_primeira_cpfs.append(cpf)
            print(f"✅ CPF {cpf} ({turma}): nossa escola não é a 1ª opção -> não registrado")
            continue

        _herdar_vinculo(cadastros.get(cpf), aluno_dados)
        cadastros[cpf] = aluno_dados
        _aplicar_posicao_no_aluno(aluno, posicao, anteriores)
        if posicao == POSICAO_ENCAMINHADO:
            print(f"   ➡️ CPF {cpf} ({turma}): encaminhado por outra escola -> fila de análise")

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
    print(f"   Cancelados por cadastro em outra escola: {len(outra_escola_cpfs)}")
    print(f"   Cancelados por nossa escola não ser a 1ª opção: {len(nao_primeira_cpfs)}")
    print(f"   Sem resposta clara (mantidos como presumidos): {len(sem_resposta)}")
    print(f"   Arquivo salvo em: {caminho_pre_matricula()}")

    return {
        "total_pendentes": len(pendentes),
        "confirmados": confirmados,
        "sem_resposta": sem_resposta,
        "outra_escola": outra_escola_cpfs,
    }


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
            if tentativa_substituida(aluno):
                continue          # histórico da tentativa antiga: a situação do cadastro é da nova
            if aluno.get("cadastro_refeito_outra_escola"):
                continue          # cancelado por cadastro em outra escola; o cadastro antigo não vale mais
            if aluno.get("nao_e_primeira_opcao"):
                continue          # nossa escola não é a 1ª opção do último cadastro; a outra escola decide
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
            if tentativa_substituida(aluno):
                continue          # devolve a turma da tentativa atual, não a da antiga
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
            self._browser = await _navegador.lancar(self._pw, self.navegador, self.headless)
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


async def _executar_alvo(page, alvo, analise, pular_pendentes):
    """Etapas 1 -> 2 -> 4 -> 3 para UM alvo, na sessão já logada."""
    token = definir_alvo(alvo)
    try:
        print("\n" + "#" * 60)
        print(f"# PRÉ-MATRÍCULA {_ano()} (alvo: {alvo})")
        print("#" * 60)

        dados_prematricula = await etapa_coleta(page, analise=analise)
        if dados_prematricula is None:
            print("❌ Etapa 1 falhou. Abortando este alvo.")
            return {"ok": False, "sem_periodo": False, "resumo_pendentes": None, "arquivo_contatos": None}

        if dados_prematricula.get("sem_periodo"):
            return {"ok": True, "sem_periodo": True, "resumo_pendentes": None, "arquivo_contatos": None}

        dados_processados = await etapa_cadastro(page, dados_prematricula, analise=analise)

        resumo_pendentes = None
        if not pular_pendentes:
            resumo_pendentes = await etapa_verificar_pendentes(page, analise=analise)
        else:
            print("\n(Etapa 4 pulada)")

        arquivo_contatos = etapa_contatos(dados_processados, dados_prematricula)
        return {
            "ok": True,
            "sem_periodo": False,
            "resumo_pendentes": resumo_pendentes,
            "arquivo_contatos": arquivo_contatos,
        }
    finally:
        _ALVO.reset(token)


async def processo_completo_via_login(
    matricula=None,
    senha=None,
    analise=False,
    pular_pendentes=False,
    navegador="chromium",
    headless=True,
    avisar_whatsapp=True,
    alvo="ambos",
):
    """
    Etapas 1 -> 2 -> 4 -> 3 numa única sessão, para o(s) alvo(s) pedido(s):
    "proximo" (ano atual + 1), "atual" (ano atual) ou "ambos" (padrão; o próximo
    ano primeiro). Cada alvo tem o seu pre_matricula*.json e o seu CSV de contatos.

    `analise=True` salva screenshot de cada etapa; `pular_pendentes=True` pula a Etapa 4.

    Devolve {"ok", "resumo_pendentes", "arquivo_contatos", "resultados"}:
      - "resultados": {alvo: {"ok", "sem_periodo", "resumo_pendentes", "arquivo_contatos"}}
      - "resumo_pendentes" / "arquivo_contatos": do alvo "atual" (ou do único alvo rodado)
      - "ok" é False se o login falhar ou a Etapa 1 de algum alvo falhar. Alvo sem período
        cadastrado no portal ainda (ex.: 2027 antes de a SME abrir) NÃO é falha.
    """
    alvos = _alvos(alvo)

    print("=" * 60)
    print(f"PROCESSO DE PRÉ-MATRÍCULA - alvo(s): {', '.join(alvos)}")
    if analise:
        print("Modo de análise ativo: screenshots de cada etapa serão salvos.")
    print("=" * 60)

    resultados = {}

    async with _Sessao(matricula, senha, analise, navegador, headless) as sessao:
        if not sessao.ok:
            return {"ok": False, "resumo_pendentes": None, "arquivo_contatos": None, "resultados": {}}

        for a in alvos:
            resultados[a] = await _executar_alvo(sessao.page, a, analise, pular_pendentes)

    # Comunicado de matrícula por WhatsApp (provedor simulado por padrão; nunca quebra o processo).
    avisar_apos_pre_matricula(avisar_whatsapp)

    print("\n" + "=" * 60)
    for a, r in resultados.items():
        if r["sem_periodo"]:
            print(f"   [{a}] sem período cadastrado no portal (nada coletado)")
        elif not r["ok"]:
            print(f"   [{a}] ❌ falhou")
        elif r["resumo_pendentes"] is not None:
            rp = r["resumo_pendentes"]
            print(
                f"   [{a}] ✅ Pendentes verificados: {rp['total_pendentes']} | "
                f"Confirmados: {rp['confirmados']} | Sem resposta: {len(rp['sem_resposta'])}"
            )
        else:
            print(f"   [{a}] ✅ concluído")
    ok = all(r["ok"] for r in resultados.values())
    print("✅ PROCESSO COMPLETO FINALIZADO" if ok else "⚠️ PROCESSO FINALIZADO COM FALHAS")
    print("=" * 60)

    principal = resultados.get(ALVO_ATUAL) or next(iter(resultados.values()))
    return {
        "ok": ok,
        "resumo_pendentes": principal["resumo_pendentes"],
        "arquivo_contatos": principal["arquivo_contatos"],
        "resultados": resultados,
    }


async def completar_json_via_login(
    caminho_matriculados=None,
    caminho_intencoes=None,
    matricula=None,
    senha=None,
    analise=False,
    navegador="chromium",
    headless=True,
    avisar_whatsapp=True,
    alvo="atual",
):
    """
    Antigo --completar_json: lê os relatórios .xlsx (padrão: o mais recente
    "Relatorio_Alunos_Matriculados*.xlsx" / "Relatorio_Intencoes_Vaga*.xlsx"
    na pasta de dados do ano) e consulta o cadastro de cada CPF no site.
    As planilhas valem para UM alvo ("atual" ou "proximo"; "ambos" não faz sentido
    aqui): os dados vão para o pre_matricula*.json desse alvo.
    Requer openpyxl. Devolve {cpf: cadastro} ou None.
    """
    if alvo not in ALVOS_VALIDOS:
        raise ValueError(f"alvo inválido: {alvo!r} (use 'atual' ou 'proximo')")

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
        token = definir_alvo(alvo)
        try:
            resultado = await completar_json_a_partir_de_planilhas(
                sessao.page, caminho_matriculados, caminho_intencoes, analise=analise
            )
        finally:
            _ALVO.reset(token)

    if resultado is not None:
        avisar_apos_pre_matricula(avisar_whatsapp)
    return resultado


async def verificar_pendentes_via_login(
    matricula=None,
    senha=None,
    analise=False,
    navegador="chromium",
    headless=True,
    avisar_whatsapp=True,
    alvo="ambos",
):
    """
    Antigo --somente-pendentes: roda só a Etapa 4 para o(s) alvo(s).
    Devolve o resumo (alvo único) ou {alvo: resumo} (alvo="ambos"); None se o login falhar.
    """
    alvos = _alvos(alvo)

    resumos = {}
    async with _Sessao(matricula, senha, analise, navegador, headless) as sessao:
        if not sessao.ok:
            return None
        for a in alvos:
            token = definir_alvo(a)
            try:
                if not caminho_pre_matricula().exists():
                    print(f"[{a}] {caminho_pre_matricula().name} não existe ainda; nada a verificar.")
                    resumos[a] = {"total_pendentes": 0, "confirmados": 0, "sem_resposta": [], "outra_escola": []}
                    continue
                resumos[a] = await etapa_verificar_pendentes(sessao.page, analise=analise)
            finally:
                _ALVO.reset(token)

    avisar_apos_pre_matricula(avisar_whatsapp)

    print("\n" + "=" * 60)
    print("✅ --somente-pendentes FINALIZADO")
    print("=" * 60)
    return resumos[alvos[0]] if len(alvos) == 1 else resumos
""" === RESUMO ESTRUTURAL DO SCRIPT ===
Classes encontradas:
   - Classe: GerenciadorErros (Linha 242)
Funções encontradas:
   - Função: _chave_ordem() (Sem documentação)
   - Função: selecionar_turmas_interativo()
       Exibe menu numerado das turmas e retorna lista de alunos
       das turmas escolhidas. Suporta seleção múltipla (1,3,5) e "0" = todas.
   - Função: filtrar_alunos_cruzamento()
       Lê cruzamento-documentos.json e retorna apenas os alunos cujo
       Status NÃO é 'Completo — todos PC anexados'.
   - Função: filtrar_alunos_por_cgm()
       Recebe uma lista de CGMs e retorna os dados desses alunos
       a partir de alunos.json. CGMs não encontrados são avisados.
   - Função: _parse_validado()
       Retorna True se o campo 'tag' do documento indicar validado = SIM.
       Aceita string JSON ou lista já decodificada.
   - Função: _processar_json_api()
       Recebe o array JSON retornado pela API do SERE e devolve
       (lista_de_pdfs, lista_de_detalhes) — ignorando entradas sem arquivo.
   - Função: salvar_documentos() (Sem documentação)
   - Função: gerar_relatorio() (Sem documentação)
   - Função: __init__() (Sem documentação)
   - Função: registrar() (Sem documentação)
   - Função: salvar() (Sem documentação)
   - Função: _carregar_raw() (Sem documentação)
   - Função: carregar_alunos_com_erro() (Sem documentação)
   - Função: limpar_resolvidos() (Sem documentação)
==================================== """

import os
import sys
import json
import asyncio
import argparse
from datetime import datetime
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pathlib import Path
from src.comum.credenciais import LOGIN, SENHA
from src.comum.configuracao import cgm_upload as _cgm_upload_configurado
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.sere_normalizacao import SERE_SLOTS, IDTIPO_PARA_SLOT, SINONIMOS, SINONIMOS_LOWER
from src.comum import paths as _paths
from src.comum.opcoes_execucao import (adicionar_argumentos, analisar_cgms, opcoes_do_argparse,
                                         selecionar_alunos)

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, PatternFill, Font
from openpyxl.utils import get_column_letter
from src.comum import navegador as _navegador

# ============================================================
#  CONFIGURAÇÕES
# ============================================================
URL  = "https://www.sere.pr.gov.br/sere"

# ─────────────────────────────────────────────────────────────────────────
# CAMINHOS DE DADOS
# ─────────────────────────────────────────────────────────────────────────
# Antes: BASE = Path.home() / "compartilhado/ARQUIVOS" (fixo, servidor Linux
# específico). Trocado por src.comum.paths.dados_ano_atual(), que resolve
# para <pasta_de_instalação>/dados/<ano_letivo>/ — correto tanto para o
# executável Windows instalado quanto para este ambiente de desenvolvimento.
SERE = _paths.dados_ano_atual()
SERE.mkdir(parents=True, exist_ok=True)

ALUNOS_JSON      = SERE / "alunos.json"
TURMAS_JSON      = SERE / "turmas.json"
DOCUMENTOS_JSON  = SERE / "documentos-alunos.json"
CRUZAMENTO_JSON  = SERE / "cruzamento-documentos.json"
RELATORIO_XLSX   = SERE / "relatorio_documentos-SERE.xlsx"
ERROS_JSON       = SERE / "erros_processamento.json"

# Documentos obrigatórios usados no relatório de pendências
DOCUMENTOS = [
    "Declaração de vacina",
    "Requerimento de Matricula",
    "Comprovante de Vacinação",
    "RG",
    "CPF do Aluno",
    "Comprovante de residência",
    "Certidão de nascimento do aluno",
    "CPF Responsável",
]

# CGMs para o modo --alunos (edite aqui e rode com --alunos)
# Antes: *CGM_UPLOAD vinha de "from sere_2026 import CGM_UPLOAD" (acoplamento
# cruzado entre este script e sere_2026.py). Agora vem de
# src.comum.configuracao.cgm_upload(), a mesma lista usada pelo sere_2026.py
# portado — uma única fonte de verdade, configurável via setup ou editando
# config/config_usuario.json diretamente.
CGM_ANALISE: list[str] = [
    # Cole os CGMs abaixo, um por linha:
    # "1027161410",
    # "1024495511",

    *_cgm_upload_configurado(),

]


# ============================================================
#  MODO TURMA — seleção interativa + filtragem por turma
# ============================================================
_ORDEM_TURMAS = [
    "INFANTIL 4", "INFANTIL 5",
    "1º ANO", "1º Ano",
    "2º ANO", "2º Ano",
    "3º ANO", "3º Ano",
    "4º ANO", "4º Ano",
    "5º ANO", "5º Ano",
]

def _chave_ordem(nome_turma: str) -> tuple:
    nome_up = nome_turma.upper()
    for i, prefixo in enumerate(_ORDEM_TURMAS):
        if prefixo.upper() in nome_up:
            return (i, nome_turma)
    return (len(_ORDEM_TURMAS), nome_turma)


def selecionar_turmas_interativo(caminho_turmas: str) -> list[dict]:
    """
    Exibe menu numerado das turmas e retorna lista de alunos
    das turmas escolhidas. Suporta seleção múltipla (1,3,5) e "0" = todas.
    """
    with open(caminho_turmas, "r", encoding="utf-8") as f:
        turmas: dict[str, list] = json.load(f)

    nomes_ordenados = sorted(turmas.keys(), key=_chave_ordem)

    print()
    print("=" * 60)
    print("  MODO TURMA — selecione a(s) turma(s) para processar")
    print("=" * 60)
    print(f"   {'0':>3}  →  TODAS AS TURMAS")
    print()
    for idx, nome in enumerate(nomes_ordenados, start=1):
        qtd = len(turmas[nome])
        print(f"   {idx:>3}  →  {nome}  ({qtd} alunos)")
    print()

    while True:
        if not sys.stdin or not sys.stdin.isatty():
            # Rodando pelo sistema (sem terminal): perguntar travaria ou quebraria com EOFError.
            print("❌ --turma sem valor precisa de um terminal para perguntar qual turma.")
            print("   Informe a turma: --turma \"5º Ano\"  (veja a opção na tela de Automações).")
            sys.exit(1)
        entrada = input("Digite o(s) número(s) [ex: 1  ou  1,3,5]: ").strip()
        if not entrada:
            print("   ⚠️  Entrada vazia. Tente novamente.")
            continue

        if entrada == "0":
            selecionados = nomes_ordenados
            break

        partes = [p.strip() for p in entrada.split(",")]
        invalidos = [
            p for p in partes
            if not p.isdigit() or not (1 <= int(p) <= len(nomes_ordenados))
        ]
        if invalidos:
            print(f"   ⚠️  Valor(es) inválido(s): {', '.join(invalidos)}. Tente novamente.")
            continue

        selecionados = [nomes_ordenados[int(p) - 1] for p in partes]
        break

    # Deduplica por CGM (aluno em mais de uma turma)
    alunos_vistos: set[str] = set()
    alunos: list[dict] = []
    for nome_turma in selecionados:
        for aluno in turmas[nome_turma]:
            cgm = str(aluno["CGM"])
            if cgm not in alunos_vistos:
                alunos_vistos.add(cgm)
                alunos.append({"CGM": cgm, "Nome": aluno["Nome"], "Turma": nome_turma})

    print()
    print(f"✅ Turma(s): {', '.join(selecionados)}")
    print(f"   👥 Total de alunos: {len(alunos)}")
    print()
    return alunos


# ============================================================
#  MODO RÁPIDO — filtra alunos não-completos pelo cruzamento
# ============================================================
_STATUS_COMPLETO = "Completo — todos PC anexados"

def filtrar_alunos_cruzamento(caminho_cruzamento: str) -> list[dict]:
    """
    Lê cruzamento-documentos.json e retorna apenas os alunos cujo
    Status NÃO é 'Completo — todos PC anexados'.
    """
    if not Path(caminho_cruzamento).exists():
        print(f"❌ Arquivo de cruzamento não encontrado: {caminho_cruzamento}")
        print("   Execute cruzar_documentos.py primeiro.")
        return []

    with open(caminho_cruzamento, "r", encoding="utf-8") as f:
        dados = json.load(f)

    alunos_cruzamento: list[dict] = dados.get("Alunos", [])
    data_hora = dados.get("Data_Hora", "?")

    incompletos: list[dict] = []
    completos = 0

    for aluno in alunos_cruzamento:
        cgm    = str(aluno["CGM"])
        nome   = aluno.get("Nome", "SemNome")
        turma  = aluno.get("Turma", "")
        status = aluno.get("Status", "")

        if status == _STATUS_COMPLETO:
            completos += 1
        else:
            incompletos.append({"CGM": cgm, "Nome": nome, "Turma": turma, "_status": status})

    print(f"📂 Cruzamento de: {data_hora}")
    print(f"📋 Total de alunos no cruzamento   : {len(alunos_cruzamento)}")
    print(f"   ✅ Completos (ignorados)         : {completos}")
    print(f"   ⚠️  Não-completos                : {len(incompletos)}")
    print()

    if incompletos:
        print("Alunos que serão reprocessados:")
        for a in incompletos:
            print(f"   • {a['Nome']} (CGM: {a['CGM']}) — {a['_status']}")
        print()

    # Remove campo auxiliar antes de retornar
    for a in incompletos:
        a.pop("_status", None)

    return incompletos


# ============================================================
#  Auxiliar — CGMs de alunos marcados como transferidos
# ============================================================
def obter_cgms_transferidos(caminho_turmas: str) -> set[str]:
    """
    Lê turmas.json e retorna o conjunto de CGMs cujo campo
    'Situacao' é 'Transferido' (comparação case-insensitive).
    """
    if not Path(caminho_turmas).exists():
        return set()

    with open(caminho_turmas, "r", encoding="utf-8") as f:
        turmas: dict[str, list] = json.load(f)

    transferidos: set[str] = set()
    for alunos_turma in turmas.values():
        for aluno in alunos_turma:
            situacao = str(aluno.get("Situação", aluno.get("Situacao", ""))).strip().lower()
            if situacao == "transferido":
                transferidos.add(str(aluno["CGM"]))

    return transferidos


def obter_situacao_por_cgm(caminho_turmas: str) -> dict[str, str]:
    """
    Lê turmas.json e retorna um dicionário {CGM: 'Matriculado' | 'Transferido'}
    com base no campo 'Situacao' de cada aluno.
    """
    if not Path(caminho_turmas).exists():
        return {}

    with open(caminho_turmas, "r", encoding="utf-8") as f:
        turmas: dict[str, list] = json.load(f)

    situacoes: dict[str, str] = {}
    for alunos_turma in turmas.values():
        for aluno in alunos_turma:
            cgm      = str(aluno["CGM"])
            situacao = str(aluno.get("Situação", aluno.get("Situacao", ""))).strip().lower()
            situacoes[cgm] = "Transferido" if situacao == "transferido" else "Matriculado"

    return situacoes


def filtrar_alunos_por_situacao(caminho_turmas: str, apenas_transferidos: bool) -> list[dict]:
    """
    Lê turmas.json e retorna a lista de alunos (com CGM, Nome, Turma, Situacao).
    Se apenas_transferidos=True, retorna somente os com Situacao == 'Transferido'.
    Caso contrário, retorna todos os alunos de todas as turmas.
    """
    with open(caminho_turmas, "r", encoding="utf-8") as f:
        turmas: dict[str, list] = json.load(f)

    alunos_vistos: set[str] = set()
    alunos: list[dict] = []

    for nome_turma, alunos_turma in turmas.items():
        for aluno in alunos_turma:
            cgm = str(aluno["CGM"])
            situacao_raw = str(aluno.get("Situação", aluno.get("Situacao", ""))).strip().lower()
            situacao = "Transferido" if situacao_raw == "transferido" else "Matriculado"

            if apenas_transferidos and situacao != "Transferido":
                continue

            if cgm not in alunos_vistos:
                alunos_vistos.add(cgm)
                alunos.append({
                    "CGM":      cgm,
                    "Nome":     aluno["Nome"],
                    "Turma":    nome_turma,
                    "Situacao": situacao,
                })

    rotulo = "transferidos" if apenas_transferidos else "todos"
    print(f"✅ Modo {rotulo}: {len(alunos)} aluno(s) selecionados")
    print()

    return alunos


# ============================================================
#  MODO ALUNOS — filtra por lista de CGMs informados
# ============================================================
def filtrar_alunos_por_cgm(cgms_alvo: list[str], caminho_alunos: str) -> list[dict]:
    """
    Recebe uma lista de CGMs e retorna os dados desses alunos
    a partir de alunos.json. CGMs não encontrados são avisados.
    """
    cgms_set = {str(c).strip() for c in cgms_alvo}

    with open(caminho_alunos, "r", encoding="utf-8") as f:
        todos_alunos: list[dict] = json.load(f)

    indice = {str(a["CGM"]): a for a in todos_alunos}

    encontrados: list[dict] = []
    nao_encontrados: list[str] = []

    for cgm in cgms_alvo:
        cgm_str = str(cgm).strip()
        if cgm_str in indice:
            a = indice[cgm_str]
            encontrados.append({
                "CGM":   cgm_str,
                "Nome":  a.get("Nome", "SemNome"),
                "Turma": a.get("Turma", ""),
            })
        else:
            nao_encontrados.append(cgm_str)

    print(f"🎯 CGMs solicitados   : {len(cgms_alvo)}")
    print(f"   ✅ Encontrados      : {len(encontrados)}")
    if nao_encontrados:
        print(f"   ❌ Não encontrados  : {len(nao_encontrados)}")
        for cgm in nao_encontrados:
            print(f"      • CGM {cgm} não consta em {caminho_alunos}")
    print()

    if encontrados:
        print("Alunos que serão processados:")
        for a in encontrados:
            turma_label = f" [{a['Turma']}]" if a.get("Turma") else ""
            print(f"   • {a['Nome']} (CGM: {a['CGM']}){turma_label}")
        print()

    return encontrados


# ============================================================
#  GERENCIADOR DE ERROS
# ============================================================
class GerenciadorErros:
    def __init__(self, caminho: str):
        self.caminho = caminho
        self.erros: list[dict] = []

    def registrar(self, cgm, nome: str, etapa: str, mensagem: str):
        entrada = {
            "CGM":       str(cgm),
            "Nome":      nome,
            "Etapa":     etapa,
            "Mensagem":  mensagem,
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.erros.append(entrada)
        print(f"   ⚠️  [ERRO REGISTRADO] {etapa} — {mensagem}")

    def salvar(self):
        try:
            Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)
            anteriores = self._carregar_raw()
            cgms_novos = {e["CGM"] for e in self.erros}
            anteriores = [e for e in anteriores if e["CGM"] not in cgms_novos]
            todos = anteriores + self.erros
            with open(self.caminho, "w", encoding="utf-8") as f:
                json.dump(todos, f, ensure_ascii=False, indent=2)
            print(f"\n📋 Arquivo de erros salvo em: {self.caminho}")
            print(f"   Total de erros nesta execução : {len(self.erros)}")
            print(f"   Total acumulado no arquivo    : {len(todos)}")
        except Exception as e:
            print(f"❌ Não foi possível salvar o arquivo de erros: {e}")

    def _carregar_raw(self) -> list[dict]:
        try:
            with open(self.caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def carregar_alunos_com_erro(self) -> list[dict]:
        raw = self._carregar_raw()
        if not raw:
            print("✅ Nenhum erro registrado anteriormente. Nada a reprocessar.")
            return []
        vistos = set()
        alunos = []
        for entrada in raw:
            cgm = entrada["CGM"]
            if cgm not in vistos:
                vistos.add(cgm)
                alunos.append({"CGM": cgm, "Nome": entrada.get("Nome", "SemNome")})
        print(f"🔁 {len(alunos)} aluno(s) com erro serão reprocessados:")
        for a in alunos:
            print(f"   • {a['Nome']} (CGM: {a['CGM']})")
        return alunos

    def limpar_resolvidos(self, cgms_ok: set):
        raw = self._carregar_raw()
        restantes = [e for e in raw if e["CGM"] not in cgms_ok]
        with open(self.caminho, "w", encoding="utf-8") as f:
            json.dump(restantes, f, ensure_ascii=False, indent=2)
        removidos = len(raw) - len(restantes)
        print(f"\n🧹 {removidos} erro(s) removido(s) (alunos resolvidos).")
        if restantes:
            print(f"   ⚠️  {len(restantes)} erro(s) ainda persistem.")


# ============================================================
#  HELPERS — parse do JSON da API
# ============================================================
def _parse_validado(tag_raw) -> bool:
    """
    Retorna True se o campo 'tag' do documento indicar validado = SIM.
    Aceita string JSON ou lista já decodificada.
    """
    if not tag_raw:
        return False
    try:
        tag_list = json.loads(tag_raw) if isinstance(tag_raw, str) else tag_raw
        return any(
            str(t.get("validado", "")).upper() == "SIM"
            for t in tag_list
            if isinstance(t, dict)
        )
    except (json.JSONDecodeError, TypeError):
        return False


def _processar_json_api(dados_json: list) -> tuple[list[str], list[dict]]:
    """
    Recebe o array JSON retornado pela API do SERE e devolve
    (lista_de_pdfs, lista_de_detalhes) — ignorando entradas sem arquivo.
    """
    pdfs: list[str]     = []
    detalhes: list[dict] = []

    for doc in dados_json:
        nome_pdf = (doc.get("nomearquivo") or "").strip()
        if not nome_pdf:          # documento cadastrado mas não anexado → ignora
            continue

        tipo_doc      = (doc.get("tipodocumento") or "").strip()
        data_anexacao = (doc.get("datainclusao")  or "").strip() or None
        validado      = _parse_validado(doc.get("tag"))

        pdfs.append(nome_pdf)
        detalhes.append({
            "tipo":     tipo_doc,
            "arquivo":  nome_pdf,
            "data":     data_anexacao,
            "validado": validado,
        })

    return pdfs, detalhes


# ============================================================
#  NAVEGAÇÃO NO SERE
# ============================================================
async def navigate_to_por_aluno(page):
    try:
        menu = await page.query_selector("#divoCMenu0_0")
        if not menu:
            raise Exception("Não encontrou o menu principal")
        await menu.evaluate("""
            (el) => {
                var evento = new MouseEvent('mouseover', {
                    view: window, bubbles: true, cancelable: true
                });
                el.dispatchEvent(evento);
            }
        """)
        await page.wait_for_timeout(500)
        await page.click("//div[contains(text(),'Consulta Padrão')]")
        await page.wait_for_timeout(300)
        await page.click("//div[contains(text(),'Por Aluno')]")
    except Exception as e:
        raise Exception(f"Erro ao navegar para Por Aluno: {e}")


# ============================================================
#  COLETA DE DOCUMENTOS — Opção A: interceptação de rede
# ============================================================
async def coletar_documentos(
    page,
    alunos: list[dict],
    gerenciador_erros: GerenciadorErros,
) -> tuple[list[dict], set]:
    documentos_data: list[dict] = []
    cgms_ok: set[str]           = set()

    situacoes_por_cgm = obter_situacao_por_cgm(TURMAS_JSON)

    for aluno in alunos:
        # Ponto seguro de cancelamento (botão "Cancelar" da interface): se o
        # usuário pediu, levanta CancelamentoSolicitado aqui — o `finally` de
        # executar() fecha o navegador. Fora da interface não faz nada.
        verificar_cancelamento()
        cgm      = aluno["CGM"]
        nome     = aluno.get("Nome", "SemNome")
        turma    = aluno.get("Turma", "")
        situacao = aluno.get("Situacao") or situacoes_por_cgm.get(str(cgm), "Matriculado")
        label = f"{nome} (CGM: {cgm})" + (f" [{turma}]" if turma else "") + f" — {situacao}"
        print(f"\n🔎 Processando {label}")

        # ── 1. Busca pelo CGM ──────────────────────────────────────────────
        try:
            await page.wait_for_selector("#cgm", timeout=10000)
            await page.fill("#cgm", str(cgm))
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)
        except Exception as e:
            gerenciador_erros.registrar(cgm, nome, "Busca por CGM", str(e))
            continue

        # ── 2. Seleciona turma (primeiro link disponível) ──────────────────
        try:
            turmas_links = await page.query_selector_all("a.texto_normal")
            if turmas_links:
                turma_texto = await turmas_links[0].inner_text()
                print(f"   🎯 Turma: {turma_texto.strip()}")
                await turmas_links[0].click()
                await page.wait_for_timeout(2000)
            else:
                print(f"   ℹ️  Nenhuma turma encontrada para {nome}")
        except Exception as e:
            gerenciador_erros.registrar(cgm, nome, "Seleção de Turma", str(e))

        pdfs:     list[str]  = []
        detalhes: list[dict] = []

        # ── 3. Clica em "Listar Arquivos" interceptando a resposta JSON ────
        try:
            botao = await page.wait_for_selector(
                "input[value='Listar Arquivos']", timeout=5000
            )

            # Registra o listener ANTES de clicar para não perder a resposta.
            # O predicate filtra pela URL que o SERE usa para retornar os
            # documentos do aluno (ajuste o fragmento se necessário).
            async with page.expect_response(
                lambda r: (
                    r.status == 200
                    and (
                        "listarArquivos"  in r.url
                        or "documentos"   in r.url
                        or "pasta_virtual" in r.url
                        or "ListarArquivos" in r.url
                    )
                ),
                timeout=15000,
            ) as resp_info:
                await botao.click()

            response = await resp_info.value

            # Tenta decodificar como JSON
            try:
                dados_json = await response.json()

                if isinstance(dados_json, list) and dados_json:
                    pdfs, detalhes = _processar_json_api(dados_json)

                    for d in detalhes:
                        status_txt = "✅ validado" if d["validado"] else "⏳ não validado"
                        print(f"      📄 {d['arquivo']} | {d['data']} | {status_txt}")

                    print(f"   📂 {len(pdfs)} documento(s) encontrado(s)")
                    cgms_ok.add(str(cgm))

                else:
                    # JSON veio vazio ou em formato inesperado → fallback HTML
                    print("   ⚠️  JSON vazio ou formato inesperado — usando fallback HTML")
                    await page.wait_for_selector("#div_pasta_virtual", timeout=10000)
                    pdfs, detalhes = await _fallback_html(page)
                    print(f"   📂 {len(pdfs)} documento(s) encontrado(s) (HTML)")
                    cgms_ok.add(str(cgm))

            except Exception as json_err:
                # Resposta não é JSON (ex: HTML) → fallback HTML
                print(f"   ⚠️  Resposta não é JSON ({json_err}) — usando fallback HTML")
                try:
                    await page.wait_for_selector("#div_pasta_virtual", timeout=10000)
                    pdfs, detalhes = await _fallback_html(page)
                    print(f"   📂 {len(pdfs)} documento(s) encontrado(s) (HTML)")
                    cgms_ok.add(str(cgm))
                except PlaywrightTimeoutError:
                    print(f"   ℹ️  Nenhum PDF no modal para {nome}")
                    cgms_ok.add(str(cgm))

        except PlaywrightTimeoutError as te:
            # O botão não apareceu OU a resposta de rede não veio a tempo
            if "expect_response" in str(te) or "Timeout" in str(te):
                # Pode ser que o SERE não disparou a request esperada;
                # tenta ler o modal que já esteja aberto via HTML.
                try:
                    await page.wait_for_selector("#div_pasta_virtual", timeout=5000)
                    pdfs, detalhes = await _fallback_html(page)
                    print(f"   📂 {len(pdfs)} documento(s) (fallback após timeout de rede)")
                    cgms_ok.add(str(cgm))
                except PlaywrightTimeoutError:
                    gerenciador_erros.registrar(
                        cgm, nome, "Listar Arquivos",
                        "Botão 'Listar Arquivos' não apareceu ou nenhuma resposta de rede (timeout)"
                    )
            else:
                gerenciador_erros.registrar(
                    cgm, nome, "Listar Arquivos", str(te)
                )

        # ── 4. Monta registro do aluno ─────────────────────────────────────
        documentos_data.append({
            "CGM":        cgm,
            "Nome":       nome,
            "Turma":      turma,
            "Situacao":   situacao,
            "Documentos": pdfs,
            "Detalhes":   detalhes,
            "Total":      len(pdfs),
        })

        # ── 5. Volta para a tela de busca ──────────────────────────────────
        try:
            voltar = await page.query_selector("a[href*='AoClicarVoltar']")
            if voltar:
                await voltar.click()
            else:
                await page.go_back()
            await page.wait_for_timeout(1000)
        except Exception as e:
            gerenciador_erros.registrar(cgm, nome, "Navegação (Voltar)", str(e))

    return documentos_data, cgms_ok


# ============================================================
#  FALLBACK — leitura da tabela HTML (comportamento anterior)
# ============================================================
async def _fallback_html(page) -> tuple[list[str], list[dict]]:
    """
    Lê os documentos diretamente do modal HTML (#pasta_virtual).
    Usado quando a interceptação de rede não retorna JSON válido.
    """
    pdfs:     list[str]  = []
    detalhes: list[dict] = []

    linhas = await page.query_selector_all(
        "#pasta_virtual tbody tr:not(:first-child)"
    )

    for linha in linhas:
        colunas = await linha.query_selector_all("td")
        if len(colunas) < 3:
            continue

        tipo_doc  = (await colunas[0].inner_text()).strip()
        col2_html = await colunas[1].inner_html()
        nome_pdf  = ""
        validado  = False
        
        extensoes = ['.pdf', '.jpeg', '.jpg', '.png']

        if any(ext in col2_html.lower() for ext in extensoes):
            col2_texto = (await colunas[1].inner_text()).strip()
            for parte in col2_texto.split():
                parte_lower = parte.lower()
                if any(parte_lower.endswith(ext) for ext in extensoes):
                    nome_pdf = parte
                    break

            # Ícone "Validar" presente = ainda NÃO validado
            icone_validar = await colunas[1].query_selector(
                "i.fa-check-circle[title='Validar']"
            )
            validado = (icone_validar is None)

        data_anexacao = (await colunas[2].inner_text()).strip() or None

        if nome_pdf:
            pdfs.append(nome_pdf)
            detalhes.append({
                "tipo":     tipo_doc,
                "arquivo":  nome_pdf,
                "data":     data_anexacao,
                "validado": validado,
            })
            status_txt = "✅ validado" if validado else "⏳ não validado"
            print(f"      📄 {nome_pdf} | {data_anexacao} | {status_txt}")

    return pdfs, detalhes


# ============================================================
#  SALVAMENTO DO JSON
# ============================================================
def salvar_documentos(dados: list[dict], caminho: str):
    try:
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        existentes = {}
        if Path(caminho).exists():
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    brutos = json.load(f)
            except json.JSONDecodeError:
                brutos = []

            for item in brutos:
                if "CGM" not in item:
                    print(f"   ⚠️  Registro ignorado em {caminho} (sem CGM): {item}")
                    continue
                if "Nome" not in item:
                    print(f"   ⚠️  Registro sem 'Nome' encontrado (CGM {item['CGM']}) — preenchendo com 'SemNome'")
                    item["Nome"] = "SemNome"
                existentes[str(item["CGM"])] = item

        for item in dados:
            existentes[str(item["CGM"])] = item

        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(list(existentes.values()), f, ensure_ascii=False, indent=2)

        print(f"💾 JSON salvo em: {caminho}")
    except Exception as e:
        print(f"❌ Erro ao salvar JSON: {e}")


# ============================================================
#  GERAÇÃO DO RELATÓRIO EXCEL
# ============================================================
def gerar_relatorio(documentos_data: list[dict], caminho: str):
    print("\n📊 Gerando relatório Excel...")

    linhas = []
    for aluno in documentos_data:
        cgm        = str(aluno.get("CGM", ""))
        nome       = aluno.get("Nome", "SemNome")
        turma      = aluno.get("Turma", "")
        situacao   = aluno.get("Situacao", "Matriculado")
        docs_aluno = aluno.get("Documentos", [])
        detalhes   = aluno.get("Detalhes", [])

        detalhe_por_pdf = {d["arquivo"]: d for d in detalhes}

        status = {}
        for doc in DOCUMENTOS:
            doc_key        = doc.replace(" ", "_")
            pdf_encontrado = next(
                (pdf for pdf in docs_aluno if doc_key in pdf), None
            )
            if pdf_encontrado:
                det      = detalhe_por_pdf.get(pdf_encontrado, {})
                validado = det.get("validado")
                data     = det.get("data", "")
                if validado:
                    status[doc]               = "✔"
                    status[doc + "_data"]     = data
                    status[doc + "_validado"] = "Sim"
                else:
                    status[doc]               = "⚠"
                    status[doc + "_data"]     = data
                    status[doc + "_validado"] = "Não"
            else:
                status[doc]               = "❌"
                status[doc + "_data"]     = ""
                status[doc + "_validado"] = ""

        enviados = sum(1 for doc in DOCUMENTOS if status[doc] in ("✔", "⚠"))
        perc     = round(enviados / len(DOCUMENTOS) * 100, 2)

        linha = {"Turma": turma, "Nome": nome, "CGM": cgm, "Situação": situacao}
        linha.update(status)
        linha["Porcentagem"] = perc
        linhas.append(linha)

    df = pd.DataFrame(linhas).sort_values(["Turma", "Nome"]).reset_index(drop=True)
    df.to_excel(caminho, index=False)

    wb = load_workbook(caminho)
    ws = wb.active
    ws.freeze_panes = "E2"

    fill_colors = ["FFF2CC", "D9EAD3", "CCE5FF", "F4CCCC", "EAD1DC", "CFE2F3"]
    colunas     = list(df.columns)
    max_row     = ws.max_row

    for col_idx, col_name in enumerate(colunas, start=1):
        col_letter = get_column_letter(col_idx)
        color      = fill_colors[(col_idx - 1) % len(fill_colors)]
        fill       = PatternFill(start_color=color, end_color=color, fill_type="solid")

        header_cell = ws[f"{col_letter}1"]
        header_cell.font = Font(bold=True, name="Arial", size=10)
        header_cell.fill = fill
        if col_idx >= 5:
            header_cell.alignment = Alignment(
                textRotation=45, horizontal="center", vertical="center"
            )
        else:
            header_cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )

        for row in range(2, max_row + 1):
            cell           = ws[f"{col_letter}{row}"]
            cell.fill      = fill
            cell.font      = Font(name="Arial", size=10)
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.column_dimensions["A"].width = 28   # Turma
    ws.column_dimensions["B"].width = 40   # Nome
    ws.column_dimensions["C"].width = 14   # CGM
    ws.column_dimensions["D"].width = 14   # Situação
    for col_idx in range(5, len(colunas) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 8
    ws.row_dimensions[1].height = 80

    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_fill   = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    green_font = Font(name="Arial", size=10, color="276221")
    red_font   = Font(name="Arial", size=10, color="9C0006")

    situacao_transferido_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    situacao_matriculado_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    situacao_transferido_font = Font(name="Arial", size=10, color="9C0006", bold=True)
    situacao_matriculado_font = Font(name="Arial", size=10, color="276221", bold=True)

    if "Situação" in colunas:
        col_situacao = colunas.index("Situação") + 1
        for row in range(2, max_row + 1):
            cell = ws.cell(row=row, column=col_situacao)
            if cell.value == "Transferido":
                cell.fill = situacao_transferido_fill
                cell.font = situacao_transferido_font
            else:
                cell.fill = situacao_matriculado_fill
                cell.font = situacao_matriculado_font

    doc_start = colunas.index(DOCUMENTOS[0]) + 1
    doc_end   = colunas.index(DOCUMENTOS[-1]) + 1

    for row in range(2, max_row + 1):
        for col_idx in range(doc_start, doc_end + 1):
            cell = ws.cell(row=row, column=col_idx)
            if cell.value == "✔":
                cell.fill = green_fill
                cell.font = green_font
            elif cell.value == "❌":
                cell.fill = red_fill
                cell.font = red_font

    wb.save(caminho)

    # ---------- Aba: Documentos Faltando ----------
    faltando_rows = []
    for aluno in documentos_data:
        cgm        = str(aluno.get("CGM", ""))
        nome       = aluno.get("Nome", "SemNome")
        turma      = aluno.get("Turma", "")
        docs_aluno = aluno.get("Documentos", [])
        faltando   = [
            doc for doc in DOCUMENTOS
            if not any(doc.replace(" ", "_") in pdf for pdf in docs_aluno)
        ]
        if faltando:
            faltando_rows.append({
                "Turma":               turma,
                "Nome":                nome,
                "CGM":                 cgm,
                "Documentos Faltando": ", ".join(faltando),
                "Qtd Faltando":        len(faltando),
            })

    df_faltando = (
        pd.DataFrame(faltando_rows)
        .sort_values(["Turma", "Qtd Faltando"], ascending=[True, False])
        .reset_index(drop=True)
    )

    with pd.ExcelWriter(caminho, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df_faltando.to_excel(writer, sheet_name="Documentos Faltando", index=False)

    wb2 = load_workbook(caminho)
    ws2 = wb2["Documentos Faltando"]
    ws2.freeze_panes = "A2"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    for col_idx in range(1, 6):
        cell           = ws2.cell(row=1, column=col_idx)
        cell.fill      = header_fill
        cell.font      = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    ws2.column_dimensions["A"].width = 28   # Turma
    ws2.column_dimensions["B"].width = 42   # Nome
    ws2.column_dimensions["C"].width = 14   # CGM
    ws2.column_dimensions["D"].width = 70   # Documentos Faltando
    ws2.column_dimensions["E"].width = 14   # Qtd

    alt_fills = [
        PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid"),
        PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid"),
    ]
    for row in range(2, ws2.max_row + 1):
        f = alt_fills[row % 2]
        for col_idx in range(1, 6):
            cell           = ws2.cell(row=row, column=col_idx)
            cell.fill      = f
            cell.font      = Font(name="Arial", size=10)
            cell.alignment = Alignment(
                horizontal="left" if col_idx in (2, 4) else "center",
                vertical="center",
                wrap_text=(col_idx == 4),
            )
        ws2.row_dimensions[row].height = 30

    ws2.row_dimensions[1].height = 22
    wb2.save(caminho)

    total_alunos     = len(df)
    com_faltando     = len(df_faltando)
    total_documentos = sum(a["Total"] for a in documentos_data)

    print(f"\n✅ Relatório salvo em: {caminho}")
    print(f"   👥 Total de alunos processados      : {total_alunos}")
    print(f"   📄 Total de documentos anexados     : {total_documentos}")
    print(f"   ⚠️  Alunos com documentos faltando  : {com_faltando}")


# ============================================================
#  FLUXO PRINCIPAL
# ============================================================
def _headless() -> bool:
    """
    Firefox sem janela por padrão. Para ver o navegador durante um
    diagnóstico, defina a variável de ambiente AUTO_SERE_HEADLESS=0 antes de
    iniciar o servidor (no WSL isso exige WSLg/servidor X).
    """
    return os.getenv("AUTO_SERE_HEADLESS", "1").strip().lower() not in ("0", "false", "no", "nao", "não")


async def _registrar_falha_login(page, motivo: str) -> str:
    """
    Guarda evidências de uma falha de login (captura de tela + URL + trecho do
    texto da página) e devolve um resumo curto para entrar na mensagem de
    erro. Nunca levanta exceção — é só diagnóstico. Não registra a senha.
    """
    partes = [motivo]
    try:
        partes.append(f"URL atual: {page.url}")
    except Exception:
        pass
    try:
        texto = await page.evaluate("() => (document.body && document.body.innerText) || ''")
        texto = " ".join(str(texto).split())[:400]
        if texto:
            partes.append(f"Texto na página: \"{texto}\"")
    except Exception:
        pass
    try:
        captura = SERE / "debug_login_sere.png"
        await page.screenshot(path=str(captura), full_page=True)
        partes.append(f"Captura de tela: {captura}")
    except Exception:
        pass
    resumo = " | ".join(partes)
    print(f"   ❌ {resumo}")
    return resumo


async def _fazer_login(page) -> None:
    """
    Login no SERE com verificação real: só segue quando o menu principal
    aparece. Antes, o script clicava em Entrar, esperava 5 s fixos e seguia —
    qualquer falha de login só aparecia depois, como o enganoso
    "Não encontrou o menu principal".
    """
    if not LOGIN or not SENHA:
        raise RuntimeError(
            "Credenciais do SERE não configuradas (login/senha vazios). "
            "Salve em Configurações > Salvar senha do SERE e rode de novo."
        )

    print("🌐 Acessando o SERE...")
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightTimeoutError:
        raise RuntimeError(f"O SERE não respondeu em 60 s ({URL}). Verifique a internet ou se o site está no ar.")

    try:
        await page.wait_for_selector("#CHAVE", timeout=20_000)
    except PlaywrightTimeoutError:
        detalhe = await _registrar_falha_login(page, "A tela de login não carregou (campo #CHAVE não apareceu em 20 s)")
        raise RuntimeError(f"Falha ao abrir a tela de login do SERE. {detalhe}")

    await page.fill("#CHAVE", LOGIN)
    await page.fill("#CHAVE_ENCRIPT", SENHA)
    await page.click("//input[@value='Entrar']")

    try:
        await page.wait_for_selector("#divoCMenu0_0", state="attached", timeout=30_000)
    except PlaywrightTimeoutError:
        detalhe = await _registrar_falha_login(
            page, "O menu principal não apareceu em 30 s após clicar em Entrar (login recusado, site lento ou layout alterado)"
        )
        raise RuntimeError(f"Login no SERE não foi concluído. {detalhe}")

    await page.wait_for_timeout(1000)
    print("✅ Login realizado.")


async def executar(alunos: list[dict], gerenciador_erros: GerenciadorErros):
    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", _headless())
        try:
            page = await browser.new_page()

            await _fazer_login(page)
            await navigate_to_por_aluno(page)

            documentos_data, cgms_ok = await coletar_documentos(
                page, alunos, gerenciador_erros
            )
        finally:
            # Fecha o navegador também quando algo falha (antes, um erro
            # deixava o Firefox aberto em segundo plano).
            await browser.close()

    return documentos_data, cgms_ok


def usa_selecao_compartilhada(args) -> bool:
    """
    True quando a seleção vem de --turma NOME... e/ou --matriculados (e --transferidos junto).
    `--transferidos` sozinho continua no ramo antigo; `--turma` sem valor continua no menu interativo.
    """
    return bool(args.turma) or bool(args.matriculados)


def escolher_alunos_compartilhado(args) -> list[dict]:
    """Alunos de turmas.json pelas opções compartilhadas (turma × matriculados × transferidos)."""
    opcoes = opcoes_do_argparse(args)
    with open(TURMAS_JSON, "r", encoding="utf-8") as f:
        turmas = json.load(f)
    try:
        sel = selecionar_alunos(turmas, turmas=opcoes.turmas, matriculados=opcoes.matriculados,
                                transferidos=opcoes.transferidos)
    except ValueError as exc:                      # turma que não existe
        print(f"❌ {exc}")
        sys.exit(1)
    quais = " e ".join(n for n, ligado in (("matriculados", opcoes.matriculados), ("transferidos", opcoes.transferidos)) if ligado)
    onde = ", ".join(sel.turmas) if sel.turmas else "nenhuma turma"
    print(f"✅ {sel.total} aluno(s) — {quais} — em: {onde}")
    print()
    return sel.alunos


def escolher_alunos_por_cgm(args) -> list[dict]:
    """--cgm N [N ...]: mesmo comportamento do --alunos, mas com os CGMs vindos da linha de comando."""
    r = analisar_cgms(" ".join(args.cgm))
    if r.invalidos:
        print(f"❌ CGM com formato inválido: {', '.join(r.invalidos)}")
        sys.exit(1)
    alunos = filtrar_alunos_por_cgm(list(r.validos), ALUNOS_JSON)
    if not alunos:
        print("❌ Nenhum dos CGMs informados foi encontrado.")
        sys.exit(1)
    return alunos


def criar_parser() -> argparse.ArgumentParser:
    """
    Opções da linha de comando. --turma, --matriculados, --transferidos e --cgm são as MESMAS que a
    interface web monta (src/comum/opcoes_execucao.py); as outras são só deste script.
    """
    parser = argparse.ArgumentParser(
        description="Coleta documentos de alunos no SERE e gera relatório Excel."
    )
    parser.add_argument(
        "--erros",
        action="store_true",
        help="Reprocessa somente os alunos que falharam na última execução.",
    )
    parser.add_argument(
        "--rapido",
        action="store_true",
        help="Pula alunos completos; processa só os não-completos via cruzamento-documentos.json.",
    )
    parser.add_argument(
        "--alunos",
        action="store_true",
        help="Processa apenas os CGMs definidos em CGM_ANALISE (no topo do script).",
    )
    parser.add_argument(
        "--todos",
        action="store_true",
        help="Processa TODOS os alunos de turmas.json (matriculados e transferidos).",
    )
    # Compartilhadas com a interface: --turma [NOME ...] (sem valor = menu interativo, como sempre),
    # --matriculados, --transferidos (agora combináveis entre si e com --turma) e --cgm N [N ...].
    adicionar_argumentos(parser, turma=True, situacao=True, cgm=True)
    return parser


async def main():
    args = criar_parser().parse_args()

    gerenciador_erros = GerenciadorErros(ERROS_JSON)

    # ── Decide qual lista de alunos usar ───────────────────────
    if args.todos:
        print("=" * 60)
        print("  MODO TODOS — todos os alunos de turmas.json")
        print("=" * 60)
        alunos = filtrar_alunos_por_situacao(TURMAS_JSON, apenas_transferidos=False)
        if not alunos:
            print("❌ Nenhum aluno encontrado em turmas.json.")
            sys.exit(1)

    elif args.cgm:
        print("=" * 60)
        print("  MODO CGM — CGMs informados na linha de comando")
        print("=" * 60)
        alunos = escolher_alunos_por_cgm(args)

    elif usa_selecao_compartilhada(args):
        print("=" * 60)
        print("  MODO SELEÇÃO — turma(s) e situação informadas")
        print("=" * 60)
        alunos = escolher_alunos_compartilhado(args)
        if not alunos:
            print("❌ Nenhum aluno encontrado com essa seleção.")
            sys.exit(0)

    elif args.transferidos:
        print("=" * 60)
        print("  MODO TRANSFERIDOS — apenas alunos transferidos")
        print("=" * 60)
        alunos = filtrar_alunos_por_situacao(TURMAS_JSON, apenas_transferidos=True)
        if not alunos:
            print("✅ Nenhum aluno transferido encontrado em turmas.json.")
            sys.exit(0)

    elif args.turma is not None:     # --turma sem valor: menu interativo
        print("=" * 60)
        print("  MODO TURMA")
        print("=" * 60)
        alunos = selecionar_turmas_interativo(TURMAS_JSON)
        if not alunos:
            print("✅ Nenhum aluno encontrado nas turmas selecionadas.")
            sys.exit(0)

    elif args.rapido:
        print("=" * 60)
        print("  MODO RÁPIDO — Apenas não-completos (via cruzamento)")
        print("=" * 60)
        alunos = filtrar_alunos_cruzamento(CRUZAMENTO_JSON)
        if not alunos:
            print("✅ Todos os alunos estão completos. Nada a processar.")
            sys.exit(0)

    elif args.alunos:
        print("=" * 60)
        print("  MODO ALUNOS — CGMs específicos")
        print("=" * 60)
        cgms_limpos = [str(c).strip() for c in CGM_ANALISE if str(c).strip()]
        if not cgms_limpos:
            print("❌ CGM_ANALISE está vazio. Edite o array no topo do script.")
            sys.exit(1)
        alunos = filtrar_alunos_por_cgm(cgms_limpos, ALUNOS_JSON)
        if not alunos:
            print("❌ Nenhum dos CGMs informados foi encontrado.")
            sys.exit(1)

    elif args.erros:
        print("=" * 60)
        print("  MODO REPROCESSAMENTO DE ERROS")
        print("=" * 60)
        alunos = gerenciador_erros.carregar_alunos_com_erro()
        if not alunos:
            sys.exit(0)

    else:
        print("=" * 60)
        print("  MODO COMPLETO")
        print("=" * 60)
        with open(ALUNOS_JSON, "r", encoding="utf-8") as f:
            alunos = json.load(f)
        print(f"📋 {len(alunos)} aluno(s) carregados de {ALUNOS_JSON}")

        cgms_transferidos = obter_cgms_transferidos(TURMAS_JSON)
        if cgms_transferidos:
            total_antes = len(alunos)
            alunos = [a for a in alunos if str(a["CGM"]) not in cgms_transferidos]
            print(f"   🚫 Transferidos ignorados          : {total_antes - len(alunos)}")
            print(f"   👥 Total após filtro                : {len(alunos)}")

    # ── Executa coleta ─────────────────────────────────────────
    documentos_data, cgms_ok = await executar(alunos, gerenciador_erros)

    # ── Persiste erros ─────────────────────────────────────────
    gerenciador_erros.salvar()

    if args.erros and cgms_ok:
        gerenciador_erros.limpar_resolvidos(cgms_ok)

    # ── Salva JSON e relatório ─────────────────────────────────
    salvar_documentos(documentos_data, DOCUMENTOS_JSON)

    with open(DOCUMENTOS_JSON, "r", encoding="utf-8") as f:
        todos_os_dados = json.load(f)

    gerar_relatorio(todos_os_dados, RELATORIO_XLSX)

    # ── Resumo ─────────────────────────────────────────────────
    if gerenciador_erros.erros:
        print(f"\n{'=' * 60}")
        print(f"  ⚠️  {len(gerenciador_erros.erros)} ERRO(S) NESTA EXECUÇÃO")
        print(f"  Execute com --erros para reprocessar.")
        print(f"{'=' * 60}")
    else:
        print(f"\n{'=' * 60}")
        print("  ✅ Execução concluída sem erros!")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
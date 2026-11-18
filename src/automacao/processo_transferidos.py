"""
processo_transferidos.py
════════════════════════════════════════════════════════════════════════════
SERE — Processamento de Transferências (v2 — Arquitetura orientada a decisão)
Portado de AUTO_SERE/processo_tranferidos.py para
src/automacao/processo_transferidos.py.

Filosofia (preservada do original):
  1. Analisa os dados do JSON.
  2. Decide o que fazer com base em regras objetivas.
  3. Executa APENAS as ações necessárias no portal.

Regra absoluta de validade de documento:
  Um documento somente é válido se possuir AMBAS as assinaturas:
    • Secretário
    • Diretor
  Sem isso: não baixa, não substitui, não gera — apenas registra em log.

Este é o script que GERA e MANTÉM transferidos.json — o arquivo consumido
por src.automacao.sere_2026.modo_transferidos (já portado) para fazer o
upload de Guia/Histórico/Parecer no SERE. Fecha o ciclo do fluxo de
transferência: processo_transferidos.py emite/assina/baixa os documentos
oficiais e registra o progresso em transferidos.json; modo_transferidos lê
esse mesmo arquivo para saber o que já pode ser anexado na pasta virtual
do aluno.
════════════════════════════════════════════════════════════════════════════

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. CORREÇÃO DE SEGURANÇA (aprovada pelo usuário em 01/09/2026): o original,
   em registrar_pre_corte(), APAGAVA transferidos.json inteiro
   (JSON_TRANSFERIDOS.unlink()) e recriava do zero se qualquer exceção
   ocorresse ao processar o pré-corte — destruindo histórico de
   assinaturas/anexos já registrados de TODOS os alunos, não só do que
   causou o erro. Isso viola a regra fundamental de nunca apagar dados
   automaticamente. Corrigido: em caso de erro, o pré-corte desta execução
   é abortado (nada é persistido), o erro é logado com detalhe, e o
   arquivo existente permanece intocado — quem usa a função decide como
   investigar, em vez do script decidir sozinho apagar tudo.

2. Navegação de menu: _hover_menu()/navegar() (específicos deste arquivo,
   entrando por "Relatórios") portados para
   src.comum.sere_api.navegar_relatorios(page, rota) — decisão do usuário:
   função NOVA e distinta da navegação "Consulta Padrão" já unificada
   (navegar_por_aluno/navegar_por_turma), pois são dois menus de topo
   diferentes do SERE. Reaproveitável por outros scripts que precisem
   navegar em Relatórios.

3. Caminhos: BASE_DIR fixo (servidor Linux) trocado pela arquitetura já
   estabelecida — JSON_TURMAS e JSON_TRANSFERIDOS vêm de
   src.comum.paths.dados_ano_atual() (dados de trabalho); DIR_HISTORICOS e
   DIR_GUIA_TRANSFERENCIA vêm de subpastas dentro de
   src.comum.configuracao.pasta_digitalizacao() (a pasta que o usuário
   escolhe no setup) — mesmo padrão já usado por
   src.automacao.sere_2026.TRANSFERIDOS_SLOTS para as mesmas três pastas.

4. Credenciais: `from credenciais import LOGIN, SENHA` →
   `from src.comum.credenciais import LOGIN, SENHA`.

5. Interface: o menu_selecao() original usava input() para alternar quais
   das 8 etapas rodar. Decisão do usuário (01/09/2026, mesma decisão já
   tomada para os modos de sere_2026.py): preparar cada etapa como função
   pronta para um futuro botão de GUI, sem input() nenhum. ETAPAS (a lista
   de (nome, função) usada pelo menu original) foi preservada como
   referência/ordem canônica; a seleção interativa em si
   (exibir_menu/menu_selecao) foi removida — uma futura GUI decide quais
   etapas rodar chamando processar_transferencias() com o parâmetro
   `etapas`, ou chamando as funções de etapa individualmente. No menu
   lateral isto é a automação "Gerar guia e histórico"
   (src.comum.registro_scripts, chave transferidos_gerar).

ATUALIZAÇÃO (27/10/2026) — fluxo por FILA e DATA_CORTE configurável:
   • Quem processar vem de fila_transferidos.json (gerada pelo turmas.py a
     cada coleta; ver src.automacao.fila_transferidos), não mais de uma
     leitura direta do turmas.json. A DATA_CORTE vem de Configurações
     (src.comum.configuracao.data_corte_transferidos) e vale A PARTIR dela
     (inclusive); antes dela é "pré-corte" (tratado à mão).
   • Histórico e guia são salvos em dados/<ano>/TRANSFERENCIAS/HISTORICO e
     /GUIA DE TRANSFERENCIA (src.comum.pastas_transferencias), as mesmas
     pastas de onde sere_2026.modo_transferidos envia ao SERE.
   • processar_transferencias(simulacao=True) só mostra o plano.

Toda a lógica de negócio (regras de decisão de download/emissão, critério
de validade por dupla assinatura, sincronização SERE↔JSON, comparação de
data para substituição, as 8 etapas e seus seletores) é idêntica ao
original — nenhuma regra foi alterada, exceto o item 1 acima.
"""

from __future__ import annotations

import asyncio
import functools
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from src.comum.credenciais import LOGIN, SENHA
from src.comum import paths as _paths
from src.comum import configuracao as _config
from src.comum import pastas_transferencias as _pastas
from src.comum.sere_api import URL, navegar_relatorios
from src.comum import navegador as _navegador


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════════════════

ANO_ATUAL      = int(_paths.ano_atual())

# Dados de trabalho (turmas.json, transferidos.json) — antes fixos em
# BASE_DIR/"PYTHON/SERE/<ano>/...". Agora via src.comum.paths.dados_ano_atual().
_DADOS = _paths.dados_ano_atual()
JSON_TURMAS       = _DADOS / "turmas.json"
JSON_TRANSFERIDOS = _DADOS / "transferidos.json"

# Pastas de PDFs gerados (histórico, guia) — antes fixas em
# BASE_DIR/"<ano>/TRANSFERENCIAS/...". Agora subpastas da pasta de
# digitalização escolhida pelo usuário no setup (mesmo padrão de
# src.automacao.sere_2026.TRANSFERIDOS_SLOTS). Resolvidas em runtime (não
# como constante de nível de módulo), pois a pasta pode não estar
# configurada ainda no momento em que este módulo é importado — ver
# _dir_historicos() / _dir_guia_transferencia() abaixo.

URL_HISTORICO_PDF = "https://www.sere.pr.gov.br/sere/relHistoricoEscolar.do?action=exibir&codDocumentoAluno={cod}"
URL_GUIA_PDF      = "https://www.sere.pr.gov.br/sere/relGuiaTransferencia.do?action=exibirRelatorioGuiaTransferenciaAlunoVersaoDigital&codDocumentoAluno={cod}"

OBSERVACAO   = ""
DELAY_MIN    = 0.5
DELAY_MAX    = 1.2
JANELA_HORAS = 24
DIAS_ATUAL   = 30          # documento com menos de N dias é considerado "atual"


def _corte() -> datetime:
    """
    DATA_CORTE em vigor (Configurações → data de corte; padrão 22/06 do ano letivo). O processo automático
    começa para quem foi transferido A PARTIR desta data (inclusive); antes dela os documentos são
    considerados já tratados à mão (pré-corte). Lida a cada uso: mudar a data vale na hora.
    """
    d = _config.data_corte_transferidos()
    return datetime(d.year, d.month, d.day)


def _dir_historicos() -> Path:
    """dados/<ano>/TRANSFERENCIAS/HISTORICO (ver src.comum.pastas_transferencias)."""
    return _pastas.subpasta(_pastas.HISTORICO, _DADOS)


def _dir_guia_transferencia() -> Path:
    """dados/<ano>/TRANSFERENCIAS/GUIA DE TRANSFERENCIA (ver src.comum.pastas_transferencias)."""
    return _pastas.subpasta(_pastas.GUIA, _DADOS)


# ══════════════════════════════════════════════════════════════════════════
# DOMÍNIO — tipos e enumerações
# ══════════════════════════════════════════════════════════════════════════

class TipoDoc(str, Enum):
    HISTORICO = "historico"
    GUIA      = "guia"


class AcaoDecidida(Enum):
    BAIXAR           = auto()   # documento válido, baixar
    SUBSTITUIR       = auto()   # documento local inferior, substituir
    GERAR_E_BAIXAR   = auto()   # documento existente, mas desatualizado (>30 dias)
    GERAR_NOVO       = auto()   # nenhum documento válido disponível; gerar
    IGNORAR          = auto()   # sem assinaturas; nada a fazer agora
    JA_EXISTE        = auto()   # arquivo local já é o mais completo; pular


@dataclass
class DocSERE:
    """Documento encontrado na listagem do portal SERE."""
    cod:                 str
    texto:               str
    data:                Optional[datetime]
    assinado_secretario: bool
    assinado_diretor:    bool

    @property
    def valido(self) -> bool:
        """Válido = ambas as assinaturas presentes."""
        return self.assinado_secretario and self.assinado_diretor


@dataclass
class InfoDocJSON:
    """Dados de um documento registrados em transferidos.json."""
    emitido_em:          Optional[datetime]
    assinado_secretario: Optional[datetime]
    assinado_diretor:    Optional[datetime]
    anexado_em:          Optional[datetime]

    @property
    def valido(self) -> bool:
        return bool(self.assinado_secretario and self.assinado_diretor)

    @property
    def dias_desde_emissao(self) -> Optional[int]:
        if self.emitido_em is None:
            return None
        return (datetime.now() - self.emitido_em).days


@dataclass
class Aluno:
    cgm:   str
    nome:  str
    turma: str

    @property
    def e_infantil(self) -> bool:
        return "INFANTIL" in self.turma.upper()


@dataclass
class DecisaoDoc:
    tipo:   TipoDoc
    aluno:  Aluno
    acao:   AcaoDecidida
    motivo: str
    doc_sere: Optional[DocSERE]      = None
    caminho_local: Optional[Path]    = None


# ══════════════════════════════════════════════════════════════════════════
# LOG
# ══════════════════════════════════════════════════════════════════════════

class RotuloLog(str, Enum):
    DOWNLOAD    = "DOWNLOAD"
    SUBSTITUIDO = "SUBSTITUÍDO"
    GERADO      = "GERADO"
    IGNORADO    = "IGNORADO"
    ERRO        = "ERRO"
    INFO        = "INFO"


def log(rotulo: RotuloLog, nome: str, tipo: str, motivo: str) -> None:
    icone = {
        RotuloLog.DOWNLOAD:    "✅",
        RotuloLog.SUBSTITUIDO: "♻️ ",
        RotuloLog.GERADO:      "📄",
        RotuloLog.IGNORADO:    "⏭️ ",
        RotuloLog.ERRO:        "❌",
        RotuloLog.INFO:        "ℹ️ ",
    }.get(rotulo, "  ")
    print(f"  {icone} [{rotulo.value}] {tipo} — {nome}")
    print(f"     Motivo: {motivo}")


# ══════════════════════════════════════════════════════════════════════════
# PERSISTÊNCIA — transferidos.json
# ══════════════════════════════════════════════════════════════════════════

def _agora_str() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _parse_iso(valor: Optional[str]) -> Optional[datetime]:
    if not valor:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, fmt)
        except ValueError:
            continue
    return None


def _parse_data(valor: str) -> Optional[datetime]:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor.strip(), fmt)
        except ValueError:
            continue
    return None


def carregar_json() -> dict:
    if JSON_TRANSFERIDOS.exists():
        with open(JSON_TRANSFERIDOS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def salvar_json(dados: dict) -> None:
    JSON_TRANSFERIDOS.parent.mkdir(parents=True, exist_ok=True)

    def _chave_ordenacao(item: tuple) -> datetime:
        cgm, reg = item
        # Tenta emitido_em da guia, do histórico, ou fallback mínimo
        for doc in ("guia", "historico"):
            dt = _parse_iso(reg.get(doc, {}).get("emitido_em"))
            if dt:
                return dt
        return datetime.min

    dados_ordenados = dict(sorted(dados.items(), key=_chave_ordenacao))

    tmp = JSON_TRANSFERIDOS.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados_ordenados, f, ensure_ascii=False, indent=2)
    tmp.replace(JSON_TRANSFERIDOS)


_CAMPOS_OPCIONAIS = {"baixado_em"}      # aceitos mesmo em registros antigos que ainda não os têm


def _marcar(cgm: str, documento: str, campo: str, valor: Optional[str] = None) -> None:
    dados = carregar_json()
    secao = dados.get(cgm, {}).get(documento)
    if secao is not None and (campo in secao or campo in _CAMPOS_OPCIONAIS):
        secao[campo] = valor if valor is not None else _agora_str()
        salvar_json(dados)


# ── atalhos de marcação ──────────────────────────────────────────────────
def marcar(cgm: str, tipo: TipoDoc, campo: str, valor: Optional[str] = None) -> None:
    _marcar(cgm, tipo.value, campo, valor)


def info_doc_json(cgm: str, tipo: TipoDoc) -> InfoDocJSON:
    reg = carregar_json().get(cgm, {}).get(tipo.value, {})
    return InfoDocJSON(
        emitido_em          = _parse_iso(reg.get("emitido_em")),
        assinado_secretario = _parse_iso(reg.get("assinado_secretario")),
        assinado_diretor    = _parse_iso(reg.get("assinado_diretor")),
        anexado_em          = _parse_iso(reg.get("anexado_em")),
    )


def _registro_vazio(nome: str, turma: str) -> dict:
    _doc = lambda: {
        "emitido_em": None, "assinado_secretario": None,
        "assinado_diretor": None, "anexado_em": None,
    }
    return {
        "nome": nome, "turma": turma,
        "guia": _doc(), "historico": _doc(),
        "parecer": {"digitalizado_em": None, "anexado_em": None},
    }


def _registro_pre_corte(nome: str, turma: str, dt_iso: str) -> dict:
    _doc = lambda: {
        "emitido_em": dt_iso, "assinado_secretario": dt_iso,
        "assinado_diretor": dt_iso, "anexado_em": dt_iso,
    }
    return {
        "nome": nome, "turma": turma,
        "guia": _doc(), "historico": _doc(),
        "parecer": {"digitalizado_em": dt_iso, "anexado_em": dt_iso},
    }


def inicializar_alunos(alunos: list[Aluno]) -> None:
    dados = carregar_json()
    novos = [a for a in alunos if a.cgm not in dados]
    if novos:
        for a in novos:
            dados[a.cgm] = _registro_vazio(a.nome, a.turma)
        salvar_json(dados)
        print(f"  💾 transferidos.json: {len(novos)} novo(s) aluno(s) registrado(s).")


def sincronizar_assinaturas(cgm: str, tipo: TipoDoc, doc: DocSERE) -> None:
    """
    Sincroniza o JSON com o estado real do SERE.
    O SERE é a fonte de verdade: sobrescreve dados desatualizados.
    Registra no log toda divergência detectada e corrigida.
    """
    dados = carregar_json()
    secao = dados.get(cgm, {}).get(tipo.value)
    if secao is None:
        return

    dt = doc.data.strftime("%Y-%m-%dT%H:%M:%S") if doc.data else _agora_str()
    alterou = False
    divergencias: list[str] = []

    def _sincronizar_campo(campo: str, valor_sere: str, condicao_sere: bool) -> bool:
        """
        Atualiza o campo se o SERE indicar que deve estar preenchido
        e o JSON estiver vazio OU desatualizado.
        """
        valor_json = secao.get(campo)
        if condicao_sere and valor_json is None:
            secao[campo] = valor_sere
            divergencias.append(f"{campo}: JSON=None → SERE={valor_sere[:10]}")
            return True
        return False

    alterou |= _sincronizar_campo("emitido_em", dt, True)
    alterou |= _sincronizar_campo("assinado_secretario", dt, doc.assinado_secretario)
    alterou |= _sincronizar_campo("assinado_diretor", dt, doc.assinado_diretor)

    if alterou:
        salvar_json(dados)
        doc_nome = tipo.value.capitalize()
        print(f"  🔄 [SINCRONIZAÇÃO] {doc_nome} (CGM {cgm}): {' | '.join(divergencias)}")


def aluno_completo(cgm: str) -> bool:
    dados = carregar_json().get(cgm, {})
    return all(
        dados.get(t, {}).get(c)
        for t in ("guia", "historico")
        for c in ("emitido_em", "assinado_secretario", "assinado_diretor")
    )


# ══════════════════════════════════════════════════════════════════════════
# PRÉ-CORTE
# ══════════════════════════════════════════════════════════════════════════

def registrar_pre_corte() -> int:
    """
    Para alunos já Transferidos ANTES da DATA_CORTE,
    registra (ou completa) um registro "pré-preenchido" em transferidos.json
    — considerando que documentos desse período já foram tratados
    manualmente antes da existência deste fluxo automatizado.

    CORREÇÃO DE SEGURANÇA (aprovada pelo usuário em 01/09/2026): o original
    apagava transferidos.json inteiro (JSON_TRANSFERIDOS.unlink()) e
    recriava do zero se qualquer exceção ocorresse ao processar o
    pré-corte. Isso destruiria o histórico de TODOS os alunos por causa de
    um erro pontual — viola a regra de nunca apagar dados automaticamente.
    Agora: se ocorrer um erro, nada é persistido (o transferidos.json
    existente permanece exatamente como estava), o erro é logado com
    detalhe para investigação manual, e a função retorna 0 sem alterar o
    arquivo.
    """
    if not JSON_TURMAS.exists():
        print(f"  ⚠️  {JSON_TURMAS} não encontrado — pulando pré-corte.")
        return 0
    corte = _corte()

    with open(JSON_TURMAS, encoding="utf-8") as f:
        dados_turmas = json.load(f)

    dados_transf = carregar_json()

    def _processar_turmas(dados_transf: dict) -> int:
        adicionados = 0
        for turma, alunos in dados_turmas.items():
            for aluno in alunos:
                if aluno.get("Situação", "").strip() != "Transferido":
                    continue
                data = _parse_data(aluno.get("Data Matricula", ""))
                if data is None or data >= corte:          # a partir da DATA_CORTE é processo novo
                    continue
                cgm = str(aluno.get("CGM", "")).strip()
                if not cgm:
                    continue

                dt_iso = data.strftime("%Y-%m-%dT%H:%M:%S")
                if cgm not in dados_transf:
                    dados_transf[cgm] = _registro_pre_corte(
                        nome=aluno.get("Nome", "").strip(),
                        turma=turma.strip(),
                        dt_iso=dt_iso,
                    )
                    adicionados += 1
                else:
                    reg   = dados_transf[cgm]
                    d_reg = _parse_data(reg.get("data_transferencia") or "")
                    if d_reg is not None and d_reg >= corte:
                        continue     # o registro é de uma saída DEPOIS do corte; esta linha é de uma saída anterior
                    mudou = False
                    for doc in ("guia", "historico"):
                        for campo in ("emitido_em", "assinado_secretario", "assinado_diretor", "anexado_em"):
                            if reg.get(doc, {}).get(campo) is None:
                                reg[doc][campo] = dt_iso
                                mudou = True
                    for campo in ("digitalizado_em", "anexado_em"):
                        if reg.get("parecer", {}).get(campo) is None:
                            reg["parecer"][campo] = dt_iso
                            mudou = True
                    if mudou:
                        adicionados += 1
        return adicionados

    try:
        adicionados = _processar_turmas(dados_transf)
    except Exception as e:
        print(f"  ❌ Erro no pré-corte: {e}")
        print(f"  ⚠️  Pré-corte ABORTADO — nenhuma alteração foi salva.")
        print(f"      {JSON_TRANSFERIDOS} permanece intocado. Investigue o erro acima antes de tentar novamente.")
        return 0

    if adicionados:
        salvar_json(dados_transf)

    print(f"  📋 Pré-corte: {adicionados} aluno(s) registrado(s)/atualizados.")
    return adicionados


# ══════════════════════════════════════════════════════════════════════════
# CARREGAMENTO DE ALUNOS
# ══════════════════════════════════════════════════════════════════════════

def carregar_alunos(gravar_fila: bool = True) -> list[Aluno]:
    """
    Alunos a processar = os da fila_transferidos.json marcados "processar" (transferidos a partir da
    DATA_CORTE) que ainda não têm guia + histórico completos em transferidos.json. A fila é gerada a partir
    do turmas.json se ainda não existe (ver src.automacao.fila_transferidos). Quem foi transferido mas já
    voltou à escola não entra (o processo é feito uma vez só).
    """
    from src.automacao.fila_transferidos import alunos_a_processar, garantir_fila

    fila = garantir_fila(_DADOS, gravar=gravar_fila)          # FileNotFoundError se faltar o turmas.json
    alunos:  list[Aluno] = []
    completos = 0

    for a in alunos_a_processar(fila):
        if a["cgm"] and aluno_completo(a["cgm"]):
            completos += 1
            continue
        alunos.append(Aluno(cgm=a["cgm"], nome=a["nome"], turma=a["turma"]))

    print(f"📋 {len(alunos)} aluno(s) a processar (transferidos a partir de {fila['data_corte']}).")
    if completos:
        print(f"⏭️  {completos} aluno(s) já completo(s) (guia+histórico) — ignorado(s).")
    retornados = fila.get("resumo", {}).get("retornaram_sem_processar", 0)
    if retornados:
        print(f"⏭️  {retornados} aluno(s) transferido(s) que já voltou(aram) à escola — não entram (processo feito uma vez só).")
    return alunos


# ══════════════════════════════════════════════════════════════════════════
# MOTOR DE DECISÃO
# ══════════════════════════════════════════════════════════════════════════

TOLERANCIA_EMISSAO = timedelta(hours=2)   # diferença máxima entre o emitido_em registrado e o "gerado em" do SERE


def docs_da_escola(docs_sere: list[DocSERE], emitido_em: Optional[datetime],
                   corte: Optional[datetime] = None) -> list[DocSERE]:
    """
    Dos documentos que o SERE lista para o aluno, só os que ESTA escola emitiu nesta transferência.

    A listagem do SERE mostra também documentos de transferência de outras escolas. Um documento é
    considerado nosso quando (1) foi gerado depois da DATA_CORTE e (2) a data/hora "gerado em" bate com
    o `emitido_em` que o próprio processo registrou em transferidos.json ao emitir (mesmo dia, ou até
    2 h de diferença, por causa da virada do dia). Sem `emitido_em` registrado, nenhum documento é
    nosso: faz-se o processo completo (emitir, assinar, baixar). Mais próximo do registro primeiro.
    """
    if emitido_em is None:
        return []
    corte = corte or _corte()
    nossos = [d for d in docs_sere
              if d.data and d.data > corte
              and (d.data.date() == emitido_em.date() or abs(d.data - emitido_em) <= TOLERANCIA_EMISSAO)]
    return sorted(nossos, key=lambda d: abs(d.data - emitido_em))


def _nota_outros(docs_sere: list[DocSERE], nossos: list[DocSERE]) -> str:
    outros = len(docs_sere) - len(nossos)
    return f" ({outros} documento(s) de outra origem ou sem registro de emissão ignorado(s))" if outros > 0 else ""


MSG_SEM_DOC_DA_ESCOLA = "Nenhum documento emitido por esta escola nesta transferência (emita antes)."


def decidir_acao_download(
    aluno:        Aluno,
    tipo:         TipoDoc,
    docs_sere:    list[DocSERE],
    caminho_base: Path,
    info:         Optional[InfoDocJSON] = None,
) -> DecisaoDoc:
    """
    Analisa os dados disponíveis e retorna uma DecisaoDoc com a ação a executar.

    Regra absoluta: documento inválido (sem ambas assinaturas) → IGNORAR.
    Regras de data (só se válido):
      - < DIAS_ATUAL dias → BAIXAR (ou JA_EXISTE se arquivo local idêntico/melhor)
      - ≥ DIAS_ATUAL dias → GERAR_E_BAIXAR (pode estar desatualizado)
    Estratégia de substituição:
      - Se arquivo local existir, comparar; substituir se versão do SERE for melhor.
    """
    nome_arquivo = f"{aluno.nome}.pdf"
    pasta        = caminho_base / aluno.turma
    caminho_pdf  = pasta / nome_arquivo

    # Só considera documentos do ciclo de transferência atual (emitidos após
    # DATA_CORTE). Um histórico válido, porém de um ciclo/ano anterior, não
    # deve ser reaproveitado — precisa gerar um novo para o ano corrente.
    # Além do ciclo atual, só vale o documento que ESTA escola emitiu (ver docs_da_escola): a listagem
    # traz também documentos de outras escolas, que não devem ser baixados como se fossem nossos.
    if info is None:
        info = info_doc_json(aluno.cgm, tipo)
    docs_ciclo_atual = docs_da_escola(docs_sere, info.emitido_em)

    doc_valido = next((d for d in docs_ciclo_atual if d.valido), None)

    # ── Regra absoluta ──────────────────────────────────────────────────
    if doc_valido is None:
        # verifica se há ao menos doc parcial para informar status
        doc_parcial = docs_ciclo_atual[0] if docs_ciclo_atual else None
        if doc_parcial:
            falta = []
            if not doc_parcial.assinado_secretario:
                falta.append("Secretário")
            if not doc_parcial.assinado_diretor:
                falta.append("Diretor")
            motivo = f"Ausência de assinatura obrigatória: {', '.join(falta)}."
        else:
            motivo = (MSG_SEM_DOC_DA_ESCOLA if docs_sere else "Nenhum documento encontrado no portal.") \
                     + _nota_outros(docs_sere, docs_ciclo_atual)
        return DecisaoDoc(tipo=tipo, aluno=aluno, acao=AcaoDecidida.IGNORAR, motivo=motivo)

    # ── Arquivo local existente? ─────────────────────────────────────────
    if caminho_pdf.exists():
        data_local = datetime.fromtimestamp(caminho_pdf.stat().st_mtime)

        # Se o doc do SERE é mais recente que o arquivo local → substituir
        if doc_valido.data and doc_valido.data > data_local:
            return DecisaoDoc(
                tipo=tipo, aluno=aluno, acao=AcaoDecidida.SUBSTITUIR,
                motivo="Versão mais recente encontrada no portal.",
                doc_sere=doc_valido, caminho_local=caminho_pdf,
            )

        # Se o doc tem mais de DIAS_ATUAL dias → pode gerar versão nova
        if doc_valido.data and (datetime.now() - doc_valido.data).days >= DIAS_ATUAL:
            return DecisaoDoc(
                tipo=tipo, aluno=aluno, acao=AcaoDecidida.GERAR_E_BAIXAR,
                motivo=f"Documento emitido há mais de {DIAS_ATUAL} dias — regenerar.",
                doc_sere=doc_valido, caminho_local=caminho_pdf,
            )

        # Arquivo local já é o mais completo
        return DecisaoDoc(
            tipo=tipo, aluno=aluno, acao=AcaoDecidida.JA_EXISTE,
            motivo="Arquivo local está atualizado.",
            doc_sere=doc_valido, caminho_local=caminho_pdf,
        )

    # ── Sem arquivo local ────────────────────────────────────────────────
    return DecisaoDoc(
        tipo=tipo, aluno=aluno, acao=AcaoDecidida.BAIXAR,
        motivo="Documento válido e sem arquivo local.",
        doc_sere=doc_valido, caminho_local=caminho_pdf,
    )


def decidir_acao_emissao(
    aluno:     Aluno,
    tipo:      TipoDoc,
    docs_sere: list[DocSERE],
    info:      Optional[InfoDocJSON] = None,
) -> tuple[AcaoDecidida, Optional[DocSERE], str]:
    """
    Decide o que fazer na etapa de emissão, olhando só os documentos que ESTA escola emitiu nesta
    transferência (ver docs_da_escola). Documento de outra escola não conta: se não há nenhum nosso, gera.
      - nosso e válido (2 assinaturas)         → JA_EXISTE (não sobrescreve)
      - nosso, sem assinatura do Secretário    → BAIXAR (só assinar; NÃO gera outro)
      - nosso, falta só o Diretor              → JA_EXISTE (aguardando; NÃO gera outro a cada execução)
      - nenhum nosso                           → GERAR_NOVO
    Retorna (ação, doc_relevante, motivo).
    """
    agora = datetime.now()
    if info is None:
        info = info_doc_json(aluno.cgm, tipo)
    nossos = docs_da_escola(docs_sere, info.emitido_em)
    nota = _nota_outros(docs_sere, nossos)

    doc_valido = next((d for d in nossos if d.valido), None)
    if doc_valido:
        if doc_valido.data and (agora - doc_valido.data).total_seconds() <= JANELA_HORAS * 3600:
            return AcaoDecidida.JA_EXISTE, doc_valido, f"Documento válido e recente (cod: {doc_valido.cod}).{nota}"
        return AcaoDecidida.JA_EXISTE, doc_valido, f"Documento válido (cod: {doc_valido.cod}) — utilizando.{nota}"

    doc_sem_sec = next((d for d in nossos if not d.assinado_secretario), None)
    if doc_sem_sec:
        return AcaoDecidida.BAIXAR, doc_sem_sec, f"Doc não assinado encontrado (cod: {doc_sem_sec.cod}) — assinar.{nota}"

    doc_aguardando = next((d for d in nossos if d.assinado_secretario and not d.assinado_diretor), None)
    if doc_aguardando:
        return (AcaoDecidida.JA_EXISTE, doc_aguardando,
                f"Documento desta escola (cod: {doc_aguardando.cod}) aguardando a assinatura do Diretor — não gera outro.{nota}")

    return AcaoDecidida.GERAR_NOVO, None, f"Nenhum documento desta escola encontrado — gerar.{nota}"


# ══════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS PLAYWRIGHT
# ══════════════════════════════════════════════════════════════════════════

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

_JS_INSPECIONAR = """() => {
    const docs = [];
    document.querySelectorAll('input[value="Exibir"]').forEach(btn => {
        const td = btn.closest('td');
        if (!td) return;
        const onclick = btn.getAttribute('onclick') || '';
        const mCod = onclick.match(/\\d+/);
        if (!mCod) return;
        const hidSec = td.querySelector('input[id="assinadoSecretario"]');
        const hidDir = td.querySelector('input[id="assinadoDiretor"]');
        docs.push({
            cod:        mCod[0],
            texto:      td.innerText.trim(),
            assinadoSec: hidSec ? hidSec.value === 'S' : false,
            assinadoDir: hidDir ? hidDir.value === 'S' : false,
        });
    });
    return docs;
}"""

# GET simples — usado pelo Histórico Escolar
_JS_FETCH_PDF_GET = """async (url) => {
    const r = await fetch(url, {credentials: 'include'});
    const buf = await r.arrayBuffer();
    return Array.from(new Uint8Array(buf));
}"""

# POST via form — usado pela Guia de Transferência
_JS_FETCH_PDF_POST = """async (url) => {
    const form = document.querySelector('form[name="relGuiaTransferenciaForm"]');
    const formData = new FormData(form);
    const r = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        body: formData,
    });
    const buf = await r.arrayBuffer();
    return Array.from(new Uint8Array(buf));
}"""

# Alias para compatibilidade (histórico usa GET)
_JS_FETCH_PDF = _JS_FETCH_PDF_GET


async def delay() -> None:
    await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


async def inspecionar_documentos(page) -> list[DocSERE]:
    resultado = await page.evaluate(_JS_INSPECIONAR)
    docs: list[DocSERE] = []
    for item in resultado:
        m = re.search(
            r"gerado em (\d{1,2}) de (\w+) de (\d{4}) às (\d{2}):(\d{2})",
            item["texto"], re.IGNORECASE,
        )
        data = None
        if m:
            dia, mes_str, ano, hora, minuto = m.groups()
            mes = MESES_PT.get(mes_str.lower())
            if mes:
                data = datetime(int(ano), mes, int(dia), int(hora), int(minuto))
        docs.append(DocSERE(
            cod                 = item["cod"],
            texto               = item["texto"],
            data                = data,
            assinado_secretario = item["assinadoSec"],
            assinado_diretor    = item["assinadoDir"],
        ))
    docs.sort(key=lambda d: d.data or datetime.min, reverse=True)
    return docs


async def baixar_pdf(page, url: str, caminho: Path, method: str = "GET") -> None:
    js = _JS_FETCH_PDF_POST if method == "POST" else _JS_FETCH_PDF_GET
    pdf_bytes = await page.evaluate(js, url)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(bytes(pdf_bytes))


async def assinar_como_secretario(page, cod: str) -> bool:
    """Clica em 'Assinar como Secretário' para o cod fornecido. Retorna True se bem-sucedido."""
    btn = page.locator('input[value="Assinar como Secretário"]').first
    try:
        await btn.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        return False
    if await btn.is_disabled():
        return True  # já assinado
    await btn.click()
    await delay()
    try:
        await page.wait_for_function(
            f"""() => {{
                const btns = document.querySelectorAll('input[value="Assinar como Secretário"]');
                for (const b of btns) {{
                    if (b.getAttribute('onclick')?.includes('{cod}')) return b.disabled;
                }}
                return false;
            }}""",
            timeout=10000,
        )
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════
# NAVEGAÇÃO
# ══════════════════════════════════════════════════════════════════════════
# _hover_menu()/navegar() do original foram substituídas por
# src.comum.sere_api.navegar_relatorios(page, rota) — ver decisão do
# usuário no docstring do módulo.

_ROTA_HISTORICO_GRAVAR   = ("Histórico Escolar", "Gravar Matrículas no Histórico")
_ROTA_HISTORICO_ALTERAR  = ("Histórico Escolar", "Alterar/Excluir")
_ROTA_HISTORICO_EMITIR   = ("Histórico Escolar", "Emitir")
_ROTA_GUIA               = ("Documentos Oficiais", "Guia de Transferência")


async def navegar_historico_gravar(page)  -> None: await navegar_relatorios(page, _ROTA_HISTORICO_GRAVAR)
async def navegar_historico_alterar(page) -> None: await navegar_relatorios(page, _ROTA_HISTORICO_ALTERAR)
async def navegar_historico_emitir(page)  -> None: await navegar_relatorios(page, _ROTA_HISTORICO_EMITIR)
async def navegar_guia(page)              -> None: await navegar_relatorios(page, _ROTA_GUIA)


def _locator_nivel_historico(page, aluno: Aluno):
    if aluno.e_infantil:
        return page.locator('a:has-text("Educação Infantil")')
    return page.locator('a:has-text("Ensino Fundamental - 9 Anos")')


def _locator_tipo_guia(page, aluno: Aluno):
    if aluno.e_infantil:
        return page.locator('a:has-text("EDUC INFANTIL INTEGRAL")')
    return page.locator('a:has-text("ENS FUND 1/5 A/S - TEMPO INTEGRAL")')


# ══════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════

async def login(page) -> None:
    print("🔐 Fazendo login...")
    await page.goto(URL)
    await page.wait_for_load_state("networkidle")
    await page.fill("#CHAVE", LOGIN)
    await page.fill("#CHAVE_ENCRIPT", SENHA)
    await page.click("//input[@value='Entrar']")
    await page.wait_for_load_state("networkidle")
    print("✅ Login realizado.")


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 1 — Gravar Matrículas
# ══════════════════════════════════════════════════════════════════════════

async def gravar_matriculas(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 1 — GRAVAR MATRÍCULAS")
    await navegar_historico_gravar(page)

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm}")
        try:
            await page.locator('input[name="cgm"]').fill(aluno.cgm)
            await delay()
            await page.click('input[name="pesquisar"]')
            await page.wait_for_load_state("networkidle")
            await delay()

            btn = page.locator('input[name="confirmar"]')
            await btn.wait_for(state="visible", timeout=10000)
            await btn.click()
            await delay()

            btn_sim = page.locator('input[value="Sim"]')
            await btn_sim.wait_for(state="visible", timeout=10000)
            await btn_sim.click()
            await page.wait_for_load_state("networkidle")
            await delay()

            log(RotuloLog.INFO, aluno.nome, "Matrícula", "Gravada com sucesso.")

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Matrícula", f"TIMEOUT: {e}")
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Matrícula", str(e))


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 2 — Alterar/Excluir (adicionar observação)
# ══════════════════════════════════════════════════════════════════════════

async def alterar_historico(page, alunos: list[Aluno], observacao: Optional[str] = None) -> None:
    """`observacao`: texto a gravar em cada histórico (da tela); None usa a constante OBSERVACAO."""
    texto_obs = OBSERVACAO if observacao is None else observacao
    _cabecalho("ETAPA 2 — ALTERAR/EXCLUIR HISTÓRICO")
    print(f"  📝 Texto da observação: {texto_obs!r}" if texto_obs.strip() else "  ⚠️  Texto da observação vazio.")

    async def handle_dialog(dialog):
        await dialog.accept()

    page.on("dialog", handle_dialog)
    await navegar_historico_alterar(page)

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await page.locator('input[name="cgm"]').fill(aluno.cgm)
            await delay()
            await page.click('input[name="pesquisar"]')
            await page.wait_for_load_state("networkidle")
            await delay()

            link = _locator_nivel_historico(page, aluno)
            await link.wait_for(state="visible", timeout=10000)
            await link.click()
            await page.wait_for_load_state("networkidle")
            await delay()

            txt = page.locator('textarea[name="observacao"]')
            await txt.wait_for(state="visible", timeout=10000)
            await txt.fill(texto_obs)
            await delay()

            await page.click('input[name="salvar"]')
            await page.wait_for_load_state("networkidle")
            await delay()
            await page.evaluate("aoClicarVoltar()")
            await page.wait_for_load_state("networkidle")
            await delay()

            log(RotuloLog.INFO, aluno.nome, "Histórico", "Observação salva.")

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Histórico", f"TIMEOUT: {e}")
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Histórico", str(e))

    page.remove_listener("dialog", handle_dialog)


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 3 — Emitir/Gerar Histórico
# ══════════════════════════════════════════════════════════════════════════

async def gerar_historico(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 3 — EMITIR/GERAR HISTÓRICO")
    await navegar_historico_emitir(page)

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await _pesquisar_cgm(page, aluno.cgm)

            link = _locator_nivel_historico(page, aluno)
            await link.wait_for(state="visible", timeout=10000)
            await link.click()
            await page.wait_for_load_state("networkidle")
            await delay()

            docs  = await inspecionar_documentos(page)
            acao, doc_ref, motivo = decidir_acao_emissao(aluno, TipoDoc.HISTORICO, docs)

            if doc_ref:
                sincronizar_assinaturas(aluno.cgm, TipoDoc.HISTORICO, doc_ref)

            if acao != AcaoDecidida.GERAR_NOVO:          # já há documento desta escola: só falta assinar/baixar
                log(RotuloLog.IGNORADO, aluno.nome, "Histórico Escolar", motivo)
            else:
                # Registra ANTES de clicar: se o programa cair depois do clique, o documento gerado continua
                # sendo reconhecido como nosso (ver docs_da_escola) em vez de gerar outro na próxima execução.
                marcar(aluno.cgm, TipoDoc.HISTORICO, "emitido_em")
                await page.click('input[name="btnImprimirFrente"]')
                await page.wait_for_load_state("networkidle")
                await delay()
                log(RotuloLog.GERADO, aluno.nome, "Histórico Escolar", "Documento gerado com sucesso.")

            await navegar_historico_emitir(page)

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Histórico", f"TIMEOUT: {e}")
            await _safe_nav(page, navegar_historico_emitir)
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Histórico", str(e))
            await _safe_nav(page, navegar_historico_emitir)


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 4 — Assinar Históricos
# ══════════════════════════════════════════════════════════════════════════

async def assinar_historico(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 4 — ASSINAR HISTÓRICOS")
    await navegar_historico_emitir(page)

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await _pesquisar_cgm(page, aluno.cgm)

            link = _locator_nivel_historico(page, aluno)
            await link.wait_for(state="visible", timeout=10000)
            await link.click()
            await page.wait_for_load_state("networkidle")
            await delay()

            # só documentos que ESTA escola emitiu (a listagem traz também os de outras escolas)
            emissao = info_doc_json(aluno.cgm, TipoDoc.HISTORICO).emitido_em
            docs = docs_da_escola(await inspecionar_documentos(page), emissao)
            if not docs:
                log(RotuloLog.IGNORADO, aluno.nome, "Histórico Escolar", MSG_SEM_DOC_DA_ESCOLA)
                await navegar_historico_emitir(page)
                continue
            sincronizar_assinaturas(aluno.cgm, TipoDoc.HISTORICO, docs[0])

            doc_a_assinar = next((d for d in docs if not d.assinado_secretario), None)

            if doc_a_assinar is None:
                log(RotuloLog.INFO, aluno.nome, "Histórico Escolar", "Já assinado como Secretário.")
            else:
                ok = await assinar_como_secretario(page, doc_a_assinar.cod)
                if ok:
                    marcar(aluno.cgm, TipoDoc.HISTORICO, "assinado_secretario")
                    log(RotuloLog.INFO, aluno.nome, "Histórico Escolar",
                        f"Assinado como Secretário (cod: {doc_a_assinar.cod}).")
                else:
                    log(RotuloLog.ERRO, aluno.nome, "Histórico Escolar",
                        "Não foi possível assinar como Secretário.")

            # re-inspeciona para capturar estado do Diretor
            docs = docs_da_escola(await inspecionar_documentos(page), emissao)
            if docs:
                sincronizar_assinaturas(aluno.cgm, TipoDoc.HISTORICO, docs[0])
                if docs[0].assinado_diretor:
                    marcar(aluno.cgm, TipoDoc.HISTORICO, "assinado_diretor")
                    log(RotuloLog.INFO, aluno.nome, "Histórico Escolar",
                        "Também assinado pelo Diretor.")
                else:
                    log(RotuloLog.INFO, aluno.nome, "Histórico Escolar",
                        "Pendente de assinatura do Diretor.")

            await navegar_historico_emitir(page)

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Histórico", f"TIMEOUT: {e}")
            await _safe_nav(page, navegar_historico_emitir)
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Histórico", str(e))
            await _safe_nav(page, navegar_historico_emitir)


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 5 — Imprimir Históricos (baixar PDF)
# ══════════════════════════════════════════════════════════════════════════

async def imprimir_historicos(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 5 — IMPRIMIR HISTÓRICOS (PDF)")
    await navegar_historico_emitir(page)
    dir_historicos = _dir_historicos()
    if dir_historicos is None:
        print("  ⚠️  Pasta de digitalização não configurada — pulando etapa.")
        return
    await _processar_download_lote(page, alunos, TipoDoc.HISTORICO,
                                   dir_historicos, URL_HISTORICO_PDF,
                                   navegar_historico_emitir,
                                   _locator_nivel_historico)


# ══════════════════════════════════════════════════════════════════════════
# NAVEGAÇÃO ATÉ OS DOCUMENTOS DA GUIA (compartilhada pelas etapas 6/7/8)
# ══════════════════════════════════════════════════════════════════════════

async def _navegar_ate_documentos_guia(page, aluno: Aluno) -> None:
    """
    A partir da tela de pesquisa por CGM já carregada, navega até a lista de
    documentos da Guia de Transferência do aluno.

    Lida com os dois formatos possíveis de retorno do portal:
      • Matrícula única: o link do tipo de curso já é o próprio
        `buscarMatricula` — clicar direto, sem passar pelo intermediário,
        já que nesse caso o link intermediário nunca fica visível.
      • Matrícula múltipla: primeiro seleciona a matrícula, depois o
        tipo de curso na tabela que aparece em seguida.
    """
    link_tipo = _locator_tipo_guia(page, aluno)
    tipo_ja_visivel = await link_tipo.count() > 0

    if tipo_ja_visivel:
        await link_tipo.wait_for(state="visible", timeout=10000)
        await link_tipo.click()
    else:
        link_matricula = page.locator('a[onclick*="buscarMatricula"]').first
        try:
            await link_matricula.wait_for(state="visible", timeout=10000)
            await link_matricula.click()
        except PlaywrightTimeoutError:
            link_existe = await page.evaluate(
                "() => document.querySelectorAll('a[onclick*=\"buscarMatricula\"]').length"
            )
            if link_existe == 0:
                raise Exception("Tabela de matrículas não carregou.")
            await page.evaluate("buscarMatricula(1)")

        await page.wait_for_load_state("networkidle")
        await delay()

        link_tipo = _locator_tipo_guia(page, aluno)
        await link_tipo.wait_for(state="visible", timeout=10000)
        await link_tipo.click()

    await page.wait_for_load_state("networkidle")
    await delay()


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 6 — Emitir/Gerar Guia de Transferência
# ══════════════════════════════════════════════════════════════════════════

async def gerar_guia(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 6 — EMITIR/GERAR GUIA DE TRANSFERÊNCIA")
    await navegar_guia(page)

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await _pesquisar_cgm_guia(page, aluno.cgm)
            await _navegar_ate_documentos_guia(page, aluno)

            docs = await inspecionar_documentos(page)
            acao, doc_ref, motivo = decidir_acao_emissao(aluno, TipoDoc.GUIA, docs)

            if doc_ref:
                sincronizar_assinaturas(aluno.cgm, TipoDoc.GUIA, doc_ref)

            if acao != AcaoDecidida.GERAR_NOVO:          # já há documento desta escola: só falta assinar/baixar
                log(RotuloLog.IGNORADO, aluno.nome, "Guia de Transferência", motivo)
            else:
                marcar(aluno.cgm, TipoDoc.GUIA, "emitido_em")          # antes do clique (ver o histórico acima)
                await page.click('input[value="Gerar Documento"]')
                await page.wait_for_load_state("networkidle")
                await delay()
                log(RotuloLog.GERADO, aluno.nome, "Guia de Transferência", "Documento gerado com sucesso.")

            await navegar_guia(page)

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência", f"TIMEOUT: {e}")
            await _safe_nav(page, navegar_guia)
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência", str(e))
            await _safe_nav(page, navegar_guia)


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 7 — Assinar Guias
# ══════════════════════════════════════════════════════════════════════════

async def assinar_guia(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 7 — ASSINAR GUIAS")
    await navegar_guia(page)

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await _pesquisar_cgm_guia(page, aluno.cgm)
            await _navegar_ate_documentos_guia(page, aluno)

            # só documentos que ESTA escola emitiu (a listagem traz também os de outras escolas)
            emissao = info_doc_json(aluno.cgm, TipoDoc.GUIA).emitido_em
            docs = docs_da_escola(await inspecionar_documentos(page), emissao)
            if not docs:
                log(RotuloLog.IGNORADO, aluno.nome, "Guia de Transferência", MSG_SEM_DOC_DA_ESCOLA)
                await navegar_guia(page)
                continue
            sincronizar_assinaturas(aluno.cgm, TipoDoc.GUIA, docs[0])

            doc_a_assinar = next((d for d in docs if not d.assinado_secretario), None)

            if doc_a_assinar is None:
                log(RotuloLog.INFO, aluno.nome, "Guia de Transferência", "Já assinada como Secretário.")
            else:
                ok = await assinar_como_secretario(page, doc_a_assinar.cod)
                if ok:
                    marcar(aluno.cgm, TipoDoc.GUIA, "assinado_secretario")
                    log(RotuloLog.INFO, aluno.nome, "Guia de Transferência",
                        f"Assinada como Secretário (cod: {doc_a_assinar.cod}).")
                else:
                    log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência",
                        "Não foi possível assinar como Secretário.")

            # re-inspeciona para capturar estado do Diretor
            docs = docs_da_escola(await inspecionar_documentos(page), emissao)
            if docs:
                sincronizar_assinaturas(aluno.cgm, TipoDoc.GUIA, docs[0])
                if docs[0].assinado_diretor:
                    marcar(aluno.cgm, TipoDoc.GUIA, "assinado_diretor")
                    log(RotuloLog.INFO, aluno.nome, "Guia de Transferência",
                        "Também assinada pelo Diretor.")
                else:
                    log(RotuloLog.INFO, aluno.nome, "Guia de Transferência",
                        "Pendente de assinatura do Diretor.")

            await navegar_guia(page)

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência", f"TIMEOUT: {e}")
            await _safe_nav(page, navegar_guia)
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência", str(e))
            await _safe_nav(page, navegar_guia)


# ══════════════════════════════════════════════════════════════════════════
# ETAPA 8 — Imprimir Guias (baixar PDF)
# ══════════════════════════════════════════════════════════════════════════

async def imprimir_guias(page, alunos: list[Aluno]) -> None:
    _cabecalho("ETAPA 8 — IMPRIMIR GUIAS (PDF)")
    await navegar_guia(page)
    dir_guia = _dir_guia_transferencia()
    if dir_guia is None:
        print("  ⚠️  Pasta de digitalização não configurada — pulando etapa.")
        return

    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await _pesquisar_cgm_guia(page, aluno.cgm)
            await _navegar_ate_documentos_guia(page, aluno)

            docs = await inspecionar_documentos(page)
            info = info_doc_json(aluno.cgm, TipoDoc.GUIA)
            nossos = docs_da_escola(docs, info.emitido_em)
            if nossos:
                sincronizar_assinaturas(aluno.cgm, TipoDoc.GUIA, nossos[0])

            decisao = decidir_acao_download(aluno, TipoDoc.GUIA, docs, dir_guia, info)
            await _executar_download(page, aluno, TipoDoc.GUIA, decisao, URL_GUIA_PDF)

            await navegar_guia(page)

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência", f"TIMEOUT: {e}")
            await _safe_nav(page, navegar_guia)
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, "Guia de Transferência", str(e))
            await _safe_nav(page, navegar_guia)


# ══════════════════════════════════════════════════════════════════════════
# NÚCLEO GENÉRICO — download em lote (reutilizável para Histórico e Guia)
# ══════════════════════════════════════════════════════════════════════════

async def _processar_download_lote(
    page,
    alunos:         list[Aluno],
    tipo:           TipoDoc,
    dir_base:       Path,
    url_template:   str,
    fn_navegar,
    fn_locator_link,
) -> None:
    for aluno in alunos:
        print(f"\n  👤 {aluno.nome} | CGM: {aluno.cgm} | Turma: {aluno.turma}")
        try:
            await _pesquisar_cgm(page, aluno.cgm)

            link = fn_locator_link(page, aluno)
            await link.wait_for(state="visible", timeout=10000)
            await link.click()
            await page.wait_for_load_state("networkidle")
            await delay()

            docs = await inspecionar_documentos(page)
            info = info_doc_json(aluno.cgm, tipo)
            nossos = docs_da_escola(docs, info.emitido_em)
            if nossos:
                sincronizar_assinaturas(aluno.cgm, tipo, nossos[0])

            decisao = decidir_acao_download(aluno, tipo, docs, dir_base, info)
            await _executar_download(page, aluno, tipo, decisao, url_template)

            await fn_navegar(page)

        except PlaywrightTimeoutError as e:
            log(RotuloLog.ERRO, aluno.nome, tipo.value, f"TIMEOUT: {e}")
            await _safe_nav(page, fn_navegar)
        except Exception as e:
            log(RotuloLog.ERRO, aluno.nome, tipo.value, str(e))
            await _safe_nav(page, fn_navegar)


async def _executar_download(
    page,
    aluno:        Aluno,
    tipo:         TipoDoc,
    decisao:      DecisaoDoc,
    url_template: str,
) -> None:
    """
    Executa o download (ou pula) com base na DecisaoDoc.
    Registra em log cada decisão.
    """
    nome_tipo = "Histórico Escolar" if tipo == TipoDoc.HISTORICO else "Guia de Transferência"

    if decisao.acao == AcaoDecidida.IGNORAR:
        log(RotuloLog.IGNORADO, aluno.nome, nome_tipo, decisao.motivo)
        return

    if decisao.acao == AcaoDecidida.JA_EXISTE:
        log(RotuloLog.IGNORADO, aluno.nome, nome_tipo, decisao.motivo)
        return

    if decisao.doc_sere is None:
        log(RotuloLog.IGNORADO, aluno.nome, nome_tipo, "Sem documento válido para baixar.")
        return

    url     = url_template.format(cod=decisao.doc_sere.cod)
    caminho = decisao.caminho_local
    method  = "POST" if tipo == TipoDoc.GUIA else "GET"

    await baixar_pdf(page, url, caminho, method=method)

    rotulo = {
        AcaoDecidida.BAIXAR:         RotuloLog.DOWNLOAD,
        AcaoDecidida.SUBSTITUIR:     RotuloLog.SUBSTITUIDO,
        AcaoDecidida.GERAR_E_BAIXAR: RotuloLog.DOWNLOAD,
        AcaoDecidida.GERAR_NOVO:     RotuloLog.GERADO,
    }.get(decisao.acao, RotuloLog.DOWNLOAD)

    log(rotulo, aluno.nome, nome_tipo, f"{decisao.motivo} → {caminho}")
    # "baixado_em" e NÃO "anexado_em": anexado_em só pode ser gravado quando o arquivo é ENVIADO à pasta
    # virtual do SERE (sere_2026.modo_transferidos). Antes, o download já marcava anexado_em e o envio,
    # achando que já estava anexado, pulava — quando o slot do SERE tinha documento de outra escola, o
    # nosso nunca era enviado.
    marcar(aluno.cgm, tipo, "baixado_em")


# ══════════════════════════════════════════════════════════════════════════
# AUXILIARES INTERNOS
# ══════════════════════════════════════════════════════════════════════════

def _cabecalho(titulo: str) -> None:
    sep = "═" * 43
    print(f"\n{sep}\n{titulo}\n{sep}")


async def _pesquisar_cgm(page, cgm: str) -> None:
    campo = page.locator('input[name="cgm"]')
    await campo.fill(cgm)
    await delay()
    await campo.press("Enter")
    await page.wait_for_load_state("networkidle")
    await delay()


async def _pesquisar_cgm_guia(page, cgm: str) -> None:
    campo = page.locator('input[name="cgm"]')
    await campo.fill(cgm)
    await delay()
    btn = page.locator('input[name="btnPesquisar"]')
    if await btn.count() > 0:
        await btn.click()
    else:
        await campo.press("Enter")
    await page.wait_for_timeout(2000)


async def _safe_nav(page, fn_nav) -> None:
    try:
        await fn_nav(page)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# ETAPAS — lista canônica (ordem de execução, referência para GUI)
# ══════════════════════════════════════════════════════════════════════════
# Antes: usada por menu_selecao() (input() interativo) para exibir e
# alternar quais etapas rodar. A seleção interativa foi removida — decisão
# do usuário (01/09/2026): cada etapa fica pronta para virar um botão de
# GUI. Esta lista permanece como referência da ordem canônica e é usada
# por processar_transferencias() como padrão quando `etapas` não é
# especificado.

ETAPAS: list[tuple[str, object]] = [
    ("Gravar Matrículas no Histórico",    gravar_matriculas),
    ("Alterar/Excluir (adicionar obs.)",  alterar_historico),
    ("Emitir/Gerar Histórico",            gerar_historico),
    ("Assinar Históricos",                assinar_historico),
    ("Imprimir Históricos (baixar PDF)",  imprimir_historicos),
    ("Emitir/Gerar Guia de Transferência", gerar_guia),
    ("Assinar Guias",                     assinar_guia),
    ("Imprimir Guias (baixar PDF)",       imprimir_guias),
]


_NOMES_ETAPAS = [nome for nome, _ in ETAPAS]
GRUPOS_ETAPAS: dict[str, list[str]] = {
    "todas":     _NOMES_ETAPAS,
    "historico": _NOMES_ETAPAS[:5],          # gravar matrículas → alterar → gerar → assinar → baixar o histórico
    "guia":      _NOMES_ETAPAS[5:],          # gerar → assinar → baixar a guia de transferência
}

# As 5 ações da tela, cada uma com a(s) etapa(s) que executa. Gravar e Alterar são só do histórico;
# Emitir, Assinar e Imprimir valem para o histórico e para a guia.
ETAPA_ACAO = {
    "gravar":   {"historico": [_NOMES_ETAPAS[0]]},
    "alterar":  {"historico": [_NOMES_ETAPAS[1]]},
    "emitir":   {"historico": [_NOMES_ETAPAS[2]], "guia": [_NOMES_ETAPAS[5]]},
    "assinar":  {"historico": [_NOMES_ETAPAS[3]], "guia": [_NOMES_ETAPAS[6]]},
    "imprimir": {"historico": [_NOMES_ETAPAS[4]], "guia": [_NOMES_ETAPAS[7]]},
}
ACOES = tuple(ETAPA_ACAO)                    # ordem em que aparecem na tela
ETAPA_ALTERAR = _NOMES_ETAPAS[1]


def etapas_por_acoes(acoes: list[str], documentos: str = "ambos") -> list[str]:
    """
    Nomes de etapa (na ordem canônica) para as ações marcadas. `documentos`: "ambos", "historico" ou "guia"
    (restringe Emitir/Assinar/Imprimir; Gravar e Alterar não existem para a guia). ValueError se algo for inválido.
    """
    if documentos not in ("ambos", "historico", "guia"):
        raise ValueError(f"Documentos inválido: {documentos!r}. Use ambos, historico ou guia.")
    invalidas = [a for a in acoes if a not in ETAPA_ACAO]
    if invalidas:
        raise ValueError(f"Ação(ões) desconhecida(s): {invalidas}. Válidas: {', '.join(ACOES)}.")
    tipos = ("historico", "guia") if documentos == "ambos" else (documentos,)
    escolhidas = {nome for a in acoes for t in tipos for nome in ETAPA_ACAO[a].get(t, [])}
    return [nome for nome in _NOMES_ETAPAS if nome in escolhidas]


def _escolher_etapas(etapas: Optional[list[str]], observacao: Optional[str] = None) -> list[tuple[str, object]]:
    if etapas is None:
        etapas = _NOMES_ETAPAS
    desconhecidas = [e for e in etapas if e not in set(_NOMES_ETAPAS)]
    if desconhecidas:
        print(f"⚠️  Etapa(s) desconhecida(s), ignorada(s): {desconhecidas}")
    escolhidas = []
    for nome, fn in ETAPAS:
        if nome not in etapas:
            continue
        if nome == ETAPA_ALTERAR and observacao is not None:
            fn = functools.partial(fn, observacao=observacao)        # o texto vem da tela
        escolhidas.append((nome, fn))
    return escolhidas


def _imprimir_plano(alunos: list[Aluno], etapas: list[tuple[str, object]], observacao: Optional[str] = None) -> None:
    """Simulação: mostra o que seria feito, sem abrir o SERE e sem gravar nada."""
    print(f"\n{'='*65}\n  🧪 SIMULAÇÃO — nada será gerado, baixado nem gravado\n{'='*65}")
    print(f"  Data de corte : {_corte().strftime('%d/%m/%Y')}")
    print(f"  Histórico em  : {_dir_historicos()}")
    print(f"  Guia em       : {_dir_guia_transferencia()}")
    print(f"  Etapas ({len(etapas)}):")
    for i, (nome, _) in enumerate(etapas, 1):
        print(f"     {i}. {nome}")
    if any(nome == ETAPA_ALTERAR for nome, _ in etapas):
        print(f"  Texto da observação (Alterar): {observacao!r}" if observacao else
              "  Texto da observação (Alterar): (vazio)")
    print(f"\n  Alunos ({len(alunos)}):")
    for a in alunos:
        partes = []
        for tipo, rotulo in ((TipoDoc.HISTORICO, "histórico"), (TipoDoc.GUIA, "guia")):
            info = info_doc_json(a.cgm, tipo)
            if info.emitido_em is None:
                partes.append(f"{rotulo}: a emitir")
            else:
                assin = "assinado" if info.valido else "sem assinaturas"
                partes.append(f"{rotulo}: emitido em {info.emitido_em:%d/%m/%Y} ({assin})")
        print(f"     CGM {a.cgm} — {a.nome} [{a.turma}] → " + " | ".join(partes))
    print(f"{'='*65}\n  O SERE decide, no momento real, se cada documento é gerado, baixado ou reaproveitado.\n")


# ══════════════════════════════════════════════════════════════════════════
# PROCESSAMENTO COMPLETO (ponto de entrada pronto para uma futura GUI)
# ══════════════════════════════════════════════════════════════════════════

async def processar_transferencias(
    etapas: Optional[list[str]] = None,
    simulacao: bool = False,
    modo_teste: bool = False,
    observacao: Optional[str] = None,
) -> None:
    """
    Ponto de entrada completo: lê a fila de transferidos (fila_transferidos.json, gerada pelo turmas.py),
    registra o pré-corte, abre o SERE e executa as etapas escolhidas (todas, por padrão), uma por vez para
    todos os alunos elegíveis, salvando histórico e guia em dados/<ano>/TRANSFERENCIAS.

    `etapas`: nomes de etapa (ver ETAPAS / GRUPOS_ETAPAS), executados na ordem canônica; None = todas.
    `simulacao`: só mostra quem e o que seria processado — não abre o SERE e não grava nada (nem a fila).
    `modo_teste`: processa só o primeiro aluno da fila (de verdade; não é simulação).
    `observacao`: texto gravado em cada histórico na etapa "Alterar" (None = constante OBSERVACAO).
    """
    print(f"\n🔄 Processo de transferidos — data de corte {_corte().strftime('%d/%m/%Y')}"
          f"{' — SIMULAÇÃO' if simulacao else ''}")

    if not simulacao:
        _pastas.garantir_pastas(_DADOS)
        print("\n🗂️  Verificando alunos pré-corte...")
        registrar_pre_corte()

    alunos = carregar_alunos(gravar_fila=not simulacao)
    if not alunos:
        print("⚠️  Nenhum aluno encontrado com os critérios definidos. Encerrando.")
        return
    if modo_teste:
        alunos = alunos[:1]
        print("⚠️  MODO TESTE — só o primeiro aluno")

    etapas_a_rodar = _escolher_etapas(etapas, observacao)
    if not etapas_a_rodar:
        print("⚠️  Nenhuma etapa válida selecionada. Encerrando.")
        return

    if simulacao:
        _imprimir_plano(alunos, etapas_a_rodar, observacao)
        return

    print(f"\n👥 Alunos carregados ({len(alunos)}):")
    for a in alunos:
        print(f"   CGM {a.cgm} — {a.nome} [{a.turma}]")

    print("\n📝 Inicializando transferidos.json...")
    inicializar_alunos(alunos)

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "chromium", True, slow_mo=200)
        context = await browser.new_context()
        page    = await context.new_page()

        await login(page)

        for nome_etapa, func in etapas_a_rodar:
            await func(page, alunos)

        print("\n🎉 Processo finalizado para todos os alunos!")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(processar_transferencias())

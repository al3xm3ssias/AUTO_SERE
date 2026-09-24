"""
cruzar_documentos.py — Cruzamento entre documentos do SERE e documentos do PC
=============================================================================

RESUMO ESTRUTURAL (funções principais):
   - normalize(): remove extensão, acentos, pontuação; minúsculo, colapsa espaços.
   - should_ignore(): True se o documento deve ser descartado (situacional/irrelevante).
   - _strip_nome_aluno(): remove o sufixo '-Nome-S-O-B' (iniciais do aluno) do
     nome de arquivo do PC, para isolar o tipo do documento.
   - classify_slot(): retorna o slot canônico para um nome de documento/tipo/
     arquivo, em pipeline de 5 etapas (sinônimo exato → ignore → substring de
     palavra completa → prefixo de palavra completa → regex de fallback).
   - build_sere_index() / build_pc_index() / determine_status() / cruzar()

cruzar_documentos.py — Cruzamento entre documentos do SERE e documentos do PC
=============================================================================
Portado de AUTO_SERE/cruzar_documentos.py para
src/relatorios/cruzar_documentos.py.

Fecha o ciclo de verificação de documentos: cruza o que
src.relatorios.analisa_arquivos_sere gera (documentos-alunos.json, o que
está anexado no SERE) com o que src.relatorios.analisa_documentos_pc gera
(documentos-alunos-pc.json, o que está digitalizado no PC), produzindo
cruzamento-documentos.json com o status de cada aluno (Completo, Parcial,
Pendente, Sem pasta no PC, Sem docs básicos no PC).

Este script tem seu PRÓPRIO sistema de classificação de documentos
(SINONIMOS, SLOT_PATTERNS, classify_slot — um pipeline de 5 etapas),
DELIBERADAMENTE mantido independente do catálogo de
src.comum.sere_normalizacao (decisão do usuário em 02/09/2026) — são
vocabulários e propósitos de classificação diferentes; unificar arriscaria
quebrar a lógica fina do pipeline (ordem de prioridade entre sinônimo
exato, ignore, substring de palavra completa, prefixo, regex de fallback).
100% offline: não usa Playwright, só processa os três JSONs já coletados.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Caminhos: main() usava argparse com defaults de caminho RELATIVO
   ('documentos-alunos.json', 'documentos-alunos-pc.json',
   'cruzamento-documentos.json', 'turmas.json') — dependia de estar
   rodando no diretório certo. Agora os defaults vêm de
   src.comum.paths.dados_ano_atual(), mesma arquitetura de todos os
   outros scripts já portados. Os parâmetros continuam aceitando um
   caminho explícito (agora Path, opcional) para quem quiser sobrescrever.

2. main() foi mantida com o nome main() por consistência com o padrão dos
   outros módulos utilitários já portados (analisa_documentos_pc.py), mas
   agora aceita os caminhos como parâmetros de função em vez de ler de
   sys.argv via argparse — argparse removido, pronta para ser chamada
   diretamente por outro script ou por um futuro botão de GUI.

Toda a lógica de classificação (normalize, should_ignore, _strip_nome_aluno,
classify_slot, build_sere_index, build_pc_index, determine_status, cruzar)
é idêntica ao original — nenhuma regra de negócio foi alterada.

Uso:
    from src.relatorios.cruzar_documentos import main
    main()
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.comum import paths as _paths

_DADOS = _paths.dados_ano_atual()


# ─────────────────────────────────────────────────────────────────────────────
#  SLOTS CANÔNICOS
#  Cada slot representa um tipo de documento para fins de cruzamento.
#  "rg do aluno" e "cpf responsavel" são os nomes internos definitivos.
# ─────────────────────────────────────────────────────────────────────────────

# Slots obrigatórios — todos precisam estar no SERE para status "Completo".
# RG é situacional: se existir no PC, precisa estar no SERE; mas a ausência
# do RG no PC não impede o status Completo.
SLOTS_OBRIGATORIOS = {
    'cpf do aluno',
    'cpf responsavel',
    'certidao de nascimento do aluno',
    'comprovante de vacinacao',
    'comprovante de residencia',
}

# Slots situacionais — existem nos arquivos mas não são exigidos para "Completo"
SLOTS_SITUACIONAIS = {
    'rg do aluno',          # Situacional: exigido só se o aluno já tem RG
}


# ─────────────────────────────────────────────────────────────────────────────
#  BIBLIOTECA DE SINÔNIMOS
#  Chave  = slot canônico (interno, normalizado, sem acentos)
#  Valor  = lista de strings que, após normalize(), devem mapear para esse slot.
#
#  A função classify_slot() também aplica um conjunto de regexes como fallback,
#  mas os sinônimos têm PRIORIDADE e cobrem todos os casos reais observados
#  nos arquivos do PC e nos tipos do SERE.
# ─────────────────────────────────────────────────────────────────────────────
SINONIMOS: dict[str, list[str]] = {

    # ── RG do aluno ──────────────────────────────────────────────────────────
    'rg do aluno': [
        'rg do aluno',
        'rg aluno',
        'rg',               # arquivo genérico "RG" no SERE
    ],

    # ── CPF do aluno ─────────────────────────────────────────────────────────
    'cpf do aluno': [
        'cpf do aluno',
        'cpf aluno',
        'cpf da aluna',     # feminino
        'rg e cpf do aluno',            # arquivo combinado → CPF prevalece
        'cpf e rg do aluno',            # idem, ordem invertida
        'rg e cpf da aluna',            # feminino
        'cpf e rg da aluna',
        'rg e cpf do aluno e cartao do sus',   # RG+CPF+cartão SUS
        'cpf e cartao sus da aluna',
        'cpf do aluno e cartao sus',
    ],

    # ── CPF / Documento do responsável ───────────────────────────────────────
    'cpf responsavel': [
        'cpf responsavel',
        'cpf do responsavel',
        'cpf dos responsaveis',
        'cpf pai',
        'cpf mae',
        'documento do responsavel',
        'documento da mae',         # "documento da mãe"
        'documento do pai',
        'documentos do responsavel',
        'documento dos responsaveis',
        'documentos dos responsaveis',
        'documentos dos pais',      # "DOCUMENTOS DOS PAIS"
        'documentos pais',
        'rg e cpf do responsavel',
        'rg e cpf da responsavel',  # feminino
        'rg e cpf dos responsaveis',
        'cnh do responsavel',       # CNH conta como doc do responsável
        'cnh da mae',               # "CNH DA MÃE DA VALENTINA"
        'cnh do pai',
        # genéricos — só quando o arquivo não tem outro indicador
        'documentos',
        'documento',
        'responsavel',
    ],

    # ── Certidão de nascimento ────────────────────────────────────────────────
    'certidao de nascimento do aluno': [
        'certidao de nascimento',
        'certidao de nascimento do aluno',
        'certidao do nascimento',           # variação comum
        'certidão de nacimento',            # typo frequente (1 's')
        'certidão do aluno',
        'certidao',                         # arquivo "certidão" sozinho
        'nascimento',
    ],

    # ── Comprovante de vacinação ──────────────────────────────────────────────
    'comprovante de vacinacao': [
        'comprovante de vacinacao',
        'comprovante de vacinacao e cartao sus',
        'cartao sus e carteirinha de vacinacao',   # combinado
        'carteirinha de vacinacao',
        'carteirinha de vacinacao e cartao sus',
        'cartao de vacinacao',
        'carteirinha',                  # arquivo "carteirinha" sozinho
        'carteira de vacinacao',
        'carteira',                     # arquivo "carteira" sozinho
        'declaracao de vacinacao',
        'declaracao de vacina',
        'vacinacao',
        'vacina',
        'comprovante de vacina',
    ],

    # ── Comprovante de residência ─────────────────────────────────────────────
    'comprovante de residencia': [
        'comprovante de residencia',
        'comprovante de endereco',      # "endereço" é sinônimo de residência
        'comprovante de residencia sanepar',
        'residencia',
        'endereco',
        'copel',
        'faturacopel',                  # "FaturaCopel" — conta de luz
        'sanepar',
        'talao',
    ],
}

# Índice invertido: string normalizada → slot canônico
# Construído uma única vez na inicialização do módulo.
_SINONIMO_IDX: dict[str, str] = {}
for _slot, _lista in SINONIMOS.items():
    for _s in _lista:
        _key = _s.strip().lower()
        # Remove acentos do próprio sinônimo para consistência
        _key = unicodedata.normalize('NFKD', _key)
        _key = ''.join(c for c in _key if not unicodedata.combining(c))
        _SINONIMO_IDX[_key] = _slot


# ─────────────────────────────────────────────────────────────────────────────
#  IGNORADOS — descartados antes de qualquer classificação (SERE e PC)
# ─────────────────────────────────────────────────────────────────────────────
IGNORE_PATTERNS = [
    r'laudo',
    r'cartao\s*(sus|saude)',
    r'cartao\s*do\s*(sus|saude)',
    r'cartao\s*sus',
    r'requerimento\s*(de)?\s*matricul',
    r'^requerimento$',
    r'^matricula$',
    r'parecer',
    r'ficha\s*(de)?\s*saude',
    r'comp(rovante)?\s*(de)?\s*trabalho',
    r'guia\s*(de)?\s*transfer',
    r'historico\s*(escolar)?',
    r'declaracao\s*(de)?\s*matricul',
    r'transfer(encia)?\s*escolar',
    r'^img\s*\d+',                  # IMG_0001, IMG_0002 etc.
    r'receita\s*medica',
    r'cad\s*(unico|único)',
    r'bolsa\s*familia',
    r'folha\s*de\s*resumo',
    r'termo\s*de\s*desistencia',
    r'certidao\s*de\s*casamento',   # certidão de casamento ≠ de nascimento
]

# Extensões aceitas ao processar nomes de arquivo do PC
EXTENSOES_ACEITAS = {'.pdf', '.jpg', '.jpeg', '.png'}


# ─────────────────────────────────────────────────────────────────────────────
#  REGEXES DE FALLBACK (usados quando nenhum sinônimo exato casa)
#  Ordem importa: o primeiro padrão que casar vence.
# ─────────────────────────────────────────────────────────────────────────────
SLOT_PATTERNS = [
    # RG do aluno (exclui "RG E CPF DO RESPONSAVEL" — capturado por cpf responsavel)
    (r'^rg(\s*(do|da)?\s*(aluno|aluna))?$'
     r'|^rg\s*(do|da)\s*(aluno|aluna)'
     r'|^rg\s*(aluno|aluna)',                                'rg do aluno'),

    # CPF do aluno — inclui feminino "da aluna"
    (r'cpf\s*(do|da)?\s*(aluno|aluna)'
     r'|cpf\s*(aluno|aluna)',                                'cpf do aluno'),

    # "RG E CPF DO ALUNO" — arquivo combinado → apenas CPF (RG extra é bonus)
    (r'rg\s*e\s*cpf\s*(do|da)?\s*(aluno|aluna)'
     r'|cpf\s*e\s*rg\s*(do|da)?\s*(aluno|aluna)',           'cpf do aluno'),

    # CPF do responsável — cobre variações + arquivos genéricos
    (r'cpf\s*(do|da|dos)?\s*respons'
     r'|cpf\s*(pai|mae|pais)'
     r'|rg\s*e\s*cpf\s*(do|da|dos)?\s*respons'
     r'|rg\s*e\s*cpf\s*(da)?\s*respons'
     r'|documento\s*(do|da|dos)?\s*respons'
     r'|documentos\s*(do|da|dos)?\s*respons'
     r'|documento\s*(d[ao])?\s*mae'
     r'|cnh\s*(do|da)?\s*respons'
     r'|cnh\s*(d[ao])?\s*(mae|pai)'
     r'|^documentos\s*dos\s*pais'
     r'|^documentos\s*pais$'
     r'|^responsavel$'
     r'|^documentos$'
     r'|^documento$',                                        'cpf responsavel'),

    # Certidão de nascimento — inclui typos e variações
    (r'certidao\s*(de|do)?\s*nas[ci]mento'    # "nacimento" e "nascimento"
     r'|certidao\s*(do)?\s*aluno'
     r'|^certidao$'
     r'|^nascimento$',                                       'certidao de nascimento'),

    # Vacinação — unifica todas as variações
    (r'comp(rovante)?\s*(de)?\s*vacin'
     r'|carteira\s*(de)?\s*vacin'
     r'|carteirinha\s*(de)?\s*vacin'
     r'|cartao\s*(de)?\s*vacin'
     r'|declaracao\s*(de)?\s*vacin'
     r'|^vacinacao'
     r'|^vacina$'
     r'|^carteirinha$'
     r'|^carteira$',                                         'comprovante de vacinacao'),

    # Comprovante de residência / endereço
    (r'comp(rovante)?\s*(de)?\s*(resid|enderec)'
     r'|comrpovante\s*(de)?\s*(resid|enderec)'  # typo "COMRPOVANTE"
     r'|comprovanta\s*(de)?\s*(resid|enderec)'  # typo "comprovanta"
     r'|comrpvante\s*(de)?\s*(resid|enderec)'   # typo "comrpvante"
     r'|^residencia$'
     r'|^endereco$'
     r'|^copel$'
     r'|^faturacopel'
     r'|^sanepar$'
     r'|^talao$'
     r'|^comprovante$',                                      'comprovante de residencia'),
]


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Remove extensão, acentos, pontuação; converte para minúsculo e
    colapsa espaços múltiplos."""
    # Remove extensão conhecida
    for ext in EXTENSOES_ACEITAS:
        if text.lower().endswith(ext):
            text = text[: -len(ext)]
            break
    # Remove acentos
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    # Normaliza separadores e caracteres especiais
    text = re.sub(r'[_\-\.\(\)]', ' ', text)
    text = re.sub(r'[^a-z0-9 ]', '', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def should_ignore(name: str) -> bool:
    """Retorna True se o documento deve ser descartado (situacional/irrelevante)."""
    n = normalize(name)
    return any(re.search(p, n) for p in IGNORE_PATTERNS)


def _strip_nome_aluno(text_norm: str) -> str:
    """
    Os nomes de arquivo do PC terminam com '-Nome-S-O-B' (iniciais do aluno).
    Esta função tenta remover esse sufixo para isolar o tipo do documento.
    Estratégia: remove a última sequência de tokens curtos (≤3 chars) separados
    por espaço, precedidos de pelo menos um token longo (o tipo do documento).
    """
    tokens = text_norm.split()
    # Encontrar até onde vai o "tipo": é a parte antes das iniciais do nome.
    # Heurística: iniciais são tokens de 1-2 chars (letras). O nome próprio
    # em minúsculo também pode ter 3-4 chars. Paramos quando encontramos
    # sequência de ≥2 tokens curtos consecutivos (1-2 chars) no final.
    cut = len(tokens)
    i = len(tokens) - 1
    short_run = 0
    while i >= 0:
        t = tokens[i]
        if len(t) <= 2:
            short_run += 1
        else:
            # token longo: pode ser parte do nome próprio (ex: 'alice', 'mariana')
            # ou parte do tipo (ex: 'comprovante', 'certidao').
            # Se já temos ≥1 token curto depois, e esse token longo parece um
            # nome próprio (letra, sem dígitos), paramos antes dele.
            if short_run >= 1 and not any(c.isdigit() for c in t):
                cut = i + 1  # mantém até aqui (exclusive o nome)
            else:
                break
        i -= 1

    # Garante que não removemos o tipo inteiro
    result = ' '.join(tokens[:cut]).strip()
    return result if result else text_norm


def classify_slot(name: str) -> str | None:
    """
    Retorna o slot canônico para um nome de documento/tipo/arquivo.
    Pipeline (ordem importa):
      1. Correspondência exata no índice de sinônimos (prioridade máxima;
         sinônimos longos/compostos como "rg e cpf do aluno" entram aqui).
      2. Check de ignore — descarta situacionais/irrelevantes.
      3. Substring de palavra completa (mais longa primeiro).
      4. Prefixo de palavra completa.
      5. Regexes de fallback.
    Retorna None se não reconhecido ou ignorado.
    """
    n_full = normalize(name)
    n_tipo = _strip_nome_aluno(n_full)

    # ── Etapa 1: exato (tipo limpo e texto completo) ─────────────────────────
    if n_tipo in _SINONIMO_IDX:
        return _SINONIMO_IDX[n_tipo]
    if n_full in _SINONIMO_IDX:
        return _SINONIMO_IDX[n_full]

    # ── Etapa 2: ignore ───────────────────────────────────────────────────────
    # Feito ANTES da busca substring para que "certidao de casamento" seja
    # descartado mesmo que "certidao" seja substring de outro slot.
    if should_ignore(name):
        return None

    # ── Etapa 3: substring de palavra completa (mais longa primeiro) ─────────
    # Cobre "cartao sus e carteirinha de vacinacao ..." via sinônimo longo.
    # O check de ignore acima já descartou casos puros como "CARTAO SUS-Alice".
    for key, slot in sorted(_SINONIMO_IDX.items(), key=lambda x: -len(x[0])):
        if len(key) < 6:
            continue
        pos = n_full.find(key)
        if pos == -1:
            continue
        before_ok = (pos == 0) or (n_full[pos - 1] == ' ')
        after_pos = pos + len(key)
        after_ok  = (after_pos >= len(n_full)) or (n_full[after_pos] == ' ')
        if before_ok and after_ok:
            return slot

    # ── Etapa 4: prefixo de palavra completa (mais longa primeiro) ──────────
    for key, slot in sorted(_SINONIMO_IDX.items(), key=lambda x: -len(x[0])):
        if len(key) < 6:
            continue
        for text in (n_tipo, n_full):
            if text.startswith(key):
                rest = text[len(key):]
                if rest == '' or rest[0] == ' ':
                    return slot

    # ── Etapa 5: regexes de fallback ─────────────────────────────────────────
    for pattern, slot in SLOT_PATTERNS:
        if re.search(pattern, n_tipo) or re.search(pattern, n_full):
            return slot

    return None


# ─────────────────────────────────────────────────────────────────────────────
#  ÍNDICES
# ─────────────────────────────────────────────────────────────────────────────

def build_sere_index(sere_list: list) -> dict:
    idx = {}
    for aluno in sere_list:
        cgm = str(aluno.get('CGM', '')).strip()
        if not cgm:
            continue
        slots: dict[str, list[str]] = {}
        for det in aluno.get('Detalhes', []):
            tipo    = det.get('tipo', '')
            arquivo = det.get('arquivo', '')
            slot = classify_slot(tipo) or classify_slot(arquivo)
            if slot:
                slots.setdefault(slot, []).append(arquivo or tipo)
        idx[cgm] = {
            'nome':     aluno.get('Nome', ''),
            'slots':    slots,
            'raw_docs': aluno.get('Documentos', []),
        }
    return idx


def _doc_display_name(doc) -> str:
    """
    Extrai o nome de exibição de um item de 'Documentos' do PC.
    Cada item pode ser:
      - str: nome do arquivo diretamente (formato legado).
      - dict: objeto com campos 'nome_completo' / 'nome_arquivo' / 'nome'
        (formato atual do documentos-alunos-pc.json).
    """
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return (
            doc.get('nome_completo')
            or doc.get('nome_arquivo')
            or doc.get('nome')
            or ''
        )
    return str(doc)


def build_pc_index(pc_list: list) -> dict:
    idx = {}
    for aluno in pc_list:
        cgm = str(aluno.get('CGM', '')).strip()
        if not cgm:
            continue
        slots: dict[str, list[str]] = {}
        for doc in aluno.get('Documentos', []):
            nome_doc = _doc_display_name(doc)
            if not nome_doc:
                continue
            slot = classify_slot(nome_doc)
            if slot:
                slots.setdefault(slot, []).append(nome_doc)
        idx[cgm] = {
            'nome':     aluno.get('Nome', ''),
            'turma':    aluno.get('Turma', ''),
            'slots':    slots,
            'raw_docs': [_doc_display_name(d) for d in aluno.get('Documentos', [])],
        }
    return idx


# ─────────────────────────────────────────────────────────────────────────────
#  STATUS
# ─────────────────────────────────────────────────────────────────────────────

def determine_status(slots_pc: dict, slots_sere: dict, has_pc_entry: bool) -> str:
    if not has_pc_entry:
        return 'Sem pasta no PC'
    if not slots_pc:
        return 'Sem docs básicos no PC'

    slots_pc_set   = set(slots_pc.keys())
    slots_sere_set = set(slots_sere.keys())

    # RG: situacional — só exigido no SERE se existir no PC
    rg_no_pc   = 'rg do aluno' in slots_pc_set
    rg_no_sere = 'rg do aluno' in slots_sere_set
    rg_ok      = (not rg_no_pc) or rg_no_sere

    # Completo = os 5 obrigatórios no PC E no SERE (espelho), + RG ok
    todos_obrig_no_pc   = SLOTS_OBRIGATORIOS <= slots_pc_set
    todos_obrig_no_sere = SLOTS_OBRIGATORIOS <= slots_sere_set

    if todos_obrig_no_pc and todos_obrig_no_sere and rg_ok:
        return 'Completo — todos PC anexados'
    if slots_sere_set & SLOTS_OBRIGATORIOS or (rg_no_pc and rg_no_sere):
        return 'Parcial — parte anexada'
    return 'Pendente — nenhum PC anexado'


# ─────────────────────────────────────────────────────────────────────────────
#  CRUZAMENTO
# ─────────────────────────────────────────────────────────────────────────────

def cruzar(sere_list: list, pc_list: list) -> dict:
    sere_idx = build_sere_index(sere_list)
    pc_idx   = build_pc_index(pc_list)

    all_cgms = sorted(set(sere_idx) | set(pc_idx))

    alunos_out = []
    resumo = {
        'completo': 0, 'parcial': 0, 'pendente': 0,
        'sem_pasta_pc': 0, 'sem_docs_basicos': 0,
    }

    for cgm in all_cgms:
        sere_entry = sere_idx.get(cgm)
        pc_entry   = pc_idx.get(cgm)
        has_pc     = pc_entry is not None

        slots_pc   = (pc_entry   or {}).get('slots', {})
        slots_sere = (sere_entry or {}).get('slots', {})
        nome       = (sere_entry or pc_entry or {}).get('nome', '')
        turma      = (pc_entry or {}).get('turma', '')
        status     = determine_status(slots_pc, slots_sere, has_pc)

        slots_pc_set   = set(slots_pc.keys())
        slots_sere_set = set(slots_sere.keys())

        all_slots   = sorted(slots_pc_set | slots_sere_set)
        docs_detail = {}
        for slot in all_slots:
            docs_pc   = slots_pc.get(slot, [])
            docs_sere = slots_sere.get(slot, [])
            docs_detail[slot] = {
                'no_pc':   bool(docs_pc),
                'no_sere': bool(docs_sere),
                'anexado': bool(docs_pc) and bool(docs_sere),
                'docs_pc':   docs_pc,
                'docs_sere': docs_sere,
            }

        key_map = {
            'Completo — todos PC anexados': 'completo',
            'Parcial — parte anexada':      'parcial',
            'Pendente — nenhum PC anexado': 'pendente',
            'Sem pasta no PC':              'sem_pasta_pc',
            'Sem docs básicos no PC':       'sem_docs_basicos',
        }
        resumo[key_map.get(status, 'pendente')] += 1

        alunos_out.append({
            'CGM':    cgm,
            'Nome':   nome,
            'Turma':  turma,
            'Status': status,
            'Resumo': {
                'docs_pc_total':        len(slots_pc),
                'docs_sere_total':      len(slots_sere),
                'slots_pc':             sorted(slots_pc_set),
                'slots_sere':           sorted(slots_sere_set),
                'slots_anexados':       sorted(slots_pc_set & slots_sere_set),
                'slots_pc_nao_anexado': sorted(slots_pc_set - slots_sere_set),
                'slots_sere_sem_pc':    sorted(slots_sere_set - slots_pc_set),
            },
            'Documentos': docs_detail,
        })

    alunos_out.sort(key=lambda a: a['Nome'])
    return {
        'Total_Alunos': len(alunos_out),
        'Data_Hora':    datetime.now().strftime('%d/%m/%Y %H:%M'),
        'Resumo_Geral': resumo,
        'Alunos':       alunos_out,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  PONTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

def main(
    caminho_sere:   Optional[Path] = None,
    caminho_pc:     Optional[Path] = None,
    caminho_out:    Optional[Path] = None,
    caminho_turmas: Optional[Path] = None,
) -> dict:
    """
    Cruza documentos do PC com o SERE e gera cruzamento-documentos.json.

    Todos os caminhos são opcionais — por padrão, usam os arquivos de
    dados de trabalho do ano letivo corrente (src.comum.paths.dados_ano_atual()),
    a mesma pasta onde src.relatorios.analisa_arquivos_sere e
    src.relatorios.analisa_documentos_pc já salvam seus resultados.
    argparse removido (era `--sere`, `--pc`, `--out`, `--turmas` no
    original) — os mesmos quatro caminhos agora são parâmetros de função,
    prontos para serem chamados diretamente por outro script ou por um
    futuro botão de GUI.
    """
    caminho_sere   = caminho_sere   or (_DADOS / 'documentos-alunos.json')
    caminho_pc     = caminho_pc     or (_DADOS / 'documentos-alunos-pc.json')
    caminho_out    = caminho_out    or (_DADOS / 'cruzamento-documentos.json')
    caminho_turmas = caminho_turmas or (_DADOS / 'turmas.json')

    with open(caminho_sere, encoding='utf-8') as f:
        sere_list = json.load(f)
    with open(caminho_pc, encoding='utf-8') as f:
        pc_list = json.load(f)

    # Carrega turmas.json para obter situação de cada aluno
    cgms_transferidos: set[str] = set()
    try:
        with open(caminho_turmas, encoding='utf-8') as f:
            turmas_data = json.load(f)
        for alunos in turmas_data.values():
            for a in (alunos if isinstance(alunos, list) else []):
                sit = str(a.get('Situação', a.get('Situacao', ''))).strip().lower()
                if 'transf' in sit:
                    cgms_transferidos.add(str(a.get('CGM', '')).strip())
    except FileNotFoundError:
        print(f'  ⚠  {caminho_turmas} não encontrado — nenhum aluno ignorado por Transferido')

    sere_list_orig = sere_list
    pc_list_orig   = pc_list
    sere_list = [a for a in sere_list if str(a.get('CGM', '')).strip() not in cgms_transferidos]
    pc_list   = [a for a in pc_list   if str(a.get('CGM', '')).strip() not in cgms_transferidos]

    print(f'  SERE : {len(sere_list_orig)} alunos ({len(sere_list_orig)-len(sere_list)} transferidos ignorados)')
    print(f'  PC   : {len(pc_list_orig)} alunos ({len(pc_list_orig)-len(pc_list)} transferidos ignorados)')

    resultado = cruzar(sere_list, pc_list)

    caminho_out.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_out, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    r, total = resultado['Resumo_Geral'], resultado['Total_Alunos']
    print(f'\n✅  {caminho_out} gerado com {total} alunos:')
    print(f'   ✓ Completo  : {r["completo"]}')
    print(f'   ~ Parcial   : {r["parcial"]}')
    print(f'   ✗ Pendente  : {r["pendente"]}')
    print(f'   Sem pasta PC: {r["sem_pasta_pc"]}')
    print(f'   Sem básicos : {r["sem_docs_basicos"]}')

    return resultado


if __name__ == '__main__':
    main()

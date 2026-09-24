"""
rematricula_persistencia.py — Controle de progresso da rematrícula
=============================================================================
Portado de AUTO_SERE/rematricula.py (normalize_text,
carregar_erros_anteriores, carregar_sucessos_anteriores, salvar_resultados,
aluno_ja_processado, ErroReiniciarNavegador) para
src/automacao/rematricula_persistencia.py.

Mantém o controle de quais alunos já foram rematriculados com sucesso
(para não reprocessar em execuções futuras) e quais deram erro (para o
modo "apenas_erros" poder reprocessar só esses). Três arquivos JSON de
controle: sucessos, erros e um histórico consolidado de cada execução.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

Caminhos: ARQUIVO_ERROS/ARQUIVO_SUCESSO/ARQUIVO_HISTORICO (antes nomes de
arquivo relativos, dependentes do diretório de execução) agora vêm de
src.comum.paths.dados_ano_atual() — mesma arquitetura de todos os outros
scripts já portados.

Toda a lógica (normalização de texto tolerante a acentos/traços/NBSP para
comparação de nomes de turma, critério de "já processado" por CGM) é
idêntica ao original — nenhuma regra foi alterada.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from src.comum import paths as _paths

_DADOS = _paths.dados_ano_atual()

ARQUIVO_ERROS     = _DADOS / "rematriculas_erro.json"
ARQUIVO_SUCESSO   = _DADOS / "rematriculas_sucesso.json"
ARQUIVO_HISTORICO = _DADOS / "rematriculas_historico.json"


class ErroReiniciarNavegador(Exception):
    """
    Levantada quando um erro (ex.: timeout crítico, DOM travado) sinaliza
    que a única recuperação confiável é reiniciar a página inteira do
    aluno atual (fechar e abrir uma nova), não só re-tentar um clique
    pontual. Ver src.automacao.rematricula.processar_aluno para o retry
    que captura esta exceção.
    """
    pass


def normalize_text(s: str) -> str:
    """
    Normaliza texto para comparação:
    - Normalização Unicode (NFKC)
    - Substitui NBSP por espaço
    - Unifica tipos de traço para '-'
    - Colapsa múltiplos espaços
    - Remove acentuação (para matching mais tolerante)
    - Converte para minúsculas
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[–—−]", "-", s)
    s = " ".join(s.split())
    # remover acentos
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = unicodedata.normalize("NFC", s)
    return s.lower()


def carregar_erros_anteriores(arquivo: Path = ARQUIVO_ERROS) -> list[dict]:
    """Carrega lista de alunos que deram erro anteriormente"""
    if arquivo.exists():
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def carregar_sucessos_anteriores(arquivo: Path = ARQUIVO_SUCESSO) -> list[dict]:
    """Carrega lista de alunos já processados com sucesso"""
    if arquivo.exists():
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_resultados(
    sucessos: list[dict],
    erros: list[dict],
    historico: list[dict],
    arquivo_sucesso: Path = ARQUIVO_SUCESSO,
    arquivo_erros: Path = ARQUIVO_ERROS,
    arquivo_historico: Path = ARQUIVO_HISTORICO,
) -> None:
    """Salva os resultados em arquivos separados"""
    arquivo_sucesso.parent.mkdir(parents=True, exist_ok=True)

    with open(arquivo_sucesso, "w", encoding="utf-8") as f:
        json.dump(sucessos, f, ensure_ascii=False, indent=4)

    with open(arquivo_erros, "w", encoding="utf-8") as f:
        json.dump(erros, f, ensure_ascii=False, indent=4)

    with open(arquivo_historico, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=4)


def aluno_ja_processado(aluno: dict, lista_sucesso: list[dict]) -> bool:
    """Verifica se aluno já foi processado com sucesso"""
    for item in lista_sucesso:
        if item["cgm"] == aluno["cgm"]:
            return True
    return False

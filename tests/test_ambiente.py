"""
Teste de verificação do ambiente (Fase 3 — Verificação do ambiente).

Este teste não depende de credenciais reais nem acessa o portal SERE.
Ele só confirma que a estrutura básica do projeto está coerente.
"""

from pathlib import Path
import sys

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))


def test_estrutura_de_pastas_existe():
    pastas_essenciais = ["src", "config", "credenciais", "dados", "logs", "locks", "docs", "scripts"]
    for nome in pastas_essenciais:
        assert (RAIZ_PROJETO / nome).is_dir(), f"Pasta ausente: {nome}"


def test_arquivos_essenciais_existem():
    arquivos_essenciais = ["requirements.txt", ".gitignore", ".env.example", "README.md"]
    for nome in arquivos_essenciais:
        assert (RAIZ_PROJETO / nome).is_file(), f"Arquivo ausente: {nome}"


def test_modulo_paths_importavel():
    from src.comum import paths  # noqa: F401
    assert paths.RAIZ_PROJETO == RAIZ_PROJETO

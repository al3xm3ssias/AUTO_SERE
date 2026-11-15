"""Configuração comum dos testes: a raiz do projeto entra no caminho de importação,
para que `from src...` funcione sem precisar de PYTHONPATH."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


# ─────────────────────────────────────────────────────────────────────────────
# Troca de ano letivo recarrega módulos (src.comum.ano_letivo). Vários arquivos de teste guardam uma referência ao
# módulo (`from src.automacao import servidores as sv`) e depois a trocam com monkeypatch: se um teste de troca de ano
# deixasse módulos NOVOS no lugar, os testes seguintes enxergariam objetos diferentes dos que eles trocaram.
# Por isso, depois de CADA teste, os módulos que fixam o ano voltam a ser exatamente os objetos que eram antes.
# ─────────────────────────────────────────────────────────────────────────────
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _preservar_modulos_que_fixam_o_ano():
    from src.comum import ano_letivo
    nomes = [*ano_letivo.MODULOS_COM_ANO_FIXO, *ano_letivo.MODULOS_QUE_DEPENDEM]
    antes = {n: sys.modules.get(n) for n in nomes}
    yield
    for nome, modulo in antes.items():
        pai, _, filho = nome.rpartition(".")
        modulo_pai = sys.modules.get(pai)
        if sys.modules.get(nome) is modulo:
            continue
        if modulo is None:
            sys.modules.pop(nome, None)
            if modulo_pai is not None and hasattr(modulo_pai, filho):
                delattr(modulo_pai, filho)
        else:
            sys.modules[nome] = modulo
            if modulo_pai is not None:
                setattr(modulo_pai, filho, modulo)


# O backup automático ao fim das coletas (backup.backup_apos_coleta) gravaria zips na pasta de dados de verdade se os
# testes de coleta (com navegador de mentira) o deixassem ligado. Fica desligado em todos os testes; test_backup liga.
@pytest.fixture(autouse=True)
def _sem_backup_automatico(monkeypatch):
    monkeypatch.setenv("AUTO_SERE_BACKUP_AUTO", "0")

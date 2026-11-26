"""Coleta seletiva de alunos (só os CGMs pedidos): alunos.py (básico) e alunos_completo.py. Sem SERE: página de mentira."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.automacao import alunos as al  # noqa: E402
from src.automacao import alunos_completo as ac  # noqa: E402


class _Link:
    def __init__(self, cgm): self.cgm = cgm
    async def inner_text(self, timeout=None): return self.cgm


class _Linha:
    def __init__(self, cgm): self.cgm = cgm
    def locator(self, _): return _Link(self.cgm)


class _Linhas:
    def __init__(self, cgms): self.cgms = cgms
    async def count(self): return len(self.cgms)
    def nth(self, i): return _Linha(self.cgms[i])


class _Pagina:
    def __init__(self, cgms): self.cgms = cgms
    def locator(self, _): return _Linhas(self.cgms)
    async def wait_for_selector(self, *a, **k): return None
    async def wait_for_timeout(self, *a, **k): return None


def _preparar(monkeypatch, cgms_na_turma):
    clicados = []

    async def abrir(page, turma_id): return True

    async def voltar(page, turma_id): return None

    async def dados(page, cgm, linha=None):
        clicados.append(cgm)
        return {"CGM": cgm, "Nome": f"Aluno {cgm}"}

    async def meta(linha): return {}
    monkeypatch.setattr(al, "_abrir_turma_com_recuperacao", abrir)
    monkeypatch.setattr(al, "_voltar_para_lista_turmas", voltar)
    monkeypatch.setattr(al, "get_dados_aluno", dados)
    monkeypatch.setattr(al, "_ler_meta_linha", meta)
    return _Pagina(cgms_na_turma), clicados


def test_sem_selecao_coleta_a_turma_inteira(monkeypatch):
    pagina, clicados = _preparar(monkeypatch, ["1", "2", "3"])
    _, alunos = asyncio.run(al.get_alunos_da_turma(pagina, "T1"))
    assert clicados == ["1", "2", "3"] and [a["CGM"] for a in alunos] == ["1", "2", "3"]


def test_com_selecao_so_abre_a_ficha_dos_cgms_pedidos(monkeypatch):
    pagina, clicados = _preparar(monkeypatch, ["1", "2", "3", "4"])
    _, alunos = asyncio.run(al.get_alunos_da_turma(pagina, "T1", cgms={"2", "4"}))
    assert clicados == ["2", "4"] and [a["CGM"] for a in alunos] == ["2", "4"]       # os outros nem foram clicados


def test_normalizar_cgms():
    assert al.normalizar_cgms(None) is None and al.normalizar_cgms([]) is None and al.normalizar_cgms([" ", ""]) is None
    assert al.normalizar_cgms([" 12 ", 34]) == {"12", "34"}


def test_mesclar_substitui_so_os_coletados_e_mantem_os_demais():
    existentes = [{"CGM": "1", "v": "antigo"}, {"CGM": "2", "v": "mantido"}, {"CGM": "1", "v": "retorno antigo"}]
    r = al.mesclar_alunos(existentes, [{"CGM": "1", "v": "novo"}, {"CGM": "3", "v": "novo"}])
    assert {a["CGM"]: a["v"] for a in r} == {"1": "novo", "2": "mantido", "3": "novo"} and len(r) == 3


def test_coleta_seletiva_grava_mesclando_no_alunos_json(monkeypatch, tmp_path):
    pagina, clicados = _preparar(monkeypatch, ["1", "2", "3"])
    saida = tmp_path / "alunos.json"
    saida.write_text(json.dumps([{"CGM": "1", "Nome": "Antigo"}, {"CGM": "9", "Nome": "Fora"}]), encoding="utf-8")

    async def navegar(page): return None

    async def turmas(page): return ["T1"]
    monkeypatch.setattr(al, "navegar_por_turma", navegar)
    monkeypatch.setattr(al, "get_turmas_validas", turmas)
    r = asyncio.run(al.coletar_cadastro_completo_alunos(pagina, output_file=saida, cgms=["2", "77"]))
    gravado = json.loads(saida.read_text(encoding="utf-8"))
    assert clicados == ["2"]                                                         # 77 não está em nenhuma turma
    assert {a["CGM"] for a in gravado} == {"1", "9", "2"}                            # 1 e 9 intocados; 2 acrescentado
    assert next(a for a in gravado if a["CGM"] == "1")["Nome"] == "Antigo"
    assert [a["CGM"] for a in r] == ["1", "9", "2"] or {a["CGM"] for a in r} == {"1", "9", "2"}
    assert not list(tmp_path.glob("*.tmp"))


def test_coleta_sem_selecao_regrava_o_arquivo_inteiro(monkeypatch, tmp_path):
    pagina, _ = _preparar(monkeypatch, ["1", "2"])
    saida = tmp_path / "alunos.json"
    saida.write_text(json.dumps([{"CGM": "9"}]), encoding="utf-8")

    async def navegar(page): return None

    async def turmas(page): return ["T1"]
    monkeypatch.setattr(al, "navegar_por_turma", navegar)
    monkeypatch.setattr(al, "get_turmas_validas", turmas)
    asyncio.run(al.coletar_cadastro_completo_alunos(pagina, output_file=saida))
    assert {a["CGM"] for a in json.loads(saida.read_text(encoding="utf-8"))} == {"1", "2"}      # como sempre foi


def test_fila_do_completo_filtrada_por_cgm():
    fila = [{"cgm": "1", "turma_id": "A"}, {"cgm": "2", "turma_id": "A"}, {"cgm": "3", "turma_id": "B"}]
    assert ac.filtrar_fila_por_cgms(fila, ["2", " 3 "]) == fila[1:]
    assert ac.filtrar_fila_por_cgms(fila, None) is fila and ac.filtrar_fila_por_cgms(fila, []) is fila
    assert ac.filtrar_fila_por_cgms(fila, ["99"]) == []

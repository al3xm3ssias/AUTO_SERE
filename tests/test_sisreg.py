"""sisreg.py com um Playwright simulado (sem internet e sem o site do SISREG)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.automacao import sisreg  # noqa: E402


class _Celula:
    def __init__(self, t): self.t = t
    async def inner_text(self): return self.t


class _Linha:
    def __init__(self, textos): self.textos = textos
    async def query_selector_all(self, _sel): return [_Celula(t) for t in self.textos]


class _Pagina:
    """Responde ao CPF digitado: 'com' tem 1 encaminhamento; qualquer outro dá timeout."""
    def __init__(self, tabela_por_cpf):
        self.tabela, self.digitados, self._atual = tabela_por_cpf, [], None
    async def goto(self, _url): pass
    async def fill(self, _sel, cpf): self.digitados.append(cpf); self._atual = cpf
    async def click(self, _sel): pass
    async def wait_for_selector(self, _sel, timeout=0):
        if self._atual not in self.tabela:
            raise PlaywrightTimeoutError("sem tabela")
    async def query_selector_all(self, _sel): return [_Linha(t) for t in self.tabela[self._atual]]


def _fake_playwright(pagina):
    class _Browser:
        async def new_page(self): return pagina
        async def close(self): pass

    class _Chromium:
        async def launch(self, headless=True): return _Browser()

    class _P:
        chromium = _Chromium()

    class _Ctx:
        async def __aenter__(self): return _P()
        async def __aexit__(self, *a): return False

    return lambda: _Ctx()


def test_normalizar_cpf():
    assert sisreg.normalizar_cpf("123.456.789-00") == "12345678900"
    assert sisreg.normalizar_cpf(None) == ""


def test_cpf_com_mascara_e_consultado_sem_pontuacao(tmp_path, monkeypatch):
    entrada = tmp_path / "alunos.json"
    saida = tmp_path / "saida.json"
    entrada.write_text(json.dumps([
        {"Nome": "Com Máscara", "CGM": "1", "CPF": "111.111.111-11"},   # antes: "CPF inválido" (14 caracteres)
        {"Nome": "Sem Fila", "CGM": "2", "CPF": "22222222222"},
        {"Nome": "Curto", "CGM": "3", "CPF": "123"},
        {"Nome": "Vazio", "CGM": "4", "CPF": ""},
    ]), encoding="utf-8")
    pagina = _Pagina({"11111111111": [["01/03/2026", "Oftalmologia", "10/10/2015", "12"]]})
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(pagina))

    resultado = asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida))

    assert pagina.digitados == ["11111111111", "22222222222"]           # só os dois CPFs válidos foram consultados
    por_nome = {r["nome"]: r for r in resultado}
    assert por_nome["Com Máscara"]["encaminhamentos"][0]["procedimento"] == "Oftalmologia"
    assert por_nome["Com Máscara"]["cgm"] == "1" and "erro" not in por_nome["Com Máscara"]
    assert "Sem Fila" not in por_nome                                    # sem encaminhamento: omitido
    assert por_nome["Curto"]["erro"] == "CPF inválido" and por_nome["Vazio"]["erro"] == "CPF inválido"
    assert json.loads(saida.read_text(encoding="utf-8")) == resultado    # gravou o arquivo


def test_caminhos_padrao_seguem_o_ano_atual(tmp_path, monkeypatch):
    monkeypatch.setattr(sisreg._paths, "dados_ano_atual", lambda: tmp_path)
    (tmp_path / "alunos.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(_Pagina({})))
    assert asyncio.run(sisreg.consultar_encaminhamentos_sisreg()) == []
    assert (tmp_path / "alunos_encaminhamento.json").exists()


# ───────────── consulta parcial (cgms): só os pedidos, sem apagar o resto ─────────────

def _alunos_json(pasta):
    f = pasta / "alunos.json"
    f.write_text(json.dumps([
        {"Nome": "Ana", "CGM": "1", "CPF": "111.111.111-11"},
        {"Nome": "Beto", "CGM": "2", "CPF": "22222222222"},
        {"Nome": "Caio", "CGM": "3", "CPF": "33333333333"},
    ]), encoding="utf-8")
    return f


def _antigo(pasta):
    f = pasta / "saida.json"
    f.write_text(json.dumps([
        {"nome": "Ana", "cgm": "1", "cpf": "11111111111", "encaminhamentos": [{"procedimento": "VELHO", "data_solicitacao": "x", "data_nascimento": "x", "posicao_fila": "9"}]},
        {"nome": "Beto", "cgm": "2", "cpf": "22222222222", "encaminhamentos": [{"procedimento": "MANTIDO", "data_solicitacao": "x", "data_nascimento": "x", "posicao_fila": "1"}]},
        {"nome": "Caio (registro antigo, sem cgm)", "cpf": "33333333333", "encaminhamentos": [{"procedimento": "ANTIGO", "data_solicitacao": "x", "data_nascimento": "x", "posicao_fila": "2"}]},
    ]), encoding="utf-8")
    return f


def test_parcial_consulta_so_os_pedidos_e_preserva_os_outros(tmp_path, monkeypatch):
    entrada, saida = _alunos_json(tmp_path), _antigo(tmp_path)
    pagina = _Pagina({"11111111111": [["01/03/2026", "NOVO", "10/10/2015", "5"]]})
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(pagina))

    asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida, cgms=["1"]))

    assert pagina.digitados == ["11111111111"]                              # só a Ana foi consultada
    grav = {r["nome"]: r for r in json.loads(saida.read_text(encoding="utf-8"))}
    assert grav["Ana"]["encaminhamentos"][0]["procedimento"] == "NOVO"      # atualizada (não duplicada)
    assert grav["Beto"]["encaminhamentos"][0]["procedimento"] == "MANTIDO"  # intacto
    assert "Caio (registro antigo, sem cgm)" in grav and len(grav) == 3


def test_parcial_remove_quem_deixou_de_ter_encaminhamento(tmp_path, monkeypatch):
    entrada, saida = _alunos_json(tmp_path), _antigo(tmp_path)
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(_Pagina({})))   # Ana: nada na tabela agora
    asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida, cgms=["1"]))
    nomes = [r["nome"] for r in json.loads(saida.read_text(encoding="utf-8"))]
    assert "Ana" not in nomes and "Beto" in nomes


def test_parcial_identifica_registro_antigo_sem_cgm_pelo_cpf(tmp_path, monkeypatch):
    entrada, saida = _alunos_json(tmp_path), _antigo(tmp_path)
    pagina = _Pagina({"33333333333": [["01/03/2026", "ATUAL", "10/10/2015", "7"]]})
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(pagina))
    asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida, cgms=["3"]))
    grav = json.loads(saida.read_text(encoding="utf-8"))
    caio = [r for r in grav if r["cpf"] == "33333333333"]
    assert len(caio) == 1 and caio[0]["encaminhamentos"][0]["procedimento"] == "ATUAL" and caio[0]["cgm"] == "3"


def test_parcial_sem_arquivo_anterior_ou_com_arquivo_ruim(tmp_path, monkeypatch):
    entrada = _alunos_json(tmp_path)
    saida = tmp_path / "saida.json"
    pagina = _Pagina({"22222222222": [["01/03/2026", "X", "10/10/2015", "1"]]})
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(pagina))
    asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida, cgms=["2"]))
    assert [r["nome"] for r in json.loads(saida.read_text(encoding="utf-8"))] == ["Beto"]
    saida.write_text("{ isto nao e json", encoding="utf-8")                          # arquivo anterior corrompido
    asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida, cgms=["2"]))
    assert [r["nome"] for r in json.loads(saida.read_text(encoding="utf-8"))] == ["Beto"]


def test_parcial_sem_ninguem_nao_abre_navegador_nem_mexe_no_arquivo(tmp_path, monkeypatch):
    entrada, saida = _alunos_json(tmp_path), _antigo(tmp_path)
    antes = saida.read_text(encoding="utf-8")
    monkeypatch.setattr(sisreg, "async_playwright", lambda: (_ for _ in ()).throw(AssertionError("não deveria abrir o navegador")))
    assert asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida, cgms=["999"])) == []
    assert saida.read_text(encoding="utf-8") == antes


def test_sem_cgms_continua_consultando_todos_e_reescrevendo(tmp_path, monkeypatch):
    entrada, saida = _alunos_json(tmp_path), _antigo(tmp_path)
    pagina = _Pagina({"11111111111": [["01/03/2026", "NOVO", "10/10/2015", "5"]]})
    monkeypatch.setattr(sisreg, "async_playwright", _fake_playwright(pagina))
    asyncio.run(sisreg.consultar_encaminhamentos_sisreg(entrada, saida))
    assert pagina.digitados == ["11111111111", "22222222222", "33333333333"]
    assert [r["nome"] for r in json.loads(saida.read_text(encoding="utf-8"))] == ["Ana"]   # reescrito: só quem tem encaminhamento

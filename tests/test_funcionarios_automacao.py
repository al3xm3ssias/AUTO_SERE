"""Automação 'Funcionários / Servidores' na lista de Automações (servidores.py) + correções de robustez."""
import asyncio
import time

import pytest

from src.automacao import servidores as sv
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    monkeypatch.setattr(sv, "OUTPUT_BASICO", tmp_path / "funcionarios.json")
    monkeypatch.setattr(sv, "OUTPUT_COMPLETO", tmp_path / "funcionarios_completo.json")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    chamadas = []

    async def fake_via_login(modo):
        chamadas.append(modo)
        print(f"servidores: {modo}")
        return [{"cpf": "1"}, {"cpf": "2"}, {"cpf": "3"}]
    monkeypatch.setattr(sv, "coletar_servidores_via_login", fake_via_login)
    return create_app().test_client(), chamadas


def _esperar(c, chave="funcionarios", limite=10):
    fim = time.time() + limite
    while time.time() < fim:
        s = c.get(f"/web/api/automacoes/{chave}/status").get_json()
        if s["status"] in ("concluido", "erro", "cancelado"):
            return s
        time.sleep(0.03)
    pytest.fail("não terminou")


# ───────────── lista de Automações e registro ─────────────

def test_aparece_na_lista_logo_depois_de_turmas_e_alunos(ctx):
    c, _ = ctx
    itens = c.get("/web/api/automacoes/lista").get_json()["itens"]
    assert [i["chave"] for i in itens[:3]] == ["turmas", "alunos", "funcionarios"]
    assert itens[2]["nome"] == "Funcionários / Servidores" and "SERE" in itens[2]["descricao"]


def test_registrada_com_os_campos(ctx):
    s = reg.obter("funcionarios")
    assert s is not None and s.recursos == () and s.confirmar is False
    modo, atualizar, recomecar = s.extras()
    assert modo["nome"] == "modo" and modo["padrao"] == "completo" and modo["semVazio"] is True
    assert [o["valor"] for o in modo["opcoes"]] == ["completo", "basico"]
    assert atualizar["nome"] == "atualizar_lista" and atualizar["visivelSe"] == {"campo": "campo-modo-func", "valor": "completo"}
    assert recomecar["nome"] == "recomecar" and recomecar["visivelSe"] == atualizar["visivelSe"] and not recomecar.get("padrao")


def test_plano_padrao_e_modos(ctx):
    s = reg.obter("funcionarios")
    plano = s.planejar(Opcoes(), {}, {}, {})
    assert plano.tipo == "coroutine" and plano.funcao is sv.coletar_funcionarios_automacao
    assert plano.kwargs == {"modo": "completo", "atualizar_lista": False, "recomecar": False}
    plano = s.planejar(Opcoes(), {"modo": " BASICO "}, {}, {})
    assert plano.kwargs["modo"] == "basico"
    assert s.planejar(Opcoes(), {"modo": "completo", "atualizar_lista": True}, {}, {}).kwargs["atualizar_lista"] is True


def test_modo_invalido_no_plano(ctx):
    with pytest.raises(ValueError, match="desconhecido"):
        reg.obter("funcionarios").planejar(Opcoes(), {"modo": "rapido"}, {}, {})


# ───────────── execução pela web ─────────────

def test_executar_completo_devolve_resumo_e_nao_os_cadastros(ctx, tmp_path):
    c, chamadas = ctx
    assert c.post("/web/api/automacoes/funcionarios/executar", json={"modo": "completo"}).status_code == 200
    s = _esperar(c)
    assert s["status"] == "concluido" and chamadas == ["completo"]
    assert rotas._EXECUCOES["funcionarios"]["resultado"] == {
        "modo": "completo", "total": 3, "arquivo": str(tmp_path / "funcionarios_completo.json"), "lista_atualizada": False}
    assert "cpf" not in str(rotas._EXECUCOES["funcionarios"]["resultado"])      # CPFs não vão para a resposta
    assert any("servidores: completo" in linha for linha in s["logs"])


def test_executar_basico(ctx, tmp_path):
    c, chamadas = ctx
    c.post("/web/api/automacoes/funcionarios/executar", json={"modo": "basico"})
    s = _esperar(c)
    assert s["status"] == "concluido" and chamadas == ["basico"]
    assert rotas._EXECUCOES["funcionarios"]["resultado"]["arquivo"] == str(tmp_path / "funcionarios.json")


def test_atualizar_lista_refaz_o_basico_antes_do_completo(ctx):
    c, chamadas = ctx
    c.post("/web/api/automacoes/funcionarios/executar", json={"modo": "completo", "atualizar_lista": True})
    s = _esperar(c)
    assert s["status"] == "concluido" and chamadas == ["basico", "completo"]
    assert rotas._EXECUCOES["funcionarios"]["resultado"]["lista_atualizada"] is True


def test_atualizar_lista_nao_vale_no_modo_basico(ctx):
    c, chamadas = ctx
    c.post("/web/api/automacoes/funcionarios/executar", json={"modo": "basico", "atualizar_lista": True})
    _esperar(c)
    assert chamadas == ["basico"]


def test_modo_invalido_da_400(ctx):
    c, chamadas = ctx
    r = c.post("/web/api/automacoes/funcionarios/executar", json={"modo": "rapido"})
    assert r.status_code == 400 and "desconhecido" in r.get_json()["mensagem"] and chamadas == []


def test_falha_na_coleta_aparece_como_erro_na_tela(ctx, monkeypatch):
    c, _ = ctx
    async def quebra(modo): raise RuntimeError("Falha no login no SERE: confira o login")
    monkeypatch.setattr(sv, "coletar_servidores_via_login", quebra)
    c.post("/web/api/automacoes/funcionarios/executar", json={})
    s = _esperar(c)
    assert s["status"] == "erro" and "Falha no login no SERE" in str(s)


def test_cli_simular(ctx, capsys):
    from src.comum import cli
    assert cli.main(["funcionarios", "--modo", "basico", "--simular"]) == 0
    assert "coletar_funcionarios_automacao" in capsys.readouterr().out
    assert cli.main(["funcionarios", "--modo", "xx", "--simular"]) == 2


# ───────────── servidores.py: resumo e robustez ─────────────

def test_resumo_da_coleta(ctx, tmp_path):
    r = asyncio.run(sv.coletar_funcionarios_automacao("basico"))
    assert r == {"modo": "basico", "total": 3, "arquivo": str(tmp_path / "funcionarios.json"), "lista_atualizada": False}


def test_resumo_valida_o_modo(ctx):
    with pytest.raises(ValueError, match="basico' ou 'completo"):
        asyncio.run(sv.coletar_funcionarios_automacao("xx"))


class _Browser:
    fechado = False
    async def new_page(self): return object()
    async def close(self): _Browser.fechado = True


class _Playwright:
    async def __aenter__(self):
        class P:
            class chromium:
                @staticmethod
                async def launch(**kw): return _Browser()
        return P()
    async def __aexit__(self, *a): return False


@pytest.fixture()
def navegador_falso(monkeypatch):
    _Browser.fechado = False
    monkeypatch.setattr(sv, "async_playwright", lambda: _Playwright())


def test_falha_de_login_levanta_erro_e_fecha_o_navegador(navegador_falso, monkeypatch):
    async def login(page): return False
    monkeypatch.setattr(sv, "login_sere", login)
    with pytest.raises(RuntimeError, match="Senha do SERE"):
        asyncio.run(sv.coletar_servidores_via_login("basico"))
    assert _Browser.fechado


def test_erro_na_coleta_fecha_o_navegador(navegador_falso, monkeypatch):
    async def login(page): return True
    async def quebra(page, modo): raise ValueError("tela mudou")
    monkeypatch.setattr(sv, "login_sere", login)
    monkeypatch.setattr(sv, "coletar_servidores", quebra)
    with pytest.raises(ValueError, match="tela mudou"):
        asyncio.run(sv.coletar_servidores_via_login("completo"))
    assert _Browser.fechado


def test_caminho_feliz_devolve_a_lista_e_fecha(navegador_falso, monkeypatch):
    async def login(page): return True
    async def coleta(page, modo): return [{"cpf": "9"}]
    monkeypatch.setattr(sv, "login_sere", login)
    monkeypatch.setattr(sv, "coletar_servidores", coleta)
    assert asyncio.run(sv.coletar_servidores_via_login("basico")) == [{"cpf": "9"}]
    assert _Browser.fechado


def test_modo_invalido_nem_abre_o_navegador(navegador_falso):
    with pytest.raises(ValueError, match="basico' ou 'completo"):
        asyncio.run(sv.coletar_servidores_via_login("xx"))
    assert not _Browser.fechado


# ───────────── navegação do menu do SERE (era a causa de servidores.py não importar) ─────────────

class _PaginaMenu:
    def __init__(self, tem_menu=True):
        self.eventos, self.tem_menu = [], tem_menu

    async def query_selector(self, seletor):
        self.eventos.append(("query", seletor))
        pagina = self

        class Menu:
            async def evaluate(self, js): pagina.eventos.append(("hover", "mouseover" in js))
        return Menu() if self.tem_menu else None

    async def wait_for_timeout(self, ms): self.eventos.append(("espera", ms))
    async def click(self, seletor): self.eventos.append(("click", seletor))


def _cliques(pagina):
    return [e[1] for e in pagina.eventos if e[0] == "click"]


def test_servidores_e_funcionarios_importam():
    import importlib
    for nome in ("src.automacao.servidores", "src.automacao.funcionarios"):
        importlib.import_module(nome)                 # antes: ImportError (navegar_censo_escolar sumira de src.comum.sere_api)


def test_navegar_censo_escolar_percorre_a_rota_a_partir_do_censo():
    from src.comum.sere_api import navegar_censo_escolar
    p = _PaginaMenu()
    asyncio.run(navegar_censo_escolar(p, ("Funcionário/ Docente", "Consulta Funcionários/Docentes")))
    assert _cliques(p) == ["//div[contains(text(),'Censo Escolar')]", "//div[contains(text(),'Funcionário/ Docente')]",
                           "//div[contains(text(),'Consulta Funcionários/Docentes')]"]
    assert ("hover", True) in p.eventos and p.eventos[-1] == ("espera", 2000)


def test_navegar_relatorios_continua_igual():
    from src.comum.sere_api import navegar_relatorios
    p = _PaginaMenu()
    asyncio.run(navegar_relatorios(p, ("Histórico Escolar", "Emitir")))
    assert _cliques(p) == ["//div[contains(text(),'Relatórios')]", "//div[contains(text(),'Histórico Escolar')]",
                           "//div[contains(text(),'Emitir')]"]
    assert [e for e in p.eventos if e[0] == "espera"] == [("espera", 500), ("espera", 300), ("espera", 300), ("espera", 300), ("espera", 2000)]


def test_navegacao_sem_menu_principal_da_erro_claro():
    from src.comum.sere_api import navegar_censo_escolar, navegar_relatorios
    for funcao in (navegar_censo_escolar, navegar_relatorios):
        with pytest.raises(Exception, match="Menu principal não encontrado"):
            asyncio.run(funcao(_PaginaMenu(tem_menu=False), ("x",)))


def test_rotas_de_funcionarios_usam_o_menu_certo():
    assert sv._ROTA_CONSULTA == ("Funcionário/ Docente", "Consulta Funcionários/Docentes")
    assert sv._ROTA_CADASTRO == ("Funcionário/ Docente", "Cadastro")


def test_tela_de_funcionarios_aponta_para_uma_opcao_que_existe():
    """A tela manda 'executar pelo menu Automações': a opção precisa estar na lista."""
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'Execute "Funcionários / Servidores"' in js
    assert any(i["chave"] == "funcionarios" and i["nome"] == "Funcionários / Servidores" for i in rotas.AUTOMACOES_DISPONIVEIS)

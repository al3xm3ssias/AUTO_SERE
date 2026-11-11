"""
Cadastro "Planilhas do Drive": regras (src/comum/planilhas_registro.py), API (src/web/api/planilhas.py) e encaixe
na interface. Nada aqui fala com o Google: o cadastro só guarda links. Grava em pasta temporária.
"""
import json
from pathlib import Path

import pytest

from src.comum import configuracao, paths, planilhas_registro as pr
from src.comum.arquivos_json import ArquivoJsonCorrompidoError
from src.web.app import create_app

ID1 = "1DPyBHxA3rz-u1nxgCN9f_XosZrqyiR8zuy4ACqeGpgE"
ID2 = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE"
ID3 = "1ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
URL1 = f"https://docs.google.com/spreadsheets/d/{ID1}/edit#gid=0"
BASE = "/web/api/planilhas"


@pytest.fixture(autouse=True)
def _pastas_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")


@pytest.fixture()
def cliente():
    return create_app().test_client()


# ═════════════════════════ regras do cadastro ═════════════════════════

def test_criar_guarda_todos_os_campos_com_id_sequencial():
    a = pr.criar("  Pareceres   do Infantil ", URL1, "Pareceres do Infantil", "usada pelas professoras")
    b = pr.criar("Turmas 2027", ID2)                                           # só o ID: o link completo é montado
    assert (a["id"], a["nome"], a["link"], a["planilha_id"]) == (1, "Pareceres do Infantil", URL1, ID1)
    assert a["categoria"] == "Pareceres do Infantil" and a["observacao"] == "usada pelas professoras"
    assert a["status"] == "ativa" and a["origem"] == "manual" and a["criado_em"] == a["atualizado_em"]
    assert b["id"] == 2 and b["link"] == f"https://docs.google.com/spreadsheets/d/{ID2}/edit" and b["categoria"] == "Outras"


def test_grava_no_arquivo_do_projeto_em_dados_planilhas(tmp_path):
    pr.criar("A", URL1)
    arquivo = tmp_path / "dados" / "planilhas" / "planilhas.json"
    tabela = json.loads(arquivo.read_text(encoding="utf-8"))
    assert tabela["versao"] == 1 and tabela["proximo_id"] == 2 and tabela["itens"][0]["planilha_id"] == ID1
    assert not list(arquivo.parent.glob("*.tmp"))                              # gravação atômica não deixa temporário


def test_id_removido_nao_e_reaproveitado():
    pr.criar("A", URL1)
    pr.criar("B", ID2)
    pr.remover(2)
    assert pr.criar("C", ID3)["id"] == 3
    assert [i["id"] for i in pr.listar()["itens"]] == [1, 3]


@pytest.mark.parametrize("kw,trecho", [
    ({"nome": "", "link": URL1}, "nome da planilha"),
    ({"nome": "X", "link": ""}, "Planilha não reconhecida"),
    ({"nome": "X", "link": "lixo"}, "Planilha não reconhecida"),
    ({"nome": "X", "link": "https://exemplo.com/spreadsheets/d/" + ID1}, "planilha do Google"),
    ({"nome": "X", "link": URL1 + " depois"}, "espaços"),
    ({"nome": "X" * 251, "link": URL1}, "Nome da planilha muito longo"),
    ({"nome": "X", "link": URL1, "categoria": "C" * 61}, "Categoria muito longa"),
    ({"nome": "X", "link": URL1, "observacao": "o" * 501}, "Observação muito longa"),
    ({"nome": "X", "link": URL1, "status": "apagada"}, "Situação inválida"),
    ({"nome": "X", "link": URL1, "origem": "robo"}, "Origem inválida"),
])
def test_criar_recusa_dados_invalidos_sem_gravar(kw, trecho):
    with pytest.raises(ValueError, match=trecho):
        pr.criar(**kw)
    assert pr.listar()["total"] == 0


def test_mesma_planilha_nao_entra_duas_vezes_mesmo_com_link_diferente():
    pr.criar("Primeira", URL1)
    with pytest.raises(pr.PlanilhaDuplicada, match=r"já está cadastrada como 'Primeira' \(id 1\)"):
        pr.criar("Outra", ID1)
    assert pr.registrar_planilha_criada("Outra", ID1) is None
    assert pr.listar()["total"] == 1


def test_atualizar_muda_so_o_informado_e_atualiza_a_data(monkeypatch):
    item = pr.criar("A", URL1, "Turmas")
    monkeypatch.setattr(pr, "_agora", lambda: "2030-01-01T10:00:00")
    novo = pr.atualizar(1, nome="B", status="inativa")
    assert novo["nome"] == "B" and novo["status"] == "inativa" and novo["categoria"] == "Turmas"
    assert novo["id"] == 1 and novo["criado_em"] == item["criado_em"] and novo["atualizado_em"] == "2030-01-01T10:00:00"


def test_atualizar_sem_mudanca_nao_mexe_na_data(monkeypatch):
    pr.criar("A", URL1)
    monkeypatch.setattr(pr, "_agora", lambda: "2030-01-01T10:00:00")
    assert pr.atualizar(1, nome="A")["atualizado_em"] != "2030-01-01T10:00:00"


def test_atualizar_recusa_trocar_para_link_de_outra_planilha_e_campo_proibido():
    pr.criar("A", URL1)
    pr.criar("B", ID2)
    with pytest.raises(pr.PlanilhaDuplicada):
        pr.atualizar(2, link=ID1)
    assert pr.atualizar(1, link=URL1)["id"] == 1                               # o próprio registro não conta como repetido
    with pytest.raises(ValueError, match="não podem ser alterados: id, origem"):
        pr.atualizar(1, id=9, origem="sistema")


def test_id_inexistente_em_obter_atualizar_e_remover():
    for chamada in (lambda: pr.obter(9), lambda: pr.atualizar(9, nome="X"), lambda: pr.remover(9)):
        with pytest.raises(pr.PlanilhaNaoEncontrada, match="id 9"):
            chamada()


def _popular():
    pr.criar("Pareceres do Infantil 2026", URL1, "Pareceres do Infantil", "professoras do Infantil")
    pr.criar("Turmas 2026", ID2, "Turmas")
    pr.criar("Matrícula antiga", ID3, "Matrícula", status="inativa")


def test_busca_ignora_acento_e_maiuscula_e_olha_varios_campos():
    _popular()
    assert [i["id"] for i in pr.listar(q="MATRICULA")["itens"]] == [3]
    assert [i["id"] for i in pr.listar(q="professoras")["itens"]] == [1]       # observação
    assert [i["id"] for i in pr.listar(q=ID2[:12])["itens"]] == [2]            # pedaço do link
    assert pr.listar(q="nada disso")["total"] == 0


def test_filtros_de_status_e_categoria():
    _popular()
    assert [i["id"] for i in pr.listar(status="inativa")["itens"]] == [3]
    assert [i["id"] for i in pr.listar(categoria="pareceres do infantil")["itens"]] == [1]
    assert pr.listar(status="ativa", categoria="Matrícula")["total"] == 0
    with pytest.raises(ValueError, match="Situação inválida"):
        pr.listar(status="x")


def test_ordenacao_por_campo_e_direcao():
    _popular()
    assert [i["id"] for i in pr.listar(ordem="nome")["itens"]] == [3, 1, 2]
    assert [i["id"] for i in pr.listar(ordem="id", direcao="desc")["itens"]] == [3, 2, 1]
    assert [i["id"] for i in pr.listar(ordem="categoria")["itens"]] == [3, 1, 2]
    with pytest.raises(ValueError, match="Ordenação inválida"):
        pr.listar(ordem="senha")
    with pytest.raises(ValueError, match="Direção inválida"):
        pr.listar(direcao="lado")


def test_paginacao_carregar_mais():
    for n in range(5):
        pr.criar(f"P{n}", f"https://docs.google.com/spreadsheets/d/{'a' * 20}{n}/edit")
    p1 = pr.listar(limite=2)
    assert [i["id"] for i in p1["itens"]] == [1, 2] and p1["total"] == 5 and p1["proximo"] == 2
    p3 = pr.listar(limite=2, inicio=4)
    assert [i["id"] for i in p3["itens"]] == [5] and p3["proximo"] is None
    for ruim in ({"limite": 0}, {"limite": 201}, {"limite": "abc"}, {"inicio": -1}):
        with pytest.raises(ValueError, match="Valor inválido"):
            pr.listar(**ruim)


def test_resumo_e_categorias():
    _popular()
    assert pr.resumo() == {"total": 3, "ativas": 2, "inativas": 1}
    c = pr.categorias()
    assert c["usadas"] == ["Matrícula", "Pareceres do Infantil", "Turmas"]
    assert "Pareceres do Fundamental" in c["todas"] and "Pareceres do Fundamental" not in c["usadas"]
    assert len(c["todas"]) == len({x.casefold() for x in c["todas"]})          # sem repetir


def test_arquivo_ilegivel_nao_e_tratado_como_vazio(tmp_path):
    arquivo = tmp_path / "dados" / "planilhas" / "planilhas.json"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_text("{ isto nao e json", encoding="utf-8")
    with pytest.raises(ArquivoJsonCorrompidoError):
        pr.criar("A", URL1)
    assert arquivo.read_text(encoding="utf-8") == "{ isto nao e json"          # nada foi sobrescrito


def test_importa_uma_vez_a_lista_antiga_das_configuracoes():
    configuracao._salvar_configuracao({**configuracao.carregar_configuracao(), "google_sheets": {
        "planilha_id": ID1, "mapa_abas": {"X": "Y"}, "proximo_id": 4,
        "planilhas": [{"id": 3, "nome": "Antiga", "link": URL1, "planilha_id": ID1}]}})
    itens = pr.listar()["itens"]
    assert [(i["id"], i["nome"], i["categoria"]) for i in itens] == [(3, "Antiga", "Outras")]
    assert pr.criar("Nova", ID2)["id"] == 4                                    # o contador antigo é respeitado
    bloco = configuracao.google_sheets_config()
    assert "planilhas" not in bloco and bloco["planilha_id"] == ID1 and bloco["mapa_abas"] == {"X": "Y"}
    assert pr.listar()["total"] == 2                                           # e não importa de novo


# ═════════════════════════ API ═════════════════════════

def test_api_cadastrar_listar_editar_e_remover(cliente):
    r = cliente.post(BASE, json={"nome": "Pareceres do Infantil", "link": URL1, "categoria": "Pareceres do Infantil"})
    assert r.status_code == 201 and r.get_json()["item"]["id"] == 1
    lista = cliente.get(BASE).get_json()
    assert lista["total"] == 1 and lista["resumo"] == {"total": 1, "ativas": 1, "inativas": 0} and lista["proximo"] is None
    assert cliente.get(f"{BASE}/1").get_json()["nome"] == "Pareceres do Infantil"
    r = cliente.put(f"{BASE}/1", json={"nome": "Pareceres 2026", "status": "inativa", "id": 99})   # id é ignorado
    assert r.status_code == 200 and r.get_json()["item"]["nome"] == "Pareceres 2026" and r.get_json()["item"]["id"] == 1
    assert cliente.get(f"{BASE}?status=inativa").get_json()["total"] == 1
    assert cliente.delete(f"{BASE}/1").status_code == 200
    assert cliente.get(BASE).get_json()["total"] == 0


def test_api_codigos_de_erro(cliente):
    cliente.post(BASE, json={"nome": "A", "link": URL1})
    r = cliente.post(BASE, json={"nome": "Repetida", "link": ID1})
    assert r.status_code == 409 and "já está cadastrada" in r.get_json()["erro"]
    r = cliente.post(BASE, json={"nome": "", "link": URL1})
    assert r.status_code == 400 and "nome" in r.get_json()["erro"]
    assert cliente.post(BASE, data="isto não é json", content_type="text/plain").status_code == 400
    assert cliente.get(f"{BASE}?ordem=senha").status_code == 400
    assert cliente.get(f"{BASE}?limite=abc").status_code == 400
    for chamada in (cliente.get(f"{BASE}/9"), cliente.put(f"{BASE}/9", json={"nome": "x"}), cliente.delete(f"{BASE}/9")):
        assert chamada.status_code == 404


def test_api_busca_ordem_e_paginas(cliente):
    for n in range(3):
        cliente.post(BASE, json={"nome": f"Planilha {n}", "link": f"https://docs.google.com/spreadsheets/d/{'b' * 20}{n}/edit"})
    pagina = cliente.get(f"{BASE}?limite=2&ordem=id&dir=desc").get_json()
    assert [i["id"] for i in pagina["itens"]] == [3, 2] and pagina["proximo"] == 2
    assert cliente.get(f"{BASE}?q=planilha 1").get_json()["total"] == 1
    assert "Turmas" in cliente.get(f"{BASE}/categorias").get_json()["todas"]


def test_api_arquivo_ilegivel_responde_500_com_mensagem(cliente, tmp_path):
    arquivo = tmp_path / "dados" / "planilhas" / "planilhas.json"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_text("[[[", encoding="utf-8")
    r = cliente.get(BASE)
    assert r.status_code == 500 and "não foi alterado" in r.get_json()["erro"]


def test_cadastro_funciona_ate_vendo_um_ano_anterior(cliente, monkeypatch):
    """No modo 'somente consulta' (ano anterior) o resto do sistema bloqueia escrita; o cadastro de planilhas não."""
    monkeypatch.setattr(paths, "somente_consulta", lambda: True)
    assert cliente.post(BASE, json={"nome": "A", "link": URL1}).status_code == 201
    assert cliente.put(f"{BASE}/1", json={"nome": "B"}).status_code == 200
    assert cliente.delete(f"{BASE}/1").status_code == 200
    assert cliente.post("/web/api/configuracoes/data-corte", json={"data_corte": "01/01/2026"}).status_code == 403


# ═════════════════════════ encaixe na interface ═════════════════════════

def test_tela_esta_no_menu_na_pagina_e_no_js():
    web = Path(__file__).resolve().parents[1] / "src" / "web"
    c = create_app().test_client()
    pagina = c.get("/web").get_data(as_text=True)
    assert 'data-view="planilhas"' in pagina and 'id="sec-planilhas"' in pagina and "js/planilhas.js" in pagina
    for ident in ("pl-nova", "pl-busca", "pl-filtro-status", "pl-filtro-categoria", "pl-corpo", "pl-mais", "pl-contagem",
                  "pl-leg-ativas", "pl-leg-inativas"):
        assert f'id="{ident}"' in pagina
    js = (web / "static" / "js" / "planilhas.js").read_text(encoding="utf-8")
    assert "window.carregarPlanilhas" in js and "/web/api/planilhas" in js
    for ident in ("pl-nova", "pl-busca", "pl-filtro-status", "pl-filtro-categoria", "pl-corpo", "pl-mais"):
        assert ident in js                                                      # o JS só usa ids que existem na página
    app_js = (web / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'view === "planilhas"' in app_js and "carregarPlanilhas" in app_js and 'planilhas: "Planilhas do Drive"' in app_js

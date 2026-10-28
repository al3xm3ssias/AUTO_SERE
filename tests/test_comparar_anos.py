"""Compara anos: relatório (src.relatorios.comparar_anos), plano do registro e rota. Só lê JSONs — não toca no SERE."""
import json

import pytest
from openpyxl import load_workbook

from src.comum import paths
from src.comum.arquivos_json import ArquivoJsonCorrompidoError
from src.relatorios import comparar_anos as ca


def _al(cgm, nome, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": sit}


A = {   # 2025
    "4º Ano Integral A": [_al("111", "Ana"), _al("222", "Beto"), _al("777", "Gabi")],
    "5º Ano Integral A": [_al("333", "Caio"), _al("555", "Eli", "Transferido")],
    "3º Ano Integral B": [_al("444", "Duda")],
    "Pré II": [_al("1010", "Lia"), _al("1111", "Mel")],
    "2º Ano Integral A": [_al("999", "Ivo", "Transferido")],
}
B = {   # 2026
    "5º Ano Integral A": [_al("111", "Ana")],                                   # 4º → 5º: promovida
    "4º Ano Integral A": [_al("222", "Beto"), _al("777", "Gabi", "Transferido")],   # Beto repete; Gabi transferida
    "1º Ano Integral A": [_al("666", "Fabio"), _al("888", "Hugo", "Transferido")],
    "2º Ano Integral A": [_al("999", "Ivo")],                                    # estava transferido e voltou
    "Pré II B": [_al("1010", "Lia")],
    "Pré II": [_al("1111", "Mel")],
}


@pytest.fixture()
def r():
    return ca.comparar(A, B, "2025", "2026")


def _por_cgm(lista):
    return {x["cgm"]: x for x in lista}


# ───────────── regras de série ─────────────

@pytest.mark.parametrize("turma,serie", [("5º Ano Integral A", 5), ("3o ano B", 3), ("1° ANO", 1), ("2ª Ano", 2), ("Pré II", None)])
def test_serie_da_turma(turma, serie):
    assert ca.serie_da_turma(turma) == serie


# ───────────── cada aluno em uma categoria ─────────────

def test_continuam_com_movimento(r):
    c = _por_cgm(r.continuam)
    assert set(c) == {"111", "222", "999", "1010", "1111"}
    assert c["111"]["movimento"] == "Promovido (série seguinte)" and (c["111"]["turma_a"], c["111"]["turma_b"]) == ("4º Ano Integral A", "5º Ano Integral A")
    assert c["222"]["movimento"] == "Mesma série (repetência? verificar)"
    assert c["999"]["movimento"] == "Mesma série (repetência? verificar) — voltou: estava transferido no ano base"
    assert c["1010"]["movimento"] == "Mudou de turma" and c["1111"]["movimento"] == "Mesma turma"     # sem número de série


def test_sairam_com_motivo_provavel(r):
    s = _por_cgm(r.sairam)
    assert set(s) == {"333", "444", "555"}
    assert s["333"]["motivo"] == "Concluiu a etapa (última série da escola)"            # estava no 5º, a maior série
    assert s["444"]["motivo"] == "Verificar: saiu antes de concluir"                     # 3º ano sumiu: investigar
    assert s["555"]["motivo"] == "Já estava transferido no ano base"


def test_novos_e_transferidos(r):
    assert [x["cgm"] for x in r.novos] == ["666"] and r.novos[0]["turma_b"] == "1º Ano Integral A"
    t = _por_cgm(r.transferidos)
    assert set(t) == {"777", "888"}
    assert t["777"]["estava_em_a"] == "Sim" and t["777"]["turma_a"] == "4º Ano Integral A"
    assert t["888"]["estava_em_a"] == "Não" and t["888"]["turma_a"] == ""


def test_nenhum_aluno_em_duas_categorias_e_totais(r):
    todos = [x["cgm"] for lista in (r.continuam, r.novos, r.transferidos) for x in lista]
    assert len(todos) == len(set(todos)) == r.total_comparado == 8
    assert r.total_base == 9 and r.ultima_serie == 5
    assert (r.matriculados_base, r.matriculados_comparado) == (7, 6)
    estavam_em_a = len(r.sairam) + len(r.continuam) + sum(1 for x in r.transferidos if x["estava_em_a"] == "Sim")
    assert estavam_em_a == r.total_base                                                  # todo aluno de A tem destino: continua, saiu ou virou transferido


def test_cgm_repetido_vale_o_matriculado():
    base = {"4º Ano A": [_al("1", "Ana", "Transferido")], "5º Ano A": [_al("1", "Ana")]}
    assert ca._indexar(base)["1"]["turma"] == "5º Ano A"


def test_sem_nenhuma_serie_nao_aplica_conclusao():
    r = ca.comparar({"Pré I": [_al("1", "Ana")]}, {}, "2025", "2026")
    assert r.ultima_serie is None and r.sairam[0]["motivo"] == "Verificar: saiu antes de concluir"


# ───────────── planilha ─────────────

def test_planilha_tem_uma_aba_por_categoria_e_os_alunos(r, tmp_path):
    destino = ca.gerar_planilha(r, tmp_path / "saida" / "comparacao.xlsx")
    assert destino.exists() and not list(destino.parent.glob("*.tmp"))
    wb = load_workbook(destino)
    assert wb.sheetnames == ["Resumo", "Continuam", "Saíram", "Novos", "Transferidos"]
    assert [c.value for c in wb["Continuam"][1]] == ["CGM", "Nome", "Turma 2025", "Situação 2025", "Turma 2026", "Situação 2026", "Movimento"]
    assert wb["Continuam"].max_row == 1 + len(r.continuam) and wb["Saíram"].max_row == 1 + len(r.sairam)
    resumo = {linha[0].value: linha[1].value for linha in wb["Resumo"].iter_rows(min_row=3) if linha[0].value}
    assert resumo["Última série da escola considerada"] == "5º ano" and resumo["Novos em 2026"] == 1
    assert resumo["Transferidos em 2026"] == 2


# ───────────── leitura dos anos e execução ─────────────

@pytest.fixture()
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path)
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2026")
    for ano, turmas in (("2025", A), ("2026", B)):
        (tmp_path / ano).mkdir()
        (tmp_path / ano / "turmas.json").write_text(json.dumps(turmas, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "backup").mkdir()
    (tmp_path / "2024").mkdir()                                                         # ano sem turmas.json: não conta
    return tmp_path


def test_anos_com_turmas_ignora_pastas_que_nao_servem(dados):
    assert ca.anos_com_turmas() == ["2025", "2026"]


def test_executar_grava_a_planilha_na_pasta_do_ano_comparado_e_mostra_o_resumo(dados):
    linhas = []
    r = ca.executar_compara_anos("2025", "2026", log=linhas.append)
    arquivo = dados / "2026" / "comparacao_turmas_2025_2026.xlsx"
    assert arquivo.exists() and r.ano_comparado == "2026"
    saida = "\n".join(linhas)
    assert "COMPARAÇÃO DE TURMAS: 2025 → 2026" in saida and "Planilha salva" in saida and "Novos em 2026: 1" in saida


def test_json_ilegivel_e_erro_claro_e_nao_gera_planilha(dados):
    (dados / "2025" / "turmas.json").write_text("{ isto nao e json", encoding="utf-8")
    with pytest.raises(ArquivoJsonCorrompidoError):
        ca.executar_compara_anos("2025", "2026", log=lambda _l: None)
    assert not list((dados / "2026").glob("comparacao*"))


def test_nao_altera_os_turmas_json(dados):
    antes = {a: (dados / a / "turmas.json").read_bytes() for a in ("2025", "2026")}
    ca.executar_compara_anos("2025", "2026", log=lambda _l: None)
    assert {a: (dados / a / "turmas.json").read_bytes() for a in ("2025", "2026")} == antes


# ───────────── pela API (registro) ─────────────

@pytest.fixture()
def api(dados, monkeypatch):
    from src.web.api import rotas
    from src.web.app import create_app
    monkeypatch.setattr(rotas, "_dados_dir", lambda: dados / "2026")
    planos = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: planos.append((chave, plano)))
    return create_app().test_client(), planos


def _post(cliente, **p):
    return cliente.post("/web/api/automacoes/compara_anos/executar", json=p)


def test_campos_listam_os_anos_que_existem_com_padrao_ano_anterior_e_atual(api):
    cliente, _ = api
    info = cliente.get("/web/api/automacoes/compara_anos/componentes").get_json()
    campos = {e["nome"]: e for e in info["extras"]}
    assert [o["valor"] for o in campos["ano_base"]["opcoes"]] == ["2025", "2026"]
    assert campos["ano_base"]["padrao"] == "2025" and campos["ano_comparado"]["padrao"] == "2026"
    assert info["recursos"] == [] and not info["confirmar"]                              # só lê: sem confirmação


def test_executar_monta_o_plano(api):
    cliente, planos = api
    assert _post(cliente, ano_base="2025", ano_comparado="2026").status_code == 200
    chave, plano = planos[0]
    assert chave == "compara_anos" and plano.tipo == "sync" and plano.funcao is ca.executar_compara_anos
    assert plano.kwargs == {"ano_base": "2025", "ano_comparado": "2026"}


@pytest.mark.parametrize("payload,trecho", [
    ({}, "Escolha o ano base"),
    ({"ano_base": "2026", "ano_comparado": "2025"}, "anterior"),
    ({"ano_base": "2026", "ano_comparado": "2026"}, "anterior"),
    ({"ano_base": "2024", "ano_comparado": "2026"}, "dados/2024/turmas.json"),
])
def test_escolhas_invalidas_sao_recusadas(api, payload, trecho):
    cliente, planos = api
    r = _post(cliente, **payload)
    assert r.status_code == 400 and trecho in r.get_json()["mensagem"] and planos == []


def test_com_um_so_ano_explica_onde_colocar_o_outro(api, dados):
    cliente, planos = api
    (dados / "2025" / "turmas.json").unlink()
    r = _post(cliente, ano_base="2025", ano_comparado="2026")
    msg = r.get_json()["mensagem"]
    assert r.status_code == 400 and "só encontrei o turmas.json de 2026" in msg and "dados/2025/turmas.json" in msg and planos == []

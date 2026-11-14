"""Previsão do próximo ano: nome do arquivo previsao_alunos_<ano>.json, migração do nome antigo e a lista
rematriculados + alunos novos da pré-matrícula (src/comum/previsao.py, rota /web/api/previsao)."""
import json
import sys
import types

import pytest

from src.comum import arquivos_json, paths
from src.comum import previsao as pv


def _gravar(pasta, nome, conteudo):
    (pasta / nome).write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")


def _cad(cpf, nome, nasc="05/03/2021", situacao="", turma="Infantil IV", **extra):
    return {"cpf": cpf, "tr_id": "T" + cpf, "nome_aluno": nome, "data_nascimento": nasc, "nome_responsavel": "RITA LIMA",
            "telefone": "(42) 99999-0000",
            "escolas_escolhidas": {"turma": turma, "opcoes": [{"escola": "ESCOLA ALVO", "situacao": situacao}]}, **extra}


def _fila(cpf, nome, turma="Infantil IV", **extra):
    return {"pos": "1", "nome": nome, "cpf": cpf, "tr_id": "T" + cpf, "presente_na_ultima_coleta": True, **extra}


# ───────────── nome do arquivo e migração ─────────────

def test_nome_do_arquivo_usa_o_ano_letivo_da_previsao():
    assert pv.nome_arquivo(2027) == "previsao_alunos_2027.json"
    assert pv.nome_arquivo("2028") == "previsao_alunos_2028.json"
    assert pv.nome_arquivo_antigo(2027) == "pre_matricula_2027.json"


def test_migra_o_nome_antigo_sem_mexer_no_conteudo(tmp_path):
    antigo = tmp_path / "pre_matricula_2027.json"
    antigo.write_bytes('{"cadastros": {"1": {"nome_aluno": "JOÃO"}}}'.encode("utf-8"))
    bytes_antes = antigo.read_bytes()
    novo = pv.migrar_nome_antigo(tmp_path, 2027)
    assert novo == tmp_path / "previsao_alunos_2027.json" and not antigo.exists()
    assert novo.read_bytes() == bytes_antes


def test_nao_migra_se_o_novo_ja_existe_e_o_antigo_fica_para_conferencia(tmp_path):
    _gravar(tmp_path, "pre_matricula_2027.json", {"cadastros": {"a": {}}})
    _gravar(tmp_path, "previsao_alunos_2027.json", {"cadastros": {"b": {}}})
    assert pv.migrar_nome_antigo(tmp_path, 2027) is None
    assert (tmp_path / "pre_matricula_2027.json").exists()
    assert list(pv.carregar_previsao_alunos(tmp_path, 2027)["cadastros"]) == ["b"]


def test_sem_nenhum_dos_dois_nada_acontece(tmp_path):
    assert pv.migrar_nome_antigo(tmp_path, 2027) is None
    assert pv.carregar_previsao_alunos(tmp_path, 2027) == {}


def test_o_pre_matricula_json_do_ano_em_uso_nao_muda_de_nome(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "src.comum.navegador", types.ModuleType("src.comum.navegador"))
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)
    monkeypatch.setattr(paths, "ano_atual", lambda: 2026)
    from src.automacao import pre_matricula as pm
    _gravar(tmp_path, "pre_matricula_2027.json", {"turmas_intencao": {}, "cadastros": {}})
    token = pm.definir_alvo("atual")
    try:
        assert pm.caminho_pre_matricula() == tmp_path / "pre_matricula.json"
    finally:
        pm._ALVO.reset(token)
    token = pm.definir_alvo("proximo")
    try:
        assert pm.caminho_pre_matricula() == tmp_path / "previsao_alunos_2027.json"
        assert not (tmp_path / "pre_matricula_2027.json").exists() and (tmp_path / "previsao_alunos_2027.json").exists()
    finally:
        pm._ALVO.reset(token)


# ───────────── a previsão ─────────────

def test_junta_rematriculados_e_novos_da_pre_matricula(tmp_path):
    _gravar(tmp_path, "rematriculas_sucesso.json", [
        {"cgm": "100", "nome": "ANA LIMA", "turma": "Infantil IV A", "data_nascimento": "01/02/2020"},
        {"cgm": "101", "nome": "BETO SOUZA", "turma": "1º Ano A", "data_nascimento": "10/05/2019"}])
    _gravar(tmp_path, "previsao_alunos_2027.json", {
        "turmas_intencao": {"Infantil IV": [_fila("111", "CAIO PINTO"), _fila("222", "DORA REIS")]},
        "cadastros": {"111": _cad("111", "CAIO PINTO"), "222": _cad("222", "DORA REIS", situacao="MATRICULADO")}})
    p = pv.montar_previsao(tmp_path, 2027)
    assert p["ano"] == 2027 and p["arquivo"] == "previsao_alunos_2027.json" and p["arquivo_existe"] and p["avisos"] == []
    assert p["contagem"] == {"total": 4, "rematriculados": 2, "novos": 2, "novos_matriculados": 1, "novos_pendentes": 1}
    por_nome = {l["nome"]: l for l in p["linhas"]}
    assert por_nome["ANA LIMA"]["tipo"] == "rematriculado" and por_nome["ANA LIMA"]["cgm"] == "100"
    assert por_nome["CAIO PINTO"]["tipo"] == "novo" and por_nome["CAIO PINTO"]["situacao"] == "pendente"
    assert por_nome["DORA REIS"]["situacao"] == "matriculado" and por_nome["DORA REIS"]["turma"] == "Infantil IV"


def test_cancelados_ficam_de_fora_e_cadastro_refeito_em_outra_escola_tambem(tmp_path):
    _gravar(tmp_path, "previsao_alunos_2027.json", {
        "turmas_intencao": {"Infantil IV": [_fila("111", "A"), _fila("222", "B"), _fila("333", "C")]},
        "cadastros": {"111": _cad("111", "A", situacao="CANCELADO. MOTIVO: X"),
                      "222": _cad("222", "B", cadastro_refeito_outra_escola=True),
                      "333": _cad("333", "C")}})
    assert [l["nome"] for l in pv.montar_previsao(tmp_path, 2027)["linhas"]] == ["C"]


def test_quem_esta_nas_duas_fontes_conta_uma_vez_como_rematriculado(tmp_path):
    _gravar(tmp_path, "rematriculas_sucesso.json", [
        {"cgm": "100", "nome": "Ana Lima", "turma": "Infantil V A", "data_nascimento": "01/02/2020"},
        {"cgm": "101", "nome": "Beto Souza", "turma": "1º Ano A", "data_nascimento": "10/05/2019"}])
    _gravar(tmp_path, "previsao_alunos_2027.json", {
        "turmas_intencao": {},
        "cadastros": {
            "111": _cad("111", "ANA LIMA", nasc="01/02/2020"),                                                    # mesmo nome + nascimento
            "222": _cad("222", "BETO S", nasc="10/05/2019", vinculo_base_abc={"cgm": "101", "escola": "X"}),      # mesmo CGM
            "333": _cad("333", "ANA LIMA", nasc="09/09/2021")}})                                                  # homônima, outro nascimento
    p = pv.montar_previsao(tmp_path, 2027)
    assert p["contagem"]["rematriculados"] == 2 and p["contagem"]["novos"] == 1
    assert [l["nascimento"] for l in p["linhas"] if l["tipo"] == "novo"] == ["09/09/2021"]
    assert any("contados só como rematriculados" in a for a in p["avisos"])


def test_tentativa_antiga_substituida_nao_vale_e_o_cpf_nao_duplica(tmp_path):
    _gravar(tmp_path, "previsao_alunos_2027.json", {
        "turmas_intencao": {
            "Infantil IV": [_fila("111", "A", substituido_por_nova_tentativa=True, turma_da_tentativa_atual="Infantil V")],
            "Infantil V": [_fila("111", "A")]},
        "cadastros": {"111": _cad("111", "A", turma="Infantil V")}})
    linhas = pv.montar_previsao(tmp_path, 2027)["linhas"]
    assert len(linhas) == 1 and linhas[0]["turma"] == "Infantil V"


def test_saiu_da_fila_sem_confirmacao_nao_entra_mas_matriculado_confirmado_entra(tmp_path):
    saiu = _fila("111", "SAIU", presente_na_ultima_coleta=False, situacao="Cancelado", motivo_cancelamento="CANCELADO VIA SISTEMA/RESPONSAVEL")
    chamado = _fila("222", "CHAMADO", presente_na_ultima_coleta=False, situacao="MATRICULADO")
    _gravar(tmp_path, "previsao_alunos_2027.json", {
        "turmas_intencao": {"Infantil IV": [saiu, chamado, _fila("333", "FICA")]}, "cadastros": {}})
    p = pv.montar_previsao(tmp_path, 2027)
    assert {l["nome"]: l["situacao"] for l in p["linhas"]} == {"CHAMADO": "matriculado", "FICA": "pendente"}


def test_cadastro_pendente_de_quem_saiu_da_fila_nao_conta(tmp_path):
    _gravar(tmp_path, "previsao_alunos_2027.json", {
        "turmas_intencao": {"Infantil IV": [_fila("111", "A", presente_na_ultima_coleta=False, situacao="Cancelado",
                                                   motivo_cancelamento="CANCELADO VIA SISTEMA/RESPONSAVEL")]},
        "cadastros": {"111": _cad("111", "A")}})
    assert pv.montar_previsao(tmp_path, 2027)["linhas"] == []


def test_novo_que_ja_e_aluno_da_escola_recebe_o_aviso(tmp_path):
    _gravar(tmp_path, "turmas.json", {"Infantil V A": [{"CGM": "555", "Nome": "Caio Pinto", "Data Nasc.": "05/03/2021"}]})
    _gravar(tmp_path, "previsao_alunos_2027.json", {"turmas_intencao": {}, "cadastros": {"111": _cad("111", "CAIO PINTO")}})
    p = pv.montar_previsao(tmp_path, 2027)
    assert p["linhas"][0]["tipo"] == "novo" and p["linhas"][0]["ja_e_aluno"] is True
    assert any("já constam como alunos" in a for a in p["avisos"])


def test_sem_arquivos_devolve_vazio_com_avisos_claros(tmp_path):
    p = pv.montar_previsao(tmp_path, 2027)
    assert p["linhas"] == [] and not p["arquivo_existe"] and not p["rematriculados_existe"]
    assert len(p["avisos"]) == 2 and "previsao_alunos_2027.json" in p["avisos"][0]


def test_arquivo_ilegivel_levanta_erro_e_nao_e_alterado(tmp_path):
    (tmp_path / "previsao_alunos_2027.json").write_text("{quebrado", encoding="utf-8")
    with pytest.raises(arquivos_json.ArquivoJsonCorrompidoError):
        pv.montar_previsao(tmp_path, 2027)
    assert (tmp_path / "previsao_alunos_2027.json").read_text(encoding="utf-8") == "{quebrado"


def test_nome_antigo_so_com_pre_matricula_2027_tambem_entra_na_previsao(tmp_path):
    _gravar(tmp_path, "pre_matricula_2027.json", {"turmas_intencao": {}, "cadastros": {"111": _cad("111", "CAIO PINTO")}})
    p = pv.montar_previsao(tmp_path, 2027)
    assert [l["nome"] for l in p["linhas"]] == ["CAIO PINTO"] and (tmp_path / "previsao_alunos_2027.json").exists()


# ───────────── rota ─────────────

@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    from src.web.api import rotas
    from src.web.app import create_app
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    return create_app().test_client()


def test_rota_previsao_usa_o_ano_seguinte_e_traz_cartoes(cliente, tmp_path):
    _gravar(tmp_path, "rematriculas_sucesso.json", [{"cgm": "100", "nome": "ANA LIMA", "turma": "1º Ano A", "data_nascimento": "01/02/2020"}])
    _gravar(tmp_path, "previsao_alunos_2027.json", {"turmas_intencao": {}, "cadastros": {"111": _cad("111", "CAIO PINTO")}})
    r = cliente.get("/web/api/previsao").get_json()
    assert r["ano"] == 2027 and r["contagem"]["total"] == 2
    assert [c["valor"] for c in r["cartoes"]] == [2, 1, 1] and r["cartoes"][0]["label"] == "Previsão 2027"


def test_rota_previsao_com_arquivo_ilegivel_responde_500_com_mensagem(cliente, tmp_path):
    (tmp_path / "rematriculas_sucesso.json").write_text("[", encoding="utf-8")
    r = cliente.get("/web/api/previsao")
    assert r.status_code == 500 and "ilegível" in r.get_json()["erro"]


def test_pagina_tem_o_modulo_previsao_no_menu(cliente):
    html = cliente.get("/web").get_data(as_text=True)
    assert 'data-view="previsao"' in html and 'id="sec-previsao"' in html and "js/previsao.js" in html
    assert "Previsão 2027" in html

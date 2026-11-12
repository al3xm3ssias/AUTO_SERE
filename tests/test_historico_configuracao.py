"""Histórico das execuções e mapa das configurações de cada script (tela única da automação)."""
import json
import time

import pytest

from src.comum import configuracoes_scripts as cfgs
from src.comum import historico_execucoes as hist
from src.comum import registro_scripts as reg
from src.web.api import rotas
from src.web.app import create_app


# ───────────────────────────── histórico (módulo) ─────────────────────────────

LOGS = [
    "Iniciando",
    "✅ Ana (3000000001) enviada",
    "[OK] Beto enviado",
    "❌ Caio: documento recusado",
    "[ERRO] Duda: sessão expirou",
    "⚠️ Edu sem CPF",
    "linha comum sem marcador",
]


def _registro(chave="validar", status="concluido", logs=LOGS, erro=None, opcoes=None):
    return hist.montar_registro(chave, "Validar documentos", status=status, logs=list(logs), erro=erro,
                                iniciado_t=time.time() - 75, terminou_t=time.time(), opcoes=opcoes)


def test_classifica_o_que_deu_certo_errado_e_avisos():
    r = hist.classificar_logs(LOGS)
    assert r["totais"] == {"deu_certo": 2, "deu_errado": 2, "avisos": 1}
    assert any("Ana" in x for x in r["deu_certo"]) and any("Duda" in x for x in r["deu_errado"])
    assert not any("comum" in x for x in r["deu_certo"] + r["deu_errado"] + r["avisos"])


def test_resultado_final_por_situacao():
    assert _registro()["resultado"] == hist.RESULTADO_PARCIAL                 # terminou, mas algo falhou
    assert _registro(logs=["✅ tudo certo"])["resultado"] == hist.RESULTADO_OK
    assert _registro(status="erro", erro="ValueError: x")["resultado"] == hist.RESULTADO_FALHOU
    assert _registro(status="cancelado")["resultado"] == hist.RESULTADO_CANCELADO


def test_excecao_do_script_entra_em_deu_errado_na_frente():
    r = _registro(status="erro", logs=["✅ a"], erro="RuntimeError: caiu")
    assert r["deu_errado"][0] == "RuntimeError: caiu"
    assert r["totais"]["deu_errado"] == 1


def test_opcoes_nao_guardam_segredos():
    r = _registro(opcoes={"turmas": ["5A"], "modo_teste": True, "senha_rco": "123", "token_x": "abc",
                          "automacao": "validar", "objeto": object()})
    assert r["opcoes"] == {"turmas": ["5A"], "modo_teste": True}


def test_salvar_listar_obter_e_limpar(tmp_path):
    a, b = _registro(), _registro(logs=["✅ ok"])
    hist.salvar(tmp_path, a)
    hist.salvar(tmp_path, b)
    lista = hist.listar(tmp_path, "validar")
    assert [x["id"] for x in lista] == [b["id"], a["id"]]                     # mais nova primeiro
    assert "log" not in lista[0] and "deu_certo" not in lista[0]              # a lista é só o resumo
    assert hist.obter(tmp_path, "validar", a["id"])["deu_errado"]
    assert hist.obter(tmp_path, "validar", "nao-existe") is None
    assert hist.estatisticas(tmp_path, "validar")["total"] == 2
    assert hist.limpar(tmp_path, "validar") == 2
    assert hist.listar(tmp_path, "validar") == []


def test_historico_e_por_automacao_e_aparado_no_limite(tmp_path, monkeypatch):
    monkeypatch.setattr(hist, "MAX_EXECUCOES", 3)
    for i in range(5):
        hist.salvar(tmp_path, _registro(logs=[f"✅ rodada {i}"]))
    hist.salvar(tmp_path, _registro(chave="limpeza"))
    assert hist.estatisticas(tmp_path, "validar")["total"] == 3
    assert hist.estatisticas(tmp_path, "limpeza")["total"] == 1


def test_linha_quebrada_no_arquivo_nao_derruba_o_resto(tmp_path):
    hist.salvar(tmp_path, _registro())
    arquivo = tmp_path / hist.NOME_PASTA / "validar.jsonl"
    arquivo.write_text(arquivo.read_text(encoding="utf-8") + '{"quebrada": \n', encoding="utf-8")
    assert len(hist.listar(tmp_path, "validar")) == 1


# ───────────────────────────── mapa das configurações ─────────────────────────────

def test_todo_script_registrado_declara_as_suas_configuracoes():
    sem_mapa = [k for k, s in reg.REGISTRO.items() if s.configs is None]
    assert not sem_mapa, f"Script(s) sem mapa de configurações (configs=): {sem_mapa}"


def test_so_usa_ids_que_existem_no_catalogo():
    for chave, script in reg.REGISTRO.items():
        desconhecidos = set(script.configs) - set(cfgs.CATALOGO)
        assert not desconhecidos, f"{chave} usa configuração inexistente: {desconhecidos}"
    assert set(reg.CONFIGS_DOS_SCRIPTS) <= set(reg.REGISTRO)


def test_descrever_nunca_levanta_e_nao_vaza_segredo(monkeypatch):
    from src.comum import credenciais
    monkeypatch.setattr(credenciais, "SENHA", "SEGREDO-123")
    monkeypatch.setattr(credenciais, "LOGIN", "12345678900")
    for chave, script in reg.REGISTRO.items():
        itens = cfgs.descrever(script.configs)
        assert [i["id"] for i in itens] == list(script.configs)
        assert "SEGREDO-123" not in json.dumps(itens) and "12345678900" not in json.dumps(itens)


def test_script_novo_pode_declarar_configs_na_propria_chamada():
    s = reg.Script("x", (), lambda *a: None, configs=("ano_letivo",))
    assert s.configs == ("ano_letivo",)


# ───────────────────────────── rotas ─────────────────────────────

@pytest.fixture()
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


def _esperar_fim(chave, limite=5.0):
    fim = time.time() + limite
    while time.time() < fim:
        with rotas._EXECUCOES_LOCK:
            if rotas._EXECUCOES[chave]["status"] != "executando":
                return rotas._EXECUCOES[chave]["status"]
        time.sleep(0.02)
    raise AssertionError("a execução não terminou")


def test_execucao_que_termina_vai_para_o_historico(cli):
    def trabalho():
        print("✅ Ana enviada")
        print("❌ Caio recusado")
    rotas._OPCOES_PENDENTES["backup"] = {"turmas": ["5A"], "senha_x": "nao-gravar"}
    rotas._rodar_funcao_sincrona_em_thread("backup", trabalho)
    assert _esperar_fim("backup") == "concluido"

    h = cli.get("/web/api/automacoes/backup/historico").get_json()
    assert h["resumo"]["total"] == 1 and h["resumo"]["parcial"] == 1
    ex = h["execucoes"][0]
    assert ex["totais"]["deu_certo"] == 1 and ex["totais"]["deu_errado"] == 1 and ex["resultado"] == "parcial"

    det = cli.get(f"/web/api/automacoes/backup/historico/{ex['id']}").get_json()
    assert any("Ana" in x for x in det["deu_certo"]) and any("Caio" in x for x in det["deu_errado"])
    assert det["opcoes"] == {"turmas": ["5A"]}                    # sem a senha


def test_execucao_com_erro_fica_registrada_como_falhou(cli):
    def trabalho():
        raise RuntimeError("SERE fora do ar")
    rotas._rodar_funcao_sincrona_em_thread("backup", trabalho)
    assert _esperar_fim("backup") == "erro"
    ex = cli.get("/web/api/automacoes/backup/historico").get_json()["execucoes"][0]
    assert ex["resultado"] == "falhou" and "SERE fora do ar" in ex["erro"]


def test_o_status_so_vira_concluido_depois_de_gravar_o_historico(cli):
    rotas._rodar_funcao_sincrona_em_thread("backup", lambda: print("✅ x"))
    _esperar_fim("backup")
    assert cli.get("/web/api/automacoes/backup/historico").get_json()["resumo"]["total"] == 1


def test_apagar_historico_e_404_para_automacao_inexistente(cli):
    rotas._rodar_funcao_sincrona_em_thread("backup", lambda: print("✅ x"))
    _esperar_fim("backup")
    r = cli.delete("/web/api/automacoes/backup/historico").get_json()
    assert r["apagadas"] == 1
    assert cli.get("/web/api/automacoes/backup/historico").get_json()["execucoes"] == []
    for rota in ("historico", "configuracao"):
        assert cli.get(f"/web/api/automacoes/nao_existe/{rota}").status_code == 404
    assert cli.delete("/web/api/automacoes/nao_existe/historico").status_code == 404
    assert cli.get("/web/api/automacoes/backup/historico/xyz").status_code == 404


def test_configuracao_mapeia_execucao_flags_e_sistema(cli):
    c = cli.get("/web/api/automacoes/transferidos_gerar/configuracao").get_json()
    assert c["confirma_antes"] is True
    assert [o["id"] for o in c["opcoes_da_execucao"]] == ["teste"]
    nomes_campos = {x["id"] for x in c["campos_proprios"]}
    assert {"documentos", "alterar", "data_corte", "simulacao"} <= nomes_campos
    ids = [i["id"] for i in c["sistema"]]
    assert {"data_corte_transferidos", "observacao_historico", "pasta_digitalizacao", "credenciais_sere"} <= set(ids)
    sere = next(i for i in c["sistema"] if i["id"] == "credenciais_sere")
    assert sere["valor"] in ("configurada", "não configurada") and sere["tela"] == "senha_sere"

    analisa = cli.get("/web/api/automacoes/analisa_sere/configuracao").get_json()
    assert any(f["flag"] == "--rapido" for f in analisa["flags"])


def test_toda_automacao_da_lista_tem_configuracao_e_historico(cli):
    for item in rotas.AUTOMACOES_DISPONIVEIS:
        if item["chave"] in rotas.AUTOMACOES_NAO_IMPLEMENTADAS:
            continue
        assert cli.get(f"/web/api/automacoes/{item['chave']}/configuracao").status_code == 200, item["chave"]
        assert cli.get(f"/web/api/automacoes/{item['chave']}/historico").status_code == 200, item["chave"]

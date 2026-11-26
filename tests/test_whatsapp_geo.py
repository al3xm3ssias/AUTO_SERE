"""WhatsApp: mensagem em massa para os Direcionados GEO (sere_sisgea_<ano+1>.json). Sem rede."""
import json

import pytest

from src.comum import direcionados_geo as geo
from src.servicos.whatsapp import fila as f

# reaproveita as fixtures (amb, cli, ...) da fila
from tests.test_whatsapp_fila import amb, cli  # noqa: F401
from src.comum import paths

N1, N2 = "(42) 99999-1111", "(42) 99999-2222"


def _aluno(cgm, nome, resp, fone, confirmada=False, situacao="presente", etapa="Infantil - 4-6 anos"):
    return {"cgm": cgm, "nome": nome, "nome_responsavel": resp, "fone_responsavel": fone, "etapa": etapa,
            "matricula_confirmada": confirmada, "matricula_texto": "Confirmada" if confirmada else "Não confirmada",
            "turma": None, "situacao_lista": situacao, "estabelecimento_destino": "JUDITH M SILVEIRA,E M PROFA-EI EF"}


def _gravar(*alunos):
    dados = {"ano_letivo": 2027, "periodo": "2027-1", "coleta_completa": True, "total_na_lista": len(alunos),
             "alunos": list(alunos)}
    (paths.dados_ano_atual() / "sere_sisgea_2027.json").write_text(json.dumps(dados), encoding="utf-8")


def test_primeiro_nome_em_titulo():
    assert geo.primeiro_nome("MARIA DA SILVA") == "Maria" and geo.primeiro_nome("") == "" and geo.primeiro_nome(None) == ""


def test_alunos_para_mensagem_exige_arquivo_e_ignora_ausentes(amb):  # noqa: F811
    with pytest.raises(ValueError, match="sere_sisgea_2027.json"):
        geo.alunos_para_mensagem(paths.dados_ano_atual(), 2027)
    _gravar(_aluno("1", "ANA", "MARIA SOUZA", N1), _aluno("2", "BETO", "JOAO", N2, situacao="ausente"))
    r = geo.alunos_para_mensagem(paths.dados_ano_atual(), 2027)
    assert [a["id"] for a in r["alunos"]] == ["1"] and r["arquivo"] == "sere_sisgea_2027.json"


def test_rota_geo_lista_e_poe_na_fila_com_marcadores_trocados(cli, amb):  # noqa: F811
    _gravar(_aluno("1", "ANA LIMA", "MARIA SOUZA", N1), _aluno("2", "BETO LIMA", "JOAO", ""),
            _aluno("3", "CAIO LIMA", "LUCIA", N2, confirmada=True))
    d = cli.get("/web/api/whatsapp/fila/geo").get_json()
    assert d["ano"] == 2027 and d["modelo_padrao"] == "geo_confirmar_interesse"
    assert {a["id"]: (a["tem_telefone"], a["matricula_confirmada"]) for a in d["alunos"]} == {
        "1": (True, False), "2": (False, False), "3": (True, True)}
    r = cli.post("/web/api/whatsapp/fila/do-geo", json={"ids": ["1", "2"]})
    res = r.get_json()
    assert r.status_code == 200 and res["resultado"]["adicionados"] == 1 and res["resultado"]["sem_telefone"] == ["BETO LIMA"]
    item = f.obter_fila()._ler()["itens"][0]
    assert item["origem"] == "geo" and "$" not in item["texto"]
    assert "Olá, Maria!" in item["texto"] and "ANA LIMA" in item["texto"] and "2027" in item["texto"]
    assert "outra unidade escolar" in item["texto"]
    # repetir o mesmo envio não duplica
    assert cli.post("/web/api/whatsapp/fila/do-geo", json={"ids": ["1"]}).get_json()["resultado"]["duplicados"] == 1


def test_rota_geo_erros(cli, amb):  # noqa: F811
    assert cli.get("/web/api/whatsapp/fila/geo").status_code == 400          # sem arquivo
    _gravar(_aluno("1", "ANA", "MARIA", N1))
    assert cli.post("/web/api/whatsapp/fila/do-geo", json={"ids": []}).status_code == 400
    assert cli.post("/web/api/whatsapp/fila/do-geo", json={"ids": ["1"], "modelo_id": "comunicado"}).status_code == 400
    r = cli.post("/web/api/whatsapp/fila/do-geo", json={"ids": ["1"], "texto": "Oi $ALUNO da $TURMA"}).get_json()
    assert r["resultado"]["adicionados"] == 0 and "$TURMA" in r["resultado"]["invalidos"][0]["erro"]   # GEO não tem turma

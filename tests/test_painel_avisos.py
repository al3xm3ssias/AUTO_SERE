"""Avisos da home (src/comum/painel_avisos.py): criação sem duplicar, andamento, resolução e API."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import painel_avisos as pa  # noqa: E402
from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402

EV = {"cgm": "1001", "nome": "Bia Souza", "turma": "5º Ano A", "motivo": "situacao_mudou", "data_transferencia": "10/11/2026"}


def _grava(pasta, nome, dados):
    (pasta / nome).write_text(json.dumps(dados), encoding="utf-8")


def _reg_transferido(emitidos=True, id_matricula="M-1", data="10/11/2026"):
    doc = {"emitido_em": "2026-11-10" if emitidos else None}
    return {"nome": "Bia Souza", "turma": "5º Ano A", "guia": doc, "historico": dict(doc), "parecer": {},
            "data_transferencia": data, "retorno": None, **({"id_matricula": id_matricula} if id_matricula else {})}


def test_cria_um_aviso_de_transferencia_e_nao_duplica(tmp_path):
    assert pa.registrar_da_comparacao([EV], tmp_path) == {"criados": 1, "ja_existiam": 0, "ignorados": 0}
    assert pa.registrar_da_comparacao([EV], tmp_path) == {"criados": 0, "ja_existiam": 1, "ignorados": 0}
    avisos = pa.carregar(tmp_path)
    assert len(avisos) == 1 and avisos[0]["tipo"] == "transferencia" and avisos[0]["estado"] == "aberto"


def test_sem_eventos_nao_cria_nada(tmp_path):
    assert pa.registrar_da_comparacao([], tmp_path)["criados"] == 0
    assert not (tmp_path / pa.NOME_ARQUIVO).exists()


def test_mesma_saida_que_ganhou_id_depois_nao_vira_aviso_novo(tmp_path):
    pa.registrar_da_comparacao([EV], tmp_path)                                   # ainda sem id_matricula
    _grava(tmp_path, "transferidos.json", {"1001": _reg_transferido(id_matricula="M-1")})
    pa.registrar_da_comparacao([EV], tmp_path)                                   # agora a ponte já deu o ID
    assert len(pa.carregar(tmp_path)) == 1


def test_segunda_saida_do_mesmo_aluno_gera_outro_aviso(tmp_path):
    _grava(tmp_path, "transferidos.json", {"1001": _reg_transferido(id_matricula="M-1")})
    pa.registrar_da_comparacao([EV], tmp_path)
    pa.resolver(pa.carregar(tmp_path)[0]["id"], tmp_path)
    _grava(tmp_path, "transferidos.json", {"1001": _reg_transferido(id_matricula="M-2", data="20/12/2026")})
    pa.registrar_da_comparacao([{**EV, "data_transferencia": "20/12/2026"}], tmp_path)
    avisos = pa.carregar(tmp_path)
    assert len(avisos) == 2 and [a["estado"] for a in avisos] == ["resolvido", "aberto"]


def test_transferido_antes_da_data_de_corte_ou_que_voltou_nao_gera_aviso(tmp_path):
    _grava(tmp_path, "fila_transferidos.json", {"alunos": {"1001": {"situacao_fila": "antes_do_corte"},
                                                           "1002": {"situacao_fila": "retornou"}}})
    r = pa.registrar_da_comparacao([EV, {**EV, "cgm": "1002"}], tmp_path)
    assert r == {"criados": 0, "ja_existiam": 0, "ignorados": 2}


def test_sumido_vira_aviso_a_verificar_e_nao_de_transferencia(tmp_path):
    pa.registrar_da_comparacao([{**EV, "motivo": "saiu_da_lista", "data_transferencia": None}], tmp_path)
    a = pa.listar_abertos(tmp_path)[0]
    assert a["tipo"] == "saida_a_verificar" and "sem constar como transferido" in a["titulo"]
    assert [p["texto"] for p in a["passos"]] == ["Conferir a situação do aluno no SERE"]
    _grava(tmp_path, "turmas.json", {"5º Ano A": [{"CGM": "1001", "Nome": "Bia Souza", "Situação": "Matriculado"}]})
    assert pa.listar_abertos(tmp_path) == []                                       # voltou a aparecer: resolvido sozinho
    assert pa.carregar(tmp_path)[0]["resolvido_por"] == "automatico"


def test_andamento_do_aviso_de_transferencia_e_resolucao_automatica(tmp_path, monkeypatch):
    from src.automacao import avisos as av
    enviados = {}
    monkeypatch.setattr(av, "avisos_ja_enviados_ao_destino", lambda: enviados)
    _grava(tmp_path, "transferidos.json", {"1001": _reg_transferido(emitidos=False)})
    pa.registrar_da_comparacao([EV], tmp_path)

    def passos():
        return [p["feito"] for p in pa.listar_abertos(tmp_path)[0]["passos"]]
    assert passos() == [False, False]
    _grava(tmp_path, "transferidos.json", {"1001": _reg_transferido(emitidos=True)})       # documentos gerados
    assert passos() == [True, False]
    enviados[("id", "M-1")] = {"enviado_em": "2026-11-11", "para": "escola@x", "nome": "Bia Souza"}    # enviados ao destino
    assert pa.listar_abertos(tmp_path) == []
    a = pa.carregar(tmp_path)[0]
    assert a["estado"] == "resolvido" and a["resolvido_por"] == "automatico"
    assert pa.registrar_da_comparacao([EV], tmp_path)["ja_existiam"] == 1                  # resolvido não volta


def test_resolver_a_mao(tmp_path):
    pa.registrar_da_comparacao([EV], tmp_path)
    aviso_id = pa.listar_abertos(tmp_path)[0]["id"]
    assert pa.resolver("inexistente", tmp_path) is False
    assert pa.resolver(aviso_id, tmp_path) is True and pa.listar_abertos(tmp_path) == []
    assert pa.carregar(tmp_path)[0]["resolvido_por"] == "manual"


def test_arquivo_ilegivel_nao_derruba(tmp_path):
    (tmp_path / pa.NOME_ARQUIVO).write_text("{ quebrado", encoding="utf-8")
    assert pa.carregar(tmp_path) == [] and pa.listar_abertos(tmp_path) == []


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    return create_app().test_client(), tmp_path


def test_api_lista_e_resolve(c):
    cli, pasta = c
    assert cli.get("/web/api/painel/avisos").get_json() == {"avisos": [], "total": 0}
    pa.registrar_da_comparacao([EV], pasta)
    r = cli.get("/web/api/painel/avisos").get_json()
    assert r["total"] == 1 and r["avisos"][0]["passos"][0]["feito"] is False
    aviso_id = r["avisos"][0]["id"]
    assert cli.post("/web/api/painel/avisos/nao-existe/resolver").status_code == 404
    assert cli.post(f"/web/api/painel/avisos/{aviso_id}/resolver").get_json() == {"ok": True}
    assert cli.get("/web/api/painel/avisos").get_json()["total"] == 0


def test_home_tem_o_painel_de_avisos(c):
    html = Path(rotas.__file__).parent.parent.joinpath("templates", "painel.html").read_text(encoding="utf-8")
    assert 'id="painel-avisos"' in html and "hidden" in html

"""Coleta completa de funcionários: salva aos poucos e avisa quando parou no meio (servidores.py)."""
import asyncio
import json

import pytest

from src.automacao import servidores as sv
from src.web.api import rotas
from src.web.app import create_app


class PaginaFalsa:
    async def wait_for_timeout(self, _ms):
        return None


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    monkeypatch.setattr(sv, "OUTPUT_BASICO", tmp_path / "funcionarios.json")
    monkeypatch.setattr(sv, "OUTPUT_COMPLETO", tmp_path / "funcionarios_completo.json")
    monkeypatch.setattr(sv, "OUTPUT_PROGRESSO", tmp_path / "funcionarios_completo_progresso.json")
    monkeypatch.setattr(sv, "SALVAR_A_CADA", 3)

    async def navegar(page, rota):
        return None
    monkeypatch.setattr(sv, "navegar_censo_escolar", navegar)
    return tmp_path


def _lista(n):
    return [{"nome": f"Func {i}", "cpf": f"{i:011d}"} for i in range(1, n + 1)]


def _ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def _consulta_ok(vistos=None):
    async def consultar(page, cpf):
        if vistos is not None:
            vistos.append(cpf)
        return {"cpf": cpf, "nome_completo": f"Cadastro {cpf}", "origem": "novo"}
    return consultar


def test_salva_a_cada_n_cadastros_durante_a_coleta(ctx, monkeypatch):
    destino = ctx / "funcionarios_completo.json"
    tamanhos = []

    async def consultar(page, cpf):
        # no 4º e 7º a chamada acontece depois do 1º salvamento parcial (3 cadastros) e do 2º (6)
        tamanhos.append(len(_ler(destino)) if destino.exists() else 0)
        return {"cpf": cpf, "nome_completo": cpf}
    monkeypatch.setattr(sv, "consultar_cpf", consultar)

    r = asyncio.run(sv.coletar_completo(PaginaFalsa(), _lista(7)))
    assert len(r) == 7
    assert tamanhos == [0, 0, 0, 3, 3, 3, 6]            # gravou depois do 3º e do 6º cadastro


def test_cancelado_no_meio_mantem_o_que_foi_coletado_e_avisa(ctx, monkeypatch, capsys):
    async def consultar(page, cpf):
        if cpf.endswith("5"):
            raise asyncio.CancelledError()
        return {"cpf": cpf, "nome_completo": cpf, "origem": "novo"}
    monkeypatch.setattr(sv, "consultar_cpf", consultar)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sv.coletar_completo(PaginaFalsa(), _lista(8)))

    salvo = _ler(ctx / "funcionarios_completo.json")
    assert [r["cpf"][-2:] for r in salvo] == ["01", "02", "03", "04"]      # nada do que foi coletado se perdeu
    estado = _ler(ctx / "funcionarios_completo_progresso.json")
    assert estado["completa"] is False and estado["motivo"] == "cancelada"
    assert estado["coletados"] == 4 and estado["total"] == 8
    assert estado["pendentes"] == ["Func 5", "Func 6", "Func 7", "Func 8"]
    assert "cpf" not in json.dumps(estado).lower()                         # só nomes, sem CPF
    saida = capsys.readouterr().out
    assert "interrompida (cancelada)" in saida and "4 de 8" in saida and "NÃO foram" in saida


def test_erro_no_meio_tambem_salva_e_avisa_com_o_motivo(ctx, monkeypatch):
    async def consultar(page, cpf):
        if cpf.endswith("3"):
            raise RuntimeError("navegador fechou")
        return {"cpf": cpf, "nome_completo": cpf}
    monkeypatch.setattr(sv, "consultar_cpf", consultar)

    with pytest.raises(RuntimeError):
        asyncio.run(sv.coletar_completo(PaginaFalsa(), _lista(5)))
    estado = _ler(ctx / "funcionarios_completo_progresso.json")
    assert estado["completa"] is False and estado["motivo"] == "erro: navegador fechou"
    assert "navegador fechou" in estado["aviso"] and estado["coletados"] == 2


def test_o_arquivo_anterior_nao_encolhe_se_a_coleta_parar(ctx, monkeypatch):
    antigos = [{"cpf": f"{i:011d}", "nome_completo": f"Antigo {i}", "origem": "antigo"} for i in range(1, 11)]
    (ctx / "funcionarios_completo.json").write_text(json.dumps(antigos), encoding="utf-8")

    async def consultar(page, cpf):
        if cpf.endswith("4"):
            raise asyncio.CancelledError()
        return {"cpf": cpf, "nome_completo": f"Novo {cpf}", "origem": "novo"}
    monkeypatch.setattr(sv, "consultar_cpf", consultar)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sv.coletar_completo(PaginaFalsa(), _lista(10)))
    salvo = _ler(ctx / "funcionarios_completo.json")
    assert len(salvo) == 10                                                 # nenhum dos 10 se perdeu
    por_cpf = {r["cpf"]: r["origem"] for r in salvo}
    assert [por_cpf[f"{i:011d}"] for i in range(1, 11)] == ["novo"] * 3 + ["antigo"] * 7


def test_coleta_completa_deixa_so_os_cadastros_de_agora_e_marca_como_terminada(ctx, monkeypatch):
    antigos = [{"cpf": "99999999999", "nome_completo": "Já saiu da escola"}]
    (ctx / "funcionarios_completo.json").write_text(json.dumps(antigos), encoding="utf-8")
    (ctx / "funcionarios.json").write_text(json.dumps(_lista(4)), encoding="utf-8")
    monkeypatch.setattr(sv, "consultar_cpf", _consulta_ok())

    r = asyncio.run(sv.coletar_servidores(PaginaFalsa(), "completo"))
    assert len(r) == 4
    assert [x["cpf"][-1] for x in _ler(ctx / "funcionarios_completo.json")] == ["1", "2", "3", "4"]   # como sempre foi
    estado = _ler(ctx / "funcionarios_completo_progresso.json")
    assert estado["completa"] is True and estado["coletados"] == 4 and "aviso" not in estado
    assert not list(ctx.glob("*.tmp"))                                      # nenhum arquivo temporário sobrando


def test_cpf_nao_encontrado_nao_e_tratado_como_interrupcao(ctx, monkeypatch):
    (ctx / "funcionarios.json").write_text(json.dumps(_lista(3)), encoding="utf-8")

    async def consultar(page, cpf):
        return None if cpf.endswith("2") else {"cpf": cpf, "nome_completo": cpf}
    monkeypatch.setattr(sv, "consultar_cpf", consultar)
    asyncio.run(sv.coletar_servidores(PaginaFalsa(), "completo"))
    estado = _ler(ctx / "funcionarios_completo_progresso.json")
    assert estado["completa"] is True and estado["coletados"] == 2 and estado["pendentes"] == ["Func 2"]


# ───────────── a tela recebe o aviso ─────────────

def test_a_lista_de_funcionarios_traz_o_aviso_so_quando_a_coleta_ficou_incompleta(ctx):
    c = create_app().test_client()
    (ctx / "funcionarios.json").write_text(json.dumps(_lista(2)), encoding="utf-8")
    assert c.get("/web/api/funcionarios/lista").get_json()["coleta_completo"] is None          # nunca rodou

    sv.gravar_progresso(False, 8, 4, ["Func 5", "Func 6"], "2026-11-02 09:00:00", "cancelada")
    info = c.get("/web/api/funcionarios/lista").get_json()["coleta_completo"]
    assert info["coletados"] == 4 and info["total"] == 8 and info["pendentes"] == ["Func 5", "Func 6"]
    assert "interrompida (cancelada)" in info["aviso"] and info["motivo"] == "cancelada"

    sv.gravar_progresso(True, 8, 8, [], "2026-11-02 09:00:00")
    assert c.get("/web/api/funcionarios/lista").get_json()["coleta_completo"] is None          # terminou: some o aviso

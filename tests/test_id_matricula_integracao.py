"""ID da matrícula (turmas_relacional.json) usado por Transferidos, Base ABC e pela ligação da pré-matrícula (2026-11-20)."""
import asyncio
import json
from datetime import date

import pytest

from src.automacao import consulta_base_abc as cba
from src.automacao import fila_transferidos as ft
from src.automacao import pre_matricula as pm
from src.comum import matriculas as M
from src.comum import paths

CGM = "10101010"
TURMA = "1º Ano Integral A"
CORTE = date(2026, 6, 22)


def _al(n, situacao, data, cgm=CGM, nome="BETO LIMA", nasc="02/03/2015"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Situação": situacao, "Data Matricula": data}


def _turmas(*alunos):
    return {TURMA: list(alunos)}


@pytest.fixture()
def dados(tmp_path):
    pasta = tmp_path / "2026"
    pasta.mkdir()
    return pasta


def _coleta(dados, *alunos):
    """Uma coleta de turmas como o turmas.py faz: atualiza a ponte e acrescenta ID_MATRICULA às linhas."""
    turmas = _turmas(*alunos)
    assert M.registrar_matriculas_sem_falhar(turmas, dados, ano="2026") is not None
    return turmas


def _gravar(caminho, dados):
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def _doc(quando):
    return {"emitido_em": quando, "assinado_secretario": quando, "assinado_diretor": quando, "anexado_em": quando}


def _primeira_saida_processada(dados):
    """Matriculado em 05/02, transferido em 25/07 (ponte: 2026-0001), processo concluído com os PDFs gravados."""
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    turmas = _coleta(dados, _al(5, "Transferido", "25/07/2026"))
    ft.registrar_fila_transferidos(turmas, dados, CORTE)
    controle = _ler(dados / "transferidos.json")
    controle[CGM]["guia"], controle[CGM]["historico"] = _doc("2026-07-26T10:00:00"), _doc("2026-07-26T10:05:00")
    controle[CGM]["parecer"] = {"digitalizado_em": "2026-07-27T09:00:00", "anexado_em": "2026-07-27T09:30:00"}
    _gravar(dados / "transferidos.json", controle)
    for sub in ("HISTORICO", "GUIA DE TRANSFERENCIA"):
        pasta = dados / "TRANSFERENCIAS" / sub / TURMA
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "BETO LIMA.pdf").write_bytes(b"%PDF 1a saida " + sub.encode())


def _segunda_saida(dados):
    _coleta(dados, _al(5, "Transferido", "25/07/2026"), _al(40, "Matriculado", "15/09/2026"))     # voltou
    return _coleta(dados, _al(5, "Transferido", "25/07/2026"), _al(40, "Transferido", "10/10/2026"))


# ═════════════════════════════ Transferidos ═════════════════════════════

def test_registro_novo_de_transferido_guarda_o_id_da_saida(dados):
    _primeira_saida_processada(dados)
    reg = _ler(dados / "transferidos.json")[CGM]
    assert reg["id_matricula"] == "2026-0001"
    assert _ler(dados / "fila_transferidos.json")["alunos"][CGM]["id_matricula"] == "2026-0001"


def test_turmas_sem_id_continuam_funcionando_e_o_registro_fica_sem_o_campo(dados):
    ft.registrar_fila_transferidos(_turmas(_al(5, "Transferido", "25/07/2026")), dados, CORTE)     # turmas.json antigo
    assert "id_matricula" not in _ler(dados / "transferidos.json")[CGM]


@pytest.mark.parametrize("reg,fila,esperado,porque", [
    # mesmo ID: é a mesma saída, mesmo que a data da fila seja outra e a antiga ainda conste entre as anteriores
    ({"id_matricula": "A", "data_transferencia": "01/03/2026"},
     {"id_matricula": "A", "data_transferencia": "15/03/2026", "transferencias_anteriores": [{"data": "01/03/2026"}]}, False, "mesmo ID"),
    # ID diferente e data posterior: outra saída; o ID dispensa a saída anterior na fila
    ({"id_matricula": "A", "data_transferencia": "01/03/2026"},
     {"id_matricula": "B", "data_transferencia": "15/09/2026"}, True, "ID diferente, data posterior"),
    # ID diferente, mesma data: a ponte foi refeita e deu outro ID à MESMA saída
    ({"id_matricula": "A", "data_transferencia": "01/03/2026"},
     {"id_matricula": "B", "data_transferencia": "01/03/2026"}, False, "ponte refeita"),
    # ID diferente, data ANTERIOR: não é uma saída mais nova
    ({"id_matricula": "A", "data_transferencia": "10/10/2026"},
     {"id_matricula": "B", "data_transferencia": "01/03/2026"}, False, "data anterior"),
    # ID só de um lado: vale a regra antiga, por datas
    ({"data_transferencia": "01/03/2026"},
     {"id_matricula": "B", "data_transferencia": "15/09/2026"}, False, "registro sem ID e sem anterior"),
    ({"data_transferencia": "01/03/2026"},
     {"id_matricula": "B", "data_transferencia": "15/09/2026", "transferencias_anteriores": [{"data": "01/03/2026"}]}, True, "regra antiga"),
])
def test_e_nova_saida_com_id(reg, fila, esperado, porque):
    assert ft.e_nova_saida(reg, fila) is esperado, porque


def test_segunda_saida_com_ids_da_ponte_cria_ciclo_com_id_e_nomes_dos_pdfs(dados):
    _primeira_saida_processada(dados)
    turmas = _segunda_saida(dados)
    r = ft.registrar_fila_transferidos(turmas, dados, CORTE)
    assert r["novos_ciclos"] == 1
    reg = _ler(dados / "transferidos.json")[CGM]
    assert reg["id_matricula"] == "2026-0002" and reg["data_transferencia"] == "10/10/2026"
    (ciclo,) = reg["ciclos_anteriores"]
    assert ciclo["id_matricula"] == "2026-0001" and ciclo["data_transferencia"] == "25/07/2026"
    assert ciclo["arquivos"] == {"historico": "BETO LIMA (saída 25-07-2026).pdf", "guia": "BETO LIMA (saída 25-07-2026).pdf"}
    for sub in ("HISTORICO", "GUIA DE TRANSFERENCIA"):
        assert (dados / "TRANSFERENCIAS" / sub / TURMA / ciclo["arquivos"]["guia"]).is_file()
    # rodar de novo não cria outro ciclo
    assert ft.registrar_fila_transferidos(turmas, dados, CORTE)["novos_ciclos"] == 0


def test_data_corrigida_no_sere_com_o_mesmo_id_nao_refaz_nada(dados):
    _primeira_saida_processada(dados)
    turmas = _coleta(dados, _al(5, "Transferido", "28/07/2026"))              # o SERE corrigiu a data; a ponte mantém o período
    assert turmas[TURMA][0]["ID_MATRICULA"] == "2026-0001"
    r = ft.registrar_fila_transferidos(turmas, dados, CORTE)
    reg = _ler(dados / "transferidos.json")[CGM]
    assert r["novos_ciclos"] == 0 and "ciclos_anteriores" not in reg
    assert reg["guia"]["emitido_em"] == "2026-07-26T10:00:00" and reg["id_matricula"] == "2026-0001"


def test_registro_antigo_sem_id_adota_o_id_na_primeira_coleta_com_ponte(dados):
    turmas = _coleta(dados, _al(5, "Transferido", "25/07/2026"))
    antigo = {"nome": "BETO LIMA", "turma": TURMA, "chamada": 5, "data_nascimento": "02/03/2015", "data_transferencia": "25/07/2026",
              "retorno": None, "guia": _doc("2026-07-26T10:00:00"), "historico": _doc("2026-07-26T10:05:00"),
              "parecer": {"digitalizado_em": "2026-07-27T09:00:00", "anexado_em": None}}
    _gravar(dados / "transferidos.json", {CGM: dict(antigo)})
    ft.registrar_fila_transferidos(turmas, dados, CORTE)
    reg = _ler(dados / "transferidos.json")[CGM]
    assert reg.pop("id_matricula") == turmas[TURMA][0]["ID_MATRICULA"] and reg == antigo        # só ganhou o ID


def test_ponte_refeita_com_outro_id_para_a_mesma_saida_adota_o_novo_e_lembra_o_antigo(dados):
    _primeira_saida_processada(dados)
    M.caminho(dados).unlink()                                                   # a ponte foi apagada: os IDs recomeçam
    turmas = _coleta(dados, _al(5, "Transferido", "25/07/2026"))
    ft.registrar_fila_transferidos(turmas, dados, CORTE)
    r = ft.registrar_fila_transferidos(turmas, dados, CORTE)
    reg = _ler(dados / "transferidos.json")[CGM]
    assert r["novos_ciclos"] == 0 and "ciclos_anteriores" not in reg and reg["guia"]["emitido_em"]
    assert reg["id_matricula"] == turmas[TURMA][0]["ID_MATRICULA"]


# ═════════════════════════════ Base ABC ═════════════════════════════

def test_consulta_do_transferido_leva_o_id_e_ele_vai_para_o_vinculo_e_o_registro():
    (c,) = cba.consultas_dos_transferidos({CGM: {"nome": "BETO LIMA", "data_nascimento": "02/03/2015", "id_matricula": "2026-0002"}})
    assert c.id_matricula == "2026-0002"
    v = cba.montar_vinculo(c, "BETO LIMA", CGM, [{"ano": 2026, "escola": "ESCOLA X", "curso": "EF", "serie": "2", "resultado": "Matriculado"}], 2026)
    assert v["id_matricula"] == "2026-0002"
    res = cba.Resultado(estado="encontrado", cadastro={"cgm": CGM, "nome": "BETO LIMA"}, conferido_por="CGM")
    assert cba.montar_registro(c, res, [], 2026)["id_matricula"] == "2026-0002"


def test_consulta_sem_id_nao_ganha_o_campo():
    (c,) = cba.consultas_dos_transferidos({CGM: {"nome": "BETO LIMA", "data_nascimento": "02/03/2015"}})
    assert c.id_matricula == "" and "id_matricula" not in cba.montar_vinculo(c, "BETO LIMA", CGM, [], 2026)


def _destino_tf():
    return ("transferidos.json", "transferidos", CGM, "", cba.PERIODO_ANO_VIGENTE)


def test_vinculo_so_e_gravado_se_o_registro_ainda_for_da_mesma_saida(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path)
    pasta = tmp_path / "2026"
    pasta.mkdir()
    _gravar(pasta / "transferidos.json", {CGM: {"nome": "BETO LIMA", "id_matricula": "2026-0002"}})
    logs: list = []
    mesma = {"status": "ok", "cgm": CGM, "escola": "ESCOLA X", "id_matricula": "2026-0002"}
    outra = {"status": "ok", "cgm": CGM, "escola": "ESCOLA Y", "id_matricula": "2026-0001"}      # consulta da 1ª saída
    assert cba.gravar_vinculos_pre_matricula([(_destino_tf(), outra)], "2026", logs.append) == 0
    assert "vinculo_base_abc" not in _ler(pasta / "transferidos.json")[CGM] and any("OUTRA saída" in x for x in logs)
    assert cba.gravar_vinculos_pre_matricula([(_destino_tf(), mesma)], "2026", logs.append) == 1
    assert _ler(pasta / "transferidos.json")[CGM]["vinculo_base_abc"]["escola"] == "ESCOLA X"


def test_registro_sem_id_recebe_o_vinculo_normalmente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path)
    pasta = tmp_path / "2026"
    pasta.mkdir()
    _gravar(pasta / "transferidos.json", {CGM: {"nome": "BETO LIMA"}})
    v = {"status": "ok", "cgm": CGM, "escola": "ESCOLA X", "id_matricula": "2026-0002"}
    assert cba.gravar_vinculos_pre_matricula([(_destino_tf(), v)], "2026", lambda *_: None) == 1


# ═════════════════════════════ pré-matrícula ↔ matrícula (por CGM) ═════════════════════════════

CPF = "12345678900"


def _pre(cgm=CGM, status="ok", extra=None):
    cad = {"cpf": CPF, "nome_aluno": "BETO LIMA", "vinculo_base_abc": {"status": status, "cgm": cgm, "escola": "ESCOLA X"}}
    cad.update(extra or {})
    return {"cadastros": {CPF: cad}, "turmas_intencao": {}}


def test_aluno_da_pre_matricula_que_ganhou_cgm_e_matricula_e_ligado_ao_id(dados):
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    _gravar(dados / "pre_matricula.json", _pre())
    assert M.ligar_pre_matricula(dados) == {"ligados": 1}
    assert _ler(dados / "pre_matricula.json")["cadastros"][CPF]["id_matricula"] == "2026-0001"
    (m,) = _ler(M.caminho(dados))["matriculas"]
    assert m["pre_matricula"]["arquivo"] == "pre_matricula.json"
    assert CPF not in M.caminho(dados).read_text(encoding="utf-8")                 # o CPF nunca vai para a ponte
    assert M.ligar_pre_matricula(dados) == {"ja_ligados": 1}                       # idempotente
    assert _ler(dados / "pre_matricula.json")["cadastros"][CPF]["id_matricula"] == "2026-0001"


def test_vinculo_a_verificar_ou_sem_cgm_nao_liga_ninguem(dados):
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    _gravar(dados / "pre_matricula.json", _pre(status="verificar"))
    assert M.ligar_pre_matricula(dados) == {}
    _gravar(dados / "pre_matricula.json", _pre(cgm=""))
    assert M.ligar_pre_matricula(dados) == {}
    assert "id_matricula" not in _ler(dados / "pre_matricula.json")["cadastros"][CPF]


def test_cgm_que_ainda_nao_esta_matriculado_fica_para_depois(dados):
    _coleta(dados, _al(5, "Matriculado", "05/02/2026", cgm="99999999", nome="OUTRO ALUNO"))
    _gravar(dados / "pre_matricula.json", _pre())
    assert M.ligar_pre_matricula(dados) == {"sem_matricula": 1}
    _coleta(dados, _al(5, "Matriculado", "05/02/2026", cgm="99999999", nome="OUTRO ALUNO"), _al(6, "Matriculado", "10/03/2026"))
    assert M.ligar_pre_matricula(dados) == {"ligados": 1}                           # depois que a matrícula aparece


def test_cgm_com_dois_periodos_liga_o_mais_antigo(dados):
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    _coleta(dados, _al(5, "Transferido", "31/03/2026"))
    _coleta(dados, _al(5, "Transferido", "31/03/2026"), _al(31, "Matriculado", "06/07/2026"))
    _gravar(dados / "pre_matricula.json", _pre())
    assert M.ligar_pre_matricula(dados) == {"ligados": 1, "mais_de_um_periodo": 1}
    assert _ler(dados / "pre_matricula.json")["cadastros"][CPF]["id_matricula"] == "2026-0001"


def test_ligacao_valida_nunca_e_trocada_e_a_invalida_e_reparada(dados):
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    _gravar(dados / "pre_matricula.json", _pre(extra={"id_matricula": "2026-0001"}))
    assert M.ligar_pre_matricula(dados) == {"ja_ligados": 1}
    _gravar(dados / "pre_matricula.json", _pre(extra={"id_matricula": "2025-0099"}))      # ID que a ponte não conhece
    assert M.ligar_pre_matricula(dados) == {"reparados": 1}
    assert _ler(dados / "pre_matricula.json")["cadastros"][CPF]["id_matricula"] == "2026-0001"


def test_item_da_fila_sem_cadastro_tambem_e_ligado_e_o_previsao_do_ano_tambem(dados):
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    item = {"nome": "BETO LIMA", "cpf": CPF, "vinculo_base_abc": {"status": "ok", "cgm": CGM}}
    _gravar(dados / "pre_matricula.json", {"cadastros": {}, "turmas_intencao": {TURMA: [item]}})
    _gravar(dados / "previsao_alunos_2026.json", _pre())
    assert M.ligar_pre_matricula(dados) == {"ligados": 2}
    assert _ler(dados / "pre_matricula.json")["turmas_intencao"][TURMA][0]["id_matricula"] == "2026-0001"
    assert _ler(dados / "previsao_alunos_2026.json")["cadastros"][CPF]["id_matricula"] == "2026-0001"


def test_sem_ponte_ou_com_arquivo_ilegivel_nada_e_tocado(dados):
    _gravar(dados / "pre_matricula.json", _pre())
    assert M.ligar_pre_matricula(dados) == {}                                       # sem ponte
    _coleta(dados, _al(5, "Matriculado", "05/02/2026"))
    (dados / "pre_matricula.json").write_text("{quebrado", encoding="utf-8")
    assert M.ligar_pre_matricula(dados) == {"ilegiveis": 1}
    assert (dados / "pre_matricula.json").read_text(encoding="utf-8") == "{quebrado"


def test_ponte_ilegivel_nao_derruba_o_gancho(dados):
    M.caminho(dados).write_text("{quebrado", encoding="utf-8")
    assert M.ligar_pre_matricula_sem_falhar(dados) is None
    assert M.caminho(dados).read_text(encoding="utf-8") == "{quebrado"


def test_coleta_da_pre_matricula_nao_apaga_a_ligacao():
    antigo = {"vinculo_base_abc": {"cgm": CGM}, "id_matricula": "2026-0001"}
    novo = {"nome_aluno": "BETO LIMA"}
    pm._herdar_vinculo(antigo, novo)
    assert novo["id_matricula"] == "2026-0001" and novo["vinculo_base_abc"] == {"cgm": CGM}
    pronto = {"id_matricula": "2026-0007"}
    pm._herdar_vinculo(antigo, pronto)
    assert pronto["id_matricula"] == "2026-0007"                                    # o que já está no novo não é sobrescrito


def test_consulta_da_base_abc_que_traz_cgm_liga_o_aluno_na_mesma_rodada(tmp_path, monkeypatch):
    """Ponta a ponta: a consulta grava o vínculo (com CGM) na pré-matrícula e o aluno já sai ligado à matrícula."""
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path)
    pasta = tmp_path / "2026"
    pasta.mkdir()
    _coleta(pasta, _al(5, "Matriculado", "05/02/2026"))
    _gravar(pasta / "pre_matricula.json", {"cadastros": {CPF: {"cpf": CPF, "nome_aluno": "BETO LIMA"}}, "turmas_intencao": {}})

    async def falso(nav, consulta, resumo, ano, log):
        resumo.vinculos.append((("pre_matricula.json", "cadastros", CPF, "", cba.PERIODO_ANO_VIGENTE),
                                {"status": "ok", "cgm": CGM, "escola": "ESCOLA X", "periodo": cba.PERIODO_ANO_VIGENTE}))
    monkeypatch.setattr(cba, "processar_consulta", falso)
    resumo = asyncio.run(cba.consultar(None, [cba.Consulta(nome="BETO LIMA")], "2026", log=lambda *_: None))
    assert resumo.vinculos_gravados == 1
    cad = _ler(pasta / "pre_matricula.json")["cadastros"][CPF]
    assert cad["vinculo_base_abc"]["cgm"] == CGM and cad["id_matricula"] == "2026-0001"

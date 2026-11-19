"""Testes da ponte de IDs de matrícula (src/comum/matriculas.py → dados/<ano>/turmas_relacional.json)."""

import json
import os
import re
import time
import zipfile
from pathlib import Path

import pytest

from src.comum import matriculas as M

CGM = "10101010"


def _aluno(n, situacao, data, cgm=CGM, nome="FULANO DE TAL", **extra):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": "01/01/2014", "Situação": situacao,
            "Data Matricula": data, **extra}


def _turmas(*alunos, turma="1º ANO"):
    return {turma: list(alunos)}


@pytest.fixture
def dados(tmp_path):
    pasta = tmp_path / "2026"
    pasta.mkdir()
    return pasta


def _ponte(dados):
    return json.loads(M.caminho(dados).read_text(encoding="utf-8"))["matriculas"]


# ───────────────────────────── ciclo do aluno ─────────────────────────────

def test_entrada_nova_recebe_id_e_fica_em_aberto(dados):
    r = M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    (m,) = _ponte(dados)
    assert m["id"] == "2026-0001"
    assert (m["data_matricula"], m["data_saida"], m["status"]) == ("05/02/2026", None, "ok")
    assert r["novas"] == 1 and r["verificar"] == 0


def test_transferencia_fecha_o_mesmo_periodo_e_guarda_a_entrada(dados):
    """O SERE troca (Matriculado, 05/02) por (Transferido, 31/03): a entrada não pode se perder."""
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    r = M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026")), dados)
    (m,) = _ponte(dados)
    assert m["id"] == "2026-0001"
    assert (m["data_matricula"], m["data_saida"], m["situacao"]) == ("05/02/2026", "31/03/2026", "Transferido")
    assert r["saidas"] == 1 and r.get("novas", 0) == 0


def test_entra_sai_entra_sai_gera_dois_ids_ligados_pelo_cgm(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026")), dados)
    # voltou: o SERE mostra a saída antiga e o retorno, que entra no fim da chamada
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026"), _aluno(31, "Matriculado", "06/07/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026"), _aluno(31, "Transferido", "31/10/2026")), dados)

    primeiro, segundo = _ponte(dados)
    assert (primeiro["id"], primeiro["data_matricula"], primeiro["data_saida"]) == ("2026-0001", "05/02/2026", "31/03/2026")
    assert (segundo["id"], segundo["data_matricula"], segundo["data_saida"]) == ("2026-0002", "06/07/2026", "31/10/2026")
    assert segundo["retorno"] is True and primeiro["retorno"] is False
    assert {m["status"] for m in _ponte(dados)} == {"ok"}
    assert [m["id"] for m in M.do_cgm(CGM, dados)] == ["2026-0001", "2026-0002"]


def test_ids_nao_mudam_nem_sao_reaproveitados_em_novas_coletas(dados):
    coleta = _turmas(_aluno(2, "Transferido", "31/03/2026"), _aluno(31, "Matriculado", "06/07/2026"))
    M.sincronizar(coleta, dados)
    ids = [m["id"] for m in _ponte(dados)]
    for _ in range(3):
        M.sincronizar(coleta, dados)
    assert [m["id"] for m in _ponte(dados)] == ids
    M.sincronizar(_turmas(_aluno(5, "Matriculado", "10/08/2026", cgm="2222", nome="OUTRO")), dados)
    assert _ponte(dados)[-1]["id"] == "2026-0003"


def test_coleta_repetida_nao_regrava_o_arquivo(dados):
    coleta = _turmas(_aluno(2, "Matriculado", "05/02/2026"))
    M.sincronizar(coleta, dados)
    antes = M.caminho(dados).read_bytes()
    time.sleep(0.01)
    M.sincronizar(coleta, dados)
    assert M.caminho(dados).read_bytes() == antes


def test_primeira_coleta_ja_com_saidas_cria_periodos_so_com_saida(dados):
    """Ponte criada no meio do ano: a entrada de quem já saiu não vem do SERE (fica None, sem inventar)."""
    r = M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026"), _aluno(31, "Transferido", "31/10/2026")), dados)
    a, b = _ponte(dados)
    assert (a["data_matricula"], a["data_saida"]) == (None, "31/03/2026")
    assert (b["data_matricula"], b["data_saida"]) == (None, "31/10/2026")
    assert r["so_saida"] == 2 and r["verificar"] == 0


def test_saida_nao_fecha_periodo_que_comecou_depois_dela(dados):
    M.sincronizar(_turmas(_aluno(31, "Matriculado", "06/07/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026"), _aluno(31, "Matriculado", "06/07/2026")), dados)
    novo, antigo = sorted(_ponte(dados), key=lambda m: m["data_saida"] is None)
    assert antigo["data_saida"] is None and antigo["data_matricula"] == "06/07/2026"
    assert novo["data_saida"] == "31/03/2026"


# ───────────────────────── situações a conferir ─────────────────────────

def test_data_de_matricula_corrigida_no_sere_nao_cria_id_novo(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    r = M.sincronizar(_turmas(_aluno(2, "Matriculado", "06/02/2026")), dados)
    (m,) = _ponte(dados)
    assert m["data_matricula"] == "06/02/2026" and m["status"] == "verificar"
    assert "05/02/2026" in m["motivos"][0] and r["verificar"] == 1


def test_saida_desfeita_no_sere_reabre_e_marca_para_conferir(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    (m,) = _ponte(dados)
    assert m["data_saida"] is None and m["status"] == "verificar"


def test_saida_com_data_corrigida_no_sere(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "02/04/2026")), dados)
    (m,) = _ponte(dados)
    assert m["data_saida"] == "02/04/2026" and m["status"] == "verificar"


def test_duas_matriculas_em_aberto_em_turmas_diferentes_marcam_as_duas(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026"), turma="1º ANO"), dados)
    M.sincronizar(_turmas(_aluno(9, "Matriculado", "20/05/2026"), turma="3º ANO"), dados)
    a, b = _ponte(dados)
    assert a["status"] == b["status"] == "verificar"


def test_situacao_desconhecida_vai_para_conferencia(dados):
    M.sincronizar(_turmas(_aluno(2, "Remanejado", "05/02/2026")), dados)
    (m,) = _ponte(dados)
    assert m["status"] == "verificar" and "Remanejado" in m["motivos"][0]


def test_conferir_limpa_o_alerta_e_guarda_o_motivo(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "06/02/2026")), dados)
    (m,) = M.a_conferir(dados)
    assert M.conferir(dados, m["id"], "data correta é 06/02") is True
    (m,) = _ponte(dados)
    assert m["status"] == "ok" and m["motivos"] == [] and m["conferido"][0]["nota"] == "data correta é 06/02"
    assert M.conferir(dados, "2026-9999") is False


def test_nome_nunca_e_usado_para_casar(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026", nome="NOME ERRADO")), dados)
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026", nome="Nome Corrigido")), dados)
    (m,) = _ponte(dados)
    assert m["id"] == "2026-0001" and m["nome"] == "Nome Corrigido"


def test_linhas_sem_cgm_ou_sem_data_sao_ignoradas_e_contadas(dados):
    r = M.sincronizar(
        _turmas(_aluno(1, "Matriculado", "05/02/2026", cgm=""), _aluno(2, "Matriculado", ""),
                _aluno(3, "Transferido", "data ruim"), _aluno(4, "Matriculado", "05/02/2026", cgm="777")),
        dados,
    )
    assert r["sem_cgm"] == 1 and r["sem_data"] == 2 and r["novas"] == 1


# ───────────────────────────── segurança do arquivo ─────────────────────────────

def test_arquivo_ilegivel_nao_e_tratado_como_vazio(dados):
    M.caminho(dados).write_text("{ isto nao e json", encoding="utf-8")
    with pytest.raises(M.MatriculasCorrompidasError):
        M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    assert M.caminho(dados).read_text(encoding="utf-8") == "{ isto nao e json"


def test_estrutura_invalida_tambem_e_recusada(dados):
    M.caminho(dados).write_text(json.dumps({"matriculas": "x"}), encoding="utf-8")
    with pytest.raises(M.MatriculasCorrompidasError):
        M.carregar(dados)


def test_gancho_nunca_derruba_a_coleta(dados):
    M.caminho(dados).write_text("{ quebrado", encoding="utf-8")
    turmas = _turmas(_aluno(2, "Matriculado", "05/02/2026"))
    assert M.registrar_matriculas_sem_falhar(turmas, dados) is None
    assert CAMPO_ID not in turmas["1º ANO"][0]                      # sem ponte, nada é acrescentado
    assert M.caminho(dados).read_text(encoding="utf-8") == "{ quebrado"


def test_gravacao_deixa_copia_antes(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    assert not (dados / (M.ARQUIVO + ".antes")).exists()            # primeira gravação: nada para copiar
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026")), dados)
    antes = json.loads((dados / (M.ARQUIVO + ".antes")).read_text(encoding="utf-8"))
    assert antes["matriculas"][0]["data_saida"] is None


def test_trava_recente_bloqueia_e_trava_velha_e_removida(dados):
    lock = dados / (M.ARQUIVO + ".lock")
    lock.write_text("999")
    with pytest.raises(TimeoutError):
        with M._trava(dados, espera=0.2):
            pass
    velho = time.time() - 600
    os.utime(lock, (velho, velho))
    with M._trava(dados, espera=0.5):
        assert lock.exists()
    assert not lock.exists()                                        # liberada ao sair


def test_trava_e_liberada_mesmo_com_erro(dados):
    with pytest.raises(RuntimeError):
        with M._trava(dados):
            raise RuntimeError("falha qualquer")
    assert not (dados / (M.ARQUIVO + ".lock")).exists()


# ───────────────────── enriquecimento do turmas.json (gancho) ─────────────────────

CAMPO_ID = M.CAMPO_ID


def test_gancho_acrescenta_id_e_datas_sem_mexer_em_data_matricula(dados):
    M.registrar_matriculas_sem_falhar(_turmas(_aluno(22, "Matriculado", "05/02/2026")), dados)
    turmas = _turmas(_aluno(22, "Transferido", "25/06/2026"), _aluno(23, "Matriculado", "05/02/2026", cgm="999"))
    resumo = M.registrar_matriculas_sem_falhar(turmas, dados)

    transf, ativo = turmas["1º ANO"]
    assert transf["Data Matricula"] == "25/06/2026"                 # como o SERE entrega: módulos existentes continuam valendo
    assert (transf[CAMPO_ID], transf[M.CAMPO_ENTRADA], transf[M.CAMPO_SAIDA]) == ("2026-0001", "05/02/2026", "25/06/2026")
    assert (ativo[CAMPO_ID], ativo[M.CAMPO_ENTRADA], ativo[M.CAMPO_SAIDA]) == ("2026-0002", "05/02/2026", "")
    assert resumo["com_id"] == 2


def test_id_da_linha_encontra_a_matricula_certa(dados):
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2026")), dados)
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026"), _aluno(31, "Matriculado", "06/07/2026")), dados)
    assert M.id_da_linha(_aluno(2, "Transferido", "31/03/2026"), dados) == "2026-0001"
    assert M.id_da_linha(_aluno(31, "Matriculado", "06/07/2026"), dados) == "2026-0002"
    assert M.id_da_linha(_aluno(31, "Matriculado", "01/01/2020"), dados) == ""


def test_ano_vem_do_nome_da_pasta(tmp_path):
    pasta = tmp_path / "2027"
    pasta.mkdir()
    M.sincronizar(_turmas(_aluno(2, "Matriculado", "05/02/2027")), pasta)
    assert _ponte(pasta)[0]["id"] == "2027-0001"


# ───────────────────────────── semear pelos backups ─────────────────────────────

def test_semear_de_backups_recupera_entrada_de_quem_ja_saiu(dados, tmp_path, monkeypatch):
    from src.comum import backup

    def zip_com(nome, turmas):
        z = tmp_path / nome
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("dados_ano/turmas.json", json.dumps(turmas))
        return str(z)

    antigo = zip_com("a.zip", _turmas(_aluno(2, "Matriculado", "05/02/2026")))
    recente = zip_com("b.zip", _turmas(_aluno(2, "Transferido", "31/03/2026")))
    outro_ano = zip_com("c.zip", _turmas(_aluno(9, "Matriculado", "01/01/2025", cgm="55")))
    # listar_backups devolve do mais novo ao mais antigo
    monkeypatch.setattr(backup, "listar_backups", lambda: [
        {"caminho": recente, "ano": "2026"}, {"caminho": outro_ano, "ano": "2025"}, {"caminho": antigo, "ano": "2026"},
    ])
    r = M.semear_de_backups(dados)
    assert r == {"backups": 2, "aplicados": 2}
    (m,) = _ponte(dados)
    assert (m["data_matricula"], m["data_saida"]) == ("05/02/2026", "31/03/2026")


def test_semear_recusa_quando_a_ponte_ja_existe(dados, monkeypatch):
    """Semear depois da 1ª coleta duplicaria o período de quem já estava Transferido."""
    from src.comum import backup
    M.sincronizar(_turmas(_aluno(2, "Transferido", "31/03/2026")), dados)
    antes = M.caminho(dados).read_bytes()
    monkeypatch.setattr(backup, "listar_backups", lambda: pytest.fail("não deveria nem olhar os backups"))
    r = M.semear_de_backups(dados)
    assert "ANTES da primeira coleta" in r["erro"] and r["aplicados"] == 0
    assert M.caminho(dados).read_bytes() == antes


# ───────────────────────────── ligação na coleta ─────────────────────────────

def test_coleta_de_turmas_chama_a_ponte_antes_de_salvar_e_a_fila_depois():
    fonte = (Path(__file__).resolve().parent.parent / "src" / "automacao" / "turmas.py").read_text(encoding="utf-8")
    ponte = fonte.index("registrar_matriculas_sem_falhar(resultado")
    salvar = fonte.index("Salvando JSON em")
    fila = fonte.index("registrar_fila_sem_falhar(resultado")
    assert ponte < salvar < fila, "a ponte enriquece as linhas ANTES de gravar o turmas.json"
    assert re.search(r"registrar_matriculas_sem_falhar\(resultado,\s*dados_dir=output_file\.parent\)", fonte)

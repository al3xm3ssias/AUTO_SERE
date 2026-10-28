"""Testes de src/automacao/deteccao_transferidos.py (sem rede, sem navegador)."""
import json

import pytest

from src.automacao import deteccao_transferidos as dt


def _al(n, cgm, nome, nasc="01/01/2015", sit="Matriculado", data="05/02/2026"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Situação": sit, "Data Matricula": data}


def _base(n=10):
    """Turma A com n alunos ativos (n grande evita a trava de saída em massa) + turma B com um."""
    return {"A": [_al(i, str(i), f"ALUNO {i}") for i in range(1, n + 1)], "B": [_al(1, "100", "ALUNO 100")]}


def _copia(d):
    return json.loads(json.dumps(d))


def _ler(pasta, nome):
    return json.loads((pasta / nome).read_text(encoding="utf-8"))


# ══ construir_transferidos ════════════════════════════════════════════════

def test_so_entra_quem_foi_transferido():
    turmas = _base(); turmas["A"][2]["Situação"] = "Transferido"; turmas["A"][2]["Data Matricula"] = "31/03/2026"
    transf, resumo, _ = dt.construir_transferidos(turmas)
    assert list(transf) == ["3"]
    assert transf["3"]["data_transferencia"] == "31/03/2026" and transf["3"]["chamada"] == 3
    assert transf["3"]["guia"]["emitido_em"] is None and transf["3"]["retorno"] is None
    assert (resumo["alunos"], resumo["ativos"], resumo["transferidos_atuais"]) == (11, 10, 1)


def test_exemplo_do_usuario_transferido_e_retornou():
    """3 - FULANO - (31/03/2026) Transferido  →  31 - FULANO - (22/08/2026) Matriculado."""
    turmas = {"A": [_al(3, "777", "FULANO DA SILVA", "10/10/2014", "Transferido", "31/03/2026"),
                    _al(31, "777", "FULANO DA SILVA", "10/10/2014", "Matriculado", "22/08/2026"),
                    _al(1, "1", "OUTRO ALUNO")]}
    transf, resumo, _ = dt.construir_transferidos(turmas)
    assert list(transf) == ["777"]                                           # não foi ignorado
    assert transf["777"]["retorno"] == {"chamada": 31, "turma": "A", "data": "22/08/2026"}
    assert (resumo["alunos"], resumo["ativos"], resumo["transferidos_atuais"], resumo["retornaram"]) == (2, 2, 0, 1)


def test_retorno_em_outra_turma_tambem_e_o_mesmo_aluno():
    turmas = {"A": [_al(3, "777", "FULANO DA SILVA", "10/10/2014", "Transferido", "31/03/2026")],
              "B": [_al(31, "777", "FULANO DA SILVA", "10/10/2014", "Matriculado", "22/08/2026")]}
    transf, resumo, _ = dt.construir_transferidos(turmas)
    assert transf["777"]["retorno"]["turma"] == "B" and resumo["alunos"] == 1 and resumo["transferidos_atuais"] == 0


def test_a_data_decide_nao_o_numero_da_chamada():
    """Retorno com N MENOR que o da transferência: vale a data (22/08 é depois de 31/03)."""
    turmas = {"A": [_al(31, "777", "FULANO", "10/10/2014", "Transferido", "31/03/2026"),
                    _al(3, "777", "FULANO", "10/10/2014", "Matriculado", "22/08/2026")]}
    transf, resumo, _ = dt.construir_transferidos(turmas)
    assert transf["777"]["retorno"]["chamada"] == 3 and resumo["transferidos_atuais"] == 0


def test_transferido_depois_do_retorno_volta_a_contar_como_transferido():
    turmas = {"A": [_al(3, "777", "FULANO", "10/10/2014", "Transferido", "31/03/2026"),
                    _al(31, "777", "FULANO", "10/10/2014", "Matriculado", "22/08/2026"),
                    _al(32, "777", "FULANO", "10/10/2014", "Transferido", "15/10/2026")]}
    transf, resumo, avisos = dt.construir_transferidos(turmas)
    assert transf["777"]["data_transferencia"] == "15/10/2026" and transf["777"]["retorno"] is None
    assert transf["777"]["transferencias_anteriores"] == [{"chamada": 3, "turma": "A", "data": "31/03/2026"}]
    assert (resumo["alunos"], resumo["transferidos_atuais"]) == (1, 1) and avisos


def test_mesmo_nome_com_nascimento_diferente_sao_alunos_diferentes():
    turmas = {"A": [_al(1, "1", "MARIA SILVA", "01/01/2015", "Transferido", "10/03/2026"),
                    _al(2, "2", "MARIA SILVA", "02/02/2015", "Matriculado", "05/02/2026")]}
    transf, resumo, _ = dt.construir_transferidos(turmas)
    assert list(transf) == ["1"] and resumo["alunos"] == 2 and resumo["transferidos_atuais"] == 1


def test_nome_com_acento_ou_caixa_diferente_e_o_mesmo_aluno():
    turmas = {"A": [_al(3, "777", "JOÃO  DA SILVA", "10/10/2014", "Transferido", "31/03/2026"),
                    _al(31, "777", "Joao da Silva", "10/10/2014", "Matriculado", "22/08/2026")]}
    assert dt.construir_transferidos(turmas)[1]["alunos"] == 1


def test_linha_lida_duas_vezes_nao_duplica():
    linha = _al(3, "777", "FULANO", "10/10/2014", "Transferido", "31/03/2026")
    transf, resumo, _ = dt.construir_transferidos({"A": [linha, dict(linha)]})
    assert len(transf) == 1 and resumo["alunos"] == 1 and "transferencias_anteriores" not in transf["777"]


def test_situacao_em_minusculas_tambem_e_transferido():
    transf, _, _ = dt.construir_transferidos({"A": [_al(1, "1", "ALUNO", sit="transferido", data="10/03/2026")]})
    assert list(transf) == ["1"]


def test_transferido_sem_cgm_e_avisado_e_ignorado():
    transf, _, avisos = dt.construir_transferidos({"A": [_al(1, "", "ALUNO", sit="Transferido", data="10/03/2026")]})
    assert transf == {} and avisos


# ══ garantir_transferidos_json ════════════════════════════════════════════

def test_cria_o_arquivo_quando_nao_existe(tmp_path):
    turmas = _base(); turmas["A"][2]["Situação"] = "Transferido"
    (tmp_path / "turmas.json").write_text(json.dumps(turmas), encoding="utf-8")
    assert dt.garantir_transferidos_json(tmp_path)["transferidos_atuais"] == 1
    assert list(_ler(tmp_path, "transferidos.json")) == ["3"]


def test_cria_arquivo_vazio_se_ninguem_foi_transferido(tmp_path):
    (tmp_path / "turmas.json").write_text(json.dumps(_base()), encoding="utf-8")
    dt.garantir_transferidos_json(tmp_path)
    assert _ler(tmp_path, "transferidos.json") == {}


def test_nao_mexe_em_arquivo_existente(tmp_path):
    existente = {"9": {"nome": "X", "guia": {"emitido_em": "2026-09-01T10:00:00"}}}
    (tmp_path / "transferidos.json").write_text(json.dumps(existente), encoding="utf-8")
    turmas = _base(); turmas["A"][2]["Situação"] = "Transferido"
    (tmp_path / "turmas.json").write_text(json.dumps(turmas), encoding="utf-8")
    assert dt.garantir_transferidos_json(tmp_path) is None
    assert _ler(tmp_path, "transferidos.json") == existente


def test_sem_turmas_json_levanta_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="turmas"):
        dt.garantir_transferidos_json(tmp_path)


# ══ detectar_mudancas ═════════════════════════════════════════════════════

def test_sem_turmas_anterior_nao_deteta_nada():
    assert dt.detectar_mudancas({}, _base()) == ([], [], [])


def test_matriculado_que_virou_transferido():
    antigo, novo = _base(), _copia(_base())
    novo["A"][2]["Situação"] = "Transferido"; novo["A"][2]["Data Matricula"] = "31/03/2026"
    eventos, _, _ = dt.detectar_mudancas(antigo, novo)
    assert [(e["cgm"], e["motivo"], e["turma"], e["data_transferencia"]) for e in eventos] == \
           [("3", "situacao_mudou", "A", "31/03/2026")]


def test_ja_transferido_na_coleta_anterior_nao_gera_evento():
    antigo = _base(); antigo["A"][0]["Situação"] = "Transferido"
    assert dt.detectar_mudancas(antigo, _copia(antigo))[0] == []


def test_aluno_que_ja_retornou_nao_gera_evento():
    turmas = {"A": [_al(3, "777", "FULANO", "10/10/2014", "Transferido", "31/03/2026"),
                    _al(31, "777", "FULANO", "10/10/2014", "Matriculado", "22/08/2026")]}
    eventos, retornados, _ = dt.detectar_mudancas(turmas, _copia(turmas))
    assert eventos == [] and retornados == ["777"]


def test_aluno_que_sumiu_da_lista():
    antigo, novo = _base(), _copia(_base())
    del novo["A"][4]
    assert [(e["cgm"], e["motivo"]) for e in dt.detectar_mudancas(antigo, novo)[0]] == [("5", "saiu_da_lista")]


def test_mudanca_de_turma_nao_e_saida():
    antigo, novo = _base(), _copia(_base())
    novo["B"].append(novo["A"].pop(0))
    assert dt.detectar_mudancas(antigo, novo)[0] == []


@pytest.mark.parametrize("alterar", [lambda n: n.update(B=[]), lambda n: n.pop("B")])
def test_turma_vazia_ou_ausente_nao_gera_saidas(alterar):
    antigo, novo = _base(), _copia(_base())
    alterar(novo)
    eventos, _, avisos = dt.detectar_mudancas(antigo, novo)
    assert eventos == [] and avisos


def test_saida_em_massa_suspende_saiu_da_lista():
    antigo, novo = _base(10), _copia(_base(10))
    novo["A"] = novo["A"][:6]
    eventos, _, avisos = dt.detectar_mudancas(antigo, novo)
    assert eventos == [] and any("suspensa" in a for a in avisos)


def test_saida_em_massa_nao_suspende_mudanca_de_situacao():
    antigo, novo = _base(10), _copia(_base(10))
    for a in novo["A"][:5]:
        a["Situação"] = "Transferido"
    assert len(dt.detectar_mudancas(antigo, novo)[0]) == 5


# ══ processo_transferidos.json / sincronização ════════════════════════════

def _rodar(pasta, antigo, novo):
    return dt.processar_mudancas_de_turmas(antigo, novo, dados_dir=pasta)


def test_primeira_coleta_ja_cria_transferidos_json(tmp_path):
    """O equívoco anterior: sem coleta antiga, o arquivo não era criado."""
    novo = _base(); novo["A"][2]["Situação"] = "Transferido"
    r = _rodar(tmp_path, {}, novo)
    assert r["criado"] and r["erro"] is None and list(_ler(tmp_path, "transferidos.json")) == ["3"]


def test_fluxo_deteta_registra_e_sincroniza(tmp_path):
    antigo, novo = _base(), _copia(_base())
    (tmp_path / "transferidos.json").write_text("{}", encoding="utf-8")        # já existia (vazio)
    novo["A"][2]["Situação"] = "Transferido"; novo["A"][2]["Data Matricula"] = "31/03/2026"
    r = _rodar(tmp_path, antigo, novo)
    assert (r["novos"], r["sincronizados"], r["erro"]) == (1, 1, None)
    assert _ler(tmp_path, dt.NOME_PROCESSO_JSON)["3"]["status"] == dt.STATUS_SINCRONIZADO
    reg = _ler(tmp_path, "transferidos.json")["3"]
    assert (reg["nome"], reg["turma"], reg["chamada"], reg["data_transferencia"]) == ("ALUNO 3", "A", 3, "31/03/2026")


def test_idempotente_rodar_duas_vezes(tmp_path):
    antigo, novo = _base(), _copia(_base())
    novo["A"][2]["Situação"] = "Transferido"
    _rodar(tmp_path, antigo, novo)
    r2 = _rodar(tmp_path, antigo, novo)
    assert (r2["novos"], r2["sincronizados"], r2["criado"]) == (0, 0, False)
    assert len(_ler(tmp_path, "transferidos.json")) == 1


def test_nao_altera_registro_existente(tmp_path):
    existente = {"3": {"nome": "ALUNO 3", "turma": "A", "guia": {"emitido_em": "2026-09-01T10:00:00"}}}
    (tmp_path / "transferidos.json").write_text(json.dumps(existente), encoding="utf-8")
    antigo, novo = _base(), _copia(_base())
    novo["A"][2]["Situação"] = "Transferido"
    assert _rodar(tmp_path, antigo, novo)["sincronizados"] == 0
    assert _ler(tmp_path, "transferidos.json") == existente


def test_aluno_que_retorna_fica_marcado_e_nao_e_apagado(tmp_path):
    antigo, novo = _base(), _copia(_base())
    novo["A"][2]["Situação"] = "Transferido"; novo["A"][2]["Data Matricula"] = "31/03/2026"
    _rodar(tmp_path, antigo, novo)
    voltou = _copia(novo)
    voltou["A"].append(_al(31, "3", "ALUNO 3", "01/01/2015", "Matriculado", "22/08/2026"))
    _rodar(tmp_path, novo, voltou)
    assert _ler(tmp_path, dt.NOME_PROCESSO_JSON)["3"]["status"] == dt.STATUS_RETORNOU
    assert "3" in _ler(tmp_path, "transferidos.json")


def test_erro_nao_propaga(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "registrar_no_processo", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falha simulada")))
    antigo, novo = _base(), _copia(_base())
    novo["A"][2]["Situação"] = "Transferido"
    assert "falha simulada" in _rodar(tmp_path, antigo, novo)["erro"]


def test_esquema_base_igual_ao_de_processo_transferidos():
    pt = pytest.importorskip("src.automacao.processo_transferidos")   # precisa de credenciais/playwright
    assert dt._registro_vazio("N", "T") == pt._registro_vazio("N", "T")

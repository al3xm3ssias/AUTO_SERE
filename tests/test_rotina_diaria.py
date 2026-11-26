"""Testes de src/automacao/rotina_diaria.py (calendário em pasta temporária, sem internet, sem SERE)."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.automacao import rotina_diaria as rd  # noqa: E402
from src.web.api import calendario as cal  # noqa: E402


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(cal._paths, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(rd.paths, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(rd.paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(rd.paths, "dados_ano_atual", lambda: tmp_path / "2026")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    (tmp_path / "2026").mkdir()
    (tmp_path / "calendario" / "feriados_cache").mkdir(parents=True)
    (tmp_path / "calendario" / "feriados_cache" / "2026.json").write_text(
        json.dumps([{"date": "2026-04-21", "name": "Tiradentes"}]), encoding="utf-8")
    (tmp_path / "2026" / "calendario.json").write_text(json.dumps({
        "periodos": [{"id": "a", "nome": "1º semestre", "tipo": "letivo", "inicio": "2026-02-02", "fim": "2026-07-10"},
                     {"id": "b", "nome": "Férias", "tipo": "ferias", "inicio": "2026-07-11", "fim": "2026-07-31"},
                     {"id": "c", "nome": "2º semestre", "tipo": "letivo", "inicio": "2026-08-03", "fim": "2026-12-18"}],
        "eventos": [{"id": "e", "nome": "Conselho de classe", "tipo": "htpc", "inicio": "2026-03-10", "fim": "2026-03-10"}],
    }), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("dia,esperado", [
    (date(2026, 3, 9), True),      # segunda, período letivo
    (date(2026, 3, 7), False),     # sábado
    (date(2026, 4, 21), False),    # feriado nacional
    (date(2026, 3, 10), False),    # HTPC cadastrado
    (date(2026, 7, 15), False),    # férias
    (date(2026, 1, 20), False),    # antes do início das aulas
    (date(2026, 9, 15), False),    # aniversário da cidade (fixo)
    (date(2026, 11, 9), True),
])
def test_dia_letivo(ambiente, dia, esperado):
    assert rd.dia_letivo(dia)[0] is esperado


def _t(*alunos):
    return {"1º Ano": [{"CGM": c, "Nome": n, "Data Nasc.": "01/01/2015", "Situação": s, "Data Matricula": "01/02/2026"}
                       for c, n, s in alunos]}


def test_mudancas(ambiente):
    antes = _t(("1", "Ana", "Matriculado"), ("2", "Bia", "Matriculado"), ("3", "Cris", "Transferido"))
    depois = _t(("1", "Ana", "Matriculado"), ("2", "Bia", "Transferido"), ("3", "Cris", "Matriculado"),
                ("4", "Duda", "Matriculado"))
    r = rd.comparar_turmas(antes, depois)
    assert r["novos"] == ["4"] and r["transferidos"] == ["2"] and r["retornaram"] == ["3"]
    assert rd.comparar_turmas(antes, antes) == {"primeira_coleta": False, "novos": [], "transferidos": [], "retornaram": [],
                                                "sumiram": [], "eventos": []}
    assert rd.comparar_turmas({}, depois)["primeira_coleta"] is True


def test_virada_de_ano_uma_vez_por_ano(ambiente, monkeypatch):
    chamadas = []
    from src.comum import ano_letivo
    monkeypatch.setattr(ano_letivo, "trocar_ano", lambda novo=None: chamadas.append(novo) or {"antigo": "2026", "novo": "2027"})
    monkeypatch.setattr(rd.paths, "garantir_diretorios_runtime", lambda: None)
    assert rd.garantir_ano_letivo(date(2026, 11, 9))["acao"] in ("nada", "novo_ano")
    assert chamadas == []
    assert rd.garantir_ano_letivo(date(2027, 2, 1))["acao"] == "virou"
    assert chamadas == [None]
    monkeypatch.setattr(rd.paths, "ano_atual", lambda: "2026")           # usuário voltou a 2026 de propósito
    assert rd.garantir_ano_letivo(date(2027, 2, 2))["acao"] == "voltado_de_proposito"
    assert len(chamadas) == 1


def test_ano_fixado_por_ambiente(ambiente, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2026")
    assert rd.garantir_ano_letivo(date(2027, 2, 1))["acao"] == "fixado_por_ambiente"


def test_alunos_pula_sem_alunos_novos_e_roda_so_com_os_novos(ambiente, monkeypatch):
    rodados = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: rodados.extend(cmds) or [0] * len(cmds))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    pasta = ambiente / "2026"
    (pasta / "alunos.json").write_text('[{"CGM": "1"}]', encoding="utf-8")
    (pasta / "alunos_completo.json").write_text('{"1": {}}', encoding="utf-8")
    rd._marcar(ctx, "turmas", ok=True, mudou=True, transferidos=["9"])           # só transferido: ninguém novo
    assert rd.etapa_alunos(ctx) == 0 and rodados == []
    rd._gravar_fila(ctx, {"alunos": ["111", "222"], "alunos_todos": False, "origem": [], "avisos": []})
    assert rd.etapa_alunos(ctx) == 0
    assert rodados == [["alunos", "--modo", "basico", "--cgms", "111,222"],
                       ["alunos", "--modo", "completo", "--rapido", "--cgms", "111,222"]]
    assert rd._fila()["alunos"] == []                                              # saiu da fila: foi coletado
    assert rd._estado_etapa(ctx, "alunos") == "ok"


def test_alunos_coleta_todos_na_primeira_coleta_ou_sem_arquivo(ambiente, monkeypatch):
    rodados = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: rodados.extend(cmds) or [0] * len(cmds))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._marcar(ctx, "turmas", ok=True, mudou=True)
    rd._gravar_fila(ctx, {"alunos": [], "alunos_todos": True, "origem": [], "avisos": []})
    assert rd.etapa_alunos(ctx) == 0
    assert rodados == [["alunos", "--modo", "basico"], ["alunos", "--modo", "completo", "--rapido"]]
    assert rd._fila()["alunos_todos"] is False
    # novos na fila, mas ainda não existe alunos.json: não dá para mesclar → coleta todos
    rodados.clear()
    rd._gravar_fila(ctx, {"alunos": ["111"], "alunos_todos": False, "origem": [], "avisos": []})
    rd.etapa_alunos(ctx)
    assert rodados == [["alunos", "--modo", "basico"], ["alunos", "--modo", "completo", "--rapido"]]


def test_alunos_falhou_deixa_os_novos_na_fila(ambiente, monkeypatch):
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: [1] * len(cmds))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._marcar(ctx, "turmas", ok=True, mudou=True)
    rd._gravar_fila(ctx, {"alunos": ["111"], "alunos_todos": False, "origem": ["111"], "avisos": []})
    assert rd.etapa_alunos(ctx) == 1
    assert rd._fila()["alunos"] == ["111"] and rd._estado_etapa(ctx, "alunos") == "falhou"


def test_alunos_nao_roda_sem_turmas_de_hoje(ambiente, monkeypatch):
    monkeypatch.setattr(rd, "_executar", lambda *a: pytest.fail("não deveria executar"))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._gravar_fila(ctx, {"alunos": ["111"], "alunos_todos": False, "origem": [], "avisos": []})
    assert rd.etapa_alunos(ctx) == 0
    assert rd._estado_etapa(ctx, "alunos") == "pulada"


def test_consultas_em_simultaneo(ambiente, monkeypatch):
    lotes = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: lotes.append(cmds) or [0] * len(cmds))
    assert rd.etapa_consultas(rd.Ctx(hoje=date(2026, 11, 9))) == 0
    assert lotes == [[["cep"], ["sus"]]]            # um único lote = os dois ao mesmo tempo


def test_main_sem_aula_nao_executa(ambiente, monkeypatch):
    monkeypatch.setattr(rd, "_executar", lambda *a: pytest.fail("não deveria executar"))
    assert rd.main(["turmas", "--data", "2026-07-15"]) == 0


# ───────────────────────── etapa turmas: comparação, fila e retomada ─────────────────────────
def _grava_turmas(pasta, *alunos):
    pasta.joinpath("turmas.json").write_text(json.dumps(
        {"1º Ano": [{"CGM": c, "Nome": n, "Situação": sit} for c, n, sit in alunos]}), encoding="utf-8")


def _simula_coleta(monkeypatch, pasta, *alunos, rc=0):
    def falso(ctx, etapa, cmds):
        if alunos:
            _grava_turmas(pasta, *alunos)
        return [rc] * len(cmds)
    monkeypatch.setattr(rd, "_executar", falso)


def test_turmas_registra_mudancas_enfileira_e_separa_sumido_de_transferido(ambiente, monkeypatch):
    pasta = ambiente / "2026"
    fixos = tuple((str(n), f"Aluno {n}", "Matriculado") for n in range(10, 30))     # base grande: não dispara a trava de saída em massa
    _grava_turmas(pasta, ("1", "Ana", "Matriculado"), ("2", "Bia", "Matriculado"), ("3", "Cris", "Matriculado"), *fixos)
    _simula_coleta(monkeypatch, pasta, ("1", "Ana", "Matriculado"), ("2", "Bia", "Transferido"), ("4", "Duda", "Matriculado"), *fixos)
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_turmas(ctx) == 0
    reg = json.loads((pasta / "rotina_estado.json").read_text(encoding="utf-8"))["turmas"]
    assert reg["ok"] and reg["mudou"] and reg["novos"] == ["4"]
    assert reg["transferidos"] == ["2"]                  # a situação mudou para Transferido
    assert reg["sumiram"] == ["3"]                       # Cris sumiu da lista: NÃO é transferência
    assert {(e["cgm"], e["motivo"]) for e in reg["eventos"]} == {("2", "situacao_mudou"), ("3", "saiu_da_lista")}
    fila = rd._fila()
    assert fila["alunos"] == ["4"] and fila["origem"] == ["4"] and len(fila["avisos"]) == 2 and fila["alunos_todos"] is False


def test_turmas_primeira_coleta_pede_todos_e_nao_busca_origem(ambiente, monkeypatch):
    pasta = ambiente / "2026"
    _simula_coleta(monkeypatch, pasta, ("1", "Ana", "Matriculado"), ("2", "Bia", "Matriculado"))
    assert rd.etapa_turmas(rd.Ctx(hoje=date(2026, 2, 2))) == 0
    fila = rd._fila()
    assert fila["alunos_todos"] is True and fila["alunos"] == [] and fila["origem"] == []


def test_turmas_repetida_no_mesmo_dia_nao_perde_o_que_achou_nem_enfileira_de_novo(ambiente, monkeypatch):
    pasta = ambiente / "2026"
    _grava_turmas(pasta, ("1", "Ana", "Matriculado"))
    _simula_coleta(monkeypatch, pasta, ("1", "Ana", "Matriculado"), ("4", "Duda", "Matriculado"))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd.etapa_turmas(ctx)
    fila = rd._fila(); fila["alunos"] = []; rd._gravar_fila(ctx, fila)             # a etapa de alunos já consumiu
    rd.etapa_turmas(ctx)                                                           # segunda execução: arquivo igual ao de agora
    reg = json.loads((pasta / "rotina_estado.json").read_text(encoding="utf-8"))["turmas"]
    assert reg["novos"] == ["4"] and reg["mudou"] is True                         # o registro do dia continua valendo
    assert rd._fila()["alunos"] == []                                              # e não voltou para a fila


def test_turmas_com_falha_ou_vazia_nao_conta_como_sucesso(ambiente, monkeypatch):
    pasta = ambiente / "2026"
    _simula_coleta(monkeypatch, pasta, rc=1)
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_turmas(ctx) == 1 and rd._estado_etapa(ctx, "turmas") == "falhou"
    pasta.joinpath("turmas.json").write_text(json.dumps({"1º Ano": []}), encoding="utf-8")
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: [0] * len(cmds))
    assert rd.etapa_turmas(ctx) == 1 and rd._estado_etapa(ctx, "turmas") == "falhou"


# ───────────────────────── pré-matrícula, origem, avisos, planilha ─────────────────────────
def test_prematricula_roda_sem_whatsapp_por_padrao(ambiente, monkeypatch):
    rodados = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: rodados.extend(cmds) or [0])
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_prematricula(ctx) == 0 and rodados == [["prematricula_completa", "--sem-whatsapp"]]
    monkeypatch.setattr(rd, "PREMATRICULA_AVISAR_WHATSAPP", True)
    rodados.clear()
    rd.etapa_prematricula(ctx)
    assert rodados == [["prematricula_completa"]]
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: [1])
    assert rd.etapa_prematricula(ctx) == 1


def test_origem_so_com_alunos_novos_e_so_os_novos(ambiente, monkeypatch):
    rodados = []
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: rodados.extend(cmds) or [0])
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_origem(ctx) == 0 and rodados == [] and rd._estado_etapa(ctx, "origem") == "pulada"
    rd._gravar_fila(ctx, {"alunos": [], "alunos_todos": False, "origem": ["111", "222"], "avisos": []})
    assert rd.etapa_origem(ctx) == 0
    assert rodados == [["base_abc", "--alunos-texto", "111\n222"]] and rd._fila()["origem"] == []


def test_origem_nao_roda_se_alunos_falhou_e_mantem_a_fila_se_ela_mesma_falhar(ambiente, monkeypatch):
    monkeypatch.setattr(rd, "_executar", lambda *a: pytest.fail("não deveria executar"))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._gravar_fila(ctx, {"alunos": [], "alunos_todos": False, "origem": ["111"], "avisos": []})
    rd._marcar(ctx, "alunos", ok=False)
    assert rd.etapa_origem(ctx) == 0 and rd._fila()["origem"] == ["111"]
    rd._marcar(ctx, "alunos", ok=True)
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: [1])
    assert rd.etapa_origem(ctx) == 1 and rd._fila()["origem"] == ["111"]


def test_comparar_resultados_de_sisreg_e_cep():
    antes = [{"cgm": "1", "encaminhamentos": []}, {"cgm": "2", "encaminhamentos": ["a"]}, {"cgm": "3", "encaminhamentos": []}]
    depois = [{"cgm": "1", "encaminhamentos": []}, {"cgm": "2", "encaminhamentos": ["a", "b"]}, {"cgm": "4", "encaminhamentos": []}]
    r = rd.comparar_resultados(antes, depois)
    assert r["mudou"] and r["novos"] == ["4"] and r["removidos"] == ["3"] and r["alterados"] == ["2"]
    assert rd.comparar_resultados(antes, antes)["mudou"] is False
    assert rd.comparar_resultados(None, antes) == {"mudou": False, "primeira_execucao": True}
    cep_a = {"metadados": {"data_analise": "ontem"}, "alunos": [{"Nome": "Ana", "CEP": "1"}]}
    cep_b = {"metadados": {"data_analise": "hoje"}, "alunos": [{"Nome": "Ana", "CEP": "1"}]}
    assert rd.comparar_resultados(cep_a, cep_b)["mudou"] is False      # só os metadados mudaram


def test_consultas_registra_o_que_mudou(ambiente, monkeypatch):
    pasta = ambiente / "2026"
    (pasta / "alunos_encaminhamento.json").write_text(json.dumps([{"cgm": "1", "encaminhamentos": []}]), encoding="utf-8")

    def falso(ctx, etapa, cmds):
        (pasta / "alunos_encaminhamento.json").write_text(json.dumps(
            [{"cgm": "1", "encaminhamentos": ["x"]}, {"cgm": "2", "encaminhamentos": []}]), encoding="utf-8")
        (pasta / "alunos_fora_raio.json").write_text(json.dumps({"metadados": {}, "alunos": []}), encoding="utf-8")
        return [0, 0]
    monkeypatch.setattr(rd, "_executar", falso)
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_consultas(ctx) == 0
    reg = json.loads((pasta / "rotina_estado.json").read_text(encoding="utf-8"))["consultas"]
    assert reg["ok"] and reg["sisreg"]["mudou"] and reg["sisreg"]["novos"] == ["2"] and reg["sisreg"]["alterados"] == ["1"]
    assert reg["cep"]["primeira_execucao"] is True                     # não havia resultado de CEP antes
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, cmds: [0, 1])
    assert rd.etapa_consultas(ctx) == 1
    reg = json.loads((pasta / "rotina_estado.json").read_text(encoding="utf-8"))["consultas"]
    assert "sisreg" not in reg and "cep" in reg                        # a que falhou não é comparada


def test_avisos_so_cria_quando_ha_transferidos_e_nao_duplica(ambiente):
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._marcar(ctx, "turmas", ok=True, mudou=True)
    assert rd.etapa_avisos(ctx) == 0                                               # fila vazia: nada a avisar
    assert not (ambiente / "2026" / "painel_avisos.json").exists()
    ev = {"cgm": "2", "nome": "Bia", "turma": "1º Ano", "motivo": "situacao_mudou", "data_transferencia": "10/11/2026"}
    rd._gravar_fila(ctx, {"alunos": [], "alunos_todos": False, "origem": [], "avisos": [ev]})
    assert rd.etapa_avisos(ctx) == 0
    from src.comum import painel_avisos as pa
    avisos = pa.carregar(ambiente / "2026")
    assert len(avisos) == 1 and avisos[0]["tipo"] == "transferencia" and avisos[0]["cgm"] == "2"
    assert rd._fila()["avisos"] == []
    rd._gravar_fila(ctx, {"alunos": [], "alunos_todos": False, "origem": [], "avisos": [ev]})   # a mesma saída de novo
    rd.etapa_avisos(ctx)
    assert len(pa.carregar(ambiente / "2026")) == 1


def test_avisos_nao_roda_sem_turmas_de_hoje(ambiente):
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    ev = {"cgm": "2", "nome": "Bia", "turma": "1º Ano", "motivo": "situacao_mudou", "data_transferencia": "10/11/2026"}
    rd._gravar_fila(ctx, {"alunos": [], "alunos_todos": False, "origem": [], "avisos": [ev]})
    assert rd.etapa_avisos(ctx) == 0 and rd._fila()["avisos"] == [ev]


def test_planilha_nao_roda_se_alunos_falhou(ambiente, monkeypatch):
    monkeypatch.setattr(rd, "_executar", lambda *a: pytest.fail("não deveria executar"))
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    rd._marcar(ctx, "turmas", ok=True, mudou=True)
    rd._marcar(ctx, "alunos", ok=False)
    assert rd.etapa_planilha(ctx) == 0 and rd._estado_etapa(ctx, "planilha") == "pulada"


# ───────────────────────── sequência única, falhas e nova tentativa ─────────────────────────
def _etapas_falsas(monkeypatch, resultados=None, ordem=None):
    resultados = resultados or {}
    ordem = ordem if ordem is not None else []
    novos = {}
    for nome in rd._ETAPAS:
        def etapa(ctx, nome=nome):
            ordem.append(nome)
            rc = resultados.get(nome, 0)
            rd._marcar(ctx, nome, ok=rc == 0)
            return rc
        novos[nome] = etapa
    monkeypatch.setattr(rd, "_ETAPAS", novos)
    return ordem


def test_sequencia_roda_na_ordem_pedida(ambiente, monkeypatch):
    ordem = _etapas_falsas(monkeypatch)
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_sequencia(ctx) == 0
    assert ordem == ["turmas", "alunos", "prematricula", "origem", "consultas", "avisos", "planilha"]
    assert rd._estado_etapa(ctx, "sequencia") == "ok"


def test_sequencia_para_se_turmas_falha(ambiente, monkeypatch):
    ordem = _etapas_falsas(monkeypatch, {"turmas": 1})
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    assert rd.etapa_sequencia(ctx) == 1 and ordem == ["turmas"]
    reg = json.loads((ambiente / "2026" / "rotina_estado.json").read_text(encoding="utf-8"))["sequencia"]
    assert reg["ok"] is False and reg["interrompida_em"] == "turmas" and reg["etapas"]["planilha"] == "nao_executada"


def test_sequencia_segue_depois_de_etapa_opcional_que_falhou_mas_devolve_1(ambiente, monkeypatch):
    ordem = _etapas_falsas(monkeypatch, {"prematricula": 1})
    assert rd.etapa_sequencia(rd.Ctx(hoje=date(2026, 11, 9))) == 1
    assert ordem[-1] == "planilha" and "consultas" in ordem


def test_sequencia_retoma_de_onde_parou(ambiente, monkeypatch):
    ctx = rd.Ctx(hoje=date(2026, 11, 9))
    ordem = _etapas_falsas(monkeypatch, {"alunos": 1})
    assert rd.etapa_sequencia(ctx) == 1 and ordem == ["turmas", "alunos"]
    ordem.clear()
    monkeypatch.setattr(rd, "_ETAPAS", {**rd._ETAPAS})                              # alunos agora dá certo
    _etapas_falsas(monkeypatch, {}, ordem)
    assert rd.etapa_sequencia(ctx) == 0
    assert ordem == ["alunos", "prematricula", "origem", "consultas", "avisos", "planilha"]     # turmas não repete
    ordem.clear()
    assert rd.etapa_sequencia(rd.Ctx(hoje=date(2026, 11, 9), forcar=True)) == 0
    assert ordem[0] == "turmas"                                                     # --forcar refaz tudo


def test_sequencia_trata_excecao_de_etapa_como_falha(ambiente, monkeypatch):
    def estoura(ctx):
        raise RuntimeError("boom")
    ordem = _etapas_falsas(monkeypatch)
    rd._ETAPAS["prematricula"] = estoura
    assert rd.etapa_sequencia(rd.Ctx(hoje=date(2026, 11, 9))) == 1
    assert "planilha" in ordem


def test_executar_repete_so_o_que_falhou_e_nao_repete_pedido_invalido(ambiente, monkeypatch):
    chamadas = []

    class Proc:
        def __init__(self, rc): self.rc = rc
        def wait(self, timeout=None): return self.rc
        def kill(self): pass

    codigos = {"a": [1, 0], "b": [2], "c": [0]}

    def lancar(etapa, c, env, flags):
        chamadas.append(c[0])
        import io
        return Proc(codigos[c[0]].pop(0)), io.StringIO()
    monkeypatch.setattr(rd, "_lancar", lancar)
    monkeypatch.setattr(rd.time, "sleep", lambda s: None)
    monkeypatch.setattr(rd.paths, "LOGS_DIR", ambiente / "logs")
    r = rd._executar(rd.Ctx(hoje=date(2026, 11, 9)), "x", [["a"], ["b"], ["c"]])
    assert r == [0, 2, 0]
    assert sorted(chamadas) == ["a", "a", "b", "c"]          # só o "a" (código 1) foi repetido

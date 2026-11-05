"""Registro de scripts: planos de execução, componentes, prévia, CGM e as rotas que os usam."""
import time

import pytest

from src.comum import opcoes_execucao as oe
from src.comum import registro_scripts as reg
from src.comum.execucao_gui import ExecucaoEmBackground
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app


def _al(cgm, nome, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": sit}


TURMAS = {
    "3º Ano Integral A": [_al("3000000001", "Ana"), _al("3000000002", "Beto", "Transferido")],
    "3º Ano Integral B": [_al("3000000003", "Caio")],
    "5º Ano Integral A": [_al("5000000001", "Duda")],
}


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    planos = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: planos.append((chave, plano)))
    return create_app().test_client(), planos, tmp_path


def _post(c, chave, **payload):
    return c.post(f"/web/api/automacoes/{chave}/executar", json=payload)


# ───────────── consistência do registro ─────────────

def test_todo_script_registrado_esta_na_lista_de_automacoes():
    chaves = {i["chave"] for i in rotas.AUTOMACOES_DISPONIVEIS}
    assert set(reg.REGISTRO) <= chaves
    assert not (set(reg.REGISTRO) & rotas.AUTOMACOES_NAO_IMPLEMENTADAS)


def test_recursos_declarados_existem():
    validos = {oe.RECURSO_TURMA, oe.RECURSO_SITUACAO, oe.RECURSO_CGM, oe.RECURSO_TESTE, oe.RECURSO_ERROS, oe.RECURSO_DEBUG}
    for s in reg.REGISTRO.values():
        assert set(s.recursos) <= validos, s.chave


def test_nao_registra_duas_vezes():
    with pytest.raises(ValueError, match="já registrado"):
        reg.registrar(reg.REGISTRO["validar"])


def test_script_novo_ganha_tudo_so_registrando(monkeypatch):
    """O objetivo do registro: um script novo é só declarar recursos + plano."""
    monkeypatch.setitem(reg.REGISTRO, "novo", reg.Script(
        "novo", (oe.RECURSO_TURMA, oe.RECURSO_SITUACAO, oe.RECURSO_TESTE),
        lambda o, p, tj, c: reg.Plano("sync", print, {"turmas": list(o.turmas)})))
    s = reg.obter("novo")
    assert s.usa_turmas_json and s.tem_selecao_de_alunos


# ───────────── planos ─────────────

TJ = TURMAS


def _plano(chave, payload=None, flags=()):
    s = reg.obter(chave)
    nomes = s.turmas_de() if s.turmas_de else list(TJ)
    o = oe.opcoes_do_payload(payload or {}, s.recursos, nomes)
    if s.validar_extras:
        s.validar_extras(payload or {})
    return s.planejar(o, payload or {}, TJ, {"args_flags": list(flags)})


def test_analisa_padrao_nao_manda_nada_e_preserva_as_flags_guardadas():
    p = _plano("analisa_sere", {}, flags=["--rapido"])           # CGM em branco no analisa = opcional, não é erro
    assert p.kwargs["args_extras"] == ["--rapido"]
    assert _plano("analisa_sere", {}).log_inicial == "[OPÇÕES] nenhuma — modo completo"


def test_analisa_com_selecao_explicita_substitui_as_flags_conflitantes():
    p = _plano("analisa_sere", {"turmas": ["3º Ano Integral"], "matriculados": True, "transferidos": True}, flags=["--rapido", "--todos"])
    assert p.kwargs["args_extras"] == ["--turma", "3º Ano Integral A", "3º Ano Integral B", "--matriculados", "--transferidos"]
    assert p.log_inicial.startswith("[OPÇÕES] --turma")


def test_analisa_so_transferidos():
    p = _plano("analisa_sere", {"matriculados": False, "transferidos": True})
    assert p.kwargs["args_extras"] == ["--transferidos"]


def test_analisa_por_cgm():
    p = _plano("analisa_sere", {"cgms_texto": "3000000001, 3000000003;3000000001"}, flags=["--todos"])
    assert p.kwargs["args_extras"] == ["--cgm", "3000000001", "3000000003"]     # CGM manda: sem turma/situação


def test_analisa_reprocessar_erros_ignora_selecao_e_flags():
    p = _plano("analisa_sere", {"erros": True, "turmas": ["5"], "transferidos": True}, flags=["--rapido", "--todos"])
    assert p.kwargs["args_extras"] == ["--erros"]


def test_o_argv_do_plano_e_aceito_pelo_parser_do_script():
    import src.relatorios.analisa_arquivos_sere as an
    p = _plano("analisa_sere", {"turmas": ["5º Ano Integral A"], "matriculados": True, "transferidos": True})
    ns = an.criar_parser().parse_args(p.kwargs["args_extras"])
    assert ns.turma == ["5º Ano Integral A"] and ns.matriculados and ns.transferidos


def test_validar_filtra_por_situacao_e_turma():
    p = _plano("validar", {"turmas": ["3º Ano Integral A"], "matriculados": False, "transferidos": True, "modo_teste": True})
    k = p.kwargs
    assert k["turmas_selecionadas"] == ["3º Ano Integral A"] and k["modo_teste"] is True
    assert k["somente_transferidos"] is True
    assert [a["CGM"] for a in k["turmas"]["3º Ano Integral A"]] == ["3000000002"]


def test_validar_padrao_e_todas_as_turmas_so_matriculados():
    k = _plano("validar").kwargs
    assert k["turmas_selecionadas"] == list(TJ) and k["somente_transferidos"] is False and k["modo_teste"] is False
    assert [a["CGM"] for a in k["turmas"]["3º Ano Integral A"]] == ["3000000001"]


def test_documentos_traduz_o_tipo_pelo_dicionario_oficial():
    from src.comum.sere_normalizacao import IDTIPO_PARA_SLOT
    idtipo, nome = next(iter(IDTIPO_PARA_SLOT.items()))
    k = _plano("documentos", {"idtipo": idtipo, "turmas": ["5"]}).kwargs
    assert k["idtipo"] == str(idtipo) and k["nome_slot"] == nome and k["turmas_selecionadas"] == ["5º Ano Integral A"]
    k = _plano("espec", {"idtipo": idtipo, "modo_teste": True}).kwargs
    assert k["idtipo_alvo"] == str(idtipo) and k["nome_slot"] == nome and k["modo_teste"] is True


@pytest.mark.parametrize("chave", ["documentos", "espec"])
@pytest.mark.parametrize("payload", [{}, {"idtipo": ""}, {"idtipo": "9999999"}])
def test_tipo_de_documento_obrigatorio_e_valido(chave, payload):
    with pytest.raises(ValueError, match="tipo de documento"):
        _plano(chave, payload)


def test_limpeza_so_com_a_selecao_marcada():
    k = _plano("limpeza", {"turmas": ["5"], "modo_teste": True}).kwargs
    assert k["turmas_selecionadas"] == ["5º Ano Integral A"] and k["modo_teste"] is True


def test_aluno_usa_os_cgms_da_tela_em_vez_da_lista_guardada():
    k = _plano("aluno", {"cgms_texto": "1234567890\n1234567891", "modo_teste": True, "erros": True, "faltando": True}).kwargs
    assert k == {"modo_teste": True, "modo_erros": True, "modo_faltando": True, "cgms": ["1234567890", "1234567891"]}


def test_rematricula_resolve_contra_a_lista_propria_de_turmas():
    from src.automacao.rematricula import TURMAS_ALVO
    assert _plano("rematricula").kwargs == {"modo_teste": False, "apenas_erros": False, "turmas_alvo": None}
    k = _plano("rematricula", {"turmas": ["INFANTIL 4"], "modo_teste": True, "erros": True}).kwargs
    assert k["turmas_alvo"] == ["INFANTIL 4"] and k["modo_teste"] and k["apenas_erros"]
    assert reg.obter("rematricula").turmas_de() == list(TURMAS_ALVO)


def test_prematricula_debug_vira_analise():
    assert _plano("prematricula_completa", {"debug": True, "pular_pendentes": True}).kwargs == {"analise": True, "pular_pendentes": True}
    assert _plano("prematricula_completa").kwargs == {"analise": False, "pular_pendentes": False}


def test_transferidos_so_tem_modo_teste():
    assert _plano("transferidos", {"modo_teste": True, "turmas": ["x"], "transferidos": True}).kwargs == {"modo_teste": True}


# ───────────── rotas: componentes, lista, prévia, CGM ─────────────

def test_componentes_de_script_registrado(ctx):
    c, _, _ = ctx
    r = c.get("/web/api/automacoes/validar/componentes").get_json()
    assert r["registrado"] and r["recursos"] == ["turma", "situacao", "teste"] and r["confirmar"] is True
    assert "PRIMEIRO aluno" in r["ajuda_teste"] and r["tem_turmas"] is True
    assert r["turmas"] == [{"rotulo": "3º Ano Integral", "turmas": ["3º Ano Integral A", "3º Ano Integral B"]},
                           {"rotulo": "5º Ano Integral", "turmas": ["5º Ano Integral A"]}]


def test_componentes_documentos_trazem_a_lista_de_tipos(ctx):
    c, _, _ = ctx
    r = c.get("/web/api/automacoes/documentos/componentes").get_json()
    campo = r["extras"][0]
    assert campo["nome"] == "idtipo" and len(campo["opcoes"]) > 5
    assert all({"valor", "texto"} <= set(o) for o in campo["opcoes"])


def test_componentes_sem_turmas_json_avisa(ctx):
    c, _, tmp = ctx
    (tmp / "turmas.json").unlink()
    r = c.get("/web/api/automacoes/validar/componentes").get_json()
    assert r["tem_turmas"] is False and r["usa_turmas_json"] is True


def test_componentes_de_automacao_nao_registrada(ctx):
    c, _, _ = ctx
    assert c.get("/web/api/automacoes/agendador/componentes").get_json() == {"registrado": False}   # ainda não implementada


def test_lista_expoe_os_recursos_e_as_automacoes_novas(ctx):
    c, _, _ = ctx
    itens = {i["chave"]: i for i in c.get("/web/api/automacoes/lista").get_json()["itens"]}
    assert itens["analisa_sere"]["recursos"] == ["turma", "situacao", "cgm", "erros"]
    assert "aluno" in itens and "espec" in itens
    assert itens["backup"]["recursos"] == [] and "recursos" not in itens["agendador"]          # sem registro = sem recursos


def test_previa_conta_quem_seria_processado(ctx):
    c, _, _ = ctx
    r = c.post("/web/api/automacoes/validar/previa", json={"matriculados": True, "transferidos": True}).get_json()
    assert (r["total"], r["matriculados"], r["transferidos"]) == (4, 3, 1)
    assert r["texto"] == "4 aluno(s) — 3 matriculado(s) e 1 transferido(s) — em 3 turma(s)."
    r = c.post("/web/api/automacoes/validar/previa", json={"turmas": ["3º Ano Integral"], "matriculados": False, "transferidos": True}).get_json()
    assert r["total"] == 1 and r["turmas"] == ["3º Ano Integral A"]


def test_previa_por_cgm_avisa_dos_que_nao_existem(ctx):
    c, _, _ = ctx
    r = c.post("/web/api/automacoes/aluno/previa", json={"cgms_texto": "3000000001, 9999999999"}).get_json()
    assert r["total"] == 1 and r["cgms_nao_encontrados"] == ["9999999999"]
    assert "1 de 2 CGM(s)" in r["texto"] and "9999999999" in r["texto"]


def test_previa_erros_de_validacao_viram_400_com_mensagem(ctx):
    c, _, _ = ctx
    r = c.post("/web/api/automacoes/validar/previa", json={"matriculados": False, "transferidos": False})
    assert r.status_code == 400 and "Matriculados ou Transferidos" in r.get_json()["erro"]
    r = c.post("/web/api/automacoes/validar/previa", json={"turmas": ["99"]})
    assert r.status_code == 400 and "Turma não encontrada" in r.get_json()["erro"]


def test_previa_de_automacao_sem_selecao_e_inexistente(ctx):
    c, _, _ = ctx
    assert c.post("/web/api/automacoes/agendador/previa", json={}).status_code == 404            # não registrada
    assert c.post("/web/api/automacoes/backup/previa", json={}).get_json() == {"total": None, "texto": None}
    assert c.post("/web/api/automacoes/transferidos/previa", json={}).get_json() == {"total": None, "texto": None}
    r = c.post("/web/api/automacoes/rematricula/previa", json={"turmas": ["INFANTIL 4"]}).get_json()
    assert r["turmas"] == ["INFANTIL 4"] and r["texto"] == "Turmas: INFANTIL 4."


def test_cgm_analisar(ctx):
    c, _, _ = ctx
    r = c.post("/web/api/cgm/analisar", json={"texto": "3000000001, 9999999999;\n3000000001 abc"}).get_json()
    assert r["validos"] == ["3000000001", "9999999999"] and r["invalidos"] == ["abc"] and r["repetidos"] == 1
    assert r["nao_encontrados"] == ["9999999999"]
    assert "2 CGM(s) válido(s)" in r["texto"] and "1 inválido(s): abc" in r["texto"] and "1 repetido(s)" in r["texto"]


# ───────────── rotas: executar ─────────────

def test_executar_monta_o_plano_com_as_escolhas_da_tela(ctx):
    c, planos, _ = ctx
    r = _post(c, "analisa_sere", turmas=["3º Ano Integral"], matriculados=True, transferidos=True)
    assert r.status_code == 200 and r.get_json()["status"] == "executando"
    chave, plano = planos[0]
    assert chave == "analisa_sere"
    assert plano.kwargs["args_extras"] == ["--turma", "3º Ano Integral A", "3º Ano Integral B", "--matriculados", "--transferidos"]


@pytest.mark.parametrize("chave,payload,trecho", [
    ("validar", {"matriculados": False, "transferidos": False}, "Matriculados ou Transferidos"),
    ("validar", {"turmas": ["99"]}, "Turma não encontrada: 99"),
    ("aluno", {"cgms_texto": ""}, "ao menos um CGM"),
    ("aluno", {"cgms_texto": "123456789, xx"}, "formato inválido: xx"),
    ("documentos", {}, "tipo de documento"),
])
def test_executar_recusa_pedido_invalido_com_mensagem_pronta(ctx, chave, payload, trecho):
    c, planos, _ = ctx
    r = _post(c, chave, **payload)
    assert r.status_code == 400 and trecho in r.get_json()["mensagem"] and planos == []


def test_executar_sem_turmas_json_orienta(ctx):
    c, planos, tmp = ctx
    (tmp / "turmas.json").unlink()
    r = _post(c, "validar")
    assert r.status_code == 400 and "Turmas" in r.get_json()["mensagem"] and planos == []
    assert _post(c, "aluno", cgms_texto="1234567890").status_code == 400      # CGM também precisa dele (prévia/seleção)


def test_import_quebrado_vira_resposta_amigavel_e_nao_pagina_de_erro(ctx, monkeypatch):
    c, _, _ = ctx
    def quebra(*a, **k):
        raise ImportError("cannot import name 'coisa' from 'x'")
    monkeypatch.setitem(reg.REGISTRO, "validar", reg.Script("validar", ("turma",), quebra))
    r = _post(c, "validar")
    assert r.status_code == 500 and r.is_json and "não pôde ser carregado" in r.get_json()["mensagem"]


def test_cep_usa_o_raio_padrao_do_projeto_e_aceita_virgula(ctx):
    c, planos, _ = ctx
    from src.comum.cep_api import RAIO_KM_PADRAO
    assert _post(c, "cep").status_code == 200
    assert _post(c, "cep", raio_km="2,5").status_code == 200
    assert [p.kwargs for _, p in planos] == [{"raio_km": RAIO_KM_PADRAO}, {"raio_km": 2.5}]      # antes o padrão era 3,0 (a regra é 2,0)
    assert all(p.tipo == "sync" for _, p in planos)
    for ruim in ("abc", "0", "-1", "500"):
        r = _post(c, "cep", raio_km=ruim)
        assert r.status_code == 400 and "Raio inválido" in r.get_json()["mensagem"]


# ───────────── execução de verdade (as que antes davam ImportError) ─────────────

def _esperar(c, chave, limite=10):
    fim = time.time() + limite
    while time.time() < fim:
        s = c.get(f"/web/api/automacoes/{chave}/status").get_json()
        if s["status"] != "executando":
            return s
        time.sleep(0.03)
    pytest.fail("não terminou")


def test_rematricula_e_prematricula_completa_agora_executam(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    import src.automacao.pre_matricula as pm
    import src.automacao.rematricula as rem
    chamadas = []

    async def fake_rem(**kw):
        print("rematricula simulada"); chamadas.append(("rem", kw))

    async def fake_pm(**kw):
        print("pré-matrícula simulada"); chamadas.append(("pm", kw))

    monkeypatch.setattr(rem, "rematricular_via_login", fake_rem)
    monkeypatch.setattr(pm, "processo_completo_via_login", fake_pm)
    c = create_app().test_client()

    assert _post(c, "rematricula", turmas=["INFANTIL 4"], modo_teste=True).status_code == 200
    assert _esperar(c, "rematricula")["status"] == "concluido"
    assert _post(c, "prematricula_completa", debug=True, pular_pendentes=True).status_code == 200
    assert _esperar(c, "prematricula_completa")["status"] == "concluido"
    assert chamadas == [("rem", {"modo_teste": True, "apenas_erros": False, "turmas_alvo": ["INFANTIL 4"]}),
                        ("pm", {"analise": True, "pular_pendentes": True})]


def test_script_com_wrapper_gui_executa_pela_rota(tmp_path, monkeypatch):
    """Caminho "gui" completo: opções → plano → wrapper executar_* → log na tela."""
    import json
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    import src.automacao.executar_validar as ev
    vistos = {}

    def fake_executar_validar(callback=None, **kw):
        vistos.update(kw)
        execucao = ExecucaoEmBackground(callback=callback)

        async def coro():
            alvo = kw["turmas_selecionadas"]
            print(f"validando {sum(len(kw['turmas'][t]) for t in alvo)} aluno(s)")   # só as turmas-alvo
        execucao.iniciar(coro())
        return execucao

    monkeypatch.setattr(ev, "executar_validar", fake_executar_validar)
    c = create_app().test_client()
    assert _post(c, "validar", turmas=["3º Ano Integral"], matriculados=True, transferidos=True, modo_teste=True).status_code == 200
    s = _esperar(c, "validar")
    assert s["status"] == "concluido" and "validando 3 aluno(s)" in "\n".join(s["logs"])
    assert vistos["turmas_selecionadas"] == ["3º Ano Integral A", "3º Ano Integral B"] and vistos["modo_teste"] is True


# ───────────── as automações que sobraram também passam pelo registro ─────────────

SIMPLES = {            # chave → (módulo, função) executada sem parâmetros
    "gerar_pastas": ("src.automacao.gerar_pastas", "main"),
    "analisa_pasta": ("src.relatorios.analisa_documentos_pc", "main"),
    "mapear_pastas": ("src.relatorios.mapear_pastas_alunos", "main"),
    "cruzamento": ("src.relatorios.cruzar_documentos", "main"),
    "mascara": ("src.relatorios.mascarar", "main"),
    "coleta_emails": ("src.automacao.coleta_emails", "coletar_escolas_municipais"),
    "backup": ("src.comum.backup", "executar_backup"),
}


@pytest.mark.parametrize("chave", sorted(SIMPLES))
def test_automacao_simples_roda_a_funcao_certa_sem_parametros(chave):
    import importlib
    modulo, nome = SIMPLES[chave]
    plano = reg.obter(chave).planejar(Opcoes(), {}, {}, {})
    assert plano.tipo == "sync" and plano.funcao is getattr(importlib.import_module(modulo), nome) and plano.kwargs == {}


def test_toda_automacao_implementada_esta_no_registro_e_so_as_nao_implementadas_ficam_de_fora():
    fora = {i["chave"] for i in rotas.AUTOMACOES_DISPONIVEIS} - set(reg.REGISTRO)
    assert fora == rotas.AUTOMACOES_NAO_IMPLEMENTADAS


def test_turmas_e_alunos():
    from src.automacao.alunos import coletar_alunos_via_login
    from src.automacao.alunos_completo import coletar_cadastro_completo_via_login
    from src.automacao.turmas import coletar_turmas_e_alunos_via_login
    assert reg.obter("turmas").planejar(Opcoes(), {}, {}, {}).funcao is coletar_turmas_e_alunos_via_login
    a = reg.obter("alunos")
    assert a.planejar(Opcoes(), {}, {}, {}).funcao is coletar_alunos_via_login                          # padrão: básico
    p = a.planejar(Opcoes(), {"modo": "completo", "rapido": True}, TJ, {})
    assert p.funcao is coletar_cadastro_completo_via_login and p.kwargs == {"modo_rapido": True}
    with pytest.raises(ValueError, match="ainda não existe ou está vazio"):
        a.planejar(Opcoes(), {"modo": "completo"}, {}, {})
    with pytest.raises(ValueError, match="desconhecido"):
        a.planejar(Opcoes(), {"modo": "x"}, TJ, {})


def test_extras_de_alunos_trazem_modos_com_ajuda_e_o_rapido_condicional():
    extras = reg.obter("alunos").extras()
    modo, rapido = extras
    assert modo["nome"] == "modo" and modo["padrao"] == "basico" and modo["semVazio"] is True
    assert [o["valor"] for o in modo["opcoes"]] == ["basico", "completo"] and all(o["ajuda"] for o in modo["opcoes"])
    assert rapido["visivelSe"] == {"campo": "campo-modo", "valor": "completo"}


def test_termos_exige_tema_e_usa_o_nome_da_escola_da_configuracao(monkeypatch):
    from src.comum import escola
    s = reg.obter("termos")
    with pytest.raises(ValueError, match="tema"):
        s.validar_extras({"tema": "  "})
    monkeypatch.setattr(escola, "nome", lambda: "Escola Modelo")
    p = s.planejar(Opcoes(), {"tema": " uso de imagem "}, {}, {})
    assert p.kwargs == {"tema": "uso de imagem", "nome_escola": "Escola Modelo"}
    monkeypatch.setattr(escola, "nome", lambda: "")                       # escola ainda não configurada: o script decide
    assert s.planejar(Opcoes(), {"tema": "x"}, {}, {}).kwargs["nome_escola"] is None
    pasta = s.extras()[1]
    assert pasta["tipo"] == "pasta" and pasta["destino"] == "modelos"        # grava na config, que é de onde o script lê


def test_analisa_pasta_e_mapear_gravam_a_pasta_de_digitalizacao():
    for chave in ("analisa_pasta", "mapear_pastas"):
        (campo,) = reg.obter(chave).extras()
        assert campo["tipo"] == "pasta" and campo["destino"] == "digitalizacao"


def test_automacoes_cujas_pastas_sao_fixas_nao_pedem_pasta():
    """gerar_pastas, cruzamento, mascara e coleta de e-mails usam dados/<ano>/: o seletor de pasta era um campo morto."""
    for chave in ("gerar_pastas", "cruzamento", "mascara", "coleta_emails", "backup", "turmas"):
        assert reg.obter(chave).extras() == [] and reg.obter(chave).recursos == ()


def test_sus_consulta_so_os_alunos_selecionados():
    from src.automacao.sisreg import consultar_encaminhamentos_sisreg
    s = reg.obter("sus")
    p = s.planejar(Opcoes(("3º Ano Integral A",), True, True), {}, TJ, {})
    assert p.funcao is consultar_encaminhamentos_sisreg and p.kwargs == {"cgms": ["3000000001", "3000000002"]}
    assert "2 aluno(s)" in p.log_inicial
    p = s.planejar(Opcoes(), {}, TJ, {})                                       # padrão: matriculados de todas as turmas
    assert p.kwargs["cgms"] == ["3000000001", "3000000003", "5000000001"]
    with pytest.raises(ValueError, match="Nenhum aluno na seleção"):
        s.planejar(Opcoes(("5º Ano Integral A",), False, True), {}, TJ, {})


def test_rota_executa_automacoes_simples_e_tipo_sync(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    import src.comum.backup as bk
    monkeypatch.setattr(bk, "executar_backup", lambda: print("backup simulado"))
    c = create_app().test_client()
    assert _post(c, "backup").status_code == 200
    s = _esperar(c, "backup")
    assert s["status"] == "concluido" and "backup simulado" in "\n".join(s["logs"])


def test_automacao_desconhecida_e_nao_implementada(ctx):
    c, _, _ = ctx
    assert _post(c, "nao_existe").status_code == 404
    assert _post(c, "agendador").status_code == 501


def test_gerar_chaves_e_opcao_de_ignorar_chaves_salvas_na_rematricula():
    from src.automacao.chaves_responsavel import gerar_chaves_via_login
    from src.automacao.rematricula import rematricular_via_login
    g = reg.obter("gerar_chaves")
    assert g.turmas_de is not None and g.confirmar and set(g.recursos) == {oe.RECURSO_TURMA, oe.RECURSO_TESTE}
    p = g.planejar(Opcoes(), {}, {}, {})
    assert p.tipo == "coroutine" and p.funcao is gerar_chaves_via_login
    assert p.kwargs == {"modo_teste": False, "turmas_alvo": None}
    p = g.planejar(Opcoes(turmas=("2º Ano",), modo_teste=True), {"regenerar": True}, {}, {})
    assert p.kwargs == {"modo_teste": True, "turmas_alvo": ["2º Ano"], "regenerar": True}
    assert [e["nome"] for e in g.extras()] == ["regenerar"]

    r = reg.obter("rematricula")
    assert r.planejar(Opcoes(), {}, {}, {}).kwargs == {"modo_teste": False, "apenas_erros": False, "turmas_alvo": None}
    p = r.planejar(Opcoes(), {"ignorar_chaves_salvas": True}, {}, {})
    assert p.funcao is rematricular_via_login and p.kwargs["usar_chaves_salvas"] is False
    assert [e["nome"] for e in r.extras()] == ["um_aluno", "ignorar_chaves_salvas"]
    # "Testar com 1 único aluno": só entra nos argumentos quando marcado
    assert "um_aluno" not in r.planejar(Opcoes(), {}, {}, {}).kwargs
    p = r.planejar(Opcoes(), {"um_aluno": True}, {}, {})
    assert p.funcao is rematricular_via_login and p.kwargs["um_aluno"] is True


def test_gerar_chaves_executa_pela_rota(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    import src.automacao.chaves_responsavel as cr
    chamadas = []

    async def fake(**kw):
        print("geração simulada"); chamadas.append(kw)

    monkeypatch.setattr(cr, "gerar_chaves_via_login", fake)
    c = create_app().test_client()
    assert _post(c, "gerar_chaves", turmas=["INFANTIL 4"], modo_teste=True, regenerar=True).status_code == 200
    assert _esperar(c, "gerar_chaves")["status"] == "concluido"
    assert chamadas == [{"modo_teste": True, "turmas_alvo": ["INFANTIL 4"], "regenerar": True}]

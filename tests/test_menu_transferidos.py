"""Menu lateral dos transferidos: registro, formulários, simulação e DATA_CORTE vindos da interface."""
import json
import re
from pathlib import Path

import pytest

from src.comum import configuracao, paths
from src.comum import registro_scripts as reg
from src.web.api import rotas
from src.web.app import create_app

NOVAS = ("transferidos_fila", "transferidos_gerar", "transferidos", "pareceres_transferidos")
RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps({"A": [{"CGM": "1", "Nome": "X", "Situação": "Matriculado"}]}), encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    planos = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: planos.append((chave, plano)))
    return create_app().test_client(), planos


def _post(c, chave, **payload):
    return c.post(f"/web/api/automacoes/{chave}/executar", json=payload)


def _kwargs(planos):
    assert len(planos) == 1
    return planos[0][1].kwargs


# ── consistência: registro, catálogo, menu lateral ──────────────────────

def test_as_quatro_automacoes_estao_no_registro_no_catalogo_e_no_menu():
    catalogo = {i["chave"]: i for i in rotas.AUTOMACOES_DISPONIVEIS}
    menu = set(re.findall(r'data-auto="([a-z_]+)"', (RAIZ / "src/web/templates/base.html").read_text(encoding="utf-8")))
    for chave in NOVAS:
        assert chave in reg.REGISTRO and chave in catalogo and chave in menu, chave


def test_icones_das_automacoes_novas_no_js():
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    for chave in ("transferidos_fila", "transferidos_gerar", "pareceres_transferidos"):
        assert re.search(rf"^\s*{chave}:\s*\"", js, re.M), chave


def test_campo_de_texto_aceita_valor_padrao_no_js():
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    trecho = js[js.index('<input type="text" id="${campo.id}"'):][:300]
    assert "campo.padrao" in trecho


# ── formulários ──────────────────────────────────────────────────────────

def _extras(c, chave):
    r = c.get(f"/web/api/automacoes/{chave}/componentes").get_json()
    return {e["nome"]: e for e in r["extras"]}


def test_formularios_trazem_data_de_corte_ja_preenchida(ctx):
    c, _ = ctx
    for chave in NOVAS:
        assert _extras(c, chave)["data_corte"]["padrao"] == "22/06/2026", chave


def test_a_data_de_corte_do_formulario_reflete_a_configuracao(ctx):
    c, _ = ctx
    configuracao.definir_data_corte_transferidos("01/09/2026")
    assert _extras(c, "transferidos_gerar")["data_corte"]["padrao"] == "01/09/2026"


def test_simulacao_ja_vem_marcada_nas_telas_que_mexem_no_sere(ctx):
    c, _ = ctx
    assert _extras(c, "transferidos_fila")["simulacao"]["padrao"] is False        # só gera um JSON local
    for chave in ("transferidos_gerar", "transferidos", "pareceres_transferidos"):
        assert _extras(c, chave)["simulacao"]["padrao"] is True, chave


def test_telas_que_podem_agir_pedem_confirmacao(ctx):
    c, _ = ctx
    for chave in ("transferidos_gerar", "transferidos", "pareceres_transferidos"):
        r = c.get(f"/web/api/automacoes/{chave}/componentes").get_json()
        assert r["confirmar"] is True and "Simulação" in r["aviso_confirmacao"], chave
    assert c.get("/web/api/automacoes/transferidos_fila/componentes").get_json()["confirmar"] is False


# ── fila ─────────────────────────────────────────────────────────────────

def test_fila_executa_com_e_sem_simulacao(ctx):
    c, planos = ctx
    assert _post(c, "transferidos_fila", simulacao=True).status_code == 200
    assert _kwargs(planos) == {"simulacao": True}
    planos.clear()
    _post(c, "transferidos_fila")
    assert _kwargs(planos) == {"simulacao": False}
    assert planos[0][1].tipo == "sync"


# ── gerar guia e histórico ───────────────────────────────────────────────

def _nomes():
    from src.automacao import processo_transferidos as pr
    return pr._NOMES_ETAPAS


def test_gerar_sem_marcas_no_pedido_vale_tudo_e_usa_o_texto_enviado(ctx):
    from src.automacao import processo_transferidos as pr
    c, planos = ctx
    _post(c, "transferidos_gerar", observacao="Texto X")
    assert _kwargs(planos) == {"etapas": pr.GRUPOS_ETAPAS["todas"], "simulacao": False, "modo_teste": False,
                               "observacao": "Texto X"}
    assert planos[0][1].tipo == "coroutine" and planos[0][1].funcao is pr.processar_transferencias


def _acoes(**marcadas):
    base = {"gravar": False, "alterar": False, "emitir": False, "assinar": False, "imprimir": False}
    return {**base, **marcadas}


@pytest.mark.parametrize("acao,esperado", [
    ("gravar",   [0]),
    ("emitir",   [2, 5]),
    ("assinar",  [3, 6]),
    ("imprimir", [4, 7]),
])
def test_cada_acao_sozinha_executa_so_as_suas_etapas(ctx, acao, esperado):
    c, planos = ctx
    assert _post(c, "transferidos_gerar", documentos="ambos", **_acoes(**{acao: True})).status_code == 200
    kw = _kwargs(planos)
    assert kw["etapas"] == [_nomes()[i] for i in esperado] and kw["observacao"] is None


def test_alterar_sozinha_executa_so_a_etapa_de_alterar_com_o_texto(ctx):
    c, planos = ctx
    _post(c, "transferidos_gerar", observacao="  Aluno transferido.  ", **_acoes(alterar=True))
    assert _kwargs(planos)["etapas"] == [_nomes()[1]] and _kwargs(planos)["observacao"] == "Aluno transferido."


def test_emitir_e_assinar_respeitam_a_ordem_do_processo(ctx):
    c, planos = ctx
    _post(c, "transferidos_gerar", **_acoes(assinar=True, emitir=True))
    assert _kwargs(planos)["etapas"] == [_nomes()[i] for i in (2, 3, 5, 6)]      # histórico e depois guia


@pytest.mark.parametrize("docs,esperado", [("historico", [2, 3, 4]), ("guia", [5, 6, 7])])
def test_documentos_restringe_emitir_assinar_imprimir(ctx, docs, esperado):
    c, planos = ctx
    _post(c, "transferidos_gerar", documentos=docs, **_acoes(emitir=True, assinar=True, imprimir=True))
    assert _kwargs(planos)["etapas"] == [_nomes()[i] for i in esperado]


def test_so_a_guia_ignora_gravar_e_alterar_sem_exigir_texto(ctx):
    c, planos = ctx
    r = _post(c, "transferidos_gerar", documentos="guia", observacao="", **_acoes(gravar=True, alterar=True, emitir=True))
    assert r.status_code == 200 and _kwargs(planos)["etapas"] == [_nomes()[5]] and _kwargs(planos)["observacao"] is None


def test_so_a_guia_so_com_gravar_e_alterar_nao_tem_o_que_fazer(ctx):
    c, planos = ctx
    r = _post(c, "transferidos_gerar", documentos="guia", observacao="x", **_acoes(gravar=True, alterar=True))
    assert r.status_code == 400 and "Só a guia" in r.get_json()["mensagem"] and planos == []


def test_nenhuma_acao_marcada_e_recusada(ctx):
    c, planos = ctx
    r = _post(c, "transferidos_gerar", **_acoes())
    assert r.status_code == 400 and "pelo menos uma ação" in r.get_json()["mensagem"] and planos == []


def test_alterar_exige_o_texto(ctx):
    c, planos = ctx
    r = _post(c, "transferidos_gerar", observacao="   ", **_acoes(alterar=True))
    assert r.status_code == 400 and "texto da observação" in r.get_json()["mensagem"] and planos == []


def test_o_texto_usado_fica_guardado_e_ja_vem_preenchido(ctx):
    c, _ = ctx
    assert _extras(c, "transferidos_gerar")["observacao"]["padrao"] == ""
    _post(c, "transferidos_gerar", observacao="Transferido em 2026.", **_acoes(alterar=True))
    assert configuracao.observacao_historico() == "Transferido em 2026."
    assert _extras(c, "transferidos_gerar")["observacao"]["padrao"] == "Transferido em 2026."


def test_sem_alterar_o_texto_nao_e_guardado(ctx):
    c, _ = ctx
    _post(c, "transferidos_gerar", observacao="não vai", **_acoes(emitir=True))
    assert configuracao.observacao_historico() == ""


def test_pedido_antigo_sem_campo_de_texto_usa_o_ultimo_texto(ctx):
    c, planos = ctx
    configuracao.definir_observacao_historico("Último texto")
    _post(c, "transferidos_gerar")
    assert _kwargs(planos)["observacao"] == "Último texto"


@pytest.mark.parametrize("flags", [{"simulacao": True}, {"modo_teste": True}, {"simulacao": True, "modo_teste": True}])
def test_gerar_repassa_simulacao_e_teste(ctx, flags):
    c, planos = ctx
    _post(c, "transferidos_gerar", **_acoes(emitir=True), **flags)
    kw = _kwargs(planos)
    assert kw["simulacao"] is flags.get("simulacao", False) and kw["modo_teste"] is flags.get("modo_teste", False)


def test_gerar_rejeita_documentos_invalidos(ctx):
    c, planos = ctx
    r = _post(c, "transferidos_gerar", documentos="tudo-errado", **_acoes(emitir=True))
    assert r.status_code == 400 and "Escolha os documentos" in r.get_json()["mensagem"] and planos == []


def test_formulario_de_gerar_tem_as_5_acoes_na_ordem_e_marcadas(ctx):
    c, _ = ctx
    extras = c.get("/web/api/automacoes/transferidos_gerar/componentes").get_json()["extras"]
    caixas = [e for e in extras if e["tipo"] == "caixa" and e["nome"] != "simulacao"]
    assert [e["nome"] for e in caixas] == ["gravar", "alterar", "emitir", "assinar", "imprimir"]
    assert [e["label"] for e in caixas] == ["Gravar", "Alterar", "Emitir", "Assinar", "Imprimir"]
    assert all(e["padrao"] is True for e in caixas)
    assert "Diretor" in next(e for e in caixas if e["nome"] == "assinar")["descricao"]


def test_caixa_de_texto_so_aparece_com_alterar_marcado(ctx):
    c, _ = ctx
    texto = _extras(c, "transferidos_gerar")["observacao"]
    assert texto["multilinha"] is True and texto["visivelSe"] == {"campo": "campo-acao-alterar", "valor": "true"}


def test_js_mostra_campos_condicionais_tambem_por_caixa_de_marcar():
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'alvo?.type === "checkbox" ? String(alvo.checked)' in js
    assert js.count('querySelectorAll("select, input[type=checkbox]")') == 2          # os dois lugares que montam o formulário
    assert "campo.padrao" in js[js.index("<textarea id="):][:400]                       # texto multilinha vem preenchido


def test_nao_existe_opcao_de_pular_retornados_na_tela(ctx):
    c, _ = ctx
    assert "pular_retornados" not in _extras(c, "transferidos_gerar")


# ── envio ao SERE ────────────────────────────────────────────────────────

def test_envio_mantem_o_contrato_antigo_e_acrescenta_a_simulacao(ctx):
    c, planos = ctx
    _post(c, "transferidos", modo_teste=True)
    assert _kwargs(planos) == {"modo_teste": True}                               # contrato antigo intacto
    planos.clear()
    _post(c, "transferidos", simulacao=True)
    assert _kwargs(planos) == {"modo_teste": False, "simulacao": True}


# ── pareceres ────────────────────────────────────────────────────────────

def test_pareceres_plano_padrao_e_simulado(ctx):
    from src.automacao import pareceres_transferidos as pp
    from src.comum.compressao import LIMITE_SERE_MB
    c, planos = ctx
    _post(c, "pareceres_transferidos")
    assert _kwargs(planos) == {"simulacao": False, "enviar": True, "limite_mb": LIMITE_SERE_MB, "modo_teste": False}
    assert planos[0][1].funcao is pp.executar_pareceres_transferidos
    planos.clear()
    _post(c, "pareceres_transferidos", simulacao=True, enviar=False, limite_mb="0,8", modo_teste=True)
    assert _kwargs(planos) == {"simulacao": True, "enviar": False, "limite_mb": 0.8, "modo_teste": True}


def test_pareceres_rejeita_limite_invalido(ctx):
    c, planos = ctx
    r = _post(c, "pareceres_transferidos", limite_mb="muito")
    assert r.status_code == 400 and "Tamanho inválido" in r.get_json()["mensagem"] and planos == []


# ── DATA_CORTE digitada na tela ──────────────────────────────────────────

@pytest.mark.parametrize("chave", NOVAS)
def test_data_de_corte_digitada_fica_gravada(ctx, chave):
    c, _ = ctx
    assert _post(c, chave, data_corte="01/09/2026", observacao="texto").status_code == 200   # (o texto só vale em transferidos_gerar)
    assert configuracao.data_corte_transferidos().strftime("%d/%m/%Y") == "01/09/2026"


def test_data_de_corte_em_branco_nao_muda_nada(ctx):
    c, _ = ctx
    configuracao.definir_data_corte_transferidos("01/09/2026")
    _post(c, "transferidos_gerar", data_corte="", observacao="texto")
    assert configuracao.data_corte_transferidos().strftime("%d/%m/%Y") == "01/09/2026"


@pytest.mark.parametrize("chave", NOVAS)
def test_data_de_corte_invalida_e_recusada_sem_gravar(ctx, chave):
    c, planos = ctx
    r = _post(c, chave, data_corte="31/02/2026")
    assert r.status_code == 400 and "dd/mm/aaaa" in r.get_json()["mensagem"]
    assert planos == [] and not configuracao.data_corte_transferidos_configurada()


def test_turmas_py_registra_a_fila_depois_de_gravar_o_turmas_json():
    """O gancho está no lugar certo: depois de gravar o turmas.json e antes de encerrar a coleta."""
    fonte = (RAIZ / "src/automacao/turmas.py").read_text(encoding="utf-8")
    gravar = fonte.index("Salvando JSON em")
    gancho = fonte.index("registrar_fila_sem_falhar(resultado")
    fim = fonte.index("Coleta geral finalizada")
    assert gravar < gancho < fim


# ── Configurações: linha "Data de corte dos transferidos" ────────────────

def test_configuracoes_tem_a_linha_e_o_formulario():
    html = (RAIZ / "src/web/templates/configuracoes.html").read_text(encoding="utf-8")
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'data-config="data_corte_transferidos"' in html
    assert re.search(r"^\s*data_corte_transferidos: `", js, re.M)
    assert 'row.dataset.config === "data_corte_transferidos"' in js and "async function conectarFormDataCorte" in js
    for id_ in ("cfg-corte-data", "cfg-corte-status", "cfg-corte-salvar", "cfg-corte-padrao"):
        assert js.count(id_) >= 2, id_                                  # no HTML do modal e no código que o liga


def test_configuracao_data_corte_obter_padrao(ctx):
    c, _ = ctx
    r = c.get("/web/api/configuracoes/data-corte").get_json()
    assert r == {"data_corte": "22/06/2026", "personalizada": False, "padrao": "22/06/2026"}


def test_configuracao_data_corte_salvar_e_voltar_ao_padrao(ctx):
    c, _ = ctx
    r = c.post("/web/api/configuracoes/data-corte", json={"data_corte": "01/09/2026"})
    assert r.status_code == 200 and r.get_json()["data_corte"] == "01/09/2026" and r.get_json()["personalizada"] is True
    assert configuracao.data_corte_transferidos().strftime("%d/%m/%Y") == "01/09/2026"
    assert _extras(c, "transferidos_gerar")["data_corte"]["padrao"] == "01/09/2026"      # as telas do fluxo refletem
    r = c.post("/web/api/configuracoes/data-corte", json={"usar_padrao": True})
    assert r.get_json()["data_corte"] == "22/06/2026" and r.get_json()["personalizada"] is False


@pytest.mark.parametrize("corpo", [{"data_corte": "31/02/2026"}, {"data_corte": "amanhã"}, {"data_corte": ""}, {}])
def test_configuracao_data_corte_recusa_invalida(ctx, corpo):
    c, _ = ctx
    r = c.post("/web/api/configuracoes/data-corte", json=corpo)
    assert r.status_code == 400 and "dd/mm/aaaa" in r.get_json()["erro"]
    assert not configuracao.data_corte_transferidos_configurada()


# ── Configurações: "Turmas do QR antigo" (mapeamento_turmas_qr) ───────────

def _turmas_json(*nomes):
    (rotas._dados_dir() / "turmas.json").write_text(
        json.dumps({n: [] for n in nomes} | {"mapeamento": {}}, ensure_ascii=False), encoding="utf-8")


def test_mapeamento_qr_configuracao_grava_normaliza_e_substitui(ctx):
    assert configuracao.mapeamento_turmas_qr() == {}
    r = configuracao.definir_mapeamento_turmas_qr([(" inf 4 a ", " INFANTIL 4 Integral A "), ("", ""), ("5 ANO B", "5º Ano Integral B")])
    assert r == {"INF 4 A": "INFANTIL 4 Integral A", "5 ANO B": "5º Ano Integral B"} == configuracao.mapeamento_turmas_qr()
    configuracao.definir_mapeamento_turmas_qr({"x": "Y"})                 # substitui tudo, aceita dict
    assert configuracao.mapeamento_turmas_qr() == {"X": "Y"}
    configuracao.definir_mapeamento_turmas_qr([])
    assert configuracao.mapeamento_turmas_qr() == {}


@pytest.mark.parametrize("pares, trecho", [
    ([("INF 4 A", "")], "Linha 1"), ([("", "Turma")], "Linha 1"),
    ([("INF 4 A", "T1"), ("inf 4 a", "T2")], "mais de uma vez"), ([("x" * 81, "T")], "80 caracteres"),
])
def test_mapeamento_qr_configuracao_recusa_e_nao_mexe_no_que_existia(ctx, pares, trecho):
    configuracao.definir_mapeamento_turmas_qr({"A": "B"})
    with pytest.raises(ValueError, match=trecho):
        configuracao.definir_mapeamento_turmas_qr(pares)
    assert configuracao.mapeamento_turmas_qr() == {"A": "B"}


def test_mapeamento_qr_cadastrado_vale_na_leitura_do_parecer(ctx):
    from src.automacao import pareceres_transferidos as pp
    chaves = {"Turma Especial 7": []}
    assert pp.resolver_turma(chaves, "SALA DO MEIO") is None
    configuracao.definir_mapeamento_turmas_qr([("Sala do Meio", "Turma Especial 7")])
    assert pp.resolver_turma(chaves, "sala do meio") == "Turma Especial 7"


def test_mapeamento_qr_rotas_obter_salvar_e_apontar_turma_que_sumiu(ctx):
    c, _ = ctx
    _turmas_json("INFANTIL 4 Integral A", "5º Ano Integral B")
    r = c.get("/web/api/configuracoes/mapeamento-turmas-qr").get_json()
    assert r == {"pares": [], "turmas": ["5º Ano Integral B", "INFANTIL 4 Integral A"], "nao_reconhecidos": []}   # só turmas (sem a chave "mapeamento"), em ordem alfabética
    corpo = {"pares": [{"qr": "INF 4 A", "turma": "INFANTIL 4 Integral A"}, {"qr": "ANTIGA", "turma": "Turma que sumiu"}, {"qr": "", "turma": ""}]}
    r = c.post("/web/api/configuracoes/mapeamento-turmas-qr", json=corpo)
    assert r.status_code == 200 and r.get_json()["mensagem"] == "2 par(es) salvo(s)."
    assert r.get_json()["pares"] == [{"qr": "ANTIGA", "turma": "Turma que sumiu", "existe": False},
                                     {"qr": "INF 4 A", "turma": "INFANTIL 4 Integral A", "existe": True}]
    assert configuracao.mapeamento_turmas_qr()["INF 4 A"] == "INFANTIL 4 Integral A"
    r = c.post("/web/api/configuracoes/mapeamento-turmas-qr", json={"pares": []})
    assert r.get_json()["pares"] == [] and "só o mapeamento do sistema" in r.get_json()["mensagem"]


@pytest.mark.parametrize("corpo", [{}, {"pares": "x"}, {"pares": ["x"]}, {"pares": [{"qr": "A", "turma": ""}]},
                                   {"pares": [{"qr": "A", "turma": "T"}, {"qr": "a", "turma": "U"}]}])
def test_mapeamento_qr_rota_recusa_invalido(ctx, corpo):
    c, _ = ctx
    r = c.post("/web/api/configuracoes/mapeamento-turmas-qr", json=corpo)
    assert r.status_code == 400 and r.get_json()["erro"] and configuracao.mapeamento_turmas_qr() == {}


def test_mapeamento_qr_rota_testar_diz_a_turma_e_de_onde_veio(ctx):
    c, _ = ctx
    _turmas_json("INFANTIL 4 Integral A", "Turma Especial 7", "3º Ano Matutino A", "3º Ano Matutino B")
    testar = lambda texto, **kw: c.post("/web/api/configuracoes/mapeamento-turmas-qr/testar", json={"texto": texto, **kw}).get_json()
    assert testar("INF 4 A") == {"texto": "INF 4 A", "turma": "INFANTIL 4 Integral A", "via": "mapeamento do sistema"}
    assert testar("3 ano a")["via"] == "busca por palavras" and testar("3 ano a")["turma"] == "3º Ano Matutino A"
    assert testar("SALA DO MEIO") == {"texto": "SALA DO MEIO", "turma": None, "via": ""}
    assert testar("3º ANO")["turma"] is None                                                   # ambígua: A ou B?
    pares = [{"qr": "sala do meio", "turma": "Turma Especial 7"}]
    r = testar("SALA DO MEIO", pares=pares)                                                    # linha da tela, ainda não salva
    assert r["turma"] == "Turma Especial 7" and "ainda não salva" in r["via"]
    assert configuracao.mapeamento_turmas_qr() == {}                                           # testar não grava nada
    c.post("/web/api/configuracoes/mapeamento-turmas-qr", json={"pares": pares})
    assert testar("SALA DO MEIO")["via"] == "mapeamento cadastrado"
    assert c.post("/web/api/configuracoes/mapeamento-turmas-qr/testar", json={"texto": " "}).status_code == 400


def test_configuracoes_tem_a_linha_e_o_formulario_das_turmas_do_qr():
    html = (RAIZ / "src/web/templates/configuracoes.html").read_text(encoding="utf-8")
    js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'data-config="mapeamento_turmas_qr"' in html
    assert re.search(r"^\s*mapeamento_turmas_qr: `", js, re.M)
    assert 'row.dataset.config === "mapeamento_turmas_qr"' in js and "async function conectarFormMapeamentoQr" in js


def test_mapeamento_qr_lista_os_nao_reconhecidos_e_esconde_os_que_ja_se_resolvem(ctx):
    from src.comum import qr_turmas_nao_reconhecidas as anotados
    c, _ = ctx
    _turmas_json("INFANTIL 4 Integral A", "Turma Especial 7")
    pasta = rotas._dados_dir()
    for texto, arquivo in (("SALA DO MEIO", "a.pdf"), ("SALA DO MEIO", "b.pdf"), ("INF 4 A", "c.pdf")):
        anotados.registrar(pasta, texto, arquivo)
    r = c.get("/web/api/configuracoes/mapeamento-turmas-qr").get_json()
    assert [(n["texto"], n["quantidade"], n["arquivos"]) for n in r["nao_reconhecidos"]] == [("SALA DO MEIO", 2, ["a.pdf", "b.pdf"])]   # INF 4 A o sistema já resolve


def test_mapeamento_qr_salvar_um_par_tira_o_texto_da_lista(ctx):
    from src.comum import qr_turmas_nao_reconhecidas as anotados
    c, _ = ctx
    _turmas_json("Turma Especial 7")
    anotados.registrar(rotas._dados_dir(), "SALA DO MEIO", "a.pdf")
    anotados.registrar(rotas._dados_dir(), "OUTRA", "b.pdf")
    r = c.post("/web/api/configuracoes/mapeamento-turmas-qr", json={"pares": [{"qr": "sala do meio", "turma": "Turma Especial 7"}]}).get_json()
    assert [n["texto"] for n in r["nao_reconhecidos"]] == ["OUTRA"]
    assert [i["texto"] for i in anotados.listar(rotas._dados_dir())] == ["OUTRA"]               # saiu do arquivo, não só da tela
    c.post("/web/api/configuracoes/mapeamento-turmas-qr", json={"pares": []})                  # apagar o par não traz o texto de volta
    assert [i["texto"] for i in anotados.listar(rotas._dados_dir())] == ["OUTRA"]


def test_mapeamento_qr_ignorar_tira_da_lista_sem_mexer_nos_pares(ctx):
    from src.comum import qr_turmas_nao_reconhecidas as anotados
    c, _ = ctx
    _turmas_json("Turma Especial 7")
    configuracao.definir_mapeamento_turmas_qr([("A", "Turma Especial 7")])
    anotados.registrar(rotas._dados_dir(), "LIXO DE LEITURA", "a.pdf")
    r = c.post("/web/api/configuracoes/mapeamento-turmas-qr/ignorar", json={"texto": " lixo de leitura "}).get_json()
    assert r["nao_reconhecidos"] == [] and [p["qr"] for p in r["pares"]] == ["A"] and anotados.listar(rotas._dados_dir()) == []
    assert c.post("/web/api/configuracoes/mapeamento-turmas-qr/ignorar", json={"texto": " "}).status_code == 400


def test_mapeamento_qr_sem_turmas_json_lista_todos_os_anotados(ctx):
    from src.comum import qr_turmas_nao_reconhecidas as anotados
    c, _ = ctx
    (rotas._dados_dir() / "turmas.json").unlink()
    anotados.registrar(rotas._dados_dir(), "INF 4 A", "a.pdf")
    r = c.get("/web/api/configuracoes/mapeamento-turmas-qr").get_json()
    assert r["turmas"] == [] and [n["texto"] for n in r["nao_reconhecidos"]] == ["INF 4 A"]    # sem como conferir, não esconde nada

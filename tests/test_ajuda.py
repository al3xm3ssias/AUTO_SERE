"""
Testes da ajuda (tecla F1): src/comum/ajuda*.py, src/web/api/ajuda.py e static/js/ajuda.js.

Garantem que NENHUMA tela, automação, painel de Configurações ou janela fica sem ajuda, que os links "Veja também" e os
seletores do botão "Mostrar na tela" ainda existem, e que a API responde. Sem rede e sem SERE.
"""
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.comum import ajuda, ajuda_automacoes, ajuda_conteudo as conteudo  # noqa: E402
from src.comum import registro_scripts as registro  # noqa: E402
from src.web.api.rotas import AUTOMACOES_DISPONIVEIS  # noqa: E402

WEB = RAIZ / "src" / "web"
TEMPLATES = "".join(p.read_text(encoding="utf-8") for p in sorted((WEB / "templates").rglob("*.html")))
SCRIPTS = "".join(p.read_text(encoding="utf-8") for p in sorted((WEB / "static" / "js").glob("*.js")))
CORPO = TEMPLATES + SCRIPTS
BASE = (WEB / "templates" / "base.html").read_text(encoding="utf-8")
AJUDA_JS = (WEB / "static" / "js" / "ajuda.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cliente():
    from src.web.app import app
    return app.test_client()


def _todas_as_entradas():
    for tipo, base in (("tela", conteudo.TELAS), ("aba", conteudo.ABAS), ("configuracao", conteudo.CONFIGURACOES),
                       ("modal", conteudo.MODAIS)):
        for chave in base:
            yield tipo, chave
    for chave in ajuda_automacoes.AUTOMACOES:
        yield "automacao", chave


# ───────────────────────────── cobertura ─────────────────────────────

def test_toda_tela_do_menu_tem_ajuda():
    telas = set(re.findall(r'id="sec-([a-z-]+)"', TEMPLATES))
    assert telas, "não achei nenhuma seção nos templates"
    assert telas <= set(conteudo.TELAS), f"telas sem ajuda: {sorted(telas - set(conteudo.TELAS))}"


def test_toda_automacao_tem_ajuda_e_vice_versa():
    catalogo = {a["chave"] for a in AUTOMACOES_DISPONIVEIS}
    escritas = set(ajuda_automacoes.AUTOMACOES)
    assert catalogo - escritas == set(), f"automações sem ajuda: {sorted(catalogo - escritas)}"
    assert escritas - catalogo == set(), f"ajuda de automação que não existe mais: {sorted(escritas - catalogo)}"


def test_automacoes_do_menu_lateral_tem_ajuda():
    do_menu = set(re.findall(r'data-auto="([a-z_]+)"', BASE))
    assert do_menu <= set(ajuda_automacoes.AUTOMACOES), sorted(do_menu - set(ajuda_automacoes.AUTOMACOES))


def test_todo_painel_de_configuracoes_tem_ajuda():
    paineis = set(re.findall(r'data-config="([a-z_]+)"', (WEB / "templates" / "configuracoes.html").read_text(encoding="utf-8")))
    assert paineis <= set(conteudo.CONFIGURACOES), sorted(paineis - set(conteudo.CONFIGURACOES))


def test_toda_aba_de_documentos_tem_ajuda():
    abas = set(re.findall(r'data-doctab="([a-z]+)"', TEMPLATES))
    assert {f"documentos-{a}" for a in abas} <= set(conteudo.ABAS)


def test_toda_janela_reconhecida_pelo_javascript_tem_ajuda():
    chaves = set(re.findall(r'\["[^"]+", "([a-z-]+)"\]', AJUDA_JS)) | {"pergunta-automacao"}
    assert chaves and chaves <= set(conteudo.MODAIS), sorted(chaves - set(conteudo.MODAIS))
    assert set(conteudo.MODAIS) <= chaves, "janela com ajuda que o JavaScript nunca reconhece"


def test_grupos_das_automacoes_existem():
    grupos = {g for g, _ in ajuda_automacoes.GRUPOS}
    assert {v["grupo"] for v in ajuda_automacoes.AUTOMACOES.values()} <= grupos


def test_scripts_registrados_declaram_as_configuracoes_que_usam():
    # a ajuda lista as configurações do registro; script sem isso mostraria a seção vazia sem avisar
    sem = [k for k, s in registro.REGISTRO.items() if s.configs is None]
    assert sem == []


# ───────────────────────────── qualidade dos textos ─────────────────────────────

@pytest.mark.parametrize("tipo,chave", list(_todas_as_entradas()))
def test_cada_ajuda_monta_e_tem_conteudo(tipo, chave):
    a = ajuda.obter(tipo, chave)
    assert a is not None
    assert a["titulo"].strip() and len(a["resumo"]) > 20
    assert a["secoes"], "sem nenhuma seção"
    for s in a["secoes"]:
        assert s["tipo"] in {"texto", "passos", "lista", "elementos", "links"} and s["itens"]
        for item in s["itens"]:
            texto = item["texto"] if isinstance(item, dict) and "texto" in item else str(item)
            assert texto.count("**") % 2 == 0, f"negrito aberto em {tipo}/{chave}: {texto[:60]}"
            assert texto.count("`") % 2 == 0, f"crase aberta em {tipo}/{chave}: {texto[:60]}"


def test_telas_principais_tem_passo_a_passo_e_elementos():
    for chave, t in conteudo.TELAS.items():
        assert t.get("passos"), f"tela {chave} sem passo a passo"
        if chave not in {"configuracoes"}:
            assert t.get("elementos"), f"tela {chave} sem elementos"


def test_links_veja_tambem_apontam_para_ajudas_que_existem():
    for tipo, chave in _todas_as_entradas():
        a = ajuda.obter(tipo, chave)
        for s in a["secoes"]:
            if s["tipo"] == "links":
                for l in s["itens"]:
                    assert ajuda.obter(l["tipo"], l["chave"]), f"{tipo}/{chave} aponta para {l['tipo']}/{l['chave']}, que não existe"


def _tokens(seletor):
    return (re.findall(r"#([A-Za-z0-9_-]+)", seletor) + re.findall(r"\.([A-Za-z0-9_-]+)", seletor)
            + re.findall(r"\[([a-z-]+)(?:=|\])", seletor) + re.findall(r"=['\"]([^'\"]+)['\"]\]", seletor))


def test_seletores_do_mostrar_na_tela_existem_nas_telas():
    ruins = []
    for tipo, chave in _todas_as_entradas():
        if tipo == "automacao":
            continue                       # campos próprios vêm do registro e só existem com a tela montada
        for s in ajuda.obter(tipo, chave)["secoes"]:
            if s["tipo"] != "elementos":
                continue
            for el in s["itens"]:
                for tk in _tokens(el.get("sel", "")):
                    if tk not in CORPO:
                        ruins.append(f"{tipo}/{chave}: {el['sel']} (falta '{tk}')")
    assert not ruins, "\n".join(ruins)


def test_seletores_fixos_da_tela_de_execucao_existem():
    for nome, _, sel in ajuda_automacoes.SECOES_DA_TELA:
        for tk in _tokens(sel):
            assert tk in CORPO, f"{nome}: {sel}"
    for nome, (_, _, sel) in ajuda_automacoes.COMPONENTES.items():
        for tk in _tokens(sel):
            assert tk in CORPO, f"{nome}: {sel}"


# ───────────────────────────── campos vindos do registro ─────────────────────────────

def _secao(a, titulo):
    return next((s for s in a["secoes"] if s["titulo"] == titulo), None)


def test_ajuda_da_automacao_traz_os_campos_do_registro():
    a = ajuda.obter("automacao", "rematricula")
    nomes = [i["nome"] for i in _secao(a, "Campos desta tela")["itens"]]
    assert "Turma" in nomes and "Testar com 1 único aluno" in nomes and "Modo de teste" in nomes
    assert _secao(a, "Confirmação") is not None                     # rematrícula altera o SERE
    assert any("SERE" in i["rotulo"] if "rotulo" in i else "SERE" in i["nome"] for i in _secao(a, "O que o sistema guarda e esta automação usa")["itens"])


def test_modo_de_teste_usa_o_texto_do_proprio_script():
    a = ajuda.obter("automacao", "planilha_modelo")
    teste = [i for i in _secao(a, "Campos desta tela")["itens"] if i["nome"] == "Modo de teste"]
    assert teste == [] or "Não se aplica" in teste[0]["texto"]


def test_opcoes_de_um_select_pequeno_aparecem_com_a_explicacao():
    a = ajuda.obter("automacao", "alunos")
    modo = next(i for i in _secao(a, "Campos desta tela")["itens"] if i["nome"] == "Modo de coleta")
    assert "Básico" in modo["texto"] and "Completo" in modo["texto"] and "alunos_completo.json" in modo["texto"]


def test_select_grande_nao_despeja_todas_as_opcoes():
    a = ajuda.obter("automacao", "documentos")
    tipo = next(i for i in _secao(a, "Campos desta tela")["itens"] if i["nome"] == "Tipo de documento")
    assert "lista de" in tipo["texto"] and "2ª Via Diploma" not in tipo["texto"]


def test_automacao_sem_campos_explica_que_so_executa():
    a = ajuda.obter("automacao", "backup")
    assert "só clicar" in _secao(a, "Campos desta tela")["itens"][0]["texto"]


def test_automacao_nao_implementada_avisa():
    a = ajuda.obter("automacao", "agendador")
    assert any("não foi implementada" in str(c) for c in _secao(a, "Cuidados")["itens"])


# ───────────────────────────── API ─────────────────────────────

def test_api_indice_lista_tudo(cliente):
    r = cliente.get("/web/api/ajuda/indice")
    assert r.status_code == 200
    d = r.get_json()
    assert len(d["telas"]) == len(conteudo.TELAS)
    assert sum(len(g["itens"]) for g in d["automacoes"]) == len(AUTOMACOES_DISPONIVEIS)
    assert len(d["configuracoes"]) == len(conteudo.CONFIGURACOES)
    assert all(i["busca"] for i in d["telas"])


def test_api_entrega_cada_tipo_e_responde_404_ao_desconhecido(cliente):
    assert cliente.get("/web/api/ajuda/tela/painel").get_json()["titulo"] == "Painel principal"
    assert cliente.get("/web/api/ajuda/automacao/turmas").status_code == 200
    assert cliente.get("/web/api/ajuda/geral").status_code == 200
    for ruim in ("tela/nao-existe", "automacao/nao_existe", "tipo/painel"):
        assert cliente.get(f"/web/api/ajuda/{ruim}").status_code == 404


# ───────────────────────────── ligação com a interface ─────────────────────────────

def test_f1_esta_ligado_na_interface():
    assert "js/ajuda.js" in BASE and 'id="btn-ajuda-f1"' in BASE
    assert 'e.key === "F1"' in AJUDA_JS and "preventDefault" in AJUDA_JS
    for id_ in ("aj-busca", "aj-lista-telas", "aj-lista-automacoes", "aj-lista-config", "aj-vazio"):
        assert f'id="{id_}"' in TEMPLATES, id_


# ───────────── ajuda das automações que ganharam recursos (avisos, Base ABC, funcionários, backup) ─────────────

def _texto_da_ajuda(tipo, chave) -> str:
    import json as _json
    return _json.dumps(ajuda.obter(tipo, chave), ensure_ascii=False)


def test_ajuda_dos_avisos_descreve_o_envio_real_e_nao_diz_que_esta_bloqueado():
    t = _texto_da_ajuda("automacao", "avisos")
    assert "ainda não está liberado" not in t and "só existem os modos Simular e Teste" not in t
    for trecho in ("Enviar de verdade", "não pode ser desfeito", "AVISOS/enviados.json", "escola de origem", "Consulta na Base ABC",
                   "config/modelos_avisos.json", "escola anterior", "só para quem está chegando"):
        assert trecho in t, trecho


def test_ajuda_dos_avisos_traz_todos_os_campos_da_tela_com_nome_proprio():
    t = _texto_da_ajuda("automacao", "avisos")
    for rotulo in ("Quais unidades", "Quais alunos", "De onde vêm os alunos novos", "Tipo de mensagem", "Salvar e excluir modelos",
                   "Como fica a mensagem", "Pausa entre os e-mails", "Máximo de e-mails por execução"):
        assert rotulo in t, rotulo
    assert '"Campo"' not in t and "Preencha conforme a necessidade" not in t          # nenhum campo sem rótulo
    assert "E-mail de teste" not in t and "cujo nome contém" not in t                  # campos que saíram da tela


def test_ajuda_das_outras_automacoes_conta_o_que_mudou():
    assert "Recomeçar do zero" in _texto_da_ajuda("automacao", "funcionarios")
    b = _texto_da_ajuda("automacao", "backup")
    assert "backup \\\"automático\\\"" in b and "7 mais recentes" in b and "10 mais recentes" in b
    a = _texto_da_ajuda("automacao", "base_abc")
    assert "vinculo_base_abc" in a and "buscas_base.json" in a and "não tem data de nascimento" not in a
    assert "nome da mãe" in _texto_da_ajuda("automacao", "prematricula_completa")
    assert "backup automático" in _texto_da_ajuda("automacao", "turmas")


def test_ajuda_da_pre_matricula_explica_a_regra_da_opcao_da_escola_e_a_fila_de_analise():
    tela = " ".join(conteudo.TELAS["prematricula"]["cuidados"] + conteudo.TELAS["prematricula"]["passos"])
    auto = " ".join(ajuda_automacoes.AUTOMACOES["prematricula_completa"]["cuidados"])
    for texto in (tela, auto):
        assert "1ª opção" in texto
        assert "fila de análise" in texto
        assert "Central de Matrícula" in texto


def test_ajuda_da_pre_matricula_explica_a_correcao_de_dados_e_a_aba_da_fila():
    tela = conteudo.TELAS["prematricula"]
    texto = " ".join(tela["passos"] + tela["cuidados"])
    assert "Corrigir dados" in texto and "Desfazer" in texto and "CPF não pode ser alterado" in texto
    assert "aba **Fila de análise**" in texto
    assert "esta tela ainda não tem" not in texto        # a versão antiga dizia que a fila não aparecia na tela
    assert "ainda não há tela" not in " ".join(ajuda_automacoes.AUTOMACOES["prematricula_completa"]["cuidados"])


def test_ajuda_de_transferidos_explica_a_segunda_saida():
    corte = " ".join(conteudo.CONFIGURACOES["data_corte_transferidos"]["dicas"])
    fila = " ".join(ajuda_automacoes.AUTOMACOES["transferidos_fila"]["cuidados"])
    assert "transferido de novo" in corte and "saiu de novo" in fila and "ciclos_anteriores" in fila

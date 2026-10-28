"""funcionarios_vinculos: SERE × RH × holerite, com a flag de terceirizado (fusão dos scripts de funcionários)."""
import asyncio
import json
import os
import time
from pathlib import Path

import pytest
import requests

from src.automacao import funcionarios_vinculos as fv
from src.comum import escola, paths
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app

ESCOLA = "Escola Municipal Profª Judith Macedo Silveira"


# ───────────── dados de exemplo ─────────────

def rh(numcad, nome, titcar="PROFESSOR", nomloc="PMPG-SME-FUNDEB 40%-Ens.Fundamental", **extra):
    return {"numcad": numcad, "numemp": 1, "nomemp": "PREFEITURA MUNICIPAL DE PONTA GROSSA", "nomfun": nome,
            "nomloc": nomloc, "titcar": titcar, "datadm": "01/02/2010", "dessit": "Trabalhando", "forma_ingresso": "Concurso", **extra}


RH_SERVIDORES = [
    rh("1001", "ANA CLARA DE SOUZA LIMA"),
    rh("1002", "BETO ROCHA"),
    rh("1003", "RENATA BEATRIZ DE PAULA DE OLIVEIRA DO NASCIMENTO"),
    rh("1004", "CARLA DIAS MELO"),                      # homônima 1
    rh("1005", "CARLA DIAS MELO", nomloc="OUTRA"),      # homônima 2
]


def sere(nome, cpf, funcao="Professor"):
    return {"nome": nome, "cpf": cpf, "funcao": funcao, "email": f"{cpf}@x.com"}


def holerite_html(matricula="1001", nome="ANA CLARA", local="ESCOLA JUDITH MACEDO SILVEIRA", cargo="PROFESSOR",
                  estouro=False, com_local=True):
    """HTML no layout real: spans com top/left. Lotação à esquerda, local de trabalho à direita."""
    def sp(top, left, txt): return f'<span style="position:absolute; top:{top}px; left:{left}px;">{txt}</span>'
    partes = [sp(80, 145, "PMPG-SME-FUNDEB 40%-Ens.Fundamental")]
    if com_local:
        partes.append(sp(81, 470, local))
    partes += [sp(100, 20, matricula), sp(100, 90, nome), sp(100, 400, "01/02/2010"), sp(120, 20, cargo),
               sp(300, 20, "1973 Gratificacao"), sp(300, 200, "R$ 999,99")]
    if estouro:
        partes.append(sp(320, 20, "256 Estouro do Mes"))
    return "<html><body>" + "".join(partes) + "</body></html>"


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    dados = tmp_path / "dados" / "2026"
    dados.mkdir(parents=True)
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    monkeypatch.setattr(escola, "nome", lambda: ESCOLA)
    monkeypatch.setattr(fv, "PAUSA_HOLERITE_S", 0)
    monkeypatch.setattr(fv, "PAUSA_LISTA_RH_S", 0)
    monkeypatch.setattr(fv, "RETRY_SLEEP_S", 0)
    return dados


# ───────────── nomes ─────────────

def test_normalizar_nome():
    assert fv.normalizar_nome("  Ana-Clara  d'Ávila ") == "ANA CLARA D AVILA"
    assert fv.normalizar_nome(None) == ""


def test_match_exato_e_abreviado():
    idx = fv.construir_indice(RH_SERVIDORES)
    tipo, achados = fv.buscar_por_nome("ana clara de souza lima", idx)
    assert tipo == "exato" and [a["numcad"] for a in achados] == ["1001"]
    tipo, achados = fv.buscar_por_nome("RENATA BEATRIZ DE PAULA O DO NASCIMENTO", idx)       # o caso do capturar_matriculas.py
    assert tipo == "abreviado" and achados[0]["numcad"] == "1003"
    assert fv.buscar_por_nome("FULANO INEXISTENTE", idx) == ("nenhum", [])
    assert fv.buscar_por_nome("", idx) == ("nenhum", [])


def test_homonimos_voltam_todos():
    tipo, achados = fv.buscar_por_nome("CARLA DIAS MELO", fv.construir_indice(RH_SERVIDORES))
    assert tipo == "exato" and [a["numcad"] for a in achados] == ["1004", "1005"]


def test_abreviacao_nao_inventa_casamento():
    assert fv.nomes_compativeis_abreviado("ANA SOUZA", "ANA CLARA SOUZA") is False
    assert fv.nomes_compativeis_abreviado("ANA C SOUZA", "ANA CLARA SOUZA") is True
    assert fv.nomes_compativeis_abreviado("ANA SOUZA", "ANA SOUZA") is False        # igual: é caso do exato


# ───────────── escola × local de trabalho ─────────────

@pytest.mark.parametrize("local,esperado", [
    ("ESCOLA JUDITH MACEDO SILVEIRA", True),
    ("ESCOLA MUNICIPAL PROFª JUDITH MACEDO SILVEIRA", True),
    ("E. M. Judith Macedo Silveira - PMPG-SME 40%", True),
    ("ESCOLA MUNICIPAL ANA NERI", False),
    ("SEDE SME", False),
    ("NAO INFORMADO", False),
    ("PACO MUNICIPAL", False),
    ("CAPELA SAO JOSE", False),
    ("", False), (None, False),
])
def test_local_confere(local, esperado):
    assert fv.local_confere(local, ESCOLA) is esperado


def test_local_parecido_so_com_token_generico_nao_casa():
    assert fv.local_confere("ESCOLA SAO JORGE", "Escola Municipal São José") is False


# ───────────── holerite ─────────────

def test_extrai_local_e_cargo_por_posicao():
    assert fv.extrair_local_trabalho(holerite_html()) == ("ESCOLA JUDITH MACEDO SILVEIRA", "PROFESSOR")


def test_so_lotacao_sem_local_devolve_none():
    assert fv.extrair_local_trabalho(holerite_html(com_local=False))[0] is None
    assert fv.extrair_local_trabalho("<html>sem spans</html>") == (None, None)


def test_analisar_holerite_e_rubrica_256():
    a = fv.analisar_holerite(holerite_html())
    assert a == {"local": "ESCOLA JUDITH MACEDO SILVEIRA", "cargo": "PROFESSOR", "estouro": False, "admissao": "01/02/2010", "erro": None}
    assert fv.analisar_holerite(holerite_html(estouro=True))["estouro"] is True
    assert "layout inesperado" in fv.analisar_holerite(holerite_html(com_local=False))["erro"]


def test_analise_nao_carrega_valores_de_salario():
    assert "999" not in json.dumps(fv.analisar_holerite(holerite_html()))


class Resp:
    def __init__(self, status=200, texto="", json_=None):
        self.status_code, self.text, self._json = status, texto, json_

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json is None:
            raise ValueError("não é JSON")
        return self._json


class Sessao:
    """Falso requests.Session: `respostas` é uma função url → Resp (ou levanta)."""
    def __init__(self, respostas):
        self.respostas, self.urls = respostas, []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.respostas(url)


def test_consultar_holerite_ok_404_e_rede(amb):
    s = Sessao(lambda u: Resp(texto=holerite_html()))
    r = fv.consultar_holerite(s, "1001", "09-2026")
    assert r["local"] == "ESCOLA JUDITH MACEDO SILVEIRA" and s.urls == ["https://rh.pontagrossa.pr.gov.br/estatisticas/holerite/1/1001/09-2026"]
    r = fv.consultar_holerite(Sessao(lambda u: Resp(404)), "1", "09-2026")
    assert "não encontrada (404)" in r["erro"]

    def cai(u): raise requests.ConnectionError("sem rede")
    s = Sessao(cai)
    r = fv.consultar_holerite(s, "1", "09-2026")
    assert "falha de conexão após 3 tentativas" in r["erro"] and len(s.urls) == 3


@pytest.mark.parametrize("mes,ok", [("09-2026", True), ("12-2025", True), ("13-2026", False), ("9-2026", False),
                                    ("2026-09", False), ("abc", False)])
def test_validar_mes(mes, ok):
    if ok:
        assert fv.validar_mes(mes) == mes
    else:
        with pytest.raises(ValueError, match="MM-AAAA"):
            fv.validar_mes(mes)


def test_mes_em_branco_e_o_anterior():
    m = fv.validar_mes("  ")
    assert fv.RE_MES.match(m) and m == fv.mes_anterior_padrao()


# ───────────── listas do RH ─────────────

def _json_rh(registros, total=None):
    return Resp(json_={"titulo": "Servidores", "aaData": registros, **({"iTotalRecords": total} if total else {})})


def test_lista_rh_sem_paginacao():
    s = Sessao(lambda u: _json_rh(RH_SERVIDORES))
    titulo, regs = fv.coletar_lista_rh_xhr(s, fv.URL_SERVIDORES)
    assert titulo == "Servidores" and len(regs) == 5 and len(s.urls) == 1
    assert s.urls[0].startswith("https://rh.pontagrossa.pr.gov.br/estatisticas/servidores/1?_=")


def test_lista_rh_com_paginacao():
    paginas = {0: RH_SERVIDORES[:2], 2: RH_SERVIDORES[2:4], 4: RH_SERVIDORES[4:]}

    def resp(url):
        if "iDisplayStart" not in url:
            return _json_rh(paginas[0], total=5)
        inicio = int(url.split("iDisplayStart=")[1].split("&")[0])
        assert "iDisplayLength=100" in url
        return _json_rh(paginas[inicio], total=5)
    s = Sessao(resp)
    _, regs = fv.coletar_lista_rh_xhr(s, fv.URL_SERVIDORES)
    assert [r["numcad"] for r in regs] == ["1001", "1002", "1003", "1004", "1005"] and len(s.urls) == 3


def test_lista_rh_pagina_vazia_encerra():
    def resp(url):
        return _json_rh([] if "iDisplayStart" in url else RH_SERVIDORES[:1], total=50)
    assert len(fv.coletar_lista_rh_xhr(Sessao(resp), fv.URL_SERVIDORES)[1]) == 1


def test_obter_servidores_grava_no_formato_original_e_reusa(amb):
    s = Sessao(lambda u: _json_rh(RH_SERVIDORES))
    regs = fv.obter_servidores_rh(False, s)
    assert len(regs) == 5 and len(s.urls) == 1
    bruto = json.loads(fv.arquivo_rh_servidores().read_text(encoding="utf-8"))
    assert bruto["total_geral_servidores"] == 5 and bruto["empresas"][0]["numemp"] == 1 and len(bruto["empresas"][0]["servidores"]) == 5
    fv.obter_servidores_rh(False, s)                                   # menos de 24 h: não baixa de novo
    assert len(s.urls) == 1
    fv.obter_servidores_rh(True, s)                                    # forçar
    assert len(s.urls) == 2


def test_cache_velho_e_baixado_de_novo(amb):
    s = Sessao(lambda u: _json_rh(RH_SERVIDORES))
    fv.obter_servidores_rh(False, s)
    velho = time.time() - 25 * 3600
    os.utime(fv.arquivo_rh_servidores(), (velho, velho))
    fv.obter_servidores_rh(False, s)
    assert len(s.urls) == 2


def test_falha_do_rh_vira_erro_claro(amb):
    def cai(u): raise requests.ConnectionError("fora do ar")
    with pytest.raises(RuntimeError, match="lista de servidores do RH"):
        fv.obter_servidores_rh(False, Sessao(cai))
    with pytest.raises(RuntimeError, match="veio vazia"):
        fv.obter_servidores_rh(True, Sessao(lambda u: _json_rh([])))
    assert not fv.arquivo_rh_servidores().exists()                      # nada de arquivo vazio como se fosse coleta


TABELA_TERCEIRIZADOS = """<table><thead><tr><th>Razão Social</th></tr></thead><tbody>
<tr><td>LIMPEZA LTDA</td><td>JOANA PEREIRA</td><td>01/03/2025</td><td></td><td>AUXILIAR DE LIMPEZA</td></tr>
<tr><td>curta</td><td>x</td></tr></tbody></table>"""


def test_terceirizados_html_e_erros(amb):
    regs, erro = fv.obter_lista_extra("terceirizados", True, Sessao(lambda u: Resp(texto=TABELA_TERCEIRIZADOS)))
    assert erro is None and regs == [{"razao_social": "LIMPEZA LTDA", "nomfun": "JOANA PEREIRA", "dt_inicio": "01/03/2025",
                                      "dt_fim": "", "titcar": "AUXILIAR DE LIMPEZA"}]
    assert fv.arquivo_rh_terceirizados().exists()
    regs, erro = fv.obter_lista_extra("terceirizados", True, Sessao(lambda u: Resp(texto="<html>sem tabela</html>")))
    assert regs == [] and "tabela" in erro
    regs, erro = fv.obter_lista_extra("estagiarios", True, Sessao(lambda u: Resp(500)))
    assert regs == [] and "500" in erro


def test_estagiarios_xhr(amb):
    regs, erro = fv.obter_lista_extra("estagiarios", True, Sessao(lambda u: _json_rh([{"nomfun": "LUIZ ESTAGIARIO"}])))
    assert erro is None and regs == [{"nomfun": "LUIZ ESTAGIARIO"}]


def test_lista_extra_usa_cache(amb):
    s = Sessao(lambda u: Resp(texto=TABELA_TERCEIRIZADOS))
    fv.obter_lista_extra("terceirizados", True, s)
    n = len(s.urls)
    regs, _ = fv.obter_lista_extra("terceirizados", False, s)
    assert len(s.urls) == n and len(regs) == 1


# ───────────── classificação ─────────────

IDX = fv.construir_indice(RH_SERVIDORES)
IDX_EST = fv.construir_indice([{"nomfun": "LUIZ ESTAGIARIO"}, {"nomfun": "DUPLO NOME TESTE"}, {"nomfun": "ANA MARIA DUDA"}])
IDX_TER = fv.construir_indice([{"nomfun": "JOANA PEREIRA SANTOS", "razao_social": "LIMPEZA LTDA"}, {"nomfun": "DUPLO NOME TESTE"}])


def um(nome, funcao="Professor", **kw):
    return fv.classificar([sere(nome, "11122233344", funcao)], IDX, kw.get("est", IDX_EST), kw.get("ter", IDX_TER))[0]


def test_servidor_exato():
    r = um("ANA CLARA DE SOUZA LIMA")
    assert r["vinculo"] == "servidor" and r["terceirizado"] is False and r["matricula_encontrada"] is True
    assert (r["numcad"], r["titcar"], r["origem_vinculo"], r["match_tipo"], r["match_score"]) == ("1001", "PROFESSOR", "servidores", "exato", 100.0)
    assert r["vinculos_servidores"][0]["nomemp"].startswith("PREFEITURA") and r["multiplas_matriculas"] is False
    assert r["na_escola"] is None and r["comprovacao"] == "nenhuma"        # ainda sem holerite
    assert r["dados_originais"]["email"] == "11122233344@x.com" and r["revisar"] == []


def test_servidor_so_por_nome_abreviado_pede_revisao():
    r = um("RENATA BEATRIZ DE PAULA O DO NASCIMENTO")
    assert r["numcad"] == "1003" and r["match_tipo"] == "abreviado" and r["match_score"] == 90.0
    assert "abreviado" in r["aviso_match_abreviado"] and any("abreviação" in m for m in r["revisar"])


def test_homonimos_viram_varias_matriculas():
    r = um("CARLA DIAS MELO")
    assert r["multiplas_matriculas"] is True and [v["numcad"] for v in r["vinculos_servidores"]] == ["1004", "1005"]
    assert any("2 matrículas" in m for m in r["revisar"])


def test_nome_curto_e_sinalizado():
    r = um("BETO ROCHA")
    assert r["nome_curto_risco_homonimo"] is True and any("até 2 palavras" in m for m in r["revisar"])
    assert um("ANA CLARA DE SOUZA LIMA")["nome_curto_risco_homonimo"] is False


def test_fora_do_rh_e_terceirizado_por_inferencia():
    r = um("MARIA TERCEIRIZADA DA SILVA")
    assert r["vinculo"] == "terceirizado" and r["terceirizado"] is True and r["terceirizado_origem"] == "nao_consta_no_rh"
    assert r["matricula_encontrada"] is False and r["numcad"] is None
    assert (r["na_escola"], r["comprovacao"]) == (True, "sere")             # comprovada pelo SERE (não há holerite)
    assert any("inferência" in m for m in r["revisar"])


def test_terceirizado_que_consta_na_lista_do_rh():
    r = um("JOANA PEREIRA SANTOS")
    assert r["terceirizado"] is True and r["terceirizado_origem"] == "lista_rh" and r["origem_vinculo"] == "terceirizados"
    assert r["revisar"] == []


def test_estagiario_nao_e_terceirizado():
    r = um("LUIZ ESTAGIARIO")
    assert r["vinculo"] == "estagiario" and r["terceirizado"] is False and r["origem_vinculo"] == "estagiarios"
    assert (r["na_escola"], r["comprovacao"]) == (True, "sere")


def test_bateu_em_estagiarios_e_terceirizados_pede_revisao():
    r = um("DUPLO NOME TESTE")
    assert r["terceirizado"] is True and any("estagiários E terceirizados" in m for m in r["revisar"])


def test_listas_extras_indisponiveis_nao_impedem():
    r = um("MARIA TERCEIRIZADA DA SILVA", est=None, ter=None)
    assert r["terceirizado"] is True and r["terceirizado_origem"] == "nao_consta_no_rh"


def test_outras_funcoes_mostra_o_que_achou_nas_outras_listas():
    r = um("ANA MARIA DUDA", funcao="Outras funções")                       # estagiário no RH; não é servidor
    assert r["vinculo"] == "estagiario" and r["estagiario_encontrado"]["match"] is True
    r = fv.classificar([sere("ANA CLARA DE SOUZA LIMA", "1", "Outras funções")], IDX, fv.construir_indice([{"nomfun": "ANA CLARA DE SOUZA LIMA"}]), IDX_TER)[0]
    assert r["vinculo"] == "servidor" and r["terceirizado_encontrado"]["match"] is False and r["estagiario_encontrado"]["match"] is True
    assert any("Outras funções" in m for m in r["revisar"])


def test_precisa_listas_extras():
    assert fv.precisa_listas_extras([sere("ANA CLARA DE SOUZA LIMA", "1")], IDX) is False
    assert fv.precisa_listas_extras([sere("ANA CLARA DE SOUZA LIMA", "1"), sere("NINGUEM DA SILVA", "2")], IDX) is True
    assert fv.precisa_listas_extras([sere("ANA CLARA DE SOUZA LIMA", "1", "Outras funções")], IDX) is True


def test_formato_compativel_com_capturar_matriculas_e_com_os_termos():
    """O arquivo continua legível pelo termo_ciencia: servidor entra com matrícula; terceirizado cai em 'sem matrícula'."""
    from src.automacao import termo_ciencia
    regs = fv.classificar([sere("ANA CLARA DE SOUZA LIMA", "1"), sere("MARIA TERCEIRIZADA DA SILVA", "2")], IDX, IDX_EST, IDX_TER)
    originais = {"cpf", "nome", "funcao", "nome_curto_risco_homonimo", "matricula_encontrada", "numcad", "numemp", "nomemp",
                 "nomloc", "titcar", "datadm", "dessit", "forma_ingresso", "match_score", "match_nome_api", "origem_vinculo",
                 "dados_originais", "vinculos_servidores", "multiplas_matriculas", "match_tipo"}
    assert originais <= set(regs[0])
    linhas, sem_matricula = termo_ciencia.montar_lista(regs)
    assert [(l["nome"], l["matricula"]) for l in linhas] == [("ANA CLARA DE SOUZA LIMA", "1001")]
    assert sem_matricula == ["MARIA TERCEIRIZADA DA SILVA"]


# ───────────── comprovação ─────────────

def hol(local, erro=None, estouro=False):
    return {"local": local, "cargo": "PROFESSOR", "estouro": estouro, "erro": erro}


def servidor(nome="ANA CLARA DE SOUZA LIMA"):
    return um(nome)


def test_confirmado_pelo_holerite():
    r = servidor()
    fv.aplicar_comprovacao(r, {"1001": hol("ESCOLA JUDITH MACEDO SILVEIRA")}, ESCOLA, "09-2026")
    assert (r["na_escola"], r["comprovacao"], r["holerite_mes"]) == (True, "holerite", "09-2026")
    assert r["local_trabalho_holerite"] == "ESCOLA JUDITH MACEDO SILVEIRA" and r["revisar"] == []


def test_holerite_aponta_outro_local():
    r = servidor()
    fv.aplicar_comprovacao(r, {"1001": hol("ESCOLA MUNICIPAL ANA NERI")}, ESCOLA, "09-2026")
    assert r["na_escola"] is False and r["comprovacao"] == "holerite"
    assert any("outro local de trabalho: ESCOLA MUNICIPAL ANA NERI" in m for m in r["revisar"])
    r = servidor()
    fv.aplicar_comprovacao(r, {"1001": hol("SEDE SME")}, ESCOLA, "09-2026")
    assert r["na_escola"] is False


@pytest.mark.parametrize("resultado,trecho", [
    (hol(None, erro="matrícula 1001 não encontrada (404) para 09-2026"), "404"),
    (hol("ESCOLA JUDITH MACEDO SILVEIRA", estouro=True), "rubrica 256"),
    (None, "não consultada"),
])
def test_sem_comprovacao(resultado, trecho):
    r = servidor()
    fv.aplicar_comprovacao(r, {} if resultado is None else {"1001": resultado}, ESCOLA, "09-2026")
    assert r["na_escola"] is None and r["comprovacao"] == "nenhuma" and any(trecho in m for m in r["revisar"])


def test_holerite_desempata_homonimos():
    r = um("CARLA DIAS MELO")
    fv.aplicar_comprovacao(r, {"1004": hol("ESCOLA JUDITH MACEDO SILVEIRA"), "1005": hol("CMEI OUTRO LUGAR")}, ESCOLA, "09-2026")
    assert r["na_escola"] is True and r["numcad"] == "1004"
    assert [v["numcad"] for v in r["vinculos_servidores"]] == ["1004"] and r["multiplas_matriculas"] is False
    assert [v["numcad"] for v in r["vinculos_descartados"]] == ["1005"]
    assert not any("matrículas com esse nome" in m for m in r["revisar"])
    r = um("CARLA DIAS MELO")                                                # a outra ordem: o desempate muda o numcad principal
    fv.aplicar_comprovacao(r, {"1004": hol("CMEI OUTRO LUGAR"), "1005": hol("ESCOLA JUDITH MACEDO SILVEIRA")}, ESCOLA, "09-2026")
    assert r["numcad"] == "1005" and r["nomloc"] == "OUTRA"


def test_duas_matriculas_na_mesma_escola_ficam_as_duas():
    r = um("CARLA DIAS MELO")
    fv.aplicar_comprovacao(r, {"1004": hol("ESCOLA JUDITH MACEDO SILVEIRA"), "1005": hol("ESCOLA JUDITH MACEDO SILVEIRA")}, ESCOLA, "09-2026")
    assert r["na_escola"] is True and len(r["vinculos_servidores"]) == 2 and r["multiplas_matriculas"] is True


def test_homonimos_sem_confirmacao_nenhuma():
    r = um("CARLA DIAS MELO")
    fv.aplicar_comprovacao(r, {"1004": hol("CMEI A"), "1005": hol("CMEI B")}, ESCOLA, "09-2026")
    assert r["na_escola"] is False and len(r["vinculos_servidores"]) == 2          # nada descartado sem prova


# ───────────── ajustes manuais ─────────────

def test_ajustes_por_cpf_e_por_nome(amb):
    fv.arquivo_ajustes().write_text(json.dumps({
        "111.222.333-44": {"terceirizado": False, "na_escola": True, "observacao": "nome grafado diferente no RH"},
        "Fulano de Tal": {"terceirizado": True}}), encoding="utf-8")
    ajustes = fv.carregar_ajustes()
    assert set(ajustes) == {"11122233344", "FULANO DE TAL"}
    regs = fv.classificar([sere("MARIA TERCEIRIZADA DA SILVA", "11122233344"), sere("Fulano de Tal", "99999999999"),
                           sere("ANA CLARA DE SOUZA LIMA", "55555555555")], IDX, IDX_EST, IDX_TER)
    assert fv.aplicar_ajustes(regs, ajustes) == 2
    maria, fulano, ana = regs
    assert maria["terceirizado"] is False and maria["vinculo"] == "outro" and maria["terceirizado_origem"] is None
    assert maria["na_escola"] is True and maria["comprovacao"] == "manual" and maria["ajuste_manual"] is True
    assert maria["revisar"] == [] and maria["observacao"] == "nome grafado diferente no RH"
    assert fulano["terceirizado"] is True and fulano["vinculo"] == "terceirizado"
    assert ana["ajuste_manual"] is False


def test_sem_arquivo_de_ajustes_e_ajustes_ilegiveis(amb):
    assert fv.carregar_ajustes() == {}
    fv.arquivo_ajustes().write_text("{x", encoding="utf-8")
    with pytest.raises(ValueError, match="ilegível"):
        fv.carregar_ajustes()


# ───────────── resumo ─────────────

def test_resumo():
    regs = fv.classificar([sere("ANA CLARA DE SOUZA LIMA", "1"), sere("MARIA TERCEIRIZADA DA SILVA", "2"), sere("LUIZ ESTAGIARIO", "3")], IDX, IDX_EST, IDX_TER)
    fv.aplicar_comprovacao(regs[0], {"1001": hol("ESCOLA JUDITH MACEDO SILVEIRA")}, ESCOLA, "09-2026")
    assert fv.resumir(regs) == {"total": 3, "servidores": 1, "estagiarios": 1, "terceirizados": 1,
                                "confirmados_na_escola": 3, "fora_da_escola": 0, "sem_comprovacao": 0, "a_revisar": 1}


# ───────────── fluxo completo (assíncrono, tudo simulado) ─────────────

@pytest.fixture()
def fluxo(amb, monkeypatch):
    estado = {"holerites": [], "rh": 0, "extras": 0, "sere": 0}
    (amb / "funcionarios.json").write_text(json.dumps([
        sere("ANA CLARA DE SOUZA LIMA", "11111111111"), sere("CARLA DIAS MELO", "22222222222"),
        sere("MARIA TERCEIRIZADA DA SILVA", "33333333333"), sere("BETO ROCHA", "44444444444")]), encoding="utf-8")

    def servidores_rh(forcar=False, session=None):
        estado["rh"] += 1
        return RH_SERVIDORES

    def extras(nome, forcar=False, session=None):
        estado["extras"] += 1
        return [], None

    locais = {"1001": "ESCOLA JUDITH MACEDO SILVEIRA", "1004": "ESCOLA JUDITH MACEDO SILVEIRA", "1005": "CMEI OUTRO", "1002": "SEDE SME"}

    def holerite(session, matricula, mes):
        estado["holerites"].append((matricula, mes))
        return hol(locais[matricula])
    monkeypatch.setattr(fv, "obter_servidores_rh", servidores_rh)
    monkeypatch.setattr(fv, "obter_lista_extra", extras)
    monkeypatch.setattr(fv, "consultar_holerite", holerite)
    return estado


def rodar(**kw):
    return asyncio.run(fv.vincular_funcionarios_da_escola(**{"mes": "09-2026", **kw}))


def test_fluxo_completo(fluxo, amb, capsys):
    r = rodar()
    assert r["total"] == 4 and r["servidores"] == 3 and r["terceirizados"] == 1
    assert r["confirmados_na_escola"] == 3 and r["fora_da_escola"] == 1 and r["a_revisar"] >= 2
    assert r["holerite_mes"] == "09-2026" and r["comprovou"] is True and r["arquivo"] == str(amb / "funcionarios_matriculas.json")
    assert "nome" not in r and "cpf" not in str(r)                             # a tela recebe só o resumo
    regs = {x["nome"]: x for x in json.loads((amb / "funcionarios_matriculas.json").read_text(encoding="utf-8"))}
    ana, carla, maria, beto = (regs[n] for n in ("ANA CLARA DE SOUZA LIMA", "CARLA DIAS MELO", "MARIA TERCEIRIZADA DA SILVA", "BETO ROCHA"))
    assert (ana["na_escola"], ana["numcad"], ana["comprovacao"]) == (True, "1001", "holerite")
    assert (carla["na_escola"], carla["numcad"], len(carla["vinculos_servidores"])) == (True, "1004", 1)     # holerite desempatou
    assert (maria["terceirizado"], maria["na_escola"], maria["comprovacao"], maria["numcad"]) == (True, True, "sere", None)
    assert (beto["na_escola"], beto["local_trabalho_holerite"]) == (False, "SEDE SME")
    assert sorted(m for m, _ in fluxo["holerites"]) == ["1001", "1002", "1004", "1005"] and all(mes == "09-2026" for _, mes in fluxo["holerites"])
    saida = capsys.readouterr().out
    assert "Terceirizados:" in saida and "MARIA TERCEIRIZADA DA SILVA" in saida and "Para revisar" in saida


def test_cache_guarda_so_o_resultado_nunca_o_holerite(fluxo, amb):
    rodar()
    cache = json.loads((amb / "cache_holerites.json").read_text(encoding="utf-8"))
    assert set(cache) == {"1001_09-2026", "1002_09-2026", "1004_09-2026", "1005_09-2026"}
    assert set(cache["1001_09-2026"]) == {"local", "cargo", "estouro", "admissao"} and not list(amb.glob("**/*.html"))


def test_segunda_rodada_usa_o_cache_e_nao_consulta_o_rh(fluxo):
    rodar()
    n = len(fluxo["holerites"])
    rodar()
    assert len(fluxo["holerites"]) == n
    rodar(mes="10-2026")                                                          # outro mês: consulta de novo
    assert len(fluxo["holerites"]) == 2 * n


def test_erro_de_holerite_nao_entra_no_cache_e_vira_pendencia(fluxo, amb, monkeypatch):
    monkeypatch.setattr(fv, "consultar_holerite", lambda s, m, mes: hol(None, erro="falha de conexão"))
    r = rodar()
    assert r["confirmados_na_escola"] == 1 and r["sem_comprovacao"] == 3           # só a terceirizada segue "na escola" (SERE)
    assert not (amb / "cache_holerites.json").exists()


def test_pular_holerite(fluxo):
    r = rodar(comprovar=False)
    assert fluxo["holerites"] == [] and r["comprovou"] is False and r["holerite_mes"] is None
    assert r["sem_comprovacao"] == 3 and r["terceirizados"] == 1


def test_ajuste_manual_entra_no_arquivo(fluxo, amb):
    (amb / "funcionarios_ajustes.json").write_text(json.dumps({"44444444444": {"na_escola": True}}), encoding="utf-8")
    rodar()
    regs = {x["nome"]: x for x in json.loads((amb / "funcionarios_matriculas.json").read_text(encoding="utf-8"))}
    assert regs["BETO ROCHA"]["na_escola"] is True and regs["BETO ROCHA"]["ajuste_manual"] is True and regs["BETO ROCHA"]["revisar"] == []


def test_so_baixa_as_listas_extras_quando_precisa(fluxo, amb):
    (amb / "funcionarios.json").write_text(json.dumps([sere("ANA CLARA DE SOUZA LIMA", "1")]), encoding="utf-8")
    rodar()
    assert fluxo["extras"] == 0
    (amb / "funcionarios.json").write_text(json.dumps([sere("ANA CLARA DE SOUZA LIMA", "1"), sere("NINGUEM DA SILVA", "2")]), encoding="utf-8")
    rodar()
    assert fluxo["extras"] == 2


def test_lista_extra_com_erro_avisa_e_segue(fluxo, monkeypatch, capsys):
    monkeypatch.setattr(fv, "obter_lista_extra", lambda n, f=False, s=None: ([], "a página não traz a tabela"))
    r = rodar()
    assert r["terceirizados"] == 1 and "não consegui ler a lista de terceirizados" in capsys.readouterr().out


def test_sem_funcionarios_json_coleta_antes_no_sere(fluxo, amb, monkeypatch):
    (amb / "funcionarios.json").unlink()
    chamadas = []

    async def coleta(modo):
        chamadas.append(modo)
        (amb / "funcionarios.json").write_text(json.dumps([sere("ANA CLARA DE SOUZA LIMA", "1")]), encoding="utf-8")
        return []
    monkeypatch.setattr("src.automacao.servidores.coletar_servidores_via_login", coleta)
    r = rodar()
    assert chamadas == ["basico"] and r["total"] == 1


def test_atualizar_sere_refaz_a_coleta_mesmo_com_arquivo(fluxo, amb, monkeypatch):
    chamadas = []

    async def coleta(modo):
        chamadas.append(modo)
        return []
    monkeypatch.setattr("src.automacao.servidores.coletar_servidores_via_login", coleta)
    rodar(atualizar_sere=True)
    assert chamadas == ["basico"]


def test_lista_do_sere_vazia(fluxo, amb, monkeypatch):
    async def coleta(modo): (amb / "funcionarios.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("src.automacao.servidores.coletar_servidores_via_login", coleta)
    (amb / "funcionarios.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="lista de funcionários do SERE está vazia"):
        rodar()


def test_pedido_invalido_nem_abre_conexao(fluxo, monkeypatch):
    with pytest.raises(ValueError, match="MM-AAAA"):
        rodar(mes="99-2026")
    monkeypatch.setattr(escola, "nome", lambda: "")
    with pytest.raises(ValueError, match="nome da escola"):
        rodar()
    assert fluxo["rh"] == 0


def test_cancelamento_durante_a_comprovacao(fluxo, amb):
    async def cenario():
        tarefa = asyncio.create_task(fv.vincular_funcionarios_da_escola(mes="09-2026"))
        await asyncio.sleep(0)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
    asyncio.run(cenario())
    assert not (amb / "funcionarios_matriculas.json").exists()                    # cancelou: não grava saída pela metade


# ───────────── registro, tela e CLI ─────────────

@pytest.fixture()
def web(fluxo, amb, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: amb)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


def _esperar(c, chave="vinculos"):
    for _ in range(300):
        s = c.get(f"/web/api/automacoes/{chave}/status").get_json()
        if s["status"] not in ("executando",):
            return s
        time.sleep(0.03)
    pytest.fail("não terminou")


def test_registrada_e_na_lista(web):
    s = reg.obter("vinculos")
    assert s is not None and s.recursos == () and s.confirmar is False
    assert [e["nome"] for e in s.extras()] == ["modo", "so_nome", "pular_holerite", "mes", "atualizar_sere", "forcar_coleta"]
    itens = web.get("/web/api/automacoes/lista").get_json()["itens"]
    item = next(i for i in itens if i["chave"] == "vinculos")
    assert item["nome"] == "Vínculos dos funcionários" and "terceirizados" in item["descricao"]


def test_plano(web):
    plano = reg.obter("vinculos").planejar(Opcoes(), {"mes": "08-2026", "pular_holerite": True, "forcar_coleta": True}, {}, {})
    assert plano.tipo == "coroutine" and plano.funcao is fv.vincular_funcionarios_da_escola
    assert plano.kwargs == {"modo": "vincular", "mes": "08-2026", "forcar_coleta": True, "atualizar_sere": False, "so_nome": ""}
    assert reg.obter("vinculos").planejar(Opcoes(), {}, {}, {}).kwargs["mes"] == fv.mes_anterior_padrao()


def test_executar_pela_web(web, amb):
    assert web.post("/web/api/automacoes/vinculos/executar", json={"mes": "09-2026"}).status_code == 200
    s = _esperar(web)
    assert s["status"] == "concluido"
    assert rotas._EXECUCOES["vinculos"]["resultado"]["terceirizados"] == 1 and (amb / "funcionarios_matriculas.json").exists()
    assert any("Terceirizados:" in linha for linha in s["logs"])


def test_pedido_ruim_da_400(web):
    r = web.post("/web/api/automacoes/vinculos/executar", json={"mes": "13-2026"})
    assert r.status_code == 400 and "MM-AAAA" in r.get_json()["mensagem"]


def test_cli_simular(web, capsys):
    from src.comum import cli
    assert cli.main(["vinculos", "--mes", "09-2026", "--pular-holerite", "--simular"]) == 0
    assert "vincular_funcionarios_da_escola" in capsys.readouterr().out
    assert cli.main(["vinculos", "--mes", "xx", "--simular"]) == 2


def test_tela_de_funcionarios_mostra_terceirizado_e_filtros(web, amb):
    (amb / "funcionarios_completo.json").write_text("[]", encoding="utf-8")
    web.post("/web/api/automacoes/vinculos/executar", json={"mes": "09-2026"})
    _esperar(web)
    d = web.get("/web/api/funcionarios/lista").get_json()
    por_nome = {f["nome"]: f for f in d["funcionarios"]}
    maria, ana, beto = por_nome["MARIA TERCEIRIZADA DA SILVA"], por_nome["ANA CLARA DE SOUZA LIMA"], por_nome["BETO ROCHA"]
    assert maria["terceirizado"] is True and maria["vinculo"] == "terceirizado" and maria["matricula"] == ""
    assert maria["detalhe"]["vinculo"] == "Terceirizado" and maria["detalhe"]["situacao_na_escola"] == "Consta no SERE desta escola"
    assert ana["vinculo"] == "servidor" and ana["matricula"] == "1001" and ana["detalhe"]["situacao_na_escola"] == "Confirmada pelo holerite"
    assert ana["detalhe"]["local_holerite"] == "ESCOLA JUDITH MACEDO SILVEIRA"
    assert beto["na_escola"] is False and "outro local" in beto["detalhe"]["revisar"]
    rotulos = {c["label"]: c["valor"] for c in d["cartoes"]}
    assert rotulos["Terceirizados"] == 1 and rotulos["A revisar"] >= 2


def test_tela_sem_vinculos_nao_muda(web, amb):
    d = web.get("/web/api/funcionarios/lista").get_json()
    assert {c["label"] for c in d["cartoes"]} == {"Total Funcionários", "Docentes", "Pedagogos(as)", "Auxiliares / Sec.", "Direção", "Cadastro Completo"}
    assert all(f["vinculo"] == "" and f["terceirizado"] is False for f in d["funcionarios"])


def test_tela_tem_o_filtro_e_o_selo():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    html = (raiz / "src/web/templates/partials/funcionarios_cards.html").read_text(encoding="utf-8")
    assert 'id="func-vinculo"' in html and 'value="terceirizado"' in html
    assert 'badge("Terceirizado", "bg-amber")' in js and "funcState.vinculo" in js and "func-vinculo" in js


# ───────────── modos de consulta: sere / vincular / homonimos / completo ─────────────

def test_admissao_vem_da_linha_ancora_do_holerite():
    assert fv.extrair_admissao(holerite_html()) == "01/02/2010"
    assert fv.extrair_admissao("<html></html>") is None


def test_normalizar_modo():
    assert fv.normalizar_modo(None) == "completo" and fv.normalizar_modo("") == "completo"
    assert fv.normalizar_modo(None, comprovar=False) == "vincular"          # compatibilidade com o parâmetro antigo
    assert fv.normalizar_modo(" Homonimos ") == "homonimos"
    with pytest.raises(ValueError, match="desconhecido"):
        fv.normalizar_modo("tudo")


def test_modo_sere_nao_exige_mes_nem_escola(amb, monkeypatch):
    monkeypatch.setattr(escola, "nome", lambda: "")
    assert fv.validar_pedido("lixo", "sere") == ""
    with pytest.raises(ValueError, match="nome da escola"):
        fv.validar_pedido("09-2026", "homonimos")
    assert fv.validar_pedido("09-2026", "vincular") == "09-2026"           # sem holerite, a escola não faz falta
    with pytest.raises(ValueError, match="MM-AAAA"):
        fv.validar_pedido("13-2026", "completo")


# 20h + 20h

def test_duas_matriculas_lotadas_aqui_ficam_com_cargo_e_admissao_e_sem_revisao():
    r = um("CARLA DIAS MELO")
    r["vinculos_servidores"][0].update(titcar="PROFESSOR 20H", datadm="01/03/2010")
    r["vinculos_servidores"][1].update(titcar="PROFESSOR 20H", datadm="15/08/2018")
    fv.aplicar_comprovacao(r, {"1004": hol("ESCOLA JUDITH MACEDO SILVEIRA"), "1005": hol("ESCOLA JUDITH MACEDO SILVEIRA")}, ESCOLA, "09-2026")
    assert r["na_escola"] is True and r["multiplas_matriculas"] is True and "vinculos_descartados" not in r
    assert [(v["numcad"], v["titcar"], v["datadm"], v["na_escola"]) for v in r["vinculos_servidores"]] == [
        ("1004", "PROFESSOR 20H", "01/03/2010", True), ("1005", "PROFESSOR 20H", "15/08/2018", True)]
    assert r["revisar"] == []                                               # não é homônimo: é a mesma pessoa em dois concursos
    assert "dois concursos" in r["observacao_vinculo"] and "1004" in r["observacao_vinculo"] and "15/08/2018" in r["observacao_vinculo"]


def test_duas_matriculas_com_nome_curto_ainda_pedem_conferencia():
    r = fv.classificar([sere("CARLA MELO", "1")], fv.construir_indice([rh("2001", "CARLA MELO"), rh("2002", "CARLA MELO")]), None, None)[0]
    fv.aplicar_comprovacao(r, {"2001": hol("ESCOLA JUDITH MACEDO SILVEIRA"), "2002": hol("ESCOLA JUDITH MACEDO SILVEIRA")}, ESCOLA, "09-2026")
    assert r["na_escola"] is True and len(r["vinculos_servidores"]) == 2
    assert any("até 2 palavras" in m for m in r["revisar"])


def test_matricula_em_outro_local_e_descartada_com_o_motivo_e_o_local():
    r = um("CARLA DIAS MELO")
    fv.aplicar_comprovacao(r, {"1004": hol("ESCOLA JUDITH MACEDO SILVEIRA"), "1005": hol("CMEI OUTRO LUGAR")}, ESCOLA, "09-2026")
    d = r["vinculos_descartados"][0]
    assert (d["numcad"], d["local_holerite"], d["motivo"]) == ("1005", "CMEI OUTRO LUGAR", "holerite aponta outro local de trabalho")
    assert "1005" in r["observacao_vinculo"] and "CMEI OUTRO LUGAR" in r["observacao_vinculo"] and "segundo concurso" in r["observacao_vinculo"]
    assert r["multiplas_matriculas"] is False


def test_cargo_e_admissao_do_holerite_completam_o_cadastro_do_rh():
    sem_dados = fv.construir_indice([rh("3001", "DANIELA PAULA SOUZA RAMOS", titcar=None, datadm=None)])
    r = fv.classificar([sere("DANIELA PAULA SOUZA RAMOS", "9")], sem_dados, None, None)[0]
    assert (r["titcar"], r["datadm"]) == (None, None)
    fv.aplicar_comprovacao(r, {"3001": {"local": "ESCOLA JUDITH MACEDO SILVEIRA", "cargo": "AUXILIAR DE SERVICOS", "estouro": False,
                                        "admissao": "10/05/2012", "erro": None}}, ESCOLA, "09-2026")
    assert r["vinculos_servidores"][0]["titcar"] == "AUXILIAR DE SERVICOS" and r["vinculos_servidores"][0]["datadm"] == "10/05/2012"
    reg_rh = rh("3002", "ELIANA PAULA RAMOS DIAS", titcar="PROFESSOR", datadm="02/02/2002")                  # o do RH não é trocado
    r2 = fv.classificar([sere("ELIANA PAULA RAMOS DIAS", "8")], fv.construir_indice([reg_rh]), None, None)[0]
    fv.aplicar_comprovacao(r2, {"3002": {"local": "ESCOLA JUDITH MACEDO SILVEIRA", "cargo": "OUTRO", "estouro": False, "admissao": "09/09/2009", "erro": None}}, ESCOLA, "09-2026")
    assert (r2["titcar"], r2["datadm"]) == ("PROFESSOR", "02/02/2002")


# fluxo por modo

def _saida(amb):
    return {x["nome"]: x for x in json.loads((amb / "funcionarios_matriculas.json").read_text(encoding="utf-8"))}


def test_modo_vincular_traz_matricula_cargo_e_admissao_sem_holerite(fluxo, amb):
    r = rodar(modo="vincular")
    assert r["modo"] == "vincular" and r["comprovou"] is False and r["holerite_mes"] is None and fluxo["holerites"] == []
    ana = _saida(amb)["ANA CLARA DE SOUZA LIMA"]
    assert (ana["numcad"], ana["titcar"], ana["datadm"], ana["na_escola"], ana["comprovacao"]) == ("1001", "PROFESSOR", "01/02/2010", None, "nenhuma")
    assert _saida(amb)["MARIA TERCEIRIZADA DA SILVA"]["terceirizado"] is True


def test_modo_completo_e_o_padrao_e_o_antigo_comprovar_false_vira_vincular(fluxo):
    assert rodar()["modo"] == "completo" and fluxo["holerites"]
    fluxo["holerites"].clear()
    assert rodar(comprovar=False)["modo"] == "vincular" and fluxo["holerites"] == []


def test_modo_sere_so_consulta_o_sere_e_devolve_resumo(fluxo, amb, monkeypatch):
    chamadas = []

    async def coleta(modo):
        chamadas.append(modo)
    monkeypatch.setattr("src.automacao.servidores.coletar_servidores_via_login", coleta)
    r = asyncio.run(fv.vincular_funcionarios_da_escola(modo="sere"))
    assert chamadas == ["basico"] and fluxo["rh"] == 0 and fluxo["holerites"] == []
    assert r["modo"] == "sere" and r["total"] == 4 and r["por_funcao"] == {"Professor": 4} and r["arquivo"] == str(amb / "funcionarios.json")
    assert "cpf" not in str(r) and not (amb / "funcionarios_matriculas.json").exists()


def test_modo_sere_com_lista_vazia_da_erro(fluxo, amb, monkeypatch):
    async def coleta(modo):
        (amb / "funcionarios.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("src.automacao.servidores.coletar_servidores_via_login", coleta)
    with pytest.raises(ValueError, match="vazia"):
        asyncio.run(fv.vincular_funcionarios_da_escola(modo="sere"))


def test_modo_homonimos_consulta_so_quem_tem_mais_de_uma_matricula(fluxo, amb, capsys):
    r = rodar(modo="homonimos")
    assert sorted(m for m, _ in fluxo["holerites"]) == ["1004", "1005"]                  # só a Carla (duas matrículas)
    assert r["modo"] == "homonimos" and r["verificados"] == 1 and r["desempatados"] == 1 and r["duas_matriculas_na_escola"] == 0
    carla = _saida(amb)["CARLA DIAS MELO"]
    assert (carla["numcad"], carla["na_escola"], len(carla["vinculos_servidores"])) == ("1004", True, 1)
    assert carla["vinculos_descartados"][0]["numcad"] == "1005"
    assert _saida(amb)["ANA CLARA DE SOUZA LIMA"]["na_escola"] is None                  # não foi verificada nesta rodada
    assert "Verificação de homônimos" in capsys.readouterr().out


def test_modo_homonimos_mantem_o_resultado_ja_gravado_dos_demais(fluxo, amb):
    rodar(modo="completo")
    (amb / "cache_holerites.json").unlink()                                             # sem cache: só os alvos podem ser consultados
    fluxo["holerites"].clear()
    r = rodar(modo="homonimos")
    assert sorted(m for m, _ in fluxo["holerites"]) == ["1004", "1005"]
    s = _saida(amb)
    assert (s["ANA CLARA DE SOUZA LIMA"]["na_escola"], s["ANA CLARA DE SOUZA LIMA"]["comprovacao"]) == (True, "holerite")
    assert (s["BETO ROCHA"]["na_escola"], s["BETO ROCHA"]["local_trabalho_holerite"]) == (False, "SEDE SME")
    assert r["confirmados_na_escola"] == 3 and r["fora_da_escola"] == 1


def test_homonimos_nao_herda_se_o_rh_mudou(fluxo, amb, monkeypatch):
    rodar(modo="completo")
    saida = json.loads((amb / "funcionarios_matriculas.json").read_text(encoding="utf-8"))
    for reg_ in saida:
        if reg_["nome"] == "ANA CLARA DE SOUZA LIMA":
            reg_["vinculos_servidores"][0]["numcad"] = "9999"                           # a matrícula gravada não é mais a do RH
    (amb / "funcionarios_matriculas.json").write_text(json.dumps(saida), encoding="utf-8")
    rodar(modo="homonimos")
    assert _saida(amb)["ANA CLARA DE SOUZA LIMA"]["na_escola"] is None


def test_homonimos_duas_matriculas_na_escola_ficam_as_duas(fluxo, amb, monkeypatch):
    rh_novo = [rh("1004", "CARLA DIAS MELO", titcar="PROFESSOR 20H", datadm="01/03/2010"),
               rh("1005", "CARLA DIAS MELO", titcar="PROFESSOR 20H", datadm="15/08/2018")]
    monkeypatch.setattr(fv, "obter_servidores_rh", lambda forcar=False, session=None: rh_novo)
    monkeypatch.setattr(fv, "consultar_holerite", lambda s, m, mes: hol("ESCOLA JUDITH MACEDO SILVEIRA"))
    r = rodar(modo="homonimos")
    assert r["duas_matriculas_na_escola"] == 1 and r["desempatados"] == 0 and r["sem_decisao"] == 0
    carla = _saida(amb)["CARLA DIAS MELO"]
    assert [v["numcad"] for v in carla["vinculos_servidores"]] == ["1004", "1005"] and carla["multiplas_matriculas"] is True
    assert carla["revisar"] == [] and carla["na_escola"] is True and "dois concursos" in carla["observacao_vinculo"]


def test_homonimos_so_nome_ou_cpf_verifica_so_essa_pessoa(fluxo, amb):
    r = rodar(modo="homonimos", so_nome="ana clara")
    assert [m for m, _ in fluxo["holerites"]] == ["1001"] and r["verificados"] == 1
    fluxo["holerites"].clear()
    (amb / "cache_holerites.json").unlink()
    rodar(modo="homonimos", so_nome="222.222.222-22")                                   # CPF da Carla, com máscara
    assert sorted(m for m, _ in fluxo["holerites"]) == ["1004", "1005"]
    with pytest.raises(ValueError, match="bate com"):
        rodar(modo="homonimos", so_nome="fulano inexistente")


def test_homonimos_sem_ninguem_com_duas_matriculas_nao_consulta_nada(fluxo, amb, monkeypatch, capsys):
    monkeypatch.setattr(fv, "obter_servidores_rh", lambda forcar=False, session=None: [x for x in RH_SERVIDORES if x["numcad"] != "1005"])
    r = rodar(modo="homonimos")
    assert fluxo["holerites"] == [] and r["verificados"] == 0 and r["comprovou"] is False
    assert "nada a verificar" in capsys.readouterr().out


def test_homonimos_respeita_ajuste_manual(fluxo, amb):
    fv.arquivo_ajustes().write_text(json.dumps({"22222222222": {"na_escola": True, "observacao": "conferido na secretaria"}}), encoding="utf-8")
    carla = rodar(modo="homonimos") and _saida(amb)["CARLA DIAS MELO"]
    assert carla["ajuste_manual"] is True and carla["comprovacao"] == "manual" and carla["revisar"] == []


# modos na tela, na web e na CLI

def test_campos_do_formulario_por_modo(web):
    extras = {e["nome"]: e for e in reg.obter("vinculos").extras()}
    assert [o["valor"] for o in extras["modo"]["opcoes"]] == ["completo", "sere", "vincular", "homonimos"] and extras["modo"]["padrao"] == "completo"
    assert extras["so_nome"]["visivelSe"]["valor"] == "homonimos"
    assert extras["pular_holerite"]["visivelSe"]["valor"] == "completo"
    assert set(extras["mes"]["visivelSe"]["valor"].split("|")) == {"homonimos", "completo"}
    assert set(extras["forcar_coleta"]["visivelSe"]["valor"].split("|")) == {"vincular", "homonimos", "completo"}
    assert all(e["visivelSe"]["campo"] == extras["modo"]["id"] for n, e in extras.items() if n != "modo")


def test_plano_por_modo(web):
    s = reg.obter("vinculos")
    assert s.planejar(Opcoes(), {"modo": "homonimos", "so_nome": "  Carla  ", "mes": "08-2026"}, {}, {}).kwargs == {
        "modo": "homonimos", "mes": "08-2026", "forcar_coleta": False, "atualizar_sere": False, "so_nome": "Carla"}
    assert s.planejar(Opcoes(), {"modo": "sere"}, {}, {}).kwargs["modo"] == "sere"
    assert s.planejar(Opcoes(), {}, {}, {}).kwargs["modo"] == "completo"
    assert s.planejar(Opcoes(), {"modo": "completo", "pular_holerite": True}, {}, {}).kwargs["modo"] == "vincular"
    with pytest.raises(ValueError, match="desconhecido"):
        s.planejar(Opcoes(), {"modo": "xyz"}, {}, {})


def test_executar_pela_web_em_cada_modo(web, amb):
    assert web.post("/web/api/automacoes/vinculos/executar", json={"modo": "vincular"}).status_code == 200
    assert _esperar(web)["status"] == "concluido" and rotas._EXECUCOES["vinculos"]["resultado"]["modo"] == "vincular"
    assert web.post("/web/api/automacoes/vinculos/executar", json={"modo": "homonimos", "mes": "09-2026"}).status_code == 200
    s = _esperar(web)
    assert s["status"] == "concluido" and rotas._EXECUCOES["vinculos"]["resultado"]["verificados"] == 1
    assert any("Verificação de homônimos" in linha for linha in s["logs"])
    r = web.post("/web/api/automacoes/vinculos/executar", json={"modo": "xyz"})
    assert r.status_code == 400 and "desconhecido" in r.get_json()["mensagem"]


def test_cli_modo(web, capsys):
    from src.comum import cli
    assert cli.main(["vinculos", "--modo", "homonimos", "--so-nome", "Carla", "--mes", "09-2026", "--simular"]) == 0
    assert "modo='homonimos'" in capsys.readouterr().out
    assert cli.main(["vinculos", "--modo", "xyz", "--simular"]) == 2


def test_tela_mostra_cargo_admissao_e_duas_matriculas(web, amb, monkeypatch):
    rh_novo = [rh("1004", "CARLA DIAS MELO", titcar="PROFESSOR 20H", datadm="01/03/2010"),
               rh("1005", "CARLA DIAS MELO", titcar="PROFESSOR 20H", datadm="15/08/2018"),
               rh("1001", "ANA CLARA DE SOUZA LIMA", titcar="PROFESSOR 40H", datadm="01/02/2010")]
    monkeypatch.setattr(fv, "obter_servidores_rh", lambda forcar=False, session=None: rh_novo)
    monkeypatch.setattr(fv, "consultar_holerite", lambda s, m, mes: hol("ESCOLA JUDITH MACEDO SILVEIRA"))
    (amb / "funcionarios_completo.json").write_text("[]", encoding="utf-8")
    web.post("/web/api/automacoes/vinculos/executar", json={"mes": "09-2026"})
    _esperar(web)
    d = web.get("/web/api/funcionarios/lista").get_json()
    por_nome = {f["nome"]: f for f in d["funcionarios"]}
    carla, ana = por_nome["CARLA DIAS MELO"], por_nome["ANA CLARA DE SOUZA LIMA"]
    assert carla["multiplas_matriculas"] is True and ana["multiplas_matriculas"] is False
    assert carla["detalhe"]["matriculas"] == ("1004 — PROFESSOR 20H — admissão 01/03/2010 — ESCOLA JUDITH MACEDO SILVEIRA | "
                                              "1005 — PROFESSOR 20H — admissão 15/08/2018 — ESCOLA JUDITH MACEDO SILVEIRA")
    assert "dois concursos" in carla["detalhe"]["observacao_vinculo"]
    assert (ana["detalhe"]["cargo_prefeitura"], ana["detalhe"]["data_admissao"]) == ("PROFESSOR 40H", "01/02/2010")
    assert "matriculas" not in ana["detalhe"]
    assert {c["label"]: c["valor"] for c in d["cartoes"]}["Duas matrículas"] == 1


def test_tela_tem_o_filtro_de_duas_matriculas_e_os_campos():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    html = (raiz / "src/web/templates/partials/funcionarios_cards.html").read_text(encoding="utf-8")
    assert 'value="multiplas"' in html and '"multiplas"' in js and "f.multiplas_matriculas" in js
    assert all(k in js for k in ("cargo_prefeitura", "data_admissao", "Matrículas nesta escola", 'valor.split("|")'))


def test_toda_automacao_da_lista_tem_item_no_menu_lateral():
    """O submenu de Automações é fixo no base.html: automação nova sem item ali some do menu (aconteceu com funcionários e vínculos)."""
    import re
    html = (Path(__file__).resolve().parent.parent / "src/web/templates/base.html").read_text(encoding="utf-8")
    no_menu = set(re.findall(r'nav-subitem" data-view="automacoes" data-auto="([a-z_]+)"', html))
    na_lista = {a["chave"] for a in rotas.AUTOMACOES_DISPONIVEIS}
    assert na_lista - no_menu == set()
    assert {"funcionarios", "vinculos"} <= no_menu

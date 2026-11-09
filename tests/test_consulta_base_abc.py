"""consulta_base_abc: busca por nome + data de nascimento + nome da mãe (ou CGM) e o registro em buscas_base.json."""
import asyncio
import json
from datetime import date

import pytest

from src.automacao import consulta_base_abc as cb
from src.comum import paths
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes

D = date


# ───────────── entrada ─────────────

@pytest.mark.parametrize("linha,nome,nasc,cgm,mae", [
    ("Claudio Alex Mendes de Souza 12/03/2015", "Claudio Alex Mendes de Souza", D(2015, 3, 12), "", ""),
    ("Claudio Alex Mendes de Souza, 12-03-2015", "Claudio Alex Mendes de Souza", D(2015, 3, 12), "", ""),
    ("Claudio Alex Souza  nasc.: 1/3/2015", "Claudio Alex Souza", D(2015, 3, 1), "", ""),
    ("12/03/2015 Claudio Alex Souza", "Claudio Alex Souza", D(2015, 3, 12), "", ""),
    ("3) Maria Silva Lima 03.11.2014", "Maria Silva Lima", D(2014, 11, 3), "", ""),
    ("Claudio Alex Souza 12/03/2015 mãe: Maria Aparecida de Souza", "Claudio Alex Souza", D(2015, 3, 12), "", "Maria Aparecida de Souza"),
    ("Claudio Alex Souza mae Maria Aparecida 12/03/2015", "Claudio Alex Souza", D(2015, 3, 12), "", "Maria Aparecida 12/03/2015".replace(" 12/03/2015", "")),
    ("Claudio Alex Souza; 12/03/2015; Maria Aparecida de Souza", "Claudio Alex Souza", D(2015, 3, 12), "", "Maria Aparecida de Souza"),
    ("Claudio Alex Souza | Maria Aparecida | 12/03/2015", "Claudio Alex Souza", D(2015, 3, 12), "", "Maria Aparecida"),
    ("Claudio Alex Souza\t12/03/2015\tNome da mãe: Maria Aparecida", "Claudio Alex Souza", D(2015, 3, 12), "", "Maria Aparecida"),
    ("Claudio Alex Souza mãe: Maria Aparecida", "Claudio Alex Souza", None, "", "Maria Aparecida"),     # a mãe basta para separar
    ("Nome: Ana Clara Lima | Data de nascimento: 05/05/2016", "Ana Clara Lima", D(2016, 5, 5), "", ""),
    ("1025059227", "", None, "1025059227", ""),
    ("CGM 1025059227", "", None, "1025059227", ""),
    ("1025059227 Joao Pedro 03/11/2014", "Joao Pedro", D(2014, 11, 3), "1025059227", ""),
])
def test_interpretar_linha(linha, nome, nasc, cgm, mae):
    c = cb.interpretar_linha(linha)
    assert (c.nome, c.nascimento, c.cgm, c.mae) == (nome, nasc, cgm, mae)


@pytest.mark.parametrize("linha,trecho", [
    ("", "vazia"),
    ("Claudio 12/03/2015", "sobrenome"),
    ("Claudio Alex Souza", "data de nascimento"),
    ("Claudio Alex Souza 31/02/2015", "inválida"),
    ("Claudio Alex Souza 12/03/15", "data de nascimento"),
])
def test_linha_invalida_diz_o_motivo(linha, trecho):
    with pytest.raises(ValueError, match=trecho):
        cb.interpretar_linha(linha)


def test_interpretar_texto_separa_erros_e_tira_repetidos():
    consultas, erros = cb.interpretar_texto("Ana Clara Lima 05/05/2016\n\nana  clara lima 05/05/2016\n1025059227\nFulano\n")
    assert [c.rotulo for c in consultas] == ["Ana Clara Lima 05/05/2016", "1025059227"]       # a repetida (outro espaçamento/caixa) saiu
    assert len(erros) == 1 and erros[0][0] == "Fulano"


def test_mesmo_nome_e_data_com_maes_diferentes_sao_pedidos_diferentes():
    consultas, _ = cb.interpretar_texto("Maria Silva Lima 03/11/2014 mãe: Ana\nMaria Silva Lima 03/11/2014 mãe: Beatriz")
    assert len(consultas) == 2


# ───────────── nome ─────────────

@pytest.mark.parametrize("busca,candidato,esperado", [
    ("Claudio Alex", "CLAUDIO ALEX MENDES DE SOUZA", True),
    ("claudio souza", "CLAUDIO ALEX MENDES DE SOUZA", True),
    ("Clau Alex", "CLÁUDIO ALEX MENDES", True),                 # começo de palavra, sem acento
    ("Claudio Alexandre", "CLAUDIO ALEX MENDES", False),
    ("Joao Pedro", "JOAO PAULO PEDROSO", True),                  # "PEDRO" é começo de "PEDROSO": confere; a data e a mãe separam os dois
    ("Joao Paulo Silva", "JOAO PAULO PEDROSO", False),
    ("", "CLAUDIO", False),
])
def test_nome_confere(busca, candidato, esperado):
    assert cb.nome_confere(busca, candidato) is esperado


def _cand(i, nome, nasc=None, cgm=""):
    return cb.candidato_da_linha(i, [cgm, nome] + ([nasc] if nasc else []))


def test_candidato_da_linha_acha_data_e_cgm():
    c = cb.candidato_da_linha(0, ["1025059227", "CLAUDIO ALEX", "12/03/2015", "ESCOLA X"])
    assert c.cgm == "1025059227" and c.nascimento == D(2015, 3, 12)


def test_tabela_descarta_so_o_que_prova_ser_outro():
    cs = [_cand(0, "CLAUDIO ALEX SOUZA", "01/01/2014"), _cand(1, "CLAUDIO ALEX SOUZA", "12/03/2015"),
          _cand(2, "CLAUDIO ALEX SOUZA"), _cand(3, "OUTRO NOME", "12/03/2015")]
    ficam, fora = cb.filtrar_candidatos(cs, cb.Consulta(nome="Claudio Alex Souza", nascimento=D(2015, 3, 12)))
    assert [c.indice for c in ficam] == [1, 2] and [c.indice for c in fora] == [0]       # sem data na tabela: confere no cadastro


@pytest.mark.parametrize("cad,esperado", [
    ({"nome": "CLAUDIO ALEX SOUZA", "nascimento": D(2015, 3, 12), "mae": "MARIA APARECIDA DE SOUZA"}, True),
    ({"nome": "CLAUDIO ALEX SOUZA", "nascimento": D(2014, 1, 1), "mae": "MARIA APARECIDA DE SOUZA"}, False),
    ({"nome": "CLAUDIO ALEX SOUZA", "nascimento": D(2015, 3, 12), "mae": "ANA PAULA LIMA"}, False),
    ({"nome": "CLAUDIO ALEX SOUZA", "nascimento": D(2015, 3, 12), "mae": ""}, True),         # o cadastro não mostra a mãe: não derruba
    ({"nome": "CLAUDIO ALEX SOUZA", "nascimento": None, "mae": "MARIA APARECIDA DE SOUZA"}, True),
    ({"nome": "OUTRO ALUNO", "nascimento": D(2015, 3, 12), "mae": "MARIA APARECIDA DE SOUZA"}, False),
])
def test_cadastro_confere(cad, esperado):
    c = cb.Consulta(nome="Claudio Alex", nascimento=D(2015, 3, 12), mae="Maria Aparecida")
    assert cb.cadastro_confere(c, cad) is esperado


def test_variantes_de_busca_do_mais_especifico_ao_mais_aberto():
    assert cb.variantes_de_busca("Cláudio Alex Mendes de Souza") == [
        "Cláudio Alex Mendes de Souza", "Cláudio Souza", "Cláudio Alex", "CLAUDIO ALEX MENDES DE SOUZA"]
    assert cb.variantes_de_busca("Ana Lima") == ["Ana Lima"]


# ───────────── o registro ─────────────

HIST = [{"ano": 2024, "municipio": "CWB", "escola": "ESC B", "curso": "EF", "serie": "3º ano", "resultado": "Aprovado"},
        {"ano": 2026, "municipio": "PG", "escola": "ESC ATUAL", "curso": "EF", "serie": "5º ano", "resultado": ""},
        {"ano": 2025, "municipio": "PG", "escola": "ESC A", "curso": "EF", "serie": "4º ano", "resultado": "Aprovado"}]
CAD = {"nome": "CLAUDIO ALEX MENDES DE SOUZA", "cgm": "1025059227", "nascimento": D(2015, 3, 12), "mae": "MARIA APARECIDA DE SOUZA"}


def test_registro_encontrado_tem_os_campos_pedidos():
    c = cb.Consulta(nome="Claudio Alex", nascimento=D(2015, 3, 12), mae="Maria Aparecida")
    r = cb.montar_registro(c, cb.Resultado("encontrado", CAD), HIST)
    assert list(r)[:7] == ["data_busca", "nome", "possui_cgm", "cgm", "data_nascimento", "nome_mae", "escolas"]
    assert (r["nome"], r["possui_cgm"], r["cgm"], r["data_nascimento"], r["nome_mae"]) == (
        "CLAUDIO ALEX MENDES DE SOUZA", True, "1025059227", "12/03/2015", "MARIA APARECIDA DE SOUZA")
    assert r["escolas"] == {"1": {"ano": 2026, "escola": "ESC ATUAL", "serie": "5º ano"},
                            "2": {"ano": 2025, "escola": "ESC A", "serie": "4º ano"},
                            "3": {"ano": 2024, "escola": "ESC B", "serie": "3º ano"}}
    assert r["situacao"] == "encontrado" and r["pedido"]["nome"] == "Claudio Alex"


def test_registro_de_quem_nao_esta_na_base_guarda_o_pedido_sem_cgm_e_sem_escolas():
    c = cb.Consulta(nome="Fulano de Tal", nascimento=D(2015, 3, 12), mae="Beltrana")
    parecido = {"nome": "FULANO DE TAL", "cgm": "9", "data_nascimento": "01/01/2014", "nome_mae": ""}
    r = cb.montar_registro(c, cb.Resultado("nao_encontrado", motivo="há alunos com esse nome, mas com outra data", parecidos=[parecido]))
    assert (r["nome"], r["possui_cgm"], r["cgm"], r["data_nascimento"], r["nome_mae"], r["escolas"]) == (
        "Fulano de Tal", False, "", "12/03/2015", "Beltrana", {})
    assert r["situacao"] == "nao_encontrado" and r["encontrados_parecidos"] == [parecido] and "outra data" in r["observacao"]


def test_aluno_sem_cgm_na_base_tambem_e_registrado_como_sem_cgm():
    c = cb.Consulta(nome="Fulano de Tal", nascimento=D(2015, 3, 12))
    r = cb.montar_registro(c, cb.Resultado("encontrado", {"nome": "FULANO DE TAL", "cgm": "", "nascimento": D(2015, 3, 12), "mae": ""}), HIST)
    assert r["possui_cgm"] is False and r["cgm"] == "" and len(r["escolas"]) == 3


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path / "dados" / "2026")
    (tmp_path / "dados" / "2026").mkdir(parents=True)
    return tmp_path


def _lido():
    return json.loads(cb.arquivo_consolidado().read_text(encoding="utf-8"))


def test_arquivo_e_buscas_base_json_no_ano_atual(amb):
    assert cb.arquivo_consolidado() == amb / "dados" / "2026" / "buscas_base.json"


def test_consolidado_troca_pelo_cgm_e_sem_cgm_pelo_pedido(amb):
    def reg_(nome, cgm="", nasc="", mae="", sit="encontrado"):
        return {"nome": nome, "cgm": cgm, "situacao": sit,
                "pedido": {"nome": nome, "data_nascimento": nasc, "nome_mae": mae, "cgm": ""}}
    cb.atualizar_consolidado(reg_("ANA LIMA", "1"))
    cb.atualizar_consolidado({**reg_("ANA CLARA LIMA", "1"), "x": 2})                               # mesmo CGM: troca
    cb.atualizar_consolidado(reg_("Beto Souza", nasc="01/01/2015", mae="Carla", sit="nao_encontrado"))
    cb.atualizar_consolidado({**reg_("BETO  souza", nasc="01/01/2015", mae="CARLA", sit="nao_encontrado"), "x": 1})   # mesmo pedido: troca
    cb.atualizar_consolidado(reg_("Beto Souza", nasc="01/01/2015", mae="Dora", sit="nao_encontrado"))                 # outra mãe: outro aluno
    assert [r["nome"] for r in _lido()] == ["ANA CLARA LIMA", "BETO  souza", "Beto Souza"]


def test_registro_que_achou_nao_e_trocado_por_busca_que_nao_achou(amb):
    achou = {"nome": "ANA", "cgm": "1", "situacao": "encontrado", "pedido": {"nome": "Ana Lima", "data_nascimento": "05/05/2016", "nome_mae": "", "cgm": ""}}
    nao = {"nome": "Ana Lima", "cgm": "", "situacao": "nao_encontrado", "pedido": achou["pedido"]}
    cb.atualizar_consolidado(achou)
    arquivo, gravou = cb.atualizar_consolidado(nao)
    assert gravou is False and [r["situacao"] for r in _lido()] == ["encontrado"]
    cb.atualizar_consolidado({**achou, "nome": "ANA ATUALIZADA"})                                  # achar de novo atualiza
    assert [r["nome"] for r in _lido()] == ["ANA ATUALIZADA"]


def test_arquivo_de_entrada_do_script_antigo(tmp_path):
    arq = tmp_path / "transferidos-2025.json"
    arq.write_text(json.dumps({"alunos": [{"CGM": "1025059227", "Nome": "ANA"}, {"CGM": "1025059227"}, {"Nome": "SEM CGM"},
                                          {"Nome": "BETO SOUZA", "Nascimento": "01/01/2015", "Mae": "CARLA SOUZA"}]}), encoding="utf-8")
    cs = cb.consultas_do_arquivo(arq)
    assert [(c.cgm, c.nome, c.nascimento, c.mae) for c in cs] == [
        ("1025059227", "ANA", None, ""), ("1025059227", "", None, ""), ("", "BETO SOUZA", D(2015, 1, 1), "CARLA SOUZA")]


# ───────────── fluxo com navegador de mentira ─────────────

class NavFalso:
    """Faz de conta a Base ABC. `base`: alunos {cgm, nome, nasc, mae, historico}; `mostra_data`: a tabela traz a data?"""

    def __init__(self, base, mostra_data=True):
        self.base, self.mostra_data = base, mostra_data
        self.resultado, self.aberto, self.pesquisas, self.fechados = [], None, [], 0

    async def pesquisar(self, *, cgm, nome, nascimento, mae=""):
        self.pesquisas.append({"cgm": cgm, "nome": nome, "nascimento": nascimento, "mae": mae})
        if cgm:
            self.resultado = [a for a in self.base if a["cgm"] == cgm]
        else:
            self.resultado = [a for a in self.base if cb.nome_confere(nome, a["nome"])]
        return bool(self.resultado)

    async def candidatos(self):
        return [cb.candidato_da_linha(i, [a["cgm"], a["nome"]] + ([cb.formatar_data(a["nasc"])] if self.mostra_data else []))
                for i, a in enumerate(self.resultado)]

    async def abrir(self, candidato):
        self.aberto = self.resultado[candidato.indice]

    async def cadastro(self):
        return {"nome": self.aberto["nome"], "cgm": self.aberto["cgm"], "nascimento": self.aberto["nasc"], "mae": self.aberto["mae"]}

    async def historico(self):
        return self.aberto["historico"]

    async def fechar(self):
        self.aberto = None
        self.fechados += 1


BASE = [{"cgm": "1025059227", "nome": "CLAUDIO ALEX MENDES DE SOUZA", "nasc": D(2015, 3, 12), "mae": "MARIA APARECIDA DE SOUZA", "historico": HIST},
        {"cgm": "1025059228", "nome": "CLAUDIO ALEX MENDES DE SOUZA", "nasc": D(2012, 7, 1), "mae": "ROSA MENDES", "historico": []},
        {"cgm": "1025059300", "nome": "MARIA SILVA LIMA", "nasc": D(2014, 11, 3), "mae": "ANA PAULA LIMA", "historico": HIST},
        {"cgm": "1025059301", "nome": "MARIA SILVA LIMA", "nasc": D(2014, 11, 3), "mae": "BEATRIZ SILVA", "historico": HIST[:1]},
        {"cgm": "", "nome": "JOANA SEM CGM", "nasc": D(2013, 2, 2), "mae": "LUCIA", "historico": HIST[:2]}]


def _rodar(nav, *linhas):
    consultas, erros = cb.interpretar_texto("\n".join(linhas))
    assert not erros
    saida = []
    return asyncio.run(cb.consultar(nav, consultas, log=saida.append)), saida


def test_acha_pelo_nome_data_e_mae_e_registra_as_escolas(amb):
    nav = NavFalso(BASE)
    resumo, _ = _rodar(nav, "Claudio Alex Mendes de Souza 12/03/2015 mãe: Maria Aparecida")
    assert len(resumo.encontrados) == 1 and not (resumo.nao_encontrados or resumo.ambiguos or resumo.erros)
    [r] = _lido()
    assert (r["cgm"], r["possui_cgm"], r["nome_mae"], r["situacao"]) == ("1025059227", True, "MARIA APARECIDA DE SOUZA", "encontrado")
    assert r["escolas"]["1"] == {"ano": 2026, "escola": "ESC ATUAL", "serie": "5º ano"} and len(r["escolas"]) == 3
    assert nav.fechados >= 1 and nav.pesquisas[0]["mae"] == "Maria Aparecida"          # a mãe vai para o formulário também


def test_homonimos_com_a_mesma_data_sao_separados_pela_mae(amb):
    resumo, _ = _rodar(NavFalso(BASE), "Maria Silva Lima 03/11/2014 mãe: Beatriz")
    assert len(resumo.encontrados) == 1 and _lido()[0]["cgm"] == "1025059301"
    resumo, _ = _rodar(NavFalso(BASE), "Maria Silva Lima 03/11/2014 mãe: Ana Paula")
    assert sorted(r["cgm"] for r in _lido()) == ["1025059300", "1025059301"]


def test_homonimos_com_a_mesma_data_sem_mae_nao_escolhe_e_registra_os_candidatos(amb):
    resumo, _ = _rodar(NavFalso(BASE), "Maria Silva Lima 03/11/2014")
    assert not resumo.encontrados and len(resumo.ambiguos) == 1 and "nome da mãe" in resumo.ambiguos[0][1]
    [r] = _lido()
    assert r["situacao"] == "ambiguo" and r["possui_cgm"] is False and r["escolas"] == {}
    assert sorted(p["cgm"] for p in r["encontrados_parecidos"]) == ["1025059300", "1025059301"]
    assert sorted(p["nome_mae"] for p in r["encontrados_parecidos"]) == ["ANA PAULA LIMA", "BEATRIZ SILVA"]


def test_mesma_data_e_mesma_mae_continua_ambiguo(amb):
    base = [dict(BASE[2]), {**BASE[2], "cgm": "1025059999"}]
    resumo, _ = _rodar(NavFalso(base), "Maria Silva Lima 03/11/2014 mãe: Ana Paula Lima")
    assert len(resumo.ambiguos) == 1 and "mesmo nome, data de nascimento e mãe" in resumo.ambiguos[0][1]


def test_homonimo_so_com_mae_sem_data(amb):
    resumo, _ = _rodar(NavFalso(BASE), "Claudio Alex Mendes de Souza mãe: Rosa Mendes")
    assert _lido()[0]["cgm"] == "1025059228" and len(resumo.encontrados) == 1


def test_nao_estar_na_base_nao_e_erro_e_fica_registrado_com_o_que_foi_achado(amb):
    resumo, saida = _rodar(NavFalso(BASE), "Claudio Alex Mendes de Souza 01/01/2000 mãe: Maria Aparecida")
    assert resumo.nao_encontrados and not resumo.erros and not resumo.encontrados
    [r] = _lido()
    assert (r["situacao"], r["possui_cgm"], r["cgm"], r["escolas"]) == ("nao_encontrado", False, "", {})
    assert r["data_nascimento"] == "01/01/2000" and r["nome_mae"] == "Maria Aparecida"
    assert {p["cgm"] for p in r["encontrados_parecidos"]} == {"1025059227", "1025059228"}          # o que a base mostrou de parecido
    assert any("registrado em buscas_base.json" in l for l in saida)


def test_nome_que_nem_existe_tambem_e_registrado(amb):
    resumo, _ = _rodar(NavFalso(BASE), "Zacarias Nunca Existiu 01/01/2000")
    assert resumo.nao_encontrados[0][1] == "nenhum aluno com esse nome" and _lido()[0]["situacao"] == "nao_encontrado"


def test_data_certa_mas_mae_errada_nao_serve(amb):
    resumo, _ = _rodar(NavFalso(BASE), "Claudio Alex Mendes de Souza 12/03/2015 mãe: Fulana Qualquer")
    assert len(resumo.nao_encontrados) == 1 and "outra mãe" in resumo.nao_encontrados[0][1]
    assert _lido()[0]["situacao"] == "nao_encontrado"


def test_aluno_sem_cgm_na_base_e_registrado_com_possui_cgm_falso(amb):
    resumo, _ = _rodar(NavFalso(BASE), "Joana Sem Cgm 02/02/2013")
    [r] = _lido()
    assert r["situacao"] == "encontrado" and r["possui_cgm"] is False and r["cgm"] == "" and len(r["escolas"]) == 2


def test_tabela_sem_data_abre_o_cadastro_para_conferir(amb):
    nav = NavFalso(BASE, mostra_data=False)
    _rodar(nav, "Claudio Alex Mendes de Souza 12/03/2015")
    assert _lido()[0]["cgm"] == "1025059227" and nav.fechados >= 2                  # abriu os candidatos para conferir e depois o escolhido


def test_busca_por_cgm_como_no_script_antigo(amb):
    resumo, _ = _rodar(NavFalso(BASE), "1025059300")
    assert len(resumo.encontrados) == 1 and _lido()[0]["nome"] == "MARIA SILVA LIMA" and _lido()[0]["pedido"]["cgm"] == "1025059300"


def test_cgm_de_outro_aluno_e_registrado_como_nao_encontrado(amb):
    resumo, _ = _rodar(NavFalso(BASE), "1025059300 Claudio Alex 12/03/2015")
    [r] = _lido()
    assert r["situacao"] == "nao_encontrado" and "é de outro aluno" in r["observacao"] and r["encontrados_parecidos"][0]["cgm"] == "1025059300"


def test_cgm_que_nao_existe(amb):
    resumo, _ = _rodar(NavFalso(BASE), "9999999999")
    assert resumo.nao_encontrados and _lido()[0]["situacao"] == "nao_encontrado"


def test_tenta_variantes_do_nome_e_por_ultimo_sem_os_filtros(amb):
    class NavSoSemFiltro(NavFalso):
        async def pesquisar(self, *, cgm, nome, nascimento, mae=""):
            # o formulário só acha quando data e mãe NÃO são enviados (como se a mãe digitada fosse escrita diferente)
            if nascimento is not None or mae:
                self.pesquisas.append({"cgm": cgm, "nome": nome, "nascimento": nascimento, "mae": mae})
                return False
            return await super().pesquisar(cgm=cgm, nome=nome, nascimento=nascimento, mae=mae)
    nav = NavSoSemFiltro(BASE)
    resumo, _ = _rodar(nav, "Claudio Alex Mendes de Souza 12/03/2015 mãe: Maria Aparecida")
    assert len(resumo.encontrados) == 1 and _lido()[0]["cgm"] == "1025059227"
    filtradas = [p for p in nav.pesquisas if p["nascimento"] is not None]
    assert [p["nome"] for p in filtradas] == ["Claudio Alex Mendes de Souza", "Claudio Souza", "Claudio Alex"]     # variantes, com data e mãe
    ultima = nav.pesquisas[-1]
    assert (ultima["nome"], ultima["nascimento"], ultima["mae"]) == ("Claudio Alex Mendes de Souza", None, "")   # por último, sem os filtros


def test_erro_tecnico_e_registrado_e_os_outros_seguem(amb):
    class NavQuebra(NavFalso):
        async def historico(self):
            if self.aberto["cgm"] == "1025059227":
                raise RuntimeError("tabela não carregou")
            return await super().historico()
    resumo, _ = _rodar(NavQuebra(BASE), "1025059227", "1025059300")
    assert [r[0] for r in resumo.erros] == ["1025059227"] and len(resumo.encontrados) == 1
    assert {r["pedido"]["cgm"]: r["situacao"] for r in _lido()} == {"1025059227": "erro", "1025059300": "encontrado"}


def test_busca_que_nao_acha_nao_apaga_o_que_ja_foi_achado(amb):
    _rodar(NavFalso(BASE), "1025059300")
    resumo, _ = _rodar(NavFalso([]), "1025059300")                          # a base "some": nao_encontrado
    assert resumo.mantidos == ["1025059300"] and [r["situacao"] for r in _lido()] == ["encontrado"]


def test_formulario_desconhecido_para_tudo(amb):
    class NavSemCampo(NavFalso):
        async def pesquisar(self, **k):
            raise cb.FormularioDesconhecido("campo Nome não encontrado. Campos: a|b|text")
    consultas, _ = cb.interpretar_texto("Claudio Alex Souza 12/03/2015\nAna Lima Souza 01/01/2015")
    with pytest.raises(cb.FormularioDesconhecido, match="Campos"):
        asyncio.run(cb.consultar(NavSemCampo(BASE), consultas, log=lambda *_: None))
    assert not cb.arquivo_consolidado().exists()


def test_sessao_expirada_entra_de_novo(amb):
    logins = []

    async def valida():
        return bool(logins)                      # a 1ª checagem diz que expirou; depois de entrar de novo, vale

    async def refaz():
        logins.append(1)
    consultas, _ = cb.interpretar_texto("1025059227\n1025059300")
    resumo = asyncio.run(cb.consultar(NavFalso(BASE), consultas, sessao_valida=valida, refazer_sessao=refaz, log=lambda *_: None))
    assert logins == [1] and len(resumo.encontrados) == 2


def test_via_login_com_sessao_de_mentira(amb, monkeypatch):
    from contextlib import asynccontextmanager

    class NavComSessao(NavFalso):
        def __init__(self, page, log):
            super().__init__(BASE)

        async def sessao_valida(self):
            return True

    @asynccontextmanager
    async def sessao(mostrar):
        yield object()
    monkeypatch.setattr(cb, "NavegadorBaseAbc", NavComSessao)
    consultas, _ = cb.interpretar_texto("1025059300\nZacarias Nunca Existiu 01/01/2000")
    r = asyncio.run(cb.consultar_base_abc_via_login(consultas, sessao=sessao, log=lambda *_: None))
    assert len(r["encontrados"]) == 1 and len(r["nao_encontrados"]) == 1 and r["arquivo"].endswith("buscas_base.json")


def test_sem_alunos_e_erro():
    with pytest.raises(ValueError, match="Nenhum aluno"):
        asyncio.run(cb.consultar_base_abc_via_login([]))


# ───────────── registro / tela ─────────────

def test_registrada_com_o_campo_de_alunos(amb):
    s = reg.obter("base_abc")
    assert s is not None and set(s.recursos) == {"teste"}
    assert [e["nome"] for e in s.extras()] == ["alunos_texto", "pre_matricula", "mostrar_navegador"]
    assert [o["valor"] for o in s.extras()[1]["opcoes"]] == ["nao", "matriculados", "pendentes", "matriculados_e_pendentes", "todos"]
    assert "mãe" in s.extras()[0]["descricao"]


def test_plano_le_o_texto_da_tela(amb):
    plano = reg.obter("base_abc").planejar(Opcoes(), {"alunos_texto": "Ana Clara Lima 05/05/2016 mãe: Rita\n1025059227"}, {}, {})
    assert plano.tipo == "coroutine" and plano.funcao is cb.consultar_base_abc_via_login
    assert [c.rotulo for c in plano.kwargs["consultas"]] == ["Ana Clara Lima 05/05/2016 (mãe: Rita)", "1025059227"]
    teste = reg.obter("base_abc").planejar(Opcoes(modo_teste=True), {"alunos_texto": "1025059227\n1025059228"}, {}, {})
    assert len(teste.kwargs["consultas"]) == 1 and teste.kwargs["modo_teste"] is True


def test_texto_com_linha_ruim_explica_qual(amb):
    with pytest.raises(ValueError, match="Fulano Silva"):
        reg.obter("base_abc").validar_extras({"alunos_texto": "Ana Clara Lima 05/05/2016\nFulano Silva"})


def test_em_branco_usa_o_arquivo_do_ano_anterior_ou_explica(amb):
    with pytest.raises(ValueError, match="transferidos-2025.json"):
        reg.obter("base_abc").validar_extras({})
    (amb / "dados" / "2026" / "transferidos-2025.json").write_text(json.dumps({"alunos": [{"CGM": "1025059227", "Nome": "ANA"}]}), encoding="utf-8")
    reg.obter("base_abc").validar_extras({})
    assert len(reg.obter("base_abc").planejar(Opcoes(), {}, {}, {}).kwargs["consultas"]) == 1


# ───────────── lista vinda da pré-matrícula ─────────────

def _cad(nome, resp, situacao, cpf):
    return {"cpf": cpf, "tr_id": "T" + cpf, "nome_aluno": nome, "nome_responsavel": resp, "telefone": "(41) 99999-0000",
            "email": "pai@example.com", "escolas_escolhidas": {"turma": "1º Ano", "opcoes": [{"escola": "ESC", "situacao": situacao}]}}


PRE = {"cadastros": {
    "111": _cad("ANA CLARA LIMA", "RITA LIMA", "Matriculado", "111"),
    "222": _cad("BETO SOUZA", "CARLA SOUZA", None, "222"),
    "333": _cad("CARLA DIAS", "JOSE DIAS", "Cancelado. Motivo: desistiu", "333"),
    "444": _cad("SOMENOME", "X", "Matriculado", "444"),                                  # uma palavra só: homônimos demais
},
    "turmas_intencao": {"1º Ano": [
        {"nome": "DUDA ROCHA", "cpf": "555", "tr_id": "9", "situacao": ""},                # na fila, sem cadastro: entra só com o nome
        {"nome": "ANA CLARA LIMA", "cpf": "111", "tr_id": "T111", "situacao": "Matriculado"},   # já tem cadastro: não repete
        {"nome": "ZE SILVA", "cpf": "666", "situacao": "Matriculado"},                   # já foi chamado: não é pendente
        {"nome": "ANTIGO ALUNO", "cpf": "777", "substituido_por_nova_tentativa": True}]}}


def _nomes(cs):
    return [c.nome for c in cs]


@pytest.mark.parametrize("quais,esperado", [
    ("matriculados", ["ANA CLARA LIMA"]),
    ("pendentes", ["BETO SOUZA", "DUDA ROCHA"]),
    ("matriculados_e_pendentes", ["ANA CLARA LIMA", "BETO SOUZA", "DUDA ROCHA"]),
    ("todos", ["ANA CLARA LIMA", "BETO SOUZA", "CARLA DIAS", "DUDA ROCHA"]),
])
def test_consultas_da_pre_matricula_por_situacao(quais, esperado):
    assert _nomes(cb.consultas_da_pre_matricula(PRE, quais)) == esperado


def test_pre_matricula_leva_so_nome_e_responsavel_e_nada_de_cpf_ou_contato():
    [c] = cb.consultas_da_pre_matricula(PRE, "matriculados")
    assert (c.nome, c.responsavel, c.origem, c.mae, c.nascimento, c.cgm) == ("ANA CLARA LIMA", "RITA LIMA", "pre_matricula", "", None, "")
    texto = repr(c) + c.rotulo
    assert "111" not in texto and "99999" not in texto and "example.com" not in texto


def test_pre_matricula_opcao_invalida_e_dados_estranhos():
    with pytest.raises(ValueError, match="inválida"):
        cb.consultas_da_pre_matricula(PRE, "qualquer")
    assert cb.consultas_da_pre_matricula({}, "todos") == [] and cb.consultas_da_pre_matricula(None, "todos") == []


def test_le_o_pre_matricula_json_do_ano(amb):
    with pytest.raises(ValueError, match="pre_matricula.json"):
        cb.consultas_da_pre_matricula_arquivo("matriculados")
    arq = amb / "dados" / "2026" / "pre_matricula.json"
    arq.write_text(json.dumps(PRE), encoding="utf-8")
    assert _nomes(cb.consultas_da_pre_matricula_arquivo("matriculados")) == ["ANA CLARA LIMA"]
    arq.write_text("{ isso não é json", encoding="utf-8")
    with pytest.raises(ValueError, match="pre_matricula.json"):
        cb.consultas_da_pre_matricula_arquivo("matriculados")


def _pre(nome, resp):
    return cb.Consulta(nome=nome, responsavel=resp, origem="pre_matricula")


def _rodar_consultas(nav, *consultas):
    return asyncio.run(cb.consultar(nav, list(consultas), log=lambda *_: None))


def test_homonimos_da_pre_matricula_o_responsavel_que_e_a_mae_desempata(amb):
    resumo = _rodar_consultas(NavFalso(BASE), _pre("Maria Silva Lima", "Beatriz Silva"))
    [r] = _lido()
    assert len(resumo.encontrados) == 1 and r["cgm"] == "1025059301"
    assert r["conferido_por"] == "nome + responsável (= mãe)" and "2 homônimos" in r["observacao"]
    assert [p["cgm"] for p in r["encontrados_parecidos"]] == ["1025059300"]                # o outro fica registrado
    assert r["pedido"]["origem"] == "pre_matricula" and r["pedido"]["responsavel"] == "Beatriz Silva"


def test_responsavel_que_nao_e_a_mae_nao_desempata_e_fica_ambiguo(amb):
    resumo = _rodar_consultas(NavFalso(BASE), _pre("Maria Silva Lima", "Carlos Lima"))        # pode ser o pai: não prova nada
    [r] = _lido()
    assert len(resumo.ambiguos) == 1 and r["situacao"] == "ambiguo" and r["conferido_por"] == ""
    assert sorted(p["nome_mae"] for p in r["encontrados_parecidos"]) == ["ANA PAULA LIMA", "BEATRIZ SILVA"]


def test_responsavel_nunca_derruba_um_aluno_unico(amb):
    _rodar_consultas(NavFalso(BASE), _pre("Joana Sem Cgm", "Pedro Souza"))                   # a mãe do cadastro é LUCIA: pode ser o pai
    [r] = _lido()
    assert r["situacao"] == "encontrado" and r["conferido_por"] == "só o nome"


def test_unico_com_responsavel_igual_a_mae_diz_que_foi_confirmado_por_ele(amb):
    _rodar_consultas(NavFalso(BASE), _pre("Joana Sem Cgm", "Lucia"))
    assert _lido()[0]["conferido_por"] == "nome + responsável (= mãe)"


def test_pre_matricula_fora_da_base_e_registrada_sem_erro(amb):
    resumo = _rodar_consultas(NavFalso(BASE), _pre("Zacarias Nunca Existiu", "Rita"))
    [r] = _lido()
    assert resumo.nao_encontrados and not resumo.erros and r["situacao"] == "nao_encontrado" and r["pedido"]["responsavel"] == "Rita"


def test_conferido_por_nas_outras_origens(amb):
    _rodar(NavFalso(BASE), "Claudio Alex Mendes de Souza 12/03/2015 mãe: Maria Aparecida", "Claudio Alex Mendes de Souza 01/07/2012", "1025059300")
    assert sorted(r["conferido_por"] for r in _lido()) == ["CGM", "nome + data de nascimento", "nome + data de nascimento + nome da mãe"]


def test_so_diferem_pelo_responsavel_nao_se_sobrescrevem_no_arquivo(amb):
    cb.atualizar_consolidado(cb.montar_registro(_pre("Maria Silva Lima", "Ana"), cb.Resultado("ambiguo", motivo="x")))
    cb.atualizar_consolidado(cb.montar_registro(_pre("Maria Silva Lima", "Beatriz"), cb.Resultado("ambiguo", motivo="x")))
    assert len(_lido()) == 2


def test_cadastro_sem_mae_nao_confirma_pelo_responsavel(amb):
    base = [{**BASE[4], "mae": ""}]
    _rodar_consultas(NavFalso(base), _pre("Joana Sem Cgm", "Lucia"))
    assert _lido()[0]["conferido_por"] == "só o nome"


# ───────────── pré-matrícula na tela ─────────────

def test_plano_com_pre_matricula_sozinha(amb):
    (amb / "dados" / "2026" / "pre_matricula.json").write_text(json.dumps(PRE), encoding="utf-8")
    plano = reg.obter("base_abc").planejar(Opcoes(), {"pre_matricula": "matriculados_e_pendentes"}, {}, {})
    assert _nomes(plano.kwargs["consultas"]) == ["ANA CLARA LIMA", "BETO SOUZA", "DUDA ROCHA"]
    assert plano.log_inicial.endswith("3 aluno(s) na Base ABC")


def test_plano_junta_o_texto_digitado_e_a_pre_matricula_sem_repetir(amb):
    (amb / "dados" / "2026" / "pre_matricula.json").write_text(json.dumps(PRE), encoding="utf-8")
    p = {"alunos_texto": "Ana Clara Lima 05/05/2016 mãe: Rita Lima\n1025059227", "pre_matricula": "matriculados"}
    cs = reg.obter("base_abc").planejar(Opcoes(), p, {}, {}).kwargs["consultas"]
    assert [c.origem for c in cs] == ["digitado", "digitado", "pre_matricula"]            # a digitada tem data/mãe: é outro pedido


def test_pre_matricula_escolhida_sem_arquivo_explica(amb):
    with pytest.raises(ValueError, match="pre_matricula.json"):
        reg.obter("base_abc").validar_extras({"pre_matricula": "matriculados"})


def test_pre_matricula_sem_ninguem_com_essa_situacao_explica(amb):
    (amb / "dados" / "2026" / "pre_matricula.json").write_text(json.dumps({"cadastros": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="nenhum aluno"):
        reg.obter("base_abc").validar_extras({"pre_matricula": "todos"})


def test_modo_teste_pega_so_o_primeiro_da_pre_matricula(amb):
    (amb / "dados" / "2026" / "pre_matricula.json").write_text(json.dumps(PRE), encoding="utf-8")
    plano = reg.obter("base_abc").planejar(Opcoes(modo_teste=True), {"pre_matricula": "todos"}, {}, {})
    assert len(plano.kwargs["consultas"]) == 1

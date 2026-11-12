"""Gerenciador Centralizado de Planilhas: cadastro, resolução, modelos, plataformas, integração com os módulos."""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile

import pytest

from src.comum import configuracao, paths
from src.comum import planilhas_gerenciador as gp
from src.comum import planilhas_modelos as pm
from src.comum import planilhas_plataformas as plat
from src.comum import planilhas_registro as pr
from src.comum.conversao_pdf import encontrar_soffice

ID1 = "1DPyBHxA3rz-u1nxgCN9f_XosZrqyiR8zuy4ACqeGpgE"
ID2 = "2DPyBHxA3rz-u1nxgCN9f_XosZrqyiR8zuy4ACqeGpgE"
T1, T2 = "1º Ano Integral A", "INFANTIL 4 Integral A"
TEM_SOFFICE = bool(encontrar_soffice())


def _al(n, nome, cgm, sit="Matriculado"):
    return {"N": str(n), "Nome": nome, "CGM": cgm, "Situação": sit, "Sexo": "Feminino", "Data Nasc.": "01/02/2019",
            "Data Matricula": "10/02/2026"}


TURMAS = {T1: [_al(2, "BETO", "1002"), _al(1, "ANA", "1001"), _al(3, "CARLA", "1003", "Transferido")],
          T2: [_al(1, "DUDA", "2001")]}


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path / "dados" / "2026")
    (tmp_path / "dados" / "2026").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    (tmp_path / "dados" / "2026" / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    return tmp_path


def _xlsx(tmp_path, nome="p.xlsx"):
    arquivo = tmp_path / nome
    arquivo.write_bytes(b"x")
    return str(arquivo)


# ───────────────────────── cadastro: plataformas, finalidades, unicidade ─────────────────────────

def test_cadastra_planilha_local_e_nao_duplica_pelo_caminho(amb):
    caminho = _xlsx(amb)
    item = pr.criar("Local", caminho=caminho, plataforma="xlsx", finalidade="listagem_alunos")
    assert item["plataforma"] == "xlsx" and item["caminho"] == caminho and item["planilha_id"] == "" and item["link"] == ""
    with pytest.raises(pr.PlanilhaDuplicada):
        pr.criar("Outra", caminho=caminho, plataforma="xlsx")


def test_mesmo_texto_em_plataformas_diferentes_nao_e_duplicado(amb):
    pr.criar("Google", ID1)
    pr.criar("Local", caminho=_xlsx(amb), plataforma="xlsx")
    assert pr.listar()["total"] == 2


def test_caminho_precisa_existir_e_ter_a_extensao_da_plataforma(amb):
    with pytest.raises(ValueError, match="Não encontrei o arquivo"):
        pr.criar("X", caminho=str(amb / "nao_existe.xlsx"), plataforma="xlsx")
    outro = amb / "a.csv"
    outro.write_text("x")
    with pytest.raises(ValueError, match=r"terminar em \.xlsx"):
        pr.criar("X", caminho=str(outro), plataforma="xlsx")
    with pytest.raises(ValueError, match="não um link"):
        pr.criar("X", link="https://exemplo.com/a.xlsx", plataforma="xlsx")
    with pytest.raises(ValueError, match="Plataforma desconhecida"):
        pr.criar("X", ID1, plataforma="numbers")


def test_turma_so_e_obrigatoria_nas_finalidades_por_turma(amb):
    assert pr.criar("A", ID1, finalidade="planilha_turmas")["turma"] == ""
    with pytest.raises(ValueError, match="Informe a turma"):
        pr.criar("B", ID2, finalidade="chamada")
    assert pr.criar("B", ID2, finalidade="chamada", turma=T1)["turma"] == T1


def test_uma_ativa_por_finalidade_e_turma_e_ativar_faz_a_troca(amb):
    a = pr.criar("Turmas A", ID1, finalidade="planilha_turmas")
    with pytest.raises(pr.PlanilhaEmConflito):
        pr.criar("Turmas B", ID2, finalidade="planilha_turmas")
    b = pr.criar("Turmas B", ID2, finalidade="planilha_turmas", status="inativa")
    pr.ativar(b["id"])
    assert pr.obter(a["id"])["status"] == "inativa" and pr.obter(b["id"])["status"] == "ativa"
    assert [i["id"] for i in pr.planilhas_da_finalidade("planilha_turmas")] == [b["id"]]


def test_substituir_planilha_sem_mexer_no_codigo(amb):
    item = pr.criar("Chamada 1A", ID1, finalidade="chamada", turma=T1)
    novo = pr.atualizar(item["id"], link=ID2)
    assert novo["planilha_id"] == ID2 and novo["referencia"] == ID2 and novo["id"] == item["id"]
    local = pr.atualizar(item["id"], plataforma="xlsx", caminho=_xlsx(amb), link="")
    assert local["plataforma"] == "xlsx" and local["planilha_id"] == ""


def test_natureza_externa_modelo_e_cadastrada(amb):
    ext = pr.criar("Pareceres", ID1, finalidade="parecer_infantil", turma=T2)
    comum = pr.criar("Lista", ID2, finalidade="listagem_alunos")
    assert ext["externa"] is True and ext["natureza"] == "externa" and comum["natureza"] == "cadastrada"
    with pytest.raises(ValueError, match="não nasce de modelo"):
        pr.criar("Y", "3" + ID1[1:], finalidade="parecer_infantil", turma=T2, modelo="chamada")


def test_registro_antigo_sem_campos_novos_continua_valendo(amb):
    arquivo = amb / "dados" / "planilhas" / "planilhas.json"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_text(json.dumps({"versao": 1, "proximo_id": 2, "itens": [
        {"id": 1, "nome": "Velha", "categoria": "Outras", "link": f"https://docs.google.com/spreadsheets/d/{ID1}/edit",
         "planilha_id": ID1, "observacao": "", "status": "ativa", "finalidade": "parecer_infantil", "turma": T2,
         "origem": "manual", "criado_em": "x", "atualizado_em": "x"}]}), encoding="utf-8")
    item = pr.obter(1)
    assert item["plataforma"] == "google_sheets" and item["referencia"] == ID1 and item["externa"] is True
    with pytest.raises(pr.PlanilhaDuplicada):
        pr.criar("Dup", ID1)


# ───────────────────────── gerenciador: resolver ─────────────────────────

def test_resolver_devolve_a_vigente_e_explica_quando_nao_ha(amb):
    with pytest.raises(gp.PlanilhaNaoCadastrada, match="Planilhas do Drive"):
        gp.resolver("planilha_turmas")
    pr.criar("Turmas", ID1, finalidade="planilha_turmas")
    ref = gp.resolver("planilha_turmas")
    assert ref.planilha_id == ID1 and ref.plataforma == "google_sheets" and not ref.local and ref.destino.endswith("/edit")


def test_resolver_por_turma_ambigua_e_escolha_do_usuario(amb):
    a = pr.criar("Chamada 1A", ID1, finalidade="chamada", turma=T1)
    b = pr.criar("Chamada INF", ID2, finalidade="chamada", turma=T2)
    assert gp.resolver("chamada", turma=T2).id == b["id"]
    with pytest.raises(gp.PlanilhaAmbigua, match="Escolha qual usar"):
        gp.resolver("chamada")
    assert gp.resolver("chamada", id_item=a["id"]).turma == T1
    with pytest.raises(ValueError, match="é da turma"):
        gp.resolver("chamada", turma=T2, id_item=a["id"])


def test_resolver_recusa_id_de_outra_finalidade_e_plataforma_nao_suportada(amb):
    chamada = pr.criar("Chamada", ID1, finalidade="chamada", turma=T1)
    with pytest.raises(ValueError, match="não está cadastrada para Pareceres do Infantil"):
        gp.resolver("parecer_infantil", id_item=chamada["id"])
    pr.criar("Local", caminho=_xlsx(amb), plataforma="xlsx", finalidade="imc")
    with pytest.raises(ValueError, match="só trabalha com Google Sheets"):
        gp.resolver("imc", plataformas=["google_sheets"])
    assert gp.resolver("imc", plataformas=["xlsx", "ods"]).local


def test_opcoes_para_formulario_lista_ativas_e_inativas(amb):
    pr.criar("Turmas A", ID1, finalidade="planilha_turmas")
    pr.criar("Turmas B", ID2, finalidade="planilha_turmas", status="inativa")
    textos = [o["texto"] for o in gp.opcoes_para_formulario("planilha_turmas")]
    assert len(textos) == 2 and "[inativa]" in textos[1] and "Google Sheets" in textos[0]
    assert len(gp.opcoes_para_formulario("planilha_turmas", incluir_inativas=False)) == 1


def test_migra_o_id_legado_da_configuracao(amb):
    configuracao._salvar_configuracao({**configuracao.carregar_configuracao(),
                                       "google_sheets": {"planilha_id": ID1, "mapa_abas": {"X": "Y"}}})
    ref = gp.resolver("planilha_turmas")
    assert ref.planilha_id == ID1
    bloco = configuracao.google_sheets_config()
    assert "planilha_id" not in bloco and bloco["mapa_abas"] == {"X": "Y"}            # o mapa de abas fica
    assert gp.migrar_planilha_legada() is None and pr.listar()["total"] == 1          # idempotente


def test_migracao_nao_atropela_a_planilha_ja_ativa(amb):
    pr.criar("Nova", ID2, finalidade="planilha_turmas")
    configuracao._salvar_configuracao({**configuracao.carregar_configuracao(), "google_sheets": {"planilha_id": ID1}})
    assert gp.resolver("planilha_turmas").planilha_id == ID2


def test_cadastrar_externa_so_para_finalidade_externa(amb):
    item = gp.cadastrar_externa("Pareceres 2026", "parecer_infantil", turma=T2, link=ID1)
    assert item["externa"] is True and item["categoria"] == "Pareceres do Infantil"
    with pytest.raises(ValueError, match="é uma planilha da escola"):
        gp.cadastrar_externa("X", "chamada", turma=T1, link=ID2)


# ───────────────────────── modelos ─────────────────────────

def test_catalogo_tem_os_quatro_modelos_padrao_e_nenhum_para_a_externa(amb):
    assert {"chamada", "planilha_turmas", "listagem_alunos", "imc"} <= set(pm.modelos())
    assert pm.modelo_da_finalidade("parecer_infantil") is None
    with pytest.raises(pm.ModeloDesconhecido):
        pm.modelo("inexistente")


def test_modelo_chamada_so_com_matriculados_em_ordem_e_formulas(amb):
    abas = pm.modelo("chamada").montar(pm.Contexto(ano=2026, turmas=TURMAS, turma=T1))
    assert [a.nome for a in abas][:2] == ["Fevereiro", "Março"] and len(abas) == 11
    fev = abas[0]
    nomes = [l[1] for l in fev.linhas[4:] if l[1]]
    assert nomes == ["ANA", "BETO"]                                          # ordem do nº de chamada; transferido fora
    assert fev.linhas[4][2 + 31] == '=COUNTIF(C5:AG5,"P")'
    assert fev.listas[0][1] == ("P", "F", "J")
    with pytest.raises(ValueError, match="Escolha a turma"):
        pm.modelo("chamada").montar(pm.Contexto(ano=2026, turmas=TURMAS))


def test_modelo_planilha_turmas_reaproveita_layout_e_abas_da_sincronizacao(amb):
    from src.automacao import sincroniza_sheets as sh
    abas = pm.modelo("planilha_turmas").montar(pm.Contexto(ano=2026, turmas=TURMAS))
    assert abas[0].nome == "1º ANO" and abas[0].linhas[0] == sh.CABECALHOS         # mapa_abas + CABECALHOS reaproveitados
    assert [l[4] for l in abas[0].linhas[1:]] == ["ANA", "BETO", "CARLA"]          # transferido também entra (status T)
    assert abas[0].linhas[3][8] == "T" and abas[0].linhas[1][8] == "M"


def test_modelo_listagem_tem_resumo_com_contagem(amb):
    abas = pm.modelo("listagem_alunos").montar(pm.Contexto(ano=2026, turmas=TURMAS, selecionadas=(T1,)))
    assert [a.nome for a in abas] == ["Resumo", T1]
    assert abas[0].linhas[1] == [T1, f"=COUNTA('{T1}'!C2:C1000)"]


def test_modelo_com_turma_inexistente_e_recusado(amb):
    with pytest.raises(ValueError, match="não existem em turmas.json"):
        pm.modelo("imc").montar(pm.Contexto(ano=2026, turmas=TURMAS, selecionadas=("9º Ano",)))


def test_modelo_novo_por_arquivo_json_sem_mexer_no_codigo(amb):
    pasta = amb / "config" / "modelos_planilha"
    pasta.mkdir()
    (pasta / "merenda.json").write_text(json.dumps({
        "chave": "merenda", "nome": "Merenda", "finalidade": "listagem_alunos", "uma_aba_por_turma": True, "preencher_alunos": True,
        "abas": [{"cabecalhos": ["Nº", "Nome", "Porção", "Dobro"], "formulas": {"D": "=IF(C{linha}=\"\",\"\",C{linha}*2)"},
                  "larguras": [5, 30, 10, 10]}]}), encoding="utf-8")
    (pasta / "quebrado.json").write_text("{nao é json", encoding="utf-8")        # arquivo ruim não derruba o catálogo
    assert "merenda" in pm.modelos()
    aba = pm.modelo("merenda").montar(pm.Contexto(ano=2026, turmas=TURMAS, selecionadas=(T1,)))[0]
    assert aba.linhas[1][:2] == ["1", "ANA"] and aba.linhas[1][3] == '=IF(C2="","",C2*2)'


def test_modelo_json_com_a_mesma_chave_substitui_o_padrao(amb):
    pasta = amb / "config" / "modelos_planilha"
    pasta.mkdir()
    (pasta / "imc.json").write_text(json.dumps({
        "chave": "imc", "nome": "IMC da escola", "finalidade": "imc", "abas": [{"nome": "IMC", "cabecalhos": ["A"]}]}), encoding="utf-8")
    assert pm.modelo("imc").nome == "IMC da escola" and pm.modelo("imc").origem == "escola"


# ───────────────────────── criar de modelo (plataformas) ─────────────────────────

def test_criar_chamada_em_xlsx_cadastra_e_vira_vigente(amb):
    r = gp.criar_de_modelo("chamada", "xlsx", turma=T1, destino=amb / "saida")
    assert r["vigente"] and r["item"]["modelo"] == "chamada" and r["item"]["natureza"] == "criada_de_modelo"
    assert r["item"]["finalidade"] == "chamada" and r["item"]["turma"] == T1 and r["item"]["plataforma"] == "xlsx"
    from openpyxl import load_workbook
    livro = load_workbook(r["item"]["caminho"])
    assert livro.sheetnames[0] == "Fevereiro" and livro["Fevereiro"]["B5"].value == "ANA"
    assert livro["Fevereiro"]["AH5"].value == '=COUNTIF(C5:AG5,"P")'
    assert livro["Fevereiro"].freeze_panes == "C5" and livro["Fevereiro"].data_validations.dataValidation
    assert gp.resolver("chamada", turma=T1).id == r["item"]["id"]


def test_segunda_planilha_do_mesmo_uso_entra_inativa_e_pode_assumir(amb):
    primeira = gp.criar_de_modelo("listagem_alunos", "xlsx", destino=amb / "s")
    segunda = gp.criar_de_modelo("listagem_alunos", "xlsx", nome="Lista nova", destino=amb / "s")
    assert not segunda["vigente"] and "INATIVA" in segunda["avisos"][0]
    assert gp.resolver("listagem_alunos").id == primeira["item"]["id"]            # o que estava em uso não mudou sozinho
    terceira = gp.criar_de_modelo("listagem_alunos", "xlsx", nome="Lista 3", destino=amb / "s", tornar_vigente=True)
    assert gp.resolver("listagem_alunos").id == terceira["item"]["id"]
    assert pr.obter(primeira["item"]["id"])["status"] == "inativa"


def test_nome_de_arquivo_repetido_nao_sobrescreve(amb):
    a = gp.criar_de_modelo("imc", "xlsx", nome="IMC 2026", destino=amb / "s")
    b = gp.criar_de_modelo("imc", "xlsx", nome="IMC 2026", destino=amb / "s")
    assert a["item"]["caminho"] != b["item"]["caminho"] and b["item"]["caminho"].endswith("IMC 2026 (2).xlsx")


def test_criar_de_modelo_recusa_pedidos_invalidos(amb):
    with pytest.raises(ValueError, match="é de uma turma"):
        gp.criar_de_modelo("chamada", "xlsx")
    with pytest.raises(pm.ModeloDesconhecido):
        gp.criar_de_modelo("nada", "xlsx")
    with pytest.raises(ValueError, match="Plataforma desconhecida"):
        gp.criar_de_modelo("imc", "numbers")
    (amb / "dados" / "2026" / "turmas.json").unlink()
    with pytest.raises(ValueError, match="turmas.json"):
        gp.criar_de_modelo("imc", "xlsx")


def test_criar_de_modelo_ods_sem_libreoffice_explica(amb, monkeypatch):
    import src.comum.conversao_pdf as cp
    monkeypatch.setattr(cp, "encontrar_soffice", lambda: None)
    with pytest.raises(plat.PlataformaIndisponivel, match="LibreOffice"):
        gp.criar_de_modelo("imc", "ods")
    assert pr.listar()["total"] == 0


@pytest.mark.skipif(not TEM_SOFFICE, reason="LibreOffice não instalado")
def test_criar_em_ods_mantem_estrutura_e_formulas(amb):
    r = gp.criar_de_modelo("imc", "ods", turmas_selecionadas=[T1], destino=amb / "s")
    arquivo = r["item"]["caminho"]
    assert arquivo.endswith(".ods") and r["item"]["plataforma"] == "ods"
    with zipfile.ZipFile(arquivo) as z:
        conteudo = z.read("content.xml").decode("utf-8")
    assert "IMC (kg/m²)" in conteudo and "ROUND" in conteudo and T1 in conteudo


@pytest.mark.skipif(not TEM_SOFFICE, reason="LibreOffice não instalado")
def test_formulas_calculam_igual_no_libreoffice(amb, tmp_path):
    """O IMC e a frequência calculam de verdade (LibreOffice recalcula o .xlsx)."""
    from openpyxl import load_workbook
    r = gp.criar_de_modelo("imc", "xlsx", turmas_selecionadas=[T1], destino=amb / "s")
    livro = load_workbook(r["item"]["caminho"])
    ws = livro[T1]
    ws["F2"], ws["G2"] = 20, 120                                              # 20 / 1,2² = 13,9
    livro.save(amb / "imc_preenchido.xlsx")
    saida = tmp_path / "csv"
    subprocess.run([encontrar_soffice(), f"-env:UserInstallation={(tmp_path / 'perfil').as_uri()}", "--headless", "--convert-to", "csv",
                    "--outdir", str(saida), str(amb / "imc_preenchido.xlsx")],
                   check=True, capture_output=True, timeout=180)
    linhas = (saida / "imc_preenchido.csv").read_text(encoding="utf-8").splitlines()
    assert "13.9" in linhas[1].split(",")                                       # coluna H = IMC calculado


# ───────────────────────── plataforma Google (serviço falso) ─────────────────────────

class _Pedido:
    def __init__(self, valor):
        self.valor = valor

    def execute(self, num_retries=0):
        return self.valor


class _ServicoFalso:
    def __init__(self):
        self.valores, self.formatacao = [], []

    def create(self, body, fields=None):
        self.criada = body
        return _Pedido({"spreadsheetId": ID1, "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{ID1}/edit",
                        "properties": {"title": body["properties"]["title"]},
                        "sheets": [{"properties": {"title": s["properties"]["title"]}} for s in body.get("sheets", [])]})

    def get(self, spreadsheetId, fields=None):
        return _Pedido({"sheets": [{"properties": {"sheetId": 10 + i, "title": s["properties"]["title"]}}
                                   for i, s in enumerate(self.criada.get("sheets", []))]})

    def values(self):
        servico = self

        class _V:
            def batchUpdate(self, spreadsheetId, body):
                servico.valores.append(body)
                return _Pedido({})
        return _V()

    def batchUpdate(self, spreadsheetId, body):
        self.formatacao += body["requests"]
        return _Pedido({})


def test_criar_modelo_no_google_grava_valores_formulas_e_formatacao(amb):
    servico = _ServicoFalso()
    r = gp.criar_de_modelo("imc", "google_sheets", turmas_selecionadas=[T1], servico=servico)
    assert r["item"]["planilha_id"] == ID1 and r["item"]["plataforma"] == "google_sheets" and r["vigente"]
    assert servico.criada["sheets"] == [{"properties": {"title": T1}}]
    corpo = servico.valores[0]
    assert corpo["valueInputOption"] == "USER_ENTERED"                           # fórmulas são interpretadas
    celulas = corpo["data"][0]["values"]
    assert celulas[0][7] == "IMC (kg/m²)" and celulas[1][7].startswith("=IF(OR(F2=")
    tipos = {next(iter(p)) for p in servico.formatacao}
    assert {"setDataValidation", "repeatCell", "updateDimensionProperties", "updateSheetProperties"} <= tipos
    validacao = next(p for p in servico.formatacao if "setDataValidation" in p)["setDataValidation"]
    assert validacao["range"]["sheetId"] == 10 and validacao["range"]["startRowIndex"] == 1


# ───────────────────────── extensibilidade ─────────────────────────

def test_nova_plataforma_entra_sem_mexer_nos_modulos(amb, monkeypatch):
    class Csv(plat.Plataforma):
        nome, rotulo, local, extensao = "csvlocal", "CSV", True, ".csv"

        def referencia(self, link="", caminho="", conferir=True):
            return {"referencia": str(caminho), "link": "", "caminho": str(caminho), "planilha_id": ""}

        def criar(self, nome, abas, destino=None, servico=None):
            arquivo = amb / f"{nome}.csv"
            arquivo.write_text("\n".join(",".join(str(c) for c in l) for l in abas[0].linhas), encoding="utf-8")
            return {**self.referencia(caminho=str(arquivo)), "titulo": nome}

    monkeypatch.setitem(plat._PLATAFORMAS, "csvlocal", Csv())
    r = gp.criar_de_modelo("imc", "csvlocal", turmas_selecionadas=[T1])
    assert r["item"]["plataforma"] == "csvlocal" and "IMC (kg/m²)" in open(r["item"]["caminho"], encoding="utf-8").read()
    assert gp.resolver("imc").plataforma == "csvlocal"


# ───────────────────────── integração com os módulos ─────────────────────────

def test_parecer_usa_so_a_planilha_escolhida_e_filtra_por_turma(amb):
    from src.automacao import parecer_planilha as pp
    a = pr.criar("Pareceres IV", ID1, finalidade="parecer_infantil", turma=T2)
    pr.criar("Pareceres V", ID2, finalidade="parecer_infantil", turma="INFANTIL 5 Integral A")
    assert [p["id"] for p in pp.planilhas_do_cadastro(a["id"])] == [a["id"]]
    assert [p["turma"] for p in pp.planilhas_do_cadastro(None, [T2])] == [T2]
    with pytest.raises(ValueError, match="não está entre as turmas escolhidas"):
        pp.planilhas_do_cadastro(a["id"], ["INFANTIL 5 Integral A"])
    with pytest.raises(ValueError, match="Nenhuma planilha de pareceres"):
        pp.planilhas_do_cadastro(None, ["9º Ano"])
    assert len(pp.planilhas_do_cadastro()) == 2


def test_parecer_recusa_planilha_que_nao_e_do_google(amb):
    from src.automacao import parecer_planilha as pp
    pr.criar("Local", caminho=_xlsx(amb), plataforma="xlsx", finalidade="parecer_infantil", turma=T2)
    with pytest.raises(ValueError, match="só trabalha com Google Sheets"):
        pp.planilhas_do_cadastro()


def test_rotina_diaria_busca_a_planilha_no_gerenciador(amb, monkeypatch):
    from src.automacao import rotina_diaria as rd
    chamadas = []
    monkeypatch.setattr(rd, "_precisa_de_mudanca", lambda ctx, etapa: {"mudou": True})
    monkeypatch.setattr(rd, "_executar", lambda ctx, etapa, comandos: chamadas.append(comandos) or [0])
    monkeypatch.setattr(rd, "_marcar", lambda *a, **k: None)
    ctx = rd.Ctx(hoje=__import__("datetime").date(2026, 3, 2), forcar=True, simular=False)
    assert rd.etapa_planilha(ctx) == 1 and chamadas == []                      # sem planilha ativa: erro claro, nada roda
    pr.criar("Turmas", ID1, finalidade="planilha_turmas")
    assert rd.etapa_planilha(ctx) == 0
    assert chamadas == [[["sheets", "--operacao", "atualizar", "--confirmo"]]]  # nenhum link/ID no comando


def test_nenhum_modulo_guarda_link_id_ou_caminho_de_planilha_no_codigo():
    """Garantia de arquitetura: só o gerenciador/cadastro/plataformas conhecem formatos de link e extensões."""
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parent.parent / "src"
    permitidos = {"planilhas_registro.py", "planilhas_plataformas.py", "planilhas_gerenciador.py", "planilhas_modelos.py",
                  "google_sheets.py", "planilhas.py", "parecer_planilha.py", "configuracao.py"}
    padrao = re.compile(r"spreadsheets/d/[A-Za-z0-9_-]{20,}|\b1[A-Za-z0-9_-]{43}\b")
    achados = [f"{arq.relative_to(raiz)}:{n}" for arq in raiz.rglob("*.py") if arq.name not in permitidos
               for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1) if padrao.search(linha)]
    assert achados == []
    assert not re.search(r"planilha_google_id|definir_planilha_google", " ".join(a.read_text(encoding="utf-8") for a in raiz.rglob("*.py")))


# ───────────────────────── API ─────────────────────────

@pytest.fixture()
def web(amb):
    from src.web.app import create_app
    return create_app().test_client()


def test_api_modelos_e_plataformas(web):
    d = web.get("/web/api/planilhas/modelos").get_json()
    assert {"chamada", "imc"} <= {m["chave"] for m in d["modelos"]}
    assert {"google_sheets", "xlsx", "ods"} == {p["valor"] for p in d["plataformas"]}
    assert T1 in d["turmas"]


def test_api_cadastra_planilha_local_cria_de_modelo_e_ativa(web, amb):
    r = web.post("/web/api/planilhas", json={"nome": "Lista", "plataforma": "xlsx", "caminho": _xlsx(amb), "finalidade": "listagem_alunos"})
    assert r.status_code == 201 and r.get_json()["item"]["plataforma"] == "xlsx"
    r = web.post("/web/api/planilhas", json={"nome": "Dup", "plataforma": "xlsx", "caminho": _xlsx(amb)})
    assert r.status_code == 409
    r = web.post("/web/api/planilhas/criar-de-modelo", json={"modelo": "listagem_alunos", "plataforma": "xlsx"})
    assert r.status_code == 201 and r.get_json()["avisos"]                    # já havia uma ativa: a nova ficou inativa
    novo = r.get_json()["item"]["id"]
    r = web.post(f"/web/api/planilhas/{novo}/ativar")
    assert r.status_code == 200 and r.get_json()["item"]["status"] == "ativa"
    ativas = web.get("/web/api/planilhas?finalidade=listagem_alunos&status=ativa").get_json()
    assert [i["id"] for i in ativas["itens"]] == [novo]


def test_api_criar_de_modelo_erros(web):
    assert web.post("/web/api/planilhas/criar-de-modelo", json={"modelo": "nada", "plataforma": "xlsx"}).status_code == 400
    assert web.post("/web/api/planilhas/criar-de-modelo", json={"modelo": "chamada", "plataforma": "xlsx"}).status_code == 400
    assert web.post("/web/api/planilhas/criar-de-modelo", json={"modelo": "imc", "plataforma": "numbers"}).status_code == 400


def test_automacao_planilha_modelo_registrada(amb):
    from src.comum import registro_scripts as reg
    s = reg.obter("planilha_modelo")
    nomes = {e["nome"] for e in s.extras()}
    assert {"modelo", "plataforma", "nome_planilha", "tornar_vigente"} <= nomes
    from src.comum.opcoes_execucao import Opcoes
    plano = s.planejar(Opcoes(turmas=[T1]), {"modelo": "chamada", "plataforma": "xlsx"}, TURMAS, {})
    assert plano.kwargs["modelo"] == "chamada" and plano.kwargs["turma"] == T1
    with pytest.raises(ValueError, match="exatamente uma turma"):
        s.planejar(Opcoes(turmas=[]), {"modelo": "chamada", "plataforma": "xlsx"}, TURMAS, {})

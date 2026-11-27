"""
Requerimento de matrícula (preencher_requerimento.py): Filiação 1/2 = Responsável 1/2 (tags _RESP1/_RESP2), a coluna do
documento do responsável 1 é ignorada, modelo enviado pela tela em <base>/MODELO, PDFs em <base>/<ano>/ e a planilha vem do
cadastro (tipo Matrícula).
"""
import csv
import io

import pytest
from docx import Document

from src.automacao import preencher_requerimento as pr
from src.comum import google_sheets as gs, paths, planilhas_gerenciador as gp, planilhas_registro as reg

CAB = ["Carimbo de data/hora", "Nome do aluno (conforme consta na certidão de nascimento)", "Data de Nascimento",
       "RG do aluno:", "CPF do aluno:", "Cartão do SUS do aluno:",
       "Responsável 1 (nome) - esse também será responsável pelo acesso na Área do Aluno.seed",
       "Documento do responsável 1 (RG e CPF)", "Telefone responsável 1:", "CPF responsável 1:",
       "profissão responsável 1:", "E-mail responsável 1:", "Responsável 2 (nome):",
       "Documento Responsável 2 (RG e CPF)", "Telefone responsável 2:", "CPF responsável 2:",
       "Profissão responsável 2:", "E-mail responsável 2:"]
RESP = ["01/01/2027", "Maria Souza", "05/03/2018", "12.345", "111.222.333-44", "999", "Ana Souza", "https://foto-do-rg",
        "42999990000", "222.333.444-55", "Costureira", "a@x.com", "João Souza", "RG 9.876.543-2 CPF 333.444.555-66",
        "42888880000", "", "Pedreiro", "j@x.com"]


def _valores(resposta=RESP):
    get = pr.montar_getters(CAB)
    return pr.valores_da_linha(lambda k: get(resposta, k), [])


def test_filiacao_1_e_2_vem_dos_responsaveis_1_e_2():
    v = _valores()
    assert (v["NOME_RESP1"], v["CPF_RESP1"], v["TEL_RESP1"], v["PROF_RESP1"]) == ("ANA SOUZA", "222.333.444-55", "42999990000", "Costureira")
    assert (v["NOME_RESP2"], v["RG_RESP2"], v["CPF_RESP2"], v["PROF_RESP2"]) == ("JOÃO SOUZA", "9.876.543-2", "333.444.555-66", "Pedreiro")
    assert not any(k.endswith(("_MAE", "_PAI")) for k in v)


def test_documento_do_responsavel_1_e_ignorado():
    v = _valores()
    assert v["RG_RESP1"] == "" and v["DOC_RESP"] == ""
    com_doc = list(RESP)
    com_doc[7], com_doc[9] = "RG 1.111.111 CPF 999.999.999-99", ""     # só a coluna do documento preenchida
    v2 = _valores(com_doc)
    assert v2["RG_RESP1"] == "" and v2["CPF_RESP1"] == "" and v2["DOC_RESP"] == "" and v2["CPF_RESP"] == ""
    assert v["NOME_RESP"] == "ANA SOUZA" and v["CPF_RESP"] == "222.333.444-55"


def test_tags_resp1_resp2_nao_se_misturam_com_resp(tmp_path):
    modelo = tmp_path / "m.docx"
    d = Document()
    d.add_paragraph("$NOME_RESP1 | $NOME_RESP2 | $NOME_RESP | $TEL_RESP1 | $MAE | $PAI")
    d.save(modelo)
    saida = tmp_path / "s.docx"
    pr.preencher_docx(modelo, saida, _valores())
    texto = Document(saida).paragraphs[0].text
    assert texto.startswith("ANA SOUZA | JOÃO SOUZA | ANA SOUZA | 42999990000 |")
    assert pr.tags_sobrando(saida) == set()


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_PARECERES_BASE", str(tmp_path / "base"))
    monkeypatch.setattr(paths, "ano_atual", lambda: "2027")
    return tmp_path / "base"


def _docx_bytes(texto="$NOME_ALUNO"):
    buf = io.BytesIO()
    d = Document()
    d.add_paragraph(texto)
    d.save(buf)
    return buf.getvalue()


def test_pdfs_vao_para_a_pasta_do_ano_letivo(base):
    assert pr.pasta_saida_padrao() == base / "2027" / "REQUERIMENTO_MATRICULA"


def test_modelo_enviado_fica_na_pasta_de_modelos(base):
    assert pr.modelo_enviado() is None
    r = pr.salvar_modelo(_docx_bytes())
    assert r["substituiu"] is False and pr.modelo_enviado() == base / "MODELO" / pr.NOME_MODELO_ENVIADO
    assert pr.salvar_modelo(_docx_bytes())["substituiu"] is True


@pytest.mark.parametrize("conteudo,trecho", [(b"", "vazio"), (b"abc", "não é um documento Word"),
                                             (_docx_bytes("sem marcador"), "$NOME_ALUNO")])
def test_modelo_invalido_e_recusado(base, conteudo, trecho):
    with pytest.raises(ValueError, match=trecho.replace("$", r"\$")):
        pr.salvar_modelo(conteudo)
    assert pr.modelo_enviado() is None


def test_rota_de_upload_do_modelo(base):
    from src.web.app import create_app
    web = create_app().test_client()
    assert web.get("/web/api/configuracoes/modelo-requerimento").get_json()["existe"] is False
    r = web.post("/web/api/configuracoes/modelo-requerimento", data={"arquivo": (io.BytesIO(_docx_bytes()), "modelo.docx")},
                 content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["existe"] is True
    r = web.post("/web/api/configuracoes/modelo-requerimento", data={"arquivo": (io.BytesIO(b"x"), "modelo.txt")},
                 content_type="multipart/form-data")
    assert r.status_code == 400


def test_planilha_vem_do_cadastro_com_o_tipo_matricula(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    (tmp_path / "dados").mkdir()
    pid = "1" + "a" * 43
    reg.criar("Matrícula 2027", f"https://docs.google.com/spreadsheets/d/{pid}/edit", "Matrícula", finalidade="matricula")
    lidos = {}
    monkeypatch.setattr(gs, "abrir_servico", lambda **k: "servico")
    monkeypatch.setattr(gs, "listar_abas", lambda p, servico=None: ["Instruções", "Respostas ao formulário 1"])
    monkeypatch.setattr(gs, "ler_intervalo", lambda p, i, formatado=False, servico=None: lidos.update(p=p, i=i) or [CAB, RESP])
    cab, linhas = pr.ler_planilha_cadastrada()
    assert cab == CAB and linhas == [RESP]
    assert lidos["p"] == pid and lidos["i"].startswith("'Respostas ao formulário 1'")


def test_sem_planilha_matricula_cadastrada_o_erro_explica(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    (tmp_path / "dados").mkdir()
    with pytest.raises(ValueError, match="Matrícula"):
        pr.ler_planilha_cadastrada()


def test_gerar_com_filtro_e_modo_teste(base, tmp_path, monkeypatch):
    modelo = tmp_path / "m.docx"
    modelo.write_bytes(_docx_bytes("$NOME_ALUNO"))
    def falso(docxs, pasta):
        for d in docxs:
            (pasta / (d.stem + ".pdf")).write_bytes(b"%PDF")
        return {d: pasta / (d.stem + ".pdf") for d in docxs}
    monkeypatch.setattr(pr, "docx_para_pdf_lote", falso)
    outra = list(RESP)
    outra[1] = "Pedro Lima"
    r = pr.gerar_requerimentos(CAB, [RESP, outra], modelo=modelo, saida=base / "2027")
    assert r["gerados"] == 2 and sorted(p.name for p in (base / "2027").iterdir()) == ["001_Maria_Souza.pdf", "002_Pedro_Lima.pdf"]
    assert pr.gerar_requerimentos(CAB, [RESP, outra], modelo=modelo, saida=base / "x", nome="pedro")["gerados"] == 1
    assert pr.gerar_requerimentos(CAB, [RESP, outra], modelo=modelo, saida=base / "y", modo_teste=True)["gerados"] == 1


def test_automacao_registrada_em_documentos():
    from src.comum import ajuda_automacoes, registro_scripts as rs
    assert rs.obter("requerimento") is not None and rs.obter("requerimento").recursos == ("teste",)
    assert ajuda_automacoes.AUTOMACOES["requerimento"]["grupo"] == "documentos"
    base_html = open("src/web/templates/base.html", encoding="utf-8").read()
    assert 'data-auto="requerimento"' in base_html


def test_previa_sem_planilha_ou_modelo_explica_em_vez_de_dar_erro_500(base, tmp_path, monkeypatch):
    from src.web.app import create_app
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    (tmp_path / "dados").mkdir()
    web = create_app().test_client()
    r = web.post("/web/api/automacoes/requerimento/previa", json={})
    assert r.status_code == 400 and "Matrícula" in r.get_json()["erro"]          # sem planilha cadastrada
    reg.criar("Matrícula 2027", "https://docs.google.com/spreadsheets/d/" + "1" + "a" * 43 + "/edit", "Matrícula", finalidade="matricula")
    r = web.post("/web/api/automacoes/requerimento/previa", json={})
    assert r.status_code == 400 and "modelo" in r.get_json()["erro"].lower()    # falta enviar o modelo
    pr.salvar_modelo(_docx_bytes())
    assert web.post("/web/api/automacoes/requerimento/previa", json={}).status_code == 200


def test_configuracao_do_script_mostra_o_modelo_do_requerimento_e_nao_a_pasta_dos_termos(base):
    from src.comum import configuracoes_scripts as cs, registro_scripts as rs
    assert "modelo_requerimento" in rs.obter("requerimento").configs and "pasta_modelos" not in rs.obter("requerimento").configs
    ok, texto = cs.CATALOGO["modelo_requerimento"].ler()
    assert ok is False and "nenhum modelo" in texto
    pr.salvar_modelo(_docx_bytes())
    assert cs.CATALOGO["modelo_requerimento"].ler()[0] is True


def test_conversao_para_pdf_nao_abre_janela_de_console(monkeypatch, tmp_path):
    import subprocess
    from src.comum import conversao_pdf
    visto = {}
    monkeypatch.setattr(conversao_pdf, "exigir_soffice", lambda: "soffice")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: visto.update(k))
    conversao_pdf.docx_para_pdf([tmp_path / "a.docx"], tmp_path)
    assert visto.get("creationflags") == 0x08000000


CAB2 = CAB + ["Recebe o Bolsa família?", "Número NIS estudante", "Número NIS responsável", "Renda familiar (selecionar 1 opção):",
              "Documento do responsável 1: (RG ou CIN)", "Documento do responsável 2: (RG ou CIN)", "A Unidade consumidora é?",
              "Endereço de e-mail", "Sexo do aluno"]


def _valores2(**campos):
    resp = RESP + ["Sim", "123456", "654321", "Não declarou", "12.111.222-3", "9.876.543-2", "Da COPEL (energia elétrica)",
                   "familia@x.com", "Feminino"]
    for nome, valor in campos.items():
        resp[[c.split(":")[0].split(" (")[0] for c in CAB2].index(nome)] = valor
    get = pr.montar_getters(CAB2)
    avisos = []
    return pr.valores_da_linha(lambda k: get(resp, k), avisos), avisos


def test_colunas_novas_documento_texto_sexo_nis_bolsa_email_e_renda():
    v, avisos = _valores2()
    assert v["RG_RESP1"] == v["DOC_RESP"] == "12.111.222-3" and v["RG_RESP2"] == "9.876.543-2"   # coluna (RG ou CIN), não a foto
    assert "foto-do-rg" not in str(v.values())
    assert v["FEM"] is True and v["MASC"] is False and v["B.F"] is True
    assert (v["NIS_ALUNO"], v["NIS_RESP"], v["Email_Resp"]) == ("123456", "654321", "a@x.com")     # e-mail do responsável 1 primeiro
    assert v["OP.N.I"] is True and v["1A3"] is False
    assert (v["CP"], v["SAN"], v["N.P"], v["N.D.CONS"]) == (True, False, False, False) and avisos == []


def test_email_do_formulario_e_reserva_e_nao_declarou_da_unidade_consumidora():
    v, _ = _valores2(**{"E-mail responsável 1": "", "A Unidade consumidora é?": ""})
    assert v["Email_Resp"] == "familia@x.com" and v["N.D.CONS"] is True and v["CP"] is False


def test_modelo_novo_so_usa_tags_conhecidas():
    for tag in ("NOME_RESP1", "Email_Resp", "NIS_RESP", "NIS_ALUNO", "FEM", "MASC", "B.F", "N.D.CONS", "OP.N.I"):
        assert tag in pr.TODAS_TAGS
    assert "N.D" not in pr.TODAS_TAGS

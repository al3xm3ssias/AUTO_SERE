"""parecer_fund: modelos Word por turma, arquivo de controle, marcadores, QR de 150 px e geração por aluno."""
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Emu
from PIL import Image

from src.automacao import parecer_fund as pf
from src.comum import escola, paths
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app

NOME_ESCOLA = "Escola Municipal Profª Judith Macedo Silveira"


def _al(n, cgm, nome, sit="Matriculado"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Situação": sit}


TURMAS = {
    "1º Ano Integral A": [_al(1, "1001", "ANA CLARA LIMA"), _al(2, "1002", "BETO SOUZA", "Transferido"), _al(3, "1003", "CAIO DIAS")],
    "1º Ano Integral B": [_al(1, "2001", "DUDA ROCHA")],
    "Infantil IV A": [_al(1, "3001", "EDU PAIVA")],
}


def _modelo_docx(com_aluno=True, quebrado=False) -> bytes:
    """Modelo pequeno, no estilo do real: marcador colado em 'MUNICIPAL', marcador em tabela e cabeçalho."""
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "ANO $ANO"
    doc.add_paragraph("ESCOLA MUNICIPAL$ESCOLA")
    if com_aluno:
        p = doc.add_paragraph()
        if quebrado:                                   # o Word costuma partir assim
            p.add_run("ALUNO(A): $AL").bold = True
            p.add_run("UNO")
        else:
            p.add_run("ALUNO(A): $ALUNO").bold = True
    tabela = doc.add_table(rows=1, cols=2)
    tabela.cell(0, 0).text = "TURMA: $TURMA"
    tabela.cell(0, 1).text = "CGM $CGM / chamada $CHAMADA"
    doc.add_paragraph("Ponta Grossa, de de 20 .")
    for _ in range(3):
        doc.add_paragraph("")
    saida = io.BytesIO()
    doc.save(saida)
    return saida.getvalue()


def _texto(docx_bytes: bytes) -> str:
    doc = Document(io.BytesIO(docx_bytes))
    partes = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for linha in t.rows:
            partes += [c.text for c in linha.cells]
    partes += [p.text for p in doc.sections[0].header.paragraphs]
    return "\n".join(partes)


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path / "dados" / "2026")
    (tmp_path / "dados" / "2026").mkdir(parents=True)
    (tmp_path / "dados" / "2026" / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    monkeypatch.setattr(escola, "nome", lambda: NOME_ESCOLA)
    monkeypatch.delenv("AUTO_SERE_PARECERES_BASE", raising=False)
    return tmp_path


# ───────────── nomes e pastas ─────────────

@pytest.mark.parametrize("entrada,esperado", [
    ("1º_ANO_-_2026.docx", "1º_ANO_-_2026.docx"),
    ("Modelo 1º Ano.DOCX", "Modelo 1º Ano.docx"),
    ("..\\..\\fora\\evil.docx", "evil.docx"),
    ("a/b/c.docx", "c.docx"),
    ('mod<>:"?*elo.docx', "mod_elo.docx"),
    ("semextensao", "semextensao.docx"),
])
def test_nome_seguro_arquivo(entrada, esperado):
    assert pf.nome_seguro_arquivo(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "   ", ".docx", "...docx", "/"])
def test_nome_seguro_arquivo_vazio(entrada):
    with pytest.raises(ValueError, match="nome"):
        pf.nome_seguro_arquivo(entrada)


def test_pastas_padrao_e_com_override(amb, monkeypatch):
    assert pf.pasta_modelos() == amb / "dados" / "MODELO"
    assert pf.pasta_pareceres() == amb / "dados" / "2026" / "PARECERES"
    assert pf.arquivo_controle() == amb / "dados" / "MODELO" / "controle_modelos.json"
    monkeypatch.setenv("AUTO_SERE_PARECERES_BASE", str(amb / "servidor"))
    assert pf.pasta_modelos() == amb / "servidor" / "MODELO"
    assert pf.pasta_pareceres("2027") == amb / "servidor" / "2027" / "PARECERES"


def test_caminho_do_parecer(tmp_path):
    assert pf.caminho_do_parecer(tmp_path, "ANA CLARA LIMA", "1001", 7) == tmp_path / "7 - ANA_CLARA_LIMA.docx"
    assert pf.caminho_do_parecer(tmp_path, "Zé/da Silva", "1001", None).name == "1001 - Zé_da_Silva.docx"
    assert pf.caminho_do_parecer(tmp_path, "", "1001", "").name == "1001 - 1001.docx"


# ───────────── modelo e arquivo de controle ─────────────

def test_controle_vazio_no_comeco(amb):
    assert pf.carregar_controle() == {}


def test_salvar_modelo_grava_arquivo_e_liga_as_turmas(amb):
    r = pf.salvar_modelo("1º_ANO_-_2026.docx", _modelo_docx(), ["1º Ano Integral A", "1º Ano Integral B"])
    assert r == {"arquivo": "1º_ANO_-_2026.docx", "turmas": ["1º Ano Integral A", "1º Ano Integral B"],
                 "substituiu": False, "turmas_afetadas": []}
    assert (pf.pasta_modelos() / "1º_ANO_-_2026.docx").is_file()
    bruto = json.loads(pf.arquivo_controle().read_text(encoding="utf-8"))
    assert bruto["versao"] == 1
    assert set(bruto["modelos"]) == {"1º Ano Integral A", "1º Ano Integral B"}
    assert bruto["modelos"]["1º Ano Integral A"]["arquivo"] == "1º_ANO_-_2026.docx"
    assert bruto["modelos"]["1º Ano Integral A"]["atualizado_em"]
    assert pf.modelo_da_turma("1º Ano Integral A") == pf.pasta_modelos() / "1º_ANO_-_2026.docx"
    assert pf.modelo_da_turma("Infantil IV A") is None


def test_outro_arquivo_para_outra_turma_nao_mexe_nas_demais(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    pf.salvar_modelo("dois.docx", _modelo_docx(), ["1º Ano Integral B"])
    c = pf.carregar_controle()
    assert c["1º Ano Integral A"]["arquivo"] == "um.docx" and c["1º Ano Integral B"]["arquivo"] == "dois.docx"


def test_religar_uma_turma_troca_so_a_ligacao_dela(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A", "1º Ano Integral B"])
    pf.salvar_modelo("dois.docx", _modelo_docx(), ["1º Ano Integral B"])
    c = pf.carregar_controle()
    assert c["1º Ano Integral A"]["arquivo"] == "um.docx" and c["1º Ano Integral B"]["arquivo"] == "dois.docx"


def test_reenviar_mesmo_arquivo_avisa_das_outras_turmas_afetadas(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A", "1º Ano Integral B"])
    r = pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    assert r["substituiu"] is True and r["turmas_afetadas"] == ["1º Ano Integral B"]


def test_salvar_exige_turma(amb):
    with pytest.raises(ValueError, match="pelo menos uma turma"):
        pf.salvar_modelo("um.docx", _modelo_docx(), [])
    with pytest.raises(ValueError, match="pelo menos uma turma"):
        pf.salvar_modelo("um.docx", _modelo_docx(), ["  ", ""])
    assert not pf.pasta_modelos().exists()                         # recusou antes de gravar qualquer coisa


def test_modelo_invalido_nao_grava_nada(amb):
    for ruim, msg in [(b"", "vazio"), (b"isto nao e um docx", "não é um documento Word"),
                      (_modelo_docx(com_aluno=False), r"\$ALUNO")]:
        with pytest.raises(ValueError, match=msg):
            pf.salvar_modelo("x.docx", ruim, ["1º Ano Integral A"])
    assert not pf.arquivo_controle().exists()


def test_zip_que_nao_e_word_e_recusado():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("qualquer.txt", "oi")
    with pytest.raises(ValueError, match="não é um documento Word"):
        pf.validar_modelo(z.getvalue())


def test_modelo_grande_demais(monkeypatch):
    monkeypatch.setattr(pf, "LIMITE_MODELO_MB", 0)
    with pytest.raises(ValueError, match="passa de"):
        pf.validar_modelo(_modelo_docx())


def test_marcador_aluno_partido_em_pedacos_vale_na_validacao():
    pf.validar_modelo(_modelo_docx(quebrado=True))


def test_controle_ilegivel_da_erro_claro(amb):
    pf.pasta_modelos().mkdir(parents=True)
    pf.arquivo_controle().write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="ilegível"):
        pf.carregar_controle()
    pf.arquivo_controle().write_text(json.dumps({"modelos": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="ilegível"):
        pf.carregar_controle()


def test_arquivo_de_modelo_que_sumiu_nao_conta(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    (pf.pasta_modelos() / "um.docx").unlink()
    assert pf.modelo_da_turma("1º Ano Integral A") is None


# ───────────── QR code ─────────────

def test_payload_do_qr_ida_e_volta():
    assert pf.montar_payload_qr(2026, "1234567890") == "AUTOSERE|PF|2026|1234567890"
    assert pf.ler_payload_qr("AUTOSERE|PF|2026|1234567890") == {"ano": "2026", "cgm": "1234567890"}
    assert pf.ler_payload_qr("  AUTOSERE|PF|2026|99  ") == {"ano": "2026", "cgm": "99"}


@pytest.mark.parametrize("texto", ["", None, "https://exemplo.com", "AUTOSERE|XX|2026|1", "AUTOSERE|PF|26|1",
                                   "AUTOSERE|PF|2026|", "AUTOSERE|PF|2026|1|extra", "autosere|pf|2026|1"])
def test_ler_payload_que_nao_e_de_parecer(texto):
    assert pf.ler_payload_qr(texto) is None


@pytest.mark.parametrize("cgm", ["", "  ", "12 34", "12|34", None])
def test_cgm_invalido_no_qr(cgm):
    with pytest.raises(ValueError, match="CGM inválido"):
        pf.montar_payload_qr(2026, cgm)


def test_qr_tem_150_por_150_pixels():
    png = pf.gerar_qr_png(pf.montar_payload_qr(2026, "1234567890"))
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.size == (150, 150)


def _decodificar(png_bytes: bytes) -> str:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
    return cv2.QRCodeDetector().detectAndDecode(img)[0]


def test_qr_e_legivel():
    assert _decodificar(pf.gerar_qr_png("AUTOSERE|PF|2026|1234567890")) == "AUTOSERE|PF|2026|1234567890"


# ───────────── marcadores e preenchimento ─────────────

VALORES = {"ESCOLA": "PROFª JUDITH", "ALUNO": "ANA CLARA LIMA", "TURMA": "1º Ano Integral A", "ANO": "2026",
           "CGM": "1001", "CHAMADA": 1}


def test_preenche_corpo_tabela_e_cabecalho():
    texto = _texto(pf.preencher_modelo(_modelo_docx(), VALORES, None))
    assert "ESCOLA MUNICIPAL PROFª JUDITH" in texto          # espaço inserido depois de "MUNICIPAL"
    assert "ALUNO(A): ANA CLARA LIMA" in texto
    assert "TURMA: 1º Ano Integral A" in texto and "CGM 1001 / chamada 1" in texto
    assert "ANO 2026" in texto
    assert "$" not in texto


def test_preenche_marcador_partido_em_pedacos_e_mantem_a_formatacao():
    doc = Document(io.BytesIO(pf.preencher_modelo(_modelo_docx(quebrado=True), VALORES, None)))
    p = next(p for p in doc.paragraphs if p.text.startswith("ALUNO(A)"))
    assert p.text == "ALUNO(A): ANA CLARA LIMA"
    assert p.runs[0].bold is True                             # o trecho onde o marcador começava segue em negrito


def test_nao_troca_o_que_nao_e_marcador_e_nao_repete_a_troca():
    doc = Document()
    doc.add_paragraph("Custa $ALUNOS e $5 e $ALUNO.")
    saida = io.BytesIO(); doc.save(saida)
    texto = _texto(pf.preencher_modelo(saida.getvalue(), {**VALORES, "ALUNO": "ZÉ $TURMA"}, None))
    assert "Custa $ALUNOS e $5 e ZÉ $TURMA." in texto         # nome com '$TURMA' dentro não é trocado de novo


def test_marcador_ausente_nos_valores_vira_vazio():
    doc = Document()
    doc.add_paragraph("Chamada: $CHAMADA.")
    saida = io.BytesIO(); doc.save(saida)
    assert "Chamada: ." in _texto(pf.preencher_modelo(saida.getvalue(), {}, None))


def test_qr_no_fim_com_150px_e_sem_linhas_em_branco_depois():
    qr = pf.gerar_qr_png(pf.montar_payload_qr(2026, "1001"))
    saida = pf.preencher_modelo(_modelo_docx(), VALORES, qr)
    doc = Document(io.BytesIO(saida))
    assert len(doc.inline_shapes) == 1
    forma = doc.inline_shapes[0]
    assert forma.width == Emu(150 * 9525) and forma.height == Emu(150 * 9525)          # 150 x 150 px
    ultimo = doc.paragraphs[-1]
    assert ultimo._p.xpath(".//w:drawing")                                              # o QR é a última coisa do arquivo
    assert doc.paragraphs[-2].text == "Ponta Grossa, de de 20 ."                        # as linhas vazias do fim saíram
    with zipfile.ZipFile(io.BytesIO(saida)) as z:
        midia = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(midia) == 1
        assert _decodificar(z.read(midia[0])) == "AUTOSERE|PF|2026|1001"                # e é o QR certo


def test_sem_qr_nao_mexe_no_fim():
    doc = Document(io.BytesIO(pf.preencher_modelo(_modelo_docx(), VALORES, None)))
    assert len(doc.inline_shapes) == 0 and doc.paragraphs[-1].text == ""


def test_nome_curto_da_escola():
    f = pf._nome_curto_escola
    assert f("Escola Municipal Profª Judith Macedo Silveira") == "PROFª JUDITH MACEDO SILVEIRA"
    assert f("ESCOLA MUNICIPAL PROFª JUDITH") == "PROFª JUDITH"
    assert f("E. M. Profª Judith") == "PROFª JUDITH"
    assert f("Profª Judith Macedo Silveira") == "PROFª JUDITH MACEDO SILVEIRA"


# ───────────── seleção ─────────────

def test_numero_da_chamada():
    assert pf.numero_da_chamada(TURMAS, "1º Ano Integral A", "1003") == 3
    assert pf.numero_da_chamada(TURMAS, "1º Ano Integral A", "9999") is None
    assert pf.numero_da_chamada(TURMAS, "Não existe", "1003") is None


def test_conferir_modelos(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    todas = list(TURMAS)
    assert pf.conferir_modelos(todas, explicitas=False) == ["1º Ano Integral A"]        # as sem modelo ficam de fora
    assert pf.conferir_modelos(["1º Ano Integral A"], explicitas=True) == ["1º Ano Integral A"]
    with pytest.raises(ValueError, match="1º Ano Integral B, Infantil IV A"):
        pf.conferir_modelos(["1º Ano Integral A", "1º Ano Integral B", "Infantil IV A"], explicitas=True)


def test_conferir_modelos_sem_nenhum_modelo(amb):
    with pytest.raises(ValueError, match="Nenhuma turma tem modelo"):
        pf.conferir_modelos(list(TURMAS), explicitas=False)


# ───────────── geração ─────────────

def _alunos(*cgms):
    todos = {"1001": ("ANA CLARA LIMA", "1º Ano Integral A", 1), "1003": ("CAIO DIAS", "1º Ano Integral A", 3),
             "2001": ("DUDA ROCHA", "1º Ano Integral B", 1), "3001": ("EDU PAIVA", "Infantil IV A", 1)}
    return [{"cgm": c, "nome": todos[c][0], "turma": todos[c][1], "n_chamada": todos[c][2]} for c in cgms]


def test_gera_um_parecer_por_aluno_na_pasta_da_turma(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A", "1º Ano Integral B"])
    r = pf.gerar_pareceres_fundamental(_alunos("1001", "1003", "2001"))
    raiz = amb / "dados" / "2026" / "PARECERES"
    assert r["total"] == 3 and r["gerados"] == 3 and r["ja_existiam"] == 0 and r["falhas"] == [] and r["pasta"] == str(raiz)
    assert sorted(p.relative_to(raiz).as_posix() for p in raiz.rglob("*.docx")) == [
        "1º_Ano_Integral_A/1 - ANA_CLARA_LIMA.docx", "1º_Ano_Integral_A/3 - CAIO_DIAS.docx",
        "1º_Ano_Integral_B/1 - DUDA_ROCHA.docx"]
    texto = _texto((raiz / "1º_Ano_Integral_A" / "3 - CAIO_DIAS.docx").read_bytes())
    assert "ALUNO(A): CAIO DIAS" in texto and "TURMA: 1º Ano Integral A" in texto and "ESCOLA MUNICIPAL PROFª JUDITH MACEDO SILVEIRA" in texto


def test_cada_parecer_leva_o_qr_do_proprio_aluno(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    pf.gerar_pareceres_fundamental(_alunos("1001", "1003"))
    raiz = amb / "dados" / "2026" / "PARECERES" / "1º_Ano_Integral_A"
    for arquivo, cgm in [("1 - ANA_CLARA_LIMA.docx", "1001"), ("3 - CAIO_DIAS.docx", "1003")]:
        with zipfile.ZipFile(raiz / arquivo) as z:
            png = z.read(next(n for n in z.namelist() if n.startswith("word/media/")))
        assert pf.ler_payload_qr(_decodificar(png)) == {"ano": "2026", "cgm": cgm}


def test_parecer_que_ja_existe_e_mantido_ate_pedir_para_substituir(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    pf.gerar_pareceres_fundamental(_alunos("1001"))
    arquivo = amb / "dados" / "2026" / "PARECERES" / "1º_Ano_Integral_A" / "1 - ANA_CLARA_LIMA.docx"
    arquivo.write_bytes(b"PROFESSOR JA PREENCHEU")
    r = pf.gerar_pareceres_fundamental(_alunos("1001"))
    assert r["gerados"] == 0 and r["ja_existiam"] == 1 and arquivo.read_bytes() == b"PROFESSOR JA PREENCHEU"
    r = pf.gerar_pareceres_fundamental(_alunos("1001"), substituir=True)
    assert r["gerados"] == 1 and "ALUNO(A): ANA CLARA LIMA" in _texto(arquivo.read_bytes())


def test_aluno_de_turma_sem_modelo_vira_falha_e_os_outros_seguem(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    r = pf.gerar_pareceres_fundamental(_alunos("3001", "1001"))
    assert r["gerados"] == 1
    assert r["falhas"] == [{"cgm": "3001", "nome": "EDU PAIVA", "motivo": "a turma Infantil IV A não tem modelo de parecer"}]


def test_sem_chamada_usa_o_cgm_no_nome(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    a = _alunos("1001")
    a[0]["n_chamada"] = None
    pf.gerar_pareceres_fundamental(a)
    assert (amb / "dados" / "2026" / "PARECERES" / "1º_Ano_Integral_A" / "1001 - ANA_CLARA_LIMA.docx").exists()


def test_sem_nome_da_escola_nao_gera(amb, monkeypatch):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    monkeypatch.setattr(escola, "nome", lambda: "")
    with pytest.raises(ValueError, match="nome da escola"):
        pf.gerar_pareceres_fundamental(_alunos("1001"))
    assert not (amb / "dados" / "2026" / "PARECERES").exists()


def test_sem_alunos():
    with pytest.raises(ValueError, match="Nenhum aluno"):
        pf.gerar_pareceres_fundamental([])


def test_cancelamento_interrompe_e_nao_deixa_arquivo_pela_metade(amb, monkeypatch):
    from src.comum.execucao_gui import CancelamentoSolicitado
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    chamadas = []
    def cancelar():
        chamadas.append(1)
        if len(chamadas) == 2:
            raise CancelamentoSolicitado()
    monkeypatch.setattr(pf, "verificar_cancelamento", cancelar)
    with pytest.raises(CancelamentoSolicitado):
        pf.gerar_pareceres_fundamental(_alunos("1001", "1003"))
    raiz = amb / "dados" / "2026" / "PARECERES" / "1º_Ano_Integral_A"
    assert [p.name for p in raiz.iterdir()] == ["1 - ANA_CLARA_LIMA.docx"]            # sem .tmp sobrando


# ───────────── registro (plano) ─────────────

def test_registrada(amb):
    s = reg.obter("parecer_fund")
    assert s is not None and "parecer_fund" not in rotas.AUTOMACOES_NAO_IMPLEMENTADAS
    assert set(s.recursos) == {"turma", "situacao", "cgm", "teste"} and s.confirmar is False
    assert any(e["nome"] == "substituir" for e in s.extras())


def test_plano_todas_as_turmas_com_modelo_so_matriculados(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A", "1º Ano Integral B"])
    plano = reg.obter("parecer_fund").planejar(Opcoes(), {}, TURMAS, {})
    assert plano.tipo == "sync" and plano.funcao is pf.gerar_pareceres_fundamental
    assert [(a["cgm"], a["turma"], a["n_chamada"]) for a in plano.kwargs["alunos"]] == [
        ("1001", "1º Ano Integral A", 1), ("1003", "1º Ano Integral A", 3), ("2001", "1º Ano Integral B", 1)]
    assert plano.kwargs["substituir"] is False                # o Infantil (sem modelo) e o transferido ficaram de fora


def test_plano_transferidos_teste_e_substituir(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    plano = reg.obter("parecer_fund").planejar(
        Opcoes(turmas=("1º Ano Integral A",), matriculados=False, transferidos=True), {"substituir": True}, TURMAS, {})
    assert [a["cgm"] for a in plano.kwargs["alunos"]] == ["1002"] and plano.kwargs["substituir"] is True
    plano = reg.obter("parecer_fund").planejar(Opcoes(modo_teste=True), {}, TURMAS, {})
    assert [a["cgm"] for a in plano.kwargs["alunos"]] == ["1001"]


def test_plano_por_cgm(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    plano = reg.obter("parecer_fund").planejar(Opcoes(cgms=("1003",)), {}, TURMAS, {})
    assert [a["cgm"] for a in plano.kwargs["alunos"]] == ["1003"]


def test_plano_turma_escolhida_sem_modelo_da_erro(amb):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    with pytest.raises(ValueError, match="1º Ano Integral B"):
        reg.obter("parecer_fund").planejar(Opcoes(turmas=("1º Ano Integral B",)), {}, TURMAS, {})


def test_plano_sem_escola_ou_sem_alunos(amb, monkeypatch):
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral B"])
    with pytest.raises(ValueError, match="Nenhum aluno na seleção"):
        reg.obter("parecer_fund").planejar(Opcoes(turmas=("1º Ano Integral B",), matriculados=False), {}, TURMAS, {})
    monkeypatch.setattr(escola, "nome", lambda: "")
    with pytest.raises(ValueError, match="nome da escola"):
        reg.obter("parecer_fund").planejar(Opcoes(), {}, TURMAS, {})


# ───────────── rotas: upload do modelo e execução ─────────────

@pytest.fixture()
def web(amb, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: amb / "dados" / "2026")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


URL = "/web/api/configuracoes/modelos-parecer"


def _upload(web, conteudo=None, nome="1º_ANO_-_2026.docx", turmas=("1º Ano Integral A",)):
    dados = {"arquivo": (io.BytesIO(conteudo if conteudo is not None else _modelo_docx()), nome), "turmas": list(turmas)}
    return web.post(URL, data=dados, content_type="multipart/form-data")


def test_get_lista_as_turmas_sem_modelo(web):
    d = web.get(URL).get_json()
    assert [t["turma"] for t in d["turmas"]] == list(TURMAS)
    assert all(t["arquivo"] is None for t in d["turmas"]) and d["pasta"].endswith("MODELO")


def test_upload_salva_liga_e_mostra_no_get(web, amb):
    r = _upload(web, turmas=("1º Ano Integral A", "1º Ano Integral B"))
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok" and "salvo para 2 turma(s)" in d["mensagem"]
    ligadas = {t["turma"]: t for t in d["turmas"]}
    assert ligadas["1º Ano Integral A"]["arquivo"] == "1º_ANO_-_2026.docx" and ligadas["1º Ano Integral A"]["arquivo_existe"]
    assert ligadas["Infantil IV A"]["arquivo"] is None
    assert (amb / "dados" / "MODELO" / "1º_ANO_-_2026.docx").is_file()
    assert web.get(URL).get_json()["turmas"][0]["arquivo"] == "1º_ANO_-_2026.docx"


def test_reenvio_avisa_das_outras_turmas(web):
    _upload(web, turmas=("1º Ano Integral A", "1º Ano Integral B"))
    d = _upload(web, turmas=("1º Ano Integral A",)).get_json()
    assert "atualizado" in d["mensagem"] and "1º Ano Integral B" in d["mensagem"]


@pytest.mark.parametrize("kwargs,trecho", [
    (dict(nome="modelo.pdf"), "arquivo Word"),
    (dict(conteudo=b"lixo"), "não é um documento Word"),
    (dict(conteudo=_modelo_docx(com_aluno=False)), r"\$ALUNO"),
    (dict(turmas=()), "pelo menos uma turma"),
    (dict(turmas=("Turma Fantasma",)), "não existem em turmas.json"),
])
def test_upload_recusado(web, amb, kwargs, trecho):
    r = _upload(web, **kwargs)
    assert r.status_code == 400 and __import__("re").search(trecho, r.get_json()["erro"])
    assert not (amb / "dados" / "MODELO" / "controle_modelos.json").exists()


def test_upload_sem_arquivo(web):
    r = web.post(URL, data={"turmas": ["1º Ano Integral A"]}, content_type="multipart/form-data")
    assert r.status_code == 400 and "Escolha o arquivo" in r.get_json()["erro"]


def test_upload_sem_turmas_json(web, amb):
    (amb / "dados" / "2026" / "turmas.json").unlink()
    r = _upload(web)
    assert r.status_code == 400 and "automação 'Turmas'" in r.get_json()["erro"]


def test_get_com_controle_ilegivel_da_500_com_mensagem(web, amb):
    (amb / "dados" / "MODELO").mkdir(parents=True)
    (amb / "dados" / "MODELO" / "controle_modelos.json").write_text("{x", encoding="utf-8")
    r = web.get(URL)
    assert r.status_code == 500 and "ilegível" in r.get_json()["erro"]


def test_executar_pela_web_gera_os_arquivos(web, amb):
    _upload(web, turmas=("1º Ano Integral A",))
    r = web.post("/web/api/automacoes/parecer_fund/executar", json={"turmas": ["1º Ano Integral A"]})
    assert r.status_code == 200 and r.get_json()["status"] == "executando"
    for _ in range(300):
        s = web.get("/web/api/automacoes/parecer_fund/status").get_json()
        if s["status"] != "executando":
            break
        time.sleep(0.05)
    assert s["status"] == "concluido", s
    res = rotas._EXECUCOES["parecer_fund"]["resultado"]
    assert res["gerados"] == 2 and res["falhas"] == []
    assert (amb / "dados" / "2026" / "PARECERES" / "1º_Ano_Integral_A" / "1 - ANA_CLARA_LIMA.docx").is_file()
    assert any("Concluído: 2 parecer(es) gerado(s)" in linha for linha in s["logs"])


def test_executar_sem_modelo_da_400_com_orientacao(web):
    r = web.post("/web/api/automacoes/parecer_fund/executar", json={"turmas": ["1º Ano Integral A"]})
    assert r.status_code == 400 and "Configurações → Modelos de parecer" in r.get_json()["mensagem"]


def test_tela_tem_o_formulario_dos_modelos():
    raiz = Path(__file__).resolve().parent.parent
    html = (raiz / "src/web/templates/configuracoes.html").read_text(encoding="utf-8")
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'data-config="modelos_parecer"' in html
    assert "conectarFormModelosParecer" in js and "/configuracoes/modelos-parecer" in js
    legado = js[js.index("const CAMPOS_AUTOMACAO"):js.index("const CAMPOS_PADRAO")]
    assert "parecer_fund" not in legado


# ───────────── linha de comando ─────────────

def test_cli_simular(amb, capsys):
    from src.comum import cli
    pf.salvar_modelo("um.docx", _modelo_docx(), ["1º Ano Integral A"])
    assert cli.main(["parecer_fund", "--turma", "1º Ano Integral A", "--teste", "--simular"]) == 0
    assert "gerar_pareceres_fundamental" in capsys.readouterr().out


def test_cli_turma_sem_modelo_da_erro(amb, capsys):
    from src.comum import cli
    assert cli.main(["parecer_fund", "--turma", "1º Ano Integral B", "--simular"]) == 2
    assert "ainda não têm modelo" in capsys.readouterr().err

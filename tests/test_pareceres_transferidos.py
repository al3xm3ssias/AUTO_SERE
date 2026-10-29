"""Pareceres dos transferidos: ler QR, identificar, arquivar, comprimir e enviar (PDFs reais com QR, sem SERE)."""
import asyncio
import io
import json

import pytest

pytest.importorskip("cv2")
pytest.importorskip("qrcode")
pytest.importorskip("reportlab")

from src.comum import configuracao, paths
from src.automacao import pareceres_transferidos as pp

TURMA = "1º Ano Integral A"


def _al(n, cgm, nome, sit="Matriculado", data="05/02/2026"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": "01/01/2015", "Situação": sit, "Data Matricula": data}


def _qr_png(texto):
    import qrcode
    buf = io.BytesIO()
    qrcode.make(texto, box_size=8, border=4).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_com_qr(caminho, nome, turma=TURMA, paginas=2, pesado=False):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(caminho))
    for i in range(paginas - 1):
        c.drawString(100, 700, f"Parecer descritivo — página {i + 1}")
        if pesado and i == 0:
            import numpy as np
            from PIL import Image
            ruido = Image.fromarray(np.random.RandomState(1).randint(0, 255, (1400, 1000, 3), dtype=np.uint8))
            c.drawImage(ImageReader(ruido), 40, 40, 500, 700)
        c.showPage()
    c.drawImage(ImageReader(io.BytesIO(_qr_png(json.dumps({"nome": nome, "turma": turma})))), 200, 300, 200, 200)
    c.showPage()
    c.save()


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    dados = tmp_path / "dados"
    (dados / "TRANSFERENCIAS" / "PROCESSAMENTO DE PARECERES").mkdir(parents=True)
    (dados / "turmas.json").write_text(json.dumps({TURMA: [
        _al(1, "11", "ALICIA SOARES"),
        _al(3, "33", "SAMUEL NASCIMENTO", "Transferido", "20/07/2026"),
        _al(4, "44", "FULANO SILVA", "Transferido", "31/08/2026"),
        _al(31, "44", "FULANO SILVA", "Matriculado", "22/10/2026"),
    ]}, ensure_ascii=False), encoding="utf-8")
    (dados / "transferidos.json").write_text(json.dumps({
        "33": {"nome": "SAMUEL NASCIMENTO", "turma": TURMA, "parecer": {"digitalizado_em": None, "anexado_em": None}},
        "44": {"nome": "FULANO SILVA", "turma": TURMA, "parecer": {"digitalizado_em": None, "anexado_em": None}},
    }, ensure_ascii=False), encoding="utf-8")
    return dados


def _entrada(dados):
    return dados / "TRANSFERENCIAS" / "PROCESSAMENTO DE PARECERES"


def _parecer_arquivado(dados, nome):
    return dados / "TRANSFERENCIAS" / "PARECERES" / TURMA / nome


# ── leitura do QR ────────────────────────────────────────────────────────

@pytest.mark.parametrize("renderizador", ["pdfium", "poppler"])
def test_le_qr_do_pdf_com_cada_renderizador(tmp_path, renderizador):
    d = pp._deps()
    if renderizador == "pdfium" and d.pdfium is None and d.pdf2image is None:
        pytest.skip("sem renderizador")
    if renderizador == "pdfium":
        pytest.importorskip("pypdfium2")
        import pypdfium2
        antes = (d.pdf2image, d.pdfium)
        d.pdf2image, d.pdfium = None, pypdfium2
    else:
        pytest.importorskip("pdf2image")
        import pdf2image
        antes = (d.pdf2image, d.pdfium)
        d.pdf2image, d.poppler = pdf2image, None
    try:
        arq = tmp_path / "scan.pdf"
        _pdf_com_qr(arq, "SAMUEL NASCIMENTO", paginas=3)
        texto = pp.ler_qr_arquivo(arq, log=lambda *_: None)
        assert json.loads(texto) == {"nome": "SAMUEL NASCIMENTO", "turma": TURMA}
    finally:
        d.pdf2image, d.pdfium = antes


def test_le_qr_de_imagem_em_pasta_com_acento(tmp_path):
    pasta = tmp_path / "digitalização"
    pasta.mkdir()
    img = pasta / "parecer.png"
    img.write_bytes(_qr_png(json.dumps({"nome": "ANNA", "turma": TURMA})))
    assert json.loads(pp.ler_qr_arquivo(img, log=lambda *_: None))["nome"] == "ANNA"


def test_pdf_sem_qr_devolve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "DPIS_PDF", (100,))                     # só para o teste ser rápido
    from reportlab.pdfgen import canvas
    arq = tmp_path / "vazio.pdf"
    c = canvas.Canvas(str(arq)); c.drawString(100, 700, "sem qr"); c.save()
    assert pp.ler_qr_arquivo(arq, log=lambda *_: None) is None


# ── identificação ────────────────────────────────────────────────────────

def test_turma_do_qr_vira_a_chave_do_json():
    turmas = {TURMA: [], "mapeamento": {}}
    assert pp.resolver_turma(turmas, "1º ANO A") == TURMA
    assert pp.resolver_turma(turmas, "1 ano a") == TURMA
    assert pp.resolver_turma(turmas, TURMA) == TURMA
    assert pp.resolver_turma(turmas, "9º Ano Z") is None


def test_identificacao_prefere_o_registro_transferido(ambiente):
    turmas = json.loads((ambiente / "turmas.json").read_text(encoding="utf-8"))
    ident, motivo = pp.identificar_aluno(turmas, "Fulano Silva", "1º ANO A")
    assert (ident.numero, ident.cgm, motivo) == (4, "44", "")                # chamada 4 (transferido), não 31


def test_identificacao_com_erros(ambiente):
    turmas = json.loads((ambiente / "turmas.json").read_text(encoding="utf-8"))
    assert "turma" in pp.identificar_aluno(turmas, "X", "9º Ano Z")[1]
    assert "aluno" in pp.identificar_aluno(turmas, "NINGUEM DA SILVA", TURMA)[1]


def test_nome_do_arquivo_limpa_caracteres_invalidos():
    assert pp.nome_do_arquivo(3, "A/B: C", ".pdf") == "03-A_B_ C.pdf"


# ── rotina ───────────────────────────────────────────────────────────────

def test_simulacao_nao_altera_nada(ambiente, capsys):
    _pdf_com_qr(_entrada(ambiente) / "a.pdf", "SAMUEL NASCIMENTO")
    antes = (ambiente / "transferidos.json").read_text(encoding="utf-8")
    r = pp.processar_pareceres_da_pasta(simulacao=True, dados_dir=ambiente)
    assert len(r.processados) == 1 and r.erros == []
    assert (_entrada(ambiente) / "a.pdf").exists()                            # continua na origem
    assert not (ambiente / "TRANSFERENCIAS" / "PARECERES").exists()           # nada criado
    assert (ambiente / "transferidos.json").read_text(encoding="utf-8") == antes
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "03-SAMUEL NASCIMENTO.pdf" in saida and "cabe no limite" in saida


def test_processa_arquiva_marca_e_tira_da_origem(ambiente):
    _pdf_com_qr(_entrada(ambiente) / "scan1.pdf", "SAMUEL NASCIMENTO")
    r = pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)
    assert len(r.processados) == 1 and r.erros == [] and r.sem_registro == []
    assert _parecer_arquivado(ambiente, "03-SAMUEL NASCIMENTO.pdf").exists()
    assert not (_entrada(ambiente) / "scan1.pdf").exists()
    controle = json.loads((ambiente / "transferidos.json").read_text(encoding="utf-8"))
    assert controle["33"]["parecer"]["digitalizado_em"] and controle["44"]["parecer"]["digitalizado_em"] is None


def test_aluno_que_retornou_usa_a_chamada_da_transferencia(ambiente):
    _pdf_com_qr(_entrada(ambiente) / "f.pdf", "FULANO SILVA")
    pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)
    assert _parecer_arquivado(ambiente, "04-FULANO SILVA.pdf").exists()


def test_comprime_quando_passa_do_limite_e_guarda_o_original(ambiente):
    pytest.importorskip("pypdf")
    _pdf_com_qr(_entrada(ambiente) / "pesado.pdf", "SAMUEL NASCIMENTO", paginas=3, pesado=True)
    tamanho = (_entrada(ambiente) / "pesado.pdf").stat().st_size
    assert tamanho > 1_000_000
    r = pp.processar_pareceres_da_pasta(dados_dir=ambiente, limite_mb=0.5, log=lambda *_: None)
    final = _parecer_arquivado(ambiente, "03-SAMUEL NASCIMENTO.pdf")
    assert r.comprimidos == 1 and final.stat().st_size < tamanho * 0.9
    original = ambiente / "ORIGINAIS_ANTES_DA_COMPRESSAO" / "PARECERES" / TURMA / "03-SAMUEL NASCIMENTO.pdf"
    assert original.exists() and original.stat().st_size == tamanho                 # o original ficou guardado
    assert not list((ambiente / "TRANSFERENCIAS").rglob("*.tmp"))
    assert not list((ambiente / "TRANSFERENCIAS").rglob("*compressao.tmp"))


def test_erros_mantem_o_arquivo_na_origem(ambiente, monkeypatch):
    monkeypatch.setattr(pp, "DPIS_PDF", (100,))                     # só para o teste ser rápido
    from reportlab.pdfgen import canvas
    sem_qr = _entrada(ambiente) / "sem_qr.pdf"
    c = canvas.Canvas(str(sem_qr)); c.drawString(100, 700, "x"); c.save()
    _pdf_com_qr(_entrada(ambiente) / "desconhecido.pdf", "NINGUEM DA SILVA")
    r = pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)
    assert len(r.processados) == 0 and {e[0] for e in r.erros} == {"sem_qr.pdf", "desconhecido.pdf"}
    assert sem_qr.exists() and (_entrada(ambiente) / "desconhecido.pdf").exists()


def test_aluno_fora_do_transferidos_json_e_avisado_mas_arquivado(ambiente):
    _pdf_com_qr(_entrada(ambiente) / "a.pdf", "ALICIA SOARES")
    r = pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)
    assert r.sem_registro == ["11"] and len(r.processados) == 1
    assert _parecer_arquivado(ambiente, "01-ALICIA SOARES.pdf").exists()


def test_nao_sobrescreve_parecer_ja_arquivado(ambiente):
    for nome in ("1.pdf", "2.pdf"):
        _pdf_com_qr(_entrada(ambiente) / nome, "SAMUEL NASCIMENTO")
    pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)
    assert len(list((ambiente / "TRANSFERENCIAS" / "PARECERES" / TURMA).glob("*.pdf"))) == 2


def test_modo_teste_processa_so_o_primeiro(ambiente):
    _pdf_com_qr(_entrada(ambiente) / "a.pdf", "SAMUEL NASCIMENTO")
    _pdf_com_qr(_entrada(ambiente) / "b.pdf", "FULANO SILVA")
    r = pp.processar_pareceres_da_pasta(dados_dir=ambiente, modo_teste=True, log=lambda *_: None)
    assert len(r.processados) == 1 and len(list(_entrada(ambiente).glob("*.pdf"))) == 1


def test_pasta_vazia(ambiente):
    r = pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)
    assert r.processados == [] and r.erros == []


def test_sem_turmas_json(ambiente):
    (ambiente / "turmas.json").unlink()
    _pdf_com_qr(_entrada(ambiente) / "a.pdf", "SAMUEL NASCIMENTO")
    with pytest.raises(FileNotFoundError, match="Turmas"):
        pp.processar_pareceres_da_pasta(dados_dir=ambiente, log=lambda *_: None)


# ── rotina completa (com envio) ──────────────────────────────────────────

def test_rotina_completa_envia_so_pareceres(ambiente, monkeypatch):
    from src.automacao import sere_2026
    chamadas = []

    async def falso(**kw):
        chamadas.append(kw)
    monkeypatch.setattr(sere_2026, "modo_transferidos", falso)
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: ambiente)
    _pdf_com_qr(_entrada(ambiente) / "a.pdf", "SAMUEL NASCIMENTO")
    asyncio.run(pp.executar_pareceres_transferidos())
    assert chamadas == [{"modo_teste": False, "tipos": ("parecer",), "simulacao": False}]
    assert _parecer_arquivado(ambiente, "03-SAMUEL NASCIMENTO.pdf").exists()


def test_rotina_simulada_pede_simulacao_do_envio(ambiente, monkeypatch):
    from src.automacao import sere_2026
    chamadas = []

    async def falso(**kw):
        chamadas.append(kw)
    monkeypatch.setattr(sere_2026, "modo_transferidos", falso)
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: ambiente)
    _pdf_com_qr(_entrada(ambiente) / "a.pdf", "SAMUEL NASCIMENTO")
    asyncio.run(pp.executar_pareceres_transferidos(simulacao=True))
    assert chamadas[0]["simulacao"] is True
    assert (_entrada(ambiente) / "a.pdf").exists()


def test_sem_enviar_nao_chama_o_sere(ambiente, monkeypatch):
    from src.automacao import sere_2026

    async def falso(**kw):
        raise AssertionError("não deveria enviar")
    monkeypatch.setattr(sere_2026, "modo_transferidos", falso)
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: ambiente)
    asyncio.run(pp.executar_pareceres_transferidos(enviar=False))


def test_ampliacao_tem_limite_de_tamanho():
    import numpy as np
    grande = np.zeros((3000, 2400, 3), dtype=np.uint8)               # A4 a ~300 DPI: nenhuma escala cabe
    assert pp._variantes_escaladas(grande) == []
    pequena = np.zeros((1000, 800, 3), dtype=np.uint8)               # 1000×1,5/2/3 = 1500/2000/3000 → as três cabem
    assert len(pp._variantes_escaladas(pequena)) == 18


# ── turma do QR sem assumir nomes de uma escola ──────────────────────────

CHAVES = {"3º Ano Matutino A": [], "3º Ano Matutino B": [], "INFANTIL 4 Vespertino A": [], "mapeamento": {}}


def test_turma_por_palavras_sem_a_palavra_integral():
    assert pp.resolver_turma(CHAVES, "3º ANO B") == "3º Ano Matutino B"
    assert pp.resolver_turma(CHAVES, "3 ano a") == "3º Ano Matutino A"


def test_turma_por_palavras_aceita_abreviatura_de_3_letras():
    assert pp.resolver_turma(CHAVES, "INF 4 A") == "INFANTIL 4 Vespertino A"


def test_turma_ambigua_nao_adivinha():
    assert pp.resolver_turma(CHAVES, "3º ANO") is None                 # A ou B?


def test_turma_letra_solta_nao_casa_com_prefixo_de_outra_palavra():
    assert pp.resolver_turma({"3º Ano Matutino A": []}, "3º ANO B") is None


def test_mapeamento_extra_vem_da_configuracao(ambiente):
    chaves = {"Turma Especial 7": []}
    assert pp.resolver_turma(chaves, "SALA DO MEIO") is None
    (ambiente.parent / "config" / "config_usuario.json").write_text(
        json.dumps({"mapeamento_turmas_qr": {"sala do meio": "Turma Especial 7"}}), encoding="utf-8")
    assert pp.resolver_turma(chaves, "SALA DO MEIO") == "Turma Especial 7"


def test_mapeamento_embutido_continua_valendo():
    assert pp.resolver_turma({"1º Ano Integral A": []}, "1º ANO A") == "1º Ano Integral A"

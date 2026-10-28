"""Compressão de documentos: motor (src.comum.compressao), plano do registro e a tela."""
import io
import json
import os
import subprocess
import sys

import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from src.comum import compressao as c
from src.comum.execucao_gui import CancelamentoSolicitado

DATA_ANTIGA = 1_700_000_000


def _ruido(w=1800, h=2400):
    """Imagem de ruído: comprime mal, como um escaneamento de verdade."""
    return Image.effect_noise((w, h), 40).convert("RGB")


def _jpg(caminho, w=1800, h=2400):
    _ruido(w, h).save(caminho, "JPEG", quality=95)


def _png(caminho):
    _ruido().save(caminho, "PNG")


def _pdf(caminho, paginas=2):
    cv = canvas.Canvas(str(caminho), pagesize=(595, 842))
    for _ in range(paginas):
        b = io.BytesIO()
        _ruido().save(b, "JPEG", quality=92)
        b.seek(0)
        cv.drawImage(ImageReader(b), 0, 0, 595, 842)
        cv.showPage()
    cv.save()


@pytest.fixture()
def pasta(tmp_path):
    raiz = tmp_path / "DIGITALIZAÇÃO"
    (raiz / "5º Ano Integral A" / "1 - Ana").mkdir(parents=True)
    (raiz / "3º Ano Integral B" / "1 - Caio").mkdir(parents=True)
    (raiz / "TRANSFERENCIAS" / "PARECERES").mkdir(parents=True)
    (raiz / "BACKUP-SEGURANCA").mkdir()
    return raiz


def _rodar(pasta, tmp_path, **kw):
    kw.setdefault("log", lambda _linha: None)
    return c.comprimir_documentos(raiz=pasta, pasta_originais=tmp_path / "ORIG", registro_json=tmp_path / "registro.json", **kw)


# ───────────── o que é comprimido ─────────────

def test_limite_do_sere_e_o_mesmo_do_upload():
    from src.comum.sere_upload import LIMITE_ARQUIVO_MB_PADRAO
    assert c.LIMITE_SERE_MB == LIMITE_ARQUIVO_MB_PADRAO


def test_jpg_png_e_pdf_grandes_encolhem_com_mesmo_nome_e_data_e_o_original_fica_guardado(pasta, tmp_path):
    aluno = pasta / "5º Ano Integral A" / "1 - Ana"
    _jpg(aluno / "Foto.jpg")
    _png(pasta / "TRANSFERENCIAS" / "PARECERES" / "parecer.png")
    _pdf(aluno / "RG.pdf")
    antes = {p: p.stat().st_size for p in pasta.rglob("*") if p.is_file()}
    for p in antes:
        os.utime(p, (DATA_ANTIGA, DATA_ANTIGA))

    r = _rodar(pasta, tmp_path)

    assert r.comprimidos == 3 and r.erros == 0 and r.economia > 0
    for p, tamanho in antes.items():
        assert p.exists() and p.stat().st_size < tamanho * 0.9                  # mesmo caminho, bem menor
        assert int(p.stat().st_mtime) == DATA_ANTIGA                           # a data não muda (corte de transferidos)
        guardado = tmp_path / "ORIG" / p.relative_to(pasta)
        assert guardado.stat().st_size == tamanho                              # original intacto, fora da pasta de digitalização
    assert max(p.stat().st_size for p in antes) / 1024 / 1024 < 100            # (sanidade do teste)
    assert len(__import__("pypdf").PdfReader(str(aluno / "RG.pdf")).pages) == 2
    assert Image.open(aluno / "Foto.jpg").format == "JPEG" and Image.open(pasta / "TRANSFERENCIAS" / "PARECERES" / "parecer.png").format == "PNG"


def test_arquivo_que_ja_cabe_nao_e_tocado_e_limite_zero_comprime_todos(pasta, tmp_path):
    pequeno = pasta / "5º Ano Integral A" / "1 - Ana" / "pequeno.jpg"
    _jpg(pequeno, 600, 800)                                                      # ~ centenas de KB
    original = pequeno.read_bytes()
    r = _rodar(pasta, tmp_path)
    assert r.ja_cabem == 1 and r.comprimidos == 0 and pequeno.read_bytes() == original
    r = _rodar(pasta, tmp_path, limite_mb=0)
    assert r.comprimidos == 1 and pequeno.stat().st_size < len(original)


def test_pastas_backup_e_a_de_originais_nunca_sao_tocadas_e_so_pdf_jpg_png_entram(pasta, tmp_path):
    _jpg(pasta / "BACKUP-SEGURANCA" / "velho.jpg")
    (pasta / "ORIGINAIS_ANTES_DA_COMPRESSAO").mkdir()
    _jpg(pasta / "ORIGINAIS_ANTES_DA_COMPRESSAO" / "x.jpg")
    (pasta / "5º Ano Integral A" / "1 - Ana" / "notas.txt").write_text("não é documento")
    r = _rodar(pasta, tmp_path)
    assert r.encontrados == 0 and r.comprimidos == 0
    assert (pasta / "BACKUP-SEGURANCA" / "velho.jpg").stat().st_size > 1_500_000


# ───────────── registro: não repete trabalho ─────────────

def test_segunda_execucao_nao_refaz_e_arquivo_novo_com_mesmo_nome_volta_a_ser_tratado(pasta, tmp_path):
    foto = pasta / "5º Ano Integral A" / "1 - Ana" / "Foto.jpg"
    _jpg(foto)
    assert _rodar(pasta, tmp_path, limite_mb=0.2).comprimidos == 1
    ja = foto.stat().st_size
    r = _rodar(pasta, tmp_path, limite_mb=0.2)
    assert r.comprimidos == 0 and r.ja_processados == 1 and foto.stat().st_size == ja       # nunca recomprime em cima de si mesmo
    _jpg(foto)                                                                              # a pessoa escaneou de novo
    assert _rodar(pasta, tmp_path, limite_mb=0.2).comprimidos == 1


def test_o_que_nao_rende_fica_como_esta_e_registrado(pasta, tmp_path):
    texto = pasta / "TRANSFERENCIAS" / "PARECERES" / "so_texto.pdf"
    cv = canvas.Canvas(str(texto))
    cv.drawString(100, 700, "Parecer sem nenhuma imagem")
    cv.save()
    original = texto.read_bytes()
    r = _rodar(pasta, tmp_path, limite_mb=0)
    assert r.sem_ganho == 1 and r.comprimidos == 0 and texto.read_bytes() == original
    assert json.loads((tmp_path / "registro.json").read_text(encoding="utf-8"))["TRANSFERENCIAS/PARECERES/so_texto.pdf"]["resultado"] == "sem_ganho"
    assert _rodar(pasta, tmp_path, limite_mb=0).ja_processados == 1


# ───────────── só calcular, teste, turma, originais ─────────────

def test_somente_calcular_nao_altera_nada_nem_grava_registro(pasta, tmp_path):
    foto = pasta / "5º Ano Integral A" / "1 - Ana" / "Foto.jpg"
    _jpg(foto)
    original = foto.read_bytes()
    r = _rodar(pasta, tmp_path, somente_calcular=True)
    assert r.comprimidos == 1 and r.economia > 0
    assert foto.read_bytes() == original and not (tmp_path / "ORIG").exists() and not (tmp_path / "registro.json").exists()
    assert not list(pasta.rglob("*" + c.SUFIXO_TEMPORARIO))


def test_modo_teste_processa_so_o_primeiro(pasta, tmp_path):
    _jpg(pasta / "3º Ano Integral B" / "1 - Caio" / "a.jpg")
    _jpg(pasta / "5º Ano Integral A" / "1 - Ana" / "b.jpg")
    assert _rodar(pasta, tmp_path, modo_teste=True).comprimidos == 1


def test_turma_limita_a_pasta_e_turma_inexistente_so_avisa(pasta, tmp_path):
    _jpg(pasta / "3º Ano Integral B" / "1 - Caio" / "a.jpg")
    _jpg(pasta / "5º Ano Integral A" / "1 - Ana" / "b.jpg")
    _png(pasta / "TRANSFERENCIAS" / "PARECERES" / "p.png")
    avisos = []
    r = _rodar(pasta, tmp_path, turmas=["5º Ano Integral A", "9º Ano"], log=avisos.append)
    assert r.comprimidos == 1 and r.turmas_nao_encontradas == ["9º Ano"] and any("9º Ano" in a for a in avisos)
    assert (pasta / "3º Ano Integral B" / "1 - Caio" / "a.jpg").stat().st_size > 1_500_000       # outras turmas e TRANSFERENCIAS ficam
    r = _rodar(pasta, tmp_path, turmas=["9º Ano"])
    assert r.encontrados == 0


def test_nao_guardar_originais_nao_cria_a_pasta(pasta, tmp_path):
    _jpg(pasta / "5º Ano Integral A" / "1 - Ana" / "Foto.jpg")
    assert _rodar(pasta, tmp_path, guardar_originais=False).comprimidos == 1
    assert not (tmp_path / "ORIG").exists()


def test_pasta_de_digitalizacao_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        _rodar(tmp_path / "nao_existe", tmp_path)


# ───────────── nada se perde quando algo dá errado ─────────────

def test_arquivos_corrompidos_viram_aviso_e_o_original_fica_intacto(pasta, tmp_path):
    ruim_pdf = pasta / "5º Ano Integral A" / "1 - Ana" / "quebrado.pdf"
    ruim_jpg = pasta / "5º Ano Integral A" / "1 - Ana" / "quebrada.jpg"
    ruim_pdf.write_bytes(b"%PDF-1.4 isto nao e um pdf de verdade" * 60000)
    ruim_jpg.write_bytes(b"isto nao e uma imagem" * 120000)
    a, b = ruim_pdf.read_bytes(), ruim_jpg.read_bytes()
    r = _rodar(pasta, tmp_path)
    assert r.erros == 2 and r.comprimidos == 0
    assert ruim_pdf.read_bytes() == a and ruim_jpg.read_bytes() == b
    assert not list(pasta.rglob("*" + c.SUFIXO_TEMPORARIO))


def test_se_a_copia_do_original_falha_nada_e_substituido(pasta, tmp_path, monkeypatch):
    foto = pasta / "5º Ano Integral A" / "1 - Ana" / "Foto.jpg"
    _jpg(foto)
    original = foto.read_bytes()

    def falha(*_a, **_k):
        raise c.CompressaoImpossivel("disco cheio")
    monkeypatch.setattr(c, "_copiar_original", falha)
    r = _rodar(pasta, tmp_path)
    assert r.erros == 1 and foto.read_bytes() == original and not list(pasta.rglob("*" + c.SUFIXO_TEMPORARIO))


def test_pdf_protegido_por_senha_e_pulado(pasta, tmp_path):
    import pypdf
    origem = pasta / "5º Ano Integral A" / "1 - Ana" / "origem.pdf"
    _pdf(origem, 1)
    escritor = pypdf.PdfWriter(clone_from=str(origem))
    escritor.encrypt("segredo")
    protegido = pasta / "5º Ano Integral A" / "1 - Ana" / "protegido.pdf"
    with open(protegido, "wb") as f:
        escritor.write(f)
    origem.unlink()
    original = protegido.read_bytes()
    r = _rodar(pasta, tmp_path, limite_mb=0)
    assert r.erros == 1 and protegido.read_bytes() == original


def test_cancelar_para_entre_arquivos_e_guarda_o_que_ja_foi_feito(pasta, tmp_path, monkeypatch):
    a = pasta / "3º Ano Integral B" / "1 - Caio" / "a.jpg"
    b = pasta / "5º Ano Integral A" / "1 - Ana" / "b.jpg"
    _jpg(a)
    _jpg(b)
    chamadas = []

    def cancela_no_segundo():
        chamadas.append(1)
        if len(chamadas) == 2:
            raise CancelamentoSolicitado()
    monkeypatch.setattr(c, "verificar_cancelamento", cancela_no_segundo)
    with pytest.raises(CancelamentoSolicitado):
        _rodar(pasta, tmp_path)
    assert a.stat().st_size < 1_500_000 < b.stat().st_size                       # o 1º foi feito, o 2º não
    assert "3º Ano Integral B/1 - Caio/a.jpg" in json.loads((tmp_path / "registro.json").read_text(encoding="utf-8"))


def test_temporarios_de_execucao_interrompida_sao_limpos(pasta, tmp_path):
    sobra = pasta / "5º Ano Integral A" / "1 - Ana" / ("Foto.jpg" + c.SUFIXO_TEMPORARIO)
    sobra.write_bytes(b"x")
    _rodar(pasta, tmp_path)
    assert not sobra.exists()


# ───────────── componente de PDF (instalação automática) ─────────────

def test_pypdf_ausente_e_instalado_sozinho_e_falha_vira_mensagem_clara(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)                              # import pypdf → ImportError
    pedidos = []

    def pip(cmd, **_k):
        pedidos.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "sem rede")
    monkeypatch.setattr(subprocess, "run", pip)
    with pytest.raises(c.CompressaoImpossivel, match="sem internet"):
        c._carregar_pypdf(lambda _l: None)
    assert pedidos == [[sys.executable, "-m", "pip", "install", f"pypdf=={c.VERSAO_PYPDF}"]]    # versão fixada, mesmo Python do sistema


# ───────────── plano do registro e tela ─────────────

@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    from src.web.api import rotas
    from src.web.app import create_app
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps({"5º Ano Integral A": [{"CGM": "5000000001", "Nome": "Duda", "Situação": "Matriculado"}]}), encoding="utf-8")
    planos = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: planos.append((chave, plano)))
    return create_app().test_client(), planos


def _post(cliente, **payload):
    return cliente.post("/web/api/automacoes/comprimir/executar", json=payload)


def test_plano_padrao_comprime_a_pasta_inteira_no_limite_do_sere_guardando_originais(ctx):
    cliente, planos = ctx
    assert _post(cliente).status_code == 200
    chave, plano = planos[0]
    assert chave == "comprimir" and plano.tipo == "sync"
    assert plano.kwargs == {"turmas": [], "limite_mb": c.LIMITE_SERE_MB, "guardar_originais": True,
                            "somente_calcular": False, "modo_teste": False}


def test_plano_repassa_as_escolhas_da_tela(ctx):
    cliente, planos = ctx
    _post(cliente, turmas=["5º Ano Integral A"], limite_mb="2,5", descartar_originais=True, somente_calcular=True, modo_teste=True)
    assert planos[0][1].kwargs == {"turmas": ["5º Ano Integral A"], "limite_mb": 2.5, "guardar_originais": False,
                                   "somente_calcular": True, "modo_teste": True}
    _post(cliente, limite_mb="0")
    assert planos[1][1].kwargs["limite_mb"] == 0


@pytest.mark.parametrize("ruim", ["abc", "-1", "501"])
def test_limite_invalido_e_recusado_com_mensagem(ctx, ruim):
    cliente, planos = ctx
    r = _post(cliente, limite_mb=ruim)
    assert r.status_code == 400 and "MB" in r.get_json()["mensagem"] and planos == []


def test_comprimir_nao_responde_mais_nao_implementada_e_pede_confirmacao(ctx):
    cliente, _ = ctx
    info = cliente.get("/web/api/automacoes/comprimir/componentes").get_json()
    assert info["registrado"] and info["confirmar"] and "SUBSTITUI" in info["aviso_confirmacao"]
    assert info["recursos"] == ["turma", "teste"]
    assert [e["nome"] for e in info["extras"]] == ["limite_mb", "somente_calcular", "descartar_originais"]
    lista = {a["chave"]: a for a in cliente.get("/web/api/automacoes/lista").get_json()["itens"]}
    assert lista["comprimir"]["recursos"] == ["turma", "teste"] and "1,5 MB" in lista["comprimir"]["descricao"]

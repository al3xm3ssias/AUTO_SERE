"""
Ponta a ponta (sem SERE): coleta de turmas → fila → transferidos.json → plano de geração → pareceres → envio.
O que depende do navegador (emitir/assinar/baixar e o envio de verdade) é substituído pelo estado que ele deixaria.
"""
import asyncio
import io
import json

import pytest

pytest.importorskip("cv2")
pytest.importorskip("qrcode")
pytest.importorskip("reportlab")

from src.comum import configuracao, paths
from src.automacao import fila_transferidos as ft
from src.automacao import pareceres_transferidos as pp
from src.automacao import processo_transferidos as pr
from src.automacao import sere_2026 as s

TURMA = "1º Ano Integral A"


def _al(n, cgm, nome, sit="Matriculado", data="05/02/2026", nasc="01/01/2015"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Situação": sit, "Data Matricula": data}


def _pdf_com_qr(caminho, nome):
    import qrcode
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    qrcode.make(json.dumps({"nome": nome, "turma": TURMA}), box_size=8, border=4).save(buf, format="PNG")
    c = canvas.Canvas(str(caminho))
    c.drawString(100, 700, "Parecer descritivo")
    c.showPage()
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 200, 300, 200, 200)
    c.showPage()
    c.save()


def test_o_fluxo_inteiro(tmp_path, monkeypatch, capsys):
    # ── ambiente isolado ────────────────────────────────────────────────
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    dados = tmp_path / "dados"
    dados.mkdir()
    monkeypatch.setattr(pr, "_DADOS", dados)
    monkeypatch.setattr(pr, "JSON_TURMAS", dados / "turmas.json")
    monkeypatch.setattr(pr, "JSON_TRANSFERIDOS", dados / "transferidos.json")
    monkeypatch.setattr(s, "PATH_TRANSFERIDOS", dados / "transferidos.json")
    monkeypatch.setattr(s, "pasta_digitalizacao_configurada", lambda: False)
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    configuracao.definir_data_corte_transferidos("22/06/2026")

    # ── 1. a coleta de turmas (o que o turmas.py grava) e o gancho que registra a fila ─────────────
    turmas = {TURMA: [
        _al(1, "11", "ALICIA SOARES"),
        _al(2, "22", "ANNA DIAS", "Transferido", "13/05/2026"),                  # antes do corte: feito à mão
        _al(3, "33", "SAMUEL NASCIMENTO", "Transferido", "20/07/2026"),           # o único a processar
        _al(4, "44", "FULANO SILVA", "Transferido", "31/08/2026"),
        _al(31, "44", "FULANO SILVA", "Matriculado", "22/10/2026"),               # voltou: não se refaz
    ]}
    (dados / "turmas.json").write_text(json.dumps(turmas, ensure_ascii=False), encoding="utf-8")
    assert ft.registrar_fila_sem_falhar(turmas, dados) is not None

    # ── 2. a fila e o controle ─────────────────────────────────────────
    fila = json.loads((dados / "fila_transferidos.json").read_text(encoding="utf-8"))
    assert {c: a["situacao_fila"] for c, a in fila["alunos"].items()} == {
        "22": "antes_do_corte", "33": "processar", "44": "retornou"}
    assert set(json.loads((dados / "transferidos.json").read_text(encoding="utf-8"))) == {"33"}

    # ── 3. simulação da geração: só o Samuel, sem abrir o SERE nem alterar nada ─────────────────────
    antes = {p.name: p.read_bytes() for p in dados.iterdir() if p.is_file()}
    capsys.readouterr()
    asyncio.run(pr.processar_transferencias(simulacao=True))
    saida = capsys.readouterr().out
    assert "SAMUEL NASCIMENTO" in saida and "FULANO" not in saida and "ANNA" not in saida
    assert {p.name: p.read_bytes() for p in dados.iterdir() if p.is_file()} == antes
    assert not (dados / "TRANSFERENCIAS").exists()

    # ── 4. o que a geração deixaria: documentos assinados e baixados nas pastas novas ────────────────
    controle = json.loads((dados / "transferidos.json").read_text(encoding="utf-8"))
    for doc in ("guia", "historico"):
        controle["33"][doc].update(emitido_em="2026-08-10T10:30:00", assinado_secretario="2026-08-10T10:40:00",
                                   assinado_diretor="2026-08-11T09:00:00")
    (dados / "transferidos.json").write_text(json.dumps(controle), encoding="utf-8")
    for pasta, nome in (("GUIA DE TRANSFERENCIA", "SAMUEL NASCIMENTO.pdf"), ("HISTORICO", "SAMUEL NASCIMENTO.pdf")):
        arq = dados / "TRANSFERENCIAS" / pasta / TURMA / nome
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(b"%PDF-1.4")
    assert pr.carregar_alunos() == []                                              # completo: não reprocessa

    # ── 5. parecer digitalizado → processado (QR) → PARECERES ───────────────────────────────────────
    entrada = dados / "TRANSFERENCIAS" / "PROCESSAMENTO DE PARECERES"
    entrada.mkdir(parents=True, exist_ok=True)
    _pdf_com_qr(entrada / "scan_samuel.pdf", "SAMUEL NASCIMENTO")
    _pdf_com_qr(entrada / "scan_fulano.pdf", "FULANO SILVA")
    r = pp.processar_pareceres_da_pasta(dados_dir=dados, log=lambda *_: None)
    assert len(r.processados) == 2 and r.sem_registro == ["44"]                    # Fulano arquivado, mas não segue ao SERE
    assert (dados / "TRANSFERENCIAS" / "PARECERES" / TURMA / "03-SAMUEL NASCIMENTO.pdf").exists()
    assert (dados / "TRANSFERENCIAS" / "PARECERES" / TURMA / "04-FULANO SILVA.pdf").exists()
    assert list(entrada.glob("*.pdf")) == []                                       # saiu de PROCESSAMENTO

    # ── 6. envio (simulado): guia, histórico e parecer do Samuel — e só dele ────────────────────────
    capsys.readouterr()
    asyncio.run(s.modo_transferidos(simulacao=True))
    saida = capsys.readouterr().out
    assert "Seriam enviados 3 arquivo(s)" in saida and "FULANO" not in saida
    assert "Guia de Transferência" in saida and "Histórico" in saida and "Parecer Descritivo" in saida

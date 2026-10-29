"""
Documento da NOSSA escola × documento de outra escola.

A listagem do SERE mostra também documentos de transferência de outras escolas. Regra do usuário: se já há um
documento emitido por esta escola (bate data e tipo), não sobrescreve; se é de outra escola, faz o processo todo.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.comum import configuracao, paths
from src.automacao import processo_transferidos as pr
from src.automacao import sere_2026 as s
from src.automacao.processo_transferidos import AcaoDecidida, Aluno, DocSERE, TipoDoc

CORTE = datetime(2026, 6, 22)
EMISSAO = datetime(2026, 8, 10, 10, 30)                      # quando ESTA escola emitiu (registrado em transferidos.json)
ALUNO = Aluno(cgm="33", nome="SAMUEL NASCIMENTO", turma="1º Ano Integral A")


def _doc(cod, quando, sec=True, dire=True):
    return DocSERE(cod=cod, texto="", data=quando, assinado_secretario=sec, assinado_diretor=dire)


@pytest.fixture(autouse=True)
def _classes_atuais_do_modulo():
    """
    Outros testes (salvar credenciais pela API) recarregam processo_transferidos com importlib.reload: o módulo é o
    mesmo objeto, mas as classes (AcaoDecidida, TipoDoc...) são redefinidas. Se este arquivo guardasse as do momento da
    coleta, `acao == AcaoDecidida.X` daria falso mesmo com o mesmo nome. Por isso, antes de cada teste, os nomes são
    relidos do módulo.
    """
    for nome in ("AcaoDecidida", "Aluno", "DocSERE", "TipoDoc"):
        globals()[nome] = getattr(pr, nome)
    globals()["ALUNO"] = Aluno(cgm="33", nome="SAMUEL NASCIMENTO", turma="1º Ano Integral A")


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    dados = tmp_path / "dados"
    dados.mkdir()
    monkeypatch.setattr(pr, "_DADOS", dados)
    monkeypatch.setattr(pr, "JSON_TRANSFERIDOS", dados / "transferidos.json")
    configuracao.definir_data_corte_transferidos("22/06/2026")
    return dados


def _gravar_registro(dados, tipo="historico", **campos):
    caminho = dados / "transferidos.json"
    atual = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    reg = atual.setdefault("33", {"nome": ALUNO.nome, "turma": ALUNO.turma})
    reg.setdefault(tipo, {"emitido_em": None, "assinado_secretario": None, "assinado_diretor": None, "anexado_em": None})
    reg[tipo].update(campos)
    caminho.write_text(json.dumps(atual), encoding="utf-8")


def _info(emitido_em=EMISSAO):
    return pr.InfoDocJSON(emitido_em=emitido_em, assinado_secretario=None, assinado_diretor=None, anexado_em=None)


# ══ quais documentos são nossos ═══════════════════════════════════════════

def test_sem_emissao_registrada_nenhum_documento_e_nosso(ambiente):
    assert pr.docs_da_escola([_doc("1", EMISSAO)], None, CORTE) == []


def test_documento_do_mesmo_dia_e_nosso_e_o_mais_proximo_vem_primeiro(ambiente):
    longe, perto = _doc("longe", EMISSAO + timedelta(hours=5)), _doc("perto", EMISSAO + timedelta(minutes=1))
    assert [d.cod for d in pr.docs_da_escola([longe, perto], EMISSAO, CORTE)] == ["perto", "longe"]


def test_documento_de_outro_dia_nao_e_nosso(ambiente):
    outra_escola = _doc("x", EMISSAO - timedelta(days=40))
    assert pr.docs_da_escola([outra_escola], EMISSAO, CORTE) == []


def test_virada_do_dia_ainda_conta(ambiente):
    emitido = datetime(2026, 8, 11, 0, 10)                          # registrado 00:10; o SERE mostra 23:55 do dia anterior
    assert [d.cod for d in pr.docs_da_escola([_doc("a", datetime(2026, 8, 10, 23, 55))], emitido, CORTE)] == ["a"]


def test_documento_anterior_a_data_de_corte_nunca_e_nosso(ambiente):
    antigo = datetime(2026, 3, 1, 9, 0)
    assert pr.docs_da_escola([_doc("a", antigo)], antigo, CORTE) == []


# ══ emissão: o que fazer com o que o SERE já mostra ═══════════════════════

def test_documento_de_outra_escola_nao_impede_de_gerar(ambiente):
    """Há um histórico válido (2 assinaturas) depois do corte, mas esta escola nunca emitiu: faz o processo todo."""
    de_fora = _doc("outra", datetime(2026, 7, 1, 9, 0))
    acao, doc, motivo = pr.decidir_acao_emissao(ALUNO, TipoDoc.HISTORICO, [de_fora], _info(None))
    assert acao == AcaoDecidida.GERAR_NOVO and doc is None and "outra origem" in motivo


def test_documento_nosso_e_valido_nao_sobrescreve(ambiente):
    nosso = _doc("nosso", EMISSAO + timedelta(minutes=1))
    acao, doc, _ = pr.decidir_acao_emissao(ALUNO, TipoDoc.HISTORICO, [nosso], _info())
    assert (acao, doc.cod) == (AcaoDecidida.JA_EXISTE, "nosso")


def test_aguardando_o_diretor_nao_gera_outro_a_cada_execucao(ambiente):
    """Regressão: com a assinatura da diretora pendente, cada execução emitia mais um documento."""
    pendente = _doc("pendente", EMISSAO + timedelta(minutes=1), sec=True, dire=False)
    acao, doc, motivo = pr.decidir_acao_emissao(ALUNO, TipoDoc.GUIA, [pendente], _info())
    assert (acao, doc.cod) == (AcaoDecidida.JA_EXISTE, "pendente") and "Diretor" in motivo


def test_nosso_sem_assinatura_do_secretario_so_assina(ambiente):
    sem_sec = _doc("novo", EMISSAO + timedelta(minutes=1), sec=False, dire=False)
    acao, doc, _ = pr.decidir_acao_emissao(ALUNO, TipoDoc.GUIA, [sem_sec], _info())
    assert (acao, doc.cod) == (AcaoDecidida.BAIXAR, "novo")


def test_emissao_registrada_mas_documento_sumiu_gera_de_novo(ambiente):
    acao, _, _ = pr.decidir_acao_emissao(ALUNO, TipoDoc.GUIA, [], _info())
    assert acao == AcaoDecidida.GERAR_NOVO


def test_entre_um_documento_de_fora_e_o_nosso_pendente_vale_o_nosso(ambiente):
    de_fora = _doc("outra", datetime(2026, 7, 1, 9, 0))              # válido, mas de outra escola
    nosso = _doc("nosso", EMISSAO + timedelta(minutes=1), sec=True, dire=False)
    acao, doc, motivo = pr.decidir_acao_emissao(ALUNO, TipoDoc.HISTORICO, [de_fora, nosso], _info())
    assert (acao, doc.cod) == (AcaoDecidida.JA_EXISTE, "nosso") and "1 documento(s) de outra origem" in motivo


# ══ download ══════════════════════════════════════════════════════════════

def test_download_ignora_documento_de_outra_escola(ambiente, tmp_path):
    de_fora = _doc("outra", datetime(2026, 7, 1, 9, 0))
    d = pr.decidir_acao_download(ALUNO, TipoDoc.HISTORICO, [de_fora], tmp_path, _info(None))
    assert d.acao == AcaoDecidida.IGNORAR and "esta escola" in d.motivo


def test_download_baixa_o_nosso_e_nao_o_de_fora(ambiente, tmp_path):
    de_fora = _doc("outra", EMISSAO + timedelta(hours=1))
    nosso = _doc("nosso", EMISSAO + timedelta(minutes=2))
    d = pr.decidir_acao_download(ALUNO, TipoDoc.HISTORICO, [de_fora, nosso], tmp_path, _info())
    assert d.acao == AcaoDecidida.BAIXAR and d.doc_sere.cod == "nosso"


def test_baixar_nao_marca_mais_anexado_em(ambiente, tmp_path, monkeypatch):
    """O download grava baixado_em. anexado_em é só de quando o arquivo é ENVIADO ao SERE."""
    _gravar_registro(ambiente, emitido_em=EMISSAO.isoformat())
    chamadas = []

    async def pdf_falso(page, url, caminho, method="GET"):
        chamadas.append(url)
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        Path(caminho).write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pr, "baixar_pdf", pdf_falso)

    nosso = _doc("nosso", EMISSAO + timedelta(minutes=1))
    decisao = pr.decidir_acao_download(ALUNO, TipoDoc.HISTORICO, [nosso], tmp_path)
    asyncio.run(pr._executar_download(None, ALUNO, TipoDoc.HISTORICO, decisao, "http://sere/{cod}"))

    reg = json.loads((ambiente / "transferidos.json").read_text(encoding="utf-8"))["33"]["historico"]
    assert chamadas == ["http://sere/nosso"]
    assert reg.get("baixado_em") and reg["anexado_em"] is None


# ══ envio ao SERE: o que fazer com o slot da pasta virtual ═══════════════

@pytest.fixture
def arquivo(tmp_path):
    f = tmp_path / "03-SAMUEL NASCIMENTO.pdf"
    f.write_bytes(b"%PDF-1.4")
    antes = (datetime.now() - timedelta(hours=3)).timestamp()
    os.utime(f, (antes, antes))
    return f


ENVIADO = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")


def test_slot_vazio_envia(arquivo):
    assert s.decidir_envio_slot(False, None, {}, arquivo)[0] == "enviar"


def test_slot_com_documento_de_outra_escola_e_substituido(arquivo):
    acao, motivo = s.decidir_envio_slot(True, "HISTORICO_ESCOLA_X.pdf", {}, arquivo)
    assert acao == "substituir" and "outra origem" in motivo


def test_anexado_em_antigo_do_download_nao_engana_mais(arquivo):
    """Registro legado: anexado_em gravado pelo download (sem nome_no_sere), slot ocupado por arquivo de outra escola."""
    acao, _ = s.decidir_envio_slot(True, "HISTORICO_ESCOLA_X.pdf", {"anexado_em": ENVIADO}, arquivo)
    assert acao == "substituir"


def test_o_nosso_ja_enviado_nao_e_sobrescrito(arquivo):
    reg = {"anexado_em": ENVIADO, "nome_no_sere": "03-SAMUEL NASCIMENTO.pdf"}
    assert s.decidir_envio_slot(True, "03-SAMUEL NASCIMENTO.pdf", reg, arquivo)[0] == "pular"


def test_o_nosso_sem_nome_registrado_compara_com_o_arquivo_local(arquivo):
    assert s.decidir_envio_slot(True, "03-samuel nascimento.PDF", {"anexado_em": ENVIADO}, arquivo)[0] == "pular"


def test_o_sere_renomeou_o_arquivo_mas_o_nome_registrado_confere(arquivo):
    reg = {"anexado_em": ENVIADO, "nome_no_sere": "20260810_103000_parecer.pdf"}
    assert s.decidir_envio_slot(True, "20260810_103000_parecer.pdf", reg, arquivo)[0] == "pular"


def test_slot_com_outro_nome_que_o_registrado_e_substituido(arquivo):
    reg = {"anexado_em": ENVIADO, "nome_no_sere": "03-SAMUEL NASCIMENTO.pdf"}
    assert s.decidir_envio_slot(True, "ESCOLA_Y.pdf", reg, arquivo)[0] == "substituir"


def test_arquivo_local_alterado_depois_do_envio_e_reenviado(arquivo):
    agora = datetime.now().timestamp()
    os.utime(arquivo, (agora, agora))
    reg = {"anexado_em": ENVIADO, "nome_no_sere": arquivo.name}
    acao, motivo = s.decidir_envio_slot(True, arquivo.name, reg, arquivo)
    assert acao == "substituir" and "alterado" in motivo

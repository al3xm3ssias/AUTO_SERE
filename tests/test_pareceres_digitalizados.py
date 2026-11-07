"""Pareceres do Fundamental digitalizados: ler o QR (AUTOSERE|PF|ano|CGM), arquivar, enviar ao SERE e por e-mail."""
import asyncio
import io
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest

pytest.importorskip("cv2")
pytest.importorskip("qrcode")
pytest.importorskip("reportlab")

from src.comum import paths
from src.automacao import avisos as av
from src.automacao import envia_email
from src.automacao import pareceres_digitalizados as pd
from src.automacao import pareceres_transferidos as pt
from src.automacao import sere_2026 as s

TURMA = "1º Ano Integral A"
ANO = "2026"


def _al(n, cgm, nome, sit="Matriculado"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Situação": sit, "Data Matricula": "05/02/2026"}


def _qr_png(texto):
    import qrcode
    buf = io.BytesIO()
    qrcode.make(texto, box_size=8, border=4).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_com_qr(caminho, texto_qr, paginas=2):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(caminho))
    for i in range(paginas - 1):
        c.drawString(100, 700, f"Parecer descritivo — página {i + 1}")
        c.showPage()
    c.drawImage(ImageReader(io.BytesIO(_qr_png(texto_qr))), 200, 300, 200, 200)
    c.showPage()
    c.save()


def _qr_do_aluno(cgm, ano=ANO):
    return f"AUTOSERE|PF|{ano}|{cgm}"


@pytest.fixture
def amb(tmp_path, monkeypatch):
    base = tmp_path / "base"
    dados = tmp_path / "dados"
    dados.mkdir()
    monkeypatch.setenv("AUTO_SERE_PARECERES_BASE", str(base))
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados_raiz")          # onde o idtipo descoberto é guardado
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path / "credenciais")   # e a chave do QR
    monkeypatch.setattr(paths, "ano_atual", lambda: ANO)
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    (dados / "turmas.json").write_text(json.dumps({TURMA: [
        _al(1, "11", "ALICIA SOARES"), _al(2, "22", "BRUNO LIMA"), _al(3, "33", "CARLA DIAS", "Transferido"),
    ]}, ensure_ascii=False), encoding="utf-8")
    pd.pasta_entrada(ANO).mkdir(parents=True)
    return {"base": base, "dados": dados, "entrada": pd.pasta_entrada(ANO)}


def _controle():
    return pd.carregar_controle(ANO)


# ─────────────────────── 1–4: ler o QR e arquivar ───────────────────────

def test_arquiva_na_pasta_da_turma_e_anota_no_controle(amb):
    _pdf_com_qr(amb["entrada"] / "scan001.pdf", _qr_do_aluno("11"))
    r = pd.processar_entrada(ano=ANO, dados_dir=amb["dados"], log=lambda *_: None)
    assert len(r.processados) == 1 and not r.erros
    destino = amb["base"] / ANO / "PARECERES" / TURMA / "1 - ALICIA_SOARES.pdf"
    assert destino.exists() and not (amb["entrada"] / "scan001.pdf").exists()        # só sai da entrada depois de arquivado
    reg = _controle()["11"]
    assert reg["arquivo"] == f"{TURMA}/1 - ALICIA_SOARES.pdf" and reg["nome"] == "ALICIA SOARES" and reg["turma"] == TURMA
    assert reg["sere"] == {} and reg["email"] == {} and reg["digitalizado_em"]


def test_simulacao_nao_copia_nao_apaga_nem_grava(amb):
    _pdf_com_qr(amb["entrada"] / "scan001.pdf", _qr_do_aluno("22"))
    linhas = []
    r = pd.processar_entrada(simulacao=True, ano=ANO, dados_dir=amb["dados"], log=linhas.append)
    assert len(r.processados) == 1 and (amb["entrada"] / "scan001.pdf").exists()
    assert not pd.arquivo_controle(ANO).exists() and not (amb["base"] / ANO / "PARECERES" / TURMA).exists()
    assert any("Seria salvo em" in l and "BRUNO_LIMA" in l for l in linhas)


def test_qr_de_outro_ano_cgm_desconhecido_e_arquivo_sem_qr_ficam_na_entrada_com_motivo(amb):
    _pdf_com_qr(amb["entrada"] / "a_ano.pdf", _qr_do_aluno("11", "2025"))
    _pdf_com_qr(amb["entrada"] / "b_cgm.pdf", _qr_do_aluno("99999"))
    _pdf_com_qr(amb["entrada"] / "c_outro_qr.pdf", "https://exemplo.com")
    (amb["entrada"] / "d_sem_qr.png").write_bytes(b"nao e uma imagem")
    r = pd.processar_entrada(ano=ANO, dados_dir=amb["dados"], log=lambda *_: None)
    motivos = dict(r.erros)
    assert "parecer de 2025" in motivos["a_ano.pdf"] and "ano letivo em uso é 2026" in motivos["a_ano.pdf"]
    assert "CGM 99999 não encontrado" in motivos["b_cgm.pdf"]
    assert "não é de um parecer" in motivos["c_outro_qr.pdf"]
    assert "d_sem_qr.png" in motivos
    assert not r.processados and len(list(amb["entrada"].iterdir())) == 4 and _controle() == {}


def test_digitalizar_de_novo_nao_sobrescreve_zera_o_sere_e_mantem_o_email(amb):
    _pdf_com_qr(amb["entrada"] / "1.pdf", _qr_do_aluno("11"))
    pd.processar_entrada(ano=ANO, dados_dir=amb["dados"], log=lambda *_: None)
    c = _controle()
    c["11"]["sere"] = {"anexado_em": "2026-10-01T10:00:00"}
    c["11"]["email"] = {"enviado_em": "2026-10-01T10:05:00", "para": ["mae@exemplo.com"]}
    pd.salvar_controle(c, ANO)

    _pdf_com_qr(amb["entrada"] / "2.pdf", _qr_do_aluno("11"), paginas=3)
    pd.processar_entrada(ano=ANO, dados_dir=amb["dados"], log=lambda *_: None)
    pasta = amb["base"] / ANO / "PARECERES" / TURMA
    assert sorted(p.name for p in pasta.iterdir()) == ["1 - ALICIA_SOARES (2).pdf", "1 - ALICIA_SOARES.pdf"]
    reg = _controle()["11"]
    assert reg["arquivo"].endswith("(2).pdf") and reg["sere"] == {}                  # o novo vai de novo ao SERE
    assert reg["email"]["enviado_em"]                                                # mas o e-mail não é reenviado sozinho


def test_modo_teste_processa_so_o_primeiro(amb):
    _pdf_com_qr(amb["entrada"] / "a.pdf", _qr_do_aluno("11"))
    _pdf_com_qr(amb["entrada"] / "b.pdf", _qr_do_aluno("22"))
    r = pd.processar_entrada(modo_teste=True, ano=ANO, dados_dir=amb["dados"], log=lambda *_: None)
    assert len(r.processados) == 1 and (amb["entrada"] / "b.pdf").exists()


def test_sem_turmas_json_avisa_para_rodar_turmas(amb):
    (amb["dados"] / "turmas.json").unlink()
    _pdf_com_qr(amb["entrada"] / "a.pdf", _qr_do_aluno("11"))
    with pytest.raises(FileNotFoundError, match="Turmas"):
        pd.processar_entrada(ano=ANO, dados_dir=amb["dados"], log=lambda *_: None)


def test_transferidos_tambem_aceitam_o_qr_novo_e_o_antigo(amb):
    """pareceres_transferidos passou a entender AUTOSERE|PF|ano|CGM (preferindo o registro transferido do CGM)."""
    turmas = json.loads((amb["dados"] / "turmas.json").read_text(encoding="utf-8"))
    ident, _ = pt.identificar_pelo_texto_do_qr(_qr_do_aluno("33"), turmas, ANO)
    assert ident.cgm == "33" and ident.nome == "CARLA DIAS" and ident.turma == TURMA
    ident, _ = pt.identificar_pelo_texto_do_qr(json.dumps({"nome": "ALICIA SOARES", "turma": TURMA}), turmas, ANO)
    assert ident.cgm == "11"                                                         # formato antigo continua valendo
    ident, motivo = pt.identificar_pelo_texto_do_qr(_qr_do_aluno("33", "2024"), turmas, ANO)
    assert ident is None and "2024" in motivo


def test_cgm_em_dois_registros_vale_o_matriculado_aqui_e_o_transferido_nos_transferidos():
    turmas = {TURMA: [_al(4, "44", "FULANO", "Transferido"), _al(31, "44", "FULANO", "Matriculado")]}
    assert pt.identificar_por_cgm(turmas, "44", preferir_transferido=True)[0].numero == 4
    assert pt.identificar_por_cgm(turmas, "44", preferir_transferido=False)[0].numero == 31


# ─────────────────────── quais ainda precisam ir ───────────────────────

def _registro(amb, cgm="11", nome="ALICIA SOARES", sere=None, email=None, criar=True, ano=ANO):
    arquivo = amb["base"] / ano / "PARECERES" / TURMA / f"{cgm} - {nome.replace(' ', '_')}.pdf"
    if criar:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(b"%PDF-1.4 teste")
    reg = {"nome": nome, "turma": TURMA, "numero": 1, "arquivo": f"{TURMA}/{arquivo.name}",
           "digitalizado_em": "2026-10-30T09:00:00", "sere": sere or {}, "email": email or {}}
    return reg, arquivo


def test_pendentes_sere_pula_o_ja_enviado_que_nao_mudou_e_reenvia_o_alterado(amb):
    ok, arq_ok = _registro(amb, "11", sere={"anexado_em": (datetime.now() + timedelta(hours=1)).isoformat()})
    mudado, arq_mudado = _registro(amb, "22", "BRUNO LIMA", sere={"anexado_em": (datetime.now() - timedelta(hours=1)).isoformat()})
    novo, _ = _registro(amb, "33", "CARLA DIAS")
    sem, _ = _registro(amb, "44", "DUDA REIS", criar=False)
    controle = {"11": ok, "22": mudado, "33": novo, "44": sem}
    pendentes, sem_arquivo = pd.pendentes_sere(controle, ANO)
    assert [c for c, _, _ in pendentes] == ["22", "33"]
    assert [c for c, _ in sem_arquivo] == ["44"]
    assert [c for c, _, _ in pd.pendentes_sere(controle, ANO, cgms=["33"])[0]] == ["33"]
    assert pd.pendentes_sere(controle, ANO, turmas=["Outra turma"]) == ([], [])


def test_pendentes_email_so_os_que_nao_receberam_e_tem_arquivo(amb):
    a, _ = _registro(amb, "11", email={"enviado_em": "2026-10-31T08:00:00"})
    b, _ = _registro(amb, "22", "BRUNO LIMA")
    c, _ = _registro(amb, "33", "CARLA DIAS", criar=False)
    assert [x for x, _, _ in pd.pendentes_email({"11": a, "22": b, "33": c}, ANO)] == ["22"]


# ─────────────────────── 5: SERE (com sessão simulada) ───────────────────────

class _Pagina:
    voltou = 0
    entradas = []                                         # o que a listagem da pasta virtual devolve (para a descoberta do idtipo)

    async def evaluate(self, _js):
        return _Pagina.entradas

    async def query_selector(self, _sel):
        return None

    async def go_back(self):
        _Pagina.voltou += 1

    async def wait_for_timeout(self, _ms):
        return None


@pytest.fixture
def sere_falso(monkeypatch):
    estado = {"enviados": [], "excluidos": [], "slots": {}, "abre": True, "falha_envio": set()}
    idtipo, _ = pd.slot_sere_do_parecer(ANO)

    async def navegar(page, cgm):
        return estado["abre"]

    async def slots(page, cgm):
        existentes = {idtipo: "assin"} if cgm in estado["slots"] else {}
        return {idtipo: f"hash-{cgm}"}, existentes

    async def nomes(page, cgm):
        return {idtipo: estado["slots"].get(cgm, f"arquivo-{cgm}.pdf")}

    async def excluir(page, cgm, nome_slot, id_, assinatura):
        estado["excluidos"].append(cgm)
        return f"hash-novo-{cgm}"

    async def enviar(page, hash_doc, arquivo):
        cgm = hash_doc.rsplit("-", 1)[-1]
        if cgm in estado["falha_envio"]:
            return False, "SERE recusou o arquivo"
        estado["enviados"].append((hash_doc, arquivo.name))
        return True, "Arquivo enviado"

    for nome, fn in (("navegar_pasta_virtual", navegar), ("obter_slots_api", slots), ("obter_nomes_slots_api", nomes),
                     ("excluir_slot_e_obter_hash", excluir), ("injetar_e_enviar", enviar)):
        monkeypatch.setattr(s, nome, fn)

    @asynccontextmanager
    async def sessao():
        yield _Pagina()
    estado["sessao"] = sessao
    return estado


def test_envia_ao_sere_e_grava_anexado_em_sem_repetir_depois(amb, sere_falso):
    reg11, _ = _registro(amb, "11")
    reg22, _ = _registro(amb, "22", "BRUNO LIMA")
    controle = {"11": reg11, "22": reg22}
    pd.salvar_controle(controle, ANO)
    resumo = pd.ResumoDigitalizados()
    tarefas, _ = pd.pendentes_sere(controle, ANO)
    asyncio.run(pd.enviar_ao_sere(tarefas, controle, ANO, resumo, sessao=sere_falso["sessao"], log=lambda *_: None))
    assert resumo.sere_enviados == ["11", "22"] and not resumo.sere_erros
    assert [h for h, _ in sere_falso["enviados"]] == ["hash-11", "hash-22"]
    salvo = _controle()
    assert salvo["11"]["sere"]["anexado_em"] and salvo["11"]["sere"]["nome_no_sere"] == "arquivo-11.pdf"
    assert pd.pendentes_sere(salvo, ANO) == ([], [])                                 # nada mais a enviar


def test_slot_ocupado_por_outro_documento_e_substituido(amb, sere_falso):
    reg, _ = _registro(amb, "11")
    sere_falso["slots"]["11"] = "documento_de_outra_origem.pdf"
    controle = {"11": reg}
    resumo = pd.ResumoDigitalizados()
    asyncio.run(pd.enviar_ao_sere(pd.pendentes_sere(controle, ANO)[0], controle, ANO, resumo, sessao=sere_falso["sessao"], log=lambda *_: None))
    assert sere_falso["excluidos"] == ["11"] and sere_falso["enviados"][0][0] == "hash-novo-11" and resumo.sere_enviados == ["11"]


def test_falha_de_um_aluno_no_sere_nao_derruba_os_outros_nem_marca_como_enviado(amb, sere_falso):
    reg11, _ = _registro(amb, "11")
    reg22, _ = _registro(amb, "22", "BRUNO LIMA")
    sere_falso["falha_envio"].add("11")
    controle = {"11": reg11, "22": reg22}
    resumo = pd.ResumoDigitalizados()
    asyncio.run(pd.enviar_ao_sere(pd.pendentes_sere(controle, ANO)[0], controle, ANO, resumo, sessao=sere_falso["sessao"], log=lambda *_: None))
    assert resumo.sere_enviados == ["22"] and resumo.sere_erros == [("11", "SERE recusou o arquivo")]
    assert controle["11"]["sere"] == {} and controle["22"]["sere"]["anexado_em"]      # o de 11 continua pendente


def test_pasta_virtual_que_nao_abre_vira_erro_sem_tentar_voltar(amb, sere_falso):
    reg, _ = _registro(amb, "11")
    sere_falso["abre"] = False
    _Pagina.voltou = 0
    resumo = pd.ResumoDigitalizados()
    asyncio.run(pd.enviar_ao_sere(pd.pendentes_sere({"11": reg}, ANO)[0], {"11": reg}, ANO, resumo, sessao=sere_falso["sessao"], log=lambda *_: None))
    assert resumo.sere_erros == [("11", "falha ao abrir a pasta virtual")] and _Pagina.voltou == 0


def test_slot_do_parecer_vem_do_catalogo_e_o_nome_vale_para_qualquer_ano():
    assert pd.slot_sere_do_parecer("2026") == ("38", "Parecer Descritivo 2026-1")
    assert pd.slot_sere_do_parecer("2025") == ("37", "Parecer Descritivo 2025-1")
    assert pd.slot_sere_do_parecer("2031") == (None, "Parecer Descritivo 2031-1")        # fora do catálogo: será descoberto no SERE
    assert pd.nome_do_slot_do_parecer(2040) == "Parecer Descritivo 2040-1"


@pytest.fixture
def sere_ano_novo(monkeypatch):
    """Ano que o catálogo não conhece (2027): o idtipo (39) só aparece na listagem do SERE."""
    monkeypatch.setattr(paths, "ano_atual", lambda: "2027")
    estado = {"enviados": []}

    async def navegar(page, cgm):
        return True

    async def slots(page, cgm):
        return {"39": f"hash39-{cgm}"}, {}

    async def nomes(page, cgm):
        return {}

    async def enviar(page, hash_doc, arquivo):
        estado["enviados"].append((hash_doc, arquivo.name))
        return True, "Arquivo enviado"

    for nome, fn in (("navegar_pasta_virtual", navegar), ("obter_slots_api", slots), ("obter_nomes_slots_api", nomes),
                     ("injetar_e_enviar", enviar)):
        monkeypatch.setattr(s, nome, fn)

    @asynccontextmanager
    async def sessao():
        yield _Pagina()
    estado["sessao"] = sessao
    return estado


def _enviar_2027(amb, estado, cgms=("11",)):
    controle = {}
    for cgm in cgms:
        reg, _ = _registro(amb, cgm, f"ALUNO {cgm}", ano="2027")
        controle[cgm] = reg
    resumo, linhas = pd.ResumoDigitalizados(), []
    asyncio.run(pd.enviar_ao_sere(pd.pendentes_sere(controle, "2027")[0], controle, "2027", resumo,
                                  sessao=estado["sessao"], log=linhas.append))
    return controle, resumo, linhas


def test_ano_novo_fora_do_catalogo_acha_o_idtipo_no_sere_e_envia(amb, sere_ano_novo):
    _Pagina.entradas = [{"idtipodocumento": 38, "descricao": "Parecer Descritivo 2026-1", "nomearquivo": "antigo.pdf", "assinaturaArquivo": "x"},
                        {"idtipodocumento": 39, "descricao": "PARECER DESCRITIVO 2027-1", "nomearquivo": "", "assinaturaArquivo": "y"}]
    controle, resumo, linhas = _enviar_2027(amb, sere_ano_novo, cgms=("11", "22"))
    assert resumo.sere_enviados == ["11", "22"] and not resumo.sere_erros
    assert [h for h, _ in sere_ano_novo["enviados"]] == ["hash39-11", "hash39-22"]
    assert sum("encontrado no SERE: idtipo 39" in l for l in linhas) == 1               # procura uma vez só, não a cada aluno
    assert any("ainda não é conhecido" in l for l in linhas)


def test_ano_novo_sem_o_item_na_pasta_virtual_vira_erro_claro_sem_enviar_nada(amb, sere_ano_novo):
    _Pagina.entradas = [{"idtipodocumento": 38, "descricao": "Parecer Descritivo 2026-1"}]      # só o do ano passado
    controle, resumo, linhas = _enviar_2027(amb, sere_ano_novo)
    assert sere_ano_novo["enviados"] == [] and controle["11"]["sere"] == {}
    assert resumo.sere_erros and "Parecer Descritivo 2027-1" in resumo.sere_erros[0][1]
    assert any("Confira no SERE" in l for l in linhas)
    assert pd.carregar_slots_descobertos() == {}                                         # nada achado: nada guardado


def test_ano_novo_com_o_item_duplicado_na_listagem_nao_chuta(amb, sere_ano_novo):
    _Pagina.entradas = [{"idtipodocumento": 39, "descricao": "Parecer Descritivo 2027-1"},
                        {"idtipodocumento": 40, "descricao": "Parecer Descritivo 2027-1"}]
    _, resumo, _ = _enviar_2027(amb, sere_ano_novo)
    assert sere_ano_novo["enviados"] == [] and len(resumo.sere_erros) == 1               # ambíguo: não escolhe um id ao acaso


def test_ano_novo_listagem_invalida_nao_derruba(amb, sere_ano_novo):
    _Pagina.entradas = None                                                              # o SERE devolveu algo que não é lista
    _, resumo, _ = _enviar_2027(amb, sere_ano_novo)
    assert sere_ano_novo["enviados"] == [] and len(resumo.sere_erros) == 1


# ─────────────────────── 6: e-mail ───────────────────────

class _Correio:
    def __init__(self, falhar=()):
        self.enviados, self.pausas, self.falhar = [], [], set(falhar)

    def __call__(self, destinatario, assunto, corpo, anexos=None):
        if destinatario in self.falhar:
            return False, "caixa cheia"
        self.enviados.append({"para": destinatario, "assunto": assunto, "corpo": corpo, "anexos": [a.name for a in anexos or []]})
        return True, None

    def pausa(self, segundos):
        self.pausas.append(segundos)


def _alunos(amb, basico=None, completo=None):
    (amb["dados"] / "alunos.json").write_text(json.dumps(basico or [
        {"CGM": "11", "Nome": "ALICIA SOARES", "Responsável": "Maria Soares", "Email Responsável": "maria@exemplo.com"},
        {"CGM": "22", "Nome": "BRUNO LIMA", "Responsável": "João Lima", "Email Responsável": "—"},
        {"CGM": "33", "Nome": "CARLA DIAS", "Mãe": "Rosa Dias", "Email Responsável": "rosa@exemplo.com; pai@exemplo.com"},
    ], ensure_ascii=False), encoding="utf-8")
    if completo:
        (amb["dados"] / "alunos_completo.json").write_text(json.dumps(completo), encoding="utf-8")


def test_emails_do_responsavel_le_o_basico_o_completo_e_varios_enderecos(amb):
    _alunos(amb, completo={"22": {"cgm": "22", "nome_responsavel": "J. Lima", "email_responsavel": "joao@exemplo.com"}})
    assert pd.emails_do_responsavel("11", amb["dados"]) == (["maria@exemplo.com"], "Maria Soares")
    assert pd.emails_do_responsavel("22", amb["dados"]) == (["joao@exemplo.com"], "João Lima")     # básico vazio → completo
    assert pd.emails_do_responsavel("33", amb["dados"]) == (["rosa@exemplo.com", "pai@exemplo.com"], "Rosa Dias")
    assert pd.emails_do_responsavel("999", amb["dados"]) == ([], "")


def _tarefas_email(amb):
    r11, _ = _registro(amb, "11")
    r22, _ = _registro(amb, "22", "BRUNO LIMA")
    r33, _ = _registro(amb, "33", "CARLA DIAS")
    controle = {"11": r11, "22": r22, "33": r33}
    pd.salvar_controle(controle, ANO)
    return controle, pd.pendentes_email(controle, ANO)


def test_envio_real_manda_um_por_endereco_registra_e_deixa_de_fora_quem_nao_tem_email(amb, monkeypatch):
    monkeypatch.setattr(av, "_credenciais_email_ok", lambda: True)
    _alunos(amb)
    controle, tarefas = _tarefas_email(amb)
    correio, resumo = _Correio(), pd.ResumoDigitalizados()
    pd.enviar_emails(tarefas, controle, ANO, "enviar", resumo, pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO,
                     dados_dir=amb["dados"], enviar=correio, pausa=correio.pausa, log=lambda *_: None)
    assert [e["para"] for e in correio.enviados] == ["maria@exemplo.com", "rosa@exemplo.com", "pai@exemplo.com"]
    primeiro = correio.enviados[0]
    assert primeiro["assunto"] == "Parecer descritivo de ALICIA SOARES — 2026" and primeiro["anexos"] == ["11 - ALICIA_SOARES.pdf"]
    assert "Prezado(a) responsável Maria Soares" in primeiro["corpo"] and "turma 1º Ano Integral A" in primeiro["corpo"]
    assert "$" not in primeiro["corpo"].replace("$ESCOLA", "")                        # marcador nenhum sobrou (a escola pode estar vazia)
    assert resumo.emails_sem_endereco == ["22"] and len(resumo.emails_enviados) == 2
    assert correio.pausas == [pd.INTERVALO_EMAIL_S, pd.INTERVALO_EMAIL_S]             # pausa entre um e-mail e o seguinte
    salvo = _controle()
    assert salvo["11"]["email"]["para"] == ["maria@exemplo.com"] and salvo["33"]["email"]["enviado_em"] and not salvo["22"]["email"]
    assert [c for c, _, _ in pd.pendentes_email(salvo, ANO)] == ["22"]                # só falta quem não tem e-mail


def test_falha_num_endereco_nao_marca_como_enviado_se_nenhum_foi(amb, monkeypatch):
    monkeypatch.setattr(av, "_credenciais_email_ok", lambda: True)
    _alunos(amb)
    controle, tarefas = _tarefas_email(amb)
    correio, resumo = _Correio(falhar={"maria@exemplo.com", "pai@exemplo.com"}), pd.ResumoDigitalizados()
    pd.enviar_emails(tarefas, controle, ANO, "enviar", resumo, pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO,
                     dados_dir=amb["dados"], enviar=correio, pausa=correio.pausa, log=lambda *_: None)
    salvo = _controle()
    assert not salvo["11"]["email"]                                                   # nada foi: continua pendente
    assert salvo["33"]["email"]["para"] == ["rosa@exemplo.com"] and salvo["33"]["email"]["falhou_para"] == ["pai@exemplo.com"]
    assert {c for c, _ in resumo.emails_erros} == {"11", "33"}


def test_limite_por_execucao_corta_o_lote(amb, monkeypatch):
    monkeypatch.setattr(av, "_credenciais_email_ok", lambda: True)
    monkeypatch.setattr(pd, "LIMITE_EMAILS_POR_EXECUCAO", 1)
    _alunos(amb)
    controle, tarefas = _tarefas_email(amb)
    correio, resumo, linhas = _Correio(), pd.ResumoDigitalizados(), []
    pd.enviar_emails(tarefas, controle, ANO, "enviar", resumo, pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO,
                     dados_dir=amb["dados"], enviar=correio, pausa=correio.pausa, log=linhas.append)
    assert [e["para"] for e in correio.enviados] == ["maria@exemplo.com"]
    assert any("restantes" in l for l in linhas)


def test_modo_teste_manda_um_so_para_o_endereco_de_teste_e_nao_registra(amb):
    _alunos(amb)
    controle, tarefas = _tarefas_email(amb)
    correio, resumo = _Correio(), pd.ResumoDigitalizados()
    pd.enviar_emails(tarefas, controle, ANO, "teste", resumo, pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO, email_teste="secretaria@exemplo.com",
                     dados_dir=amb["dados"], enviar=correio, pausa=correio.pausa, log=lambda *_: None)
    assert len(correio.enviados) == 1 and correio.enviados[0]["para"] == "secretaria@exemplo.com"
    assert correio.enviados[0]["assunto"].startswith("[TESTE] ") and "maria@exemplo.com" in correio.enviados[0]["corpo"]
    assert correio.enviados[0]["anexos"] == ["11 - ALICIA_SOARES.pdf"]
    assert not any(r["email"] for r in _controle().values())                          # teste não marca ninguém como avisado
    with pytest.raises(ValueError, match="e-mail de teste válido"):
        pd.enviar_emails(tarefas, controle, ANO, "teste", resumo, pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO, email_teste="isto não é e-mail",
                         dados_dir=amb["dados"], enviar=correio, log=lambda *_: None)


def test_simulacao_de_email_nao_envia_nada(amb):
    _alunos(amb)
    controle, tarefas = _tarefas_email(amb)
    correio, resumo, linhas = _Correio(), pd.ResumoDigitalizados(), []
    for modo in ("teste", "enviar"):
        pd.enviar_emails(tarefas, controle, ANO, modo, resumo, pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO, email_teste="x@exemplo.com",
                         simulacao=True, dados_dir=amb["dados"], enviar=correio, pausa=correio.pausa, log=linhas.append)
    assert correio.enviados == [] and not any(r["email"] for r in _controle().values())
    assert any("receberia em: maria@exemplo.com" in l for l in linhas)


def test_envio_real_sem_credenciais_do_email_e_recusado(amb, monkeypatch):
    monkeypatch.setattr(av, "_credenciais_email_ok", lambda: False)
    _alunos(amb)
    controle, tarefas = _tarefas_email(amb)
    with pytest.raises(ValueError, match="EMAIL_REMETENTE"):
        pd.enviar_emails(tarefas, controle, ANO, "enviar", pd.ResumoDigitalizados(), pd.ASSUNTO_PADRAO, pd.MENSAGEM_PADRAO,
                         dados_dir=amb["dados"], enviar=_Correio(), log=lambda *_: None)


def test_marcador_desconhecido_e_recusado_antes_de_qualquer_coisa(amb):
    with pytest.raises(ValueError, match=r"Assunto: marcador\(es\) desconhecido\(s\) \$NOTA"):
        asyncio.run(pd.executar_pareceres_digitalizados(assunto="Nota de $NOTA"))
    with pytest.raises(ValueError, match="Modo de e-mail inválido"):
        asyncio.run(pd.executar_pareceres_digitalizados(email_modo="todos"))


def test_rotina_completa_em_simulacao_nao_altera_nada(amb):
    _pdf_com_qr(amb["entrada"] / "scan.pdf", _qr_do_aluno("11"))
    reg, _ = _registro(amb, "22", "BRUNO LIMA")
    pd.salvar_controle({"22": reg}, ANO)
    _alunos(amb)
    resumo = asyncio.run(pd.executar_pareceres_digitalizados(simulacao=True, enviar_sere=True, email_modo="enviar"))
    assert len(resumo.processados) == 1 and (amb["entrada"] / "scan.pdf").exists()
    assert set(_controle()) == {"22"} and not resumo.sere_enviados and not resumo.emails_enviados


def test_rotina_completa_em_simulacao_num_ano_fora_do_catalogo_nao_recusa(amb, monkeypatch):
    monkeypatch.setattr(paths, "ano_atual", lambda: "2031")
    pd.pasta_entrada("2031").mkdir(parents=True)
    resumo = asyncio.run(pd.executar_pareceres_digitalizados(simulacao=True, enviar_sere=True))
    assert resumo.sere_erros == [] and resumo.processados == []


# ─────────────────────── envia_email com anexo ───────────────────────

def test_enviar_email_anexa_o_arquivo_e_recusa_anexo_inexistente(tmp_path, monkeypatch):
    capturado = {}

    class SMTPFalso:
        def __init__(self, *a):
            pass

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def sendmail(self, de, para, texto):
            capturado.update(de=de, para=para, texto=texto)

        def quit(self):
            pass

    monkeypatch.setattr(envia_email.smtplib, "SMTP", SMTPFalso)
    pdf = tmp_path / "parecer.pdf"
    pdf.write_bytes(b"%PDF-1.4 conteudo")
    ok, erro = envia_email.enviar_email("a@b.com", "Assunto", "Corpo", remetente="esc@x.com", senha_app="s", anexos=[pdf])
    assert ok and erro is None and 'filename="parecer.pdf"' in capturado["texto"] and "application/pdf" in capturado["texto"]
    capturado.clear()
    ok, erro = envia_email.enviar_email("a@b.com", "Assunto", "Corpo", remetente="esc@x.com", senha_app="s", anexos=[tmp_path / "nao_existe.pdf"])
    assert not ok and "nao_existe.pdf" in erro and not capturado                      # não manda o e-mail sem o anexo
    ok, _ = envia_email.enviar_email("a@b.com", "Sem anexo", "Corpo", remetente="esc@x.com", senha_app="s")
    assert ok and "Content-Disposition" not in capturado["texto"]                     # chamadas antigas (sem anexos) continuam iguais


# ─────────────────────── pela linha de comando (a mesma execução da tela) ───────────────────────

def test_pela_cli_em_simulacao_le_o_qr_e_nao_altera_nada(amb, capsys):
    from src.comum import cli
    _pdf_com_qr(amb["entrada"] / "scan.pdf", _qr_do_aluno("22"))
    codigo = cli.main(["pareceres_digitalizados", "--simulacao", "--confirmo"])
    saida = capsys.readouterr().out
    assert codigo == 0, saida
    assert "SIMULAÇÃO" in saida and "BRUNO LIMA" in saida and "Seria salvo em" in saida
    assert (amb["entrada"] / "scan.pdf").exists() and not pd.arquivo_controle(ANO).exists()


def test_pela_cli_email_de_teste_com_endereco_invalido_e_recusado_antes_de_rodar(amb, capsys):
    from src.comum import cli
    codigo = cli.main(["pareceres_digitalizados", "--email-modo", "teste", "--email-teste", "isso-nao-e-email", "--confirmo"])
    assert codigo == 2 and "não é um e-mail válido" in capsys.readouterr().err
    codigo = cli.main(["pareceres_digitalizados", "--assunto", "Nota $NOTA", "--email-modo", "enviar", "--simulacao", "--confirmo"])
    assert codigo == 2 and "$NOTA" in capsys.readouterr().err


# ───────────── idtipo descoberto fica guardado (não precisa editar SERE_SLOTS) ─────────────

def test_idtipo_descoberto_e_guardado_e_vale_para_a_proxima_execucao(amb, sere_ano_novo):
    _Pagina.entradas = [{"idtipodocumento": 39, "descricao": "Parecer Descritivo 2027-1", "nomearquivo": "", "assinaturaArquivo": "y"}]
    _, resumo, linhas = _enviar_2027(amb, sere_ano_novo)
    assert resumo.sere_enviados == ["11"]
    assert pd.carregar_slots_descobertos()["Parecer Descritivo 2027-1"]["idtipo"] == "39"
    assert (amb["base"].parent / "dados_raiz" / pd.NOME_SLOTS_DESCOBERTOS).is_file()
    assert pd.slot_sere_do_parecer("2027") == ("39", "Parecer Descritivo 2027-1")        # a próxima vez já sabe

    _Pagina.entradas = []                                    # a listagem nem seria consultada: o idtipo já é conhecido
    _, resumo2, linhas2 = _enviar_2027(amb, sere_ano_novo, cgms=("22",))
    assert not any("ainda não é conhecido" in l or "encontrado no SERE" in l for l in linhas2)


def test_catalogo_do_sistema_vale_mais_que_o_descoberto(amb):
    pd.guardar_slot_descoberto("Parecer Descritivo 2026-1", "999")
    assert pd.slot_sere_do_parecer("2026") == ("38", "Parecer Descritivo 2026-1")


def test_arquivo_de_slots_ilegivel_volta_a_procurar_no_sere(amb):
    arq = pd.arquivo_slots_descobertos()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text("{ isso não é json", encoding="utf-8")
    assert pd.carregar_slots_descobertos() == {}
    assert pd.slot_sere_do_parecer("2031") == (None, "Parecer Descritivo 2031-1")

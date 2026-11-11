"""
parecer_planilha: portado de gerar_pareceres_infantil_planilha.py — planilhas do cadastro "Planilhas do Drive",
exportação em PDF, QR no padrão do sistema, laço de alunos, registro na tela. Google e HTTP são simulados.
"""
import io
import json
from types import SimpleNamespace

import httplib2
import pytest
from googleapiclient.errors import HttpError
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from src.automacao import parecer_planilha as pp
from src.comum import configuracao, google_auth, paths, planilhas_registro as registro, qr_seguro
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app

ID4 = "1-0IJ5Lra8eNgbDAgTQ4lklWph4M3BRpAWzA2SbM1z1A"
ID5 = "1PENUySv_Z4lGNnkZTUm3OIb0EAyKkLXLBD_xBhcUkwI"
URL4 = f"https://docs.google.com/spreadsheets/d/{ID4}/edit"
URL5 = f"https://docs.google.com/spreadsheets/d/{ID5}/edit"
GID = 1224152601
FIN = registro.FINALIDADE_PARECER_INFANTIL


def _al(cgm, nome, n, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "N": n, "Situação": sit}


TURMAS = {
    "INFANTIL 4 Integral A": [_al("102", "Beto Souza", 2), _al("101", "Ana Lima", 1), _al("103", "Cai Transf", 3, "Transferido")],
    "INFANTIL 5 Integral A": [_al("201", "Caio Dias", 1)],
    "3º Ano A": [_al("401", "Fundamental", 1)],
}


def _pdf_de_uma_pagina() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.drawString(100, 500, "PARECER")
    c.save()
    return buf.getvalue()


# ───────────── dublês ─────────────

class _Pedido:
    def __init__(self, f):
        self.f = f

    def execute(self, num_retries=0):
        return self.f()


class _Valores:
    def __init__(self, pai):
        self.pai = pai

    def get(self, spreadsheetId, range, **extra):
        return _Pedido(lambda: {"values": [[self.pai.c5]] if self.pai.c5 != "" else []})

    def batchUpdate(self, spreadsheetId, body):
        def f():
            if self.pai.erro_escrita:
                raise HttpError(httplib2.Response({"status": self.pai.erro_escrita}), b'{"error": {"message": "x"}}')
            for d in body["data"]:
                valor = d["values"][0][0]
                self.pai.escritas.append((spreadsheetId, d["range"], valor))
                self.pai.c5 = valor
            return {"totalUpdatedCells": len(body["data"])}
        return _Pedido(f)


class Servico:
    """spreadsheets() falso: abas, a célula C5 e o histórico de escritas."""

    def __init__(self, c5="Antes", abas=None, erro_escrita=None):
        self.c5, self.abas, self.erro_escrita = c5, abas or {"F.D.SON. A": GID, "Outra": 7}, erro_escrita
        self.escritas = []

    def get(self, spreadsheetId, fields=None):
        return _Pedido(lambda: {"sheets": [{"properties": {"title": t, "sheetId": i}} for t, i in self.abas.items()]})

    def values(self):
        return _Valores(self)

    def nomes_escritos(self, planilha=None):
        return [v for (p, _r, v) in self.escritas if planilha in (None, p)]


class Creds:
    valid = True
    token = "TOKEN-SECRETO"


class Http:
    """requests.get falso: devolve PDFs (ou o que for programado, em ordem)."""

    def __init__(self, respostas=None):
        self.respostas, self.chamadas = list(respostas or []), []

    def __call__(self, url, headers=None, timeout=None):
        self.chamadas.append((url, headers))
        if self.respostas:
            r = self.respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return pdf_ok()


def pdf_ok(corpo=None):
    return SimpleNamespace(status_code=200, headers={"content-type": "application/pdf"}, content=corpo or _pdf_de_uma_pagina())


def resp(status, tipo="text/html", corpo=b"<html>"):
    return SimpleNamespace(status_code=status, headers={"content-type": tipo}, content=corpo)


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path / "dados" / "2026")
    (tmp_path / "dados" / "2026").mkdir(parents=True)
    (tmp_path / "dados" / "2026" / "turmas.json").write_text(json.dumps(TURMAS), encoding="utf-8")
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.setattr(qr_seguro, "arquivo_da_chave", lambda: tmp_path / "chave_qr.key")
    monkeypatch.delenv(qr_seguro.VARIAVEL_CHAVE, raising=False)
    monkeypatch.delenv("AUTO_SERE_PARECERES_INFANTIL_DIR", raising=False)
    monkeypatch.setattr(google_auth, "credenciais_configuradas", lambda: True)
    return tmp_path


@pytest.fixture()
def cadastradas(amb):
    registro.criar("INFANTIL IV - 2026 - PROF", URL4, "Pareceres do Infantil", finalidade=FIN, turma="INFANTIL 4 Integral A")
    registro.criar("INFANTIL V - 2026 - PROF", URL5, "Pareceres do Infantil", finalidade=FIN, turma="INFANTIL 5 Integral A")


def rodar(servico, http=None, **kw):
    http = http or Http()
    kw.setdefault("espera_s", 0)
    r = pp.gerar_pareceres_infantil_planilha(kw.pop("bimestre", "1"), abrir=lambda: (Creds(), servico), http_get=http,
                                             dormir=lambda s: None, **kw)
    return r, http


def pasta(amb, bim="1º Bimestre"):
    return amb / "dados" / "2026" / "PARECERES INFANTIL" / bim


# ───────────── preparação ─────────────

@pytest.mark.parametrize("entrada,esperado", [("1", "1º Bimestre"), ("3", "3º Bimestre"), (" 3 ", "3º Bimestre"), ("1º", "1º Bimestre"),
                                              ("3º Bimestre", "3º Bimestre")])
def test_rotulo_bimestre(entrada, esperado):
    assert pp.rotulo_bimestre(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", None, "2", "4", "13", "um", "5º"])
def test_rotulo_bimestre_invalido_aponta_o_rco(entrada):
    with pytest.raises(ValueError, match="1º ou 3º.*RCO"):
        pp.rotulo_bimestre(entrada)


def test_sem_planilha_cadastrada_explica_o_caminho(amb):
    with pytest.raises(ValueError, match="Planilhas do Drive.*Pareceres do Infantil"):
        pp.planilhas_do_cadastro()


def test_so_as_planilhas_ativas_com_a_finalidade_valem(amb):
    registro.criar("Ativa 4", URL4, finalidade=FIN, turma="INFANTIL 4 Integral A")
    registro.criar("Inativa 5", URL5, finalidade=FIN, turma="INFANTIL 5 Integral A", status="inativa")
    registro.criar("Só guardada", f"https://docs.google.com/spreadsheets/d/{'z' * 30}/edit")
    assert [p["nome"] for p in pp.planilhas_do_cadastro()] == ["Ativa 4"]


def test_alunos_da_turma_so_matriculados_na_ordem_da_chamada(amb):
    alunos = pp.alunos_da_turma(TURMAS, "infantil 4 integral a")            # sem diferenciar maiúsculas
    assert [(a["n_chamada"], a["nome"], a["cgm"]) for a in alunos] == [(1, "Ana Lima", "101"), (2, "Beto Souza", "102")]
    assert alunos[0]["turma"] == "INFANTIL 4 Integral A"                    # o nome como está em turmas.json


def test_turma_inexistente_lista_as_do_infantil(amb):
    with pytest.raises(ValueError, match=r"'INFANTIL 9'.*INFANTIL 4 Integral A, INFANTIL 5 Integral A"):
        pp.alunos_da_turma(TURMAS, "INFANTIL 9")


def test_validar_pedido_confere_tudo_antes_do_google(amb, cadastradas, monkeypatch):
    pp.validar_pedido("1")
    with pytest.raises(ValueError, match="1º ou 3º"):
        pp.validar_pedido("2")
    monkeypatch.setattr(google_auth, "credenciais_configuradas", lambda: False)
    with pytest.raises(ValueError, match="credenciais do Google.*GOOGLE_SHEETS"):
        pp.validar_pedido("1")


def test_validar_pedido_turma_cadastrada_que_nao_existe_em_turmas_json(amb):
    registro.criar("X", URL4, finalidade=FIN, turma="INFANTIL 9")
    with pytest.raises(ValueError, match="'INFANTIL 9'.*não existe em turmas.json"):
        pp.validar_pedido("3")


def test_validar_pedido_turma_sem_matriculados(amb):
    registro.criar("X", URL4, finalidade=FIN, turma="INFANTIL 4 Integral A")
    (amb / "dados" / "2026" / "turmas.json").write_text(json.dumps({"INFANTIL 4 Integral A": [_al("1", "X", 1, "Transferido")]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Nenhum aluno Matriculado"):
        pp.validar_pedido("1")


def test_url_de_exportacao():
    url = pp.montar_url_exportacao(ID4, GID)
    assert url.startswith(f"https://docs.google.com/spreadsheets/d/{ID4}/export?")
    assert "format=pdf" in url and f"gid={GID}" in url and "range=A1%3AN52" in url and "portrait=false" in url


# ───────────── exportação do PDF ─────────────

def test_exportar_pdf_envia_o_token_e_devolve_o_pdf():
    http = Http()
    assert pp.exportar_pdf("https://x", Creds(), http_get=http).startswith(b"%PDF")
    assert http.chamadas[0][1] == {"Authorization": "Bearer TOKEN-SECRETO"}


def test_exportar_pdf_tenta_de_novo_em_erro_transitorio():
    http, esperas = Http([resp(500), OSError("rede"), resp(403), pdf_ok()]), []
    assert pp.exportar_pdf("https://x", Creds(), http_get=http, tentativas=4, dormir=esperas.append).startswith(b"%PDF")
    assert len(http.chamadas) == 4 and len(esperas) == 3


def test_exportar_pdf_401_e_404_nao_repetem():
    for status, trecho in ((401, "google_token_drive.json"), (404, "não foi encontrada")):
        http = Http([resp(status), pdf_ok()])
        with pytest.raises(pp.ExportacaoErro, match=trecho):
            pp.exportar_pdf("https://x", Creds(), http_get=http)
        assert len(http.chamadas) == 1


def test_exportar_pdf_recusa_o_que_nao_e_pdf_e_nao_vaza_token():
    http = Http([resp(200, "text/html", b"<html>login</html>")] * 3)
    with pytest.raises(pp.ExportacaoErro, match="3 tentativa.*não é um PDF") as e:
        pp.exportar_pdf("https://x", Creds(), http_get=http, dormir=lambda s: None)
    assert "TOKEN-SECRETO" not in str(e.value) and "login" not in str(e.value)
    http = Http([resp(200, "application/pdf", b"nao e pdf")] * 3)
    with pytest.raises(pp.ExportacaoErro):
        pp.exportar_pdf("https://x", Creds(), http_get=http, dormir=lambda s: None)


# ───────────── QR no PDF ─────────────

def test_qr_usa_o_padrao_do_sistema_e_volta_a_ser_lido(amb):
    zxing = pytest.importorskip("zxingcpp")
    imagem = pp.gerar_qr_imagem("2026", 1, "Ana Lima", "INFANTIL 4 Integral A", "101")
    texto = zxing.read_barcodes(imagem)[0].text
    assert texto.startswith("AUTOSERE|PF2|")
    assert qr_seguro.ler(texto) == {"ano": "2026", "chamada": "1", "nome": "Ana Lima", "turma": "INFANTIL 4 Integral A", "cgm": "101"}


def test_inserir_qr_mantem_as_paginas_e_acrescenta_a_imagem(amb):
    original = _pdf_de_uma_pagina()
    novo = pp.inserir_qr_no_pdf(original, pp.gerar_qr_imagem("2026", 1, "Ana", "T", "101"))
    leitor = PdfReader(io.BytesIO(novo))
    assert len(leitor.pages) == 1 and len(novo) > len(original)
    assert len(list(leitor.pages[0].images)) == 1


def test_qr_vai_na_ultima_pagina(amb):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.drawString(10, 10, "p1")
    c.showPage()
    c.drawString(10, 10, "p2")
    c.save()
    leitor = PdfReader(io.BytesIO(pp.inserir_qr_no_pdf(buf.getvalue(), pp.gerar_qr_imagem("2026", 1, "A", "T", "1"))))
    assert len(leitor.pages) == 2 and len(list(leitor.pages[0].images)) == 0 and len(list(leitor.pages[1].images)) == 1


# ───────────── geração ─────────────

def test_gera_um_pdf_por_aluno_na_arvore_do_rco(amb, cadastradas):
    servico = Servico()
    r, http = rodar(servico)
    base = pasta(amb)
    assert sorted(p.relative_to(base).as_posix() for p in base.rglob("*.pdf")) == [
        "INFANTIL_4_Integral_A/1 - Ana_Lima.pdf", "INFANTIL_4_Integral_A/2 - Beto_Souza.pdf", "INFANTIL_5_Integral_A/1 - Caio_Dias.pdf"]
    assert r == {"total": 3, "gerados": 3, "pulados": 0, "falhas": [], "pasta": str(base)}
    assert not list(base.rglob("*.tmp"))
    assert all(len(PdfReader(str(p)).pages) == 1 and len(list(PdfReader(str(p)).pages[0].images)) == 1 for p in base.rglob("*.pdf"))
    assert all(f"gid={GID}" in url for url, _ in http.chamadas) and any(ID5 in url for url, _ in http.chamadas)


def test_escreve_o_nome_na_c5_de_cada_planilha_e_devolve_o_valor_de_antes(amb, cadastradas):
    servico = Servico(c5="Professora Fulana")
    rodar(servico)
    assert servico.nomes_escritos(ID4) == ["Ana Lima", "Beto Souza", "Professora Fulana"]
    assert servico.nomes_escritos(ID5) == ["Caio Dias", "Professora Fulana"]
    assert all(rng == "'F.D.SON. A'!C5" for _p, rng, _v in servico.escritas)


def test_devolve_c5_vazia_quando_estava_vazia(amb, cadastradas):
    servico = Servico(c5="")
    rodar(servico)
    assert servico.c5 == ""


def test_segunda_rodada_mantem_o_que_existe_e_substituir_refaz(amb, cadastradas):
    rodar(Servico())
    r, http = rodar(Servico())
    assert (r["gerados"], r["pulados"]) == (0, 3) and http.chamadas == []
    r, http = rodar(Servico(), substituir=True)
    assert (r["gerados"], r["pulados"]) == (3, 0) and len(http.chamadas) == 3


def test_modo_teste_faz_so_o_primeiro_de_cada_planilha(amb, cadastradas):
    r, _ = rodar(Servico(), modo_teste=True)
    assert r["gerados"] == 2
    assert sorted(p.name for p in pasta(amb).rglob("*.pdf")) == ["1 - Ana_Lima.pdf", "1 - Caio_Dias.pdf"]


def test_terceiro_bimestre_vai_para_a_outra_pasta(amb, cadastradas):
    rodar(Servico(), bimestre="3")
    assert len(list(pasta(amb, "3º Bimestre").rglob("*.pdf"))) == 3 and not pasta(amb).exists()


def test_pasta_de_destino_pode_ser_trocada_pelo_ambiente(amb, cadastradas, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_PARECERES_INFANTIL_DIR", str(amb / "rede"))
    rodar(Servico(), modo_teste=True)
    assert (amb / "rede" / "1º Bimestre" / "INFANTIL_4_Integral_A" / "1 - Ana_Lima.pdf").exists()


def test_falha_de_um_aluno_nao_para_os_outros(amb, cadastradas):
    http = Http([pdf_ok(), resp(200, "text/html"), resp(200, "text/html"), resp(200, "text/html"), pdf_ok()])
    r, _ = rodar(Servico(), http=http)
    assert r["gerados"] == 2 and len(r["falhas"]) == 1
    assert r["falhas"][0]["nome"] == "Beto Souza" and "PDF" in r["falhas"][0]["motivo"]
    assert not (pasta(amb) / "INFANTIL_4_Integral_A" / "2 - Beto_Souza.pdf").exists()


def test_aluno_sem_cgm_vira_falha_e_nao_gera(amb):
    registro.criar("X", URL4, finalidade=FIN, turma="INFANTIL 4 Integral A")
    (amb / "dados" / "2026" / "turmas.json").write_text(json.dumps({"INFANTIL 4 Integral A": [_al("", "Sem Cgm", 1), _al("5", "Com Cgm", 2)]}), encoding="utf-8")
    r, _ = rodar(Servico())
    assert r["gerados"] == 1 and r["falhas"] == [{"turma": "INFANTIL 4 Integral A", "nome": "Sem Cgm", "motivo": "sem CGM em turmas.json (o QR precisa dele)"}]


def test_sem_permissao_na_planilha_para_tudo_com_a_explicacao_e_tenta_devolver_c5(amb, cadastradas):
    from src.comum.google_sheets import SheetsAcessoErro
    servico = Servico(erro_escrita=403)
    with pytest.raises(SheetsAcessoErro, match="Compartilhe a planilha"):
        rodar(servico)
    assert list(pasta(amb).rglob("*.pdf")) == []


def test_aba_inexistente_diz_quais_abas_existem(amb, cadastradas):
    with pytest.raises(ValueError, match=r"Aba 'F.D.SON. A' não existe.*Outra"):
        rodar(Servico(abas={"Outra": 7}))


def test_cancelamento_interrompe_e_devolve_c5(amb, cadastradas, monkeypatch):
    from src.comum.execucao_gui import CancelamentoSolicitado
    chamadas = []

    def cancelar():
        chamadas.append(1)
        if len(chamadas) == 2:
            raise CancelamentoSolicitado()
    monkeypatch.setattr(pp, "verificar_cancelamento", cancelar)
    servico = Servico(c5="Antes")
    with pytest.raises(CancelamentoSolicitado):
        rodar(servico)
    assert servico.c5 == "Antes" and len(list(pasta(amb).rglob("*.pdf"))) == 1


# ───────────── cadastro: finalidade, turma e a planilha vigente ─────────────

def test_finalidade_exige_turma_e_turma_sem_finalidade_e_descartada(amb):
    with pytest.raises(ValueError, match="Informe a turma"):
        registro.criar("A", URL4, finalidade=FIN)
    with pytest.raises(ValueError, match="Finalidade inválida"):
        registro.criar("A", URL4, finalidade="outra", turma="T")
    assert registro.criar("A", URL4, turma="INFANTIL 4")["turma"] == ""


def test_so_uma_ativa_por_finalidade_e_turma(amb):
    velha = registro.criar("2026 1º bim", URL4, finalidade=FIN, turma="INFANTIL 4 Integral A")
    with pytest.raises(registro.PlanilhaEmConflito, match=r"'2026 1º bim' \(id 1\).*inativa"):
        registro.criar("2026 3º bim", URL5, finalidade=FIN, turma="infantil 4 integral a")
    registro.criar("Outra turma", URL5, finalidade=FIN, turma="INFANTIL 5 Integral A")          # outra turma: pode
    registro.atualizar(velha["id"], status="inativa")
    nova = registro.criar("2026 3º bim", f"https://docs.google.com/spreadsheets/d/{'n' * 30}/edit", finalidade=FIN, turma="INFANTIL 4 Integral A")
    vigentes = registro.planilhas_da_finalidade(FIN)
    assert [(p["id"], p["nome"]) for p in vigentes] == [(nova["id"], "2026 3º bim"), (2, "Outra turma")]   # por turma: 4 antes de 5
    with pytest.raises(registro.PlanilhaEmConflito):
        registro.atualizar(velha["id"], status="ativa")                                         # reativar a velha também conflita


def test_trocar_a_finalidade_para_nenhuma_limpa_a_turma(amb):
    item = registro.criar("A", URL4, finalidade=FIN, turma="INFANTIL 4 Integral A")
    novo = registro.atualizar(item["id"], finalidade="")
    assert novo["finalidade"] == "" and novo["turma"] == "" and registro.planilhas_da_finalidade(FIN) == []


def test_listar_filtra_por_finalidade_e_busca_pela_turma(amb):
    registro.criar("A", URL4, finalidade=FIN, turma="INFANTIL 4 Integral A")
    registro.criar("B", URL5)
    assert [i["nome"] for i in registro.listar(finalidade=FIN)["itens"]] == ["A"]
    assert [i["nome"] for i in registro.listar(q="integral")["itens"]] == ["A"]
    with pytest.raises(ValueError, match="Finalidade inválida"):
        registro.listar(finalidade="x")


def test_registro_antigo_sem_os_campos_novos_continua_valendo(amb):
    registro.criar("Antiga", URL4)
    arquivo = amb / "dados" / "planilhas" / "planilhas.json"
    tabela = json.loads(arquivo.read_text(encoding="utf-8"))
    for k in ("finalidade", "turma"):
        tabela["itens"][0].pop(k)
    arquivo.write_text(json.dumps(tabela), encoding="utf-8")
    assert registro.atualizar(1, nome="Antiga")["nome"] == "Antiga"
    assert registro.atualizar(1, categoria="Turmas")["finalidade"] == ""


def test_api_cadastra_com_finalidade_e_responde_conflito_409(amb):
    c = create_app().test_client()
    corpo = {"nome": "A", "link": URL4, "finalidade": FIN, "turma": "INFANTIL 4 Integral A"}
    assert c.post("/web/api/planilhas", json=corpo).status_code == 201
    r = c.post("/web/api/planilhas", json={**corpo, "nome": "B", "link": URL5})
    assert r.status_code == 409 and "ativa para Pareceres do Infantil" in r.get_json()["erro"]
    assert c.post("/web/api/planilhas", json={"nome": "C", "link": URL5, "finalidade": FIN}).status_code == 400
    assert c.get(f"/web/api/planilhas?finalidade={FIN}").get_json()["total"] == 1


def test_api_finalidades_traz_as_turmas_do_infantil(amb):
    d = create_app().test_client().get("/web/api/planilhas/finalidades").get_json()
    assert d["finalidades"] == [{"valor": FIN, "nome": "Pareceres do Infantil"}]
    assert d["turmas"] == ["INFANTIL 4 Integral A", "INFANTIL 5 Integral A"]


def test_api_finalidades_sem_turmas_json_devolve_lista_vazia(amb):
    (amb / "dados" / "2026" / "turmas.json").unlink()
    assert create_app().test_client().get("/web/api/planilhas/finalidades").get_json()["turmas"] == []


# ───────────── google_auth: token do Drive à parte ─────────────

def test_token_do_drive_fica_em_arquivo_proprio(monkeypatch, tmp_path):
    monkeypatch.setattr(google_auth, "CREDENCIAIS_DIR", tmp_path)
    monkeypatch.delenv("GOOGLE_TOKEN_FILE", raising=False)
    assert google_auth.caminho_token_drive() == tmp_path / "google_token_drive.json"
    assert google_auth.caminho_token_drive() != google_auth.caminho_token()
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "meu.json"))
    assert google_auth.caminho_token_drive() == tmp_path / "meu_drive.json"


def test_abrir_google_pede_planilhas_e_leitura_do_drive_com_o_token_proprio(monkeypatch, tmp_path):
    visto = {}

    def falsas(escopos=None, *, interativo=True, arquivo_token=None):
        visto.update(escopos=escopos, interativo=interativo, token=arquivo_token)
        return Creds()
    monkeypatch.setattr(google_auth, "obter_credenciais", falsas)
    monkeypatch.setattr(google_auth, "CREDENCIAIS_DIR", tmp_path)
    monkeypatch.delenv("GOOGLE_TOKEN_FILE", raising=False)
    import googleapiclient.discovery as disc
    monkeypatch.setattr(disc, "build", lambda *a, **k: SimpleNamespace(spreadsheets=lambda: "SERVICO"))
    creds, servico = pp.abrir_google(interativo=False)
    assert servico == "SERVICO" and visto == {"escopos": [google_auth.ESCOPO_SHEETS, google_auth.ESCOPO_DRIVE_LEITURA],
                                              "interativo": False, "token": tmp_path / "google_token_drive.json"}


# ───────────── registro, rotas e tela ─────────────

@pytest.fixture()
def web(amb, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: amb / "dados" / "2026")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


def test_registrada_e_na_lista_de_automacoes():
    assert reg.obter("parecer_planilha") is not None
    assert "parecer_planilha" not in rotas.AUTOMACOES_NAO_IMPLEMENTADAS
    assert any(i["chave"] == "parecer_planilha" for i in rotas.AUTOMACOES_DISPONIVEIS)


def test_extras_da_tela():
    extras = reg.obter("parecer_planilha").extras()
    sel = next(e for e in extras if e["tipo"] == "select")
    assert sel["nome"] == "bimestre" and [o["valor"] for o in sel["opcoes"]] == ["1", "3"]
    assert any(e["tipo"] == "caixa" and e["nome"] == "substituir" for e in extras)
    assert reg.obter("parecer_planilha").recursos == ("teste",)


def test_plano():
    plano = reg.obter("parecer_planilha").planejar(Opcoes(modo_teste=True), {"bimestre": "3", "substituir": True}, {}, {})
    assert plano.tipo == "sync" and plano.funcao is pp.gerar_pareceres_infantil_planilha
    assert plano.kwargs == {"bimestre": "3", "modo_teste": True, "substituir": True}


def test_executar_sem_bimestre_da_400(web):
    r = web.post("/web/api/automacoes/parecer_planilha/executar", json={})
    assert r.status_code == 400 and "1º ou 3º" in r.get_json()["mensagem"]


def test_executar_sem_planilha_cadastrada_da_400_com_o_caminho(web):
    r = web.post("/web/api/automacoes/parecer_planilha/executar", json={"bimestre": "1"})
    assert r.status_code == 400 and "Planilhas do Drive" in r.get_json()["mensagem"]


def test_a_tela_lista_a_automacao_no_menu():
    base = (paths.RAIZ_PROJETO / "src/web/templates/base.html").read_text(encoding="utf-8")
    assert 'data-auto="parecer_planilha"' in base
    js = (paths.RAIZ_PROJETO / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'parecer_planilha: "certificate"' in js
    form = (paths.RAIZ_PROJETO / "src/web/static/js/planilhas.js").read_text(encoding="utf-8")
    for ident in ("pl-f-fin", "pl-f-turma", "/finalidades"):
        assert ident in form

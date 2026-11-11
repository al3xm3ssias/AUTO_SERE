"""
Integração com o Google Sheets: autenticação (google_auth), operações (google_sheets), sincronização das turmas
(sincroniza_sheets) e encaixe no sistema (registro, rotas, CLI, wizard).

NADA aqui fala com o Google. A planilha é simulada em memória (FakeSheets) com as mesmas regras da API que importam
(intervalo limita o que é gravado, 404/403, leitura sem células vazias no fim). Há também testes com o cliente OFICIAL
(googleapiclient) sobre um transporte HTTP falso, que conferem os pedidos reais montados (endereço, parâmetros, corpo).
O que só se prova com credenciais reais está no fim do arquivo (marcado com skip).
"""
import json
import logging

import httplib2
import pytest
from googleapiclient.errors import HttpError

from src.automacao import sincroniza_sheets as sh
from src.comum import configuracao, google_auth as ga, google_sheets as gs, registro_scripts as reg
from src.web.api import rotas
from src.web.app import create_app

ID = "1DPyBHxA3rz-u1nxgCN9f_XosZrqyiR8zuy4ACqeGpgE"
URL = f"https://docs.google.com/spreadsheets/d/{ID}/edit#gid=0"


# ═════════════════════════ planilha falsa ═════════════════════════

def _http_erro(status, msg="x"):
    return HttpError(httplib2.Response({"status": status}), json.dumps({"error": {"message": msg}}).encode())


def _col(letras):
    return gs.coluna_para_indice(letras)


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class FakeSheets:
    """Imita spreadsheets() da API: grades por aba, só o que os módulos usam."""

    def __init__(self, abas=None, titulo="Planilha das turmas", erro=None):
        self.grades = {a: [list(l) for l in linhas] for a, linhas in (abas or {}).items()}
        self.titulo, self.erro, self.chamadas = titulo, erro, []

    # --- helpers
    def _checar(self, pid):
        if self.erro:
            raise self.erro
        if pid != ID and not pid.startswith("NOVA"):
            raise _http_erro(404)

    def _parse(self, rng):
        aba, _, cel = rng.rpartition("!")
        aba = aba.strip("'").replace("''", "'")
        if aba not in self.grades:
            raise _http_erro(400, f"Unable to parse range: {rng}")
        ini, _, fim = cel.partition(":")
        import re
        m1 = re.match(r"([A-Z]+)(\d*)$", ini)
        m2 = re.match(r"([A-Z]+)(\d*)$", fim) if fim else m1
        return aba, _col(m1[1]), int(m1[2]) if m1[2] else 1, _col(m2[1]), int(m2[2]) if m2[2] else None

    def _grade(self, aba, linha, col):
        g = self.grades[aba]
        while len(g) < linha:
            g.append([])
        while len(g[linha - 1]) <= col:
            g[linha - 1].append("")
        return g

    def celula(self, aba, ref):
        import re
        m = re.match(r"([A-Z]+)(\d+)$", ref)
        g = self.grades[aba]
        l, c = int(m[2]) - 1, _col(m[1])
        return g[l][c] if l < len(g) and c < len(g[l]) else ""

    # --- API
    def get(self, spreadsheetId, fields=None):
        def f():
            self._checar(spreadsheetId)
            return {"spreadsheetId": spreadsheetId, "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{spreadsheetId}/edit",
                    "properties": {"title": self.titulo}, "sheets": [{"properties": {"title": a}} for a in self.grades]}
        return _Req(f)

    def create(self, body, fields=None):
        def f():
            if self.erro:
                raise self.erro
            self.criada = body
            for s in body.get("sheets", [{"properties": {"title": "Página1"}}]):
                self.grades[s["properties"]["title"]] = []
            self.titulo = body["properties"]["title"]
            return {"spreadsheetId": "NOVA" + "x" * 30, "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/NOVA/edit",
                    "properties": {"title": self.titulo}, "sheets": [{"properties": {"title": a}} for a in self.grades]}
        return _Req(f)

    def values(self):
        return self

    def update(self, **kw):
        raise AssertionError("os módulos devem usar batchUpdate")

    def batchUpdate(self, spreadsheetId, body):
        def f():
            self._checar(spreadsheetId)
            self.chamadas.append(("batchUpdate", [d["range"] for d in body["data"]]))
            total = 0
            for d in body["data"]:
                aba, c1, r1, c2, r2 = self._parse(d["range"])
                for i, linha in enumerate(d["values"]):
                    if (r2 and r1 + i > r2) or len(linha) > c2 - c1 + 1:
                        raise _http_erro(400, "fora do intervalo")
                    g = self._grade(aba, r1 + i, c1 + len(linha) - 1)
                    for j, v in enumerate(linha):
                        g[r1 + i - 1][c1 + j] = v
                        total += 1
            return {"totalUpdatedCells": total}
        return _Req(f)

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        def f():
            self._checar(spreadsheetId)
            self.chamadas.append(("append", range))
            aba = range.rpartition("!")[0].strip("'")
            g = self.grades[aba]
            while g and not any(str(c) != "" for c in g[-1]):
                g.pop()
            for linha in body["values"]:
                g.append(list(linha))
            return {"updates": {"updatedRows": len(body["values"])}}
        return _Req(f)

    def get_valores(self, spreadsheetId, range, **kw):
        def f():
            self._checar(spreadsheetId)
            self.chamadas.append(("get", range, kw))
            aba, c1, r1, c2, r2 = self._parse(range)
            fim = c2
            saida = []
            for linha in self.grades[aba][r1 - 1:r2]:
                fatia = list(linha[c1:fim + 1])
                while fatia and fatia[-1] == "":
                    fatia.pop()
                saida.append(fatia)
            while saida and not saida[-1]:
                saida.pop()
            return {"values": saida} if saida else {}
        return _Req(f)


class _ValuesGet:
    """`values().get(...)` e `get(...)` (planilha) têm assinaturas diferentes na API real: separa pelo argumento `range`."""


def _fabricar(fake):
    original_get = fake.get

    def get(spreadsheetId, fields=None, range=None, **kw):
        if range is not None:
            return fake.get_valores(spreadsheetId, range, **kw)
        return original_get(spreadsheetId, fields)
    fake.get = get
    return fake


def nova(abas=None, **kw):
    return _fabricar(FakeSheets(abas, **kw))


# ═════════════════════════ dados de exemplo ═════════════════════════

TITULO_ABA = [["ESCOLA JUDITH"], [], ["Ano letivo 2026"], [], [], [], [], [], [], []]            # linhas 1-10
CAB = [list(sh.CABECALHOS)]


def aluno(n, cgm, nome, nasc="01/02/2018", sexo="Masculino", sit="Matriculado", data="10/02/2026", idade=8):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Sexo": sexo, "Situação": sit,
            "Data Matricula": data, "Idade": idade}


def linha(n, cgm, nome, nasc="01/02/2018", sexo="M", status="M", mat="10/02/2026", transf="", cpf="=CPF()", sus="SUS1", idade="=DATEDIF()", esc="E.M. X"):
    return [n, cpf, cgm, sus, nome, nasc, idade, sexo, status, mat, esc, transf]


def planilha_com(*linhas, aba="1º ANO"):
    return nova({aba: TITULO_ABA + CAB + [list(l) for l in linhas]})


TURMA = "1º Ano Integral A"


@pytest.fixture(autouse=True)
def _config_tmp(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    from src.comum import paths
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")


# ═════════════════════════ google_sheets: funções puras ═════════════════════════

def test_extrai_id_de_link_ou_id():
    assert gs.extrair_id_planilha(URL) == ID
    assert gs.extrair_id_planilha(ID) == ID
    assert gs.extrair_id_planilha(f"  https://docs.google.com/spreadsheets/u/1/d/{ID}/edit ") == ID


@pytest.mark.parametrize("ruim", ["", "abc", "https://exemplo.com/x", None])
def test_id_invalido_e_recusado_com_explicacao(ruim):
    with pytest.raises(gs.SheetsValidacaoErro, match="Planilha não reconhecida"):
        gs.extrair_id_planilha(ruim)
    assert issubclass(gs.SheetsValidacaoErro, ValueError)          # a tela/CLI tratam como pedido inválido


def test_colunas_a1():
    assert [gs.indice_para_coluna(i) for i in (0, 25, 26, 701)] == ["A", "Z", "AA", "ZZ"]
    assert gs.coluna_para_indice("AA") == 26
    assert gs.intervalo_a1("1º ANO", "E12") == "'1º ANO'!E12"
    assert gs.intervalo_a1("Aba d'água", "A1", "C2") == "'Aba d''água'!A1:C2"


def test_valores_validos_e_normalizados():
    assert gs.validar_valores([["a", 1, 2.5, True, None]]) == [["a", 1, 2.5, True, ""]]


@pytest.mark.parametrize("ruim", [[], "texto", ["a"], [[object()]], [["x" * 50001]]])
def test_valores_invalidos_sao_recusados_antes_de_enviar(ruim):
    with pytest.raises(gs.SheetsValidacaoErro):
        gs.validar_valores(ruim)


def test_texto_que_viraria_formula_e_gravado_como_texto():
    assert gs.validar_valores([["=1+1", "+55", "@x", "normal"]]) == [["'=1+1", "'+55", "'@x", "normal"]]
    assert gs.validar_valores([["=1+1"]], permitir_formulas=True) == [["=1+1"]]


def test_valores_que_nao_cabem_no_intervalo_sao_recusados():
    gs.validar_escrita("'A'!B2:C3", [["1", "2"], ["3", "4"]])
    with pytest.raises(gs.SheetsValidacaoErro, match="não cabem"):
        gs.validar_escrita("'A'!B2:C3", [["1", "2", "3"]])
    with pytest.raises(gs.SheetsValidacaoErro, match="não cabem"):
        gs.validar_escrita("'A'!B2:C3", [["1"]] * 3)
    with pytest.raises(gs.SheetsValidacaoErro, match="não cabem"):
        gs.validar_escrita("'A'!E5", [["1", "2"]])
    gs.validar_escrita("'A'!A2:C", [["1"]] * 500)                  # sem limite de linhas
    for ruim in ("'A'", "A", "'A'!C3:A1", "'A'!A5:C2", "lixo!!"):   # sem células = regravar a aba inteira: proibido
        with pytest.raises(gs.SheetsValidacaoErro):
            gs.validar_escrita(ruim, [["1"]])


def test_resolver_aba():
    abas = ["MENU", "1º ANO", "3º ANO A"]
    assert gs.resolver_aba("1º ANO", abas) == "1º ANO"
    assert gs.resolver_aba(" 1º ano ", abas) == "1º ANO"
    assert gs.resolver_aba("3º ano a", abas) == "3º ANO A"
    with pytest.raises(gs.SheetsValidacaoErro, match="não existe.*MENU"):
        gs.resolver_aba("9º ANO", abas)


# ═════════════════════════ google_sheets: operações ═════════════════════════

def test_verificar_planilha_existente():
    info = gs.verificar_planilha(URL, servico=nova({"A": [], "B": []}))
    assert info["id"] == ID and info["abas"] == ["A", "B"] and info["titulo"] == "Planilha das turmas"
    assert info["url"].startswith("https://docs.google.com/spreadsheets/d/")


def test_planilha_inexistente_e_sem_permissao_dao_mensagens_claras():
    with pytest.raises(gs.SheetsAcessoErro, match="não encontrada"):
        gs.verificar_planilha("2" * 44, servico=nova({"A": []}))
    with pytest.raises(gs.SheetsAcessoErro, match="Compartilhe a planilha"):
        gs.verificar_planilha(ID, servico=nova({"A": []}, erro=_http_erro(403, "The caller does not have permission")))
    with pytest.raises(gs.SheetsAcessoErro, match="não está ativada"):
        gs.verificar_planilha(ID, servico=nova({"A": []}, erro=_http_erro(403, "Google Sheets API has not been used in project 1 before or it is disabled")))
    with pytest.raises(gs.SheetsAutenticacaoErro, match="recusou as credenciais"):
        gs.verificar_planilha(ID, servico=nova({"A": []}, erro=_http_erro(401)))
    with pytest.raises(gs.SheetsErro, match="Limite de uso"):
        gs.verificar_planilha(ID, servico=nova({"A": []}, erro=_http_erro(429)))
    with pytest.raises(gs.SheetsErro, match="Sem conexão"):
        gs.verificar_planilha(ID, servico=nova({"A": []}, erro=ConnectionError("x")))


def test_intervalo_invalido_recusado_pelo_google_vira_erro_de_validacao():
    with pytest.raises(gs.SheetsValidacaoErro, match="recusou o pedido"):
        gs.ler_intervalo(ID, "'NaoExiste'!A:L", servico=nova({"A": []}))


def test_criar_planilha_com_cabecalhos():
    fake = nova()
    r = gs.criar_planilha("Turmas 2026", {"1º ANO": ["Nº", "Nome"], "2º ANO": []}, servico=fake)
    assert r["id"].startswith("NOVA") and r["url"].startswith("https://") and r["abas"] == ["1º ANO", "2º ANO"]
    assert fake.criada["properties"]["title"] == "Turmas 2026"
    assert fake.grades["1º ANO"] == [["Nº", "Nome"]] and fake.grades["2º ANO"] == []


@pytest.mark.parametrize("nome,estrutura", [("", None), ("x" * 251, None), ("ok", {"": []}), ("ok", {"A": [], "a": []})])
def test_criar_planilha_valida_nome_e_abas(nome, estrutura):
    with pytest.raises(gs.SheetsValidacaoErro):
        gs.criar_planilha(nome, estrutura, servico=nova())


def test_atualizar_intervalo_mexe_so_no_intervalo():
    fake = nova({"A": [["a1", "b1", "c1"], ["a2", "b2", "c2"], ["a3", "b3", "c3"]]})
    assert gs.atualizar_intervalo(ID, "'A'!B2", [["NOVO"]], servico=fake) == 1
    assert fake.grades["A"] == [["a1", "b1", "c1"], ["a2", "NOVO", "c2"], ["a3", "b3", "c3"]]


def test_atualizar_recusa_dados_maiores_que_o_intervalo_sem_enviar_nada():
    fake = nova({"A": [["a1", "b1"], ["a2", "b2"]]})
    with pytest.raises(gs.SheetsValidacaoErro):
        gs.atualizar_intervalos(ID, {"'A'!A1": [["ok"]], "'A'!B2": [["x", "y"]]}, servico=fake)
    assert fake.chamadas == [] and fake.grades["A"] == [["a1", "b1"], ["a2", "b2"]]      # nem o 1º (válido) foi enviado


def test_anexar_linhas_nao_mexe_nas_existentes():
    fake = nova({"A": [["x", "y"]]})
    assert gs.anexar_linhas(ID, "A", [["n1", "n2"], ["m1", "m2"]], servico=fake) == 2
    assert fake.grades["A"] == [["x", "y"], ["n1", "n2"], ["m1", "m2"]]
    assert gs.anexar_linhas(ID, "A", [], servico=fake) == 0


# ═════════════════════════ cliente OFICIAL sobre transporte falso ═════════════════════════

class HttpFalso:
    """Transporte HTTP que registra os pedidos reais montados pelo googleapiclient e devolve respostas prontas."""

    def __init__(self, *respostas):
        self.respostas, self.pedidos = list(respostas), []

    def request(self, uri, method="GET", body=None, headers=None, **kw):
        self.pedidos.append((method, uri, json.loads(body) if body else None))
        return httplib2.Response({"status": "200", "content-type": "application/json"}), json.dumps(self.respostas.pop(0)).encode()


def _cliente_real(http):
    from googleapiclient.discovery import build
    return build("sheets", "v4", http=http, developerKey="falsa", cache_discovery=False).spreadsheets()


def test_cliente_oficial_criar_e_atualizar_montam_pedidos_validos():
    http = HttpFalso(
        {"spreadsheetId": ID, "spreadsheetUrl": URL, "properties": {"title": "T"}, "sheets": [{"properties": {"title": "1º ANO"}}]},
        {"totalUpdatedCells": 2},
        {"totalUpdatedCells": 1},
        {"values": [["1", "x"]]},
        {"updates": {"updatedRows": 1}},
    )
    svc = _cliente_real(http)
    r = gs.criar_planilha("T", {"1º ANO": ["Nº", "Nome"]}, servico=svc)
    assert r["id"] == ID
    assert gs.atualizar_intervalo(ID, "'1º ANO'!E12", [["MARIA"]], servico=svc) == 1
    assert gs.ler_intervalo(ID, "'1º ANO'!A:L", servico=svc) == [["1", "x"]]
    assert gs.anexar_linhas(ID, "1º ANO", [["a"]], servico=svc) == 1

    (m1, u1, b1), (m2, u2, b2), (m3, u3, b3), (m4, u4, _), (m5, u5, b5) = http.pedidos
    assert m1 == "POST" and u1.startswith("https://sheets.googleapis.com/v4/spreadsheets?")
    assert b1["sheets"] == [{"properties": {"title": "1º ANO"}}]
    assert u2.split("?")[0].endswith(f"/spreadsheets/{ID}/values:batchUpdate")
    assert b2["valueInputOption"] == "USER_ENTERED" and b2["data"][0]["range"] == "'1º ANO'!A1:B1"
    assert b3["data"] == [{"range": "'1º ANO'!E12", "values": [["MARIA"]]}]
    assert m4 == "GET" and "valueRenderOption=UNFORMATTED_VALUE" in u4 and "dateTimeRenderOption=FORMATTED_STRING" in u4
    assert ":append" in u5 and "insertDataOption=INSERT_ROWS" in u5 and "valueInputOption=USER_ENTERED" in u5
    assert b5 == {"values": [["a"]]}


def test_abrir_servico_constroi_cliente_oficial_offline(monkeypatch):
    from google.auth.credentials import AnonymousCredentials
    monkeypatch.setattr(gs, "obter_credenciais", lambda escopos, interativo=True: AnonymousCredentials())
    svc = gs.abrir_servico()
    assert hasattr(svc, "values") and hasattr(svc, "create")


# ═════════════════════════ google_auth ═════════════════════════

@pytest.fixture()
def cred_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_CREDENTIALS", str(tmp_path / "cred.json"))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)
    return tmp_path


def test_caminhos_padrao_e_variaveis(monkeypatch, tmp_path):
    for v in ("GOOGLE_API_CREDENTIALS", "GOOGLE_CREDENTIALS_FILE", "GOOGLE_TOKEN_FILE"):
        monkeypatch.delenv(v, raising=False)
    assert ga.caminho_credenciais() == ga.CREDENCIAIS_DIR / "google_credentials.json"
    assert ga.caminho_token() == ga.CREDENCIAIS_DIR / "google_token.json"
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "pasta/antigo.json")                    # nome do antigo sheets_sync, relativo à raiz
    assert ga.caminho_credenciais() == ga.RAIZ_PROJETO / "pasta" / "antigo.json"
    monkeypatch.setenv("GOOGLE_API_CREDENTIALS", str(tmp_path / "novo.json"))             # a variável do projeto manda
    assert ga.caminho_credenciais() == tmp_path / "novo.json"


def test_detectar_modo(cred_env):
    arq = cred_env / "cred.json"
    assert ga.credenciais_configuradas() is False
    with pytest.raises(ga.CredenciaisGoogleErro, match="não encontrado"):
        ga.detectar_modo()
    arq.write_text("não é json", encoding="utf-8")
    with pytest.raises(ga.CredenciaisGoogleErro, match="não é um JSON válido"):
        ga.detectar_modo()
    arq.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    with pytest.raises(ga.CredenciaisGoogleErro, match="Aplicativo da Web"):
        ga.detectar_modo()
    arq.write_text(json.dumps({"qualquer": 1}), encoding="utf-8")
    with pytest.raises(ga.CredenciaisGoogleErro, match="não parece"):
        ga.detectar_modo()
    arq.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
    assert ga.detectar_modo() == "oauth" and ga.credenciais_configuradas()
    arq.write_text(json.dumps({"type": "service_account", "private_key": "SEGREDO"}), encoding="utf-8")
    assert ga.detectar_modo() == "service_account"


class CredFalsa:
    def __init__(self, valida=True, expirada=False, refresh="R"):
        self.valid, self.expired, self.refresh_token = valida, expirada, refresh
        self.renovou = False

    def refresh(self, request):
        self.renovou, self.valid = True, True

    def to_json(self):
        return json.dumps({"token": "TOKEN-SECRETO", "refresh_token": "REFRESH-SECRETO"})


def _oauth_pronto(cred_env):
    (cred_env / "cred.json").write_text(json.dumps({"installed": {"client_id": "i", "client_secret": "SEGREDO-CLIENTE"}}), encoding="utf-8")


def test_oauth_token_valido_e_reaproveitado(cred_env, monkeypatch):
    from google.oauth2.credentials import Credentials
    _oauth_pronto(cred_env)
    (cred_env / "token.json").write_text("{}", encoding="utf-8")
    cred = CredFalsa()
    monkeypatch.setattr(Credentials, "from_authorized_user_file", classmethod(lambda c, f, s=None: cred))
    assert ga.obter_credenciais() is cred


def test_oauth_renova_token_expirado_e_salva_sem_vazar_em_log(cred_env, monkeypatch, caplog):
    from google.oauth2.credentials import Credentials
    _oauth_pronto(cred_env)
    (cred_env / "token.json").write_text("{}", encoding="utf-8")
    cred = CredFalsa(valida=False, expirada=True)
    monkeypatch.setattr(Credentials, "from_authorized_user_file", classmethod(lambda c, f, s=None: cred))
    with caplog.at_level(logging.DEBUG):
        assert ga.obter_credenciais() is cred
    assert cred.renovou
    assert json.loads((cred_env / "token.json").read_text(encoding="utf-8"))["refresh_token"] == "REFRESH-SECRETO"
    texto = caplog.text
    for segredo in ("TOKEN-SECRETO", "REFRESH-SECRETO", "SEGREDO-CLIENTE"):
        assert segredo not in texto


def test_sem_autorizacao_e_modo_nao_interativo_nunca_abre_navegador(cred_env):
    _oauth_pronto(cred_env)
    with pytest.raises(ga.CredenciaisGoogleErro, match="não foi autorizado"):
        ga.obter_credenciais(interativo=False)


def test_oauth_primeira_autorizacao_salva_token(cred_env, monkeypatch, capsys):
    from google_auth_oauthlib.flow import InstalledAppFlow
    _oauth_pronto(cred_env)
    visto = {}

    class Fluxo:
        def run_local_server(self, **kw):
            visto.update(kw)
            return CredFalsa()
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", classmethod(lambda c, f, s: Fluxo()))
    monkeypatch.setenv("GOOGLE_OAUTH_ABRIR_NAVEGADOR", "0")
    ga.obter_credenciais()
    assert visto["open_browser"] is False and visto["port"] == 0 and visto["timeout_seconds"] == ga.TEMPO_MAXIMO_AUTORIZACAO_S
    assert (cred_env / "token.json").is_file()
    assert "endereço mostrado" in capsys.readouterr().out


def test_falha_na_autorizacao_nao_vaza_detalhes(cred_env, monkeypatch):
    from google_auth_oauthlib.flow import InstalledAppFlow
    _oauth_pronto(cred_env)

    class Fluxo:
        def run_local_server(self, **kw):
            raise RuntimeError("client_secret=SEGREDO-CLIENTE code=ABC")
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", classmethod(lambda c, f, s: Fluxo()))
    with pytest.raises(ga.CredenciaisGoogleErro) as e:
        ga.obter_credenciais()
    assert "SEGREDO" not in str(e.value) and "RuntimeError" in str(e.value)
    assert not (cred_env / "token.json").exists()


def test_conta_de_servico(cred_env, monkeypatch):
    from google.oauth2 import service_account
    (cred_env / "cred.json").write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        classmethod(lambda c, f, scopes=None: ("conta", scopes)))
    assert ga.obter_credenciais(interativo=False) == ("conta", [ga.ESCOPO_SHEETS])
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        classmethod(lambda c, f, scopes=None: (_ for _ in ()).throw(ValueError("private_key=SEGREDO"))))
    with pytest.raises(ga.CredenciaisGoogleErro) as e:
        ga.obter_credenciais()
    assert "SEGREDO" not in str(e.value)


def test_segredos_ficam_fora_do_git():
    from pathlib import Path
    gi = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "credenciais/google_*.json" in gi and "credenciais/*token*.json" in gi
    env = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    assert "GOOGLE_API_CREDENTIALS=\n" in env and "private_key" not in env


# ═════════════════════════ sincronização das turmas ═════════════════════════

def _sync(fake, alunos, **kw):
    return sh.sincronizar_turmas({TURMA: alunos}, ID, servico=fake, mapa={TURMA: "1º ANO"}, **kw)


def _escritas(fake):
    return [c for c in fake.chamadas if c[0] in ("batchUpdate", "append")]


def test_atualiza_so_a_celula_que_mudou_e_preserva_o_resto():
    antes = linha(1, "1000001", "MARIA SILVA")
    fake = planilha_com(antes)
    r = _sync(fake, [aluno(1, "1000001", "MARIA DA SILVA")])
    assert (r.atualizados, r.adicionados, r.erros) == (1, 0, [])
    assert fake.chamadas[-1] == ("batchUpdate", ["'1º ANO'!E12"])             # linha 12 = 10 de título + cabeçalho + 1ª
    linha_depois = fake.grades["1º ANO"][11]
    assert linha_depois[4] == "MARIA DA SILVA"
    for col in "BDGK":                                                         # CPF, SUS, Idade, Escola de origem: intactos
        assert linha_depois[_col(col)] == antes[_col(col)]
    assert fake.grades["1º ANO"][:11] == TITULO_ABA + CAB                      # título e cabeçalho intactos


def test_sem_mudanca_nao_grava_nada_e_segunda_execucao_e_idempotente():
    fake = planilha_com(linha(1, 1000001, "MARIA"), linha(2, "1000002", "JOAO"))               # CGM numérico e texto
    r = _sync(fake, [aluno(1, "1000001", "MARIA", sexo="Masculino"), aluno(2, "1000002", "JOAO")])
    assert (r.sem_mudanca, r.atualizados, r.adicionados) == (2, 0, 0)
    assert _escritas(fake) == []
    copia = json.dumps(fake.grades)
    _sync(fake, [aluno(1, "1000001", "MARIA"), aluno(2, "1000002", "JOAO")])
    assert json.dumps(fake.grades) == copia


def test_datas_iguais_em_formato_diferente_nao_contam_como_mudanca():
    fake = planilha_com(linha(1, "1000001", "MARIA", nasc="01/02/18"))
    assert _sync(fake, [aluno(1, "1000001", "MARIA", nasc="01/02/2018")]).sem_mudanca == 1


def test_cgm_que_o_google_devolve_como_float_e_achado():
    fake = planilha_com(linha(1, 1000001.0, "MARIA"))
    r = _sync(fake, [aluno(1, "1000001", "MARIA")])
    assert (r.sem_mudanca, r.adicionados) == (1, 0)


def test_matriculado_que_foi_transferido():
    fake = planilha_com(linha(1, "1000001", "MARIA"))
    r = _sync(fake, [aluno(1, "1000001", "MARIA", sit="Transferido", data="20/08/2026")])
    assert (r.transferidos, r.atualizados) == (1, 0)
    ln = fake.grades["1º ANO"][11]
    assert (ln[_col("I")], ln[_col("J")], ln[_col("H")], ln[_col("L")]) == ("T", "", "", "20/08/2026")
    assert ln[_col("G")] == "=DATEDIF()" and ln[_col("B")] == "=CPF()"


def test_aluno_novo_vai_para_o_fim_sem_tocar_nas_linhas_existentes():
    fake = planilha_com(linha(1, "1000001", "MARIA"))
    antes = json.dumps(fake.grades["1º ANO"])
    r = _sync(fake, [aluno(1, "1000001", "MARIA"), aluno(2, "1000009", "PEDRO", idade=7),
                     aluno(3, "1000010", "ANA", sit="Transferido", data="01/03/2026")])
    assert (r.adicionados, r.transferidos) == (2, 1)
    g = fake.grades["1º ANO"]
    assert json.dumps(g[:12]) == antes
    pedro, ana = g[12], g[13]
    assert (pedro[_col("C")], pedro[_col("E")], pedro[_col("I")], pedro[_col("G")], pedro[_col("B")]) == ("1000009", "PEDRO", "M", 7, "")
    assert (ana[_col("I")], ana[_col("L")], ana[_col("J")]) == ("T", "01/03/2026", "")


def test_cgm_repetido_no_json_vale_o_registro_mais_recente():
    fake = planilha_com(linha(3, "1000001", "FULANO", status="T", mat="", transf="31/03/2026", sexo=""))
    r = _sync(fake, [aluno(3, "1000001", "FULANO", sit="Transferido", data="31/03/2026"),
                     aluno(31, "1000001", "FULANO", sit="Matriculado", data="22/08/2026")])
    assert (r.atualizados, r.adicionados, r.transferidos) == (1, 0, 0)
    ln = fake.grades["1º ANO"][11]
    assert (ln[_col("A")], ln[_col("I")], ln[_col("J")], ln[_col("L")]) == (31, "M", "22/08/2026", "")


def test_aluno_sem_cgm_e_ignorado():
    fake = planilha_com()
    r = _sync(fake, [aluno(1, "", "SEM CGM")])
    assert (r.adicionados, r.atualizados) == (0, 0) and _escritas(fake) == []


def test_simulacao_le_mas_nao_grava():
    fake = planilha_com(linha(1, "1000001", "MARIA"))
    r = _sync(fake, [aluno(1, "1000001", "MARIA NOVA"), aluno(2, "1000002", "NOVO")], simulacao=True)
    assert (r.atualizados, r.adicionados) == (1, 1) and _escritas(fake) == []


def test_aba_ausente_nao_derruba_as_outras():
    fake = planilha_com(linha(1, "1000001", "MARIA"))
    turmas = {TURMA: [aluno(1, "1000001", "MARIA NOVA")], "9º Ano": [aluno(1, "2000001", "X")]}
    r = sh.sincronizar_turmas(turmas, ID, servico=fake, mapa={TURMA: "1º ANO"})
    assert r.atualizados == 1 and len(r.erros) == 1 and "9º Ano" in r.erros[0]


def test_sem_permissao_interrompe_tudo_com_mensagem_clara():
    fake = planilha_com()
    fake.erro = _http_erro(403, "caller does not have permission")
    with pytest.raises(gs.SheetsAcessoErro, match="Compartilhe"):
        _sync(fake, [aluno(1, "1000001", "MARIA")])


def test_mapa_de_abas_da_escola_e_configuravel():
    assert sh.mapa_abas()["3º Ano Integral B"] == "3º ANO B"
    configuracao._salvar_configuracao({**configuracao.carregar_configuracao(), "google_sheets": {"mapa_abas": {"3º Ano Integral B": "3B"}}})
    assert sh.mapa_abas()["3º Ano Integral B"] == "3B" and sh.mapa_abas()["1º Ano Integral A"] == "1º ANO"


# ─── executar_planilha_google: criar / atualizar / verificar ───

@pytest.fixture()
def servico_falso(monkeypatch):
    caixa = {}

    def abrir(**kw):
        return caixa["fake"]
    monkeypatch.setattr(gs, "abrir_servico", abrir)
    return caixa


def test_executar_criar_cria_estrutura_preenche_e_guarda_o_id(servico_falso):
    servico_falso["fake"] = fake = nova()
    r = sh.executar_planilha_google("criar", nome="Turmas 2026", turmas={TURMA: [aluno(1, "1000001", "MARIA")]})
    assert r["resumo"].adicionados == 1
    assert fake.criada["sheets"] == [{"properties": {"title": "1º ANO"}}]
    g = fake.grades["1º ANO"]
    assert g[0] == sh.CABECALHOS and g[1][_col("E")] == "MARIA"
    assert configuracao.planilha_google_id() == r["id"]


def test_executar_criar_simulado_nao_cria_nada(servico_falso):
    servico_falso["fake"] = fake = nova()
    sh.executar_planilha_google("criar", nome="X", turmas={TURMA: [aluno(1, "1000001", "M")]}, simulacao=True)
    assert not hasattr(fake, "criada") and fake.grades == {} and configuracao.planilha_google_id() == ""


def test_executar_atualizar_usa_planilha_lembrada_e_falha_se_houver_problema(servico_falso):
    servico_falso["fake"] = planilha_com(linha(1, "1000001", "MARIA"))
    configuracao.definir_planilha_google(ID)
    r = sh.executar_planilha_google("atualizar", turmas={TURMA: [aluno(1, "1000001", "MARIA")]})
    assert r["resumo"].sem_mudanca == 1
    with pytest.raises(gs.SheetsErro, match="1 problema"):                     # aba não existe → resultado parcial + falha
        sh.executar_planilha_google("atualizar", planilha=URL, turmas={"9º Ano": [aluno(1, "2000001", "X")]})


def test_executar_atualizar_lembra_o_id_digitado(servico_falso):
    servico_falso["fake"] = planilha_com()
    sh.executar_planilha_google("atualizar", planilha=URL, turmas={TURMA: []})
    assert configuracao.planilha_google_id() == ID


def test_executar_verificar_nao_grava(servico_falso):
    servico_falso["fake"] = fake = planilha_com(linha(1, "1000001", "MARIA"))
    info = sh.executar_planilha_google("verificar", planilha=ID)
    assert info["abas"] == ["1º ANO"] and _escritas(fake) == []


def test_pedido_invalido_e_recusado_antes_de_autenticar(monkeypatch):
    def nao_deve(**kw):
        raise AssertionError("não deveria autenticar")
    monkeypatch.setattr(gs, "abrir_servico", nao_deve)
    for kw in ({"operacao": "criar", "nome": " ", "turmas": {TURMA: []}},
               {"operacao": "atualizar", "turmas": {TURMA: []}},
               {"operacao": "atualizar", "planilha": "lixo", "turmas": {TURMA: []}},
               {"operacao": "apagar", "planilha": ID}):
        with pytest.raises(gs.SheetsValidacaoErro):
            sh.executar_planilha_google(**kw)


# ═════════════════════════ criação → cadastro "Planilhas do Drive" ═════════════════════════

def test_planilha_criada_e_cadastrada_em_planilhas_do_drive(servico_falso):
    from src.comum import planilhas_registro as pr
    servico_falso["fake"] = nova()
    r = sh.executar_planilha_google("criar", nome="Turmas 2026", turmas={TURMA: [aluno(1, "1000001", "MARIA")]})
    itens = pr.listar()["itens"]
    assert len(itens) == 1
    assert itens[0]["id"] == 1 and itens[0]["nome"] == "Turmas 2026" and itens[0]["origem"] == "sistema"
    assert itens[0]["planilha_id"] == r["id"] and itens[0]["link"].endswith("/edit") and itens[0]["categoria"] == "Turmas"
    assert configuracao.planilha_google_id() == r["id"]                       # a "última usada" continua funcionando


def test_criar_simulado_nao_cadastra_nada(servico_falso):
    from src.comum import planilhas_registro as pr
    servico_falso["fake"] = nova()
    sh.executar_planilha_google("criar", nome="X", turmas={TURMA: [aluno(1, "1000001", "M")]}, simulacao=True)
    assert pr.listar()["total"] == 0


def test_falha_ao_cadastrar_nao_derruba_a_criacao(servico_falso, monkeypatch):
    from src.comum import planilhas_registro as pr
    servico_falso["fake"] = nova()

    def quebra(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(pr, "registrar_planilha_criada", quebra)
    r = sh.executar_planilha_google("criar", nome="X", turmas={TURMA: [aluno(1, "1000001", "M")]})
    assert r["resumo"].adicionados == 1 and configuracao.planilha_google_id() == r["id"]


# ═════════════════════════ encaixe no sistema ═════════════════════════

TURMAS_JSON = {TURMA: [aluno(1, "1000001", "MARIA"), aluno(2, "1000002", "JOAO", sit="Transferido")], "2º Ano Integral A": [aluno(1, "2000001", "ANA")]}


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    (tmp_path / "turmas.json").write_text(json.dumps(TURMAS_JSON), encoding="utf-8")
    from src.comum import paths
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    planos = []
    monkeypatch.setattr(rotas, "_executar_plano", lambda chave, plano: planos.append((chave, plano)))
    return create_app().test_client(), planos


def _post(c, rota, **payload):
    return c.post(f"/web/api/automacoes/sheets/{rota}", json=payload)


def test_script_registrado_com_confirmacao_e_na_lista():
    s = reg.obter("sheets")
    assert s.confirmar and "turma" in s.recursos
    assert any(i["chave"] == "sheets" for i in rotas.AUTOMACOES_DISPONIVEIS)
    nomes = {c["nome"] for c in s.extras()}
    assert {"operacao", "planilha", "nome_planilha", "simulacao"} <= nomes


def test_rota_executar_monta_o_plano(ctx):
    c, planos = ctx
    r = _post(c, "executar", operacao="atualizar", planilha=URL, turmas=["1º Ano Integral A"], simulacao=True, confirmado=True)
    assert r.status_code in (200, 202), r.get_json()
    chave, plano = planos[0]
    assert chave == "sheets" and plano.tipo == "sync" and plano.funcao is sh.executar_planilha_google
    assert plano.kwargs["operacao"] == "atualizar" and plano.kwargs["planilha"] == URL and plano.kwargs["simulacao"] is True
    assert plano.kwargs["turmas_selecionadas"] == ["1º Ano Integral A"]
    assert "2 aluno(s) em 1 turma(s): 1 matriculado(s) e 1 transferido(s)" in plano.log_inicial


@pytest.mark.parametrize("payload,trecho", [
    ({"operacao": "atualizar", "planilha": ""}, "Informe o link ou o ID"),
    ({"operacao": "atualizar", "planilha": "lixo"}, "Planilha não reconhecida"),
    ({"operacao": "criar", "nome_planilha": " "}, "nome da nova planilha"),
    ({"operacao": "apagar", "planilha": ID}, "desconhecida"),
])
def test_rota_executar_recusa_pedido_invalido_com_mensagem(ctx, payload, trecho):
    c, planos = ctx
    r = _post(c, "executar", confirmado=True, **payload)
    assert r.status_code == 400 and trecho in json.dumps(r.get_json(), ensure_ascii=False) and planos == []


def test_previa_conta_matriculados_e_transferidos(ctx):
    c, _ = ctx
    r = _post(c, "previa", operacao="atualizar", planilha=ID, turmas=[])
    assert r.status_code == 200
    assert "3 aluno(s) em 2 turma(s): 2 matriculado(s) e 1 transferido(s)" in r.get_json()["texto"]


def test_cli_lista_e_simula_sem_chamar_o_google(monkeypatch, capsys):
    from src.comum import cli
    monkeypatch.setattr(cli, "carregar_turmas", lambda: TURMAS_JSON)

    def nao_deve(**kw):
        raise AssertionError("simulação não pode autenticar")
    monkeypatch.setattr(gs, "abrir_servico", nao_deve)
    assert cli.main(["listar"]) == 0 and "sheets" in capsys.readouterr().out
    assert cli.main(["sheets", "--planilha", URL, "--simular"]) == 0
    assert "executar_planilha_google" in capsys.readouterr().out
    assert cli.main(["sheets", "--operacao", "criar", "--simular"]) == 2          # falta o nome
    assert "nome da nova planilha" in capsys.readouterr().err


def test_wizard_google_api_reflete_e_trata_credenciais(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_API_CREDENTIALS", str(tmp_path / "cred.json"))
    c = create_app().test_client()
    assert c.get("/web/api/wizard/status").get_json()["google_api"] is False
    r = c.post("/web/api/wizard/google_api/executar", json={})
    assert r.status_code == 400 and "não encontrado" in r.get_json()["mensagem"]
    (tmp_path / "cred.json").write_text(json.dumps({"installed": {}}), encoding="utf-8")
    assert c.get("/web/api/wizard/status").get_json()["google_api"] is True
    chamadas = []
    monkeypatch.setattr(rotas, "_rodar_funcao_sincrona_em_thread", lambda chave, f, *a, **k: chamadas.append((chave, f)))
    r = c.post("/web/api/wizard/google_api/executar", json={})
    assert r.status_code == 200 and chamadas == [("wizard_google_api", gs.testar_autenticacao)]


# ═════════════════════════ só com credenciais reais ═════════════════════════

@pytest.mark.skip(reason="exige credenciais reais do Google (e abre o navegador na 1ª vez): rode  python -m src.comum.cli sheets "
                         "--operacao verificar --planilha <link>  e depois  --operacao atualizar --planilha <link> --simulacao")
def test_contra_o_google_de_verdade():
    pass

"""
Autorização do Google: copiar o link, escolher navegador/perfil e sugerir a conta (google_oauth_navegador).

Nada abre navegador de verdade nem mexe na área de transferência: subprocess, webbrowser e shutil.which são trocados por
falsos. O fluxo da biblioteca do Google é imitado (ela chama webbrowser.get(browser).open(url) e repassa **kwargs ao
endereço de autorização).
"""
import json
import subprocess
import webbrowser

import pytest

from src.comum import google_auth as ga, google_oauth_navegador as go

URL = "https://accounts.google.com/o/oauth2/auth?client_id=x&state=y"
VARIAVEIS = ("GOOGLE_OAUTH_COPIAR_LINK", "GOOGLE_OAUTH_ABRIR_NAVEGADOR", "GOOGLE_OAUTH_NAVEGADOR", "GOOGLE_OAUTH_PERFIL",
             "GOOGLE_OAUTH_NAVEGADOR_ARGS", "GOOGLE_OAUTH_CONTA", "GOOGLE_OAUTH_ESCOLHER_CONTA")


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for v in VARIAVEIS:
        monkeypatch.delenv(v, raising=False)


def _exe(tmp_path, *partes):
    caminho = tmp_path.joinpath(*partes)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("", encoding="utf-8")
    return str(caminho)


# ═════════════════════════ copiar para a área de transferência ═════════════════════════

def test_copia_o_texto_pelo_comando_do_sistema(monkeypatch):
    chamadas = []
    monkeypatch.setattr(go, "_comandos_de_copia", lambda: [["copiador", "--x"]])
    monkeypatch.setattr(go.shutil, "which", lambda c: f"/bin/{c}")
    monkeypatch.setattr(go.subprocess, "run", lambda cmd, **kw: chamadas.append((cmd, kw["input"])))
    assert go.copiar_para_area_de_transferencia(URL) is True
    assert chamadas == [(["copiador", "--x"], URL.encode("utf-8"))]


def test_tenta_o_proximo_comando_quando_um_falha(monkeypatch):
    usados = []

    def _run(cmd, **kw):
        usados.append(cmd[0])
        if cmd[0] == "ruim":
            raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(go, "_comandos_de_copia", lambda: [["ruim"], ["bom"]])
    monkeypatch.setattr(go.shutil, "which", lambda c: f"/bin/{c}")
    monkeypatch.setattr(go.subprocess, "run", _run)
    assert go.copiar_para_area_de_transferencia(URL) is True and usados == ["ruim", "bom"]


def test_sem_nenhum_comando_de_copia_devolve_falso_sem_quebrar(monkeypatch):
    monkeypatch.setattr(go.shutil, "which", lambda c: None)
    assert go.copiar_para_area_de_transferencia(URL) is False


def test_tempo_esgotado_na_copia_devolve_falso(monkeypatch):
    monkeypatch.setattr(go, "_comandos_de_copia", lambda: [["lento"]])
    monkeypatch.setattr(go.shutil, "which", lambda c: f"/bin/{c}")
    monkeypatch.setattr(go.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd, 5)))
    assert go.copiar_para_area_de_transferencia(URL) is False


# ═════════════════════════ localizar o navegador ═════════════════════════

def test_chrome_e_edge_sao_achados_nas_pastas_de_programas(monkeypatch, tmp_path):
    chrome = _exe(tmp_path, "pf", "Google", "Chrome", "Application", "chrome.exe")
    edge = _exe(tmp_path, "pf86", "Microsoft", "Edge", "Application", "msedge.exe")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setattr(go.shutil, "which", lambda c: None)
    assert go.localizar_navegador("chrome") == chrome and go.localizar_navegador("EDGE") == edge


def test_alias_cai_para_o_path_e_depois_para_none(monkeypatch, tmp_path):
    for v in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(go.shutil, "which", lambda c: "/usr/bin/google-chrome" if c == "google-chrome" else None)
    assert go.localizar_navegador("chrome") == "/usr/bin/google-chrome"
    monkeypatch.setattr(go.shutil, "which", lambda c: None)
    assert go.localizar_navegador("chrome") is None and go.localizar_navegador("") is None


def test_caminho_explicito_com_aspas_e_aceito(tmp_path):
    exe = _exe(tmp_path, "Meu Navegador", "nav.exe")
    assert go.localizar_navegador(f'"{exe}"') == exe
    assert go.localizar_navegador(str(tmp_path / "nao-existe.exe")) is None


# ═════════════════════════ comando do navegador e perfil ═════════════════════════

def test_nada_configurado_usa_o_navegador_padrao():
    assert go.comando_do_navegador() is None


def test_chrome_com_perfil(monkeypatch, tmp_path):
    chrome = _exe(tmp_path, "Google", "Chrome", "Application", "chrome.exe")
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", chrome)
    monkeypatch.setenv("GOOGLE_OAUTH_PERFIL", "Profile 2")
    assert go.comando_do_navegador() == [chrome, "--profile-directory=Profile 2"]


def test_so_o_perfil_assume_o_chrome(monkeypatch, tmp_path):
    chrome = _exe(tmp_path, "pf", "Google", "Chrome", "Application", "chrome.exe")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("GOOGLE_OAUTH_PERFIL", "Default")
    assert go.comando_do_navegador() == [chrome, "--profile-directory=Default"]


def test_edge_e_brave_usam_a_mesma_opcao_de_perfil(monkeypatch, tmp_path):
    for nome in ("msedge.exe", "brave.exe"):
        exe = _exe(tmp_path, nome)
        monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", exe)
        monkeypatch.setenv("GOOGLE_OAUTH_PERFIL", "Profile 1")
        assert go.comando_do_navegador() == [exe, "--profile-directory=Profile 1"]


def test_firefox_usa_a_opcao_de_perfil_dele(monkeypatch, tmp_path):
    exe = _exe(tmp_path, "firefox.exe")
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", exe)
    monkeypatch.setenv("GOOGLE_OAUTH_PERFIL", "Escola")
    assert go.comando_do_navegador() == [exe, "-P", "Escola"]


def test_perfil_em_navegador_desconhecido_avisa_e_ignora(monkeypatch, tmp_path):
    exe = _exe(tmp_path, "outro.exe")
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", exe)
    monkeypatch.setenv("GOOGLE_OAUTH_PERFIL", "X")
    avisos = []
    assert go.comando_do_navegador(avisos.append) == [exe] and "GOOGLE_OAUTH_NAVEGADOR_ARGS" in avisos[0]


def test_argumentos_extras_respeitam_aspas(monkeypatch, tmp_path):
    exe = _exe(tmp_path, "nav.exe")
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", exe)
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR_ARGS", '--incognito --profile-directory="Meu Perfil"')
    assert go.comando_do_navegador() == [exe, "--incognito", "--profile-directory=Meu Perfil"]


def test_aspas_abertas_nos_argumentos_sao_ignoradas_com_aviso(monkeypatch, tmp_path):
    exe = _exe(tmp_path, "nav.exe")
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", exe)
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR_ARGS", '--x "aberta')
    avisos = []
    assert go.comando_do_navegador(avisos.append) == [exe] and "aspas" in avisos[0]


def test_navegador_configurado_que_nao_existe_cai_no_padrao_com_aviso(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", "/nao/existe/nav.exe")
    avisos = []
    assert go.comando_do_navegador(avisos.append) is None and "não foi encontrado" in avisos[0]


# ═════════════════════════ conta ═════════════════════════

def test_sem_configuracao_nao_acrescenta_parametros():
    assert go.parametros_da_conta() == {} and go.conta_esperada() == ""


def test_conta_vira_login_hint_e_escolher_conta_vira_prompt(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CONTA", "escola@gmail.com")
    assert go.parametros_da_conta() == {"login_hint": "escola@gmail.com"}
    monkeypatch.setenv("GOOGLE_OAUTH_ESCOLHER_CONTA", "1")
    assert go.parametros_da_conta() == {"login_hint": "escola@gmail.com", "prompt": "select_account consent"}


def test_conta_com_espaco_e_ignorada(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CONTA", "escola @gmail.com")
    assert go.parametros_da_conta() == {}


# ═════════════════════════ o navegador que a biblioteca usa ═════════════════════════

class _Registro:
    def __init__(self, monkeypatch, copia=True):
        self.popen, self.padrao, self.falas = [], [], []
        monkeypatch.setattr(go.subprocess, "Popen", lambda cmd, **kw: self.popen.append(cmd))
        monkeypatch.setattr(go.webbrowser, "open", lambda url, **kw: self.padrao.append(url) or True)
        self.copiados = []
        monkeypatch.setattr(go, "copiar_para_area_de_transferencia", lambda t: self.copiados.append(t) or copia)


def test_modo_so_copiar_nao_abre_nada(monkeypatch):
    r = _Registro(monkeypatch)
    assert go.NavegadorAutorizacao(False, None, True, r.falas.append).open(URL) is False
    assert r.copiados == [URL] and r.popen == [] and r.padrao == [] and "COPIADO" in r.falas[0]


def test_modo_so_copiar_sem_area_de_transferencia_manda_copiar_o_endereco_mostrado(monkeypatch):
    r = _Registro(monkeypatch, copia=False)
    go.NavegadorAutorizacao(False, None, True, r.falas.append).open(URL)
    assert r.popen == [] and r.padrao == [] and "Copie o endereço mostrado" in r.falas[0]


def test_abre_no_navegador_e_perfil_configurados_e_copia(monkeypatch):
    r = _Registro(monkeypatch)
    assert go.NavegadorAutorizacao(True, ["chrome.exe", "--profile-directory=Profile 2"], True, r.falas.append).open(URL) is True
    assert r.popen == [["chrome.exe", "--profile-directory=Profile 2", URL]] and r.padrao == [] and r.copiados == [URL]


def test_sem_navegador_configurado_usa_o_padrao(monkeypatch):
    r = _Registro(monkeypatch)
    go.NavegadorAutorizacao(True, None, True, r.falas.append).open(URL)
    assert r.padrao == [URL] and r.popen == []


def test_copia_desligada_nao_toca_na_area_de_transferencia(monkeypatch):
    r = _Registro(monkeypatch)
    go.NavegadorAutorizacao(True, None, False, r.falas.append).open(URL)
    assert r.copiados == [] and r.padrao == [URL]


def test_falha_ao_abrir_o_navegador_configurado_cai_no_padrao(monkeypatch):
    r = _Registro(monkeypatch)
    monkeypatch.setattr(go.subprocess, "Popen", lambda cmd, **kw: (_ for _ in ()).throw(OSError("sem exe")))
    go.NavegadorAutorizacao(True, ["nav.exe"], True, r.falas.append).open(URL)
    assert r.padrao == [URL] and any("navegador padrão" in f for f in r.falas)


def test_navegador_padrao_que_volta_para_ele_mesmo_nao_entra_em_recursao(monkeypatch):
    r = _Registro(monkeypatch)
    nav = go.NavegadorAutorizacao(True, None, False, r.falas.append)
    monkeypatch.setattr(go.webbrowser, "open", lambda url, **kw: nav.open(url))        # o "padrão" é o próprio
    assert nav.open(URL) is False


def test_registro_e_removido_ao_terminar(monkeypatch):
    with go.navegador_de_autorizacao(False, lambda *_: None):
        assert isinstance(webbrowser.get(go.NOME_REGISTRADO), go.NavegadorAutorizacao)
    assert go.NOME_REGISTRADO not in webbrowser._browsers and go.NOME_REGISTRADO not in webbrowser._tryorder


def test_registro_e_removido_mesmo_com_erro(monkeypatch):
    with pytest.raises(RuntimeError):
        with go.navegador_de_autorizacao(False, lambda *_: None):
            raise RuntimeError("falhou")
    assert go.NOME_REGISTRADO not in webbrowser._browsers


# ═════════════════════════ encaixe no fluxo do google_auth ═════════════════════════

class CredFalsa:
    valid = True

    def to_json(self):
        return json.dumps({"token": "t", "refresh_token": "r"})


@pytest.fixture
def fluxo(monkeypatch, tmp_path):
    """Imita InstalledAppFlow: guarda o que recebe e, como a biblioteca, pede ao navegador registrado que abra o endereço."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    monkeypatch.setenv("GOOGLE_API_CREDENTIALS", str(tmp_path / "cred.json"))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)
    (tmp_path / "cred.json").write_text(json.dumps({"installed": {"client_id": "i", "client_secret": "s"}}), encoding="utf-8")
    visto = {}

    class Fluxo:
        def run_local_server(self, **kw):
            visto.update(kw)
            if kw["open_browser"]:
                webbrowser.get(kw["browser"]).open(URL, new=1, autoraise=True)
            return CredFalsa()
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", classmethod(lambda c, f, s: Fluxo()))
    return visto


def test_fluxo_padrao_copia_o_link_e_abre_o_navegador_padrao(fluxo, monkeypatch, capsys):
    r = _Registro(monkeypatch)
    ga.obter_credenciais()
    assert r.copiados == [URL] and r.padrao == [URL] and r.popen == []
    assert "login_hint" not in fluxo and "prompt" not in fluxo
    assert "COPIADO" in capsys.readouterr().out


def test_fluxo_com_navegador_perfil_e_conta_configurados(fluxo, monkeypatch, tmp_path, capsys):
    chrome = _exe(tmp_path, "Google", "Chrome", "Application", "chrome.exe")
    monkeypatch.setenv("GOOGLE_OAUTH_NAVEGADOR", chrome)
    monkeypatch.setenv("GOOGLE_OAUTH_PERFIL", "Profile 2")
    monkeypatch.setenv("GOOGLE_OAUTH_CONTA", "escola@gmail.com")
    monkeypatch.setenv("GOOGLE_OAUTH_ESCOLHER_CONTA", "1")
    r = _Registro(monkeypatch)
    ga.obter_credenciais()
    assert r.popen == [[chrome, "--profile-directory=Profile 2", URL]] and r.padrao == []
    assert fluxo["login_hint"] == "escola@gmail.com" and fluxo["prompt"] == "select_account consent"
    assert "Conta esperada: escola@gmail.com" in capsys.readouterr().out
    assert go.NOME_REGISTRADO not in webbrowser._browsers


def test_fluxo_so_copiar_nao_abre_nada_e_ainda_copia(fluxo, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_ABRIR_NAVEGADOR", "0")
    r = _Registro(monkeypatch)
    ga.obter_credenciais()
    assert r.copiados == [URL] and r.popen == [] and r.padrao == []


def test_fluxo_que_falha_remove_o_registro_do_navegador(fluxo, monkeypatch):
    from google_auth_oauthlib.flow import InstalledAppFlow

    class Quebra:
        def run_local_server(self, **kw):
            raise RuntimeError("segredo=ABC")
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", classmethod(lambda c, f, s: Quebra()))
    with pytest.raises(ga.CredenciaisGoogleErro):
        ga.obter_credenciais()
    assert go.NOME_REGISTRADO not in webbrowser._browsers


def test_o_link_nao_vai_para_o_log(fluxo, monkeypatch, caplog):
    import logging
    _Registro(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        ga.obter_credenciais()
    assert "client_id=x" not in caplog.text and "escola@gmail.com" not in caplog.text

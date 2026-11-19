"""
google_oauth_navegador.py — como o pedido de autorização do Google chega ao navegador certo
==========================================================================================
A autorização (Sheets, Contatos, Drive) precisa ser concedida por UMA conta Google específica, mas o navegador padrão
do computador costuma estar com outra conta ou outro perfil. Este módulo resolve isso sem mexer no resto do OAuth.
Tudo é opcional e configurado em `credenciais/.env` (veja `.env.example`):

  Copiar o link (ligado por padrão)
    GOOGLE_OAUTH_COPIAR_LINK=1        copia o endereço de autorização para a área de transferência: basta colar (Ctrl+V)
                                      na barra de endereço do navegador/perfil da conta certa. 0 desliga.
    GOOGLE_OAUTH_ABRIR_NAVEGADOR=0    não abre navegador nenhum: só copia e mostra o endereço.

  Abrir direto num navegador e perfil
    GOOGLE_OAUTH_NAVEGADOR=chrome     chrome, edge, firefox, brave, ou o caminho do .exe.
    GOOGLE_OAUTH_PERFIL="Profile 2"   pasta do perfil do Chrome/Edge/Brave (ou nome do perfil do Firefox). Sem
                                      GOOGLE_OAUTH_NAVEGADOR, assume o Chrome.
    GOOGLE_OAUTH_NAVEGADOR_ARGS=...   argumentos extras para o navegador (para quem precisa de algo além do perfil).

  Sugerir a conta ao Google
    GOOGLE_OAUTH_CONTA=nome@gmail.com            o Google já escolhe/preenche essa conta na tela de login.
    GOOGLE_OAUTH_ESCOLHER_CONTA=1                sempre mostra a lista de contas para escolher (e pede a permissão de novo).

Nada aqui lê nem guarda token, chave ou senha: o endereço de autorização é o mesmo que o programa já mostrava.
"""
from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Iterator, Optional

NOME_REGISTRADO = "auto_sere_google_oauth"
_FALSO = ("0", "false", "nao", "não", "no", "off")
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)                  # só existe no Windows (0 nos demais)

# nome amigável → (caminhos sob as pastas de programas do Windows, comandos no PATH, caminhos no macOS)
_NAVEGADORES = {
    "chrome": ([("Google", "Chrome", "Application", "chrome.exe")],
               ["google-chrome", "google-chrome-stable", "chrome", "chromium"],
               ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]),
    "edge": ([("Microsoft", "Edge", "Application", "msedge.exe")],
             ["microsoft-edge", "msedge"],
             ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]),
    "firefox": ([("Mozilla Firefox", "firefox.exe")], ["firefox"],
                ["/Applications/Firefox.app/Contents/MacOS/firefox"]),
    "brave": ([("BraveSoftware", "Brave-Browser", "Application", "brave.exe")],
              ["brave-browser", "brave"],
              ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]),
}


def _env(nome: str) -> str:
    return (os.getenv(nome) or "").strip()


def _ligado(nome: str, padrao: bool) -> bool:
    valor = _env(nome).lower()
    return padrao if not valor else valor not in _FALSO


# ───────────────────────────── conta ───────────────────────────────────────────

def conta_esperada() -> str:
    """E-mail da conta que deve autorizar (GOOGLE_OAUTH_CONTA), ou vazio."""
    conta = _env("GOOGLE_OAUTH_CONTA")
    return conta if conta and not any(c.isspace() for c in conta) else ""


def parametros_da_conta() -> dict:
    """Parâmetros extras do endereço de autorização: `login_hint` e/ou `prompt`. Vazio se nada foi configurado."""
    parametros: dict = {}
    if conta_esperada():
        parametros["login_hint"] = conta_esperada()
    if _ligado("GOOGLE_OAUTH_ESCOLHER_CONTA", False):
        parametros["prompt"] = "select_account consent"
    return parametros


# ───────────────────────────── navegador e perfil ──────────────────────────────

def localizar_navegador(valor: str) -> Optional[str]:
    """Caminho do executável para um nome amigável (chrome, edge, firefox, brave) ou para um caminho/comando. None se não achar."""
    valor = (valor or "").strip().strip('"').strip("'")
    if not valor:
        return None
    if valor.lower() in _NAVEGADORES:
        relativos, comandos, macs = _NAVEGADORES[valor.lower()]
        bases = [os.getenv(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData") if os.getenv(v)]
        for base in bases:
            for rel in relativos:
                candidato = Path(base, *rel)
                if candidato.is_file():
                    return str(candidato)
        for comando in comandos:
            achado = shutil.which(comando)
            if achado:
                return achado
        return next((m for m in macs if Path(m).is_file()), None)
    caminho = Path(os.path.expandvars(os.path.expanduser(valor)))
    return str(caminho) if caminho.is_file() else shutil.which(valor)


def comando_do_navegador(avisar: Callable[[str], None] = print) -> Optional[list[str]]:
    """
    Comando para abrir o endereço no navegador/perfil configurado ([executável, argumentos...]; o endereço entra no fim),
    ou None para usar o navegador padrão do computador.
    """
    valor, perfil, extras = _env("GOOGLE_OAUTH_NAVEGADOR"), _env("GOOGLE_OAUTH_PERFIL"), _env("GOOGLE_OAUTH_NAVEGADOR_ARGS")
    if not (valor or perfil or extras):
        return None
    pedido = valor or "chrome"
    exe = localizar_navegador(pedido)
    if not exe:
        avisar(f"⚠️ Navegador configurado ({pedido}) não foi encontrado; usando o navegador padrão. "
               "Confira GOOGLE_OAUTH_NAVEGADOR no credenciais/.env.")
        return None
    nome = Path(exe).name.lower()
    args: list[str] = []
    if perfil:
        if any(n in nome for n in ("chrome", "msedge", "chromium", "brave")):
            args.append(f"--profile-directory={perfil}")
        elif "firefox" in nome:
            args += ["-P", perfil]
        else:
            avisar("⚠️ GOOGLE_OAUTH_PERFIL só vale para Chrome, Edge, Brave e Firefox; "
                   "para outro navegador use GOOGLE_OAUTH_NAVEGADOR_ARGS.")
    if extras:
        try:
            args += shlex.split(extras)
        except ValueError:
            avisar("⚠️ GOOGLE_OAUTH_NAVEGADOR_ARGS está com aspas abertas; foi ignorado.")
    return [exe, *args]


# ───────────────────────────── copiar o link ───────────────────────────────────

def _comandos_de_copia() -> list[list[str]]:
    if sys.platform == "win32":
        return [["clip"]]
    if sys.platform == "darwin":
        return [["pbcopy"]]
    return [["clip.exe"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]   # clip.exe = WSL


def copiar_para_area_de_transferencia(texto: str) -> bool:
    """Copia o texto para a área de transferência do computador. False se não houver como (servidor sem tela, etc.)."""
    for comando in _comandos_de_copia():
        if not shutil.which(comando[0]):
            continue
        try:
            subprocess.run(comando, input=texto.encode("utf-8"), check=True, timeout=5, creationflags=_SEM_JANELA,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


# ───────────────────────────── o "navegador" que a biblioteca do Google usa ────

class NavegadorAutorizacao(webbrowser.BaseBrowser):
    """
    Entregue à biblioteca do Google no lugar do navegador padrão. Ao receber o endereço de autorização: copia para a área
    de transferência (se ligado) e abre no navegador/perfil configurado, no navegador padrão, ou em nenhum (`abrir=False`).
    """

    def __init__(self, abrir: bool, comando: Optional[list[str]] = None, copiar: bool = True,
                 falar: Callable[[str], None] = print):
        super().__init__(NOME_REGISTRADO)
        self.abrir, self.comando, self.copiar, self.falar = abrir, comando, copiar, falar
        self._em_uso = False                                  # impede recursão se o navegador padrão acabar sendo este

    def open(self, url, new=0, autoraise=True):
        copiado = self.copiar and copiar_para_area_de_transferencia(url)
        if copiado:
            self.falar("📋 Endereço de autorização COPIADO. Para usar outro navegador ou perfil, "
                       "cole (Ctrl+V) na barra de endereço dele.")
        if not self.abrir:
            if not copiado:
                self.falar("Copie o endereço mostrado abaixo e cole no navegador da conta certa.")
            return False
        if self.comando:
            try:
                subprocess.Popen([*self.comando, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=_SEM_JANELA)
                return True
            except OSError:
                self.falar("⚠️ Não consegui abrir o navegador configurado; usando o navegador padrão.")
        if self._em_uso:
            return False
        self._em_uso = True
        try:
            return webbrowser.open(url, new=1, autoraise=True)
        finally:
            self._em_uso = False


@contextlib.contextmanager
def navegador_de_autorizacao(abrir: bool, falar: Callable[[str], None] = print) -> Iterator[NavegadorAutorizacao]:
    """Registra o navegador de autorização durante o fluxo (use `browser=NOME_REGISTRADO`) e o remove ao terminar."""
    navegador = NavegadorAutorizacao(abrir, comando_do_navegador(falar) if abrir else None,
                                     _ligado("GOOGLE_OAUTH_COPIAR_LINK", True), falar)
    webbrowser.register(NOME_REGISTRADO, None, instance=navegador)
    try:
        yield navegador
    finally:
        with contextlib.suppress(Exception):
            webbrowser._browsers.pop(NOME_REGISTRADO.lower(), None)                      # type: ignore[attr-defined]
            if NOME_REGISTRADO in webbrowser._tryorder:                                  # type: ignore[attr-defined]
                webbrowser._tryorder.remove(NOME_REGISTRADO)                             # type: ignore[attr-defined]

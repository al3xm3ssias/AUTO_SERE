"""
google_navegador.py — em QUAL navegador/perfil abrir a autorização do Google
============================================================================
A autorização do Google (OAuth) abre uma página de login. Se o navegador padrão do computador estiver logado
em OUTRA conta, o Google pede a conta errada. Este módulo resolve isso de dois jeitos:

  1. Abre o endereço num navegador escolhido (Chrome, Edge, Firefox ou um .exe qualquer) e, nos navegadores
     baseados em Chromium, no PERFIL certo. O perfil pode ser escolhido pelo nome da pasta ("Profile 2") ou
     descoberto sozinho pelo e-mail da conta Google (o Chrome/Edge guardam o e-mail de cada perfil no arquivo
     "Local State").
  2. Se nada disso for configurado ou der errado, quem chama mostra o link para o usuário COPIAR e colar
     onde quiser (ver google_auth.autorizacao_pendente e a janela "Autorizar acesso ao Google" da tela).

Nada aqui lê senha, cookie ou histórico do navegador: só o nome e o e-mail dos perfis (Local State) para o
usuário escolher na lista. Nenhuma função levanta exceção por problema de ambiente: devolvem vazio/False.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

NAVEGADORES = ("chrome", "edge", "firefox")
ROTULOS = {"chrome": "Google Chrome", "edge": "Microsoft Edge", "firefox": "Mozilla Firefox"}

_EXE_WINDOWS = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}
_PASTAS_WINDOWS = {
    "chrome": [r"Google\Chrome\Application"],
    "edge": [r"Microsoft\Edge\Application"],
    "firefox": [r"Mozilla Firefox"],
}
_COMANDOS_UNIX = {
    "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
    "firefox": ("firefox",),
}
_APPS_MAC = {
    "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "firefox": "/Applications/Firefox.app/Contents/MacOS/firefox",
}


# ───────────────────────────── localizar o navegador ───────────────────────────

def _app_path_registro(exe: str) -> Path | None:
    """Caminho registrado pelo instalador do navegador (Windows: HKCU/HKLM → App Paths)."""
    if os.name != "nt":
        return None
    try:
        import winreg
        chave = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
        for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(raiz, chave) as k:
                    valor, _ = winreg.QueryValueEx(k, "")
                    if valor and Path(valor).is_file():
                        return Path(valor)
            except OSError:
                continue
    except Exception:                                              # noqa: BLE001
        pass
    return None


def localizar_navegador(nome: str) -> Path | None:
    """
    Executável de 'chrome' | 'edge' | 'firefox', ou o próprio caminho se `nome` for um arquivo existente.
    None se não achar.
    """
    nome = (nome or "").strip()
    if not nome:
        return None
    if nome.lower() not in NAVEGADORES:
        caminho = Path(nome).expanduser()
        return caminho if caminho.is_file() else None
    nome = nome.lower()
    if os.name == "nt":
        achado = _app_path_registro(_EXE_WINDOWS[nome])
        if achado:
            return achado
        bases = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for base in filter(None, bases):
            for rel in _PASTAS_WINDOWS[nome]:
                candidato = Path(base) / rel / _EXE_WINDOWS[nome]
                if candidato.is_file():
                    return candidato
        return None
    if sys.platform == "darwin" and Path(_APPS_MAC[nome]).is_file():
        return Path(_APPS_MAC[nome])
    for comando in _COMANDOS_UNIX[nome]:
        achado = shutil.which(comando)
        if achado:
            return Path(achado)
    return None


def navegadores_instalados() -> list[str]:
    return [n for n in NAVEGADORES if localizar_navegador(n)]


# ───────────────────────────── perfis do Chrome / Edge ─────────────────────────

def _pasta_dados_chromium(nome: str) -> Path | None:
    home = Path.home()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return None
        sub = {"chrome": r"Google\Chrome\User Data", "edge": r"Microsoft\Edge\User Data"}.get(nome)
        return Path(local) / sub if sub else None
    if sys.platform == "darwin":
        sub = {"chrome": "Google/Chrome", "edge": "Microsoft Edge"}.get(nome)
        return home / "Library" / "Application Support" / sub if sub else None
    sub = {"chrome": ".config/google-chrome", "edge": ".config/microsoft-edge"}.get(nome)
    return home / sub if sub else None


def listar_perfis(nome: str) -> list[dict]:
    """
    Perfis do Chrome/Edge: [{"pasta": "Profile 2", "nome": "Trabalho", "email": "fulano@gmail.com"}].
    `email` vem vazio se o perfil não está logado numa conta Google. Lista vazia para Firefox ou se não achar.
    """
    nome = (nome or "").strip().lower()
    base = _pasta_dados_chromium(nome)
    if base is None:
        return []
    try:
        dados = json.loads((base / "Local State").read_text(encoding="utf-8"))
        cache = (dados.get("profile") or {}).get("info_cache") or {}
    except (OSError, ValueError, AttributeError):
        return []
    perfis = []
    for pasta, info in cache.items():
        if not isinstance(info, dict):
            continue
        perfis.append({"pasta": str(pasta), "nome": str(info.get("name") or pasta),
                       "email": str(info.get("user_name") or "").strip()})
    perfis.sort(key=lambda p: (p["pasta"] != "Default", p["pasta"].lower()))
    return perfis


def perfil_da_conta(nome: str, email: str) -> str:
    """Pasta do perfil do Chrome/Edge logado em `email` ('' se nenhum perfil tiver esse e-mail)."""
    alvo = (email or "").strip().lower()
    if not alvo:
        return ""
    for perfil in listar_perfis(nome):
        if perfil["email"].lower() == alvo:
            return perfil["pasta"]
    return ""


# ───────────────────────────── abrir o endereço ────────────────────────────────

def _escolher_navegador(navegador: str, conta: str) -> str:
    """'chrome' | 'edge' | 'firefox' | caminho | '' (= nenhum específico → navegador padrão do sistema).
    Sem escolha mas COM conta: se algum perfil de Chrome/Edge for dessa conta, usa esse navegador."""
    navegador = (navegador or "").strip()
    if navegador and navegador.lower() not in ("padrao", "padrão", "automatico", "automático"):
        return navegador
    if conta:
        for candidato in ("chrome", "edge"):
            if localizar_navegador(candidato) and perfil_da_conta(candidato, conta):
                return candidato
    return ""


def abrir_url(url: str, *, navegador: str = "", perfil: str = "", conta: str = "") -> tuple[bool, str]:
    """
    Abre `url`. Devolve (abriu, descrição curta do que foi usado — sem o endereço).
    Ordem: navegador escolhido (+ perfil escolhido, ou o perfil logado em `conta`) → navegador padrão do sistema.
    """
    if not url.lower().startswith(("https://", "http://")):
        return False, "endereço inválido"
    escolhido = _escolher_navegador(navegador, conta)
    exe = localizar_navegador(escolhido) if escolhido else None
    if escolhido and exe is None:
        log.warning("Navegador '%s' não encontrado; usando o navegador padrão do sistema.", escolhido)

    if exe is not None:
        chave = escolhido.lower() if escolhido.lower() in NAVEGADORES else _tipo_pelo_exe(exe)
        args = [str(exe)]
        descricao = ROTULOS.get(chave, exe.stem)
        if chave in ("chrome", "edge"):
            pasta = (perfil or "").strip() or perfil_da_conta(chave, conta)
            if pasta:
                args.append(f"--profile-directory={pasta}")
                descricao += f", perfil “{_nome_do_perfil(chave, pasta)}”"
            args.append(url)
        elif chave == "firefox":
            if (perfil or "").strip():
                args += ["-P", perfil.strip()]
                descricao += f", perfil “{perfil.strip()}”"
            args += ["-new-tab", url]
        else:
            args.append(url)
        try:
            _executar_destacado(args)
            return True, descricao
        except OSError as exc:
            log.warning("Não consegui abrir %s (%s); usando o navegador padrão do sistema.", exe.name, type(exc).__name__)

    try:
        return bool(webbrowser.open(url, new=1)), "navegador padrão do sistema"
    except Exception:                                              # noqa: BLE001
        return False, "nenhum navegador disponível"


def _tipo_pelo_exe(exe: Path) -> str:
    nome = exe.name.lower()
    if "chrome" in nome or "chromium" in nome:
        return "chrome"
    if "msedge" in nome or "edge" in nome:
        return "edge"
    if "firefox" in nome:
        return "firefox"
    return ""


def _nome_do_perfil(nome: str, pasta: str) -> str:
    for perfil in listar_perfis(nome):
        if perfil["pasta"] == pasta:
            return perfil["nome"]
    return pasta


def _executar_destacado(args: list[str]) -> None:
    """Dispara o navegador sem esperar ele fechar e sem prender o terminal/servidor."""
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)

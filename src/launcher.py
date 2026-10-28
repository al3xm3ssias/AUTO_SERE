"""
launcher.py — abre o AUTO SERE como aplicativo (Windows)
=========================================================
Fluxo (o que o atalho "AUTO SERE" executa):

    atalho → pythonw -m src.launcher
               ├─ já existe servidor respondendo?  → só abre a janela
               ├─ não existe → sobe o servidor (sem janela de console),
               │               espera ele responder e abre a janela
               └─ abre o Chrome em modo aplicativo (--app=URL):
                  janela própria, sem abas nem barra de endereço

Garantias:
  • Duplo clique no atalho NÃO cria um segundo servidor: antes de subir,
    o launcher pergunta ao servidor (GET /web/api/ping). Um lock de curta
    duração cobre o intervalo em que o servidor ainda está iniciando.
  • Se a porta estiver ocupada por OUTRO programa, avisa em vez de falhar
    em silêncio.
  • Como roda sem console (pythonw), erros vão para logs/launcher.log e
    para uma caixa de mensagem do Windows.

Uso:
    python -m src.launcher             # inicia (se preciso) e abre a janela
    python -m src.launcher --parar     # encerra o servidor iniciado por ele
    python -m src.launcher --sem-janela  # só garante o servidor (sem Chrome)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

from src.comum import paths
from src.comum import servidor

PID_ARQUIVO = paths.LOCKS_DIR / "servidor.pid"
LOCK_ARQUIVO = paths.LOCKS_DIR / "launcher.lock"
LOG_LAUNCHER = paths.LOGS_DIR / "launcher.log"
LOG_SERVIDOR = paths.LOGS_DIR / "servidor.log"

LOCK_VALIDADE_S = 60        # lock mais velho que isso é considerado abandonado
ESPERA_SERVIDOR_S = 45      # tempo máximo para o servidor responder ao ping

# Flags de criação de processo (só existem no Windows).
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


# ─────────────────────────────── utilitários ────────────────────────────────

def _log(msg: str) -> None:
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_LAUNCHER, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def _aviso(titulo: str, texto: str) -> None:
    """Caixa de mensagem do Windows (o launcher roda sem console)."""
    _log(f"AVISO: {titulo} — {texto}")
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, texto, titulo, 0x10)  # ícone de erro
            return
        except Exception:
            pass
    print(f"{titulo}: {texto}", file=sys.stderr)


def _ping(timeout: float = 1.0) -> bool:
    """True se há um AUTO SERE respondendo na URL configurada."""
    try:
        with urllib.request.urlopen(f"{servidor.url_base()}/web/api/ping", timeout=timeout) as r:
            dados = json.loads(r.read().decode("utf-8"))
        return dados.get("app") == "auto-sere"
    except Exception:
        return False


def _porta_ocupada() -> bool:
    """
    True se a porta configurada já está em uso por alguém.

    Testa com bind() em vez de connect(): no Windows, conectar numa porta
    FECHADA pode demorar ~2 s para falhar (o que daria falso positivo com
    timeout curto), e um servidor que não aceita conexões também engana o
    connect(). O bind falha de forma imediata e inequívoca quando a porta
    está ocupada. SO_REUSEADDR só em POSIX (no Windows ele permitiria
    "roubar" uma porta ativa).
    """
    host = servidor.servidor_host()
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, servidor.servidor_porta()))
        except OSError:
            return True
    return False


# ──────────────────────────── lock de inicialização ──────────────────────────

def _adquirir_lock() -> bool:
    """Lock de curta duração: impede dois launchers de subirem o servidor juntos."""
    paths.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(LOCK_ARQUIVO), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return True
        except FileExistsError:
            try:
                idade = time.time() - LOCK_ARQUIVO.stat().st_mtime
            except OSError:
                continue
            if idade > LOCK_VALIDADE_S:       # lock abandonado (launcher morreu)
                try:
                    LOCK_ARQUIVO.unlink()
                except OSError:
                    pass
                continue
            return False
    return False


def _liberar_lock() -> None:
    try:
        LOCK_ARQUIVO.unlink()
    except OSError:
        pass


# ─────────────────────────────────── servidor ────────────────────────────────

def _python_do_servidor() -> str:
    """Prefere python.exe (com stdout redirecionado) ao pythonw.exe do launcher."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidato = exe.with_name("python.exe")
        if candidato.exists():
            return str(candidato)
    return str(exe)


def ambiente_do_servidor() -> dict:
    """Variáveis de ambiente do processo do servidor."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"                 # evita UnicodeEncodeError (cp1252) em print/log
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("AUTO_SERE_DEBUG", None)        # nunca com reloader a partir do launcher
    # Navegadores do Playwright instalados pelo INSTALAR_WINDOWS ficam em
    # runtime/browsers (junto do projeto). Sem isso o Playwright procuraria
    # em %LOCALAPPDATA%\ms-playwright e não os acharia.
    navegadores = paths.RAIZ_PROJETO / "runtime" / "browsers"
    if navegadores.is_dir() and not env.get("PLAYWRIGHT_BROWSERS_PATH"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(navegadores)
    return env


def iniciar_servidor() -> subprocess.Popen:
    """Sobe `python -m src.web.app` sem janela, com log em logs/servidor.log."""
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    env = ambiente_do_servidor()
    saida = open(LOG_SERVIDOR, "ab")
    saida.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} iniciando servidor ===\n".encode("utf-8"))
    saida.flush()
    flags = 0
    if os.name == "nt":
        flags = _CREATE_NO_WINDOW | _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [_python_do_servidor(), "-m", "src.web.app"],
        cwd=str(paths.RAIZ_PROJETO),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=saida,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )
    try:
        PID_ARQUIVO.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass
    _log(f"servidor iniciado (pid {proc.pid}) em {servidor.url_base()}")
    return proc


def _esperar_servidor(proc: subprocess.Popen | None) -> bool:
    limite = time.time() + ESPERA_SERVIDOR_S
    while time.time() < limite:
        if _ping():
            return True
        if proc is not None and proc.poll() is not None:
            return False                    # o servidor morreu ao subir
        time.sleep(0.4)
    return False


def garantir_servidor() -> bool:
    """Deixa um servidor respondendo. Devolve True se conseguiu."""
    if _ping():
        _log("servidor já estava rodando")
        return True

    if not _adquirir_lock():
        # Outro launcher está subindo o servidor agora: só espera.
        _log("outro launcher está iniciando o servidor; aguardando")
        return _esperar_servidor(None)

    try:
        if _ping():
            return True
        if _porta_ocupada():
            _aviso(
                "AUTO SERE",
                f"A porta {servidor.servidor_porta()} já está em uso por outro programa.\n\n"
                "Feche esse programa ou mude a porta (variável AUTO_SERE_PORT ou a chave "
                '"servidor" em config/config_usuario.json).',
            )
            return False
        proc = iniciar_servidor()
        if _esperar_servidor(proc):
            return True
        _aviso(
            "AUTO SERE",
            "O servidor não respondeu a tempo.\n\n"
            f"Veja o motivo em:\n{LOG_SERVIDOR}",
        )
        return False
    finally:
        _liberar_lock()


def parar_servidor() -> int:
    """Encerra o servidor iniciado pelo launcher (usa o pid gravado)."""
    if not PID_ARQUIVO.exists():
        print("Nenhum servidor registrado.")
        return 0
    try:
        pid = int(PID_ARQUIVO.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        PID_ARQUIVO.unlink(missing_ok=True)
        print("Registro de pid inválido; removido.")
        return 1
    if os.name == "nt":
        # /T mata também os processos filhos (ex.: navegadores do Playwright).
        resultado = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        ok = resultado.returncode == 0
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
            ok = True
        except OSError:
            ok = False
    PID_ARQUIVO.unlink(missing_ok=True)
    print("Servidor encerrado." if ok else "Não foi possível encerrar (talvez já estivesse parado).")
    _log(f"parar_servidor pid={pid} ok={ok}")
    return 0 if ok else 1


# ─────────────────────────────────── navegador ───────────────────────────────

def _candidatos_navegador(exe: str, pastas_relativas: list[str]) -> list[Path]:
    bases = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    return [Path(b) / rel / exe for b in bases if b for rel in pastas_relativas]


def _app_path_registro(exe: str) -> Path | None:
    """Caminho registrado pelo instalador (HKCU/HKLM → App Paths)."""
    if os.name != "nt":
        return None
    try:
        import winreg

        chave = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
        for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(raiz, chave) as k:
                    valor, _ = winreg.QueryValueEx(k, "")
                    if valor and Path(valor).exists():
                        return Path(valor)
            except OSError:
                continue
    except Exception:
        pass
    return None


def localizar_chrome() -> Path | None:
    """Chrome: AUTO_SERE_CHROME → registro do Windows → pastas padrão."""
    manual = os.environ.get("AUTO_SERE_CHROME")
    if manual and Path(manual).exists():
        return Path(manual)
    achado = _app_path_registro("chrome.exe")
    if achado:
        return achado
    for c in _candidatos_navegador("chrome.exe", [r"Google\Chrome\Application"]):
        if c.exists():
            return c
    return None


def localizar_edge() -> Path | None:
    """Edge (também Chromium; aceita --app). Só usado se não houver Chrome."""
    achado = _app_path_registro("msedge.exe")
    if achado:
        return achado
    for c in _candidatos_navegador("msedge.exe", [r"Microsoft\Edge\Application"]):
        if c.exists():
            return c
    return None


def abrir_janela(url: str) -> bool:
    """Abre `url` em janela de aplicativo. Devolve True se abriu."""
    chrome = localizar_chrome()
    navegador, nome = chrome, "Chrome"
    if navegador is None:
        navegador, nome = localizar_edge(), "Edge"
        if navegador is not None:
            _log("Chrome não encontrado; usando Edge (Chromium) em modo aplicativo")
    if navegador is None:
        _log("nenhum navegador Chromium encontrado; abrindo no navegador padrão")
        webbrowser.open(url)
        return False
    flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        [str(navegador), f"--app={url}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    _log(f"janela aberta com {nome}: {url}")
    return True


# ─────────────────────────────────── principal ───────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Launcher do AUTO SERE")
    ap.add_argument("--parar", action="store_true", help="encerra o servidor iniciado pelo launcher")
    ap.add_argument("--sem-janela", action="store_true", help="só garante o servidor, sem abrir o Chrome")
    args = ap.parse_args(argv)

    if args.parar:
        return parar_servidor()

    try:
        paths.garantir_diretorios_runtime()
        if not garantir_servidor():
            return 1
        if not args.sem_janela:
            abrir_janela(servidor.url_base() + "/web")
        return 0
    except Exception:
        _aviso("AUTO SERE", "Erro inesperado ao iniciar:\n\n" + traceback.format_exc(limit=3))
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""
dialogo_pasta.py — janela nativa para escolher uma pasta
=========================================================
No Windows usa o seletor de pastas do próprio sistema (Windows Forms via
PowerShell, que existe em qualquer Windows). Isso evita depender do tkinter,
que não vem no Python "embutível" usado pelo instalador do AUTO SERE.
Fora do Windows (WSL/Linux) cai para o tkinter, como era antes.
"""
from __future__ import annotations

import base64
import os
import subprocess

_CREATE_NO_WINDOW = 0x08000000


def script_powershell(titulo: str) -> str:
    """Script do diálogo. O título entra entre aspas simples (apóstrofo vira '')."""
    t = (titulo or "Selecione a pasta").replace("'", "''")
    return (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
        "Add-Type -AssemblyName System.Windows.Forms;"
        # janela-dona invisível e "sempre no topo": o diálogo aparece NA FRENTE do Chrome
        "$f = New-Object System.Windows.Forms.Form;"
        "$f.TopMost = $true; $f.ShowInTaskbar = $false; $f.Opacity = 0; $f.Show();"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$d.Description = '{t}'; $d.ShowNewFolderButton = $true;"
        "if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Out.Write($d.SelectedPath) };"
        "$f.Dispose()"
    )


def _comando_powershell(titulo: str) -> list[str]:
    # -EncodedCommand (UTF-16LE em base64) evita qualquer problema de aspas/acentos.
    codificado = base64.b64encode(script_powershell(titulo).encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-STA",
            "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado]


def _via_powershell(titulo: str) -> str | None:
    r = subprocess.run(
        _comando_powershell(titulo),
        capture_output=True,
        timeout=900,
        creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or f"PowerShell código {r.returncode}")
    caminho = r.stdout.decode("utf-8-sig", "replace").strip()
    return caminho or None


def _via_tkinter(titulo: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    try:
        return filedialog.askdirectory(title=titulo) or None
    finally:
        root.destroy()


def escolher_pasta(titulo: str = "Selecione a pasta") -> str | None:
    """Abre o seletor e devolve o caminho escolhido, ou None se o usuário cancelou."""
    if os.name == "nt":
        try:
            return _via_powershell(titulo)
        except FileNotFoundError:
            pass                      # sem PowerShell: tenta o tkinter
    return _via_tkinter(titulo)

"""
conversao_pdf.py — converte .docx em PDF com o LibreOffice (modo sem janela)
============================================================================
Usado pelo parecer_fund para entregar o parecer pronto para imprimir em PDF. Precisa do LibreOffice instalado
(gratuito, libreoffice.org). Para um instalador em outro lugar, defina AUTO_SERE_SOFFICE com o caminho do soffice.

Converte vários arquivos numa só chamada (abrir o LibreOffice leva alguns segundos; por arquivo ficaria lento).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Optional

VARIAVEL = "AUTO_SERE_SOFFICE"
_CANDIDATOS_WINDOWS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
TEMPO_LIMITE_S = 180


class ConversaoPdfErro(RuntimeError):
    pass


def encontrar_soffice() -> Optional[str]:
    """Caminho do soffice, ou None se o LibreOffice não está instalado."""
    do_ambiente = os.environ.get(VARIAVEL, "").strip()
    if do_ambiente:
        return do_ambiente if Path(do_ambiente).is_file() else None
    for nome in ("soffice", "libreoffice"):
        achado = shutil.which(nome)
        if achado:
            return achado
    for candidato in _CANDIDATOS_WINDOWS:
        if Path(candidato).is_file():
            return candidato
    return None


def exigir_soffice() -> str:
    caminho = encontrar_soffice()
    if not caminho:
        raise ConversaoPdfErro(
            "Para gerar o parecer em PDF é preciso ter o LibreOffice instalado (gratuito, libreoffice.org). "
            f"Instale-o, ou defina {VARIAVEL} com o caminho do soffice, ou escolha o formato Word (.docx).")
    return caminho


def docx_para_pdf(arquivos: Iterable[Path], pasta_saida: Path, tempo_limite: int = TEMPO_LIMITE_S) -> dict[Path, Optional[Path]]:
    """
    Converte os .docx e grava os PDFs em `pasta_saida` (mesmo nome, extensão .pdf). Devolve {docx: pdf ou None se
    aquele arquivo não saiu}. Levanta ConversaoPdfErro se o LibreOffice nem chegou a rodar.
    """
    arquivos = [Path(a) for a in arquivos]
    if not arquivos:
        return {}
    soffice = exigir_soffice()
    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autosere_lo_") as perfil:          # perfil próprio: não briga com um LibreOffice aberto
        comando = [soffice, f"-env:UserInstallation={Path(perfil).resolve().as_uri()}", "--headless", "--norestore",
                   "--convert-to", "pdf", "--outdir", str(pasta_saida), *map(str, arquivos)]
        try:
            # CREATE_NO_WINDOW (só existe no Windows): sem isso abre uma janela de cmd a cada conversão
            subprocess.run(comando, capture_output=True, timeout=tempo_limite, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise ConversaoPdfErro(f"O LibreOffice demorou mais de {tempo_limite} s para converter.") from exc
        except OSError as exc:
            raise ConversaoPdfErro(f"Não foi possível abrir o LibreOffice: {exc}") from exc
    saida: dict[Path, Optional[Path]] = {}
    for a in arquivos:
        pdf = pasta_saida / (a.stem + ".pdf")
        saida[a] = pdf if pdf.is_file() and pdf.stat().st_size > 0 else None
    return saida

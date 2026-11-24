"""
segredo.py — a "pimenta" das senhas e a proteção do arquivo
============================================================
A pimenta é um segredo aleatório de 32 bytes, guardado em credenciais/seguranca/pimenta.bin e misturado a TODA senha antes
do Argon2 (HMAC-SHA256). Quem copiar só o usuarios.json (por exemplo num zip enviado a alguém) não consegue tentar
adivinhar senhas offline, porque falta a pimenta.

No Windows o arquivo da pimenta é cifrado pela própria conta do Windows (DPAPI, CryptProtectData): ele só abre no mesmo
computador, para o mesmo usuário do Windows. Fora do Windows (testes, Linux) fica em texto, com permissão 600.

Se a pimenta ficar ilegível (perfil do Windows refeito, arquivo copiado para outro PC), NINGUÉM consegue entrar com a senha
antiga: a recuperação é `python -m src.seguranca redefinir-senha` (exige estar no computador) — ver documentacao/Seguranca.md.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import subprocess
import sys
import threading

from src.comum import paths

log = logging.getLogger(__name__)

_MAGICO_DPAPI = b"AUTOSERE-DPAPI-1\n"
_MAGICO_CRU = b"AUTOSERE-RAW-1\n"
_ENTROPIA = b"AUTO_SERE|pimenta|v1"
_LOCK = threading.Lock()
_cache: dict[str, bytes] = {}


class ChaveIndisponivel(Exception):
    """A pimenta existe mas não pode ser lida (outro usuário/PC do Windows, arquivo corrompido)."""


def pasta_seguranca():
    return paths.CREDENCIAIS_DIR / "seguranca"


def _arquivo_pimenta():
    return pasta_seguranca() / "pimenta.bin"


# ───────────────────────────── DPAPI (só Windows) ─────────────────────────────

def _dpapi(dados: bytes, proteger: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return _Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    entrada, _k1 = _blob(dados)
    entropia, _k2 = _blob(_ENTROPIA)
    saida = _Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    funcao = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if proteger:
        ok = funcao(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
    else:
        ok = funcao(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
    if not ok:
        raise OSError(f"DPAPI falhou (erro {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def _proteger(dados: bytes) -> bytes:
    if os.name == "nt":
        try:
            return _MAGICO_DPAPI + base64.b64encode(_dpapi(dados, True))
        except Exception as exc:                                   # noqa: BLE001 — cai para o modo "cru" e avisa
            log.warning("DPAPI indisponível ao gravar a pimenta (%s); guardada sem a proteção do Windows.", exc)
    return _MAGICO_CRU + base64.b64encode(dados)


def _desproteger(conteudo: bytes) -> bytes:
    if conteudo.startswith(_MAGICO_DPAPI):
        if os.name != "nt":
            raise ChaveIndisponivel("a pimenta foi protegida pelo Windows e este computador não é Windows")
        try:
            return _dpapi(base64.b64decode(conteudo[len(_MAGICO_DPAPI):]), False)
        except Exception as exc:                                   # noqa: BLE001
            raise ChaveIndisponivel("a pimenta só abre no mesmo computador e usuário do Windows em que foi criada") from exc
    if conteudo.startswith(_MAGICO_CRU):
        try:
            return base64.b64decode(conteudo[len(_MAGICO_CRU):])
        except ValueError as exc:
            raise ChaveIndisponivel("arquivo da pimenta corrompido") from exc
    raise ChaveIndisponivel("arquivo da pimenta em formato desconhecido")


# ───────────────────────────── pimenta ─────────────────────────────

def _gravar_privado(caminho, conteudo: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass


def pimenta_existe() -> bool:
    return _arquivo_pimenta().is_file()


def obter_pimenta(criar: bool = True) -> bytes:
    """Devolve a pimenta (cria na primeira vez se `criar`). Levanta ChaveIndisponivel se existe e não abre."""
    chave = str(_arquivo_pimenta())
    with _LOCK:
        if chave in _cache:
            return _cache[chave]
        arq = _arquivo_pimenta()
        if arq.is_file():
            valor = _desproteger(arq.read_bytes())
            if len(valor) != 32:
                raise ChaveIndisponivel("a pimenta tem tamanho inesperado")
        elif criar:
            valor = secrets.token_bytes(32)
            _gravar_privado(arq, _proteger(valor))
            proteger_pasta(pasta_seguranca().parent)
        else:
            raise ChaveIndisponivel("a pimenta ainda não existe")
        _cache[chave] = valor
        return valor


def esquecer_cache() -> None:
    with _LOCK:
        _cache.clear()


def regenerar_pimenta() -> None:
    """Só para a recuperação (CLI): cria uma pimenta nova. Todas as senhas antigas deixam de valer."""
    with _LOCK:
        _cache.clear()
        _gravar_privado(_arquivo_pimenta(), _proteger(secrets.token_bytes(32)))


# ───────────────────────────── pasta credenciais/ ─────────────────────────────

def proteger_pasta(pasta) -> bool:
    """
    Restringe a pasta ao usuário atual (+ SYSTEM e Administradores) no Windows, tirando o grupo "Usuários".
    Em outros sistemas aplica chmod 700. Melhor esforço: devolve False se não conseguiu, sem levantar erro.
    """
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(pasta, 0o700)
            return True
        usuario = os.environ.get("USERNAME") or ""
        dominio = os.environ.get("USERDOMAIN") or ""
        alvo = f"{dominio}\\{usuario}" if dominio and usuario else usuario
        if not alvo:
            return False
        comando = ["icacls", str(pasta), "/inheritance:r",
                   "/grant:r", f"{alvo}:(OI)(CI)F", "/grant:r", "SYSTEM:(OI)(CI)F", "/grant:r", "*S-1-5-32-544:(OI)(CI)F"]
        r = subprocess.run(comando, capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception as exc:                                       # noqa: BLE001
        log.warning("Não consegui restringir a pasta %s: %s", pasta, exc)
        return False

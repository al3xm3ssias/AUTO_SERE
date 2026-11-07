"""
qr_seguro.py — conteúdo criptografado do QR dos pareceres
==========================================================
O QR do parecer leva  ano letivo, nº da chamada, nome, turma e CGM. Lido pela câmera do celular, ele mostra só um
texto embaralhado:

    AUTOSERE|PF2|<texto base64 da mensagem criptografada>

Criptografia: AES-256-GCM (biblioteca `cryptography`). O GCM também garante que o QR não foi alterado: se um único
caractere mudar, a leitura falha. A chave fica em  credenciais/chave_qr.key  (ou na variável de ambiente
AUTO_SERE_QR_CHAVE), é criada sozinha na primeira geração e NUNCA é versionada (o .gitignore bloqueia *.key).

⚠️  Sem a chave, os QR já impressos não podem mais ser lidos. Guarde uma cópia de credenciais/chave_qr.key.

Formato antigo (AUTOSERE|PF|<ano>|<CGM>, em texto aberto) continua sendo lido por parecer_fund.ler_payload_qr.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path
from typing import Optional

from src.comum import paths

PREFIXO = "AUTOSERE"
TIPO = "PF2"
VARIAVEL_CHAVE = "AUTO_SERE_QR_CHAVE"
NOME_ARQUIVO_CHAVE = "chave_qr.key"
_AAD = f"{PREFIXO}|{TIPO}".encode()
_TAM_NONCE = 12
_RE_TEXTO = re.compile(rf"{PREFIXO}\|{TIPO}\|([A-Za-z0-9_\-]+)")


class QrIlegivel(ValueError):
    """O QR é de um parecer (formato novo), mas não foi possível abri-lo. A mensagem já diz o motivo."""


def arquivo_da_chave() -> Path:
    return paths.CREDENCIAIS_DIR / NOME_ARQUIVO_CHAVE


def _decodificar_chave(texto: str) -> bytes:
    try:
        chave = base64.urlsafe_b64decode(texto.strip() + "=" * (-len(texto.strip()) % 4))
    except (binascii.Error, ValueError) as exc:
        raise QrIlegivel("A chave do QR está num formato inválido.") from exc
    if len(chave) != 32:
        raise QrIlegivel("A chave do QR precisa ter 32 bytes (base64).")
    return chave


def _chave(criar: bool) -> bytes:
    """Chave de 32 bytes: variável de ambiente, senão o arquivo. `criar`: gera o arquivo se ainda não existe."""
    do_ambiente = os.environ.get(VARIAVEL_CHAVE, "").strip()
    if do_ambiente:
        return _decodificar_chave(do_ambiente)
    caminho = arquivo_da_chave()
    if caminho.is_file():
        return _decodificar_chave(caminho.read_text(encoding="utf-8"))
    if not criar:
        raise QrIlegivel(
            f"Este parecer tem QR criptografado, mas a chave não foi encontrada ({caminho}). Copie para lá o arquivo "
            f"{NOME_ARQUIVO_CHAVE} do computador que gerou os pareceres (ou defina {VARIAVEL_CHAVE}).")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    nova = base64.urlsafe_b64encode(os.urandom(32)).decode()
    try:
        with open(caminho, "x", encoding="utf-8") as f:           # "x": nunca sobrescreve uma chave que já existe
            f.write(nova + "\n")
    except FileExistsError:
        return _decodificar_chave(caminho.read_text(encoding="utf-8"))
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass
    return _decodificar_chave(nova)


def _limpo(valor) -> str:
    return "" if valor is None else str(valor).strip()


def montar(ano, chamada, nome, turma, cgm) -> str:
    """Texto do QR (criptografado) com ano letivo, nº da chamada, nome, turma e CGM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    cgm = _limpo(cgm)
    ano = _limpo(ano)
    if not cgm or not re.fullmatch(r"\w+", cgm):
        raise ValueError(f"CGM inválido para o QR code: '{cgm}'")
    if not re.fullmatch(r"\d{4}", ano):
        raise ValueError(f"Ano letivo inválido para o QR code: '{ano}'")
    corpo = json.dumps({"a": ano, "n": _limpo(chamada), "m": _limpo(nome), "t": _limpo(turma), "c": cgm},
                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(_TAM_NONCE)
    cifrado = AESGCM(_chave(criar=True)).encrypt(nonce, corpo, _AAD)
    token = base64.urlsafe_b64encode(nonce + cifrado).decode().rstrip("=")
    return f"{PREFIXO}|{TIPO}|{token}"


def eh_formato_novo(texto: str) -> bool:
    return str(texto or "").strip().startswith(f"{PREFIXO}|{TIPO}|")


def ler(texto: str) -> Optional[dict]:
    """
    {"ano","chamada","nome","turma","cgm"}, ou None se o texto não é do formato novo. Se é do formato novo mas não abre
    (chave ausente ou errada, QR alterado/cortado), levanta QrIlegivel com o motivo.
    """
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    texto = str(texto or "").strip()
    if not eh_formato_novo(texto):
        return None
    m = _RE_TEXTO.fullmatch(texto)
    if not m:
        raise QrIlegivel("O QR do parecer está incompleto ou foi lido com erro. Escaneie de novo.")
    token = m.group(1)
    try:
        bruto = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError) as exc:
        raise QrIlegivel("O QR do parecer está incompleto ou foi lido com erro. Escaneie de novo.") from exc
    if len(bruto) <= _TAM_NONCE + 16:
        raise QrIlegivel("O QR do parecer está incompleto ou foi lido com erro. Escaneie de novo.")
    aes = AESGCM(_chave(criar=False))                     # fora do try: o motivo exato (chave ausente) não pode ser trocado por outro
    try:
        corpo = aes.decrypt(bruto[:_TAM_NONCE], bruto[_TAM_NONCE:], _AAD)
        dados = json.loads(corpo.decode("utf-8"))
        ano, cgm = _limpo(dados["a"]), _limpo(dados["c"])
    except InvalidTag as exc:
        raise QrIlegivel("Não foi possível abrir o QR: a chave é outra ou o QR foi alterado.") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise QrIlegivel("O conteúdo do QR não é de um parecer válido.") from exc
    if not re.fullmatch(r"\d{4}", ano) or not re.fullmatch(r"\w+", cgm):
        raise QrIlegivel("O conteúdo do QR não é de um parecer válido.")
    return {"ano": ano, "chamada": _limpo(dados.get("n")), "nome": _limpo(dados.get("m")),
            "turma": _limpo(dados.get("t")), "cgm": cgm}

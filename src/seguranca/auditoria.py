"""
auditoria.py — registro de eventos de segurança (logs/auditoria.log)
=====================================================================
Uma linha JSON por evento: quando, o quê, quem, de onde. Cada linha leva o hash da linha anterior, formando uma corrente:
apagar ou alterar uma linha do meio quebra a corrente e `verificar_corrente()` aponta onde. (Quem apaga o arquivo INTEIRO ou
corta o final não é detectado por isto: para isso é preciso guardar uma cópia fora do computador.)

NUNCA entra aqui: senha (nem a errada), hash, token de sessão, token CSRF.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone

from src.comum import paths

log = logging.getLogger(__name__)
_LOCK = threading.Lock()
_ULTIMO: dict[str, str] = {}          # caminho do arquivo -> hash da última linha (cache; relido do disco se faltar)

EVENTOS = {
    "admin_instalado": "Administrador criado na instalação",
    "login_ok": "Entrada no sistema", "login_falha": "Tentativa de entrada recusada", "login_bloqueio": "Acesso bloqueado por excesso de tentativas",
    "logout": "Saída do sistema", "sessao_expirada": "Sessão encerrada por tempo",
    "senha_alterada": "Senha alterada pelo próprio usuário", "senha_redefinida": "Senha redefinida por um administrador",
    "senha_redefinida_cli": "Senha redefinida pelo computador (recuperação)",
    "usuario_criado": "Usuário criado", "usuario_alterado": "Usuário alterado", "usuario_removido": "Usuário removido",
    "usuario_desbloqueado": "Bloqueio de usuário removido",
    "acesso_negado": "Acesso negado por falta de permissão", "csrf_bloqueado": "Requisição recusada (CSRF)",
    "origem_bloqueada": "Requisição recusada (origem ou endereço não permitido)", "limite_tentativas": "Muitas tentativas do mesmo endereço",
    "chave_regenerada": "Chave de proteção das senhas recriada",
}


def _arquivo():
    return paths.LOGS_DIR / "auditoria.log"


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _hash_da_linha(anterior: str, corpo: dict) -> str:
    canonico = json.dumps(corpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((anterior + canonico).encode("utf-8")).hexdigest()


def _ultimo_hash(arq) -> str:
    chave = str(arq)
    if chave in _ULTIMO:
        return _ULTIMO[chave]
    ultimo = "0" * 64
    try:
        with open(arq, "rb") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    try:
                        ultimo = json.loads(linha).get("hash", ultimo)
                    except ValueError:
                        pass
    except OSError:
        pass
    _ULTIMO[chave] = ultimo
    return ultimo


def registrar(evento: str, usuario: str = "", ip: str = "", detalhe: str = "") -> None:
    """Acrescenta uma linha. Nunca levanta erro (auditar não pode derrubar o sistema)."""
    try:
        with _LOCK:
            arq = _arquivo()
            arq.parent.mkdir(parents=True, exist_ok=True)
            anterior = _ultimo_hash(arq)
            corpo = {"ts": _agora(), "evento": evento, "usuario": usuario or "", "ip": ip or "", "detalhe": (detalhe or "")[:300], "anterior": anterior}
            corpo["hash"] = _hash_da_linha(anterior, {k: v for k, v in corpo.items() if k != "hash"})
            with open(arq, "a", encoding="utf-8") as f:
                f.write(json.dumps(corpo, ensure_ascii=False, separators=(",", ":")) + "\n")
            _ULTIMO[str(arq)] = corpo["hash"]
    except Exception as exc:                                       # noqa: BLE001
        log.warning("Falha ao gravar a auditoria: %s", exc)


def ler(limite: int = 200) -> list[dict]:
    """Os últimos `limite` eventos, do mais novo para o mais antigo."""
    linhas: list[dict] = []
    try:
        with open(_arquivo(), "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    try:
                        linhas.append(json.loads(linha))
                    except ValueError:
                        linhas.append({"ts": "", "evento": "linha_ilegivel", "usuario": "", "ip": "", "detalhe": linha[:80]})
    except OSError:
        return []
    for l in linhas:
        l["descricao"] = EVENTOS.get(l.get("evento", ""), l.get("evento", ""))
    return list(reversed(linhas[-max(1, int(limite)):]))


def verificar_corrente() -> dict:
    """{"integra": bool, "linhas": n, "primeira_quebra": nº da linha ou None}."""
    anterior, n = "0" * 64, 0
    try:
        with open(_arquivo(), "r", encoding="utf-8") as f:
            for numero, linha in enumerate(f, 1):
                linha = linha.strip()
                if not linha:
                    continue
                n += 1
                try:
                    corpo = json.loads(linha)
                except ValueError:
                    return {"integra": False, "linhas": n, "primeira_quebra": numero}
                esperado = _hash_da_linha(anterior, {k: v for k, v in corpo.items() if k != "hash"})
                if corpo.get("anterior") != anterior or corpo.get("hash") != esperado:
                    return {"integra": False, "linhas": n, "primeira_quebra": numero}
                anterior = corpo["hash"]
    except OSError:
        return {"integra": True, "linhas": 0, "primeira_quebra": None}
    return {"integra": True, "linhas": n, "primeira_quebra": None}


def esquecer_cache() -> None:
    _ULTIMO.clear()

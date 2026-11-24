"""
sessoes.py — sessões no servidor
=================================
O navegador guarda só um código aleatório de 256 bits (cookie HttpOnly + SameSite=Strict). Tudo o mais (quem é o usuário,
o token CSRF, até quando vale) fica AQUI, na memória do servidor — e do código só se guarda o SHA-256, então nem um
despejo de memória do dicionário entrega cookies utilizáveis.

Uma sessão morre por: inatividade (sem nenhuma requisição por X minutos), duração máxima (mesmo em uso), saída do usuário,
troca de senha, desativação/remoção/mudança de perfil do usuário, ou reinício do servidor.
Os tempos podem ser ajustados em config/config_usuario.json:  {"seguranca": {"inatividade_min": 30, "duracao_max_horas": 12}}
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field

INATIVIDADE_PADRAO_S = 30 * 60
DURACAO_MAX_PADRAO_S = 12 * 3600


def _config_seguranca() -> dict:
    try:
        from src.comum import configuracao
        bloco = configuracao.carregar_configuracao().get("seguranca")
        return bloco if isinstance(bloco, dict) else {}
    except Exception:                                              # noqa: BLE001
        return {}


def _limitar(valor, padrao: float, minimo: float, maximo: float) -> float:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return padrao
    return min(max(v, minimo), maximo)


def inatividade_s() -> int:
    return int(_limitar(_config_seguranca().get("inatividade_min", INATIVIDADE_PADRAO_S / 60), INATIVIDADE_PADRAO_S / 60, 5, 480) * 60)


def duracao_max_s() -> int:
    return int(_limitar(_config_seguranca().get("duracao_max_horas", DURACAO_MAX_PADRAO_S / 3600), DURACAO_MAX_PADRAO_S / 3600, 1, 24) * 3600)


def hosts_extras() -> list[str]:
    extras = _config_seguranca().get("hosts_permitidos")
    return [str(h).strip().lower() for h in extras if str(h).strip()] if isinstance(extras, list) else []


@dataclass
class Sessao:
    usuario_id: str
    csrf: str
    criada: float
    ultimo_uso: float
    ip: str = ""
    perfil_ao_entrar: str = ""
    extras: dict = field(default_factory=dict)


class RepositorioSessoes:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._por_id: dict[str, Sessao] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _chave(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def criar(self, usuario_id: str, ip: str = "", perfil: str = "") -> tuple[str, Sessao]:
        """Sessão NOVA (sempre um código novo: impede 'fixação de sessão'). Devolve (token para o cookie, sessão)."""
        token = secrets.token_urlsafe(32)
        agora = self._relogio()
        s = Sessao(usuario_id=usuario_id, csrf=secrets.token_urlsafe(32), criada=agora, ultimo_uso=agora, ip=ip, perfil_ao_entrar=perfil)
        with self._lock:
            self._varrer(agora)
            self._por_id[self._chave(token)] = s
        return token, s

    def _vencida(self, s: Sessao, agora: float) -> bool:
        return agora - s.ultimo_uso > inatividade_s() or agora - s.criada > duracao_max_s()

    def _varrer(self, agora: float) -> None:
        for k in [k for k, s in self._por_id.items() if self._vencida(s, agora)]:
            del self._por_id[k]

    def obter(self, token: str | None, renovar: bool = True) -> Sessao | None:
        if not token:
            return None
        agora = self._relogio()
        chave = self._chave(token)
        with self._lock:
            s = self._por_id.get(chave)
            if s is None:
                return None
            if self._vencida(s, agora):
                del self._por_id[chave]
                return None
            if renovar:
                s.ultimo_uso = agora
            return s

    def revogar(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            return self._por_id.pop(self._chave(token), None) is not None

    def revogar_usuario(self, usuario_id: str, exceto_token: str | None = None) -> int:
        manter = self._chave(exceto_token) if exceto_token else None
        with self._lock:
            alvo = [k for k, s in self._por_id.items() if s.usuario_id == usuario_id and k != manter]
            for k in alvo:
                del self._por_id[k]
            return len(alvo)

    def revogar_todas(self) -> None:
        with self._lock:
            self._por_id.clear()

    def total(self) -> int:
        with self._lock:
            return len(self._por_id)

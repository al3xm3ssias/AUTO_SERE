"""
limite.py — limite de tentativas por endereço
==============================================
O bloqueio por usuário (usuarios.py) protege uma conta; este protege o sistema inteiro: o mesmo endereço não pode ficar
tentando usuários e senhas sem parar. Janela deslizante, só em memória (zera ao reiniciar o servidor).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class LimitadorTentativas:
    def __init__(self, maximo: int, janela_s: float):
        self.maximo = maximo
        self.janela_s = janela_s
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _podar(self, fila: deque, agora: float) -> None:
        while fila and agora - fila[0] > self.janela_s:
            fila.popleft()

    def liberado(self, chave: str) -> bool:
        with self._lock:
            fila = self._eventos[chave]
            self._podar(fila, time.monotonic())
            return len(fila) < self.maximo

    def registrar(self, chave: str) -> None:
        with self._lock:
            agora = time.monotonic()
            fila = self._eventos[chave]
            self._podar(fila, agora)
            fila.append(agora)

    def segundos_para_liberar(self, chave: str) -> int:
        with self._lock:
            fila = self._eventos[chave]
            agora = time.monotonic()
            self._podar(fila, agora)
            if len(fila) < self.maximo:
                return 0
            return max(1, int(self.janela_s - (agora - fila[0])) + 1)

    def zerar(self, chave: str | None = None) -> None:
        with self._lock:
            if chave is None:
                self._eventos.clear()
            else:
                self._eventos.pop(chave, None)

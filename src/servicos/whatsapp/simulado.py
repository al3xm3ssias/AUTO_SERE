"""Provedor simulado: NUNCA acessa a rede nem envia nada. É o padrão do sistema."""
from __future__ import annotations

from .base import EstadoConexao, ResultadoEnvio, normalizar_numero


class ProvedorSimulado:
    nome = "simulado"

    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str]] = []     # (número normalizado, texto) — só em memória

    def estado(self) -> EstadoConexao:
        return EstadoConexao(True, "Simulado: nenhuma mensagem real é enviada.", situacao="simulado")

    def enviar(self, numero: str, texto: str) -> ResultadoEnvio:
        alvo = normalizar_numero(numero)
        if not str(texto or "").strip():
            return ResultadoEnvio(False, True, erro="Mensagem vazia.")
        self.enviadas.append((alvo, texto))
        return ResultadoEnvio(True, True, id_mensagem=f"simulado-{len(self.enviadas)}")

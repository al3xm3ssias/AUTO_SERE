"""
navegador.py — como as automações abrem o navegador (Playwright)
================================================================
TODA automação que abre navegador chama `await navegador.lancar(p, "<motor do script>", <headless do script>)`
em vez de `p.chromium.launch(...)`. Assim duas escolhas do usuário valem para todos os scripts, sem cada um
reimplementar:

  1. **Navegador padrão** (Configurações → "Navegador das automações"): Automático, Chrome ou Firefox.
     Automático = cada script abre o navegador para o qual foi feito (nada muda em relação ao que já existia).
  2. **Ver a janela** (tela de cada automação → Configurações do script): liga/desliga o modo headless só
     naquele script. Sem escolha, vale o headless que o próprio script já usava.

Prioridade do headless:  janela pedida na execução (`forcar_mostrar`)  >  escolha salva do script  >  padrão do script.
Motor:  `travar_motor=True` (script que usa recurso exclusivo do Chromium)  >  navegador padrão global  >  o do script.

Qual script está rodando vem de uma ContextVar que o servidor preenche ao iniciar a execução
(`ExecucaoEmBackground.iniciar` leva o contexto para a thread). Fora do servidor (linha de comando, testes) não há
script atual: vale só o navegador padrão global e o padrão do script.

Aqui nada derruba a execução por causa da configuração: se ler o arquivo falhar, usa o padrão do script.
"""
from __future__ import annotations

import contextvars
from typing import Any, Optional

MOTORES = ("chromium", "firefox")
ROTULOS = {"chromium": "Chrome", "firefox": "Firefox"}

_script_atual: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("navegador_script_atual", default=None)


def definir_script(chave: Optional[str]) -> contextvars.Token:
    """Marca qual automação está sendo iniciada neste contexto. Guarde o token e devolva com `restaurar`."""
    return _script_atual.set(chave)


def restaurar(token: contextvars.Token) -> None:
    _script_atual.reset(token)


def script_atual() -> Optional[str]:
    return _script_atual.get()


def _motor_global() -> str:
    try:
        from src.comum import configuracao
        return configuracao.navegador_padrao()
    except Exception:                       # noqa: BLE001 — config ilegível não pode impedir a automação
        return ""


def _janela_do_script(chave: Optional[str]) -> Optional[bool]:
    if not chave:
        return None
    try:
        from src.comum import configuracao
        return configuracao.mostrar_janela_script(chave)
    except Exception:                       # noqa: BLE001
        return None


def resolver(motor_do_script: str, headless_do_script: bool = True, *, forcar_mostrar: bool = False,
             travar_motor: bool = False, chave: Optional[str] = None) -> tuple[str, bool]:
    """(motor, headless) que valem para esta abertura. Função pura em cima da configuração: fácil de testar."""
    chave = chave or script_atual()
    motor = motor_do_script if motor_do_script in MOTORES else "chromium"
    if not travar_motor and _motor_global():
        motor = _motor_global()
    if forcar_mostrar:
        return motor, False
    janela = _janela_do_script(chave)
    if janela is None:
        return motor, bool(headless_do_script)
    return motor, not janela


async def lancar(p: Any, motor_do_script: str = "chromium", headless_do_script: bool = True, *,
                 forcar_mostrar: bool = False, travar_motor: bool = False, **kwargs: Any) -> Any:
    """Abre o navegador conforme a configuração. `p` é o objeto do `async_playwright()`; `kwargs` vão ao launch()."""
    motor, headless = resolver(motor_do_script, headless_do_script, forcar_mostrar=forcar_mostrar,
                               travar_motor=travar_motor)
    if motor != motor_do_script:
        print(f"[navegador] Usando {ROTULOS[motor]} (configurado em Configurações → Navegador das automações).")
    if not headless and headless_do_script:
        print("[navegador] A janela do navegador ficará visível.")
    return await getattr(p, motor).launch(headless=headless, **kwargs)

"""
Teste SEGURO do WhatsApp
========================
  python -m src.servicos.whatsapp.teste

O que faz (e só isso):
  1. mostra qual provedor está configurado e o que falta, sem exibir chaves;
  2. consulta o ESTADO da conexão (somente leitura; no provedor simulado nem usa a rede);
  3. passa uma mensagem de exemplo pelo provedor SIMULADO, para provar que o fluxo funciona.
NENHUMA mensagem real é enviada.

Envio real de UMA mensagem de teste (precisa dos dois, de propósito):
  set WHATSAPP_ENVIO_REAL=1
  python -m src.servicos.whatsapp.teste --enviar-para 42999998888 --confirmo-envio-real
"""
from __future__ import annotations

import argparse
import os
import sys

from src.servicos.whatsapp import (ConfiguracaoIncompletaError, EnvioNaoAutorizadoError, ProvedorSimulado,
                                   criar_provedor, envio_real_autorizado, mascarar_numero, normalizar_numero)

TEXTO_TESTE = "Teste do sistema AUTO SERE — pode ignorar esta mensagem."


def main(argv: list[str] | None = None, provedor=None) -> int:
    ap = argparse.ArgumentParser(description="Teste seguro do WhatsApp (não envia mensagens reais por padrão)")
    ap.add_argument("--enviar-para", metavar="NUMERO", help="envia UMA mensagem de teste real (exige também --confirmo-envio-real e WHATSAPP_ENVIO_REAL=1)")
    ap.add_argument("--confirmo-envio-real", action="store_true", help="confirma que quero enviar uma mensagem de verdade")
    args = ap.parse_args(argv)

    nome = os.environ.get("WHATSAPP_PROVEDOR", "simulado") or "simulado"
    print(f"Provedor configurado: {nome}")
    print(f"Envio real autorizado (WHATSAPP_ENVIO_REAL): {'SIM' if envio_real_autorizado() else 'não'}")
    for var in ("WHATSAPP_API_URL", "WHATSAPP_API_KEY", "WHATSAPP_SESSAO"):
        if nome == "http":
            print(f"  {var}: {'definida' if os.environ.get(var, '').strip() else 'FALTANDO' if var != 'WHATSAPP_SESSAO' else 'não definida (usa \"autosere\")'}")

    try:
        prov = provedor or criar_provedor()
    except ConfiguracaoIncompletaError as exc:
        print(f"ERRO de configuração: {exc}", file=sys.stderr)
        return 1

    estado = prov.estado()
    print(f"Estado da conexão: {'CONECTADO' if estado.conectado else 'NÃO conectado'} — {estado.detalhe}")

    # Fluxo de exemplo: sempre no provedor simulado, nunca no real.
    simulador = ProvedorSimulado()
    r = simulador.enviar("42 99999-8888", TEXTO_TESTE)
    print(f"Fluxo de envio (simulado): {'ok' if r.ok else 'falhou'} — nada saiu do computador.")

    if not args.enviar_para:
        print("Nenhuma mensagem real foi enviada.")
        return 0 if (estado.conectado or prov.nome == "simulado") else 1

    # ── envio real: três travas ──
    if not args.confirmo_envio_real:
        print("RECUSADO: para enviar de verdade use também --confirmo-envio-real. Nenhuma mensagem foi enviada.", file=sys.stderr)
        return 2
    if prov.nome == "simulado":
        print("RECUSADO: o provedor é o simulado. Configure WHATSAPP_PROVEDOR=http para enviar de verdade. Nenhuma mensagem foi enviada.", file=sys.stderr)
        return 2
    if not envio_real_autorizado():
        print("RECUSADO: defina WHATSAPP_ENVIO_REAL=1 para autorizar o envio real. Nenhuma mensagem foi enviada.", file=sys.stderr)
        return 2
    try:
        alvo = normalizar_numero(args.enviar_para)
        resultado = prov.enviar(alvo, TEXTO_TESTE)
    except (ValueError, EnvioNaoAutorizadoError) as exc:
        print(f"RECUSADO: {exc}", file=sys.stderr)
        return 2
    if resultado.ok:
        print(f"Mensagem de teste enviada para {mascarar_numero(alvo)}.")
        return 0
    print(f"Falha ao enviar para {mascarar_numero(alvo)}: {resultado.erro}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

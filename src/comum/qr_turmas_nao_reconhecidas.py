"""
Textos de turma do QR ANTIGO dos pareceres que a leitura não reconheceu (pedido do usuário, 22/11/2026).

Quando o parecer traz uma turma como "INF 4 A" e nenhuma turma do turmas.json casa com ela, a rotina de pareceres
deixa o arquivo onde estava e guarda aqui o texto. O painel Configurações → "Turmas do QR antigo" lista esses textos,
e o usuário cria o par com um clique. Fica em dados/<ano>/qr_turmas_nao_reconhecidas.json:

    {"INF 4 A": {"texto": "INF 4 A", "quantidade": 3, "arquivos": ["scan 01.pdf", ...], "ultima_vez": "2026-11-22T10:00:00"}}

A chave é o texto em MAIÚSCULO, sem espaços nas pontas: é como a leitura procura o mapeamento. Gravar aqui NUNCA pode
derrubar a rotina de pareceres: qualquer falha é engolida.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.comum.arquivos_json import salvar_json_atomico

ARQUIVO = "qr_turmas_nao_reconhecidas.json"
MAX_TEXTO = 80          # igual ao limite do painel: um texto maior não poderia virar par
MAX_ENTRADAS = 100      # lixo de leitura ruim não cresce sem fim: ficam os mais recentes
MAX_ARQUIVOS = 20


def _chave(texto) -> str:
    return str(texto or "").strip().upper()


def _ler(dados_dir) -> dict:
    caminho = Path(dados_dir) / ARQUIVO
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in dados.items() if isinstance(v, dict)} if isinstance(dados, dict) else {}


def registrar(dados_dir, turma_qr, arquivo) -> bool:
    """Anota que `arquivo` trouxe a turma `turma_qr` e ela não foi reconhecida. True se gravou."""
    texto = str(turma_qr or "").strip()
    if not texto or len(texto) > MAX_TEXTO:
        return False
    try:
        dados = _ler(dados_dir)
        item = dados.get(_chave(texto)) or {"texto": texto, "quantidade": 0, "arquivos": []}
        nome = str(arquivo or "")
        if nome and nome not in item["arquivos"]:         # reprocessar o mesmo arquivo não infla a contagem
            item["arquivos"] = (list(item["arquivos"]) + [nome])[-MAX_ARQUIVOS:]
            item["quantidade"] = int(item.get("quantidade") or 0) + 1
        item["ultima_vez"] = datetime.now().isoformat()
        atual = _chave(texto)
        dados[atual] = item
        if len(dados) > MAX_ENTRADAS:                      # o texto que acabou de chegar nunca é o que sai
            recentes = sorted(dados.items(), key=lambda kv: (kv[0] == atual, str(kv[1].get("ultima_vez") or "")), reverse=True)
            dados = dict(recentes[:MAX_ENTRADAS])
        salvar_json_atomico(Path(dados_dir) / ARQUIVO, dados)
        return True
    except Exception:                                      # noqa: BLE001 — anotar é um extra: nunca derruba a rotina
        return False


def listar(dados_dir) -> list:
    """Os textos anotados, o mais recente primeiro: [{"texto", "quantidade", "arquivos", "ultima_vez"}]."""
    itens = []
    for chave, v in _ler(dados_dir).items():
        arquivos = [str(a) for a in v.get("arquivos") or [] if a]
        try:
            quantidade = int(v.get("quantidade") or len(arquivos))
        except (TypeError, ValueError):
            quantidade = len(arquivos)
        itens.append({"texto": str(v.get("texto") or chave), "quantidade": quantidade, "arquivos": arquivos,
                      "ultima_vez": str(v.get("ultima_vez") or "")})
    return sorted(itens, key=lambda i: i["ultima_vez"], reverse=True)


def remover(dados_dir, textos) -> int:
    """Tira da lista os textos dados (maiúsculas e minúsculas contam igual). Devolve quantos saíram."""
    alvo = {_chave(t) for t in textos or []}
    if not alvo:
        return 0
    dados = _ler(dados_dir)
    sobra = {k: v for k, v in dados.items() if k not in alvo}
    saiu = len(dados) - len(sobra)
    if saiu:
        salvar_json_atomico(Path(dados_dir) / ARQUIVO, sobra)
    return saiu

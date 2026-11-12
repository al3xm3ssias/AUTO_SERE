"""
historico_execucoes.py — histórico persistente das execuções de cada automação
=============================================================================
Cada vez que uma automação termina (concluída, com erro ou cancelada) o servidor grava aqui um
registro com: quando rodou, quanto durou, como terminou, **o que deu certo**, **o que deu errado**,
os avisos, as opções usadas e o fim do log. A tela da automação (Automações → <script>) lê isto
para mostrar o histórico logo abaixo das configurações, sem precisar de outra aba.

Onde fica:   dados/<ano>/historico_automacoes/<chave>.jsonl   (uma linha JSON por execução, mais nova no fim)
Limite:      as últimas MAX_EXECUCOES de cada automação (as mais antigas saem sozinhas).

O que é "deu certo" / "deu errado": os scripts do projeto já marcam o log com ✅ ✔ [OK] (sucesso),
❌ [ERRO] (falha) e ⚠ (aviso); `classificar_logs` só separa as linhas por esses marcadores. Quando o
script termina com exceção, a mensagem dela entra em "deu errado" também.

Aqui não há Flask nem rede: recebe a pasta de dados por parâmetro (assim os testes usam uma pasta temporária).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

NOME_PASTA = "historico_automacoes"
MAX_EXECUCOES = 100          # por automação
MAX_ITENS = 300              # linhas guardadas em cada lista (certo / errado / aviso)
MAX_LINHAS_LOG = 400         # fim do log guardado em cada execução
MAX_TEXTO = 400              # tamanho máximo de cada linha guardada

MARCAS_OK = ("✅", "✔", "[OK]")
MARCAS_ERRO = ("❌", "✖", "[ERRO]")
MARCAS_AVISO = ("⚠",)

# Opções que nunca vão para o histórico (a execução não deve deixar segredos gravados em disco).
_RE_SEGREDO = re.compile(r"senha|password|segredo|token|chave_api|secret", re.IGNORECASE)

# Resultado final, para a etiqueta da tela.
RESULTADO_OK = "ok"                  # terminou e nada deu errado
RESULTADO_PARCIAL = "parcial"        # terminou, mas alguma coisa deu errado no caminho
RESULTADO_FALHOU = "falhou"          # parou com erro
RESULTADO_CANCELADO = "cancelado"


def _arquivo(pasta: Path, chave: str) -> Path:
    seguro = re.sub(r"[^A-Za-z0-9_\-]", "_", str(chave))
    return Path(pasta) / NOME_PASTA / f"{seguro}.jsonl"


def _limpar_texto(linha: Any) -> str:
    texto = " ".join(str(linha).split())
    return texto if len(texto) <= MAX_TEXTO else texto[: MAX_TEXTO - 1] + "…"


def classificar_logs(logs: Iterable[str]) -> dict[str, list[str]]:
    """Separa as linhas do log em deu_certo / deu_errado / avisos (pelos marcadores dos scripts)."""
    certo: list[str] = []
    errado: list[str] = []
    avisos: list[str] = []
    totais = {"deu_certo": 0, "deu_errado": 0, "avisos": 0}
    for linha in logs:
        texto = str(linha)
        if any(m in texto for m in MARCAS_ERRO):
            destino, chave = errado, "deu_errado"
        elif any(m in texto for m in MARCAS_OK):
            destino, chave = certo, "deu_certo"
        elif any(m in texto for m in MARCAS_AVISO):
            destino, chave = avisos, "avisos"
        else:
            continue
        totais[chave] += 1
        if len(destino) < MAX_ITENS:
            destino.append(_limpar_texto(texto))
    return {"deu_certo": certo, "deu_errado": errado, "avisos": avisos, "totais": totais}


def opcoes_sem_segredos(opcoes: Optional[dict]) -> dict:
    """Cópia das opções usadas na execução, sem campos sensíveis e só com valores simples."""
    limpo: dict[str, Any] = {}
    for k, v in (opcoes or {}).items():
        if _RE_SEGREDO.search(str(k)) or k == "automacao":
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            limpo[str(k)] = v if not isinstance(v, str) else _limpar_texto(v)
        elif isinstance(v, (list, tuple)) and all(isinstance(x, (str, int, float, bool)) for x in v):
            limpo[str(k)] = [x if not isinstance(x, str) else _limpar_texto(x) for x in v][:100]
    return limpo


def resultado_final(status: str, total_errado: int) -> str:
    if status == "cancelado":
        return RESULTADO_CANCELADO
    if status == "erro":
        return RESULTADO_FALHOU
    return RESULTADO_PARCIAL if total_errado else RESULTADO_OK


def montar_registro(chave: str, nome: str, *, status: str, logs: list[str], erro: Optional[str],
                    iniciado_t: float, terminou_t: float, opcoes: Optional[dict] = None) -> dict:
    """Monta o registro de uma execução terminada (ainda não grava)."""
    itens = classificar_logs(logs)
    deu_errado = list(itens["deu_errado"])
    total_errado = itens["totais"]["deu_errado"]
    if erro:
        # A exceção que derrubou o script é, antes de tudo, "o que deu errado".
        deu_errado.insert(0, _limpar_texto(erro))
        total_errado += 1
    ini = datetime.fromtimestamp(iniciado_t)
    fim = datetime.fromtimestamp(terminou_t)
    return {
        "id": f"{ini.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}",
        "chave": chave,
        "nome": nome,
        "iniciado_em": ini.isoformat(timespec="seconds"),
        "terminou_em": fim.isoformat(timespec="seconds"),
        "duracao_s": max(0, round(terminou_t - iniciado_t)),
        "status": status,
        "resultado": resultado_final(status, total_errado),
        "erro": erro or None,
        "totais": {**itens["totais"], "deu_errado": total_errado},
        "deu_certo": itens["deu_certo"],
        "deu_errado": deu_errado[:MAX_ITENS],
        "avisos": itens["avisos"],
        "opcoes": opcoes_sem_segredos(opcoes),
        "log": [_limpar_texto(x) for x in logs[-MAX_LINHAS_LOG:]],
    }


def _ler_todos(arquivo: Path) -> list[dict]:
    if not arquivo.exists():
        return []
    registros = []
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    reg = json.loads(linha)
                except json.JSONDecodeError:
                    continue            # linha quebrada (queda de energia no meio da gravação): ignora só ela
                if isinstance(reg, dict):
                    registros.append(reg)
    except OSError:
        return []
    return registros


def _gravar_todos(arquivo: Path, registros: list[dict]) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(arquivo.parent), prefix=".tmp_", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for reg in registros:
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        os.replace(tmp, arquivo)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def salvar(pasta: Path, registro: dict) -> None:
    """Acrescenta a execução ao histórico da automação e apara o que passar do limite."""
    arquivo = _arquivo(pasta, registro["chave"])
    registros = _ler_todos(arquivo)
    registros.append(registro)
    _gravar_todos(arquivo, registros[-MAX_EXECUCOES:])


def _resumo(reg: dict) -> dict:
    """A execução sem as listas e o log (o que a lista do histórico precisa)."""
    return {k: reg.get(k) for k in ("id", "iniciado_em", "terminou_em", "duracao_s", "status", "resultado", "erro", "totais")}


def listar(pasta: Path, chave: str, limite: int = 30) -> list[dict]:
    """Execuções da automação, da mais nova para a mais antiga, só com o resumo."""
    registros = _ler_todos(_arquivo(pasta, chave))
    return [_resumo(r) for r in reversed(registros[-max(1, limite):])]


def obter(pasta: Path, chave: str, id_execucao: str) -> Optional[dict]:
    """Uma execução completa (com o que deu certo, o que deu errado, as opções e o log)."""
    for reg in reversed(_ler_todos(_arquivo(pasta, chave))):
        if reg.get("id") == id_execucao:
            return reg
    return None


def limpar(pasta: Path, chave: str) -> int:
    """Apaga o histórico da automação. Devolve quantas execuções foram apagadas."""
    arquivo = _arquivo(pasta, chave)
    total = len(_ler_todos(arquivo))
    if arquivo.exists():
        arquivo.unlink()
    return total


def estatisticas(pasta: Path, chave: str) -> dict:
    """Totais para o cabeçalho do histórico: quantas vezes rodou e como terminou cada uma."""
    registros = _ler_todos(_arquivo(pasta, chave))
    contagem = {RESULTADO_OK: 0, RESULTADO_PARCIAL: 0, RESULTADO_FALHOU: 0, RESULTADO_CANCELADO: 0}
    for r in registros:
        if r.get("resultado") in contagem:
            contagem[r["resultado"]] += 1
    ultima = _resumo(registros[-1]) if registros else None
    return {"total": len(registros), **contagem, "ultima": ultima}

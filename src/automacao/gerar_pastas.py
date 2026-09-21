"""
gerar_pastas.py — Gerador da estrutura de pastas de digitalização
=============================================================================
Portado de AUTO_SERE/gerar_pastas.py para src/automacao/gerar_pastas.py.

Cria, dentro da pasta de digitalização (a pasta que o usuário escolhe no
setup inicial — ver src.comum.configuracao.pasta_digitalizacao), uma
subpasta por turma e, dentro dela, uma subpasta por aluno ativo
("<N> - <NOME>"), a partir do turmas.json já coletado (ver
src.automacao.turmas). Também identifica e move para uma subpasta
TRANSFERIDOS as pastas de alunos que:
  1. não constam mais no turmas.json, ou
  2. constam no turmas.json com situação "Transferido".

Este script NÃO escolhe a pasta de digitalização em si — essa escolha é
feita pelo usuário no setup inicial (credenciais → carregar turmas →
ESCOLHER PASTA DE DIGITALIZAÇÃO → uso de rotina) e persistida via
src.comum.configuracao.definir_pasta_digitalizacao(). Este script só cria
a estrutura de subpastas DENTRO da pasta já escolhida — confirmado com o
usuário em 01/09/2026.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. ARQ_TURMAS: antes fixo em BASE/"PYTHON/SERE/2026/turmas.json". Agora
   resolvido via src.comum.paths.dados_ano_atual() / "turmas.json" — a
   mesma fonte usada por todos os outros scripts (sere_2026.py,
   analisa_arquivos_sere.py, etc.).

2. DIGITALIZACAO_DIR: antes fixo em BASE/"2026/DIGITALIZAÇÃO". Agora vem de
   src.comum.configuracao.pasta_digitalizacao() — a pasta escolhida pelo
   usuário. Como essa pasta pode não estar configurada ainda no momento em
   que o módulo é importado, DIGITALIZACAO_DIR não é mais uma constante de
   nível de módulo: é resolvida dentro de main() (e pode ser passada
   explicitamente via base_dir nas funções que já aceitavam esse parâmetro
   no original — criar_pastas, verificar_transferidos — preservado para
   uso em testes, exatamente como no script original).

3. Suíte de testes (_Testes, unittest.TestCase, rodar_testes(), a flag
   --teste): portada para tests/test_gerar_pastas.py, convertida para
   pytest puro (mesmos 18 casos, mesmas asserções) em vez de embutida
   neste arquivo — decisão do usuário, para integrar com o pytest que o
   bootstrap (criar_projeto.py) já configura para todo o projeto, em vez
   de manter um segundo mecanismo de teste paralelo (--teste + unittest)
   só para este script.

Toda a lógica de negócio (extração/ordenação de alunos, formato do nome de
pasta "N - NOME", separação ativos/transferidos, critério para mover para
TRANSFERIDOS) é idêntica ao original — nenhuma regra foi alterada.

Uso:
    from src.automacao.gerar_pastas import main
    main()
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from src.comum import paths as _paths
from src.comum.configuracao import pasta_digitalizacao

ARQ_TURMAS = _paths.dados_ano_atual() / "turmas.json"


# ─────────────────────────────────────────────
#  FUNÇÕES AUXILIARES
# ─────────────────────────────────────────────
def carregar_json(caminho: Path):
    """Carrega arquivo JSON com tratamento de erros."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Arquivo não encontrado: {caminho}")
        return None
    except json.JSONDecodeError:
        print(f"❌ Erro ao decodificar JSON: {caminho}")
        return None


def extrair_alunos(lista_alunos: list) -> list[tuple[int, str]]:
    """
    Retorna lista de tuplas (N, NOME) ordenada por N.
    Aceita tanto lista de dicts  [{"N": 1, "Nome": "FULANO", ...}]
    quanto lista de strings      ["FULANO", ...]  (N gerado por índice)
    Sem duplicatas de nome.
    """
    vistos = set()
    alunos = []

    for i, item in enumerate(lista_alunos, start=1):
        if isinstance(item, dict):
            n    = item.get("N", i)
            nome = (item.get("Nome") or item.get("nome") or "").strip().upper()
        elif isinstance(item, str):
            n    = i
            nome = item.strip().upper()
        else:
            continue

        if nome and nome not in vistos:
            vistos.add(nome)
            alunos.append((int(n), nome))

    return sorted(alunos, key=lambda x: x[0])


def nome_pasta(n: int, nome: str) -> str:
    """Formata o nome da pasta: '1 - FULANO DE TAL'"""
    return f"{n} - {nome}"


def separar_alunos(lista_alunos: list) -> tuple[set[str], set[str]]:
    """
    Retorna duas sets de nomes de pasta (em maiúsculo):
      - ativos:      alunos SEM situação 'Transferido'
      - transferidos: alunos COM situação 'Transferido'
    """
    ativos = set()
    transferidos = set()

    for i, item in enumerate(lista_alunos, start=1):
        if isinstance(item, dict):
            n        = item.get("N", i)
            nome     = (item.get("Nome") or item.get("nome") or "").strip().upper()
            situacao = (item.get("Situação") or item.get("Situacao") or "").strip().lower()
        elif isinstance(item, str):
            n        = i
            nome     = item.strip().upper()
            situacao = ""
        else:
            continue

        if not nome:
            continue

        pasta = nome_pasta(int(n), nome).upper()

        if "transferido" in situacao:
            transferidos.add(pasta)
        else:
            ativos.add(pasta)

    return ativos, transferidos


def nomes_pastas_validos(lista_alunos: list) -> set[str]:
    """Mantida para compatibilidade — retorna apenas alunos ativos."""
    ativos, _ = separar_alunos(lista_alunos)
    return ativos


def criar_pastas(turmas: dict, base_dir: Optional[Path] = None) -> int:
    """
    Cria estrutura <pasta_de_digitalização> / <TURMA> / <N - NOME> para
    cada turma. Se `base_dir` não for informado, usa
    src.comum.configuracao.pasta_digitalizacao() (a pasta configurada pelo
    usuário) — ver main() para a checagem de que ela existe antes de
    chamar esta função sem base_dir.
    """
    alvo = base_dir or pasta_digitalizacao()
    os.makedirs(alvo, exist_ok=True)

    print(f"\n📁 Criando estrutura de pastas em:")
    print(f"   {alvo}\n")

    total_alunos = 0

    for turma, lista_alunos in turmas.items():
        turma_path = alvo / turma.upper()
        os.makedirs(turma_path, exist_ok=True)

        alunos = extrair_alunos(lista_alunos)

        for n, nome in alunos:
            pasta = nome_pasta(n, nome)
            os.makedirs(turma_path / pasta, exist_ok=True)

        total_alunos += len(alunos)
        print(f"   📂 {turma:25} → {len(alunos):3} aluno(s)")

    print(f"\n   ✅ Total: {total_alunos} pasta(s) de aluno(s) criada(s)")
    return total_alunos


def verificar_transferidos(turmas: dict, base_dir: Optional[Path] = None) -> None:
    """
    Move para TRANSFERIDOS as pastas que:
      1. Não constam no JSON, OU
      2. Constam no JSON com situação 'Transferido'
    Se `base_dir` não for informado, usa
    src.comum.configuracao.pasta_digitalizacao().
    """
    alvo = base_dir or pasta_digitalizacao()

    print("\n🔍 Verificando pastas para mover para TRANSFERIDOS...")

    total_movidos = 0

    for turma, lista_alunos in turmas.items():
        turma_path = alvo / turma.upper()

        if not turma_path.exists():
            continue

        ativos, transferidos_json = separar_alunos(lista_alunos)
        transferidos_path = turma_path / "TRANSFERIDOS"

        for pasta in turma_path.iterdir():
            if not pasta.is_dir() or pasta.name.upper() == "TRANSFERIDOS":
                continue

            nome_upper = pasta.name.upper()

            if nome_upper not in ativos or nome_upper in transferidos_json:
                os.makedirs(transferidos_path, exist_ok=True)
                destino = transferidos_path / pasta.name

                if destino.exists():
                    print(f"   ⏭️  [{turma}] '{pasta.name}' já existe em TRANSFERIDOS, ignorando.")
                    continue

                shutil.move(str(pasta), str(destino))

                motivo = "transferido no JSON" if nome_upper in transferidos_json else "não listado no JSON"
                print(f"   📦 [{turma}] '{pasta.name}' → TRANSFERIDOS ({motivo})")
                total_movidos += 1

    if total_movidos == 0:
        print("   ✓ Nenhuma pasta para mover.")
    else:
        print(f"   ✓ {total_movidos} pasta(s) movida(s) para TRANSFERIDOS.")


def exibir_resumo(turmas: dict) -> None:
    """Exibe resumo das turmas lidas."""
    print("\n📊 RESUMO DAS TURMAS (turmas.json):")
    print("=" * 50)
    total = 0
    for turma, lista_alunos in turmas.items():
        alunos = extrair_alunos(lista_alunos)
        print(f"   {turma:25} → {len(alunos):3} aluno(s)")
        total += len(alunos)
    print("=" * 50)
    print(f"   {'TOTAL':25} → {total:3} aluno(s)")


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main() -> None:
    print("=" * 50)
    print("📂 GERADOR DE PASTAS - DIGITALIZAÇÃO")
    print("=" * 50)

    dir_digitalizacao = pasta_digitalizacao()
    if dir_digitalizacao is None:
        print("\n⚠️  A pasta de digitalização ainda não foi configurada.")
        print("    Rode o setup inicial (escolha da pasta de documentos digitalizados)")
        print("    antes de gerar a estrutura de pastas.")
        return

    turmas = carregar_json(ARQ_TURMAS)

    if not turmas:
        print(f"\n❌ Não foi possível carregar {ARQ_TURMAS}. Encerrando.")
        return

    print(f"   ✓ {len(turmas)} turma(s) encontrada(s)")

    exibir_resumo(turmas)
    criar_pastas(turmas, base_dir=dir_digitalizacao)
    verificar_transferidos(turmas, base_dir=dir_digitalizacao)

    print("\n✅ Concluído com sucesso!")
    print("=" * 50)


if __name__ == "__main__":
    main()

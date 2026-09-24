"""
sere_limpeza.py — Limpeza de documentos do SERE (remoção de slots)
=============================================================================
Portado de AUTO_SERE/sere_2026.py (linhas 873-1003 do original, funções
remover_slot e limpar_aluno) para src/comum/sere_limpeza.py.

CORREÇÃO EM RELAÇÃO AO ORIGINAL (aprovada pelo usuário em 28/08/2026):
Em remover_slot(), o original tinha:
    versoes_removidas = 0,
    ...
    versoes_removidas += 1,
(vírgula sobrando no final de cada linha) — isso faz `versoes_removidas` ser
uma TUPLA em vez de um inteiro (`(0,)`, depois `(0,) + (1,) = (0, 1)`, etc.),
então a mensagem final ("Removido (N versão(ões))") imprimia a tupla inteira
em vez da contagem numérica esperada. Corrigido para um inteiro comum. Esta
foi a única mudança de comportamento — toda a lógica de negócio (quantas
tentativas, quando desistir, como decidir sucesso/falha) é idêntica.

UNIFICAÇÃO (aprovada pelo usuário em 29/08/2026):
O sere_2026.py original tinha uma SEGUNDA função quase idêntica,
remover_slot_por_tipo() (usada só no modo --documento), com o MESMO bug de
tupla, que filtrava documentos por idtipo OU nome do slot (em vez de só pelo
nome, como remover_slot). Em vez de portar as duas funções duplicadas,
remover_slot() abaixo ganhou o parâmetro opcional `idtipo_alvo`: quando
informado, reproduz o comportamento de remover_slot_por_tipo (aceita bater
por idtipo OU por nome); quando omitido (padrão), comportamento idêntico ao
remover_slot original (só por nome). Nenhuma das duas regras de negócio foi
alterada — só deixaram de estar duplicadas em dois lugares.

Uso:
    from src.comum.sere_limpeza import remover_slot, limpar_aluno
"""

from __future__ import annotations

import asyncio
import logging

from .sere_utils import norm
from .sere_api import buscar_documentos_api, excluir_arquivo_api, navegar_pasta_virtual

log = logging.getLogger("sere.sere_limpeza")

# Máximo de tentativas de exclusão por slot (para versões empilhadas no SERE).
# Igual a MAX_TENTATIVAS_SLOT no sere_2026.py original (linha 163).
MAX_TENTATIVAS_SLOT_PADRAO = 15


async def remover_slot(
    page,
    cgm: str,
    doc: dict,
    max_tentativas: int = MAX_TENTATIVAS_SLOT_PADRAO,
    idtipo_alvo: str | None = None,
) -> tuple[bool, str]:
    """
    Remove TODAS as versões empilhadas de um slot.
    Itera até max_tentativas ou até o slot ficar vazio.

    `idtipo_alvo`: se informado, um documento é considerado "do mesmo slot"
    quando o idtipodocumento bate OU o nome do tipo bate (norm) — usado pelo
    modo --documento (via idtipo, que é mais confiável que o nome do slot).
    Se None (padrão), considera só o nome do tipo — comportamento original
    de remover_slot() no fluxo de limpeza geral.
    """
    slot = doc["tipodocumento"]
    slot_norm = norm(slot)
    versoes_removidas = 0  # corrigido: era "0," (tupla) no original

    def _e_do_slot(d: dict) -> bool:
        bate_nome = norm(d.get("tipodocumento", "")) == slot_norm
        bate_idtipo = idtipo_alvo is not None and str(d.get("idtipodocumento", "")) == str(idtipo_alvo)
        return (bate_nome or bate_idtipo) and d.get("nomearquivo", "").strip()

    for tentativa in range(1, max_tentativas + 1):
        docs_atuais = await buscar_documentos_api(page, cgm)
        pendentes = [d for d in docs_atuais if _e_do_slot(d)]

        if not pendentes:
            return True, f"Removido ({versoes_removidas} versão(ões))"

        versao_atual = pendentes[0]
        assinatura = versao_atual["assinaturaArquivo"]
        nome_arquivo = versao_atual.get("nomearquivo", "")

        print(f"       ↳ versão {versoes_removidas + 1}: {nome_arquivo} — excluindo…")

        try:
            ok = await excluir_arquivo_api(page, cgm, assinatura)
            if ok:
                versoes_removidas += 1  # corrigido: era "+= 1," (tupla) no original
            else:
                log.warning("  mudarStatus não-OK — tentando excluirDocumento JS")
                page.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
                await page.evaluate(f"excluirDocumento('{assinatura}')")
                versoes_removidas += 1
        except Exception as exc:
            log.warning(f"  Tentativa {tentativa} com erro: {exc}")

        await page.wait_for_timeout(1_200)

    docs_finais = await buscar_documentos_api(page, cgm)
    ainda_presente = any(_e_do_slot(d) for d in docs_finais)
    if not ainda_presente:
        return True, f"Removido ({versoes_removidas} versão(ões))"

    return False, (
        f"Falhou após {max_tentativas} tentativas "
        f"({versoes_removidas} versão(ões) removida(s), slot ainda tem arquivo)"
    )


async def limpar_aluno(
    page,
    aluno: dict,
    nome_turma: str,
    slots_protegidos_norm: set[str],
) -> tuple[dict, list[dict]]:
    """
    Limpa todos os documentos de um aluno (exceto slots protegidos).
    `slots_protegidos_norm` deve conter os nomes de slot já normalizados
    (ver src.comum.sere_utils.norm) que nunca devem ser removidos — no
    sere_2026.py original isso vinha da constante global SLOTS_PROTEGIDOS_NORM.
    """
    cgm = str(aluno["CGM"])
    nome = aluno.get("Nome", "SemNome")
    situacao = aluno.get("Situação", "")

    log.info(f"{'─'*50}")
    log.info(f"Limpando: '{nome}' | CGM={cgm} | Turma='{nome_turma}'")
    print(f"  🔎 {nome}  (CGM: {cgm}  |  Turma: {nome_turma})")

    resultado = {
        "CGM": cgm, "Nome": nome, "Turma": nome_turma,
        "Status": "Não processado", "Removidos": [],
        "Protegidos": [], "Falhas": [],
    }

    if "TRANSFER" in norm(situacao):
        resultado["Status"] = f"Ignorado (situação: {situacao})"
        print(f"     ⏭️  Ignorado: situação '{situacao}'")
        return resultado, []

    ok = await navegar_pasta_virtual(page, cgm)
    if not ok:
        resultado["Status"] = "Falha ao abrir pasta virtual"
        return resultado, []

    documentos = await buscar_documentos_api(page, cgm)
    if not documentos:
        resultado["Status"] = "API não retornou documentos"
        return resultado, []

    para_remover = [
        doc for doc in documentos
        if doc.get("nomearquivo", "").strip()
        and norm(doc.get("tipodocumento", "")) not in slots_protegidos_norm
    ]
    for doc in documentos:
        tipo_norm = norm(doc.get("tipodocumento", ""))
        if tipo_norm in slots_protegidos_norm and doc.get("nomearquivo", "").strip():
            resultado["Protegidos"].append(doc["tipodocumento"])

    print(f"     📊 Slots: {len(documentos)} total | "
          f"{sum(1 for d in documentos if d.get('nomearquivo','').strip())} com arquivo | "
          f"{len(para_remover)} a remover")

    if not para_remover:
        resultado["Status"] = "Nenhum arquivo para remover"
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        docs_restantes = await buscar_documentos_api(page, cgm)
        return resultado, docs_restantes

    todos_ok = True
    for doc in para_remover:
        slot = doc["tipodocumento"]
        print(f"     🗑️  {slot}: removendo…")
        sucesso, msg = await remover_slot(page, cgm, doc)

        if sucesso:
            print(f"     ✅ {slot}: {msg}")
            resultado["Removidos"].append(slot)
        else:
            print(f"     ❌ {slot}: {msg}")
            resultado["Falhas"].append({"Slot": slot, "Motivo": msg})
            todos_ok = False

    resultado["Status"] = "Todos removidos" if todos_ok else "Parcial — algumas remoções falharam"

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)

    docs_restantes = await buscar_documentos_api(page, cgm)
    return resultado, docs_restantes

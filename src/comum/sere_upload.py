"""
sere_upload.py — Upload de documentos ao SERE (POST direto sem DOM)
=============================================================================
Portado de AUTO_SERE/sere_2026.py (seção "FUNÇÕES AUXILIARES DE UPLOAD",
linhas 1357-1525 do original) para src/comum/sere_upload.py.

Nenhuma regra de negócio foi alterada — mesma lógica de decisão de pular
slot (validado / dentro do prazo / documento estável), mesmo comportamento
de replicar o uploadArquivo() do JavaScript da página via POST direto.

MUDANÇA ESTRUTURAL (sem mudança de comportamento):
deve_pular_slot() original lia SINONIMOS, DOCS_ESTAVEIS e PRAZO_REENVIO_MESES
como globais do módulo sere_2026.py. Agora recebe DOCS_ESTAVEIS e
PRAZO_REENVIO_MESES como parâmetros (com os mesmos valores padrão do
original) e importa SINONIMOS de src.comum.sere_normalizacao — a mesma fonte
de verdade já usada por analisa_arquivos_sere.py.

Uso:
    from src.comum.sere_upload import (
        deve_pular_slot, obter_slots_api, excluir_slot_e_obter_hash, injetar_e_enviar,
    )
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path

from .sere_normalizacao import SINONIMOS
from .sere_utils import norm, data_dentro_do_prazo, PRAZO_REENVIO_MESES_PADRAO
from .sere_api import URL_API_LISTAR, excluir_arquivo_api

log = logging.getLogger("sere.sere_upload")

# Tamanho máximo aceito pelo SERE em MB (acima disso gera HTTP 500).
# Igual a LIMITE_ARQUIVO_MB no sere_2026.py original (linha 179).
LIMITE_ARQUIVO_MB_PADRAO = 1.5

# Documentos "estáveis" — só sobem se não houver nenhum registro anterior.
# Igual a DOCS_ESTAVEIS no sere_2026.py original (linhas 242-249). Mantido
# aqui como padrão para quem não quer montar o conjunto manualmente, mas
# pode ser sobrescrito por quem chamar deve_pular_slot().
DOCS_ESTAVEIS_PADRAO = {
    "CPF Responsável",
    "CPF do Responsável",
    "RG do aluno",
    "RG",
    "Certidão de nascimento do aluno",
    "CPF do aluno",
}


def deve_pular_slot(
    indice_docs: dict[str, dict[str, dict]],
    cgm: str,
    slot: str,
    docs_estaveis: set[str] = DOCS_ESTAVEIS_PADRAO,
    prazo_reenvio_meses: int = PRAZO_REENVIO_MESES_PADRAO,
) -> tuple[bool, str]:
    """
    Decide se um slot deve ser pulado com base no documentos-alunos.json.
    Regras:
      1. validado=true → sempre pula
      2. data < N meses → pula
      3. Documento estável com qualquer registro → pula
      4. Caso contrário → não pula
    """
    aluno_docs = indice_docs.get(cgm, {})
    slot_norm = norm(slot)

    tipos_eq = {slot_norm}
    for sinonimo in SINONIMOS.get(slot, []):
        tipos_eq.add(norm(sinonimo))

    info = None
    for tipo in tipos_eq:
        if tipo in aluno_docs:
            info = aluno_docs[tipo]
            break

    if info is None:
        return False, ""

    data_str = info.get("data", "")

    if info.get("validado"):
        return True, f"já validado (data={data_str})"

    if data_str and data_dentro_do_prazo(data_str, prazo_reenvio_meses):
        return True, f"upload recente há menos de {prazo_reenvio_meses} meses (data={data_str})"

    eh_estavel = slot_norm in {norm(s) for s in docs_estaveis}
    if eh_estavel:
        return True, f"documento estável com registro anterior (data={data_str})"

    return False, ""


async def obter_slots_api(page, cgm: str) -> tuple[dict[str, str], dict[str, str]]:
    """
    Classifica os slots em vazios (hash de upload) e preenchidos (hash para exclusão).
    Retorna (hash_upload_por_idtipo, assinatura_por_idtipo).
    """
    hash_upload_por_idtipo: dict[str, str] = {}
    assinatura_por_idtipo: dict[str, str] = {}

    url = f"{URL_API_LISTAR}{cgm}"
    resultado = await page.evaluate(f"""
        async () => {{
            const resp = await fetch('{url}', {{credentials: 'include'}});
            if (!resp.ok) return null;
            return await resp.json();
        }}
    """)

    if not isinstance(resultado, list):
        log.error(f"obter_slots_api: resposta inválida para CGM={cgm}")
        return hash_upload_por_idtipo, assinatura_por_idtipo

    for entrada in resultado:
        idtipo = str(entrada.get("idtipodocumento", "")).strip()
        assin = str(entrada.get("assinaturaArquivo", "")).strip()
        nome_arq = str(entrada.get("nomearquivo", "")).strip()
        if not idtipo or not assin:
            continue
        if nome_arq:
            assinatura_por_idtipo[idtipo] = assin
        else:
            hash_upload_por_idtipo[idtipo] = assin

    log.info(
        f"obter_slots_api CGM={cgm}: "
        f"{len(hash_upload_por_idtipo)} vazios, {len(assinatura_por_idtipo)} preenchidos"
    )
    return hash_upload_por_idtipo, assinatura_por_idtipo


async def excluir_slot_e_obter_hash(page, cgm: str, slot: str, idtipo: str, assinatura: str) -> str | None:
    """Exclui o arquivo existente de um slot e retorna o hash fixo de upload."""
    print(f"     🗑️  '{slot}' já tem arquivo — excluindo para liberar o slot…")
    ok = await excluir_arquivo_api(page, cgm, assinatura)
    if not ok:
        log.warning(f"excluir_slot_e_obter_hash: mudarStatus não-OK assin={assinatura[:8]}…")

    await page.wait_for_timeout(1_500)

    hash_upload, _ = await obter_slots_api(page, cgm)
    novo_hash = hash_upload.get(idtipo)

    if novo_hash:
        log.info(f"excluir_slot_e_obter_hash: hash liberado para '{slot}': {novo_hash[:8]}…")
    else:
        log.warning(f"excluir_slot_e_obter_hash: slot '{slot}' não apareceu vazio após exclusão")

    return novo_hash


async def injetar_e_enviar(
    page,
    hash_doc: str,
    arquivo: Path,
    limite_arquivo_mb: float = LIMITE_ARQUIVO_MB_PADRAO,
) -> tuple[bool, str]:
    """
    Envia um arquivo para um slot do SERE via POST direto (sem DOM).
    Replica o comportamento do uploadArquivo() do JS da página.
    """
    tamanho_mb = arquivo.stat().st_size / (1024 * 1024)
    if tamanho_mb > limite_arquivo_mb:
        return False, f"Arquivo muito grande: {tamanho_mb:.2f} MB (limite {limite_arquivo_mb} MB)"

    print(f"     📎 Anexando: {arquivo.name}  ({tamanho_mb:.2f} MB)")

    mime = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(arquivo.read_bytes()).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    nome_arquivo = arquivo.name

    print("     📨 Enviando via POST direto…")

    resultado = await page.evaluate(f"""
        async () => {{
            try {{
                const resp = await fetch('/sere/gerenciarPastaVirtual.do?action=uploadArquivo', {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                    body: new URLSearchParams({{
                        nomeArquivo:      {json.dumps(nome_arquivo)},
                        conteudoArquivo:  {json.dumps(data_url)},
                        assinaturaArquivo: {json.dumps(hash_doc)},
                    }}).toString()
                }});
                const status = resp.status;
                let estado = null;
                try {{
                    const o = await resp.json();
                    estado = o.estado || null;
                }} catch(e) {{}}
                return {{status, estado}};
            }} catch(e) {{
                return {{status: 0, estado: null, erro: e.toString()}};
            }}
        }}
    """)

    if not resultado:
        return False, "Sem resposta do servidor"

    status = resultado.get("status", 0)
    estado = resultado.get("estado")
    erro = resultado.get("erro")

    print(f"     🌐 HTTP {status}" + (f" | estado={estado}" if estado else ""))

    if erro:
        return False, f"Erro de rede: {erro}"
    if status == 200 and estado == "OK":
        return True, f"Upload realizado com sucesso (HTTP {status})"
    if status == 200 and estado is None:
        return True, f"Upload realizado com sucesso (HTTP {status}, sem JSON)"
    if status == 500:
        return False, "Servidor retornou erro interno (HTTP 500)"
    if status == 413:
        return False, "Arquivo rejeitado: tamanho excede o limite (HTTP 413)"
    return False, f"Resposta inesperada (HTTP {status}, estado={estado})"
"""
direcionados_geo.py — leitura dos "Direcionados GEO" (sere_sisgea_<ano>.json)
=============================================================================
Arquivo gravado por ``src.automacao.fluxo_geo`` em dados/<ano em uso>/sere_sisgea_<próximo ano>.json.
Aqui só se LÊ e se organiza para as telas "Previsão" (turma, aluno, CGM, responsável) e "Pré matrícula"
(todos os dados, principalmente o telefone do responsável). Nada é gravado.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.comum.arquivos_json import carregar_json

PREFIXO_ARQUIVO = "sere_sisgea_"


def nome_arquivo(ano_letivo) -> str:
    return f"{PREFIXO_ARQUIVO}{int(ano_letivo)}.json"


def _txt(v: Any) -> str:
    return str(v or "").strip()


def _normalizar(a: dict) -> dict:
    turma = _txt(a.get("turma")) or _txt(a.get("turma_matricula"))
    return {
        "nome": _txt(a.get("nome")),
        "cgm": _txt(a.get("cgm")),
        "etapa": _txt(a.get("etapa")),
        "turma": turma,                                   # vazio = ainda sem turma no planejamento
        "responsavel": _txt(a.get("nome_responsavel")),
        "telefone": _txt(a.get("fone_responsavel")),
        "municipio_origem": _txt(a.get("municipio_origem")),
        "escola_origem": _txt(a.get("estabelecimento_origem")),
        "escola_destino": _txt(a.get("estabelecimento_destino")),
        "matricula": _txt(a.get("matricula_texto")),
        "matricula_confirmada": bool(a.get("matricula_confirmada")),
        "documentos_pendentes": [d for d in (a.get("documentos_pendentes") or []) if _txt(d)],
        "situacao_lista": _txt(a.get("situacao_lista")) or "presente",
        "primeira_vez_visto": _txt(a.get("primeira_vez_visto")),
        "ultima_vez_visto": _txt(a.get("ultima_vez_visto")),
        "ausente_desde": _txt(a.get("ausente_desde")),
    }


def carregar_direcionados(pasta, ano_letivo) -> dict:
    """
    ``{"ano", "arquivo", "existe", "coletado_em", "coleta_completa", "alunos": [...], "contagem": {...}}``.
    Arquivo inexistente -> existe False e lista vazia. Arquivo ilegível levanta ArquivoJsonCorrompidoError.
    """
    caminho = Path(pasta) / nome_arquivo(ano_letivo)
    existe = caminho.exists()
    bruto = carregar_json(caminho, dict, dict) if existe else {}
    alunos = [_normalizar(a) for a in (bruto.get("alunos") or []) if isinstance(a, dict)]
    alunos.sort(key=lambda a: (a["situacao_lista"] == "ausente", a["etapa"].lower(), a["nome"].lower()))
    presentes = [a for a in alunos if a["situacao_lista"] != "ausente"]
    return {
        "ano": int(ano_letivo), "arquivo": caminho.name, "existe": existe,
        "coletado_em": _txt(bruto.get("coletado_em")), "coleta_completa": bool(bruto.get("coleta_completa", True)),
        "alunos": alunos,
        "contagem": {
            "total": len(alunos), "presentes": len(presentes), "ausentes": len(alunos) - len(presentes),
            "com_telefone": sum(1 for a in presentes if a["telefone"]),
            "sem_telefone": sum(1 for a in presentes if not a["telefone"]),
            "matricula_confirmada": sum(1 for a in presentes if a["matricula_confirmada"]),
        },
    }

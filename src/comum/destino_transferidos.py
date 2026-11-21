"""
destino_transferidos.py — para onde o aluno transferido foi e quais documentos seguem no aviso à escola de destino
=================================================================================================================
Pedido do usuário (2026-11-19): usar o `vinculo_base_abc` do transferido (gravado pela Consulta na Base ABC) como ESCOLA DE
DESTINO e avisá-la por e-mail com a guia, o histórico e o parecer em anexo. Há casos em que a consulta não devolve nada
(a escola de destino não usa o SERE): aí o destino é preenchido à mão, ou o aluno é marcado como "encaminhado por e-mail
à parte" / "não avisar automaticamente" e o `avisos` o pula.

O QUE FICA EM transferidos.json (por CGM, no registro do aluno; vale para a saída ATUAL):
    vinculo_base_abc   o que a Consulta na Base ABC achou (escrito pela consulta, nunca por este módulo)
    destino_manual     {"escola", "status", "observacao", "atualizado_em"} — escrito AQUI, pela tela de Transferidos.
                       Fica separado do vínculo para uma nova consulta não apagá-lo; o manual tem prioridade.
    status             "automatico" (o `avisos` envia), "encaminhado" (você mandou por e-mail à parte) ou
                       "nao_avisar" (a escola não usa o SERE / não se avisa).
Na 2ª saída do aluno os três vão para o ciclo anterior (fila_transferidos.iniciar_novo_ciclo): a nova saída começa sem
destino e sem status, porque a escola pode ser outra.

Este módulo não conhece o `avisos`: quem casa o nome da escola com a lista de e-mails é o avisos.py.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.comum import paths as _paths
from src.comum import pastas_transferencias as _pastas
from src.comum.arquivos_json import carregar_json, salvar_json_atomico

NOME_ARQUIVO = "transferidos.json"
CHAVE_MANUAL = "destino_manual"

STATUS_AVISO = {
    "automatico": "Avisar automaticamente por e-mail",
    "encaminhado": "Encaminhado por e-mail à parte",
    "nao_avisar": "Não avisar automaticamente",
}
LIMITE_ESCOLA = 200
LIMITE_OBSERVACAO = 300

_CARACTERES_PROIBIDOS = '<>:"/\\|?*'       # os mesmos que pareceres_transferidos.nome_do_arquivo troca por "_"


class DestinoInvalidoError(ValueError):
    """Mensagem pronta para mostrar na tela."""


def _uma_linha(valor) -> str:
    return " ".join(str(valor or "").split())


# ───────────────────────────── destino: leitura ─────────────────────────────

def ler_manual(reg: dict) -> dict:
    """O `destino_manual` do registro, normalizado ({} se não há ou se está estragado)."""
    m = reg.get(CHAVE_MANUAL) if isinstance(reg, dict) else None
    if not isinstance(m, dict):
        return {}
    status = str(m.get("status") or "automatico")
    return {"escola": _uma_linha(m.get("escola")), "status": status if status in STATUS_AVISO else "automatico",
            "observacao": _uma_linha(m.get("observacao")), "atualizado_em": str(m.get("atualizado_em") or "")}


def estado_da_consulta(vinculo) -> str:
    """"ok" (CGM + escola), "verificar" (vínculo incompleto ou duvidoso) ou "sem_vinculo" (a consulta não gravou nada)."""
    if not isinstance(vinculo, dict) or not vinculo:
        return "sem_vinculo"
    if vinculo.get("status") == "ok" and _uma_linha(vinculo.get("escola")):
        return "ok"
    return "verificar"


def resolver_destino(reg: dict) -> dict:
    """
    Onde o aviso deve ir, com o que se sabe agora. Devolve {fonte, escola, status_aviso, consulta, observacao, motivo}:
      fonte        "manual" (você preencheu a escola), "base_abc" (vínculo ok) ou "nenhuma"
      escola       nome da escola de destino ("" se não há)
      status_aviso "automatico" | "encaminhado" | "nao_avisar"
      consulta     "ok" | "verificar" | "sem_vinculo" (estado do vínculo da Base ABC, para a tela mostrar)
    O vínculo que não está "ok" NUNCA vira destino sozinho: só o preenchimento manual o substitui.
    """
    manual = ler_manual(reg)
    vinculo = reg.get("vinculo_base_abc") if isinstance(reg, dict) else None
    consulta = estado_da_consulta(vinculo)
    if manual.get("escola"):
        escola, fonte = manual["escola"], "manual"
    elif consulta == "ok":
        escola, fonte = _uma_linha(vinculo.get("escola")), "base_abc"
    else:
        escola, fonte = "", "nenhuma"
    motivo = _uma_linha(vinculo.get("motivo")) if consulta == "verificar" else ""
    return {"fonte": fonte, "escola": escola, "status_aviso": manual.get("status", "automatico"), "consulta": consulta,
            "observacao": manual.get("observacao", ""), "motivo": motivo}


# ───────────────────────────── destino: gravação (tela de Transferidos) ─────────────────────────────

def _caminho(dados_dir: Optional[Path] = None) -> Path:
    return (Path(dados_dir) if dados_dir is not None else _paths.dados_ano_atual()) / NOME_ARQUIVO


def _validar(escola, status, observacao) -> tuple[str, str, str]:
    escola, observacao, status = _uma_linha(escola), _uma_linha(observacao), str(status or "automatico")
    if status not in STATUS_AVISO:
        raise DestinoInvalidoError("Situação do aviso inválida: use automatico, encaminhado ou nao_avisar.")
    if len(escola) > LIMITE_ESCOLA:
        raise DestinoInvalidoError(f"O nome da escola passa de {LIMITE_ESCOLA} caracteres.")
    if len(observacao) > LIMITE_OBSERVACAO:
        raise DestinoInvalidoError(f"A observação passa de {LIMITE_OBSERVACAO} caracteres.")
    return escola, status, observacao


def salvar_destino(cgm: str, escola, status, observacao="", dados_dir: Optional[Path] = None) -> dict:
    """
    Grava o `destino_manual` do aluno em transferidos.json (leitura + gravação atômica; só essa chave é tocada).
    Tudo em branco com status "automatico" equivale a LIMPAR (volta a valer só o vínculo da Base ABC).
    DestinoInvalidoError com mensagem pronta; ArquivoJsonCorrompidoError se o arquivo estiver ilegível (nunca sobrescrito).
    Devolve o registro resolvido ({resolver_destino}).
    """
    escola, status, observacao = _validar(escola, status, observacao)
    caminho = _caminho(dados_dir)
    if not caminho.exists():
        raise DestinoInvalidoError("transferidos.json ainda não existe.")
    dados = carregar_json(caminho, dict, dict)
    reg = dados.get(str(cgm))
    if not isinstance(reg, dict):
        raise DestinoInvalidoError("Aluno não encontrado em transferidos.json.")
    if not escola and not observacao and status == "automatico":
        reg.pop(CHAVE_MANUAL, None)
    else:
        reg[CHAVE_MANUAL] = {"escola": escola, "status": status, "observacao": observacao,
                             "atualizado_em": datetime.now().isoformat(timespec="seconds")}
    salvar_json_atomico(caminho, dados, indent=2)
    return resolver_destino(reg)


# ───────────────────────────── documentos que seguem no aviso ─────────────────────────────

def _arquivo_unico(pasta: Path, prefixo_numero: bool, nome: str) -> tuple[Optional[Path], str]:
    """(arquivo, problema). Guia/histórico: <pasta>/<nome>.pdf. Parecer: NN-<nome>.<ext> (ou NN-<nome>_<n>.<ext>)."""
    limpo = nome
    for c in _CARACTERES_PROIBIDOS:
        limpo = limpo.replace(c, "_")
    if not pasta.is_dir():
        return None, "não encontrado"
    if not prefixo_numero:
        alvo = pasta / f"{limpo}.pdf"
        return (alvo, "") if alvo.is_file() else (None, "não encontrado")
    padrao = re.compile(rf"^\d+-{re.escape(limpo)}(?:_\d+)?\.[A-Za-z0-9]+$")
    achados = sorted(p for p in pasta.iterdir() if p.is_file() and padrao.match(p.name))
    if not achados:
        return None, "não encontrado"
    if len(achados) > 1:
        return None, f"há {len(achados)} arquivos ({', '.join(p.name for p in achados)}); deixe só o desta saída"
    return achados[0], ""


def documentos_do_aluno(reg: dict, dados_dir: Optional[Path] = None) -> dict:
    """
    Os três documentos da saída ATUAL do aluno, nas pastas de TRANSFERENCIAS:
        GUIA DE TRANSFERENCIA/<turma>/<nome>.pdf · HISTORICO/<turma>/<nome>.pdf · PARECERES/<turma>/NN-<nome>.<ext>
    Devolve {"guia": Path|None, "historico": Path|None, "parecer": Path|None, "faltando": ["parecer: não encontrado", ...]}.
    Os PDFs de guia e histórico de saídas anteriores foram renomeados "(saída dd-mm-aaaa)" e por isso nunca entram aqui;
    o parecer da saída anterior não é renomeado, então: sem o parecer DESTA saída digitalizado, ele vai para `faltando`; e
    um parecer ambíguo (mais de um arquivo para o nome) não é escolhido, também vai para `faltando`. Para resolver, renomeie
    o antigo como "NN-NOME (saída dd-mm-aaaa).ext": esse nome não é considerado.
    """
    nome, turma = _uma_linha(reg.get("nome")), _uma_linha(reg.get("turma"))
    base = Path(dados_dir) if dados_dir is not None else _paths.dados_ano_atual()
    saida: dict = {"faltando": []}
    for chave, subpasta, numerado in (("guia", _pastas.GUIA, False), ("historico", _pastas.HISTORICO, False),
                                      ("parecer", _pastas.PARECERES, True)):
        arquivo, problema = _arquivo_unico(_pastas.subpasta(subpasta, base) / turma, numerado, nome) if nome and turma \
            else (None, "registro sem nome ou turma")
        saida[chave] = arquivo
        if problema:
            saida["faltando"].append(f"{chave}: {problema}")
    # 2ª saída em diante: o parecer da saída anterior NÃO é renomeado como a guia e o histórico e continua em PARECERES.
    # Sem o parecer desta saída já digitalizado, o arquivo que está lá é o da anterior: nunca anexar.
    if reg.get("ciclos_anteriores") and not (reg.get("parecer") or {}).get("digitalizado_em"):
        saida["parecer"] = None
        saida["faltando"] = [f for f in saida["faltando"] if not f.startswith("parecer:")] + [
            "parecer: o desta saída (2ª ou posterior) ainda não foi digitalizado"]
    return saida

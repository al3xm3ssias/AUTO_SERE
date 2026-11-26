"""
painel_avisos.py — avisos do PAINEL PRINCIPAL (home)
=====================================================
Guarda em dados/<ano>/painel_avisos.json o que a rotina diária encontrou e que precisa de uma pessoa. Não confundir
com src/automacao/avisos.py, que envia comunicados (e-mail) a escolas e responsáveis.

Dois tipos de aviso:

  transferencia      o SERE mostra o aluno como "Transferido" (a situação mudou).
                     Pede: 1) gerar os documentos do aluno; 2) enviá-los à escola de destino.
  saida_a_verificar  o aluno SUMIU das turmas sem constar como transferido. Não se presume transferência: o aviso só
                     pede para conferir a situação dele no SERE.

Nada de duplicado: cada aviso tem uma CHAVE (a mesma saída = a mesma chave, em qualquer número de execuções):
    • id_matricula da saída (ponte turmas_relacional.json), quando existe; senão  CGM|data da saída.
Quem sai, volta e sai de novo tem outra saída (outro id_matricula / outra data) e, portanto, um aviso novo.

Quando um aviso se resolve:
    • transferencia: sozinho, quando a guia e o histórico foram emitidos (transferidos.json) E os documentos já foram
      enviados à escola de destino (AVISOS/enviados.json) ou o destino foi marcado como "encaminhado à parte" / "não
      avisar". Ou à mão, pelo botão "Marcar como resolvido" da home.
    • saida_a_verificar: sozinho, se o aluno voltar a aparecer em turmas.json; ou à mão.
Aviso resolvido não volta (a chave continua registrada) e some da home.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

NOME_ARQUIVO = "painel_avisos.json"
TIPO_TRANSFERENCIA = "transferencia"
TIPO_SAIDA = "saida_a_verificar"

PASSOS = {
    TIPO_TRANSFERENCIA: (("documentos", "Gerar os documentos do aluno transferido (guia e histórico)"),
                         ("envio", "Enviar os documentos à escola de destino")),
    TIPO_SAIDA: (("conferir", "Conferir a situação do aluno no SERE"),),
}


# ───────────────────────────── arquivo ─────────────────────────────
def _pasta(dados_dir: Optional[Path] = None) -> Path:
    if dados_dir is not None:
        return Path(dados_dir)
    from src.comum import paths
    return paths.dados_ano_atual()


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ler_json(caminho: Path, padrao):
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return dados if isinstance(dados, type(padrao)) else padrao
    except (OSError, ValueError):
        return padrao


def _gravar(dados_dir: Optional[Path], avisos: list[dict]) -> None:
    caminho = _pasta(dados_dir) / NOME_ARQUIVO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"avisos": avisos}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def carregar(dados_dir: Optional[Path] = None) -> list[dict]:
    """Todos os avisos gravados (abertos e resolvidos), na ordem de criação."""
    dados = _ler_json(_pasta(dados_dir) / NOME_ARQUIVO, {})
    lista = dados.get("avisos") if isinstance(dados, dict) else None
    return [a for a in (lista or []) if isinstance(a, dict) and a.get("chave")]


# ───────────────────────────── criação (sem duplicar) ─────────────────────────────
def chave_da_saida(cgm: str, data_saida: str = "", id_matricula: str = "") -> str:
    """Identifica UMA saída do aluno. O id da matrícula resiste a uma data corrigida no SERE."""
    if str(id_matricula or "").strip():
        return f"id:{str(id_matricula).strip()}"
    return f"cgm:{str(cgm).strip()}|{str(data_saida or '').strip()}"


def _id_do_aviso(tipo: str, chave: str) -> str:
    return f"{tipo}-{hashlib.sha1(chave.encode('utf-8')).hexdigest()[:10]}"


def _novo(tipo: str, cgm: str, nome: str, turma: str, data_saida: str, id_matricula: str) -> dict:
    chave = chave_da_saida(cgm, data_saida, id_matricula)
    return {"id": _id_do_aviso(tipo, chave), "tipo": tipo, "chave": chave, "cgm": str(cgm).strip(),
            "nome": str(nome or "").strip(), "turma": str(turma or "").strip(), "data_saida": str(data_saida or "").strip(),
            "id_matricula": str(id_matricula or "").strip(), "criado_em": _agora(), "estado": "aberto",
            "resolvido_em": None, "resolvido_por": None}


def registrar(tipo: str, cgm: str, nome: str = "", turma: str = "", data_saida: str = "", id_matricula: str = "",
              dados_dir: Optional[Path] = None) -> bool:
    """Cria o aviso se ainda não existe um para esta saída (aberto OU já resolvido). True se criou."""
    if tipo not in PASSOS:
        raise ValueError(f"Tipo de aviso desconhecido: {tipo}")
    if not str(cgm or "").strip():
        return False
    avisos = carregar(dados_dir)
    aviso = _novo(tipo, cgm, nome, turma, data_saida, id_matricula)
    if any(a["id"] == aviso["id"] for a in avisos):
        return False
    # Mesma saída que ganhou id_matricula depois (a ponte só dá o ID na coleta seguinte): CGM + data iguais = o mesmo aviso.
    if aviso["data_saida"] and any(a["tipo"] == tipo and a["cgm"] == aviso["cgm"] and a.get("data_saida") == aviso["data_saida"]
                                   for a in avisos):
        return False
    avisos.append(aviso)
    _gravar(dados_dir, avisos)
    return True


def _registro_em_transferidos(cgm: str, dados_dir: Optional[Path]) -> dict:
    reg = _ler_json(_pasta(dados_dir) / "transferidos.json", {}).get(str(cgm).strip())
    return reg if isinstance(reg, dict) else {}


def _situacao_na_fila(cgm: str, dados_dir: Optional[Path]) -> str:
    fila = _ler_json(_pasta(dados_dir) / "fila_transferidos.json", {})
    return str(((fila.get("alunos") or {}).get(str(cgm).strip()) or {}).get("situacao_fila") or "")


def registrar_da_comparacao(eventos: list[dict], dados_dir: Optional[Path] = None) -> dict:
    """
    Cria os avisos a partir dos eventos da comparação de turmas (rotina_diaria.comparar_turmas → "eventos"):
    {cgm, nome, turma, motivo: "situacao_mudou"|"saiu_da_lista", data_transferencia}.
    Quem a fila de transferidos já deixou de fora (transferido ANTES da data de corte = já tratado à mão; retornou à
    escola) não gera aviso. Sem eventos, não cria nada. Devolve {"criados": n, "ja_existiam": n, "ignorados": n}.
    """
    r = {"criados": 0, "ja_existiam": 0, "ignorados": 0}
    for ev in eventos or []:
        cgm = str(ev.get("cgm") or "").strip()
        if not cgm:
            r["ignorados"] += 1
            continue
        transferencia = ev.get("motivo") == "situacao_mudou"
        reg = _registro_em_transferidos(cgm, dados_dir) if transferencia else {}
        if transferencia and _situacao_na_fila(cgm, dados_dir) in ("antes_do_corte", "retornou"):
            r["ignorados"] += 1
            continue
        criado = registrar(
            TIPO_TRANSFERENCIA if transferencia else TIPO_SAIDA, cgm,
            nome=reg.get("nome") or ev.get("nome") or "", turma=reg.get("turma") or ev.get("turma") or "",
            data_saida=reg.get("data_transferencia") or ev.get("data_transferencia") or "",
            id_matricula=reg.get("id_matricula") or "", dados_dir=dados_dir)
        r["criados" if criado else "ja_existiam"] += 1
    return r


# ───────────────────────────── andamento e resolução ─────────────────────────────
def _documentos_emitidos(aviso: dict, dados_dir: Optional[Path]) -> bool:
    reg = _registro_em_transferidos(aviso["cgm"], dados_dir)
    if not reg:
        return False
    mesma_saida = (aviso.get("id_matricula") and reg.get("id_matricula") == aviso["id_matricula"]) or \
                  (not aviso.get("id_matricula") and str(reg.get("data_transferencia") or "") == aviso.get("data_saida", ""))
    if not mesma_saida:                                          # o registro já é de outra saída (ou ainda não é desta)
        return False
    return bool((reg.get("guia") or {}).get("emitido_em") and (reg.get("historico") or {}).get("emitido_em"))


def _enviado_ao_destino(aviso: dict, dados_dir: Optional[Path]) -> bool:
    try:
        from src.automacao import avisos as av
        from src.comum import destino_transferidos as destino_tf
        enviados = av.avisos_ja_enviados_ao_destino()
        if aviso.get("id_matricula") and ("id", aviso["id_matricula"]) in enviados:
            return True
        if (aviso["cgm"], aviso.get("data_saida", "")) in enviados:
            return True
        reg = _registro_em_transferidos(aviso["cgm"], dados_dir)
        return bool(reg) and destino_tf.resolver_destino(reg).get("status_aviso") in ("encaminhado", "nao_avisar")
    except Exception:                                            # noqa: BLE001 — sem o registro de envios, não resolve sozinho
        return False


def _cgm_em_turmas(cgm: str, dados_dir: Optional[Path]) -> bool:
    turmas = _ler_json(_pasta(dados_dir) / "turmas.json", {})
    return any(str(a.get("CGM", "")).strip() == cgm for alunos in turmas.values() for a in (alunos or []))


def _passos_feitos(aviso: dict, dados_dir: Optional[Path]) -> dict[str, bool]:
    if aviso["tipo"] == TIPO_TRANSFERENCIA:
        docs = _documentos_emitidos(aviso, dados_dir)
        return {"documentos": docs, "envio": docs and _enviado_ao_destino(aviso, dados_dir)}
    return {"conferir": _cgm_em_turmas(aviso["cgm"], dados_dir)}


def reavaliar(dados_dir: Optional[Path] = None) -> int:
    """Resolve sozinho os avisos abertos cujos passos já foram feitos. Devolve quantos resolveu."""
    avisos = carregar(dados_dir)
    resolvidos = 0
    for a in avisos:
        if a.get("estado") != "aberto":
            continue
        if all(_passos_feitos(a, dados_dir).values()):
            a.update({"estado": "resolvido", "resolvido_em": _agora(), "resolvido_por": "automatico"})
            resolvidos += 1
    if resolvidos:
        _gravar(dados_dir, avisos)
    return resolvidos


def resolver(id_aviso: str, dados_dir: Optional[Path] = None) -> bool:
    """Marca como resolvido à mão. False se o aviso não existe; True também se já estava resolvido."""
    avisos = carregar(dados_dir)
    for a in avisos:
        if a["id"] == id_aviso:
            if a.get("estado") != "resolvido":
                a.update({"estado": "resolvido", "resolvido_em": _agora(), "resolvido_por": "manual"})
                _gravar(dados_dir, avisos)
            return True
    return False


def _apresentar(aviso: dict, feitos: dict[str, bool]) -> dict:
    nome = aviso.get("nome") or f"CGM {aviso['cgm']}"
    quando = f" em {aviso['data_saida']}" if aviso.get("data_saida") else ""
    turma = f" ({aviso['turma']})" if aviso.get("turma") else ""
    if aviso["tipo"] == TIPO_TRANSFERENCIA:
        titulo = f"Aluno transferido: {nome}{turma}{quando}"
        texto = "Gere os documentos do aluno transferido e envie-os à escola de destino."
    else:
        titulo = f"Aluno saiu da lista sem constar como transferido: {nome}{turma}"
        texto = "Confira a situação dele no SERE. Se foi transferido, o aviso de transferência aparece quando a situação mudar."
    return {"id": aviso["id"], "tipo": aviso["tipo"], "cgm": aviso["cgm"], "nome": nome, "titulo": titulo, "texto": texto,
            "criado_em": aviso.get("criado_em"),
            "passos": [{"chave": c, "texto": t, "feito": bool(feitos.get(c))} for c, t in PASSOS[aviso["tipo"]]]}


def listar_abertos(dados_dir: Optional[Path] = None) -> list[dict]:
    """Os avisos abertos para a home, já com o andamento de cada passo (reavalia e resolve os que se completaram)."""
    reavaliar(dados_dir)
    return [_apresentar(a, _passos_feitos(a, dados_dir)) for a in carregar(dados_dir) if a.get("estado") == "aberto"]

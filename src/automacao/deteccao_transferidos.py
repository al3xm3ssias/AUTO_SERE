"""
deteccao_transferidos.py
════════════════════════════════════════════════════════════════════════════
Constrói e mantém o transferidos.json a partir do turmas.json.

    turmas.json ──construir_transferidos()──► transferidos.json   (se não existir)
    turmas.json (antigo) + (novo) ──detectar_mudancas()──► processo_transferidos.json
                                  ──sincronizar_transferidos_json()──► transferidos.json

IDENTIDADE (decisão do usuário, 27/10/2026)
    • Um REGISTRO (cadastro) é identificado por  nº da chamada (N) + nome + data de nascimento.
    • Um ALUNO (pessoa) é identificado por  nome + data de nascimento.
      Se o N é diferente, é conceitualmente um "cadastro novo" — mas é o MESMO aluno.
      Ex.:  3 - FULANO - 01/01/2015 - (31/03/2026) Transferido
           31 - FULANO - 01/01/2015 - (22/08/2026) Matriculado   → um só aluno, hoje ativo.
    • A situação ATUAL do aluno é a do registro de data mais recente (desempate: maior N).
      Assim cada pessoa é contada UMA vez (ativo OU transferido), sem divergência de totais.
    • Quem foi transferido e retornou continua em transferidos.json (a guia/histórico emitidos na
      saída são fatos), com o campo "retorno" preenchido — mas conta como ATIVO.

Salvaguardas: sem turmas.json anterior não há deteção; mudança de turma não é saída; turma vazia/
ausente na coleta (falha de leitura) não gera saídas; saída em massa suspende "saiu_da_lista";
nada é apagado de nenhum JSON; falhas aqui nunca derrubam a coleta de turmas.
════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.comum.registros_aluno import eh_transferido, parse_data

LIMITE_SAIDAS_EM_MASSA = 0.25      # fração da base anterior; acima disso, suspende "saiu_da_lista"

STATUS_PENDENTE     = "pendente"       # detetado, ainda não passou para transferidos.json
STATUS_SINCRONIZADO = "sincronizado"   # já existe em transferidos.json
STATUS_RETORNOU     = "retornou"       # voltou a constar como ativo

NOME_PROCESSO_JSON     = "processo_transferidos.json"
NOME_TRANSFERIDOS_JSON = "transferidos.json"
NOME_TURMAS_JSON       = "turmas.json"


# ══════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════════

def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _dados_dir(dados_dir: Optional[Path]) -> Path:
    if dados_dir is not None:
        return Path(dados_dir)
    from src.comum import paths as _paths      # import tardio: mantém o módulo testável isoladamente
    return _paths.dados_ano_atual()


def _ler_json(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _gravar_json(caminho: Path, dados: dict) -> None:
    """Escrita atómica (temporário + replace): uma falha a meio não corrompe o original."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    tmp.replace(caminho)


def _norm_nome(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def _fmt(d: Optional[date]) -> Optional[str]:
    return d.strftime("%d/%m/%Y") if d else None


def _n(aluno: dict) -> Optional[int]:
    try:
        return int(aluno.get("N"))
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════
# AGRUPAMENTO POR ALUNO (pessoa)
# ══════════════════════════════════════════════════════════════════════════

def _pessoas(turmas: dict) -> dict[tuple, list[dict]]:
    """
    {(nome normalizado, data de nascimento): [registros ordenados do mais antigo ao mais recente]}.
    Registros idênticos (mesma turma, N, situação e data) são a mesma linha lida duas vezes → um só.
    """
    pessoas: dict[tuple, list[dict]] = {}
    vistos: set[tuple] = set()
    for turma, alunos in (turmas or {}).items():
        turma = str(turma).strip()
        for a in alunos or []:
            nome = str(a.get("Nome", "")).strip()
            cgm = str(a.get("CGM", "")).strip()
            nasc = str(a.get("Data Nasc.", "")).strip()
            if not nome:
                continue
            situacao = str(a.get("Situação", a.get("Situacao", ""))).strip()
            data_txt = str(a.get("Data Matricula", "")).strip()
            reg = {"turma": turma, "n": _n(a), "cgm": cgm, "nome": nome, "nasc": nasc,
                   "situacao": situacao, "transf": eh_transferido(situacao),
                   "data": parse_data(data_txt), "data_txt": data_txt}
            id_reg = (turma, reg["n"], _norm_nome(nome), nasc, _norm_nome(situacao), data_txt)
            if id_reg in vistos:
                continue
            vistos.add(id_reg)
            chave = (_norm_nome(nome), nasc or f"cgm:{cgm}")      # sem nascimento, o CGM desempata
            pessoas.setdefault(chave, []).append(reg)
    for regs in pessoas.values():
        regs.sort(key=lambda r: (r["data"] or date.min, r["n"] if r["n"] is not None else 0))
    return pessoas


def _ativo(regs: list[dict]) -> bool:
    """Situação ATUAL do aluno: a do registro mais recente."""
    return not regs[-1]["transf"]


# ══════════════════════════════════════════════════════════════════════════
# CRIAÇÃO DO transferidos.json A PARTIR DO turmas.json
# ══════════════════════════════════════════════════════════════════════════

def _registro_vazio(nome: str, turma: str) -> dict:
    """Mesmo esquema de processo_transferidos._registro_vazio (um teste garante que não divergem)."""
    def doc() -> dict:
        return {"emitido_em": None, "assinado_secretario": None,
                "assinado_diretor": None, "anexado_em": None}
    return {"nome": nome, "turma": turma, "guia": doc(), "historico": doc(),
            "parecer": {"digitalizado_em": None, "anexado_em": None}}


def _registro_novo(nome: str, turma: str, chamada=None, nasc=None, data_transf=None,
                   retorno: Optional[dict] = None, anteriores: Optional[list] = None) -> dict:
    reg = _registro_vazio(nome, turma)
    reg.update({"chamada": chamada, "data_nascimento": nasc,
                "data_transferencia": data_transf, "retorno": retorno})
    if anteriores:
        reg["transferencias_anteriores"] = anteriores
    return reg


def construir_transferidos(turmas: dict) -> tuple[dict, dict, list[str]]:
    """
    Monta o dicionário {CGM: registro} só com quem teve algum registro "Transferido".
    Retorna (transferidos, resumo, avisos). O resumo conta cada aluno UMA vez:
        alunos = ativos + transferidos_atuais ;  retornaram ⊆ ativos.
    """
    avisos: list[str] = []
    pessoas = _pessoas(turmas)
    transferidos: dict[str, dict] = {}
    atuais = retornaram = 0

    for regs in pessoas.values():
        if not _ativo(regs):
            atuais += 1
        saidas = [r for r in regs if r["transf"]]
        if not saidas:
            continue
        if sum(1 for r in regs if r["data"] is None) and len(regs) > 1:
            avisos.append(f"{regs[0]['nome']}: registro sem data de movimentação válida — "
                          f"a ordem cronológica foi decidida pelo nº da chamada; confira.")

        por_cgm: dict[str, list[dict]] = {}
        for r in saidas:
            if not r["cgm"]:
                avisos.append(f"{r['nome']} (chamada {r['n']}, {r['turma']}): transferido sem CGM — ignorado.")
                continue
            por_cgm.setdefault(r["cgm"], []).append(r)
        if len(por_cgm) > 1:
            avisos.append(f"{regs[0]['nome']}: transferências com CGMs diferentes {sorted(por_cgm)} — confira.")

        for cgm, lista in por_cgm.items():
            principal = lista[-1]                                    # a transferência mais recente
            depois = regs[regs.index(principal) + 1:]
            retorno = None
            if depois:                                               # há registro posterior → voltou
                r = depois[0]
                retorno = {"chamada": r["n"], "turma": r["turma"], "data": r["data_txt"]}
            anteriores = [{"chamada": r["n"], "turma": r["turma"], "data": r["data_txt"]} for r in lista[:-1]]
            if anteriores:
                avisos.append(f"{principal['nome']} (CGM {cgm}): {len(lista)} transferências no ano — o registro "
                              f"usa a mais recente; as anteriores ficam em 'transferencias_anteriores'.")
            transferidos[cgm] = _registro_novo(principal["nome"], principal["turma"], principal["n"],
                                               principal["nasc"], principal["data_txt"], retorno, anteriores)
        if _ativo(regs):
            retornaram += 1

    resumo = {"alunos": len(pessoas), "ativos": len(pessoas) - atuais, "transferidos_atuais": atuais,
              "retornaram": retornaram, "registros_em_transferidos": len(transferidos)}
    return transferidos, resumo, avisos


def garantir_transferidos_json(dados_dir: Optional[Path] = None, turmas: Optional[dict] = None) -> Optional[dict]:
    """
    Se transferidos.json NÃO existir, cria-o a partir do turmas.json (ou de `turmas`, se já em memória).
    Se existir, não toca em nada e retorna None. Levanta FileNotFoundError se faltar o turmas.json.
    """
    pasta = _dados_dir(dados_dir)
    destino = pasta / NOME_TRANSFERIDOS_JSON
    if destino.exists():
        return None
    if turmas is None:
        origem = pasta / NOME_TURMAS_JSON
        if not origem.exists():
            raise FileNotFoundError(f"{origem} não encontrado — carregue as turmas antes de criar o transferidos.json.")
        turmas = _ler_json(origem)

    transferidos, resumo, avisos = construir_transferidos(turmas)
    _gravar_json(destino, transferidos)
    print(f"  🆕 transferidos.json criado a partir do turmas.json: {len(transferidos)} registro(s).")
    print(f"     {resumo['alunos']} aluno(s) = {resumo['ativos']} ativo(s) + {resumo['transferidos_atuais']} transferido(s); "
          f"{resumo['retornaram']} retornou(aram) após transferência (contado(s) como ativo).")
    for aviso in avisos:
        print(f"  ⚠️  {aviso}")
    return resumo


# ══════════════════════════════════════════════════════════════════════════
# 1) DETEÇÃO DE MUDANÇAS ENTRE DUAS COLETAS (função pura)
# ══════════════════════════════════════════════════════════════════════════

def detectar_mudancas(antigo: dict, novo: dict) -> tuple[list[dict], list[str], list[str]]:
    """
    Retorna (eventos, retornados, avisos): eventos = alunos que eram ATIVOS e passaram a transferidos
    (situação mudou, ou sumiram de todas as turmas); retornados = CGMs de alunos hoje ativos.
    """
    avisos: list[str] = []
    if not antigo:
        return [], [], avisos          # primeira coleta: só serve de base

    pa, pn = _pessoas(antigo), _pessoas(novo)
    turmas_ok = {str(t).strip() for t, alunos in (novo or {}).items() if alunos}
    eventos: list[dict] = []

    def _evento(ultimo: dict, motivo: str, anterior: dict) -> dict:
        return {"cgm": ultimo["cgm"], "nome": ultimo["nome"], "turma": anterior["turma"], "motivo": motivo,
                "situacao_anterior": anterior["situacao"],
                "situacao_atual": ultimo["situacao"] if motivo == "situacao_mudou" else None,
                "chamada": ultimo["n"], "data_nascimento": ultimo["nasc"],
                "data_transferencia": ultimo["data_txt"] if motivo == "situacao_mudou" else None}

    # (a) continuam na lista, mas o registro mais recente agora é "Transferido"
    for chave, regs_n in pn.items():
        if chave in pa and _ativo(pa[chave]) and not _ativo(regs_n):
            eventos.append(_evento(regs_n[-1], "situacao_mudou", pa[chave][-1]))

    # (b) desapareceram de todas as turmas
    candidatos = []
    for chave, regs_a in pa.items():
        if chave in pn or not _ativo(regs_a):
            continue
        if regs_a[-1]["turma"] not in turmas_ok:
            avisos.append(f"Turma '{regs_a[-1]['turma']}' veio vazia/ausente na coleta — {regs_a[-1]['nome']} "
                          f"não foi tratado como saído.")
            continue
        candidatos.append(regs_a[-1])
    base = sum(1 for r in pa.values() if _ativo(r)) or 1
    if len(candidatos) / base > LIMITE_SAIDAS_EM_MASSA:
        avisos.append(f"{len(candidatos)} de {base} alunos sumiram de uma vez — parece falha de coleta; "
                      f"a deteção de 'saiu da lista' foi suspensa nesta execução.")
        candidatos = []
    for ultimo in candidatos:
        eventos.append(_evento(ultimo, "saiu_da_lista", ultimo))

    retornados = sorted({r["cgm"] for regs in pn.values() if _ativo(regs) for r in regs if r["cgm"]})
    return eventos, retornados, avisos


# ══════════════════════════════════════════════════════════════════════════
# 2) processo_transferidos.json
# ══════════════════════════════════════════════════════════════════════════

def registrar_no_processo(eventos: list[dict], retornados: list[str],
                          dados_dir: Optional[Path] = None) -> tuple[int, int]:
    """Acrescenta os eventos a processo_transferidos.json (nunca apaga). Retorna (novos, alterados)."""
    caminho = _dados_dir(dados_dir) / NOME_PROCESSO_JSON
    processo = _ler_json(caminho)
    novos = alterados = 0
    agora = _agora()

    for ev in eventos:
        cgm = ev["cgm"]
        if not cgm:
            continue
        dados_ev = {k: v for k, v in ev.items() if k != "cgm"}
        atual = processo.get(cgm)
        if atual is None:
            processo[cgm] = {**dados_ev, "status": STATUS_PENDENTE, "detectado_em": agora,
                             "sincronizado_em": None, "retornou_em": None}
            novos += 1
        elif atual.get("status") == STATUS_RETORNOU:      # voltou a sair: reabre
            atual.update(dados_ev)
            atual.update({"status": STATUS_PENDENTE, "detectado_em": agora, "retornou_em": None})
            alterados += 1

    for cgm in retornados:
        atual = processo.get(cgm)
        if atual and atual.get("status") != STATUS_RETORNOU:
            atual["status"] = STATUS_RETORNOU           # não mexe em transferidos.json
            atual["retornou_em"] = agora
            alterados += 1

    if novos or alterados:
        _gravar_json(caminho, processo)
    return novos, alterados


# ══════════════════════════════════════════════════════════════════════════
# 3) processo_transferidos.json → transferidos.json
# ══════════════════════════════════════════════════════════════════════════

def sincronizar_transferidos_json(dados_dir: Optional[Path] = None) -> int:
    """
    Para cada entrada 'pendente' cria o registro vazio em transferidos.json (se ainda não existir).
    Registros existentes NÃO são alterados. Retorna quantos foram criados.
    """
    pasta = _dados_dir(dados_dir)
    caminho_proc = pasta / NOME_PROCESSO_JSON
    processo = _ler_json(caminho_proc)
    pendentes = {c: r for c, r in processo.items() if r.get("status") == STATUS_PENDENTE}
    if not pendentes:
        return 0

    caminho_transf = pasta / NOME_TRANSFERIDOS_JSON
    transferidos = _ler_json(caminho_transf)
    criados = 0
    agora = _agora()
    for cgm, reg in pendentes.items():
        if cgm not in transferidos:
            transferidos[cgm] = _registro_novo(reg.get("nome", ""), reg.get("turma", ""), reg.get("chamada"),
                                               reg.get("data_nascimento"), reg.get("data_transferencia"))
            criados += 1
        reg["status"] = STATUS_SINCRONIZADO
        reg["sincronizado_em"] = agora

    if criados:
        _gravar_json(caminho_transf, transferidos)      # primeiro o destino…
    _gravar_json(caminho_proc, processo)                # …depois marca como sincronizado
    return criados


# ══════════════════════════════════════════════════════════════════════════
# 4) PONTO DE ENTRADA (chamado por turmas.py logo após a coleta)
# ══════════════════════════════════════════════════════════════════════════

def processar_mudancas_de_turmas(antigo: dict, novo: dict, dados_dir: Optional[Path] = None) -> dict:
    """
    Cria o transferidos.json se faltar, deteta mudanças, regista e sincroniza.
    Nunca levanta exceção: uma falha aqui não pode estragar a coleta de turmas.
    """
    resumo = {"criado": False, "novos": 0, "marcados": 0, "sincronizados": 0, "avisos": [], "erro": None}
    try:
        resumo["criado"] = garantir_transferidos_json(dados_dir, turmas=novo) is not None
        eventos, retornados, avisos = detectar_mudancas(antigo, novo)
        resumo["avisos"] = avisos
        resumo["novos"], resumo["marcados"] = registrar_no_processo(eventos, retornados, dados_dir)
        resumo["sincronizados"] = sincronizar_transferidos_json(dados_dir)
    except Exception as exc:                      # noqa: BLE001 — isolamento deliberado
        resumo["erro"] = f"{type(exc).__name__}: {exc}"
        print(f"  ❌ Deteção de transferidos falhou (a coleta de turmas NÃO foi afetada): {resumo['erro']}")
        return resumo

    for aviso in resumo["avisos"]:
        print(f"  ⚠️  {aviso}")
    if resumo["novos"]:
        print(f"  🔄 {resumo['novos']} aluno(s) passaram a transferidos → processo_transferidos.json")
    if resumo["sincronizados"]:
        print(f"  💾 {resumo['sincronizados']} registro(s) novo(s) em transferidos.json")
    return resumo

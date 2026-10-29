"""
fila_transferidos.py
════════════════════════════════════════════════════════════════════════════
Fila de transferidos: quem foi transferido (turmas.json) e já entra no processo automático.

    turmas.py ─► turmas.json ─► registrar_fila_transferidos() ─► fila_transferidos.json  (TEMPORÁRIO)
                                                                        │
                       processo_transferidos.processar_transferencias() ◄┘  gera guia e histórico no SERE
                                                                        │
                                                                        ▼
                                              transferidos.json (controle permanente: emitido/assinado/anexado)

• fila_transferidos.json é REGERADO a cada coleta de turmas (não edite à mão): lista TODOS os transferidos e
  marca, pela DATA_CORTE (Configurações), quem entra no processo ("processar") e quem fica de fora
  ("antes_do_corte": já tratado à mão; "retornou": voltou à escola, o processo é feito uma vez só).
• transferidos.json nunca é sobrescrito: só ganha registro (vazio) para quem entra no processo e ainda não tem.

IDENTIDADE (decisão do usuário, 27/10/2026)
    • Um REGISTRO (cadastro) é identificado por  nº da chamada (N) + nome + data de nascimento.
    • Um ALUNO (pessoa) é identificado por  nome + data de nascimento.
      Se o N é diferente, é conceitualmente um "cadastro novo" — mas é o MESMO aluno.
      Ex.:  3 - FULANO - 01/01/2015 - (31/03/2026) Transferido
           31 - FULANO - 01/01/2015 - (22/08/2026) Matriculado   → um só aluno, hoje ativo.
    • A situação ATUAL do aluno é a do registro de data mais recente (desempate: maior N): cada pessoa é
      contada UMA vez (ativo OU transferido), sem divergência de totais.
    • Quem foi transferido e retornou continua na fila, com o campo "retorno" preenchido, mas conta como
      ATIVO e NÃO é processado (decisão do usuário: o processo é feito uma vez, não se refaz).
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

NOME_FILA_JSON         = "fila_transferidos.json"
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


# ══════════════════════════════════════════════════════════════════════════
# FILA (fila_transferidos.json)
# ══════════════════════════════════════════════════════════════════════════

SITUACAO_PROCESSAR = "processar"          # transferido a partir da DATA_CORTE → entra no processo
SITUACAO_ANTES     = "antes_do_corte"     # transferido antes da DATA_CORTE → já tratado à mão
SITUACAO_RETORNOU  = "retornou"           # foi transferido mas voltou à escola → o processo é feito uma vez só: não se refaz
SITUACAO_SEM_DATA  = "sem_data"           # data de movimentação ilegível → fica de fora até alguém conferir


def _data_corte(data_corte: Optional[date]) -> date:
    if data_corte is not None:
        return data_corte
    from src.comum import configuracao as _config          # import tardio: módulo testável isoladamente
    return _config.data_corte_transferidos()


def classificar(registro: dict, data_corte: date) -> str:
    """
    'processar' se a transferência é de DATA_CORTE em diante (inclusive) e o aluno não voltou à escola;
    senão o motivo de ficar de fora (antes do corte = tratado à mão; retornou = não se refaz).
    """
    d = parse_data(registro.get("data_transferencia") or "")
    if d is None:
        return SITUACAO_SEM_DATA
    if d < data_corte:
        return SITUACAO_ANTES
    if registro.get("retorno") is not None:
        return SITUACAO_RETORNOU
    return SITUACAO_PROCESSAR


def montar_fila(turmas: dict, data_corte: Optional[date] = None) -> tuple[dict, list[str]]:
    """Monta (sem gravar) a fila a partir de um turmas.json em memória. Retorna (fila, avisos)."""
    corte = _data_corte(data_corte)
    transferidos, resumo, avisos = construir_transferidos(turmas)

    alunos: dict[str, dict] = {}
    for cgm, reg in transferidos.items():
        situacao = classificar(reg, corte)
        if situacao == SITUACAO_SEM_DATA:
            avisos.append(f"{reg['nome']} (CGM {cgm}): transferido sem data válida — não entra no processo; confira.")
        alunos[cgm] = {"nome": reg["nome"], "turma": reg["turma"], "chamada": reg.get("chamada"),
                       "data_nascimento": reg.get("data_nascimento"),
                       "data_transferencia": reg.get("data_transferencia"),
                       "retornou": reg.get("retorno") is not None, "retorno": reg.get("retorno"),
                       "situacao_fila": situacao, "processar": situacao == SITUACAO_PROCESSAR}
        if reg.get("transferencias_anteriores"):
            alunos[cgm]["transferencias_anteriores"] = reg["transferencias_anteriores"]

    resumo.update({"transferidos_na_fila": len(alunos),
                   "a_processar": sum(1 for a in alunos.values() if a["processar"]),
                   "antes_do_corte": sum(1 for a in alunos.values() if a["situacao_fila"] == SITUACAO_ANTES),
                   "retornaram_sem_processar": sum(1 for a in alunos.values() if a["situacao_fila"] == SITUACAO_RETORNOU),
                   "retornaram": sum(1 for a in alunos.values() if a["retornou"])})
    fila = {"gerado_em": _agora(), "data_corte": corte.strftime("%d/%m/%Y"), "resumo": resumo, "alunos": alunos}
    return fila, avisos


def imprimir_fila(fila: dict, avisos: list[str], simulacao: bool = False) -> None:
    r = fila["resumo"]
    rotulo = "SIMULAÇÃO — nada foi gravado" if simulacao else "gravada em fila_transferidos.json"
    print(f"  📋 Fila de transferidos ({rotulo}) — data de corte {fila['data_corte']}")
    print(f"     {r['alunos']} aluno(s) = {r['ativos']} ativo(s) + {r['transferidos_atuais']} transferido(s) | "
          f"{r['retornaram']} retornou(aram) após transferência (contado(s) como ativo)")
    print(f"     {r['a_processar']} a processar | {r['antes_do_corte']} antes da data de corte (já tratados à mão) | "
          f"{r['retornaram_sem_processar']} retornou(aram) à escola (não se refaz)")
    for cgm, a in fila["alunos"].items():
        marca = {"processar": "▶ processar", "antes_do_corte": "⏭ antes do corte", "retornou": "⏭ retornou",
                 "sem_data": "⚠ sem data"}[a["situacao_fila"]]
        extra = f"  (retornou em {a['retorno']['data']})" if a["retornou"] else ""
        print(f"       {marca:<16} {a['nome']} — CGM {cgm} — {a['turma']} — transferido em {a['data_transferencia']}{extra}")
    for aviso in avisos:
        print(f"  ⚠️  {aviso}")


def registrar_fila_transferidos(turmas: dict, dados_dir: Optional[Path] = None,
                                data_corte: Optional[date] = None, simulacao: bool = False) -> dict:
    """
    Gera a fila a partir do turmas.json. Com `simulacao`, só calcula e mostra (não grava nada).
    Sem simulação: grava fila_transferidos.json (substitui o anterior) e acrescenta a transferidos.json um
    registro vazio para quem vai ser processado e ainda não tem (registros existentes ficam intactos).
    Retorna {"fila", "avisos", "novos_em_transferidos"}.
    """
    fila, avisos = montar_fila(turmas, data_corte)
    novos = 0
    if not simulacao:
        pasta = _dados_dir(dados_dir)
        _gravar_json(pasta / NOME_FILA_JSON, fila)
        caminho = pasta / NOME_TRANSFERIDOS_JSON
        controle = _ler_json(caminho)
        for cgm, a in fila["alunos"].items():
            if a["processar"] and cgm not in controle:
                controle[cgm] = _registro_novo(a["nome"], a["turma"], a["chamada"], a["data_nascimento"],
                                               a["data_transferencia"], a["retorno"],
                                               a.get("transferencias_anteriores"))
                novos += 1
        if novos or not caminho.exists():            # o controle sempre passa a existir (vazio, se ninguém entra)
            _gravar_json(caminho, controle)
    imprimir_fila(fila, avisos, simulacao)
    if novos:
        print(f"  💾 {novos} registro(s) novo(s) em transferidos.json")
    return {"fila": fila, "avisos": avisos, "novos_em_transferidos": novos}


def registrar_fila_sem_falhar(turmas: dict, dados_dir: Optional[Path] = None) -> Optional[dict]:
    """Para o turmas.py: uma falha aqui nunca pode estragar a coleta de turmas (já salva)."""
    try:
        return registrar_fila_transferidos(turmas, dados_dir)
    except Exception as exc:                      # noqa: BLE001 — isolamento deliberado
        print(f"  ❌ Fila de transferidos NÃO foi gerada (a coleta de turmas não foi afetada): "
              f"{type(exc).__name__}: {exc}")
        return None


def ler_fila(dados_dir: Optional[Path] = None) -> Optional[dict]:
    caminho = _dados_dir(dados_dir) / NOME_FILA_JSON
    return _ler_json(caminho) if caminho.exists() else None


def garantir_fila(dados_dir: Optional[Path] = None, data_corte: Optional[date] = None, gravar: bool = True) -> dict:
    """
    Devolve a fila em vigor. Gera-a agora a partir do turmas.json se ainda não existe OU se foi gerada com
    outra DATA_CORTE (a data mudou em Configurações depois da última coleta). FileNotFoundError se faltar o
    turmas.json e não houver fila alguma. Com gravar=False (simulação) a fila é só calculada, nunca gravada.
    """
    pasta = _dados_dir(dados_dir)
    corte = _data_corte(data_corte).strftime("%d/%m/%Y")
    fila = ler_fila(pasta)
    if fila is not None and fila.get("data_corte") == corte:
        return fila
    origem = pasta / NOME_TURMAS_JSON
    if not origem.exists():
        if fila is not None:
            print(f"  ⚠️  A fila foi gerada com a data de corte {fila.get('data_corte')} (agora é {corte}) e não há "
                  f"turmas.json para regerá-la — usando a fila existente.")
            return fila
        raise FileNotFoundError(f"{origem} não encontrado — rode 'Turmas' para coletar as turmas antes.")
    if not gravar:
        fila_nova, _ = montar_fila(_ler_json(origem), data_corte)
        return fila_nova
    return registrar_fila_transferidos(_ler_json(origem), pasta, data_corte)["fila"]


def alunos_a_processar(fila: dict) -> list[dict]:
    """Entradas da fila com processar=True (quem retornou à escola nunca entra), cada uma com seu 'cgm'."""
    return [{"cgm": cgm, **a} for cgm, a in fila.get("alunos", {}).items() if a.get("processar")]


def garantir_transferidos_json(dados_dir: Optional[Path] = None, data_corte: Optional[date] = None) -> bool:
    """
    Se transferidos.json não existe, cria-o a partir do turmas.json (só quem foi transferido e entra no
    processo; a fila é regerada junto). Se existe, não toca em nada. Retorna True se criou.
    FileNotFoundError se faltar o turmas.json.
    """
    pasta = _dados_dir(dados_dir)
    if (pasta / NOME_TRANSFERIDOS_JSON).exists():
        return False
    origem = pasta / NOME_TURMAS_JSON
    if not origem.exists():
        raise FileNotFoundError(f"{origem} não encontrado — rode 'Turmas' para coletar as turmas antes.")
    registrar_fila_transferidos(_ler_json(origem), pasta, data_corte)
    print("  🆕 transferidos.json criado a partir do turmas.json.")
    return True


def executar_fila_transferidos(simulacao: bool = False) -> dict:
    """Menu: regera a fila a partir do turmas.json atual (com `simulacao`, só mostra — não grava nada)."""
    from src.comum import paths as _paths
    pasta = _paths.dados_ano_atual()
    origem = pasta / NOME_TURMAS_JSON
    if not origem.exists():
        raise FileNotFoundError(f"{origem} não encontrado — rode 'Turmas' para coletar as turmas antes.")
    return registrar_fila_transferidos(_ler_json(origem), pasta, simulacao=simulacao)

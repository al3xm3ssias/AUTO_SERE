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
• SEGUNDA SAÍDA (regra do usuário, 17/11/2026): quem saiu, foi processado, voltou e saiu DE NOVO precisa de guia,
  histórico e parecer novos. O registro da 1ª saída vai para `ciclos_anteriores` (nada se perde), os PDFs dela são
  renomeados "<nome> (saída dd-mm-aaaa).pdf" para o 2º ciclo não sobrescrevê-los, e um registro novo (vazio) é criado.

ID DA MATRÍCULA (2026-11-20)
    Cada saída tem o `id_matricula` do período dela na ponte (src/comum/matriculas.py, turmas_relacional.json), que vem
    do ID_MATRICULA das linhas do turmas.json. Com ID nos dois lados, ele decide: ID igual = a MESMA saída (mesmo que a
    data tenha sido corrigida no SERE); ID diferente e data mais nova = OUTRA saída (novo ciclo). Registros antigos, sem
    ID, seguem a regra por datas e adotam o ID na primeira coleta em que a saída é a mesma. O ciclo anterior guarda o
    ID dela e o nome dos PDFs renomeados (`arquivos`), para os documentos ficarem ligados à saída e não ao nome do arquivo.

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
                   "data": parse_data(data_txt), "data_txt": data_txt,
                   "id": str(a.get("ID_MATRICULA") or "").strip()}          # ID do período (ponte); "" em turmas.json antigo
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
                   retorno: Optional[dict] = None, anteriores: Optional[list] = None,
                   id_matricula: Optional[str] = None) -> dict:
    reg = _registro_vazio(nome, turma)
    reg.update({"chamada": chamada, "data_nascimento": nasc,
                "data_transferencia": data_transf, "retorno": retorno})
    if id_matricula:
        reg["id_matricula"] = str(id_matricula)         # só aparece quando a ponte já deu ID a esta saída
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
            anteriores = [{"chamada": r["n"], "turma": r["turma"], "data": r["data_txt"], **({"id": r["id"]} if r["id"] else {})}
                          for r in lista[:-1]]
            if anteriores:
                avisos.append(f"{principal['nome']} (CGM {cgm}): {len(lista)} transferências no ano — o registro "
                              f"usa a mais recente; as anteriores ficam em 'transferencias_anteriores'.")
            transferidos[cgm] = _registro_novo(principal["nome"], principal["turma"], principal["n"],
                                               principal["nasc"], principal["data_txt"], retorno, anteriores,
                                               principal["id"] or None)
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


# ══════════════════════════════════════════════════════════════════════════
# SEGUNDA SAÍDA NO MESMO ANO (novo ciclo de documentos)
# ══════════════════════════════════════════════════════════════════════════

def _data_iso(valor) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(valor)).date() if valor else None
    except ValueError:
        return None


def _ultima_emissao(reg: dict) -> Optional[date]:
    """Data mais recente em que a guia ou o histórico deste registro foram emitidos (None: nada emitido ainda)."""
    datas = [_data_iso((reg.get(doc) or {}).get("emitido_em")) for doc in ("guia", "historico")]
    datas = [d for d in datas if d]
    return max(datas) if datas else None


def _tem_documentos(reg: dict) -> bool:
    """O registro já tem algo emitido/digitalizado (então não pode ser reaproveitado para outra saída)."""
    return _ultima_emissao(reg) is not None or bool((reg.get("parecer") or {}).get("digitalizado_em"))


def e_nova_saida(reg: dict, aluno_da_fila: dict) -> bool:
    """
    O registro de transferidos.json é de uma saída ANTERIOR à que a fila mostra agora?

      • Registro com `data_transferencia`: a saída atual é posterior E a data do registro ainda aparece entre as
        saídas anteriores (se só a data foi corrigida no SERE, a saída é a mesma e nada se refaz).
      • Registro antigo (ou pré-corte), sem `data_transferencia`: os documentos dele foram emitidos ANTES da
        saída atual, logo não podem ser desta saída.
    Em qualquer caso é preciso existir uma saída anterior (`transferencias_anteriores`).

    COM ID DA MATRÍCULA nos dois lados (registro e fila), o ID manda: igual = mesma saída (a data pode ter sido
    corrigida no SERE); diferente = outra saída, desde que a data atual seja posterior à do registro (se não for, é a
    ponte que foi refeita e deu outro ID à MESMA saída: nada se refaz). Aí não se exige a saída anterior na fila.
    """
    d_nova = parse_data(aluno_da_fila.get("data_transferencia") or "")
    id_reg, id_novo = str(reg.get("id_matricula") or ""), str(aluno_da_fila.get("id_matricula") or "")
    por_id = bool(id_reg and id_novo)
    if por_id and id_reg == id_novo:
        return False
    anteriores = {parse_data(x.get("data") or "") for x in aluno_da_fila.get("transferencias_anteriores") or []} - {None}
    if d_nova is None or (not anteriores and not por_id):
        return False
    d_reg = parse_data(reg.get("data_transferencia") or "")
    if d_reg is not None:
        return d_reg < d_nova and (por_id or d_reg in anteriores)
    emissao = _ultima_emissao(reg)
    return emissao is not None and emissao < d_nova


def _guardar_pdfs_do_ciclo(pasta: Path, reg: dict, mapa: Optional[dict] = None) -> list[str]:
    """
    Renomeia os PDFs da saída anterior (histórico e guia) para o novo ciclo não sobrescrevê-los.
    Com `mapa`, preenche {"historico": nome novo, "guia": nome novo} para o ciclo guardar onde ficaram os documentos.
    Levanta OSError se algum não puder ser renomeado (ex.: aberto no leitor de PDF): nesse caso o chamador
    não inicia o novo ciclo, e a próxima execução tenta de novo.
    """
    from src.comum import pastas_transferencias as _pastas

    rotulo = (reg.get("data_transferencia") or "").replace("/", "-")
    if not rotulo:
        d = _ultima_emissao(reg)
        rotulo = d.strftime("%d-%m-%Y") if d else "anterior"
    renomeados = []
    for subpasta in (_pastas.HISTORICO, _pastas.GUIA):
        origem = _pastas.subpasta(subpasta, pasta) / str(reg.get("turma") or "") / f"{reg.get('nome')}.pdf"
        if not origem.exists():
            continue
        destino = origem.with_name(f"{origem.stem} (saída {rotulo}).pdf")
        n = 2
        while destino.exists():
            destino = origem.with_name(f"{origem.stem} (saída {rotulo}) {n}.pdf")
            n += 1
        origem.rename(destino)
        renomeados.append(destino.name)
        if mapa is not None:
            mapa["historico" if subpasta == _pastas.HISTORICO else "guia"] = destino.name
    return renomeados


def _adotar_id(reg: dict, aluno_da_fila: dict) -> bool:
    """
    A saída é a mesma (e_nova_saida disse que não): o registro passa a guardar o ID da ponte. Registro antigo, sem ID,
    adota o atual; se o ID mudou porque a ponte foi refeita, adota o novo e lembra o antigo. True se o registro mudou.
    """
    novo, atual = str(aluno_da_fila.get("id_matricula") or ""), str(reg.get("id_matricula") or "")
    if not novo or novo == atual:
        return False
    if atual:
        reg["id_matricula_anterior"] = atual
    reg["id_matricula"] = novo
    return True


def iniciar_novo_ciclo(controle: dict, cgm: str, a: dict, pasta: Path) -> str:
    """
    Trata a 2ª (3ª...) saída de quem já tem registro em `controle`. Devolve "atualizado" (o registro antigo
    não tinha nada emitido: só ganha os dados da saída atual) ou "novo_ciclo" (o antigo foi para
    `ciclos_anteriores`, os PDFs dele foram renomeados e o registro agora está vazio para o processo refazer).
    """
    antigo = controle[cgm]
    if not _tem_documentos(antigo):
        antigo.update({"nome": a["nome"], "turma": a["turma"], "chamada": a["chamada"],
                       "data_nascimento": a["data_nascimento"], "data_transferencia": a["data_transferencia"],
                       "retorno": a["retorno"]})
        if a.get("id_matricula"):
            antigo["id_matricula"] = a["id_matricula"]
        if a.get("transferencias_anteriores"):
            antigo["transferencias_anteriores"] = a["transferencias_anteriores"]
        descartados = {k: antigo.pop(k) for k in ("vinculo_base_abc", "destino_manual") if antigo.get(k)}
        if descartados:                                             # era da saída anterior (sem documentos): guarda, não apaga
            antigo["destino_anterior"] = {**descartados, "arquivado_em": _agora()}
        return "atualizado"

    arquivos: dict = {}
    _guardar_pdfs_do_ciclo(pasta, antigo, arquivos)             # se falhar, nada abaixo acontece
    ciclo = {k: antigo.get(k) for k in ("chamada", "turma", "data_transferencia", "retorno", "guia", "historico", "parecer")}
    if antigo.get("id_matricula"):
        ciclo["id_matricula"] = antigo["id_matricula"]          # a saída que este ciclo documentou
    if arquivos:
        ciclo["arquivos"] = arquivos                            # onde ficaram a guia e o histórico dela (já renomeados)
    for k in ("vinculo_base_abc", "destino_manual"):               # o destino é da saída: a nova saída começa sem ele
        if antigo.get(k):
            ciclo[k] = antigo[k]
    ciclo["arquivado_em"] = _agora()
    novo = _registro_novo(a["nome"], a["turma"], a["chamada"], a["data_nascimento"], a["data_transferencia"],
                          a["retorno"], a.get("transferencias_anteriores"), a.get("id_matricula"))
    novo["ciclos_anteriores"] = list(antigo.get("ciclos_anteriores") or []) + [ciclo]
    controle[cgm] = novo
    return "novo_ciclo"


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
        if reg.get("id_matricula"):
            alunos[cgm]["id_matricula"] = reg["id_matricula"]

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
    novos = ciclos = 0
    alterou = False
    if not simulacao:
        pasta = _dados_dir(dados_dir)
        _gravar_json(pasta / NOME_FILA_JSON, fila)
        caminho = pasta / NOME_TRANSFERIDOS_JSON
        controle = _ler_json(caminho)
        for cgm, a in fila["alunos"].items():
            if not a["processar"]:
                continue
            if cgm not in controle:
                controle[cgm] = _registro_novo(a["nome"], a["turma"], a["chamada"], a["data_nascimento"],
                                               a["data_transferencia"], a["retorno"],
                                               a.get("transferencias_anteriores"), a.get("id_matricula"))
                novos += 1
            elif e_nova_saida(controle[cgm], a):                       # saiu de novo: precisa de documentos novos
                try:
                    resultado = iniciar_novo_ciclo(controle, cgm, a, pasta)
                except OSError as exc:
                    avisos.append(f"{a['nome']} (CGM {cgm}): saiu de novo, mas os PDFs da saída anterior não puderam "
                                  f"ser renomeados ({exc}). Feche-os e rode de novo; nada foi alterado.")
                    continue
                alterou = True
                if resultado == "novo_ciclo":
                    ciclos += 1
                    avisos.append(f"{a['nome']} (CGM {cgm}): saiu de novo em {a['data_transferencia']} — novos "
                                  f"documentos serão feitos; os da saída anterior ficaram guardados.")
            elif _adotar_id(controle[cgm], a):                         # mesma saída: só liga o registro ao ID da ponte
                alterou = True
        if novos or alterou or not caminho.exists():  # o controle sempre passa a existir (vazio, se ninguém entra)
            _gravar_json(caminho, controle)
    imprimir_fila(fila, avisos, simulacao)
    if novos:
        print(f"  💾 {novos} registro(s) novo(s) em transferidos.json")
    if ciclos:
        print(f"  🔁 {ciclos} aluno(s) que saíram de novo ganharam um novo ciclo de documentos")
    return {"fila": fila, "avisos": avisos, "novos_em_transferidos": novos, "novos_ciclos": ciclos}


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

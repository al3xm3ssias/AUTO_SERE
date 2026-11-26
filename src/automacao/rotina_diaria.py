"""
rotina_diaria.py — rotinas diárias do AUTO SERE, só em dia letivo
=================================================================
Duas formas de rodar (as mesmas etapas, o mesmo código):

  A) SEQUÊNCIA ÚNICA (recomendada)   python -m src.automacao.rotina_diaria sequencia      às 08:00
        1  turmas         coleta turmas (SERE), compara com a coleta anterior (novos, transferidos, retornados, sumidos)
        2  alunos         SÓ OS ALUNOS NOVOS: alunos (básico) e alunos completo --rapido
        3  prematricula   coleta a pré-matrícula e confere quem precisa ser chamado (sem enviar WhatsApp)
        4  origem         SÓ SE houve alunos novos: Base ABC, para registrar de onde cada um veio (buscas_base.json)
        5  consultas      CEP e SISREG (sus) ao mesmo tempo, e registra o que mudou desde a execução anterior
        6  avisos         SÓ SE houve transferidos: aviso na home (gerar os documentos e enviar à escola de destino)
        7  planilha       SÓ SE houve mudança: atualiza a planilha de turmas do Google Sheets
     Uma etapa que depende de outra só roda se a anterior deu certo. Turmas e alunos são OBRIGATÓRIAS: se turmas falha,
     tudo para; se alunos falha, não rodam origem e planilha (as demais seguem). Rodar de novo no mesmo dia RETOMA de onde
     parou (etapas já concluídas hoje são puladas; use --forcar para refazer).

  B) UMA ETAPA POR HORÁRIO (o modo antigo, ainda disponível): virada, turmas, alunos, prematricula, origem,
     consultas, avisos e planilha, cada uma sozinha. Cada etapa confere o resultado da que ela depende.

    07:50  virada      confere o ano; se virou o ano, passa o programa para o novo ano letivo

Toda etapa (menos `status`) começa conferindo o CALENDÁRIO LETIVO da tela "Calendário letivo": fim de semana,
férias, fora dos períodos letivos, feriado nacional/municipal e qualquer recesso/emenda/HTPC/evento cadastrado =
não roda. É a mesma regra da tela (src/web/static/js/calendario.js).

Cada etapa executa os scripts pela CLI do projeto (python -m src.comum.cli ...), cada um num processo separado,
com a saída gravada em logs/rotina_<etapa>.log. Um comando que falha é repetido (TENTATIVAS_POR_COMANDO). O que cada
etapa decidiu fica em dados/<ano>/rotina_estado.json, junto com a FILA de pendências (alunos novos ainda sem coleta,
sem busca de origem e avisos ainda não criados): se uma etapa falhar, o pendente continua na fila no dia seguinte.

Uso:
    python -m src.automacao.rotina_diaria status                  # hoje é dia letivo? qual o próximo? o que rodou? o que está na fila?
    python -m src.automacao.rotina_diaria sequencia --simular     # mostra o que faria, sem executar
    python -m src.automacao.rotina_diaria alunos --forcar         # ignora calendário e "só se houve mudança"
    python -m src.automacao.rotina_diaria status --data 2027-02-01   # testa o calendário em outra data

Códigos de saída: 0 = ok (ou nada a fazer) · 1 = alguma execução falhou.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.comum import paths

log = logging.getLogger("rotina_diaria")

# ───────────────────────────── ajustes ─────────────────────────────
ALUNOS_BASICO = True          # False = a etapa de alunos roda só o alunos completo --rapido
TIMEOUT_ETAPA_S = 3 * 3600    # uma execução que passar disso é encerrada
DIAS_PARA_PROXIMO_LETIVO = 120
TENTATIVAS_POR_COMANDO = 2    # 1 = sem nova tentativa. Só repete falha de execução (código 1); nunca pedido inválido (2) nem tempo esgotado (124)
PAUSA_ENTRE_TENTATIVAS_S = 60
MAX_CGMS_POR_COMANDO = 400    # acima disso a linha de comando fica grande demais: a coleta passa a ser de TODOS os alunos
PREMATRICULA_AVISAR_WHATSAPP = False   # False = a rotina só coleta; o comunicado por WhatsApp fica para quem opera a tela

ETAPAS = ("virada", "turmas", "alunos", "prematricula", "origem", "consultas", "avisos", "planilha", "sequencia", "status")
# Ordem da sequência única e se a etapa é OBRIGATÓRIA (se falhar, as seguintes não rodam).
ORDEM_SEQUENCIA = (("turmas", True), ("alunos", True), ("prematricula", False), ("origem", False),
                   ("consultas", False), ("avisos", False), ("planilha", False))
_DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_TIPOS_EVENTO = {"municipal": "feriado municipal", "recesso": "recesso", "emenda": "emenda de feriado",
                 "htpc": "HTPC", "outro": "evento"}


@dataclass(frozen=True)
class Ctx:
    hoje: date
    forcar: bool = False
    simular: bool = False


# ───────────────────────────── estado em disco ─────────────────────────────
def _ler_json(caminho: Path) -> dict:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_json(caminho: Path, dados: dict) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def _arquivo_estado() -> Path:
    return paths.dados_ano_atual() / "rotina_estado.json"


def _arquivo_global() -> Path:
    return paths.DADOS_DIR / "rotina_global.json"        # vale para todos os anos


def _marcar(ctx: Ctx, etapa: str, **campos) -> None:
    if ctx.simular:
        return
    estado = _ler_json(_arquivo_estado())
    estado[etapa] = {"data": ctx.hoje.isoformat(), "hora": datetime.now().strftime("%H:%M:%S"), **campos}
    _gravar_json(_arquivo_estado(), estado)


def _turmas_de_hoje(ctx: Ctx) -> Optional[dict]:
    reg = _ler_json(_arquivo_estado()).get("turmas") or {}
    return reg if reg.get("data") == ctx.hoje.isoformat() and reg.get("ok") else None


def _estado_etapa(ctx: Ctx, etapa: str) -> str:
    """Como a etapa terminou HOJE: "ok" | "falhou" | "pulada" | "nao_rodou"."""
    reg = _ler_json(_arquivo_estado()).get(etapa) or {}
    if reg.get("data") != ctx.hoje.isoformat():
        return "nao_rodou"
    if reg.get("ok") is True:
        return "ok"
    if reg.get("ok") is False:
        return "falhou"
    return "pulada" if reg.get("pulada") else "nao_rodou"


# Fila de pendências (dentro de rotina_estado.json, chave "fila"): o que as etapas seguintes ainda precisam tratar.
#   alunos       CGMs de alunos novos sem coleta de cadastro
#   alunos_todos True = coletar todos (primeira coleta do ano, ou alunos.json ausente)
#   origem       CGMs de alunos novos (matriculados) sem busca de origem na Base ABC
#   avisos       eventos de transferência/saída ainda sem aviso na home
def _fila() -> dict:
    f = _ler_json(_arquivo_estado()).get("fila") or {}
    return {"alunos": list(f.get("alunos") or []), "alunos_todos": bool(f.get("alunos_todos")),
            "origem": list(f.get("origem") or []), "avisos": list(f.get("avisos") or [])}


def _gravar_fila(ctx: Ctx, fila: dict) -> None:
    if ctx.simular:
        return
    estado = _ler_json(_arquivo_estado())
    estado["fila"] = fila
    _gravar_json(_arquivo_estado(), estado)


def _sem_repetir(lista: list, extra: list, chave=lambda x: x) -> list:
    vistos, saida = set(), []
    for x in [*lista, *extra]:
        k = chave(x)
        if k not in vistos:
            vistos.add(k)
            saida.append(x)
    return saida


def _arquivo_com_dados(caminho: Path) -> bool:
    try:
        return Path(caminho).stat().st_size > 2
    except OSError:
        return False


# ───────────────────────────── calendário letivo ─────────────────────────────
def _feriados_nacionais(ano: int) -> list[dict]:
    """Feriados nacionais do ano: cache em disco do calendário; sem cache, tenta a BrasilAPI (como a tela faz)."""
    from src.web.api import calendario as cal
    cache = cal._pasta_cache() / f"{ano}.json"
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        req = urllib.request.Request(cal.BRASILAPI_URL.format(ano=ano), headers={"User-Agent": "auto-sere-rotina/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            lista = json.loads(resp.read().decode("utf-8"))
        cal._garantir_pastas()
        cache.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
        return lista
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        log.warning("Sem feriados nacionais de %s (sem cache e sem internet): considerando só o calendário cadastrado.", ano)
        return []


def dia_letivo(d: date) -> tuple[bool, str]:
    """(é dia letivo?, motivo). Mesma regra de calendario.js: período letivo, fora de férias, dia útil, sem feriado
    (nacional, fixo da cidade ou municipal cadastrado) e sem nenhum evento cadastrado (recesso, emenda, HTPC, outro)."""
    if d.weekday() >= 5:
        return False, f"fim de semana ({_DIAS[d.weekday()]})"
    from src.web.api import calendario as cal
    iso = d.isoformat()
    dados = cal.carregar_dados()
    periodos = [p for p in dados["periodos"] if str(p.get("inicio")) <= iso <= str(p.get("fim"))]
    for p in periodos:
        if p.get("tipo") == "ferias":
            return False, f"férias escolares ({p.get('nome', '')})"
    if not any(p.get("tipo") != "ferias" for p in periodos):
        return False, "fora dos períodos letivos (cadastre os períodos em Calendário letivo)"
    for h in _feriados_nacionais(d.year):
        if h.get("date") == iso:
            return False, f"feriado nacional ({h.get('name', '')})"
    for f in cal.datas_fixas(d.year):
        if f["tipo"] == "municipal" and f["date"] == iso:
            return False, f"feriado municipal ({f['name']})"
    for e in dados["eventos"]:
        inicio = str(e.get("inicio"))
        if inicio <= iso <= str(e.get("fim") or inicio):
            return False, f"{_TIPOS_EVENTO.get(e.get('tipo'), 'evento')}: {e.get('nome', '')}"
    return True, "dia letivo"


def proximo_dia_letivo(a_partir_de: date) -> Optional[date]:
    d = a_partir_de
    for _ in range(DIAS_PARA_PROXIMO_LETIVO):
        d += timedelta(days=1)
        if dia_letivo(d)[0]:
            return d
    return None


# ───────────────────────────── virada de ano letivo ─────────────────────────────
def garantir_ano_letivo(hoje: Optional[date] = None, simular: bool = False) -> dict:
    """
    Põe o programa no ano letivo do calendário. Chamada por toda etapa e também ao abrir o programa (launcher).

    • AUTO_SERE_ANO_BASE definida  → não mexe (é a forma de continuar no ano anterior em jan/fev).
    • ano em uso < ano civil       → troca para o ano automático (src.comum.ano_letivo.trocar_ano(None)), UMA vez por
                                     ano civil: se você voltar de propósito a um ano anterior depois disso, ele respeita.
    • ano novo ainda sem pasta     → cria dados/<ano>/ e avisa se o calendário do ano não tem períodos letivos.
    Devolve {"acao": ..., "ano": ...}; acao ∈ fixado_por_ambiente | virou | novo_ano | nada | voltado_de_proposito.
    """
    hoje = hoje or date.today()
    if os.getenv("AUTO_SERE_ANO_BASE"):
        return {"acao": "fixado_por_ambiente", "ano": paths.ano_atual()}
    glob = _ler_json(_arquivo_global())
    ativo, civil = int(paths.ano_atual()), hoje.year
    acao = "nada"

    if ativo < civil:
        if glob.get("virada_ano") == civil:
            log.warning("Ano letivo em uso: %s (anterior ao de %s). Voltado de propósito? Nada foi alterado.", ativo, civil)
            return {"acao": "voltado_de_proposito", "ano": str(ativo)}
        if simular:
            log.info("[simulação] trocaria o ano letivo %s → %s", ativo, civil)
            return {"acao": "virou", "ano": str(civil)}
        from src.comum import ano_letivo
        res = ano_letivo.trocar_ano(None)
        glob["virada_ano"] = civil
        _gravar_json(_arquivo_global(), glob)
        ativo, acao = int(res["novo"]), "virou"
        log.info("NOVO ANO LETIVO: %s → %s.", res["antigo"], res["novo"])

    if glob.get("ano_iniciado") != ativo and not simular:
        pasta_nova = not (paths.DADOS_DIR / str(ativo) / "turmas.json").exists()
        paths.garantir_diretorios_runtime()
        glob["ano_iniciado"] = ativo
        _gravar_json(_arquivo_global(), glob)
        if pasta_nova:
            acao = "novo_ano" if acao == "nada" else acao
            log.info("Ano letivo %s preparado em %s. As turmas serão coletadas no primeiro dia letivo.",
                     ativo, paths.dados_ano_atual())
            from src.web.api import calendario as cal
            if not cal.carregar_dados()["periodos"]:
                log.warning("O calendário de %s ainda não tem períodos letivos: nenhuma rotina vai rodar até você "
                            "cadastrá-los em Calendário letivo.", ativo)
    return {"acao": acao, "ano": str(ativo)}


# ───────────────────────────── execução dos scripts ─────────────────────────────
def _lancar(etapa: str, c: list[str], env: dict, flags: int):
    cmd = [sys.executable, "-m", "src.comum.cli", *c]
    arq = open(paths.LOGS_DIR / f"rotina_{etapa}.log", "a", encoding="utf-8")
    resumo = " ".join(c) if len(" ".join(c)) <= 200 else " ".join(c)[:200] + " …"
    arq.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} · {resumo}\n")
    arq.flush()
    log.info("Executando: %s", resumo)
    proc = subprocess.Popen(cmd, cwd=paths.RAIZ_PROJETO, env=env, stdin=subprocess.DEVNULL, stdout=arq,
                            stderr=subprocess.STDOUT, creationflags=flags)
    return proc, arq


def _executar(ctx: Ctx, etapa: str, comandos: list[list[str]]) -> list[int]:
    """Roda um ou mais comandos da CLI AO MESMO TEMPO (cada um num processo) e devolve os códigos de saída.
    Um comando que falha (código 1) é repetido até TENTATIVAS_POR_COMANDO vezes, com pausa; só os que falharam."""
    if ctx.simular:
        for c in comandos:
            log.info("[simulação] python -m src.comum.cli %s", " ".join(c))
        return [0] * len(comandos)
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    flags = 0x08000000 if os.name == "nt" else 0           # CREATE_NO_WINDOW
    codigos: list[int] = [1] * len(comandos)
    pendentes = list(range(len(comandos)))
    for tentativa in range(1, max(1, TENTATIVAS_POR_COMANDO) + 1):
        abertos = [(i, comandos[i], *_lancar(etapa, comandos[i], env, flags)) for i in pendentes]
        repetir = []
        for i, c, proc, arq in abertos:
            try:
                rc = proc.wait(timeout=TIMEOUT_ETAPA_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = 124
                log.error("'%s' passou de %s s e foi encerrado.", " ".join(c)[:120], TIMEOUT_ETAPA_S)
            arq.close()
            (log.info if rc == 0 else log.error)("'%s' terminou com código %s (tentativa %s).", " ".join(c)[:120], rc, tentativa)
            codigos[i] = rc
            if rc not in (0, 2, 124) and tentativa < TENTATIVAS_POR_COMANDO:
                repetir.append(i)
        if not repetir:
            break
        log.warning("%s comando(s) falharam; nova tentativa em %s s.", len(repetir), PAUSA_ENTRE_TENTATIVAS_S)
        time.sleep(PAUSA_ENTRE_TENTATIVAS_S)
        pendentes = repetir
    return codigos


# ───────────────────────────── detecção de mudanças ─────────────────────────────
def _carregar_turmas() -> dict:
    return _ler_json(paths.dados_ano_atual() / "turmas.json")


def _cgms(turmas: dict) -> set[str]:
    return {str(a.get("CGM", "")).strip() for alunos in (turmas or {}).values() for a in (alunos or [])
            if str(a.get("CGM", "")).strip()}


def _ativos(turmas: dict) -> set[str]:
    from src.comum.registros_aluno import eh_transferido
    return {str(a.get("CGM", "")).strip() for alunos in (turmas or {}).values() for a in (alunos or [])
            if str(a.get("CGM", "")).strip() and not eh_transferido(str(a.get("Situação", a.get("Situacao", ""))))}


def comparar_turmas(antes: dict, depois: dict) -> dict:
    """
    Compara a coleta anterior de turmas.json com a nova.
      novos          CGM que não existia antes
      transferidos   era ATIVO e o SERE agora mostra "Transferido" (a situação mudou). Só isto é transferência.
      sumiram        era ativo e SUMIU de todas as turmas sem constar como transferido. NÃO se presume transferência:
                     vira um aviso "a verificar" (mesma regra de identidade de src/automacao/deteccao_transferidos.py,
                     inclusive as travas contra turma vazia e saída em massa)
      retornaram     estava só como transferido e voltou a ativo
      eventos        os detalhes de transferidos e sumiram (cgm, nome, turma, motivo, data_transferencia)
    Sem coleta anterior = primeira coleta (tudo conta como novo; nada é transferido nem sumido).
    """
    if not antes:
        return {"primeira_coleta": True, "novos": sorted(_cgms(depois)), "transferidos": [], "retornaram": [],
                "sumiram": [], "eventos": []}
    from src.automacao.deteccao_transferidos import detectar_mudancas
    eventos, _, _ = detectar_mudancas(antes, depois)
    so_transferidos_antes = _cgms(antes) - _ativos(antes)
    transferidos = [e for e in eventos if e.get("cgm") and e.get("motivo") == "situacao_mudou"]
    sumiram = [e for e in eventos if e.get("cgm") and e.get("motivo") != "situacao_mudou"]
    resumo = lambda e: {k: e.get(k) for k in ("cgm", "nome", "turma", "motivo", "data_transferencia")}   # noqa: E731
    return {"primeira_coleta": False,
            "novos": sorted(_cgms(depois) - _cgms(antes)),
            "transferidos": sorted({e["cgm"] for e in transferidos}),
            "retornaram": sorted(_ativos(depois) & so_transferidos_antes),
            "sumiram": sorted({e["cgm"] for e in sumiram}),
            "eventos": [resumo(e) for e in [*transferidos, *sumiram]]}


def _houve_mudanca(mud: dict) -> bool:
    return bool(mud["novos"] or mud["transferidos"] or mud["retornaram"] or mud.get("sumiram"))


def _somar_ao_do_dia(ctx: Ctx, mud: dict) -> dict:
    """Rodar a coleta de novo no mesmo dia compara o arquivo de hoje com ele mesmo e não acharia nada: o que as
    execuções anteriores de hoje já tinham achado é mantido no registro do dia."""
    antes = _turmas_de_hoje(ctx)
    if not antes:
        return mud
    soma = dict(mud)
    for campo in ("novos", "transferidos", "retornaram", "sumiram"):
        soma[campo] = sorted(set(mud[campo]) | set(antes.get(campo) or []))
    soma["eventos"] = _sem_repetir(list(antes.get("eventos") or []), mud["eventos"], chave=lambda e: (e.get("cgm"), e.get("motivo")))
    soma["primeira_coleta"] = bool(mud["primeira_coleta"] or antes.get("primeira_coleta"))
    return soma


def _enfileirar(ctx: Ctx, delta: dict, depois: dict) -> None:
    """Põe na fila o que ESTA coleta achou de novo (alunos a coletar, origem a buscar, avisos a criar)."""
    fila = _fila()
    if delta["primeira_coleta"]:
        fila["alunos_todos"] = True            # primeira coleta do ano: ninguém é "novo" de verdade; coleta todos, sem busca de origem
    else:
        ativos = _ativos(depois)
        fila["alunos"] = _sem_repetir(fila["alunos"], delta["novos"])
        fila["origem"] = _sem_repetir(fila["origem"], [c for c in delta["novos"] if c in ativos])
    fila["avisos"] = _sem_repetir(fila["avisos"], delta["eventos"], chave=lambda e: (e.get("cgm"), e.get("motivo")))
    _gravar_fila(ctx, fila)


# ───────────────────────────── etapas ─────────────────────────────
def etapa_virada(ctx: Ctx) -> int:
    r = garantir_ano_letivo(ctx.hoje, ctx.simular)
    log.info("Virada de ano: %s (ano letivo %s).", r["acao"], r["ano"])
    return 0


def etapa_turmas(ctx: Ctx) -> int:
    antes = {} if ctx.simular else _carregar_turmas()
    rc = max(_executar(ctx, "turmas", [["turmas"]]))
    if ctx.simular:
        return 0
    if rc != 0:
        _marcar(ctx, "turmas", ok=False, codigo=rc)
        return 1
    depois = _carregar_turmas()
    if not any(depois.values()):                           # defesa: a coleta "deu certo" mas não trouxe nenhum aluno
        log.error("turmas.json ficou sem nenhum aluno: coleta tratada como falha.")
        _marcar(ctx, "turmas", ok=False, erro="turmas.json sem nenhum aluno")
        return 1
    delta = comparar_turmas(antes, depois)
    mud = _somar_ao_do_dia(ctx, delta)
    _marcar(ctx, "turmas", ok=True, mudou=_houve_mudanca(mud), **mud)
    _enfileirar(ctx, delta, depois)
    log.info("Mudanças: %s novo(s), %s transferido(s), %s retornado(s), %s sumido(s) sem transferência%s.", len(mud["novos"]),
             len(mud["transferidos"]), len(mud["retornaram"]), len(mud["sumiram"]),
             " (primeira coleta do ano)" if mud["primeira_coleta"] else "")
    return 0


def _precisa_de_mudanca(ctx: Ctx, etapa: str) -> Optional[dict]:
    """Registro das turmas de hoje se a etapa deve rodar; None (e já loga o motivo) se deve ser pulada."""
    if ctx.forcar:
        return _turmas_de_hoje(ctx) or {}
    reg = _turmas_de_hoje(ctx)
    if reg is None:
        log.info("Etapa '%s' pulada: a coleta de turmas de hoje não terminou com sucesso.", etapa)
        _marcar(ctx, etapa, pulada="turmas de hoje não concluiu")
        return None
    if not reg.get("mudou"):
        log.info("Etapa '%s' pulada: nenhuma mudança nas turmas hoje.", etapa)
        _marcar(ctx, etapa, pulada="sem mudanças")
        return None
    return reg


def _pular(ctx: Ctx, etapa: str, motivo: str) -> int:
    log.info("Etapa '%s' pulada: %s.", etapa, motivo)
    _marcar(ctx, etapa, pulada=motivo)
    return 0


def _com_cgms(comando: list[str], cgms: Optional[list[str]]) -> list[str]:
    return comando + (["--cgms", ",".join(cgms)] if cgms else [])


def etapa_alunos(ctx: Ctx) -> int:
    """Consulta SÓ os alunos novos (fila de pendências). Todos os alunos apenas na primeira coleta do ano, se o
    arquivo ainda não existe, se são mais de MAX_CGMS_POR_COMANDO, ou com --forcar sem ninguém na fila."""
    if not ctx.forcar and _turmas_de_hoje(ctx) is None:
        return _pular(ctx, "alunos", "turmas de hoje não concluiu")
    fila = _fila()
    todos = fila["alunos_todos"] or len(fila["alunos"]) > MAX_CGMS_POR_COMANDO
    if not todos and not fila["alunos"]:
        if not ctx.forcar:
            return _pular(ctx, "alunos", "sem alunos novos")
        todos = True
    cgms = [] if todos else list(fila["alunos"])
    pasta = paths.dados_ano_atual()
    cg_basico = None if todos or not _arquivo_com_dados(pasta / "alunos.json") else cgms
    cg_completo = None if todos or not _arquivo_com_dados(pasta / "alunos_completo.json") else cgms
    comandos = ([_com_cgms(["alunos", "--modo", "basico"], cg_basico)] if ALUNOS_BASICO else []) + \
               [_com_cgms(["alunos", "--modo", "completo", "--rapido"], cg_completo)]
    codigos = []
    for c in comandos:                                    # um depois do outro (os dois usam o login do SERE)
        codigos += _executar(ctx, "alunos", [c])
    rc = max(codigos)
    if rc == 0 and not ctx.simular:
        fila = _fila()
        fila["alunos"] = [] if todos else [c for c in fila["alunos"] if c not in set(cgms)]
        fila["alunos_todos"] = False if todos else fila["alunos_todos"]
        _gravar_fila(ctx, fila)
    _marcar(ctx, "alunos", ok=rc == 0, codigos=codigos, selecao="todos" if todos else "novos", quantidade=len(cgms))
    return 0 if rc == 0 else 1


def etapa_prematricula(ctx: Ctx) -> int:
    """Coleta a pré-matrícula e confere quem precisa ser chamado (as regras são as da tela Pré-matrícula).
    Roda todo dia letivo: a lista muda no portal, não nas turmas."""
    comando = ["prematricula_completa"] + ([] if PREMATRICULA_AVISAR_WHATSAPP else ["--sem-whatsapp"])
    rc = _executar(ctx, "prematricula", [comando])[0]
    _marcar(ctx, "prematricula", ok=rc == 0, codigo=rc)
    return 0 if rc == 0 else 1


def etapa_origem(ctx: Ctx) -> int:
    """Base ABC para os alunos novos (matriculados): de onde cada um veio. O resultado fica em buscas_base.json."""
    if _estado_etapa(ctx, "alunos") == "falhou":
        return _pular(ctx, "origem", "a coleta de alunos de hoje falhou")
    fila = _fila()
    cgms = fila["origem"][:MAX_CGMS_POR_COMANDO]
    if not cgms:
        return _pular(ctx, "origem", "sem alunos novos")
    rc = _executar(ctx, "origem", [["base_abc", "--alunos-texto", "\n".join(cgms)]])[0]
    if rc == 0 and not ctx.simular:
        fila = _fila()
        fila["origem"] = [c for c in fila["origem"] if c not in set(cgms)]
        _gravar_fila(ctx, fila)
    _marcar(ctx, "origem", ok=rc == 0, codigo=rc, quantidade=len(cgms))
    return 0 if rc == 0 else 1


ARQUIVOS_CONSULTAS = {"sisreg": "alunos_encaminhamento.json", "cep": "alunos_fora_raio.json"}
_LIMITE_LISTA_ESTADO = 50


def _ler_qualquer(caminho: Path):
    """JSON do arquivo, ou None se não existe/está ilegível."""
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _itens_por_chave(dados) -> dict[str, str]:
    """{chave do aluno: conteúdo} de uma saída de SISREG (lista) ou de CEP ({"metadados", "alunos"}); os metadados
    (data da análise etc.) ficam de fora para não contarem como mudança."""
    if isinstance(dados, dict):
        dados = dados.get("alunos", [])
    saida: dict[str, str] = {}
    for i, it in enumerate(dados if isinstance(dados, list) else []):
        if isinstance(it, dict):
            chave = str(it.get("cgm") or it.get("CGM") or it.get("nome") or it.get("Nome") or f"#{i}")
            saida[chave] = json.dumps(it, sort_keys=True, ensure_ascii=False)
    return saida


def comparar_resultados(antes, depois) -> dict:
    """O que mudou entre duas execuções de SISREG/CEP. `antes` None = primeira execução (só serve de base)."""
    if antes is None:
        return {"mudou": False, "primeira_execucao": True}
    a, d = _itens_por_chave(antes), _itens_por_chave(depois)
    novos = sorted(set(d) - set(a))
    removidos = sorted(set(a) - set(d))
    alterados = sorted(k for k in set(a) & set(d) if a[k] != d[k])
    cortar = lambda lista: lista[:_LIMITE_LISTA_ESTADO]   # noqa: E731
    return {"mudou": bool(novos or removidos or alterados), "primeira_execucao": False,
            "novos": cortar(novos), "removidos": cortar(removidos), "alterados": cortar(alterados),
            "totais": {"novos": len(novos), "removidos": len(removidos), "alterados": len(alterados)}}


def etapa_consultas(ctx: Ctx) -> int:
    """CEP e SISREG (sus) em simultâneo; depois compara os resultados com os da execução anterior e registra o que mudou."""
    pasta = paths.dados_ano_atual()
    antes = {} if ctx.simular else {k: _ler_qualquer(pasta / v) for k, v in ARQUIVOS_CONSULTAS.items()}
    codigos = _executar(ctx, "consultas", [["cep"], ["sus"]])          # em simultâneo
    campos: dict = {}
    if not ctx.simular:
        for nome, rc in (("cep", codigos[0]), ("sisreg", codigos[1])):
            if rc != 0:
                continue                                              # falhou: o arquivo não é confiável para comparar
            r = comparar_resultados(antes[nome], _ler_qualquer(pasta / ARQUIVOS_CONSULTAS[nome]))
            campos[nome] = r
            if r.get("primeira_execucao"):
                log.info("%s: primeira execução registrada (sem comparação).", nome.upper())
            else:
                t = r["totais"]
                log.info("%s: %s novo(s), %s removido(s), %s alterado(s)%s.", nome.upper(), t["novos"], t["removidos"],
                         t["alterados"], "" if r["mudou"] else " — nenhuma alteração")
    _marcar(ctx, "consultas", ok=max(codigos) == 0, codigos=codigos, **campos)
    return 0 if max(codigos) == 0 else 1


def etapa_avisos(ctx: Ctx) -> int:
    """Cria na home os avisos de transferência (e de saída a verificar) que estão na fila. Sem ninguém na fila, não cria nada."""
    if not ctx.forcar and _turmas_de_hoje(ctx) is None:
        return _pular(ctx, "avisos", "turmas de hoje não concluiu")
    fila = _fila()
    eventos = fila["avisos"]
    if ctx.simular:
        log.info("[simulação] criaria %s aviso(s) na home.", len(eventos))
        return 0
    from src.comum import painel_avisos
    try:
        r = painel_avisos.registrar_da_comparacao(eventos, paths.dados_ano_atual()) if eventos else \
            {"criados": 0, "ja_existiam": 0, "ignorados": 0}
        painel_avisos.reavaliar(paths.dados_ano_atual())              # resolve os que já tiveram documentos gerados e enviados
    except Exception:                                                  # noqa: BLE001
        log.exception("Não foi possível gravar os avisos da home.")
        _marcar(ctx, "avisos", ok=False, erro="falha ao gravar painel_avisos.json")
        return 1
    fila["avisos"] = []
    _gravar_fila(ctx, fila)
    _marcar(ctx, "avisos", ok=True, **r)
    log.info("Avisos da home: %s criado(s), %s já existiam, %s ignorado(s).", r["criados"], r["ja_existiam"], r["ignorados"])
    return 0


def etapa_planilha(ctx: Ctx) -> int:
    if _precisa_de_mudanca(ctx, "planilha") is None:
        return 0
    if not ctx.forcar and _estado_etapa(ctx, "alunos") == "falhou":
        return _pular(ctx, "planilha", "a coleta de alunos de hoje falhou")
    from src.automacao.sincroniza_sheets import localizar_planilha
    try:
        localizar_planilha()                                          # a vigente no gerenciador de planilhas
    except ValueError as exc:
        log.error("%s", exc)
        _marcar(ctx, "planilha", ok=False, erro="sem planilha das turmas ativa no cadastro")
        return 1
    rc = _executar(ctx, "planilha", [["sheets", "--operacao", "atualizar", "--confirmo"]])[0]
    _marcar(ctx, "planilha", ok=rc == 0, codigo=rc)
    return 0 if rc == 0 else 1


def etapa_sequencia(ctx: Ctx) -> int:
    """Todas as etapas, uma depois da outra. Obrigatórias (turmas, alunos): se falham, a sequência para. As outras
    registram a falha e a sequência segue. Etapas já concluídas hoje são puladas (retomada), salvo com --forcar."""
    log.info("=== SEQUÊNCIA DIÁRIA: %s ===", " → ".join(n for n, _ in ORDEM_SEQUENCIA))
    resultados: dict[str, str] = {}
    interrompida_em = None
    for nome, obrigatoria in ORDEM_SEQUENCIA:
        if interrompida_em:
            resultados[nome] = "nao_executada"
            continue
        if not ctx.forcar and not ctx.simular and _estado_etapa(ctx, nome) == "ok":
            log.info("Etapa '%s' já concluída hoje: pulada (retomada).", nome)
            resultados[nome] = "ja_concluida"
            continue
        log.info("--- Etapa '%s'%s ---", nome, " (obrigatória)" if obrigatoria else "")
        try:
            rc = _ETAPAS[nome](ctx)
        except Exception:                                              # noqa: BLE001
            log.exception("A etapa '%s' levantou uma exceção.", nome)
            _marcar(ctx, nome, ok=False, erro="exceção (veja o log)")
            rc = 1
        resultados[nome] = "ok" if rc == 0 else "falhou"
        if rc != 0 and obrigatoria:
            log.error("Etapa obrigatória '%s' falhou: as etapas seguintes não serão executadas.", nome)
            interrompida_em = nome
    falhas = [n for n, r in resultados.items() if r == "falhou"]
    _marcar(ctx, "sequencia", ok=not falhas, etapas=resultados, interrompida_em=interrompida_em)
    log.info("=== SEQUÊNCIA %s: %s ===", "CONCLUÍDA" if not falhas else "COM FALHAS",
             ", ".join(f"{n}={r}" for n, r in resultados.items()))
    return 1 if falhas else 0


def etapa_status(ctx: Ctx) -> int:
    ok, motivo = dia_letivo(ctx.hoje)
    print(f"{ctx.hoje:%d/%m/%Y} ({_DIAS[ctx.hoje.weekday()]}): {'DIA LETIVO' if ok else 'sem aula'} — {motivo}")
    if not ok:
        prox = proximo_dia_letivo(ctx.hoje)
        print("Próximo dia letivo:", f"{prox:%d/%m/%Y} ({_DIAS[prox.weekday()]})" if prox else
              f"nenhum nos próximos {DIAS_PARA_PROXIMO_LETIVO} dias (confira o Calendário letivo)")
    print(f"Ano letivo em uso: {paths.ano_atual()} · ano do calendário: {ctx.hoje.year}"
          + (" · AUTO_SERE_ANO_BASE fixa o ano" if os.getenv("AUTO_SERE_ANO_BASE") else ""))
    estado = _ler_json(_arquivo_estado())
    ocultos = ("data", "hora", "novos", "transferidos", "retornaram", "sumiram", "eventos", "cep", "sisreg")
    for nome, reg in estado.items():
        if nome == "fila":
            continue
        print(f"  {nome:<12} {reg.get('data')} {reg.get('hora', '')}  "
              + ", ".join(f"{k}={v}" for k, v in reg.items() if k not in ocultos))
    f = _fila()
    print(f"  fila: {len(f['alunos'])} aluno(s) novo(s) a coletar{' (ou todos)' if f['alunos_todos'] else ''}, "
          f"{len(f['origem'])} sem busca de origem, {len(f['avisos'])} aviso(s) a criar na home")
    return 0


_ETAPAS = {"virada": etapa_virada, "turmas": etapa_turmas, "alunos": etapa_alunos, "prematricula": etapa_prematricula,
           "origem": etapa_origem, "consultas": etapa_consultas, "avisos": etapa_avisos, "planilha": etapa_planilha,
           "sequencia": etapa_sequencia, "status": etapa_status}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.automacao.rotina_diaria", description=__doc__.split("\n\n")[0])
    ap.add_argument("etapa", choices=ETAPAS)
    ap.add_argument("--forcar", action="store_true", help="ignora o calendário letivo e o 'só se houve mudança'")
    ap.add_argument("--simular", action="store_true", help="mostra o que faria, sem executar nem gravar nada")
    ap.add_argument("--data", help="AAAA-MM-DD: faz de conta que hoje é esta data (para testar o calendário)")
    args = ap.parse_args(argv)
    try:
        hoje = date.fromisoformat(args.data) if args.data else date.today()
    except ValueError:
        print("ERRO: --data deve ser AAAA-MM-DD.", file=sys.stderr)
        return 2
    ctx = Ctx(hoje=hoje, forcar=args.forcar, simular=args.simular)

    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[
        logging.FileHandler(paths.LOGS_DIR / "rotina_diaria.log", encoding="utf-8"), logging.StreamHandler()])
    try:
        if args.etapa not in ("status", "virada"):
            garantir_ano_letivo(hoje, ctx.simular)
        if args.etapa not in ("status", "virada") and not args.forcar:
            ok, motivo = dia_letivo(hoje)
            if not ok:
                log.info("Etapa '%s' não executada: %s.", args.etapa, motivo)
                return 0
        return _ETAPAS[args.etapa](ctx)
    except Exception:                                                  # noqa: BLE001 — vira log + código 1
        log.exception("A etapa '%s' falhou.", args.etapa)
        return 1


if __name__ == "__main__":
    sys.exit(main())

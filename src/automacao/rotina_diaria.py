"""
rotina_diaria.py — rotinas diárias do AUTO SERE, só em dia letivo
=================================================================
Pensado para ser chamado pelo Agendador de Tarefas do Windows (ver scripts/windows/agendar_rotinas.ps1),
uma etapa por horário:

    07:50  virada      confere o ano; se virou o ano, passa o programa para o novo ano letivo
    08:00  turmas      coleta turmas (SERE) e vê se houve aluno novo / transferido / que retornou
    09:00  alunos      SÓ SE houve mudança: alunos (básico) e, em seguida, alunos completo --rapido
    10:00  planilha    SÓ SE houve mudança: atualiza a planilha do Google Sheets
    11:00  consultas   CEP e SISREG (sus) ao mesmo tempo

Toda etapa (menos `status`) começa conferindo o CALENDÁRIO LETIVO da tela "Calendário letivo": fim de semana,
férias, fora dos períodos letivos, feriado nacional/municipal e qualquer recesso/emenda/HTPC/evento cadastrado =
não roda. É a mesma regra da tela (src/web/static/js/calendario.js).

Cada etapa executa os scripts pela CLI do projeto (python -m src.comum.cli ...), cada um num processo separado,
com a saída gravada em logs/rotina_<etapa>.log. O que uma etapa decidiu fica em dados/<ano>/rotina_estado.json
(é como o das 09h sabe o que o das 08h encontrou).

Uso:
    python -m src.automacao.rotina_diaria status                  # hoje é dia letivo? qual o próximo? o que rodou?
    python -m src.automacao.rotina_diaria turmas --simular        # mostra o que faria, sem executar
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
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.comum import paths

log = logging.getLogger("rotina_diaria")

# ───────────────────────────── ajustes ─────────────────────────────
ALUNOS_BASICO = True          # False = a etapa das 09h roda só o alunos completo --rapido
TIMEOUT_ETAPA_S = 3 * 3600    # uma execução que passar disso é encerrada
DIAS_PARA_PROXIMO_LETIVO = 120

ETAPAS = ("virada", "turmas", "alunos", "planilha", "consultas", "status")
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
def _executar(ctx: Ctx, etapa: str, comandos: list[list[str]]) -> list[int]:
    """Roda um ou mais comandos da CLI AO MESMO TEMPO (cada um num processo) e devolve os códigos de saída."""
    if ctx.simular:
        for c in comandos:
            log.info("[simulação] python -m src.comum.cli %s", " ".join(c))
        return [0] * len(comandos)
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    flags = 0x08000000 if os.name == "nt" else 0           # CREATE_NO_WINDOW
    abertos = []
    for c in comandos:
        cmd = [sys.executable, "-m", "src.comum.cli", *c]
        arq = open(paths.LOGS_DIR / f"rotina_{etapa}.log", "a", encoding="utf-8")
        arq.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} · {' '.join(c)}\n")
        arq.flush()
        log.info("Executando: %s", " ".join(c))
        proc = subprocess.Popen(cmd, cwd=paths.RAIZ_PROJETO, env=env, stdin=subprocess.DEVNULL, stdout=arq,
                                stderr=subprocess.STDOUT, creationflags=flags)
        abertos.append((c, proc, arq))
    codigos = []
    for c, proc, arq in abertos:
        try:
            rc = proc.wait(timeout=TIMEOUT_ETAPA_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = 124
            log.error("'%s' passou de %s s e foi encerrado.", " ".join(c), TIMEOUT_ETAPA_S)
        arq.close()
        (log.info if rc == 0 else log.error)("'%s' terminou com código %s.", " ".join(c), rc)
        codigos.append(rc)
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
    """Aluno novo (CGM que não existia antes), transferido (era ativo e saiu; mesma regra de identidade de
    src/automacao/deteccao_transferidos.py) e retornado (estava só como transferido e voltou a ativo).
    Sem coleta anterior = primeira coleta (tudo conta como novo)."""
    if not antes:
        return {"primeira_coleta": True, "novos": sorted(_cgms(depois)), "transferidos": [], "retornaram": []}
    from src.automacao.deteccao_transferidos import detectar_mudancas
    eventos, _, _ = detectar_mudancas(antes, depois)
    so_transferidos_antes = _cgms(antes) - _ativos(antes)
    return {"primeira_coleta": False,
            "novos": sorted(_cgms(depois) - _cgms(antes)),
            "transferidos": sorted({e["cgm"] for e in eventos if e.get("cgm")}),
            "retornaram": sorted(_ativos(depois) & so_transferidos_antes)}


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
    mud = comparar_turmas(antes, _carregar_turmas())
    mudou = bool(mud["novos"] or mud["transferidos"] or mud["retornaram"])
    _marcar(ctx, "turmas", ok=True, mudou=mudou, **mud)
    log.info("Mudanças: %s novo(s), %s transferido(s), %s retornado(s)%s.", len(mud["novos"]), len(mud["transferidos"]),
             len(mud["retornaram"]), " (primeira coleta do ano)" if mud["primeira_coleta"] else "")
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


def etapa_alunos(ctx: Ctx) -> int:
    if _precisa_de_mudanca(ctx, "alunos") is None:
        return 0
    comandos = ([["alunos", "--modo", "basico"]] if ALUNOS_BASICO else []) + [["alunos", "--modo", "completo", "--rapido"]]
    codigos = []
    for c in comandos:                                    # um depois do outro (os dois usam o login do SERE)
        codigos += _executar(ctx, "alunos", [c])
    rc = max(codigos)
    _marcar(ctx, "alunos", ok=rc == 0, codigos=codigos)
    return 0 if rc == 0 else 1


def etapa_planilha(ctx: Ctx) -> int:
    if _precisa_de_mudanca(ctx, "planilha") is None:
        return 0
    from src.comum.configuracao import planilha_google_id
    planilha = planilha_google_id()
    if not planilha:
        log.error("Nenhuma planilha configurada: informe o link em Automações → Google Sheets uma vez pela tela.")
        _marcar(ctx, "planilha", ok=False, erro="sem planilha configurada")
        return 1
    rc = _executar(ctx, "planilha", [["sheets", "--operacao", "atualizar", "--planilha", planilha, "--confirmo"]])[0]
    _marcar(ctx, "planilha", ok=rc == 0, codigo=rc)
    return 0 if rc == 0 else 1


def etapa_consultas(ctx: Ctx) -> int:
    codigos = _executar(ctx, "consultas", [["cep"], ["sus"]])          # em simultâneo
    _marcar(ctx, "consultas", ok=max(codigos) == 0, codigos=codigos)
    return 0 if max(codigos) == 0 else 1


def etapa_status(ctx: Ctx) -> int:
    ok, motivo = dia_letivo(ctx.hoje)
    print(f"{ctx.hoje:%d/%m/%Y} ({_DIAS[ctx.hoje.weekday()]}): {'DIA LETIVO' if ok else 'sem aula'} — {motivo}")
    if not ok:
        prox = proximo_dia_letivo(ctx.hoje)
        print("Próximo dia letivo:", f"{prox:%d/%m/%Y} ({_DIAS[prox.weekday()]})" if prox else
              f"nenhum nos próximos {DIAS_PARA_PROXIMO_LETIVO} dias (confira o Calendário letivo)")
    print(f"Ano letivo em uso: {paths.ano_atual()} · ano do calendário: {ctx.hoje.year}"
          + (" · AUTO_SERE_ANO_BASE fixa o ano" if os.getenv("AUTO_SERE_ANO_BASE") else ""))
    for nome, reg in _ler_json(_arquivo_estado()).items():
        print(f"  {nome:<10} {reg.get('data')} {reg.get('hora', '')}  "
              + ", ".join(f"{k}={v}" for k, v in reg.items() if k not in ("data", "hora", "novos", "transferidos", "retornaram")))
    return 0


_ETAPAS = {"virada": etapa_virada, "turmas": etapa_turmas, "alunos": etapa_alunos,
           "planilha": etapa_planilha, "consultas": etapa_consultas, "status": etapa_status}


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

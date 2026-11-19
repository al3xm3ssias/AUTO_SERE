"""
matriculas.py — ID único por MATRÍCULA (período em que o aluno ficou na escola)
==============================================================================
Arquivo: dados/<ano>/turmas_relacional.json  (a "ponte")

PROBLEMA
    O aluno entra, sai, volta e sai de novo. O CGM é da PESSOA; nada identifica
    cada PERÍODO. Além disso, a listagem do SERE tem UMA coluna de data: para
    quem está Matriculado ela é a data da matrícula; para quem está Transferido
    ela vira a data da SAÍDA. Ao ser transferido, a linha troca de
    (Matriculado, 05/02) para (Transferido, 31/03) e a data de entrada some do
    turmas.json — que é reescrito inteiro a cada coleta.

SOLUÇÃO
    Este arquivo só recebe dados (nunca é recriado) e lembra de cada período:

        id             "2026-0007" (ano + sequencial; nunca reaproveitado)
        cgm            liga os períodos do mesmo aluno
        data_matricula entrada (None quando só se conheceu a saída)
        data_saida     saída (None enquanto estiver matriculado)
        turma, chamada, situacao, retorno
        status         "ok" | "verificar" (+ motivos) — nada é decidido no escuro

REGRAS DE CASAMENTO (por CGM, em ordem de data)
    Linha Matriculado (data D):
        1. mesma data de matrícula               → mesmo período
        2. já há período em aberto na mesma turma/chamada → mesmo período, data
           mudou → "verificar"
        3. senão                                  → período novo (retorno, se já
           houve saída antes de D)
    Linha Transferido (data S = saída):
        1. mesma data de saída                    → mesmo período
        2. período em aberto com entrada <= S     → é a SAÍDA dele (fecha)
        3. período fechado, mesma turma/chamada, outra data de saída →
           correção no SERE → "verificar"
        4. senão                                  → período novo só com saída
           (a entrada não vem do SERE para transferidos)

    O nome NUNCA é usado para casar (nome errado/homônimo era a fragilidade).

SEGURANÇA
    - Gravação atômica + cópia .antes + trava entre processos.
    - Arquivo ilegível NÃO é tratado como vazio (isso regeneraria os IDs):
      levanta MatriculasCorrompidasError e não toca no arquivo.
    - O gancho da coleta nunca derruba a coleta (registrar_matriculas_sem_falhar).
    - Só grava quando algo mudou.

Funções puras (aplicar_coleta) não dependem de Playwright nem de credenciais.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional

from src.comum import paths
from src.comum.arquivos_json import (
    ArquivoJsonCorrompidoError,
    carregar_json,
    salvar_json_atomico,
)
from src.comum.logger import get_logger
from src.comum.registros_aluno import eh_matriculado, eh_transferido, parse_data

logger = get_logger(__name__)

ARQUIVO = "turmas_relacional.json"
VERSAO = 1

CAMPO_ID = "ID_MATRICULA"
CAMPO_ENTRADA = "Data Entrada"
CAMPO_SAIDA = "Data Transferência"


class MatriculasCorrompidasError(ArquivoJsonCorrompidoError):
    """turmas_relacional.json existe mas não pôde ser lido: nada foi alterado."""


# ───────────────────────────── arquivo, trava e ano ─────────────────────────────

def caminho(dados_dir) -> Path:
    return Path(dados_dir) / ARQUIVO


def _ano_de(dados_dir, ano=None) -> str:
    if ano:
        return str(ano)
    nome = Path(dados_dir).name
    return nome if paths.RE_ANO.match(nome) else paths.ano_atual()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _trava(dados_dir, espera: float = 15.0, obsoleta: float = 120.0) -> Iterator[None]:
    """Trava simples entre processos (arquivo .lock criado com O_EXCL). Lock antigo = processo morto."""
    pasta = Path(dados_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    lock = pasta / (ARQUIVO + ".lock")
    limite = time.monotonic() + espera
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > obsoleta:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.monotonic() > limite:
                raise TimeoutError(f"{lock} está travado por outro processo.")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _estado_vazio(ano: str) -> dict:
    return {"versao": VERSAO, "ano": ano, "proximo": 1, "atualizado_em": None, "matriculas": []}


def carregar(dados_dir, ano=None) -> dict:
    """Estado atual da ponte (ou um estado vazio se o arquivo ainda não existe)."""
    estado = carregar_json(caminho(dados_dir), dict, dict, erro=MatriculasCorrompidasError)
    if not estado:
        return _estado_vazio(_ano_de(dados_dir, ano))
    if not isinstance(estado.get("matriculas"), list) or not isinstance(estado.get("proximo"), int):
        raise MatriculasCorrompidasError(
            f"{caminho(dados_dir)} não tem a estrutura esperada. Arquivo não alterado."
        )
    return estado


def _salvar(dados_dir, estado: dict) -> None:
    alvo = caminho(dados_dir)
    if alvo.exists():
        shutil.copy2(alvo, alvo.with_name(alvo.name + ".antes"))
    estado["atualizado_em"] = _agora()
    salvar_json_atomico(alvo, estado)


# ─────────────────────────────── normalização ───────────────────────────────

def _num(valor) -> Optional[int]:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _linha(aluno: dict, turma: str) -> dict:
    situacao = str(aluno.get("Situação", "") or "").strip()
    data = str(aluno.get("Data Matricula", "") or "").strip()
    if eh_transferido(situacao):
        tipo = "saida"
    elif eh_matriculado(situacao):
        tipo = "entrada"
    else:
        tipo = "outra"
    return {
        "cgm": str(aluno.get("CGM", "") or "").strip(),
        "nome": str(aluno.get("Nome", "") or "").strip(),
        "nasc": str(aluno.get("Data Nasc.", "") or "").strip(),
        "turma": str(turma or "").strip(),
        "n": _num(aluno.get("N")),
        "situacao": situacao,
        "data": data,
        "d": parse_data(data),
        "tipo": tipo,
        "retorno": bool(aluno.get("Retorno")),
    }


def _mesmo_lugar(m: dict, l: dict) -> bool:
    return (bool(l["turma"]) and m.get("turma") == l["turma"]) or (
        l["n"] is not None and m.get("chamada") == l["n"]
    )


# ─────────────────────────────── regras (puras) ───────────────────────────────

def _tocar(m: dict, agora: str, **campos) -> bool:
    mudou = False
    for k, v in campos.items():
        if m.get(k) != v:
            m[k] = v
            mudou = True
    if mudou:
        m["atualizado_em"] = agora
    return mudou


def _verificar(m: dict, motivo: str, agora: str) -> bool:
    if m.get("status") == "verificar" and motivo in m.get("motivos", []):
        return False
    m["status"] = "verificar"
    m.setdefault("motivos", []).append(motivo)
    m["atualizado_em"] = agora
    return True


def _comuns(m: dict, l: dict, agora: str) -> bool:
    campos = {"nome": l["nome"], "data_nasc": l["nasc"], "turma": l["turma"], "chamada": l["n"]}
    return _tocar(m, agora, **{k: v for k, v in campos.items() if v not in ("", None)})


def _nova(estado: dict, idx: dict, l: dict, agora: str, *, data_matricula, data_saida, retorno) -> dict:
    m = {
        "id": f"{estado['ano']}-{estado['proximo']:04d}",
        "cgm": l["cgm"],
        "nome": l["nome"],
        "data_nasc": l["nasc"],
        "turma": l["turma"],
        "chamada": l["n"],
        "data_matricula": data_matricula,
        "data_saida": data_saida,
        "situacao": l["situacao"],
        "retorno": retorno,
        "status": "ok",
        "motivos": [],
        "criado_em": agora,
        "atualizado_em": agora,
    }
    estado["proximo"] += 1
    estado["matriculas"].append(m)
    idx[l["cgm"]].append(m)
    return m


def _aplicar_entrada(estado, idx, l, agora, r: Counter) -> None:
    ms = idx[l["cgm"]]
    exata = next((m for m in ms if m["data_matricula"] == l["data"]), None)
    if exata:
        if _comuns(exata, l, agora):
            r["atualizadas"] += 1
        if exata["data_saida"]:
            _tocar(exata, agora, data_saida=None, situacao=l["situacao"])
            _verificar(exata, "a saída deixou de constar no SERE (transferência desfeita?)", agora)
            r["reabertas"] += 1
        return

    abertas = [m for m in ms if m["data_saida"] is None]
    mesma = next((m for m in abertas if _mesmo_lugar(m, l)), None)
    if mesma:
        antiga = mesma["data_matricula"]
        _tocar(mesma, agora, data_matricula=l["data"], situacao=l["situacao"])
        _comuns(mesma, l, agora)
        _verificar(mesma, f"data da matrícula mudou de {antiga} para {l['data']}", agora)
        r["atualizadas"] += 1
        return

    retorno = l["retorno"] or any(
        m["data_saida"] and (parse_data(m["data_saida"]) or date.max) <= l["d"] for m in ms
    )
    nova = _nova(estado, idx, l, agora, data_matricula=l["data"], data_saida=None, retorno=retorno)
    r["novas"] += 1
    if abertas:
        _verificar(nova, f"já havia matrícula em aberto ({abertas[0]['id']}) em outra turma/chamada", agora)
        for m in abertas:
            _verificar(m, f"surgiu outra matrícula em aberto ({nova['id']})", agora)


def _aplicar_saida(estado, idx, l, agora, r: Counter) -> None:
    ms = idx[l["cgm"]]
    exata = next((m for m in ms if m["data_saida"] == l["data"]), None)
    if exata:
        if _comuns(exata, l, agora) | _tocar(exata, agora, situacao=l["situacao"]):
            r["atualizadas"] += 1
        return

    elegiveis = [
        m for m in ms
        if m["data_saida"] is None
        and (m["data_matricula"] is None or (parse_data(m["data_matricula"]) or date.max) <= l["d"])
    ]
    if elegiveis:
        elegiveis.sort(key=lambda m: (
            m.get("chamada") == l["n"],
            m.get("turma") == l["turma"],
            parse_data(m["data_matricula"] or "") or date.min,
        ), reverse=True)
        m = elegiveis[0]
        _tocar(m, agora, data_saida=l["data"], situacao=l["situacao"])
        _comuns(m, l, agora)
        r["saidas"] += 1
        return

    corrigivel = next(
        (m for m in ms if m["data_saida"] and m.get("turma") == l["turma"] and m.get("chamada") == l["n"]),
        None,
    )
    if corrigivel:
        antiga = corrigivel["data_saida"]
        _tocar(corrigivel, agora, data_saida=l["data"], situacao=l["situacao"])
        _verificar(corrigivel, f"data da saída mudou de {antiga} para {l['data']}", agora)
        r["atualizadas"] += 1
        return

    _nova(estado, idx, l, agora, data_matricula=None, data_saida=l["data"], retorno=bool(ms))
    r["novas"] += 1
    r["so_saida"] += 1


def _aplicar_outra(estado, idx, l, agora, r: Counter) -> None:
    ms = idx[l["cgm"]]
    existente = next((m for m in ms if m["situacao"] == l["situacao"] and m["data_matricula"] == l["data"]), None)
    if existente:
        if _comuns(existente, l, agora):
            r["atualizadas"] += 1
        return
    nova = _nova(estado, idx, l, agora, data_matricula=l["data"], data_saida=None, retorno=False)
    _verificar(nova, f"situação não prevista: {l['situacao'] or '(vazia)'}", agora)
    r["novas"] += 1


def aplicar_coleta(estado: dict, turmas: dict, agora: Optional[str] = None) -> dict:
    """Aplica uma coleta (o dict de turmas.json) sobre `estado`. Muda `estado` e devolve o resumo."""
    agora = agora or _agora()
    r: Counter = Counter()
    por_cgm: dict[str, list[dict]] = defaultdict(list)

    if isinstance(turmas, dict):
        for nome_turma, alunos in turmas.items():
            if not isinstance(alunos, list):
                continue
            for aluno in alunos:
                if not isinstance(aluno, dict):
                    continue
                l = _linha(aluno, nome_turma)
                r["linhas"] += 1
                if not l["cgm"]:
                    r["sem_cgm"] += 1
                elif l["d"] is None:
                    r["sem_data"] += 1
                else:
                    por_cgm[l["cgm"]].append(l)

    idx: dict[str, list[dict]] = defaultdict(list)
    for m in estado["matriculas"]:
        idx[m["cgm"]].append(m)

    antes_verificar = sum(1 for m in estado["matriculas"] if m.get("status") == "verificar")
    for cgm in sorted(por_cgm):
        linhas = sorted(por_cgm[cgm], key=lambda l: (l["d"], l["tipo"] != "entrada", l["n"] or 0))
        for l in linhas:
            if l["tipo"] == "entrada":
                _aplicar_entrada(estado, idx, l, agora, r)
            elif l["tipo"] == "saida":
                _aplicar_saida(estado, idx, l, agora, r)
            else:
                _aplicar_outra(estado, idx, l, agora, r)

    total_verificar = sum(1 for m in estado["matriculas"] if m.get("status") == "verificar")
    r["verificar"] = total_verificar
    r["verificar_novos"] = max(0, total_verificar - antes_verificar)
    r["total"] = len(estado["matriculas"])
    return dict(r)


# ─────────────────────────── consulta e enriquecimento ───────────────────────────

def listar(dados_dir) -> list[dict]:
    return list(carregar(dados_dir)["matriculas"])


def do_cgm(cgm, dados_dir) -> list[dict]:
    """Períodos do aluno, do mais antigo para o mais novo (pela data de saída/entrada conhecida)."""
    cgm = str(cgm).strip()
    itens = [m for m in listar(dados_dir) if m["cgm"] == cgm]
    return sorted(itens, key=lambda m: parse_data(m["data_matricula"] or m["data_saida"] or "") or date.min)


def _indice_linhas(estado: dict) -> dict:
    ind = {}
    for m in estado["matriculas"]:
        if m["data_matricula"]:
            ind[(m["cgm"], "entrada", m["data_matricula"])] = m
        if m["data_saida"]:
            ind[(m["cgm"], "saida", m["data_saida"])] = m
    return ind


def _matricula_da_linha(aluno: dict, ind: dict) -> Optional[dict]:
    cgm = str(aluno.get("CGM", "") or "").strip()
    data = str(aluno.get("Data Matricula", "") or "").strip()
    situacao = str(aluno.get("Situação", "") or "").strip()
    if eh_transferido(situacao):
        return ind.get((cgm, "saida", data))
    return ind.get((cgm, "entrada", data))


def id_da_linha(aluno: dict, dados_dir) -> str:
    """ID da matrícula a que uma linha do turmas.json pertence ('' se ainda não existir)."""
    m = _matricula_da_linha(aluno, _indice_linhas(carregar(dados_dir)))
    return m["id"] if m else ""


def enriquecer_com(estado: dict, turmas: dict) -> int:
    """
    Acrescenta a cada linha: ID_MATRICULA, Data Entrada, Data Transferência.
    NÃO altera "Data Matricula" (continua como o SERE entrega): vários módulos
    leem essa coluna como data da movimentação. Devolve quantas linhas receberam ID.
    """
    ind = _indice_linhas(estado)
    n = 0
    for alunos in turmas.values():
        if not isinstance(alunos, list):
            continue
        for aluno in alunos:
            if not isinstance(aluno, dict):
                continue
            m = _matricula_da_linha(aluno, ind)
            aluno[CAMPO_ID] = m["id"] if m else ""
            aluno[CAMPO_ENTRADA] = (m["data_matricula"] or "") if m else ""
            aluno[CAMPO_SAIDA] = (m["data_saida"] or "") if m else ""
            n += bool(m)
    return n


# ───────────────────────────── sincronização (com I/O) ─────────────────────────────

def _sincronizar(turmas: dict, dados_dir, ano=None) -> tuple[dict, dict]:
    with _trava(dados_dir):
        estado = carregar(dados_dir, ano)
        antes = json.dumps(estado["matriculas"], sort_keys=True, ensure_ascii=False)
        resumo = aplicar_coleta(estado, turmas)
        depois = json.dumps(estado["matriculas"], sort_keys=True, ensure_ascii=False)
        if antes != depois or not caminho(dados_dir).exists():
            _salvar(dados_dir, estado)
    return estado, resumo


def sincronizar(turmas: dict, dados_dir, ano=None) -> dict:
    """Aplica a coleta e grava a ponte (só se mudou). Devolve o resumo."""
    return _sincronizar(turmas, dados_dir, ano)[1]


def _texto_resumo(r: dict) -> str:
    partes = [f"{r.get('total', 0)} matrícula(s) no total"]
    for chave, rotulo in (("novas", "novas"), ("saidas", "saídas registradas"), ("reabertas", "reabertas"),
                          ("so_saida", "só com saída"), ("sem_cgm", "linhas sem CGM"), ("sem_data", "linhas sem data")):
        if r.get(chave):
            partes.append(f"{r[chave]} {rotulo}")
    if r.get("verificar"):
        partes.append(f"{r['verificar']} A CONFERIR")
    return "; ".join(partes)


def registrar_matriculas_sem_falhar(turmas: dict, dados_dir, ano=None, enriquecer: bool = True) -> Optional[dict]:
    """
    Gancho da coleta de turmas: atualiza a ponte e (opcional) acrescenta ID/datas às linhas de `turmas`.
    NUNCA levanta exceção: a coleta do SERE não pode falhar por causa disto.
    """
    try:
        estado, resumo = _sincronizar(turmas, dados_dir, ano)
        if enriquecer:
            resumo["com_id"] = enriquecer_com(estado, turmas)
        logger.info("Matrículas (ponte): %s", _texto_resumo(resumo))
        if resumo.get("verificar"):
            logger.warning(
                "Matrículas a conferir: %s. Veja %s (status=verificar).", resumo["verificar"], caminho(dados_dir).name
            )
        return resumo
    except MatriculasCorrompidasError as e:
        logger.error("Ponte de matrículas ilegível, nada foi alterado: %s", e)
    except Exception as e:  # noqa: BLE001 — não derruba a coleta
        logger.error("Falha ao atualizar a ponte de matrículas (a coleta seguiu normalmente): %s", e)
    return None


# ─────────────────────────────── conferência manual ───────────────────────────────

def a_conferir(dados_dir) -> list[dict]:
    return [m for m in listar(dados_dir) if m.get("status") == "verificar"]


def conferir(dados_dir, id_matricula: str, nota: str = "") -> bool:
    """Marca como conferido (status ok), guardando os motivos e a nota. False se o ID não existe."""
    with _trava(dados_dir):
        estado = carregar(dados_dir)
        for m in estado["matriculas"]:
            if m["id"] == id_matricula:
                m.setdefault("conferido", []).append(
                    {"em": _agora(), "nota": nota, "motivos": list(m.get("motivos", []))}
                )
                m["status"], m["motivos"], m["atualizado_em"] = "ok", [], _agora()
                _salvar(dados_dir, estado)
                return True
    return False


# ─────────────────────────────── semear pelos backups ───────────────────────────────

def semear_de_backups(dados_dir, ano=None) -> dict:
    """
    Reaplica, do mais antigo ao mais novo, os turmas.json guardados nos backups do ano. Recupera datas de
    entrada de quem já foi transferido (o backup ainda o viu como Matriculado). Só com a ponte VAZIA
    (antes da primeira coleta); depois disso recusa, sem alterar nada.
    """
    from src.comum import backup

    ano = _ano_de(dados_dir, ano)
    resumo: dict = {"backups": 0, "aplicados": 0}
    if carregar(dados_dir, ano)["matriculas"]:
        # Reaplicar dados ANTIGOS sobre uma ponte que já tem "só saída" duplicaria o período (a entrada
        # recuperada viraria uma matrícula em aberto à parte). Semear só vale com a ponte ainda vazia.
        resumo["erro"] = ("A ponte já tem matrículas; semear só pode ser feito ANTES da primeira coleta. "
                          "Nada foi alterado.")
        return resumo
    for item in reversed(backup.listar_backups()):          # listar_backups vem do mais novo ao mais antigo
        if item.get("ano") != ano:
            continue
        resumo["backups"] += 1
        try:
            with zipfile.ZipFile(item["caminho"]) as z:
                turmas = json.loads(z.read("dados_ano/turmas.json").decode("utf-8"))
        except (KeyError, ValueError, zipfile.BadZipFile, OSError):
            continue
        if isinstance(turmas, dict):
            sincronizar(turmas, dados_dir, ano)
            resumo["aplicados"] += 1
    return resumo


# ─────────────────────────────────────── CLI ───────────────────────────────────────

def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ponte de IDs de matrícula (turmas_relacional.json).")
    ap.add_argument("--ano", help="ano letivo (padrão: o ano em uso)")
    ap.add_argument("--semear", action="store_true", help="reaplica os turmas.json dos backups do ano; só ANTES da primeira coleta (ponte vazia)")
    ap.add_argument("--verificar", action="store_true", help="lista só as matrículas a conferir")
    ap.add_argument("--conferido", metavar="ID", help="marca uma matrícula como conferida")
    ap.add_argument("--nota", default="", help="nota ao marcar como conferida")
    args = ap.parse_args(argv)

    ano = args.ano or paths.ano_atual()
    dados_dir = paths.DADOS_DIR / ano

    if args.conferido:
        ok = conferir(dados_dir, args.conferido, args.nota)
        print("Conferido." if ok else f"ID {args.conferido} não encontrado.")
        return 0 if ok else 1

    if not args.verificar:
        if args.semear:
            print("Semeando a partir dos backups:", semear_de_backups(dados_dir, ano))
        turmas_json = dados_dir / "turmas.json"
        turmas = carregar_json(turmas_json, dict, dict)
        print("Resumo:", _texto_resumo(sincronizar(turmas, dados_dir, ano)))

    for m in a_conferir(dados_dir):
        print(f"  {m['id']}  CGM {m['cgm']}  {m['nome']}  [{m['data_matricula']} → {m['data_saida']}]")
        for motivo in m.get("motivos", []):
            print(f"      - {motivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

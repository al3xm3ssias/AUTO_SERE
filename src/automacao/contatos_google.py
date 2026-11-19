"""
contatos_google.py — contatos da pré-matrícula direto no Google Contatos
========================================================================
Substitui a importação manual do CSV: cada responsável vira UM contato (o mesmo agrupamento e o mesmo nome do CSV),
criado na primeira vez e ATUALIZADO nas seguintes (nunca duplicado, nunca apagado).

Rótulos (grupos de contatos) por alvo:
  • alvo "atual"   → o ano letivo vigente, ex.: "2026"
  • alvo "proximo" → DOIS rótulos: "Pré-matrícula 2027" e "Aluno 2027"

Como não duplica: o arquivo dados/google_contatos.json guarda, para cada contato enviado, o resourceName do Google, o
resumo (hash) do que foi enviado e a identificação (CPFs, só como hash) dos alunos dele. Na rodada seguinte:
  • mesmo contato (mesma chave de agrupamento, ou algum aluno em comum) e nada mudou → ignora;
  • mudou (telefone corrigido, irmão novo, endereço) → atualiza só os campos preenchidos;
  • foi apagado no Google → cria de novo;
  • sumiu dos dados (aluno cancelado) → NÃO é removido do Google; só é contado como "fora desta rodada".
O arquivo é regravado a cada lote criado: uma queda no meio não deixa contatos sem registro (que virariam duplicados).

Simulação: não autentica nem fala com o Google; compara com o arquivo e mostra o que seria criado/atualizado.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from src.comum import google_contacts as gc
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json, salvar_json_atomico

ROTULO_PRE_MATRICULA = "Pré-matrícula"
ROTULO_ALUNO = "Aluno"
ALVO_PROXIMO = "proximo"
VERSAO_MAPA = 1


class MapaContatosCorrompidoError(ArquivoJsonCorrompidoError):
    """google_contatos.json existe mas não pôde ser lido. O arquivo NÃO é tocado."""


# ───────────────────────────── regras da escola ────────────────────────────────

def rotulos_do_alvo(alvo: str, ano) -> list[str]:
    """Ano vigente → ["2026"]; só o próximo ano → ["Pré-matrícula 2027", "Aluno 2027"]."""
    ano = str(ano)
    if alvo == ALVO_PROXIMO:
        return [f"{ROTULO_PRE_MATRICULA} {ano}", f"{ROTULO_ALUNO} {ano}"]
    return [ano]


def pessoa_do_contato(contato: dict) -> dict:
    """Mesmos campos do CSV: nome, e-mail, telefone, CEP, responsável (relação) e "Endereço Completo"."""
    return gc.montar_pessoa(nome=contato["nome"], email=contato.get("email", ""), telefone=contato.get("telefone", ""),
                            cep=contato.get("cep", ""), relacao=contato.get("responsavel", ""),
                            extras={"Endereço Completo": contato.get("endereco", "")})


# ───────────────────────────── mapa dos contatos já enviados ───────────────────

def _id_cpf(cpf) -> str:
    digitos = re.sub(r"\D", "", str(cpf or ""))
    return hashlib.sha256(digitos.encode("utf-8")).hexdigest()[:16] if digitos else ""


def _resumo(pessoa: dict) -> str:
    return hashlib.sha256(json.dumps(pessoa, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _carregar_mapa(caminho: Path) -> dict:
    mapa = carregar_json(caminho, lambda: {"versao": VERSAO_MAPA, "contatos": []}, dict, MapaContatosCorrompidoError)
    if not isinstance(mapa.get("contatos"), list):
        raise MapaContatosCorrompidoError(f"{caminho} não tem o formato esperado (campo \"contatos\"). Arquivo não alterado.")
    return mapa


def _salvar_mapa(caminho: Path, mapa: dict) -> None:
    mapa["versao"] = VERSAO_MAPA
    salvar_json_atomico(caminho, mapa)


def _casar(contatos: list[dict], entradas: list[dict], ano: str) -> list[dict | None]:
    """Para cada contato, a entrada do mapa que é o MESMO contato (ou None). Cada entrada casa uma vez só.
    Casa pela chave de agrupamento; senão por algum aluno em comum (telefone corrigido não cria contato novo)."""
    do_ano = [e for e in entradas if str(e.get("ano")) == ano and e.get("resource_name")]
    por_chave = {e.get("chave"): e for e in do_ano if e.get("chave")}
    por_aluno: dict[str, dict] = {}
    for e in do_ano:
        for h in e.get("alunos", []):
            por_aluno.setdefault(h, e)
    usadas: set[int] = set()
    achadas: list[dict | None] = []
    for c in contatos:
        candidatas = [por_chave.get(c["chave"])] + [por_aluno.get(_id_cpf(cpf)) for cpf in c.get("cpfs", [])]
        escolhida = next((e for e in candidatas if e is not None and id(e) not in usadas), None)
        if escolhida is not None:
            usadas.add(id(escolhida))
        achadas.append(escolhida)
    return achadas


# ───────────────────────────── sincronização ───────────────────────────────────

def sincronizar(contatos: list[dict], *, alvo: str, ano, caminho_mapa, simulacao: bool = False, servico=None,
                interativo: bool = True, pausa: float = gc.PAUSA_ENTRE_LOTES_S, imprimir=print) -> dict:
    """
    `contatos`: [{"chave", "cpfs", "nome", "email", "telefone", "cep", "responsavel", "endereco"}] (vem de
    pre_matricula.contatos_para_google). Devolve {"simulacao", "rotulos", "total", "criados", "atualizados", "iguais",
    "rotulados", "erros", "fora_da_rodada"}. Erros do Google (GoogleErro) sobem para quem chamou.
    """
    ano = str(ano)
    caminho_mapa = Path(caminho_mapa)
    rotulos = rotulos_do_alvo(alvo, ano)
    mapa = _carregar_mapa(caminho_mapa)
    entradas = mapa["contatos"]

    pessoas = [pessoa_do_contato(c) for c in contatos]
    resumos = [_resumo(p) for p in pessoas]
    casadas = _casar(contatos, entradas, ano)

    a_criar = [i for i, e in enumerate(casadas) if e is None]
    a_atualizar = [i for i, e in enumerate(casadas) if e is not None and e.get("hash") != resumos[i]]
    iguais = [i for i, e in enumerate(casadas) if e is not None and e.get("hash") == resumos[i]]
    fora = len([e for e in entradas if str(e.get("ano")) == ano and e.get("resource_name")]) - len([e for e in casadas if e])

    resultado = {"simulacao": simulacao, "rotulos": rotulos, "total": len(contatos), "criados": 0, "atualizados": 0,
                 "iguais": len(iguais), "rotulados": 0, "erros": [], "fora_da_rodada": max(fora, 0)}

    imprimir(f"Rótulos: {', '.join(rotulos)}")
    if simulacao:
        resultado.update(criados=len(a_criar), atualizados=len(a_atualizar))
        imprimir(f"SIMULAÇÃO (nada é enviado ao Google): criaria {len(a_criar)}, atualizaria {len(a_atualizar)}, "
                 f"já em dia {len(iguais)} de {len(contatos)} contato(s).")
        for i in (a_criar + a_atualizar)[:5]:
            imprimir(f"   • {'novo      ' if casadas[i] is None else 'atualizar '}{contatos[i]['nome']}")
        if len(a_criar) + len(a_atualizar) > 5:
            imprimir(f"   … e mais {len(a_criar) + len(a_atualizar) - 5}")
        imprimir("   (a simulação não confere se algum contato foi apagado no Google; isso só é visto na rodada real)")
        return resultado

    api = servico if servico is not None else gc.abrir_servico(interativo=interativo)
    rn_rotulos = gc.garantir_rotulos(api, rotulos)
    agora = lambda: datetime.now().isoformat(timespec="seconds")                      # noqa: E731

    def _entrada(i: int, rn: str) -> dict:
        c = contatos[i]
        return {"chave": c["chave"], "alunos": sorted({h for h in map(_id_cpf, c.get("cpfs", [])) if h}), "ano": ano,
                "resource_name": rn, "hash": resumos[i], "rotulos": list(rotulos), "atualizado_em": agora()}

    # 1) atualizar quem já existe (e recriar quem foi apagado no Google)
    if a_atualizar or iguais:
        existentes = [casadas[i]["resource_name"] for i in a_atualizar + iguais]
        etags = gc.buscar_etags(api, existentes)
        apagados = [i for i in a_atualizar + iguais if casadas[i]["resource_name"] not in etags]
        for i in apagados:
            entradas.remove(casadas[i])
            casadas[i] = None
            a_criar.append(i)
            (a_atualizar if i in a_atualizar else iguais).remove(i)
        resultado["iguais"] = len(iguais)
        if apagados:
            imprimir(f"   {len(apagados)} contato(s) apagado(s) no Google serão criados de novo.")

        itens = [(casadas[i]["resource_name"], etags[casadas[i]["resource_name"]], pessoas[i]) for i in a_atualizar]
        retorno = gc.atualizar_contatos(api, itens, pausa=pausa) if itens else {}
        for i in a_atualizar:
            rn = casadas[i]["resource_name"]
            if retorno.get(rn):
                resultado["erros"].append(f"{contatos[i]['nome']}: {retorno[rn]}")
                continue
            casadas[i].update(_entrada(i, rn), rotulos=casadas[i].get("rotulos", []))
            resultado["atualizados"] += 1

        # rótulos que o contato ainda não tem (ex.: era "Pré-matrícula 2027"/"Aluno 2027" e virou aluno do ano vigente)
        for nome in rotulos:
            faltam = [casadas[i]["resource_name"] for i in a_atualizar + iguais
                      if casadas[i] and nome not in casadas[i].get("rotulos", []) and casadas[i]["resource_name"] in etags]
            if faltam:
                gc.adicionar_aos_rotulos(api, rn_rotulos[nome], faltam)
                for i in a_atualizar + iguais:
                    if casadas[i] and casadas[i]["resource_name"] in faltam:
                        casadas[i].setdefault("rotulos", []).append(nome)
                resultado["rotulados"] += len(faltam)
        _salvar_mapa(caminho_mapa, mapa)

    # 2) criar os novos, gravando o mapa a cada lote
    if a_criar:
        ordem = sorted(a_criar)

        def _gravar_lote(inicio: int, parcial: list[dict]) -> None:
            for k, r in enumerate(parcial):
                i = ordem[inicio + k]
                if r["erro"]:
                    resultado["erros"].append(f"{contatos[i]['nome']}: {r['erro']}")
                    continue
                entradas.append(_entrada(i, r["resource_name"]))
                resultado["criados"] += 1
            _salvar_mapa(caminho_mapa, mapa)

        gc.criar_contatos(api, [pessoas[i] for i in ordem], list(rn_rotulos.values()), pausa=pausa,
                          ao_fim_de_cada_lote=_gravar_lote)

    imprimir(f"✅ Google Contatos: {resultado['criados']} criado(s), {resultado['atualizados']} atualizado(s), "
             f"{resultado['iguais']} já em dia"
             + (f", {resultado['rotulados']} rotulado(s)" if resultado["rotulados"] else "")
             + (f", {len(resultado['erros'])} com erro" if resultado["erros"] else "") + ".")
    if resultado["fora_da_rodada"]:
        imprimir(f"   {resultado['fora_da_rodada']} contato(s) enviado(s) antes não estão nesta rodada (não foram removidos do Google).")
    for erro in resultado["erros"][:5]:
        imprimir(f"   ⚠️ {erro}")
    return resultado

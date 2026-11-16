"""
ajuda.py — monta a ajuda (tecla F1) que a interface mostra
===========================================================
Junta os textos escritos à mão (ajuda_conteudo.py e ajuda_automacoes.py) com o que o sistema já sabe sobre cada
automação (src/comum/registro_scripts.py e configuracoes_scripts.py): campos da tela, modo de teste, confirmação e
configurações usadas. Assim os campos da ajuda nunca ficam diferentes dos da tela.

Todo resultado tem o mesmo formato, que o JavaScript desenha sem precisar saber de que tela veio:

    {"tipo", "chave", "titulo", "icone", "resumo", "secoes": [ {"titulo", "tipo", "itens"} ... ]}

    tipo da seção: "texto" (parágrafos) | "passos" (lista numerada) | "lista" (marcadores)
                   "elementos" (nome + texto + seletor opcional) | "links" (outras ajudas)

Sem Flask e sem rede: só leitura de dados em memória.
"""
from __future__ import annotations

from typing import Optional

from src.comum import registro_scripts as _registro
from src.comum.ajuda_automacoes import (AUTOMACOES, COMO_EXECUTAR, COMPONENTES, GRUPOS, SECOES_DA_TELA)
from src.comum.ajuda_conteudo import ABAS, CONFIGURACOES, GERAL, MODAIS, TELAS, E, R
from src.comum.configuracoes_scripts import CATALOGO

TIPOS = ("tela", "aba", "configuracao", "modal", "automacao")
_OPCOES_MAX = 8      # selects maiores que isso (lista de tipos de documento, por exemplo) não listam as opções


def _sec(titulo: str, tipo: str, itens: list) -> Optional[dict]:
    return {"titulo": titulo, "tipo": tipo, "itens": itens} if itens else None


def _catalogo() -> dict[str, dict]:
    """chave → {nome, descricao} das automações (a mesma lista que a tela Automações mostra)."""
    from src.web.api.rotas import AUTOMACOES_DISPONIVEIS     # import tardio: evita Flask ao carregar este módulo
    return {a["chave"]: a for a in AUTOMACOES_DISPONIVEIS}


# ───────────────────────────── automações ─────────────────────────────

def _campo_extra(c: dict) -> dict:
    """Um campo próprio do script (extras do registro) como item de ajuda."""
    partes = []
    if c.get("descricao"):
        partes.append(str(c["descricao"]))
    opcoes = c.get("opcoes") or []
    if c.get("tipo") == "select" and opcoes and len(opcoes) <= _OPCOES_MAX:
        linhas = []
        for o in opcoes:
            texto = str(o.get("texto", "")).strip()
            ajuda = str(o.get("ajuda", "")).strip()
            if texto:
                linhas.append(f"• **{texto}**" + (f": {ajuda}" if ajuda else ""))
        if linhas:
            partes.append("Opções:\n" + "\n".join(linhas))
    elif c.get("tipo") == "select" and len(opcoes) > _OPCOES_MAX:
        partes.append(f"Escolha numa lista de {len(opcoes)} opções (a mesma do SERE).")
    if c.get("tipo") == "pasta":
        partes.append("Clique em **Escolher pasta** para abrir a janela do Windows e selecionar.")
    if c.get("padrao") not in (None, "", False):
        partes.append("Já vem marcado." if c["padrao"] is True else f"Valor inicial: `{c['padrao']}`.")
    if c.get("visivelSe"):
        partes.append("Este campo só aparece quando você escolhe a opção que o libera, em outro campo acima.")
    item = E(str(c.get("label") or c.get("nome") or "Campo"), "\n".join(partes) or "Preencha conforme a necessidade.")
    if c.get("id"):
        item["sel"] = "#" + str(c["id"])
    return item


def _campos_da_automacao(chave: str) -> tuple[list[dict], list[dict], list[dict]]:
    """(campos da tela, configurações usadas, avisos de confirmação) lidos do registro de scripts."""
    script = _registro.obter(chave)
    if script is None:
        return [], [], []
    recursos = set(script.recursos)
    campos: list[dict] = []

    def comp(nome_chave: str) -> dict:
        rotulo, texto, sel = COMPONENTES[nome_chave]
        if nome_chave == "teste":
            texto = script.ajuda_teste
        elif nome_chave == "debug":
            texto = script.ajuda_debug or "Salva capturas de tela para análise de falhas."
        return E(rotulo, texto, sel)

    if "turma" in recursos:
        campos.append(comp("turma"))
    if "situacao" in recursos:
        campos.append(comp("situacao"))
    if "cgm" in recursos:
        campos.append(comp("cgm_obrigatorio" if script.cgm_obrigatorio else "cgm_opcional"))
    if "erros" in recursos:
        campos.append(comp("erros"))
    try:
        extras = script.extras()
    except Exception:           # extra que lê arquivo ausente: a ajuda não pode quebrar por isso
        extras = []
    campos.extend(_campo_extra(c) for c in extras)
    if "debug" in recursos:
        campos.append(comp("debug"))
    if "teste" in recursos:
        campos.append(comp("teste"))

    configs = []
    for cid in (script.configs or ()):
        item = CATALOGO.get(cid)
        if item:
            tela = item.tela if item.tela in CONFIGURACOES else None
            configs.append({"rotulo": item.rotulo, "descricao": item.descricao, "tela": tela})
    avisos = []
    if script.confirmar:
        avisos.append(E("Confirmação antes de executar",
                        (script.aviso_confirmacao or "Esta automação altera dados.")
                        + " Uma janela mostra este aviso e a prévia; só começa depois de **Confirmar e executar**."
                        + (" Com **Modo de teste** marcado a confirmação é dispensada." if "teste" in recursos else "")))
    return campos, configs, avisos


def ajuda_automacao(chave: str) -> Optional[dict]:
    texto = AUTOMACOES.get(chave)
    cat = _catalogo().get(chave)
    if texto is None or cat is None:
        return None
    campos, configs, avisos = _campos_da_automacao(chave)
    secoes = [
        _sec("Quando usar", "texto", [texto["quando"]] if texto.get("quando") else []),
        _sec("Antes de executar", "lista", texto.get("antes", [])),
        _sec("Como executar", "passos", COMO_EXECUTAR),
        _sec("Campos desta tela", "elementos", campos or [
            E("Sem campos", "Esta automação não pede nada: é só clicar em **Executar tarefa**.", "#btn-executar-tarefa")]),
        _sec("Confirmação", "elementos", avisos),
        _sec("O que ela faz e grava", "lista", texto.get("resultado", [])),
        _sec("Cuidados", "lista", texto.get("cuidados", [])),
        _sec("O que o sistema guarda e esta automação usa", "elementos",
             [E(c["rotulo"], c["descricao"] + (" Para mudar: Configurações." if c["tela"] else "")) for c in configs]),
        _sec("Partes da tela de execução", "elementos", [E(n, t, s) for n, t, s in SECOES_DA_TELA]),
    ]
    return {
        "tipo": "automacao", "chave": chave, "titulo": cat["nome"], "icone": "bolt",
        "resumo": texto["resumo"],
        "secoes": [s for s in secoes if s] + _links(texto.get("veja_tambem", [])
                                                     + [R("configuracao", c["tela"]) for c in configs if c["tela"]]),
    }


# ───────────────────────────── telas, abas, painéis e janelas ─────────────────────────────

def _de_entrada(tipo: str, chave: str, e: dict) -> dict:
    secoes = [
        _sec("De onde vêm os dados" if tipo != "configuracao" else "Observação", "texto", [e["dados"]] if e.get("dados") else []),
        _sec("Passo a passo", "passos", e.get("passos", [])),
        _sec("Elementos da tela" if tipo in ("tela", "aba") else "Elementos", "elementos", e.get("elementos", [])),
        _sec("Dicas", "lista", e.get("dicas", [])),
        _sec("Cuidados", "lista", e.get("cuidados", [])),
    ]
    return {"tipo": tipo, "chave": chave, "titulo": e["titulo"], "icone": e.get("icone", "help"), "resumo": e["resumo"],
            "secoes": [s for s in secoes if s] + _links(e.get("veja_tambem", []))}


def _links(refs: list[dict]) -> list[dict]:
    itens, vistos = [], set()
    for r in refs:
        chave = (r["tipo"], r["chave"])
        if chave in vistos:
            continue
        vistos.add(chave)
        titulo = _titulo(r["tipo"], r["chave"])
        if titulo:
            itens.append({"tipo": r["tipo"], "chave": r["chave"], "rotulo": r.get("rotulo") or titulo})
    return [{"titulo": "Veja também", "tipo": "links", "itens": itens}] if itens else []


def _titulo(tipo: str, chave: str) -> str:
    if tipo == "automacao":
        return (_catalogo().get(chave) or {}).get("nome", "") if chave in AUTOMACOES else ""
    base = {"tela": TELAS, "aba": ABAS, "configuracao": CONFIGURACOES, "modal": MODAIS}.get(tipo, {})
    return base.get(chave, {}).get("titulo", "")


def obter(tipo: str, chave: str) -> Optional[dict]:
    """A ajuda de uma tela/aba/painel/janela/automação, ou None se não existe."""
    if tipo == "automacao":
        return ajuda_automacao(chave)
    base = {"tela": TELAS, "aba": ABAS, "configuracao": CONFIGURACOES, "modal": MODAIS}.get(tipo)
    if base is None or chave not in base:
        return None
    return _de_entrada(tipo, chave, base[chave])


def geral() -> dict:
    """O que existe em todas as telas (menu, barra do alto, selo do ano...)."""
    return _de_entrada("geral", "geral", GERAL)


def _texto_plano(a: dict) -> str:
    """Todo o texto de uma ajuda, em minúsculas, para a busca da Central de ajuda."""
    partes = [a["titulo"], a["resumo"]]
    for s in a["secoes"]:
        for i in s["itens"]:
            partes.append(" ".join(str(v) for v in i.values()) if isinstance(i, dict) else str(i))
    return " ".join(partes).lower()


def indice() -> dict:
    """Tudo que a Central de ajuda lista: telas, automações por grupo e painéis de Configurações."""
    def item(tipo, chave):
        a = obter(tipo, chave)
        return {"tipo": tipo, "chave": chave, "titulo": a["titulo"], "resumo": a["resumo"], "busca": _texto_plano(a)}

    grupos = []
    for gchave, rotulo in GRUPOS:
        chaves = [k for k, v in AUTOMACOES.items() if v["grupo"] == gchave and _catalogo().get(k)]
        if chaves:
            grupos.append({"grupo": gchave, "rotulo": rotulo, "itens": [item("automacao", k) for k in chaves]})
    return {
        "telas": [item("tela", k) for k in TELAS],
        "automacoes": grupos,
        "configuracoes": [item("configuracao", k) for k in CONFIGURACOES],
    }

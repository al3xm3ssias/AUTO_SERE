"""
Ajuda (tecla F1) — API do Auto SERE
====================================
Só leitura: entrega os textos montados por src/comum/ajuda.py para o painel de ajuda (static/js/ajuda.js).

    GET /web/api/ajuda/indice                  tudo que a Central de ajuda lista (telas, automações por grupo, painéis)
    GET /web/api/ajuda/geral                   o que existe em todas as telas (menu, barra do alto...)
    GET /web/api/ajuda/<tipo>/<chave>          tipo = tela | aba | configuracao | modal | automacao;  404 se não existe

Por serem GET, funcionam também no modo somente consulta.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from src.comum import ajuda as _ajuda
from src.seguranca import politica as _politica
from src.seguranca.web import perfil_atual as _perfil_atual

ajuda_bp = Blueprint("ajuda", __name__)


def _liberado(tipo: str, chave: str) -> bool:
    """A Pedagoga só vê a ajuda do que ela usa (telas, automações e configurações dela). Os demais perfis veem tudo."""
    perfil = _perfil_atual()
    if perfil != _politica.PEDAGOGA:
        return True
    if tipo == "tela":
        return _politica.pode_ver_tela(perfil, chave)
    if tipo == "automacao":
        return _politica.automacao_permitida(perfil, chave)
    if tipo == "configuracao":
        return _politica.pode_ver_configuracao(perfil, chave)
    return False                                  # abas e janelas pertencem a telas que ela não tem


@ajuda_bp.route("/indice")
def indice():
    dados = _ajuda.indice()
    if _perfil_atual() == _politica.PEDAGOGA:
        dados["telas"] = [i for i in dados.get("telas", []) if _liberado("tela", i["chave"])]
        grupos = []
        for g in dados.get("automacoes", []):
            itens = [i for i in g["itens"] if _liberado("automacao", i["chave"])]
            if itens:
                grupos.append(dict(g, itens=itens))
        dados["automacoes"] = grupos
        dados["configuracoes"] = [i for i in dados.get("configuracoes", []) if _liberado("configuracao", i["chave"])]
        for outra in set(dados) - {"telas", "automacoes", "configuracoes"}:
            dados[outra] = []
    return jsonify(dados)


@ajuda_bp.route("/geral")
def geral():
    return jsonify(_ajuda.geral())


@ajuda_bp.route("/<string:tipo>/<string:chave>")
def obter(tipo: str, chave: str):
    resultado = _ajuda.obter(tipo, chave) if tipo in _ajuda.TIPOS and _liberado(tipo, chave) else None
    if resultado is None:
        return jsonify({"erro": "Ainda não há ajuda para esta tela."}), 404
    return jsonify(resultado)

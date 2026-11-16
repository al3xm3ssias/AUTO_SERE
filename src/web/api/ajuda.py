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

ajuda_bp = Blueprint("ajuda", __name__)


@ajuda_bp.route("/indice")
def indice():
    return jsonify(_ajuda.indice())


@ajuda_bp.route("/geral")
def geral():
    return jsonify(_ajuda.geral())


@ajuda_bp.route("/<string:tipo>/<string:chave>")
def obter(tipo: str, chave: str):
    resultado = _ajuda.obter(tipo, chave) if tipo in _ajuda.TIPOS else None
    if resultado is None:
        return jsonify({"erro": "Ainda não há ajuda para esta tela."}), 404
    return jsonify(resultado)

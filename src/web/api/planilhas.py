"""
Planilhas do Google Drive — API do Auto SERE
=============================================
Cadastro dos links das planilhas (pareceres do Infantil, turmas, ...). As regras e o armazenamento ficam em
src/comum/planilhas_registro.py (dados/planilhas/planilhas.json); aqui só se traduz HTTP ⇄ cadastro.

Rotas (registradas em src/web/app.py com url_prefix="/web/api/planilhas"):

    GET    /web/api/planilhas              lista: ?q= &status=ativa|inativa &categoria= &ordem= &dir=asc|desc &limite= &inicio=
    POST   /web/api/planilhas              cadastra   {"nome", "link", "categoria", "observacao", "status"}
    GET    /web/api/planilhas/<id>         um registro
    PUT    /web/api/planilhas/<id>         altera os campos enviados
    DELETE /web/api/planilhas/<id>         remove do cadastro (a planilha no Google não é apagada)
    GET    /web/api/planilhas/categorias   categorias em uso e sugeridas

Erros: 400 dado inválido · 404 id inexistente · 409 planilha já cadastrada · 500 arquivo do cadastro ilegível.
"""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, request

from src.comum import planilhas_registro as _pr
from src.comum.arquivos_json import ArquivoJsonCorrompidoError

planilhas_bp = Blueprint("planilhas", __name__)


def _tratar_erros(funcao):
    @wraps(funcao)
    def interna(*args, **kwargs):
        try:
            return funcao(*args, **kwargs)
        except _pr.PlanilhaDuplicada as exc:                    # antes de ValueError: é uma subclasse
            return jsonify({"erro": str(exc)}), 409
        except _pr.PlanilhaNaoEncontrada as exc:
            return jsonify({"erro": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        except ArquivoJsonCorrompidoError as exc:
            return jsonify({"erro": str(exc)}), 500
    return interna


def _corpo() -> dict:
    corpo = request.get_json(silent=True)
    return corpo if isinstance(corpo, dict) else {}


@planilhas_bp.route("", methods=["GET"])
@_tratar_erros
def listar():
    a = request.args
    dados = _pr.listar(q=a.get("q", ""), status=a.get("status", ""), categoria=a.get("categoria", ""),
                       ordem=a.get("ordem", "id"), direcao=a.get("dir", "asc"),
                       limite=a.get("limite", _pr.LIMITE_PAGINA_PADRAO), inicio=a.get("inicio", 0))
    dados["resumo"] = _pr.resumo()
    return jsonify(dados)


@planilhas_bp.route("/categorias", methods=["GET"])
@_tratar_erros
def categorias():
    return jsonify(_pr.categorias())


@planilhas_bp.route("", methods=["POST"])
@_tratar_erros
def criar():
    c = _corpo()
    item = _pr.criar(c.get("nome"), c.get("link"), c.get("categoria", ""), c.get("observacao", ""), c.get("status", "ativa"))
    return jsonify({"status": "ok", "mensagem": f"Planilha cadastrada (id {item['id']}).", "item": item}), 201


@planilhas_bp.route("/<int:id_item>", methods=["GET"])
@_tratar_erros
def obter(id_item):
    return jsonify(_pr.obter(id_item))


@planilhas_bp.route("/<int:id_item>", methods=["PUT"])
@_tratar_erros
def atualizar(id_item):
    campos = {k: v for k, v in _corpo().items() if k in _pr.CAMPOS_EDITAVEIS}
    item = _pr.atualizar(id_item, **campos)
    return jsonify({"status": "ok", "mensagem": "Planilha atualizada.", "item": item})


@planilhas_bp.route("/<int:id_item>", methods=["DELETE"])
@_tratar_erros
def remover(id_item):
    item = _pr.remover(id_item)
    return jsonify({"status": "ok", "mensagem": f"'{item['nome']}' removida do cadastro.", "item": item})

"""
Planilhas do Google Drive — API do Auto SERE
=============================================
Gerenciador centralizado de planilhas (Google Sheets, Excel .xlsx, LibreOffice .ods). As regras e o armazenamento ficam
em src/comum/planilhas_registro.py (dados/planilhas/planilhas.json), a localização/criação em
src/comum/planilhas_gerenciador.py; aqui só se traduz HTTP ⇄ gerenciador.

Rotas (registradas em src/web/app.py com url_prefix="/web/api/planilhas"):

    GET    /web/api/planilhas              lista: ?q= &status=ativa|inativa &categoria= &finalidade= &ordem= &dir=asc|desc &limite= &inicio=
    POST   /web/api/planilhas              cadastra   {"nome", "plataforma", "link"|"caminho", "categoria", "observacao", "status", "finalidade", "turma"}
    POST   /web/api/planilhas/<id>/ativar  torna esta a planilha vigente do seu uso (a anterior fica inativa)
    POST   /web/api/planilhas/criar-de-modelo   {"modelo", "plataforma", "nome", "turma", "turmas", "tornar_vigente"}: cria e cadastra
    GET    /web/api/planilhas/modelos      modelos do sistema (chamada, turmas, listagem, IMC…) e plataformas disponíveis
    GET    /web/api/planilhas/<id>         um registro
    PUT    /web/api/planilhas/<id>         altera os campos enviados
    DELETE /web/api/planilhas/<id>         remove do cadastro (a planilha no Google não é apagada)
    GET    /web/api/planilhas/categorias   categorias em uso e sugeridas
    GET    /web/api/planilhas/finalidades  finalidades possíveis e as turmas do Infantil de turmas.json (sugestões)

Erros: 400 dado inválido · 404 id inexistente · 409 planilha já cadastrada ou outra ativa para a mesma finalidade e turma · 500 arquivo do cadastro ilegível.
"""
from __future__ import annotations

import re
from functools import wraps

from flask import Blueprint, jsonify, request

from src.comum import paths as _paths
from src.comum import planilhas_gerenciador as _gp
from src.comum import planilhas_plataformas as _plat
from src.comum import planilhas_registro as _pr
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json

planilhas_bp = Blueprint("planilhas", __name__)


def _tratar_erros(funcao):
    @wraps(funcao)
    def interna(*args, **kwargs):
        try:
            return funcao(*args, **kwargs)
        except (_pr.PlanilhaDuplicada, _pr.PlanilhaEmConflito) as exc:   # antes de ValueError: são subclasses
            return jsonify({"erro": str(exc)}), 409
        except _pr.PlanilhaNaoEncontrada as exc:
            return jsonify({"erro": str(exc)}), 404
        except _plat.PlataformaIndisponivel as exc:
            return jsonify({"erro": str(exc)}), 422
        except (ValueError, _gp._modelos.ModeloDesconhecido) as exc:
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
                       finalidade=a.get("finalidade", ""), plataforma=a.get("plataforma", ""), turma=a.get("turma", ""),
                       ordem=a.get("ordem", "id"), direcao=a.get("dir", "asc"),
                       limite=a.get("limite", _pr.LIMITE_PAGINA_PADRAO), inicio=a.get("inicio", 0))
    dados["resumo"] = _pr.resumo()
    return jsonify(dados)


@planilhas_bp.route("/categorias", methods=["GET"])
@_tratar_erros
def categorias():
    return jsonify(_pr.categorias())


def _turmas_infantil() -> list[str]:
    """Turmas do Infantil de turmas.json (só sugestão para o formulário; vazio se o arquivo ainda não existe)."""
    try:
        turmas = carregar_json(_paths.dados_ano_atual() / "turmas.json", dict, dict)
    except (ArquivoJsonCorrompidoError, OSError, ValueError):
        return []
    return sorted(nome for nome in turmas if re.search(r"infantil", str(nome), re.IGNORECASE))


def _todas_as_turmas() -> list[str]:
    try:
        turmas = carregar_json(_paths.dados_ano_atual() / "turmas.json", dict, dict)
    except (ArquivoJsonCorrompidoError, OSError, ValueError):
        return []
    return sorted(str(t) for t in turmas)


@planilhas_bp.route("/finalidades", methods=["GET"])
@_tratar_erros
def finalidades():
    return jsonify({"finalidades": [{"valor": v, "nome": n, "por_turma": _pr.FINALIDADES_INFO[v]["por_turma"],
                                     "externa": _pr.FINALIDADES_INFO[v]["externa"]} for v, n in _pr.FINALIDADES.items()],
                    "turmas": _todas_as_turmas() or _turmas_infantil(), "plataformas": _plat.listar()})


@planilhas_bp.route("/modelos", methods=["GET"])
@_tratar_erros
def modelos():
    return jsonify({"modelos": _gp.modelos_disponiveis(), "plataformas": _plat.listar(), "turmas": _todas_as_turmas()})


@planilhas_bp.route("/criar-de-modelo", methods=["POST"])
@_tratar_erros
def criar_de_modelo():
    c = _corpo()
    turmas = c.get("turmas") if isinstance(c.get("turmas"), list) else []
    r = _gp.criar_de_modelo(str(c.get("modelo") or ""), str(c.get("plataforma") or "google_sheets"), nome=str(c.get("nome") or ""),
                            turma=str(c.get("turma") or ""), turmas_selecionadas=[str(t) for t in turmas],
                            tornar_vigente=bool(c.get("tornar_vigente")))
    return jsonify({"status": "ok", "mensagem": "Planilha criada e cadastrada." if r["item"] else "Planilha criada.",
                    "item": r["item"], "destino": r["destino"], "avisos": r["avisos"]}), 201


@planilhas_bp.route("/<int:id_item>/ativar", methods=["POST"])
@_tratar_erros
def ativar(id_item):
    ref = _gp.definir_vigente(id_item)
    return jsonify({"status": "ok", "mensagem": f"'{ref.nome}' agora é a planilha em uso.", "item": _pr.obter(id_item)})


@planilhas_bp.route("", methods=["POST"])
@_tratar_erros
def criar():
    c = _corpo()
    item = _pr.criar(c.get("nome"), c.get("link", ""), c.get("categoria", ""), c.get("observacao", ""), c.get("status", "ativa"),
                     finalidade=c.get("finalidade", ""), turma=c.get("turma", ""), plataforma=c.get("plataforma") or "google_sheets",
                     caminho=c.get("caminho", ""))
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

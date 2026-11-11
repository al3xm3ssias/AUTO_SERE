"""
Auto SERE — Interface Web
==========================
Servidor Flask que expõe a interface gráfica do Auto SERE e os
endpoints de API que disparam as automações já existentes em
src/automacao e src/comum.

Para rodar (a partir da raiz do projeto AUTO_SERE):

    pip install -r requirements.txt
    python -m src.web.app

No Windows, o jeito normal é o atalho "AUTO SERE" (ou AUTO_SERE.bat), que
usa src.launcher: sobe este servidor uma única vez e abre o Chrome em modo
aplicativo. Host e porta vêm de src.comum.servidor (padrão 127.0.0.1:8000).
"""

import os
import re

from flask import Flask, Blueprint, jsonify, render_template, request, send_from_directory

from src.comum import paths as _paths
from src.comum import servidor as _servidor

from src.web.api.calendario import calendario_bp
from src.web.api.planilhas import planilhas_bp
from src.web.api.rotas import api_bp
from src.web.api.whatsapp import whatsapp_bp

# Blueprint da interface (páginas HTML + estáticos), isolado sob /web
# para não colidir com outras rotas que o projeto venha a ter.
web_bp = Blueprint(
    "web",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/web/static",
)


@web_bp.route("/")
@web_bp.route("/web")
def index():
    """Renderiza o shell único da aplicação (SPA simples por troca de view)."""
    return render_template("base.html")


@web_bp.route("/web/api/ping")
def ping():
    """Usado pelo launcher para saber se JÁ existe um AUTO SERE rodando."""
    return jsonify({"app": "auto-sere", "ok": True, "pid": os.getpid()})


@web_bp.route("/manifest.webmanifest")
def manifest():
    """Manifest do PWA (nome, ícones e modo standalone)."""
    img = "/web/static/img/"
    resposta = jsonify({
        "name": "Auto SERE",
        "short_name": "Auto SERE",
        "description": "Automações do portal SERE — Escola Municipal Profª Judith Macedo Silveira",
        "id": "/web",
        "start_url": "/web",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0f1117",
        "theme_color": "#161b27",
        "lang": "pt-BR",
        "icons": [
            {"src": img + "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": img + "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": img + "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    })
    resposta.mimetype = "application/manifest+json"
    return resposta


@web_bp.route("/sw.js")
def service_worker():
    """Service worker na raiz (escopo "/"). Sem cache: os dados são dinâmicos."""
    resposta = send_from_directory(web_bp.static_folder, "sw.js", mimetype="text/javascript")
    resposta.headers["Cache-Control"] = "no-cache"
    resposta.headers["Service-Worker-Allowed"] = "/"
    return resposta


# ── Modo "somente consulta" (ano letivo anterior) ──────────────────────────────────────────────────────────
# Voltar a um ano anterior é para VER. Em vez de espalhar a checagem por cada rota (e esquecer a próxima que
# alguém criar), um único guarda recusa toda requisição que escreve, salvo as poucas abaixo.
_RE_PERMITIDAS_EM_CONSULTA = (
    re.compile(r"^/web/api/configuracoes/ano-letivo$"),            # trocar de ano (é o caminho de volta)
    re.compile(r"^/web/api/configuracoes/ano-letivo/backup$"),     # copiar dados não altera nada
    re.compile(r"^/web/api/automacoes/[^/]+/(previa|cancelar)$"),  # prévia só lê; cancelar só encerra
    re.compile(r"^/web/api/whatsapp/webhook$"),                    # evento que o gateway manda para cá (não é ação do usuário)
    re.compile(r"^/web/api/planilhas(/\d+)?$"),                    # cadastro de planilhas: atravessa os anos letivos, não é dado de um ano
)
_METODOS_DE_LEITURA = ("GET", "HEAD", "OPTIONS")


def mensagem_somente_consulta(ano) -> str:
    return (f"Somente consulta: o ano letivo {ano} está sendo visualizado e não pode ser alterado. "
            "Para trabalhar, volte ao ano atual em Configurações → Ano letivo.")


def _permitido_em_consulta() -> bool:
    caminho = request.path.rstrip("/")
    if any(r.match(caminho) for r in _RE_PERMITIDAS_EM_CONSULTA):
        return True
    if caminho == "/web/api/configuracoes/ano-letivo/restaurar":     # só "conferir" (aplicar=false) é leitura
        return not (request.get_json(silent=True) or {}).get("aplicar")
    return False


def _instalar_guarda_somente_consulta(app: Flask) -> None:
    @app.before_request
    def _guarda():
        if request.method in _METODOS_DE_LEITURA or not request.path.startswith("/web/api/"):
            return None
        if not _paths.somente_consulta() or _permitido_em_consulta():
            return None
        ano = _paths.ano_atual()
        texto = mensagem_somente_consulta(ano)
        return jsonify({"erro": texto, "mensagem": texto, "somente_consulta": True, "ano": str(ano)}), 403

    @app.context_processor
    def _contexto_do_ano():
        return {"ano_letivo": str(_paths.ano_atual()), "somente_consulta": _paths.somente_consulta()}


def create_app() -> Flask:
    app = Flask(__name__)
    _instalar_guarda_somente_consulta(app)

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/web/api")
    app.register_blueprint(calendario_bp, url_prefix="/web/api/calendario")
    app.register_blueprint(whatsapp_bp, url_prefix="/web/api/whatsapp")
    app.register_blueprint(planilhas_bp, url_prefix="/web/api/planilhas")

    return app


app = create_app()

if __name__ == "__main__":
    # Sem debug/reloader por padrão: o reloader sobe o processo duas vezes e
    # quebraria o launcher ("não abrir várias instâncias"). Para desenvolver
    # com auto-reload, defina AUTO_SERE_DEBUG=1.
    _debug = _servidor.modo_debug()
    app.run(
        host=_servidor.servidor_host(),
        port=_servidor.servidor_porta(),
        debug=_debug,
        use_reloader=_debug,
        threaded=True,
    )

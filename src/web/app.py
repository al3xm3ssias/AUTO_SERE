"""
Auto SERE — Interface Web
==========================
Servidor Flask que expõe a interface gráfica do Auto SERE e os
endpoints de API que disparam as automações já existentes em
src/automacao e src/comum.

Para rodar (a partir da raiz do projeto AUTO_SERE):

    pip install -r requirements.txt
    python -m src.web.app

A aplicação sobe em http://127.0.0.1:5000
"""

from flask import Flask, Blueprint, render_template

from src.web.api.calendario import calendario_bp
from src.web.api.rotas import api_bp

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


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/web/api")
    app.register_blueprint(calendario_bp, url_prefix="/web/api/calendario")

    return app


app = create_app()

if __name__ == "__main__":
    # debug=True facilita o desenvolvimento (auto-reload); desligar em produção.
    app.run(host="127.0.0.1", port=5000, debug=True)

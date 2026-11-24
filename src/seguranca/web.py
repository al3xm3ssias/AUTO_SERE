"""
web.py — a segurança ligada ao Flask
=====================================
Tudo passa por UM guarda (`before_request`), na ordem:

  1. Host      só 127.0.0.1 / localhost / ::1 (ou o configurado). Barra "DNS rebinding": um site malicioso aberto no navegador
               fazendo o navegador falar com este servidor local por outro nome.
  2. Origem    em escrita (POST/PUT/PATCH/DELETE) o Origin/Referer/Sec-Fetch-Site tem de ser o próprio sistema.
  3. Sessão    sem sessão válida: páginas vão para o login, a API responde 401. Exceções: login, criação do administrador,
               arquivos estáticos, ping do launcher e o webhook do WhatsApp (esse tem token próprio).
  4. Troca     se a senha é temporária, só a tela de troca de senha funciona.
  5. Perfil    politica.perfil_exigido(): consulta / operador / admin.
  6. CSRF      escrita autenticada exige o cabeçalho X-CSRF-Token igual ao da sessão (static/js/seguranca.js põe em todo fetch).

E, em toda resposta: Content-Security-Policy estrita (só scripts do próprio sistema), X-Frame-Options, nosniff, sem cache dos
dados (alunos!) etc.

`ATIVA` liga/desliga o guarda. Existe só para os testes antigos (que não conhecem login); em produção é sempre True e não há
variável de ambiente nem arquivo de configuração que a desligue.
"""
from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import quote, urlsplit

from flask import Blueprint, Response, g, jsonify, redirect, render_template, request

from src.comum import servidor as _servidor

from . import auditoria, limite, politica, segredo, senhas, sessoes as _sessoes, usuarios
from .usuarios import ErroUsuarios, FalhaLogin

ATIVA = True
COOKIE = "auto_sere_sid"
SEGUROS = ("GET", "HEAD", "OPTIONS")

sessoes = _sessoes.RepositorioSessoes()
limitador_login = limite.LimitadorTentativas(maximo=10, janela_s=300)        # 10 erros de entrada por endereço a cada 5 min
limitador_troca = limite.LimitadorTentativas(maximo=10, janela_s=300)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; connect-src 'self'; "
       "frame-src 'self' blob: https://www.openstreetmap.org; object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'; worker-src 'self'; manifest-src 'self'")

_HOSTS_FIXOS = {"localhost", "127.0.0.1", "::1"}
_PUBLICAS_EXATAS = {"/web/entrar", "/web/instalacao", "/web/api/ping", "/manifest.webmanifest", "/sw.js"}
_WEBHOOK = "/web/api/whatsapp/webhook"


# ───────────────────────────── utilidades ─────────────────────────────

def _ip() -> str:
    return request.remote_addr or ""


def _hostname_de(valor: str) -> str:
    try:
        return (urlsplit("//" + valor).hostname or "").lower()
    except ValueError:
        return ""


def _host_permitido(hostname: str, caminho: str) -> bool:
    if not hostname:
        return False
    if hostname in _HOSTS_FIXOS or hostname == _servidor.servidor_host().lower() or hostname in _sessoes.hosts_extras():
        return True
    try:
        ipaddress.ip_address(hostname)          # IP "puro" não existe em ataque de DNS rebinding (ele depende de um NOME)
        return True
    except ValueError:
        pass
    return caminho == _WEBHOOK and hostname == "host.docker.internal"       # o gateway Docker do WhatsApp chama por este nome


def _origem_ok() -> bool:
    """Em escrita: de onde veio a requisição? Navegadores sempre mandam Origin (ou Sec-Fetch-Site) em POST."""
    site = (request.headers.get("Sec-Fetch-Site") or "").lower()
    if site and site not in ("same-origin", "none"):
        return False
    for cab in ("Origin", "Referer"):
        valor = request.headers.get(cab)
        if valor:
            if valor == "null":
                return False
            return urlsplit(valor).netloc.lower() == request.host.lower()
    return True                                  # sem Origin/Referer: não é navegador (script local, gateway); o CSRF cobre o resto


def _eh_publica(caminho: str) -> bool:
    return caminho in _PUBLICAS_EXATAS or caminho.startswith("/web/static/") or caminho == _WEBHOOK


def _quer_json() -> bool:
    return request.path.startswith("/web/api/") or request.is_json or request.method not in SEGUROS


def _proximo_seguro(valor: str | None) -> str:
    v = (valor or "").strip()
    if v.startswith("/web") and not v.startswith("//") and "\\" not in v and "\n" not in v and "\r" not in v and "://" not in v:
        return v
    return "/web"


def _resposta_erro(codigo: int, mensagem: str, **extra) -> Response:
    r = jsonify({"erro": mensagem, "mensagem": mensagem, **extra})
    r.status_code = codigo
    return r


def _pagina_erro(codigo: int, titulo: str, texto: str) -> Response:
    r = Response(render_template("auth/erro.html", titulo=titulo, texto=texto), status=codigo, mimetype="text/html")
    return r


def _definir_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Strict", secure=request.is_secure, path="/")


def _apagar_cookie(resp: Response) -> None:
    resp.set_cookie(COOKIE, "", expires=0, max_age=0, httponly=True, samesite="Strict", secure=request.is_secure, path="/")


def usuario_atual():
    return getattr(g, "usuario", None)


# ───────────────────────────── o guarda ─────────────────────────────

def _guarda():
    if not ATIVA:
        return None
    g.usuario, g.sessao, g.token = None, None, request.cookies.get(COOKIE)
    caminho = request.path.rstrip("/") or "/"

    if not _host_permitido(_hostname_de(request.host), caminho):
        auditoria.registrar("origem_bloqueada", "", _ip(), f"Host recusado: {request.host[:80]}")
        return _resposta_erro(400, "Endereço de acesso não permitido.") if _quer_json() else _pagina_erro(400, "Endereço não permitido", "Abra o AUTO SERE pelo atalho (ele usa o endereço correto deste computador).")

    if request.method not in SEGUROS and not _origem_ok():
        auditoria.registrar("origem_bloqueada", "", _ip(), f"{request.method} {caminho}: origem recusada")
        return _resposta_erro(403, "Requisição recusada: ela não veio da própria tela do sistema.")

    if caminho == _WEBHOOK or caminho.startswith("/web/static/") or caminho in ("/web/api/ping", "/manifest.webmanifest", "/sw.js"):
        return None

    estado = usuarios.estado()
    if estado == "ilegivel":
        return (_resposta_erro(503, "O cadastro de usuários está ilegível. Ninguém entra até isso ser resolvido (veja documentacao/Seguranca.md).")
                if _quer_json() else _pagina_erro(503, "Cadastro de usuários ilegível", "O arquivo credenciais/usuarios.json está ilegível ou foi alterado. Por segurança ninguém entra até isso ser resolvido: restaure o usuarios.json.bak ou use a recuperação (python -m src.seguranca redefinir-senha)."))

    sessao = sessoes.obter(g.token) if estado == "ok" else None
    usuario = usuarios.obter(sessao.usuario_id) if sessao else None
    if sessao and (usuario is None or not usuario.ativo or usuario.perfil != sessao.perfil_ao_entrar):
        sessoes.revogar(g.token)                                      # desativado/removido/rebaixado depois de entrar: cai na hora
        sessao = usuario = None
    if sessao and usuario:
        g.usuario, g.sessao = usuario, sessao

    if caminho in ("/web/entrar", "/web/instalacao"):                 # fluxo de entrada: tratado nas próprias rotas
        return None

    if estado == "sem_usuarios":
        return (_resposta_erro(401, "O sistema ainda não tem administrador. Abra o AUTO SERE e crie o primeiro usuário.", instalacao=True)
                if request.path.startswith("/web/api/") else redirect("/web/instalacao"))
    if sessao is None or usuario is None:
        if request.path.startswith("/web/api/"):
            return _resposta_erro(401, "Sua sessão terminou. Entre de novo.", autenticacao=True)
        alvo = _proximo_seguro(request.full_path.rstrip("?")) if request.method == "GET" else "/web"
        return redirect("/web/entrar" + ("" if alvo == "/web" else "?proximo=" + _quote(alvo)))
    if usuario.trocar_senha and caminho not in ("/web/trocar-senha", "/web/api/seguranca/trocar-senha", "/web/api/seguranca/sessao", "/web/api/seguranca/sair"):
        if request.path.startswith("/web/api/"):
            return _resposta_erro(403, "Você precisa trocar a senha temporária antes de continuar.", trocar_senha=True)
        return redirect("/web/trocar-senha")

    exigido = politica.perfil_exigido(request.method, caminho)
    if not usuario.tem_perfil(exigido):
        auditoria.registrar("acesso_negado", usuario.usuario, _ip(), f"{request.method} {caminho} (precisa {exigido})")
        texto = f"O seu perfil ({usuarios.ROTULO_PERFIL.get(usuario.perfil, usuario.perfil)}) não tem permissão para isso. Peça a um administrador."
        return (_resposta_erro(403, texto, permissao=True) if _quer_json()
                else _pagina_erro(403, "Sem permissão", texto))

    if request.method not in SEGUROS:
        enviado = request.headers.get("X-CSRF-Token", "")
        if not enviado or not hmac.compare_digest(enviado.encode(), sessao.csrf.encode()):
            auditoria.registrar("csrf_bloqueado", usuario.usuario, _ip(), f"{request.method} {caminho}")
            return _resposta_erro(403, "Requisição recusada por segurança (token ausente ou vencido). Recarregue a página e tente de novo.", csrf=True)
    return None


def _quote(texto: str) -> str:
    return quote(texto, safe="")


def _cabecalhos(resp: Response) -> Response:
    if not ATIVA:
        return resp
    h = resp.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    if not request.path.startswith("/web/static/") and request.path != "/sw.js":
        h["Cache-Control"] = "no-store, max-age=0"                    # dados de alunos: nada de cópia no cache do navegador
        h["Pragma"] = "no-cache"
    return resp


def _contexto():
    u = usuario_atual()
    s = getattr(g, "sessao", None)
    return {"csrf_token": s.csrf if s else "", "usuario_atual": u.publico() if u else None,
            "inatividade_cliente_s": max(60, _sessoes.inatividade_s() - 120),
            "seguranca_ativa": ATIVA}


# ───────────────────────────── páginas ─────────────────────────────

paginas_bp = Blueprint("seguranca_paginas", __name__)
api_seg_bp = Blueprint("seguranca_api", __name__)


def _entrar_sessao(usuario, resp: Response) -> None:
    token, _ = sessoes.criar(usuario.id, _ip(), usuario.perfil)
    _definir_cookie(resp, token)


@paginas_bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if request.method == "GET":
        estado = usuarios.estado()
        if estado == "sem_usuarios":
            return redirect("/web/instalacao")
        if usuario_atual():
            return redirect(_proximo_seguro(request.args.get("proximo")))
        return render_template("auth/entrar.html", proximo=_proximo_seguro(request.args.get("proximo")), motivo=request.args.get("motivo", ""))

    ip = _ip()
    if not limitador_login.liberado(ip):
        espera = limitador_login.segundos_para_liberar(ip)
        auditoria.registrar("limite_tentativas", "", ip, f"aguardar {espera}s")
        return _resposta_erro(429, f"Muitas tentativas. Aguarde {max(1, espera // 60 + (1 if espera % 60 else 0))} minuto(s) e tente de novo.")
    corpo = request.get_json(silent=True) or {}
    try:
        u = usuarios.autenticar(str(corpo.get("usuario", "")), str(corpo.get("senha", "")), ip)
    except FalhaLogin as f:
        limitador_login.registrar(ip)
        auditoria.registrar("login_falha", f.usuario, ip, f.motivo)
        return _resposta_erro(401, "Usuário ou senha inválidos, ou acesso temporariamente bloqueado por excesso de tentativas.")
    except segredo.ChaveIndisponivel:
        return _resposta_erro(503, "A chave de proteção das senhas não pode ser lida neste computador/usuário do Windows. "
                                   "Use a recuperação: python -m src.seguranca redefinir-senha (veja documentacao/Seguranca.md).")
    except ErroUsuarios as e:
        return _resposta_erro(503, e.mensagem)
    resp = jsonify({"ok": True, "proximo": _proximo_seguro(corpo.get("proximo")) if not u.trocar_senha else "/web/trocar-senha",
                    "trocar_senha": u.trocar_senha})
    _entrar_sessao(u, resp)
    auditoria.registrar("login_ok", u.usuario, ip)
    return resp


@paginas_bp.route("/instalacao", methods=["GET", "POST"])
def instalacao():
    """Cria o PRIMEIRO administrador. Só existe enquanto não houver nenhum usuário e só responde ao próprio computador."""
    estado = usuarios.estado()
    if estado != "sem_usuarios":
        return redirect("/web/entrar") if estado == "ok" else _pagina_erro(503, "Cadastro de usuários ilegível", "Veja documentacao/Seguranca.md.")
    if (request.remote_addr or "") not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return _pagina_erro(403, "Só neste computador", "A criação do primeiro administrador só pode ser feita no próprio computador onde o AUTO SERE está instalado.")
    if request.method == "GET":
        return render_template("auth/instalacao.html")
    corpo = request.get_json(silent=True) or {}
    if str(corpo.get("senha", "")) != str(corpo.get("confirmacao", "")):
        return _resposta_erro(400, "A confirmação não é igual à senha.")
    try:
        u = usuarios.criar_primeiro_admin(str(corpo.get("usuario", "admin")), str(corpo.get("nome", "")), str(corpo.get("senha", "")), origem="tela", ip=_ip())
    except ErroUsuarios as e:
        return _resposta_erro(400, e.mensagem, problemas=e.problemas)
    except segredo.ChaveIndisponivel as e:
        return _resposta_erro(503, f"Não foi possível proteger a senha: {e}")
    segredo.proteger_pasta(segredo.pasta_seguranca().parent)
    resp = jsonify({"ok": True, "proximo": "/web"})
    _entrar_sessao(u, resp)
    return resp


@paginas_bp.route("/trocar-senha", methods=["GET"])
def trocar_senha_pagina():
    u = usuario_atual()
    if not u:
        return redirect("/web/entrar")
    return render_template("auth/trocar_senha.html", obrigatoria=u.trocar_senha)


# ───────────────────────────── API ─────────────────────────────

@api_seg_bp.route("/sessao", methods=["GET"])
def sessao_atual():
    u, s = usuario_atual(), getattr(g, "sessao", None)
    if not u or not s:
        return _resposta_erro(401, "Sem sessão.", autenticacao=True)
    return jsonify({"usuario": u.publico(), "csrf": s.csrf, "inatividade_s": _sessoes.inatividade_s()})


@api_seg_bp.route("/sair", methods=["POST"])
def sair():
    u = usuario_atual()
    sessoes.revogar(getattr(g, "token", None))
    if u:
        auditoria.registrar("logout", u.usuario, _ip())
    resp = jsonify({"ok": True})
    _apagar_cookie(resp)
    return resp


@api_seg_bp.route("/trocar-senha", methods=["POST"])
def trocar_senha():
    u = usuario_atual()
    if not u:
        return _resposta_erro(401, "Sem sessão.", autenticacao=True)
    ip = _ip()
    if not limitador_troca.liberado(u.id):
        return _resposta_erro(429, "Muitas tentativas de troca de senha. Aguarde alguns minutos.")
    corpo = request.get_json(silent=True) or {}
    if str(corpo.get("nova", "")) != str(corpo.get("confirmacao", corpo.get("nova", ""))):
        return _resposta_erro(400, "A confirmação não é igual à senha nova.")
    try:
        novo = usuarios.alterar_propria_senha(u.id, str(corpo.get("atual", "")), str(corpo.get("nova", "")), ip)
    except ErroUsuarios as e:
        limitador_troca.registrar(u.id)
        return _resposta_erro(400, e.mensagem, problemas=e.problemas)
    sessoes.revogar_usuario(u.id)                                      # derruba TODAS as sessões (inclusive de quem roubou uma) e abre uma nova
    resp = jsonify({"ok": True, "proximo": "/web"})
    _entrar_sessao(novo, resp)
    return resp


def _dados_gerenciar(id: str):
    alvo = usuarios.obter(id)
    if alvo is None:
        raise ErroUsuarios("Usuário não encontrado.")
    return alvo


def _erro_usuarios(e: ErroUsuarios) -> Response:
    return _resposta_erro(400, e.mensagem, problemas=e.problemas)


@api_seg_bp.route("/usuarios", methods=["GET"])
def usuarios_listar():
    return jsonify({"usuarios": [u.publico() for u in usuarios.listar()], "perfis": [{"id": p, "rotulo": usuarios.ROTULO_PERFIL[p]} for p in usuarios.PERFIS]})


@api_seg_bp.route("/usuarios", methods=["POST"])
def usuarios_criar():
    quem = usuario_atual()
    corpo = request.get_json(silent=True) or {}
    senha = str(corpo.get("senha") or "")
    gerada = not senha
    if gerada:
        senha = senhas.gerar_senha_temporaria()
    try:
        novo = usuarios.criar(str(corpo.get("usuario", "")), str(corpo.get("nome", "")), str(corpo.get("perfil", "operador")), senha,
                              por=quem.usuario if quem else "", ip=_ip(), trocar_senha=True)
    except ErroUsuarios as e:
        return _erro_usuarios(e)
    return jsonify({"ok": True, "usuario": novo.publico(), "senha_temporaria": senha if gerada else None}), 201


@api_seg_bp.route("/usuarios/<string:id_usuario>", methods=["PATCH"])
def usuarios_alterar(id_usuario: str):
    quem = usuario_atual()
    corpo = request.get_json(silent=True) or {}
    if quem and quem.id == id_usuario and ("perfil" in corpo or "ativo" in corpo):
        return _resposta_erro(400, "Você não pode mudar o seu próprio perfil nem se desativar. Peça a outro administrador.")
    try:
        novo = usuarios.alterar(id_usuario, perfil=corpo.get("perfil"), ativo=corpo.get("ativo"), nome=corpo.get("nome"),
                                por=quem.usuario if quem else "", ip=_ip())
    except ErroUsuarios as e:
        return _erro_usuarios(e)
    if "perfil" in corpo or "ativo" in corpo:
        sessoes.revogar_usuario(id_usuario)                            # a mudança vale na hora: ele precisa entrar de novo
    return jsonify({"ok": True, "usuario": novo.publico()})


@api_seg_bp.route("/usuarios/<string:id_usuario>/redefinir-senha", methods=["POST"])
def usuarios_redefinir(id_usuario: str):
    quem = usuario_atual()
    corpo = request.get_json(silent=True) or {}
    senha = str(corpo.get("senha") or "")
    gerada = not senha
    if gerada:
        senha = senhas.gerar_senha_temporaria()
    try:
        novo = usuarios.redefinir_senha(id_usuario, senha, por=quem.usuario if quem else "", ip=_ip(), temporaria=True)
    except ErroUsuarios as e:
        return _erro_usuarios(e)
    sessoes.revogar_usuario(id_usuario)
    return jsonify({"ok": True, "usuario": novo.publico(), "senha_temporaria": senha if gerada else None})


@api_seg_bp.route("/usuarios/<string:id_usuario>/desbloquear", methods=["POST"])
def usuarios_desbloquear(id_usuario: str):
    quem = usuario_atual()
    try:
        novo = usuarios.desbloquear(id_usuario, por=quem.usuario if quem else "", ip=_ip())
    except ErroUsuarios as e:
        return _erro_usuarios(e)
    return jsonify({"ok": True, "usuario": novo.publico()})


@api_seg_bp.route("/usuarios/<string:id_usuario>", methods=["DELETE"])
def usuarios_remover(id_usuario: str):
    quem = usuario_atual()
    if quem and quem.id == id_usuario:
        return _resposta_erro(400, "Você não pode apagar o seu próprio usuário. Peça a outro administrador.")
    try:
        usuarios.remover(id_usuario, por=quem.usuario if quem else "", ip=_ip())
    except ErroUsuarios as e:
        return _erro_usuarios(e)
    sessoes.revogar_usuario(id_usuario)
    return jsonify({"ok": True})


@api_seg_bp.route("/auditoria", methods=["GET"])
def auditoria_listar():
    try:
        limite_n = min(max(int(request.args.get("limite", 100)), 1), 1000)
    except ValueError:
        limite_n = 100
    return jsonify({"eventos": auditoria.ler(limite_n), "corrente": auditoria.verificar_corrente()})


# ───────────────────────────── instalação no app ─────────────────────────────

def instalar(app) -> None:
    """Chamar ANTES dos outros before_request (o guarda de login vem primeiro)."""
    app.before_request(_guarda)
    app.after_request(_cabecalhos)
    app.context_processor(_contexto)
    app.register_blueprint(paginas_bp, url_prefix="/web")
    app.register_blueprint(api_seg_bp, url_prefix="/web/api/seguranca")

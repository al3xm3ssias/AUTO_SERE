"""Segurança — camada web: guarda de login, cookie, CSRF, Host/Origin, perfis, troca obrigatória, cabeçalhos e CLI."""
import pytest

from src.comum import paths
from src.seguranca import auditoria, cli, segredo, senhas, usuarios
from src.seguranca import web as seg_web
from src.web.app import create_app

SENHA = "Escola-Forte#2026x"
SENHA2 = "Outra-Senha!9876zz"


@pytest.fixture(autouse=True)
def seguranca_ligada(tmp_path, monkeypatch):
    monkeypatch.setattr(seg_web, "ATIVA", True)
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path / "credenciais")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(senhas, "PARAMETROS", {"memoria_kib": 1024, "tempo": 1, "paralelismo": 1})
    monkeypatch.setattr(senhas, "_hash_de_mentira", None)
    monkeypatch.setattr(seg_web, "sessoes", seg_web._sessoes.RepositorioSessoes())
    seg_web.limitador_login.zerar()
    seg_web.limitador_troca.zerar()
    segredo.esquecer_cache()
    auditoria.esquecer_cache()
    yield


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def c(app):
    return app.test_client()


def _admin():
    return usuarios.criar_primeiro_admin("admin", "Adm", SENHA)


def _entrar(cliente, usuario="admin", senha=SENHA):
    r = cliente.post("/web/entrar", json={"usuario": usuario, "senha": senha})
    return r


def _csrf(cliente):
    return cliente.get("/web/api/seguranca/sessao").get_json()["csrf"]


def _logado(app, perfil="admin", usuario=None):
    """Cliente já entrado com o perfil pedido."""
    if usuarios.estado() == "sem_usuarios":
        _admin()
    nome = "admin"
    senha = SENHA
    if perfil != "admin":
        nome = usuario or perfil
        usuarios.criar(nome, nome.title(), perfil, SENHA2, trocar_senha=False)
        senha = SENHA2
    cli_ = app.test_client()
    assert _entrar(cli_, nome, senha).status_code == 200
    return cli_


# ───────────────────────────── sem login ─────────────────────────────

def test_sem_usuarios_tudo_vai_para_a_instalacao(c):
    assert c.get("/web").headers["Location"].endswith("/web/instalacao")
    r = c.get("/web/api/turmas/lista")
    assert r.status_code == 401 and r.get_json()["instalacao"] is True


def test_com_usuarios_pagina_vai_para_entrar_e_api_da_401(c):
    _admin()
    r = c.get("/web")
    assert r.status_code == 302 and "/web/entrar" in r.headers["Location"]
    r = c.get("/web/api/turmas/lista")
    assert r.status_code == 401 and r.get_json()["autenticacao"] is True
    assert c.get("/web/api/ajuda/indice").status_code == 401           # as demais rotas existentes também


def test_rotas_publicas():
    app = create_app()
    c = app.test_client()
    _admin()
    assert c.get("/web/api/ping").get_json() == {"app": "auto-sere", "ok": True}
    assert c.get("/web/entrar").status_code == 200
    assert c.get("/manifest.webmanifest").status_code == 200
    assert c.get("/web/static/js/entrar.js").status_code == 200


def test_toda_rota_do_app_exige_login(app):
    """Percorre TODAS as rotas (inclusive as que alguém criar depois): sem login, nenhuma entrega dado."""
    _admin()
    c = app.test_client()
    liberadas = {"/web/entrar", "/web/instalacao", "/web/api/ping", "/manifest.webmanifest", "/sw.js", "/web/api/whatsapp/webhook"}
    furos = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint.endswith("static") or rule.rule in liberadas or rule.rule.startswith("/web/static"):
            continue
        import re
        caminho = re.sub(r"<[^>]+>", "1", rule.rule)
        for metodo in sorted(set(rule.methods) - {"HEAD", "OPTIONS"}):
            r = c.open(caminho, method=metodo, json={} if metodo != "GET" else None)
            if r.status_code not in (302, 401):
                furos.append((metodo, rule.rule, r.status_code))
    assert not furos, furos


def test_webhook_do_whatsapp_continua_com_token_proprio(c):
    _admin()
    r = c.post("/web/api/whatsapp/webhook", json={"a": 1})
    assert r.status_code == 403 and "Não autorizado" in r.get_json()["erro"]       # chegou na rota (token errado), não no login


# ───────────────────────────── entrar e sair ─────────────────────────────

def test_login_correto_cria_cookie_seguro(c):
    _admin()
    r = _entrar(c)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    cookie = r.headers["Set-Cookie"]
    assert "auto_sere_sid=" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert c.get("/web").status_code == 200
    assert c.get("/web/api/seguranca/sessao").get_json()["usuario"]["usuario"] == "admin"


def test_login_errado_mensagem_unica_e_sem_cookie(c):
    _admin()
    r1 = _entrar(c, "admin", "errada-errada-1A!")
    r2 = _entrar(c, "naoexiste", "errada-errada-1A!")
    assert r1.status_code == r2.status_code == 401
    assert r1.get_json()["erro"] == r2.get_json()["erro"]
    assert "Set-Cookie" not in r1.headers


def test_bloqueio_por_usuario_aparece_igual_a_senha_errada(c):
    _admin()
    msgs = set()
    for _ in range(6):
        msgs.add(_entrar(c, "admin", "errada-errada-1A!").get_json()["erro"])
    assert len(msgs) == 1
    assert _entrar(c).status_code == 401                                # senha certa, mas bloqueado


def test_limite_por_endereco_devolve_429(c):
    _admin()
    for i in range(10):
        assert _entrar(c, f"u{i}x", "errada-errada-1A!").status_code == 401
    r = _entrar(c)
    assert r.status_code == 429


def test_sair_encerra_a_sessao_e_o_cookie_velho_nao_volta_a_valer(app):
    _admin()
    c = app.test_client()
    _entrar(c)
    token = c.get_cookie("auto_sere_sid").value
    csrf = _csrf(c)
    assert c.post("/web/api/seguranca/sair", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert c.get("/web/api/turmas/lista").status_code == 401
    c.set_cookie("auto_sere_sid", token)                                # alguém reaproveita o cookie antigo
    assert c.get("/web/api/turmas/lista").status_code == 401


def test_proximo_so_aceita_caminho_interno(c):
    _admin()
    for ruim in ("https://evil.com", "//evil.com", "/web\\evil", "javascript:alert(1)", "/fora"):
        r = c.post("/web/entrar", json={"usuario": "admin", "senha": SENHA, "proximo": ruim})
        assert r.get_json()["proximo"] == "/web", ruim
        c = create_app().test_client()
    r = c.post("/web/entrar", json={"usuario": "admin", "senha": SENHA, "proximo": "/web?x=1"})
    assert r.get_json()["proximo"] == "/web?x=1"


def test_sessao_nova_a_cada_login(app):
    _admin()
    a, b = app.test_client(), app.test_client()
    _entrar(a)
    _entrar(b)
    assert a.get_cookie("auto_sere_sid").value != b.get_cookie("auto_sere_sid").value


# ───────────────────────────── CSRF, Host e origem ─────────────────────────────

def test_escrita_sem_token_csrf_e_barrada_e_com_token_passa(app):
    c = _logado(app)
    r = c.post("/web/api/seguranca/usuarios", json={"usuario": "novo", "perfil": "operador"})
    assert r.status_code == 403 and r.get_json()["csrf"] is True
    r = c.post("/web/api/seguranca/usuarios", json={"usuario": "novo", "perfil": "operador"}, headers={"X-CSRF-Token": "errado"})
    assert r.status_code == 403
    r = c.post("/web/api/seguranca/usuarios", json={"usuario": "novo", "perfil": "operador"}, headers={"X-CSRF-Token": _csrf(c)})
    assert r.status_code == 201
    assert "csrf_bloqueado" in [e["evento"] for e in auditoria.ler()]


def test_csrf_de_uma_sessao_nao_vale_em_outra(app):
    a = _logado(app)
    _admin_token_a = _csrf(a)
    usuarios.criar("outro", "Outro", "admin", SENHA2, trocar_senha=False)
    b = app.test_client()
    _entrar(b, "outro", SENHA2)
    r = b.post("/web/api/seguranca/usuarios", json={"usuario": "x1y", "perfil": "consulta"}, headers={"X-CSRF-Token": _admin_token_a})
    assert r.status_code == 403


@pytest.mark.parametrize("host", ["evil.com", "evil.com:8000", "127.0.0.1.evil.com", "localhost.evil.com"])
def test_host_estranho_e_barrado(app, host):
    _admin()
    c = app.test_client()
    r = c.get("/web/entrar", headers={"Host": host})
    assert r.status_code == 400
    assert "origem_bloqueada" in [e["evento"] for e in auditoria.ler()]


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "192.168.0.10:8000", "localhost"])
def test_hosts_locais_passam(app, host):
    _admin()
    assert app.test_client().get("/web/entrar", headers={"Host": host}).status_code == 200


def test_host_docker_so_vale_para_o_webhook(app):
    _admin()
    c = app.test_client()
    assert c.post("/web/api/whatsapp/webhook", json={}, headers={"Host": "host.docker.internal:8000"}).status_code == 403   # chegou na rota
    assert c.get("/web/entrar", headers={"Host": "host.docker.internal:8000"}).status_code == 400


def test_origem_de_outro_site_e_barrada_em_escrita(app):
    _admin()
    c = app.test_client()
    for cab in ({"Origin": "https://evil.com"}, {"Origin": "null"}, {"Referer": "https://evil.com/x"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
        r = c.post("/web/entrar", json={"usuario": "admin", "senha": SENHA}, headers=cab)
        assert r.status_code == 403, cab
    r = c.post("/web/entrar", json={"usuario": "admin", "senha": SENHA}, headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


# ───────────────────────────── perfis ─────────────────────────────

def test_consulta_so_le(app):
    c = _logado(app, "consulta")
    assert c.get("/web/api/ajuda/indice").status_code == 200
    r = c.post("/web/api/automacoes/turmas/executar", json={}, headers={"X-CSRF-Token": _csrf(c)})
    assert r.status_code == 403 and r.get_json()["permissao"] is True
    assert c.get("/web/api/seguranca/usuarios").status_code == 403
    assert c.get("/web/api/configuracoes/gmail").status_code == 403


def test_operador_executa_mas_nao_administra(app):
    c = _logado(app, "operador")
    h = {"X-CSRF-Token": _csrf(c)}
    assert c.post("/web/api/configuracoes/gmail", json={}, headers=h).status_code == 403
    assert c.post("/web/api/seguranca/usuarios", json={}, headers=h).status_code == 403
    assert c.post("/web/api/wizard/escola/executar", json={}, headers=h).status_code == 403
    r = c.post("/web/api/automacoes/inexistente/executar", json={}, headers=h)
    assert r.status_code != 403                                         # passou pelo guarda (a rota responde por conta própria)


def test_admin_passa_em_tudo(app):
    c = _logado(app)
    h = {"X-CSRF-Token": _csrf(c)}
    assert c.get("/web/api/seguranca/usuarios").status_code == 200
    assert c.post("/web/api/configuracoes/gmail", json={}, headers=h).status_code != 403


def test_negacao_vai_para_a_auditoria(app):
    c = _logado(app, "consulta")
    c.post("/web/api/automacoes/turmas/executar", json={}, headers={"X-CSRF-Token": _csrf(c)})
    ev = [e for e in auditoria.ler() if e["evento"] == "acesso_negado"]
    assert ev and ev[0]["usuario"] == "consulta"


def test_mudar_perfil_derruba_a_sessao_na_hora(app):
    adm = _logado(app)
    op = _logado(app, "operador", "maria")
    assert op.get_cookie("auto_sere_sid")
    alvo = usuarios.obter_por_usuario("maria")
    r = adm.patch(f"/web/api/seguranca/usuarios/{alvo.id}", json={"perfil": "consulta"}, headers={"X-CSRF-Token": _csrf(adm)})
    assert r.status_code == 200
    assert op.get("/web/api/ajuda/indice").status_code == 401


def test_desativar_usuario_derruba_a_sessao(app):
    adm = _logado(app)
    op = _logado(app, "operador", "maria")
    alvo = usuarios.obter_por_usuario("maria")
    adm.patch(f"/web/api/seguranca/usuarios/{alvo.id}", json={"ativo": False}, headers={"X-CSRF-Token": _csrf(adm)})
    assert op.get("/web/api/ajuda/indice").status_code == 401


def test_perfil_alterado_direto_no_arquivo_nao_eleva_sessao_antiga(app):
    op = _logado(app, "operador", "maria")
    u = usuarios.obter_por_usuario("maria")
    import json
    arq = paths.CREDENCIAIS_DIR / "usuarios.json"
    d = json.loads(arq.read_text())
    for r in d["usuarios"]:
        if r["id"] == u.id:
            r["perfil"] = "admin"
    arq.write_text(json.dumps(d))
    assert op.get("/web/api/ajuda/indice").status_code == 401           # a sessão nasceu como operador: refaz o login


def test_admin_nao_se_apaga_nem_se_rebaixa(app):
    adm = _logado(app)
    eu = usuarios.obter_por_usuario("admin")
    h = {"X-CSRF-Token": _csrf(adm)}
    assert adm.delete(f"/web/api/seguranca/usuarios/{eu.id}", headers=h).status_code == 400
    assert adm.patch(f"/web/api/seguranca/usuarios/{eu.id}", json={"perfil": "consulta"}, headers=h).status_code == 400


# ───────────────────────────── usuários pela API ─────────────────────────────

def test_criar_usuario_gera_senha_temporaria_e_troca_e_obrigatoria(app):
    adm = _logado(app)
    r = adm.post("/web/api/seguranca/usuarios", json={"usuario": "joao", "nome": "João", "perfil": "operador"}, headers={"X-CSRF-Token": _csrf(adm)})
    temp = r.get_json()["senha_temporaria"]
    assert temp and senhas.problemas_da_senha(temp) == []
    joao = app.test_client()
    resp = _entrar(joao, "joao", temp)
    assert resp.get_json()["trocar_senha"] is True and resp.get_json()["proximo"] == "/web/trocar-senha"
    # preso na troca: nada mais funciona
    assert joao.get("/web").headers["Location"].endswith("/web/trocar-senha")
    r = joao.get("/web/api/ajuda/indice")
    assert r.status_code == 403 and r.get_json()["trocar_senha"] is True
    assert joao.get("/web/trocar-senha").status_code == 200
    h = {"X-CSRF-Token": _csrf(joao)}
    assert joao.post("/web/api/seguranca/trocar-senha", json={"atual": temp, "nova": "fraca", "confirmacao": "fraca"}, headers=h).status_code == 400
    ok = joao.post("/web/api/seguranca/trocar-senha", json={"atual": temp, "nova": SENHA2, "confirmacao": SENHA2}, headers=h)
    assert ok.status_code == 200
    assert joao.get("/web/api/ajuda/indice").status_code == 200       # liberado, com sessão nova


def test_trocar_senha_derruba_as_outras_sessoes(app):
    _admin()
    a, b = app.test_client(), app.test_client()
    _entrar(a)
    _entrar(b)
    r = a.post("/web/api/seguranca/trocar-senha", json={"atual": SENHA, "nova": SENHA2, "confirmacao": SENHA2}, headers={"X-CSRF-Token": _csrf(a)})
    assert r.status_code == 200
    assert b.get("/web/api/ajuda/indice").status_code == 401
    assert a.get("/web/api/ajuda/indice").status_code == 200
    assert _entrar(app.test_client(), senha=SENHA).status_code == 401


def test_trocar_senha_com_confirmacao_diferente(app):
    c = _logado(app)
    r = c.post("/web/api/seguranca/trocar-senha", json={"atual": SENHA, "nova": SENHA2, "confirmacao": "outra"}, headers={"X-CSRF-Token": _csrf(c)})
    assert r.status_code == 400


def test_listagem_nunca_expoe_hash(app):
    c = _logado(app)
    corpo = c.get("/web/api/seguranca/usuarios").get_data(as_text=True)
    assert "argon2" not in corpo and "hash" not in corpo and SENHA not in corpo


def test_admin_redefine_senha_de_outro_e_desbloqueia(app):
    adm = _logado(app)
    usuarios.criar("maria", "Maria", "operador", SENHA2, trocar_senha=False)
    maria = usuarios.obter_por_usuario("maria")
    for _ in range(5):
        _entrar(app.test_client(), "maria", "errada-errada-1A!")
        seg_web.limitador_login.zerar()
    assert usuarios.obter(maria.id).bloqueado
    h = {"X-CSRF-Token": _csrf(adm)}
    r = adm.post(f"/web/api/seguranca/usuarios/{maria.id}/redefinir-senha", json={}, headers=h)
    nova = r.get_json()["senha_temporaria"]
    assert nova and not usuarios.obter(maria.id).bloqueado
    assert _entrar(app.test_client(), "maria", nova).status_code == 200


def test_auditoria_pela_api_so_para_admin(app):
    adm = _logado(app)
    r = adm.get("/web/api/seguranca/auditoria")
    assert r.status_code == 200 and r.get_json()["corrente"]["integra"] is True and r.get_json()["eventos"]
    assert _logado(app, "operador", "opera").get("/web/api/seguranca/auditoria").status_code == 403


# ───────────────────────────── instalação (1º administrador) ─────────────────────────────

def test_tela_de_instalacao_cria_admin_e_ja_entra(c):
    assert c.get("/web/instalacao").status_code == 200
    r = c.post("/web/instalacao", json={"usuario": "admin", "nome": "Fulana", "senha": SENHA, "confirmacao": SENHA})
    assert r.status_code == 200 and usuarios.obter_por_usuario("admin").perfil == "admin"
    assert c.get("/web/api/ajuda/indice").status_code == 200


def test_instalacao_valida_confirmacao_e_politica(c):
    assert c.post("/web/instalacao", json={"usuario": "admin", "senha": SENHA, "confirmacao": "x"}).status_code == 400
    r = c.post("/web/instalacao", json={"usuario": "admin", "senha": "123", "confirmacao": "123"})
    assert r.status_code == 400 and r.get_json()["problemas"]
    assert usuarios.estado() == "sem_usuarios"


def test_instalacao_fecha_depois_do_primeiro_usuario(c):
    _admin()
    assert c.get("/web/instalacao").status_code == 302
    r = c.post("/web/instalacao", json={"usuario": "invasor", "senha": SENHA2, "confirmacao": SENHA2})
    assert r.status_code == 302 and usuarios.obter_por_usuario("invasor") is None


def test_instalacao_so_responde_ao_proprio_computador(app):
    c = app.test_client()
    r = c.post("/web/instalacao", json={"usuario": "admin", "senha": SENHA, "confirmacao": SENHA}, environ_base={"REMOTE_ADDR": "10.1.2.3"})
    assert r.status_code == 403 and usuarios.estado() == "sem_usuarios"


def test_arquivo_ilegivel_nao_reabre_a_instalacao(app):
    _admin()
    (paths.CREDENCIAIS_DIR / "usuarios.json").write_text("{", encoding="utf-8")
    c = app.test_client()
    assert c.get("/web/instalacao").status_code == 503
    assert c.get("/web").status_code == 503
    assert c.post("/web/instalacao", json={"usuario": "admin", "senha": SENHA, "confirmacao": SENHA}).status_code == 503


# ───────────────────────────── cabeçalhos e telas ─────────────────────────────

def test_cabecalhos_de_seguranca(app):
    _admin()
    c = app.test_client()
    r = c.get("/web/entrar")
    h = r.headers
    assert "script-src 'self'" in h["Content-Security-Policy"] and "'unsafe-inline'" not in h["Content-Security-Policy"].split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"] and "object-src 'none'" in h["Content-Security-Policy"]
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff" and h["Referrer-Policy"] == "no-referrer"
    assert "no-store" in h["Cache-Control"]
    assert "no-store" not in c.get("/web/static/js/entrar.js").headers.get("Cache-Control", "")


def test_spa_so_traz_scripts_externos_e_dados_do_usuario(app):
    c = _logado(app)
    html = c.get("/web").get_data(as_text=True)
    import re
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag, f"script inline não é aceito pela política: {tag}"
    assert 'name="csrf-token"' in html and 'data-perfil="admin"' in html and 'id="btn-sair"' in html
    assert html.index("js/seguranca.js") < html.index("js/app.js")


def test_html_dos_templates_nao_tem_handler_inline():
    from pathlib import Path
    import re
    raiz = Path(__file__).resolve().parent.parent / "src" / "web"
    for p in list((raiz / "templates").rglob("*.html")) + list((raiz / "static" / "js").glob("*.js")):
        if "vendor" in p.parts:
            continue
        texto = p.read_text(encoding="utf-8")
        assert not re.search(r"\son(click|change|input|submit|load|error)\s*=", texto), f"handler inline em {p.name}"


def test_login_mostra_aviso_de_inatividade(app):
    _admin()
    assert "falta de uso" in app.test_client().get("/web/entrar?motivo=inatividade").get_data(as_text=True)


def test_sessao_informa_o_que_esta_rodando_e_estender_renova(app, monkeypatch):
    c = _logado(app)
    assert c.get("/web/api/seguranca/sessao").get_json()["ocupado"] == []
    monkeypatch.setattr(seg_web, "tarefas_em_andamento", lambda: ["turmas", "fila de WhatsApp"])
    d = c.get("/web/api/seguranca/sessao").get_json()
    assert d["ocupado"] == ["turmas", "fila de WhatsApp"]
    r = c.post("/web/api/seguranca/estender", headers={"X-CSRF-Token": d["csrf"]})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert c.post("/web/api/seguranca/estender").status_code in (400, 403)          # sem CSRF não vale


def test_estender_funciona_para_perfil_consulta_e_exige_login(app):
    consulta = _logado(app, "consulta")
    csrf = _csrf(consulta)
    assert consulta.post("/web/api/seguranca/estender", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert app.test_client().post("/web/api/seguranca/estender").status_code == 401


def test_tarefas_em_andamento_enxerga_fila_do_whatsapp_rodando(monkeypatch):
    from src.servicos.whatsapp import fila as _fila_mod

    class Falsa:
        def em_andamento(self): return True
    monkeypatch.setattr(_fila_mod, "obter_fila", lambda: Falsa())
    assert "fila de WhatsApp" in seg_web.tarefas_em_andamento()


def test_js_pergunta_antes_de_sair_por_inatividade():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "src" / "web" / "static" / "js" / "seguranca.js").read_text(encoding="utf-8")
    assert "Estender essa sessão?" in js and "/web/api/seguranca/estender" in js
    assert 'setInterval(function () { if (!saindo && Date.now() - ultimo > limite) { sair("inatividade"); } }, 15000);' not in js


# ───────────────────────────── CLI ─────────────────────────────

def _roteiro(monkeypatch, senhas_digitadas, textos=()):
    s, t = iter(senhas_digitadas), iter(textos)
    monkeypatch.setattr(cli, "_ler_senha", lambda prompt: next(s))
    monkeypatch.setattr(cli, "_ler_texto", lambda prompt: next(t))
    monkeypatch.setattr(cli, "_escrever", lambda texto="": None)


def test_cli_criar_admin_interativo(monkeypatch):
    _roteiro(monkeypatch, ["fraca", SENHA, SENHA2, SENHA, SENHA], ["admin", "Dona Maria"])
    assert cli.main(["criar-admin"]) == cli.OK                          # 1ª fraca; 2ª e 3ª não conferem; 4ª e 5ª ok
    u = usuarios.obter_por_usuario("admin")
    assert u.perfil == "admin" and u.nome == "Dona Maria"
    assert usuarios.autenticar("admin", SENHA)


def test_cli_nao_recria_se_ja_existe_e_existe_informa(monkeypatch):
    assert cli.main(["existe"]) == 1
    _admin()
    assert cli.main(["existe"]) == 0
    _roteiro(monkeypatch, [])
    assert cli.main(["criar-admin"]) == cli.OK
    assert len(usuarios.listar()) == 1


def test_cli_cancelar_nao_cria_nada(monkeypatch):
    def cancela(prompt):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "_ler_texto", cancela)
    monkeypatch.setattr(cli, "_escrever", lambda texto="": None)
    assert cli.main(["criar-admin"]) == cli.CANCELADO and usuarios.estado() == "sem_usuarios"


def test_cli_senha_pela_entrada_padrao(monkeypatch):
    import io, sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(SENHA + "\n"))
    monkeypatch.setattr(cli, "_escrever", lambda texto="": None)
    assert cli.main(["criar-admin", "--senha-stdin", "--usuario", "diretoria"]) == cli.OK
    assert usuarios.autenticar("diretoria", SENHA)


def test_cli_redefinir_senha_desbloqueia(monkeypatch):
    _admin()
    for _ in range(5):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada-errada-1A!")
    _roteiro(monkeypatch, [SENHA2, SENHA2])
    assert cli.main(["redefinir-senha", "--usuario", "admin"]) == cli.OK
    assert usuarios.autenticar("admin", SENHA2)


def test_cli_pimenta_perdida_exige_confirmacao_e_invalida_os_outros(monkeypatch):
    _admin()
    usuarios.criar("maria", "Maria", "operador", SENHA2, trocar_senha=False)
    segredo._arquivo_pimenta().write_bytes(b"lixo")
    segredo.esquecer_cache()
    _roteiro(monkeypatch, [SENHA2, SENHA2])
    assert cli.main(["redefinir-senha", "--usuario", "admin"]) == cli.ERRO       # sem --regenerar-chave não mexe em nada
    assert cli.main(["redefinir-senha", "--usuario", "admin", "--regenerar-chave"]) == cli.OK
    assert usuarios.autenticar("admin", SENHA2)
    with pytest.raises(usuarios.FalhaLogin):
        usuarios.autenticar("maria", SENHA2)                            # a senha dela deixou de valer: o admin redefine


def test_cli_recupera_arquivo_ilegivel_com_criar(monkeypatch):
    _admin()
    (paths.CREDENCIAIS_DIR / "usuarios.json").write_text("{", encoding="utf-8")
    _roteiro(monkeypatch, [SENHA2, SENHA2])
    assert cli.main(["redefinir-senha", "--usuario", "admin"]) == cli.ILEGIVEL
    _roteiro(monkeypatch, [SENHA2, SENHA2])
    assert cli.main(["redefinir-senha", "--usuario", "admin", "--criar"]) == cli.OK
    assert usuarios.autenticar("admin", SENHA2).perfil == "admin"


def test_cli_listar_e_verificar_auditoria(monkeypatch, capsys):
    _admin()
    monkeypatch.undo() if False else None
    assert cli.main(["listar"]) == cli.OK
    saida = capsys.readouterr().out
    assert "admin" in saida and "argon2" not in saida
    assert cli.main(["verificar-auditoria"]) == cli.OK

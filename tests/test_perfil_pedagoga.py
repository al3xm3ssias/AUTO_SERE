"""Perfil Pedagoga: permissões próprias (lista, nega por padrão), validadas no servidor, e a interface só com o que ela pode usar.
O administrador (e operador/consulta) continua exatamente como antes."""
import re

import pytest

from src.comum import paths
from src.seguranca import auditoria, politica, segredo, senhas, usuarios
from src.seguranca import web as seg_web
from src.web.api import rotas
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


@pytest.fixture()
def app():
    return create_app()


def _cliente(app, perfil):
    if usuarios.estado() == "sem_usuarios":
        usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    nome, senha = "admin", SENHA
    if perfil != "admin":
        nome, senha = perfil, SENHA2
        usuarios.criar(nome, nome.title(), perfil, SENHA2, trocar_senha=False)
    c = app.test_client()
    assert c.post("/web/entrar", json={"usuario": nome, "senha": senha}).status_code == 200
    return c


def _h(c):
    return {"X-CSRF-Token": c.get("/web/api/seguranca/sessao").get_json()["csrf"]}


def _rotas(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint.endswith("static") or rule.rule.startswith("/web/static"):
            continue
        caminho = re.sub(r"<[^>]+>", "x", rule.rule)
        for metodo in sorted(set(rule.methods) - {"HEAD", "OPTIONS"}):
            yield metodo, caminho


# Tudo o que a Pedagoga pode chamar. Se alguém ampliar a lista em politica.py, este teste obriga a decidir de propósito.
PERMITIDAS = {
    ("GET", "/web/api/seguranca/sessao"), ("POST", "/web/api/seguranca/estender"), ("POST", "/web/api/seguranca/sair"),
    ("POST", "/web/api/seguranca/trocar-senha"), ("GET", "/web/trocar-senha"), ("GET", "/"), ("GET", "/web"),
    ("GET", "/web/api/painel/resumo"), ("GET", "/web/api/turmas/lista"), ("GET", "/web/api/alunos/lista"),
    ("GET", "/web/api/encaminhamentos/lista"), ("GET", "/web/api/ano-letivo/contexto"),
    ("GET", "/web/api/configuracoes/escola"), ("GET", "/web/api/configuracoes/ano-letivo"),
    ("GET", "/web/api/configuracoes/navegador"), ("GET", "/web/api/configuracoes/backup-automatico"),
    ("GET", "/web/api/ajuda/indice"), ("GET", "/web/api/ajuda/geral"), ("GET", "/web/api/ajuda/x/x"),
    ("GET", "/web/api/automacoes/lista"), ("POST", "/web/api/cgm/analisar"),
    ("GET", "/web/api/automacoes/x/componentes"), ("GET", "/web/api/automacoes/x/status"),
    ("GET", "/web/api/automacoes/x/configuracao"), ("GET", "/web/api/automacoes/x/historico"),
    ("GET", "/web/api/automacoes/x/historico/x"), ("GET", "/web/api/automacoes/x/flags"),
    ("POST", "/web/api/automacoes/x/executar"), ("POST", "/web/api/automacoes/x/previa"),
    ("POST", "/web/api/automacoes/x/resposta"), ("POST", "/web/api/automacoes/x/cancelar"),
    ("POST", "/web/api/pedagoga/atualizar-dados"), ("GET", "/web/api/pedagoga/atualizar-dados/status"),
}


def test_pedagoga_so_tem_o_que_esta_na_lista(app):
    """Para toda rota do app (inclusive as futuras): a decisão da Pedagoga bate com a lista fechada acima, com 'x' no lugar da chave
    só para as rotas de automação (que dependem da chave)."""
    liberadas = set()
    for metodo, caminho in _rotas(app):
        # /automacoes/<chave>/...: testa com uma chave liberada e uma que não é
        for chave in ("turmas", "x_proibida"):
            c2 = caminho.replace("/automacoes/x/", f"/automacoes/{chave}/")
            ok = politica.permite("pedagoga", metodo, c2)
            if ok and chave == "turmas":
                liberadas.add((metodo, caminho))
            if "/automacoes/x/" in caminho and chave == "x_proibida":
                assert not ok, (metodo, c2)
    # rotas de /ajuda têm 1 ou 2 segmentos; /web/api/ajuda/<tipo>/<chave> aparece como x/x
    assert liberadas <= PERMITIDAS, sorted(liberadas - PERMITIDAS)


PUBLICAS = {"/web/entrar", "/web/instalacao", "/web/api/ping", "/manifest.webmanifest", "/sw.js", "/web/api/whatsapp/webhook"}


def test_pedagoga_recebe_403_em_toda_rota_fora_da_lista(app):
    c = _cliente(app, "pedagoga")
    h = _h(c)
    negadas = 0
    for metodo, caminho in _rotas(app):
        if caminho in PUBLICAS or politica.permite("pedagoga", metodo, caminho.replace("/automacoes/x/", "/automacoes/zzz/")):
            continue
        r = c.open(caminho.replace("/automacoes/x/", "/automacoes/zzz/"), method=metodo, json={} if metodo != "GET" else None, headers=h)
        assert r.status_code == 403, (metodo, caminho, r.status_code)
        negadas += 1
    assert negadas > 100


def test_perfil_pedagoga_nao_herda_nada_da_escada():
    for m, c in [("GET", "/web/api/funcionarios/lista"), ("GET", "/web/api/transferidos/lista"), ("GET", "/web/api/prematricula/lista"),
                 ("GET", "/web/api/painel/avisos"), ("GET", "/web/api/whatsapp/status"), ("GET", "/web/api/planilhas"),
                 ("GET", "/web/api/documentos/analise"), ("GET", "/web/api/configuracoes/gmail"), ("GET", "/web/api/seguranca/usuarios")]:
        assert not politica.permite("pedagoga", m, c), (m, c)
        assert politica.permite("consulta", m, c) == (politica.perfil_exigido(m, c) == "consulta")
    assert usuarios.Usuario.tem_perfil  # a escada continua existindo
    assert politica.permite("desconhecido", "GET", "/web/api/turmas/lista") is False


def test_automacoes_permitidas_so_turmas_e_alunos(app):
    c = _cliente(app, "pedagoga")
    h = _h(c)
    assert {i["chave"] for i in c.get("/web/api/automacoes/lista").get_json()["itens"]} == {"turmas", "alunos"}
    for chave in ("funcionarios", "rematricula", "transferidos", "documentos", "limpeza", "aluno", "sus", "avisos", "backup", "wizard_turmas"):
        for rota in ("executar", "previa", "cancelar", "resposta"):
            assert c.post(f"/web/api/automacoes/{chave}/{rota}", json={}, headers=h).status_code == 403, (chave, rota)
        assert c.get(f"/web/api/automacoes/{chave}/status").status_code == 403
    # gravar opções guardadas, navegador e apagar histórico: nem nas liberadas
    assert c.post("/web/api/automacoes/turmas/flags", json={"flags": []}, headers=h).status_code == 403
    assert c.post("/web/api/automacoes/turmas/navegador", json={}, headers=h).status_code == 403
    assert c.delete("/web/api/automacoes/turmas/historico", headers=h).status_code == 403


def test_pedagoga_executa_turmas_e_alunos_modo_basico_e_completo(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr(rotas, "_executar_registrado", lambda script, chave, payload, tj: chamadas.append((chave, payload.get("modo"))))
    c = _cliente(app, "pedagoga")
    h = _h(c)
    for chave, corpo in [("turmas", {}), ("alunos", {"modo": "basico"}), ("alunos", {"modo": "completo", "rapido": True})]:
        rotas._EXECUCOES.pop(chave, None)
        r = c.post(f"/web/api/automacoes/{chave}/executar", json=corpo, headers=h)
        assert r.status_code == 200, r.get_json()
    assert chamadas == [("turmas", None), ("alunos", "basico"), ("alunos", "completo")]


def test_segunda_trava_na_propria_rota_de_execucao(app, monkeypatch):
    monkeypatch.setattr(seg_web, "ATIVA", False)           # sem o guarda: só a trava da rota
    monkeypatch.setattr(rotas, "_perfil_atual", lambda: "pedagoga")
    r = app.test_client().post("/web/api/automacoes/funcionarios/executar", json={})
    assert r.status_code == 403 and r.get_json()["permissao"] is True


def test_somente_leitura_nada_de_escrita_nem_configuracao(app):
    c = _cliente(app, "pedagoga")
    h = _h(c)
    for metodo, caminho in [("POST", "/web/api/configuracoes/escola"), ("POST", "/web/api/configuracoes/ano-letivo"),
                            ("POST", "/web/api/configuracoes/navegador"), ("POST", "/web/api/configuracoes/backup-automatico"),
                            ("POST", "/web/api/wizard/escola/executar"), ("POST", "/web/api/wizard/funcionarios/executar"),
                            ("POST", "/web/api/prematricula/registro/1"),
                            ("POST", "/web/api/transferidos/destino/1"), ("POST", "/web/api/whatsapp/enviar"),
                            ("POST", "/web/api/seguranca/usuarios"), ("PATCH", "/web/api/seguranca/usuarios/x"),
                            ("DELETE", "/web/api/seguranca/usuarios/x"), ("POST", "/web/api/painel/avisos/x/resolver")]:
        assert c.open(caminho, method=metodo, json={}, headers=h).status_code == 403, (metodo, caminho)
    eventos = [e for e in auditoria.ler(100)]
    assert any("acesso_negado" in str(e) for e in eventos)


def test_pedagoga_pode_trocar_a_propria_senha_e_sair(app):
    c = _cliente(app, "pedagoga")
    h = _h(c)
    r = c.post("/web/api/seguranca/trocar-senha", json={"atual": SENHA2, "nova": "Terceira-Senha#4321qq"}, headers=h)
    assert r.status_code == 200, r.get_json()


def test_painel_reduzido_no_servidor(app, tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_alunos_fora_do_raio", lambda: (_ for _ in ()).throw(AssertionError("não devia ler")))
    c = _cliente(app, "pedagoga")
    d = c.get("/web/api/painel/resumo").get_json()
    assert [m["chave"] for m in d["principais"]] == ["total_alunos", "meninos", "meninas", "turmas"]
    assert [m["chave"] for m in d["secundarias"]] == ["encaminhamentos"]


def test_painel_do_administrador_continua_completo(app, monkeypatch):
    c = _cliente(app, "admin")
    d = c.get("/web/api/painel/resumo").get_json()
    assert [m["chave"] for m in d["principais"]] == ["total_alunos", "meninos", "meninas", "fila_prematricula", "turmas"]
    assert [m["chave"] for m in d["secundarias"]] == ["docs_pendentes", "fora_do_raio", "transferidos", "encaminhamentos"]
    assert len(c.get("/web/api/automacoes/lista").get_json()["itens"]) > 30


def test_menu_da_pedagoga_so_tem_o_autorizado(app):
    html = _cliente(app, "pedagoga").get("/web").get_data(as_text=True)
    views = set(re.findall(r'class="nav-item[^"]*" data-view="([\w-]+)"', html))
    assert views == {"painel", "turmas", "alunos", "encaminhamentos", "configuracoes", "ajuda", "automacoes"}
    assert set(re.findall(r'data-auto="(\w+)"', html)) == {"turmas", "alunos"}
    assert 'data-subgroup="matricula"' not in html and 'id="sec-funcionarios"' not in html and 'id="sec-whatsapp"' not in html
    assert 'data-perfil-restrito="1"' in html
    cfg = set(re.findall(r'data-config="(\w+)"', html))
    assert cfg == politica.CONFIGURACOES_PEDAGOGA


def test_menu_do_administrador_e_identico_ao_de_sempre(app):
    html = _cliente(app, "admin").get("/web").get_data(as_text=True)
    assert len(set(re.findall(r'data-auto="(\w+)"', html))) == 40
    for v in ("prematricula", "funcionarios", "transferidos", "whatsapp", "primeira-execucao", "planilhas"):
        assert f'data-view="{v}"' in html
    assert "data-perfil-restrito" not in html
    assert len(re.findall(r'data-config="(\w+)"', html)) == 20


def test_admin_cria_usuario_pedagoga_e_mudar_perfil_derruba_sessao(app):
    adm = _cliente(app, "admin")
    h = _h(adm)
    r = adm.post("/web/api/seguranca/usuarios", json={"usuario": "maria", "nome": "Maria", "perfil": "pedagoga", "senha": SENHA2}, headers=h)
    assert r.status_code == 201 and r.get_json()["usuario"]["perfil_rotulo"] == "Pedagoga"
    u = usuarios.obter_por_usuario("maria")
    usuarios.alterar(u.id, ativo=True)
    p = app.test_client()
    usuarios.redefinir_senha(u.id, SENHA2, temporaria=False)
    assert p.post("/web/entrar", json={"usuario": "maria", "senha": SENHA2}).status_code == 200
    assert p.get("/web/api/funcionarios/lista").status_code == 403
    adm.patch(f"/web/api/seguranca/usuarios/{u.id}", json={"perfil": "operador"}, headers=h)
    assert p.get("/web/api/turmas/lista").status_code == 401           # sessão derrubada: entra de novo já como operador


def test_ajuda_da_pedagoga_so_tem_o_que_ela_usa(app):
    ped = _cliente(app, "pedagoga").get("/web/api/ajuda/indice").get_json()
    assert {i["chave"] for i in ped["telas"]} <= politica.TELAS_PEDAGOGA and ped["telas"]
    assert {i["chave"] for g in ped["automacoes"] for i in g["itens"]} == {"turmas", "alunos"}
    assert {i["chave"] for i in ped["configuracoes"]} <= politica.CONFIGURACOES_PEDAGOGA
    p = app.test_client()
    p.post("/web/entrar", json={"usuario": "pedagoga", "senha": SENHA2})
    assert p.get("/web/api/ajuda/automacao/turmas").status_code == 200
    assert p.get("/web/api/ajuda/automacao/rematricula").status_code == 404
    assert p.get("/web/api/ajuda/tela/funcionarios").status_code == 404
    adm = app.test_client()
    adm.post("/web/entrar", json={"usuario": "admin", "senha": SENHA})
    full = adm.get("/web/api/ajuda/indice").get_json()
    assert len(full["telas"]) > len(ped["telas"]) and adm.get("/web/api/ajuda/automacao/rematricula").status_code == 200


def test_instalador_cria_admin_e_depois_pedagoga(monkeypatch):
    from src.seguranca import cli
    saidas = iter(["pedagoga", "Maria"])
    monkeypatch.setattr(cli, "_ler_texto", lambda prompt: next(saidas))
    monkeypatch.setattr(cli, "_ler_senha", lambda prompt: SENHA2)
    assert cli.main(["criar-usuario"]) != 0                         # sem administrador ainda: recusa
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    assert cli.main(["criar-usuario", "--perfil", "pedagoga"]) == 0
    u = usuarios.obter_por_usuario("pedagoga")
    assert u.perfil == "pedagoga" and u.trocar_senha is True


def test_pedagoga_salva_usuario_e_senha_do_sere_e_so_isso_no_assistente(app, monkeypatch):
    gravado = {}
    monkeypatch.setattr(rotas, "_persistir_env", lambda valores: gravado.update(valores))
    monkeypatch.setattr(rotas, "_recarregar_credenciais_em_runtime", lambda: True)
    c = _cliente(app, "pedagoga")
    h = _h(c)
    r = c.post("/web/api/wizard/credenciais_sere/executar", json={"login": "maria.sere", "senha": "segredo-123"}, headers=h)
    assert r.status_code == 200 and gravado == {"SERE_LOGIN": "maria.sere", "SERE_SENHA": "segredo-123"}
    assert "segredo-123" not in r.get_data(as_text=True)                    # a senha nunca volta na resposta
    for passo in ("escola", "funcionarios", "turmas", "alunos", "credenciais_rco"):    # os demais passos seguem só do administrador
        assert c.post(f"/web/api/wizard/{passo}/executar", json={}, headers=h).status_code == 403, passo
    html = c.get("/web").get_data(as_text=True)
    assert 'data-config-editaveis="' in html and "senha_sere" in html.split('data-config-editaveis="')[1].split('"')[0]
    linha = re.search(r'<div class="config-row" data-config="senha_sere"[^>]*>', html).group(0)
    assert "data-requer" not in linha                                        # senão o CSS da vitrine esconderia a linha dela


@pytest.fixture()
def auto_zerada(monkeypatch):
    monkeypatch.setattr(rotas, "_AUTO_PEDAGOGA", {"estado": "nao_iniciado", "etapa": "", "mensagem": "", "iniciado_em": None, "terminado_em": None})
    monkeypatch.delenv("PEDAGOGA_COLETA_AUTOMATICA", raising=False)
    iniciadas = []
    monkeypatch.setattr(rotas, "_auto_pedagoga_trabalho", lambda: iniciadas.append(1))
    return iniciadas


def test_atualizacao_automatica_so_da_pedagoga_e_so_uma_vez(app, monkeypatch, auto_zerada):
    monkeypatch.setenv("SERE_LOGIN", "maria.sere")
    monkeypatch.setenv("SERE_SENHA", "segredo-123")
    assert _cliente(app, "admin").post("/web/api/pedagoga/atualizar-dados", json={}, headers=_h(_cliente(app, "admin"))).status_code == 403
    c = _cliente(app, "pedagoga")
    h = _h(c)
    r1 = c.post("/web/api/pedagoga/atualizar-dados", json={}, headers=h)
    assert r1.status_code == 200 and r1.get_json()["estado"] == "executando"
    import time as _t
    _t.sleep(0.2)
    assert c.post("/web/api/pedagoga/atualizar-dados", json={}, headers=h).get_json()["estado"] == "executando"
    assert len(auto_zerada) == 1                                            # a segunda chamada (F5) não inicia outra coleta
    assert c.get("/web/api/pedagoga/atualizar-dados/status").get_json()["estado"] == "executando"


def test_atualizacao_automatica_sem_senha_do_sere_avisa_e_tenta_de_novo_depois(app, monkeypatch, auto_zerada):
    monkeypatch.setenv("SERE_LOGIN", "cpf")
    monkeypatch.setenv("SERE_SENHA", "senha_sere")
    c = _cliente(app, "pedagoga")
    h = _h(c)
    assert c.post("/web/api/pedagoga/atualizar-dados", json={}, headers=h).get_json()["estado"] == "sem_credenciais"
    assert auto_zerada == []
    monkeypatch.setenv("SERE_LOGIN", "maria.sere")
    monkeypatch.setenv("SERE_SENHA", "segredo-123")                          # ela salvou a senha: agora começa
    assert c.post("/web/api/pedagoga/atualizar-dados", json={}, headers=h).get_json()["estado"] == "executando"


def test_atualizacao_automatica_pode_ser_desligada(app, monkeypatch, auto_zerada):
    monkeypatch.setenv("PEDAGOGA_COLETA_AUTOMATICA", "0")
    monkeypatch.setenv("SERE_LOGIN", "maria.sere")
    monkeypatch.setenv("SERE_SENHA", "segredo-123")
    c = _cliente(app, "pedagoga")
    assert c.post("/web/api/pedagoga/atualizar-dados", json={}, headers=_h(c)).get_json()["estado"] == "desativado"
    assert auto_zerada == []


def _trabalhador(monkeypatch, status_por_chave):
    """Roda o trabalhador de verdade, com a execução trocada por um fantoche que só registra o status final."""
    monkeypatch.setattr(rotas, "_AUTO_PEDAGOGA", {"estado": "executando", "etapa": "", "mensagem": "", "iniciado_em": 1, "terminado_em": None})
    monkeypatch.setattr(rotas, "_EXECUCOES", {})
    chamadas = []

    def falsa(script, chave, payload, turmas_json):
        chamadas.append((chave, dict(payload)))
        rotas._EXECUCOES[chave] = {"status": status_por_chave[chave]}

    monkeypatch.setattr(rotas, "_executar_registrado", falsa)
    monkeypatch.setattr(rotas.time, "sleep", lambda s: None)
    rotas._auto_pedagoga_trabalho()
    return chamadas, rotas._auto_pedagoga_copia()


def test_trabalhador_roda_turmas_e_depois_alunos_basico(monkeypatch):
    chamadas, estado = _trabalhador(monkeypatch, {"turmas": "concluido", "alunos": "concluido"})
    assert chamadas == [("turmas", {}), ("alunos", {"modo": "basico"})]
    assert estado["estado"] == "concluido"


def test_trabalhador_para_na_primeira_falha_sem_derrubar_nada(monkeypatch):
    chamadas, estado = _trabalhador(monkeypatch, {"turmas": "erro", "alunos": "concluido"})
    assert [c for c, _ in chamadas] == ["turmas"]                              # Alunos não roda sobre Turmas que falhou
    assert estado["estado"] == "erro" and "Turmas" in estado["mensagem"]

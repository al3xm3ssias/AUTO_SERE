"""Segurança — núcleo: hash de senha, política, pimenta, usuários, bloqueio, sessões, auditoria e política de perfis."""
import json
import os

import pytest

from src.comum import paths
from src.seguranca import auditoria, politica, segredo, senhas, sessoes as sess, usuarios

SENHA = "Escola-Forte#2026x"
SENHA2 = "Outra-Senha!9876zz"


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    """Pastas temporárias e custo de hash mínimo (o real, de 128 MiB, deixaria a suíte lenta)."""
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path / "credenciais")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(senhas, "PARAMETROS", {"memoria_kib": 1024, "tempo": 1, "paralelismo": 1})
    monkeypatch.setattr(senhas, "SCRYPT", {"n": 2 ** 10, "r": 8, "p": 1})
    monkeypatch.setattr(senhas, "_hash_de_mentira", None)
    segredo.esquecer_cache()
    auditoria.esquecer_cache()
    yield tmp_path
    segredo.esquecer_cache()


# ───────────────────────────── política ─────────────────────────────

@pytest.mark.parametrize("senha", ["curta1A!", "senhasenhasenha", "Mudar@123456", "aaaaaaaaaaaa", "123456789012", "qwertyuiopas",
                                   "somenteminusc", " Com-espaco-na-ponta1A ", "ABCDEFGHIJKLMN"])
def test_senhas_fracas_sao_recusadas(senha):
    assert senhas.problemas_da_senha(senha), senha


@pytest.mark.parametrize("senha", [SENHA, "uma frase longa e boa de verdade", "Tr0ca-Isto#Agora"])
def test_senhas_fortes_passam(senha):
    assert senhas.problemas_da_senha(senha) == []


def test_senha_com_o_usuario_ou_o_nome_e_recusada():
    assert any("usuário" in p for p in senhas.problemas_da_senha("Maria.Silva#2026ab", usuario="maria.silva"))
    assert any("nome" in p for p in senhas.problemas_da_senha("Joaquim-Forte#2026", usuario="x1y2z", nome="Joaquim Pereira"))


def test_senha_temporaria_gerada_passa_na_politica():
    for _ in range(20):
        assert senhas.problemas_da_senha(senhas.gerar_senha_temporaria()) == []


# ───────────────────────────── hash e pimenta ─────────────────────────────

def test_hash_nao_contem_a_senha_e_confere():
    h = senhas.gerar_hash(SENHA)
    assert h.startswith("$argon2id$") and SENHA not in h
    assert senhas.verificar(h, SENHA)[0] is True
    assert senhas.verificar(h, SENHA + "x")[0] is False


def test_mesma_senha_gera_hashes_diferentes_por_causa_do_sal():
    assert senhas.gerar_hash(SENHA) != senhas.gerar_hash(SENHA)


def test_normalizacao_unicode_da_a_mesma_senha():
    h = senhas.gerar_hash("Sen\u00e1-Forte#2026ab")                      # á composto
    assert senhas.verificar(h, "Sena\u0301-Forte#2026ab")[0]            # a + acento combinante


def test_hash_com_outra_pimenta_nao_confere():
    h = senhas.gerar_hash(SENHA)
    segredo.regenerar_pimenta()
    assert senhas.verificar(h, SENHA)[0] is False


def test_pimenta_e_criada_uma_vez_e_tem_32_bytes():
    p1 = segredo.obter_pimenta()
    segredo.esquecer_cache()
    assert segredo.obter_pimenta() == p1 and len(p1) == 32
    if os.name != "nt":
        assert oct(os.stat(segredo._arquivo_pimenta()).st_mode)[-3:] == "600"


def test_pimenta_ilegivel_levanta_erro_claro():
    segredo.obter_pimenta()
    segredo._arquivo_pimenta().write_bytes(b"lixo")
    segredo.esquecer_cache()
    with pytest.raises(segredo.ChaveIndisponivel):
        segredo.obter_pimenta()


def test_hash_estranho_nunca_levanta_erro():
    for h in ("", None, "abc", "$argon2id$lixo", "$scrypt$x", "$scrypt$n=1,r=1,p=1$a$b"):
        assert senhas.verificar(h, SENHA) == (False, False)


def test_scrypt_de_reserva_funciona_e_e_refeito_em_argon2(monkeypatch):
    monkeypatch.setattr(senhas, "ARGON2_DISPONIVEL", False)
    h = senhas.gerar_hash(SENHA)
    assert h.startswith("$scrypt$")
    assert senhas.verificar(h, SENHA) == (True, False)
    assert senhas.verificar(h, "errada-errada-1A!")[0] is False
    monkeypatch.setattr(senhas, "ARGON2_DISPONIVEL", True)
    assert senhas.verificar(h, SENHA) == (True, True)                   # quando o argon2 volta, pede para refazer


def test_hash_com_parametros_antigos_pede_refazer(monkeypatch):
    h = senhas.gerar_hash(SENHA)
    monkeypatch.setattr(senhas, "PARAMETROS", {"memoria_kib": 2048, "tempo": 2, "paralelismo": 1})
    assert senhas.verificar(h, SENHA) == (True, True)


# ───────────────────────────── usuários ─────────────────────────────

def test_primeiro_usuario_e_admin_e_so_existe_um_primeiro():
    assert usuarios.estado() == "sem_usuarios"
    u = usuarios.criar_primeiro_admin("Admin", "Fulano de Tal", SENHA)
    assert u.perfil == "admin" and u.usuario == "admin" and usuarios.estado() == "ok"
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.criar_primeiro_admin("outro", "x", SENHA2)


def test_arquivo_nao_guarda_a_senha_nem_texto_reversivel():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    bruto = (paths.CREDENCIAIS_DIR / "usuarios.json").read_text(encoding="utf-8")
    assert SENHA not in bruto and "$argon2id$" in bruto
    if os.name != "nt":
        assert oct(os.stat(paths.CREDENCIAIS_DIR / "usuarios.json").st_mode)[-3:] == "600"


def test_senha_fraca_nao_cria_usuario():
    with pytest.raises(usuarios.ErroUsuarios) as e:
        usuarios.criar_primeiro_admin("admin", "Adm", "123456")
    assert e.value.problemas and usuarios.estado() == "sem_usuarios"


@pytest.mark.parametrize("nome", ["ab", "Com Espaco", "acentuação", "x" * 40, "-comeca", "a/b", ""])
def test_nomes_de_usuario_invalidos(nome):
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.criar_primeiro_admin(nome, "Adm", SENHA)


def test_autenticar_ok_e_erros_sao_indistinguiveis():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    assert usuarios.autenticar("ADMIN", SENHA).usuario == "admin"          # maiúsculas no usuário não importam
    for u, s in (("admin", "errada"), ("naoexiste", SENHA), ("", ""), ("admin", "")):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar(u, s)


def test_bloqueio_apos_cinco_erros_e_nem_a_senha_certa_entra():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    for _ in range(usuarios.MAX_FALHAS):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada")
    assert usuarios.obter_por_usuario("admin").bloqueado
    with pytest.raises(usuarios.FalhaLogin) as e:
        usuarios.autenticar("admin", SENHA)
    assert e.value.motivo == "bloqueado"


def test_bloqueio_passa_com_o_tempo_e_dobra_no_seguinte(monkeypatch):
    from datetime import datetime, timedelta, timezone
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    relogio = {"t": datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(usuarios, "_agora", lambda: relogio["t"])
    for _ in range(5):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada")
    ate1 = usuarios._parse(usuarios.obter_por_usuario("admin").bloqueado_ate)
    assert ate1 - relogio["t"] == timedelta(minutes=15)
    relogio["t"] += timedelta(minutes=16)
    for _ in range(5):                                                 # errou de novo sem ter acertado no meio: dobra
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada")
    ate2 = usuarios._parse(usuarios.obter_por_usuario("admin").bloqueado_ate)
    assert ate2 - relogio["t"] == timedelta(minutes=30)
    relogio["t"] += timedelta(minutes=31)
    assert usuarios.autenticar("admin", SENHA).usuario == "admin"      # acertou: zera tudo
    assert not usuarios.obter_por_usuario("admin").bloqueado


def test_acerto_zera_o_contador_de_erros():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    for _ in range(4):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada")
    usuarios.autenticar("admin", SENHA)
    for _ in range(4):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada")
    assert not usuarios.obter_por_usuario("admin").bloqueado


def test_usuario_desativado_nao_entra():
    a = usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    o = usuarios.criar("maria", "Maria", "operador", SENHA2)
    usuarios.alterar(o.id, ativo=False)
    with pytest.raises(usuarios.FalhaLogin):
        usuarios.autenticar("maria", SENHA2)
    assert a.id


def test_nunca_fica_sem_administrador_ativo():
    a = usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.remover(a.id)
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.alterar(a.id, perfil="operador")
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.alterar(a.id, ativo=False)
    b = usuarios.criar("segundo", "Segundo", "admin", SENHA2)
    usuarios.alterar(a.id, perfil="operador")                            # agora pode: sobra o segundo
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.remover(b.id)


def test_usuario_repetido_e_perfil_invalido():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.criar("ADMIN", "x", "operador", SENHA2)
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.criar("novo", "x", "superuser", SENHA2)


def test_trocar_propria_senha():
    a = usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.alterar_propria_senha(a.id, "errada", SENHA2)
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.alterar_propria_senha(a.id, SENHA, SENHA)                 # igual à atual
    with pytest.raises(usuarios.ErroUsuarios):
        usuarios.alterar_propria_senha(a.id, SENHA, "fraca")
    usuarios.alterar_propria_senha(a.id, SENHA, SENHA2)
    with pytest.raises(usuarios.FalhaLogin):
        usuarios.autenticar("admin", SENHA)
    assert usuarios.autenticar("admin", SENHA2)


def test_adivinhar_a_senha_atual_na_troca_tambem_bloqueia():
    a = usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    for _ in range(usuarios.MAX_FALHAS):
        with pytest.raises(usuarios.ErroUsuarios):
            usuarios.alterar_propria_senha(a.id, "errada", SENHA2)
    assert usuarios.obter(a.id).bloqueado


def test_redefinir_senha_pelo_admin_exige_troca_e_desbloqueia():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    m = usuarios.criar("maria", "Maria", "operador", SENHA2, trocar_senha=False)
    for _ in range(5):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("maria", "errada")
    nova = senhas.gerar_senha_temporaria()
    usuarios.redefinir_senha(m.id, nova, por="admin")
    u = usuarios.autenticar("maria", nova)
    assert u.trocar_senha is True


def test_hash_antigo_e_refeito_ao_entrar(monkeypatch):
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    antes = json.loads((paths.CREDENCIAIS_DIR / "usuarios.json").read_text())["usuarios"][0]["hash"]
    monkeypatch.setattr(senhas, "PARAMETROS", {"memoria_kib": 2048, "tempo": 2, "paralelismo": 1})
    usuarios.autenticar("admin", SENHA)
    depois = json.loads((paths.CREDENCIAIS_DIR / "usuarios.json").read_text())["usuarios"][0]["hash"]
    assert depois != antes and "m=2048" in depois


def test_arquivo_corrompido_nao_vira_tela_de_instalacao():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    (paths.CREDENCIAIS_DIR / "usuarios.json").write_text("{ quebrado", encoding="utf-8")
    assert usuarios.estado() == "ilegivel"
    with pytest.raises(usuarios.ArquivoIlegivel):
        usuarios.listar()


def test_arquivo_apagado_com_copia_existente_tambem_bloqueia():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    usuarios.criar("maria", "Maria", "operador", SENHA2)                 # a 2ª gravação cria o .bak
    (paths.CREDENCIAIS_DIR / "usuarios.json").unlink()
    assert usuarios.estado() == "ilegivel"


def test_estrutura_adulterada_e_ilegivel():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    (paths.CREDENCIAIS_DIR / "usuarios.json").write_text(json.dumps({"usuarios": [{"x": 1}]}), encoding="utf-8")
    assert usuarios.estado() == "ilegivel"


def test_recuperacao_pela_linha_de_comando_funciona_sem_a_senha_antiga():
    a = usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    for _ in range(5):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "errada")
    usuarios.redefinir_pela_linha_de_comando("admin", SENHA2)
    assert usuarios.autenticar("admin", SENHA2).id == a.id
    ev = [e["evento"] for e in auditoria.ler()]
    assert "senha_redefinida_cli" in ev


def test_isolar_arquivo_ilegivel_nao_apaga_nada():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    (paths.CREDENCIAIS_DIR / "usuarios.json").write_text("lixo", encoding="utf-8")
    movidos = usuarios.isolar_arquivo_ilegivel()
    assert movidos and usuarios.estado() == "sem_usuarios"
    assert any(p.name.startswith("usuarios.json.ilegivel-") for p in paths.CREDENCIAIS_DIR.iterdir())


# ───────────────────────────── sessões ─────────────────────────────

def test_sessao_expira_por_inatividade_e_por_duracao():
    t = {"v": 1000.0}
    repo = sess.RepositorioSessoes(relogio=lambda: t["v"])
    token, s = repo.criar("u1", "127.0.0.1", "admin")
    assert repo.obter(token) is s
    t["v"] += sess.INATIVIDADE_PADRAO_S - 5
    assert repo.obter(token) is not None                                 # usar renova a inatividade
    t["v"] += sess.INATIVIDADE_PADRAO_S + 5
    assert repo.obter(token) is None
    token2, _ = repo.criar("u1")
    for _ in range(30):                                                  # em uso constante, mas passa da duração máxima
        t["v"] += 1500
        if repo.obter(token2) is None:
            break
    assert repo.obter(token2) is None


def test_sessao_guarda_so_o_hash_do_token_e_cada_login_tem_token_novo():
    repo = sess.RepositorioSessoes()
    t1, _ = repo.criar("u1")
    t2, _ = repo.criar("u1")
    assert t1 != t2 and len(t1) >= 40
    assert t1 not in repo._por_id and all(len(k) == 64 for k in repo._por_id)


def test_revogar_usuario_derruba_todas_menos_a_excecao():
    repo = sess.RepositorioSessoes()
    a, _ = repo.criar("u1")
    b, _ = repo.criar("u1")
    c, _ = repo.criar("u2")
    assert repo.revogar_usuario("u1", exceto_token=b) == 1
    assert repo.obter(a) is None and repo.obter(b) and repo.obter(c)
    assert repo.obter("") is None and repo.obter(None) is None


def test_tempos_da_sessao_vem_da_configuracao_com_limites(monkeypatch):
    monkeypatch.setattr(sess, "_config_seguranca", lambda: {"inatividade_min": 1, "duracao_max_horas": 999})
    assert sess.inatividade_s() == 5 * 60 and sess.duracao_max_s() == 24 * 3600
    monkeypatch.setattr(sess, "_config_seguranca", lambda: {"inatividade_min": "lixo"})
    assert sess.inatividade_s() == 1800


# ───────────────────────────── auditoria ─────────────────────────────

def test_auditoria_encadeada_detecta_adulteracao():
    for i in range(5):
        auditoria.registrar("login_ok", f"u{i}", "127.0.0.1")
    assert auditoria.verificar_corrente() == {"integra": True, "linhas": 5, "primeira_quebra": None}
    arq = paths.LOGS_DIR / "auditoria.log"
    linhas = arq.read_text(encoding="utf-8").splitlines()
    del linhas[2]                                                        # apaga uma do meio
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    r = auditoria.verificar_corrente()
    assert r["integra"] is False and r["primeira_quebra"] == 3


def test_auditoria_editar_uma_linha_quebra_a_corrente():
    auditoria.registrar("login_ok", "ana", "")
    auditoria.registrar("login_falha", "bob", "")
    arq = paths.LOGS_DIR / "auditoria.log"
    arq.write_text(arq.read_text(encoding="utf-8").replace("bob", "ana"), encoding="utf-8")
    assert auditoria.verificar_corrente()["integra"] is False


def test_auditoria_nunca_tem_senha_nem_hash():
    usuarios.criar_primeiro_admin("admin", "Adm", SENHA)
    for _ in range(5):
        with pytest.raises(usuarios.FalhaLogin):
            usuarios.autenticar("admin", "segredo-errado-XYZ")
    bruto = (paths.LOGS_DIR / "auditoria.log").read_text(encoding="utf-8")
    assert "segredo-errado-XYZ" not in bruto and SENHA not in bruto and "argon2" not in bruto
    assert "admin_instalado" in bruto and "login_bloqueio" in bruto


def test_auditoria_continua_a_corrente_depois_de_reiniciar():
    auditoria.registrar("login_ok", "a", "")
    auditoria.esquecer_cache()                                           # como se o servidor tivesse reiniciado
    auditoria.registrar("login_ok", "b", "")
    assert auditoria.verificar_corrente()["linhas"] == 2 and auditoria.verificar_corrente()["integra"]


# ───────────────────────────── política de perfis ─────────────────────────────

@pytest.mark.parametrize("metodo,caminho,perfil", [
    ("GET", "/web/api/turmas/lista", "consulta"), ("GET", "/web/api/configuracoes/escola", "consulta"),
    ("GET", "/web/api/configuracoes/gmail", "admin"), ("GET", "/web/api/whatsapp/qr.svg", "admin"),
    ("POST", "/web/api/automacoes/turmas/executar", "operador"), ("POST", "/web/api/avisos/modelos", "operador"),
    ("POST", "/web/api/configuracoes/gmail", "admin"), ("POST", "/web/api/configuracoes/data-corte", "admin"),
    ("POST", "/web/api/configuracoes/ano-letivo", "operador"), ("POST", "/web/api/configuracoes/ano-letivo/restaurar", "admin"),
    ("POST", "/web/api/configuracoes/mapeamento-turmas-qr/testar", "operador"),
    ("POST", "/web/api/wizard/escola/executar", "admin"), ("POST", "/web/api/sistema/escolher-pasta", "admin"),
    ("POST", "/web/api/whatsapp/provedor", "admin"), ("POST", "/web/api/whatsapp/enviar", "operador"),
    ("GET", "/web/api/seguranca/usuarios", "admin"), ("DELETE", "/web/api/seguranca/usuarios/u_1", "admin"),
    ("GET", "/web/api/seguranca/auditoria", "admin"), ("POST", "/web/api/seguranca/trocar-senha", "consulta"),
    ("DELETE", "/web/api/planilhas/3", "operador"), ("PUT", "/web/api/qualquer/coisa/nova", "operador"),
    ("GET", "/web/api/qualquer/coisa/nova", "consulta"),
])
def test_politica_de_perfis(metodo, caminho, perfil):
    assert politica.perfil_exigido(metodo, caminho) == perfil

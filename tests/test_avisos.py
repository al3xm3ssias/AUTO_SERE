"""avisos: comunicados oficiais por e-mail (escola → escolas, escola → pais) — só simular e teste."""
import email
import json
import time
from email.header import decode_header, make_header
from pathlib import Path

import pytest

from src.automacao import avisos as av
from src.comum import credenciais, escola, paths
from src.comum import registro_scripts as reg
from src.comum.opcoes_execucao import Opcoes
from src.web.api import rotas
from src.web.app import create_app

PROPRIA = "Escola Municipal Profª Judith Macedo Silveira"

ESCOLAS = {
    "escolas-municipais": {"url": "x", "quantidade": 6, "escolas": [
        {"nome": PROPRIA, "endereco": "R. A", "ramal": "1", "email": "judith@pontagrossa.pr.gov.br"},
        {"nome": "Escola Municipal Ana Néri", "endereco": "", "ramal": "", "email": "ana@pg.gov.br; Ana.Secretaria@PG.gov.br"},
        {"nome": "Escola Municipal Rural São José", "endereco": "", "ramal": "", "email": "sj@pg.gov.br"},
        {"nome": "Escola Municipal Sem Email", "endereco": "", "ramal": "", "email": ""},
        {"nome": "Escola Municipal Repetida", "endereco": "", "ramal": "", "email": "ana@pg.gov.br"},
        {"nome": "Escola Municipal Lixo", "endereco": "", "ramal": "", "email": "ligar na secretaria"},
    ]},
    "cmeis-2": {"url": "y", "quantidade": 1, "escolas": [
        {"nome": "CMEI Pequeno Príncipe", "endereco": "", "ramal": "", "email": "cmei1@pg.gov.br"}]},
}

PRE = {
    "atualizado_em": "2026-10-01T10:00:00",
    "turmas_intencao": {
        "Infantil IV": [
            {"cpf": "111", "nome": "ANA LIMA", "situacao": "Matriculado"},
            {"cpf": "112", "nome": "BETO LIMA", "situacao": "Matriculado"},
            {"cpf": "113", "nome": "CAIO PAIVA", "situacao": ""},
            {"cpf": "114", "nome": "DUDA ROCHA", "situacao": "Cancelado. Motivo: Responsável desistiu"},
        ],
        "1º Ano do Ensino Fundamental": [
            {"cpf": "115", "nome": "EDU DIAS", "situacao": "MATRICULADO"},
            {"cpf": "116", "nome": "FABI SOUZA", "situacao": "Matriculado", "substituido_por_nova_tentativa": True},
            {"cpf": "117", "nome": "GIGI NUNES", "situacao": "", "matriculado_em": "2026-02-01"},
            {"cpf": "118", "nome": "HUGO MELO", "situacao": "Matriculado"},
            {"cpf": "119", "nome": "IVO SEM CAD", "situacao": "Matriculado"},
        ],
    },
    "cadastros": {
        "111": {"nome_responsavel": "MARIA LIMA", "email": "mae@x.com"},
        "112": {"nome_responsavel": "MARIA LIMA", "email": "mae@x.com"},
        "113": {"nome_responsavel": "JOAO PAIVA", "email": "pai@x.com"},
        "114": {"nome_responsavel": "RITA ROCHA", "email": "cancelado@x.com"},
        "115": {"nome_responsavel": "EDNA DIAS", "email": "edu@x.com"},
        "116": {"nome_responsavel": "FABIO SOUZA", "email": "fabio@x.com"},
        "117": {"nome_responsavel": "GILDA NUNES", "email": "gigi@x.com"},
        "118": {"nome_responsavel": "HELENA MELO", "email": ""},
    },
}


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    dados = tmp_path / "dados" / "2026"
    dados.mkdir(parents=True)
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    (dados / "escolas_completas.json").write_text(json.dumps(ESCOLAS), encoding="utf-8")
    (dados / "pre_matricula.json").write_text(json.dumps(PRE), encoding="utf-8")
    monkeypatch.setattr(escola, "nome", lambda: PROPRIA)
    monkeypatch.setattr(credenciais, "EMAIL_REMETENTE", "escola@gmail.com")
    monkeypatch.setattr(credenciais, "EMAIL_SENHA_APP", "abcdabcdabcdabcd")
    return tmp_path


@pytest.fixture()
def smtp(monkeypatch):
    """Troca o envio real; qualquer chamada fica registrada."""
    chamadas = []

    def falso(destinatario, assunto, corpo, remetente=None, senha_app=None):
        chamadas.append({"para": destinatario, "assunto": assunto, "corpo": corpo})
        return True, None
    monkeypatch.setattr("src.automacao.envia_email.enviar_email", falso)
    return chamadas


# ───────────── utilitários ─────────────

def test_extrair_emails():
    assert av.extrair_emails("A@x.com; b@Y.com.br / a@x.com , lixo, c@z") == ["a@x.com", "b@y.com.br"]
    assert av.extrair_emails("ligar na secretaria") == [] and av.extrair_emails(None) == []


@pytest.mark.parametrize("texto,ok", [("a@b.com", True), (" a@b.com ", True), ("a@b", False), ("a b@c.com", False),
                                      ("a@b.com,c@d.com", False), ("", False), (None, False), ("a@b.com\nBcc: x@y.com", False)])
def test_email_valido(texto, ok):
    assert av.email_valido(texto) is ok


@pytest.mark.parametrize("candidata,propria,esperado", [
    ("Escola Municipal Profª Judith Macedo Silveira", PROPRIA, True),
    ("Judith Macedo Silveira", PROPRIA, True),
    ("E. M. PROF. JUDITH MACEDO SILVEIRA", PROPRIA, True),
    ("Escola Municipal Ana Néri", PROPRIA, False),
    ("Escola Municipal Macedo Soares", PROPRIA, False),
    ("Escola Municipal Judith", PROPRIA, False),           # só 1 palavra em comum: é outra escola
])
def test_reconhece_a_propria_escola(candidata, propria, esperado):
    assert av._e_a_propria_escola(candidata, propria) is esperado


# ───────────── público: escolas ─────────────

def test_escolas_padrao(amb):
    r = av.destinatarios_escolas()
    assert [(d["nome"], d["email"]) for d in r["destinatarios"]] == [
        ("Escola Municipal Ana Néri", "ana@pg.gov.br"), ("Escola Municipal Ana Néri", "ana.secretaria@pg.gov.br"),
        ("Escola Municipal Rural São José", "sj@pg.gov.br"), ("CMEI Pequeno Príncipe", "cmei1@pg.gov.br")]
    assert r["excluidas"] == [PROPRIA]                                       # a própria escola nunca recebe
    assert r["sem_email"] == ["Escola Municipal Sem Email", "Escola Municipal Lixo"]
    assert r["destinatarios"][0]["contexto"] == {"ESCOLA_DESTINO": "Escola Municipal Ana Néri"}


def test_escolas_nao_repete_email(amb):
    emails = [d["email"] for d in av.destinatarios_escolas()["destinatarios"]]
    assert emails.count("ana@pg.gov.br") == 1                                # "Repetida" tem o mesmo e-mail da Ana Néri


def test_escolas_exclui_quem_tem_o_email_do_remetente(amb, monkeypatch):
    monkeypatch.setattr(credenciais, "EMAIL_REMETENTE", "sj@pg.gov.br")
    r = av.destinatarios_escolas()
    assert "Escola Municipal Rural São José" in r["excluidas"]


def test_escolas_por_tipo(amb):
    assert [d["nome"] for d in av.destinatarios_escolas("cmeis")["destinatarios"]] == ["CMEI Pequeno Príncipe"]
    nomes = {d["nome"] for d in av.destinatarios_escolas("escolas")["destinatarios"]}
    assert "CMEI Pequeno Príncipe" not in nomes and "Escola Municipal Ana Néri" in nomes


def test_escolas_filtro_por_nome_sem_acento_nem_caixa(amb):
    assert [d["nome"] for d in av.destinatarios_escolas(filtro_nome="sao JOSE")["destinatarios"]] == ["Escola Municipal Rural São José"]
    assert av.destinatarios_escolas(filtro_nome="inexistente")["destinatarios"] == []


def test_escolas_sem_arquivo_ou_ilegivel(amb):
    arq = paths.dados_ano_atual() / "escolas_completas.json"
    arq.write_text("{x", encoding="utf-8")
    with pytest.raises(ValueError, match="ilegível"):
        av.destinatarios_escolas()
    arq.unlink()
    with pytest.raises(ValueError, match="Coleta e-mails"):
        av.destinatarios_escolas()


# ───────────── público: pais ─────────────

@pytest.mark.parametrize("situacao,esperado", [("Matriculado", "matriculado"), ("MATRICULADO EM 02/02", "matriculado"),
                                               ("Cancelado. Motivo: x", "cancelado"), ("", "aguardando"), (None, "aguardando"),
                                               ("Em análise", "outra")])
def test_situacao_do_aluno(situacao, esperado):
    assert av.situacao_do_aluno({"situacao": situacao}) == esperado


def test_situacao_matriculado_pela_data():
    assert av.situacao_do_aluno({"situacao": "", "matriculado_em": "2026-02-01"}) == "matriculado"


def test_pais_matriculados_um_email_por_responsavel(amb):
    r = av.destinatarios_pais("matriculados")
    por_email = {d["email"]: d for d in r["destinatarios"]}
    assert set(por_email) == {"mae@x.com", "edu@x.com", "gigi@x.com"}
    mae = por_email["mae@x.com"]
    assert mae["nome"] == "MARIA LIMA"
    assert mae["contexto"] == {"RESPONSAVEL": "MARIA LIMA", "ALUNO": "ANA LIMA e BETO LIMA", "TURMA": "Infantil IV"}
    assert por_email["edu@x.com"]["contexto"]["TURMA"] == "1º Ano"          # " do Ensino Fundamental" some
    assert r["alunos"] == 6                                                  # ana, beto, edu, gigi, hugo, ivo
    assert r["sem_email"] == ["HUGO MELO (1º Ano do Ensino Fundamental)",
                              "IVO SEM CAD (1º Ano do Ensino Fundamental) — sem cadastro consultado"]


def test_pais_nunca_inclui_cancelado_nem_tentativa_substituida(amb):
    emails = {d["email"] for d in av.destinatarios_pais("ambos")["destinatarios"]}
    assert "cancelado@x.com" not in emails and "fabio@x.com" not in emails


def test_pais_aguardando_e_ambos(amb):
    assert [d["email"] for d in av.destinatarios_pais("aguardando")["destinatarios"]] == ["pai@x.com"]
    assert {d["email"] for d in av.destinatarios_pais("ambos")["destinatarios"]} == {"mae@x.com", "edu@x.com", "gigi@x.com", "pai@x.com"}


def test_pais_sem_arquivo_ou_ilegivel(amb):
    arq = paths.dados_ano_atual() / "pre_matricula.json"
    arq.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="formato esperado"):
        av.destinatarios_pais()
    arq.unlink()
    with pytest.raises(ValueError, match="'Pré-matrícula'"):
        av.destinatarios_pais()


# ───────────── marcadores ─────────────

def test_marcadores_por_publico():
    assert av.marcadores_validos("escolas") == ("ESCOLA", "ANO", "DATA", "ESCOLA_DESTINO")
    assert av.marcadores_validos("pais") == ("ESCOLA", "ANO", "DATA", "RESPONSAVEL", "ALUNO", "TURMA")


def test_marcador_desconhecido_e_recusado_com_a_lista():
    av.conferir_marcadores("Olá $RESPONSAVEL, custa $5 em $ESCOLA", "pais", "Mensagem")
    with pytest.raises(ValueError, match=r"Mensagem: marcador\(es\) desconhecido\(s\) \$NOME.*\$RESPONSAVEL"):
        av.conferir_marcadores("Olá $NOME", "pais", "Mensagem")
    with pytest.raises(ValueError, match=r"\$ALUNOS"):                          # plural não vira $ALUNO + "S"
        av.conferir_marcadores("$ALUNOS", "pais", "Assunto")
    with pytest.raises(ValueError, match=r"\$RESPONSAVEL"):                    # marcador de pais não vale para escolas
        av.conferir_marcadores("$RESPONSAVEL", "escolas", "Assunto")


def test_renderizar_troca_so_o_que_conhece():
    assert av.renderizar("Oi $A e $B $C", {"A": "1", "B": "2"}) == "Oi 1 e 2 $C"


# ───────────── validação ─────────────

def _ok(**kw):
    base = dict(publico="escolas", canal="email", modo="simular", assunto="Aviso $ESCOLA", mensagem="Olá $ESCOLA_DESTINO")
    base.update(kw)
    return base


def test_validar_ok_e_normaliza(amb):
    p = av.validar_pedido(**_ok(assunto="  Aviso  ", tipo_escola=None, email_teste=None))
    assert p["assunto"] == "Aviso" and p["tipo_escola"] == "todas" and p["situacao_pais"] == "matriculados"


@pytest.mark.parametrize("kw,trecho", [
    (dict(publico=""), "para quem"),
    (dict(publico="todos"), "para quem"),
    (dict(canal="whatsapp"), "ainda não existe"),
    (dict(modo="enviar"), "ainda não foi liberado"),
    (dict(modo="real"), "ainda não foi liberado"),
    (dict(assunto="  "), "assunto"),
    (dict(assunto="Oi\nBcc: x@y.com"), "uma linha só"),
    (dict(assunto="x" * 201), "passa de 200"),
    (dict(mensagem=""), "Escreva a mensagem"),
    (dict(mensagem="x" * 20001), "passa de 20000"),
    (dict(mensagem="Olá $NOME"), "desconhecido"),
    (dict(assunto="$RESPONSAVEL"), "desconhecido"),
    (dict(tipo_escola="todas2"), "Tipo de escola"),
    (dict(publico="pais", mensagem="x", situacao_pais="todos"), "Situação inválida"),
])
def test_validar_recusa(amb, kw, trecho):
    with pytest.raises(ValueError, match=trecho):
        av.validar_pedido(**_ok(**kw))


def test_validar_escola_usada_sem_nome_da_escola(amb, monkeypatch):
    monkeypatch.setattr(escola, "nome", lambda: "")
    with pytest.raises(ValueError, match="nome da escola"):
        av.validar_pedido(**_ok())
    av.validar_pedido(**_ok(assunto="Aviso", mensagem="Olá $ESCOLA_DESTINO"))   # $ESCOLA_DESTINO não é $ESCOLA


def test_validar_modo_teste(amb, monkeypatch):
    p = av.validar_pedido(**_ok(modo="teste"))
    assert p["email_teste"] == "claudioalex16@gmail.com"                          # escolas: a escola fictícia de teste
    p = av.validar_pedido(**_ok(modo="teste", publico="pais", mensagem="Olá $RESPONSAVEL"))
    assert p["email_teste"] == "escola@gmail.com"                                # pais: o remetente
    assert av.validar_pedido(**_ok(modo="teste", email_teste=" Eu@Mail.com "))["email_teste"] == "eu@mail.com"
    with pytest.raises(ValueError, match="não parece um endereço"):
        av.validar_pedido(**_ok(modo="teste", email_teste="sem-arroba"))
    with pytest.raises(ValueError, match="não parece um endereço"):
        av.validar_pedido(**_ok(modo="teste", email_teste="a@b.com\nBcc: x@y.com"))
    monkeypatch.setattr(credenciais, "EMAIL_SENHA_APP", "senha_app_email")
    with pytest.raises(ValueError, match="Senha do Gmail"):
        av.validar_pedido(**_ok(modo="teste"))
    av.validar_pedido(**_ok(modo="simular"))                                     # simular não precisa de credenciais


def test_sem_destinatarios(amb):
    with pytest.raises(ValueError, match="Nenhum destinatário"):
        av.reunir_destinatarios("escolas", filtro_nome="inexistente")


# ───────────── montagem ─────────────

def test_montar_mensagens(amb):
    dest = [{"nome": "X", "email": "x@x.com", "contexto": {"ESCOLA_DESTINO": "Escola\nA   B"}}]
    m = av.montar_mensagens(dest, "Aviso de $ESCOLA - $ANO", "Para $ESCOLA_DESTINO em $DATA ($ANO)")[0]
    assert m["para"] == "x@x.com" and m["assunto"] == f"Aviso de {PROPRIA} - 2026"
    assert m["corpo"].startswith("Para Escola A B em ") and "\n" not in m["corpo"]      # quebra de linha de dado raspado some
    assert len(m["corpo"].split(" em ")[1].split(" ")[0]) == 10                          # dd/mm/aaaa


# ───────────── execução: simular e teste ─────────────

def _args(**kw):
    base = dict(publico="pais", canal="email", modo="simular", assunto="Matrícula de $ALUNO",
                mensagem="Olá, $RESPONSAVEL!\n\nA matrícula de $ALUNO ($TURMA) em $ESCOLA está confirmada.")
    base.update(kw)
    return base


def test_simular_nao_envia_nada_e_grava_registro(amb, smtp, capsys):
    r = av.executar_avisos(**_args())
    assert smtp == []                                                            # nenhum e-mail saiu
    assert r["modo"] == "simular" and r["total"] == 3 and r["simulados"] == 3 and r["enviados_teste"] == 0
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO — nada será enviado" in saida and "MARIA LIMA <mae@x.com>" in saida
    assert "Sem e-mail válido (2)" in saida and "PRÉVIA — mensagem 1 de 3" in saida
    assert "A matrícula de ANA LIMA e BETO LIMA (Infantil IV)" in saida
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert Path(r["registro"]).parent == paths.dados_ano_atual() / "AVISOS" and r["registro"].endswith("_pais_simular.json")
    assert registro["total"] == 3 and registro["enviados_teste"] == 0 and registro["modo"] == "simular"
    assert [m["para"] for m in registro["mensagens"]] == ["mae@x.com", "edu@x.com", "gigi@x.com"]
    assert "ANA LIMA e BETO LIMA" in registro["mensagens"][0]["corpo"]


def test_simular_escolas(amb, smtp, capsys):
    r = av.executar_avisos(**_args(publico="escolas", assunto="Comunicado", mensagem="Prezada direção da $ESCOLA_DESTINO"))
    assert smtp == [] and r["total"] == 4
    saida = capsys.readouterr().out
    assert f"Fora da lista (a própria escola): {PROPRIA}" in saida and "Prezada direção da Escola Municipal Ana Néri" in saida


def test_teste_envia_um_so_para_o_endereco_de_teste(amb, smtp):
    r = av.executar_avisos(**_args(modo="teste", email_teste="eu@mail.com"))
    assert len(smtp) == 1
    e = smtp[0]
    assert e["para"] == "eu@mail.com"                                            # nunca para mae@x.com & cia.
    assert e["assunto"] == "[TESTE] Matrícula de ANA LIMA e BETO LIMA"
    assert e["corpo"].startswith("*** TESTE — esta mensagem NÃO foi enviada aos destinatários reais. ***")
    assert "iria para 3 destinatário(s)" in e["corpo"] and "MARIA LIMA <mae@x.com>" in e["corpo"]
    assert "Olá, MARIA LIMA!" in e["corpo"]
    assert r["enviados_teste"] == 1 and r["simulados"] == 0 and r["modo"] == "teste"
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert r["registro"].endswith("_pais_teste.json") and registro["email_teste"] == "eu@mail.com" and registro["enviados_teste"] == 1


def test_teste_usa_o_remetente_por_padrao(amb, smtp):
    av.executar_avisos(**_args(modo="teste"))
    assert smtp[0]["para"] == "escola@gmail.com"


def test_falha_no_smtp_vira_erro_e_nao_grava_registro(amb, monkeypatch):
    monkeypatch.setattr("src.automacao.envia_email.enviar_email", lambda *a, **k: (False, "Authentication failed"))
    with pytest.raises(RuntimeError, match="Authentication failed"):
        av.executar_avisos(**_args(modo="teste"))
    assert not (paths.dados_ano_atual() / "AVISOS").exists()


def test_modo_real_nao_existe(amb, smtp):
    with pytest.raises(ValueError, match="ainda não foi liberado"):
        av.executar_avisos(**_args(modo="enviar"))
    assert smtp == [] and not (paths.dados_ano_atual() / "AVISOS").exists()


def test_lista_longa_e_resumida_no_log(amb, smtp, capsys):
    dados = paths.dados_ano_atual()
    escolas = [{"nome": f"Escola Municipal Teste {i:03d}", "email": f"e{i}@pg.gov.br"} for i in range(80)]
    (dados / "escolas_completas.json").write_text(json.dumps({"escolas-municipais": {"escolas": escolas}}), encoding="utf-8")
    r = av.executar_avisos(**_args(publico="escolas", assunto="Aviso", mensagem="Oi $ESCOLA_DESTINO"))
    assert r["total"] == 80
    assert "… e mais 20" in capsys.readouterr().out
    assert len(json.loads(Path(r["registro"]).read_text(encoding="utf-8"))["mensagens"]) == 80   # o registro tem todos


def test_cancelamento(amb, smtp, monkeypatch):
    from src.comum.execucao_gui import CancelamentoSolicitado
    def cancelar(): raise CancelamentoSolicitado()
    monkeypatch.setattr(av, "verificar_cancelamento", cancelar)
    with pytest.raises(CancelamentoSolicitado):
        av.executar_avisos(**_args(modo="teste"))
    assert smtp == []


def test_enviar_email_existente_codifica_acentos(monkeypatch):
    """O envio real usa enviar_email; confere que assunto e corpo com acentos saem corretos."""
    from src.automacao import envia_email
    capturado = {}

    class SMTPFalso:
        def __init__(self, *a): pass
        def starttls(self): pass
        def login(self, *a): pass
        def sendmail(self, de, para, texto): capturado.update(de=de, para=para, texto=texto)
        def quit(self): pass
    monkeypatch.setattr(envia_email.smtplib, "SMTP", SMTPFalso)
    ok, erro = envia_email.enviar_email("x@x.com", "Aviso à família: matrícula", "Olá, atenção às orientações.", "a@b.com", "senha")
    assert ok and erro is None
    msg = email.message_from_string(capturado["texto"])
    assert str(make_header(decode_header(msg["Subject"]))) == "Aviso à família: matrícula"
    assert "atenção às orientações" in msg.get_payload()[0].get_payload(decode=True).decode("utf-8")


# ───────────── registro, CLI e web ─────────────

def test_registrada(amb):
    s = reg.obter("avisos")
    assert s is not None and "avisos" not in rotas.AUTOMACOES_NAO_IMPLEMENTADAS and s.confirmar is False
    nomes = [e["nome"] for e in s.extras()]
    assert nomes == ["publico", "canal", "modo", "tipo_escola", "filtro_nome", "situacao_pais", "assunto", "mensagem", "email_teste"]
    mensagem = next(e for e in s.extras() if e["nome"] == "mensagem")
    assert mensagem["multilinha"] is True
    modos = next(e for e in s.extras() if e["nome"] == "modo")
    assert [o["valor"] for o in modos["opcoes"]] == ["simular", "teste"] and modos["padrao"] == "simular"
    publico = next(e for e in s.extras() if e["nome"] == "publico")
    assert "$RESPONSAVEL" in next(o for o in publico["opcoes"] if o["valor"] == "pais")["ajuda"]


def test_plano(amb):
    p = {"publico": "pais", "assunto": "A", "mensagem": "B", "modo": "teste", "email_teste": "x@y.com"}
    plano = reg.obter("avisos").planejar(Opcoes(), p, {}, {})
    assert plano.tipo == "sync" and plano.funcao is av.executar_avisos
    assert plano.kwargs["modo"] == "teste" and plano.kwargs["canal"] == "email" and plano.kwargs["situacao_pais"] == "matriculados"


def test_validar_extras_do_registro(amb):
    v = reg.obter("avisos").validar_extras
    v({"publico": "pais", "assunto": "A", "mensagem": "B"})
    with pytest.raises(ValueError, match="assunto"):
        v({"publico": "pais", "mensagem": "B"})
    with pytest.raises(ValueError, match="Nenhum destinatário"):
        v({"publico": "escolas", "assunto": "A", "mensagem": "B", "filtro_nome": "zzz"})


def test_cli_simular(amb, capsys):
    from src.comum import cli
    assert cli.main(["avisos", "--publico", "pais", "--assunto", "A", "--mensagem", "B", "--simular"]) == 0
    assert "executar_avisos" in capsys.readouterr().out
    assert cli.main(["avisos", "--publico", "pais", "--assunto", "A", "--mensagem", "B", "--modo", "enviar"]) == 2


@pytest.fixture()
def web(amb, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: paths.dados_ano_atual())
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


def _esperar(web):
    for _ in range(300):
        s = web.get("/web/api/automacoes/avisos/status").get_json()
        if s["status"] != "executando":
            return s
        time.sleep(0.05)
    raise AssertionError("não terminou")


def test_web_simula_pelo_botao(web, smtp):
    r = web.post("/web/api/automacoes/avisos/executar", json={
        "publico": "escolas", "canal": "email", "modo": "simular", "assunto": "Comunicado", "mensagem": "Olá, $ESCOLA_DESTINO"})
    assert r.status_code == 200
    s = _esperar(web)
    assert s["status"] == "concluido" and smtp == []
    assert rotas._EXECUCOES["avisos"]["resultado"]["total"] == 4
    assert any("SIMULAÇÃO — nada será enviado" in linha for linha in s["logs"])


def test_web_pedido_ruim_da_400(web):
    r = web.post("/web/api/automacoes/avisos/executar", json={"publico": "pais", "assunto": "", "mensagem": "x"})
    assert r.status_code == 400 and "assunto" in r.get_json()["mensagem"]
    r = web.post("/web/api/automacoes/avisos/executar", json={"publico": "pais", "assunto": "a", "mensagem": "Oi $NOME"})
    assert r.status_code == 400 and "desconhecido" in r.get_json()["mensagem"]


def test_web_componentes_trazem_os_campos(web):
    d = web.get("/web/api/automacoes/avisos/componentes").get_json()
    assert d["registrado"] is True
    assert {e["nome"] for e in d["extras"]} >= {"publico", "modo", "assunto", "mensagem"}


def test_tela_tem_textarea_e_nao_tem_mais_o_formulario_legado():
    js = (Path(__file__).resolve().parent.parent / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert "campo.multilinha" in js and "<textarea" in js and "#campos-automacao textarea" in js
    legado = js[js.index("const CAMPOS_AUTOMACAO"):js.index("const CAMPOS_PADRAO")]
    assert "avisos" not in legado


def test_previa_conta_destinatarios_sem_exigir_o_texto(web):
    def previa(payload):
        return web.post("/web/api/automacoes/avisos/previa", json=payload)
    r = previa({})                                                      # ainda sem escolher o público: sem aviso nenhum
    assert r.status_code == 200 and r.get_json()["texto"] is None
    d = previa({"publico": "escolas"}).get_json()["texto"]
    assert d.startswith("4 e-mail(s) de escolas e CMEIs; 2 sem e-mail válido ficariam de fora") and "Simular ou Teste" in d
    assert previa({"publico": "escolas", "tipo_escola": "cmeis"}).get_json()["texto"].startswith("1 e-mail(s)")
    d = previa({"publico": "pais"}).get_json()["texto"]
    assert d.startswith("3 responsável(is) por e-mail, de 6 aluno(s) novo(s); 2 sem e-mail válido")
    assert previa({"publico": "pais", "situacao_pais": "aguardando"}).get_json()["texto"].startswith("1 responsável(is)")


def test_previa_avisa_quando_falta_a_lista(web, amb):
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    r = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas"})
    assert r.status_code == 400 and "Coleta e-mails" in r.get_json()["erro"]
    r = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas", "filtro_nome": "zzz"})
    assert r.status_code == 400


# ───────────── escola fictícia no modo teste das escolas ─────────────

NOME_FICTICIA = "ESCOLA MUNICIPAL TESTE DA SILVA"
EMAIL_FICTICIA = "claudioalex16@gmail.com"


def _args_escolas(**kw):
    base = dict(publico="escolas", canal="email", modo="teste", assunto="Comunicado oficial - $ESCOLA",
                mensagem="Prezada direção da $ESCOLA_DESTINO,\n\nSegue o comunicado oficial da $ESCOLA.")
    base.update(kw)
    return base


def test_a_escola_ficticia_existe_com_os_dados_pedidos():
    assert av.ESCOLA_TESTE == {"nome": NOME_FICTICIA, "email": EMAIL_FICTICIA}


def test_teste_das_escolas_envia_para_a_escola_ficticia(amb, smtp):
    r = av.executar_avisos(**_args_escolas())
    assert len(smtp) == 1
    e = smtp[0]
    assert e["para"] == EMAIL_FICTICIA                                           # chega na caixa da escola fictícia
    assert e["assunto"] == f"[TESTE] Comunicado oficial - {PROPRIA}"
    assert e["corpo"].startswith("*** TESTE — esta mensagem NÃO foi enviada aos destinatários reais. ***")
    assert f"Prezada direção da {NOME_FICTICIA}," in e["corpo"]                  # texto como a escola receberia
    assert f"escola fictícia de teste: {NOME_FICTICIA} <{EMAIL_FICTICIA}>" in e["corpo"]
    assert "iria para 4 destinatário(s) reais" in e["corpo"]
    reais = {d["email"] for d in av.destinatarios_escolas()["destinatarios"]}
    assert e["para"] not in reais and "Escola Municipal Ana Néri" not in e["corpo"]
    assert r["enviados_teste"] == 1 and r["total"] == 4
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert registro["escola_teste"] == {"nome": NOME_FICTICIA, "email": EMAIL_FICTICIA} and registro["email_teste"] == EMAIL_FICTICIA


def test_teste_das_escolas_funciona_sem_a_lista_coletada(amb, smtp, capsys):
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    r = av.executar_avisos(**_args_escolas())
    assert len(smtp) == 1 and smtp[0]["para"] == EMAIL_FICTICIA and r["total"] == 0 and r["enviados_teste"] == 1
    assert "iria para 0 destinatário(s) reais" in smtp[0]["corpo"]
    saida = capsys.readouterr().out
    assert "Coleta e-mails" in saida and "o teste com a escola fictícia segue mesmo assim" in saida


def test_simular_continua_exigindo_a_lista_real(amb, smtp):
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    with pytest.raises(ValueError, match="Coleta e-mails"):
        av.executar_avisos(**_args_escolas(modo="simular"))
    assert smtp == []


def test_teste_das_escolas_com_outro_email_mantem_o_nome_ficticio(amb, smtp):
    av.executar_avisos(**_args_escolas(email_teste="outro@mail.com"))
    assert smtp[0]["para"] == "outro@mail.com" and f"direção da {NOME_FICTICIA}" in smtp[0]["corpo"]


def test_a_escola_ficticia_nunca_entra_na_lista_real_nem_na_simulacao(amb, smtp):
    emails = {d["email"] for d in av.destinatarios_escolas()["destinatarios"]}
    nomes = {d["nome"] for d in av.destinatarios_escolas()["destinatarios"]}
    assert EMAIL_FICTICIA not in emails and NOME_FICTICIA not in nomes
    r = av.executar_avisos(**_args_escolas(modo="simular"))
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert EMAIL_FICTICIA not in {m["para"] for m in registro["mensagens"]} and registro["escola_teste"] is None
    assert smtp == []


def test_simular_escolas_avisa_para_onde_iria_o_teste(amb, smtp, capsys):
    av.executar_avisos(**_args_escolas(modo="simular"))
    assert f"No modo Teste, o e-mail iria para a escola fictícia {NOME_FICTICIA} <{EMAIL_FICTICIA}>." in capsys.readouterr().out


def test_teste_dos_pais_nao_mudou(amb, smtp):
    av.executar_avisos(**_args(modo="teste"))
    assert smtp[0]["para"] == "escola@gmail.com" and "ESCOLA MUNICIPAL TESTE" not in smtp[0]["corpo"]


def test_validar_extras_do_teste_das_escolas_dispensa_a_lista(amb):
    v = reg.obter("avisos").validar_extras
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    v({"publico": "escolas", "modo": "teste", "assunto": "A", "mensagem": "B"})
    with pytest.raises(ValueError, match="Coleta e-mails"):
        v({"publico": "escolas", "modo": "simular", "assunto": "A", "mensagem": "B"})


def test_previa_do_teste_das_escolas(web):
    d = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas", "modo": "teste"}).get_json()["texto"]
    assert d == (f"Teste: 1 e-mail para a escola fictícia {NOME_FICTICIA} <{EMAIL_FICTICIA}> "
                 "(o comunicado real iria para 4 e-mail(s) de escolas e CMEIs).")
    d = web.post("/web/api/automacoes/avisos/previa",
                 json={"publico": "escolas", "modo": "teste", "email_teste": "x@y.com"}).get_json()["texto"]
    assert "<x@y.com>" in d


def test_previa_do_teste_das_escolas_sem_a_lista(web):
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    r = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas", "modo": "teste"})
    assert r.status_code == 200 and r.get_json()["texto"] == f"Teste: 1 e-mail para a escola fictícia {NOME_FICTICIA} <{EMAIL_FICTICIA}>."


def test_web_teste_das_escolas_pelo_botao(web, smtp):
    r = web.post("/web/api/automacoes/avisos/executar", json={
        "publico": "escolas", "canal": "email", "modo": "teste", "assunto": "Comunicado", "mensagem": "Olá, $ESCOLA_DESTINO"})
    assert r.status_code == 200
    s = _esperar(web)
    assert s["status"] == "concluido" and len(smtp) == 1 and smtp[0]["para"] == EMAIL_FICTICIA
    assert any("E-mail de teste enviado para claudioalex16@gmail.com" in linha for linha in s["logs"])


def test_ajuda_do_modo_teste_cita_a_escola_ficticia(amb):
    modo = next(e for e in reg.obter("avisos").extras() if e["nome"] == "modo")
    assert NOME_FICTICIA in next(o for o in modo["opcoes"] if o["valor"] == "teste")["ajuda"]

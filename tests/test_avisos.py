"""avisos: comunicados oficiais por e-mail (escola → escolas, escola → pais) — só simular e teste."""
import email
import json
import time
from datetime import datetime, timedelta
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
    ("JUDITH M SILVEIRA,E M PROFA-EI EF", PROPRIA, True),  # como a Base ABC escreve: inicial solta e o que vem depois da vírgula
    ("JUDITH MACEDO SILVEIRA,E M PROFA-EF", PROPRIA, True),
    ("ANA NERI,E M-EF", PROPRIA, False),
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
    assert av.marcadores_validos("escolas") == ("ESCOLA", "ANO", "DATA", "ESCOLA_DESTINO", "ALUNO", "CGM", "SERIE", "TURMA")
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
    base = dict(publico="escolas", canal="email", modo="simular", assunto="Aviso $ESCOLA", mensagem="Olá $ESCOLA_DESTINO, sobre $ALUNO")
    base.update(kw)
    return base


def test_validar_ok_e_normaliza(amb):
    p = av.validar_pedido(**_ok(assunto="  Aviso  ", tipo_escola=None, email_teste=None))
    assert p["assunto"] == "Aviso" and p["tipo_escola"] == "todas" and p["situacao_pais"] == "matriculados"


@pytest.mark.parametrize("kw,trecho", [
    (dict(publico=""), "para quem"),
    (dict(publico="todos"), "para quem"),
    (dict(canal="whatsapp"), "ainda não existe"),
    (dict(modo="real"), "Modo inválido"),
    (dict(fonte="outra"), "Fonte dos alunos"),
    (dict(unidades=["@todos-os-cmeis"]), "Grupo de unidades desconhecido"),
    (dict(intervalo_s=1), "Intervalo entre e-mails"),
    (dict(intervalo_s="abc"), "número inteiro"),
    (dict(limite_lote=0), "Máximo de e-mails por execução"),
    (dict(limite_lote=501), "Máximo de e-mails por execução"),
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
    av.validar_pedido(**_ok(assunto="Aviso", mensagem="Olá $ESCOLA_DESTINO, sobre $ALUNO"))   # $ESCOLA_DESTINO não é $ESCOLA


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
    with pytest.raises(ValueError, match="Nenhum aluno novo"):
        av.reunir_destinatarios("escolas", filtro_nome="inexistente", por_aluno=True)


# ───────────── NÃO existe aviso em massa para escolas (decisão de 23/11/2026) ─────────────

@pytest.mark.parametrize("modo", ["simular", "teste", "enviar"])
def test_escolas_sem_marcador_de_aluno_nunca_vira_aviso_em_massa(amb, smtp, modo):
    with pytest.raises(ValueError, match="não existe aviso em massa"):
        av.executar_avisos(**_args(publico="escolas", modo=modo, assunto="Comunicado", mensagem="Prezada direção da $ESCOLA_DESTINO"))
    assert smtp == [] and not (paths.dados_ano_atual() / "AVISOS").exists()


def test_so_o_marcador_da_escola_nao_basta_para_escolas(amb):
    for texto in ("Para $ESCOLA_DESTINO", "Aviso de $ESCOLA em $DATA", "Sem marcador nenhum"):
        with pytest.raises(ValueError, match="um por aluno"):
            av.validar_pedido(**_ok(assunto="Aviso", mensagem=texto))


@pytest.mark.parametrize("marcador", ["$ALUNO", "$CGM", "$SERIE", "$TURMA"])
def test_cada_marcador_de_aluno_libera_o_texto_para_escolas(amb, marcador):
    p = av.validar_pedido(**_ok(assunto="Aviso", mensagem=f"Pedido {marcador}"))
    assert p["por_aluno"] is True


def test_escolas_nunca_tem_destinatarios_sem_ser_por_aluno(amb):
    with pytest.raises(ValueError, match="não existe aviso em massa"):
        av.reunir_destinatarios("escolas")                                    # a lista real de escolas existe e não é usada
    with pytest.raises(ValueError, match="não existe aviso em massa"):
        av.reunir_destinatarios("escolas", unidades=["@todas"], por_aluno=False)


def test_exemplo_da_mensagem_de_escolas_sem_marcador_so_avisa(amb):
    r = av.exemplo_da_mensagem("escolas", "Aviso", "Para $ESCOLA_DESTINO")
    assert "não existe aviso em massa" in r["aviso"] and "corpo" not in r


def test_modelo_para_escolas_exige_marcador_de_aluno(amb, monkeypatch, tmp_path):
    from src.comum import modelos_avisos as ma
    with pytest.raises(ValueError, match="aviso em massa"):
        ma._validar("Meu modelo", "escolas", "Aviso", "Olá $ESCOLA_DESTINO")
    assert ma._validar("Meu modelo", "escolas", "Aviso", "Olá, $ALUNO")[1] == "escolas"
    assert ma._validar("Meu modelo", "", "Aviso", "Olá")[1] == ""             # sem público definido: a trava vale na hora de enviar


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


def test_envio_real_sem_simulacao_antes_e_recusado(amb, smtp):
    with pytest.raises(ValueError, match="rode o modo .Simular."):
        av.executar_avisos(**_args(modo="enviar"))
    assert smtp == [] and not (paths.dados_ano_atual() / "AVISOS").exists()


def test_lista_longa_e_resumida_no_log(amb, smtp, capsys):
    dados = paths.dados_ano_atual()
    alunos = [{"cpf": f"9{i:03d}", "nome": f"ALUNO {i:03d}", "situacao": "Matriculado"} for i in range(80)]
    cadastros = {a["cpf"]: {"nome_responsavel": f"RESP {i:03d}", "email": f"r{i}@x.com"} for i, a in enumerate(alunos)}
    (dados / "pre_matricula.json").write_text(
        json.dumps({"turmas_intencao": {"Infantil IV": alunos}, "cadastros": cadastros}), encoding="utf-8")
    r = av.executar_avisos(**_args(publico="pais", assunto="Aviso", mensagem="Oi $RESPONSAVEL"))
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
    assert nomes == ["publico", "canal", "modo", "unidades", "situacao_pais", "fonte", "alunos", "tipo_mensagem", "modelo_acoes",
                     "assunto", "mensagem", "exemplo_mensagem", "intervalo_s", "limite_lote", "enviados_registro"]
    assert "filtro_nome" not in nomes and "email_teste" not in nomes                  # saíram da tela a pedido
    mensagem = next(e for e in s.extras() if e["nome"] == "mensagem")
    assert mensagem["multilinha"] is True
    modos = next(e for e in s.extras() if e["nome"] == "modo")
    assert [o["valor"] for o in modos["opcoes"]] == ["simular", "teste", "enviar"] and modos["padrao"] == "simular"
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
    with pytest.raises(ValueError, match="não existe aviso em massa"):
        v({"publico": "escolas", "assunto": "A", "mensagem": "B", "filtro_nome": "zzz"})
    with pytest.raises(ValueError, match="Nenhum aluno novo"):
        v({"publico": "escolas", "assunto": "A $ALUNO", "mensagem": "B", "filtro_nome": "zzz"})


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
        "publico": "pais", "canal": "email", "modo": "simular", "assunto": "Comunicado", "mensagem": "Olá, $RESPONSAVEL"})
    assert r.status_code == 200
    s = _esperar(web)
    assert s["status"] == "concluido" and smtp == []
    assert rotas._EXECUCOES["avisos"]["resultado"]["total"] == 3
    assert any("SIMULAÇÃO — nada será enviado" in linha for linha in s["logs"])


def test_web_escolas_sem_marcador_de_aluno_da_400_e_nao_executa(web, smtp):
    for modo in ("simular", "teste", "enviar"):
        r = web.post("/web/api/automacoes/avisos/executar", json={
            "publico": "escolas", "canal": "email", "modo": modo, "assunto": "Comunicado", "mensagem": "Olá, $ESCOLA_DESTINO"})
        assert r.status_code == 400 and "não existe aviso em massa" in r.get_json()["mensagem"]
    assert smtp == []


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
    d = previa({"publico": "escolas"}).get_json()["texto"]                 # escolas sem texto: nunca conta "todas as escolas"
    assert "um por aluno" in d and "não existe aviso em massa" in d
    assert "um por aluno" in previa({"publico": "escolas", "assunto": "Aviso", "mensagem": "Para $ESCOLA_DESTINO"}).get_json()["texto"]
    d = previa({"publico": "pais"}).get_json()["texto"]
    assert d.startswith("3 responsável(is) por e-mail, de 6 aluno(s) novo(s); sem e-mail ficariam de fora 2:")
    assert previa({"publico": "pais", "situacao_pais": "aguardando"}).get_json()["texto"].startswith("1 responsável(is)")


def test_previa_das_escolas_conta_um_email_por_aluno(web, chegando):
    d = web.post("/web/api/automacoes/avisos/previa",
                 json={"publico": "escolas", "assunto": "Transferência de $ALUNO", "mensagem": "Aluno $ALUNO"}).get_json()["texto"]
    assert d.startswith("2 e-mail(s) para escolas de origem, um por aluno que chega")


def test_previa_avisa_quando_falta_a_lista(web, amb):
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    com_texto = {"publico": "escolas", "assunto": "Transferência de $ALUNO", "mensagem": "Aluno $ALUNO"}
    r = web.post("/web/api/automacoes/avisos/previa", json=com_texto)
    assert r.status_code == 400 and "Coleta e-mails" in r.get_json()["erro"]
    r = web.post("/web/api/automacoes/avisos/previa", json={**com_texto, "filtro_nome": "zzz"})
    assert r.status_code == 400


# ───────────── escola fictícia no modo teste das escolas ─────────────

NOME_FICTICIA = "ESCOLA MUNICIPAL TESTE DA SILVA"
EMAIL_FICTICIA = "claudioalex16@gmail.com"


def _args_escolas(**kw):
    base = dict(publico="escolas", canal="email", modo="teste", assunto="Comunicado oficial - $ESCOLA",
                mensagem="Prezada direção da $ESCOLA_DESTINO,\n\nSegue o comunicado oficial da $ESCOLA sobre o aluno $ALUNO.")
    base.update(kw)
    return base


def test_a_escola_ficticia_existe_com_os_dados_pedidos():
    assert av.ESCOLA_TESTE == {"nome": NOME_FICTICIA, "email": EMAIL_FICTICIA}


def test_teste_das_escolas_envia_para_a_escola_ficticia(chegando, smtp):
    r = av.executar_avisos(**_args_escolas())
    assert len(smtp) == 1
    e = smtp[0]
    assert e["para"] == EMAIL_FICTICIA                                           # chega na caixa da escola fictícia
    assert e["assunto"] == f"[TESTE] Comunicado oficial - {PROPRIA}"
    assert e["corpo"].startswith("*** TESTE — esta mensagem NÃO foi enviada aos destinatários reais. ***")
    assert f"Prezada direção da {NOME_FICTICIA}," in e["corpo"]                  # texto como a escola receberia
    assert f"escola fictícia de teste: {NOME_FICTICIA} <{EMAIL_FICTICIA}>" in e["corpo"]
    assert "iria para 2 destinatário(s) reais" in e["corpo"]
    reais = {d["email"] for d in av.destinatarios_escolas()["destinatarios"]}
    assert e["para"] not in reais and "Escola Municipal Ana Néri" not in e["corpo"]
    assert r["enviados_teste"] == 1 and r["total"] == 2
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


def test_a_escola_ficticia_nunca_entra_na_lista_real_nem_na_simulacao(chegando, smtp):
    emails = {d["email"] for d in av.destinatarios_escolas()["destinatarios"]}
    nomes = {d["nome"] for d in av.destinatarios_escolas()["destinatarios"]}
    assert EMAIL_FICTICIA not in emails and NOME_FICTICIA not in nomes
    r = av.executar_avisos(**_args_escolas(modo="simular"))
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert EMAIL_FICTICIA not in {m["para"] for m in registro["mensagens"]} and registro["escola_teste"] is None
    assert smtp == []


def test_simular_escolas_avisa_para_onde_iria_o_teste(chegando, smtp, capsys):
    av.executar_avisos(**_args_escolas(modo="simular"))
    assert f"No modo Teste, o e-mail iria para a escola fictícia {NOME_FICTICIA} <{EMAIL_FICTICIA}>." in capsys.readouterr().out


def test_teste_dos_pais_nao_mudou(amb, smtp):
    av.executar_avisos(**_args(modo="teste"))
    assert smtp[0]["para"] == "escola@gmail.com" and "ESCOLA MUNICIPAL TESTE" not in smtp[0]["corpo"]


def test_validar_extras_do_teste_das_escolas_dispensa_a_lista(amb):
    v = reg.obter("avisos").validar_extras
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    v({"publico": "escolas", "modo": "teste", "assunto": "A $ALUNO", "mensagem": "B"})
    with pytest.raises(ValueError, match="Coleta e-mails"):
        v({"publico": "escolas", "modo": "simular", "assunto": "A $ALUNO", "mensagem": "B"})


def test_previa_do_teste_das_escolas(web, chegando):
    texto = {"publico": "escolas", "modo": "teste", "assunto": "Pedido de $ALUNO", "mensagem": "Aluno $ALUNO"}
    d = web.post("/web/api/automacoes/avisos/previa", json=texto).get_json()["texto"]
    assert d == (f"Teste: 1 e-mail para a escola fictícia {NOME_FICTICIA} <{EMAIL_FICTICIA}> "
                 "(o comunicado real iria para 2 e-mail(s) de escolas de origem).")
    d = web.post("/web/api/automacoes/avisos/previa", json={**texto, "email_teste": "x@y.com"}).get_json()["texto"]
    assert "<x@y.com>" in d


def test_previa_do_teste_das_escolas_sem_a_lista(web):
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    r = web.post("/web/api/automacoes/avisos/previa",
                 json={"publico": "escolas", "modo": "teste", "assunto": "Pedido de $ALUNO", "mensagem": "Aluno $ALUNO"})
    assert r.status_code == 200 and r.get_json()["texto"] == f"Teste: 1 e-mail para a escola fictícia {NOME_FICTICIA} <{EMAIL_FICTICIA}>."


def test_web_teste_das_escolas_pelo_botao(web, smtp):
    r = web.post("/web/api/automacoes/avisos/executar", json={
        "publico": "escolas", "canal": "email", "modo": "teste", "assunto": "Comunicado", "mensagem": "Olá, $ESCOLA_DESTINO, sobre $ALUNO"})
    assert r.status_code == 200
    s = _esperar(web)
    assert s["status"] == "concluido" and len(smtp) == 1 and smtp[0]["para"] == EMAIL_FICTICIA
    assert any("E-mail de teste enviado para claudioalex16@gmail.com" in linha for linha in s["logs"])


def test_ajuda_do_modo_teste_cita_a_escola_ficticia(amb):
    modo = next(e for e in reg.obter("avisos").extras() if e["nome"] == "modo")
    assert NOME_FICTICIA in next(o for o in modo["opcoes"] if o["valor"] == "teste")["ajuda"]


# ═════════════ só quem chega: unidades, escola de origem, fonte, envio real ═════════════

def _vinc(escola, cgm="1025059227", turma="5º ano", status="ok", **extra):
    return {"vinculo_base_abc": {"periodo": "ano_vigente", "nome": "X", "cgm": cgm, "turma": turma, "escola": escola,
                                 "situacao": "Matriculado", "status": status, **extra}}


@pytest.fixture()
def chegando(amb):
    """Alunos novos com o vínculo da Base ABC (escola de origem) gravado, como a 'Consulta na Base ABC' deixa."""
    pre = json.loads(json.dumps(PRE))
    cad = pre["cadastros"]
    cad["111"].update(_vinc("ESCOLA MUNICIPAL ANA NERI", cgm="1000000001", turma="5º ano"))               # → ana@
    cad["112"].update(_vinc("Escola Municipal Rural São José", cgm="1000000002", turma="3º ano"))          # → sj@
    cad["115"].update(_vinc("ESCOLA MUNICIPAL SEM EMAIL", cgm="1000000005"))                              # escola sem e-mail
    cad["117"].update(_vinc("COLEGIO PARTICULAR XYZ", cgm="1000000007"))                                  # fora da lista
    cad["118"].update(_vinc("ESCOLA MUNICIPAL ANA NERI", cgm="1000000008", status="verificar", motivo="sem linha de 2026"))
    pre["turmas_intencao"]["1º Ano do Ensino Fundamental"][4]["vinculo_base_abc"] = _vinc(      # IVO: só no item da turma
        "Escola Municipal Profª Judith Macedo Silveira", cgm="1000000009")["vinculo_base_abc"]
    (paths.dados_ano_atual() / "pre_matricula.json").write_text(json.dumps(pre), encoding="utf-8")
    return pre


TRANSF = dict(publico="escolas", assunto="Transferência de $ALUNO",
              mensagem="Aluno $ALUNO, CGM $CGM, série $SERIE, vai para a turma $TURMA de $ESCOLA para $ESCOLA_DESTINO.")


def test_normalizar_unidades():
    assert av.normalizar_unidades(None) is None and av.normalizar_unidades([]) is None and av.normalizar_unidades("") is None
    assert av.normalizar_unidades(["@todas", "Escola X"]) is None
    assert av.normalizar_unidades(["@cmeis", "  Escola  Municipal Ana Néri "]) == (frozenset({"@cmeis"}), frozenset({"escola municipal ana neri"}))
    assert av.normalizar_unidades('["Escola A", "@escolas"]') == (frozenset({"@escolas"}), frozenset({"escola a"}))
    assert av.normalizar_unidades("Escola Única") == (frozenset(), frozenset({"escola unica"}))
    with pytest.raises(ValueError, match="Grupo de unidades desconhecido: @outras"):
        av.normalizar_unidades(["@outras"])


def test_listar_unidades_sem_a_propria_escola_em_ordem(amb):
    u = av.listar_unidades()
    assert PROPRIA not in [x["nome"] for x in u]
    assert [x["nome"] for x in u] == sorted([x["nome"] for x in u], key=lambda n: av._sem_acento(n))
    por_nome = {x["nome"]: x for x in u}
    assert por_nome["CMEI Pequeno Príncipe"]["tipo"] == "cmei" and por_nome["Escola Municipal Ana Néri"]["tipo"] == "escola"
    assert por_nome["Escola Municipal Sem Email"]["tem_email"] is False and por_nome["Escola Municipal Ana Néri"]["tem_email"] is True


def test_quais_unidades_filtra_por_nome_e_por_grupo(amb):
    nomes = lambda **kw: sorted({d["nome"] for d in av.destinatarios_escolas(**kw)["destinatarios"]})
    assert nomes(unidades=["Escola Municipal Ana Néri"]) == ["Escola Municipal Ana Néri"]
    assert [d["email"] for d in av.destinatarios_escolas(unidades=["escola municipal ana neri"])["destinatarios"]] == ["ana@pg.gov.br", "ana.secretaria@pg.gov.br"]
    assert nomes(unidades=["@cmeis"]) == ["CMEI Pequeno Príncipe"]
    assert nomes(unidades=["@cmeis", "Escola Municipal Rural São José"]) == ["CMEI Pequeno Príncipe", "Escola Municipal Rural São José"]
    assert "CMEI Pequeno Príncipe" not in nomes(unidades=["@escolas"])
    assert len(nomes(unidades=["@todas"])) == len(nomes())                         # @todas = sem filtro


def test_alunos_que_chegam_vao_para_a_escola_de_origem_um_email_por_aluno(chegando):
    r = av.destinatarios_alunos_origem()
    por_aluno = {d["contexto"]["ALUNO"]: d for d in r["destinatarios"]}
    assert set(por_aluno) == {"ANA LIMA", "BETO LIMA"}
    ana = por_aluno["ANA LIMA"]
    assert ana["email"] == "ana@pg.gov.br"                                          # a escola tem 2 e-mails: vai o primeiro
    assert ana["contexto"] == {"ESCOLA_DESTINO": "Escola Municipal Ana Néri", "ALUNO": "ANA LIMA", "CGM": "1000000001",
                               "SERIE": "5º ano", "TURMA": "Infantil IV"}
    assert por_aluno["BETO LIMA"]["email"] == "sj@pg.gov.br" and por_aluno["BETO LIMA"]["contexto"]["SERIE"] == "3º ano"
    assert r["alunos"] == 6 and r["sem_vinculo"] == []                                # CAIO (aguardando) não entra em "matriculados"
    assert r["origem_desconhecida"] == ["GIGI NUNES (1º Ano) — COLEGIO PARTICULAR XYZ"]
    assert len(r["a_verificar"]) == 1 and r["a_verificar"][0].startswith("HUGO MELO (1º Ano) — sem linha de 2026")
    assert r["da_propria_escola"] == ["IVO SEM CAD (1º Ano)"]                         # o vínculo veio do item da turma, sem cadastro
    assert r["sem_email"] == ["Escola Municipal Sem Email (aluno EDU DIAS)"]


def test_aluno_sem_vinculo_da_base_abc_nao_recebe_e_e_listado(chegando):
    r = av.destinatarios_alunos_origem("ambos")
    assert r["sem_vinculo"] == ["CAIO PAIVA (Infantil IV)"] and r["alunos"] == 7


def test_unidades_escolhidas_tambem_filtram_os_alunos(chegando):
    r = av.destinatarios_alunos_origem(unidades=["Escola Municipal Ana Néri"])
    assert [d["contexto"]["ALUNO"] for d in r["destinatarios"]] == ["ANA LIMA"] and r["fora_da_selecao"] == 2       # BETO e EDU: outras escolas de origem
    assert av.destinatarios_alunos_origem(unidades=["@cmeis"])["destinatarios"] == []


def test_origem_so_vale_se_for_a_unica_parecida(chegando):
    unidades = [{"nome": "Escola Municipal Ana Néri Norte", "eh_cmei": False, "emails": ["n@x.com"]},
                {"nome": "Escola Municipal Ana Néri Sul", "eh_cmei": False, "emails": ["s@x.com"]}]
    assert av._achar_unidade("Escola Municipal Ana Néri", unidades) is None          # duas parecidas: não adivinha
    assert av._achar_unidade("Escola Municipal Ana Néri Sul", unidades)["emails"] == ["s@x.com"]
    assert av._achar_unidade("Ana Néri Norte", unidades)["emails"] == ["n@x.com"]    # sem 'Escola Municipal': ainda é igual


def test_nenhum_aluno_com_escola_de_origem_explica_o_motivo(amb):
    with pytest.raises(ValueError, match=r"Nenhum aluno novo com escola de origem e e-mail.*6 aluno\(s\) novo\(s\) lido\(s\).*6 sem o vínculo da Base ABC"):
        av.reunir_destinatarios("escolas", por_aluno=True)


def test_texto_com_marcador_de_aluno_vira_um_email_por_aluno(chegando, smtp, capsys):
    r = av.executar_avisos(**_args(**TRANSF))
    assert smtp == [] and r["total"] == 2
    saida = capsys.readouterr().out
    assert "um e-mail por aluno que chega, para a escola de origem" in saida
    assert "Escola Municipal Ana Néri <ana@pg.gov.br> — aluno ANA LIMA" in saida
    assert "Sem e-mail válido (1)" in saida and "Escola de origem fora da lista de escolas (não recebem) (1)" in saida
    assert "Vínculo da Base ABC a verificar (não recebem) (1)" in saida and "Já estão na nossa escola (não recebem) (1)" in saida
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert registro["filtros"]["por_aluno"] is True and registro["mensagens"][0]["aluno"] == "ANA LIMA"
    assert "chave" not in registro["mensagens"][0]
    corpo = registro["mensagens"][0]["corpo"]
    assert corpo == f"Aluno ANA LIMA, CGM 1000000001, série 5º ano, vai para a turma Infantil IV de {PROPRIA} para Escola Municipal Ana Néri."


def test_texto_sem_marcador_de_aluno_nao_segue_um_email_por_escola(chegando, smtp):
    with pytest.raises(ValueError, match="não existe aviso em massa"):
        av.executar_avisos(**_args(publico="escolas", assunto="Aviso", mensagem="Para $ESCOLA_DESTINO"))
    assert smtp == []


def test_teste_por_aluno_monta_o_texto_com_o_primeiro_aluno_real(chegando, smtp):
    r = av.executar_avisos(**_args(**TRANSF, modo="teste"))
    assert r["enviados_teste"] == 1 and smtp[0]["para"] == EMAIL_FICTICIA
    assert smtp[0]["assunto"] == "[TESTE] Transferência de ANA LIMA"
    assert f"para {NOME_FICTICIA}." in smtp[0]["corpo"] and "CGM 1000000001" in smtp[0]["corpo"]


def test_teste_por_aluno_sem_nenhum_aluno_ainda_envia_com_a_escola_ficticia(amb, smtp):
    r = av.executar_avisos(**_args(**TRANSF, modo="teste"))
    assert r["enviados_teste"] == 1 and "$ALUNO" in smtp[0]["assunto"]             # sem aluno real, o marcador fica à vista


def _previsao(amb, cadastros, turmas):
    (paths.dados_ano_atual() / "previsao_alunos_2027.json").write_text(
        json.dumps({"cadastros": cadastros, "turmas_intencao": turmas}), encoding="utf-8")


def test_pais_podem_vir_da_previsao_do_proximo_ano(amb):
    _previsao(amb, {"211": {"nome_responsavel": "PAULA NOVA", "email": "paula@x.com"},
                    "111": {"nome_responsavel": "MARIA LIMA", "email": "mae@x.com"}},
              {"Infantil V": [{"cpf": "211", "nome": "NINA NOVA", "situacao": "Matriculado"},
                              {"cpf": "111", "nome": "ANA LIMA", "situacao": "Matriculado"}]})   # ANA já está na pré-matrícula
    ano = av.destinatarios_pais("matriculados", "ano")
    proximo = av.destinatarios_pais("matriculados", "proximo")
    ambas = av.destinatarios_pais("matriculados", "ambas")
    assert sorted(d["email"] for d in proximo["destinatarios"]) == ["mae@x.com", "paula@x.com"]
    assert len(ano["destinatarios"]) == 3 and proximo["alunos"] == 2
    emails = {d["email"]: d["contexto"] for d in ambas["destinatarios"]}
    assert set(emails) == {"mae@x.com", "edu@x.com", "gigi@x.com", "paula@x.com"}
    assert emails["mae@x.com"]["ALUNO"] == "ANA LIMA e BETO LIMA"                   # ANA não repete: mesmo CPF nos dois arquivos
    assert ambas["alunos"] == 7                                                      # 6 da pré-matrícula + NINA (ANA não conta 2 vezes)


def test_fonte_sem_o_arquivo_pede_a_automacao(amb):
    with pytest.raises(ValueError, match="previsao_alunos_2027.json"):
        av.destinatarios_pais("matriculados", "proximo")
    assert len(av.destinatarios_pais("matriculados", "ambas")["destinatarios"]) == 3   # com "ambas", basta um existir
    (paths.dados_ano_atual() / "pre_matricula.json").unlink()
    with pytest.raises(ValueError, match="pre_matricula.json"):
        av.destinatarios_pais("matriculados", "ano")


def test_arquivo_ilegivel_nunca_e_ignorado_com_ambas(amb):
    (paths.dados_ano_atual() / "pre_matricula.json").write_text("{ quebrado", encoding="utf-8")
    _previsao(amb, {}, {})
    with pytest.raises(ValueError):
        av.destinatarios_pais("matriculados", "ambas")


# ───────────── envio real ─────────────

@pytest.fixture()
def sem_espera(monkeypatch):
    """Troca a pausa entre e-mails (senão cada teste esperaria segundos) e anota quantas pausas houve."""
    pausas = []
    monkeypatch.setattr(av, "_esperar", lambda s: pausas.append(s))
    return pausas


def _simular_e_enviar(**kw):
    av.executar_avisos(**_args(**TRANSF, **{k: v for k, v in kw.items() if k in ("unidades",)}))
    return av.executar_avisos(**_args(**TRANSF, modo="enviar", **kw))


def test_envio_real_depois_da_simulacao_envia_com_pausa_e_registra(chegando, smtp, sem_espera):
    r = _simular_e_enviar(intervalo_s=7)
    assert r["enviados"] == 2 and r["falhas"] == 0 and r["ja_enviados"] == 0 and r["restantes"] == 0 and r["modo"] == "enviar"
    assert [e["para"] for e in smtp] == ["ana@pg.gov.br", "sj@pg.gov.br"]
    assert not any(e["assunto"].startswith("[TESTE]") for e in smtp) and "TESTE" not in smtp[0]["corpo"]
    assert smtp[0]["assunto"] == "Transferência de ANA LIMA"
    assert sem_espera == [7]                                                       # uma pausa entre os 2 (não depois do último)
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert r["registro"].endswith("_escolas_enviar.json") and registro["estado"] == "concluído"
    assert [e["aluno"] for e in registro["enviados"]] == ["ANA LIMA", "BETO LIMA"] and registro["falhas"] == []
    enviados = json.loads((paths.dados_ano_atual() / "AVISOS" / "enviados.json").read_text(encoding="utf-8"))["envios"]
    assert len(enviados) == 2 and {v["para"] for v in enviados.values()} == {"ana@pg.gov.br", "sj@pg.gov.br"}


def test_envio_real_exige_simulacao_do_mesmo_comunicado(chegando, smtp, sem_espera):
    av.executar_avisos(**_args(**TRANSF))                                          # simulou
    with pytest.raises(ValueError, match="simule de novo"):
        av.executar_avisos(**_args(**{**TRANSF, "mensagem": TRANSF["mensagem"] + " Obrigado."}, modo="enviar"))
    with pytest.raises(ValueError, match="rode o modo .Simular."):
        av.executar_avisos(**_args(**TRANSF, modo="enviar", unidades=["Escola Municipal Ana Néri"]))   # outra lista de destinatários
    assert smtp == []


def test_simulacao_velha_demais_nao_vale(chegando, smtp, sem_espera):
    av.executar_avisos(**_args(**TRANSF))
    arq = paths.dados_ano_atual() / "AVISOS" / "previas.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    dados["previas"] = {h: (datetime.now() - timedelta(hours=25)).isoformat() for h in dados["previas"]}
    arq.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(ValueError, match="rode o modo .Simular."):
        av.executar_avisos(**_args(**TRANSF, modo="enviar"))
    assert smtp == []


def test_rodar_de_novo_nao_manda_outra_vez_para_quem_ja_recebeu(chegando, smtp, sem_espera):
    _simular_e_enviar()
    smtp.clear()
    r = av.executar_avisos(**_args(**TRANSF, modo="enviar"))                       # a prévia de 24 h ainda vale
    assert smtp == [] and r["enviados"] == 0 and r["ja_enviados"] == 2


def test_limite_por_execucao_e_continua_na_proxima(chegando, smtp, sem_espera):
    av.executar_avisos(**_args(**TRANSF))
    r1 = av.executar_avisos(**_args(**TRANSF, modo="enviar", limite_lote=1))
    assert r1["enviados"] == 1 and r1["restantes"] == 1 and [e["para"] for e in smtp] == ["ana@pg.gov.br"]
    r2 = av.executar_avisos(**_args(**TRANSF, modo="enviar", limite_lote=1))
    assert r2["enviados"] == 1 and r2["ja_enviados"] == 1 and r2["restantes"] == 0
    assert [e["para"] for e in smtp] == ["ana@pg.gov.br", "sj@pg.gov.br"]          # ninguém recebeu 2 vezes


def test_tres_falhas_seguidas_param_o_envio_sem_marcar_como_enviado(chegando, monkeypatch, sem_espera):
    pre = json.loads((paths.dados_ano_atual() / "pre_matricula.json").read_text(encoding="utf-8"))
    for cpf, escola_origem, cgm in (("115", "Escola Municipal Rural São José", "1000000015"),
                                    ("117", "CMEI Pequeno Príncipe", "1000000017"),
                                    ("118", "ESCOLA MUNICIPAL ANA NERI", "1000000018")):
        pre["cadastros"][cpf].update(_vinc(escola_origem, cgm=cgm))                 # agora são 5 alunos com escola de origem
    (paths.dados_ano_atual() / "pre_matricula.json").write_text(json.dumps(pre), encoding="utf-8")
    av.executar_avisos(**_args(publico="escolas", assunto="Aviso $ALUNO", mensagem="Para $ESCOLA_DESTINO"))
    tentativas = []
    monkeypatch.setattr("src.automacao.envia_email.enviar_email",
                        lambda *a, **k: (tentativas.append(a[0]) or (False, "autenticação recusada")))
    with pytest.raises(RuntimeError, match="3 falhas seguidas.*autenticação recusada"):
        av.executar_avisos(**_args(publico="escolas", assunto="Aviso $ALUNO", mensagem="Para $ESCOLA_DESTINO", modo="enviar"))
    assert len(tentativas) == 3                                                     # parou, não insistiu nos 5 destinos
    pasta = paths.dados_ano_atual() / "AVISOS"
    assert not (pasta / "enviados.json").exists()
    registro = json.loads(next(pasta.glob("*_escolas_enviar.json")).read_text(encoding="utf-8"))
    assert registro["estado"] == "interrompido por falhas" and len(registro["falhas"]) == 3 and registro["enviados"] == []


def test_uma_falha_isolada_nao_derruba_os_outros(chegando, monkeypatch, sem_espera):
    av.executar_avisos(**_args(**TRANSF))
    enviados = []

    def envio(destino, assunto, corpo, **kw):
        if destino == "ana@pg.gov.br":
            return False, "caixa cheia"
        enviados.append(destino)
        return True, None
    monkeypatch.setattr("src.automacao.envia_email.enviar_email", envio)
    r = av.executar_avisos(**_args(**TRANSF, modo="enviar"))
    assert r["enviados"] == 1 and r["falhas"] == 1 and enviados == ["sj@pg.gov.br"]
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert registro["falhas"][0]["erro"] == "caixa cheia" and registro["estado"] == "concluído"
    # a falha NÃO entra no registro de enviados: na próxima execução ela é tentada de novo
    enviados.clear()
    monkeypatch.setattr("src.automacao.envia_email.enviar_email", lambda d, a, c, **k: (enviados.append(d) or (True, None)))
    r2 = av.executar_avisos(**_args(**TRANSF, modo="enviar"))
    assert enviados == ["ana@pg.gov.br"] and r2["ja_enviados"] == 1


def test_cancelar_no_meio_guarda_o_que_ja_saiu(chegando, smtp, monkeypatch):
    av.executar_avisos(**_args(**TRANSF))
    chamadas = {"n": 0}

    class Cancelado(Exception):
        pass

    def verificar():
        chamadas["n"] += 1
        if len(smtp) >= 1:                                   # cancelou logo depois do 1º e-mail
            raise Cancelado()
    monkeypatch.setattr(av, "verificar_cancelamento", verificar)
    monkeypatch.setattr(av, "_esperar", lambda s: verificar())
    with pytest.raises(Cancelado):
        av.executar_avisos(**_args(**TRANSF, modo="enviar"))
    assert [e["para"] for e in smtp] == ["ana@pg.gov.br"]
    pasta = paths.dados_ano_atual() / "AVISOS"
    assert len(json.loads((pasta / "enviados.json").read_text(encoding="utf-8"))["envios"]) == 1
    registro = json.loads(next(pasta.glob("*_escolas_enviar.json")).read_text(encoding="utf-8"))
    assert registro["estado"] == "interrompido" and len(registro["enviados"]) == 1 and len(registro["restantes"]) == 1
    monkeypatch.undo()                                       # voltar a rodar continua só com quem faltou


# ───────────── tela: prévia com a lista de quem fica de fora, confirmação, rotas e modelos ─────────────

def test_previa_do_texto_de_transferencia_mostra_escolas_de_origem_e_quem_fica_de_fora(web, chegando):
    d = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas", **{k: TRANSF[k] for k in ("assunto", "mensagem")}}).get_json()["texto"]
    assert d.startswith("2 e-mail(s) para escolas de origem, um por aluno que chega (de 6 aluno(s) novo(s))")
    assert "sem e-mail ficariam de fora 1: Escola Municipal Sem Email (aluno EDU DIAS)" in d
    assert "1 aluno(s) com vínculo a verificar" in d and "1 aluno(s) com escola de origem fora da lista: GIGI NUNES" in d


def test_previa_avisa_aluno_sem_vinculo_da_base_abc(web, amb):
    r = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas", "assunto": "A", "mensagem": "$ALUNO"})
    assert r.status_code == 400 and "6 sem o vínculo da Base ABC" in r.get_json()["erro"]


def test_previa_do_envio_real_bloqueia_sem_simulacao_e_libera_depois(web, chegando, smtp, sem_espera):
    pedido = {"publico": "escolas", "modo": "enviar", **{k: TRANSF[k] for k in ("assunto", "mensagem")}, "limite_lote": "1"}
    r = web.post("/web/api/automacoes/avisos/previa", json=pedido)
    assert r.status_code == 400 and "rode o modo" in r.get_json()["erro"]
    av.executar_avisos(**_args(**TRANSF))                                              # simula
    d = web.post("/web/api/automacoes/avisos/previa", json=pedido).get_json()["texto"]
    assert "ENVIO REAL: 1 e-mail(s) nesta execução" in d
    av.executar_avisos(**_args(**TRANSF, modo="enviar", limite_lote=1))                 # manda 1
    d = web.post("/web/api/automacoes/avisos/previa", json=pedido).get_json()["texto"]
    assert "(1 já enviado(s) antes não repetem)" in d


def test_validar_extras_do_envio_real_exige_a_simulacao(chegando):
    s = reg.obter("avisos")
    p = {"publico": "escolas", "modo": "enviar", **{k: TRANSF[k] for k in ("assunto", "mensagem")}}
    with pytest.raises(ValueError, match="rode o modo"):
        s.validar_extras(p)
    av.executar_avisos(**_args(**TRANSF))
    s.validar_extras(p)                                                                 # agora passa


def test_envio_real_pede_confirmacao_so_no_modo_enviar(web):
    info = web.get("/web/api/automacoes/avisos/componentes").get_json()
    assert info["confirmar"] is False and info["confirmar_quando"] == {"campo": "modo", "valor": "enviar"}
    assert "ENVIA e-mails de verdade" in info["aviso_confirmacao"]
    outra = web.get("/web/api/automacoes/turmas/componentes").get_json()
    assert outra.get("confirmar_quando") is None


def test_plano_leva_unidades_fonte_pausa_limite_e_tipo_de_mensagem(amb):
    p = {"publico": "escolas", "assunto": "A $ALUNO", "mensagem": "B", "modo": "enviar", "unidades": '["@cmeis"]', "fonte": "ambas",
         "intervalo_s": "20", "limite_lote": "25", "tipo_mensagem": "transferencia"}
    k = reg.obter("avisos").planejar(Opcoes(), p, {}, {}).kwargs
    assert (k["unidades"], k["fonte"], k["intervalo_s"], k["limite_lote"], k["modelo"]) == ('["@cmeis"]', "ambas", "20", "25", "transferencia")
    assert av.validar_pedido(**{x: k[x] for x in k if x != "modelo"})["intervalo_s"] == 20


def test_tela_tem_o_tipo_de_mensagem_com_os_modelos_e_sem_os_campos_removidos(amb):
    extras = {e["nome"]: e for e in reg.obter("avisos").extras()}
    tipo = extras["tipo_mensagem"]
    assert [o["valor"] for o in tipo["opcoes"]][:2] == ["livre", "transferencia"] and tipo["padrao"] == "livre"
    transf = next(o for o in tipo["opcoes"] if o["valor"] == "transferencia")
    assert transf["publico"] == "escolas" and "$ALUNO" in transf["assunto"] and "$CGM" in transf["mensagem"] and "$SERIE" in transf["mensagem"]
    assert "SME" in transf["mensagem"] and "histórico escolar" in transf["mensagem"] and "SERE" in transf["mensagem"]
    assert extras["assunto"].get("placeholder") is None                                 # sem o exemplo no campo
    assert extras["unidades"]["tipo"] == "unidades" and [g["valor"] for g in extras["unidades"]["grupos"]] == ["@todas", "@escolas", "@cmeis"]
    assert extras["fonte"]["padrao"] == "ambas" and {o["valor"] for o in extras["fonte"]["opcoes"]} == {"ano", "proximo", "ambas"}
    assert extras["intervalo_s"]["visivelSe"] == {"campo": "campo-modo-aviso", "valor": "enviar"} == extras["limite_lote"]["visivelSe"]


def test_rota_de_unidades(web, amb):
    r = web.get("/web/api/avisos/unidades").get_json()
    assert PROPRIA not in [u["nome"] for u in r["unidades"]] and r["unidades"][0]["nome"] == "CMEI Pequeno Príncipe"
    (paths.dados_ano_atual() / "escolas_completas.json").unlink()
    r = web.get("/web/api/avisos/unidades").get_json()
    assert r["unidades"] == [] and "Coleta e-mails" in r["aviso"]


@pytest.fixture()
def modelos(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    return tmp_path / "config" / "modelos_avisos.json"


def test_rotas_de_modelos_criar_ajustar_restaurar_excluir(web, amb, modelos):
    ids = lambda r: [m["id"] for m in r["modelos"]]
    assert ids(web.get("/web/api/avisos/modelos").get_json()) == ["livre", "transferencia", "transferencia_destino", "chamada_matricula"]
    r = web.post("/web/api/avisos/modelos", json={"nome": "Documentos pendentes", "publico": "pais",
                                                 "assunto": "Documentos de $ALUNO", "mensagem": "Olá $RESPONSAVEL, faltam documentos de $ALUNO."})
    assert r.status_code == 200 and r.get_json()["modelo"]["id"] == "documentos-pendentes"
    assert ids(r.get_json()) == ["livre", "transferencia", "transferencia_destino", "chamada_matricula", "documentos-pendentes"]
    # ajustar um pronto: a versão ajustada vale no lugar da original
    r = web.post("/web/api/avisos/modelos", json={"id": "transferencia", "nome": "Transferência de aluno (pedir à escola de origem)",
                                                 "publico": "escolas", "assunto": "Transferência $ALUNO", "mensagem": "Ajustado: $ALUNO $CGM"})
    assert r.get_json()["modelo"]["personalizado"] is True and r.get_json()["modelo"]["padrao"] is True
    assert next(o for o in reg.obter("avisos").extras() if o["nome"] == "tipo_mensagem")["opcoes"][1]["mensagem"] == "Ajustado: $ALUNO $CGM"
    r = web.delete("/web/api/avisos/modelos/transferencia")
    assert r.get_json()["acao"] == "restaurado" and "SME" in next(m for m in r.get_json()["modelos"] if m["id"] == "transferencia")["mensagem"]
    assert web.delete("/web/api/avisos/modelos/transferencia").status_code == 400            # pronto sem ajuste: nada a excluir
    r = web.delete("/web/api/avisos/modelos/documentos-pendentes")
    assert r.get_json()["acao"] == "excluido" and ids(r.get_json()) == ["livre", "transferencia", "transferencia_destino", "chamada_matricula"]
    assert web.delete("/web/api/avisos/modelos/nao-existe").status_code == 400


@pytest.mark.parametrize("corpo,trecho", [
    ({"nome": "", "assunto": "A", "mensagem": "B"}, "Dê um nome"),
    ({"nome": "X", "assunto": "A", "mensagem": ""}, "Escreva a mensagem"),
    ({"nome": "X", "assunto": "A\nB", "mensagem": "B"}, "uma linha só"),
    ({"nome": "X", "assunto": "A", "mensagem": "Olá $NOME"}, "marcador"),
    ({"nome": "X", "publico": "pais", "assunto": "A", "mensagem": "$CGM"}, "marcador"),       # $CGM só existe para escolas
    ({"nome": "X", "publico": "todos", "assunto": "A", "mensagem": "B"}, "Público do modelo"),
    ({"nome": "Mensagem livre (escrever na hora)", "assunto": "A", "mensagem": "B"}, "Já existe um modelo"),
    ({"id": "nao-existe", "nome": "X", "assunto": "A", "mensagem": "B"}, "não encontrado"),
])
def test_modelo_invalido_e_recusado_com_mensagem_pronta(web, amb, modelos, corpo, trecho):
    r = web.post("/web/api/avisos/modelos", json=corpo)
    assert r.status_code == 400 and trecho in r.get_json()["erro"]
    assert not modelos.exists()                                                                # nada foi gravado


def test_modelo_sem_publico_aceita_marcadores_dos_dois(web, amb, modelos):
    r = web.post("/web/api/avisos/modelos", json={"nome": "Geral", "publico": "", "assunto": "$ESCOLA", "mensagem": "$ALUNO $CGM $RESPONSAVEL"})
    assert r.status_code == 200


def test_modelo_com_html_no_nome_nao_vira_html_na_tela(web, amb, modelos):
    web.post("/web/api/avisos/modelos", json={"nome": "<img src=x onerror=alert(1)>", "assunto": "A", "mensagem": "B"})
    tipo = next(e for e in reg.obter("avisos").extras() if e["nome"] == "tipo_mensagem")
    texto = tipo["opcoes"][-1]["texto"]
    assert "<img" not in texto and "&lt;img" in texto


def test_arquivo_de_modelos_quebrado_vira_erro_e_nao_e_apagado(web, amb, modelos):
    modelos.parent.mkdir(parents=True)
    modelos.write_text("{ quebrado", encoding="utf-8")
    assert web.get("/web/api/avisos/modelos").status_code == 400
    assert web.post("/web/api/avisos/modelos", json={"nome": "X", "assunto": "A", "mensagem": "B"}).status_code == 400
    assert modelos.read_text(encoding="utf-8") == "{ quebrado"


# ───────────── escolher os alunos na tela ─────────────

def test_listar_alunos_novos_mostra_o_estado_do_vinculo_de_cada_um(chegando):
    por_nome = {a["nome"]: a for a in av.listar_alunos_novos()}
    assert list(por_nome) == sorted(por_nome, key=av._sem_acento) and len(por_nome) == 6          # só os matriculados, por nome
    ana = por_nome["ANA LIMA"]
    assert (ana["estado"], ana["cgm"], ana["escola_origem"], ana["turma"], ana["id"]) == ("ok", "1000000001", "ESCOLA MUNICIPAL ANA NERI", "Infantil IV", "111")
    assert por_nome["HUGO MELO"]["estado"] == "verificar" and por_nome["HUGO MELO"]["motivo"] == "sem linha de 2026"
    assert av.listar_alunos_novos("ambos")[0]["nome"] == "ANA LIMA" and len(av.listar_alunos_novos("ambos")) == 7
    assert [a["nome"] for a in av.listar_alunos_novos("aguardando")] == ["CAIO PAIVA"]
    assert [a for a in av.listar_alunos_novos("ambos") if a["nome"] == "CAIO PAIVA"][0]["estado"] == "sem_vinculo"


def test_listar_alunos_novos_valida_e_explica(amb):
    with pytest.raises(ValueError, match="Situação inválida"):
        av.listar_alunos_novos("todos")
    with pytest.raises(ValueError, match="previsao_alunos_2027.json"):
        av.listar_alunos_novos("matriculados", "proximo")


def test_aluno_sem_cpf_tem_id_pelo_tr_id_ou_pelo_nome():
    assert av.id_do_aluno({"cpf": "111", "tr_id": "T1", "nome": "A"}) == "111"
    assert av.id_do_aluno({"tr_id": "T1", "nome": "A"}) == "T1"
    assert av.id_do_aluno({"nome": "Áurea Dias"}) == "nome:aurea dias"


def test_so_os_alunos_marcados_recebem_o_comunicado(chegando, smtp, sem_espera):
    r = av.destinatarios_alunos_origem(alunos=["112"])
    assert [d["contexto"]["ALUNO"] for d in r["destinatarios"]] == ["BETO LIMA"] and r["alunos"] == 1
    assert [d["contexto"]["ALUNO"] for d in av.destinatarios_alunos_origem(alunos='["111", "112"]')["destinatarios"]] == ["ANA LIMA", "BETO LIMA"]
    av.executar_avisos(**_args(**TRANSF, alunos=["112"]))
    with pytest.raises(ValueError, match="rode o modo .Simular."):                      # outra seleção = outro comunicado
        av.executar_avisos(**_args(**TRANSF, modo="enviar"))
    r = av.executar_avisos(**_args(**TRANSF, modo="enviar", alunos=["112"]))
    assert r["enviados"] == 1 and [e["para"] for e in smtp] == ["sj@pg.gov.br"] and "BETO LIMA" in smtp[0]["assunto"]
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert registro["filtros"]["alunos"] == ["112"]


def test_marcar_so_quem_nao_tem_vinculo_explica_o_motivo(chegando):
    with pytest.raises(ValueError, match=r"Nenhum aluno novo com escola de origem e e-mail.*1 aluno\(s\) novo\(s\) lido\(s\).*1 sem o vínculo"):
        av.reunir_destinatarios("escolas", situacao_pais="ambos", por_aluno=True, alunos=["113"])      # CAIO: nunca consultado


def test_pais_tambem_filtram_pelos_alunos_marcados(amb):
    r = av.destinatarios_pais("matriculados", "ano", alunos=["111"])
    assert [d["email"] for d in r["destinatarios"]] == ["mae@x.com"] and r["alunos"] == 1
    assert [d["contexto"]["ALUNO"] for d in r["destinatarios"]] == ["ANA LIMA"]                         # BETO (mesma mãe) fica de fora


def test_rota_de_alunos_novos(web, chegando):
    r = web.get("/web/api/avisos/alunos?situacao=matriculados&fonte=ano").get_json()
    assert [a["nome"] for a in r["alunos"]][:2] == ["ANA LIMA", "BETO LIMA"] and r["alunos"][0]["estado"] == "ok"
    r = web.get("/web/api/avisos/alunos?fonte=proximo").get_json()
    assert r["alunos"] == [] and "previsao_alunos_2027.json" in r["aviso"]                              # a tela mostra o aviso
    assert web.get("/web/api/avisos/alunos?situacao=x").status_code == 400
    assert web.get("/web/api/avisos/alunos?fonte=x").status_code == 400


def test_previa_respeita_os_alunos_marcados(web, chegando):
    d = web.post("/web/api/automacoes/avisos/previa", json={"publico": "escolas", "alunos": '["111"]',
                                                           **{k: TRANSF[k] for k in ("assunto", "mensagem")}}).get_json()["texto"]
    assert d.startswith("1 e-mail(s) para escolas de origem, um por aluno que chega (de 1 aluno(s) novo(s))")


# ───────────── nome da escola no formato da Base ABC, escola anterior e o exemplo da mensagem ─────────────

NOSSA_NA_BASE = "JUDITH M SILVEIRA,E M PROFA-EI EF"


def test_nome_da_base_abc_casa_com_a_lista_de_escolas():
    unidades = [{"nome": "Escola Municipal Ana Néri", "eh_cmei": False, "emails": ["a@x.com"]},
                {"nome": "CMEI Pequeno Príncipe", "eh_cmei": True, "emails": ["c@x.com"]}]
    assert av._achar_unidade("ANA NERI,E M-EF", unidades)["emails"] == ["a@x.com"]
    assert av._achar_unidade("PEQUENO PRINCIPE,CMEI-EI", unidades)["emails"] == ["c@x.com"]
    assert av._achar_unidade("OUTRA ESCOLA,E M-EF", unidades) is None


def _so_a_nossa(chegando_pre, **vinculo):
    pre = chegando_pre
    for c in pre["cadastros"].values():
        c.pop("vinculo_base_abc", None)
    for lista in pre["turmas_intencao"].values():
        for a in lista:
            a.pop("vinculo_base_abc", None)
    pre["cadastros"]["111"].update(_vinc(NOSSA_NA_BASE, cgm="1000000001", turma="1º Ano", **vinculo))
    (paths.dados_ano_atual() / "pre_matricula.json").write_text(json.dumps(pre), encoding="utf-8")


def test_aluno_que_ja_entrou_na_nossa_escola_pede_a_escola_anterior(chegando):
    _so_a_nossa(chegando, escola_anterior="ESCOLA MUNICIPAL ANA NERI", turma_anterior="5º Ano do Ensino Fundamental", ano_anterior=2025)
    r = av.destinatarios_alunos_origem()
    [d] = r["destinatarios"]
    assert d["email"] == "ana@pg.gov.br" and d["contexto"]["ALUNO"] == "ANA LIMA"
    assert d["contexto"]["SERIE"] == "5º Ano do Ensino Fundamental" and d["contexto"]["TURMA"] == "Infantil IV"   # série de origem x turma daqui
    assert r["da_propria_escola"] == [] and r["origem_desconhecida"] == []
    [a] = [x for x in av.listar_alunos_novos() if x["id"] == "111"]
    assert (a["estado"], a["escola_origem"], a["serie"], a["na_nossa_escola"]) == ("ok", "ESCOLA MUNICIPAL ANA NERI", "5º Ano do Ensino Fundamental", False)


def test_aluno_na_nossa_escola_sem_escola_anterior_nao_e_origem_desconhecida(chegando):
    _so_a_nossa(chegando)                                                          # vínculo antigo: sem escola_anterior
    r = av.destinatarios_alunos_origem(alunos=["111"])
    assert r["destinatarios"] == [] and r["da_propria_escola"] == ["ANA LIMA (Infantil IV)"] and r["origem_desconhecida"] == []
    with pytest.raises(ValueError, match="já estão na nossa escola e sem escola anterior.*refaça a Consulta na Base ABC"):
        av.reunir_destinatarios("escolas", por_aluno=True, alunos=["111"])
    [a] = [x for x in av.listar_alunos_novos() if x["id"] == "111"]
    assert a["na_nossa_escola"] is True and a["estado"] == "ok"


def test_exemplo_mostra_o_texto_do_aluno_marcado(chegando):
    r = av.exemplo_da_mensagem("escolas", TRANSF["assunto"], TRANSF["mensagem"], alunos=["112"])
    assert (r["para"], r["aluno"], r["total"]) == ("sj@pg.gov.br", "BETO LIMA", 1) and "aviso" not in r
    assert r["assunto"] == "Transferência de BETO LIMA"
    assert r["corpo"] == f"Aluno BETO LIMA, CGM 1000000002, série 3º ano, vai para a turma Infantil IV de {PROPRIA} para Escola Municipal Rural São José."
    primeiro = av.exemplo_da_mensagem("escolas", TRANSF["assunto"], TRANSF["mensagem"])                      # nada marcado: o primeiro da lista
    assert primeiro["aluno"] == "ANA LIMA" and primeiro["total"] == 2


def test_exemplo_de_quem_nao_receberia_mostra_o_texto_e_o_motivo(chegando):
    r = av.exemplo_da_mensagem("escolas", TRANSF["assunto"], TRANSF["mensagem"], alunos=["118"])               # HUGO: vínculo a verificar
    assert r["para"] == "" and r["aluno"] == "HUGO MELO" and "Nenhum aluno novo com escola de origem e e-mail" in r["aviso"]
    assert "HUGO MELO" in r["corpo"] and "CGM 1000000008" in r["corpo"]               # o texto aparece mesmo sem poder enviar


def test_exemplo_vazio_marcador_errado_e_pais(amb):
    assert av.exemplo_da_mensagem("escolas", "", "") == {"vazio": True}
    assert av.exemplo_da_mensagem(None, "A", "B") == {"vazio": True}
    assert "marcador" in av.exemplo_da_mensagem("pais", "A", "$CGM")["aviso"]
    r = av.exemplo_da_mensagem("pais", "Aviso para $ALUNO", "Olá $RESPONSAVEL, $ALUNO em $TURMA", alunos=["111"])
    assert (r["para"], r["assunto"], r["corpo"]) == ("mae@x.com", "Aviso para ANA LIMA", "Olá MARIA LIMA, ANA LIMA em Infantil IV")


def test_rota_do_exemplo(web, chegando):
    r = web.post("/web/api/avisos/exemplo", json={"publico": "escolas", "alunos": '["111"]', **{k: TRANSF[k] for k in ("assunto", "mensagem")}})
    assert r.status_code == 200 and r.get_json()["aluno"] == "ANA LIMA" and "CGM 1000000001" in r.get_json()["corpo"]
    assert web.post("/web/api/avisos/exemplo", json={}).get_json() == {"vazio": True}


# ───────────── chamada para matrícula: posição na turma e modelo pronto ─────────────

@pytest.mark.parametrize("pos,esperado", [("1", 1), ("3º", 3), (" 12 ", 12), (7, 7), ("", None), (None, None), ("—", None)])
def test_posicao_do_aluno_na_lista_da_turma(pos, esperado):
    assert av.posicao_do_aluno({"pos": pos}) == esperado
    assert av.posicao_do_aluno({}) is None


def test_modelo_de_chamada_para_matricula_e_para_os_pais_e_so_usa_marcadores_validos():
    from src.comum import modelos_avisos as ma
    m = ma.obter("chamada_matricula")
    assert m["publico"] == "pais" and "vaga" in m["mensagem"] and "$RESPONSAVEL" in m["mensagem"]
    av.conferir_marcadores(m["assunto"], "pais", "Assunto")
    av.conferir_marcadores(m["mensagem"], "pais", "Mensagem")
    corpo = av.renderizar(m["mensagem"], {"RESPONSAVEL": "Maria", "ALUNO": "Ana", "TURMA": "1º Ano", "ESCOLA": "Escola X", "ANO": "2026"})
    assert "Olá, Maria!" in corpo and "vaga para Ana na turma 1º Ano da Escola X em 2026" in corpo and "$" not in corpo


# ───────────── "Quem já recebeu" (só leitura do enviados.json) ─────────────

def _gravar_enviados(envios: dict) -> None:
    pasta = paths.dados_ano_atual() / "AVISOS"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "enviados.json").write_text(json.dumps({"envios": envios}), encoding="utf-8")


def test_listar_enviados_sem_registro(amb):
    assert av.listar_enviados() == {"total": 0, "envios": [], "por_publico": {}}


def test_listar_enviados_ordena_pelo_mais_recente_e_reconhece_o_publico(amb):
    _gravar_enviados({
        "a": {"para": "x@pg.gov.br", "nome": "Escola X", "assunto": "A", "enviado_em": "2026-11-01T10:00:00", "publico": "pais", "aluno": "ANA"},
        "b": {"para": "y@pg.gov.br", "nome": "Escola Y", "assunto": "B", "enviado_em": "2026-11-03T09:00:00", "aluno": "BETO",
              "cgm": "55", "data_saida": "2026-10-30", "anexos": ["guia.pdf"]},
        "c": {"para": "z@pg.gov.br", "nome": "Escola Z", "assunto": "C", "enviado_em": "2026-11-02T08:00:00"},
        "lixo": "não é um dicionário",
    })
    r = av.listar_enviados()
    assert [e["para"] for e in r["envios"]] == ["y@pg.gov.br", "z@pg.gov.br", "x@pg.gov.br"] and r["total"] == 3
    assert r["por_publico"] == {"destino": 1, "": 1, "pais": 1} and r["envios"][0]["anexos"] == ["guia.pdf"]


def test_listar_enviados_nao_altera_o_registro(amb):
    _gravar_enviados({"a": {"para": "x@pg.gov.br", "enviado_em": "2026-11-01T10:00:00"}})
    arquivo = paths.dados_ano_atual() / "AVISOS" / "enviados.json"
    antes = arquivo.read_bytes()
    av.listar_enviados()
    assert arquivo.read_bytes() == antes


def test_rota_enviados(amb):
    _gravar_enviados({"a": {"para": "x@pg.gov.br", "nome": "X", "assunto": "A", "enviado_em": "2026-11-01T10:00:00"}})
    r = create_app().test_client().get("/web/api/avisos/enviados")
    assert r.status_code == 200 and r.get_json()["total"] == 1 and r.get_json()["envios"][0]["para"] == "x@pg.gov.br"


def test_rota_enviados_com_registro_corrompido_avisa_sem_quebrar(amb):
    pasta = paths.dados_ano_atual() / "AVISOS"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "enviados.json").write_text("{quebrado", encoding="utf-8")
    r = create_app().test_client().get("/web/api/avisos/enviados")
    assert r.status_code == 200 and r.get_json()["envios"] == [] and "Registro de envios" in r.get_json()["aviso"]


def test_envio_real_guarda_o_publico_no_registro(chegando, smtp, sem_espera):
    _simular_e_enviar()
    assert {e["publico"] for e in av.listar_enviados()["envios"]} == {"escolas"}

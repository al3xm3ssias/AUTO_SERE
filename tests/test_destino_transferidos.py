"""Escola de destino dos transferidos: destino (Base ABC + preenchimento manual), documentos em anexo e o público
`destino` do avisos (um e-mail por aluno transferido, com guia, histórico e parecer anexados)."""
import json
from pathlib import Path

import pytest

from src.automacao import avisos as av
from src.comum import credenciais, escola, paths
from src.comum import destino_transferidos as dt
from src.comum import registro_scripts as reg
from src.comum.arquivos_json import ArquivoJsonCorrompidoError
from src.web.api import rotas
from src.web.app import create_app

PROPRIA = "Escola Municipal Profª Judith Macedo Silveira"
ESCOLAS = {
    "escolas-municipais": {"url": "x", "quantidade": 4, "escolas": [
        {"nome": PROPRIA, "endereco": "", "ramal": "", "email": "judith@pg.gov.br"},
        {"nome": "Escola Municipal Ana Néri", "endereco": "", "ramal": "", "email": "ana@pg.gov.br"},
        {"nome": "Escola Municipal Rural São José", "endereco": "", "ramal": "", "email": "sj@pg.gov.br"},
        {"nome": "Escola Municipal Sem Email", "endereco": "", "ramal": "", "email": ""},
    ]},
    "cmeis-2": {"url": "y", "quantidade": 1, "escolas": [
        {"nome": "CMEI Pequeno Príncipe", "endereco": "", "ramal": "", "email": "cmei1@pg.gov.br"}]},
}
TURMA = "5º Ano A"


def _doc():
    return {"emitido_em": "2026-10-01T10:00:00", "assinado_secretario": "2026-10-01T11:00:00",
            "assinado_diretor": "2026-10-01T12:00:00", "anexado_em": "2026-10-02T09:00:00"}


def _reg(nome, vinculo_escola=None, **extra):
    r = {"nome": nome, "turma": TURMA, "chamada": 1, "data_nascimento": "01/01/2015", "data_transferencia": "05/10/2026",
         "retorno": None, "guia": _doc(), "historico": _doc(), "parecer": {"digitalizado_em": "2026-10-03T08:00:00", "anexado_em": None}}
    if vinculo_escola:
        r["vinculo_base_abc"] = {"escola": vinculo_escola, "status": "ok", "cgm": "x", "periodo": "ano_vigente"}
    r.update(extra)
    return r


def _arquivos(dados: Path, nome: str, turma=TURMA, com=("guia", "historico", "parecer")):
    base = dados / "TRANSFERENCIAS"
    pastas = {"guia": ("GUIA DE TRANSFERENCIA", f"{nome}.pdf"), "historico": ("HISTORICO", f"{nome}.pdf"),
              "parecer": ("PARECERES", f"01-{nome}.pdf")}
    for chave in com:
        sub, arq = pastas[chave]
        (base / sub / turma).mkdir(parents=True, exist_ok=True)
        (base / sub / turma / arq).write_bytes(f"%PDF {chave} {nome}".encode())


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    dados = tmp_path / "dados" / "2026"
    dados.mkdir(parents=True)
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    (dados / "escolas_completas.json").write_text(json.dumps(ESCOLAS), encoding="utf-8")
    monkeypatch.setattr(escola, "nome", lambda: PROPRIA)
    monkeypatch.setattr(credenciais, "EMAIL_REMETENTE", "escola@gmail.com")
    monkeypatch.setattr(credenciais, "EMAIL_SENHA_APP", "abcdabcdabcdabcd")
    return dados


def _gravar(dados: Path, registros: dict):
    (dados / "transferidos.json").write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


def _ler(dados: Path) -> dict:
    return json.loads((dados / "transferidos.json").read_text(encoding="utf-8"))


@pytest.fixture()
def smtp(monkeypatch):
    chamadas = []

    def falso(destinatario, assunto, corpo, remetente=None, senha_app=None, anexos=None):
        chamadas.append({"para": destinatario, "assunto": assunto, "corpo": corpo, "anexos": [Path(a).name for a in anexos or []]})
        return True, None
    monkeypatch.setattr("src.automacao.envia_email.enviar_email", falso)
    return chamadas


# ───────────── destino: o que vale ─────────────

def test_destino_vem_da_base_abc_quando_o_vinculo_esta_ok():
    d = dt.resolver_destino(_reg("ANA", "ESCOLA MUNICIPAL ANA NERI"))
    assert (d["fonte"], d["escola"], d["consulta"], d["status_aviso"]) == ("base_abc", "ESCOLA MUNICIPAL ANA NERI", "ok", "automatico")


def test_vinculo_a_verificar_nunca_vira_destino_sozinho():
    r = _reg("ANA")
    r["vinculo_base_abc"] = {"escola": "ESCOLA DUVIDOSA", "status": "verificar", "motivo": "duas matrículas em curso"}
    d = dt.resolver_destino(r)
    assert d["escola"] == "" and d["consulta"] == "verificar" and d["motivo"] == "duas matrículas em curso"


def test_sem_vinculo_e_sem_manual_nao_tem_destino():
    d = dt.resolver_destino(_reg("ANA"))
    assert (d["fonte"], d["escola"], d["consulta"]) == ("nenhuma", "", "sem_vinculo")


def test_destino_manual_vale_no_lugar_do_vinculo():
    r = _reg("ANA", "ESCOLA MUNICIPAL ANA NERI", destino_manual={"escola": "CMEI Pequeno Príncipe", "status": "automatico"})
    d = dt.resolver_destino(r)
    assert (d["fonte"], d["escola"]) == ("manual", "CMEI Pequeno Príncipe")


# ───────────── gravar o destino à mão ─────────────

def test_salvar_destino_grava_so_essa_chave_e_o_vinculo_da_consulta_fica_intacto(amb):
    _gravar(amb, {"10": _reg("ANA", "ESCOLA MUNICIPAL ANA NERI")})
    d = dt.salvar_destino("10", "  Colégio   Particular ", "encaminhado", "enviei à parte", amb)
    assert d["escola"] == "Colégio Particular" and d["status_aviso"] == "encaminhado"
    gravado = _ler(amb)["10"]
    assert gravado["destino_manual"]["escola"] == "Colégio Particular" and gravado["destino_manual"]["atualizado_em"]
    assert gravado["vinculo_base_abc"]["escola"] == "ESCOLA MUNICIPAL ANA NERI" and gravado["guia"] == _doc()


def test_tudo_em_branco_com_aviso_automatico_limpa_o_preenchimento(amb):
    _gravar(amb, {"10": _reg("ANA", destino_manual={"escola": "X", "status": "nao_avisar"})})
    dt.salvar_destino("10", "", "automatico", "", amb)
    assert "destino_manual" not in _ler(amb)["10"]


@pytest.mark.parametrize("escola,status,obs", [("X", "enviar_logo", ""), ("x" * 201, "automatico", ""), ("X", "automatico", "o" * 301)])
def test_salvar_destino_recusa_o_que_nao_presta(amb, escola, status, obs):
    _gravar(amb, {"10": _reg("ANA")})
    with pytest.raises(dt.DestinoInvalidoError):
        dt.salvar_destino("10", escola, status, obs, amb)
    assert "destino_manual" not in _ler(amb)["10"]


def test_salvar_destino_aluno_inexistente_e_arquivo_ilegivel(amb):
    with pytest.raises(dt.DestinoInvalidoError, match="não existe"):
        dt.salvar_destino("10", "X", "automatico", "", amb)
    _gravar(amb, {"10": _reg("ANA")})
    with pytest.raises(dt.DestinoInvalidoError, match="não encontrado"):
        dt.salvar_destino("99", "X", "automatico", "", amb)
    (amb / "transferidos.json").write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ArquivoJsonCorrompidoError):
        dt.salvar_destino("10", "X", "automatico", "", amb)
    assert (amb / "transferidos.json").read_text(encoding="utf-8") == "{quebrado"           # nunca sobrescrito


# ───────────── documentos da saída atual ─────────────

def test_documentos_completos(amb):
    _arquivos(amb, "ANA")
    docs = dt.documentos_do_aluno(_reg("ANA"), amb)
    assert docs["faltando"] == [] and [docs[k].name for k in ("guia", "historico", "parecer")] == ["ANA.pdf", "ANA.pdf", "01-ANA.pdf"]


def test_documento_que_falta_e_dito(amb):
    _arquivos(amb, "ANA", com=("guia", "parecer"))
    docs = dt.documentos_do_aluno(_reg("ANA"), amb)
    assert docs["historico"] is None and docs["faltando"] == ["historico: não encontrado"]


def test_parecer_com_mais_de_um_arquivo_nao_e_escolhido(amb):
    _arquivos(amb, "ANA")
    (amb / "TRANSFERENCIAS" / "PARECERES" / TURMA / "01-ANA_1.pdf").write_bytes(b"%PDF outro")
    docs = dt.documentos_do_aluno(_reg("ANA"), amb)
    assert docs["parecer"] is None and "há 2 arquivos" in docs["faltando"][0]


def test_parecer_antigo_renomeado_com_a_saida_nao_atrapalha(amb):
    _arquivos(amb, "ANA")
    (amb / "TRANSFERENCIAS" / "PARECERES" / TURMA / "01-ANA (saída 05-07-2026).pdf").write_bytes(b"%PDF velho")
    assert dt.documentos_do_aluno(_reg("ANA"), amb)["faltando"] == []


def test_segunda_saida_sem_parecer_novo_digitalizado_nao_anexa_o_da_primeira(amb):
    _arquivos(amb, "ANA")                                                  # o parecer da 1ª saída continua em PARECERES
    r = _reg("ANA", ciclos_anteriores=[{"data_transferencia": "05/07/2026"}])
    r["parecer"] = {"digitalizado_em": None, "anexado_em": None}
    docs = dt.documentos_do_aluno(r, amb)
    assert docs["parecer"] is None and "ainda não foi digitalizado" in docs["faltando"][0]
    r["parecer"]["digitalizado_em"] = "2026-10-20T08:00:00"               # agora o parecer desta saída existe
    assert dt.documentos_do_aluno(r, amb)["faltando"] == []


def test_pdfs_de_saida_anterior_renomeados_nao_contam_como_os_da_saida_atual(amb):
    _arquivos(amb, "ANA", com=("parecer",))
    for sub in ("GUIA DE TRANSFERENCIA", "HISTORICO"):
        pasta = amb / "TRANSFERENCIAS" / sub / TURMA
        pasta.mkdir(parents=True)
        (pasta / "ANA (saída 05-07-2026).pdf").write_bytes(b"%PDF 1a saida")
    docs = dt.documentos_do_aluno(_reg("ANA"), amb)
    assert docs["guia"] is None and docs["historico"] is None and len(docs["faltando"]) == 2


# ───────────── público destino ─────────────

def _cenario(amb):
    _gravar(amb, {
        "10": _reg("ANA", "ESCOLA MUNICIPAL ANA NERI"),                         # ok
        "11": _reg("BETO", "Colégio Particular Alfa"),                          # destino fora da lista
        "12": _reg("CAIO"),                                                     # sem destino
        "13": _reg("DUDA", "ESCOLA MUNICIPAL ANA NERI", destino_manual={"status": "encaminhado", "escola": ""}),
        "14": _reg("EDU", "ESCOLA MUNICIPAL ANA NERI", destino_manual={"status": "nao_avisar", "escola": ""}),
        "15": _reg("FABI", "Escola Municipal Sem Email"),                       # escola sem e-mail
        "16": _reg("GIGI", "ESCOLA MUNICIPAL ANA NERI"),                        # sem os documentos
        "17": _reg("HUGO", "ESCOLA MUNICIPAL ANA NERI", retorno={"data": "10/10/2026"}),   # voltou: nem conta
        "18": _reg("IVO", PROPRIA),                                             # vínculo aponta para a nossa escola
        "19": _reg("JOAO", "Colégio Particular Alfa", destino_manual={"escola": "CMEI Pequeno Príncipe", "status": "automatico"}),
    })
    for n in ("ANA", "BETO", "CAIO", "DUDA", "EDU", "FABI", "IVO", "JOAO"):
        _arquivos(amb, n)


def test_so_recebe_quem_fecha_tudo_e_o_resto_vai_numa_lista_com_o_motivo(amb):
    _cenario(amb)
    r = av.destinatarios_destino_transferidos()
    assert [(d["nome"], d["contexto"]["ALUNO"]) for d in r["destinatarios"]] == [
        ("Escola Municipal Ana Néri", "ANA"), ("CMEI Pequeno Príncipe", "JOAO")]
    assert r["alunos"] == 9                                                     # o HUGO, que voltou, não conta
    assert r["destino_fora_da_lista"] == [f"BETO ({TURMA}) — Colégio Particular Alfa"]
    assert r["sem_destino"] == [f"CAIO ({TURMA})"]
    assert r["encaminhados"] == [f"DUDA ({TURMA})"] and r["nao_avisar"] == [f"EDU ({TURMA})"]
    assert r["sem_email"] == ["Escola Municipal Sem Email (aluno FABI)"]
    assert r["sem_documentos"] and r["sem_documentos"][0].startswith(f"GIGI ({TURMA})")
    assert len(r["a_verificar"]) == 1 and "nossa própria escola" in r["a_verificar"][0]


def test_destinatario_leva_os_tres_anexos_e_os_dados_do_aluno(amb):
    _cenario(amb)
    d = av.destinatarios_destino_transferidos()["destinatarios"][0]
    assert d["email"] == "ana@pg.gov.br" and d["cgm"] == "10"
    assert [Path(a).name for a in d["anexos"]] == ["ANA.pdf", "ANA.pdf", "01-ANA.pdf"]
    assert [Path(a).parent.parent.name for a in d["anexos"]] == ["GUIA DE TRANSFERENCIA", "HISTORICO", "PARECERES"]
    assert d["contexto"] == {"ESCOLA_DESTINO": "Escola Municipal Ana Néri", "ALUNO": "ANA", "CGM": "10", "TURMA": TURMA,
                             "DATA_SAIDA": "05/10/2026"}


def test_filtros_de_unidade_e_de_alunos(amb):
    _cenario(amb)
    assert [d["contexto"]["ALUNO"] for d in av.destinatarios_destino_transferidos(tipo="cmeis")["destinatarios"]] == ["JOAO"]
    assert [d["contexto"]["ALUNO"] for d in av.destinatarios_destino_transferidos(unidades=["Escola Municipal Ana Néri"])["destinatarios"]] == ["ANA"]
    r = av.destinatarios_destino_transferidos(alunos=["19"])
    assert [d["contexto"]["ALUNO"] for d in r["destinatarios"]] == ["JOAO"] and r["alunos"] == 1


def test_nenhum_destinatario_explica_por_que(amb):
    _gravar(amb, {"12": _reg("CAIO"), "13": _reg("DUDA", destino_manual={"status": "encaminhado", "escola": ""})})
    with pytest.raises(ValueError) as e:
        av.reunir_destinatarios("destino")
    assert "1 sem escola de destino" in str(e.value) and "1 marcados como encaminhados por e-mail à parte" in str(e.value)


def test_sem_transferidos_json_pede_a_coleta_de_turmas(amb):
    with pytest.raises(ValueError, match="coleta de turmas"):
        av.reunir_destinatarios("destino")


def test_marcadores_do_destino_e_modelo_pronto(amb):
    assert av.marcadores_validos("destino") == ("ESCOLA", "ANO", "DATA", "ESCOLA_DESTINO", "ALUNO", "CGM", "TURMA", "DATA_SAIDA")
    with pytest.raises(ValueError, match=r"\$SERIE"):
        av.conferir_marcadores("Série $SERIE", "destino", "Mensagem")
    from src.comum import modelos_avisos as ma
    m = ma.obter("transferencia_destino")
    assert m["publico"] == "destino" and "anexo" in m["mensagem"]
    av.conferir_marcadores(m["assunto"], "destino", "Assunto")
    av.conferir_marcadores(m["mensagem"], "destino", "Mensagem")


# ───────────── envio ─────────────

def _modelo():
    from src.comum import modelos_avisos as ma
    m = ma.obter("transferencia_destino")
    return m["assunto"], m["mensagem"]


def test_simular_nao_envia_nada_e_mostra_os_anexos(amb, smtp, capsys):
    _cenario(amb)
    assunto, mensagem = _modelo()
    r = av.executar_avisos("destino", "email", "simular", assunto, mensagem)
    assert r["total"] == 2 and smtp == []
    saida = capsys.readouterr().out
    assert "Anexos desta mensagem: ANA.pdf; ANA.pdf; 01-ANA.pdf" in saida and "Transferidos sem escola de destino" in saida
    registro = json.loads(Path(r["registro"]).read_text(encoding="utf-8"))
    assert registro["mensagens"][0]["anexos"] == ["ANA.pdf", "ANA.pdf", "01-ANA.pdf"]       # no registro só os nomes


def test_envio_real_leva_os_anexos_e_registra_cgm_e_data_da_saida(amb, smtp):
    _cenario(amb)
    assunto, mensagem = _modelo()
    av.executar_avisos("destino", "email", "simular", assunto, mensagem)
    r = av.executar_avisos("destino", "email", "enviar", assunto, mensagem, intervalo_s=2, limite_lote=10)
    assert r["enviados"] == 2
    assert [c["para"] for c in smtp] == ["ana@pg.gov.br", "cmei1@pg.gov.br"]
    assert smtp[0]["anexos"] == ["ANA.pdf", "ANA.pdf", "01-ANA.pdf"]
    assert "ANA" in smtp[0]["assunto"] and "05/10/2026" in smtp[0]["corpo"] and "Escola Municipal Ana Néri" not in smtp[1]["corpo"]
    enviados = list(av.carregar_enviados().values())
    assert {(e["cgm"], e["data_saida"]) for e in enviados} == {("10", "05/10/2026"), ("19", "05/10/2026")}
    assert av.avisos_ja_enviados_ao_destino()[("10", "05/10/2026")]["para"] == "ana@pg.gov.br"
    # rodar de novo não repete
    smtp.clear()
    assert av.executar_avisos("destino", "email", "enviar", assunto, mensagem, intervalo_s=2)["enviados"] == 0 and smtp == []


def test_envio_real_exige_simulacao_do_mesmo_comunicado(amb, smtp):
    _cenario(amb)
    assunto, mensagem = _modelo()
    with pytest.raises(ValueError, match="Simular"):
        av.executar_avisos("destino", "email", "enviar", assunto, mensagem, intervalo_s=2)
    assert smtp == []


def test_segunda_saida_do_mesmo_aluno_e_um_aviso_novo(amb, smtp):
    _gravar(amb, {"10": _reg("ANA", "ESCOLA MUNICIPAL ANA NERI")})
    _arquivos(amb, "ANA")
    assunto, mensagem = _modelo()
    av.executar_avisos("destino", "email", "simular", assunto, mensagem)
    assert av.executar_avisos("destino", "email", "enviar", assunto, mensagem, intervalo_s=2)["enviados"] == 1
    # voltou e saiu de novo: outra data, e o registro novo tem os documentos dele
    novo = _reg("ANA", "ESCOLA MUNICIPAL ANA NERI", data_transferencia="20/11/2026", ciclos_anteriores=[{"data_transferencia": "05/10/2026"}])
    _gravar(amb, {"10": novo})
    av.executar_avisos("destino", "email", "simular", assunto, mensagem)
    assert av.executar_avisos("destino", "email", "enviar", assunto, mensagem, intervalo_s=2)["enviados"] == 1
    assert "20/11/2026" in smtp[1]["corpo"] and len(smtp) == 2


def test_modo_teste_nao_anexa_documento_de_aluno_nem_escreve_para_escola_real(amb, smtp):
    _cenario(amb)
    assunto, mensagem = _modelo()
    r = av.executar_avisos("destino", "email", "teste", assunto, mensagem)
    assert r["enviados_teste"] == 1 and len(smtp) == 1
    assert smtp[0]["para"] == av.ESCOLA_TESTE["email"] and smtp[0]["anexos"] == []
    assert smtp[0]["assunto"].startswith("[TESTE]")
    assert "No envio real seguiriam em anexo: ANA.pdf, ANA.pdf, 01-ANA.pdf" in smtp[0]["corpo"]
    assert "os documentos do aluno NÃO são anexados no teste" in smtp[0]["corpo"]


# ───────────── tela e rotas ─────────────

@pytest.fixture()
def web(amb, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: paths.dados_ano_atual())
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    return create_app().test_client()


def test_lista_de_transferidos_traz_o_destino_e_se_o_aviso_foi_enviado(web, amb, smtp):
    _cenario(amb)
    linhas = {r["nome"]: r for r in web.get("/web/api/transferidos/lista").get_json()["transferidos"]}
    assert linhas["ANA"]["destino"]["escola"] == "ESCOLA MUNICIPAL ANA NERI" and linhas["ANA"]["destino"]["aviso_enviado_em"] is None
    assert linhas["CAIO"]["destino"]["consulta"] == "sem_vinculo" and linhas["DUDA"]["destino"]["status_texto"].startswith("Encaminhado")
    assunto, mensagem = _modelo()
    av.executar_avisos("destino", "email", "simular", assunto, mensagem)
    av.executar_avisos("destino", "email", "enviar", assunto, mensagem, intervalo_s=2)
    linhas = {r["nome"]: r for r in web.get("/web/api/transferidos/lista").get_json()["transferidos"]}
    assert linhas["ANA"]["destino"]["aviso_enviado_em"] and linhas["ANA"]["destino"]["aviso_enviado_para"] == "ana@pg.gov.br"
    assert linhas["BETO"]["destino"]["aviso_enviado_em"] is None


def test_rota_do_destino_le_e_grava(web, amb):
    _gravar(amb, {"10": _reg("ANA")})
    r = web.get("/web/api/transferidos/destino/10").get_json()
    assert r["nome"] == "ANA" and r["manual"] == {} and "CMEI Pequeno Príncipe" in r["escolas"] and "nao_avisar" in r["status_opcoes"]
    r = web.post("/web/api/transferidos/destino/10", json={"escola": "Colégio Alfa", "status": "encaminhado", "observacao": "à parte"})
    assert r.status_code == 200 and r.get_json()["destino"]["status_aviso"] == "encaminhado"
    assert _ler(amb)["10"]["destino_manual"]["escola"] == "Colégio Alfa"
    assert web.post("/web/api/transferidos/destino/10", json={"status": "xis"}).status_code == 400
    assert web.post("/web/api/transferidos/destino/99", json={"status": "automatico"}).status_code == 404
    assert web.get("/web/api/transferidos/destino/99").status_code == 404
    assert web.post("/web/api/transferidos/destino/10", data="não é json", content_type="text/plain").status_code == 400


def test_rota_do_destino_recusa_com_automacao_rodando_e_arquivo_ilegivel(web, amb, monkeypatch):
    _gravar(amb, {"10": _reg("ANA")})
    monkeypatch.setattr(rotas, "_automacoes_rodando", lambda: ["turmas"])
    r = web.post("/web/api/transferidos/destino/10", json={"escola": "X", "status": "automatico"})
    assert r.status_code == 409 and "turmas" in r.get_json()["erro"] and "destino_manual" not in _ler(amb)["10"]
    monkeypatch.setattr(rotas, "_automacoes_rodando", lambda: [])
    (amb / "transferidos.json").write_text("{quebrado", encoding="utf-8")
    assert web.post("/web/api/transferidos/destino/10", json={"escola": "X", "status": "automatico"}).status_code == 500
    assert web.get("/web/api/transferidos/destino/10").status_code == 500


def test_seletor_de_alunos_do_avisos_lista_os_transferidos_com_o_estado(web, amb):
    _cenario(amb)
    r = web.get("/web/api/avisos/alunos?publico=destino").get_json()
    por_nome = {a["nome"]: a for a in r["alunos"]}
    assert "HUGO" not in por_nome                                               # voltou
    assert por_nome["ANA"]["estado"] == "ok" and "Base ABC" in por_nome["ANA"]["selo"]
    assert por_nome["JOAO"]["estado"] == "ok" and "preenchido à mão" in por_nome["JOAO"]["selo"]
    assert por_nome["GIGI"]["estado"] == "verificar" and "faltam documentos" in por_nome["GIGI"]["selo"]
    assert por_nome["CAIO"]["estado"] == "sem_vinculo" and por_nome["DUDA"]["estado"] == "dispensado"


def test_tela_do_avisos_tem_o_publico_destino_e_o_limite_de_1_email(amb):
    extras = {e["nome"]: e for e in reg.obter("avisos").extras()}
    assert "destino" in [o["valor"] for o in extras["publico"]["opcoes"]]
    assert extras["unidades"]["visivelSe"]["valor"] == "escolas|destino" and "destino" in extras["alunos"]["visivelSe"]["valor"]
    assert extras["limite_lote"]["opcoes"][0]["valor"] == "1"


def test_previa_da_automacao_para_o_destino(amb, smtp):
    _cenario(amb)
    assunto, mensagem = _modelo()
    p = {"publico": "destino", "modo": "simular", "assunto": assunto, "mensagem": mensagem}
    texto = reg._previa_avisos(p)
    assert "2 e-mail(s) para escolas de destino" in texto and "1 aluno(s) sem escola de destino" in texto
    assert "1 aluno(s) encaminhados por e-mail à parte" in texto


def test_modo_somente_consulta_bloqueia_a_gravacao_do_destino_mas_deixa_ler(web, amb, monkeypatch):
    _gravar(amb, {"10": _reg("ANA")})
    monkeypatch.setattr(paths, "somente_consulta", lambda: True)
    r = web.post("/web/api/transferidos/destino/10", json={"escola": "X", "status": "automatico"})
    assert r.status_code == 403 and "destino_manual" not in _ler(amb)["10"]
    assert web.get("/web/api/transferidos/destino/10").status_code == 200

"""comunicado_matricula: WhatsApp para o responsável a cada cadastro da pré-matrícula (aguardando e matriculado)."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace

import pytest

from src.automacao import comunicado_matricula as cm
from src.automacao import pre_matricula as pm
from src.comum import configuracao, escola, paths
from src.comum.arquivos_json import ArquivoJsonCorrompidoError
from src.servicos.whatsapp.base import EnvioNaoAutorizadoError, EstadoConexao, ResultadoEnvio
from src.servicos.whatsapp.simulado import ProvedorSimulado

HOJE = date(2026, 10, 31)
G_GERAL = "https://chat.whatsapp.com/DgVKHb1JnvI0STymAK4cIn"

ALUNOS = {
    "Infantil IV": [
        {"cpf": "111", "nome": "ANA LIMA", "situacao": "Matriculado"},
        {"cpf": "112", "nome": "BETO LIMA", "situacao": "Matriculado"},
        {"cpf": "113", "nome": "CAIO PAIVA", "situacao": ""},                                  # aguardando vaga
        {"cpf": "114", "nome": "DUDA ROCHA", "situacao": "Cancelado. Motivo: Responsável desistiu"},
    ],
    "1º Ano do Ensino Fundamental": [
        {"cpf": "115", "nome": "EDU DIAS", "situacao": "MATRICULADO"},
        {"cpf": "116", "nome": "FABI SOUZA", "situacao": "Matriculado", "substituido_por_nova_tentativa": True},
        {"cpf": "117", "nome": "GIGI NUNES", "situacao": "", "matriculado_em": "2026-02-01"},
        {"cpf": "119", "nome": "IVO SEM CAD", "situacao": "Matriculado"},
    ],
}
CADASTROS = {
    "111": {"nome_responsavel": "MARIA LIMA", "telefone": "(42) 99999-1111"},
    "112": {"nome_responsavel": "MARIA LIMA", "telefone": "(42) 99999-1111"},
    "113": {"nome_responsavel": "JOAO PAIVA", "telefone": "(42) 99999-3333"},
    "114": {"nome_responsavel": "RITA ROCHA", "telefone": "(42) 99999-4444"},
    "115": {"nome_responsavel": "EDNA DIAS", "telefone": "42 98888-2222"},
    "116": {"nome_responsavel": "FABIO SOUZA", "telefone": "(42) 99999-5555"},
    "117": {"nome_responsavel": "GILDA NUNES", "telefone": "(42) 3222-1111"},       # fixo
}
NUM_MARIA, NUM_EDNA, NUM_PAIVA = "5542999991111", "5542988882222", "5542999993333"
N_BASE = 6                                                                           # 111 112 113 115 117 119


class Prov:
    """Provedor 'real' falso: registra o que seria enviado."""
    nome = "real"

    def __init__(self, conectado=True, respostas=None):
        self.conectado, self.enviadas, self.respostas = conectado, [], list(respostas or [])

    def estado(self):
        return EstadoConexao(self.conectado, "Conectado." if self.conectado else "Desconectado.")

    def enviar(self, numero, texto):
        self.enviadas.append((numero, texto))
        r = self.respostas.pop(0) if self.respostas else ResultadoEnvio(True, False, id_mensagem=f"id{len(self.enviadas)}")
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    dados = tmp_path / "dados" / "2026"
    dados.mkdir(parents=True)
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path / "dados")
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    env = SimpleNamespace(dados=dados, cfg={}, alunos=json.loads(json.dumps(ALUNOS)), cadastros=dict(CADASTROS))
    monkeypatch.setattr(configuracao, "carregar_configuracao", lambda: {"comunicado_matricula": env.cfg})
    monkeypatch.setattr(escola, "carregar", lambda: {"nome": "ESCOLA JUDITH MACEDO SILVEIRA", "nome_abreviado": "JUDITH"})

    def gravar():
        """Reescreve os dados da coleta SEM apagar o registro de avisos (como a pré-matrícula real faz)."""
        arq = dados / "pre_matricula.json"
        atual = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
        atual.update({"turmas_intencao": env.alunos, "cadastros": env.cadastros})
        arq.write_text(json.dumps(atual), encoding="utf-8")
    env.gravar = gravar
    gravar()
    return env


def rodar(prov, **kw):
    saida = []
    kw.setdefault("hoje", HOJE)
    r = cm.avisar_matriculados(provedor=prov, pausa_s=0, dormir=lambda s: None, saida=saida.append, **kw)
    return r, saida


def registro(amb):
    return json.loads((amb.dados / "pre_matricula.json").read_text(encoding="utf-8"))["avisos_whatsapp"]


def aviso(amb, chave, tipo):
    return registro(amb)["alunos"].get(chave, {}).get(tipo)


def cadastrar(amb, cpf="120", nome="JOANA NOVA", tel="(42) 97777-3333", situacao="Matriculado", turma="Infantil IV"):
    amb.alunos.setdefault(turma, []).append({"cpf": cpf, "nome": nome, "situacao": situacao})
    amb.cadastros[cpf] = {"nome_responsavel": "PAULA NOVA", "telefone": tel}
    amb.gravar()


def base(amb):
    """Primeira execução (linha de base) — a partir daqui só o que for novo dispara mensagem."""
    rodar(Prov())


# ───────────── texto ─────────────

def test_mensagem_usa_data_do_envio_mais_oito_dias_e_nome_formatado(amb):
    m = cm.montar_mensagem(["MARIA DA SILVA"], HOJE)
    assert "a matrícula de Maria da Silva para o ano letivo de 2026 foi aprovada" in m
    assert "De 31 de outubro de 2026 a 8 de novembro de 2026" in m
    assert "Prazo final: 08/11/2026" in m
    assert "Me chamo Claudio, sou escriturário da Escola Judith." in m
    assert "Escriturário – Escola Judith" in m and G_GERAL in m
    assert "$" not in m


def test_mensagem_aguardando(amb):
    m = cm.montar_mensagem(["CAIO PAIVA"], HOJE, tipo="aguardando")
    assert "Recebemos a pré-matrícula de Caio Paiva para o ano letivo de 2026" in m
    assert "aguardando vaga" in m and "foi aprovada" not in m and "Prazo final" not in m and "$" not in m


def test_mensagem_com_varios_filhos_e_ajustes(amb):
    amb.cfg = {"dias_prazo": 5, "escriturario": "Ana"}
    m = cm.montar_mensagem(["ANA LIMA", "BETO LIMA", "CLARA LIMA"], date(2026, 12, 28))
    assert "de Ana Lima, Beto Lima e Clara Lima para" in m
    assert "a 2 de janeiro de 2027" in m and "Prazo final: 02/01/2027" in m and "Me chamo Ana," in m


def test_ajustes_invalidos_sao_recusados(amb):
    for ruim in ({"dias_prazo": 0}, {"dias_prazo": "8"}, {"limite_por_execucao": 999}, {"escriturario": " "},
                 {"link_grupo": "http://x"}, {"links_turmas": ["a"]}, {"links_turmas": {"Infantil IV": "chat.whatsapp.com/x"}}):
        amb.cfg = ruim
        with pytest.raises(ValueError):
            cm.ajustes()


def test_texto_personalizado_e_marcador_desconhecido(amb, tmp_path):
    (tmp_path / "config").mkdir()
    arq = tmp_path / "config" / "comunicado_matricula.txt"
    arq.write_text("Oi! Matrícula de $ALUNO. Prazo $FIM_CURTA.", encoding="utf-8")
    assert cm.montar_mensagem(["ANA LIMA"], HOJE) == "Oi! Matrícula de Ana Lima. Prazo 08/11/2026."
    (tmp_path / "config" / "comunicado_aguardando.txt").write_text("Cadastro de $ALUNO recebido.", encoding="utf-8")
    assert cm.montar_mensagem(["CAIO PAIVA"], HOJE, tipo="aguardando") == "Cadastro de Caio Paiva recebido."
    arq.write_text("Oi $NOME_DO_PAI", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\$NOME_DO_PAI"):
        cm.modelo()


# ───────────── link do grupo por turma ─────────────

LINK_INF, LINK_1ANO = "https://chat.whatsapp.com/INFANTIL4", "https://chat.whatsapp.com/PRIMEIROANO"


def test_link_da_turma_com_fallback_para_o_geral(amb):
    amb.cfg = {"links_turmas": {"Infantil IV": LINK_INF, "1º ANO": LINK_1ANO}}
    cfg = cm.ajustes()
    assert cm.link_da_turma("Infantil IV", cfg) == LINK_INF
    assert cm.link_da_turma("infantil iv", cfg) == LINK_INF                           # maiúscula não importa
    assert cm.link_da_turma("1º Ano do Ensino Fundamental", cfg) == LINK_1ANO         # sufixo da série não importa
    assert cm.link_da_turma("2º Ano", cfg) == G_GERAL                                 # sem link próprio → geral


def test_mensagem_traz_o_link_da_turma_do_aluno(amb):
    amb.cfg = {"links_turmas": {"Infantil IV": LINK_INF}}
    m = cm.montar_mensagem(["ANA LIMA"], HOJE, turmas=["Infantil IV"])
    assert LINK_INF in m and G_GERAL not in m


def test_irmaos_de_turmas_diferentes_recebem_cada_link(amb):
    amb.cfg = {"links_turmas": {"Infantil IV": LINK_INF, "1º Ano": LINK_1ANO}}
    m = cm.montar_mensagem(["ANA LIMA", "EDU LIMA"], HOJE, turmas=["Infantil IV", "1º Ano"])
    assert f"Infantil IV: {LINK_INF}" in m and f"1º Ano: {LINK_1ANO}" in m
    mesma = cm.montar_mensagem(["ANA LIMA", "BETO LIMA"], HOJE, turmas=["Infantil IV", "Infantil IV"])
    assert LINK_INF in mesma and "Infantil IV:" not in mesma                         # mesma turma → link simples


def test_envio_usa_o_link_da_turma_de_cada_aluno(amb):
    amb.cfg = {"links_turmas": {"1º Ano": LINK_1ANO}}
    prov = Prov()
    rodar(prov, incluir_existentes=True)
    edna = next(t for n, t in prov.enviadas if n == NUM_EDNA)
    maria = next(t for n, t in prov.enviadas if n == NUM_MARIA)
    assert LINK_1ANO in edna and G_GERAL not in edna
    assert G_GERAL in maria                                                            # Infantil IV não tem link → geral


# ───────────── telefone ─────────────

@pytest.mark.parametrize("texto,esperado", [
    ("(42) 99999-8888", "5542999998888"), ("42999998888", "5542999998888"), ("+55 42 99999-8888", "5542999998888"),
    ("(42) 3222-1111", None),                                   # fixo
    ("(42) 3222-1111 / (42) 99999-8888", "5542999998888"),      # dois números: pega o celular
    ("(42) 99999-8888 (42) 3222-1111", "5542999998888"),
    ("", None), (None, None), ("não tem", None), ("12345", None)])
def test_extrair_numero(texto, esperado):
    assert cm.extrair_numero(texto) == esperado


# ───────────── quem entra ─────────────

def test_so_matriculados_e_aguardando_validos(amb):
    a = cm.alunos_elegiveis()
    assert sorted(a) == ["111", "112", "113", "115", "117", "119"]     # sem cancelado e sem substituído
    assert {c: a[c]["tipo"] for c in a} == {"111": "matriculado", "112": "matriculado", "113": "aguardando",
                                            "115": "matriculado", "117": "matriculado", "119": "matriculado"}
    assert a["111"]["numero"] == NUM_MARIA and a["111"]["turma"] == "Infantil IV"
    assert a["115"]["turma"] == "1º Ano" and a["115"]["numero"] == NUM_EDNA
    assert a["117"]["numero"] is None and a["119"]["numero"] is None and not a["119"]["tem_cadastro"]


def test_sem_pre_matricula_json(amb):
    (amb.dados / "pre_matricula.json").unlink()
    with pytest.raises(ValueError):
        cm.alunos_elegiveis()


# ───────────── linha de base: não avisa quem já estava cadastrado ─────────────

def test_primeira_execucao_so_marca_linha_de_base(amb):
    prov = Prov()
    r, _ = rodar(prov)
    assert prov.enviadas == [] and r["linha_de_base"] == N_BASE and r["enviados"] == 0
    assert aviso(amb, "111", "matriculado") == {**aviso(amb, "111", "matriculado"), "avisado": "NÃO", "situacao": "linha_de_base"}
    assert aviso(amb, "113", "aguardando")["situacao"] == "linha_de_base"
    assert aviso(amb, "113", "matriculado") is None


def test_novo_cadastro_aguardando_recebe_aviso_de_aguardando(amb):
    base(amb)
    cadastrar(amb, "120", "JOANA NOVA", situacao="")
    prov = Prov()
    r, _ = rodar(prov)
    assert [n for n, _ in prov.enviadas] == ["5542977773333"] and r["por_tipo"] == {"matriculado": 0, "aguardando": 1}
    texto = prov.enviadas[0][1]
    assert "Joana Nova" in texto and "aguardando vaga" in texto and "foi aprovada" not in texto
    reg = aviso(amb, "120", "aguardando")
    assert reg["avisado"] == "SIM" and reg["situacao"] == "enviado" and reg["em"]
    assert reg["numero"] == cm.mascarar_numero("5542977773333") != "5542977773333"    # nunca o número inteiro


def test_novo_aluno_aprovado_recebe_o_comunicado_de_matricula(amb):
    base(amb)
    cadastrar(amb)
    prov = Prov()
    r, _ = rodar(prov)
    assert r["por_tipo"] == {"matriculado": 1, "aguardando": 0}
    assert "Joana Nova" in prov.enviadas[0][1] and "08/11/2026" in prov.enviadas[0][1]
    assert aviso(amb, "120", "matriculado")["avisado"] == "SIM"


def test_aguardando_que_e_aprovado_recebe_os_dois_avisos(amb):
    base(amb)
    cadastrar(amb, situacao="")
    rodar(Prov())                                                    # 1º aviso: aguardando
    amb.alunos["Infantil IV"][-1]["situacao"] = "Matriculado"        # a vaga saiu
    amb.gravar()
    prov = Prov()
    r, _ = rodar(prov)
    assert r["por_tipo"] == {"matriculado": 1, "aguardando": 0} and "foi aprovada" in prov.enviadas[0][1]
    assert aviso(amb, "120", "aguardando")["avisado"] == aviso(amb, "120", "matriculado")["avisado"] == "SIM"
    prov = Prov()
    rodar(prov)
    assert prov.enviadas == []                                       # e acabou: nada se repete


def test_quem_ja_estava_aguardando_na_base_so_recebe_quando_for_aprovado(amb):
    base(amb)                                                        # Caio (113) aguardando → linha de base
    prov = Prov()
    rodar(prov)
    assert prov.enviadas == []
    amb.alunos["Infantil IV"][2]["situacao"] = "Matriculado"         # Caio foi aprovado
    amb.gravar()
    r, _ = rodar(prov)
    assert [n for n, _ in prov.enviadas] == [NUM_PAIVA] and "foi aprovada" in prov.enviadas[0][1]


def test_avisar_aguardando_pode_ser_desligado(amb):
    base(amb)
    amb.cfg = {"avisar_aguardando": False}
    cadastrar(amb, "120", "JOANA NOVA", situacao="")
    cadastrar(amb, "121", "LUCAS NOVO", "(42) 96666-4444", situacao="Matriculado")
    prov = Prov()
    rodar(prov)
    assert [n for n, _ in prov.enviadas] == ["5542966664444"]
    assert aviso(amb, "120", "aguardando") is None                   # não foi marcado: quando ligar, ainda recebe


def test_aprovados_vao_antes_dos_aguardando(amb):
    base(amb)
    cadastrar(amb, "120", "A NOVA", "(42) 97777-0001", situacao="")
    cadastrar(amb, "121", "B NOVO", "(42) 97777-0002", situacao="Matriculado")
    prov = Prov()
    rodar(prov)
    assert [n for n, _ in prov.enviadas] == ["5542977770002", "5542977770001"]


def test_incluir_existentes_avisa_todos_com_celular(amb):
    prov = Prov()
    r, saida = rodar(prov, incluir_existentes=True)
    assert sorted(n for n, _ in prov.enviadas) == sorted([NUM_EDNA, NUM_MARIA, NUM_PAIVA])
    assert r["enviados"] == 4 and r["por_tipo"] == {"matriculado": 3, "aguardando": 1}   # Ana, Beto, Edu | Caio
    assert sorted(r["sem_celular"]) == ["Gigi Nunes (1º Ano)", "Ivo Sem Cad (1º Ano) — sem cadastro consultado"]


def test_irmaos_recebem_uma_mensagem_so(amb):
    prov = Prov()
    rodar(prov, incluir_existentes=True)
    maria = [t for n, t in prov.enviadas if n == NUM_MARIA]
    assert len(maria) == 1 and "de Ana Lima e Beto Lima para" in maria[0]
    assert aviso(amb, "111", "matriculado")["avisado"] == aviso(amb, "112", "matriculado")["avisado"] == "SIM"


def test_nunca_repete(amb):
    rodar(Prov(), incluir_existentes=True)
    prov = Prov()
    r, _ = rodar(prov)
    assert prov.enviadas == [] and r["enviados"] == 0


# ───────────── o registro vive no pre_matricula.json e sobrevive à coleta ─────────────

def test_registro_sobrevive_a_nova_coleta_e_nao_apaga_os_dados(amb):
    base(amb)
    cadastrar(amb)
    rodar(Prov())
    bruto = json.loads((amb.dados / "pre_matricula.json").read_text(encoding="utf-8"))
    assert len(bruto["turmas_intencao"]["Infantil IV"]) == 5 and "120" in bruto["cadastros"]       # dados intactos
    dados = pm.carregar_pre_matricula()                                      # uma coleta carrega, mexe e regrava
    dados["turmas_intencao"]["Infantil IV"][0]["nome"] = "ANA LIMA ATUALIZADA"
    pm.salvar_pre_matricula(dados)
    assert aviso(amb, "120", "matriculado")["avisado"] == "SIM"                # registro continua lá
    prov = Prov()
    rodar(prov)
    assert prov.enviadas == []


# ───────────── simulado não registra ─────────────

def test_simulacao_nao_registra_e_nao_bloqueia_o_envio_real(amb):
    rodar(ProvedorSimulado())                       # linha de base
    cadastrar(amb)
    sim = ProvedorSimulado()
    r, saida = rodar(sim)
    assert r["modo"] == "simulado" and r["simulados"] == 1 and r["enviados"] == 0
    assert [n for n, _ in sim.enviadas] == ["5542977773333"] and any("PRÉVIA" in s for s in saida)
    assert aviso(amb, "120", "matriculado") is None
    prov = Prov()
    r, _ = rodar(prov)
    assert r["enviados"] == 1 and len(prov.enviadas) == 1                      # agora sim, de verdade


# ───────────── travas ─────────────

def test_whatsapp_desconectado_nao_envia_nem_grava(amb):
    base(amb)
    cadastrar(amb)
    prov = Prov(conectado=False)
    r, _ = rodar(prov)
    assert prov.enviadas == [] and "não conectado" in r["bloqueado"]
    assert aviso(amb, "120", "matriculado") is None


def test_envio_real_nao_autorizado_para_sem_gravar(amb):
    base(amb)
    cadastrar(amb)
    prov = Prov(respostas=[EnvioNaoAutorizadoError("Envio real bloqueado: defina WHATSAPP_ENVIO_REAL=1")])
    r, _ = rodar(prov)
    assert "WHATSAPP_ENVIO_REAL" in r["bloqueado"] and r["enviados"] == 0
    assert aviso(amb, "120", "matriculado") is None


def test_desconectou_no_meio_para_tudo(amb):
    base(amb)
    cadastrar(amb, "120", "JOANA NOVA", "(42) 97777-3333")
    cadastrar(amb, "121", "LUCAS NOVO", "(42) 96666-4444")
    prov = Prov(respostas=[ResultadoEnvio(False, False, erro="O WhatsApp não está conectado. Abra a tela WhatsApp.")])
    r, _ = rodar(prov)
    assert len(prov.enviadas) == 1 and r["bloqueado"]
    assert aviso(amb, "120", "matriculado") is None and aviso(amb, "121", "matriculado") is None


def test_limite_por_execucao(amb):
    base(amb)
    for i in range(5):
        cadastrar(amb, f"20{i}", f"ALUNO {i}", f"(42) 9777{i}-0000")
    prov = Prov()
    r, _ = rodar(prov, limite=2)
    assert len(prov.enviadas) == 2 and r["adiados"] == 3
    prov2 = Prov()
    r2, _ = rodar(prov2, limite=10)
    assert len(prov2.enviadas) == 3 and r2["adiados"] == 0                      # o resto sai na próxima


def test_pausa_so_entre_envios_reais(amb):
    base(amb)
    cadastrar(amb, "120", "A NOVA", "(42) 97777-0001")
    cadastrar(amb, "121", "B NOVA", "(42) 97777-0002")
    pausas = []
    cm.avisar_matriculados(provedor=Prov(), hoje=HOJE, pausa_s=3, dormir=pausas.append, saida=lambda m: None)
    assert pausas == [3]                                                        # 2 mensagens → 1 pausa


def test_arquivo_corrompido_nao_envia_nada(amb):
    (amb.dados / "pre_matricula.json").write_text("{quebrado", encoding="utf-8")
    prov = Prov()
    with pytest.raises((ValueError, ArquivoJsonCorrompidoError)):
        rodar(prov, incluir_existentes=True)
    assert prov.enviadas == []


# ───────────── falhas ─────────────

def test_sem_whatsapp_so_tenta_de_novo_se_o_telefone_mudar(amb):
    base(amb)
    cadastrar(amb)
    r, _ = rodar(Prov(respostas=[ResultadoEnvio(False, False, erro="Esse número não tem WhatsApp.")]))
    assert len(r["sem_whatsapp"]) == 1
    reg = aviso(amb, "120", "matriculado")
    assert reg["situacao"] == "sem_whatsapp" and reg["avisado"] == "NÃO"
    prov = Prov()
    rodar(prov)
    assert prov.enviadas == []                                                   # mesmo número: não insiste
    amb.cadastros["120"]["telefone"] = "(42) 97777-9999"                         # responsável corrigiu o telefone
    amb.gravar()
    r, _ = rodar(prov)
    assert [n for n, _ in prov.enviadas] == ["5542977779999"] and r["enviados"] == 1


def test_falha_incerta_nunca_e_repetida_sozinha(amb):
    base(amb)
    cadastrar(amb)
    erro = "Não consegui confirmar o envio. A mensagem pode ou não ter saído: confira no WhatsApp antes de reenviar."
    r, saida = rodar(Prov(respostas=[ResultadoEnvio(False, False, erro=erro)]))
    assert len(r["incertos"]) == 1 and any("Confira no WhatsApp" in s for s in saida)
    prov = Prov()
    rodar(prov)
    assert prov.enviadas == []


def test_falha_comum_tenta_de_novo_ate_tres_vezes(amb):
    base(amb)
    cadastrar(amb)
    for _ in range(3):
        r, _ = rodar(Prov(respostas=[ResultadoEnvio(False, False, erro="O gateway respondeu erro 500.")]))
        assert len(r["falhas"]) == 1
    assert aviso(amb, "120", "matriculado")["tentativas"] == 3
    prov = Prov()
    rodar(prov)
    assert prov.enviadas == []                                                   # desistiu: não fica insistindo


def test_excecao_do_provedor_nao_derruba(amb):
    base(amb)
    cadastrar(amb)
    r, _ = rodar(Prov(respostas=[RuntimeError("boom")]))
    assert len(r["falhas"]) == 1 and r["enviados"] == 0


def test_resumo_e_registro_nao_guardam_texto_nem_numero_inteiro(amb):
    base(amb)
    cadastrar(amb)
    r, _ = rodar(Prov())
    bruto = open(r["registro"], encoding="utf-8").read() + json.dumps(registro(amb))
    assert "5542977773333" not in bruto and "Comunicado" not in bruto and "Olá, tudo bem" not in bruto


# ───────────── gancho da pré-matrícula ─────────────

def test_gancho_nunca_levanta_erro(amb, capsys):
    (amb.dados / "pre_matricula.json").unlink()
    assert cm.avisar_apos_pre_matricula() is None
    assert "NÃO foi executado" in capsys.readouterr().out


def test_gancho_desligado(amb, capsys):
    assert cm.avisar_apos_pre_matricula(ativo=False) is None
    amb.cfg = {"ativo": False}
    assert cm.avisar_apos_pre_matricula() is None and "desligado" in capsys.readouterr().out


def test_gancho_usa_provedor_simulado_por_padrao(amb, monkeypatch):
    monkeypatch.delenv("WHATSAPP_PROVEDOR", raising=False)
    from src.servicos.whatsapp import gerenciador
    monkeypatch.setattr(gerenciador, "_instancia", None)
    r = cm.avisar_apos_pre_matricula()
    assert r["modo"] == "simulado" and r["linha_de_base"] == N_BASE
    monkeypatch.setattr(gerenciador, "_instancia", None)


class _SessaoFalsa:
    ok, page = True, None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_pre_matricula_chama_o_gancho(monkeypatch):
    chamadas = []
    monkeypatch.setattr(pm, "_Sessao", _SessaoFalsa)
    monkeypatch.setattr(pm, "avisar_apos_pre_matricula", lambda ativo=True: chamadas.append(ativo))

    async def pendentes(page, dados_pre_matricula=None, analise=False):
        return {"total_pendentes": 0, "confirmados": 0, "sem_resposta": []}

    async def planilhas(page, mat, intencoes, analise=False):
        return {"111": {}}

    monkeypatch.setattr(pm, "etapa_verificar_pendentes", pendentes)
    monkeypatch.setattr(pm, "completar_json_a_partir_de_planilhas", planilhas)
    asyncio.run(pm.verificar_pendentes_via_login())
    asyncio.run(pm.verificar_pendentes_via_login(avisar_whatsapp=False))
    assert asyncio.run(pm.completar_json_via_login("m.xlsx", "i.xlsx")) == {"111": {}}
    assert chamadas == [True, False, True]


def test_pre_matricula_nao_chama_o_gancho_se_o_login_falha(monkeypatch):
    class Falha(_SessaoFalsa):
        ok = False

    chamadas = []
    monkeypatch.setattr(pm, "_Sessao", Falha)
    monkeypatch.setattr(pm, "avisar_apos_pre_matricula", lambda ativo=True: chamadas.append(ativo))
    assert asyncio.run(pm.verificar_pendentes_via_login()) is None
    assert asyncio.run(pm.completar_json_via_login("m.xlsx", "i.xlsx")) is None
    assert chamadas == []

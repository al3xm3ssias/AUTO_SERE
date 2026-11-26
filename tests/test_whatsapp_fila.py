"""WhatsApp: fila de envio (7b) — intervalo, limite diário, pausa/cancelamento, histórico, modelos e rotas. Sem rede."""
import json
import threading
from datetime import datetime, timedelta

import pytest

from src.comum import modelos_whatsapp as modelos
from src.comum import paths
from src.servicos.whatsapp import ResultadoEnvio, EnvioNaoAutorizadoError, EstadoConexao
from src.servicos.whatsapp import fila as f
from src.web.app import create_app

N1, N2, N3 = "(42) 99999-1111", "(42) 99999-2222", "(42) 99999-3333"


class Prov:
    def __init__(self, nome="blake", conectado=True, falha=None):
        self.nome, self.conectado, self.falha, self.enviados = nome, conectado, falha, []

    def estado(self):
        return EstadoConexao(self.conectado, "x")

    def enviar(self, numero, texto):
        if self.falha == "bloqueado":
            raise EnvioNaoAutorizadoError("bloqueado")
        if self.falha:
            return ResultadoEnvio(False, False, None, self.falha)
        self.enviados.append((numero, texto))
        return ResultadoEnvio(True, self.nome == "simulado", f"id{len(self.enviados)}")


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    dados = tmp_path / "dados" / "2026"
    dados.mkdir(parents=True)
    monkeypatch.setattr(paths, "ano_atual", lambda: "2026")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: dados)
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    return tmp_path


def _fila(prov, agora=None):
    fila = f.FilaWhatsApp(provedor=lambda: prov, agora=agora or datetime.now)
    esperas = []
    fila._dormir = lambda s: (esperas.append(s) or fila._parar.is_set())    # sem esperar de verdade
    fila.esperas = esperas
    return fila


def _rodar(fila):
    fila.iniciar()
    fila.esperar_fim()


def _tres(fila):
    return fila.adicionar([{"numero": n, "nome": f"Pai {i}", "texto": f"Oi {i}"} for i, n in enumerate((N1, N2, N3), 1)])


def test_adicionar_valida_e_nao_repete(amb):
    fila = _fila(Prov())
    r = fila.adicionar([{"numero": N1, "nome": "A", "texto": "Oi"}, {"numero": N1, "nome": "A", "texto": "Oi"},
                        {"numero": "123", "nome": "B", "texto": "Oi"}, {"numero": N2, "nome": "C", "texto": "  "}])
    assert r["adicionados"] == 1 and r["duplicados"] == 1 and [i["nome"] for i in r["invalidos"]] == ["B", "C"]
    assert fila.resumo()["contagem"]["pendente"] == 1


def test_envia_tudo_com_intervalo_e_registra_historico(amb):
    prov = Prov()
    fila = _fila(prov)
    _tres(fila)
    fila.configurar(30, 10)
    _rodar(fila)
    r = fila.resumo()
    assert [t for _, t in prov.enviados] == ["Oi 1", "Oi 2", "Oi 3"] and r["estado"] == f.CONCLUIDA
    assert fila.esperas == [30, 30] and r["contagem"]["enviado"] == 3 and r["enviados_hoje"] == 3 and r["restante_hoje"] == 7
    assert all(i["enviado_em"] and "*" in i["numero"] for i in r["itens"])         # número mascarado na saída


def test_limite_diario_para_e_nao_envia_alem(amb):
    prov = Prov()
    fila = _fila(prov)
    _tres(fila)
    fila.configurar(10, 2, continuar_no_dia_seguinte=False)
    _rodar(fila)
    r = fila.resumo()
    assert len(prov.enviados) == 2 and r["estado"] == f.PAUSADA and "Limite de 2" in r["mensagem"] and r["contagem"]["pendente"] == 1


def test_limite_diario_espera_o_dia_seguinte_e_retoma(amb):
    prov = Prov()
    relogio = {"t": datetime(2026, 11, 22, 15, 0)}
    fila = f.FilaWhatsApp(provedor=lambda: prov, agora=lambda: relogio["t"])
    fila.adicionar([{"numero": N1, "nome": "A", "texto": "1"}, {"numero": N2, "nome": "B", "texto": "2"}])
    fila.configurar(10, 1)
    esperas = []

    def dormir(s):
        esperas.append(s)
        relogio["t"] += timedelta(hours=10)          # a espera atravessa a meia-noite
        return False
    fila._dormir = dormir
    _rodar(fila)
    assert len(prov.enviados) == 2 and fila.resumo()["estado"] == f.CONCLUIDA and any(e > 1 for e in esperas)


def test_pausar_termina_a_mensagem_atual_e_continua_depois(amb):
    prov = Prov()
    fila = _fila(prov)
    _tres(fila)
    fila._dormir = lambda s: (fila.pausar() or True)                    # pede pausa na 1ª espera entre mensagens
    _rodar(fila)
    assert len(prov.enviados) == 1 and fila.resumo()["estado"] == f.PAUSADA and fila.resumo()["contagem"]["pendente"] == 2
    fila._dormir = lambda s: fila._parar.is_set()
    _rodar(fila)
    assert len(prov.enviados) == 3 and fila.resumo()["estado"] == f.CONCLUIDA


def test_cancelar_item_e_pendentes_e_repetir(amb):
    fila = _fila(Prov())
    _tres(fila)
    ids = [i["id"] for i in fila.resumo()["itens"]]
    fila.cancelar_item(ids[0])
    assert fila.resumo()["contagem"]["cancelado"] == 1
    assert fila.cancelar_pendentes() == 2
    fila.repetir_item(ids[0])
    r = fila.resumo()
    assert r["contagem"]["pendente"] == 1 and r["contagem"]["cancelado"] == 2
    with pytest.raises(ValueError, match="pendente"):
        fila.cancelar_item(ids[1])                    # já cancelado em bloco: não é mais pendente


def test_tres_falhas_seguidas_pausam_e_item_fica_para_tentar_de_novo(amb):
    prov = Prov(falha="sem rede")
    fila = _fila(prov)
    fila.adicionar([{"numero": n, "nome": "x", "texto": f"t{n}"} for n in (N1, N2, N3, "(42) 99999-4444")])
    _rodar(fila)
    r = fila.resumo()
    assert r["estado"] == f.PAUSADA and "3 falhas" in r["mensagem"] and r["contagem"]["falhou"] == 3 and r["contagem"]["pendente"] == 1
    assert all(i["erro"] == "sem rede" for i in r["itens"] if i["status"] == "falhou")
    fila.repetir_item(next(i["id"] for i in r["itens"] if i["status"] == "falhou"))
    assert fila.resumo()["contagem"]["pendente"] == 2


def test_envio_real_bloqueado_nao_consome_o_item(amb, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "0")
    fila = _fila(Prov())
    _tres(fila)
    with pytest.raises(ValueError, match="bloqueado"):
        fila.iniciar()
    assert fila.resumo()["contagem"]["pendente"] == 3


def test_provedor_levanta_envio_nao_autorizado_no_meio_pausa_sem_perder_o_item(amb):
    fila = _fila(Prov(falha="bloqueado"))
    _tres(fila)
    _rodar(fila)
    r = fila.resumo()
    assert r["estado"] == f.PAUSADA and r["contagem"]["pendente"] == 3 and r["contagem"]["falhou"] == 0


def test_whatsapp_desconectado_pausa(amb):
    fila = _fila(Prov(conectado=False))
    _tres(fila)
    _rodar(fila)
    assert fila.resumo()["estado"] == f.PAUSADA and "não está conectado" in fila.resumo()["mensagem"] and fila.resumo()["contagem"]["pendente"] == 3


def test_simulado_nao_envia_de_verdade_nem_conta_no_limite_e_pode_voltar(amb):
    prov = Prov(nome="simulado")
    fila = _fila(prov)
    _tres(fila)
    fila.configurar(10, 1)
    _rodar(fila)
    r = fila.resumo()
    assert r["contagem"]["simulado"] == 3 and r["enviados_hoje"] == 0 and r["estado"] == f.CONCLUIDA
    assert set(fila.esperas) == {f.PAUSA_SIMULADO_S}
    fila.repetir_item(r["itens"][0]["id"])
    assert fila.resumo()["contagem"]["pendente"] == 1


def test_enviando_que_sobrou_de_uma_queda_vira_falhou(amb):
    fila = _fila(Prov())
    _tres(fila)
    arquivo = paths.dados_ano_atual() / "WHATSAPP" / "fila.json"
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    dados["itens"][0]["status"] = "enviando"
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    r = fila.resumo()
    assert r["contagem"]["falhou"] == 1 and "Confira no WhatsApp" in r["itens"][0]["erro"]


def test_limpar_historico_preserva_pendentes_e_enviados_de_hoje(amb):
    prov = Prov()
    fila = _fila(prov)
    _tres(fila)
    fila.cancelar_item(fila.resumo()["itens"][2]["id"])
    fila.configurar(10, 1, False)
    _rodar(fila)                                  # envia 1 (limite), deixa 1 pendente, 1 cancelado
    assert fila.limpar_historico() == 1           # só o cancelado sai
    r = fila.resumo()
    assert r["contagem"]["enviado"] == 1 and r["contagem"]["pendente"] == 1


def test_configurar_valida_limites(amb):
    fila = _fila(Prov())
    for args in ((5, 10), (601, 10), (30, 0), (30, 301), ("x", 10)):
        with pytest.raises(ValueError):
            fila.configurar(*args)
    assert fila.configurar(45, 40)["intervalo_s"] == 45


def test_iniciar_sem_pendentes_recusa_e_duas_vezes_nao_duplica(amb):
    fila = _fila(Prov())
    with pytest.raises(ValueError, match="pendentes"):
        fila.iniciar()


def test_arquivo_corrompido_da_erro_claro_e_nao_apaga(amb):
    fila = _fila(Prov())
    arquivo = paths.dados_ano_atual() / "WHATSAPP"
    arquivo.mkdir()
    (arquivo / "fila.json").write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="Fila do WhatsApp"):
        fila.resumo()
    assert (arquivo / "fila.json").read_text(encoding="utf-8") == "{quebrado"


# ───────────── modelos ─────────────

def test_modelos_prontos_criar_ajustar_excluir(amb):
    assert [m["id"] for m in modelos.listar()] == ["livre", "matricula_aprovada", "geo_confirmar_interesse", "chamada_matricula"]
    novo = modelos.salvar("Lembrete", "Olá, $RESPONSAVEL! $ALUNO.")
    assert novo["id"] == "lembrete" and not novo["padrao"]
    with pytest.raises(ValueError, match="desconhecido"):
        modelos.salvar("Ruim", "Oi $NADA")
    with pytest.raises(ValueError, match="Já existe"):
        modelos.salvar("lembrete", "x")
    ajustado = modelos.salvar("Chamada", "Texto novo", "chamada_matricula")
    assert ajustado["personalizado"] and modelos.excluir("chamada_matricula") == "restaurado"
    assert modelos.excluir("lembrete") == "excluido"
    with pytest.raises(ValueError, match="pronto"):
        modelos.excluir("livre")


def test_renderizar_deixa_marcador_sem_valor_a_vista():
    assert modelos.renderizar("Oi $ALUNO $TURMA", {"ALUNO": "Ana"}) == "Oi Ana $TURMA"


# ───────────── rotas ─────────────

@pytest.fixture()
def cli(amb, monkeypatch):
    prov = Prov(nome="simulado")
    monkeypatch.setattr(f, "_instancia", f.FilaWhatsApp(provedor=lambda: prov))
    from src.servicos.whatsapp import gerenciador as g
    from src.servicos.whatsapp.gerenciador import GerenciadorWhatsApp
    monkeypatch.setattr(g, "_instancia", GerenciadorWhatsApp(prov))
    return create_app().test_client()


def test_rotas_fluxo_basico(cli):
    r = cli.post("/web/api/whatsapp/fila/itens", json={"itens": [{"numero": N1, "nome": "Ana", "texto": "Oi"}]})
    assert r.status_code == 200 and r.get_json()["resultado"]["adicionados"] == 1 and r.get_json()["contagem"]["pendente"] == 1
    assert cli.post("/web/api/whatsapp/fila/itens", json={"itens": []}).status_code == 400
    assert cli.post("/web/api/whatsapp/fila/config", json={"intervalo_s": 5, "limite_diario": 10}).status_code == 400
    assert cli.post("/web/api/whatsapp/fila/config", json={"intervalo_s": 20, "limite_diario": 10}).get_json()["config"]["intervalo_s"] == 20
    r = cli.post("/web/api/whatsapp/fila/iniciar", json={})                      # simulado: não exige confirmação
    assert r.status_code == 200
    f.obter_fila().esperar_fim()
    assert cli.get("/web/api/whatsapp/fila").get_json()["contagem"]["simulado"] == 1
    assert "numero" in cli.get("/web/api/whatsapp/fila").get_json()["itens"][0]


def test_rota_iniciar_real_exige_confirmacao(cli, monkeypatch):
    from src.servicos.whatsapp import gerenciador as g
    from src.servicos.whatsapp.gerenciador import GerenciadorWhatsApp
    prov = Prov(nome="blake")
    monkeypatch.setattr(g, "_instancia", GerenciadorWhatsApp(prov))
    monkeypatch.setattr(f, "_instancia", f.FilaWhatsApp(provedor=lambda: prov))
    cli.post("/web/api/whatsapp/fila/itens", json={"itens": [{"numero": N1, "nome": "Ana", "texto": "Oi"}]})
    r = cli.post("/web/api/whatsapp/fila/iniciar", json={})
    assert r.status_code == 400 and r.get_json()["codigo_erro"] == "falta_confirmacao" and prov.enviados == []


def test_rotas_cancelar_repetir_modelos(cli):
    cli.post("/web/api/whatsapp/fila/itens", json={"itens": [{"numero": N1, "nome": "Ana", "texto": "Oi"}]})
    id_ = cli.get("/web/api/whatsapp/fila").get_json()["itens"][0]["id"]
    assert cli.post(f"/web/api/whatsapp/fila/itens/{id_}/cancelar").get_json()["contagem"]["cancelado"] == 1
    assert cli.post(f"/web/api/whatsapp/fila/itens/{id_}/repetir").get_json()["contagem"]["pendente"] == 1
    assert cli.post(f"/web/api/whatsapp/fila/itens/{id_}/apagar").status_code == 404
    assert cli.post(f"/web/api/whatsapp/fila/itens/inexistente/cancelar").status_code == 400
    m = cli.post("/web/api/whatsapp/fila/modelos", json={"nome": "Meu", "texto": "Oi $ALUNO"}).get_json()
    assert m["modelo"]["id"] == "meu" and "ALUNO" in m["marcadores"]
    assert cli.delete("/web/api/whatsapp/fila/modelos/meu").get_json()["acao"] == "excluido"
    assert cli.post("/web/api/whatsapp/fila/modelos", json={"nome": "X", "texto": "$ZZ"}).status_code == 400


def _previsao_2027(**extra):
    dados = {
        "turmas_intencao": {"Infantil IV": [
            {"cpf": "111", "nome": "ANA LIMA", "pos": 1}, {"cpf": "112", "nome": "BETO LIMA", "pos": 2},
            {"cpf": "113", "nome": "CAIO LIMA", "pos": 3}]},
        "cadastros": {
            "111": {"cpf": "111", "nome_aluno": "ANA LIMA", "nome_responsavel": "MARIA", "telefone": N1,
                    "escolas_escolhidas": {"turma": "Infantil IV", "opcoes": [{"situacao": "MATRICULADO"}]}},
            "112": {"cpf": "112", "nome_aluno": "BETO LIMA", "nome_responsavel": "JOAO",
                    "escolas_escolhidas": {"turma": "Infantil IV", "opcoes": [{"situacao": "MATRICULADO"}]}},
            "113": {"cpf": "113", "nome_aluno": "CAIO LIMA", "nome_responsavel": "LUCIA", "telefone": N1,
                    "escolas_escolhidas": {"turma": "Infantil IV", "opcoes": []}}}}
    dados.update(extra)
    (paths.dados_ano_atual() / "previsao_alunos_2027.json").write_text(json.dumps(dados), encoding="utf-8")


def test_da_prematricula_usa_previsao_do_proximo_ano_com_todos_e_marcadores_trocados(cli, amb):
    _previsao_2027()
    d = cli.get("/web/api/whatsapp/fila/prematricula").get_json()
    assert d["ano"] == 2027 and d["arquivo"] == "previsao_alunos_2027.json"
    # vêm todos (inclusive quem aguarda vaga): quem será chamado é filtrado na tela, por turma e posição
    assert {a["nome"]: (a["situacao"], a["tem_telefone"], a["posicao"]) for a in d["alunos"]} == {
        "ANA LIMA": ("matriculado", True, "1"), "BETO LIMA": ("matriculado", False, "2"), "CAIO LIMA": ("pendente", True, "3")}
    r = cli.post("/web/api/whatsapp/fila/da-prematricula", json={"ids": ["111", "112"], "modelo_id": "matricula_aprovada"})
    res = r.get_json()
    assert r.status_code == 200 and res["resultado"]["adicionados"] == 1 and res["resultado"]["sem_telefone"] == ["BETO LIMA"]
    texto = f.obter_fila()._ler()["itens"][0]["texto"]
    assert "ano letivo de 2027 foi aprovada" in texto and "aluno(a) ANA LIMA compareça" in texto and "$" not in texto
    assert cli.post("/web/api/whatsapp/fila/da-prematricula", json={"ids": []}).status_code == 400


def test_da_prematricula_recusa_modelo_com_marcador_sem_dado(cli, amb):
    _previsao_2027()
    cli.post("/web/api/whatsapp/fila/modelos", json={"nome": "Com turma", "texto": "Oi $ALUNO da $TURMA"})
    r = cli.post("/web/api/whatsapp/fila/da-prematricula", json={"ids": ["111"], "modelo_id": "com-turma"}).get_json()
    assert r["resultado"]["adicionados"] == 1 and "$" not in f.obter_fila()._ler()["itens"][0]["texto"]   # turma existe
    dados = json.loads((paths.dados_ano_atual() / "previsao_alunos_2027.json").read_text(encoding="utf-8"))
    dados["cadastros"]["111"]["escolas_escolhidas"]["turma"] = ""
    dados["turmas_intencao"] = {}
    (paths.dados_ano_atual() / "previsao_alunos_2027.json").write_text(json.dumps(dados), encoding="utf-8")
    r2 = cli.post("/web/api/whatsapp/fila/da-prematricula", json={"ids": ["111"], "modelo_id": "com-turma"}).get_json()
    assert r2["resultado"]["adicionados"] == 0 and "$TURMA" in r2["resultado"]["invalidos"][0]["erro"]


def test_mensagem_avulsa_troca_marcadores_e_recusa_o_que_faltar(cli, amb):
    texto = "Ano $PROXIMO_ANO_LETIVO, aluno(a) $ALUNO"
    r = cli.post("/web/api/whatsapp/fila/itens", json={"itens": [{"numero": N1, "nome": "ANA LIMA", "texto": texto}]})
    assert r.status_code == 200 and f.obter_fila()._ler()["itens"][0]["texto"] == "Ano 2027, aluno(a) ANA LIMA"
    r = cli.post("/web/api/whatsapp/fila/itens", json={"itens": [{"numero": N1, "nome": "", "texto": texto}]})
    assert r.status_code == 400 and "$ALUNO" in r.get_json()["erro"]
    r = cli.post("/web/api/whatsapp/fila/itens", json={"itens": [{"numero": N1, "nome": "X", "texto": "Preço R$ 50 e R$50"}]})
    assert r.status_code == 200


def test_da_prematricula_sem_arquivo_da_previsao_explica(cli, amb):
    r = cli.get("/web/api/whatsapp/fila/prematricula")
    assert r.status_code == 400 and "previsao_alunos_2027.json" in r.get_json()["erro"]


def test_da_prematricula_arquivo_antigo_pre_matricula_nao_e_a_fonte(cli, amb):
    (paths.dados_ano_atual() / "pre_matricula.json").write_text(json.dumps({"turmas_intencao": {"X": [{"cpf": "9", "nome": "Z"}]}}), encoding="utf-8")
    assert cli.get("/web/api/whatsapp/fila/prematricula").status_code == 400


def test_modo_consulta_bloqueia_escrita_da_fila(cli, monkeypatch):
    monkeypatch.setattr(paths, "somente_consulta", lambda: True)
    assert cli.post("/web/api/whatsapp/fila/iniciar", json={}).status_code == 403
    assert cli.get("/web/api/whatsapp/fila").status_code == 200


def test_pausa_padrao_entre_mensagens_e_de_5_minutos(amb):
    """Comunicado em massa: sem ajuste salvo, a pausa é de 5 minutos (pedido do usuário, 23/11/2026)."""
    from src.servicos.whatsapp import fila as modulo
    assert modulo.INTERVALO_PADRAO_S == 300
    assert _fila(Prov()).resumo()["config"]["intervalo_s"] == 300


def test_enviada_sem_confirmacao_do_tique_nao_conta_como_falha_nem_pausa(amb):
    """Antes, 3 mensagens que SAÍRAM mas sem o tique viravam 3 "falhas" e a fila pausava sozinha."""
    class SemTique(Prov):
        def enviar(self, numero, texto):
            self.enviados.append((numero, texto))
            return ResultadoEnvio(True, False, aviso="Enviada, sem confirmação do tique.")
    prov = SemTique()
    fila = _fila(prov)
    fila.adicionar([{"numero": n, "nome": f"Pai {i}", "texto": f"Oi {i}"} for i, n in enumerate((N1, N2, N3, "(42) 99999-4444"), 1)])
    _rodar(fila)
    r = fila.resumo()
    assert len(prov.enviados) == 4 and r["estado"] == f.CONCLUIDA and r["contagem"]["enviado"] == 4 and r["contagem"]["falhou"] == 0
    assert all(i["status"] == "enviado" and "tique" in i["aviso"] and not i["erro"] for i in r["itens"])
    assert r["enviados_hoje"] == 4                               # conta no limite do dia


def test_falha_de_verdade_continua_pausando_depois_de_3(amb):
    fila = _fila(Prov(falha="O WhatsApp não abriu a conversa: número sem WhatsApp ou inválido."))
    fila.adicionar([{"numero": n, "nome": f"Pai {i}", "texto": f"Oi {i}"} for i, n in enumerate((N1, N2, N3, "(42) 99999-4444"), 1)])
    _rodar(fila)
    r = fila.resumo()
    assert r["estado"] == f.PAUSADA and r["contagem"]["falhou"] == 3 and r["contagem"]["pendente"] == 1


def test_whatsplay_false_sem_erro_e_enviada_sem_confirmacao_e_com_erro_e_falha(amb):
    from src.servicos.whatsapp.provedor_whatsplay import ProvedorWhatsplay

    class Sessao:
        def __init__(self, erro): self.erro = erro
        def foto(self):
            from src.servicos.whatsapp.monitor import Foto, Situacao
            return Foto(Situacao.CONECTADO, gateway_online=True)
        def limpar_erro(self): pass
        def ultimo_erro(self): return self.erro
        def executar(self, fazer, timeout=0): return False

    sem_erro = ProvedorWhatsplay(Sessao(""), intervalo_min_s=0, dormir=lambda s: None).enviar(N1, "Oi")
    assert sem_erro.ok and sem_erro.aviso and not sem_erro.erro
    com_erro = ProvedorWhatsplay(Sessao("Could not open chat: 5542"), intervalo_min_s=0, dormir=lambda s: None).enviar(N1, "Oi")
    assert not com_erro.ok and "não abriu a conversa" in com_erro.erro
    outro = ProvedorWhatsplay(Sessao("Error sending message: x"), intervalo_min_s=0, dormir=lambda s: None).enviar(N1, "Oi")
    assert not outro.ok and "Não consegui enviar" in outro.erro


def test_da_prematricula_usa_o_texto_da_tela_mesmo_sem_salvar_o_modelo(cli, amb):
    _previsao_2027()
    r = cli.post("/web/api/whatsapp/fila/da-prematricula", json={
        "ids": ["111"], "modelo_id": "matricula_aprovada", "texto": "Oi, responsável de $ALUNO ($TURMA)!"})
    assert r.status_code == 200 and r.get_json()["resultado"]["adicionados"] == 1
    assert f.obter_fila()._ler()["itens"][0]["texto"] == "Oi, responsável de ANA LIMA (Infantil IV)!"
    # sem texto na requisição, vale o do modelo salvo (compatível com o jeito antigo)
    r = cli.post("/web/api/whatsapp/fila/da-prematricula", json={"ids": ["112", "113"], "modelo_id": "matricula_aprovada"})
    assert r.status_code == 200
    # modelo vazio e sem texto: recusa
    r = cli.post("/web/api/whatsapp/fila/da-prematricula", json={"ids": ["111"], "modelo_id": "livre", "texto": "  "})
    assert r.status_code == 400

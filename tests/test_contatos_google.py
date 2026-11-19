"""
Contatos da pré-matrícula no Google Contatos: módulo genérico (google_contacts), regra da escola (contatos_google)
e encaixe na pré-matrícula (etapa_contatos_google, opções da tela).

NADA aqui fala com o Google. A People API é simulada em memória (FakePeople) com as regras que importam: rótulos de
usuário x de sistema, etag exigida na atualização, máscara limitando o que é gravado, contato apagado, item recusado
dentro do lote.
"""
import json

import httplib2
import pytest
from googleapiclient.errors import HttpError

from src.automacao import contatos_google as cg, pre_matricula as pm
from src.comum import google_auth as ga, google_contacts as gc, paths, registro_scripts as reg
from src.comum.google_auth import GoogleErro


def _http_erro(status, msg="x"):
    return HttpError(httplib2.Response({"status": status}), json.dumps({"error": {"message": msg}}).encode())


# ═════════════════════════ People API falsa ═════════════════════════

class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class FakePeople:
    def __init__(self, recusar_nomes=(), falhar_no_lote=None):
        self.grupos = {"contactGroups/myContacts": {"name": "myContacts", "groupType": "SYSTEM_CONTACT_GROUP"}}
        self.pessoas = {}
        self.chamadas = []
        self.recusar_nomes = set(recusar_nomes)
        self.falhar_no_lote = falhar_no_lote          # nº (1, 2, ...) do batchCreate que dá erro de rede/HTTP
        self._n = 0
        self._lotes_criacao = 0

    def _novo(self, prefixo):
        self._n += 1
        return f"{prefixo}{self._n}"

    def novo_rotulo(self, nome):
        rn = f"contactGroups/{self._novo('g')}"
        self.grupos[rn] = {"name": nome, "groupType": "USER_CONTACT_GROUP"}
        return rn

    def nomes_dos_rotulos(self, rn_pessoa):
        return sorted((self.grupos[m]["name"] for m in self.pessoas[rn_pessoa]["membros"]), key=str.casefold)

    def escritas(self):
        return [c for c in self.chamadas if c in ("batchCreate", "batchUpdate", "modify", "createGroup")]

    def contactGroups(self):
        return _Grupos(self)

    def people(self):
        return _Pessoas(self)


class _Grupos:
    def __init__(self, f):
        self.f = f

    def list(self, **params):
        def _go():
            self.f.chamadas.append("listGroups")
            return {"contactGroups": [{"resourceName": rn, **g} for rn, g in self.f.grupos.items()]}
        return _Req(_go)

    def create(self, body):
        def _go():
            self.f.chamadas.append("createGroup")
            return {"resourceName": self.f.novo_rotulo(body["contactGroup"]["name"]), "name": body["contactGroup"]["name"]}
        return _Req(_go)

    def members(self):
        f = self.f

        class _M:
            def modify(self, resourceName, body):
                def _go():
                    f.chamadas.append("modify")
                    for rn in body["resourceNamesToAdd"]:
                        f.pessoas[rn]["membros"].add(resourceName)
                    return {}
                return _Req(_go)
        return _M()


class _Pessoas:
    def __init__(self, f):
        self.f = f

    def batchCreateContacts(self, body):
        def _go():
            self.f.chamadas.append("batchCreate")
            self.f._lotes_criacao += 1
            assert len(body["contacts"]) <= gc.LOTE and body["readMask"]
            if self.f.falhar_no_lote == self.f._lotes_criacao:
                raise _http_erro(500, "boom")
            criados = []
            for item in body["contacts"]:
                p = item["contactPerson"]
                nome = p["names"][0]["givenName"]
                if nome in self.f.recusar_nomes:
                    criados.append({"httpStatusCode": 400, "status": {"message": "dados recusados"}})
                    continue
                rn = f"people/{self.f._novo('c')}"
                membros = {m["contactGroupMembership"]["contactGroupResourceName"] for m in p.pop("memberships")}
                self.f.pessoas[rn] = {**p, "etag": "e1", "membros": membros, "apagado": False}
                criados.append({"httpStatusCode": 200, "person": {"resourceName": rn}})
            return {"createdPeople": criados}
        return _Req(_go)

    def getBatchGet(self, resourceNames, personFields):
        def _go():
            self.f.chamadas.append("getBatchGet")
            assert len(resourceNames) <= gc.LOTE
            resp = []
            for rn in resourceNames:
                p = self.f.pessoas.get(rn)
                if p is None:
                    resp.append({"requestedResourceName": rn, "httpStatusCode": 404, "status": {"message": "not found"}})
                else:
                    resp.append({"requestedResourceName": rn, "httpStatusCode": 200,
                                 "person": {"resourceName": rn, "etag": p["etag"], "metadata": {"deleted": p["apagado"]}}})
            return {"responses": resp}
        return _Req(_go)

    def batchUpdateContacts(self, body):
        def _go():
            self.f.chamadas.append("batchUpdate")
            campos = body["updateMask"].split(",")
            assert all(campos) and body["readMask"]
            resultado = {}
            for rn, nova in body["contacts"].items():
                atual = self.f.pessoas[rn]
                if nova["etag"] != atual["etag"]:
                    resultado[rn] = {"httpStatusCode": 400, "status": {"message": "etag desatualizada"}}
                    continue
                for c in campos:
                    if c in nova:
                        atual[c] = nova[c]
                atual["etag"] = atual["etag"] + "x"
                resultado[rn] = {"httpStatusCode": 200, "person": {"resourceName": rn}}
            return {"updateResult": resultado}
        return _Req(_go)


# ═════════════════════════ dados de exemplo ═════════════════════════

def contato(chave="111", cpfs=("1", "2"), nome="3º Ano - 2026 - RESPONSAVEL DO IRMAO UM E DO IRMAO DOIS",
            email="mae@exemplo.com", telefone="111", cep="84000-000", responsavel="MAE", endereco="Rua A, 10, 84000-000"):
    return {"chave": chave, "cpfs": list(cpfs), "nome": nome, "email": email, "telefone": telefone, "cep": cep,
            "responsavel": responsavel, "endereco": endereco}


def outro(n):
    return contato(chave=f"9{n}", cpfs=(f"9{n}",), nome=f"1º Ano - 2026 - RESPONSAVEL DO ALUNO {n}", telefone=f"9{n}",
                   email="", endereco="")


def rodar(contatos, mapa, fake, *, alvo="atual", ano=2026, simulacao=False, **kw):
    return cg.sincronizar(contatos, alvo=alvo, ano=ano, caminho_mapa=mapa, simulacao=simulacao, servico=fake, pausa=0,
                          imprimir=lambda *_a: None, **kw)


@pytest.fixture
def mapa(tmp_path):
    return tmp_path / "google_contatos.json"


# ═════════════════════════ rótulos ═════════════════════════

def test_rotulos_ano_vigente_e_proximo_ano():
    assert cg.rotulos_do_alvo("atual", 2026) == ["2026"]
    assert cg.rotulos_do_alvo("proximo", 2027) == ["Pré-matrícula 2027", "Aluno 2027"]


def test_alvo_atual_cria_o_contato_com_o_rotulo_do_ano_e_em_meus_contatos(mapa):
    f = FakePeople()
    r = rodar([contato()], mapa, f)
    assert (r["criados"], r["atualizados"], r["iguais"], r["erros"]) == (1, 0, 0, [])
    rn = next(iter(f.pessoas))
    assert f.nomes_dos_rotulos(rn) == ["2026", "myContacts"]


def test_alvo_proximo_cria_o_contato_com_os_dois_rotulos(mapa):
    f = FakePeople()
    rodar([contato(nome="1º Ano - 2027 - RESPONSAVEL DO X")], mapa, f, alvo="proximo", ano=2027)
    rn = next(iter(f.pessoas))
    assert f.nomes_dos_rotulos(rn) == ["Aluno 2027", "myContacts", "Pré-matrícula 2027"]


def test_rotulo_que_ja_existe_e_reaproveitado_sem_diferenciar_maiusculas(mapa):
    f = FakePeople()
    existente = f.novo_rotulo("PRÉ-MATRÍCULA 2027")
    rodar([contato()], mapa, f, alvo="proximo", ano=2027)
    assert f.chamadas.count("createGroup") == 1                    # só "Aluno 2027" foi criado
    assert existente in f.pessoas[next(iter(f.pessoas))]["membros"]


def test_rotulo_de_sistema_com_o_mesmo_nome_nao_e_confundido(mapa):
    f = FakePeople()
    f.grupos["contactGroups/sistema"] = {"name": "2026", "groupType": "SYSTEM_CONTACT_GROUP"}
    rodar([contato()], mapa, f)
    assert f.chamadas.count("createGroup") == 1


# ═════════════════════════ campos do contato ═════════════════════════

def test_campos_iguais_aos_do_csv_e_vazios_omitidos(mapa):
    f = FakePeople()
    rodar([contato(), outro(1)], mapa, f)
    p1, p2 = f.pessoas.values()
    assert p1["names"] == [{"givenName": "3º Ano - 2026 - RESPONSAVEL DO IRMAO UM E DO IRMAO DOIS"}]
    assert p1["emailAddresses"] == [{"value": "mae@exemplo.com", "type": "home"}]
    assert p1["phoneNumbers"] == [{"value": "111", "type": "mobile"}]
    assert p1["addresses"] == [{"postalCode": "84000-000", "type": "home"}]
    assert p1["relations"] == [{"person": "MAE"}]
    assert p1["userDefined"] == [{"key": "Endereço Completo", "value": "Rua A, 10, 84000-000"}]
    assert "emailAddresses" not in p2 and "userDefined" not in p2 and "addresses" in p2


def test_contato_sem_nome_e_recusado_antes_de_enviar():
    with pytest.raises(gc.ContatosValidacaoErro):
        gc.montar_pessoa(nome="   ")


# ═════════════════════════ não duplica, atualiza, recria ═════════════════════════

def test_segunda_rodada_sem_mudanca_nao_escreve_nada(mapa):
    f = FakePeople()
    rodar([contato(), outro(1)], mapa, f)
    f.chamadas.clear()
    r = rodar([contato(), outro(1)], mapa, f)
    assert (r["criados"], r["atualizados"], r["iguais"]) == (0, 0, 2)
    assert f.escritas() == [] and len(f.pessoas) == 2


def test_telefone_corrigido_atualiza_o_mesmo_contato_em_vez_de_criar_outro(mapa):
    f = FakePeople()
    rodar([contato()], mapa, f)
    rn = next(iter(f.pessoas))
    r = rodar([contato(chave="222", telefone="222")], mapa, f)                  # chave mudou; o aluno (CPF) é o mesmo
    assert (r["criados"], r["atualizados"]) == (0, 1) and list(f.pessoas) == [rn]
    assert f.pessoas[rn]["phoneNumbers"][0]["value"] == "222"
    assert json.loads(mapa.read_text("utf-8"))["contatos"][0]["chave"] == "222"


def test_atualizacao_nao_apaga_campo_que_ficou_vazio(mapa):
    f = FakePeople()
    rodar([contato()], mapa, f)
    rn = next(iter(f.pessoas))
    rodar([contato(email="", telefone="333")], mapa, f)
    assert f.pessoas[rn]["emailAddresses"][0]["value"] == "mae@exemplo.com"      # e-mail antigo preservado
    assert f.pessoas[rn]["phoneNumbers"][0]["value"] == "333"


def test_irmao_novo_muda_o_nome_e_atualiza(mapa):
    f = FakePeople()
    rodar([contato(cpfs=("1",), nome="3º Ano - 2026 - RESPONSAVEL DO IRMAO UM")], mapa, f)
    r = rodar([contato()], mapa, f)
    assert (r["criados"], r["atualizados"]) == (0, 1) and len(f.pessoas) == 1


def test_contato_apagado_no_google_e_criado_de_novo(mapa):
    f = FakePeople()
    rodar([contato(), outro(1)], mapa, f)
    apagado = next(iter(f.pessoas))
    del f.pessoas[apagado]
    r = rodar([contato(), outro(1)], mapa, f)
    assert (r["criados"], r["iguais"]) == (1, 1) and len(f.pessoas) == 2
    registrados = {e["resource_name"] for e in json.loads(mapa.read_text("utf-8"))["contatos"]}
    assert registrados == set(f.pessoas) and apagado not in registrados


def test_contato_na_lixeira_tambem_e_recriado(mapa):
    f = FakePeople()
    rodar([contato()], mapa, f)
    next(iter(f.pessoas.values()))["apagado"] = True
    assert rodar([contato()], mapa, f)["criados"] == 1


def test_aluno_que_saiu_dos_dados_nao_e_removido_do_google(mapa):
    f = FakePeople()
    rodar([contato(), outro(1)], mapa, f)
    r = rodar([contato()], mapa, f)
    assert r["fora_da_rodada"] == 1 and len(f.pessoas) == 2
    assert len(json.loads(mapa.read_text("utf-8"))["contatos"]) == 2


def test_virada_de_ano_proximo_vira_atual_reconhece_o_contato_e_acrescenta_o_rotulo(mapa):
    f = FakePeople()
    c = contato(nome="1º Ano - 2027 - RESPONSAVEL DO X")
    rodar([c], mapa, f, alvo="proximo", ano=2027)
    rn = next(iter(f.pessoas))
    r = rodar([c], mapa, f, alvo="atual", ano=2027)                           # em 2027, 2027 é o ano vigente
    assert (r["criados"], r["rotulados"]) == (0, 1) and len(f.pessoas) == 1
    assert f.nomes_dos_rotulos(rn) == ["2027", "Aluno 2027", "myContacts", "Pré-matrícula 2027"]
    assert rodar([c], mapa, f, alvo="atual", ano=2027)["rotulados"] == 0       # só acrescenta uma vez


def test_mesmo_aluno_em_anos_diferentes_gera_contatos_diferentes(mapa):
    f = FakePeople()
    rodar([contato()], mapa, f, alvo="atual", ano=2026)
    rodar([contato(nome="4º Ano - 2027 - RESPONSAVEL DO IRMAO UM E DO IRMAO DOIS")], mapa, f, alvo="proximo", ano=2027)
    assert len(f.pessoas) == 2


def test_entrada_do_mapa_casa_uma_vez_so(mapa):
    f = FakePeople()
    rodar([contato(chave="111", cpfs=("1", "2"))], mapa, f)
    r = rodar([contato(chave="111", cpfs=("1",), nome="A"), contato(chave="555", cpfs=("2",), nome="B", telefone="555")], mapa, f)
    assert (r["criados"], r["atualizados"]) == (1, 1) and len(f.pessoas) == 2


# ═════════════════════════ simulação ═════════════════════════

def test_simulacao_nao_autentica_nao_fala_com_o_google_e_nao_grava(mapa, monkeypatch):
    monkeypatch.setattr(gc, "abrir_servico", lambda **_k: pytest.fail("a simulação não pode autenticar"))
    r = cg.sincronizar([contato(), outro(1)], alvo="atual", ano=2026, caminho_mapa=mapa, simulacao=True,
                       imprimir=lambda *_a: None)
    assert (r["simulacao"], r["criados"], r["atualizados"]) == (True, 2, 0) and not mapa.exists()


def test_simulacao_conta_o_que_ja_esta_em_dia(mapa):
    f = FakePeople()
    rodar([contato()], mapa, f)
    r = cg.sincronizar([contato(), outro(1)], alvo="atual", ano=2026, caminho_mapa=mapa, simulacao=True,
                       imprimir=lambda *_a: None)
    assert (r["criados"], r["iguais"]) == (1, 1)


# ═════════════════════════ robustez ═════════════════════════

def test_contato_recusado_no_lote_vira_erro_e_nao_entra_no_mapa(mapa):
    f = FakePeople(recusar_nomes={outro(1)["nome"]})
    r = rodar([contato(), outro(1), outro(2)], mapa, f)
    assert (r["criados"], len(r["erros"])) == (2, 1) and "ALUNO 1" in r["erros"][0]
    assert len(json.loads(mapa.read_text("utf-8"))["contatos"]) == 2
    r2 = rodar([contato(), outro(1), outro(2)], mapa, f)                       # o recusado é tentado de novo, sem duplicar
    assert (r2["criados"], r2["iguais"], len(r2["erros"])) == (0, 2, 1)
    f.recusar_nomes.clear()
    assert rodar([contato(), outro(1), outro(2)], mapa, f)["criados"] == 1 and len(f.pessoas) == 3


def test_mapa_e_gravado_a_cada_lote_e_uma_queda_nao_gera_duplicados(mapa, monkeypatch):
    monkeypatch.setattr(gc, "LOTE", 2)
    f = FakePeople(falhar_no_lote=2)
    with pytest.raises(GoogleErro):
        rodar([outro(i) for i in range(5)], mapa, f)
    assert len(json.loads(mapa.read_text("utf-8"))["contatos"]) == 2           # o 1º lote já estava registrado
    f.falhar_no_lote = None
    r = rodar([outro(i) for i in range(5)], mapa, f)
    assert (r["criados"], r["iguais"]) == (3, 2) and len(f.pessoas) == 5


def test_lotes_respeitam_o_limite_da_api(mapa, monkeypatch):
    monkeypatch.setattr(gc, "LOTE", 3)
    f = FakePeople()
    rodar([outro(i) for i in range(7)], mapa, f)
    assert f.chamadas.count("batchCreate") == 3 and len(f.pessoas) == 7


def test_mapa_corrompido_nao_e_tocado_e_nada_e_enviado(mapa):
    mapa.write_text("{isso nao e json", encoding="utf-8")
    f = FakePeople()
    with pytest.raises(cg.MapaContatosCorrompidoError):
        rodar([contato()], mapa, f)
    assert mapa.read_text("utf-8") == "{isso nao e json" and f.pessoas == {} and f.escritas() == []


def test_mapa_com_formato_errado_e_recusado(mapa):
    mapa.write_text(json.dumps({"contatos": "x"}), encoding="utf-8")
    with pytest.raises(cg.MapaContatosCorrompidoError):
        rodar([contato()], mapa, FakePeople())


def test_mapa_nao_guarda_cpf_em_claro(mapa):
    rodar([contato(cpfs=("123.456.789-09",))], mapa, FakePeople())
    assert "123" not in mapa.read_text("utf-8") and "789" not in mapa.read_text("utf-8")


# ═════════════════════════ google_contacts: erros e credenciais ═════════════════════════

def test_conta_de_servico_e_recusada_com_mensagem_pronta(monkeypatch):
    monkeypatch.setattr(gc, "detectar_modo", lambda *_a, **_k: ga.MODO_CONTA_SERVICO)
    with pytest.raises(gc.ContatosAcessoErro, match="conta Google pessoal"):
        gc.abrir_servico()


def test_token_de_contatos_fica_em_arquivo_proprio(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "meu.json"))
    assert ga.caminho_token_contatos() == tmp_path / "meu_contatos.json"
    assert ga.caminho_token_contatos() not in (ga.caminho_token(), ga.caminho_token_drive())
    assert ga.ESCOPO_CONTATOS == "https://www.googleapis.com/auth/contacts"


@pytest.mark.parametrize("status,msg,classe,trecho", [
    (401, "x", gc.ContatosAutenticacaoErro, "google_token_contatos.json"),
    (403, "People API has not been used in project 1 before or it is disabled", gc.ContatosAcessoErro, "People API"),
    (403, "Request had insufficient authentication scopes.", gc.ContatosAcessoErro, "permissão de contatos"),
    (403, "Quota exceeded", gc.ContatosErro, "Limite de uso"),
    (400, "campo inválido", gc.ContatosValidacaoErro, "campo inválido"),
    (429, "x", gc.ContatosErro, "429"),
    (500, "x", gc.ContatosErro, "HTTP 500"),
])
def test_erros_do_google_viram_mensagem_em_portugues(status, msg, classe, trecho):
    erro = gc._traduzir(_http_erro(status, msg), "criar os contatos")
    assert isinstance(erro, classe) and trecho in str(erro)


def test_queda_de_conexao_vira_erro_do_google():
    class _Cai:
        def execute(self, num_retries=0):
            raise ConnectionError("sem rede")
    with pytest.raises(gc.ContatosErro, match="Sem conexão"):
        gc._executar(_Cai(), "criar os contatos")


def test_mascara_so_tem_campos_preenchidos():
    assert gc.mascara_da_pessoa(gc.montar_pessoa(nome="A")) == "names"
    assert gc.mascara_da_pessoa(gc.montar_pessoa(nome="A", telefone="1", cep="84000-000")) == "names,phoneNumbers,addresses"


# ═════════════════════════ pré-matrícula: agrupamento, etapa e tela ═════════════════════════

def _cad(cpf, resp, tel="", email="", endereco="Rua A, 10, 84000-000"):
    return {"cpf": cpf, "nome_responsavel": resp, "telefone": tel, "email": email, "endereco": endereco}


def _dados_pre():
    turmas = {"3º Ano do Ensino Fundamental": [{"cpf": "1", "nome": "IRMAO UM"}, {"cpf": "2", "nome": "IRMAO DOIS"},
                                              {"cpf": "3", "nome": "SOZINHA"}],
              "1º Ano do Ensino Fundamental": [{"cpf": "4", "nome": "SEM RESP"}]}
    cads = {"1": _cad("1", "MAE", "111", "mae@exemplo.com"), "2": _cad("2", "MAE", "111", "mae@exemplo.com"),
            "3": _cad("3", "OUTRA"), "4": _cad("4", "")}
    return cads, {"turmas_intencao": turmas}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: tmp_path)
    monkeypatch.setattr(paths, "ano_atual", lambda: 2026)
    monkeypatch.setattr(paths, "DADOS_DIR", tmp_path)
    return tmp_path


def test_contatos_para_google_tem_o_mesmo_agrupamento_e_nome_do_csv(ambiente):
    cads, base = _dados_pre()
    csv_ = pm.processar_contatos(cads, base)
    goo = pm.contatos_para_google(cads, base)
    assert [c["First Name"] for c in csv_] == [g["nome"] for g in goo]
    assert [c["Phone 1 - Value"] for c in csv_] == [g["telefone"] for g in goo]
    assert [c["Address 1 - Postal Code"] for c in csv_] == [g["cep"] for g in goo]
    mae = goo[0]
    assert mae["chave"] == "111" and mae["cpfs"] == ["1", "2"] and mae["responsavel"] == "MAE"
    assert goo[1]["chave"] == "outra"                                          # sem telefone agrupa pelo nome


def test_etapa_envia_ao_google_com_o_rotulo_do_alvo(ambiente, monkeypatch):
    f = FakePeople()
    monkeypatch.setattr(gc, "abrir_servico", lambda **_k: f)
    monkeypatch.setattr(gc.time, "sleep", lambda *_a: None)
    cads, base = _dados_pre()
    r = pm.etapa_contatos_google(cads, base)
    assert r["criados"] == 2 and r["rotulos"] == ["2026"]
    assert (ambiente / "google_contatos.json").exists()
    assert pm.etapa_contatos_google(cads, base)["iguais"] == 2                 # reexecutar não duplica


def test_etapa_no_alvo_proximo_usa_os_dois_rotulos(ambiente, monkeypatch):
    f = FakePeople()
    monkeypatch.setattr(gc, "abrir_servico", lambda **_k: f)
    monkeypatch.setattr(gc.time, "sleep", lambda *_a: None)
    cads, base = _dados_pre()
    token = pm.definir_alvo("proximo")
    try:
        r = pm.etapa_contatos_google(cads, base)
    finally:
        pm._ALVO.reset(token)
    assert r["rotulos"] == ["Pré-matrícula 2027", "Aluno 2027"]
    assert all("2027" in n for n in (g["name"] for g in f.grupos.values() if g["groupType"] == "USER_CONTACT_GROUP"))


def test_etapa_nunca_derruba_o_processo_quando_o_google_falha(ambiente, monkeypatch, capsys):
    def _falha(**_k):
        raise gc.ContatosAcessoErro("A People API não está ativada")
    monkeypatch.setattr(gc, "abrir_servico", _falha)
    cads, base = _dados_pre()
    assert pm.etapa_contatos_google(cads, base) == {"erro": True}
    saida = capsys.readouterr().out
    assert "não está ativada" in saida and "CSV" in saida


def test_etapa_nunca_derruba_o_processo_com_erro_inesperado(ambiente, monkeypatch):
    monkeypatch.setattr(cg, "sincronizar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    cads, base = _dados_pre()
    assert pm.etapa_contatos_google(cads, base) == {"erro": True}


def test_etapa_em_simulacao_nao_chama_o_google(ambiente, monkeypatch):
    monkeypatch.setattr(gc, "abrir_servico", lambda **_k: pytest.fail("simulação não autentica"))
    cads, base = _dados_pre()
    r = pm.etapa_contatos_google(cads, base, simulacao=True)
    assert r["simulacao"] and r["criados"] == 2 and not (ambiente / "google_contatos.json").exists()


def test_etapa_sem_contatos_nao_faz_nada(ambiente, monkeypatch):
    monkeypatch.setattr(gc, "abrir_servico", lambda **_k: pytest.fail("sem contatos não autentica"))
    assert pm.etapa_contatos_google({}, {"turmas_intencao": {}}) is None


def test_tela_da_pre_matricula_tem_as_duas_opcoes_desligadas_por_padrao():
    extras = {e["nome"]: e for e in reg.REGISTRO["prematricula_completa"].extras()}
    assert extras["enviar_google_contatos"]["padrao"] is False
    assert extras["simular_google_contatos"]["padrao"] is False


def test_opcoes_da_tela_chegam_ao_processo(monkeypatch):
    o = type("O", (), {"debug": False})()
    plano = reg._plano_prematricula(o, {"enviar_google_contatos": True}, None, None)
    assert plano.kwargs == {"analise": False, "pular_pendentes": False, "enviar_google_contatos": True}
    plano = reg._plano_prematricula(o, {"simular_google_contatos": True}, None, None)
    assert plano.kwargs["simular_google_contatos"] is True and "enviar_google_contatos" not in plano.kwargs
    # desligadas (padrão): o contrato antigo do plano não muda
    assert reg._plano_prematricula(o, {}, None, None).kwargs == {"analise": False, "pular_pendentes": False}


# ═════════════════════════ cliente OFICIAL (googleapiclient) sobre transporte HTTP falso ═════════════════════════
# Confere os pedidos reais montados (endereço, parâmetros, corpo) contra o documento de descrição da People API que vem
# com a biblioteca: se um método ou parâmetro não existir na API, o cliente oficial levanta erro aqui.

class _Transporte(httplib2.Http):
    def __init__(self, respostas):
        super().__init__()
        self.pedidos, self.respostas = [], respostas

    def request(self, uri, method="GET", body=None, headers=None, **kw):
        from urllib.parse import parse_qs, urlparse
        pr = urlparse(uri)
        self.pedidos.append((method, pr.path, parse_qs(pr.query), json.loads(body) if body else None))
        return (httplib2.Response({"status": "200", "content-type": "application/json"}),
                json.dumps(self.respostas.get(pr.path, {})).encode())


def test_pedidos_montados_pelo_cliente_oficial():
    from googleapiclient.discovery import build
    http = _Transporte({
        "/v1/contactGroups": {"contactGroups": [{"resourceName": "contactGroups/1", "name": "2026", "groupType": "USER_CONTACT_GROUP"}]},
        "/v1/people:batchCreateContacts": {"createdPeople": [{"httpStatusCode": 200, "person": {"resourceName": "people/c1"}}]},
        "/v1/people:batchGet": {"responses": [{"httpStatusCode": 200, "person": {"resourceName": "people/c1", "etag": "E1"}}]},
        "/v1/people:batchUpdateContacts": {"updateResult": {"people/c1": {"httpStatusCode": 200}}},
    })
    api = build("people", "v1", http=http, developerKey="x", cache_discovery=False)
    pessoa = gc.montar_pessoa(nome="N", telefone="1", cep="84000-000", relacao="MAE", extras={"Endereço Completo": "Rua"})

    assert gc.listar_rotulos(api) == {"2026": "contactGroups/1"}
    assert gc.criar_contatos(api, [pessoa], ["contactGroups/1"], pausa=0) == [{"resource_name": "people/c1", "erro": ""}]
    assert gc.buscar_etags(api, ["people/c1"]) == {"people/c1": "E1"}
    assert gc.atualizar_contatos(api, [("people/c1", "E1", pessoa)], pausa=0) == {"people/c1": ""}
    gc.adicionar_aos_rotulos(api, "contactGroups/1", ["people/c1"])

    (m1, c1, q1, _), (m2, c2, _, b2), (m3, c3, q3, _), (m4, c4, _, b4), (m5, c5, _, b5) = http.pedidos
    assert (m1, c1, q1["groupFields"]) == ("GET", "/v1/contactGroups", ["name,groupType"])
    assert (m2, c2) == ("POST", "/v1/people:batchCreateContacts") and b2["readMask"] == "names"
    filiacoes = b2["contacts"][0]["contactPerson"]["memberships"]
    assert [f["contactGroupMembership"]["contactGroupResourceName"] for f in filiacoes] == ["contactGroups/myContacts", "contactGroups/1"]
    assert (m3, c3, q3["resourceNames"], q3["personFields"]) == ("GET", "/v1/people:batchGet", ["people/c1"], ["names,metadata"])
    assert (m4, c4) == ("POST", "/v1/people:batchUpdateContacts")
    assert b4["updateMask"] == "names,phoneNumbers,addresses,relations,userDefined" and b4["contacts"]["people/c1"]["etag"] == "E1"
    assert (m5, c5, b5) == ("POST", "/v1/contactGroups/1/members:modify", {"resourceNamesToAdd": ["people/c1"]})


# O que só se prova com credenciais reais (People API ativada, escopo autorizado): rodar à mão, com a opção
# "Simulação" desligada, numa conta de teste, e conferir os contatos e os rótulos no Google Contatos.
@pytest.mark.skip(reason="exige credenciais reais do Google e escreve na conta autorizada")
def test_real_cria_atualiza_e_nao_duplica():
    raise NotImplementedError

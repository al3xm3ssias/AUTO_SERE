"""Testes dos dados da escola, da consulta de CEP e das rotas do assistente."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import cep_consulta, configuracao, escola  # noqa: E402
from src.web.app import create_app  # noqa: E402


@pytest.fixture()
def config_tmp(tmp_path, monkeypatch):
    """Redireciona config_usuario.json para uma pasta temporária."""
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    return tmp_path


@pytest.fixture()
def cliente(config_tmp):
    return create_app().test_client()


VALIDO = {"nome": "Escola Teste", "cep": "84016-630", "logradouro": "Av. Antônio Saad", "numero": "935"}


# ── validação ───────────────────────────────────────────────────────────────

def test_validar_normaliza_e_monta_endereco():
    d = escola.validar({**VALIDO, "nome": "  Escola   Teste ", "uf": "pr"})
    assert d["nome"] == "Escola Teste"
    assert d["cep"] == "84016630"
    assert d["uf"] == "PR"
    assert d["endereco"] == "Av. Antônio Saad, 935"


def test_obrigatorios_sao_so_nome_cep_e_logradouro():
    with pytest.raises(escola.ValidacaoErro) as e:
        escola.validar({})
    assert set(e.value.erros) == {"nome", "cep", "logradouro"}
    escola.validar({"nome": "X", "cep": "84016630", "logradouro": "Rua A"})  # sem número, UF, etc.


@pytest.mark.parametrize("campo,valor", [
    ("cep", "123"), ("uf", "XX"), ("email", "sem-arroba"),
    ("telefone", "123"), ("inep", "12ab"),
])
def test_campos_invalidos(campo, valor):
    with pytest.raises(escola.ValidacaoErro) as e:
        escola.validar({**VALIDO, campo: valor})
    assert campo in e.value.erros


def test_opcionais_validos_passam():
    d = escola.validar({**VALIDO, "email": "a@b.com", "telefone": "(42) 3200-0000",
                        "inep": "41000000", "responsavel": "Fulana"})
    assert d["inep"] == "41000000" and d["responsavel"] == "Fulana"


# ── persistência e compatibilidade com configuracao.py ──────────────────────

def test_salvar_e_carregar(config_tmp):
    assert escola.configurada() is False
    escola.salvar(VALIDO)
    d = escola.carregar()
    assert d["nome"] == "Escola Teste" and d["cep"] == "84016630"
    assert d["cep_formatado"] == "84016-630"
    assert escola.configurada() is True
    # as funções antigas de configuracao.py continuam enxergando os 3 campos
    antigo = configuracao.unidade_escolar()
    assert antigo["nome"] and antigo["endereco"] == "Av. Antônio Saad, 935" and antigo["cep"] == "84016630"


def test_salvar_nao_apaga_outras_chaves_da_config(config_tmp):
    configuracao.definir_pasta_modelos(str(config_tmp))
    escola.salvar(VALIDO)
    assert configuracao.carregar_configuracao()["pasta_modelos"] == str(config_tmp)


def test_carregar_aceita_config_antiga_de_tres_campos(config_tmp):
    configuracao.definir_unidade_escolar("Escola Velha", "Rua Velha, 10", "84000000")
    d = escola.carregar()
    assert d["nome"] == "Escola Velha" and d["logradouro"] == "Rua Velha, 10"


# ── consulta de CEP (rede simulada) ─────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, corpo=None):
        self.status_code, self._corpo = status, corpo or {}

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_cep_viacep(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **k: _Resp(corpo={
        "logradouro": "Avenida Antônio Saad", "bairro": "Jardim Carvalho",
        "localidade": "Ponta Grossa", "uf": "pr"}))
    d = cep_consulta.consultar_cep("84016-630")
    assert d == {"cep": "84016630", "logradouro": "Avenida Antônio Saad",
                 "bairro": "Jardim Carvalho", "cidade": "Ponta Grossa", "uf": "PR"}


def test_cep_cai_para_brasilapi_se_viacep_falhar(monkeypatch):
    def falso(url, **k):
        if "viacep" in url:
            raise requests.ConnectionError("fora do ar")
        return _Resp(corpo={"street": "Rua B", "neighborhood": "Centro", "city": "Cidade", "state": "SP"})
    monkeypatch.setattr(requests, "get", falso)
    assert cep_consulta.consultar_cep("01001000")["cidade"] == "Cidade"


def test_cep_inexistente(monkeypatch):
    def falso(url, **k):
        return _Resp(corpo={"erro": True}) if "viacep" in url else _Resp(status=404)
    monkeypatch.setattr(requests, "get", falso)
    with pytest.raises(cep_consulta.CepNaoEncontrado):
        cep_consulta.consultar_cep("99999999")


def test_cep_sem_internet(monkeypatch):
    def falso(url, **k):
        raise requests.ConnectionError("sem rede")
    monkeypatch.setattr(requests, "get", falso)
    with pytest.raises(cep_consulta.ErroConsultaCep):
        cep_consulta.consultar_cep("84016630")


def test_cep_invalido_nem_consulta_a_rede(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("não deveria consultar"))
    with pytest.raises(cep_consulta.CepInvalido):
        cep_consulta.consultar_cep("123")


# ── rotas ───────────────────────────────────────────────────────────────────

def test_rota_ler_vazio_e_salvar(cliente):
    r = cliente.get("/web/api/configuracoes/escola").get_json()
    assert r["configurada"] is False and r["dados"]["nome"] == ""
    r = cliente.post("/web/api/configuracoes/escola", json=VALIDO)
    assert r.status_code == 200 and r.get_json()["configurada"] is True
    assert cliente.get("/web/api/configuracoes/escola").get_json()["dados"]["cep_formatado"] == "84016-630"


def test_rota_salvar_invalido_devolve_400_com_campos(cliente):
    r = cliente.post("/web/api/configuracoes/escola", json={"nome": "X", "cep": "1"})
    assert r.status_code == 400
    assert {"cep", "logradouro"} <= set(r.get_json()["campos"])


def test_rota_cep(cliente, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **k: _Resp(corpo={
        "logradouro": "Rua X", "bairro": "B", "localidade": "C", "uf": "PR"}))
    assert cliente.get("/web/api/cep/84016630").get_json()["logradouro"] == "Rua X"
    assert cliente.get("/web/api/cep/12").status_code == 400


def test_wizard_tem_passo_escola(cliente):
    assert cliente.get("/web/api/wizard/status").get_json()["escola"] is False
    assert cliente.post("/web/api/wizard/escola/executar", json=VALIDO).status_code == 200
    assert cliente.get("/web/api/wizard/status").get_json()["escola"] is True
    assert cliente.post("/web/api/wizard/escola/executar", json={}).status_code == 400

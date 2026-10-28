"""
cep_consulta.py — consulta de endereço por CEP
===============================================
Usada pelo assistente de configuração (dados da escola) para preencher
logradouro, bairro, cidade e UF a partir do CEP.

Fontes, nesta ordem: ViaCEP e BrasilAPI. Se uma falhar (fora do ar, sem
internet), tenta a outra. Não depende de geopy (ao contrário de
src.comum.cep_api, que é a análise de distância aluno↔escola).
"""
from __future__ import annotations

import re

import requests


class CepInvalido(ValueError):
    """O CEP informado não tem 8 dígitos."""


class CepNaoEncontrado(LookupError):
    """Nenhuma fonte conhece esse CEP."""


class ErroConsultaCep(RuntimeError):
    """Não foi possível consultar (sem internet, serviço fora do ar...)."""


def normalizar_cep(valor) -> str | None:
    """Devolve só os 8 dígitos, ou None se não for um CEP válido."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if len(digitos) == 8 else None


def _viacep(cep: str, timeout: float) -> dict:
    r = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if j.get("erro"):
        raise CepNaoEncontrado(cep)
    return {
        "cep": cep,
        "logradouro": (j.get("logradouro") or "").strip(),
        "bairro": (j.get("bairro") or "").strip(),
        "cidade": (j.get("localidade") or "").strip(),
        "uf": (j.get("uf") or "").strip().upper(),
    }


def _brasilapi(cep: str, timeout: float) -> dict:
    r = requests.get(f"https://brasilapi.com.br/api/cep/v2/{cep}", timeout=timeout)
    if r.status_code == 404:
        raise CepNaoEncontrado(cep)
    r.raise_for_status()
    j = r.json()
    return {
        "cep": cep,
        "logradouro": (j.get("street") or "").strip(),
        "bairro": (j.get("neighborhood") or "").strip(),
        "cidade": (j.get("city") or "").strip(),
        "uf": (j.get("state") or "").strip().upper(),
    }


def consultar_cep(cep, timeout: float = 6.0) -> dict:
    """
    Consulta o CEP. Devolve {"cep", "logradouro", "bairro", "cidade", "uf"}.
    Levanta CepInvalido, CepNaoEncontrado ou ErroConsultaCep.
    """
    digitos = normalizar_cep(cep)
    if digitos is None:
        raise CepInvalido("CEP deve ter 8 dígitos")

    nao_encontrado = False
    for fonte in (_viacep, _brasilapi):
        try:
            return fonte(digitos, timeout)
        except CepNaoEncontrado:
            nao_encontrado = True          # essa fonte não conhece; tenta a outra
        except (requests.RequestException, ValueError):
            continue                       # fonte fora do ar / resposta ruim

    if nao_encontrado:
        raise CepNaoEncontrado(digitos)
    raise ErroConsultaCep("serviços de CEP indisponíveis")

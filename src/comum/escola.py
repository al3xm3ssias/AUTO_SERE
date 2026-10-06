"""
escola.py — dados da escola (fonte única)
==========================================
Nome, CEP, endereço e identificação da escola. Ficam em
config/config_usuario.json, na chave "unidade_escolar" (a mesma que
src.comum.configuracao já usa), e qualquer script que precise desses dados
deve ler daqui — nunca escrever o nome ou o CEP da escola no código.

Compatibilidade: continuam existindo as chaves "nome", "endereco" e "cep"
que configuracao.unidade_escolar_configurada() exige. "endereco" é montado a
partir de logradouro + número; "cep" é guardado só com os 8 dígitos.

Obrigatórios: nome, CEP e logradouro. Todo o resto é opcional.
"""
from __future__ import annotations

import re

from src.comum import configuracao
from src.comum.cep_consulta import normalizar_cep

CAMPOS_OBRIGATORIOS = ("nome", "cep", "logradouro")
CAMPOS = (
    "nome", "nome_abreviado",
    "cep", "logradouro", "numero", "bairro", "cidade", "uf",
    "codigo", "inep", "telefone", "email", "responsavel",
)
ROTULOS = {
    "nome": "Nome da escola", "cep": "CEP", "logradouro": "Endereço",
    "uf": "Estado", "inep": "INEP", "telefone": "Telefone", "email": "E-mail",
}
UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidacaoErro(ValueError):
    """Dados inválidos. `erros` mapeia campo → mensagem."""

    def __init__(self, erros: dict[str, str]):
        super().__init__("; ".join(erros.values()))
        self.erros = erros

    def mensagem(self) -> str:
        return "; ".join(self.erros.values())


def formatar_cep(cep) -> str:
    d = normalizar_cep(cep)
    return f"{d[:5]}-{d[5:]}" if d else str(cep or "")


def _limpo(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def montar_endereco(logradouro: str, numero: str) -> str:
    return f"{logradouro}, {numero}" if logradouro and numero else logradouro


def validar(dados: dict) -> dict:
    """Devolve os dados limpos ou levanta ValidacaoErro."""
    d = {c: _limpo(dados.get(c)) for c in CAMPOS}
    erros: dict[str, str] = {}

    for campo in CAMPOS_OBRIGATORIOS:
        if not d[campo]:
            erros[campo] = f"Informe {'o' if campo != 'cep' else 'o'} {ROTULOS[campo].lower()}."

    if d["cep"]:
        cep = normalizar_cep(d["cep"])
        if cep is None:
            erros["cep"] = "CEP inválido: informe 8 dígitos."
        else:
            d["cep"] = cep

    d["uf"] = d["uf"].upper()
    if d["uf"] and d["uf"] not in UFS:
        erros["uf"] = "Estado inválido: use a sigla de 2 letras (ex.: PR)."

    if d["email"] and not _EMAIL.match(d["email"]):
        erros["email"] = "E-mail inválido."

    if d["telefone"] and len(re.sub(r"\D", "", d["telefone"])) not in (10, 11):
        erros["telefone"] = "Telefone inválido: informe DDD + número."

    if d["inep"] and not re.fullmatch(r"\d{8}", d["inep"]):
        erros["inep"] = "INEP inválido: são 8 dígitos."

    if len(d["nome"]) > 150:
        erros["nome"] = "Nome muito longo (máximo 150 caracteres)."

    if erros:
        raise ValidacaoErro(erros)

    d["endereco"] = montar_endereco(d["logradouro"], d["numero"])
    return d


def carregar() -> dict:
    """Dados atuais (todos os campos presentes, vazios se não preenchidos)."""
    bruto = configuracao.unidade_escolar() or {}
    d = {c: str(bruto.get(c) or "") for c in CAMPOS}
    if not d["logradouro"] and bruto.get("endereco"):     # config antiga
        d["logradouro"] = str(bruto["endereco"])
    d["endereco"] = str(bruto.get("endereco") or montar_endereco(d["logradouro"], d["numero"]))
    d["cep_formatado"] = formatar_cep(d["cep"]) if d["cep"] else ""
    return d


def salvar(dados: dict) -> dict:
    """Valida e grava. Levanta ValidacaoErro se algo estiver errado."""
    limpos = validar(dados)
    configuracao.definir_unidade_escolar_completa(limpos)
    return limpos


def configurada() -> bool:
    return configuracao.unidade_escolar_configurada()


def nome() -> str:
    """Nome da escola configurado ('' se ainda não configurado)."""
    return carregar()["nome"]

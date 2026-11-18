"""
Correção manual de dados do pre_matricula.json (nome digitado errado pelos pais, telefone, etc.).

Problema que resolve: a automação da pré-matrícula REGRAVA nome e cadastro a cada coleta, com o que está no
site. Uma correção feita direto no JSON sumiria na próxima execução. Por isso a correção fica registrada em
`correcoes_manuais` (chave = CPF do aluno) e é REAPLICADA toda vez que o arquivo é gravado
(`salvar_pre_matricula` chama `aplicar_correcoes_manuais`).

    "correcoes_manuais": {
        "12345678900": {
            "nome_aluno": {"valor": "MARIA SOUZA", "original": "MARIA SOZA", "editado_em": "2026-11-17T10:00:00"}
        }
    }

  - `original` é o valor que o site tinha na 1ª correção do campo; serve para desfazer.
  - Corrigir de volta para o valor original apaga a correção.
  - O CPF do aluno é a chave do registro e NÃO pode ser editado.
  - Corrigir `nome_aluno` também corrige o `nome` do aluno em `turmas_intencao` (todas as turmas/tentativas).

Este módulo não importa nada pesado (Playwright, Flask): é usado pela automação e pela API.
"""
from __future__ import annotations

import re
from datetime import datetime

CHAVE = "correcoes_manuais"

# campo -> (rótulo, normalização)
CAMPOS_EDITAVEIS: dict[str, str] = {
    "nome_aluno": "Nome do aluno",
    "data_nascimento": "Data de nascimento",
    "nome_mae": "Nome da mãe",
    "nome_responsavel": "Nome do responsável",
    "telefone": "Telefone",
    "telefone_2": "Telefone 2",
    "email": "E-mail",
}
_NOMES = {"nome_aluno", "nome_mae", "nome_responsavel"}   # a coleta grava estes em MAIÚSCULAS
_OBRIGATORIOS = {"nome_aluno"}
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


class EdicaoInvalidaError(ValueError):
    """Valor ou campo inválido; a mensagem é mostrada ao usuário."""


def _limpar(texto) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def normalizar_valor(campo: str, valor) -> str:
    """Valida e normaliza no mesmo padrão que a coleta grava (nomes em maiúsculas, e-mail em minúsculas)."""
    if campo not in CAMPOS_EDITAVEIS:
        raise EdicaoInvalidaError(f"O campo {campo!r} não pode ser editado.")
    v = _limpar(valor)
    if campo in _OBRIGATORIOS and not v:
        raise EdicaoInvalidaError(f"{CAMPOS_EDITAVEIS[campo]} não pode ficar em branco.")
    if campo in _NOMES:
        v = v.upper()
    elif campo == "email":
        v = v.lower()
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise EdicaoInvalidaError("E-mail inválido.")
    elif campo == "data_nascimento" and v:
        if not _RE_DATA.match(v):
            raise EdicaoInvalidaError("Data de nascimento deve estar no formato dd/mm/aaaa.")
        try:
            datetime.strptime(v, "%d/%m/%Y")
        except ValueError:
            raise EdicaoInvalidaError("Data de nascimento inexistente.") from None
    return v


def _cpf_ident(cpf) -> str:
    return str(cpf or "").strip()


def localizar(dados: dict, cpf: str):
    """(chave_do_cadastro | None, cadastro | None, [registros de turmas_intencao com esse CPF])."""
    cpf = _cpf_ident(cpf)
    chave, cadastro = None, None
    cadastros = dados.get("cadastros") if isinstance(dados.get("cadastros"), dict) else {}
    if isinstance(cadastros.get(cpf), dict):
        chave, cadastro = cpf, cadastros[cpf]
    else:
        for k, c in cadastros.items():
            if isinstance(c, dict) and _cpf_ident(c.get("cpf")) == cpf:
                chave, cadastro = k, c
                break
    intencoes = []
    turmas = dados.get("turmas_intencao") if isinstance(dados.get("turmas_intencao"), dict) else {}
    for turma, alunos in turmas.items():
        for a in alunos if isinstance(alunos, list) else []:
            if isinstance(a, dict) and cpf and _cpf_ident(a.get("cpf")) == cpf:
                intencoes.append(a)
    return chave, cadastro, intencoes


def _valor_atual(campo: str, cadastro, intencoes) -> str:
    if cadastro is not None and campo in cadastro:
        return str(cadastro.get(campo) or "")
    if campo == "nome_aluno" and intencoes:
        return str(intencoes[0].get("nome") or "")
    return ""


def _aplicar_campo(campo: str, valor: str, cadastro, intencoes) -> None:
    if cadastro is not None:
        cadastro[campo] = valor
    if campo == "nome_aluno":
        for a in intencoes:
            a["nome"] = valor


def aplicar_correcoes_manuais(dados: dict) -> int:
    """Reaplica TODAS as correções registradas sobre o que a coleta acabou de gravar. Devolve quantas foram aplicadas."""
    correcoes = dados.get(CHAVE)
    if not isinstance(correcoes, dict):
        return 0
    n = 0
    for cpf, campos in correcoes.items():
        if not isinstance(campos, dict):
            continue
        _chave, cadastro, intencoes = localizar(dados, cpf)
        if cadastro is None and not intencoes:
            continue            # o aluno ainda não voltou ao arquivo; a correção espera
        for campo, info in campos.items():
            if campo in CAMPOS_EDITAVEIS and isinstance(info, dict) and "valor" in info:
                if campo != "nome_aluno" and cadastro is None:
                    continue    # sem cadastro coletado só o nome tem onde ser aplicado
                _aplicar_campo(campo, info["valor"], cadastro, intencoes)
                n += 1
    return n


def corrigir(dados: dict, cpf: str, novos: dict, agora: datetime | None = None) -> list[str]:
    """
    Aplica as correções em `dados` (em memória; quem chama grava) e as registra em `correcoes_manuais`.
    Devolve os campos que realmente mudaram. Levanta EdicaoInvalidaError se algo estiver inválido
    (nesse caso `dados` não é alterado).
    """
    cpf = _cpf_ident(cpf)
    if not cpf:
        raise EdicaoInvalidaError("Aluno sem CPF: não dá para corrigir por aqui.")
    if not isinstance(novos, dict) or not novos:
        raise EdicaoInvalidaError("Nada para corrigir.")
    _chave, cadastro, intencoes = localizar(dados, cpf)
    if cadastro is None and not intencoes:
        raise EdicaoInvalidaError("Aluno não encontrado no pre_matricula.json.")

    normalizados = {}
    for campo, valor in novos.items():
        v = normalizar_valor(campo, valor)
        if cadastro is None and campo != "nome_aluno":
            raise EdicaoInvalidaError("Este aluno ainda não tem cadastro coletado: só o nome pode ser corrigido.")
        normalizados[campo] = v

    carimbo = (agora or datetime.now()).isoformat(timespec="seconds")
    correcoes = dados.setdefault(CHAVE, {})
    mudou = []
    for campo, v in normalizados.items():
        atual = _valor_atual(campo, cadastro, intencoes)
        reg = correcoes.setdefault(cpf, {}).get(campo)
        original = reg["original"] if isinstance(reg, dict) and "original" in reg else atual
        if v == atual:
            continue
        mudou.append(campo)
        if v == original:                     # voltou ao que o site tinha: não há mais correção
            correcoes[cpf].pop(campo, None)
        else:
            correcoes[cpf][campo] = {"valor": v, "original": original, "editado_em": carimbo}
        _aplicar_campo(campo, v, cadastro, intencoes)
    if not correcoes.get(cpf):
        correcoes.pop(cpf, None)
    if not correcoes:
        dados.pop(CHAVE, None)
    return mudou


def desfazer(dados: dict, cpf: str, campos=None) -> list[str]:
    """Volta os campos (ou todos, se `campos` vier vazio) ao valor que o site tinha. Devolve os campos desfeitos."""
    cpf = _cpf_ident(cpf)
    correcoes = dados.get(CHAVE) if isinstance(dados.get(CHAVE), dict) else {}
    do_aluno = correcoes.get(cpf)
    if not isinstance(do_aluno, dict) or not do_aluno:
        return []
    _chave, cadastro, intencoes = localizar(dados, cpf)
    desfeitos = []
    for campo in list(campos or do_aluno):
        info = do_aluno.get(campo)
        if not isinstance(info, dict):
            continue
        _aplicar_campo(campo, info.get("original", ""), cadastro, intencoes)
        do_aluno.pop(campo, None)
        desfeitos.append(campo)
    if not do_aluno:
        correcoes.pop(cpf, None)
    if not correcoes:
        dados.pop(CHAVE, None)
    return desfeitos


def ler_registro(dados: dict, cpf: str) -> dict | None:
    """O que a tela de edição precisa: valor atual de cada campo editável e se foi corrigido à mão."""
    cpf = _cpf_ident(cpf)
    _chave, cadastro, intencoes = localizar(dados, cpf)
    if cadastro is None and not intencoes:
        return None
    correcoes = (dados.get(CHAVE) or {}).get(cpf) or {}
    campos = {}
    for campo, rotulo in CAMPOS_EDITAVEIS.items():
        if cadastro is None and campo != "nome_aluno":
            continue
        info = correcoes.get(campo) if isinstance(correcoes.get(campo), dict) else None
        campos[campo] = {
            "rotulo": rotulo,
            "valor": _valor_atual(campo, cadastro, intencoes),
            "corrigido": info is not None,
            "original": info.get("original") if info else None,
            "editado_em": info.get("editado_em") if info else None,
        }
    return {
        "cpf": cpf,
        "tem_cadastro": cadastro is not None,
        "ordem": list(campos),        # o JSON da API não preserva a ordem das chaves: a tela usa esta lista
        "campos": campos,
        "turmas": sorted({t for t, alunos in (dados.get("turmas_intencao") or {}).items()
                          for a in alunos if isinstance(a, dict) and _cpf_ident(a.get("cpf")) == cpf}),
    }

"""
modelos_avisos.py — modelos de mensagem da tela "Mandar avisos" (automação `avisos`)
=====================================================================================
Cada modelo é um TIPO de comunicado: nome, para quem é (escolas / pais / qualquer), assunto e mensagem. Ao escolher o
tipo na tela, o assunto e a mensagem são preenchidos (e continuam editáveis).

Há dois modelos que já vêm prontos (PADROES):
  livre          em branco, para escrever na hora;
  transferencia  pede à escola de ORIGEM do aluno que chega a liberação da transferência no SERE, o parecer via SME e o
                 histórico escolar na pasta do aluno. Usa $ALUNO, $CGM e $SERIE (série em que ele está na escola de origem).

Os seus próprios modelos ficam em config/modelos_avisos.json (entra no backup). Dá para:
  - criar um modelo novo (salvar);
  - ajustar um dos prontos: a versão ajustada passa a valer no lugar da original;
  - excluir um criado por você; excluir um pronto ajustado devolve o texto original (um pronto nunca some).
O texto dos marcadores ($ALUNO...) é conferido pelo avisos.py na hora de enviar, não aqui.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from src.comum import paths
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json, salvar_json_atomico

NOME_ARQUIVO = "modelos_avisos.json"
PUBLICOS_DO_MODELO = ("", "escolas", "pais")        # "" = serve para qualquer público
LIMITE_NOME = 80
LIMITE_ASSUNTO = 200
LIMITE_MENSAGEM = 20000

PADROES: dict[str, dict] = {
    "livre": {
        "nome": "Mensagem livre (escrever na hora)",
        "publico": "",
        "assunto": "",
        "mensagem": "",
    },
    "transferencia": {
        "nome": "Transferência de aluno (pedir à escola de origem)",
        "publico": "escolas",
        "assunto": "Solicitação de transferência do aluno $ALUNO",
        "mensagem": (
            "Olá, tudo bem?\n\n"
            "Solicitamos a transferência do aluno $ALUNO, sob o CGM $CGM, da série $SERIE.\n"
            "Por gentileza, liberar a transferência do aluno no SERE, encaminhar o parecer via SME e, se possível, "
            "anexar o histórico escolar na pasta do aluno.\n\n"
            "Atenciosamente,\n$ESCOLA"
        ),
    },
}


def caminho():
    return paths.CONFIG_DIR / NOME_ARQUIVO


def _ler_personalizados() -> dict[str, dict]:
    arquivo = caminho()
    if not arquivo.exists():
        return {}
    try:
        dados = carregar_json(arquivo, dict, dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    modelos = dados.get("modelos") if isinstance(dados, dict) else None
    return {str(k): v for k, v in (modelos or {}).items() if isinstance(v, dict)}


def _gravar_personalizados(modelos: dict[str, dict]) -> None:
    salvar_json_atomico(caminho(), {"modelos": modelos}, indent=2)


def _completo(id_: str, base: dict, personalizado: bool) -> dict:
    return {"id": id_, "nome": str(base.get("nome") or id_), "publico": str(base.get("publico") or ""),
            "assunto": str(base.get("assunto") or ""), "mensagem": str(base.get("mensagem") or ""),
            "padrao": id_ in PADROES, "personalizado": personalizado}


def listar() -> list[dict]:
    """Os prontos (com o ajuste do usuário, se houver) e depois os criados por ele, em ordem de criação."""
    mios = _ler_personalizados()
    saida = [_completo(i, mios.get(i, p), i in mios) for i, p in PADROES.items()]
    saida += [_completo(i, m, True) for i, m in mios.items() if i not in PADROES]
    return saida


def obter(id_: str) -> Optional[dict]:
    return next((m for m in listar() if m["id"] == id_), None)


def _slug(nome: str) -> str:
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40] or "modelo"


def _validar(nome, publico, assunto, mensagem) -> tuple[str, str, str, str]:
    nome, publico = " ".join(str(nome or "").split()), str(publico or "")
    assunto, mensagem = str(assunto or "").strip(), str(mensagem or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao modelo.")
    if len(nome) > LIMITE_NOME:
        raise ValueError(f"O nome do modelo passa de {LIMITE_NOME} caracteres.")
    if publico not in PUBLICOS_DO_MODELO:
        raise ValueError("Público do modelo inválido: use escolas, pais ou deixe em branco.")
    if "\n" in assunto or "\r" in assunto:
        raise ValueError("O assunto precisa ter uma linha só.")
    if len(assunto) > LIMITE_ASSUNTO:
        raise ValueError(f"O assunto passa de {LIMITE_ASSUNTO} caracteres.")
    if not mensagem:
        raise ValueError("Escreva a mensagem do modelo.")
    if len(mensagem) > LIMITE_MENSAGEM:
        raise ValueError(f"A mensagem passa de {LIMITE_MENSAGEM} caracteres.")
    return nome, publico, assunto, mensagem


def salvar(nome, publico, assunto, mensagem, id_: Optional[str] = None) -> dict:
    """
    Cria um modelo (sem `id_`) ou atualiza o de `id_`. Com `id_` de um pronto, grava o ajuste. ValueError com mensagem
    pronta se algo não presta. Devolve o modelo gravado.
    """
    nome, publico, assunto, mensagem = _validar(nome, publico, assunto, mensagem)
    mios = _ler_personalizados()
    if id_:
        if id_ not in PADROES and id_ not in mios:
            raise ValueError("Modelo não encontrado.")
    else:
        if any(" ".join(str(m.get("nome") or "").split()).casefold() == nome.casefold()
               for m in [*PADROES.values(), *mios.values()]):
            raise ValueError(f"Já existe um modelo chamado \"{nome}\". Escolha outro nome ou ajuste aquele.")
        base = _slug(nome)
        id_, n = base, 1
        while id_ in PADROES or id_ in mios:
            n += 1
            id_ = f"{base}-{n}"
    mios[id_] = {"nome": nome, "publico": publico, "assunto": assunto, "mensagem": mensagem}
    _gravar_personalizados(mios)
    return obter(id_)


def excluir(id_: str) -> str:
    """
    Apaga um modelo criado pelo usuário, ou o ajuste de um pronto (volta o texto original). Devolve \"excluido\" ou
    \"restaurado\". ValueError se o modelo não existe ou é um pronto sem ajuste (nada a excluir).
    """
    mios = _ler_personalizados()
    if id_ in mios:
        del mios[id_]
        _gravar_personalizados(mios)
        return "restaurado" if id_ in PADROES else "excluido"
    if id_ in PADROES:
        raise ValueError("Este é um modelo pronto e já está no texto original: não há o que excluir.")
    raise ValueError("Modelo não encontrado.")

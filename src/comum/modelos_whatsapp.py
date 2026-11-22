"""
modelos_whatsapp.py — modelos de mensagem da fila do WhatsApp
=============================================================
Mesma ideia de modelos_avisos.py (e-mail), mas só com o texto (WhatsApp não tem assunto). Vêm prontos (PADROES) e os do
usuário ficam em config/modelos_whatsapp.json (entra no backup). Um pronto ajustado vale no lugar do original; excluir o
ajuste devolve o texto original; um pronto nunca some.

Marcadores ($MARCADOR; um desconhecido é recusado ao salvar e ao montar a mensagem):
  $ESCOLA  $ANO  $DATA   (nossa escola, ano letivo e data de hoje)
  $ALUNO  $TURMA         (do aluno da pré-matrícula)  ·  $RESPONSAVEL (quando o nome do responsável é conhecido)
O texto montado é gravado na própria mensagem da fila: mudar o modelo depois não altera o que já está na fila.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

from src.comum import paths
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json, salvar_json_atomico

NOME_ARQUIVO = "modelos_whatsapp.json"
MARCADORES = ("ESCOLA", "ANO", "DATA", "ALUNO", "TURMA", "RESPONSAVEL")
LIMITE_NOME, LIMITE_TEXTO = 80, 4000
_RE_MARCADOR = re.compile(r"\$([A-Z_]+)")

PADROES: dict[str, dict] = {
    "livre": {"nome": "Mensagem livre (escrever na hora)", "texto": ""},
    "chamada_matricula": {
        "nome": "Chamada para matrícula (pais de aluno novo)",
        "texto": ("Olá, $RESPONSAVEL! Aqui é da $ESCOLA.\n\n"
                  "Há vaga para $ALUNO na turma $TURMA em $ANO. Para efetivar a matrícula, compareça à secretaria da escola, "
                  "em horário de atendimento, com os documentos exigidos.\n\n"
                  "Se não tiver mais interesse na vaga, por favor nos avise, para que ela seja oferecida a outra família."),
    },
}


def caminho():
    return paths.CONFIG_DIR / NOME_ARQUIVO


def _ler() -> dict[str, dict]:
    arquivo = caminho()
    try:
        dados = carregar_json(arquivo, dict, dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    return {str(k): v for k, v in (dados.get("modelos") or {}).items() if isinstance(v, dict)}


def _gravar(modelos: dict[str, dict]) -> None:
    salvar_json_atomico(caminho(), {"modelos": modelos}, indent=2)


def _completo(id_: str, base: dict, personalizado: bool) -> dict:
    return {"id": id_, "nome": str(base.get("nome") or id_), "texto": str(base.get("texto") or ""),
            "padrao": id_ in PADROES, "personalizado": personalizado}


def listar() -> list[dict]:
    mios = _ler()
    saida = [_completo(i, mios.get(i, p), i in mios) for i, p in PADROES.items()]
    return saida + [_completo(i, m, True) for i, m in mios.items() if i not in PADROES]


def obter(id_: str) -> Optional[dict]:
    return next((m for m in listar() if m["id"] == id_), None)


def conferir_marcadores(texto: str) -> None:
    desconhecidos = sorted({m for m in _RE_MARCADOR.findall(texto) if m not in MARCADORES})
    if desconhecidos:
        raise ValueError("Marcador(es) desconhecido(s) " + ", ".join("$" + m for m in desconhecidos)
                         + ". Os que valem: " + ", ".join("$" + m for m in MARCADORES) + ".")


def renderizar(texto: str, contexto: dict) -> str:
    """Troca os marcadores pelo contexto; um sem valor fica como está (à vista, para o usuário perceber)."""
    return _RE_MARCADOR.sub(lambda m: str(contexto.get(m.group(1)) or m.group(0)), texto)


def contexto_base() -> dict:
    from src.comum import escola
    return {"ESCOLA": " ".join(str(escola.nome()).split()), "ANO": str(paths.ano_atual()), "DATA": datetime.now().strftime("%d/%m/%Y")}


def _slug(nome: str) -> str:
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40] or "modelo"


def salvar(nome, texto, id_: Optional[str] = None) -> dict:
    nome, texto = " ".join(str(nome or "").split()), str(texto or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao modelo.")
    if len(nome) > LIMITE_NOME:
        raise ValueError(f"O nome do modelo passa de {LIMITE_NOME} caracteres.")
    if not texto:
        raise ValueError("Escreva a mensagem do modelo.")
    if len(texto) > LIMITE_TEXTO:
        raise ValueError(f"A mensagem passa de {LIMITE_TEXTO} caracteres.")
    conferir_marcadores(texto)
    mios = _ler()
    if id_:
        if id_ not in PADROES and id_ not in mios:
            raise ValueError("Modelo não encontrado.")
    else:
        if any(" ".join(str(m.get("nome") or "").split()).casefold() == nome.casefold() for m in [*PADROES.values(), *mios.values()]):
            raise ValueError(f"Já existe um modelo chamado \"{nome}\". Escolha outro nome ou ajuste aquele.")
        base = _slug(nome)
        id_, n = base, 1
        while id_ in PADROES or id_ in mios:
            n += 1
            id_ = f"{base}-{n}"
    mios[id_] = {"nome": nome, "texto": texto}
    _gravar(mios)
    return obter(id_)


def excluir(id_: str) -> str:
    """\"excluido\" (criado pelo usuário) ou \"restaurado\" (pronto ajustado voltou ao original)."""
    mios = _ler()
    if id_ in mios:
        del mios[id_]
        _gravar(mios)
        return "restaurado" if id_ in PADROES else "excluido"
    if id_ in PADROES:
        raise ValueError("Este é um modelo pronto e já está no texto original: não há o que excluir.")
    raise ValueError("Modelo não encontrado.")

"""
modelos_whatsapp.py — modelos de mensagem da fila do WhatsApp
=============================================================
Mesma ideia de modelos_avisos.py (e-mail), mas só com o texto (WhatsApp não tem assunto). Vêm prontos (PADROES) e os do
usuário ficam em config/modelos_whatsapp.json (entra no backup). Um pronto ajustado vale no lugar do original; excluir o
ajuste devolve o texto original; um pronto nunca some.

Marcadores ($MARCADOR; um desconhecido é recusado ao salvar e ao montar a mensagem):
  $ESCOLA  $ANO  $DATA   (nossa escola, ano letivo em uso e data de hoje)
  $PROXIMO_ANO_LETIVO    (ano letivo em uso + 1: o da previsão/pré-matrícula, ex.: 2027)
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
MARCADORES = ("ESCOLA", "ANO", "DATA", "PROXIMO_ANO_LETIVO", "ALUNO", "TURMA", "RESPONSAVEL")
LIMITE_NOME, LIMITE_TEXTO = 80, 4000
_RE_MARCADOR = re.compile(r"\$([A-Z_]+)")

TEXTO_MATRICULA_APROVADA = """🌟 Olá, tudo bem?
Me chamo Claudio, sou escriturário da Escola Judith.

Estou entrando em contato para informar que a matrícula do(a) seu(sua) filho(a) para o ano letivo de $PROXIMO_ANO_LETIVO foi aprovada em nossa escola. ✅

Pedimos, por gentileza, que o responsável do/da aluno(a) $ALUNO compareça à secretaria para confirmar a matrícula.

📅 Período para comparecimento:
De 24 de novembro de 2026 a 2 de dezembro de 2026

⏰ Horário de atendimento da secretaria:
Segunda a sexta-feira
🕗 08h00 às 12h00
🕐 13h30 às 16h00

⚠️ É muito importante que o responsável leia atentamente toda a mensagem, pois aqui constam todas as informações sobre a matrícula.

📄 Documentos necessários

Trazer ORIGINAIS e CÓPIAS, pois os documentos serão digitalizados e anexados ao sistema da escola, conforme determinação do Governo do Estado e do Núcleo Regional de Educação do Paraná.

✔️ Certidão de Nascimento (cópia)
✔️ Cartão do SUS (cópia)
✔️ Carteirinha de vacinação (cópia)
📌 Obs.: Deve constar na carteirinha a declaração de que as vacinas estão em dia.
✔️ Comprovante de residência atualizado (preferencialmente emitido nos últimos 45 dias — talão de luz em nome do responsável)
✔️ Documento do responsável (RG e CPF ou CNH — cópia)

⚠️ Atenção – Beneficiários do Bolsa Família:
Trazer também a Folha Resumo do CadÚnico (retirada no CRAS onde o benefício está cadastrado).

📌 É obrigatório apresentar todos os documentos que comprovem as informações declaradas na pré-matrícula, principalmente os documentos da criança e do responsável.

Caso a documentação não seja apresentada dentro do prazo, a matrícula será cancelada, sendo necessário realizar novo cadastro posteriormente.

🛑 Prazo final: 02/12/2026
Se não puder comparecer, orientamos que agende um horário.
O não comparecimento implicará no cancelamento da vaga.

🏫 Horário escolar

🚪 Abertura dos portões: 07h30 às 07h45
📚 Início das aulas: 07h45
⏰ Saída:
* 16h00 (segunda a quinta)
* 11h30 (sexta-feira – regime parcial)"""

TEXTO_CONFIRMAR_INTERESSE_GEO = """Olá, $RESPONSAVEL! Tudo bem? 🌟
Aqui é o Claudio, escriturário da $ESCOLA.

O(A) aluno(a) $ALUNO foi direcionado(a) pela rede de ensino para a nossa escola no ano letivo de $PROXIMO_ANO_LETIVO.

Para organizarmos as turmas e liberarmos a vaga para outra família caso necessário, precisamos saber:

Vocês querem a vaga em nossa escola?

Responda com uma das opções:
1️⃣ SIM, quero a vaga na $ESCOLA
2️⃣ NÃO, já confirmei a matrícula em outra escola
3️⃣ Ainda não decidi

Se já matriculou em outra unidade, é só avisar — assim cancelamos o direcionamento sem nenhum problema. 🙏"""

PADROES: dict[str, dict] = {
    "livre": {"nome": "Mensagem livre (escrever na hora)", "texto": ""},
    "matricula_aprovada": {
        "nome": "Matrícula aprovada (próximo ano letivo)",
        "texto": TEXTO_MATRICULA_APROVADA,
    },
    "geo_confirmar_interesse": {
        "nome": "GEO: confirmar interesse na vaga (pais de aluno direcionado)",
        "texto": ("Olá, $RESPONSAVEL! Aqui é da $ESCOLA.\n\n"
                  "O(a) aluno(a) $ALUNO foi direcionado(a) à nossa escola para o ano letivo de $PROXIMO_ANO_LETIVO, "
                  "mas a matrícula ainda não foi confirmada.\n\n"
                  "Para organizarmos as vagas, precisamos saber: vocês ainda têm interesse na vaga em nossa escola "
                  "ou já confirmaram a matrícula em outra unidade escolar?\n\n"
                  "Por favor, responda esta mensagem com o número da opção:\n"
                  "1 - Tenho interesse e vou confirmar a matrícula nesta escola\n"
                  "2 - Já matriculei em outra escola\n\n"
                  "Assim, se a vaga não for mais necessária, podemos oferecê-la a outra família. Obrigado!"),
    },
    "confirmar_interesse_geo": {
        "nome": "Confirmar interesse na vaga (direcionados GEO)",
        "texto": TEXTO_CONFIRMAR_INTERESSE_GEO,
    },
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


def marcadores_sobrando(texto: str) -> list[str]:
    """Marcadores válidos que continuam no texto depois de renderizar (faltou o dado): nunca devem ir para um responsável."""
    return sorted({m for m in _RE_MARCADOR.findall(texto or "") if m in MARCADORES})


def contexto_base() -> dict:
    from src.comum import escola
    return {"ESCOLA": " ".join(str(escola.nome()).split()), "ANO": str(paths.ano_atual()),
            "PROXIMO_ANO_LETIVO": str(int(paths.ano_atual()) + 1), "DATA": datetime.now().strftime("%d/%m/%Y")}


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

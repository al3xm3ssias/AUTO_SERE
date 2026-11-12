"""
planilhas_registro.py — cadastro das planilhas do Google Drive
=============================================================================
Uma "tabela" de planilhas (pareceres do Infantil, turmas, matrícula, ...) com as regras de um cadastro de banco de
dados, guardada no padrão do projeto (JSON gravado de forma atômica, como o calendário e as demais bases em dados/):

    dados/planilhas/planilhas.json
        {"versao": 1, "proximo_id": 4, "itens": [ {registro}, ... ]}

Um registro (linha da tabela):
    id            número sequencial (chave primária). Nunca é reaproveitado, nem depois de remover um registro.
    nome          nome da planilha (obrigatório, até 250 caracteres)
    categoria     texto livre com sugestões ("Turmas", "Pareceres do Infantil", ...); vazio vira "Outras"
    link          link da planilha no Google (só https://docs.google.com/spreadsheets/…)
    planilha_id   ID do Google tirado do link — é ÚNICO: a mesma planilha não entra duas vezes
    observacao    anotação livre (opcional, até 500 caracteres)
    status        "ativa" | "inativa" (inativa = guardada, mas fora de uso)
    finalidade    para que o SISTEMA usa a planilha: "" (só guardada) | parecer_infantil | planilha_turmas | chamada |
                  listagem_alunos | imc (ver FINALIDADES_INFO). É por ela que os módulos acham a planilha vigente
    turma         turma a que a planilha pertence (nome como em turmas.json); obrigatória nas finalidades "por turma"
    plataforma    "google_sheets" | "xlsx" | "ods" (planilhas_plataformas.py; registro antigo sem o campo = google_sheets)
    caminho       arquivo no computador (xlsx/ods); vazio no Google
    referencia    chave ÚNICA da planilha: ID do Google ou caminho absoluto do arquivo (a mesma não entra duas vezes)
    externa       True = recebida pronta da Secretaria (não nasce de modelo). Decidido pela finalidade (parecer_infantil)
    modelo        chave do modelo (planilhas_modelos.py) de que a planilha foi criada; vazio = cadastrada/externa
    natureza      calculada: "externa" | "criada_de_modelo" | "cadastrada"
    origem        "manual" (cadastrada na tela) | "sistema" (criada pelo sistema a partir de um modelo ou da automação do Google)
    criado_em / atualizado_em   data e hora locais ISO (aaaa-mm-ddThh:mm:ss)

Regra de banco: para cada finalidade + turma só pode haver UMA planilha ativa (a vigente). Para trocar de planilha
(outro ano, outro bimestre) deixe a antiga inativa e cadastre/ative a nova; as automações pegam sempre a ativa.

Operações (CRUD): criar, obter, atualizar, remover, listar (busca, filtros, ordenação e paginação), resumo, categorias.
Esta camada só guarda referências: NÃO fala com o Google, então não precisa de credenciais. Quem localiza e cria
planilhas para os módulos é planilhas_gerenciador.py (o ponto de entrada do resto do sistema).

Por que fica em dados/planilhas/ e não em dados/<ano letivo>/: as planilhas atravessam os anos letivos (as "futuras"
também), e trocar o ano em Configurações não pode esconder nem bloquear o cadastro.

A configuração antiga (config_usuario.json → google_sheets.planilhas, de uma versão anterior) é importada uma única
vez, na primeira leitura, e removida de lá.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from datetime import datetime

from . import paths as _paths
from .arquivos_json import carregar_json, salvar_json_atomico

VERSAO_ESQUEMA = 1
STATUS = ("ativa", "inativa")
ORIGENS = ("manual", "sistema")
CATEGORIA_PADRAO = "Outras"
CATEGORIA_TURMAS = "Turmas"
FINALIDADE_PARECER_INFANTIL = "parecer_infantil"
FINALIDADE_PLANILHA_TURMAS = "planilha_turmas"
FINALIDADE_CHAMADA = "chamada"
FINALIDADE_LISTAGEM_ALUNOS = "listagem_alunos"
FINALIDADE_IMC = "imc"
# Para que o sistema usa cada planilha. por_turma: há uma planilha vigente POR TURMA (senão, uma só para a escola);
# externa: a planilha vem pronta da Secretaria (nunca nasce de modelo); modelo vem de planilhas_modelos.py.
FINALIDADES_INFO = {
    FINALIDADE_PARECER_INFANTIL: {"nome": "Pareceres do Infantil", "por_turma": True, "externa": True},
    FINALIDADE_PLANILHA_TURMAS: {"nome": "Planilha das Turmas (movimentação dos alunos)", "por_turma": False, "externa": False},
    FINALIDADE_CHAMADA: {"nome": "Chamada", "por_turma": True, "externa": False},
    FINALIDADE_LISTAGEM_ALUNOS: {"nome": "Listagem dos Alunos", "por_turma": False, "externa": False},
    FINALIDADE_IMC: {"nome": "IMC", "por_turma": False, "externa": False},
}
FINALIDADES = {k: v["nome"] for k, v in FINALIDADES_INFO.items()}        # valor → nome na tela
CATEGORIAS_SUGERIDAS = (CATEGORIA_TURMAS, "Pareceres do Infantil", "Pareceres do Fundamental", "Chamada", "IMC", "Matrícula",
                        "Funcionários", CATEGORIA_PADRAO)

LIMITE_NOME = 250
LIMITE_CATEGORIA = 60
LIMITE_OBSERVACAO = 500
LIMITE_TURMA = 100
ORDENS = ("id", "nome", "categoria", "status", "atualizado_em")
LIMITE_PAGINA_PADRAO = 20
LIMITE_PAGINA_MAXIMO = 200

CAMPOS_EDITAVEIS = ("nome", "link", "categoria", "observacao", "status", "finalidade", "turma", "plataforma", "caminho")
_PREFIXO_LINK = "https://docs.google.com/spreadsheets/"

_lock = threading.RLock()                      # leitura-alteração-gravação de uma só vez (a API é multithread)


class PlanilhaNaoEncontrada(LookupError):
    """Não existe registro com esse id."""


class PlanilhaDuplicada(ValueError):
    """Aquela planilha (mesmo ID do Google) já está cadastrada."""


class PlanilhaEmConflito(ValueError):
    """Já há outra planilha ATIVA para a mesma finalidade e turma."""


# ───────────────────────────── armazenamento ───────────────────────────────────

def _arquivo():
    """dados/planilhas/planilhas.json (função, para os testes trocarem a pasta)."""
    return _paths.DADOS_DIR / "planilhas" / "planilhas.json"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _inteiro(valor, padrao: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _ler() -> dict:
    """
    A tabela inteira, já conferida. Arquivo ilegível levanta ArquivoJsonCorrompidoError SEM ser alterado
    (o cadastro nunca é tratado como vazio por engano). Chamar sempre com `_lock`.
    """
    arquivo = _arquivo()
    existia = arquivo.exists()
    bruto = carregar_json(arquivo, dict, dict)
    itens = [normalizar_item(i) for i in bruto["itens"] if isinstance(i, dict)] if isinstance(bruto.get("itens"), list) else []
    ids = [int(i["id"]) for i in itens if str(i.get("id", "")).isdigit()]
    tabela = {"versao": VERSAO_ESQUEMA, "proximo_id": max(_inteiro(bruto.get("proximo_id"), 1), max(ids, default=0) + 1),
              "itens": itens}
    if not existia:
        _importar_da_configuracao(tabela)
    return tabela


def normalizar_item(item: dict) -> dict:
    """Completa um registro antigo (só Google, sem os campos novos) sem alterar o que ele já tinha."""
    item = dict(item)
    item.setdefault("plataforma", "google_sheets")
    item.setdefault("caminho", "")
    if not item.get("referencia"):
        item["referencia"] = item.get("planilha_id") or item.get("caminho") or ""
    info = FINALIDADES_INFO.get(item.get("finalidade") or "", {})
    item["externa"] = bool(item.get("externa") or info.get("externa"))
    item.setdefault("modelo", "")
    item.setdefault("modelo_versao", 0)
    item["natureza"] = "externa" if item["externa"] else ("criada_de_modelo" if item["modelo"] else "cadastrada")
    return item


def _gravar(tabela: dict) -> None:
    itens = [{k: v for k, v in i.items() if k != "natureza"} for i in tabela["itens"]]       # natureza é calculada
    salvar_json_atomico(_arquivo(), {"versao": VERSAO_ESQUEMA, "proximo_id": tabela["proximo_id"], "itens": itens})


def _importar_da_configuracao(tabela: dict) -> None:
    """Traz para o cadastro a lista que uma versão anterior guardava em config_usuario.json (uma vez só)."""
    from . import configuracao
    try:
        config = configuracao.carregar_configuracao()
    except (OSError, ValueError):
        return
    bloco = config.get("google_sheets")
    antigos = bloco.get("planilhas") if isinstance(bloco, dict) else None
    if not isinstance(antigos, list) or not antigos:
        return
    agora = _agora()
    for a in antigos:
        if not isinstance(a, dict) or not a.get("planilha_id") or not a.get("link"):
            continue
        if any(i.get("planilha_id") == a["planilha_id"] for i in tabela["itens"]):
            continue
        novo = _inteiro(a.get("id"), 0)
        if novo < 1 or any(i.get("id") == novo for i in tabela["itens"]):
            novo = tabela["proximo_id"]
        tabela["itens"].append({"id": novo, "nome": str(a.get("nome") or "Planilha"), "categoria": CATEGORIA_PADRAO,
                                "link": a["link"], "planilha_id": a["planilha_id"], "observacao": "", "status": "ativa",
                                "origem": "manual", "criado_em": agora, "atualizado_em": agora})
        tabela["proximo_id"] = max(tabela["proximo_id"], novo + 1)
    tabela["proximo_id"] = max(tabela["proximo_id"], _inteiro(bloco.get("proximo_id"), 1))
    _gravar(tabela)                                                   # primeiro o cadastro novo…
    bloco.pop("planilhas", None)
    bloco.pop("proximo_id", None)
    try:
        configuracao._salvar_configuracao(config)                     # …depois limpa a lista antiga
    except OSError:
        pass


# ───────────────────────────── regras (validação) ──────────────────────────────

def _texto(valor) -> str:
    return " ".join(str(valor if valor is not None else "").split())


def _chave(texto) -> str:
    """Sem acento, sem maiúsculas e sem espaços repetidos: para buscar e comparar."""
    sem = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(sem.casefold().split())


def _referencia(plataforma, link, caminho, conferir=True) -> dict:
    """{plataforma, referencia, link, caminho, planilha_id} validados pela plataforma (ValueError com mensagem pronta)."""
    from . import planilhas_plataformas as plat
    p = plat.plataforma(plataforma)
    return {"plataforma": p.nome, **p.referencia(link=link, caminho=caminho, conferir=conferir)}


def _limpar(nome, link, categoria, observacao, status, finalidade="", turma="", plataforma="google_sheets", caminho="",
            conferir_arquivo=True) -> dict:
    nome = _texto(nome)
    if not nome:
        raise ValueError("Informe o nome da planilha.")
    if len(nome) > LIMITE_NOME:
        raise ValueError(f"Nome da planilha muito longo (máximo {LIMITE_NOME} caracteres).")
    categoria = _texto(categoria) or CATEGORIA_PADRAO
    if len(categoria) > LIMITE_CATEGORIA:
        raise ValueError(f"Categoria muito longa (máximo {LIMITE_CATEGORIA} caracteres).")
    observacao = str(observacao or "").strip()
    if len(observacao) > LIMITE_OBSERVACAO:
        raise ValueError(f"Observação muito longa (máximo {LIMITE_OBSERVACAO} caracteres).")
    status = _texto(status or "ativa").casefold()
    if status not in STATUS:
        raise ValueError("Situação inválida: use 'ativa' ou 'inativa'.")
    finalidade = _texto(finalidade).casefold()
    if finalidade and finalidade not in FINALIDADES:
        raise ValueError(f"Finalidade inválida: use {', '.join(FINALIDADES)} (ou deixe em branco).")
    turma = _texto(turma)
    if finalidade and FINALIDADES_INFO[finalidade]["por_turma"]:
        if not turma:
            raise ValueError("Informe a turma desta planilha (o nome igual ao de turmas.json).")
        if len(turma) > LIMITE_TURMA:
            raise ValueError(f"Nome da turma muito longo (máximo {LIMITE_TURMA} caracteres).")
    else:
        turma = ""                                                    # turma só faz sentido nas finalidades por turma
    ref = _referencia(plataforma, link, caminho, conferir=conferir_arquivo)
    return {"nome": nome, "categoria": categoria, "observacao": observacao, "status": status, "finalidade": finalidade,
            "turma": turma, **ref}


def _achar(itens: list[dict], id_item) -> tuple[int, dict]:
    alvo = str(id_item).strip()
    for posicao, item in enumerate(itens):
        if str(item.get("id")) == alvo:
            return posicao, item
    raise PlanilhaNaoEncontrada(f"Não há planilha cadastrada com o id {alvo}.")


def _conferir_unica(itens: list[dict], campos: dict, ignorar_id=None) -> None:
    """A mesma planilha (plataforma + referência: ID do Google ou caminho do arquivo) não entra duas vezes."""
    for item in itens:
        if (item.get("referencia") == campos["referencia"] and item.get("plataforma") == campos["plataforma"]
                and item.get("id") != ignorar_id):
            raise PlanilhaDuplicada(f"Esta planilha já está cadastrada como '{item.get('nome')}' (id {item.get('id')}).")


def _conferir_vigente_unica(itens: list[dict], campos: dict, ignorar_id=None) -> None:
    """Para finalidade + turma, só uma planilha ativa (a vigente)."""
    if campos["status"] != "ativa" or not campos["finalidade"]:
        return
    for item in itens:
        if (item.get("id") != ignorar_id and item.get("status") == "ativa" and item.get("finalidade") == campos["finalidade"]
                and _chave(item.get("turma")) == _chave(campos["turma"])):
            raise PlanilhaEmConflito(
                f"Já existe a planilha '{item.get('nome')}' (id {item.get('id')}) ativa para "
                f"{FINALIDADES[campos['finalidade']]} da turma '{campos['turma']}'. Deixe uma das duas inativa.")


# ───────────────────────────── operações ───────────────────────────────────────

def criar(nome, link="", categoria="", observacao="", status="ativa", origem="manual", finalidade="", turma="",
          plataforma="google_sheets", caminho="", modelo="", modelo_versao=0) -> dict:
    """
    Cadastra uma planilha e devolve o registro (com o id novo). ValueError se algum dado for inválido; PlanilhaDuplicada
    se já existir; PlanilhaEmConflito se já houver outra ativa para a mesma finalidade e turma.
    Google: informe `link` (link ou ID). Excel/LibreOffice: informe `caminho` (o arquivo precisa existir).
    """
    campos = _limpar(nome, link, categoria, observacao, status, finalidade, turma, plataforma, caminho)
    if origem not in ORIGENS:
        raise ValueError(f"Origem inválida: use {' ou '.join(ORIGENS)}.")
    if modelo and FINALIDADES_INFO.get(campos["finalidade"], {}).get("externa"):
        raise ValueError("Planilha externa (recebida pronta) não nasce de modelo.")
    with _lock:
        tabela = _ler()
        _conferir_unica(tabela["itens"], campos)
        _conferir_vigente_unica(tabela["itens"], campos)
        agora = _agora()
        item = normalizar_item({"id": tabela["proximo_id"], **campos, "origem": origem, "modelo": str(modelo or ""),
                                "modelo_versao": int(modelo_versao or 0), "criado_em": agora, "atualizado_em": agora})
        tabela["itens"].append(item)
        tabela["proximo_id"] += 1
        _gravar(tabela)
        return dict(item)


def obter(id_item) -> dict:
    with _lock:
        return dict(_achar(_ler()["itens"], id_item)[1])


def atualizar(id_item, **campos) -> dict:
    """
    Altera só os campos informados (nome, link, caminho, plataforma, categoria, observacao, status, finalidade, turma):
    é assim que se SUBSTITUI a planilha de um uso por outra sem mexer no código. id, origem e criado_em não mudam.
    """
    desconhecidos = sorted(set(campos) - set(CAMPOS_EDITAVEIS))
    if desconhecidos:
        raise ValueError(f"Campo(s) que não podem ser alterados: {', '.join(desconhecidos)}.")
    with _lock:
        tabela = _ler()
        posicao, atual = _achar(tabela["itens"], id_item)
        mudou_arquivo = any(k in campos for k in ("link", "caminho", "plataforma"))
        novos = _limpar(*(campos.get(c, atual.get(c)) for c in CAMPOS_EDITAVEIS), conferir_arquivo=mudou_arquivo)
        _conferir_unica(tabela["itens"], novos, ignorar_id=atual["id"])
        _conferir_vigente_unica(tabela["itens"], novos, ignorar_id=atual["id"])
        if all(str(atual.get(k) or "") == str(v) for k, v in novos.items()):
            return dict(atual)                                         # nada mudou: não mexe na data
        item = normalizar_item({**atual, **novos, "atualizado_em": _agora()})
        tabela["itens"][posicao] = item
        _gravar(tabela)
        return dict(item)


def ativar(id_item) -> dict:
    """
    Torna esta planilha a VIGENTE da sua finalidade (e turma): deixa inativas as outras ativas do mesmo uso e ativa esta,
    de uma vez só. É a troca de planilha (outro ano, outro bimestre) sem editar nada. Sem finalidade, só ativa.
    """
    with _lock:
        tabela = _ler()
        posicao, alvo = _achar(tabela["itens"], id_item)
        agora = _agora()
        if alvo.get("finalidade"):
            for i, outro in enumerate(tabela["itens"]):
                if (outro["id"] != alvo["id"] and outro.get("status") == "ativa" and outro.get("finalidade") == alvo["finalidade"]
                        and _chave(outro.get("turma")) == _chave(alvo.get("turma"))):
                    tabela["itens"][i] = {**outro, "status": "inativa", "atualizado_em": agora}
        if alvo.get("status") != "ativa":
            tabela["itens"][posicao] = alvo = {**alvo, "status": "ativa", "atualizado_em": agora}
        _gravar(tabela)
        return dict(alvo)


def remover(id_item) -> dict:
    """Tira o registro do cadastro (a planilha no Google não é tocada). Devolve o registro removido."""
    with _lock:
        tabela = _ler()
        posicao, item = _achar(tabela["itens"], id_item)
        del tabela["itens"][posicao]
        _gravar(tabela)
        return dict(item)


def _numero(valor, nome: str, minimo: int, maximo: int | None = None) -> int:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Valor inválido para '{nome}': informe um número inteiro.") from None
    if n < minimo or (maximo is not None and n > maximo):
        faixa = f"entre {minimo} e {maximo}" if maximo is not None else f"a partir de {minimo}"
        raise ValueError(f"Valor inválido para '{nome}': use um número {faixa}.")
    return n


def listar(q="", status="", categoria="", ordem="id", direcao="asc", limite=LIMITE_PAGINA_PADRAO, inicio=0,
           finalidade="", plataforma="", turma="") -> dict:
    """
    Consulta com busca, filtros, ordenação e paginação (o "Carregar mais" da tela pede a página seguinte com `inicio`).
    `q` procura (sem acento nem maiúsculas) em id, nome, categoria, link e observação.
    Devolve {"itens": [...], "total": <com os filtros>, "inicio", "limite", "proximo": <início da próxima página ou None>}.
    """
    status = _texto(status).casefold()
    if status and status not in STATUS:
        raise ValueError("Situação inválida: use 'ativa' ou 'inativa'.")
    finalidade = _texto(finalidade).casefold()
    if finalidade and finalidade not in FINALIDADES:
        raise ValueError(f"Finalidade inválida: use {', '.join(FINALIDADES)}.")
    plataforma = _texto(plataforma).casefold()
    turma_f = _chave(turma)
    ordem = _texto(ordem).casefold() or "id"
    if ordem not in ORDENS:
        raise ValueError(f"Ordenação inválida: use {', '.join(ORDENS)}.")
    direcao = _texto(direcao).casefold() or "asc"
    if direcao not in ("asc", "desc"):
        raise ValueError("Direção inválida: use 'asc' ou 'desc'.")
    limite = _numero(limite, "limite", 1, LIMITE_PAGINA_MAXIMO)
    inicio = _numero(inicio, "inicio", 0)
    busca, cat = _chave(q), _chave(categoria)

    with _lock:
        itens = _ler()["itens"]
    achados = []
    for item in itens:
        if status and item.get("status") != status:
            continue
        if cat and _chave(item.get("categoria")) != cat:
            continue
        if finalidade and item.get("finalidade") != finalidade:
            continue
        if plataforma and item.get("plataforma") != plataforma:
            continue
        if turma_f and _chave(item.get("turma")) != turma_f:
            continue
        if busca and busca not in _chave(" ".join(str(item.get(c, "")) for c in ("id", "nome", "categoria", "link", "caminho", "observacao", "turma"))):
            continue
        achados.append(item)

    def valor(item):
        return _inteiro(item.get("id"), 0) if ordem == "id" else _chave(item.get(ordem))
    achados.sort(key=lambda i: (valor(i), _inteiro(i.get("id"), 0)), reverse=(direcao == "desc"))
    pagina = [dict(i) for i in achados[inicio:inicio + limite]]
    fim = inicio + len(pagina)
    return {"itens": pagina, "total": len(achados), "inicio": inicio, "limite": limite,
            "proximo": fim if fim < len(achados) else None}


def planilhas_da_finalidade(finalidade: str) -> list[dict]:
    """As planilhas ATIVAS (vigentes) com essa finalidade, por turma. É o que as automações consultam."""
    if finalidade not in FINALIDADES:
        raise ValueError(f"Finalidade inválida: use {', '.join(FINALIDADES)}.")
    with _lock:
        itens = _ler()["itens"]
    ativas = [dict(i) for i in itens if i.get("finalidade") == finalidade and i.get("status") == "ativa"]
    return sorted(ativas, key=lambda i: (_chave(i.get("turma")), _inteiro(i.get("id"), 0)))


def resumo() -> dict:
    """Contagens do cadastro todo (sem filtro): total, ativas e inativas."""
    with _lock:
        itens = _ler()["itens"]
    ativas = sum(1 for i in itens if i.get("status") == "ativa")
    return {"total": len(itens), "ativas": ativas, "inativas": len(itens) - ativas}


def categorias() -> dict:
    """{"usadas": categorias que existem no cadastro, "sugeridas": as padrão, "todas": as duas juntas, sem repetir}."""
    with _lock:
        itens = _ler()["itens"]
    usadas: dict[str, str] = {}
    for item in itens:
        nome = _texto(item.get("categoria"))
        if nome:
            usadas.setdefault(_chave(nome), nome)
    todas = dict(usadas)
    for nome in CATEGORIAS_SUGERIDAS:
        todas.setdefault(_chave(nome), nome)
    ordenar = lambda d: [d[k] for k in sorted(d)]                   # noqa: E731
    return {"usadas": ordenar(usadas), "sugeridas": list(CATEGORIAS_SUGERIDAS), "todas": ordenar(todas)}


def registrar_planilha_criada(nome, planilha_id, categoria=CATEGORIA_TURMAS, finalidade="", turma="", status="ativa",
                              modelo="", modelo_versao=0, plataforma="google_sheets", caminho="") -> dict | None:
    """
    Cadastra a planilha que o sistema acabou de criar (origem "sistema"). Se ela já estiver no cadastro, não duplica e
    devolve None. A planilha já existe: quem chama não deve falhar por causa daqui.
    """
    try:
        return criar(nome, f"{_PREFIXO_LINK}d/{planilha_id}/edit" if planilha_id else "", categoria=categoria,
                     observacao="Criada pelo sistema.", origem="sistema", finalidade=finalidade, turma=turma, status=status,
                     plataforma=plataforma, caminho=caminho, modelo=modelo, modelo_versao=modelo_versao)
    except PlanilhaDuplicada:
        return None

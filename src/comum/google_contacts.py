"""
google_contacts.py — criar e atualizar contatos no Google Contatos (People API)
===============================================================================
Funções INDEPENDENTES e reutilizáveis (nenhuma conhece alunos, turmas ou o SERE; isso fica em
src/automacao/contatos_google.py). Quem autentica é src/comum/google_auth.py.

    from src.comum import google_contacts as gc
    servico = gc.abrir_servico()                                     # autentica uma vez e reaproveita
    rotulos = gc.garantir_rotulos(servico, ["2026"])                 # {"2026": "contactGroups/123"} (cria se faltar)
    pessoa = gc.montar_pessoa(nome="5º A - 2026 - RESPONSAVEL DO JOAO", telefone="(42) 99999-0000")
    gc.criar_contatos(servico, [pessoa], list(rotulos.values()))     # [{"resource_name": "people/c1", "erro": ""}]
    gc.buscar_etags(servico, ["people/c1"])                          # {"people/c1": "%EgUBAj..."}
    gc.atualizar_contatos(servico, [("people/c1", etag, pessoa)])    # só os campos que a pessoa traz

Regras que estas funções garantem:
  • Contatos pertencem a uma conta Google PESSOAL: conta de serviço não serve (recusada com mensagem pronta).
  • Todo erro vira uma exceção da família GoogleErro com mensagem pronta para o usuário em português
    (autenticação, acesso/permissão, API desativada, pedido inválido, cota, sem conexão). Falhas temporárias
    (cota, 5xx, conexão) são repetidas pela própria biblioteca do Google (`num_retries`).
  • Atualização NUNCA apaga o que o contato já tem: só os campos preenchidos no que foi enviado entram na máscara.
  • Escritas em lote (até 200 por chamada) e SEQUENCIAIS, como a People API recomenda para o mesmo usuário.
  • Nada sensível em log: nunca nome, telefone, e-mail ou endereço.
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Iterable, Optional

from .google_auth import (ESCOPO_CONTATOS, GoogleErro, MODO_CONTA_SERVICO, caminho_token_contatos, detectar_modo,
                          obter_credenciais)

log = logging.getLogger(__name__)

TENTATIVAS = 5                                  # repetições automáticas em cota (429), 5xx e queda de conexão
LOTE = 200                                      # máximo da API em batchCreate / batchUpdate / getBatchGet
PAUSA_ENTRE_LOTES_S = 1.0                       # respiro entre lotes de escrita (cota de gravações por minuto)
LIMITE_TEXTO = 1000
GRUPO_MEUS_CONTATOS = "contactGroups/myContacts"
TIPO_ROTULO_USUARIO = "USER_CONTACT_GROUP"

_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


class ContatosErro(GoogleErro):
    """Erro ao falar com o Google Contatos (base dos três abaixo)."""


class ContatosAutenticacaoErro(ContatosErro):
    """O Google recusou as credenciais (401)."""


class ContatosAcessoErro(ContatosErro):
    """API desativada, permissão/escopo insuficiente ou credencial que não serve para contatos (403/404)."""


class ContatosValidacaoErro(ContatosErro, ValueError):
    """Dados inválidos (detectado aqui ou recusado pelo Google com 400)."""


# ───────────────────────────── conexão e erros ─────────────────────────────────

def abrir_servico(*, interativo: bool = True):
    """Autentica e devolve o cliente da People API. Reaproveite-o em várias chamadas (`servico=`)."""
    from googleapiclient.discovery import build
    if detectar_modo() == MODO_CONTA_SERVICO:
        raise ContatosAcessoErro(
            "Contatos pertencem a uma conta Google pessoal: uma conta de serviço não tem agenda de contatos. "
            "Use credenciais OAuth (tipo \"Aplicativo para computador\") e autorize com a conta dona dos contatos.")
    creds = obter_credenciais([ESCOPO_CONTATOS], interativo=interativo, arquivo_token=caminho_token_contatos())
    return build("people", "v1", credentials=creds, cache_discovery=False)


def _mensagem_do_google(exc) -> str:
    try:
        return str(json.loads(exc.content.decode("utf-8"))["error"]["message"])[:300]
    except Exception:                                                     # noqa: BLE001 — corpo ausente ou fora do padrão
        return ""


def _traduzir(exc, contexto: str) -> ContatosErro:
    status = getattr(getattr(exc, "resp", None), "status", None)
    detalhe = _mensagem_do_google(exc)
    baixo = detalhe.lower().replace(" ", "")
    if status == 401:
        return ContatosAutenticacaoErro(
            "O Google recusou as credenciais (401). Refaça a autorização: apague o arquivo do token de contatos "
            "(google_token_contatos.json em credenciais/) e execute de novo.")
    if status == 403:
        if "hasnotbeenused" in baixo or "isdisabled" in baixo or "accessnotconfigured" in baixo:
            return ContatosAcessoErro("A People API não está ativada no projeto do Google Cloud das suas credenciais. "
                                      "Ative em APIs e serviços → Biblioteca → People API.")
        if "insufficient" in baixo and ("scope" in baixo or "permission" in baixo):
            return ContatosAcessoErro("A autorização não inclui o acesso a contatos. Apague google_token_contatos.json "
                                      "(em credenciais/), execute de novo e, na tela do Google, marque a permissão de contatos. "
                                      "Confira também se o escopo .../auth/contacts está na tela de consentimento OAuth.")
        if "quota" in baixo or "ratelimit" in baixo:
            return ContatosErro("Limite de uso da API do Google atingido. Aguarde alguns minutos e tente de novo.")
        return ContatosAcessoErro(f"Sem permissão para {contexto}. Confira a conta que autorizou o programa e a tela de "
                                  "consentimento OAuth (a conta precisa estar como usuário de teste, ou o app em produção).")
    if status == 404:
        return ContatosAcessoErro(f"Recurso não encontrado ao {contexto}.")
    if status == 400:
        return ContatosValidacaoErro(f"O Google recusou o pedido ao {contexto}: {detalhe or 'dados inválidos'}.")
    if status == 429:
        return ContatosErro("Limite de uso da API do Google atingido (429). Aguarde alguns minutos e tente de novo.")
    return ContatosErro(f"Erro do Google ao {contexto} (HTTP {status}){': ' + detalhe if detalhe else ''}.")


def _executar(pedido, contexto: str):
    from googleapiclient.errors import HttpError
    try:
        return pedido.execute(num_retries=TENTATIVAS)
    except HttpError as exc:
        raise _traduzir(exc, contexto) from None
    except GoogleErro:
        raise
    except OSError as exc:
        raise ContatosErro(f"Sem conexão com o Google ao {contexto} ({type(exc).__name__}). "
                           "Confira a internet e tente de novo.") from None


def _servico(servico):
    return servico if servico is not None else abrir_servico()


def _em_lotes(itens: list, tamanho: Optional[int] = None) -> Iterable[list]:
    tamanho = tamanho or LOTE
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


def _msg_item(resposta: dict) -> str:
    status = resposta.get("status") or {}
    return str(status.get("message") or f"HTTP {resposta.get('httpStatusCode')}")[:200]


def _item_ok(resposta: dict) -> bool:
    codigo = resposta.get("httpStatusCode")
    return (codigo is None or int(codigo) < 300) and not resposta.get("status")


# ───────────────────────────── montar a pessoa ─────────────────────────────────

def _limpo(valor) -> str:
    return _CONTROLE.sub(" ", str(valor or "")).strip()[:LIMITE_TEXTO]


def montar_pessoa(*, nome: str, email: str = "", telefone: str = "", cep: str = "", relacao: str = "",
                  extras: Optional[dict] = None) -> dict:
    """
    Pessoa no formato da People API. Campos vazios são OMITIDOS (a API recusa valor vazio, e omitir é o que impede a
    atualização de apagar algo). `relacao` = nome de quem se relaciona com o contato; `extras` = {rótulo: valor}
    (campos personalizados).
    """
    nome = _limpo(nome)
    if not nome:
        raise ContatosValidacaoErro("Contato sem nome.")
    pessoa: dict = {"names": [{"givenName": nome}]}
    if _limpo(email):
        pessoa["emailAddresses"] = [{"value": _limpo(email), "type": "home"}]
    if _limpo(telefone):
        pessoa["phoneNumbers"] = [{"value": _limpo(telefone), "type": "mobile"}]
    if _limpo(cep):
        pessoa["addresses"] = [{"postalCode": _limpo(cep), "type": "home"}]
    if _limpo(relacao):
        pessoa["relations"] = [{"person": _limpo(relacao)}]
    campos = [{"key": _limpo(k), "value": _limpo(v)} for k, v in (extras or {}).items() if _limpo(k) and _limpo(v)]
    if campos:
        pessoa["userDefined"] = campos
    return pessoa


_CAMPO_DA_MASCARA = ("names", "emailAddresses", "phoneNumbers", "addresses", "relations", "userDefined")


def mascara_da_pessoa(pessoa: dict) -> str:
    """Campos que a atualização pode escrever: só os que a pessoa traz (nunca limpa um campo por estar vazio)."""
    return ",".join(c for c in _CAMPO_DA_MASCARA if pessoa.get(c))


# ───────────────────────────── rótulos (grupos de contatos) ────────────────────

def _norm(texto: str) -> str:
    return unicodedata.normalize("NFC", str(texto or "")).strip().casefold()


def listar_rotulos(servico=None) -> dict[str, str]:
    """{nome do rótulo → resourceName} só dos rótulos criados pelo usuário (os do sistema ficam de fora)."""
    api = _servico(servico)
    achados: dict[str, str] = {}
    token = None
    while True:
        params = {"pageSize": 200, "groupFields": "name,groupType"}
        if token:
            params["pageToken"] = token
        resp = _executar(api.contactGroups().list(**params), "listar os rótulos")
        for g in resp.get("contactGroups", []):
            if g.get("groupType") == TIPO_ROTULO_USUARIO and g.get("name") and g.get("resourceName"):
                achados.setdefault(_norm(g["name"]), g["resourceName"])
        token = resp.get("nextPageToken")
        if not token:
            return achados


def garantir_rotulos(servico, nomes: Iterable[str]) -> dict[str, str]:
    """Cada nome → resourceName do rótulo; cria os que não existem (comparação sem diferenciar maiúsculas)."""
    api = _servico(servico)
    existentes = listar_rotulos(api)
    resultado: dict[str, str] = {}
    for nome in nomes:
        nome = _limpo(nome)
        if not nome:
            raise ContatosValidacaoErro("Rótulo sem nome.")
        rn = existentes.get(_norm(nome))
        if rn is None:
            criado = _executar(api.contactGroups().create(body={"contactGroup": {"name": nome}}), "criar o rótulo")
            rn = criado["resourceName"]
            existentes[_norm(nome)] = rn
            log.info("Rótulo criado (%s).", rn)
        resultado[nome] = rn
    return resultado


def adicionar_aos_rotulos(servico, rotulo: str, resource_names: list[str]) -> None:
    """Põe os contatos no rótulo (quem já está nele é ignorado pela API)."""
    api = _servico(servico)
    for lote in _em_lotes(list(resource_names), 1000):
        _executar(api.contactGroups().members().modify(resourceName=rotulo, body={"resourceNamesToAdd": lote}),
                  "colocar contatos no rótulo")


# ───────────────────────────── criar ───────────────────────────────────────────

def criar_contatos(servico, pessoas: list[dict], rotulos: Iterable[str] = (), *, pausa: float = PAUSA_ENTRE_LOTES_S,
                   ao_fim_de_cada_lote=None) -> list[dict]:
    """
    Cria os contatos (lotes de 200) nos rótulos dados (resourceName) e em "Meus contatos". Devolve, NA MESMA ORDEM,
    [{"resource_name": str | "", "erro": str}]. Um contato recusado não derruba os outros do lote.
    `ao_fim_de_cada_lote(inicio, resultados_do_lote)` deixa o chamador gravar o progresso antes do próximo lote.
    """
    api = _servico(servico)
    filiacoes = [{"contactGroupMembership": {"contactGroupResourceName": rn}} for rn in [GRUPO_MEUS_CONTATOS, *rotulos]]
    saida: list[dict] = []
    for n, lote in enumerate(_em_lotes(list(pessoas))):
        if n and pausa:
            time.sleep(pausa)
        corpo = {"contacts": [{"contactPerson": {**p, "memberships": filiacoes}} for p in lote], "readMask": "names"}
        resp = _executar(api.people().batchCreateContacts(body=corpo), "criar os contatos")
        criados = resp.get("createdPeople", [])
        parcial = []
        for i in range(len(lote)):
            item = criados[i] if i < len(criados) else {"status": {"message": "sem resposta do Google"}}
            rn = (item.get("person") or {}).get("resourceName", "")
            parcial.append({"resource_name": rn, "erro": "" if (_item_ok(item) and rn) else _msg_item(item)})
        saida.extend(parcial)
        if ao_fim_de_cada_lote:
            ao_fim_de_cada_lote(len(saida) - len(parcial), parcial)
    return saida


# ───────────────────────────── consultar e atualizar ───────────────────────────

def buscar_etags(servico, resource_names: list[str]) -> dict[str, str]:
    """
    {resourceName → etag} dos contatos que ainda existem. Contato apagado no Google (ou na lixeira) NÃO aparece no
    resultado: quem chama decide recriá-lo. A etag é exigida para atualizar (impede sobrescrever edição mais nova).
    """
    api = _servico(servico)
    achados: dict[str, str] = {}
    for lote in _em_lotes(list(resource_names)):
        resp = _executar(api.people().getBatchGet(resourceNames=lote, personFields="names,metadata"), "consultar os contatos")
        for item in resp.get("responses", []):
            pessoa = item.get("person") or {}
            rn = pessoa.get("resourceName") or item.get("requestedResourceName")
            apagado = bool((pessoa.get("metadata") or {}).get("deleted"))
            if rn and pessoa.get("etag") and _item_ok(item) and not apagado:
                achados[rn] = pessoa["etag"]
    return achados


def atualizar_contatos(servico, itens: list[tuple[str, str, dict]], *, pausa: float = PAUSA_ENTRE_LOTES_S) -> dict[str, str]:
    """
    itens = [(resourceName, etag, pessoa)]. Atualiza só os campos que a pessoa traz (lotes de 200, agrupados pela mesma
    máscara). Devolve {resourceName → "" se deu certo, ou a mensagem do erro}.
    """
    api = _servico(servico)
    por_mascara: dict[str, list[tuple[str, str, dict]]] = {}
    for rn, etag, pessoa in itens:
        por_mascara.setdefault(mascara_da_pessoa(pessoa), []).append((rn, etag, pessoa))
    resultado: dict[str, str] = {}
    primeiro = True
    for mascara, grupo in por_mascara.items():
        if not mascara:
            continue
        for lote in _em_lotes(grupo):
            if not primeiro and pausa:
                time.sleep(pausa)
            primeiro = False
            corpo = {"contacts": {rn: {**pessoa, "etag": etag} for rn, etag, pessoa in lote},
                     "updateMask": mascara, "readMask": "names"}
            resp = _executar(api.people().batchUpdateContacts(body=corpo), "atualizar os contatos")
            retorno = resp.get("updateResult", {})
            for rn, _etag, _pessoa in lote:
                item = retorno.get(rn)
                resultado[rn] = "" if (item is not None and _item_ok(item)) else (_msg_item(item) if item else "sem resposta do Google")
    return resultado

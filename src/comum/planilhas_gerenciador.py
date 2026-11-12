"""
planilhas_gerenciador.py — Gerenciador Centralizado de Planilhas
=============================================================================
O ÚNICO ponto por onde o sistema acha, escolhe e cria planilhas. Nenhum módulo guarda caminho, link ou ID de planilha:
pergunta aqui, por FINALIDADE (e turma, quando a finalidade é por turma).

    from src.comum import planilhas_gerenciador as gp
    ref = gp.resolver("planilha_turmas")                    # a vigente da escola
    ref = gp.resolver("chamada", turma="1º Ano Integral A") # a vigente da turma
    ref = gp.resolver("parecer_infantil", id_item=7)        # a que o usuário escolheu na tela
    ref.plataforma, ref.planilha_id, ref.caminho, ref.link

Três coisas bem separadas (o gerenciador distingue as três):
    • MODELOS (planilhas_modelos.py)      estruturas do sistema, usadas para CRIAR planilhas novas
    • PLANILHAS CADASTRADAS (planilhas_registro.py)   os arquivos em uso no dia a dia, ligados a uma finalidade
    • PLANILHAS EXTERNAS                  recebidas prontas da Secretaria (pareceres do Infantil): são só cadastradas,
                                          nunca criadas de modelo
E as PLATAFORMAS (planilhas_plataformas.py): Google Sheets, Excel (.xlsx) e LibreOffice Calc (.ods).

Operações:
    resolver / candidatas / opcoes_para_formulario     localizar (e deixar o usuário escolher quando há mais de uma)
    criar_de_modelo                                    gera a planilha na plataforma escolhida e já a cadastra
    cadastrar_externa                                  cadastra uma planilha recebida pronta
    definir_vigente                                    troca a planilha de um uso (a antiga fica inativa)
    migrar_planilha_legada                             traz o antigo "ID da última planilha" (configuração) para o cadastro
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import paths as _paths
from . import planilhas_modelos as _modelos
from . import planilhas_plataformas as _plat
from . import planilhas_registro as _reg

FINALIDADE_PARECER_INFANTIL = _reg.FINALIDADE_PARECER_INFANTIL
FINALIDADE_PLANILHA_TURMAS = _reg.FINALIDADE_PLANILHA_TURMAS
FINALIDADE_CHAMADA = _reg.FINALIDADE_CHAMADA
FINALIDADE_LISTAGEM_ALUNOS = _reg.FINALIDADE_LISTAGEM_ALUNOS
FINALIDADE_IMC = _reg.FINALIDADE_IMC


class PlanilhaNaoCadastrada(LookupError):
    """Não há planilha (ativa) cadastrada para aquele uso. A mensagem diz o que fazer."""


class PlanilhaAmbigua(LookupError):
    """Há mais de uma candidata e o pedido não disse qual; o usuário precisa escolher."""


@dataclass(frozen=True)
class PlanilhaRef:
    """A referência que um módulo recebe: tudo o que precisa para abrir a planilha, sem saber de onde ela veio."""
    id: int
    nome: str
    plataforma: str
    referencia: str
    link: str
    caminho: str
    planilha_id: str
    finalidade: str
    turma: str
    externa: bool
    modelo: str
    status: str

    @property
    def local(self) -> bool:
        return _plat.plataforma(self.plataforma).local

    @property
    def destino(self) -> str:
        """O que mostrar/abrir: o caminho do arquivo ou o link do Google."""
        return self.caminho or self.link

    @property
    def rotulo(self) -> str:
        return f"{self.nome} ({_plat.plataforma(self.plataforma).rotulo})"


def _ref(item: dict) -> PlanilhaRef:
    item = _reg.normalizar_item(item)
    return PlanilhaRef(id=int(item["id"]), nome=item["nome"], plataforma=item["plataforma"], referencia=item["referencia"],
                       link=item.get("link", ""), caminho=item.get("caminho", ""), planilha_id=item.get("planilha_id", ""),
                       finalidade=item.get("finalidade", ""), turma=item.get("turma", ""), externa=bool(item["externa"]),
                       modelo=item.get("modelo", ""), status=item.get("status", "ativa"))


def _conferir_finalidade(finalidade: str) -> dict:
    if finalidade not in _reg.FINALIDADES_INFO:
        raise ValueError(f"Finalidade inválida: '{finalidade}'. Use {', '.join(_reg.FINALIDADES)}.")
    return _reg.FINALIDADES_INFO[finalidade]


def _mesma_turma(a, b) -> bool:
    return _reg._chave(a) == _reg._chave(b)


# ───────────────────────────── localizar ───────────────────────────────────────

def migrar_planilha_legada() -> Optional[dict]:
    """
    Versões anteriores guardavam, em config_usuario.json, o ID da "última planilha usada" na sincronização dos alunos.
    Esse ID passa a viver só no cadastro: vira a planilha vigente de "Planilha das Turmas" (se ainda não houver uma) e é
    removido da configuração. Idempotente; nunca levanta erro (devolve o registro criado/alterado ou None).
    """
    from . import configuracao
    try:
        pid = str(configuracao.google_sheets_config().get("planilha_id") or "").strip()
    except (OSError, ValueError):
        return None
    if not pid:
        return None
    resultado = None
    try:
        achadas = [i for i in _reg.listar(q=pid, limite=200)["itens"] if i.get("planilha_id") == pid]
        if achadas:
            item = achadas[0]
            if not item.get("finalidade") and not _reg.planilhas_da_finalidade(FINALIDADE_PLANILHA_TURMAS):
                resultado = _reg.atualizar(item["id"], finalidade=FINALIDADE_PLANILHA_TURMAS)
        elif not _reg.planilhas_da_finalidade(FINALIDADE_PLANILHA_TURMAS):
            resultado = _reg.criar("Planilha das Turmas (importada da configuração)", pid, categoria=_reg.CATEGORIA_TURMAS,
                                   observacao="Estava guardada como 'última planilha usada' em Configurações.",
                                   origem="sistema", finalidade=FINALIDADE_PLANILHA_TURMAS)
    except (ValueError, OSError):
        return None
    configuracao.esquecer_planilha_google_legada()
    return resultado


def candidatas(finalidade: str, turma: str = "", incluir_inativas: bool = False) -> list[PlanilhaRef]:
    """Planilhas cadastradas para o uso (só as ativas, ou todas), da turma quando for o caso, em ordem de turma e id."""
    info = _conferir_finalidade(finalidade)
    if finalidade == FINALIDADE_PLANILHA_TURMAS:
        migrar_planilha_legada()
    itens = _reg.listar(finalidade=finalidade, status="" if incluir_inativas else "ativa", limite=_reg.LIMITE_PAGINA_MAXIMO)["itens"]
    if info["por_turma"] and turma:
        itens = [i for i in itens if _mesma_turma(i.get("turma"), turma)]
    itens.sort(key=lambda i: (_reg._chave(i.get("turma")), 0 if i.get("status") == "ativa" else 1, int(i["id"])))
    return [_ref(i) for i in itens]


def _mensagem_sem_planilha(finalidade: str, turma: str) -> str:
    nome = _reg.FINALIDADES[finalidade]
    onde = f" da turma '{turma}'" if turma else ""
    return (f"Nenhuma planilha de {nome}{onde} está ativa no cadastro. Abra 'Planilhas do Drive' e cadastre a planilha "
            f"(finalidade '{nome}'){' com a turma' if _reg.FINALIDADES_INFO[finalidade]['por_turma'] else ''}, "
            f"ou crie uma a partir do modelo; deixe-a Ativa.")


def resolver(finalidade: str, turma: str = "", id_item=None, plataformas=None) -> PlanilhaRef:
    """
    A planilha a usar numa operação.
      id_item   o usuário escolheu uma planilha cadastrada (qualquer situação): vale exatamente ela, desde que seja do uso certo.
      sem id    a vigente (ativa) do uso — e da turma, nas finalidades por turma.
      plataformas   (opcional) lista das plataformas que a operação sabe usar; outra plataforma é recusada com explicação.
    PlanilhaNaoCadastrada se não há nenhuma; PlanilhaAmbigua se há mais de uma e faltou escolher.
    """
    info = _conferir_finalidade(finalidade)
    if id_item not in (None, ""):
        item = _reg.obter(id_item)                                          # PlanilhaNaoEncontrada se o id não existe
        if item.get("finalidade") != finalidade:
            raise ValueError(f"A planilha '{item['nome']}' (id {item['id']}) não está cadastrada para "
                             f"{_reg.FINALIDADES[finalidade]}.")
        if info["por_turma"] and turma and not _mesma_turma(item.get("turma"), turma):
            raise ValueError(f"A planilha '{item['nome']}' é da turma '{item.get('turma')}', não da turma '{turma}'.")
        achada = _ref(item)
    else:
        lista = candidatas(finalidade, turma)
        if not lista:
            raise PlanilhaNaoCadastrada(_mensagem_sem_planilha(finalidade, turma))
        if len(lista) > 1:
            raise PlanilhaAmbigua("Há mais de uma planilha ativa para " + _reg.FINALIDADES[finalidade]
                                  + (f" (turma '{turma}')" if turma else "") + ": " + "; ".join(f"{r.nome} (id {r.id})" for r in lista)
                                  + ". Escolha qual usar (ou deixe só uma ativa).")
        achada = lista[0]
    if plataformas and achada.plataforma not in set(plataformas):
        aceitas = " ou ".join(_plat.plataforma(p).rotulo for p in plataformas)
        raise ValueError(f"A planilha '{achada.nome}' está no formato {_plat.plataforma(achada.plataforma).rotulo}, "
                         f"mas esta operação só trabalha com {aceitas}.")
    return achada


def opcoes_para_formulario(finalidade: str, turma: str = "", incluir_inativas: bool = True) -> list[dict]:
    """Para o seletor de planilha de uma tela: [{"valor": "<id>", "texto": "Nome — turma (plataforma)"}]."""
    return [{"valor": str(r.id),
             "texto": r.nome + (f" — {r.turma}" if r.turma else "") + f" ({_plat.plataforma(r.plataforma).rotulo})"
                      + ("" if r.status == "ativa" else " [inativa]")}
            for r in candidatas(finalidade, turma, incluir_inativas=incluir_inativas)]


def modelos_disponiveis() -> list[dict]:
    return _modelos.listar()


def plataformas_disponiveis() -> list[dict]:
    return _plat.listar()


# ───────────────────────────── criar / cadastrar / trocar ──────────────────────

def _turmas_do_ano() -> dict:
    from .arquivos_json import ArquivoJsonCorrompidoError, carregar_json
    try:
        return carregar_json(_paths.dados_ano_atual() / "turmas.json", dict, dict)
    except (ArquivoJsonCorrompidoError, OSError, ValueError):
        return {}


def criar_de_modelo(modelo: str, plataforma: str = "google_sheets", nome: str = "", turma: str = "", turmas_selecionadas=(),
                    destino=None, tornar_vigente: bool = False, turmas: Optional[dict] = None, servico=None,
                    escola: str = "") -> dict:
    """
    Cria uma planilha NOVA a partir de um modelo, na plataforma escolhida, e a cadastra (com finalidade, turma, modelo e
    versão). Alunos vêm do turmas.json do ano. Se já existe outra ativa para o mesmo uso, a nova entra INATIVA (o que
    está em uso não muda sozinho); `tornar_vigente=True` troca. Devolve {"item", "ref", "vigente", "avisos"}.
    ValueError / ModeloDesconhecido / PlataformaIndisponivel com mensagem pronta; o cadastro nunca perde a planilha criada.
    """
    m = _modelos.modelo(modelo)
    info = _reg.FINALIDADES_INFO[m.finalidade]
    if info["externa"]:
        raise ValueError(f"'{_reg.FINALIDADES[m.finalidade]}' vem pronta da Secretaria: cadastre a planilha recebida, não crie de modelo.")
    turma = " ".join(str(turma or "").split())
    if m.uma_turma and not turma:
        raise ValueError(f"O modelo '{m.nome}' é de uma turma: escolha a turma.")
    plat = _plat.plataforma(plataforma)
    motivo = plat.disponivel()
    if motivo:
        raise _plat.PlataformaIndisponivel(motivo)

    dados = turmas if turmas is not None else _turmas_do_ano()
    if not dados:
        raise ValueError("Ainda não existe turmas.json: execute primeiro a automação 'Turmas'.")
    ano = int(_paths.ano_atual())
    contexto = _modelos.Contexto(ano=ano, turmas=dados, turma=turma if m.uma_turma else "", escola=escola,
                                 selecionadas=tuple(turmas_selecionadas or ()))
    abas = m.montar(contexto)
    titulo = " ".join(str(nome or "").split()) or " ".join(p for p in (m.nome, turma if m.uma_turma else "", str(ano)) if p)

    criada = plat.criar(titulo, abas, destino=destino, servico=servico)

    avisos = []
    uso_turma = turma if info["por_turma"] else ""
    ja_ha_ativa = bool(candidatas(m.finalidade, uso_turma))
    item = None
    try:
        item = _reg.registrar_planilha_criada(
            criada.get("titulo") or titulo, criada.get("planilha_id", ""), categoria=_categoria_da(m.finalidade),
            finalidade=m.finalidade, turma=uso_turma, status="inativa" if ja_ha_ativa else "ativa",
            modelo=m.chave, modelo_versao=m.versao, plataforma=plat.nome, caminho=criada.get("caminho", ""))
        if item and tornar_vigente and ja_ha_ativa:
            item = _reg.ativar(item["id"])                  # nasce inativa e assume: a anterior fica inativa na mesma operação
        if item and item["status"] == "inativa":
            avisos.append(f"Já existe uma planilha ativa para {_reg.FINALIDADES[m.finalidade]}; a nova ficou INATIVA. "
                          f"Ative-a em 'Planilhas do Drive' (id {item['id']}) quando quiser trocar.")
    except (ValueError, OSError) as exc:
        avisos.append(f"A planilha foi criada ({criada.get('caminho') or criada.get('link')}), mas não deu para cadastrá-la: {exc}")
    return {"item": item, "ref": _ref(item) if item else None, "vigente": bool(item and item["status"] == "ativa"),
            "destino": criada.get("caminho") or criada.get("link"), "avisos": avisos}


def _categoria_da(finalidade: str) -> str:
    return {FINALIDADE_PLANILHA_TURMAS: _reg.CATEGORIA_TURMAS, FINALIDADE_CHAMADA: "Chamada", FINALIDADE_IMC: "IMC",
            FINALIDADE_LISTAGEM_ALUNOS: _reg.CATEGORIA_TURMAS}.get(finalidade, _reg.CATEGORIA_PADRAO)


def cadastrar_externa(nome: str, finalidade: str, turma: str = "", link: str = "", caminho: str = "",
                      plataforma: str = "google_sheets", observacao: str = "", status: str = "ativa") -> dict:
    """Cadastra uma planilha recebida pronta (ex.: pareceres do Infantil, da Secretaria). Não usa modelo nenhum."""
    info = _conferir_finalidade(finalidade)
    if not info["externa"]:
        raise ValueError(f"'{_reg.FINALIDADES[finalidade]}' é uma planilha da escola: crie-a de um modelo, "
                         "ou cadastre o arquivo pela tela 'Planilhas do Drive'.")
    return _reg.criar(nome, link, categoria="Pareceres do Infantil", observacao=observacao, status=status,
                      finalidade=finalidade, turma=turma, plataforma=plataforma, caminho=caminho)


def definir_vigente(id_item) -> PlanilhaRef:
    """Troca a planilha em uso: a escolhida vira a ativa do seu uso (e turma) e a anterior fica inativa."""
    return _ref(_reg.ativar(id_item))

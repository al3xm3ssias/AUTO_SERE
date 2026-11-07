"""
registro_scripts.py — registro dos scripts que usam as opções compartilhadas
=============================================================================
Cada script se registra UMA vez, dizendo:
  • quais recursos usa  (turma, situação matriculados/transferidos, CGM, teste, erros, debug);
  • como é executado    (`planejar`: transforma as opções num "plano" = função + argumentos).

A interface monta os campos a partir dos recursos declarados (um único componente de turma, um de
matriculados/transferidos, um de CGM...), e as rotas executam o plano. Para adicionar um script novo:

    registrar(Script(chave="meu_script", recursos=(RECURSO_TURMA, RECURSO_TESTE), planejar=_plano_meu_script))

e ele já ganha seleção de turma, modo de teste, prévia do que será processado e execução com log.
Scripts que ainda não foram migrados continuam no despacho antigo de src/web/api/rotas.py.

Aqui não há Flask nem rede; as funções pesadas (Playwright etc.) só são importadas dentro de `planejar`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.comum.opcoes_execucao import (RECURSO_CGM, RECURSO_DEBUG, RECURSO_ERROS, RECURSO_SITUACAO,
                                       RECURSO_TESTE, RECURSO_TURMA, Opcoes, argv_cli,
                                       filtrar_turmas_por_situacao, selecionar_alunos)

AJUDA_TESTE_PADRAO = ("Processa só o PRIMEIRO aluno da seleção, para você conferir antes de rodar tudo. "
                      "Atenção: não é simulação — esse aluno é processado de verdade.")


@dataclass(frozen=True)
class Plano:
    """O que executar: `tipo` diz como (gui = wrapper executar_*, coroutine, sync)."""
    tipo: str
    funcao: Callable
    kwargs: dict = field(default_factory=dict)
    log_inicial: str = ""


@dataclass(frozen=True)
class Script:
    chave: str
    recursos: tuple[str, ...]
    planejar: Callable[[Opcoes, dict, dict, dict], Plano]      # (opcoes, payload, turmas_json, contexto) → Plano
    cgm_obrigatorio: bool = False              # com o recurso CGM: True = exige CGMs; False = opcional (em branco vale turma/situação)
    confirmar: bool = False                    # pede confirmação com a prévia antes de executar (altera algo no SERE)
    aviso_confirmacao: str = ""
    ajuda_teste: str = AJUDA_TESTE_PADRAO
    ajuda_debug: str = ""
    extras: Callable[[], list[dict]] = lambda: []              # campos próprios do script (já com as opções resolvidas)
    validar_extras: Optional[Callable[[dict], None]] = None    # levanta ValueError com mensagem pronta
    turmas_de: Optional[Callable[[], list[str]]] = None        # fonte própria de nomes de turma (rematrícula)
    previa: Optional[Callable[[dict], str]] = None             # texto da prévia (ex.: "4 destinatários"); ValueError = aviso na tela

    @property
    def usa_turmas_json(self) -> bool:
        """Precisa de turmas.json (para turma/situação/CGM) — a menos que tenha fonte própria de turmas."""
        return self.turmas_de is None and bool(set(self.recursos) & {RECURSO_TURMA, RECURSO_SITUACAO, RECURSO_CGM})

    @property
    def tem_selecao_de_alunos(self) -> bool:
        return self.turmas_de is None and bool(set(self.recursos) & {RECURSO_TURMA, RECURSO_SITUACAO, RECURSO_CGM})


REGISTRO: dict[str, Script] = {}


def registrar(script: Script) -> Script:
    if script.chave in REGISTRO:
        raise ValueError(f"Script já registrado: {script.chave}")
    REGISTRO[script.chave] = script
    return script


def obter(chave: str) -> Optional[Script]:
    return REGISTRO.get(chave)


# ───────────────────────────── campos próprios (extras) ────────────────────────

def _opcoes_tipos_documento() -> list[dict]:
    from src.comum.sere_normalizacao import IDTIPO_PARA_SLOT
    return [{"valor": k, "texto": v} for k, v in sorted(IDTIPO_PARA_SLOT.items(), key=lambda kv: kv[1].lower())]


def _extras_tipo_documento() -> list[dict]:
    return [{"tipo": "select", "id": "campo-idtipo", "nome": "idtipo", "label": "Tipo de documento",
             "opcoes": _opcoes_tipos_documento()}]


def _validar_tipo_documento(payload: dict) -> None:
    from src.comum.sere_normalizacao import IDTIPO_PARA_SLOT
    if str(payload.get("idtipo") or "") not in IDTIPO_PARA_SLOT:
        raise ValueError("Escolha o tipo de documento.")


def _nome_do_tipo(payload: dict) -> tuple[str, str]:
    from src.comum.sere_normalizacao import IDTIPO_PARA_SLOT
    idtipo = str(payload["idtipo"])
    return idtipo, str(payload.get("nome_slot") or IDTIPO_PARA_SLOT[idtipo])


# ───────────────────────────── planos de cada script ───────────────────────────

# Flags guardadas na aba "Configuração" do analisa_sere que mandam mais do que uma seleção explícita.
_FLAGS_QUE_COMPETEM_COM_SELECAO = {"--todos", "--rapido", "--alunos", "--erros", "--turma", "--transferidos",
                                   "--matriculados", "--cgm"}


def _plano_analisa(o: Opcoes, p: dict, tj: dict, ctx: dict) -> Plano:
    from src.automacao.executar_analisa import executar_analisa
    flags = list(ctx.get("args_flags", []))
    if o.erros:
        # --erros e seleção não se combinam no script (cada um é um modo): reprocessar erros manda.
        argv = ["--erros"]
        flags = [f for f in flags if f not in _FLAGS_QUE_COMPETEM_COM_SELECAO]
    else:
        e_padrao = not o.turmas and not o.cgms and o.matriculados and not o.transferidos
        # Estado padrão da tela (todas as turmas, só matriculados) = não manda nada: assim as flags
        # guardadas na Configuração (ex.: --rapido) continuam valendo. Qualquer seleção explícita as substitui.
        if o.cgms:
            argv = ["--cgm", *o.cgms]            # CGMs informados mandam: turma/situação não entram
        else:
            argv = [] if e_padrao else argv_cli(o, {RECURSO_TURMA, RECURSO_SITUACAO})
        if argv:
            flags = [f for f in flags if f not in _FLAGS_QUE_COMPETEM_COM_SELECAO]
    args = [*flags, *argv]
    return Plano("gui", executar_analisa, {"args_extras": args},
                 "[OPÇÕES] " + (" ".join(args) if args else "nenhuma — modo completo"))


def _turmas_para(o: Opcoes, tj: dict) -> tuple[list[str], dict]:
    """(turmas a processar, dicionário de turmas já filtrado pela situação marcada)."""
    return (list(o.turmas) or list(tj)), filtrar_turmas_por_situacao(tj, matriculados=o.matriculados, transferidos=o.transferidos)


def _plano_validar(o, p, tj, ctx) -> Plano:
    from src.automacao.executar_validar import executar_validar
    alvo, filtradas = _turmas_para(o, tj)
    return Plano("gui", executar_validar, {
        "turmas_selecionadas": alvo, "turmas": filtradas, "modo_teste": o.modo_teste,
        "somente_transferidos": o.transferidos and not o.matriculados})


def _plano_documentos(o, p, tj, ctx) -> Plano:
    from src.automacao.executar_documento import executar_documento
    idtipo, nome = _nome_do_tipo(p)
    alvo, filtradas = _turmas_para(o, tj)
    return Plano("gui", executar_documento, {
        "idtipo": idtipo, "nome_slot": nome, "turmas_selecionadas": alvo, "turmas": filtradas,
        "modo_teste": o.modo_teste})


def _plano_limpeza(o, p, tj, ctx) -> Plano:
    from src.comum.executar_limpeza import executar_limpeza
    alvo, filtradas = _turmas_para(o, tj)
    return Plano("gui", executar_limpeza, {"turmas_selecionadas": alvo, "turmas": filtradas, "modo_teste": o.modo_teste})


def _plano_espec(o, p, tj, ctx) -> Plano:
    from src.automacao.executar_espec import executar_espec
    idtipo, nome = _nome_do_tipo(p)
    alvo, filtradas = _turmas_para(o, tj)
    return Plano("gui", executar_espec, {
        "idtipo_alvo": idtipo, "nome_slot": nome, "turmas_selecionadas": alvo, "turmas": filtradas,
        "modo_teste": o.modo_teste})


def _plano_aluno(o, p, tj, ctx) -> Plano:
    from src.automacao.executar_aluno import executar_aluno
    return Plano("gui", executar_aluno, {
        "modo_teste": o.modo_teste, "modo_erros": o.erros, "modo_faltando": bool(p.get("faltando", False)),
        "cgms": list(o.cgms)})


def _turmas_da_rematricula() -> list[str]:
    from src.automacao.rematricula import TURMAS_ALVO
    return list(TURMAS_ALVO)


def _plano_rematricula(o, p, tj, ctx) -> Plano:
    from src.automacao.rematricula import rematricular_via_login
    kwargs = {"modo_teste": o.modo_teste, "apenas_erros": o.erros, "turmas_alvo": list(o.turmas) or None}
    if p.get("ignorar_chaves_salvas"):
        kwargs["usar_chaves_salvas"] = False
    if p.get("um_aluno"):
        kwargs["um_aluno"] = True
    return Plano("coroutine", rematricular_via_login, kwargs)


def _plano_gerar_chaves(o, p, tj, ctx) -> Plano:
    from src.automacao.chaves_responsavel import gerar_chaves_via_login
    kwargs = {"modo_teste": o.modo_teste, "turmas_alvo": list(o.turmas) or None}
    if p.get("regenerar"):
        kwargs["regenerar"] = True
    return Plano("coroutine", gerar_chaves_via_login, kwargs)


def _plano_prematricula(o, p, tj, ctx) -> Plano:
    from src.automacao.pre_matricula import processo_completo_via_login
    return Plano("coroutine", processo_completo_via_login, {
        "analise": o.debug, "pular_pendentes": bool(p.get("pular_pendentes", False))})


# ── Transferidos: fila, geração de guia/histórico, envio ao SERE e pareceres ──────────────────────────

def _extra_data_corte() -> dict:
    from src.comum.configuracao import data_corte_transferidos
    return {"tipo": "texto", "id": "campo-data-corte", "nome": "data_corte",
            "label": "Data de corte (dd/mm/aaaa): o processo vale para transferidos a partir dela",
            "padrao": data_corte_transferidos().strftime("%d/%m/%Y"), "placeholder": "22/06/2026"}


def _extra_simulacao(padrao: bool, descricao: str) -> dict:
    return {"tipo": "caixa", "id": "campo-simulacao", "nome": "simulacao", "padrao": padrao,
            "label": "Simulação (não altera nada)", "descricao": descricao}


def _validar_data_corte(p: dict) -> None:
    if str(p.get("data_corte") or "").strip():
        from src.comum.configuracao import validar_data_corte
        validar_data_corte(p["data_corte"])                        # ValueError com mensagem pronta


def _aplicar_data_corte(p: dict) -> None:
    """Grava a data de corte digitada no formulário (vale também para as outras telas e para o turmas.py)."""
    texto = str(p.get("data_corte") or "").strip()
    if texto:
        from src.comum import configuracao as c
        if c.validar_data_corte(texto) != c.data_corte_transferidos():
            c.definir_data_corte_transferidos(texto)


def _plano_transferidos(o, p, tj, ctx) -> Plano:
    from src.automacao.executar_transferidos import executar_transferidos
    _aplicar_data_corte(p)
    kwargs = {"modo_teste": o.modo_teste}
    if p.get("simulacao"):
        kwargs["simulacao"] = True
    return Plano("gui", executar_transferidos, kwargs)


def _plano_transferidos_fila(o, p, tj, ctx) -> Plano:
    from src.automacao.fila_transferidos import executar_fila_transferidos
    _aplicar_data_corte(p)
    return Plano("sync", executar_fila_transferidos, {"simulacao": bool(p.get("simulacao"))})


_DOCUMENTOS_GERAR = [
    {"valor": "ambos", "texto": "Histórico e guia de transferência",
     "ajuda": "Emitir, Assinar e Imprimir valem para os dois documentos."},
    {"valor": "historico", "texto": "Só o histórico escolar",
     "ajuda": "Todas as ações marcadas, só para o histórico."},
    {"valor": "guia", "texto": "Só a guia de transferência",
     "ajuda": "Gravar e Alterar são do histórico e ficam de fora."},
]

# (chave, rótulo, descrição) das 5 ações, na ordem da tela; cada uma é uma caixa que se marca separadamente
_ACOES_GERAR = [
    ("gravar", "Gravar", "Grava as matrículas no histórico (só histórico)."),
    ("alterar", "Alterar", "Escreve no histórico o texto da observação, abaixo (só histórico)."),
    ("emitir", "Emitir", "Gera o documento no SERE (histórico e/ou guia)."),
    ("assinar", "Assinar",
     "Assina como o usuário do SERE que está logado (Secretário) e confere se o Diretor já assinou. "
     "O Diretor assina em outra sessão: rode \"Assinar\" de novo depois para registrar a assinatura dele."),
    ("imprimir", "Imprimir", "Baixa o PDF para a pasta de TRANSFERENCIAS (histórico e/ou guia)."),
]


def _acoes_gerar_marcadas(p: dict) -> list[str]:
    """Ações marcadas. Sem nenhuma das 5 chaves no pedido (CLI/API antiga), vale tudo."""
    chaves = [c for c, _, _ in _ACOES_GERAR]
    if not any(c in p for c in chaves):
        return chaves
    return [c for c in chaves if p.get(c)]


def _observacao_gerar(p: dict) -> str:
    """Texto do pedido; se o pedido não traz o campo, o último texto usado."""
    if "observacao" in p:
        return str(p.get("observacao") or "").strip()
    from src.comum.configuracao import observacao_historico
    return observacao_historico().strip()


def _etapas_gerar(p: dict) -> list[str]:
    from src.automacao import processo_transferidos as pr
    return pr.etapas_por_acoes(_acoes_gerar_marcadas(p), p.get("documentos") or "ambos")


def _validar_transferidos_gerar(p: dict) -> None:
    _validar_data_corte(p)
    if (p.get("documentos") or "ambos") not in {o["valor"] for o in _DOCUMENTOS_GERAR}:
        raise ValueError("Escolha os documentos: histórico e guia, só o histórico ou só a guia.")
    if not _acoes_gerar_marcadas(p):
        raise ValueError("Marque pelo menos uma ação: Gravar, Alterar, Emitir, Assinar ou Imprimir.")
    etapas = _etapas_gerar(p)
    if not etapas:
        raise ValueError("Com \"Só a guia\", Gravar e Alterar não se aplicam (são do histórico). "
                         "Marque Emitir, Assinar ou Imprimir.")
    from src.automacao.processo_transferidos import ETAPA_ALTERAR
    if ETAPA_ALTERAR in etapas and not _observacao_gerar(p):
        raise ValueError("Escreva o texto da observação para a ação Alterar, ou desmarque Alterar.")


def _plano_transferidos_gerar(o, p, tj, ctx) -> Plano:
    from src.automacao import processo_transferidos as pr
    _aplicar_data_corte(p)
    etapas = _etapas_gerar(p)
    observacao = None
    if pr.ETAPA_ALTERAR in etapas:
        observacao = _observacao_gerar(p)
        from src.comum.configuracao import definir_observacao_historico
        definir_observacao_historico(observacao)                       # já vem preenchida na próxima vez
    return Plano("coroutine", pr.processar_transferencias, {
        "etapas": etapas, "simulacao": bool(p.get("simulacao")),
        "modo_teste": o.modo_teste, "observacao": observacao})


def _extras_transferidos_gerar() -> list[dict]:
    from src.comum.configuracao import observacao_historico
    return [
        {"tipo": "select", "id": "campo-documentos", "nome": "documentos", "label": "Documentos", "semVazio": True,
         "padrao": "ambos", "opcoes": _DOCUMENTOS_GERAR},
        *[{"tipo": "caixa", "id": f"campo-acao-{chave}", "nome": chave, "padrao": True,
           "label": rotulo, "descricao": descricao} for chave, rotulo, descricao in _ACOES_GERAR],
        {"tipo": "texto", "multilinha": True, "linhas": 4, "id": "campo-observacao", "nome": "observacao",
         "label": "Texto da observação (ação Alterar)", "padrao": observacao_historico(),
         "placeholder": "Texto que será gravado na observação de cada histórico",
         "visivelSe": {"campo": "campo-acao-alterar", "valor": "true"}},
        _extra_data_corte(),
        _extra_simulacao(True, "Mostra quem seria processado, as ações e as pastas de destino. Não abre o SERE e não grava nada. "
                               "Desmarque para executar de verdade."),
    ]


def _validar_pareceres_transferidos(p: dict) -> None:
    _validar_data_corte(p)
    _ler_limite_mb(p)


def _plano_pareceres_transferidos(o, p, tj, ctx) -> Plano:
    from src.automacao.pareceres_transferidos import executar_pareceres_transferidos
    _aplicar_data_corte(p)
    return Plano("coroutine", executar_pareceres_transferidos, {
        "simulacao": bool(p.get("simulacao")), "enviar": bool(p.get("enviar", True)),
        "limite_mb": _ler_limite_mb(p), "modo_teste": o.modo_teste})


def _validar_pareceres_digitalizados(p: dict) -> None:
    from src.automacao import avisos as av
    from src.automacao import pareceres_digitalizados as pd
    _ler_limite_mb(p)
    modo = p.get("email_modo") or "nao"
    if modo not in pd.MODOS_EMAIL:
        raise ValueError(f"Modo de e-mail inválido: '{modo}'.")
    pd.conferir_marcadores(str(p.get("assunto") or pd.ASSUNTO_PADRAO), "Assunto")
    pd.conferir_marcadores(str(p.get("mensagem") or pd.MENSAGEM_PADRAO), "Mensagem")
    teste = str(p.get("email_teste") or "").strip()
    if modo == "teste" and teste and not av.email_valido(teste):
        raise ValueError(f"O endereço de teste '{teste}' não é um e-mail válido.")
    if modo != "nao" and not p.get("simulacao") and not av._credenciais_email_ok():
        raise ValueError("O e-mail da escola ainda não está configurado: preencha EMAIL_REMETENTE e EMAIL_SENHA_APP em credenciais/.env.")


def _plano_pareceres_digitalizados(o, p, tj, ctx) -> Plano:
    from src.automacao import pareceres_digitalizados as pd
    return Plano("coroutine", pd.executar_pareceres_digitalizados, {
        "simulacao": bool(p.get("simulacao")), "enviar_sere": bool(p.get("enviar_sere", False)),
        "email_modo": p.get("email_modo") or "nao", "email_teste": str(p.get("email_teste") or "").strip(),
        "assunto": str(p.get("assunto") or pd.ASSUNTO_PADRAO), "mensagem": str(p.get("mensagem") or pd.MENSAGEM_PADRAO),
        "limite_mb": _ler_limite_mb(p), "modo_teste": o.modo_teste,
        "turmas": list(o.turmas), "cgms": list(o.cgms)})


def _extras_pareceres_digitalizados() -> list[dict]:
    from src.automacao import pareceres_digitalizados as pd
    return [
        {"tipo": "texto", "id": "campo-limite-parecer", "nome": "limite_mb", "label": "Comprimir arquivos maiores que (MB)",
         "placeholder": "1,5 (limite do SERE) — 0 comprime todos"},
        {"tipo": "caixa", "id": "campo-enviar-sere", "nome": "enviar_sere", "padrao": False, "label": "Enviar ao SERE depois de arquivar",
         "descricao": "Envia o parecer de cada aluno para o item \"Parecer Descritivo <ano>-1\" da pasta virtual do SERE "
                      "(vale para qualquer ano; se o item ainda não estiver no catálogo do sistema, é procurado no próprio SERE). "
                      "Quem já foi enviado e não mudou é pulado."},
        {"tipo": "select", "id": "campo-email-modo", "nome": "email_modo", "label": "E-mail ao responsável", "semVazio": True,
         "padrao": "nao", "opcoes": [{"valor": k, "texto": v} for k, v in pd.MODOS_EMAIL.items()]},
        {"tipo": "texto", "id": "campo-email-teste", "nome": "email_teste", "label": "Endereço de teste",
         "placeholder": "em branco = o e-mail da própria escola",
         "visivelSe": {"campo": "campo-email-modo", "valor": "teste"}},
        {"tipo": "texto", "id": "campo-email-assunto", "nome": "assunto", "label": "Assunto do e-mail", "padrao": pd.ASSUNTO_PADRAO,
         "placeholder": "Marcadores: " + ", ".join("$" + m for m in pd.MARCADORES),
         "visivelSe": {"campo": "campo-email-modo", "valor": "teste|enviar"}},
        {"tipo": "texto", "multilinha": True, "linhas": 6, "id": "campo-email-mensagem", "nome": "mensagem",
         "label": "Mensagem do e-mail", "padrao": pd.MENSAGEM_PADRAO,
         "placeholder": "Marcadores: " + ", ".join("$" + m for m in pd.MARCADORES),
         "visivelSe": {"campo": "campo-email-modo", "valor": "teste|enviar"}},
        _extra_simulacao(True, "Lê os QR e mostra onde cada arquivo seria salvo, o que iria ao SERE e quem receberia o e-mail (com a prévia). "
                               "Não copia, não comprime, não apaga, não grava, não abre o SERE e não envia e-mail. Desmarque para executar."),
    ]


def _plano_turmas(o, p, tj, ctx) -> Plano:
    from src.automacao.turmas import coletar_turmas_e_alunos_via_login
    return Plano("coroutine", coletar_turmas_e_alunos_via_login)


_OPCOES_MODO_FUNCIONARIOS = [
    {"valor": "completo", "texto": "Completo (lista + cadastro de cada um)",
     "ajuda": "Lê a lista e, para cada funcionário, consulta o cadastro pelo CPF: documentos, filiação e endereço. "
              "Mais lento. Grava funcionarios.json e funcionarios_completo.json. Se funcionarios.json já existe, "
              "usa essa lista (marque a opção abaixo para atualizá-la antes)."},
    {"valor": "basico", "texto": "Básico (só a lista)",
     "ajuda": "Lê a tela Consulta Funcionários/Docentes: nome, CPF, função, RG, mãe, e-mail, formação e turmas/"
              "disciplinas. Rápido. Grava funcionarios.json."},
]


def _extras_funcionarios() -> list[dict]:
    return [
        {"tipo": "select", "id": "campo-modo-func", "nome": "modo", "label": "Modo de coleta", "semVazio": True,
         "padrao": "completo", "opcoes": _OPCOES_MODO_FUNCIONARIOS},
        {"tipo": "caixa", "id": "campo-atualizar-lista", "nome": "atualizar_lista", "label": "Atualizar a lista antes",
         "descricao": "Refaz a lista de funcionários antes do cadastro completo, para pegar quem entrou ou saiu desde a "
                      "última coleta. Sem isso, o modo completo reaproveita a lista já salva.",
         "visivelSe": {"campo": "campo-modo-func", "valor": "completo"}},
    ]


def _plano_funcionarios(o, p, tj, ctx) -> Plano:
    modo = str(p.get("modo") or "completo").strip().lower()
    if modo not in ("basico", "completo"):
        raise ValueError(f"Modo '{modo}' desconhecido: use 'basico' ou 'completo'.")
    from src.automacao.servidores import coletar_funcionarios_automacao
    return Plano("coroutine", coletar_funcionarios_automacao,
                 {"modo": modo, "atualizar_lista": bool(p.get("atualizar_lista", False))})


_OPCOES_MODO_VINCULOS = [
    {"valor": "completo", "texto": "Completo (vincular + holerite de todos)",
     "ajuda": "Cruza os nomes do SERE com o RH, traz matrícula, cargo e data de admissão e confere no holerite de cada servidor "
              "se ele trabalha nesta escola. É o mais lento (uma consulta a cada 5 s); as consultas já feitas ficam em cache."},
    {"valor": "sere", "texto": "1. Consultar o SERE (só a lista)",
     "ajuda": "Refaz a lista de funcionários da escola no SERE (funcionarios.json) e para. Não consulta o RH da Prefeitura."},
    {"valor": "vincular", "texto": "2. Vincular com a matrícula da Prefeitura (rápido)",
     "ajuda": "Cruza os nomes do SERE com os servidores do RH e grava matrícula, nome do cargo e data de admissão de cada matrícula. "
              "Não consulta holerite. Quem não está entre os servidores vira terceirizado (ou estagiário)."},
    {"valor": "homonimos", "texto": "3. Verificar homônimos / duas matrículas",
     "ajuda": "Só para quem tem mais de uma matrícula com o mesmo nome (ou só para o nome/CPF informado): consulta o holerite de cada "
              "matrícula e vê qual está lotada nesta escola. Se só uma está, as outras são descartadas; se duas estão (dois concursos, "
              "ex.: professor 20h + 20h), ficam as duas, com cargo e admissão de cada uma. Os demais mantêm o resultado já gravado."},
]


def _extras_vinculos() -> list[dict]:
    com_rh = "vincular|homonimos|completo"
    return [
        {"tipo": "select", "id": "campo-modo-vinc", "nome": "modo", "label": "Modo de consulta", "semVazio": True,
         "padrao": "completo", "opcoes": _OPCOES_MODO_VINCULOS},
        {"tipo": "texto", "id": "campo-so-nome", "nome": "so_nome", "label": "Só este funcionário (nome ou CPF)",
         "placeholder": "em branco = todos com mais de uma matrícula", "visivelSe": {"campo": "campo-modo-vinc", "valor": "homonimos"}},
        {"tipo": "caixa", "id": "campo-pular-holerite", "nome": "pular_holerite", "label": "Não conferir no holerite (mais rápido)",
         "descricao": "Pula a comprovação: o holerite de cada servidor casado é consultado no RH (uma consulta a cada 5 s) "
                      "para confirmar que ele trabalha nesta escola. É o mesmo que o modo 2.",
         "visivelSe": {"campo": "campo-modo-vinc", "valor": "completo"}},
        {"tipo": "texto", "id": "campo-mes-holerite", "nome": "mes", "label": "Mês do holerite (MM-AAAA)",
         "placeholder": "em branco = mês anterior", "visivelSe": {"campo": "campo-modo-vinc", "valor": "homonimos|completo"}},
        {"tipo": "caixa", "id": "campo-atualizar-sere", "nome": "atualizar_sere", "label": "Atualizar antes a lista do SERE",
         "descricao": "Refaz a coleta básica de funcionários no SERE. Sem isso usa funcionarios.json (e só coleta se ele não existir).",
         "visivelSe": {"campo": "campo-modo-vinc", "valor": com_rh}},
        {"tipo": "caixa", "id": "campo-forcar-rh", "nome": "forcar_coleta", "label": "Baixar de novo as listas do RH",
         "descricao": "As listas do RH baixadas há menos de 24 h são reaproveitadas; marque para ignorar isso.",
         "visivelSe": {"campo": "campo-modo-vinc", "valor": com_rh}},
    ]


def _modo_vinculos(p: dict) -> str:
    """Modo escolhido; 'pular holerite' no modo completo (opção antiga) vale como o modo 'vincular'."""
    from src.automacao import funcionarios_vinculos as fv
    modo = fv.normalizar_modo(p.get("modo") or fv.MODO_COMPLETO)
    return fv.MODO_VINCULAR if modo == fv.MODO_COMPLETO and bool(p.get("pular_holerite", False)) else modo


def _validar_vinculos(p: dict) -> None:
    from src.automacao import funcionarios_vinculos as fv
    fv.validar_pedido(p.get("mes") or "", _modo_vinculos(p))


def _plano_vinculos(o, p, tj, ctx) -> Plano:
    from src.automacao import funcionarios_vinculos as fv
    modo = _modo_vinculos(p)
    mes = fv.validar_pedido(p.get("mes") or "", modo)
    return Plano("coroutine", fv.vincular_funcionarios_da_escola, {
        "modo": modo, "mes": mes, "forcar_coleta": bool(p.get("forcar_coleta", False)),
        "atualizar_sere": bool(p.get("atualizar_sere", False)), "so_nome": str(p.get("so_nome") or "").strip()})


_OPCOES_MODO_ALUNOS = [
    {"valor": "basico", "texto": "Básico (alunos.py)",
     "ajuda": "Lê a tela de consulta de cada aluno: documentos, filiação, endereço e contatos. Mais rápido. Grava alunos.json."},
    {"valor": "completo", "texto": "Completo (alunos_completo.py)",
     "ajuda": "Lê a tela de edição de cada aluno (cerca de 60 campos: deficiências, recursos de prova, perfil "
              "socioeconômico, atendimento especializado). Mais lento, salva aos poucos e registra erros. "
              "Grava alunos_completo.json. Precisa do turmas.json: rode antes a automação Turmas."},
]


def _extras_alunos() -> list[dict]:
    return [
        {"tipo": "select", "id": "campo-modo", "nome": "modo", "label": "Modo de coleta", "semVazio": True,
         "padrao": "basico", "opcoes": _OPCOES_MODO_ALUNOS},
        {"tipo": "caixa", "id": "campo-rapido", "nome": "rapido", "label": "Modo rápido",
         "descricao": "Pula os alunos já coletados nos últimos 2 meses e coleta só o que falta ou está desatualizado.",
         "visivelSe": {"campo": "campo-modo", "valor": "completo"}},
    ]


def _plano_alunos(o, p, tj, ctx) -> Plano:
    modo = str(p.get("modo") or "basico").strip().lower()
    if modo == "basico":
        from src.automacao.alunos import coletar_alunos_via_login
        return Plano("coroutine", coletar_alunos_via_login)
    if modo == "completo":
        if not tj:
            raise ValueError("O modo completo usa a lista de alunos de turmas.json, que ainda não existe ou está vazio: "
                             "execute primeiro a automação 'Turmas'.")
        from src.automacao.alunos_completo import coletar_cadastro_completo_via_login
        return Plano("coroutine", coletar_cadastro_completo_via_login, {"modo_rapido": bool(p.get("rapido", False))})
    raise ValueError(f"Modo '{modo}' desconhecido: use 'basico' ou 'completo'.")


def _plano_sus(o, p, tj, ctx) -> Plano:
    from src.automacao.sisreg import consultar_encaminhamentos_sisreg
    sel = selecionar_alunos(tj, turmas=o.turmas, matriculados=o.matriculados, transferidos=o.transferidos)
    if not sel.alunos:
        raise ValueError("Nenhum aluno na seleção: confira a turma e se Matriculados/Transferidos estão marcados.")
    return Plano("coroutine", consultar_encaminhamentos_sisreg, {"cgms": [a["CGM"] for a in sel.alunos]},
                 f"[OPÇÕES] consultando {sel.total} aluno(s); os demais mantêm o resultado anterior")


def _ler_raio(p: dict) -> float:
    """Raio em km (aceita vírgula). Vazio = padrão do projeto (RAIO_KM_PADRAO)."""
    from src.comum.cep_api import RAIO_KM_PADRAO
    bruto = str(p.get("raio_km") or "").strip().replace(",", ".")
    try:
        raio = float(bruto) if bruto else RAIO_KM_PADRAO
    except ValueError:
        raio = 0.0
    if not 0 < raio <= 100:
        raise ValueError("Raio inválido: informe um número de km (ex.: 2 ou 2,5).")
    return raio


def _plano_cep(o, p, tj, ctx) -> Plano:
    from src.comum.cep_api import executar_analise_distancia
    return Plano("sync", executar_analise_distancia, {"raio_km": _ler_raio(p)})


def _validar_tema(p: dict) -> None:
    if not str(p.get("tema") or "").strip():
        raise ValueError("Informe o tema do termo de ciência.")


def _plano_termos(o, p, tj, ctx) -> Plano:
    from src.automacao.termo_ciencia import gerar_termo
    from src.comum import escola
    # O nome da escola vem da configuração central (antes: o mais comum nos dados dos funcionários).
    return Plano("sync", gerar_termo, {"tema": str(p["tema"]).strip(), "nome_escola": escola.nome() or None})


# ── Google Sheets: criar / atualizar a planilha das turmas ────────────────────────────────────────────

_OPERACOES_SHEETS = [
    {"valor": "atualizar", "texto": "Atualizar uma planilha existente",
     "ajuda": "Compara o turmas.json com cada aba da planilha (pelo CGM) e grava SÓ as células que mudaram; alunos novos entram "
              "no fim da aba. CPF, SUS, Idade e Escola de origem existentes nunca são tocados."},
    {"valor": "criar", "texto": "Criar uma planilha nova",
     "ajuda": "Cria a planilha (uma aba por turma, com cabeçalhos), preenche com os alunos e guarda o link para as próximas vezes."},
    {"valor": "verificar", "texto": "Só verificar o acesso",
     "ajuda": "Confere se a planilha existe, se a conta tem permissão e quais abas ela tem. Não grava nada."},
]


def _extras_sheets() -> list[dict]:
    from src.comum.configuracao import planilha_google_id
    return [
        {"tipo": "select", "id": "campo-operacao-sheets", "nome": "operacao", "label": "Operação", "semVazio": True,
         "padrao": "atualizar", "opcoes": _OPERACOES_SHEETS},
        {"tipo": "texto", "id": "campo-planilha-sheets", "nome": "planilha", "label": "Link ou ID da planilha",
         "padrao": planilha_google_id(), "placeholder": "https://docs.google.com/spreadsheets/d/…",
         "visivelSe": {"campo": "campo-operacao-sheets", "valor": "atualizar|verificar"}},
        {"tipo": "texto", "id": "campo-nome-sheets", "nome": "nome_planilha", "label": "Nome da nova planilha",
         "placeholder": "Turmas 2026", "visivelSe": {"campo": "campo-operacao-sheets", "valor": "criar"}},
        _extra_simulacao(True, "Lê a planilha e mostra o que seria adicionado e atualizado, sem gravar (nem criar) nada. "
                               "Não vale para \"Só verificar\". Desmarque para gravar de verdade."),
    ]


def _validar_sheets(p: dict) -> None:
    from src.automacao.sincroniza_sheets import OPERACOES
    from src.comum import configuracao, google_sheets as gs
    operacao = str(p.get("operacao") or "atualizar")
    if operacao not in OPERACOES:
        raise ValueError(f"Operação '{operacao}' desconhecida: use {', '.join(OPERACOES)}.")
    if operacao == "criar":
        if not str(p.get("nome_planilha") or "").strip():
            raise ValueError("Informe o nome da nova planilha.")
        return
    alvo = str(p.get("planilha") or "").strip() or configuracao.planilha_google_id()
    if not alvo:
        raise ValueError("Informe o link ou o ID da planilha.")
    gs.extrair_id_planilha(alvo)                                          # SheetsValidacaoErro (é ValueError) com a explicação


def _previa_sheets(p: dict) -> str:
    from src.automacao.sincroniza_sheets import descrever_sincronizacao
    from src.comum import paths
    from src.comum.arquivos_json import carregar_json
    from src.comum.opcoes_execucao import resolver_turmas
    turmas = carregar_json(paths.dados_ano_atual() / "turmas.json", {})
    if not turmas:
        raise ValueError("Ainda não existe turmas.json: execute primeiro a automação 'Turmas'.")
    alvo = resolver_turmas(p.get("turmas") or [], turmas.keys())
    return descrever_sincronizacao(turmas, alvo)


def _plano_sheets(o, p, tj, ctx) -> Plano:
    from src.automacao.sincroniza_sheets import descrever_sincronizacao, executar_planilha_google
    _validar_sheets(p)
    operacao = str(p.get("operacao") or "atualizar")
    alvo = list(o.turmas) or list(tj)
    return Plano("sync", executar_planilha_google, {
        "operacao": operacao, "planilha": str(p.get("planilha") or "").strip(), "nome": str(p.get("nome_planilha") or "").strip(),
        "turmas": tj, "turmas_selecionadas": alvo, "simulacao": bool(p.get("simulacao"))},
        f"[OPÇÕES] Google Sheets — {operacao}: {descrever_sincronizacao(tj, alvo)}")


def _plano_sync(modulo: str, funcao: str) -> Callable:
    """Plano de uma automação que só roda uma função sem parâmetros."""
    def planejar(o, p, tj, ctx) -> Plano:
        import importlib
        return Plano("sync", getattr(importlib.import_module(modulo), funcao))
    return planejar


# ───────────────────────────── registro ────────────────────────────────────────

def _ler_limite_mb(payload: dict) -> float:
    """Limite acima do qual comprime (MB). Em branco = limite do SERE; 0 = todos os arquivos."""
    from src.comum.compressao import LIMITE_SERE_MB
    bruto = str(payload.get("limite_mb") or "").strip().replace(",", ".")
    if not bruto:
        return LIMITE_SERE_MB
    try:
        valor = float(bruto)
    except ValueError:
        raise ValueError(f"Tamanho inválido: '{payload.get('limite_mb')}'. Digite um número em MB (ex.: 1,5) ou 0 para todos.") from None
    if not 0 <= valor <= 500:
        raise ValueError("O tamanho deve ficar entre 0 e 500 MB (0 = comprimir todos os arquivos).")
    return valor


def _plano_comprimir(o, payload, turmas_json, ctx):
    from src.automacao.comprimir import executar_comprimir
    return Plano("sync", executar_comprimir, {
        "turmas": list(o.turmas),                       # vazio = a pasta inteira, com TRANSFERENCIAS
        "limite_mb": _ler_limite_mb(payload),
        "guardar_originais": not payload.get("descartar_originais"),
        "somente_calcular": bool(payload.get("somente_calcular")),
        "modo_teste": o.modo_teste,
    })


def _anos_escolhidos(p: dict) -> tuple[str, str]:
    """(ano base, ano comparado), conferidos contra as pastas dados/<ano>/turmas.json que existem."""
    from src.relatorios.comparar_anos import anos_com_turmas
    anos = anos_com_turmas()
    if len(anos) < 2:
        achado = f"só encontrei o turmas.json de {anos[0]}" if anos else "não encontrei nenhum turmas.json"
        raise ValueError(
            f"Para comparar preciso do turmas.json de dois anos: {achado}. Coloque o arquivo do outro ano em "
            "dados/<ano>/turmas.json (ex.: dados/2025/turmas.json, copiado do ano passado) e rode de novo.")
    base, comparado = str(p.get("ano_base") or "").strip(), str(p.get("ano_comparado") or "").strip()
    if not base or not comparado:
        raise ValueError("Escolha o ano base e o ano comparado.")
    for ano in (base, comparado):
        if ano not in anos:
            raise ValueError(f"Não existe dados/{ano}/turmas.json.")
    if base >= comparado:
        raise ValueError("O ano base deve ser anterior ao ano comparado (ex.: base 2025, comparado 2026).")
    return base, comparado


def _extras_compara_anos() -> list[dict]:
    from src.comum import paths
    from src.relatorios.comparar_anos import anos_com_turmas
    anos = anos_com_turmas()
    opcoes = [{"valor": a, "texto": a} for a in anos]
    atual = paths.ano_atual()
    comparado = atual if atual in anos else (anos[-1] if anos else "")
    anteriores = [a for a in anos if a < comparado]
    base = anteriores[-1] if anteriores else (anos[0] if anos else "")
    return [
        {"tipo": "select", "id": "campo-ano-base", "nome": "ano_base", "label": "Ano base (o mais antigo)",
         "semVazio": True, "padrao": base, "opcoes": opcoes},
        {"tipo": "select", "id": "campo-ano-comparado", "nome": "ano_comparado", "label": "Ano comparado (o mais novo)",
         "semVazio": True, "padrao": comparado, "opcoes": opcoes},
    ]


def _plano_compara_anos(o, p, tj, ctx):
    from src.relatorios.comparar_anos import executar_compara_anos
    base, comparado = _anos_escolhidos(p)
    return Plano("sync", executar_compara_anos, {"ano_base": base, "ano_comparado": comparado})


def _extras_parecer_rco() -> list[dict]:
    from src.automacao.parecer_rco import BIMESTRES
    return [
        {"tipo": "select", "id": "campo-bimestre", "nome": "bimestre", "label": "Bimestre",
         "opcoes": [{"valor": k, "texto": v} for k, v in BIMESTRES.items()]},
        {"tipo": "caixa", "id": "campo-mostrar-navegador", "nome": "mostrar_navegador", "label": "Mostrar o navegador",
         "descricao": "Abre a janela do RCO enquanto trabalha. Útil se algo falhar; por padrão ela fica escondida."},
    ]


def _validar_parecer_rco(p: dict) -> None:
    from src.automacao import parecer_rco
    parecer_rco.validar_pedido(p.get("bimestre"))


def _plano_parecer_rco(o, p, tj, ctx) -> Plano:
    from src.automacao.parecer_rco import CHAVE, gerar_pareceres_infantil_via_login
    return Plano("coroutine", gerar_pareceres_infantil_via_login, {
        "bimestre": p.get("bimestre"), "modo_teste": o.modo_teste,
        "mostrar_navegador": bool(p.get("mostrar_navegador", False)), "chave": CHAVE})


def _extras_parecer_fund() -> list[dict]:
    from src.automacao.parecer_fund import FORMATOS, formato_padrao
    return [
        {"tipo": "select", "id": "campo-formato-parecer", "nome": "formato", "label": "Formato do parecer", "semVazio": True,
         "padrao": formato_padrao(), "opcoes": [{"valor": k, "texto": v} for k, v in FORMATOS.items()]},
        {"tipo": "caixa", "id": "campo-substituir", "nome": "substituir", "label": "Substituir pareceres que já existem",
         "descricao": "Por padrão um parecer já gerado é mantido (o professor pode já ter preenchido). "
                      "Marque só para refazer do zero."},
    ]


def _plano_parecer_fund(o, p, tj, ctx) -> Plano:
    from src.automacao import parecer_fund as pf
    # Nada escolhido = todas as turmas que têm modelo; turma escolhida sem modelo = erro com a lista delas.
    turmas = pf.conferir_modelos(list(o.turmas) or list(tj), explicitas=bool(o.turmas))
    pf.nome_da_escola_para_o_modelo()                                   # falha já aqui se a escola não foi informada
    sel = selecionar_alunos(tj, turmas=turmas, matriculados=o.matriculados, transferidos=o.transferidos, cgms=o.cgms)
    if not sel.alunos:
        raise ValueError("Nenhum aluno na seleção: confira a turma e se Matriculados/Transferidos estão marcados.")
    alunos = pf.montar_alunos(tj, sel.alunos)
    if o.modo_teste:
        alunos = alunos[:1]
    return Plano("sync", pf.gerar_pareceres_fundamental,
                 {"alunos": alunos, "substituir": bool(p.get("substituir", False)), "formato": pf.normalizar_formato(p.get("formato"))},
                 f"[OPÇÕES] {len(alunos)} parecer(es) em {len({a['turma'] for a in alunos})} turma(s)")


def _args_avisos(p: dict) -> dict:
    return {"publico": p.get("publico"), "canal": p.get("canal") or "email", "modo": p.get("modo") or "simular",
            "assunto": p.get("assunto"), "mensagem": p.get("mensagem"),
            "tipo_escola": p.get("tipo_escola") or "todas", "filtro_nome": p.get("filtro_nome") or "",
            "situacao_pais": p.get("situacao_pais") or "matriculados", "email_teste": p.get("email_teste") or ""}


def _extras_avisos() -> list[dict]:
    from src.automacao import avisos as av
    so = lambda campo, valor: {"campo": campo, "valor": valor}
    marcadores = {
        "escolas": "Marcadores no assunto e na mensagem: " + ", ".join("$" + m for m in av.marcadores_validos("escolas")),
        "pais": "Marcadores no assunto e na mensagem: " + ", ".join("$" + m for m in av.marcadores_validos("pais")),
    }
    return [
        {"tipo": "select", "id": "campo-publico", "nome": "publico", "label": "Para quem",
         "opcoes": [{"valor": k, "texto": v, "ajuda": marcadores[k]} for k, v in av.PUBLICOS.items()]},
        {"tipo": "select", "id": "campo-canal", "nome": "canal", "label": "Canal", "semVazio": True, "padrao": "email",
         "opcoes": [{"valor": k, "texto": v} for k, v in av.CANAIS.items()]},
        {"tipo": "select", "id": "campo-modo-aviso", "nome": "modo", "label": "Modo", "semVazio": True, "padrao": "simular",
         "opcoes": [
             {"valor": "simular", "texto": av.MODOS["simular"],
              "ajuda": "Lista quem receberia e mostra a prévia da mensagem. Não envia nada."},
             {"valor": "teste", "texto": av.MODOS["teste"],
              "ajuda": "Envia UM e-mail de verdade, só para o e-mail de teste. Para escolas, vai para a escola fictícia "
                       "ESCOLA MUNICIPAL TESTE DA SILVA. Os destinatários reais não recebem nada."}]},
        {"tipo": "select", "id": "campo-tipo-escola", "nome": "tipo_escola", "label": "Quais unidades", "semVazio": True,
         "padrao": "todas", "opcoes": [{"valor": k, "texto": v} for k, v in av.TIPOS_ESCOLA.items()],
         "visivelSe": so("campo-publico", "escolas")},
        {"tipo": "texto", "id": "campo-filtro-nome", "nome": "filtro_nome", "label": "Só unidades cujo nome contém (opcional)",
         "placeholder": "ex.: Rural", "visivelSe": so("campo-publico", "escolas")},
        {"tipo": "select", "id": "campo-situacao-pais", "nome": "situacao_pais", "label": "Quais alunos novos",
         "semVazio": True, "padrao": "matriculados", "opcoes": [{"valor": k, "texto": v} for k, v in av.SITUACOES_PAIS.items()],
         "visivelSe": so("campo-publico", "pais")},
        {"tipo": "texto", "id": "campo-assunto", "nome": "assunto", "label": "Assunto",
         "placeholder": "ex.: Comunicado oficial - $ESCOLA"},
        {"tipo": "texto", "multilinha": True, "id": "campo-mensagem", "nome": "mensagem", "label": "Mensagem",
         "placeholder": "Escreva o comunicado. Use os marcadores acima para personalizar."},
        {"tipo": "texto", "id": "campo-email-teste", "nome": "email_teste", "label": "E-mail de teste (opcional)",
         "placeholder": "em branco: escolas → a escola fictícia; pais → o e-mail do remetente",
         "visivelSe": so("campo-modo-aviso", "teste")},
    ]


def _previa_avisos(p: dict) -> str:
    """Quantos destinatários o comunicado alcançaria com as escolhas atuais (não exige o texto pronto)."""
    from src.automacao import avisos as av
    if p.get("publico") not in av.PUBLICOS:
        return ""
    if av.teste_com_escola_ficticia(p["publico"], p.get("modo") or "simular"):
        email = (p.get("email_teste") or "").strip() or av.ESCOLA_TESTE["email"]
        texto = f"Teste: 1 e-mail para a escola fictícia {av.ESCOLA_TESTE['nome']} <{email}>"
        try:
            n = len(av.reunir_destinatarios("escolas", p.get("tipo_escola") or "todas", p.get("filtro_nome") or "")["destinatarios"])
            texto += f" (o comunicado real iria para {n} e-mail(s) de escolas e CMEIs)"
        except ValueError:
            pass                                # sem a lista real o teste funciona do mesmo jeito
        return texto + "."
    r = av.reunir_destinatarios(p["publico"], p.get("tipo_escola") or "todas", p.get("filtro_nome") or "",
                                p.get("situacao_pais") or "matriculados")
    n = len(r["destinatarios"])
    if p["publico"] == "pais":
        texto = f"{n} responsável(is) por e-mail, de {r['alunos']} aluno(s) novo(s)"
    else:
        texto = f"{n} e-mail(s) de escolas e CMEIs"
    if r["sem_email"]:
        texto += f"; {len(r['sem_email'])} sem e-mail válido ficariam de fora"
    return texto + ". O envio real ainda não está liberado: use Simular ou Teste."


def _validar_avisos(p: dict) -> None:
    from src.automacao import avisos as av
    a = av.validar_pedido(**_args_avisos(p))
    if av.teste_com_escola_ficticia(a["publico"], a["modo"]):
        return                                  # o teste com a escola fictícia não depende da lista real
    av.reunir_destinatarios(a["publico"], a["tipo_escola"], a["filtro_nome"], a["situacao_pais"])


def _plano_avisos(o, p, tj, ctx) -> Plano:
    from src.automacao import avisos as av
    a = _args_avisos(p)
    return Plano("sync", av.executar_avisos, a, f"[AVISOS] público={a['publico']} | canal={a['canal']} | modo={a['modo']}")


_T, _S, _C, _TE, _E, _D = RECURSO_TURMA, RECURSO_SITUACAO, RECURSO_CGM, RECURSO_TESTE, RECURSO_ERROS, RECURSO_DEBUG

registrar(Script("analisa_sere", (_T, _S, _C, _E), _plano_analisa))

registrar(Script("validar", (_T, _S, _TE), _plano_validar, confirmar=True,
                 aviso_confirmacao="Valida (clica em \"validar\") os documentos pendentes desses alunos no SERE."))

registrar(Script("documentos", (_T, _S, _TE), _plano_documentos, confirmar=True,
                 aviso_confirmacao="REMOVE do SERE o tipo de documento escolhido desses alunos.",
                 extras=_extras_tipo_documento, validar_extras=_validar_tipo_documento))

registrar(Script("limpeza", (_T, _S, _TE), _plano_limpeza, confirmar=True,
                 aviso_confirmacao="REMOVE TODOS os arquivos desses alunos no SERE. Não dá para desfazer."))

registrar(Script("espec", (_T, _S, _TE), _plano_espec, confirmar=True,
                 aviso_confirmacao="Envia ao SERE o tipo de documento escolhido (da pasta de digitalização) para esses alunos.",
                 extras=_extras_tipo_documento, validar_extras=_validar_tipo_documento))

registrar(Script("aluno", (_C, _TE, _E), _plano_aluno, cgm_obrigatorio=True, confirmar=True,
                 aviso_confirmacao="Envia ao SERE os documentos da pasta de digitalização só destes alunos.",
                 extras=lambda: [{"tipo": "caixa", "id": "campo-faltando", "nome": "faltando",
                                  "label": "Só quem ainda tem documento pendente",
                                  "descricao": "Pula os alunos que já estão com todos os documentos no SERE."}]))

registrar(Script("gerar_chaves", (_T, _TE), _plano_gerar_chaves, confirmar=True, turmas_de=_turmas_da_rematricula,
                 aviso_confirmacao="Gera no SERE a chave de acesso do responsável de cada aluno e guarda a chave e o CPF em "
                                   "dados/<ano>/chave_responsavel.json, para a Rematrícula usar. Não rematricula ninguém.",
                 ajuda_teste="Gera a chave de só 1 aluno por turma, para você conferir antes de rodar tudo.",
                 extras=lambda: [{"tipo": "caixa", "id": "campo-regenerar", "nome": "regenerar",
                                  "label": "Gerar de novo mesmo para quem já tem chave salva",
                                  "descricao": "Por padrão pula quem já tem chave salva e quem já foi rematriculado."}]))

registrar(Script("rematricula", (_T, _TE, _E), _plano_rematricula, confirmar=True, turmas_de=_turmas_da_rematricula,
                 aviso_confirmacao="Faz a rematrícula desses alunos no SERE.",
                 ajuda_teste="Faz a rematrícula de só 1 aluno por turma, para você conferir antes de rodar tudo. "
                             "Atenção: não é simulação — esses alunos são rematriculados de verdade.",
                 extras=lambda: [{"tipo": "caixa", "id": "campo-um-aluno", "nome": "um_aluno",
                                  "label": "Testar com 1 único aluno",
                                  "descricao": "Rematricula só o primeiro aluno pendente (no total, não por turma) e para. "
                                                 "Atenção: não é simulação — esse aluno é rematriculado de verdade."},
                                 {"tipo": "caixa", "id": "campo-ignorar-chaves", "nome": "ignorar_chaves_salvas",
                                  "label": "Ignorar as chaves salvas (gerar todas na hora)",
                                  "descricao": "Por padrão, quem tem chave salva (automação \"Gerar chaves\") entra direto na Área do Aluno."}]))

registrar(Script("prematricula_completa", (_D,), _plano_prematricula,
                 ajuda_debug="Modo de análise: salva uma captura de tela de cada etapa em dados/<ano>/screenshots, "
                             "para descobrir o que mudou no site se algo falhar.",
                 extras=lambda: [{"tipo": "caixa", "id": "campo-pular", "nome": "pular_pendentes",
                                  "label": "Pular a verificação de pendentes (Etapa 4)",
                                  "descricao": "Mais rápido; não consulta de novo quem ainda está pendente."}]))

registrar(Script("transferidos_fila", (), _plano_transferidos_fila, validar_extras=_validar_data_corte,
                 extras=lambda: [_extra_data_corte(),
                                 _extra_simulacao(False, "Só mostra quem entraria na fila (e quem fica de fora pela data de corte), "
                                                         "sem gravar fila_transferidos.json nem transferidos.json.")]))

registrar(Script("transferidos_gerar", (_TE,), _plano_transferidos_gerar, confirmar=True,
                 validar_extras=_validar_transferidos_gerar,
                 aviso_confirmacao="Executa no SERE as ações marcadas (gravar, alterar, emitir, assinar, imprimir) para os alunos da fila "
                                   "(transferidos a partir da data de corte). Com \"Simulação\" marcada nada é feito.",
                 ajuda_teste="Processa só o primeiro aluno da fila. Atenção: não é simulação — ele é processado de verdade.",
                 extras=_extras_transferidos_gerar))

registrar(Script("transferidos", (_TE,), _plano_transferidos, confirmar=True, validar_extras=_validar_data_corte,
                 aviso_confirmacao="Envia ao SERE (pasta virtual) a guia, o histórico e o parecer dos transferidos que estão "
                                   "nas pastas de TRANSFERENCIAS. Com \"Simulação\" marcada nada é enviado.",
                 ajuda_teste="Envia só o primeiro arquivo. Atenção: não é simulação — ele é enviado de verdade.",
                 extras=lambda: [_extra_data_corte(),
                                 _extra_simulacao(True, "Só varre as pastas e mostra o que seria enviado. Não abre o SERE e não grava nada. "
                                                        "Desmarque para enviar de verdade.")]))

registrar(Script("pareceres_transferidos", (_TE,), _plano_pareceres_transferidos, confirmar=True,
                 validar_extras=_validar_pareceres_transferidos,
                 aviso_confirmacao="Lê o QR de cada parecer digitalizado, arquiva em PARECERES, comprime se passar do limite "
                                   "(o original fica guardado) e envia ao SERE. Com \"Simulação\" marcada nada é alterado.",
                 ajuda_teste="Processa só o primeiro arquivo. Atenção: não é simulação — ele é processado de verdade.",
                 extras=lambda: [
                     _extra_data_corte(),
                     {"tipo": "texto", "id": "campo-limite-parecer", "nome": "limite_mb", "label": "Comprimir arquivos maiores que (MB)",
                      "placeholder": "1,5 (limite do SERE) — 0 comprime todos"},
                     {"tipo": "caixa", "id": "campo-enviar", "nome": "enviar", "padrao": True, "label": "Enviar ao SERE depois de processar",
                      "descricao": "Desmarque para só processar e arquivar os pareceres, sem abrir o SERE."},
                     _extra_simulacao(True, "Lê os QR e mostra, para cada arquivo, quem é, onde seria salvo e se seria comprimido. "
                                            "Não copia, não comprime, não apaga, não grava e não abre o SERE. Desmarque para processar de verdade.")]))


registrar(Script("pareceres_digitalizados", (_T, _C, _TE), _plano_pareceres_digitalizados, confirmar=True,
                 validar_extras=_validar_pareceres_digitalizados, extras=_extras_pareceres_digitalizados,
                 aviso_confirmacao="Lê o QR dos pareceres do Fundamental digitalizados (pasta PARECERES/_PROCESSAR), arquiva cada um na turma "
                                   "do aluno e, se marcado, envia ao SERE e por e-mail ao responsável. Com \"Simulação\" marcada nada é "
                                   "alterado nem enviado. O envio por e-mail vai para famílias de verdade.",
                 ajuda_teste="Processa e envia só o primeiro parecer. Atenção: não é simulação — ele é processado de verdade."))

registrar(Script("parecer_rco", (_TE,), _plano_parecer_rco, validar_extras=_validar_parecer_rco,
                 extras=_extras_parecer_rco,
                 ajuda_teste="Baixa só o parecer do primeiro aluno do Infantil IV/V, para você conferir o login, o código "
                             "de verificação e a pasta antes de rodar todos."))

registrar(Script("parecer_fund", (_T, _S, _C, _TE), _plano_parecer_fund,
                 ajuda_teste="Gera só o parecer do primeiro aluno da seleção, para você conferir o resultado antes de gerar todos.",
                 extras=_extras_parecer_fund))

registrar(Script("avisos", (), _plano_avisos, validar_extras=_validar_avisos, extras=_extras_avisos,
                 previa=_previa_avisos))

# ── coletas e relatórios (sem opções compartilhadas, ou só as próprias) ──
registrar(Script("turmas", (), _plano_turmas))
registrar(Script("alunos", (), _plano_alunos, extras=_extras_alunos))
registrar(Script("funcionarios", (), _plano_funcionarios, extras=_extras_funcionarios))
registrar(Script("vinculos", (), _plano_vinculos, validar_extras=_validar_vinculos, extras=_extras_vinculos))
registrar(Script("sus", (_T, _S), _plano_sus))
registrar(Script("sheets", (_T,), _plano_sheets, confirmar=True, validar_extras=_validar_sheets, extras=_extras_sheets,
                 previa=_previa_sheets,
                 aviso_confirmacao="Cria ou altera uma planilha do Google Sheets (só as células que mudaram; nada é apagado nem "
                                   "regravado por inteiro). Com \"Simulação\" marcada nada é gravado."))
registrar(Script("cep", (), _plano_cep, validar_extras=_ler_raio,
                 extras=lambda: [{"tipo": "texto", "id": "campo-raio", "nome": "raio_km", "label": "Raio de atendimento (km)",
                                  "placeholder": "2 (padrão do sistema)"}]))
registrar(Script("termos", (), _plano_termos, validar_extras=_validar_tema,
                 extras=lambda: [
                     {"tipo": "texto", "id": "campo-tema", "nome": "tema", "label": "Tema do termo de ciência",
                      "placeholder": "Ex.: Uso de imagem"},
                     {"tipo": "pasta", "label": "Pasta com o modelo do termo (o termo gerado é salvo nela)", "destino": "modelos"},
                 ]))
registrar(Script("comprimir", (_T, _TE), _plano_comprimir, confirmar=True, validar_extras=_ler_limite_mb,
                 aviso_confirmacao="SUBSTITUI os PDFs e imagens maiores que o limite por versões comprimidas (qualidade menor; "
                                   "mesmo nome e mesma data). Os originais ficam em dados/<ano>/ORIGINAIS_ANTES_DA_COMPRESSAO, "
                                   "a menos que você marque para não guardar. Com \"Só calcular\" nada é alterado.",
                 ajuda_teste="Comprime só o primeiro arquivo que passar do limite, para você conferir a qualidade antes de rodar tudo. "
                             "Atenção: não é simulação — esse arquivo é substituído de verdade (o original fica guardado).",
                 extras=lambda: [
                     {"tipo": "texto", "id": "campo-limite", "nome": "limite_mb", "label": "Comprimir arquivos maiores que (MB)",
                      "placeholder": "1,5 (limite do SERE) — 0 comprime todos"},
                     {"tipo": "caixa", "id": "campo-calcular", "nome": "somente_calcular", "label": "Só calcular quanto vai economizar",
                      "descricao": "Não altera nenhum arquivo: mostra no log quanto cada um encolheria. Bom para ver antes de comprimir."},
                     {"tipo": "caixa", "id": "campo-descartar", "nome": "descartar_originais", "label": "Não guardar cópia dos originais",
                      "descricao": "Por padrão cada original é guardado antes de ser substituído. Marque só se estiver sem espaço em disco."},
                 ]))

registrar(Script("compara_anos", (), _plano_compara_anos, validar_extras=_anos_escolhidos, extras=_extras_compara_anos))
registrar(Script("gerar_pastas", (), _plano_sync("src.automacao.gerar_pastas", "main")))
registrar(Script("analisa_pasta", (), _plano_sync("src.relatorios.analisa_documentos_pc", "main"),
                 extras=lambda: [{"tipo": "pasta", "label": "Pasta de digitalização a ser analisada", "destino": "digitalizacao"}]))
registrar(Script("mapear_pastas", (), _plano_sync("src.relatorios.mapear_pastas_alunos", "main"),
                 extras=lambda: [{"tipo": "pasta", "label": "Pasta raiz dos alunos", "destino": "digitalizacao"}]))
registrar(Script("cruzamento", (), _plano_sync("src.relatorios.cruzar_documentos", "main")))
registrar(Script("mascara", (), _plano_sync("src.relatorios.mascarar", "main")))
registrar(Script("coleta_emails", (), _plano_sync("src.automacao.coleta_emails", "coletar_escolas_municipais")))
registrar(Script("backup", (), _plano_sync("src.comum.backup", "executar_backup")))

"""
avisos.py — Comunicados oficiais por e-mail (escola → escolas, escola → pais)
=============================================================================
Pedido do usuário (20/10/2026): criar o modo de comunicação de ESCOLA PARA ESCOLA (só as escolas de Ponta
Grossa que vêm da automação "Coleta e-mails") e de ESCOLA PARA OS PAIS (os responsáveis dos alunos novos
da PRÉ-MATRÍCULA que vão iniciar na escola), ambos para comunicações oficiais. Começa pelo e-mail, com
MODOS DE TESTE; o envio de verdade será liberado depois.

PÚBLICOS
  escolas   escolas municipais e CMEIs de escolas_completas.json (Coleta e-mails), exceto a própria escola;
            filtros: tipo (todas / só escolas / só CMEIs) e um trecho do nome.
  pais      responsáveis de pre_matricula.json (cadastros), um e-mail por e-mail distinto: quem tem mais de
            um filho recebe UMA mensagem com todos os nomes. Quem entra: matriculados (padrão), aguardando
            vaga ou ambos; nunca cancelados nem tentativas antigas substituídas (BUG-PRE-002).

MODOS (o envio real NÃO existe ainda — de propósito)
  simular   não envia nada: lista os destinatários, mostra a prévia da mensagem e grava o registro em
            dados/<ano>/AVISOS/.
  teste     envia UM e-mail de verdade, só para o endereço de teste, com "[TESTE]" no assunto e um aviso no
            topo. Os destinatários reais NUNCA recebem nada neste modo.
              - público escolas: o e-mail vai para a ESCOLA FICTÍCIA de teste (ESCOLA_TESTE: "ESCOLA MUNICIPAL
                TESTE DA SILVA", claudioalex16@gmail.com) e o texto sai montado exatamente como essa escola
                receberia ($ESCOLA_DESTINO = o nome dela). Funciona mesmo sem a lista de escolas coletada.
              - público pais: vai para o e-mail do próprio remetente, com o texto do primeiro destinatário.
            A escola fictícia nunca entra na lista real (simular).

MARCADORES na mensagem e no assunto ($MARCADOR; um desconhecido é recusado antes de qualquer envio):
  todos     $ESCOLA (nome da nossa escola)  $ANO  $DATA
  escolas   $ESCOLA_DESTINO (nome da escola que recebe)
  pais      $RESPONSAVEL  $ALUNO (nomes unidos por " e ")  $TURMA (turmas unidas por " e ")

Cada endereço recebe a sua própria mensagem (o SMTP de enviar_email aceita um destinatário por vez).
O registro em AVISOS/ guarda os textos montados e os e-mails dos destinatários: fica só neste computador.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from src.comum import credenciais, escola, paths
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json, salvar_json_atomico
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.logger import get_logger

log = get_logger(__file__)

PUBLICOS = {"escolas": "Escolas e CMEIs de Ponta Grossa", "pais": "Pais de alunos novos (pré-matrícula)"}
CANAIS = {"email": "E-mail"}
MODOS = {"simular": "Simular (não envia nada)", "teste": "Teste (envia só para o e-mail de teste)"}
TIPOS_ESCOLA = {"todas": "Escolas e CMEIs", "escolas": "Só escolas municipais", "cmeis": "Só CMEIs"}
SITUACOES_PAIS = {"matriculados": "Matriculados", "aguardando": "Aguardando vaga", "ambos": "Matriculados e aguardando"}

MARCADORES = {
    "comuns": ("ESCOLA", "ANO", "DATA"),
    "escolas": ("ESCOLA_DESTINO",),
    "pais": ("RESPONSAVEL", "ALUNO", "TURMA"),
}
# Escola FICTÍCIA usada no modo teste do público "escolas" (pedido do usuário, 20/10/2026): o e-mail de teste
# chega a esta caixa de verdade, com o texto montado como uma escola real o receberia.
ESCOLA_TESTE = {"nome": "ESCOLA MUNICIPAL TESTE DA SILVA", "email": "claudioalex16@gmail.com"}
LIMITE_ASSUNTO = 200
LIMITE_MENSAGEM = 20000
LINHAS_LISTADAS = 60

_RE_EMAIL_NO_TEXTO = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_RE_EMAIL_UNICO = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_RE_MARCADOR = re.compile(r"\$([A-Z][A-Z_]*)")
_PALAVRAS_GENERICAS = {"escola", "municipal", "prof", "profa", "profe", "professor", "professora", "cmei", "centro",
                       "de", "da", "do", "das", "dos", "e", "educacao", "infantil", "emei"}


# ───────────────────────────── utilitários ─────────────────────────────

def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").casefold()


def _uma_linha(valor) -> str:
    return " ".join(str(valor or "").split())


def extrair_emails(texto) -> list[str]:
    """Todos os e-mails de um texto (a célula do site pode ter mais de um), em minúsculas, sem repetir."""
    vistos: list[str] = []
    for achado in _RE_EMAIL_NO_TEXTO.findall(str(texto or "")):
        e = achado.lower()
        if e not in vistos:
            vistos.append(e)
    return vistos


def email_valido(texto) -> bool:
    return bool(_RE_EMAIL_UNICO.match(str(texto or "").strip()))


def _chave_nome_escola(nome: str) -> frozenset:
    """Palavras que identificam a escola (sem 'Escola Municipal', 'Profª', 'de'...), para reconhecer a própria escola."""
    palavras = re.findall(r"[a-z0-9]+", _sem_acento(nome))
    return frozenset(p for p in palavras if p not in _PALAVRAS_GENERICAS)


def _e_a_propria_escola(nome_candidata: str, nome_propria: str) -> bool:
    a, b = _chave_nome_escola(nome_candidata), _chave_nome_escola(nome_propria)
    return bool(a and b and (a == b or (len(a) >= 2 and a <= b) or (len(b) >= 2 and b <= a)))


def _lista_com_e(itens: list[str]) -> str:
    itens = [i for i in itens if i]
    return " e ".join(dict.fromkeys(itens))


# ───────────────────────────── público: escolas ─────────────────────────────

def arquivo_escolas() -> Path:
    return paths.dados_ano_atual() / "escolas_completas.json"


def carregar_escolas() -> list[dict]:
    """Registros de escolas_completas.json ({nome, endereco, ramal, email, fonte}). ValueError se faltar/estiver ruim."""
    caminho = arquivo_escolas()
    if not caminho.exists():
        raise ValueError("Ainda não existe a lista de escolas: execute primeiro a automação 'Coleta e-mails'.")
    try:
        dados = carregar_json(caminho, dict, tipo_esperado=dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    escolas = []
    for fonte, pagina in dados.items():
        for e in (pagina or {}).get("escolas", []) if isinstance(pagina, dict) else []:
            escolas.append({**e, "fonte": str(fonte)})
    return escolas


def destinatarios_escolas(tipo: str = "todas", filtro_nome: str = "") -> dict:
    """
    {"destinatarios": [{nome, email, contexto}], "sem_email": [nomes], "excluidas": [nomes]}.
    Fora da lista: a própria escola, a que não tem e-mail válido (vai em `sem_email`) e e-mail repetido.
    """
    propria = escola.nome()
    filtro = _sem_acento(filtro_nome).strip()
    meu_email = str(credenciais.EMAIL_REMETENTE or "").strip().lower()
    destinatarios, sem_email, excluidas, vistos = [], [], [], set()
    for e in carregar_escolas():
        nome = _uma_linha(e.get("nome"))
        if not nome:
            continue
        eh_cmei = "cmei" in e["fonte"].lower() or _sem_acento(nome).startswith("cmei")
        if (tipo == "cmeis" and not eh_cmei) or (tipo == "escolas" and eh_cmei):
            continue
        if filtro and filtro not in _sem_acento(nome):
            continue
        emails = extrair_emails(e.get("email"))
        if propria and _e_a_propria_escola(nome, propria) or (meu_email and meu_email in emails):
            excluidas.append(nome)
            continue
        if not emails:
            sem_email.append(nome)
            continue
        for em in emails:
            if em in vistos:
                continue
            vistos.add(em)
            destinatarios.append({"nome": nome, "email": em, "contexto": {"ESCOLA_DESTINO": nome}})
    return {"destinatarios": destinatarios, "sem_email": sem_email, "excluidas": excluidas}


# ───────────────────────────── público: pais (pré-matrícula) ─────────────────────────────

def arquivo_pre_matricula() -> Path:
    return paths.dados_ano_atual() / "pre_matricula.json"


def carregar_pre_matricula() -> dict:
    caminho = arquivo_pre_matricula()
    if not caminho.exists():
        raise ValueError("Ainda não existe pre_matricula.json: execute primeiro a automação 'Pré-matrícula'.")
    try:
        dados = carregar_json(caminho, dict, tipo_esperado=dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc
    return dados


def situacao_do_aluno(aluno: dict) -> str:
    """'matriculado' | 'aguardando' | 'cancelado' | 'outra', a partir do texto de situação da pré-matrícula."""
    texto = _sem_acento(aluno.get("situacao"))
    if "cancel" in texto:
        return "cancelado"
    if "matricul" in texto or (not texto and aluno.get("matriculado_em")):
        return "matriculado"
    if not texto:
        return "aguardando"
    return "outra"


def destinatarios_pais(situacao: str = "matriculados") -> dict:
    """
    {"destinatarios": [{nome, email, contexto}], "sem_email": [descrições], "alunos": n}.
    Um destinatário por e-mail: responsável com vários filhos recebe uma mensagem só.
    """
    aceitas = {"matriculados": {"matriculado"}, "aguardando": {"aguardando"}, "ambos": {"matriculado", "aguardando"}}[situacao]
    base = carregar_pre_matricula()
    cadastros = base.get("cadastros") or {}
    por_email: dict[str, dict] = {}
    sem_email, alunos = [], 0
    for turma, lista in (base.get("turmas_intencao") or {}).items():
        for a in lista or []:
            if a.get("substituido_por_nova_tentativa") or situacao_do_aluno(a) not in aceitas:
                continue
            alunos += 1
            cad = cadastros.get(str(a.get("cpf") or "")) or cadastros.get(str(a.get("tr_id") or "")) or {}
            nome_aluno = _uma_linha(a.get("nome") or cad.get("nome_aluno"))
            emails = extrair_emails(cad.get("email"))
            if not emails:
                sem_email.append(f"{nome_aluno} ({turma})" + ("" if cad else " — sem cadastro consultado"))
                continue
            turma_limpa = _uma_linha(str(turma).replace(" do Ensino Fundamental", ""))
            resp = _uma_linha(cad.get("nome_responsavel"))
            for em in emails[:1]:                                   # o cadastro tem um e-mail só; extras seriam ruído
                reg = por_email.setdefault(em, {"nome": resp, "email": em, "alunos": [], "turmas": []})
                if not reg["nome"]:
                    reg["nome"] = resp
                reg["alunos"].append(nome_aluno)
                reg["turmas"].append(turma_limpa)
    destinatarios = []
    for reg in por_email.values():
        destinatarios.append({"nome": reg["nome"] or reg["email"], "email": reg["email"], "contexto": {
            "RESPONSAVEL": reg["nome"] or "Responsável", "ALUNO": _lista_com_e(reg["alunos"]),
            "TURMA": _lista_com_e(reg["turmas"])}})
    return {"destinatarios": destinatarios, "sem_email": sem_email, "alunos": alunos}


# ───────────────────────────── texto: marcadores ─────────────────────────────

def marcadores_validos(publico: str) -> tuple[str, ...]:
    return MARCADORES["comuns"] + MARCADORES[publico]


def conferir_marcadores(texto: str, publico: str, onde: str) -> None:
    """ValueError com a lista de marcadores desconhecidos e dos válidos."""
    validos = marcadores_validos(publico)
    desconhecidos = sorted({m for m in _RE_MARCADOR.findall(texto) if m not in validos})
    if desconhecidos:
        raise ValueError(f"{onde}: marcador(es) desconhecido(s) " + ", ".join("$" + m for m in desconhecidos)
                         + ". Os que valem para este público: " + ", ".join("$" + m for m in validos) + ".")


def renderizar(texto: str, contexto: dict) -> str:
    return _RE_MARCADOR.sub(lambda m: str(contexto.get(m.group(1), m.group(0))), texto)


def _contexto_base() -> dict:
    return {"ESCOLA": _uma_linha(escola.nome()), "ANO": str(paths.ano_atual()), "DATA": datetime.now().strftime("%d/%m/%Y")}


# ───────────────────────────── validação e montagem ─────────────────────────────

def _credenciais_email_ok() -> bool:
    return (str(credenciais.EMAIL_REMETENTE or "").strip() not in ("", "email@exemplo.com")
            and str(credenciais.EMAIL_SENHA_APP or "") not in ("", "senha_app_email"))


def validar_pedido(publico, canal, modo, assunto, mensagem, tipo_escola="todas", filtro_nome="",
                   situacao_pais="matriculados", email_teste="") -> dict:
    """Confere TUDO antes de qualquer envio. ValueError com mensagem pronta; devolve os parâmetros já normalizados."""
    publico, canal, modo = str(publico or ""), str(canal or "email"), str(modo or "simular")
    if publico not in PUBLICOS:
        raise ValueError("Escolha para quem é o comunicado (escolas ou pais).")
    if canal not in CANAIS:
        raise ValueError(f"Canal '{canal}' ainda não existe. Por enquanto só: " + ", ".join(CANAIS) + ".")
    if modo not in MODOS:
        raise ValueError("Modo inválido. O envio real ainda não foi liberado: use 'simular' ou 'teste'.")
    assunto, mensagem = str(assunto or "").strip(), str(mensagem or "").strip()
    if not assunto:
        raise ValueError("Escreva o assunto do e-mail.")
    if "\n" in assunto or "\r" in assunto:
        raise ValueError("O assunto precisa ter uma linha só.")
    if len(assunto) > LIMITE_ASSUNTO:
        raise ValueError(f"O assunto passa de {LIMITE_ASSUNTO} caracteres.")
    if not mensagem:
        raise ValueError("Escreva a mensagem.")
    if len(mensagem) > LIMITE_MENSAGEM:
        raise ValueError(f"A mensagem passa de {LIMITE_MENSAGEM} caracteres.")
    conferir_marcadores(assunto, publico, "Assunto")
    conferir_marcadores(mensagem, publico, "Mensagem")
    if publico == "escolas" and str(tipo_escola or "todas") not in TIPOS_ESCOLA:
        raise ValueError("Tipo de escola inválido: use todas, escolas ou cmeis.")
    if publico == "pais" and str(situacao_pais or "matriculados") not in SITUACOES_PAIS:
        raise ValueError("Situação inválida: use matriculados, aguardando ou ambos.")
    if "ESCOLA" in set(_RE_MARCADOR.findall(assunto)) | set(_RE_MARCADOR.findall(mensagem)) and not escola.nome():
        raise ValueError("O texto usa $ESCOLA, mas o nome da escola ainda não foi informado (Configurações → Dados da escola).")
    email_teste = str(email_teste or "").strip().lower()
    if modo == "teste":
        if not _credenciais_email_ok():
            raise ValueError("Para o modo teste, salve o e-mail e a senha de app do Gmail em Configurações → Senha do Gmail.")
        padrao = ESCOLA_TESTE["email"] if publico == "escolas" else str(credenciais.EMAIL_REMETENTE).strip()
        email_teste = email_teste or padrao.lower()
        if not email_valido(email_teste):
            raise ValueError("O e-mail de teste não parece um endereço válido.")
    return {"publico": publico, "canal": canal, "modo": modo, "assunto": assunto, "mensagem": mensagem,
            "tipo_escola": str(tipo_escola or "todas"), "filtro_nome": str(filtro_nome or "").strip(),
            "situacao_pais": str(situacao_pais or "matriculados"), "email_teste": email_teste}


def teste_com_escola_ficticia(publico: str, modo: str) -> bool:
    """No modo teste das escolas o e-mail vai para a escola fictícia; a lista real é opcional."""
    return modo == "teste" and publico == "escolas"


def reunir_destinatarios(publico: str, tipo_escola="todas", filtro_nome="", situacao_pais="matriculados") -> dict:
    if publico == "escolas":
        r = destinatarios_escolas(tipo_escola, filtro_nome)
    else:
        r = destinatarios_pais(situacao_pais)
    if not r["destinatarios"]:
        raise ValueError("Nenhum destinatário com e-mail válido para este público e estes filtros.")
    return r


def montar_mensagens(destinatarios: list[dict], assunto: str, mensagem: str) -> list[dict]:
    base = _contexto_base()
    mensagens = []
    for d in destinatarios:
        ctx = {**base, **{k: _uma_linha(v) for k, v in d["contexto"].items()}}
        mensagens.append({"para": d["email"], "nome": d["nome"], "assunto": renderizar(assunto, ctx),
                          "corpo": renderizar(mensagem, ctx)})
    return mensagens


def pasta_avisos() -> Path:
    return paths.dados_ano_atual() / "AVISOS"


def _gravar_registro(publico: str, modo: str, dados: dict) -> Path:
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = pasta_avisos() / f"{carimbo}_{publico}_{modo}.json"
    salvar_json_atomico(caminho, dados, indent=2)
    return caminho


# ───────────────────────────── ponto de entrada ─────────────────────────────

def executar_avisos(publico, canal, modo, assunto, mensagem, tipo_escola="todas", filtro_nome="",
                    situacao_pais="matriculados", email_teste="") -> dict:
    """
    Monta o comunicado e, conforme o modo, só simula ou envia UM e-mail de teste. Nunca escreve aos destinatários
    reais. Devolve {"modo","publico","canal","total","simulados","enviados_teste","sem_email","registro"}.
    """
    p = validar_pedido(publico, canal, modo, assunto, mensagem, tipo_escola, filtro_nome, situacao_pais, email_teste)
    ficticia = teste_com_escola_ficticia(p["publico"], p["modo"])
    aviso_lista = ""
    try:
        r = reunir_destinatarios(p["publico"], p["tipo_escola"], p["filtro_nome"], p["situacao_pais"])
    except ValueError as exc:
        if not ficticia:
            raise
        aviso_lista = str(exc)                      # o teste com a escola fictícia não depende da lista real
        r = {"destinatarios": [], "sem_email": [], "excluidas": []}
    mensagens = montar_mensagens(r["destinatarios"], p["assunto"], p["mensagem"])
    total = len(mensagens)
    verificar_cancelamento()

    titulo_modo = "SIMULAÇÃO — nada será enviado" if p["modo"] == "simular" else "TESTE — só o e-mail de teste recebe"
    print(f"Comunicado oficial por e-mail | Público: {PUBLICOS[p['publico']]} | Modo: {titulo_modo}")
    print(f"{total} destinatário(s):")
    for m in mensagens[:LINHAS_LISTADAS]:
        print(f"  - {m['nome']} <{m['para']}>")
    if total > LINHAS_LISTADAS:
        print(f"  … e mais {total - LINHAS_LISTADAS} (a lista completa fica no registro).")
    if r.get("excluidas"):
        print(f"Fora da lista (a própria escola): {', '.join(r['excluidas'])}")
    if r["sem_email"]:
        print(f"Sem e-mail válido ({len(r['sem_email'])}) — não receberiam: " + "; ".join(r["sem_email"][:LINHAS_LISTADAS]))
    if aviso_lista:
        print(f"Aviso: {aviso_lista} (o teste com a escola fictícia segue mesmo assim).")
    if p["publico"] == "escolas" and p["modo"] == "simular":
        print(f"No modo Teste, o e-mail iria para a escola fictícia {ESCOLA_TESTE['nome']} <{ESCOLA_TESTE['email']}>.")

    if mensagens:
        amostra = mensagens[0]
        print(f"\nPRÉVIA — mensagem 1 de {total} (para {amostra['nome']})\nAssunto: {amostra['assunto']}\n\n{amostra['corpo']}\n")

    enviados_teste, erro, escola_teste = 0, None, None
    if p["modo"] == "teste":
        from src.automacao.envia_email import enviar_email
        if ficticia:                                # texto como a escola fictícia o receberia
            escola_teste = {"nome": ESCOLA_TESTE["nome"], "email": p["email_teste"]}
            exemplo = montar_mensagens(
                [{**escola_teste, "contexto": {"ESCOLA_DESTINO": ESCOLA_TESTE["nome"]}}], p["assunto"], p["mensagem"])[0]
            quem = f"a escola fictícia de teste: {escola_teste['nome']} <{escola_teste['email']}>"
        else:
            exemplo = mensagens[0]
            quem = f"{exemplo['nome']} <{exemplo['para']}>"
        faixa = (f"*** TESTE — esta mensagem NÃO foi enviada aos destinatários reais. ***\n"
                 f"O comunicado iria para {total} destinatário(s) reais. Abaixo, o texto montado para {quem}\n"
                 + "-" * 60 + "\n\n")
        print(f"Enviando o e-mail de teste para {p['email_teste']}...")
        ok, erro = enviar_email(p["email_teste"], "[TESTE] " + exemplo["assunto"], faixa + exemplo["corpo"])
        if not ok:
            raise RuntimeError(f"Não consegui enviar o e-mail de teste: {erro}")
        enviados_teste = 1
        print(f"E-mail de teste enviado para {p['email_teste']}.")

    registro = _gravar_registro(p["publico"], p["modo"], {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "publico": p["publico"], "canal": p["canal"],
        "modo": p["modo"], "assunto": p["assunto"], "mensagem": p["mensagem"], "filtros": {
            "tipo_escola": p["tipo_escola"], "filtro_nome": p["filtro_nome"], "situacao_pais": p["situacao_pais"]},
        "email_teste": p["email_teste"] if p["modo"] == "teste" else "", "escola_teste": escola_teste, "total": total,
        "enviados_teste": enviados_teste, "sem_email": r["sem_email"], "excluidas": r.get("excluidas", []),
        "mensagens": mensagens})
    print(f"Registro salvo em: {registro}")
    return {"modo": p["modo"], "publico": p["publico"], "canal": p["canal"], "total": total,
            "simulados": total if p["modo"] == "simular" else 0, "enviados_teste": enviados_teste,
            "sem_email": r["sem_email"], "registro": str(registro)}

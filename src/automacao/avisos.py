"""
avisos.py — Comunicados oficiais por e-mail (escola → escolas, escola → pais)
=============================================================================
Pedido do usuário (20/10/2026): comunicação de ESCOLA PARA ESCOLA (as escolas de Ponta Grossa que vêm da automação
"Coleta e-mails") e de ESCOLA PARA OS PAIS (responsáveis dos alunos novos da PRÉ-MATRÍCULA).
Revisão de 14/11/2026: só se comunica com quem está CHEGANDO (nada para pais de quem sai), tanto na pré-matrícula do ano
letivo quanto na previsão do próximo; envio real liberado, com prévia obrigatória, pausa, limite por execução e registro.

PÚBLICOS
  escolas   escolas municipais e CMEIs de escolas_completas.json (Coleta e-mails), exceto a própria escola.
            "Quais unidades": nada marcado = todas; ou grupos (@escolas, @cmeis) e/ou escolas pelo nome.
            Dois jeitos de enviar, decididos pelo TEXTO:
              - sem marcador de aluno: um e-mail por unidade (e por endereço dela);
              - com $ALUNO, $CGM, $SERIE ou $TURMA: um e-mail POR ALUNO que chega, para a escola de ORIGEM dele (o vínculo
                da Base ABC gravado em pre_matricula.json / previsao_alunos_<ano+1>.json). Só entra quem tem vínculo "ok"
                com CGM e escola, cuja escola está na lista e tem e-mail (vai o primeiro). O resto fica numa lista de
                "não recebem" (sem vínculo, a verificar, origem fora da lista, já na nossa escola, escola sem e-mail).
  destino   escola de DESTINO dos alunos transferidos (2026-11-19): um e-mail por aluno que SAIU, para a escola para onde ele foi
            (vínculo da Base ABC gravado em transferidos.json, ou o destino preenchido à mão na tela de Transferidos),
            avisando que histórico, guia e parecer estão na pasta do aluno e seguem em ANEXO neste e-mail. Só entra quem tem
            os três arquivos da saída atual, a escola na lista de e-mails e o aviso "automático" (quem foi marcado como
            "encaminhado por e-mail à parte" ou "não avisar automaticamente" fica de fora). Veja destino_transferidos.py.
  pais      responsáveis dos alunos novos, um e-mail por e-mail distinto: quem tem mais de um filho recebe UMA mensagem.
            Quem entra: matriculados (padrão), aguardando vaga ou ambos; nunca cancelados nem tentativas antigas
            substituídas (BUG-PRE-002).
  FONTE dos alunos novos (os dois públicos): "ano" (pre_matricula.json), "proximo" (previsao_alunos_<ano+1>.json) ou
  "ambas" (o aluno que está nos dois conta uma vez, pelo CPF).

MODOS
  simular   não envia nada: lista os destinatários, mostra a prévia, grava o registro em dados/<ano>/AVISOS/ e guarda a
            "impressão digital" do comunicado (AVISOS/previas.json), que libera o envio real por 24 h.
  teste     envia UM e-mail de verdade, só para o endereço de teste, com "[TESTE]" no assunto e um aviso no topo. Os
            destinatários reais NUNCA recebem nada neste modo.
              - escolas: vai para a ESCOLA FICTÍCIA (ESCOLA_TESTE), com o texto como ela receberia (num texto por aluno,
                com o primeiro aluno real);
              - pais: vai para o e-mail do próprio remetente, com o texto do primeiro destinatário.
  enviar    ENVIO REAL. Só depois de uma simulação do MESMO comunicado (texto + destinatários) de até 24 h. Um e-mail por
            vez, com pausa entre eles (`intervalo_s`) e no máximo `limite_lote` por execução. Quem já recebeu este texto
            (AVISOS/enviados.json) não recebe de novo: cancelar e rodar outra vez continua de onde parou. O registro
            (AVISOS/<data>_<público>_enviar.json) é regravado a cada e-mail: enviados, falhas (com o erro), já enviados e
            os que faltam. 3 falhas seguidas (senha errada, sem rede...) param o envio.

MARCADORES na mensagem e no assunto ($MARCADOR; um desconhecido é recusado antes de qualquer envio):
  todos     $ESCOLA (nome da nossa escola)  $ANO  $DATA
  escolas   $ESCOLA_DESTINO (escola que recebe)  $ALUNO  $CGM  $SERIE (série na escola de origem)  $TURMA (turma pretendida aqui)
  destino   $ESCOLA_DESTINO (escola para onde o aluno foi)  $ALUNO  $CGM  $TURMA (turma dele aqui)  $DATA_SAIDA (data da transferência)
  pais      $RESPONSAVEL  $ALUNO (nomes unidos por " e ")  $TURMA (turmas unidas por " e ")

Os modelos de mensagem (tipo de mensagem na tela) ficam em src/comum/modelos_avisos.py.
Cada endereço recebe a sua própria mensagem (o SMTP de enviar_email aceita um destinatário por vez).
O registro em AVISOS/ guarda os textos montados e os e-mails dos destinatários: fica só neste computador.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.comum import credenciais, escola, paths, previsao
from src.comum import destino_transferidos as destino_tf
from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json, salvar_json_atomico
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.logger import get_logger

log = get_logger(__file__)

PUBLICOS = {"escolas": "Escolas e CMEIs de Ponta Grossa", "pais": "Pais de alunos novos (pré-matrícula)",
            "destino": "Escola de destino dos alunos transferidos"}
CANAIS = {"email": "E-mail"}
MODOS = {"simular": "Simular (não envia nada)", "teste": "Teste (envia só para o e-mail de teste)",
         "enviar": "Enviar de verdade (para os destinatários reais)"}
TIPOS_ESCOLA = {"todas": "Escolas e CMEIs", "escolas": "Só escolas municipais", "cmeis": "Só CMEIs"}
SITUACOES_PAIS = {"matriculados": "Matriculados", "aguardando": "Aguardando vaga", "ambos": "Matriculados e aguardando"}
FONTES_ALUNOS = {"ano": "Pré-matrícula do ano letivo", "proximo": "Previsão do próximo ano", "ambas": "As duas"}
GRUPOS_UNIDADES = {"@todas": "Todas as escolas e CMEIs", "@escolas": "Todas as escolas municipais", "@cmeis": "Todos os CMEIs"}

MARCADORES = {
    "comuns": ("ESCOLA", "ANO", "DATA"),
    # ALUNO/CGM/SERIE/TURMA: usados num texto para a escola de ORIGEM do aluno que chega (um e-mail por aluno)
    "escolas": ("ESCOLA_DESTINO", "ALUNO", "CGM", "SERIE", "TURMA"),
    "pais": ("RESPONSAVEL", "ALUNO", "TURMA"),
    # um e-mail por aluno transferido, para a escola para onde ele foi; os documentos seguem em anexo
    "destino": ("ESCOLA_DESTINO", "ALUNO", "CGM", "TURMA", "DATA_SAIDA"),
}
# Escola FICTÍCIA usada no modo teste do público "escolas" (pedido do usuário, 20/10/2026): o e-mail de teste
# chega a esta caixa de verdade, com o texto montado como uma escola real o receberia.
ESCOLA_TESTE = {"nome": "ESCOLA MUNICIPAL TESTE DA SILVA", "email": "claudioalex16@gmail.com"}
MARCADORES_DE_ALUNO = ("ALUNO", "CGM", "SERIE", "TURMA", "DATA_SAIDA")      # no público escolas, quem usa vira "um e-mail por aluno"
LIMITE_ASSUNTO = 200
LIMITE_MENSAGEM = 20000
LINHAS_LISTADAS = 60

# envio real
INTERVALO_PADRAO_S, INTERVALO_MIN_S, INTERVALO_MAX_S = 10, 2, 300     # pausa entre um e-mail e o seguinte
LOTE_PADRAO, LOTE_MIN, LOTE_MAX = 50, 1, 500                         # e-mails por execução (o Gmail limita o envio diário)
VALIDADE_PREVIA_HORAS = 24                                           # a simulação precisa ser de até 24 h antes do envio
FALHAS_SEGUIDAS_MAX = 3                                              # 3 falhas seguidas: o envio para (senha errada, sem rede...)

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
    """
    Palavras que identificam a escola (sem 'Escola Municipal', 'Profª', 'de'...), para reconhecer a própria escola.
    A Base ABC escreve \"JUDITH M SILVEIRA,E M PROFA-EI EF\": vale só o que vem antes da vírgula, e letras soltas (a inicial
    do nome do meio) não contam.
    """
    palavras = re.findall(r"[a-z0-9]+", _sem_acento(str(nome or "").split(",")[0]))
    return frozenset(p for p in palavras if len(p) > 1 and p not in _PALAVRAS_GENERICAS)


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


def _eh_cmei(e: dict) -> bool:
    return "cmei" in str(e.get("fonte") or "").lower() or _sem_acento(e.get("nome")).startswith("cmei")


def _itens_unidades(unidades) -> list[str]:
    """Os itens marcados em \"Quais unidades\" como lista de textos. Aceita lista, texto JSON de lista ou um nome só."""
    if isinstance(unidades, str):
        texto = unidades.strip()
        try:
            achado = json.loads(texto) if texto.startswith("[") else [texto]
        except ValueError:
            achado = [texto]
        unidades = achado
    return [_uma_linha(u) for u in (unidades or []) if _uma_linha(u)]


def normalizar_unidades(unidades) -> Optional[tuple[frozenset, frozenset]]:
    """
    (grupos, nomes) das unidades escolhidas na tela, ou None para "todas".
    Grupos: "@escolas", "@cmeis" ("@todas" = sem filtro). Nomes comparados sem acento e sem diferença de caixa.
    """
    itens = _itens_unidades(unidades)
    if not itens or "@todas" in itens:
        return None
    grupos = {i for i in itens if i.startswith("@")}
    desconhecidos = grupos - set(GRUPOS_UNIDADES)
    if desconhecidos:
        raise ValueError("Grupo de unidades desconhecido: " + ", ".join(sorted(desconhecidos)) + ".")
    return frozenset(grupos), frozenset(_sem_acento(i) for i in itens if not i.startswith("@"))


def _unidade_escolhida(nome: str, eh_cmei: bool, escolhidas: Optional[tuple[frozenset, frozenset]]) -> bool:
    if escolhidas is None:
        return True
    grupos, nomes = escolhidas
    return (("@cmeis" in grupos and eh_cmei) or ("@escolas" in grupos and not eh_cmei) or _sem_acento(nome) in nomes)


def listar_unidades() -> list[dict]:
    """[{nome, tipo: 'escola'|'cmei', tem_email}] das unidades da lista coletada (sem a própria escola), em ordem alfabética."""
    propria = escola.nome()
    saida, vistos = [], set()
    for e in carregar_escolas():
        nome = _uma_linha(e.get("nome"))
        if not nome or _sem_acento(nome) in vistos or (propria and _e_a_propria_escola(nome, propria)):
            continue
        vistos.add(_sem_acento(nome))
        saida.append({"nome": nome, "tipo": "cmei" if _eh_cmei(e) else "escola", "tem_email": bool(extrair_emails(e.get("email")))})
    return sorted(saida, key=lambda u: _sem_acento(u["nome"]))


def destinatarios_escolas(tipo: str = "todas", filtro_nome: str = "", unidades=None) -> dict:
    """
    {"destinatarios": [{nome, email, contexto}], "sem_email": [nomes], "excluidas": [nomes]}.
    Fora da lista: a própria escola, a que não tem e-mail válido (vai em `sem_email`) e e-mail repetido.
    `unidades`: o que foi marcado em "Quais unidades" (ver normalizar_unidades); vazio = todas.
    """
    propria = escola.nome()
    escolhidas = normalizar_unidades(unidades)
    filtro = _sem_acento(filtro_nome).strip()
    meu_email = str(credenciais.EMAIL_REMETENTE or "").strip().lower()
    destinatarios, sem_email, excluidas, vistos = [], [], [], set()
    for e in carregar_escolas():
        nome = _uma_linha(e.get("nome"))
        if not nome:
            continue
        eh_cmei = _eh_cmei(e)
        if (tipo == "cmeis" and not eh_cmei) or (tipo == "escolas" and eh_cmei):
            continue
        if filtro and filtro not in _sem_acento(nome):
            continue
        if not _unidade_escolhida(nome, eh_cmei, escolhidas):
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


def _bases_de_alunos(fonte: str) -> list[tuple[str, dict]]:
    """
    [(rótulo, dados)] das fontes de alunos novos: a pré-matrícula do ano letivo ("ano") e/ou a previsão do próximo ano
    ("proximo"), cada uma com as chaves `cadastros` e `turmas_intencao`. Com "ambas", basta uma existir. ValueError com a
    mensagem pronta se nenhuma existe ou se a que existe está ilegível.
    """
    fonte = str(fonte or "ano")
    if fonte not in FONTES_ALUNOS:
        raise ValueError("Fonte dos alunos novos inválida: use ano, proximo ou ambas.")
    achadas: list[tuple[str, dict]] = []
    faltando: list[str] = []
    if fonte in ("ano", "ambas"):
        try:
            achadas.append(("ano", carregar_pre_matricula()))
        except ValueError as exc:
            if not str(exc).startswith("Ainda não existe"):
                raise                                            # arquivo ilegível: nunca seguir como se não existisse
            faltando.append(str(exc))
    if fonte in ("proximo", "ambas"):
        ano_proximo = int(paths.ano_atual()) + 1
        try:
            dados = previsao.carregar_previsao_alunos(paths.dados_ano_atual(), ano_proximo)
        except ArquivoJsonCorrompidoError as exc:
            raise ValueError(str(exc)) from exc
        if dados:
            achadas.append(("proximo", dados))
        else:
            faltando.append(f"Ainda não existe {previsao.nome_arquivo(ano_proximo)}: execute primeiro a automação 'Pré-matrícula' "
                            "com a previsão do próximo ano.")
    if not achadas:
        raise ValueError(" ".join(faltando))
    return achadas


def id_do_aluno(a: dict) -> str:
    """Identifica o aluno novo na tela e no pedido: o CPF; sem ele, o tr_id; sem os dois, o nome."""
    return str(a.get("cpf") or a.get("tr_id") or "") or "nome:" + _sem_acento(a.get("nome"))


def _alunos_da_base(base: dict, aceitas: set, vistos: set, escolhidos: Optional[set] = None):
    """
    (turma, aluno, cadastro) dos alunos novos que valem: situação aceita, sem tentativa substituída, sem repetir o CPF e,
    se `escolhidos` (ids marcados na tela) não for vazio, só esses.
    """
    cadastros = base.get("cadastros") or {}
    for turma, lista in (base.get("turmas_intencao") or {}).items():
        for a in lista or []:
            if a.get("substituido_por_nova_tentativa") or situacao_do_aluno(a) not in aceitas:
                continue
            if escolhidos and id_do_aluno(a) not in escolhidos:
                continue
            cpf = str(a.get("cpf") or "")
            if cpf and cpf in vistos:                           # o mesmo aluno nos dois arquivos
                continue
            if cpf:
                vistos.add(cpf)
            cad = cadastros.get(cpf) or cadastros.get(str(a.get("tr_id") or "")) or {}
            yield turma, a, cad


_SITUACOES_ACEITAS = {"matriculados": {"matriculado"}, "aguardando": {"aguardando"}, "ambos": {"matriculado", "aguardando"}}


def _origem_e_serie(v: dict, propria: str, turma_limpa: str) -> tuple[str, str, bool]:
    """
    (escola de origem, série nela, já_está_na_nossa_escola) a partir do vínculo da Base ABC. Se a linha do ano é a NOSSA escola
    (o aluno já entrou), a origem é a escola anterior do histórico; sem ela, o aluno já está aqui e não há a quem pedir.
    """
    origem, serie = _uma_linha(v.get("escola")), _uma_linha(v.get("turma")) or turma_limpa
    if propria and origem and _e_a_propria_escola(origem, propria):
        anterior = _uma_linha(v.get("escola_anterior"))
        if anterior and not _e_a_propria_escola(anterior, propria):
            return anterior, _uma_linha(v.get("turma_anterior")) or serie, False
        return origem, serie, True
    return origem, serie, False


def posicao_do_aluno(aluno: dict) -> Optional[int]:
    """Posição do aluno na lista da turma (coluna "pos" que a coleta da pré-matrícula guarda: "3", "3º"...). None se não vier."""
    m = re.search(r"\d+", str(aluno.get("pos") or ""))
    return int(m.group()) if m else None


def listar_alunos_novos(situacao: str = "matriculados", fonte: str = "ano") -> list[dict]:
    """
    Os alunos novos para a tela escolher: [{id, nome, turma, pos, serie, fonte, estado, cgm, escola_origem, na_nossa_escola, motivo}],
    por nome. `pos` é a posição na lista da turma (int ou None): a tela usa para marcar uma faixa, ex.: do 1º ao 5º da turma. `escola_origem`/`serie` são as de quem receberia o pedido (a escola anterior, se o aluno já entrou aqui).
    `estado`: "ok" (vínculo da Base ABC com CGM e escola), "verificar" (vínculo incompleto) ou "sem_vinculo" (a Consulta na
    Base ABC ainda não achou/gravou o aluno). Mostra quem já está pronto para um texto com $CGM e $SERIE.
    """
    if situacao not in _SITUACOES_ACEITAS:
        raise ValueError("Situação inválida: use matriculados, aguardando ou ambos.")
    saida, vistos, propria = [], set(), escola.nome()
    for rotulo, base in _bases_de_alunos(fonte):
        for turma, a, cad in _alunos_da_base(base, _SITUACOES_ACEITAS[situacao], vistos):
            v = a.get("vinculo_base_abc") or cad.get("vinculo_base_abc") or {}
            cgm = re.sub(r"\D", "", str(v.get("cgm") or ""))
            estado = "sem_vinculo" if not v else ("ok" if v.get("status") == "ok" and cgm and v.get("escola") else "verificar")
            turma_limpa = _uma_linha(str(turma).replace(" do Ensino Fundamental", ""))
            origem, serie, ja_aqui = _origem_e_serie(v, propria, turma_limpa)
            saida.append({"id": id_do_aluno(a), "nome": _uma_linha(a.get("nome") or cad.get("nome_aluno")),
                          "turma": turma_limpa, "pos": posicao_do_aluno(a), "serie": serie, "fonte": rotulo, "estado": estado, "cgm": cgm,
                          "escola_origem": origem, "na_nossa_escola": bool(v) and ja_aqui, "motivo": _uma_linha(v.get("motivo"))})
    return sorted(saida, key=lambda x: _sem_acento(x["nome"]))


def destinatarios_pais(situacao: str = "matriculados", fonte: str = "ano", alunos=None) -> dict:
    """
    {"destinatarios": [{nome, email, contexto}], "sem_email": [descrições], "alunos": n}.
    Um destinatário por e-mail: responsável com vários filhos recebe uma mensagem só (também entre a pré-matrícula do
    ano e a previsão do próximo, se `fonte` for "ambas").
    """
    aceitas = _SITUACOES_ACEITAS[situacao]
    escolhidos = set(_itens_unidades(alunos)) or None
    por_email: dict[str, dict] = {}
    sem_email, total_alunos, vistos = [], 0, set()
    for _rotulo, base in _bases_de_alunos(fonte):
        for turma, a, cad in _alunos_da_base(base, aceitas, vistos, escolhidos):
            total_alunos += 1
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
    return {"destinatarios": destinatarios, "sem_email": sem_email, "alunos": total_alunos}


# ───────────── público: escolas, um e-mail por ALUNO que chega (pedido à escola de origem) ─────────────

def _achar_unidade(origem: str, unidades: list[dict]) -> Optional[dict]:
    """A unidade da lista que é a escola de origem. Nome igual vence; senão só vale se for a ÚNICA parecida."""
    chave = _chave_nome_escola(origem)
    if not chave:
        return None
    iguais = [u for u in unidades if _chave_nome_escola(u["nome"]) == chave]
    if iguais:
        return iguais[0]
    parecidas = [u for u in unidades if _e_a_propria_escola(origem, u["nome"])]
    return parecidas[0] if len(parecidas) == 1 else None


def destinatarios_alunos_origem(situacao: str = "matriculados", fonte: str = "ano", tipo: str = "todas",
                                filtro_nome: str = "", unidades=None, alunos=None) -> dict:
    """
    Um destinatário POR ALUNO novo: a escola de origem dele (do vínculo da Base ABC gravado na pré-matrícula/previsão),
    com o e-mail da lista coletada (o primeiro, se a escola tem mais de um).

    Devolve {"destinatarios", "sem_email", "alunos", "sem_vinculo", "a_verificar", "origem_desconhecida", "da_propria_escola",
    "fora_da_selecao"}. Só entra quem tem vínculo `ok` com CGM e escola; o que não fecha vai numa dessas listas (e NÃO
    recebe e-mail) para ninguém pedir transferência à escola errada. Rode a "Consulta na Base ABC" antes.
    """
    aceitas = _SITUACOES_ACEITAS[situacao]
    escolhidas = normalizar_unidades(unidades)
    alunos_marcados = set(_itens_unidades(alunos)) or None
    filtro = _sem_acento(filtro_nome).strip()
    propria = escola.nome()
    lista = [{"nome": _uma_linha(e.get("nome")), "eh_cmei": _eh_cmei(e), "emails": extrair_emails(e.get("email"))}
             for e in carregar_escolas() if _uma_linha(e.get("nome"))]
    r = {"destinatarios": [], "sem_email": [], "alunos": 0, "sem_vinculo": [], "a_verificar": [],
         "origem_desconhecida": [], "da_propria_escola": [], "fora_da_selecao": 0}
    vistos = set()
    for _rotulo, base in _bases_de_alunos(fonte):
        for turma, a, cad in _alunos_da_base(base, aceitas, vistos, alunos_marcados):
            r["alunos"] += 1
            nome_aluno = _uma_linha(a.get("nome") or cad.get("nome_aluno"))
            turma_limpa = _uma_linha(str(turma).replace(" do Ensino Fundamental", ""))
            quem = f"{nome_aluno} ({turma_limpa})"
            v = a.get("vinculo_base_abc") or cad.get("vinculo_base_abc") or {}
            if not v:
                r["sem_vinculo"].append(quem)
                continue
            cgm = re.sub(r"\D", "", str(v.get("cgm") or ""))
            if v.get("status") != "ok" or not _uma_linha(v.get("escola")) or not cgm:
                r["a_verificar"].append(f"{quem} — {v.get('motivo') or 'vínculo incompleto'}")
                continue
            origem, serie, ja_aqui = _origem_e_serie(v, propria, turma_limpa)
            if ja_aqui:
                r["da_propria_escola"].append(quem)
                continue
            un = _achar_unidade(origem, lista)
            if un is None:
                r["origem_desconhecida"].append(f"{quem} — {origem}")
                continue
            if ((tipo == "cmeis" and not un["eh_cmei"]) or (tipo == "escolas" and un["eh_cmei"])
                    or (filtro and filtro not in _sem_acento(un["nome"]))
                    or not _unidade_escolhida(un["nome"], un["eh_cmei"], escolhidas)):
                r["fora_da_selecao"] += 1
                continue
            if not un["emails"]:
                r["sem_email"].append(f"{un['nome']} (aluno {nome_aluno})")
                continue
            r["destinatarios"].append({"nome": un["nome"], "email": un["emails"][0], "contexto": {
                "ESCOLA_DESTINO": un["nome"], "ALUNO": nome_aluno, "CGM": cgm, "SERIE": serie, "TURMA": turma_limpa}})
    return r


# ───────────── público: escola de DESTINO dos transferidos (um e-mail por aluno, com os documentos em anexo) ─────────────

def _documentos_do_aviso(reg: dict) -> dict:
    return destino_tf.documentos_do_aluno(reg, paths.dados_ano_atual())


def arquivo_transferidos() -> Path:
    return paths.dados_ano_atual() / destino_tf.NOME_ARQUIVO


def _carregar_transferidos() -> dict:
    """transferidos.json ({CGM: registro}). ValueError com mensagem pronta se não existe ou está ilegível."""
    caminho = arquivo_transferidos()
    if not caminho.exists():
        raise ValueError(f"Ainda não existe {caminho.name}: rode a coleta de turmas (ela monta a fila de transferidos).")
    try:
        return carregar_json(caminho, dict, dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(str(exc)) from exc


def _quem_saiu(cgm: str, reg: dict) -> str:
    return f"{_uma_linha(reg.get('nome')) or 'CGM ' + cgm} ({_uma_linha(reg.get('turma')) or 'sem turma'})"


def listar_transferidos_para_aviso() -> list[dict]:
    """
    Os transferidos que ainda estão fora da escola, com o destino resolvido, para a tela e a prévia:
    [{id (CGM), nome, turma, escola_destino, fonte, status_aviso, consulta, documentos_faltando}], por nome.
    """
    saida = []
    for cgm, reg in _carregar_transferidos().items():
        if not isinstance(reg, dict) or reg.get("retorno"):
            continue
        d = destino_tf.resolver_destino(reg)
        faltando = _documentos_do_aviso(reg)["faltando"]
        estado, selo = _estado_do_transferido(d, faltando)
        saida.append({"id": str(cgm), "nome": _uma_linha(reg.get("nome")), "turma": _uma_linha(reg.get("turma")),
                      "escola_destino": d["escola"], "fonte": d["fonte"], "status_aviso": d["status_aviso"],
                      "consulta": d["consulta"], "documentos_faltando": faltando, "estado": estado, "selo": selo})
    return sorted(saida, key=lambda x: _sem_acento(x["nome"]))


def _estado_do_transferido(d: dict, faltando: list[str]) -> tuple[str, str]:
    """("ok" | "verificar" | "sem_vinculo" | "dispensado", texto do selo) de um transferido, para o seletor da tela."""
    if d["status_aviso"] == "encaminhado":
        return "dispensado", "encaminhado por e-mail à parte (não recebe pelo sistema)"
    if d["status_aviso"] == "nao_avisar":
        return "dispensado", "marcado para não avisar automaticamente"
    if not d["escola"]:
        if d["consulta"] == "verificar":
            return "verificar", "vínculo da Base ABC a verificar" + (f": {d['motivo']}" if d["motivo"] else "")
        return "sem_vinculo", "sem escola de destino (rode a Consulta na Base ABC ou preencha na tela de Transferidos)"
    origem = "preenchido à mão" if d["fonte"] == "manual" else "Base ABC"
    if faltando:
        return "verificar", f"{d['escola']} ({origem}) · faltam documentos: " + "; ".join(faltando)
    return "ok", f"{d['escola']} ({origem}) · guia, histórico e parecer prontos"


def avisos_ja_enviados_ao_destino() -> dict:
    """
    Do que já saiu de verdade para escolas de destino: {(CGM, data da saída): {...}} e, quando o envio guardou o ID da
    matrícula, também {("id", ID): {...}} (o ID resiste a uma data corrigida no SERE). {} se o registro estiver ilegível.
    """
    try:
        enviados = carregar_enviados()
    except ValueError:
        return {}
    saida = {}
    for e in enviados.values():
        if isinstance(e, dict) and e.get("cgm"):
            dados = {"enviado_em": e.get("enviado_em"), "para": e.get("para"), "nome": e.get("nome")}
            saida[(str(e["cgm"]), str(e.get("data_saida") or ""))] = dados
            if e.get("id_matricula"):
                saida[("id", str(e["id_matricula"]))] = dados
    return saida


def destinatarios_destino_transferidos(tipo: str = "todas", filtro_nome: str = "", unidades=None, alunos=None) -> dict:
    """
    Um destinatário POR ALUNO transferido: a escola de destino dele, com o e-mail da lista coletada (o primeiro, se a escola
    tem mais de um) e os 3 documentos da saída atual em `anexos`.

    Devolve {"destinatarios", "sem_email", "alunos", "sem_destino", "a_verificar", "destino_fora_da_lista", "encaminhados",
    "nao_avisar", "sem_documentos", "fora_da_selecao"}. Só recebe quem fecha TUDO; o resto vai numa dessas listas e NÃO recebe
    e-mail, para ninguém avisar a escola errada nem mandar a saída errada. Quem voltou à escola nem entra na contagem.
    `alunos` = CGMs marcados (nenhum = todos); `unidades`/`tipo`/`filtro_nome` filtram pela escola de DESTINO.
    """
    escolhidas = normalizar_unidades(unidades)
    marcados = set(_itens_unidades(alunos)) or None
    filtro = _sem_acento(filtro_nome).strip()
    propria = escola.nome()
    lista = [{"nome": _uma_linha(e.get("nome")), "eh_cmei": _eh_cmei(e), "emails": extrair_emails(e.get("email"))}
             for e in carregar_escolas() if _uma_linha(e.get("nome"))]
    r = {"destinatarios": [], "sem_email": [], "alunos": 0, "sem_destino": [], "a_verificar": [], "destino_fora_da_lista": [],
         "encaminhados": [], "nao_avisar": [], "sem_documentos": [], "fora_da_selecao": 0}
    for cgm, reg in sorted(_carregar_transferidos().items(), key=lambda kv: _sem_acento(str((kv[1] or {}).get("nome") if isinstance(kv[1], dict) else ""))):
        if not isinstance(reg, dict) or reg.get("retorno"):
            continue
        cgm = str(cgm)
        if marcados and cgm not in marcados:
            continue
        r["alunos"] += 1
        quem = _quem_saiu(cgm, reg)
        d = destino_tf.resolver_destino(reg)
        if d["status_aviso"] == "encaminhado":
            r["encaminhados"].append(quem)
            continue
        if d["status_aviso"] == "nao_avisar":
            r["nao_avisar"].append(quem)
            continue
        if not d["escola"]:
            if d["consulta"] == "verificar":
                r["a_verificar"].append(f"{quem} — {d['motivo'] or 'vínculo incompleto'}")
            else:
                r["sem_destino"].append(quem)
            continue
        if propria and _e_a_propria_escola(d["escola"], propria):       # o vínculo aponta para a NOSSA escola: não é destino
            r["a_verificar"].append(f"{quem} — o vínculo aponta para a nossa própria escola ({d['escola']}); preencha o destino à mão")
            continue
        un = _achar_unidade(d["escola"], lista)
        if un is None:
            r["destino_fora_da_lista"].append(f"{quem} — {d['escola']}")
            continue
        if ((tipo == "cmeis" and not un["eh_cmei"]) or (tipo == "escolas" and un["eh_cmei"])
                or (filtro and filtro not in _sem_acento(un["nome"]))
                or not _unidade_escolhida(un["nome"], un["eh_cmei"], escolhidas)):
            r["fora_da_selecao"] += 1
            continue
        if not un["emails"]:
            r["sem_email"].append(f"{un['nome']} (aluno {_uma_linha(reg.get('nome'))})")
            continue
        docs = _documentos_do_aviso(reg)
        if docs["faltando"]:
            r["sem_documentos"].append(f"{quem} — " + "; ".join(docs["faltando"]))
            continue
        r["destinatarios"].append({
            "nome": un["nome"], "email": un["emails"][0], "cgm": cgm, "id_matricula": str(reg.get("id_matricula") or ""),
            "anexos": [str(docs["guia"]), str(docs["historico"]), str(docs["parecer"])],
            "contexto": {"ESCOLA_DESTINO": un["nome"], "ALUNO": _uma_linha(reg.get("nome")), "CGM": cgm,
                         "TURMA": _uma_linha(reg.get("turma")), "DATA_SAIDA": _uma_linha(reg.get("data_transferencia"))}})
    return r


# ───────────────────────────── texto: marcadores ─────────────────────────────

def marcadores_validos(publico: str) -> tuple[str, ...]:
    """Marcadores que valem para o público. Público em branco (modelo para qualquer público) = os dos dois."""
    if not publico:
        return tuple(dict.fromkeys(MARCADORES["comuns"] + MARCADORES["escolas"] + MARCADORES["pais"] + MARCADORES["destino"]))
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


def _marcadores_de_aluno(texto: str) -> set:
    return {m for m in _RE_MARCADOR.findall(texto or "") if m in MARCADORES_DE_ALUNO}


def _inteiro_entre(valor, minimo: int, maximo: int, padrao: int, nome: str) -> int:
    try:
        n = int(str(valor).strip()) if str(valor if valor is not None else "").strip() else padrao
    except ValueError as exc:
        raise ValueError(f"{nome}: use um número inteiro.") from exc
    if not minimo <= n <= maximo:
        raise ValueError(f"{nome}: use um valor de {minimo} a {maximo}.")
    return n


def validar_pedido(publico, canal, modo, assunto, mensagem, tipo_escola="todas", filtro_nome="",
                   situacao_pais="matriculados", email_teste="", unidades=None, fonte="ano",
                   intervalo_s=INTERVALO_PADRAO_S, limite_lote=LOTE_PADRAO, alunos=None) -> dict:
    """Confere TUDO antes de qualquer envio. ValueError com mensagem pronta; devolve os parâmetros já normalizados."""
    publico, canal, modo = str(publico or ""), str(canal or "email"), str(modo or "simular")
    if publico not in PUBLICOS:
        raise ValueError("Escolha para quem é o comunicado (escolas, pais ou escola de destino dos transferidos).")
    if canal not in CANAIS:
        raise ValueError(f"Canal '{canal}' ainda não existe. Por enquanto só: " + ", ".join(CANAIS) + ".")
    if modo not in MODOS:
        raise ValueError("Modo inválido: use 'simular', 'teste' ou 'enviar'.")
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
    if publico in ("escolas", "destino") and str(tipo_escola or "todas") not in TIPOS_ESCOLA:
        raise ValueError("Tipo de escola inválido: use todas, escolas ou cmeis.")
    if str(situacao_pais or "matriculados") not in SITUACOES_PAIS:
        raise ValueError("Situação inválida: use matriculados, aguardando ou ambos.")
    if str(fonte or "ano") not in FONTES_ALUNOS:
        raise ValueError("Fonte dos alunos novos inválida: use ano, proximo ou ambas.")
    normalizar_unidades(unidades)                   # recusa grupo desconhecido
    if "ESCOLA" in set(_RE_MARCADOR.findall(assunto)) | set(_RE_MARCADOR.findall(mensagem)) and not escola.nome():
        raise ValueError("O texto usa $ESCOLA, mas o nome da escola ainda não foi informado (Configurações → Dados da escola).")
    por_aluno = publico == "destino" or (publico == "escolas" and bool(_marcadores_de_aluno(assunto + " " + mensagem)))
    intervalo = _inteiro_entre(intervalo_s, INTERVALO_MIN_S, INTERVALO_MAX_S, INTERVALO_PADRAO_S, "Intervalo entre e-mails (segundos)")
    lote = _inteiro_entre(limite_lote, LOTE_MIN, LOTE_MAX, LOTE_PADRAO, "Máximo de e-mails por execução")
    email_teste = str(email_teste or "").strip().lower()
    if modo in ("teste", "enviar") and not _credenciais_email_ok():
        raise ValueError(("Para o modo teste" if modo == "teste" else "Para enviar")
                         + ", salve o e-mail e a senha de app do Gmail em Configurações → Senha do Gmail.")
    if modo == "teste":
        padrao = ESCOLA_TESTE["email"] if publico in ("escolas", "destino") else str(credenciais.EMAIL_REMETENTE).strip()
        email_teste = email_teste or padrao.lower()
        if not email_valido(email_teste):
            raise ValueError("O e-mail de teste não parece um endereço válido.")
    return {"publico": publico, "canal": canal, "modo": modo, "assunto": assunto, "mensagem": mensagem,
            "tipo_escola": str(tipo_escola or "todas"), "filtro_nome": str(filtro_nome or "").strip(),
            "situacao_pais": str(situacao_pais or "matriculados"), "email_teste": email_teste,
            "unidades": _itens_unidades(unidades), "fonte": str(fonte or "ano"), "por_aluno": por_aluno,
            "alunos": _itens_unidades(alunos),
            "intervalo_s": intervalo, "limite_lote": lote}


def teste_com_escola_ficticia(publico: str, modo: str) -> bool:
    """No modo teste das escolas o e-mail vai para a escola fictícia; a lista real é opcional."""
    return modo == "teste" and publico in ("escolas", "destino")


def _por_que_nao_ha_alunos(r: dict) -> str:
    partes = []
    for chave, texto in (("sem_vinculo", "sem o vínculo da Base ABC (rode a 'Consulta na Base ABC' com a pré-matrícula)"),
                         ("a_verificar", "com o vínculo da Base ABC a verificar"),
                         ("origem_desconhecida", "com escola de origem que não está na lista de escolas"),
                         ("da_propria_escola", "que já estão na nossa escola e sem escola anterior no vínculo (se acabaram de entrar, "
                                               "refaça a Consulta na Base ABC para trazer a escola anterior)"),
                         ("sem_email", "cuja escola de origem está sem e-mail")):
        if r.get(chave):
            partes.append(f"{len(r[chave])} {texto}")
    if r.get("fora_da_selecao"):
        partes.append(f"{r['fora_da_selecao']} fora das unidades escolhidas")
    motivo = ("Nenhum aluno novo com escola de origem e e-mail para este pedido"
              + (f" ({r['alunos']} aluno(s) novo(s) lido(s)" + (": " + "; ".join(partes) if partes else "") + ")" if r.get("alunos") else "")
              + ".")
    return motivo


def _por_que_nao_ha_transferidos(r: dict) -> str:
    partes = []
    for chave, texto in (("sem_destino", "sem escola de destino (rode a 'Consulta na Base ABC' com os transferidos ou preencha o destino na tela de Transferidos)"),
                         ("a_verificar", "com o vínculo da Base ABC a verificar"),
                         ("destino_fora_da_lista", "com destino fora da lista de escolas (marque como encaminhado à parte, se for o caso)"),
                         ("encaminhados", "marcados como encaminhados por e-mail à parte"),
                         ("nao_avisar", "marcados para não avisar automaticamente"),
                         ("sem_email", "cuja escola de destino está sem e-mail"),
                         ("sem_documentos", "sem os três documentos (guia, histórico e parecer) desta saída")):
        if r.get(chave):
            partes.append(f"{len(r[chave])} {texto}")
    if r.get("fora_da_selecao"):
        partes.append(f"{r['fora_da_selecao']} fora das unidades escolhidas")
    return ("Nenhum transferido com escola de destino, e-mail e documentos para este pedido"
            + (f" ({r['alunos']} transferido(s) lido(s)" + (": " + "; ".join(partes) if partes else "") + ")" if r.get("alunos") else "") + ".")


def reunir_destinatarios(publico: str, tipo_escola="todas", filtro_nome="", situacao_pais="matriculados",
                         unidades=None, fonte="ano", por_aluno=False, alunos=None) -> dict:
    if publico == "destino":
        r = destinatarios_destino_transferidos(tipo_escola, filtro_nome, unidades, alunos)
        if not r["destinatarios"]:
            raise ValueError(_por_que_nao_ha_transferidos(r))
        return r
    if publico == "escolas" and por_aluno:
        r = destinatarios_alunos_origem(situacao_pais, fonte, tipo_escola, filtro_nome, unidades, alunos)
        if not r["destinatarios"]:
            raise ValueError(_por_que_nao_ha_alunos(r))
        return r
    if publico == "escolas":
        r = destinatarios_escolas(tipo_escola, filtro_nome, unidades)
    else:
        r = destinatarios_pais(situacao_pais, fonte, alunos)
    if not r["destinatarios"]:
        raise ValueError("Nenhum destinatário com e-mail válido para este público e estes filtros.")
    return r


def exemplo_da_mensagem(publico, assunto, mensagem, tipo_escola="todas", filtro_nome="", situacao_pais="matriculados",
                        unidades=None, fonte="ano", alunos=None) -> dict:
    """
    Como o texto fica para o PRIMEIRO destinatário (ou aluno marcado), para a tela mostrar ao vivo. Nunca levanta:
    {"vazio": True} sem texto; {"aviso": ...} se não dá para montar; senão {para, nome, assunto, corpo, aluno, total} (+ "aviso"
    quando o aluno aparece mas não receberia o e-mail, ex.: sem vínculo ou escola de origem fora da lista).
    """
    assunto, mensagem = str(assunto or "").strip(), str(mensagem or "").strip()
    if publico not in PUBLICOS or not (assunto or mensagem):
        return {"vazio": True}
    try:
        conferir_marcadores(assunto, publico, "Assunto")
        conferir_marcadores(mensagem, publico, "Mensagem")
        por_aluno = publico == "destino" or (publico == "escolas" and bool(_marcadores_de_aluno(assunto + " " + mensagem)))
    except ValueError as exc:
        return {"aviso": str(exc)}
    try:
        r = reunir_destinatarios(publico, tipo_escola or "todas", filtro_nome or "", situacao_pais or "matriculados",
                                 unidades, fonte or "ano", por_aluno, alunos)
        m = montar_mensagens(r["destinatarios"][:1], assunto, mensagem, por_aluno)[0]
        return {"para": m["para"], "nome": m["nome"], "assunto": m["assunto"], "corpo": m["corpo"], "aluno": m.get("aluno", ""),
                "total": len(r["destinatarios"])}
    except ValueError as exc:
        aviso = str(exc)
    if por_aluno and publico == "destino":
        try:
            marcados = set(_itens_unidades(alunos))
            lista = [a for a in listar_transferidos_para_aviso() if not marcados or a["id"] in marcados]
        except ValueError:
            lista = []
        if lista:
            a = lista[0]
            contexto = {"ESCOLA_DESTINO": a["escola_destino"] or "(escola de destino)", "ALUNO": a["nome"], "CGM": a["id"],
                        "TURMA": a["turma"], "DATA_SAIDA": ""}
            m = montar_mensagens([{"nome": contexto["ESCOLA_DESTINO"], "email": "(sem e-mail)", "contexto": contexto}],
                                 assunto, mensagem, True)[0]
            return {"para": "", "nome": m["nome"], "assunto": m["assunto"], "corpo": m["corpo"], "aluno": a["nome"], "total": 0,
                    "aviso": aviso}
    if por_aluno:                       # ninguém receberia, mas o texto ainda dá para ver com os dados do primeiro aluno
        try:
            marcados = set(_itens_unidades(alunos))
            lista = [a for a in listar_alunos_novos(situacao_pais or "matriculados", fonte or "ano") if not marcados or a["id"] in marcados]
        except ValueError:
            lista = []
        if lista:
            a = lista[0]
            contexto = {"ESCOLA_DESTINO": a["escola_origem"] or "(escola de origem)", "ALUNO": a["nome"],
                        "CGM": a["cgm"] or "(sem CGM)", "SERIE": a["serie"], "TURMA": a["turma"]}
            m = montar_mensagens([{"nome": a["escola_origem"] or "(escola de origem)", "email": "(sem e-mail)", "contexto": contexto}],
                                 assunto, mensagem, True)[0]
            return {"para": "", "nome": m["nome"], "assunto": m["assunto"], "corpo": m["corpo"], "aluno": a["nome"], "total": 0,
                    "aviso": aviso}
    return {"aviso": aviso}


def _chave_estavel(d: dict, assunto: str, mensagem: str) -> str:
    """Identifica 'este texto para este destinatário' sem depender do $DATA: serve para não enviar duas vezes."""
    base = json.dumps([d["email"], assunto, mensagem, sorted((k, _uma_linha(v)) for k, v in d["contexto"].items())],
                      ensure_ascii=False)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def montar_mensagens(destinatarios: list[dict], assunto: str, mensagem: str, por_aluno: bool = False) -> list[dict]:
    base = _contexto_base()
    mensagens = []
    for d in destinatarios:
        ctx = {**base, **{k: _uma_linha(v) for k, v in d["contexto"].items()}}
        m = {"para": d["email"], "nome": d["nome"], "assunto": renderizar(assunto, ctx), "corpo": renderizar(mensagem, ctx),
             "chave": _chave_estavel(d, assunto, mensagem)}
        if por_aluno:
            m["aluno"] = ctx.get("ALUNO", "")
        if d.get("anexos"):
            m["anexos"] = list(d["anexos"])
        if d.get("cgm"):
            m["cgm"] = str(d["cgm"])
            m["data_saida"] = ctx.get("DATA_SAIDA", "")           # CGM + data separam a 1ª da 2ª saída do mesmo aluno
            if d.get("id_matricula"):
                m["id_matricula"] = str(d["id_matricula"])        # e o ID da saída, quando a ponte já deu um
        mensagens.append(m)
    return mensagens


def pasta_avisos() -> Path:
    return paths.dados_ano_atual() / "AVISOS"


def _gravar_registro(publico: str, modo: str, dados: dict, caminho: Optional[Path] = None) -> Path:
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = caminho or pasta_avisos() / f"{carimbo}_{publico}_{modo}.json"
    salvar_json_atomico(caminho, dados, indent=2)
    return caminho


# ───────────────────────────── prévia obrigatória e registro de quem já recebeu ─────────────────────────────

def _arquivo_previas() -> Path:
    return pasta_avisos() / "previas.json"


def _arquivo_enviados() -> Path:
    return pasta_avisos() / "enviados.json"


def hash_da_previa(mensagens: list[dict]) -> str:
    """Impressão digital de 'quem receberia o quê' (pelas chaves estáveis): muda se o texto ou a lista mudar."""
    return hashlib.sha256("\n".join(sorted(m["chave"] for m in mensagens)).encode("utf-8")).hexdigest()


def _carregar_dict(caminho: Path, rotulo: str) -> dict:
    if not caminho.exists():
        return {}
    try:
        return carregar_json(caminho, dict, dict)
    except ArquivoJsonCorrompidoError as exc:
        raise ValueError(f"{rotulo}: {exc}") from exc


def registrar_previa(mensagens: list[dict]) -> None:
    """A simulação grava a impressão digital; o envio real só libera se achar uma de até VALIDADE_PREVIA_HORAS."""
    dados = _carregar_dict(_arquivo_previas(), "Registro de prévias")
    limite = datetime.now() - timedelta(days=7)
    previas = {h: t for h, t in (dados.get("previas") or {}).items() if _data_ou_none(t) and _data_ou_none(t) >= limite}
    previas[hash_da_previa(mensagens)] = datetime.now().isoformat(timespec="seconds")
    salvar_json_atomico(_arquivo_previas(), {"previas": previas}, indent=2)


def _data_ou_none(texto) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(texto))
    except ValueError:
        return None


def conferir_previa(mensagens: list[dict]) -> None:
    """ValueError se este envio não passou antes pela simulação (mesmo texto, mesmos destinatários, até 24 h antes)."""
    feita = _data_ou_none((_carregar_dict(_arquivo_previas(), "Registro de prévias").get("previas") or {}).get(hash_da_previa(mensagens)))
    if feita is None or datetime.now() - feita > timedelta(hours=VALIDADE_PREVIA_HORAS):
        raise ValueError(
            "Antes de enviar de verdade, rode o modo \"Simular\" com este mesmo texto e os mesmos destinatários e confira a "
            f"prévia (vale por {VALIDADE_PREVIA_HORAS} horas). Se você mudou o texto, as unidades ou a lista de alunos desde a "
            "última simulação, simule de novo.")


def carregar_enviados() -> dict:
    """{chave: {para, nome, assunto, enviado_em}} de tudo que já foi enviado de verdade (nunca é apagado pelo sistema)."""
    return dict(_carregar_dict(_arquivo_enviados(), "Registro de envios").get("envios") or {})


def listar_enviados() -> dict:
    """
    O que já saiu de verdade (AVISOS/enviados.json), do mais recente para o mais antigo, para a tela "Quem já recebeu".
    Só lê: nada aqui altera ou apaga o registro. Devolve {"total", "envios": [{"para","nome","aluno","cgm","assunto",
    "enviado_em","publico","anexos"}], "por_publico": {publico: n}}. Registros gravados antes de o público ser guardado
    ficam com publico "" (só o de escola de destino se reconhece, por ter CGM + data da saída).
    """
    envios = []
    for chave, v in carregar_enviados().items():
        if not isinstance(v, dict):
            continue
        publico = str(v.get("publico") or ("destino" if v.get("data_saida") and v.get("cgm") else ""))
        envios.append({"para": str(v.get("para") or ""), "nome": str(v.get("nome") or ""), "aluno": str(v.get("aluno") or ""),
                       "cgm": str(v.get("cgm") or ""), "assunto": str(v.get("assunto") or ""),
                       "enviado_em": str(v.get("enviado_em") or ""), "publico": publico,
                       "anexos": [str(a) for a in (v.get("anexos") or [])]})
    envios.sort(key=lambda e: e["enviado_em"], reverse=True)
    por_publico: dict[str, int] = {}
    for e in envios:
        por_publico[e["publico"]] = por_publico.get(e["publico"], 0) + 1
    return {"total": len(envios), "envios": envios, "por_publico": por_publico}


def _esperar(segundos: float) -> None:
    """Pausa entre e-mails, conferindo o botão Cancelar a cada segundo."""
    fim = time.monotonic() + segundos
    while True:
        verificar_cancelamento()
        resto = fim - time.monotonic()
        if resto <= 0:
            return
        time.sleep(min(1.0, resto))


def _enviar_real(p: dict, mensagens: list[dict], base_registro: dict) -> dict:
    """
    Envia de verdade, um a um, com pausa entre eles e no máximo `limite_lote` por execução. Quem já recebeu este mesmo
    texto não recebe de novo (rodar outra vez continua de onde parou). O registro é regravado a cada e-mail, então
    cancelar (ou cair) no meio não perde nada. Devolve {"enviados","falhas","ja_enviados","restantes","registro"}.
    """
    from src.automacao.envia_email import enviar_email
    enviados_antes = carregar_enviados()
    ja = [m for m in mensagens if m["chave"] in enviados_antes]
    pendentes = [m for m in mensagens if m["chave"] not in enviados_antes]
    lote, restantes = pendentes[:p["limite_lote"]], pendentes[p["limite_lote"]:]
    print(f"\nENVIO REAL: {len(lote)} e-mail(s) agora, com {p['intervalo_s']} s entre um e outro."
          + (f" Já enviados antes (não repetem): {len(ja)}." if ja else "")
          + (f" Ficam para a próxima execução: {len(restantes)} (limite de {p['limite_lote']} por execução)." if restantes else ""))
    enviados: list[dict] = []
    falhas: list[dict] = []
    tentados: set[str] = set()
    estado = {"estado": "em andamento"}
    caminho = _gravar_registro(p["publico"], p["modo"], {})

    def gravar() -> None:
        _gravar_registro(p["publico"], p["modo"], {
            **base_registro, **estado, "intervalo_s": p["intervalo_s"], "limite_lote": p["limite_lote"],
            "enviados": enviados, "falhas": falhas, "ja_enviados": [{"para": m["para"], "nome": m["nome"]} for m in ja],
            "restantes": [{"para": m["para"], "nome": m["nome"]}
                          for m in [*(x for x in lote if x["chave"] not in tentados), *restantes]]}, caminho)
    gravar()
    seguidas, parou_por_falhas = 0, False
    try:
        for i, m in enumerate(lote, 1):
            verificar_cancelamento()
            tentados.add(m["chave"])
            if m.get("anexos"):
                ok, erro = enviar_email(m["para"], m["assunto"], m["corpo"], anexos=m["anexos"])
            else:
                ok, erro = enviar_email(m["para"], m["assunto"], m["corpo"])
            if ok:
                seguidas = 0
                agora = datetime.now().isoformat(timespec="seconds")
                novo = {"para": m["para"], "nome": m["nome"], "assunto": m["assunto"], "enviado_em": agora,
                        "publico": p["publico"]}
                if m.get("aluno"):
                    novo["aluno"] = m["aluno"]
                if m.get("cgm"):
                    novo["cgm"] = m["cgm"]
                    novo["data_saida"] = m.get("data_saida", "")
                    if m.get("id_matricula"):
                        novo["id_matricula"] = m["id_matricula"]
                if m.get("anexos"):
                    novo["anexos"] = [Path(a).name for a in m["anexos"]]
                enviados_antes[m["chave"]] = novo
                salvar_json_atomico(_arquivo_enviados(), {"envios": enviados_antes}, indent=2)    # grava ANTES de seguir
                enviados.append(novo)
                print(f"  ✔ [{i}/{len(lote)}] {m['nome']} <{m['para']}>")
            else:
                seguidas += 1
                falhas.append({"para": m["para"], "nome": m["nome"], "erro": str(erro)})
                print(f"  ✖ [{i}/{len(lote)}] {m['nome']} <{m['para']}> — {erro}")
                if seguidas >= FALHAS_SEGUIDAS_MAX:
                    parou_por_falhas = True
                    break
            gravar()
            if i < len(lote):
                _esperar(p["intervalo_s"])
        estado["estado"] = "interrompido por falhas" if parou_por_falhas else "concluído"
    except BaseException:                                   # cancelamento ou erro inesperado: registra e deixa subir
        estado["estado"] = "interrompido"
        raise
    finally:
        gravar()
    sobra = len(restantes) + sum(1 for x in lote if x["chave"] not in tentados)
    print(f"\nEnviados: {len(enviados)} | Falhas: {len(falhas)} | Já enviados antes: {len(ja)} | Faltam: {sobra}.")
    if parou_por_falhas:
        raise RuntimeError(f"O envio parou depois de {FALHAS_SEGUIDAS_MAX} falhas seguidas (última: {falhas[-1]['erro']}). "
                           "O que já saiu ficou registrado; corrija o problema e rode de novo: quem já recebeu não recebe outra vez.")
    return {"enviados": len(enviados), "falhas": len(falhas), "ja_enviados": len(ja), "restantes": len(restantes), "registro": str(caminho)}


# ───────────────────────────── ponto de entrada ─────────────────────────────

def _rotulo_destinatario(m: dict) -> str:
    return f"{m['nome']} <{m['para']}>" + (f" — aluno {m['aluno']}" if m.get("aluno") else "")


def executar_avisos(publico, canal, modo, assunto, mensagem, tipo_escola="todas", filtro_nome="",
                    situacao_pais="matriculados", email_teste="", unidades=None, fonte="ano",
                    intervalo_s=INTERVALO_PADRAO_S, limite_lote=LOTE_PADRAO, modelo="", alunos=None) -> dict:
    """
    Monta o comunicado e, conforme o modo: só simula; envia UM e-mail de teste; ou envia de verdade (só depois de uma
    simulação do mesmo comunicado). Devolve {"modo","publico","canal","total","simulados","enviados_teste","enviados","falhas",
    "ja_enviados","restantes","sem_email","registro"}.
    """
    p = validar_pedido(publico, canal, modo, assunto, mensagem, tipo_escola, filtro_nome, situacao_pais, email_teste,
                       unidades, fonte, intervalo_s, limite_lote, alunos)
    ficticia = teste_com_escola_ficticia(p["publico"], p["modo"])
    aviso_lista = ""
    try:
        r = reunir_destinatarios(p["publico"], p["tipo_escola"], p["filtro_nome"], p["situacao_pais"],
                                 p["unidades"], p["fonte"], p["por_aluno"], p["alunos"])
    except ValueError as exc:
        if not ficticia:
            raise
        aviso_lista = str(exc)                      # o teste com a escola fictícia não depende da lista real
        r = {"destinatarios": [], "sem_email": [], "excluidas": []}
    mensagens = montar_mensagens(r["destinatarios"], p["assunto"], p["mensagem"], p["por_aluno"])
    total = len(mensagens)
    verificar_cancelamento()
    if p["modo"] == "enviar":
        conferir_previa(mensagens)                  # antes de qualquer saída: sem prévia, nada é enviado

    titulo_modo = {"simular": "SIMULAÇÃO — nada será enviado", "teste": "TESTE — só o e-mail de teste recebe",
                   "enviar": "ENVIO REAL — os destinatários recebem de verdade"}[p["modo"]]
    print(f"Comunicado oficial por e-mail | Público: {PUBLICOS[p['publico']]} | Modo: {titulo_modo}")
    print(f"{total} destinatário(s)" + ((" (um e-mail por aluno transferido, para a escola de destino, com os documentos em anexo)"
                                         if p["publico"] == "destino" else " (um e-mail por aluno que chega, para a escola de origem)")
                                        if p["por_aluno"] else "") + ":")
    for m in mensagens[:LINHAS_LISTADAS]:
        print(f"  - {_rotulo_destinatario(m)}")
    if total > LINHAS_LISTADAS:
        print(f"  … e mais {total - LINHAS_LISTADAS} (a lista completa fica no registro).")
    if r.get("excluidas"):
        print(f"Fora da lista (a própria escola): {', '.join(r['excluidas'])}")
    if r["sem_email"]:
        print(f"Sem e-mail válido ({len(r['sem_email'])}) — não receberiam: " + "; ".join(r["sem_email"][:LINHAS_LISTADAS]))
    for chave, texto in (("sem_vinculo", "Sem vínculo da Base ABC (rode a 'Consulta na Base ABC')"),
                         ("a_verificar", "Vínculo da Base ABC a verificar (não recebem)"),
                         ("origem_desconhecida", "Escola de origem fora da lista de escolas (não recebem)"),
                         ("da_propria_escola", "Já estão na nossa escola (não recebem)"),
                         ("sem_destino", "Transferidos sem escola de destino (não recebem; rode a Consulta na Base ABC ou preencha na tela de Transferidos)"),
                         ("destino_fora_da_lista", "Escola de destino fora da lista de escolas (não recebem; marque como encaminhado à parte, se for o caso)"),
                         ("encaminhados", "Marcados como encaminhados por e-mail à parte (não recebem)"),
                         ("nao_avisar", "Marcados para não avisar automaticamente (não recebem)"),
                         ("sem_documentos", "Sem guia, histórico ou parecer desta saída (não recebem)")):
        if r.get(chave):
            print(f"{texto} ({len(r[chave])}): " + "; ".join(r[chave][:LINHAS_LISTADAS]))
    if r.get("fora_da_selecao"):
        print(f"Fora das unidades escolhidas: {r['fora_da_selecao']} aluno(s).")
    if aviso_lista:
        print(f"Aviso: {aviso_lista} (o teste com a escola fictícia segue mesmo assim).")
    if p["publico"] in ("escolas", "destino") and p["modo"] == "simular":
        print(f"No modo Teste, o e-mail iria para a escola fictícia {ESCOLA_TESTE['nome']} <{ESCOLA_TESTE['email']}>.")

    if mensagens:
        amostra = mensagens[0]
        print(f"\nPRÉVIA — mensagem 1 de {total} (para {amostra['nome']})\nAssunto: {amostra['assunto']}\n\n{amostra['corpo']}\n")
        if amostra.get("anexos"):
            print("Anexos desta mensagem: " + "; ".join(Path(a).name for a in amostra["anexos"]) + "\n")

    registro_comum = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "publico": p["publico"], "canal": p["canal"],
        "modo": p["modo"], "modelo": str(modelo or ""), "assunto": p["assunto"], "mensagem": p["mensagem"], "filtros": {
            "tipo_escola": p["tipo_escola"], "filtro_nome": p["filtro_nome"], "situacao_pais": p["situacao_pais"],
            "unidades": p["unidades"], "fonte": p["fonte"], "por_aluno": p["por_aluno"], "alunos": p["alunos"]},
        "total": total, "sem_email": r["sem_email"], "excluidas": r.get("excluidas", []),
        "mensagens": [{k: ([Path(a).name for a in v] if k == "anexos" else v) for k, v in m.items() if k != "chave"}
                      for m in mensagens]}

    enviados_teste, erro, escola_teste = 0, None, None
    if p["modo"] == "teste":
        from src.automacao.envia_email import enviar_email
        if ficticia:                                # texto como a escola fictícia o receberia
            escola_teste = {"nome": ESCOLA_TESTE["nome"], "email": p["email_teste"]}
            contexto = {**(r["destinatarios"][0]["contexto"] if r["destinatarios"] and p["por_aluno"] else {}),
                        "ESCOLA_DESTINO": ESCOLA_TESTE["nome"]}
            exemplo = montar_mensagens([{**escola_teste, "contexto": contexto}], p["assunto"], p["mensagem"])[0]
            quem = f"a escola fictícia de teste: {escola_teste['nome']} <{escola_teste['email']}>"
        else:
            exemplo = mensagens[0]
            quem = f"{exemplo['nome']} <{exemplo['para']}>"
        anexos_reais = (r["destinatarios"][0].get("anexos") if r["destinatarios"] else None) or []
        faixa = (f"*** TESTE — esta mensagem NÃO foi enviada aos destinatários reais. ***\n"
                 f"O comunicado iria para {total} destinatário(s) reais. Abaixo, o texto montado para {quem}\n"
                 + (f"No envio real seguiriam em anexo: {', '.join(Path(a).name for a in anexos_reais)} "
                    "(os documentos do aluno NÃO são anexados no teste).\n" if anexos_reais else "")
                 + "-" * 60 + "\n\n")
        print(f"Enviando o e-mail de teste para {p['email_teste']}...")
        ok, erro = enviar_email(p["email_teste"], "[TESTE] " + exemplo["assunto"], faixa + exemplo["corpo"])
        if not ok:
            raise RuntimeError(f"Não consegui enviar o e-mail de teste: {erro}")
        enviados_teste = 1
        print(f"E-mail de teste enviado para {p['email_teste']}.")

    resultado_real = {"enviados": 0, "falhas": 0, "ja_enviados": 0, "restantes": 0}
    if p["modo"] == "enviar":
        resultado_real = _enviar_real(p, mensagens, registro_comum)
        registro = Path(resultado_real.pop("registro"))
    else:
        registro = _gravar_registro(p["publico"], p["modo"], {
            **registro_comum, "email_teste": p["email_teste"] if p["modo"] == "teste" else "", "escola_teste": escola_teste,
            "enviados_teste": enviados_teste})
        if p["modo"] == "simular":
            registrar_previa(mensagens)
            print("Prévia registrada: para enviar de verdade, escolha o modo \"Enviar de verdade\" com este mesmo texto e estes "
                  f"destinatários (vale por {VALIDADE_PREVIA_HORAS} horas).")
    print(f"Registro salvo em: {registro}")
    return {"modo": p["modo"], "publico": p["publico"], "canal": p["canal"], "total": total,
            "simulados": total if p["modo"] == "simular" else 0, "enviados_teste": enviados_teste, **resultado_real,
            "sem_email": r["sem_email"], "registro": str(registro)}

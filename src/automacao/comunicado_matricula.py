"""
comunicado_matricula.py — WhatsApp para o responsável a cada cadastro da pré-matrícula
=======================================================================================
Pedido do usuário: quando houver cadastro na pré-matrícula, mandar mensagem pelo WhatsApp do responsável.
Dois avisos, cada um enviado UMA vez por aluno:

  aguardando   cadastro na pré-matrícula, ainda sem vaga  → "recebemos a pré-matrícula, aguarde nosso contato"
  matriculado  matrícula aprovada                         → "Comunicado de Matrícula" (documentos, prazo, horários)

Quem estava "aguardando" e depois é aprovado recebe o segundo aviso também.

QUANDO RODA
  No fim da automação de pré-matrícula (processo completo, só pendentes e completar JSON), por
  `avisar_apos_pre_matricula()`. Também pode ser chamado à mão: `avisar_matriculados()`.

QUEM RECEBE
  Aluno com cadastro consultado e um CELULAR válido, na situação "aguardando" ou "matriculado". Nunca cancelados
  nem tentativas antigas substituídas (BUG-PRE-002). Responsável com mais de um filho na mesma situação recebe
  UMA mensagem com os nomes juntos (um envio por número e por tipo de aviso).

ONDE FICA O REGISTRO  (dentro do próprio pre_matricula.json, chave de topo "avisos_whatsapp")
    "avisos_whatsapp": {"linha_de_base_em": "...", "alunos": {"<cpf>": {
        "aguardando":  {"avisado": "SIM", "situacao": "enviado", "em": "2026-10-31T10:00:00", "numero": "55 42 *******-**11"},
        "matriculado": {"avisado": "NÃO", "situacao": "falha", "tentativas": 1, "erro": "..."}}}}
  É uma chave de topo de propósito: a coleta reescreve o registro de cada aluno e apagaria um campo guardado
  dentro dele; chaves de topo a pré-matrícula preserva.

SEGURANÇA (o WhatsApp não oficial pode banir o número, e mensagem enviada não volta)
  • Provedor SIMULADO é o padrão: nada sai do computador. Só envia de verdade com o provedor real
    configurado, conectado e WHATSAPP_ENVIO_REAL=1 (as mesmas travas do resto do sistema).
  • LINHA DE BASE: na PRIMEIRA execução ninguém é avisado — quem já está cadastrado é marcado como "linha de
    base" no aviso correspondente. Só o que acontecer depois dispara mensagem. (`incluir_existentes=True` desliga.)
  • Nunca repete: cada envio real é gravado na hora (não só no fim). Simulação NÃO registra, para não bloquear o
    envio real depois.
  • Falha incerta ("pode ou não ter saído") e "número sem WhatsApp" não são repetidas sozinhas (sem WhatsApp
    tenta de novo se o telefone do cadastro mudar). Falha comum é tentada de novo, até 3 vezes.
  • Limite de mensagens por execução (padrão 30) e pausa entre envios; o resto fica para a próxima.
  • WhatsApp desconectado ou envio real bloqueado: para na hora, sem gravar nada.
  • O texto das mensagens não vai para log nem para registro; números só aparecem mascarados.

AJUSTES (opcionais) em config/config_usuario.json, chave "comunicado_matricula":
    {"ativo": true, "avisar_aguardando": true, "escriturario": "Claudio", "dias_prazo": 8, "limite_por_execucao": 30,
     "link_grupo": "https://chat.whatsapp.com/...",              ← grupo geral (usado quando a turma não tem o seu)
     "links_turmas": {"Infantil IV": "https://chat.whatsapp.com/...", "1º Ano": "https://chat.whatsapp.com/..."}}
  Nome da turma = como aparece na pré-matrícula (sem " do Ensino Fundamental"; acento e maiúscula não importam).
  Os textos podem ser trocados criando config/comunicado_matricula.txt e config/comunicado_aguardando.txt
  (marcadores: ver MARCADORES).
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from src.automacao import avisos
from src.comum import configuracao, escola, paths
from src.comum.arquivos_json import carregar_json, salvar_json_atomico
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.logger import get_logger
from src.servicos.whatsapp.base import (EnvioNaoAutorizadoError, ResultadoEnvio, mascarar_numero,
                                        normalizar_numero)

log = get_logger(__file__)

TIPOS = ("matriculado", "aguardando")           # ordem de envio: quem foi aprovado vem primeiro
TENTATIVAS_MAXIMAS = 3
PAUSA_ENTRE_ENVIOS_S = 3.0
AJUSTES_PADRAO: dict[str, Any] = {
    "ativo": True,
    "avisar_aguardando": True,
    "escriturario": "Claudio",
    "link_grupo": "https://chat.whatsapp.com/DgVKHb1JnvI0STymAK4cIn",
    "links_turmas": {},
    "dias_prazo": 8,
    "limite_por_execucao": 30,
}
MARCADORES = ("ALUNO", "ANO", "INICIO", "FIM", "FIM_CURTA", "ESCRITURARIO", "ESCOLA_CURTA", "LINK_GRUPO")

MODELO_MATRICULADO = """🌟 Olá, tudo bem?
Me chamo $ESCRITURARIO, sou escriturário da $ESCOLA_CURTA.

Estou entrando em contato para informar que a matrícula de $ALUNO para o ano letivo de $ANO foi aprovada em nossa escola. ✅

Pedimos, por gentileza, que o responsável compareça à secretaria para confirmar a matrícula.

📅 Período para comparecimento:
De $INICIO a $FIM

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

🛑 Prazo final: $FIM_CURTA
Se não puder comparecer, orientamos que agende um horário.
O não comparecimento implicará no cancelamento da vaga.

🏫 Horário escolar

🚪 Abertura dos portões: 07h30 às 07h45
📚 Início das aulas: 07h45
⏰ Saída:
* 16h00 (segunda a quinta)
* 11h30 (sexta-feira – regime parcial)

📲 Link do grupo oficial da turma no WhatsApp:
$LINK_GRUPO

Desde já, agradecemos pela atenção. 🙏

Atenciosamente,
$ESCRITURARIO
Escriturário – $ESCOLA_CURTA"""

# RASCUNHO escrito por mim (o usuário só enviou o texto de matrícula aprovada): revisar antes de usar de verdade,
# ou trocar criando config/comunicado_aguardando.txt.
MODELO_AGUARDANDO = """🌟 Olá, tudo bem?
Me chamo $ESCRITURARIO, sou escriturário da $ESCOLA_CURTA.

Recebemos a pré-matrícula de $ALUNO para o ano letivo de $ANO. ✅

No momento, a pré-matrícula está aguardando vaga. Assim que houver uma vaga disponível, entraremos em contato por este mesmo número para informar como será feita a matrícula.

📌 Por enquanto, não é necessário comparecer à escola. Pedimos que aguarde o nosso contato.

Desde já, agradecemos pela atenção. 🙏

Atenciosamente,
$ESCRITURARIO
Escriturário – $ESCOLA_CURTA"""

_MODELOS = {"matriculado": MODELO_MATRICULADO, "aguardando": MODELO_AGUARDANDO}
_ARQUIVOS_TEXTO = {"matriculado": "comunicado_matricula.txt", "aguardando": "comunicado_aguardando.txt"}

_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")
_RE_MARCADOR = re.compile(r"\$([A-Z][A-Z_]*)")
_RE_TELEFONE = re.compile(r"(?:\+?55\s*)?\(?\d{2}\)?[\s.\-]*9?\d{4}[\s.\-]?\d{4}")
_MINUSCULAS = {"de", "da", "do", "das", "dos", "e"}
_BLOQUEIAM = {"enviado", "linha_de_base", "incerto"}


# ───────────────────────────── ajustes e texto ─────────────────────────────

def _link_valido(valor, onde: str) -> str:
    v = str(valor or "").strip()
    if not v.lower().startswith("https://"):
        raise ValueError(f"config_usuario.json: {onde} precisa ser um link começando com https://")
    return v


def ajustes() -> dict[str, Any]:
    """Padrões + o que estiver em config_usuario.json → comunicado_matricula. ValueError se algo estiver errado."""
    bruto = configuracao.carregar_configuracao().get("comunicado_matricula") or {}
    if not isinstance(bruto, dict):
        raise ValueError("config_usuario.json: 'comunicado_matricula' precisa ser um objeto {...}.")
    r = {**AJUSTES_PADRAO, **bruto}
    for chave, minimo, maximo in (("dias_prazo", 1, 60), ("limite_por_execucao", 1, 200)):
        v = r[chave]
        if isinstance(v, bool) or not isinstance(v, int) or not minimo <= v <= maximo:
            raise ValueError(f"config_usuario.json: comunicado_matricula.{chave} deve ser um número inteiro de {minimo} a {maximo}.")
    if not str(r["escriturario"] or "").strip():
        raise ValueError("config_usuario.json: comunicado_matricula.escriturario não pode ficar vazio.")
    r["link_grupo"] = _link_valido(r["link_grupo"], "comunicado_matricula.link_grupo")
    if not isinstance(r["links_turmas"], dict):
        raise ValueError("config_usuario.json: comunicado_matricula.links_turmas precisa ser {\"turma\": \"link\", ...}.")
    r["links_turmas"] = {chave_turma(t): _link_valido(l, f"comunicado_matricula.links_turmas[{t!r}]")
                         for t, l in r["links_turmas"].items()}
    r["ativo"], r["avisar_aguardando"] = bool(r["ativo"]), bool(r["avisar_aguardando"])
    return r


def modelo(tipo: str = "matriculado") -> str:
    """Texto padrão do aviso, ou o arquivo em config/ se existir. ValueError com marcador desconhecido."""
    arquivo = configuracao.CONFIG_DIR / _ARQUIVOS_TEXTO[tipo]
    texto = arquivo.read_text(encoding="utf-8").strip() if arquivo.exists() else _MODELOS[tipo]
    if not texto:
        raise ValueError(f"{arquivo} está vazio.")
    desconhecidos = sorted({m for m in _RE_MARCADOR.findall(texto) if m not in MARCADORES})
    if desconhecidos:
        raise ValueError("Texto do comunicado: marcador(es) desconhecido(s) " + ", ".join("$" + m for m in desconhecidos)
                         + ". Os que valem: " + ", ".join("$" + m for m in MARCADORES) + ".")
    return texto


def data_longa(d: date) -> str:
    """'31 de outubro de 2026' (sem depender do idioma instalado no Windows)."""
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def _uma_linha(valor) -> str:
    return " ".join(str(valor or "").split())


def chave_turma(nome) -> str:
    """'1º Ano do Ensino Fundamental' e '1º ano' dão a mesma chave (sem acento, maiúscula nem sufixo)."""
    t = avisos._sem_acento(_uma_linha(nome)).lower()
    return t.removesuffix(" do ensino fundamental").strip()


def link_da_turma(turma, cfg: dict) -> str:
    """Link do grupo da turma; se ela não tiver o seu, o grupo geral."""
    return cfg["links_turmas"].get(chave_turma(turma)) or cfg["link_grupo"]


def _texto_link(turmas: list[str], cfg: dict) -> str:
    """Um link só quando todos os filhos caem no mesmo grupo; senão uma linha 'Turma: link' por turma."""
    pares = list(dict.fromkeys((t, link_da_turma(t, cfg)) for t in turmas if t)) or [("", cfg["link_grupo"])]
    if len({l for _, l in pares}) == 1:
        return pares[0][1]
    return "\n".join(f"{t}: {l}" for t, l in pares)


def nome_proprio(nome) -> str:
    """'MARIA DA SILVA' → 'Maria da Silva' (a pré-matrícula grava tudo em maiúsculas)."""
    palavras = _uma_linha(nome).lower().split()
    return " ".join(p if i and p in _MINUSCULAS else p.capitalize() for i, p in enumerate(palavras))


def _juntar_nomes(nomes: list[str]) -> str:
    nomes = list(dict.fromkeys(n for n in nomes if n))
    if len(nomes) <= 1:
        return nomes[0] if nomes else ""
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _escola_curta() -> str:
    d = escola.carregar()
    base = (d["nome_abreviado"] or d["nome"]).title().strip()
    if not base:
        return "Escola"
    return base if base.lower().startswith(("escola", "cmei", "colégio", "colegio")) else f"Escola {base}"


def montar_mensagem(nomes_alunos: list[str], hoje: date, cfg: Optional[dict] = None, texto: Optional[str] = None,
                    turmas: Optional[list[str]] = None, tipo: str = "matriculado") -> str:
    """Prazo = data do envio + dias_prazo (como no modelo HTML, que usa a data em que a página é aberta)."""
    cfg = cfg or ajustes()
    fim = hoje + timedelta(days=cfg["dias_prazo"])
    ctx = {"ALUNO": _juntar_nomes([nome_proprio(n) for n in nomes_alunos]) or "seu(sua) filho(a)",
           "ANO": str(paths.ano_atual()), "INICIO": data_longa(hoje), "FIM": data_longa(fim),
           "FIM_CURTA": fim.strftime("%d/%m/%Y"), "ESCRITURARIO": cfg["escriturario"].strip(),
           "ESCOLA_CURTA": _escola_curta(), "LINK_GRUPO": _texto_link(turmas or [], cfg)}
    return avisos.renderizar(texto if texto is not None else modelo(tipo), ctx)


# ───────────────────────────── telefone ─────────────────────────────

def pode_ter_whatsapp(numero: str) -> bool:
    """Celular (9 dígitos começando em 9, ou o antigo de 8 começando em 6-9). Fixo não tem WhatsApp."""
    local = numero[4:]
    return (len(local) == 9 and local[0] == "9") or (len(local) == 8 and local[0] in "6789")


def extrair_numero(texto) -> Optional[str]:
    """Primeiro celular válido do campo telefone do cadastro (que pode trazer mais de um número), já com 55."""
    t = str(texto or "")
    for candidato in [t, *_RE_TELEFONE.findall(t)]:
        try:
            n = normalizar_numero(candidato)
        except ValueError:
            continue
        if pode_ter_whatsapp(n):
            return n
    return None


def _id_numero(numero: str) -> str:
    return hashlib.sha256(numero.encode()).hexdigest()[:10]


# ───────────────────────────── quem recebe ─────────────────────────────

def alunos_elegiveis() -> dict[str, dict]:
    """
    {chave: {nome, turma, responsavel, numero, tipo, tem_cadastro}} dos alunos 'matriculado' ou 'aguardando'
    (tipo = qual aviso lhe cabe; numero None = sem celular válido). Chave = CPF (ou tr_id/nome).
    ValueError se pre_matricula.json não existir ou estiver ilegível.
    """
    base = avisos.carregar_pre_matricula()
    cadastros = base.get("cadastros") or {}
    resultado: dict[str, dict] = {}
    for turma, lista in (base.get("turmas_intencao") or {}).items():
        for a in lista or []:
            tipo = avisos.situacao_do_aluno(a)
            if a.get("substituido_por_nova_tentativa") or tipo not in TIPOS:
                continue
            chave = str(a.get("cpf") or a.get("tr_id") or a.get("nome") or "").strip()
            if not chave or chave in resultado:
                continue
            cad = cadastros.get(str(a.get("cpf") or "")) or cadastros.get(str(a.get("tr_id") or "")) or {}
            resultado[chave] = {
                "nome": _uma_linha(a.get("nome") or cad.get("nome_aluno")),
                "turma": _uma_linha(str(turma).replace(" do Ensino Fundamental", "")),
                "responsavel": _uma_linha(cad.get("nome_responsavel")),
                "numero": extrair_numero(cad.get("telefone")),
                "tipo": tipo,
                "tem_cadastro": bool(cad),
            }
    return resultado


# ───────────────────────────── registro (nunca repetir) ─────────────────────────────

def pasta_registro() -> Path:
    """Resumo de cada execução (sem texto de mensagem; números mascarados)."""
    return paths.dados_ano_atual() / "WHATSAPP_MATRICULA"


def _arquivo_base() -> Path:
    return paths.dados_ano_atual() / "pre_matricula.json"


def carregar_avisos() -> dict:
    """
    Registro de avisos (chave 'avisos_whatsapp' do pre_matricula.json). ValueError / ArquivoJsonCorrompidoError se
    o arquivo estiver ilegível: sem o registro não dá para garantir que não vai repetir.
    """
    base = carregar_json(_arquivo_base(), lambda: {}, tipo_esperado=dict)
    reg = base.get("avisos_whatsapp")
    if not isinstance(reg, dict):
        reg = {}
    reg.setdefault("linha_de_base_em", None)
    reg.setdefault("alunos", {})
    return reg


def salvar_avisos(reg: dict) -> None:
    """Relê o arquivo na hora e troca só a chave 'avisos_whatsapp': o resto do pre_matricula.json fica como está."""
    base = carregar_json(_arquivo_base(), lambda: {}, tipo_esperado=dict)
    base["avisos_whatsapp"] = reg
    salvar_json_atomico(_arquivo_base(), base, indent=2)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _registro(situacao: str, **extra) -> dict:
    """{'avisado': 'SIM'|'NÃO', 'situacao': ..., 'em': timestamp, ...}"""
    return {"avisado": "SIM" if situacao == "enviado" else "NÃO", "situacao": situacao, "em": _agora(), **extra}


def _bloqueado(reg: Optional[dict], numero: Optional[str]) -> bool:
    if not reg:
        return False
    situacao = reg.get("situacao")
    if situacao in _BLOQUEIAM:
        return True
    if situacao == "sem_whatsapp":        # corrigiu o telefone no cadastro → tenta de novo
        return bool(numero) and reg.get("numero_id") == _id_numero(numero)
    return int(reg.get("tentativas") or 0) >= TENTATIVAS_MAXIMAS


def _classificar_falha(erro: str) -> str:
    t = avisos._sem_acento(erro)
    if "conectado" in t or "nao confirmou o envio" in t:
        return "desconectado"
    if "sem whatsapp" in t or "nao tem whatsapp" in t or "nao reconhece" in t:
        return "sem_whatsapp"
    if "pode ou nao" in t:
        return "incerto"
    return "falha"


# ───────────────────────────── envio ─────────────────────────────

def _resumo(modo: str) -> dict:
    return {"modo": modo, "linha_de_base": 0, "enviados": 0, "simulados": 0,
            "por_tipo": {t: 0 for t in TIPOS}, "sem_celular": [], "sem_whatsapp": [], "incertos": [],
            "falhas": [], "adiados": 0, "bloqueado": "", "registro": ""}


def avisar_matriculados(*, provedor=None, hoje: Optional[date] = None, incluir_existentes: bool = False,
                        limite: Optional[int] = None, pausa_s: float = PAUSA_ENTRE_ENVIOS_S,
                        dormir: Callable[[float], None] = time.sleep, saida: Callable[[str], None] = print) -> dict:
    """
    Avisa os responsáveis dos alunos 'aguardando' e 'matriculado' que ainda não foram avisados (ver o topo do
    arquivo). Levanta ValueError / ArquivoJsonCorrompidoError (nada enviado) se dados ou ajustes estiverem ruins.
    Devolve o resumo: {modo, linha_de_base, enviados, simulados, por_tipo, sem_celular, sem_whatsapp, incertos,
    falhas, adiados, bloqueado, registro}.
    """
    hoje = hoje or date.today()
    cfg = ajustes()
    tipos = [t for t in TIPOS if t == "matriculado" or cfg["avisar_aguardando"]]
    textos = {t: modelo(t) for t in tipos}
    alunos = alunos_elegiveis()
    reg = carregar_avisos()

    if provedor is None:
        from src.servicos.whatsapp.gerenciador import obter_gerenciador
        provedor = obter_gerenciador().provedor
    simulado = getattr(provedor, "nome", "") == "simulado"
    r = _resumo("simulado" if simulado else "real")

    if reg["linha_de_base_em"] is None:
        reg["linha_de_base_em"] = _agora()
        if not incluir_existentes:
            for chave, a in alunos.items():
                reg["alunos"].setdefault(chave, {}).setdefault(a["tipo"], _registro("linha_de_base"))
            salvar_avisos(reg)
            r["linha_de_base"] = len(alunos)
            saida(f"Primeira execução: {len(alunos)} aluno(s) já cadastrado(s) foram marcados como linha de base e NÃO "
                  "serão avisados. Só quem se cadastrar ou for aprovado daqui para a frente recebe mensagem.")
            return r
        salvar_avisos(reg)

    grupos: dict[tuple[str, str], dict] = {}
    for chave, a in alunos.items():
        tipo = a["tipo"]
        if tipo not in tipos:
            continue
        anterior = reg["alunos"].get(chave, {}).get(tipo)
        if a["numero"] is None:
            if not _bloqueado(anterior, None):
                r["sem_celular"].append(f"{nome_proprio(a['nome'])} ({a['turma']})"
                                        + ("" if a["tem_cadastro"] else " — sem cadastro consultado"))
            continue
        if _bloqueado(anterior, a["numero"]):
            continue
        g = grupos.setdefault((tipo, a["numero"]), {"alunos": [], "chaves": []})
        g["alunos"].append(a)
        g["chaves"].append(chave)

    titulo = "SIMULAÇÃO — nada sai do computador" if simulado else "ENVIO REAL"
    saida(f"Comunicado por WhatsApp | {titulo} | {len(grupos)} mensagem(ns) a enviar")
    if r["sem_celular"]:
        saida(f"Sem celular válido no cadastro ({len(r['sem_celular'])}): " + "; ".join(r["sem_celular"][:20]))

    if grupos and not simulado:
        est = provedor.estado()
        if not est.conectado:
            r["bloqueado"] = f"WhatsApp não conectado ({est.detalhe}). Nada foi enviado; abra a tela WhatsApp e conecte."
            saida(r["bloqueado"])
            r["registro"] = str(_gravar_registro(r, hoje))
            return r

    ordem = sorted(grupos.items(), key=lambda kv: tipos.index(kv[0][0]))
    maximo = limite or cfg["limite_por_execucao"]
    r["adiados"] = max(0, len(ordem) - maximo)
    previas: set[str] = set()
    for i, ((tipo, numero), g) in enumerate(ordem[:maximo]):
        verificar_cancelamento()
        nomes = [a["nome"] for a in g["alunos"]]
        texto = montar_mensagem(nomes, hoje, cfg, textos[tipo], [a["turma"] for a in g["alunos"]], tipo)
        if simulado and tipo not in previas:
            previas.add(tipo)
            saida(f"\nPRÉVIA — aviso '{tipo}' (para {mascarar_numero(numero)}):\n{texto}\n")
        try:
            res = provedor.enviar(numero, texto)
        except EnvioNaoAutorizadoError as exc:
            r["bloqueado"] = str(exc)
            break
        except Exception as exc:            # nunca derruba o resto da pré-matrícula
            res = ResultadoEnvio(False, False, erro=f"Falha ao enviar ({type(exc).__name__}).")

        rotulo = f"{_juntar_nomes([nome_proprio(n) for n in nomes])} ({mascarar_numero(numero)})"
        if res.ok and res.simulado:
            r["simulados"] += len(nomes)
            continue
        if res.ok:
            for chave in g["chaves"]:
                reg["alunos"].setdefault(chave, {})[tipo] = _registro(
                    "enviado", numero=mascarar_numero(numero), id_mensagem=res.id_mensagem or "")
            salvar_avisos(reg)               # a cada envio: se travar no meio, ninguém recebe duas vezes
            r["enviados"] += len(nomes)
            r["por_tipo"][tipo] += len(nomes)
            saida(f"✅ Aviso '{tipo}' enviado: {rotulo}")
        else:
            falha = _classificar_falha(res.erro or "")
            if falha == "desconectado":
                r["bloqueado"] = res.erro or "WhatsApp desconectado."
                break
            for chave in g["chaves"]:
                anterior = reg["alunos"].get(chave, {}).get(tipo) or {}
                reg["alunos"].setdefault(chave, {})[tipo] = _registro(
                    falha, numero=mascarar_numero(numero), numero_id=_id_numero(numero),
                    erro=str(res.erro or "")[:200], tentativas=int(anterior.get("tentativas") or 0) + 1)
            salvar_avisos(reg)
            {"sem_whatsapp": r["sem_whatsapp"], "incerto": r["incertos"]}.get(falha, r["falhas"]).append(rotulo)
            saida(f"⚠️ Aviso '{tipo}' não enviado para {rotulo}: {res.erro}")
        if not simulado and pausa_s and i < min(len(ordem), maximo) - 1:
            dormir(pausa_s)

    if r["bloqueado"]:
        saida(f"⛔ Envio interrompido: {r['bloqueado']}")
    if r["adiados"]:
        saida(f"{r['adiados']} mensagem(ns) ficam para a próxima execução (limite de {maximo} por vez).")
    if r["incertos"]:
        saida("Confira no WhatsApp se estes receberam (não serão reenviados sozinhos): " + "; ".join(r["incertos"]))
    saida(f"Resumo: {r['enviados']} enviado(s) ({r['por_tipo']['aguardando']} aguardando, {r['por_tipo']['matriculado']} "
          f"matriculado), {r['simulados']} simulado(s), {len(r['sem_celular'])} sem celular, "
          f"{len(r['sem_whatsapp'])} sem WhatsApp, {len(r['falhas'])} falha(s).")
    r["registro"] = str(_gravar_registro(r, hoje))
    return r


def _gravar_registro(resumo: dict, hoje: date) -> Path:
    """Resumo da execução (sem texto de mensagem; números já mascarados)."""
    caminho = pasta_registro() / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{resumo['modo']}.json"
    salvar_json_atomico(caminho, {**resumo, "registro": "", "data": hoje.isoformat()}, indent=2)
    return caminho


def avisar_apos_pre_matricula(ativo: bool = True) -> Optional[dict]:
    """
    Gancho chamado no fim da pré-matrícula. Nunca levanta erro (um problema aqui não pode estragar a coleta que
    acabou de dar certo); o cancelamento do usuário (BaseException) continua passando.
    """
    if not ativo:
        return None
    try:
        if not ajustes()["ativo"]:
            print("\nComunicado por WhatsApp desligado em config_usuario.json (comunicado_matricula.ativo).")
            return None
        print("\n" + "=" * 60 + "\nCOMUNICADO POR WHATSAPP (PRÉ-MATRÍCULA)\n" + "=" * 60)
        return avisar_matriculados()
    except Exception as exc:
        log.error("comunicado por WhatsApp não executado: %s", type(exc).__name__)
        print(f"⚠️ Comunicado por WhatsApp NÃO foi executado (nada enviado): {exc}")
        return None

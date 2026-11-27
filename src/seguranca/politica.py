"""
politica.py — quem pode chamar o quê
=====================================
Regra central, num lugar só (e não espalhada por cada rota — esquecer a próxima que alguém criar deixaria um buraco):

    leitura (GET/HEAD/OPTIONS)  → consulta        (ver telas e tabelas)
    escrita (POST/PUT/PATCH/DELETE) → operador    (executar automações, editar registros, enviar mensagens)
    exceções que exigem ADMIN   → usuários, auditoria, credenciais e integrações, ano letivo (restaurar/dados de teste), assistente
                                  de 1ª execução, conexão do WhatsApp, escolher pastas, data de corte
    exceções liberadas ao OPERADOR dentro de /configuracoes/ → trocar o ano letivo (para consultar), copiar dados, "Turmas do QR antigo"
    exceções liberadas a QUALQUER usuário entrado → ver a própria sessão, sair, trocar a própria senha

A tabela é por EXPRESSÃO REGULAR sobre o caminho; a primeira que casar vale. O que não casa com nenhuma cai na regra geral.

PERFIL INDEPENDENTE — "pedagoga". Não faz parte da escada consulta < operador < admin (nela, "consulta" já leria TUDO). Ela tem uma
LISTA DE PERMISSÕES PRÓPRIA, com a lógica invertida: o que não está na lista é NEGADO (inclusive qualquer rota que alguém criar depois).
A lista (`_REGRAS_PEDAGOGA`) só tem leitura: telas Turmas, Alunos e Encaminhamentos SUS, o painel resumido, e executar/acompanhar as
automações `turmas` e `alunos` (a coleta de `alunos` cobre o modo básico, alunos.py, e o completo, alunos_completo.py). Essas coletas só
LEEM do SERE (navegam e consultam) e atualizam o cache local em JSON; nenhuma grava, envia ou apaga nada no SERE. Nada de configuração
é gravável por ela, a não ser a própria senha de acesso e o usuário/senha do SERE (as coletas dela precisam entrar no SERE). O que o administrador/operador já fazem NÃO muda: para eles vale exatamente a tabela acima.
"""
from __future__ import annotations

import re

LEITURA = ("GET", "HEAD", "OPTIONS")

# Escada dos perfis hierárquicos (quem tem o nível exigido ou mais, pode). A Pedagoga NÃO está aqui de propósito: ver `permite`.
NIVEL = {"consulta": 1, "operador": 2, "admin": 3}

PEDAGOGA = "pedagoga"

# Automações (chaves de src/comum/registro_scripts.py) que a Pedagoga pode abrir e executar. "alunos" tem os dois modos de coleta
# (básico = alunos.py, completo = alunos_completo.py): o modo é uma opção da própria automação, não outra chave.
AUTOMACOES_PEDAGOGA = frozenset({"turmas", "alunos"})

# Interface da Pedagoga: o que a tela mostra (o servidor monta o HTML só com isto; os dados e as ações são barrados à parte,
# pela lista de rotas abaixo). Esconder um botão nunca é a proteção — é só a vitrine.
TELAS_PEDAGOGA = frozenset({"painel", "turmas", "alunos", "encaminhamentos", "automacoes", "configuracoes", "ajuda"})
GRUPOS_AUTOMACAO_PEDAGOGA = frozenset({"cadastros"})        # "Turmas e alunos" (só Turmas e Alunos aparecem dentro dele)
CONFIGURACOES_PEDAGOGA = frozenset({"minha_conta", "escola", "ano_letivo", "navegador", "backup_automatico", "senha_sere", "temas", "perfil"})
# Destas, só estas aceitam alteração (a própria senha e o tema, que é do navegador). As demais aparecem para CONSULTA: a Pedagoga vê o
# que as coletas usam, mas quem grava ano letivo, senha do SERE, dados da escola etc. é o administrador.
CONFIGURACOES_PEDAGOGA_EDITAVEIS = frozenset({"minha_conta", "temas", "senha_sere"})

# (método ou None = qualquer, expressão, perfil mínimo). A ORDEM IMPORTA: a primeira que casa vale.
_TABELA: list[tuple[tuple[str, ...] | None, re.Pattern, str]] = [
    # a própria conta: qualquer usuário entrado
    (None, re.compile(r"^/web/api/seguranca/(sessao|estender|sair|trocar-senha)$"), "consulta"),
    (None, re.compile(r"^/web/(sair|trocar-senha)$"), "consulta"),
    # administração
    (None, re.compile(r"^/web/api/seguranca/(usuarios|auditoria)(/.*)?$"), "admin"),
    # leituras que mostram logins/links de integrações: só admin
    (LEITURA, re.compile(r"^/web/api/configuracoes/(gmail|rco|prematricula|google-conta)(/.*)?$"), "admin"),
    (LEITURA, re.compile(r"^/web/api/google/autorizacao$"), "admin"),
    (LEITURA, re.compile(r"^/web/api/whatsapp/(qr|qr\.svg|webhooks)$"), "admin"),
    (LEITURA, re.compile(r"^/web/api/wizard/atividade$"), "operador"),
    # escritas que o operador PODE fazer dentro de /configuracoes
    (("POST",), re.compile(r"^/web/api/configuracoes/ano-letivo$"), "operador"),
    (("POST",), re.compile(r"^/web/api/configuracoes/ano-letivo/backup$"), "operador"),
    (("POST",), re.compile(r"^/web/api/configuracoes/mapeamento-turmas-qr(/(ignorar|testar))?$"), "operador"),
    # escritas só do admin
    (("POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/web/api/configuracoes(/.*)?$"), "admin"),
    (("POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/web/api/google/autorizacao(/.*)?$"), "admin"),
    (("POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/web/api/wizard(/.*)?$"), "admin"),
    (("POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/web/api/sistema(/.*)?$"), "admin"),
    (("POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/web/api/whatsapp/(conectar|desconectar|provedor|envio-real|webhooks|fila/config)$"), "admin"),
]


def perfil_exigido(metodo: str, caminho: str) -> str:
    caminho = caminho.rstrip("/") or "/"
    metodo = (metodo or "GET").upper()
    for metodos, expressao, perfil in _TABELA:
        if (metodos is None or metodo in metodos) and expressao.match(caminho):
            return perfil
    return "consulta" if metodo in LEITURA else "operador"


# ───────────────────────────── perfil Pedagoga (lista de permissões) ─────────────────────────────

_CHAVES_PEDAGOGA = "|".join(re.escape(c) for c in sorted(AUTOMACOES_PEDAGOGA))

# (métodos, expressão). Tudo o que não casar aqui é NEGADO à Pedagoga. HEAD e OPTIONS valem como GET.
_REGRAS_PEDAGOGA: list[tuple[tuple[str, ...], re.Pattern]] = [(m, re.compile(e)) for m, e in [
    # a própria conta
    (("GET",), r"^/web/api/seguranca/sessao$"),
    (("POST",), r"^/web/api/seguranca/(estender|sair|trocar-senha)$"),
    (("GET",), r"^/web/trocar-senha$"),
    # a página do sistema (o HTML já vem só com o que ela pode ver)
    (("GET",), r"^/(web)?$"),
    # dados das telas liberadas (só leitura). O painel responde numa versão reduzida (ver rotas.painel_resumo)
    (("GET",), r"^/web/api/(painel/resumo|turmas/lista|alunos/lista|encaminhamentos/lista|ano-letivo/contexto)$"),
    # configurações que as coletas usam, só para CONSULTA (as gravações ficam com o administrador)
    (("GET",), r"^/web/api/configuracoes/(escola|ano-letivo|navegador|backup-automatico)$"),
    # ajuda (texto fixo, sem dado de aluno)
    (("GET",), r"^/web/api/ajuda(/[^/]+){1,2}$"),
    # automações liberadas: ver, executar e acompanhar. NÃO: gravar opções guardadas (/flags), navegador, apagar histórico
    (("GET",), r"^/web/api/automacoes/lista$"),
    (("GET",), rf"^/web/api/automacoes/(?:{_CHAVES_PEDAGOGA})/(componentes|status|configuracao|historico|flags)$"),
    (("GET",), rf"^/web/api/automacoes/(?:{_CHAVES_PEDAGOGA})/historico/[^/]+$"),
    (("POST",), rf"^/web/api/automacoes/(?:{_CHAVES_PEDAGOGA})/(executar|previa|resposta|cancelar)$"),
    (("POST",), r"^/web/api/cgm/analisar$"),                  # só confere o texto de CGMs digitados (não grava nada)
    # ÚNICA gravação de configuração dela: usuário e senha do SERE (as coletas dela precisam entrar no SERE). A rota do wizard confere de novo.
    (("POST",), r"^/web/api/wizard/credenciais_sere/executar$"),
    # atualização silenciosa de Turmas e Alunos ao abrir o sistema (começa uma vez por abertura; só dispara as duas coletas dela)
    (("GET",), r"^/web/api/pedagoga/atualizar-dados/status$"),
    (("POST",), r"^/web/api/pedagoga/atualizar-dados$"),
]]


def _pedagoga_permite(metodo: str, caminho: str) -> bool:
    metodo = "GET" if metodo in ("HEAD", "OPTIONS") else metodo
    return any(metodo in metodos and expressao.match(caminho) for metodos, expressao in _REGRAS_PEDAGOGA)


def permite(perfil: str, metodo: str, caminho: str) -> bool:
    """A decisão única do guarda: este perfil pode fazer este método neste caminho?

    Administrador, operador e consulta: pela escada (`perfil_exigido`), exatamente como antes. Pedagoga: pela lista de permissões
    própria. Perfil desconhecido: nada (nega por padrão)."""
    caminho = caminho.rstrip("/") or "/"
    metodo = (metodo or "GET").upper()
    if perfil == PEDAGOGA:
        return _pedagoga_permite(metodo, caminho)
    return NIVEL.get(perfil, 0) >= NIVEL.get(perfil_exigido(metodo, caminho), 99)


def motivo_da_negativa(perfil: str, metodo: str, caminho: str) -> str:
    """Texto curto para a auditoria (nunca vai ao navegador)."""
    if perfil == PEDAGOGA:
        return f"{metodo} {caminho} (fora das permissões do perfil pedagoga)"
    return f"{metodo} {caminho} (precisa {perfil_exigido(metodo, caminho)})"


def automacao_permitida(perfil: str | None, chave: str) -> bool:
    """A automação `chave` pode ser executada/vista por este perfil? (A Pedagoga só tem as de AUTOMACOES_PEDAGOGA.)

    Sem perfil (chamada fora da interface web: linha de comando, agendador) não há o que restringir aqui."""
    return perfil != PEDAGOGA or chave in AUTOMACOES_PEDAGOGA


def pode_ver_tela(perfil: str | None, tela: str) -> bool:
    return perfil != PEDAGOGA or tela in TELAS_PEDAGOGA


def pode_ver_grupo_automacao(perfil: str | None, grupo: str) -> bool:
    return perfil != PEDAGOGA or grupo in GRUPOS_AUTOMACAO_PEDAGOGA


def pode_ver_configuracao(perfil: str | None, id_config: str) -> bool:
    return perfil != PEDAGOGA or id_config in CONFIGURACOES_PEDAGOGA


def resumo_de_permissoes(perfil: str | None) -> dict:
    """O que a tela precisa saber do perfil (vai para o navegador, só para desenhar a vitrine)."""
    return {"perfil": perfil or "", "restrito": perfil == PEDAGOGA,
            "configuracoes_editaveis": sorted(CONFIGURACOES_PEDAGOGA_EDITAVEIS) if perfil == PEDAGOGA else None}

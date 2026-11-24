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
"""
from __future__ import annotations

import re

LEITURA = ("GET", "HEAD", "OPTIONS")

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

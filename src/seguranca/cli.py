"""
cli.py — o que se faz pelo terminal (e que o instalador usa)
==============================================================
    python -m src.seguranca existe                      sai com 0 se já há usuários, 1 se não há, 3 se o cadastro está ilegível
    python -m src.seguranca criar-admin                 cria o 1º administrador (pede usuário, nome e senha 2x, sem mostrar a senha)
    python -m src.seguranca criar-admin-provisorio      cria o 1º administrador "admin" com senha provisória "admin" (troca obrigatória no 1º acesso; usado pelo instalador)
    python -m src.seguranca redefinir-senha             RECUPERAÇÃO de quem perdeu a senha (exige estar neste computador)
    python -m src.seguranca desbloquear USUARIO         tira o bloqueio por tentativas erradas
    python -m src.seguranca listar                      usuários, perfis e situação (nunca mostra senha nem hash)
    python -m src.seguranca verificar-auditoria         confere a corrente de logs/auditoria.log
    python -m src.seguranca proteger-pasta              restringe credenciais/ ao usuário atual do Windows

A senha só é digitada no terminal (getpass) ou lida da entrada padrão com --senha-stdin; nunca vai como argumento de linha de
comando, porque argumentos aparecem na lista de processos do computador.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from src.comum import paths

from . import auditoria, segredo, senhas, usuarios
from .usuarios import ErroUsuarios

OK, ERRO, CANCELADO, ILEGIVEL = 0, 1, 2, 3
TENTATIVAS = 5


def _ler_senha(prompt: str) -> str:
    return getpass.getpass(prompt)


def _ler_texto(prompt: str) -> str:
    return input(prompt)


def _escrever(texto: str = "") -> None:
    print(texto)


def _pedir_senha_nova(usuario: str, nome: str = "") -> str | None:
    _escrever(f"Regras da senha: pelo menos {senhas.MIN_CARACTERES} caracteres, misturando 3 tipos (minúsculas, MAIÚSCULAS, números, símbolos) "
              f"ou uma frase com {senhas.LIMITE_CARACTERES_MISTURA}+ caracteres. Não use o nome de usuário nem sequências.")
    for _ in range(TENTATIVAS):
        s1 = _ler_senha("Senha: ")
        problemas = senhas.problemas_da_senha(s1, usuario, nome)
        if problemas:
            for p in problemas:
                _escrever("  - " + p)
            continue
        if _ler_senha("Repita a senha: ") != s1:
            _escrever("  - As duas senhas não são iguais. Tente de novo.")
            continue
        return s1
    _escrever("Muitas tentativas. Nada foi criado.")
    return None


def _senha_da_entrada_padrao() -> str:
    return (sys.stdin.readline() or "").rstrip("\r\n")


def cmd_existe(_args) -> int:
    estado = usuarios.estado()
    return {"ok": OK, "sem_usuarios": ERRO, "ilegivel": ILEGIVEL}[estado]


def cmd_criar_admin(args) -> int:
    estado = usuarios.estado()
    if estado == "ilegivel":
        _escrever("O cadastro de usuários está ilegível; use 'redefinir-senha' ou restaure usuarios.json.bak (veja documentacao/Seguranca.md).")
        return ILEGIVEL
    if estado == "ok":
        _escrever("O sistema já tem usuários cadastrados; nada a fazer. (Para trocar uma senha perdida: python -m src.seguranca redefinir-senha)")
        return OK
    try:
        _escrever("")
        _escrever("=== Criar o administrador do AUTO SERE ===")
        _escrever("Este será o primeiro usuário e terá controle total do sistema.")
        if args.senha_stdin:
            usuario, nome, senha = args.usuario or "admin", args.nome or "Administrador", _senha_da_entrada_padrao()
        else:
            digitado = _ler_texto(f"Nome de usuário [{args.usuario or 'admin'}]: ").strip()
            usuario = digitado or args.usuario or "admin"
            nome = _ler_texto("Seu nome completo [Administrador]: ").strip() or args.nome or "Administrador"
            senha = _pedir_senha_nova(usuario, nome)
            if senha is None:
                return ERRO
        usuarios.criar_primeiro_admin(usuario, nome, senha, origem="instalador")
    except (KeyboardInterrupt, EOFError):
        _escrever("\nCancelado. O administrador poderá ser criado no primeiro acesso ao sistema.")
        return CANCELADO
    except ErroUsuarios as e:
        _escrever("ERRO: " + e.mensagem)
        for p in e.problemas:
            _escrever("  - " + p)
        return ERRO
    except segredo.ChaveIndisponivel as e:
        _escrever(f"ERRO: não foi possível proteger a senha ({e}).")
        return ERRO
    segredo.proteger_pasta(paths.CREDENCIAIS_DIR)
    _escrever(f"Administrador '{usuario}' criado. Guarde a senha: ela NÃO pode ser recuperada (só redefinida, estando neste computador).")
    return OK


def cmd_criar_admin_provisorio(_args) -> int:
    """Usado pelo instalador: admin/admin com troca de senha obrigatória no primeiro login. Não faz nada se já houver usuários."""
    estado = usuarios.estado()
    if estado == "ilegivel":
        _escrever("O cadastro de usuários está ilegível; veja documentacao/Seguranca.md.")
        return ILEGIVEL
    if estado == "ok":
        _escrever("O sistema já tem usuários cadastrados; nada a fazer.")
        return OK
    try:
        usuarios.criar_admin_provisorio(origem="instalador")
    except ErroUsuarios as e:
        _escrever("ERRO: " + e.mensagem)
        return ERRO
    except segredo.ChaveIndisponivel as e:
        _escrever(f"ERRO: não foi possível proteger a senha ({e}).")
        return ERRO
    segredo.proteger_pasta(paths.CREDENCIAIS_DIR)
    _escrever(f"Administrador provisório criado: usuário '{usuarios.USUARIO_PROVISORIO}', senha '{usuarios.SENHA_PROVISORIA}'. "
              f"No primeiro acesso o sistema exige uma senha nova (mínimo de {senhas.MIN_CARACTERES} caracteres).")
    return OK


def cmd_criar_usuario(args) -> int:
    """Cadastra um usuário comum (pedagoga, operador, consulta ou admin) depois que o administrador já existe."""
    estado = usuarios.estado()
    if estado == "ilegivel":
        _escrever("O cadastro de usuários está ilegível (veja documentacao/Seguranca.md).")
        return ILEGIVEL
    if estado == "sem_usuarios":
        _escrever("Ainda não há administrador. Crie-o primeiro: python -m src.seguranca criar-admin")
        return ERRO
    perfil = args.perfil
    rotulo = usuarios.ROTULO_PERFIL[perfil]
    try:
        _escrever("")
        _escrever(f"=== Criar usuário com perfil {rotulo} ===")
        padrao = args.usuario or perfil
        if args.senha_stdin:
            usuario, nome, senha = padrao, args.nome or rotulo, _senha_da_entrada_padrao()
        else:
            usuario = _ler_texto(f"Nome de usuário [{padrao}]: ").strip() or padrao
            nome = _ler_texto(f"Nome completo [{args.nome or rotulo}]: ").strip() or args.nome or rotulo
            senha = _pedir_senha_nova(usuario, nome)
            if senha is None:
                return ERRO
        usuarios.criar(usuario, nome, perfil, senha, por="instalador", trocar_senha=True)
    except (KeyboardInterrupt, EOFError):
        _escrever("\nCancelado. O usuário poderá ser criado depois, em Configurações → Usuários e segurança.")
        return CANCELADO
    except ErroUsuarios as e:
        _escrever("ERRO: " + e.mensagem)
        for pr in e.problemas:
            _escrever("  - " + pr)
        return ERRO
    except segredo.ChaveIndisponivel as e:
        _escrever(f"ERRO: não foi possível proteger a senha ({e}).")
        return ERRO
    _escrever(f"Usuário '{usuario}' ({rotulo}) criado. No primeiro acesso o sistema pede para trocar a senha.")
    return OK


def cmd_redefinir_senha(args) -> int:
    try:
        usuario = (args.usuario or _ler_texto("Usuário que vai receber a nova senha: ")).strip().lower()
        if not usuario:
            return CANCELADO
        _escrever("ATENÇÃO: esta recuperação só existe porque você está NESTE computador. Fica registrada na auditoria.")
        try:
            segredo.obter_pimenta(criar=False)
        except segredo.ChaveIndisponivel as e:
            if not args.regenerar_chave:
                _escrever(f"A chave de proteção das senhas não pode ser lida ({e}).")
                _escrever("Se for isso mesmo, rode de novo com --regenerar-chave: as senhas de TODOS os outros usuários deixam de valer "
                          "(um administrador terá de redefinir cada uma) e o usuário informado ganha a nova senha.")
                return ERRO
            _escrever("Recriando a chave de proteção das senhas...")
            segredo.regenerar_pimenta()
            auditoria.registrar("chave_regenerada", usuario, "", "recuperação pelo computador")
            regenerou = True
        else:
            regenerou = False
        if usuarios.estado() == "ilegivel":
            if not args.criar:
                _escrever("O arquivo de usuários está ilegível. Opções: restaurar credenciais/usuarios.json.bak (renomeando para usuarios.json), "
                          "ou rodar de novo com --criar, que põe os arquivos ruins de lado e cria o usuário como administrador "
                          "(os OUTROS usuários precisarão ser cadastrados de novo).")
                return ILEGIVEL
            for nome_arq in usuarios.isolar_arquivo_ilegivel():
                _escrever(f"Arquivo posto de lado: credenciais/{nome_arq}")
        existente = usuarios.obter_por_usuario(usuario)
        if existente is None and usuarios.estado() == "ok" and not args.criar:
            _escrever("Esse usuário não existe. Use --criar para criá-lo como administrador, ou 'listar' para ver os nomes.")
            return ERRO
        senha = _senha_da_entrada_padrao() if args.senha_stdin else _pedir_senha_nova(usuario, existente.nome if existente else "")
        if senha is None:
            return ERRO
        novo = usuarios.redefinir_pela_linha_de_comando(usuario, senha, criar_se_nao_existir=bool(args.criar))
        if regenerou:
            n = usuarios.invalidar_senhas_exceto(novo.id)
            if n:
                _escrever(f"{n} outro(s) usuário(s) precisam ter a senha redefinida por um administrador.")
    except (KeyboardInterrupt, EOFError):
        _escrever("\nCancelado.")
        return CANCELADO
    except ErroUsuarios as e:
        _escrever("ERRO: " + e.mensagem)
        for p in e.problemas:
            _escrever("  - " + p)
        return ERRO
    _escrever(f"Senha de '{novo.usuario}' redefinida. O usuário está desbloqueado e ativo.")
    return OK


def cmd_desbloquear(args) -> int:
    try:
        alvo = usuarios.obter_por_usuario(args.usuario)
        if alvo is None:
            _escrever("Esse usuário não existe.")
            return ERRO
        usuarios.desbloquear(alvo.id, por="linha de comando")
    except ErroUsuarios as e:
        _escrever("ERRO: " + e.mensagem)
        return ERRO
    _escrever(f"Usuário '{alvo.usuario}' desbloqueado.")
    return OK


def cmd_listar(_args) -> int:
    try:
        lista = usuarios.listar()
    except ErroUsuarios as e:
        _escrever("ERRO: " + e.mensagem)
        return ILEGIVEL
    if not lista:
        _escrever("Nenhum usuário cadastrado.")
        return OK
    for u in lista:
        situacao = "ATIVO" if u.ativo else "DESATIVADO"
        if u.bloqueado:
            situacao += ", BLOQUEADO até " + (u.bloqueado_ate or "")
        if u.trocar_senha:
            situacao += ", senha temporária"
        _escrever(f"{u.usuario:<20} {usuarios.ROTULO_PERFIL.get(u.perfil, u.perfil):<14} {situacao}   ({u.nome})")
    return OK


def cmd_verificar_auditoria(_args) -> int:
    r = auditoria.verificar_corrente()
    if r["integra"]:
        _escrever(f"Auditoria íntegra: {r['linhas']} evento(s), corrente sem quebras.")
        return OK
    _escrever(f"ATENÇÃO: a corrente da auditoria está QUEBRADA na linha {r['primeira_quebra']} de logs/auditoria.log (arquivo alterado ou apagado em parte).")
    return ERRO


def cmd_proteger_pasta(_args) -> int:
    if segredo.proteger_pasta(paths.CREDENCIAIS_DIR):
        _escrever(f"Pasta {paths.CREDENCIAIS_DIR} restrita ao usuário atual.")
        return OK
    _escrever("Não consegui restringir a pasta (sem permissão ou sistema sem suporte).")
    return ERRO


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.seguranca", description="Usuários e senhas do AUTO SERE")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("existe", help="sai com 0 se já há usuários").set_defaults(f=cmd_existe)
    a = sub.add_parser("criar-admin", help="cria o primeiro administrador")
    a.add_argument("--usuario", default="")
    a.add_argument("--nome", default="")
    a.add_argument("--senha-stdin", action="store_true", help="lê a senha da entrada padrão (instalação sem janela)")
    a.set_defaults(f=cmd_criar_admin)
    sub.add_parser("criar-admin-provisorio", help="cria o administrador admin/admin com troca de senha obrigatória no 1º acesso").set_defaults(f=cmd_criar_admin_provisorio)
    u = sub.add_parser("criar-usuario", help="cria um usuário (pedagoga, operador, consulta ou admin); o administrador já precisa existir")
    u.add_argument("--perfil", choices=usuarios.PERFIS, default="pedagoga")
    u.add_argument("--usuario", default="")
    u.add_argument("--nome", default="")
    u.add_argument("--senha-stdin", action="store_true", help="lê a senha da entrada padrão (sem janela)")
    u.set_defaults(f=cmd_criar_usuario)

    r = sub.add_parser("redefinir-senha", help="recuperação de senha perdida (exige estar no computador)")
    r.add_argument("--usuario", default="")
    r.add_argument("--criar", action="store_true", help="cria o usuário como administrador se ele não existir")
    r.add_argument("--regenerar-chave", action="store_true", help="recria a chave de proteção (invalida as senhas dos OUTROS usuários)")
    r.add_argument("--senha-stdin", action="store_true")
    r.set_defaults(f=cmd_redefinir_senha)
    d = sub.add_parser("desbloquear", help="remove o bloqueio por tentativas erradas")
    d.add_argument("usuario")
    d.set_defaults(f=cmd_desbloquear)
    sub.add_parser("listar", help="lista usuários").set_defaults(f=cmd_listar)
    sub.add_parser("verificar-auditoria", help="confere a corrente do log de auditoria").set_defaults(f=cmd_verificar_auditoria)
    sub.add_parser("proteger-pasta", help="restringe credenciais/ ao usuário atual").set_defaults(f=cmd_proteger_pasta)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return int(args.f(args))


if __name__ == "__main__":                                          # pragma: no cover
    sys.exit(main())

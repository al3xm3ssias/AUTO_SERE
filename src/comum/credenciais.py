""" === RESUMO ESTRUTURAL DO SCRIPT ===
Este arquivo não possui classes ou funções estruturadas.
==================================== """

"""
credenciais.py — Loader de credenciais do SERE
=================================================
Portado de AUTO_SERE/credenciais_modelo.py para src/comum/credenciais.py.

Comportamento idêntico ao original: lê LOGIN e SENHA das variáveis de
ambiente SERE_LOGIN e SERE_SENHA, com fallback para os valores placeholder
"cpf" / "senha_sere" caso não estejam definidas (para nunca quebrar um
import, mesmo sem .env configurado — mas nesse caso o login no SERE vai
falhar de propósito, como já acontecia no script original).

As variáveis de ambiente devem ser definidas em credenciais/.env (ver
.env.example na raiz do projeto), carregado via python-dotenv ou pela
configuração "python.envFile" do VS Code (já configurada pelo bootstrap).

Uso:
    from src.comum.credenciais import LOGIN, SENHA
"""
import os

LOGIN = os.getenv("SERE_LOGIN", "cpf")
SENHA = os.getenv("SERE_SENHA", "senha_sere")
""" === RESUMO ESTRUTURAL DO SCRIPT ===
Este arquivo não possui classes ou funções estruturadas.
==================================== """

"""
credenciais.py — Loader de credenciais do SERE e da Pré-Matrícula
=================================================
Portado de AUTO_SERE/credenciais_modelo.py para src/comum/credenciais.py.

Comportamento idêntico ao original: lê LOGIN e SENHA das variáveis de
ambiente SERE_LOGIN e SERE_SENHA, com fallback para os valores placeholder
"cpf" / "senha_sere" caso não estejam definidas (para nunca quebrar um
import, mesmo sem .env configurado — mas nesse caso o login no SERE vai
falhar de propósito, como já acontecia no script original).

MATRICULA_PREMATRICULA e SENHA_PREMATRICULA (adicionadas em 03/09/2026,
a pedido do usuário, para portar src.automacao.pre_matricula): credenciais
de um site DIFERENTE do SERE — o portal de pré-matrícula
(web.pontagrossa.pr.gov.br/prematricula) usa login próprio (MATRICULA/
SENHA_PRE no script original), não o CPF/senha do SERE. Lidas de
PREMATRICULA_LOGIN e PREMATRICULA_SENHA, mesmo padrão de fallback.

EMAIL_REMETENTE e EMAIL_SENHA_APP (adicionadas em 04/09/2026, a pedido do
usuário, para portar src.automacao.envia_email): credenciais de envio de
e-mail via SMTP (Gmail). O script original (envia_email.py) tinha o
e-mail institucional e uma SENHA DE APLICATIVO em texto puro diretamente
no código-fonte — uma credencial exposta. O usuário confirmou que essa
senha específica já foi/será revogada antes de qualquer uso deste
projeto; o valor real NUNCA foi copiado para cá — lidas de EMAIL_REMETENTE
e EMAIL_SENHA_APP, com fallback placeholder (login vai falhar de
propósito até configurar o .env com uma nova senha de aplicativo).

As variáveis de ambiente devem ser definidas em credenciais/.env (ver
.env.example na raiz do projeto), carregado via python-dotenv ou pela
configuração "python.envFile" do VS Code (já configurada pelo bootstrap).

Uso:
    from src.comum.credenciais import LOGIN, SENHA
    from src.comum.credenciais import MATRICULA_PREMATRICULA, SENHA_PREMATRICULA
    from src.comum.credenciais import EMAIL_REMETENTE, EMAIL_SENHA_APP
"""
import os

# Carrega credenciais/.env no ambiente ANTES de ler as variáveis abaixo.
# Sem isto, quem importa este módulo fora do fluxo "salvar credenciais"
# (ex.: ao reiniciar o servidor) só enxerga os valores placeholder.
from dotenv import load_dotenv
from .paths import CREDENCIAIS_DIR
load_dotenv(CREDENCIAIS_DIR / ".env")

LOGIN = os.getenv("SERE_LOGIN", "cpf")
SENHA = os.getenv("SERE_SENHA", "senha_sere")

MATRICULA_PREMATRICULA = os.getenv("PREMATRICULA_LOGIN", "matricula")
SENHA_PREMATRICULA     = os.getenv("PREMATRICULA_SENHA", "senha_prematricula")

EMAIL_REMETENTE  = os.getenv("EMAIL_REMETENTE", "email@exemplo.com")
EMAIL_SENHA_APP  = os.getenv("EMAIL_SENHA_APP", "senha_app_email")

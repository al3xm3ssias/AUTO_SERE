"""
google_auth.py — autenticação com as APIs do Google (usada pelo Google Sheets)
=============================================================================
Só cuida de CREDENCIAIS: quem é o programa perante o Google. As chamadas à API ficam em
src/comum/google_sheets.py.

Dois jeitos de autenticar (o programa descobre qual pelo conteúdo do arquivo de credenciais):

  • OAuth 2.0 "aplicativo de computador" (arquivo com a chave "installed"): o programa age COMO A SUA CONTA
    Google. Na 1ª vez abre o navegador para você autorizar; o token fica salvo e é renovado sozinho.
    É o jeito indicado para planilhas que são suas, e o único em que a planilha CRIADA pelo programa
    aparece no seu Google Drive.
  • Conta de serviço (arquivo com "type": "service_account"): um "robô" com e-mail próprio, sem navegador.
    Serve para planilhas que existem e foram COMPARTILHADAS com o e-mail do robô (campo client_email do
    JSON). Uma planilha criada por ele pertence ao robô e você não a vê, a menos que ele a compartilhe.

SENHA DE APLICATIVO NÃO FUNCIONA: a Google Sheets API só aceita OAuth 2.0 ou conta de serviço. A senha de
aplicativo (16 letras) vale apenas para e-mail (SMTP/IMAP, como em src/automacao/envia_email.py).

Configuração (credenciais/.env ou variáveis de ambiente; nada disso fica no código):
    GOOGLE_API_CREDENTIALS   caminho do JSON baixado do Google Cloud
                             (padrão: credenciais/google_credentials.json). Relativo = a partir da raiz do projeto.
                             GOOGLE_CREDENTIALS_FILE (nome usado pelo antigo sheets_sync) também é aceita.
    GOOGLE_TOKEN_FILE        onde guardar o token do OAuth (padrão: credenciais/google_token.json).
                             Um token.json do antigo sheets_sync pode ser reaproveitado apontando para ele.
    GOOGLE_OAUTH_ABRIR_NAVEGADOR   1 (padrão) abre o navegador na autorização; 0 só mostra o endereço
                             (útil em WSL/servidor sem navegador).

Segurança: credenciais/ e os arquivos google_*.json estão no .gitignore e fora do backup. Nada daqui grava
token, chave ou segredo em log: só o modo usado e o NOME do arquivo.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import credenciais as _credenciais  # noqa: F401  (importar já carrega credenciais/.env no ambiente)
from .arquivos_json import salvar_json_atomico
from .paths import CREDENCIAIS_DIR, RAIZ_PROJETO

log = logging.getLogger(__name__)

ESCOPO_SHEETS = "https://www.googleapis.com/auth/spreadsheets"
ESCOPO_DRIVE_LEITURA = "https://www.googleapis.com/auth/drive.readonly"   # exigido pela exportação de planilha em PDF
ESCOPO_CONTATOS = "https://www.googleapis.com/auth/contacts"              # criar/atualizar contatos (People API)
ESCOPOS_PADRAO = [ESCOPO_SHEETS]

MODO_OAUTH = "oauth"
MODO_CONTA_SERVICO = "service_account"

NOME_CREDENCIAIS_PADRAO = "google_credentials.json"
NOME_TOKEN_PADRAO = "google_token.json"
TEMPO_MAXIMO_AUTORIZACAO_S = 300


class GoogleErro(Exception):
    """Base dos erros deste módulo e de google_sheets.py: a mensagem já vem pronta para o usuário."""


class CredenciaisGoogleErro(GoogleErro):
    """Credenciais ausentes, ilegíveis, recusadas ou que exigem autorização do usuário."""


# ───────────────────────────── onde ficam os arquivos ──────────────────────────

def _caminho_de(variaveis: tuple[str, ...], padrao: str) -> Path:
    for nome in variaveis:
        valor = (os.getenv(nome) or "").strip()
        if valor:
            caminho = Path(valor).expanduser()
            return caminho if caminho.is_absolute() else RAIZ_PROJETO / caminho
    return CREDENCIAIS_DIR / padrao


def caminho_credenciais() -> Path:
    return _caminho_de(("GOOGLE_API_CREDENTIALS", "GOOGLE_CREDENTIALS_FILE"), NOME_CREDENCIAIS_PADRAO)


def caminho_token() -> Path:
    return _caminho_de(("GOOGLE_TOKEN_FILE",), NOME_TOKEN_PADRAO)


def caminho_token_drive() -> Path:
    """
    Token do OAuth para quem precisa TAMBÉM ler o Drive (exportar planilha em PDF: pareceres do Infantil). Fica num arquivo
    à parte (google_token_drive.json) para o token só-de-planilhas continuar valendo: o token guarda os escopos de quando
    foi autorizado, então misturar os dois faria o programa achar que já tem a permissão do Drive sem ter.
    """
    base = caminho_token()
    return base.with_name(f"{base.stem}_drive{base.suffix}")


def caminho_token_contatos() -> Path:
    """
    Token do OAuth do Google Contatos (People API). Arquivo à parte (google_token_contatos.json) pelo mesmo motivo do
    Drive: o token guarda os escopos de quando foi autorizado, então misturar faria o programa achar que já tem a
    permissão de contatos sem ter, e a autorização de contatos não invalida a das planilhas.
    """
    base = caminho_token()
    return base.with_name(f"{base.stem}_contatos{base.suffix}")


def credenciais_configuradas() -> bool:
    """True se o arquivo de credenciais do Google existe (não testa se o Google o aceita)."""
    return caminho_credenciais().is_file()


def _abrir_navegador() -> bool:
    return (os.getenv("GOOGLE_OAUTH_ABRIR_NAVEGADOR") or "1").strip().lower() not in ("0", "false", "nao", "não")


# ───────────────────────────── leitura do arquivo de credenciais ───────────────

def detectar_modo(caminho: Path | None = None) -> str:
    """'oauth' ou 'service_account', conforme o conteúdo do arquivo. Não imprime nada do conteúdo."""
    caminho = Path(caminho) if caminho else caminho_credenciais()
    if not caminho.is_file():
        raise CredenciaisGoogleErro(
            f"Arquivo de credenciais do Google não encontrado ({caminho.name}). Baixe o JSON no Google Cloud "
            f"(APIs e serviços → Credenciais) e salve em credenciais/{NOME_CREDENCIAIS_PADRAO}, ou aponte o caminho em "
            "GOOGLE_API_CREDENTIALS. Passo a passo em docs/GOOGLE_SHEETS.md.")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CredenciaisGoogleErro(f"O arquivo {caminho.name} não é um JSON válido de credenciais do Google.") from None
    if isinstance(dados, dict):
        if dados.get("type") == MODO_CONTA_SERVICO:
            return MODO_CONTA_SERVICO
        if "installed" in dados:
            return MODO_OAUTH
        if "web" in dados:
            raise CredenciaisGoogleErro(
                f"{caminho.name} é um 'ID do cliente OAuth' do tipo Aplicativo da Web. Crie outro do tipo "
                "'Aplicativo para computador' (ou use uma conta de serviço).")
    raise CredenciaisGoogleErro(
        f"{caminho.name} não parece um arquivo de credenciais do Google (esperado: ID do cliente OAuth do tipo "
        "'Aplicativo para computador' ou chave JSON de conta de serviço).")


# ───────────────────────────── token do OAuth ──────────────────────────────────

def _salvar_token(creds, caminho: Path) -> None:
    salvar_json_atomico(caminho, json.loads(creds.to_json()))
    try:
        os.chmod(caminho, 0o600)           # só o dono lê; no Windows é inofensivo (a pasta já é do usuário)
    except OSError:
        pass
    log.info("Token do Google salvo (%s).", caminho.name)


def _oauth(caminho_cred: Path, escopos: list[str], interativo: bool, arquivo_token: Path | None = None):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    caminho_tok = Path(arquivo_token) if arquivo_token else caminho_token()
    creds = None
    if caminho_tok.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(caminho_tok), escopos)
        except (OSError, ValueError):
            log.warning("Token do Google ilegível (%s); será pedida nova autorização.", caminho_tok.name)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _salvar_token(creds, caminho_tok)
            log.info("Token do Google renovado.")
            return creds
        except RefreshError:
            log.warning("O Google recusou renovar o token (revogado ou expirado); será pedida nova autorização.")

    if not interativo:
        raise CredenciaisGoogleErro(
            "O acesso ao Google ainda não foi autorizado (ou expirou). Autorize uma vez pela tela "
            "(Primeira execução → Google API, ou Automações → Planilha no Google Sheets) e repita.")

    from google_auth_oauthlib.flow import InstalledAppFlow
    from . import google_oauth_navegador as navegador
    fluxo = InstalledAppFlow.from_client_secrets_file(str(caminho_cred), escopos)
    abrir = _abrir_navegador()
    conta = navegador.parametros_da_conta()
    print("Autorização do Google: " + ("o navegador vai abrir; entre na sua conta e clique em Permitir."
                                        if abrir else "abra o endereço mostrado abaixo no navegador e clique em Permitir."))
    if conta.get("login_hint"):
        print(f"   Conta esperada: {conta['login_hint']}")
    try:
        # A biblioteca sempre "abre o navegador" que lhe damos (open_browser=True): quem decide se abre mesmo, em qual
        # navegador/perfil e se copia o endereço é o NavegadorAutorizacao (google_oauth_navegador.py), conforme o .env.
        with navegador.navegador_de_autorizacao(abrir):
            creds = fluxo.run_local_server(
                port=0, open_browser=True, browser=navegador.NOME_REGISTRADO, timeout_seconds=TEMPO_MAXIMO_AUTORIZACAO_S,
                authorization_prompt_message="Endereço de autorização: {url}",
                success_message="Autorização concluída. Pode fechar esta aba e voltar ao AUTO SERE.", **conta)
    except Exception as exc:                                              # noqa: BLE001 — a mensagem do Google pode ter detalhes
        raise CredenciaisGoogleErro(f"A autorização do Google não foi concluída ({type(exc).__name__}). Tente de novo.") from None
    if not creds:
        raise CredenciaisGoogleErro("A autorização do Google não foi concluída. Tente de novo.")
    _salvar_token(creds, caminho_tok)
    return creds


def _conta_de_servico(caminho_cred: Path, escopos: list[str]):
    from google.oauth2 import service_account
    try:
        return service_account.Credentials.from_service_account_file(str(caminho_cred), scopes=escopos)
    except (OSError, ValueError, KeyError):
        raise CredenciaisGoogleErro(
            f"A chave da conta de serviço em {caminho_cred.name} está incompleta ou corrompida. Baixe uma nova no Google Cloud.") from None


# ───────────────────────────── entrada principal ───────────────────────────────

def obter_credenciais(escopos: list[str] | None = None, *, interativo: bool = True, arquivo_token: Path | None = None):
    """
    Credenciais prontas para usar na API. `interativo=False` nunca abre navegador (agendador): se faltar
    autorização, levanta CredenciaisGoogleErro explicando o que fazer. `arquivo_token` guarda o token do OAuth num
    arquivo próprio (padrão: google_token.json); a conta de serviço não usa token em arquivo.
    """
    escopos = list(escopos or ESCOPOS_PADRAO)
    caminho_cred = caminho_credenciais()
    modo = detectar_modo(caminho_cred)
    log.info("Autenticando no Google (modo %s, arquivo %s).", modo, caminho_cred.name)
    if modo == MODO_CONTA_SERVICO:
        return _conta_de_servico(caminho_cred, escopos)
    return _oauth(caminho_cred, escopos, interativo, arquivo_token)

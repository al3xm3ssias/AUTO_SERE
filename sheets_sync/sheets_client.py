# =============================================================================
#  sheets_client.py — Wrapper para a Google Sheets API
# =============================================================================

import logging
import time
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    CREDENTIALS_FILE,
    SCOPES,
    SPREADSHEET_ID,
    TOKEN_FILE,
)

logger = logging.getLogger(__name__)

# Retry automático para erros 429 (quota) e 503 (servidor)
_RETRY_STATUS = {429, 500, 503}
_MAX_RETRIES  = 5

def _autenticar() -> Credentials:
    """
    Fluxo OAuth2 simplificado para WSL/Linux.
    """

    import os
    from pathlib import Path

    creds: Optional[Credentials] = None

    token_path = Path(TOKEN_FILE)

    # Carrega token existente
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES
        )

    # Se não existir ou for inválido
    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            logger.info("Token renovado automaticamente.")

        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE,
                SCOPES
            )

            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

            auth_url, _ = flow.authorization_url(
                access_type="offline",
                prompt="consent"
            )

            print("\nAbra este link no navegador:\n")
            print(auth_url)
            print("\n")

            code = input("Cole aqui o código de autorização: ")

            flow.fetch_token(code=code)

            creds = flow.credentials

        # salva token
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

        logger.info("Token salvo com sucesso.")

    return creds

def criar_servico():
    """Retorna o serviço autenticado da Sheets API."""
    creds = _autenticar()
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return service.spreadsheets()


def _executar_com_retry(request, descricao: str = ""):
    """Executa uma requisição com retry exponencial."""
    for tentativa in range(1, _MAX_RETRIES + 1):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status in _RETRY_STATUS and tentativa < _MAX_RETRIES:
                espera = 2 ** tentativa
                logger.warning(
                    "Erro %s em '%s'. Tentativa %d/%d — aguardando %ds.",
                    e.resp.status, descricao, tentativa, _MAX_RETRIES, espera,
                )
                time.sleep(espera)
            else:
                raise


def ler_aba(sheets, nome_aba: str) -> List[List]:
    """
    Lê todos os dados de uma aba e retorna como lista de listas.
    Células vazias ao final de cada linha são omitidas pela API — normalize depois.
    """
    resultado = _executar_com_retry(
        sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{nome_aba}'",
            valueRenderOption="UNFORMATTED_VALUE",
        ),
        descricao=f"ler_aba({nome_aba})",
    )
    return resultado.get("values", [])


def escrever_lote(sheets, atualizacoes: List[dict]) -> int:
    """
    Envia um batch de atualizações para a planilha em uma única chamada.

    Cada item de `atualizacoes` deve ter:
        {
            "range": "'Nome da Aba'!A2:L2",
            "values": [[val_A, val_B, ..., val_L]]
        }

    Retorna o número de células atualizadas.
    """
    if not atualizacoes:
        return 0

    body = {
        "valueInputOption": "USER_ENTERED",   # respeita formatação de datas
        "data": atualizacoes,
    }
    resultado = _executar_com_retry(
        sheets.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body,
        ),
        descricao="escrever_lote",
    )
    return resultado.get("totalUpdatedCells", 0)


def adicionar_linhas(sheets, nome_aba: str, linhas: List[List]) -> int:
    """
    Adiciona linhas novas no final da aba (append).
    Retorna o número de linhas inseridas.
    """
    if not linhas:
        return 0

    resultado = _executar_com_retry(
        sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{nome_aba}'",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": linhas},
        ),
        descricao=f"adicionar_linhas({nome_aba})",
    )
    updates = resultado.get("updates", {})
    return updates.get("updatedRows", 0)


def listar_abas(sheets) -> List[str]:
    """Retorna os nomes de todas as abas da planilha."""
    meta = _executar_com_retry(
        sheets.get(spreadsheetId=SPREADSHEET_ID, fields="sheets.properties.title"),
        descricao="listar_abas",
    )
    return [s["properties"]["title"] for s in meta.get("sheets", [])]
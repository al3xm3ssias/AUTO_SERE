# =============================================================================
#  config.py — Configurações centralizadas do sincronizador
# =============================================================================
#  Edite apenas este arquivo para adaptar o script à sua planilha.
# =============================================================================

import os

from pathlib import Path


BASE = Path.home() / "compartilhado/ARQUIVOS/ESCOLA JUDITH"
# --- Arquivo de turmas ---
TURMAS_JSON_PATH = os.getenv("TURMAS_JSON_PATH", BASE /  "PYTHON/SERE/2026/turmas.json")



# --- Google Sheets ---
SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    "1DPyBHxA3rz-u1nxgCN9f_XosZrqyiR8zuy4ACqeGpgE",  # ID da sua planilha
)

# Arquivo de credenciais OAuth2 gerado no Google Cloud Console
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE",  str(BASE / "PYTHON/SERE/2026/sheets_sync/credentials.json"))

# Arquivo de token salvo após o primeiro login (gerado automaticamente)
TOKEN_FILE = "/home/sambauser/compartilhado/ARQUIVOS/ESCOLA JUDITH/PYTHON/SERE/2026/token.json"

# Escopos necessários para leitura e escrita na planilha
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- Mapeamento de colunas (0-indexed internamente, A=0, B=1, ...) ---
# Altere aqui se a planilha mudar de layout.
COL = {
    "numero":              0,   # A — Nº de chamada
    "cpf":                 1,   # B — CPF (não existe no JSON, será mantido como está)
    "cgm":                 2,   # C — CGM  ← chave única
    "sus":                 3,   # D — SUS  (ignorado)
    "nome":                4,   # E — Nome do aluno
    "data_nasc":           5,   # F — D.N.
    "idade":               6,   # G — Idade (ignorado)
    "sexo":                7,   # H — Sexo
    "status":              8,   # I — M / T
    "data_matricula":      9,   # J — Data de Matrícula
    "escola_origem":       10,  # K — Escola de Origem (ignorado)
    "data_transferencia":  11,  # L — Data de Transferência
}

# Número total de colunas na planilha (A até L = 12)
TOTAL_COLS = 12

# Linha inicial dos dados (1-indexed para a API do Sheets; linha 1 = cabeçalho)
HEADER_ROW = 1
DATA_START_ROW = 2  # dados começam na linha 2

# Valores de status usados na coluna I
STATUS_MATRICULADO   = "M"
STATUS_TRANSFERIDO   = "T"

SEXO_MASCULINO = "M"
SEXO_FEMININO  = "F"

SEXO_MAP = {"M": SEXO_MASCULINO, "F": SEXO_FEMININO}

# Mapeamento do campo "Situação" do JSON para o código da planilha
SITUACAO_MAP = {
    "Matriculado": STATUS_MATRICULADO,
    "Transferido":  STATUS_TRANSFERIDO,
}

# Colunas que o script NÃO toca (mantém o valor existente na planilha)
COLUNAS_IGNORADAS = {"cpf", "sus", "idade", "escola_origem", "status"}
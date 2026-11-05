# 📚 Sincronizador de Turmas — turmas.json ↔ Google Sheets

Sincroniza automaticamente os dados do arquivo `turmas.json` com o Google Sheets,
identificando alunos matriculados e transferidos via CGM (chave única).

---

## 📁 Estrutura do projeto

```
sheets_sync/
├── main.py            # Ponto de entrada — execute este arquivo
├── config.py          # ⚙️  Configurações (planilha, colunas, paths)
├── turmas_reader.py   # Leitura e parsing do turmas.json
├── sheets_client.py   # Wrapper da Google Sheets API (auth + chamadas)
├── sync_engine.py     # Motor de sincronização (lógica principal)
├── requirements.txt   # Dependências Python
├── credentials.json   # ❌ NÃO inclua no Git (veja abaixo)
├── token.json         # ❌ NÃO inclua no Git (gerado automaticamente)
└── .gitignore
```

---

## ⚙️ Configuração inicial

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Criar credenciais no Google Cloud

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. Crie um projeto (ou use um existente)
3. Ative a **Google Sheets API**:
   - Menu lateral → APIs e Serviços → Biblioteca → busque "Google Sheets API" → Ativar
4. Crie credenciais OAuth2:
   - APIs e Serviços → Credenciais → Criar credenciais → **ID do cliente OAuth**
   - Tipo: **Aplicativo de computador**
   - Baixe o JSON e salve como **`credentials.json`** na pasta do projeto
5. Em "Tela de consentimento OAuth", adicione seu e-mail como usuário de teste

### 3. Configurar o `config.py`

Abra `config.py` e verifique/ajuste:

```python
SPREADSHEET_ID = "1DPyBHxA3rz-u1nxgCN9f_XosZrqyiR8zuy4ACqeGpgE"  # ID da sua planilha
TURMAS_JSON_PATH = "turmas.json"   # caminho para o JSON
```

### 4. Primeira execução (autenticação)

```bash
python main.py
```

Na primeira vez, o browser abrirá pedindo autorização. Após aceitar,
o `token.json` será salvo e as próximas execuções não precisarão do browser.

---

## ▶️ Como usar

```bash
# Sincronizar todas as turmas
python main.py

# Sincronizar apenas uma turma específica
python main.py --turma "1º Ano Integral A"

# Simular sem gravar (dry-run)
python main.py --dry-run

# Logs detalhados
python main.py --verbose

# Usar arquivo JSON alternativo
python main.py --json /caminho/para/outro.json
```

---

## 🗂️ Mapeamento de colunas

| Coluna | Campo na planilha     | Fonte              |
|--------|-----------------------|--------------------|
| A      | Nº de chamada         | `N` do JSON        |
| B      | CPF                   | Preservado         |
| C      | CGM ⭐ chave única    | `CGM` do JSON      |
| D      | SUS                   | Preservado         |
| E      | Nome do aluno         | `Nome` do JSON     |
| F      | D.N.                  | `Data Nasc.`       |
| G      | Idade                 | Preservado         |
| H      | Sexo                  | `Sexo`             |
| I      | Status                | `M` ou `T`         |
| J      | Data de Matrícula     | `Data Matricula` (se Matriculado) |
| K      | Escola de Origem      | Preservado         |
| L      | Data de Transferência | `Data Matricula` (se Transferido) |

> **Preservado** = o script não toca nessa coluna; mantém o que já está na planilha.

---

## 📋 Lógica de sincronização

| Situação | O que o script faz |
|----------|-------------------|
| Aluno novo, Matriculado | Adiciona linha nova com `M` na col. I e data em col. J |
| Aluno novo, Transferido | Adiciona linha nova com `T` na col. I e data em col. L |
| Aluno existente sem mudanças | Não faz nada (sem chamadas à API) |
| Aluno existente com dados alterados | Atualiza apenas as colunas gerenciadas |
| Aluno existente → Transferido | Muda col. I para `T`, limpa col. J, preenche col. L |

---

## 🔒 Segurança das credenciais

Adicione ao `.gitignore`:

```
credentials.json
token.json
*.log
```

Para ambientes de servidor ou n8n, use variáveis de ambiente:

```bash
export GOOGLE_CREDENTIALS_FILE=/caminho/seguro/credentials.json
export SPREADSHEET_ID=sua_planilha_id
export TURMAS_JSON_PATH=/caminho/turmas.json
```

---

## 🔗 Integração com n8n

No n8n, use um nó **Execute Command** com:

```bash
cd /caminho/do/projeto && python main.py --json turmas.json
```

Ou com o JSON gerado dinamicamente pelo fluxo:

```bash
python main.py --json {{ $json.caminho_arquivo }}
```

---

## 📄 Logs

A cada execução é gerado um arquivo `sync_YYYYMMDD.log` com o histórico completo.
O terminal exibe um resumo como:

```
============================================================
  RESUMO FINAL
  ➕ Adicionados  : 3
  ✏  Atualizados  : 5
  🔄 Transferidos : 2
  ⏱  Duração      : 4.2s
============================================================
```
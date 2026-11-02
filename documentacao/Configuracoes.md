# Configurações, 1ª execução, ano letivo e backup

## Onde ficam as coisas
| O quê | Onde |
|---|---|
| Segredos (SERE, pré-matrícula, RCO, Gmail, WhatsApp) | `credenciais/.env` (fora do Git); gravar pela tela vale na hora |
| Preferências do usuário | `config/config_usuario.json` (`src/comum/configuracao.py`) |
| Configuração fixa | `config/config.yaml` (nome, escola, ano base 2026, logging: arquivo DEBUG, console INFO, 5 MB × 3) |
| Dados da escola | `config_usuario.json` → `unidade_escolar` (`src/comum/escola.py`; **obrigatórios:** nome, CEP e logradouro) |
| Servidor | `src/comum/servidor.py`: `AUTO_SERE_HOST`/`PORT` > `"servidor"` no JSON > `127.0.0.1:8000` (porta fixa!) |

Chaves de `config_usuario.json`: `pasta_digitalizacao`, `pasta_modelos`, `cgm_upload`, `setup_concluido`, `ano_letivo`,
`unidade_escolar`, `flags_automacoes` (por automação; ex.: `analisa_sere`), `data_corte_transferidos`, `observacao_historico`,
`servidor`, `comunicado_matricula`. **No zip atual:** `setup_concluido=false`, `ano_letivo="2025"` e a unidade sem `codigo`,
`inep`, `telefone`, `email` e `responsavel`.

## Telas e rotas de Configurações
Credenciais: SERE, pré-matrícula (`/configuracoes/prematricula`), Gmail (`/gmail` → `EMAIL_REMETENTE`, `EMAIL_SENHA_APP`,
senha de app no padrão "xxxx xxxx xxxx xxxx"), RCO (`/rco`, opção de usar o login do SERE). Também: pasta de digitalização,
data de corte, modelos de parecer, dados da escola (`/configuracoes/escola`, com consulta de CEP via ViaCEP e BrasilAPI),
ano letivo. Editar o JSON à mão com o programa aberto só vale ao reiniciar (a faixa avisa e oferece "Aplicar agora").

## 1ª execução (wizard)
`GET /wizard/status`, `POST /wizard/<passo>/executar`, `GET /wizard/atividade`. `GET /wizard/status` informa: escola, `credenciais_sere`, `turmas`, `gerar_pastas`, `funcionarios`, `alunos` (**só básico**),
`google_api` e `whatsapp` (conectado de verdade ou não). Cada passo é concluído pela existência do arquivo que gera
(`turmas.json`, `funcionarios.json`, `alunos.json`) ou pela configuração salva. A coleta de turmas e alunos pode demorar; o progresso é
mostrado na tela.

## Ano letivo (`src/comum/ano_letivo.py`, `paths.py`)
Precedência: `AUTO_SERE_ANO_BASE` > escolha da tela > ano do calendário. A troca é **imediata, sem reiniciar**:
grava a escolha, recarrega os 18 módulos que fixam `dados/<ano>` na importação (lista `MODULOS_COM_ANO_FIXO`), **desfaz se
falhar** e recusa se houver automação rodando. `tests/test_ano_letivo_troca.py` falha se um módulo novo fixar o ano sem
estar na lista.
**Modo somente consulta:** ano anterior ao do calendário → selo no topo, faixa de aviso, tela de carregamento e guarda no
servidor que recusa toda escrita (CLI só aceita `--simular`). Pendência: desabilitar também os botões de escrita nas outras telas.

## Backup (`src/comum/backup.py`, automação `backup`)
Zip datado + manifesto com tamanho e SHA-256. **Entra:** `dados/<ano>/` (`.json .xlsx .csv .txt`), `dados/calendario/`
(sem cache de feriados), `config/`. **Nunca entra:** `credenciais/`, qualquer `.env`, `DIGITALIZAÇÃO/`, screenshots, logs, backups.
Destino: `dados/backup/backup_AAAA-MM-DD_HHMMSS.zip`; guarda os **10** mais recentes **por ano** (`AUTO_SERE_BACKUP_MANTER`).
`--restaurar ARQ.zip` extrai para conferir; `--aplicar` repõe de verdade **com backup de segurança antes**; `--so-dados`
não toca em config/calendário; `--ano 2025` faz backup de outro ano. Restaurar a configuração não desfaz o ano escolhido.
Pendência 3b: backup automático ao fim das coletas. `backup_auto_sere.py` (raiz) é outro empacotador, com `C:\Auto_sere` fixo.

## Logs e locks
`src/comum/logger.py` (arquivo rotativo + console); `logs/` e `locks/` são gerados em execução. Senhas não vão para log.

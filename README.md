# AUTO_SERE — Projeto Portado

> Estrutura gerada por `criar_projeto.py` em 27/08/2026 11:16.
> Escola Municipal Profª Judith Macedo Silveira — Automação SERE.

## O que é isto

Este é o ambiente de trabalho organizado para a portabilidade do ecossistema
AUTO_SERE (scripts Python de automação do portal SERE, geração de relatórios,
painel escolar, etc.), migrando de uma pasta plana de scripts para um projeto
estruturado, versionável e multiplataforma (Windows / Linux / WSL).

**Este bootstrap NUNCA apaga arquivos existentes.** Pode ser executado
novamente a qualquer momento — ele só cria o que ainda estiver faltando.

> **Windows:** para instalar e usar como aplicativo (atalho + Chrome), veja [`docs/WINDOWS.md`](docs/WINDOWS.md).

## Estrutura de pastas

```
AUTO_SERE/
├── criar_projeto.py       ← este bootstrap (idempotente, não-destrutivo)
├── requirements.txt        ← dependências Python do projeto
├── .gitignore
├── .env.example             ← modelo de variáveis de ambiente
├── README.md                 ← este arquivo
├── .vscode/                   ← configuração do VS Code (settings, launch, tasks)
├── src/
│   ├── comum/                  ← logger.py, credenciais.py (loader), config.py, paths.py
│   ├── automacao/               ← scripts de automação SERE portados (um módulo por script)
│   ├── relatorios/               ← geração de relatórios/planilhas/PDFs/crachás/etiquetas
│   └── web/                       ← index.html, painel escolar, manual do escriturário
├── config/                     ← configuração versionável (não sensível)
├── credenciais/                ← credenciais.py real e .env (fora do git — ver .gitignore)
├── dados/                       ← JSONs de trabalho (alunos.json, turmas.json, ...)
│   └── backup/                    ← backups automáticos, não destrutivos
├── logs/                         ← logs rotativos de execução
├── locks/                        ← arquivos de lock (execução concorrente / agendamento)
├── docs/                          ← documentação do projeto
├── scripts/                       ← orquestração (.sh, .ps1, equivalentes multiplataforma)
└── tests/                          ← testes automatizados
    └── fixtures/                    ← dados de teste (sem dados reais de alunos)
```

## Como usar o bootstrap

```bash
python criar_projeto.py
```

Pode rodar de novo sempre que quiser — é seguro. Ele nunca apaga nada que já
exista; apenas informa o que já estava lá e cria o que estiver faltando.

Para escolher outro destino:

```bash
python criar_projeto.py --destino "/caminho/para/o/projeto"
```

## Próximos passos (depois do bootstrap)

1. Copiar `.env.example` para `credenciais/.env` e preencher os valores reais
   (login/senha do SERE, WORKDIR, ano base). **Nunca commitar esse arquivo.**
2. Criar um ambiente virtual Python e instalar as dependências:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux / WSL:
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```
3. Abrir a pasta no VS Code (`code .`) — o `.vscode/settings.json` já aponta
   o interpretador Python para o `.venv` criado no passo anterior.
4. Portar os módulos originais para `src/`, um de cada vez, começando pelos
   módulos comuns (`logger.py`, `credenciais.py`) e seguindo para os scripts
   de automação.

## Compatibilidade

Testado para funcionar de forma equivalente em:
- Windows (PowerShell / VS Code)
- Linux (servidor Samba / `sambauser`)
- WSL (Windows Subsystem for Linux)

Nenhum caminho absoluto de uma máquina específica é assumido pelo bootstrap.

# AUTO SERE

Automação do portal **SERE** (Sistema Estadual de Registro Escolar) e de rotinas administrativas da **Escola Municipal Profª Judith Macedo Silveira**, operada por uma interface web local.

O sistema coleta turmas, alunos e funcionários, confere e envia documentos, trata transferências, gera pareceres e termos, consulta pré-matrícula, SISREG e RCO, e envia comunicados. Tudo roda no computador da escola: não há banco de dados nem servidor externo, e os dados ficam em arquivos JSON por ano letivo.

> **Estado do projeto:** a maior parte foi testada com dados e páginas simuladas. As execuções reais no SERE, RCO, SISREG, pré-matrícula e WhatsApp ainda estão sendo validadas. Veja [`pendencias.md`](pendencias.md), [`PROXIMAS_ETAPAS.md`](PROXIMAS_ETAPAS.md) e [`BUGS_CONHECIDOS.md`](BUGS_CONHECIDOS.md).

---

## Instalação

### Windows (uso normal)
Não precisa ter Python instalado, só internet na primeira vez e o Google Chrome.

1. Extraia o zip completo em qualquer pasta.
2. Dê dois cliques em `INSTALAR_WINDOWS.bat` e escolha a pasta de instalação (sugestão: `C:\AUTO_SERE`).
3. O assistente instala um Python próprio (3.12, em `runtime\python`), as bibliotecas e os navegadores do Playwright, e cria o atalho **AUTO SERE**.
4. Na primeira abertura, a tela **1ª execução** pede os dados da escola, as credenciais do SERE e a coleta de turmas e alunos.

Rodar a instalação de novo é seguro: o programa é atualizado e dados, credenciais e configurações são preservados. Detalhes, instalação silenciosa, uso sem internet e solução de problemas em [`docs/WINDOWS.md`](docs/WINDOWS.md).

### Linux / WSL / desenvolvimento
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example credenciais/.env   # preencha SERE_LOGIN e SERE_SENHA
python -m src.web.app
```
Abra **http://127.0.0.1:8000** (porta padrão). Rode sempre como módulo (`python -m ...`), a partir da raiz do projeto.

---

## Como usar

| O quê | Como |
|---|---|
| Abrir o sistema (Windows) | Atalho **AUTO SERE** ou `AUTO_SERE.bat` (Chrome em modo aplicativo) |
| Encerrar o servidor | `PARAR_AUTO_SERE.bat` ou `python -m src.launcher --parar` |
| Subir o gateway do WhatsApp (Docker) | `WHATSAPP_SUBIR.bat` |
| Apagar o vínculo do WhatsApp | `WHATSAPP_ZERAR_VINCULO.bat` |
| Servidor sem abrir janela | `python -m src.launcher --sem-janela` |
| Mudar host/porta | `AUTO_SERE_HOST` / `AUTO_SERE_PORT` ou `"servidor"` em `config/config_usuario.json` (mantenha a porta fixa) |

### Telas principais
Painel, Turmas, Alunos, Pré-matrícula, Funcionários, Encaminhamentos do SUS, Alunos fora do raio, Calendário letivo, Documentos, WhatsApp, **Automações** e **Configurações** (dados da escola, credenciais, ano letivo, modelos de parecer, data de corte dos transferidos).

### Automações
A tela **Automações** lista mais de 30 rotinas, todas registradas em `src/comum/registro_scripts.py`. Cada uma recebe as mesmas opções comuns na tela e na linha de comando: turma, matriculados/transferidos, CGM, modo de teste, reprocessar erros e prévia do que será processado. Principais grupos:

- **Coletas:** Turmas, Alunos (básico ou completo), Funcionários, Vínculos dos funcionários (SERE × RH × holerite), Coleta e-mails.
- **Documentos dos alunos:** Analisa documentos (SERE e pasta), Validar, Documentos, Upload de um tipo, Comprimir, Limpeza total, Gerar e Mapear pastas, Cruzamento, Máscara de dados, Compara anos.
- **Transferidos:** Fila, Gerar guia e histórico, Enviar ao SERE, Pareceres dos transferidos. Visão geral em [`docs/FLUXO_TRANSFERIDOS.md`](docs/FLUXO_TRANSFERIDOS.md).
- **Pareceres e termos:** Pareceres do Fundamental (modelo Word + QR code), Pareceres do Infantil (RCO), Gerar termos de ciência.
- **Matrícula:** Processo de pré-matrícula, Rematrícula, CEP (regra de raio, padrão 2,0 km), Encaminhamentos do SUS (SISREG).
- **Comunicação:** Mandar avisos por e-mail (envio real ainda bloqueado; hoje só simulação e teste) e WhatsApp ([`docs/WHATSAPP.md`](docs/WHATSAPP.md)).
- **Manutenção:** Backup dos dados.

### Linha de comando
Todas as automações também rodam fora da tela, por exemplo no agendador de tarefas:

```bash
python -m src.comum.cli listar
python -m src.comum.cli SCRIPT --ajuda
python -m src.comum.cli validar --turma "3º Ano Integral" --simular   # só mostra o que seria processado
python -m src.comum.cli alunos --modo completo --rapido
python -m src.comum.cli backup
```
Scripts que alteram o SERE pedem confirmação (`SIM` ou `--confirmo`), exceto com `--teste`. Saída: 0 concluído, 1 falhou, 2 pedido inválido ou não confirmado. No Windows instalado, use `runtime\python\python.exe -m src.comum.cli ...`.

### Ano letivo, backup e modo consulta
- **Configurações → Ano letivo** escolhe o ano em uso; a troca é imediata, sem reiniciar. Ordem de precedência: `AUTO_SERE_ANO_BASE` > escolha da tela > ano do calendário.
- Ao abrir um ano anterior ao do calendário, o sistema entra em **somente consulta**: o servidor recusa qualquer escrita, e a CLI só aceita `--simular`.
- **Backup** (`python -m src.comum.backup`): zip com manifesto e SHA-256, guarda os 10 mais recentes por ano, restauração segura com cópia de segurança antes. Nunca inclui senhas, documentos digitalizados, logs nem screenshots.
- Existem dados fictícios de 2025 para testar as telas (`python -m src.comum.dados_ficticios --ano 2025`).

---

## Configuração e credenciais

As credenciais ficam em `credenciais/.env` (fora do Git) e podem ser cadastradas pela tela **Configurações**, valendo na hora. O modelo completo está em [`.env.example`](.env.example). Principais variáveis:

| Variável | Para quê |
|---|---|
| `SERE_LOGIN` / `SERE_SENHA` | Acesso ao SERE |
| `PREMATRICULA_LOGIN` / `PREMATRICULA_SENHA` | Portal da pré-matrícula |
| `RCO_LOGIN` / `RCO_SENHA` | RCO (em branco = mesmo login do SERE) |
| `AUTO_SERE_ANO_BASE` | Fixa o ano letivo (sobrepõe a tela) |
| `AUTO_SERE_WORKDIR` | Base de trabalho alternativa |
| `AUTO_SERE_BACKUP_MANTER` | Quantos backups guardar (padrão 10) |
| `WHATSAPP_PROVEDOR` | `simulado` (padrão), `whatsplay`, `blake` ou `http` |
| `WHATSAPP_ENVIO_REAL` | Trava de envio real (só `1` envia) |

Preferências do usuário (pasta de digitalização, ano letivo, dados da escola, data de corte dos transferidos etc.) ficam em `config/config_usuario.json`; configuração fixa em `config/config.yaml`.

---

## Estrutura do projeto

```
Auto_sere/
├── src/
│   ├── web/              ← Flask + HTML/CSS/JS puro (app.py, api/, templates/, static/)
│   ├── automacao/        ← um módulo por automação (SERE, pré-matrícula, transferidos, pareceres...)
│   ├── relatorios/       ← análises, cruzamentos, mapeamento de pastas, máscara de dados
│   ├── servicos/whatsapp/← provedores e gerenciador de WhatsApp
│   ├── comum/            ← núcleo: paths, configuração, credenciais, registro de scripts, CLI, backup, ano letivo
│   └── launcher.py       ← abre o sistema como aplicativo no Windows
├── config/               ← config.yaml e config_usuario.json
├── credenciais/          ← .env e sessão do WhatsApp (nunca versionar)
├── dados/<ano>/          ← JSONs, pareceres e transferências do ano (dados sensíveis, fora do Git)
│   └── backup/           ← backups em zip
├── docs/                 ← WINDOWS, WHATSAPP, FLUXO_TRANSFERIDOS, NOVO_SCRIPT
├── docker/whatsapp/      ← gateway Docker do WhatsApp (opcional)
├── scripts/windows/      ← instalador e criação de atalho
├── logs/  locks/         ← gerados em execução
└── tests/                ← testes automatizados
```

Os caminhos nunca são fixos no código: tudo vem de `src/comum/paths.py`, da configuração e do `.env`. Mais detalhes da interface em [`src/web/README.md`](src/web/README.md) e da arquitetura em [`diagrama_de_funcionamento.md`](diagrama_de_funcionamento.md).

---

## Desenvolvimento

```bash
python -m pytest tests          # não precisa de PYTHONPATH
python -m compileall src/       # verificação de sintaxe
```
Os testes de interface usam o Chromium do Playwright e são pulados se ele não estiver instalado.

- **Novo script:** siga [`docs/NOVO_SCRIPT.md`](docs/NOVO_SCRIPT.md) (registro em `registro_scripts.py` e opções compartilhadas em `opcoes_execucao.py`).
- **Módulo que calcula `dados/<ano>` na importação:** inclua em `MODULOS_COM_ANO_FIXO` (`src/comum/ano_letivo.py`); `tests/test_ano_letivo_troca.py` falha se for esquecido.
- **Pacote para envio:** `gerar_zip.sh` (usa `git ls-files`) ou `backup_auto_sere.py` (caminho `C:\Auto_sere` fixo no script).
- `analisar_io_scripts.py` gera o `RELATORIO_IO.md` por análise estática dos scripts.

## Segurança e privacidade

- `.gitignore` bloqueia credenciais, sessão do WhatsApp, JSONs de `dados/`, digitalização, pareceres, screenshots, planilhas, logs e backups.
- Senhas nunca aparecem na tela, nos logs nem nos backups.
- O WhatsApp usa clientes **não oficiais** (risco de banimento do número): use um número dedicado da escola, nunca em massa. O envio real exige três travas. A alternativa oficial é a WhatsApp Business Cloud API.
- O sistema trata dados de alunos e servidores (LGPD): mantenha o computador e os backups em local protegido.

## Compatibilidade

Windows (uso principal, com Python embutido), Linux e WSL. O Chrome é necessário no Windows para o modo aplicativo; sem ele o sistema usa o Edge ou o navegador padrão.

## Segurança e acesso

O sistema exige login. O primeiro usuário (administrador) é criado na instalação; depois o administrador cadastra os demais em Configurações → Usuários e segurança. Como a senha é guardada, os perfis, o que fazer ao esquecer a senha e os limites da proteção estão em [`documentacao/Seguranca.md`](documentacao/Seguranca.md).

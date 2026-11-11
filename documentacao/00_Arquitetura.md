# Arquitetura

## Camadas

| Camada | Pasta | Papel |
|---|---|---|
| Interface | `src/web` | Flask + HTML/CSS/JS puro (sem framework de front). `app.py`, `api/rotas.py` (≈2,7 mil linhas, 49 rotas), `api/whatsapp.py`, `api/calendario.py`, `templates/`, `static/` |
| Registro de automações | `src/comum/registro_scripts.py` | Cada automação declara **recursos** (turma, situação, CGM, teste, erros, debug) e um **plano** (função + argumentos) |
| Opções comuns | `src/comum/opcoes_execucao.py` | Mesmas opções na tela e na linha de comando; seleção de alunos; prévia |
| Ponte assíncrona | `src/comum/execucao_gui.py` | Cada automação roda numa thread com event loop próprio; o progresso volta por callback |
| Automações | `src/automacao` | Um módulo por tarefa (Playwright) |
| Relatórios | `src/relatorios` | Análises, cruzamentos, mapeamento de pastas, máscara de dados, comparação de anos |
| Serviços | `src/servicos/whatsapp` | Provedores de WhatsApp, gerenciador, monitor, eventos |
| Núcleo | `src/comum` | `paths`, `configuracao`, `credenciais`, `escola`, `ano_letivo`, `backup`, `cli`, `logger`, `sere_*` |
| Persistência | `dados/<ano>/`, `config/`, `credenciais/`, `logs/`, `locks/` | Arquivos JSON/planilhas. **Não há banco de dados.** |

Regra de ouro: nenhum caminho é fixo no código. Tudo vem de `src/comum/paths.py`, da configuração do usuário e do `.env`.

## Ciclo de uma automação

1. A tela (ou a CLI) monta as **opções** a partir dos recursos que o script declarou.
2. `POST /web/api/automacoes/<chave>/previa` mostra o que seria processado (sem executar).
3. `POST .../executar` cria um **plano** e inicia a thread. A rota responde na hora.
4. A tela consulta `GET .../status` (log, progresso, estado). `POST .../cancelar` interrompe.
5. Se a automação precisa de algo do usuário no meio (ex.: código 2FA do RCO), usa `entrada_usuario.perguntar`; a tela
   responde por `POST .../resposta`.
6. Scripts que alteram o SERE têm `confirmar=True`: pedem confirmação com a prévia (`SIM` na CLI ou `--confirmo`),
   exceto no **modo de teste**.

## Automações registradas (34 chaves)

`analisa_sere`, `validar`, `documentos`, `limpeza`, `espec`, `aluno`, `gerar_chaves`, `rematricula`, `prematricula_completa`,
`transferidos_fila`, `transferidos_gerar`, `transferidos`, `pareceres_transferidos`, `pareceres_digitalizados`, `parecer_rco`, `parecer_planilha`, `parecer_fund`,
`avisos`, `sheets` (Google Sheets: `docs/GOOGLE_SHEETS.md`), `turmas`, `alunos`, `funcionarios`, `vinculos`, `sus`, `cep`, `termos`, `comprimir`, `compara_anos`,
`gerar_pastas`, `analisa_pasta`, `mapear_pastas`, `cruzamento`, `mascara`, `coleta_emails`, `backup`.

Para criar uma nova: `docs/NOVO_SCRIPT.md`.

## Opções comuns (`opcoes_execucao.py`)

Turma(s); matriculados e/ou transferidos (regra: o campo *Situação* de `turmas.json` contendo "matriculado" ou "transf");
lista de CGMs; **modo de teste** (processa só o primeiro aluno — *não é simulação*); reprocessar erros; debug.
`--simular` só mostra o que seria processado.

## Travas de segurança do servidor

- **Modo somente consulta** (`src/web/app.py`): quando o ano letivo aberto é anterior ao do calendário, um guarda recusa
  com 403 toda requisição que escreve em `/web/api/`. Liberado: trocar de ano, backup, conferir backup (`aplicar=false`),
  prévia e cancelar de automações, e o webhook do WhatsApp. Rotas novas já nascem bloqueadas.
- **Trava de execução simultânea**: hoje é **por processo**; o arquivo de lock em `locks/` é pendência (item 11q).
- **Segredos**: `credenciais/.env` e `credenciais/whatsapp_sessao/` fora do Git; senhas não aparecem em tela, log nem backup.

## Linha de comando

```bash
python -m src.comum.cli listar
python -m src.comum.cli SCRIPT --ajuda
python -m src.comum.cli SCRIPT [opções] --simular
```
Saída: 0 concluído · 1 falhou · 2 pedido inválido ou não confirmado. No ano em somente consulta, só `--simular` funciona.
`src/automacao/sere_2026.py --modo` é o caminho legado, com as mesmas regras.

## Interface

Telas: Painel, Turmas, Alunos, Pré-matrícula, Funcionários, Encaminhamentos do SUS, Alunos fora do raio, Calendário,
Documentos, WhatsApp, Automações, Configurações e a **1ª execução** (wizard). É um PWA (`static/sw.js`), aberto pelo
`launcher.py` como janela de aplicativo do Chrome (`--app`). A porta padrão é **8000** e deve ser fixa (o PWA instalado
depende da origem).

## Inicialização no Windows

`AUTO_SERE.bat`/atalho → `pythonw -m src.launcher`: se já há servidor (`GET /web/api/ping`), só abre a janela; senão sobe
o servidor sem console, espera responder e abre o Chrome. Um lock curto evita dois servidores em duplo clique.
`PARAR_AUTO_SERE.bat` encerra. Instalação: `INSTALAR_WINDOWS.bat` → `scripts/windows/instalar.ps1` (Python 3.12 próprio em
`runtime\python`, Playwright, atalho).

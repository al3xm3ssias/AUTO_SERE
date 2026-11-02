# PRÓXIMAS ETAPAS — AUTO SERE

Checklist vivo do desenvolvimento. Legenda: `[ ]` pendente · `[-]` em andamento · `[x]` concluído **e testado** · `[!]` bloqueado.
Onde o teste só pôde usar dados ou páginas simuladas (sem acesso ao SERE, SISREG, pré-matrícula e WhatsApp reais), isso está escrito na tarefa.

Última atualização: 2026-11-02.

## O que falta agora (resumo, 2026-11-02)

Visão rápida. O detalhe e o histórico de cada item estão nas seções abaixo (os números, como 3b e 11q, são os mesmos).

### A. Validar no ambiente real (maior risco)
Quase tudo foi testado só com navegador ou dados simulados.
- [!] **SERE:** coletas de Turmas, Alunos (básico e completo) e Funcionários; `vinculos` (RH e holerite); `sus`/SISREG; e uma execução real de cada automação migrada para o registro (item 11), com "Modo de teste".
- [!] **Transferidos:** emitir, assinar, baixar e enviar de verdade com um aluno real; leitura de QR com scans reais; `parecer_fund` completo no computador da escola e modelos dos demais anos.
- [!] **RCO:** `parecer_rco` (login, 2FA, botões, download) no site real.
- [!] **WhatsApp:** primeiro pareamento e envio com número real; testar `whatsplay` no Windows.
- [!] **Pré-matrícula e rematrícula:** BUG-PRE-001 (consulta por CPF pode ler o cadastro cancelado), conferência ao vivo da coleta e BUG-REM-001 (clique em "Confirmar" tratado como sucesso sem conferir a página).
- [!] **Tela Alunos (10h):** abrir com os `alunos.json` e `alunos_completo.json` reais e ver se aparecem divergências falsas (⚠).

### B. Funcionalidades pendentes
- [ ] **`avisos` — dois públicos novos** (uso real do e-mail, definido em 2026-11-02): (1) **escola de origem**, um e-mail por aluno que chega, pedindo a documentação; (2) **responsáveis de alunos que saem**, avisando sobre a transferência. Hoje só existem "todas as escolas/CMEIs" e "pais da pré-matrícula". Falta decidir de onde vem a escola de origem (não existe esse dado no sistema).
- [ ] `avisos`: reconhecer e-mail de escola escrito de forma disfarçada e mostrar "sem e-mail" na tela; responsável sem e-mail hoje só vai para o log.
- [ ] `avisos`: liberar o envio real (confirmação com prévia, intervalo e limite por lote, envio em segundo plano com pausa, registro de quem recebeu/falhou) e outros canais (WhatsApp, SERE).
- [ ] **7b** WhatsApp: fila de envio com limite diário, pausa, histórico e modelos.
- [ ] **3b** Backup automático ao fim das coletas.
- [ ] Decidir se os termos de ciência pulam quem tem `na_escola = false`.
- [ ] Transferidos: aluno transferido duas vezes no ano; painel só lê quem está em processo; mapeamento de turmas do QR sem tela.
- [ ] Script futuro: decodificar o QR dos pareceres e enviar ao SERE e por e-mail (falta escolher a biblioteca de leitura de QR).

### C. Limpeza, robustez e documentação
- [ ] **11q** Trava contra execução simultânea é por processo; criar arquivo de lock em `locks/`.
- [ ] Teste intermitente `test_ui_automacoes.py::test_funcionarios_e_vinculos...` (falha também no zip original).
- [ ] Modo consulta: desabilitar os botões de escrita das demais telas.
- [ ] Código duplicado (conferido em 2026-11-02):
  - `src/automacao/sere_api.py`, `sere_limpeza.py`, `sere_upload.py` e `sere_utils.py` são versões antigas **sem uso** (ninguém importa; o projeto usa as de `src/comum/`). Podem ser apagadas.
  - `src/comum/executar_{aluno,analisa,documento,espec,transferidos,validar}.py` são cópias idênticas das de `src/automacao/`. **As usadas são as de `src/automacao/`** (o `registro_scripts.py` importa de lá); as seis de `src/comum/` sobram. `executar_limpeza.py` só existe em `src/comum/` e é usado, fica.
  - `src/automacao/test_gerar_pastas.py` é idêntico a `tests/test_gerar_pastas.py`; o de `tests/` basta.
- [ ] Documentação desatualizada: `src/web/README.md` e `diagrama_de_funcionamento.md` dizem porta 5000 (a padrão é 8000); a tarefa "Bootstrap: criar_projeto.py" em `.vscode/tasks.json` aponta para arquivo que não existe; `backup_auto_sere.py` tem `C:\Auto_sere` fixo; `AUTO_SERE_MAPA.txt` (1 byte) e `src/web/templates/partials/help/*.html` (3 arquivos) estão vazios; `BUGS_CONHECIDOS.md` parou em 2026-10-30.
- [!] `config/config_usuario.json`: `setup_concluido` está `false` e a unidade escolar está sem `codigo`, `inep`, `telefone`, `email` e `responsavel`.
- [ ] Editar `config_usuario.json` à mão com o programa aberto só vale ao reiniciar (a faixa avisa e oferece "Aplicar agora").

### D. Decidido (não é mais pendência)
- **10g:** o wizard (1ª execução) fica só com o modo **básico** de Alunos, porque o completo demora mais; o completo segue em Automações → Alunos.
- **10h:** a tela Alunos une `alunos.json` e `alunos_completo.json` (feito em 2026-11-02).

## Análise do estado inicial (resumo)

- **Dados**: não há banco de dados; tudo é JSON em `dados/<ano>/` (+ `dados/calendario/`, `config/config_usuario.json`).
- **Já existia**: telas de Turmas, Alunos, Pré-matrícula, Funcionários, Calendário, Documentos; automações `sus` (`sisreg.py`) e `cep` (regra de raio em `src/comum/cep_api.py`, `RAIO_KM_PADRAO = 2.0`).
- **Faltava**: telas Encaminhamentos do SUS e Alunos fora do Raio (parciais vazios); backup (respondia 501); nada de WhatsApp.

## Tarefas

### Pedidas
- [x] **1. Pré-matrícula** — corrigido o que estava quebrado, sem implementação paralela
  - [x] 1a. `ImportError` ao rodar: o código importava `MATRICULA, SENHA_PRE`, mas `comum.credenciais` define `MATRICULA_PREMATRICULA`/`SENHA_PREMATRICULA`. Corrigido; sem credenciais, para com mensagem clara em vez de logar com dados de exemplo. Variáveis documentadas no `.env.example` (`PREMATRICULA_LOGIN`/`PREMATRICULA_SENHA`).
  - [x] 1b. **`pre_matricula.py` e `rematricula.py` não importavam no app** (`from comum import ...` só funciona com `PYTHONPATH=src`; o app usa `src.`): "Processo de pré-matrícula" e "Rematrícula" davam `ModuleNotFoundError`. Unificado em `src.comum`; testes ajustados e `tests/conftest.py` criado (não precisa mais de `PYTHONPATH`).
  - [x] 1c. Testes que dependiam de credenciais "de sandbox" ficaram independentes; `test_falha_na_gravacao...` apontava para `pm.json`, que não existe mais.
  - [x] 1d. **Tela de Pré-matrícula nunca era preenchida**: o id `tbody-prematricula` existia duas vezes (painel e tela) e o JS escrevia no errado. Renomeado o do painel; teste impede ids duplicados.
  - [x] 1e. BUG-PRE-002 (aluno que muda de turma): vale a última tentativa, o registro antigo fica guardado e marcado `substituido_por_nova_tentativa`; fila, contador do painel, contatos, pendentes e reconciliação ignoram o antigo. Testado com dados simulados.
  - [!] BUG-PRE-001 e conferência ao vivo da coleta: o site da pré-matrícula estava fora do ar em 2026-10-01; precisa do site real (ver `BUGS_CONHECIDOS.md`).
  - [x] 1f. Tela para cadastrar as credenciais da pré-matrícula: Configurações → "Salvar senha da Pré-matrícula" (`/configuracoes/prematricula`, grava `PREMATRICULA_LOGIN`/`PREMATRICULA_SENHA` em `credenciais/.env`).
- [x] **2. Encaminhamentos do SUS**
  - [x] 2a. `sisreg.py`: CPF com pontuação (`123.456.789-00`) era recusado como "inválido"; agora é normalizado. O resultado passa a guardar o CGM (liga o aluno à turma). Caminhos resolvidos na hora (não na importação).
  - [x] 2b. API `GET /encaminhamentos/lista`: uma linha por encaminhamento, com turma (por CGM, senão por nome sem acento), data e posição na fila. CPF não vai para a tela.
  - [x] 2c. Tela "Encaminhamentos do SUS" (menu, filtro por turma, busca, exportar CSV e botão "Atualizar dados" que abre a automação `sus`).
  - [x] 2d. Contador do painel contava também os registros "CPF inválido"; agora conta só quem tem encaminhamento.
  - [!] A consulta real ao SISREG só foi testada com navegador simulado; confirmar com uma execução real.
- [x] **3. Backup** — `src/comum/backup.py` (ver "Como executar" abaixo). Zip com manifesto e SHA-256, verificado antes de publicar; guarda os 10 mais recentes; **nunca** copia senhas/`.env`, documentos digitalizados, logs ou screenshots; restauração segura. Ligado à tela de Automações ("Backup dos dados").
  - [x] 3a. Tela para listar/restaurar backups: Configurações → Ano letivo (ver "Ano letivo" abaixo). Também continua pela linha de comando.
  - [ ] 3b. Backup automático ao fim dos passos de coleta (turmas, alunos, funcionários).
- [x] **4. Calendário** — corrigido
  - [x] 4a. Causa raiz: o `irPara()` do `app.js` não tinha ramo para `"calendario"`; `carregarCalendario()` nunca era chamada e a tela abria sem grade e sem dados.
  - [x] 4b. A busca de feriados nacionais na internet (até 8 s sem rede) segurava o desenho; agora desenha primeiro com os dados locais e completa depois (timeout do servidor 4 s). Troca de mês também é imediata.
  - [x] 4c. "Dia da Servente Escolar" estava em 31/05; o correto (e o teste `test_fixos_2026`) é 31/10.
- [x] **5. Alunos fora do Raio** — API `GET /fora-do-raio/lista` + tela, reaproveitando `alunos_fora_raio.json` e a regra de `cep_api.py` (nenhuma regra nova). Ordenada pela distância, com turma, raio e data da análise.
  - [x] 5a. O contador do painel usava `len()` do arquivo, que é um objeto `{metadados, alunos}` (sempre 2); corrigido.
- [x] **6. Funcionários** — a tela existia; completada
  - [x] 6a. A coluna "Cargo" saía sempre vazia (o coletor grava `funcao`, a rota lia `Cargo`); "Situação" não existia nos dados. Agora: Nome, Função, E-mail, Formação e Turmas.
- [x] **7. Teste do WhatsApp** — `src/servicos/whatsapp/` (ver "Como executar"). Provedor **simulado por padrão**; gateway HTTP (formato wwebjs-api) só com configuração; envio real exige três travas.
  - [!] O gateway HTTP foi testado só com servidor falso. Gateways baseados em whatsapp-web.js são não oficiais (risco de banimento do número); a alternativa oficial é a WhatsApp Business Cloud API.
  - [x] 7a. Tela **WhatsApp** (estado, QR Code, teste de envio, webhook) e passo do wizard — dois modos reais: **sem Docker** (`whatsplay`, Playwright; recomendado no Windows) e gateway Docker `blakegt/whatsapp-web-api-rest` (`blake`, `docker/whatsapp/`). Ver `docs/WHATSAPP.md`. Testado com whatsplay+Chromium reais contra um WhatsApp Web de mentira e com o gateway real **sem WhatsApp**; falta o primeiro pareamento/envio com número real (e testar no Windows).
  - [ ] 7b. Fila de envio com intervalo e limite diário, pausa/cancelamento, histórico e modelos de mensagem (ganchos prontos: `enviar_midia`, `eventos.registrar_tratador`).
  - [!] whatsplay: biblioteca de 1 mantenedor que depende do HTML do WhatsApp Web (versão fixada; revisar o código a cada atualização).
  - [!] Docker: a imagem usa `baileys 7.0.0-rc.9` (depreciado por falha de falsificação de mensagens recebidas): não automatizar decisões irreversíveis a partir de mensagens recebidas.

### Coletas na lista de Automações (pedido de 2026-10-08)
- [x] **10. Turmas e Alunos na lista de Automações** (antes só existiam como passos da 1ª execução)
  - [x] 10a. **Turmas** → `turmas.py` (`coletar_turmas_e_alunos_via_login`), grava `turmas.json`. Sem parâmetros.
  - [x] 10b. **Alunos**, com escolha do modo na tela (explicado abaixo do seletor):
    - **Básico** (padrão) → `alunos.py` (`coletar_alunos_via_login`): tela de consulta, grava `alunos.json`.
    - **Completo** → `alunos_completo.py` (`coletar_cadastro_completo_via_login`): tela de edição (~60 campos), salva aos poucos, registra erros, grava `alunos_completo.json`. Opção **Modo rápido** (só aparece no completo): pula quem foi coletado há menos de 2 meses.
  - [x] 10c. Os dois entram no topo do submenu e da lista de Automações. O modo completo explica o que fazer se faltar o `turmas.json`; modo desconhecido é recusado.
  - [x] 10d. Travas contra execução em conflito: a coleta do wizard e a da Automação que gravam o mesmo arquivo não rodam juntas (409 com explicação; no wizard o aviso aparece no painel de registros); o modo completo espera uma coleta de Turmas em andamento terminar.
  - [x] 10e. A tela de Automações ganhou caixa de marcar, campo que só aparece para certo valor de outro campo e texto de ajuda por opção (reutilizáveis por outras automações).
  - [x] 10f. O backup pedia uma "pasta de destino" que era ignorada (ele sempre vai para `dados/backup`); o campo foi removido.
  - [!] As coletas reais no SERE só foram testadas com versões simuladas (as funções `*_via_login` são trocadas por falsas nos testes).
  - [x] 10g. Decidido (2026-11-02): o passo "Alunos" do wizard (1ª execução) fica só no modo básico, porque o completo demora mais. O completo continua disponível em Automações → Alunos.
  - [x] 10h. A tela **Alunos** agora une `alunos.json` e `alunos_completo.json` pelo CGM (`src/comum/alunos_unificados.py`, rota `/alunos/lista`) numa **ficha única** por aluno: coluna "Cadastro" (Completo / Básico / Só completo), filtros "Cadastro completo" e "Só básico", resumo sob os filtros. A ficha mostra **todos os campos dos dois cadastros sempre**, agrupados (Identificação, Nascimento e origem, Documentação, Família e responsável, Contato, Endereço, Programas sociais, Perfil socioeconômico, Necessidades especiais, Observação, Escola), e **"—" onde nenhum dos dois tem o dado**: se um dos JSONs não existe, os campos dele aparecem como "—" (e a tela explica o que rodar). Campo vazio no básico é completado pelo completo (marca "· completo"); quando os dois têm valores diferentes, nenhum é sobrescrito e aparece ⚠ com a seção "Diferenças". O HTML da tela está todo em `partials/alunos_completo_cards.html`; `alunos_cards.html` só o inclui (nada foi apagado). Testado (`tests/test_alunos_unificados.py`, 13 testes) com dados simulados, nos três casos (os dois JSONs, só o básico, só o completo); falta olhar com os arquivos reais da escola.

### Registro de scripts e componentes compartilhados (pedido de 2026-10-10)
Guia: `docs/NOVO_SCRIPT.md`. Núcleo: `src/comum/opcoes_execucao.py` (opções) e `src/comum/registro_scripts.py` (registro).
- [x] **11. Componentes compartilhados** — turma (por ano ou específica), matriculados/transferidos, CGM, modo de teste, reprocessar erros e modo debug, iguais em todos os scripts, na tela e na linha de comando.
  - [x] 11a. **CGM**: aceita um por linha, vírgula, ponto e vírgula ou mistura; tira espaços, remove repetidos, valida (5 a 12 dígitos), mostra ao vivo o que será processado e quantos existem em `turmas.json`.
  - [x] 11b. **Prévia** "o que será processado" (ex.: "181 aluno(s) — 181 matriculado(s) — em 8 turma(s)") e **confirmação** antes de scripts que alteram o SERE (não aparece com o modo de teste).
  - [x] 11c. **Linha de comando e tela são a mesma coisa**: `--turma 5 --matriculados [--transferidos]`, `--cgm ...`; a tela monta os argumentos e um teste confere a ida e a volta. A CLI antiga continua (`--todos`, `--transferidos` sozinho, `--turma` sem valor = menu).
  - [x] 11d. Migrados para o registro: `analisa_sere`, `validar`, `documentos`, `limpeza`, `transferidos`, `rematricula`, `prematricula_completa`; e dois scripts que existiam só como código passaram a aparecer na tela: **Alunos por CGM** (`aluno`) e **Upload de um tipo de documento** (`espec`).
  - [x] 11e. `analisa_sere`: marcar turmas na tela só acrescentava `--turma` (menu interativo, que quebra sem console) e **ignorava a escolha**; agora a seleção é de fato usada. `--turma` sem valor, sem terminal, avisa em vez de travar.
  - [x] 11f. `rematricula` e `prematricula_completa` (da lista de automações) davam `ImportError` (as funções que a rota chamava não existem); agora chamam `rematricular_via_login` e `processo_completo_via_login`. ImportError virou mensagem amigável, não página de erro.
  - [x] 11g. `documentos` não conseguia rodar pela tela (exigia `idtipo`, que a tela não pedia); agora há a lista de tipos de documento.
  - [x] 11h. `cep`: a tela enviava um "CEP" que ninguém lia e o servidor usava raio 3,0 km (a regra do projeto é 2,0). Agora é o campo "Raio (km)" com padrão 2,0.
  - [x] 11i. Removidos campos de turma/pasta que o backend ignorava (`sus`, `transferidos`).
  - [!] Todos testados com as funções de coleta trocadas por falsas; falta uma execução real de cada no SERE.
  - [x] 11j. `sus` aceita turma e situação: consulta só os alunos escolhidos e **preserva** o resultado anterior dos demais (atualiza e remove quem não tem mais encaminhamento; reconhece registros antigos pelo CPF). O padrão passa a ser "matriculados de todas as turmas" (antes consultava todos os de `alunos.json`).
  - [x] 11k. As 12 automações que sobravam foram para o registro (turmas, alunos, sus, cep, termos, gerar_pastas, analisa_pasta, mapear_pastas, cruzamento, mascara, coleta_emails, backup) e a cadeia antiga de `if/elif` de `rotas.py` foi apagada: agora há **um único caminho de execução** (21 automações na época; **31 em 2026-11-02**, ver `python -m src.comum.cli listar`). Só as 6 "não implementadas" ficam de fora.
  - [x] 11l. Itens de menu lateral para `aluno`, `validar`, `espec`, `limpeza` e `prematricula_completa`; o submenu estava limitado a 1200 px e cortaria o fim da lista (agora 2400 px, com teste).
  - [x] 11m. **Linha de comando para todas as automações** (`python -m src.comum.cli`), em vez de refatorar o `sere_2026.py` (que só tem `input()` interativo): o executor lê o registro e dá a cada script as mesmas opções, validação e prévia da tela; `--simular` mostra o que seria processado sem executar; scripts que alteram o SERE pedem SIM ou `--confirmo` (não pedem com `--teste`). Saída 0/1/2. Os nomes vêm da lista da tela.
  - [ ] 11q. A trava contra duas execuções iguais ao mesmo tempo é por processo: tela e linha de comando (ou duas linhas de comando) podem rodar a mesma coleta juntas. Um arquivo de lock em `locks/` resolveria.
  - [x] 11n. `termos` não rodava pela tela (exigia `tema`, que ninguém perguntava); agora há o campo, a pasta de modelos é gravada na configuração e o **nome da escola vem da configuração central** (antes era o mais comum nos dados dos funcionários).
  - [x] 11o. Seletores de pasta que o script ignorava foram removidos (`gerar_pastas`, `cruzamento`, `mascara`: usam `dados/<ano>/`); `analisa_pasta` e `mapear_pastas` mantêm o seletor (gravam a pasta de digitalização).
  - [x] 11p. `gerar_pastas` criava sempre em `dados/<ano>/DIGITALIZAÇÃO`, ignorando a pasta escolhida na 1ª execução/Configurações (que é a que `analisa_pasta` e `mapear_pastas` leem). Agora usa a pasta escolhida; sem escolha, o padrão. **Se você já gerou pastas no padrão e depois escolheu outra pasta, rode o gerar_pastas de novo ou mova as pastas.**
  - Nota: a aba "Configuração" do `analisa_sere` deixou de listar `--turma` e `--transferidos` (agora são escolhidas na tela de execução); uma flag antiga guardada com esses nomes é ignorada.

### Credenciais e Pareceres do Infantil (pedido de 2026-10-19)
- [x] **Credenciais em Configurações** (gravam em `credenciais/.env` e valem na hora, sem reiniciar; a senha nunca volta para a tela): pré-matrícula (`/configuracoes/prematricula`), Gmail — e-mail + senha de app de 16 letras, no formato `btxq xxxx xxxx xxxx` (`/configuracoes/gmail`) — e RCO (`/configuracoes/rco`; por padrão usa o mesmo login e senha do SERE).
- [x] **`parecer_rco` (Pareceres infantil)**: portado de `gerar_pareceres_infantil.py` para `src/automacao/parecer_rco.py` e registrado em `registro_scripts.py`. Baixa do RCDIG os pareceres do Infantil IV/V (matriculados). Campos na tela: bimestre (2º/4º), modo teste (1 aluno) e "Mostrar o navegador". PDFs em `dados/<ano>/PARECERES INFANTIL/<N>º Bimestre/<turma>/` (ou na pasta definida em `AUTO_SERE_PARECERES_INFANTIL_DIR`).
- [x] **Perguntas no meio da execução** (`src/comum/entrada_usuario.py`): o código 2FA que o RCO manda por e-mail é pedido numa caixa na tela (`/status` devolve `pergunta`, `/resposta` entrega); na linha de comando vira `input()`.
- [!] `parecer_rco`: testado só com navegador simulado. Falta rodar com o RCO real (login, 2FA, nomes dos botões e download) — se o site mudou desde o script original, ajustar os seletores em `parecer_rco.py`.
- [x] **`parecer_fund` (Pareceres do Fundamental)**, `src/automacao/parecer_fund.py`: o modelo Word (.docx) é enviado em Configurações → Modelos de parecer e ligado a uma ou mais turmas; `dados/MODELO/controle_modelos.json` guarda a ligação turma → arquivo. A automação gera um .docx por aluno em `dados/<ano>/PARECERES/<turma>/<nº da chamada> - <nome>.docx`, troca `$ESCOLA`, `$ALUNO`, `$TURMA` (e `$ANO`, `$CGM`, `$CHAMADA`) e põe no FIM um QR code de 150x150 px com o texto `AUTOSERE|PF|<ano>|<CGM>`. Parecer que já existe não é sobrescrito, a menos que se marque "Substituir". Base das pastas: `dados/`, ou `AUTO_SERE_PARECERES_BASE`.
- [x] **`avisos` (Mandar avisos) — comunicados oficiais por e-mail, só em modo de teste** (`src/automacao/avisos.py`): público **escolas** (escolas e CMEIs de `escolas_completas.json`, vindos da Coleta e-mails, sem a própria escola, com filtro por tipo e por nome) e público **pais** (responsáveis de `pre_matricula.json`, um e-mail por responsável; matriculados por padrão, ou aguardando, ou ambos; nunca cancelados). Modos: **simular** (lista quem receberia, mostra a prévia e grava o registro em `dados/<ano>/AVISOS/`) e **teste** (envia UM e-mail só para o endereço de teste, com `[TESTE]` no assunto). No teste das **escolas**, o e-mail vai para a **escola fictícia ESCOLA MUNICIPAL TESTE DA SILVA** (`ESCOLA_TESTE` em `avisos.py`), com o texto montado como uma escola real o receberia, e funciona mesmo sem a lista de escolas coletada; a escola fictícia nunca entra na lista real. Marcadores: `$ESCOLA $ANO $DATA` + `$ESCOLA_DESTINO` (escolas) ou `$RESPONSAVEL $ALUNO $TURMA` (pais).
- **`avisos`: o uso real do e-mail** (definido em 2026-11-02): (1) escrever **para a escola de origem**, na hora da transferência, pedindo a documentação de aluno que está vindo; (2) avisar os **responsáveis de alunos que estão saindo**. Os dois públicos de hoje (todas as escolas/CMEIs e pais da pré-matrícula) não cobrem isso.
  - [ ] Público **escola de origem**: um e-mail por aluno que chega, para uma escola escolhida, com nome, CGM e série do aluno e a lista de documentos pedida. Não existe no sistema o dado "escola de origem do aluno"; definir de onde vem (digitar na hora, escolher na lista de `escolas_completas.json` ou campo no cadastro).
  - [ ] Público **responsáveis de quem sai**: destinatários de `transferidos.json` / fila de transferidos, com o e-mail do responsável (`alunos.json` / `alunos_completo.json`).
  - [ ] E-mail de escola escrito de forma disfarçada no site (ex.: "nome [arroba] dominio") não é reconhecido: a escola de origem ficaria sem destinatário. Reconhecer as variações comuns e, quando falhar, mostrar "sem e-mail" na tela, não só no log.
  - [ ] Responsável sem e-mail: hoje só vai para o log; para quem sai, mostrar na tela e oferecer outro caminho (WhatsApp ou aviso impresso).
  - [ ] **Liberar o envio real** (hoje o modo "enviar" é recusado de propósito): confirmação com a prévia, intervalo entre e-mails e limite por lote (o Gmail limita o envio diário), envio em segundo plano com pausa/cancelamento e registro de quem recebeu e de quem falhou, para retomar sem repetir.
  - [ ] Outros canais: WhatsApp (o provedor já existe em `src/servicos/whatsapp`) e SERE; o campo "Canal" da tela já está pronto.
  - [ ] Confirmar se o público em massa "todas as escolas/CMEIs" ainda é útil.
- [x] **`funcionarios` (Funcionários / Servidores) na lista de Automações**: a coleta que consulta os funcionários no SERE (`servidores.py`) só existia como passo da 1ª execução, embora a tela de Funcionários mandasse "executar pelo menu Automações". Agora tem entrada própria: modo **básico** (só a lista → `funcionarios.json`) ou **completo** (cadastro de cada um pelo CPF → `funcionarios_completo.json`), com a opção "Atualizar a lista antes" (sem ela, o completo reaproveita a lista já salva). A tela recebe só um resumo (modo, total, arquivo), não os cadastros.
  - [x] **Correção grave**: `servidores.py` e `funcionarios.py` **não importavam** (`navegar_censo_escolar` só existia numa cópia sem uso de `sere_api.py`), então a coleta de funcionários, inclusive o passo da 1ª execução, nunca rodava. A função voltou para `src/comum/sere_api.py` (a que o projeto importa), com `navegar_relatorios` igual ao que era.
  - [x] Falha de login no SERE agora vira ERRO na tela (antes devolvia lista vazia e terminava "com sucesso"); o navegador é fechado também em erro/cancelamento.
  - [!] Testado só com navegador simulado; a navegação e a leitura das telas do SERE (Censo Escolar → Funcionário/Docente) ainda não rodaram com o SERE real neste projeto.
  - [x] **Modo completo salva aos poucos** (2026-11-02, `servidores.py`): grava `funcionarios_completo.json` a cada 5 cadastros (`SALVAR_A_CADA`), com troca atômica do arquivo. Enquanto roda, o arquivo **não encolhe**: quem ainda não foi consultado mantém o registro da coleta anterior; só ao terminar fica exatamente o que foi coletado agora (como sempre foi). Se for **cancelada, der erro ou o programa cair no meio**, salva o que já tinha, escreve no log "⚠️ A coleta completa de funcionários foi interrompida…" (quantos foram salvos, quantos ficaram sem atualizar) e grava `funcionarios_completo_progresso.json` (sem CPF, só nomes). A tela **Funcionários** mostra um aviso âmbar "Coleta incompleta" enquanto esse estado for de coleta interrompida; some quando uma coleta completa termina. Testado (`tests/test_funcionarios_completo_parcial.py`, 7 testes) com página e consulta simuladas. Ainda não retoma de onde parou: rodar de novo refaz todos.
  - [x] `funcionarios_matriculas.json` (matrícula/`numcad`, lido pelos termos): agora é gerado pela automação **Vínculos dos funcionários** (abaixo). Os campos `numcad`/`nomemp` vêm do RH da Prefeitura, não do SERE.
  - [ ] Limpeza: ver "Código duplicado" no resumo do topo (as quatro `sere_*.py` de `src/automacao/` são antigas e sem uso).
- [x] **`vinculos` (Vínculos dos funcionários)** — fusão de `servidores.py` + `coleta_servidores.py` + `capturar_matriculas.py` + `mapa_escriturarios.py` em `src/automacao/funcionarios_vinculos.py`: lista do SERE × servidores do RH (por nome, exato ou abreviado) → matrícula; o que não está entre os servidores recebe a flag **terceirizado** (`lista_rh` se consta na lista de terceirizados do RH, `nao_consta_no_rh` por inferência); para cada servidor casado, o **holerite** do mês confirma que o local de trabalho é esta escola (`na_escola`); homônimos são desempatados pelo holerite. Grava `funcionarios_matriculas.json` no formato antigo + campos novos. Ajustes à mão em `funcionarios_ajustes.json`. A tela de Funcionários mostra o selo "Terceirizado" / "Outro local", o filtro "Vínculo" e os cartões Terceirizados / A revisar.
  - [!] Só testado com respostas simuladas: o endpoint de RH estagiários (`…/estagiarios/1`) foi deduzido por analogia, e a leitura do holerite depende do layout atual do site do RH (posição dos campos).
  - [x] **Modos de consulta** (campo "Modo de consulta" da automação, `--modo` na CLI): **1. `sere`** (só refaz a lista do SERE), **2. `vincular`** (SERE × RH por nome → matrícula, **nome do cargo** e **data de admissão** de cada matrícula, sem holerite), **3. `homonimos`** (só quem tem mais de uma matrícula com o nome, ou só o nome/CPF de `--so-nome`: consulta o holerite de cada matrícula e vê qual está lotada aqui) e **`completo`** (o de sempre, padrão). Quem não é verificado no modo 3 mantém o resultado já gravado, desde que as matrículas do RH sejam as mesmas.
  - [x] **Duas matrículas (20h + 20h, dois concursos)**: se as duas estão lotadas na escola, ficam as duas (com cargo e admissão de cada uma) e a pessoa não vai para a revisão; só nome com até 2 palavras ainda pede conferência. Matrícula em outro local vai para `vinculos_descartados` com o local do holerite e o motivo. Cargo/admissão vazios no RH são completados pelo holerite. A tela de Funcionários mostra cargo, admissão e as matrículas, e tem o filtro e o cartão "Duas matrículas".
  - [!] Modos testados só com RH e holerites simulados (como o restante de `vinculos`). Um professor com a 2ª matrícula em outra escola cai no mesmo caso de homônimo: o sistema descarta a de fora e avisa na observação, mas sem CPF no RH não há como saber se é a mesma pessoa.
  - [ ] Decidir se os termos de ciência devem pular quem tem `na_escola = false` (hoje usam todo `numcad` encontrado, como antes).
  - [ ] As consultas de holerite respeitam a pausa de 5 s do original: ~80 servidores levam uns 7 min na 1ª vez (as seguintes usam o cache de resultado).
- [ ] **Script futuro**: decodificar o QR dos pareceres (usar `parecer_fund.ler_payload_qr`, que devolve ano e CGM) e enviar ao SERE e por e-mail. Falta escolher a biblioteca de leitura de QR (não está no requirements).
- [!] `parecer_fund`: conferido com o modelo real do 1º ano (9 páginas, QR legível de 72 a 200 dpi), mas ainda não com o fluxo completo no computador da escola; os modelos dos demais anos podem trazer marcadores que o Word partiu de outro jeito (a troca já trata marcador partido em pedaços).

### Ano letivo (pedido de 2026-10-24)
- [x] **Configurar o ano letivo** — Configurações → **Ano letivo**: mostra o ano em uso e o do próximo início, lista os anos que têm pasta em `dados/` (com nº de arquivos, backups e selo "fictício"), "Usar este ano" e "Voltar ao automático" (ano do calendário). Fica em `config/config_usuario.json` (`ano_letivo`). Ordem de quem manda: variável `AUTO_SERE_ANO_BASE` > escolha da tela > calendário (`paths.ano_atual()`; a tela avisa se o ambiente fixa o ano).
  - [x] **A troca é imediata, sem reiniciar** (pedido de 2026-10-25) — `src/comum/ano_letivo.py::trocar_ano`. Desafio: 18 módulos fixam `dados/<ano>` na importação (`_DADOS = dados_ano_atual()` e derivados), então mudar só o ano misturaria dois anos. Solução: grava a escolha, muda o ano do processo, descarrega esses módulos (e `rematricula_sere`, que importa um deles) de `sys.modules` **e apaga a referência que o pacote pai guarda** (senão `from src.automacao import turmas` devolveria o módulo velho) e os importa de novo na hora; se algum falhar, a troca é **desfeita** (ano, configuração e módulos voltam). A tela mostra a tela de carregamento e recarrega os dados. Só recusa (409) com automação em execução ou com o ano fixado por `AUTO_SERE_ANO_BASE`. Ao trocar, limpa o que a tela guardava do ano anterior (resultado/log das execuções, atividade do assistente).
  - [x] **Guardas contra esquecimento**: `tests/test_ano_letivo_troca.py` varre o código e FALHA se um módulo novo passar a calcular o ano na importação sem estar em `MODULOS_COM_ANO_FIXO`, ou se alguém importar um deles logo ao carregar sem estar em `MODULOS_QUE_DEPENDEM`. Ao criar um script que usa `dados_ano_atual()` fora de função, adicione-o à lista.
  - [ ] Editar `config/config_usuario.json` à mão com o programa aberto só vale ao reiniciar; a faixa avisa e oferece "Aplicar agora".
- [x] **Voltar os dados de um ano** — mesma tela: escolhe um backup (cada um é de UM ano), "Conferir" (extrai numa pasta, não altera nada) ou "Restaurar os dados…" (pede confirmação, faz cópia de segurança antes, repõe só os dados do ano por padrão). Correções no `backup.py` que isso exigiu:
  - [x] O backup guarda o ano e a restauração repõe na pasta **desse ano**. Antes, um backup de 2025 restaurado em 2026 gravava os dados de 2025 por cima da pasta de 2026.
  - [x] Cópia de segurança antes de restaurar é do ano que será sobrescrito; se a pasta do ano está vazia, restaura sem ela.
  - [x] "Só os dados do ano" não mexe em configuração nem calendário; restaurar a configuração não desfaz a escolha de ano letivo.
  - [x] A retenção (10 mais recentes) vale **por ano**: backups novos de 2026 não apagam os de 2025. Backup de um ano sem dados é recusado (antes saía um zip só com config e calendário).
  - [x] Restaurar o **ano em uso** com automação rodando é recusado; restaurar outro ano pode.
  - Linha de comando: `python -m src.comum.backup --ano 2025` (backup de outro ano) e `... --restaurar ARQ.zip --aplicar --so-dados`.
- [x] **Dados fictícios de 2025** para testes — `src/comum/dados_ficticios.py`, pronto em `dados/2025/` (8 turmas, 57 alunos, 14 funcionários com servidor/terceirizado/estagiário e um holerite em outro local, 14 na pré-matrícula, `_DADOS_FICTICIOS.txt`) + um backup de 2025 em `dados/backup/`. No formato real: as telas Painel, Alunos, Funcionários e Pré-matrícula leem esses arquivos. Nomes sorteados, CPFs com dígitos verificadores errados, e-mails `@example.com`, telefones `(00) 00000-xxxx`. Refaz pela tela (Criar dados fictícios) ou `python -m src.comum.dados_ficticios --ano 2025 [--backup]`. Nunca escreve por cima de dados reais nem no ano em uso (a menos que já seja fictício).
  - Não gerados: documentos digitalizados, `documentos-alunos.json`, `transferidos.json`, `alunos_fora_raio.json`.
  - Para testar: Ano letivo → "Usar este ano" em 2025 (troca na hora, em modo consulta) → conferir as telas → voltar a 2026 → estragar um arquivo de `dados/2025` → "Restaurar os dados…" → "Usar este ano" em 2025.
- [x] **Modo somente consulta** (pedido de 2026-10-25): quando o ano em uso é **anterior ao do calendário** e foi escolhido na tela (`paths.somente_consulta()`), o programa só permite VER:
  - **Selo no topo, ao lado do perfil**: "Ano letivo 2025 · somente consulta" (âmbar); em modo normal mostra só "Ano letivo 2026". A lateral ("Auto SERE · 2025") também mostra o ano em uso.
  - **Faixa de aviso** no alto de toda tela, com o botão "Voltar ao ano atual…" (abre Configurações → Ano letivo). Também avisa, em qualquer modo, quando a configuração aponta para um ano diferente do que está em uso (botão "Aplicar agora").
  - **Tela de carregamento** "Ano letivo 2025 restaurado — somente consulta" ao abrir o programa nesse ano (uma vez por sessão); depois de restaurar os dados do ano em uso ("Dados de 2025 restaurados", recarrega as telas) e **durante a troca de ano** ("Carregando o ano letivo 2025…", depois "Ano letivo 2025 restaurado", e a página recarrega sozinha).
  - **Trava no servidor** (`src/web/app.py`): um guarda recusa (403, mensagem em português) TODA requisição que escreve em `/web/api/` — executar automações e passos da 1ª execução, credenciais, escola, calendário, WhatsApp, modelos de parecer, restaurar de verdade, dados fictícios. Liberado: trocar de ano (o caminho de volta), fazer backup, conferir um backup (`aplicar=false`), prévia e cancelar de automações, e o webhook de entrada do gateway do WhatsApp. Rotas novas já nascem bloqueadas. A linha de comando também recusa executar (só `--simular` funciona).
  - O botão "Executar" das automações fica desabilitado; no painel Ano letivo, "Restaurar os dados" e "Criar dados fictícios" também.
  - **Não vale** quando o ano é fixado por `AUTO_SERE_ANO_BASE` (é o caminho de quem precisa trabalhar num ano "atrasado", ex.: janeiro/fevereiro com o ano anterior ainda aberto no SERE) nem para ano igual ou futuro ao do calendário.
  - [ ] Os botões de escrita das demais telas continuam clicáveis em consulta (o servidor recusa e a tela mostra a mensagem); desabilitá-los um a um não foi feito.
  - [ ] Calendário letivo, modelos de parecer, credenciais e configuração NÃO são por ano (ficam em `dados/calendario`, `dados/MODELO`, `credenciais/` e `config/`): os mesmos em qualquer ano. A pasta de digitalização padrão é por ano (`dados/<ano>/DIGITALIZAÇÃO`), mas uma pasta escolhida à mão vale para todos os anos.
- [!] A tela de Ano letivo, o selo, a faixa e a tela de carregamento têm testes no Chromium (3 testes de navegador) e foram conferidos em captura de tela; nunca rodaram com o SERE real nem com os seus dados de verdade.
- [ ] Teste de tela intermitente (já presente no Auto_sere.zip que você enviou): `tests/test_ui_automacoes.py::test_funcionarios_e_vinculos_estao_no_menu_...` às vezes falha porque o rótulo "Sistema" do menu fica por cima do item "Vínculos" no clique; passa na maioria das vezes.

### Fluxo dos transferidos (pedido de 2026-10-27) — visão geral em `docs/FLUXO_TRANSFERIDOS.md`
- [x] **1. Fila de transferidos**: `turmas.py` → `turmas.json` → `fila_transferidos.json` (temporária, regerada a cada coleta) → `transferidos.json` (controle). `src/automacao/fila_transferidos.py`. Identidade do aluno: nome + data de nascimento; a chamada distingue o cadastro; quem foi transferido e voltou conta uma vez, como ativo.
- [x] **2. `DATA_CORTE` configurável** (Configurações → "Data de corte dos transferidos" e campo em cada tela do fluxo). Vale **a partir** da data, inclusive (antes o dia do corte contava como pré-corte). Padrão: 22/06 do ano letivo.
- [x] **3. Pastas únicas** `dados/<ano>/TRANSFERENCIAS/{PROCESSAMENTO DE PARECERES, PARECERES, HISTORICO, GUIA DE TRANSFERENCIA}` (`src/comum/pastas_transferencias.py`), usadas por quem gera e por quem envia; o envio ainda procura nas pastas antigas da digitalização.
- [x] **4. Quatro itens no menu lateral**, cada um com **Simulação** (já marcada nos que mexem no SERE ou nos arquivos): Fila de transferidos · Gerar guia e histórico · Enviar transferidos ao SERE · Pareceres dos transferidos.
- [x] **5. Pareceres numa rotina só** (`pareceres_transferidos.py`): lê o QR → arquiva em `PARECERES/<turma>/NN-NOME.pdf` → comprime se passar do limite (original guardado) → marca no controle → envia ao SERE. Turma do QR resolvida por palavras, sem assumir nomes "Integral"; variações extras em `config_usuario.json` (`mapeamento_turmas_qr`).
- [x] **6. Documento da escola × de outra escola** (`docs_da_escola`): só conta como nosso o documento cujo "gerado em" bate com o `emitido_em` que o processo registrou; o de outra escola nunca é reaproveitado, baixado nem assinado. Corrigidos por isso: (a) com a assinatura da diretora pendente, cada execução emitia outro documento; (b) a assinatura podia recair em documento de outra escola; (c) o **download gravava `anexado_em`** e o envio, achando que já estava anexado, pulava quando o slot do SERE tinha documento de outra escola — agora o download grava `baixado_em`; (d) o envio compara o arquivo que está no slot (`decidir_envio_slot`) e só pula o que é comprovadamente nosso.
- [x] **6b. "Gerar guia e histórico" com ações marcadas separadamente**: Gravar · Alterar (caixa de texto, só aparece com Alterar marcado; guarda o último texto) · Emitir · Assinar (só o usuário logado, e confere o Diretor) · Imprimir, mais o seletor Documentos. Testado também no navegador (`tests/test_ui_transferidos.py`).
- [x] **7. Quem foi transferido e voltou à escola não é refeito** (o processo é feito uma vez só).
- [x] **Mescla com a troca imediata do ano letivo** (2026-10-29): o fluxo foi construído sobre uma versão em que a troca de ano só valia ao reiniciar. Na mescla vale a troca imediata (`ano_letivo.py`, rota `/configuracoes/ano-letivo`, `app.js`); do fluxo entraram só as telas, rotas, registro de scripts e módulos de transferidos. Os módulos novos (`fila_transferidos`, `pareceres_transferidos`, `pastas_transferencias`) calculam `dados/<ano>` dentro de funções, então não precisam entrar em `MODULOS_COM_ANO_FIXO` (o teste-guarda confere).
- [x] **Mescla das duas linhas de trabalho** (2026-10-31): base = `AUTO_SERE-master` (troca imediata do ano letivo); do `Auto_sere_mesclado` entraram o 6b acima (`processo_transferidos.etapas_por_acoes`, `registro_scripts`, `configuracao.observacao_historico`, `app.js`), o comunicado de matrícula por WhatsApp (`comunicado_matricula.py`, ligado a `pre_matricula.py`) e a correção BUG-PRE-003 (`rotas._aluno_na_fila_prematricula`). Mantido do master: `ano_letivo.trocar_ano`, rota `/configuracoes/ano-letivo`, "Aplicar agora" e a fixture de `test_documentos_da_escola.py`.
- [x] **Consolidação final dos 4 zips** (2026-11-01): `Auto_sere_mesclado_final` ficou como base por ser superconjunto de `AUTO_SERE-master`, `Auto_sere` e `Auto_sere_mesclado (3)` (diferenças só de CRLF/LF, mais os imports `Optional` em `sere_2026.py` e `date` em `configuracao.py`, `.gitignore` de PARECERES/screenshots e `.gitattributes`). Fora do projeto: `dados/2026/PARECERES`, `screenshots`, `logs/*.txt` e o `Auto_sere.zip` aninhado no master (cópia antiga).
- [!] Emitir, assinar, baixar e enviar de verdade só foram testados com o estado que o SERE deixaria (decisões, pastas, simulações e o encadeamento ponta a ponta em `tests/test_ponta_a_ponta_transferidos.py`); falta uma execução real com um aluno (use "Modo de teste"). A leitura de QR foi testada só com PDFs gerados, não com scans reais.
- [ ] Aluno transferido duas vezes no ano: a segunda saída que precise de documentos novos não é tratada (o registro guarda a mais recente e lista a anterior em `transferencias_anteriores`).
- [ ] A tabela "Transferidos" do painel lê só o `transferidos.json` (quem está em processo): o cartão "Total" não é o total de transferidos da escola, e não mostra quem é pré-corte nem quem retornou.
- [ ] Mapeamento de turmas do QR: sem tela, só pelo arquivo de configuração.

### Melhorias fáceis feitas
- [x] **8.** `garantir_diretorios_runtime()` agora cria `credenciais/` (o `test_ambiente` falhava numa instalação limpa).
- [x] **9. Tabelas genéricas**: filtro livre, busca (sem diferenciar acento/caixa), seletor de turma e "Exportar" (CSV para Excel) existiam na tela, mas não estavam ligados. Texto vindo dos sites agora é escapado (antes ia direto como HTML). Removida a coluna "Ação" cujos botões não faziam nada.
- [x] Mensagens de "tela vazia" dizem o que fazer; resumo (raio, data da consulta) acima das tabelas.

### Depois (não iniciadas)
- [ ] BUG-REM-001 (conferir o sucesso da rematrícula na página): precisa confirmar no SERE real.
- [ ] Primeiro pareamento e envio reais do WhatsApp (gateway Docker já integrado; ver `docs/WHATSAPP.md`).
- [x] ~~Registro de scripts com componentes compartilhados~~ (feito: item 11).

## Como executar

### Backup
- **Pela tela:** Automações → "Backup dos dados".
- **Pela linha de comando** (na pasta do projeto, com o Python do projeto):
  - `python -m src.comum.backup` — cria um backup agora (em `dados/backup/backup_AAAA-MM-DD_HHMMSS_mmmmmm.zip`).
  - `python -m src.comum.backup --listar` — lista os backups.
  - `python -m src.comum.backup --restaurar ARQUIVO.zip` — só **extrai para conferência** em `dados/backup/restaurado_.../`; nada do sistema é alterado.
  - `python -m src.comum.backup --restaurar ARQUIVO.zip --aplicar` — repõe os dados de verdade (confere o backup antes e faz uma cópia de segurança do estado atual).
- No Windows instalado: `runtime\python\python.exe -m src.comum.backup`.
- Quantos manter: variável `AUTO_SERE_BACKUP_MANTER` (padrão 10).
  - `python -m src.comum.backup --ano 2025` — backup dos dados de **outro ano** (sem trocar o ano em uso); `--restaurar ARQUIVO.zip --aplicar --so-dados` repõe só os dados do ano. Os dados voltam para a pasta do ano **do backup**.
- **Fora do backup, de propósito:** `credenciais/` (senhas), `DIGITALIZAÇÃO/` (documentos dos alunos), logs, screenshots. Para guardar a digitalização, copie essa pasta à parte.

### Qualquer automação pela linha de comando (agendador de tarefas, .bat)
- `python -m src.comum.cli listar` · `python -m src.comum.cli SCRIPT --ajuda` (opções daquele script)
- `python -m src.comum.cli validar --turma "3º Ano Integral" --simular` (só mostra: "44 aluno(s) — 44 matriculado(s) — em 2 turma(s)")
- `python -m src.comum.cli analisa_sere --turma 5 --matriculados --transferidos`
- `python -m src.comum.cli aluno --cgm 1234567890,1234567891 1234567892 --confirmo`
- `python -m src.comum.cli alunos --modo completo --rapido` · `python -m src.comum.cli backup` · `python -m src.comum.cli sus --turma 5`
- No Windows instalado: `runtime\python\python.exe -m src.comum.cli ...`. Saída: 0 concluído · 1 falhou · 2 pedido inválido/não confirmado.
- Scripts que alteram o SERE perguntam (SIM) ou exigem `--confirmo`; com `--teste` não perguntam. As flags da aba "Configuração" da tela não valem aqui.

### Opções compartilhadas na linha de comando (analisa_arquivos_sere)
- `python -m src.relatorios.analisa_arquivos_sere --turma 5 --matriculados`
- `... --turma 5 --matriculados --transferidos` · `... --turma "3º Ano Integral" "5º Ano Integral A" --transferidos`
- `... --cgm 1234567890,1234567891 1234567892` (CGMs específicos)
- Compatíveis com o que já existia: sem opções = só matriculados; `--todos`; `--transferidos` sozinho; `--turma` sem valor abre o menu (só com terminal).

### Turmas e Alunos
- **Pela tela:** Automações → Turmas / Alunos (escolha **Básico** ou **Completo**). Ordem recomendada: Turmas → Alunos.
- **Pela linha de comando** (não há `main` nesses módulos; chame a função):
  - `python -c "import asyncio; from src.automacao.turmas import coletar_turmas_e_alunos_via_login as f; asyncio.run(f())"`
  - básico: `python -c "import asyncio; from src.automacao.alunos import coletar_alunos_via_login as f; asyncio.run(f())"`
  - completo: `python -c "import asyncio; from src.automacao.alunos_completo import coletar_cadastro_completo_via_login as f; asyncio.run(f(modo_rapido=False))"`
- Precisam de `SERE_LOGIN`/`SERE_SENHA` em `credenciais/.env` (a 1ª execução já pergunta).

### Teste do WhatsApp (seguro)
- `python -m src.servicos.whatsapp.teste` — mostra o provedor configurado, consulta o estado da conexão (somente leitura) e passa uma mensagem de exemplo pelo provedor simulado. **Nenhuma mensagem real é enviada.**
- Configuração (em `credenciais/.env`, ver `.env.example`): `WHATSAPP_PROVEDOR` (`simulado` — padrão —, `blake` — gateway Docker, usado pela tela — ou `http`), `WHATSAPP_API_URL`, `WHATSAPP_API_KEY`, `WHATSAPP_SESSAO`.
- Para enviar **uma** mensagem real de teste (as três travas são obrigatórias): `WHATSAPP_PROVEDOR=http`, `WHATSAPP_ENVIO_REAL=1` e o parâmetro `--enviar-para 42999998888 --confirmo-envio-real`. O número só aparece mascarado nas mensagens do teste.

### Testes
- `python -m pytest tests` (não precisa mais de `PYTHONPATH`). Os testes de interface usam o Chromium do Playwright e são pulados se ele não estiver instalado.

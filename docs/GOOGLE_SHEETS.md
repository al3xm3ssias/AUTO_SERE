# Google Sheets no AUTO SERE

Cria e atualiza a planilha das turmas (uma aba por turma) a partir do `turmas.json`. Substitui o antigo `sheets_sync` /
`atualiza_planilha.py`: mesma regra de negócio, agora dentro do sistema (tela **Automações → Planilha no Google Sheets**
e linha de comando).

| Arquivo | Papel |
|---|---|
| `src/comum/google_auth.py` | Credenciais: OAuth ou conta de serviço, token, caminhos (`credenciais/`) |
| `src/comum/google_sheets.py` | Funções genéricas: `verificar_planilha`, `criar_planilha`, `ler_intervalo`, `atualizar_intervalo(s)`, `anexar_linhas` |
| `src/automacao/sincroniza_sheets.py` | Regra das turmas: `turmas.json` → abas (`sincronizar_turmas`, `executar_planilha_google`) |
| `registro_scripts.py` (`sheets`) | Opções da tela/CLI; a planilha vem do gerenciador (`planilhas_gerenciador.py`), não da configuração |

## 1. Escolha da autenticação

* **OAuth 2.0 "Aplicativo para computador" (recomendado).** O programa age como a SUA conta Google: a planilha criada
  aparece no seu Drive e as que já são suas funcionam sem compartilhar nada. Abre o navegador uma vez.
* **Conta de serviço.** Sem navegador (bom para agendador), mas só enxerga planilhas **compartilhadas** com o e-mail do
  robô (`client_email` do JSON). Planilha criada por ele pertence ao robô: prefira criar a planilha à mão, compartilhar e usar *Atualizar*.
* **Senha de aplicativo: não funciona.** A Sheets API só aceita OAuth ou conta de serviço; senha de app vale só para e-mail (SMTP).

O programa descobre o tipo pelo conteúdo do JSON; não há chave para trocar.

## 2. Configurar

1. Google Cloud Console → crie/escolha um projeto → **APIs e serviços → Biblioteca → Google Sheets API → Ativar**.
2. **Credenciais**: *ID do cliente OAuth* tipo **Aplicativo para computador** (e, na *Tela de consentimento*, adicione seu e-mail
   como usuário de teste) — ou *Conta de serviço* → Chaves → JSON.
3. Salve o JSON em `credenciais/google_credentials.json` (ou aponte outro caminho em `GOOGLE_API_CREDENTIALS`, no `credenciais/.env`).
4. Autorize: **Primeira execução → Google API** (ou rode qualquer operação da automação). No OAuth o navegador abre; clique em *Permitir*.
   O token fica em `credenciais/google_token.json` e se renova sozinho.

Variáveis (veja `.env.example`): `GOOGLE_API_CREDENTIALS`, `GOOGLE_TOKEN_FILE`, `GOOGLE_OAUTH_ABRIR_NAVEGADOR` (0 = só mostra o endereço; WSL/servidor).
Para escolher a conta e o navegador da autorização, veja a seção abaixo.
Para reaproveitar o `token.json` do antigo sheets_sync: `GOOGLE_TOKEN_FILE=<caminho do token.json>` e `GOOGLE_CREDENTIALS_FILE=<caminho do credentials.json>` (também aceita).

Segurança: `credenciais/google_*.json` e `credenciais/*token*.json` estão no `.gitignore`; `credenciais/` não entra no backup; nenhum token, chave ou segredo vai para log.

### Conta e navegador certos na autorização

A autorização vale para **uma conta Google** (a dona da planilha ou dos contatos), mas o navegador padrão do computador
costuma estar com outra conta ou outro perfil. Há três formas de resolver, todas no `credenciais/.env` (modelo em `.env.example`):

1. **Copiar o link e colar no navegador certo (já vem ligado).** Ao pedir a autorização o programa **copia o endereço para a
   área de transferência** e mostra a mensagem "Endereço de autorização COPIADO". Se o navegador abrir na conta errada, feche a
   aba, abra o navegador/perfil da conta certa e cole (Ctrl+V) na barra de endereço. O endereço também aparece escrito no log
   ("Endereço de autorização: ..."). Para **não abrir navegador nenhum** e só copiar: `GOOGLE_OAUTH_ABRIR_NAVEGADOR=0`.
   Para não mexer na área de transferência: `GOOGLE_OAUTH_COPIAR_LINK=0`.
2. **Abrir direto no navegador e perfil da conta certa.** `GOOGLE_OAUTH_NAVEGADOR=chrome` (ou `edge`, `firefox`, `brave`, ou o
   caminho do `.exe`) e `GOOGLE_OAUTH_PERFIL=Profile 2`. O perfil é o **nome da pasta**, não o nome que aparece no Chrome:
   abra `chrome://version` (no Edge, `edge://version`) **dentro do perfil da conta certa** e veja o último trecho de "Caminho do
   perfil" (`Default`, `Profile 1`, `Profile 2`...). Só o perfil, sem navegador, assume o Chrome. Argumentos extras:
   `GOOGLE_OAUTH_NAVEGADOR_ARGS`.
3. **Sugerir a conta ao Google.** `GOOGLE_OAUTH_CONTA=escola@gmail.com` faz o Google selecionar/preencher essa conta na tela de
   login. Isso **não troca de perfil**: se o navegador aberto não estiver conectado a essa conta, o Google pede o login dela.
   `GOOGLE_OAUTH_ESCOLHER_CONTA=1` mostra sempre a lista de contas (e pede a permissão de novo).

O mais seguro é combinar 2 e 3. O endereço de autorização termina em `http://localhost:<porta>`, então o navegador usado
**precisa estar no mesmo computador** em que o AUTO SERE está rodando. Em servidor ou WSL sem tela, use
`GOOGLE_OAUTH_ABRIR_NAVEGADOR=0` e abra o endereço copiado no computador onde a tela está.

## 3. Usar

**Tela:** Automações → *Planilha no Google Sheets* → escolha a operação:

* **Só verificar o acesso** — confere se a planilha existe, se há permissão e lista as abas. Não grava. Comece por aqui.
* **Atualizar uma planilha existente** — informe o link/ID (na próxima vez já vem preenchido). Marque *Simulação* para ver o que mudaria.
* **Criar uma planilha nova** — informe o nome; cria uma aba por turma com cabeçalhos, preenche e mostra o link. A planilha criada também é **salva na lista de Configurações** (veja abaixo).

**Linha de comando** (mesmas opções da tela):

```
python -m src.comum.cli sheets --operacao verificar                      # usa a planilha ativa do cadastro
python -m src.comum.cli sheets --operacao atualizar --simulacao --confirmo
python -m src.comum.cli sheets --operacao atualizar --planilha_cadastro 7 --turma 3 --confirmo   # 7 = id em Planilhas do Drive
python -m src.comum.cli sheets --operacao criar --nome-planilha "Turmas 2026" --confirmo
```
(`--simular` só mostra o plano e não autentica; `--simulacao` autentica, lê a planilha e mostra o que seria gravado.)

Para o agendador, substitua `atualiza_planilha.py` por essa linha de comando (use conta de serviço, ou autorize uma vez antes).

## 4. O que a atualização faz

Cada turma vai para uma aba (mapa padrão da escola em `ABA_PADRAO`; ajuste em `config/config_usuario.json` →
`"google_sheets": {"mapa_abas": {"3º Ano Integral B": "3B"}}`). O aluno é achado pelo **CGM** (coluna C):

* novo → linha no fim da aba (com a Idade do JSON); existente → só as células **A, C, E, F, H, I, J, L** que mudaram;
* **B (CPF), D (SUS), G (Idade) e K (Escola de origem) existentes nunca são tocadas**; títulos e cabeçalhos também não;
* Transferido: I = T, H e J em branco, L = data. Matriculado: I = M, J = data, L em branco;
* CGM repetido no JSON (ex.: transferido que voltou com outro Nº): vale o registro mais recente;
* aba inexistente não derruba as outras; no fim a execução acusa os problemas.

## 5. Testes

`python -m pytest tests/test_google_sheets.py` — tudo simulado (planilha falsa em memória + cliente oficial sobre HTTP falso).
O que exige credenciais reais: autorizar de verdade, `--operacao verificar` e `atualizar --simulacao` numa planilha sua, e o 1º `criar`.


## Planilhas do Drive (cadastro de links)

Tela própria no menu lateral: **Planilhas do Drive**. É um cadastro (como uma tabela de banco de dados) dos links das suas
planilhas do Google: pareceres do Infantil, turmas, matrícula e as que vierem depois. Só guarda links; não fala com o Google.

Cada registro tem: **id** (número automático, nunca reaproveitado), **nome**, **link**, **categoria**, **situação** (ativa/inativa),
**observação**, origem (cadastrada à mão ou criada pelo sistema) e data da última alteração. A mesma planilha (mesmo ID do Google)
não entra duas vezes, mesmo com link escrito de outro jeito. Aceita o link completo ou só o ID.

A tela tem busca, filtros por situação e categoria, colunas ordenáveis, "Carregar mais", e ações de copiar link, editar e remover
(remover só tira o link do cadastro; a planilha no Google não é apagada).

* Cada planilha pode ter uma **finalidade** no sistema. Hoje existe **Pareceres do Infantil** (com a **turma** dela): é como a
  automação *Pareceres infantil (planilha)* acha a planilha das professoras (ver `documentacao/Pareceres.md`). Para cada
  finalidade + turma só pode haver **uma planilha ativa** (a vigente); para trocar, deixe a antiga inativa.
* Ao **criar** uma planilha pela automação (não vale para a *Simulação*), ela é cadastrada sozinha, na categoria "Turmas". Se não
  der para cadastrar, a criação não é desfeita: o log só avisa.
* Fica em `dados/planilhas/planilhas.json` (um arquivo só, gravado de forma atômica), e não em `dados/<ano letivo>/`, porque as
  planilhas atravessam os anos. Funciona também no modo "somente consulta" de um ano anterior.
* Código: `src/comum/planilhas_registro.py` (regras e armazenamento), `src/web/api/planilhas.py` (API `/web/api/planilhas`),
  `src/web/templates/planilhas.html` e `src/web/static/js/planilhas.js` (tela).
* O antigo `google_sheets.planilha_id` ("última planilha usada") foi aposentado: na primeira vez, o gerenciador leva esse ID para o
  cadastro como a "Planilha das Turmas" vigente e o remove de `config_usuario.json` (só `mapa_abas` fica lá). A automação e a rotina
  diária usam a planilha **ativa** do cadastro, ou a escolhida no formulário. Uma planilha criada pela automação, havendo já uma ativa,
  entra **inativa** (use "Usar esta" para trocar). Ver `documentacao/Planilhas.md`.

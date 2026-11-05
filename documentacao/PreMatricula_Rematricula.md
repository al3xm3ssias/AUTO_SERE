# Pré-matrícula e Rematrícula

## Pré-matrícula (`pre_matricula.py`, chave `prematricula_completa`)
Portal próprio da pré-matrícula (credenciais `PREMATRICULA_LOGIN`/`PREMATRICULA_SENHA`, Configurações). Quatro etapas
com o mesmo login:

| Etapa | Faz | Grava em `pre_matricula.json` |
|---|---|---|
| 1 Coleta | percorre as turmas e coleta quem tem intenção de vaga | chave `turmas_intencao` (mesclada **sem apagar histórico**) |
| 2 Cadastro | consulta o cadastro completo de cada CPF coletado | chave `cadastros` |
| 3 Contatos | cruza 1 e 2 e gera o CSV do Google Contacts | `TEMPLATE_PREENCHIDO_<data>.csv` |
| 4 Pendentes | re-consulta o CPF de quem sumiu de "aguardando" com situação só **presumida**, para saber se foi matriculado ou cancelado | atualiza situação |

Pontos de entrada: `processo_completo_via_login` (1→2→4→3), `completar_json_via_login` (lê as planilhas `.xlsx` do SERE em
vez da etapa 1) e `verificar_pendentes_via_login` (só a 4).

### Regra de negócio (decidida pelo usuário)
- Aluno cancelado que volta com **nova tentativa de vaga**: vale a **última** tentativa.
- Pendente na fila que foi cancelado no passado: também vale a nova.
- **Mudança de turma não importa** (a revisão é manual; a matrícula na turma correta segue a Secretaria).
- **Manter os dados de cada tentativa** como registro; nunca apagar histórico.
Implementação: `mesclar_turmas_intencao` e `reconciliar_situacoes` (ignora quem está na fila agora), ambas com teste.

### Segurança dos dados
- `pre_matricula.json` é gravado de forma **atômica** e **nunca sobrescrito se ilegível** (antes, JSON corrompido virava
  "vazio" e apagava o histórico).
- A etapa 4 usa a opção da **escola alvo**, não a primeira da lista.
- Screenshots em `dados/<ano>/screenshots`. `extrair_cep()` usa regex.
- **Chaves de topo preservadas** pela coleta, como `avisos_whatsapp` (ver `WhatsApp.md`).

### Telas
Pré-matrícula (`/prematricula/lista`, `/cadastros`, `/fila`). A fila do painel mostra só quem **ainda aguarda** (BUG-PRE-003
corrigido via `_aluno_na_fila_prematricula`).

### Depois da coleta
No fim do processo completo, de "só pendentes" e de "completar JSON", é chamado `avisar_apos_pre_matricula()` —
**comunicado por WhatsApp** (ver `WhatsApp.md`). Também há e-mail aos pais (`avisos`, ver `Comunicacao.md`).

## Rematrícula (`rematricula.py`, chave `rematricula`)
Para cada turma/seção alvo: abre no SERE a lista de matriculados e, **aluno por aluno**, gera a **chave de acesso** do
responsável, entra na **Área do Aluno** (site do Estado) com CPF + chave e confirma a matrícula online na escola sugerida.

| Módulo | Opera em |
|---|---|
| `rematricula_sere.py` | SERE: selecionar turma, listar matriculados, gerar chave, obter CPF do responsável |
| `rematricula_area_aluno.py` | areadoaluno.seed.pr.gov.br: login CPF+chave, selecionar aluno (PrimeFaces), cascata de "Sim" |
| `rematricula_persistencia.py` | controle de progresso |
| `chaves_responsavel.py` | gera e guarda as chaves de acesso (ver abaixo) |

Arquivos em `dados/<ano>/`: `rematriculas_sucesso.json` (**nunca reprocessa**), `rematriculas_erro.json` (com nº de
tentativas acumulado), `rematriculas_historico.json` (todas as tentativas de todas as execuções).
Opções: modo teste (1 aluno por seção), **"Testar com 1 único aluno"** (`um_aluno=True`: só o primeiro pendente no total, para logo depois de tentá-lo, sucesso ou erro; não é simulação), `apenas_erros`. Tem **limite de tentativas** por turma (falha de login/navegação
não prende mais em laço). Fonte própria de turmas (`turmas_de=_turmas_da_rematricula`), com a normalização tolerante a
acento/traço/NBSP.

### Chaves de acesso salvas (`chaves_responsavel.py`, chave `gerar_chaves`)
Automação separada que **só gera e guarda** a chave de acesso do responsável (e o CPF dele); não rematricula ninguém. Mesma
lógica do antigo script avulso `gerar_chaves.py`, com a recuperação de sessão da rematrícula (limite de tentativas) e gravação
atômica. Grava em `dados/<ano>/chave_responsavel.json` — **mesmo nome e formato do script avulso**: se você já tem um arquivo
gerado por ele, copie para `dados/<ano>/` e a rematrícula passa a usá-lo.

| Situação do aluno | O que a rematrícula faz |
|---|---|
| tem chave **e** CPF salvos | pula a ficha do SERE e entra direto na Área do Aluno |
| a chave salva é recusada (login ou abrir a matrícula online falha) | gera uma nova no SERE, **atualiza o arquivo** e tenta **uma** vez de novo |
| não tem chave salva (ou o registro está sem CPF) | gera na hora, como antes (não grava) |
| falha ao **confirmar** a matrícula | não gera chave nova (o problema não é a chave) |

Pontos de atenção:
- O prazo de validade da chave no SERE **não é conhecido pelo sistema**. Por isso não há prazo fixo: chave vencida é detectada na
  hora (recusada) e trocada. `gerar_chaves_via_login(validade_horas=N)` regenera as salvas há mais de N horas; `regenerar=True`
  (caixa na tela) regenera todas.
- O gerador pula quem já tem chave utilizável e quem já está em `rematriculas_sucesso.json`.
- Opção "Ignorar as chaves salvas" na rematrícula (`usar_chaves_salvas=False`) gera todas na hora. Arquivo de chaves ilegível
  **não impede** a rematrícula (avisa e gera na hora); no gerador ele aborta antes de abrir o navegador. Em ambos o arquivo não é alterado.
- O arquivo guarda **CPF + chave em texto puro**; fica em `dados/<ano>/` (bloqueado pelo `.gitignore`). Não envie por e-mail/WhatsApp.

## Bugs abertos (`BUGS_CONHECIDOS.md`)
| ID | Estado |
|---|---|
| BUG-PRE-001 | **Suspeita, não confirmada**: a consulta por CPF talvez leia só o primeiro cadastro (possivelmente o cancelado). Aguardando o site voltar |
| BUG-PRE-002 | Corrigido em 2026-10-07 (testado com dados simulados; falta validar com coleta real) |
| BUG-PRE-003 | Corrigido: fila do painel mostrava matriculados e cancelados |
| BUG-REM-001 | Risco identificado: o clique final de "Confirmar" é tratado como sucesso **sem conferir a página** |

`BUGS_CONHECIDOS.md` parou em 2026-10-30.

## Sessão única no SERE

A rematrícula e o "Gerar chaves" usam **uma única página logada** no SERE durante toda a execução
(`SessaoSere` em `rematricula.py`). Ela lista as seções, abre a turma, lê os alunos e processa cada um a
partir da mesma tela, como o `alunos.py`; entre seções volta pelo botão "Voltar" ou pelo menu. O SERE só
aceita uma sessão por usuário, por isso não se abre página nova com login a cada etapa. Só se loga de novo
se a sessão cair ou depois de um erro crítico. A Área do Aluno continua em páginas próprias (outro site).

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

Arquivos em `dados/<ano>/`: `rematriculas_sucesso.json` (**nunca reprocessa**), `rematriculas_erro.json` (com nº de
tentativas acumulado), `rematriculas_historico.json` (todas as tentativas de todas as execuções).
Opções: modo teste (1 aluno por seção), `apenas_erros`. Tem **limite de tentativas** por turma (falha de login/navegação
não prende mais em laço). Fonte própria de turmas (`turmas_de=_turmas_da_rematricula`), com a normalização tolerante a
acento/traço/NBSP.

## Bugs abertos (`BUGS_CONHECIDOS.md`)
| ID | Estado |
|---|---|
| BUG-PRE-001 | **Suspeita, não confirmada**: a consulta por CPF talvez leia só o primeiro cadastro (possivelmente o cancelado). Aguardando o site voltar |
| BUG-PRE-002 | Corrigido em 2026-10-07 (testado com dados simulados; falta validar com coleta real) |
| BUG-PRE-003 | Corrigido: fila do painel mostrava matriculados e cancelados |
| BUG-REM-001 | Risco identificado: o clique final de "Confirmar" é tratado como sucesso **sem conferir a página** |

`BUGS_CONHECIDOS.md` parou em 2026-10-30.

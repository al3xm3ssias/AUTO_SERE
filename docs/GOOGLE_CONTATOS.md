# Contatos da pré-matrícula no Google Contatos

A pré-matrícula já gera o CSV de contatos (Etapa 3). Com a opção **Enviar os contatos ao Google Contatos**, o mesmo
agrupamento e o mesmo nome (`3º Ano - 2026 - RESPONSAVEL DO ALUNO`) vão **direto para a agenda de contatos** da conta
Google, sem importar arquivo. O CSV continua sendo gerado (serve de backup).

## Rótulos

| Alvo | Rótulos do contato |
|---|---|
| ano letivo vigente (`atual`) | `2026` |
| só o próximo ano (`proximo`) | `Pré-matrícula 2027` **e** `Aluno 2027` |

Os rótulos são criados se não existirem (maiúsculas e minúsculas não importam). Todo contato também fica em
"Meus contatos". Para mudar os textos, ajuste `ROTULO_PRE_MATRICULA` e `ROTULO_ALUNO` em
`src/automacao/contatos_google.py`.

## O que é enviado

Os mesmos campos do CSV: nome, e-mail, telefone (celular), CEP, responsável (como "relação") e o campo
personalizado **Endereço Completo**. Campo vazio não é enviado.

## Não duplica

`dados/google_contatos.json` guarda, para cada contato enviado, o endereço dele no Google, um resumo do que foi enviado
e a identificação dos alunos (CPF só como hash). Em cada rodada:

* **nada mudou** → ignora;
* **mudou** (telefone corrigido, irmão novo, endereço) → atualiza o mesmo contato, só nos campos preenchidos (nunca
  apaga um campo por ele estar vazio nos dados);
* **apagado no Google** (ou na lixeira) → cria de novo;
* **saiu dos dados** (aluno cancelado) → **não** é apagado do Google; a rodada só informa quantos ficaram de fora;
* **virada de ano:** o contato criado como `Pré-matrícula 2027`/`Aluno 2027` é reconhecido quando 2027 vira o ano
  vigente e ganha o rótulo `2027`, sem criar outro.

O arquivo é regravado a cada lote de até 200 contatos: uma queda no meio não deixa contatos sem registro.
Se `google_contatos.json` estiver ilegível, nada é enviado e o arquivo não é alterado.

## Configurar (uma vez)

1. No Google Cloud, no **mesmo projeto** do `google_credentials.json`, ative a **People API**
   (APIs e serviços → Biblioteca → People API).
2. Na tela de consentimento OAuth (Google Auth Platform → Acesso a dados), adicione o escopo
   `https://www.googleapis.com/auth/contacts`.
3. Em **Público**: se o app é "Externo" em modo **Teste**, a conta precisa estar na lista de usuários de teste, e o
   token expira em **7 dias** (a rotina automática falharia). Para uso contínuo, mude para **Em produção**; para uso
   pessoal funciona sem verificação (aparece só o aviso de "app não verificado").
4. A credencial precisa ser OAuth, tipo **Aplicativo para computador**. **Conta de serviço não serve**: contatos
   pertencem a uma conta pessoal.
5. Na primeira execução com a opção marcada o navegador abre; clique em **Permitir** com a conta dona dos contatos.
   O token fica em `credenciais/google_token_contatos.json`, à parte do token das planilhas.

Se o navegador abrir na conta errada, cole o endereço copiado no navegador/perfil da conta certa, ou configure o perfil e a
conta no `credenciais/.env` (veja "Conta e navegador certos na autorização" em `docs/GOOGLE_SHEETS.md`).

Se a conta for institucional (Prefeitura), o administrador pode bloquear apps de terceiros ("acesso bloqueado").

## Usar

Na tela da automação **Pré-matrícula completa**:

* **Enviar os contatos ao Google Contatos**: cria e atualiza de verdade.
* **Simulação do Google Contatos**: não autentica nem fala com o Google; compara com `google_contatos.json` e mostra
  quantos seriam criados e atualizados. Não confere se algum contato foi apagado no Google (isso só aparece na rodada
  real).

Ambas começam **desmarcadas**. Para deixar o envio ligado por padrão, troque `"padrao": False` por `True` em
`src/comum/registro_scripts.py`. Na linha de comando: `--enviar-google-contatos` e `--simular-google-contatos`.

## Se der erro

O erro vira uma mensagem em português e **nunca interrompe a pré-matrícula** (o CSV já foi gerado antes):

| Mensagem | O que fazer |
|---|---|
| "A People API não está ativada" | passo 1 acima |
| "A autorização não inclui o acesso a contatos" | apague `credenciais/google_token_contatos.json`, execute de novo e marque a permissão de contatos; confira o passo 2 |
| "O Google recusou as credenciais (401)" | apague `google_token_contatos.json` e execute de novo |
| "Limite de uso da API" | aguarde alguns minutos e execute de novo (o que já foi criado não duplica) |
| "uma conta de serviço não tem agenda de contatos" | use credencial OAuth (passo 4) |

## Limites conhecidos

* Se o mesmo aluno estiver nos dois alvos (atual e próximo), gera **dois contatos** (um por ano, com nomes diferentes).
* Rótulos de um contato existente não são retirados nem reorganizados pelo programa; só são **acrescentados**.
* A atualização reescreve nome, e-mail, telefone, CEP, relação e "Endereço Completo" quando preenchidos nos dados;
  edição manual nesses campos é sobrescrita se o dado de origem mudar.
* O que só se prova com credenciais reais (aceitação da People API) está marcado como `skip` no fim de
  `tests/test_contatos_google.py`.

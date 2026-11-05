# Bugs conhecidos e pendências

Registro de problemas **identificados e ainda não corrigidos** nos scripts portados.
Cada item diz o que acontece, onde está no código, qual é a regra de negócio
combinada, como confirmar e como corrigir.

Última atualização: 2026-10-30.

| ID | Script | Resumo | Estado |
|---|---|---|---|
| BUG-PRE-001 | `pre_matricula.py` | A consulta por CPF talvez leia só o **primeiro** cadastro, que pode ser o antigo (cancelado) em vez da nova tentativa | **Suspeita, não confirmada** (site fora do ar) |
| BUG-PRE-002 | `pre_matricula.py` | Aluno que volta em **outra turma** fica duplicado, com o registro antigo como cancelado | **Corrigido em 2026-10-07** (testado com dados simulados; ver a seção abaixo) |
| BUG-PRE-003 | `web/api/rotas.py` | A fila da pré-matrícula do painel (widget, contador e lista) mostrava também quem **já foi chamado** (matriculado ou cancelado), como se ainda aguardasse | **Corrigido em 2026-10-30** (testado com dados simulados; ver a seção abaixo) |
| BUG-REM-001 | `rematricula.py` | O clique final de "Confirmar" é tratado como sucesso sem conferir a página | **Corrigido em 2026-11-04** (a validar no site real) |

---

## BUG-PRE-003 — Fila da pré-matrícula mostrava matriculados e cancelados

> **Corrigido em 2026-10-30.** `pre_matricula.json` é o histórico de todos que já passaram pela fila: o site só lista
> quem está "aguardando", então quem é chamado (matriculado ou cancelado) some da lista do site mas **continua no
> arquivo**, com `presente_na_ultima_coleta: false` e uma situação (a presumida, "Cancelado", até a Etapa 4 confirmar a
> real). A fila do painel (`_fila_prematricula`), o contador "Fila da pré-matrícula" e a lista `/prematricula/lista`
> listavam **todos** de `turmas_intencao`, só ignorando a tentativa substituída.
>
> Agora `_aluno_na_fila_prematricula` (`src/web/api/rotas.py`) decide em um só lugar. Fica na fila quem **ainda aguarda**:
> não foi substituído, não saiu da lista na última coleta e não tem situação registrada. Em arquivo antigo, sem
> `presente_na_ultima_coleta`, confere o cadastro (matriculado/cancelado = fora). **O cadastro não tem a última palavra
> quando a marca existe**, por causa do BUG-PRE-001: ele pode ser a tentativa antiga (cancelada) de quem voltou a aguardar.
> Quem foi chamado continua na tela **Cadastros**, com a situação. Testes: `tests/test_telas_dados.py` (seção
> "matriculado e cancelado saem da fila").

---

## Regra de negócio (vale para BUG-PRE-001 e BUG-PRE-002)

- Se o aluno já foi cancelado e voltou com uma **nova tentativa de vaga**, **vale a nova
  (a última) tentativa**.
- Se ele está **pendente na fila** e foi cancelado no passado, também vale a nova tentativa.
- A **mudança de turma não importa** para essa decisão: a revisão é manual, e a matrícula
  na turma correta é feita seguindo as orientações da Secretaria.
- **Os dados de cada tentativa devem ser mantidos** como registro; não apagar o histórico.

O que já respeita a regra hoje:

- `mesclar_turmas_intencao`: aluno que volta para a fila **na mesma turma** tem o registro
  substituído pelo novo (some o cancelamento antigo). Há teste:
  `test_aluno_que_volta_a_fila_perde_o_cancelamento_anterior_no_merge`.
- `reconciliar_situacoes`: ignora quem está na fila agora
  (`presente_na_ultima_coleta is True`). Há teste:
  `test_reconciliar_nao_aplica_cancelamento_antigo_em_quem_voltou_para_a_fila`.

---

## BUG-PRE-001: consulta por CPF pode ler o cadastro errado

**Onde:** `src/automacao/pre_matricula.py`: `consultar_cpf()` e `_extrair_escolas_escolhidas()`.

**Suspeita.** Todos os seletores da tela de consulta terminam em `0`:

- `span#turma0`
- `span#e{n}0` e `span#status{n}0` (n = opção de escola 1, 2 ou 3)
- `span#dNome0`, `span#dNomeResponsavel0`, `span#dTelefoneResponsavel0`, `span#dEmailResponsavel0`
- `span#dLogradouro0`, `dNumero0`, `dComplemento0`, `dBairro0`, `dMunicipio0`, `dUF0`, `dCEP0`
- `div#dCriterios0 li`

O container de resultado se chama `div#divCadastros` (plural). A hipótese é que o `0`
seja o **índice do cadastro** dentro da página, e que um CPF com mais de um cadastro (por
exemplo, o antigo cancelado e uma nova tentativa) mostre `...0`, `...1` etc. O script
**só lê o índice 0**.

**Isso é uma hipótese.** Não foi verificada no site; os IDs vieram do script original.
Também não se sabe se o índice 0 é o cadastro mais antigo ou o mais recente.

**Impacto se confirmado:**

- **Etapa 4** (`etapa_verificar_pendentes`): pode gravar a situação do cadastro antigo
  (ex.: CANCELADO) em quem tem uma nova tentativa em andamento ou já matriculada.
- **Etapa 2/3:** telefone, e-mail, endereço e responsável do CSV de contatos podem vir
  do cadastro antigo.
- `reconciliar_situacoes` e `opcao_da_escola_alvo` leem `escolas_escolhidas`, então herdam o problema.

**Como confirmar (quando o site voltar):**

1. Escolher um CPF que cancelou e voltou com nova tentativa.
2. Rodar `consultar_cpf(page, cpf, analise=True)`. O modo de análise salva screenshot
   da página inteira em `<dados do ano>/screenshots`.
3. Salvar também o HTML (`await page.content()`) e procurar por `span#turma1`, `span#e11`,
   `span#status11`, `span#dNome1` etc. Se existirem, a hipótese está confirmada.
4. Anotar **como distinguir a tentativa mais recente**: posição na página (índice maior =
   mais novo?), ou algum campo de data na tela.

**Correção proposta (não implementada):**

- Percorrer todos os cadastros presentes (`i = 0, 1, 2...` enquanto `span#turma{i}`
  existir), em vez de fixar o `0`.
- **Guardar todos** em `cadastros[cpf]` (por exemplo, uma lista de tentativas), para manter
  o registro de cada tentativa.
- Expor a **tentativa mais recente** (critério definido no passo 4) no formato atual de
  `escolas_escolhidas`, para o restante do código continuar funcionando; `opcao_da_escola_alvo`,
  `reconciliar_situacoes` e `processar_contatos` passam a usar só essa.
- Cuidado ao alterar o formato de `pre_matricula.json`: `interface.html` e o painel de
  funcionários podem ler esse arquivo.

**Testes a escrever:** página simulada com 2 cadastros para o mesmo CPF (antigo
CANCELADO, novo MATRICULADO ou aguardando) e verificar que a Etapa 4 e o CSV usam o novo
e que o antigo continua guardado. O Chromium real roda nos testes (ver `tests/test_rematricula.py`
como exemplo de HTML local).

---

## BUG-PRE-002: mudança de turma duplica o CPF e deixa o registro antigo como cancelado

> **CORRIGIDO em 2026-10-07.** `mesclar_turmas_intencao` agora carimba cada registro visto com
> `coletado_em` e chama `marcar_tentativas_substituidas`: se o mesmo CPF está em mais de uma turma,
> vale quem está presente na última coleta (ou, se nenhum, o `coletado_em` mais recente; em empate
> real nada é marcado). O registro antigo **não é apagado**: recebe `substituido_por_nova_tentativa: true`
> e `turma_da_tentativa_atual`. `extrair_turma_e_aluno`, `listar_pendentes_para_verificar`,
> `reconciliar_situacoes`, a fila da tela de Pré-matrícula e o contador do painel ignoram os registros
> substituídos. A marcação é recalculada a cada coleta (se o aluno voltar à turma anterior, os papéis
> se invertem). Testes: `tests/test_pre_matricula.py` (seção BUG-PRE-002) e `tests/test_telas_dados.py`.
> Novos campos opcionais em `pre_matricula.json`: `coletado_em`, `substituido_por_nova_tentativa`,
> `turma_da_tentativa_atual`. Falta apenas conferir com uma coleta real quando o site voltar.
>
> O texto abaixo é o diagnóstico original, mantido como registro.

**Onde:** `src/automacao/pre_matricula.py`: `mesclar_turmas_intencao()`,
`listar_pendentes_para_verificar()` e `extrair_turma_e_aluno()`.

**O que acontece.** `mesclar_turmas_intencao` mescla **por turma**. Se o aluno some da
lista da turma A e reaparece na turma B:

- na turma A o registro antigo é **mantido**, com `presente_na_ultima_coleta = False` e
  situação presuntiva (`Cancelado` / `CANCELADO VIA SISTEMA/RESPONSAVEL`) ou real;
- na turma B entra o registro novo, com `presente_na_ultima_coleta = True`;
- o mesmo CPF passa a existir **duas vezes** em `turmas_intencao`.

**Decisão:** vale a última tentativa; a turma não importa; **manter os dados das duas
tentativas**. Não apagar o registro antigo.

**Consequências conhecidas:**

- Quem lê `turmas_intencao` pode contar o aluno duas vezes ou ver o registro antigo como cancelado.
- `extrair_turma_e_aluno()` devolve a **primeira turma** em que o CPF aparece (ordem do dict).
  Se for a turma antiga, o nome do contato no CSV do Google Contacts sai com a turma antiga.
- A Etapa 4 volta a consultar o CPF do registro antigo (está ausente e com situação
  presuntiva). Isso não faz mal, mas é uma consulta a mais.

**Estado atual dos dados:** no `pre_matricula.json` enviado em 2026-10, **nenhum CPF
aparece em mais de um registro**. O problema ainda não ocorreu, mas vai ocorrer.

**Correção proposta (não implementada):**

- **Não apagar nada.** Marcar o registro antigo com um campo, por exemplo
  `substituido_por_nova_tentativa: true` (e a turma da tentativa atual), assim que o mesmo
  CPF estiver presente em outra turma na coleta.
- Fazer os consumidores (`processar_contatos`, `extrair_turma_e_aluno`,
  `listar_pendentes_para_verificar`, `reconciliar_situacoes` e o painel) **ignorarem os
  registros marcados como substituídos** ao decidir situação, turma e contato.
- Decidir o critério de "última tentativa" quando **os dois registros estão ausentes**
  (os dois cancelados). Hoje o registro do aluno **não tem data de coleta**; só o arquivo
  tem `atualizado_em`. Provavelmente será preciso gravar um `coletado_em` por registro.

**Testes a escrever:** mesmo CPF na turma A (ausente) e B (presente) → A marcado como
substituído, B intacto, ambos presentes no arquivo; contatos usam a turma B; a Etapa 4
não consulta o registro substituído.

---

## BUG-REM-001: sucesso da rematrícula não era conferido na página

> **Corrigido em 2026-11-04** (testado só com navegador simulado; falta validar no site real, ver abaixo).

**Onde:** `src/automacao/rematricula.py`: `confirmar_matricula()`.

**O que acontecia.** Depois de clicar no botão final de "Confirmar", a função esperava 2 s e
devolvia `True`, sem verificar se a página mostrou a confirmação. Se o clique não tivesse
efeito (erro de validação, página travada), o aluno era gravado em
`rematriculas_sucesso.json` e **nunca mais era reprocessado**.

**Correção.** Depois do clique final, `_aguardar_matricula_realizada()` consulta a página a
cada 0,5 s por até 15 s (`ESPERA_CONFIRMACAO_MS`) procurando `MATRÍCULA REALIZADA COM SUCESSO`
ou `IMPRIMIR COMPROVANTE` (os mesmos textos que já indicam "já matriculado"). Se nenhum
aparecer, devolve `False` ("Erro ao confirmar matrícula") e o aluno vai para
`rematriculas_erro.json`. Erros de leitura durante a navegação são ignorados e tentados de novo.

**Risco que sobra: falso negativo.** Se o site confirmar mas mostrar outro texto, o aluno é
marcado como erro. Ele se corrige sozinho: na próxima execução o aluno cai no caso
`JA_MATRICULADO` e vira sucesso. **A validar:** rodar o teste com 1 aluno e conferir se a
página realmente mostra um desses dois textos logo depois do clique final; se não mostrar,
ajustar `TEXTOS_MATRICULA_REALIZADA`.

---

## Verificações pendentes com os sites reais

O site da pré-matrícula estava **fora do ar em 2026-10-01, sem previsão de volta**. Tudo
o que foi testado foi com navegador simulado.

- [ ] Rodar `consultar_cpf(..., analise=True)` num CPF que cancelou e voltou (BUG-PRE-001).
- [ ] Rodar uma coleta completa da pré-matrícula e conferir `pre_matricula.json` e o CSV de contatos.
- [ ] Rodar `rematricular_via_login(modo_teste=True)` (1 aluno por seção) no SERE.
- [ ] Corrigir os 2 alunos do 3º ano marcados como CANCELADO, mas matriculados nesta
  escola (com cópia de segurança do arquivo antes):

  ```python
  from automacao import pre_matricula as pm
  dados = pm.carregar_pre_matricula()
  for d in pm.reconciliar_situacoes(dados, aplicar=True):
      print(d["nome"], d["situacao_atual"], "->", d["situacao_correta"])
  pm.salvar_pre_matricula(dados)
  ```

- [ ] Confirmar os imports assumidos: `from comum import paths` e os nomes em
  `comum/credenciais.py` (`MATRICULA`, `SENHA_PRE`, `LOGIN`, `SENHA`).
- [ ] Incluir `src/comum/arquivos_json.py` no projeto.

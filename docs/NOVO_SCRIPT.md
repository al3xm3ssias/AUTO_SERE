# Como adicionar um script novo ao AUTO SERE

O sistema tem **um só lugar** para as escolhas que todo script repete: *qual turma?*, *matriculados e/ou
transferidos?*, *quais CGMs?*, *modo de teste*, *reprocessar erros*, *modo debug*. Um script novo só
declara o que usa; a tela, a prévia, a confirmação e a linha de comando vêm prontas.

```
Interface (JSON) ─┐
                  ├─► Opcoes ─► registro_scripts.py (plano) ─► seu script
Linha de comando ─┘      └─► selecionar_alunos(...)  (quem será processado)
```

## Os recursos disponíveis (`src/comum/opcoes_execucao.py`)

| Recurso | Na tela | Na linha de comando | Vira em `Opcoes` |
|---|---|---|---|
| `turma` | lista "Turma": todas, um **ano** (ex.: *3º Ano Integral*) ou uma turma | `--turma [NOME ...]` | `turmas` (vazio = todas) |
| `situacao` | caixas **Matriculados** / **Transferidos** | `--matriculados` `--transferidos` | `matriculados`, `transferidos` |
| `cgm` | caixa de texto com conferência ao vivo | `--cgm N [N ...]` | `cgms` |
| `teste` | "Modo de teste" | `--teste` | `modo_teste` |
| `erros` | "Reprocessar só o que deu erro" | `--erros` | `erros` |
| `debug` | "Modo debug (análise)" | `--debug` | `debug` |

* **Turma** aceita o nome completo (`5º Ano Integral A`), o nome do ano (`5º Ano Integral`) ou só o começo (`5`).
  Letras maiúsculas e acentos não importam.
* **Matriculado/transferido**: em `turmas.json`, `Situação == "Transferido"` é transferido; o resto é matriculado.
  Sem marcar nada na linha de comando = só matriculados (comportamento histórico).
* **CGM**: um por linha, ou separados por vírgula, ponto e vírgula ou espaço (e qualquer mistura). Repetidos são
  removidos e o que não for número de 5 a 12 dígitos é recusado com a lista do que está errado.
* **Modo de teste não é simulação**: processa de verdade o primeiro da seleção (para conferir antes de rodar tudo).

## Passo a passo

1. **Escreva o plano** em `src/comum/registro_scripts.py`: uma função que recebe as opções e devolve *o que executar*.

   ```python
   def _plano_meu_script(o, payload, turmas_json, ctx):
       from src.automacao.meu_modulo import executar_meu_script
       alvo = list(o.turmas) or list(turmas_json)
       turmas = filtrar_turmas_por_situacao(turmas_json, matriculados=o.matriculados, transferidos=o.transferidos)
       return Plano("gui", executar_meu_script, {"turmas_selecionadas": alvo, "turmas": turmas, "modo_teste": o.modo_teste})
   ```

   `Plano.tipo`: `"gui"` (wrappers `executar_*`, que recebem `callback`), `"coroutine"` (função `async`) ou `"sync"`.

2. **Registre**:

   ```python
   registrar(Script("meu_script", (RECURSO_TURMA, RECURSO_SITUACAO, RECURSO_TESTE), _plano_meu_script,
                    confirmar=True, aviso_confirmacao="Altera tal coisa no SERE."))
   ```

   * `confirmar=True`: antes de executar, abre uma janela com o aviso e a prévia ("181 alunos — em 8 turmas").
     Use em tudo que **altera algo no SERE**. Não aparece com o modo de teste marcado.
   * `cgm_obrigatorio=True`: o CGM é exigido (sem isso, em branco = vale turma/situação).
   * `extras`: campos próprios (lista de dicts `{"tipo": "select"|"caixa", "id", "nome", "label", ...}`) e
     `validar_extras` (levanta `ValueError` com a mensagem para o usuário).
   * `turmas_de`: se o script tem a própria lista de turmas (como a rematrícula).

3. **Coloque na lista**: um item em `AUTOMACOES_DISPONIVEIS` (`src/web/api/rotas.py`) com `chave`, `nome` e `descricao`.
   (Um teste confere que todo script registrado está nessa lista.)

4. **Linha de comando**: já vem pronta. O executor genérico (`src/comum/cli.py`) lê o registro e monta as opções do
   seu script sozinho (`--turma`, `--matriculados`, `--transferidos`, `--cgm`, `--teste`, `--erros`, `--debug` e os
   `extras`), com a mesma validação e a mesma prévia da tela:

   ```
   python -m src.comum.cli listar
   python -m src.comum.cli meu_script --ajuda
   python -m src.comum.cli meu_script --turma 5 --matriculados --simular     # só mostra o que seria processado
   python -m src.comum.cli meu_script --turma 5 --matriculados --confirmo     # executa (--confirmo: sem perguntar)
   ```

   Código de saída 0 = concluído, 1 = a execução falhou, 2 = pedido inválido ou não confirmado.
   Se o script também tiver um `argparse` próprio (como o `analisa_arquivos_sere.py`), use as mesmas opções nele:

   ```python
   from src.comum.opcoes_execucao import adicionar_argumentos, opcoes_do_argparse, selecionar_alunos
   adicionar_argumentos(parser, turma=True, situacao=True, cgm=True, teste=True)
   opcoes = opcoes_do_argparse(parser.parse_args())
   ```

   O `analisa_arquivos_sere.py` é o exemplo completo. `argv_cli(opcoes, recursos)` faz o caminho inverso
   (a tela monta os argumentos da linha de comando) e há teste de ida e volta.

5. **Testes**: copie o padrão de `tests/test_registro_scripts.py` (plano) e `tests/test_ui_componentes.py` (tela).

## Campos próprios do script (`extras`)

Além dos componentes compartilhados, o script pode ter campos seus. O servidor os devolve prontos para a tela:

| `tipo` | Campos |
|---|---|
| `select` | `id`, `nome` (chave no JSON), `label`, `opcoes` = `[{valor, texto, ajuda}]`, `padrao`, `semVazio` |
| `caixa` | `id`, `nome`, `label`, `descricao`, `padrao` |
| `texto` | `id`, `nome`, `label`, `placeholder` |
| `pasta` | `label`, `destino` (`"digitalizacao"` ou `"modelos"`: a pasta escolhida é gravada na configuração, que é de onde o script lê) |

Qualquer campo aceita `visivelSe: {campo: "<id de outro campo>", valor: "<valor>"}` (aparece só para aquele valor) e
o `select` mostra a `ajuda` da opção escolhida. Exemplo completo: o modo Básico/Completo de **Alunos**
(`_extras_alunos` em `registro_scripts.py`). Só coloque um campo de pasta se o script realmente a ler da configuração;
um seletor de pasta que o script ignora engana quem usa.

## Estado atual

Todas as automações **implementadas** passam pelo registro (23). As 4 que ainda respondem "não implementada" (pareceres,
agendador, avisos) ficam fora até existirem; os campos delas, por enquanto, estão em
`CAMPOS_AUTOMACAO` (`app.js`). Quando uma for implementada: registre e apague a entrada antiga.


## Configurações e histórico na tela do script

A tela de cada automação não tem abas: abaixo de **Executar** aparecem **Configurações do script** e **Histórico**.

- **Configurações do sistema que o script lê:** declare em `registrar(Script(..., configs=("ano_letivo", "credenciais_sere", ...)))`
  ou acrescente a linha em `CONFIGS_DOS_SCRIPTS` (`src/comum/registro_scripts.py`). Os ids válidos estão em
  `CATALOGO` (`src/comum/configuracoes_scripts.py`). Configuração nova do sistema = uma entrada nesse catálogo
  (rótulo, como ler o valor, linha da tela Configurações onde se altera). Script sem mapa reprova em
  `tests/test_historico_configuracao.py`.
- **Opções da execução e flags:** continuam vindo de `recursos`, `extras` e `flags_automacao`; a tela as lista sozinha.
- **Histórico:** é gravado automaticamente ao fim de cada execução em `dados/<ano>/historico_automacoes/<chave>.jsonl`
  (últimas 100). "Deu certo" = linhas do log com ✅ ✔ [OK]; "deu errado" = ❌ [ERRO] (e a exceção, se o script caiu);
  avisos = ⚠. Para o histórico ficar útil, o script deve marcar o resultado de cada item com esses símbolos.

## Navegador (Chrome/Firefox) e "ver a janela"

Todo script que abre navegador usa `await navegador.lancar(p, "<motor do script>", <headless do script>)`
(`src/comum/navegador.py`) — **nunca** `p.chromium.launch(...)` direto (um teste reprova). Assim valem para todos:

- **Navegador padrão** (Configurações → *Navegador das automações*): Automático (cada script usa o seu, como sempre),
  Chrome ou Firefox. Script que usa algo exclusivo do Chromium passa `travar_motor=True` (hoje: `parecer_rco`).
- **Ver a janela** (tela da automação → *Configurações do script* → *Navegador*): liga/desliga o headless só naquele
  script. Sem escolha salva, vale o headless que o script já usava. Script que já tem opção própria de mostrar a janela
  passa `forcar_mostrar=<a opção>`.
- Script novo que abre navegador: acrescente-o em `NAVEGADOR_DOS_SCRIPTS` (`src/comum/registro_scripts.py`) com o motor
  para o qual foi feito; ele ganha o bloco "Navegador" na tela sozinho.

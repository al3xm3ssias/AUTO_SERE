# Turmas

## Para que serve
Coleta no SERE (Consulta Padrão → Por Turma) a lista de alunos de cada turma da escola. O resultado, `turmas.json`, é a
**fonte de dados de quase todo o resto**: pastas, coleta de cadastros, transferidos, documentos, painel, comparação de anos.

- **Automação:** `turmas` (`src/automacao/turmas.py`, função `coletar_turmas_e_alunos_via_login`).
- **Tela:** Turmas (`GET /web/api/turmas/lista`) — um cartão por turma, com matriculados, transferidos, masculino/feminino
  e a lista completa de alunos com os campos originais.
- **Saída:** `dados/<ano>/turmas.json`.

## Formato de `turmas.json`
Dicionário `{ "<nome da turma>": [ {N, CGM, Nome, Data Nasc., Idade, Sexo, Situação, Data Matricula}, … ] }`.
Situação **matriculado** = o campo contém "matriculado"; **transferido** = contém "transf" (regra única usada em todo o projeto).

## Regra de identidade (decisão de 27/10/2026)
| Conceito | Chave |
|---|---|
| **Registro** (uma linha da turma) | nº da chamada (N) + nome + data de nascimento — na consolidação por CGM: (CGM, Situação, Data da movimentação, N) |
| **Aluno** (pessoa) | nome + data de nascimento |

- O mesmo aluno pode ter **dois registros** (transferido e depois matriculado de novo, com N maior). Os dois são mantidos;
  o posterior recebe `Retorno: True` (`src/comum/registros_aluno.py`). Repetição idêntica (retry/recarga) é descartada.
- A situação **atual** é a do registro de data mais recente (desempate: maior N). Cada pessoa é contada **uma vez**.
- Efeito colateral importante: a coleta de alunos por CGM antes abria sempre a primeira linha; hoje respeita o registro.

## Efeitos ao coletar
Ao terminar a coleta de turmas, o sistema **regera `fila_transferidos.json`** e atualiza `transferidos.json` por
`src/automacao/deteccao_transferidos.py` (ver `Transferencias.md`). Falha nessa etapa **nunca derruba a coleta**.
O backup automático ao fim das coletas é a pendência **3b**.

## Painel
`GET /web/api/painel/resumo` calcula, sem valores inventados: total de alunos ativos, meninos/meninas, documentos
(`documentos-alunos.json`), pré-matrícula, fora do raio, encaminhamentos e transferidos. Arquivo ausente = 0.
**Limitação conhecida:** a tabela "Transferidos" do painel lê só quem está em processo; o "Total" não é o total da escola e
não mostra pré-corte nem retornados.

## Pastas de digitalização (relacionado)
`gerar_pastas` cria `<pasta de digitalização>/<turma>/<N - NOME>/` e move para `TRANSFERIDOS/` quem saiu do `turmas.json`
ou está "Transferido". A pasta é escolhida pelo usuário (Configurações → pasta de digitalização).
Em `config_usuario.json` de exemplo: `C:\AUTO_SERE\dados\2026\DIGITALIZAÇÃO`.

## Particularidades
- Turmas "SEM SERIAÇÃO" são ignoradas em coletas derivadas (`alunos_completo`).
- Tempos de espera da navegação foram unificados nos mais conservadores (800 ms/500 ms): robustez antes de velocidade.
- **[não validado]** Coleta real de Turmas no SERE (pendência de ambiente).

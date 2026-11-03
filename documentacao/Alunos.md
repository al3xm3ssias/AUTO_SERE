# Alunos

## Para que serve
Mantém o cadastro individual dos alunos (documentos pessoais, filiação, endereço, contatos, perfil socioeconômico) e
apresenta tudo numa **ficha única** na tela Alunos.

## Duas coletas (duas fontes)
| | Básico — `alunos` | Completo — `alunos_completo` |
|---|---|---|
| Módulo | `src/automacao/alunos.py` | `src/automacao/alunos_completo.py` |
| Tela do SERE | consulta (visualização) | **edição** do aluno |
| Saída | `alunos.json` — **lista** com rótulos do SERE (`"Nome"`, `"Data Nascimento"`, `"Mãe"`…) | `alunos_completo.json` — **dicionário `{cgm: {...}}`** com chaves snake_case, ≈60 campos a mais |
| Alcança | dados gerais | inputs/selects/radios/checkboxes: deficiências, recursos de prova, perfil socioeconômico, atendimento educacional especializado |
| Robustez | sem retry (falha só é logada) | cache incremental, fila por status, erros persistentes, recuperação quando a tabela some |
| Parâmetros | — | `MESES_CACHE = 2` (modo rápido pula quem foi coletado há menos de 2 meses); `STATUS_ACEITOS = {"matriculado"}` |
| Arquivos extras | `alunos_erros.json` | `alunos_completo_erros.json`; grava a cada 10 alunos |

No **wizard** (1ª execução) entra só o modo **básico** (decisão 10g, o completo demora mais); o completo fica em
Automações → Alunos.

## Ficha unificada (`src/comum/alunos_unificados.py`, rota `GET /web/api/alunos/lista`)
Une os dois arquivos **pelo CGM, sem alterar nenhum**:
1. Campos do básico permanecem com os mesmos rótulos.
2. Campo básico **vazio** que o completo tem preenchido é completado e marcado em `_preenchido_completo`.
3. Campo preenchido nos dois com valores **diferentes** não é sobrescrito: vai para `_divergencias` (cada cadastro foi
   coletado numa data; quem usa a tela confere).
4. Campos só do completo vão para `_extras`, agrupados e com rótulo legível.
5. CGM só existente no completo vira aluno com os rótulos do básico preenchidos a partir dele.

Metadados por aluno: `_cadastro` (`"completo"` | `"basico"` | `"so_completo"`), `_coleta_completo`, `_extras`,
`_preenchido_completo`, `_divergencias`.
Tela: todos os campos sempre visíveis, "—" onde falta dado (decisão 10h). O HTML fica todo em
`partials/alunos_completo_cards.html` (**não apagar**); `alunos_cards.html` só o inclui.
**[não validado]** abrir com os JSON reais e ver se aparecem divergências falsas (⚠).

## Aluno que volta à escola
Ver `Turmas.md` — registros do mesmo CGM são mantidos; o posterior recebe `Retorno`.

## Pastas dos alunos
`gerar_pastas` (pasta por turma e por aluno) e `mapear_pastas` (`alunos_pastas.json`, `nao_encontrados.json`; casamento
exato normalizado com *fallback* fuzzy via rapidfuzz/difflib acima de `LIMIAR_SIMILARIDADE`). Ver `Documentos.md`.

## Rematrícula, pré-matrícula, SUS e CEP
Usam dados de alunos mas têm documentos próprios: `PreMatricula_Rematricula.md` e `Relatorios_e_Extras.md`.

## Dados fictícios
`python -m src.comum.dados_ficticios --ano 2025` gera turmas, alunos e funcionários **falsos** para testar telas e troca de
ano (Configurações → Ano letivo → dados fictícios).

# Funcionários

## Para que serve
Saber quem trabalha na escola, com que vínculo, e gerar os **termos de ciência**.

## Automações
| Chave | Módulo | Saída |
|---|---|---|
| `funcionarios` | `servidores.py` (`coletar_basico` / `coletar_completo`) | `funcionarios.json` (básico) e `funcionarios_completo.json` (completo) |
| `vinculos` | `funcionarios_vinculos.py` | `funcionarios_matriculas.json` (e `coleta_servidores.json`, `rh_estagiarios.json`, `rh_terceirizados.json`, `cache_holerites.json`) |
| `termos` | `termo_ciencia.py` | `.docx` preenchido a partir do modelo Word |

Existe também `src/automacao/funcionarios.py`, versão simples/antiga da coleta (não é a registrada).

## Coleta no SERE (`servidores.py`)
Navega **Censo Escolar → Funcionário/Docente → Consulta** (`sere_api.navegar_censo_escolar`).
- **Básico:** nome, CPF, função, RG, nome da mãe, e-mail, curso superior, pós-graduação, turmas/disciplinas.
- **Completo:** para cada funcionário consulta pelo CPF no formulário de Cadastro (documentos, filiação, endereço).
  Grava a cada `SALVAR_A_CADA = 5` cadastros, em `funcionarios_completo_progresso.json`; **não encolhe** o arquivo no meio; se
  for cancelado, der erro ou cair, avisa no log e na tela. Rodar de novo ainda refaz todos (retomada é pendência).

## Vínculos (SERE × RH da Prefeitura × holerite)
Fusão de quatro scripts: `servidores`, `coleta_servidores` (site do RH), `capturar_matriculas` (cruzamento por nome) e
`mapa_escriturarios` (comprovação por holerite). Fluxo:
1. Lista do SERE (`funcionarios.json`; coleta antes se não existir ou se pedir atualizar).
2. Lista do RH (reusa o arquivo se tiver menos de 24 h).
3. Cruza por **nome** (igual ou abreviado, "DE OLIVEIRA" → "O"). Quem não é servidor: consta em RH estagiários →
   `estagiario`; em RH terceirizados → `terceirizado` (`terceirizado_origem = lista_rh`); em nenhuma → `terceirizado` com
   `nao_consta_no_rh` (**inferência**: confira a lista de revisão, pode ser grafia diferente).
4. **Comprovação pelo holerite** do mês: compara o **local de trabalho** com o nome da escola (Configurações → Dados da
   escola). `na_escola` = `True` / `False` (pode ser homônimo) / `None` (sem holerite, layout diferente, rubrica 256
   "Estouro do Mês"). Terceirizados e estagiários valem pelo SERE (`comprovacao = "sere"`).
   Homônimos: o holerite desempata e fica só a matrícula lotada aqui.
5. Grava `funcionarios_matriculas.json` — mesmo formato do script original (os termos já o leem) + campos novos:
   `vinculo`, `terceirizado`, `terceirizado_origem`, `na_escola`, `comprovacao`, `local_trabalho_holerite`, `holerite_mes`,
   `revisar`, `ajuste_manual`.

### Modos (`modo`)
| Modo | Faz |
|---|---|
| `sere` | só refaz `funcionarios.json`; não fala com o RH |
| `vincular` | cruza nomes e grava matrícula, **cargo** (`titcar`) e **admissão** (`datadm`); sem holerite (rápido) |
| `homonimos` | só para quem tem mais de uma matrícula com o nome (ou `so_nome`): holerite de cada uma; só uma lotada aqui → fica, as outras vão para `vinculos_descartados`; duas ou mais → **dois concursos** (ex.: 20 h + 20 h) ficam todas; nenhuma → nada descartado sem prova |
| `completo` | vincular + holerite de todos os casados (padrão) |

### Ajustes manuais — `funcionarios_ajustes.json`
Editado por você, na pasta de dados do ano: `{"<cpf só números>": {"terceirizado": false, "na_escola": true, "observacao": "..."}}`.
Chave = CPF (ou o nome, sem CPF). Vale a cada execução e **tira a pessoa da lista de revisão**.

### Cuidados
- O **holerite não é guardado em disco** (tem salário): o cache guarda só local, cargo e se há a rubrica 256.
- Pausa de **5 s** entre consultas ao RH. Cancelável a qualquer momento.
- RH estagiários/terceirizados são lidos por HTTP simples; o endpoint de estagiários (`…/estagiarios/1`) foi **deduzido por
  analogia — não confirmado**. Se o site exigir navegador, essas listas são puladas com aviso.

## Termos de ciência (`termo_ciencia.py`)
Preenche "MODELO DE TERMO DE CIENCIA.docx" (pasta definida por `configuracao.pasta_modelos()`, Configurações) com
`NOME | MATRÍCULA | DATA | ASSINATURA` para todos de `funcionarios_matriculas.json` com `numcad` válido. O modelo
original nunca é alterado. Requer `python-docx`. Tem campo de **tema** validado antes de rodar.
**Pendência:** decidir se os termos pulam quem tem `na_escola = false`.

## Tela Funcionários
`GET /web/api/funcionarios/lista` (`partials/funcionarios_cards.html`); mostra aviso se a coleta completa parou no meio.
**[não validado]** coletas reais, RH de estagiários e leitura do holerite (depende do layout atual do site).

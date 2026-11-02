# Documentos

## Para que serve
Conferir, enviar, validar, limpar e comprimir os documentos digitalizados dos alunos, cruzando **o que o SERE tem** com
**o que está na pasta de digitalização** do computador (PC).

## Peças
| Peça | Módulo | Papel |
|---|---|---|
| Motor unificado | `src/automacao/sere_2026.py` (≈2,6 mil linhas) | Modos `--limpeza`, `--documento`, `--analisa`, `--espec`, `--aluno`, `--transferidos`, `--validar` |
| Navegação/API do SERE | `src/comum/sere_api.py` | login, navegar por aluno, pasta virtual, buscar documentos (API interna), excluir arquivo |
| Upload | `src/comum/sere_upload.py` | POST direto que replica o `uploadArquivo()` da página; decide pular slot |
| Limpeza | `src/comum/sere_limpeza.py` | `remover_slot` (com correção do bug da tupla de contagem) |
| Normalização | `src/comum/sere_normalizacao.py` (≈1 mil linhas) | **Fonte de verdade** de slots, sinônimos, `IDTIPO_PARA_SLOT`, `resolver_slot`, `norm` |
| Utilitários | `src/comum/sere_utils.py` | datas do SERE, slot ↔ `idtipo`, sem I/O |
| Análise SERE | `src/relatorios/analisa_arquivos_sere.py` | coleta os documentos de todos os alunos via API → Excel + JSON |
| Análise da pasta | `src/relatorios/analisa_documentos_pc.py` | confere a pasta do PC (considera sinônimos; CPF dispensado em certidão de quem nasceu depois de 2017) |
| Cruzamento | `src/relatorios/cruzar_documentos.py` | SERE × PC; status por aluno (ex.: "Completo — todos PC anexados") |
| Mapa de pastas | `src/relatorios/mapear_pastas_alunos.py` | aluno ↔ pasta (fuzzy) |
| Compressão | `src/comum/compressao.py` + `src/automacao/comprimir.py` | reduz o que passa do limite do SERE |

## Automações (chaves)
| Chave | Altera o SERE? | Resumo |
|---|---|---|
| `analisa_sere` | não | Coleta documentos do SERE → `documentos-alunos.json` + relatório. Usa flags guardadas na aba "Configuração" (ex.: `--rapido`); uma seleção explícita as substitui |
| `analisa_pasta` | não | Análise da pasta do PC |
| `cruzamento` | não | `cruzamento-documentos.json` (usado depois por `--aluno --faltando`) |
| `validar` | **sim** | Valida documentos pendentes (`--delay N`, padrão 10 s entre alunos) |
| `documentos` | **sim** | Remove **um tipo** de documento (por ID) de todos os alunos |
| `limpeza` | **sim** | Limpa **todos** os arquivos de todos os alunos e reconsulta o que restou |
| `espec` | **sim** | Envia um tipo de documento da pasta para todos os alunos |
| `aluno` | **sim** | Envia os documentos só dos CGMs informados (`--erros`, `--faltando`); CGM obrigatório |
| `comprimir` | não (só arquivos) | Reduz PDFs/JPG/PNG acima do limite |
| `gerar_pastas`, `mapear_pastas` | não | Estrutura de pastas e índice |

Scripts que **alteram** o SERE pedem confirmação com prévia (exceto no modo de teste, que processa **de verdade** o primeiro aluno).

## Regras de upload (`sere_upload.py`)
- Limite de arquivo: **1,5 MB** (`LIMITE_ARQUIVO_MB_PADRAO`); acima disso o SERE responde HTTP 500.
  `compressao.LIMITE_SERE_MB` deve ser igual (há teste conferindo).
- Um slot é **pulado** se estiver validado, dentro do prazo (`PRAZO_REENVIO_MESES_PADRAO = 9`) ou for documento estável
  (`DOCS_ESTAVEIS_PADRAO`).
- Navegador: Firefox em `limpeza` e `documento` (padronizado em 29/08/2026).

## Compressão (conservadora, mexe em documentos de alunos)
- JPG/PNG: reduz o maior lado (até 1300 px no último passo) e a qualidade; PDF: reencoda imagens das páginas e compacta
  estrutura (PDF só de texto quase não encolhe e fica como está). Para no **primeiro** passo que fica abaixo do alvo.
- Grava em temporário e confere (abre? mesmas páginas? menor?) **antes** de trocar; o original vai para
  `dados/<ano>/ORIGINAIS_ANTES_DA_COMPRESSAO` (fora da pasta de digitalização) e a cópia é conferida.
- **Preserva a data de modificação** (o modo `--transferidos` usa a data dos arquivos como corte).
- Pastas `BACKUP*` nunca são tocadas; só troca se economizar o mínimo (`GANHO_MINIMO`); o que não rende é registrado em
  `compressao_registro.json` para não repetir; cancelar para entre um arquivo e outro. `pypdf` é instalado na primeira necessidade.

## Tela Documentos
`GET /documentos/digitalizados`, `/documentos/pive`, `/documentos/analise` (`partials/documentos_cards.html`).

## Particularidades
- **Sinônimos**: nomes de arquivo do PC têm sufixo `-Nome-S-O-B` (iniciais do aluno), removido para isolar o tipo
  (`_strip_nome_aluno`). A classificação segue um pipeline de 5 etapas: sinônimo exato → ignorar (situacionais) →
  substring de palavra completa → prefixo de palavra completa → regex de fallback.
- `CGM_UPLOAD` deixou de ser lista editada à mão: vem de `configuracao.cgm_upload()`.
- Versões antigas `src/automacao/sere_{api,limpeza,upload,utils}.py` são **código morto** (ver `Pendencias_e_Divergencias.md`).
- **[não validado]** uma execução real de cada automação com "Modo de teste".

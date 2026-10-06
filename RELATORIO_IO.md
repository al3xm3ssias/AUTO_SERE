# Relatório de Entrada/Saída dos Scripts — AUTO_SERE

> Gerado por análise estática (AST), sem executar nenhum script. Os itens listados são heurísticos: baseiam-se em padrões de código reconhecidos (chamadas conhecidas, imports, decorators). Revise casos de entrada/saída dinâmica ou indireta manualmente.

## Referência: AUTO_SERE_MAPA.txt

```
.env.example
.gitignore
.vscode/extensions.json
.vscode/launch.json
.vscode/settings.json
.vscode/tasks.json
README.md
config/config.yaml
dados/backup/.gitkeep
gerar_zip.sh
locks/.gitkeep
logs/.gitkeep
requirements.txt
src/__init__.py
src/automacao/__init__.py
src/automacao/alunos.py
src/automacao/alunos_completo.py
src/automacao/coleta_emails.py
src/automacao/envia_email.py
src/automacao/executar_aluno.py
src/automacao/executar_analisa.py
src/automacao/executar_documento.py
src/automacao/executar_espec.py
src/automacao/executar_transferidos.py
src/automacao/executar_validar.py
src/automacao/funcionarios.py
src/automacao/gerar_pastas.py
src/automacao/prematricula.py
src/automacao/prematricula_api.py
src/automacao/prematricula_cadastro.py
src/automacao/prematricula_coleta.py
src/automacao/prematricula_contatos.py
src/automacao/prematricula_pendentes.py
src/automacao/prematricula_planilhas.py
src/automacao/processo_transferidos.py
src/automacao/rematricula.py
src/automacao/rematricula_area_aluno.py
src/automacao/rematricula_persistencia.py
src/automacao/rematricula_sere.py
src/automacao/sere_2026.py
src/automacao/sere_api.py
src/automacao/sere_limpeza.py
src/automacao/sere_normalizacao.py
src/automacao/sere_upload.py
src/automacao/sere_utils.py
src/automacao/servidores.py
src/automacao/sisreg.py
src/automacao/termo_ciencia.py
src/automacao/test_gerar_pastas.py
src/automacao/turmas.py
src/comum/__init__.py
src/comum/cep_api.py
src/comum/configuracao.py
src/comum/credenciais.py
src/comum/execucao_gui.py
src/comum/executar_aluno.py
src/comum/executar_analisa.py
src/comum/executar_documento.py
src/comum/executar_espec.py
src/comum/executar_limpeza.py
src/comum/executar_transferidos.py
src/comum/executar_validar.py
src/comum/logger.py
src/comum/paths.py
src/comum/sere_api.py
src/comum/sere_limpeza.py
src/comum/sere_normalizacao.py
src/comum/sere_upload.py
src/comum/sere_utils.py
src/relatorios/__init__.py
src/relatorios/analisa_arquivos_sere.py
src/relatorios/analisa_documentos_pc.py
src/relatorios/cruzar_documentos.py
src/relatorios/mapear_pastas_alunos.py
src/relatorios/mascarar.py
src/web/README.md
src/web/__init__.py
src/web/api/__init__.py
src/web/api/rotas.py
src/web/app.py
src/web/static/css/styles.css
src/web/static/img/favicon-16.png
src/web/static/img/favicon-32.png
src/web/static/img/favicon.svg
src/web/static/img/logo-branco-192.png
src/web/static/img/logo-branco.png
src/web/static/img/logo-preto-192.png
src/web/static/img/logo-preto.png
src/web/static/js/app.js
src/web/static/js/icons.js
src/web/templates/ajuda.html
src/web/templates/automacoes.html
src/web/templates/base.html
src/web/templates/configuracoes.html
src/web/templates/menu.html
src/web/templates/painel.html
src/web/templates/partials/tabela_generica.html
src/web/templates/primeira_execucao.html
tests/fixtures/.gitkeep
tests/test_ambiente.py
tests/test_gerar_pastas.py
```

## Scripts analisados: 68

## Índice

- [src\__init__.py](#src\--init--py)
- [src\automacao\__init__.py](#src\automacao\--init--py)
- [src\automacao\alunos.py](#src\automacao\alunospy)
- [src\automacao\alunos_completo.py](#src\automacao\alunos-completopy)
- [src\automacao\coleta_emails.py](#src\automacao\coleta-emailspy)
- [src\automacao\envia_email.py](#src\automacao\envia-emailpy)
- [src\automacao\executar_aluno.py](#src\automacao\executar-alunopy)
- [src\automacao\executar_analisa.py](#src\automacao\executar-analisapy)
- [src\automacao\executar_documento.py](#src\automacao\executar-documentopy)
- [src\automacao\executar_espec.py](#src\automacao\executar-especpy)
- [src\automacao\executar_transferidos.py](#src\automacao\executar-transferidospy)
- [src\automacao\executar_validar.py](#src\automacao\executar-validarpy)
- [src\automacao\funcionarios.py](#src\automacao\funcionariospy)
- [src\automacao\gerar_pastas.py](#src\automacao\gerar-pastaspy)
- [src\automacao\prematricula.py](#src\automacao\prematriculapy)
- [src\automacao\prematricula_api.py](#src\automacao\prematricula-apipy)
- [src\automacao\prematricula_cadastro.py](#src\automacao\prematricula-cadastropy)
- [src\automacao\prematricula_coleta.py](#src\automacao\prematricula-coletapy)
- [src\automacao\prematricula_contatos.py](#src\automacao\prematricula-contatospy)
- [src\automacao\prematricula_pendentes.py](#src\automacao\prematricula-pendentespy)
- [src\automacao\prematricula_planilhas.py](#src\automacao\prematricula-planilhaspy)
- [src\automacao\processo_transferidos.py](#src\automacao\processo-transferidospy)
- [src\automacao\rematricula.py](#src\automacao\rematriculapy)
- [src\automacao\rematricula_area_aluno.py](#src\automacao\rematricula-area-alunopy)
- [src\automacao\rematricula_persistencia.py](#src\automacao\rematricula-persistenciapy)
- [src\automacao\rematricula_sere.py](#src\automacao\rematricula-serepy)
- [src\automacao\sere_2026.py](#src\automacao\sere-2026py)
- [src\automacao\sere_api.py](#src\automacao\sere-apipy)
- [src\automacao\sere_limpeza.py](#src\automacao\sere-limpezapy)
- [src\automacao\sere_normalizacao.py](#src\automacao\sere-normalizacaopy)
- [src\automacao\sere_upload.py](#src\automacao\sere-uploadpy)
- [src\automacao\sere_utils.py](#src\automacao\sere-utilspy)
- [src\automacao\servidores.py](#src\automacao\servidorespy)
- [src\automacao\sisreg.py](#src\automacao\sisregpy)
- [src\automacao\termo_ciencia.py](#src\automacao\termo-cienciapy)
- [src\automacao\test_gerar_pastas.py](#src\automacao\test-gerar-pastaspy)
- [src\automacao\turmas.py](#src\automacao\turmaspy)
- [src\comum\__init__.py](#src\comum\--init--py)
- [src\comum\cep_api.py](#src\comum\cep-apipy)
- [src\comum\configuracao.py](#src\comum\configuracaopy)
- [src\comum\credenciais.py](#src\comum\credenciaispy)
- [src\comum\execucao_gui.py](#src\comum\execucao-guipy)
- [src\comum\executar_aluno.py](#src\comum\executar-alunopy)
- [src\comum\executar_analisa.py](#src\comum\executar-analisapy)
- [src\comum\executar_documento.py](#src\comum\executar-documentopy)
- [src\comum\executar_espec.py](#src\comum\executar-especpy)
- [src\comum\executar_limpeza.py](#src\comum\executar-limpezapy)
- [src\comum\executar_transferidos.py](#src\comum\executar-transferidospy)
- [src\comum\executar_validar.py](#src\comum\executar-validarpy)
- [src\comum\logger.py](#src\comum\loggerpy)
- [src\comum\paths.py](#src\comum\pathspy)
- [src\comum\sere_api.py](#src\comum\sere-apipy)
- [src\comum\sere_limpeza.py](#src\comum\sere-limpezapy)
- [src\comum\sere_normalizacao.py](#src\comum\sere-normalizacaopy)
- [src\comum\sere_upload.py](#src\comum\sere-uploadpy)
- [src\comum\sere_utils.py](#src\comum\sere-utilspy)
- [src\relatorios\__init__.py](#src\relatorios\--init--py)
- [src\relatorios\analisa_arquivos_sere.py](#src\relatorios\analisa-arquivos-serepy)
- [src\relatorios\analisa_documentos_pc.py](#src\relatorios\analisa-documentos-pcpy)
- [src\relatorios\cruzar_documentos.py](#src\relatorios\cruzar-documentospy)
- [src\relatorios\mapear_pastas_alunos.py](#src\relatorios\mapear-pastas-alunospy)
- [src\relatorios\mascarar.py](#src\relatorios\mascararpy)
- [src\web\__init__.py](#src\web\--init--py)
- [src\web\api\__init__.py](#src\web\api\--init--py)
- [src\web\api\rotas.py](#src\web\api\rotaspy)
- [src\web\app.py](#src\web\apppy)
- [tests\test_ambiente.py](#tests\test-ambientepy)
- [tests\test_gerar_pastas.py](#tests\test-gerar-pastaspy)

## src\__init__.py

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\automacao\__init__.py

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\automacao\alunos.py

**Descrição (docstring):** alunos.py — Coleta de cadastro completo de alunos no SERE

**Principais imports:** `asyncio, json, pathlib, playwright.async_api, src.comum, src.comum.credenciais, src.comum.logger, src.comum.sere_api`

**Funções definidas:** `get_turmas_validas, get_dados_aluno, get_text, get_alunos_da_turma, coletar_cadastro_completo_alunos, coletar_alunos_via_login`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\alunos_completo.py

**Descrição (docstring):** alunos_completo.py — Coleta robusta de cadastro completo de alunos no SERE

**Principais imports:** `asyncio, datetime, json, pathlib, playwright.async_api, src.comum, src.comum.credenciais, src.comum.logger, src.comum.sere_api`

**Funções definidas:** `carregar_json_existente, salvar_json, registrar_erro, carregar_fila, verificar_timestamp, login, garantir_lista_turmas, abrir_turma, _garantir_tabela_alunos, abrir_aluno, _voltar_para_turma, _val, _select_text, _radio_value, _checkbox_checked, _deficiencias, _recursos_prova, _socioeconomico_servicos, _socioeconomico_itens, _com_quem_reside, coletar_campos, processar_aluno, executar_coleta, coletar_cadastro_completo_via_login`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\coleta_emails.py

**Descrição (docstring):** coleta_emails.py — Coleta de escolas municipais no site da SME

**Principais imports:** `bs4, json, pathlib, requests, src.comum, typing`

**Funções definidas:** `limpar_texto, extrair_dados_tabela, coletar_dados, coletar_escolas_municipais, listar_nomes_escolas, buscar_escola_por_nome`

**Entradas:**
- Requisição HTTP GET: `<url dinâmica>`
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Requisição HTTP GET: `escolas`
- Requisição HTTP GET: `nome`

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)

## src\automacao\envia_email.py

**Descrição (docstring):** envia_email.py — Utilitário de envio de e-mail via SMTP (Gmail)

**Principais imports:** `email.mime.multipart, email.mime.text, smtplib, src.comum.credenciais, typing`

**Funções definidas:** `enviar_email`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)

## src\automacao\executar_aluno.py

**Descrição (docstring):** executar_aluno.py — Wrapper de modo_aluno para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_aluno`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\executar_analisa.py

**Descrição (docstring):** executar_analisa.py — Wrapper de modo_analisa para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_analisa`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\executar_documento.py

**Descrição (docstring):** executar_documento.py — Wrapper de modo_documento para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_documento`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\executar_espec.py

**Descrição (docstring):** executar_espec.py — Wrapper de modo_espec para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_espec`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\executar_transferidos.py

**Descrição (docstring):** executar_transferidos.py — Wrapper de modo_transferidos para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_transferidos`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\executar_validar.py

**Descrição (docstring):** executar_validar.py — Wrapper de modo_validar para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_validar`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\funcionarios.py

**Descrição (docstring):** funcionarios.py — Coleta de cadastro completo de funcionários no SERE

**Principais imports:** `asyncio, json, pathlib, playwright.async_api, src.comum, src.comum.credenciais, src.comum.logger, src.comum.sere_api`

**Funções definidas:** `get_dados_funcionario, get_text, get_funcionarios_da_lista, coletar_funcionarios, coletar_funcionarios_via_login`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\gerar_pastas.py

**Descrição (docstring):** gerar_pastas.py — Gerador da estrutura de pastas de digitalização

**Principais imports:** `json, os, pathlib, shutil, src.comum, src.comum.configuracao, typing`

**Funções definidas:** `carregar_json, extrair_alunos, nome_pasta, separar_alunos, nomes_pastas_validos, criar_pastas, verificar_transferidos, exibir_resumo, main` (possui `main()`)

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)

## src\automacao\prematricula.py

**Descrição (docstring):** prematricula.py — Orquestrador do Processo de Pré-Matrícula

**Principais imports:** `asyncio, playwright.async_api, src.automacao.prematricula_cadastro, src.automacao.prematricula_coleta, src.automacao.prematricula_contatos, src.automacao.prematricula_pendentes, src.comum, src.comum.prematricula_api, typing`

**Funções definidas:** `executar_processo_completo, executar_prematricula_somente_pendentes`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\prematricula_api.py

**Descrição (docstring):** prematricula_api.py — Infraestrutura compartilhada do portal de Pré-Matrícula

**Principais imports:** `asyncio, datetime, pathlib, playwright.async_api, re, src.comum, src.comum.credenciais, typing`

**Funções definidas:** `navegar_com_retry, _nome_arquivo_seguro, capturar_tela, safe_text, fazer_login, _extrair_motivo_situacao, _extrair_escolas_escolhidas, _normalizar_maiusculas_aluno, consultar_cpf`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\prematricula_cadastro.py

**Descrição (docstring):** prematricula_cadastro.py — Etapa 2: Consulta de Cadastro por CPF

**Principais imports:** `asyncio, playwright.async_api, src.automacao.prematricula_coleta, src.comum.prematricula_api, typing`

**Funções definidas:** `consultar_cadastros, executar_prematricula_cadastro`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\prematricula_coleta.py

**Descrição (docstring):** prematricula_coleta.py — Etapa 1: Coleta de Intenções de Vaga

**Principais imports:** `asyncio, datetime, json, pathlib, playwright.async_api, src.comum, src.comum.prematricula_api, typing`

**Funções definidas:** `carregar_json, carregar_pre_matricula, salvar_pre_matricula, mesclar_turmas_intencao, chave_aluno, coletar_intencoes_vaga, text_of, executar_prematricula_coleta`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\prematricula_contatos.py

**Descrição (docstring):** prematricula_contatos.py — Etapa 3: Geração do CSV de Contatos

**Principais imports:** `collections, csv, datetime, pathlib, src.automacao.prematricula_coleta, src.comum, src.comum.configuracao, typing`

**Funções definidas:** `extrair_turma_e_aluno, extrair_cep, processar_contatos, obter_colunas_template, exportar_csv, gerar_csv_contatos, executar_prematricula_contatos`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)

## src\automacao\prematricula_pendentes.py

**Descrição (docstring):** prematricula_pendentes.py — Etapa 4: Verificação de Pendentes

**Principais imports:** `asyncio, playwright.async_api, src.automacao.prematricula_coleta, src.comum.prematricula_api, typing`

**Funções definidas:** `_situacao_e_presuntiva, listar_pendentes_para_verificar, verificar_pendentes, executar_prematricula_pendentes`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\prematricula_planilhas.py

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\automacao\processo_transferidos.py

**Descrição (docstring):** processo_transferidos.py

**Principais imports:** `asyncio, dataclasses, datetime, enum, json, pathlib, playwright.async_api, random, re, src.comum, src.comum.configuracao, src.comum.credenciais`

**Funções definidas:** `_dir_historicos, _dir_guia_transferencia, valido, valido, dias_desde_emissao, e_infantil, log, _agora_str, _parse_iso, _parse_data, carregar_json, salvar_json, _chave_ordenacao, _marcar, marcar, info_doc_json, _registro_vazio, _registro_pre_corte, inicializar_alunos, sincronizar_assinaturas, _sincronizar_campo, aluno_completo, registrar_pre_corte, _processar_turmas, carregar_alunos, decidir_acao_download, decidir_acao_emissao, delay, inspecionar_documentos, baixar_pdf, assinar_como_secretario, navegar_historico_gravar, navegar_historico_alterar, navegar_historico_emitir, navegar_guia, _locator_nivel_historico, _locator_tipo_guia, login, gravar_matriculas, alterar_historico, handle_dialog, gerar_historico, assinar_historico, imprimir_historicos, _navegar_ate_documentos_guia, gerar_guia, assinar_guia, imprimir_guias, _processar_download_lote, _executar_download, _cabecalho, _pesquisar_cgm, _pesquisar_cgm_guia, _safe_nav, processar_transferencias`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\rematricula.py

**Descrição (docstring):** rematricula.py — Orquestrador do Processo de Rematrícula

**Principais imports:** `asyncio, datetime, playwright.async_api, src.automacao.rematricula_area_aluno, src.automacao.rematricula_persistencia, src.automacao.rematricula_sere, src.comum.credenciais, src.comum.sere_api`

**Funções definidas:** `_fazer_login_sere, processar_aluno, processar_turma, executar_rematricula`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\rematricula_area_aluno.py

**Descrição (docstring):** rematricula_area_aluno.py — Operações na Área do Aluno (site do Estado)

**Principais imports:** ``

**Funções definidas:** `fazer_login_area_aluno, acessar_matricula_online, confirmar_matricula, voltar_para_turma`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)

## src\automacao\rematricula_persistencia.py

**Descrição (docstring):** rematricula_persistencia.py — Controle de progresso da rematrícula

**Principais imports:** `json, pathlib, re, src.comum, unicodedata`

**Funções definidas:** `normalize_text, carregar_erros_anteriores, carregar_sucessos_anteriores, salvar_resultados, aluno_ja_processado`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)

## src\automacao\rematricula_sere.py

**Descrição (docstring):** rematricula_sere.py — Operações na página do SERE

**Principais imports:** `playwright.async_api, re, src.automacao.rematricula_persistencia`

**Funções definidas:** `listar_secao_turmas, selecionar_turma, link_label, obter_alunos_matriculados, gerar_chave_acesso, obter_cpf_responsavel`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\sere_2026.py

**Descrição (docstring):** ╔══════════════════════════════════════════════════════════════════════════════╗

**Principais imports:** `argparse, asyncio, datetime, json, pathlib, playwright.async_api, re, src.comum, src.comum.configuracao, src.comum.credenciais, src.comum.logger, src.comum.sere_api`

**Funções definidas:** `_pasta_digitalizacao_ou_avisar, carregar_documentos_alunos, atualizar_documentos_alunos_via_api, _parse_validado, carregar_turmas, menu_selecionar_turma, menu_selecionar_multiplas_turmas, menu_selecionar_tipo_documento, modo_limpeza, modo_documento, modo_analisa, encontrar_pasta_aluno, encontrar_pasta_turma, modo_espec, processar_aluno_upload, modo_aluno, _carregar_transferidos, _salvar_transferidos, _data_apos_corte, _localizar_arquivo_transferido, modo_transferidos, _carregar_cgms_com_pendencia, revalidar_navegacao, voltar_para_menu_por_aluno, validar_aluno, modo_validar, _aceitar_dialog`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Entrada interativa do usuário (input): "
Digite o número da turma: "
- Entrada interativa do usuário (input): "  Turmas: "
- Entrada interativa do usuário (input): "
Digite o ID do documento: "
- Leitura de `sys.argv` (argumentos de linha de comando)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\sere_api.py

**Descrição (docstring):** sere_api.py — Navegação e API do portal SERE (compartilhado)

**Principais imports:** `logging, playwright.async_api, sere_utils`

**Funções definidas:** `esta_na_tela_login, garantir_logado, _navegar_consulta_padrao, navegar_por_aluno, navegar_por_turma, _navegar_menu_topo, navegar_relatorios, navegar_censo_escolar, navegar_pasta_virtual, buscar_documentos_api, excluir_arquivo_api`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Log (warning) via logging
- Saída impressa no console (print)
- Log (error) via logging
- Log (info) via logging
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\sere_limpeza.py

**Descrição (docstring):** sere_limpeza.py — Limpeza de documentos do SERE (remoção de slots)

**Principais imports:** `asyncio, logging, sere_api, sere_utils`

**Funções definidas:** `remover_slot, _e_do_slot, limpar_aluno`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Log (warning) via logging
- Log (info) via logging

## src\automacao\sere_normalizacao.py

**Descrição (docstring):** ''

**Principais imports:** `typing, unicodedata`

**Funções definidas:** `norm, norm_lower, _build_index, _ensure_index, _build_index_lower, _ensure_index_lower, resolver_slot, resolver_slot_lower, slot_por_id, id_por_nome, slots_por_grupo`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)

## src\automacao\sere_upload.py

**Descrição (docstring):** sere_upload.py — Upload de documentos ao SERE (POST direto sem DOM)

**Principais imports:** `base64, json, logging, mimetypes, pathlib, sere_api, sere_normalizacao, sere_utils`

**Funções definidas:** `deve_pular_slot, obter_slots_api, excluir_slot_e_obter_hash, injetar_e_enviar`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Log (error) via logging
- Log (info) via logging
- Saída impressa no console (print)
- Log (warning) via logging

## src\automacao\sere_utils.py

**Descrição (docstring):** sere_utils.py — Utilitários puros compartilhados entre scripts do SERE

**Principais imports:** `datetime, sere_normalizacao, unicodedata`

**Funções definidas:** `norm, parse_data_sere, data_dentro_do_prazo, slot_para_idtipo`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\servidores.py

**Descrição (docstring):** servidores.py — Coleta de funcionários no SERE (básico + completo)

**Principais imports:** `asyncio, datetime, json, pathlib, playwright.async_api, src.comum, src.comum.credenciais, src.comum.sere_api, sys, traceback, typing`

**Funções definidas:** `login_sere, coletar_basico, _limpar_e_voltar, _extrair_dados_completos, consultar_cpf, coletar_completo, coletar_servidores, coletar_servidores_via_login`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Leitura de `sys.argv` (argumentos de linha de comando)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Saída impressa no console (print)
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\sisreg.py

**Descrição (docstring):** sisreg.py — Consulta de encaminhamentos SISREG por CPF de aluno

**Principais imports:** `asyncio, json, pathlib, playwright.async_api, src.comum, typing`

**Funções definidas:** `consultar_encaminhamentos_sisreg`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Função retorna um valor (`return ...`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\automacao\termo_ciencia.py

**Descrição (docstring):** termo_ciencia.py — Geração do Termo de Ciência preenchido

**Principais imports:** `copy, datetime, docx, docx.oxml.ns, json, os, pathlib, src.comum, src.comum.configuracao, sys, typing, unicodedata`

**Funções definidas:** `template_padrao, json_padrao, normalizar, carregar_funcionarios, extrair_candidatos, montar_lista, substituir_no_paragrafo, substituir_marcadores, limpar_celula, definir_texto_celula, adicionar_linha, gerar_documento, preparar_lista_funcionarios, gerar_termo`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Leitura de `sys.argv` (argumentos de linha de comando)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)

## src\automacao\test_gerar_pastas.py

**Descrição (docstring):** test_gerar_pastas.py — Testes de src.automacao.gerar_pastas

**Principais imports:** `pathlib, pytest, src.automacao.gerar_pastas`

**Funções definidas:** `_pasta_aluno, test_extrai_dicts, test_extrai_strings, test_ignora_duplicatas, test_ignora_nome_vazio, test_ordena_por_n, test_lista_vazia, test_nome_pasta_formato, test_separa_ativo_e_transferido, test_sem_situacao_vai_para_ativos, test_cria_pasta_turma, test_cria_pasta_aluno, test_retorna_total_correto, test_idempotente, test_pasta_fantasma_vai_para_transferidos, test_transferido_no_json_vai_para_transferidos, test_ativo_nao_e_movido, test_duplicado_nao_move_se_ja_existe`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\automacao\turmas.py

**Descrição (docstring):** turmas.py — Coleta de turmas e alunos do SERE

**Principais imports:** `asyncio, json, pathlib, playwright.async_api, src.comum, src.comum.credenciais, src.comum.logger, src.comum.sere_api`

**Funções definidas:** `get_turmas_validas, get_alunos_da_turma, coletar_turmas_e_alunos, coletar_turmas_e_alunos_via_login`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\comum\__init__.py

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\comum\cep_api.py

**Descrição (docstring):** cep_api.py — Análise de distância aluno↔escola por CEP

**Principais imports:** `geopy.distance, geopy.geocoders, json, openpyxl, openpyxl.styles, pathlib, requests, src.comum, src.comum.configuracao, time, typing`

**Funções definidas:** `limpar_cache_geocodificacao, _coord_chave, _coord_e_generica, _tentar_nominatim, cep_para_coords, executar_analise_distancia`

**Entradas:**
- Requisição HTTP GET: `<url dinâmica>`
- Requisição HTTP GET: `erro`
- Requisição HTTP GET: `logradouro`
- Requisição HTTP GET: `bairro`
- Requisição HTTP GET: `localidade`
- Requisição HTTP GET: `uf`
- Requisição HTTP GET: `lat`
- Requisição HTTP GET: `lng`
- Requisição HTTP GET: `cep`
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Requisição HTTP GET: `CGM`
- Requisição HTTP GET: `Cgm`
- Requisição HTTP GET: `Situação`
- Requisição HTTP GET: `SituaÃ§Ã£o`
- Requisição HTTP GET: `Situacao`
- Requisição HTTP GET: `Nome`
- Requisição HTTP GET: `CEP`

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)

## src\comum\configuracao.py

**Descrição (docstring):** configuracao.py — Configuração persistida do usuário

**Principais imports:** `json, pathlib, paths, typing`

**Funções definidas:** `carregar_configuracao, _salvar_configuracao, pasta_digitalizacao, pasta_digitalizacao_configurada, definir_pasta_digitalizacao, pasta_modelos, pasta_modelos_configurada, definir_pasta_modelos, cgm_upload, definir_cgm_upload, setup_concluido, marcar_setup_concluido, unidade_escolar, unidade_escolar_configurada, definir_unidade_escolar`

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)

## src\comum\credenciais.py

**Descrição (docstring):** === RESUMO ESTRUTURAL DO SCRIPT ===

**Principais imports:** `os`

**Entradas:**
- Leitura de variável de ambiente: `SERE_LOGIN`
- Leitura de variável de ambiente: `SERE_SENHA`
- Leitura de variável de ambiente: `PREMATRICULA_LOGIN`
- Leitura de variável de ambiente: `PREMATRICULA_SENHA`
- Leitura de variável de ambiente: `EMAIL_REMETENTE`
- Leitura de variável de ambiente: `EMAIL_SENHA_APP`

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\comum\execucao_gui.py

**Descrição (docstring):** execucao_gui.py — Infraestrutura para expor modos assíncronos como funções

**Principais imports:** `asyncio, dataclasses, enum, logging, sys, threading, traceback, typing`

**Funções definidas:** `__init__, emit, __init__, write, flush, __post_init__, iniciar, aguardar, _executar_na_thread`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_aluno.py

**Descrição (docstring):** executar_aluno.py — Wrapper de modo_aluno para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_aluno`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_analisa.py

**Descrição (docstring):** executar_analisa.py — Wrapper de modo_analisa para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_analisa`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_documento.py

**Descrição (docstring):** executar_documento.py — Wrapper de modo_documento para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_documento`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_espec.py

**Descrição (docstring):** executar_espec.py — Wrapper de modo_espec para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_espec`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_limpeza.py

**Descrição (docstring):** executar_limpeza.py — Wrapper de modo_limpeza para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_limpeza`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_transferidos.py

**Descrição (docstring):** executar_transferidos.py — Wrapper de modo_transferidos para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_transferidos`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\executar_validar.py

**Descrição (docstring):** executar_validar.py — Wrapper de modo_validar para uso por interface gráfica

**Principais imports:** `src.automacao.sere_2026, src.comum.execucao_gui, typing`

**Funções definidas:** `executar_validar`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\logger.py

**Descrição (docstring):** === RESUMO ESTRUTURAL DO SCRIPT ===

**Principais imports:** `datetime, logging, logging.handlers, os, paths`

**Funções definidas:** `get_logger`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Log (debug) via logging

## src\comum\paths.py

**Descrição (docstring):** paths.py — Caminhos centrais do projeto AUTO_SERE

**Principais imports:** `datetime, os, pathlib`

**Funções definidas:** `ano_atual, dados_ano_atual, workdir, garantir_diretorios_runtime`

**Entradas:**
- Leitura de variável de ambiente: `AUTO_SERE_ANO_BASE`
- Leitura de variável de ambiente: `AUTO_SERE_WORKDIR`

**Saídas:**
- Função retorna um valor (`return ...`)

## src\comum\sere_api.py

**Descrição (docstring):** sere_api.py — Navegação e API do portal SERE (compartilhado)

**Principais imports:** `logging, playwright.async_api, sere_utils`

**Funções definidas:** `esta_na_tela_login, garantir_logado, _navegar_consulta_padrao, navegar_por_aluno, navegar_por_turma, navegar_relatorios, navegar_pasta_virtual, buscar_documentos_api, excluir_arquivo_api`

**Entradas:**
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Log (warning) via logging
- Saída impressa no console (print)
- Log (error) via logging
- Log (info) via logging
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\comum\sere_limpeza.py

**Descrição (docstring):** sere_limpeza.py — Limpeza de documentos do SERE (remoção de slots)

**Principais imports:** `asyncio, logging, sere_api, sere_utils`

**Funções definidas:** `remover_slot, _e_do_slot, limpar_aluno`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Log (warning) via logging
- Log (info) via logging

## src\comum\sere_normalizacao.py

**Descrição (docstring):** ''

**Principais imports:** `typing, unicodedata`

**Funções definidas:** `norm, norm_lower, _build_index, _ensure_index, _build_index_lower, _ensure_index_lower, resolver_slot, resolver_slot_lower, slot_por_id, id_por_nome, slots_por_grupo`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)

## src\comum\sere_upload.py

**Descrição (docstring):** sere_upload.py — Upload de documentos ao SERE (POST direto sem DOM)

**Principais imports:** `base64, json, logging, mimetypes, pathlib, sere_api, sere_normalizacao, sere_utils`

**Funções definidas:** `deve_pular_slot, obter_slots_api, excluir_slot_e_obter_hash, injetar_e_enviar`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)
- Log (error) via logging
- Log (info) via logging
- Saída impressa no console (print)
- Log (warning) via logging

## src\comum\sere_utils.py

**Descrição (docstring):** sere_utils.py — Utilitários puros compartilhados entre scripts do SERE

**Principais imports:** `datetime, sere_normalizacao, unicodedata`

**Funções definidas:** `norm, parse_data_sere, data_dentro_do_prazo, slot_para_idtipo`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## src\relatorios\__init__.py

**Descrição (docstring):** Pacote do projeto AUTO_SERE.

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\relatorios\analisa_arquivos_sere.py

**Descrição (docstring):** === RESUMO ESTRUTURAL DO SCRIPT ===

**Principais imports:** `argparse, asyncio, datetime, json, openpyxl, openpyxl.styles, openpyxl.utils, os, pandas, pathlib, playwright.async_api, src.comum`

**Funções definidas:** `_chave_ordem, selecionar_turmas_interativo, filtrar_alunos_cruzamento, obter_cgms_transferidos, obter_situacao_por_cgm, filtrar_alunos_por_situacao, filtrar_alunos_por_cgm, __init__, registrar, salvar, _carregar_raw, carregar_alunos_com_erro, limpar_resolvidos, _parse_validado, _processar_json_api, navigate_to_por_aluno, coletar_documentos, _fallback_html, salvar_documentos, gerar_relatorio, executar, main` (possui `main()`)

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Entrada interativa do usuário (input): "Digite o(s) número(s) [ex: 1  ou  1,3,5]: "
- Argumento de linha de comando: `--erros` (argparse)
- Argumento de linha de comando: `--rapido` (argparse)
- Argumento de linha de comando: `--turma` (argparse)
- Argumento de linha de comando: `--alunos` (argparse)
- Argumento de linha de comando: `--todos` (argparse)
- Argumento de linha de comando: `--transferidos` (argparse)
- Interação com navegador automatizado (Selenium/Playwright) — lê elementos da página

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Escrita de dados via `df.to_excel(...)`: `<caminho/objeto dinâmico>`
- Escrita de dados via `df_faltando.to_excel(...)`: `<caminho/objeto dinâmico>`
- Ações no navegador automatizado (cliques, preenchimento de formulários)

## src\relatorios\analisa_documentos_pc.py

**Descrição (docstring):** === RESUMO ESTRUTURAL DO SCRIPT ===

**Principais imports:** `datetime, json, openpyxl, openpyxl.styles, openpyxl.utils, pandas, pathlib, re, src.comum, src.comum.configuracao, sys, unicodedata`

**Funções definidas:** `normalizar, verificar_documento, cpf_na_certidao, main` (possui `main()`)

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)
- Escrita de dados via `df.to_excel(...)`: `<caminho/objeto dinâmico>`
- Escrita de dados via `df_faltando.to_excel(...)`: `<caminho/objeto dinâmico>`

## src\relatorios\cruzar_documentos.py

**Descrição (docstring):** cruzar_documentos.py — Cruzamento entre documentos do SERE e documentos do PC

**Principais imports:** `datetime, json, pathlib, re, src.comum, typing, unicodedata`

**Funções definidas:** `normalize, should_ignore, _strip_nome_aluno, classify_slot, build_sere_index, _doc_display_name, build_pc_index, determine_status, cruzar, main` (possui `main()`)

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)

## src\relatorios\mapear_pastas_alunos.py

**Descrição (docstring):** mapear_pastas_alunos.py — Índice fuzzy nome de aluno ↔ pasta de digitalização

**Principais imports:** `difflib, json, pathlib, rapidfuzz, re, src.comum, src.comum.configuracao, time, typing, unicodedata`

**Funções definidas:** `similaridade, similaridade, normalizar, normalizar_nome_pasta, carregar_turmas, indexar_pastas, indexar_pastas_transferidos, encontrar_pasta, exportar_json, formatar_caminho_saida, main` (possui `main()`)

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)
- Leitura de arquivo: `w` (modo `r`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita de dados JSON: `w` (via `json.dump(...)`)

## src\relatorios\mascarar.py

**Descrição (docstring):** mascarar.py — Anonimização de dados pessoais para dados de teste/demonstração

**Principais imports:** `json, pathlib, re, src.comum`

**Funções definidas:** `mask_value, main` (possui `main()`)

**Entradas:**
- Leitura de arquivo: `<caminho dinâmico>` (modo `r`)
- Leitura de dados JSON: `<caminho dinâmico>` (via `json.load(...)`)

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída impressa no console (print)
- Escrita em arquivo: `<caminho dinâmico>` (modo `w`)
- Escrita de dados JSON: `<caminho dinâmico>` (via `json.dump(...)`)

## src\web\__init__.py

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\web\api\__init__.py

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## src\web\api\rotas.py

**Descrição (docstring):** Rotas de API do Auto SERE

**Principais imports:** `datetime, flask, tkinter`

**Funções definidas:** `painel_resumo, _resposta_lista_generica, turmas_lista, alunos_lista, prematricula_lista, prematricula_fila, funcionarios_lista, automacoes_lista, automacoes_executar, escolher_pasta, wizard_status, wizard_executar_passo`

**Entradas:**
- Entrada via interface gráfica (GUI) — campos preenchidos pelo usuário

**Saídas:**
- Função retorna um valor (`return ...`)
- Saída via interface gráfica (GUI) — telas, mensagens, widgets atualizados

## src\web\app.py

**Descrição (docstring):** Auto SERE — Interface Web

**Principais imports:** `flask, src.web.api.rotas`

**Funções definidas:** `index, create_app`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

## tests\test_ambiente.py

**Descrição (docstring):** Teste de verificação do ambiente (Fase 3 — Verificação do ambiente).

**Principais imports:** `pathlib, src.comum, sys`

**Funções definidas:** `test_estrutura_de_pastas_existe, test_arquivos_essenciais_existem, test_modulo_paths_importavel`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- _Nenhuma saída explícita detectada (pode apenas definir funções/classes usadas por outros módulos)._

## tests\test_gerar_pastas.py

**Descrição (docstring):** test_gerar_pastas.py — Testes de src.automacao.gerar_pastas

**Principais imports:** `pathlib, pytest, src.automacao.gerar_pastas`

**Funções definidas:** `_pasta_aluno, test_extrai_dicts, test_extrai_strings, test_ignora_duplicatas, test_ignora_nome_vazio, test_ordena_por_n, test_lista_vazia, test_nome_pasta_formato, test_separa_ativo_e_transferido, test_sem_situacao_vai_para_ativos, test_cria_pasta_turma, test_cria_pasta_aluno, test_retorna_total_correto, test_idempotente, test_pasta_fantasma_vai_para_transferidos, test_transferido_no_json_vai_para_transferidos, test_ativo_nao_e_movido, test_duplicado_nao_move_se_ja_existe`

**Entradas:**
- _Nenhuma entrada explícita detectada (pode receber dados via import de outro módulo, variáveis globais ou parâmetros de função não capturados por esta análise)._

**Saídas:**
- Função retorna um valor (`return ...`)

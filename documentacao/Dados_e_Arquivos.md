# Dados e arquivos

Raiz: pasta do programa (`paths.RAIZ_PROJETO`). **Não há banco de dados.** Dados do ano em `dados/<ano>/`
(`paths.dados_ano_atual()`). Tudo que contém dado de aluno/servidor está **fora do Git** (`.gitignore`).
Gravação de JSON: `arquivos_json.salvar_json_atomico` (temporário + `os.replace`); JSON ilegível levanta
`ArquivoJsonCorrompidoError` e **nunca** é tratado como vazio.

## Pastas
| Pasta | Conteúdo |
|---|---|
| `config/` | `config.yaml`, `config_usuario.json`, textos opcionais do comunicado |
| `credenciais/` | `.env`, `whatsapp_sessao/` (perfil do WhatsApp) — **nunca versionar** |
| `dados/<ano>/` | JSONs do ano, `DIGITALIZAÇÃO/` (padrão), `TRANSFERENCIAS/`, `PARECERES/`, `PARECERES INFANTIL/`, `AVISOS/`, `screenshots/`, `debug_rco/`, `ORIGINAIS_ANTES_DA_COMPRESSAO/` |
| `dados/calendario/` | calendário letivo |
| `dados/backup/` | backups em zip |
| `logs/`, `locks/` | gerados em execução |

## Arquivos de `dados/<ano>/`
| Arquivo | Gerado por | Lido por / uso |
|---|---|---|
| `turmas.json` | `turmas` | quase tudo; painel; fila de transferidos; compara anos |
| `alunos.json` | `alunos` | tela Alunos, SUS, CEP |
| `alunos_completo.json`, `alunos_completo_erros.json` | `alunos` (modo completo) | tela Alunos (ficha unificada) |
| `alunos_erros.json` | `alunos` (básico) | reprocessar erros |
| `funcionarios.json`, `funcionarios_completo.json`, `funcionarios_completo_progresso.json` | `funcionarios` | tela Funcionários, vínculos |
| `coleta_servidores.json`, `rh_estagiarios.json`, `rh_terceirizados.json`, `cache_holerites.json` | `vinculos` | cache do RH (reuso < 24 h) |
| `funcionarios_matriculas.json` | `vinculos` | termos de ciência |
| `funcionarios_ajustes.json` | **você** (manual) | `vinculos` |
| `documentos-alunos.json` | `analisa_sere`, `limpeza` | painel, documentos |
| `cruzamento-documentos.json` | `cruzamento` | `analisa_sere --faltando` |
| `alunos_pastas.json`, `nao_encontrados.json` | `mapear_pastas` | cruzamento |
| `compressao_registro.json` | `comprimir` | evita repetir compressão |
| `fila_transferidos.json` | `transferidos_fila` / coleta de turmas | **temporário**, regerado |
| `transferidos.json` | `processo_transferidos` | controle permanente; envio ao SERE |
| `processo_transferidos.json` | detecção de mudanças | histórico de movimentos |
| `pre_matricula.json` | `prematricula_completa` | tela, avisos, comunicado (`turmas_intencao`, `cadastros`, `avisos_whatsapp`) |
| `rematriculas_sucesso/erro/historico.json` | `rematricula` | controle de progresso |
| `alunos_encaminhamento.json` | `sus` | tela, painel |
| `alunos_fora_raio.json/.xlsx`, `alunos_coordenadas.json` | `cep` | tela, painel |
| `escolas_completas.json` | `coleta_emails` | seletor de escola, avisos |
| `MODELO/controle_modelos.json` (base `dados/`) | upload de modelos | `parecer_fund` |
| `*_mask.json` | `mascara` | compartilhar estrutura |

> A lista acima vem das referências no código e do mapa de E/S; confira `RELATORIO_IO.md` para o detalhe por script.

## Dados sensíveis (LGPD)
Alunos e servidores: CPF, filiação, endereço, celular. Cuidados já implementados: números mascarados em log/registro, senhas
fora de logs e backups, holerite **não** guardado em disco, cookies do RCO sem valor, `.gitignore` bloqueando dados,
digitalização, pareceres, screenshots, planilhas, logs e backups.

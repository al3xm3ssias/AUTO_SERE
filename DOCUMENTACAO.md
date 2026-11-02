# AUTO SERE — Documentação do projeto

Índice geral da documentação técnica e funcional. O `README.md` explica **como instalar e usar**; aqui está **como
cada parte funciona por dentro**, módulo por módulo. Cada arquivo de `documentacao/` descreve: para que serve, telas,
automações, arquivos lidos e gravados, regras de negócio, particularidades e pendências.

> **Fonte dos fatos.** Tudo foi extraído do código-fonte, dos docstrings, de `docs/`, `pendencias.md`,
> `PROXIMAS_ETAPAS.md` e `BUGS_CONHECIDOS.md` do zip de 2026-11-02. O que **não foi validado em ambiente real**
> está marcado com **[não validado]**. Onde o código e a documentação antiga divergem, isso é dito.

## Mapa dos documentos

| Arquivo | Assunto |
|---|---|
| [`documentacao/00_Arquitetura.md`](documentacao/00_Arquitetura.md) | Camadas, fluxo de uma automação, registro de scripts, opções comuns, travas de segurança, CLI |
| [`documentacao/Turmas.md`](documentacao/Turmas.md) | Coleta de turmas (`turmas.json`), regra de identidade do aluno, painel |
| [`documentacao/Alunos.md`](documentacao/Alunos.md) | Cadastro básico × completo, ficha unificada, divergências, pastas de digitalização |
| [`documentacao/Transferencias.md`](documentacao/Transferencias.md) | Fila, guia e histórico, assinatura, data de corte, pareceres dos transferidos |
| [`documentacao/Documentos.md`](documentacao/Documentos.md) | Análise, validação, upload, limpeza, compressão, cruzamento SERE × pasta |
| [`documentacao/Funcionarios.md`](documentacao/Funcionarios.md) | Coleta básica/completa, vínculos (SERE × RH × holerite), termos de ciência |
| [`documentacao/PreMatricula_Rematricula.md`](documentacao/PreMatricula_Rematricula.md) | Pré-matrícula (4 etapas), regras de negócio, rematrícula, bugs abertos |
| [`documentacao/Pareceres.md`](documentacao/Pareceres.md) | Parecer do Fundamental (Word + QR) e do Infantil (RCO/RCDIG) |
| [`documentacao/Comunicacao.md`](documentacao/Comunicacao.md) | Avisos por e-mail, coleta de e-mails das escolas, estado do envio real |
| [`documentacao/WhatsApp.md`](documentacao/WhatsApp.md) | Provedores, travas, comunicado de matrícula, API, o que falta (item 7b) |
| [`documentacao/Configuracoes.md`](documentacao/Configuracoes.md) | Wizard, credenciais, escola, ano letivo, modo consulta, backup, servidor |
| [`documentacao/Relatorios_e_Extras.md`](documentacao/Relatorios_e_Extras.md) | SUS/SISREG, CEP/raio, calendário, compara anos, máscara de dados |
| [`documentacao/Dados_e_Arquivos.md`](documentacao/Dados_e_Arquivos.md) | Todos os arquivos JSON/pastas, quem grava e quem lê |
| [`documentacao/Pendencias_e_Divergencias.md`](documentacao/Pendencias_e_Divergencias.md) | O que falta validar, código duplicado e divergências encontradas na análise |

## Em uma frase por módulo

- **Turmas** — fonte de verdade de quem está matriculado/transferido; quase tudo depende de `turmas.json`.
- **Alunos** — cadastro individual (básico e completo) mesclado numa ficha única na tela.
- **Transferências** — gera, assina, baixa e envia guia, histórico e parecer de quem saiu.
- **Documentos** — confere o que o SERE tem × o que está na pasta, envia, valida, limpa e comprime.
- **Funcionários** — quem trabalha na escola, vínculo (concursado/terceirizado/estagiário) e termos de ciência.
- **Pré-matrícula / Rematrícula** — fila de vaga, cadastros por CPF, contatos e rematrícula online.
- **Pareceres** — documentos descritivos do Fundamental (Word) e do Infantil (RCO).
- **Comunicação** — e-mail (simulação/teste) e WhatsApp.

## Como manter esta documentação

Ao criar uma automação (ver `docs/NOVO_SCRIPT.md`), acrescente-a ao arquivo do módulo correspondente e, se ela gravar
um arquivo novo, a `Dados_e_Arquivos.md`. Conferir antes de editar: as informações aqui são um retrato de 2026-11-02.

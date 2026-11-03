# Fluxo dos transferidos

```
Turmas ─► turmas.json ─► fila_transferidos.json (temporária) ─► Gerar guia e histórico ─► TRANSFERENCIAS/HISTORICO
                                    │                                                    └► TRANSFERENCIAS/GUIA DE TRANSFERENCIA
                                    └► transferidos.json (controle permanente)                      │
                                                                                                    ▼
Pareceres digitalizados ─► PROCESSAMENTO DE PARECERES ─► (QR, comprimir) ─► PARECERES ─► Enviar ao SERE (pasta virtual)
```

Tudo fica em `dados/<ano letivo>/TRANSFERENCIAS/` (`src/comum/pastas_transferencias.py`).

## Menu lateral (Automações)

| Item | O que faz | Simulação |
|---|---|---|
| Fila de transferidos | Refaz `fila_transferidos.json` a partir do `turmas.json` (também acontece sozinho ao coletar as turmas) | mostra a fila sem gravar |
| Gerar guia e histórico | Executa no SERE as ações marcadas para os alunos da fila (ver abaixo) | mostra alunos, ações, texto e pastas; não abre o SERE |
| Enviar transferidos ao SERE | Envia guia, histórico e parecer das pastas de `TRANSFERENCIAS` | só varre as pastas |
| Pareceres dos transferidos | Lê o QR, arquiva em `PARECERES`, comprime se passar do limite e envia | lê os QR e mostra o plano |
| Pareceres digitalizados | Para **todos** os alunos do Fundamental: lê o QR novo (`AUTOSERE\|PF\|ano\|CGM`), arquiva na turma e, opcionalmente, envia ao SERE e por e-mail ao responsável | lê os QR e mostra o plano e a prévia do e-mail |

A simulação já vem marcada nas telas que mexem no SERE ou nos arquivos.

## Gerar guia e histórico: ações marcadas separadamente

Cinco caixas, todas marcadas por padrão, mais o seletor **Documentos** (histórico e guia / só histórico / só guia):

| Ação | O que faz | Vale para |
|---|---|---|
| Gravar | Grava as matrículas no histórico | só histórico |
| Alterar | Escreve no histórico o texto da observação (a caixa de texto aparece quando Alterar está marcado; o último texto usado volta preenchido) | só histórico |
| Emitir | Gera o documento no SERE | histórico e/ou guia |
| Assinar | Assina como o usuário do SERE logado (Secretário) e confere se o Diretor já assinou; o Diretor assina em outra sessão, e rodar Assinar de novo regista a assinatura dele | histórico e/ou guia |
| Imprimir | Baixa o PDF para `TRANSFERENCIAS` | histórico e/ou guia |

As ações rodam sempre na ordem do processo (gravar → alterar → emitir → assinar → imprimir), mesmo marcando só algumas.
Alterar exige o texto; com "Só a guia", Gravar e Alterar ficam de fora.

## DATA_CORTE

O processo automático vale para quem foi transferido **a partir** da data de corte (inclusive). Antes dela os documentos
são considerados já tratados à mão. Define-se em **Configurações → Data de corte dos transferidos** ou no campo "Data de
corte" de qualquer tela acima (o que for digitado e executado fica gravado em `config/config_usuario.json`,
`data_corte_transferidos`). Sem valor, vale 22/06 do ano letivo.

## Documento da nossa escola × de outra escola

A listagem do SERE mostra também documentos de transferência de outras escolas. Só é **nosso** o documento cujo
"gerado em" bate (mesmo dia, até 2 h) com o `emitido_em` que o processo registrou em `transferidos.json` ao emitir.

- Nosso e válido (2 assinaturas): não sobrescreve. Nosso e só falta a diretora: aguarda, **não emite outro**.
- De outra escola, ou sem registro de emissão nosso: faz o processo todo (emitir, assinar, baixar). Nunca é baixado nem assinado.
- No envio ao SERE, o slot só é pulado se o que está lá é o nosso (já enviado, mesmo nome de arquivo, arquivo local
  inalterado). Documento de outra escola no slot é substituído.
- `baixado_em` = PDF baixado para a pasta; `anexado_em` = enviado à pasta virtual do SERE.

## Quem voltou

Quem foi transferido e voltou à escola continua na fila, com o campo `retorno`, mas **não é processado**: o processo é
feito uma vez só.

## Quem é o aluno

Registro = nº da chamada + nome + data de nascimento. Aluno = nome + data de nascimento. Se o nº da chamada mudou
(transferido e depois matriculado de novo), é um cadastro novo do mesmo aluno: ele conta uma vez, como ativo, e a
transferência continua na fila com o campo `retorno`. A situação atual é a do registro de data mais recente.

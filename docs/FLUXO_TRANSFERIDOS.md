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
| Gerar guia e histórico | Emite, assina e baixa do SERE o histórico e a guia dos alunos da fila | mostra alunos, etapas e pastas; não abre o SERE |
| Enviar transferidos ao SERE | Envia guia, histórico e parecer das pastas de `TRANSFERENCIAS` | só varre as pastas |
| Pareceres dos transferidos | Lê o QR, arquiva em `PARECERES`, comprime se passar do limite e envia | lê os QR e mostra o plano |

A simulação já vem marcada nas telas que mexem no SERE ou nos arquivos.

## DATA_CORTE

O processo automático vale para quem foi transferido **a partir** da data de corte (inclusive). Antes dela os documentos
são considerados já tratados à mão. A data aparece em todas as telas acima (campo "Data de corte"); o que for digitado e
executado fica gravado em `config/config_usuario.json` (`data_corte_transferidos`). Sem valor, vale 22/06 do ano letivo.

## Quem é o aluno

Registro = nº da chamada + nome + data de nascimento. Aluno = nome + data de nascimento. Se o nº da chamada mudou
(transferido e depois matriculado de novo), é um cadastro novo do mesmo aluno: ele conta uma vez, como ativo, e a
transferência continua na fila com o campo `retorno`. A situação atual é a do registro de data mais recente.

# Transferências

## Visão geral
```
Turmas ─► turmas.json ─► fila_transferidos.json (temporária) ─► Gerar guia e histórico ─► TRANSFERENCIAS/HISTORICO
                                │                                                      └► TRANSFERENCIAS/GUIA DE TRANSFERENCIA
                                └► transferidos.json (controle permanente)                          │
Pareceres digitalizados ─► PROCESSAMENTO DE PARECERES ─► (QR, comprimir) ─► PARECERES ─► Enviar ao SERE (pasta virtual)
```
Tudo em `dados/<ano>/TRANSFERENCIAS/` (`src/comum/pastas_transferencias.py`).

## Automações (grupo "Transferidos")
| Chave | Módulo | O que faz | Simulação |
|---|---|---|---|
| `transferidos_fila` | `fila_transferidos.py` | Refaz `fila_transferidos.json` (também ocorre ao coletar turmas) | mostra a fila sem gravar |
| `transferidos_gerar` | `processo_transferidos.py` | No SERE, executa as ações marcadas para os alunos da fila | mostra alunos, ações, texto e pastas; não abre o SERE |
| `transferidos` | `sere_2026.py` (`modo_transferidos`) | Envia guia, histórico e parecer das pastas ao SERE | só varre as pastas |
| `pareceres_transferidos` | `pareceres_transferidos.py` | Lê o QR, arquiva, comprime se passar do limite e envia | lê os QR e mostra o plano |

A simulação já vem marcada nas telas que mexem no SERE ou nos arquivos.

## Arquivos
| Arquivo | Natureza |
|---|---|
| `fila_transferidos.json` | **Temporário**: regerado a cada coleta de turmas. Não editar à mão. Lista **todos** os transferidos e marca `processar`, `antes_do_corte` ou `retornou` |
| `transferidos.json` | **Permanente**: controle (emitido/assinado/baixado/anexado). **Nunca é sobrescrito**; só ganha registro vazio para quem entra no processo e ainda não tem |
| `processo_transferidos.json` | Mudanças detectadas entre coletas de turmas |

## Detecção (`deteccao_transferidos.py`)
- Constrói `transferidos.json` a partir do `turmas.json` (se não existir).
- `detectar_mudancas()` compara o `turmas.json` antigo e o novo → `processo_transferidos.json`; `sincronizar_transferidos_json()` atualiza o controle.
- **Proteção:** se a saída em massa passar de `LIMITE_SAIDAS_EM_MASSA = 25%` da base anterior, suspende "saiu_da_lista"
  (evita tratar uma coleta incompleta como transferência de todos).
- Nada é apagado de nenhum JSON.

## Data de corte
O processo vale para quem foi transferido **a partir** da data de corte (inclusive); antes dela, os documentos são
considerados tratados à mão. Configura-se em Configurações → *Data de corte dos transferidos* ou no campo de qualquer
tela acima (o que for executado fica gravado em `config_usuario.json`, chave `data_corte_transferidos`).
Sem valor: 22/06 do ano letivo. Valor atual no zip: `18/10/2026`.

## Gerar guia e histórico: cinco ações marcáveis
Mais o seletor **Documentos** (histórico e guia / só histórico / só guia). Todas vêm marcadas.

| Ação | Faz | Vale para |
|---|---|---|
| Gravar | grava as matrículas no histórico | só histórico |
| Alterar | escreve a observação (caixa de texto aparece; último texto volta preenchido; chave `observacao_historico`) | só histórico |
| Emitir | gera o documento no SERE | histórico e/ou guia |
| Assinar | assina como o usuário do SERE logado (Secretário) e confere se o Diretor já assinou; o Diretor assina em outra sessão | histórico e/ou guia |
| Imprimir | baixa o PDF para `TRANSFERENCIAS` | histórico e/ou guia |

Rodam sempre na ordem do processo (gravar → alterar → emitir → assinar → imprimir), mesmo marcando só algumas.
Alterar exige o texto; com "Só a guia", Gravar e Alterar ficam de fora.

**Regra absoluta de validade:** um documento só vale com **as duas assinaturas** (Secretário e Diretor). Sem isso: não baixa,
não substitui, não gera — só registra em log.

## Documento "nosso" × de outra escola
A listagem do SERE mostra também documentos de outras escolas. É **nosso** o documento cujo "gerado em" bate (mesmo dia,
até 2 h) com o `emitido_em` que o processo registrou.
- Nosso e válido: não sobrescreve. Nosso e só falta a diretora: aguarda, **não emite outro**.
- De outra escola ou sem registro nosso: faz o processo todo, mas **nunca baixa nem assina** o alheio.
- No envio, o slot só é pulado se o que está lá é o nosso (já enviado, mesmo nome, arquivo local inalterado); de outra escola é substituído.
- `baixado_em` = PDF baixado; `anexado_em` = enviado à pasta virtual.

## Pareceres dos transferidos (`pareceres_transferidos.py`)
Une o antigo *processa-parecer* e *comprimir_pareceres* com o envio:
1. lê o QR (nome + turma) e acha o aluno no `turmas.json`; 2. copia para `PARECERES/<turma>/NN-NOME.ext`; 3. comprime se
passar do limite do SERE (original vai para `ORIGINAIS_ANTES_DA_COMPRESSAO`); 4. marca `parecer.digitalizado_em`;
5. remove de `PROCESSAMENTO DE PARECERES` **só depois** de 2–4 darem certo; 6. envia ao SERE (slot "Parecer Descritivo").
Dependências de leitura de QR em `requirements.txt`. Testado só com PDFs gerados **[não validado com scans reais]**.

## Quem voltou
Fica na fila com `retorno`, conta como **ativo** e **não é processado** (o processo é feito uma vez só).

## Pendências do módulo
- Aluno transferido **duas vezes** no ano: a segunda saída não é tratada.
- Painel não mostra pré-corte nem retornados.
- Mapeamento de turmas do QR só por arquivo, sem tela.
- Script futuro: decodificar o QR dos pareceres e enviar ao SERE e por e-mail (falta escolher a biblioteca).
- **[não validado]** emitir, assinar, baixar e enviar com um aluno real.

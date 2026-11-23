# Comunicação por e-mail

O WhatsApp tem documento próprio (`WhatsApp.md`).

## Avisos (`avisos.py`, chave `avisos`)
Comunicados oficiais por e-mail. **O envio real não existe — de propósito.**

### Públicos hoje
| Público | Origem | Observação |
|---|---|---|
| `escolas` | `escolas_completas.json` (Coleta e-mails), exceto a própria escola | filtros: todas / só escolas / só CMEIs e trecho do nome |
| `pais` | `pre_matricula.json` (cadastros) | um e-mail por endereço distinto; quem tem vários filhos recebe **uma** mensagem; entram matriculados (padrão), aguardando ou ambos; nunca cancelados nem tentativas antigas |

### Modos
- `simular`: não envia; lista destinatários, mostra a prévia e grava o registro em `dados/<ano>/AVISOS/`.
- `teste`: envia **um** e-mail real só ao endereço de teste, com "[TESTE]" no assunto e aviso no topo. Destinatários reais
  nunca recebem. Para escolas, usa a escola fictícia `ESCOLA MUNICIPAL TESTE DA SILVA` (constante `ESCOLA_TESTE`, com um
  e-mail de teste do usuário); para pais, vai ao próprio remetente.

### Marcadores (`$MARCADOR`; desconhecido é recusado antes de enviar)
Todos: `$ESCOLA`, `$ANO`, `$DATA`. Escolas: `$ESCOLA_DESTINO`. Pais: `$RESPONSAVEL`, `$ALUNO`, `$TURMA`.
Limites: assunto 200, mensagem 20 000 caracteres. Cada endereço recebe sua mensagem (SMTP aceita um destinatário por vez).

### Envio
`envia_email.py`: SMTP Gmail, STARTTLS 587, credenciais `EMAIL_REMETENTE`/`EMAIL_SENHA_APP` (Configurações → Gmail,
padrão de senha de app). **Nunca coloque senha no código** (o original tinha uma, já revogada, e não foi copiada).

### Coleta de e-mails (`coleta_emails.py`)
Raspa o site público da SME de Ponta Grossa: todas as escolas municipais e CMEIs (nome, endereço, ramal, e-mail) →
`escolas_completas.json`. Alimenta o seletor de escola no setup e o público `escolas`.

## Uso real do e-mail (definido em 2026-11-02, revisado em 2026-11-14)
Só se comunica **quem está chegando**. A escola não avisa responsável de aluno que sai (público descartado).

**Escola de origem** (feito): um e-mail por aluno que chega, pedindo a transferência. Fluxo:
1. O responsável faz o cadastro na pré-matrícula e o AUTO_SERE salva os cadastros (com nome, nascimento e nome da mãe).
2. A **Consulta na Base ABC** procura o aluno e grava o `vinculo_base_abc` (CGM, escola e turma de origem, situação) no cadastro.
3. O `avisos` manda o e-mail à escola de origem, a partir da lista de `escolas_completas.json`.

Regras:
- Só vale para aluno que estava em escola que usa o SERE; escola particular e de outro estado ficam de fora (e escola sem e-mail na lista também).
- Só recebe aviso quem tem vínculo `ok` com CGM. Sem vínculo, vínculo a verificar ou escola fora da lista: não recebe e aparece numa lista na prévia.
- A Base ABC acha o aluno **estreitando por etapas**: nome completo; se vier mais de um resultado, nome + data de nascimento; a mãe e, na pré-matrícula, o responsável (quando é a mãe) ajudam a separar homônimos. Todos os resultados da página são comparados, sem limite. Se ainda sobrar mais de um, nenhum é escolhido (fica "ambíguo") e o aluno não recebe aviso.

**Envio real** (liberado em 2026-11-14): prévia, simulação, confirmação, intervalo e limite por lote, registro em `AVISOS/enviados.json` e retomada sem repetir. Falta testar com Gmail real (um aluno só).

**Descartado:** responsáveis de quem sai; e-mail de escola escrito de forma disfarçada; "outros canais: SERE". O WhatsApp é a fila 7b. O detalhe e o histórico estão em `pendencias.md`.

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

## Uso real definido em 2026-11-02 (ainda por fazer)
1. Escrever **para a escola de origem**, na hora da transferência, pedindo a documentação do aluno que está chegando.
2. Avisar os **responsáveis de alunos que estão saindo**.
Pendências: público "escola de origem" (de onde vem o dado — digitar, escolher da lista ou campo no cadastro);
público "responsáveis de quem sai" (de `transferidos.json`/fila); reconhecer e-mail disfarçado ("nome [arroba] dominio");
mostrar "sem e-mail" na tela; liberar o **envio real** com prévia, intervalo, limite por lote, segundo plano com pausa e
registro de quem recebeu/falhou; outros canais (WhatsApp, SERE). A ordem sugerida em `pendencias.md` deixa o envio real
**por último**.

# WhatsApp no AUTO SERE

A tela **WhatsApp** do sistema mostra o estado, o QR Code e faz um envio de teste. Há **dois modos reais**
(e o simulado, padrão, que nunca envia nada). Escolha em *WhatsApp → Avançado → Modo de funcionamento*.

| Modo | `WHATSAPP_PROVEDOR` | Precisa de Docker | Como funciona |
|---|---|---|---|
| **Sem Docker** (recomendado no Windows) | `whatsplay` | não | abre o WhatsApp Web num Chromium (Playwright, que o projeto já usa no SERE) |
| Gateway Docker | `blake` | sim | contêiner `blakegt/whatsapp-web-api-rest` (Baileys, sem navegador) |
| Simulado | `simulado` | não | nada sai do computador |

> **Aviso:** os dois modos reais são clientes **não oficiais**. O número pode ser banido, mesmo com poucas
> mensagens. Use um número **dedicado da escola**, nunca em massa e só para quem espera contato.
> A alternativa oficial é a WhatsApp Business Cloud API.

## Modo sem Docker (whatsplay)

1. `pip install -r requirements.txt` e, se ainda não tiver, `python -m playwright install chromium`
   (o mesmo Chromium do SERE).
2. AUTO SERE → **WhatsApp** → **Usar sem Docker** → **Abrir o WhatsApp**.
3. Uma janela do Chromium abre com o WhatsApp Web e o QR Code **também aparece na tela do sistema**.
   No celular: *Aparelhos conectados → Conectar um aparelho*.
4. **Não feche a janela do navegador** enquanto o sistema precisar enviar (pode minimizar). Se fechar, a
   tela volta a "Não iniciado" e basta clicar em *Abrir o WhatsApp* (segundo a biblioteca, o login fica guardado no perfil e não pede QR de novo; isso não pude verificar sem o WhatsApp real).
5. Para enviar de verdade: **Permitir envio real** e use *Mensagem de teste*.

O login fica em `credenciais/whatsapp_sessao/` (fora do Git). **Esse perfil equivale à senha da conta**: não
copie nem compartilhe. Para trocar de número: `WHATSAPP_ZERAR_VINCULO.bat`.

### O que o AUTO SERE corrige na biblioteca (conferido lendo o código da whatsplay 2.6.1)

- Ela sobe por conta própria um servidor de QR em `0.0.0.0:8000` **sem senha** (o QR é chave de pareamento):
  **desligado**; o QR só sai pela tela do sistema.
- O construtor quebra fora da thread principal (`signal.signal`): subclasse que anula isso.
- Por padrão ela acha o contato pelo **nome** (pode escrever para a pessoa errada): o envio é sempre por
  **número** (`/send?phone=<dígitos>`), que também detecta número inválido.
- Escreve o **número completo no log**: INFO silenciado e dígitos mascarados (`***88`).
- Exceções em handlers atrapalham o loop dela: todos blindados.
- Espaçamento mínimo de 3 s entre mensagens.

### Limites do modo sem Docker

- **Depende do HTML do WhatsApp Web.** Quando o WhatsApp mudar o site, pode parar até sair versão nova da
  biblioteca. Por isso `requirements.txt` fixa `whatsplay==2.6.1`; só atualize depois de ler o código e testar.
- Biblioteca nova, de **um só mantenedor** e publicada sem verificação de origem no PyPI. Li o código (sem
  telemetria nem execução de comandos), mas isso não substitui revisar a cada atualização.
- Não há id de mensagem. `enviar` devolve falha também quando a mensagem **pode ter saído** sem o "tique" ser
  visto: confira no WhatsApp antes de reenviar. Arquivos são enviados **como documento, sem legenda**, e a
  biblioteca **não confirma** o envio deles.
- Mensagens de **várias linhas** não foram testadas. Não há recebimento de mensagens (webhook é só do Docker).
- Cada envio navega a página do WhatsApp Web (lento: alguns segundos a dezenas de segundos).
- A biblioteca fixa um user-agent de Chrome 114 e idioma inglês: se o WhatsApp Web recusar (ex.: pedir para
  atualizar o Chrome), a tela avisa após 2 min para olhar a janela.
- **Não foi testado contra o WhatsApp Web real nem no Windows.** Foi testado com a biblioteca e um Chromium
  reais (Linux) contra uma página de mentira local com os seletores da biblioteca.

## Modo gateway Docker (blake)

Só se o Docker funcionar na máquina.

1. Abra o Docker Desktop e execute **`WHATSAPP_SUBIR.bat`** (ou, no Linux:
   `docker compose -f docker/whatsapp/docker-compose.yml up -d`).
2. AUTO SERE → **WhatsApp** → **Usar o gateway Docker** → **Gerar QR Code** e leia pelo celular.

O login fica num volume Docker (`sessao_whatsapp`): reiniciar não pede QR de novo.

## Segurança (leia)

- Vale para os dois modos reais: envio real só com `WHATSAPP_ENVIO_REAL=1` (a tela grava, com confirmação); nenhum
  número completo, texto de mensagem ou QR vai para log.

**Gateway Docker:**

- O gateway **não tem senha**. Quem alcançar a porta envia mensagens pelo WhatsApp da escola.
  O compose publica a porta só em `127.0.0.1`; **nunca** troque por `8085:8085`.
- O QR Code é uma **chave de pareamento**: quem o ler vincula a conta. Mantenha o AUTO SERE em
  `127.0.0.1` (padrão) enquanto pareia e não compartilhe tela com o QR visível.
- A imagem usa o `baileys 7.0.0-rc.9`, que o npm marca como depreciado por falha de **falsificação
  de mensagens recebidas**. Para envio é pouco relevante; para módulos que **reagem a mensagens
  recebidas**, trate o conteúdo como "pedido a confirmar", nunca como ordem (apagar/alterar cadastro).
  Quando houver imagem atualizada, troque a tag no compose (e fixe por digest).

## Zerar o vínculo (gateway Docker)

O gateway **não apaga o login salvo** ao desconectar (nem quando o celular desvincula o aparelho),
e nesse estado não gera QR novo. Se *Gerar QR Code* não mostra nada: execute
**`WHATSAPP_ZERAR_VINCULO.bat`** (= `docker compose ... down -v` + `up -d`) e tente de novo.
*(Deduzido do código do gateway; não foi testado com um número real.)*

## Como funciona (resumo técnico)

| Peça | Arquivo |
|---|---|
| Modo sem Docker: thread/loop do Playwright, envio, blindagens | `src/servicos/whatsapp/provedor_whatsplay.py` |
| Gateway Docker: cliente (envio, consulta de número, mídia, webhooks) | `src/servicos/whatsapp/gateway_blake.py` |
| Gateway Docker: monitor do estado/QR via SSE (`/sse`) | `src/servicos/whatsapp/monitor.py` |
| Objeto único por processo (provedor + monitor) | `src/servicos/whatsapp/gerenciador.py` |
| Mensagens recebidas → módulos | `src/servicos/whatsapp/eventos.py` |
| Rotas `/web/api/whatsapp/*` | `src/web/api/whatsapp.py` |
| Tela | `templates/whatsapp.html`, `static/js/whatsapp.js` |

Particularidades do **gateway Docker** que o código já trata (conferidas rodando o gateway real, sem WhatsApp):

- **Sem endpoint de estado**: o estado vem do SSE; se o AUTO SERE abrir depois da conexão, o estado
  começa "não confirmado" e é confirmado por uma consulta `GET /number/<n>`.
- **Erros não são erros HTTP**: sem sessão, `POST /message` responde 201 com `{}`. "Enviado" só vale
  quando a resposta traz `key.id`.
- **`GET /` inicia a sessão e, com sessão viva, abre um 2º socket**: por isso a tela só chama quando
  a sessão não está ativa e pede confirmação se o estado é incerto.
- `DELETE /webhooks/:n` é 1-based.
- O número é validado no WhatsApp antes do envio e o `jid` devolvido é usado (resolve o 9º dígito).

**Não validado** (precisa de um número real): leitura do QR e pareamento, envio efetivo, e a
inferência de que "consulta respondida com corpo vazio" significa "conectado, número sem WhatsApp".

## Para módulos futuros

```python
from src.servicos.whatsapp.gerenciador import obter_gerenciador
from src.servicos.whatsapp import eventos

g = obter_gerenciador()
if g.estado().conectado:
    g.provedor.enviar("42 99999-8888", "Texto")                       # respeita WHATSAPP_ENVIO_REAL
    g.provedor.enviar_midia("42999998888", "document", pdf_bytes, nome_arquivo="termo.pdf")   # legenda: só gateway Docker
    g.provedor.simular_presenca("42999998888", "composing")           # "digitando…" (só gateway Docker)

@eventos.registrar_tratador                                           # mensagens recebidas
def responder(msg: eventos.MensagemRecebida) -> None:
    if msg.tipo == "text" and not msg.minha and msg.numero:
        ...
```

- Mensagens recebidas exigem o **gateway Docker** e o **webhook** (tela → Avançado → *Registrar webhook*). O gateway chama
  `http://host.docker.internal:<porta>/web/api/whatsapp/webhook?t=<token>`. No Docker Desktop
  funciona com o AUTO SERE em `127.0.0.1`; no Linux o contêiner só alcança o host se o AUTO SERE
  escutar além do loopback (isso expõe a interface à rede: avalie antes) ou defina
  `WHATSAPP_WEBHOOK_URL_BASE`.
- Os tratadores rodam numa thread, isolados: um erro não afeta os outros.
- **Ainda não existe** (próxima etapa, `PROXIMAS_ETAPAS.md` 7b): fila de envio com intervalo e limite
  diário, pausa/cancelamento, histórico e modelos de mensagem. Qualquer envio em lote deve nascer
  com intervalo aleatório e limite por dia.

## Testes

`python -m pytest tests/test_whatsapp_blake.py tests/test_whatsapp_whatsplay.py` (servidor SSE falso e WhatsApp Web de
mentira em localhost; sem internet; o teste com Chromium real pula sozinho se o navegador não existir).
Linha de comando segura: `python -m src.servicos.whatsapp.teste`.

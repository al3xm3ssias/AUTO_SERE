# WhatsApp

> Estado em 2026-11-02: a **integração está feita e testada só com simulações**; falta o primeiro pareamento e envio com
> número real, o teste no Windows e a **fila de envio (item 7b)**. Guia operacional: `docs/WHATSAPP.md`.

## Provedores (`WHATSAPP_PROVEDOR`)
| Valor | O que é | Docker | Observação |
|---|---|---|---|
| `simulado` (**padrão**) | nunca acessa a rede | não | nada sai do computador |
| `whatsplay` | WhatsApp Web num Chromium via Playwright (biblioteca `whatsplay==2.6.1`, fixada) | **não** | recomendado no Windows; perfil em `credenciais/whatsapp_sessao/` (equivale à senha da conta) |
| `blake` | gateway `blakegt/whatsapp-web-api-rest` (Baileys, sem navegador) | sim | `docker/whatsapp/docker-compose.yml`; porta publicada **só em `127.0.0.1:8085`** |
| `http` | formato wwebjs-api (legado) | — | testado só com servidor falso |

Todos são clientes **não oficiais**: o número pode ser banido mesmo com poucas mensagens. Use um número **dedicado da
escola**, nunca em massa, só para quem espera contato. A alternativa oficial é a WhatsApp Business Cloud API.

## Arquitetura (`src/servicos/whatsapp/`)
| Arquivo | Papel |
|---|---|
| `base.py` | Contrato `ProvedorWhatsApp` (`estado`, `enviar`), `EstadoConexao`, `ResultadoEnvio`, `ConsultaNumero`, `normalizar_numero` (DDD+telefone → `55…`, 12–13 dígitos), `mascarar_numero` (`55 42 *****-**88`) |
| `simulado.py` | provedor padrão |
| `provedor_whatsplay.py` | thread própria com loop asyncio; blindagens da biblioteca; espaçamento mínimo de **3 s** entre mensagens |
| `gateway_blake.py` | cliente do gateway: envio, consulta de número, mídia (até 18 MB), webhooks |
| `gateway_http.py` | provedor legado + `envio_real_autorizado()` |
| `monitor.py` | estado/QR do gateway via SSE (`/sse`) |
| `gerenciador.py` | **um por processo**: provedor + monitor; `estado()`, `conectar()`, `verificar()`, QR (SVG/PNG) |
| `eventos.py` | mensagens recebidas → tratadores registrados (`registrar_tratador`), cada um isolado |
| `teste.py` | `python -m src.servicos.whatsapp.teste` (seguro; nenhuma mensagem real) |

Uso por outros módulos:
```python
from src.servicos.whatsapp.gerenciador import obter_gerenciador
g = obter_gerenciador()
if g.estado().conectado:
    g.provedor.enviar("42 99999-8888", "Texto")      # respeita WHATSAPP_ENVIO_REAL
```

## Travas de envio real
Só envia de verdade com: provedor real **configurado**, **conectado** e `WHATSAPP_ENVIO_REAL=1` (a tela grava, com
confirmação). Na mensagem de teste há trava dupla (variável + confirmação) e intervalo mínimo de 5 s. Nenhum número
completo, texto de mensagem ou QR vai para log; números só mascarados. O servidor também bloqueia escrita em ano de consulta.

## Rotas (`/web/api/whatsapp`)
`GET /status`, `GET /qr` (SVG ou PNG; 404 sem QR), `POST /conectar`, `POST /verificar`, `POST /teste`,
`POST /envio-real`, `POST /provedor`, `POST /desconectar`, `GET|POST|DELETE /webhooks`,
`POST /webhook?t=<token>` (recebe mensagens do gateway; token em `WHATSAPP_WEBHOOK_TOKEN`; corpo até 30 MB).
Tela: `templates/whatsapp.html` + `static/js/whatsapp.js`; também há um passo no wizard.

## Variáveis (`credenciais/.env`)
`WHATSAPP_PROVEDOR`, `WHATSAPP_ENVIO_REAL`, `WHATSAPP_WHATSPLAY_HEADLESS` (0 = janela visível, recomendado),
`WHATSAPP_WHATSPLAY_PERFIL`, `WHATSAPP_API_URL`, `WHATSAPP_VALIDAR_NUMERO` (1), `WHATSAPP_NUMERO_SONDA`,
`WHATSAPP_WEBHOOK_TOKEN`, `WHATSAPP_WEBHOOK_URL_BASE`, `WHATSAPP_API_KEY`, `WHATSAPP_SESSAO`. A tela grava e vale na hora.

## Comunicado de matrícula (`src/automacao/comunicado_matricula.py`) — o primeiro uso real
Ao fim da automação de pré-matrícula (`avisar_apos_pre_matricula()`; também `avisar_matriculados()` à mão), envia ao
responsável **um aviso por situação, uma única vez por aluno**:
- `aguardando` → "recebemos a pré-matrícula, aguarde nosso contato";
- `matriculado` → "Comunicado de Matrícula" (documentos, prazo, horários). Quem estava aguardando e foi aprovado recebe o segundo também.

Quem recebe: cadastro consultado + celular válido; nunca cancelados nem tentativas antigas. Responsável com vários filhos
na mesma situação recebe **uma** mensagem com os nomes.

Registro: dentro de `pre_matricula.json`, chave de topo **`avisos_whatsapp`** (de propósito: a coleta reescreve o registro
de cada aluno e apagaria um campo interno). Estrutura por CPF: `{aguardando|matriculado: {avisado, situacao, em, numero(mascarado), tentativas, erro}}`.

Salvaguardas:
- **Linha de base:** na primeira execução ninguém é avisado; quem já existe é marcado. Só o que ocorrer depois dispara.
- **Nunca repete:** cada envio real é gravado na hora; **simulação não registra**.
- Falha incerta ("pode ou não ter saído") e "número sem WhatsApp" não se repetem sozinhas (sem WhatsApp tenta de novo se o
  telefone mudar); falha comum tenta até **3 vezes**.
- Limite de **30 mensagens por execução** (`limite_por_execucao`) e pausa entre envios; o resto fica para a próxima.
- WhatsApp desconectado ou envio real bloqueado: para na hora, sem gravar.
- Texto e número completo nunca vão para log/registro.

Ajustes em `config_usuario.json`, chave `comunicado_matricula`: `ativo`, `avisar_aguardando`, `escriturario`, `dias_prazo`
(8), `limite_por_execucao` (30), `link_grupo`, `links_turmas` (nome da turma como na pré-matrícula, sem acento/maiúscula).
Textos podem ser trocados por `config/comunicado_matricula.txt` e `config/comunicado_aguardando.txt`.
**Nota:** o `config_usuario.json` do zip **não tem** essa chave (valores padrão valem).

## Limites conhecidos
- whatsplay depende do HTML do WhatsApp Web (versão fixada; revisar o código a cada atualização); biblioteca de um só
  mantenedor; sem id de mensagem (falha pode significar que **saiu** sem o "tique"); arquivos vão como documento, **sem
  legenda** e sem confirmação; multilinha **não testada**; **sem recebimento** (webhook é só do Docker).
- Gateway Docker: **sem senha** (nunca publicar a porta além de `127.0.0.1`); QR é chave de pareamento; imagem usa
  `baileys 7.0.0-rc.9`, marcado como depreciado por falha de falsificação de **mensagens recebidas** (trate o recebido como
  "pedido a confirmar", nunca como ordem). `WHATSAPP_ZERAR_VINCULO.bat` apaga o vínculo; `WHATSAPP_SUBIR.bat` sobe o gateway.
- No Linux o contêiner só alcança o host do webhook se o AUTO SERE escutar além do loopback (ou `WHATSAPP_WEBHOOK_URL_BASE`).

## Item 7b: fila de envio (implementada em 2026-11-22; falta validar com WhatsApp real)
Fila com pausa entre mensagens, limite por dia, pausa/cancelamento, histórico e modelos de mensagem: ver `docs/WHATSAPP.md`
(seção "Fila de envio"). Testes: `tests/test_whatsapp_fila.py`. **Ainda não existe**: variação aleatória na pausa, janela de
horário e canal WhatsApp em `avisos`. Ganchos prontos: `enviar_midia`, `simular_presenca`
(só Docker), `eventos.registrar_tratador`. Também previstos: canal WhatsApp em `avisos` (o campo "Canal" da tela já existe).
`pendencias.md` recomenda usar a fila com pais de verdade **só depois** de rodar `pytest`, limpar duplicatas, validar o SERE
real e criar o lock de execução.

Testes: `tests/test_whatsapp.py`, `test_whatsapp_blake.py`, `test_whatsapp_whatsplay.py` (servidor SSE falso e WhatsApp Web de mentira em localhost).

## Mensagem em massa aos Direcionados GEO (26/11/2026)

Em **Pré matrícula → Direcionados GEO → Mensagem em massa** o sistema pergunta aos responsáveis dos alunos de `sere_sisgea_<ano+1>.json`
se ainda querem a vaga ou se já matricularam em outra unidade (modelo pronto `confirmar_interesse_geo`, editável na própria tela).

- **Só enfileira.** O envio é feito pela fila de sempre (pausa de 5 min, limite por dia, trava `WHATSAPP_ENVIO_REAL`), iniciada na tela WhatsApp.
- **Uma mensagem por telefone:** irmãos com o mesmo número recebem uma só, com os nomes juntos em `$ALUNO`.
- **Ficam de fora:** ausentes da lista, matrícula já confirmada aqui (dá para incluir), sem telefone e telefone inválido.
- Filtro por etapa; repetir o pedido não duplica (mesmo número + mesmo texto).
- API: `GET /web/api/whatsapp/fila/geo/resumo` e `POST /web/api/whatsapp/fila/geo/em-massa` (`{modelo_id, texto, etapa, incluir_confirmados, confirmo}`).
- A escolha aluno a aluno na tela WhatsApp ("Direcionados GEO (próximo ano)") continua como era: `GET /fila/geo` e `POST /fila/do-geo`, modelo `geo_confirmar_interesse`.

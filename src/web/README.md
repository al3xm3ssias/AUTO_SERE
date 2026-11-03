# Auto SERE — Interface Web (`src/web`)

Interface gráfica do Auto SERE, construída com **Flask 3** no backend e
HTML/CSS/JS puro no frontend (sem build step — abre direto no navegador
enquanto o Flask roda localmente).

O visual (paleta de cores, tipografia, cards, sidebar, os 3 temas) foi
extraído e adaptado do painel de referência do usuário — mesma
identidade visual, agora servida pelo Flask com dados reais via
`/web/api/...` em vez de arquivos `.json` estáticos soltos.

## Como rodar

A partir da **raiz do projeto** (`AUTO_SERE/`):

```bash
pip install -r requirements.txt
python -m src.web.app
```

Acesse **http://127.0.0.1:8000** no navegador (porta padrão; mude com `AUTO_SERE_PORT` ou `"servidor"` em `config/config_usuario.json`).

> Rodando como `python -m src.web.app` (e não `python src/web/app.py`)
> para que os imports `from src.automacao...` funcionem corretamente
> quando você conectar as automações reais.

## Estrutura

```
src/web/
├── app.py                     # cria o Flask app e registra os blueprints
├── api/
│   ├── rotas.py                # endpoints de API (painel, listas, automações, wizard)
│   └── calendario.py           # API do calendário letivo (blueprint próprio)
├── templates/
│   ├── base.html                # shell da aplicação: sidebar + topbar + temas
│   ├── painel.html               # tela "Painel principal"
│   ├── menu.html                 # inclui as 4 telas de listagem (turmas/alunos/...)
│   ├── calendario.html           # tela "Calendário letivo"
│   ├── corte_etario.html         # tela "Corte etário" (turma por mês/ano de nascimento)
│   ├── automacoes.html           # lista de automações + tela de execução
│   ├── configuracoes.html        # telas de credenciais/config
│   ├── primeira_execucao.html    # wizard de 1ª execução obrigatória
│   ├── ajuda.html
│   └── partials/
│       └── tabela_generica.html  # tabela reutilizada por turmas/alunos/etc.
└── static/
    ├── css/styles.css           # design system completo: tokens, 3 temas, componentes
    ├── js/icons.js                # ícones SVG inline (sem CDN — ver nota abaixo)
    ├── js/app.js                  # navegação SPA + todas as chamadas fetch()
    ├── js/calendario.js           # lógica da tela Calendário (IIFE; expõe carregarCalendario)
    ├── js/corte_etario.js         # lógica da tela Corte etário (IIFE; expõe carregarCorteEtario)
    └── js/vendor/jspdf.umd.min.js # jsPDF local (exportação do quadro em PDF, funciona offline)
```

## Calendário letivo

Tela **Menu → Calendário letivo** (view `calendario`). Mostra o mês/ano com
feriados nacionais (BrasilAPI), recessos, feriados municipais e períodos
letivos, e conta os dias letivos (dia útil, dentro de um período, sem
feriado nem recesso).

| Método | Rota | O que faz |
|---|---|---|
| GET | `/web/api/calendario/dados` | eventos + períodos cadastrados |
| GET | `/web/api/calendario/feriados/<ano>` | feriados nacionais (cache de 30 dias) |
| GET | `/web/api/calendario/fixos/<ano>` | feriados fixos de Ponta Grossa + Quarta-feira de Cinzas + datas comemorativas |
| POST | `/web/api/calendario/eventos` | cria `recesso`, `emenda`, `htpc`, `municipal` ou `outro` |
| DELETE | `/web/api/calendario/eventos/<id>` | exclui |
| POST | `/web/api/calendario/periodos` | cria período (`tipo`: `letivo` ou `ferias`) |
| DELETE | `/web/api/calendario/periodos/<id>` | exclui |

**Padrão de cores:** feriado (nacional, municipal e Quarta-feira de Cinzas) =
vermelho · recesso e emenda de feriado = azul claro · HTPC = verde-limão ·
férias escolares = amarelo · data comemorativa = ★ roxa (não tira o dia
letivo) · dia letivo = sem cor. Quando um dia cai em mais de uma categoria, a
prioridade é feriado > recesso/emenda > HTPC > outro > férias.

**Datas fixas embutidas** (constantes no topo de `src/web/api/calendario.py`):
26/07 Padroeira, 15/09 Aniversário da cidade, Quarta-feira de Cinzas
(calculada pela Páscoa) e as datas comemorativas (30/05, 22/08, 30/09, 15/10,
30/10, 31/10, 12/11). O Dia do Servidor (28/10) não entra, pois muda por
decreto; se for decretado, cadastre como evento.

Dados em `dados/calendario/calendario.json` e
`dados/calendario/feriados_cache/AAAA.json`. É um arquivo único (não por ano
letivo) porque férias e recessos atravessam a virada do ano. Sem internet, a
tela usa o cache de feriados já baixado; sem cache para o ano, mostra um aviso.

Testes: `pytest tests/test_calendario.py`.

## Ícones: por que SVG inline em vez de Font Awesome

O painel de referência usa Font Awesome via CDN. Testamos e o CDN
(`cdnjs.cloudflare.com`) retorna **403 bloqueado** na rede onde isso
roda — o mesmo acontece com o CDN do Google Fonts. Por isso os ícones
são SVGs inline, gerados por `static/js/icons.js`, sem depender de
internet. Se sua rede não bloquear esses CDNs, as fontes Google (Inter
+ DM Mono) carregam normalmente pelo `<link>` no `base.html`; se
bloquear, o CSS já cai automaticamente no fallback do sistema
operacional — nada quebra visualmente.

Para adicionar um ícone novo: abra `static/js/icons.js`, adicione uma
entrada no objeto `ICONS` com o path SVG, e use `data-icon="nome"` no
HTML ou `icon("nome")` dentro de template strings no `app.js`.

## Temas

Três temas prontos, trocáveis pelo seletor no rodapé da barra lateral:

- `escuro` (padrão)
- `medio` (equilibrado)
- `claro`

Persistem via `localStorage`. Para ajustar cores, edite os tokens no
topo de `static/css/styles.css` (bloco `THEME TOKENS`, com um `:root`
+ um bloco `[data-theme="..."]` por tema).

## Como conectar as automações reais

Todos os endpoints de API estão em **`src/web/api/rotas.py`**, cada um
com um comentário `TODO` indicando exatamente o que trocar. O padrão é
sempre o mesmo:

```python
# hoje (mock):
@api_bp.route("/automacoes/gerar_pastas/executar", methods=["POST"])
def automacoes_executar(chave):
    ...
    return jsonify({"status": "ok", "mensagem": "[MOCK] ..."})

# depois de conectar:
from src.automacao.gerar_pastas import executar as executar_gerar_pastas

@api_bp.route("/automacoes/gerar_pastas/executar", methods=["POST"])
def executar_gerar_pastas_view():
    payload = request.get_json(silent=True) or {}
    resultado = executar_gerar_pastas(
        por_turma=payload.get("por_turma", False),
        turmas=payload.get("turmas", []),
        pasta_raiz=payload.get("pasta"),
    )
    return jsonify(resultado)
```

Endpoints que precisam de conexão, por área:

| Área | Endpoint | Conectar com |
|---|---|---|
| Painel | `GET /web/api/painel/resumo` | `src/relatorios/analisa_arquivos_sere.py` |
| Turmas | `GET /web/api/turmas/lista` | `src/automacao/turmas.py` |
| Alunos | `GET /web/api/alunos/lista` | `src/automacao/alunos.py`, `alunos_completo.py` |
| Pré-matrícula | `GET /web/api/prematricula/lista` e `/fila` | `capturar_matricula.py` (prematricula.py) |
| Funcionários | `GET /web/api/funcionarios/lista` | `servidores.py` |
| Automações | `POST /web/api/automacoes/<chave>/executar` | cada script em `src/automacao/` |
| Sistema | `POST /web/api/sistema/escolher-pasta` | já funcional (tkinter, ver nota abaixo) |
| Wizard | `GET /web/api/wizard/status`, `POST /web/api/wizard/<passo>/executar` | `src/comum/credenciais.py`, `configuracao.py` |

### Seleção de pasta (janela nativa do Windows)

O botão "Clique para escolher a pasta" em qualquer automação chama
`POST /web/api/sistema/escolher-pasta`, que abre a janela **nativa**
do Windows via `tkinter.filedialog.askdirectory()` no processo do
próprio Flask, e devolve o caminho absoluto escolhido (ex.:
`C:\ARQUIVOS\ESCOLA JUDITH\ALUNOS`). Isso já está pronto e funcional,
não precisa de nenhuma conexão adicional.

Só funciona quando o Flask roda diretamente na máquina Windows do
usuário (é o seu caso). Se um dia isso rodar num servidor headless
(sem tela), o endpoint devolve um erro tratado (HTTP 500 com uma
mensagem clara) em vez de travar — o front-end mostra isso como um
toast.

O `chave` de cada automação usado pela interface já corresponde 1:1 aos
itens do menu lateral (`gerar_pastas`, `analisa_pasta`, `analisa_sere`,
`documentos`, `cruzamento`, `cep`, `sus`, `transferidos`, `parecer_fund`,
`parecer_rco`, `comprimir`, `coleta_emails`, `agendador`, `backup`,
`avisos`, `compara_anos`, `termos`, `mapear_pastas`, `mascara`,
`rematricula`) — veja a lista completa em `AUTOMACOES_DISPONIVEIS` no
topo de `rotas.py`.

## Próximos passos sugeridos

1. Trocar os mocks de `painel/resumo` e das 4 listas (`turmas`, `alunos`,
   `prematricula`, `funcionarios`) pelas funções reais — é o que dá vida
   ao Painel Principal e às telas de Menu.
2. Conectar `automacoes/<chave>/executar` uma automação por vez,
   começando pelas mais usadas (`gerar_pastas`, `documentos`).
3. Implementar `wizard/status` de verdade lendo `credenciais.py` /
   `configuracao.py`, para o passo "1ª execução" refletir o estado real.
4. Se quiser rodar tarefas longas sem travar a requisição HTTP, considere
   rodá-las em thread/subprocess e expor um endpoint de status/polling
   (a UI já tem um estado de "Executando..." pronto no botão).

## Corte etário

Tela **Menu → Corte etário** (view `corte-etario`). Quadro mês × ano de nascimento com a turma
(Berçário ao 5º ano) em que a criança entra no ano letivo escolhido: vale a idade completa até
**31/03**. Não usa API — tudo roda no navegador (`js/corte_etario.js`).

- Abre no ano letivo seguinte a partir de novembro (período de matrículas); setas ← → ou botões trocam o ano.
- Para mudar a data de corte, as turmas ou a regra do Berçário, edite as constantes no topo de `corte_etario.js`.
- **Exportar PDF** baixa o quadro em A4 paisagem, sempre nas cores do tema claro.
- Cores das turmas: variáveis `--ce-t0…--ce-t10` no fim de `styles.css`, uma paleta por tema.

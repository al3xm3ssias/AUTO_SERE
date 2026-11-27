# Alterações — perfil PEDAGOGA (mesclagem de 27/11/2026)

Base: `AUTO_SERE_mesclado_final (2).zip`. Mesclado: `perfil_pedagoga.patch` (aplicado com `patch -p1`, sem conflitos, sem rejeições).
Resultado: 19 arquivos alterados/criados, ~600 linhas adicionadas. Nenhum arquivo existente teve comportamento mudado para Administrador, Operador ou Consulta.

## Resumo

Novo perfil **Pedagoga**, independente da escada Consulta < Operador < Administrador. Ela só consulta **Painel, Turmas, Alunos e Encaminhamentos SUS**
e só executa as coletas **Turmas** (`turmas.py`) e **Alunos** (básico `alunos.py` e completo `alunos_completo.py`). É somente leitura: não grava
registro nem configuração, não apaga histórico, não envia mensagem; só troca a própria senha.

Princípio: **lista de permissões** (o que não está na lista é negado com 403, inclusive rotas criadas no futuro), validada **no servidor** em duas
camadas; esconder menu é só vitrine.

## Alterações por arquivo

### Segurança (servidor)
| Arquivo | O que mudou |
|---|---|
| `src/seguranca/politica.py` | Constante `PEDAGOGA`; conjuntos `AUTOMACOES_PEDAGOGA` (`turmas`, `alunos`), `TELAS_PEDAGOGA`, `GRUPOS_AUTOMACAO_PEDAGOGA`, `CONFIGURACOES_PEDAGOGA` (somente consulta) e `CONFIGURACOES_PEDAGOGA_EDITAVEIS` (`minha_conta`, `temas`); lista `_REGRAS_PEDAGOGA` (método + expressão de rota); funções `permite`, `motivo_da_negativa`, `automacao_permitida`, `pode_ver_tela`, `pode_ver_grupo_automacao`, `pode_ver_configuracao` e o resumo de perfil para o front. |
| `src/seguranca/usuarios.py` | `PERFIS` e `ROTULO_PERFIL` passam a incluir `pedagoga`; `Usuario.pode(metodo, caminho)` como decisão única (escada ou lista). |
| `src/seguranca/web.py` | Guarda de toda requisição usa `usuario.pode(...)` e audita a negativa com o motivo; novo `perfil_atual()`; o contexto dos templates expõe `pode_tela`, `pode_automacao`, `pode_grupo_automacao`, `pode_configuracao`, `perfil_restrito`, `config_editaveis`. |
| `src/seguranca/cli.py` | Novo comando `python -m src.seguranca criar-usuario --perfil pedagoga|operador|consulta|admin` (exige administrador já existente; aceita `--usuario`, `--nome`, `--senha-stdin`). |
| `scripts/windows/instalar.ps1` | Depois de criar o administrador, pergunta "Deseja cadastrar agora um usuário com o perfil PEDAGOGA? (S/N)". |

### Rotas e ajuda
| Arquivo | O que mudou |
|---|---|
| `src/web/api/rotas.py` | **Painel reduzido no servidor** para a Pedagoga (total de alunos, meninos, meninas, turmas, encaminhamentos SUS; pré-matrícula, documentos, raio e transferidos nem são lidos). Lista de automações filtrada por perfil. **Segunda trava** em `automacoes_executar`: 403 se o perfil não pode a automação. |
| `src/web/api/ajuda.py` | A Central de ajuda (F1) mostra à Pedagoga só os textos das telas, automações e configurações que ela usa. |

### Interface
| Arquivo | O que mudou |
|---|---|
| `src/web/templates/base.html` | Menu/seções e script de inicialização condicionados a `pode_tela`/`pode_automacao`; `body[data-perfil-restrito]`. |
| `src/web/templates/menu.html` | Itens do menu só para o que o perfil pode. |
| `src/web/templates/configuracoes.html` | Pedagoga vê só: Dados da escola, Ano letivo, Navegador, Backup automático, Senha do SERE (nunca exibida), Minha conta, Temas e Perfil; as quatro primeiras e a senha do SERE em somente consulta. |
| `src/web/templates/painel.html` | Blocos Transferidos e Pré-matrícula só aparecem se `pode_tela(...)`. |
| `src/web/static/js/app.js` | Respeita perfil restrito (sem opções guardadas, navegador, limpar histórico; campos de configuração travados). |
| `src/web/static/js/calendario.js`, `corte_etario.js` | Não quebram quando a tela não existe para o perfil (guarda `if (!$(...)) return`). |
| `src/web/static/js/usuarios.js` | Opção "Pedagoga" no cadastro e texto explicativo dos perfis. |
| `src/web/static/css/auth.css` | Regras `body[data-perfil-restrito]` e selo `.usr-selo.pedagoga`. |

### Documentação e testes
| Arquivo | O que mudou |
|---|---|
| `documentacao/Seguranca.md` | Linha do perfil na tabela e seção "Perfil Pedagoga" (regras, criação, como liberar mais algo). |
| `tests/test_perfil_pedagoga.py` (novo) | 21 testes: lista fechada, 403 em toda rota fora da lista (percorre todas as rotas do app), não herda a escada, só Turmas/Alunos (básico e completo), segunda trava, somente leitura, troca da própria senha, painel reduzido, painel/menu do admin inalterados, mudar perfil derruba a sessão, ajuda filtrada, instalador. |

## Correção extra: visual da tela "Usuários e segurança" (27/11/2026)
- **Causa:** `base.html` (tela principal) nunca carregava `auth.css`, onde ficam os estilos `.usr-*`. Por isso select e botões apareciam crus e o log sem formatação. Isso também impedia as regras `body[data-perfil-restrito]` e `body.perfil-consulta` de esconder itens na vitrine (o servidor já bloqueava de qualquer forma).
- `src/web/templates/base.html`: passa a carregar `css/auth.css` depois de `styles.css`.
- `src/web/static/js/usuarios.js`: auditoria vira **tabela** (Hora, Evento, Usuário, IP, Detalhe), agrupada por **dia** com cabeçalho "quinta-feira, 27/11/2026", mais novo primeiro; eventos de recusa/bloqueio ganham selo vermelho.
- `src/web/static/css/auth.css`: estilo de select, botões, cabeçalho fixo e linhas da auditoria no tema do sistema.

## Ajustes de 27/11/2026 (2): senha do SERE e atualização automática
1. **Pedagoga pode salvar o usuário e a senha do SERE.** `politica.py`: `senha_sere` entra em `CONFIGURACOES_PEDAGOGA_EDITAVEIS` e a regra `POST /web/api/wizard/credenciais_sere/executar` entra na lista dela. Em `rotas.py`, `wizard_executar_passo` tem segunda trava: para a Pedagoga, qualquer outro passo do assistente dá 403. `app.js`: some o painel "guardada pelo administrador" e aparece o formulário normal; `configuracoes.html`: a linha `senha_sere` não leva `data-requer="admin"` para ela (senão o CSS a esconderia). Atenção: o login do SERE é **um só para o sistema** (`credenciais/.env`); o que ela salvar vale para todos.
2. **Atualização silenciosa de Turmas e Alunos.** `rotas.py`: `POST /pedagoga/atualizar-dados` e `GET /pedagoga/atualizar-dados/status`; um trabalhador em segundo plano roda `turmas` e depois `alunos` (básico) pelas mesmas automações da tela (histórico, navegador conforme configurado, por padrão sem janela). Roda uma vez por abertura do sistema, para quando uma etapa falha (Alunos não roda sobre Turmas com erro) e nunca derruba o sistema. Sem senha do SERE salva, avisa e tenta de novo quando ela salvar. `app.js`: `iniciarAtualizacaoSilenciosa()` dispara ao abrir a tela da Pedagoga, mostra só um aviso discreto no canto e recarrega o painel ao terminar. Desligar: `PEDAGOGA_COLETA_AUTOMATICA=0`.
3. Testes: `test_perfil_pedagoga.py` agora tem 21 testes (senha do SERE, demais passos do wizard negados, atualização uma vez só, sem credenciais, desligada, ordem Turmas→Alunos e parada na falha).

## Como liberar mais algo para a Pedagoga
Editar `AUTOMACOES_PEDAGOGA`, `TELAS_PEDAGOGA`, `CONFIGURACOES_PEDAGOGA` e `_REGRAS_PEDAGOGA` em `src/seguranca/politica.py` e atualizar `PERMITIDAS` em `tests/test_perfil_pedagoga.py`.

## Verificação feita na mesclagem
- `patch --dry-run` e aplicação real: 18 arquivos, 0 conflitos. O `.ps1` tem fim de linha CRLF e foi preservado.
- `tests/test_perfil_pedagoga.py`: 15 passaram. Arquivos de teste de segurança, ajuda, calendário, menu, painel e UI (automações, calendário, escola, painel de avisos, tabelas): todos passaram.
- `tests/test_ui_componentes.py` (29 falhas) e `tests/test_ui_transferidos.py` (6 falhas) falham **igual na árvore original**, sem o patch (testes de navegador que estouram o tempo neste ambiente); não são causados pela mudança.
- A suíte completa (2.828 testes) não terminou neste ambiente por tempo; rode `python -m pytest tests -q` na sua máquina para confirmar.

## Observações
- O zip já trazia sobras de merges antigos que não foram mexidas: `src/comum/modelos_whatsapp.py.orig/.rej`, `src/servicos/whatsapp/base.py.rej`, `src/seguranca/web.py.orig`, `src/seguranca/politica.py.orig`. Vale revisar o `.rej` do WhatsApp (pode ter pedaço que não foi aplicado) e apagar os `.orig`.
- Limite: a linha de comando e o Agendador (`python -m src.comum.cli`) não passam pelo login e, portanto, não têm perfil.

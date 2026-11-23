# PENDÊNCIAS — AUTO SERE

Lista curta do que ainda falta. O detalhe e o histórico estão em [`PROXIMAS_ETAPAS.md`](PROXIMAS_ETAPAS.md) (os números, como 3b e 11q, são os mesmos) e os bugs em [`BUGS_CONHECIDOS.md`](BUGS_CONHECIDOS.md).

Atualizado em 2026-11-20 (destino dos transferidos e aviso à escola de destino; ID da matrícula em Transferidos, Base ABC e pré-matrícula; o resto segue como em 18/11). Legenda: `[ ]` pendente · `[!]` depende de ambiente real ou de decisão · `[x]` decidido/feito.

---

## 1. Validar no ambiente real (maior risco)

Quase tudo foi testado só com navegador ou dados simulados.

### SERE
- [!] Coletas de **Turmas**, **Alunos** (básico e completo) e **Funcionários**
- [!] **`vinculos`**: RH (o endpoint de estagiários foi deduzido por analogia) e leitura do holerite (depende do layout atual do site)
- [!] **`sus`/SISREG**: consulta real
- [!] Uma execução real de cada automação migrada para o registro (item 11), com "Modo de teste"

### Transferidos
- [!] Emitir, assinar, baixar e enviar de verdade com um aluno real
- [!] Leitura de QR com scans reais (testada só com PDFs gerados)
- [!] `parecer_fund`: fluxo completo no computador da escola e modelos dos demais anos

### RCO
- [!] `parecer_rco`: login, 2FA, nomes dos botões e download no site real (ajustar seletores se mudou)

### WhatsApp
- [!] Primeiro pareamento e envio com número real
- [!] Testar `whatsplay` no Windows

### Pré-matrícula e rematrícula
- [!] **BUG-PRE-001**: a consulta por CPF pode ler só o primeiro cadastro (talvez o cancelado). Confirmar quando o site voltar
- [!] Conferência ao vivo da coleta (BUG-PRE-002 está corrigido, falta validar com coleta real)
- [!] **BUG-REM-001**: o clique final de "Confirmar" é tratado como sucesso sem conferir a página

### Pareceres digitalizados (Fundamental)
- [!] Testar com scans reais, com o SERE real (item "Parecer Descritivo 2026-1"; e, no ano que vem, a descoberta automática do item do ano novo) e com e-mail real. Usar "Modo de teste" e o e-mail em "Só teste" antes de enviar às famílias

### Tela Alunos
- [!] Abrir o calendário depois de colocar a atualização: conferir se o `calendario.json` antigo foi dividido certo em `dados/<ano>/calendario.json` (o antigo fica como `dados/calendario/calendario.json.antes-da-migracao`)
- [!] Abrir com os `alunos.json` e `alunos_completo.json` reais e ver se aparecem divergências falsas (⚠)

---

## 2. Funcionalidades pendentes

### `avisos` (e-mail)
Uso real, definido em 2026-11-02 e **revisado em 2026-11-14**: comunicar **só quem está chegando** (pré-matrícula do ano letivo e previsão do próximo). Não se avisa responsável de aluno que está saindo. A tela é "Mandar avisos".

- [x] Público **escola de origem** (2026-11-14): texto com `$ALUNO`, `$CGM`, `$SERIE` ou `$TURMA` vira **um e-mail por aluno que chega**, para a escola de origem dele. Tipo de mensagem **"Transferência de aluno"** já vem pronto (pede liberação da transferência no SERE, parecer via SME e histórico escolar na pasta do aluno). ⚠️ Rode a "Consulta na Base ABC" antes: sem o vínculo o aluno fica de fora (e aparece na lista "sem vínculo")
- [x] De onde vem a escola de origem (2026-11-14): do `vinculo_base_abc` gravado na pré-matrícula/previsão pela Consulta na Base ABC; casada com `escolas_completas.json` pelo nome (se houver mais de uma parecida, não adivinha: vai para "origem fora da lista"). ⚠️ Só municipais têm e-mail na lista; escola particular/estadual fica de fora. Se a escola tem mais de um e-mail, vai o primeiro
- [x] Fonte dos alunos novos (2026-11-14): pré-matrícula do ano, previsão do próximo ano ou as duas
- [x] **Mostrar "sem e-mail" na tela** (2026-11-14): a prévia da tela nomeia quem ficaria de fora e por quê (sem e-mail, sem vínculo, a verificar, origem fora da lista)
- [x] **Envio real liberado** (2026-11-14), só depois de **Simular** o mesmo comunicado (vale 24 h); confirmação antes de enviar; pausa configurável entre e-mails; máximo por execução; quem já recebeu não recebe de novo (`AVISOS/enviados.json`), então cancelar e rodar de novo continua de onde parou; registro regravado a cada e-mail (enviados, falhas com o erro, faltantes); 3 falhas seguidas param o envio. ⚠️ **Nunca foi testado com Gmail de verdade nesta mescla**: faça primeiro um envio real para um aluno só (marque só uma unidade e "Máximo: 10")
- [x] Tela (2026-11-14): "Quais unidades" virou lista pesquisável com marcação; saíram "Só unidades cujo nome contém", o exemplo do Assunto e "E-mail de teste"; "Tipo de mensagem" carrega assunto e mensagem e dá para **salvar, ajustar e excluir modelos** (`config/modelos_avisos.json`)
- [x] **Escolher os alunos na tela** (2026-11-14): "Quais alunos" lista os alunos novos (conforme "Quais alunos novos" e "De onde vêm"), pesquisável, cada um com o estado do vínculo da Base ABC (**CGM ok** + escola de origem / vínculo a verificar / sem vínculo). Botão "Marcar quem tem CGM ok"; nenhum marcado = todos. Vale para escolas e pais. Teste de ponta a ponta: a Consulta na Base ABC (nome + nascimento + mãe da pré-matrícula) grava o CGM no cadastro e o texto de transferência sai preenchido (`test_consulta_da_pre_matricula_grava_o_cgm_e_o_aviso_de_transferencia_usa`)
- [x] **Texto por aluno na tela** (2026-11-14): caixa "Como fica a mensagem" mostra o assunto e o corpo já preenchidos com o primeiro aluno marcado (ou o primeiro da lista) e para qual escola iria; se ele não receberia (sem vínculo, escola fora da lista...), mostra o texto mesmo assim com o motivo. O texto-modelo continua com os marcadores (cada aluno recebe o seu)
- [x] **Nome da escola no formato da Base ABC** (2026-11-14): "JUDITH M SILVEIRA,E M PROFA-EI EF" agora é reconhecido (vale só o antes da vírgula; inicial solta não conta), tanto para achar a própria escola quanto a escola de origem na lista
- [x] **Aluno que já entrou na nossa escola** (2026-11-14): o vínculo da Base ABC passa a guardar `escola_anterior`/`turma_anterior`/`ano_anterior` (última linha do histórico de OUTRA escola) e o pedido de transferência vai para ela, com a série dela em `$SERIE`. ⚠️ **Vínculos gravados antes disso não têm a escola anterior**: refaça a Consulta na Base ABC desses alunos (a tela marca "já está na nossa escola, sem escola anterior no vínculo")
- [~] Público **responsáveis de quem sai**: descartado pelo usuário (2026-11-14)
- [~] E-mail de escola escrito de forma disfarçada ("nome [arroba] dominio"): **descartado** (2026-11-21): a lista vem do site da SME e todas as escolas têm e-mail
- [~] Responsável sem e-mail (pais que chegam): **não é pendência** (2026-11-21): quem fez a pré-matrícula tem e-mail no cadastro; a prévia continua nomeando o caso raro
- [?] Mensagem em HTML (hoje o e-mail sai em texto puro, sem negrito, link clicável formatado ou logotipo). **Só se você quiser** esse acabamento; sem decisão. **Anexos já funcionam** no público "escola de destino" (abaixo)
- [x] **Chamar os pais por turma e faixa de posição (2026-11-21):** no público "pais", a lista de alunos mostra a posição de cada um na turma (`pos` da pré-matrícula) e ganhou a barra **"Marcar por posição"** (turma + "do __ ao __"; "todas as turmas" marca o mesmo intervalo em cada uma). Só marca; o envio segue com prévia, simulação e confirmação. Modelo pronto **"Chamada para matrícula (pais de aluno novo)"**. Quem fica do N-ésimo em diante continua na fila e não é chamado. Use a situação **"Aguardando vaga"** (a padrão é "Matriculados"). A barra só aparece se a coleta trouxe `pos` (confirmar no real, principalmente na coleta pelo relatório .xlsx)
- [x] **Botão "Ver quem já recebeu" (2026-11-22)** na tela "Mandar avisos": lista o `AVISOS/enviados.json` (quando, para quem, aluno, assunto, anexos), mais recente primeiro, com busca. Só leitura (`GET /web/api/avisos/enviados`); os envios novos passam a guardar também o público (os antigos aparecem sem ele, exceto escola de destino). Validado no Chromium (22/11/2026) com registros gerados pelo próprio envio real e um registro no formato antigo: lista, ordem (mais recente primeiro), busca sem acento, "Atualizar" com envio novo, registro vazio e registro corrompido; o arquivo não é alterado (`tests/test_ui_avisos_enviados.py`). **Falta só olhar o seu `enviados.json` real**
- [~] Outros canais: **SERE descartado** (não é canal de comunicação); o WhatsApp é o item 7b (fila de envio), logo abaixo
- [x] Público em massa "todas as escolas/CMEIs": **sem utilidade** (2026-11-21). Falta decidir se o texto sem marcadores de aluno, que hoje vai para todas, deve ser removido da tela

### WhatsApp
- [x] **7b: fila de envio (2026-11-22)** — cartão "Fila de envio" na tela WhatsApp (`src/servicos/whatsapp/fila.py`, rotas `/web/api/whatsapp/fila/*`, modelos em `config/modelos_whatsapp.json`): pausa entre mensagens (10 s a 10 min), limite por dia (1 a 300; retoma sozinha no dia seguinte se marcado), Pausar/Continuar, cancelar item ou todos os pendentes, "pôr na fila de novo", histórico, não repete o mesmo texto para o mesmo número, 3 falhas seguidas pausam, envio real só com a permissão e o WhatsApp conectado, e põe na fila direto os alunos da pré-matrícula (comunicado oficial ou modelo). Dados em `<ano>/WHATSAPP/fila.json`. **Falta validar com o WhatsApp real** (whatsplay no Windows e gateway Docker)
  - [ ] Opcional, não pedido: variação aleatória na pausa (hoje é fixa), janela de horário (ex.: só 8h–18h) e canal WhatsApp dentro de "Mandar avisos"

### Escola de destino dos transferidos (2026-11-19/20)
- [x] **Coluna "Destino" na tela de Transferidos** + janela "Destino…": mostra a escola para onde o aluno foi (do `vinculo_base_abc` ou **preenchida à mão**) e a situação do aviso: *Avisar automaticamente* / *Encaminhado por e-mail à parte* / *Não avisar automaticamente*. O preenchimento manual fica em `destino_manual` (separado do vínculo: uma nova consulta não o apaga e ele vale no lugar do vínculo). Rotas `GET/POST /web/api/transferidos/destino/<cgm>` (recusam com automação rodando e em modo consulta)
- [x] **Público "Escola de destino dos transferidos" no `avisos`**: um e-mail por aluno que saiu, para a escola de destino, avisando que histórico, guia e parecer estão na pasta do aluno e **seguem em anexo** (modelo `transferencia_destino`; marcadores `$ESCOLA_DESTINO $ALUNO $CGM $TURMA $DATA_SAIDA`). Só recebe quem tem escola na lista de e-mails, os três arquivos da saída atual e o aviso "automático". O resto cai em listas na prévia (sem destino, vínculo a verificar, fora da lista, encaminhado, não avisar, sem e-mail, sem documentos). Vínculo que aponta para a **nossa própria escola** vai para "a verificar". Modo de teste **não** anexa documento de aluno. Limite de envio ganhou "1 e-mail" e "5 e-mails"
- [x] **2ª saída**: destino e vínculo da 1ª vão para o ciclo anterior; a nova saída começa sem destino. O aviso é por saída (ID ou CGM + data). Parecer da 1ª saída **nunca** é anexado à 2ª (sem o parecer novo digitalizado, ou com mais de um arquivo, o aluno fica sem aviso; renomeie o antigo para `NN-NOME (saída dd-mm-aaaa).ext`)
- [!] **Validar no real:** o vínculo dos transferidos na Base ABC; envio real com Gmail para **um aluno só** (simular antes, "1 e-mail", e-mail em "Só teste"); o parecer da 2ª saída com arquivos reais; abrir a tela de Transferidos e a janela "Destino…" no navegador (os testes de tela não rodaram no ambiente de desenvolvimento)
- [x] **Ciclos anteriores na tela Transferidos** (2026-11-21): quem saiu, voltou e saiu de novo ganha, sob o nome, o botão "↺ N saída(s) anterior(es)". Ele abre uma janela só de leitura com cada saída anterior (data de saída, data em que voltou, turma, ID da matrícula, selos de guia/histórico/parecer, escola de destino e o nome dos PDFs renomeados). A linha da tabela continua sendo a saída ATUAL (o status e os cartões não mudam). `/transferidos/lista` devolve `ciclos_anteriores` e `n_ciclos` por aluno; a exportação ganhou a coluna "Saídas anteriores"; ajuda F1 atualizada. Teste em `tests/test_telas_dados.py`. Janela e botão conferidos no Chromium (`tests/test_ui_tabelas.py`)

### Backup
- [x] **3b** (2026-11-14): backup automático ao fim das coletas de turmas, alunos (`alunos.py` e `alunos_completo.py`) e funcionários (`servidores.py`, `funcionarios.py`), por `backup.backup_apos_coleta()`. Motivo "automático (após a coleta de …)"; **retenção própria** de 7 (`AUTO_SERE_BACKUP_MANTER_AUTO`), para as coletas diárias não empurrarem os manuais e os de "antes de restaurar" (10 de cada ano); coletas seguidas (< 30 min) trocam o automático anterior; nunca derruba a coleta (erro vira aviso no log); `AUTO_SERE_BACKUP_AUTO=0` desliga. Testes em `tests/test_backup.py`. ⚠️ Falta decidir se vale um botão em Configurações para ligar/desligar (hoje só por variável de ambiente)

### Funcionários
- [x] Modo completo: **retoma de onde parou** (2026-11-14). Cada cadastro coletado leva `coletado_em`; se a última coleta completa foi interrompida há menos de 3 dias (`funcionarios_completo_progresso.json` com `completa: false`), a nova rodada só consulta quem faltou e mantém o `iniciado_em` original. Caixa **"Recomeçar do zero"** na tela de Funcionários força todos de novo; interrupção antiga demais ou coleta que terminou não é retomada; quem saiu da lista não fica no arquivo. Testes em `tests/test_funcionarios_completo_parcial.py`
- [!] Decidir se os termos de ciência pulam quem tem `na_escola = false`

### Transferidos
- [x] **Aluno que sai duas vezes no mesmo ano** (2026-11-18): regra do usuário: saiu, foi processado, voltou e saiu de novo → a 2ª saída tem guia, histórico e parecer próprios. O registro da 1ª vai para `ciclos_anteriores` em `transferidos.json`, os PDFs dela são renomeados `<nome> (saída dd-mm-aaaa).pdf` (se não der para renomear, nada é alterado) e o processo refaz tudo. Corrigido junto o pré-corte, que preenchia como pronto o registro da 2ª saída quando a 1ª foi antes do corte. Testes em `tests/test_fluxo_transferidos.py`. ⚠️ Falta ver como fica o parecer da 2ª saída (`PARECERES/<turma>/NN-NOME.pdf` pode ter o mesmo nome do da 1ª) e mostrar os ciclos anteriores na tela Transferidos. `deteccao_transferidos.py` (módulo antigo, só `detectar_mudancas` é usado) tem a mesma trava e não foi alterado
- [x] **Tabela "Transferidos" mostra o total da escola** (2026-11-21): `/transferidos/lista` junta `transferidos.json` (controle) com `fila_transferidos.json` (todos os transferidos). Nova coluna **"Situação no processo"**: *A processar*, *Em andamento*, *Concluído* (quem tem registro, pelos documentos), *Antes do corte*, *Retornou à escola* e *Sem data válida* (vindos da fila). A situação é recalculada pela DATA_CORTE em vigor (a fila pode ter sido gerada com outra data) e nada é gravado: a tela só lê. Quem está só na fila aparece sem documentos nem Destino, com status "Fora do processo"; quem voltou mantém os documentos que já tinha e ganha selo "Retornou". Novos: cartão "Fora do processo", filtro "Fora do processo" e caixa "Ocultar quem retornou". Os contadores Completos/Parciais/Pendentes continuam contando só quem tem registro. Exportação ganhou "Situação no processo" e "Data da saída"; ajuda F1 atualizada. Testes em `tests/test_telas_dados.py` e `tests/test_ui_tabelas.py` (este roda no Chromium). Fila ausente ou ilegível: a tela volta a mostrar só o controle, como antes
- [x] **Mapeamento de turmas do QR (só QR antigo)** (2026-11-21): novo painel em Configurações → **"Turmas do QR antigo"** (`mapeamento_turmas_qr`). Uma linha por par: o texto como está no QR (ex.: "INF 4 A") → a turma do `turmas.json`, escolhida numa lista para não errar o nome (sem `turmas.json`, vira campo de texto). Tem **Testar** (diz qual turma a leitura escolheria e por qual caminho: linha ainda não salva, mapeamento cadastrado, mapeamento do sistema ou busca por palavras), marca o par cuja turma deixou de existir ("não existe mais") e recusa linha pela metade ou texto repetido sem alterar nada. Rotas `/configuracoes/mapeamento-turmas-qr` (GET/POST) e `/testar`; `configuracao.mapeamento_turmas_qr()` / `definir_mapeamento_turmas_qr()`. A leitura (`pareceres_transferidos._mapeamento`) já lia a chave: os pares cadastrados valem acima do mapeamento embutido. Ajuda F1 do painel incluída. Testes: `tests/test_menu_transferidos.py` e `tests/test_ui_turmas_qr.py` (Chromium) **Sugestões (22/11/2026)**: a rotina de pareceres agora anota, em `dados/<ano>/qr_turmas_nao_reconhecidas.json` (`src/comum/qr_turmas_nao_reconhecidas.py`), o texto de turma do QR antigo que não casou com nenhuma turma (o arquivo continua na pasta, esperando; a simulação só mostra a dica e não grava). O painel lista esses textos num quadro no topo: **Usar** abre a linha já com o texto, **Ignorar** tira da lista; os que passam a ser reconhecidos somem sozinhos e são podados ao salvar. Testes em `tests/test_qr_turmas_nao_reconhecidas.py`, `tests/test_pareceres_transferidos.py` (rodam só com opencv, qrcode e reportlab instalados), `tests/test_menu_transferidos.py` e `tests/test_ui_turmas_qr.py`

### Pareceres digitalizados (Fundamental)
- [x] **idtipo de ano novo** (2026-11-07): o sistema acha o item `Parecer Descritivo <ano>-1` no SERE na 1ª vez e guarda o idtipo em `dados/sere_slots_descobertos.json`; não precisa mais editar `SERE_SLOTS`. O catálogo do sistema tem prioridade sobre o guardado
- [x] **QR com o ano letivo e criptografado** (2026-11-07): `AUTOSERE|PF2|…` leva ano, chamada, nome, turma e CGM (AES-GCM, chave em `credenciais/chave_qr.key`). O ano do QR é conferido com o ano letivo em uso
- [x] **Parecer para imprimir em PDF** (2026-11-07): `parecer_fund` gera PDF em `PARECERES/_PARA_IMPRIMIR/<turma>/` (LibreOffice); Word e "ambos" continuam como opção
- [!] **Validar no computador da escola**: LibreOffice no Windows gerando o PDF com o modelo real; imprimir, digitalizar e ler o QR criptografado de verdade (o QR tem mais módulos: se a leitura falhar com o scan, aumentar `LADO_QR_SEGURO_PX` em `parecer_fund.py`)
- [!] **Guardar cópia de `credenciais/chave_qr.key`** (sem ela os QR já impressos não abrem). Decidir onde fica o backup da chave

### Consulta na Base ABC (2026-11-08)
Adaptação do script antigo `consulta_transferidos_ano_anterior.py`: automação `base_abc` (menu → Consulta na Base ABC), em `src/automacao/consulta_base_abc.py`. Busca por **nome + data de nascimento + nome da mãe** (ou CGM) e registra em `dados/<ano>/buscas_base.json`: data da busca, nome, possui CGM, CGM, data de nascimento, nome da mãe e `escolas` numeradas (ano, escola, série), mais situação, observação, parecidos achados e o pedido digitado. Aluno que não está na base **não é erro**: fica registrado. Só lê do SERE.
- [x] Entrada em linha (`Nome 12/03/2015 mãe: Fulana`, ou `Nome; data; mãe`, ou CGM), homônimos separados por data + mãe, ambíguo nunca escolhido (registra os candidatos), registro "encontrado" nunca apagado por busca que não achou: coberto por teste com navegador de mentira
- [!] **Validar no SERE real** (o formulário da Base ABC não foi visto): campos Nome, Data de nascimento e Nome da mãe do formulário (`CAMPOS_NOME`, `CAMPOS_NASCIMENTO`, `CAMPOS_MAE`); se a tabela de resultados mostra a data; rótulos do cadastro (`ROTULOS_*`) para Nome, CGM, Data de nascimento e Nome da mãe. Campo Nome não achado: a execução para e lista os campos da página (mande a lista para ajustar)
- [!] Rode primeiro com "Mostrar o navegador" e o modo de teste (só o 1º aluno)
- [x] **Sem limite de candidatos (2026-11-22)**: o `LIMITE_VERIFICAR` (5) saiu; com nome comum, todos os resultados que a tabela traz na página são conferidos (abrindo o cadastro quando a tabela não mostra data/mãe). Teste `test_confere_todos_os_resultados_da_pagina_sem_limite`. [!] Se a Base ABC dividir os resultados em **várias páginas**, só a 1ª é lida (não há paginação no código): confirmar no SERE real
- [ ] **Vínculo CGM + aluno + turma de origem (2026-11-12)**: além de `buscas_base.json`, o vínculo é gravado em `vinculo_base_abc` dentro de `pre_matricula.json` (regra do ano vigente: Matriculado/Transferido) e de `previsao_alunos_<ano+1>.json` (regra da pré-matrícula: + Desistente/Reprovado), em `cadastros[cpf]` ou, para quem só está na fila, no item de `turmas_intencao`. A Base ABC passou a ler os DOIS arquivos. Campos: periodo, ano_referencia, nome, cgm, turma (origem), escola, situacao, status ("ok"|"verificar"), motivo, consultado_em. Fora da regra, sem linha do ano, duas matrículas em curso ou sem CGM: grava e marca "verificar". `pre_matricula.py` preserva `vinculo_base_abc` ao recoletar. Base do módulo "Previsão <ano+1>" (feito em 2026-11-13, ver abaixo). ⚠️ Validar no SERE real os textos de "Resultado" (Desistente/Reprovado/Aprovado) em `SITUACOES_VINCULO`.
- [x] **Previsão do próximo ano (2026-11-13)**: o arquivo da coleta do alvo "proximo" passou de `pre_matricula_<ano+1>.json` para `previsao_alunos_<ano+1>.json` (o `pre_matricula.json` do ano em uso não muda). Um `pre_matricula_<ano+1>.json` já gravado é **renomeado sozinho** na primeira leitura (`os.replace`, conteúdo intacto; se os dois existirem, vale o novo e o antigo fica para conferência). Novo módulo **Previsão <ano+1>** (menu lateral, `previsao.html` + `previsao.js`, rota `GET /web/api/previsao`, regra em `src/comum/previsao.py`): lista os **rematriculados** (`rematriculas_sucesso.json`) + os **alunos novos da pré-matrícula** (matriculados e pendentes; cancelados, cadastro refeito em outra escola e tentativas substituídas ficam de fora). Quem está nas duas fontes conta uma vez, como rematriculado (CGM ou nome + nascimento). Testes em `tests/test_previsao.py`. ⚠️ Falta validar com dados reais do SERE/pré-matrícula; a turma exibida é a de origem (rematriculado) ou a pretendida (novo): o sistema **não calcula** a turma de destino do rematriculado.
- [x] **Lista da pré-matrícula** (2026-11-08): campo "Incluir alunos da pré-matrícula" (matriculados, aguardando, os dois ou todos) lê `pre_matricula.json` e soma ao que foi digitado. ⚠️ Cadastro da pré-matrícula coletado **antes de 2026-11-14** não tem o nome da mãe (e o de antes da Previsão pode não ter a data): a busca é por nome (+ o responsável só desempata homônimos, quando é a mãe no cadastro da Base ABC). Recoletar a etapa 2 traz a data e, se o portal mostrar, a mãe. `conferido_por` diz o quanto cada aluno foi confirmado; confira à mão os "só o nome"
- [x] **Decidido (2026-11-14): a coleta da pré-matrícula guarda data de nascimento e nome da mãe.** A data já era coletada (`dDataNasc0`); agora também o `nome_mae` (`CAMPOS_CADASTRO`, ids `dNomeMae{s}`, `dMae{s}`, `dNomeMaeAluno{s}`, `dFiliacao1{s}`, `dFiliacao{s}`) e a Base ABC o usa na busca (`Consulta.mae`). ⚠️ **Os ids da mãe são tentativas: não foram vistos no portal real.** Se nenhum existir o campo fica vazio, sem custo de tempo, e a busca segue só por nome + nascimento. Mande o HTML do modal do cadastro para fixar o id certo. Cadastros já coletados não têm a mãe até a próxima coleta da etapa 2
- [x] `escolas` traz **todas** as linhas do histórico (a janela de 3 anos do script antigo saiu): **decidido manter tudo** (2026-11-19)
- [x] **`buscas_base.json` agora alimenta os cadastros (2026-11-14)**: (1) novo público **transferidos** (`transferidos.json`, só quem saiu e não voltou, busca pelo CGM): o vínculo (escola/situação do histórico) é gravado no registro dele em `vinculo_base_abc`, como já era feito na pré-matrícula; (2) caixa **"Tirar do buscas_base.json quem já foi vinculado"** (ligada por padrão): depois de gravar o vínculo no cadastro de origem, o registro sai de `buscas_base.json`, que fica só com o que não está em outro lugar (digitados e vínculos que não puderam ser gravados; nada é podado se a gravação falhou). ⚠️ Validar no SERE real o vínculo dos transferidos (a regra é a do ano vigente: Matriculado/Transferido). O `vinculo_base_abc` do transferido agora é usado na coluna "Destino" da tela de Transferidos e como escola de destino no `avisos` (ver "Escola de destino dos transferidos", abaixo)

### Pré-matrícula: opção da escola e correção de dados (2026-11-17/18)
- [x] **Regra da Opção da escola**: Opção 1 segue o fluxo; Opção 2 ou 3 com alguma escola anterior **sem situação** (ou já com matrícula) → o aluno **não é registrado** (sai dos cadastros e contatos; aparece em Cancelados com o motivo "NOSSA ESCOLA NÃO É A 1ª OPÇÃO"); Opção 2 ou 3 com **todas as anteriores já com situação** → **fila de análise**. Vale nas etapas 2 e 4. Testes em `tests/test_pre_matricula.py` (o simulador `FakePage` foi atualizado ao fluxo atual do período `select#anoLetivo`: 16 testes antigos já falhavam por isso)
- [x] **Aba "Fila de análise"** na tela Pré-matrícula (com o que cada escola anterior respondeu). O aluno **sai sozinho** quando a nossa opção ganha situação (matriculado ou cancelado). Corrigido junto: o aluno "não é a 1ª opção" aparecia como Pendente e o da fila aparecia como Matriculado
- [x] **Corrigir dados pela tela** (nome do aluno, nascimento, mãe, responsável, telefones, e-mail; o CPF não muda): rotas `GET/POST /web/api/prematricula/registro/<cpf>`. A correção fica em `correcoes_manuais` no `pre_matricula.json` e é **reaplicada em todo salvamento**, senão a próxima coleta traria de volta o nome errado do site. Recusada com automação rodando e em ano de consulta; guarda `pre_matricula.json.antes_da_edicao` (só a última). Só o `pre_matricula.json` é editável: o `previsao_alunos_<ano>.json` não. Testes em `tests/test_pre_matricula_edicao.py`
- [!] Validar a regra da Opção com cadastros reais (os textos que as outras escolas escrevem na situação variam)
- [ ] Conferir se a Etapa 4 reconsulta quem está na fila de análise: o aluno só sai da fila quando uma coleta traz a situação nova da nossa opção
- [ ] Os outros JSONs (`previsao_alunos_<ano>.json`, `transferidos.json`...) ainda não têm edição pela tela

## 2b. Arquitetura: banco de dados local (IDEIA do usuário, 2026-11-18: só registrar, NÃO implementar agora)

> **Atualização 2026-11-18 — decisão do usuário: NÃO usar banco de dados (as desvantagens pesam demais).** O problema de fundo (identidade de cada período do aluno) foi resolvido com uma **ponte em JSON**, ver "2b-1" logo abaixo. O texto a seguir fica como registro da ideia do banco, caso algum dia volte a valer a pena.

### 2b-1. ID por matrícula: `turmas_relacional.json` (IMPLEMENTADO em 2026-11-18, falta validar no SERE real)

- **O que é.** `dados/<ano>/turmas_relacional.json` dá um ID (`2026-0007`) a cada **período** do aluno na escola. Entra, sai, volta e sai de novo = dois IDs, ligados pelo CGM. Código: `src/comum/matriculas.py`. Testes: `tests/test_matriculas.py`.
- **Por que existe.** A listagem do SERE tem **uma só coluna de data**: para Matriculado é a data da matrícula; para Transferido vira a **data da saída**. Ao transferir, a data de entrada some do `turmas.json` (reescrito inteiro a cada coleta). A ponte só recebe dados e lembra das duas datas.
- **Como roda sozinho.** `turmas.py` chama `registrar_matriculas_sem_falhar` a cada coleta (também na rotina diária), antes de gravar o `turmas.json`. Nunca derruba a coleta.
- **Campos novos nas linhas do `turmas.json`:** `ID_MATRICULA`, `Data Entrada`, `Data Transferência`. **`Data Matricula` não mudou** (12 arquivos do `src` e 22 de testes a leem como data da movimentação).
- **Regras de casamento** (por CGM, em ordem de data; o **nome nunca é usado**): matrícula casa por CGM + data; saída fecha o período em aberto cuja entrada é anterior; qualquer dúvida vira `status: "verificar"` com o motivo (data da matrícula ou da saída corrigida no SERE, transferência desfeita, duas matrículas em aberto, situação não prevista).
- **Segurança do arquivo:** gravação atômica + cópia `.antes` + trava entre processos; arquivo ilegível **não** é tratado como vazio (regeneraria os IDs); só grava quando algo mudou; entra no backup junto com os demais `.json` do ano.
- **Comandos:** `python -m src.comum.matriculas` (reaplica o `turmas.json` atual), `--semear` (reaplica os `turmas.json` dos backups do ano, recuperando a entrada de quem já saiu; **só funciona ANTES da primeira coleta**, com a ponte vazia, senão recusa), `--verificar` (lista o que conferir), `--conferido ID --nota "..."`.
- **Pendente:**
  - [ ] **Validar no SERE real:** o aluno que volta recebe mesmo uma nova `Data Matricula`? Transferidos continuam aparecendo no `turmas.json`? Antes da 1ª coleta com o código novo, rodar `python -m src.comum.matriculas --semear` e ver quantos ficam `verificar`.
  - [ ] Quem já estava Transferido quando a ponte nasceu fica com `data_matricula: null` (o SERE não informa); `--semear` recupera o que os backups ainda tiverem.
  - [x] **Transferidos e Base ABC usam o ID (2026-11-20):** cada registro de `transferidos.json` guarda `id_matricula` (o período da saída). Com ID dos dois lados o ID decide: igual = mesma saída (data corrigida no SERE não refaz nada); diferente e data mais nova = nova saída (novo ciclo, sem exigir a saída anterior na fila); diferente com a mesma data = ponte refeita (adota o ID novo, guarda o antigo em `id_matricula_anterior`, não cria ciclo). Registro antigo sem ID adota o ID na primeira coleta. O ciclo anterior guarda `id_matricula` e `arquivos` (nomes dos PDFs renomeados). A Consulta na Base ABC dos transferidos leva o ID e **só grava o vínculo se o registro ainda for da mesma saída**; o aviso à escola de destino também guarda o ID (o "aviso enviado" resiste a data corrigida). Ficou como estava: os PDFs continuam renomeados `<nome> (saída dd-mm-aaaa).pdf` e os pareceres continuam em `PARECERES/<turma>/NN-NOME.ext`
  - [ ] Avaliar trocar o significado de `Data Matricula` por um auxiliar `data_movimentacao()` (só agora faz sentido; 12 arquivos do `src` e 22 de testes a leem)
  - [x] **Aluno da pré-matrícula ligado ao ID quando ganha CGM (2026-11-20):** `matriculas.ligar_pre_matricula` (roda ao fim da coleta de turmas e ao fim de cada Consulta na Base ABC; também `python -m src.comum.matriculas --ligar-pre-matricula`). Para cada cadastro/item de `pre_matricula.json` e `previsao_alunos_<ano>.json` com vínculo da Base ABC **ok** e CGM que já tem matrícula na ponte, grava `id_matricula` no cadastro e `pre_matricula: {arquivo, ligado_em}` no período da ponte (o CPF nunca vai para a ponte). Vínculo a verificar não liga; ligação válida nunca é trocada; CGM com mais de um período liga o **mais antigo** e é contado no log; arquivo ilegível nunca é sobrescrito. A coleta da pré-matrícula preserva `id_matricula`. ⚠️ Linhas do `turmas.json` sem CGM continuam fora da ponte
  - [!] Validar no real: o aluno da pré-matrícula que entra na escola aparece com o mesmo CGM do vínculo da Base ABC, e a ligação cai no período certo
  - [ ] Opcional: registrar a conferência como automação na tela (hoje é por linha de comando).
  - [ ] Duas execuções do `turmas.py` ao mesmo tempo já são protegidas na ponte; o item 11q (trava geral por processo) continua aberto.

**Problema.** O sistema cresceu e hoje guarda a mesma pessoa em vários JSONs (`turmas.json`, `alunos*.json`, `pre_matricula.json`, `previsao_alunos_<ano>.json`, `transferidos.json`, `fila_transferidos.json`, `buscas_base.json`, `rematriculas_sucesso.json`), ligados por **CGM, CPF ou nome + nascimento + nº da chamada**. Isso gerou remendos:
- 2ª saída do mesmo aluno (`ciclos_anteriores` e PDFs renomeados à mão);
- correções manuais que precisam ser reaplicadas a cada coleta (`correcoes_manuais`);
- aluno da pré-matrícula só tem CPF (ainda não tem CGM), e o vínculo com a Base ABC (`vinculo_base_abc`) é copiado em dois arquivos;
- "mesmo aluno com chamada diferente" decidido por nome + nascimento (frágil com nome errado, homônimo ou nome corrigido);
- trava de execução simultânea só por processo (item 11q) e vários programas gravando os mesmos arquivos.

**Ideia.** Um **banco de dados local** (arquivo único, sem servidor; SQLite é o candidato natural, já vem no Python) e um **ID exclusivo e aleatório por aluno** (a pessoa), no lugar de depender de CGM/CPF/nome:
- tabela de **pessoas** (id aleatório, nome, nascimento, mãe...);
- tabela de **identificadores** ligados à pessoa (CGM, CPF, chamada por ano, id do site da pré-matrícula...), cada um com a data em que passou a valer. Assim um CGM que aparece depois, ou um nome corrigido, não cria pessoa nova;
- **matrículas/vínculos** por ano (turma, chamada, situação, datas) e **eventos** (matrícula, transferência, retorno, nova saída). Quem sai e volta mantém o histórico do que aconteceu, e cada saída é um ciclo com seus documentos;
- **documentos** (guia, histórico, parecer: emitido, assinado, enviado) ligados ao evento, não ao CGM;
- **correções manuais** como dado de primeira classe (campo, valor do site, valor corrigido, quando), em vez de reaplicar por cima do JSON;
- cada **coleta** vira uma carga que atualiza a pessoa, não um arquivo que substitui o anterior.

**A decidir antes de começar (não decidido):**
- [ ] SQLite ou outro; onde fica o arquivo e como entra no `backup` (hoje o backup copia JSONs por ano letivo);
- [ ] como migrar: ler os JSONs atuais e juntar pessoas duplicadas (regra de junção e tela para conferir os casos duvidosos); se os JSONs continuam existindo como exportação/cópia de segurança;
- [ ] se o banco é por ano letivo (como `dados/<ano>/`) ou único, com o ano dentro das tabelas (a pessoa atravessa os anos);
- [ ] como fica o modo "somente consulta" (ano anterior) e a troca de ano letivo;
- [ ] ordem de migração: começar por pré-matrícula + transferidos (onde mais dói) ou por tudo;
- [ ] impacto nos testes (hoje quase todos montam JSONs em pasta temporária) e nas telas, que leem direto dos JSONs.

**Não fazer agora.** Antes disso, as pendências de validação no ambiente real (seção 1) e a limpeza (seção 3) têm prioridade, porque o banco só compensa depois que o sistema estiver estável.

---

## 3. Limpeza e robustez

- [ ] **11q**: a trava contra execução simultânea é por processo; criar arquivo de lock em `locks/`
- [ ] Teste intermitente `test_ui_automacoes.py::test_funcionarios_e_vinculos...` (o rótulo "Sistema" cobre o item "Vínculos"); falha também no zip original
- [ ] Modo consulta: desabilitar os botões de escrita das demais telas (hoje o servidor recusa, mas o botão continua clicável)
- [ ] Editar `config_usuario.json` à mão com o programa aberto só vale ao reiniciar (a faixa avisa e oferece "Aplicar agora")
- [ ] Rodar `python -m pytest tests` na sua máquina para ter a linha de base

### Código duplicado (conferido em 2026-11-02)
- [ ] Apagar `src/automacao/sere_api.py`, `sere_limpeza.py`, `sere_upload.py` e `sere_utils.py`: são versões antigas e nenhum arquivo as importa (o projeto usa as de `src/comum/`)
- [ ] Apagar `src/comum/executar_{aluno,analisa,documento,espec,transferidos,validar}.py`: são cópias idênticas das de `src/automacao/`, **que são as usadas** (o `registro_scripts.py` importa de lá). Atenção: não apagar as de `src/automacao/`. O `src/comum/executar_limpeza.py` só existe lá e é usado, fica
- [ ] Apagar `src/automacao/test_gerar_pastas.py` (idêntico a `tests/test_gerar_pastas.py`)

---

## 4. Ajuda para os usuários

- [x] Ajuda (F1) de todas as telas, abas, painéis, janelas e automações: feita em `src/comum/ajuda*.py` + `static/js/ajuda.js` (os três `partials/help/*.html` vazios não são mais necessários e podem ser apagados) Atualizada em 2026-11-17 com os recursos novos: avisos (envio real, escola de origem, unidades, alunos, modelos), Base ABC (vínculo, escola anterior, limpeza), funcionários (retomada), backup automático, turmas e pré-matrícula (nome da mãe); `tests/test_ajuda.py` confere.

---

## 5. Decidido

- [x] **10g**: o wizard (1ª execução) fica só com o modo **básico** de Alunos, porque o completo demora mais; o completo segue em Automações → Alunos
- [x] **Documentação e arquivos soltos** (2026-11-02): porta 8000 corrigida em `src/web/README.md` e `diagrama_de_funcionamento.md`; `backup_auto_sere.py` usa a pasta da instalação (não mais `C:\Auto_sere` fixo); tarefa "Bootstrap: criar_projeto.py" removida do `.vscode/tasks.json` (o script não é mais necessário)
- [x] **Não são pendência:** `config_usuario.json` com `setup_concluido = false` e unidade sem dados (preenchido quando o usuário informa os dados); `AUTO_SERE_MAPA.txt` vazio (ignorado); `BUGS_CONHECIDOS.md` (só recebe bugs quando aparecerem; nenhum achado até agora)
- [x] **Calendário por ano letivo** (2026-11-02): `dados/<ano>/calendario.json`; voltando o ano aparece o calendário daquele ano (só consulta); o arquivo único antigo é dividido por ano na primeira abertura e guardado, sem apagar nada
- [x] **Pareceres digitalizados do Fundamental** (2026-11-02): lê o QR novo (`AUTOSERE|PF|ano|CGM`), arquiva na turma, envia ao SERE e por e-mail ao responsável (e-mail: não enviar / só teste / enviar). A leitura do QR já existia; o que faltava era usá-la com o QR novo
- [x] **10h**: a tela Alunos une `alunos.json` e `alunos_completo.json` numa ficha única, com todos os campos sempre visíveis e "—" onde falta dado (2026-11-02). O HTML fica todo em `alunos_completo_cards.html` (não apagar); `alunos_cards.html` só o inclui
- [x] **Sem banco de dados** (2026-11-18): decidido não implementar (ver 2b); a identidade de cada período do aluno fica em `dados/<ano>/turmas_relacional.json` (ID por matrícula, ligado pelo CGM), alimentado a cada coleta de turmas
- [x] **Funcionários completo salva aos poucos** (2026-11-02): grava a cada 5 cadastros, não encolhe o arquivo no meio da coleta e, se parar (cancelada, erro ou queda), avisa no log e na tela de Funcionários

---

## Ordem sugerida

1. Rodar `pytest tests` (linha de base)
2. Limpar as duplicatas (seção 3), conferindo antes qual cópia é a usada
3. Execução real com um aluno no SERE (transferidos e coletas); fechar os `[!]`
4. Confirmar BUG-PRE-001 quando o site da pré-matrícula voltar
5. Testar o `avisos` com Gmail de verdade (um aluno só) e conferir o vínculo da Base ABC dos alunos que chegam
6. Lock de execução (11q)
7. ~~Só então a fila do WhatsApp~~ (feita em 2026-11-22, mas **ainda sem teste com WhatsApp real**: faça os itens 1 a 5 antes de usar com pais de verdade)

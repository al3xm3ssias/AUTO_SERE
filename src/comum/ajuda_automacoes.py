"""
ajuda_automacoes.py — textos da ajuda (tecla F1) de cada automação
===================================================================
Escrito à mão: o que a automação faz, quando usar, o que preparar antes, o que ela grava e os cuidados.
Os CAMPOS da tela (turma, situação, CGM, modo de teste, opções próprias) NÃO se repetem aqui: src/comum/ajuda.py os
lê do registro de scripts (src/comum/registro_scripts.py) na hora de montar a ajuda, então nunca ficam
desatualizados. Para criar a ajuda de uma automação nova, basta uma entrada em AUTOMACOES (o teste
tests/test_ajuda.py reclama se faltar).

Nomes de arquivos, pastas e botões só aparecem aqui se existem no código; em caso de dúvida, o texto é genérico.
"""
from __future__ import annotations

from src.comum.ajuda_conteudo import R

# Grupos do menu lateral (Automações), na ordem em que aparecem.
GRUPOS: list[tuple[str, str]] = [
    ("cadastros", "Cadastros"),
    ("matricula", "Matrícula"),
    ("transferidos", "Transferidos"),
    ("pareceres", "Pareceres"),
    ("documentos", "Documentos"),
    ("saude", "Saúde"),
    ("comunicacao", "Comunicação"),
    ("sistema", "Rotinas e sistema"),
]

# ───────────────────────────── a tela de execução, em geral ─────────────────────────────
# Mostrado em TODA automação, na seção "Como executar".

COMO_EXECUTAR = [
    "Escolha as opções do formulário (cada campo está explicado abaixo em **Campos desta tela**).",
    "Confira a **Prévia**, logo abaixo dos campos: ela conta quantos alunos serão processados com as escolhas atuais, sem executar nada. "
    "Se houver erro de preenchimento, ele aparece ali em vermelho e a execução não começa.",
    "Clique em **Executar tarefa**. Nas automações que alteram dados, abre antes a janela **Confirmar execução** com o aviso e a prévia.",
    "Acompanhe o **registro** que aparece sob o botão: as últimas linhas do que o script está fazendo. O botão vira **Cancelar execução** enquanto roda.",
    "Se o script precisar de uma informação (por exemplo, um código enviado por e-mail), abre uma janela para você digitar.",
    "Quando termina, aparece um aviso (concluída, cancelada ou erro) e o resultado entra no **Histórico**, no fim da tela.",
]

SECOES_DA_TELA = [
    ("Executar tarefa", "Inicia a automação. Durante a execução vira **Cancelar execução** (vermelho); clique para parar. Em anos em somente consulta o botão fica desativado.", "#btn-executar-tarefa"),
    ("Voltar para automações", "Volta à lista de automações. Uma automação que está rodando continua rodando.", "#btn-voltar-automacoes"),
    ("Prévia", "Texto \"Prévia: …\" que diz o que será processado com as escolhas atuais.", "#campos-automacao"),
    ("Configurações do script",
     "Mostra tudo que o script usa: **Escolhido a cada execução** (as opções do formulário), **Opções guardadas do script** (modos que ficam salvos) e "
     "**O que o sistema guarda e este script usa**. Cada configuração do sistema tem uma bolinha: verde = configurada, vermelha = falta configurar; "
     "o botão **Alterar** leva ao painel certo em Configurações.", "#secao-config-script"),
    ("Opções guardadas do script",
     "Aparece quando o script tem modos ou opções que ficam salvos (por exemplo, \"modo rápido\"). Marque e clique em **Salvar opções** — nada é gravado ao "
     "só marcar; vale a partir da próxima execução. **Voltar ao padrão** restaura o modo completo.", "#cfg-flags"),
    ("Histórico",
     "Lista as execuções anteriores deste script, da mais recente para a mais antiga. Cada linha mostra data, resultado (Concluída, Concluída com erros, Falhou ou "
     "Cancelada), totais ✔/✖/⚠ e a duração. Clique para abrir: colunas **Deu certo** e **Deu errado**, avisos, as opções usadas e o fim do registro.", "#secao-historico-script"),
    ("Atualizar (histórico)", "Recarrega a lista de execuções.", "#btn-historico-atualizar"),
    ("Apagar histórico", "Apaga só o histórico deste script. Nada do que ele gerou ou enviou é tocado. Pede confirmação.", "#btn-historico-limpar"),
]

# Explicação dos componentes que o registro declara em `recursos`.
COMPONENTES = {
    "turma": ("Turma",
              "Escolha **Todas as turmas**, um ano inteiro (**Por ano**, todas as turmas daquele ano) ou uma **turma específica**. "
              "Precisa do `turmas.json`; se ele não existe aparece um aviso para executar antes a automação **Turmas**.",
              "#comp-turma"),
    "situacao": ("Processar",
                 "Marque **Matriculados** (marcado por padrão) e/ou **Transferidos**. A escolha vale junto com a turma.",
                 "#comp-matriculados"),
    "cgm_obrigatorio": ("CGMs",
                        "Digite os CGMs, um por linha ou separados por vírgula ou ponto e vírgula. A tela confere em tempo real quantos são válidos, repetidos ou "
                        "não encontrados. É obrigatório nesta automação.",
                        "#comp-cgm"),
    "cgm_opcional": ("CGMs (opcional)",
                     "Se você preencher, **só estes alunos** são processados e a turma e a situação são ignoradas. Um por linha ou separados por vírgula ou ponto e vírgula; "
                     "a tela confere quantos são válidos, repetidos ou não encontrados.",
                     "#comp-cgm"),
    "erros": ("Reprocessar só o que deu erro",
              "Refaz apenas o que falhou na última execução. Quando marcado, a turma e a situação são ignoradas.",
              "#comp-erros"),
    "teste": ("Modo de teste", None, "#comp-teste"),       # o texto vem do próprio script (ajuda_teste)
    "debug": ("Modo debug (análise)", None, "#comp-debug"),  # idem (ajuda_debug)
}

# ───────────────────────────── cada automação ─────────────────────────────

AUTOMACOES: dict[str, dict] = {

    # ───── Cadastros ─────
    "turmas": {
        "grupo": "cadastros",
        "resumo": "Percorre o SERE (Consulta Padrão → Por Turma) e coleta, para cada turma da escola, a lista de alunos com CGM, nome, nascimento, idade, sexo, "
                  "situação e data de matrícula. É a base de quase todo o resto do sistema.",
        "quando": "Na configuração inicial e sempre que houver matrícula, transferência ou troca de turma no SERE.",
        "antes": ["Salvar o login do SERE em Configurações.", "Preencher os dados da escola."],
        "resultado": ["Grava `turmas.json` do ano letivo em uso.",
                      "Refaz sozinha a fila de transferidos (`fila_transferidos.json`) a cada coleta.",
                      "Dá um ID a cada período do aluno na escola e guarda a data de entrada e a de saída em `turmas_relacional.json` "
                      "(as linhas do `turmas.json` ganham `ID_MATRICULA`, `Data Entrada` e `Data Transferência`).",
                      "Ao terminar, cria um backup automático dos dados."],
        "cuidados": ["Não roda ao mesmo tempo que outra coleta de Turmas: o sistema recusa a segunda."],
        "veja_tambem": [R("tela", "turmas"), R("automacao", "alunos"), R("automacao", "gerar_pastas"), R("automacao", "transferidos_fila")],
    },
    "alunos": {
        "grupo": "cadastros",
        "resumo": "Coleta o cadastro dos alunos no SERE, em dois modos: **Básico** (lê a tela de consulta de cada aluno: documentos, filiação, endereço e contatos) e "
                  "**Completo** (lê a tela de edição, com cerca de 60 campos: deficiências, recursos de prova, perfil socioeconômico, atendimento especializado).",
        "quando": "Para ter a ficha dos alunos atualizada na tela Alunos. Use o modo Completo quando precisar de todos os campos.",
        "antes": ["Executar **Turmas** antes (o modo Completo precisa do `turmas.json`).", "Login do SERE salvo."],
        "resultado": ["Modo Básico grava `alunos.json`; modo Completo grava `alunos_completo.json`.",
                      "O modo Completo salva aos poucos e registra os erros, então pode ser retomado."],
        "cuidados": ["O modo Completo é bem mais lento.", "Duas coletas de Alunos não rodam juntas."],
        "veja_tambem": [R("tela", "alunos"), R("automacao", "turmas")],
    },
    "aluno": {
        "grupo": "cadastros",
        "resumo": "Envia ao SERE os documentos da pasta de digitalização **só dos alunos que você informar pelo CGM**.",
        "quando": "Quando poucos alunos receberam documentos novos e não vale processar a escola inteira.",
        "antes": ["Documentos do aluno na pasta de digitalização, na pasta dele.", "Login do SERE salvo."],
        "resultado": ["Anexa os documentos no SERE (altera dados lá)."],
        "cuidados": ["Pede confirmação antes de enviar, com a quantidade de alunos.",
                     "Marque **Só quem ainda tem documento pendente** para pular quem já está completo."],
        "veja_tambem": [R("automacao", "espec"), R("automacao", "cruzamento"), R("configuracao", "pasta_digitalizacao")],
    },
    "funcionarios": {
        "grupo": "cadastros",
        "resumo": "Coleta no SERE a lista e o cadastro dos funcionários e servidores da escola, pelo menu Censo Escolar → Funcionário/Docente.",
        "quando": "Quando entrou ou saiu alguém, ou para atualizar contatos e formação.",
        "antes": ["Login do SERE salvo."],
        "resultado": ["Modo Básico: `funcionarios.json` (nome, CPF, função, RG, mãe, e-mail, formação, turmas).",
                      "Modo Completo: também `funcionarios_completo.json` (documentos, filiação, endereço), consultando cada um pelo CPF."],
        "cuidados": ["O modo Completo é mais lento. Sem marcar **Atualizar a lista antes**, ele reaproveita a lista já salva.",
                     "Se a coleta completa foi interrompida há menos de 3 dias, rodar de novo continua de onde parou e só consulta quem faltou. Marque **Recomeçar do zero** para consultar todos.",
                     "Ao terminar, o sistema cria um backup automático."],
        "veja_tambem": [R("tela", "funcionarios"), R("automacao", "vinculos")],
    },
    "vinculos": {
        "grupo": "cadastros",
        "resumo": "Cruza os funcionários do SERE com o RH da Prefeitura para achar a matrícula, o cargo e a data de admissão, e comprova pelo holerite que cada um "
                  "trabalha nesta escola. Quem não consta no RH é marcado como **terceirizado**.",
        "quando": "Para ter a matrícula de cada servidor (necessária para os termos de ciência) e separar servidores de terceirizados.",
        "antes": ["Login do SERE salvo.", "Internet para consultar o RH da Prefeitura."],
        "resultado": ["Grava as matrículas e os vínculos dos funcionários; a lista do RH baixada fica reaproveitada por 24 horas."],
        "cuidados": ["O modo completo é o mais lento: uma consulta ao RH a cada 5 segundos, mas as já feitas ficam em cache.",
                     "Cada **Modo de consulta** está explicado nos campos abaixo."],
        "veja_tambem": [R("automacao", "funcionarios"), R("automacao", "termos"), R("tela", "funcionarios")],
    },
    "compara_anos": {
        "grupo": "cadastros",
        "resumo": "Compara o `turmas.json` de dois anos letivos e gera uma planilha: quem **continua** (e se foi promovido, ficou na mesma série ou mudou de turma), "
                  "quem **saiu**, quem **entrou** e os **transferidos**.",
        "quando": "No fim do ano, para ver a movimentação de uma turma de um ano para o outro.",
        "antes": ["Ter o `turmas.json` dos dois anos (cada um em `dados/<ano>/`)."],
        "resultado": ["Gera uma planilha com o resultado. Cada aluno cai em uma só categoria (o CGM liga o mesmo aluno entre os anos)."],
        "cuidados": ["Só lê arquivos: não acessa o SERE e não altera nada.",
                     "Quem saiu aparece como \"Concluiu a etapa\" (estava na última série da escola) ou \"Verificar\" (saiu antes de concluir)."],
    },
    "sheets": {
        "grupo": "cadastros",
        "resumo": "Cria ou atualiza no Google Sheets a planilha das turmas (uma aba por turma) a partir do `turmas.json`. Só grava o que mudou. Também confere o acesso à planilha.",
        "quando": "Depois de coletar Turmas, para manter a planilha da secretaria em dia.",
        "antes": ["Planilha cadastrada em **Planilhas do Drive** (finalidade \"Planilha das Turmas\"), ou escolha **Criar uma planilha nova**.",
                  "Acesso ao Google configurado."],
        "resultado": ["**Atualizar**: compara o `turmas.json` com cada aba pelo CGM e grava só as células que mudaram; alunos novos entram no fim da aba. "
                      "CPF, SUS, Idade e Escola de origem existentes nunca são tocados.",
                      "**Criar**: cria a planilha com cabeçalhos, preenche e guarda o link no cadastro.",
                      "**Só verificar o acesso**: confere se a planilha existe e quais abas tem; não grava nada."],
        "cuidados": ["A caixa **Simulação** vem marcada: mostra o que seria feito sem gravar. Desmarque para gravar de verdade.",
                     "Nada é apagado nem regravado por inteiro."],
        "veja_tambem": [R("tela", "planilhas"), R("automacao", "turmas"), R("automacao", "planilha_modelo")],
    },

    # ───── Matrícula ─────
    "prematricula_completa": {
        "grupo": "matricula",
        "resumo": "Roda o processo completo da pré-matrícula em 4 etapas, com o mesmo login: **1) Coleta** das filas de cada turma, **2) Cadastro** completo de cada CPF, "
                  "**3) Contatos** (arquivo para importação) e **4) Pendentes** (nova consulta de quem ainda está pendente).",
        "quando": "Durante o período de pré-matrícula, para acompanhar a fila e os cadastros.",
        "antes": ["Salvar o login da Pré-matrícula em Configurações."],
        "resultado": ["Grava/atualiza `pre_matricula.json` sem apagar o histórico.",
                      "No cadastro (etapa 2) guarda também a data de nascimento e, quando o portal mostrar, o nome da mãe, que a Consulta na Base ABC usa na busca.",
                      "A coleta do próximo ano letivo grava `previsao_alunos_<ano>.json`, usado na tela Previsão.",
                      "Com **Enviar os contatos ao Google Contatos** marcado, cada responsável vira um contato no Google (além do CSV): criado na 1ª vez e **atualizado** nas seguintes, sem duplicar. "
                      "Ano vigente: rótulo do ano (ex.: 2026). Só próximo ano: dois rótulos, \"Pré-matrícula <ano>\" e \"Aluno <ano>\". Contatos enviados ficam registrados em `dados/google_contatos.json`.",
                      "Ao terminar, o sistema pode avisar os responsáveis pelo WhatsApp (cadastro recebido / matrícula aprovada); cada aviso vai uma vez por aluno, e no modo simulado nada sai."],
        "cuidados": ["Só lê o site; não altera cadastros no portal. Pode levar vários minutos.",
                     "**Cadastro refeito (Escolas Escolhidas do último cadastro):** se a nossa escola é a **Opção 1**, o fluxo é o normal. "
                     "Se é a **Opção 2 ou 3** e alguma escola anterior ainda **não tem situação**, o aluno **não é registrado** (a escola da Opção 1 é quem cancela ou matricula): "
                     "sai dos cadastros e dos contatos e fica como Cancelado, motivo \"nossa escola não é a 1ª opção\". Se alguma anterior já matriculou, também não entra.",
                     "Se é a Opção 2 ou 3 e **todas as anteriores já têm situação** (texto livre das outras escolas, por exemplo \"A escola não dispõe de vaga no momento\"), "
                     "o aluno vai para a **fila de análise**: a escola decide se matricula ou confirma antes com a Central de Matrícula. "
                     "Ele aparece na aba **Fila de análise** da tela Pré-matrícula (a marca fica em `pre_matricula.json`: `fila_analise`, `encaminhado_de`) e sai de lá quando a nossa opção ganha uma situação.",
                     "A regra vale nas etapas **2 (Cadastro)** e **4 (Pendentes)**.",
                     "**Google Contatos:** exige a People API ativada no Google Cloud e a conta Google que será dona dos contatos (credencial OAuth, não conta de serviço). "
                     "Na 1ª vez abre o navegador para autorizar. Se falhar, o CSV sai normalmente e o processo não para. Quem sai dos dados (aluno cancelado) **não** é apagado do Google. "
                     "**Simulação do Google Contatos** só mostra quantos seriam criados e atualizados, sem falar com o Google."],
        "veja_tambem": [R("tela", "prematricula"), R("tela", "previsao"), R("tela", "whatsapp"), R("configuracao", "senha_prematricula")],
    },
    "rematricula": {
        "grupo": "matricula",
        "resumo": "Rematrícula automática: para cada turma escolhida, abre no SERE a lista de matriculados e, aluno por aluno, entra na **Área do Aluno** com o CPF do "
                  "responsável e a chave de acesso, e confirma a matrícula online na escola sugerida.",
        "quando": "No período de rematrícula.",
        "antes": ["Executar **Gerar chaves de acesso** (opcional, mas deixa tudo mais rápido: quem tem chave salva entra direto).", "Login do SERE salvo."],
        "resultado": ["Rematricula os alunos no SERE (altera dados lá).", "Quem deu certo alimenta a tela **Previsão**; quem falhou fica para **Reprocessar só o que deu erro**."],
        "cuidados": ["Pede confirmação antes de executar.",
                     "**Modo de teste** rematricula 1 aluno por turma; **Testar com 1 único aluno** rematricula só o primeiro pendente, no total. Nenhum dos dois é simulação.",
                     "Se uma chave salva não funcionar (expirada), uma nova é gerada na hora."],
        "veja_tambem": [R("automacao", "gerar_chaves"), R("tela", "previsao")],
    },

    # ───── Transferidos ─────
    "transferidos_fila": {
        "grupo": "transferidos",
        "resumo": "Lista, a partir do `turmas.json`, todos os transferidos e marca quem entra no processo automático pela **data de corte**.",
        "quando": "Para ver quem entra no processo antes de gerar os documentos. A fila também é refeita sozinha a cada coleta de Turmas.",
        "antes": ["Ter o `turmas.json` atualizado."],
        "resultado": ["Grava `fila_transferidos.json` (temporário: não edite à mão) e atualiza o `transferidos.json` (controle permanente)."],
        "cuidados": ["Com **Simulação**, só mostra quem entraria e quem fica de fora pela data de corte, sem gravar nada.",
                     "O mesmo aluno que voltou à escola não é refeito (a identidade é nome + data de nascimento).",
                     "Se ele voltou e **saiu de novo**, a 2ª saída tem documentos próprios: o registro da 1ª vai para `ciclos_anteriores` em `transferidos.json`, "
                     "os PDFs dela são renomeados \"<nome> (saída dd-mm-aaaa).pdf\" e o processo refaz guia, histórico e parecer. "
                     "Se um PDF antigo estiver aberto e não puder ser renomeado, nada é alterado: feche-o e rode de novo."],
        "veja_tambem": [R("configuracao", "data_corte_transferidos"), R("automacao", "transferidos_gerar"), R("tela", "transferidos")],
    },
    "transferidos_gerar": {
        "grupo": "transferidos",
        "resumo": "No SERE, emite, assina e baixa o **histórico escolar** e a **guia de transferência** dos alunos da fila, salvando os PDFs em TRANSFERENCIAS.",
        "quando": "Depois de a fila de transferidos estar certa.",
        "antes": ["Fila de transferidos pronta.", "Login do SERE salvo.", "Para a ação **Alterar**, o texto da observação do histórico."],
        "resultado": ["Executa no SERE as ações marcadas: **Gravar** (matrículas no histórico), **Alterar** (texto da observação), **Emitir**, **Assinar** e **Imprimir** (baixa o PDF).",
                      "Os PDFs vão para as pastas de TRANSFERENCIAS (GUIA DE TRANSFERENCIA e HISTORICO)."],
        "cuidados": ["A caixa **Simulação** vem marcada: mostra quem seria processado, as ações e as pastas de destino, sem abrir o SERE. Desmarque para executar de verdade.",
                     "**Assinar** assina como o usuário logado (Secretário) e confere se o Diretor já assinou. O Diretor assina em outra sessão: rode **Assinar** de novo depois.",
                     "Pede confirmação antes de executar."],
        "veja_tambem": [R("automacao", "transferidos_fila"), R("automacao", "transferidos"), R("tela", "transferidos")],
    },
    "transferidos": {
        "grupo": "transferidos",
        "resumo": "Envia à **pasta virtual do SERE** a guia, o histórico e o parecer dos transferidos que estão nas pastas de TRANSFERENCIAS.",
        "quando": "Depois de gerar a guia e o histórico e de ter o parecer digitalizado e arquivado.",
        "antes": ["Documentos nas pastas de TRANSFERENCIAS.", "Login do SERE salvo."],
        "resultado": ["Anexa os documentos no SERE e registra no controle de transferidos."],
        "cuidados": ["A caixa **Simulação** vem marcada: só varre as pastas e mostra o que seria enviado, sem abrir o SERE. Desmarque para enviar de verdade.",
                     "Pede confirmação antes de executar. **Modo de teste** envia só o primeiro arquivo (de verdade)."],
        "veja_tambem": [R("automacao", "pareceres_transferidos"), R("tela", "transferidos"), R("configuracao", "data_corte_transferidos")],
    },
    "pareceres_transferidos": {
        "grupo": "transferidos",
        "resumo": "Numa rotina só: lê o **QR code** de cada parecer digitalizado, arquiva em PARECERES, comprime se passar do limite e envia ao SERE.",
        "quando": "Depois de digitalizar os pareceres dos transferidos.",
        "antes": ["Pareceres digitalizados na pasta de processamento (PROCESSAMENTO DE PARECERES).", "Login do SERE salvo."],
        "resultado": ["Arquiva o parecer na pasta PARECERES, comprime (o original fica guardado) e, se marcado, envia ao SERE."],
        "cuidados": ["**Simulação** vem marcada: lê os QR e mostra onde cada arquivo seria salvo e se seria comprimido, sem copiar nem enviar. Desmarque para processar de verdade.",
                     "Desmarque **Enviar ao SERE depois de processar** para só arquivar.",
                     "Pede confirmação antes de executar."],
        "veja_tambem": [R("automacao", "transferidos"), R("automacao", "comprimir")],
    },

    # ───── Pareceres ─────
    "parecer_fund": {
        "grupo": "pareceres",
        "resumo": "Gera o parecer de cada aluno do **Ensino Fundamental** a partir do modelo Word (.docx) da turma. Cada parecer leva um **QR code** no fim.",
        "quando": "Antes de cada bimestre, para imprimir os pareceres.",
        "antes": ["Enviar o modelo da turma em Configurações → Modelos de parecer.", "Ter o `turmas.json`."],
        "resultado": ["Um arquivo por aluno em `PARECERES/<turma>/`, com o nome \"<nº da chamada> - <nome>\", em PDF, Word ou ambos."],
        "cuidados": ["Parecer que já existe é mantido (o professor pode já ter preenchido): marque **Substituir pareceres que já existem** só para refazer do zero.",
                     "O QR é criptografado: lido pela câmera do celular aparece ilegível."],
        "veja_tambem": [R("configuracao", "modelos_parecer"), R("automacao", "pareceres_digitalizados")],
    },
    "pareceres_digitalizados": {
        "grupo": "pareceres",
        "resumo": "Lê o **QR** dos pareceres do Fundamental digitalizados (pasta PARECERES/_PROCESSAR), arquiva cada um na turma do aluno, comprime se passar do limite e, "
                  "se marcado, envia ao SERE e por e-mail ao responsável.",
        "quando": "Depois de imprimir, assinar e digitalizar os pareceres.",
        "antes": ["Pareceres digitalizados em PARECERES/_PROCESSAR.", "Login do SERE e Gmail salvos, se for enviar."],
        "resultado": ["Arquiva por turma. Com **Enviar ao SERE**, envia ao item \"Parecer Descritivo <ano>-1\" da pasta virtual; quem já foi enviado e não mudou é pulado.",
                      "Com **E-mail ao responsável**, escolha: não enviar, **só teste** (1 e-mail, para o endereço de teste) ou enviar ao responsável de cada aluno."],
        "cuidados": ["**Simulação** vem marcada: lê os QR e mostra o que aconteceria (inclusive quem receberia e-mail e a prévia), sem copiar, enviar nem gravar. Desmarque para executar.",
                     "O envio por e-mail vai para **famílias de verdade**. Teste antes com a opção \"só teste\".",
                     "Assunto e mensagem aceitam os marcadores `$ALUNO`, `$TURMA`, `$ESCOLA`, `$ANO` e `$RESPONSAVEL`.",
                     "Pede confirmação antes de executar."],
        "veja_tambem": [R("automacao", "parecer_fund"), R("configuracao", "chave_gmail")],
    },
    "parecer_rco": {
        "grupo": "pareceres",
        "resumo": "Baixa do **RCO** (Registro de Classe Digital) os pareceres em PDF dos alunos matriculados no **Infantil IV e V**.",
        "quando": "No 2º e no 4º bimestres.",
        "antes": ["Login do RCO (por padrão o mesmo do SERE) salvo.", "Ter acesso ao e-mail que recebe o código de verificação."],
        "resultado": ["PDFs em `PARECERES INFANTIL/<N>º Bimestre/<turma>/<nº da chamada> - <nome>.pdf`."],
        "cuidados": ["O RCO envia um código de verificação por e-mail: a tela abre uma janela e você digita o código.",
                     "Por padrão o navegador fica escondido; marque **Mostrar o navegador** se algo falhar.",
                     "O 1º e o 3º bimestres vêm da automação **Pareceres infantil (planilha)**."],
        "veja_tambem": [R("automacao", "parecer_planilha"), R("configuracao", "senha_rco"), R("modal", "pergunta-automacao")],
    },
    "parecer_planilha": {
        "grupo": "pareceres",
        "resumo": "Gera, a partir das **planilhas do Google que as professoras preenchem**, o parecer em PDF de cada aluno matriculado no Infantil IV e V, com QR code.",
        "quando": "No 1º e no 3º bimestres.",
        "antes": ["Planilhas ativas cadastradas em Planilhas do Drive com a finalidade \"Pareceres do Infantil\" (uma por turma).",
                  "Acesso ao Google configurado (na primeira vez o Google pede autorização)."],
        "resultado": ["PDFs na mesma árvore dos pareceres do RCO: `PARECERES INFANTIL/<N>º Bimestre/<turma>/<nº da chamada> - <nome>.pdf`."],
        "cuidados": ["Parecer já gerado é mantido; marque **Substituir pareceres que já existem** só para refazer.",
                     "Escolha uma planilha específica ou deixe **Todas as ativas** (uma por turma); o filtro de turma limita."],
        "veja_tambem": [R("automacao", "parecer_rco"), R("tela", "planilhas")],
    },
    "planilha_modelo": {
        "grupo": "pareceres",
        "resumo": "Cria uma planilha nova a partir dos modelos do sistema — **Chamada**, **Planilha das Turmas**, **Listagem dos Alunos** ou **IMC** — no Google Sheets, "
                  "Excel (.xlsx) ou LibreOffice (.ods), já preenchida com os alunos do `turmas.json` e cadastrada em Planilhas do Drive.",
        "quando": "No início do ano, para entregar planilhas prontas às professoras.",
        "antes": ["Ter o `turmas.json`.", "Para Google Sheets, o acesso ao Google configurado."],
        "resultado": ["Cria a planilha e a cadastra. Se já existe uma ativa para o mesmo uso, a nova fica inativa, a menos que você marque **Passar a usar a nova planilha**."],
        "cuidados": ["O **Modo de teste** não se aplica aqui: a automação só cria uma planilha nova."],
        "veja_tambem": [R("tela", "planilhas"), R("automacao", "sheets")],
    },
    "termos": {
        "grupo": "pareceres",
        "resumo": "Preenche o modelo \"MODELO DE TERMO DE CIENCIA.docx\" com a lista dos funcionários da escola que têm matrícula: uma linha por pessoa com nome, matrícula, data e assinatura em branco.",
        "quando": "Quando a escola precisar colher a ciência dos funcionários sobre algum assunto.",
        "antes": ["Executar **Vínculos dos funcionários** (traz as matrículas).", "Ter o modelo .docx numa pasta."],
        "resultado": ["Salva um novo .docx na pasta do modelo. O modelo original nunca é alterado."],
    },

    # ───── Documentos ─────
    "validar": {
        "grupo": "documentos",
        "resumo": "Valida (clica em \"validar\") no SERE todos os documentos pendentes dos alunos selecionados.",
        "quando": "Depois de conferir que os documentos anexados estão corretos.",
        "antes": ["Login do SERE salvo."],
        "resultado": ["Marca documentos como validados no SERE (altera dados lá)."],
        "cuidados": ["Pede confirmação antes de executar. Valide só o que você já conferiu."],
        "veja_tambem": [R("aba", "documentos-pive"), R("automacao", "analisa_sere")],
    },
    "espec": {
        "grupo": "documentos",
        "resumo": "Envia ao SERE **um tipo específico de documento** (da pasta de digitalização) para os alunos escolhidos.",
        "quando": "Quando chegou um único tipo de documento (por exemplo, comprovantes de residência) para vários alunos.",
        "antes": ["Documentos na pasta de digitalização.", "Login do SERE salvo."],
        "resultado": ["Anexa o tipo escolhido no SERE (altera dados lá)."],
        "cuidados": ["Pede confirmação antes de executar. Escolha o **Tipo de documento** com atenção: a lista é a mesma do SERE."],
        "veja_tambem": [R("automacao", "aluno"), R("configuracao", "pasta_digitalizacao")],
    },
    "limpeza": {
        "grupo": "documentos",
        "resumo": "Remove **todos os arquivos** de todos os alunos das turmas selecionadas no SERE.",
        "quando": "Raramente: só para recomeçar a documentação de uma turma.",
        "antes": ["Ter certeza de que os documentos estão guardados na pasta de digitalização."],
        "resultado": ["Apaga arquivos no SERE."],
        "cuidados": ["**Não dá para desfazer.** Pede confirmação.", "Use o **Modo de teste** primeiro, numa turma pequena, e confira o resultado."],
    },
    "documentos": {
        "grupo": "documentos",
        "resumo": "Remove um **tipo de documento** de todos os alunos selecionados no SERE.",
        "quando": "Quando um tipo de documento foi anexado errado em massa.",
        "antes": ["Login do SERE salvo."],
        "resultado": ["Remove o tipo escolhido no SERE (altera dados lá)."],
        "cuidados": ["Pede confirmação antes de executar. Confira o **Tipo de documento** escolhido."],
        "veja_tambem": [R("automacao", "limpeza")],
    },
    "analisa_pasta": {
        "grupo": "documentos",
        "resumo": "Analisa os documentos que estão na **pasta de digitalização** do computador: confere, para cada aluno, quais documentos existem (considerando sinônimos de nome).",
        "quando": "Depois de digitalizar documentos novos, antes do cruzamento.",
        "antes": ["Pasta de digitalização configurada e com as pastas dos alunos."],
        "resultado": ["Grava `documentos-alunos-pc.json`, que alimenta a aba **Documentos Digitalizados**.",
                      "Aluno nascido depois de 2017 com certidão dispensa o CPF separado (o CPF já consta na certidão)."],
        "veja_tambem": [R("aba", "documentos-pc"), R("automacao", "cruzamento"), R("automacao", "gerar_pastas")],
    },
    "analisa_sere": {
        "grupo": "documentos",
        "resumo": "Percorre os alunos no **SERE** e lê quais documentos já estão anexados e se estão validados.",
        "quando": "Antes do cruzamento, para saber o que já está no SERE.",
        "antes": ["Login do SERE salvo.", "`turmas.json` atualizado."],
        "resultado": ["Grava `documentos-alunos.json`, que alimenta a aba **Documentos do PIVE**."],
        "cuidados": ["Se existirem **Opções guardadas do script** (por exemplo, modo rápido), elas valem quando você deixa a seleção no padrão; qualquer seleção explícita as substitui."],
        "veja_tambem": [R("aba", "documentos-pive"), R("automacao", "cruzamento")],
    },
    "cruzamento": {
        "grupo": "documentos",
        "resumo": "Cruza o que está no SERE com o que está no computador e dá a cada aluno um status: **Completo**, **Parcial**, **Pendente** ou **Sem básicos**.",
        "quando": "Depois de executar **Analisa documentos da pasta** e **Analisa documentos do SERE**.",
        "antes": ["Os dois arquivos de análise gerados (`documentos-alunos-pc.json` e `documentos-alunos.json`)."],
        "resultado": ["Grava `cruzamento-documentos.json`, que alimenta a aba **Análise**."],
        "cuidados": ["Só lê arquivos; não altera nada no SERE."],
        "veja_tambem": [R("aba", "documentos-analise"), R("automacao", "analisa_pasta"), R("automacao", "analisa_sere")],
    },
    "comprimir": {
        "grupo": "documentos",
        "resumo": "Encolhe os PDFs e imagens (alunos, guias, históricos e pareceres) que passam do limite de **1,5 MB** do SERE, guardando os originais.",
        "quando": "Quando o envio ao SERE recusa arquivos por tamanho.",
        "antes": ["Pasta de digitalização configurada."],
        "resultado": ["Substitui o arquivo por uma versão menor (mesmo nome e mesma data).",
                      "Os originais ficam em `dados/<ano>/ORIGINAIS_ANTES_DA_COMPRESSAO`; o que já foi feito fica em `compressao_registro.json`."],
        "cuidados": ["Sem escolher turma, processa a pasta inteira (alunos e TRANSFERENCIAS).",
                     "Marque **Só calcular quanto vai economizar** para ver sem alterar nada.",
                     "A qualidade fica menor. Pede confirmação antes de executar."],
        "veja_tambem": [R("automacao", "pareceres_transferidos")],
    },
    "gerar_pastas": {
        "grupo": "documentos",
        "resumo": "Cria, dentro da pasta de digitalização do ano, uma subpasta por turma e, dentro dela, uma por aluno ativo (\"<N> - <NOME>\"). Move para **TRANSFERIDOS** as pastas de quem saiu.",
        "quando": "Na configuração inicial e sempre que houver alunos novos ou transferidos.",
        "antes": ["Executar **Turmas** antes."],
        "resultado": ["Cria e organiza pastas. Move para TRANSFERIDOS as pastas de alunos que não constam mais no `turmas.json` ou que constam como \"Transferido\"."],
        "veja_tambem": [R("automacao", "turmas"), R("configuracao", "pasta_digitalizacao")],
    },
    "mapear_pastas": {
        "grupo": "documentos",
        "resumo": "Liga cada aluno à sua pasta de digitalização, tolerando acentos, pontuação e o número na frente do nome.",
        "quando": "Para descobrir quais alunos estão sem pasta ou com a pasta com nome diferente.",
        "antes": ["Ter o `turmas.json` e a pasta dos alunos."],
        "resultado": ["Grava `alunos_pastas.json` (aluno → caminho da pasta) e `nao_encontrados.json`."],
        "cuidados": ["Só lê: não move nem renomeia pastas."],
        "veja_tambem": [R("automacao", "gerar_pastas")],
    },

    # ───── Saúde ─────
    "sus": {
        "grupo": "saude",
        "resumo": "Consulta no **SISREG** (fila de espera do SUS de Ponta Grossa), pelo CPF, os encaminhamentos dos alunos escolhidos.",
        "quando": "Para atualizar a tela de Encaminhamentos do SUS.",
        "antes": ["Alunos com CPF no cadastro (execute **Alunos** antes)."],
        "resultado": ["Grava `alunos_encaminhamento.json`. Os alunos que você não escolheu mantêm o resultado anterior."],
        "cuidados": ["A consulta é pública: não precisa de login. Aluno com CPF inválido aparece com o erro dele na tela de Encaminhamentos."],
        "veja_tambem": [R("tela", "encaminhamentos"), R("automacao", "alunos")],
    },
    "cep": {
        "grupo": "saude",
        "resumo": "Consulta, valida e completa endereços pelo **CEP** e calcula a distância entre o aluno e a escola.",
        "quando": "Para atualizar a tela Alunos fora do raio.",
        "antes": ["Dados da escola (CEP e endereço) configurados.", "Cadastro dos alunos coletado."],
        "resultado": ["Alimenta a tela **Alunos fora do raio**."],
        "cuidados": ["O raio padrão é de 2 km; mude no campo **Raio de atendimento (km)** desta tela."],
        "veja_tambem": [R("tela", "fora-do-raio"), R("configuracao", "escola")],
    },

    # ───── Comunicação ─────
    "avisos": {
        "grupo": "comunicacao",
        "resumo": "Comunicados oficiais por e-mail, **só para quem está chegando**: de escola para as escolas e CMEIs de Ponta Grossa (por exemplo, "
                  "pedir a transferência de um aluno à escola de origem) ou para os **pais de alunos novos** (pré-matrícula do ano letivo e previsão do próximo ano).",
        "quando": "Para avisos em massa. Comece sempre por **Simular**: o envio real só libera depois de simular o mesmo comunicado.",
        "antes": ["E-mail do Gmail salvo em Configurações.", "Para escolas, a lista de unidades (automação **Coleta e-mails**).",
                  "Para o texto de transferência (com $ALUNO, $CGM, $SERIE), a **Consulta na Base ABC** feita antes: é ela que liga o CGM e a escola de origem a cada aluno novo."],
        "resultado": ["No modo **Simular**, lista quem receberia, quem fica de fora (e por quê), mostra a prévia e guarda o registro em `AVISOS/`, sem enviar nada.",
                      "No modo **Teste**, envia UM e-mail de verdade, só para o e-mail de teste (para escolas, a escola fictícia ESCOLA MUNICIPAL TESTE DA SILVA).",
                      "No modo **Enviar de verdade**, envia um por um, com pausa entre eles e no máximo o limite escolhido por execução; grava cada envio em "
                      "`AVISOS/enviados.json` e o registro da execução (enviados, falhas, os que faltam). O botão **Ver quem já recebeu** mostra esse registro."],
        "cuidados": ["O envio real **não pode ser desfeito** e pede confirmação. Só funciona depois de **Simular** o mesmo texto e os mesmos destinatários (a simulação vale 24 horas).",
                     "Quem já recebeu o mesmo texto não recebe de novo: dá para cancelar e rodar outra vez, que continua de onde parou. Três falhas seguidas (senha errada, sem rede) param o envio.",
                     "Um texto com **$ALUNO, $CGM, $SERIE ou $TURMA** vira um e-mail por aluno que chega, para a escola de origem dele; sem esses marcadores, é um e-mail por unidade. "
                     "Aluno sem vínculo da Base ABC, com vínculo a verificar ou com escola de origem fora da lista **não recebe** e aparece na lista. "
                     "Se o aluno já entrou na nossa escola, o pedido vai para a escola anterior do histórico.",
                     "**Tipo de mensagem** carrega modelos (o de transferência já vem pronto) e dá para salvar, ajustar e excluir os seus, que ficam em `config/modelos_avisos.json`.",
                     "Use os marcadores no assunto e na mensagem; os disponíveis aparecem na descrição de cada público."],
        "veja_tambem": [R("automacao", "coleta_emails"), R("configuracao", "chave_gmail")],
    },
    "coleta_emails": {
        "grupo": "comunicacao",
        "resumo": "Lê o site da Secretaria Municipal de Educação de Ponta Grossa e lista todas as **escolas municipais e CMEIs** com nome, endereço, ramal e e-mail.",
        "quando": "Uma vez, e depois quando a lista da prefeitura mudar.",
        "antes": ["Internet."],
        "resultado": ["Grava `escolas_completas.json`, a lista de escolas do município usada nos avisos."],
        "cuidados": ["Só lê páginas públicas."],
        "veja_tambem": [R("automacao", "avisos"), R("configuracao", "escola")],
    },

    # ───── Rotinas e sistema ─────
    "agendador": {
        "grupo": "sistema",
        "resumo": "Criaria rotinas automáticas no Agendador de Tarefas do Windows.",
        "cuidados": ["**Ainda não foi implementada.** A tela existe, mas ao clicar em Executar tarefa o sistema responde que a automação ainda não foi implementada."],
    },
    "backup": {
        "grupo": "sistema",
        "resumo": "Cria uma cópia de segurança dos dados do sistema num único arquivo `.zip` datado, com um manifesto (tamanho e SHA-256 de cada arquivo) para conferir a integridade.",
        "quando": "Antes de mudanças grandes e periodicamente.",
        "resultado": ["Grava `dados/backup/backup_AAAA-MM-DD_HHMMSS.zip` e guarda os 10 mais recentes.",
                      "Ao fim das coletas de turmas, alunos e funcionários o sistema cria sozinho um backup \"automático\"; desses ficam os 7 mais recentes, à parte, sem empurrar os seus.",
                      "**Entram**: os `.json`, `.xlsx`, `.csv` e `.txt` do ano em uso e a configuração (`config_usuario.json` e `config.yaml`).",
                      "**Não entram**: senhas (`credenciais/` e qualquer `.env`), a pasta DIGITALIZAÇÃO, screenshots, logs e os próprios backups."],
        "cuidados": ["Para voltar os dados de um ano, use Configurações → Ano letivo → Restaurar."],
        "veja_tambem": [R("configuracao", "ano_letivo")],
    },
    "mascara": {
        "grupo": "sistema",
        "resumo": "Anonimiza os dados pessoais dos arquivos de trabalho (letras e números viram x e 0), gerando cópias `*_mask.json` ao lado dos originais. Serve para a LGPD.",
        "quando": "Ao compartilhar a estrutura dos dados (pedir ajuda, documentar) sem expor alunos ou servidores.",
        "resultado": ["Cria arquivos `*_mask.json`; os originais não são alterados."],
        "cuidados": ["Compartilhe apenas os arquivos `_mask`."],
    },
    "base_abc": {
        "grupo": "sistema",
        "resumo": "Busca o aluno na **Base ABC** do SERE (nome + data de nascimento + nome da mãe, ou o CGM) e registra as escolas do histórico escolar dele.",
        "quando": "Para descobrir de onde um aluno veio, principalmente na pré-matrícula.",
        "antes": ["Login do SERE salvo."],
        "resultado": ["Grava `buscas_base.json` com data da busca, nome, se tem CGM, CGM, nascimento, mãe e as escolas numeradas (ano, escola, série).",
                      "Quem não está na base **não é erro**: fica registrado o que foi encontrado.",
                      "Com a pré-matrícula, a previsão do próximo ano ou os transferidos como origem, grava também o vínculo (CGM, escola, série e a escola anterior do histórico) "
                      "no cadastro do aluno (`vinculo_base_abc`): é o que preenche os avisos de transferência."],
        "cuidados": ["Só lê o SERE: não altera nada lá; os vínculos são gravados nos arquivos do próprio sistema.",
                     "A pré-matrícula traz a data de nascimento e, se o portal mostrar, o nome da mãe: quanto mais dados, mais forte a busca (veja \"conferido_por\" no resultado).",
                     "Mãe e data de nascimento é que separam homônimos.",
                     "Com **Tirar do buscas_base.json quem já foi vinculado** (vem marcada), o registro sai de `buscas_base.json` depois de gravado no cadastro de origem; o que foi digitado fica."],
        "veja_tambem": [R("tela", "prematricula")],
    },
    "gerar_chaves": {
        "grupo": "sistema",
        "resumo": "Gera no SERE a **chave de acesso do responsável** de cada aluno matriculado e guarda a chave com o CPF dele para a rematrícula usar.",
        "quando": "Antes da rematrícula.",
        "antes": ["Login do SERE salvo.", "`turmas.json` atualizado."],
        "resultado": ["Grava `chave_responsavel.json` do ano com CGM, nome, turma, CPF do responsável e chave."],
        "cuidados": ["**Não rematricula ninguém.**",
                     "Por padrão pula quem já tem chave salva e quem já foi rematriculado; marque **Gerar de novo…** para refazer.",
                     "O **Modo de teste** gera a chave de só 1 aluno por turma. Pede confirmação antes de executar."],
        "veja_tambem": [R("automacao", "rematricula")],
    },
}

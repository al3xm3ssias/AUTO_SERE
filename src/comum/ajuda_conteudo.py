"""
ajuda_conteudo.py — textos da ajuda (tecla F1) de cada tela, aba, painel e janela do Auto SERE
==============================================================================================
Só dados, sem lógica: quem monta e serve a ajuda é src/comum/ajuda.py (rota /web/api/ajuda/...), e quem a mostra é
src/web/static/js/ajuda.js. As automações têm o seu próprio arquivo (ajuda_automacoes.py), porque também
herdam do registro de scripts os campos de cada tela.

FORMATO de cada entrada (todas as chaves são opcionais, menos titulo e resumo):

    "chave": {
        "titulo":  "nome mostrado no alto da ajuda",
        "icone":   "nome do ícone (src/web/static/js/icons.js)",
        "resumo":  "o que a tela faz, em uma ou duas frases",
        "dados":   "de onde vêm as informações (arquivo e automação que o preenche)",
        "passos":  ["passo a passo para usar a tela", ...],
        "elementos": [E("Nome do botão/campo", "o que é e como usar", "#seletor-css"), ...],
        "dicas":   ["...", ...],
        "cuidados": ["...", ...],
        "veja_tambem": [R("tela"|"automacao"|"configuracao", "chave"), ...],
    }

Nos textos, **negrito** e `código` são interpretados pelo JavaScript; todo o resto é texto puro.
O seletor CSS (3º argumento de E) liga o item ao botão "Mostrar na tela": o sistema destaca o elemento
real. Um teste (tests/test_ajuda.py) confere se cada seletor ainda existe nos templates ou nos scripts da tela.
"""
from __future__ import annotations


def E(nome: str, texto: str, sel: str | None = None) -> dict:
    """Um elemento da tela (botão, campo, coluna...). `sel` é o seletor CSS que o botão 'Mostrar na tela' destaca."""
    item = {"nome": nome, "texto": texto}
    if sel:
        item["sel"] = sel
    return item


def R(tipo: str, chave: str, rotulo: str = "") -> dict:
    """Link 'Veja também' para outra ajuda (tipo: tela, automacao, configuracao)."""
    return {"tipo": tipo, "chave": chave, "rotulo": rotulo}


# ───────────────────────────── o que existe em TODAS as telas ─────────────────────────────

GERAL = {
    "titulo": "Em todas as telas",
    "resumo": "A moldura do sistema é sempre a mesma: menu à esquerda, barra no alto e a tela escolhida no meio.",
    "elementos": [
        E("Menu lateral",
          "Cada item abre uma tela. O grupo **Automações** se abre em subgrupos (Cadastros, Matrícula, Transferidos, "
          "Pareceres, Documentos, Saúde, Comunicação, Rotinas e sistema); clicar numa automação abre direto a tela de "
          "execução dela.", "#sidebar-nav"),
        E("Botão ☰ (recolher menu)",
          "No computador recolhe o menu para dar mais espaço à tela; no celular abre e fecha o menu.", "#sidebar-toggle"),
        E("Caminho no alto", "Mostra onde você está (por exemplo, Painel / Turmas).", "#breadcrumb"),
        E("Selo do ano letivo",
          "Mostra o ano em que o sistema está trabalhando. Quando aparece **somente consulta**, você está vendo um ano "
          "anterior: dá para ver tudo, mas nada pode ser alterado nem executado.", "#ano-badge"),
        E("Faixa de aviso do ano",
          "Aparece sob a barra quando o ano está em somente consulta, ou quando a configuração aponta para outro ano "
          "(botão **Aplicar agora**). O botão **Voltar ao ano atual…** leva às Configurações.", "#ano-banner"),
        E("Resumo no alto à direita", "Hora da última atualização do painel e total de alunos.", "#t-meta"),
        E("Ícone de usuário", "Atalho para as Configurações.", "#topbar-user"),
        E("Botão ? (Ajuda desta tela)", "Abre esta ajuda, igual à tecla **F1**. Útil no celular, que não tem F1.", "#btn-ajuda-f1"),
        E("Trocar tema",
          "Três botões no rodapé do menu: Escuro, Equilibrado e Claro. A escolha fica guardada.", "#theme-switcher"),
        E("Mensagens rápidas",
          "Avisos curtos (\"Salvo\", \"Automação iniciada\", erros) aparecem no canto da tela e somem sozinhos.", "#toast"),
    ],
    "dicas": [
        "**F1** abre a ajuda da tela em que você está, e também da janela aberta por cima dela (confirmações, formulários). "
        "Aperte **F1** ou **Esc** de novo para fechar.",
        "O botão **Mostrar na tela** ao lado de cada item da ajuda destaca o botão ou campo real, para você achá-lo.",
        "A Central de ajuda (menu Sistema → Ajuda) lista todas as telas e automações, com busca.",
    ],
}


# ───────────────────────────── telas do menu ─────────────────────────────

TELAS: dict[str, dict] = {

    "painel": {
        "titulo": "Painel principal", "icone": "dashboard",
        "resumo": "Visão geral da escola no ano letivo em uso: os números principais e os primeiros da fila da "
                  "pré-matrícula. É a tela que abre quando você entra no sistema.",
        "dados": "Calculado cada vez que a tela abre, a partir dos arquivos do ano (turmas, pré-matrícula, documentos, "
                 "transferidos, encaminhamentos). Número zerado costuma significar que a automação que coleta aquele "
                 "dado ainda não foi executada.",
        "passos": [
            "Se aparecer o cartão **Avisos**, ele traz o que a rotina diária encontrou e pede ação: aluno transferido (gerar "
            "os documentos e enviá-los à escola de destino) ou aluno que sumiu da lista sem constar como transferido (conferir no SERE). "
            "O aviso se resolve sozinho quando os passos são feitos; ou clique em **Marcar como resolvido**.",
            "Olhe os cartões do alto: total de alunos, meninos, meninas, fila da pré-matrícula e turmas.",
            "Veja os **indicadores complementares** (documentos pendentes, alunos fora do raio, transferidos e "
            "encaminhamentos do SUS) para saber onde ainda há trabalho.",
            "Na tabela **Fila da pré-matrícula** aparecem os 5 primeiros. Clique em **Mandar mensagem** para escrever ao "
            "responsável pelo WhatsApp, ou em **Ver tudo** para abrir a tela Pré matrícula.",
            "Clique em **Atualizar** para recalcular os números.",
        ],
        "elementos": [
            E("Avisos", "Só aparece quando há algo a fazer: transferidos a documentar e enviar à escola de destino, e saídas a conferir. "
                        "Cada aviso mostra os passos já feitos (✔) e os que faltam (☐).", "#painel-avisos"),
            E("Última atualização", "Data e hora em que os números foram calculados.", "#ultima-atualizacao"),
            E("Botão Atualizar", "Recalcula todos os números agora.", "#btn-atualizar-painel"),
            E("Cartões principais",
              "Total de alunos, Meninos, Meninas (com a porcentagem), Fila da pré-matrícula e Turmas.", "#metrics-principais"),
            E("Indicadores complementares",
              "Docs pendentes, Fora do raio da escola, Qtd. transferidos e Qtd. encaminhamentos SUS.", "#metrics-secundarias"),
            E("Tabela da fila da pré-matrícula",
              "Nº, nome do aluno, turma, posição na fila, telefone do pai/responsável e a ação **Mandar mensagem**.",
              "#tbody-painel-prematricula"),
            E("Ver tudo", "Abre a tela Pré matrícula, com todos os cadastros.", "#sec-painel [data-goto='prematricula']"),
        ],
        "dicas": ["Se um cartão mostra 0, abra a automação correspondente em Automações e execute-a uma vez."],
        "veja_tambem": [R("tela", "prematricula"), R("tela", "alunos"), R("tela", "turmas")],
    },

    "turmas": {
        "titulo": "Turmas", "icone": "users",
        "resumo": "Lista todas as turmas da escola, com a quantidade de matriculados e transferidos e a relação de alunos de cada uma.",
        "dados": "`turmas.json`, coletado do SERE pela automação **Turmas**.",
        "passos": [
            "Digite parte do nome na caixa de busca para filtrar as turmas (a lista se refaz enquanto você digita).",
            "Clique no título de uma turma para abrir a lista de alunos dela; clique de novo para fechar.",
            "Role a tabela da turma para ver todos os alunos (a tabela tem altura limitada e rola por dentro).",
        ],
        "elementos": [
            E("Buscar turma", "Filtra pelo nome da turma.", "#turmas-busca"),
            E("Resumo", "Total de turmas, matriculados e transferidos.", "#turmas-resumo"),
            E("Cartão da turma",
              "Cada turma mostra selos: matriculados (azul-claro), transferidos (vermelho), meninas (F) e meninos (M). "
              "A seta à direita indica que ela se abre.", "#turmas-lista"),
        ],
        "cuidados": ["Esta tela só mostra os dados; para atualizá-los execute a automação Turmas."],
        "veja_tambem": [R("automacao", "turmas"), R("tela", "alunos")],
    },

    "alunos": {
        "titulo": "Alunos", "icone": "student",
        "resumo": "Tabela de todos os alunos com a ficha completa de cada um, juntando o cadastro básico e o cadastro completo.",
        "dados": "`alunos.json` (cadastro básico) e `alunos_completo.json` (cadastro completo), ligados pelo CGM. "
                 "Ambos vêm da automação **Alunos** (modos Básico e Completo).",
        "passos": [
            "Escolha um filtro: Todos, Matriculados, Transferidos, Cadastro completo ou Só básico.",
            "Para achar alguém, digite nome, CGM ou turma na busca.",
            "Clique nos títulos das colunas (Nome, CGM, Turma, Situação, Cadastro) para ordenar; clique de novo para inverter.",
            "Clique no **+** da linha para abrir a ficha do aluno; clique de novo (agora **−**) para fechar.",
        ],
        "elementos": [
            E("Contador", "Quantos alunos aparecem agora, de quantos no total (por exemplo, 12 / 380).", "#alunos-cnt"),
            E("Botões de filtro",
              "**Cadastro completo** são os alunos que já têm o cadastro completo coletado; **Só básico** são os que ainda não.",
              "#sec-alunos .fbar"),
            E("Busca", "Procura em todos os campos do aluno (nome, CGM, turma, filiação, endereço…).", "#alunos-q"),
            E("Linha de resumo",
              "Diz quantos alunos já têm o cadastro completo e quando o arquivo foi atualizado; avisa se o cadastro "
              "completo ainda não foi coletado.", "#alunos-info"),
            E("Tabela",
              "Colunas: Nome, CGM, Turma, Situação (matriculado/transferido) e Cadastro (básico ou completo). "
              "O selo **⚠** indica diferença entre os dois cadastros.", "#alunos-tbody"),
            E("Botão + da linha",
              "Abre a ficha, organizada em grupos: Identificação, Nascimento e origem, Documentação, Família e "
              "responsável, Contato, Endereço, Programas sociais, Perfil socioeconômico, Necessidades especiais e "
              "Observação. Campo sem dado mostra —.", "#sec-alunos .al-expand-btn"),
        ],
        "dicas": ["Se aparecer só o cadastro básico, rode Automações → Alunos no modo **Completo** para ver os demais campos."],
        "veja_tambem": [R("automacao", "alunos"), R("tela", "turmas"), R("tela", "documentos")],
    },

    "prematricula": {
        "titulo": "Pré matrícula", "icone": "clipboard",
        "resumo": "Fila e cadastros da pré-matrícula: quem pediu vaga, quem foi matriculado, quem está pendente e quem foi cancelado. "
                  "Também executa a coleta no portal, sem sair da tela.",
        "dados": "`pre_matricula.json` (o histórico nunca é apagado), gerado pela automação **Processo de pré-matrícula**. "
                 "O login do portal fica em Configurações → Salvar senha da Pré-matrícula.",
        "passos": [
            "Escolha a aba: **Geral**, **Matriculados**, **Cancelados**, **Pendentes** ou **Fila de análise**. As colunas mudam conforme a aba.",
            "Use a busca para achar por aluno, responsável, CPF ou turma matriculada.",
            "Clique no **+** da linha para ver o cadastro completo: dados, critérios informados, turmas de intenção "
            "(posição e pontuação), escolas escolhidas e situação da matrícula.",
            "Para atualizar os dados, clique em **Executar** no alto, escolha as opções e clique em **Iniciar pré-matrícula**.",
            "Use **Exportar** para baixar a lista que está na tela em CSV (abre no Excel).",
            "Na aba **Cancelados**, a coluna **Motivo da Recusa** explica o porquê. Se estiver escrito **CADASTRO REFEITO: NOSSA ESCOLA NÃO É A 1ª OPÇÃO**, "
            "o responsável refez o cadastro e a nossa escola ficou como 2ª ou 3ª opção (veja **Cadastro refeito** em Cuidados).",
            "A aba **Fila de análise** lista quem a escola precisa decidir: matricular ou confirmar antes com a **Central de Matrícula**. "
            "Abaixo de **Em análise** aparece o que as escolas anteriores responderam. Quando a nossa opção ganha uma situação (matriculado ou cancelado), o aluno sai da fila sozinho.",
            "Para **corrigir um dado** (por exemplo, o nome que os pais escreveram errado), abra o **+** do aluno e clique em **✎ Corrigir dados**. "
            "Altere o que precisar e clique em **Salvar correção**. O aluno passa a ter o selo **corrigido**.",
            "Para voltar ao que o site tinha, abra **Corrigir dados** de novo e clique em **Desfazer** embaixo do campo.",
        ],
        "elementos": [
            E("Executar", "Abre ou fecha o painel de execução da pré-matrícula.", "#pm-btn-executar"),
            E("Painel Executar pré-matrícula",
              "Mostra as 4 etapas (coleta das filas, cadastro de cada CPF, contatos e verificação de pendentes), "
              "o andamento e o registro da execução.", "#pm-exec"),
            E("Pular a verificação de pendentes",
              "Mais rápido: não consulta de novo quem ainda está pendente (Etapa 4).", "#pm-opt-pular"),
            E("Modo de análise",
              "Salva uma captura de tela de cada etapa em dados/<ano>/screenshots, para descobrir o que mudou no site se algo falhar.",
              "#pm-opt-debug"),
            E("Iniciar pré-matrícula",
              "Começa a coleta. Pode levar vários minutos; a tela acompanha. Só lê o site e atualiza o arquivo.", "#pm-exec-iniciar"),
            E("Cancelar execução", "Aparece enquanto a coleta roda; pede a parada.", "#pm-exec-cancelar"),
            E("Cartões de resumo", "Totais por situação.", "#cartoes-prematricula"),
            E("Abas", "Geral, Matriculados, Cancelados, Pendentes e Fila de análise (quem a escola precisa decidir).", "#sec-prematricula .fbar"),
            E("Busca", "Aluno, responsável, CPF ou turma matriculada.", "#pm-search"),
            E("Tabela", "Clique nos títulos que têm seta para ordenar. O **+** abre o cadastro completo.", "#pm-tbody"),
            E("Paginação", "Navega entre as páginas de resultados.", "#pm-pag-btns"),
            E("Exportar", "Baixa a lista atual (com a busca e a aba aplicadas) em CSV.", "#sec-prematricula .js-exportar"),
        ],
        "cuidados": [
            "A execução abre o portal da pré-matrícula e depende da senha salva em Configurações.",
            "A coleta só lê o site; ela não altera cadastros no portal.",
            "**Cadastro refeito:** se o responsável refaz o cadastro, vale o **último**. A escola da **Opção 1** é quem matricula ou cancela. "
            "Se a nossa escola (Judith Macedo Silveira) é a Opção 2 ou 3 e a escola anterior **ainda não escreveu a situação**, o aluno **não é registrado**: "
            "sai dos cadastros e dos contatos e aparece em Cancelados com o motivo \"nossa escola não é a 1ª opção\".",
            "**Fila de análise:** se a nossa escola é a Opção 2 ou 3 e **todas as opções anteriores já têm situação** "
            "(texto escrito pelas outras escolas, como \"A escola não dispõe de vaga no momento\"), o aluno é marcado para análise: "
            "a escola decide se matricula ou confirma antes com a **Central de Matrícula**. Se alguma anterior já matriculou o aluno, ele também não é registrado.",
            "Se o responsável refizer o cadastro e a nossa escola voltar a ser a Opção 1, o aluno sai da fila de análise na próxima coleta.",
            "**Correções à mão:** valem também nas próximas coletas (a coleta traz de novo o dado errado do site, mas o sistema reaplica a sua correção). "
            "Dá para corrigir nome do aluno, data de nascimento, nome da mãe, nome do responsável, telefones e e-mail. O **CPF não pode ser alterado**. "
            "Quem ainda não tem cadastro coletado só pode ter o nome corrigido.",
            "A correção não é feita enquanto uma automação estiver rodando, porque ela regrava o arquivo. Antes de cada correção o sistema guarda uma cópia em "
            "`pre_matricula.json.antes_da_edicao` (só a última). A tela **Previsão** usa outro arquivo (`previsao_alunos_<ano>.json`), que não é corrigido por aqui.",
        ],
        "veja_tambem": [R("automacao", "prematricula_completa"), R("configuracao", "senha_prematricula"),
                        R("tela", "previsao"), R("tela", "whatsapp")],
    },

    "previsao": {
        "titulo": "Previsão do próximo ano", "icone": "users",
        "resumo": "Quem deve estar na escola no ano letivo seguinte: os alunos já rematriculados somados aos alunos novos da pré-matrícula do próximo ano.",
        "dados": "Rematriculados: `rematriculas_sucesso.json`. Novos: `previsao_alunos_<ano>.json`, gravado pela "
                 "automação **Processo de pré-matrícula** ao coletar o próximo ano letivo. "
                 "Quem aparece nas duas fontes conta uma vez só, como rematriculado. Cancelados ficam de fora.",
        "passos": [
            "Olhe os cartões e os avisos do alto: eles dizem quantos alunos há e se falta algum arquivo.",
            "Escolha **Todos**, **Rematriculados** ou **Novos**.",
            "Busque por nome, CGM, CPF ou turma.",
            "Clique em **Exportar** para baixar a lista exibida em CSV (abre no Excel).",
        ],
        "elementos": [
            E("Cartões", "Totais da previsão por tipo.", "#pv-cartoes"),
            E("Avisos", "Dizem o que está faltando (por exemplo, a pré-matrícula do próximo ano ainda não foi coletada).", "#pv-avisos"),
            E("Abas Todos / Rematriculados / Novos", "Filtram a lista por tipo de aluno.", "#sec-previsao .fbar"),
            E("Busca", "Nome, CGM, CPF ou turma.", "#pv-busca"),
            E("Tabela", "Aluno, Tipo, Turma, CGM/CPF, Nascimento, Situação e Responsável.", "#pv-tbody"),
            E("Exportar", "Baixa a lista que está na tela em CSV.", "#pv-exportar"),
        ],
        "cuidados": ["Esta tela só lê arquivos; para mudar os dados, execute a rematrícula e a pré-matrícula."],
        "veja_tambem": [R("automacao", "rematricula"), R("automacao", "prematricula_completa"), R("tela", "prematricula")],
    },

    "transferidos": {
        "titulo": "Transferidos", "icone": "transfer",
        "resumo": "Todos os alunos transferidos da escola e o controle dos documentos de cada um: guia de transferência, histórico escolar e parecer, com as datas de emissão, assinatura e envio.",
        "dados": "`transferidos.json` (o controle dos documentos, só de quem entra no processo) e `fila_transferidos.json` (todos os transferidos, regerada a cada coleta de turmas). "
                 "Quem entra no processo é definido pela **data de corte** em Configurações.",
        "passos": [
            "Olhe os cartões do alto para ver quantos estão completos, parciais e pendentes.",
            "Filtre por **Todos**, **Completos**, **Parciais**, **Pendentes** ou **Fora do processo**; busque por nome, CGM, turma ou situação.",
            "Leia a coluna **Situação no processo**: ela diz em que ponto cada aluno está, inclusive quem não entra no processo automático.",
            "Leia os selos de cada documento: colorido com data = feito; cinza com **—** = ainda não feito.",
            "Para executar o envio ao SERE, clique em **Atualizar dados** (abre a automação) e siga a tela de execução.",
        ],
        "elementos": [
            E("Atualizar dados", "Abre a automação **Enviar transferidos ao SERE**.", "#sec-transferidos .js-atualizar"),
            E("Exportar", "Baixa a tabela atual em CSV, com uma coluna para cada data.", "#sec-transferidos .js-exportar"),
            E("Cartões", "**Total** é o total de transferidos da escola. Completos, Parciais e Pendentes contam só quem está no processo; "
                         "**Fora do processo** conta quem saiu antes do corte ou voltou à escola.", "#cartoes-transferidos"),
            E("Filtros", "Todos, Completos, Parciais, Pendentes e Fora do processo (cada um com sua contagem).", "#sec-transferidos .fbar"),
            E("Ocultar quem retornou", "Esconde da tabela os alunos que foram transferidos mas voltaram à escola.", "#transf-oculta-retorno"),
            E("Busca", "Nome, CGM, turma ou situação no processo.", "#transf-q"),
            E("Situação no processo",
              "**A processar**: entra no processo e ainda não tem documento. **Em andamento**: já tem parte dos documentos. **Concluído**: guia e histórico completos. "
              "**Antes do corte**: saiu antes da data de corte e foi tratado à mão. **Retornou à escola**: voltou, o processo não se refaz. "
              "**Sem data válida**: a data de saída está ilegível e precisa ser conferida. Sob o selo aparecem a data da saída e, se voltou, a do retorno.",
              "#sec-transferidos [data-ts='situacao_texto']"),
            E("Guia de Transferência",
              "Selos: **Emitida** (gerada no SERE), **Secr.** (assinada pelo secretário) e **Dir.** (assinada pelo diretor).",
              "#transf-tbody"),
            E("Histórico Escolar", "Mesmos selos da guia: Emitido, Secr. e Dir.", "#transf-tbody"),
            E("Parecer", "**Digitalizado** (arquivo encontrado) e **Anexado** (enviado ao SERE).", "#transf-tbody"),
            E("Destino",
              "A escola para onde o aluno foi (da Base ABC ou preenchida à mão) e o que o aviso por e-mail fará. O botão **Destino…** preenche ou corrige à mão. "
              "Quem está fora do processo não tem destino nem documentos: aparece só com o traço.", "#transf-tbody"),
            E("Saídas anteriores",
              "O botão **↺ N saída(s) anterior(es)** aparece sob o nome do aluno que saiu, voltou e saiu de novo. A linha da tabela mostra a "
              "**saída atual**; o botão abre uma janela, só para leitura, com cada saída anterior: data de saída, data em que voltou, turma, "
              "documentos feitos, escola de destino e o nome dos PDFs guardados.", "#transf-tbody"),
            E("Status", "**Completo**, **Pendente**, uma fração como 3/6 (passos feitos de um total) ou **Fora do processo**.", "#sec-transferidos [data-ts='status']"),
        ],
        "dicas": ["O Diretor assina em outra sessão do SERE; por isso a assinatura dele pode aparecer depois da do secretário."],
        "veja_tambem": [R("automacao", "transferidos_fila"), R("automacao", "transferidos_gerar"),
                        R("automacao", "pareceres_transferidos"), R("automacao", "transferidos"),
                        R("configuracao", "data_corte_transferidos")],
    },

    "funcionarios": {
        "titulo": "Funcionários", "icone": "badge",
        "resumo": "Cadastro e consulta de funcionários e servidores: cargo, contato, formação, vínculo e matrículas na Prefeitura.",
        "dados": "`funcionarios.json` e `funcionarios_completo.json` (automação **Funcionários / Servidores**) e o cruzamento com o RH "
                 "(automação **Vínculos dos funcionários**).",
        "passos": [
            "Escolha o grupo: Todos, Docentes, Direção, Pedagogos, Auxiliares ou Outros.",
            "Refine com a busca e com os filtros de **Sexo** e **Vínculo**.",
            "Escolha quantos registros por página (10, 25, 50 ou 100) e use a paginação.",
            "Clique no **+** de uma linha para ver o detalhe do funcionário.",
        ],
        "elementos": [
            E("Aviso de coleta", "Aparece como **Coleta incompleta** quando a última coleta não pegou todos os funcionários; lista quem ficou sem atualização.", "#func-aviso-coleta"),
            E("Cartões", "Totais de funcionários.", "#cartoes-funcionarios"),
            E("Grupos", "Todos, Docentes, Direção, Pedagogos, Auxiliares e Outros.", "#sec-funcionarios .fbar"),
            E("Busca", "Nome, CPF, e-mail ou cargo.", "#func-q"),
            E("Sexo", "Todos, Feminino ou Masculino.", "#func-sexo"),
            E("Vínculo", "Servidores, Terceirizados, Estagiários, A revisar ou Duas matrículas (20h + 20h).", "#func-vinculo"),
            E("Registros por página", "10, 25, 50 ou 100.", "#func-pagesize"),
            E("Tabela", "Clique nos títulos para ordenar. Colunas: nome, cargo/função, e-mail, telefone, sexo, CPF e formação.", "#func-tbody"),
            E("Paginação", "Mostra a faixa de registros e os botões de página.", "#func-pag-btns"),
            E("Exportar", "Baixa a lista atual em CSV.", "#sec-funcionarios .js-exportar"),
        ],
        "cuidados": ["Os dados incluem CPF e telefone: não compartilhe a tela nem o CSV exportado."],
        "veja_tambem": [R("automacao", "funcionarios"), R("automacao", "vinculos"), R("automacao", "termos")],
    },

    "encaminhamentos": {
        "titulo": "Encaminhamentos do SUS", "icone": "heart",
        "resumo": "Alunos que têm procedimentos de saúde na fila de espera do SISREG, consultados pelo CPF.",
        "dados": "`alunos_encaminhamento.json`, gerado pela automação **Encaminhamentos do SUS** (consulta pública, sem login).",
        "passos": [
            "Olhe o gráfico e os cartões do alto.",
            "Filtre por **Todos**, **Com encaminhamentos** ou **CPF inválido**; busque por nome, CPF ou procedimento.",
            "Cada aluno aparece num cartão com os procedimentos, a posição na fila e a data da solicitação.",
            "Para consultar de novo o SISREG, clique em **Atualizar dados**.",
        ],
        "elementos": [
            E("Atualizar dados", "Abre a automação que consulta o SISREG.", "#sec-encaminhamentos .js-atualizar"),
            E("Exportar", "Baixa a lista em CSV.", "#sec-encaminhamentos .js-exportar"),
            E("Cartões e gráfico", "Totais e distribuição dos encaminhamentos.", "#cartoes-encaminhamentos"),
            E("Filtros", "Todos, Com encaminhamentos e CPF inválido.", "#sec-encaminhamentos .fbar"),
            E("Busca", "Nome, CPF ou procedimento.", "#enc-q"),
            E("Cartão do aluno",
              "Nome, CPF e turma; abaixo, cada procedimento com **Fila** (posição), data da solicitação e nascimento. "
              "Faixa vermelha = erro na consulta (CPF inválido). \"Sem encaminhamentos ativos\" = nada na fila.", "#encam-list"),
        ],
        "dicas": ["Alunos sem CPF válido no cadastro não podem ser consultados: corrija o CPF no SERE e consulte de novo."],
        "veja_tambem": [R("automacao", "sus")],
    },

    "fora-do-raio": {
        "titulo": "Alunos fora do raio", "icone": "mapPinOff",
        "resumo": "Alunos cujo CEP fica além do raio de atendimento da escola, com a distância e a situação do comprovante de endereço.",
        "dados": "Gerado pela automação **CEP**, que valida o endereço pelo CEP e calcula a distância até a escola. "
                 "O raio padrão é 2 km e pode ser mudado na própria automação.",
        "passos": [
            "Veja o mapa e os cartões do alto.",
            "Filtre por **Todos**, **Com comp. endereço** ou **Sem comprovante** (estes dois só aparecem se os documentos do PC já foram analisados).",
            "Busque por aluno, CGM ou CEP; a lista vem ordenada da maior distância para a menor.",
            "Para recalcular, clique em **Atualizar dados**.",
        ],
        "elementos": [
            E("Atualizar dados", "Abre a automação CEP.", "#sec-fora-do-raio .js-atualizar"),
            E("Exportar", "Baixa a lista em CSV.", "#sec-fora-do-raio .js-exportar"),
            E("Mapa", "Mostra a posição dos alunos em relação à escola.", "#mapa-fora-do-raio"),
            E("Filtros", "Todos, Com comp. endereço e Sem comprovante.", "#sec-fora-do-raio .fbar"),
            E("Busca", "Aluno, CGM ou CEP.", "#fora-q"),
            E("Tabela", "Nome, Turma, Distância (com barra), CGM, CEP, Comp. Endereço e Docs no PC. Clique nos títulos para ordenar.", "#fora-tbody"),
        ],
        "veja_tambem": [R("automacao", "cep"), R("tela", "documentos")],
    },

    "calendario": {
        "titulo": "Calendário letivo", "icone": "calendar",
        "resumo": "Calendário do ano letivo com períodos, férias, recessos, emendas, HTPC e feriados nacionais e de Ponta Grossa.",
        "dados": "Salvo por ano letivo. Feriados nacionais vêm da BrasilAPI (precisa de internet); feriados de Ponta Grossa e "
                 "datas comemorativas já vêm embutidos.",
        "passos": [
            "Use as setas e **Hoje** para navegar; **Mês** e **Ano** trocam a visão.",
            "Clique num dia para ver o que há nele; o dia clicado também preenche a data do formulário de recessos.",
            "Para cadastrar um período (bimestre ou férias): preencha nome, tipo, início e fim e clique em **Salvar período**. "
            "Se preferir, clique em **Marcar no calendário** e escolha o início e o fim direto no calendário.",
            "Para cadastrar um recesso, emenda, HTPC ou feriado extra: preencha nome, tipo e data e clique em **Salvar**.",
            "Para excluir um cadastro, use o botão de excluir ao lado dele nas listas.",
        ],
        "elementos": [
            E("Anterior / Próximo / Hoje", "Navegam entre os meses (ou anos) e voltam para hoje.", "#cal-prev"),
            E("Mês / Ano", "Alterna entre a visão de um mês e a dos 12 meses.", "#cal-v-mes"),
            E("Legenda", "Feriado, Recesso/emenda, HTPC, Férias escolares, Data comemorativa (★) e Dia letivo.", ".cal-legenda"),
            E("Aviso de feriados", "Aparece se não foi possível buscar os feriados nacionais; use **Tentar de novo**.", "#cal-aviso"),
            E("Faixa de seleção", "Aparece quando você está marcando um período; **Cancelar** (ou **Esc**) desiste.", "#cal-selecao"),
            E("Calendário", "Clique num dia para ver detalhes; no modo Ano, clique no nome do mês para abri-lo.", "#cal-vista"),
            E("Períodos letivos", "Lista e formulário (nome, tipo Período letivo/Férias escolares, início e fim).", "#cal-f-periodo"),
            E("Marcar no calendário", "Escolha início e fim clicando nos dias.", "#cal-marcar-periodo"),
            E("Recessos, emendas e HTPC", "Lista e formulário (nome, tipo e data). Tipos: Recesso, Emenda de feriado, HTPC, Feriado municipal (extra) e Outro (sem aula).", "#cal-f-evento"),
            E("Feriados nacionais", "Lista recolhível dos feriados do ano; \"Ver JSON\" mostra os dados brutos.", "#cal-nac-resumo"),
        ],
        "cuidados": ["Sem internet os feriados nacionais não carregam, mas o que você cadastrou continua valendo."],
    },

    "corte-etario": {
        "titulo": "Corte etário", "icone": "ageCut",
        "resumo": "Quadro que mostra em que turma a criança entra no ano letivo, conforme o mês e o ano de nascimento (Berçário ao 5º ano).",
        "dados": "Calculado na própria tela, sem arquivo: a criança precisa ter a idade da turma completa até **31/03** do ano letivo.",
        "passos": [
            "O quadro abre no ano letivo padrão (a partir de novembro já abre no ano seguinte, época de matrículas).",
            "Use **Ano anterior** e **Próximo ano**, ou as setas ← → do teclado, para trocar o ano.",
            "Leia o quadro: ele cruza o mês e o ano de nascimento com a turma, e as cores seguem a legenda. A nota embaixo explica a regra.",
            "Clique em **Exportar PDF** para baixar o quadro em A4 paisagem.",
        ],
        "elementos": [
            E("Ano anterior / Próximo ano", "Trocam o ano letivo do quadro.", "#ce-anterior"),
            E("Ano em exibição", "Mostra o ano e uma legenda curta.", "#ce-ano-titulo"),
            E("Voltar", "Aparece quando você sai do ano padrão e leva de volta a ele.", "#ce-voltar"),
            E("Quadro", "Cruza o mês e o ano de nascimento com a turma em que a criança entra.", "#ce-tabela"),
            E("Legenda de cores", "Uma cor para cada turma.", "#ce-legenda"),
            E("Nota", "Explica a regra usada, incluindo a do Berçário.", "#ce-nota"),
            E("Exportar PDF", "Gera o PDF do quadro.", "#ce-exportar"),
        ],
        "dicas": ["As setas do teclado só funcionam com esta tela aberta e fora de campos de texto."],
    },

    "planilhas": {
        "titulo": "Planilhas do Drive", "icone": "database",
        "resumo": "Cadastro das planilhas usadas pelo sistema (Google Sheets, Excel e LibreOffice): pareceres da Secretaria, turmas, chamada, listagem e IMC. As automações buscam aqui a planilha **ativa** de cada uso.",
        "dados": "`dados/planilhas/planilhas.json`. Vale para todos os anos letivos. Remover do cadastro não apaga a planilha no Google.",
        "passos": [
            "Para guardar uma planilha que já existe, clique em **Cadastrar planilha** e preencha nome, plataforma, link (ou caminho), categoria, situação e finalidade.",
            "Para criar uma planilha nova já preenchida com os alunos, clique em **Criar de modelo**.",
            "Filtre a lista por situação, categoria ou pela busca (nome, link, caminho, categoria).",
            "Para trocar a planilha em uso, clique em **Usar esta** na nova: a anterior daquele uso fica inativa.",
            "Use **Copiar** para copiar o link, **Editar** para corrigir dados e **Remover** para tirar do cadastro.",
        ],
        "elementos": [
            E("Criar de modelo", "Cria uma planilha nova (Chamada, Planilha das Turmas, Listagem dos Alunos ou IMC) e já a cadastra.", "#pl-modelo"),
            E("Cadastrar planilha", "Abre o formulário para registrar uma planilha existente.", "#pl-nova"),
            E("Filtro de situação", "Todas, Ativas ou Inativas.", "#pl-filtro-status"),
            E("Filtro de categoria", "Mostra só uma categoria.", "#pl-filtro-categoria"),
            E("Busca", "Procura por nome, link, caminho ou categoria.", "#pl-busca"),
            E("Tabela", "ID, Nome (com o uso e a origem), Categoria, Link/arquivo, Situação e data de atualização. Clique nos títulos para ordenar.", "#pl-tabela"),
            E("Ações da linha", "**Usar esta** (só aparece em planilha inativa com finalidade), **Copiar**, **Editar** e **Remover**.", "#pl-corpo"),
            E("Legenda", "Ativa = em uso; Inativa = guardada, fora de uso. Em cada uso (e turma) só uma fica ativa.", ".pl-legenda"),
            E("Carregar mais", "Aparece quando há mais planilhas do que cabem na tela.", "#pl-mais"),
        ],
        "cuidados": [
            "Duas planilhas ativas para a mesma finalidade e turma não são aceitas: deixe uma inativa.",
            "Para planilhas do Google, a conta usada no acesso ao Google precisa conseguir abrir a planilha.",
        ],
        "veja_tambem": [R("automacao", "sheets"), R("automacao", "planilha_modelo"), R("automacao", "parecer_planilha")],
    },

    "documentos": {
        "titulo": "Análise de documentos", "icone": "files",
        "resumo": "Compara os documentos digitalizados no computador com os documentos que já estão no SERE, aluno por aluno, e mostra o que falta anexar.",
        "dados": "Três arquivos, um por aba: `documentos-alunos-pc.json` (digitalizados), `documentos-alunos.json` (SERE/PIVE) e "
                 "`cruzamento-documentos.json` (análise). Gerados pelas automações de análise e de cruzamento.",
        "passos": [
            "Comece pela aba **Documentos Digitalizados** para ver o que existe na pasta de digitalização.",
            "Veja na aba **Documentos do PIVE** o que já está no SERE.",
            "Na aba **Análise** veja quem está completo, parcial, pendente ou sem documentos básicos, e o que falta anexar.",
            "Em cada aba, use os botões de filtro e a busca; clique nos títulos para ordenar.",
        ],
        "elementos": [
            E("Abas", "Documentos Digitalizados, Documentos do PIVE e Análise, cada uma com a quantidade de alunos.", "#doc-tabs"),
        ],
        "dicas": ["Cada aba tem a sua própria ajuda: aperte **F1** com ela aberta."],
        "veja_tambem": [R("aba", "documentos-pc"), R("aba", "documentos-pive"), R("aba", "documentos-analise"),
                        R("automacao", "analisa_pasta"), R("automacao", "analisa_sere"), R("automacao", "cruzamento")],
    },

    "automacoes": {
        "titulo": "Automações", "icone": "bolt",
        "resumo": "Lista de todas as automações do sistema. Cada uma tem a sua tela de execução, com as opções, as configurações que usa e o histórico.",
        "passos": [
            "Clique numa automação da lista (ou no menu lateral) para abrir a tela de execução.",
            "Na tela de execução, escolha as opções e clique em **Executar tarefa**.",
            "Use **Voltar para automações** para retornar a esta lista.",
        ],
        "elementos": [
            E("Lista de automações", "Cada linha mostra o nome e uma explicação curta; a seta indica que abre a tela de execução.", "#lista-automacoes"),
        ],
        "dicas": [
            "Aperte **F1** dentro da tela de execução de uma automação: a ajuda explica aquela automação, campo por campo.",
            "Duas coletas que gravam o mesmo arquivo (por exemplo, duas coletas de Turmas) não rodam ao mesmo tempo.",
        ],
        "veja_tambem": [R("tela", "configuracoes"), R("tela", "primeira-execucao")],
    },

    "whatsapp": {
        "titulo": "WhatsApp", "icone": "whatsapp",
        "resumo": "Conecta o sistema ao WhatsApp Web e permite enviar uma mensagem de teste. As mensagens aos responsáveis usam esta conexão.",
        "passos": [
            "Veja o selo **Conexão** e a mensagem logo abaixo: eles dizem se está conectado, parado ou em modo simulado.",
            "Em **modo simulado** nada sai do computador. Para usar de verdade, escolha **Usar sem Docker (abre o navegador)** ou **Usar o gateway Docker**.",
            "Clique em **Abrir o WhatsApp** (ou **Gerar QR Code**). No celular: WhatsApp → Aparelhos conectados → Conectar um aparelho, e aponte para o QR Code.",
            "Para testar, digite o número com DDD, marque a confirmação e clique em **Enviar teste**.",
        ],
        "elementos": [
            E("Selo de conexão", "Mostra o estado atual (conectado, desconectado, simulado…).", "#wa-badge"),
            E("Modo simulado", "Aviso com os botões para sair do modo simulado.", "#wa-bloco-simulado"),
            E("Usar sem Docker", "Abre um navegador (Chromium) com o WhatsApp Web. Não feche essa janela enquanto o sistema precisar enviar; pode minimizá-la.", "#wa-usar-whatsplay"),
            E("Usar o gateway Docker", "Usa o contêiner do gateway; o Docker precisa estar aberto.", "#wa-usar-gateway"),
            E("QR Code", "Aponte o celular para conectar. Ele se renova sozinho. Use um número **dedicado da escola**, não pessoal.", "#wa-bloco-qr"),
            E("Gerar QR Code / Verificar conexão", "Pedem um novo QR ou conferem se a conexão está ativa. O campo de número é opcional e melhora a verificação.", "#wa-conectar"),
            E("Não aparece o QR Code?", "Instruções para zerar o vínculo antigo (arquivo WHATSAPP_ZERAR_VINCULO.bat).", "#wa-ajuda-qr"),
            E("Número (com DDD)", "Para quem vai a mensagem de teste.", "#wa-numero"),
            E("Texto (opcional)", "Mensagem de teste; em branco usa o texto padrão do sistema.", "#wa-texto"),
            E("Confirmo que é um envio de verdade", "Obrigatório para enviar de verdade (fora do modo simulado).", "#wa-confirmo"),
            E("Enviar teste", "Envia UMA mensagem para o número informado.", "#wa-enviar"),
            E("Permitir envio real", "Envio real fica bloqueado até você permitir aqui.", "#wa-alternar-envio"),
            E("Webhook", "Entrega mensagens recebidas a módulos futuros (só no gateway Docker).", "#wa-webhook-bloco"),
            E("Desconectar", "Encerra a sessão do WhatsApp neste computador.", "#wa-desconectar"),
            E("Modo de funcionamento", "Sem Docker (navegador), Gateway Docker ou Simulado.", "#wa-card-avancado"),
        ],
        "cuidados": [
            "O WhatsApp pode banir números que enviam em massa ou para quem não pediu contato. Este é um cliente **não oficial**.",
            "Use sempre um número dedicado da escola.",
        ],
        "veja_tambem": [R("tela", "prematricula"), R("tela", "primeira-execucao")],
    },

    "configuracoes": {
        "titulo": "Configurações", "icone": "settings",
        "resumo": "Dados da escola, ano letivo, senhas, pastas e modelos que todos os scripts usam. Escolha um item e o painel dele abre embaixo.",
        "passos": [
            "Clique numa linha (por exemplo, Dados da escola). O painel correspondente aparece em **Painel selecionado**, no fim da tela.",
            "Preencha o painel e clique no botão de salvar dele.",
            "Para saber o que cada painel faz, deixe-o aberto e aperte **F1**: a ajuda é do painel.",
        ],
        "elementos": [
            E("Escola", "Dados da escola, Ano letivo, Data de corte dos transferidos, Turmas do QR antigo e Navegador das automações.", "[data-config='escola']"),
            E("Credenciais e integrações", "Senhas do SERE, da Pré-matrícula, do RCO e do Gmail; Planilhas do Google Drive; outras credenciais; Temas e Perfil.", "[data-config='senha_sere']"),
            E("Pastas", "Pasta de digitalização e Modelos de parecer.", "[data-config='pasta_digitalizacao']"),
            E("Painel selecionado", "Área onde aparece o formulário do item escolhido.", "#config-detalhe"),
        ],
        "cuidados": ["Senhas ficam salvas só neste computador (arquivo credenciais/.env)."],
        "veja_tambem": [R("configuracao", "escola"), R("configuracao", "ano_letivo"), R("configuracao", "senha_sere"),
                        R("configuracao", "pasta_digitalizacao")],
    },

    "primeira-execucao": {
        "titulo": "1ª execução do sistema", "icone": "rocket",
        "resumo": "Assistente de configuração inicial: uma lista de passos em ordem que deixa o sistema pronto para uso.",
        "passos": [
            "Siga os passos de cima para baixo. Cada um tem o botão **Executar**.",
            "Depois que um passo termina ele ganha o selo **Concluído**; se estiver rodando, aparece **Executando…** e o botão **Cancelar**.",
            "Acompanhe tudo no **Registro de atividades**, à direita.",
        ],
        "elementos": [
            E("Lista de passos",
              "1) Dados da escola; 2) Credenciais do SERE (obrigatório); 3) Executar Turmas; 4) Gerar Pastas; "
              "5) Funcionários/Servidores; 6) Alunos; 7) Chave de acesso do Google; 8) Conectar WhatsApp.", "#wizard-lista"),
            E("Registro de atividades", "Mostra o que está acontecendo em cada passo, em tempo real.", "#wizard-log-corpo"),
            E("Copiar", "Copia o registro para a área de transferência (útil para pedir suporte).", "#wizard-log-copiar"),
            E("Limpar", "Esconde o que já aconteceu; não apaga os arquivos de log.", "#wizard-log-limpar"),
        ],
        "dicas": ["Depois da configuração inicial você pode usar qualquer funcionalidade livremente, sem seguir a ordem."],
        "cuidados": ["O passo das credenciais do SERE é obrigatório para os passos seguintes."],
        "veja_tambem": [R("configuracao", "escola"), R("configuracao", "senha_sere"), R("automacao", "turmas"),
                        R("automacao", "gerar_pastas"), R("tela", "whatsapp")],
    },

    "ajuda": {
        "titulo": "Central de ajuda", "icone": "help",
        "resumo": "Índice de toda a ajuda do sistema. Você também pode apertar **F1** em qualquer tela para ver a ajuda dela.",
        "passos": [
            "Digite na busca uma palavra (por exemplo, transferidos, senha, CGM) para achar telas e automações.",
            "Clique no cartão para abrir a ajuda correspondente.",
        ],
        "elementos": [
            E("Busca", "Procura por nome e por conteúdo nas telas e nas automações.", "#aj-busca"),
            E("Telas", "Uma ajuda para cada tela do menu.", "#aj-lista-telas"),
            E("Automações", "Uma ajuda para cada automação, agrupadas como no menu.", "#aj-lista-automacoes"),
            E("Painéis das Configurações", "Uma ajuda para cada painel de Configurações.", "#aj-lista-config"),
        ],
    },
}


# ───────────────────────────── abas de dentro de uma tela ─────────────────────────────

ABAS: dict[str, dict] = {

    "documentos-pc": {
        "titulo": "Aba: Documentos Digitalizados", "icone": "folder",
        "resumo": "O que existe na **pasta de digitalização** do computador, aluno por aluno.",
        "dados": "`documentos-alunos-pc.json`, gerado pela automação **Analisa documentos da pasta**.",
        "passos": [
            "Escolha um filtro: Todos, Com comp. endereço, Sem comp. ou Sem docs básicos.",
            "Busque por aluno, CGM ou nome do documento; ordene clicando nos títulos.",
            "Na coluna **Documentos** cada selo é um arquivo encontrado; os verdes são comprovantes de endereço.",
        ],
        "elementos": [
            E("Cartões", "Totais de alunos, documentos e comprovantes.", "#dc-stats"),
            E("Filtros", "Todos, Com comp. endereço, Sem comp. e Sem docs básicos.", "[data-dcf='all']"),
            E("Busca", "Aluno, CGM ou documento.", "#dc-q"),
            E("Tabela", "Aluno, Turma, Qtd. Docs, Comp. Endereço e a lista de documentos.", "#dc-tbody"),
        ],
        "cuidados": ["Se aparecer \"não gerado\", execute a automação Analisa documentos da pasta."],
        "veja_tambem": [R("automacao", "analisa_pasta"), R("tela", "documentos")],
    },

    "documentos-pive": {
        "titulo": "Aba: Documentos do PIVE", "icone": "files",
        "resumo": "Os documentos que já estão anexados no **SERE (PIVE)**, aluno por aluno, com a contagem de validados e pendentes.",
        "dados": "`documentos-alunos.json`, gerado pela automação **Analisa documentos do SERE**.",
        "passos": [
            "Escolha: Todos, Matriculados, Transferidos ou Com pendentes.",
            "Busque por aluno, CGM ou tipo de documento; ordene pelos títulos.",
            "Compare Total, Validados e Pendentes de cada aluno.",
        ],
        "elementos": [
            E("Cartões", "Totais do SERE.", "#dp-stats"),
            E("Filtros", "Todos, Matriculados, Transferidos e Com pendentes.", "#dp-tabs"),
            E("Busca", "Aluno, CGM ou tipo.", "#dp-q"),
            E("Tabela", "Aluno, CGM, Turma, Situação, Total Docs, Validados, Pendentes e Tipos de Documento.", "#dp-tbody"),
        ],
        "veja_tambem": [R("automacao", "analisa_sere"), R("automacao", "validar"), R("tela", "documentos")],
    },

    "documentos-analise": {
        "titulo": "Aba: Análise", "icone": "compare",
        "resumo": "O cruzamento entre o que está no computador e o que está no SERE: mostra o que **falta anexar** de cada aluno.",
        "dados": "`cruzamento-documentos.json`, gerado pela automação **Cruzamento de docs**.",
        "passos": [
            "Olhe as barras de progresso por tipo de documento (quanto do que está no PC já foi anexado no SERE).",
            "Filtre por Completo, Parcial, Pendente ou Sem básicos; busque por aluno, CGM ou turma.",
            "Clique no botão de expandir da linha para ver cada tipo de documento do aluno (OK, pendente ou ausente).",
        ],
        "elementos": [
            E("Cartões", "Totais por situação do cruzamento.", "#da-stats"),
            E("Progresso por tipo", "Barras com a proporção já anexada no SERE.", "#da-slot-bars"),
            E("Filtros", "Todos, Completo, Parcial, Pendente e Sem básicos.", "#da-filtros"),
            E("Busca", "Aluno, CGM ou turma.", "#da-q"),
            E("Tabela", "Aluno, Turma, Status, Docs no PC, No SERE, Falta anexar e Detalhes por tipo.", "#da-tbody"),
        ],
        "dicas": ["Depois de ver o que falta, use Automações → Documentos para enviar o que está pendente."],
        "veja_tambem": [R("automacao", "cruzamento"), R("automacao", "espec"), R("automacao", "aluno")],
    },

    "prematricula-executar": {
        "titulo": "Painel: Executar pré-matrícula", "icone": "play",
        "resumo": "Roda a coleta da pré-matrícula sem sair da tela.",
        "passos": [
            "Marque as opções, se quiser (pular pendentes, modo de análise).",
            "Clique em **Iniciar pré-matrícula** e acompanhe as etapas.",
            "Para parar, clique em **Cancelar execução**.",
        ],
        "elementos": [
            E("Etapas", "Coleta, cadastro, contatos e pendentes, cada uma marcada conforme avança.", "#pm-etapas"),
            E("Iniciar", "Começa a coleta.", "#pm-exec-iniciar"),
            E("Registro", "Texto do que está acontecendo.", "#pm-exec-log"),
        ],
        "veja_tambem": [R("automacao", "prematricula_completa")],
    },
}


# ───────────────────────────── painéis de Configurações ─────────────────────────────

CONFIGURACOES: dict[str, dict] = {

    "escola": {
        "titulo": "Painel: Dados da escola", "icone": "school",
        "resumo": "Nome, CEP, endereço e identificação da escola. Todos os scripts usam estes dados.",
        "passos": [
            "Preencha o **nome da escola**, o **CEP** e o endereço (os campos com * são obrigatórios).",
            "Digite o CEP e clique em **Buscar endereço**: rua, bairro, cidade e UF são completados sozinhos (ViaCEP e BrasilAPI).",
            "Se quiser, abra **Identificação (opcional)** e informe código da escola, INEP, telefone, e-mail e responsável.",
            "Clique em **Salvar dados da escola**.",
        ],
        "elementos": [
            E("Buscar endereço", "Consulta o CEP e preenche o endereço.", "#esc-buscar-cep"),
            E("Salvar dados da escola", "Grava os dados para todos os scripts.", "#esc-salvar"),
        ],
        "dicas": ["O endereço é a base do cálculo de distância da automação CEP."],
        "veja_tambem": [R("automacao", "cep"), R("tela", "primeira-execucao")],
    },

    "ano_letivo": {
        "titulo": "Painel: Ano letivo", "icone": "calendar",
        "resumo": "Escolha o ano de trabalho, volte a um ano anterior em modo somente consulta ou restaure os dados de um ano a partir de um backup.",
        "dados": "Os dados de cada ano ficam em `dados/<ano>/`.",
        "passos": [
            "Clique no ano desejado: a troca é imediata, sem reiniciar. Só não dá enquanto uma automação estiver rodando.",
            "Para voltar os dados de um ano, escolha o backup, deixe marcado **Só os dados do ano** (não mexe em configuração nem calendário) e clique em **Conferir** (não altera nada).",
            "Se a conferência estiver certa, clique em **Restaurar os dados…** e confirme.",
            "Para testar sem risco, crie **dados fictícios** num ano que não está em uso.",
        ],
        "elementos": [
            E("Anos", "Botões com os anos disponíveis; o atual aparece marcado.", "#cfg-ano-anos"),
            E("Conferir", "Simula a restauração e mostra o que mudaria, sem alterar nada.", "#cfg-ano-conferir"),
            E("Restaurar os dados…", "Aplica a restauração do backup escolhido.", "#cfg-ano-restaurar"),
            E("Criar dados fictícios", "Cria turmas, alunos, funcionários e pré-matrícula inventados, e um backup, num ano que não está em uso. Nunca escreve por cima de dados reais.", "#cfg-ano-gerar"),
        ],
        "cuidados": ["Restaurar substitui os dados do ano escolhido: use **Conferir** antes."],
    },

    "data_corte_transferidos": {
        "titulo": "Painel: Data de corte dos transferidos", "icone": "calendar",
        "resumo": "A partir de que data o processo de transferidos (guia, histórico e parecer) é automático.",
        "passos": [
            "Digite a data no formato dd/mm/aaaa (por exemplo, 22/06/2026) e clique em **Salvar data**.",
            "Para voltar ao valor padrão do sistema, clique em **Usar a data padrão**.",
        ],
        "dicas": [
            "Quem foi transferido **antes** da data é considerado já tratado à mão e não é refeito.",
            "Quem foi transferido e voltou à escola também não é refeito.",
            "Quem foi transferido, voltou e foi **transferido de novo** ganha documentos novos (guia, histórico e parecer). Os da 1ª saída ficam guardados "
            "(os PDFs passam a se chamar \"<nome> (saída dd-mm-aaaa).pdf\").",
        ],
        "veja_tambem": [R("automacao", "transferidos_fila"), R("automacao", "transferidos_gerar"), R("tela", "transferidos")],
    },

    "mapeamento_turmas_qr": {
        "titulo": "Painel: Turmas do QR antigo", "icone": "compare",
        "resumo": "Ensina o sistema a reconhecer o nome da turma escrito no QR antigo dos pareceres, quando ele não bate com o nome da turma no sistema.",
        "passos": [
            "Se a leitura de pareceres não reconheceu alguma turma, ela aparece num quadro no topo do painel: clique em **Usar**, escolha a turma certa e clique em **Salvar turmas**.",
            "Para cadastrar à mão, clique em **+ Adicionar linha**. No campo da esquerda, digite o texto da turma **como está no QR** (por exemplo, INF 4 A). No da direita, escolha a turma certa na lista.",
            "Clique em **Salvar turmas**. A próxima leitura de pareceres já usa os pares.",
            "Para conferir antes, digite um texto em **Testar um texto de turma** e clique em **Testar**: o painel diz qual turma seria escolhida e por qual caminho. As linhas ainda não salvas também valem no teste.",
        ],
        "elementos": [
            E("Turmas não reconhecidas", "Textos de turma que a leitura dos pareceres não reconheceu, com quantos pareceres trouxeram cada um. **Usar** abre a linha já com o texto; **Ignorar** tira da lista (leitura ruim, QR de teste).", "#cfg-qr-sugestoes"),
            E("Linhas dos pares", "Cada linha liga o texto do QR (esquerda) à turma do sistema (direita). Maiúsculas e minúsculas contam igual.", "#cfg-qr-linhas"),
            E("+ Adicionar linha", "Abre uma linha vazia no fim da lista.", "#cfg-qr-add"),
            E("✕", "Remove a linha. Só vale depois de **Salvar turmas**.", "#cfg-qr-linhas"),
            E("Testar", "Mostra a turma que a leitura do parecer escolheria para o texto digitado, ou avisa que não achou (ou que há mais de uma possível).", "#cfg-qr-testar"),
            E("Salvar turmas", "Grava a lista inteira: o que não está na tela deixa de valer.", "#cfg-qr-salvar"),
        ],
        "dicas": [
            "Os pares cadastrados valem **antes** do mapeamento que já vem no sistema e da busca por palavras (que acerta a maioria, como INF 4 A → INFANTIL 4 …).",
            "Se o texto do QR serve para mais de uma turma (por exemplo, \"3º ANO\" com turmas A e B), a leitura não adivinha: cadastre o texto completo, com a letra da turma.",
            "Se uma turma for renomeada ou deixar de existir no ano seguinte, o par aparece marcado como **não existe mais**: escolha a nova turma ou remova a linha.",
            "Os pareceres de turma não reconhecida **continuam na pasta**, esperando: depois de salvar o par, rode a automação de pareceres de novo. A lista só é preenchida nas execuções de verdade (a simulação não grava nada).",
            "O QR novo (com o CGM) não usa este painel.",
        ],
        "veja_tambem": [R("automacao", "pareceres_transferidos"), R("configuracao", "data_corte_transferidos"), R("tela", "transferidos")],
    },

    "minha_conta": {
        "titulo": "Painel: Minha conta", "icone": "userCircle",
        "resumo": "Mostra quem está logado no AUTO SERE, deixa trocar a **sua** senha e sair do sistema. Vale para todos os perfis.",
        "passos": [
            "Clique em **Trocar a minha senha**, digite a senha atual e a nova duas vezes.",
            "Use **Sair do sistema** ao terminar, principalmente em computador usado por mais de uma pessoa.",
        ],
        "elementos": [
            E("Trocar a minha senha", "Abre a tela de troca de senha. Ao trocar, todas as outras sessões abertas com a sua conta são encerradas.", "#cfg-minha-conta"),
        ],
        "dicas": ["Uma boa senha tem 12 caracteres ou mais, misturando letras maiúsculas, minúsculas, números e símbolos; ou uma frase longa de 16+ caracteres."],
        "cuidados": [
            "A senha do AUTO SERE é só sua e **não** é a do SERE. O sistema guarda apenas uma \"impressão digital\" dela (hash), por isso não consegue mostrá-la nem recuperá-la.",
            "Sem uso do mouse ou teclado por cerca de 28 minutos o sistema encerra a sessão sozinho.",
        ],
        "veja_tambem": [R("configuracao", "usuarios")],
    },

    "usuarios": {
        "titulo": "Painel: Usuários e segurança", "icone": "key",
        "resumo": "Só para o **administrador**: cadastra quem pode usar o AUTO SERE, define o perfil de cada um, redefine senhas, desbloqueia contas e mostra o registro de segurança.",
        "passos": [
            "Em **Novo usuário**, escreva o usuário, o nome e o perfil e clique em **Criar usuário**.",
            "O sistema mostra uma **senha temporária** uma única vez. Anote e entregue à pessoa: no primeiro acesso ela é obrigada a trocá-la.",
            "Na tabela, mude o **Perfil**, **Redefina a senha**, **Desbloqueie**, **Desative** ou **Apague** um usuário.",
            "Confira o **Registro de segurança** para ver entradas, tentativas recusadas, bloqueios e mudanças.",
        ],
        "elementos": [
            E("Perfis", "**Administrador**: tudo, inclusive usuários e senhas das integrações. **Operador**: executa as automações e edita registros. **Consulta**: só vê as telas.", "#cfg-usuarios"),
            E("Redefinir senha", "Gera uma senha temporária nova e encerra as sessões daquela pessoa.", "#cfg-usuarios"),
            E("Desbloquear", "Remove o bloqueio que aparece após 5 senhas erradas seguidas (15 minutos, dobrando a cada novo bloqueio).", "#cfg-usuarios"),
            E("Registro de segurança", "Lista os últimos eventos. A mensagem de \"registro íntegro\" confirma que ninguém apagou ou alterou linhas do meio do arquivo.", "#cfg-usuarios"),
        ],
        "dicas": ["Tenha pelo menos **dois administradores**: se um esquecer a senha, o outro redefine. O sistema não deixa apagar, desativar ou rebaixar o último administrador ativo."],
        "cuidados": [
            "Mudar o perfil, desativar ou apagar um usuário encerra a sessão dele na hora.",
            "Se o único administrador esquecer a senha, a recuperação é feita no computador do sistema: `python -m src.seguranca redefinir-senha` (veja documentacao/Seguranca.md).",
        ],
        "veja_tambem": [R("configuracao", "minha_conta")],
    },

    "senha_sere": {
        "titulo": "Painel: Salvar senha do SERE", "icone": "lock",
        "resumo": "Guarda o usuário e a senha do SERE, usados por todas as automações que entram no sistema.",
        "passos": ["Digite o usuário e a senha e clique em **Salvar credenciais**."],
        "cuidados": ["Fica salvo apenas neste computador. Se trocar a senha no SERE, salve aqui de novo."],
    },

    "senha_prematricula": {
        "titulo": "Painel: Senha da Pré-matrícula", "icone": "lock",
        "resumo": "Login e senha do portal da pré-matrícula (diferentes dos do SERE).",
        "passos": ["Digite o login (matrícula) e a senha e clique em **Salvar credenciais**."],
        "cuidados": ["Ficam em credenciais/.env neste computador."],
        "veja_tambem": [R("automacao", "prematricula_completa")],
    },

    "senha_rco": {
        "titulo": "Painel: Senha do RCO", "icone": "lock",
        "resumo": "Login e senha do RCO. Por padrão são os mesmos do SERE, porque ambos entram pela Central de Segurança.",
        "passos": [
            "Deixe marcado **Usar o mesmo login e senha do SERE** se for o caso.",
            "Para usar outros, desmarque, digite CPF ou Login Sentinela e a senha, e clique em **Salvar credenciais do RCO**.",
        ],
        "veja_tambem": [R("automacao", "parecer_rco")],
    },

    "chave_gmail": {
        "titulo": "Painel: Senha do Gmail", "icone": "mail",
        "resumo": "E-mail e senha de app do Gmail, usados para enviar e-mails (avisos e pareceres).",
        "passos": ["Digite o e-mail e a **senha de app** do Google e clique em **Salvar senha do Gmail**."],
        "cuidados": ["Use a senha de app (16 letras), **não** a senha normal da conta. Fica em credenciais/.env neste computador."],
        "veja_tambem": [R("automacao", "avisos"), R("automacao", "pareceres_digitalizados")],
    },

    "planilhas_google": {
        "titulo": "Painel: Planilhas do Google Drive", "icone": "files",
        "resumo": "Guarda o link e o nome das planilhas, cada uma com um id. As planilhas criadas pelo sistema entram aqui.",
        "passos": ["O cadastro completo fica na tela **Planilhas do Drive**, no menu Menu."],
        "veja_tambem": [R("tela", "planilhas")],
    },

    "outras_credenciais": {
        "titulo": "Painel: Outras credenciais", "icone": "key",
        "resumo": "Reservado para outras chaves e tokens de acesso.",
        "cuidados": ["Este painel ainda é só um modelo visual: o botão Adicionar ainda não grava nada."],
    },

    "temas": {
        "titulo": "Painel: Temas", "icone": "palette",
        "resumo": "Escolha do tema visual do sistema.",
        "passos": ["Use os três botões no rodapé do menu lateral: Escuro, Equilibrado e Claro."],
    },

    "perfil": {
        "titulo": "Painel: Perfil", "icone": "userCircle",
        "resumo": "Dados do usuário e permissões.",
        "cuidados": ["Este painel ainda é só um modelo visual: o botão Salvar perfil ainda não grava nada."],
    },

    "pasta_digitalizacao": {
        "titulo": "Painel: Pasta de digitalização", "icone": "folder",
        "resumo": "Pasta raiz onde ficam os documentos digitalizados dos alunos (as pastas das turmas).",
        "dados": "Por padrão é `dados/<ano>/DIGITALIZAÇÃO`.",
        "passos": [
            "Digite o caminho completo da pasta e clique em **Salvar pasta**.",
            "Para voltar à pasta padrão, clique em **Usar pasta padrão**.",
        ],
        "veja_tambem": [R("automacao", "gerar_pastas"), R("automacao", "aluno"), R("automacao", "analisa_pasta")],
    },

    "modelos_parecer": {
        "titulo": "Painel: Modelos de parecer", "icone": "files",
        "resumo": "Envio do modelo Word (.docx) do parecer do Ensino Fundamental e ligação dele às turmas.",
        "passos": [
            "Escolha o arquivo .docx do modelo.",
            "Marque as turmas que usam este modelo.",
            "Clique em **Enviar modelo**.",
        ],
        "dicas": [
            "O modelo precisa ter `$ALUNO`. Também valem `$ESCOLA`, `$TURMA`, `$ANO`, `$CGM` e `$CHAMADA`.",
            "Reenviar um arquivo com o mesmo nome substitui o modelo de todas as turmas ligadas a ele.",
        ],
        "veja_tambem": [R("automacao", "parecer_fund")],
    },

    "navegador": {
        "titulo": "Painel: Navegador das automações", "icone": "globe",
        "resumo": "Escolhe se as automações que abrem navegador usam o Chrome, o Firefox ou o navegador para o qual cada uma foi feita.",
        "passos": [
            "Marque **Automático** para cada script continuar com o navegador que já usava (nada muda).",
            "Ou marque **Chrome** ou **Firefox** para todos os scripts passarem a usar o escolhido.",
            "Clique em **Salvar navegador**. Vale a partir da próxima execução.",
            "Para ver ou esconder a janela do navegador, abra a automação e use **Configurações do script**.",
        ],
        "elementos": [
            E("Opções de navegador", "Automático, Chrome ou Firefox.", "#cfg-nav-opcoes"),
            E("Salvar navegador", "Grava a escolha para todas as automações.", "#cfg-nav-salvar"),
        ],
        "cuidados": ["O script do RCO precisa do Chrome e ignora esta escolha."],
    },

    "backup_automatico": {
        "titulo": "Painel: Backup automático", "icone": "database",
        "resumo": "Liga ou desliga o backup que o sistema faz sozinho ao fim das coletas de turmas, alunos e funcionários.",
        "passos": [
            "Marque **Fazer backup automático ao fim das coletas** para ligar, ou desmarque para desligar.",
            "Clique em **Salvar**. Vale a partir da próxima coleta.",
        ],
        "elementos": [
            E("Fazer backup automático", "Marcado = cada coleta termina com um backup dos dados do ano.", "#cfg-backup-auto-ligado"),
            E("Situação", "Mostra se o backup automático está ligado de verdade e avisa se algo o está desligando por fora.", "#cfg-backup-auto-status"),
            E("Salvar", "Grava a escolha.", "#cfg-backup-auto-salvar"),
        ],
        "dicas": [
            "Ficam os 7 backups automáticos mais recentes; eles não empurram para fora os backups manuais.",
            "Coletas seguidas (menos de 30 minutos) trocam o automático anterior pelo novo.",
        ],
        "cuidados": [
            "Desligar não apaga os backups que já existem. O backup manual (Automações → Backup) continua funcionando.",
            "Se a variável de ambiente AUTO_SERE_BACKUP_AUTO estiver em 0 no computador, ela desliga o backup acima desta escolha, e o painel avisa.",
        ],
    },

    "google_conta": {
        "titulo": "Painel: Conta Google da autorização", "icone": "lock",
        "resumo": "Define com qual conta, em qual navegador e em qual perfil abre o link de autorização do Google (planilhas e contatos).",
        "passos": [
            "Digite o **e-mail da conta Google** que é dona das planilhas. O Google já abre o login com essa conta escolhida.",
            "Escolha o **navegador**. No Chrome e no Edge, se um perfil estiver logado nessa conta, o perfil certo é achado sozinho; se preferir, escolha o perfil na lista.",
            "Clique em **Testar abertura** para ver se abre na conta certa e, estando certo, em **Salvar**.",
            "Se preferir copiar o link e colar você mesmo, desmarque **Abrir o navegador sozinho**: na hora de autorizar, a janela mostra o link com o botão **Copiar link**.",
        ],
        "elementos": [
            E("E-mail da conta Google", "Conta que deve autorizar.", "#cfg-gconta-email"),
            E("Navegador", "Navegador padrão do computador, Chrome, Edge ou Firefox.", "#cfg-gconta-nav"),
            E("Perfil do navegador", "Perfil do Chrome/Edge em que o link abre (Automático = o logado na conta).", "#cfg-gconta-perfil"),
            E("Testar abertura", "Abre a página da sua conta Google com estas escolhas, ainda sem salvar.", "#cfg-gconta-testar"),
        ],
        "cuidados": ["A autorização só se completa no computador onde o AUTO SERE roda; de outro computador, use o campo de colar o endereço final na janela de autorização."],
        "veja_tambem": [R("modal", "autorizar-google")],
    },
}


# ───────────────────────────── janelas (modais) ─────────────────────────────
# O JavaScript reconhece a janela pelo título (ver ajuda.js → detectarModal).

MODAIS: dict[str, dict] = {

    "confirmar-execucao": {
        "titulo": "Janela: Confirmar execução", "icone": "alertFile",
        "resumo": "Aparece antes de automações que **alteram dados** (no SERE, em planilhas ou em arquivos). Mostra o aviso e a prévia de quantos alunos serão afetados.",
        "passos": [
            "Leia o aviso e a **Prévia** (por exemplo, 12 alunos).",
            "Se estiver certo, clique em **Confirmar e executar**. Para desistir, **Cancelar** ou **Esc**.",
        ],
        "dicas": ["Marcar **Modo de teste** na tela da automação pula esta confirmação e processa só o primeiro."],
        "cuidados": ["Modo de teste **não é simulação**: o item processado é alterado de verdade. A simulação existe só nas automações que têm a caixa **Simulação**."],
    },

    "pergunta-automacao": {
        "titulo": "Janela: A automação precisa de uma informação", "icone": "help",
        "resumo": "A automação parou para pedir um dado (por exemplo, o código de verificação que o RCO manda por e-mail).",
        "passos": [
            "Digite a resposta e clique em **Enviar** (ou tecle Enter).",
            "Se a resposta estiver errada, a janela mostra o erro e você pode tentar de novo.",
            "**Cancelar execução** encerra a automação.",
        ],
        "dicas": ["Se você fechar a janela com Esc sem responder, ela reabre em poucos segundos porque a automação continua esperando."],
    },

    "autorizar-google": {
        "titulo": "Janela: Autorizar acesso ao Google", "icone": "lock",
        "resumo": "Aparece sozinha quando o Google precisa da sua permissão. Mostra o link de autorização para você abrir ou copiar.",
        "passos": [
            "Se o link abriu no navegador/perfil certo, entre na conta indicada e clique em **Permitir**; a janela fecha sozinha.",
            "Se abriu na conta errada, clique em **Copiar link** e cole no navegador (ou perfil) da conta certa.",
            "Em outro computador, depois do **Permitir** cole na janela o endereço completo que apareceu (começa com http://localhost) e clique em **Concluir com este endereço**.",
        ],
        "veja_tambem": [R("configuracao", "google_conta")],
    },

    "credenciais-sere": {
        "titulo": "Janela: Credenciais do SERE", "icone": "lock",
        "resumo": "Pede o usuário e a senha do SERE (a senha fica escondida).",
        "passos": ["Digite o usuário e a senha e confirme."],
    },

    "dados-escola": {
        "titulo": "Janela: Dados da escola", "icone": "school",
        "resumo": "Formulário com nome, CEP e endereço da escola.",
        "passos": ["Preencha nome e CEP, clique em **Buscar endereço** para completar o restante, confira e clique em **Salvar dados da escola**."],
        "veja_tambem": [R("configuracao", "escola")],
    },

    "planilha-formulario": {
        "titulo": "Janela: Cadastrar / Editar planilha", "icone": "database",
        "resumo": "Registra uma planilha no cadastro do sistema.",
        "passos": [
            "Informe o **nome**, a **plataforma** (Google Sheets, Excel ou LibreOffice) e o **link** (ou só o ID) — ou o caminho do arquivo no computador.",
            "Escolha **categoria** e **situação** (Ativa ou Inativa).",
            "Em **Finalidade no sistema** escolha o uso (Pareceres do Infantil, Planilha das Turmas, Chamada, Listagem dos Alunos ou IMC). "
            "Em usos por turma, informe a **turma** exatamente como em turmas.json.",
            "Clique em **Cadastrar** (ou **Salvar alterações**).",
        ],
        "dicas": ["As automações usam a planilha **ativa** de cada uso (e turma)."],
    },

    "planilha-modelo": {
        "titulo": "Janela: Criar planilha a partir de um modelo", "icone": "folderPlus",
        "resumo": "Cria uma planilha nova já preenchida com os alunos e a cadastra.",
        "passos": [
            "Escolha o **modelo** e onde criar (Google Sheets, Excel ou LibreOffice).",
            "Em modelos por turma, escolha a turma. O nome é opcional (em branco = modelo + turma + ano).",
            "Marque **Passar a usar a nova planilha** se quiser torná-la a ativa (a antiga fica inativa).",
            "Clique em **Criar e cadastrar**.",
        ],
    },

    "mensagem-responsavel": {
        "titulo": "Janela: Mensagem para o responsável", "icone": "send",
        "resumo": "Prepara e envia, pelo WhatsApp, a mensagem ao responsável de um aluno da pré-matrícula.",
        "passos": [
            "Confira o número e edite o texto, se quiser.",
            "Se o WhatsApp estiver conectado de verdade, marque **Confirmo o envio de uma mensagem de verdade**.",
            "Clique em **Enviar**.",
        ],
        "cuidados": ["Em modo simulado nada é enviado. O responsável precisa ter telefone coletado."],
        "veja_tambem": [R("tela", "whatsapp")],
    },
}

# PENDÊNCIAS — AUTO SERE

Lista curta do que ainda falta. O detalhe e o histórico estão em [`PROXIMAS_ETAPAS.md`](PROXIMAS_ETAPAS.md) (os números, como 3b e 11q, são os mesmos) e os bugs em [`BUGS_CONHECIDOS.md`](BUGS_CONHECIDOS.md).

Atualizado em 2026-11-02. Legenda: `[ ]` pendente · `[!]` depende de ambiente real ou de decisão · `[x]` decidido/feito.

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

### Tela Alunos
- [!] Abrir o calendário depois de colocar a atualização: conferir se o `calendario.json` antigo foi dividido certo em `dados/<ano>/calendario.json` (o antigo fica como `dados/calendario/calendario.json.antes-da-migracao`)
- [!] Abrir com os `alunos.json` e `alunos_completo.json` reais e ver se aparecem divergências falsas (⚠)

---

## 2. Funcionalidades pendentes

### `avisos` (e-mail)
Uso real, definido em 2026-11-02: (1) escrever **para a escola de origem**, na hora da transferência, pedindo a documentação de aluno que está vindo; (2) avisar os **responsáveis de alunos que estão saindo**. Hoje só existem os públicos "todas as escolas/CMEIs" (em massa) e "pais da pré-matrícula", que não cobrem nenhum dos dois.

- [ ] Público **escola de origem**: um e-mail por aluno que chega, para uma escola escolhida, com nome, CGM e série do aluno e a lista de documentos pedida
- [!] Decidir de onde vem a escola de origem: o sistema não tem esse dado (digitar na hora, escolher na lista de `escolas_completas.json` ou campo no cadastro)
- [ ] Público **responsáveis de quem sai**: destinatários de `transferidos.json` / fila de transferidos, com o e-mail do responsável do cadastro
- [ ] E-mail de escola escrito de forma disfarçada (ex.: "nome [arroba] dominio") não é reconhecido: reconhecer as variações comuns e mostrar "sem e-mail" na tela, não só no log
- [ ] Responsável sem e-mail: hoje só vai para o log; para quem sai, mostrar na tela e oferecer outro caminho (WhatsApp ou aviso impresso)
- [ ] Liberar o **envio real** (hoje recusado de propósito): confirmação com prévia, intervalo entre e-mails, limite por lote, envio em segundo plano com pausa/cancelamento, registro de quem recebeu e de quem falhou
- [ ] Outros canais: WhatsApp e SERE
- [ ] Confirmar se o público em massa "todas as escolas/CMEIs" ainda é útil

### WhatsApp
- [ ] **7b**: fila de envio com intervalo e limite diário, pausa/cancelamento, histórico e modelos de mensagem

### Backup
- [ ] **3b**: backup automático ao fim das coletas (turmas, alunos, funcionários)

### Funcionários
- [ ] Modo completo: retomar de onde parou (hoje salva aos poucos e avisa se parar no meio, mas rodar de novo refaz todos)
- [!] Decidir se os termos de ciência pulam quem tem `na_escola = false`

### Transferidos
- [ ] Aluno transferido duas vezes no ano: a segunda saída não é tratada
- [ ] Painel: a tabela "Transferidos" lê só quem está em processo (o "Total" não é o total da escola; não mostra pré-corte nem retornados)
- [ ] Mapeamento de turmas do QR só por arquivo, sem tela

### Script futuro
- [ ] Decodificar o QR dos pareceres e enviar ao SERE e por e-mail (falta escolher a biblioteca de leitura de QR)

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

- [ ] Preencher os três `src/web/templates/partials/help/*.html` (hoje vazios): textos de ajuda (planejado)

---

## 5. Decidido

- [x] **10g**: o wizard (1ª execução) fica só com o modo **básico** de Alunos, porque o completo demora mais; o completo segue em Automações → Alunos
- [x] **Documentação e arquivos soltos** (2026-11-02): porta 8000 corrigida em `src/web/README.md` e `diagrama_de_funcionamento.md`; `backup_auto_sere.py` usa a pasta da instalação (não mais `C:\Auto_sere` fixo); tarefa "Bootstrap: criar_projeto.py" removida do `.vscode/tasks.json` (o script não é mais necessário)
- [x] **Não são pendência:** `config_usuario.json` com `setup_concluido = false` e unidade sem dados (preenchido quando o usuário informa os dados); `AUTO_SERE_MAPA.txt` vazio (ignorado); `BUGS_CONHECIDOS.md` (só recebe bugs quando aparecerem; nenhum achado até agora)
- [x] **Calendário por ano letivo** (2026-11-02): `dados/<ano>/calendario.json`; voltando o ano aparece o calendário daquele ano (só consulta); o arquivo único antigo é dividido por ano na primeira abertura e guardado, sem apagar nada
- [x] **10h**: a tela Alunos une `alunos.json` e `alunos_completo.json` numa ficha única, com todos os campos sempre visíveis e "—" onde falta dado (2026-11-02). O HTML fica todo em `alunos_completo_cards.html` (não apagar); `alunos_cards.html` só o inclui
- [x] **Funcionários completo salva aos poucos** (2026-11-02): grava a cada 5 cadastros, não encolhe o arquivo no meio da coleta e, se parar (cancelada, erro ou queda), avisa no log e na tela de Funcionários

---

## Ordem sugerida

1. Rodar `pytest tests` (linha de base)
2. Limpar as duplicatas (seção 3), conferindo antes qual cópia é a usada
3. Execução real com um aluno no SERE (transferidos e coletas); fechar os `[!]`
4. Confirmar BUG-PRE-001 quando o site da pré-matrícula voltar
5. Decidir a origem da escola de origem e criar os dois públicos novos do `avisos`
6. Lock de execução (11q)
7. Só então liberar o envio real do `avisos` e a fila do WhatsApp

# PENDÊNCIAS — AUTO SERE

Consolidação do que ainda falta, a partir de `PROXIMAS_ETAPAS.md` (atualizado em 2026-11-01), `BUGS_CONHECIDOS.md` e da estrutura do projeto.
Gerado em 2026-11-01. Legenda: `[ ]` pendente · `[!]` depende de ambiente real ou decisão.

---

## 1. Validação no ambiente real (maior risco)

Quase tudo foi testado só com navegador ou dados simulados.

### SERE
- [!] Coletas de **Turmas**, **Alunos** (básico e completo) e **Funcionários**: executar de verdade
- [!] **`vinculos`**: RH (endpoint de estagiários deduzido por analogia) e leitura do holerite (depende do layout atual do site)
- [!] **`sus`/SISREG**: consulta real
- [!] Automações migradas para o registro (item 11 do PROXIMAS_ETAPAS): uma execução real de cada, com "Modo de teste"

### Transferidos
- [!] Emitir, assinar, baixar e enviar de verdade, com um aluno real
- [!] Leitura de QR com scans reais (testada só com PDFs gerados)
- [!] `parecer_fund`: fluxo completo no computador da escola e modelos dos demais anos

### RCO
- [!] `parecer_rco`: login, 2FA, nomes dos botões e download no site real (ajustar seletores se mudou)

### WhatsApp
- [!] Primeiro pareamento e envio com número real
- [!] Testar no Windows (`whatsplay`)

### Pré-matrícula e rematrícula
- [!] **BUG-PRE-001**: consulta por CPF pode ler só o primeiro cadastro (talvez o cancelado). Confirmar quando o site voltar (ver passos em `BUGS_CONHECIDOS.md`)
- [!] Conferência ao vivo da coleta (BUG-PRE-002 corrigido, falta validar com coleta real)
- [!] **BUG-REM-001**: clique final de "Confirmar" tratado como sucesso sem conferir a página

---

## 2. Funcionalidades pendentes

### `avisos`
- [ ] Liberar o **envio real** de e-mail (hoje recusado de propósito): confirmação com prévia, intervalo entre e-mails, limite por lote, envio em segundo plano com pausa/cancelamento, registro de quem recebeu e de quem falhou
- [ ] Outros canais: WhatsApp e SERE
- [ ] Pais sem e-mail (hoje só listados no log); e-mails de escolas escritos de forma disfarçada não são reconhecidos

### WhatsApp
- [ ] **7b**: fila de envio com intervalo e limite diário, pausa/cancelamento, histórico e modelos de mensagem

### Backup
- [ ] **3b**: backup automático ao fim das coletas (turmas, alunos, funcionários)

### Alunos
- [ ] **10g**: passo "Alunos" do wizard só no modo básico; decidir se oferece o completo
- [ ] **10h**: nenhuma tela lê `alunos_completo.json`; definir quem vai usá-lo

### Funcionários
- [ ] Modo completo só grava no fim: cancelar ou cair no meio perde a coleta toda (salvar aos poucos, como `alunos_completo`)
- [ ] Decidir se os termos de ciência pulam quem tem `na_escola = false`

### Transferidos
- [ ] Aluno transferido duas vezes no ano: a segunda saída não é tratada
- [ ] Painel: a tabela "Transferidos" lê só quem está em processo (não mostra pré-corte nem retornados; o "Total" não é o total da escola)
- [ ] Mapeamento de turmas do QR só por arquivo (`mapeamento_turmas_qr`), sem tela

### Script futuro
- [ ] Decodificar o QR dos pareceres (`parecer_fund.ler_payload_qr`) e enviar ao SERE e por e-mail; escolher a biblioteca de leitura de QR (não está no `requirements.txt`)

---

## 3. Limpeza e robustez

- [ ] Apagar cópias mortas em `src/automacao/`: `sere_api.py`, `sere_limpeza.py`, `sere_upload.py`, `sere_utils.py`
- [ ] Conferir e remover duplicatas aparentes: `src/automacao/executar_*.py` (mesmos tamanhos que em `src/comum/`) e `src/automacao/test_gerar_pastas.py` (existe também em `tests/`)
- [ ] **11q**: trava contra execução simultânea é por processo; criar arquivo de lock em `locks/`
- [ ] Teste intermitente `tests/test_ui_automacoes.py::test_funcionarios_e_vinculos_estao_no_menu_...` (rótulo "Sistema" cobre o item "Vínculos")
- [ ] Modo consulta: desabilitar os botões de escrita das demais telas (hoje o servidor recusa, mas o botão continua clicável)
- [ ] Editar `config_usuario.json` à mão com o programa aberto só vale ao reiniciar (faixa avisa e oferece "Aplicar agora")
- [ ] Rodar `python -m pytest tests` para ter a linha de base atual

---

## 4. Documentação e configuração

- [ ] Atualizar cabeçalho do `PROXIMAS_ETAPAS.md` ("Última atualização: 2026-10-31", mas há entradas de 01/11)
- [ ] Atualizar `BUGS_CONHECIDOS.md` (última atualização 2026-10-30)
- [ ] Remover de "Depois (não iniciadas)" o item "Registro de scripts com componentes compartilhados" (já feito, item 11)
- [ ] Preencher ou remover `AUTO_SERE_MAPA.txt` (1 byte) e os três `src/web/templates/partials/help/*.html` (vazios)
- [!] `config/config_usuario.json`: `setup_concluido` está `false`; unidade escolar sem `codigo`, `inep`, `telefone`, `email` e `responsavel`

---

## Ordem sugerida

1. Rodar `pytest tests` (linha de base)
2. Execução real com um aluno no SERE (transferidos e coletas); fechar os `[!]`
3. Confirmar BUG-PRE-001 quando o site da pré-matrícula voltar
4. Limpar as cópias mortas
5. Lock de execução (11q)
6. Só então liberar o envio real do `avisos` e a fila do WhatsApp

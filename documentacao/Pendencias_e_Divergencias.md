# Pendências e divergências encontradas

Resumo de `pendencias.md` (2026-11-02) mais o que a leitura do zip mostrou. Itens `[!]` dependem de ambiente real ou decisão.

## Validar no ambiente real (maior risco)
SERE (coletas de Turmas/Alunos/Funcionários, vínculos, SISREG, uma execução de cada automação com modo de teste) ·
Transferidos (emitir/assinar/baixar/enviar com aluno real; QR com scans reais; `parecer_fund`) · RCO (login, 2FA, seletores) ·
**WhatsApp (primeiro pareamento e envio real; `whatsplay` no Windows)** · Pré-matrícula (BUG-PRE-001, coleta ao vivo,
BUG-REM-001) · Tela Alunos com dados reais.

## Funcionalidades
`avisos` (público escola de origem e responsáveis de quem sai; envio real; outros canais) · **WhatsApp 7b (fila)** ·
backup automático após coletas (3b) · Funcionários completo retomar de onde parou · transferido duas vezes no ano ·
painel de transferidos · decodificar QR dos pareceres.

## Limpeza e robustez
- Lock de execução por arquivo em `locks/` (11q); hoje a trava é por processo.
- Teste intermitente em `test_ui_automacoes.py` (rótulo "Sistema" cobre "Vínculos"); falha também no zip original.
- Modo consulta: botões de escrita ainda clicáveis (o servidor recusa).
- `pytest tests` ainda sem linha de base na máquina do usuário.

## Código duplicado (apagar com cuidado)
| Apagar | Motivo | Não apagar |
|---|---|---|
| `src/automacao/sere_api.py`, `sere_limpeza.py`, `sere_upload.py`, `sere_utils.py` | versões antigas; ninguém importa (usa-se `src/comum/`) | — |
| `src/comum/executar_{aluno,analisa,documento,espec,transferidos,validar}.py` | cópias idênticas das de `src/automacao/` | **as de `src/automacao/` são as usadas** (o registro importa de lá); `src/comum/executar_limpeza.py` é usado |
| `src/automacao/test_gerar_pastas.py` | idêntico a `tests/test_gerar_pastas.py` | — |

## Divergências na documentação/configuração
- `src/web/README.md` e `diagrama_de_funcionamento.md` dizem porta **5000**; a padrão é **8000**.
- `.vscode/tasks.json`: tarefa "Bootstrap: criar_projeto.py" aponta para arquivo inexistente.
- `backup_auto_sere.py` com `C:\Auto_sere` fixo.
- `AUTO_SERE_MAPA.txt` (1 byte) e `partials/help/*.html` (3, vazios).
- `BUGS_CONHECIDOS.md` parou em 2026-10-30.
- `config_usuario.json`: `setup_concluido=false`, `ano_letivo="2025"`, unidade sem `codigo/inep/telefone/email/responsavel`.
- O diagrama antigo lista a ordem "alunos antes de funcionários"; o wizard usa funcionários antes (ambas funcionam).
- README cita "mais de 30 rotinas"; o registro tem **31** chaves.

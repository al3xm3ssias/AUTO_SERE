# Relatórios e extras

## Encaminhamentos do SUS (`sisreg.py`, chave `sus`)
Para cada aluno de `alunos.json`, consulta **por CPF** o sistema público SISREG/FMS de Ponta Grossa
(`fms.pontagrossa.pr.gov.br/lista-espera-sisreg-cpf`, sem login). Se houver encaminhamento/procedimento em fila de espera,
grava o aluno, o CPF e a lista em `alunos_encaminhamento.json`. Tela: Encaminhamentos do SUS (`/encaminhamentos/lista`).
O painel conta também os CPFs inválidos. **[não validado]** consulta real.

## CEP e alunos fora do raio (`src/comum/cep_api.py`, chave `cep`)
Geocodifica o CEP de cada aluno (AwesomeAPI; *fallback* ViaCEP + Nominatim quando a coordenada parece genérica ou falha) e
calcula a distância até a escola. **Raio padrão: 2,0 km** (campo da automação). O CEP da escola vem de Configurações → dados da
escola. Saídas: `alunos_fora_raio.json/.xlsx` e `alunos_coordenadas.json`. Transferidos e nomes duplicados são ignorados.
Tela: Alunos fora do raio (`/fora-do-raio/lista`). Consulta de endereço por CEP no cadastro da escola: `cep_consulta.py`
(ViaCEP e BrasilAPI; `GET /cep/<cep>`).

## Calendário letivo (`src/web/api/calendario.py`, `calendario.js`)
Períodos letivos, recessos e feriados municipais (cadastrados pelo usuário) combinados com os **feriados nacionais da
BrasilAPI** (cache em disco, fora do backup). Rotas em `/web/api/calendario`: `dados`, `feriados/<ano>`, `fixos/<ano>`
(feriados fixos de Ponta Grossa e datas comemorativas), `eventos` (POST/DELETE), `periodos`. Dados em `dados/calendario/`
(entram no backup). O ano do calendário define quando o sistema entra em "somente consulta".

## Compara anos (`comparar_anos.py`, chave `compara_anos`)
Só lê `dados/<ano>/turmas.json` de dois anos (não acessa o SERE). O **CGM** liga o aluno entre anos. Cada aluno cai em uma
categoria (A = ano base, B = comparado): **Transferidos** (em B como transferido), **Continuam** (movimento: Promovido,
Mesma série, Mudou de turma…), **Novos**, **Saíram** (motivo: "Concluiu a etapa" se estava na última série da escola;
"Verificar" se saiu antes; "Já estava transferido no ano base" não conta). A série vem do nome da turma ("5º Ano Integral A" → 5).

## Máscara de dados (`mascarar.py`, chave `mascara`)
Gera `*_mask.json` ao lado dos originais trocando cada caractere alfanumérico por `x`, números por `0` e booleanos por `x`.
Serve para compartilhar **estrutura** (pedir ajuda, anexar exemplos) sem expor dados reais. Retorna a lista de arquivos processados.

## Ferramentas de desenvolvimento
- `analisar_io_scripts.py` → `RELATORIO_IO.md` (análise estática dos scripts: o que cada um lê/grava).
- `gerar_zip.sh` (usa `git ls-files`) e `backup_auto_sere.py` (pacote para envio).
- `src/comum/dados_ficticios.py`: dados falsos de 2025 para testar telas.

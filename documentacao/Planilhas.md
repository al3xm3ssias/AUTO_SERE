# Gerenciador Centralizado de Planilhas

Nenhum módulo do sistema guarda caminho, link ou ID de planilha. Tudo é cadastrado em **Planilhas do Drive** e os módulos
perguntam ao gerenciador (`src/comum/planilhas_gerenciador.py`) qual planilha usar, **por finalidade** (e por turma, quando for o caso).

## Três coisas separadas
| | O que é | Onde vive |
|---|---|---|
| **Modelos** | estruturas criadas e mantidas pelo sistema (Chamada, Planilha das Turmas, Listagem dos Alunos, IMC) | `src/comum/planilhas_modelos.py` (+ `.json` em `config/modelos_planilha/`) |
| **Planilhas cadastradas** | os arquivos em uso no dia a dia, ligados a uma finalidade | `dados/planilhas/planilhas.json` (`planilhas_registro.py`) |
| **Planilhas externas** | recebidas prontas da Secretaria (pareceres do Infantil); nunca nascem de modelo | mesmo cadastro, com `natureza = externa` |

## Finalidades (`FINALIDADES_INFO`)
| Finalidade | Por turma? | Quem usa |
|---|---|---|
| `parecer_infantil` (externa) | sim | `parecer_planilha` (gera PDF dos pareceres) |
| `planilha_turmas` | não | `sincroniza_sheets` / rotina diária (movimentação dos alunos) |
| `chamada` | sim | modelo Chamada (uma planilha por turma) |
| `listagem_alunos` | não | modelo Listagem |
| `imc` | não | modelo IMC |

Em cada finalidade (e turma) só **uma** planilha fica *ativa* (a vigente). Trocar de planilha = **Usar esta** na nova (a antiga fica
inativa na mesma operação); substituir o arquivo de um uso = editar o link/caminho do registro. Nada disso mexe no código.

## Plataformas (`planilhas_plataformas.py`)
Google Sheets, Excel (`.xlsx`) e LibreOffice Calc (`.ods`). Cada uma é um plugue (`referencia` valida/normaliza, `criar` gera a
planilha a partir das abas neutras do modelo). Os modelos usam fórmulas em notação universal, então as três saem com a mesma
estrutura, colunas e fórmulas. `.ods` precisa do LibreOffice instalado (a criação usa um perfil temporário próprio).
Hoje a **atualização** dos alunos e a **geração dos pareceres em PDF** trabalham só com Google Sheets (usam a API e a exportação do
Google); qualquer outra plataforma é recusada com mensagem clara.

## Como o usuário usa
* **Cadastrar** uma planilha existente (qualquer plataforma) ou **Criar de modelo** na tela *Planilhas do Drive* (ou a automação
  *Criar planilha de modelo*): escolhe modelo, plataforma e turma; a planilha sai preenchida com os alunos do `turmas.json` e já cadastrada.
* **Pareceres (planilha)**: o formulário pede a planilha cadastrada (ou "todas as ativas") e o filtro de turma.
* **Planilha das turmas (Google Sheets)**: o formulário escolhe a cadastrada; vazio = a ativa.

## Como o desenvolvedor usa
```python
from src.comum import planilhas_gerenciador as gp
ref = gp.resolver("planilha_turmas")                     # a vigente
ref = gp.resolver("chamada", turma="1º Ano Integral A")  # a vigente da turma
ref = gp.resolver("parecer_infantil", id_item=7, plataformas=["google_sheets"])   # a que o usuário escolheu
gp.opcoes_para_formulario("chamada")                     # para um seletor de tela
gp.criar_de_modelo("imc", "xlsx", turmas_selecionadas=["1º Ano Integral A"])
```
Erros: `PlanilhaNaoCadastrada` (diz o que cadastrar), `PlanilhaAmbigua` (pede para escolher), `ValueError` (plataforma/turma erradas).

**Novo modelo**: `registrar_modelo(Modelo(...))` ou um `.json` em `config/modelos_planilha/` (formato em `_modelo_de_json`); mesma
chave de um padrão = substitui. **Nova plataforma**: classe `Plataforma` + `registrar_plataforma(...)`. Nenhum módulo muda.

O teste `test_nenhum_modulo_guarda_link_id_ou_caminho_de_planilha_no_codigo` falha se alguém voltar a fixar um ID/link no código.

## Observações dos modelos
* **IMC**: peso e altura digitados, IMC calculado; a *classificação* é escolhida numa lista (para crianças depende de idade e sexo —
  IMC-para-idade da OMS —, não de faixas fixas de adulto).
* **Chamada**: uma aba por mês (fevereiro a dezembro), P/F/J por dia, totais e % de frequência (presenças ÷ P+F+J).

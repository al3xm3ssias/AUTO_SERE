# Pareceres

Dois fluxos independentes, mais os pareceres dos transferidos (ver `Transferencias.md`).

## Fundamental — `parecer_fund` (Word → PDF + QR criptografado)
Pedido de 20/10/2026. O parecer é um **arquivo `.docx` modelo enviado por upload**; o sistema gera uma cópia preenchida por aluno.
Em 07/11/2026: a saída para imprimir passou a ser **PDF** e o QR passou a levar mais dados, **criptografados**.

- Modelos em `<base>/MODELO/`, com `controle_modelos.json` ligando **turma → arquivo de modelo** (um modelo pode servir a
  várias turmas; reenviar com o mesmo nome substitui). Limite de upload: `LIMITE_MODELO_MB = 15`.
- **Formato** (campo "Formato do parecer" na tela; padrão em `config_usuario.json` → `parecer_fund_formato`, senão `pdf`):
  - `pdf`: `<base>/<ano>/PARECERES/_PARA_IMPRIMIR/<turma>/<nº da chamada> - <nome>.pdf`. Converte com o **LibreOffice**
    (`src/comum/conversao_pdf.py`; caminho próprio em `AUTO_SERE_SOFFICE`), 25 por vez. Sem LibreOffice, a geração para
    **antes** de criar qualquer arquivo e diz como resolver. Fica fora da pasta da turma porque o parecer **digitalizado**
    é arquivado lá com o mesmo nome.
  - `docx`: `<base>/<ano>/PARECERES/<turma>/<nº da chamada> - <nome>.docx` (como antes). `ambos`: os dois.
  - A base é `dados/` (ou `AUTO_SERE_PARECERES_BASE`).
- Marcadores no Word: `$ALUNO` (**obrigatório** — sem ele todos sairiam iguais), `$ESCOLA`, `$TURMA`, `$ANO`, `$CGM`, `$CHAMADA`.
- **QR code** no **fim** do arquivo (200 px no Word), texto `AUTOSERE|PF2|<criptografado>` com **ano letivo, nº da chamada,
  nome, turma e CGM** (`src/comum/qr_seguro.py`: AES-256-GCM; a câmera do celular mostra só texto embaralhado e um QR
  alterado não abre). A **chave** fica em `credenciais/chave_qr.key` (ou na variável `AUTO_SERE_QR_CHAVE`), é criada na
  1ª geração e **não é versionada**. ⚠️ **Guarde uma cópia**: sem ela, os QR já impressos não podem mais ser lidos, e em
  outro computador é preciso copiar o arquivo para `credenciais/`.
- `ler_payload_qr` lê os dois formatos: o criptografado e o antigo em texto aberto (`AUTOSERE|PF|<ano>|<CGM>`).
  Quem lê (digitalizados e transferidos) acha o aluno pelo CGM e confere se o **ano do QR é o ano letivo em uso**.
- **Nunca sobrescreve** um parecer que já existe (cada formato é conferido à parte), salvo pedido de "substituir".
- Gerenciar modelos: Configurações → modelos de parecer (`/configuracoes/modelos-parecer`).
- **[não validado]** fluxo completo no computador da escola (LibreOffice no Windows, leitura do scan impresso de verdade)
  e modelos dos demais anos.

## Infantil — `parecer_rco` (RCDIG/RCO)
Baixa os PDFs dos alunos **Matriculados** de Infantil IV e V.
1. Login na Central de Segurança (login Sentinela/CPF + senha; por padrão as do SERE, ou as próprias em Configurações → RCO).
2. O RCO envia **código 2FA por e-mail**; a tela abre uma caixa e pede o código (sem resposta em **10 min**, a execução
   termina com mensagem clara; na CLI continua `input()`).
3. Estabelecimento → Relatórios → Consultar Aluno, com o período letivo.
4. Por CGM: solicita o parecer, espera o processamento e baixa o PDF.
- Campo **bimestre** ("2" ou "4") escolhe a subpasta; modo teste processa só o primeiro aluno; opção de mostrar navegador.
- Destino: `dados/<ano>/PARECERES INFANTIL/<N>º Bimestre/<turma>/<nº chamada> - <nome>.pdf`
  (ou `AUTO_SERE_PARECERES_INFANTIL_DIR`).
- **Segurança:** diagnóstico (captura, HTML, log de rede) só quando o **login falha**, em `dados/<ano>/debug_rco/`; o log não
  guarda a query das URLs (têm o `code` do OAuth) e os cookies guardam só nome e domínio.
- **[não validado]** login, 2FA, nomes de botões e download no site real (ajustar seletores se mudou).

## Infantil — `parecer_planilha` (planilhas do Google, 1º e 3º bimestres)
Portado de `gerar_pareceres_infantil_planilha.py`. As professoras do Infantil preenchem uma planilha do Google por turma
(Infantil IV e V); o sistema gera um PDF por aluno **Matriculado** a partir dela. É a metade "planilha" dos pareceres do
Infantil: faz o **1º e o 3º bimestre**, e o `parecer_rco` (acima) faz o **2º e o 4º**. Os dois gravam na mesma árvore de
pastas, então o resultado fica junto.
1. **Cadastre as planilhas** em *Planilhas do Drive*: uma por turma, com a finalidade **Pareceres do Infantil** e a **turma**
   (o nome igual ao de `turmas.json`, por exemplo `INFANTIL 4 Integral A`). Só vale a planilha **Ativa**; para trocar de
   planilha (outro ano, outro bimestre) deixe a antiga inativa e ative a nova. O sistema não deixa haver duas ativas para a
   mesma turma.
2. Em *Automações → Pareceres infantil (planilha)*, escolha o **bimestre** (1º ou 3º) e execute.
3. Para cada aluno, na ordem do nº de chamada: grava o nome na célula `C5` da aba `F.D.SON. A` (a lista suspensa), espera
   a planilha recalcular (3 s), exporta `A1:N52` em PDF (A4 paisagem), cola o **QR code** no canto inferior esquerdo da
   última página e salva. No fim de cada planilha a `C5` volta ao valor de antes.
- Destino: `dados/<ano>/PARECERES INFANTIL/<N>º Bimestre/<turma>/<nº chamada> - <nome>.pdf` (a pasta da turma segue o nome do
  `parecer_rco`, como `INFANTIL_4_Integral_A`; ou `AUTO_SERE_PARECERES_INFANTIL_DIR`).
- **Já gerado** é o PDF existir: por padrão é mantido; marque **Substituir** para refazer. **Modo teste** faz só o primeiro
  aluno de cada planilha.
- **QR:** no padrão do sistema (`qr_seguro`, o mesmo dos pareceres do Fundamental: ano, nº da chamada, nome, turma e CGM).
  Esse padrão não leva o bimestre; o bimestre está na pasta do arquivo.
- **Primeira vez:** o Google pede para autorizar o acesso às planilhas **e a leitura do Drive** (necessária para exportar
  PDF); o navegador abre sozinho. O token fica em `credenciais/google_token_drive.json`, separado do token das planilhas.
  As credenciais do Google são as de `docs/GOOGLE_SHEETS.md`. Se der erro 401 ao exportar, apague esse arquivo e rode de novo.
- A conta que autoriza precisa ter acesso às planilhas das professoras (como editora, porque o sistema escreve na `C5`).
- Um aluno que falha (erro ao exportar, sem CGM) vai para a lista de falhas e os outros continuam; erro de permissão para tudo.
- **[não validado]** no Google real: a exportação em PDF e o tempo de recálculo (ajustar `ESPERA_ATUALIZACAO_S` se o
  parecer sair com o aluno anterior).



## Planilha do Infantil e o gerenciador de planilhas
A planilha de pareceres vem pronta da Secretaria e é cadastrada em *Planilhas do Drive* (finalidade `parecer_infantil`, uma por turma). O formulário `parecer_planilha` deixa escolher a planilha cadastrada e a(s) turma(s). Ver `documentacao/Planilhas.md`.

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

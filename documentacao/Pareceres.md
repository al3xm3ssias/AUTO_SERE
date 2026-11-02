# Pareceres

Dois fluxos independentes, mais os pareceres dos transferidos (ver `Transferencias.md`).

## Fundamental — `parecer_fund` (Word + QR)
Pedido de 20/10/2026. O parecer é um **arquivo `.docx` modelo enviado por upload**; o sistema gera uma cópia preenchida por aluno.

- Modelos em `<base>/MODELO/`, com `controle_modelos.json` ligando **turma → arquivo de modelo** (um modelo pode servir a
  várias turmas; reenviar com o mesmo nome substitui). Limite de upload: `LIMITE_MODELO_MB = 15`.
- Saída: `<base>/<ano>/PARECERES/<turma>/<nº da chamada> - <nome>.docx`. A base é `dados/` (ou `AUTO_SERE_PARECERES_BASE`).
- Marcadores no Word: `$ALUNO` (**obrigatório** — sem ele todos sairiam iguais), `$ESCOLA`, `$TURMA`, `$ANO`, `$CGM`, `$CHAMADA`.
- **QR code** 150×150 px no **fim** do arquivo, texto `AUTOSERE|PF|<ano>|<CGM>` (`montar_payload_qr` / `ler_payload_qr`),
  para um script futuro decodificar e enviar às escolas (SERE e e-mail).
- **Nunca sobrescreve** um parecer que já existe (o professor pode ter preenchido), salvo pedido de "substituir".
- Gerenciar modelos: Configurações → modelos de parecer (`/configuracoes/modelos-parecer`).
- **[não validado]** fluxo completo no computador da escola e modelos dos demais anos.

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

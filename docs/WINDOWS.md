# AUTO SERE no Windows

## Instalar (uma vez)
Não precisa ter Python instalado. Precisa de internet na primeira vez e do **Google Chrome**.

1. Extraia o zip **completo** do AUTO SERE em qualquer pasta (ex.: Downloads).
2. Dê dois cliques em `INSTALAR_WINDOWS.bat`. Abre uma janela perguntando **em que pasta instalar**
   (sugestão: `C:\AUTO_SERE`; use **Procurar...** para escolher outra).
3. O assistente então, sem precisar de administrador:
   - copia o programa para a pasta escolhida;
   - instala um **Python próprio** em `<pasta>\runtime\python` (o Python do sistema não é usado nem alterado);
   - instala as bibliotecas do `requirements.txt`;
   - instala os navegadores do Playwright (chromium e firefox) em `<pasta>\runtime\browsers`;
   - cria o atalho **AUTO SERE** (área de trabalho e menu Iniciar) e abre o sistema.
4. Na primeira abertura, o sistema mostra sozinho a tela **1ª execução**. O primeiro passo é
   **Dados da escola**: nome, **CEP** (o botão *Buscar endereço* preenche rua, bairro, cidade e UF),
   número e, se quiser, código, INEP, telefone, e-mail e responsável. Só nome, CEP e endereço são
   obrigatórios. Depois vêm as credenciais do SERE (campo de senha mascarado) e a coleta de turmas e alunos.

Rodar a instalação de novo é seguro: se a pasta já tiver o AUTO SERE, o programa é atualizado e
**dados, credenciais e configurações são preservados**.

Para instalar sem janela: `INSTALAR_WINDOWS.bat -Destino "C:\AUTO_SERE" -Silencioso`.

Observações:
- Escolha um **disco local**. O instalador recusa unidade de rede (SMB), disco removível e
  Arquivos de Programas. Os *dados* podem continuar na rede.
- **Python embutido, sem instalar nada no Windows.** O assistente baixa o *Python portátil* do
  python.org (um zip de ~10 MB, versão 3.12) e extrai em `<pasta>\runtime\python`. Não usa
  instalador, não escreve no registro, não aparece em *Aplicativos instalados* e já traz junto as
  DLLs de runtime do Visual C++. Tendo ou não Python no computador (inclusive quebrado), o resultado
  é o mesmo. Para desinstalar, basta apagar a pasta.
- **Sem internet?** Baixe o "Windows embeddable package (64-bit)" 3.12 em python.org/downloads/windows,
  salve como `<pasta>\runtime\python-embed.zip` e rode de novo (o pip, as bibliotecas e os navegadores
  ainda precisam de internet).

## Usar
- Clique no atalho **AUTO SERE** (ou em `AUTO_SERE.bat`). Ele sobe o servidor se ainda não estiver
  rodando e abre o Chrome em **modo aplicativo** (janela própria, sem abas e sem barra de endereço).
- Clicar duas vezes não cria dois servidores. Cada clique abre uma nova janela do aplicativo.
- Para encerrar o servidor: `PARAR_AUTO_SERE.bat`.
- Dados da escola podem ser alterados depois em **Configurações → Dados da escola**.

## Endereço
Padrão `http://127.0.0.1:8000`. Para mudar, use as variáveis `AUTO_SERE_HOST` / `AUTO_SERE_PORT` ou,
em `config/config_usuario.json`: `{"servidor": {"host": "127.0.0.1", "porta": 8000}}`.
**Mantenha a porta fixa**: o Chrome liga o app instalado à origem (endereço + porta).

## Instalar como PWA (opcional)
O modo aplicativo do atalho já basta. Se quiser o app "instalado" no Chrome: abra
`http://127.0.0.1:8000` numa aba normal e use o ícone de instalar na barra de endereço
(ou menu ⋮ → Transmitir, salvar e compartilhar → Instalar página como app).
O `localhost` é tratado como contexto seguro pelo Chrome, então não precisa de HTTPS.

## Se der problema
- `logs/servidor.log`: saída do servidor. `logs/launcher.log`: o que o launcher fez.
- "Porta em uso": outro programa usa a porta; feche-o ou mude a porta.
- Chrome fora do lugar padrão: defina `AUTO_SERE_CHROME` com o caminho do `chrome.exe`.
  Sem Chrome, usa o Edge (também Chromium); sem nenhum dos dois, abre o navegador padrão.
- Desenvolvimento com auto-reload: `set AUTO_SERE_DEBUG=1` e `python -m src.web.app`.

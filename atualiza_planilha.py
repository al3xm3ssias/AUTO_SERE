"""
=====================================================================
 SCRIPT: atualiza_planilha.py
=====================================================================

OBJETIVO
--------
Script "wrapper" (invólucro) responsável por disparar a sincronização
de dados com o Google Sheets, delegando a execução real para o
submódulo `sheets_sync` (pacote Python localizado em subpasta própria,
relativa a este arquivo). Sua função é puramente orquestradora: prepara
o ambiente de logging, ajusta o `sys.path` para tornar o submódulo
importável e então invoca a função `main()` de `sheets_sync/main.py`,
tratando os possíveis desfechos da execução (sucesso, saída controlada
via SystemExit, ou exceção não tratada).

FLUXO DE EXECUÇÃO
------------------
1. Inicializa o logger próprio do script via `get_logger(__file__)`
   (módulo local `logger.py`), que passa a centralizar a gravação de
   log deste processo.
2. Redireciona o logger raiz (root logger) da biblioteca padrão
   `logging` para usar os mesmos handlers do logger local. Isso é
   necessário porque o submódulo `sheets_sync/main.py` (chamado na
   sequência) provavelmente usa `logging.basicConfig()` ou chamadas
   diretas ao logger raiz — sem esse redirecionamento, os logs
   gerados dentro de `sheets_sync` não apareceriam no arquivo de log
   deste script.
3. Define o nível do logger raiz como DEBUG, garantindo que nenhuma
   mensagem de log (de qualquer nível) seja descartada por filtro de
   severidade.
4. Insere o caminho da subpasta `sheets_sync` (relativa ao diretório
   deste script) no início do `sys.path`, permitindo que o Python
   localize e importe o módulo `main` de dentro dessa subpasta como
   se fosse um módulo de nível superior.
5. Registra no log o início da sincronização.
6. Importa a função `main` do módulo `sheets_sync/main.py` e a
   executa.
7. Trata três cenários possíveis de desfecho:
   a. Execução normal (sem exceção) → loga mensagem de sucesso.
   b. `SystemExit` capturado (o submódulo chamou `sys.exit()` ou
      `exit()`) → verifica o código de saída: se for 0 (ou None),
      loga como encerramento normal; se for diferente de 0, loga como
      erro.
   c. Qualquer outra exceção não tratada → loga a exceção completa
      (com stack trace, via `log.exception`) como erro inesperado.

PRINCIPAIS FUNCIONALIDADES
---------------------------
- Ponte entre o sistema de logging do script principal e o logging
  interno do submódulo `sheets_sync`, unificando toda a saída de log
  em um único arquivo/fluxo.
- Ajuste dinâmico do `sys.path` para permitir a importação de um
  submódulo organizado como pacote separado, sem a necessidade de
  instalá-lo formalmente (ex.: via pip/setup.py) ou de reestruturar
  os imports internos do `sheets_sync`.
- Tratamento diferenciado de saída controlada (`SystemExit`) versus
  falha inesperada (`Exception`), permitindo distinguir no log se o
  submódulo terminou por decisão própria (ex.: validação que decidiu
  abortar) ou por erro real.

ENTRADAS
--------
- Não recebe parâmetros de linha de comando nem argumentos próprios.
- Depende inteiramente da existência e correta configuração do
  submódulo `sheets_sync` (em especial do arquivo
  `sheets_sync/main.py`, que deve expor uma função `main()`).
- Indiretamente, todas as entradas necessárias para a sincronização
  em si (credenciais OAuth do Google, planilha de destino, arquivos
  de dados de origem) são de responsabilidade do submódulo
  `sheets_sync`, não deste script.

SAÍDAS
------
- Não produz arquivos de saída diretamente. Toda a saída de dados
  (ex.: escrita na planilha Google Sheets) é realizada dentro do
  submódulo `sheets_sync`.
- Gera log de execução através do módulo `logger.py` (arquivo de log
  nomeado conforme convenção do projeto, associado a
  "atualiza_planilha").
- Como o logger raiz é redirecionado para os mesmos handlers, todo
  log emitido dentro de `sheets_sync/main.py` (mesmo que use
  `logging.info()`/`logging.error()` diretamente, sem logger próprio)
  também será capturado neste mesmo arquivo de log.

DEPENDÊNCIAS E BIBLIOTECAS
----------------------------
- Python 3 (síncrono).
- logging — biblioteca padrão, usada para o redirecionamento do root
  logger.
- sys, pathlib.Path — bibliotecas padrão, usadas para manipulação do
  `sys.path`.
- Módulo local `logger.py` — deve expor `get_logger(__file__)`.
- Submódulo local `sheets_sync` (pacote/pasta) — deve conter
  `main.py` com uma função `main()` executável sem argumentos
  obrigatórios. Este submódulo, por sua vez, provavelmente depende de
  bibliotecas do Google (google-api-python-client, google-auth,
  google-auth-oauthlib) para acesso ao Google Sheets, conforme
  contexto do projeto (uso de OAuth Desktop App).

ARQUIVOS LIDOS, GRAVADOS OU MODIFICADOS
------------------------------------------
- Este script, isoladamente, não lê nem grava arquivos de dados.
- GRAVA: arquivo(s) de log via `logger.py`.
- Indiretamente, através da execução de `sheets_sync/main.py`: pode
  ler arquivos de credenciais OAuth, tokens salvos em disco, e/ou
  arquivos JSON de dados de alunos/turmas que alimentam a planilha do
  Google Sheets — essas operações estão fora do escopo deste arquivo
  e devem ser documentadas junto ao submódulo `sheets_sync`.

EFEITOS COLATERAIS E OBSERVAÇÕES IMPORTANTES
-----------------------------------------------
- Este script é fortemente acoplado à existência da estrutura de
  pastas `sheets_sync/` no mesmo diretório — se essa pasta for
  renomeada, movida ou o arquivo `main.py` interno for removido, a
  importação falhará com `ImportError`/`ModuleNotFoundError`, sem
  tratamento específico para esse caso (cairá no bloco `except
  Exception`, sendo logado como "erro inesperado").
- A técnica de redirecionar o root logger duplicando handlers pode,
  em cenários onde este script seja executado mais de uma vez no
  mesmo processo Python (o que não é o caso do uso via linha de
  comando/cron, mas pode ser relevante se importado por outro
  script), causar duplicação de handlers e, consequentemente, cada
  mensagem de log sendo escrita múltiplas vezes.
- Não há tratamento de código de saída diferente de "None/0 = sucesso"
  e "outro valor = erro" — não distingue códigos de erro específicos
  que `sheets_sync/main.py` porventura utilize para sinalizar tipos
  distintos de falha.
- Por depender de um `sys.exit()` interno ao submódulo para
  identificar sucesso/erro "controlado", se o submódulo simplesmente
  retornar (sem chamar exit) após uma falha silenciosa, esse script
  não terá como identificar a falha — apenas registrará "Sincronização
  finalizada com sucesso", mesmo que a sincronização tenha,
  na prática, falhado parcialmente.
- Adequado para uso em agendador (cron), pois não requer interação do
  usuário.
"""

import logging
import sys
from pathlib import Path

from logger import get_logger



log = get_logger(__file__)

# ── Redireciona o root logger para os handlers do seu logger ──────────────
# Assim os logs do main.py (que usam basicConfig/root) aparecem no seu log
root = logging.getLogger()
for handler in log.handlers:
    root.addHandler(handler)
root.setLevel(logging.DEBUG)

# ── Adiciona sheets_sync ao path e executa ────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent / "sheets_sync"))

log.info("Iniciando sincronização com Google Sheets...")

try:
    from main import main
    main()
    log.info("Sincronização finalizada com sucesso.")
except SystemExit as e:
    code = e.code or 0
    if code == 0:
        log.info("Script encerrou normalmente (código 0).")
    else:
        log.error("Script encerrou com erro (código %s).", code)
except Exception as e:
    log.exception("Erro inesperado ao executar sheets_sync: %s", e)

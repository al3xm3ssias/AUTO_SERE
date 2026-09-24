"""
prematricula_coleta.py — Etapa 1: Coleta de Intenções de Vaga
=============================================================================
Portado de AUTO_SERE/pre_matricula.py (etapa_coleta, mesclar_turmas_intencao,
carregar_pre_matricula, salvar_pre_matricula) para
src/automacao/prematricula_coleta.py.

Para cada turma disponível na tela de intenções de vaga do portal de
pré-matrícula, coleta a lista de candidatos "aguardando" (posição, nome,
CPF, tipo, pontuação) e mescla o resultado com o pre_matricula.json já
existente, SEM apagar ninguém — ver mesclar_turmas_intencao() para a regra
completa (é a peça mais delicada deste arquivo).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Login, navegação com retry e captura de tela: REMOVIDOS daqui —
   reaproveitam src.comum.prematricula_api (fazer_login, navegar_com_retry,
   capturar_tela), já portada. Nenhuma lógica de navegação foi duplicada.

2. Caminhos: PREMATRICULA_FILE (antes um nome de arquivo relativo,
   "pre_matricula.json", dependente do diretório de execução) agora vem de
   src.comum.paths.dados_ano_atual() — mesma arquitetura dos demais
   scripts já portados.

3. etapa_coleta() RENOMEADA para coletar_intencoes_vaga(page,
   analise_codigo=False) — mesma lógica, só repassando analise_codigo
   adiante para capturar_tela (que agora recebe esse parâmetro
   explicitamente, em vez de ler uma global — ver
   src.comum.prematricula_api).

4. NOVA: executar_prematricula_coleta(analise_codigo=False) — ponto de
   entrada completo (abre navegador, login, coleta, fecha navegador),
   pronto para ser chamado por um futuro botão de GUI (decisão do
   usuário, 03/09/2026, mesmo padrão de src.automacao.sere_2026): sem
   argparse, sem input().

Toda a lógica de negócio (seleção da escola por busca+lista, sinal correto
de que a pesquisa terminou — a tabela de resultado, não o select de
turmas, que já vem populado desde o carregamento inicial da página —,
retry de clique em Pesquisar, extração das 5 colunas por linha, e
sobretudo a regra de merge/presunção de cancelamento em
mesclar_turmas_intencao) é idêntica ao original — nenhuma regra foi
alterada.

Uso:
    import asyncio
    from src.automacao.prematricula_coleta import executar_prematricula_coleta

    asyncio.run(executar_prematricula_coleta())
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from src.comum import paths as _paths
from src.comum.prematricula_api import (
    INTENCOES_URL,
    NOME_ESCOLA_BUSCA,
    NOME_ESCOLA_ALVO,
    capturar_tela,
    fazer_login,
    navegar_com_retry,
)

PREMATRICULA_FILE: Path = _paths.dados_ano_atual() / "pre_matricula.json"

ANO_ATUAL = _paths.ano_atual()


# ==========================================================
# PERSISTÊNCIA
# ==========================================================

def carregar_json(caminho: Path) -> Optional[dict]:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        print(f"Erro: Arquivo JSON inválido - {caminho}")
        return None


def carregar_pre_matricula() -> dict:
    """
    Carrega o pre_matricula.json existente, se houver, para permitir merge
    incremental entre as etapas: a Etapa 1 (turmas_intencao) e a Etapa 2
    (cadastros por CPF) escrevem no mesmo arquivo sem uma apagar os dados
    da outra.
    """
    if not PREMATRICULA_FILE.exists():
        return {"atualizado_em": None, "turmas_intencao": {}, "cadastros": {}}

    dados = carregar_json(PREMATRICULA_FILE)
    if dados is None:
        return {"atualizado_em": None, "turmas_intencao": {}, "cadastros": {}}

    dados.setdefault("turmas_intencao", {})
    dados.setdefault("cadastros", {})
    return dados


def salvar_pre_matricula(dados: dict) -> None:
    """Persiste o pre_matricula.json unificado, atualizando o timestamp."""
    dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    PREMATRICULA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PREMATRICULA_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def mesclar_turmas_intencao(turmas_antigas: dict, turmas_novas: dict) -> dict:
    """
    Mescla o resultado recém-coletado com o que já existia no
    pre_matricula.json, SEM apagar ninguém.

    pre_matricula.json é o guia histórico de todos os alunos que já
    passaram pela intenção de vaga (aguardando, matriculados ou
    cancelados). O site só mostra quem está "aguardando" no momento da
    consulta — então, se um aluno some da lista (foi matriculado ou
    cancelado), ele NÃO pode simplesmente desaparecer do arquivo.

    Regra:
      - Cada aluno é identificado por CPF (ou tr_id, se o CPF vier vazio).
      - Se o aluno já existe no arquivo (mesma turma + mesmo CPF/tr_id):
        os dados são atualizados com segurança (sobrescreve pos, nome,
        tipo, pontuação com o valor mais recente do site).
      - Se o aluno é novo: é adicionado à lista da turma.
      - Se o aluno estava no arquivo antigo mas não veio na coleta atual
        (não está mais "aguardando" nessa turma): ele é MANTIDO como
        está, marcado com "presente_na_ultima_coleta": False, para
        indicar que provavelmente foi matriculado ou cancelado, sem
        perder o registro dele.
      - Turmas que existiam no arquivo antigo mas não vieram na coleta
        atual (ex: filtro diferente, erro pontual) também são mantidas
        intactas.

    IMPORTANTE — sobre o "sumiço" do aluno da lista de intenções:
    Quando um aluno deixa de aparecer na tela de intenção de vaga, o
    site não diz o motivo: pode ter sido matriculado ou cancelado. A
    situação real e definitiva (Matriculado/Cancelado + motivo) só é
    capturada de fato pela Etapa 2 (consulta por CPF, campo
    escolas_escolhidas.opcoes[].situacao / motivo_cancelamento), e essa
    etapa só roda para CPFs que ainda estavam "aguardando" na Etapa 1
    da mesma execução. Ou seja: assim que o aluno some da lista, ele
    também para de ser re-consultado, e o motivo real nunca é
    capturado automaticamente depois disso.

    Para não deixar esse registro "órfão" sem nenhuma indicação do que
    aconteceu, na PRIMEIRA vez em que um aluno é detectado como ausente
    (presente_na_ultima_coleta passando de True/inexistente para False)
    este script grava, apenas no registro de turmas_intencao:
        situacao: "Cancelado"
        motivo_cancelamento: "CANCELADO VIA SISTEMA/RESPONSAVEL"
    Isso é uma PRESUNÇÃO automática, não uma confirmação — o sistema não
    informa o motivo real do sumiço; é só um valor convencionado para não
    deixar o campo em branco. Se o CPF desse aluno voltar a ser
    consultado depois (ex: via --completar_json / prematricula_planilhas)
    e a Etapa 2 capturar a situação real em cadastros[cpf], aquele dado
    tem prioridade e deve ser considerado a fonte da verdade — o valor
    presuntivo aqui em turmas_intencao NÃO é sobrescrito automaticamente
    por este merge (ele mexe só na lista de intenção), mas também não
    deve ser tratado como confirmação oficial de cancelamento em nenhum
    relatório.
    """

    def chave_aluno(aluno: dict) -> str:
        cpf = (aluno.get("cpf") or "").strip()
        if cpf:
            return cpf
        return (aluno.get("tr_id") or aluno.get("nome") or "").strip()

    turmas_mescladas: dict = {}

    # Começa com todas as turmas que já existiam (preserva o que não vier
    # na coleta atual).
    for turma, alunos_antigos in (turmas_antigas or {}).items():
        turmas_mescladas[turma] = {chave_aluno(a): dict(a) for a in alunos_antigos if chave_aluno(a)}

    # Aplica a coleta atual por cima, turma por turma.
    for turma, alunos_novos in (turmas_novas or {}).items():
        existentes = turmas_mescladas.setdefault(turma, {})
        chaves_vistas_agora = set()

        for aluno_novo in alunos_novos:
            chave = chave_aluno(aluno_novo)
            if not chave:
                continue
            chaves_vistas_agora.add(chave)

            aluno_atualizado = dict(aluno_novo)
            aluno_atualizado["presente_na_ultima_coleta"] = True
            existentes[chave] = aluno_atualizado

        # Quem estava na turma antes e não apareceu nesta coleta:
        # mantém o registro, só marca que não está mais "aguardando".
        for chave, aluno_antigo in existentes.items():
            if chave not in chaves_vistas_agora:
                estava_presente_antes = aluno_antigo.get("presente_na_ultima_coleta", True)
                aluno_antigo["presente_na_ultima_coleta"] = False

                # Só grava a situação presuntiva na PRIMEIRA vez que o
                # aluno é detectado como ausente, e só se ainda não
                # houver nenhuma situação registrada (ex: vinda da
                # Etapa 2 antes de sumir). Isso evita sobrescrever um
                # dado real já capturado.
                if estava_presente_antes and not aluno_antigo.get("situacao"):
                    aluno_antigo["situacao"] = "Cancelado"
                    aluno_antigo["motivo_cancelamento"] = "CANCELADO VIA SISTEMA/RESPONSAVEL"

    # Converte de volta para listas (formato original do JSON).
    resultado = {
        turma: list(alunos_por_chave.values())
        for turma, alunos_por_chave in turmas_mescladas.items()
    }
    return resultado


# ==========================================================
# ETAPA 1 - COLETA
# ==========================================================

async def coletar_intencoes_vaga(page, analise_codigo: bool = False) -> Optional[dict]:
    """
    Executa a Etapa 1: seleciona a escola, percorre cada turma disponível
    na tela de intenções de vaga, coleta os candidatos "aguardando" e
    mescla o resultado com o pre_matricula.json existente (via
    mesclar_turmas_intencao — nunca apaga registros antigos).

    Assume que `page` já está autenticada no portal de pré-matrícula —
    quem só quer disparar a coleta completa (login + coleta) deve chamar
    executar_prematricula_coleta() em vez desta função diretamente.

    Retorna o dict {"meta": {...}, "turmas": {...}} recém-coletado (antes
    do merge) em caso de sucesso, ou None em caso de falha irrecuperável.
    """
    print("\n" + "=" * 60)
    print(f"ETAPA 1/4 - COLETA DE INTENÇÕES DE VAGA ({ANO_ATUAL})")
    print("=" * 60)

    if not await navegar_com_retry(page, INTENCOES_URL, pausa_antes=1.0):
        await capturar_tela(page, "coleta", "falha ao abrir tela de intencoes", erro=True)
        return None
    await capturar_tela(page, "coleta", "tela de intencoes de vaga", analise_codigo=analise_codigo)

    # Selecionar a escola
    try:
        await page.wait_for_selector("input#nomeEscola", timeout=7000)
        await page.click("input#nomeEscola")
        await page.type("input#nomeEscola", NOME_ESCOLA_BUSCA, delay=200)

        try:
            await page.wait_for_selector("#listaEscolas a", timeout=7000)
            await capturar_tela(page, "coleta", "lista de escolas", analise_codigo=analise_codigo)
            escolas = page.locator("#listaEscolas a")
            count = await escolas.count()
            encontrou = False

            for i in range(count):
                h5 = escolas.nth(i).locator("h5")
                try:
                    texto = await h5.inner_text()
                    if NOME_ESCOLA_ALVO in texto:
                        await escolas.nth(i).click()
                        print(f"Escola selecionada: {texto}")
                        encontrou = True
                        break
                except Exception:
                    continue

            if not encontrou:
                print(f"Escola '{NOME_ESCOLA_ALVO}' não encontrada na lista.")
                await capturar_tela(page, "coleta", "escola nao encontrada na lista", erro=True)

        except PWTimeout:
            print("Não encontrei a lista de escolas.")
            await capturar_tela(page, "coleta", "timeout lista de escolas", erro=True)

    except PWTimeout:
        print("Campo nomeEscola não encontrado.")
        await capturar_tela(page, "coleta", "timeout campo nomeEscola", erro=True)
        return None

    # Pesquisar
    #
    # IMPORTANTE: select#sTurma já vem populado com as 7 turmas desde o
    # carregamento inicial da página (confirmado por screenshot — a option
    # "Infantil IV" já aparece selecionada ANTES de clicar em Pesquisar).
    # Ou seja, esperar por 'select#sTurma option:not([value=""])' nunca é
    # um sinal confiável de que a pesquisa terminou: o elemento já existe
    # e é visível mesmo sem nenhuma busca ter sido feita, e por isso esse
    # wait_for_selector ficava estourando timeout à toa.
    #
    # O sinal real de que a pesquisa terminou é o bloco de resultado
    # "Intenções de Vaga:" (div#divIntencoes / a tabela #tableIntencoes)
    # aparecer na página.
    try:
        botao_pesquisar = page.locator("#bPesquisar")
        await botao_pesquisar.wait_for(state="visible", timeout=10000)

        # Espera o botão não estar desabilitado (alguns sites só habilitam
        # o botão de pesquisa depois que a escola é confirmada via JS).
        for _ in range(20):
            se_desabilitado = await botao_pesquisar.is_disabled()
            if not se_desabilitado:
                break
            await asyncio.sleep(0.5)

        await botao_pesquisar.click()

        # Aguarda a rede assentar (a pesquisa dispara uma chamada AJAX que
        # popula a seção de resultados) antes de checar o resultado.
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass

        # Espera o bloco de resultado da pesquisa aparecer, não o select
        # de turmas (que já estava lá desde o início). A tabela
        # #tableIntencoes é renderizada sempre que a pesquisa é concluída,
        # com ou sem linhas de dados.
        await page.wait_for_selector("#tableIntencoes", timeout=15000)
        await capturar_tela(page, "coleta", "resultado pesquisa escola", analise_codigo=analise_codigo)
    except Exception as e:
        print(f"Falha ao clicar em Pesquisar: {e}")
        await capturar_tela(page, "coleta", "falha ao clicar em pesquisar", erro=True)

        # Tentativa de recuperação: às vezes o primeiro clique acontece
        # cedo demais (botão ainda não reagiu à seleção da escola). Um
        # segundo clique, após uma pequena pausa, costuma resolver.
        try:
            await asyncio.sleep(1.5)
            await page.click("#bPesquisar")
            await page.wait_for_selector("#tableIntencoes", timeout=10000)
            print("✓ Recuperado após novo clique em Pesquisar.")
            await capturar_tela(page, "coleta", "resultado pesquisa escola apos retry", analise_codigo=analise_codigo)
        except Exception as e2:
            # Não trava o fluxo: mesmo sem confirmar visualmente o bloco
            # de resultado, o select de turmas já está disponível (ele
            # nunca dependeu da pesquisa) e o loop abaixo consegue seguir
            # turma por turma normalmente.
            print(f"Aviso: não foi possível confirmar o bloco de resultado após pesquisar: {e2}")
            print("Prosseguindo mesmo assim, pois o select de turmas já está disponível.")

    # Coletar turmas disponíveis
    try:
        await page.wait_for_selector("select#sTurma", timeout=7000)
    except PWTimeout:
        print("Select de turmas não encontrado.")
        await capturar_tela(page, "coleta", "timeout select de turmas", erro=True)
        return None

    options = await page.eval_on_selector_all(
        "select#sTurma option",
        "opts => opts.map(o => ({value: o.value, label: o.textContent.trim()}))",
    )

    resultado = {
        "meta": {
            "url": INTENCOES_URL,
            "coletado_em": datetime.now().isoformat(),
        },
        "turmas": {},
    }

    for opt in options:
        val = opt["value"]
        label = opt["label"]

        if not val or val.isspace():
            continue

        print(f"\nProcessando turma: {label} (value={val})")

        try:
            await page.select_option("select#sTurma", val)
            await asyncio.sleep(2.5)
            await page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Falha ao selecionar turma {label}: {e}")
            await capturar_tela(page, "coleta", f"falha ao selecionar turma {label}", erro=True)
            continue

        try:
            await page.click("#bPesquisar")
            await asyncio.sleep(1.5)
            await page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Falha ao clicar em pesquisar para {label}: {e}")
            await capturar_tela(page, "coleta", f"falha ao pesquisar turma {label}", erro=True)

        try:
            await page.wait_for_selector("table#tableIntencoes tbody tr", timeout=5000)
            await capturar_tela(page, "coleta", f"turma {label}", analise_codigo=analise_codigo)
        except PWTimeout:
            print(f"Nenhum registro na turma '{label}'.")
            await capturar_tela(page, "coleta", f"sem registros turma {label}", analise_codigo=analise_codigo)
            resultado["turmas"][label] = []
            continue

        try:
            rows = await page.query_selector_all("table#tableIntencoes tbody tr")
            turma_lista = []

            for row in rows:
                tds = await row.query_selector_all("td")

                async def text_of(td_idx):
                    try:
                        if td_idx < len(tds):
                            return (await tds[td_idx].inner_text()).strip()
                        return ""
                    except Exception:
                        return ""

                registro = {
                    "pos": await text_of(0),
                    "nome": await text_of(1),
                    "cpf": await text_of(2),
                    "tipo": await text_of(3),
                    "pontuacao": await text_of(4),
                    "tr_id": await row.get_attribute("id"),
                }
                turma_lista.append(registro)

            resultado["turmas"][label] = turma_lista
            print(f"✓ Coletados {len(turma_lista)} registros da turma '{label}'.")

        except Exception as e:
            print(f"Erro ao processar linhas da turma '{label}': {e}")
            await capturar_tela(page, "coleta", f"erro processando turma {label}", erro=True)
            resultado["turmas"][label] = []

    try:
        pre_matricula = carregar_pre_matricula()
        pre_matricula["turmas_intencao"] = mesclar_turmas_intencao(
            pre_matricula.get("turmas_intencao", {}), resultado["turmas"]
        )
        salvar_pre_matricula(pre_matricula)
        print(f"\n✅ Etapa 1 concluída. Resultado salvo em: {PREMATRICULA_FILE}")
    except Exception as e:
        print(f"Erro ao salvar arquivo da etapa 1: {e}")
        return None

    return resultado


# ==========================================================
# ENTRY POINT (pronto para uma futura GUI)
# ==========================================================

async def executar_prematricula_coleta(analise_codigo: bool = False) -> Optional[dict]:
    """
    Ponto de entrada completo: abre o navegador, faz login no portal de
    pré-matrícula, executa a Etapa 1 (coleta de intenções de vaga) e fecha
    o navegador.

    Pronta para ser chamada por um futuro botão de GUI (decisão do
    usuário, 03/09/2026, mesmo padrão de src.automacao.sere_2026): sem
    argparse, sem input(). Para rodar em background com progresso via
    callback, envolva esta função com
    src.comum.execucao_gui.ExecucaoEmBackground, como já feito para os
    modos de sere_2026.py.

    Retorna o resultado recém-coletado ({"meta": ..., "turmas": ...}), ou
    None se o login ou a coleta falharem.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        if not await fazer_login(page, analise_codigo=analise_codigo):
            print("❌ Falha no login. Encerrando.")
            await browser.close()
            return None

        resultado = await coletar_intencoes_vaga(page, analise_codigo=analise_codigo)

        await browser.close()
        return resultado


if __name__ == "__main__":
    asyncio.run(executar_prematricula_coleta())

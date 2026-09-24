"""
rematricula_sere.py — Operações na página do SERE
=============================================================================
Portado de AUTO_SERE/rematricula.py (fazer_login_sere,
navegar_para_por_turmas, listar_secao_turmas, selecionar_turma,
obter_alunos_matriculados, gerar_chave_acesso, obter_cpf_responsavel) para
src/automacao/rematricula_sere.py.

Funções que operam exclusivamente na página do SERE (não confundir com
src.automacao.rematricula_area_aluno, que opera no site do Estado —
areadoaluno.seed.pr.gov.br): selecionar a turma, listar os alunos
matriculados, e — para cada aluno — gerar a chave de acesso temporária e
obter o CPF do responsável, que juntos permitem fazer login na Área do
Aluno (ver src.automacao.rematricula_area_aluno.fazer_login_area_aluno).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. navegar_para_por_turmas() REMOVIDA — comparada com
   src.comum.sere_api.navegar_por_turma (já portada) e confirmada
   funcionalmente idêntica (mesmo seletor #divoCMenu0_0, mesmo
   MouseEvent, mesma sequência de cliques Consulta Padrão → Por Turma).
   Decisão do usuário (04/09/2026): reaproveitada diretamente.

2. fazer_login_sere() REMOVIDA — reaproveita
   src.comum.sere_api (URL) + src.comum.credenciais (LOGIN, SENHA)
   diretamente na função de orquestração
   (src.automacao.rematricula.executar_rematricula), no mesmo padrão de
   login usado pelos outros scripts SERE já portados.

Toda a lógica de negócio (extração de seção/turma a partir dos
argumentos do href AoClicarTurma, os 3 níveis de correspondência de nome
de turma — exata, parcial, debug —, extração de dados do aluno via
page.evaluate() percorrendo as linhas da tabela, geração de chave de
acesso via clique + retry de 5 tentativas lendo o input #chaveAcesso —
levantando ErroReiniciarNavegador se não aparecer —, e extração de CPF
do responsável via busca direta no DOM por texto + regex) é idêntica ao
original — nenhuma regra foi alterada.

Uso:
    from src.automacao.rematricula_sere import selecionar_turma, obter_alunos_matriculados

    ok = await selecionar_turma(page_sere, "3º Ano - A")
    alunos = await obter_alunos_matriculados(page_sere)
"""

from __future__ import annotations

import re

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.automacao.rematricula_persistencia import normalize_text, ErroReiniciarNavegador


async def listar_secao_turmas(page, nome_turma: str) -> list[str]:
    """
    Retorna lista de labels das seções encontradas relacionadas a nome_turma.
    Busca tanto no texto do link quanto nos argumentos do href javascript (AoClicarTurma),
    porque em alguns casos o texto do <a> é apenas "B" enquanto o href contém "2º Ano".
    A label retornada será no formato: "<turma_arg> - <letra_secao>" se possível
    (ex.: "2º Ano - B"), ou o texto do link se não for possível extrair.
    """
    try:
        await page.wait_for_selector("a[href*='AoClicarTurma']", timeout=8000)
        raw = await page.evaluate(
            """() => {
                const links = Array.from(document.querySelectorAll("a[href*='AoClicarTurma']"));
                return links.map(l => ({
                    text: (l && l.textContent) ? l.textContent.trim().replace(/\\s+/g,' ') : '',
                    href: l.getAttribute('href') || ''
                }));
            }"""
        )

        alvo_norm = normalize_text(nome_turma)
        secoes = []
        seen = set()

        for item in raw:
            texto = item.get("text", "")
            href = item.get("href", "")

            # extrair argumentos da chamada AoClicarTurma('...','...','...','...','...','B ','2º Ano',...)
            args = re.findall(r"'([^']*)'", href) if href else []
            letra_secao = args[5].strip() if len(args) > 5 else ""
            turma_arg = args[6].strip() if len(args) > 6 else ""

            # construir label preferencial: "2º Ano - B"
            if turma_arg:
                label = f"{turma_arg} - {letra_secao}" if letra_secao else turma_arg
            else:
                label = texto or href

            # verificar se corresponde ao alvo (no texto do link OU no argumento da href)
            if alvo_norm in normalize_text(texto) or alvo_norm in normalize_text(turma_arg):
                if label not in seen:
                    secoes.append(label)
                    seen.add(label)

        return secoes
    except Exception as e:
        print(f"❌ Erro ao listar seções da turma '{nome_turma}': {e}")
        return []


async def selecionar_turma(page, nome_turma: str) -> bool:
    """
    Seleciona a turma verificando:
    - correspondência exata normalizada com o texto do link
    - correspondência com o label construído a partir dos argumentos da href (p.ex. "2º Ano - B")
    - correspondência parcial normalizada
    Se não encontrar, imprime debug com todos os links (texto + argumentos).
    """
    try:
        print(f"📚 Selecionando turma: {nome_turma}...")
        await page.wait_for_selector("a[href*='AoClicarTurma']", timeout=20000)
        await page.wait_for_timeout(300)

        links_turmas = await page.query_selector_all("a[href*='AoClicarTurma']")

        alvo_norm = normalize_text(nome_turma)

        # Função auxiliar para extrair label (igual ao listar_secao_turmas)
        async def link_label(link):
            texto = (await link.inner_text()).strip()
            href = await link.get_attribute("href") or ""
            args = re.findall(r"'([^']*)'", href) if href else []
            letra = args[5].strip() if len(args) > 5 else ""
            turma_arg = args[6].strip() if len(args) > 6 else ""
            if turma_arg:
                return texto, turma_arg, f"{turma_arg} - {letra}" if letra else turma_arg, href
            return texto, "", texto or href, href

        # 1) tentar correspondência exata com label (turma_arg - letra) ou texto do link
        for link in links_turmas:
            texto, turma_arg, label, href = await link_label(link)
            if normalize_text(texto) == alvo_norm or normalize_text(label) == alvo_norm:
                await link.click()
                await page.wait_for_timeout(2000)
                print(f"✅ Turma '{nome_turma}' selecionada (correspondência exata)!")
                return True

        # 2) tentar correspondência parcial (contém)
        for link in links_turmas:
            texto, turma_arg, label, href = await link_label(link)
            if alvo_norm in normalize_text(texto) or (turma_arg and alvo_norm in normalize_text(turma_arg)) or alvo_norm in normalize_text(label):
                await link.click()
                await page.wait_for_timeout(2000)
                print(f"✅ Turma '{nome_turma}' selecionada (correspondência parcial)!")
                return True

        # 3) debug: listar todos os links (texto, label, normalized)
        disponiveis = []
        for link in links_turmas:
            texto, turma_arg, label, href = await link_label(link)
            disponiveis.append((texto, turma_arg, label, href))

        print("⚠️ Não encontrou a turma desejada. Links de turma disponíveis (texto | turma_arg | label):")
        for texto, turma_arg, label, href in disponiveis:
            print(f"  - texto: {texto!r} | turma_arg: {turma_arg!r} | label: {label!r} | normalized: {normalize_text(label)!r}")

        print(f"❌ Turma '{nome_turma}' não encontrada")
        return False

    except Exception as e:
        print(f"❌ Erro ao selecionar turma: {e}")
        return False


async def obter_alunos_matriculados(page) -> list[dict]:
    try:
        print("👥 Obtendo alunos matriculados...")
        await page.wait_for_selector("a[href*='AoClicarAluno']", timeout=20000)
        await page.wait_for_timeout(1000)

        alunos = await page.evaluate("""
            () => {
                const linhas = Array.from(document.querySelectorAll('table tr'));
                const alunos = [];

                linhas.forEach((linha, idx) => {
                    if (idx === 0) return;

                    const colunas = linha.querySelectorAll('td');
                    if (colunas.length < 8) return;

                    const situacao = colunas[6].textContent.trim();

                    if (situacao === 'Matriculado') {
                        // Normaliza espaços em branco no nome (substitui múltiplos espaços por um único)
                        const nomeRaw = colunas[2].textContent || '';
                        const nome = nomeRaw.replace(/\\s+/g, ' ').trim();

                        alunos.push({
                            n: colunas[0].textContent.trim(),
                            cgm: colunas[1].textContent.trim(),
                            Nome: nome,
                            'Data Nasc.': colunas[3].textContent.trim(),
                            Idade: colunas[4].textContent.trim(),
                            Sexo: colunas[5].textContent.trim(),
                            'Situação': situacao,
                            'Data Matricula': colunas[7].textContent.trim()
                        });
                    }
                });

                return alunos;
            }
        """)

        print(f"✅ {len(alunos)} alunos matriculados encontrados")
        return alunos

    except Exception as e:
        print(f"❌ Erro ao obter alunos: {e}")
        return []


async def gerar_chave_acesso(page) -> str:
    """
    Clica no botão de gerar chave de acesso na ficha do aluno (SERE) e
    captura o valor exibido no input #chaveAcesso, com retry (a chave
    pode levar alguns segundos para ser gerada pelo backend do SERE) —
    essa chave, junto com o CPF do responsável (ver
    obter_cpf_responsavel), é usada para autenticar na Área do Aluno (ver
    src.automacao.rematricula_area_aluno.fazer_login_area_aluno).

    Levanta ErroReiniciarNavegador (ver
    src.automacao.rematricula_persistencia) se o botão não responder ou
    a chave não aparecer após as tentativas — sinal de que a única
    recuperação confiável é reiniciar a página do aluno, não só
    re-tentar o clique.
    """
    try:
        print("🔑 Gerando chave de acesso...")

        await page.click("//button[contains(., 'Gerar Chave')]", timeout=5000)

        for tentativa in range(5):
            await page.wait_for_timeout(1500)
            chave = await page.input_value("#chaveAcesso")

            if chave:
                print(f"✅ Chave gerada: {chave}")
                return chave

        print("❌ Timeout ao gerar chave")
        raise ErroReiniciarNavegador("Não foi possível gerar chave após múltiplas tentativas")

    except PlaywrightTimeoutError as e:
        print(f"❌ Erro ao gerar chave: Timeout ao clicar no botão")
        raise ErroReiniciarNavegador(f"Timeout ao tentar gerar chave: {e}")
    except ErroReiniciarNavegador:
        raise
    except Exception as e:
        print(f"❌ Erro ao gerar chave: {e}")
        raise ErroReiniciarNavegador(f"Erro ao gerar chave: {e}")


async def obter_cpf_responsavel(page) -> str | None:
    """
    Extrai o CPF do responsável exibido na ficha do aluno (SERE), via
    busca direta no DOM (não XPath) pelo texto "CPF do Responsável"
    seguido de 11+ dígitos.
    """
    try:
        cpf = await page.evaluate("""
            () => {
                const tds = Array.from(document.querySelectorAll('td.texto_normal'));

                for (let td of tds) {
                    if (td.textContent.includes('CPF do Responsável')) {
                        const texto = td.textContent;
                        const cpfText = texto.replace('CPF do Responsável :', '').trim();
                        const match = cpfText.match(/(\\d{11,})/);
                        if (match) return match[1];
                    }
                }

                return null;
            }
        """)

        if cpf:
            print(f"👤 CPF Responsável: {cpf}")
            return cpf
        else:
            print("⚠️ CPF do responsável não encontrado")
            return None

    except Exception as e:
        print(f"❌ Erro ao obter CPF: {e}")
        return None

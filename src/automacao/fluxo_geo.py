"""
fluxo_geo.py — "Direcionados GEO": alunos direcionados por fluxo/geo no SERE
===========================================================================
Menu > Estrutura e Funcionamento > Planejamento Escolar > Criar planejamento de turma, período
"<próximo ano>-1" (ex.: 2027-1). Salva em dados/<ano em uso>/sere_sisgea_<próximo ano>.json
(ex.: dados/2026/sere_sisgea_2027.json).

A tela tem um modal por etapa (Infantil 0-3, Infantil 4-6, 1º Ano...), aberto por links
listarFluxo(2, <etapa>). O script abre cada modal visível, lê a tabela, confere com o "Total:N" do link e
fecha com ESC.

Diferente da rematrícula, isso NÃO é certeza de matrícula: o responsável pode desistir. Por isso o JSON
preserva o histórico: quem sumiu da lista fica marcado como "ausente" (com a data), em vez de ser apagado.
Só LÊ o SERE; nada é alterado lá.

Quem usa o resultado: tela "Previsão <ano>" (turma, aluno, CGM, responsável) e tela "Pré matrícula" →
"Direcionados GEO" (todos os dados, principalmente o telefone do responsável). Leitura em
src/comum/direcionados_geo.py.

Ponto de entrada: `fluxo_geo_via_login()` (sem argparse/input()). `coletar_fluxo_geo(page)` recebe uma página
já logada no SERE.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.comum import navegador as _navegador
from src.comum import paths
from src.comum.arquivos_json import carregar_json, salvar_json_atomico

PREFIXO_ARQUIVO = "sere_sisgea_"


def nome_arquivo(ano_letivo) -> str:
    """``sere_sisgea_2027.json`` para o ano letivo 2027 (o ano para onde os alunos foram direcionados)."""
    return f"{PREFIXO_ARQUIVO}{int(ano_letivo)}.json"


SEL_PERIODO = "#codPeriodoLetivoPlanejadoId"
SEL_MODAL = "#janela_direcionados_fluxo_geo"
SEL_LINHAS = f"{SEL_MODAL} #list_tabela tr[id='tr_data']"

# ---------------------------------------------------------------- JS no navegador
JS_LER_TABELA = """
() => {
  const limpa = s => (s || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
  const linhas = [...document.querySelectorAll(
      '#janela_direcionados_fluxo_geo #list_tabela tr[id="tr_data"]')];
  return linhas.map(tr => {
    const td = tr.querySelectorAll(':scope > td');
    if (td.length < 7) return null;
    const partes = td[3].innerText.split('\\n').map(limpa).filter(Boolean);
    let resp = '', fone = '';
    for (const p of partes.slice(1)) {
      if (/^Nome respons/i.test(p)) resp = limpa(p.split(':').slice(1).join(':'));
      else if (/^Fone respons/i.test(p)) fone = limpa(p.split(':').slice(1).join(':'));
    }
    const sel = td[5].querySelector('select');
    const opt = sel && sel.selectedOptions[0];
    const turma = opt ? limpa(opt.textContent) : '';
    const btn = td[4].querySelector('input');
    const docs = [...td[6].querySelectorAll('input[type=checkbox]')]
      .filter(c => c.checked)
      .map(c => limpa(c.nextSibling ? c.nextSibling.textContent : c.value));
    return {
      municipio_origem: limpa(td[0].innerText),
      estabelecimento_origem: limpa(td[1].innerText),
      cgm: limpa(td[2].innerText),
      nome: partes[0] || '',
      nome_responsavel: resp,
      fone_responsavel: fone,
      matricula_texto: btn ? limpa(btn.value) : '',
      turma: /não há turmas/i.test(turma) ? null : turma,
      documentos_pendentes: docs,
    };
  }).filter(Boolean);
}
"""

# links de etapa VISÍVEIS (os de 6º ano / 1ª série EM vêm com display:none)
JS_LISTAR_ETAPAS = """
() => [...document.querySelectorAll('a[href^="javascript:listarFluxo("]')]
  .filter(a => a.offsetParent !== null)
  .map(a => {
    const m = a.getAttribute('href').match(/listarFluxo\\(\\d+,\\s*(\\d+)\\)/);
    const bloco = a.closest('div[name^="div_qtd"]');
    const rotulo = bloco ? bloco.childNodes[0].textContent : '';
    return {
      cod: m ? m[1] : null,
      etapa: rotulo.replace(/\\u00a0/g, ' ').replace(/Quantidade de alunos direcionados( para (o|a))?/i, '')
                   .replace(':', '').replace(/\\s+/g, ' ').trim(),
      texto: a.textContent.trim(),
    };
  }).filter(e => e.cod)
"""


# ---------------------------------------------------------------- navegação
async def _abrir_criar_planejamento(page):
    await page.get_by_text("Estrutura e Funcionamento", exact=True).first.hover()
    await page.wait_for_timeout(800)
    await page.get_by_text("Planejamento Escolar", exact=True).first.hover()
    await page.wait_for_timeout(500)
    await page.get_by_text("Criar planejamento de turma", exact=True).first.click()
    await page.wait_for_selector(SEL_PERIODO, timeout=30000)
    await page.wait_for_load_state("networkidle")


async def _selecionar_periodo(page, periodo):
    sel = page.locator(SEL_PERIODO)
    opcoes = await sel.evaluate(
        "s => [...s.options].map(o => [o.value, o.textContent.trim()])")
    valor = next((v for v, t in opcoes if t == periodo), None)
    if valor is None:
        raise RuntimeError(f"Período '{periodo}' não existe no select (opções: {opcoes}).")
    if await sel.input_value() != valor:
        await sel.select_option(value=valor)       # dispara onchange
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1000)              # contadores recarregam por ajax


async def _fechar_modal(page):
    modal = page.locator(SEL_MODAL)
    await page.keyboard.press("Escape")
    try:
        await modal.wait_for(state="hidden", timeout=2000)
    except Exception:
        # ESC não fechou: usa a própria função da página
        await page.evaluate("typeof fechar_lista_fluxo === 'function' && fechar_lista_fluxo()")
        await modal.wait_for(state="hidden", timeout=5000)


def _total_do_link(texto):
    m = re.search(r"Total:\s*(\d+)", texto)
    return int(m.group(1)) if m else None


async def _coletar_modal(page, cod, esperado):
    await page.locator(f"a[href*='listarFluxo(2,{cod})']").first.click()
    await page.locator(SEL_MODAL).wait_for(state="visible", timeout=15000)
    linhas = []
    for _ in range(3):                              # 2ª leitura se vier incompleto
        try:
            await page.wait_for_selector(SEL_LINHAS, timeout=8000 if esperado else 1500)
        except Exception:
            pass
        await page.wait_for_timeout(700)
        linhas = await page.evaluate(JS_LER_TABELA)
        if esperado is None or len(linhas) == esperado:
            break
    await _fechar_modal(page)
    return linhas


# ---------------------------------------------------------------- respostas JSON
def _achar_registros(obj, saida):
    if isinstance(obj, dict):
        if "cgmaluno" in obj:
            saida.append(obj)
        else:
            for v in obj.values():
                _achar_registros(v, saida)
    elif isinstance(obj, list):
        for v in obj:
            _achar_registros(v, saida)


# ---------------------------------------------------------------- salvar com histórico
def _mesclar(anterior, novos, agora, marcar_ausentes):
    por_cgm = {a["cgm"]: a for a in anterior}
    vistos = set()
    for n in novos:
        vistos.add(n["cgm"])
        antigo = por_cgm.get(n["cgm"], {})
        n["primeira_vez_visto"] = antigo.get("primeira_vez_visto", agora)
        n["ultima_vez_visto"] = agora
        n["situacao_lista"] = "presente"
        por_cgm[n["cgm"]] = n
    if marcar_ausentes:
        for cgm, a in por_cgm.items():
            if cgm not in vistos and a.get("situacao_lista") != "ausente":
                a["situacao_lista"] = "ausente"     # sumiu da lista: possível desistência
                a["ausente_desde"] = agora
    return list(por_cgm.values())


# ---------------------------------------------------------------- principal
async def coletar_fluxo_geo(page, ano_letivo=None, pasta_saida=None, sufixo_periodo="1",
                            log: Callable[[str], None] = print):
    ano_letivo = int(ano_letivo or int(paths.ano_atual()) + 1)
    periodo = f"{ano_letivo}-{sufixo_periodo}"
    pasta = Path(pasta_saida or paths.dados_ano_atual())
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / nome_arquivo(ano_letivo)

    json_por_cgm = {}

    async def _ler_resposta(resp):
        try:
            regs = []
            _achar_registros(await resp.json(), regs)
            for r in regs:
                json_por_cgm[str(r.get("cgmaluno"))] = r
        except Exception:
            pass

    page.on("response", lambda r: asyncio.ensure_future(_ler_resposta(r)))

    await _abrir_criar_planejamento(page)
    await _selecionar_periodo(page, periodo)

    etapas = await page.evaluate(JS_LISTAR_ETAPAS)
    log(f"{len(etapas)} etapa(s) visível(is): " + "; ".join(f"{e['etapa']} [{e['texto']}]" for e in etapas))

    todos, completo = {}, True
    for e in etapas:
        esperado = _total_do_link(e["texto"])
        if esperado == 0:
            log(f"  {e['etapa']}: 0 aluno(s), pulando")
            continue
        linhas = await _coletar_modal(page, e["cod"], esperado)
        ok = esperado is None or len(linhas) == esperado
        completo = completo and ok
        log(f"  {e['etapa']}: {len(linhas)}/{esperado} {'OK' if ok else 'DIVERGENTE'}")
        for l in linhas:
            extra = json_por_cgm.get(l["cgm"], {})
            l["etapa"] = e["etapa"]
            l["cod_etapa"] = int(e["cod"])
            l["matricula_confirmada"] = (extra.get("matriculaconfirmada") == "S")
            l["estabelecimento_destino"] = extra.get("estabDest")
            l["turma_matricula"] = extra.get("turmamatricula")
            if not l["fone_responsavel"] and extra.get("foneCelResponsavel"):
                l["fone_responsavel"] = extra["foneCelResponsavel"]
            todos[l["cgm"]] = l

    agora = datetime.now().isoformat(timespec="seconds")
    anterior = []
    if arq.exists():
        # Arquivo ilegível levanta ArquivoJsonCorrompidoError e NÃO é tocado (o histórico não se perde).
        anterior = carregar_json(arq, dict, dict).get("alunos", [])

    if not completo:
        log("ATENÇÃO: alguma etapa divergiu do total do link — não marquei ninguém como ausente.")
    alunos = _mesclar(anterior, list(todos.values()), agora, marcar_ausentes=completo)
    pacote = {
        "ano_letivo": ano_letivo,
        "periodo": periodo,
        "coletado_em": agora,
        "coleta_completa": completo,
        "total_na_lista": len(todos),
        "alunos": alunos,
    }
    salvar_json_atomico(arq, pacote, indent=2)
    log(f"{len(todos)} aluno(s) capturado(s) -> {arq}")
    return pacote


async def _entrar_no_sere(page) -> None:
    from src.automacao import sere_2026 as s
    await page.goto(s.URL)
    await page.fill("#CHAVE", s.LOGIN)
    await page.fill("#CHAVE_ENCRIPT", s.SENHA)
    await page.click("//input[@value='Entrar']")
    await page.wait_for_timeout(3_000)
    if not await page.query_selector("#divoCMenu0_0"):
        raise RuntimeError("Não encontrou o menu principal do SERE depois do login")


async def fluxo_geo_via_login(mostrar_navegador: bool = False, log: Callable[[str], None] = print) -> dict:
    """Abre o SERE, entra e coleta os direcionados GEO do próximo ano letivo. Devolve um resumo."""
    from src.automacao import sere_2026 as s
    log("=" * 60 + "\n  Direcionados GEO (fluxo) — SERE\n" + "=" * 60)
    async with s.async_playwright() as p:
        browser = await _navegador.lancar(p, "firefox", True, forcar_mostrar=mostrar_navegador)
        page = await browser.new_page()
        try:
            await _entrar_no_sere(page)
            pacote = await coletar_fluxo_geo(page, log=log)
        finally:
            await browser.close()
    return {"ano_letivo": pacote["ano_letivo"], "total_na_lista": pacote["total_na_lista"],
            "coleta_completa": pacote["coleta_completa"],
            "arquivo": nome_arquivo(pacote["ano_letivo"])}

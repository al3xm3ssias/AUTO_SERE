"""
alunos_completo.py — Coleta robusta de cadastro completo de alunos no SERE
=============================================================================

RESUMO ESTRUTURAL (funções principais):
   - carregar_json_existente(): Carrega o JSON de saída existente (ou devolve dict vazio).
   - salvar_json(): Salva o dicionário no arquivo JSON com indentação.
   - registrar_erro(): Adiciona uma entrada de erro no arquivo de erros.
   - carregar_fila(): Lê turmas.json e devolve lista plana de dicts com
     cgm, nome, situacao, turma_id — filtra por STATUS_ACEITOS, ignora
     turmas "SEM SERIAÇÃO".
   - verificar_timestamp(): Retorna True se o aluno deve ser ignorado
     (já coletado há menos de MESES_CACHE).

Portado de AUTO_SERE/alunos_completo.py para src/automacao/alunos_completo.py.

Versão de produção da coleta de cadastro de alunos — mais robusta que
src.automacao.alunos (a versão mais simples/antiga, também portada a pedido
do usuário): interage com a TELA DE EDIÇÃO do aluno (não a de visualização),
o que permite coletar campos de formulário (inputs, selects, radios,
checkboxes) que a versão simples não alcança — deficiências, recursos de
prova, perfil socioeconômico detalhado (moradia, itens, com quem reside),
atendimento educacional especializado.

Recursos adicionais em relação a alunos.py:
  - Cache incremental (MESES_CACHE): ignora alunos já coletados recentemente
    no modo --rapido.
  - Fila filtrada por status (STATUS_ACEITOS) a partir de turmas.json.
  - Registro de erros persistente (alunos_completo_erros.json).
  - Salvamento incremental a cada 10 alunos processados (não perde tudo se
    o script cair no meio de uma coleta longa).
  - Recuperação automática quando a tabela de alunos "some" da tela
    (_garantir_tabela_alunos/garantir_lista_turmas).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. navigate_to_por_turma() REMOVIDA — reaproveita
   src.comum.sere_api.navegar_por_turma (mesma decisão já tomada para
   src.automacao.alunos e src.automacao.turmas, aprovada pelo usuário).

2. CORREÇÃO DE BUG (aprovada pelo usuário em 02/09/2026): em
   executar_coleta(), quando abrir_turma() falhava, o original calculava
   `fila_restante` (a lista de alunos daquela turma a pular) mas NUNCA
   usava essa variável — o loop continuava normalmente, então cada aluno
   daquela turma tentava abrir a MESMA turma já sabidamente com falha,
   individualmente, repetindo o mesmo erro N vezes em vez de pular a turma
   inteira de uma só vez. Não alterava o resultado final (contadores e
   arquivo de erros ficavam corretos de qualquer forma, só com tentativas
   desperdiçadas) — mas foi corrigido para pular a turma inteira assim que
   a falha é detectada, usando um `set` de turmas já sabidas com falha
   (`turmas_com_falha`), mais eficiente e sem alterar o resultado final.

3. Caminhos: BASE_DIR fixo (Path.home() / caminho absoluto do servidor
   Linux, com um bug sutil no original — `Path.home() / "/caminho/abs..."`
   descarta Path.home() por completo quando o segundo operando já é
   absoluto, então o resultado final já era equivalente a um caminho fixo)
   trocado por src.comum.paths.dados_ano_atual() — mesma fonte usada por
   todos os outros scripts já portados. TURMAS_JSON, OUTPUT_JSON e
   ERROS_JSON derivam dali.

4. Credenciais e logger: imports trocados para src.comum.credenciais e
   src.comum.logger.

5. main() RENOMEADA para coletar_cadastro_completo_via_login(modo_rapido),
   no mesmo padrão de src.automacao.turmas/alunos — pronta para ser
   chamada por um futuro botão de GUI. parse_args()/argparse removidos: o
   parâmetro `modo_rapido` passa a ser um argumento de função comum, em
   vez de lido de sys.argv.

Toda a lógica de coleta de campos (os ~60 campos de formulário mapeados em
coletar_campos, as funções auxiliares _val/_select_text/_radio_value/
_checkbox_checked/_deficiencias/_recursos_prova/_socioeconomico_*/
_com_quem_reside) é idêntica ao original — nenhuma regra de negócio foi
alterada, exceto o item 2 acima.

Uso:
    import asyncio
    from src.automacao.alunos_completo import coletar_cadastro_completo_via_login

    asyncio.run(coletar_cadastro_completo_via_login(modo_rapido=False))
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum.logger import get_logger
from src.comum import paths as _paths
from src.comum.sere_api import URL, navegar_por_turma
from src.comum import navegador as _navegador

log = get_logger(__file__)

# ──────────────────────────────────────────────
# CONSTANTES
# ──────────────────────────────────────────────
# Pasta de dados de trabalho do ano letivo corrente — antes fixo em
# BASE_DIR = Path.home() / "/home/sambauser/.../SERE/2026" (o Path.home()
# era descartado de qualquer forma, já que o segundo operando já era um
# caminho absoluto — comportamento padrão do pathlib). Agora via
# src.comum.paths.dados_ano_atual(), mesma fonte dos outros scripts.
_DADOS = _paths.dados_ano_atual()

TURMAS_JSON      = _DADOS / "turmas.json"
OUTPUT_JSON      = _DADOS / "alunos_completo.json"
ERROS_JSON       = _DADOS / "alunos_completo_erros.json"
MESES_CACHE      = 2          # modo --rapido: ignora se coletado há menos de X meses
STATUS_ACEITOS   = {"matriculado"}   # apenas estes status são processados

if not LOGIN or not SENHA:
    raise ValueError("Configure LOGIN e SENHA em credenciais/.env (ver .env.example)")


# ══════════════════════════════════════════════
# 1. UTILITÁRIOS DE PERSISTÊNCIA
# ══════════════════════════════════════════════

def carregar_json_existente(caminho: Path = OUTPUT_JSON) -> dict:
    """Carrega o JSON de saída existente (ou devolve dict vazio)."""
    if not caminho.exists():
        return {}
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Não foi possível ler {caminho}: {e} — iniciando do zero.")
        return {}


def salvar_json(dados: dict, caminho: Path = OUTPUT_JSON) -> None:
    """Salva o dicionário no arquivo JSON com indentação."""
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=4)
        log.info(f"JSON salvo em '{caminho}' ({len(dados)} alunos).")
    except OSError as e:
        log.error(f"FALHA ao salvar JSON: {e}")


def registrar_erro(cgm: str, turma_id: str, motivo: str) -> None:
    """Adiciona uma entrada de erro no arquivo de erros."""
    erros = []
    if ERROS_JSON.exists():
        try:
            with open(ERROS_JSON, encoding="utf-8") as f:
                erros = json.load(f)
        except (json.JSONDecodeError, OSError):
            erros = []

    erros.append({
        "cgm": cgm,
        "turma": turma_id,
        "motivo": motivo,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })

    try:
        ERROS_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROS_JSON, "w", encoding="utf-8") as f:
            json.dump(erros, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.error(f"FALHA ao gravar {ERROS_JSON}: {e}")

    log.warning(f"[ERRO] CGM {cgm} | turma '{turma_id}' | {motivo}")


# ══════════════════════════════════════════════
# 2. FILA DE PROCESSAMENTO (turmas.json)
# ══════════════════════════════════════════════

def carregar_fila(caminho: Path = TURMAS_JSON) -> list[dict]:
    """
    Lê turmas.json e devolve lista plana de dicts com:
        cgm, nome, situacao, turma_id
    Filtra apenas alunos com situação em STATUS_ACEITOS.
    Ignora turmas "SEM SERIAÇÃO".
    """
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)

    fila: list[dict] = []
    ignoradas = 0
    for turma_id, alunos in dados.items():
        if "SEM SERIAÇÃO" in turma_id.upper():
            log.info(f"Turma ignorada (SEM SERIAÇÃO): {turma_id}")
            ignoradas += 1
            continue
        for a in alunos:
            cgm      = str(a.get("CGM", "")).strip()
            nome     = a.get("Nome", "").strip()
            situacao = a.get("Situação", "").strip().lower()
            if not cgm:
                continue
            if situacao not in STATUS_ACEITOS:
                continue
            fila.append({
                "cgm":      cgm,
                "nome":     nome,
                "situacao": situacao,
                "turma_id": turma_id,
            })

    total_turmas = len(dados) - ignoradas
    log.info(
        f"Fila carregada: {len(fila)} alunos matriculados "
        f"em {total_turmas} turma(s) válidas."
    )
    return fila


# ══════════════════════════════════════════════
# 3. MODO RÁPIDO — verificação de cache
# ══════════════════════════════════════════════

def verificar_timestamp(cgm: str, dados_existentes: dict) -> bool:
    """
    Retorna True se o aluno deve ser ignorado (já coletado há menos de MESES_CACHE).
    Retorna False se deve ser coletado.
    """
    registro = dados_existentes.get(cgm)
    if not registro:
        return False  # nunca coletado → coletar

    ts_str = registro.get("timestamp_coleta")
    if not ts_str:
        return False  # sem timestamp → coletar

    try:
        ts = datetime.fromisoformat(ts_str)
        limite = datetime.now() - timedelta(days=MESES_CACHE * 30)
        return ts > limite   # True = recente → ignorar
    except (ValueError, TypeError):
        return False


# ══════════════════════════════════════════════
# 4. LOGIN
# ══════════════════════════════════════════════

async def login(page) -> None:
    """Acessa a URL e faz o login."""
    log.info(f"Acessando {URL}...")
    await page.goto(URL)
    await page.fill("#CHAVE", LOGIN)
    await page.fill("#CHAVE_ENCRIPT", SENHA)
    await page.click("//input[@value='Entrar']")
    await page.wait_for_timeout(3000)
    log.info("Login efetuado.")


# ══════════════════════════════════════════════
# 5. NAVEGAÇÃO — lista de turmas
# ══════════════════════════════════════════════
# navigate_to_por_turma() do original foi removida — reaproveita
# src.comum.sere_api.navegar_por_turma (decisão do usuário, 02/09/2026,
# mesma já tomada para src.automacao.alunos e src.automacao.turmas).

async def garantir_lista_turmas(page) -> bool:
    """Garante que a tabela de turmas está visível; renavega se necessário."""
    rows = await page.query_selector_all(
        "//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]"
    )
    if rows:
        return True
    log.info("Lista de turmas não visível — renavegando...")
    try:
        await navegar_por_turma(page)
        await page.wait_for_selector(
            "//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]",
            timeout=15000,
        )
        return True
    except Exception as e:
        log.error(f"Falha ao renavegar para lista de turmas: {e}")
        return False


async def abrir_turma(page, turma_id: str) -> bool:
    """Localiza e abre a turma; aguarda table#tb_alunos."""
    if not await garantir_lista_turmas(page):
        return False

    rows = await page.query_selector_all(
        "//tr[td/a[starts-with(@href,'javascript:AoClicarTurma')]]"
    )
    target = None
    for r in rows:
        cols = await r.query_selector_all("td")
        if len(cols) < 4:
            continue
        serie = (await cols[1].inner_text()).strip()
        turno = (await cols[2].inner_text()).strip()
        letra = (await cols[3].inner_text()).strip()
        if f"{serie} {turno} {letra}" == turma_id:
            target = r
            break

    if not target:
        log.error(f"[{turma_id}] Turma não encontrada na lista.")
        return False

    link = await target.query_selector("td:nth-child(2) a")
    if not link:
        log.error(f"[{turma_id}] Link da turma ausente na linha.")
        return False

    await link.click()
    try:
        await page.wait_for_selector("table#tb_alunos tbody tr", timeout=20000)
        log.info(f"[{turma_id}] Tabela de alunos carregada.")
        return True
    except Exception:
        log.error(f"[{turma_id}] Timeout aguardando table#tb_alunos.")
        return False


# ══════════════════════════════════════════════
# 6. ABRIR ALUNO (tela de edição)
# ══════════════════════════════════════════════

async def _garantir_tabela_alunos(page, turma_id: str) -> bool:
    """Verifica se a tabela de alunos está visível; reabre a turma se não estiver."""
    tabela = await page.query_selector("table#tb_alunos tbody tr")
    if tabela:
        return True
    log.warning(f"[{turma_id}] Tabela de alunos sumiu — reabrindo...")
    return await abrir_turma(page, turma_id)


async def abrir_aluno(page, cgm: str, turma_id: str) -> bool:
    """
    Localiza o link alterarAluno(cgm, ...) e clica para abrir a edição.
    Aguarda o campo #cgm ou #observacao aparecer.
    Retorna True se abriu com sucesso.
    """
    if not await _garantir_tabela_alunos(page, turma_id):
        return False

    seletor = f"a[href*=\"alterarAluno('{cgm}'\"]"
    link = await page.query_selector(seletor)

    if not link:
        log.warning(f"[{turma_id}] CGM {cgm}: link não encontrado — recarregando turma...")
        if not await abrir_turma(page, turma_id):
            return False
        link = await page.query_selector(seletor)

    if not link:
        log.error(f"[{turma_id}] CGM {cgm}: link de edição não encontrado.")
        return False

    await link.click()
    try:
        await page.wait_for_selector("#cgm, #observacao, #frmEnvio", timeout=20000)
        log.info(f"[{turma_id}] CGM {cgm}: tela de edição aberta.")
        return True
    except Exception:
        log.error(f"[{turma_id}] CGM {cgm}: timeout aguardando tela de edição.")
        return False


async def _voltar_para_turma(page, turma_id: str) -> None:
    """Clica em #btnVoltar ou usa go_back() e aguarda networkidle."""
    voltar = await page.query_selector("#btnVoltar")
    if voltar:
        await voltar.click()
    else:
        await page.go_back()
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


# ══════════════════════════════════════════════
# 7. COLETA DE CAMPOS (tela de edição)
# ══════════════════════════════════════════════

async def _val(page, selector: str, attr: str = "value") -> str:
    """Lê um atributo de um elemento; devolve string vazia se não existir."""
    try:
        el = await page.query_selector(selector)
        if not el:
            return ""
        if attr == "value":
            v = await el.get_attribute("value") or ""
        elif attr == "innerText":
            v = await el.inner_text()
        elif attr == "checked":
            v = await el.get_attribute("checked")
            return "true" if v is not None else "false"
        else:
            v = await el.get_attribute(attr) or ""
        return v.strip().replace("\xa0", " ")
    except Exception:
        return ""


async def _select_text(page, selector: str) -> str:
    """Devolve o texto da opção selecionada em um <select>."""
    try:
        return await page.eval_on_selector(
            selector,
            "el => el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : ''"
        )
    except Exception:
        return ""


async def _radio_value(page, name: str) -> str:
    """Devolve o value do radio button selecionado pelo name."""
    try:
        return await page.evaluate(
            """(name) => {
                const els = document.querySelectorAll(`input[type=radio][name="${name}"]`);
                for (const el of els) { if (el.checked) return el.value; }
                return '';
            }""",
            name,
        )
    except Exception:
        return ""


async def _checkbox_checked(page, id_: str) -> bool:
    """Verifica se um checkbox está marcado."""
    try:
        return await page.eval_on_selector(f"#{id_}", "el => el.checked")
    except Exception:
        return False


async def _deficiencias(page) -> list[dict]:
    """
    Coleta todas as deficiências marcadas (checkboxes .chk_deficiencia).
    Para cada uma, captura nome, se requer atendimento e diagnóstico (se houver).
    """
    try:
        result = await page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('.chk_deficiencia').forEach((chk, i) => {
                    const nome = chk.parentElement ? chk.parentElement.textContent.trim() : '';
                    const selecionada = chk.checked;
                    const div = document.getElementById(`_reqAtend_${i}`);
                    let requer = '';
                    let diagnostico = '';
                    if (div) {
                        const radioSim = div.querySelector('input[type=radio][value=S]');
                        const radioNao = div.querySelector('input[type=radio][value=N]');
                        if (radioSim && radioSim.checked) requer = 'Sim';
                        else if (radioNao && radioNao.checked) requer = 'Não';
                        const sel = div.querySelector('select');
                        if (sel && sel.selectedIndex > 0) {
                            diagnostico = sel.options[sel.selectedIndex].text;
                        }
                    }
                    if (selecionada) {
                        items.push({ nome, requer_atendimento: requer, diagnostico });
                    }
                });
                return items;
            }
        """)
        return result
    except Exception:
        return []


async def _recursos_prova(page) -> list[str]:
    """Coleta todos os tipoAtendimento marcados (checkboxes de recursos de prova)."""
    try:
        return await page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('input[name=tipoAtendimento]:checked').forEach(chk => {
                    const td = chk.parentElement;
                    const label = td ? td.nextElementSibling : null;
                    items.push(label ? label.textContent.trim() : chk.value);
                });
                return items;
            }
        """)
    except Exception:
        return []


async def _socioeconomico_servicos(page) -> list[str]:
    """Coleta serviços da moradia (checkboxes 18301-18304)."""
    mapa = {
        "18301": "Água encanada",
        "18302": "Energia Elétrica",
        "18303": "Esgoto",
        "18304": "Coleta de Lixo",
    }
    selecionados = []
    for id_, label in mapa.items():
        try:
            checked = await page.eval_on_selector(f"#{id_}", "el => el.checked")
            if checked:
                selecionados.append(label)
        except Exception:
            pass
    return selecionados


async def _socioeconomico_itens(page) -> list[str]:
    """Coleta itens da moradia (checkboxes 18401-18412)."""
    mapa = {
        "18401": "Banheiro", "18402": "Rádio", "18403": "Televisão",
        "18404": "Geladeira", "18405": "Computador", "18406": "Celular Smart",
        "18407": "Tablet", "18408": "Freezer", "18409": "Máquina de Lavar",
        "18410": "Bicicleta", "18411": "Motocicleta", "18412": "Automóvel",
    }
    selecionados = []
    for id_, label in mapa.items():
        try:
            checked = await page.eval_on_selector(f"#{id_}", "el => el.checked")
            if checked:
                selecionados.append(label)
        except Exception:
            pass
    return selecionados


async def _com_quem_reside(page) -> list[str]:
    """Coleta com quem o aluno reside (checkboxes 18601-18609)."""
    mapa = {
        "18601": "Pai", "18602": "Irmãos", "18603": "Avós", "18604": "Tios",
        "18605": "Mãe", "18606": "Tutor legal", "18607": "Cônjuge",
        "18608": "Filhos", "18609": "Outros",
    }
    selecionados = []
    for id_, label in mapa.items():
        try:
            checked = await page.eval_on_selector(f"#{id_}", "el => el.checked")
            if checked:
                selecionados.append(label)
        except Exception:
            pass
    return selecionados


async def coletar_campos(page, cgm: str, turma_id: str) -> dict:
    """
    Coleta TODOS os campos disponíveis na tela de edição do aluno.
    Mapeia inputs, selects, radios, checkboxes e textareas conforme teste2.html.
    """
    d: dict = {}

    # ── Dados Pessoais ──────────────────────────────────────────
    d["cgm"]             = await _val(page, "#cgm")
    d["nome"]            = await _val(page, "input[name=nome]")
    d["data_nascimento"] = await _val(page, "input[name=dataNascimento]")
    d["cod_inep"]        = await _val(page, "#codInep")

    d["modalidade"]      = await _radio_value(page, "tpModalidade")

    d["ultima_serie_cursada"]       = await _val(page, "#ultimaSerieCursada")
    d["ultima_serie_cursada_texto"] = await _select_text(page, "#ultimaSerieCursada")

    d["sexo"]                  = await _select_text(page, "#sexo")
    d["estado_civil"]          = await _select_text(page, "#estadoCivil")
    d["tipo_nacionalidade"]    = await _select_text(page, "#tipoNacionalidade")
    d["raca_cor"]              = await _select_text(page, "#racaCor")
    d["pais_origem"]           = await _select_text(page, "#nacionalidade")
    d["povo_indigena"]         = await _select_text(page, "#tipoPovoIndigena")
    d["uf_naturalidade"]       = await _select_text(page, "#ufNaturalidade")
    d["municipio_nascimento"]  = await _val(page, "#naturalidade")

    # ── Documentação ────────────────────────────────────────────
    d["modelo_certidao"]       = await _radio_value(page, "modeloCertidao")
    d["tipo_certidao"]         = await _select_text(page, "#tipoCertidao")
    d["data_emissao_certidao"] = await _val(page, "#dataEmissaoCertidao")
    d["uf_cartorio"]           = await _val(page, "#ufCartorio")
    d["municipio_cartorio"]    = await _select_text(page, "#municipioCartorio")
    d["nome_cartorio"]         = await _select_text(page, "#nomeCartorio")
    d["nome_cartorio_antigo"]  = await _val(page, "#nomeCartorio1")
    d["numero_certidao"]       = await _val(page, "#numeroCertidaoNasc")
    d["folha_certidao"]        = await _val(page, "#folhaCertidaoNasc")
    d["livro_certidao"]        = await _val(page, "#livroCertidaoNasc")
    d["matricula_certidao"]    = await _val(page, "#matriculaCertidaoNasc")
    d["rg"]                    = await _val(page, "#rg")
    d["orgao_emissor_rg"]      = await _select_text(page, "#orgaoEmissor")
    d["uf_rg"]                 = await _select_text(page, "#ufRg")
    d["data_expedicao_rg"]     = await _val(page, "#dataExpedicaoRG")
    d["cpf"]                   = await _val(page, "#cpf")
    d["titulo_eleitor"]        = await _val(page, "#numeroTituloEleitor")
    d["zona_eleitoral"]        = await _val(page, "#zonaEleitoral")
    d["secao_eleitoral"]       = await _val(page, "#secaoEleitoral")
    d["possui_passaporte"]     = await _radio_value(page, "possuiPassaporte")
    d["passaporte_rne_rnm"]    = await _val(page, "#passaporte")

    # ── Dados Familiares ────────────────────────────────────────
    d["nome_mae"]  = await _val(page, "#nomeMae")
    d["rg_mae"]    = await _val(page, "#rgMae")
    d["uf_rg_mae"] = await _select_text(page, "#UFRGMae")
    d["cel_mae"]   = await _val(page, "#foneCelMae")

    d["nome_pai"]  = await _val(page, "#nomePai")
    d["rg_pai"]    = await _val(page, "#rgPai")
    d["uf_rg_pai"] = await _select_text(page, "#ufRgPai")
    d["cpf_pai"]   = await _val(page, "#cpfPai")
    d["cel_pai"]   = await _val(page, "#foneCelPai")

    d["filiacao3"] = await _val(page, "#filiacao3")

    d["nome_responsavel"]       = await _val(page, "#nomeResponsavel")
    d["parentesco_responsavel"] = await _select_text(page, "#parentescoResponsavel")
    d["cpf_responsavel"]        = await _val(page, "#cpfResponsavel")

    # ── Contato ─────────────────────────────────────────────────
    d["cel_aluno"]         = await _val(page, "#foneCelAluno")
    d["cel_responsavel"]   = await _val(page, "#foneCelResponsavel")
    d["fone_residencial"]  = await _val(page, "#foneResidencial")
    d["fone_comercial"]    = await _val(page, "#foneComercial")
    d["ramal"]             = await _val(page, "#ramal")
    d["email_responsavel"] = await _val(page, "#email")
    d["email_aluno"]       = await _val(page, "#emailAluno")

    # ── Endereço ────────────────────────────────────────────────
    d["pais_residencia"]          = await _select_text(page, "#paisResidencia")
    d["cep"]                      = await _val(page, "#cep")
    d["uf"]                       = await _select_text(page, "#uf")
    d["cidade"]                   = await _val(page, "#cidade")
    d["endereco"]                 = await _val(page, "#endereco")
    d["numero_endereco"]          = await _val(page, "#numeroEndereco")
    d["complemento_endereco"]     = await _val(page, "#complementoEndereco")
    d["bairro"]                   = await _val(page, "#bairro")
    d["zona_residencial"]         = await _radio_value(page, "zonaResidencial")
    d["tipo_ident_geo"]           = await _select_text(page, "#tipoIdentGeo")
    d["num_ident_geo"]            = await _val(page, "#copel_id")
    d["localizacao_diferenciada"] = await _select_text(page, "#localizacaoDiferenciada")

    # ── Programas Sociais ────────────────────────────────────────
    d["bolsa_familia"]   = await _radio_value(page, "bolsaFamilia")
    d["nis_estudante"]   = await _val(page, "#identificacaoSocial")
    d["nis_responsavel"] = await _val(page, "input[name=nisResponsavel]")
    d["cad_unico"]       = await _val(page, "input[name=numCadUnico]")

    # ── Perfil Socioeconômico ────────────────────────────────────
    d["renda_familiar"]         = await _select_text(page, "#rendaFamiliar")
    d["tipo_moradia"]           = await _select_text(page, "#tipoMoradia")
    d["forma_ocupacao_moradia"] = await _select_text(page, "#formaOcupacaoMoradia")
    d["tipo_construcao"]        = await _select_text(page, "#tipoConstrucao")
    d["tipo_conexao_internet"]  = await _select_text(page, "#tipoConexao")
    d["servicos_moradia"]       = await _socioeconomico_servicos(page)
    d["itens_moradia"]          = await _socioeconomico_itens(page)
    d["com_quem_reside"]        = await _com_quem_reside(page)
    d["qtd_pessoas_residem"]    = await _val(page, "input[name=qtd_pessoas_residem_aluno]")

    # ── Observação ───────────────────────────────────────────────
    try:
        d["observacao"] = await page.eval_on_selector("#observacao", "el => el.value")
    except Exception:
        d["observacao"] = ""

    # ── Necessidades Especiais / Deficiências ────────────────────
    d["deficiencias"]   = await _deficiencias(page)
    d["recursos_prova"] = await _recursos_prova(page)

    # ── Atendimento Educacional Especializado ────────────────────
    d["atend_educacional"] = await _radio_value(page, "atendEducacional")

    # ── Metadados de coleta ──────────────────────────────────────
    d["turma_id"]         = turma_id
    d["timestamp_coleta"] = datetime.now().isoformat(timespec="seconds")

    return d


# ══════════════════════════════════════════════
# 8. PROCESSAMENTO PRINCIPAL
# ══════════════════════════════════════════════

async def processar_aluno(
    page,
    aluno: dict,
    dados_existentes: dict,
    modo_rapido: bool,
    idx: int,
    total: int,
) -> dict | None:
    """
    Abre a tela de edição de um aluno, coleta todos os campos e retorna o dict.
    Retorna None em caso de aluno ignorado (modo rápido) ou erro.
    """
    cgm      = aluno["cgm"]
    nome     = aluno["nome"]
    turma_id = aluno["turma_id"]

    log.info(f"[{idx}/{total}] Processando CGM {cgm} | {nome} | turma: {turma_id}")

    if modo_rapido and verificar_timestamp(cgm, dados_existentes):
        ts = dados_existentes[cgm].get("timestamp_coleta", "")
        log.info(f"  → Ignorado (modo --rapido): coletado em {ts}")
        return None

    if not await _garantir_tabela_alunos(page, turma_id):
        registrar_erro(cgm, turma_id, "Não foi possível garantir tabela de alunos")
        return None

    aberto = await abrir_aluno(page, cgm, turma_id)
    if not aberto:
        registrar_erro(cgm, turma_id, "Não foi possível abrir tela de edição")
        await navegar_por_turma(page)
        await abrir_turma(page, turma_id)
        return None

    try:
        dados = await coletar_campos(page, cgm, turma_id)
        dados["nome_turmas_json"] = nome
        dados["situacao"]         = aluno["situacao"]
        log.info(f"  → Coleta concluída: {len(dados)} campos.")
    except Exception as e:
        registrar_erro(cgm, turma_id, f"Erro durante coletar_campos: {e}")
        dados = None

    await _voltar_para_turma(page, turma_id)

    return dados


async def executar_coleta(page, fila: list[dict], dados_existentes: dict, modo_rapido: bool) -> dict:
    """
    Itera a fila de alunos, abrindo cada turma conforme necessário.
    Salva o JSON incrementalmente a cada 10 alunos processados.

    CORREÇÃO DE BUG (aprovada pelo usuário em 02/09/2026): quando
    abrir_turma() falha para uma turma, todos os alunos restantes DAQUELA
    turma são pulados de uma vez (via `turmas_com_falha`), em vez de cada
    um tentar reabrir individualmente a mesma turma já sabidamente com
    falha — o original calculava essa lista (`fila_restante`) mas nunca a
    usava. Resultado final (contadores, arquivo de erros) é o mesmo; só
    fica mais eficiente.
    """
    resultado = dict(dados_existentes)  # preserva dados já coletados
    total   = len(fila)
    turma_atual = None
    turmas_com_falha: set[str] = set()

    contadores = {"coletados": 0, "ignorados": 0, "erros": 0}

    for idx, aluno in enumerate(fila, start=1):
        cgm      = aluno["cgm"]
        turma_id = aluno["turma_id"]

        if turma_id in turmas_com_falha:
            contadores["erros"] += 1
            continue

        if turma_id != turma_atual:
            log.info(f"=== Abrindo turma: {turma_id} ===")
            ok = await abrir_turma(page, turma_id)
            if not ok:
                registrar_erro("—", turma_id, "Não foi possível abrir a turma")
                turmas_com_falha.add(turma_id)
                contadores["erros"] += 1
                turma_atual = None
                continue
            turma_atual = turma_id

        dados = await processar_aluno(page, aluno, resultado, modo_rapido, idx, total)

        if dados is None:
            contadores["ignorados"] += 1
        else:
            resultado[cgm] = dados
            contadores["coletados"] += 1

        if idx % 10 == 0:
            salvar_json(resultado)
            restante = total - idx
            log.info(
                f"Progresso: {idx}/{total} | "
                f"coletados={contadores['coletados']} | "
                f"ignorados={contadores['ignorados']} | "
                f"erros={contadores['erros']} | "
                f"restante={restante}"
            )

    salvar_json(resultado)

    log.info(
        f"=== COLETA FINALIZADA === "
        f"coletados={contadores['coletados']} | "
        f"ignorados={contadores['ignorados']} | "
        f"erros={contadores['erros']} | "
        f"total_no_json={len(resultado)}"
    )
    return resultado


# ══════════════════════════════════════════════
# 9. PONTO DE ENTRADA (pronto para uma futura GUI)
# ══════════════════════════════════════════════

def filtrar_fila_por_cgms(fila: list[dict], cgms) -> list[dict]:
    """Só os alunos da fila cujo CGM está em `cgms` (ex.: os alunos novos da rotina diária).
    `cgms` vazio/None = a fila inteira, como sempre foi."""
    alvo = {str(c).strip() for c in (cgms or ()) if str(c).strip()}
    if not alvo:
        return fila
    return [a for a in fila if a["cgm"] in alvo]


async def coletar_cadastro_completo_via_login(modo_rapido: bool = False, cgms=None) -> dict:
    """
    Ponto de entrada completo: carrega a fila e os dados existentes, abre o
    navegador, faz login, navega até 'Por Turma' e executa a coleta
    completa. Renomeada de main() no original — mesmo padrão de
    src.automacao.turmas/alunos, pronta para ser chamada por um futuro
    botão de GUI (sem argparse, sem sys.exit — retorna/levanta exceção
    normalmente para quem chamar decidir o que fazer).

    `modo_rapido`: equivalente à antiga flag --rapido — ignora alunos já
    coletados há menos de MESES_CACHE meses.

    `cgms`: se informado, coleta SÓ esses alunos (a rotina diária passa os alunos novos). Quem não está na fila
    (não é "matriculado" em turmas.json) é avisado no log e não é coletado. Os demais dados do arquivo são
    preservados. Sem `cgms`, coleta a fila inteira, como antes.
    """
    log.info("=" * 60)
    log.info("alunos_completo.py — iniciando")
    log.info(f"Modo rápido: {'SIM' if modo_rapido else 'NÃO'}")
    log.info("=" * 60)

    fila             = carregar_fila(TURMAS_JSON)
    dados_existentes = carregar_json_existente(OUTPUT_JSON)

    pedidos = [str(c).strip() for c in (cgms or ()) if str(c).strip()]
    if pedidos:
        fila = filtrar_fila_por_cgms(fila, pedidos)
        fora = [c for c in dict.fromkeys(pedidos) if c not in {a["cgm"] for a in fila}]
        log.info(f"Seleção por CGM: {len(fila)} de {len(set(pedidos))} aluno(s) pedido(s) estão na fila.")
        if fora:
            log.warning("CGM(s) fora da fila (não matriculados ou ausentes em turmas.json): " + ", ".join(fora[:20])
                        + (" …" if len(fora) > 20 else ""))
        if not fila:
            log.info("Nenhum dos CGMs pedidos está na fila — nada a coletar.")
            return dados_existentes

    if not fila:
        log.error("Fila vazia — nenhum aluno matriculado encontrado em turmas.json.")
        raise RuntimeError("Fila vazia — nenhum aluno matriculado encontrado em turmas.json.")

    log.info(f"Alunos já no JSON: {len(dados_existentes)}")
    log.info(f"Alunos na fila:    {len(fila)}")

    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "chromium", True)
        page    = await browser.new_page()

        await login(page)
        await navegar_por_turma(page)

        resultado = await executar_coleta(page, fila, dados_existentes, modo_rapido)

        await browser.close()

    log.info("=== Script encerrado com sucesso ===")
    from src.comum import backup as _backup
    _backup.backup_apos_coleta("alunos", log.info)
    return resultado


if __name__ == "__main__":
    import asyncio
    asyncio.run(coletar_cadastro_completo_via_login())

"""
servidores.py — Coleta de funcionários no SERE (básico + completo)
=============================================================================
Portado de AUTO_SERE/servidores.py para src/automacao/servidores.py.

Une dois módulos do original (o antigo funcionarios.py de lista resumida,
e o antigo dados_funcionarios.py de consulta individual por CPF):

  - coletar_basico(): extrai a lista resumida da tela de Consulta
    Funcionários/Docentes (nome, CPF, função, RG, nome da mãe, e-mail,
    curso superior, pós-graduação, turmas/disciplinas) → funcionarios.json
  - coletar_completo(): para cada funcionário da lista básica, consulta
    pelo CPF no formulário de Cadastro e extrai o cadastro completo
    (documentos, filiação, endereço) → funcionarios_completo.json

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Navegação Censo Escolar: _ativar_menu_censo(),
   navegar_para_consulta_funcionarios() e navegar_para_cadastro_funcionarios()
   REMOVIDAS — comparadas linha a linha com
   src.comum.sere_api.navegar_censo_escolar (já criada ao portar
   src.automacao.funcionarios) e confirmadas IDÊNTICAS (mesmo seletor,
   mesmo evento, mesmos tempos de espera 500ms/300ms, mesma sequência de
   cliques) — a única diferença era a mensagem de log impressa para cada
   destino, não o comportamento. Reaproveitada diretamente, chamada com a
   rota apropriada para cada destino (Consulta ou Cadastro).

2. Caminhos: OUTPUT_BASICO/OUTPUT_COMPLETO (antes nomes de arquivo
   relativos, "funcionarios.json"/"funcionarios_completo.json", que
   dependiam do diretório de execução) agora vêm de
   src.comum.paths.dados_ano_atual() — mesma arquitetura de todos os
   outros scripts já portados.

3. Credenciais: import trocado para src.comum.credenciais.

4. Interface: argparse (--basico / --completo, mutuamente exclusivos)
   removido — decisão do usuário (02/09/2026, mesma já tomada em outros
   scripts): coletar_servidores() recebe `modo` ("basico" ou "completo")
   como parâmetro de função. main() RENOMEADA para
   coletar_servidores_via_login(modo), mesmo padrão de
   src.automacao.turmas/alunos/funcionarios — pronta para ser chamada por
   um futuro botão de GUI.

NOTA (confirmada com o usuário): este script NÃO gera
funcionarios_matriculas.json (o arquivo com o campo numcad/matrícula que
src.automacao.termo_ciencia espera) — nem o original gerava. Esse terceiro
arquivo fica pendente para um script futuro; portar servidores.py aqui é
fiel ao comportamento original nesse ponto.

Toda a lógica de extração de campos (coletar_basico, _extrair_dados_completos,
consultar_cpf, os mapeamentos _CAMPOS_INPUT/_CAMPOS_SELECT) é idêntica ao
original — nenhuma regra de negócio foi alterada.

Uso:
    import asyncio
    from src.automacao.servidores import coletar_servidores_via_login

    asyncio.run(coletar_servidores_via_login(modo="basico"))
    asyncio.run(coletar_servidores_via_login(modo="completo"))
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from src.comum.credenciais import LOGIN, SENHA
from src.comum import paths as _paths
from src.comum.sere_api import URL, navegar_censo_escolar
from src.comum import navegador as _navegador

if not LOGIN or not SENHA:
    raise ValueError("Configure LOGIN e SENHA em credenciais/.env (ver .env.example)")

_DADOS = _paths.dados_ano_atual()

OUTPUT_BASICO   = _DADOS / "funcionarios.json"
OUTPUT_COMPLETO = _DADOS / "funcionarios_completo.json"
# Estado da última coleta COMPLETA: se terminou ou foi interrompida (e quem ficou sem atualizar). A tela de
# Funcionários lê este arquivo para avisar. Não guarda CPF, só nomes.
OUTPUT_PROGRESSO = _DADOS / "funcionarios_completo_progresso.json"
SALVAR_A_CADA = 5   # modo completo: grava o arquivo a cada N cadastros coletados (como alunos_completo.py)
RETOMAR_VALIDADE_DIAS = 3   # coleta interrompida há mais que isso não é retomada: os dados já estariam velhos
_FORMATO_DATA_HORA = "%Y-%m-%d %H:%M:%S"

_ROTA_CONSULTA = ("Funcionário/ Docente", "Consulta Funcionários/Docentes")
_ROTA_CADASTRO = ("Funcionário/ Docente", "Cadastro")


# ═════════════════════════════════════════════════════════════════════════════
#  AUTENTICAÇÃO
# ═════════════════════════════════════════════════════════════════════════════

async def login_sere(page) -> bool:
    """Faz login no sistema SERE."""
    try:
        print("🔐 Fazendo login no SERE...")
        await page.goto(URL)
        await page.fill("#CHAVE", LOGIN)
        await page.fill("#CHAVE_ENCRIPT", SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3000)
        if "sere" in page.url.lower():
            print("✅ Login realizado com sucesso!")
            return True
        print("⚠️  Possível falha no login — verifique as credenciais.")
        return False
    except Exception as e:
        print(f"❌ Erro no login: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  MÓDULO BÁSICO
# ═════════════════════════════════════════════════════════════════════════════

async def coletar_basico(page) -> list[dict]:
    """
    Extrai a lista resumida da tela de Consulta Funcionários/Docentes.
    Retorna uma lista de dicionários com os campos básicos.
    """
    await navegar_censo_escolar(page, _ROTA_CONSULTA)
    print("✅ Navegou até Consulta Funcionários/Docentes")
    await asyncio.sleep(2)

    funcionarios: list[dict] = []

    try:
        print("📋 Extraindo dados da tabela de funcionários...")

        linhas = await page.query_selector_all(
            "//table[@id='list_tabela']//tr[.//table[@id='lista_tabela_censo']]"
        )
        total = len(linhas)
        print(f"   Encontrados {total} funcionários na página")

        for idx, linha in enumerate(linhas, 1):
            try:
                print(f"   Processando {idx}/{total}...", end="  ")
                dados: dict = {}

                sub = await linha.query_selector("table#lista_tabela_censo")
                if not sub:
                    print("⚠️  sem sub-tabela, pulando")
                    continue

                # ── Nome ──────────────────────────────────────────────
                nome_elem = await sub.query_selector(
                    "xpath=.//tr[contains(.,'Nome:')]/following-sibling::tr[1]/td"
                )
                if not nome_elem:
                    nome_elem = await sub.query_selector(
                        "xpath=.//td[contains(text(),'Nome:')]/following-sibling::td"
                    )
                dados['nome'] = (await nome_elem.inner_text()).strip() if nome_elem else ""
                if not dados['nome']:
                    print("⚠️  sem nome, pulando")
                    continue

                # ── Data de Nascimento ────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'Data Nascimento:')]/following-sibling::tr[1]/td[1]"
                )
                dados['data_nascimento'] = (await e.inner_text()).strip() if e else ""

                # ── CPF ───────────────────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'CPF:')]/following-sibling::tr[1]/td[2]"
                )
                dados['cpf'] = (await e.inner_text()).strip() if e else ""

                # ── Função ────────────────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'Função:')]/following-sibling::tr[1]/td"
                )
                dados['funcao'] = (await e.inner_text()).strip() if e else ""

                # ── RG ────────────────────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'RG:')]/following-sibling::tr[1]/td"
                )
                dados['rg'] = (await e.inner_text()).strip() if e else ""

                # ── Nome da Mãe ───────────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'Nome Mãe:')]/following-sibling::tr[1]/td"
                )
                dados['nome_mae'] = (await e.inner_text()).strip() if e else ""

                # ── E-mail ────────────────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'e-mail:')]/following-sibling::tr[1]/td"
                )
                dados['email'] = (await e.inner_text()).strip() if e else ""

                # ── Curso Superior ────────────────────────────────────
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'Curso superior:')]/following-sibling::tr[1]//spam"
                )
                dados['curso_superior'] = (await e.inner_text()).strip() if e else ""

                # ── Pós-Graduação ─────────────────────────────────────
                dados['pos_graduacao'] = []
                e = await sub.query_selector(
                    "xpath=.//tr[contains(.,'Pós Graduação')]/following-sibling::tr[1]//spam"
                )
                if e:
                    texto = await e.inner_text()
                    for linha_pg in texto.strip().split('\n'):
                        linha_pg = linha_pg.strip()
                        if linha_pg and 'Pós-Graduação' in linha_pg:
                            dados['pos_graduacao'].append(linha_pg)

                # ── Turmas e Disciplinas ──────────────────────────────
                dados['turmas'] = []
                atuacao_td = await linha.query_selector("xpath=./td[2]")
                if atuacao_td:
                    atuacao_elem = await atuacao_td.query_selector("pre spam")
                    if atuacao_elem:
                        texto = await atuacao_elem.inner_text()
                        if texto and texto.strip():
                            turma_atual = None
                            for linha_at in texto.strip().split('\n'):
                                linha_at = linha_at.strip()
                                if not linha_at:
                                    continue
                                if linha_at.startswith('-'):
                                    if turma_atual:
                                        dados['turmas'].append(turma_atual)
                                    turma_atual = {'descricao': linha_at, 'disciplinas': []}
                                elif turma_atual:
                                    turma_atual['disciplinas'].append(linha_at)
                            if turma_atual:
                                dados['turmas'].append(turma_atual)

                funcionarios.append(dados)
                print(f"✓ {dados['nome']}")

            except Exception as e:
                print(f"❌ erro: {e}")
                continue

    except Exception as e:
        print(f"❌ Erro geral ao coletar funcionários: {e}")
        import traceback; traceback.print_exc()

    return funcionarios


# ═════════════════════════════════════════════════════════════════════════════
#  MÓDULO COMPLETO
# ═════════════════════════════════════════════════════════════════════════════

# Mapeamento input[name] → chave no JSON de saída
_CAMPOS_INPUT = {
    "nomeCompleto":         "nome_completo",
    "dataNasc":             "data_nascimento",
    "numNis":               "nis",
    "email":                "email",
    "foneCelFuncionario":   "telefone",
    "nomeCompletoMae":      "nome_mae",
    "municipioNasc":        "municipio_nascimento",
    "cep":                  "cep",
    "municipioEnd":         "municipio_endereco",
    "enderecoEnd":          "endereco",
    "bairroEnd":            "bairro",
    "numeroEnd":            "numero",
    "complementoEnd":       "complemento",
    "nomeCartorio":         "nome_cartorio",
    "numTermo":             "numero_termo",
    "folha":                "folha",
    "livro":                "livro",
    "numIdentidade":        "rg",
    "dataExpedicao":        "data_expedicao_rg",
    "complIdentidade":      "complemento_rg",
}

_CAMPOS_SELECT = {
    "racaCor":          "raca_cor",
    "tipoNacionalidade":"tipo_nacionalidade",
    "nacionalidade":    "pais_origem",
    "ufNasc":           "uf_nascimento",
    "ufEnd":            "uf_endereco",
    "zonaRes":          "zona_residencial",
    "tipoCertidao":     "tipo_certidao",
    "ufCartorio":       "uf_cartorio",
    "ufIdentidade":     "uf_rg",
    "orgaoEmissIdent":  "orgao_emissor_rg",
    "escolaridade":     "escolaridade",
}


async def _limpar_e_voltar(page) -> None:
    """Clica em Voltar e limpa os campos para a próxima consulta."""
    try:
        btn = await page.query_selector('input[name="voltar"]')
        if btn:
            await btn.click()
            await page.wait_for_timeout(2000)
        campos = [
            'input[name="nomeCompleto"]',
            'input[name="dataNasc"]',
            'input[name="numCpf"]',
        ]
        for sel in campos:
            campo = await page.query_selector(sel)
            if campo:
                await campo.click(click_count=3)
                await campo.press("Backspace")
        cpf_field = await page.query_selector('input[name="numCpf"][maxlength="11"]')
        return bool(cpf_field)
    except Exception as e:
        print(f"⚠️  Erro ao limpar campos: {e}")
        return False


async def _extrair_dados_completos(page, cpf: str) -> dict:
    """Extrai todos os campos do formulário de cadastro de um funcionário."""
    dados: dict = {"cpf": cpf, "data_consulta": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # Inputs
    for campo_html, chave in _CAMPOS_INPUT.items():
        try:
            el = await page.query_selector(f'input[name="{campo_html}"]')
            dados[chave] = (await el.input_value()) if el else None
        except Exception:
            dados[chave] = None

    # Selects
    for campo_html, chave in _CAMPOS_SELECT.items():
        try:
            el = await page.query_selector(f'select[name="{campo_html}"]')
            if el:
                opt = await el.query_selector("option:checked")
                if opt:
                    v = await opt.get_attribute("value") or await opt.text_content()
                    dados[chave] = v.strip() if v else None
                else:
                    dados[chave] = None
            else:
                dados[chave] = None
        except Exception:
            dados[chave] = None

    # Sexo (radio)
    try:
        r = await page.query_selector('input[name="sexo"]:checked')
        dados["sexo"] = await r.get_attribute("value") if r else None
    except Exception:
        dados["sexo"] = None

    # Deficiências (checkboxes)
    try:
        cbs = await page.query_selector_all('input[name="def"]:checked')
        vals = []
        for cb in cbs:
            v = await cb.get_attribute("value")
            if v:
                vals.append(v)
        dados["deficiencias"] = ";".join(vals) if vals else None
    except Exception:
        dados["deficiencias"] = None

    return dados


async def consultar_cpf(page, cpf: str) -> Optional[dict]:
    """Consulta um funcionário pelo CPF no cadastro e retorna os dados completos."""
    try:
        cpf_field = await page.query_selector('input[name="numCpf"][maxlength="11"]')
        btn_pesq   = await page.query_selector('input[name="btnPesquisar"]')

        if not cpf_field or not btn_pesq:
            print(f"   ❌ Campos de pesquisa não encontrados")
            return None

        await cpf_field.click(click_count=3)
        await cpf_field.press("Backspace")
        await cpf_field.fill(cpf)
        await btn_pesq.click()
        await page.wait_for_timeout(4000)

        nome_field = await page.query_selector('input[name="nomeCompleto"]')
        if nome_field:
            nome_val = await nome_field.input_value()
            if nome_val and nome_val.strip():
                print(f"   ✅ {nome_val.strip()}")
                dados = await _extrair_dados_completos(page, cpf)
                await _limpar_e_voltar(page)
                return dados

        print(f"   ⚠️  CPF {cpf} não encontrado")
        await _limpar_e_voltar(page)
        return None

    except Exception as e:
        print(f"   ❌ Erro ao consultar CPF {cpf}: {e}")
        try:
            await _limpar_e_voltar(page)
        except Exception:
            pass
        return None


def _so_digitos(valor) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _gravar_json(caminho: Path, dados, indent: int = 2) -> None:
    """Grava sem deixar o arquivo pela metade se o programa cair no meio da escrita (escreve ao lado e troca)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=indent)
    tmp.replace(caminho)


def _carregar_completo_anterior() -> list[dict]:
    """Registros que já estavam em funcionarios_completo.json (de uma coleta anterior). [] se não existir ou estiver ruim."""
    if not OUTPUT_COMPLETO.exists():
        return []
    try:
        with open(OUTPUT_COMPLETO, encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return [r for r in dados if isinstance(r, dict)] if isinstance(dados, list) else []


def gravar_progresso(completa: bool, total: int, coletados: int, pendentes: list[str],
                     iniciado_em: str, motivo: str = "") -> dict:
    """Grava funcionarios_completo_progresso.json e devolve o conteúdo (com o texto do aviso, se incompleta)."""
    estado = {
        "completa": completa,
        "total": total,
        "coletados": coletados,
        "pendentes": pendentes,
        "iniciado_em": iniciado_em,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "motivo": motivo,
    }
    if not completa:
        quando = ("não terminou (ainda em andamento, ou o programa parou no meio)" if motivo in ("", "em andamento")
                  else f"foi interrompida ({motivo})")
        estado["aviso"] = (
            f"A coleta completa de funcionários {quando}: "
            f"{coletados} de {total} cadastros foram coletados e salvos. Os outros {len(pendentes)} NÃO foram "
            f"atualizados e ficaram com os dados da coleta anterior (ou sem cadastro completo, se não havia). "
            f"Rode a coleta completa de novo para terminar."
        )
    try:
        _gravar_json(OUTPUT_PROGRESSO, estado)
    except OSError as e:
        print(f"⚠️  Não foi possível gravar {OUTPUT_PROGRESSO.name}: {e}")
    return estado


def _motivo_da_parada(erro: BaseException) -> str:
    """Texto curto do porquê a coleta parou: cancelamento pelo usuário ou erro."""
    if isinstance(erro, (asyncio.CancelledError, KeyboardInterrupt)) or type(erro).__name__ == "CancelamentoSolicitado":
        return "cancelada"
    return f"erro: {str(erro).strip() or type(erro).__name__}"


def _retomada_pendente() -> Optional[str]:
    """
    `iniciado_em` da última coleta completa se ela foi INTERROMPIDA há pouco (progresso com completa=False e dentro de
    RETOMAR_VALIDADE_DIAS); None se terminou, nunca rodou, o arquivo está ruim ou a interrupção é antiga demais.
    """
    try:
        with open(OUTPUT_PROGRESSO, encoding="utf-8") as f:
            estado = json.load(f)
        if not isinstance(estado, dict) or estado.get("completa") is not False:
            return None
        iniciado = str(estado.get("iniciado_em") or "")
        if (datetime.now() - datetime.strptime(iniciado, _FORMATO_DATA_HORA)).days >= RETOMAR_VALIDADE_DIAS:
            return None
        return iniciado
    except (OSError, ValueError, json.JSONDecodeError):
        return None


async def coletar_completo(page, lista_basico: list[dict], recomecar: bool = False) -> list[dict]:
    """
    Percorre a lista de funcionários básicos, busca cada um pelo CPF no
    formulário de Cadastro e retorna os dados completos.

    Salva aos poucos (a cada SALVAR_A_CADA cadastros), como alunos_completo.py: se a coleta for cancelada ou cair
    no meio, o que já foi coletado fica gravado. Enquanto roda, o arquivo nunca encolhe: quem ainda não foi
    consultado mantém o registro da coleta anterior. Se parar antes do fim, avisa no log e deixa o aviso em
    funcionarios_completo_progresso.json (a tela de Funcionários mostra). Só quando termina o arquivo passa a
    ter exatamente os cadastros coletados agora (como sempre foi).

    RETOMADA: cada cadastro coletado leva `coletado_em`. Se a última coleta completa foi interrompida há pouco
    (ver _retomada_pendente), quem já foi coletado nela NÃO é consultado de novo: a rodada continua de onde parou e
    mantém o `iniciado_em` original. `recomecar=True` ignora a interrupção e consulta todos.
    """
    await navegar_censo_escolar(page, _ROTA_CADASTRO)
    print("✅ Navegou até Cadastro de Funcionários")

    anteriores = _carregar_completo_anterior()
    iniciado_em = datetime.now().strftime(_FORMATO_DATA_HORA)
    dados_completos: list[dict] = []
    total = len(lista_basico)
    com_cpf = [f for f in lista_basico if _so_digitos(f.get("cpf"))]
    coletados_cpf: set[str] = set()

    desde = None if recomecar else _retomada_pendente()
    if desde:
        na_lista = {_so_digitos(f.get("cpf")) for f in com_cpf}
        for r in anteriores:                      # coletados na rodada interrompida (e ainda na lista): ficam
            cpf_r = _so_digitos(r.get("cpf"))
            if cpf_r in na_lista and cpf_r not in coletados_cpf and str(r.get("coletado_em") or "") >= desde:
                dados_completos.append(r)
                coletados_cpf.add(cpf_r)
        iniciado_em = desde
        print(f"↩️  Retomando a coleta interrompida (iniciada em {desde}): {len(dados_completos)} de {len(com_cpf)} "
              f"cadastros já coletados; faltam {len(com_cpf) - len(dados_completos)}. (Para refazer todos, marque \"Recomeçar do zero\".)")

    def _pendentes() -> list[str]:
        return [str(f.get("nome") or f.get("cpf") or "").strip() or "(sem nome)"
                for f in com_cpf if _so_digitos(f.get("cpf")) not in coletados_cpf]

    def _salvar_parcial() -> None:
        # novos + registros antigos de quem ainda não foi coletado agora: o arquivo não encolhe no meio da coleta
        restantes = [r for r in anteriores if _so_digitos(r.get("cpf")) not in coletados_cpf]
        _gravar_json(OUTPUT_COMPLETO, dados_completos + restantes)
        gravar_progresso(False, len(com_cpf), len(dados_completos), _pendentes(), iniciado_em, "em andamento")

    try:
        for i, func in enumerate(lista_basico, 1):
            cpf = func.get("cpf", "").strip()
            if not cpf:
                print(f"   [{i}/{total}] ⚠️  sem CPF, pulando")
                continue
            if _so_digitos(cpf) in coletados_cpf:
                print(f"[{i}/{total}] já coletado na rodada interrompida, pulando")
                continue

            print(f"[{i}/{total}] CPF {cpf} ...", end="  ")
            dados = await consultar_cpf(page, cpf)
            if dados:
                dados["coletado_em"] = datetime.now().strftime(_FORMATO_DATA_HORA)
                dados_completos.append(dados)
                coletados_cpf.add(_so_digitos(cpf))
                if len(dados_completos) % SALVAR_A_CADA == 0:
                    _salvar_parcial()
                    print(f"   💾 {len(dados_completos)} cadastros salvos até aqui")
            else:
                print(f"   [{i}/{total}] Não coletado")

            await page.wait_for_timeout(800)
    except BaseException as erro:          # cancelamento (CancelledError/CancelamentoSolicitado) e erro: salva e avisa
        motivo = _motivo_da_parada(erro)
        try:
            restantes = [r for r in anteriores if _so_digitos(r.get("cpf")) not in coletados_cpf]
            _gravar_json(OUTPUT_COMPLETO, dados_completos + restantes)
        except OSError as e:
            print(f"⚠️  Não foi possível salvar o que foi coletado: {e}")
        estado = gravar_progresso(False, len(com_cpf), len(dados_completos), _pendentes(), iniciado_em, motivo)
        print(f"\n⚠️  {estado['aviso']}")
        raise
    return dados_completos


# ═════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT (pronto para uma futura GUI)
# ═════════════════════════════════════════════════════════════════════════════

async def coletar_servidores(page, modo: str, recomecar: bool = False) -> list[dict]:
    """
    Executa o modo de coleta especificado ("basico" ou "completo") numa
    `page` já autenticada no SERE, e salva o resultado no arquivo
    correspondente (OUTPUT_BASICO ou OUTPUT_COMPLETO). Retorna a lista
    coletada.

    No modo "completo", se OUTPUT_BASICO ainda não existir, coleta os
    dados básicos primeiro (mesmo comportamento do original).
    """
    if modo == "basico":
        print("\n── MODO BÁSICO ─────────────────────────────────────────")
        lista = await coletar_basico(page)

        OUTPUT_BASICO.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_BASICO, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False, indent=4)

        print(f"\n✅ {OUTPUT_BASICO} salvo com {len(lista)} funcionários.")
        return lista

    elif modo == "completo":
        print("\n── MODO COMPLETO ───────────────────────────────────────")

        if OUTPUT_BASICO.exists():
            with open(OUTPUT_BASICO, "r", encoding="utf-8") as f:
                lista_basico = json.load(f)
            print(f"📂 Lista básica carregada de {OUTPUT_BASICO} ({len(lista_basico)} registros)")
        else:
            print(f"⚠️  {OUTPUT_BASICO} não encontrado — coletando dados básicos primeiro...")
            lista_basico = await coletar_basico(page)
            OUTPUT_BASICO.parent.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_BASICO, "w", encoding="utf-8") as f:
                json.dump(lista_basico, f, ensure_ascii=False, indent=4)
            print(f"✅ {OUTPUT_BASICO} salvo com {len(lista_basico)} funcionários.")

        print(f"\n📡 Consultando {len(lista_basico)} funcionários no cadastro individual...")
        inicio_coleta = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dados_completos = await coletar_completo(page, lista_basico, recomecar)

        _gravar_json(OUTPUT_COMPLETO, dados_completos)
        com_cpf = [f for f in lista_basico if _so_digitos(f.get("cpf"))]
        coletados = {_so_digitos(r.get("cpf")) for r in dados_completos}
        nao_achados = [str(f.get("nome") or f.get("cpf") or "").strip() for f in com_cpf
                       if _so_digitos(f.get("cpf")) not in coletados]
        gravar_progresso(True, len(com_cpf), len(dados_completos), nao_achados, inicio_coleta)

        print(f"\n✅ {OUTPUT_COMPLETO} salvo com {len(dados_completos)} registros completos.")
        if nao_achados:
            print(f"ℹ️  {len(nao_achados)} funcionário(s) da lista básica não foram encontrados no cadastro pelo CPF.")
        return dados_completos

    else:
        raise ValueError(f"modo deve ser 'basico' ou 'completo', recebido: {modo!r}")


async def coletar_servidores_via_login(modo: str, recomecar: bool = False) -> list[dict]:
    """
    Ponto de entrada completo: abre o navegador, faz login no SERE,
    executa o modo de coleta especificado e fecha o navegador. Renomeada
    de main() no original — argparse (--basico/--completo) removido,
    `modo` é parâmetro de função, mesmo padrão de
    src.automacao.turmas/alunos/funcionarios — pronta para ser chamada
    por um futuro botão de GUI.

    Ajustes (20/10/2026, ao colocar a coleta na lista de Automações):
      - falha de login agora LEVANTA RuntimeError (antes devolvia [] e a execução terminava "com sucesso", sem
        nenhum dado e sem explicação na tela);
      - o navegador é fechado também quando a coleta dá erro ou é cancelada (antes ficava aberto).
    """
    if modo not in ("basico", "completo"):
        raise ValueError(f"modo deve ser 'basico' ou 'completo', recebido: {modo!r}")
    async with async_playwright() as p:
        browser = await _navegador.lancar(p, "chromium", True)
        try:
            page = await browser.new_page()

            if not await login_sere(page):
                raise RuntimeError("Falha no login no SERE: confira o login e a senha em Configurações → Senha do SERE.")

            resultado = await coletar_servidores(page, modo, **({"recomecar": True} if recomecar else {}))
        finally:
            await browser.close()
    from src.comum import backup as _backup
    _backup.backup_apos_coleta("funcionários")
    return resultado


async def coletar_funcionarios_automacao(modo: str = "completo", atualizar_lista: bool = False, recomecar: bool = False) -> dict:
    """
    Ponto de entrada da automação "Funcionários / Servidores" (lista de Automações). Devolve só um RESUMO
    ({"modo", "total", "arquivo", "lista_atualizada"}) — os cadastros completos ficam nos arquivos, e não na
    resposta da tela.

    No modo "completo", se funcionarios.json já existe a coleta REUSA essa lista (comportamento do original);
    `atualizar_lista=True` refaz a lista básica antes, para pegar quem entrou ou saiu desde a última coleta.
    """
    if modo not in ("basico", "completo"):
        raise ValueError(f"modo deve ser 'basico' ou 'completo', recebido: {modo!r}")
    atualizar = bool(atualizar_lista) and modo == "completo"
    if atualizar:
        print("Atualizando antes a lista básica de funcionários...")
        await coletar_servidores_via_login("basico")
    lista = await coletar_servidores_via_login(modo, **({"recomecar": True} if recomecar else {}))
    arquivo = OUTPUT_BASICO if modo == "basico" else OUTPUT_COMPLETO
    return {"modo": modo, "total": len(lista), "arquivo": str(arquivo), "lista_atualizada": atualizar}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] not in ("basico", "completo"):
        print("Uso: python -m src.automacao.servidores basico|completo")
        sys.exit(1)
    asyncio.run(coletar_servidores_via_login(sys.argv[1]))

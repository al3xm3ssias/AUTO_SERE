"""
sincroniza_sheets.py — turmas.json ↔ planilha do Google Sheets
════════════════════════════════════════════════════════════════════════════
Incorpora ao AUTO SERE o antigo `sheets_sync` (main.py, sync_engine.py, turmas_reader.py, config.py): a mesma
regra de negócio, agora usando o turmas.json do ano letivo, as opções comuns (turma), o registro de scripts
e as funções genéricas de src/comum/google_sheets.py.

    turmas.py ─► turmas.json ─► sincronizar_turmas() ─► uma ABA por turma na planilha do Google

Operações (`executar_planilha_google`):
    criar      cria uma planilha NOVA (uma aba por turma, com cabeçalhos) e já a preenche
    atualizar  atualiza uma planilha que já existe (ID ou link)
    verificar  só confere o acesso e lista as abas (não grava nada)

Layout de cada aba (colunas A–L; quem manda é a coluna C, o CGM):
    A Nº · B CPF* · C CGM · D SUS* · E Nome · F D.N. · G Idade* · H Sexo · I Status (M/T) · J Data de matrícula ·
    K Escola de origem* · L Data de transferência          (* = o programa NÃO mexe nessas colunas)

Regras (herdadas do sheets_sync, que já rodava em produção):
    • o aluno é achado pelo CGM; as linhas de cabeçalho/título da aba são ignoradas (CGM = só dígitos);
    • aluno novo → linha nova no fim da aba; aluno existente → só as células que MUDARAM;
    • Transferido: I = T, J e H em branco, L = data da movimentação;  Matriculado: I = M, J = data, L em branco.

O que mudou em relação ao sheets_sync (de propósito):
    • antes a linha INTEIRA (A–L) era regravada quando algo mudava, trocando fórmulas das colunas "preservadas"
      (ex.: Idade) por valores e mexendo em colunas fora do escopo; agora só se grava célula por célula o que
      difere, e as colunas B, D, G e K existentes nunca são tocadas (a Idade só é preenchida em linha NOVA);
    • a leitura traz as datas como aparecem na tela (dd/mm/aaaa) e compara data com data. Antes a comparação
      contra o número de série do Google fazia quase toda linha parecer "alterada" a cada execução
      (no log de 25/05: 183–184 "atualizados" em execuções seguidas sem nenhuma mudança);
    • duas linhas do JSON com o mesmo CGM (ex.: transferido que voltou, cadastro novo com outro Nº) viram UMA:
      vale o registro de data mais recente (desempate: maior Nº), a mesma regra de src/automacao/fila_transferidos.py;
    • a situação segue a regra comum do sistema (opcoes_execucao.eh_transferido);
    • aba ausente ou com erro não derruba as demais; no fim, os problemas são resumidos e a execução acusa falha.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from src.comum import google_sheets as gs
from src.comum.logger import get_logger
from src.comum.opcoes_execucao import eh_transferido
from src.comum.registros_aluno import parse_data

log = get_logger(__file__)

OPERACOES = ("criar", "atualizar", "verificar")

# ── layout da planilha (letras de coluna; antes: sheets_sync/config.py) ────────────────────────────────
COLUNAS = {"numero": "A", "cpf": "B", "cgm": "C", "sus": "D", "nome": "E", "data_nasc": "F", "idade": "G",
           "sexo": "H", "status": "I", "data_matricula": "J", "escola_origem": "K", "data_transferencia": "L"}
CABECALHOS = ["Nº", "CPF", "CGM", "SUS", "Nome do aluno", "D.N.", "Idade", "Sexo", "Status",
              "Data de Matrícula", "Escola de Origem", "Data de Transferência"]
ULTIMA_COLUNA = "L"
GERENCIADAS = ("numero", "cgm", "nome", "data_nasc", "sexo", "status", "data_matricula", "data_transferencia")
STATUS_MATRICULADO, STATUS_TRANSFERIDO = "M", "T"
SEXO = {"Masculino": "M", "Feminino": "F"}

# Turma do turmas.json → aba da planilha da escola (antes: ABA_MAP em sheets_sync/main.py). Pode ser
# complementado/substituído em config/config_usuario.json → google_sheets.mapa_abas. Turma fora do mapa usa o próprio nome.
ABA_PADRAO = {
    "INFANTIL 4 Integral A": "INFANTIL IV",
    "INFANTIL 5 Integral A": "INFANTIL V",
    "1º Ano Integral A": "1º ANO",
    "2º Ano Integral A": "2º ANO",
    "3º Ano Integral A": "3º ANO A",
    "3º Ano Integral B": "3º ANO B",
    "4º Ano Integral A": "4º ANO",
    "5º Ano Integral A": "5º ANO",
}

_RE_CGM = re.compile(r"^\d{5,12}$")


def mapa_abas() -> dict[str, str]:
    from src.comum.configuracao import google_sheets_config
    return {**ABA_PADRAO, **{str(k): str(v) for k, v in (google_sheets_config().get("mapa_abas") or {}).items()}}


@dataclass
class Resumo:
    adicionados: int = 0
    atualizados: int = 0
    transferidos: int = 0
    sem_mudanca: int = 0
    erros: list[str] = field(default_factory=list)

    def somar(self, outro: "Resumo") -> None:
        self.adicionados += outro.adicionados
        self.atualizados += outro.atualizados
        self.transferidos += outro.transferidos
        self.sem_mudanca += outro.sem_mudanca
        self.erros += outro.erros


# ══════════════════════════════════════════════════════════════════════════
# VALORES E COMPARAÇÃO
# ══════════════════════════════════════════════════════════════════════════

def _cgm_texto(valor) -> str:
    """CGM como texto de dígitos, venha como texto, int ou float (o Google devolve 123.0 às vezes)."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor if valor is not None else "").strip()


def valores_do_aluno(aluno: dict) -> dict[str, object]:
    """O que o programa quer na planilha para este aluno, só nas colunas que ele gerencia."""
    transferido = eh_transferido(aluno)
    data = aluno.get("Data Matricula", "")
    sexo = aluno.get("Sexo", "")
    return {
        "numero": aluno.get("N", ""),
        "cgm": _cgm_texto(aluno.get("CGM", "")),
        "nome": aluno.get("Nome", ""),
        "data_nasc": aluno.get("Data Nasc.", ""),
        "sexo": "" if transferido else SEXO.get(sexo, sexo),
        "status": STATUS_TRANSFERIDO if transferido else STATUS_MATRICULADO,
        "data_matricula": "" if transferido else data,
        "data_transferencia": data if transferido else "",
    }


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _como_data(texto: str) -> Optional[date]:
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _iguais(atual, desejado) -> bool:
    a, b = _texto(atual), _texto(desejado)
    if a == b:
        return True
    da, db = _como_data(a), _como_data(b)
    return da is not None and da == db


def _celula(linha: list, campo: str):
    indice = gs.coluna_para_indice(COLUNAS[campo])
    return linha[indice] if indice < len(linha) else ""


def _linha_nova(aluno: dict) -> list:
    """Linha completa de um aluno que ainda não está na planilha (as colunas não gerenciadas ficam em branco; Idade vem do JSON)."""
    linha = [""] * (gs.coluna_para_indice(ULTIMA_COLUNA) + 1)
    for campo, valor in valores_do_aluno(aluno).items():
        linha[gs.coluna_para_indice(COLUNAS[campo])] = valor
    linha[gs.coluna_para_indice(COLUNAS["idade"])] = aluno.get("Idade", "")
    return linha


def _numero(aluno: dict) -> int:
    try:
        return int(aluno.get("N"))
    except (TypeError, ValueError):
        return 0


def escolher_registros(alunos: list[dict]) -> list[dict]:
    """
    Um registro por CGM (a aba tem uma linha por aluno). Se o CGM repete, vale o de data mais recente, depois o de
    maior Nº. Alunos sem CGM são ignorados com aviso. Mantém a ordem da primeira aparição.
    """
    escolhidos: dict[str, dict] = {}
    for aluno in alunos:
        cgm = _cgm_texto(aluno.get("CGM", ""))
        if not cgm:
            log.warning("  ⚠ Aluno sem CGM ignorado: %s", aluno.get("Nome"))
            continue
        atual = escolhidos.get(cgm)
        if atual is None:
            escolhidos[cgm] = aluno
            continue
        chave = lambda a: (parse_data(a.get("Data Matricula")) or date.min, _numero(a))     # noqa: E731
        log.warning("  ⚠ CGM %s repetido no turmas.json (%s): vale o registro mais recente.", cgm, aluno.get("Nome"))
        if chave(aluno) > chave(atual):
            escolhidos[cgm] = aluno
    return list(escolhidos.values())


# ══════════════════════════════════════════════════════════════════════════
# SINCRONIZAÇÃO
# ══════════════════════════════════════════════════════════════════════════

def sincronizar_aba(planilha: str, aba: str, alunos: list[dict], *, simulacao: bool = False, servico=None) -> Resumo:
    """Sincroniza UMA aba com a lista de alunos de uma turma. Com `simulacao`, lê e compara mas não grava."""
    resumo = Resumo()
    leitura = gs.ler_intervalo(planilha, gs.intervalo_a1(aba, "A", ULTIMA_COLUNA), servico=servico)

    indice: dict[str, tuple[int, list]] = {}                  # CGM → (nº da linha na planilha, linha lida)
    for posicao, linha in enumerate(leitura, start=1):
        cgm = _cgm_texto(_celula(linha, "cgm"))
        if _RE_CGM.match(cgm):                                 # cabeçalho/título/linha em branco não entram
            if cgm in indice:
                log.warning("  ⚠ CGM %s aparece em mais de uma linha da aba '%s'; vale a última (linha %d).", cgm, aba, posicao)
            indice[cgm] = (posicao, linha)

    alteracoes: dict[str, list[list]] = {}
    novas: list[list] = []
    for aluno in escolher_registros(alunos):
        cgm = _cgm_texto(aluno.get("CGM", ""))
        desejado = valores_do_aluno(aluno)
        transferido = desejado["status"] == STATUS_TRANSFERIDO
        if cgm in indice:
            posicao, linha = indice[cgm]
            mudou = [c for c in GERENCIADAS if not _iguais(_celula(linha, c), desejado[c])]
            if not mudou:
                resumo.sem_mudanca += 1
                continue
            for campo in mudou:
                alteracoes[gs.intervalo_a1(aba, f"{COLUNAS[campo]}{posicao}")] = [[desejado[campo]]]
            if transferido:
                resumo.transferidos += 1
                log.info("  🔄 TRANSFERIDO | %-40s | CGM %s | %s", aluno.get("Nome"), cgm, aluno.get("Data Matricula"))
            else:
                resumo.atualizados += 1
                log.info("  ✏ ATUALIZADO  | %-40s | CGM %s | %s", aluno.get("Nome"), cgm, ", ".join(mudou))
        else:
            novas.append(_linha_nova(aluno))
            resumo.adicionados += 1
            if transferido:
                resumo.transferidos += 1
            log.info("  ➕ ADICIONADO%s | %-40s | CGM %s", " (TRANSF.)" if transferido else "           ", aluno.get("Nome"), cgm)

    if simulacao:
        return resumo
    if alteracoes:
        celulas = gs.atualizar_intervalos(planilha, alteracoes, servico=servico)
        log.debug("  → %d célula(s) atualizada(s) em lote.", celulas)
    if novas:
        inseridas = gs.anexar_linhas(planilha, aba, novas, servico=servico)
        log.debug("  → %d linha(s) nova(s) inserida(s).", inseridas)
    return resumo


def sincronizar_turmas(turmas: dict, planilha: str, *, turmas_selecionadas=None, simulacao: bool = False,
                       servico=None, mapa: dict | None = None) -> Resumo:
    """
    Sincroniza as turmas escolhidas (padrão: todas) com as abas da planilha. Erros de acesso/credencial interrompem
    tudo; aba ausente ou com erro só entra no resumo, e as demais seguem. Quem chama decide o que fazer com `erros`.
    """
    mapa = mapa if mapa is not None else mapa_abas()
    info = gs.verificar_planilha(planilha, servico=servico)
    log.info("Planilha: %s — abas: %s", info["titulo"], ", ".join(info["abas"]))
    alvo = list(turmas_selecionadas) if turmas_selecionadas else list(turmas)

    total = Resumo()
    for turma in alvo:
        alunos = turmas.get(turma, [])
        log.info("")
        log.info("─── Turma: %s (%d aluno(s)) ───", turma, len(alunos))
        try:
            aba = gs.resolver_aba(mapa.get(turma, turma), info["abas"])
            total.somar(sincronizar_aba(info["id"], aba, alunos, simulacao=simulacao, servico=servico))
        except (gs.SheetsAutenticacaoErro, gs.SheetsAcessoErro):
            raise                                              # vale para a planilha toda: continuar só repetiria o erro
        except gs.GoogleErro as exc:
            log.error("  ✗ %s: %s", turma, exc)
            total.erros.append(f"{turma}: {exc}")
    return total


def _salvar_no_cadastro(info: dict) -> None:
    """
    Cadastra a planilha recém-criada na tela "Planilhas do Drive" (nome, link e id). A planilha já existe no Google:
    se não der para cadastrar, só avisa (o ID continua guardado como "última usada" nas Configurações).
    """
    from src.comum import planilhas_registro
    from src.comum.arquivos_json import ArquivoJsonCorrompidoError
    try:
        item = planilhas_registro.registrar_planilha_criada(info.get("titulo") or "Planilha", info["id"])
    except (ValueError, OSError, ArquivoJsonCorrompidoError) as exc:
        log.warning("  ⚠ A planilha foi criada, mas não deu para cadastrá-la em 'Planilhas do Drive': %s", exc)
        return
    if item:
        log.info("  Cadastrada em 'Planilhas do Drive' (id %s).", item["id"])


def _imprimir_resumo(r: Resumo, simulacao: bool) -> None:
    log.info("")
    log.info("═" * 60)
    log.info("  RESUMO%s", " (SIMULAÇÃO: nada foi gravado)" if simulacao else "")
    log.info("  ➕ %s: %d", "Seriam adicionados" if simulacao else "Adicionados", r.adicionados)
    log.info("  ✏ %s: %d", "Seriam atualizados" if simulacao else "Atualizados", r.atualizados)
    log.info("  🔄 Transferidos (novos): %d", r.transferidos)
    log.info("  = Sem mudança: %d", r.sem_mudanca)
    for erro in r.erros:
        log.warning("  ✗ %s", erro)
    log.info("═" * 60)


# ══════════════════════════════════════════════════════════════════════════
# PONTO DE ENTRADA (plano "sync" em registro_scripts.py)
# ══════════════════════════════════════════════════════════════════════════

def contar_alunos(turmas: dict, turmas_selecionadas=None) -> tuple[int, int, int]:
    """(turmas, matriculados, transferidos) do que seria sincronizado."""
    alvo = list(turmas_selecionadas) if turmas_selecionadas else list(turmas)
    alunos = [a for t in alvo for a in turmas.get(t, [])]
    transf = sum(1 for a in alunos if eh_transferido(a))
    return len(alvo), len(alunos) - transf, transf


def descrever_sincronizacao(turmas: dict, turmas_selecionadas=None) -> str:
    n_turmas, matr, transf = contar_alunos(turmas, turmas_selecionadas)
    return f"{matr + transf} aluno(s) em {n_turmas} turma(s): {matr} matriculado(s) e {transf} transferido(s) (os dois grupos entram)."


def executar_planilha_google(operacao: str, planilha: str = "", nome: str = "", turmas: dict | None = None,
                             turmas_selecionadas=None, simulacao: bool = False) -> dict:
    """
    criar     → cria a planilha `nome` (uma aba por turma escolhida, com cabeçalhos) e preenche com os alunos;
                guarda o ID para a próxima vez.
    atualizar → sincroniza a planilha `planilha` (ID ou link; vazio = a última usada).
    verificar → confere acesso e abas (não grava).
    Com `simulacao`, lê e mostra o que mudaria sem gravar nem criar nada. Falha (exceção) se algo não deu certo.
    """
    from src.comum import configuracao
    if operacao not in OPERACOES:
        raise gs.SheetsValidacaoErro(f"Operação '{operacao}' desconhecida: use {', '.join(OPERACOES)}.")
    turmas = turmas or {}
    mapa = mapa_abas()
    alvo = list(turmas_selecionadas) if turmas_selecionadas else list(turmas)

    # Pedidos inválidos são recusados ANTES de autenticar (nada de navegador à toa).
    if operacao == "criar":
        if not str(nome or "").strip():
            raise gs.SheetsValidacaoErro("Informe o nome da nova planilha.")
        if not alvo:
            raise gs.SheetsValidacaoErro("Nenhuma turma para colocar na planilha: execute primeiro a automação 'Turmas'.")
    else:
        planilha = planilha or configuracao.planilha_google_id()
        if not planilha:
            raise gs.SheetsValidacaoErro("Informe o link ou o ID da planilha.")
        gs.extrair_id_planilha(planilha)
        if operacao == "atualizar" and not turmas:
            raise gs.SheetsValidacaoErro("Ainda não existe turmas.json: execute primeiro a automação 'Turmas'.")

    servico = gs.abrir_servico()

    if operacao == "verificar":
        info = gs.verificar_planilha(planilha, servico=servico)
        log.info("✓ Planilha '%s' acessível. Abas: %s", info["titulo"], ", ".join(info["abas"]))
        log.info("  %s", info["url"])
        return info

    if operacao == "criar":
        abas = list(dict.fromkeys(mapa.get(t, t) for t in alvo))
        if simulacao:
            log.info("SIMULAÇÃO: seria criada a planilha '%s' com as abas: %s.", nome.strip(), ", ".join(abas))
            planilha = None
        else:
            info = gs.criar_planilha(nome, {aba: CABECALHOS for aba in abas}, servico=servico)
            configuracao.definir_planilha_google(info["id"])
            log.info("✓ Planilha criada: %s", info["titulo"])
            log.info("  Link: %s", info["url"])
            _salvar_no_cadastro(info)
            planilha = info["id"]
        resumo = Resumo()
        if planilha:                                            # recém-criada: o preenchimento usa o mesmo motor
            resumo = sincronizar_turmas(turmas, planilha, turmas_selecionadas=alvo, simulacao=False, servico=servico, mapa=mapa)
            _imprimir_resumo(resumo, False)
        resultado = {"id": planilha, "resumo": resumo}
    else:
        resumo = sincronizar_turmas(turmas, planilha, turmas_selecionadas=alvo, simulacao=simulacao, servico=servico, mapa=mapa)
        _imprimir_resumo(resumo, simulacao)
        if not simulacao:
            configuracao.definir_planilha_google(gs.extrair_id_planilha(planilha))
        resultado = {"id": gs.extrair_id_planilha(planilha), "resumo": resumo}

    if resultado["resumo"].erros:
        raise gs.SheetsErro(f"Concluído com {len(resultado['resumo'].erros)} problema(s): " + "; ".join(resultado["resumo"].erros))
    return resultado

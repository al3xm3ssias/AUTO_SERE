"""
pareceres_digitalizados.py — pareceres do Fundamental digitalizados: ler o QR, arquivar, enviar ao SERE e por e-mail
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
O parecer gerado por `parecer_fund` leva no fim um QR criptografado (AUTOSERE|PF2|…) com ano letivo, nº da chamada, nome,
turma e CGM (os antigos, AUTOSERE|PF|<ano>|<CGM>, também são lidos). Depois de impresso, preenchido,
assinado e digitalizado, esta rotina fecha o ciclo (a leitura do QR é a mesma de pareceres_transferidos.py):

    dados/<ano>/PARECERES/_PROCESSAR/*.pdf|jpg|png…            (digitalizados, um parecer por arquivo)
        1. lê o QR → ano + CGM → acha o aluno no turmas.json (o ano do QR tem de ser o ano letivo em uso)
        2. copia para  dados/<ano>/PARECERES/<turma>/<nº da chamada> - <nome>.<ext>   (nunca sobrescreve)
        3. se passa do limite do SERE, comprime (o original fica em ORIGINAIS_ANTES_DA_COMPRESSAO)
        4. anota em dados/<ano>/pareceres_digitalizados.json e tira o arquivo de _PROCESSAR
           (só depois de 2–4 darem certo)
    5. (opcional) envia ao SERE (pasta virtual, item "Parecer Descritivo <ano>-1"; o idtipo vem do catálogo do sistema e,
       para um ano que ainda não está lá, é descoberto no próprio SERE na 1ª vez e guardado em
       dados/sere_slots_descobertos.json, sem precisar mexer no código) o que ainda não foi enviado
    6. (opcional) manda por e-mail ao responsável, com o PDF em anexo, o que ainda não foi mandado

O que já foi enviado fica registrado no controle e não se repete (SERE e e-mail). Se um parecer é digitalizado de novo,
o arquivo novo substitui o do SERE na próxima execução; o e-mail não é reenviado sozinho.

E-mail — três modos (o padrão é não enviar):
    nao      não manda e-mail
    teste    manda UM e-mail, com [TESTE] no assunto, só para o endereço de teste (padrão: o remetente), com o PDF do
             primeiro parecer; não registra nada
    enviar   manda ao responsável de cada aluno (um e-mail por endereço), com intervalo entre os envios e no máximo
             LIMITE_EMAILS_POR_EXECUCAO por execução; registra cada envio; quem não tem e-mail válido fica na lista
             "sem e-mail" do resumo
Simulação: faz tudo só para mostrar — lê os QR, diz onde cada arquivo seria salvo, quem receberia o quê e a prévia do
e-mail; não copia, comprime, apaga, grava, abre o SERE nem envia e-mail.
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.comum import compressao, paths as _paths
from src.comum.arquivos_json import carregar_json, salvar_json_atomico

PASTA_ENTRADA = "_PROCESSAR"
NOME_CONTROLE = "pareceres_digitalizados.json"
INTERVALO_EMAIL_S = 3.0                      # pausa entre um e-mail e o seguinte
LIMITE_EMAILS_POR_EXECUCAO = 100             # o Gmail limita o envio diário; quem ficar de fora sai na próxima execução

MODOS_EMAIL = {
    "nao": "Não enviar e-mail",
    "teste": "Só teste (1 e-mail, para o endereço de teste)",
    "enviar": "Enviar ao responsável de cada aluno",
}
MARCADORES = ("ALUNO", "TURMA", "ESCOLA", "ANO", "RESPONSAVEL")
ASSUNTO_PADRAO = "Parecer descritivo de $ALUNO — $ANO"
MENSAGEM_PADRAO = (
    "Prezado(a) responsável $RESPONSAVEL,\n\n"
    "Segue em anexo o parecer descritivo de $ALUNO, da turma $TURMA, referente ao ano letivo de $ANO.\n\n"
    "Em caso de dúvidas, procure a secretaria da escola.\n\n"
    "Atenciosamente,\n$ESCOLA"
)
_RE_MARCADOR = re.compile(r"\$([A-Za-z_]+)")
_EXTENSOES_PADRAO = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".pdf"}


# ───────────────────────────── pastas e controle ─────────────────────────────

def pasta_pareceres(ano: Optional[str] = None) -> Path:
    from src.automacao import parecer_fund as pf
    return pf.pasta_pareceres(ano)


def pasta_entrada(ano: Optional[str] = None) -> Path:
    return pasta_pareceres(ano) / PASTA_ENTRADA


def arquivo_controle(ano: Optional[str] = None) -> Path:
    return pasta_pareceres(ano).parent / NOME_CONTROLE


def carregar_controle(ano: Optional[str] = None) -> dict:
    """{cgm: {nome, turma, numero, arquivo, digitalizado_em, sere:{...}, email:{...}}}. {} se ainda não existe."""
    return carregar_json(arquivo_controle(ano), dict, dict)


def salvar_controle(controle: dict, ano: Optional[str] = None) -> None:
    caminho = arquivo_controle(ano)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    salvar_json_atomico(caminho, controle)


def nome_do_slot_do_parecer(ano) -> str:
    """Nome do item do SERE para o parecer do ano: "Parecer Descritivo <ano>-1" (vale para qualquer ano, também os próximos)."""
    return f"Parecer Descritivo {ano}-1"


NOME_SLOTS_DESCOBERTOS = "sere_slots_descobertos.json"


def arquivo_slots_descobertos() -> Path:
    return _paths.DADOS_DIR / NOME_SLOTS_DESCOBERTOS


def carregar_slots_descobertos() -> dict:
    """{nome do item: {"idtipo", "descoberto_em"}} dos itens que o sistema já achou no SERE. {} se ainda não há."""
    try:
        dados = carregar_json(arquivo_slots_descobertos(), dict, dict)
    except Exception:                                       # noqa: BLE001 — arquivo ilegível: volta a procurar no SERE
        return {}
    return {k: v for k, v in dados.items() if isinstance(v, dict) and str(v.get("idtipo", "")).strip()}


def guardar_slot_descoberto(nome_slot: str, idtipo: str) -> None:
    """Anota o idtipo achado no SERE para não procurar de novo (nem em outra execução, nem no ano seguinte ao reabrir)."""
    dados = carregar_slots_descobertos()
    dados[nome_slot] = {"idtipo": str(idtipo), "descoberto_em": datetime.now().isoformat(timespec="seconds")}
    caminho = arquivo_slots_descobertos()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    salvar_json_atomico(caminho, dados)


def slot_sere_do_parecer(ano) -> tuple[Optional[str], str]:
    """
    (idtipo, nome do item). O idtipo vem do catálogo do sistema (SERE_SLOTS: hoje 2025-1 e 2026-1) ou, para um ano que
    ainda não está lá, do que o sistema já descobriu no SERE em outra execução (sere_slots_descobertos.json). Se não
    há em nenhum dos dois, vem None, e `enviar_ao_sere` descobre o idtipo no próprio SERE, procurando esse nome na
    pasta virtual, e guarda.
    """
    from src.comum.sere_normalizacao import SERE_SLOTS
    nome = nome_do_slot_do_parecer(ano)
    for idtipo, info in SERE_SLOTS.items():
        if info.get("nome") == nome:
            return str(idtipo), nome
    achado = carregar_slots_descobertos().get(nome)
    return (str(achado["idtipo"]), nome) if achado else (None, nome)


async def descobrir_idtipo_no_sere(page, cgm: str, nome_slot: str) -> Optional[str]:
    """
    Procura `nome_slot` na pasta virtual do aluno (a mesma listagem que `obter_slots_api` usa) e devolve o idtipo daquele
    item. Compara o nome com qualquer campo de texto de cada entrada (sem diferenciar maiúsculas e acentos), porque o
    campo exato do nome não é conhecido. Se mais de uma entrada bater (ambíguo) ou nenhuma, devolve None: nunca chuta.
    """
    from src.comum.sere_upload import URL_API_LISTAR
    from src.comum.sere_utils import norm

    entradas = await page.evaluate(f"""
        async () => {{
            const resp = await fetch('{URL_API_LISTAR}{cgm}', {{credentials: 'include'}});
            if (!resp.ok) return null;
            return await resp.json();
        }}
    """)
    if not isinstance(entradas, list):
        return None
    alvo = norm(nome_slot)
    achados = {str(e.get("idtipodocumento", "")).strip() for e in entradas if isinstance(e, dict)
               and str(e.get("idtipodocumento", "")).strip()
               and any(isinstance(v, str) and norm(v) == alvo for v in e.values())}
    return achados.pop() if len(achados) == 1 else None


# ───────────────────────────── resumo ─────────────────────────────

@dataclass
class ResumoDigitalizados:
    simulacao: bool = False
    processados: list = field(default_factory=list)      # (arquivo, destino)
    erros: list = field(default_factory=list)            # (arquivo ou aluno, motivo)
    comprimidos: int = 0
    ainda_grandes: int = 0
    sere_enviados: list = field(default_factory=list)    # CGMs
    sere_pulados: list = field(default_factory=list)
    sere_erros: list = field(default_factory=list)       # (cgm, motivo)
    emails_enviados: list = field(default_factory=list)  # (cgm, [endereços])
    emails_sem_endereco: list = field(default_factory=list)   # CGMs
    emails_erros: list = field(default_factory=list)     # (cgm, motivo)


# ───────────────────────────── 1–4: processar a pasta ─────────────────────────────

def _destino_livre(base: Path) -> Path:
    """`base`, ou `base (2)`, `base (3)`… se já existir: um parecer já arquivado nunca é sobrescrito."""
    if not base.exists():
        return base
    n = 2
    while True:
        candidato = base.with_name(f"{base.stem} ({n}){base.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def _relativo(caminho: Path, base: Path) -> str:
    try:
        return caminho.relative_to(base).as_posix()
    except ValueError:
        return str(caminho)


def processar_entrada(simulacao: bool = False, limite_mb: Optional[float] = None, modo_teste: bool = False,
                      ano: Optional[str] = None, dados_dir: Optional[Path] = None,
                      log: Callable[[str], None] = print) -> ResumoDigitalizados:
    """Passos 1–4 (ler o QR, arquivar, comprimir e anotar). Ver o cabeçalho do módulo."""
    from src.automacao import parecer_fund as pf
    from src.automacao import pareceres_transferidos as pt

    ano = str(ano or _paths.ano_atual())
    dados = Path(dados_dir) if dados_dir is not None else _paths.dados_ano_atual()
    entrada = pasta_entrada(ano)
    base = pasta_pareceres(ano)
    limite = compressao.LIMITE_SERE_MB if limite_mb is None else limite_mb
    limite_bytes = int(limite * 1024 * 1024)
    resumo = ResumoDigitalizados(simulacao=simulacao)

    arquivos = sorted(f for f in entrada.glob("*") if f.is_file() and f.suffix.lower() in _EXTENSOES_PADRAO) if entrada.exists() else []
    if not arquivos:
        log(f"Nenhum parecer digitalizado para processar em: {entrada}")
        return resumo
    if modo_teste:
        arquivos = arquivos[:1]
        log("⚠️  MODO TESTE — só o primeiro arquivo")

    turmas_json = dados / "turmas.json"
    if not turmas_json.exists():
        raise FileNotFoundError(f"{turmas_json} não encontrado — rode 'Turmas' antes.")
    turmas_data = carregar_json(turmas_json, dict, dict)
    controle = carregar_controle(ano)

    rotulo = "🧪 SIMULAÇÃO — nada será copiado, comprimido, apagado nem gravado" if simulacao else "Processando pareceres digitalizados"
    log(f"{'='*60}\n  {rotulo}\n  Origem : {entrada}\n  Destino: {base}\n  Limite : {limite:g} MB\n{'='*60}")
    log(f"{len(arquivos)} arquivo(s) encontrado(s).")

    for arq in arquivos:
        log(f"\n── {arq.name}")
        texto = pt.ler_qr_arquivo(arq, log)
        if not texto:
            resumo.erros.append((arq.name, "QR code não encontrado"))
            log("  ERRO: QR code não encontrado.")
            continue
        ident, motivo = pt.identificar_pelo_texto_do_qr(texto, turmas_data, ano, preferir_transferido=False)
        if ident is None:
            resumo.erros.append((arq.name, motivo))
            log(f"  ERRO: {motivo}.")
            continue
        log(f"  Aluno: {ident.nome} (chamada {ident.numero}, CGM {ident.cgm}) — {ident.turma}")

        pasta_turma = base / ident.turma
        destino = _destino_livre(pf.caminho_do_parecer(pasta_turma, ident.nome, ident.cgm, ident.numero).with_suffix(arq.suffix.lower()))
        tamanho = arq.stat().st_size
        if simulacao:
            log(f"  Seria salvo em: {destino}")
            log(f"  Tamanho: {compressao.formatar_tamanho(tamanho)} → "
                f"{'seria comprimido (passa do limite)' if tamanho > limite_bytes else 'cabe no limite, sem compressão'}")
            resumo.processados.append((arq.name, str(destino)))
            continue

        try:
            pasta_turma.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arq, destino)
            if destino.stat().st_size != tamanho:
                destino.unlink(missing_ok=True)
                raise OSError("a cópia não conferiu com o original")
        except OSError as exc:
            resumo.erros.append((arq.name, f"falha ao copiar: {exc}"))
            log(f"  ERRO ao copiar: {exc}")
            continue
        log(f"  Salvo em: {destino}")

        resultado = pt._comprimir_no_lugar(destino, limite_bytes, base, dados / compressao.PASTA_ORIGINAIS, log)
        resumo.comprimidos += resultado in ("comprimido", "ainda_grande")
        resumo.ainda_grandes += resultado in ("ainda_grande", "sem_ganho", "erro")
        if resultado in ("sem_ganho", "erro", "ainda_grande"):
            log(f"  ⚠️  Continua acima de {limite:g} MB — o SERE pode recusar. Escaneie de novo com menor resolução.")

        anterior = controle.get(ident.cgm) or {}
        registro = {"nome": ident.nome, "turma": ident.turma, "numero": ident.numero,
                    "arquivo": _relativo(destino, base), "digitalizado_em": datetime.now().isoformat(timespec="seconds"),
                    "sere": {}, "email": anterior.get("email") or {}}            # arquivo novo: vai de novo ao SERE; e-mail não repete
        if anterior.get("arquivo") and anterior["arquivo"] != registro["arquivo"]:
            log("  ℹ️  Este aluno já tinha um parecer digitalizado: o novo substitui o do SERE no próximo envio "
                "(o e-mail já mandado não é reenviado).")
        controle[ident.cgm] = registro
        salvar_controle(controle, ano)
        arq.unlink()                                    # só chega aqui com a cópia conferida e anotada
        resumo.processados.append((arq.name, str(destino)))

    log(f"\n{'='*60}\n  RESUMO: {len(resumo.processados)} processado(s), {len(resumo.erros)} com erro, "
        f"{resumo.comprimidos} comprimido(s), {resumo.ainda_grandes} ainda acima do limite")
    for nome, motivo in resumo.erros:
        log(f"    • {nome}: {motivo}")
    log("=" * 60)
    return resumo


# ───────────────────────────── seleção do que enviar ─────────────────────────────

def _confere_filtros(registro: dict, cgm: str, turmas: Iterable[str], cgms: Iterable[str]) -> bool:
    turmas, cgms = list(turmas or []), {str(c).strip() for c in (cgms or [])}
    if cgms and cgm not in cgms:
        return False
    return not turmas or registro.get("turma") in turmas


def _arquivo_do_registro(registro: dict, ano: Optional[str] = None) -> Optional[Path]:
    rel = registro.get("arquivo")
    if not rel:
        return None
    caminho = Path(rel)
    return caminho if caminho.is_absolute() else pasta_pareceres(ano) / caminho


def pendentes_sere(controle: dict, ano: Optional[str] = None, turmas: Iterable[str] = (), cgms: Iterable[str] = ()) -> tuple[list, list]:
    """([(cgm, registro, arquivo)] a enviar, [(cgm, motivo)] sem arquivo). Já enviado e não alterado depois não entra."""
    pendentes, sem_arquivo = [], []
    for cgm, reg in controle.items():
        if not _confere_filtros(reg, cgm, turmas, cgms):
            continue
        arquivo = _arquivo_do_registro(reg, ano)
        if arquivo is None or not arquivo.exists():
            sem_arquivo.append((cgm, f"arquivo não encontrado ({reg.get('arquivo')})"))
            continue
        anexado = (reg.get("sere") or {}).get("anexado_em")
        if anexado:
            try:
                if datetime.fromtimestamp(arquivo.stat().st_mtime) <= datetime.fromisoformat(anexado) + timedelta(seconds=1):
                    continue                              # já enviado e o arquivo não mudou (1 s de folga para o relógio do disco)
            except ValueError:
                pass
        pendentes.append((cgm, reg, arquivo))
    return pendentes, sem_arquivo


def pendentes_email(controle: dict, ano: Optional[str] = None, turmas: Iterable[str] = (), cgms: Iterable[str] = ()) -> list:
    """[(cgm, registro, arquivo)] que ainda não receberam o parecer por e-mail (e cujo arquivo existe)."""
    saida = []
    for cgm, reg in controle.items():
        if not _confere_filtros(reg, cgm, turmas, cgms) or (reg.get("email") or {}).get("enviado_em"):
            continue
        arquivo = _arquivo_do_registro(reg, ano)
        if arquivo is not None and arquivo.exists():
            saida.append((cgm, reg, arquivo))
    return saida


# ───────────────────────────── 5: SERE ─────────────────────────────

@asynccontextmanager
async def _sessao_sere():
    """Navegador logado no SERE (a mesma abertura de sessão de sere_2026.modo_transferidos)."""
    from src.automacao import sere_2026 as s
    async with s.async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await page.goto(s.URL)
        await page.fill("#CHAVE", s.LOGIN)
        await page.fill("#CHAVE_ENCRIPT", s.SENHA)
        await page.click("//input[@value='Entrar']")
        await page.wait_for_timeout(3_000)
        await s.navegar_por_aluno(page)
        try:
            yield page
        finally:
            await browser.close()


async def enviar_ao_sere(tarefas: list, controle: dict, ano: str, resumo: ResumoDigitalizados,
                         sessao=_sessao_sere, log: Callable[[str], None] = print) -> None:
    """
    Envia cada parecer da lista `tarefas` [(cgm, registro, arquivo)] para o slot "Parecer Descritivo <ano>-1" do
    aluno, como sere_2026.modo_transferidos faz com os transferidos: slot vazio → envia; ocupado por outro documento →
    substitui; já é o nosso e não mudou → pula. Grava sere.anexado_em no controle a cada envio que dá certo.
    """
    from src.automacao import sere_2026 as s

    idtipo, nome_slot = slot_sere_do_parecer(ano)
    if idtipo is None:
        log(f"\nℹ️  '{nome_slot}' ainda não é conhecido pelo sistema: o idtipo será procurado no SERE, na pasta virtual do primeiro aluno, e guardado.")
    async with sessao() as page:
        for i, (cgm, reg, arquivo) in enumerate(tarefas, 1):
            log(f"\n  [{i:02d}/{len(tarefas)}] {reg.get('nome')} (CGM {cgm}) — {reg.get('turma')}\n           Arquivo: {arquivo.name}")
            abriu = False
            try:
                if not await s.navegar_pasta_virtual(page, cgm):
                    resumo.sere_erros.append((cgm, "falha ao abrir a pasta virtual"))
                    log("     ❌ Falha ao abrir a pasta virtual")
                    continue
                abriu = True
                if idtipo is None:
                    idtipo = await descobrir_idtipo_no_sere(page, cgm, nome_slot)
                    if idtipo is None:
                        resumo.sere_erros.append((cgm, f"o SERE não mostra o item '{nome_slot}' na pasta virtual deste aluno"))
                        log(f"     ❌ O item '{nome_slot}' não aparece (ou aparece mais de uma vez) na pasta virtual. "
                            f"Confira no SERE se o item do ano existe e se o nome é exatamente esse.")
                        continue
                    try:
                        guardar_slot_descoberto(nome_slot, idtipo)
                        guardado = f"Guardado em {NOME_SLOTS_DESCOBERTOS}: não será procurado de novo."
                    except OSError as exc:                  # noqa: BLE001 — só deixa de lembrar; o envio continua
                        guardado = f"(não foi possível guardar o idtipo: {exc})"
                    log(f"     ✅ Item '{nome_slot}' encontrado no SERE: idtipo {idtipo}. {guardado}")
                hash_upload, existentes = await s.obter_slots_api(page, cgm)
                ja_no_sere = idtipo in existentes
                nome_no_sere = (await s.obter_nomes_slots_api(page, cgm)).get(idtipo) if ja_no_sere else None
                decisao, motivo = s.decidir_envio_slot(ja_no_sere, nome_no_sere, reg.get("sere") or {}, arquivo)
                if ja_no_sere:
                    log(f"     ℹ️  {motivo}")
                if decisao == "pular":
                    resumo.sere_pulados.append(cgm)
                    log("     ⏭️  Já está no SERE — pulando")
                    continue
                hash_doc = (await s.excluir_slot_e_obter_hash(page, cgm, nome_slot, idtipo, existentes[idtipo])
                            if ja_no_sere else hash_upload.get(idtipo))
                if not hash_doc:
                    resumo.sere_erros.append((cgm, f"hash não encontrado para [{idtipo}] {nome_slot}"))
                    log(f"     ❌ Hash não encontrado para [{idtipo}] {nome_slot}")
                    continue
                sucesso, msg = await s.injetar_e_enviar(page, hash_doc, arquivo)
                log(f"     {'✅' if sucesso else '❌'} {nome_slot}: {msg}")
                if not sucesso:
                    resumo.sere_erros.append((cgm, msg))
                    continue
                reg_sere = {"anexado_em": datetime.now().isoformat()}      # com fração de segundo: o arquivo, gravado antes, nunca parece mais novo
                try:
                    nome_final = (await s.obter_nomes_slots_api(page, cgm)).get(idtipo)
                    if nome_final:
                        reg_sere["nome_no_sere"] = nome_final
                except Exception as exc:                  # noqa: BLE001 — só ajuda a reconhecer o nosso depois
                    log(f"     ⚠ Não foi possível ler o nome do arquivo no SERE: {exc}")
                reg["sere"] = reg_sere
                salvar_controle(controle, ano)
                resumo.sere_enviados.append(cgm)
            except Exception as exc:                      # noqa: BLE001 — um aluno com erro não derruba os outros
                resumo.sere_erros.append((cgm, str(exc)))
                log(f"     ❌ Erro inesperado: {exc}")
            finally:
                try:
                    if not abriu:
                        continue                            # nem chegou à pasta virtual: não há para onde voltar
                    voltar = await page.query_selector("a[href*='AoClicarVoltar']")
                    if voltar:
                        await voltar.click()
                    else:
                        await page.go_back()
                    await page.wait_for_timeout(1_500)
                except Exception as exc:                  # noqa: BLE001
                    log(f"     ⚠ Erro ao voltar: {exc}")


# ───────────────────────────── 6: e-mail ─────────────────────────────

def conferir_marcadores(texto: str, onde: str) -> None:
    desconhecidos = sorted({m for m in _RE_MARCADOR.findall(texto or "") if m not in MARCADORES})
    if desconhecidos:
        raise ValueError(f"{onde}: marcador(es) desconhecido(s) " + ", ".join("$" + m for m in desconhecidos)
                         + ". Os que valem aqui: " + ", ".join("$" + m for m in MARCADORES) + ".")


def _renderizar(texto: str, contexto: dict) -> str:
    return _RE_MARCADOR.sub(lambda m: str(contexto.get(m.group(1), m.group(0))), texto)


def emails_do_responsavel(cgm: str, dados_dir: Optional[Path] = None) -> tuple[list[str], str]:
    """
    (endereços válidos, nome do responsável) do aluno. Procura em alunos.json ("Email Responsável") e, se não achar, no
    alunos_completo.json ("email_responsavel"); também aceita vários endereços no mesmo campo.
    """
    from src.automacao import avisos as av
    from src.comum.alunos_unificados import indexar_completo

    dados = Path(dados_dir) if dados_dir is not None else _paths.dados_ano_atual()
    basico = carregar_json(dados / "alunos.json", list, list) if (dados / "alunos.json").exists() else []
    completo = indexar_completo(carregar_json(dados / "alunos_completo.json", dict, dict)) if (dados / "alunos_completo.json").exists() else {}
    cgm = str(cgm).strip()
    reg_b = next((a for a in basico if isinstance(a, dict) and str(a.get("CGM", "")).strip() == cgm), {})
    reg_c = completo.get(cgm, {})
    responsavel = str(reg_b.get("Responsável") or reg_c.get("nome_responsavel") or reg_b.get("Mãe") or reg_c.get("nome_mae") or "").strip()
    for bruto in (reg_b.get("Email Responsável"), reg_c.get("email_responsavel")):
        achados = av.extrair_emails(bruto)
        if achados:
            return achados, responsavel
    return [], responsavel


def montar_email(reg: dict, ano: str, responsavel: str, assunto: str, mensagem: str, escola_nome: str) -> tuple[str, str]:
    contexto = {"ALUNO": reg.get("nome", ""), "TURMA": reg.get("turma", ""), "ESCOLA": escola_nome, "ANO": str(ano),
                "RESPONSAVEL": responsavel or "responsável"}
    return _renderizar(assunto, contexto), _renderizar(mensagem, contexto)


def _nome_da_escola() -> str:
    try:
        from src.comum import escola
        return " ".join(str(escola.nome() or "").split())
    except Exception:                                     # noqa: BLE001 — sem o nome, o texto sai com o marcador vazio
        return ""


def enviar_emails(tarefas: list, controle: dict, ano: str, modo: str, resumo: ResumoDigitalizados, assunto: str,
                  mensagem: str, email_teste: str = "", simulacao: bool = False, dados_dir: Optional[Path] = None,
                  enviar: Optional[Callable] = None, pausa: Optional[Callable[[float], None]] = None,
                  log: Callable[[str], None] = print) -> None:
    """
    Passo 6. `tarefas`: [(cgm, registro, arquivo)]. `enviar(destinatario, assunto, corpo, anexos=[...])` devolve
    (ok, erro) — o padrão é src.automacao.envia_email.enviar_email; `pausa(segundos)` o intervalo entre e-mails.
    """
    if modo == "nao" or not tarefas:
        return
    from src.automacao import avisos as av
    if enviar is None:
        from src.automacao.envia_email import enviar_email as enviar
    pausa = pausa or time.sleep
    escola_nome = _nome_da_escola()

    if modo == "teste":
        destino = (email_teste or "").strip() or str(av.credenciais.EMAIL_REMETENTE or "").strip()
        if not av.email_valido(destino):
            raise ValueError("Informe um endereço de e-mail de teste válido (ou configure o remetente em credenciais/.env).")
        cgm, reg, arquivo = tarefas[0]
        enderecos, resp = emails_do_responsavel(cgm, dados_dir)
        titulo, corpo = montar_email(reg, ano, resp, assunto, mensagem, escola_nome)
        titulo = f"[TESTE] {titulo}"
        corpo = f"[TESTE — o responsável real seria: {', '.join(enderecos) or 'sem e-mail cadastrado'}]\n\n{corpo}"
        log(f"\n✉️  E-MAIL DE TESTE → {destino}\n   Assunto: {titulo}\n   Anexo  : {arquivo.name}")
        if simulacao:
            log("   (simulação: não enviado)\n" + corpo)
            return
        ok, erro = enviar(destino, titulo, corpo, anexos=[arquivo])
        log("   ✅ Enviado." if ok else f"   ❌ {erro}")
        if not ok:
            resumo.emails_erros.append((cgm, erro or "falha ao enviar"))
        return

    # modo == "enviar"
    if not simulacao and not av._credenciais_email_ok():
        raise ValueError("O e-mail da escola ainda não está configurado (EMAIL_REMETENTE e EMAIL_SENHA_APP em credenciais/.env).")
    lote = tarefas[:LIMITE_EMAILS_POR_EXECUCAO]
    if len(tarefas) > len(lote):
        log(f"\nℹ️  {len(tarefas)} e-mails pendentes; esta execução manda {len(lote)} (limite por execução). "
            f"Rode de novo para os {len(tarefas) - len(lote)} restantes.")
    log(f"\n✉️  {'SIMULAÇÃO DE ' if simulacao else ''}ENVIO POR E-MAIL — {len(lote)} aluno(s)")
    primeiro_envio = True
    for cgm, reg, arquivo in lote:
        enderecos, resp = emails_do_responsavel(cgm, dados_dir)
        if not enderecos:
            resumo.emails_sem_endereco.append(cgm)
            log(f"   • {reg.get('nome')} (CGM {cgm}): sem e-mail válido do responsável — não enviado")
            continue
        titulo, corpo = montar_email(reg, ano, resp, assunto, mensagem, escola_nome)
        if simulacao:
            log(f"   • {reg.get('nome')} (CGM {cgm}) receberia em: {', '.join(enderecos)}  [{arquivo.name}]")
            continue
        enviados, falhas = [], []
        for endereco in enderecos:
            if not primeiro_envio:
                pausa(INTERVALO_EMAIL_S)
            primeiro_envio = False
            ok, erro = enviar(endereco, titulo, corpo, anexos=[arquivo])
            (enviados if ok else falhas).append(endereco if ok else (endereco, erro))
        if enviados:
            reg["email"] = {"enviado_em": datetime.now().isoformat(timespec="seconds"), "para": enviados}
            if falhas:
                reg["email"]["falhou_para"] = [e for e, _ in falhas]
            salvar_controle(controle, ano)
            resumo.emails_enviados.append((cgm, enviados))
            log(f"   ✅ {reg.get('nome')} (CGM {cgm}) → {', '.join(enviados)}")
        for endereco, erro in falhas:
            resumo.emails_erros.append((cgm, f"{endereco}: {erro}"))
            log(f"   ❌ {reg.get('nome')} (CGM {cgm}) → {endereco}: {erro}")


# ───────────────────────────── rotina completa ─────────────────────────────

async def executar_pareceres_digitalizados(simulacao: bool = False, enviar_sere: bool = False, email_modo: str = "nao",
                                           email_teste: str = "", assunto: str = ASSUNTO_PADRAO,
                                           mensagem: str = MENSAGEM_PADRAO, limite_mb: Optional[float] = None,
                                           modo_teste: bool = False, turmas: Iterable[str] = (),
                                           cgms: Iterable[str] = ()) -> ResumoDigitalizados:
    """A rotina completa (ver o cabeçalho do módulo). `turmas`/`cgms` limitam o que é enviado ao SERE e por e-mail."""
    if email_modo not in MODOS_EMAIL:
        raise ValueError(f"Modo de e-mail inválido: '{email_modo}'. Use: {', '.join(MODOS_EMAIL)}.")
    assunto, mensagem = assunto or ASSUNTO_PADRAO, mensagem or MENSAGEM_PADRAO
    conferir_marcadores(assunto, "Assunto")
    conferir_marcadores(mensagem, "Mensagem")
    ano = str(_paths.ano_atual())
    resumo = processar_entrada(simulacao=simulacao, limite_mb=limite_mb, modo_teste=modo_teste, ano=ano)
    controle = carregar_controle(ano)

    if enviar_sere:
        tarefas, sem_arquivo = pendentes_sere(controle, ano, turmas, cgms)
        for cgm, motivo in sem_arquivo:
            resumo.erros.append((cgm, motivo))
        if modo_teste:
            tarefas = tarefas[:1]
        print(f"\n📤 Envio dos pareceres ao SERE — {len(tarefas)} pendente(s)")
        if simulacao:
            for cgm, reg, arquivo in tarefas:
                print(f"     • {reg.get('nome')} (CGM {cgm}, {reg.get('turma')})  ←  {arquivo}")
        elif tarefas:
            await enviar_ao_sere(tarefas, controle, ano, resumo)

    if email_modo != "nao":
        tarefas = pendentes_email(controle, ano, turmas, cgms)
        if modo_teste:
            tarefas = tarefas[:1]
        if not tarefas:
            print("\n✉️  Nenhum parecer pendente de e-mail.")
        else:
            enviar_emails(tarefas, controle, ano, email_modo, resumo, assunto, mensagem, email_teste, simulacao)

    print(f"\n{'='*60}\n  RESUMO GERAL"
          f"\n   Pareceres processados : {len(resumo.processados)}"
          f"\n   SERE                  : {len(resumo.sere_enviados)} enviado(s), {len(resumo.sere_pulados)} já estavam, {len(resumo.sere_erros)} com erro"
          f"\n   E-mail                : {len(resumo.emails_enviados)} enviado(s), {len(resumo.emails_sem_endereco)} sem e-mail, {len(resumo.emails_erros)} com erro"
          f"\n{'='*60}")
    if resumo.emails_sem_endereco:
        print("   Sem e-mail do responsável (CGM): " + ", ".join(resumo.emails_sem_endereco))
    return resumo

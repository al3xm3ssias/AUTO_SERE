"""
pareceres_transferidos.py — pareceres dos transferidos numa rotina só
════════════════════════════════════════════════════════════════════════════
Une o antigo processa-parecer.py (ler o QR e identificar o aluno) e o comprimir_pareceres.py (reduzir
ao limite do SERE) com o envio ao SERE (sere_2026.modo_transferidos):

    TRANSFERENCIAS/PROCESSAMENTO DE PARECERES/*.pdf|jpg|png…   (digitalizados, com o QR do parecer)
        1. lê o QR e acha o aluno no turmas.json (QR novo AUTOSERE|PF|ano|CGM, do parecer_fund, ou o antigo com nome + turma)
        2. copia para  TRANSFERENCIAS/PARECERES/<turma>/NN-NOME.ext
        3. se passa do limite do SERE, comprime (o original fica em ORIGINAIS_ANTES_DA_COMPRESSAO)
        4. marca parecer.digitalizado_em em transferidos.json
        5. tira o arquivo de PROCESSAMENTO DE PARECERES (só depois de 2–4 darem certo)
    6. envia ao SERE (pasta virtual, slot "Parecer Descritivo") o que está em PARECERES e ainda não foi enviado

Simulação: lê os QR e mostra, para cada arquivo, quem é, onde seria salvo e se seria comprimido — sem copiar,
comprimir, apagar, gravar nem abrir o SERE.

Dependências de leitura de QR (só são importadas quando esta rotina roda):
    pip install opencv-python-headless zxing-cpp pypdfium2
(pdf2image + poppler, pyzbar e qreader também são usados se estiverem instalados.)
════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

from src.comum import compressao
from src.comum.arquivos_json import salvar_json_atomico
from src.comum import pastas_transferencias as _pastas

EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".pdf"}
DPIS_PDF = (200, 300, 150, 400)

# QR → chave real do turmas.json (nomes "Integral" da escola do usuário). Serve de atalho: a busca por palavras
# (resolver_turma) já resolve a maioria sem isto, e variações novas podem ser acrescentadas, sem mexer no código,
# em config/config_usuario.json: "mapeamento_turmas_qr": {"INF 4 A": "INFANTIL 4 Integral A"}. Chaves em MAIÚSCULO.
MAPEAMENTO_TURMAS: dict[str, str] = {
    "INFANTIL 4 A": "INFANTIL 4 Integral A", "INFANTIL4 A": "INFANTIL 4 Integral A",
    "INF 4 A": "INFANTIL 4 Integral A", "INF4 A": "INFANTIL 4 Integral A",
    "INFANTIL 5 A": "INFANTIL 5 Integral A", "INFANTIL5 A": "INFANTIL 5 Integral A",
    "INF 5 A": "INFANTIL 5 Integral A", "INF5 A": "INFANTIL 5 Integral A",
    **{f"{n}º ANO {t}": f"{n}º Ano Integral {t}" for n in range(1, 6) for t in "AB"},
    **{f"{n} ANO {t}": f"{n}º Ano Integral {t}" for n in range(1, 6) for t in "AB"},
    **{f"{n}ANO {t}": f"{n}º Ano Integral {t}" for n in range(1, 6) for t in "AB"},
}


class DependenciaAusente(RuntimeError):
    """Falta uma biblioteca para ler o QR code (a mensagem diz o que instalar)."""


# ══════════════════════════════════════════════════════════════════════════
# LEITURA DE QR (portado de processa-parecer.py; bibliotecas carregadas só quando usadas)
# ══════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def _deps() -> SimpleNamespace:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise DependenciaAusente("Para ler o QR dos pareceres falta o OpenCV. Instale com: "
                                 "pip install opencv-python-headless zxing-cpp pypdfium2") from exc

    d = SimpleNamespace(cv2=cv2, np=np, pyzbar=None, zxing=None, qreader=None, pdf2image=None, pdfium=None)
    try:
        from pyzbar import pyzbar
        d.pyzbar = pyzbar
    except Exception:                                    # noqa: BLE001 — falta a lib ou a DLL do zbar
        pass
    try:
        import zxingcpp
        d.zxing = zxingcpp
    except ImportError:
        pass
    try:
        from qreader import QReader
        d.qreader = QReader()
    except Exception:                                    # noqa: BLE001 — opcional e pesada
        pass
    d.opencv_qr = cv2.QRCodeDetector()

    poppler = os.environ.get("POPPLER_PATH") or None
    if shutil.which("pdftoppm") or poppler:
        try:
            import pdf2image
            d.pdf2image, d.poppler = pdf2image, poppler
        except ImportError:
            pass
    if d.pdf2image is None:
        try:
            import pypdfium2
            d.pdfium = pypdfium2
        except ImportError:
            pass
    d.leitores_nomes = [n for n, ok in (("pyzbar", d.pyzbar), ("zxingcpp", d.zxing), ("opencv", True),
                                        ("qreader", d.qreader)) if ok]
    d.pdf_ok = d.pdf2image is not None or d.pdfium is not None
    return d


def _limpar_bytes(raw: bytes) -> Optional[str]:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            texto = re.sub(r"[^\x20-\x7E]", "", raw.decode(enc))
            if texto.strip():
                return texto.strip()
        except Exception:                                # noqa: BLE001
            continue
    return None


def _variantes(img) -> list:
    d = _deps(); cv2 = d.cv2
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    _, otsu = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt = cv2.adaptiveThreshold(cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(cinza)
    nitida = cv2.addWeighted(cinza, 1.5, cv2.GaussianBlur(cinza, (0, 0), 3), -0.5, 0)
    return [img, cinza, otsu, adapt, clahe, nitida]


LADO_MAXIMO_AMPLIADO = 4000      # px: ampliar além disso só gasta memória/tempo (o original ampliava até 3× sem limite)


def _variantes_escaladas(img, escalas=(2, 3, 1.5)) -> list:
    """Variantes ampliadas; pula as escalas que passariam de LADO_MAXIMO_AMPLIADO no lado maior."""
    cv2 = _deps().cv2
    lado = max(img.shape[:2])
    saida = []
    for e in escalas:
        if lado * e > LADO_MAXIMO_AMPLIADO:
            continue
        saida.extend(_variantes(cv2.resize(img, None, fx=e, fy=e, interpolation=cv2.INTER_CUBIC)))
    return saida


def _ler_pyzbar(img):
    d = _deps()
    if not d.pyzbar:
        return None
    try:
        qrs = d.pyzbar.decode(img)
        return _limpar_bytes(qrs[0].data) if qrs else None
    except Exception:                                    # noqa: BLE001
        return None


def _ler_zxing(img):
    d = _deps()
    if not d.zxing:
        return None
    try:
        rgb = d.cv2.cvtColor(img, d.cv2.COLOR_BGR2RGB) if len(img.shape) == 3 else img
        r = d.zxing.read_barcodes(rgb)
        return r[0].text.strip() if r and r[0].text.strip() else None
    except Exception:                                    # noqa: BLE001
        return None


def _ler_opencv(img):
    d = _deps()
    try:
        bgr = d.cv2.cvtColor(img, d.cv2.COLOR_GRAY2BGR) if len(img.shape) == 2 else img
        ok, textos, _, _ = d.opencv_qr.detectAndDecodeMulti(bgr)
        if ok and textos:
            return next((t.strip() for t in textos if t.strip()), None)
    except Exception:                                    # noqa: BLE001
        pass
    return None


def _ler_qreader(img):
    d = _deps()
    if not d.qreader:
        return None
    try:
        rgb = d.cv2.cvtColor(img, d.cv2.COLOR_GRAY2RGB if len(img.shape) == 2 else d.cv2.COLOR_BGR2RGB)
        for r in d.qreader.detect_and_decode(image=rgb) or []:
            if r and r.strip():
                return r.strip()
    except Exception:                                    # noqa: BLE001
        pass
    return None


def ler_qr_imagem(img, log: Callable[[str], None] = print) -> Optional[str]:
    """Cascata pyzbar → zxingcpp → opencv → qreader, primeiro na imagem e variantes; depois ampliada."""
    leitores = [("pyzbar", _ler_pyzbar), ("zxingcpp", _ler_zxing), ("opencv", _ler_opencv), ("qreader", _ler_qreader)]
    for rodada, variantes in (("original", _variantes(img)), ("ampliada", None)):
        if variantes is None:
            variantes = _variantes_escaladas(img)
            if not variantes:
                break                                   # página já grande: ampliar não ajuda
            log("    Tentando com imagens ampliadas...")
        for nome, leitor in leitores:
            for v in variantes:
                texto = leitor(v)
                if texto:
                    log(f"    [OK] Lido com {nome} (imagem {rodada})")
                    return texto
    return None


def _ultima_pagina(caminho: Path, dpi: int):
    """Última página do PDF como imagem BGR (numpy). Usa pdf2image/poppler se houver; senão pypdfium2."""
    d = _deps()
    if d.pdf2image is not None:
        from pdf2image import convert_from_path, pdfinfo_from_path
        total = pdfinfo_from_path(str(caminho), poppler_path=d.poppler)["Pages"]
        imgs = convert_from_path(str(caminho), dpi=dpi, first_page=total, last_page=total, poppler_path=d.poppler)
        pil, total_paginas = (imgs[0] if imgs else None), total
    elif d.pdfium is not None:
        pdf = d.pdfium.PdfDocument(str(caminho))
        total_paginas = len(pdf)
        pil = pdf[total_paginas - 1].render(scale=dpi / 72).to_pil()
        pdf.close()
    else:
        raise DependenciaAusente("Para ler PDFs falta um renderizador. Instale com: pip install pypdfium2 "
                                 "(ou pdf2image + poppler)")
    if pil is None:
        return None, total_paginas
    return d.cv2.cvtColor(d.np.array(pil.convert("RGB")), d.cv2.COLOR_RGB2BGR), total_paginas


def ler_qr_arquivo(caminho: Path, log: Callable[[str], None] = print) -> Optional[str]:
    """Texto do QR do arquivo (PDF: última página; imagem: ela inteira). None se não achou."""
    d = _deps()
    if caminho.suffix.lower() == ".pdf":
        for dpi in DPIS_PDF:
            img, total = _ultima_pagina(caminho, dpi)
            if img is None:
                continue
            if dpi == DPIS_PDF[0]:
                log(f"  Páginas: {total} — lendo a última")
            log(f"  Tentando DPI {dpi}...")
            texto = ler_qr_imagem(img, log)
            if texto:
                return texto
        return None
    dados = d.np.fromfile(str(caminho), dtype=d.np.uint8)              # imread falha com acentos no Windows
    img = d.cv2.imdecode(dados, d.cv2.IMREAD_COLOR)
    return ler_qr_imagem(img, log) if img is not None else None


# ══════════════════════════════════════════════════════════════════════════
# IDENTIFICAÇÃO DO ALUNO
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Identificacao:
    numero: object
    nome: str
    turma: str
    cgm: str


def _limpar(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9\s]", "", t)).upper().strip()


def _mapeamento() -> dict[str, str]:
    """Mapeamento embutido + o que o usuário acrescentou em config/config_usuario.json ("mapeamento_turmas_qr")."""
    try:
        from src.comum.configuracao import carregar_configuracao
        extra = carregar_configuracao().get("mapeamento_turmas_qr") or {}
    except Exception:                                    # noqa: BLE001 — configuração ilegível não impede a leitura
        extra = {}
    return {**MAPEAMENTO_TURMAS, **{str(k).upper().strip(): str(v) for k, v in extra.items()}}


def _casa_por_palavras(qr: str, chave: str) -> bool:
    """Toda palavra do QR aparece na chave (inteira; ou como início, se tiver 3+ letras: "INF" → "INFANTIL")."""
    palavras_chave = _limpar(chave).split()
    palavras_qr = _limpar(qr).split()
    return bool(palavras_qr) and all(
        any(k == q or (len(q) >= 3 and k.startswith(q)) for k in palavras_chave) for q in palavras_qr)


def resolver_turma(turmas_data: dict, turma_qr: str) -> Optional[str]:
    """
    Turma do QR → chave real do turmas.json. Ordem: mapeamento explícito (embutido + config), igualdade,
    palavras do QR contidas na chave (só se der UMA turma: com mais de uma, não adivinha), substring.
    Nada aqui assume nomes de turma de uma escola específica.
    """
    chaves = [k for k, v in turmas_data.items() if isinstance(v, list)]
    explicita = _mapeamento().get(turma_qr.upper().strip())
    if explicita in chaves:
        return explicita
    limpa = _limpar(turma_qr)
    for chave in chaves:
        if chave == turma_qr or limpa == _limpar(chave):
            return chave
    por_palavras = [c for c in chaves if _casa_por_palavras(turma_qr, c)]
    if len(por_palavras) == 1:
        return por_palavras[0]
    if len(por_palavras) > 1:
        return None                                      # ambíguo (ex.: "3 ANO" com turmas A e B)
    for chave in chaves:
        if limpa and limpa in _limpar(chave):
            return chave
    for chave in chaves:
        if _limpar(chave) and _limpar(chave) in limpa:
            return chave
    return None


def identificar_aluno(turmas_data: dict, nome_qr: str, turma_qr: str) -> tuple[Optional[Identificacao], str]:
    """
    (Identificacao, "") ou (None, motivo). Se o aluno aparece em mais de um registro da turma (transferido e
    depois matriculado de novo, com outra chamada), vale o registro TRANSFERIDO: é dele o parecer.
    """
    from src.comum.registros_aluno import eh_transferido

    turma = resolver_turma(turmas_data, turma_qr)
    if turma is None:
        return None, f"turma '{turma_qr}' não encontrada no turmas.json"
    alvo = _limpar(nome_qr)
    linhas = turmas_data[turma]
    for exato in (True, False):
        achados = [a for a in linhas if (_limpar(a.get("Nome", "")) == alvo if exato
                                         else alvo in _limpar(a.get("Nome", "")) or _limpar(a.get("Nome", "")) in alvo)]
        if achados:
            achados.sort(key=lambda a: not eh_transferido(a.get("Situação", "")))     # transferido primeiro
            a = achados[0]
            return Identificacao(a.get("N"), a.get("Nome", ""), turma, str(a.get("CGM", "")).strip()), ""
    return None, f"aluno '{nome_qr}' não encontrado na turma '{turma}'"


def identificar_por_cgm(turmas_data: dict, cgm: str, preferir_transferido: bool = True) -> tuple[Optional[Identificacao], str]:
    """
    (Identificacao, "") ou (None, motivo), procurando o CGM em todas as turmas. Com o mesmo CGM em mais de um registro
    (transferido e depois matriculado de novo), `preferir_transferido` escolhe qual vale: o transferido (padrão: é dele
    o parecer dos transferidos) ou o que não é transferido.
    """
    from src.comum.registros_aluno import eh_transferido

    cgm = str(cgm or "").strip()
    achados = [(turma, a) for turma, linhas in turmas_data.items() if isinstance(linhas, list)
               for a in linhas if str(a.get("CGM", "")).strip() == cgm]
    if not achados:
        return None, f"CGM {cgm} não encontrado no turmas.json"
    achados.sort(key=lambda ta: eh_transferido(ta[1].get("Situação", "")) != preferir_transferido)
    turma, a = achados[0]
    return Identificacao(a.get("N"), a.get("Nome", ""), turma, cgm), ""


def identificar_pelo_texto_do_qr(texto: str, turmas_data: dict, ano: str,
                                 preferir_transferido: bool = True) -> tuple[Optional[Identificacao], str]:
    """
    Do texto lido no QR até o aluno. Aceita os dois formatos que existem:
      * novo, gerado pelo parecer_fund:  AUTOSERE|PF|<ano>|<CGM>   (confere o ano e acha o aluno pelo CGM)
      * antigo, do processa-parecer.py:  {"nome": "...", "turma": "..."}
    Devolve (Identificacao, "") ou (None, motivo).
    """
    from src.automacao import parecer_fund as pf

    payload = pf.ler_payload_qr(texto)
    if payload:
        if payload["ano"] != str(ano):
            return None, f"parecer de {payload['ano']}, mas o ano letivo em uso é {ano}"
        return identificar_por_cgm(turmas_data, payload["cgm"], preferir_transferido)
    try:
        qr = json.loads(texto)
        nome_qr, turma_qr = str(qr.get("nome", "")).strip(), str(qr.get("turma", "")).strip()
    except (ValueError, AttributeError):
        return None, "QR não é de um parecer (nem AUTOSERE|PF|ano|CGM, nem o JSON antigo com nome e turma)"
    if not nome_qr or not turma_qr:
        return None, "QR sem nome ou turma"
    return identificar_aluno(turmas_data, nome_qr, turma_qr)


def nome_do_arquivo(numero, nome: str, extensao: str) -> str:
    base = f"{str(numero).zfill(2)}-{nome}{extensao}"
    for c in '<>:"/\\|?*':
        base = base.replace(c, "_")
    return base


def _destino_livre(pasta: Path, numero, nome: str, extensao: str) -> Path:
    destino = pasta / nome_do_arquivo(numero, nome, extensao)
    contador = 1
    while destino.exists():                              # nunca sobrescreve um parecer já arquivado
        destino = pasta / nome_do_arquivo(numero, f"{nome}_{contador}", extensao)
        contador += 1
    return destino


# ══════════════════════════════════════════════════════════════════════════
# COMPRESSÃO E CONTROLE (transferidos.json)
# ══════════════════════════════════════════════════════════════════════════

def _comprimir_no_lugar(arquivo: Path, limite_bytes: int, raiz: Path, pasta_originais: Path,
                        log: Callable[[str], None]) -> str:
    """'cabe' | 'comprimido' | 'ainda_grande' | 'sem_ganho' | 'erro'. O original é guardado antes de substituir."""
    antes = arquivo.stat().st_size
    if antes <= limite_bytes:
        return "cabe"
    temporario = arquivo.with_name(arquivo.name + compressao.SUFIXO_TEMPORARIO)
    try:
        if arquivo.suffix.lower() == ".pdf":
            depois = compressao.comprimir_pdf(arquivo, temporario, limite_bytes, log)
        else:
            depois = compressao.comprimir_imagem(arquivo, temporario, limite_bytes)
        if depois > antes * (1 - compressao.GANHO_MINIMO):
            log(f"    Compressão sem ganho útil ({compressao.formatar_tamanho(antes)}); mantido como está.")
            return "sem_ganho" if antes > limite_bytes else "cabe"
        compressao._copiar_original(arquivo, raiz, pasta_originais)
        st = arquivo.stat()
        os.replace(temporario, arquivo)
        os.utime(arquivo, ns=(st.st_atime_ns, st.st_mtime_ns))
        log(f"    Comprimido: {compressao.formatar_tamanho(antes)} → {compressao.formatar_tamanho(depois)}")
        return "ainda_grande" if depois > limite_bytes else "comprimido"
    except (compressao.CompressaoImpossivel, OSError) as exc:
        log(f"    ⚠ Não foi possível comprimir: {exc}")
        return "erro"
    finally:
        temporario.unlink(missing_ok=True)


def _marcar_digitalizado(cgm: str, dados_dir: Path) -> str:
    """parecer.digitalizado_em = agora em transferidos.json. 'ok' | 'sem_registro' | 'sem_arquivo'."""
    caminho = dados_dir / "transferidos.json"
    if not caminho.exists():
        return "sem_arquivo"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if cgm not in dados:
        return "sem_registro"
    dados[cgm].setdefault("parecer", {})["digitalizado_em"] = datetime.now().isoformat()
    salvar_json_atomico(caminho, dados)
    return "ok"


# ══════════════════════════════════════════════════════════════════════════
# ROTINA
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ResumoPareceres:
    processados: list = field(default_factory=list)      # (arquivo, destino)
    erros: list = field(default_factory=list)            # (arquivo, motivo)
    comprimidos: int = 0
    ainda_grandes: int = 0
    sem_registro: list = field(default_factory=list)     # CGMs que não estão em transferidos.json
    simulacao: bool = False


def _ano_da_pasta(dados: Path) -> str:
    """Ano letivo da pasta de dados (dados/<ano>); se a pasta não tem o nome de um ano, o ano em uso."""
    from src.comum import paths as _paths
    return dados.name if re.fullmatch(r"\d{4}", dados.name) else str(_paths.ano_atual())


def processar_pareceres_da_pasta(simulacao: bool = False, limite_mb: Optional[float] = None, modo_teste: bool = False,
                                 dados_dir: Optional[Path] = None, log: Callable[[str], None] = print) -> ResumoPareceres:
    """Passos 1–5 (tudo menos o envio ao SERE). Ver o cabeçalho do módulo."""
    from src.comum import paths as _paths

    dados = Path(dados_dir) if dados_dir is not None else _paths.dados_ano_atual()
    origem = _pastas.subpasta(_pastas.PROCESSAMENTO_PARECERES, dados)
    destino_raiz = _pastas.subpasta(_pastas.PARECERES, dados)
    pasta_originais = dados / compressao.PASTA_ORIGINAIS
    limite = compressao.LIMITE_SERE_MB if limite_mb is None else limite_mb
    limite_bytes = int(limite * 1024 * 1024)
    resumo = ResumoPareceres(simulacao=simulacao)

    if not simulacao:
        _pastas.garantir_pastas(dados)
    arquivos = sorted(f for f in origem.glob("*") if f.is_file() and f.suffix.lower() in EXTENSOES) if origem.exists() else []
    if not arquivos:
        log(f"Nenhum parecer para processar em: {origem}")
        return resumo
    if modo_teste:
        arquivos = arquivos[:1]
        log("⚠️  MODO TESTE — só o primeiro arquivo")

    turmas_json = dados / "turmas.json"
    if not turmas_json.exists():
        raise FileNotFoundError(f"{turmas_json} não encontrado — rode 'Turmas' antes.")
    turmas_data = json.loads(turmas_json.read_text(encoding="utf-8"))

    rotulo = "🧪 SIMULAÇÃO — nada será copiado, comprimido, apagado nem gravado" if simulacao else "Processando pareceres"
    log(f"{'='*60}\n  {rotulo}\n  Origem : {origem}\n  Destino: {destino_raiz}\n  Limite : {limite:g} MB\n{'='*60}")
    log(f"{len(arquivos)} arquivo(s) encontrado(s).")

    for arq in arquivos:
        log(f"\n── {arq.name}")
        texto = ler_qr_arquivo(arq, log)
        if not texto:
            resumo.erros.append((arq.name, "QR code não encontrado"))
            log("  ERRO: QR code não encontrado.")
            continue
        ident, motivo = identificar_pelo_texto_do_qr(texto, turmas_data, _ano_da_pasta(dados))
        if ident is None:
            resumo.erros.append((arq.name, motivo))
            log(f"  ERRO: {motivo}.")
            continue
        log(f"  Aluno: {ident.nome} (chamada {ident.numero}, CGM {ident.cgm}) — {ident.turma}")

        pasta_turma = destino_raiz / ident.turma
        destino = _destino_livre(pasta_turma, ident.numero, ident.nome, arq.suffix)
        tamanho = arq.stat().st_size
        precisa = tamanho > limite_bytes
        if simulacao:
            log(f"  Seria salvo em: {destino}")
            log(f"  Tamanho: {compressao.formatar_tamanho(tamanho)} → "
                f"{'seria comprimido (passa do limite)' if precisa else 'cabe no limite, sem compressão'}")
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

        resultado = _comprimir_no_lugar(destino, limite_bytes, _pastas.pasta_transferencias(dados), pasta_originais, log)
        resumo.comprimidos += resultado in ("comprimido", "ainda_grande")
        resumo.ainda_grandes += resultado in ("ainda_grande", "sem_ganho", "erro")
        if resultado in ("sem_ganho", "erro", "ainda_grande"):
            log(f"  ⚠️  Continua acima de {limite:g} MB — o SERE pode recusar. Escaneie de novo com menor resolução.")

        marcou = _marcar_digitalizado(ident.cgm, dados)
        if marcou == "ok":
            log(f"  transferidos.json: parecer.digitalizado_em (CGM {ident.cgm})")
        else:
            resumo.sem_registro.append(ident.cgm)
            log(f"  AVISO: CGM {ident.cgm} não está em transferidos.json — o parecer foi arquivado, mas não será "
                f"enviado ao SERE (aluno transferido antes da data de corte?).")

        arq.unlink()                                      # só chega aqui com a cópia conferida (e original guardado, se comprimiu)
        resumo.processados.append((arq.name, str(destino)))

    log(f"\n{'='*60}\n  RESUMO: {len(resumo.processados)} processado(s), {len(resumo.erros)} com erro, "
        f"{resumo.comprimidos} comprimido(s), {resumo.ainda_grandes} ainda acima do limite")
    for nome, motivo in resumo.erros:
        log(f"    • {nome}: {motivo}")
    log("=" * 60)
    return resumo


async def executar_pareceres_transferidos(simulacao: bool = False, enviar: bool = True,
                                          limite_mb: Optional[float] = None, modo_teste: bool = False) -> ResumoPareceres:
    """A rotina completa: processa os pareceres e (se `enviar`) manda ao SERE os que estão em PARECERES."""
    resumo = processar_pareceres_da_pasta(simulacao=simulacao, limite_mb=limite_mb, modo_teste=modo_teste)
    if enviar:
        print("\n📤 Envio dos pareceres ao SERE")
        from src.automacao.sere_2026 import modo_transferidos
        await modo_transferidos(modo_teste=modo_teste, tipos=("parecer",), simulacao=simulacao)
    return resumo

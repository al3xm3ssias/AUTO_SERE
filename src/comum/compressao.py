"""
compressao.py — Reduz o tamanho dos documentos digitalizados (PDF, JPG e PNG)
=============================================================================
O SERE recusa arquivos acima de ~1,5 MB (HTTP 500 no upload — ver
src.comum.sere_upload.LIMITE_ARQUIVO_MB_PADRAO). Escaneamentos costumam passar
disso. Este módulo encolhe só o que passa do limite, sem trocar nome, extensão
nem data do arquivo.

COMO COMPRIME
  * JPG/PNG: reduz o maior lado (até 1300 px no último passo) e, no JPG, a qualidade.
  * PDF: reencoda as imagens de cada página (as páginas escaneadas são imagens) e
    compacta a estrutura. PDF só de texto quase não encolhe e é deixado como está.
  * Tenta passos cada vez mais fortes e PARA no primeiro que ficar abaixo do alvo —
    quanto menos perda de qualidade, melhor.

SEGURANÇA (mexe nos documentos dos alunos, então é conservador)
  * O resultado é gravado num arquivo temporário e conferido (abre? mesmas páginas?
    ficou menor?) ANTES de substituir qualquer coisa. Qualquer falha deixa o original intacto.
  * O original é copiado para ORIGINAIS_ANTES_DA_COMPRESSAO (fora da pasta de digitalização,
    para os outros scripts não o tratarem como turma) e a cópia é conferida antes da troca.
  * A data de modificação do arquivo é preservada: o modo --transferidos do sere_2026 usa
    a data dos arquivos como data de corte.
  * Pastas BACKUP* nunca são tocadas.
  * Só troca se economizar pelo menos GANHO_MINIMO; o que não rende fica registrado para
    não ser tentado de novo (e JPG nunca é recomprimido em cima de si mesmo).
  * Cancelar (botão da tela) para entre um arquivo e outro.

A biblioteca pypdf (PDF) é instalada sozinha na primeira vez que for preciso — ver _carregar_pypdf().
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.comum.arquivos_json import carregar_json, salvar_json_atomico
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.sere_normalizacao import norm

EXTENSOES = (".pdf", ".jpg", ".jpeg", ".png")
LIMITE_SERE_MB = 1.5                 # igual a sere_upload.LIMITE_ARQUIVO_MB_PADRAO (há teste conferindo)
GANHO_MINIMO = 0.10                  # só substitui se o arquivo encolher pelo menos 10%
PASTA_ORIGINAIS = "ORIGINAIS_ANTES_DA_COMPRESSAO"
SUFIXO_TEMPORARIO = ".compressao.tmp"
VERSAO_PYPDF = "5.9.0"
# (maior lado em pixels, qualidade JPEG): do mais suave ao mais forte
ETAPAS = ((2400, 80), (2000, 72), (1600, 62), (1300, 50))
_PIXELS_MINIMOS_NO_PDF = 40_000      # imagens menores que isso (logos, linhas) não valem o trabalho


class CompressaoImpossivel(Exception):
    """Este arquivo não pode ser comprimido (protegido, corrompido, resultado inválido...). Vira aviso no log."""


@dataclass
class Resumo:
    """O que aconteceu na execução — o log mostra isto no fim e os testes conferem."""
    encontrados: int = 0
    ja_cabem: int = 0
    ja_processados: int = 0
    comprimidos: int = 0
    sem_ganho: int = 0
    erros: int = 0
    ainda_grandes: int = 0
    bytes_antes: int = 0             # só dos arquivos comprimidos (ou que seriam, em "só calcular")
    bytes_depois: int = 0
    turmas_nao_encontradas: list[str] = field(default_factory=list)

    @property
    def economia(self) -> int:
        return self.bytes_antes - self.bytes_depois


def formatar_tamanho(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f} MB".replace(".", ",")


# ───────────────────────────── imagens ─────────────────────────────

def _reduzir(imagem, lado_max: int):
    from PIL import Image
    largura, altura = imagem.size
    maior = max(largura, altura)
    if maior <= lado_max:
        return imagem
    fator = lado_max / maior
    return imagem.resize((max(1, round(largura * fator)), max(1, round(altura * fator))), Image.LANCZOS)


def comprimir_imagem(origem: Path, destino: Path, alvo_bytes: int) -> int:
    """Grava em `destino` a versão comprimida de um JPG/PNG (mesmo formato do original); devolve o tamanho."""
    from PIL import Image, ImageOps
    jpeg = origem.suffix.lower() in (".jpg", ".jpeg")
    try:
        with Image.open(origem) as aberta:
            imagem = ImageOps.exif_transpose(aberta)       # respeita a rotação gravada pela câmera/scanner
            imagem.load()
    except Exception as exc:                                # noqa: BLE001 — Pillow levanta vários tipos
        raise CompressaoImpossivel(f"imagem ilegível ({type(exc).__name__})") from exc

    tamanho = 0
    for indice, (lado, qualidade) in enumerate(ETAPAS):
        candidata = _reduzir(imagem, lado)
        if jpeg:
            if candidata.mode not in ("RGB", "L"):
                candidata = candidata.convert("RGB")
            candidata.save(destino, "JPEG", quality=qualidade, optimize=True)
        else:
            if indice >= 2:                                  # PNG sem perdas é pesado: nos passos fortes usa 256 cores
                candidata = candidata.convert("RGB").quantize(colors=256)
            candidata.save(destino, "PNG", optimize=True)
        tamanho = destino.stat().st_size
        if tamanho <= alvo_bytes:
            break
    return tamanho


# ───────────────────────────── PDF ─────────────────────────────

def _carregar_pypdf(log: Callable[[str], None] = print):
    """Importa o pypdf; se faltar, instala (uma vez) para a pessoa não precisar abrir terminal."""
    try:
        import pypdf
        return pypdf
    except ImportError:
        pass
    log(f"Instalando o componente de PDF (pypdf {VERSAO_PYPDF}) — só na primeira vez, precisa de internet…")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", f"pypdf=={VERSAO_PYPDF}"],
                           capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompressaoImpossivel(f"não consegui instalar o pypdf: {exc}") from exc
    if r.returncode != 0:
        raise CompressaoImpossivel("não consegui instalar o pypdf (sem internet?). Os PDFs foram pulados; "
                                   "as imagens continuam sendo comprimidas.")
    import importlib
    importlib.invalidate_caches()
    import pypdf
    return pypdf


def _tem_mascara(imagem_pdf) -> bool:
    """Imagem com transparência (/SMask): reescrever perderia a máscara, então fica como está."""
    try:
        return "/SMask" in imagem_pdf.indirect_reference.get_object()
    except Exception:                                        # noqa: BLE001
        return False


def comprimir_pdf(origem: Path, destino: Path, alvo_bytes: int, log: Callable[[str], None] = print) -> int:
    """Grava em `destino` o PDF com as imagens reencodadas; devolve o tamanho. Confere o resultado antes de devolver."""
    pypdf = _carregar_pypdf(log)
    paginas_originais = 0
    tamanho = 0
    for lado, qualidade in ETAPAS:
        try:
            leitor = pypdf.PdfReader(str(origem))
            if leitor.is_encrypted:
                raise CompressaoImpossivel("PDF protegido por senha")
            paginas_originais = len(leitor.pages)
            escritor = pypdf.PdfWriter(clone_from=leitor)
            reencodadas = 0
            for pagina in escritor.pages:
                try:
                    imagens = list(pagina.images)
                except Exception:                            # noqa: BLE001 — página com imagem que o pypdf não lê
                    imagens = []
                for img in imagens:
                    try:
                        pil = img.image
                        if pil is None or pil.width * pil.height < _PIXELS_MINIMOS_NO_PDF or _tem_mascara(img):
                            continue
                        if pil.mode not in ("RGB", "L"):
                            pil = pil.convert("RGB")
                        img.replace(_reduzir(pil, lado), quality=qualidade)
                        reencodadas += 1
                    except Exception:                        # noqa: BLE001 — essa imagem fica como estava
                        continue
                pagina.compress_content_streams()
            escritor.compress_identical_objects(remove_identicals=True, remove_orphans=True)
            with open(destino, "wb") as f:
                escritor.write(f)
        except CompressaoImpossivel:
            raise
        except Exception as exc:                             # noqa: BLE001 — PDF corrompido ou fora do padrão
            raise CompressaoImpossivel(f"PDF não pôde ser processado ({type(exc).__name__}: {exc})") from exc
        tamanho = destino.stat().st_size
        if tamanho <= alvo_bytes or reencodadas == 0:        # sem imagens a reencodar, passos mais fortes não ajudam
            break

    try:
        if len(pypdf.PdfReader(str(destino)).pages) != paginas_originais:
            raise CompressaoImpossivel("o PDF comprimido ficou com número de páginas diferente")
    except CompressaoImpossivel:
        raise
    except Exception as exc:                                 # noqa: BLE001
        raise CompressaoImpossivel(f"o PDF comprimido não abriu ({type(exc).__name__})") from exc
    return tamanho


# ───────────────────────────── seleção dos arquivos ─────────────────────────────

def _pasta_ignorada(nome: str) -> bool:
    maiusculo = nome.upper()
    return maiusculo.startswith("BACKUP") or maiusculo == PASTA_ORIGINAIS


def pastas_das_turmas(raiz: Path, nomes: list[str]) -> tuple[list[Path], list[str]]:
    """(pastas encontradas, nomes sem pasta). Mesma regra de encontrar_pasta_turma (sere_2026)."""
    entradas = [e for e in sorted(raiz.iterdir()) if e.is_dir() and not _pasta_ignorada(e.name)]
    achadas: list[Path] = []
    faltando: list[str] = []
    for nome in nomes:
        n = norm(nome)
        variacoes = [n, n.replace("O ANO", "º ANO"), n.replace("º", "O").replace("ª", "A")]
        pasta = next((e for e in entradas for v in variacoes if norm(e.name) == v or v in norm(e.name) or norm(e.name) in v), None)
        if pasta is None:
            faltando.append(nome)
        elif pasta not in achadas:
            achadas.append(pasta)
    return achadas, faltando


def listar_arquivos(bases: list[Path]) -> list[Path]:
    """Todos os PDF/JPG/PNG sob as bases, sem entrar em pastas BACKUP* nem na de originais."""
    encontrados: list[Path] = []
    for base in bases:
        for pasta, subpastas, arquivos in os.walk(base):
            subpastas[:] = sorted(d for d in subpastas if not _pasta_ignorada(d))
            for nome in sorted(arquivos):
                if nome.lower().endswith(EXTENSOES) and not nome.endswith(SUFIXO_TEMPORARIO):
                    encontrados.append(Path(pasta) / nome)
    return encontrados


def _limpar_temporarios(bases: list[Path]) -> int:
    """Sobras de uma execução interrompida (queda de luz, janela fechada)."""
    n = 0
    for base in bases:
        for pasta, subpastas, arquivos in os.walk(base):
            subpastas[:] = [d for d in subpastas if not _pasta_ignorada(d)]
            for nome in arquivos:
                if nome.endswith(SUFIXO_TEMPORARIO):
                    try:
                        (Path(pasta) / nome).unlink()
                        n += 1
                    except OSError:
                        pass
    return n


# ───────────────────────────── execução ─────────────────────────────

def _assinatura(arquivo: Path) -> dict:
    st = arquivo.stat()
    return {"tamanho": st.st_size, "mtime_ns": st.st_mtime_ns}


def _copiar_original(arquivo: Path, raiz: Path, pasta_originais: Path) -> Path:
    """Guarda o original e confere a cópia. Nunca sobrescreve uma cópia antiga (cria sufixo com data)."""
    destino = pasta_originais / arquivo.relative_to(raiz)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino = destino.with_name(f"{destino.stem}__{datetime.now():%Y%m%d_%H%M%S}{destino.suffix}")
    shutil.copy2(arquivo, destino)
    if destino.stat().st_size != arquivo.stat().st_size:
        destino.unlink(missing_ok=True)
        raise CompressaoImpossivel("a cópia do original não conferiu; nada foi alterado")
    return destino


def comprimir_documentos(
    *,
    raiz: Path,
    pasta_originais: Path,
    registro_json: Path,
    turmas: Optional[list[str]] = None,
    limite_mb: float = LIMITE_SERE_MB,
    guardar_originais: bool = True,
    somente_calcular: bool = False,
    modo_teste: bool = False,
    log: Callable[[str], None] = print,
) -> Resumo:
    """
    Comprime os documentos acima de `limite_mb` (0 = todos). `turmas` vazio/None = a pasta inteira
    (inclui TRANSFERENCIAS). `somente_calcular` não altera nada. `modo_teste` processa só o primeiro candidato.
    """
    raiz = Path(raiz)
    if not raiz.is_dir():
        raise FileNotFoundError(f"Pasta de digitalização não encontrada: {raiz}")
    resumo = Resumo()
    limite_bytes = int(limite_mb * 1024 * 1024)

    if turmas:
        bases, resumo.turmas_nao_encontradas = pastas_das_turmas(raiz, list(turmas))
        for nome in resumo.turmas_nao_encontradas:
            log(f"⚠ Pasta da turma não encontrada, pulada: {nome}")
        if not bases:
            log("Nenhuma pasta de turma encontrada: nada a fazer.")
            return resumo
    else:
        bases = [raiz]

    sobras = _limpar_temporarios(bases)
    if sobras:
        log(f"Removi {sobras} arquivo(s) temporário(s) de uma execução interrompida.")

    registro = carregar_json(registro_json, dict, dict)
    arquivos = listar_arquivos(bases)
    resumo.encontrados = len(arquivos)

    candidatos: list[Path] = []
    for arquivo in arquivos:
        try:
            assinatura = _assinatura(arquivo)
        except OSError:
            continue
        if limite_bytes and assinatura["tamanho"] <= limite_bytes:
            resumo.ja_cabem += 1
            continue
        anterior = registro.get(arquivo.relative_to(raiz).as_posix())
        if anterior and anterior.get("tamanho") == assinatura["tamanho"] and anterior.get("mtime_ns") == assinatura["mtime_ns"]:
            resumo.ja_processados += 1
            continue
        candidatos.append(arquivo)

    acao = "calcular a economia (nada será alterado)" if somente_calcular else "comprimir"
    log(f"{resumo.encontrados} arquivo(s) encontrado(s): {resumo.ja_cabem} já cabem no limite"
        + (f" de {limite_mb:g} MB".replace(".", ",") if limite_bytes else "")
        + f", {resumo.ja_processados} já tratado(s) antes, {len(candidatos)} para {acao}.")
    if modo_teste and candidatos:
        candidatos = candidatos[:1]
        log("Modo de teste: só o primeiro arquivo será processado.")
    if not somente_calcular and guardar_originais and candidatos:
        log(f"Os originais ficam em: {pasta_originais}")

    alvo = limite_bytes or 0
    alterou_registro = False
    try:
        for i, arquivo in enumerate(candidatos, 1):
            verificar_cancelamento()
            rel = arquivo.relative_to(raiz)
            rotulo = f"[{i}/{len(candidatos)}] {rel.as_posix()}"
            antes = arquivo.stat().st_size
            temporario = arquivo.with_name(arquivo.name + SUFIXO_TEMPORARIO)
            try:
                if arquivo.suffix.lower() == ".pdf":
                    depois = comprimir_pdf(arquivo, temporario, alvo, log)
                else:
                    depois = comprimir_imagem(arquivo, temporario, alvo)

                if depois > antes * (1 - GANHO_MINIMO):
                    resumo.sem_ganho += 1
                    log(f"{rotulo}: {formatar_tamanho(antes)} — sem ganho útil, mantido como está.")
                    if not somente_calcular:
                        registro[rel.as_posix()] = {**_assinatura(arquivo), "resultado": "sem_ganho"}
                        alterou_registro = True
                    continue

                resumo.comprimidos += 1
                resumo.bytes_antes += antes
                resumo.bytes_depois += depois
                pct = round((1 - depois / antes) * 100)
                aviso = ""
                if limite_bytes and depois > limite_bytes:
                    resumo.ainda_grandes += 1
                    aviso = "  ⚠ ainda acima do limite do SERE"
                if somente_calcular:
                    log(f"{rotulo}: {formatar_tamanho(antes)} → {formatar_tamanho(depois)} (-{pct}%){aviso}  [simulado]")
                    continue

                if guardar_originais:
                    _copiar_original(arquivo, raiz, pasta_originais)
                st = arquivo.stat()
                os.replace(temporario, arquivo)
                os.utime(arquivo, ns=(st.st_atime_ns, st.st_mtime_ns))     # preserva a data (corte de transferidos)
                registro[rel.as_posix()] = {**_assinatura(arquivo), "resultado": "comprimido", "antes": antes,
                                            "em": datetime.now().isoformat(timespec="seconds")}
                alterou_registro = True
                log(f"{rotulo}: {formatar_tamanho(antes)} → {formatar_tamanho(depois)} (-{pct}%){aviso}")
            except CompressaoImpossivel as exc:
                resumo.erros += 1
                log(f"{rotulo}: ⚠ pulado — {exc}")
            except OSError as exc:
                resumo.erros += 1
                log(f"{rotulo}: ⚠ erro de arquivo ({exc}); o original não foi alterado.")
            finally:
                temporario.unlink(missing_ok=True)
    finally:
        if alterou_registro:
            salvar_json_atomico(registro_json, registro)

    rotulo_economia = "Espaço que seria economizado" if somente_calcular else "Espaço economizado"
    log("=" * 60)
    log(f"Resumo: {resumo.comprimidos} comprimido(s), {resumo.sem_ganho} sem ganho, {resumo.erros} com erro, "
        f"{resumo.ja_cabem} já cabiam, {resumo.ja_processados} já tratados antes.")
    if resumo.comprimidos:
        log(f"{rotulo_economia}: {formatar_tamanho(resumo.economia)} "
            f"({formatar_tamanho(resumo.bytes_antes)} → {formatar_tamanho(resumo.bytes_depois)}).")
    if resumo.ainda_grandes:
        log(f"⚠ {resumo.ainda_grandes} arquivo(s) continuam acima do limite do SERE mesmo comprimidos "
            "(escaneie de novo com menor resolução).")
    return resumo

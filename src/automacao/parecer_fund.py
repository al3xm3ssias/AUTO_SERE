"""
parecer_fund.py — Pareceres do Ensino Fundamental a partir de um modelo Word por turma
=============================================================================
Pedido do usuário (20/10/2026): por enquanto o parecer do Fundamental é UM ARQUIVO (.docx) que o
usuário envia (upload) e o sistema gera, para cada aluno, uma cópia preenchida.

Pastas (a base é a pasta `dados/`; para outro lugar, defina AUTO_SERE_PARECERES_BASE):

    <base>/MODELO/                          os modelos enviados, + controle_modelos.json
    <base>/<ano>/PARECERES/<turma>/         um .docx por aluno:  "<nº da chamada> - <nome>.docx"

Arquivo de controle  <base>/MODELO/controle_modelos.json  — liga cada TURMA ao arquivo de modelo dela:

    {"versao": 1,
     "modelos": {"1º Ano Integral A": {"arquivo": "1º_ANO_-_2026.docx", "atualizado_em": "2026-10-20 14:03:11"},
                 "1º Ano Integral B": {"arquivo": "1º_ANO_-_2026.docx", "atualizado_em": "2026-10-20 14:03:11"}}}

Um mesmo arquivo pode servir a várias turmas (ex.: todas as de 1º ano). Reenviar um arquivo com o mesmo
nome substitui o modelo de TODAS as turmas ligadas a ele.

Marcadores que o modelo pode ter (substituídos mesmo que o Word tenha quebrado o texto em pedaços):
    $ESCOLA   nome da escola SEM o prefixo "Escola Municipal" e em maiúsculas — o modelo já traz
              "ESCOLA MUNICIPAL" escrito antes do marcador (um espaço é inserido se faltar)
    $ALUNO    nome do aluno          $TURMA    nome da turma        $ANO    ano letivo
    $CGM      CGM do aluno           $CHAMADA  número da chamada
O modelo precisa ter, no mínimo, $ALUNO (sem ele todos os pareceres sairiam iguais).

QR code no FIM do arquivo, para pareceres_digitalizados/pareceres_transferidos lerem depois de impresso, preenchido e
digitalizado. O QR leva ano letivo, nº da chamada, nome, turma e CGM, CRIPTOGRAFADOS (a câmera do celular mostra só
um texto embaralhado):

    AUTOSERE|PF2|<texto criptografado>        (ver src/comum/qr_seguro.py; a chave fica em credenciais/chave_qr.key)

Os pareceres antigos, com QR em texto aberto  AUTOSERE|PF|<ano>|<CGM>, continuam sendo lidos (ler_payload_qr lê os dois).

Formato de saída (opção `formato`; padrão em config_usuario.json → "parecer_fund_formato", senão "pdf"):
    pdf     só o PDF, pronto para imprimir, em <base>/<ano>/PARECERES/_PARA_IMPRIMIR/<turma>/  (converte com o LibreOffice;
            fica fora da pasta da turma para não se misturar com o parecer digitalizado, que ganha o mesmo nome lá)
    docx    só o Word, na pasta da turma (como antes)
    ambos   os dois

Segurança do trabalho já feito: um parecer que JÁ EXISTE (o professor pode já ter preenchido) NÃO é
sobrescrito, a não ser que se peça "substituir".
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from src.comum import conversao_pdf, escola, paths, qr_seguro
from src.comum.execucao_gui import verificar_cancelamento
from src.comum.logger import get_logger

log = get_logger(__file__)

NOME_CONTROLE = "controle_modelos.json"
LADO_QR_PX = 150
LADO_QR_SEGURO_PX = 200                              # o QR criptografado tem mais dados: mais módulos, precisa de mais espaço
PREFIXO_QR = "AUTOSERE"
TIPO_QR = "PF"
LIMITE_MODELO_MB = 15
PASTA_PARA_IMPRIMIR = "_PARA_IMPRIMIR"
FORMATOS = {"pdf": "PDF (pronto para imprimir)", "docx": "Word (.docx)", "ambos": "PDF e Word"}
FORMATO_PADRAO = "pdf"
LOTE_PDF = 25                                        # quantos .docx vão por vez ao LibreOffice (abrir leva alguns segundos)
_EMU_POR_PX = 9525                                  # 96 dpi: 1 px = 9525 EMU

_RE_TOKEN = re.compile(r"\$(ESCOLA|ALUNO|TURMA|ANO|CGM|CHAMADA)(?![A-Za-z0-9_])")
_RE_PREFIXO_ESCOLA = re.compile(r"^\s*(?:escola\s+municipal|e\.?\s?m\.?)\s+", re.IGNORECASE)
_RE_NOME_INVALIDO = re.compile(r"[^\w\-. ]+", re.UNICODE)


# ───────────────────────────── pastas e arquivo de controle ─────────────────────────────

def pasta_base() -> Path:
    base = os.getenv("AUTO_SERE_PARECERES_BASE", "").strip()
    return Path(base) if base else paths.DADOS_DIR


def pasta_modelos() -> Path:
    return pasta_base() / "MODELO"


def pasta_pareceres(ano: Optional[str] = None) -> Path:
    return pasta_base() / str(ano or paths.ano_atual()) / "PARECERES"


def pasta_para_imprimir(ano: Optional[str] = None) -> Path:
    return pasta_pareceres(ano) / PASTA_PARA_IMPRIMIR


def arquivo_controle() -> Path:
    return pasta_modelos() / NOME_CONTROLE


def formato_padrao() -> str:
    """O formato configurado em config_usuario.json (\"parecer_fund_formato\"); sem configuração (ou inválido), PDF."""
    try:
        from src.comum.configuracao import carregar_configuracao
        valor = str(carregar_configuracao().get("parecer_fund_formato") or "").strip().lower()
    except Exception:                                    # noqa: BLE001 — configuração ilegível não impede de gerar
        valor = ""
    return valor if valor in FORMATOS else FORMATO_PADRAO


def normalizar_formato(formato: Optional[str]) -> str:
    valor = str(formato or "").strip().lower()
    if not valor:
        return formato_padrao()
    if valor not in FORMATOS:
        raise ValueError(f"Formato de parecer inválido: '{formato}'. Use: {', '.join(FORMATOS)}.")
    return valor


def _slug(texto) -> str:
    return re.sub(r"[^\w\-]+", "_", str(texto)).strip("_")


def nome_seguro_arquivo(nome: str) -> str:
    """Só o nome (sem pastas), sem caracteres problemáticos, terminando em .docx."""
    base = os.path.basename(str(nome).replace("\\", "/")).strip()
    base = re.sub(r"\.docx$", "", base, flags=re.IGNORECASE)
    base = _RE_NOME_INVALIDO.sub("_", base).strip(" ._")
    if not base:
        raise ValueError("O arquivo precisa de um nome.")
    return f"{base[:120]}.docx"


def carregar_controle() -> dict[str, dict]:
    """{turma: {"arquivo", "atualizado_em"}}. Vazio se o controle não existe; ValueError se estiver ilegível."""
    caminho = arquivo_controle()
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        modelos = dados["modelos"]
        if not isinstance(modelos, dict):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"O arquivo de controle {caminho} está ilegível ({exc}). Corrija-o ou apague-o.") from exc
    return {str(t): dict(v) for t, v in modelos.items() if isinstance(v, dict) and v.get("arquivo")}


def _gravar_atomico(destino: Path, conteudo: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_bytes(conteudo)
    os.replace(tmp, destino)


def _salvar_controle(modelos: dict[str, dict]) -> None:
    corpo = {"versao": 1, "modelos": dict(sorted(modelos.items()))}
    _gravar_atomico(arquivo_controle(), json.dumps(corpo, ensure_ascii=False, indent=2).encode("utf-8"))


def modelo_da_turma(turma: str, controle: Optional[dict] = None) -> Optional[Path]:
    """Caminho do modelo ligado à turma (None se não há ligação ou se o arquivo sumiu)."""
    controle = carregar_controle() if controle is None else controle
    entrada = controle.get(turma)
    if not entrada:
        return None
    caminho = pasta_modelos() / entrada["arquivo"]
    return caminho if caminho.is_file() else None


def validar_modelo(conteudo: bytes) -> None:
    """ValueError com mensagem pronta se o arquivo não serve de modelo."""
    if not conteudo:
        raise ValueError("O arquivo está vazio.")
    if len(conteudo) > LIMITE_MODELO_MB * 1024 * 1024:
        raise ValueError(f"O arquivo passa de {LIMITE_MODELO_MB} MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            if sum(i.file_size for i in z.infolist()) > 200 * 1024 * 1024:
                raise ValueError("O arquivo descompactado é grande demais para ser um modelo.")
        doc = Document(io.BytesIO(conteudo))
    except ValueError:
        raise
    except Exception as exc:                                    # noqa: BLE001 — qualquer erro = não é um .docx
        raise ValueError("Esse arquivo não é um documento Word (.docx) válido.") from exc
    if "$ALUNO" not in _texto_do_documento(doc):
        raise ValueError("O modelo não tem o marcador $ALUNO. Escreva $ALUNO onde deve sair o nome do aluno "
                         "(opcionais: $ESCOLA, $TURMA, $ANO, $CGM, $CHAMADA).")


def salvar_modelo(nome_arquivo: str, conteudo: bytes, turmas: Iterable[str]) -> dict:
    """
    Guarda o modelo em MODELO/ e liga as turmas a ele no controle. Devolve
    {"arquivo", "turmas", "substituiu", "turmas_afetadas"} — `turmas_afetadas` são as OUTRAS turmas que já
    usavam esse mesmo arquivo e passam a usar a versão nova.
    """
    turmas = [str(t).strip() for t in turmas if str(t).strip()]
    if not turmas:
        raise ValueError("Escolha pelo menos uma turma para usar este modelo.")
    nome = nome_seguro_arquivo(nome_arquivo)
    validar_modelo(conteudo)

    controle = carregar_controle()
    destino = pasta_modelos() / nome
    substituiu = destino.exists()
    afetadas = sorted(t for t, e in controle.items() if e["arquivo"] == nome and t not in turmas)
    _gravar_atomico(destino, conteudo)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for t in turmas:
        controle[t] = {"arquivo": nome, "atualizado_em": agora}
    _salvar_controle(controle)
    log.info(f"Modelo de parecer salvo: {nome} → {', '.join(turmas)}")
    return {"arquivo": nome, "turmas": turmas, "substituiu": substituiu, "turmas_afetadas": afetadas}


# ───────────────────────────── QR code ─────────────────────────────

def montar_payload_qr(ano, cgm) -> str:
    """Texto gravado no QR do parecer: AUTOSERE|PF|<ano>|<CGM>."""
    cgm = "" if cgm is None else str(cgm).strip()
    if not cgm or not re.fullmatch(r"\w+", cgm):
        raise ValueError(f"CGM inválido para o QR code: '{cgm}'")
    return f"{PREFIXO_QR}|{TIPO_QR}|{ano}|{cgm}"


def montar_payload_qr_seguro(ano, cgm, chamada=None, nome="", turma="") -> str:
    """Texto CRIPTOGRAFADO do QR: ano letivo, nº da chamada, nome, turma e CGM (AUTOSERE|PF2|…). Cria a chave na 1ª vez."""
    return qr_seguro.montar(ano, chamada, nome, turma, cgm)


def ler_payload_qr(texto: str) -> Optional[dict]:
    """
    Lê o texto de um QR de parecer do Fundamental, nos dois formatos:
      * criptografado (AUTOSERE|PF2|…): {"ano","cgm","chamada","nome","turma"}; se não abre (sem a chave, QR alterado ou
        lido pela metade) levanta qr_seguro.QrIlegivel com o motivo;
      * antigo, em texto aberto (AUTOSERE|PF|ano|CGM): {"ano","cgm"}.
    None se o texto não é de um parecer do Fundamental.
    """
    novo = qr_seguro.ler(texto)
    if novo is not None:
        return novo
    m = re.fullmatch(rf"{PREFIXO_QR}\|{TIPO_QR}\|(\d{{4}})\|(\w+)", str(texto or "").strip())
    return {"ano": m.group(1), "cgm": m.group(2)} if m else None


def gerar_qr_png(payload: str, lado: int = LADO_QR_PX, redimensionar: bool = True) -> bytes:
    """
    PNG quadrado de `lado` x `lado` px (150), preto no branco, correção de erro M. Com `redimensionar=False` devolve o
    PNG no tamanho natural (10 px por módulo, bordas perfeitas) e quem usa a imagem define o tamanho na página: é o que
    o QR criptografado faz, porque com muitos módulos um redimensionamento não inteiro deixaria os quadradinhos desiguais.
    """
    import qrcode
    from PIL import Image
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2 if not redimensionar else 1)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")
    if redimensionar:
        img = img.resize((lado, lado), Image.NEAREST)           # bordas nítidas: melhor para leitor de QR
    saida = io.BytesIO()
    img.save(saida, format="PNG")
    return saida.getvalue()


# ───────────────────────────── preenchimento do modelo ─────────────────────────────

def _paragrafos(raiz):
    """Todos os parágrafos de um pedaço do documento (corpo, tabelas aninhadas, caixas de texto, cabeçalho)."""
    return raiz.iter(qn("w:p"))


def _textos_do_paragrafo(p) -> list:
    """Os <w:t> do próprio parágrafo, em ordem (inclui links; não entra em parágrafos aninhados)."""
    return p.xpath("./w:r/w:t | ./w:hyperlink/w:r/w:t")


def _texto_do_documento(doc) -> str:
    partes = [doc.element.body]
    for sec in doc.sections:
        for hf in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
            partes.append(hf._element)
    return "\n".join("".join(t.text or "" for t in _textos_do_paragrafo(p)) for raiz in partes for p in _paragrafos(raiz))


def _nome_curto_escola(nome: str) -> str:
    return _RE_PREFIXO_ESCOLA.sub("", str(nome or "").strip()).strip().upper()


def _substituir_no_paragrafo(p, valores: dict) -> int:
    """
    Troca os marcadores do parágrafo mantendo a formatação do trecho onde o marcador começa. Funciona
    mesmo quando o Word partiu o marcador em vários <w:t> ("$AL" + "UNO"). Devolve quantas trocas fez.
    """
    ts = _textos_do_paragrafo(p)
    if not ts:
        return 0
    achados = list(_RE_TOKEN.finditer("".join(t.text or "" for t in ts)))
    for m in reversed(achados):                                  # de trás para a frente: as posições anteriores não mudam
        textos = [t.text or "" for t in ts]
        completo = "".join(textos)
        novo = str(valores.get(m.group(1), ""))
        if m.start() > 0 and completo[m.start() - 1].isalnum() and novo and not novo[0].isspace():
            novo = " " + novo                                    # "MUNICIPAL$ESCOLA" → "MUNICIPAL NOME"

        pos, i_ini, i_fim, off_ini, off_fim = 0, None, None, 0, 0
        for i, tx in enumerate(textos):
            if i_ini is None and m.start() < pos + len(tx):
                i_ini, off_ini = i, m.start() - pos
            if m.end() <= pos + len(tx):
                i_fim, off_fim = i, m.end() - pos
                break
            pos += len(tx)
        if i_ini is None or i_fim is None:
            continue                                             # não deveria acontecer; não trava
        if i_ini == i_fim:
            ts[i_ini].text = textos[i_ini][:off_ini] + novo + textos[i_ini][off_fim:]
        else:
            ts[i_ini].text = textos[i_ini][:off_ini] + novo
            for k in range(i_ini + 1, i_fim):
                ts[k].text = ""
            ts[i_fim].text = textos[i_fim][off_fim:]
        for k in range(i_ini, i_fim + 1):
            ts[k].set(qn("xml:space"), "preserve")
    return len(achados)


def _remover_paragrafos_vazios_do_fim(doc) -> None:
    """Tira as linhas em branco do fim (sobre elas o QR ganha lugar sem empurrar uma página só para ele)."""
    corpo = doc.element.body
    while True:
        filhos = [f for f in corpo.iterchildren() if f.tag != qn("w:sectPr")]
        if not filhos or filhos[-1].tag != qn("w:p"):
            return
        ultimo = filhos[-1]
        vazio = (not "".join(t.text or "" for t in ultimo.iter(qn("w:t"))).strip()
                 and not ultimo.xpath(".//w:drawing | .//w:pict | .//w:sectPr | .//w:br[@w:type='page']"))
        if not vazio:
            return
        corpo.remove(ultimo)


def preencher_modelo(modelo: bytes, valores: dict, qr_png: Optional[bytes], lado_px: int = LADO_QR_PX) -> bytes:
    """Devolve o .docx preenchido (marcadores trocados, QR de `lado_px` px — 150 por padrão — no fim)."""
    doc = Document(io.BytesIO(modelo))
    raizes = [doc.element.body]
    vistos = set()
    for sec in doc.sections:
        for hf in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
            if id(hf._element) not in vistos:
                vistos.add(id(hf._element))
                raizes.append(hf._element)
    for raiz in raizes:
        for p in _paragrafos(raiz):
            _substituir_no_paragrafo(p, valores)

    if qr_png:
        _remover_paragrafos_vazios_do_fim(doc)
        lado = Emu(lado_px * _EMU_POR_PX)
        doc.add_picture(io.BytesIO(qr_png), width=lado, height=lado)
        doc.paragraphs[-1].paragraph_format.space_before = Pt(10)      # um respiro entre a última linha e o QR
    saida = io.BytesIO()
    doc.save(saida)
    return saida.getvalue()


def caminho_do_parecer(pasta_turma: Path, nome: str, cgm: str, numero_chamada) -> Path:
    """<pasta da turma>/<nº da chamada> - <nome>.docx (sem nº de chamada, usa o CGM)."""
    prefixo = str(numero_chamada).strip() if numero_chamada not in (None, "") else str(cgm)
    return pasta_turma / f"{prefixo} - {_slug(nome) or cgm}.docx"


# ───────────────────────────── seleção e geração ─────────────────────────────

def numero_da_chamada(turmas_json: dict, turma: str, cgm: str):
    for aluno in turmas_json.get(turma, []):
        if str(aluno.get("CGM", "")).strip() == str(cgm):
            return aluno.get("N")
    return None


def montar_alunos(turmas_json: dict, selecionados: Iterable[dict]) -> list[dict]:
    """De alunos da seleção ({"CGM","Nome","Turma"}) para o formato desta automação, com o nº da chamada."""
    return [{"cgm": a["CGM"], "nome": a["Nome"], "turma": a["Turma"],
             "n_chamada": numero_da_chamada(turmas_json, a["Turma"], a["CGM"])} for a in selecionados]


def turmas_com_modelo(nomes_turmas: Iterable[str]) -> list[str]:
    controle = carregar_controle()
    return [t for t in nomes_turmas if modelo_da_turma(t, controle) is not None]


def conferir_modelos(turmas_alvo: Iterable[str], explicitas: bool) -> list[str]:
    """
    Turmas que serão processadas. Se o usuário ESCOLHEU turmas e alguma não tem modelo → ValueError listando
    quais. Se não escolheu (= todas), vale só quem tem modelo (as de Infantil, por exemplo, não têm).
    """
    turmas_alvo = list(turmas_alvo)
    com = turmas_com_modelo(turmas_alvo)
    if explicitas:
        sem = [t for t in turmas_alvo if t not in com]
        if sem:
            raise ValueError("Estas turmas ainda não têm modelo de parecer: " + ", ".join(sem) +
                             ". Envie em Configurações → Modelos de parecer.")
        return com
    if not com:
        raise ValueError("Nenhuma turma tem modelo de parecer ainda. Envie em Configurações → Modelos de parecer.")
    return com


def nome_da_escola_para_o_modelo() -> str:
    nome = escola.nome()
    if not nome:
        raise ValueError("O nome da escola ainda não foi informado (Configurações → Dados da escola).")
    return _nome_curto_escola(nome) or nome.upper()


def _converter_lote(fila: list, saida_tmp: Path, falhas: list, log=print) -> int:
    """
    Converte para PDF os .docx da `fila` [(posição, aluno, docx temporário, destino do PDF)] e grava cada PDF no destino.
    Quem não saiu vira falha. Devolve quantos PDFs foram gravados.
    """
    if not fila:
        return 0
    try:
        resultado = conversao_pdf.docx_para_pdf([f[2] for f in fila], saida_tmp)
    except conversao_pdf.ConversaoPdfErro as exc:
        resultado = {}
        motivo_geral = str(exc)[:200]
    else:
        motivo_geral = "o LibreOffice não gerou o PDF"
    gravados = 0
    for _, a, docx_tmp, destino in fila:
        pdf = resultado.get(docx_tmp)
        if pdf is None:
            falhas.append({"cgm": str(a["cgm"]), "nome": a["nome"], "motivo": motivo_geral})
            log(f"[ERRO] {a['nome']} (CGM {a['cgm']}): {motivo_geral}")
            continue
        _gravar_atomico(destino, pdf.read_bytes())
        gravados += 1
    fila.clear()
    return gravados


def gerar_pareceres_fundamental(alunos: list[dict], substituir: bool = False, ano: Optional[str] = None,
                                formato: Optional[str] = None) -> dict:
    """
    Gera o parecer de cada aluno usando o modelo ligado à turma. `formato`: "pdf" (padrão; vai para
    <base>/<ano>/PARECERES/_PARA_IMPRIMIR/<turma>/), "docx" (<base>/<ano>/PARECERES/<turma>/) ou "ambos".
    `alunos`: [{"cgm","nome","turma","n_chamada"}]. Parecer que já existe é mantido, a menos que `substituir`
    (cada formato é conferido à parte). O QR leva ano, chamada, nome, turma e CGM criptografados.
    Devolve {"total","gerados","ja_existiam","falhas":[{"cgm","nome","motivo"}],"pasta","formato"}.
    """
    if not alunos:
        raise ValueError("Nenhum aluno para gerar o parecer.")
    formato = normalizar_formato(formato)
    quer_docx, quer_pdf = formato in ("docx", "ambos"), formato in ("pdf", "ambos")
    if quer_pdf:
        try:
            conversao_pdf.exigir_soffice()
        except conversao_pdf.ConversaoPdfErro as exc:
            raise ValueError(str(exc)) from exc
    ano = str(ano or paths.ano_atual())
    nome_escola = nome_da_escola_para_o_modelo()
    controle = carregar_controle()
    raiz = pasta_pareceres(ano)
    raiz_pdf = pasta_para_imprimir(ano)
    print(f"Pareceres ({FORMATOS[formato]}) serão salvos em: {raiz_pdf if formato == 'pdf' else raiz}")

    modelos: dict[Path, bytes] = {}
    gerados, existentes, falhas = 0, 0, []
    total = len(alunos)
    fila_pdf: list = []
    with tempfile.TemporaryDirectory(prefix="autosere_parecer_") as tmp_txt:
        tmp = Path(tmp_txt)
        (tmp / "pdf").mkdir()

        def descarregar_fila() -> int:
            """Converte o que está na fila. Só conta como "gerado" o aluno que não teve o Word gravado (esse já foi contado)."""
            if not fila_pdf:
                return 0
            verificar_cancelamento()
            print(f"Convertendo {len(fila_pdf)} parecer(es) para PDF…")
            gravados = _converter_lote(fila_pdf, tmp / "pdf", falhas)
            return 0 if quer_docx else gravados

        for i, a in enumerate(alunos, 1):
            verificar_cancelamento()
            cgm, nome, turma = str(a["cgm"]), a["nome"], a["turma"]
            try:
                modelo = modelo_da_turma(turma, controle)
                if modelo is None:
                    raise ValueError(f"a turma {turma} não tem modelo de parecer")
                pasta = _slug(turma) or "SEM_TURMA"
                destino_docx = caminho_do_parecer(raiz / pasta, nome, cgm, a.get("n_chamada"))
                destino_pdf = raiz_pdf / pasta / destino_docx.with_suffix(".pdf").name
                fazer_docx = quer_docx and (substituir or not destino_docx.exists())
                fazer_pdf = quer_pdf and (substituir or not destino_pdf.exists())
                if not fazer_docx and not fazer_pdf:
                    existentes += 1
                    print(f"[{i}/{total}] {(destino_docx if quer_docx else destino_pdf).name} já existe — mantido.")
                    continue
                if modelo not in modelos:
                    modelos[modelo] = modelo.read_bytes()
                valores = {"ESCOLA": nome_escola, "ALUNO": nome, "TURMA": turma, "ANO": ano, "CGM": cgm,
                           "CHAMADA": "" if a.get("n_chamada") in (None, "") else a["n_chamada"]}
                qr = gerar_qr_png(montar_payload_qr_seguro(ano, cgm, a.get("n_chamada"), nome, turma), redimensionar=False)
                conteudo = preencher_modelo(modelos[modelo], valores, qr, lado_px=LADO_QR_SEGURO_PX)
                if fazer_docx:
                    _gravar_atomico(destino_docx, conteudo)
                    gerados += 1
                if fazer_pdf:
                    docx_tmp = tmp / f"{i:05d}.docx"
                    docx_tmp.write_bytes(conteudo)
                    fila_pdf.append((i, a, docx_tmp, destino_pdf))
                print(f"[{i}/{total}] {turma} — {destino_docx.stem}")
            except Exception as exc:                            # noqa: BLE001 — um aluno com problema não para os demais
                print(f"[{i}/{total}] [ERRO] {nome} (CGM {cgm}): {exc}")
                falhas.append({"cgm": cgm, "nome": nome, "motivo": str(exc)[:200]})
            if len(fila_pdf) >= LOTE_PDF:
                gerados += descarregar_fila()
        gerados += descarregar_fila()

    print(f"\nConcluído: {gerados} parecer(es) gerado(s), {existentes} já existia(m), {len(falhas)} com problema.")
    return {"total": total, "gerados": gerados, "ja_existiam": existentes, "falhas": falhas,
            "pasta": str(raiz_pdf if formato == "pdf" else raiz), "formato": formato}

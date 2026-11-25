#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preenche o REQUERIMENTO_MATRICULA_2027.docx a partir da planilha do Google
(respostas do formulário) e salva um PDF por aluno.

Uso:
    pip install lxml
    python preencher_requerimento.py                       # baixa a planilha pela URL abaixo
    python preencher_requerimento.py --csv respostas.csv   # usa um CSV baixado
    python preencher_requerimento.py --linha 3             # só a 3ª resposta (1 = primeira)
    python preencher_requerimento.py --nome "maria"        # só quem tiver "maria" no nome
    python preencher_requerimento.py --juntar              # gera também um PDF único (precisa de pypdf)

Requisitos: Python 3.8+, lxml e LibreOffice (comando `soffice`) para converter em PDF.
"""
import argparse
import csv
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

from lxml import etree

# ----------------------------------------------------------------------------
# CONFIGURAÇÃO  (ajuste aqui)
# ----------------------------------------------------------------------------
PLANILHA_URL = ("https://docs.google.com/spreadsheets/d/"
                "1aBJCj-yZYIgGZHenmagG-QelY79ponHIcIaOYkXb6ww/edit?resourcekey=&gid=510310807#gid=510310807")
TEMPLATE = "REQUERIMENTO_MATRICULA_2027.docx"
PASTA_SAIDA = "pdfs_matricula"

# Valor da tag $ESCOLA (coloque o nome oficial completo da escola)
ESCOLA = "ESCOLA JUDITH MACEDO SILVEIRA"

# A planilha tem "Responsável 1" e "Responsável 2", mas o modelo tem MÃE / PAI.
# Defina aqui quem é quem (valores: "MAE", "PAI" ou "TUTOR").
# O Responsável 1 também preenche o bloco "Responsável legal" ($NOME_RESP, $V.x ...).
RESP1_PAPEL = "MAE"
RESP2_PAPEL = "PAI"

MARCADO = "X"      # o que entra no lugar da tag quando a opção está marcada
DESMARCADO = " "   # o que entra quando não está

# ----------------------------------------------------------------------------
# TAGS DO MODELO  (mapeadas a partir do .docx)
# ----------------------------------------------------------------------------
TAGS_TEXTO = [
    "ESCOLA", "NOME_ALUNO", "CGM", "DT.N", "N_RG", "N_CIN", "N_CPF",
    "NOME_MAE", "RG_MAE", "CPF_MAE", "TEL_MAE", "PROF_MAE",
    "NOME_PAI", "RG_PAI", "CPF_PAI", "TEL_PAI", "PROF_PAI",
    "NOME_RESP", "DOC_RESP", "CPF_RESP", "TEL_RESP",
    "ENDERECO", "N", "BAIRRO", "CEP", "U.C",
]
TAGS_CHECK = [
    # autodeclaração
    "A", "PD", "B", "PR", "N.R",
    # vínculo do responsável
    "V.P", "V.M", "V.T",
    # tipo de construção / ocupação / moradia
    "ALV", "MAD", "MIS", "CS.P", "CS.C", "CS.A", "CS",
    # concessionária (GEO)
    "CP", "SAN", "N.P",
    # serviços públicos
    "A.E", "I.P", "E.E", "E.S", "C.L",
    # quem mora com o aluno
    "PAI", "TIO", "MAE", "IR", "AVOS", "OUT",
    # itens na moradia
    "BANHEIRO", "FRE", "M.L", "TV", "CEL", "COMP", "RAD", "TAB", "MOTO", "GEL", "BIC", "CARRO",
    # renda
    "S.R", "1S", "1A3", "3A5", "A5", "N.D",
    # internet
    "F.O", "V.S", "4G", "COMPAR", "V.C", "V.R", "PUB", "N.PO",
]
TODAS_TAGS = sorted(set(TAGS_TEXTO) | set(TAGS_CHECK), key=len, reverse=True)
# longest-first evita que $N pegue o começo de $N_RG, $A o de $A5, $COMP o de $COMPAR etc.
TAG_RE = re.compile(r"\$(" + "|".join(re.escape(t) for t in TODAS_TAGS) + ")")
ANY_DOLLAR_RE = re.compile(r"\$[A-Za-z0-9_.]+")

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


# ----------------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def tem(texto, *padroes):
    """True se algum regex (em texto normalizado) casar."""
    t = norm(texto)
    return any(re.search(p, t) for p in padroes)


def so_digitos(s):
    return re.sub(r"\D", "", s or "")


CPF_RE = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")


def extrair_rg(doc):
    """O campo 'Documento (RG e CPF)' traz os dois juntos; tira o CPF e os rótulos."""
    if not doc:
        return ""
    t = CPF_RE.sub(" ", doc)
    t = re.sub(r"(?i)\b(cpf|rg|cin|e|n[ºo°]\.?)\b", " ", t)
    t = re.sub(r"[;/|,]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–:")
    return t or doc.strip()


def separar_endereco(end):
    """'Rua X, 123' -> ('Rua X', '123'). Se não achar número, devolve (end, '')."""
    end = (end or "").strip()
    m = re.match(r"^(.*?)[,\s\-–]+(?:n[ºo°.]*\s*)?(\d+\s?[A-Za-z]?|s/?n)\s*$", end, re.I)
    if m:
        return m.group(1).strip(" ,-–"), m.group(2).strip()
    return end, ""


# ----------------------------------------------------------------------------
# LEITURA DA PLANILHA
# ----------------------------------------------------------------------------
def url_csv(url):
    m = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not m:
        sys.exit("URL de planilha inválida.")
    g = re.search(r"gid=(\d+)", url)
    u = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
    return u + (f"&gid={g.group(1)}" if g else "")


def ler_planilha(csv_path=None):
    if csv_path:
        raw = Path(csv_path).read_text(encoding="utf-8-sig")
    else:
        try:
            with urllib.request.urlopen(url_csv(PLANILHA_URL), timeout=60) as r:
                raw = r.read().decode("utf-8-sig")
        except Exception as e:
            sys.exit(
                f"Não consegui baixar a planilha ({e}).\n"
                "Compartilhe como 'qualquer pessoa com o link' ou baixe em "
                "Arquivo > Fazer download > CSV e rode com --csv arquivo.csv"
            )
        if raw.lstrip().lower().startswith("<!doctype html") or "<html" in raw[:200].lower():
            sys.exit("O Google devolveu uma página de login: a planilha não está pública. "
                     "Use --csv com o arquivo baixado.")
    linhas = list(csv.reader(io.StringIO(raw)))
    if len(linhas) < 2:
        sys.exit("A planilha não tem respostas.")
    return linhas[0], linhas[1:]


class Colunas:
    """Acha colunas pelo texto (normalizado) do cabeçalho."""

    def __init__(self, cab):
        self.cab = [norm(c) for c in cab]

    def idx(self, *needles, inicio=False):
        for i, c in enumerate(self.cab):
            ok = all(n in c for n in needles)
            if inicio:
                ok = c.startswith(needles[0]) and all(n in c for n in needles[1:])
            if ok:
                return i
        return None


def montar_getters(cab):
    C = Colunas(cab)
    mapa = {
        "nome":      C.idx("nome do aluno"),
        "nasc":      C.idx("data de nascimento"),
        "rg":        C.idx("rg do aluno", inicio=True),
        "cor":       C.idx("autodeclaracao"),
        "cpf":       C.idx("cpf do aluno", inicio=True),
        "endereco":  C.idx("rua/endereco"),
        "cep":       C.idx("cep", inicio=True),
        "geo":       C.idx("identificacao geo"),
        "r1_nome":   C.idx("responsavel 1 (nome)", inicio=True),
        "r1_doc":    C.idx("documento do responsavel 1", inicio=True),
        "r1_tel":    C.idx("telefone responsavel 1", inicio=True),
        "r1_cpf":    C.idx("cpf responsavel 1", inicio=True),
        "r1_prof":   C.idx("profissao responsavel 1", inicio=True),
        "r2_nome":   C.idx("responsavel 2 (nome)", inicio=True),
        "r2_doc":    C.idx("documento responsavel 2", inicio=True),
        "r2_tel":    C.idx("telefone responsavel 2", inicio=True),
        "r2_cpf":    C.idx("cpf responsavel 2", inicio=True),
        "r2_prof":   C.idx("profissao responsavel 2", inicio=True),
        "renda":     C.idx("renda familiar"),
        "moradia":   C.idx("tipo de moradia"),
        "ocupacao":  C.idx("forma de ocupacao"),
        "construc":  C.idx("tipo de construcao"),
        "itens":     C.idx("quais itens"),
        "servicos":  C.idx("servicos publicos"),
        "internet":  C.idx("tipo de conexao"),
        "mora_com":  C.idx("quem mora com"),
    }
    faltando = [k for k, v in mapa.items() if v is None]
    if faltando:
        print("AVISO: colunas não encontradas na planilha:", ", ".join(faltando))

    def get(linha, chave):
        i = mapa.get(chave)
        if i is None or i >= len(linha):
            return ""
        return (linha[i] or "").strip()

    return get


# ----------------------------------------------------------------------------
# REGRAS: linha da planilha -> valor de cada tag
# ----------------------------------------------------------------------------
def valores_da_linha(g, avisos):
    v = {}  # tag -> str (texto) ou bool (checkbox)

    # ---- dados do aluno
    v["ESCOLA"] = ESCOLA
    v["NOME_ALUNO"] = g("nome").upper()
    v["DT.N"] = g("nasc")
    v["N_RG"] = g("rg")
    v["N_CPF"] = g("cpf")
    v["CGM"] = ""     # não existe na planilha
    v["N_CIN"] = ""   # não existe na planilha

    # ---- autodeclaração
    cor = g("cor")
    v["A"] = tem(cor, r"amarel")
    v["PD"] = tem(cor, r"pard")
    v["B"] = tem(cor, r"branc")
    v["PR"] = tem(cor, r"pret")
    v["N.R"] = tem(cor, r"nao declar", r"prefiro nao", r"optou", r"nao quer", r"nao sei")
    if cor and not any(v[k] for k in ("A", "PD", "B", "PR", "N.R")) and not tem(cor, r"indigen"):
        avisos.append(f"cor/raça não reconhecida: '{cor}'")

    # ---- responsáveis (R1 -> MAE/PAI/TUTOR conforme configuração)
    r1 = dict(nome=g("r1_nome"), doc=extrair_rg(g("r1_doc")), cpf=g("r1_cpf") or "",
              tel=g("r1_tel"), prof=g("r1_prof"))
    r2 = dict(nome=g("r2_nome"), doc=extrair_rg(g("r2_doc")), cpf=g("r2_cpf") or "",
              tel=g("r2_tel"), prof=g("r2_prof"))
    if not r1["cpf"]:
        m = CPF_RE.search(g("r1_doc"))
        r1["cpf"] = m.group(0) if m else ""
    if not r2["cpf"]:
        m = CPF_RE.search(g("r2_doc"))
        r2["cpf"] = m.group(0) if m else ""

    for papel, r in ((RESP1_PAPEL, r1), (RESP2_PAPEL, r2)):
        if papel in ("MAE", "PAI"):
            v[f"NOME_{papel}"] = r["nome"].upper()
            v[f"RG_{papel}"] = r["doc"]
            v[f"CPF_{papel}"] = r["cpf"]
            v[f"TEL_{papel}"] = r["tel"]
            v[f"PROF_{papel}"] = r["prof"]
    for t in ("NOME", "RG", "CPF", "TEL", "PROF"):   # o que ficar sem dono vira vazio
        v.setdefault(f"{t}_MAE", "")
        v.setdefault(f"{t}_PAI", "")

    # bloco "Responsável legal" = Responsável 1
    v["NOME_RESP"] = r1["nome"].upper()
    v["DOC_RESP"] = r1["doc"]
    v["CPF_RESP"] = r1["cpf"]
    v["TEL_RESP"] = r1["tel"]
    v["V.P"] = RESP1_PAPEL == "PAI"
    v["V.M"] = RESP1_PAPEL == "MAE"
    v["V.T"] = RESP1_PAPEL == "TUTOR"

    # ---- endereço
    rua, num = separar_endereco(g("endereco"))
    v["ENDERECO"] = rua
    v["N"] = num
    v["BAIRRO"] = ""   # não existe na planilha
    v["CEP"] = g("cep")
    geo = g("geo")
    v["U.C"] = geo
    v["CP"] = tem(geo, r"copel")
    v["SAN"] = tem(geo, r"sanepar")
    v["N.P"] = False

    # ---- construção / ocupação / moradia
    c = g("construc")
    v["ALV"] = tem(c, r"alvenaria")
    v["MAD"] = tem(c, r"madeira")
    v["MIS"] = tem(c, r"mista")
    if c and not any(v[k] for k in ("ALV", "MAD", "MIS")):
        avisos.append(f"tipo de construção não reconhecido: '{c}'")

    o = g("ocupacao")
    v["CS.P"] = tem(o, r"propri")
    v["CS.C"] = tem(o, r"ced")
    v["CS.A"] = tem(o, r"alug")
    if o and not any(v[k] for k in ("CS.P", "CS.C", "CS.A")):
        avisos.append(f"forma de ocupação não reconhecida: '{o}'")

    m = g("moradia")
    v["CS"] = tem(m, r"\bcasa\b") and not tem(m, r"casa lar")

    # ---- serviços públicos
    s = g("servicos")
    v["A.E"] = tem(s, r"agua")
    v["I.P"] = tem(s, r"ilumina")
    v["E.E"] = tem(s, r"energia", r"eletric")
    v["E.S"] = tem(s, r"esgoto")
    v["C.L"] = tem(s, r"coleta", r"lixo")

    # ---- quem mora com o aluno
    mc = g("mora_com")
    v["PAI"] = tem(mc, r"\bpais?\b")
    v["MAE"] = tem(mc, r"\bmaes?\b")
    v["TIO"] = tem(mc, r"\btios?\b", r"\btias?\b")
    v["IR"] = tem(mc, r"\birma")
    v["AVOS"] = tem(mc, r"\bavo", r"\bavos\b")
    v["OUT"] = tem(mc, r"\boutros?\b")

    # ---- itens na moradia
    it = g("itens")
    v["BANHEIRO"] = tem(it, r"banheiro")
    v["FRE"] = tem(it, r"freezer")
    v["M.L"] = tem(it, r"lavar", r"lavadora")
    v["TV"] = tem(it, r"televis", r"\btv\b")
    v["CEL"] = tem(it, r"celular")
    v["COMP"] = tem(it, r"computador", r"notebook")
    v["RAD"] = tem(it, r"radio")
    v["TAB"] = tem(it, r"tablet")
    v["MOTO"] = tem(it, r"moto")
    v["GEL"] = tem(it, r"geladeira")
    v["BIC"] = tem(it, r"bicicleta")
    v["CARRO"] = tem(it, r"automovel", r"\bcarro\b")

    # ---- renda
    r = g("renda")
    v["S.R"] = tem(r, r"sem renda")
    v["1S"] = tem(r, r"ate 0?1 sal", r"ate 1 sal")
    v["1A3"] = tem(r, r"0?1 (ate|a) 0?3", r"1 (ate|a) 3")
    v["3A5"] = tem(r, r"0?3 (ate|a) 0?5", r"3 (ate|a) 5")
    v["A5"] = tem(r, r"acima de 0?5", r"mais de 0?5")
    v["N.D"] = tem(r, r"nao declar")
    if r and not any(v[k] for k in ("S.R", "1S", "1A3", "3A5", "A5", "N.D")):
        avisos.append(f"renda não reconhecida: '{r}'")

    # ---- internet
    n = g("internet")
    v["F.O"] = tem(n, r"fibra")
    v["V.S"] = tem(n, r"satelite")
    v["4G"] = tem(n, r"movel", r"4g", r"5g")
    v["COMPAR"] = tem(n, r"compartilhad")
    v["V.C"] = tem(n, r"\bcabo\b")
    v["V.R"] = tem(n, r"via radio", r"\bradio\b")
    v["PUB"] = tem(n, r"publica")
    v["N.PO"] = tem(n, r"nao possui")
    if n and not any(v[k] for k in ("F.O", "V.S", "4G", "COMPAR", "V.C", "V.R", "PUB", "N.PO")):
        avisos.append(f"conexão de internet não reconhecida: '{n}'")

    return v


# ----------------------------------------------------------------------------
# PREENCHIMENTO DO .DOCX
# ----------------------------------------------------------------------------
def _texto_da_tag(tag, valores):
    val = valores.get(tag, "")
    if tag in TAGS_CHECK:
        return MARCADO if val else DESMARCADO
    return "" if val is None else str(val)


def substituir_no_paragrafo(p, valores):
    """Troca as tags mesmo que o Word as tenha quebrado em vários <w:r>/<w:t>."""
    ts = list(p.iter("{%s}t" % W))
    if not ts:
        return
    orig = [t.text or "" for t in ts]
    full = "".join(orig)
    if "$" not in full:
        return
    matches = list(TAG_RE.finditer(full))
    if not matches:
        return

    inicio, acc = [], 0
    for s in orig:
        inicio.append(acc)
        acc += len(s)
    novo = list(orig)

    for m in reversed(matches):
        s, e = m.span()
        rep = _texto_da_tag(m.group(1), valores)
        j = next(i for i in range(len(ts)) if inicio[i] <= s < inicio[i] + len(orig[i]))
        pos, primeiro = s, True
        while pos < e and j < len(ts):
            local = pos - inicio[j]
            if local >= len(orig[j]):
                j += 1
                continue
            take = min(len(orig[j]) - local, e - pos)
            if primeiro:
                novo[j] = novo[j][:local] + rep + novo[j][local + take:]
                primeiro = False
            else:
                novo[j] = novo[j][:local] + novo[j][local + take:]
            pos += take
            j += 1

    for t, s in zip(ts, novo):
        if s != (t.text or ""):
            t.text = s
            t.set(XML_SPACE, "preserve")


def preencher_docx(template, saida, valores):
    partes_xml = re.compile(r"word/(document|header\d+|footer\d+)\.xml$")
    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            dados = zin.read(item.filename)
            if partes_xml.match(item.filename):
                raiz = etree.fromstring(dados)
                for p in raiz.iter("{%s}p" % W):
                    substituir_no_paragrafo(p, valores)
                dados = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(item, dados)


def tags_sobrando(docx_path):
    achou = set()
    with zipfile.ZipFile(docx_path) as z:
        for n in z.namelist():
            if n.endswith(".xml") and n.startswith("word/"):
                raiz = etree.fromstring(z.read(n))
                for p in raiz.iter("{%s}p" % W):
                    txt = "".join(t.text or "" for t in p.iter("{%s}t" % W))
                    achou.update(ANY_DOLLAR_RE.findall(txt))
    return achou


# ----------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------
def achar_soffice():
    for nome in ("soffice", "libreoffice"):
        p = shutil.which(nome)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).exists():
            return p
    return None


def docx_para_pdf(docx, pasta_pdf):
    soffice = achar_soffice()
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pasta_pdf), str(docx)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return Path(pasta_pdf) / (Path(docx).stem + ".pdf")
    try:  # alternativa no Windows com Word instalado
        from docx2pdf import convert
        destino = Path(pasta_pdf) / (Path(docx).stem + ".pdf")
        convert(str(docx), str(destino))
        return destino
    except ImportError:
        sys.exit("Instale o LibreOffice (ou 'pip install docx2pdf' com Word) para gerar PDF.")


def nome_arquivo(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "aluno"


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="CSV exportado da planilha (em vez de baixar pela URL)")
    ap.add_argument("--template", default=TEMPLATE)
    ap.add_argument("--saida", default=PASTA_SAIDA)
    ap.add_argument("--linha", type=int, help="só esta resposta (1 = primeira)")
    ap.add_argument("--nome", help="só alunos cujo nome contenha este texto")
    ap.add_argument("--juntar", action="store_true", help="gera também um PDF único com todos")
    ap.add_argument("--manter-docx", action="store_true", help="não apaga os .docx intermediários")
    a = ap.parse_args()

    if not Path(a.template).exists():
        sys.exit(f"Modelo não encontrado: {a.template}")

    cab, linhas = ler_planilha(a.csv)
    get = montar_getters(cab)
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)

    pdfs = []
    for n, linha in enumerate(linhas, start=1):
        if not any(c.strip() for c in linha):
            continue
        if a.linha and n != a.linha:
            continue
        nome = get(linha, "nome")
        if a.nome and norm(a.nome) not in norm(nome):
            continue

        avisos = []
        valores = valores_da_linha(lambda k, l=linha: get(l, k), avisos)
        base = f"{n:03d}_{nome_arquivo(nome)}"

        with tempfile.TemporaryDirectory() as tmp:
            docx_tmp = Path(tmp) / f"{base}.docx"
            preencher_docx(a.template, docx_tmp, valores)
            sobrou = tags_sobrando(docx_tmp)
            if sobrou:
                avisos.append("tags não substituídas: " + ", ".join(sorted(sobrou)))
            pdf = docx_para_pdf(docx_tmp, saida)
            if a.manter_docx:
                shutil.copy(docx_tmp, saida / docx_tmp.name)
        pdfs.append(pdf)
        print(f"[{n}] {nome or '(sem nome)'} -> {pdf}")
        for av in avisos:
            print("     AVISO:", av)

    if a.juntar and pdfs:
        try:
            from pypdf import PdfWriter
        except ImportError:
            sys.exit("Para --juntar instale: pip install pypdf")
        w = PdfWriter()
        for p in pdfs:
            w.append(str(p))
        destino = saida / "TODOS.pdf"
        w.write(str(destino))
        print("PDF único:", destino)

    print(f"\nConcluído: {len(pdfs)} PDF(s) em {saida}/")


if __name__ == "__main__":
    main()
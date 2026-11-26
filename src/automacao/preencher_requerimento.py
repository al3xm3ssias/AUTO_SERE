#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preenche o REQUERIMENTO_MATRICULA_2027.docx a partir da planilha do Google
(respostas do formulário) e salva um PDF por aluno.

Uso:
    pip install lxml
    python preencher_requerimento.py                       # usa a planilha cadastrada com o tipo Matrícula
    python preencher_requerimento.py --csv respostas.csv   # usa um CSV baixado
    python preencher_requerimento.py --linha 3             # só a 3ª resposta (1 = primeira)
    python preencher_requerimento.py --nome "maria"        # só quem tiver "maria" no nome
    python preencher_requerimento.py --juntar              # gera também um PDF único (precisa de pypdf)

Requisitos: Python 3.8+, lxml e LibreOffice (comando `soffice`) para converter em PDF.
"""
import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from lxml import etree

# ----------------------------------------------------------------------------
# CONFIGURAÇÃO  (ajuste aqui)
# ----------------------------------------------------------------------------
TEMPLATE = "REQUERIMENTO_MATRICULA_2027.docx"

# Sem --saida, os PDFs vão para <base>/<ano letivo atual>/ (a mesma pasta-base dos modelos de parecer: dados/ ou
# AUTO_SERE_PARECERES_BASE). O modelo enviado pela tela fica em <base>/MODELO/.
PASTA_SAIDA_FALLBACK = "pdfs_matricula"       # só se o programa não estiver instalado (script solto)
NOME_MODELO_ENVIADO = "REQUERIMENTO_MATRICULA.docx"
LIMITE_MODELO_MB = 15

# Valor da tag $ESCOLA (coloque o nome oficial completo da escola)
ESCOLA = "ESCOLA JUDITH MACEDO SILVEIRA"

# Filiação 1 e 2 do modelo = Responsável 1 e 2 da planilha ($NOME_RESP1, $NOME_RESP2 ...).
# O Responsável 1 também preenche o bloco "Responsável legal" ($NOME_RESP, $V.x ...);
# RESP1_PAPEL só decide qual vínculo ($V.M / $V.P / $V.T) fica marcado nesse bloco ("MAE", "PAI" ou "TUTOR").
# A coluna "Documento do responsável 1" é IGNORADA (é a foto do RG): RG do responsável 1 e $DOC_RESP saem vazios.
RESP1_PAPEL = "MAE"

MARCADO = "X"      # o que entra no lugar da tag quando a opção está marcada
DESMARCADO = " "   # o que entra quando não está

# ----------------------------------------------------------------------------
# TAGS DO MODELO  (mapeadas a partir do .docx)
# ----------------------------------------------------------------------------
TAGS_TEXTO = [
    "ESCOLA", "NOME_ALUNO", "CGM", "DT.N", "N_RG", "N_CIN", "N_CPF",
    "NOME_RESP1", "RG_RESP1", "CPF_RESP1", "TEL_RESP1", "PROF_RESP1",    # Filiação 1
    "NOME_RESP2", "RG_RESP2", "CPF_RESP2", "TEL_RESP2", "PROF_RESP2",    # Filiação 2
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
# PASTAS (modelo enviado pela tela e saída por ano letivo)
# ----------------------------------------------------------------------------
def _pasta_base():
    """Pasta-base do programa (a mesma dos modelos de parecer); None se rodando fora do projeto."""
    try:
        from src.automacao import parecer_fund
        return parecer_fund.pasta_base()
    except Exception:  # noqa: BLE001 — script solto, sem o restante do projeto
        return None


def pasta_modelos():
    base = _pasta_base()
    return (base / "MODELO") if base else None


def modelo_enviado():
    """Caminho do modelo enviado pela tela (Configurações → Modelo do requerimento) ou None."""
    pasta = pasta_modelos()
    caminho = (pasta / NOME_MODELO_ENVIADO) if pasta else None
    return caminho if caminho and caminho.is_file() else None


def pasta_saida_padrao():
    """<base>/<ano letivo atual>/ — ex.: dados/2027/."""
    base = _pasta_base()
    if base is None:
        return Path(PASTA_SAIDA_FALLBACK)
    from src.comum import paths
    return base / paths.ano_atual() / "REQUERIMENTO_MATRICULA"


def validar_modelo(conteudo):
    """ValueError com mensagem pronta se o arquivo não serve de modelo do requerimento."""
    if not conteudo:
        raise ValueError("O arquivo está vazio.")
    if len(conteudo) > LIMITE_MODELO_MB * 1024 * 1024:
        raise ValueError(f"O arquivo passa de {LIMITE_MODELO_MB} MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            xml = z.read("word/document.xml")
        texto = "".join(t.text or "" for t in etree.fromstring(xml).iter("{%s}t" % W))
    except Exception as exc:  # noqa: BLE001 — qualquer erro = não é um .docx
        raise ValueError("Esse arquivo não é um documento Word (.docx) válido.") from exc
    if "$NOME_ALUNO" not in texto:
        raise ValueError("O modelo não tem o marcador $NOME_ALUNO. Escreva $NOME_ALUNO onde deve sair o nome do aluno.")


def salvar_modelo(conteudo):
    """Guarda o modelo em <base>/MODELO/REQUERIMENTO_MATRICULA.docx. Devolve {"arquivo", "substituiu"}."""
    validar_modelo(conteudo)
    pasta = pasta_modelos()
    if pasta is None:
        raise ValueError("Pasta de modelos indisponível (programa fora da instalação).")
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / NOME_MODELO_ENVIADO
    substituiu = destino.exists()
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_bytes(conteudo)
    os.replace(tmp, destino)
    return {"arquivo": str(destino), "substituiu": substituiu}


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
def ler_planilha_csv(csv_path):
    """(cabeçalho, linhas) de um CSV exportado da planilha. ValueError com mensagem pronta."""
    raw = Path(csv_path).read_text(encoding="utf-8-sig")
    linhas = list(csv.reader(io.StringIO(raw)))
    if len(linhas) < 2:
        raise ValueError("A planilha não tem respostas.")
    return linhas[0], linhas[1:]


def _escolher_aba(abas):
    """A aba das respostas do formulário (a que tem 'respostas' no nome); sem ela, a primeira."""
    return next((a for a in abas if "respostas" in norm(a)), abas[0])


def ler_planilha_cadastrada(planilha_id=None):
    """
    (cabeçalho, linhas) da planilha cadastrada em 'Planilhas do Drive' com o tipo Matrícula (a ativa; ou a escolhida
    por `planilha_id`). O link/ID nunca fica neste arquivo: quem sabe qual é a planilha é o gerenciador.
    """
    from src.comum import google_sheets as gs, planilhas_gerenciador as gp
    try:
        ref = gp.resolver(gp.FINALIDADE_MATRICULA, id_item=planilha_id, plataformas=["google_sheets"])
    except LookupError as exc:                       # sem planilha cadastrada / mais de uma ativa / id inexistente
        raise ValueError(str(exc)) from exc
    print(f"Planilha de matrícula: {ref.nome}")
    servico = gs.abrir_servico()
    abas = gs.listar_abas(ref.planilha_id, servico=servico)
    if not abas:
        raise ValueError(f"A planilha '{ref.nome}' não tem abas.")
    aba = _escolher_aba(abas)
    dados = gs.ler_intervalo(ref.planilha_id, "'" + aba.replace("'", "''") + "'!A:ZZ", formatado=True, servico=servico)
    if len(dados) < 2:
        raise ValueError(f"A aba '{aba}' da planilha '{ref.nome}' não tem respostas.")
    return dados[0], dados[1:]


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
        "r1_tel":    C.idx("telefone responsavel 1", inicio=True),
        "r1_cpf":    C.idx("cpf responsavel 1", inicio=True),
        "r1_prof":   C.idx("profissao responsavel 1", inicio=True),
        "r1_email":  C.idx("e-mail responsavel 1", inicio=True),
        "r2_nome":   C.idx("responsavel 2 (nome)", inicio=True),
        "r2_doc":    C.idx("documento responsavel 2", inicio=True),
        "r2_tel":    C.idx("telefone responsavel 2", inicio=True),
        "r2_cpf":    C.idx("cpf responsavel 2", inicio=True),
        "r2_prof":   C.idx("profissao responsavel 2", inicio=True),
        "r2_email":  C.idx("e-mail responsavel 2", inicio=True),
        "sus":       C.idx("cartao do sus", inicio=True),
        "bolsa":     C.idx("recebe o bolsa", inicio=True),
        "nis_aluno": C.idx("numero nis estudante", inicio=True),
        "nis_resp":  C.idx("numero nis responsavel", inicio=True),
        "total_res": C.idx("total de pessoas", inicio=True),
        "deficiencia": C.idx("aluno apresenta algum tipo de deficiencia", inicio=True),
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

    # ---- responsáveis: Responsável 1 -> Filiação 1 ($..._RESP1), Responsável 2 -> Filiação 2 ($..._RESP2)
    # A coluna "Documento do responsável 1" é uma foto do RG e é ignorada: sem RG nem documento do responsável 1.
    r1 = dict(nome=g("r1_nome"), doc="", cpf=g("r1_cpf"), tel=g("r1_tel"), prof=g("r1_prof"))
    r2 = dict(nome=g("r2_nome"), doc=extrair_rg(g("r2_doc")), cpf=g("r2_cpf"), tel=g("r2_tel"), prof=g("r2_prof"))
    if not r2["cpf"]:
        m = CPF_RE.search(g("r2_doc"))
        r2["cpf"] = m.group(0) if m else ""

    for sufixo, r in (("RESP1", r1), ("RESP2", r2)):
        v[f"NOME_{sufixo}"] = r["nome"].upper()
        v[f"RG_{sufixo}"] = r["doc"]
        v[f"CPF_{sufixo}"] = r["cpf"]
        v[f"TEL_{sufixo}"] = r["tel"]
        v[f"PROF_{sufixo}"] = r["prof"]

    # bloco "Responsável legal" = Responsável 1
    v["NOME_RESP"] = r1["nome"].upper()
    v["DOC_RESP"] = ""
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


LOTE_PDF = 25   # quantos .docx vão por vez ao LibreOffice (abrir leva alguns segundos)


def docx_para_pdf_lote(docxs, pasta_pdf):
    """
    Converte os .docx em PDF (em `pasta_pdf`) de um lote por vez, SEM abrir janela de console no Windows.
    Devolve {docx: pdf ou None se aquele não saiu}. RuntimeError se não há conversor instalado.
    """
    docxs = [Path(d) for d in docxs]
    try:
        from src.comum import conversao_pdf
    except ImportError:                                       # script solto, fora do projeto
        conversao_pdf = None
    resultado = {}
    if conversao_pdf is not None:
        try:
            for i in range(0, len(docxs), LOTE_PDF):
                resultado.update(conversao_pdf.docx_para_pdf(docxs[i:i + LOTE_PDF], pasta_pdf))
        except conversao_pdf.ConversaoPdfErro as exc:
            raise RuntimeError(str(exc)) from exc
        return resultado
    soffice = achar_soffice()
    if not soffice:
        raise RuntimeError("Instale o LibreOffice para gerar PDF.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for docx in docxs:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pasta_pdf), str(docx)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        pdf = Path(pasta_pdf) / (docx.stem + ".pdf")
        resultado[docx] = pdf if pdf.is_file() else None
    return resultado


def nome_arquivo(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "aluno"


# ----------------------------------------------------------------------------
# GERAÇÃO (usada pela tela Automações → Documentos e pela linha de comando)
# ----------------------------------------------------------------------------
def gerar_requerimentos(cab, linhas, *, modelo, saida, linha=None, nome=None, modo_teste=False, juntar=False,
                        manter_docx=False):
    """
    Gera um PDF por resposta. `linha` = só essa resposta (1 = primeira); `nome` = só quem tem esse texto no nome;
    `modo_teste` = só a primeira resposta que passar nos filtros. Devolve {"total", "gerados", "avisos", "pasta", "pdfs"}.
    """
    try:
        from src.comum.execucao_gui import verificar_cancelamento
    except Exception:  # noqa: BLE001 — script solto
        def verificar_cancelamento():
            return None

    if not Path(modelo).exists():
        raise ValueError(f"Modelo não encontrado: {modelo}. Envie o modelo em Configurações → Modelo do requerimento.")
    get = montar_getters(cab)
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)

    pdfs, todos_avisos = [], []
    with tempfile.TemporaryDirectory() as tmp:
        pendentes = []                                   # (n, aluno, docx) preenchidos, à espera da conversão
        for n, resposta in enumerate(linhas, start=1):
            verificar_cancelamento()
            if not any(c.strip() for c in resposta):
                continue
            if linha and n != linha:
                continue
            aluno = get(resposta, "nome")
            if nome and norm(nome) not in norm(aluno):
                continue

            avisos = []
            valores = valores_da_linha(lambda k, l=resposta: get(l, k), avisos)
            docx_tmp = Path(tmp) / f"{n:03d}_{nome_arquivo(aluno)}.docx"
            preencher_docx(modelo, docx_tmp, valores)
            sobrou = tags_sobrando(docx_tmp)
            if sobrou:
                avisos.append("tags não substituídas: " + ", ".join(sorted(sobrou)))
            for av in avisos:
                print(f"[{n}] {aluno or '(sem nome)'} AVISO:", av)
                todos_avisos.append(f"{aluno or n}: {av}")
            pendentes.append((n, aluno, docx_tmp))
            if manter_docx:
                shutil.copy(docx_tmp, saida / docx_tmp.name)
            if modo_teste:
                print("Modo de teste: só a primeira resposta será gerada.")
                break

        if pendentes:
            print(f"Convertendo {len(pendentes)} requerimento(s) em PDF...")
            verificar_cancelamento()
            feitos = docx_para_pdf_lote([d for _, _, d in pendentes], saida)
            for n, aluno, docx_tmp in pendentes:
                pdf = feitos.get(docx_tmp)
                if pdf is None:
                    todos_avisos.append(f"{aluno or n}: o PDF não foi gerado")
                    print(f"[{n}] {aluno or '(sem nome)'} -> ERRO: o PDF não foi gerado")
                else:
                    pdfs.append(pdf)
                    print(f"[{n}] {aluno or '(sem nome)'} -> {pdf}")

    if juntar and pdfs:
        try:
            from pypdf import PdfWriter
        except ImportError:
            raise RuntimeError("Para juntar os PDFs instale: pip install pypdf") from None
        w = PdfWriter()
        for p in pdfs:
            w.append(str(p))
        destino = saida / "TODOS.pdf"
        w.write(str(destino))
        print("PDF único:", destino)

    print(f"\nConcluído: {len(pdfs)} PDF(s) em {saida}/")
    return {"total": len(pdfs), "gerados": len(pdfs), "avisos": todos_avisos, "pasta": str(saida),
            "pdfs": [str(p) for p in pdfs]}


def executar(planilha_id=None, *, nome=None, juntar=False, modo_teste=False):
    """Ponto de entrada da tela: lê a planilha cadastrada (tipo Matrícula) e gera os PDFs em <base>/<ano>/."""
    modelo = modelo_enviado() or TEMPLATE
    if not Path(modelo).exists():
        raise ValueError("Nenhum modelo do requerimento enviado. Envie o .docx em Configurações → Modelo do requerimento.")
    cab, linhas = ler_planilha_cadastrada(planilha_id)
    return gerar_requerimentos(cab, linhas, modelo=modelo, saida=pasta_saida_padrao(), nome=nome, juntar=juntar,
                               modo_teste=modo_teste)


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="CSV exportado da planilha (sem isso, usa a planilha cadastrada com o tipo Matrícula)")
    ap.add_argument("--template", default=None,
                    help="modelo .docx (padrão: o enviado em Configurações → Modelo do requerimento; "
                         f"se não houver, {TEMPLATE})")
    ap.add_argument("--saida", default=None,
                    help="pasta dos PDFs (padrão: <base>/<ano letivo atual>/, ex.: dados/2027/)")
    ap.add_argument("--linha", type=int, help="só esta resposta (1 = primeira)")
    ap.add_argument("--nome", help="só alunos cujo nome contenha este texto")
    ap.add_argument("--juntar", action="store_true", help="gera também um PDF único com todos")
    ap.add_argument("--manter-docx", action="store_true", help="não apaga os .docx intermediários")
    a = ap.parse_args()
    try:
        modelo = a.template or modelo_enviado() or TEMPLATE
        cab, linhas = ler_planilha_csv(a.csv) if a.csv else ler_planilha_cadastrada()
        gerar_requerimentos(cab, linhas, modelo=modelo, saida=a.saida or pasta_saida_padrao(), linha=a.linha,
                            nome=a.nome, juntar=a.juntar, manter_docx=a.manter_docx)
    except (ValueError, RuntimeError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()

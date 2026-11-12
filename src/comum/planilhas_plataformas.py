"""
planilhas_plataformas.py — plataformas de planilha (Google Sheets, Excel .xlsx, LibreOffice .ods)
=============================================================================
Cada plataforma é um "plugue" registrado aqui. O gerenciador (planilhas_gerenciador.py) e o cadastro
(planilhas_registro.py) só conversam com esta interface; para acrescentar uma plataforma nova basta escrever uma classe
com os mesmos métodos e chamar `registrar_plataforma(...)` — nenhum módulo do sistema precisa mudar.

Interface de uma plataforma:
    nome, rotulo            identificador gravado no cadastro ("google_sheets") e texto da tela
    local                   True = arquivo no disco (tem `caminho`); False = serviço online (tem `link`/ID)
    extensao                ".xlsx" / ".ods" (só plataformas locais)
    referencia(link, caminho, conferir) -> dict     valida e normaliza a referência digitada pelo usuário:
                            {"referencia", "link", "caminho", "planilha_id"} (referencia é a chave ÚNICA do cadastro)
    criar(nome, abas, destino=None, servico=None) -> dict
                            cria uma planilha NOVA a partir das abas neutras (planilhas_modelos.Aba) e devolve o mesmo
                            dict de `referencia`, mais "titulo"

As abas são neutras: valores, fórmulas em notação universal (funções em inglês, argumentos separados por vírgula, como
o Google Sheets e o Excel aceitam pela API/arquivo), larguras, listas suspensas, formatos e congelamento de linhas. Cada
plataforma traduz isso para o seu formato, então as três saem com a mesma estrutura, colunas e fórmulas.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from . import paths as _paths

PREFIXO_LINK_GOOGLE = "https://docs.google.com/spreadsheets/"


class PlataformaDesconhecida(ValueError):
    """Nome de plataforma que não está registrada."""


class PlataformaIndisponivel(RuntimeError):
    """A plataforma existe, mas falta algo no computador (ex.: LibreOffice para .ods). A mensagem já vem pronta."""


# ───────────────────────────── utilitários ─────────────────────────────────────

def pasta_arquivos_padrao() -> Path:
    """Onde ficam as planilhas locais criadas pelo sistema (dados/planilhas/arquivos). Função: os testes trocam a pasta."""
    return _paths.DADOS_DIR / "planilhas" / "arquivos"


def nome_de_arquivo_seguro(nome: str) -> str:
    sem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(nome or "")).strip(" .")
    return " ".join(sem.split())[:120] or "Planilha"


def _caminho_novo(pasta: Path, nome: str, extensao: str) -> Path:
    """Caminho livre em `pasta` (acrescenta (2), (3)... em vez de sobrescrever)."""
    base = nome_de_arquivo_seguro(nome)
    pasta.mkdir(parents=True, exist_ok=True)
    candidato, n = pasta / f"{base}{extensao}", 2
    while candidato.exists():
        candidato = pasta / f"{base} ({n}){extensao}"
        n += 1
    return candidato


def normalizar_caminho(caminho) -> str:
    """Caminho absoluto, sem '..' nem barras duplas. É o que vale como referência única de uma planilha local."""
    return str(Path(os.path.expandvars(os.path.expanduser(str(caminho).strip()))).resolve())


# ───────────────────────────── base ────────────────────────────────────────────

class Plataforma:
    nome = ""
    rotulo = ""
    local = False
    extensao = ""

    def referencia(self, link="", caminho="", conferir=True) -> dict:      # pragma: no cover - interface
        raise NotImplementedError

    def criar(self, nome, abas, destino=None, servico=None) -> dict:       # pragma: no cover - interface
        raise NotImplementedError

    def disponivel(self) -> Optional[str]:
        """None se dá para usar; senão o motivo (texto pronto para a tela)."""
        return None


# ───────────────────────────── arquivos locais ─────────────────────────────────

class _Local(Plataforma):
    local = True

    def referencia(self, link="", caminho="", conferir=True) -> dict:
        bruto = str(caminho or link or "").strip()
        if not bruto:
            raise ValueError(f"Informe o caminho do arquivo {self.extensao} da planilha.")
        if bruto.lower().startswith(("http://", "https://")):
            raise ValueError(f"Para {self.rotulo} informe o caminho do arquivo no computador, não um link.")
        absoluto = normalizar_caminho(bruto)
        if not absoluto.lower().endswith(self.extensao):
            raise ValueError(f"O arquivo precisa terminar em {self.extensao} ({self.rotulo}).")
        if conferir and not Path(absoluto).is_file():
            raise ValueError(f"Não encontrei o arquivo: {absoluto}")
        return {"referencia": absoluto.casefold() if os.name == "nt" else absoluto, "link": "", "caminho": absoluto,
                "planilha_id": ""}


class PlataformaXlsx(_Local):
    nome, rotulo, extensao = "xlsx", "Microsoft Excel (.xlsx)", ".xlsx"

    def criar(self, nome, abas, destino=None, servico=None) -> dict:
        arquivo = _escrever_xlsx(abas, _caminho_novo(Path(destino) if destino else pasta_arquivos_padrao(), nome, ".xlsx"))
        return {**self.referencia(caminho=str(arquivo)), "titulo": nome}


class PlataformaOds(_Local):
    nome, rotulo, extensao = "ods", "LibreOffice Calc (.ods)", ".ods"

    def disponivel(self) -> Optional[str]:
        from .conversao_pdf import encontrar_soffice
        if encontrar_soffice():
            return None
        return ("Para criar planilhas .ods é preciso ter o LibreOffice instalado (gratuito, libreoffice.org) "
                "ou definir AUTO_SERE_SOFFICE com o caminho do soffice.")

    def criar(self, nome, abas, destino=None, servico=None) -> dict:
        motivo = self.disponivel()
        if motivo:
            raise PlataformaIndisponivel(motivo)
        from .conversao_pdf import encontrar_soffice
        alvo = _caminho_novo(Path(destino) if destino else pasta_arquivos_padrao(), nome, ".ods")
        with tempfile.TemporaryDirectory() as tmp:
            origem = _escrever_xlsx(abas, Path(tmp) / (nome_de_arquivo_seguro(nome) + ".xlsx"))
            saida = Path(tmp) / "saida"
            saida.mkdir()
            try:
                # Perfil de usuário próprio e descartável: duas instâncias do LibreOffice com o mesmo perfil se atrapalham
                # (a segunda conversão falha se o LibreOffice já estiver aberto ou convertendo outro arquivo).
                perfil = (Path(tmp) / "perfil").as_uri()
                subprocess.run([encontrar_soffice(), f"-env:UserInstallation={perfil}", "--headless", "--convert-to", "ods",
                                "--outdir", str(saida), str(origem)], check=True, capture_output=True, timeout=180)
            except (subprocess.SubprocessError, OSError) as exc:
                raise PlataformaIndisponivel(f"O LibreOffice não conseguiu criar o arquivo .ods ({type(exc).__name__}).") from exc
            gerado = saida / (origem.stem + ".ods")
            if not gerado.is_file():
                raise PlataformaIndisponivel("O LibreOffice não gerou o arquivo .ods.")
            shutil.move(str(gerado), str(alvo))
        return {**self.referencia(caminho=str(alvo)), "titulo": nome}


def _escrever_xlsx(abas, destino: Path) -> Path:
    """Grava as abas neutras num .xlsx (openpyxl). A gravação é atômica: nunca fica um arquivo pela metade."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    livro = Workbook()
    livro.remove(livro.active)
    for aba in abas:
        ws = livro.create_sheet(title=aba.nome[:31])
        for r, linha in enumerate(aba.linhas, start=1):
            for c, valor in enumerate(linha, start=1):
                if valor not in (None, ""):
                    ws.cell(row=r, column=c, value=valor)
        for r in aba.negrito_linhas:
            for celula in ws[r]:
                celula.font = Font(bold=True)
        for i, largura in enumerate(aba.larguras, start=1):
            ws.column_dimensions[get_column_letter(i)].width = largura
        for intervalo, formato in aba.formatos:
            for linha in ws[intervalo]:
                for celula in (linha if isinstance(linha, tuple) else (linha,)):
                    celula.number_format = formato
        for intervalo, opcoes in aba.listas:
            dv = DataValidation(type="list", formula1='"' + ",".join(opcoes) + '"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(intervalo)
        for intervalo in aba.mesclar:
            ws.merge_cells(intervalo)
        if aba.congelar_linhas or aba.congelar_colunas:
            ws.freeze_panes = f"{get_column_letter(aba.congelar_colunas + 1)}{aba.congelar_linhas + 1}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        livro.save(temporario)
        os.replace(temporario, destino)
    finally:
        if temporario.exists():
            temporario.unlink()
    return destino


# ───────────────────────────── Google Sheets ───────────────────────────────────

class PlataformaGoogle(Plataforma):
    nome, rotulo, local = "google_sheets", "Google Sheets", False

    def referencia(self, link="", caminho="", conferir=True) -> dict:
        from .google_sheets import extrair_id_planilha        # import tardio: não carrega o Google à toa
        bruto = str(link or "").strip()
        pid = extrair_id_planilha(bruto)                      # SheetsValidacaoErro (é ValueError) explica o formato
        if re.search(r"\s", bruto):
            raise ValueError("O link não pode ter espaços.")
        if "/" in bruto:
            if not bruto.startswith(PREFIXO_LINK_GOOGLE):     # o link vira botão na tela: só links do Google Sheets
                raise ValueError("O link precisa ser de uma planilha do Google (começa com https://docs.google.com/spreadsheets/).")
            url = bruto
        else:
            url = f"{PREFIXO_LINK_GOOGLE}d/{pid}/edit"
        return {"referencia": pid, "link": url, "caminho": "", "planilha_id": pid}

    def criar(self, nome, abas, destino=None, servico=None) -> dict:
        from . import google_sheets as gs
        servico = servico or gs.abrir_servico()
        info = gs.criar_planilha(nome, {a.nome: [] for a in abas}, servico=servico)
        pid = info["id"]
        gids = _gids(servico, pid)
        dados, pedidos = [], []
        for aba in abas:
            dados.append({"range": gs.intervalo_a1(aba.nome, "A1"), "values": [[("" if v is None else v) for v in l] for l in aba.linhas]})
            pedidos += _pedidos_formatacao(aba, gids.get(aba.nome, 0), gs)
        gs._executar(servico.values().batchUpdate(spreadsheetId=pid, body={"valueInputOption": "USER_ENTERED", "data": dados}),
                     "gravar o modelo")
        if pedidos:
            gs._executar(servico.batchUpdate(spreadsheetId=pid, body={"requests": pedidos}), "formatar o modelo")
        return {**self.referencia(link=info["url"]), "titulo": info.get("titulo") or nome}


def _gids(servico, pid: str) -> dict[str, int]:
    from . import google_sheets as gs
    meta = gs._executar(servico.get(spreadsheetId=pid, fields="sheets.properties(sheetId,title)"), "abrir a planilha criada")
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}


def _grade(intervalo: str, gid: int, gs) -> dict:
    """'A5:C9' → GridRange do Google (índices a partir de 0, fim exclusivo)."""
    m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", intervalo)
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3) or m.group(1), int(m.group(4) or m.group(2))
    return {"sheetId": gid, "startRowIndex": r1 - 1, "endRowIndex": r2, "startColumnIndex": gs.coluna_para_indice(c1),
            "endColumnIndex": gs.coluna_para_indice(c2) + 1}


_FORMATOS_GOOGLE = {"0.0": "0.0", "0": "0", "0%": "0%", "0.0%": "0.0%", "dd/mm/yyyy": "dd/mm/yyyy", "@": "@"}


def _pedidos_formatacao(aba, gid: int, gs) -> list[dict]:
    pedidos = []
    for i, largura in enumerate(aba.larguras):
        pedidos.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": int(largura * 7 + 5)}, "fields": "pixelSize"}})
    for r in aba.negrito_linhas:
        pedidos.append({"repeatCell": {"range": {"sheetId": gid, "startRowIndex": r - 1, "endRowIndex": r},
                                       "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                       "fields": "userEnteredFormat.textFormat.bold"}})
    for intervalo, formato in aba.formatos:
        tipo = "TEXT" if formato == "@" else ("DATE" if "yy" in formato else "NUMBER")
        pedidos.append({"repeatCell": {"range": _grade(intervalo, gid, gs),
                                       "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": _FORMATOS_GOOGLE.get(formato, formato)}}},
                                       "fields": "userEnteredFormat.numberFormat"}})
    for intervalo, opcoes in aba.listas:
        pedidos.append({"setDataValidation": {"range": _grade(intervalo, gid, gs), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in opcoes]},
            "showCustomUi": True, "strict": False}}})
    for intervalo in aba.mesclar:
        pedidos.append({"mergeCells": {"range": _grade(intervalo, gid, gs), "mergeType": "MERGE_ALL"}})
    if aba.congelar_linhas or aba.congelar_colunas:
        pedidos.append({"updateSheetProperties": {
            "properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": aba.congelar_linhas, "frozenColumnCount": aba.congelar_colunas}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})
    return pedidos


# ───────────────────────────── registro ────────────────────────────────────────

_PLATAFORMAS: dict[str, Plataforma] = {}
PLATAFORMA_PADRAO = "google_sheets"           # o que um registro antigo (sem o campo) sempre foi


def registrar_plataforma(plataforma: Plataforma) -> Plataforma:
    _PLATAFORMAS[plataforma.nome] = plataforma
    return plataforma


def plataforma(nome: str) -> Plataforma:
    try:
        return _PLATAFORMAS[str(nome or PLATAFORMA_PADRAO).strip()]
    except KeyError:
        raise PlataformaDesconhecida(f"Plataforma desconhecida: '{nome}'. Use {' ou '.join(nomes())}.") from None


def nomes() -> list[str]:
    return list(_PLATAFORMAS)


def listar() -> list[dict]:
    """Para a tela: [{valor, nome, local, extensao, disponivel(None|motivo)}]."""
    return [{"valor": p.nome, "nome": p.rotulo, "local": p.local, "extensao": p.extensao, "indisponivel": p.disponivel()}
            for p in _PLATAFORMAS.values()]


for _p in (PlataformaGoogle(), PlataformaXlsx(), PlataformaOds()):
    registrar_plataforma(_p)

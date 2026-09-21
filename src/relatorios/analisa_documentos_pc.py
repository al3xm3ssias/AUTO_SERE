""" === RESUMO ESTRUTURAL DO SCRIPT ===
Funções encontradas:
   - Função: normalizar() (Sem documentação)
   - Função: verificar_documento()
       Verifica se o arquivo corresponde ao documento (considerando sinônimos)
   - Função: cpf_na_certidao()
       Retorna True se o aluno tem certidão de nascimento E nasceu após 2017.
       Nesse caso o CPF já consta na própria certidão.
       Aceita datas nos formatos: 'DD/MM/AAAA', 'AAAA-MM-DD' ou só 'AAAA'.
   - Função: main()
       Orquestra as 6 etapas do script (carregar dados → gerar relatório).
==================================== """

"""
analisa_documentos_pc.py — Cruzamento de documentos digitalizados no PC
=============================================================================
Portado de AUTO_SERE/analisa_documentos_pc.py para
src/relatorios/analisa_documentos_pc.py.

MUDANÇAS ESTRUTURAIS EM RELAÇÃO AO ORIGINAL (decididas com o usuário em
28/08/2026):

1. Bloco "1. CARREGAR DADOS" estava duplicado por engano no original
   (linhas 145-159, copy-paste acidental, mesmo comportamento repetido
   duas vezes). Removida a duplicação — mantido um único carregamento.

2. Todo o corpo do script, que antes rodava solto no nível do módulo
   (sem função), agora está dentro de main(), para poder ser importado
   sem efeito colateral e testado. Comportamento idêntico ao original,
   só reorganizado dentro de uma função.

3. Caminhos de dados (TURMAS_JSON, DOCUMENTOS_PC_JSON, RELATORIO_XLSX):
   antes fixos em BASE = Path.home() / "compartilhado/ARQUIVOS" (servidor
   Linux específico). Agora resolvidos via src.comum.paths.dados_ano_atual()
   — correto tanto no executável Windows instalado quanto neste ambiente.

4. PASTA_DIGITALIZACAO: antes fixa em
   BASE / "ESCOLA JUDITH/2026/DIGITALIZAÇÃO". Essa pasta é conceitualmente
   diferente dos dados de trabalho acima — é escolhida livremente pelo
   usuário (C:\\, D:\\, HD externo) durante o setup inicial do programa
   (ver src/comum/configuracao.py). Agora lida de lá; se ainda não foi
   configurada, o script avisa e para, em vez de estourar erro tentando
   iterar um caminho fixo que não existe.

Toda a lógica de negócio (sinônimos de documento, regra de CPF-na-certidão,
cores e formatação do Excel, cálculo de porcentagem) é idêntica ao original
— nenhuma regra foi alterada, só a forma como os caminhos são resolvidos e
a organização em função.

Uso:
    python -m src.relatorios.analisa_documentos_pc
"""

import json
import re
from datetime import datetime
from pathlib import Path
from unicodedata import normalize

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from src.comum import paths as _paths
from src.comum.configuracao import pasta_digitalizacao, pasta_digitalizacao_configurada


# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
# Dados de trabalho (turmas, cruzamento, relatório): pasta de instalação,
# organizados por ano letivo — ver src/comum/paths.py.
_SERE = _paths.dados_ano_atual()
_SERE.mkdir(parents=True, exist_ok=True)

TURMAS_JSON        = _SERE / "turmas.json"
DOCUMENTOS_PC_JSON = _SERE / "documentos-alunos-pc.json"
RELATORIO_XLSX     = _SERE / "relatorio_documentos-PC.xlsx"

# Pasta de digitalização: escolhida pelo usuário no setup inicial, NÃO fixa.
# Resolvida em tempo de execução (dentro de main()), pois pode ainda não
# estar configurada na primeira vez que o script é importado.

# Documento padrão e seus sinônimos
DOCUMENTOS_SINONIMOS = {
    "Declaração de vacina": [
        "carteirinha de vacinação",
        "cartão de vacinação",
        "vacinação",
        "carteirinha",
        "vacina",
    ],

    "Comprovante de Vacinação": [
        "comprovante de vacinação",
        "carteirinha de vacinação",
        "cartão de vacinação",
        "vacinação",
        "carteirinha",
        "vacina",
    ],
    "RG": [
        "rg",
        "rg do aluno",
        "rg aluno",
    ],
    "CPF do Aluno": [
        "cpf do aluno",
        "cpf aluno",
        "cpf",
    ],
    "Comprovante de residência": [
        "comprovante de residência",
        "copel",
        "sanepar",
        "talão",
        "residência",
        "comprovante de endereço",
        "endereço",
    ],
    "Certidão de nascimento do aluno": [
        "certidão de nascimento",
        "certido de nascimento",
        "certidão de nascimento do aluno",
        "certidao de nascimento do aluno",
        "certidão",
        "nascimento",
        "certidao",

    ],
    "CPF Responsável": [
        "cpf responsável",
        "cpf do responsável",
        "documento do responsável",
        "rg e cpf do responsável",
        "documentos dos responsaveis",
        "cpf pai",
        "cpf mãe",
        "cpf mae",
        "documento responsavel",
        "responsavel",
        "documentos",
        "documento",
    ],
}

# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def normalizar(texto: str) -> str:
    return normalize("NFKD", texto).encode("ASCII", "ignore").decode().upper().strip()

def verificar_documento(nome_arquivo: str, documento_chave: str) -> bool:
    """Verifica se o arquivo corresponde ao documento (considerando sinônimos)"""
    nome_norm = normalizar(nome_arquivo)

    # Verifica a chave principal
    if normalizar(documento_chave) in nome_norm:
        return True

    # Verifica sinônimos
    for sinonimo in DOCUMENTOS_SINONIMOS.get(documento_chave, []):
        if normalizar(sinonimo) in nome_norm:
            return True

    return False


def cpf_na_certidao(docs_aluno: list[dict], data_nascimento: str) -> bool:
    """
    Retorna True se o aluno tem certidão de nascimento E nasceu após 2017.
    Nesse caso o CPF já consta na própria certidão.
    Aceita datas nos formatos: 'DD/MM/AAAA', 'AAAA-MM-DD' ou só 'AAAA'.
    """
    tem_certidao = any(verificar_documento(pdf["nome"], "Certidão de nascimento do aluno")
                       for pdf in docs_aluno)
    if not tem_certidao:
        return False

    # Extrair o ano de qualquer formato
    ano = None
    for part in re.split(r"[-/]", data_nascimento):
        if len(part) == 4 and part.isdigit():
            ano = int(part)
            break

    return ano is not None and ano > 2017

# Padrão da pasta do aluno: "1 - NOME DO ALUNO"
RE_PASTA_ALUNO = re.compile(r"^(\d+)\s*-\s*(.+)$")


def main() -> int:
    """
    Orquestra as 6 etapas do script original (carregar turmas → montar
    mapa de nomes → varrer pasta de digitalização → salvar JSON → gerar
    relatório Excel → imprimir resumo). Retorna 0 em caso de sucesso,
    1 se a pasta de digitalização ainda não foi configurada.
    """

    # ─────────────────────────────────────────────
    # 0. VERIFICAR PASTA DE DIGITALIZAÇÃO CONFIGURADA
    # ─────────────────────────────────────────────
    if not pasta_digitalizacao_configurada():
        print("⚠️  A pasta de digitalização ainda não foi configurada.")
        print("    Rode o setup inicial (escolha da pasta de documentos digitalizados)")
        print("    antes de usar este script.")
        return 1

    pasta_digitalizacao_atual = pasta_digitalizacao()

    # ─────────────────────────────────────────────
    # 1. CARREGAR DADOS
    # ─────────────────────────────────────────────
    # (bloco duplicado no script original removido — mantido um único
    #  carregamento, com comportamento idêntico)

    print("📂 Carregando turmas.json ...")
    with open(TURMAS_JSON, "r", encoding="utf-8") as f:
        turmas_raw = json.load(f)

    alunos_sere: dict[str, dict] = {}
    for turma, alunos in turmas_raw.items():
        for aluno in alunos:
            # ✅ Ignora alunos que não estão com situação "Matriculado"
            situacao = aluno.get("Situação", "").strip().lower()
            if situacao != "matriculado":
                continue

            cgm = str(aluno["CGM"])
            alunos_sere[cgm] = {
                "CGM":   cgm,
                "Nome":  aluno["Nome"],
                "N":     aluno["N"],
                "Turma": turma,
                "DataNascimento": aluno.get("Data Nasc."),
            }

    print(f"   ✔ {len(alunos_sere)} alunos carregados do SERE.")

    # ─────────────────────────────────────────────
    # 2. MONTAR MAPA NOME → CGM
    # ─────────────────────────────────────────────

    nome_para_cgm: dict[str, str] = {
        normalizar(info["Nome"]): cgm
        for cgm, info in alunos_sere.items()
    }

    # ─────────────────────────────────────────────
    # 3. VARRER PASTAS DOS ALUNOS NO PC
    # ─────────────────────────────────────────────

    print(f"\n📂 Varrendo pasta: {pasta_digitalizacao_atual} ...")

    arquivos_pc_cgm: dict[str, list[str]] = {}
    pastas_nao_reconhecidas = []

    for pasta_turma in pasta_digitalizacao_atual.iterdir():
        if not pasta_turma.is_dir():
            continue

        for pasta_aluno in pasta_turma.iterdir():
            if not pasta_aluno.is_dir():
                continue

            m = RE_PASTA_ALUNO.match(pasta_aluno.name)
            if not m:
                pastas_nao_reconhecidas.append(str(pasta_aluno))
                continue

            nome_bruto = m.group(2).strip()
            nome_norm  = normalizar(nome_bruto)
            cgm        = nome_para_cgm.get(nome_norm)

            if not cgm:
                pastas_nao_reconhecidas.append(
                    f"{pasta_aluno.name}  ← nome não encontrado no SERE"
                )
                continue
            extensoes_validas = (".pdf", ".jpeg", ".jpg", ".png")

            # Listar todos os documentos dentro da pasta do aluno,
            # com a data de modificação do arquivo (data do documento)
            pdfs = [
                {
                    "nome":          arq.stem,
                    "nome_arquivo":  arq.stem,
                    "extensao":      arq.suffix.lower(),
                    "nome_completo": arq.name,
                    "data":          datetime.fromtimestamp(arq.stat().st_mtime).strftime("%d/%m/%Y"),
                }
                for arq in pasta_aluno.iterdir()
                if arq.is_file() and arq.suffix.lower() in extensoes_validas
            ]

            arquivos_pc_cgm[cgm] = pdfs

    total_arqs = sum(len(v) for v in arquivos_pc_cgm.values())
    print(f"   ✔ {len(arquivos_pc_cgm)} pastas de alunos reconhecidas, {total_arqs} arquivos no total.")

    if pastas_nao_reconhecidas:
        print(f"   ⚠  {len(pastas_nao_reconhecidas)} pastas não reconhecidas:")
        for p in pastas_nao_reconhecidas:
            print(f"      • {p}")

    # ─────────────────────────────────────────────
    # 4. SALVAR JSON DO PC
    # ─────────────────────────────────────────────

    print("\n💾 Salvando documentos-alunos-pc.json ...")

    documentos_pc_data = []
    for cgm, info in alunos_sere.items():
        if cgm in arquivos_pc_cgm:
            documentos_pc_data.append({
                "CGM": cgm,
                "Nome": info["Nome"],
                "Turma": info["Turma"],
                "Documentos": arquivos_pc_cgm[cgm],
            })

    with open(DOCUMENTOS_PC_JSON, "w", encoding="utf-8") as f:
        json.dump(documentos_pc_data, f, ensure_ascii=False, indent=2)

    print(f"   ✔ Salvo: {DOCUMENTOS_PC_JSON}")

    # ─────────────────────────────────────────────
    # 5. GERAR RELATÓRIO EXCEL
    # ─────────────────────────────────────────────

    print("\n📊 Gerando relatório Excel...")

    DOCUMENTOS = list(DOCUMENTOS_SINONIMOS.keys())

    # ── Aba principal ──────────────────────────────────────────────────────────────
    linhas = []
    for cgm, info in alunos_sere.items():
        nome = info["Nome"]
        docs_aluno = arquivos_pc_cgm.get(cgm, [])

        data_nasc = info.get("DataNascimento", "")
        status = {}
        for doc in DOCUMENTOS:
            if doc == "CPF do Aluno" and cpf_na_certidao(docs_aluno, data_nasc):
                # CPF já vem impresso na certidão de nascimento pós-2017
                status[doc] = "✔"
            else:
                encontrado = any(verificar_documento(pdf["nome"], doc) for pdf in docs_aluno)
                status[doc] = "✔" if encontrado else "❌"

        enviados = sum(1 for v in status.values() if v == "✔")
        perc     = round(enviados / len(DOCUMENTOS) * 100, 2)

        linha = {"Nome": nome, "CGM": cgm}
        linha.update(status)
        linha["Porcentagem"] = perc
        linhas.append(linha)

    df = pd.DataFrame(linhas).sort_values("Nome").reset_index(drop=True)
    df.to_excel(RELATORIO_XLSX, index=False)

    wb = load_workbook(RELATORIO_XLSX)
    ws = wb.active
    ws.freeze_panes = "C2"

    fill_colors = ["FFF2CC", "D9EAD3", "CCE5FF", "F4CCCC", "EAD1DC", "CFE2F3"]
    colunas  = list(df.columns)
    max_row  = ws.max_row

    for col_idx, col_name in enumerate(colunas, start=1):
        col_letter = get_column_letter(col_idx)
        color      = fill_colors[(col_idx - 1) % len(fill_colors)]
        fill       = PatternFill(start_color=color, end_color=color, fill_type="solid")

        header_cell = ws[f"{col_letter}1"]
        header_cell.font = Font(bold=True, name="Arial", size=10)
        header_cell.fill = fill
        if col_idx >= 3:
            header_cell.alignment = Alignment(textRotation=45, horizontal="center", vertical="center")
        else:
            header_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for row in range(2, max_row + 1):
            cell           = ws[f"{col_letter}{row}"]
            cell.fill      = fill
            cell.font      = Font(name="Arial", size=10)
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 14
    for col_idx in range(3, len(colunas) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 8
    ws.row_dimensions[1].height = 80

    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_fill   = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    green_font = Font(name="Arial", size=10, color="276221")
    red_font   = Font(name="Arial", size=10, color="9C0006")

    doc_start = colunas.index(DOCUMENTOS[0]) + 1
    doc_end   = colunas.index(DOCUMENTOS[-1]) + 1

    for row in range(2, max_row + 1):
        for col_idx in range(doc_start, doc_end + 1):
            cell = ws.cell(row=row, column=col_idx)
            if cell.value == "✔":
                cell.fill = green_fill
                cell.font = green_font
            elif cell.value == "❌":
                cell.fill = red_fill
                cell.font = red_font

    wb.save(RELATORIO_XLSX)

    # ── Aba: Documentos Faltando ───────────────────────────────────────────────────
    faltando_rows = []
    for cgm, info in alunos_sere.items():
        nome = info["Nome"]
        docs_aluno = arquivos_pc_cgm.get(cgm, [])
        data_nasc = info.get("DataNascimento", "")

        faltando = [
            doc for doc in DOCUMENTOS
            if not (
                (doc == "CPF do Aluno" and cpf_na_certidao(docs_aluno, data_nasc))
                or any(verificar_documento(pdf["nome"], doc) for pdf in docs_aluno)
            )
        ]
        if faltando:
            faltando_rows.append({
                "Nome": nome,
                "CGM": cgm,
                "Documentos Faltando": ", ".join(faltando),
                "Qtd Faltando": len(faltando),
            })

    df_faltando = (
        pd.DataFrame(faltando_rows)
        .sort_values("Qtd Faltando", ascending=False)
        .reset_index(drop=True)
    )

    with pd.ExcelWriter(RELATORIO_XLSX, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df_faltando.to_excel(writer, sheet_name="Documentos Faltando", index=False)

    wb2 = load_workbook(RELATORIO_XLSX)
    ws2 = wb2["Documentos Faltando"]
    ws2.freeze_panes = "A2"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    for col_idx in range(1, 5):
        cell           = ws2.cell(row=1, column=col_idx)
        cell.fill      = header_fill
        cell.font      = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    ws2.column_dimensions["A"].width = 42
    ws2.column_dimensions["B"].width = 14
    ws2.column_dimensions["C"].width = 70
    ws2.column_dimensions["D"].width = 14

    alt_fills = [
        PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid"),
        PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid"),
    ]
    for row in range(2, ws2.max_row + 1):
        f = alt_fills[row % 2]
        for col_idx in range(1, 5):
            cell           = ws2.cell(row=row, column=col_idx)
            cell.fill      = f
            cell.font      = Font(name="Arial", size=10)
            cell.alignment = Alignment(
                horizontal="left" if col_idx in (1, 3) else "center",
                vertical="center",
                wrap_text=(col_idx == 3),
            )
        ws2.row_dimensions[row].height = 30

    ws2.row_dimensions[1].height = 22
    wb2.save(RELATORIO_XLSX)

    print(f"💾 Salvo: {RELATORIO_XLSX}")

    # ─────────────────────────────────────────────
    # 6. RESUMO FINAL
    # ─────────────────────────────────────────────

    print("\n" + "="*55)
    print("  RESUMO")
    print("="*55)
    print(f"  Total de alunos no SERE         : {len(alunos_sere)}")
    print(f"  Alunos com documentos no PC     : {len(arquivos_pc_cgm)}")
    if pastas_nao_reconhecidas:
        print(f"  Pastas não reconhecidas         : {len(pastas_nao_reconhecidas)}")
    print("="*55)
    print("✅ Concluído!")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
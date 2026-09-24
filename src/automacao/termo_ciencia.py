"""
termo_ciencia.py — Geração do Termo de Ciência preenchido
=============================================================================
Portado de AUTO_SERE/termo_ciencia.py para src/automacao/termo_ciencia.py.

Preenche o modelo "MODELO DE TERMO DE CIENCIA.docx" com a lista de
funcionários de uma escola, a partir de funcionarios_matriculas.json:
  - Usa TODOS os funcionários do JSON que tenham matrícula (numcad) válida.
  - Para cada um, acrescenta uma linha na tabela do modelo com
    NOME | MATRÍCULA | DATA (em branco) | ASSINATURA (em branco).
  - Salva um novo .docx (o modelo original nunca é alterado).

Requisitos: pip install python-docx

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Localização do modelo: o original subia pastas a partir de onde o
   script estava salvo até achar uma pasta chamada "ESCOLA JUDITH"
   (caminho fixo do servidor Linux) — não fazia sentido na nova
   arquitetura (instalação Windows). Decisão do usuário (02/09/2026):
   caminho configurável separadamente, via nova chave
   src.comum.configuracao.pasta_modelos() (com
   definir_pasta_modelos() para o setup) — modelos de documento a
   preencher são conceito diferente da pasta de digitalização (documentos
   escaneados dos alunos).

2. funcionarios_matriculas.json: antes buscado perto do próprio script ou
   no diretório de trabalho (Path.cwd()). Agora vem de
   src.comum.paths.dados_ano_atual() — a mesma pasta de dados de trabalho
   de todos os outros scripts já portados (mesmo que o script que GERA
   esse arquivo, funcionarios.py/servidores.py, ainda não tenha sido
   portado nesta jornada — decisão do usuário, preparando o terreno).

3. Interatividade: o original pedia o TEMA e a confirmação de geração via
   input(). Decisão do usuário (02/09/2026, mesma já tomada para os modos
   de sere_2026.py e processo_transferidos.py): removida — gerar_termo()
   recebe `tema` como parâmetro obrigatório e não pede confirmação
   (quem chama decide se quer confirmar antes, ex.: uma futura GUI
   mostrando a lista de funcionários num diálogo antes de clicar
   "Gerar"). argparse removido — todos os caminhos e opções agora são
   parâmetros de função.

Toda a lógica de negócio (extração de candidatos a partir de
vinculos_servidores, deduplicação por nome+matrícula, substituição de
marcadores #TEMA/#NOME_ESCOLA preservando formatação, clonagem da linha de
cabeçalho da tabela) é idêntica ao original — nenhuma regra foi alterada.

Uso:
    from src.automacao.termo_ciencia import gerar_termo

    resultado = gerar_termo(tema="DE NOTEBOOK")
    print(resultado["saida_path"])
"""

from __future__ import annotations

import copy
import json
import os
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from docx import Document
from docx.oxml.ns import qn

from src.comum import paths as _paths
from src.comum.configuracao import pasta_modelos

NOME_MODELO = "MODELO DE TERMO DE CIENCIA.docx"

_DADOS = _paths.dados_ano_atual()


# --------------------------------------------------------------------------
# Localização de arquivos
# --------------------------------------------------------------------------

def template_padrao() -> Optional[Path]:
    """
    Retorna o caminho do modelo dentro da pasta de modelos configurada
    pelo usuário (src.comum.configuracao.pasta_modelos), ou None se essa
    pasta ainda não foi configurada ou o modelo não existir nela.
    """
    base = pasta_modelos()
    if base is None:
        return None
    candidato = base / NOME_MODELO
    return candidato if candidato.is_file() else None


def json_padrao() -> Path:
    """Caminho padrão de funcionarios_matriculas.json — dados de trabalho do ano corrente."""
    return _DADOS / "funcionarios_matriculas.json"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def normalizar(texto) -> str:
    """Remove acentos e deixa em maiúsculas, para comparação sem case/acento."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper().strip()


def carregar_funcionarios(json_path: Path) -> list[dict]:
    if not json_path.is_file():
        raise FileNotFoundError(f"Arquivo JSON não encontrado: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extrair_candidatos(funcionario: dict, sem_matricula: Optional[list] = None) -> list[tuple]:
    """
    Retorna uma lista de tuplas (nome, matricula, nomemp) para um funcionário.
    Todo funcionário do JSON é considerado (o arquivo já é específico da
    escola) — só é preciso ter uma matrícula válida.

    Prioriza os vínculos detalhados em 'vinculos_servidores' (um funcionário
    pode ter mais de uma matrícula / mais de um vínculo); se não houver essa
    lista, usa os campos de nível superior (numcad / nomemp).
    Lembrete: numcad == matricula.

    Se 'sem_matricula' (lista) for passado, nomes sem numcad válido são
    anotados ali (para diagnóstico).
    """
    nome = funcionario.get("nome")
    candidatos = []

    vinculos = funcionario.get("vinculos_servidores") or []
    if vinculos:
        for v in vinculos:
            nomemp = v.get("nomemp")
            numcad = v.get("numcad")
            if numcad in (None, 0):
                continue
            candidatos.append((nome, numcad, nomemp))
    else:
        nomemp = funcionario.get("nomemp")
        numcad = funcionario.get("numcad")
        if numcad not in (None, 0):
            candidatos.append((nome, numcad, nomemp))

    if not candidatos and sem_matricula is not None:
        sem_matricula.append(nome)

    return candidatos


def montar_lista(funcionarios: list[dict]) -> tuple[list[dict], list[str]]:
    linhas = []
    vistos = set()
    sem_matricula: list[str] = []
    for func in funcionarios:
        for nome, matricula, nomemp in extrair_candidatos(func, sem_matricula):
            chave = (normalizar(nome), matricula)
            if chave in vistos:
                continue
            vistos.add(chave)
            linhas.append({"nome": nome, "matricula": matricula, "nomemp": nomemp})
    linhas.sort(key=lambda x: normalizar(x["nome"]))
    return linhas, sorted(set(sem_matricula))


# --------------------------------------------------------------------------
# Geração do .docx
# --------------------------------------------------------------------------

def substituir_no_paragrafo(paragrafo, marcador: str, valor: str) -> None:
    """Substitui um marcador (#TEMA, #NOME_ESCOLA, ...) preservando a
    formatação do run onde ele aparece."""
    for run in paragrafo.runs:
        if marcador in run.text:
            run.text = run.text.replace(marcador, valor)


def substituir_marcadores(doc, substituicoes: dict) -> None:
    for paragrafo in doc.paragraphs:
        for marcador, valor in substituicoes.items():
            substituir_no_paragrafo(paragrafo, marcador, valor)
    # marcadores também podem estar dentro de tabelas
    for tabela in doc.tables:
        for linha in tabela.rows:
            for celula in linha.cells:
                for paragrafo in celula.paragraphs:
                    for marcador, valor in substituicoes.items():
                        substituir_no_paragrafo(paragrafo, marcador, valor)


def limpar_celula(tc) -> None:
    """Remove a negrito e o texto de uma célula clonada (mantém bordas/estilo)."""
    for r in tc.findall(".//" + qn("w:r")):
        rpr = r.find(qn("w:rPr"))
        if rpr is None:
            continue
        for tag in (qn("w:b"), qn("w:bCs")):
            el = rpr.find(tag)
            if el is not None:
                rpr.remove(el)


def definir_texto_celula(tc, texto: str) -> None:
    """Define o texto de uma célula clonada, mantendo apenas um run/texto."""
    ts = tc.findall(".//" + qn("w:t"))
    if not ts:
        return
    ts[0].text = texto
    ts[0].set(qn("xml:space"), "preserve")
    # remove runs/<w:t> extras (ex.: célula "# NOME" tinha 2 runs)
    for t_extra in ts[1:]:
        r_pai = t_extra.getparent()
        r_pai.getparent().remove(r_pai)


def adicionar_linha(tabela, nome: str, matricula) -> None:
    """Clona a linha de cabeçalho da tabela e insere nome/matrícula,
    deixando DATA e ASSINATURA em branco para preenchimento manual."""
    tr_cabecalho = tabela.rows[0]._tr
    nova_tr = copy.deepcopy(tr_cabecalho)

    tcs = nova_tr.findall(qn("w:tc"))
    valores = [nome, str(matricula), "", ""]
    for tc, valor in zip(tcs, valores):
        limpar_celula(tc)
        definir_texto_celula(tc, valor)

    tabela._tbl.append(nova_tr)


def gerar_documento(
    template_path: Path,
    saida_path: Path,
    tema: str,
    nome_escola: str,
    linhas: list[dict],
) -> None:
    doc = Document(str(template_path))

    substituicoes = {
        "#TEMA": f" {tema}".rstrip() if tema else "",
        "#NOME_ESCOLA": nome_escola or "",
    }
    substituir_marcadores(doc, substituicoes)

    if not doc.tables:
        raise ValueError("Não encontrei a tabela de assinaturas no modelo.")
    tabela = doc.tables[0]

    for item in linhas:
        adicionar_linha(tabela, item["nome"], item["matricula"])

    saida_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(saida_path))


# --------------------------------------------------------------------------
# Ponto de entrada (pronto para uma futura GUI)
# --------------------------------------------------------------------------

def preparar_lista_funcionarios(
    json_path: Optional[Path] = None,
) -> dict:
    """
    Carrega funcionarios_matriculas.json e monta a lista de funcionários
    elegíveis (com matrícula válida), sem gerar nenhum documento ainda.

    Pensada para uma futura GUI mostrar a lista de funcionários e o nome
    da escola detectado ANTES do usuário confirmar a geração — equivalente
    à parte do main() original que imprimia a lista e perguntava
    "Gerar o documento com esta lista? [S/n]" antes do input() do tema.

    Retorna um dict com: linhas, sem_matricula, nome_escola_sugerido.
    Levanta FileNotFoundError se o JSON não existir, ValueError se
    nenhum funcionário com matrícula válida for encontrado.
    """
    json_path = json_path or json_padrao()

    funcionarios = carregar_funcionarios(json_path)
    linhas, sem_matricula = montar_lista(funcionarios)

    if not linhas:
        raise ValueError(
            f"Nenhum funcionário com matrícula (numcad) válida foi encontrado em {json_path}."
        )

    nomes_unidade = [x["nomemp"] for x in linhas if x["nomemp"]]
    nome_escola_sugerido = max(set(nomes_unidade), key=nomes_unidade.count) if nomes_unidade else ""

    return {
        "linhas": linhas,
        "sem_matricula": sem_matricula,
        "nome_escola_sugerido": nome_escola_sugerido,
    }


def gerar_termo(
    tema: str,
    nome_escola: Optional[str] = None,
    json_path: Optional[Path] = None,
    template_path: Optional[Path] = None,
    saida_path: Optional[Path] = None,
) -> dict:
    """
    Gera o Termo de Ciência preenchido. Renomeada de main() no original —
    decisão do usuário (02/09/2026): sem input()/argparse, `tema` é
    parâmetro obrigatório (antes era perguntado interativamente), sem
    confirmação pedida aqui (quem chamar — ex.: uma futura GUI — decide se
    quer mostrar a lista para confirmação antes, usando
    preparar_lista_funcionarios() para isso).

    `nome_escola`: se omitido, usa o nomemp mais comum no JSON (mesmo
    comportamento do original quando --nome-escola não era passado).

    Levanta FileNotFoundError (modelo ou JSON não encontrado) ou
    ValueError (nenhum funcionário elegível, ou tabela ausente no modelo)
    em vez de sys.exit() — quem chamar decide como tratar.

    Retorna um dict com: saida_path, linhas, sem_matricula, nome_escola.
    """
    template_path = template_path or template_padrao()
    if template_path is None:
        raise FileNotFoundError(
            f"Modelo '{NOME_MODELO}' não encontrado na pasta de modelos configurada "
            "(ver src.comum.configuracao.pasta_modelos). Configure a pasta de modelos "
            "ou informe template_path explicitamente."
        )

    info = preparar_lista_funcionarios(json_path)
    linhas         = info["linhas"]
    sem_matricula  = info["sem_matricula"]
    nome_escola    = nome_escola or info["nome_escola_sugerido"]

    tema = tema.upper()

    if saida_path is None:
        pasta = template_path.parent
        data_str = datetime.now().strftime("%Y-%m-%d")
        tema_arquivo = "".join(c if c.isalnum() or c in " -" else "" for c in tema).strip()
        saida_path = pasta / f"TERMO DE CIENCIA - {tema_arquivo} - {data_str}.docx"

    gerar_documento(template_path, saida_path, tema, nome_escola, linhas)

    print(f"Documento gerado com sucesso:\n  {saida_path}")
    if sem_matricula:
        print(f"[AVISO] {len(sem_matricula)} funcionário(s) sem matrícula (numcad) válida "
              "foram ignorados:")
        for nome in sem_matricula:
            print(f"  - {nome}")

    return {
        "saida_path": saida_path,
        "linhas": linhas,
        "sem_matricula": sem_matricula,
        "nome_escola": nome_escola,
    }


if __name__ == "__main__":
    # Uso mínimo por linha de comando, sem input() — para rodar diretamente
    # é preciso informar o tema; para um fluxo interativo de terminal,
    # construa um wrapper próprio que chame preparar_lista_funcionarios()
    # e gerar_termo() com o tema já decidido.
    import sys
    if len(sys.argv) < 2:
        print("Uso: python -m src.automacao.termo_ciencia \"TEMA DO TERMO\"")
        sys.exit(1)
    gerar_termo(tema=sys.argv[1])

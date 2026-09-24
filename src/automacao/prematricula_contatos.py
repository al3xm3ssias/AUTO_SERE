"""
prematricula_contatos.py — Etapa 3: Geração do CSV de Contatos
=============================================================================
Portado de AUTO_SERE/pre_matricula.py (extrair_turma_e_aluno, extrair_cep,
processar_contatos, obter_colunas_template, exportar_csv, etapa_contatos)
para src/automacao/prematricula_contatos.py.

A partir dos cadastros coletados na Etapa 2 (ver
src.automacao.prematricula_cadastro), agrupa os responsáveis por
telefone (ou nome, se sem telefone) — assim, irmãos com o mesmo
responsável viram UM único contato, listando as turmas e nomes dos alunos
no próprio "First Name" — e exporta um CSV no formato de importação do
Google Contacts, pronto para importar na agenda telefônica da secretaria.

Esta etapa é 100% offline: não usa Playwright, só processa os dados já
coletados nas Etapas 1/2.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Caminhos: CONTATOS_FILE (antes fixo, servidor Linux, com a data do dia
   no nome) agora vai para src.comum.paths.dados_ano_atual(). TEMPLATE_FILE
   (opcional — cabeçalho customizado do CSV) agora vem de
   src.comum.configuracao.pasta_modelos(), a mesma pasta configurável já
   usada por src.automacao.termo_ciencia para outros modelos de
   documento — mas continua sendo OPCIONAL: se não configurado ou o
   arquivo não existir, cai no fallback de colunas padrão do Google
   Contacts, exatamente como o original.

2. ANO_ATUAL: vem de src.comum.paths.ano_atual() (já usada por
   src.automacao.prematricula_coleta), em vez de uma chamada local.

3. etapa_contatos() RENOMEADA para gerar_csv_contatos(dados_cadastros,
   dados_prematricula) — mesma lógica e assinatura de entrada.

4. NOVA: executar_prematricula_contatos(dados_cadastros=None,
   dados_prematricula=None) — ponto de entrada pronto para um futuro
   botão de GUI (decisão do usuário, 03/09/2026): se os dois parâmetros
   não forem informados, lê pre_matricula.json do disco (cadastros e
   turmas_intencao) — permite rodar esta etapa isoladamente, sem repetir
   as etapas 1/2. Sem argparse, sem input().

Toda a lógica de negócio (agrupamento por telefone/responsável, extração
de CEP do endereço por heurística de posição de token com hífen, formato
"TURMA - ANO - RESPONSAVEL DO ALUNO", e o formato de colunas do Google
Contacts) é idêntica ao original — nenhuma regra foi alterada. A correção
de bug já documentada no código original (Etapa 2 retorna dict por CPF,
não list — tratar como "um único aluno" zerava os contatos processados)
também foi preservada tal como estava, já corrigida.

Uso:
    from src.automacao.prematricula_contatos import executar_prematricula_contatos

    contatos = executar_prematricula_contatos()
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.comum import paths as _paths
from src.comum.configuracao import pasta_modelos

ANO_ATUAL = _paths.ano_atual()

_DADOS = _paths.dados_ano_atual()

DATA_HOJE = datetime.now().strftime("%Y%m%d")
CONTATOS_FILE: Path = _DADOS / f"TEMPLATE_PREENCHIDO_{DATA_HOJE}.csv"

NOME_TEMPLATE_CSV = "Google Contacts Import Template.csv"

COLUNAS_PADRAO_GOOGLE_CONTACTS = [
    "Name Prefix", "First Name", "Middle Name", "Last Name", "Name Suffix",
    "Phonetic First Name", "Phonetic Middle Name", "Phonetic Last Name",
    "Nickname", "File As", "E-mail 1 - Label", "E-mail 1 - Value",
    "Phone 1 - Label", "Phone 1 - Value", "Address 1 - Label",
    "Address 1 - Country", "Address 1 - Street", "Address 1 - Extended Address",
    "Address 1 - City", "Address 1 - Region", "Address 1 - Postal Code",
    "Address 1 - PO Box", "Organization Name", "Organization Title",
    "Organization Department", "Birthday", "Event 1 - Label", "Event 1 - Value",
    "Relation 1 - Label", "Relation 1 - Value", "Website 1 - Label",
    "Website 1 - Value", "Custom Field 1 - Label", "Custom Field 1 - Value",
    "Notes", "Labels",
]


def extrair_turma_e_aluno(cpf: str, dados_prematricula: dict) -> tuple[Optional[str], Optional[str]]:
    """
    A Etapa 1 devolve o resultado em memória usando a chave "turmas", mas
    o mesmo dado é persistido no pre_matricula.json sob a chave
    "turmas_intencao". Aceitar as duas evita que esta etapa fique
    silenciosamente com 0 contatos caso `dados_prematricula` venha do
    pre_matricula.json carregado direto do disco (chave
    "turmas_intencao") em vez do retorno em memória da Etapa 1 (chave
    "turmas").
    """
    turmas = dados_prematricula.get("turmas") or dados_prematricula.get("turmas_intencao") or {}
    for turma, alunos in turmas.items():
        for aluno in alunos:
            if aluno.get("cpf") == cpf or aluno.get("tr_id") == cpf:
                turma_limpa = turma.replace(" do Ensino Fundamental", "").strip()
                return turma_limpa, aluno.get("nome", "")
    return None, None


def extrair_cep(endereco: str) -> str:
    """Heurística simples: primeiro token com 8+ caracteres contendo hífen."""
    partes = endereco.split()
    for parte in partes:
        if len(parte) >= 8 and "-" in parte:
            return parte
    return ""


def processar_contatos(dados_alunos, dados_prematricula: dict) -> list[dict]:
    """
    Monta a lista de contatos no formato Google Contacts a partir dos
    cadastros coletados na Etapa 2.

    `dados_alunos`: aceita list, dict {cpf: aluno_dados} (o formato real
    devolvido pela Etapa 2 e persistido em pre_matricula.json["cadastros"]),
    ou um único registro de aluno solto (dict que já tem "cpf" como chave
    de primeiro nível).
    """
    if isinstance(dados_alunos, list):
        alunos_list = dados_alunos
    elif isinstance(dados_alunos, dict):
        if "cpf" in dados_alunos:
            alunos_list = [dados_alunos]
        else:
            alunos_list = list(dados_alunos.values())
    else:
        alunos_list = []

    agrupados = defaultdict(list)

    for aluno in alunos_list:
        cpf = aluno.get("cpf", "")
        nome_responsavel = aluno.get("nome_responsavel", "").strip()
        telefone = aluno.get("telefone", "").strip()
        email = aluno.get("email", "").strip()
        endereco = aluno.get("endereco", "").strip()

        turma, nome_aluno = extrair_turma_e_aluno(cpf, dados_prematricula)
        if not turma or not nome_responsavel:
            continue

        chave = telefone if telefone else nome_responsavel.lower()

        agrupados[chave].append(
            {
                "turma": turma,
                "nome_aluno": nome_aluno,
                "nome_responsavel": nome_responsavel,
                "telefone": telefone,
                "email": email,
                "endereco": endereco,
            }
        )

    contatos = []
    for chave, registros in agrupados.items():
        turmas = sorted(set(r["turma"] for r in registros))
        alunos = [r["nome_aluno"] for r in registros]
        responsavel = registros[0]["nome_responsavel"]
        telefone = registros[0]["telefone"]
        email = registros[0]["email"]
        endereco = registros[0]["endereco"]

        turmas_str = " E ".join(turmas)
        alunos_str = " E DO ".join(alunos)
        nome_prefix = f"{turmas_str} - {ANO_ATUAL} - RESPONSAVEL DO {alunos_str}"

        contato = {
            "First Name": nome_prefix,
            "E-mail 1 - Label": "Home",
            "E-mail 1 - Value": email,
            "Phone 1 - Label": "Mobile",
            "Phone 1 - Value": telefone,
            "Address 1 - Postal Code": extrair_cep(endereco),
            "Relation 1 - Value": responsavel,
            "Website 1 - Label": "Homepage",
            "Website 1 - Value": "",
            "Custom Field 1 - Label": "Endereço Completo",
            "Custom Field 1 - Value": endereco,
            "Labels - " + ANO_ATUAL: ANO_ATUAL,
        }
        contatos.append(contato)

    return contatos


def obter_colunas_template() -> list[str]:
    """
    Lê o cabeçalho de um CSV modelo (opcional), se configurado em
    src.comum.configuracao.pasta_modelos() (mesma pasta usada por
    src.automacao.termo_ciencia). Se não configurado, arquivo ausente, ou
    erro de leitura, cai no fallback de colunas padrão do Google
    Contacts — mesmo comportamento do original.
    """
    base = pasta_modelos()
    template_path = (base / NOME_TEMPLATE_CSV) if base else None

    if template_path and template_path.is_file():
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                return next(reader)
        except (OSError, StopIteration) as e:
            print(f"Aviso: erro ao ler template em {template_path}: {e}")

    print("Usando colunas padrão do Google Contacts...")
    return list(COLUNAS_PADRAO_GOOGLE_CONTACTS)


def exportar_csv(contatos: list[dict], contatos_file: Path = CONTATOS_FILE) -> None:
    try:
        colunas = obter_colunas_template()

        contatos_file.parent.mkdir(parents=True, exist_ok=True)
        with open(contatos_file, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=colunas, delimiter=",")
            writer.writeheader()

            for contato in contatos:
                row = {col: contato.get(col, "") for col in colunas}
                writer.writerow(row)

        print("✓ Arquivo CSV criado com sucesso!")
        print(f"✓ Arquivo salvo em: {contatos_file}")
        print(f"✓ Total de contatos exportados: {len(contatos)}")

    except Exception as e:
        print(f"Erro ao criar arquivo CSV: {e}")


# ==========================================================
# ETAPA 3 - GERAÇÃO DO CSV
# ==========================================================

def gerar_csv_contatos(
    dados_cadastros,
    dados_prematricula: dict,
    contatos_file: Path = CONTATOS_FILE,
) -> list[dict]:
    """
    Executa a Etapa 3: agrupa os cadastros coletados na Etapa 2 por
    telefone/responsável e exporta o CSV no formato Google Contacts.

    `dados_cadastros`: o dicionário {cpf: aluno_dados} retornado pela
    Etapa 2 (ver src.automacao.prematricula_cadastro), ou o equivalente
    carregado de pre_matricula.json["cadastros"].
    `dados_prematricula`: o resultado da Etapa 1 (chave "turmas") ou o
    pre_matricula.json carregado do disco (chave "turmas_intencao") — ver
    extrair_turma_e_aluno() para os dois formatos aceitos.

    Retorna a lista de contatos gerados (vazia se nenhum contato pôde ser
    montado — nesse caso nenhum CSV é escrito, mesmo comportamento do
    original).
    """
    print("\n" + "=" * 60)
    print("ETAPA 3/4 - GERAÇÃO DO CSV DE CONTATOS")
    print("=" * 60)

    contatos = processar_contatos(dados_cadastros, dados_prematricula)

    if not contatos:
        print("Nenhum contato foi processado. Verifique os dados coletados.")
        return []

    print(f"Total de contatos processados: {len(contatos)}\n")
    print("Preview dos contatos:")
    print("-" * 60)
    for i, contato in enumerate(contatos[:3], 1):
        print(f"{i}. {contato['First Name']}")
        print(f"   E-mail: {contato['E-mail 1 - Value']}")
        print(f"   Telefone: {contato['Phone 1 - Value']}")
        print(f"   CEP: {contato['Address 1 - Postal Code']}\n")
    if len(contatos) > 3:
        print(f"... e mais {len(contatos) - 3} contatos\n")

    print("Gerando arquivo CSV...")
    exportar_csv(contatos, contatos_file=contatos_file)

    return contatos


# ==========================================================
# ENTRY POINT (pronto para uma futura GUI)
# ==========================================================

def executar_prematricula_contatos(
    dados_cadastros: Optional[dict] = None,
    dados_prematricula: Optional[dict] = None,
) -> list[dict]:
    """
    Ponto de entrada: se `dados_cadastros`/`dados_prematricula` não forem
    informados, carrega pre_matricula.json do disco (seções "cadastros" e
    "turmas_intencao") — permite rodar só esta etapa isoladamente, sem
    repetir as Etapas 1/2. 100% offline, não abre navegador.

    Pronta para ser chamada por um futuro botão de GUI (decisão do
    usuário, 03/09/2026, mesmo padrão de src.automacao.sere_2026): sem
    argparse, sem input().

    Retorna a lista de contatos gerados.
    """
    if dados_cadastros is None or dados_prematricula is None:
        # Import local para evitar acoplamento desnecessário no topo do
        # módulo — só é preciso quando os dados não são fornecidos.
        from src.automacao.prematricula_coleta import carregar_pre_matricula

        pre_matricula = carregar_pre_matricula()
        if dados_cadastros is None:
            dados_cadastros = pre_matricula.get("cadastros", {})
        if dados_prematricula is None:
            dados_prematricula = pre_matricula

    return gerar_csv_contatos(dados_cadastros, dados_prematricula)


if __name__ == "__main__":
    executar_prematricula_contatos()

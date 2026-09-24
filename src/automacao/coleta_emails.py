"""
coleta_emails.py — Coleta de escolas municipais no site da SME
=============================================================================
Portado de AUTO_SERE/coleta_emails.py para src/automacao/coleta_emails.py.

Raspa as páginas públicas da Secretaria Municipal de Educação de Ponta
Grossa (sme.pontagrossa.pr.gov.br) listando TODAS as escolas municipais e
CMEIs do município (nome, endereço, ramal, email), salvando em
escolas_completas.json.

Este é um script de PRÉ-REQUISITO de instalação (decisão do usuário,
03/09/2026): deve rodar antes do setup escolher qual é a unidade escolar
do usuário — o resultado (escolas_completas.json) alimenta um seletor
pesquisável na interface de setup, de onde o usuário escolhe sua escola
por nome (ver src.comum.configuracao para onde a escolha final é
persistida, e src.automacao.cep_api, que consome o endereço da escola
escolhida).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Caminho de saída: ARQUIVO_SAIDA (antes um nome de arquivo relativo,
   "escolas_completas.json", dependente do diretório de execução) agora
   vem de src.comum.paths.dados_ano_atual() — mesma arquitetura dos
   demais scripts já portados. Diferente da maioria dos outros JSONs de
   dados de trabalho, este NÃO é específico do ano letivo (a lista de
   escolas do município não muda por ano), mas fica na mesma pasta por
   simplicidade e consistência com o restante do projeto.

2. main() RENOMEADA para coletar_escolas_municipais() — sem argparse
   (não tinha nenhum no original), sem side effect de import (o original
   já usava `if __name__ == "__main__":` corretamente, então nesse ponto
   não havia nada para corrigir) — só a troca de nome para o mesmo padrão
   dos demais módulos já portados, e passou a retornar o dicionário
   coletado (antes só imprimia o total).

Toda a lógica de raspagem (extração da tabela #tablepress-3 ou fallback
por classe .tablepress, limpeza de texto, tratamento de erro por URL) é
idêntica ao original — nenhuma regra de negócio foi alterada.

Uso:
    from src.automacao.coleta_emails import coletar_escolas_municipais

    resultado = coletar_escolas_municipais()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.comum import paths as _paths

URLS = [
    "https://sme.pontagrossa.pr.gov.br/escolas-municipais/",
    "https://sme.pontagrossa.pr.gov.br/unidades-escolares/cmeis-2/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

ARQUIVO_SAIDA: Path = _paths.dados_ano_atual() / "escolas_completas.json"


def limpar_texto(texto: Optional[str]) -> str:
    """Remove espaços extras e quebras de linha."""
    if texto:
        return " ".join(texto.split()).strip()
    return ""


def extrair_dados_tabela(soup: BeautifulSoup) -> list[dict]:
    """
    Procura a tabela com id 'tablepress-3' e extrai linhas.
    Retorna lista de dicionários com: nome, endereco, ramal, email.
    """
    tabela = soup.find("table", id="tablepress-3")
    if not tabela:
        # Tenta achar qualquer table com classe tablepress
        tabela = soup.find("table", class_="tablepress")
    if not tabela:
        print("   ⚠️ Tabela não encontrada.")
        return []

    dados = []
    tbody = tabela.find("tbody")
    if not tbody:
        print("   ⚠️ <tbody> não encontrado.")
        return []

    linhas = tbody.find_all("tr")
    for linha in linhas:
        colunas = linha.find_all("td")
        if len(colunas) >= 4:
            nome = limpar_texto(colunas[0].get_text())
            endereco = limpar_texto(colunas[1].get_text())
            ramal = limpar_texto(colunas[2].get_text())
            email = limpar_texto(colunas[3].get_text())
            # Filtra linhas vazias (caso existam)
            if nome or email:
                dados.append({
                    "nome": nome,
                    "endereco": endereco,
                    "ramal": ramal,
                    "email": email,
                })
    return dados


def coletar_dados(url: str) -> list[dict]:
    try:
        print(f"🔄 Acessando: {url}")
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        dados = extrair_dados_tabela(soup)
        print(f"   ✅ Encontrados {len(dados)} registros em {url}")
        return dados
    except Exception as e:
        print(f"   ❌ Erro em {url}: {e}")
        return []


def coletar_escolas_municipais(arquivo_saida: Path = ARQUIVO_SAIDA) -> dict:
    """
    Coleta todas as escolas municipais e CMEIs listados nas páginas da SME
    e salva o resultado consolidado em `arquivo_saida` (escolas_completas.json,
    por padrão).

    Renomeada de main() no original — mesmo padrão dos demais módulos já
    portados. Retorna o dicionário completo coletado (chave = último
    segmento da URL, valor = {url, quantidade, escolas}).
    """
    todos: dict = {}
    for url in URLS:
        dados = coletar_dados(url)
        chave = url.rstrip("/").split("/")[-1] or "pagina"
        todos[chave] = {
            "url": url,
            "quantidade": len(dados),
            "escolas": dados,
        }

    arquivo_saida.parent.mkdir(parents=True, exist_ok=True)
    with open(arquivo_saida, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

    total = sum(item["quantidade"] for item in todos.values())
    print(f"\n✅ Coleta finalizada! {total} registros salvos em '{arquivo_saida}'")

    return todos


def listar_nomes_escolas(arquivo_saida: Path = ARQUIVO_SAIDA) -> list[str]:
    """
    Lê escolas_completas.json (já coletado) e retorna a lista simples de
    nomes de todas as escolas, para popular um seletor pesquisável na
    interface de setup (decisão do usuário, 03/09/2026: o usuário escolhe
    sua escola por nome num select digitável, em vez de digitar o nome
    manualmente).

    Levanta FileNotFoundError se coletar_escolas_municipais() ainda não
    tiver sido executado.
    """
    if not arquivo_saida.exists():
        raise FileNotFoundError(
            f"{arquivo_saida} não encontrado — rode coletar_escolas_municipais() primeiro."
        )

    with open(arquivo_saida, encoding="utf-8") as f:
        dados = json.load(f)

    nomes = []
    for pagina in dados.values():
        for escola in pagina.get("escolas", []):
            nome = escola.get("nome", "").strip()
            if nome:
                nomes.append(nome)
    return nomes


def buscar_escola_por_nome(nome: str, arquivo_saida: Path = ARQUIVO_SAIDA) -> Optional[dict]:
    """
    Retorna o registro completo ({nome, endereco, ramal, email}) da escola
    cujo nome bate exatamente com `nome`, ou None se não encontrada.

    Usada por src.comum.configuracao (via um futuro fluxo de setup) para
    recuperar o endereço da escola escolhida pelo usuário no seletor.
    """
    if not arquivo_saida.exists():
        raise FileNotFoundError(
            f"{arquivo_saida} não encontrado — rode coletar_escolas_municipais() primeiro."
        )

    with open(arquivo_saida, encoding="utf-8") as f:
        dados = json.load(f)

    for pagina in dados.values():
        for escola in pagina.get("escolas", []):
            if escola.get("nome", "").strip() == nome.strip():
                return escola
    return None


if __name__ == "__main__":
    coletar_escolas_municipais()

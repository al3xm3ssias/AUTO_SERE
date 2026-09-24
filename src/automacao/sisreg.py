"""
sisreg.py — Consulta de encaminhamentos SISREG por CPF de aluno
=============================================================================
Portado de AUTO_SERE/SISREG.py para src/automacao/sisreg.py.

Para cada aluno em alunos.json, consulta o sistema público de regulação
de saúde SISREG/FMS de Ponta Grossa
(fms.pontagrossa.pr.gov.br/lista-espera-sisreg-cpf) pelo CPF, e — se
houver algum encaminhamento/procedimento em fila de espera — registra o
aluno, CPF e a lista de encaminhamentos em alunos_encaminhamento.json.
Não requer login (o formulário consultado é público).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Caminhos: BASE_DIR fixo (servidor Linux) trocado por
   src.comum.paths.dados_ano_atual() — mesma arquitetura dos demais
   scripts já portados. INPUT_FILE/OUTPUT_FILE derivam dali.

2. consultar_cpfs() RENOMEADA para consultar_encaminhamentos_sisreg() —
   mesmo padrão de nomes usado pelos outros pontos de entrada já
   portados. O corpo (que já era uma função async no original, mas
   disparada por um `asyncio.run()` solto no nível do módulo) agora só é
   chamado dentro de `if __name__ == "__main__":`.

Toda a lógica de negócio (validação de CPF por comprimento — a docstring
original já sinalizava que essa validação é frágil se o CPF estiver
salvo com máscara, ver observação preservada abaixo —, timeout de 3s na
espera pela tabela, tratamento assimétrico entre CPF inválido — sempre
registrado — e sem encaminhamento — omitido do resultado) é idêntica ao
original — nenhuma regra foi alterada.

NOTA HERDADA DO ORIGINAL (não corrigida — apenas preservada e
documentada, já que corrigi-la mudaria o comportamento de filtragem sem
confirmação do usuário): a validação de CPF verifica só o COMPRIMENTO
(11 caracteres), sem remover pontuação. Se alunos.json guardar o CPF com
máscara (ex.: "123.456.789-00", 14 caracteres), o registro será
classificado como "CPF inválido" mesmo sendo um CPF válido. Vale
confirmar o formato salvo por src.automacao.alunos antes de considerar
isso um bug a corrigir.

Uso:
    import asyncio
    from src.automacao.sisreg import consultar_encaminhamentos_sisreg

    asyncio.run(consultar_encaminhamentos_sisreg())
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from src.comum import paths as _paths

URL = "https://fms.pontagrossa.pr.gov.br/lista-espera-sisreg-cpf"

_DADOS = _paths.dados_ano_atual()

INPUT_FILE  = _DADOS / "alunos.json"
OUTPUT_FILE = _DADOS / "alunos_encaminhamento.json"


async def consultar_encaminhamentos_sisreg(
    input_file: Path = INPUT_FILE,
    output_file: Path = OUTPUT_FILE,
) -> list[dict]:
    """
    Para cada aluno em `input_file` (alunos.json, por padrão), consulta o
    SISREG pelo CPF. Alunos com CPF inválido (não 11 caracteres) são
    sempre registrados no resultado com encaminhamentos=[] e
    erro="CPF inválido" (para auditoria de cadastro); alunos sem nenhum
    encaminhamento encontrado (timeout na tabela) são omitidos do
    resultado.

    Salva o resultado consolidado em `output_file`
    (alunos_encaminhamento.json, por padrão) e o retorna também em
    memória.
    """
    with open(input_file, "r", encoding="utf-8") as f:
        alunos = json.load(f)

    resultados: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for aluno in alunos:
            cpf = aluno.get("CPF", "").strip()
            nome = aluno.get("Nome", "")

            if not cpf or len(cpf) != 11:
                print(f"CPF inválido para {nome}")
                resultados.append({
                    "nome": nome,
                    "cpf": cpf,
                    "encaminhamentos": [],
                    "erro": "CPF inválido",
                })
                continue

            print(f"Consultando: {nome} - {cpf}")

            try:
                await page.goto(URL)

                await page.fill("#cpf-mask", cpf)
                await page.click("button[type='submit']")

                await page.wait_for_selector("table.table tbody tr", timeout=3000)

                linhas = await page.query_selector_all("table.table tbody tr")

                encaminhamentos = []

                for linha in linhas:
                    colunas = await linha.query_selector_all("td")
                    textos = [await col.inner_text() for col in colunas]

                    if len(textos) >= 4:
                        encaminhamentos.append({
                            "data_solicitacao": textos[0].strip(),
                            "procedimento": textos[1].strip(),
                            "data_nascimento": textos[2].strip(),
                            "posicao_fila": textos[3].strip(),
                        })

                if encaminhamentos:
                    resultados.append({
                        "nome": nome,
                        "cpf": cpf,
                        "encaminhamentos": encaminhamentos,
                    })

            except PlaywrightTimeoutError:
                print(f"Nenhum encaminhamento encontrado para {nome}")
                # Sem encaminhamentos = não salva

        await browser.close()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=4)

    print(f"Arquivo {output_file.name} criado com sucesso.")

    return resultados


if __name__ == "__main__":
    asyncio.run(consultar_encaminhamentos_sisreg())

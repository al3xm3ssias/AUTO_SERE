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
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from src.comum import paths as _paths

URL = "https://fms.pontagrossa.pr.gov.br/lista-espera-sisreg-cpf"

_DADOS = _paths.dados_ano_atual()

INPUT_FILE  = _DADOS / "alunos.json"
OUTPUT_FILE = _DADOS / "alunos_encaminhamento.json"


def _mesclar_com_anterior(arquivo: Path, novos: list[dict], cgms: set, cpfs: set) -> list[dict]:
    """
    Resultado da consulta parcial + o que já estava no arquivo para quem NÃO foi consultado.
    Quem foi consultado é identificado pelo CGM (ou, em registros antigos sem CGM, pelo CPF).
    """
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            anterior = json.load(f)
        if not isinstance(anterior, list):
            raise ValueError("formato inesperado")
    except FileNotFoundError:
        return novos
    except (ValueError, OSError):
        print(f"Aviso: não consegui ler o resultado anterior em {arquivo.name}; gravando só os consultados agora.")
        return novos

    def foi_consultado(registro) -> bool:
        if not isinstance(registro, dict):
            return False
        if str(registro.get("cgm", "")).strip() in cgms:
            return True
        return normalizar_cpf(registro.get("cpf")) in cpfs

    preservados = [r for r in anterior if isinstance(r, dict) and not foi_consultado(r)]
    print(f"Mantidos {len(preservados)} registro(s) anteriores de alunos não consultados.")
    return preservados + novos


def normalizar_cpf(valor) -> str:
    """Só os dígitos do CPF ("123.456.789-00" → "12345678900")."""
    return re.sub(r"\D", "", str(valor or ""))


async def consultar_encaminhamentos_sisreg(
    input_file: Optional[Path] = None,
    output_file: Optional[Path] = None,
    cgms=None,
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

    `cgms` (opcional): consulta SÓ esses alunos (por CGM). Nesse caso o resultado
    anterior dos demais alunos é PRESERVADO no arquivo (só os consultados são
    atualizados, inclusive removendo quem não tem mais encaminhamento). Sem `cgms`,
    consulta todos e o arquivo é reescrito por inteiro, como sempre foi.
    """
    # Resolvidos na hora (não na importação): respeita o ano letivo atual e facilita testar.
    input_file = Path(input_file) if input_file else _paths.dados_ano_atual() / "alunos.json"
    output_file = Path(output_file) if output_file else _paths.dados_ano_atual() / "alunos_encaminhamento.json"

    with open(input_file, "r", encoding="utf-8") as f:
        alunos = json.load(f)

    parcial = cgms is not None
    alvo_cgms = {str(c).strip() for c in (cgms or [])}
    if parcial:
        alunos = [a for a in alunos if str(a.get("CGM", "")).strip() in alvo_cgms]
        if not alunos:
            print("Nenhum dos alunos selecionados está em alunos.json: nada a consultar.")
            return []
        print(f"Consulta parcial: {len(alunos)} aluno(s) selecionado(s); os demais mantêm o resultado anterior.")
    cpfs_consultados = {normalizar_cpf(a.get("CPF")) for a in alunos} - {""}

    resultados: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for aluno in alunos:
            # Remove pontuação antes de validar: "123.456.789-00" é um CPF válido e antes
            # era recusado por ter 14 caracteres. CPFs só com dígitos não mudam de comportamento.
            cpf = normalizar_cpf(aluno.get("CPF"))
            nome = aluno.get("Nome", "")
            cgm = str(aluno.get("CGM", "")).strip()

            if len(cpf) != 11:
                print(f"CPF inválido para {nome}")
                resultados.append({
                    "nome": nome,
                    "cgm": cgm,
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
                        "cgm": cgm,
                        "cpf": cpf,
                        "encaminhamentos": encaminhamentos,
                    })

            except PlaywrightTimeoutError:
                print(f"Nenhum encaminhamento encontrado para {nome}")
                # Sem encaminhamentos = não salva

        await browser.close()

    if parcial:
        resultados = _mesclar_com_anterior(output_file, resultados, alvo_cgms, cpfs_consultados)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=4)

    print(f"Arquivo {output_file.name} criado com sucesso.")

    return resultados


if __name__ == "__main__":
    asyncio.run(consultar_encaminhamentos_sisreg())

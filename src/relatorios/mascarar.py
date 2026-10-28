"""
mascarar.py — Anonimização de dados pessoais para dados de teste/demonstração
=============================================================================
Portado de AUTO_SERE/mascarar.py para src/relatorios/mascarar.py.

Mascara TODOS os dados pessoais (substitui cada caractere alfanumérico por
'x', números por 0, booleanos por "x") dos JSONs de dados de trabalho,
gerando arquivos *_mask.json ao lado dos originais — úteis para
compartilhar estrutura de dados sem expor informação real de alunos ou
servidores (ex.: ao pedir ajuda de depuração, ou anexar exemplos em
documentação).

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Caminhos: o original usava Path.cwd() (diretório de onde o comando era
   executado) para localizar os JSONs — dependia de rodar o script na
   pasta certa. Agora usa src.comum.paths.dados_ano_atual(), a mesma pasta
   de dados de trabalho de todos os outros scripts já portados.

2. main() ajustada para retornar a lista de arquivos processados (em vez
   de só imprimir e retornar None), útil para quem chamar programaticamente
   verificar o resultado — comportamento de impressão no console
   preservado integralmente.

A lista de nomes de arquivo (target_names) foi mantida INTEGRALMENTE,
incluindo nomes de scripts ainda não portados nesta jornada
(pre_matricula.json, funcionarios*.json, resultado_cpf.json,
transferidos_base_abc.json, emails_senhas_5ano.json) — o script já lida
graciosamente com arquivos ausentes (avisa e ignora), então não há custo
em mantê-los na lista à espera de existirem no futuro.

A lógica de mascaramento (mask_value — recursiva sobre str/bool/int/float/
list/dict) é idêntica ao original — nenhuma regra foi alterada.

Uso:
    from src.relatorios.mascarar import main
    main()
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.comum import paths as _paths

_DADOS = _paths.dados_ano_atual()


def mask_value(value):
    """Aplica máscara total a qualquer valor."""
    if isinstance(value, str):
        return re.sub(r'[A-Za-zÀ-ÿ0-9]', 'x', value)
    elif isinstance(value, bool):
        return "x"
    elif isinstance(value, (int, float)):
        return 0
    elif isinstance(value, list):
        return [mask_value(item) for item in value]
    elif isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    else:
        return value


def main() -> list[Path]:
    """
    Mascara todos os JSONs de dados de trabalho reconhecidos que existirem
    em src.comum.paths.dados_ano_atual(), gerando um *_mask.json ao lado de
    cada um. Retorna a lista de arquivos de saída gerados.
    """
    target_names = [
        "aluno_completo.json",
        "alunos.json",
        "turmas.json",
        "alunos_pastas.json",
        "resultado_cpf.json",
        "transferidos_base_abc.json",
        "emails_senhas_5ano.json",
        "documentos-alunos-pc.json",
        "pre_matricula.json",
        "funcionarios.json",
        "funcionarios_completo.json",
        "funcionarios_matriculas.json",
    ]
    files_to_process = []

    for name in target_names:
        file_path = _DADOS / name
        if file_path.exists():
            files_to_process.append(file_path)
        else:
            print(f"Aviso: {name} não encontrado – será ignorado.")

    if not files_to_process:
        print("Nenhum dos arquivos esperados foi encontrado. Encerrando.")
        return []

    output_paths: list[Path] = []

    for file_path in files_to_process:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original = json.load(f)
        except Exception as e:
            print(f"Erro ao ler {file_path.name}: {e}")
            continue

        masked = mask_value(original)

        output_path = file_path.with_name(file_path.stem + "_mask.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(masked, f, indent=4, ensure_ascii=False)

        print(f"Arquivo mascarado: {file_path.name} -> {output_path.name}")
        output_paths.append(output_path)

    return output_paths


if __name__ == "__main__":
    main()

"""
Leitura e gravação segura de arquivos JSON de dados de trabalho.

Motivo: vários scripts tratavam um JSON ilegível como "vazio" e, na
gravação seguinte, sobrescreviam o histórico inteiro; e gravavam direto no
arquivo final, deixando-o truncado se o processo fosse interrompido no meio.

  - carregar_json(): arquivo inexistente -> valor padrão; arquivo existente
    mas ilegível (ou com tipo errado) -> ArquivoJsonCorrompidoError. O arquivo
    NUNCA é alterado por esta função.
  - salvar_json_atomico(): grava num temporário na mesma pasta e troca por
    os.replace(); em qualquer falha o arquivo anterior permanece intacto.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class ArquivoJsonCorrompidoError(Exception):
    """O arquivo existe, mas não pôde ser lido como o JSON esperado."""


def carregar_json(caminho, padrao, tipo_esperado=None, erro=ArquivoJsonCorrompidoError):
    """
    `padrao`: função sem argumentos que devolve o valor para arquivo
    inexistente (ex.: `list`, `dict`, ou um lambda). `erro`: classe de exceção
    a levantar (subclasse de ArquivoJsonCorrompidoError) para mensagens
    específicas do chamador.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return padrao()

    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise erro(
            f"{caminho} está ilegível ({e}). O arquivo não foi alterado; "
            "corrija-o ou restaure um backup antes de rodar de novo."
        ) from e

    if tipo_esperado is not None and not isinstance(dados, tipo_esperado):
        raise erro(
            f"{caminho} não tem o formato esperado ({tipo_esperado.__name__} JSON). "
            "Arquivo não alterado."
        )
    return dados


def salvar_json_atomico(caminho, dados, indent=2):
    """Grava `dados` em `caminho` de forma atômica (temporário + os.replace)."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(caminho.parent), prefix=caminho.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

"""
Gera <pasta da instalação>\\<nome da pasta>.zip com o conteúdo da pasta onde este script está
(a instalação do AUTO SERE, onde quer que ela esteja: C:\\AUTO_SERE, C:\\Auto_sere, outra pasta...),
ignorando credenciais, dados, logs e pastas pesadas/regeneráveis.

Uso:  python backup_auto_sere.py
"""
import os
import sys
import zipfile
from datetime import datetime

# Pasta da instalação = a pasta onde este arquivo está (não depende de um caminho fixo)
PASTA = os.path.dirname(os.path.abspath(__file__))
NOME = os.path.basename(PASTA)                      # ex.: "AUTO_SERE"
ZIP_FINAL = os.path.join(PASTA, f"{NOME}.zip")      # ex.: <pasta da instalação>\AUTO_SERE.zip
ZIP_TEMP = ZIP_FINAL + ".tmp"

# Pastas ignoradas (comparação sem diferenciar maiúsculas/minúsculas)
IGNORAR_PASTAS = {
    "credenciais",
    "dados",
    "logs",
    # extras recomendados (remova da lista se quiser incluir):
    "runtime",       # navegadores e Python embutido (muito pesado, reinstalável)
    "__pycache__",
    "locks",
    ".git",
}

# Arquivos ignorados
IGNORAR_EXTENSOES = {".zip", ".tmp", ".pyc", ".log"}


def deve_ignorar_arquivo(nome: str) -> bool:
    return os.path.splitext(nome)[1].lower() in IGNORAR_EXTENSOES


def main() -> int:
    if not os.path.isdir(PASTA):
        print(f"Pasta não encontrada: {PASTA}")
        return 1

    inicio = datetime.now()
    total = 0

    try:
        with zipfile.ZipFile(ZIP_TEMP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for raiz, pastas, arquivos in os.walk(PASTA):
                # poda as pastas ignoradas para o os.walk nem entrar nelas
                pastas[:] = [p for p in pastas if p.lower() not in IGNORAR_PASTAS]

                for arq in arquivos:
                    if deve_ignorar_arquivo(arq):
                        continue
                    caminho = os.path.join(raiz, arq)
                    # dentro do zip: Auto_sere/subpasta/arquivo
                    arcname = os.path.join(NOME, os.path.relpath(caminho, PASTA))
                    try:
                        zf.write(caminho, arcname)
                        total += 1
                    except (PermissionError, OSError) as e:
                        print(f"  [pulado] {caminho}: {e}")

        # só substitui o zip antigo quando o novo foi gerado com sucesso
        os.replace(ZIP_TEMP, ZIP_FINAL)
    except Exception as e:
        if os.path.exists(ZIP_TEMP):
            os.remove(ZIP_TEMP)
        print(f"Erro ao gerar backup: {e}")
        return 1

    tamanho_mb = os.path.getsize(ZIP_FINAL) / (1024 * 1024)
    dur = (datetime.now() - inicio).total_seconds()
    print(f"Backup concluído: {ZIP_FINAL}")
    print(f"{total} arquivos, {tamanho_mb:.1f} MB, {dur:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
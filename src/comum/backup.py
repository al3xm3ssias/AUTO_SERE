"""
backup.py — cópia de segurança dos dados do AUTO SERE
======================================================
O sistema não usa banco de dados: tudo é JSON/planilha em pastas. Este módulo
junta o que é *dado do sistema* num único .zip datado, com um manifesto (tamanho
e SHA-256 de cada arquivo) para poder conferir a integridade depois.

O QUE ENTRA
  dados_ano/   dados/<ano atual>/   .json .xlsx .csv .txt (turmas, alunos, pré-matrícula...)
  calendario/  dados/calendario/    calendário letivo (sem o cache de feriados)
  config/      config/              config_usuario.json (escola, pastas...) e config.yaml

O QUE NUNCA ENTRA
  credenciais/ e qualquer .env  → senhas não devem ser copiadas para backups.
  DIGITALIZAÇÃO/ (documentos dos alunos, enormes e já guardados em outro lugar),
  screenshots, logs e os próprios backups.

ONDE FICA  dados/backup/backup_AAAA-MM-DD_HHMMSS.zip  (guarda os 10 mais recentes;
           AUTO_SERE_BACKUP_MANTER muda o número). Só apaga arquivos backup_*.zip.

USO
  python -m src.comum.backup                      cria um backup agora
  python -m src.comum.backup --listar             lista os backups
  python -m src.comum.backup --restaurar ARQ.zip  extrai numa pasta "restaurado_..." para CONFERIR
  python -m src.comum.backup --restaurar ARQ.zip --aplicar
                                                  repõe de verdade (faz um backup de segurança antes)
  python -m src.comum.backup --ano 2025           backup dos dados de OUTRO ano (sem trocar o ano em uso)
  python -m src.comum.backup --restaurar ARQ.zip --aplicar --so-dados
                                                  repõe só os dados do ano (não mexe em config nem calendário)

ANOS (24/10/2026): cada backup é de UM ano (o manifesto guarda `ano`) e a restauração repõe os dados na pasta
desse ano — nunca por cima do ano em uso, se forem diferentes. Cópia de segurança antes de restaurar também é
do ano que será sobrescrito. A retenção (10 mais recentes) vale por ano, para um backup de 2025 não ser
apagado por backups novos de 2026. Restaurar a configuração não desfaz o ano letivo escolhido na tela.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from src.comum import paths

VERSAO_MANIFESTO = 1
EXTENSOES = {".json", ".xlsx", ".csv", ".txt", ".yaml", ".yml"}
IGNORAR_PASTAS = {"DIGITALIZAÇÃO", "screenshots", "backup", "feriados_cache", "__pycache__"}
MANIFESTO = "MANIFESTO.json"
PADRAO_NOME = "backup_*.zip"
MANTER_PADRAO = 10


class BackupInvalidoError(Exception):
    """O arquivo de backup está corrompido, adulterado ou mal formado."""


class BackupVazioError(BackupInvalidoError):
    """Não há nenhum arquivo de dados para copiar."""


# ───────────────────────────────────── origens ─────────────────────────────────

def _origens(ano=None) -> list[tuple[str, Path]]:
    """(prefixo dentro do zip, pasta de origem/destino). Resolvido na hora, não na importação. `ano` = outro ano."""
    return [
        ("dados_ano", paths.dados_ano_atual() if ano is None else paths.DADOS_DIR / str(ano)),
        ("calendario", paths.DADOS_DIR / "calendario"),
        ("config", paths.CONFIG_DIR),
    ]


def _arquivos_da_pasta(pasta: Path):
    """Gera (caminho relativo em formato posix, caminho absoluto) dos arquivos que entram no backup."""
    if not pasta.is_dir():
        return
    for raiz, subpastas, arquivos in os.walk(pasta):
        subpastas[:] = sorted(d for d in subpastas if d not in IGNORAR_PASTAS)
        for nome in sorted(arquivos):
            if nome.lower().startswith(".env") or Path(nome).suffix.lower() not in EXTENSOES:
                continue
            absoluto = Path(raiz) / nome
            yield absoluto.relative_to(pasta).as_posix(), absoluto


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _sha256_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _nome_livre(pasta: Path, agora: datetime) -> Path:
    """
    backup_AAAA-MM-DD_HHMMSS_mmmmmm.zip — os microssegundos garantem nomes únicos E em ordem
    cronológica, mesmo para backups feitos no mesmo segundo (um contador 2, 3... se perderia
    quando os anteriores fossem apagados pela retenção).
    """
    while True:
        candidato = pasta / f"backup_{agora:%Y-%m-%d_%H%M%S}_{agora.microsecond:06d}.zip"
        if not candidato.exists():
            return candidato
        agora += timedelta(microseconds=1)


# ───────────────────────────────────── criar ───────────────────────────────────

def criar_backup(motivo: str = "manual", manter: int | None = None, ano=None) -> Path:
    """
    Cria o backup e devolve o caminho do .zip. Levanta erro se não conseguir gerar um zip válido.
    `ano`: faz o backup dos dados desse ano (padrão: o ano em uso).
    """
    destino_dir = paths.DADOS_BACKUP_DIR
    destino_dir.mkdir(parents=True, exist_ok=True)
    agora = datetime.now()
    final = _nome_livre(destino_dir, agora)

    arquivos = []
    for prefixo, pasta in _origens(ano):
        for rel, absoluto in _arquivos_da_pasta(pasta):
            arquivos.append((f"{prefixo}/{rel}", absoluto))
    if ano is not None and not any(nome.startswith("dados_ano/") for nome, _ in arquivos):
        # backup "do ano X" sem nenhum dado de X seria só config + calendário rotulados com o ano errado
        raise BackupVazioError(f"Não há dados do ano {ano} para copiar.")
    if not arquivos:
        raise BackupVazioError("Não há nenhum arquivo de dados para copiar (a pasta de dados está vazia).")

    manifesto = {
        "versao": VERSAO_MANIFESTO,
        "criado_em": agora.isoformat(timespec="seconds"),
        "motivo": motivo,
        "ano": paths.ano_atual() if ano is None else str(ano),
        "arquivos": [],
    }

    fd, tmp = tempfile.mkstemp(dir=destino_dir, prefix=".backup_", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for nome_no_zip, absoluto in arquivos:
                dados = absoluto.read_bytes()                  # os arquivos de dados são pequenos (KB a poucos MB)
                z.writestr(nome_no_zip, dados)
                manifesto["arquivos"].append(
                    {"caminho": nome_no_zip, "tamanho": len(dados), "sha256": _sha256_bytes(dados)}
                )
            z.writestr(MANIFESTO, json.dumps(manifesto, ensure_ascii=False, indent=2))
        _verificar_zip(Path(tmp))                              # só publica o que foi conferido
        os.replace(tmp, final)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    limpar_antigos(manter, preservar=final)
    return final


def _manter_configurado(manter: int | None) -> int:
    if manter is not None:
        return max(1, int(manter))
    try:
        return max(1, int(os.environ.get("AUTO_SERE_BACKUP_MANTER", MANTER_PADRAO)))
    except ValueError:
        return MANTER_PADRAO


_NOME_BACKUP = re.compile(r"backup_(\d{4}-\d{2}-\d{2}_\d{6})(?:_(\d+))?")   # sufixo = microssegundos


def _ordem(p: Path) -> tuple[str, int]:
    """
    Ordem cronológica pela data gravada NO NOME (backup_AAAA-MM-DD_HHMMSS_mmmmmm).
    Não usa a data de modificação: ela muda quando a pasta é copiada para outro disco.
    Arquivos com nome fora do padrão caem para a data de modificação.
    """
    m = _NOME_BACKUP.fullmatch(p.stem)
    if m:
        return m.group(1), int(m.group(2) or 1)
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d_%H%M%S"), 0


def _manifesto_leve(arquivo: Path) -> dict:
    """Manifesto do zip SEM conferir os SHA-256 (para listar/agrupar); {} se ilegível."""
    try:
        with zipfile.ZipFile(arquivo) as z:
            m = json.loads(z.read(MANIFESTO).decode("utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:                                           # noqa: BLE001 — arquivo ruim só fica sem ano
        return {}


def _ano_do_backup(arquivo: Path) -> str | None:
    ano = _manifesto_leve(arquivo).get("ano")
    return str(ano) if ano not in (None, "") else None


def limpar_antigos(manter: int | None = None, preservar: Path | None = None) -> list[Path]:
    """
    Apaga os backup_*.zip mais antigos, mantendo os `manter` mais recentes DE CADA ANO (um backup de 2025 não é
    apagado por backups novos de 2026). Mexe só nesses arquivos. `preservar` (o recém-criado) nunca é apagado.
    """
    manter = _manter_configurado(manter)
    grupos: dict[str | None, list[Path]] = {}
    for p in sorted(paths.DADOS_BACKUP_DIR.glob(PADRAO_NOME), key=_ordem):
        grupos.setdefault(_ano_do_backup(p), []).append(p)
    removidos = []
    for lista in grupos.values():
        excedentes = lista[:-manter] if len(lista) > manter else []
        removidos += [p for p in excedentes if p != preservar]
    for p in removidos:
        p.unlink()
    return removidos


def listar_backups() -> list[dict]:
    itens = []
    for p in sorted(paths.DADOS_BACKUP_DIR.glob(PADRAO_NOME), key=_ordem, reverse=True):
        st = p.stat()
        manifesto = _manifesto_leve(p)
        ano = manifesto.get("ano")
        itens.append({
            "nome": p.name,
            "caminho": str(p),
            "tamanho": st.st_size,
            "data": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
            "ano": str(ano) if ano not in (None, "") else None,
            "motivo": manifesto.get("motivo"),
        })
    return itens


# ───────────────────────────────── verificar / restaurar ───────────────────────

def _ler_manifesto(z: zipfile.ZipFile) -> dict:
    try:
        return json.loads(z.read(MANIFESTO).decode("utf-8"))
    except (KeyError, ValueError) as exc:
        raise BackupInvalidoError("Arquivo de backup sem manifesto válido.") from exc


def _verificar_zip(arquivo: Path) -> dict:
    """Confere o zip (estrutura + SHA-256 de cada arquivo). Devolve o manifesto ou levanta BackupInvalidoError."""
    try:
        with zipfile.ZipFile(arquivo) as z:
            ruim = z.testzip()
            if ruim:
                raise BackupInvalidoError(f"Arquivo corrompido dentro do backup: {ruim}")
            manifesto = _ler_manifesto(z)
            for item in manifesto.get("arquivos", []):
                try:
                    dados = z.read(item["caminho"])
                except KeyError as exc:
                    raise BackupInvalidoError(f"Falta no backup: {item['caminho']}") from exc
                if len(dados) != item["tamanho"] or _sha256_bytes(dados) != item["sha256"]:
                    raise BackupInvalidoError(f"Conteúdo alterado ou corrompido: {item['caminho']}")
            return manifesto
    except zipfile.BadZipFile as exc:
        raise BackupInvalidoError("O arquivo não é um .zip válido.") from exc


def verificar_backup(arquivo) -> dict:
    return _verificar_zip(Path(arquivo))


def _destino_seguro(base: Path, relativo: str) -> Path:
    """Impede que um zip adulterado escreva fora da pasta de destino (zip slip)."""
    alvo = (base / relativo).resolve()
    if base.resolve() != alvo and base.resolve() not in alvo.parents:
        raise BackupInvalidoError(f"Caminho inseguro no backup: {relativo}")
    return alvo


def _config_usuario() -> Path:
    return paths.CONFIG_DIR / "config_usuario.json"


def _ler_ano_letivo_configurado() -> str | None:
    try:
        dados = json.loads(_config_usuario().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    valor = dados.get("ano_letivo") if isinstance(dados, dict) else None
    return str(valor) if valor else None


def _regravar_ano_letivo(valor: str | None) -> None:
    """Depois de restaurar a configuração de um backup antigo, devolve a escolha de ano letivo que estava valendo."""
    caminho = _config_usuario()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(dados, dict):
        return
    if valor:
        dados["ano_letivo"] = valor
    else:
        dados.pop("ano_letivo", None)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def restaurar_backup(arquivo, aplicar: bool = False, so_dados: bool = False) -> dict:
    """
    aplicar=False (padrão): extrai para dados/backup/restaurado_<data>/ — nada do sistema é alterado,
                            serve para conferir o conteúdo.
    aplicar=True: faz antes um backup de segurança e então repõe os arquivos nos locais de origem.
    so_dados=True: repõe só os dados do ano (dados_ano), sem tocar na configuração nem no calendário.
    Em ambos os casos o backup é conferido (SHA-256) ANTES de qualquer escrita.

    Os dados do ano vão para a pasta do ANO DO BACKUP (manifesto), mesmo que seja diferente do ano em uso; e a
    cópia de segurança é desse mesmo ano. A escolha de ano letivo da configuração é preservada.
    """
    arquivo = Path(arquivo)
    manifesto = _verificar_zip(arquivo)
    ano_backup = str(manifesto["ano"]) if manifesto.get("ano") not in (None, "") else None
    origens = dict(_origens())
    if ano_backup and ano_backup != str(paths.ano_atual()):
        origens["dados_ano"] = paths.DADOS_DIR / ano_backup
    seguranca = None
    ano_letivo_anterior = _ler_ano_letivo_configurado()
    if aplicar:
        try:
            seguranca = criar_backup(motivo="antes_de_restaurar", ano=ano_backup if ano_backup != str(paths.ano_atual()) else None)
        except BackupVazioError:
            seguranca = None                                    # nada a perder: a pasta do ano estava vazia
        base_por_prefixo = origens
    else:
        pasta = paths.DADOS_BACKUP_DIR / f"restaurado_{datetime.now():%Y-%m-%d_%H%M%S}"
        base_por_prefixo = {p: pasta / p for p in origens}

    gravados = []
    config_regravada = False
    with zipfile.ZipFile(arquivo) as z:
        for item in manifesto["arquivos"]:
            prefixo, _, rel = item["caminho"].partition("/")
            if prefixo not in base_por_prefixo or not rel:
                raise BackupInvalidoError(f"Pasta desconhecida no backup: {item['caminho']}")
            if so_dados and prefixo != "dados_ano":
                continue
            base = base_por_prefixo[prefixo]
            alvo = _destino_seguro(base, rel)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=alvo.parent, suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(z.read(item["caminho"]))
            os.replace(tmp, alvo)
            gravados.append(str(alvo))
            if aplicar and prefixo == "config" and rel == "config_usuario.json":
                config_regravada = True
    if config_regravada:
        _regravar_ano_letivo(ano_letivo_anterior)
    return {
        "aplicado": aplicar,
        "arquivos": len(gravados),
        "pasta": None if aplicar else str(next(iter(base_por_prefixo.values())).parent),
        "backup_de_seguranca": str(seguranca) if seguranca else None,
        "criado_em": manifesto.get("criado_em"),
        "ano": ano_backup,
        "pasta_destino": str(origens["dados_ano"]) if aplicar else None,
    }


# ───────────────────────────────── execução (tela e CLI) ───────────────────────

def _tamanho_legivel(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def executar_backup() -> Path:
    """Usado pela tela de Automações: imprime o andamento (o print vira o log da tela)."""
    print("Criando backup dos dados...")
    for prefixo, pasta in _origens():
        n = sum(1 for _ in _arquivos_da_pasta(pasta))
        print(f"  {prefixo}: {n} arquivo(s)  ({pasta})")
    antes = {p.name for p in paths.DADOS_BACKUP_DIR.glob(PADRAO_NOME)} if paths.DADOS_BACKUP_DIR.exists() else set()
    arquivo = criar_backup()
    depois = {p.name for p in paths.DADOS_BACKUP_DIR.glob(PADRAO_NOME)}
    print(f"Backup criado e conferido: {arquivo.name} ({_tamanho_legivel(arquivo.stat().st_size)})")
    print(f"Pasta: {arquivo.parent}")
    removidos = (antes | {arquivo.name}) - depois
    if removidos:
        print(f"Backups antigos removidos (mantidos os {_manter_configurado(None)} mais recentes): {len(removidos)}")
    print("Obs.: senhas e credenciais NÃO são copiadas para o backup.")
    return arquivo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backup dos dados do AUTO SERE")
    ap.add_argument("--listar", action="store_true", help="lista os backups existentes")
    ap.add_argument("--restaurar", metavar="ARQUIVO", help="restaura um backup (por padrão só extrai para conferir)")
    ap.add_argument("--aplicar", action="store_true", help="com --restaurar: repõe os dados de verdade")
    ap.add_argument("--so-dados", action="store_true", help="com --restaurar: só os dados do ano (sem config/calendário)")
    ap.add_argument("--ano", metavar="AAAA", help="faz o backup dos dados desse ano (padrão: o ano em uso)")
    args = ap.parse_args(argv)

    if args.listar:
        itens = listar_backups()
        if not itens:
            print("Nenhum backup encontrado.")
        for i in itens:
            print(f"{i['data']}  {_tamanho_legivel(i['tamanho']):>8}  {i['nome']}")
        return 0
    if args.restaurar:
        alvo = Path(args.restaurar)
        if not alvo.exists():
            alvo = paths.DADOS_BACKUP_DIR / args.restaurar
        try:
            r = restaurar_backup(alvo, aplicar=args.aplicar, so_dados=args.so_dados)
        except (BackupInvalidoError, OSError) as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
        if r["aplicado"]:
            print(f"Dados restaurados ({r['arquivos']} arquivos). Cópia de segurança do estado anterior: {r['backup_de_seguranca']}")
        else:
            print(f"Conteúdo extraído para conferência em: {r['pasta']}  (nada foi alterado no sistema; use --aplicar para repor)")
        return 0
    paths.garantir_diretorios_runtime()
    try:
        if args.ano:
            print(f"Backup dos dados do ano {args.ano}: {criar_backup(ano=args.ano).name}")
            return 0
        executar_backup()
    except BackupInvalidoError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

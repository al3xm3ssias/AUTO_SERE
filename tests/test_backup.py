"""Backup dos dados: conteúdo, exclusões, retenção, integridade e restauração."""
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import backup, paths  # noqa: E402


@pytest.fixture()
def raiz(tmp_path, monkeypatch):
    dados = tmp_path / "dados"
    ano = dados / "2026"
    (ano / "DIGITALIZAÇÃO" / "5A").mkdir(parents=True)
    (ano / "screenshots").mkdir()
    (dados / "calendario" / "feriados_cache").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "credenciais").mkdir()
    (tmp_path / "dados" / "backup").mkdir()

    (ano / "turmas.json").write_text('{"5A": []}', encoding="utf-8")
    (ano / "alunos.json").write_text('[{"Nome": "João"}]', encoding="utf-8")
    (ano / "planilha.xlsx").write_bytes(b"xlsx-bytes")
    (ano / "DIGITALIZAÇÃO" / "5A" / "doc.json").write_text("{}", encoding="utf-8")   # documentos de alunos: fora
    (ano / "screenshots" / "x.json").write_text("{}", encoding="utf-8")
    (ano / "foto.png").write_bytes(b"png")                                          # extensão não incluída
    (dados / "calendario" / "calendario.json").write_text('{"eventos": [], "periodos": []}', encoding="utf-8")
    (dados / "calendario" / "feriados_cache" / "2026.json").write_text("[]", encoding="utf-8")
    (tmp_path / "config" / "config_usuario.json").write_text('{"unidade_escolar": {"nome": "Escola"}}', encoding="utf-8")
    (tmp_path / "config" / "config.yaml").write_text("a: 1", encoding="utf-8")
    (tmp_path / "credenciais" / ".env").write_text("SERE_SENHA=segredo-super-secreto", encoding="utf-8")
    (tmp_path / "config" / ".env").write_text("SENHA=outro-segredo", encoding="utf-8")   # mesmo dentro de config/

    monkeypatch.setattr(paths, "DADOS_DIR", dados)
    monkeypatch.setattr(paths, "DADOS_BACKUP_DIR", dados / "backup")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "dados_ano_atual", lambda: ano)
    monkeypatch.setattr(paths, "ano_atual", lambda: 2026)
    return tmp_path


def _nomes(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return sorted(z.namelist())


def test_conteudo_do_backup(raiz):
    z = backup.criar_backup()
    assert z.parent == raiz / "dados" / "backup" and z.name.startswith("backup_") and z.suffix == ".zip"
    assert _nomes(z) == sorted([
        "MANIFESTO.json",
        "dados_ano/alunos.json", "dados_ano/planilha.xlsx", "dados_ano/turmas.json",
        "calendario/calendario.json",
        "config/config.yaml", "config/config_usuario.json",
    ])
    manifesto = backup.verificar_backup(z)
    assert manifesto["ano"] == 2026 and len(manifesto["arquivos"]) == 6
    assert all(len(a["sha256"]) == 64 for a in manifesto["arquivos"])


def test_nunca_inclui_senhas_nem_documentos_de_alunos(raiz):
    z = backup.criar_backup()
    with zipfile.ZipFile(z) as arq:
        tudo = b"".join(arq.read(n) for n in arq.namelist())
    assert b"segredo" not in tudo                                  # nem credenciais/.env nem config/.env
    assert not any("DIGITALIZA" in n or "screenshots" in n or ".env" in n or "feriados_cache" in n for n in _nomes(z))


def test_nao_deixa_arquivo_temporario(raiz):
    backup.criar_backup()
    assert [p.name for p in (raiz / "dados" / "backup").iterdir() if p.suffix == ".tmp"] == []


def test_dois_backups_no_mesmo_segundo_nao_se_sobrescrevem(raiz):
    a, b = backup.criar_backup(), backup.criar_backup()
    assert a != b and a.exists() and b.exists()
    assert backup._ordem(a) < backup._ordem(b)                       # e a ordem é a cronológica


def test_retencao_nunca_apaga_o_backup_recem_criado(raiz, monkeypatch):
    """Regressão: no mesmo segundo, a retenção chegou a apagar o backup que acabara de ser feito."""
    monkeypatch.setenv("AUTO_SERE_BACKUP_MANTER", "1")
    for _ in range(5):
        novo = backup.criar_backup()
        assert novo.exists()
    assert [p.name for p in (raiz / "dados" / "backup").glob("backup_*.zip")] == [novo.name]


def test_retencao_mantem_so_os_mais_recentes_e_nao_toca_em_outros_arquivos(raiz):
    pasta = raiz / "dados" / "backup"
    (pasta / "anotacao.txt").write_text("meu arquivo", encoding="utf-8")
    (pasta / ".gitkeep").write_text("", encoding="utf-8")
    criados = [backup.criar_backup(manter=99) for _ in range(4)]       # criados em sequência (mesmo segundo ou não)
    removidos = backup.limpar_antigos(manter=2)
    assert {p.name for p in removidos} == {criados[0].name, criados[1].name}
    restantes = sorted(p.name for p in pasta.glob("backup_*.zip"))
    assert restantes == sorted([criados[2].name, criados[3].name])
    assert (pasta / "anotacao.txt").exists() and (pasta / ".gitkeep").exists()


def test_retencao_configuravel_por_ambiente(raiz, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_BACKUP_MANTER", "1")
    ultimo = [backup.criar_backup() for _ in range(3)][-1]
    assert [p.name for p in (raiz / "dados" / "backup").glob("backup_*.zip")] == [ultimo.name]   # ficou o mais recente


def test_ordem_nao_depende_da_data_de_modificacao_do_arquivo(raiz):
    """Copiar a pasta de backups para outro disco muda as datas de modificação; a ordem tem de se manter."""
    a, b, c = (backup.criar_backup(manter=99) for _ in range(3))
    for i, p in enumerate((c, b, a)):                       # inverte as datas de propósito
        os.utime(p, (1_000_000_000 + i, 1_000_000_000 + i))
    backup.limpar_antigos(manter=1)
    assert [p.name for p in (raiz / "dados" / "backup").glob("backup_*.zip")] == [c.name]


def test_pasta_de_dados_vazia_da_erro_claro(raiz):
    for p in list((raiz / "dados" / "2026").glob("*.*")) + list((raiz / "dados" / "calendario").glob("*.json")) + list((raiz / "config").glob("*.*")):
        p.unlink()
    with pytest.raises(backup.BackupInvalidoError, match="nenhum arquivo"):
        backup.criar_backup()
    assert list((raiz / "dados" / "backup").glob("*")) == []


def test_arquivo_adulterado_e_detectado(raiz):
    z = backup.criar_backup()
    adulterado = z.with_name("adulterado.zip")
    with zipfile.ZipFile(z) as origem, zipfile.ZipFile(adulterado, "w") as novo:
        for item in origem.namelist():
            dados = origem.read(item)
            novo.writestr(item, b'{"hackeado": true}' if item == "dados_ano/turmas.json" else dados)
    with pytest.raises(backup.BackupInvalidoError, match="alterado"):
        backup.verificar_backup(adulterado)
    with pytest.raises(backup.BackupInvalidoError):
        backup.restaurar_backup(adulterado, aplicar=True)
    assert json.loads((raiz / "dados" / "2026" / "turmas.json").read_text(encoding="utf-8")) == {"5A": []}   # nada foi escrito


def test_nao_e_zip(raiz):
    falso = raiz / "dados" / "backup" / "falso.zip"
    falso.write_text("nao sou zip", encoding="utf-8")
    with pytest.raises(backup.BackupInvalidoError, match="zip"):
        backup.verificar_backup(falso)


def test_restaurar_sem_aplicar_so_extrai_para_conferencia(raiz):
    z = backup.criar_backup()
    (raiz / "dados" / "2026" / "turmas.json").write_text('{"mudou": 1}', encoding="utf-8")
    r = backup.restaurar_backup(z)
    assert r["aplicado"] is False and r["arquivos"] == 6
    extraido = Path(r["pasta"])
    assert extraido.name.startswith("restaurado_")
    assert json.loads((extraido / "dados_ano" / "turmas.json").read_text(encoding="utf-8")) == {"5A": []}
    assert json.loads((raiz / "dados" / "2026" / "turmas.json").read_text(encoding="utf-8")) == {"mudou": 1}   # sistema intacto


def test_restaurar_aplicando_faz_backup_de_seguranca_antes(raiz):
    original = backup.criar_backup()
    (raiz / "dados" / "2026" / "turmas.json").write_text('{"estragou": 1}', encoding="utf-8")
    r = backup.restaurar_backup(original, aplicar=True)
    assert json.loads((raiz / "dados" / "2026" / "turmas.json").read_text(encoding="utf-8")) == {"5A": []}   # voltou
    seguranca = Path(r["backup_de_seguranca"])
    assert seguranca.exists() and seguranca != original
    with zipfile.ZipFile(seguranca) as z:                                     # o estado "estragado" ficou guardado
        assert json.loads(z.read("dados_ano/turmas.json")) == {"estragou": 1}


def test_zip_com_caminho_malicioso_e_recusado(raiz):
    z = raiz / "dados" / "backup" / "malicioso.zip"
    conteudo = b"pwn"
    import hashlib
    manifesto = {"versao": 1, "criado_em": "x", "ano": 2026, "arquivos": [
        {"caminho": "dados_ano/../../fora.json", "tamanho": len(conteudo), "sha256": hashlib.sha256(conteudo).hexdigest()}]}
    with zipfile.ZipFile(z, "w") as arq:
        arq.writestr("dados_ano/../../fora.json", conteudo)
        arq.writestr("MANIFESTO.json", json.dumps(manifesto))
    with pytest.raises(backup.BackupInvalidoError, match="inseguro"):
        backup.restaurar_backup(z, aplicar=True)
    assert not (raiz / "dados" / "fora.json").exists() and not (raiz / "fora.json").exists()


def test_cli_listar_e_criar(raiz, capsys):
    assert backup.main(["--listar"]) == 0
    assert "Nenhum backup" in capsys.readouterr().out
    assert backup.main([]) == 0
    saida = capsys.readouterr().out
    assert "Backup criado e conferido" in saida and "NÃO são copiadas" in saida
    assert backup.main(["--listar"]) == 0
    assert "backup_" in capsys.readouterr().out


def test_cli_restaurar_arquivo_inexistente(raiz, capsys):
    assert backup.main(["--restaurar", "nao_existe.zip"]) == 1
    assert "ERRO" in capsys.readouterr().err


def test_tela_de_automacoes_executa_o_backup(raiz):
    from src.web.app import create_app
    c = create_app().test_client()
    r = c.post("/web/api/automacoes/backup/executar", json={})
    assert r.status_code == 200 and r.get_json()["status"] == "executando"
    fim = time.time() + 10
    while time.time() < fim:
        st = c.get("/web/api/automacoes/backup/status").get_json()
        if st["status"] != "executando":
            break
        time.sleep(0.05)
    assert st["status"] == "concluido", st
    texto = "\n".join(st["logs"])
    assert "Backup criado e conferido" in texto and "dados_ano: 3 arquivo(s)" in texto
    assert len(list((raiz / "dados" / "backup").glob("backup_*.zip"))) == 1

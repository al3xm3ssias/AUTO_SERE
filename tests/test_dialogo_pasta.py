"""Seletor de pasta: comando do PowerShell, parsing da saída e rota."""
import base64
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comum import configuracao, dialogo_pasta  # noqa: E402
from src.web.app import create_app  # noqa: E402


def _decodificar(cmd):
    return base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")


def test_comando_usa_sta_e_encoded_command():
    cmd = dialogo_pasta._comando_powershell("Escolha a pasta dos alunos")
    assert cmd[0] == "powershell" and "-STA" in cmd and "-NoProfile" in cmd
    script = _decodificar(cmd)
    assert "FolderBrowserDialog" in script and "TopMost" in script
    assert "Escolha a pasta dos alunos" in script          # acentos/espacos preservados


def test_titulo_com_apostrofo_nao_quebra_o_script():
    script = dialogo_pasta.script_powershell("Pasta d'água")
    assert "Pasta d''água" in script


class _R:
    def __init__(self, out=b"", err=b"", code=0):
        self.stdout, self.stderr, self.returncode = out, err, code


def _como_windows(monkeypatch, resultado):
    monkeypatch.setattr(dialogo_pasta.os, "name", "nt")
    monkeypatch.setattr(dialogo_pasta.subprocess, "run", lambda *a, **k: resultado)


def test_caminho_escolhido_com_bom_e_acentos(monkeypatch):
    _como_windows(monkeypatch, _R(out="\ufeffC:\\Escola\\DIGITALIZAÇÃO".encode("utf-8")))
    assert dialogo_pasta.escolher_pasta("x") == "C:\\Escola\\DIGITALIZAÇÃO"


def test_cancelado_devolve_none(monkeypatch):
    _como_windows(monkeypatch, _R(out=b""))
    assert dialogo_pasta.escolher_pasta("x") is None


def test_erro_do_powershell_vira_excecao(monkeypatch):
    _como_windows(monkeypatch, _R(err=b"falhou", code=1))
    with pytest.raises(RuntimeError, match="falhou"):
        dialogo_pasta.escolher_pasta("x")


def test_rota_escolher_pasta_salva_destino(tmp_path, monkeypatch):
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    alvo = tmp_path / "dig"
    alvo.mkdir()
    monkeypatch.setattr(dialogo_pasta, "escolher_pasta", lambda titulo="": str(alvo))
    c = create_app().test_client()
    r = c.post("/web/api/sistema/escolher-pasta", json={"destino": "digitalizacao"})
    assert r.get_json() == {"caminho": str(alvo), "cancelado": False}
    assert str(configuracao.pasta_digitalizacao()) == str(alvo)


def test_rota_escolher_pasta_cancelada(tmp_path, monkeypatch):
    monkeypatch.setattr(dialogo_pasta, "escolher_pasta", lambda titulo="": None)
    r = create_app().test_client().post("/web/api/sistema/escolher-pasta", json={})
    assert r.get_json()["cancelado"] is True

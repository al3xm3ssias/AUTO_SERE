"""A tela 'Mandar avisos' (unidades pesquisáveis, tipo de mensagem, modelos) rodando no jsdom. Pula sem node ou sem jsdom."""
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent / "js"


def _tem_jsdom() -> bool:
    return shutil.which("node") is not None and any((p / "node_modules" / "jsdom").exists() for p in (JS, JS.parent, JS.parent.parent))


@pytest.mark.skipif(not _tem_jsdom(), reason="precisa de node e do pacote jsdom (npm install jsdom em tests/js)")
def test_tela_de_avisos_no_jsdom(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gerar_dados_js", JS / "gerar_dados.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    dados = modulo.gerar(tmp_path / "dados.json")
    r = subprocess.run(["node", str(JS / "teste_tela_avisos.js"), str(dados)], capture_output=True, text=True, timeout=120,
                       cwd=JS, encoding="utf-8")
    assert r.returncode == 0 and "TUDO OK" in r.stdout, r.stdout[-3000:] + r.stderr[-1500:]

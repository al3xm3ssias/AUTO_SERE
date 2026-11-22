"""'Quem já recebeu' (Mandar avisos) e 'Fila de envio' (WhatsApp) rodando no jsdom. Pula sem node ou sem jsdom."""
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent / "js"


def _tem_jsdom() -> bool:
    return shutil.which("node") is not None and any((p / "node_modules" / "jsdom").exists() for p in (JS, JS.parent, JS.parent.parent))


@pytest.mark.skipif(not _tem_jsdom(), reason="precisa de node e do pacote jsdom (npm install jsdom em tests/js)")
def test_enviados_e_fila_no_jsdom():
    r = subprocess.run(["node", str(JS / "teste_enviados_e_fila.js")], capture_output=True, text=True, timeout=120, cwd=JS, encoding="utf-8")
    assert r.returncode == 0 and "TUDO OK" in r.stdout, r.stdout[-3000:] + r.stderr[-1500:]

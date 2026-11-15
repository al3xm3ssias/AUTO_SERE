"""Gera dados.json para teste_tela_avisos.js: os campos reais da tela de avisos (com os modelos prontos e um modelo criado)."""
import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))


def gerar(destino: Path) -> Path:
    from src.comum import modelos_avisos as ma
    from src.comum import paths
    from src.comum import registro_scripts as reg
    antigo = paths.CONFIG_DIR
    paths.CONFIG_DIR = Path(tempfile.mkdtemp()) / "config"            # nunca mexe nos modelos de verdade
    try:
        extras = reg._extras_avisos()
        info = {"registrado": True, "recursos": [], "confirmar": False, "confirmar_quando": {"campo": "modo", "valor": "enviar"},
                "aviso_confirmacao": "x", "ajuda_teste": "", "ajuda_debug": "", "cgm_obrigatorio": False, "extras": extras}
        ma.salvar("Meu modelo", "pais", "Assunto $ALUNO", "Texto $RESPONSAVEL")
        info2 = {**info, "extras": reg._extras_avisos()}                  # a tela depois de salvar um modelo
    finally:
        paths.CONFIG_DIR = antigo
    unidades = [{"nome": "CMEI Pequeno Príncipe", "tipo": "cmei", "tem_email": True},
                {"nome": "Escola Municipal Ana Néri", "tipo": "escola", "tem_email": True},
                {"nome": "Escola Municipal Sem Email", "tipo": "escola", "tem_email": False},
                {"nome": "Escola <b>Perigosa</b>", "tipo": "escola", "tem_email": True}]
    destino.write_text(json.dumps({"info": info, "info2": info2, "unidades": unidades}, ensure_ascii=False), encoding="utf-8")
    return destino


if __name__ == "__main__":
    print(gerar(Path(__file__).with_name("dados.json")))

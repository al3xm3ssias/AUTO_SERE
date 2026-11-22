"""Lista dos textos de turma do QR antigo que a leitura dos pareceres não reconheceu."""
import json

from src.comum import qr_turmas_nao_reconhecidas as q


def test_registrar_conta_arquivos_diferentes_e_nao_infla_com_o_mesmo(tmp_path):
    assert q.listar(tmp_path) == []
    assert q.registrar(tmp_path, " inf 4 a ", "a.pdf") and q.registrar(tmp_path, "INF 4 A", "b.pdf") and q.registrar(tmp_path, "INF 4 A", "a.pdf")
    (item,) = q.listar(tmp_path)
    assert item["texto"] == "inf 4 a" and item["quantidade"] == 2 and item["arquivos"] == ["a.pdf", "b.pdf"] and item["ultima_vez"]
    assert list(json.loads((tmp_path / q.ARQUIVO).read_text(encoding="utf-8"))) == ["INF 4 A"]                  # a chave é a da leitura


def test_registrar_ignora_texto_vazio_ou_grande_demais_e_nao_cria_arquivo(tmp_path):
    assert not q.registrar(tmp_path, "  ", "a.pdf") and not q.registrar(tmp_path, "x" * 81, "a.pdf") and not q.registrar(tmp_path, None, "a.pdf")
    assert not (tmp_path / q.ARQUIVO).exists()


def test_registrar_nunca_levanta_erro(tmp_path):
    arquivo = tmp_path / "isto e um arquivo"
    arquivo.write_text("x", encoding="utf-8")
    assert q.registrar(arquivo, "INF 4 A", "a.pdf") is False                                                  # não dá para gravar dentro de um arquivo
    assert q.registrar(tmp_path / "pasta nova", "INF 4 A", "a.pdf") is True                                   # pasta que não existe é criada


def test_arquivo_corrompido_vira_lista_vazia_e_e_reescrito_ao_registrar(tmp_path):
    (tmp_path / q.ARQUIVO).write_text("{ quebrado", encoding="utf-8")
    assert q.listar(tmp_path) == []
    assert q.registrar(tmp_path, "INF 4 A", "a.pdf") and q.listar(tmp_path)[0]["texto"] == "INF 4 A"
    (tmp_path / q.ARQUIVO).write_text("[1, 2]", encoding="utf-8")
    assert q.listar(tmp_path) == []


def test_so_ficam_os_mais_recentes_e_os_arquivos_tem_limite(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "MAX_ENTRADAS", 3)
    for i in range(5):
        q.registrar(tmp_path, f"TURMA {i}", "a.pdf")
    assert len(q.listar(tmp_path)) == 3
    for i in range(30):
        q.registrar(tmp_path, "CHEIA", f"{i}.pdf")
    cheia = next(x for x in q.listar(tmp_path) if x["texto"] == "CHEIA")
    assert len(cheia["arquivos"]) == q.MAX_ARQUIVOS and cheia["arquivos"][-1] == "29.pdf" and cheia["quantidade"] == 30


def test_listar_mostra_o_mais_recente_primeiro_e_remover_ignora_maiusculas(tmp_path):
    (tmp_path / q.ARQUIVO).write_text(json.dumps({
        "VELHA": {"texto": "velha", "quantidade": 1, "arquivos": ["a.pdf"], "ultima_vez": "2026-01-01T10:00:00"},
        "NOVA": {"texto": "nova", "quantidade": "x", "arquivos": ["b.pdf", "c.pdf"], "ultima_vez": "2026-06-01T10:00:00"}}), encoding="utf-8")
    assert [i["texto"] for i in q.listar(tmp_path)] == ["nova", "velha"]
    assert q.listar(tmp_path)[0]["quantidade"] == 2                                                           # quantidade ilegível: conta os arquivos
    assert q.remover(tmp_path, ["Nova", "nao existe"]) == 1 and [i["texto"] for i in q.listar(tmp_path)] == ["velha"]
    assert q.remover(tmp_path, []) == 0

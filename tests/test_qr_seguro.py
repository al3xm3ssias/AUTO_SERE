"""qr_seguro: o QR dos pareceres leva ano, chamada, nome, turma e CGM criptografados (AES-GCM)."""
import pytest

from src.comum import paths, qr_seguro as q


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CREDENCIAIS_DIR", tmp_path / "credenciais")
    monkeypatch.delenv(q.VARIAVEL_CHAVE, raising=False)
    return tmp_path


def _montar(**o):
    d = dict(ano=2027, chamada=12, nome="MARIA APARECIDA DOS SANTOS", turma="1º Ano Integral A", cgm="1234567890")
    d.update(o)
    return q.montar(d["ano"], d["chamada"], d["nome"], d["turma"], d["cgm"])


def test_ida_e_volta_com_os_cinco_campos():
    assert q.ler(_montar()) == {"ano": "2027", "chamada": "12", "nome": "MARIA APARECIDA DOS SANTOS",
                                "turma": "1º Ano Integral A", "cgm": "1234567890"}


def test_o_texto_do_qr_nao_mostra_nada_legivel():
    texto = _montar()
    assert texto.startswith("AUTOSERE|PF2|")
    for pedaco in ("MARIA", "APARECIDA", "1234567890", "2027", "Integral"):
        assert pedaco not in texto


def test_cada_geracao_sai_diferente_mas_le_igual():
    assert _montar() != _montar() and q.ler(_montar()) == q.ler(_montar())


def test_chave_e_criada_na_primeira_geracao_e_reaproveitada(ambiente):
    arq = q.arquivo_da_chave()
    assert not arq.exists()
    t1 = _montar()
    conteudo = arq.read_text(encoding="utf-8")
    t2 = _montar()
    assert arq.read_text(encoding="utf-8") == conteudo and q.ler(t1) and q.ler(t2)


def test_ler_nao_cria_chave_e_explica_quando_falta(ambiente):
    texto = _montar()
    q.arquivo_da_chave().unlink()
    with pytest.raises(q.QrIlegivel, match="chave não foi encontrada"):
        q.ler(texto)
    assert not q.arquivo_da_chave().exists()


def test_chave_de_outro_computador_nao_abre():
    texto = _montar()
    q.arquivo_da_chave().unlink()
    _montar()                                                  # gera outra chave
    with pytest.raises(q.QrIlegivel, match="chave é outra ou o QR foi alterado"):
        q.ler(texto)


def test_qr_alterado_nao_abre():
    texto = _montar()
    trocado = texto[:-4] + ("AAAA" if not texto.endswith("AAAA") else "BBBB")
    with pytest.raises(q.QrIlegivel):
        q.ler(trocado)


@pytest.mark.parametrize("texto", ["AUTOSERE|PF2|", "AUTOSERE|PF2|abc", "AUTOSERE|PF2|@@@@"])
def test_qr_incompleto_ou_lixo(texto):
    with pytest.raises(q.QrIlegivel):
        q.ler(texto)


@pytest.mark.parametrize("texto", ["", None, "AUTOSERE|PF|2026|1234", "outra coisa", '{"nome": "A", "turma": "B"}'])
def test_outros_formatos_nao_sao_deste_modulo(texto):
    assert q.ler(texto) is None


def test_chave_pela_variavel_de_ambiente(monkeypatch):
    import base64, os
    monkeypatch.setenv(q.VARIAVEL_CHAVE, base64.urlsafe_b64encode(os.urandom(32)).decode())
    texto = _montar()
    assert q.ler(texto)["cgm"] == "1234567890" and not q.arquivo_da_chave().exists()


def test_chave_invalida_na_variavel(monkeypatch):
    monkeypatch.setenv(q.VARIAVEL_CHAVE, "curta")
    with pytest.raises(q.QrIlegivel, match="chave"):
        _montar()


@pytest.mark.parametrize("campo,valor", [("cgm", ""), ("cgm", "12 34"), ("ano", "27"), ("ano", "abcd")])
def test_dados_invalidos_nao_geram_qr(campo, valor):
    with pytest.raises(ValueError):
        _montar(**{campo: valor})


def test_nome_longo_com_acentos_cabe_e_volta():
    nome = "JOÃO PEDRO DE ALCÂNTARA E SILVA DOS SANTOS OLIVEIRA PEREIRA"
    texto = _montar(nome=nome, turma="5º Ano Integral B")
    assert len(texto) < 230 and q.ler(texto)["nome"] == nome

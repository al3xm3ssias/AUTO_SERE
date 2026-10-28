"""Linha de comando do sere_2026 (main): flags → o modo certo, com as regras de turma, prévia e confirmação."""
import sys

import pytest

from src.automacao import sere_2026 as s
from src.comum.sere_normalizacao import IDTIPO_PARA_SLOT


def _al(cgm, nome, sit="Matriculado"):
    return {"CGM": cgm, "Nome": nome, "Situação": sit}


TURMAS = {
    "3º Ano Integral A": [_al("3000000001", "Ana"), _al("3000000002", "Beto", "Transferido")],
    "3º Ano Integral B": [_al("3000000003", "Caio")],
    "5º Ano Integral A": [_al("5000000001", "Duda")],
}
ID_VALIDO = sorted(IDTIPO_PARA_SLOT)[0]
NOME_VALIDO = IDTIPO_PARA_SLOT[ID_VALIDO]


@pytest.fixture()
def chamadas(monkeypatch):
    """Troca os modos reais (que abririam o navegador) por falsos que só anotam a chamada."""
    registro = []

    def falso(nome):
        async def modo(*a, **kw):
            registro.append((nome, kw))
        modo.__name__ = nome
        return modo

    for nome in ("modo_limpeza", "modo_documento", "modo_espec", "modo_aluno", "modo_transferidos", "modo_validar"):
        monkeypatch.setattr(s, nome, falso(nome))
    monkeypatch.setattr(s, "modo_analisa", lambda extras: registro.append(("modo_analisa", {"args_extras": extras})))
    monkeypatch.setattr(s, "carregar_turmas", lambda: TURMAS)
    return registro


# ───────────── pedido inválido ─────────────

def test_sem_modo_ou_com_dois_modos_e_pedido_invalido(chamadas, capsys):
    assert s.main([]) == 2 and "Escolha exatamente um modo" in capsys.readouterr().err
    assert s.main(["--limpeza", "--validar", "--teste"]) == 2 and "só um modo" in capsys.readouterr().err
    assert chamadas == []


def test_turma_inexistente_e_turmas_json_ausente(chamadas, capsys, monkeypatch):
    assert s.main(["--limpeza", "--turma", "9º Ano", "--teste"]) == 2
    assert "Turma não encontrada" in capsys.readouterr().err
    monkeypatch.setattr(s, "carregar_turmas", lambda: (_ for _ in ()).throw(FileNotFoundError("sem arquivo")))
    assert s.main(["--limpeza", "--teste"]) == 2 and "Ainda não existe turmas.json" in capsys.readouterr().err
    assert chamadas == []


def test_argumento_desconhecido_nao_executa(chamadas):
    assert s.main(["--limpeza", "--nao-existe"]) == 2 and chamadas == []


# ───────────── limpeza: turmas, situação e confirmação ─────────────

def test_limpeza_com_teste_nao_pede_confirmacao_e_filtra_turmas_e_situacao(chamadas):
    assert s.main(["--limpeza", "--teste", "--turma", "3"]) == 0
    nome, kw = chamadas[0]
    assert nome == "modo_limpeza" and kw["modo_teste"] is True
    assert kw["turmas_selecionadas"] == ["3º Ano Integral A", "3º Ano Integral B"]
    assert [a["Nome"] for a in kw["turmas"]["3º Ano Integral A"]] == ["Ana"]            # transferido fora (padrão: só matriculados)


def test_limpeza_sem_confirmacao_nao_executa_sem_terminal(chamadas, capsys):
    assert s.main(["--limpeza"]) == 2                                                    # sem --teste e sem terminal
    assert "--confirmo" in capsys.readouterr().err and chamadas == []


def test_limpeza_com_confirmo_executa_em_todas_as_turmas(chamadas):
    assert s.main(["--limpeza", "--confirmo"]) == 0
    assert chamadas[0][1]["turmas_selecionadas"] == list(TURMAS)


def test_limpeza_pergunta_sim_no_terminal(chamadas, monkeypatch):
    class Terminal:
        def isatty(self):
            return True
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda *_: "nao")
    assert s.main(["--limpeza"]) == 2 and chamadas == []
    monkeypatch.setattr("builtins.input", lambda *_: "sim")
    assert s.main(["--limpeza"]) == 0 and len(chamadas) == 1


def test_simular_mostra_a_previa_e_nao_executa(chamadas, capsys):
    assert s.main(["--limpeza", "--turma", "5", "--simular"]) == 0
    saida = capsys.readouterr().out
    assert "Prévia:" in saida and "modo_limpeza" in saida and "nada foi executado" in saida and chamadas == []


def test_turma_sem_valor_abre_menu_de_uma_turma_e_turmas_o_menu_multiplo(chamadas, monkeypatch):
    monkeypatch.setattr(s, "menu_selecionar_turma", lambda turmas: "5º Ano Integral A")
    assert s.main(["--limpeza", "--teste", "--turma"]) == 0
    assert chamadas[-1][1]["turmas_selecionadas"] == ["5º Ano Integral A"]
    monkeypatch.setattr(s, "menu_selecionar_multiplas_turmas", lambda turmas: ["3º Ano Integral B", "5º Ano Integral A"])
    assert s.main(["--limpeza", "--teste", "--turmas"]) == 0
    assert chamadas[-1][1]["turmas_selecionadas"] == ["3º Ano Integral B", "5º Ano Integral A"]


def test_cancelar_o_menu_nao_executa(chamadas, monkeypatch, capsys):
    monkeypatch.setattr(s, "menu_selecionar_turma", lambda turmas: None)
    assert s.main(["--limpeza", "--teste", "--turma"]) == 2 and chamadas == []
    assert "Cancelado" in capsys.readouterr().err


# ───────────── documento e espec ─────────────

def test_documento_com_id_valido_e_invalido(chamadas, capsys):
    assert s.main(["--documento", ID_VALIDO, "--teste"]) == 0
    nome, kw = chamadas[0]
    assert nome == "modo_documento" and kw["idtipo"] == ID_VALIDO and kw["nome_slot"] == NOME_VALIDO
    assert s.main(["--documento", "999999", "--teste"]) == 2 and "desconhecido" in capsys.readouterr().err
    assert len(chamadas) == 1


def test_documento_sem_id_usa_o_menu_e_cancelar_nao_executa(chamadas, monkeypatch):
    monkeypatch.setattr(s, "menu_selecionar_tipo_documento", lambda: (ID_VALIDO, NOME_VALIDO))
    assert s.main(["--documento", "--teste"]) == 0 and chamadas[0][1]["idtipo"] == ID_VALIDO
    monkeypatch.setattr(s, "menu_selecionar_tipo_documento", lambda: None)
    assert s.main(["--documento", "--teste"]) == 2 and len(chamadas) == 1


def test_espec_repassa_idtipo_alvo(chamadas):
    assert s.main(["--espec", ID_VALIDO, "--turma", "5", "--teste"]) == 0
    nome, kw = chamadas[0]
    assert nome == "modo_espec" and kw["idtipo_alvo"] == ID_VALIDO and kw["turmas_selecionadas"] == ["5º Ano Integral A"]


# ───────────── aluno, transferidos, validar, analisa ─────────────

def test_aluno_repassa_cgms_erros_e_faltando(chamadas):
    assert s.main(["--aluno", "--cgm", "3000000001,3000000002", "3000000003", "--erros", "--faltando", "--teste"]) == 0
    nome, kw = chamadas[0]
    assert nome == "modo_aluno" and kw == {"modo_teste": True, "modo_erros": True, "modo_faltando": True,
                                           "cgms": ["3000000001", "3000000002", "3000000003"]}


def test_aluno_com_cgm_invalido_e_recusado(chamadas, capsys):
    assert s.main(["--aluno", "--cgm", "12", "--teste"]) == 2 and "formato inválido" in capsys.readouterr().err
    assert chamadas == []


def test_aluno_sem_cgm_usa_a_lista_configurada(chamadas):
    assert s.main(["--aluno", "--teste"]) == 0 and chamadas[0][1]["cgms"] == []


def test_transferidos_sozinho_e_o_modo_de_upload(chamadas):
    assert s.main(["--transferidos", "--teste"]) == 0
    assert chamadas == [("modo_transferidos", {"modo_teste": True})]


def test_validar_com_transferidos_valida_so_transferidos_e_repassa_o_delay(chamadas):
    assert s.main(["--validar", "--transferidos", "--delay", "3", "--teste"]) == 0
    nome, kw = chamadas[0]
    assert nome == "modo_validar" and kw["somente_transferidos"] is True and kw["delay_segundos"] == 3
    assert [a["Nome"] for a in kw["turmas"]["3º Ano Integral A"]] == ["Beto"]
    assert s.main(["--validar", "--teste"]) == 0
    assert chamadas[-1][1]["somente_transferidos"] is False and chamadas[-1][1]["delay_segundos"] == s.DELAY_VALIDACAO_PADRAO


def test_validar_delay_negativo_e_recusado(chamadas):
    assert s.main(["--validar", "--delay", "-1", "--teste"]) == 2 and chamadas == []


def test_analisa_repassa_o_resto_dos_argumentos_sem_interpretar(chamadas):
    assert s.main(["--analisa", "--turma", "5", "--rapido"]) == 0
    assert chamadas == [("modo_analisa", {"args_extras": ["--turma", "5", "--rapido"]})]


# ───────────── falhas dos modos viram código de saída ─────────────

def test_encerramento_forcado_sai_com_codigo_1(chamadas, monkeypatch, capsys):
    async def aborta(**kw):
        raise s.EncerramentoForcado("SERE parece fora do ar")
    monkeypatch.setattr(s, "modo_validar", aborta)
    assert s.main(["--validar", "--teste"]) == 1 and "SERE parece fora do ar" in capsys.readouterr().err


def test_sys_exit_do_modo_e_excecao_viram_codigo_de_saida(chamadas, monkeypatch, capsys):
    async def sai(**kw):
        raise SystemExit(1)

    async def quebra(**kw):
        raise RuntimeError("deu ruim")
    monkeypatch.setattr(s, "modo_aluno", sai)
    assert s.main(["--aluno", "--teste"]) == 1
    monkeypatch.setattr(s, "modo_aluno", quebra)
    assert s.main(["--aluno", "--teste"]) == 1 and "RuntimeError: deu ruim" in capsys.readouterr().err

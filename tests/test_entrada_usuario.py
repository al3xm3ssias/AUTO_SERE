"""entrada_usuario: perguntas que a automação faz ao usuário no meio da execução (ex.: código 2FA)."""
import asyncio
import threading
import time

import pytest

from src.comum import entrada_usuario as eu


@pytest.fixture(autouse=True)
def _limpo():
    eu.usar_terminal(False)
    eu._PENDENTES.clear()
    yield
    eu.usar_terminal(False)
    eu._PENDENTES.clear()


def _rodar(coro):
    return asyncio.run(coro)


def test_pergunta_e_resposta():
    async def cenario():
        tarefa = asyncio.create_task(eu.perguntar("x", "Código", "msg", "Código do e-mail", intervalo=0.01))
        await asyncio.sleep(0.05)
        p = eu.pergunta_pendente("x")
        assert p["titulo"] == "Código" and p["rotulo"] == "Código do e-mail" and p["segredo"] is False
        assert "resposta" not in p and "validar" not in p            # nada interno vaza para a tela
        assert eu.responder("x", p["id"], " 123456 ")[0] is True
        assert await tarefa == "123456"
        assert eu.pergunta_pendente("x") is None                      # apagada depois de respondida
    _rodar(cenario())


def test_resposta_de_outra_thread():
    """O caso real: a automação espera numa thread e a rota Flask responde de outra."""
    async def cenario():
        def da_interface():
            for _ in range(200):
                p = eu.pergunta_pendente("y")
                if p:
                    eu.responder("y", p["id"], "999000")
                    return
                time.sleep(0.01)
        t = threading.Thread(target=da_interface)
        t.start()
        valor = await eu.perguntar("y", "Código", intervalo=0.01)
        t.join()
        return valor
    assert _rodar(cenario()) == "999000"


def test_validacao_recusa_sem_fechar_o_pedido():
    def so_digitos(v):
        if not v.isdigit():
            raise ValueError("Só números.")

    async def cenario():
        tarefa = asyncio.create_task(eu.perguntar("x", "C", validar=so_digitos, intervalo=0.01))
        await asyncio.sleep(0.05)
        pid = eu.pergunta_pendente("x")["id"]
        ok, msg = eu.responder("x", pid, "abc")
        assert (ok, msg) == (False, "Só números.")
        assert eu.pergunta_pendente("x") is not None                  # continua aberta
        assert eu.responder("x", pid, "123")[0] is True
        assert await tarefa == "123"
    _rodar(cenario())


def test_resposta_vazia_ou_id_errado_ou_sem_pergunta():
    async def cenario():
        tarefa = asyncio.create_task(eu.perguntar("x", "C", intervalo=0.01))
        await asyncio.sleep(0.05)
        pid = eu.pergunta_pendente("x")["id"]
        assert eu.responder("x", pid, "   ")[0] is False
        assert eu.responder("x", "id-velho", "1")[0] is False
        assert eu.responder("outra", pid, "1")[0] is False
        eu.responder("x", pid, "1")
        await tarefa
    _rodar(cenario())
    assert eu.responder("x", "qualquer", "1")[0] is False             # nada pendente


def test_cancelar_a_tarefa_apaga_o_pedido():
    async def cenario():
        tarefa = asyncio.create_task(eu.perguntar("x", "C", intervalo=0.01))
        await asyncio.sleep(0.05)
        assert eu.pergunta_pendente("x") is not None
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
        assert eu.pergunta_pendente("x") is None
    _rodar(cenario())


def test_cancelar_pendente_explicito():
    async def cenario():
        tarefa = asyncio.create_task(eu.perguntar("x", "C", intervalo=0.01))
        await asyncio.sleep(0.05)
        eu.cancelar_pendente("x")
        assert eu.pergunta_pendente("x") is None
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
    _rodar(cenario())


def test_timeout():
    with pytest.raises(eu.PedidoExpirou, match="Ninguém respondeu"):
        _rodar(eu.perguntar("x", "Código", timeout=0.05, intervalo=0.01))
    assert eu.pergunta_pendente("x") is None


def test_modo_terminal_usa_input(monkeypatch):
    respostas = iter(["", "abc", " 654321 "])
    monkeypatch.setattr("builtins.input", lambda *_: next(respostas))

    def so_digitos(v):
        if not v.isdigit():
            raise ValueError("Só números.")
    eu.usar_terminal(True)
    assert _rodar(eu.perguntar("x", "Código", validar=so_digitos)) == "654321"
    assert eu.pergunta_pendente("x") is None                          # no terminal nada fica pendente


def test_modo_terminal_segredo_usa_getpass(monkeypatch):
    chamado = []
    monkeypatch.setattr("getpass.getpass", lambda *_: chamado.append(1) or "s3gredo")
    eu.usar_terminal(True)
    assert _rodar(eu.perguntar("x", "Senha", segredo=True)) == "s3gredo" and chamado

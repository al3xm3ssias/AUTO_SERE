"""Testes do launcher, do PWA (manifest/service worker) e do endereço do servidor."""
import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import launcher  # noqa: E402
from src.comum import servidor  # noqa: E402
from src.web.app import create_app  # noqa: E402


@pytest.fixture()
def cliente():
    return create_app().test_client()


# ── rotas do PWA ────────────────────────────────────────────────────────────

def test_ping_identifica_o_auto_sere(cliente):
    dados = cliente.get("/web/api/ping").get_json()
    assert dados["app"] == "auto-sere" and dados["ok"] is True


def test_manifest_e_instalavel(cliente):
    r = cliente.get("/manifest.webmanifest")
    assert r.mimetype == "application/manifest+json"
    m = r.get_json()
    assert m["display"] == "standalone"
    assert m["start_url"] == "/web" and m["scope"] == "/"
    tamanhos = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= tamanhos
    for icone in m["icons"]:  # todo ícone declarado precisa existir e ser servido
        assert cliente.get(icone["src"]).status_code == 200, icone["src"]


def test_service_worker_na_raiz_sem_cache(cliente):
    r = cliente.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["Service-Worker-Allowed"] == "/"
    assert r.headers["Cache-Control"] == "no-cache"


def test_pagina_principal_referencia_manifest_e_sw(cliente):
    html = cliente.get("/web").get_data(as_text=True)
    assert 'rel="manifest"' in html
    assert "serviceWorker" in html


# ── host/porta ──────────────────────────────────────────────────────────────

def test_servidor_padrao(monkeypatch):
    monkeypatch.delenv("AUTO_SERE_HOST", raising=False)
    monkeypatch.delenv("AUTO_SERE_PORT", raising=False)
    monkeypatch.setattr(servidor, "_bloco_config", lambda: {})
    assert servidor.servidor_host() == "127.0.0.1"
    assert servidor.servidor_porta() == 8000
    assert servidor.url_base() == "http://127.0.0.1:8000"


def test_servidor_precedencia_env_sobre_config(monkeypatch):
    monkeypatch.setattr(servidor, "_bloco_config", lambda: {"host": "127.0.0.1", "porta": 9000})
    monkeypatch.delenv("AUTO_SERE_PORT", raising=False)
    assert servidor.servidor_porta() == 9000
    monkeypatch.setenv("AUTO_SERE_PORT", "8123")
    assert servidor.servidor_porta() == 8123


@pytest.mark.parametrize("ruim", ["abc", "0", "70000", ""])
def test_porta_invalida_cai_no_padrao(monkeypatch, ruim):
    monkeypatch.setattr(servidor, "_bloco_config", lambda: {})
    monkeypatch.setenv("AUTO_SERE_PORT", ruim)
    assert servidor.servidor_porta() == 8000


def test_url_base_troca_0000_por_loopback(monkeypatch):
    monkeypatch.setenv("AUTO_SERE_HOST", "0.0.0.0")
    monkeypatch.setenv("AUTO_SERE_PORT", "8000")
    assert servidor.url_base() == "http://127.0.0.1:8000"


def test_debug_desligado_por_padrao(monkeypatch):
    monkeypatch.delenv("AUTO_SERE_DEBUG", raising=False)
    assert servidor.modo_debug() is False
    monkeypatch.setenv("AUTO_SERE_DEBUG", "1")
    assert servidor.modo_debug() is True


# ── lock e navegador ────────────────────────────────────────────────────────

@pytest.fixture()
def isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "LOCK_ARQUIVO", tmp_path / "launcher.lock")
    monkeypatch.setattr(launcher, "PID_ARQUIVO", tmp_path / "servidor.pid")
    monkeypatch.setattr(launcher, "LOG_LAUNCHER", tmp_path / "launcher.log")
    monkeypatch.setattr(launcher, "LOG_SERVIDOR", tmp_path / "servidor.log")
    monkeypatch.setattr(launcher.paths, "LOCKS_DIR", tmp_path)
    monkeypatch.setattr(launcher.paths, "LOGS_DIR", tmp_path)
    return tmp_path


def test_lock_impede_segundo_launcher(isolado):
    assert launcher._adquirir_lock() is True
    assert launcher._adquirir_lock() is False
    launcher._liberar_lock()
    assert launcher._adquirir_lock() is True


def test_lock_abandonado_e_recuperado(isolado):
    assert launcher._adquirir_lock() is True
    velho = time.time() - launcher.LOCK_VALIDADE_S - 5
    os.utime(launcher.LOCK_ARQUIVO, (velho, velho))
    assert launcher._adquirir_lock() is True


def test_chrome_manual_por_variavel(tmp_path, monkeypatch):
    falso = tmp_path / "chrome.exe"
    falso.write_text("x")
    monkeypatch.setenv("AUTO_SERE_CHROME", str(falso))
    assert launcher.localizar_chrome() == falso


def test_abrir_janela_usa_modo_app(isolado, tmp_path, monkeypatch):
    falso = tmp_path / "chrome.exe"
    falso.write_text("x")
    monkeypatch.setenv("AUTO_SERE_CHROME", str(falso))
    chamadas = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, **kw: chamadas.append(cmd))
    assert launcher.abrir_janela("http://127.0.0.1:8000/web") is True
    assert chamadas[0] == [str(falso), "--app=http://127.0.0.1:8000/web"]


# ── ponta a ponta: sobe de verdade, não duplica, e para ─────────────────────

def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sobe_uma_vez_so_e_para(isolado, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_PORT", str(_porta_livre()))
    monkeypatch.setenv("AUTO_SERE_HOST", "127.0.0.1")
    try:
        assert launcher.main(["--sem-janela"]) == 0
        assert launcher._ping()
        pid1 = launcher.PID_ARQUIVO.read_text()

        # "Segundo clique": não pode subir outro servidor.
        assert launcher.main(["--sem-janela"]) == 0
        assert launcher.PID_ARQUIVO.read_text() == pid1
    finally:
        launcher.parar_servidor()
    time.sleep(0.5)
    assert not launcher._ping()


def test_porta_ocupada_por_outro_programa_avisa(isolado, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        monkeypatch.setenv("AUTO_SERE_PORT", str(s.getsockname()[1]))
        avisos = []
        monkeypatch.setattr(launcher, "_aviso", lambda t, m: avisos.append(m))
        assert launcher.main(["--sem-janela"]) == 1
        assert avisos and "em uso" in avisos[0]


# ── navegadores do Playwright dentro do projeto ─────────────────────────────

def test_ambiente_do_servidor_aponta_para_navegadores_locais(tmp_path, monkeypatch):
    (tmp_path / "runtime" / "browsers").mkdir(parents=True)
    monkeypatch.setattr(launcher.paths, "RAIZ_PROJETO", tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("AUTO_SERE_DEBUG", "1")
    env = launcher.ambiente_do_servidor()
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "runtime" / "browsers")
    assert env["PYTHONUTF8"] == "1"
    assert "AUTO_SERE_DEBUG" not in env


def test_ambiente_do_servidor_respeita_variavel_existente(tmp_path, monkeypatch):
    (tmp_path / "runtime" / "browsers").mkdir(parents=True)
    monkeypatch.setattr(launcher.paths, "RAIZ_PROJETO", tmp_path)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "D:/meus-navegadores")
    assert launcher.ambiente_do_servidor()["PLAYWRIGHT_BROWSERS_PATH"] == "D:/meus-navegadores"


def test_sem_pasta_runtime_nao_define_variavel(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.paths, "RAIZ_PROJETO", tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert "PLAYWRIGHT_BROWSERS_PATH" not in launcher.ambiente_do_servidor()

"""Navegador das automações: padrão global (Chrome/Firefox), "ver a janela" por script e lançamento central."""
import asyncio
import re
import time
from pathlib import Path

import pytest

from src.comum import configuracao, navegador
from src.comum import registro_scripts as reg
from src.comum.execucao_gui import ExecucaoEmBackground
from src.web.api import rotas
from src.web.app import create_app


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """Configuração isolada em pasta temporária (não toca config/config_usuario.json)."""
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    return configuracao


# ───────────────────────────── configuração ─────────────────────────────

def test_padrao_e_automatico_e_nao_cria_arquivo(cfg):
    assert cfg.navegador_padrao() == ""
    assert cfg.mostrar_janela_script("turmas") is None
    assert not cfg.ARQUIVO_CONFIG.exists()


def test_define_navegador_padrao(cfg):
    assert cfg.definir_navegador_padrao("Chrome") == "chromium"
    assert cfg.navegador_padrao() == "chromium"
    assert cfg.definir_navegador_padrao("firefox") == "firefox"
    assert cfg.definir_navegador_padrao("automatico") == ""
    assert cfg.navegador_padrao() == ""
    with pytest.raises(ValueError):
        cfg.definir_navegador_padrao("edge")


def test_mostrar_janela_e_por_script_e_none_volta_ao_padrao(cfg):
    cfg.definir_mostrar_janela_script("turmas", True)
    cfg.definir_mostrar_janela_script("alunos", False)
    assert cfg.mostrar_janela_script("turmas") is True and cfg.mostrar_janela_script("alunos") is False
    assert cfg.mostrar_janela_script("sus") is None
    cfg.definir_mostrar_janela_script("turmas", None)
    assert cfg.mostrar_janela_script("turmas") is None


def test_salvar_navegador_nao_apaga_outras_configuracoes(cfg):
    cfg.definir_observacao_historico("texto que já existia")
    cfg.definir_navegador_padrao("firefox")
    cfg.definir_mostrar_janela_script("turmas", True)
    assert cfg.observacao_historico() == "texto que já existia"


# ───────────────────────────── resolução (motor e headless) ─────────────────────────────

def test_sem_configuracao_vale_o_que_o_script_ja_usava(cfg):
    assert navegador.resolver("firefox", True, chave="validar") == ("firefox", True)
    assert navegador.resolver("chromium", False, chave="rematricula") == ("chromium", False)   # padrão do script: janela visível


def test_navegador_global_troca_o_motor_mas_nao_o_headless(cfg):
    cfg.definir_navegador_padrao("chromium")
    assert navegador.resolver("firefox", True, chave="validar") == ("chromium", True)
    cfg.definir_navegador_padrao("firefox")
    assert navegador.resolver("chromium", False, chave="rematricula") == ("firefox", False)


def test_motor_travado_ignora_o_navegador_global(cfg):
    cfg.definir_navegador_padrao("firefox")
    assert navegador.resolver("chromium", True, travar_motor=True, chave="parecer_rco") == ("chromium", True)


def test_janela_do_script_vale_so_para_ele(cfg):
    cfg.definir_mostrar_janela_script("turmas", True)
    assert navegador.resolver("chromium", True, chave="turmas") == ("chromium", False)
    assert navegador.resolver("chromium", True, chave="alunos") == ("chromium", True)
    cfg.definir_mostrar_janela_script("turmas", False)
    assert navegador.resolver("chromium", False, chave="turmas") == ("chromium", True)   # esconder também vale


def test_janela_pedida_na_execucao_vence_a_escolha_salva(cfg):
    cfg.definir_mostrar_janela_script("base_abc", False)
    assert navegador.resolver("firefox", True, forcar_mostrar=True, chave="base_abc") == ("firefox", False)


def test_configuracao_ilegivel_nao_derruba_a_execucao(cfg):
    cfg.ARQUIVO_CONFIG.write_text("{ isto não é json", encoding="utf-8")
    assert navegador.resolver("firefox", True, chave="validar") == ("firefox", True)


class _Motor:
    def __init__(self, nome, chamadas):
        self.nome, self.chamadas = nome, chamadas

    async def launch(self, **kw):
        self.chamadas.append((self.nome, kw))
        return object()


class _P:
    def __init__(self):
        self.chamadas = []
        self.chromium, self.firefox = _Motor("chromium", self.chamadas), _Motor("firefox", self.chamadas)


def test_lancar_abre_o_motor_certo_e_repassa_os_argumentos(cfg):
    p = _P()
    cfg.definir_navegador_padrao("firefox")
    token = navegador.definir_script("turmas")
    try:
        cfg.definir_mostrar_janela_script("turmas", True)
        asyncio.run(navegador.lancar(p, "chromium", True, slow_mo=200))
    finally:
        navegador.restaurar(token)
    assert p.chamadas == [("firefox", {"headless": False, "slow_mo": 200})]


def test_lancar_sem_configuracao_e_igual_ao_launch_de_antes(cfg):
    p = _P()
    asyncio.run(navegador.lancar(p, "firefox", True))
    asyncio.run(navegador.lancar(p, "chromium", False))
    assert p.chamadas == [("firefox", {"headless": True}), ("chromium", {"headless": False})]


# ───────────────────────────── qual script está rodando ─────────────────────────────

def test_a_thread_da_execucao_enxerga_o_script_que_a_iniciou():
    vistos = []
    token = navegador.definir_script("turmas")
    try:
        ex = ExecucaoEmBackground().iniciar(lambda: vistos.append(navegador.script_atual()))
    finally:
        navegador.restaurar(token)
    assert ex.aguardar(5) and vistos == ["turmas"]
    assert navegador.script_atual() is None                       # e o servidor não fica "preso" a ele


def test_a_coroutine_da_execucao_tambem_enxerga():
    vistos = []

    async def trabalho():
        vistos.append(navegador.script_atual())

    token = navegador.definir_script("sus")
    try:
        ex = ExecucaoEmBackground().iniciar(trabalho())
    finally:
        navegador.restaurar(token)
    assert ex.aguardar(5) and vistos == ["sus"]


def test_executar_plano_marca_o_script_durante_o_disparo(monkeypatch):
    vistos = []
    monkeypatch.setattr(rotas, "_disparar_plano", lambda chave, plano: vistos.append(navegador.script_atual()))
    rotas._executar_plano("limpeza", object())
    assert vistos == ["limpeza"] and navegador.script_atual() is None


# ───────────────────────────── padrão para todos os módulos ─────────────────────────────

def test_nenhum_script_abre_navegador_sem_passar_pelo_helper():
    """Quem chamar `.launch(` direto escapa do navegador padrão e do "ver a janela": use navegador.lancar."""
    raiz = Path(__file__).resolve().parent.parent / "src"
    suspeitos = []
    for arq in raiz.rglob("*.py"):
        if arq.name == "navegador.py":
            continue
        for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(chromium|firefox|webkit)\.launch\(|\)\.launch\(headless", linha) and not linha.lstrip().startswith("#"):
                suspeitos.append(f"{arq.relative_to(raiz.parent)}:{n}")
    assert not suspeitos, f"Abrem navegador sem navegador.lancar: {suspeitos}"


def test_scripts_com_navegador_estao_registrados_e_mapeados():
    assert set(reg.NAVEGADOR_DOS_SCRIPTS) <= set(reg.REGISTRO)
    for chave, (motor, _travado) in reg.NAVEGADOR_DOS_SCRIPTS.items():
        assert motor in navegador.MOTORES
        assert "navegador" in reg.REGISTRO[chave].configs, chave
    for chave, script in reg.REGISTRO.items():
        if "navegador" in script.configs:
            assert chave in reg.NAVEGADOR_DOS_SCRIPTS, chave


def test_rco_fica_travado_no_chrome():
    assert reg.navegador_do_script("parecer_rco") == ("chromium", True)


# ───────────────────────────── rotas ─────────────────────────────

@pytest.fixture()
def cli(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    return create_app().test_client()


def test_rota_global_salva_e_le(cli):
    assert cli.get("/web/api/configuracoes/navegador").get_json()["navegador"] == "automatico"
    r = cli.post("/web/api/configuracoes/navegador", json={"navegador": "firefox"})
    assert r.status_code == 200 and r.get_json()["navegador"] == "firefox"
    assert cli.get("/web/api/configuracoes/navegador").get_json()["navegador"] == "firefox"
    assert cli.post("/web/api/configuracoes/navegador", json={"navegador": "edge"}).status_code == 400
    assert cli.post("/web/api/configuracoes/navegador", json={"navegador": "chromium"}).get_json()["navegador"] == "chromium"


def test_rota_do_script_salva_a_janela_e_mostra_o_navegador_em_uso(cli):
    c = cli.get("/web/api/automacoes/turmas/configuracao").get_json()["navegador"]
    assert c == {"usa": True, "mostrar_janela": False, "janela_configurada": False, "navegador": "Chrome",
                 "origem": "padrão deste script"}
    r = cli.post("/web/api/automacoes/turmas/navegador", json={"mostrar_janela": True}).get_json()
    assert r["mostrar_janela"] is True and r["janela_configurada"] is True
    cli.post("/web/api/configuracoes/navegador", json={"navegador": "firefox"})
    c = cli.get("/web/api/automacoes/turmas/configuracao").get_json()["navegador"]
    assert c["navegador"] == "Firefox" and c["origem"] == "definido em Configurações" and c["mostrar_janela"] is True
    assert cli.post("/web/api/automacoes/turmas/navegador", json={"mostrar_janela": None}).get_json()["janela_configurada"] is False


def test_rco_mostra_chrome_fixo_mesmo_com_firefox_global(cli):
    cli.post("/web/api/configuracoes/navegador", json={"navegador": "firefox"})
    c = cli.get("/web/api/automacoes/parecer_rco/configuracao").get_json()["navegador"]
    assert c["navegador"] == "Chrome" and "fixo" in c["origem"]


def test_script_sem_navegador_nao_tem_bloco_e_recusa_o_post(cli):
    assert cli.get("/web/api/automacoes/backup/configuracao").get_json()["navegador"] == {"usa": False}
    assert cli.post("/web/api/automacoes/backup/navegador", json={"mostrar_janela": True}).status_code == 400
    assert cli.post("/web/api/automacoes/nao_existe/navegador", json={"mostrar_janela": True}).status_code == 404
    assert cli.post("/web/api/automacoes/turmas/navegador", json={"mostrar_janela": "sim"}).status_code == 400
    assert cli.post("/web/api/automacoes/turmas/navegador", json={}).status_code == 400

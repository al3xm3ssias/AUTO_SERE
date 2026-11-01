"""Fluxo de transferidos: DATA_CORTE, pastas, fila, simulações e pareceres (sem rede, sem SERE)."""
import asyncio
import json
from datetime import date

import pytest

from src.comum import configuracao, paths
from src.comum import pastas_transferencias as pt_
from src.automacao import fila_transferidos as ft


# ── utilitários ──────────────────────────────────────────────────────────

def _al(n, cgm, nome, nasc="01/01/2015", sit="Matriculado", data="05/02/2026"):
    return {"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Situação": sit, "Data Matricula": data}


def _turmas():
    return {"1º Ano Integral A": [
        _al(1, "11", "ALICIA SOARES"),
        _al(2, "22", "ANNA DIAS", "29/02/2020", "Transferido", "13/05/2026"),       # antes do corte
        _al(3, "33", "SAMUEL NASCIMENTO", "11/12/2019", "Transferido", "20/07/2026"),  # depois
        _al(4, "44", "FULANO SILVA", "10/10/2014", "Transferido", "31/08/2026"),
        _al(31, "44", "FULANO SILVA", "10/10/2014", "Matriculado", "22/10/2026"),      # retornou
    ]}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    dados = tmp_path / "dados"
    dados.mkdir()
    return dados


def _gravar(caminho, dados):
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def _ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


# ══ DATA_CORTE ════════════════════════════════════════════════════════════

def test_data_corte_padrao_e_22_06_do_ano_letivo(ambiente):
    assert configuracao.data_corte_transferidos() == date(int(paths.ano_atual()), 6, 22)
    assert not configuracao.data_corte_transferidos_configurada()


def test_definir_data_corte_e_voltar_ao_padrao(ambiente):
    assert configuracao.definir_data_corte_transferidos("01/09/2026") == date(2026, 9, 1)
    assert configuracao.data_corte_transferidos() == date(2026, 9, 1)
    configuracao.definir_data_corte_transferidos("")
    assert not configuracao.data_corte_transferidos_configurada()


@pytest.mark.parametrize("ruim", ["31/02/2026", "ontem", "2026", "32/13/2026"])
def test_data_corte_invalida(ambiente, ruim):
    with pytest.raises(ValueError, match="dd/mm/aaaa"):
        configuracao.definir_data_corte_transferidos(ruim)
    assert not configuracao.data_corte_transferidos_configurada()


# ══ pastas ════════════════════════════════════════════════════════════════

def test_pastas_criadas_com_os_4_nomes(ambiente):
    criadas = pt_.garantir_pastas(ambiente)
    assert {p.name for p in criadas} == {"PROCESSAMENTO DE PARECERES", "PARECERES", "HISTORICO", "GUIA DE TRANSFERENCIA"}
    assert pt_.pasta_transferencias(ambiente) == ambiente / "TRANSFERENCIAS"
    assert pt_.garantir_pastas(ambiente) == []                      # idempotente


def test_pastas_antigas(tmp_path):
    assert pt_.pastas_antigas(pt_.HISTORICO, tmp_path) == [tmp_path / "TRANSFERENCIAS" / "HISTÓRICOS"]
    assert pt_.pastas_antigas(pt_.HISTORICO, None) == []
    with pytest.raises(ValueError):
        pt_.subpasta("OUTRA", tmp_path)


# ══ fila ══════════════════════════════════════════════════════════════════

def test_fila_classifica_pelo_corte(ambiente):
    fila, _ = ft.montar_fila(_turmas(), date(2026, 6, 22))
    sit = {cgm: a["situacao_fila"] for cgm, a in fila["alunos"].items()}
    assert sit == {"22": "antes_do_corte", "33": "processar", "44": "retornou"}
    r = fila["resumo"]
    assert (r["alunos"], r["ativos"], r["transferidos_atuais"], r["retornaram"]) == (4, 2, 2, 1)
    assert (r["a_processar"], r["antes_do_corte"], r["retornaram_sem_processar"]) == (1, 1, 1)


def test_corte_e_inclusivo(ambiente):
    fila, _ = ft.montar_fila(_turmas(), date(2026, 7, 20))          # Samuel foi transferido EM 20/07
    assert fila["alunos"]["33"]["processar"] is True
    fila, _ = ft.montar_fila(_turmas(), date(2026, 7, 21))
    assert fila["alunos"]["33"]["processar"] is False


def test_quem_retornou_fica_na_fila_mas_nao_e_processado(ambiente):
    """Decisão do usuário: o processo é feito uma vez; quem voltou à escola não se refaz."""
    fila, _ = ft.montar_fila(_turmas(), date(2026, 6, 22))
    f = fila["alunos"]["44"]
    assert f["retornou"] and f["retorno"] == {"chamada": 31, "turma": "1º Ano Integral A", "data": "22/10/2026"}
    assert f["situacao_fila"] == "retornou" and f["processar"] is False
    assert [a["cgm"] for a in ft.alunos_a_processar(fila)] == ["33"]


def test_retornou_mas_transferido_antes_do_corte_continua_antes_do_corte(ambiente):
    turmas = {"A": [_al(1, "1", "ALUNO UM", sit="Transferido", data="10/03/2026"),
                    _al(2, "1", "ALUNO UM", sit="Matriculado", data="10/05/2026")]}
    fila, _ = ft.montar_fila(turmas, date(2026, 6, 22))
    assert fila["alunos"]["1"]["situacao_fila"] == "antes_do_corte"


def test_registrar_fila_grava_fila_e_cria_transferidos(ambiente):
    r = ft.registrar_fila_transferidos(_turmas(), ambiente, date(2026, 6, 22))
    assert r["novos_em_transferidos"] == 1
    assert set(_ler(ambiente / "fila_transferidos.json")["alunos"]) == {"22", "33", "44"}
    controle = _ler(ambiente / "transferidos.json")
    assert set(controle) == {"33"}                                  # pré-corte (22) e quem retornou (44) não entram
    assert controle["33"]["guia"]["emitido_em"] is None and controle["33"]["data_transferencia"] == "20/07/2026"


def test_registrar_fila_nao_mexe_em_registro_existente(ambiente):
    existente = {"33": {"nome": "SAMUEL NASCIMENTO", "turma": "x", "guia": {"emitido_em": "2026-09-01T10:00:00"}}}
    _gravar(ambiente / "transferidos.json", existente)
    ft.registrar_fila_transferidos(_turmas(), ambiente, date(2026, 6, 22))
    assert _ler(ambiente / "transferidos.json")["33"] == existente["33"]


def test_simulacao_nao_grava_nada(ambiente, capsys):
    r = ft.registrar_fila_transferidos(_turmas(), ambiente, date(2026, 6, 22), simulacao=True)
    assert list(ambiente.iterdir()) == []
    assert r["fila"]["resumo"]["a_processar"] == 1
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "SAMUEL NASCIMENTO" in saida and "antes do corte" in saida and "⏭ retornou" in saida


def test_fila_refeita_quando_a_data_de_corte_muda(ambiente):
    _gravar(ambiente / "turmas.json", _turmas())
    configuracao.definir_data_corte_transferidos("22/06/2026")
    assert ft.garantir_fila(ambiente)["resumo"]["a_processar"] == 1
    configuracao.definir_data_corte_transferidos("21/07/2026")      # Samuel (20/07) passa a ser anterior ao corte
    fila = ft.garantir_fila(ambiente)
    assert ft.alunos_a_processar(fila) == []
    assert _ler(ambiente / "fila_transferidos.json")["data_corte"] == "21/07/2026"


def test_garantir_transferidos_json_cria_so_se_faltar(ambiente):
    with pytest.raises(FileNotFoundError, match="Turmas"):
        ft.garantir_transferidos_json(ambiente)
    _gravar(ambiente / "turmas.json", _turmas())
    assert ft.garantir_transferidos_json(ambiente, date(2026, 6, 22)) is True
    assert set(_ler(ambiente / "transferidos.json")) == {"33"}
    assert ft.garantir_transferidos_json(ambiente) is False


def test_transferidos_json_existe_mesmo_sem_ninguem_a_processar(ambiente):
    turmas = {"A": [_al(1, "1", "ALUNO UM")]}
    _gravar(ambiente / "turmas.json", turmas)
    ft.garantir_transferidos_json(ambiente, date(2026, 6, 22))
    assert _ler(ambiente / "transferidos.json") == {}


def test_registrar_fila_sem_falhar_nao_propaga(ambiente, capsys):
    assert ft.registrar_fila_sem_falhar({"A": "isto não é uma lista"}, ambiente) is None
    assert "NÃO foi gerada" in capsys.readouterr().out


# ══ processo_transferidos (geração de guia e histórico) — só o que roda sem SERE ═══

@pytest.fixture
def processo(ambiente, monkeypatch):
    from src.automacao import processo_transferidos as pr
    monkeypatch.setattr(pr, "_DADOS", ambiente)
    monkeypatch.setattr(pr, "JSON_TURMAS", ambiente / "turmas.json")
    monkeypatch.setattr(pr, "JSON_TRANSFERIDOS", ambiente / "transferidos.json")
    configuracao.definir_data_corte_transferidos("22/06/2026")
    _gravar(ambiente / "turmas.json", _turmas())
    return pr


def test_carregar_alunos_le_a_fila(processo, ambiente):
    alunos = processo.carregar_alunos()
    assert [(a.cgm, a.nome) for a in alunos] == [("33", "SAMUEL NASCIMENTO")]      # 44 retornou; 22 é pré-corte
    assert (ambiente / "fila_transferidos.json").exists()


def test_carregar_alunos_avisa_de_quem_retornou(processo, capsys):
    processo.carregar_alunos()
    assert "voltou(aram) à escola" in capsys.readouterr().out


def test_carregar_alunos_ignora_quem_ja_esta_completo(processo, ambiente):
    doc = {"emitido_em": "2026-08-01T10:00:00", "assinado_secretario": "2026-08-01T10:00:00",
           "assinado_diretor": "2026-08-01T10:00:00", "anexado_em": None}
    _gravar(ambiente / "transferidos.json", {"33": {"nome": "S", "turma": "T", "guia": doc, "historico": doc,
                                                    "parecer": {"digitalizado_em": None, "anexado_em": None}}})
    assert processo.carregar_alunos() == []


def test_corte_do_processo_segue_a_configuracao(processo):
    assert processo._corte().strftime("%d/%m/%Y") == "22/06/2026"
    configuracao.definir_data_corte_transferidos("01/08/2026")
    assert processo._corte().strftime("%d/%m/%Y") == "01/08/2026"


def test_simulacao_do_processo_nao_grava_nada_nem_abre_o_sere(processo, ambiente, capsys):
    asyncio.run(processo.processar_transferencias(simulacao=True))
    assert sorted(p.name for p in ambiente.iterdir()) == ["turmas.json"]      # nem fila, nem pastas, nem controle
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "SAMUEL NASCIMENTO" in saida and "histórico: a emitir" in saida
    assert "HISTORICO" in saida and "GUIA DE TRANSFERENCIA" in saida


def test_simulacao_com_etapas_do_grupo_guia(processo, capsys):
    asyncio.run(processo.processar_transferencias(etapas=processo.GRUPOS_ETAPAS["guia"], simulacao=True, modo_teste=True))
    saida = capsys.readouterr().out
    assert "Etapas (3)" in saida and "Emitir/Gerar Guia" in saida and "Gerar Histórico" not in saida
    assert "FULANO" not in saida                                              # modo teste: só o primeiro


def test_grupos_de_etapas_cobrem_as_8(processo):
    g = processo.GRUPOS_ETAPAS
    assert len(g["todas"]) == 8 and g["historico"] + g["guia"] == g["todas"]


def test_pastas_de_saida_do_processo(processo, ambiente):
    assert processo._dir_historicos() == ambiente / "TRANSFERENCIAS" / "HISTORICO"
    assert processo._dir_guia_transferencia() == ambiente / "TRANSFERENCIAS" / "GUIA DE TRANSFERENCIA"


# ══ sere_2026.modo_transferidos (varredura/simulação, sem abrir o SERE) ═══════════

@pytest.fixture
def envio(ambiente, monkeypatch):
    from src.automacao import sere_2026 as s
    monkeypatch.setattr(s, "PATH_TRANSFERIDOS", ambiente / "transferidos.json")
    monkeypatch.setattr(s, "pasta_digitalizacao_configurada", lambda: False)
    configuracao.definir_data_corte_transferidos("22/06/2026")
    doc = {"emitido_em": "2026-08-01T10:00:00", "assinado_secretario": "2026-08-01T10:00:00",
           "assinado_diretor": "2026-08-01T10:00:00", "anexado_em": None}
    _gravar(ambiente / "transferidos.json", {"33": {
        "nome": "SAMUEL NASCIMENTO", "turma": "1º Ano Integral A", "guia": doc, "historico": doc,
        "parecer": {"digitalizado_em": "2026-08-02T10:00:00", "anexado_em": None}}})
    return s


def _arquivo(ambiente, subpasta, nome="03-SAMUEL NASCIMENTO.pdf", turma="1º Ano Integral A"):
    pasta = ambiente / "TRANSFERENCIAS" / subpasta / turma
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(b"%PDF-1.4 teste")
    return pasta / nome


def test_envio_simulado_lista_os_arquivos_das_novas_pastas(envio, ambiente, capsys):
    _arquivo(ambiente, "GUIA DE TRANSFERENCIA"); _arquivo(ambiente, "HISTORICO"); _arquivo(ambiente, "PARECERES")
    asyncio.run(envio.modo_transferidos(simulacao=True))
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "Seriam enviados 3 arquivo(s)" in saida
    assert "Guia de Transferência" in saida and "Parecer Descritivo" in saida


def test_envio_filtra_por_tipo(envio, ambiente, capsys):
    _arquivo(ambiente, "GUIA DE TRANSFERENCIA"); _arquivo(ambiente, "PARECERES")
    asyncio.run(envio.modo_transferidos(tipos=("parecer",), simulacao=True))
    saida = capsys.readouterr().out
    assert "Seriam enviados 1 arquivo(s)" in saida and "Parecer Descritivo" in saida and "Guia de Transfer" not in saida


def test_envio_tipo_invalido(envio, capsys):
    asyncio.run(envio.modo_transferidos(tipos=("xyz",), simulacao=True))
    assert "Nenhum tipo válido" in capsys.readouterr().out


def test_envio_acha_arquivo_na_pasta_antiga(envio, ambiente, tmp_path, monkeypatch, capsys):
    antiga = tmp_path / "digitalizacao"
    pasta = antiga / "TRANSFERENCIAS" / "HISTÓRICOS" / "1º Ano Integral A"
    pasta.mkdir(parents=True)
    (pasta / "03-SAMUEL NASCIMENTO.pdf").write_bytes(b"%PDF-1.4 antigo")
    monkeypatch.setattr(envio, "pasta_digitalizacao_configurada", lambda: True)
    monkeypatch.setattr(envio, "pasta_digitalizacao", lambda: antiga)
    asyncio.run(envio.modo_transferidos(tipos=("historico",), simulacao=True))
    assert "HISTÓRICOS" in capsys.readouterr().out


def test_envio_simulado_nao_cria_pastas(envio, ambiente):
    asyncio.run(envio.modo_transferidos(simulacao=True))
    assert not (ambiente / "TRANSFERENCIAS").exists()


def test_o_erro_original_nao_acontece_mais(ambiente, monkeypatch):
    """Sem transferidos.json, o modo de upload cria o arquivo a partir do turmas.json em vez de abortar."""
    from src.automacao import sere_2026 as s
    monkeypatch.setattr(s, "PATH_TRANSFERIDOS", ambiente / "transferidos.json")
    _gravar(ambiente / "turmas.json", _turmas())
    configuracao.definir_data_corte_transferidos("22/06/2026")
    assert set(s._carregar_transferidos()) == {"33"}
    assert (ambiente / "fila_transferidos.json").exists()


def test_sem_transferidos_nem_turmas_sai_com_mensagem(ambiente, monkeypatch, capsys):
    from src.automacao import sere_2026 as s
    monkeypatch.setattr(s, "PATH_TRANSFERIDOS", ambiente / "transferidos.json")
    with pytest.raises(SystemExit):
        s._carregar_transferidos()
    assert "Turmas" in capsys.readouterr().out


# ══ ações da tela × etapas, e o texto da observação ═══════════════════════════════

def test_etapas_por_acoes(processo):
    n = processo._NOMES_ETAPAS
    assert processo.etapas_por_acoes(["alterar"]) == [n[1]]
    assert processo.etapas_por_acoes(list(processo.ACOES)) == n
    assert processo.etapas_por_acoes(["assinar", "emitir"], "guia") == [n[5], n[6]]
    assert processo.etapas_por_acoes(["gravar", "alterar"], "guia") == []
    assert processo.etapas_por_acoes([]) == []


@pytest.mark.parametrize("acoes,docs", [(["xyz"], "ambos"), (["emitir"], "tudo")])
def test_etapas_por_acoes_invalidas(processo, acoes, docs):
    with pytest.raises(ValueError):
        processo.etapas_por_acoes(acoes, docs)


def test_o_texto_chega_a_etapa_de_alterar(processo):
    import functools
    escolhidas = processo._escolher_etapas([processo.ETAPA_ALTERAR, processo._NOMES_ETAPAS[2]], "Meu texto")
    alterar, emitir = escolhidas[0][1], escolhidas[1][1]
    assert isinstance(alterar, functools.partial) and alterar.keywords == {"observacao": "Meu texto"}
    assert alterar.func is processo.alterar_historico and emitir is processo.gerar_historico


def test_sem_texto_a_etapa_de_alterar_fica_como_era(processo):
    assert processo._escolher_etapas([processo.ETAPA_ALTERAR])[0][1] is processo.alterar_historico


def test_a_simulacao_mostra_o_texto_da_observacao(processo, capsys):
    asyncio.run(processo.processar_transferencias(etapas=[processo.ETAPA_ALTERAR], simulacao=True,
                                                  observacao="Aluno transferido."))
    assert "Texto da observação (Alterar): 'Aluno transferido.'" in capsys.readouterr().out


def test_a_simulacao_so_de_assinar_nao_fala_de_observacao(processo, capsys):
    asyncio.run(processo.processar_transferencias(etapas=processo.etapas_por_acoes(["assinar"]), simulacao=True))
    saida = capsys.readouterr().out
    assert "Assinar Históricos" in saida and "Assinar Guias" in saida and "observação" not in saida

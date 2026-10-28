"""Ano letivo: configurar, voltar a um ano anterior, backup/restauração por ano e dados fictícios de teste."""
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from src.comum import backup, configuracao, dados_ficticios as df, escola, paths
from src.web.api import rotas
from src.web.app import create_app

URL = "/web/api/configuracoes/ano-letivo"
ANO_CIVIL = datetime.now().year


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    """Árvore temporária completa. O ano em uso é 2026 e fica 'congelado' como no programa de verdade."""
    dados = tmp_path / "dados"
    (dados / "calendario").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "DADOS_DIR", dados)
    monkeypatch.setattr(paths, "DADOS_BACKUP_DIR", dados / "backup")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    monkeypatch.setattr(escola, "nome", lambda: "Escola Municipal Profª Judith Macedo Silveira")
    monkeypatch.setattr(rotas, "_dados_dir", lambda: paths.dados_ano_atual())
    (tmp_path / "config" / "config_usuario.json").write_text(json.dumps({"ano_letivo": "2026", "pasta_modelos": None}), encoding="utf-8")
    (dados / "calendario" / "calendario.json").write_text('{"eventos": []}', encoding="utf-8")
    paths.recarregar_ano_do_processo()
    assert paths.ano_atual() == "2026"                           # lido da configuração e congelado
    (dados / "2026").mkdir()
    (dados / "2026" / "turmas.json").write_text('{"5A": []}', encoding="utf-8")
    (dados / "2026" / "alunos.json").write_text('[{"Nome": "REAL DE 2026"}]', encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    yield tmp_path
    paths.recarregar_ano_do_processo()


def _config(amb):
    return json.loads((amb / "config" / "config_usuario.json").read_text(encoding="utf-8"))


def _gravar_config(amb, **kw):
    (amb / "config" / "config_usuario.json").write_text(json.dumps(kw), encoding="utf-8")


@pytest.fixture()
def web(amb):
    return create_app().test_client()


# ───────────── paths: de onde vem o ano ─────────────

def test_ano_vem_do_ambiente_depois_da_configuracao_depois_do_calendario(amb, monkeypatch):
    _gravar_config(amb, ano_letivo="2024")
    paths.recarregar_ano_do_processo()
    assert paths.ano_atual() == "2024"
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2023")                    # o ambiente manda
    assert paths.ano_atual() == "2023" and paths.ano_fixado_por_ambiente() and paths.ano_do_proximo_inicio() == "2023"
    monkeypatch.delenv("AUTO_SERE_ANO_BASE")
    _gravar_config(amb)                                                 # sem escolha: calendário
    paths.recarregar_ano_do_processo()
    assert paths.ano_atual() == str(ANO_CIVIL) and paths.ano_configurado() is None


def test_ano_configurado_so_vale_depois_de_reiniciar(amb):
    """O ponto central: trocar a configuração com o programa aberto NÃO muda o ano em uso (nada de dois anos misturados)."""
    _gravar_config(amb, ano_letivo="2025")
    assert paths.ano_configurado() == "2025" and paths.ano_do_proximo_inicio() == "2025"     # o arquivo já diz 2025
    assert paths.ano_atual() == "2026"                                                      # mas o processo segue em 2026
    assert paths.dados_ano_atual() == amb / "dados" / "2026"
    paths.recarregar_ano_do_processo()                                                      # = reiniciar o programa
    assert paths.ano_atual() == "2025" and paths.dados_ano_atual() == amb / "dados" / "2025"


@pytest.mark.parametrize("valor", ["abc", "25", "20255", "1899", "", None, ["2025"]])
def test_configuracao_invalida_cai_no_calendario(amb, valor):
    _gravar_config(amb, ano_letivo=valor)
    paths.recarregar_ano_do_processo()
    assert paths.ano_configurado() is None and paths.ano_atual() == str(ANO_CIVIL)


def test_config_ilegivel_ou_sem_arquivo(amb):
    (amb / "config" / "config_usuario.json").write_text("{quebrado", encoding="utf-8")
    paths.recarregar_ano_do_processo()
    assert paths.ano_atual() == str(ANO_CIVIL)
    (amb / "config" / "config_usuario.json").unlink()
    paths.recarregar_ano_do_processo()
    assert paths.ano_atual() == str(ANO_CIVIL)


def test_anos_disponiveis(amb):
    (amb / "dados" / "2025").mkdir()
    (amb / "dados" / "2024").mkdir()
    (amb / "dados" / "backup").mkdir()
    (amb / "dados" / "20255").mkdir()
    (amb / "dados" / "2023.txt").write_text("x", encoding="utf-8")
    assert paths.anos_disponiveis() == ["2026", "2025", "2024"]


# ───────────── configuracao ─────────────

@pytest.mark.parametrize("valor,esperado", [("2025", "2025"), (" 2025 ", "2025"), (2025, "2025"), ("2000", "2000"), (str(ANO_CIVIL + 1), str(ANO_CIVIL + 1))])
def test_validar_ano_letivo_ok(valor, esperado):
    assert configuracao.validar_ano_letivo(valor) == esperado


@pytest.mark.parametrize("valor", ["", None, "25", "abcd", "20 25", "1999", str(ANO_CIVIL + 2), "2025.0"])
def test_validar_ano_letivo_recusa(valor):
    with pytest.raises(ValueError, match="ano letivo|intervalo"):
        configuracao.validar_ano_letivo(valor)


def test_definir_e_voltar_ao_automatico_preservam_o_resto(amb):
    _gravar_config(amb, pasta_modelos="X", unidade_escolar={"nome": "E"})
    assert configuracao.definir_ano_letivo(2025) == "2025" and configuracao.ano_letivo_configurado() == "2025"
    c = _config(amb)
    assert c["ano_letivo"] == "2025" and c["pasta_modelos"] == "X" and c["unidade_escolar"] == {"nome": "E"}
    configuracao.usar_ano_letivo_automatico()
    assert configuracao.ano_letivo_configurado() is None and _config(amb)["pasta_modelos"] == "X"


# ───────────── backup por ano ─────────────

def _ano_com_dados(amb, ano, nome="ALUNO"):
    pasta = amb / "dados" / str(ano)
    pasta.mkdir(exist_ok=True)
    (pasta / "alunos.json").write_text(json.dumps([{"Nome": f"{nome} {ano}"}]), encoding="utf-8")
    (pasta / "turmas.json").write_text(json.dumps({f"T{ano}": []}), encoding="utf-8")
    return pasta


def _conteudo(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return sorted(z.namelist())


def test_backup_de_outro_ano_copia_so_aquele_ano(amb):
    _ano_com_dados(amb, 2025)
    z = backup.criar_backup(ano=2025)
    nomes = _conteudo(z)
    assert "dados_ano/alunos.json" in nomes and "dados_ano/turmas.json" in nomes
    with zipfile.ZipFile(z) as arq:
        assert json.loads(arq.read("dados_ano/alunos.json"))[0]["Nome"] == "ALUNO 2025"            # não é o de 2026
        assert str(json.loads(arq.read(backup.MANIFESTO))["ano"]) == "2025"


def test_backup_de_ano_sem_dados(amb):
    with pytest.raises(backup.BackupVazioError):
        backup.criar_backup(ano=2019)
    assert issubclass(backup.BackupVazioError, backup.BackupInvalidoError)


def test_listagem_mostra_ano_e_motivo(amb):
    _ano_com_dados(amb, 2025)
    backup.criar_backup(motivo="manual")
    backup.criar_backup(motivo="dados_ficticios", ano=2025)
    itens = backup.listar_backups()
    assert [(i["ano"], i["motivo"]) for i in itens] == [("2025", "dados_ficticios"), ("2026", "manual")]


def test_retencao_vale_por_ano(amb):
    _ano_com_dados(amb, 2025)
    for _ in range(3):
        backup.criar_backup(ano=2025, manter=2)
    for _ in range(4):
        backup.criar_backup(manter=2)                       # depois vêm 4 de 2026
    por_ano = {}
    for i in backup.listar_backups():
        por_ano[i["ano"]] = por_ano.get(i["ano"], 0) + 1
    # com retenção global só sobrariam 2 backups, ambos de 2026: os de 2025 teriam sido apagados pelos novos
    assert por_ano == {"2025": 2, "2026": 2}


# ───────────── restauração de um ano ─────────────

def test_restaurar_ano_antigo_nao_toca_no_ano_em_uso(amb):
    pasta25 = _ano_com_dados(amb, 2025)
    z = backup.criar_backup(ano=2025)
    (pasta25 / "alunos.json").write_text('[{"Nome": "ESTRAGADO"}]', encoding="utf-8")
    (amb / "dados" / "2026" / "alunos.json").write_text('[{"Nome": "TRABALHO NOVO DE 2026"}]', encoding="utf-8")
    r = backup.restaurar_backup(z, aplicar=True, so_dados=True)
    assert r["ano"] == "2025" and r["pasta_destino"] == str(pasta25) and r["aplicado"] is True
    assert json.loads((pasta25 / "alunos.json").read_text(encoding="utf-8"))[0]["Nome"] == "ALUNO 2025"            # voltou
    assert json.loads((amb / "dados" / "2026" / "alunos.json").read_text(encoding="utf-8"))[0]["Nome"] == "TRABALHO NOVO DE 2026"
    seguranca = Path(r["backup_de_seguranca"])                                                                    # segurança é do 2025
    with zipfile.ZipFile(seguranca) as arq:
        assert str(json.loads(arq.read(backup.MANIFESTO))["ano"]) == "2025"
        assert json.loads(arq.read("dados_ano/alunos.json"))[0]["Nome"] == "ESTRAGADO"


def test_restaurar_o_ano_em_uso(amb):
    z = backup.criar_backup()
    (amb / "dados" / "2026" / "alunos.json").write_text('[{"Nome": "ESTRAGADO"}]', encoding="utf-8")
    r = backup.restaurar_backup(z, aplicar=True, so_dados=True)
    assert r["ano"] == "2026" and "REAL DE 2026" in (amb / "dados" / "2026" / "alunos.json").read_text(encoding="utf-8")
    assert r["backup_de_seguranca"]


def test_restaurar_em_pasta_do_ano_vazia_ou_inexistente(amb):
    pasta25 = _ano_com_dados(amb, 2025)
    z = backup.criar_backup(ano=2025)
    for f in pasta25.iterdir():
        f.unlink()
    pasta25.rmdir()
    r = backup.restaurar_backup(z, aplicar=True, so_dados=True)                          # nada a perder: sem segurança, mas funciona
    assert r["backup_de_seguranca"] is None and (pasta25 / "alunos.json").exists()


def test_so_dados_nao_mexe_em_config_nem_calendario(amb):
    _ano_com_dados(amb, 2025)
    z = backup.criar_backup(ano=2025)
    (amb / "config" / "config_usuario.json").write_text('{"mudou": true}', encoding="utf-8")
    (amb / "dados" / "calendario" / "calendario.json").write_text('{"mudou": true}', encoding="utf-8")
    backup.restaurar_backup(z, aplicar=True, so_dados=True)
    assert _config(amb) == {"mudou": True}
    assert json.loads((amb / "dados" / "calendario" / "calendario.json").read_text(encoding="utf-8")) == {"mudou": True}


def test_restaurar_config_nao_desfaz_a_escolha_do_ano(amb):
    _ano_com_dados(amb, 2025)
    z = backup.criar_backup(ano=2025)                       # o backup leva a config com ano_letivo = "2026"
    _gravar_config(amb, ano_letivo="2025", pasta_modelos="Y")
    backup.restaurar_backup(z, aplicar=True, so_dados=False)
    c = _config(amb)
    assert c["ano_letivo"] == "2025"                        # a escolha atual é mantida, não a do backup
    assert c["pasta_modelos"] is None                       # o resto da configuração foi restaurado
    _gravar_config(amb, pasta_modelos="Z")                  # sem escolha agora, mas o backup antigo tinha "2026"
    backup.restaurar_backup(z, aplicar=True, so_dados=False)
    assert "ano_letivo" not in _config(amb)


def test_conferir_extrai_sem_alterar_nada(amb):
    pasta25 = _ano_com_dados(amb, 2025)
    z = backup.criar_backup(ano=2025)
    (pasta25 / "alunos.json").write_text('[{"Nome": "ESTRAGADO"}]', encoding="utf-8")
    r = backup.restaurar_backup(z, aplicar=False, so_dados=True)
    assert r["aplicado"] is False and r["pasta_destino"] is None and r["ano"] == "2025"
    assert "ESTRAGADO" in (pasta25 / "alunos.json").read_text(encoding="utf-8")                 # nada mudou
    assert list(Path(r["pasta"]).rglob("alunos.json"))


# ───────────── dados fictícios ─────────────

def _cpf_valido(cpf: str) -> bool:
    d = [int(c) for c in cpf if c.isdigit()]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    v1 = (sum(x * w for x, w in zip(d[:9], range(10, 1, -1))) * 10 % 11) % 10
    v2 = (sum(x * w for x, w in zip(d[:10], range(11, 1, -1))) * 10 % 11) % 10
    return d[9] == v1 and d[10] == v2


def _ler(amb, ano, nome):
    return json.loads((amb / "dados" / str(ano) / nome).read_text(encoding="utf-8"))


def test_gera_os_arquivos_no_formato_do_sistema(amb):
    r = df.gerar_dados_ficticios(2025)
    assert r["ano"] == "2025" and r["turmas"] == 8 and r["alunos"] == 57 and r["funcionarios"] == 14 and r["backup"] is None
    pasta = amb / "dados" / "2025"
    assert sorted(p.name for p in pasta.iterdir()) == sorted(r["arquivos"])
    turmas = _ler(amb, 2025, "turmas.json")
    aluno = turmas["1º Ano Integral A"][0]
    assert {"N", "CGM", "Nome", "Data Nasc.", "Idade", "Sexo", "Situação", "Data Matricula"} <= set(aluno)
    assert [a["N"] for a in turmas["3º Ano A"]] == list(range(1, 9)) and "Infantil IV A" in turmas
    cadastro = _ler(amb, 2025, "alunos.json")[0]
    assert {"Nome", "CGM", "Data Nascimento", "Sexo", "CPF", "Mãe", "Responsável", "CEP", "Email Responsável"} <= set(cadastro)
    assert {a["CGM"] for a in _ler(amb, 2025, "alunos.json")} == {a["CGM"] for t in turmas.values() for a in t}   # os dois arquivos combinam
    assert (pasta / df.MARCADOR).exists() and df.pasta_e_ficticia(pasta) and not df.pasta_tem_dados_reais(pasta)


def test_os_dados_parecem_falsos_e_sao_seguros(amb):
    df.gerar_dados_ficticios(2025)
    cpfs = [a["CPF"] for a in _ler(amb, 2025, "alunos.json")] + [a["CPF Responsável"] for a in _ler(amb, 2025, "alunos.json")]
    cpfs += [f["cpf"] for f in _ler(amb, 2025, "funcionarios.json")] + list(_ler(amb, 2025, "pre_matricula.json")["cadastros"])
    assert len(cpfs) > 100 and not any(_cpf_valido(c) for c in cpfs)                       # nenhum CPF passa na verificação
    emails = [a["Email Responsável"] for a in _ler(amb, 2025, "alunos.json")] + [f["email"] for f in _ler(amb, 2025, "funcionarios.json")]
    emails += [c["email"] for c in _ler(amb, 2025, "pre_matricula.json")["cadastros"].values()]
    assert emails and all(e.endswith("@example.com") for e in emails)                      # domínio reservado: ninguém recebe
    telefones = [a["Celular Responsável"] for a in _ler(amb, 2025, "alunos.json")]
    assert all(re.fullmatch(r"\(00\) 00000-\d{4}", t) for t in telefones)
    nomes = [a["Nome"] for t in _ler(amb, 2025, "turmas.json").values() for a in t]
    assert len(nomes) == len(set(nomes))


def test_e_repetivel_e_muda_com_o_ano(amb):
    df.gerar_dados_ficticios(2025)
    primeiro = (amb / "dados" / "2025" / "turmas.json").read_bytes()
    df.gerar_dados_ficticios(2025)
    assert (amb / "dados" / "2025" / "turmas.json").read_bytes() == primeiro
    df.gerar_dados_ficticios(2024)
    assert (amb / "dados" / "2024" / "turmas.json").read_bytes() != primeiro


def test_vinculos_fictícios_cobrem_os_casos(amb):
    df.gerar_dados_ficticios(2025)
    v = _ler(amb, 2025, "funcionarios_matriculas.json")
    por_vinculo = {}
    for x in v:
        por_vinculo.setdefault(x["vinculo"], []).append(x)
    assert set(por_vinculo) == {"servidor", "terceirizado", "estagiario"} and len(v) == 14
    assert all(x["terceirizado"] and x["terceirizado_origem"] == "nao_consta_no_rh" and x["numcad"] is None for x in por_vinculo["terceirizado"])
    assert sorted({x["na_escola"] for x in por_vinculo["servidor"]}) == [False, True]          # um com holerite em outro local
    assert all(x["numcad"].startswith("9") for x in por_vinculo["servidor"])


def test_pre_matricula_ficticia_tem_todas_as_situacoes(amb):
    df.gerar_dados_ficticios(2025)
    pre = _ler(amb, 2025, "pre_matricula.json")
    situacoes = {a["situacao"] for lista in pre["turmas_intencao"].values() for a in lista}
    assert "Matriculado" in situacoes and "" in situacoes and any(s.startswith("Cancelado") for s in situacoes)
    assert all(a["cpf"] in pre["cadastros"] for lista in pre["turmas_intencao"].values() for a in lista)


def test_recusa_pasta_com_dados_reais_e_nao_escreve_nada(amb):
    pasta = amb / "dados" / "2026"
    antes = {p.name: p.read_bytes() for p in pasta.iterdir()}
    with pytest.raises(ValueError, match="já tem dados"):
        df.gerar_dados_ficticios(2026)
    assert {p.name: p.read_bytes() for p in pasta.iterdir()} == antes


def test_regenera_quando_a_pasta_so_tem_dados_ficticios(amb):
    df.gerar_dados_ficticios(2025)
    (amb / "dados" / "2025" / "alunos.json").write_text("[]", encoding="utf-8")
    df.gerar_dados_ficticios(2025)
    assert len(_ler(amb, 2025, "alunos.json")) == 57


def test_ano_invalido(amb):
    for ano in ("abc", "25", "1999", None):
        with pytest.raises(ValueError):
            df.gerar_dados_ficticios(ano)


def test_gera_com_backup_restauravel(amb):
    r = df.gerar_dados_ficticios(2025, com_backup=True)
    assert r["backup"].startswith("backup_") and backup.listar_backups()[0]["ano"] == "2025"
    (amb / "dados" / "2025" / "turmas.json").write_text("{}", encoding="utf-8")
    backup.restaurar_backup(paths.DADOS_BACKUP_DIR / r["backup"], aplicar=True, so_dados=True)
    assert "Infantil IV A" in _ler(amb, 2025, "turmas.json")


def test_cli(amb, capsys):
    assert df.main(["--ano", "2025"]) == 0 and "57 alunos" in capsys.readouterr().out
    assert df.main(["--ano", "2026"]) == 1 and "já tem dados" in capsys.readouterr().err


def test_as_telas_leem_os_dados_ficticios(amb, web):
    """O teste de fidelidade: se o formato estivesse errado, as telas do sistema não mostrariam nada."""
    df.gerar_dados_ficticios(2025)
    monkey_ano = paths.dados_ano_atual
    paths.dados_ano_atual = lambda: amb / "dados" / "2025"
    try:
        painel = web.get("/web/api/painel/resumo").get_json()
        valores = {c["label"]: c["valor"] for c in painel["principais"] + painel["secundarias"]}
        assert valores["Total de alunos"] == 54 and valores["Meninos"] + valores["Meninas"] == 54       # 57 menos 3 transferidos
        alunos = web.get("/web/api/alunos/lista").get_json()
        assert alunos["total"] == 57 and all(a["_turma"] != "—" for a in alunos["alunos"])
        func = web.get("/web/api/funcionarios/lista").get_json()
        assert len(func["funcionarios"]) == 14
        assert {c["label"]: c["valor"] for c in func["cartoes"]}["Terceirizados"] == 2
        assert sum(1 for f in func["funcionarios"] if f["terceirizado"]) == 2 and any(f["na_escola"] is False for f in func["funcionarios"])
        pre = web.get("/web/api/prematricula/lista")
        assert pre.status_code == 200 and pre.get_json()
        from src.automacao import avisos
        r = avisos.destinatarios_pais("matriculados")
        assert r["destinatarios"] and all(d["email"].endswith("@example.com") for d in r["destinatarios"])
    finally:
        paths.dados_ano_atual = monkey_ano


# ───────────── rotas ─────────────

def test_estado_inicial(web, amb):
    _ano_com_dados(amb, 2025)
    df.gerar_dados_ficticios(2024)
    backup.criar_backup(ano=2025)
    d = web.get(URL).get_json()
    assert (d["ativo"], d["proximo"], d["configurado"], d["automatico"], d["pendente_reinicio"]) == ("2026", "2026", "2026", False, False)
    assert d["fixado_por_ambiente"] is False and d["ano_do_calendario"] == str(ANO_CIVIL)
    linhas = {a["ano"]: a for a in d["anos"]}
    assert list(linhas) == ["2026", "2025", "2024"]
    assert linhas["2026"]["ativo"] is True and linhas["2026"]["arquivos"] == 2 and linhas["2024"]["ficticio"] is True
    assert linhas["2025"]["backups"] == 1 and linhas["2025"]["ficticio"] is False
    assert d["backups"][0]["ano"] == "2025" and d["backups"][0]["tamanho"]


def test_escolher_outro_ano_vale_na_hora(web, amb):
    r = web.post(URL, json={"ano": "2025"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["trocou"] is True and d["antigo"] == "2026"
    assert d["ativo"] == "2025" and d["proximo"] == "2025" and d["configurado"] == "2025" and d["pendente_reinicio"] is False
    assert "carregado" in d["mensagem"] and "reinici" not in d["mensagem"].lower() and "já usam os dados de 2025" in d["mensagem"]
    assert _config(amb)["ano_letivo"] == "2025"
    assert paths.ano_atual() == "2025" and paths.dados_ano_atual() == amb / "dados" / "2025"   # sem reiniciar nada
    assert web.get(URL).get_json()["ativo"] == "2025"


def test_voltar_ao_automatico(web, amb):
    web.post(URL, json={"ano": "2025"})
    d = web.post(URL, json={"automatico": True}).get_json()
    assert d["trocou"] is True and d["ativo"] == "2026" and d["automatico"] is True and d["configurado"] is None and d["proximo"] == "2026"
    assert "ano_letivo" in _config(amb) and _config(amb)["ano_letivo"] is None
    assert "carregado" in d["mensagem"] and "2026" in d["mensagem"]


def test_escolher_o_ano_que_ja_esta_em_uso(web):
    d = web.post(URL, json={"ano": "2026"}).get_json()
    assert d["trocou"] is False and d["pendente_reinicio"] is False and "já é o que está em uso" in d["mensagem"]


@pytest.mark.parametrize("corpo", [{}, {"ano": ""}, {"ano": "25"}, {"ano": "abcd"}, {"ano": "1999"}, {"ano": str(ANO_CIVIL + 5)}])
def test_ano_invalido_da_400_e_nao_grava(web, amb, corpo):
    antes = _config(amb)
    r = web.post(URL, json=corpo)
    assert r.status_code == 400 and r.get_json()["erro"]
    assert _config(amb) == antes


def test_ambiente_fixando_o_ano_recusa_a_troca(web, amb, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2023")
    antes = _config(amb)
    r = web.post(URL, json={"ano": "2025"})
    assert r.status_code == 409 and "AUTO_SERE_ANO_BASE=2023" in r.get_json()["erro"]
    assert _config(amb) == antes
    d = web.get(URL).get_json()
    assert d["fixado_por_ambiente"] is True and d["ativo"] == "2023"


def test_backup_pela_rota(web, amb):
    _ano_com_dados(amb, 2025)
    d = web.post(URL + "/backup", json={"ano": "2025"}).get_json()
    assert d["status"] == "ok" and "dados de 2025" in d["mensagem"] and d["backups"][0]["ano"] == "2025"
    d = web.post(URL + "/backup", json={}).get_json()                                              # padrão: o ano em uso
    assert "dados de 2026" in d["mensagem"] and d["backups"][0]["ano"] == "2026"


def test_backup_de_ano_sem_dados_ou_invalido(web):
    r = web.post(URL + "/backup", json={"ano": "2019"})
    assert r.status_code == 400 and "Não há dados do ano 2019" in r.get_json()["erro"]
    assert web.post(URL + "/backup", json={"ano": "x"}).status_code == 400


def _backup_de(web, amb, ano=2025):
    if ano != 2026:                                          # 2026 já tem os dados "reais" da fixture
        _ano_com_dados(amb, ano)
    web.post(URL + "/backup", json={"ano": str(ano)})
    return web.get(URL).get_json()["backups"][0]["nome"]


@pytest.mark.parametrize("nome", ["", "../../etc/passwd", "backup_x.zip/../../y.zip", "outro.zip", "backup_x.txt", "..\\backup_x.zip", None])
def test_restaurar_recusa_nome_de_backup_suspeito(web, nome):
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 400 and "Escolha um backup" in r.get_json()["erro"]


def test_restaurar_backup_que_nao_existe(web):
    r = web.post(URL + "/restaurar", json={"backup": "backup_2020-01-01_000000_000000.zip"})
    assert r.status_code == 404


def test_conferir_pela_rota_nao_altera_nada(web, amb):
    nome = _backup_de(web, amb)
    (amb / "dados" / "2025" / "alunos.json").write_text("[]", encoding="utf-8")
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": False})
    d = r.get_json()
    assert r.status_code == 200 and "Nada foi alterado" in d["mensagem"] and d["resultado"]["aplicado"] is False
    assert (amb / "dados" / "2025" / "alunos.json").read_text(encoding="utf-8") == "[]"


def test_restaurar_exige_confirmacao(web, amb):
    nome = _backup_de(web, amb)
    (amb / "dados" / "2025" / "alunos.json").write_text("[]", encoding="utf-8")
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True})
    assert r.status_code == 400 and "Confirme" in r.get_json()["erro"]
    assert (amb / "dados" / "2025" / "alunos.json").read_text(encoding="utf-8") == "[]"


def test_restaurar_os_dados_de_outro_ano(web, amb):
    nome = _backup_de(web, amb)
    (amb / "dados" / "2025" / "alunos.json").write_text("[]", encoding="utf-8")
    (amb / "dados" / "2026" / "alunos.json").write_text('[{"Nome": "TRABALHO DE 2026"}]', encoding="utf-8")
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    d = r.get_json()
    assert r.status_code == 200 and d["status"] == "ok" and d["resultado"]["ano"] == "2025"
    assert "Dados de 2025 restaurados" in d["mensagem"] and "não está em uso agora" in d["mensagem"]
    assert "ALUNO 2025" in (amb / "dados" / "2025" / "alunos.json").read_text(encoding="utf-8")
    assert "TRABALHO DE 2026" in (amb / "dados" / "2026" / "alunos.json").read_text(encoding="utf-8")
    assert d["resultado"]["backup_de_seguranca"]


def test_restaurar_o_ano_em_uso_com_automacao_rodando_e_recusado(web, amb):
    nome = _backup_de(web, amb, 2026)
    (amb / "dados" / "2026" / "alunos.json").write_text("[]", encoding="utf-8")
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["turmas"] = {"status": "executando"}
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 409 and "automação em execução" in r.get_json()["erro"]
    assert (amb / "dados" / "2026" / "alunos.json").read_text(encoding="utf-8") == "[]"
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["turmas"] = {"status": "concluido"}
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 200 and "Recarregue as telas" in r.get_json()["mensagem"]
    assert "REAL DE 2026" in (amb / "dados" / "2026" / "alunos.json").read_text(encoding="utf-8")


def test_restaurar_outro_ano_com_automacao_rodando_pode(web, amb):
    nome = _backup_de(web, amb, 2025)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["alunos"] = {"status": "executando"}
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 200                                # a automação trabalha em 2026: 2025 está livre


def test_backup_adulterado_e_recusado(web, amb):
    nome = _backup_de(web, amb)
    caminho = paths.DADOS_BACKUP_DIR / nome
    with zipfile.ZipFile(caminho) as z:
        itens = {n: z.read(n) for n in z.namelist()}
    itens["dados_ano/alunos.json"] = b'[{"Nome": "ADULTERADO"}]'
    with zipfile.ZipFile(caminho, "w") as z:
        for n, c in itens.items():
            z.writestr(n, c)
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 400 and "Backup inválido" in r.get_json()["erro"]
    assert "ADULTERADO" not in (amb / "dados" / "2025" / "alunos.json").read_text(encoding="utf-8")


def test_dados_ficticios_pela_rota(web, amb):
    r = web.post(URL + "/dados-ficticios", json={"ano": "2025"})
    d = r.get_json()
    assert r.status_code == 200 and "57 alunos" in d["mensagem"] and d["resultado"]["backup"]
    linha = next(a for a in d["anos"] if a["ano"] == "2025")
    assert linha["ficticio"] is True and linha["backups"] == 1
    r = web.post(URL + "/dados-ficticios", json={"ano": "2025", "backup": False})                 # regenerar é permitido
    assert r.status_code == 200 and r.get_json()["resultado"]["backup"] is None


def test_dados_ficticios_nunca_no_ano_em_uso_nem_no_proximo(web, amb):
    r = web.post(URL + "/dados-ficticios", json={"ano": "2026"})
    assert r.status_code == 400 and "em uso" in r.get_json()["erro"]
    web.post(URL, json={"ano": "2027"})                                                           # 2027 será o próximo início
    r = web.post(URL + "/dados-ficticios", json={"ano": "2027"})
    assert r.status_code == 400 and "em uso" in r.get_json()["erro"]
    assert not (amb / "dados" / "2027" / df.MARCADOR).exists()


def test_dados_ficticios_recusa_pasta_com_dados_reais_e_ano_invalido(web, amb):
    _ano_com_dados(amb, 2025)
    r = web.post(URL + "/dados-ficticios", json={"ano": "2025"})
    assert r.status_code == 400 and "já tem dados" in r.get_json()["erro"]
    assert "ALUNO 2025" in (amb / "dados" / "2025" / "alunos.json").read_text(encoding="utf-8")
    assert web.post(URL + "/dados-ficticios", json={"ano": "x"}).status_code == 400


def test_voltado_a_2025_nao_regenera_dados_ficticios(web, amb):
    """Em 2025 (ano anterior) o programa é só de consulta: nem os dados fictícios podem ser refeitos ali."""
    web.post(URL + "/dados-ficticios", json={"ano": "2025"})
    web.post(URL, json={"ano": "2025"})
    assert paths.ano_atual() == "2025" and paths.somente_consulta() is True
    r = web.post(URL + "/dados-ficticios", json={"ano": "2025", "backup": False})
    assert r.status_code == 403 and r.get_json()["somente_consulta"] is True


# ───────────── a jornada completa do usuário ─────────────

def test_jornada_completa_2025(web, amb):
    """Dados de teste de 2025 → ver 2025 (só consulta) → voltar a 2026 → restaurar 2025 → rever 2025. Tudo SEM reiniciar."""
    # 1) dados fictícios de 2025 (+ backup) enquanto o programa está em 2026
    d = web.post(URL + "/dados-ficticios", json={"ano": "2025"}).get_json()
    assert d["resultado"]["alunos"] == 57
    # 2) escolhe 2025: a tela passa a mostrar o 2025 na hora, mas é só consulta
    assert web.post(URL, json={"ano": "2025"}).status_code == 200
    assert paths.ano_atual() == "2025" and paths.dados_ano_atual() == amb / "dados" / "2025" and paths.somente_consulta()
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 57
    nome = web.get(URL).get_json()["backups"][0]["nome"]
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 403                                                    # em consulta não se restaura nada
    # 3) volta a 2026 (trocar de ano é permitido em consulta)
    assert web.post(URL, json={"ano": "2026"}).status_code == 200
    assert paths.ano_atual() == "2026" and not paths.somente_consulta()
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 1               # os dados de 2026 (1 aluno nesta fixture)
    # 4) 2025 é estragado e restaurado a partir de 2026 (outro ano: permitido)
    (amb / "dados" / "2025" / "alunos.json").write_text("[]", encoding="utf-8")
    (amb / "dados" / "2025" / "turmas.json").write_text("{}", encoding="utf-8")
    r = web.post(URL + "/restaurar", json={"backup": nome, "aplicar": True, "confirmar": True})
    assert r.status_code == 200 and "não está em uso agora" in r.get_json()["mensagem"]
    # 5) os dados reais de 2026 ficaram intactos o tempo todo; e ao rever 2025 os dados voltaram
    assert "REAL DE 2026" in (amb / "dados" / "2026" / "alunos.json").read_text(encoding="utf-8")
    web.post(URL, json={"ano": "2025"})
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 57


# ───────────── tela ─────────────

def test_tela_tem_o_item_e_o_formulario():
    raiz = Path(__file__).resolve().parent.parent
    html = (raiz / "src/web/templates/configuracoes.html").read_text(encoding="utf-8")
    js = (raiz / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'data-config="ano_letivo"' in html
    assert "conectarFormAnoLetivo" in js and 'row.dataset.config === "ano_letivo"' in js
    for rota in ('"/configuracoes/ano-letivo"', "/backup", "/restaurar", "/dados-ficticios"):
        assert rota in js
    assert "window.confirm" in js and "trocarAnoLetivo" in js and "PARAR_AUTO_SERE" not in js

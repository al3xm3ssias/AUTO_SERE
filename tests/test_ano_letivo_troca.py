"""Trocar o ano letivo SEM reiniciar: os módulos que fixam dados/<ano> são recarregados (src.comum.ano_letivo)."""
import ast
import importlib
import json
import pathlib
import sys
import threading

import pytest

from src.comum import ano_letivo, configuracao, escola, paths, registro_scripts as reg
from src.web.api import rotas
from src.web.app import create_app

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FIXOS = set(ano_letivo.MODULOS_COM_ANO_FIXO)
DEPENDEM = set(ano_letivo.MODULOS_QUE_DEPENDEM)
URL = "/web/api/configuracoes/ano-letivo"


# ───────────── guarda de completude: o código novo não pode escapar das listas ─────────────

def _nome_do_modulo(caminho: pathlib.Path) -> str:
    nome = ".".join(caminho.relative_to(RAIZ).with_suffix("").parts)
    return nome[:-9] if nome.endswith(".__init__") else nome


def _chamadas_ao_ano_na_importacao(arvore) -> list[int]:
    """Linhas com dados_ano_atual()/ano_atual() avaliadas na importação (fora do corpo de função)."""
    alvo = {"dados_ano_atual", "ano_atual", "ano_do_proximo_inicio"}
    achados = []

    def nome(n):
        f = n.func
        return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)

    class V(ast.NodeVisitor):
        def __init__(self): self.dentro = 0
        def _func(self, node):
            for d in [*node.args.defaults, *[x for x in node.args.kw_defaults if x], *node.decorator_list]:
                self.visit(d)                                        # padrões e decoradores rodam na DEFINIÇÃO
            self.dentro += 1
            for st in node.body:
                self.visit(st)
            self.dentro -= 1
        visit_FunctionDef = _func
        visit_AsyncFunctionDef = _func
        def visit_Lambda(self, node): pass
        def visit_Call(self, node):
            if nome(node) in alvo and not self.dentro:
                achados.append(node.lineno)
            self.generic_visit(node)
    V().visit(arvore)
    return achados


def test_a_lista_de_modulos_que_fixam_o_ano_esta_completa():
    """Se alguém criar um módulo que calcula dados/<ano> na importação, este teste obriga a pô-lo em MODULOS_COM_ANO_FIXO."""
    achados = set()
    for arq in (RAIZ / "src").rglob("*.py"):
        if _chamadas_ao_ano_na_importacao(ast.parse(arq.read_text(encoding="utf-8"))):
            achados.add(_nome_do_modulo(arq))
    assert achados == FIXOS, (f"faltam na lista: {sorted(achados - FIXOS)}; sobram na lista: {sorted(FIXOS - achados)}")


def _imports_no_carregamento(arq: pathlib.Path, nome: str, conhecidos: set[str]) -> set[str]:
    """Módulos src.* importados logo ao carregar (imports dentro de funções são tardios e não contam)."""
    pacote = nome if arq.name == "__init__.py" else nome.rpartition(".")[0]
    achados: set[str] = set()

    def resolver(no):
        if isinstance(no, ast.Import):
            return {a.name for a in no.names}
        base = pacote.split(".")
        base = base[:len(base) - (no.level - 1)] if no.level else []
        alvo = ".".join(base + ([no.module] if no.module else [])) if no.level else (no.module or "")
        return {alvo, *(f"{alvo}.{a.name}" for a in no.names)}

    def visita(corpo):
        for st in corpo:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                achados.update(m for m in resolver(st) if m in conhecidos)
            elif isinstance(st, (ast.If, ast.Try, ast.With)):
                for campo in ("body", "orelse", "finalbody"):
                    visita(getattr(st, campo, []))
                for h in getattr(st, "handlers", []):
                    visita(h.body)
    visita(ast.parse(arq.read_text(encoding="utf-8")).body)
    return achados


def test_ninguem_fora_das_listas_importa_um_modulo_que_fixa_o_ano_no_carregamento():
    """Quem importa um desses módulos logo ao carregar guardaria a cópia velha: precisa estar em MODULOS_QUE_DEPENDEM."""
    arquivos = {_nome_do_modulo(a): a for a in (RAIZ / "src").rglob("*.py")}
    conhecidos = set(arquivos)
    grafo = {n: _imports_no_carregamento(a, n, conhecidos) for n, a in arquivos.items()}
    afetados = set(FIXOS)
    while True:
        novos = {m for m, deps in grafo.items() if m not in afetados and deps & afetados}
        if not novos:
            break
        afetados |= novos
    extras = afetados - FIXOS
    # test_gerar_pastas é um arquivo de teste solto dentro de src/automacao (não é carregado pelo programa)
    assert extras - {"src.automacao.test_gerar_pastas"} == DEPENDEM, sorted(extras)
    # a camada web e a CLI nunca podem estar nesse grupo: elas não são recarregadas
    for camada in ("src.web.api.rotas", "src.web.app", "src.comum.registro_scripts", "src.comum.cli", "src.comum.configuracao", "src.comum.paths"):
        assert camada not in afetados, f"{camada} importa um módulo que fixa o ano logo ao carregar"


def test_todos_os_modulos_das_listas_existem_e_importam():
    for nome in (*FIXOS, *DEPENDEM):
        assert importlib.import_module(nome).__name__ == nome


# ───────────── ambiente temporário ─────────────

@pytest.fixture()
def amb(tmp_path, monkeypatch):
    dados = tmp_path / "dados"
    (dados / "calendario").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(paths, "DADOS_DIR", dados)
    monkeypatch.setattr(paths, "DADOS_BACKUP_DIR", dados / "backup")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config" / "config_usuario.json")
    monkeypatch.setattr(paths, "ano_do_calendario", lambda: 2026)
    monkeypatch.delenv("AUTO_SERE_ANO_BASE", raising=False)
    monkeypatch.setattr(escola, "nome", lambda: "Escola Municipal Teste")
    monkeypatch.setattr(rotas, "_dados_dir", lambda: paths.dados_ano_atual())
    (tmp_path / "config" / "config_usuario.json").write_text(json.dumps({"ano_letivo": "2026"}), encoding="utf-8")
    paths.recarregar_ano_do_processo()
    assert paths.ano_atual() == "2026"
    for ano in ("2025", "2026"):
        (dados / ano).mkdir()
        (dados / ano / "turmas.json").write_text(json.dumps({f"T{ano}": []}), encoding="utf-8")
    # os módulos são importados já com o ano e as pastas deste teste
    for nome in (*FIXOS, *DEPENDEM):
        sys.modules.pop(nome, None)
        pai, _, filho = nome.rpartition(".")
        if hasattr(sys.modules.get(pai), filho):
            delattr(sys.modules[pai], filho)
    for nome in (*FIXOS, *DEPENDEM):
        importlib.import_module(nome)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES.clear()
    yield tmp_path
    paths.recarregar_ano_do_processo()


def _config(amb):
    return json.loads((amb / "config" / "config_usuario.json").read_text(encoding="utf-8"))


def _caminhos_do_modulo(modulo, dados_dir):
    """Valores do módulo que são caminhos dentro de dados/ (o que os scripts usam para ler/gravar)."""
    achados = {}
    for chave, valor in vars(modulo).items():
        if chave.startswith("__"):
            continue
        if isinstance(valor, (str, pathlib.PurePath)) and str(dados_dir) in str(valor):
            achados[chave] = str(valor)
    return achados


# ───────────── a troca recarrega os módulos ─────────────

def test_trocar_ano_recarrega_os_18_modulos(amb):
    dados = amb / "dados"
    antes = {n: sys.modules[n] for n in (*FIXOS, *DEPENDEM)}
    for n in FIXOS:                                          # estado de partida: todos em 2026
        caminhos = _caminhos_do_modulo(antes[n], dados)
        assert caminhos and all(str(dados / "2026") in v for v in caminhos.values()), (n, caminhos)
    r = ano_letivo.trocar_ano("2025")
    assert r == {"antigo": "2026", "novo": "2025", "trocou": True, "modulos": 19}
    assert paths.ano_atual() == "2025" and _config(amb)["ano_letivo"] == "2025"
    for n in (*FIXOS, *DEPENDEM):
        assert sys.modules[n] is not antes[n], f"{n} não foi recarregado"
    for n in FIXOS:
        caminhos = _caminhos_do_modulo(sys.modules[n], dados)
        assert caminhos, n
        assert all(str(dados / "2025") in v and str(dados / "2026") not in v for v in caminhos.values()), (n, caminhos)


def test_nao_sobra_nenhum_valor_do_ano_antigo(amb):
    """Varredura geral: depois da troca nenhum atributo dos 18 módulos aponta para dados/2026."""
    ano_letivo.trocar_ano("2025")
    velhos = {n: [k for k, v in vars(sys.modules[n]).items() if not k.startswith("__") and isinstance(v, (str, pathlib.PurePath))
                  and str(amb / "dados" / "2026") in str(v)] for n in FIXOS}
    assert {n: v for n, v in velhos.items() if v} == {}


def test_importar_pelo_pacote_devolve_o_modulo_novo(amb):
    """O pacote pai guarda uma referência ao submódulo: se ela não fosse apagada, 'from pacote import modulo' voltaria o velho."""
    from src.automacao import turmas as antiga
    ano_letivo.trocar_ano("2025")
    from src.automacao import turmas as nova
    import src.automacao.turmas as via_import
    assert nova is not antiga and nova is sys.modules["src.automacao.turmas"] and via_import is nova
    assert nova._DADOS == amb / "dados" / "2025" and nova.TURMAS_JSON == amb / "dados" / "2025" / "turmas.json"
    from src.automacao.turmas import TURMAS_JSON                       # import "tardio" como o do registro de automações
    assert TURMAS_JSON == amb / "dados" / "2025" / "turmas.json"
    assert importlib.import_module("src.automacao.turmas") is nova


def test_dependente_tambem_e_recarregado(amb):
    antes = sys.modules["src.automacao.rematricula_sere"]
    classe_antiga = antes.ErroReiniciarNavegador
    ano_letivo.trocar_ano("2025")
    novo = sys.modules["src.automacao.rematricula_sere"]
    persistencia = sys.modules["src.automacao.rematricula_persistencia"]
    assert novo is not antes
    # a exceção que rematricula_sere captura tem de ser a MESMA que a persistência lança (senão o `except` não casa)
    assert novo.ErroReiniciarNavegador is persistencia.ErroReiniciarNavegador and novo.ErroReiniciarNavegador is not classe_antiga
    assert persistencia._DADOS == amb / "dados" / "2025"


def test_ida_e_volta(amb):
    for ano in ("2025", "2026", "2025", "2026"):
        ano_letivo.trocar_ano(ano)
        assert paths.ano_atual() == ano
        assert sys.modules["src.automacao.alunos"]._DADOS == amb / "dados" / ano


def test_modulo_que_nao_estava_carregado_continua_sem_estar(amb):
    ano_letivo.descarregar(["src.automacao.sisreg"])
    assert "src.automacao.sisreg" not in sys.modules
    r = ano_letivo.trocar_ano("2025")
    assert r["modulos"] == 18 and "src.automacao.sisreg" not in sys.modules      # não gasta tempo importando o que ninguém usou
    sisreg = importlib.import_module("src.automacao.sisreg")                      # quando for usado, já vem no ano novo
    assert str(amb / "dados" / "2025") in str(sisreg._DADOS)


def test_mesmo_ano_nao_recarrega_nada(amb):
    antes = {n: sys.modules[n] for n in FIXOS}
    r = ano_letivo.trocar_ano("2026")
    assert r["trocou"] is False and r["modulos"] == 0 and all(sys.modules[n] is antes[n] for n in FIXOS)


def test_automatico_volta_ao_ano_do_calendario(amb):
    ano_letivo.trocar_ano("2025")
    r = ano_letivo.trocar_ano(None)
    assert r["novo"] == "2026" and r["trocou"] is True and paths.ano_atual() == "2026"
    assert _config(amb)["ano_letivo"] is None and paths.ano_configurado() is None


def test_ano_invalido_nao_muda_nada(amb):
    antes = {n: sys.modules[n] for n in FIXOS}
    cfg = _config(amb)
    for ruim in ("abc", "25", "1999", ""):
        with pytest.raises(ValueError):
            ano_letivo.trocar_ano(ruim)
    assert paths.ano_atual() == "2026" and _config(amb) == cfg and all(sys.modules[n] is antes[n] for n in FIXOS)


def test_ambiente_fixando_o_ano_recusa(amb, monkeypatch):
    monkeypatch.setenv("AUTO_SERE_ANO_BASE", "2024")
    cfg = _config(amb)
    with pytest.raises(ano_letivo.TrocaDeAnoErro, match="AUTO_SERE_ANO_BASE"):
        ano_letivo.trocar_ano("2025")
    assert _config(amb) == cfg


def test_falha_ao_carregar_desfaz_tudo(amb, monkeypatch):
    """Se um módulo não importar no ano novo, o ano, a configuração e os módulos voltam como estavam."""
    original = importlib.import_module
    estado = {"quebrou": False}

    def import_com_defeito(nome, *a, **k):
        if nome == "src.automacao.sisreg" and not estado["quebrou"]:
            estado["quebrou"] = True
            raise RuntimeError("arquivo corrompido")
        return original(nome, *a, **k)
    monkeypatch.setattr(ano_letivo.importlib, "import_module", import_com_defeito)
    with pytest.raises(ano_letivo.TrocaDeAnoErro, match=r"arquivo corrompido.*O ano 2026 foi mantido"):
        ano_letivo.trocar_ano("2025")
    assert paths.ano_atual() == "2026" and _config(amb)["ano_letivo"] == "2026"
    for n in FIXOS:                                           # e nada ficou apontando para 2025
        assert all(str(amb / "dados" / "2026") in v for v in _caminhos_do_modulo(sys.modules[n], amb / "dados").values()), n


def test_duas_trocas_ao_mesmo_tempo_terminam_consistentes(amb):
    erros = []

    def trabalhar(anos):
        try:
            for a in anos:
                ano_letivo.trocar_ano(a)
        except Exception as exc:                              # noqa: BLE001
            erros.append(exc)
    ts = [threading.Thread(target=trabalhar, args=(["2025", "2026", "2025", "2026", "2025"],)),
          threading.Thread(target=trabalhar, args=(["2026", "2025", "2026", "2025", "2026"],))]
    [t.start() for t in ts]
    [t.join(timeout=120) for t in ts]
    assert not erros
    ano = paths.ano_atual()
    assert _config(amb)["ano_letivo"] == ano
    for n in FIXOS:
        assert all(str(amb / "dados" / ano) in v for v in _caminhos_do_modulo(sys.modules[n], amb / "dados").values()), n


# ───────────── a rota ─────────────

@pytest.fixture()
def web(amb):
    return create_app().test_client()


def test_rota_troca_e_a_tela_ja_le_o_ano_novo(web, amb):
    (amb / "dados" / "2025" / "alunos.json").write_text(json.dumps([{"Nome": "ALUNO DE 2025"}]), encoding="utf-8")
    (amb / "dados" / "2026" / "alunos.json").write_text(json.dumps([{"Nome": "ALUNO DE 2026"}, {"Nome": "OUTRO DE 2026"}]), encoding="utf-8")
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 2
    d = web.post(URL, json={"ano": "2025"}).get_json()
    assert d["trocou"] is True and d["ativo"] == "2025" and d["somente_consulta"] is True
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 1                # outra resposta, sem reiniciar
    web.post(URL, json={"ano": "2026"})
    assert web.get("/web/api/alunos/lista").get_json()["total"] == 2


def test_rota_troca_de_ano_troca_tambem_o_calendario(web, amb):
    """O calendário é por ano letivo: voltando para 2025 aparece o de 2025 (só leitura); voltando a 2026, o de 2026."""
    cal = "/web/api/calendario"
    ev = web.post(f"{cal}/eventos", json={"nome": "Recesso 2026", "tipo": "recesso", "inicio": "2026-10-13"})
    assert ev.status_code == 201 and (amb / "dados" / "2026" / "calendario.json").exists()
    (amb / "dados" / "2025" / "calendario.json").write_text(json.dumps({"eventos": [
        {"id": "z", "nome": "Recesso 2025", "tipo": "recesso", "inicio": "2025-10-14", "fim": "2025-10-14"}], "periodos": []}), encoding="utf-8")

    assert [e["nome"] for e in web.get(f"{cal}/dados").get_json()["eventos"]] == ["Recesso 2026"]
    assert web.post(URL, json={"ano": "2025"}).get_json()["ativo"] == "2025"
    d = web.get(f"{cal}/dados").get_json()
    assert d["ano_letivo"] == "2025" and [e["nome"] for e in d["eventos"]] == ["Recesso 2025"]
    # ano anterior é só consulta: o servidor recusa cadastrar e apagar no calendário
    assert web.post(f"{cal}/eventos", json={"nome": "X", "tipo": "recesso", "inicio": "2025-11-03"}).status_code == 403
    assert web.delete(f"{cal}/eventos/z").status_code == 403
    assert [e["nome"] for e in web.get(f"{cal}/dados").get_json()["eventos"]] == ["Recesso 2025"]
    web.post(URL, json={"ano": "2026"})
    assert [e["nome"] for e in web.get(f"{cal}/dados").get_json()["eventos"]] == ["Recesso 2026"]


def test_rota_a_automacao_usa_o_ano_novo(web, amb):
    """O ponto que importa para quem executa: a automação, importada pelo registro, grava no ano que a tela mostra."""
    web.post(URL, json={"ano": "2025"})
    modulo = importlib.import_module("src.automacao.turmas")                         # como o registro faz, na hora do uso
    assert modulo.TURMAS_JSON == amb / "dados" / "2025" / "turmas.json"
    plano = reg.obter("turmas").planejar(reg.opcoes_vazias() if hasattr(reg, "opcoes_vazias") else __import__("src.comum.opcoes_execucao", fromlist=["Opcoes"]).Opcoes(), {}, {}, {})
    assert plano.funcao.__module__ == "src.automacao.turmas" and sys.modules[plano.funcao.__module__] is modulo
    assert plano.funcao.__globals__["TURMAS_JSON"] == amb / "dados" / "2025" / "turmas.json"


def test_rota_recusa_com_automacao_rodando_e_nada_muda(web, amb):
    antes = {n: sys.modules[n] for n in FIXOS}
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["alunos"] = {"status": "executando"}
    r = web.post(URL, json={"ano": "2025"})
    assert r.status_code == 409 and "automação em execução" in r.get_json()["erro"] and "2026" in r.get_json()["erro"]
    assert paths.ano_atual() == "2026" and _config(amb)["ano_letivo"] == "2026" and all(sys.modules[n] is antes[n] for n in FIXOS)
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["alunos"] = {"status": "concluido"}
    assert web.post(URL, json={"ano": "2025"}).status_code == 200


def test_rota_valida_o_ano_antes_de_olhar_as_automacoes(web):
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["x"] = {"status": "executando"}
    assert web.post(URL, json={"ano": "abc"}).status_code == 400


def test_rota_limpa_o_que_a_tela_guardava_do_ano_anterior(web):
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["turmas"] = {"status": "concluido", "resultado": {"x": 1}, "logs": ["do ano passado"]}
        rotas._EVENTOS_WIZARD.append({"t": 1, "passo": "turmas", "nivel": "info", "texto": "velho"})
    web.post(URL, json={"ano": "2025"})
    assert "turmas" not in rotas._EXECUCOES and rotas._EVENTOS_WIZARD == []
    assert web.get("/web/api/automacoes/turmas/status").get_json()["status"] != "concluido"


def test_rota_mesmo_ano_nao_limpa_nem_recarrega(web):
    with rotas._EXECUCOES_LOCK:
        rotas._EXECUCOES["turmas"] = {"status": "concluido", "logs": ["fica"]}
    d = web.post(URL, json={"ano": "2026"}).get_json()
    assert d["trocou"] is False and "turmas" in rotas._EXECUCOES


def test_rota_erro_ao_carregar_vira_500_com_motivo(web, monkeypatch):
    def quebra(novo=None):
        raise ano_letivo.TrocaDeAnoErro("Não consegui carregar o ano 2025 (RuntimeError: x). O ano 2026 foi mantido.")
    monkeypatch.setattr(ano_letivo, "trocar_ano", quebra)
    r = web.post(URL, json={"ano": "2025"})
    assert r.status_code == 500 and "O ano 2026 foi mantido" in r.get_json()["erro"]


def test_rota_automatico(web):
    web.post(URL, json={"ano": "2025"})
    d = web.post(URL, json={"automatico": True}).get_json()
    assert d["trocou"] is True and d["ativo"] == "2026" and d["automatico"] is True and d["somente_consulta"] is False


# ───────────── prova de ponta a ponta: o que as automações GRAVAM vai para o ano certo ─────────────

def test_funcao_com_caminho_padrao_grava_no_ano_novo(amb):
    """
    salvar_resultados() tem os caminhos como VALOR PADRÃO (fixados quando a função é definida). Sem recarregar o módulo
    ela continuaria gravando em dados/2026 mesmo com o programa em 2025: é exatamente o defeito que a troca evita.
    """
    antiga = sys.modules["src.automacao.rematricula_persistencia"]
    ano_letivo.trocar_ano("2025")
    nova = importlib.import_module("src.automacao.rematricula_persistencia")
    nova.salvar_resultados([{"nome": "NOVO"}], [], [])                         # sem passar caminho nenhum
    assert (amb / "dados" / "2025" / "rematriculas_sucesso.json").exists()
    assert not (amb / "dados" / "2026" / "rematriculas_sucesso.json").exists()
    assert json.loads((amb / "dados" / "2025" / "rematriculas_sucesso.json").read_text(encoding="utf-8")) == [{"nome": "NOVO"}]
    # prova de que o módulo antigo (sem a troca) gravaria no ano errado
    antiga.salvar_resultados([{"nome": "VELHO"}], [], [])
    assert (amb / "dados" / "2026" / "rematriculas_sucesso.json").exists()

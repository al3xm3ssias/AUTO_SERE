"""Telas de dados no Chromium: Encaminhamentos do SUS, Alunos fora do raio, Funcionários, Pré-matrícula, Transferidos."""
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import rotas  # noqa: E402
from src.web.app import create_app  # noqa: E402

playwright_sync = pytest.importorskip("playwright.sync_api")


def _gravar(pasta, nome, conteudo):
    (pasta / nome).write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def pagina(tmp_path, monkeypatch):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    _gravar(tmp_path, "turmas.json", {
        "5º Ano A": [{"CGM": "111", "Nome": "João da Silva", "Situação": "Matriculado"}],
        "3º Ano B": [{"CGM": "222", "Nome": "Maria Conceição", "Situação": "Matriculado"}]})
    _gravar(tmp_path, "alunos_encaminhamento.json", [
        {"nome": "João da Silva", "cgm": "111", "cpf": "11111111111", "encaminhamentos": [
            {"data_solicitacao": "01/03/2026", "procedimento": "Oftalmologia", "data_nascimento": "x", "posicao_fila": "12"},
            {"data_solicitacao": "05/04/2026", "procedimento": "Fonoaudiologia", "data_nascimento": "x", "posicao_fila": "3"}]},
        {"nome": "Maria Conceição", "cgm": "222", "cpf": "22222222222", "encaminhamentos": [
            {"data_solicitacao": "10/02/2026", "procedimento": "Cardiologia <b>urgente</b>", "data_nascimento": "x", "posicao_fila": "8"}]},
        {"nome": "Sem CPF", "cpf": "", "encaminhamentos": [], "erro": "CPF inválido"}])
    _gravar(tmp_path, "alunos_fora_raio.json", {
        "metadados": {"raio_km": 2.0, "total_alunos_processados": 50, "data_analise": "2026-10-01 10:00:00",
                      "cep_escola": "84010-000", "coordenadas_escola": {"latitude": -25.05, "longitude": -50.15}},
        "alunos": [{"nome": "Maria Conceição", "cgm": "222", "cep": "84000000", "distancia_km": 2.5},
                   {"nome": "João da Silva", "cgm": "111", "cep": "84010000", "distancia_km": 7.1}]})
    _gravar(tmp_path, "documentos-alunos-pc.json", [
        {"CGM": "111", "Nome": "João da Silva", "Documentos": ["Comprovante de residencia.pdf"]},
        {"CGM": "222", "Nome": "Maria Conceição", "Documentos": ["RG.pdf"]}])
    _gravar(tmp_path, "funcionarios.json", [
        {"nome": "Zélia Souza", "cpf": "11122233344", "funcao": "Docente", "email": "z@x.com", "curso_superior": "Pedagogia", "turmas": [{"descricao": "- 5º A"}]},
        {"nome": "Ana Lima", "cpf": "55566677788", "funcao": "Auxiliar/Assistente Educacional", "email": "", "curso_superior": "", "turmas": []}])
    _gravar(tmp_path, "funcionarios_completo.json", [
        {"cpf": "11122233344", "nome_completo": "ZÉLIA DE SOUZA", "telefone": "42999998888", "sexo": "F", "escolaridade": "Superior", "rg": "123456", "bairro": "Centro"}])
    _gravar(tmp_path, "transferidos.json", {
        "111": {"nome": "João da Silva", "turma": "5º Ano A",
                "guia": {"emitido_em": "2026-03-01T10:00:00", "assinado_secretario": "2026-03-02T10:00:00", "assinado_diretor": "2026-03-03T10:00:00"},
                "historico": {"emitido_em": "2026-03-01T10:00:00", "assinado_secretario": "2026-03-02T10:00:00", "assinado_diretor": "2026-03-03T10:00:00"},
                "parecer": {"digitalizado_em": "2026-03-04T10:00:00"}},
        "222": {"nome": "Maria Conceição", "turma": "3º Ano B", "guia": {"emitido_em": "2026-03-01T10:00:00"}, "historico": {}, "parecer": {}},
        "333": {"nome": "Pedro Alves", "turma": "1º Ano C", "guia": {}, "historico": {}, "parecer": {}}})

    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with playwright_sync.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium indisponível: {exc}")
        pg = nav.new_page(accept_downloads=True)
        pg.goto(f"http://127.0.0.1:{srv.server_port}/web")
        yield pg
        nav.close()
    srv.shutdown()


_PRONTO = {"fora-do-raio": "#fora-tbody tr", "encaminhamentos": "#encam-list .encam-card", "funcionarios": "#func-tbody tr",
           "prematricula": "#pm-tbody tr", "transferidos": "#transf-tbody tr"}


def _abrir(pg, view):
    pg.click(f'.nav-item[data-view="{view}"]')
    pg.wait_for_selector(_PRONTO.get(view, f"#tbody-{view} td:not([colspan])"))


def _total(pg, view):
    return pg.inner_text(f"#view-{view} .js-total")


def _cards(pg, view):
    return {
        e.query_selector(".stat-lbl").text_content().strip().lower(): e.query_selector(".stat-val").text_content().strip()
        for e in pg.query_selector_all(f"#cartoes-{view} .stat-card")
    }


def test_encaminhamentos_cards_grafico_filtros_e_busca(pagina):
    pg = pagina
    _abrir(pg, "encaminhamentos")
    cards = _cards(pg, "encaminhamentos")
    assert cards["alunos pesquisados"] == "3" and cards["com encaminhamentos"] == "2"
    assert cards["total procedimentos"] == "3" and cards["cpf inválido/erro"] == "1"
    assert pg.locator("#grafico-encaminhamentos .hbar").count() == 3
    assert pg.locator("#encam-list .encam-card").count() == 3                          # inclui o aluno com CPF inválido
    assert "Cardiologia <b>urgente</b>" in pg.inner_text("#encam-list")                # texto literal, sem virar HTML
    assert pg.locator("#encam-list b").count() == 0
    assert "5º Ano A" in pg.inner_text("#encam-list .encam-card:first-child .encam-cpf")

    pg.click('#sec-encaminhamentos [data-ef="com"]')
    assert pg.locator("#encam-list .encam-card").count() == 2
    pg.click('#sec-encaminhamentos [data-ef="sem-cpf"]')
    assert pg.locator("#encam-list .encam-card").count() == 1 and "CPF inválido" in pg.inner_text("#encam-list .encam-erro")
    pg.click('#sec-encaminhamentos [data-ef="all"]')
    pg.fill("#enc-q", "OFTALMO")                                                       # sem diferenciar caixa
    assert pg.locator("#encam-list .encam-card").count() == 1
    pg.fill("#enc-q", "conceicao")                                                     # sem acento acha "Conceição"
    assert pg.locator("#encam-list .encam-card").count() == 1
    pg.fill("#enc-q", "zzz")
    assert "Nenhum resultado" in pg.inner_text("#encam-list")


def test_atualizar_dados_abre_a_automacao_sus(pagina):
    pg = pagina
    _abrir(pg, "encaminhamentos")
    pg.click("#sec-encaminhamentos .js-atualizar")
    pg.wait_for_selector("#sec-automacoes.active")


def test_fora_do_raio_cards_mapa_tabela_ordenavel_e_filtros(pagina):
    pg = pagina
    _abrir(pg, "fora-do-raio")
    cards = _cards(pg, "fora-do-raio")
    assert cards["fora do raio"] == "2" and cards["processados"] == "50"
    assert cards["com comp. endereço"] == "1" and cards["sem comp. endereço"] == "1"
    assert cards["máx. distância"] == "7,10 km" and cards["cep da escola"] == "84010-000"
    assert "marker=-25.05%2C-50.15" in pg.get_attribute("#mapa-fora-do-raio iframe", "src")
    assert pg.locator("#fora-tbody .dist-bar").count() == 2                            # barrinha de distância

    linhas = pg.locator("#fora-tbody tr").all_inner_texts()                           # mais distante primeiro
    assert linhas[0].startswith("João da Silva") and "7,10 km" in linhas[0] and "Sim — 1 doc(s)" in linhas[0]
    assert pg.locator("#fora-tbody tr:first-child .chip.addr").count() == 1            # chip do comprovante em destaque
    pg.click('#sec-fora-do-raio th[data-sf="nome"]')                                   # ordena por nome (A→Z)
    assert pg.locator("#fora-tbody tr").first.inner_text().startswith("João")
    pg.click('#sec-fora-do-raio th[data-sf="nome"]')
    assert pg.locator("#fora-tbody tr").first.inner_text().startswith("Maria")

    pg.click('#sec-fora-do-raio [data-ff="no-doc"]')
    assert pg.locator("#fora-tbody tr").count() == 1 and "Não encontrado" in pg.inner_text("#fora-tbody")
    pg.click('#sec-fora-do-raio [data-ff="all"]')
    pg.fill("#fora-q", "84010")                                                        # busca por CEP
    assert pg.locator("#fora-tbody tr").count() == 1
    pg.fill("#fora-q", "zzz")
    assert "Nenhum resultado" in pg.inner_text("#fora-empty") and pg.is_visible("#fora-empty")
    assert pg.locator("#sec-fora-do-raio .js-atualizar").get_attribute("data-auto") == "cep"


def test_fora_do_raio_sem_documentos_do_pc_esconde_filtros_de_comprovante(pagina, tmp_path):
    (tmp_path / "documentos-alunos-pc.json").unlink()
    pg = pagina
    _abrir(pg, "fora-do-raio")
    assert not pg.is_visible('#sec-fora-do-raio [data-ff="has-doc"]') and pg.is_visible('#sec-fora-do-raio [data-ff="all"]')
    assert "com comp. endereço" not in _cards(pg, "fora-do-raio")


def test_exportar_baixa_so_as_linhas_filtradas(pagina, tmp_path):
    pg = pagina
    _abrir(pg, "fora-do-raio")
    pg.fill("#fora-q", "conceicao")                                                    # sem acento acha "Conceição"
    assert pg.locator("#fora-tbody tr").count() == 1
    with pg.expect_download() as d:
        pg.click("#sec-fora-do-raio .js-exportar")
    destino = tmp_path / "saida.csv"
    d.value.save_as(destino)
    texto = destino.read_text(encoding="utf-8-sig")
    assert "Maria Conceição" in texto and "João da Silva" not in texto
    assert d.value.suggested_filename.startswith("fora-do-raio_") and d.value.suggested_filename.endswith(".csv")


def test_funcionarios_cards_filtros_busca_detalhe_e_paginacao(pagina):
    pg = pagina
    _abrir(pg, "funcionarios")
    cards = _cards(pg, "funcionarios")
    assert cards["total funcionários"] == "2" and cards["docentes"] == "1" and cards["auxiliares / sec."] == "1"
    assert cards["cadastro completo"] == "1"
    cabecalho = pg.locator("#sec-funcionarios thead th").evaluate_all("els => els.map(e => e.textContent.trim())")
    assert cabecalho == ["", "Nome", "Cargo / Função", "E-mail", "Telefone", "Sexo", "CPF", "Formação"]
    primeira = pg.locator("#func-tbody tr.al-detail-row").count()
    assert primeira == 2 and "Ana Lima" in pg.inner_text("#func-tbody tr:first-child")      # ordem A→Z
    linha_z = pg.locator("#func-tbody tr").nth(2).inner_text()                               # Zélia (a 1ª é Ana + detalhe)
    assert "(42) 99999-8888" in linha_z and "***.222.333-**" in linha_z and "Feminino" in linha_z and "Superior" in linha_z

    pg.click('#func-tbody tr:nth-child(3) .al-expand-btn')                                   # abre o detalhe da Zélia
    detalhe = pg.inner_text("#fn-row-1")
    assert "123456" in detalhe and "Centro" in detalhe and "ZÉLIA DE SOUZA" in detalhe and "11122233344" not in detalhe

    pg.click('#sec-funcionarios [data-fg="Docente"]')
    assert pg.locator("#func-tbody .al-expand-btn").count() == 1
    assert "Docentes (1)" in pg.inner_text("#sec-funcionarios .fbar")
    pg.click('#sec-funcionarios [data-fg="todos"]')
    pg.fill("#func-q", "zelia")                                                              # sem acento
    assert pg.locator("#func-tbody .al-expand-btn").count() == 1
    pg.fill("#func-q", "")
    pg.select_option("#func-sexo", "M")
    assert "Nenhum funcionário" in pg.inner_text("#func-empty") and pg.is_visible("#func-empty")
    pg.select_option("#func-sexo", "todos")
    pg.select_option("#func-pagesize", "10")
    assert "Exibindo 1–2 de 2" in pg.inner_text("#func-pag-info")
    with pg.expect_download() as d:
        pg.click("#sec-funcionarios .js-exportar")
    assert d.value.suggested_filename.startswith("funcionarios_")


def test_prematricula_aba_do_proximo_ano_mostra_as_opcoes_de_escola(pagina, tmp_path):
    from src.comum import paths
    ano = int(paths.ano_atual())
    pg = pagina
    _gravar(tmp_path, "pre_matricula.json", {"turmas_intencao": {}, "cadastros": {
        "1": {"nome_aluno": "Do Ano Atual", "escolas_escolhidas": {"opcoes": [{"escola": "Esc X", "situacao": "MATRICULADO"}]}}}})
    _gravar(tmp_path, f"previsao_alunos_{ano + 1}.json", {
        "turmas_intencao": {"Infantil IV": [{"nome": "Ana Futura", "cpf": "7", "pos": "3"}]},
        "cadastros": {"7": {"nome_aluno": "Ana Futura", "nome_responsavel": "Mãe da Ana", "telefone": "42999990000",
                            "escolas_escolhidas": {"turma": "Infantil IV", "opcoes": [
                                {"escola": "Escola Primeira"}, {"escola": "Judith Macedo Silveira"}, {"escola": "Escola Terceira"}]}}}})
    _abrir(pg, "prematricula")
    anos = pg.inner_text("#pm-anos")
    assert str(ano) in anos and str(ano + 1) in anos and "Do Ano Atual" in pg.inner_text("#pm-tbody")
    pg.click(f'#pm-anos [data-pmano="{ano + 1}"]')
    pg.wait_for_function("document.getElementById('pm-titulo').textContent.includes('%d')" % (ano + 1))
    corpo = pg.inner_text("#pm-tbody")
    assert "Ana Futura" in corpo and "Do Ano Atual" not in corpo
    assert "1ª" in corpo and "2ª" in corpo and "3ª" in corpo and "Escola Primeira" in corpo and "Escola Terceira" in corpo
    assert "Somente consulta" in pg.inner_text("#pm-ano-aviso")
    pg.click("#pm-tbody .al-expand-btn")
    detalhe = pg.inner_text("#pm-det-0")
    assert "Escolas Escolhidas" in detalhe.title() or "Escolas Escolhidas" in detalhe
    assert "nossa escola" in detalhe and "Corrigir dados" not in detalhe                  # próximo ano é só consulta
    pg.click(f'#pm-anos [data-pmano="{ano}"]')
    pg.wait_for_function("document.getElementById('pm-titulo').textContent.includes('%d')" % ano)
    assert "Do Ano Atual" in pg.inner_text("#pm-tbody")


def test_prematricula_abas_busca_detalhe_e_nao_mostra_a_tentativa_antiga(pagina, tmp_path):
    pg = pagina
    _gravar(tmp_path, "pre_matricula.json", {"atualizado_em": "2026-10-01 09:00", "turmas_intencao": {
        "5º Ano A": [{"nome": "Ana", "cpf": "1", "pos": "1", "substituido_por_nova_tentativa": True},
                     {"nome": "Beto", "cpf": "2", "pos": "2"}],
        "5º Ano B": [{"nome": "Ana", "cpf": "1", "pos": "1"}, {"nome": "Caio", "cpf": "3", "pos": "2"}]},
        "cadastros": {
            "1": {"nome_aluno": "Ana", "nome_responsavel": "Mãe da Ana", "telefone": "4299", "criterios": ["IRMÃO NA ESCOLA"],
                  "escolas_escolhidas": {"turma": "5º Ano B", "opcoes": [{"escola": "Esc X", "situacao": "MATRICULADO"}]}},
            "2": {"nome_aluno": "Beto", "escolas_escolhidas": {"opcoes": [{"escola": "Esc X", "situacao": "CANCELADO", "motivo_cancelamento": "Mudou de cidade"}]}}}})
    _abrir(pg, "prematricula")
    cards = _cards(pg, "prematricula")
    assert cards["total de cadastros"] == "3" and cards["matriculados"] == "1" and cards["cancelados"] == "1" and cards["pendentes"] == "1"
    assert pg.locator("#pm-tbody .al-expand-btn").count() == 3                                # Ana não conta duas vezes
    assert "Geral (3)" in pg.inner_text("#sec-prematricula .fbar") and "Pendentes (1)" in pg.inner_text("#sec-prematricula .fbar")
    ana = pg.locator("#pm-tbody tr").first.inner_text()
    assert "5º Ano B" in ana and "5º Ano A" not in ana and "Matriculado" in ana

    pg.click('#pm-tbody tr:first-child .al-expand-btn')                                       # detalhe do cadastro
    assert "IRMÃO NA ESCOLA" in pg.inner_text("#pm-det-0") and "Mãe da Ana" in pg.inner_text("#pm-det-0")

    pg.click('#sec-prematricula [data-pmtab="cancelados"]')                                   # abas mudam as colunas
    assert pg.locator("#pm-tbody .al-expand-btn").count() == 1 and "Mudou de cidade" in pg.inner_text("#pm-tbody")
    assert "Motivo da Recusa" in pg.text_content("#pm-thead")
    pg.click('#sec-prematricula [data-pmtab="matriculados"]')
    assert "Turma" in pg.text_content("#pm-thead") and "5º Ano B" in pg.inner_text("#pm-tbody")
    pg.click('#sec-prematricula [data-pmtab="geral"]')
    pg.fill("#pm-search", "caio")
    assert pg.locator("#pm-tbody .al-expand-btn").count() == 1 and "pendente" in pg.inner_text("#pm-tbody").lower()
    pg.fill("#pm-search", "zzz")
    assert "Nenhum resultado" in pg.inner_text("#pm-empty")


def test_transferidos_cards_filtros_busca_e_exportacao(pagina):
    pg = pagina
    _abrir(pg, "transferidos")
    cards = _cards(pg, "transferidos")
    assert cards["total"] == "3" and cards["completos"] == "1" and cards["parciais"] == "1" and cards["pendentes"] == "1"
    linhas = pg.locator("#transf-tbody tr").all_inner_texts()
    assert linhas[0].startswith("João da Silva") and "Completo" in linhas[0] and "01/03/2026" in linhas[0]   # ordem A→Z
    assert "1/6" in linhas[1] and "Pendente" in linhas[2]
    pg.click('#sec-transferidos [data-tf="parcial"]')
    assert pg.locator("#transf-tbody tr").count() == 1 and "Maria Conceição" in pg.inner_text("#transf-tbody")
    pg.click('#sec-transferidos [data-tf="todos"]')
    pg.click('#sec-transferidos th[data-ts="status"]')                                                         # ordena por andamento
    assert pg.locator("#transf-tbody tr").first.inner_text().startswith("Pedro Alves")
    pg.fill("#transf-q", "conceicao")
    assert pg.locator("#transf-tbody tr").count() == 1
    with pg.expect_download() as d:
        pg.click("#sec-transferidos .js-exportar")
    assert d.value.suggested_filename.startswith("transferidos_")
    assert pg.locator("#sec-transferidos .js-atualizar").get_attribute("data-auto") == "transferidos"


def test_telas_vazias_orientam_o_que_fazer(pagina, tmp_path):
    pg = pagina
    for f in ("alunos_fora_raio.json",):
        (tmp_path / f).unlink()
    pg.click('.nav-item[data-view="fora-do-raio"]')
    # espera a mensagem final (e não a linha "Carregando…", que também usa colspan)
    pg.wait_for_function("document.querySelector('#fora-empty').textContent.includes('Atualizar dados')")


def test_pagina_nao_tem_ids_duplicados(pagina):
    """Regressão: 'tbody-prematricula' existia no painel E na tela de Pré-matrícula; o JS preenchia o errado."""
    repetidos = pagina.evaluate("""() => {
        const cont = {};
        document.querySelectorAll('[id]').forEach((e) => { cont[e.id] = (cont[e.id] || 0) + 1; });
        return Object.entries(cont).filter(([, n]) => n > 1).map(([id]) => id);
    }""")
    assert repetidos == []


def test_painel_continua_mostrando_a_previa_da_fila(pagina, tmp_path):
    pg = pagina
    _gravar(tmp_path, "pre_matricula.json", {"turmas_intencao": {"5º Ano A": [{"nome": "Beto", "cpf": "2", "pos": "1"}]}, "cadastros": {}})
    pg.reload()
    pg.wait_for_function("document.querySelector('#tbody-painel-prematricula').textContent.includes('Beto')")


# ───────────── executar a pré-matrícula pela própria tela ─────────────
# As rotas de executar/status/cancelar são simuladas no navegador: o teste nunca abre o site real da pré-matrícula.

def _cad(nome):
    return {"nome_aluno": nome, "nome_responsavel": "Resp", "escolas_escolhidas": {"opcoes": []}}


class _ServidorFalso:
    """Respostas simuladas de /automacoes/prematricula_completa/{executar,status,cancelar}."""
    def __init__(self, pg):
        self.fase = "parado"            # parado | rodando | fim | erro
        self.postados, self.cancelamentos = [], 0
        self.erro_ao_iniciar = None
        pg.route("**/automacoes/prematricula_completa/status", self._status)
        pg.route("**/automacoes/prematricula_completa/executar", self._executar)
        pg.route("**/automacoes/prematricula_completa/cancelar", self._cancelar)

    def _json(self, route, corpo, codigo=200):
        route.fulfill(status=codigo, content_type="application/json", body=json.dumps(corpo))

    def _status(self, route):
        logs = {"parado": [], "rodando": ["PROCESSO DE PRÉ-MATRÍCULA - 2026", "✅ Etapa 1 concluída. Resultado salvo"],
                "fim": ["✅ Etapa 1 concluída.", "✅ Etapa 2 concluída.", "(Etapa 4 pulada)", "Contatos gerados"],
                "erro": ["❌ Etapa 1 falhou. Abortando processo."]}[self.fase]
        status = {"parado": "nunca_executado", "rodando": "executando", "fim": "concluido", "erro": "erro"}[self.fase]
        self._json(route, {"status": status, "logs": logs, "erro": "login recusado" if self.fase == "erro" else None,
                           "cancelando": False})

    def _executar(self, route):
        if self.erro_ao_iniciar:
            return self._json(route, {"status": "erro", "mensagem": self.erro_ao_iniciar}, 400)
        self.postados.append(json.loads(route.request.post_data or "{}"))
        self.fase = "rodando"
        self._json(route, {"status": "executando"})

    def _cancelar(self, route):
        self.cancelamentos += 1
        self._json(route, {"status": "ok"})


def test_executar_prematricula_na_tela_acompanha_e_atualiza_os_dados(pagina, tmp_path):
    pg = pagina
    _gravar(tmp_path, "pre_matricula.json", {"cadastros": {"1": _cad("Ana")}, "turmas_intencao": {}})
    srv = _ServidorFalso(pg)
    _abrir(pg, "prematricula")
    assert not pg.is_visible("#pm-exec") and _cards(pg, "prematricula")["total de cadastros"] == "1"

    pg.click("#pm-btn-executar")                                       # abre o painel
    assert pg.is_visible("#pm-exec") and "parado" in pg.inner_text("#pm-exec-status")
    assert pg.locator("#pm-etapas .pm-etapa").count() == 4
    pg.check("#pm-opt-pular")
    pg.check("#pm-opt-debug")
    pg.click("#pm-exec-iniciar")
    pg.wait_for_function("document.querySelector('#pm-exec-status').textContent.includes('executando')")
    assert srv.postados == [{"debug": True, "pular_pendentes": True}]  # as opções vão para a automação
    assert pg.locator("#pm-exec-iniciar").is_disabled() and pg.is_visible("#pm-exec-cancelar")
    assert "Etapa 1 concluída" in pg.inner_text("#pm-exec-log")
    assert pg.locator("#pm-etapas .pm-etapa.feita").count() == 1 and pg.locator("#pm-etapas .pm-etapa.ativa").count() == 1
    assert pg.is_disabled("#pm-opt-debug")                             # não muda opção no meio da execução

    _gravar(tmp_path, "pre_matricula.json", {"cadastros": {"1": _cad("Ana"), "2": _cad("Beto")}, "turmas_intencao": {}})
    srv.fase = "fim"                                                   # o servidor termina; o próximo ciclo (2 s) percebe
    pg.wait_for_function("document.querySelector('#pm-exec-status').textContent.includes('concluído')", timeout=8000)
    assert "Concluído" in pg.inner_text("#pm-exec-msg") and not pg.is_visible("#pm-exec-cancelar")
    assert pg.locator("#pm-etapas .pm-etapa.feita").count() == 3 and pg.locator("#pm-etapas .pm-etapa.pulada").count() == 1
    pg.wait_for_function("[...document.querySelectorAll('#cartoes-prematricula .stat-card')].some(e => e.textContent.includes('2'))")
    assert _cards(pg, "prematricula")["total de cadastros"] == "2"      # dados recarregados sozinhos
    assert pg.locator("#pm-exec-iniciar").is_enabled()


def test_executar_prematricula_mostra_o_erro_do_servidor_e_permite_tentar_de_novo(pagina):
    pg = pagina
    srv = _ServidorFalso(pg)
    srv.erro_ao_iniciar = "Credenciais da pré-matrícula não configuradas."
    pg.click('.nav-item[data-view="prematricula"]')
    pg.click("#pm-btn-executar")
    pg.click("#pm-exec-iniciar")
    pg.wait_for_function("document.querySelector('#pm-exec-msg').textContent.includes('Credenciais')")
    assert "erro" in pg.get_attribute("#pm-exec-msg", "class") and pg.locator("#pm-exec-iniciar").is_enabled()
    assert srv.postados == []


def test_executar_prematricula_falha_marca_a_etapa_e_cancelar_chama_a_rota(pagina):
    pg = pagina
    srv = _ServidorFalso(pg)
    srv.fase = "rodando"                                               # já havia uma execução em andamento ao abrir a tela
    pg.click('.nav-item[data-view="prematricula"]')
    pg.wait_for_selector("#pm-exec", state="visible")                  # painel reaparece sozinho e retoma o acompanhamento
    pg.wait_for_function("document.querySelector('#pm-exec-status').textContent.includes('executando')")
    pg.click("#pm-exec-cancelar")
    pg.wait_for_function("true")
    assert srv.cancelamentos == 1
    srv.fase = "erro"
    pg.wait_for_function("document.querySelector('#pm-exec-status').textContent.includes('erro')", timeout=8000)
    assert "login recusado" in pg.inner_text("#pm-exec-msg") and pg.locator("#pm-etapas .pm-etapa.falha").count() == 1


def test_transferidos_fila_situacao_no_processo_e_ciclos_anteriores(pagina, tmp_path, monkeypatch):
    from datetime import date
    monkeypatch.setattr(rotas._config, "data_corte_transferidos", lambda: date(2026, 6, 22))
    d = "2026-08-01T10:00:00"
    controle = json.loads((tmp_path / "transferidos.json").read_text(encoding="utf-8"))
    controle["444"] = {"nome": "Ana Duas Saídas", "turma": "2º Ano A", "data_transferencia": "10/10/2026", "guia": {}, "historico": {},
                       "ciclos_anteriores": [{"turma": "2º Ano A", "data_transferencia": "05/03/2026", "retorno": {"data": "20/04/2026"},
                                               "guia": {"emitido_em": d}, "historico": {}, "parecer": {}, "id_matricula": "M-9",
                                               "arquivos": {"guia": "Ana (saída 05-03-2026).pdf"}}]}
    _gravar(tmp_path, "transferidos.json", controle)

    def f(nome, data, retorno=None):
        return {"nome": nome, "turma": "4º Ano A", "chamada": 1, "data_transferencia": data, "retornou": retorno is not None, "retorno": retorno}
    _gravar(tmp_path, "fila_transferidos.json", {"gerado_em": "2026-11-20 10:00:00", "data_corte": "22/06/2026", "alunos": {
        "555": f("Zeca Antes", "10/03/2026"), "666": f("Caio Voltou", "01/08/2026", {"data": "20/08/2026"})}})

    pg = pagina
    _abrir(pg, "transferidos")
    cards = _cards(pg, "transferidos")
    assert cards["total"] == "6" and cards["fora do processo"] == "2" and cards["completos"] == "1"
    assert "Fora do processo (2)" in pg.inner_text('#sec-transferidos [data-tf="fora"]')
    assert pg.locator("#transf-tbody tr").count() == 6

    pg.click('#sec-transferidos [data-tf="fora"]')                                       # só quem não entra no processo
    texto = pg.inner_text("#transf-tbody")
    assert pg.locator("#transf-tbody tr").count() == 2 and "Antes do corte" in texto and "voltou em 20/08/2026" in texto
    assert "tratada à mão" in texto and pg.locator("#transf-tbody [data-destino]").count() == 0   # sem registro: sem botão Destino…
    pg.click('#sec-transferidos [data-tf="todos"]')

    pg.check("#transf-oculta-retorno")                                                   # esconde quem voltou
    assert pg.locator("#transf-tbody tr").count() == 5 and "Caio Voltou" not in pg.inner_text("#transf-tbody")
    pg.uncheck("#transf-oculta-retorno")

    pg.fill("#transf-q", "duas saídas")
    assert "1 saída anterior" in pg.inner_text("#transf-tbody")
    pg.click("#transf-tbody [data-ciclos]")
    pg.wait_for_selector(".modal-card")
    janela = pg.inner_text(".modal-card")
    assert "1ª saída: 05/03/2026" in janela and "voltou à escola em 20/04/2026" in janela and "M-9" in janela
    assert "Ana (saída 05-03-2026).pdf" in janela
    pg.click("#tf-ciclos-fechar")
    assert pg.locator(".modal-card").count() == 0

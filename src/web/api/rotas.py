"""
Rotas de API do Auto SERE
==========================
Cada endpoint abaixo já está com um retorno de EXEMPLO (mock) para que
a interface funcione de ponta a ponta imediatamente. Substitua o corpo
de cada função pela chamada real às automações já implementadas em
`src/automacao/*.py` e `src/comum/*.py`.

Padrão sugerido para conectar uma automação real:

    from src.automacao.gerar_pastas import executar as executar_gerar_pastas

    @api_bp.route("/automacoes/gerar_pastas/executar", methods=["POST"])
    def executar_gerar_pastas_view():
        payload = request.get_json(silent=True) or {}
        resultado = executar_gerar_pastas(
            por_turma=payload.get("por_turma", False),
            turmas=payload.get("turmas", []),
            pasta_raiz=payload.get("pasta"),
        )
        return jsonify(resultado)

Todas as respostas seguem JSON simples para facilitar o consumo pelo
static/js/app.js já pronto na interface.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

api_bp = Blueprint("api", __name__)


# ============================================================
# PAINEL PRINCIPAL
# ============================================================

@api_bp.route("/painel/resumo")
def painel_resumo():
    """
    TODO: conectar com src/relatorios/analisa_arquivos_sere.py ou
    equivalente para trazer os números reais da escola.
    """
    return jsonify({
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "principais": [
            {"chave": "total_alunos", "label": "Total de alunos", "valor": 768},
            {"chave": "meninos", "label": "Meninos", "valor": 389, "sub": "50,7%"},
            {"chave": "meninas", "label": "Meninas", "valor": 379, "sub": "49,3%"},
            {"chave": "fila_prematricula", "label": "Fila da pré-matrícula", "valor": 23},
            {"chave": "turmas", "label": "Turmas", "valor": 18},
        ],
        "secundarias": [
            {"chave": "docs_pendentes", "label": "Docs pendentes", "valor": 12},
            {"chave": "fora_do_raio", "label": "Fora do raio da escola", "valor": 4},
            {"chave": "transferidos", "label": "Qtd. transferidos", "valor": 7},
            {"chave": "encaminhamentos", "label": "Qtd. encaminhamentos SUS", "valor": 3},
        ],
    })


# ============================================================
# ENTIDADES (TURMAS / ALUNOS / PRÉ-MATRÍCULA / FUNCIONÁRIOS)
# ============================================================

def _resposta_lista_generica(colunas, linhas):
    return jsonify({"colunas": colunas, "linhas": linhas, "total": len(linhas)})


@api_bp.route("/turmas/lista")
def turmas_lista():
    """TODO: conectar com src/automacao/turmas.py"""
    colunas = [
        {"chave": "id", "label": "ID"},
        {"chave": "nome", "label": "Turma"},
        {"chave": "etapa", "label": "Etapa"},
        {"chave": "qtd_alunos", "label": "Qtd. alunos"},
        {"chave": "turno", "label": "Turno"},
    ]
    linhas = [
        {"id": "1", "nome": "INFANTIL IV", "etapa": "Educação Infantil", "qtd_alunos": 22, "turno": "Manhã"},
        {"id": "2", "nome": "INFANTIL V", "etapa": "Educação Infantil", "qtd_alunos": 24, "turno": "Tarde"},
        {"id": "3", "nome": "3º ANO", "etapa": "Fundamental", "qtd_alunos": 27, "turno": "Manhã"},
    ]
    return _resposta_lista_generica(colunas, linhas)


@api_bp.route("/alunos/lista")
def alunos_lista():
    """TODO: conectar com src/automacao/alunos.py e alunos_completo.py"""
    colunas = [
        {"chave": "nome", "label": "Nome"},
        {"chave": "turma", "label": "Turma"},
        {"chave": "situacao", "label": "Situação"},
        {"chave": "docs_pendentes", "label": "Docs pendentes"},
    ]
    linhas = [
        {"nome": "FULANO DA SILVA", "turma": "INFANTIL IV", "situacao": "Ativo", "docs_pendentes": 0},
        {"nome": "JOÃO PEREIRA", "turma": "INFANTIL V", "situacao": "Ativo", "docs_pendentes": 2},
    ]
    return _resposta_lista_generica(colunas, linhas)


@api_bp.route("/prematricula/lista")
def prematricula_lista():
    """TODO: conectar com src/automacao/prematricula.py (capturar_matricula.py)"""
    colunas = [
        {"chave": "nome", "label": "Nome do aluno"},
        {"chave": "turma", "label": "Turma"},
        {"chave": "posicao", "label": "Posição na fila"},
        {"chave": "telefone_responsavel", "label": "Número do pai"},
    ]
    linhas = [
        {"nome": "FULANO", "turma": "INFANTIL IV", "posicao": 1, "telefone_responsavel": "(42) xxxx-xxxx"},
        {"nome": "JOÃO", "turma": "INFANTIL V", "posicao": 1, "telefone_responsavel": "(42) xxxx-xxxx"},
        {"nome": "MARIA", "turma": "3º ANO", "posicao": 1, "telefone_responsavel": "(42) xxxx-xxxx"},
    ]
    return _resposta_lista_generica(colunas, linhas)


@api_bp.route("/prematricula/fila")
def prematricula_fila():
    """Versão resumida usada no painel principal (widget da fila)."""
    limit = int(request.args.get("limit", 5))
    itens = [
        {"id": 1, "nome": "FULANO", "turma": "INFANTIL IV", "posicao": 1, "telefone_responsavel": "(42) xxxx-xxxx"},
        {"id": 2, "nome": "JOÃO", "turma": "INFANTIL V", "posicao": 1, "telefone_responsavel": "(42) xxxx-xxxx"},
        {"id": 3, "nome": "MARIA", "turma": "3º ANO", "posicao": 1, "telefone_responsavel": "(42) xxxx-xxxx"},
    ][:limit]
    return jsonify({"itens": itens})


@api_bp.route("/funcionarios/lista")
def funcionarios_lista():
    """TODO: conectar com src/automacao/servidores.py e capturar_matricula.py"""
    colunas = [
        {"chave": "nome", "label": "Nome"},
        {"chave": "cargo", "label": "Cargo"},
        {"chave": "situacao", "label": "Situação"},
    ]
    linhas = [
        {"nome": "MARIA APARECIDA", "cargo": "Professora", "situacao": "Ativa"},
        {"nome": "JOSÉ CARLOS", "cargo": "Diretor", "situacao": "Ativo"},
    ]
    return _resposta_lista_generica(colunas, linhas)


# ============================================================
# AUTOMAÇÕES
# ============================================================

AUTOMACOES_DISPONIVEIS = [
    {"chave": "gerar_pastas", "nome": "Gerar pastas", "descricao": "Cria pastas dos alunos automaticamente."},
    {"chave": "analisa_pasta", "nome": "Analisa documentos da pasta", "descricao": "Analisa e organiza documentos diretamente da pasta."},
    {"chave": "analisa_sere", "nome": "Analisa documentos do SERE", "descricao": "Analisa documentos disponíveis no SERE."},
    {"chave": "documentos", "nome": "Documentos", "descricao": "Gerencia todos os documentos do SERE (normalização)."},
    {"chave": "cruzamento", "nome": "Cruzamento de docs", "descricao": "Cruza informações e valida documentações."},
    {"chave": "cep", "nome": "CEP", "descricao": "Consulta, valida e completa endereços via CEP."},
    {"chave": "sus", "nome": "Encaminhamentos do SUS", "descricao": "Consulta se o aluno possui encaminhamentos na fila pública do SUS."},
    {"chave": "transferidos", "nome": "Processo transferidos", "descricao": "Gera histórico e guia de transferência."},
    {"chave": "parecer_fund", "nome": "Pareceres fundamental", "descricao": "Gera todos os pareceres do Fundamental."},
    {"chave": "parecer_rco", "nome": "Pareceres infantil", "descricao": "Gera parecer do RCO e parecer da planilha."},
    {"chave": "comprimir", "nome": "Comprimir documentos", "descricao": "Comprime todos os docs, pareceres e docs dos alunos."},
    {"chave": "coleta_emails", "nome": "Coleta e-mails", "descricao": "Coleta os e-mails de outras escolas da rede municipal."},
    {"chave": "agendador", "nome": "Criar rotinas no agendador", "descricao": "Cria rotinas automáticas no Agendador de Tarefas do Windows."},
    {"chave": "backup", "nome": "Backup dos dados", "descricao": "Realiza backup de toda base de dados e arquivos."},
    {"chave": "avisos", "nome": "Mandar avisos", "descricao": "Envia e-mails e mensagens automáticas."},
    {"chave": "compara_anos", "nome": "Compara transferidos entre anos", "descricao": "Compara transferidos entre anos diferentes."},
    {"chave": "termos", "nome": "Gerar termos de ciência", "descricao": "Gera termos de ciência para os funcionários."},
    {"chave": "mapear_pastas", "nome": "Mapear pastas dos alunos", "descricao": "Mapeia e organiza caminhos das pastas dos alunos."},
    {"chave": "mascara", "nome": "Máscara de dados", "descricao": "Aplica máscara em dados sensíveis (LGPD)."},
    {"chave": "rematricula", "nome": "Rematrícula alunos no SERE", "descricao": "Realiza rematrícula dos alunos no SERE."},
]


@api_bp.route("/automacoes/lista")
def automacoes_lista():
    return jsonify({"itens": AUTOMACOES_DISPONIVEIS})


@api_bp.route("/automacoes/<string:chave>/executar", methods=["POST"])
def automacoes_executar(chave):
    """
    TODO: mapear `chave` para a função real, por exemplo:

        MAPA_AUTOMACOES = {
            "gerar_pastas": src.automacao.gerar_pastas.executar,
            "analisa_pasta": src.relatorios.analisa_documentos_pc.executar,
            "analisa_sere": src.relatorios.analisa_arquivos_sere.executar,
            ...
        }
        funcao = MAPA_AUTOMACOES.get(chave)
        if not funcao:
            return jsonify({"erro": f"Automação '{chave}' não encontrada"}), 404
        resultado = funcao(**payload)
        return jsonify(resultado)
    """
    payload = request.get_json(silent=True) or {}
    return jsonify({
        "status": "ok",
        "mensagem": f"[MOCK] Automação '{chave}' executada com sucesso.",
        "recebido": payload,
    })


# ============================================================
# SISTEMA — seleção de pasta via janela nativa do Windows (tkinter)
# ============================================================
# Como o Flask roda localmente na mesma máquina Windows que tem o
# SERE, o jeito mais direto de escolher uma pasta é abrir a janela
# nativa do Explorer via tkinter.filedialog, no processo do backend.
# O navegador não participa da escolha — só dispara a requisição e
# recebe de volta o caminho absoluto (ex: C:\ARQUIVOS\ESCOLA JUDITH\...).
#
# IMPORTANTE: tkinter precisa rodar numa janela do sistema operacional,
# então isso só funciona quando o servidor Flask roda diretamente na
# máquina Windows do usuário (não em contêiner, WSL sem X server, ou
# servidor remoto/hospedado). Se a automação não puder abrir GUI,
# ela cai automaticamente num fallback simples (ver except abaixo).

@api_bp.route("/sistema/escolher-pasta", methods=["POST"])
def escolher_pasta():
    """
    Abre o diálogo nativo do Windows para escolher uma pasta e devolve
    o caminho absoluto selecionado.

    payload opcional: {"titulo": "Escolha a pasta raiz dos alunos"}
    """
    payload = request.get_json(silent=True) or {}
    titulo = payload.get("titulo", "Selecione a pasta")

    try:
        import tkinter as tk
        from tkinter import filedialog

        # Janela raiz invisível: existe só para o filedialog funcionar,
        # não deve aparecer na tela.
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)  # traz o diálogo para frente

        caminho = filedialog.askdirectory(title=titulo)
        root.destroy()

        if not caminho:
            # Usuário cancelou o diálogo
            return jsonify({"caminho": None, "cancelado": True})

        return jsonify({"caminho": caminho, "cancelado": False})

    except Exception as exc:
        # Ambiente sem suporte a GUI (ex.: servidor headless/remoto).
        # Devolve erro explícito em vez de mascarar com um caminho falso.
        return jsonify({
            "caminho": None,
            "erro": f"Não foi possível abrir o explorador de arquivos neste ambiente: {exc}",
        }), 500


# ============================================================
# WIZARD — 1ª execução obrigatória
# ============================================================

@api_bp.route("/wizard/status")
def wizard_status():
    """
    TODO: conectar com src/comum/credenciais.py e src/comum/configuracao.py
    para checar de verdade quais passos já foram concluídos.
    """
    return jsonify({
        "credenciais_sere": True,
        "turmas": True,
        "gerar_pastas": False,
        "funcionarios": False,
        "alunos": False,
        "google_api": False,
        "whatsapp": False,
    })


@api_bp.route("/wizard/<string:passo>/executar", methods=["POST"])
def wizard_executar_passo(passo):
    """TODO: mapear cada passo do wizard para a automação real correspondente."""
    return jsonify({"status": "ok", "mensagem": f"[MOCK] Passo '{passo}' executado."})

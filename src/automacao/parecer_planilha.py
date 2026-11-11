"""
parecer_planilha.py (portado de gerar_pareceres_infantil_planilha.py para src/automacao/)

Gera os pareceres do INFANTIL IV e V a partir das planilhas do Google Sheets que as professoras preenchem: um PDF por
aluno, com QR code criptografado, na mesma árvore de pastas dos pareceres baixados do RCO (parecer_rco):

    dados/<ano>/PARECERES INFANTIL/<N>º Bimestre/<turma>/<nº da chamada> - <nome>.pdf

Os dois se completam: esta automação faz o 1º e o 3º bimestre (planilha); o parecer_rco faz o 2º e o 4º (RCO).

Para cada planilha ATIVA cadastrada em "Planilhas do Drive" com finalidade "Pareceres do Infantil" (cada uma com a sua
turma):
  1. autentica na API do Google (as credenciais do sistema, src/comum/google_auth.py) com permissão de planilhas e de
     leitura do Drive (exigida pela exportação em PDF; ver "Primeira vez");
  2. para cada aluno Matriculado da turma, na ordem do nº de chamada:
       a) grava o nome do aluno na célula C5 da aba "F.D.SON. A" (a lista suspensa que a planilha usa para montar o parecer);
       b) espera a planilha recalcular;
       c) exporta o intervalo A1:N52 em PDF (A4 paisagem), com o endereço de exportação do Sheets;
       d) cola o QR code no canto inferior ESQUERDO da última página (texto AUTOSERE|PF2|…, criptografado, o mesmo padrão
          dos pareceres do Fundamental: ano letivo, nº da chamada, nome, turma e CGM);
       e) salva o PDF.
  3. ao terminar a planilha, devolve a C5 ao valor que ela tinha antes.

Ponto de entrada (sem argparse/sys.argv; pronto para virar botão de GUI):

  gerar_pareceres_infantil_planilha(bimestre="1", modo_teste=False, substituir=False)

    bimestre     "1" ou "3" — define a subpasta de destino (antes: pergunta no terminal)
    modo_teste   só o primeiro aluno de cada planilha (para conferir o acesso e o resultado)
    substituir   refaz também os pareceres que já existem (por padrão são mantidos)

Primeira vez: o Google pede para você autorizar o acesso à planilha E ao Drive em leitura (o navegador abre sozinho; o
token fica em credenciais/google_token_drive.json, à parte do token das planilhas). Sem o Drive não há como exportar PDF.

Diferenças em relação ao script original:
  - As planilhas, em vez de fixas no código (ID, aba, gid, turma), vêm do cadastro "Planilhas do Drive": finalidade
    "Pareceres do Infantil" + turma, e vale a que está ATIVA. Trocar de ano ou de planilha é só cadastrar/ativar outra.
    O gid da aba é descoberto pelo nome da aba (não fica mais preso a um número).
  - As credenciais e o token são os do sistema (google_auth), não um credentials1.json/token_sheets.json à parte.
  - turmas.json do ano (paths.dados_ano_atual()), só alunos Matriculado e com CGM (como o parecer_rco); o original
    pegava a turma inteira, inclusive transferidos.
  - O QR usa o padrão do sistema (src/comum/qr_seguro.py: AES-256-GCM, chave em credenciais/chave_qr.key, a mesma dos
    pareceres do Fundamental), e não mais uma chave Fernet própria. Atenção: esse padrão não leva o bimestre no QR
    (o bimestre está na pasta do arquivo).
  - A pasta da turma segue o nome do parecer_rco (INFANTIL_4_Integral_A), para o RCO e a planilha caírem juntos.
  - Em vez do controle_pareceres_infantil.json, "já gerado" é o próprio PDF existir (como no parecer_fund); nunca
    sobrescreve sem o pedido "substituir".
  - O PDF é gravado de forma atômica (um arquivo pela metade nunca fica como se estivesse pronto).
  - Um aluno com erro vai para a lista de falhas e os demais continuam; erro de acesso/permissão para tudo na hora.
  - O bimestre e as opções vêm da tela (sem input()); devolve um resumo; cancelamento a cada aluno.
  - A C5 é devolvida ao valor de antes no fim (o original deixava o último aluno na planilha das professoras).
"""
from __future__ import annotations

import io
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

from src.automacao import parecer_rco as _rco
from src.comum import google_auth, google_sheets as gs, paths, planilhas_registro as registro, qr_seguro
from src.comum.execucao_gui import verificar_cancelamento

CHAVE = "parecer_planilha"

BIMESTRES = {"1": "1º Bimestre", "3": "3º Bimestre"}

ABA_PADRAO = "F.D.SON. A"
CELULA_SELECAO = "C5"
INTERVALO_PDF = "A1:N52"
ESPERA_ATUALIZACAO_S = 3.0              # a planilha recalcula fórmulas/PROCV depois de mudar a C5
TENTATIVAS_EXPORTACAO = 3
ESPERA_ENTRE_TENTATIVAS_S = 2.0
TIMEOUT_EXPORTACAO_S = 30

TAMANHO_QR_PT = 100                     # pontos (1 pt = 1/72")
MARGEM_ESQUERDA_PT = 30
MARGEM_INFERIOR_PT = 30

ESCOPOS = [google_auth.ESCOPO_SHEETS, google_auth.ESCOPO_DRIVE_LEITURA]


class ExportacaoErro(RuntimeError):
    """Não foi possível exportar o PDF da planilha (a mensagem já vem pronta)."""


# ───────────────────────────── preparação (sem Google) ─────────────────────────────

def rotulo_bimestre(valor) -> str:
    """'1' / '3' (também '1º', '3º Bimestre') → '1º Bimestre' / '3º Bimestre'. ValueError se for outro valor."""
    m = re.fullmatch(r"\s*([13])\s*[º°o]?\s*(?:bimestre)?\s*", str(valor or ""), flags=re.IGNORECASE)
    if not m:
        raise ValueError("Escolha o bimestre: 1º ou 3º (o 2º e o 4º vêm do RCO, em 'Pareceres infantil').")
    return BIMESTRES[m.group(1)]


def planilhas_do_cadastro() -> list[dict]:
    """As planilhas ativas do cadastro 'Planilhas do Drive' para pareceres do Infantil. ValueError com mensagem pronta."""
    itens = registro.planilhas_da_finalidade(registro.FINALIDADE_PARECER_INFANTIL)
    if not itens:
        raise ValueError(
            "Nenhuma planilha de pareceres do Infantil está ativa no cadastro. Abra 'Planilhas do Drive', cadastre cada "
            "planilha com a finalidade 'Pareceres do Infantil' e a turma dela, e deixe-a Ativa.")
    vistas: dict[str, dict] = {}
    for item in itens:
        chave = str(item.get("turma") or "").casefold()
        if not chave:
            raise ValueError(f"A planilha '{item.get('nome')}' (id {item.get('id')}) está sem turma no cadastro 'Planilhas do Drive'.")
        if chave in vistas:
            raise ValueError(f"A turma '{item['turma']}' tem duas planilhas ativas ('{vistas[chave]['nome']}' e '{item['nome']}'). "
                             "Deixe uma delas inativa em 'Planilhas do Drive'.")
        vistas[chave] = item
    return itens


def _situacao(aluno: dict) -> str:
    return str(aluno.get("Situação") or aluno.get("Situacao") or aluno.get("Situacão") or "").strip().lower()


def _numero(aluno: dict) -> int:
    try:
        return int(str(aluno.get("N") or "").strip())
    except ValueError:
        return 10 ** 6                                   # sem nº de chamada vai para o fim


def alunos_da_turma(turmas: dict, turma: str) -> list[dict]:
    """
    Alunos Matriculado da turma (como em turmas.json), na ordem do nº de chamada:
    [{"n_chamada", "nome", "cgm"}]. ValueError (com as turmas do Infantil que existem) se a turma não existe.
    """
    chave = str(turma).strip().casefold()
    nome_real = next((t for t in turmas if str(t).strip().casefold() == chave), None)
    if nome_real is None:
        infantil = sorted(t for t in turmas if re.search(r"infantil", str(t), re.IGNORECASE))
        raise ValueError(f"A turma '{turma}' (cadastrada em 'Planilhas do Drive') não existe em turmas.json. "
                         f"Turmas do Infantil que existem: {', '.join(infantil) or '(nenhuma)'}.")
    lista = turmas[nome_real] if isinstance(turmas[nome_real], list) else []
    alunos = [a for a in lista if isinstance(a, dict) and _situacao(a) == "matriculado" and str(a.get("Nome") or "").strip()]
    alunos.sort(key=_numero)
    return [{"n_chamada": a.get("N"), "nome": str(a.get("Nome")).strip(), "cgm": str(a.get("CGM") or "").strip(),
             "turma": nome_real} for a in alunos]


def validar_pedido(bimestre) -> None:
    """Tudo o que dá para conferir ANTES de falar com o Google (ValueError = mensagem pronta)."""
    rotulo_bimestre(bimestre)
    if not google_auth.credenciais_configuradas():
        raise ValueError(
            "As credenciais do Google ainda não foram configuradas (arquivo credenciais/google_credentials.json). "
            "O passo a passo está em docs/GOOGLE_SHEETS.md.")
    turmas = _rco.carregar_turmas()
    for planilha in planilhas_do_cadastro():
        if not alunos_da_turma(turmas, planilha["turma"]):
            raise ValueError(f"Nenhum aluno Matriculado na turma '{planilha['turma']}' em turmas.json.")


def montar_url_exportacao(planilha_id: str, gid, intervalo: str = INTERVALO_PDF) -> str:
    """Endereço de exportação em PDF (A4 paisagem, ajustado à largura, sem grade nem título)."""
    from urllib.parse import urlencode
    params = {
        "format": "pdf", "gid": gid, "range": intervalo, "size": "A4", "portrait": "false", "fitw": "true",
        "top_margin": 0.40, "bottom_margin": 0.40, "left_margin": 0.40, "right_margin": 0.40,
        "gridlines": "false", "printtitle": "false", "sheetnames": "false", "pagenumbers": "false", "fzr": "false",
        "attachment": "true",
    }
    return f"https://docs.google.com/spreadsheets/d/{planilha_id}/export?" + urlencode(params)


# ───────────────────────────── Google ─────────────────────────────

def abrir_google(*, interativo: bool = True):
    """(credenciais, recurso spreadsheets()) com permissão de planilhas e de leitura do Drive."""
    from googleapiclient.discovery import build
    creds = google_auth.obter_credenciais(ESCOPOS, interativo=interativo, arquivo_token=google_auth.caminho_token_drive())
    return creds, build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()


def _token_valido(creds) -> str:
    """Renova o token de acesso se preciso (a conta de serviço começa sem ele) e devolve o atual."""
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    return creds.token


def _nome_e_gid_da_aba(servico, planilha_id: str, aba: str) -> tuple[str, int]:
    """(nome exato da aba, gid) pelo nome da aba."""
    meta = gs._executar(servico.get(spreadsheetId=planilha_id, fields="sheets.properties(sheetId,title)"), "abrir a planilha")
    abas = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
    nome = gs.resolver_aba(aba, abas)
    return nome, abas[nome]


def exportar_pdf(url: str, creds, *, http_get: Optional[Callable] = None, tentativas: int = TENTATIVAS_EXPORTACAO,
                 espera_s: float = ESPERA_ENTRE_TENTATIVAS_S, dormir: Callable = time.sleep) -> bytes:
    """
    GET autenticado (Bearer) do endereço de exportação. Só aceita se for mesmo um PDF (HTTP 200 + tipo + assinatura
    %PDF). Tenta de novo em erro transitório (rede, limite de uso, 5xx); sem autorização (401) ou planilha inexistente
    (404) repetir não adianta. ExportacaoErro com mensagem pronta; nada de token ou conteúdo da resposta na mensagem.
    """
    if http_get is None:
        import requests
        http_get = requests.get
    ultimo = "motivo desconhecido"
    for tentativa in range(1, tentativas + 1):
        try:
            resp = http_get(url, headers={"Authorization": f"Bearer {_token_valido(creds)}"}, timeout=TIMEOUT_EXPORTACAO_S)
        except OSError as exc:                                   # requests.RequestException também é OSError
            ultimo = f"falha de conexão ({type(exc).__name__})"
            dormir(espera_s)
            continue
        status = resp.status_code
        if status == 401:
            raise ExportacaoErro(
                "O Google recusou o acesso ao exportar o PDF (401). Apague credenciais/google_token_drive.json e rode de novo "
                "para autorizar outra vez (precisa da permissão de leitura do Drive).")
        if status == 404:
            raise ExportacaoErro("A planilha não foi encontrada ao exportar o PDF (404): confira o link e se a conta tem acesso.")
        if status != 200:
            ultimo = f"HTTP {status}" + (" (sem permissão ou limite de uso do Google)" if status == 403 else "")
            dormir(espera_s)
            continue
        tipo = str(resp.headers.get("content-type") or "").lower()
        corpo = resp.content
        if "pdf" not in tipo or not corpo.startswith(b"%PDF"):
            ultimo = "o Google respondeu com algo que não é um PDF"
            dormir(espera_s)
            continue
        return corpo
    raise ExportacaoErro(f"Não consegui exportar o PDF depois de {tentativas} tentativa(s): {ultimo}.")


# ───────────────────────────── QR code no PDF ─────────────────────────────

def gerar_qr_imagem(ano, chamada, nome, turma, cgm):
    """Imagem (PIL) do QR criptografado no padrão do sistema (qr_seguro)."""
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(qr_seguro.montar(ano, chamada, nome, turma, cgm))
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def inserir_qr_no_pdf(pdf: bytes, imagem_qr, *, tamanho_pt: float = TAMANHO_QR_PT, margem_esquerda_pt: float = MARGEM_ESQUERDA_PT,
                      margem_inferior_pt: float = MARGEM_INFERIOR_PT) -> bytes:
    """Cola o QR no canto inferior ESQUERDO da última página (tudo em memória)."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    leitor = PdfReader(io.BytesIO(pdf))
    alvo = len(leitor.pages) - 1
    largura, altura = float(leitor.pages[alvo].mediabox.width), float(leitor.pages[alvo].mediabox.height)

    camada = io.BytesIO()
    c = canvas.Canvas(camada, pagesize=(largura, altura))
    png = io.BytesIO()
    imagem_qr.save(png, format="PNG")
    png.seek(0)
    c.drawImage(ImageReader(png), margem_esquerda_pt, margem_inferior_pt, width=tamanho_pt, height=tamanho_pt,
                preserveAspectRatio=True, mask="auto")
    c.save()
    camada.seek(0)
    sobreposta = PdfReader(camada).pages[0]

    escritor = PdfWriter()
    for i, pagina in enumerate(leitor.pages):
        if i == alvo:
            pagina.merge_page(sobreposta)
        escritor.add_page(pagina)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def _gravar_atomico(caminho: Path, dados: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        temporario.write_bytes(dados)
        os.replace(temporario, caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


# ───────────────────────────── processamento ─────────────────────────────

def _processar_planilha(planilha: dict, turmas: dict, *, servico, creds, rotulo: str, ano: str, destino_base: Path,
                        modo_teste: bool, substituir: bool, http_get, dormir, espera_s: float) -> dict:
    turma = planilha["turma"]
    alunos = alunos_da_turma(turmas, turma)
    if modo_teste:
        alunos = alunos[:1]
        print(f"[MODO TESTE] Só o primeiro aluno desta planilha: {alunos[0]['nome']}.")
    pid = planilha["planilha_id"]
    aba, gid = _nome_e_gid_da_aba(servico, pid, ABA_PADRAO)
    celula = f"'{aba}'!{CELULA_SELECAO}"
    print(f"\n=== {planilha['nome']} — {len(alunos)} aluno(s) — turma '{alunos[0]['turma'] if alunos else turma}' ===")

    resultado = {"gerados": 0, "pulados": 0, "falhas": []}
    antes = gs.ler_intervalo(pid, celula, formatado=True, servico=servico)
    valor_antes = str(antes[0][0]) if antes and antes[0] else ""

    try:
        url = montar_url_exportacao(pid, gid)
        for i, aluno in enumerate(alunos, 1):
            verificar_cancelamento()
            nome, cgm = aluno["nome"], aluno["cgm"]
            destino = _rco.caminho_do_parecer(destino_base, aluno["turma"], nome, cgm, aluno["n_chamada"])
            if destino.exists() and not substituir:
                print(f"[{i}/{len(alunos)}] {nome}: já existe, mantido.")
                resultado["pulados"] += 1
                continue
            if not cgm:
                resultado["falhas"].append({"turma": turma, "nome": nome, "motivo": "sem CGM em turmas.json (o QR precisa dele)"})
                continue
            print(f"[{i}/{len(alunos)}] Gerando {nome}...")
            try:
                gs.atualizar_intervalo(pid, celula, [[nome]], servico=servico)
                dormir(espera_s)
                pdf = exportar_pdf(url, creds, http_get=http_get, dormir=dormir)
                pdf = inserir_qr_no_pdf(pdf, gerar_qr_imagem(ano, aluno["n_chamada"], nome, aluno["turma"], cgm))
                _gravar_atomico(destino, pdf)
                resultado["gerados"] += 1
            except (gs.SheetsAutenticacaoErro, gs.SheetsAcessoErro):
                raise                                            # vale para todos os alunos: para aqui, com a explicação
            except (gs.SheetsErro, ExportacaoErro, ValueError, OSError) as exc:
                print(f"  [ERRO] {nome}: {exc}")
                resultado["falhas"].append({"turma": turma, "nome": nome, "motivo": str(exc)[:200]})
    finally:
        try:
            gs.atualizar_intervalo(pid, celula, [[valor_antes]], servico=servico)
        except (gs.GoogleErro, ValueError, OSError) as exc:      # não esconder o erro principal por causa disto
            print(f"  [AVISO] Não consegui devolver a célula {CELULA_SELECAO} ao valor de antes: {exc}")
    return resultado


def gerar_pareceres_infantil_planilha(bimestre, *, modo_teste: bool = False, substituir: bool = False, interativo: bool = True,
                                      abrir: Optional[Callable] = None, http_get: Optional[Callable] = None,
                                      dormir: Callable = time.sleep, espera_s: float = ESPERA_ATUALIZACAO_S) -> dict:
    """
    Gera os pareceres do Infantil IV/V a partir das planilhas ativas do cadastro. Devolve
    {"total", "gerados", "pulados", "falhas": [{"turma","nome","motivo"}], "pasta"}.
    ValueError se faltar algo (bimestre, credenciais, planilha no cadastro, turmas.json); SheetsErro se o Google recusar.
    """
    rotulo = rotulo_bimestre(bimestre)
    validar_pedido(bimestre)
    planilhas = planilhas_do_cadastro()
    turmas = _rco.carregar_turmas()
    ano = str(paths.ano_atual())
    destino_base = _rco.pasta_destino(ano, rotulo)
    destino_base.mkdir(parents=True, exist_ok=True)
    print(f"Ano letivo {ano} | {rotulo} | {len(planilhas)} planilha(s) | Pareceres serão salvos em: {destino_base}")

    print("Autenticando na API do Google...")
    creds, servico = abrir() if abrir else abrir_google(interativo=interativo)

    total = {"gerados": 0, "pulados": 0, "falhas": []}
    alunos_total = 0
    for planilha in planilhas:
        r = _processar_planilha(planilha, turmas, servico=servico, creds=creds, rotulo=rotulo, ano=ano, destino_base=destino_base,
                                modo_teste=modo_teste, substituir=substituir, http_get=http_get, dormir=dormir, espera_s=espera_s)
        total["gerados"] += r["gerados"]
        total["pulados"] += r["pulados"]
        total["falhas"] += r["falhas"]
        alunos_total += r["gerados"] + r["pulados"] + len(r["falhas"])

    print(f"\nConcluído: {total['gerados']} parecer(es) gerado(s), {total['pulados']} já existiam, {len(total['falhas'])} com problema.")
    for f in total["falhas"]:
        print(f"  - {f['turma']} | {f['nome']}: {f['motivo']}")
    return {"total": alunos_total, "gerados": total["gerados"], "pulados": total["pulados"], "falhas": total["falhas"],
            "pasta": str(destino_base)}

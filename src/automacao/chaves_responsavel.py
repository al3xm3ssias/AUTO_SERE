"""
chaves_responsavel.py — Gera e guarda a chave de acesso do responsável de cada aluno
=============================================================================
Versão integrada do antigo script avulso `gerar_chaves.py`. Para cada aluno
matriculado das turmas alvo da rematrícula, abre a ficha no SERE, gera a chave
de acesso do responsável, lê o CPF do responsável e grava os dois em

    dados/<ano>/chave_responsavel.json     (mesmo nome e mesmo formato do script avulso)

A rematrícula (src.automacao.rematricula) lê esse arquivo e, para o aluno que
tem chave salva, pula a etapa de gerar chave no SERE e entra direto na Área do
Aluno. Se a chave salva não funcionar (expirada, por exemplo), a rematrícula
gera uma nova na hora e atualiza este arquivo.

NÃO rematricula ninguém: só coleta CGM, nome, turma, CPF do responsável e chave.

Formato de cada registro (igual ao do script avulso):
    {"cgm", "nome", "turma", "data_nascimento", "cpf_responsavel", "chave", "timestamp"}

Segurança: o arquivo guarda CPF + chave de acesso em texto puro. Fica em
dados/<ano>/, que o .gitignore já bloqueia (dados/**/*.json). Não copie para
fora da máquina da escola.

Uso:
    from src.automacao.chaves_responsavel import gerar_chaves_via_login
    resumo = await gerar_chaves_via_login(modo_teste=True)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

from src.comum import paths
from src.comum.arquivos_json import (
    ArquivoJsonCorrompidoError,
    carregar_json,
    salvar_json_atomico,
)

ARQUIVO_CHAVES = "chave_responsavel.json"


class ChavesCorrompidasError(ArquivoJsonCorrompidoError):
    """chave_responsavel.json está ilegível. Ele NÃO é tocado."""


# ==========================================================
# PERSISTÊNCIA (funções puras; o caminho é resolvido na hora do uso,
# então a troca de ano letivo é respeitada sem recarregar o módulo)
# ==========================================================

def caminho_chaves() -> Path:
    return Path(paths.dados_ano_atual()) / ARQUIVO_CHAVES


def carregar_chaves() -> list:
    """Chaves salvas. Arquivo inexistente -> []. Ilegível -> ChavesCorrompidasError (arquivo intacto)."""
    return carregar_json(caminho_chaves(), list, tipo_esperado=list, erro=ChavesCorrompidasError)


def salvar_chaves(chaves: list) -> None:
    """Grava de forma atômica (a versão anterior permanece intacta se algo falhar)."""
    salvar_json_atomico(caminho_chaves(), chaves, indent=4)


def _cgm(valor) -> str:
    return str(valor if valor is not None else "").strip()


def buscar_chave(chaves, cgm) -> dict | None:
    """Registro do CGM na lista (ignora itens que não sejam registros), ou None."""
    alvo = _cgm(cgm)
    for item in chaves or []:
        if isinstance(item, dict) and _cgm(item.get("cgm")) == alvo:
            return item
    return None


def chave_utilizavel(registro, validade_horas: float | None = None, agora: datetime | None = None) -> bool:
    """
    True se o registro tem chave E CPF do responsável (sem os dois não dá para entrar na Área do Aluno).
    Com `validade_horas`, exige também timestamp válido e não mais velho que isso.
    Sem `validade_horas` a idade não é conferida (o prazo real da chave no SERE não é conhecido pelo sistema).
    """
    if not isinstance(registro, dict):
        return False
    if not str(registro.get("chave") or "").strip() or not str(registro.get("cpf_responsavel") or "").strip():
        return False
    if validade_horas is None:
        return True
    try:
        gerada_em = datetime.fromisoformat(str(registro.get("timestamp")))
    except (TypeError, ValueError):
        return False
    return (agora or datetime.now()) - gerada_em <= timedelta(hours=validade_horas)


def registrar_chave(chaves: list, aluno: dict, turma: str, chave: str, cpf: str, agora: datetime | None = None) -> dict:
    """Coloca (ou substitui, por CGM) o registro do aluno na lista em memória e o devolve."""
    registro = {
        "cgm": _cgm(aluno["cgm"]),
        "nome": aluno.get("Nome") or aluno.get("nome") or "",
        "turma": turma,
        "data_nascimento": aluno.get("Data Nasc.", aluno.get("data_nascimento", "")),
        "cpf_responsavel": cpf,
        "chave": chave,
        "timestamp": (agora or datetime.now()).isoformat(),
    }
    chaves[:] = [c for c in chaves if not (isinstance(c, dict) and _cgm(c.get("cgm")) == registro["cgm"])]
    chaves.append(registro)
    return registro


# ==========================================================
# GERAÇÃO NO SERE
# ==========================================================

async def _gerar_chave_do_aluno(page_sere, aluno):
    """
    Abre a ficha do aluno, gera a chave, lê o CPF e volta para a lista da turma.
    Devolve (chave, cpf, erro); erro None = deu certo. ErroReiniciarNavegador propaga.
    """
    from src.automacao import rematricula as rem

    print(f"\n{'=' * 70}")
    print(f"🔑 Gerando chave para: {aluno['Nome']} (CGM: {aluno['cgm']})")
    print(f"{'=' * 70}")

    chave, cpf, erro = await rem._abrir_ficha_gerar_chave(page_sere, aluno)
    if erro is None:
        await rem.voltar_para_turma(page_sere)
    return chave, cpf, erro


async def _processar_secao(sessao, secao, alunos, chaves, resumo, ja_na_secao=False) -> bool:
    """
    Gera a chave de cada aluno da seção na página da `sessao` (a mesma da rematrícula: um login só,
    continuando da tela atual), com a mesma recuperação (rem.processar_alunos_da_secao): reinicia a
    sessão em erro crítico; desiste do aluno após MAX_TENTATIVAS_NAVEGADOR e da seção após
    MAX_FALHAS_SESSAO falhas de sessão. Grava o arquivo a cada chave gerada. Devolve False se a seção foi abandonada.
    """
    from src.automacao import rematricula as rem

    def _concluir(aluno, resultado):
        chave, cpf, erro = resultado
        if erro is None:
            registrar_chave(chaves, aluno, secao, chave, cpf)
            salvar_chaves(chaves)
            resumo["geradas"] += 1
            print(f"✅ {aluno['Nome']} - CHAVE SALVA")
        else:
            resumo["falhas"].append({"cgm": aluno["cgm"], "nome": aluno["Nome"], "turma": secao, "erro": erro})
            print(f"⚠️ {aluno['Nome']} - {erro}")

    def _desistir(aluno, e):
        resumo["falhas"].append({
            "cgm": aluno["cgm"], "nome": aluno["Nome"], "turma": secao,
            "erro": f"Erro crítico após {rem.MAX_TENTATIVAS_NAVEGADOR} tentativas: {e}",
        })

    return await rem.processar_alunos_da_secao(
        sessao, secao, alunos, _gerar_chave_do_aluno, _concluir, _desistir, ja_na_secao=ja_na_secao
    )


async def gerar_chaves_via_login(
    modo_teste=False,
    turmas_alvo=None,
    login=None,
    senha=None,
    navegador="chromium",
    headless=False,
    regenerar=False,
    validade_horas=None,
):
    """
    Gera e salva a chave de acesso do responsável dos alunos matriculados. Devolve um resumo:
      {"total_chaves", "geradas", "falhas": [{cgm, nome, turma, erro}], "arquivo"}

    turmas_alvo:    nomes-base (padrão: TURMAS_ALVO da rematrícula); cada um pode ter várias seções.
    modo_teste:     1 aluno pendente por seção.
    regenerar:      gera de novo mesmo para quem já tem chave utilizável salva.
    validade_horas: se informado, chave salva há mais tempo que isso conta como vencida e é gerada de novo.

    Pula quem já tem chave utilizável (a menos que `regenerar`) e quem já está em rematriculas_sucesso.json
    (já rematriculado, não precisa de chave). Arquivo de chaves ou de sucessos ilegível aborta ANTES de abrir
    o navegador, sem alterar nada.
    """
    from src.automacao import rematricula as rem

    turmas_alvo = list(turmas_alvo) if turmas_alvo is not None else list(rem.TURMAS_ALVO)

    if login is None or senha is None:
        login_padrao, senha_padrao = rem._credenciais_padrao()
        login = login_padrao if login is None else login
        senha = senha_padrao if senha is None else senha

    print("\n" + "=" * 70)
    print("🔑 GERAÇÃO DE CHAVES DE ACESSO DO RESPONSÁVEL")
    if modo_teste:
        print("🧪 MODO TESTE - 1 aluno por seção")
    print("=" * 70)

    chaves = carregar_chaves()
    sucessos = rem.carregar_sucessos_anteriores()
    print(f"📊 Chaves já salvas: {len(chaves)}")

    resumo = {"geradas": 0, "falhas": []}

    async with async_playwright() as p:
        browser = await getattr(p, navegador).launch(headless=headless)
        sessao = rem.SessaoSere(browser, login, senha)  # UMA página logada no SERE para a execução inteira

        try:
            for turma_nome in turmas_alvo:
                print(f"\n{'=' * 70}\n📚 PROCESSANDO TURMA (base): {turma_nome}\n{'=' * 70}")

                if not await sessao.ir_para_lista_de_turmas():
                    continue
                secoes = await rem.listar_secao_turmas(sessao.page, turma_nome)

                if not secoes:
                    print(f"\n⚠️ Nenhuma seção encontrada para '{turma_nome}'")
                    continue

                for secao in secoes:
                    print(f"\n--- Iniciando seção: {secao} ---")

                    if not await sessao.ir_para_lista_de_turmas():
                        continue
                    if not await rem.selecionar_turma(sessao.page, secao):
                        print(f"\n⚠️ Seção '{secao}' não encontrada ao tentar selecionar")
                        continue
                    alunos = await rem.obter_alunos_matriculados(sessao.page)

                    if not alunos:
                        print(f"\n⚠️ Nenhum aluno matriculado em '{secao}'")
                        continue

                    pendentes = [
                        a for a in alunos
                        if not rem.aluno_ja_processado(a, sucessos)
                        and (regenerar or not chave_utilizavel(buscar_chave(chaves, a["cgm"]), validade_horas))
                    ]
                    if modo_teste:
                        pendentes = pendentes[:1]

                    if not pendentes:
                        print(f"✅ Todos os alunos de '{secao}' já têm chave (ou já foram rematriculados)!")
                        continue

                    # a página já está na lista de alunos da seção: continua dali, sem logar de novo
                    await _processar_secao(sessao, secao, pendentes, chaves, resumo, ja_na_secao=True)

        finally:
            await sessao.fechar()
            await browser.close()

    salvar_chaves(chaves)

    print("\n\n" + "=" * 70)
    print("📊 RESUMO FINAL")
    print("=" * 70)
    print(f"🔑 Chaves geradas agora: {resumo['geradas']}")
    print(f"🔑 Total de chaves salvas: {len(chaves)}")
    if resumo["falhas"]:
        print(f"⚠️ Alunos sem chave ({len(resumo['falhas'])}):")
        for f in resumo["falhas"]:
            print(f"  - {f['nome']} (CGM: {f['cgm']}, {f['turma']}): {f['erro']}")
    print(f"📁 Arquivo: {caminho_chaves()}")
    print("=" * 70 + "\n")

    return {
        "total_chaves": len(chaves),
        "geradas": resumo["geradas"],
        "falhas": resumo["falhas"],
        "arquivo": caminho_chaves(),
    }

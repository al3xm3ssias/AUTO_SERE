"""
ano_letivo.py — trocar o ano letivo SEM reiniciar o programa
============================================================
Pedido do usuário (25/10/2026): "não queria ter que executar o PARAR_AUTO_SERE para voltar e carregar os dados do
ano atual ou de outros anos letivos".

POR QUE ISSO NÃO ERA TRIVIAL
  18 módulos calculam a pasta do ano UMA VEZ, quando são importados (ex.: `_DADOS = dados_ano_atual()`,
  `TURMAS_JSON = _DADOS / "turmas.json"`). Trocar só o ano em paths.ano_atual() deixaria as telas num ano e esses
  scripts gravando no outro. A solução é fazer esses módulos serem importados DE NOVO depois da troca.

COMO A TROCA FUNCIONA (trocar_ano)
  1. grava a escolha em config/config_usuario.json e muda o ano em uso no processo (paths.definir_ano_do_processo);
  2. descarrega de sys.modules os módulos que fixam o ano (MODULOS_COM_ANO_FIXO) e os que os importam logo ao
     carregar (MODULOS_QUE_DEPENDEM) e APAGA a referência que o pacote pai guarda (`src.automacao.turmas`): sem isso,
     `from src.automacao import turmas` devolveria o módulo velho;
  3. importa de novo, na hora, os que estavam carregados — se algum falhar, a troca é DESFEITA (ano e configuração
     voltam) e o erro é explicado. Os que não estavam carregados serão importados, já no ano novo, quando alguém usar.
  A camada web (rotas, registro de automações, CLI) importa esses módulos só na hora do uso, por isso não guarda cópia
  velha. A rota recusa trocar com uma automação em execução (ela segura referências ao módulo antigo).

ESTAS LISTAS PRECISAM ESTAR COMPLETAS: tests/test_ano_letivo_troca.py varre o código-fonte e FALHA se algum módulo novo
passar a fixar o ano na importação sem estar aqui (ou a importar um que fixa).
"""
from __future__ import annotations

import importlib
import sys
import threading

from src.comum import configuracao, paths

# Módulos que calculam dados/<ano> (ou o próprio ano) no momento da importação.
MODULOS_COM_ANO_FIXO: tuple[str, ...] = (
    "src.automacao.alunos",
    "src.automacao.alunos_completo",
    "src.automacao.coleta_emails",
    "src.automacao.funcionarios",
    "src.automacao.gerar_pastas",
    "src.automacao.processo_transferidos",
    "src.automacao.rematricula_persistencia",
    "src.automacao.sere_2026",
    "src.automacao.servidores",
    "src.automacao.sisreg",
    "src.automacao.termo_ciencia",
    "src.automacao.turmas",
    "src.comum.cep_api",
    "src.relatorios.analisa_arquivos_sere",
    "src.relatorios.analisa_documentos_pc",
    "src.relatorios.cruzar_documentos",
    "src.relatorios.mapear_pastas_alunos",
    "src.relatorios.mascarar",
)

# Módulos que importam algum dos de cima já no carregamento (guardariam a cópia velha).
MODULOS_QUE_DEPENDEM: tuple[str, ...] = (
    "src.automacao.rematricula_sere",
)

_TRAVA = threading.Lock()


class TrocaDeAnoErro(Exception):
    """A troca não pôde ser feita (e o ano anterior foi mantido)."""


def _carregados() -> list[str]:
    return [n for n in (*MODULOS_COM_ANO_FIXO, *MODULOS_QUE_DEPENDEM) if n in sys.modules]


def descarregar(nomes) -> None:
    """Tira os módulos de sys.modules E a referência que o pacote pai guarda (senão `from pacote import modulo` volta o velho)."""
    for nome in nomes:
        sys.modules.pop(nome, None)
        pai, _, filho = nome.rpartition(".")
        modulo_pai = sys.modules.get(pai)
        if modulo_pai is not None and hasattr(modulo_pai, filho):
            try:
                delattr(modulo_pai, filho)
            except AttributeError:
                pass


def recarregar(nomes) -> None:
    for nome in nomes:
        importlib.import_module(nome)


def trocar_ano(novo=None) -> dict:
    """
    Põe o programa inteiro no ano `novo` (ex.: "2025"); None = automático (ano do calendário). Vale na hora.
    Devolve {"antigo", "novo", "trocou", "modulos"}. ValueError se o ano for inválido; TrocaDeAnoErro se não der
    (ano fixado por variável de ambiente, ou falha ao carregar os módulos: nesse caso o ano antigo é mantido).
    O chamador deve garantir que NENHUMA automação esteja rodando (a rota faz isso).
    """
    with _TRAVA:
        if paths.ano_fixado_por_ambiente():
            raise TrocaDeAnoErro("O ano está fixado pela variável de ambiente AUTO_SERE_ANO_BASE, que manda sobre esta "
                                 "configuração. Remova a variável para poder escolher o ano.")
        antigo = str(paths.ano_atual())
        alvo = str(paths.ano_do_calendario()) if novo is None else configuracao.validar_ano_letivo(novo)
        escolha_anterior = configuracao.ano_letivo_configurado()

        if novo is None:
            configuracao.usar_ano_letivo_automatico()
        else:
            configuracao.definir_ano_letivo(alvo)
        if alvo == antigo:                                       # mesmo ano: só a escolha mudou, nada a recarregar
            paths.definir_ano_do_processo(None if novo is None else alvo)
            return {"antigo": antigo, "novo": alvo, "trocou": False, "modulos": 0}

        processo_anterior = paths.definir_ano_do_processo(None if novo is None else alvo)
        carregados = _carregados()
        try:
            descarregar(carregados)
            recarregar(carregados)
        except Exception as exc:                                 # noqa: BLE001 — qualquer falha desfaz a troca
            try:                                                  # volta tudo como estava
                if escolha_anterior:
                    configuracao.definir_ano_letivo(escolha_anterior)
                else:
                    configuracao.usar_ano_letivo_automatico()
            except Exception:                                    # noqa: BLE001
                pass
            paths.definir_ano_do_processo(processo_anterior)
            try:
                descarregar(carregados)
                recarregar(carregados)
            except Exception:                                    # noqa: BLE001 — pior caso: ficam para o próximo uso
                pass
            raise TrocaDeAnoErro(f"Não consegui carregar o ano {alvo} ({type(exc).__name__}: {exc}). "
                                 f"O ano {antigo} foi mantido.") from exc
        return {"antigo": antigo, "novo": alvo, "trocou": True, "modulos": len(carregados)}

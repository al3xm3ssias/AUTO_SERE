"""
cli.py — executa qualquer automação do AUTO SERE pela linha de comando
=======================================================================
Usa o MESMO registro (src/comum/registro_scripts.py) e as MESMAS opções da tela (turma, matriculados,
transferidos, CGM, teste, erros, debug), com a mesma validação e a mesma prévia. Assim, tudo o que dá para
fazer clicando também dá para fazer num agendador de tarefas ou num .bat.

    python -m src.comum.cli listar
    python -m src.comum.cli SCRIPT --ajuda                      # opções que aquele script aceita
    python -m src.comum.cli SCRIPT [opções] --simular           # mostra o que seria processado, sem executar
    python -m src.comum.cli SCRIPT [opções] [--confirmo]        # executa

Exemplos:
    python -m src.comum.cli analisa_sere --turma 5 --matriculados --transferidos
    python -m src.comum.cli validar --turma "3º Ano Integral" --teste
    python -m src.comum.cli aluno --cgm 1234567890,1234567891 1234567892 --confirmo
    python -m src.comum.cli alunos --modo completo --rapido
    python -m src.comum.cli backup

Códigos de saída: 0 = concluído · 1 = a execução falhou · 2 = pedido inválido/não confirmado.

Observações:
  • Scripts que alteram algo no SERE pedem confirmação (digitar SIM) ou o parâmetro --confirmo; com --teste não pedem.
  • As flags guardadas na aba "Configuração" da tela NÃO valem aqui: só o que você escrever na linha de comando.
  • Não rode a mesma coleta pela tela e por aqui ao mesmo tempo (a trava contra duplicidade é por processo).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional

from src.comum import opcoes_execucao as oe
from src.comum import paths
from src.comum import registro_scripts as reg

class _Nomes(dict):
    """Nomes de exibição = os da lista de automações da tela (uma única fonte). Carregado só quando preciso,
    para o executor de linha de comando não importar o Flask à toa."""

    def _carregar(self):
        if not self:
            from src.web.api.rotas import AUTOMACOES_DISPONIVEIS
            self.update({i["chave"]: i["nome"] for i in AUTOMACOES_DISPONIVEIS})

    def get(self, chave, padrao=None):
        self._carregar()
        return super().get(chave, padrao)

    def __getitem__(self, chave):
        self._carregar()
        return super().__getitem__(chave)


NOMES = _Nomes()


def carregar_turmas() -> dict:
    """Conteúdo de turmas.json do ano atual ({} se não existir)."""
    arquivo = paths.dados_ano_atual() / "turmas.json"
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _flag(nome: str) -> str:
    return "--" + nome.replace("_", "-")


def _montar_parser_do_script(sub, script: reg.Script) -> argparse.ArgumentParser:
    r = set(script.recursos)
    p = sub.add_parser(script.chave, help=NOMES.get(script.chave, script.chave), add_help=False,
                       description=NOMES.get(script.chave, script.chave),
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ajuda", "-h", "--help", action="help", help="mostra esta ajuda")
    oe.adicionar_argumentos(
        p, turma=oe.RECURSO_TURMA in r, situacao=oe.RECURSO_SITUACAO in r, cgm=oe.RECURSO_CGM in r,
        teste=oe.RECURSO_TESTE in r, erros=oe.RECURSO_ERROS in r, debug=oe.RECURSO_DEBUG in r)
    for campo in script.extras():
        tipo, nome = campo.get("tipo"), campo.get("nome")
        if not nome:
            continue                                      # campos de pasta: valem pela configuração, não por argumento
        if tipo == "select":
            valores = [str(o["valor"]) for o in campo["opcoes"]]
            ajuda = campo["label"] + ". Valores: " + ", ".join(
                f"{o['valor']}" if len(valores) > 6 else f"{o['valor']} ({o['texto']})" for o in campo["opcoes"])
            p.add_argument(_flag(nome), dest=nome, default=campo.get("padrao"), metavar=nome.upper(), help=ajuda)
        elif tipo == "caixa":
            p.add_argument(_flag(nome), dest=nome, action="store_true", help=campo["label"])
        elif tipo == "texto":
            p.add_argument(_flag(nome), dest=nome, default=None, metavar=nome.upper(), help=campo["label"])
    p.add_argument("--simular", action="store_true", help="só mostra o que seria processado e o que seria executado")
    if script.confirmar:
        p.add_argument("--confirmo", action="store_true", help="confirma a execução sem perguntar (ex.: agendador de tarefas)")
    return p


def montar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m src.comum.cli", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", metavar="SCRIPT|listar", required=True)
    sub.add_parser("listar", help="lista as automações disponíveis")
    for chave in sorted(reg.REGISTRO):
        _montar_parser_do_script(sub, reg.REGISTRO[chave])
    return ap


def _payload_do_namespace(script: reg.Script, ns: argparse.Namespace) -> dict:
    """O mesmo JSON que a tela envia."""
    r = set(script.recursos)
    p: dict = {}
    if oe.RECURSO_TURMA in r:
        if ns.turma is not None and not ns.turma:
            raise ValueError("--turma precisa de ao menos um valor (ex.: --turma 5 ou --turma \"3º Ano Integral\").")
        p["turmas"] = list(ns.turma or [])
    if oe.RECURSO_SITUACAO in r:
        p["matriculados"] = bool(ns.matriculados) or not ns.transferidos          # sem nenhuma flag = só matriculados
        p["transferidos"] = bool(ns.transferidos)
    if oe.RECURSO_CGM in r:
        p["cgms_texto"] = " ".join(ns.cgm or [])
    if oe.RECURSO_TESTE in r:
        p["modo_teste"] = bool(ns.teste)
    if oe.RECURSO_ERROS in r:
        p["erros"] = bool(ns.erros)
    if oe.RECURSO_DEBUG in r:
        p["debug"] = bool(ns.debug)
    for campo in script.extras():
        nome = campo.get("nome")
        if nome and campo.get("tipo") in ("select", "caixa", "texto"):
            valor = getattr(ns, nome, None)
            if campo["tipo"] == "select" and valor is not None and str(valor) not in {str(o["valor"]) for o in campo["opcoes"]}:
                raise ValueError(f"Valor inválido para {_flag(nome)}: '{valor}'.")
            if valor is not None:
                p[nome] = valor
    return p


def _resumo_kwargs(kwargs: dict) -> str:
    def curto(v):
        if isinstance(v, dict):
            return f"<{len(v)} itens>"
        if isinstance(v, (list, tuple)) and len(v) > 6:
            return f"[{len(v)} itens]"
        return repr(v)
    return ", ".join(f"{k}={curto(v)}" for k, v in kwargs.items()) or "sem argumentos"


def _confirmar(script: reg.Script, previa: Optional[str], args) -> bool:
    print(f"ATENÇÃO: {script.aviso_confirmacao or 'esta automação altera dados no SERE.'}")   # a prévia já foi mostrada acima
    if getattr(args, "confirmo", False):
        return True
    if sys.stdin is None or not sys.stdin.isatty():
        print("Sem terminal para perguntar: repita o comando com --confirmo (ou use --teste / --simular).", file=sys.stderr)
        return False
    return input('Digite SIM para continuar: ').strip().upper() == "SIM"


def _executar_plano(plano: reg.Plano) -> int:
    if plano.tipo == "gui":
        execucao = plano.funcao(callback=print, **plano.kwargs)
        execucao.aguardar(None)
        if getattr(execucao.status, "value", execucao.status) == "concluido":
            return 0
        print(f"A execução terminou com status: {getattr(execucao.status, 'value', execucao.status)}", file=sys.stderr)
        return 1
    if plano.tipo == "coroutine":
        asyncio.run(plano.funcao(**plano.kwargs))
        return 0
    plano.funcao(**plano.kwargs)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = montar_parser().parse_args(argv)
    if args.comando == "listar":
        for chave in sorted(reg.REGISTRO):
            s = reg.REGISTRO[chave]
            marcas = ", ".join(s.recursos) or "—"
            print(f"{chave:<22} {NOMES.get(chave, ''):<34} recursos: {marcas}{'  [pede confirmação]' if s.confirmar else ''}")
        return 0

    script = reg.REGISTRO[args.comando]
    turmas = carregar_turmas()
    try:
        if script.usa_turmas_json and not turmas:
            raise ValueError("Ainda não existe turmas.json: execute primeiro  python -m src.comum.cli turmas")
        payload = _payload_do_namespace(script, args)
        nomes = script.turmas_de() if script.turmas_de else list(turmas)
        opcoes = oe.opcoes_do_payload(payload, script.recursos, nomes, cgm_obrigatorio=script.cgm_obrigatorio)
        if script.validar_extras:
            script.validar_extras(payload)
        plano = script.planejar(opcoes, payload, turmas, {"args_flags": []})
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2

    previa = None
    if script.tem_selecao_de_alunos and turmas:
        sel = oe.selecionar_alunos(turmas, turmas=opcoes.turmas, matriculados=opcoes.matriculados,
                                   transferidos=opcoes.transferidos, cgms=opcoes.cgms)
        previa = oe.descrever_selecao(sel, len(opcoes.cgms))
    elif script.turmas_de is not None:
        previa = "Turmas: " + ", ".join(opcoes.turmas or script.turmas_de()) + "."

    nome_funcao = f"{plano.funcao.__module__}.{plano.funcao.__name__}"
    print(f"Automação: {NOMES.get(script.chave, script.chave)} ({script.chave})")
    if previa:
        print(f"Prévia:    {previa}")
    if args.simular:
        print(f"Executaria: {nome_funcao}({_resumo_kwargs(plano.kwargs)})  [{plano.tipo}]")
        print("(simulação: nada foi executado)")
        return 0

    from src.comum import paths as _paths
    if _paths.somente_consulta():
        print(f"Somente consulta: o ano letivo {_paths.ano_atual()} está sendo visualizado e não pode ser alterado. "
              "Volte ao ano atual (Configurações → Ano letivo) antes de executar.", file=sys.stderr)
        return 2

    if script.confirmar and not opcoes.modo_teste and not _confirmar(script, previa, args):
        print("Cancelado: nada foi executado.", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if plano.log_inicial:
        print(plano.log_inicial)
    try:
        # Sem interface web: perguntas da automação (ex.: código 2FA do RCO) viram input() no terminal.
        from src.comum import entrada_usuario
        entrada_usuario.usar_terminal(True)
        try:
            return _executar_plano(plano)
        finally:
            entrada_usuario.usar_terminal(False)
    except KeyboardInterrupt:
        print("\nInterrompido.", file=sys.stderr)
        return 130
    except Exception as exc:                                # noqa: BLE001 — qualquer falha vira mensagem + código 1
        print(f"ERRO: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

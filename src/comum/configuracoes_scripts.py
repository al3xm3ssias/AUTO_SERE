"""
configuracoes_scripts.py — mapa das configurações de cada script de automação
=============================================================================
A tela de cada automação mostra, junto de "Executar", **todas** as configurações que aquele script usa:

  1. as opções desta execução (turma, situação, CGM, teste, erros, debug e os campos próprios) —
     já vêm de `registro_scripts.Script.recursos` e `Script.extras`;
  2. as opções guardadas do script (flags, ex.: --rapido) — `configuracao.flags_automacao`;
  3. as configurações do sistema que o script lê (pasta de digitalização, data de corte, credenciais,
     unidade escolar, planilhas...) — o que este módulo cataloga.

Cada configuração do sistema é declarada UMA vez em `CATALOGO` (id, rótulo, de onde vem o valor e em qual
linha da tela Configurações ela se altera). Cada script diz quais usa em `Script.configs`
(src/comum/registro_scripts.py). Um teste exige que todo script registrado declare as suas — script novo
sem mapa não passa nos testes.

Nada sigiloso sai daqui: credenciais aparecem só como "configurada" / "não configurada".
Aqui não há Flask nem rede.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class ConfigSistema:
    id: str
    rotulo: str
    descricao: str
    ler: Callable[[], tuple[bool, str]]       # → (definida?, texto para mostrar)
    tela: Optional[str] = None                # valor de data-config da linha em Configurações (None = não editável lá)


def _credencial(var_login: str, padrao_login: str, var_senha: str, padrao_senha: str) -> Callable[[], tuple[bool, str]]:
    def ler() -> tuple[bool, str]:
        from src.comum import credenciais as c
        login, senha = getattr(c, var_login), getattr(c, var_senha)
        ok = bool(login) and bool(senha) and login != padrao_login and senha != padrao_senha
        return ok, "configurada" if ok else "não configurada"
    return ler


def _ler_ano() -> tuple[bool, str]:
    from src.comum import paths
    return True, str(paths.ano_atual())


def _ler_pasta_digitalizacao() -> tuple[bool, str]:
    from src.comum import configuracao as c
    pasta = c.pasta_digitalizacao()
    if pasta is None:
        return False, "não definida"
    sufixo = "" if c.pasta_digitalizacao_personalizada() else " (padrão do ano)"
    return pasta.is_dir(), f"{pasta}{sufixo}" + ("" if pasta.is_dir() else " — a pasta não existe")


def _ler_pasta_modelos() -> tuple[bool, str]:
    from src.comum import configuracao as c
    pasta = c.pasta_modelos()
    if pasta is None:
        return False, "não definida"
    return pasta.is_dir(), str(pasta) + ("" if pasta.is_dir() else " — a pasta não existe")


def _ler_data_corte() -> tuple[bool, str]:
    from src.comum import configuracao as c
    data = c.data_corte_transferidos().strftime("%d/%m/%Y")
    return True, data if c.data_corte_transferidos_configurada() else f"{data} (padrão)"


def _ler_observacao() -> tuple[bool, str]:
    from src.comum import configuracao as c
    texto = c.observacao_historico().strip()
    return bool(texto), (texto[:120] + "…" if len(texto) > 120 else texto) or "ainda não usada"


def _ler_escola() -> tuple[bool, str]:
    from src.comum import escola
    nome = escola.nome()
    return bool(nome) and escola.configurada(), nome or "não configurada"


def _ler_cgm_upload() -> tuple[bool, str]:
    from src.comum import configuracao as c
    cgms = c.cgm_upload()
    return bool(cgms), f"{len(cgms)} CGM(s) salvo(s)" if cgms else "nenhum CGM salvo"


def _ler_planilhas() -> tuple[bool, str]:
    from src.comum import planilhas_registro as r
    total = r.listar(status="ativa", limite=1)["total"]
    return total > 0, f"{total} planilha(s) ativa(s) cadastrada(s)" if total else "nenhuma planilha cadastrada"


def _ler_google() -> tuple[bool, str]:
    from src.comum import google_auth
    try:
        caminho = google_auth.caminho_credenciais()
    except Exception:                       # noqa: BLE001 — só informa o estado, nunca derruba a tela
        return False, "não configurada"
    return bool(caminho) and caminho.exists(), "arquivo de credenciais encontrado" if (caminho and caminho.exists()) else "arquivo de credenciais não encontrado"


def _ler_email() -> tuple[bool, str]:
    from src.comum import credenciais as c
    ok = c.EMAIL_REMETENTE != "email@exemplo.com" and c.EMAIL_SENHA_APP != "senha_app_email"
    return ok, "configurado" if ok else "não configurado"


def _ler_navegador() -> tuple[bool, str]:
    from src.comum import configuracao as c
    from src.comum.navegador import ROTULOS
    escolhido = c.navegador_padrao()
    return True, (f"{ROTULOS[escolhido]} (para todos os scripts)" if escolhido
                  else "Automático (cada script abre o navegador para o qual foi feito)")


def _ler_raio() -> tuple[bool, str]:
    from src.comum.cep_api import RAIO_KM_PADRAO
    return True, f"{RAIO_KM_PADRAO:g} km (padrão do sistema; pode ser trocado no campo da execução)"


CATALOGO: dict[str, ConfigSistema] = {c.id: c for c in (
    ConfigSistema("ano_letivo", "Ano letivo", "Pasta dados/<ano> em que o script lê e grava.", _ler_ano, "ano_letivo"),
    ConfigSistema("credenciais_sere", "Login do SERE", "Usuário e senha para entrar no SERE.",
                  _credencial("LOGIN", "cpf", "SENHA", "senha_sere"), "senha_sere"),
    ConfigSistema("credenciais_rco", "Login do RCO", "Usuário e senha do RCO (em branco = os mesmos do SERE).",
                  _credencial("LOGIN_RCO", "cpf", "SENHA_RCO", "senha_sere"), "senha_rco"),
    ConfigSistema("credenciais_prematricula", "Login da pré-matrícula", "Usuário e senha do portal da pré-matrícula.",
                  _credencial("MATRICULA_PREMATRICULA", "matricula", "SENHA_PREMATRICULA", "senha_prematricula"), "senha_prematricula"),
    ConfigSistema("email_envio", "E-mail de envio (Gmail)", "Remetente e senha de aplicativo para enviar e-mails.", _ler_email, "chave_gmail"),
    ConfigSistema("escola", "Unidade escolar", "Nome, endereço e CEP da escola.", _ler_escola, "escola"),
    ConfigSistema("pasta_digitalizacao", "Pasta de digitalização", "Onde ficam os documentos escaneados dos alunos.",
                  _ler_pasta_digitalizacao, "pasta_digitalizacao"),
    ConfigSistema("pasta_modelos", "Pasta de modelos", "Onde ficam os modelos .docx (termos, pareceres).", _ler_pasta_modelos, "modelos_parecer"),
    ConfigSistema("data_corte_transferidos", "Data de corte dos transferidos",
                  "O processo automático vale para transferidos a partir dessa data.", _ler_data_corte, "data_corte_transferidos"),
    ConfigSistema("observacao_historico", "Texto da observação do histórico",
                  "Último texto usado na ação Alterar do histórico dos transferidos.", _ler_observacao),
    ConfigSistema("cgm_upload", "CGMs salvos para envio", "Lista de CGMs guardada para os modos por aluno.", _ler_cgm_upload),
    ConfigSistema("planilhas_drive", "Planilhas do Drive", "Planilhas cadastradas em Planilhas do Drive.", _ler_planilhas, "planilhas_google"),
    ConfigSistema("google_credenciais", "Acesso ao Google", "Arquivo de credenciais da API do Google (Sheets).", _ler_google),
    ConfigSistema("navegador", "Navegador das automações", "Chrome, Firefox ou automático (cada script usa o seu).",
                  _ler_navegador, "navegador"),
    ConfigSistema("raio_cep", "Raio de atendimento", "Distância máxima aluno–escola usada pelo script de CEP.", _ler_raio),
)}


def descrever(ids: tuple[str, ...]) -> list[dict]:
    """As configurações do sistema que um script usa, já com o valor atual (para a tela)."""
    saida = []
    for id_ in ids:
        item = CATALOGO[id_]
        try:
            definida, valor = item.ler()
        except Exception as exc:            # noqa: BLE001 — uma leitura quebrada não pode derrubar a tela inteira
            definida, valor = False, f"não foi possível ler ({type(exc).__name__})"
        saida.append({"id": item.id, "rotulo": item.rotulo, "descricao": item.descricao,
                      "definida": bool(definida), "valor": valor, "tela": item.tela})
    return saida

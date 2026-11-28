"""
usuarios.py — o cadastro de usuários (credenciais/usuarios.json)
=================================================================
Guarda, por usuário: nome de usuário, nome, perfil, o HASH da senha (nunca a senha), se está ativo, se precisa trocar a senha
no próximo acesso e os contadores do bloqueio por tentativas erradas.

Perfis (do menor para o maior poder):
    consulta   só vê (telas, tabelas, relatórios); não executa nem altera nada
    operador   o uso do dia a dia: executa as automações, edita registros, envia mensagens
    admin      tudo do operador + usuários, senhas e integrações (SERE, Gmail, Google, WhatsApp), ano letivo, dados de teste

Perfil independente (fora dessa escada):
    pedagoga   só consulta (Turmas, Alunos, Encaminhamentos SUS) e só executa as coletas `turmas` e `alunos` (que apenas leem do
               SERE). Permissões próprias, em src/seguranca/politica.py; o que não está lá é negado.

Regras que este módulo garante, em qualquer porta de entrada (tela, instalador, linha de comando):
  • o PRIMEIRO usuário criado é administrador, e só se não houver nenhum usuário;
  • nunca fica sem pelo menos 1 administrador ATIVO (não dá para apagar, desativar ou rebaixar o último);
  • 5 senhas erradas seguidas bloqueiam o usuário por 15 min; a cada novo bloqueio o tempo dobra (até 24 h);
  • a resposta de uma entrada recusada é sempre a mesma, exista o usuário ou não, e demora o mesmo tempo;
  • um arquivo ilegível NUNCA é tratado como "sem usuários" (isso abriria a tela de criação do administrador a qualquer um).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.comum import paths

from . import auditoria, politica, senhas

PERFIS = ("consulta", "operador", "admin", politica.PEDAGOGA)
NIVEL = politica.NIVEL                      # só a escada hierárquica: a Pedagoga fica de fora de propósito (ver politica.py)
ROTULO_PERFIL = {"consulta": "Consulta", "operador": "Operador", "admin": "Administrador", politica.PEDAGOGA: "Pedagoga"}

RE_USUARIO = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MAX_FALHAS = 5
BLOQUEIO_BASE_S = 15 * 60
BLOQUEIO_MAX_S = 24 * 3600

_LOCK = threading.RLock()


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(texto) if texto else None
    except (TypeError, ValueError):
        return None


class ErroUsuarios(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""

    def __init__(self, mensagem: str, problemas: list[str] | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.problemas = problemas or []


class ArquivoIlegivel(ErroUsuarios):
    pass


class FalhaLogin(Exception):
    """Entrada recusada. `motivo` é só para a auditoria (nunca vai ao navegador): desconhecido, bloqueado, inativo, senha."""

    def __init__(self, motivo: str, usuario: str = ""):
        super().__init__(motivo)
        self.motivo = motivo
        self.usuario = usuario


@dataclass(frozen=True)
class Usuario:
    id: str
    usuario: str
    nome: str
    perfil: str
    ativo: bool
    trocar_senha: bool
    criado_em: str
    ultimo_login: str | None
    bloqueado_ate: str | None
    senha_alterada_em: str | None

    @property
    def bloqueado(self) -> bool:
        ate = _parse(self.bloqueado_ate)
        return bool(ate and ate > _agora())

    def tem_perfil(self, minimo: str) -> bool:
        """Só para a escada consulta < operador < admin. A Pedagoga NUNCA passa aqui (nível 0): o que ela pode está em `pode`."""
        return NIVEL.get(self.perfil, 0) >= NIVEL.get(minimo, 99)

    def pode(self, metodo: str, caminho: str) -> bool:
        """Este usuário pode fazer este método neste caminho? É a pergunta que o guarda de toda requisição faz."""
        return politica.permite(self.perfil, metodo, caminho)

    def publico(self) -> dict:
        return {"id": self.id, "usuario": self.usuario, "nome": self.nome, "perfil": self.perfil,
                "perfil_rotulo": ROTULO_PERFIL.get(self.perfil, self.perfil), "ativo": self.ativo,
                "trocar_senha": self.trocar_senha, "criado_em": self.criado_em, "ultimo_login": self.ultimo_login,
                "bloqueado": self.bloqueado, "bloqueado_ate": self.bloqueado_ate if self.bloqueado else None,
                "senha_alterada_em": self.senha_alterada_em}


def _de_registro(r: dict) -> Usuario:
    return Usuario(id=r["id"], usuario=r["usuario"], nome=r.get("nome") or r["usuario"], perfil=r.get("perfil", "consulta"),
                   ativo=bool(r.get("ativo", True)), trocar_senha=bool(r.get("trocar_senha", False)), criado_em=r.get("criado_em", ""),
                   ultimo_login=r.get("ultimo_login"), bloqueado_ate=r.get("bloqueado_ate"), senha_alterada_em=r.get("senha_alterada_em"))


# ───────────────────────────── arquivo ─────────────────────────────

def _arquivo():
    return paths.CREDENCIAIS_DIR / "usuarios.json"


def _copia():
    return paths.CREDENCIAIS_DIR / "usuarios.json.bak"


def _ler() -> dict:
    arq = _arquivo()
    if not arq.exists():
        if _copia().exists():
            raise ArquivoIlegivel("O arquivo de usuários (credenciais/usuarios.json) sumiu, mas existe a cópia usuarios.json.bak. "
                                  "Restaure a cópia (renomeie para usuarios.json) ou use a recuperação: python -m src.seguranca redefinir-senha.")
        return {"versao": 1, "usuarios": []}
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or not isinstance(dados.get("usuarios"), list):
            raise ValueError("formato")
        for r in dados["usuarios"]:
            if not isinstance(r, dict) or not r.get("id") or not r.get("usuario"):
                raise ValueError("registro")
        return dados
    except (OSError, ValueError) as exc:
        raise ArquivoIlegivel("O arquivo de usuários (credenciais/usuarios.json) está ilegível ou foi alterado de forma inválida. "
                              "Por segurança ninguém entra até isso ser resolvido: restaure usuarios.json.bak ou use a recuperação "
                              "(python -m src.seguranca redefinir-senha).") from exc


def _gravar(dados: dict) -> None:
    arq = _arquivo()
    arq.parent.mkdir(parents=True, exist_ok=True)
    if arq.exists():
        try:
            _copia().write_bytes(arq.read_bytes())
            try:
                os.chmod(_copia(), 0o600)
            except OSError:
                pass
        except OSError:
            pass
    tmp = arq.with_name(arq.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, arq)
    try:
        os.chmod(arq, 0o600)
    except OSError:
        pass


def estado() -> str:
    """'sem_usuarios' (instalação: criar o administrador), 'ok' ou 'ilegivel' (bloqueia tudo)."""
    try:
        return "ok" if _ler()["usuarios"] else "sem_usuarios"
    except ArquivoIlegivel:
        return "ilegivel"


def existe_algum() -> bool:
    return estado() != "sem_usuarios"


# ───────────────────────────── validação ─────────────────────────────

def normalizar_usuario(texto: str) -> str:
    return (texto or "").strip().lower()


def _validar_usuario(usuario: str) -> str:
    u = normalizar_usuario(usuario)
    if not RE_USUARIO.match(u):
        raise ErroUsuarios("O usuário deve ter de 3 a 32 caracteres: letras minúsculas sem acento, números, ponto, hífen ou sublinhado "
                           "(e começar com letra ou número).")
    return u


def _validar_nome(nome: str, padrao: str) -> str:
    n = " ".join((nome or "").split())
    if not n:
        return padrao
    if len(n) > 80 or any(ord(c) < 32 for c in n):
        raise ErroUsuarios("O nome deve ter até 80 caracteres, sem caracteres de controle.")
    return n


def _validar_perfil(perfil: str) -> str:
    if perfil not in PERFIS:
        raise ErroUsuarios("Perfil inválido. Use: consulta, operador, admin ou pedagoga.")
    return perfil


def _checar_senha(senha: str, usuario: str, nome: str) -> None:
    try:
        senhas.validar_politica(senha, usuario, nome)
    except senhas.SenhaInvalida as exc:
        raise ErroUsuarios("A senha não é forte o bastante.", exc.problemas) from exc


def _achar(dados: dict, *, id: str | None = None, usuario: str | None = None) -> dict | None:
    for r in dados["usuarios"]:
        if (id is not None and r["id"] == id) or (usuario is not None and r["usuario"] == usuario):
            return r
    return None


def _admins_ativos(dados: dict) -> list[dict]:
    return [r for r in dados["usuarios"] if r.get("perfil") == "admin" and r.get("ativo", True)]


# ───────────────────────────── consulta ─────────────────────────────

def listar() -> list[Usuario]:
    with _LOCK:
        return sorted((_de_registro(r) for r in _ler()["usuarios"]), key=lambda u: u.usuario)


def obter(id: str) -> Usuario | None:
    with _LOCK:
        r = _achar(_ler(), id=id)
        return _de_registro(r) if r else None


def obter_por_usuario(usuario: str) -> Usuario | None:
    with _LOCK:
        r = _achar(_ler(), usuario=normalizar_usuario(usuario))
        return _de_registro(r) if r else None


# ───────────────────────────── criação ─────────────────────────────

def _novo_registro(usuario: str, nome: str, perfil: str, senha: str, trocar: bool) -> dict:
    agora = _iso(_agora())
    return {"id": "u_" + secrets.token_hex(8), "usuario": usuario, "nome": nome, "perfil": perfil, "hash": senhas.gerar_hash(senha),
            "ativo": True, "trocar_senha": trocar, "criado_em": agora, "senha_alterada_em": agora, "ultimo_login": None,
            "falhas": 0, "bloqueios": 0, "bloqueado_ate": None}


def criar_primeiro_admin(usuario: str, nome: str, senha: str, origem: str = "instalacao", ip: str = "") -> Usuario:
    """O 1º usuário: administrador. Só funciona quando NÃO existe nenhum usuário."""
    u = _validar_usuario(usuario)
    n = _validar_nome(nome, "Administrador")
    _checar_senha(senha, u, n)
    with _LOCK:
        dados = _ler()
        if dados["usuarios"]:
            raise ErroUsuarios("O sistema já tem usuários. A criação do primeiro administrador só vale na instalação.")
        reg = _novo_registro(u, n, "admin", senha, trocar=False)
        dados["usuarios"].append(reg)
        _gravar(dados)
    auditoria.registrar("admin_instalado", u, ip, f"origem: {origem}")
    return _de_registro(reg)


# Credencial PROVISÓRIA da instalação: existe só para o 1º acesso. A senha "admin" não passa na política de senhas de propósito
# (é curta e conhecida), por isso é gravada por esta função, que ignora a política, e o usuário fica marcado para TROCAR a senha:
# o guarda de requisições (web.py) não deixa fazer mais nada até a troca, e a senha nova passa pela política normal.
USUARIO_PROVISORIO = "admin"
SENHA_PROVISORIA = "admin"


def criar_admin_provisorio(origem: str = "instalador", ip: str = "") -> Usuario:
    """Cria o 1º administrador com usuário e senha provisórios (admin/admin) e a troca da senha obrigatória no 1º acesso.

    Só funciona quando NÃO existe nenhum usuário (mesma regra de `criar_primeiro_admin`)."""
    with _LOCK:
        dados = _ler()
        if dados["usuarios"]:
            raise ErroUsuarios("O sistema já tem usuários. O administrador provisório só vale na instalação.")
        reg = _novo_registro(USUARIO_PROVISORIO, "Administrador", "admin", SENHA_PROVISORIA, trocar=True)
        dados["usuarios"].append(reg)
        _gravar(dados)
    auditoria.registrar("admin_instalado", USUARIO_PROVISORIO, ip, f"origem: {origem} (senha provisória, troca obrigatória)")
    return _de_registro(reg)


def criar(usuario: str, nome: str, perfil: str, senha: str, por: str = "", ip: str = "", trocar_senha: bool = True) -> Usuario:
    u = _validar_usuario(usuario)
    n = _validar_nome(nome, u)
    p = _validar_perfil(perfil)
    _checar_senha(senha, u, n)
    with _LOCK:
        dados = _ler()
        if _achar(dados, usuario=u):
            raise ErroUsuarios("Já existe um usuário com esse nome.")
        reg = _novo_registro(u, n, p, senha, trocar_senha)
        dados["usuarios"].append(reg)
        _gravar(dados)
    auditoria.registrar("usuario_criado", por, ip, f"{u} ({p})")
    return _de_registro(reg)


# ───────────────────────────── entrada ─────────────────────────────

def autenticar(usuario: str, senha: str, ip: str = "") -> Usuario:
    """Confere usuário e senha. Levanta FalhaLogin (sempre a mesma coisa para o navegador). Conta erros e bloqueia."""
    nome = normalizar_usuario(usuario)
    if not senha or len(senha) > 1024:                              # corta lixo gigante antes de gastar memória no hash
        senhas.verificar_de_mentira("x")
        raise FalhaLogin("senha", nome)
    with _LOCK:
        reg = _achar(_ler(), usuario=nome) if nome else None
        copia = dict(reg) if reg else None
    if copia is None:
        senhas.verificar_de_mentira(senha)
        raise FalhaLogin("desconhecido", nome)

    bloqueado = bool((_parse(copia.get("bloqueado_ate")) or _agora()) > _agora())
    if bloqueado or not copia.get("ativo", True) or not copia.get("hash"):
        senhas.verificar_de_mentira(senha)                          # mesmo tempo de uma conferência de verdade
        raise FalhaLogin("bloqueado" if bloqueado else "inativo", nome)

    ok, refazer = senhas.verificar(copia["hash"], senha)
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, id=copia["id"])
        if reg is None:
            raise FalhaLogin("desconhecido", nome)
        if not ok:
            reg["falhas"] = int(reg.get("falhas", 0)) + 1
            bloqueou = False
            if reg["falhas"] >= MAX_FALHAS:
                reg["bloqueios"] = int(reg.get("bloqueios", 0)) + 1
                espera = min(BLOQUEIO_BASE_S * (2 ** (reg["bloqueios"] - 1)), BLOQUEIO_MAX_S)
                reg["bloqueado_ate"] = _iso(_agora() + timedelta(seconds=espera))
                reg["falhas"] = 0
                bloqueou = True
            _gravar(dados)
            if bloqueou:
                auditoria.registrar("login_bloqueio", nome, ip, f"bloqueado por {int(espera // 60)} min")
            raise FalhaLogin("senha", nome)
        reg["falhas"], reg["bloqueios"], reg["bloqueado_ate"] = 0, 0, None
        reg["ultimo_login"] = _iso(_agora())
        if refazer:
            reg["hash"] = senhas.gerar_hash(senha)
        _gravar(dados)
        return _de_registro(reg)


# ───────────────────────────── senha ─────────────────────────────

def alterar_propria_senha(id: str, atual: str, nova: str, ip: str = "") -> Usuario:
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, id=id)
        if reg is None:
            raise ErroUsuarios("Usuário não encontrado.")
        ok, _ = senhas.verificar(reg.get("hash", ""), atual or "")
        if not ok:
            reg["falhas"] = int(reg.get("falhas", 0)) + 1          # quem tem uma sessão roubada não pode adivinhar a senha atual à vontade
            if reg["falhas"] >= MAX_FALHAS:
                reg["bloqueios"] = int(reg.get("bloqueios", 0)) + 1
                reg["bloqueado_ate"] = _iso(_agora() + timedelta(seconds=min(BLOQUEIO_BASE_S * 2 ** (reg["bloqueios"] - 1), BLOQUEIO_MAX_S)))
                reg["falhas"] = 0
                auditoria.registrar("login_bloqueio", reg["usuario"], ip, "bloqueado ao errar a senha atual na troca")
            _gravar(dados)
            raise ErroUsuarios("A senha atual está incorreta.")
        if senhas.verificar(reg["hash"], nova or "")[0]:
            raise ErroUsuarios("A senha nova precisa ser diferente da atual.")
        _checar_senha(nova, reg["usuario"], reg.get("nome", ""))
        reg["hash"] = senhas.gerar_hash(nova)
        reg["trocar_senha"] = False
        reg["senha_alterada_em"] = _iso(_agora())
        reg["falhas"] = 0
        _gravar(dados)
        resultado = _de_registro(reg)
    auditoria.registrar("senha_alterada", resultado.usuario, ip)
    return resultado


def redefinir_senha(id: str, nova: str, por: str = "", ip: str = "", temporaria: bool = True) -> Usuario:
    """Um administrador define a senha de outra pessoa. Por padrão a pessoa é obrigada a trocá-la no 1º acesso."""
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, id=id)
        if reg is None:
            raise ErroUsuarios("Usuário não encontrado.")
        _checar_senha(nova, reg["usuario"], reg.get("nome", ""))
        reg["hash"] = senhas.gerar_hash(nova)
        reg["trocar_senha"] = bool(temporaria)
        reg["senha_alterada_em"] = _iso(_agora())
        reg["falhas"], reg["bloqueios"], reg["bloqueado_ate"] = 0, 0, None
        _gravar(dados)
        resultado = _de_registro(reg)
    auditoria.registrar("senha_redefinida", por, ip, f"de {resultado.usuario}")
    return resultado


# ───────────────────────────── administração ─────────────────────────────

def alterar(id: str, *, perfil: str | None = None, ativo: bool | None = None, nome: str | None = None, por: str = "", ip: str = "") -> Usuario:
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, id=id)
        if reg is None:
            raise ErroUsuarios("Usuário não encontrado.")
        mudancas = []
        novo_perfil = _validar_perfil(perfil) if perfil is not None else reg["perfil"]
        novo_ativo = bool(ativo) if ativo is not None else reg.get("ativo", True)
        era_admin_ativo = reg["perfil"] == "admin" and reg.get("ativo", True)
        if era_admin_ativo and not (novo_perfil == "admin" and novo_ativo) and len(_admins_ativos(dados)) <= 1:
            raise ErroUsuarios("Não dá para rebaixar ou desativar o último administrador ativo. Crie ou promova outro administrador antes.")
        if novo_perfil != reg["perfil"]:
            mudancas.append(f"perfil {reg['perfil']} → {novo_perfil}")
            reg["perfil"] = novo_perfil
        if novo_ativo != reg.get("ativo", True):
            mudancas.append("ativado" if novo_ativo else "desativado")
            reg["ativo"] = novo_ativo
        if nome is not None:
            novo_nome = _validar_nome(nome, reg["usuario"])
            if novo_nome != reg.get("nome"):
                mudancas.append("nome")
                reg["nome"] = novo_nome
        if mudancas:
            _gravar(dados)
        resultado = _de_registro(reg)
    if mudancas:
        auditoria.registrar("usuario_alterado", por, ip, f"{resultado.usuario}: " + ", ".join(mudancas))
    return resultado


def remover(id: str, por: str = "", ip: str = "") -> None:
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, id=id)
        if reg is None:
            raise ErroUsuarios("Usuário não encontrado.")
        if reg["perfil"] == "admin" and reg.get("ativo", True) and len(_admins_ativos(dados)) <= 1:
            raise ErroUsuarios("Não dá para apagar o último administrador ativo.")
        dados["usuarios"] = [r for r in dados["usuarios"] if r["id"] != id]
        _gravar(dados)
    auditoria.registrar("usuario_removido", por, ip, reg["usuario"])


def desbloquear(id: str, por: str = "", ip: str = "") -> Usuario:
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, id=id)
        if reg is None:
            raise ErroUsuarios("Usuário não encontrado.")
        reg["falhas"], reg["bloqueios"], reg["bloqueado_ate"] = 0, 0, None
        _gravar(dados)
        resultado = _de_registro(reg)
    auditoria.registrar("usuario_desbloqueado", por, ip, resultado.usuario)
    return resultado


# ───────────────────────────── recuperação (só pela linha de comando) ─────────────────────────────

def isolar_arquivo_ilegivel() -> list[str]:
    """Arquivo de usuários ilegível e sem restauração possível: põe os restos de lado (sem apagar, para análise) e deixa o
    cadastro vazio. Devolve os nomes dos arquivos movidos. Só a linha de comando chama isto."""
    carimbo = _agora().strftime("%Y%m%d-%H%M%S")
    movidos = []
    with _LOCK:
        for arq in (_arquivo(), _copia()):
            if arq.exists():
                destino = arq.with_name(f"{arq.name}.ilegivel-{carimbo}")
                os.replace(arq, destino)
                movidos.append(destino.name)
    return movidos


def redefinir_pela_linha_de_comando(usuario: str, nova: str, criar_se_nao_existir: bool = False) -> Usuario:
    """Recuperação de quem perdeu a senha: exige estar no computador (a CLI é o único chamador). Desbloqueia e reativa o
    usuário. Não pede a senha antiga, e por isso fica registrada na auditoria."""
    u = _validar_usuario(usuario)
    with _LOCK:
        dados = _ler()
        reg = _achar(dados, usuario=u)
        if reg is None:
            if not criar_se_nao_existir:
                raise ErroUsuarios("Esse usuário não existe.")
            _checar_senha(nova, u, "")
            reg = _novo_registro(u, u, "admin", nova, trocar=False)
            dados["usuarios"].append(reg)
        else:
            _checar_senha(nova, u, reg.get("nome", ""))
            reg["hash"] = senhas.gerar_hash(nova)
            reg["ativo"] = True
            reg["trocar_senha"] = False
            reg["senha_alterada_em"] = _iso(_agora())
            reg["falhas"], reg["bloqueios"], reg["bloqueado_ate"] = 0, 0, None
        _gravar(dados)
        resultado = _de_registro(reg)
    auditoria.registrar("senha_redefinida_cli", u, "", "recuperação pelo computador")
    return resultado


def invalidar_senhas_exceto(id_mantido: str) -> int:
    """Depois de recriar a pimenta: as outras senhas deixaram de valer. Apaga os hashes e exige redefinição por um administrador."""
    n = 0
    with _LOCK:
        dados = _ler()
        for r in dados["usuarios"]:
            if r["id"] != id_mantido and r.get("hash"):
                r["hash"], r["trocar_senha"] = None, True
                n += 1
        if n:
            _gravar(dados)
    return n

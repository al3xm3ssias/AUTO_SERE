"""
senhas.py — como a senha é guardada e como se decide se ela é forte
====================================================================
A senha NUNCA é guardada, nem cifrada de forma reversível: guarda-se só o HASH (uma "impressão digital" que não volta
para a senha). É mais seguro do que criptografar, porque nem o próprio sistema consegue recuperar a senha.

Como o hash é feito:
  1. a senha é normalizada (Unicode NFKC, para "é" digitado de dois jeitos dar a mesma senha);
  2. mistura-se a PIMENTA local (HMAC-SHA256, ver segredo.py): sem ela o hash roubado não serve para nada;
  3. Argon2id (vencedor do concurso de hashes de senha; exige muita memória, o que encarece cada tentativa de quem rouba
     o arquivo e tenta adivinhar com placas de vídeo), com SAL aleatório próprio de cada senha, embutido no resultado.

Sem a biblioteca argon2-cffi (ex.: pacote ainda não reinstalado) cai para scrypt, com custo equivalente; na próxima entrada
bem-sucedida o hash é refeito em Argon2id. O formato do hash diz qual foi usado e com quais parâmetros, então os
parâmetros podem ser aumentados no futuro sem invalidar as senhas já guardadas (elas são refeitas ao entrar).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import unicodedata

from . import segredo

try:                                                               # pragma: no cover — depende do ambiente
    from argon2 import PasswordHasher, Type
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
    ARGON2_DISPONIVEL = True
except Exception:                                                  # noqa: BLE001
    ARGON2_DISPONIVEL = False

# Custo. 128 MiB de memória, 3 passadas, 4 trilhas: ~0,4 s num PC comum (cada tentativa errada custa isso a quem ataca).
# Os testes trocam por valores pequenos (monkeypatch em PARAMETROS).
PARAMETROS = {"memoria_kib": 131072, "tempo": 3, "paralelismo": 4}
SCRYPT = {"n": 2 ** 16, "r": 8, "p": 2}

MIN_CARACTERES = 12
MAX_CARACTERES = 128
LIMITE_CARACTERES_MISTURA = 16                                    # a partir daqui a "frase-senha" dispensa misturar tipos de caractere

# No máximo 2 hashes ao mesmo tempo: cada um usa muita memória, e um ataque simultâneo não pode estourar a RAM do PC.
_SEMAFORO = threading.BoundedSemaphore(2)


class SenhaInvalida(ValueError):
    """A senha não passa na política. `problemas` traz as frases (em português) para mostrar ao usuário."""

    def __init__(self, problemas: list[str]):
        super().__init__(" ".join(problemas))
        self.problemas = problemas


# ───────────────────────────── política ─────────────────────────────

# Senhas que a internet inteira tenta primeiro (e variações típicas de escola/Brasil). Comparadas sem maiúsculas e sem
# símbolos nas pontas. Não é uma lista completa: é a barreira contra o óbvio; o tamanho mínimo faz o resto.
_COMUNS = {
    "123456789012", "1234567890123", "12345678901234", "123456123456", "111111111111", "000000000000", "aaaaaaaaaaaa",
    "qwertyuiopas", "qwertyuiop12", "qwertyuiop123", "asdfghjklzxc", "abcdefghijkl", "abc123abc123", "senhasenhasenha",
    "senha1234567", "senha12345678", "senha123456789", "minhasenha123", "minhasenha1234", "mudar123456", "mudar@123456",
    "password1234", "password12345", "password123456", "passw0rd1234", "p@ssw0rd1234", "p@ssword1234", "iloveyou1234",
    "administrador", "administrador1", "administrador123", "admin1234567", "admin12345678", "admin123456789", "admin@123456",
    "escola123456", "escola2026", "escola20262026", "escolamunicipal", "escolajudith", "judith123456", "judithmacedo",
    "prefeitura123", "prefeitura1234", "pontagrossa123", "pontagrossa1234", "pontagrossa2026", "brasil123456",
    "brasil2026brasil", "secretaria123", "secretaria1234", "professor1234", "professora123", "diretor123456", "autosere12345",
    "autosere123456", "auto_sere12345", "sere12345678", "sere123456789", "sere2026sere2026", "trocar123456", "bemvindo1234",
    "bemvindo12345", "futebol12345", "flamengo1234", "corinthians1", "123mudar12345", "12345678abcd", "abcd12345678",
}
_SEQUENCIAS = ("0123456789", "9876543210", "abcdefghijklmnopqrstuvwxyz", "zyxwvutsrqponmlkjihgfedcba", "qwertyuiopasdfghjklzxcvbnm",
               "qwertyuiop", "asdfghjkl", "zxcvbnm")


def normalizar(senha: str) -> str:
    return unicodedata.normalize("NFKC", senha)


def _so_alfanumerico(texto: str) -> str:
    return "".join(c for c in texto.lower() if c.isalnum())


def _eh_sequencia_ou_repeticao(senha: str) -> bool:
    s = _so_alfanumerico(senha)
    if len(s) < MIN_CARACTERES:
        return False
    if len(set(s)) <= 3:                                           # aaaaaaaaaaaa, abababababab, 121212121212
        return True
    for seq in _SEQUENCIAS:                                        # 123456789012… / qwertyuiopas… (a senha cabe numa sequência)
        if s in seq or s in seq * 3:
            return True
    return False


def problemas_da_senha(senha: str, usuario: str = "", nome: str = "") -> list[str]:
    """Lista de motivos pelos quais a senha NÃO serve (vazia = serve). Frases prontas, em português."""
    s = normalizar(senha or "")
    erros: list[str] = []
    if len(s) < MIN_CARACTERES:
        erros.append(f"Use pelo menos {MIN_CARACTERES} caracteres.")
    if len(s) > MAX_CARACTERES:
        erros.append(f"Use no máximo {MAX_CARACTERES} caracteres.")
    if s != s.strip():
        erros.append("A senha não pode começar nem terminar com espaço.")
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        erros.append("A senha tem caracteres de controle (como Tab ou Enter); use só letras, números, símbolos e espaços.")
    classes = sum(bool(x) for x in (any(c.islower() for c in s), any(c.isupper() for c in s),
                                    any(c.isdigit() for c in s), any(not c.isalnum() for c in s)))
    if 0 < len(s) < LIMITE_CARACTERES_MISTURA and classes < 3:
        erros.append("Misture pelo menos 3 tipos: letras minúsculas, MAIÚSCULAS, números e símbolos "
                     f"(ou use uma frase com {LIMITE_CARACTERES_MISTURA} caracteres ou mais).")
    minuscula = s.lower()
    if _so_alfanumerico(s) in _COMUNS or minuscula.strip() in _COMUNS:
        erros.append("Essa senha é muito comum e fácil de adivinhar. Escolha outra.")
    elif _eh_sequencia_ou_repeticao(s):
        erros.append("Evite sequências (123456…, abcdef…, qwerty…) e repetições (aaaa…).")
    u = _so_alfanumerico(usuario or "")
    if len(u) >= 3 and u in _so_alfanumerico(s):
        erros.append("A senha não pode conter o nome de usuário.")
    for parte in (nome or "").split():
        p = _so_alfanumerico(parte)
        if len(p) >= 4 and p in _so_alfanumerico(s):
            erros.append("A senha não pode conter o seu nome.")
            break
    return erros


def validar_politica(senha: str, usuario: str = "", nome: str = "") -> None:
    erros = problemas_da_senha(senha, usuario, nome)
    if erros:
        raise SenhaInvalida(erros)


# ───────────────────────────── hash ─────────────────────────────

def _pre_hash(senha: str) -> bytes:
    """HMAC-SHA256(pimenta, senha normalizada) em base64: tamanho fixo e a pimenta entra em TODO hash."""
    bruto = hmac.new(segredo.obter_pimenta(), normalizar(senha).encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(bruto)


def _hasher():
    return PasswordHasher(time_cost=PARAMETROS["tempo"], memory_cost=PARAMETROS["memoria_kib"],
                          parallelism=PARAMETROS["paralelismo"], hash_len=32, salt_len=16, type=Type.ID)


def _scrypt_calcular(pre: bytes, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(pre, salt=sal, n=n, r=r, p=p, dklen=32, maxmem=256 * 1024 * 1024)


def gerar_hash(senha: str) -> str:
    """Hash pronto para guardar. Não valida a política (quem chama decide; ver validar_politica)."""
    pre = _pre_hash(senha)
    with _SEMAFORO:
        if ARGON2_DISPONIVEL:
            return _hasher().hash(pre)
        sal = secrets.token_bytes(16)
        n, r, p = SCRYPT["n"], SCRYPT["r"], SCRYPT["p"]
        derivado = _scrypt_calcular(pre, sal, n, r, p)
    return "$scrypt$n={},r={},p={}${}${}".format(n, r, p, base64.b64encode(sal).decode(), base64.b64encode(derivado).decode())


def verificar(hash_guardado: str, senha: str) -> tuple[bool, bool]:
    """(senha confere?, o hash deve ser refeito?). Nunca levanta erro por hash estranho: devolve (False, False)."""
    if not hash_guardado or not isinstance(hash_guardado, str):
        return False, False
    try:
        pre = _pre_hash(senha)
    except segredo.ChaveIndisponivel:
        raise
    with _SEMAFORO:
        if hash_guardado.startswith("$argon2"):
            if not ARGON2_DISPONIVEL:
                return False, False
            h = _hasher()
            try:
                h.verify(hash_guardado, pre)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False, False
            return True, bool(h.check_needs_rehash(hash_guardado))
        if hash_guardado.startswith("$scrypt$"):
            try:
                _, _, params, sal_b64, hash_b64 = hash_guardado.split("$")
                valores = dict(item.split("=") for item in params.split(","))
                n, r, p = int(valores["n"]), int(valores["r"]), int(valores["p"])
                esperado = base64.b64decode(hash_b64)
                calculado = _scrypt_calcular(pre, base64.b64decode(sal_b64), n, r, p)
            except (ValueError, KeyError, MemoryError):
                return False, False
            if not hmac.compare_digest(calculado, esperado):
                return False, False
            refazer = ARGON2_DISPONIVEL or (n, r, p) != (SCRYPT["n"], SCRYPT["r"], SCRYPT["p"])
            return True, refazer
    return False, False


_hash_de_mentira: str | None = None


def verificar_de_mentira(senha: str) -> None:
    """Gasta o mesmo tempo de uma verificação de verdade. Usado quando o usuário nem existe, para o tempo da resposta
    não revelar quais usuários existem."""
    global _hash_de_mentira
    if _hash_de_mentira is None:
        _hash_de_mentira = gerar_hash(secrets.token_urlsafe(24))
    try:
        verificar(_hash_de_mentira, senha)
    except segredo.ChaveIndisponivel:
        pass


def gerar_senha_temporaria() -> str:
    """Senha aleatória forte (para o administrador entregar a outro usuário, que é obrigado a trocá-la no 1º acesso)."""
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        s = "".join(secrets.choice(alfabeto) for _ in range(14)) + secrets.choice("23456789") + secrets.choice("abcdefghjkmnpqrstuvwxyz")
        s = "-".join([s[:5], s[5:10], s[10:]])
        if not problemas_da_senha(s):
            return s

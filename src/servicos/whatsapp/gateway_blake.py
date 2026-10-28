"""
Provedor do gateway  blakegt/whatsapp-web-api-rest  (Baileys + NestJS, Docker)
===============================================================================
Escrito a partir do código-fonte do gateway (github.com/BlakePro/whatsapp-web-api-rest) e
conferido rodando o gateway real, sem WhatsApp. O que isso significa na prática:

  • NÃO há autenticação (nem API key). Quem alcança a porta controla o WhatsApp da escola.
    Por isso o docker-compose publica a porta só em 127.0.0.1.
  • NÃO há endpoint de estado. O estado vem do SSE (monitor.py) e, quando preciso, de uma
    consulta GET /number/<n>.
  • Respostas de erro NÃO são erro HTTP: sem sessão, POST /message devolve 201 com `{}`.
    Por isso "enviou" só vale quando a resposta traz `key.id` (o id da mensagem do WhatsApp).
  • GET /  inicia a sessão — e, se já houver sessão viva, abre um segundo socket por cima
    (o gateway nunca marca "conectado" internamente). Só chamar com a sessão desligada.
  • DELETE /webhooks/:n é 1-based na prática (/0 e /1 apagam o primeiro).
  • Número no formato do WhatsApp: <DDI><DDD><número>@s.whatsapp.net. Para números brasileiros
    o WhatsApp decide se há o 9º dígito: usamos o `jid` que GET /number devolve.

AVISO: é um cliente NÃO oficial do WhatsApp. O número usado pode ser banido, mesmo com poucas
mensagens. Não envie em massa, não envie para quem não pediu contato.

Envio real continua exigindo WHATSAPP_ENVIO_REAL=1 (a mesma trava dos outros provedores).
"""
from __future__ import annotations

import base64
import mimetypes
from typing import Any, Optional

import requests

from .base import (ConsultaNumero, EnvioNaoAutorizadoError, EstadoConexao, ResultadoAcao, ResultadoEnvio,
                   normalizar_numero)
from .gateway_http import envio_real_autorizado
from .monitor import Foto, MonitorSessao, Situacao

URL_PADRAO = "http://127.0.0.1:8085"
SUFIXO_JID = "@s.whatsapp.net"
# Número bem formado e (praticamente certo) sem WhatsApp, usado só para perguntar "o gateway está
# conectado?": se a consulta é respondida, há sessão. Pode ser trocado por WHATSAPP_NUMERO_SONDA.
NUMERO_SONDA = "5542900000000"
TIPOS_MIDIA = ("document", "image", "video", "audio")
PRESENCAS = ("unavailable", "available", "composing", "recording", "paused")
LIMITE_MIDIA_BYTES = 18 * 1024 * 1024          # o gateway aceita corpo de 25 MB; base64 incha ~33%

MSG_NAO_CONFIRMOU = ("O gateway não confirmou o envio (resposta vazia). Quase sempre significa WhatsApp "
                     "desconectado: confira o estado da conexão.")


class ProvedorBlake:
    nome = "blake"

    def __init__(self, url_base: str = URL_PADRAO, *, http: Any = requests, timeout: float = 10.0,
                 monitor: Optional[MonitorSessao] = None, validar_numero: bool = True,
                 numero_sonda: str = NUMERO_SONDA) -> None:
        self.url_base = (url_base or URL_PADRAO).rstrip("/")
        self.timeout = timeout
        self.monitor = monitor
        self.validar_numero = validar_numero
        self.numero_sonda = numero_sonda
        self._http = http

    # ───────────────────────── infraestrutura HTTP ─────────────────────────
    def _req(self, metodo: str, caminho: str, *, timeout: Optional[float] = None, **kw):
        """(resposta, None) ou (None, mensagem amigável). Nunca levanta erro de rede."""
        try:
            fn = getattr(self._http, metodo.lower())
            return fn(f"{self.url_base}{caminho}", timeout=timeout or self.timeout, **kw), None
        except requests.Timeout:
            return None, "O gateway demorou demais para responder."
        except requests.ConnectionError:
            return None, f"Gateway inacessível em {self.url_base}. Ele está ligado? (veja docs/WHATSAPP.md)"
        except requests.RequestException as exc:
            return None, f"Falha de rede ao falar com o gateway ({type(exc).__name__})."

    @staticmethod
    def _json(resp) -> Any:
        try:
            return resp.json() if resp.content else None
        except ValueError:
            return None

    # ───────────────────────────── estado ─────────────────────────────
    def _foto(self) -> Foto:
        if self.monitor is not None and self.monitor.ativo:
            return self.monitor.foto()
        # Sem monitor (ex.: linha de comando): pergunta direto.
        resp, _ = self._req("GET", "/webhooks", timeout=3)
        if resp is None or resp.status_code >= 400:
            return Foto(Situacao.GATEWAY_OFFLINE)
        if self.confirmar_conexao().situacao in ("existe", "nao_existe"):
            return Foto(Situacao.CONECTADO, texto="Sessão confirmada por consulta ao WhatsApp.", gateway_online=True)
        return Foto(Situacao.DESCONHECIDO, gateway_online=True)

    def estado(self) -> EstadoConexao:
        f = self._foto()
        sit = f.situacao
        if sit == Situacao.GATEWAY_OFFLINE:
            det = f"Gateway inacessível em {self.url_base}. Ele está ligado? (veja docs/WHATSAPP.md)"
        elif sit == Situacao.VERIFICANDO:
            det = "Verificando o gateway…"
        elif sit == Situacao.CONECTADO:
            det = "Conectado."
        elif sit == Situacao.AGUARDANDO_QR:
            det = "Aguardando a leitura do QR Code no celular."
        elif sit == Situacao.RECONECTANDO:
            det = "O gateway está tentando reconectar sozinho…"
        elif sit == Situacao.INICIANDO:
            det = "Iniciando a sessão… o QR Code aparece em instantes."
        elif sit == Situacao.DESCONECTADO:
            det = f"Desconectado: {f.texto}" if f.texto else "Desconectado."
        else:
            det = "Gateway no ar, mas a sessão do WhatsApp ainda não foi confirmada."
        return EstadoConexao(sit == Situacao.CONECTADO, det, situacao=sit)

    def confirmar_conexao(self, numero: Optional[str] = None) -> ConsultaNumero:
        """Pergunta ao WhatsApp (via gateway) por um número. Qualquer resposta de verdade — achou ou
        não achou — prova que há sessão; só `indisponivel` significa "não consegui confirmar"."""
        try:
            alvo = normalizar_numero(numero) if numero else self.numero_sonda
        except ValueError:
            alvo = self.numero_sonda
        return self._consultar(alvo)

    # ─────────────────────── administração da sessão ───────────────────────
    def iniciar_sessao(self) -> ResultadoAcao:
        """GET /  — pede ao gateway para iniciar a sessão (gera o QR Code se não houver login salvo).
        Perigoso com sessão viva (abre um 2º socket): quem chama decide se pode (ver gerenciador)."""
        antes = self.monitor.foto().atualizado_em if self.monitor else None
        resp, erro = self._req("GET", "/", timeout=15)
        if resp is None:
            return ResultadoAcao(False, erro or "Sem resposta do gateway.")
        if resp.status_code >= 400:
            return ResultadoAcao(False, f"O gateway respondeu erro {resp.status_code}.")
        if self.monitor:
            self.monitor.marcar_iniciando(se_inalterado_desde=antes)
        return ResultadoAcao(True, "Sessão em início. O QR Code aparece em instantes.")

    def sair(self) -> ResultadoAcao:
        """GET /logout — encerra a sessão. ATENÇÃO: o gateway não apaga o login salvo; para vincular
        outro número é preciso zerar o volume (docs/WHATSAPP.md → "Zerar o vínculo")."""
        resp, erro = self._req("GET", "/logout")
        if resp is None:
            return ResultadoAcao(False, erro or "Sem resposta do gateway.")
        if resp.status_code >= 400:
            return ResultadoAcao(False, f"O gateway respondeu erro {resp.status_code}.")
        return ResultadoAcao(True, "Pedido de logout enviado ao gateway.")

    # ───────────────────────────── números ─────────────────────────────
    def _consultar(self, digitos: str) -> ConsultaNumero:
        resp, erro = self._req("GET", f"/number/{digitos}")
        if resp is None:
            return ConsultaNumero("indisponivel", detalhe=erro or "")
        if resp.status_code >= 400:
            return ConsultaNumero("indisponivel", detalhe=f"O gateway respondeu erro {resp.status_code}.")
        if not resp.content or not resp.content.strip():
            # Consulta feita com sucesso e o WhatsApp não devolveu ninguém (o gateway devolve corpo vazio).
            return ConsultaNumero("nao_existe", detalhe="O WhatsApp não reconhece esse número.")
        corpo = self._json(resp)
        if isinstance(corpo, dict) and corpo.get("jid") and corpo.get("exists", True) is not False:
            return ConsultaNumero("existe", jid=str(corpo["jid"]))
        if isinstance(corpo, dict) and corpo.get("exists") is False:
            return ConsultaNumero("nao_existe", detalhe="O WhatsApp não reconhece esse número.")
        # `{}` = o gateway engoliu um erro (sem sessão, socket fechado...)
        return ConsultaNumero("indisponivel", detalhe="O gateway não conseguiu consultar (WhatsApp desconectado?).")

    def consultar_numero(self, numero: str) -> ConsultaNumero:
        """Esse número tem WhatsApp? Levanta ValueError se o número não for brasileiro válido."""
        return self._consultar(normalizar_numero(numero))

    def _resolver_destino(self, alvo: str) -> tuple[Optional[str], Optional[str]]:
        """(chatId, erro). Com validação ligada usa o jid canônico do WhatsApp; se a consulta estiver
        indisponível, tenta o envio mesmo assim (ele próprio acusa falha se estiver desconectado)."""
        if not self.validar_numero:
            return f"{alvo}{SUFIXO_JID}", None
        c = self._consultar(alvo)
        if c.situacao == "nao_existe":
            return None, "Esse número não tem WhatsApp."
        if c.situacao == "existe" and c.jid:
            return c.jid, None
        return f"{alvo}{SUFIXO_JID}", None

    # ───────────────────────────── envio ─────────────────────────────
    @staticmethod
    def _exigir_autorizacao() -> None:
        if not envio_real_autorizado():
            raise EnvioNaoAutorizadoError(
                "Envio real bloqueado: defina WHATSAPP_ENVIO_REAL=1 para autorizar. Nenhuma mensagem foi enviada.")

    def _postar_mensagem(self, payload: dict) -> ResultadoEnvio:
        resp, erro = self._req("POST", "/message", json=payload)
        if resp is None:
            return ResultadoEnvio(False, False, erro=erro)
        if resp.status_code >= 400:
            return ResultadoEnvio(False, False, erro=f"O gateway respondeu erro {resp.status_code}.")
        corpo = self._json(resp)
        chave = corpo.get("key") if isinstance(corpo, dict) else None
        id_msg = chave.get("id") if isinstance(chave, dict) else None
        if not id_msg:
            return ResultadoEnvio(False, False, erro=MSG_NAO_CONFIRMOU)
        return ResultadoEnvio(True, False, id_mensagem=str(id_msg))

    def enviar(self, numero: str, texto: str) -> ResultadoEnvio:
        self._exigir_autorizacao()
        alvo = normalizar_numero(numero)
        if not str(texto or "").strip():
            return ResultadoEnvio(False, False, erro="Mensagem vazia.")
        chat_id, erro = self._resolver_destino(alvo)
        if erro:
            return ResultadoEnvio(False, False, erro=erro)
        return self._postar_mensagem({"chatId": chat_id, "text": texto})

    def enviar_midia(self, numero: str, tipo: str, dados: bytes, *, nome_arquivo: Optional[str] = None,
                     mimetype: Optional[str] = None, legenda: Optional[str] = None, voz: bool = False) -> ResultadoEnvio:
        """Documento (PDF...), imagem, vídeo ou áudio. Pensado para os módulos futuros (termos, avisos)."""
        self._exigir_autorizacao()
        alvo = normalizar_numero(numero)
        if tipo not in TIPOS_MIDIA:
            return ResultadoEnvio(False, False, erro=f"Tipo de mídia inválido: use um de {', '.join(TIPOS_MIDIA)}.")
        if not dados:
            return ResultadoEnvio(False, False, erro="Arquivo vazio.")
        if len(dados) > LIMITE_MIDIA_BYTES:
            return ResultadoEnvio(False, False, erro="Arquivo grande demais (limite de cerca de 18 MB).")
        if tipo == "document":
            if not nome_arquivo:
                return ResultadoEnvio(False, False, erro="Informe o nome do arquivo ao enviar um documento.")
            mimetype = mimetype or mimetypes.guess_type(nome_arquivo)[0] or "application/octet-stream"
        chat_id, erro = self._resolver_destino(alvo)
        if erro:
            return ResultadoEnvio(False, False, erro=erro)
        midia: dict[str, Any] = {"type": tipo, "data": base64.b64encode(dados).decode("ascii")}
        if nome_arquivo:
            midia["filename"] = nome_arquivo
        if mimetype:
            midia["mimetype"] = mimetype
        if legenda and tipo != "audio":
            midia["caption"] = legenda
        if tipo == "audio":
            midia["ptt"] = bool(voz)
        return self._postar_mensagem({"chatId": chat_id, "media": midia})

    def simular_presenca(self, numero: str, acao: str = "composing") -> ResultadoAcao:
        """"digitando…" / "gravando áudio…". O destinatário VÊ isso, então passa pela mesma trava do envio."""
        self._exigir_autorizacao()
        if acao not in PRESENCAS:
            return ResultadoAcao(False, f"Ação inválida: use uma de {', '.join(PRESENCAS)}.")
        chat_id, erro = self._resolver_destino(normalizar_numero(numero))
        if erro:
            return ResultadoAcao(False, erro)
        resp, erro = self._req("POST", "/simulate", json={"chatId": chat_id, "action": acao})
        if resp is None:
            return ResultadoAcao(False, erro or "Sem resposta do gateway.")
        return ResultadoAcao(resp.status_code < 400, "Presença enviada." if resp.status_code < 400 else f"Erro {resp.status_code}.")

    # ───────────────────────── webhooks (mensagens recebidas) ─────────────────────────
    def webhooks_listar(self) -> Optional[list[str]]:
        resp, _ = self._req("GET", "/webhooks")
        if resp is None or resp.status_code >= 400:
            return None
        corpo = self._json(resp)
        return [str(u) for u in corpo] if isinstance(corpo, list) else None

    def webhook_registrar(self, url: str) -> ResultadoAcao:
        if not str(url).startswith(("http://", "https://")):
            return ResultadoAcao(False, "O endereço do webhook precisa começar com http:// ou https://.")
        atuais = self.webhooks_listar()
        if atuais is None:
            return ResultadoAcao(False, "Não consegui ler a lista de webhooks do gateway.")
        if url in atuais:
            return ResultadoAcao(True, "Webhook já estava registrado.")
        resp, erro = self._req("POST", "/webhooks", json={"url": url})
        if resp is None:
            return ResultadoAcao(False, erro or "Sem resposta do gateway.")
        if resp.status_code >= 400:
            return ResultadoAcao(False, f"O gateway respondeu erro {resp.status_code}.")
        return ResultadoAcao(True, "Webhook registrado.")

    def webhook_remover(self, url: str) -> ResultadoAcao:
        atuais = self.webhooks_listar()
        if atuais is None:
            return ResultadoAcao(False, "Não consegui ler a lista de webhooks do gateway.")
        if url not in atuais:
            return ResultadoAcao(True, "Esse webhook já não estava registrado.")
        posicao = atuais.index(url) + 1                     # o gateway trata o índice como 1-based
        resp, erro = self._req("DELETE", f"/webhooks/{posicao}")
        if resp is None:
            return ResultadoAcao(False, erro or "Sem resposta do gateway.")
        depois = self.webhooks_listar()
        if depois is not None and url in depois:
            return ResultadoAcao(False, "O gateway não removeu o webhook.")
        return ResultadoAcao(True, "Webhook removido.")

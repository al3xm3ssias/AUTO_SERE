"""
Gerenciador do WhatsApp (um por processo)
=========================================
Junta o provedor configurado + o monitor da sessão e oferece o que a interface e os módulos
futuros precisam, sem que eles conheçam o gateway:

    from src.servicos.whatsapp.gerenciador import obter_gerenciador
    g = obter_gerenciador()
    g.estado()                      # EstadoConexao
    g.provedor.enviar("42 99999-8888", "texto")   # respeita WHATSAPP_ENVIO_REAL

Variáveis de ambiente (credenciais/.env):
    WHATSAPP_PROVEDOR        simulado (padrão) | whatsplay | blake | http
    WHATSAPP_WHATSPLAY_HEADLESS  whatsplay: 1 esconde a janela (padrão 0: janela visível)
    WHATSAPP_WHATSPLAY_PERFIL    whatsplay: pasta do perfil (padrão credenciais/whatsapp_sessao)
    WHATSAPP_API_URL         blake: padrão http://127.0.0.1:8085
    WHATSAPP_ENVIO_REAL      1 para permitir envio de verdade (padrão: não)
    WHATSAPP_VALIDAR_NUMERO  blake: 1 (padrão) consulta o número antes de enviar
    WHATSAPP_NUMERO_SONDA    blake: número usado só para confirmar a conexão
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from .base import EstadoConexao, ProvedorWhatsApp, ResultadoAcao
from .gateway_blake import NUMERO_SONDA, URL_PADRAO, ProvedorBlake
from .monitor import MonitorSessao, Situacao, fonte_sse_http
from .provedor_whatsplay import ProvedorWhatsplay, criar_provedor_whatsplay, id_do_qr


def qr_para_svg(texto: str) -> str:
    """QR Code como SVG (usa a biblioteca `qrcode`, que já é dependência do projeto). O pareamento
    precisa de fundo branco: quem exibe deve colocar o SVG sobre um quadro branco."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    return re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)     # o tamanho vem do CSS


class GerenciadorWhatsApp:
    def __init__(self, provedor: ProvedorWhatsApp, monitor: Optional[MonitorSessao] = None,
                 url_gateway: str = "") -> None:
        self.provedor = provedor
        self.monitor = monitor
        self.url_gateway = url_gateway
        self._cache_qr: tuple[str, str] = ("", "")

    # ── identificação ──
    @property
    def nome(self) -> str:
        return self.provedor.nome

    @property
    def simulado(self) -> bool:
        return self.provedor.nome == "simulado"

    @property
    def tem_gateway(self) -> bool:
        """Gateway Docker (blake): tem webhook, consulta de número e logout próprios."""
        return isinstance(self.provedor, ProvedorBlake)

    @property
    def tem_sessao(self) -> bool:
        """Provedor com sessão real que a tela conecta (blake ou whatsplay)."""
        return isinstance(self.provedor, (ProvedorBlake, ProvedorWhatsplay))

    @property
    def tem_webhook(self) -> bool:
        return self.tem_gateway

    # ── leitura ──
    def estado(self) -> EstadoConexao:
        return self.provedor.estado()

    def detalhe_extra(self) -> str:
        """Última mensagem técnica do gateway/navegador (para diagnóstico na tela)."""
        if self.monitor:
            return self.monitor.foto().texto
        if isinstance(self.provedor, ProvedorWhatsplay):
            return self.provedor.sessao.foto().texto
        return ""

    def qr_id(self) -> str:
        """Identificador curto do QR atual ("" se não há) — a tela só baixa a imagem quando ele muda."""
        if self.monitor:
            qr = self.monitor.foto().qr
            return hashlib.sha256(qr.encode()).hexdigest()[:12] if qr else ""
        if isinstance(self.provedor, ProvedorWhatsplay):
            png = self.provedor.qr_png()
            return id_do_qr(png) if png else ""
        return ""

    def qr_imagem(self) -> Optional[tuple[str, bytes]]:
        """(mimetype, bytes) do QR atual, ou None."""
        if isinstance(self.provedor, ProvedorWhatsplay):
            png = self.provedor.qr_png()
            return ("image/png", png) if png else None
        svg = self.qr_svg()
        return ("image/svg+xml", svg.encode("utf-8")) if svg else None

    def qr_svg(self) -> Optional[str]:
        """SVG do QR Code atual, ou None. Nunca grava o QR em lugar nenhum."""
        if not self.monitor:
            return None
        qr = self.monitor.foto().qr
        if not qr:
            return None
        if self._cache_qr[0] != qr:
            self._cache_qr = (qr, qr_para_svg(qr))
        return self._cache_qr[1]

    # ── ações ──
    def conectar(self, forcar: bool = False) -> dict[str, Any]:
        """Pede ao gateway para iniciar a sessão (gerar o QR Code) — só quando é seguro.
        Retorna {ok, mensagem, precisa_confirmar}."""
        if not self.tem_sessao:
            motivo = ("Modo simulado: não há WhatsApp real para conectar." if self.simulado
                      else "Este provedor não gera QR Code por aqui.")
            return {"ok": False, "mensagem": motivo, "precisa_confirmar": False}
        est = self.provedor.estado()
        sit = est.situacao
        if sit == Situacao.GATEWAY_OFFLINE:
            return {"ok": False, "mensagem": est.detalhe, "precisa_confirmar": False}
        if sit == Situacao.VERIFICANDO:
            return {"ok": False, "mensagem": "Ainda verificando o gateway; tente de novo em instantes.", "precisa_confirmar": False}
        if sit == Situacao.CONECTADO:
            return {"ok": False, "mensagem": "O WhatsApp já está conectado.", "precisa_confirmar": False}
        if sit in (Situacao.AGUARDANDO_QR, Situacao.INICIANDO, Situacao.RECONECTANDO):
            return {"ok": True, "mensagem": "A sessão já está em andamento.", "precisa_confirmar": False}
        if sit == Situacao.DESCONHECIDO and not forcar:
            # Se já houver sessão viva, iniciar de novo abre um 2º socket e pode derrubá-la.
            return {"ok": False, "precisa_confirmar": True,
                    "mensagem": ("Não consegui confirmar se já existe uma sessão ativa. Se existir, iniciar de "
                                 "novo pode derrubá-la. Quer gerar o QR Code mesmo assim?")}
        r: ResultadoAcao = self.provedor.iniciar_sessao()
        return {"ok": r.ok, "mensagem": r.detalhe, "precisa_confirmar": False}

    def verificar(self, numero: Optional[str] = None) -> dict[str, Any]:
        """Confirma a conexão perguntando ao WhatsApp por um número (o seu, de preferência)."""
        if not self.tem_gateway:
            return {"ok": self.simulado, "mensagem": ("Modo simulado: nada a verificar." if self.simulado
                                                      else "A verificação por consulta só existe no gateway Docker.")}
        c = self.provedor.confirmar_conexao(numero)
        if c.situacao in ("existe", "nao_existe"):
            if self.monitor:
                self.monitor.marcar_conectado_por_consulta()
            return {"ok": True, "mensagem": "Conexão confirmada: o WhatsApp respondeu à consulta."}
        return {"ok": False, "mensagem": c.detalhe or "Não consegui confirmar a conexão."}

    def sondar_ao_conectar(self) -> None:
        """Chamado pelo monitor quando o /sse (re)conecta: descobre se já havia sessão ativa."""
        try:
            self.verificar()
        except Exception:
            pass


# ───────────────────────── singleton do processo ─────────────────────────
_instancia: Optional[GerenciadorWhatsApp] = None
_trava = threading.Lock()


def _flag(nome: str, padrao: bool) -> bool:
    v = os.environ.get(nome, "").strip().lower()
    return padrao if not v else v in ("1", "true", "sim", "yes")


def _provedor_whatsplay_do_ambiente() -> ProvedorWhatsplay:
    from src.comum.paths import CREDENCIAIS_DIR
    pasta = Path(os.environ.get("WHATSAPP_WHATSPLAY_PERFIL", "").strip() or (CREDENCIAIS_DIR / "whatsapp_sessao"))
    return criar_provedor_whatsplay(pasta, headless=_flag("WHATSAPP_WHATSPLAY_HEADLESS", False))


def _construir() -> GerenciadorWhatsApp:
    nome = (os.environ.get("WHATSAPP_PROVEDOR", "simulado").strip().lower() or "simulado")
    if nome == "blake":
        url = os.environ.get("WHATSAPP_API_URL", "").strip() or URL_PADRAO
        prov = ProvedorBlake(url, validar_numero=_flag("WHATSAPP_VALIDAR_NUMERO", True),
                             numero_sonda=os.environ.get("WHATSAPP_NUMERO_SONDA", "").strip() or NUMERO_SONDA)
        ger = GerenciadorWhatsApp(prov, None, url)
        prov.monitor = ger.monitor = MonitorSessao(fonte_sse_http(url), ao_conectar=ger.sondar_ao_conectar)
        ger.monitor.iniciar()
        return ger
    if nome == "whatsplay":
        return GerenciadorWhatsApp(_provedor_whatsplay_do_ambiente(), None, "")
    # simulado / http (legado): sem monitor; criar_provedor valida a configuração e levanta erro claro
    from . import criar_provedor
    return GerenciadorWhatsApp(criar_provedor(), None, "")


def obter_gerenciador() -> GerenciadorWhatsApp:
    global _instancia
    with _trava:
        if _instancia is None:
            _instancia = _construir()
        return _instancia


def reiniciar_gerenciador() -> None:
    """Descarta o gerenciador (para a thread do monitor). O próximo obter_gerenciador() relê o ambiente."""
    global _instancia
    with _trava:
        if _instancia and _instancia.monitor:
            _instancia.monitor.parar()
        if _instancia and isinstance(_instancia.provedor, ProvedorWhatsplay):
            _instancia.provedor.sessao.parar()          # troca de modo: fecha o navegador
        _instancia = None

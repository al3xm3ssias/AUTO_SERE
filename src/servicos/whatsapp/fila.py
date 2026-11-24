"""
Fila de envio do WhatsApp (7b)
==============================
Em vez de mandar uma mensagem de cada vez, o usuário põe várias na fila e o sistema as envia sozinho, devagar, para não
parecer envio em massa (o WhatsApp bane números que mandam rápido demais; este é um cliente não oficial).

O que a fila garante:
  - pausa fixa ENTRE uma mensagem e a seguinte (INTERVALO_MIN_S a INTERVALO_MAX_S segundos); o padrão é de 5 minutos;
  - limite por dia de mensagens de verdade (LIMITE_MIN a LIMITE_MAX). Ao atingi-lo, a fila espera o dia seguinte e
    continua sozinha (se `continuar_no_dia_seguinte`) ou para;
  - Pausar a qualquer momento (termina a mensagem em andamento) e continuar depois; cancelar item a item ou todos os
    pendentes; "tentar de novo" para o que falhou;
  - histórico: cada item guarda o resultado (enviado, simulado, falhou, cancelado) e a hora;
  - nada se repete: o mesmo texto para o mesmo número, se já está na fila ou já foi enviado, não entra de novo;
  - envio real só com WHATSAPP_ENVIO_REAL=1 (a fila pausa e avisa se estiver bloqueado) e só com o WhatsApp conectado;
  - "enviada, sem confirmação do tique" (o WhatsApp Web não mostrou o visto a tempo) NÃO é falha: o item fica "enviado" com um
    aviso e não conta para pausar;
  - 3 falhas seguidas pausam a fila; uma mensagem que ficou "enviando" quando o programa caiu vira "falhou" (confira no
    WhatsApp se saiu antes de tentar de novo, para não mandar duas vezes).
No provedor SIMULADO a fila roda (sem pausas longas) mas nada sai: os itens ficam "simulado" e podem voltar à fila.

Os dados ficam em <dados do ano>/WHATSAPP/fila.json (entra no backup do ano). O estado de execução (rodando/pausada)
vale só enquanto o programa está aberto: ao reabrir, a fila está parada e o usuário decide continuar.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .base import EnvioNaoAutorizadoError, mascarar_numero, normalizar_numero
from .gateway_http import envio_real_autorizado

# Padrão de 5 minutos (23/11/2026, pedido do usuário): em comunicado em massa a pausa curta arrisca o bloqueio do número.
INTERVALO_PADRAO_S, INTERVALO_MIN_S, INTERVALO_MAX_S = 300, 10, 600
LIMITE_PADRAO, LIMITE_MIN, LIMITE_MAX = 40, 1, 300
LIMITE_TEXTO = 4000
FALHAS_SEGUIDAS_MAX = 3
PAUSA_SIMULADO_S = 0.5

PENDENTE, ENVIANDO, ENVIADO, SIMULADO, FALHOU, CANCELADO = "pendente", "enviando", "enviado", "simulado", "falhou", "cancelado"
STATUS = (PENDENTE, ENVIANDO, ENVIADO, SIMULADO, FALHOU, CANCELADO)

PARADA, RODANDO, PAUSADA, CONCLUIDA, AGUARDANDO_DIA = "parada", "rodando", "pausada", "concluida", "aguardando_dia"


def _caminho_padrao() -> Path:
    from src.comum import paths
    return paths.dados_ano_atual() / "WHATSAPP" / "fila.json"


def _obter_provedor_padrao():
    from .gerenciador import obter_gerenciador
    return obter_gerenciador().provedor


def _inteiro_entre(valor, minimo: int, maximo: int, nome: str) -> int:
    try:
        n = int(str(valor).strip())
    except ValueError as exc:
        raise ValueError(f"{nome}: use um número inteiro.") from exc
    if not minimo <= n <= maximo:
        raise ValueError(f"{nome}: use um valor de {minimo} a {maximo}.")
    return n


class FilaWhatsApp:
    def __init__(self, caminho: Callable[[], Path] = _caminho_padrao, provedor: Callable[[], object] = _obter_provedor_padrao,
                 agora: Callable[[], datetime] = datetime.now) -> None:
        self._caminho, self._provedor, self._agora = caminho, provedor, agora
        self._trava = threading.RLock()
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._estado, self._mensagem = PARADA, ""

    # ── armazenamento ──
    def _ler(self) -> dict:
        from src.comum.arquivos_json import ArquivoJsonCorrompidoError, carregar_json
        arquivo = self._caminho()
        try:
            dados = carregar_json(arquivo, dict, dict)
        except ArquivoJsonCorrompidoError as exc:
            raise ValueError(f"Fila do WhatsApp: {exc}") from exc
        dados.setdefault("config", {})
        dados.setdefault("itens", [])
        if not self._rodando():          # sobrou "enviando" de uma queda: não sabemos se saiu, então não repete sozinho
            for item in dados["itens"]:
                if item.get("status") == ENVIANDO:
                    item.update(status=FALHOU, erro="O programa fechou durante o envio. Confira no WhatsApp se esta mensagem saiu "
                                                   "antes de tentar de novo.")
        return dados

    def _gravar(self, dados: dict) -> None:
        from src.comum.arquivos_json import salvar_json_atomico
        salvar_json_atomico(self._caminho(), dados, indent=2)

    def _rodando(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def em_andamento(self) -> bool:
        """A fila está enviando (ou esperando a próxima mensagem / o dia seguinte) agora."""
        return self._rodando()

    @staticmethod
    def _config(dados: dict) -> dict:
        c = dados.get("config") or {}
        return {"intervalo_s": int(c.get("intervalo_s") or INTERVALO_PADRAO_S),
                "limite_diario": int(c.get("limite_diario") or LIMITE_PADRAO),
                "continuar_no_dia_seguinte": bool(c.get("continuar_no_dia_seguinte", True))}

    def _enviados_hoje(self, dados: dict) -> int:
        hoje = self._agora().date().isoformat()
        return sum(1 for i in dados["itens"] if i.get("status") == ENVIADO and not i.get("simulado")
                   and str(i.get("enviado_em", ""))[:10] == hoje)

    # ── o que a tela mostra ──
    def resumo(self) -> dict:
        with self._trava:
            dados = self._ler()
            cfg = self._config(dados)
            contagem = {s: 0 for s in STATUS}
            for i in dados["itens"]:
                contagem[i.get("status", PENDENTE)] = contagem.get(i.get("status", PENDENTE), 0) + 1
            hoje = self._enviados_hoje(dados)
            itens = [{"id": i["id"], "nome": i.get("nome", ""), "numero": mascarar_numero(i.get("numero")), "texto": i.get("texto", ""),
                      "origem": i.get("origem", ""), "status": i.get("status", PENDENTE), "erro": i.get("erro", ""), "aviso": i.get("aviso", ""),
                      "criado_em": i.get("criado_em", ""), "enviado_em": i.get("enviado_em", ""), "tentativas": i.get("tentativas", 0)}
                     for i in dados["itens"]]
            return {"estado": self._estado if self._rodando() or self._estado != RODANDO else PARADA, "mensagem": self._mensagem,
                    "config": cfg, "contagem": contagem, "enviados_hoje": hoje,
                    "restante_hoje": max(0, cfg["limite_diario"] - hoje), "itens": itens}

    # ── configuração e itens ──
    def configurar(self, intervalo_s, limite_diario, continuar_no_dia_seguinte=True) -> dict:
        cfg = {"intervalo_s": _inteiro_entre(intervalo_s, INTERVALO_MIN_S, INTERVALO_MAX_S, "Intervalo entre mensagens (segundos)"),
               "limite_diario": _inteiro_entre(limite_diario, LIMITE_MIN, LIMITE_MAX, "Limite por dia"),
               "continuar_no_dia_seguinte": bool(continuar_no_dia_seguinte)}
        with self._trava:
            dados = self._ler()
            dados["config"] = cfg
            self._gravar(dados)
        return cfg

    def adicionar(self, itens: list[dict], origem: str = "manual") -> dict:
        """Cada item: {numero, nome, texto}. Devolve {"adicionados","duplicados","invalidos":[{"nome","erro"}]}."""
        adicionados, duplicados, invalidos = 0, 0, []
        with self._trava:
            dados = self._ler()
            existentes = {(i.get("numero"), i.get("texto")) for i in dados["itens"] if i.get("status") in (PENDENTE, ENVIANDO, ENVIADO)}
            for it in itens:
                nome = " ".join(str(it.get("nome") or "").split())
                texto = str(it.get("texto") or "").strip()
                try:
                    numero = normalizar_numero(it.get("numero"))
                    if not texto:
                        raise ValueError("Mensagem vazia.")
                    if len(texto) > LIMITE_TEXTO:
                        raise ValueError(f"Mensagem longa demais (máximo {LIMITE_TEXTO} caracteres).")
                except ValueError as exc:
                    invalidos.append({"nome": nome or str(it.get("numero") or ""), "erro": str(exc)})
                    continue
                if (numero, texto) in existentes:
                    duplicados += 1
                    continue
                existentes.add((numero, texto))
                dados["itens"].append({"id": uuid.uuid4().hex[:12], "numero": numero, "nome": nome, "texto": texto, "origem": origem,
                                       "status": PENDENTE, "tentativas": 0, "erro": "",
                                       "criado_em": self._agora().isoformat(timespec="seconds")})
                adicionados += 1
            if adicionados:
                self._gravar(dados)
        return {"adicionados": adicionados, "duplicados": duplicados, "invalidos": invalidos}

    def _alterar_item(self, id_item: str, de: tuple, para: str, mensagem: str) -> None:
        with self._trava:
            dados = self._ler()
            item = next((i for i in dados["itens"] if i["id"] == id_item), None)
            if item is None:
                raise ValueError("Mensagem não encontrada na fila.")
            if item["status"] not in de:
                raise ValueError(mensagem)
            item.update(status=para, erro="")
            self._gravar(dados)

    def cancelar_item(self, id_item: str) -> None:
        self._alterar_item(id_item, (PENDENTE,), CANCELADO, "Só dá para cancelar o que ainda está pendente.")

    def repetir_item(self, id_item: str) -> None:
        self._alterar_item(id_item, (FALHOU, CANCELADO, SIMULADO), PENDENTE,
                           "Só voltam para a fila as mensagens que falharam, foram canceladas ou só simuladas.")

    def cancelar_pendentes(self) -> int:
        with self._trava:
            dados = self._ler()
            n = 0
            for i in dados["itens"]:
                if i.get("status") == PENDENTE:
                    i["status"] = CANCELADO
                    n += 1
            if n:
                self._gravar(dados)
            return n

    def limpar_historico(self) -> int:
        """Tira da lista o que já terminou (cancelado, simulado, falhou, enviado de dias anteriores). Os enviados de hoje ficam,
        porque contam para o limite do dia; pendentes nunca saem."""
        hoje = self._agora().date().isoformat()
        with self._trava:
            dados = self._ler()
            ficam = [i for i in dados["itens"] if i.get("status") in (PENDENTE, ENVIANDO)
                     or (i.get("status") == ENVIADO and not i.get("simulado") and str(i.get("enviado_em", ""))[:10] == hoje)]
            n = len(dados["itens"]) - len(ficam)
            if n:
                dados["itens"] = ficam
                self._gravar(dados)
            return n

    # ── execução ──
    def iniciar(self) -> str:
        """Começa (ou continua) a enviar. ValueError com o motivo se não dá. Devolve uma frase para a tela."""
        with self._trava:
            if self._rodando():
                return "A fila já está enviando."
            dados = self._ler()
            if not any(i.get("status") == PENDENTE for i in dados["itens"]):
                raise ValueError("Não há mensagens pendentes na fila.")
            prov = self._provedor()
            if prov.nome != "simulado" and not envio_real_autorizado():
                raise ValueError("O envio real está bloqueado. Permita o envio real no cartão \"Mensagem de teste\" e tente de novo.")
            self._parar.clear()
            self._estado, self._mensagem = RODANDO, "Enviando…"
            self._thread = threading.Thread(target=self._executar, name="whatsapp-fila", daemon=True)
            self._thread.start()
        return "Fila iniciada." + (" (Modo simulado: nada sai de verdade.)" if prov.nome == "simulado" else "")

    def pausar(self) -> None:
        """Pede para parar; a mensagem em andamento termina e a fila fica pausada."""
        self._parar.set()
        with self._trava:
            if self._rodando():
                self._mensagem = "Pausando…"

    def esperar_fim(self, timeout: float = 10.0) -> None:
        t = self._thread
        if t:
            t.join(timeout)

    def _dormir(self, segundos: float) -> bool:
        """Espera `segundos`; devolve True se pediram para parar."""
        return self._parar.wait(segundos)

    def _terminar(self, estado: str, mensagem: str) -> None:
        with self._trava:
            self._estado, self._mensagem = estado, mensagem

    def _proximo(self) -> Optional[tuple[dict, dict]]:
        dados = self._ler()
        item = next((i for i in dados["itens"] if i.get("status") == PENDENTE), None)
        return (dados, item) if item else None

    def _executar(self) -> None:
        falhas_seguidas = 0
        try:
            while not self._parar.is_set():
                with self._trava:
                    achou = self._proximo()
                    if achou is None:
                        self._terminar(CONCLUIDA, "Fila concluída: não há mais mensagens pendentes.")
                        return
                    dados, item = achou
                    cfg = self._config(dados)
                    prov = self._provedor()
                    real = prov.nome != "simulado"
                    if real and not envio_real_autorizado():
                        self._terminar(PAUSADA, "Pausada: o envio real foi bloqueado.")
                        return
                    if real and not prov.estado().conectado:
                        self._terminar(PAUSADA, "Pausada: o WhatsApp não está conectado. Conecte e continue.")
                        return
                    if real and self._enviados_hoje(dados) >= cfg["limite_diario"]:
                        if not cfg["continuar_no_dia_seguinte"]:
                            self._terminar(PAUSADA, f"Limite de {cfg['limite_diario']} mensagens por dia atingido. Continue amanhã.")
                            return
                        amanha = (self._agora() + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
                        espera = max(1.0, (amanha - self._agora()).total_seconds())
                        self._estado = AGUARDANDO_DIA
                        self._mensagem = (f"Limite de {cfg['limite_diario']} mensagens por dia atingido. "
                                          f"Retoma sozinha a partir de {amanha.strftime('%d/%m %H:%M')} (com o programa aberto).")
                    else:
                        espera = 0.0
                        self._estado, self._mensagem = RODANDO, f"Enviando para {item.get('nome') or mascarar_numero(item['numero'])}…"
                        item.update(status=ENVIANDO, tentativas=int(item.get("tentativas", 0)) + 1)
                        self._gravar(dados)
                if espera:
                    if self._dormir(min(espera, 60.0)):
                        break
                    continue
                try:
                    r = prov.enviar(item["numero"], item["texto"])
                    ok, simulado, erro, id_msg, aviso = r.ok, bool(r.simulado), r.erro, r.id_mensagem, getattr(r, "aviso", None) or ""
                except EnvioNaoAutorizadoError:
                    self._devolver(item["id"], PENDENTE, "")
                    self._terminar(PAUSADA, "Pausada: o envio real foi bloqueado.")
                    return
                except Exception as exc:                       # noqa: BLE001 — qualquer falha do provedor vira "falhou"
                    ok, simulado, erro, id_msg, aviso = False, False, f"{type(exc).__name__}: {exc}", None, ""
                if ok:
                    falhas_seguidas = 0
                    self._registrar(item["id"], SIMULADO if simulado else ENVIADO, "", simulado, id_msg, aviso)
                else:
                    falhas_seguidas += 1
                    self._registrar(item["id"], FALHOU, str(erro or "Falha desconhecida."), False, None)
                    if falhas_seguidas >= FALHAS_SEGUIDAS_MAX:
                        self._terminar(PAUSADA, f"Pausada depois de {FALHAS_SEGUIDAS_MAX} falhas seguidas (última: {erro}).")
                        return
                with self._trava:
                    resta = self._proximo() is not None
                if resta and self._dormir(PAUSA_SIMULADO_S if simulado else cfg["intervalo_s"]):
                    break
            self._terminar(PAUSADA, "Fila pausada. Continue quando quiser.")
        except Exception as exc:                               # noqa: BLE001 — a thread nunca morre calada
            self._terminar(PAUSADA, f"Pausada por erro: {exc}")

    def _registrar(self, id_item: str, status: str, erro: str, simulado: bool, id_mensagem, aviso: str = "") -> None:
        with self._trava:
            dados = self._ler()
            for i in dados["itens"]:
                if i["id"] == id_item:
                    i.update(status=status, erro=erro, simulado=simulado, id_mensagem=id_mensagem, aviso=aviso)
                    if status in (ENVIADO, SIMULADO):
                        i["enviado_em"] = self._agora().isoformat(timespec="seconds")
            self._gravar(dados)

    def _devolver(self, id_item: str, status: str, erro: str) -> None:
        with self._trava:
            dados = self._ler()
            for i in dados["itens"]:
                if i["id"] == id_item:
                    i.update(status=status, erro=erro, tentativas=max(0, int(i.get("tentativas", 1)) - 1))
            self._gravar(dados)


_instancia: Optional[FilaWhatsApp] = None
_trava_instancia = threading.Lock()


def obter_fila() -> FilaWhatsApp:
    global _instancia
    with _trava_instancia:
        if _instancia is None:
            _instancia = FilaWhatsApp()
        return _instancia

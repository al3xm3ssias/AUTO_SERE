"""
envia_email.py — Utilitário de envio de e-mail via SMTP (Gmail)
=============================================================================
Portado de AUTO_SERE/envia_email.py para src/automacao/envia_email.py.

O script original era um teste único de conectividade SMTP (destinatário,
assunto e corpo fixos no código, junto com as credenciais). Este módulo
generaliza isso num utilitário real e reutilizável de envio, mantendo a
mesma lógica de conexão (STARTTLS na porta 587, autenticação, envio de
texto puro).

⚠️ CORREÇÃO DE SEGURANÇA (confirmada com o usuário em 04/09/2026): o
original tinha uma SENHA DE APLICATIVO DO GMAIL EM TEXTO PURO no
código-fonte, para a conta institucional judith@pontagrossa.pr.gov.br. O
usuário confirmou que essa senha específica já foi/será revogada — o
valor real NUNCA foi copiado para este projeto. As credenciais agora vêm
de src.comum.credenciais.EMAIL_REMETENTE/EMAIL_SENHA_APP (variáveis de
ambiente EMAIL_REMETENTE/EMAIL_SENHA_APP em credenciais/.env), o mesmo
padrão já usado para SERE e Pré-Matrícula. NUNCA reintroduza uma senha de
aplicativo diretamente no código.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. Credenciais: EMAIL_REMETENTE/SENHA fixas no código → lidas de
   src.comum.credenciais (ver correção de segurança acima).

2. Destinatário/assunto/corpo: antes fixos (hardcoded) como constantes de
   módulo — decisão do usuário (04/09/2026): agora são parâmetros da
   função enviar_email(), tornando o script um utilitário real (pode
   enviar qualquer e-mail), não só um teste de conectividade fixo.

3. Todo o corpo (antes rodando solto no nível do módulo, sem função nem
   `if __name__ == "__main__":`) foi envolvido em enviar_email(...) —
   mesma decisão já aplicada a outros scripts que rodavam soltos no nível
   do módulo (ex.: src.comum.cep_api): pronta para ser chamada por outro
   script ou por uma futura interface, sem efeito colateral ao importar
   o módulo.

Toda a lógica de envio (STARTTLS, MIMEMultipart/MIMEText, tratamento de
erro genérico) é idêntica ao original — nenhuma regra foi alterada.

Uso:
    from src.automacao.envia_email import enviar_email

    ok, erro = enviar_email(
        destinatario="alguem@exemplo.com",
        assunto="Assunto do e-mail",
        corpo="Corpo do e-mail em texto puro.",
    )
"""

from __future__ import annotations

import mimetypes
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, Optional

from src.comum.credenciais import EMAIL_REMETENTE, EMAIL_SENHA_APP

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def enviar_email(
    destinatario: str,
    assunto: str,
    corpo: str,
    remetente: Optional[str] = None,
    senha_app: Optional[str] = None,
    anexos: Optional[Iterable] = None,
) -> tuple[bool, Optional[str]]:
    """
    Envia um e-mail de texto puro via SMTP (Gmail, porta 587, STARTTLS).

    `remetente`/`senha_app`: se omitidos, usam
    src.comum.credenciais.EMAIL_REMETENTE/EMAIL_SENHA_APP (configurados
    via credenciais/.env — ver .env.example). Aceitos como parâmetros
    explícitos para permitir enviar de uma conta diferente da configurada
    globalmente, se necessário.

    `anexos`: caminhos de arquivos a anexar (ex.: o PDF do parecer). Um anexo que não existe falha o envio, com a
    mensagem no retorno, em vez de mandar o e-mail sem ele.

    Retorna (sucesso: bool, erro: str | None) — nunca levanta exceção
    para falhas de conexão/autenticação/envio (mesmo comportamento do
    original: captura a exceção genérica e reporta), para que quem chamar
    decida como tratar (log, nova tentativa, aviso na interface).
    """
    remetente = remetente or EMAIL_REMETENTE
    senha_app = senha_app or EMAIL_SENHA_APP

    msg = MIMEMultipart()
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "plain"))

    for anexo in anexos or []:
        caminho = Path(anexo)
        try:
            conteudo = caminho.read_bytes()
        except OSError as e:
            print(f"❌ Anexo não pôde ser lido: {caminho} ({e})")
            return False, f"anexo não encontrado ou ilegível: {caminho.name} ({e})"
        subtipo = (mimetypes.guess_type(caminho.name)[0] or "application/octet-stream").split("/")[-1]
        parte = MIMEApplication(conteudo, _subtype=subtipo)
        parte.add_header("Content-Disposition", "attachment", filename=caminho.name)
        msg.attach(parte)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(remetente, senha_app)
        server.sendmail(remetente, destinatario, msg.as_string())
        server.quit()

        print("✅ E-mail enviado com sucesso!")
        return True, None

    except Exception as e:
        print(f"❌ Falha ao enviar: {e}")
        return False, str(e)


if __name__ == "__main__":
    enviar_email(
        destinatario="destinatario@exemplo.com",
        assunto="Teste",
        corpo="Mensagem de teste enviada pelo utilitário envia_email.",
    )

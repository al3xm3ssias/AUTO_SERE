"""
src.seguranca — acesso ao AUTO SERE: usuários, senhas, sessões e proteção da interface web
==========================================================================================
Camadas (de dentro para fora):

  senhas.py     senha → hash Argon2id (com sal próprio) + chave secreta local ("pimenta"); política de senha forte
  segredo.py    a pimenta e a proteção do arquivo pelo Windows (DPAPI); trava a pasta credenciais/ ao usuário atual
  usuarios.py   cadastro (credenciais/usuarios.json): 1º administrador, perfis, bloqueio por tentativas, troca de senha
  sessoes.py    sessão no servidor (cookie opaco), expira por inatividade e por duração máxima
  limite.py     limite de tentativas por endereço (contra adivinhação de senha)
  auditoria.py  registro de eventos de segurança em logs/auditoria.log, encadeado por hash (detecta adulteração)
  politica.py   quem pode chamar o quê (administrador / operador / consulta)
  web.py        a integração com o Flask: guarda de login, CSRF, Host/Origin, cabeçalhos, páginas e rotas
  cli.py        python -m src.seguranca ... (usado pelo instalador para criar o administrador)

Nada aqui grava senha em texto: só o hash. A senha digitada nunca vai para log, auditoria ou resposta da API.
"""

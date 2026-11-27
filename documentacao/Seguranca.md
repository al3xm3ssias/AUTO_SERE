# Segurança: login, usuários e proteção da interface

Implementado em 2026-11-24 (item 2c-3 das `pendencias.md`, sem a parte "ligar a senha à chave dos dados"). Código em `src/seguranca/`; telas em `src/web/templates/auth/`; testes em `tests/test_seguranca_nucleo.py` e `tests/test_seguranca_web.py`.

## Primeiro uso: o administrador

- **Na instalação** (`INSTALAR_WINDOWS.bat`, passo 6/7): o instalador pede o nome de usuário (Enter = `admin`), o nome completo e a senha duas vezes, sem mostrar a senha. Esse primeiro usuário é o **administrador**. Reexecutar a instalação não pede de novo.
- **Se não foi criado na instalação** (instalação sem janela, ou cancelada): a primeira vez que o sistema abre aparece a tela **Criar o administrador**. Ela só existe enquanto não há nenhum usuário e só responde ao próprio computador.
- Pela linha de comando: `python -m src.seguranca criar-admin`.

## Como a senha é guardada

A senha **não é criptografada, é transformada em hash** (uma impressão digital que não volta para a senha): nem o sistema consegue ler ou mostrar uma senha. Isso é mais seguro do que criptografar.

1. a senha é normalizada (Unicode) e misturada a uma **chave secreta local** (a "pimenta", 32 bytes aleatórios, `credenciais/seguranca/pimenta.bin`) com HMAC-SHA256;
2. o resultado passa por **Argon2id** (128 MiB de memória, 3 passadas, 4 trilhas, ~0,4 s por tentativa), com **sal aleatório** próprio de cada senha;
3. só o hash vai para `credenciais/usuarios.json` (permissão 600; no Windows a pasta `credenciais\` é restrita ao seu usuário).

No Windows a pimenta é cifrada pela conta do Windows (DPAPI): quem copiar só a pasta `credenciais\` para outro computador não consegue sequer tentar adivinhar senhas. Os parâmetros podem subir no futuro: o hash antigo continua valendo e é refeito na próxima entrada. Sem a biblioteca `argon2-cffi` o sistema usa scrypt (custo equivalente) e converte depois.

**Política de senha:** 12 a 128 caracteres; 3 tipos entre minúsculas, MAIÚSCULAS, números e símbolos (ou frase de 16+ caracteres); sem o nome de usuário ou do dono; sem sequências (`123456…`, `qwerty…`), repetições nem senhas comuns.

## Perfis

| Perfil | Pode |
|---|---|
| **Administrador** | tudo: usuários, auditoria, senhas e integrações (SERE, Gmail, Google, WhatsApp), data de corte, restaurar ano letivo, assistente de 1ª execução, escolher pastas |
| **Operador** | o dia a dia: executar automações, editar registros, enviar mensagens, trocar o ano letivo para consultar, "Turmas do QR antigo" |
| **Consulta** | só ver telas e tabelas |
| **Pedagoga** | perfil **independente** (fora da escada acima): só consulta **Painel, Turmas, Alunos e Encaminhamentos SUS** e executa **apenas** as coletas **Turmas** (`turmas.py`) e **Alunos** (modo básico `alunos.py` e completo `alunos_completo.py`) |

### Perfil Pedagoga

- **Lista de permissões, não escada.** Em `politica.py`, `_REGRAS_PEDAGOGA` enumera o que ela pode chamar; **tudo o que não está na lista é negado** (403), inclusive rotas criadas no futuro. O teste `tests/test_perfil_pedagoga.py` percorre todas as rotas do app e trava a lista.
- **Validado no servidor**, no mesmo guarda de toda requisição, e de novo na própria rota de execução (`automacoes_executar`). Esconder menu é só vitrine: o HTML dela já nasce sem as telas e automações proibidas, e o painel principal é reduzido no servidor (sem pré-matrícula, documentos, raio nem transferidos).
- **Somente leitura.** Ela não grava registro nem configuração, não apaga histórico, não salva opções do script nem navegador, não envia mensagem. Só troca a **própria** senha. As coletas Turmas e Alunos apenas **leem** do SERE (navegam e consultam; não enviam, alteram nem apagam nada lá) e atualizam o cache local (`turmas.json`, `alunos.json`, `alunos_completo.json`).
- **Configurações** que ela vê, em **somente consulta**: Dados da escola, Ano letivo, Navegador, Backup automático e Senha do SERE (a senha nunca é mostrada), mais Minha conta, Temas e Perfil. Quem grava é o administrador.
- Para liberar mais algo: `AUTOMACOES_PEDAGOGA`, `TELAS_PEDAGOGA`, `CONFIGURACOES_PEDAGOGA` e `_REGRAS_PEDAGOGA` em `src/seguranca/politica.py` (e atualizar `PERMITIDAS` no teste).
- Criação: na **instalação**, depois de criar o administrador, o instalador pergunta "Deseja cadastrar agora um usuário com o perfil PEDAGOGA? (S/N)" (o primeiro usuário é sempre administrador). Ou, a qualquer hora, `python -m src.seguranca criar-usuario --perfil pedagoga`, ou Configurações → Usuários e segurança (perfil "Pedagoga"). Mudar o perfil derruba a sessão na hora.
- Limite: a linha de comando e o Agendador (`python -m src.comum.cli`) não passam pelo login, então não têm perfil. A Central de ajuda (F1) mostra a ela só os textos das telas, automações e configurações que ela usa.

A regra está em **um lugar só** (`src/seguranca/politica.py`) e vale para toda rota, inclusive as que alguém criar depois. Mudar o perfil, desativar ou apagar um usuário **derruba a sessão dele na hora**. Nunca fica sem administrador ativo (o sistema não deixa apagar, desativar ou rebaixar o último). Tenha pelo menos dois administradores.

## O que protege a interface

- **Login obrigatório** em todas as páginas e rotas. Exceções: tela de entrada, criação do 1º administrador, arquivos estáticos, `/web/api/ping` (usado pelo launcher; sem dados) e o webhook do WhatsApp (que tem token próprio).
- **Sessão no servidor**, cookie aleatório de 256 bits (`HttpOnly`, `SameSite=Strict`); só o SHA-256 do código fica na memória. Expira por **inatividade** (30 min no servidor; a tela sai sozinha após ~28 min sem mouse/teclado) e por **duração máxima** (12 h). Reiniciar o servidor encerra todas. Cada login gera código novo (sem fixação de sessão); trocar a senha derruba as outras sessões.
- **Bloqueio por tentativas**: 5 senhas erradas seguidas bloqueiam o usuário por 15 min; a cada novo bloqueio o tempo dobra (até 24 h). Mais: no máximo 10 erros de entrada por endereço a cada 5 min. A mensagem de erro é sempre a mesma, exista o usuário ou não, e demora o mesmo tempo.
- **CSRF**: toda escrita exige o cabeçalho `X-CSRF-Token` da sessão (o `seguranca.js` o põe em todo `fetch`), além de checar `Origin`/`Referer`/`Sec-Fetch-Site`.
- **Host**: só `127.0.0.1`, `localhost`, `::1`, IPs literais ou o host configurado; barra "DNS rebinding". `host.docker.internal` só vale no webhook do WhatsApp.
- **Cabeçalhos**: Content-Security-Policy estrita (só scripts do próprio sistema; por isso não há mais `onclick` nem script inline), `X-Frame-Options: DENY`, `nosniff`, sem Referer, **sem cache** das respostas (dados de alunos).
- **Servidor só em `127.0.0.1`** por padrão (`src/comum/servidor.py`). Se algum dia precisar de outra máquina da rede, o tráfego seria HTTP puro: acrescente o nome em `seguranca.hosts_permitidos` e prefira uma VPN ou um proxy com HTTPS.

## Auditoria

`logs/auditoria.log`: uma linha por evento (entradas, recusas, bloqueios, trocas de senha, mudanças de usuário, acessos negados, CSRF e Host recusados). **Nunca** tem senha, hash ou token. As linhas formam uma corrente de hashes: apagar ou editar uma linha do meio quebra a corrente (`python -m src.seguranca verificar-auditoria`, ou o painel Usuários e segurança). Apagar o arquivo inteiro ou cortar o final não é detectado: para isso, guarde cópia fora do computador.

## Esqueci a senha

- **Usuário comum**: um administrador faz **Redefinir senha** (gera uma temporária; a pessoa é obrigada a trocar no 1º acesso).
- **Único administrador** (ou todos): no computador do sistema, `python -m src.seguranca redefinir-senha --usuario admin`. Exige estar no computador, não pede a senha antiga e fica registrada na auditoria.
- **"A chave de proteção das senhas não pode ser lida"** (perfil do Windows refeito, pasta copiada para outro PC): use `redefinir-senha --regenerar-chave`. Atenção: as senhas de todos os **outros** usuários deixam de valer e um administrador precisa redefinir cada uma.
- **Arquivo `usuarios.json` ilegível**: ninguém entra (de propósito: um arquivo estragado nunca reabre a tela de criação do administrador). Restaure `credenciais/usuarios.json.bak`, ou rode `redefinir-senha --usuario admin --criar`, que põe os arquivos ruins de lado e cria o administrador de novo.

Outros comandos: `existe`, `listar`, `desbloquear USUARIO`, `proteger-pasta`.

## Ajustes (config/config_usuario.json)

```json
"seguranca": { "inatividade_min": 30, "duracao_max_horas": 12, "hosts_permitidos": [] }
```

Limites: inatividade de 5 min a 8 h; duração de 1 a 24 h. Não existe chave nem variável de ambiente que desligue o login.

## O que isto NÃO faz (limites combinados na seção 2c das pendências)

- **Não cifra os dados em disco.** Quem tem acesso ao Windows ou ao disco ainda lê os JSONs, os PDFs e `credenciais/.env` (senhas do SERE, Gmail, RCO, pré-matrícula, token do Google, `chave_qr.key`). A pasta `credenciais\` fica restrita ao seu usuário do Windows, o que ajuda, mas não substitui cifrar (itens 2c-1 e 2c-2) nem o BitLocker.
- A senha do login **ainda não é a chave** que destrava os dados; por isso a recuperação pela linha de comando não perde dado nenhum. Quando o 2c-2 existir, a redefinição passará a depender da frase de recuperação.
- Não há autenticação em dois fatores.
- As automações agendadas (Agendador do Windows) rodam sem login: elas não passam pela interface web.
- A proteção da pimenta pelo DPAPI só funciona no Windows; nos testes (Linux) ela fica em arquivo com permissão 600.

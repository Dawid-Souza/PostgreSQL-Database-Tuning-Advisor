# Segurança

O PostgreSQL Database Tuning Advisor roda na estação de quem administra o PostgreSQL. Ele guarda segredo em disco cifrado, abre SSH quando o operador confirma e lê o catálogo com o usuário que você cadastrou. Esta página descreve o que o código faz e o que continua com o operador.

## Superfície

| Controle | Onde está |
| --- | --- |
| Bind | `start.bat` e `start.ps1` usam `--host 127.0.0.1 --port 8000` |
| Autenticação da interface | Inativa. `app/security/auth.py` define `login_enabled()` como falso |
| OpenAPI | `/docs`, `/redoc` e `/openapi.json` seguem o padrão do FastAPI |
| Health | `GET /health` responde `ok` sem consultar banco |

Quem consegue abrir `http://127.0.0.1:8000` nesta máquina consegue ver metadados de host, disparar a coleta SSH já configurada e ler o catálogo com as credenciais do cofre. Não publique a porta. Se um dia o bind mudar para outra interface, coloque autenticação e TLS na frente antes de qualquer outra pessoa alcançar o processo.

A página `/login-settings` lista os prefixos que um login futuro deve proteger: `/`, `/environments`, `/postgres`, `/catalog`, `/query`, `/logs` e `/history`. O middleware de sessão ainda não está instalado. `get_current_user` engole a falta de sessão e devolve um usuário local anônimo. Nenhuma rota chama esse gancho hoje.

## Cofre

`app/security/secret_vault.py` grava `data/secrets.json`.

- O arquivo tem `version`, `salt` (16 bytes) e `items`.
- A chave Fernet sai de PBKDF2-HMAC-SHA256 sobre `APP_SECRET`, com o salt do arquivo e 390.000 iterações.
- Cada valor é um token Fernet. A chave lógica (`postgres:<uuid>:password`, e as demais listadas em [arquitetura.md](arquitetura.md)) fica em claro no JSON. O segredo não.
- Token que não abre com a chave atual vira ausência (`InvalidToken`). A interface trata isso como senha a recadastrar.
- Trocar `APP_SECRET` ou apagar o salt invalida os itens existentes. Não há migração de chave.

O processo também mantém os valores decifrados em memória depois da primeira leitura, para redigir saídas. Encerrar o processo solta essa cópia. O arquivo cifrado permanece.

`data/environment_configs.json` pode conter host, login, caminho de chave privada, nome de container e prévia de DSN. Trate o arquivo como dado operacional da estação. O `.gitignore` exclui `data/` e `.env`.

Excluir um ambiente ou uma conexão na interface não remove os tokens daquele `id` no cofre. Para tirar a senha do disco, apague o item em `secrets.json` com o processo parado, ou troque o `APP_SECRET` e aceite recadastrar tudo. Enquanto o token existir e a chave for a mesma, o valor ainda abre.

Não coloque senha, token ou chave privada no `.env`, no README ou no JSON de configuração. O único segredo previsto no `.env` é o `APP_SECRET`.

## Redação

Antes de gravar comando, erro de coleta ou prévia de conexão, o texto passa por `redact_text`:

- cada segredo conhecido com 4 ou mais caracteres é substituído por `[REDACTED]`;
- um trecho `:segredo@` em URL vira `:[REDACTED]@`;
- pares `password`, `passwd`, `pwd`, `token` ou `secret` seguidos de `=` ou `:` têm o valor trocado.

A prévia de DSN com `://` ainda remove a senha via parse de URL quando o formato é padrão.

Redação não é criptografia do histórico. Uma query lenta pode conter dados de cliente dentro do SQL. O SQLite local guarda a amostra da query. Proteja a pasta `data/` com o mesmo cuidado da estação.

## SSH

A coleta só abre conexão quando a ação é `fetch` e o checkbox de confirmação veio marcado (`confirm_execution=on`). A prévia não conecta.

Paramiko é criado com `AutoAddPolicy`: a chave de host apresentada na primeira conexão é aceita e entradas posteriores seguem o que o Paramiko gravar naquele uso. Confira host e porta no cadastro antes de salvar a senha. Numa rede em que o IP pode ser respondido por outra máquina, essa política não detecta troca de host.

A chave privada, no método `key`, é lida do caminho local informado. O arquivo da chave não é copiado para `data/`. Quem usa a estação e alcança o painel alcança esse caminho através do Paramiko, no momento da coleta.

Sudo usa `sudo -S -p ''`. A senha vai no stdin do comando remoto. Ela não entra no comando exibido. O comando customizado é concatenado depois do prefixo sudo quando "Usar sudo" está ligado, então o texto digitado também roda elevado.

Comando customizado e comando base são shell remoto sob o login SSH. Não há lista de comandos permitidos. Cadastre nesse campo só o que você digitaria numa sessão SSH sua, e restrinja o uso do painel a operadores que já têm esse acesso.

Stderr e stdout voltam para a estação e podem ser gravados no SQLite depois da redação. Um log de erro do PostgreSQL às vezes repete parâmetros de conexão. Vale olhar a run antes de exportar o `app.sqlite3`.

## PostgreSQL

A senha segue como parâmetro do conninfo, separada da URL, no modo de campos. No DSN manual, senha embutida vai inteira para o cofre e a prévia no JSON fica mascarada.

As consultas de catálogo e o `EXPLAIN` sem `ANALYZE` não alteram dados de usuário. `EXPLAIN ANALYZE` executa a query. A tela limita esse modo a `SELECT` e `WITH`, e recusa DDL e DML óbvios no começo do texto. Isso reduz acidente operacional. Não substitui um papel de banco só de leitura: um `SELECT` pode chamar função com efeito, e o papel cadastrado é o que manda.

Índice, `ANALYZE` e `DROP INDEX` aparecem como texto. Copiar e executar é decisão do DBA, de preferência com o `CONCURRENTLY` fora de transação e com o plano conferido.

## O que conferir antes de usar numa estação compartilhada

1. `APP_SECRET` único, fora do valor de `.env.example`.
2. Pasta do projeto com permissão só do operador.
3. Bind mantido em `127.0.0.1`.
4. Papel PostgreSQL limitado aos databases que o diagnóstico precisa ver.
5. Chave SSH com passphrase e arquivo protegido, quando o método for chave. O Paramiko usa o caminho informado. Passphrase de chave não tem campo próprio na tela.
6. Comando customizado de log revisado na prévia, com a confirmação desmarcada, antes da primeira execução.

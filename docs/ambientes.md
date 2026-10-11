# Ambientes e conexões

O ambiente descreve **como chegar no host** para ler log. A conexão PostgreSQL descreve **como falar com o banco**. As telas de diagnóstico usam a conexão. A busca SSH de log usa o ambiente. Os dois ficam amarrados: uma conexão pertence a exatamente um ambiente, e o ambiente ativo pode ter várias conexões.

## Ambiente

Tela `/environments`. Tipos:

| Tipo | Valor gravado | Uso |
| --- | --- | --- |
| Container | `container` | O PostgreSQL (ou o processo que escreve o log) está num container Docker ou Podman nesse host |
| Instalação direta no servidor/VM | `direct` | Pacote, compilado ou VM, com log em arquivo ou no journal |

Campos gerais:

| Campo | Regra |
| --- | --- |
| Nome | Obrigatório na prática. Vazio vira "Ambiente sem nome" |
| Host/IP | Obrigatório para executar SSH |
| Porta SSH | 1–65535, padrão 22 |
| Login SSH | Obrigatório para executar SSH |
| Método SSH | `password` ou `key` |
| Senha SSH | Gravada no cofre. Em branco na edição conserva a senha já salva |
| Caminho da chave privada | Obrigatório quando o método é chave. É um caminho na máquina do painel, lido pelo Paramiko |
| Caminho base da aplicação | Metadado livre, não entra no comando automático |
| Timeout de conexão | 1–300 segundos, padrão 20. O comando remoto usa o triplo desse valor, com piso de 30 segundos |
| Observações | Texto livre |

Sudo:

| Campo | Efeito |
| --- | --- |
| Usar sudo | Prefixa o comando com `sudo -S -p ''`. Se houver usuário sudo, o prefixo inclui `-u` |
| Usuário sudo | Vazio mantém o usuário do login SSH elevado pelo sudo padrão |
| Usar mesma senha do SSH para sudo | A senha enviada ao `sudo -S` é a senha SSH |
| Senha sudo | Usada só quando sudo está ligado e a caixa acima está desmarcada |

Container (relevante no tipo container e no modo de log de container):

| Campo | Efeito |
| --- | --- |
| Nome ou ID do container | Obrigatório para buscar log de ambiente container |
| Runtime | `docker` ou `podman`. Qualquer outro texto cai em `docker` na hora de montar o comando |
| Diretório interno | Usado só com exec. Vazio vira `/` |
| Usuário interno | Vira `--user` no exec |
| Usar docker exec/podman exec | Troca `docker logs` por `exec` + `tail` |

### Como o comando de log é escolhido

A função `build_log_command` segue esta ordem. O primeiro caso que se aplica ganha.

1. **Comando customizado preenchido.** O texto é usado como está, com `{lines}` trocado pela quantidade pedida. Isso vale mesmo que o modo escolhido seja outro.
2. **Comando base preenchido.** Substitui `{lines}`, `{container}` e `{runtime}`.
3. **Tipo container e modo container.** Sem a caixa de exec: `<runtime> logs --tail <linhas> <container> 2>&1`. Com exec e arquivo de log: `exec` entra no container, faz `cd` no diretório interno e roda `tail`. Com exec e sem arquivo: o comando interno é `ls -la` naquele diretório, útil para achar o caminho antes de fixar o arquivo.
4. **Modo arquivo, ou instalação direta.** Com arquivo de log: `tail -n <linhas> <arquivo>`. Sem arquivo, no tipo direto: um script que procura o log mais recente. Sem arquivo e fora do tipo direto: a montagem falha e pede arquivo ou comando.

O modo `container` num ambiente `direct` é tratado como `file` antes dessa escolha.

O script da instalação direta, quando não há arquivo informado:

- consulta `pg_lsclusters -h`, se o binário existir, e fica com a última coluna (diretório de dados do cluster Debian/Ubuntu);
- procura arquivos nestes globs: `/var/log/postgresql/*.log`, `postgresql-*.log`, `/var/log/pgsql/*.log`, `/var/log/postgres/*.log`, `/var/lib/pgsql/*/data/log/*.log`, `/var/lib/pgsql/*/data/pg_log/*.log`, `/var/lib/postgresql/*/*/log/*.log` e `pg_log` equivalente;
- escolhe o arquivo regular com maior `mtime` (`stat -c %Y`);
- se nada for arquivo, tenta `journalctl -u` para `postgresql`, `postgresql.service` e `postgresql-*`;
- se ainda assim não houver log, termina com código 2 e uma mensagem pedindo arquivo ou comando customizado.

O script escreve em stderr a linha `[pg_dta] log_file=<caminho>` quando acha um arquivo. Essa linha pode aparecer no erro ou no texto coletado, porque stderr também é lido.

Placeholders aceitos no comando base e, para `{lines}`, no comando customizado:

| Token | Troca |
| --- | --- |
| `{lines}` | Inteiro entre 100 e 200.000. Fora da faixa, o serviço corta para esses limites. O padrão do formulário de ambiente é 5.000 |
| `{container}` | Nome do container, sem aspas adicionais neste token |
| `{runtime}` | Valor do campo runtime, ou `docker` |

Argumentos montados pelo próprio serviço (arquivo, container, usuário, diretório) passam por `shlex.quote`. O comando customizado e o comando base são texto do operador: aspas e encadeamento ficam como foram digitados.

O prefixo sudo, quando ligado, é colado na frente do comando inteiro.

### Limite de bytes do ambiente

**Limite máximo de bytes** no cadastro: `0` desliga o corte. O formulário de ambiente grava no máximo 512 MiB (`512 * 1024 * 1024`). A tela de logs pode informar outro valor só para aquela coleta. Ver [logs.md](logs.md).

**Linhas padrão** do ambiente ficam entre 100 e 200.000. A tela de logs tem o próprio campo **Linhas finais**, que é o valor usado naquela busca.

## Conexão PostgreSQL

Tela `/postgres`. A lista mostra só conexões do ambiente ativo. O formulário pede o ambiente dono. Se o campo vier vazio, a conexão fica no ambiente ativo, ou no ambiente que ela já tinha.

| Campo | Regra |
| --- | --- |
| Nome | Vazio vira "PostgreSQL sem nome" |
| Host | Padrão de conexão `localhost` se ficar vazio na hora de conectar |
| Porta | 1–65535, padrão 5432 |
| Banco padrão | Padrão `postgres`. É o database inicial do conninfo e o fallback do seletor |
| Usuário | Vai no parâmetro `user` |
| Senha | Cofre. Em branco na edição conserva a anterior |
| Timeout de conexão | 1–120 segundos, padrão 10 |
| SSL mode | `prefer` (padrão), `disable`, `require`, `verify-ca`, `verify-full` |

Salvar fecha o cache local daquela conexão, monta uma prévia redigida e executa o teste (`version`, database, usuário, endereço e porta do servidor). Sucesso mostra "Conexão salva e testada com sucesso". Falha mantém o cadastro e mostra o erro redigido.

**Testar** repete o teste sem passar pelo salvamento. **Selecionar** torna a conexão a ativa e também limpa o cache dela.

### Campos separados e DSN manual

O modo normal monta o conninfo com `host`, `port`, `dbname`, `user`, `password`, `connect_timeout` e `sslmode`. A senha não entra numa URL, então `$`, `#`, `@`, `:`, `/`, `%`, espaço e aspas não precisam de encode.

**Usar DSN manual avançado** troca a base da conexão pelo texto do campo DSN. O timeout da tela continua sobrescrevendo `connect_timeout`. A senha do campo **Senha**, se houver, também sobrescreve. O banco escolhido no topo sobrescreve `dbname` durante as análises.

Se o DSN tiver senha na URL (`usuario:senha@host`) ou um `password=`, o texto inteiro vai para o cofre e a prévia gravada no JSON já sai redigida. Um DSN sem esses sinais fica só como prévia no JSON. Na edição, um DSN que contém `[REDACTED]` não substitui o segredo anterior: é a prévia mascarada de volta no formulário.

Quando `use_manual_dsn` está ligado e o cofre não devolve o DSN, a conexão tenta a prévia. Se essa prévia contiver `[REDACTED]`, a operação para com o pedido para informar o DSN de novo.

### Teste e prévia

A prévia mostrada na tela passa por `redact_text` com todos os segredos conhecidos do cofre. Ela serve para conferir host, porta, usuário e database. Ela não é um segredo para colar em ticket: ainda pode carregar opções que você tenha posto no DSN manual.

`inet_server_addr()` volta nulo em conexão por socket local. A interface mostra esse caso como endereço indisponível.

# Logs

A tela `/logs` transforma texto de log do PostgreSQL em grupos de query e em recomendações de índice. O texto pode ser colado ou lido por SSH no ambiente selecionado. O resultado fica em `data/app.sqlite3`.

A recomendação usa o banco escolhido no topo para resolver tabela, coluna, índice e estatística. Log de um database analisado com outro banco selecionado produz cartões "tabela não localizada".

## Formato reconhecido

O parser varre o texto linha a linha. Uma linha entra quando contém:

```text
duration: <número> ms  statement: <sql>
duration: <número> ms  execute <nome>: <sql>
```

A busca é case insensitive. O número aceita decimal (`1234.567`). Se a linha tem `duration:` e `ms` mas não casa com `statement:` nem com `execute`, o restante da linha ainda vira a query, e um prefixo `statement:` solto é removido.

Linhas seguintes, não vazias, até a próxima duração, continuam a mesma query. A soma do texto acumulado para em 20.000 caracteres. Linha em branco não entra no miolo.

Esse formato é o de `log_min_duration_statement` (e de `auto_explain` quando a linha segue o mesmo desenho). Sem a palavra `duration:`, o arquivo é ignorado: entradas ficam em zero e nenhuma recomendação nasce. CSV do `pg_stat_statements` e log JSON do PostgreSQL 15+ não são o formato desta tela.

Exemplo mínimo:

```text
2026-10-11 10:00:01 UTC [1234] user=app,db=loja LOG:  duration: 842.120 ms  statement: SELECT *
    FROM pedidos p
    WHERE p.cliente_id = 10
2026-10-11 10:00:02 UTC [1234] user=app,db=loja LOG:  duration: 15.5 ms  statement: SELECT 1
```

Com **Ignorar abaixo de ms** em `100`, a segunda entrada conta como ignorada. A primeira vira um grupo.

## Agrupamento

A chave do grupo é a query normalizada (ver [recomendacoes.md](recomendacoes.md)). Cada grupo guarda:

| Campo | Significado |
| --- | --- |
| `calls` | Quantidade de entradas no grupo |
| `total_ms` | Soma das durações |
| `mean_ms` | `total_ms / calls`, duas casas |
| `max_ms` | Maior duração do grupo |
| `sample_query` | Texto da primeira ocorrência, até 20.000 caracteres |
| `normalized_query` | Chave, até 1.000 caracteres |

A tabela da tela ordena por `total_ms` decrescente. A paginação usa `LOG_CACHE_PAGE_SIZE` (padrão 50).

## Recomendações a partir do log

Só os primeiros `MAX_LOG_RECOMMENDATION_GROUPS` grupos (padrão 250, piso interno 10) são lidos. Em cada um, o parser extrai tabela e colunas. Pares já vistos são pulados. Cada par novo chama `build_index_recommendation` com `source=slow_log_cache` e `weight_ms` igual ao `total_ms` do grupo. O teto é `MAX_LOG_RECOMMENDATIONS` (padrão 250, piso interno 10).

Acima de 30.000 ms no grupo, o score sobe e a severidade vai para `high`, se o candidato não tiver sido descartado como redundante. O detalhe do score está em [recomendacoes.md](recomendacoes.md).

Falha ao resolver a tabela não interrompe a run: o cartão sai com confiança baixa.

## Busca SSH

Formulário **Buscar por SSH**, `POST /logs/fetch`.

| Campo | Efeito |
| --- | --- |
| Linhas finais | Repassado ao comando. O serviço limita a 100–200.000. Padrão visual 5.000 |
| Ignorar abaixo de ms | Filtro do parser, não do `tail` |
| Limite máximo de bytes | Corte da leitura no painel. `0` lê até o comando acabar. O valor inicial vem de `max_bytes` do ambiente, ou de `MAX_LOG_FETCH_BYTES` se o ambiente não tiver o campo |
| Confirmação | Obrigatória para o botão **Buscar e analisar** |
| Ação | `preview` mostra o comando. `fetch` conecta |

Sem ambiente selecionado, a página responde "Selecione um ambiente antes de buscar logs."

**Mostrar comando** chama `command_preview`. Não há socket SSH. Segredos conhecidos no texto do comando saem como `[REDACTED]`.

**Buscar e analisar** sem a caixa marcada devolve o comando e o erro "Execução remota não confirmada. O comando foi apenas gerado para revisão." Nada é gravado no histórico nesse caso.

Com a caixa marcada, a execução ainda exige:

- host e login SSH;
- senha presente no cofre, quando o método é senha e o cadastro diz que há senha;
- caminho da chave, quando o método é chave;
- senha sudo no cofre, quando sudo está ligado, não reutiliza a senha SSH, e o cadastro diz que há senha sudo;
- nome do container, quando o tipo é container.

A sessão Paramiko usa porta, login e timeout do ambiente. A política de chave de host é `AutoAddPolicy` (ver [seguranca.md](seguranca.md)). Método chave usa `key_filename`. Método senha usa a senha do cofre quando ela existe. Timeout do `exec_command`: no mínimo 30 segundos, ou três vezes o timeout do ambiente.

Se o comando contém `sudo -S` ou o ambiente pediu sudo, a senha sudo (ou a senha SSH, se essa opção estiver marcada) é escrita no stdin seguida de nova linha. Sem senha carregada, a coleta falha depois de já ter aberto o canal.

### Corte por bytes

`max_bytes` nulo usa o valor do ambiente. Valor menor ou igual a zero não corta. Acima de zero, a leitura para ao atingir o teto, fecha o canal e marca a run como truncada. A interface mostra o aviso e acrescenta ao texto a linha `[TRUNCADO PELO APP: limite de N bytes atingido]`. O código de saída acompanhado nesse caso é 124, para distinguir do término normal do `tail`.

Stderr é lido junto. Se o comando termina com código diferente de zero e não houve stdout, a coleta falha e o erro (stderr redigido ou o código) aparece na tela, sem run nova. Se houve stdout e o código é diferente de zero, a análise segue e o stderr fica em `fetch_error` da run, exceto no caso truncado, em que esse campo de erro fica vazio.

O texto analisado é o stdout quando ele existe. Sem stdout e com sucesso relativo, entra o stderr. Os dois já passam pela redação.

### Run gravada

Origem `ssh`. Campos úteis na evidência operacional da run: `lines_requested`, `command` (redigido), `raw_bytes`, `raw_truncated`, `fetch_error`. A página de resumo mostra entradas, ignoradas, grupos e recomendações.

## Colar manualmente

`POST /logs/manual` exige o textarea. Não exige ambiente. Usa o banco do contexto, a conexão ativa e o ambiente ativo só como metadados da run (`source=manual`). Em seguida redireciona para `/logs?run_id=`.

Texto vazio ou sem nenhuma linha `duration:` cria uma run com zero entradas e zero recomendações. Ela aparece no histórico e pode ser apagada.

## Histórico

`/history` lista até 100 runs, as mais novas primeiro (ordem de `id` decrescente). `/logs` lista 15 acima do resultado aberto. Sem `run_id` na URL, `/logs` abre a run mais recente cujo `database_name` é o banco selecionado.

Apagar e compactar IDs está descrito em [arquitetura.md](arquitetura.md) e [operacao.md](operacao.md).

## O que ajustar no PostgreSQL para o log ser útil

No servidor de banco, uma configuração típica para esta tela é `log_min_duration_statement` num limiar que caiba na sua política (o filtro **Ignorar abaixo de ms** faz um segundo corte no painel). `log_statement = 'all'` sem a linha de duração não alimenta o parser.

Em container, `docker logs` só vê o que o processo escreve em stdout/stderr. PostgreSQL com `logging_collector` e arquivo dentro do volume não aparece em `docker logs`. Nesse caso use o modo arquivo, o exec com `tail`, ou um comando customizado.

Em instalação direta sem caminho preenchido, o script depende de permissão de leitura no arquivo escolhido. Sudo no ambiente existe para esse caso. Confira a prévia do comando antes de marcar a execução.

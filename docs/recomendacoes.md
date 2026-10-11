# Recomendações

Toda recomendação é um objeto com `kind`, `severity`, `title`, `detail`, `sql`, `confidence` e `evidence`. A página ordena por severidade (`high`, `medium`, `low`) e, no mesmo nível, pela confiança decrescente.

O SQL exibido é candidato. O processo do painel não o executa, com uma exceção: em **Analisar SQL**, o único SQL enviado ao servidor é o `EXPLAIN` da query colada.

Identificadores no SQL gerado são citados com aspas duplas, inclusive em nomes qualificados `schema.tabela`. Aspas no nome são duplicadas.

O nome de um índice novo é:

```text
idx_dta_<tabela>_<colunas>_<8 hex do sha1>
```

A tabela entra só com o último componente do nome, cortada a 40 caracteres seguros. O sufixo é o começo do SHA-1 de `tabela:col1,col2`. O comando é sempre:

```sql
CREATE INDEX CONCURRENTLY "idx_dta_..." ON "schema"."tabela" ("col1", "col2");
```

`CREATE INDEX CONCURRENTLY` não pode rodar dentro de um bloco de transação. Há no máximo quatro colunas no candidato vindo do parser.

## Comparação com índices existentes

Antes de sugerir criação, `compare_suggested_index` olha os índices reais da tabela. A regra é de prefixo, na mesma ordem. Índice parcial, expressão e `INCLUDE` não são reconhecidos como cobertura. O `EXPLAIN` continua sendo a validação.

| Status | Decisão | O que aconteceu | Confiança do cartão |
| --- | --- | --- | --- |
| `redundant_exact` | `skip` | Mesmas colunas, mesma ordem | 0,90 |
| `redundant_covered` | `skip` | Um índice existente começa com a sugestão e tem colunas a mais | 0,84 |
| `candidate_extends_existing` | `review` | A sugestão começa com um índice mais curto | entra no score abaixo, com −0,12 |
| `same_columns_different_order` | `review` | Mesmo conjunto, outra ordem | score com −0,12 |
| `partial_overlap` | `review` | A primeira coluna coincide e o restante não cobre | score com −0,12 |
| `no_overlap` | `create_candidate` | Nenhum desses casos | score sem o desconto de revisão |
| `invalid` | `skip` | Sem colunas válidas | cartão próprio, confiança 0,20 |

`skip` não devolve `CREATE INDEX`. Os outros devolvem, com o título "Índice candidato" ou "Sugestão descartada" no caso de skip por redundância.

Tabela não encontrada no banco selecionado: severidade `low`, confiança 0,25, e o `CREATE INDEX` ainda é mostrado para você conferir schema e `search_path`. Colunas que não existem na tabela: severidade `low`, confiança 0,20, sem SQL.

## Score do índice candidato

Ponto de partida: confiança 0,55 e severidade `medium`. O valor final fica entre 0,20 e 0,95.

| Sinal | Efeito |
| --- | --- |
| Decisão `review` | −0,12. O texto cita o índice relacionado |
| Tabela acima de 1 GB ou mais de 1.000.000 linhas estimadas | +0,18 e severidade `high` |
| Tabela abaixo de 32 MB e menos de 50.000 linhas | −0,18 e severidade `low` |
| `seq_scan` maior que `max(50, idx_scan * 2)` | +0,10 |
| `weight_ms` do grupo de log acima de 30.000 ms | +0,10 e severidade `high` |
| `n_mod_since_analyze` acima de `max(10.000, 20% das linhas)` | −0,07. O texto pede `ANALYZE` antes de decidir o índice |
| `n_distinct` da primeira coluna acima de 1.000 valores estimados | +0,08 |
| `n_distinct` da primeira coluna até 10 | −0,12 |

`n_distinct` negativo no `pg_stats` é fração de linhas. O cálculo usa o módulo vezes as linhas estimadas. Severidade `high` marcada pelo volume ou pelo tempo de log não é rebaixada pelo ramo de tabela pequena, porque esse ramo só roda no `elif`.

Esse score é usado por catálogo (FK), plano, parser e log. A origem fica em `evidence.source`: `foreign_key`, `explain_plan`, `query_parser`, `slow_log_cache` ou `slow_log`.

## Regras de catálogo

`catalog_recommendations` roda em `/catalog` e em `/recommendations`. Limites são da consulta, não do tamanho do banco inteiro: o que passar do `LIMIT` não aparece.

### Chave estrangeira sem índice de prefixo

`kind=index` (ou `index-comparison` se a comparação decidir revisão).

Uma FK entra na lista quando nenhum índice da tabela tem, nas primeiras posições, exatamente as colunas da constraint, na mesma ordem (`indkey` comparado ao `conkey`). Até 100 FKs. Cada uma passa pelo score de índice, com `source=foreign_key`.

Uma FK cujo prefixo já é a primary key ou outro índice não gera `CREATE INDEX`.

### Estatísticas possivelmente desatualizadas

`kind=statistics`, severidade `medium`, confiança 0,80.

Entra tabela de `pg_stat_user_tables` com mais de 10.000 linhas vivas e pelo menos uma destas condições: `last_analyze` nulo, ou `n_mod_since_analyze` maior que `GREATEST(10000, n_live_tup * 0.2)`. Até 50, as mais modificadas primeiro.

SQL:

```sql
ANALYZE "schema"."tabela";
```

O painel não executa esse `ANALYZE`. `last_autoanalyze` aparece na evidência e não entra no filtro. `last_analyze` nulo já inclui a tabela, mesmo quando o autovacuum analisou há pouco e `n_mod_since_analyze` está baixo. A segunda condição pega tabela com `ANALYZE` manual antigo e muitas modificações desde então.

### Tabela grande sem primary key

`kind=modeling`, severidade `medium`, confiança 0,70, sem SQL.

Tabela ordinária (`relkind = r`) com mais de 10 MB e sem índice `indisprimary`. Até 50, as maiores primeiro. O texto pede avaliação de chave antes de replicação lógica, manutenção e joins. A tabela pai particionada (`relkind = p`) fica de fora. Partição filha registrada como tabela ordinária entra se passar do tamanho e não tiver primary key própria.

### Muitos sequential scans

`kind=workload-structure`, severidade `low`, confiança 0,58, sem SQL.

`seq_scan > 100`, `seq_tup_read > 100000` e `seq_scan > idx_scan * 2`. Até 50, ordenado por tuplas lidas. O cartão aponta a tabela e pede uma query real ou um log para sugerir colunas. Contadores do PostgreSQL são cumulativos desde o reset da estatística.

### Índice grande sem uso registrado

`kind=index-maintenance`, severidade `low`, confiança 0,50.

`idx_scan = 0`, índice que não é primary key nem unique, tamanho acima de 10 MB. Até 50. O SQL vem comentado:

```sql
-- Revisar antes de executar
DROP INDEX CONCURRENTLY "schema"."indice";
```

Estatística zerada não prova que o índice é inútil: a coleta pode ter sido resetada, ou o uso pode ser mensal. O cartão existe para revisão, não para execução automática.

## Plano e parser de query

### Nós do EXPLAIN

| Nó | Limiar | Resultado |
| --- | --- | --- |
| `Seq Scan` | custo total > 1000 ou `Plan Rows` > 10.000 | Índice se houver colunas no `Filter` ou no parser. Sem colunas: cartão `index`, confiança 0,42, sem SQL |
| `Sort` | custo total > 1000 | `kind=query-plan`, confiança 0,55, sem SQL. A evidência traz `Sort Key` |
| `Nested Loop` | `Plan Rows` > 10.000 | `kind=query-plan`, confiança 0,55, sem SQL |

O filtro do seq scan aceita colunas seguidas de `=`, comparação, `~~`, `LIKE`, `ILIKE` ou `IS`, até quatro, ignorando `and`, `or`, `not`, `null`, `true` e `false`.

Se a caminhada do plano não produzir cartão, `extract_candidates_from_query` tenta a query original com `source=query_parser`.

### O que o parser reconhece

A extração é lexical, não um parse completo do SQL.

- Tabelas depois de `FROM` e `JOIN`, com alias opcional.
- `alias.coluna` seguido de `=`, comparação, `IN`, `LIKE`, `ILIKE`, `BETWEEN` ou `IS`.
- Os dois lados de `alias.col = alias.col`.
- Numa query com uma única tabela, colunas sem qualificador no `WHERE`, até `GROUP BY`, `ORDER BY` ou `LIMIT`.

No máximo quatro colunas por tabela. Funções sobre a coluna, `OR` complexo, subselect e `LATERAL` ficam fora ou saem incompletos. Por isso um seq scan sem predicado simples vira cartão sem SQL, em vez de um índice inventado.

### Normalização usada no log

Antes de agrupar, a query passa por `normalize_query`:

- literais entre aspas simples viram `?` (aspas escapadas `''` inclusas);
- números viram `?`;
- whitespace vira um espaço;
- o texto corta em 1.000 caracteres.

`IN (1, 2, 3)` e `IN (4)` tendem ao mesmo grupo. Comentários e literais dólar (`$tag$`) não têm regra própria.

## Como revisar antes de aplicar

1. Leia a decisão. `skip` encerra a criação daquele índice.
2. Em `review`, abra a evidência e o `indexdef` do índice citado.
3. Rode o `EXPLAIN` da query que motivou o cartão, no mesmo banco. Confira se o plano usa o índice existente.
4. Se for criar, execute o `CREATE INDEX CONCURRENTLY` fora de transação, em janela compatível com a escrita da tabela.
5. Para estatística, rode o `ANALYZE` sugerido e repita o `EXPLAIN` antes de criar índice em cima de estimativa velha.
6. Para `DROP INDEX`, confirme o intervalo da estatística e se há relatório ou job que use o índice fora dessa janela.

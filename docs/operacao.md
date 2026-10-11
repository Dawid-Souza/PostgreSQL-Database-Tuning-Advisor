# Operação

Este guia descreve o uso do painel depois que `start.bat` está no ar em [http://127.0.0.1:8000](http://127.0.0.1:8000). O cadastro de host e de conexão está em [ambientes.md](ambientes.md). As regras que produzem cada cartão estão em [recomendacoes.md](recomendacoes.md).

## Barra do topo

Em todas as páginas operacionais a barra mostra:

- **Ambiente** — nome do host SSH selecionado, ou "não selecionado".
- **PostgreSQL** — nome da conexão selecionada dentro desse ambiente.
- **Banco** — aparece quando a listagem de databases funciona. Mudar o combo envia `GET` com `set_db=1` e grava `selected_database` na conexão ativa.

O banco escolhido permanece ao ir de Dashboard para Catálogo, SQL, Logs e Histórico. Ele muda quando o operador troca o combo, quando o nome deixou de existir, ou quando outra conexão entra no lugar.

## Dashboard

`GET /` mostra três números de cadastro (ambientes, conexões do ambiente ativo, banco selecionado) e o teste ao vivo da conexão.

Com conexão aceita, a página lê o tamanho do banco e as 20 maiores tabelas de usuário, fora de `pg_catalog` e `information_schema`: tamanho total, linhas estimadas, `seq_scan`, `idx_scan` e modificações desde o último analyze.

Em seguida tenta `pg_stat_statements`, ordenado por `total_exec_time`, com limite 10, ignorando SQL que começa com `EXPLAIN` ou que cita a própria view. Se a extensão não estiver instalada ou o usuário não puder lê-la, a página avisa e o restante do painel segue funcionando. Essa lista é só leitura: ela não gera recomendação de índice. Para isso, use Catálogo, Analisar SQL ou Logs.

## Catálogo

`GET /catalog` repete o snapshot de tamanho e maiores tabelas e chama as regras estruturais no banco selecionado. `GET /recommendations` executa as mesmas regras e omite o snapshot. Essa segunda rota não está no menu lateral.

As regras estão descritas em [recomendacoes.md](recomendacoes.md). Nenhuma delas altera o banco.

## Analisar SQL

`/query` recebe o texto no `POST` e devolve a mesma página com recomendações e o plano JSON.

O checkbox **Usar EXPLAIN ANALYZE, BUFFERS** muda as opções:

| Checkbox | Comando enviado |
| --- | --- |
| Desmarcado | `EXPLAIN (FORMAT JSON, BUFFERS false)` |
| Marcado | `EXPLAIN (ANALYZE true, BUFFERS true, FORMAT JSON)` |

Sem o checkbox, o servidor só planeja. Com o checkbox, o servidor executa a query. A interface só libera esse modo para texto que começa com `SELECT` ou `WITH`.

O advisor recusa, com ou sem o checkbox, um texto que começa com `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `VACUUM`, `ANALYZE`, `GRANT`, `REVOKE`, `COPY`, `CALL` ou `DO`.

Uma função chamada de dentro de um `SELECT` ainda roda de verdade no modo `ANALYZE`. Use esse checkbox em query que você já executaria à mão naquele banco.

A leitura do plano procura:

- `Seq Scan` com custo total acima de 1000 ou mais de 10.000 linhas estimadas. As colunas saem do `Filter` do nó ou, na falta dele, do parser da query.
- `Sort` com custo total acima de 1000. O cartão pede revisão de `ORDER BY`/`GROUP BY` ou de `work_mem`. Não há `CREATE INDEX` automático para sort.
- `Nested Loop` com mais de 10.000 linhas estimadas.

Se nenhum nó gerar cartão, o parser da query inteira ainda tenta achar tabela e colunas de predicado.

## Logs e histórico

A coleta, o formato aceito e os limites estão em [logs.md](logs.md). No dia a dia:

1. Confira ambiente, conexão e banco no topo. As recomendações de índice são validadas nesse banco.
2. Para um arquivo que você já tem, use **Colar logs manualmente**. `Ignorar abaixo de ms` descarta entradas mais rápidas antes do agrupamento.
3. Para buscar no servidor, use **Buscar por SSH**. **Mostrar comando** não abre sessão. **Buscar e analisar** só segue com a confirmação marcada.
4. A análise bem-sucedida por texto redireciona para `/logs?run_id=<id>`. A busca SSH reapresenta a página já com o resultado.
5. Abra uma análise antiga pelo link **abrir** ou por `/history`.

Cada grupo mostra chamadas, total, média, máximo e a query normalizada (literais e números viram `?`). A amostra original fica na evidência da recomendação, limitada a 20.000 caracteres.

### Limpar análises

Nas duas telas há **Excluir selecionados** e **Limpar histórico**.

- Excluir selecionados apaga só as linhas marcadas e renumerá os IDs que sobraram, em ordem crescente, a partir de 1.
- Limpar histórico apaga todas as análises somente se o campo contiver exatamente `LIMPAR`. Qualquer outro texto volta com "Confirmação inválida" e mantém os dados.

O `return_to` do formulário só é honrado para `/history` e `/logs`. Outro valor cai em `/history`.

## Leitura de um cartão

Cada recomendação mostra:

- título e a linha `tipo · severidade · confiança`;
- o texto que explica a decisão;
- quando houve comparação de índice, o status (`redundant_exact`, `redundant_covered`, `candidate_extends_existing`, `same_columns_different_order`, `partial_overlap`, `no_overlap`) e a decisão (`skip`, `review`, `create_candidate`);
- o SQL, quando a regra produz um;
- o bloco **Evidência**, com o JSON usado (estatística da tabela, índices existentes, nó do plano ou grupo de log).

Confiança é um número de 0 a 1 exibido em percentual. Ela ordena a lista junto com a severidade: `high`, depois `medium`, depois `low`, e dentro do nível a maior confiança primeiro.

`skip` significa que a sugestão foi descartada porque um índice existente já cobre o prefixo. O cartão não traz `CREATE INDEX`. `review` traz o `CREATE INDEX` e pede leitura do índice relacionado antes de criar outro. `create_candidate` traz o `CREATE INDEX` porque nenhum índice existente cobre aquelas colunas como prefixo.

## Permissão útil no PostgreSQL

O usuário cadastrado em `/postgres` é o único papel usado pelo painel. Para um diagnóstico completo desse banco, esse papel precisa:

- `CONNECT` no database e enxergar os databases da instância que você quer listar;
- ler as views de estatística das tabelas analisadas. Em PostgreSQL moderno, `pg_read_all_stats` cobre `pg_stat_user_tables` e `pg_stat_user_indexes` de objetos de outros donos;
- `SELECT` nas tabelas cujas estatísticas de coluna (`pg_stats`) e cujo `EXPLAIN` você quer ver;
- permissão de leitura em `pg_stat_statements`, se quiser o bloco de workload do dashboard.

O painel não cria extensão, não altera `postgresql.conf` e não pede superusuário. Sem estatística visível, várias regras de catálogo simplesmente não listam aquelas tabelas.

## Quando reiniciar

Trocar `APP_SECRET` exige recadastrar senhas. Reiniciar o processo com o mesmo `APP_SECRET` reabre o cofre. Salvar ou testar uma conexão descarta o cache local daquele `id`. O `--reload` do `start.bat` reinicia sozinho quando um arquivo Python muda. Os JSON e o SQLite ficam em `data/` e sobrevivem ao restart.

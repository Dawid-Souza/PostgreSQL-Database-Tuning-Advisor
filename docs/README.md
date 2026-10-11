# Documentação do PostgreSQL Database Tuning Advisor

Índice dos guias. O [README](../README.md) na raiz cobre instalação, início rápido e visão do produto.

| Guia | Conteúdo |
| --- | --- |
| [Arquitetura](arquitetura.md) | Módulos, fluxo de uma análise, SQLite, JSON e cofre |
| [Operação](operacao.md) | Telas, banco ativo, histórico e o que cada ação faz |
| [Ambientes e conexões](ambientes.md) | SSH, sudo, Docker/Podman, instalação direta, DSN e senha |
| [Recomendações](recomendacoes.md) | Regras de catálogo, plano, score de índice e SQL gerado |
| [Logs](logs.md) | Formato aceito, agrupamento, modos de coleta e limites |
| [Segurança](seguranca.md) | Bind local, cofre, redação, SSH e login ainda inativo |
| [Configuração](configuracao.md) | Variáveis do `.env` e defaults do código |

O diagnóstico de catálogo e o `EXPLAIN` sem `ANALYZE` só leem. `EXPLAIN ANALYZE` executa `SELECT`/`WITH`. `CREATE INDEX`, `ANALYZE` e `DROP INDEX` aparecem como texto para o DBA revisar e aplicar.

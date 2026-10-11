# PostgreSQL Database Tuning Advisor

Painel web local para diagnóstico de carga e estrutura no PostgreSQL. O operador cadastra o ambiente e a conexão pela interface, escolhe o banco e recebe recomendações de índice, estatísticas, modelagem e manutenção. O SQL gerado fica para revisão: a aplicação no servidor continua manual.

Tela Principal (Dashboard)
<img width="1919" height="648" alt="image" src="https://github.com/user-attachments/assets/841442f2-652e-4f6d-909c-d44f42057de9" />

Tela de Configuração do Ambiente (Servidor)
Suporte a Linux e docker em linux, o suporte ao postgresql no Windows ainda está meio limitado mas estou trabalhando nessa parte. :D

<img width="1914" height="910" alt="image" src="https://github.com/user-attachments/assets/1b46081a-d580-4fcb-927d-b693a2a9e360" />

Tela de Configuração da Instancia/Cluster, nessa tela deve ser feito o cadastro do cluster e vinculado a instância.
Mesmo que seu servidor so tenha um cluster do postgresql deve ser cadastrado e vinculado aqui, fiz nesse modelo deivido a forma que uso
tenho mais de um cluster rodando no mesmo servidor, um cluster 'local' e um em docker.

<img width="1919" height="854" alt="image" src="https://github.com/user-attachments/assets/45a9ecf0-8bab-41aa-8098-dbe6724cd65b" />


O pacote FastAPI usa `Postgresql Database Tuning Advisor` (versão 1.0.0). Com ambientes, cofre local e histórico em SQLite.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-catálogo%20nativo-336791?logo=postgresql&logoColor=white)
![Plataforma](https://img.shields.io/badge/Painel-Windows%20local-0078D6?logo=windows&logoColor=white)

## Sumário

- [O que o painel entrega](#o-que-o-painel-entrega)
- [Início rápido](#início-rápido)
- [Pré-requisitos](#pré-requisitos)
- [Fluxo recomendado](#fluxo-recomendado)
- [Telas](#telas)
- [Segurança](#segurança)
- [Dados locais](#dados-locais)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Documentação](#documentação)

## O que o painel entrega

| Área | O que você vê |
| --- | --- |
| Dashboard | Versão do servidor, usuário, tamanho do banco, 20 maiores tabelas e, quando existir, as 10 queries de `pg_stat_statements` |
| Catálogo | Chaves estrangeiras sem índice de prefixo, estatísticas defasadas, tabelas grandes sem primary key, sequential scans relevantes e índices grandes sem uso |
| Analisar SQL | `EXPLAIN (FORMAT JSON)` e, se marcado, `EXPLAIN (ANALYZE, BUFFERS)` com leitura do plano |
| Logs | Parser de linhas `duration: … ms`, agrupamento por query normalizada e candidatos de índice ligados ao tempo observado |
| Histórico | Análises gravadas em SQLite, com exclusão seletiva ou limpeza total |

`pg_stat_statements` é opcional. Sem a extensão, dashboard, catálogo, SQL e logs continuam disponíveis.

Cada recomendação traz tipo, severidade (`high`, `medium`, `low`), confiança, detalhe, SQL candidato quando existe e o JSON de evidência usado na decisão. A comparação com índices existentes é conservadora: só trata como coberto um índice cuja lista de colunas começa com as mesmas colunas, na mesma ordem.

Guia das regras: [docs/recomendacoes.md](docs/recomendacoes.md).

## Início rápido

Na pasta do projeto, no Windows:

```bat
setup.bat
start.bat
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). `start.bat` sobe o Uvicorn só em `127.0.0.1`, porta `8000`, com `--reload`.

`setup.bat` cria `.venv`, instala `requirements.txt` e copia `.env.example` para `.env` quando esse arquivo ainda não existe. `start.ps1` faz a instalação e já sobe o servidor.

Equivalente manual:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Antes do primeiro uso, troque `APP_SECRET` no `.env`. Essa chave abre o cofre `data/secrets.json`. Se ela mudar, as senhas já gravadas deixam de abrir e precisam ser cadastradas de novo.

Saúde do processo: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) responde `ok`.

## Pré-requisitos

Na máquina do painel:

- Windows com Python 3.11 ou superior (`py -3`)
- Rede até o PostgreSQL que será diagnosticado
- Para coleta remota de log: SSH (porta configurável, padrão 22) até o host Linux, com `docker`/`podman`, arquivo de log ou um comando definido pelo operador

No PostgreSQL, o usuário da conexão precisa consultar o banco escolhido. As leituras usam `pg_database`, `pg_class`, `pg_stat_user_tables`, `pg_stat_user_indexes`, `pg_stats`, `pg_constraint`, `pg_index` e `pg_attribute`. O papel `pg_read_all_stats` é o caminho usual para enxergar estatísticas de objetos de outros donos. `EXPLAIN ANALYZE` executa o `SELECT`/`WITH` informado.

Para o parser de log reconhecer statements, o servidor precisa emitir linhas com `duration:` (em geral `log_min_duration_statement`).

## Fluxo recomendado

1. Em **Ambientes** (`/environments`), cadastre o host. O ambiente serve à coleta de logs por SSH. O tipo é **Container** ou **Instalação direta**.
2. Em **PostgreSQL** (`/postgres`), cadastre a conexão no ambiente ativo. Prefira host, porta, banco, usuário e senha separados. Salvar já testa a conexão.
3. Selecione o ambiente e a conexão. Cada conexão pertence a um ambiente. Trocar o ambiente ativo passa a usar uma conexão desse ambiente.
4. No topo, o seletor **Banco** lista os databases com `datallowconn` e grava a escolha na conexão ativa. Dashboard, Catálogo, SQL e Logs seguem esse banco até uma troca manual.
5. Use **Catálogo** para o diagnóstico estrutural e **Analisar SQL** para uma query pontual.
6. Em **Logs**, cole um trecho ou busque o final do log no servidor. O resultado entra no **Histórico**.

Senhas com `$`, `#`, `@`, `:`, `/`, `%`, espaço ou aspas vão no campo **Senha**. O `psycopg` recebe a senha como parâmetro, sem URL encode. DSN manual fica para opções avançadas: deixe a senha fora da URL e preencha **Senha**.

## Telas

| Rota | Uso |
| --- | --- |
| `/` | Estado da conexão, tamanho do banco, maiores tabelas, workload opcional |
| `/environments` | CRUD do host SSH, sudo, container e modo de log |
| `/postgres` | CRUD da conexão, teste e seleção |
| `/catalog` | Snapshot e recomendações do catálogo |
| `/recommendations` | Mesmas regras do catálogo, só a lista |
| `/query` | Plano JSON e recomendações da query |
| `/logs` | Coleta SSH ou texto colado, grupos e recomendações |
| `/history` | Até 100 análises, exclusão e limpeza |
| `/login-settings` | Rotas previstas para um login ainda inativo |
| `/health` | Probe em texto puro |

Ao excluir análises selecionadas, os IDs restantes são recompactados em sequência. Ao limpar todo o histórico, o próximo ID volta para `1`. A limpeza total exige digitar `LIMPAR`.

## Segurança

O painel foi feito para a estação do DBA.

- `start.bat` e `start.ps1` escutam apenas em `127.0.0.1`.
- Senhas de SSH, sudo, PostgreSQL e DSN com senha vão para `data/secrets.json`, cifradas com Fernet. A chave deriva de `APP_SECRET` por PBKDF2-HMAC-SHA256 (390.000 iterações) e um salt próprio do cofre.
- `data/environment_configs.json` guarda metadados (`has_password`, host, usuário, caminho de chave). O valor da senha fica no cofre.
- A coleta SSH só executa com a caixa **Confirmo a execução remota**. **Mostrar comando** gera a prévia e redige segredos.
- Saídas, erros e comandos passam por redação antes do histórico.
- A tela **Analisar SQL** recusa `INSERT`, `UPDATE`, `DELETE`, `MERGE`, DDL, `VACUUM`, `ANALYZE`, `GRANT`, `REVOKE`, `COPY`, `CALL` e `DO`. `EXPLAIN ANALYZE` só aceita `SELECT` e `WITH`, e esse modo executa a query.
- O login de aplicação ainda não está ligado (`login_enabled()` retorna falso). Publique o painel na rede só atrás de autenticação e HTTPS que você controle.

Detalhe de cofre, SSH, sudo e comandos customizados: [docs/seguranca.md](docs/seguranca.md).

## Dados locais

```text
data/app.sqlite3               Histórico de análises de log
data/environment_configs.json  Ambientes e conexões, sem senha em claro
data/secrets.json              Cofre cifrado
.env                           APP_SECRET e limites locais
```

Os três arquivos de `data/` e o `.env` nascem na máquina. O `.gitignore` deixa essa pasta e o `.env` fora do Git. `app.sqlite3` é criado no startup.

## Estrutura do projeto

```text
app/main.py                     FastAPI, estáticos e routers
app/routes/                     Páginas e POSTs da interface
app/services/advisor_service.py Regras, EXPLAIN e comparação de índices
app/services/log_analysis_service.py  Parser e cache de slow log
app/services/server_log_service.py    Comando remoto e SSH
app/services/postgres_service.py      Conexão e consultas
app/services/config_service.py  Formulários de ambiente e conexão
app/repositories/               JSON de configuração e SQLite
app/security/                   Cofre, redação e gancho de login
app/templates/                  Jinja2
setup.bat / start.bat / start.ps1
```

## Documentação

| Guia | Conteúdo |
| --- | --- |
| [Índice](docs/README.md) | Mapa da documentação |
| [Arquitetura](docs/arquitetura.md) | Módulos, fluxo e persistência |
| [Operação](docs/operacao.md) | Uso das telas, banco ativo e histórico |
| [Ambientes e conexões](docs/ambientes.md) | SSH, container, instalação direta, DSN |
| [Recomendações](docs/recomendacoes.md) | Regras, score, SQL gerado |
| [Logs](docs/logs.md) | Parser, modos de coleta e limites |
| [Segurança](docs/seguranca.md) | Cofre, redação, superfície local |
| [Configuração](docs/configuracao.md) | `.env` e valores padrão |

## Limites conhecidos

- Recomendações de índice são heurísticas. Índices parciais, funcionais e `INCLUDE` pedem `EXPLAIN` antes de qualquer `CREATE INDEX`.
- O nome sugerido segue `idx_dta_<tabela>_<colunas>_<8 hex>`. `CREATE INDEX CONCURRENTLY` precisa rodar fora de um bloco de transação.
- `DROP INDEX CONCURRENTLY` aparece comentado, só para índice não único, não primário, com mais de 10 MB e `idx_scan = 0` nas estatísticas atuais.
- Comandos customizados de log executam no host remoto, com o usuário SSH e o `sudo` configurado. Use-os só em operadores que já podem administrar esse host.
- A política SSH é `AutoAddPolicy`: o primeiro contato aceita a chave do host. Confira o host antes de guardar a senha.

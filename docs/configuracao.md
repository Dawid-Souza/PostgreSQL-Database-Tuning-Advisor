# Configuração

O comportamento de produto é configurado na interface. O `.env` guarda a chave do cofre e os tetos da análise de log. O arquivo lido é `.env` na raiz do projeto (`app/config/settings.py`).

`setup.bat` copia `.env.example` para `.env` somente quando `.env` ainda não existe. Um setup repetido não sobrescreve a chave que você já trocou.

## Variáveis

Os nomes seguem o campo do `Settings` em maiúsculas. Valores desconhecidos no `.env` são ignorados.

| Variável | Default no código | Função |
| --- | --- | --- |
| `APP_SECRET` | `change-me-local-only` no código; o exemplo traz `change-this-local-secret` | Segredo mestre do cofre. Troque antes de cadastrar senha |
| `LOG_CACHE_PAGE_SIZE` | `50` | Itens por página de grupos e de recomendações em `/logs` |
| `MAX_LOG_FETCH_BYTES` | `0` | Teto de bytes usado na tela de logs quando o ambiente não tem `max_bytes`. `0` não corta |
| `MAX_LOG_RECOMMENDATION_GROUPS` | `250` | Quantos grupos de log, do mais caro ao mais barato, geram candidato de índice. O código não deixa esse teto efetivo abaixo de 10 |
| `MAX_LOG_RECOMMENDATIONS` | `250` | Quantidade máxima de recomendações gravadas numa run. Piso efetivo 10 |
| `APP_NAME` | `PostgreSQL Database Tuning Advisor` | Título do FastAPI e da aba do navegador |
| `APP_VERSION` | `1.0.0` | Versão informada ao FastAPI |
| `CONFIG_FILE` | `environment_configs.json` | Nome do JSON dentro de `data/` |
| `APP_SQLITE_FILE` | `app.sqlite3` | Nome do SQLite dentro de `data/` |

Exemplo alinhado ao `.env.example`:

```text
APP_SECRET=troque-por-um-valor-longo-desta-estacao
LOG_CACHE_PAGE_SIZE=50
MAX_LOG_FETCH_BYTES=0
MAX_LOG_RECOMMENDATION_GROUPS=250
MAX_LOG_RECOMMENDATIONS=250
```

Reinicie o Uvicorn depois de editar o `.env`. Com `--reload`, salvar o arquivo já reinicia se o processo estiver observando a pasta. Confirme que o processo subiu de novo antes de testar a conexão: a chave nova só vale no processo novo, e os segredos antigos não abrem com ela.

## Limites que não estão no `.env`

Eles estão no serviço que lê o formulário ou monta o comando.

| Limite | Onde | Faixa |
| --- | --- | --- |
| Porta SSH | ambiente | 1–65535, default 22 |
| Timeout SSH | ambiente | 1–300 s, default 20 |
| Linhas de log no cadastro | ambiente | 100–200.000, default 5.000 |
| Linhas pedidas na coleta | serviço de log | 100–200.000 |
| Bytes máximos gravados no ambiente | formulário de ambiente | 0–512 MiB. `0` significa sem corte |
| Bytes na coleta da tela `/logs` | valor enviado naquele POST | `0` sem corte. Não passa pelo teto de 512 MiB do formulário de ambiente |
| Porta PostgreSQL | conexão | 1–65535, default 5432 |
| Timeout PostgreSQL | conexão | 1–120 s, default 10 |
| Página do SQLite | repositório | 5–500, mesmo que `LOG_CACHE_PAGE_SIZE` saia dessa faixa |
| Amostra de query no grupo | parser | 20.000 caracteres |
| Query normalizada | agrupamento | 1.000 caracteres |
| Colunas num candidato | parser | 4 |
| FKs, tabelas sem PK, seq scans, índices sem uso, estatística velha | SQL de catálogo | 100 FKs e 50 nas demais regras |
| Maiores tabelas no snapshot | dashboard e catálogo | 20 |
| Workload `pg_stat_statements` | dashboard | 10 |

## Arquivos gerados

Na primeira subida, `data/` é criado. Na primeira leitura de configuração, `environment_configs.json` nasce vazio (`selected_*` nulos e listas vazias). Na primeira gravação de segredo, `secrets.json` nasce com salt novo. No startup, `app.sqlite3` ganha as tabelas se ainda não existirem.

Apagar `secrets.json` sem apagar o JSON de configuração deixa os cadastros com a flag de senha e sem o segredo. A coluna de senha na tela PostgreSQL mostra **requer salvar novamente**. Apagar os dois e o `.env` volta a estação ao estado de instalação, desde que você gere outro `APP_SECRET`.

## Subir sem os scripts

Os scripts fixam host e porta de propósito. Para a mesma postura:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Outro host ou outra porta é decisão de exposição. Leia [seguranca.md](seguranca.md) antes de escutar fora de localhost.

Dependências diretas, em `requirements.txt`: FastAPI, Uvicorn, `psycopg` com binário e pool, pydantic-settings, Jinja2, python-multipart, sqlparse, Paramiko e cryptography. O código de análise não chama `sqlparse` nos fluxos descritos aqui. A biblioteca está declarada para o ambiente de execução instalado pelo `setup.bat`.

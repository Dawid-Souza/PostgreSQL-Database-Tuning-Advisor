from __future__ import annotations

from typing import Any

from anyio import to_thread
from psycopg import Connection
from psycopg.conninfo import make_conninfo

from app.repositories import config_repository
from app.security.redaction import redact_text
from app.security.secret_store import secret_store
from app.services.config_service import secret_key


_pools: dict[tuple[str, str | None], object] = {}


def selected_config() -> dict[str, Any] | None:
    return config_repository.get_selected_postgres_config()


def _require_config(config_id: str | None = None) -> dict[str, Any]:
    config = config_repository.get_postgres_config(config_id) if config_id else selected_config()
    if not config:
        raise RuntimeError("Nenhuma configuração PostgreSQL selecionada.")
    return config


def build_conninfo(config: dict[str, Any], database: str | None = None) -> str:
    config_id = str(config["id"])
    connect_timeout = int(config.get("connect_timeout_seconds") or 10)
    if config.get("use_manual_dsn"):
        runtime_dsn = secret_store.get(secret_key("postgres", config_id, "manual_dsn"))
        dsn = runtime_dsn or config.get("dsn_preview")
        if not dsn or "[REDACTED]" in str(dsn):
            raise RuntimeError("DSN manual contém segredo e precisa ser informado novamente nesta sessão.")
        overrides: dict[str, Any] = {"connect_timeout": connect_timeout}
        password = secret_store.get(secret_key("postgres", config_id, "password"))
        if password:
            overrides["password"] = password
        if database:
            overrides["dbname"] = database
        return make_conninfo(str(dsn), **overrides)

    password = secret_store.get(secret_key("postgres", config_id, "password"))
    if config.get("has_password") and not password:
        raise RuntimeError("Senha PostgreSQL não está carregada nesta sessão. Edite a conexão e informe a senha novamente.")

    kwargs: dict[str, Any] = {
        "host": config.get("host") or "localhost",
        "port": int(config.get("port") or 5432),
        "dbname": database or config.get("default_database") or "postgres",
        "user": config.get("username") or None,
        "connect_timeout": connect_timeout,
    }
    if password:
        kwargs["password"] = password
    if config.get("sslmode"):
        kwargs["sslmode"] = config.get("sslmode")
    return make_conninfo("", **{k: v for k, v in kwargs.items() if v is not None})


def safe_conninfo_preview(config_id: str | None = None, database: str | None = None) -> str | None:
    try:
        config = _require_config(config_id)
        return redact_text(build_conninfo(config, database=database), secret_store.known_values())
    except Exception as exc:
        return f"Não foi possível montar preview: {secret_store.redact(str(exc))}"


async def close_pools() -> None:
    _pools.clear()


async def close_pools_for_config(config_id: str) -> None:
    keys = [key for key in _pools if key[0] == str(config_id)]
    for key in keys:
        _pools.pop(key, None)


def _conninfo_for(database: str | None = None, config_id: str | None = None) -> str:
    config = _require_config(config_id)
    return build_conninfo(config, database=database)


async def fetch_all(sql: str, params: tuple = (), database: str | None = None, config_id: str | None = None) -> list[dict[str, Any]]:
    conninfo = _conninfo_for(database=database, config_id=config_id)
    return await to_thread.run_sync(_fetch_all_sync, conninfo, sql, params)


def _fetch_all_sync(conninfo: str, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with Connection.connect(conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            cols = [d.name for d in cur.description]
            rows = cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def fetch_one(sql: str, params: tuple = (), database: str | None = None, config_id: str | None = None) -> dict[str, Any] | None:
    rows = await fetch_all(sql, params, database=database, config_id=config_id)
    return rows[0] if rows else None


async def list_databases(config_id: str | None = None) -> list[str]:
    rows = await fetch_all(
        """
        SELECT datname
        FROM pg_database
        WHERE datallowconn
          AND datistemplate = false
        ORDER BY datname
        """,
        config_id=config_id,
    )
    return [row["datname"] for row in rows]


async def current_database_name(config_id: str | None = None) -> str | None:
    row = await fetch_one("SELECT current_database() AS database", config_id=config_id)
    return row["database"] if row else None


async def resolve_database(database: str | None, config_id: str | None = None) -> str | None:
    dbs = await list_databases(config_id=config_id)
    if database and database in dbs:
        return database
    current = await current_database_name(config_id=config_id)
    return current or (dbs[0] if dbs else None)


async def test_connection(config_id: str | None = None) -> dict[str, Any]:
    config = _require_config(config_id)
    await close_pools_for_config(str(config["id"]))
    row = await fetch_one(
        """
        SELECT
            version() AS version,
            current_database() AS database,
            current_user AS username,
            inet_server_addr()::text AS server_addr,
            inet_server_port() AS server_port
        """,
        config_id=str(config["id"]),
    )
    return {"ok": True, "info": row, "conninfo_preview": safe_conninfo_preview(str(config["id"]))}

from __future__ import annotations

from fastapi import Request

from app.config import settings
from app.repositories import config_repository
from app.security.secret_store import secret_store
from app.services import postgres_service


async def build_context(request: Request, posted_db: str | None = None, include_databases: bool = True) -> dict:
    environments = config_repository.list_environments()
    selected_environment = config_repository.get_selected_environment()
    postgres_configs = config_repository.list_postgres_configs((selected_environment or {}).get("id"))
    selected_postgres = config_repository.get_selected_postgres_config()

    query_db = request.query_params.get("db")
    manual_db_change = request.method == "GET" and request.query_params.get("set_db") == "1" and bool(query_db)
    requested_db = posted_db or (query_db if manual_db_change else None)
    selected_db = (selected_postgres or {}).get("selected_database") or (selected_postgres or {}).get("default_database")
    databases: list[str] = []
    database_error = None
    if include_databases and selected_postgres:
        try:
            databases = await postgres_service.list_databases(config_id=selected_postgres["id"])
            if manual_db_change and query_db in databases:
                selected_db = query_db
                config_repository.select_postgres_database(selected_postgres["id"], selected_db)
                selected_postgres = config_repository.get_postgres_config(selected_postgres["id"])
            elif posted_db and posted_db in databases:
                selected_db = posted_db
            if selected_db not in databases:
                selected_db = (selected_postgres or {}).get("default_database") or (databases[0] if databases else None)
                if selected_db:
                    config_repository.select_postgres_database(selected_postgres["id"], selected_db)
                    selected_postgres = config_repository.get_postgres_config(selected_postgres["id"])
        except Exception as exc:
            database_error = secret_store.redact(str(exc))

    return {
        "request": request,
        "settings": settings,
        "environments": environments,
        "postgres_configs": postgres_configs,
        "selected_environment": selected_environment,
        "selected_postgres": selected_postgres,
        "databases": databases,
        "selected_db": selected_db,
        "database_error": database_error,
    }

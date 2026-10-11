from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


DEFAULT_CONFIG: dict[str, Any] = {
    "selected_environment_id": None,
    "selected_postgres_id": None,
    "environments": [],
    "postgres_connections": [],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path() -> Path:
    settings.config_path.parent.mkdir(parents=True, exist_ok=True)
    return settings.config_path


def load_config() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        save_config(deepcopy(DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = deepcopy(DEFAULT_CONFIG)
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update({k: data.get(k, v) for k, v in DEFAULT_CONFIG.items()})
    changed = _migrate_config(merged)
    if changed:
        save_config(merged)
    return merged


def save_config(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def list_environments() -> list[dict[str, Any]]:
    return sorted(load_config()["environments"], key=lambda x: (x.get("name") or "").lower())


def _migrate_config(data: dict[str, Any]) -> bool:
    changed = False
    selected_environment_id = data.get("selected_environment_id")
    if not selected_environment_id and data.get("environments"):
        selected_environment_id = data["environments"][0].get("id")
        data["selected_environment_id"] = selected_environment_id
        changed = True

    old_default_log_limit = 32 * 1024 * 1024
    for item in data.get("environments", []):
        if "max_bytes" not in item or item.get("max_bytes") == old_default_log_limit:
            item["max_bytes"] = 0
            changed = True

    environment_ids = {item.get("id") for item in data.get("environments", [])}
    for item in data.get("postgres_connections", []):
        if not item.get("environment_id") and selected_environment_id:
            item["environment_id"] = selected_environment_id
            changed = True
        elif item.get("environment_id") and item.get("environment_id") not in environment_ids and selected_environment_id:
            item["environment_id"] = selected_environment_id
            changed = True

    selected_postgres_id = data.get("selected_postgres_id")
    if selected_environment_id and selected_postgres_id:
        selected = next((item for item in data.get("postgres_connections", []) if item.get("id") == selected_postgres_id), None)
        if selected and selected.get("environment_id") != selected_environment_id:
            replacement = next((item for item in data.get("postgres_connections", []) if item.get("environment_id") == selected_environment_id), None)
            data["selected_postgres_id"] = replacement.get("id") if replacement else None
            changed = True
    return changed


def get_environment(environment_id: str | None) -> dict[str, Any] | None:
    if not environment_id:
        return None
    for item in load_config()["environments"]:
        if item.get("id") == environment_id:
            return item
    return None


def get_selected_environment() -> dict[str, Any] | None:
    data = load_config()
    return get_environment(data.get("selected_environment_id"))


def save_environment(environment: dict[str, Any]) -> dict[str, Any]:
    data = load_config()
    existing = get_environment(environment.get("id")) or {}
    saved = {**existing, **environment}
    saved.setdefault("created_at", _now())
    saved["updated_at"] = _now()
    data["environments"] = [e for e in data["environments"] if e.get("id") != saved["id"]]
    data["environments"].append(saved)
    if not data.get("selected_environment_id"):
        data["selected_environment_id"] = saved["id"]
    save_config(data)
    return saved


def delete_environment(environment_id: str) -> None:
    data = load_config()
    data["environments"] = [e for e in data["environments"] if e.get("id") != environment_id]
    if data.get("selected_environment_id") == environment_id:
        data["selected_environment_id"] = data["environments"][0]["id"] if data["environments"] else None
    selected_environment_id = data.get("selected_environment_id")
    if selected_environment_id:
        replacement = next((c for c in data["postgres_connections"] if c.get("environment_id") == selected_environment_id), None)
        data["selected_postgres_id"] = replacement.get("id") if replacement else None
    else:
        data["selected_postgres_id"] = None
    save_config(data)


def select_environment(environment_id: str | None) -> None:
    data = load_config()
    if environment_id and not any(e.get("id") == environment_id for e in data["environments"]):
        raise ValueError("Ambiente não encontrado.")
    data["selected_environment_id"] = environment_id
    selected = next((c for c in data["postgres_connections"] if c.get("id") == data.get("selected_postgres_id")), None)
    if environment_id and (not selected or selected.get("environment_id") != environment_id):
        replacement = next((c for c in data["postgres_connections"] if c.get("environment_id") == environment_id), None)
        data["selected_postgres_id"] = replacement.get("id") if replacement else None
    save_config(data)


def list_postgres_configs(environment_id: str | None = None) -> list[dict[str, Any]]:
    items = load_config()["postgres_connections"]
    if environment_id:
        items = [item for item in items if item.get("environment_id") == environment_id]
    return sorted(items, key=lambda x: (x.get("name") or "").lower())


def get_postgres_config(config_id: str | None) -> dict[str, Any] | None:
    if not config_id:
        return None
    for item in load_config()["postgres_connections"]:
        if item.get("id") == config_id:
            return item
    return None


def get_selected_postgres_config() -> dict[str, Any] | None:
    data = load_config()
    selected_environment_id = data.get("selected_environment_id")
    selected_postgres_id = data.get("selected_postgres_id")
    selected = next((item for item in data["postgres_connections"] if item.get("id") == selected_postgres_id), None)
    if selected and (not selected_environment_id or selected.get("environment_id") == selected_environment_id):
        return selected
    replacement = next((item for item in data["postgres_connections"] if item.get("environment_id") == selected_environment_id), None)
    if replacement:
        data["selected_postgres_id"] = replacement.get("id")
        save_config(data)
        return replacement
    if selected_postgres_id is not None:
        data["selected_postgres_id"] = None
        save_config(data)
    return None


def save_postgres_config(config: dict[str, Any]) -> dict[str, Any]:
    data = load_config()
    existing = get_postgres_config(config.get("id")) or {}
    saved = {**existing, **config}
    if not saved.get("environment_id"):
        saved["environment_id"] = data.get("selected_environment_id")
    if saved.get("environment_id") and not any(e.get("id") == saved.get("environment_id") for e in data["environments"]):
        raise ValueError("Ambiente da conexão PostgreSQL não encontrado.")
    saved.setdefault("created_at", _now())
    saved["updated_at"] = _now()
    data["postgres_connections"] = [c for c in data["postgres_connections"] if c.get("id") != saved["id"]]
    data["postgres_connections"].append(saved)
    selected_environment_id = data.get("selected_environment_id")
    selected = next((c for c in data["postgres_connections"] if c.get("id") == data.get("selected_postgres_id")), None)
    if not selected or (selected_environment_id and selected.get("environment_id") != selected_environment_id):
        data["selected_postgres_id"] = saved["id"]
    save_config(data)
    return saved


def delete_postgres_config(config_id: str) -> None:
    data = load_config()
    deleted = next((c for c in data["postgres_connections"] if c.get("id") == config_id), None)
    data["postgres_connections"] = [c for c in data["postgres_connections"] if c.get("id") != config_id]
    if data.get("selected_postgres_id") == config_id:
        environment_id = (deleted or {}).get("environment_id") or data.get("selected_environment_id")
        replacement = next((c for c in data["postgres_connections"] if c.get("environment_id") == environment_id), None)
        data["selected_postgres_id"] = replacement.get("id") if replacement else None
    save_config(data)


def select_postgres_config(config_id: str | None) -> None:
    data = load_config()
    selected_environment_id = data.get("selected_environment_id")
    selected = next((c for c in data["postgres_connections"] if c.get("id") == config_id), None) if config_id else None
    if config_id and not selected:
        raise ValueError("Conexão PostgreSQL não encontrada.")
    if selected and selected_environment_id and selected.get("environment_id") != selected_environment_id:
        raise ValueError("Conexão PostgreSQL não pertence ao ambiente ativo.")
    data["selected_postgres_id"] = config_id
    save_config(data)


def select_postgres_database(config_id: str, database_name: str | None) -> None:
    data = load_config()
    found = False
    for item in data["postgres_connections"]:
        if item.get("id") == config_id:
            item["selected_database"] = database_name
            item["updated_at"] = _now()
            found = True
            break
    if not found:
        raise ValueError("Conexão PostgreSQL não encontrada.")
    save_config(data)


def config_summary() -> dict[str, Any]:
    data = load_config()
    return {
        "selected_environment_id": data.get("selected_environment_id"),
        "selected_postgres_id": data.get("selected_postgres_id"),
        "environments": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "environment_type": item.get("environment_type"),
                "host": item.get("host"),
                "has_ssh_password": item.get("has_ssh_password", False),
                "has_sudo_password": item.get("has_sudo_password", False),
            }
            for item in data.get("environments", [])
        ],
        "postgres_connections": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "host": item.get("host"),
                "port": item.get("port"),
                "default_database": item.get("default_database"),
                "selected_database": item.get("selected_database"),
                "username": item.get("username"),
                "has_password": item.get("has_password", False),
            }
            for item in data.get("postgres_connections", [])
        ],
    }

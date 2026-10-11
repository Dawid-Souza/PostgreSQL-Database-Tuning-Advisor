from __future__ import annotations

import uuid
from typing import Any

from app.repositories import config_repository
from app.security.redaction import looks_like_secret_dsn, redact_dsn
from app.security.secret_store import secret_store


CHECKED_VALUES = {"1", "true", "on", "yes", "sim"}


def _text(form: Any, name: str, default: str = "") -> str:
    value = form.get(name, default)
    return str(value).strip() if value is not None else default


def _raw(form: Any, name: str, default: str = "") -> str:
    value = form.get(name, default)
    return str(value) if value is not None else default


def _int(form: Any, name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(_text(form, name, str(default)))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _bool(form: Any, name: str) -> bool:
    return _text(form, name).lower() in CHECKED_VALUES


def _secret_key(scope: str, item_id: str, field: str) -> str:
    return f"{scope}:{item_id}:{field}"


def save_environment_from_form(form: Any) -> dict[str, Any]:
    env_id = _text(form, "id") or str(uuid.uuid4())
    existing = config_repository.get_environment(env_id) or {}
    auth_method = _text(form, "ssh_auth_method", "password") or "password"
    use_sudo = _bool(form, "use_sudo")
    sudo_from_ssh = _bool(form, "sudo_password_from_ssh")

    environment = {
        "id": env_id,
        "name": _text(form, "name") or "Ambiente sem nome",
        "environment_type": _text(form, "environment_type", "container"),
        "host": _text(form, "host"),
        "ssh_port": _int(form, "ssh_port", 22, 1, 65535),
        "ssh_login": _text(form, "ssh_login"),
        "ssh_auth_method": auth_method,
        "ssh_key_path": _text(form, "ssh_key_path"),
        "base_path": _text(form, "base_path"),
        "timeout_seconds": _int(form, "timeout_seconds", 20, 1, 300),
        "notes": _text(form, "notes"),
        "use_sudo": use_sudo,
        "sudo_user": _text(form, "sudo_user"),
        "sudo_password_from_ssh": sudo_from_ssh,
        "container_name": _text(form, "container_name"),
        "container_runtime": _text(form, "container_runtime", "docker"),
        "container_app_dir": _text(form, "container_app_dir"),
        "container_user": _text(form, "container_user"),
        "log_base_command": _text(form, "log_base_command"),
        "use_container_exec": _bool(form, "use_container_exec"),
        "log_mode": _text(form, "log_mode", "container"),
        "log_file_path": _text(form, "log_file_path"),
        "custom_log_command": _text(form, "custom_log_command"),
        "default_lines": _int(form, "default_lines", 5000, 100, 200000),
        "max_bytes": _int(form, "max_bytes", 0, 0, 512 * 1024 * 1024),
    }

    ssh_password = _raw(form, "ssh_password")
    if auth_method == "password":
        if ssh_password:
            secret_store.set(_secret_key("environment", env_id, "ssh_password"), ssh_password)
            environment["has_ssh_password"] = True
        else:
            environment["has_ssh_password"] = bool(existing.get("has_ssh_password"))
    else:
        environment["has_ssh_password"] = False
        secret_store.forget(_secret_key("environment", env_id, "ssh_password"))

    sudo_password = _raw(form, "sudo_password")
    if use_sudo and not sudo_from_ssh:
        if sudo_password:
            secret_store.set(_secret_key("environment", env_id, "sudo_password"), sudo_password)
            environment["has_sudo_password"] = True
        else:
            environment["has_sudo_password"] = bool(existing.get("has_sudo_password"))
    else:
        environment["has_sudo_password"] = False
        secret_store.forget(_secret_key("environment", env_id, "sudo_password"))

    saved = config_repository.save_environment(environment)
    return saved


def save_postgres_from_form(form: Any) -> dict[str, Any]:
    config_id = _text(form, "id") or str(uuid.uuid4())
    existing = config_repository.get_postgres_config(config_id) or {}
    selected_environment = config_repository.get_selected_environment() or {}
    use_manual = _bool(form, "use_manual_dsn")
    password = _raw(form, "password")
    manual_dsn = _raw(form, "manual_dsn").strip()
    environment_id = _text(form, "environment_id") or existing.get("environment_id") or selected_environment.get("id")

    config = {
        "id": config_id,
        "environment_id": environment_id,
        "name": _text(form, "name") or "PostgreSQL sem nome",
        "host": _text(form, "host"),
        "port": _int(form, "port", 5432, 1, 65535),
        "default_database": _text(form, "default_database") or "postgres",
        "username": _text(form, "username"),
        "sslmode": _text(form, "sslmode", "prefer"),
        "connect_timeout_seconds": _int(form, "connect_timeout_seconds", 10, 1, 120),
        "use_manual_dsn": use_manual,
        "dsn_preview": existing.get("dsn_preview", ""),
        "manual_dsn_runtime_only": bool(existing.get("manual_dsn_runtime_only", False)),
    }

    if password:
        secret_store.set(_secret_key("postgres", config_id, "password"), password)
        config["has_password"] = True
    else:
        config["has_password"] = bool(existing.get("has_password"))

    if use_manual and manual_dsn and "[REDACTED]" not in manual_dsn:
        if looks_like_secret_dsn(manual_dsn):
            secret_store.set(_secret_key("postgres", config_id, "manual_dsn"), manual_dsn)
            config["dsn_preview"] = redact_dsn(manual_dsn)
            config["manual_dsn_runtime_only"] = True
        else:
            config["dsn_preview"] = manual_dsn
            config["manual_dsn_runtime_only"] = False
    elif use_manual and existing.get("dsn_preview"):
        config["dsn_preview"] = existing.get("dsn_preview", "")
        config["manual_dsn_runtime_only"] = bool(existing.get("manual_dsn_runtime_only", False))
    elif not use_manual:
        config["manual_dsn_runtime_only"] = False

    saved = config_repository.save_postgres_config(config)
    return saved


def secret_key(scope: str, item_id: str, field: str) -> str:
    return _secret_key(scope, item_id, field)

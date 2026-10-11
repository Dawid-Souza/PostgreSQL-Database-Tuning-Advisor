from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import DATA_DIR, settings


VAULT_PATH = DATA_DIR / "secrets.json"
PBKDF2_ITERATIONS = 390_000


def _load_file() -> dict:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not VAULT_PATH.exists():
        data = {"version": 1, "salt": base64.urlsafe_b64encode(os.urandom(16)).decode("ascii"), "items": {}}
        _save_file(data)
        return data
    try:
        data = json.loads(VAULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {"version": 1, "salt": base64.urlsafe_b64encode(os.urandom(16)).decode("ascii"), "items": {}}
        _save_file(data)
    data.setdefault("version", 1)
    data.setdefault("salt", base64.urlsafe_b64encode(os.urandom(16)).decode("ascii"))
    data.setdefault("items", {})
    return data


def _save_file(data: dict) -> None:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = VAULT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(VAULT_PATH)


def _fernet(data: dict | None = None) -> Fernet:
    vault = data or _load_file()
    salt = base64.urlsafe_b64decode(vault["salt"].encode("ascii"))
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = base64.urlsafe_b64encode(kdf.derive(settings.app_secret.encode("utf-8")))
    return Fernet(key)


def set_secret(key: str, value: str) -> None:
    data = _load_file()
    token = _fernet(data).encrypt(value.encode("utf-8")).decode("ascii")
    data["items"][key] = token
    _save_file(data)


def get_secret(key: str) -> str | None:
    data = _load_file()
    token = data.get("items", {}).get(key)
    if not token:
        return None
    try:
        return _fernet(data).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def delete_secret(key: str) -> None:
    data = _load_file()
    if key in data.get("items", {}):
        data["items"].pop(key, None)
        _save_file(data)


def has_secret(key: str) -> bool:
    return key in _load_file().get("items", {})


def delete_prefix(prefix: str) -> None:
    data = _load_file()
    keys = [key for key in data.get("items", {}) if key.startswith(prefix)]
    for key in keys:
        data["items"].pop(key, None)
    if keys:
        _save_file(data)


def list_secret_values() -> list[str]:
    values: list[str] = []
    for key in list(_load_file().get("items", {})):
        value = get_secret(key)
        if value:
            values.append(value)
    return values


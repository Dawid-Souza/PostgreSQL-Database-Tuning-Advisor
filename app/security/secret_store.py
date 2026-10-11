from __future__ import annotations

from app.security.redaction import redact_text
from app.security import secret_vault


class RuntimeSecretStore:
    """Runtime cache backed by an encrypted local vault."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, key: str, value: str | None) -> None:
        if value:
            self._values[key] = value
            secret_vault.set_secret(key, value)

    def get(self, key: str) -> str | None:
        value = self._values.get(key)
        if value is not None:
            return value
        value = secret_vault.get_secret(key)
        if value is not None:
            self._values[key] = value
        return value

    def forget(self, key: str) -> None:
        self._values.pop(key, None)
        secret_vault.delete_secret(key)

    def has(self, key: str) -> bool:
        return key in self._values or secret_vault.has_secret(key)

    def clear_prefix(self, prefix: str) -> None:
        for key in [k for k in self._values if k.startswith(prefix)]:
            self._values.pop(key, None)
        secret_vault.delete_prefix(prefix)

    def known_values(self) -> list[str]:
        values = list(self._values.values())
        for value in secret_vault.list_secret_values():
            if value not in values:
                values.append(value)
        return values

    def redact(self, text: str | None) -> str | None:
        return redact_text(text, self.known_values())


secret_store = RuntimeSecretStore()

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


GENERIC_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(password|passwd|pwd|token|secret)\s*=\s*('[^']*'|\"[^\"]*\"|[^\s]+)"),
    re.compile(r"(?i)\b(password|passwd|pwd|token|secret)\s*:\s*('[^']*'|\"[^\"]*\"|[^\s,}]+)"),
)


def redact_text(text: str | None, secrets: list[str] | tuple[str, ...] = ()) -> str | None:
    if text is None:
        return None
    redacted = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r":([^:@/\s]+)@", ":[REDACTED]@", redacted)
    for pattern in GENERIC_SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    return redacted


def redact_dsn(dsn: str | None) -> str | None:
    if not dsn:
        return dsn
    text = str(dsn)
    if "://" in text:
        try:
            parts = urlsplit(text)
            if parts.password:
                user = parts.username or ""
                netloc = user
                if user:
                    netloc += ":[REDACTED]"
                host = parts.hostname or ""
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                netloc += f"@{host}" if user else host
                if parts.port:
                    netloc += f":{parts.port}"
                return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        except Exception:
            pass
    return redact_text(text)


def looks_like_secret_dsn(dsn: str | None) -> bool:
    if not dsn:
        return False
    text = str(dsn)
    return bool(re.search(r":([^:@/\s]+)@", text) or re.search(r"(?i)\bpassword\s*=", text))


from __future__ import annotations

from fastapi import Request

from app.models.user import User


PROTECTED_ROUTE_PREFIXES = (
    "/",
    "/environments",
    "/postgres",
    "/catalog",
    "/query",
    "/logs",
    "/history",
)


def get_current_user(request: Request) -> User:
    try:
        username = request.session.get("username")
    except AssertionError:
        username = None
    return User(username=username or "local-user", is_authenticated=bool(username))


def login_enabled() -> bool:
    return False


def route_requires_auth(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in PROTECTED_ROUTE_PREFIXES)

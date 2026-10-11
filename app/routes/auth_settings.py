from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.routes.context import build_context
from app.security.auth import PROTECTED_ROUTE_PREFIXES
from app.web import templates


router = APIRouter()


@router.get("/login-settings", response_class=HTMLResponse)
async def login_settings(request: Request):
    ctx = await build_context(request)
    return templates.TemplateResponse(
        request=request,
        name="login_settings.html",
        context={**ctx, "protected_routes": PROTECTED_ROUTE_PREFIXES},
    )


from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.routes.context import build_context
from app.services import advisor_service
from app.web import templates


router = APIRouter()


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request):
    ctx = await build_context(request)
    snapshot = {}
    recs = []
    error = ctx.get("database_error")
    if ctx.get("selected_postgres") and not error:
        try:
            snapshot = await advisor_service.get_catalog_snapshot(ctx["selected_db"])
            recs = await advisor_service.catalog_recommendations(ctx["selected_db"])
        except Exception as exc:
            error = str(exc)
    return templates.TemplateResponse(request=request, name="catalog.html", context={**ctx, "snapshot": snapshot, "recs": recs, "error": error})


@router.get("/recommendations", response_class=HTMLResponse)
async def recommendations(request: Request):
    ctx = await build_context(request)
    recs = []
    error = ctx.get("database_error")
    if ctx.get("selected_postgres") and not error:
        try:
            recs = await advisor_service.catalog_recommendations(ctx["selected_db"])
        except Exception as exc:
            error = str(exc)
    return templates.TemplateResponse(request=request, name="recommendations.html", context={**ctx, "recs": recs, "source": "Catálogo", "error": error})

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.routes.context import build_context
from app.services import advisor_service
from app.web import templates


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    ctx = await build_context(request)
    selected_db = ctx["selected_db"]
    conn = {"ok": False, "error": ctx.get("database_error") or "Configure e selecione uma conexão PostgreSQL."}
    catalog = {}
    workload = []
    workload_error = None
    if ctx.get("selected_postgres") and not ctx.get("database_error"):
        conn = await advisor_service.connection_info(selected_db)
        if conn.get("ok"):
            try:
                catalog = await advisor_service.get_catalog_snapshot(selected_db)
            except Exception as exc:
                catalog = {}
                conn = {"ok": False, "error": str(exc)}
            workload, workload_error = await advisor_service.get_optional_workload(10, database=selected_db)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={**ctx, "conn": conn, "catalog": catalog, "workload": workload, "workload_error": workload_error},
    )

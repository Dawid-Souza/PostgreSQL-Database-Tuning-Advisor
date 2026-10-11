from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.routes.context import build_context
from app.services import advisor_service
from app.web import templates


router = APIRouter()


@router.get("/query", response_class=HTMLResponse)
async def query_page(request: Request):
    ctx = await build_context(request)
    return templates.TemplateResponse(request=request, name="query.html", context={**ctx, "query": "", "plan": None, "recs": [], "error": None, "analyze": False})


@router.post("/query", response_class=HTMLResponse)
async def query_analyze(request: Request, query: str = Form(...), analyze: str | None = Form(None), db: str | None = Form(None)):
    ctx = await build_context(request, posted_db=db)
    use_analyze = analyze == "on"
    try:
        plan = await advisor_service.explain_json(query, analyze=use_analyze, database=ctx["selected_db"])
        recs = await advisor_service.analyze_plan(plan, query, database=ctx["selected_db"])
        error = None
    except Exception as exc:
        plan = None
        recs = []
        error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="query.html",
        context={**ctx, "query": query, "plan": plan, "recs": recs, "error": error, "analyze": use_analyze},
    )

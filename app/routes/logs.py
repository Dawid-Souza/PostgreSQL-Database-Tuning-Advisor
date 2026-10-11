from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.repositories import config_repository, log_repository
from app.routes.context import build_context
from app.services.log_analysis_service import process_log_text_to_cache
from app.services.server_log_service import command_preview, fetch_server_logs
from app.web import templates


router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, run_id: int | None = None, group_page: int = 1, rec_page: int = 1):
    ctx = await build_context(request)
    selected_run = run_id
    if selected_run is None:
        latest = log_repository.latest_run(ctx["selected_db"])
        selected_run = int(latest["id"]) if latest else None
    result = log_repository.build_result(selected_run, group_page=group_page, rec_page=rec_page, page_size=settings.log_cache_page_size) if selected_run else None
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            **ctx,
            "log_text": "",
            "result": result,
            "min_ms": (result or {}).get("run", {}).get("min_ms", 0) if result else 0,
            "fetch_error": None,
            "fetch_command": (result or {}).get("run", {}).get("command") if result else None,
            "lines": (result or {}).get("run", {}).get("lines_requested", 5000) if result else 5000,
            "runs": log_repository.list_runs(15),
        },
    )


@router.post("/logs/manual", response_class=HTMLResponse)
async def logs_manual(request: Request, log_text: str = Form(...), min_ms: float = Form(0), db: str | None = Form(None)):
    ctx = await build_context(request, posted_db=db)
    run_id = await process_log_text_to_cache(
        text=log_text,
        min_ms=min_ms,
        database=ctx["selected_db"],
        postgres_config_id=(ctx.get("selected_postgres") or {}).get("id"),
        environment_id=(ctx.get("selected_environment") or {}).get("id"),
        source="manual",
    )
    return RedirectResponse(f"/logs?run_id={run_id}", status_code=303)


@router.post("/logs/fetch", response_class=HTMLResponse)
async def logs_fetch(
    request: Request,
    min_ms: float = Form(0),
    lines: int = Form(5000),
    max_bytes: int | None = Form(None),
    db: str | None = Form(None),
    action: str = Form("preview"),
    confirm_execution: str | None = Form(None),
):
    ctx = await build_context(request, posted_db=db)
    environment = ctx.get("selected_environment")
    result = None
    fetch_error = None
    fetch_command = None
    if not environment:
        fetch_error = "Selecione um ambiente antes de buscar logs."
    elif action == "preview":
        try:
            fetch_command = command_preview(environment, lines)
        except Exception as exc:
            fetch_error = str(exc)
    else:
        fetched = fetch_server_logs(environment, lines=lines, max_bytes=max_bytes, confirm_execution=(confirm_execution == "on"))
        fetch_command = fetched.command
        if fetched.ok:
            run_id = await process_log_text_to_cache(
                text=fetched.text,
                min_ms=min_ms,
                database=ctx["selected_db"],
                postgres_config_id=(ctx.get("selected_postgres") or {}).get("id"),
                environment_id=environment.get("id"),
                source="ssh",
                lines_requested=lines,
                command=fetched.command,
                fetch_error=fetched.error,
                raw_bytes=fetched.raw_bytes,
                raw_truncated=fetched.truncated,
            )
            result = log_repository.build_result(run_id, page_size=settings.log_cache_page_size)
        else:
            fetch_error = fetched.error

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            **ctx,
            "log_text": "",
            "result": result,
            "min_ms": min_ms,
            "fetch_error": fetch_error,
            "fetch_command": fetch_command,
            "lines": lines,
            "runs": log_repository.list_runs(15),
        },
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    ctx = await build_context(request)
    return templates.TemplateResponse(request=request, name="history.html", context={**ctx, "runs": log_repository.list_runs(100), "message": request.query_params.get("message")})


@router.post("/history/delete-selected")
async def delete_selected_history(run_ids: list[int] = Form(default=[]), return_to: str = Form("/history")):
    deleted = log_repository.delete_runs(run_ids)
    target = return_to if return_to in {"/history", "/logs"} else "/history"
    return RedirectResponse(f"{target}?message={deleted}%20an%C3%A1lise(s)%20exclu%C3%ADda(s)", status_code=303)


@router.post("/history/delete-all")
async def delete_all_history(confirm_text: str = Form(""), return_to: str = Form("/history")):
    target = return_to if return_to in {"/history", "/logs"} else "/history"
    if confirm_text != "LIMPAR":
        return RedirectResponse(f"{target}?message=Confirma%C3%A7%C3%A3o%20inv%C3%A1lida", status_code=303)
    deleted = log_repository.delete_all_runs()
    return RedirectResponse(f"{target}?message={deleted}%20an%C3%A1lise(s)%20exclu%C3%ADda(s)", status_code=303)

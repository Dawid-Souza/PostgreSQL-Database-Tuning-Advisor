from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories import config_repository
from app.routes.context import build_context
from app.security.secret_store import secret_store
from app.services import postgres_service
from app.services.config_service import save_postgres_from_form, secret_key
from app.web import templates


router = APIRouter(prefix="/postgres")


def _with_secret_status(configs: list[dict]) -> list[dict]:
    decorated = []
    for item in configs:
        copy = dict(item)
        copy["password_available"] = bool(copy.get("has_password") and secret_store.has(secret_key("postgres", str(copy["id"]), "password")))
        decorated.append(copy)
    return decorated


@router.get("", response_class=HTMLResponse)
async def postgres_page(request: Request, edit_id: str | None = None):
    ctx = await build_context(request, include_databases=False)
    ctx["postgres_configs"] = _with_secret_status(ctx["postgres_configs"])
    edit_config = config_repository.get_postgres_config(edit_id) if edit_id else None
    return templates.TemplateResponse(
        request=request,
        name="postgres_configs.html",
        context={**ctx, "edit_config": edit_config, "test_result": None, "message": request.query_params.get("message")},
    )


@router.post("", response_class=HTMLResponse)
async def save_postgres(request: Request):
    form = await request.form()
    saved = save_postgres_from_form(form)
    await postgres_service.close_pools_for_config(str(saved["id"]))
    preview = postgres_service.safe_conninfo_preview(str(saved["id"]))
    try:
        test_result = await postgres_service.test_connection(config_id=str(saved["id"]))
        message = "Conexão salva e testada com sucesso."
    except Exception as exc:
        test_result = {"ok": False, "error": secret_store.redact(str(exc)), "conninfo_preview": preview}
        message = "Conexão salva, mas o teste falhou."
    ctx = await build_context(request, include_databases=False)
    ctx["postgres_configs"] = _with_secret_status(ctx["postgres_configs"])
    return templates.TemplateResponse(
        request=request,
        name="postgres_configs.html",
        context={**ctx, "edit_config": saved, "test_result": test_result, "message": message},
    )


@router.post("/select")
async def select_postgres(config_id: str = Form(...)):
    config_repository.select_postgres_config(config_id)
    await postgres_service.close_pools_for_config(config_id)
    return RedirectResponse("/postgres?message=Conex%C3%A3o%20selecionada", status_code=303)


@router.post("/delete")
async def delete_postgres(config_id: str = Form(...)):
    config_repository.delete_postgres_config(config_id)
    await postgres_service.close_pools_for_config(config_id)
    return RedirectResponse("/postgres?message=Conex%C3%A3o%20removida", status_code=303)


@router.post("/test", response_class=HTMLResponse)
async def test_postgres(request: Request, config_id: str = Form(...)):
    ctx = await build_context(request, include_databases=False)
    ctx["postgres_configs"] = _with_secret_status(ctx["postgres_configs"])
    preview = postgres_service.safe_conninfo_preview(config_id)
    try:
        result = await postgres_service.test_connection(config_id=config_id)
    except Exception as exc:
        result = {"ok": False, "error": secret_store.redact(str(exc)), "conninfo_preview": preview}
    edit_config = config_repository.get_postgres_config(config_id)
    return templates.TemplateResponse(
        request=request,
        name="postgres_configs.html",
        context={**ctx, "edit_config": edit_config, "test_result": result, "message": None},
    )

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories import config_repository
from app.routes.context import build_context
from app.services.config_service import save_environment_from_form
from app.web import templates


router = APIRouter(prefix="/environments")


@router.get("", response_class=HTMLResponse)
async def environments_page(request: Request, edit_id: str | None = None):
    ctx = await build_context(request, include_databases=False)
    edit_environment = config_repository.get_environment(edit_id) if edit_id else None
    return templates.TemplateResponse(
        request=request,
        name="environments.html",
        context={**ctx, "edit_environment": edit_environment, "message": request.query_params.get("message")},
    )


@router.post("", response_class=HTMLResponse)
async def save_environment(request: Request):
    form = await request.form()
    save_environment_from_form(form)
    return RedirectResponse("/environments?message=Ambiente%20salvo", status_code=303)


@router.post("/select")
async def select_environment(environment_id: str = Form(...)):
    config_repository.select_environment(environment_id)
    return RedirectResponse("/environments?message=Ambiente%20selecionado", status_code=303)


@router.post("/delete")
async def delete_environment(environment_id: str = Form(...)):
    config_repository.delete_environment(environment_id)
    return RedirectResponse("/environments?message=Ambiente%20removido", status_code=303)

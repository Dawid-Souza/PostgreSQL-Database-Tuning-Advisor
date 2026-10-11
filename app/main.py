from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.repositories.log_repository import init_store
from app.routes import auth_settings, catalog, configurations, dashboard, logs, postgres, public, query
from app.services.postgres_service import close_pools


app = FastAPI(title=settings.app_name, version=settings.app_version)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")

# Public routes are separate from the main application routes so real auth can
# later add session/cookie middleware and protect the operational panel without
# moving handlers.
app.include_router(public.router)
app.include_router(dashboard.router)
app.include_router(configurations.router)
app.include_router(postgres.router)
app.include_router(catalog.router)
app.include_router(query.router)
app.include_router(logs.router)
app.include_router(auth_settings.router)


@app.on_event("startup")
async def startup() -> None:
    init_store()


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_pools()

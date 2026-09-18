from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.exceptions import ResourceOutOfScopeError
from app.core.firestore_client import get_firestore_client
from app.routers import (
    ai_router,
    auth_router,
    certificates_router,
    dashboard_router,
    departments_router,
    employees_router,
    leaves_router,
    notifications_router,
    positions_router,
    settings_router,
    trial_periods_router,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the Firestore client eagerly so a misconfigured emulator host or
    # missing credentials fails loudly at boot, not on the first request.
    get_firestore_client()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(departments_router.router)
    app.include_router(positions_router.router)
    app.include_router(employees_router.router)
    app.include_router(leaves_router.router)
    app.include_router(trial_periods_router.router)
    app.include_router(notifications_router.router)
    app.include_router(certificates_router.router)
    app.include_router(settings_router.router)
    app.include_router(ai_router.router)

    @app.exception_handler(ResourceOutOfScopeError)
    async def resource_out_of_scope_handler(request: Request, exc: ResourceOutOfScopeError):
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/")
    def root():
        return RedirectResponse(url="/login")

    return app


app = create_app()

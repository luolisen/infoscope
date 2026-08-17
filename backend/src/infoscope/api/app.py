from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from infoscope.api.routes.archive_search import router as archive_search_router
from infoscope.api.routes.ask import router as ask_router
from infoscope.api.routes.auth import router as auth_router
from infoscope.api.routes.brief import router as brief_router
from infoscope.api.routes.events import router as events_router
from infoscope.api.routes.health import router as health_router
from infoscope.api.routes.maintenance import router as maintenance_router
from infoscope.api.routes.model_settings import router as model_settings_router
from infoscope.api.routes.now import router as now_router
from infoscope.api.routes.onboarding import router as onboarding_router
from infoscope.db import close_database
from infoscope.errors import ApiError
from infoscope.schemas.common import ErrorDetail, ErrorResponse

FRONTEND_DIST = Path(__file__).resolve().parents[4] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_database()


app = FastAPI(
    title="Infoscope API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(archive_search_router, prefix="/api/v1")
app.include_router(brief_router, prefix="/api/v1")
app.include_router(ask_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(maintenance_router, prefix="/api/v1")
app.include_router(model_settings_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
app.include_router(now_router, prefix="/api/v1")


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid4()))
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, _: RequestValidationError) -> JSONResponse:
    current_request_id = request_id(request)
    onboarding_selection_path = request.method == "PUT" and request.url.path in {
        "/api/v1/onboarding",
        "/api/v1/scope",
    }
    payload = ErrorResponse(
        error=ErrorDetail(
            code=(
                "INVALID_ONBOARDING_SELECTION"
                if onboarding_selection_path
                else "VALIDATION_ERROR"
            ),
            message=(
                "The onboarding selection is invalid."
                if onboarding_selection_path
                else "Request validation failed."
            ),
            request_id=current_request_id,
        )
    )
    return JSONResponse(
        status_code=422,
        content=payload.model_dump(),
        headers={"x-request-id": current_request_id},
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    current_request_id = request_id(request)
    payload = ErrorResponse(
        error=ErrorDetail(
            code=error.code,
            message=error.message,
            request_id=current_request_id,
        )
    )
    return JSONResponse(
        status_code=error.status_code,
        content=payload.model_dump(),
        headers={"x-request-id": current_request_id},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, _: Exception) -> JSONResponse:
    current_request_id = request_id(request)
    payload = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An internal server error occurred.",
            request_id=current_request_id,
        )
    )
    return JSONResponse(
        status_code=500,
        content=payload.model_dump(),
        headers={"x-request-id": current_request_id},
    )


def mount_frontend(application: FastAPI, dist: Path = FRONTEND_DIST) -> bool:
    """Serve the built SPA without changing or shadowing the API contract."""
    index = dist / "index.html"
    assets = dist / "assets"
    if not index.is_file() or not assets.is_dir():
        return False

    application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(index)

    @application.get("/{path:path}", include_in_schema=False)
    async def frontend_route(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/") or "." in Path(path).name:
            raise HTTPException(status_code=404)
        return FileResponse(index)

    return True


mount_frontend(app)

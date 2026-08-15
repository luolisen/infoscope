from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from infoscope.api.routes.health import router as health_router
from infoscope.db import close_database
from infoscope.schemas.common import ErrorDetail, ErrorResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_database()


app = FastAPI(
    title="Infoscope API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health_router, prefix="/api/v1")


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
    payload = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            request_id=current_request_id,
        )
    )
    return JSONResponse(
        status_code=422,
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

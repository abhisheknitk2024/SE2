"""HTTP layer: app factory, request correlation, error envelope, ops endpoints.

Kept as a factory (``create_app``) plus a module-level instance so that tests can
build an app with their own settings, while uvicorn still gets ``relay.app:app``.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from relay import __version__
from relay.api import health
from relay.config import Settings, get_settings
from relay.db import Database
from relay.log import configure_logging, get_logger

log = get_logger("relay.api")

# Stable, machine-readable codes. Clients switch on `code`, humans read `message`;
# never make a client parse prose or a status code that we might want to reuse.
_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable",
    429: "too_many_requests",
}


def error_body(status: int, code: str, message: str, request_id: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def _request_id(request: Request) -> str:
    """Accept a caller-supplied correlation id, but never trust it blindly.

    Echoing arbitrary client input into logs and headers is how you get log
    injection and header splitting. Length-bounded, printable, ASCII, else drop it.
    """
    supplied = request.headers.get("x-request-id", "")
    if 0 < len(supplied) <= 64 and supplied.isascii() and supplied.isprintable():
        return supplied
    return uuid.uuid4().hex


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(
            settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
        )
        db.open()
        app.state.db = db
        log.info("api.started", extra={"env": settings.env, "version": __version__})
        try:
            yield
        finally:
            db.close()
            log.info("api.stopped")

    app = FastAPI(title="Relay", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = _request_id(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "http.request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise  # the Exception handler below turns it into the error envelope
        response.headers["X-Request-Id"] = request_id
        log.info(
            "http.request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                exc.status_code,
                _CODE_BY_STATUS.get(exc.status_code, "http_error"),
                str(exc.detail),
                request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Deliberately opaque to the caller: internal messages leak table names,
        # driver errors and sometimes connection strings. The detail goes to logs,
        # tied together by request_id.
        request_id = getattr(request.state, "request_id", "")
        log.exception(
            "unhandled_exception",
            extra={"request_id": request_id, "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content=error_body(500, "internal_error", "internal server error", request_id),
        )

    app.include_router(health.router)
    return app


app = create_app()

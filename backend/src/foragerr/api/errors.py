"""Uniform 4xx error shape for the API (FRG-API-002).

Every 4xx response body is ``{"message": <str>, "errors": [...]}``. FastAPI's
default ``{"detail": ...}`` shape never reaches a client: this module
replaces the framework's request-validation and HTTP-exception handlers, and
adds :class:`ApiError` for application-raised 4xx (unknown sort keys,
resource-not-found, command validation failures). Pydantic validation
failures — including a malformed JSON request body, which surfaces as a
``RequestValidationError`` with a ``body`` location — are mapped into
``errors[]`` entries naming the offending field.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

__all__ = ["ApiError", "error_body", "register_error_handlers"]


class ApiError(Exception):
    """An application-raised 4xx carrying the uniform error shape.

    ``field`` is optional; when set, the response's ``errors[]`` names it
    (e.g. an unknown paging ``sortKey``, an unknown command ``name``).
    """

    def __init__(self, status_code: int, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.field = field


def error_body(message: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The uniform 4xx shape: ``{"message": <str>, "errors": [...]}``."""
    return {"message": message, "errors": errors or []}


def _field_from_loc(loc: tuple[Any, ...]) -> str | None:
    """Turn a Pydantic error ``loc`` tuple into a dotted field name.

    ``loc`` looks like ``("body", "name")`` or ``("query", "sortKey")``. A
    whole-body failure has no meaningful field (``None``): a malformed JSON
    body reports ``loc=("body", <char offset>)`` where the numeric offset is
    not a field name.
    """
    parts = [
        str(p)
        for p in loc
        if p not in ("body", "query", "path", "header", "cookie") and not isinstance(p, int)
    ]
    return ".".join(parts) if parts else None


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "field": _field_from_loc(tuple(err.get("loc", ()))),
            "message": (
                "malformed JSON body" if err.get("type") == "json_invalid" else err.get("msg", "invalid value")
            ),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=400, content=error_body("request validation failed", errors)
    )


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else "request failed"
    errors: list[dict[str, Any]] = []
    if isinstance(exc.detail, dict):
        # Endpoints may raise HTTPException(..., detail={"message":, "field":})
        # for a field-precise 4xx without needing a dedicated exception type.
        message = exc.detail.get("message", message)
        if exc.detail.get("field"):
            errors = [{"field": exc.detail["field"], "message": message}]
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(message, errors),
        headers=headers,
    )


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    errors = [{"field": exc.field, "message": exc.message}] if exc.field else []
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.message, errors))


def register_error_handlers(app: FastAPI) -> None:
    """Install the uniform-shape handlers (FRG-API-002).

    Registered for ``RequestValidationError`` (covers Pydantic body/query/path
    validation failures and malformed JSON bodies), Starlette's
    ``HTTPException`` (covers 404s — including the framework's own
    route-not-found — and any handler-raised ``HTTPException``), and the
    application's :class:`ApiError`.
    """
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(ApiError, _api_error_handler)

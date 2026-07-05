"""Download-client schema + test HTTP surface (FRG-DL-002, FRG-API-009).

Mirrors :mod:`foragerr.api.indexers` — the same zero-frontend provider seam,
reused generically rather than forked:

- ``GET /api/v1/downloadclient/schema`` — every implementation's renderable
  ``fields[]`` metadata (derived from its Pydantic settings contract; secret
  fields flagged, carrying no value).
- ``POST /api/v1/downloadclient/test`` — validates a settings payload, then runs
  the implementation's live ``test()`` action, returning success or a
  field-precise failure in the uniform error shape without persisting anything.

The outbound factory is read from ``app.state.http_factory`` when present (the
test-injection seam) and otherwise built from settings — no other module
constructs HTTP clients for download-client traffic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import ApiError
from foragerr.downloads import make_download_factory
from foragerr.downloads.errors import DownloadClientError
from foragerr.downloads.registry import (
    ClientBuildContext,
    UnknownImplementationError,
    get_implementation,
    implementations,
    validate_settings,
)
from foragerr.indexers.schema import schema_for
from foragerr.providers.backoff import ProviderBackoff

router = APIRouter(prefix="/downloadclient", tags=["downloadclient"])


class DownloadClientImplementationSchema(BaseModel):
    """One implementation's schema template (FRG-API-009)."""

    implementation: str
    name: str
    protocol: str
    fields: list[dict[str, Any]]


class DownloadClientTestRequest(BaseModel):
    """Body for ``POST /downloadclient/test``."""

    implementation: str
    settings: dict[str, Any]


class DownloadClientTestResponse(BaseModel):
    """A passing connectivity/credentials test result."""

    success: bool
    message: str
    version: str | None = None
    warnings: list[str] = []


def _factory(request: Request):
    """The outbound factory: an ``app.state.http_factory`` test override wins,
    else the shared ``make_download_factory`` seam (mirrors ``api.indexers``)."""
    override = getattr(request.app.state, "http_factory", None)
    if override is not None:
        return override
    return make_download_factory(request.app.state.settings)


@router.get("/schema", response_model=list[DownloadClientImplementationSchema])
async def downloadclient_schema() -> list[DownloadClientImplementationSchema]:
    """Renderable settings-field metadata for every implementation (FRG-DL-002,
    FRG-API-009). Purely derived from each settings contract — no values, so no
    secret can be echoed here."""
    return [
        DownloadClientImplementationSchema(
            implementation=impl.name,
            name=impl.label,
            protocol=impl.protocol,
            fields=[spec.as_dict() for spec in schema_for(impl.settings_model)],
        )
        for impl in implementations()
    ]


@router.post("/test", response_model=DownloadClientTestResponse)
async def downloadclient_test(
    body: DownloadClientTestRequest, request: Request
) -> DownloadClientTestResponse:
    """Validate settings, then run the client's live ``test()`` (FRG-DL-002).

    Returns success, or a field-precise failure in the uniform error shape.
    Nothing is persisted (this is a pre-save test)."""
    try:
        impl = get_implementation(body.implementation)
    except UnknownImplementationError as exc:
        raise ApiError(400, str(exc), field="implementation") from exc

    try:
        settings_model = validate_settings(body.implementation, body.settings)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    if impl.client_factory is None:
        raise ApiError(
            400,
            f"download client {impl.name!r} has no runnable client to test yet",
            field="implementation",
        )

    db = request.app.state.db
    ctx = ClientBuildContext(
        row=_TransientRow(implementation=impl.name, protocol=impl.protocol),
        settings=settings_model,
        db=db,
        http_factory=_factory(request),
        backoff=ProviderBackoff(db),
        mappings=[],
        app_settings=request.app.state.settings,
    )
    client = impl.client_factory(ctx)
    try:
        result = await client.test()
    except DownloadClientError as exc:
        raise ApiError(400, str(exc), field="base_url") from exc

    return DownloadClientTestResponse(
        success=result.success,
        message=result.message,
        version=result.version,
        warnings=list(result.warnings),
    )


class _TransientRow:
    """A minimal stand-in for a ``DownloadClientRow`` in the pre-save test path.

    The test action never persists, so it needs no real row — only the fields a
    client factory reads: ``id`` (0, mirroring the indexer test's
    ``indexer_id=0``), ``implementation``, ``protocol`` and the
    ``remove_completed_downloads`` flag (irrelevant to ``test()``)."""

    id = 0

    def __init__(self, *, implementation: str, protocol: str) -> None:
        self.implementation = implementation
        self.protocol = protocol
        self.remove_completed_downloads = True


def _validation_error(exc: ValidationError) -> ApiError:
    """Map a settings ``ValidationError`` to a field-precise 400 (uniform shape)."""
    parts = []
    first_field: str | None = None
    for err in exc.errors():
        field = "settings." + ".".join(str(p) for p in err.get("loc", ()))
        if first_field is None:
            first_field = field
        parts.append(f"{field}: {err.get('msg', 'invalid value')}")
    message = "download client settings validation failed — " + "; ".join(parts)
    return ApiError(400, message, field=first_field)

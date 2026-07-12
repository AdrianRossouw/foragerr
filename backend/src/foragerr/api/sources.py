"""Store-source connect/manage HTTP surface (FRG-SRC-001/002/003/005).

CRUD + lifecycle over ``/api/v1/sources``, following the indexer provider-
resource conventions:

- ``GET /sources/schema`` — every store type's renderable ``fields[]`` metadata.
- ``GET /sources`` — configured sources with PUBLIC settings (the cookie is
  dropped — write-only, FRG-SRC-002).
- ``POST /sources`` — connect: a LIVE order-list validation runs BEFORE anything
  is persisted; success reports the order count, failure persists nothing and
  names the cause (FRG-SRC-002).
- ``POST /sources/{id}/reconnect`` — re-paste a cookie on an ``expired`` source.
- ``POST /sources/{id}/disconnect`` — delete the credential, keep entitlements.
- ``POST /sources/{id}/sync`` — enqueue a manual "Sync now" for one source.
- ``DELETE /sources/{id}`` — remove a source entirely (and its entitlements).

The outbound factory is an ``app.state.http_factory`` test override when present,
else built from settings — the same seam ``api.indexers`` uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import ApiError
from foragerr.http import HttpClientFactory
from foragerr.indexers.schema import schema_for
from foragerr.keystore import ENC_PREFIX, top_level_secret_field_names
from foragerr.sources.commands import SOURCE_SYNC_TASK, make_humble_factory
from foragerr.sources.models import SourceRow
from foragerr.sources.registry import (
    UnknownSourceTypeError,
    get_source_type,
    implementations,
    validate_settings,
)
from foragerr.sources.repo import (
    delete_source,
    get_source,
    list_sources,
    load_source_settings,
    public_settings,
)
from foragerr.sources.service import (
    SourceConnectError,
    connect_source,
    disconnect_source,
    reconnect_source,
)

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceTypeSchema(BaseModel):
    """One store type's schema template (mirrors the indexer schema)."""

    type: str
    name: str
    fields: list[dict[str, Any]]


class SourceResource(BaseModel):
    """A configured source as returned by the surface (FRG-SRC-001).

    ``settings`` is the PUBLIC view — the cookie is dropped, never echoed
    (write-only, FRG-SRC-002)."""

    id: int
    type: str
    name: str
    connection_state: str
    auto_sync: bool
    last_sync_status: str | None
    settings: dict[str, Any]

    @classmethod
    def from_row(cls, row: SourceRow, settings: BaseModel | None) -> "SourceResource":
        return cls(
            id=row.id,
            type=row.type,
            name=row.name,
            connection_state=row.connection_state,
            auto_sync=row.auto_sync,
            last_sync_status=row.last_sync_status,
            settings=public_settings(settings) if settings is not None else {},
        )


class SourceConnect(BaseModel):
    """Request body for ``POST /sources`` — the store type + its settings dict
    (which must include the required ``session_cookie``)."""

    type: str
    name: str | None = None
    settings: dict[str, Any]
    auto_sync: bool = False


class SourceReconnect(BaseModel):
    """Request body for ``POST /sources/{id}/reconnect`` — a fresh settings dict."""

    settings: dict[str, Any]


class ConnectResponse(BaseModel):
    """A successful connect/reconnect result with the validated order count."""

    source: SourceResource
    order_count: int
    message: str


def _factory(request: Request) -> HttpClientFactory:
    override = getattr(request.app.state, "http_factory", None)
    if override is not None:
        return override
    return make_humble_factory(request.app.state.settings)


def _min_interval(request: Request) -> float:
    return float(request.app.state.settings.source_min_request_interval_seconds)


@router.get("/schema", response_model=list[SourceTypeSchema])
async def sources_schema() -> list[SourceTypeSchema]:
    """Renderable settings-field metadata for every store type (FRG-SRC-001)."""
    return [
        SourceTypeSchema(
            type=impl.name,
            name=impl.label,
            fields=[spec.as_dict() for spec in schema_for(impl.settings_model)],
        )
        for impl in implementations()
    ]


@router.get("", response_model=list[SourceResource])
async def list_sources_endpoint(request: Request) -> list[SourceResource]:
    """Every configured source with its PUBLIC settings (cookie dropped)."""
    db = request.app.state.db
    records: list[SourceResource] = []
    for row in await list_sources(db):
        try:
            model = load_source_settings(row.type, row.settings)
        except Exception:  # noqa: BLE001 — a disconnected/blank row loads no secret
            model = None
        records.append(SourceResource.from_row(row, model))
    return records


@router.post("", status_code=201, response_model=ConnectResponse)
async def connect_source_endpoint(
    body: SourceConnect, request: Request
) -> ConnectResponse:
    """Connect a source: validate the cookie live, then persist (FRG-SRC-002)."""
    try:
        source_type = get_source_type(body.type)
    except UnknownSourceTypeError as exc:
        raise ApiError(400, str(exc), field="type") from exc
    _reject_reserved_secret_prefix(body.type, body.settings)
    try:
        model = validate_settings(body.type, body.settings)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    db = request.app.state.db
    try:
        row, order_count = await connect_source(
            db,
            _factory(request),
            source_type=body.type,
            name=body.name or source_type.label,
            settings=model,
            auto_sync=body.auto_sync,
            min_interval=_min_interval(request),
        )
    except SourceConnectError as exc:
        field = "settings.session_cookie" if exc.cause == "auth" else "type"
        raise ApiError(400, str(exc), field=field) from exc

    return ConnectResponse(
        source=SourceResource.from_row(row, model),
        order_count=order_count,
        message=f"Connected — {order_count} order(s)",
    )


@router.post("/{source_id}/reconnect", response_model=ConnectResponse)
async def reconnect_source_endpoint(
    source_id: int, body: SourceReconnect, request: Request
) -> ConnectResponse:
    """Re-paste a cookie on an existing source and return it to ``connected``
    (FRG-SRC-005 reconnect resumes)."""
    db = request.app.state.db
    existing = await get_source(db, source_id)
    if existing is None:
        raise ApiError(404, f"source {source_id} not found")
    _reject_reserved_secret_prefix(existing.type, body.settings)
    try:
        model = validate_settings(existing.type, body.settings)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    try:
        row, order_count = await reconnect_source(
            db,
            _factory(request),
            existing,
            settings=model,
            min_interval=_min_interval(request),
        )
    except SourceConnectError as exc:
        field = "settings.session_cookie" if exc.cause == "auth" else "type"
        raise ApiError(400, str(exc), field=field) from exc
    return ConnectResponse(
        source=SourceResource.from_row(row, model),
        order_count=order_count,
        message=f"Reconnected — {order_count} order(s)",
    )


@router.post("/{source_id}/disconnect", response_model=SourceResource)
async def disconnect_source_endpoint(
    source_id: int, request: Request
) -> SourceResource:
    """Disconnect: delete the credential, keep entitlements (FRG-SRC-001)."""
    db = request.app.state.db
    row = await disconnect_source(db, source_id)
    if row is None:
        raise ApiError(404, f"source {source_id} not found")
    return SourceResource.from_row(row, None)


@router.post("/{source_id}/sync", status_code=202)
async def sync_source_endpoint(source_id: int, request: Request) -> dict[str, Any]:
    """Enqueue a manual "Sync now" for one source (FRG-SRC-003).

    Runs immediately regardless of the scheduled interval; the diff runs on the
    command backbone and progress is observable via the command/queue surface."""
    db = request.app.state.db
    row = await get_source(db, source_id)
    if row is None:
        raise ApiError(404, f"source {source_id} not found")
    if row.connection_state != "connected":
        raise ApiError(
            409,
            f"source {source_id} is {row.connection_state}; reconnect before syncing",
        )
    record = await request.app.state.commands.enqueue(
        SOURCE_SYNC_TASK, {"source_id": source_id}, triggered_by="manual"
    )
    return {"command_id": record.id, "status": record.status}


@router.delete("/{source_id}", status_code=204)
async def delete_source_endpoint(source_id: int, request: Request) -> None:
    """Remove a source entirely (and its entitlements). Unknown id -> 404."""
    db = request.app.state.db
    if not await delete_source(db, source_id):
        raise ApiError(404, f"source {source_id} not found")
    return None


def _reject_reserved_secret_prefix(source_type: str, supplied: dict[str, Any]) -> None:
    """Reject a user-supplied secret beginning with the reserved ``enc:v1:``
    framing prefix (FRG-AUTH-008) — it would be stored as plaintext and then fail
    to decrypt. Mirrors ``api.indexers._reject_reserved_secret_prefix``."""
    model_cls = get_source_type(source_type).settings_model
    for name in top_level_secret_field_names(model_cls):
        value = supplied.get(name)
        if isinstance(value, str) and value.startswith(ENC_PREFIX):
            raise ApiError(
                422,
                f"settings.{name}: value must not begin with the reserved "
                f"'{ENC_PREFIX}' prefix (it is reserved for at-rest secret framing)",
                field=f"settings.{name}",
            )


def _validation_error(exc: ValidationError) -> ApiError:
    """Map a settings ``ValidationError`` to a field-precise 400 (uniform shape)."""
    parts = []
    first_field: str | None = None
    for err in exc.errors():
        field = "settings." + ".".join(str(p) for p in err.get("loc", ()))
        if first_field is None:
            first_field = field
        parts.append(f"{field}: {err.get('msg', 'invalid value')}")
    message = "source settings validation failed — " + "; ".join(parts)
    return ApiError(400, message, field=first_field)

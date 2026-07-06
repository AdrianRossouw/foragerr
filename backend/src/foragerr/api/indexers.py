"""Indexer schema + test HTTP surface (FRG-IDX-003, FRG-API-009).

Two endpoints, the zero-frontend extensibility seam:

- ``GET /api/v1/indexer/schema`` — every implementation's renderable
  ``fields[]`` metadata (order/name/type/label/help/required/secret/
  selectOptions/advanced), derived from its Pydantic settings contract. Secret
  fields are flagged and carry no value (write-only).
- ``POST /api/v1/indexer/test`` — validates a settings payload, then runs a
  live ``?t=caps`` probe, returning success or a field-precise failure in the
  uniform error shape without persisting anything.

The outbound factory is read from ``app.state.http_factory`` when present (a
test-injection seam) and otherwise built from settings — no other module
constructs HTTP clients for indexer traffic.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import ApiError
from foragerr.http import HttpClientFactory
from foragerr.indexers.caps import parse_caps
from foragerr.search_ops import make_indexer_factory
from foragerr.indexers.errors import (
    IndexerAuthError,
    IndexerLimitError,
    IndexerMalformedError,
    IndexerUnavailable,
)
from foragerr.indexers.models import IndexerRow
from foragerr.indexers.newznab import NewznabClient
from foragerr.indexers.registry import (
    UnknownImplementationError,
    get_implementation,
    implementations,
    validate_settings,
)
from foragerr.indexers.repo import (
    create_indexer,
    delete_indexer,
    get_indexer,
    load_indexers,
    load_settings,
    public_settings,
    update_indexer,
)
from foragerr.indexers.schema import schema_for

router = APIRouter(prefix="/indexer", tags=["indexer"])


class IndexerImplementationSchema(BaseModel):
    """One implementation's schema template (FRG-API-009)."""

    implementation: str
    name: str
    protocol: str
    fields: list[dict[str, Any]]


class IndexerTestRequest(BaseModel):
    """Body for ``POST /indexer/test``: which implementation and its settings."""

    implementation: str
    settings: dict[str, Any]


class IndexerTestResponse(BaseModel):
    """A passing connectivity/credentials test result."""

    success: bool
    message: str
    categories: dict[int, str]
    degraded: bool


class IndexerResource(BaseModel):
    """A configured indexer as returned by the CRUD surface (FRG-IDX-001/002).

    Field names mirror the ``IndexerRow`` columns verbatim (the provider-
    resource convention shared with the frontend). ``settings`` is the PUBLIC
    settings view — secret values (e.g. ``api_key``) are dropped, never echoed
    (write-only, FRG-API-009)."""

    id: int
    name: str
    implementation: str
    protocol: str
    enabled: bool
    priority: int
    enable_rss: bool
    enable_auto: bool
    enable_interactive: bool
    settings: dict[str, Any]

    @classmethod
    def from_row(cls, row: IndexerRow, settings: BaseModel) -> "IndexerResource":
        return cls(
            id=row.id,
            name=row.name,
            implementation=row.implementation,
            protocol=row.protocol,
            enabled=row.enabled,
            priority=row.priority,
            enable_rss=row.enable_rss,
            enable_auto=row.enable_auto,
            enable_interactive=row.enable_interactive,
            settings=public_settings(settings),
        )


class IndexerCreate(BaseModel):
    """Request body for ``POST /indexer`` — row toggles plus the implementation
    settings dict (which must include any required secret, FRG-IDX-001)."""

    name: str
    implementation: str
    settings: dict[str, Any]
    enabled: bool = True
    enable_rss: bool = True
    enable_auto: bool = True
    enable_interactive: bool = True
    priority: int = 25


class IndexerUpdate(BaseModel):
    """Request body for ``PUT /indexer/{id}`` — every field optional (a partial
    update). An omitted ``settings`` leaves the stored settings untouched; a
    supplied ``settings`` that omits a secret key keeps the stored secret
    (write-only round-trip, FRG-API-009). ``implementation`` cannot change and
    is ignored if sent."""

    name: str | None = None
    implementation: str | None = None
    settings: dict[str, Any] | None = None
    enabled: bool | None = None
    enable_rss: bool | None = None
    enable_auto: bool | None = None
    enable_interactive: bool | None = None
    priority: int | None = None


def _factory(request: Request) -> HttpClientFactory:
    """The outbound factory: an ``app.state.http_factory`` test override wins,
    else the shared ``make_indexer_factory`` seam — so ``/indexer/test`` and
    real searches resolve indexer HTTP through the SAME indirection tests
    monkeypatch (mirrors ``api.release``)."""
    override = getattr(request.app.state, "http_factory", None)
    if override is not None:
        return override
    return make_indexer_factory(request.app.state.settings)


@router.get("/schema", response_model=list[IndexerImplementationSchema])
async def indexer_schema() -> list[IndexerImplementationSchema]:
    """Renderable settings-field metadata for every implementation (FRG-IDX-003,
    FRG-API-009). Purely derived from each settings contract; no values, so no
    secret can be echoed here."""
    return [
        IndexerImplementationSchema(
            implementation=impl.name,
            name=impl.label,
            protocol=impl.protocol,
            fields=[spec.as_dict() for spec in schema_for(impl.settings_model)],
        )
        for impl in implementations()
    ]


@router.get("", response_model=list[IndexerResource])
async def list_indexers_endpoint(request: Request) -> list[IndexerResource]:
    """Every configured indexer with its PUBLIC settings (FRG-IDX-001/002).

    Secret values are dropped from ``settings`` (write-only, FRG-API-009). A row
    whose stored settings can't load is skipped (isolated, never fatal —
    FRG-NFR-010), mirroring the search path."""
    db = request.app.state.db
    listing = await load_indexers(db)
    records: list[IndexerResource] = []
    for row in listing.healthy:
        model = load_settings(row.implementation, row.settings)
        records.append(IndexerResource.from_row(row, model))
    return records


@router.post("", status_code=201, response_model=IndexerResource)
async def create_indexer_endpoint(
    body: IndexerCreate, request: Request
) -> IndexerResource:
    """Validate + persist one indexer (FRG-IDX-001). Invalid settings yield a
    field-precise 400 and persist nothing; the response never echoes secrets."""
    try:
        get_implementation(body.implementation)
    except UnknownImplementationError as exc:
        raise ApiError(400, str(exc), field="implementation") from exc
    try:
        model = validate_settings(body.implementation, body.settings)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    db = request.app.state.db
    row = await create_indexer(
        db,
        name=body.name,
        implementation=body.implementation,
        settings=model,
        priority=body.priority,
        enabled=body.enabled,
        enable_rss=body.enable_rss,
        enable_auto=body.enable_auto,
        enable_interactive=body.enable_interactive,
    )
    return IndexerResource.from_row(row, model)


@router.put("/{indexer_id}", response_model=IndexerResource)
async def update_indexer_endpoint(
    indexer_id: int, body: IndexerUpdate, request: Request
) -> IndexerResource:
    """Partially update one indexer (FRG-IDX-001/002).

    An omitted ``settings`` leaves stored settings untouched; a supplied
    ``settings`` is MERGED over the stored values before validation, so an
    omitted secret key keeps the persisted secret (write-only, FRG-API-009).
    Unknown id -> 404; invalid merged settings -> field-precise 400."""
    db = request.app.state.db
    existing = await get_indexer(db, indexer_id)
    if existing is None:
        raise ApiError(404, f"indexer {indexer_id} not found")

    # Build the delta: only fields actually supplied are passed on, so the repo
    # leaves everything else untouched (a partial PUT). `implementation` is
    # intentionally not in this map — it cannot change on edit.
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.enable_rss is not None:
        updates["enable_rss"] = body.enable_rss
    if body.enable_auto is not None:
        updates["enable_auto"] = body.enable_auto
    if body.enable_interactive is not None:
        updates["enable_interactive"] = body.enable_interactive
    if body.settings is not None:
        stored = json.loads(existing.settings)
        merged = {**stored, **body.settings}  # incoming overrides; omitted kept
        try:
            updates["settings"] = validate_settings(existing.implementation, merged)
        except ValidationError as exc:
            raise _validation_error(exc) from exc

    row = await update_indexer(db, indexer_id, **updates)
    # get_indexer already proved the row exists; update runs in one writer txn.
    assert row is not None
    return IndexerResource.from_row(row, load_settings(row.implementation, row.settings))


@router.delete("/{indexer_id}", status_code=204)
async def delete_indexer_endpoint(indexer_id: int, request: Request) -> None:
    """Delete one indexer (FRG-IDX-001). Unknown id -> 404."""
    db = request.app.state.db
    if not await delete_indexer(db, indexer_id):
        raise ApiError(404, f"indexer {indexer_id} not found")
    return None


@router.post("/test", response_model=IndexerTestResponse)
async def indexer_test(body: IndexerTestRequest, request: Request) -> IndexerTestResponse:
    """Validate settings, then run a live caps probe (FRG-IDX-003, FRG-API-009).

    Returns success, or a field-precise failure in the uniform error shape.
    Nothing is persisted on failure (nothing is persisted at all — this is a
    pre-save test)."""
    try:
        get_implementation(body.implementation)
    except UnknownImplementationError as exc:
        raise ApiError(400, str(exc), field="implementation") from exc

    try:
        settings_model = validate_settings(body.implementation, body.settings)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    factory = _factory(request)
    async with NewznabClient(
        settings_model, factory, indexer_id=0
    ) as client:
        try:
            caps = await client.caps()
        except IndexerAuthError as exc:
            raise ApiError(400, str(exc), field="api_key") from exc
        except IndexerLimitError as exc:
            raise ApiError(400, str(exc), field="api_key") from exc
        except IndexerMalformedError as exc:
            raise ApiError(400, f"indexer returned an unreadable response: {exc}",
                           field="base_url") from exc
        except IndexerUnavailable as exc:
            raise ApiError(400, str(exc), field="base_url") from exc

    return IndexerTestResponse(
        success=True,
        message="indexer reachable; capabilities retrieved",
        categories=caps.categories,
        degraded=caps.degraded,
    )


def _validation_error(exc: ValidationError) -> ApiError:
    """Map a settings ``ValidationError`` to a field-precise 400 (uniform shape).

    Names the first offending settings field and folds every field message into
    the response message, so no invalid payload is ever silently accepted
    (FRG-IDX-001 scenario 2)."""
    parts = []
    first_field: str | None = None
    for err in exc.errors():
        field = "settings." + ".".join(str(p) for p in err.get("loc", ()))
        if first_field is None:
            first_field = field
        parts.append(f"{field}: {err.get('msg', 'invalid value')}")
    message = "indexer settings validation failed — " + "; ".join(parts)
    return ApiError(400, message, field=first_field)

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
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.repo import (
    delete_source,
    get_entitlement,
    get_source,
    list_entitlements,
    list_sources,
    load_source_settings,
    public_settings,
)
from foragerr.sources.review import (
    EntitlementActionError,
    add_entitlement,
    bulk_ignore,
    bulk_match,
    bulk_restore,
    ignore_entitlement,
    match_entitlement,
    restore_entitlement,
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


# --- entitlement review surface (FRG-SRC-004/007) ---------------------------


class EntitlementResource(BaseModel):
    """One reviewable entitlement as returned by the surface (FRG-SRC-004)."""

    id: int
    source_id: int
    machine_name: str
    human_name: str
    publisher: str | None
    classification: str
    review_status: str
    download_state: str | None
    download_error: str | None
    preferred_format: str | None
    file_size: int | None
    filename: str | None
    proposed_series_id: int | None
    matched_series_id: int | None
    proposed_match: dict[str, Any] | None

    @classmethod
    def from_row(cls, row: SourceEntitlementRow) -> "EntitlementResource":
        import json

        proposed = None
        if row.proposed_match_json:
            try:
                proposed = json.loads(row.proposed_match_json)
            except ValueError:
                proposed = None
        return cls(
            id=row.id,
            source_id=row.source_id,
            machine_name=row.machine_name,
            human_name=row.human_name,
            publisher=row.publisher,
            classification=row.classification,
            review_status=row.review_status,
            download_state=row.download_state,
            download_error=row.download_error,
            preferred_format=row.preferred_format,
            file_size=row.file_size,
            filename=row.filename,
            proposed_series_id=row.proposed_series_id,
            matched_series_id=row.matched_series_id,
            proposed_match=proposed,
        )


class EntitlementDetail(EntitlementResource):
    """An entitlement plus its collected-edition fill-sets (FRG-SRC-007)."""

    fill_sets: list[dict[str, Any]] = []


class MatchBody(BaseModel):
    series_id: int


class AddBody(BaseModel):
    cv_volume_id: int | None = None
    root_folder_id: int | None = None


class BulkBody(BaseModel):
    action: str
    entitlement_ids: list[int]
    series_id: int | None = None


@router.get("/{source_id}/entitlements", response_model=list[EntitlementResource])
async def list_entitlements_endpoint(
    source_id: int,
    request: Request,
    classification: str | None = None,
    review_status: str | None = None,
) -> list[EntitlementResource]:
    """List a source's entitlements, filterable by classification/review status."""
    db = request.app.state.db
    if await get_source(db, source_id) is None:
        raise ApiError(404, f"source {source_id} not found")
    rows = await list_entitlements(
        db, source_id, classification=classification, review_status=review_status
    )
    return [EntitlementResource.from_row(r) for r in rows]


@router.get("/entitlements/{entitlement_id}", response_model=EntitlementDetail)
async def entitlement_detail_endpoint(
    entitlement_id: int, request: Request
) -> EntitlementDetail:
    """One entitlement with its collected-edition fill-sets for the UI chips."""
    db = request.app.state.db
    row = await get_entitlement(db, entitlement_id)
    if row is None:
        raise ApiError(404, f"entitlement {entitlement_id} not found")
    fill_sets = await _fill_sets(db, row.matched_series_id)
    detail = EntitlementDetail(**EntitlementResource.from_row(row).model_dump())
    detail.fill_sets = fill_sets
    return detail


@router.post("/entitlements/{entitlement_id}/match", response_model=EntitlementResource)
async def match_entitlement_endpoint(
    entitlement_id: int, body: MatchBody, request: Request
) -> EntitlementResource:
    """Link an entitlement to an existing series and accept it (FRG-SRC-004)."""
    return await _run_action(
        request,
        lambda db, commands: match_entitlement(
            db, entitlement_id, series_id=body.series_id, commands=commands
        ),
    )


@router.post("/entitlements/{entitlement_id}/add", response_model=EntitlementResource)
async def add_entitlement_endpoint(
    entitlement_id: int, body: AddBody, request: Request
) -> EntitlementResource:
    """Add a brand-new series for an entitlement, then link it (FRG-SRC-004)."""
    db = request.app.state.db
    settings = request.app.state.settings
    commands = getattr(request.app.state, "commands", None)
    try:
        row = await add_entitlement(
            db,
            settings,
            entitlement_id,
            commands=commands,
            cv_volume_id=body.cv_volume_id,
            root_folder_id=body.root_folder_id,
        )
    except EntitlementActionError as exc:
        raise ApiError(exc.status, str(exc)) from exc
    return EntitlementResource.from_row(row)


@router.post(
    "/entitlements/{entitlement_id}/ignore", response_model=EntitlementResource
)
async def ignore_entitlement_endpoint(
    entitlement_id: int, request: Request
) -> EntitlementResource:
    """Ignore an entitlement (excluded from pending review) (FRG-SRC-004)."""
    return await _run_action(
        request, lambda db, commands: ignore_entitlement(db, entitlement_id)
    )


@router.post(
    "/entitlements/{entitlement_id}/restore", response_model=EntitlementResource
)
async def restore_entitlement_endpoint(
    entitlement_id: int, request: Request
) -> EntitlementResource:
    """Restore an ignored entitlement to ``new`` with a recomputed proposal."""
    return await _run_action(
        request, lambda db, commands: restore_entitlement(db, entitlement_id)
    )


@router.post("/entitlements/bulk")
async def bulk_entitlements_endpoint(
    body: BulkBody, request: Request
) -> dict[str, Any]:
    """Apply one review action to several entitlements (FRG-SRC-004)."""
    db = request.app.state.db
    commands = getattr(request.app.state, "commands", None)
    if body.action == "ignore":
        result = await bulk_ignore(db, body.entitlement_ids)
    elif body.action == "restore":
        result = await bulk_restore(db, body.entitlement_ids)
    elif body.action == "match":
        if body.series_id is None:
            raise ApiError(422, "match requires series_id", field="series_id")
        result = await bulk_match(
            db, body.entitlement_ids, series_id=body.series_id, commands=commands
        )
    else:
        raise ApiError(
            400,
            f"unknown bulk action {body.action!r}; expected ignore|restore|match",
            field="action",
        )
    return {"applied": result.applied, "skipped": result.skipped, "errors": result.errors}


async def _run_action(request: Request, action) -> EntitlementResource:
    """Run a single-entitlement action, mapping its error to an ApiError."""
    db = request.app.state.db
    commands = getattr(request.app.state, "commands", None)
    try:
        row = await action(db, commands)
    except EntitlementActionError as exc:
        raise ApiError(exc.status, str(exc)) from exc
    return EntitlementResource.from_row(row)


async def _fill_sets(db, series_id: int | None) -> list[dict[str, Any]]:
    """The matched series' collected-edition fill-sets as plain dicts."""
    if series_id is None:
        return []
    from foragerr.sources.reconcile import fill_sets_for_series

    async with db.read_session() as session:
        sets = await fill_sets_for_series(session, series_id=series_id)
    return [
        {
            "trade_issue_id": fs.trade_issue_id,
            "standalone": fs.standalone,
            "ranges": [
                {
                    "target_series_id": r.target_series_id,
                    "range_label": r.range_label,
                    "issues": [
                        {
                            "issue_id": i.issue_id,
                            "issue_number": i.issue_number,
                            "ownership": i.ownership,
                        }
                        for i in r.issues
                    ],
                }
                for r in fs.ranges
            ],
        }
        for fs in sets
    ]


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

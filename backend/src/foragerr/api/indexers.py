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
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, text

from foragerr.api.errors import ApiError
from foragerr.db.first_run import APP_STATE_TABLE
from foragerr.http import HttpClientFactory
from foragerr.keystore import (
    ENC_PREFIX,
    KeystoreDecryptError,
    top_level_secret_field_names,
)
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

logger = logging.getLogger("foragerr.api.indexers")

router = APIRouter(prefix="/indexer", tags=["indexer"])

#: ``triggered_by`` stamped on the FRG-SCHED-012 first-enabled-indexer sweep, so
#: job history distinguishes it from the scheduled tick and a manual run.
FIRST_INDEXER_TRIGGER = "first-indexer"

#: Persisted one-shot marker recording that this database's first-enabled-indexer
#: sweep has been claimed (FRG-SCHED-012). Lives in the existing ``app_state``
#: key/value table beside ``first_run_ddl_seed`` and ``creators_backfill_done``,
#: which is the established idiom for "this happens once per database, ever" —
#: no migration needed, and it survives every kind of row churn.
FIRST_INDEXER_MARKER_KEY = "first_indexer_sweep"
#: Marker value (presence of the row is what matters; the value is descriptive).
FIRST_INDEXER_MARKER_VALUE = "done"


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
    _reject_reserved_secret_prefix(body.implementation, body.settings)
    try:
        model = validate_settings(body.implementation, body.settings)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    db = request.app.state.db
    # Captured BEFORE the write (FRG-SCHED-012): the sweep is owed to the
    # zero-to-one TRANSITION. Reading it afterwards would make two simultaneous
    # first creates each see the other's row and conclude the deployment was
    # already acquiring — losing the one sweep a fresh install actually needs.
    had_enabled = await _had_enabled_indexer(db)
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
    await _maybe_first_indexer_sweep(
        request, enabled=row.enabled, had_enabled_indexer=had_enabled
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
        _reject_reserved_secret_prefix(existing.implementation, body.settings)
        stored = json.loads(existing.settings)
        merged = {**stored, **body.settings}  # incoming overrides; omitted kept
        try:
            updates["settings"] = validate_settings(existing.implementation, merged)
        except ValidationError as exc:
            raise _validation_error(exc) from exc

    # Both captured BEFORE the write: the sweep is owed to the disabled→enabled
    # TRANSITION on a deployment that had nothing enabled, not to the enabled
    # state. Re-saving the only enabled indexer (a name or priority edit) is not
    # a transition and must fire nothing.
    became_enabled = body.enabled is True and not existing.enabled
    had_enabled = await _had_enabled_indexer(db) if became_enabled else True

    row = await update_indexer(db, indexer_id, **updates)
    # get_indexer already proved the row exists; update runs in one writer txn.
    assert row is not None
    if became_enabled:
        await _maybe_first_indexer_sweep(
            request, enabled=row.enabled, had_enabled_indexer=had_enabled
        )
    return IndexerResource.from_row(row, _settings_for_response(row))


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


async def _had_enabled_indexer(db) -> bool:
    """Whether ANY indexer is enabled right now — read BEFORE the write.

    The "was this deployment already acquiring?" question. Taken before the
    row is created/enabled precisely so two simultaneous first creates both
    answer ``False`` (see :func:`_maybe_first_indexer_sweep`); read after the
    write, each would see the other's row and the deployment's very first sweep
    would be lost.
    """
    async with db.read_session() as session:
        found = await session.scalar(
            select(IndexerRow.id).where(IndexerRow.enabled.is_(True)).limit(1)
        )
    return found is not None


async def _claim_first_indexer_sweep(db) -> bool:
    """Atomically claim the ONE first-indexer sweep this database ever owes.

    A persisted marker row in ``app_state`` — the same one-shot idiom as
    ``first_run_ddl_seed`` and ``creators_backfill_done`` — is exact where a
    live row count cannot be: it distinguishes "the first indexer ever" from
    "the first indexer again after the last one was deleted" regardless of how
    the rows have churned.

    ``INSERT ... WHERE NOT EXISTS`` inside a single ``write_session`` makes the
    claim transactional: every write goes through the one writer lock under
    SQLite's ``BEGIN IMMEDIATE``, so of two concurrent claimants exactly one
    sees ``rowcount == 1`` and owns the sweep. Returns True for the winner only.
    """
    async with db.write_session() as session:
        result = await session.execute(
            text(
                f"INSERT INTO {APP_STATE_TABLE} (key, value) "
                "SELECT :key, :value "
                f"WHERE NOT EXISTS (SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key)"
            ),
            {"key": FIRST_INDEXER_MARKER_KEY, "value": FIRST_INDEXER_MARKER_VALUE},
        )
        return (result.rowcount or 0) == 1


async def _maybe_first_indexer_sweep(
    request: Request, *, enabled: bool, had_enabled_indexer: bool
) -> None:
    """Enqueue ONE backlog search when the first enabled indexer appears
    (FRG-SCHED-012).

    The fresh-install order is series first, indexers second, so a new install
    would otherwise download nothing until the six-hour backlog tick. Three
    conditions, in this order:

    1. this write left an indexer ENABLED (a disabled row acquires nothing);
    2. the deployment had NO enabled indexer beforehand — the zero-to-one
       transition, read before the write so concurrent first creates agree;
    3. the persisted one-shot marker is still unclaimed, and this call wins it.

    (3) is what makes the trigger correct rather than merely plausible: an
    inference from the live enabled-count could be reopened by later deletes,
    disables, or re-enables, and could miss two concurrent first creates
    entirely. The marker gives one sweep per database, ever, no matter how the
    rows churn.

    Everything downstream is unchanged — the same ``backlog-search`` command the
    scheduler runs, bounded by its own wanted walk with the usual politeness
    delay, and collapsed by CommandService's payload dedup (FRG-SCHED-003) if
    one is already queued or running.

    Best-effort by construction: configuring an indexer must succeed even if the
    sweep cannot be queued, so a missing command service or an enqueue failure
    is logged, never surfaced — the scheduled tick remains the backstop. The
    marker is claimed BEFORE the enqueue deliberately: a failed enqueue must not
    leave the claim open for a later save to re-fire, since the tick already
    covers it.
    """
    if not enabled or had_enabled_indexer:
        return
    commands = getattr(request.app.state, "commands", None)
    if commands is None:  # pragma: no cover - always wired by create_app
        return
    if not await _claim_first_indexer_sweep(request.app.state.db):
        return  # another request (or an earlier one) already owned this sweep
    try:
        await commands.enqueue("backlog-search", triggered_by=FIRST_INDEXER_TRIGGER)
    except Exception:  # noqa: BLE001 - the indexer is saved; the tick backstops
        logger.warning(
            "first-indexer sweep could not be enqueued; the scheduled "
            "backlog search still covers it",
            exc_info=True,
        )


def _reject_reserved_secret_prefix(implementation: str, supplied: dict[str, Any]) -> None:
    """Reject a user-supplied secret whose value begins with the reserved
    ``enc:v1:`` framing prefix (FRG-AUTH-008).

    Such a value would be stored as PLAINTEXT — ``encrypt_secret`` treats an
    already-``enc:v1:`` string as ciphertext and passes it through — and then fail
    to decrypt on load, silently disabling the credential. Only the caller-supplied
    secret fields are checked, so the stored-ciphertext merge path (an omitted
    secret that round-trips as stored ciphertext) is unaffected."""
    model_cls = get_implementation(implementation).settings_model
    for name in top_level_secret_field_names(model_cls):
        value = supplied.get(name)
        if isinstance(value, str) and value.startswith(ENC_PREFIX):
            raise ApiError(
                422,
                f"settings.{name}: value must not begin with the reserved "
                f"'{ENC_PREFIX}' prefix (it is reserved for at-rest secret framing)",
                field=f"settings.{name}",
            )


def _settings_for_response(row: IndexerRow) -> BaseModel:
    """Load a persisted row's settings for the response, resiliently.

    A successful write can leave the row carrying a secret the CURRENT key cannot
    decrypt (wrong-key/corrupt); loading it for the response would otherwise 500.
    Fall back to validating the raw (still-encrypted) payload so the endpoint keeps
    its 200 — ``public_settings`` drops secret fields, so no ciphertext leaks
    (FRG-AUTH-012 fail-soft)."""
    try:
        return load_settings(row.implementation, row.settings)
    except KeystoreDecryptError:
        return validate_settings(row.implementation, json.loads(row.settings))


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

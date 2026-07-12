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

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import ApiError
from foragerr.keystore import (
    ENC_PREFIX,
    KeystoreDecryptError,
    top_level_secret_field_names,
)
from foragerr.downloads import make_download_factory
from foragerr.downloads.errors import DownloadClientError
from foragerr.downloads.models import DownloadClientRow
from foragerr.downloads.registry import (
    ClientBuildContext,
    UnknownImplementationError,
    get_implementation,
    implementations,
    validate_settings,
)
from foragerr.downloads.repo import (
    create_download_client,
    delete_download_client,
    get_download_client,
    load_download_clients,
    load_settings,
    public_settings,
    update_download_client,
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


class DownloadClientResource(BaseModel):
    """A configured download client as returned by the CRUD surface (FRG-DL-002).

    Field names mirror the ``DownloadClientRow`` columns (the provider-resource
    convention shared with the frontend). ``settings`` is the PUBLIC settings
    view — secret values (e.g. ``api_key``) are dropped, never echoed
    (write-only, FRG-API-009)."""

    id: int
    name: str
    implementation: str
    protocol: str
    enabled: bool
    priority: int
    remove_completed_downloads: bool
    settings: dict[str, Any]

    @classmethod
    def from_row(
        cls, row: DownloadClientRow, settings: BaseModel
    ) -> "DownloadClientResource":
        return cls(
            id=row.id,
            name=row.name,
            implementation=row.implementation,
            protocol=row.protocol,
            enabled=row.enabled,
            priority=row.priority,
            remove_completed_downloads=row.remove_completed_downloads,
            settings=public_settings(settings),
        )


class DownloadClientCreate(BaseModel):
    """Request body for ``POST /downloadclient`` — row flags plus the
    implementation settings dict (which must include any required secret)."""

    name: str
    implementation: str
    settings: dict[str, Any]
    enabled: bool = True
    remove_completed_downloads: bool = True
    priority: int = 25


class DownloadClientUpdate(BaseModel):
    """Request body for ``PUT /downloadclient/{id}`` — every field optional (a
    partial update). An omitted ``settings`` leaves stored settings untouched; a
    supplied ``settings`` that omits a secret key keeps the stored secret
    (write-only, FRG-API-009). ``implementation`` cannot change and is ignored
    if sent."""

    name: str | None = None
    implementation: str | None = None
    settings: dict[str, Any] | None = None
    enabled: bool | None = None
    remove_completed_downloads: bool | None = None
    priority: int | None = None


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


@router.get("", response_model=list[DownloadClientResource])
async def list_download_clients_endpoint(
    request: Request,
) -> list[DownloadClientResource]:
    """Every configured download client with its PUBLIC settings (FRG-DL-002).

    Secret values are dropped from ``settings`` (write-only, FRG-API-009); a row
    whose stored settings can't load is skipped (isolated, FRG-NFR-010)."""
    db = request.app.state.db
    listing = await load_download_clients(db)
    records: list[DownloadClientResource] = []
    for row in listing.healthy:
        model = load_settings(row.implementation, row.settings)
        records.append(DownloadClientResource.from_row(row, model))
    return records


@router.post("", status_code=201, response_model=DownloadClientResource)
async def create_download_client_endpoint(
    body: DownloadClientCreate, request: Request
) -> DownloadClientResource:
    """Validate + persist one download client (FRG-DL-002). Invalid settings
    yield a field-precise 400 and persist nothing; secrets are never echoed."""
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
    row = await create_download_client(
        db,
        name=body.name,
        implementation=body.implementation,
        settings=model,
        priority=body.priority,
        enabled=body.enabled,
        remove_completed_downloads=body.remove_completed_downloads,
    )
    return DownloadClientResource.from_row(row, model)


@router.put("/{client_id}", response_model=DownloadClientResource)
async def update_download_client_endpoint(
    client_id: int, body: DownloadClientUpdate, request: Request
) -> DownloadClientResource:
    """Partially update one download client (FRG-DL-002).

    A supplied ``settings`` is MERGED over the stored values before validation,
    so an omitted secret key keeps the persisted secret (write-only,
    FRG-API-009). Unknown id -> 404; invalid merged settings -> 400."""
    db = request.app.state.db
    existing = await get_download_client(db, client_id)
    if existing is None:
        raise ApiError(404, f"download client {client_id} not found")

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.remove_completed_downloads is not None:
        updates["remove_completed_downloads"] = body.remove_completed_downloads
    if body.settings is not None:
        _reject_reserved_secret_prefix(existing.implementation, body.settings)
        stored = json.loads(existing.settings)
        merged = {**stored, **body.settings}  # incoming overrides; omitted kept
        try:
            updates["settings"] = validate_settings(existing.implementation, merged)
        except ValidationError as exc:
            raise _validation_error(exc) from exc

    row = await update_download_client(db, client_id, **updates)
    assert row is not None  # existence proven above; single-writer txn
    return DownloadClientResource.from_row(row, _settings_for_response(row))


@router.delete("/{client_id}", status_code=204)
async def delete_download_client_endpoint(
    client_id: int, request: Request
) -> None:
    """Delete one download client (FRG-DL-002). Unknown id -> 404."""
    db = request.app.state.db
    if not await delete_download_client(db, client_id):
        raise ApiError(404, f"download client {client_id} not found")
    return None


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


def _settings_for_response(row: DownloadClientRow) -> BaseModel:
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

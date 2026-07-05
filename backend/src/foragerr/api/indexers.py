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

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import ApiError
from foragerr.http import HttpClientFactory
from foragerr.indexers.caps import parse_caps
from foragerr.indexers.errors import (
    IndexerAuthError,
    IndexerLimitError,
    IndexerMalformedError,
    IndexerUnavailable,
)
from foragerr.indexers.newznab import NewznabClient
from foragerr.indexers.registry import (
    UnknownImplementationError,
    get_implementation,
    implementations,
    validate_settings,
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


def _factory(request: Request) -> HttpClientFactory:
    override = getattr(request.app.state, "http_factory", None)
    if override is not None:
        return override
    return HttpClientFactory(request.app.state.settings)


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

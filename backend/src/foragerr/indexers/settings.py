"""Per-implementation indexer settings contracts (FRG-IDX-001).

Each indexer implementation registers ONE Pydantic settings model. It is the
single source of truth for three things:

- **validation** — a settings payload is validated against it at save time,
  yielding field-level errors and persisting no partial row
  (FRG-IDX-001 scenario 2);
- **the dynamic settings schema** — :mod:`foragerr.indexers.schema` derives the
  renderable ``fields[]`` metadata from it, so a new implementation needs zero
  frontend work (FRG-IDX-003 / FRG-API-009);
- **secret handling** — API keys are :class:`~pydantic.SecretStr`, so they are
  write-only in GET responses and register for log redaction at row load
  (FRG-IDX-001 scenario 3).

Field presentation metadata (label/help/select options/advanced flag) rides in
each field's ``json_schema_extra`` so the contract and the rendered form can
never drift apart.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

#: The default Newznab category for comics — 7030 (Books/Comics). Multi-category
#: per indexer is supported (Mylar parity); this is only the default.
COMICS_CATEGORY = 7030


class NewznabSettings(BaseModel):
    """Settings contract for the ``newznab`` implementation (the only M1 one)."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(
        ...,
        json_schema_extra={
            "label": "URL",
            "help": "Base URL of the Newznab indexer, e.g. https://api.dognzb.cr",
            "advanced": False,
        },
    )
    api_key: SecretStr = Field(
        ...,
        json_schema_extra={
            "label": "API Key",
            "help": "Your account's Newznab API key.",
            "advanced": False,
        },
    )
    categories: list[int] = Field(
        default_factory=lambda: [COMICS_CATEGORY],
        json_schema_extra={
            "label": "Categories",
            "help": "Newznab categories to search; defaults to 7030 (Books/Comics).",
            "advanced": False,
            # Baseline options; refined from the live caps probe at test time.
            "selectOptions": [
                {"value": COMICS_CATEGORY, "name": "Books/Comics (7030)"},
            ],
        },
    )
    additional_parameters: str | None = Field(
        default=None,
        json_schema_extra={
            "label": "Additional Parameters",
            "help": "Extra query parameters appended verbatim, e.g. &extended=1.",
            "advanced": True,
        },
    )

    @field_validator("base_url")
    @classmethod
    def _valid_http_url(cls, value: str) -> str:
        value = value.strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("must be an http(s) URL")
        # Reject a scheme-only value ("https://") with no host.
        remainder = value.split("://", 1)[1]
        if not remainder or remainder.startswith("/"):
            raise ValueError("must include a host")
        return value.rstrip("/")

    @field_validator("categories")
    @classmethod
    def _non_empty_categories(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("at least one category is required")
        if any(c <= 0 for c in value):
            raise ValueError("categories must be positive integers")
        return value

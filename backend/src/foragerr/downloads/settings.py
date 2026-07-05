"""Per-implementation download-client settings contracts (FRG-DL-002/003).

Mirrors :mod:`foragerr.indexers.settings`: each download-client implementation
registers ONE Pydantic settings model that is the single source of truth for
validation, the dynamic settings-form schema (reused verbatim by
:mod:`foragerr.indexers.schema`), and secret handling (API keys are
``SecretStr`` — write-only in GET responses, redaction-registered at row load).
Presentation metadata rides in each field's ``json_schema_extra`` so the
contract and the rendered form cannot drift.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

#: SABnzbd's default download category for comics (created in SAB by the
#: operator); every foragerr grab is filed under this category and polling is
#: filtered to it (FRG-DL-003/004).
DEFAULT_SAB_CATEGORY = "comics"

#: SABnzbd priority sentinel meaning "use the category's default priority".
SAB_PRIORITY_DEFAULT = -100


class SabnzbdSettings(BaseModel):
    """Settings contract for the ``sabnzbd`` implementation (FRG-DL-003)."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(
        ...,
        json_schema_extra={
            "label": "URL",
            "help": "Base URL of the SABnzbd host, e.g. http://192.168.1.10:8080",
            "advanced": False,
        },
    )
    api_key: SecretStr = Field(
        ...,
        json_schema_extra={
            "label": "API Key",
            "help": "SABnzbd API key (Config → General → API Key).",
            "advanced": False,
        },
    )
    category: str = Field(
        default=DEFAULT_SAB_CATEGORY,
        json_schema_extra={
            "label": "Category",
            "help": "SABnzbd category grabs are filed under; polling is "
            "filtered to it. Defaults to 'comics'.",
            "advanced": False,
        },
    )
    priority: int = Field(
        default=SAB_PRIORITY_DEFAULT,
        json_schema_extra={
            "label": "Priority",
            "help": "SABnzbd priority for added downloads: -100 Default, "
            "-1 Low, 0 Normal, 1 High, 2 Force.",
            "advanced": True,
            "selectOptions": [
                {"value": -100, "name": "Default"},
                {"value": -1, "name": "Low"},
                {"value": 0, "name": "Normal"},
                {"value": 1, "name": "High"},
                {"value": 2, "name": "Force"},
            ],
        },
    )

    @field_validator("base_url")
    @classmethod
    def _valid_http_url(cls, value: str) -> str:
        value = value.strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("must be an http(s) URL")
        remainder = value.split("://", 1)[1]
        if not remainder or remainder.startswith("/"):
            raise ValueError("must include a host")
        return value.rstrip("/")

    @field_validator("category")
    @classmethod
    def _non_empty_category(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("category must not be empty")
        return value


class BuiltinDdlSettings(BaseModel):
    """Settings contract for the built-in ``ddl`` client (FRG-DDL-004/006).

    Defined here in the foundation area so the download-client provider table,
    schema, and resolver treat DDL as "just another client" from day one; the
    ddl worktree area wires these fields into GetComics link selection and
    politeness (FRG-DDL-004/006) and supplies the concrete client factory.
    """

    model_config = ConfigDict(extra="forbid")

    host_priority: str = Field(
        default="main,mirror,pixeldrain,mediafire,mega",
        json_schema_extra={
            "label": "Host Priority",
            "help": "Comma-separated download-host preference order "
            "(FRG-DDL-004). Earlier hosts are tried first.",
            "advanced": True,
        },
    )
    prefer_upscaled: bool = Field(
        default=True,
        json_schema_extra={
            "label": "Prefer Upscaled",
            "help": "Prefer HD-Upscaled quality links when a post offers "
            "several quality tiers (FRG-DDL-004).",
            "advanced": True,
        },
    )
    min_interval_seconds: int = Field(
        default=15,
        ge=1,
        json_schema_extra={
            "label": "Minimum Fetch Interval (s)",
            "help": "Minimum seconds between GetComics page fetches, plus "
            "jitter (FRG-DDL-006). Clamped to a safe floor.",
            "advanced": True,
        },
    )


__all__ = [
    "DEFAULT_SAB_CATEGORY",
    "SAB_PRIORITY_DEFAULT",
    "BuiltinDdlSettings",
    "SabnzbdSettings",
]

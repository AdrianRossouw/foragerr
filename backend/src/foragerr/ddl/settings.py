"""Settings contract for the GetComics *search provider* (FRG-DDL-002/006).

This is the indexer-side settings model (the GetComics provider is registered as
a change-4 search provider — an ``indexers`` row with protocol ``ddl``). It is
distinct from :class:`foragerr.downloads.settings.BuiltinDdlSettings`, which
configures the *download client* (host priority / quality / interval on the
``download_clients`` row). Splitting them mirrors the architecture: one row
searches, the other downloads.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The one hardcoded upstream (mylar-ddl §1.1). A field so a future mirror is
#: config, not code — but the default is the canonical site.
DEFAULT_GETCOMICS_URL = "https://getcomics.org"

#: Politeness floor for search-page fetches (FRG-DDL-006). The configured
#: interval is clamped UP to this so it can never be set below a polite floor.
MIN_INTERVAL_FLOOR_SECONDS = 15

#: Hard ceiling on how many "older posts" pages the ladder walks per query
#: (FRG-DDL-002 — Mylar's uncapped pagination is the anti-pattern, §3.7).
DEFAULT_MAX_PAGES = 3


class GetComicsSettings(BaseModel):
    """Settings for the ``getcomics`` search-provider implementation."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(
        default=DEFAULT_GETCOMICS_URL,
        json_schema_extra={
            "label": "Site URL",
            "help": "GetComics base URL. The default is the canonical site; "
            "only change it for a known mirror.",
            "advanced": True,
        },
    )
    min_interval_seconds: int = Field(
        default=MIN_INTERVAL_FLOOR_SECONDS,
        ge=1,
        json_schema_extra={
            "label": "Minimum Fetch Interval (s)",
            "help": "Minimum seconds between search-page fetches, plus jitter "
            "(FRG-DDL-006). Clamped up to a polite floor.",
            "advanced": True,
        },
    )
    max_pages: int = Field(
        default=DEFAULT_MAX_PAGES,
        ge=1,
        le=20,
        json_schema_extra={
            "label": "Max Pages per Query",
            "help": "How many result pages the 'older posts' pagination walks "
            "per query tier before giving up (FRG-DDL-002).",
            "advanced": True,
        },
    )

    @field_validator("base_url")
    @classmethod
    def _valid_https_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("must be an https URL")
        remainder = value.split("://", 1)[1]
        if not remainder or remainder.startswith("/"):
            raise ValueError("must include a host")
        return value

    def effective_min_interval(self) -> int:
        """The politeness interval, clamped up to the floor (FRG-DDL-006)."""
        return max(self.min_interval_seconds, MIN_INTERVAL_FLOOR_SECONDS)


__all__ = [
    "DEFAULT_GETCOMICS_URL",
    "DEFAULT_MAX_PAGES",
    "MIN_INTERVAL_FLOOR_SECONDS",
    "GetComicsSettings",
]

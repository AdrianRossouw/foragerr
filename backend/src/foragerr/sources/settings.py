"""Per-store-type source settings contracts (FRG-SRC-002).

Each store type registers ONE Pydantic settings model, the single source of
truth for validation, the renderable settings schema, and secret handling —
identical to the indexer settings pattern (:mod:`foragerr.indexers.settings`).

The Humble cookie is a TOP-LEVEL :class:`~pydantic.SecretStr`, so the shared
keystore helpers encrypt it at rest, drop it from GET responses (write-only),
and register it for log redaction with zero source-specific code
(FRG-SRC-002 / FRG-AUTH-008). Keeping it top-level is load-bearing: a nested
secret would be stored as PLAINTEXT (the top-level-only keystore detection),
which the ``test_no_registered_settings_model_hides_a_nested_secret`` tripwire
guards against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class HumbleSettings(BaseModel):
    """Settings contract for the ``humble`` store type (FRG-SRC-002)."""

    model_config = ConfigDict(extra="forbid")

    session_cookie: SecretStr = Field(
        ...,
        json_schema_extra={
            "label": "Session cookie",
            "help": (
                "The '_simpleauth_sess' cookie from your logged-in Humble "
                "Bundle browser session. foragerr never stores your password "
                "and never logs in for you."
            ),
            "advanced": False,
        },
    )

    @field_validator("session_cookie")
    @classmethod
    def _non_empty_cookie(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("the session cookie must not be empty")
        return value

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

#: Bounds on the operator's publisher rule list (FRG-SRC-012) — a settings blob
#: is stored as one JSON column, so the list is capped rather than unbounded.
MAX_PUBLISHER_RULES = 200
MAX_PUBLISHER_RULE_LENGTH = 200


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

    publisher_rules: list[str] = Field(
        default_factory=list,
        json_schema_extra={
            "label": "Non-comic publishers",
            "help": (
                "Publishers whose items are always classified as Other, "
                "whatever their file formats — the RPG-sourcebook escape "
                "hatch. Ships empty; a suggested starter list is offered in "
                "the review screen and only applied when you accept it. "
                "Changing this reclassifies unreviewed items on the next "
                "sync; items you have already matched or ignored never move."
            ),
            "advanced": True,
        },
    )

    @field_validator("session_cookie")
    @classmethod
    def _non_empty_cookie(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("the session cookie must not be empty")
        return value

    @field_validator("publisher_rules")
    @classmethod
    def _clean_publisher_rules(cls, value: list[str]) -> list[str]:
        """Trim, drop blanks, de-duplicate, and bound the list — the rule list
        is operator-typed free text (FRG-SRC-012).

        Order is preserved so the settings screen renders what was entered;
        de-duplication keeps the first spelling of a repeated publisher.

        **De-duplication uses the same fold the classifier matches on**
        (:func:`~foragerr.parser.normalize.matching_key`, FRG-IMP-005). It used
        to use ``str.casefold``, which is a STRICTLY narrower equivalence than
        the classifier's: ``"Modiphius Entertainment"`` and ``"Modiphius
        Entertainment."`` survived as two stored rules that then matched the
        same publisher, so the stored list disagreed with its own effect — the
        settings screen showed a duplicate the operator could not distinguish,
        and removing one of them changed nothing. One fold, one rule identity.
        (A rule that folds to nothing — punctuation only — keeps its casefolded
        spelling as the dedupe key, since it can never match a publisher and
        must not collapse with every other such entry.)
        """
        from foragerr.parser.normalize import matching_key

        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            rule = raw.strip()
            if not rule:
                continue
            if len(rule) > MAX_PUBLISHER_RULE_LENGTH:
                raise ValueError(
                    "a publisher rule must be at most "
                    f"{MAX_PUBLISHER_RULE_LENGTH} characters"
                )
            key = matching_key(rule) or rule.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(rule)
        if len(cleaned) > MAX_PUBLISHER_RULES:
            raise ValueError(
                f"at most {MAX_PUBLISHER_RULES} publisher rules are supported"
            )
        return cleaned

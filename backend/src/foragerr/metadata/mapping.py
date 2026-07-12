"""Pure ComicVine-JSON -> typed-record mapping (FRG-META-005, FRG-META-006).

No I/O; every function takes a decoded JSON ``dict`` and returns a frozen
record from :mod:`foragerr.metadata.models`. Rules enforced here:

* absent fields map to ``None`` — never a sentinel string;
* issue numbers are preserved verbatim as ``str`` (no float coercion);
* an issue's actual returned element count wins over ``count_of_issues``;
* every human-readable string is run through
  :func:`foragerr.metadata.sanitize.sanitize_cv_text` at this ingest point;
* an unnumbered issue is surfaced (mapped with ``issue_number=None``) and logged
  exactly once, never silently dropped.
"""

from __future__ import annotations

import logging
from typing import Any

from foragerr.metadata.credits import map_person_credits
from foragerr.metadata.models import IssueRecord, IssueRef, SeriesRecord, VolumeStub
from foragerr.metadata.sanitize import sanitize_cv_text

logger = logging.getLogger("foragerr.metadata.mapping")


def _text(value: Any) -> str | None:
    """Sanitize an untrusted CV string to plain text or ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return sanitize_cv_text(value)


def _int(value: Any) -> int | None:
    """Coerce a CV int-ish value (int or numeric string) to ``int`` or ``None``.

    Non-numeric or empty values map to ``None`` rather than a sentinel.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _year(value: Any) -> int | None:
    """CV ``start_year`` is a string like ``"1963"``; keep only a real year."""
    year = _int(value)
    # Guard the ``'0000'`` sentinel family: a zero/negative year is not real.
    return year if year and year > 0 else None


def _date(value: Any) -> str | None:
    """Keep a CV date string verbatim, or ``None`` — never a date sentinel."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.startswith("0000"):
        return None
    return stripped


def _image_url(value: Any) -> str | None:
    """Pull the best cover URL from a CV ``image`` object."""
    if not isinstance(value, dict):
        return None
    for key in ("original_url", "super_url", "medium_url", "small_url"):
        url = value.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _nested_name(value: Any) -> str | None:
    """Sanitized ``name`` from a nested CV object (publisher, etc.)."""
    if isinstance(value, dict):
        return _text(value.get("name"))
    return None


def _aliases(value: Any) -> tuple[str, ...]:
    """CV ``aliases`` is a newline-separated string; split + sanitize."""
    if not isinstance(value, str):
        return ()
    out: list[str] = []
    for line in value.splitlines():
        cleaned = sanitize_cv_text(line)
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def map_issue_ref(payload: Any) -> IssueRef | None:
    """Map a nested issue reference (e.g. a volume's ``first_issue``)."""
    if not isinstance(payload, dict):
        return None
    return IssueRef(
        cv_issue_id=_int(payload.get("id")),
        issue_number=_issue_number(payload.get("issue_number")),
        name=_text(payload.get("name")),
    )


def _issue_number(value: Any) -> str | None:
    """Preserve a CV issue number verbatim as text, or ``None`` if absent.

    Never coerced to a number: ``"1.5"``, ``"1.MU"`` and ``"½"`` round-trip
    unchanged. Whitespace is trimmed but the token itself is untouched. HTML
    stripping is deliberately NOT applied — an issue number is a short token,
    not prose, and sanitizing could mangle a legitimate value.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped or None


def map_issue(payload: dict[str, Any]) -> IssueRecord:
    """Map one CV issue object to an :class:`IssueRecord` (FRG-META-006)."""
    cv_issue_id = _int(payload.get("id")) or 0
    number = _issue_number(payload.get("issue_number"))
    if number is None:
        logger.warning(
            "comicvine issue %s has no issue number; surfaced unmonitored",
            cv_issue_id,
        )
    return IssueRecord(
        cv_issue_id=cv_issue_id,
        issue_number=number,
        title=_text(payload.get("name")),
        cover_date=_date(payload.get("cover_date")),
        store_date=_date(payload.get("store_date")),
        image_url=_image_url(payload.get("image")),
        credits=map_person_credits(payload.get("person_credits")),
    )


def map_volume_stubs(value: Any) -> tuple[VolumeStub, ...]:
    """Map an untrusted CV ``volume_credits`` value to typed volume stubs
    (FRG-CRTR-005).

    Total by contract (mirrors :func:`map_person_credits`): an absent, empty, or
    malformed value maps to ``()`` and never raises. Each stub carries only a cv
    volume id and a sanitized name; entries with no usable positive id are
    dropped, and a volume id already seen is collapsed so the same volume is
    listed once. The full publisher/start_year/issue-count fields are NOT present
    on a stub — they come from a later batched :func:`map_volume` hydration.
    """
    if not isinstance(value, list):
        return ()
    out: list[VolumeStub] = []
    seen: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        vid = _int(raw.get("id"))
        if not vid or vid <= 0 or vid in seen:
            continue
        seen.add(vid)
        out.append(VolumeStub(cv_volume_id=vid, name=_text(raw.get("name"))))
    return tuple(out)


def map_volume(payload: dict[str, Any]) -> SeriesRecord:
    """Map one CV volume object to a :class:`SeriesRecord` (FRG-META-005).

    When the volume carries an ``issues`` array, its element count wins over
    the advertised ``count_of_issues``; otherwise the advertised count is used.
    """
    issues = payload.get("issues")
    if isinstance(issues, list):
        count = len(issues)
    else:
        count = _int(payload.get("count_of_issues"))
    return SeriesRecord(
        cv_volume_id=_int(payload.get("id")) or 0,
        name=_text(payload.get("name")),
        publisher=_nested_name(payload.get("publisher")),
        imprint=_nested_name(payload.get("imprint")),
        start_year=_year(payload.get("start_year")),
        count_of_issues=count,
        aliases=_aliases(payload.get("aliases")),
        description=_text(payload.get("description")),
        site_url=(
            payload.get("site_detail_url").strip()
            if isinstance(payload.get("site_detail_url"), str)
            and payload.get("site_detail_url").strip()
            else None
        ),
        first_issue=map_issue_ref(payload.get("first_issue")),
        image_url=_image_url(payload.get("image")),
        date_last_updated=_text(payload.get("date_last_updated")),
    )

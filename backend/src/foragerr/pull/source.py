"""The hardened external weekly-pull fetch client (FRG-PULL-002).

This is the change's one new *outbound integration + untrusted-content ingress*
(FRG-PROC-006), so the whole module is written defensively:

* **Egress.** Every request is issued over the shared outbound factory's
  ``external`` profile (:class:`foragerr.http.HttpClientFactory`, FRG-SEC-001) —
  no module here ever touches ``httpx`` directly (the static-guard test forbids
  it). A source URL pointed at a loopback/private/link-local host is therefore
  refused *per hop* before any connection is made (closing the pull-source arm
  of RISK-025), and every request carries the factory's mandatory timeouts,
  TLS-verify-always, bounded redirect walk, and response byte cap (FRG-NFR-006).
* **Untrusted JSON.** The response body is treated as hostile (FRG-NFR-012): it
  is fetched under a byte cap, parsed with the stdlib :mod:`json`, and every
  field is bounded/sanitised before it can reach a log line or storage —
  control characters and forged CR/LF are stripped so a malicious ``series``
  value can never inject a log record. A malformed/oversized body degrades to a
  source-outage outcome; a single malformed *entry* is skipped (bounded log),
  never crashing the run. An entry-count cap bounds a hostile "millions of rows"
  payload.
* **Error mapping.** The source's documented non-standard HTTP codes are mapped
  explicitly (mirroring the house convention of typed, transport-free errors,
  cf. :mod:`foragerr.metadata.comicvine`): **619** bad-date → skip *only* that
  week; **522** backend-down and **666** client-update-required (and any
  transport/egress/oversize failure) → a source *outage* that leaves the
  previously-stored week intact and marks the pull source **degraded** in the
  health surface (FRG-NFR-011 / FRG-API-014) via the shared provider back-off
  ladder (:class:`foragerr.providers.backoff.ProviderBackoff`,
  ``PROVIDER_PULL``) — never a silent discard of good data.

Ownership seam (m3-pull-backbone, area B): this module parses source JSON into
area A's DB-free :class:`foragerr.pull.models.ParsedPullEntry` and reports a
per-run outcome. It does **not** compute which weeks to fetch, does **not**
store anything, and does **not** call ``entry_key``/the repo — the ``pull-refresh``
command (area D) drives the storage using this client's :class:`PullFetchOutcome`.
The configurable source URL is a config key owned by area D
(``pull_source_url``); this client takes it as an explicit constructor argument
so area B carries no config surface of its own.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

from foragerr.db.migrations import app_version
from foragerr.http import EgressPolicyError, HttpClientFactory, OutboundHttpError
from foragerr.providers.backoff import (
    PROVIDER_PULL,
    PULL_PROVIDER_ID,
    ProviderBackoff,
)
from foragerr.pull.models import ParsedPullEntry

logger = logging.getLogger("foragerr.pull.source")

#: The source's documented non-standard HTTP status codes (locg.py in the Mylar
#: reference): a *bad-date* request, a *backend-down* signal, and a
#: *client-update-required* signal. They are real HTTP response codes returned
#: by the walksoftly service, not JSON envelope fields.
CODE_BAD_DATE = 619
CODE_BACKEND_DOWN = 522
CODE_UPDATE_REQUIRED = 666

#: Byte cap on a single week's pull JSON (lower than the factory's 25 MiB
#: ceiling). A real week is a few hundred entries / tens of KiB; 4 MiB is ample
#: headroom while still refusing a hostile multi-megabyte body outright.
PULL_JSON_MAX_BYTES = 4_000_000

#: Hard cap on entries parsed from one week — bounds a hostile "millions of
#: rows" payload even within the byte cap. Extra rows are dropped with one
#: bounded warning, never accumulated.
MAX_PULL_ENTRIES = 10_000

#: Length cap applied to every source-supplied string field before it is stored
#: or logged (FRG-NFR-012 "truncated to the documented length cap"). A comic
#: series name / publisher / issue token is short; anything longer is hostile
#: or junk and is truncated.
MAX_FIELD_LENGTH = 300

#: Upper bound on an accepted ComicVine id — ids well past ComicVine's real
#: id space are treated as junk and dropped to ``None`` (they are *candidates*
#: only anyway, FRG-PULL-002 Notes). Keeps a hostile huge integer out of the
#: typed ``StrictInteger`` column.
_MAX_CV_ID = 2_000_000_000

# ANSI/VT escape sequences and C0/DEL control characters (incl. CR/LF) —
# stripped so a source string can never forge a log line or carry control
# codes into storage (mirrors metadata.sanitize's RISK-014 posture).
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _user_agent() -> str:
    """The honest ``foragerr/<version>`` User-Agent (resolved once)."""
    return f"foragerr/{app_version()}"


# --- typed errors (transport-free, house convention) ------------------------


class PullSourceError(Exception):
    """Base class for every pull-source client failure."""


class PullBadDate(PullSourceError):
    """The source reported a bad/invalid date for a requested week (HTTP 619).

    Only the affected week is skipped; the rest of the run proceeds and stored
    data for other weeks is untouched (FRG-PULL-002).
    """


class PullSourceOutage(PullSourceError):
    """The source could not deliver usable data for a request — a backend-down
    (522) / update-required (666) signal, an egress refusal, an oversize or
    malformed body, or a transport/timeout failure.

    Treated as a *source outage*: the previously-stored week is left intact and
    the pull source is marked degraded in health, rather than discarding good
    data or crashing the run (FRG-PULL-002).

    ``reason`` is a short machine-readable cause for the health/back-off record;
    ``fast_forward`` asks the back-off ladder to jump rather than step one rung
    (an update-required signal will not recover by retrying in a minute).
    """

    def __init__(
        self, message: str, *, reason: str, fast_forward: bool = False
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.fast_forward = fast_forward


# --- per-run result shapes (area D consumes these) --------------------------


@dataclass(frozen=True, slots=True)
class PullWeekResult:
    """One successfully fetched + parsed week — the set area D replaces-on-store."""

    week: int
    year: int
    entries: tuple[ParsedPullEntry, ...]


@dataclass(frozen=True, slots=True)
class PullFetchOutcome:
    """The result of one fetch run over one or more requested weeks.

    ``weeks`` are the fetched-and-parsed weeks area D should replace-on-store;
    when ``degraded`` is ``True`` this is empty by construction so a run that hit
    an outage never asks area D to overwrite a stored week with partial/empty
    data (FRG-PULL-002 "leaves the previously stored week intact"). ``skipped``
    holds the ``(week, year)`` pairs the source rejected with a 619 bad-date —
    skipped, not an outage.
    """

    weeks: tuple[PullWeekResult, ...] = ()
    skipped: tuple[tuple[int, int], ...] = ()
    degraded: bool = False
    outage_reason: str | None = None


# --- untrusted-JSON parsing (FRG-NFR-012) -----------------------------------


def _clean_str(value: Any) -> str | None:
    """Reduce one untrusted source scalar to bounded, control-free plain text.

    Non-strings are coerced via ``str`` (the source occasionally sends a bare
    number for a field); ANSI escapes and C0/DEL control chars (including CR/LF)
    are stripped so nothing can forge a log line or smuggle control codes into
    storage; whitespace is collapsed; the result is length-capped. Returns
    ``None`` when nothing printable remains. Never raises.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > MAX_FIELD_LENGTH:
        text = text[:MAX_FIELD_LENGTH].rstrip()
    return text or None


def _coerce_cv_id(value: Any) -> int | None:
    """Coerce a source-supplied ComicVine id to a bounded positive int, else
    ``None``. Accepts ``int`` or a digit string; rejects junk, negatives, and
    absurdly large values (defence against a hostile integer in a typed column).
    The ids are *candidates* only — dropping a bad one is harmless (the matcher
    guards them regardless, FRG-PULL-004)."""
    if isinstance(value, bool):  # bools are ints in Python — never an id
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str):
        token = value.strip()
        if not token.isdigit():
            return None
        try:
            candidate = int(token)
        except ValueError:  # pragma: no cover - isdigit already guards this
            return None
    else:
        return None
    if candidate <= 0 or candidate > _MAX_CV_ID:
        return None
    return candidate


def _parse_date(value: Any) -> dt.date | None:
    """Parse a source ``shipdate`` ("YYYY-MM-DD") to a ``date``, hardened: any
    malformed / out-of-range / wrong-type value yields ``None`` (the entry is
    then skipped) rather than raising."""
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    try:
        return dt.date.fromisoformat(token[:10])
    except ValueError:
        return None


def _parse_entry(raw: Any) -> ParsedPullEntry | None:
    """Map one raw source object to a :class:`ParsedPullEntry`, or ``None`` to
    skip it. Every field is bounded/sanitised; a missing/malformed required
    field (series, issue, ship date) drops the whole entry. Never raises."""
    if not isinstance(raw, dict):
        return None
    series = _clean_str(raw.get("series"))
    issue = _clean_str(raw.get("issue"))
    release_date = _parse_date(raw.get("shipdate"))
    if series is None or issue is None or release_date is None:
        return None
    return ParsedPullEntry(
        series_name=series,
        issue_number=issue,
        release_date=release_date,
        publisher=_clean_str(raw.get("publisher")),
        cv_series_id=_coerce_cv_id(raw.get("comicid")),
        cv_issue_id=_coerce_cv_id(raw.get("issueid")),
    )


def parse_pull_payload(
    content: bytes, *, max_entries: int = MAX_PULL_ENTRIES
) -> list[ParsedPullEntry]:
    """Parse an (already byte-capped) untrusted pull-source body into typed
    entries (FRG-NFR-012).

    Whole-body malformation — non-JSON, or a top level that is not a JSON array —
    raises :class:`PullSourceOutage` (``reason="malformed"``): the body is
    unusable, so the run degrades rather than storing garbage. A single
    malformed *entry* inside a valid array is skipped with a bounded debug log.
    At most ``max_entries`` entries are returned; extras are dropped with one
    bounded warning.
    """
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise PullSourceOutage(
            "pull source returned a non-JSON body", reason="malformed"
        ) from exc
    if not isinstance(data, list):
        raise PullSourceOutage(
            "pull source body was not a JSON array", reason="malformed"
        )

    entries: list[ParsedPullEntry] = []
    skipped = 0
    for raw in data:
        if len(entries) >= max_entries:
            logger.warning(
                "pull source payload exceeded the %d-entry cap; extra rows dropped",
                max_entries,
            )
            break
        parsed = _parse_entry(raw)
        if parsed is None:
            skipped += 1
            continue
        entries.append(parsed)
    if skipped:
        logger.debug("pull source: skipped %d malformed/incomplete entries", skipped)
    return entries


# --- the client -------------------------------------------------------------


class PullSourceClient:
    """Hardened async client for the external weekly-pull JSON source
    (FRG-PULL-002).

    Bound to one outbound ``external`` client from the shared factory. Usable as
    an async context manager; otherwise call :meth:`aclose`.

    ``source_url`` is the configured endpoint (``pull_source_url``, owned by area
    D) — passed explicitly so this client carries no config surface. ``backoff``
    is optional: when supplied, an outage records a failure and a fully
    successful run records a success on the shared ``PROVIDER_PULL`` ladder,
    which is what drives the degraded-source health item; when omitted (unit
    tests of pure parse/fetch), no health state is written. This client does
    NOT gate itself on the ladder — scheduling/throttle and the manual-force
    bypass are area D's concern (FRG-PULL-006).
    """

    def __init__(
        self,
        factory: HttpClientFactory,
        source_url: str,
        *,
        backoff: ProviderBackoff | None = None,
        max_response_bytes: int = PULL_JSON_MAX_BYTES,
        max_entries: int = MAX_PULL_ENTRIES,
    ) -> None:
        self._client = factory.external()
        self._source_url = source_url
        self._backoff = backoff
        self._max_response_bytes = max_response_bytes
        self._max_entries = max_entries

    # -- public API ---------------------------------------------------------

    async def fetch_week(self, *, week: int, year: int) -> list[ParsedPullEntry]:
        """Fetch and parse one release week.

        Raises :class:`PullBadDate` for a 619 bad-date, or
        :class:`PullSourceOutage` for a 522/666/other-status, an egress refusal,
        an oversize or malformed body, or a transport failure.
        """
        content = await self._fetch_raw(week=week, year=year)
        return parse_pull_payload(content, max_entries=self._max_entries)

    async def fetch_weeks(
        self, weeks: Sequence[tuple[int, int]]
    ) -> PullFetchOutcome:
        """Fetch a run of weeks (typically current + previous, FRG-PULL-002).

        A 619 skips only its week and the run continues; ANY outage
        (522/666/egress/oversize/malformed/transport) degrades the whole run —
        no weeks are returned for storage (the prior stored data is left intact)
        and the source is marked degraded in health via the back-off ladder. A
        fully successful run clears the ladder.
        """
        results: list[PullWeekResult] = []
        skipped: list[tuple[int, int]] = []
        for week, year in weeks:
            try:
                entries = await self.fetch_week(week=week, year=year)
            except PullBadDate:
                logger.warning(
                    "pull source: bad-date (619) for week %s of %s; skipping only "
                    "that week",
                    week,
                    year,
                )
                skipped.append((week, year))
                continue
            except PullSourceOutage as outage:
                logger.warning(
                    "pull source outage (%s) fetching week %s of %s; leaving stored "
                    "data intact and marking the source degraded",
                    outage.reason,
                    week,
                    year,
                )
                await self._record_outage(outage)
                return PullFetchOutcome(
                    skipped=tuple(skipped),
                    degraded=True,
                    outage_reason=outage.reason,
                )
            results.append(
                PullWeekResult(week=week, year=year, entries=tuple(entries))
            )
        await self._record_success()
        return PullFetchOutcome(weeks=tuple(results), skipped=tuple(skipped))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PullSourceClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- fetch + status mapping ---------------------------------------------

    async def _fetch_raw(self, *, week: int, year: int) -> bytes:
        """One request end-to-end over the ``external`` egress profile; returns
        the (byte-capped) body for a 200 or raises a typed error."""
        try:
            result = await self._client.get(
                self._source_url,
                params={"week": str(int(week)), "year": str(int(year))},
                headers={"user-agent": _user_agent()},
                max_bytes=self._max_response_bytes,
            )
        except EgressPolicyError as exc:
            # A loopback/private/link-local (or forbidden-scheme) source URL is
            # refused per-hop before any connection — surfaced as a degraded
            # source, never used to reach an internal host (RISK-025).
            raise PullSourceOutage(
                f"pull source refused by egress policy: {exc}",
                reason="egress-refused",
            ) from exc
        except OutboundHttpError as exc:
            # Oversize body / too-many-redirects from the factory (redacted).
            raise PullSourceOutage(
                f"pull source fetch refused: {exc}", reason="fetch-refused"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            # httpx timeout/transport types cannot be named here (importing
            # httpx outside foragerr.http is banned by the static guard), so any
            # non-typed failure of the network call is wrapped.
            raise PullSourceOutage(
                "pull source request failed", reason="transport"
            ) from exc

        return self._body_for_status(result, week=week, year=year)

    def _body_for_status(self, result: Any, *, week: int, year: int) -> bytes:
        code = result.status_code
        if code == 200:
            return result.content
        if code == CODE_BAD_DATE:
            raise PullBadDate(
                f"pull source reported a bad/invalid date (HTTP {CODE_BAD_DATE}) "
                f"for week {week} of {year}"
            )
        if code == CODE_BACKEND_DOWN:
            raise PullSourceOutage(
                f"pull source backend is down (HTTP {CODE_BACKEND_DOWN})",
                reason="backend-down",
            )
        if code == CODE_UPDATE_REQUIRED:
            raise PullSourceOutage(
                f"pull source requires a client update (HTTP {CODE_UPDATE_REQUIRED})",
                reason="update-required",
                fast_forward=True,
            )
        raise PullSourceOutage(
            f"pull source returned unexpected HTTP {code}", reason=f"http-{code}"
        )

    # -- health / back-off ladder -------------------------------------------

    async def _record_outage(self, outage: PullSourceOutage) -> None:
        if self._backoff is not None:
            await self._backoff.record_failure(
                PROVIDER_PULL,
                PULL_PROVIDER_ID,
                reason=outage.reason,
                fast_forward=outage.fast_forward,
            )

    async def _record_success(self) -> None:
        if self._backoff is not None:
            await self._backoff.record_success(PROVIDER_PULL, PULL_PROVIDER_ID)


__all__ = [
    "CODE_BACKEND_DOWN",
    "CODE_BAD_DATE",
    "CODE_UPDATE_REQUIRED",
    "MAX_FIELD_LENGTH",
    "MAX_PULL_ENTRIES",
    "PULL_JSON_MAX_BYTES",
    "ParsedPullEntry",
    "PullBadDate",
    "PullFetchOutcome",
    "PullSourceClient",
    "PullSourceError",
    "PullSourceOutage",
    "PullWeekResult",
    "parse_pull_payload",
]

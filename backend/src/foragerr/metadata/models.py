"""Typed, sentinel-free records mapped from ComicVine JSON (FRG-META-005/006).

Every field is a declared type or ``None`` — never a sentinel string such as
``'None'``, ``'Unknown'``, ``'0000'`` or ``'0000-00-00'`` (FRG-DB-008 spirit).
Issue numbers are preserved verbatim as ``str`` (``"1.5"``, ``"1.MU"``, ``"½"``
round-trip unchanged) — never coerced to a number. All human-readable text
carried here has already passed through
:func:`foragerr.metadata.sanitize.sanitize_cv_text`.

These records deliberately carry no persistence concerns and no dependency on
the ``library`` domain models — the flows/library agents translate them into
ORM rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class IssueRef:
    """A lightweight reference to an issue (e.g. a volume's first issue)."""

    cv_issue_id: int | None
    issue_number: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class SeriesRecord:
    """A ComicVine *volume* mapped to a series-shaped record (FRG-META-005)."""

    cv_volume_id: int
    name: str | None
    publisher: str | None
    imprint: str | None
    start_year: int | None
    #: Issue count — the actual returned issue-element count wins over
    #: ComicVine's ``count_of_issues`` when they disagree (FRG-META-005).
    count_of_issues: int | None
    aliases: tuple[str, ...]
    description: str | None
    site_url: str | None
    first_issue: IssueRef | None
    image_url: str | None
    #: ComicVine's ``date_last_updated`` for the volume as served, after the
    #: standard CV-string sanitizer (FRG-META-014 covers every CV string), or
    #: ``None``. Used only for equality against the stored stamp to decide the
    #: unchanged-volume refresh short-circuit (FRG-META-017) — never parsed or
    #: timezone-converted.
    date_last_updated: str | None = None


@dataclass(frozen=True, slots=True)
class VolumeStub:
    """A lightweight ComicVine volume reference (FRG-CRTR-005).

    The ``volume_credits`` a person-detail response lists are STUBS — a cv volume
    id plus a (sanitized) name only; they carry no publisher/start_year/issue
    count. Those full fields come from a later batched hydration
    (:meth:`ComicVineClient.get_volumes_by_ids`) that maps each row to a full
    :class:`SeriesRecord`. ``name`` is ``None`` when the stub had no usable name.
    """

    cv_volume_id: int
    name: str | None


@dataclass(frozen=True, slots=True)
class CreditRecord:
    """One per-issue person credit mapped from ComicVine (FRG-CRTR-001).

    ``name`` has already passed through
    :func:`foragerr.metadata.sanitize.sanitize_cv_text` (untrusted CV wiki
    content). ``role_verbatim`` retains the original (sanitized) role token so
    nothing is lost for later refinement; ``role_normalized`` is one slot of the
    fixed vocabulary (:data:`foragerr.metadata.credits.ROLE_VOCABULARY`) the UI
    chips and the ``issue_credits`` CHECK constraint key off. One record per
    ``(cv_person_id, role_normalized)`` — a compound CV role like
    ``"penciler, inker"`` yields two records.
    """

    cv_person_id: int
    name: str
    role_verbatim: str
    role_normalized: str


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """A ComicVine issue mapped to an issue-shaped record (FRG-META-006).

    ``issue_number`` is verbatim TEXT or ``None`` when ComicVine supplied no
    number; ``is_unnumbered`` mirrors that so callers can surface (not drop)
    unnumbered issues. Dates are kept as verbatim ISO ``str`` or ``None``.
    ``credits`` carries the issue's typed person credits (empty when the CV row
    had no ``person_credits`` field, or an empty/malformed one — FRG-CRTR-001).
    """

    cv_issue_id: int
    issue_number: str | None
    title: str | None
    cover_date: str | None
    store_date: str | None
    image_url: str | None
    credits: tuple[CreditRecord, ...] = ()

    @property
    def is_unnumbered(self) -> bool:
        return self.issue_number is None


@dataclass(frozen=True, slots=True)
class Plausibility:
    """Non-binding plausibility annotations riding alongside a search
    candidate (FRG-META-007). These rank/inform; they never auto-pick.

    Attributes:
        name_similarity: 0..1 similarity of the candidate name to the query,
            measured on the shared matching key (``parser.normalize``).
        year_proximity: absolute year distance when a year was extractable
            from the query and the candidate has a start year, else ``None``.
        target_issue_plausible: whether the candidate's issue count can
            contain a requested target issue, when one was supplied, else
            ``None``.
        haveit: whether this volume is already in the local library. The
            search layer cannot see library state, so it defaults ``False``;
            the flows/api caller sets it.
    """

    name_similarity: float
    year_proximity: int | None
    target_issue_plausible: bool | None
    haveit: bool = False


@dataclass(frozen=True, slots=True)
class SeriesCandidate:
    """A search result: a mapped series record plus its plausibility signals."""

    series: SeriesRecord
    plausibility: Plausibility


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The bounded, annotated result set of a series search (FRG-META-007)."""

    candidates: tuple[SeriesCandidate, ...]
    total_results: int | None
    #: True when the result set was cut to the configured cap; a truncation
    #: warning was logged.
    truncated: bool
    #: Mirrors the underlying pagination walk's completeness (FRG-META-004):
    #: ``False`` when a non-auth mid-walk failure or the hard page cap left
    #: the result partial, so callers can tell a degraded walk apart from a
    #: clean, complete empty result. (Auth failures no longer reach here —
    #: they propagate as ``ComicVineAuthError``.)
    complete: bool


@dataclass(frozen=True, slots=True)
class SuggestResult:
    """The bounded, single-page result of a ComicVine suggest fetch
    (FRG-API-017) — a cheap as-you-type accelerator over :class:`SearchResult`.

    Unlike :class:`SearchResult`, there is NO ``truncated`` flag: a suggest
    fetch is definitionally partial (the full lookup, not suggest, is the
    complete search), so a cap is not a truncation worth signalling.
    ``complete`` distinguishes a clean single-page fetch (``True``) from one
    degraded by a mid-fetch upstream failure (``False``) — auth failures
    still propagate as :class:`~foragerr.metadata.errors.ComicVineAuthError`
    rather than reaching here, exactly as :class:`SearchResult` documents.
    """

    candidates: tuple[SeriesRecord, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """The result of a bounded, offset-based ComicVine pagination walk.

    CORRECTNESS CONTRACT (relied upon by refresh reconciliation, FRG-META-004
    / FRG-META-008 — read before consuming ``items``):

    * ``items`` holds every element successfully retrieved so far, in order.
    * ``complete`` is ``True`` ONLY when the walk retrieved the *entire*
      advertised result set with no error and without hitting the hard page
      cap. When ``complete`` is ``False`` the set is PARTIAL — a page failed
      mid-walk, or the ``number_of_total_results`` exceeded the page cap.
      **Callers MUST NOT delete local records absent from a partial fetch:**
      the absence may simply be data we failed to retrieve, not data removed
      upstream.
    * ``total_results`` is ComicVine's advertised ``number_of_total_results``
      (``None`` if it was never seen), for cross-checking ``len(items)``.
    * ``truncated`` is ``True`` when the hard page cap stopped the walk before
      the advertised total was reached (a bounded, deliberately incomplete
      result); ``truncated`` implies ``complete is False``.
    """

    items: tuple[T, ...]
    complete: bool
    total_results: int | None
    truncated: bool = False

"""foragerr comic-name parser — the single implementation (FRG-IMP-001).

``parse(name, *, reference_year, mode=..., options=...)`` is a pure function:
identical inputs always yield identical output. No clock, config, watchlist,
database, or network access anywhere in this package (FRG-IMP-002). Every
input returns a structured :class:`ParseResult`; no input ever raises
(FRG-IMP-003).

Pipeline (each stage a pure pass over the token stream): normalize →
strip extension → extract ``[__id__]`` → tokenize → classify annotation
groups → scan designators (volume / markers / booktype / editions) →
collect year + issue candidates → select issue (leading-title guard,
``#`` anchor precedence, ``(of N)`` override, year-position exclusion, dash
demotion, rightmost survivor) → year-equals-issue one-shot rule → assemble
title / alternate splits / annotations / scan group → confidence.
"""

from __future__ import annotations

import re
from fractions import Fraction

from . import grammar
from .classify import (
    GroupInfo,
    classify_group,
    edition_match,
    is_page_tag,
    scan_group_eligible,
)
from .normalize import fold, matching_key, nfc
from .ordering import sort_key
from .result import (
    Annotation,
    AnnotationKind,
    Booktype,
    FailureReason,
    Issue,
    IssueClassification,
    IssueRange,
    ParseMode,
    ParseResult,
    TraceEntry,
)
from .tokenize import Token, TokenKind, tokenize
from .vocab import (
    DEFAULT_OPTIONS,
    MONTH_NAMES,
    ParseOptions,
    booktype_cue_phrases,
    edition_phrases,
    extension_re,
    issue_suffix_set,
)

__all__ = [
    "parse",
    "ParseResult",
    "ParseMode",
    "ParseOptions",
    "DEFAULT_OPTIONS",
    "Annotation",
    "AnnotationKind",
    "Booktype",
    "FailureReason",
    "Issue",
    "IssueClassification",
    "IssueRange",
    "TraceEntry",
    "matching_key",
    "sort_key",
]

_ISSUE_ID_RE = re.compile(r"\[__(.{1,64}?)__\]")

#: `(fN)` fixed-release marker group inner text (FRG-PP-014), matched whole
#: against the folded group content — `(f1)`, `(F2)`, `[f1]`.
_FIX_MARKER_RE = re.compile(r"f(\d{1,2})")

#: Trade formats whose trailing number reads as a volume (FRG-IMP-016).
_TRADE_BOOKTYPES = (Booktype.TPB, Booktype.GN, Booktype.HC)


def parse(
    name: str,
    *,
    reference_year: int,
    mode: ParseMode = ParseMode.FILENAME,
    options: ParseOptions = DEFAULT_OPTIONS,
) -> ParseResult:
    """Parse a comic filename, release title, or (folder mode) series folder.

    Never raises: any internal error degrades to a structured failure with
    reason ``INTERNAL_ERROR`` (FRG-IMP-003).
    """
    try:
        return _parse_impl(name, reference_year, mode, options)
    except Exception:  # never let any input crash a caller (FRG-IMP-003)
        return ParseResult(
            mode=mode, confidence=0.0, failure_reason=FailureReason.INTERNAL_ERROR
        )


# ---------------------------------------------------------------------------
# implementation


def _failure(
    reason: FailureReason, mode: ParseMode, confidence: float = 0.05, **fields
) -> ParseResult:
    return ParseResult(
        mode=mode, confidence=confidence, failure_reason=reason, **fields
    )


def _parse_impl(
    name: str, reference_year: int, mode: ParseMode, options: ParseOptions
) -> ParseResult:
    work = nfc(name).strip()
    if not work:
        return _failure(FailureReason.EMPTY_INPUT, mode, confidence=0.0)

    # extension: exactly the single trailing occurrence, case-insensitive
    # (FRG-IMP-006); release titles / folder names simply have none.
    ext: str | None = None
    if mode is ParseMode.FILENAME:
        m = extension_re(options).search(work)
        if m:
            ext = m.group(1).lower()
            work = work[: m.start()]

    # embedded [__<id>__] pass-through, anywhere in the name (FRG-IMP-018)
    issue_id: str | None = None
    m = _ISSUE_ID_RE.search(work)
    if m:
        issue_id = m.group(1)
        work = (work[: m.start()] + " " + work[m.end() :]).strip()

    tokens = tokenize(work)
    if not tokens:
        return _failure(
            FailureReason.NO_SERIES_TITLE, mode, type=ext, issue_id=issue_id
        )

    state = _State(tokens, reference_year, options)
    state.classify_groups()
    state.scan_multiword_editions()
    state.scan_booktype_cues()
    state.scan_volumes()
    state.scan_markers()
    state.scan_cover_variants()
    state.scan_month_year_pairs()
    state.scan_bare_counts()
    state.collect_year_candidates()
    state.collect_issue_candidates()
    state.select_year()
    state.select_issue()
    state.apply_year_equals_issue_rule()
    state.apply_trade_volume_rule()
    state.scan_fix_markers()
    state.attach_space_suffix()
    state.assemble_regions()

    return state.build_result(mode, ext, issue_id)


class _State:
    """Mutable working state for one parse (internal; results are frozen)."""

    def __init__(self, tokens: list[Token], reference_year: int, options: ParseOptions):
        self.tokens = tokens
        self.n = len(tokens)
        self.ref = reference_year
        self.options = options
        self.consumed = [False] * self.n
        self.roles: dict[int, str] = {}
        self.ginfo: dict[int, GroupInfo] = {}
        self.booktype: Booktype | None = None
        self.volume_ordinal: int | None = None
        self.volume_year: int | None = None
        self.classification = IssueClassification.REGULAR
        self.marker_found = False
        self.annotations: list[tuple[int, Annotation]] = []
        self.year_cands: list[tuple[int, int]] = []  # (index, year)
        self.cands: list[grammar.Candidate] = []
        self.miniseries_total: Fraction | None = None
        self.count_positions: list[int] = []
        self.anchored_indices: set[int] = set()
        self.year: int | None = None
        self.year_pos: int | None = None
        self.selected: grammar.Candidate | None = None
        self.issue_pos: int | None = None
        self.one_shot = False
        self.alt_series: str | None = None
        self.alt_issue_title: str | None = None
        self.scan_group: str | None = None
        self.fix_revision: int | None = None
        self.series_name: str | None = None

    # -- helpers ------------------------------------------------------------

    def words(self):
        return [
            t
            for t in self.tokens
            if t.kind is TokenKind.WORD and not self.consumed[t.index]
        ]

    def consume(self, index: int, role: str) -> None:
        self.consumed[index] = True
        self.roles[index] = role

    def annotate(self, index: int, text: str, kind: AnnotationKind) -> None:
        self.annotations.append((index, Annotation(text=text, kind=kind)))

    def _is_group(self, t: Token) -> bool:
        return t.kind in (TokenKind.GROUP_PAREN, TokenKind.GROUP_BRACKET)

    # -- stages ---------------------------------------------------------------

    def classify_groups(self) -> None:
        for t in self.tokens:
            if not self._is_group(t):
                continue
            gi = classify_group(t.inner, self.ref, self.options)
            self.ginfo[t.index] = gi
            self.consumed[t.index] = True  # groups are never title content
            self.roles[t.index] = gi.kind.value
            if gi.kind is AnnotationKind.DATE and gi.year is not None:
                self.year_cands.append((t.index, gi.year))
            elif gi.kind is AnnotationKind.YEAR_RANGE and gi.volume_year is not None:
                if self.volume_year is None:
                    self.volume_year = gi.volume_year
            elif gi.kind is AnnotationKind.COUNT and gi.total is not None:
                self.count_positions.append(t.index)
                if self.miniseries_total is None:
                    self.miniseries_total = gi.total
            if gi.booktype is not None and self.booktype is None:
                self.booktype = gi.booktype
            if gi.kind not in (AnnotationKind.DATE, AnnotationKind.YEAR_RANGE) and t.inner:
                self.annotate(t.index, t.inner, gi.kind)

    def _match_phrase(self, start: int, phrase: tuple[str, ...]) -> bool:
        for offset, word in enumerate(phrase):
            j = start + offset
            if j >= self.n:
                return False
            t = self.tokens[j]
            if t.kind is not TokenKind.WORD or self.consumed[j] or t.folded != word:
                return False
        return True

    def _scan_phrase_vocab(
        self,
        pairs: tuple[tuple[tuple[str, ...], Booktype | None], ...],
        role: str,
        annotate_kind: AnnotationKind | None = None,
    ) -> None:
        """Match multi-word vocabulary phrases (longest first), consuming each
        hit under ``role``, optionally recording an annotation, and adopting the
        paired booktype. Shared by the edition and booktype-cue scans."""
        for i in range(self.n):
            if self.consumed[i] or self.tokens[i].kind is not TokenKind.WORD:
                continue
            for phrase, bt in pairs:
                if self._match_phrase(i, phrase):
                    if annotate_kind is not None:
                        text = " ".join(
                            self.tokens[i + k].text for k in range(len(phrase))
                        )
                        self.annotate(i, text, annotate_kind)
                    for k in range(len(phrase)):
                        self.consume(i + k, role)
                    if bt is not None and self.booktype is None:
                        self.booktype = bt
                    break

    def scan_multiword_editions(self) -> None:
        self._scan_phrase_vocab(
            edition_phrases(self.options), "edition", AnnotationKind.EDITION
        )

    def scan_booktype_cues(self) -> None:
        self._scan_phrase_vocab(booktype_cue_phrases(self.options), "booktype")

    def scan_volumes(self) -> None:
        vol_words = frozenset({"vol", "vol.", "volume"})
        i = 0
        while i < self.n:
            t = self.tokens[i]
            if t.kind is not TokenKind.WORD or self.consumed[i]:
                i += 1
                continue
            m = grammar.RE_VOL_GLUED.match(t.inner)
            if m and t.folded not in vol_words:
                self._set_volume(m.group(1), i, i)
                i += 1
                continue
            if t.folded in vol_words:
                j = i + 1
                if j < self.n and self.tokens[j].kind is TokenKind.WORD and not self.consumed[j]:
                    nxt = self.tokens[j]
                    if grammar.RE_PLAIN.match(nxt.inner):
                        self._set_volume(nxt.inner, i, j)
                        i = j + 1
                        continue
                    roman = grammar.roman_to_int(nxt.inner)
                    if roman is not None:
                        if self.volume_ordinal is None and self.volume_year is None:
                            self.volume_ordinal = roman
                        self.consume(i, "volume")
                        self.consume(j, "volume")
                        i = j + 1
                        continue
            i += 1

    def _set_volume(self, digits: str, start: int, end: int) -> None:
        value = int(digits)
        if self.volume_ordinal is None and self.volume_year is None:
            if len(digits) == 4 and 1900 <= value <= 2099:
                self.volume_year = value
            else:
                self.volume_ordinal = value
        for k in range(start, end + 1):
            self.consume(k, "volume")

    def scan_markers(self) -> None:
        markers = {fold(m): cls for m, cls in self.options.annual_markers}
        seasons = frozenset(fold(s) for s in self.options.season_words)
        for i in range(1, self.n):  # never at index 0: a title must precede
            t = self.tokens[i]
            if t.kind is not TokenKind.WORD or self.consumed[i]:
                continue
            cls = markers.get(t.folded)
            if cls is None:
                continue
            nxt = self.tokens[i + 1] if i + 1 < self.n else None
            prev = self.tokens[i - 1] if i >= 1 else None
            next_ok = nxt is not None and (
                (nxt.kind is TokenKind.WORD and nxt.inner[:1].isdigit())
                or (
                    self._is_group(nxt)
                    and self.ginfo.get(nxt.index, GroupInfo(AnnotationKind.GENERIC)).kind
                    is AnnotationKind.DATE
                )
            )
            prev_ok = (
                prev is not None
                and prev.kind is TokenKind.WORD
                and prev.inner[:1].isdigit()
                and not self.consumed[prev.index]
            )
            if not (next_ok or prev_ok):
                continue
            if not self.marker_found:
                self.classification = cls
                self.marker_found = True
            self.consume(i, "marker")
            season_prev = self.tokens[i - 1] if i >= 1 else None
            if (
                season_prev is not None
                and season_prev.kind is TokenKind.WORD
                and not self.consumed[season_prev.index]
                and season_prev.folded in seasons
            ):
                self.consume(season_prev.index, "marker")

    def scan_cover_variants(self) -> None:
        for i in range(1, self.n):
            t = self.tokens[i]
            if t.kind is not TokenKind.WORD or self.consumed[i]:
                continue
            folded = t.folded
            if folded == "cover" and i + 1 < self.n:
                nxt = self.tokens[i + 1]
                if (
                    nxt.kind is TokenKind.WORD
                    and not self.consumed[nxt.index]
                    and len(nxt.inner) <= 2
                    and nxt.inner.isalnum()
                ):
                    self.consume(i, "cover-variant")
                    self.consume(nxt.index, "cover-variant")
                    self.annotate(
                        i, f"{t.text} {nxt.text}", AnnotationKind.COVER_VARIANT
                    )
            elif folded in ("covers", "cover"):
                prev = self.tokens[i - 1]
                if (
                    prev.kind is TokenKind.WORD
                    and not self.consumed[prev.index]
                    and grammar.RE_PLAIN.match(prev.inner)
                    and len(prev.inner) <= 3
                    and prev.index != 0
                ):
                    self.consume(prev.index, "covers")
                    self.consume(i, "covers")
                    self.annotate(
                        prev.index, f"{prev.text} {t.text}", AnnotationKind.COVERS
                    )

    def scan_month_year_pairs(self) -> None:
        for i in range(1, self.n - 1):
            t = self.tokens[i]
            if t.kind is not TokenKind.WORD or self.consumed[i]:
                continue
            if t.folded in MONTH_NAMES:
                nxt = self.tokens[i + 1]
                if (
                    nxt.kind is TokenKind.WORD
                    and not self.consumed[nxt.index]
                    and grammar.RE_YEAR.match(nxt.inner)
                ):
                    year = int(nxt.inner)
                    if grammar.plausible_year(year, self.ref):
                        self.consume(i, "date")
                        self.year_cands.append((nxt.index, year))

    def scan_bare_counts(self) -> None:
        # bare `01 of 8` mini-series counts (FRG-IMP-011)
        for i in range(1, self.n - 1):
            t = self.tokens[i]
            if t.kind is not TokenKind.WORD or self.consumed[i] or t.folded != "of":
                continue
            prev, nxt = self.tokens[i - 1], self.tokens[i + 1]
            if (
                prev.kind is TokenKind.WORD
                and nxt.kind is TokenKind.WORD
                and not self.consumed[prev.index]
                and not self.consumed[nxt.index]
                and grammar.RE_PLAIN.match(prev.inner)
                and (grammar.RE_PLAIN.match(nxt.inner) or grammar.RE_DECIMAL.match(nxt.inner))
                and prev.index != 0
            ):
                total = grammar.to_fraction(nxt.inner)
                if total is None:
                    continue
                if self.miniseries_total is None:
                    self.miniseries_total = total
                self.count_positions.append(i)
                self.consume(i, "count")
                self.consume(nxt.index, "count")

    def collect_year_candidates(self) -> None:
        for t in self.tokens:
            if t.kind is not TokenKind.WORD or self.consumed[t.index] or t.index == 0:
                continue
            text = t.inner
            if grammar.RE_YEAR.match(text):
                y = int(text)
                if grammar.plausible_year(y, self.ref):
                    self.year_cands.append((t.index, y))
            else:
                m = grammar.RE_ISO_DATE.match(text)
                if m and 1 <= int(m.group(2)) <= 12:
                    y = int(m.group(1))
                    if grammar.plausible_year(y, self.ref):
                        self.year_cands.append((t.index, y))

    def collect_issue_candidates(self) -> None:
        hash_pending = False
        for t in self.tokens:
            if self._is_group(t):
                continue
            if t.kind is TokenKind.HASH and not self.consumed[t.index]:
                hash_pending = True
                self.consume(t.index, "issue-anchor")
                continue
            if t.kind is not TokenKind.WORD or self.consumed[t.index]:
                continue
            cand = grammar.numeric_candidate(t, self.options, self.ref)
            if cand is None:
                hash_pending = False
                continue
            if hash_pending:
                cand.anchored = True
                hash_pending = False
            if t.index == 0 and not cand.anchored:
                continue  # leading-title guard (FRG-IMP-007)
            self.cands.append(cand)

    def select_year(self) -> None:
        if self.year_cands:
            self.year_pos, self.year = max(self.year_cands, key=lambda p: p[0])
            self.roles.setdefault(self.year_pos, "year")

    def select_issue(self) -> None:
        # (of N) override: flag the nearest candidate left of each count marker
        for pos in self.count_positions:
            preceding = [c for c in self.cands if c.index < pos]
            if preceding:
                preceding[-1].count_flagged = True

        viable = list(self.cands)
        flagged = [c for c in viable if c.count_flagged]
        if flagged:
            self.selected = flagged[-1]
        else:
            non_year = [c for c in viable if c.index != self.year_pos]
            anchored = [c for c in non_year if c.anchored]
            pool = anchored or non_year
            demoted = self._dash_demoted_indices()
            normal = [c for c in pool if c.index not in demoted]
            pick_from = normal or pool
            self.selected = pick_from[-1] if pick_from else None
        if self.selected is not None:
            self.issue_pos = self.selected.index
            self.roles[self.issue_pos] = "issue"
            self._consume_part_cue()

    def _consume_part_cue(self) -> None:
        """`Part N` is an issue/chapter cue, never a volume (FRG-IMP-012):
        when the selected issue follows a `part` token, consume the cue so it
        does not leak into the series title."""
        i = (self.issue_pos or 0) - 1
        if i >= 1:
            prev = self.tokens[i]
            if (
                prev.kind is TokenKind.WORD
                and not self.consumed[i]
                and prev.folded in ("part", "pt", "pt.")
            ):
                self.consume(i, "issue-cue")

    def _dash_demoted_indices(self) -> set[int]:
        """Candidates sitting inside a post-dash subtitle are demoted
        (FRG-IMP-007): a standalone dash lies between an earlier candidate
        and this one, and unconsumed words follow it. O(n) precomputation —
        pathological dash runs stay within the fuzz wall-clock ceiling.
        """
        if not self.cands:
            return set()
        first_cand = self.cands[0].index
        first_dash_after = next(
            (
                t.index
                for t in self.tokens[first_cand + 1 :]
                if t.kind is TokenKind.DASH
            ),
            None,
        )
        if first_dash_after is None:
            return set()
        last_word = max(
            (
                t.index
                for t in self.tokens
                if t.kind is TokenKind.WORD and not self.consumed[t.index]
            ),
            default=-1,
        )
        return {
            c.index
            for c in self.cands
            if c.index > first_dash_after and last_word > c.index
        }

    def apply_year_equals_issue_rule(self) -> None:
        """FRG-IMP-014: the only candidate equals the cover year."""
        if self.year is None:
            return
        if self.selected is None:
            # all candidates sat at the year position (e.g. `Wolverine 1997
            # Annual`): with a marker, the year is the issue (year-as-issue).
            at_year = [c for c in self.cands if c.index == self.year_pos]
            if len(self.cands) == 1 and at_year and self.marker_found:
                self.selected = at_year[0]
                self.issue_pos = self.selected.index
                self.roles[self.issue_pos] = "issue"
            return
        c = self.selected
        if (
            len(self.cands) == 1
            and not c.anchored
            and not c.is_range
            and c.suffix is None
            and c.value is not None
            and c.value == Fraction(self.year)
        ):
            if self.marker_found:
                return  # annual marker beats the one-shot reclassification
            # one-shot: the number is title content, never issue #<year>
            self.one_shot = True
            self.roles[c.index] = "series-title"
            self.selected = None
            self.issue_pos = None
            if self.booktype is None:
                self.booktype = Booktype.ONE_SHOT

    def apply_trade_volume_rule(self) -> None:
        """Trade formats read the trailing number as the volume (FRG-IMP-016)."""
        if self.booktype not in _TRADE_BOOKTYPES:
            return
        if self.volume_ordinal is None and self.volume_year is None:
            c = self.selected
            if (
                c is not None
                and not c.is_range
                and c.suffix is None
                and c.name is None
                and not c.is_infinity
                and c.value is not None
                and c.value.denominator == 1
                and c.value >= 0
            ):
                self.volume_ordinal = int(c.value)
                self.roles[c.index] = "volume"
                self.selected = None  # issue_pos kept: still the title boundary
            elif not self.cands:
                # No numeric evidence at all: fabricate v1 (FRG-IMP-016,
                # corpus row 47 East of West TPB). A disqualified candidate
                # (suffix / range / name / infinity / negative / non-integer)
                # is NOT volume evidence and leaves volume_ordinal None.
                self.volume_ordinal = 1

    def scan_fix_markers(self) -> None:
        """`(fN)` fixed-release markers (FRG-PP-014), with a title-plausibility
        guard: only a standalone group sitting AFTER the selected issue (or,
        with no issue, after the last word token — i.e. trailing, near the
        extension, per common scene naming) reads as a fix marker, so an
        `(f1)` embedded inside a series title never false-positives. A
        recognized marker is re-kinded to FIX_MARKER, which also removes it
        from the generic scan-group candidate pool. Runs after issue selection
        (it needs the issue position) and before region assembly (which picks
        the scan group)."""
        last_word = max(
            (t.index for t in self.tokens if t.kind is TokenKind.WORD), default=-1
        )
        anchor = self.issue_pos if self.issue_pos is not None else last_word
        for t in self.tokens:
            if not self._is_group(t) or t.index <= anchor:
                continue
            gi = self.ginfo.get(t.index)
            if gi is None or gi.kind is not AnnotationKind.GENERIC:
                continue
            m = _FIX_MARKER_RE.fullmatch(fold(t.inner.strip()))
            if m is None:
                continue
            revision = int(m.group(1))
            gi.kind = AnnotationKind.FIX_MARKER
            self.roles[t.index] = "fix-marker"
            self.annotations = [
                (i, Annotation(text=a.text, kind=AnnotationKind.FIX_MARKER))
                if i == t.index and a.kind is AnnotationKind.GENERIC
                else (i, a)
                for i, a in self.annotations
            ]
            if self.fix_revision is None or revision > self.fix_revision:
                self.fix_revision = revision

    # -- assembly -------------------------------------------------------------

    def _boundary(self) -> int:
        if self.issue_pos is not None:
            return self.issue_pos
        stops: list[int] = []
        for t in self.tokens:
            i = t.index
            if self._is_group(t):
                stops.append(i)
            elif self.consumed[i] and self.roles.get(i) != "series-title":
                stops.append(i)
            elif i == self.year_pos and not self.one_shot:
                stops.append(i)
        # tokens reclassified as title content (one-shot) are not stops
        if self.one_shot and self.year_pos is not None:
            stops = [s for s in stops if self.roles.get(s) != "series-title"]
        return min(stops) if stops else self.n

    def assemble_regions(self) -> None:
        boundary = self._boundary()
        title_tokens = [
            t
            for t in self.tokens[:boundary]
            if not self._is_group(t)
            and (not self.consumed[t.index] or self.roles.get(t.index) == "series-title")
        ]
        # one-shot reclassified number may sit at/after the numeric boundary
        if self.one_shot:
            title_tokens = [
                t
                for t in self.tokens
                if (t.index < boundary or self.roles.get(t.index) == "series-title")
                and not self._is_group(t)
                and (not self.consumed[t.index] or self.roles.get(t.index) == "series-title")
            ]
        while title_tokens and title_tokens[0].kind is TokenKind.DASH:
            title_tokens.pop(0)
        while title_tokens and title_tokens[-1].kind is TokenKind.DASH:
            title_tokens.pop()
        for t in title_tokens:
            self.roles.setdefault(t.index, "series-title")
        self.series_name = " ".join(t.text for t in title_tokens) or None

        # alternate split from an in-title standalone dash (FRG-IMP-019);
        # in-word hyphens (X-23) never split.
        dash_positions = [
            k for k, t in enumerate(title_tokens) if t.kind is TokenKind.DASH
        ]
        if dash_positions:
            k = dash_positions[0]
            before = " ".join(t.text for t in title_tokens[:k])
            after = " ".join(t.text for t in title_tokens[k + 1 :])
            if before and after:
                self.alt_series = before
                self.alt_issue_title = after

        self._post_issue_region()
        self._trailing_region()

    def _post_issue_region(self) -> None:
        """Words between the issue and the year: dash-led issue titles or
        annotation words (FRG-IMP-019)."""
        if self.issue_pos is None:
            return
        end = self.year_pos if (self.year_pos or -1) > self.issue_pos else self.n
        region = [
            t
            for t in self.tokens[self.issue_pos + 1 : end]
            if not self._is_group(t) and not self.consumed[t.index]
        ]
        if not region:
            return
        if region[0].kind is TokenKind.DASH:
            words = [t for t in region[1:] if t.kind is TokenKind.WORD]
            if words:
                self.alt_issue_title = " ".join(t.text for t in words)
                self.consume(region[0].index, "dash")
                for t in words:
                    self.consume(t.index, "issue-title")
            return
        leftover: list[Token] = []
        for t in region:
            if t.kind is not TokenKind.WORD:
                continue
            if edition_match(t.folded, self.options):
                self.consume(t.index, "edition")
                self.annotate(t.index, t.text, AnnotationKind.EDITION)
            elif is_page_tag(t.folded):
                self.consume(t.index, "page-tag")
                self.annotate(t.index, t.text, AnnotationKind.PAGE_TAG)
            else:
                leftover.append(t)
        if leftover and self.alt_issue_title is None:
            self.alt_issue_title = " ".join(t.text for t in leftover)
            for t in leftover:
                self.consume(t.index, "issue-title")

    def _trailing_region(self) -> None:
        """Bare words after the year: edition tags peel off, the remainder is
        the scan group; trailing generic groups are scan groups (FRG-IMP-017).
        """
        scan_cands: list[tuple[int, str]] = []
        start = self.year_pos + 1 if self.year_pos is not None else None
        if start is not None:
            for t in self.tokens[start:]:
                if self._is_group(t) or self.consumed[t.index]:
                    continue
                if t.index == self.issue_pos:
                    continue  # the issue token is never annotation content
                if t.kind is not TokenKind.WORD:
                    self.consume(t.index, "dash")
                    continue
                remainder = self._peel_editions(t)
                if remainder and not remainder.startswith("."):
                    scan_cands.append((t.index, remainder))
                    self.consume(t.index, "scan-group")
        boundary = self.issue_pos if self.issue_pos is not None else -1
        for t in self.tokens:
            if not self._is_group(t) or t.index <= boundary:
                continue
            gi = self.ginfo.get(t.index)
            if gi is not None and gi.kind is AnnotationKind.GENERIC and scan_group_eligible(t.inner):
                scan_cands.append((t.index, t.inner.strip()))
        if scan_cands:
            idx, text = max(scan_cands, key=lambda p: p[0])
            self.scan_group = text
            self.roles[idx] = "scan-group"
            self.annotations = [
                (i, a)
                for i, a in self.annotations
                if not (i == idx and a.kind is AnnotationKind.GENERIC)
            ]
            self.annotate(idx, text, AnnotationKind.SCAN_GROUP)

    def _peel_editions(self, token: Token) -> str | None:
        """Peel leading edition words off a dash-joined trailing token.

        ``digital-TheGroup`` -> edition ``digital`` + scan group ``TheGroup``;
        ``Glorith-HD`` stays whole (no leading edition word).
        """
        text = token.text
        if edition_match(fold(text), self.options):
            self.annotate(token.index, text, AnnotationKind.EDITION)
            self.consume(token.index, "edition")
            return None
        if is_page_tag(fold(text)):
            self.annotate(token.index, text, AnnotationKind.PAGE_TAG)
            self.consume(token.index, "page-tag")
            return None
        parts = text.split("-")
        while len(parts) > 1 and edition_match(fold(parts[0]), self.options):
            self.annotate(token.index, parts[0], AnnotationKind.EDITION)
            parts = parts[1:]
        return "-".join(parts) if parts else None

    # -- finalization ---------------------------------------------------------

    def attach_space_suffix(self) -> None:
        """Attach a space-separated vocabulary suffix to the selected issue."""
        c = self.selected
        if c is None or c.suffix is not None or c.is_range or c.value is None:
            return
        j = c.index + 1
        while j < self.n and self.consumed[j] and self.roles.get(j) in ("count",):
            j += 1
        if j >= self.n:
            return
        nxt = self.tokens[j]
        if nxt.kind is not TokenKind.WORD or self.consumed[j]:
            return
        canonical = fold(nxt.inner).upper().rstrip("!")
        if canonical in issue_suffix_set(self.options):
            c.suffix = canonical
            c.display = f"{c.display} {nxt.inner.rstrip('!')}"
            self.consume(j, "issue-suffix")

    def build_result(
        self, mode: ParseMode, ext: str | None, issue_id: str | None
    ) -> ParseResult:
        issue: Issue | None = None
        issue_range: IssueRange | None = None
        c = self.selected
        if c is not None:
            if c.is_range and c.value is not None and c.range_end is not None:
                issue_range = IssueRange(
                    start=c.value, end=c.range_end, display=c.display
                )
            else:
                issue = Issue(
                    value=c.value,
                    display=c.display,
                    suffix=c.suffix,
                    classification=self.classification,
                    is_infinity=c.is_infinity,
                    name=c.name,
                )

        annotations = tuple(
            a
            for _, a in sorted(self.annotations, key=lambda p: p[0])
            if a.kind not in (AnnotationKind.DATE, AnnotationKind.YEAR_RANGE)
        )

        trace: tuple[TraceEntry, ...] | None = None
        if self.options.include_trace:
            trace = tuple(
                TraceEntry(text=t.text, role=self.roles.get(t.index, "unclassified"))
                for t in self.tokens
            )

        common = dict(
            alt_series=self.alt_series,
            alt_issue_title=self.alt_issue_title,
            issue=issue,
            issue_range=issue_range,
            miniseries_total=self.miniseries_total,
            volume_ordinal=self.volume_ordinal,
            volume_year=self.volume_year,
            year=self.year,
            booktype=self.booktype or Booktype.ISSUE,
            annotations=annotations,
            scan_group=self.scan_group,
            fix_revision=self.fix_revision,
            issue_id=issue_id,
            type=ext,
            mode=mode,
            token_trace=trace,
        )

        if not self.series_name:
            return ParseResult(
                series_name=None,
                matching_key=None,
                confidence=0.05,
                failure_reason=FailureReason.NO_SERIES_TITLE,
                **common,
            )

        confidence = 0.35
        if issue is not None:
            confidence += 0.25
            if c is not None and (c.anchored or c.count_flagged):
                confidence += 0.10
        elif issue_range is not None:
            confidence += 0.10
        if self.year is not None:
            confidence += 0.20
        confidence = round(min(confidence, 0.99), 2)

        return ParseResult(
            series_name=self.series_name,
            matching_key=matching_key(self.series_name),
            confidence=confidence,
            failure_reason=None,
            **common,
        )

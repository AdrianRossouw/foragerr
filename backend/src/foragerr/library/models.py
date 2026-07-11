"""ORM models for the library domain (FRG-SER-001..004, 008, 009, FRG-DB-008).

Uses the typed/sentinel-free column conventions from :mod:`foragerr.db.base`
throughout. Two deliberate deviations from design decision 1's terse column
list, both flagged for the orchestrator before merge:

- ``series.add_options`` — decision 1's column list omits it, but decision 3
  ("inserts the series row with ``add_options`` ... persisted on the row")
  requires it to exist on this table. Added here (nullable JSON TEXT,
  cleared by the add-flow once the chain completes) so change 3's flows
  package has a column to write to without a second migration.
- ``issues.issue_type`` — decision 1's column list omits it, but FRG-SER-002
  explicitly requires "issue type (regular/annual/special/TPB-content)" as
  a stored field. Added as a plain ``Text`` + CHECK constraint. This is
  deliberately a fresh, library-local vocabulary (``regular``/``annual``/
  ``special``/``tpb-content``) rather than a reuse of the parser's
  :class:`foragerr.parser.result.IssueClassification` (which has
  ``biannual`` instead of ``tpb-content`` and serves a different purpose:
  filename disambiguation, not the persisted issue-entity type).

No ``wanted`` column exists anywhere in this module (FRG-SER-004 decision
2) — "wanted" is computed by :func:`foragerr.library.repo.wanted_issues`
and asserted absent by a schema-inventory test.

Booleans use plain SQLAlchemy ``Boolean`` (there is no ``Strict*`` boolean
type in ``db.base``): SQLite's INTEGER-backed 0/1 boolean storage has no
sentinel-string collision risk the way TEXT/DATE/DATETIME columns do, so the
typed/sentinel-free discipline (FRG-DB-008) has nothing to guard against
here.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from foragerr.db.base import (
    Base,
    IssueNumberText,
    SentinelFreeText,
    StrictDate,
    StrictDateTime,
    StrictInteger,
)

#: Series lifecycle status (FRG-SER-001). Mylar's richer status set
#: collapses into this plus the `monitored` flag (design decision, D1).
SERIES_STATUSES = ("continuing", "ended")

#: Monitor-new-items policy (FRG-SER-007): whether issues discovered by a
#: refresh are created already monitored.
MONITOR_NEW_ITEMS_POLICIES = ("all", "none")

#: Issue entity type (FRG-SER-002) — see module docstring for why this is a
#: fresh vocabulary rather than a reuse of the parser's classification enum.
ISSUE_TYPES = ("regular", "annual", "special", "tpb-content")

#: Provenance of a trade-containment record (FRG-SER-020). ``declared`` = the
#: operator declared the range from the dialog (the only value v1 writes);
#: ``derived_description`` is reserved for a later feature that mines CV
#: description text into non-binding suggestions (the column exists now so that
#: lands without a migration).
ISSUE_COLLECTION_SOURCES = ("declared", "derived_description")

#: Library-import staging group lifecycle (FRG-IMP-023, m2-existing-library-
#: import design decision 2): ``proposed`` (scan staged it, a ComicVine match
#: may or may not be attached yet), ``confirmed`` (user accepted/overrode the
#: match), ``no_match`` (unparseable files or no plausible ComicVine match —
#: stays visible for manual resolution, mass import skips it), ``imported``
#: (execute registered every file), ``skipped`` (user deselected it).
LIBRARY_IMPORT_GROUP_STATES = (
    "proposed",
    "confirmed",
    "no_match",
    "imported",
    "skipped",
)


class RootFolderRow(Base):
    """A configured library root folder (FRG-SER-008)."""

    __tablename__ = "root_folders"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class SeriesGroupRow(Base):
    """A franchise group over series (FRG-SER-016) — a *display-only* grouping
    of successive ComicVine volumes of one title ("Batman (2011)",
    "Batman (2016)") under a single franchise header.

    A group is purely additive: it has NO files, monitor flag, or wanted
    state, and never participates in the derived-wanted choke point
    (``repo.wanted_issues``) or per-series statistics. It carries only a
    display ``title`` and the normalized ``grouping_key`` its members fold to.
    """

    __tablename__ = "series_groups"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    #: Display title — the franchise name shown in the grouped view. Defaults
    #: to the derived (year/``Vol N``-stripped) title of the first member;
    #: an operator rename sets ``manual_title`` so a re-derivation never
    #: relabels it. Plain ``Text``: internally derived by default, and the
    #: operator-rename path is a local edit, not externally-sourced free text
    #: (same rationale as ``series.matching_key``/``path``).
    title: Mapped[str] = mapped_column(Text, nullable=False)
    #: The normalized franchise key its members share, from
    #: :func:`foragerr.library.grouping.franchise_key` (``matching_key`` with
    #: trailing volume-year / ``Vol N`` designators stripped). Deterministic
    #: internal derivation — plain ``Text``, like ``series.matching_key``.
    grouping_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: Set once the operator renames the group (FRG-SER-017): a marker that the
    #: title is operator-owned. Auto-grouping never relabels an existing group
    #: regardless, so this is the durable record of the operator's intent.
    manual_title: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("grouping_key", name="uq_series_groups_grouping_key"),
    )


class SeriesRow(Base):
    """A watched series keyed by ComicVine volume ID (FRG-SER-001)."""

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    cv_volume_id: Mapped[int] = mapped_column(StrictInteger, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(SentinelFreeText, nullable=False)
    sort_title: Mapped[str] = mapped_column(SentinelFreeText, nullable=False)
    #: Computed via the shared `foragerr.parser.normalize.matching_key` — the
    #: one folding implementation (FRG-IMP-005). Plain `Text`, not
    #: `SentinelFreeText`: this is an internally-derived value, and a
    #: legitimate title like "None" folds to the sentinel-string-shaped
    #: "none"; normalizing it away would silently break matching for that
    #: series (SentinelFreeText is for externally-sourced free text, not
    #: deterministic internal derivations).
    matching_key: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(SentinelFreeText, nullable=True)
    start_year: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="continuing")
    monitored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    monitor_new_items: Mapped[str] = mapped_column(Text, nullable=False, default="all")
    format_profile_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("format_profiles.id"), nullable=False
    )
    root_folder_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("root_folders.id"), nullable=False
    )
    #: Internally constructed (root + safe_path_component template), never a
    #: raw external string — plain `Text`, matching `commands.payload`'s
    #: treatment of internally-generated structured/derived data.
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    cover_cached_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    #: "last-metadata-sync timestamp" (FRG-SER-001).
    refreshed_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    description_sanitized: Mapped[str | None] = mapped_column(SentinelFreeText, nullable=True)
    #: Add-time options (monitor strategy, search_on_add, ...) as canonical
    #: JSON; cleared once the add chain completes (decision 3, change 3).
    #: Plain `Text`: internally-generated JSON, not external free text.
    add_options: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: User-editable alternate search names / aliases as a canonical-JSON
    #: array of raw user strings (FRG-SRCH-003). Consumed by the search
    #: decision engine's release-to-library mapping (normalized at context
    #: build time). `None` means no aliases. User-maintained only — there is
    #: no external alias feed. Plain `Text`: internally-serialized JSON.
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Franchise group this series belongs to (FRG-SER-016) — a *display-only*
    #: link, additive and nullable. ``ON DELETE SET NULL`` so removing a group
    #: never cascades to (let alone deletes) its member series. ``None`` = the
    #: series is ungrouped (empty franchise key, or the operator detached it),
    #: rendered as its own franchise of one in the grouped view.
    series_group_id: Mapped[int | None] = mapped_column(
        StrictInteger,
        ForeignKey("series_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: The operator reassigned/detached this series (FRG-SER-017), so
    #: auto-derivation at refresh MUST NOT re-group over their choice. Cleared
    #: to return the series to auto-derivation on the next refresh.
    group_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Collected-edition (trade) book-type (FRG-SER-018) — a lowercased/
    #: underscored parser ``Booktype`` value (``tpb``/``gn``/``hc``/
    #: ``one_shot``); ``None`` = an ordinary single-issues run. Auto-derived
    #: from the title cue at add/refresh (unless ``booktype_locked``). This is
    #: DISPLAY/NAMING metadata ONLY: no book-type predicate ever reaches
    #: ``repo.wanted_issues()`` / ``series_statistics`` — trades and singles are
    #: independent tracks (FRG-SER-019). Plain ``Text``: an internally-derived
    #: enum value (from the title), not external free text, and ``None`` is the
    #: meaningful "single-issues" default, so no ``SentinelFreeText`` folding.
    #: Deliberately distinct from the issue-level ``IssueRow.issue_type``
    #: vocabulary, which types an *issue* and DOES feed the pull matcher's guard.
    booktype: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The operator set the book-type explicitly (FRG-SER-018), so
    #: auto-derivation at refresh MUST NOT re-derive over their choice (mirrors
    #: ``group_locked`` / FRG-SER-017). Cleared to return the series to
    #: auto-derivation on the next refresh.
    booktype_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    issues: Mapped[list["IssueRow"]] = relationship(
        back_populates="series", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(f"status IN {SERIES_STATUSES!r}", name="status_valid"),
        CheckConstraint(
            f"monitor_new_items IN {MONITOR_NEW_ITEMS_POLICIES!r}",
            name="monitor_new_items_valid",
        ),
        Index("ix_series_matching_key", "matching_key"),
        Index("ix_series_root_folder_id", "root_folder_id"),
        Index("ix_series_series_group_id", "series_group_id"),
    )


class IssueRow(Base):
    """One ComicVine issue of a watched series (FRG-SER-002)."""

    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("series.id", ondelete="CASCADE"), nullable=False
    )
    cv_issue_id: Mapped[int] = mapped_column(StrictInteger, nullable=False, unique=True)
    #: TEXT verbatim — `1`, `1.5`, `1.MU`, `½` all round-trip unmangled
    #: (FRG-SER-002, FRG-DB-008). Nullable: ComicVine occasionally omits it.
    issue_number: Mapped[str | None] = mapped_column(IssueNumberText, nullable=True)
    #: Persisted total-order sort key from `foragerr.library.ordering`
    #: (reuses `foragerr.parser.ordering.sort_key`) — see that module for
    #: the fixed-width sortable-string encoding.
    ordering_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(SentinelFreeText, nullable=True)
    cover_date: Mapped[dt.date | None] = mapped_column(StrictDate, nullable=True)
    store_date: Mapped[dt.date | None] = mapped_column(StrictDate, nullable=True)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False, default="regular")
    monitored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    #: When a series refresh last fetched this issue's per-issue person credits
    #: from the ComicVine issue detail endpoint (FRG-CRTR-001/002). ``None`` =
    #: credit-needing (never fetched, or a legacy row predating migration 0017);
    #: the refresh fetch phase fetches unstamped issues newest-first up to the
    #: ``credits_fetch_per_refresh`` bound and stamps this — INCLUDING when the
    #: issue legitimately has zero credits — so a covered issue is never
    #: re-fetched. Re-fetching a stamped issue to pick up later CV credit edits
    #: is an explicit non-goal (a future mechanism may clear the stamp).
    credits_fetched_at: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )

    series: Mapped[SeriesRow] = relationship(back_populates="issues")
    files: Mapped[list["IssueFileRow"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(f"issue_type IN {ISSUE_TYPES!r}", name="issue_type_valid"),
        Index("ix_issues_series_id", "series_id"),
        Index("ix_issues_series_ordering", "series_id", "ordering_key"),
        # Partial index mirroring migration 0017 — the credit-needing lookup
        # (``WHERE credits_fetched_at IS NULL``) the refresh fetch phase runs.
        Index(
            "ix_issues_credits_needed",
            "credits_fetched_at",
            sqlite_where=text("credits_fetched_at IS NULL"),
        ),
    )


class IssueFileRow(Base):
    """An on-disk file matched to an issue (FRG-SER-002; scanned by change 1,
    consumed/extended by change 6's import pipeline).

    Presence of a row here — not a status column — is what makes an issue
    "have a file"; the derived `wanted_issues()` query is defined purely by
    the *absence* of a matching row (FRG-SER-004).
    """

    __tablename__ = "issue_files"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    #: Internally-constructed on-disk path (scan-discovered or import-
    #: written) — plain `Text`, one row per physical file.
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    size: Mapped[int] = mapped_column(StrictInteger, nullable=False)
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    #: The file's `(fN)` fixed-release marker revision as parsed at import
    #: time (FRG-PP-014). ``None`` = unfixed, or a legacy/scan row predating
    #: the column — the duplicate evaluation then falls back to parsing the
    #: stored basename. Persisted here because renaming strips the marker
    #: from the on-disk name, which would otherwise evaporate the
    #: fixed-releases-always-win guarantee for future duplicate contests.
    fix_revision: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    #: Number of image "pages" in the archive, cached for OPDS-PSE ``pse:count``
    #: (FRG-OPDS-009). Set at import from ``ArchiveReport.image_count`` for a
    #: listable archive; ``None`` = not yet computed (legacy/scan row) or an
    #: unlistable archive (CBR without ``rarfile``, corrupt/hostile container).
    #: A ``None`` value is resolved lazily on first OPDS access and written back;
    #: a size-mismatch against the on-disk file forces a recompute.
    page_count: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)

    issue: Mapped[IssueRow] = relationship(back_populates="files")

    __table_args__ = (Index("ix_issue_files_issue_id", "issue_id"),)


class LibraryImportGroupRow(Base):
    """One staged library-import group: the files of one would-be series under
    a scanned root folder, keyed by the parser's shared ``matching_key``
    normalization (FRG-IMP-023, m2-existing-library-import design decision 2).

    Persisted — not in-memory like the manual-import listing — so the review
    survives a restart and a 2000-file scan is not redone per page load. A
    re-scan of the root atomically replaces its groups (carrying confirmed /
    skipped decisions forward for groups whose ``matching_key`` persists).
    """

    __tablename__ = "library_import_groups"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    #: The shared normalized series key the group's files parsed to (or the
    #: folder-name fallback for unparseable groups). Internally derived —
    #: plain ``Text`` for the same reason as ``series.matching_key``.
    matching_key: Mapped[str] = mapped_column(Text, nullable=False)
    root_folder_id: Mapped[int] = mapped_column(
        StrictInteger,
        ForeignKey("root_folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: The group's on-disk folder (the common parent of its files) — used as
    #: the series ``path_override`` for an in-place import. Internally
    #: constructed from the walk, never raw user input.
    folder: Mapped[str] = mapped_column(Text, nullable=False)
    #: Canonical-JSON array of ``{"path", "size"}`` objects — the group's
    #: unmapped files as of the scan. Plain ``Text``: internal JSON.
    files: Mapped[str] = mapped_column(Text, nullable=False)
    #: Mean parse confidence over the group's files (0.0–1.0). Plain ``Float``:
    #: like ``Boolean``, SQLite REAL storage has no sentinel-string collision
    #: risk for the typed/sentinel-free discipline to guard against.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    proposed_cv_volume_id: Mapped[int | None] = mapped_column(
        StrictInteger, nullable=True
    )
    confirmed_cv_volume_id: Mapped[int | None] = mapped_column(
        StrictInteger, nullable=True
    )
    #: Display details of the currently proposed/confirmed volume, captured at
    #: proposal/override time so the review UI renders name/poster/year/
    #: publisher without a ComicVine round-trip per group (FRG-UI-015).
    proposal_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_start_year: Mapped[int | None] = mapped_column(
        StrictInteger, nullable=True
    )
    proposal_publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")
    #: Human-visible outcome/annotation (why no match was proposed, the
    #: import-outcome summary, ...). Never silent (FRG-IMP-023 scenario 4).
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Structured per-file blocked reasons from the last execute attempt, as a
    #: canonical-JSON list of strings (``"[]"`` when nothing blocked) — the
    #: review UI renders these as a real list; ``message`` stays the human
    #: summary. Plain ``Text``: internally-serialized JSON.
    rejections: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    scanned_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"state IN {LIBRARY_IMPORT_GROUP_STATES!r}",
            name="library_import_state_valid",
        ),
        UniqueConstraint(
            "root_folder_id", "matching_key", name="uq_library_import_root_key"
        ),
        Index("ix_library_import_groups_root_folder_id", "root_folder_id"),
    )


class IssueCollectionRow(Base):
    """One trade-containment record (FRG-SER-020): a single issue of a
    trade-typed series (one collected book, ``trade_issue_id``) collects a
    contiguous range of a ``target_series_id``'s issues.

    The range is stored as *copied ordering keys* (``start_ordering_key`` ..
    ``end_ordering_key``) — the same fixed-width sortable encoding
    ``IssueRow.ordering_key`` uses — rather than issue-id endpoints: keys are
    ``BETWEEN``-comparable in SQL and stay stable if ComicVine renumbers the
    volume. One row per contiguous sub-range, so a non-contiguous collection
    or a multi-series omnibus is several rows.

    This is a *display-only* side table (FRG-SER-020): NOTHING here ever
    reaches the derived-wanted choke point (``repo.wanted_issues``) or
    ``series_statistics`` — trades never suppress single-issue wanted state
    (extends FRG-SER-019). Coverage (Collected / Partial / Not collected) is a
    request-time read rollup over file presence within the range, never a
    stored column. Both FKs cascade on delete so removing the trade issue or
    the target series drops the dependent records and nothing else.
    """

    __tablename__ = "issue_collections"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    #: The collected book — one issue of a trade-typed series (FRG-SER-018).
    trade_issue_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    #: The single-issues (or other) series whose issues this book collects.
    target_series_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("series.id", ondelete="CASCADE"), nullable=False
    )
    #: Copied ``IssueRow.ordering_key`` bounds (inclusive). Internally-derived
    #: sortable encodings — plain ``Text``, like ``issues.ordering_key``.
    start_ordering_key: Mapped[str] = mapped_column(Text, nullable=False)
    end_ordering_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Human-readable label derived from the endpoint issues' verbatim issue
    #: numbers (``"#1–#6"``, or ``"#8"`` for a single-issue range). Internally
    #: derived — plain ``Text``.
    range_label: Mapped[str] = mapped_column(Text, nullable=False)
    #: Provenance (FRG-SER-020); v1 only ever writes ``declared``. Internally
    #: set enum value — plain ``Text``.
    source: Mapped[str] = mapped_column(Text, nullable=False, default="declared")
    #: Provenance confidence (0.0–1.0); ``declared`` records are ``1.0``. Plain
    #: ``Float``: SQLite REAL storage has no sentinel-string collision risk.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"source IN {ISSUE_COLLECTION_SOURCES!r}",
            name="issue_collections_source_valid",
        ),
        Index("ix_issue_collections_trade_issue_id", "trade_issue_id"),
        Index(
            "ix_issue_collections_target_series",
            "target_series_id",
            "start_ordering_key",
            "end_ordering_key",
        ),
    )

# Design: m2-manual-import

Grounded in the real M1/change-6 import machinery: `importer/{evidence,decisions,
pipeline,sources,context,fileops}.py`, `security/archives.py`,
`indexers/xml.py` (the single hardened XML site), `library/models.py`
(`SeriesRow.cv_volume_id`, `IssueRow.cv_issue_id`), and the
`InteractiveSearchOverlay` / queue frontend school. The governing constraint
throughout: **no parallel pipeline** — manual import, embedded read, and tagging
all extend the existing one-parser/one-decide/one-execute path.

## 1. Manual candidate source — one shape, two entry points

Add `ManualImportSource` to `importer/sources.py`. It produces the SAME neutral
`ImportCandidate[]` every other source produces; nothing downstream forks.

- **Blocked-download entry point** (`download_id` given): delegates to
  `CompletedDownloadSource(...).gather(...)` verbatim so remote-path mapping
  (FRG-PP-008), the latest grab-record lookup, and the download-id/grab hints are
  reused, not re-implemented. It then stamps `source_kind = SOURCE_MANUAL` and
  attaches per-file overrides (§2). A mapping-warning candidate is passed through
  unchanged — manual import still surfaces "add a remote-path mapping" rather than
  guessing a local path.
- **Arbitrary-folder entry point** (`path` given, no download): walks the folder
  with `matching.iter_archive_files(path, ctx.archive_extensions,
  max_depth=ctx.max_walk_depth)` — the identical bounded walk `RescanSource`
  uses — emitting unscoped candidates (`series_scope_id=None`,
  `source_kind=SOURCE_MANUAL`, no grab hints).

`SOURCE_MANUAL = "manual"` is a new provenance discriminator in
`importer/history.py` (data only). `_source_provenance` gains a manual branch for
the history `source` column; decision and file-op logic never read `source_kind`.

## 2. Override representation and injection — bypass mapping only

An override is per-file and minimal:

```python
@dataclass(frozen=True, slots=True)
class ManualOverride:
    series_id: int | None = None
    issue_id: int | None = None
    format: str | None = None   # e.g. "cbz" — feeds the upgrade check only
```

Carried on the candidate (`ImportCandidate.override: ManualOverride | None`,
defaulting `None` so the two M1 sources are untouched).

**Injection point — the reconciliation seam, ABOVE the decision specs.** The
override is treated as the top-priority reconciliation layer, conceptually seated
above `grab_record` in the confidence order (manual human intent > any parse). It
enters `reconcile()` as the first branch:

```
manual override > verified embedded CV id (§3) > [__issueid__] tag
                > grab hints > filename heuristic
```

A pinned `series_id`/`issue_id` is still validated against real rows
(`session.get(SeriesRow/IssueRow, ...)`, and — for a scoped context — the issue
must belong to the series); an override naming a non-existent or mismatched entity
is dropped, not trusted, and the file falls back to the heuristic (so a bad
override cannot fabricate a mapping). `format` overrides `ImportEvaluation.new_format`.

**What an override MAY bypass:** only `RemotePathMappedSpec` /
`MappedToIssueSpec` — i.e. the resolution of series+issue. It supplies the answer
those specs check for.

**What an override MUST NOT bypass — these still bind, unchanged:**
`ArchiveValidSpec` (a corrupt/encrypted archive with a perfect manual mapping
still routes to FAILED), `JunkFilterSpec` (below-floor sample still blocked),
`FreeSpaceSpec` (no space → still blocked), `AlreadyImportedSpec`, and
`UpgradeAllowedSpec` (a non-upgrade over an existing file is still blocked unless
it genuinely outranks). This is enforced structurally: the override only changes
what `reconcile()`/`build_evaluation()` resolve for `(series_id, issue_id,
new_format)`; `decide()` then runs the FULL `default_specs()` set over the
resulting `ImportEvaluation` exactly as automatic import does. There is no
"force" flag and no skip path.

## 3. Embedded ComicInfo read (FRG-IMP-024)

New module `metadata/comicinfo.py`, read half.

**Member selection & caps.** Read is I/O, so it happens in the `build_evaluation`
stage (which already does archive I/O via `inspect_archive`), NOT in the pure
`aggregate()`. Only after `inspect_archive` returns `ok` do we look for the
metadata member: the single root-level entry whose name equals `ComicInfo.xml`
case-insensitively (`info.filename.lower() == "comicinfo.xml"`, no path
separator). Selection uses the `zipfile.ZipInfo` list already vetted by
`inspect_archive` — the member's **declared** `file_size` is checked against a
dedicated small cap `COMICINFO_MAX_BYTES = 1 MiB` BEFORE any read; an oversized
or absent member yields no embedded metadata (skipped, logged), never an error.
The member is read into memory via `ZipFile.read(name)` bounded by that cap — no
extraction to disk, respecting `inspect_archive`'s never-extract contract. CBR/CB7
embedded read is best-effort only where the container was fully `listed`; magic-
only containers yield nothing.

**Hardened parse site (FRG-SEC-002 single-site rule).** ComicInfo XML is
untrusted. `comicinfo.py` MUST NOT construct any XML parser — the static guard
test (`test_no_unhardened_xml_parser_constructed_in_src`) forbids it. Instead,
generalize `indexers/xml.py`'s `parse_indexer_xml` to a neutral
`parse_untrusted_xml(data, *, max_bytes=...)` (keeping `parse_indexer_xml` as a
thin alias so indexer callers/tests are undisturbed) and call THAT from
`comicinfo.py`. All defusedxml hardening (`forbid_dtd/entities/external` + byte
cap) is inherited unchanged; `indexers/xml.py` stays the ONE sanctioned parser
construction site.

**Parse-degraded evidence layer.** A malformed/hostile ComicInfo (the hardened
parser raises `IndexerMalformedError`, or a field is unparseable) is caught inside
`comicinfo.py` and returned as an empty/partial `EmbeddedMetadata` with a
`parse_error` note — it degrades to "no embedded evidence", never propagates, and
never fails the candidate. The pipeline continues on filename evidence.

**Verified-embedded-id trust rule.** The embedded ComicVine issue id lives in the
`cv_issue_id` namespace (distinct from the internal `[__issueid__]` tag, which is
`IssueRow.id`). We read it from the ComicInfo `<Web>` CV URL (`4000-<id>`) or a
`<Notes>` "[Issue ID <id>]" fallback. An embedded id is **VERIFIED** — and only
then BEATS the filename parse — when ALL hold:
1. it parses to an int;
2. it resolves to an existing `IssueRow` via `cv_issue_id` lookup (present in the
   library — an id for an issue we do not have is not trusted);
3. in a scoped context (rescan / a series-pinned manual folder), the resolved
   issue belongs to the in-scope series.

A verified id becomes the resolved `(series_id, issue_id)` directly in
`reconcile()`, ahead of the filename heuristic (baseline: "prefer a verified
embedded ID"). An **unverified** id (unresolvable, or conflicting with a strong
filename series match) does NOT silently win: the file resolves by the normal
heuristic and the conflict is recorded on the evidence provenance so it surfaces
as a review/blocked item rather than a silent mis-file (baseline: "conflicting-ID
case surfaces as a review item"). Provenance vocabulary gains
`PROV_COMICINFO = "comicinfo"`.

## 4. ComicInfo write on import (FRG-PP-017)

New write half in `metadata/comicinfo.py`. Content is built from the matched
library records — never from untrusted input:
`Series`=`SeriesRow.title`, `Number`=`IssueRow.issue_number`,
`Title`=`IssueRow.title`, `Volume`=series volume/`start_year`,
`Year/Month/Day`=`IssueRow.cover_date`, `Publisher`=`SeriesRow.publisher`,
`Web`=CV issue URL from `IssueRow.cv_issue_id`, plus story-arc fields where known.
Serialized with the stdlib `ElementTree` **writer** (`Element` +
`ElementTree.write`) — the guard test forbids only *parser* construction
(`fromstring`/`parse`/`XMLParser`), so building an element tree for output is
allowed.

**Safe cbz rewrite — stream to temp, atomic replace, never extract.**

- **Gate honestly on inspection.** Rewrite runs ONLY when: tagging enabled (§5)
  AND the placed file is a `.cbz` (zip) AND the candidate's `ArchiveReport` from
  `build_evaluation` has `safe_to_extract=True`. `safe_to_extract` is `True` only
  for a fully-`listed` zip whose every member passed the name/symlink/nesting/size
  vetting — so we never rewrite an archive whose members were not vetted, and
  never rewrite a magic-only cbr/cb7 (those are read-only here; a non-goal for
  write). If the archive did not pass, tagging is skipped with a note; the import
  still succeeds.
- **Streaming member copy (no disk extraction).** Open the source zip, open a
  temp zip created via `tempfile.mkstemp(dir=<library file's own dir>)` (same
  directory → atomic `os.replace`, mirroring `fileops._copy_verify_delete`
  discipline). For each source member: RE-CHECK the name with
  `security.archives._unsafe_member_name` (defense in depth even though
  `inspect_archive` already vetted it — a hostile name is skipped/aborts), then
  copy bytes member-to-member via streamed `read`/`writestr` bounded by the same
  per-member cap; drop any existing `ComicInfo.xml`; append the freshly built
  `ComicInfo.xml`.
- **Atomic replace.** `os.fsync` the temp, then `os.replace(temp, placed)` — an
  in-place mutation is never performed; a reader never sees a half-written cbz.
- **Rewrite failure leaves the original intact.** Any exception unlinks the temp
  zip (`_suppress_missing`) and leaves the placed file byte-identical. Because
  PP-017 requires tagging failures NOT to fail the import, the failure is caught,
  the file lands untagged, and a `comicinfo_tag_failed` warning history event is
  recorded. Tagging happens AFTER `place_file` succeeds and AFTER the
  `issue_files` row/`imported` event, so a tagging failure can never unwind a
  completed import.

## 5. Tagging toggle config field

`config.py Settings`: `comicinfo_tag_on_import: bool = Field(default=False, ...)`
(OFF by default per baseline). Wired into `importer/context.py` via a new
`ImportContext.comicinfo_tag_enabled: bool = False` seam and a `_SETTINGS_TO_CTX`
entry `"comicinfo_tag_on_import": "comicinfo_tag_enabled"`. When false, execute
skips the rewrite entirely and the archive is untouched.

## 6. API shapes (FRG-API-015)

New router `api/manual_import.py`, mounted under `/api/v1`, same envelope/error
conventions (`ApiError`, `CommandResource`, camelCase Pydantic) as `rename.py`.

- `GET /api/v1/manual-import?path=<abs>` **or** `?downloadId=<id>` → plain list
  (bounded, like rename preview) of:
  ```
  { path, name, size, folder,
    approved: bool, rejections: string[],           # verbatim decision reasons
    suggestedSeriesId, suggestedIssueId, format,     # would-be reconcile result
    embedded: { comicInfoPresent, cvIssueId, verified } }  # IMP-024 read
  ```
  Read-only: runs `gather → aggregate → build_evaluation → decide` per candidate
  and reports, touching no disk beyond inspection. `path` is resolved through
  `security.paths.safe_join`/validation; unreadable path → 400/404 `ApiError`.
- `POST /api/v1/manual-import` body `{ files: [{ path, seriesId, issueId,
  format? }] }` → validates and enqueues a `manual-import` command onto the
  pp-pool (the same exclusivity-guarded transport `rename-series` uses), returning
  `201 CommandResource`. The command builds `ManualImportSource` +
  `ManualOverride`s and drives `import_candidate` — the outcome (IMPORTED /
  BLOCKED / FAILED, with reasons) is reported through history exactly as automatic
  import. Blocked/failed files stay listed for another attempt.

## 7. Overlay UX skeleton (FRG-UI-014)

`frontend/src/screens/queue/ManualImportOverlay.tsx`, modeled on
`InteractiveSearchOverlay` (`Modal`, per-row decision chip + `Popover` of verbatim
rejection reasons, no client re-sorting). Reachable two ways: (a) a "Manual
import" action on `ImportBlocked` queue rows (passes `downloadId`); (b) a path
picker entry (passes `path`). Each candidate row: filename/size, a decision chip
(approved / blocked-with-reasons), and inline override controls — series picker,
issue picker (scoped to chosen series), format select — pre-filled from the
`suggested*` fields and, when `embedded.verified`, badged "from ComicInfo". A
footer "Import N selected" posts the corrected mappings and, on the returned
command completing, invalidates the queue query. Blocked rows that still fail
after submit re-render with their new reasons.

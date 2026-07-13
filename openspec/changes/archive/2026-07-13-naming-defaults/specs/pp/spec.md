# pp — naming-defaults deltas

## ADDED Requirements

### Requirement: FRG-PP-020 — Non-destructive defaults

A fresh install SHALL NOT modify adopted files: `rename_enabled` defaults to off, and the shipped default file-naming template SHALL contain no internal-identifier tokens ({IssueId}). Persisted configuration SHALL always take precedence over shipped defaults, so a default change never alters the effective behavior of an existing install.

#### Scenario: Fresh install adopts a library untouched

- **WHEN** a fresh install (no persisted config) runs a library import in `in_place` mode
- **THEN** every adopted file keeps its exact original path and filename, byte-for-byte.

#### Scenario: Fresh-install default template carries no internal ids

- **WHEN** a fresh install renders a name with renaming explicitly enabled and the shipped default template
- **THEN** the rendered name is `{Series Title} {Issue Number:000} ({Year})` — no `[__{IssueId}__]` or other internal-row-id token appears.

#### Scenario: Existing installs keep their configured behavior

- **WHEN** a config file persisted under an earlier release (e.g. `rename_enabled: true` with the old tagged template) is loaded by a build shipping the new defaults
- **THEN** the persisted values win unchanged — renaming stays enabled with the old template until the operator edits it.

## MODIFIED Requirements

### Requirement: FRG-PP-003 — Grab reconciliation by download ID

Every grab SHALL record a history row keyed by the download-client ID, and completed downloads SHALL be reconciled to their grabbed issues primarily by that ID, falling back to parsing the download title/folder name (via the single IMP parser, including the `[__issueid__]` tag for DDL) only when no history match exists. A parsed issue-id tag SHALL be honored only when it does not disagree with the filename parse: when the tag's resolved issue belongs to a different series matching key than the parsed filename, or carries an issue identity the parsed filename contradicts, resolution SHALL fall through to the grab-history/filename heuristics on every import path — scoped and unscoped alike.

- **Milestone**: M1 (guard universalized: naming-defaults)
- **Source**: SA §4.3 ("DownloadId is the join key for the entire rest of the pipeline"); MFS §4 snatch↔download handshake (nzblog analogue); SA §8 Downloading bullet 2.
- **Notes**: Replaces Mylar's name-normalized `nzblog` matching (AltNZBName fragility) with Sonarr's ID join; the parse fallback covers Mylar's `mode='outside'` case. The universal disagree-guard closes the stale-tag hazard: internal ids embedded in filenames by an earlier database are meaningless after a reinstall and must never override a parseable name.

#### Scenario: Download-ID match survives an unparseable name

- **WHEN** a completed download has a grab_history row for its download_id but its folder/title is unparseable
- **THEN** it reconciles to the grabbed issue via the download_id join and imports correctly.

#### Scenario: Parser fallback when no history match

- **WHEN** a completed download has no grab_history match for its download_id
- **THEN** the pipeline falls back to parsing the title/folder name via the single change-2 parser, and lands the item in import_blocked if that too fails to resolve.

#### Scenario: Issue-id tag short-circuits to direct lookup

- **WHEN** a download name carries a `[__issueid__]` tag (DDL convention) and the rest of the name is unparseable or agrees with the tagged issue
- **THEN** reconciliation short-circuits to a direct issue lookup by that id.

#### Scenario: Stale tag never overrides a disagreeing filename parse

- **WHEN** a file name carries a `[__issueid__]` tag whose resolved issue disagrees with the filename parse (different series matching key, or a contradicted issue identity) on any import — scoped or unscoped
- **THEN** the tag is discarded for resolution and the pipeline proceeds via grab-history/filename heuristics exactly as if no tag were present.

### Requirement: FRG-PP-009 — Token-based renaming engine

File naming SHALL be driven by a configurable token template supporting at minimum {Series Title}, {Series CleanTitle}, {Volume}, {Year}, zero-padded decimal-safe {Issue:000}, {Issue Title}, {Classification} (Annual/Special rendering), {Booktype}, {Release Group}, {IssueId}, and {CvIssueId} tokens — with token-case controlling output case, illegal-character replacement policy, byte-aware truncation to path-length limits, and a switch to disable renaming (keep original filename) entirely. {CvIssueId} SHALL render the ComicVine issue id in a form the IMP parser recognizes into the existing cv-issue-id evidence namespace, making it the durable (reinstall-surviving) identity tag.

- **Milestone**: M1 ({CvIssueId}: naming-defaults)
- **Source**: SA §5.4 (FileNameBuilder token system, comic token list); MFS §4 Moving/renaming (FILE_FORMAT tokens, zero-level padding, lowercase/space options); MFP §2.16 (round-trip contract: renamed output must re-parse).
- **Notes**: Round-trip requirement: every rename template output in the test matrix must re-parse via the IMP parser to the same issue identity (this closes Mylar's four-way normalization divergence). Issue rendering uses the single ordering/normalization implementation from IMP. {IssueId} (internal row id) is retained for compatibility with already-stamped libraries but appears in no shipped default.

#### Scenario: Tokens, padding, and case render as specified

- **WHEN** a name is rendered from a token template using {Series Title}, {Issue Number:000}, {Year}, {Release Group}, {Classification}, and [__{IssueId}__]
- **THEN** padding specifiers, illegal-character replacement, byte-aware truncation, and case control are all applied to the output; and a decimal issue such as `15.5` renders decimal-safe under `{Issue:000}`.

#### Scenario: Optional groups dropped when empty

- **WHEN** an optional-group segment references tokens that are empty for the issue
- **THEN** that group is dropped entirely from the rendered name.

#### Scenario: Round-trip contract holds over the corpus

- **WHEN** any rendered name is re-parsed by the single change-2 parser (property-tested over the corpus identities)
- **THEN** it yields the same series matching key and issue identity (equal ordering key) as the source record.

#### Scenario: Rename can be disabled

- **WHEN** renaming is disabled
- **THEN** the file imports under its original filename.

#### Scenario: CvIssueId renders durable identity and round-trips

- **WHEN** a name is rendered from a template containing {CvIssueId} for an issue with a known ComicVine id
- **THEN** the rendered tag re-parses into the cv-issue-id evidence namespace and resolves to the same issue on a database whose internal row ids differ (reinstall simulation).

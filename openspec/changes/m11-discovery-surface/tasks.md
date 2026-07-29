# m11-discovery-surface — tasks

## 1. Cover-proxy rule shape (FRG-META-021)

- [x] 1.1 Replace `COVER_HOSTS` frozenset with allowlist rules (host,
      subdomain policy, optional required path prefix); one shared
      evaluator (single-decode, dot-segment/backslash refusal,
      directory-boundary prefix) used by request check and `_hop_check`;
      add the LOCG `s3.amazonaws.com` exact-host `/comicgeeks/` rule;
      update the module's CV-specific top comment
- [x] 1.2 Tagged abuse tests (`@pytest.mark.req("FRG-META-021")`):
      LOCG-prefix URL proxies; other-bucket path, prefix lookalike
      (`/comicgeeks-evil/`), dot-segment + percent-encoded traversal,
      bucket-subdomain (`comicgeeks.s3.amazonaws.com`) all 400 before
      fetch; redirect hop to off-rule target refused; existing CV
      scenarios still green

## 2. Enrichment ingestion (FRG-PULL-011)

- [x] 2.1 Migration 0029: nullable `cover_url`, `description`, `upc`,
      `creators`, `characters` on `pull_entries`; ORM `PullEntryRow` +
      `ParsedPullEntry` fields
- [x] 2.2 `_parse_entry` reads `covers`/`description`/`creators`/
      `characters`/`upc`: primary-else-first cover, query/fragment
      stripped, validated fail-closed through the proxy's rule
      evaluator; sanitization + length/count caps on text/lists;
      `replace_week` stores the new fields
- [x] 2.3 Tagged tests: idempotent enrichment storage w/ volatile
      cache-busters, hostile/placeholder cover URLs fail closed,
      oversized + bidi text bounded, schema-inventory guard extended
      (no status column)

## 3. Lookup by volume id (FRG-API-026)

- [x] 3.1 `GET /series/lookup/volume/{cv_volume_id}` reusing
      `ComicVineClient.get_volume` + the term lookup's auth/error
      mapping; interactive lane; structured 404-class for unknown ids
- [x] 3.2 Tagged tests: known id → one candidate w/ `have_it`; unknown
      id vs transport failure distinguishable; 503 auth contract; no
      key leakage

## 4. Pull API + Calendar (FRG-PULL-008, FRG-UI-042)

- [x] 4.1 `api/pull.py` resource + frontend types carry enrichment
      fields (coverUrl, description, creators, characters, upc)
- [x] 4.2 CalendarScreen: universal add affordance (unlinked +
      not-in-library via title-index seam), CV-id-first navigation
      state, inline "New" badge + debut filter, strip removed;
      AddSeries resolves `prefillCvVolumeId` to a preselected
      candidate, degrades to term search with notice
- [x] 4.3 CalendarScreen covers: lazy thumbnails via
      `candidateCoverUrl`, spine fallback on absent/error; entry
      detail surface (description, creators w/ roles, characters,
      UPC; absent fields omitted)
- [x] 4.4 Tagged vitest suites (IDs in test names): FRG-PULL-008
      scenarios (any-unmatched add, id-first routing, in-library
      suppression, badge/filter, no-auto-add), FRG-UI-042 scenarios
      (proxy cover render, spine fallback, detail surface, no CV
      requests)

## 5. Security + docs (FRG-PROC-006 / -011)

- [x] 5.1 `docs/security/threat-model.md` dated delta (shared-S3
      allowlist rule, second untrusted party's bytes, ingest as trust
      boundary); `docs/security/risk-register.md` RISK-025 + RISK-039
      extensions
- [x] 5.2 `docs/manual/user/web-ui.md` Calendar section rewrite
      (add-from-anywhere, id-first add, badges replace strip, covers,
      detail surface)

## 6. Verification

- [x] 6.1 Full backend suite (xdist) + frontend suite (serialized,
      never concurrent with pytest) green; `tools/soup_check.py` exit 0
- [x] 6.2 e2e `bash e2e/run.sh` green (calendar unconfigured-week +
      a11y sweep still pass with the new card layout)
- [x] 6.3 Traceability matrix regen picks up the four IDs; commit
      trailers cite them

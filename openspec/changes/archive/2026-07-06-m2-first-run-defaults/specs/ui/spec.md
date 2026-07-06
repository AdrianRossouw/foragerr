# ui — delta for m2-first-run-defaults

## ADDED Requirements

### Requirement: FRG-UI-020 — Settings: General with ComicVine metadata credential

The UI SHALL provide a **Settings → General** section (a nav item and route, using
the bespoke single-form config-singleton pattern, not the provider list+modal
machinery) that lets the user set the ComicVine API key via a **masked, write-only**
field and verify it with a **Test** connectivity button that mirrors the indexer
test-button pattern. The field SHALL never display the stored key: when a key is
configured it shows a "currently set" indicator (placeholder dots) and a blank save
keeps the stored value. When the key's source is the environment
(`FORAGERR_COMICVINE_API_KEY`, as reported by the settings resource), the field
SHALL render in a **read-only, environment-managed** state with guidance to edit the
environment variable, instead of a silently-ineffective editor. The Test button
SHALL report connectivity success or failure without revealing the key. The
ComicVine credential-failure guidance shown on the Add Series (and existing-library
import) screens SHALL link into this section, so "check Settings" routes to a real
place to fix the key.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §4 (Settings → General; provider test
  buttons); mylar-feature-surface.md §7 (config surface); m2-first-run-defaults
  (the ComicVine key gets a UI home and the AddSeries error a real destination);
  FRG-API-018 (the resource this screen reads/writes/tests), FRG-UI-008/FRG-IDX-003
  (the schema-driven form + connectivity-test pattern reused), FRG-UI-009 (the
  masked write-only secret-field pattern), FRG-UI-005 (the Add Series screen whose
  credential error links here).
- **Notes**: Placement is General (not Metadata): the Sonarr-shaped home for
  app-wide config singletons and future global settings; Metadata was considered and
  rejected as narrower. The screen follows the MediaManagement save-bar pattern with
  the SchemaForm password widget for the key (write-only — never echoes the stored
  value, `••••••••` when set, omits a blank field on save) and a Test mutation on
  the `useTestProvider` pattern hitting the connectivity endpoint. The env-read-only
  state is driven purely by the resource's reported `source`, so the operator never
  types into a field the environment shadows. The Add Series / Library Import prose
  gains a router `<Link>` exactly like the existing no-root-folders link; the
  credential classification stays on the machine-readable `field="comicvine_api_key"`
  discriminator, not message prose.

#### Scenario: The ComicVine key field is masked and write-only

- **WHEN** the Settings → General section renders with a ComicVine key already
  configured
- **THEN** the key field shows a "currently set" masked indicator and never renders
  the stored key value into the DOM, and saving the form with the field left blank
  keeps the stored key rather than clearing it

#### Scenario: Saving a key persists it and the Test button confirms connectivity

- **WHEN** the user enters a ComicVine API key and saves, then presses Test
- **THEN** the key is submitted to the settings resource (persisted and applied
  live), and the Test button reports connectivity success or failure without
  displaying the key

#### Scenario: An environment-supplied key renders read-only with guidance

- **WHEN** the settings resource reports the ComicVine key source as `environment`
- **THEN** the key field renders in a read-only, environment-managed state with
  guidance to change the `FORAGERR_COMICVINE_API_KEY` environment variable, rather
  than an editable field whose save the environment would shadow

#### Scenario: The Add Series credential error links to this section

- **WHEN** an Add Series (or existing-library import) ComicVine lookup fails on a
  missing/invalid key and the actionable credential-error state renders
- **THEN** its "check Settings" guidance is a link that navigates to the Settings →
  General ComicVine credential section, classified by the
  `field="comicvine_api_key"` discriminator rather than message prose

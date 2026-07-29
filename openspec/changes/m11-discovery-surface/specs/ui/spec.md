# ui — delta for m11-discovery-surface

## ADDED Requirements

### Requirement: FRG-UI-042 — Calendar covers and enrichment detail

The Calendar screen (FRG-UI-018) SHALL render each pull entry's stored
cover as a lazy-loaded thumbnail served same-origin through the
authenticated cover proxy (FRG-META-021), falling back to the existing
publisher-tinted spine when the cover is absent or fails to load —
never a broken image. An entry detail surface SHALL expose the stored
enrichment — description, creators (role and name), characters, and
UPC — omitting absent fields. Rendering pull imagery and enrichment
SHALL issue no ComicVine requests: the Calendar's imagery is
budget-free by design (FRG-META-022's lanes are not involved).

- **Milestone**: M11 (m11-discovery-surface).
- **Source**: rig finding #17 (Calendar covers never built) + the
  2026-07-23 cover-URL facts; FRG-PULL-011 supplies the stored data.
- **Notes**: First cover-proxy consumer outside the add/import
  pickers, via the existing same-origin URL helper. Lazy loading keeps
  concurrent proxy fetches bounded to the viewport; the browser cache
  honors the proxy's cache headers. Detail surface form (popover vs
  expando) is an implementation call.

#### Scenario: Covers render through the authenticated proxy

- **WHEN** the viewed week contains entries with stored cover URLs
- **THEN** each card's thumbnail loads lazily from the same-origin
  proxy endpoint with the cover URL as its encoded parameter, under
  the unchanged self-contained CSP

#### Scenario: Absent or failing covers degrade to the spine

- **WHEN** an entry has no stored cover, or its proxy fetch errors
- **THEN** the card renders the existing publisher-tinted spine with
  no broken-image artifact

#### Scenario: Entry detail exposes enrichment, omitting the absent

- **WHEN** the user opens an entry's detail surface for an entry with
  a description and creators but no characters or UPC
- **THEN** the description and creators (with roles) render and the
  absent fields are omitted rather than shown empty

#### Scenario: A rendered week spends no ComicVine budget

- **WHEN** a week's Calendar renders covers and enrichment for its
  entries
- **THEN** no ComicVine API request is issued on behalf of pull
  imagery or enrichment

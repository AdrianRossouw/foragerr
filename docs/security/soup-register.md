# SOUP Register (FRG-PROC-012)

SOUP = Software of Unknown Provenance (IEC 62304 terminology): third-party software
that foragerr incorporates but did not develop and does not control the release
process of. This register lists every **direct** runtime and development/test
dependency declared in the backend and frontend manifests, so that a dependency
change is a visible, reviewed event rather than a silent transitive drift.

**Scope.** Direct dependencies only — the entries a manifest (`backend/pyproject.toml`
`[project.dependencies]` / `[dependency-groups].dev`, and, once it exists,
`frontend/package.json` `dependencies` / `devDependencies`) declares explicitly.
Transitive dependencies are not tracked here; the lockfiles (`uv.lock`,
`package-lock.json` once present) remain the authoritative pin of the full
resolved tree, per FRG-PROC-012's non-goals.

**Frontend.** `frontend/package.json` was created by the `m1-ui-opds-deploy` change.
Its 5 runtime and 11 development/test dependencies were added to this register in
that same change, per the "dependency added or upgraded" scenario.

**Anomaly-review methodology.** This project has no network access from its
development sandbox and no automated CVE-scanning service (see the change-8
non-goals). The "known-anomaly review" column below is an **initial,
knowledge-based review** performed from the reviewing agent's training knowledge of
each project's maintainer changelogs, published security advisories, and CVE
history as of the review date — not a live database query. Each entry states the
date of that review and its outcome. Anomaly reviews should be refreshed (and the
date/outcome updated) whenever the pinned version constraint changes, and
periodically re-examined with live tooling (e.g. `pip-audit`, `npm audit`,
GitHub Dependabot) once the project has network-connected CI, at which point this
methodology note should be updated to reflect that.

## Runtime SOUP items (backend)

| Name | Version constraint | Source | Intended purpose | Requirements/subsystems supported | License | Known-anomaly review |
|---|---|---|---|---|---|---|
| fastapi | `>=0.115` | PyPI | ASGI web framework; defines and serves the REST API (routing, request/response models, OpenAPI schema generation) | FRG-API-* (REST API layer) | MIT | 2026-07-05: no relevant known anomalies at review date. Pinned floor (0.115) postdates the Starlette/python-multipart content-type ReDoS advisories (GHSA-qj7f-devc-hxxx / CVE-2024-24762 family, fixed upstream by FastAPI 0.109.1); no CVE known against FastAPI itself at this constraint. |
| pydantic | `>=2.7` | PyPI | Data validation and settings/model layer underlying API request/response schemas and internal domain models | FRG-API-*, FRG-DEP-003 (config validation), most typed domain models | MIT | 2026-07-05: no relevant known anomalies at review date. Pydantic v2's Rust-based `pydantic-core` has no outstanding CVEs known to the reviewer for the 2.7+ line. |
| pydantic-settings | `>=2.3` | PyPI | Environment-variable/config-file settings loading and precedence (`FORAGERR_*` env vars, `/config/config.yaml`) on top of pydantic models | FRG-DEP-003 (configuration via environment variables and config file), FRG-DEP-005 (secrets never in image/repo) | MIT | 2026-07-05: no relevant known anomalies at review date. |
| sqlalchemy | `>=2.0` | PyPI | ORM and SQL toolkit; all persistent-state access (series, issues, downloads, queue) goes through it | FRG-DB-* (single SQLite database, transactional multi-step operations, typed schema) | MIT | 2026-07-05: no relevant known anomalies at review date. SQLAlchemy 2.0's `text()`/parameter-binding API is the safe default the project relies on to avoid SQL injection; no known CVE against the 2.x line at this floor. |
| alembic | `>=1.13` | PyPI | Versioned schema migrations for the SQLite database | FRG-DB-002 (versioned schema migrations), FRG-DB-003 (pre-migration automatic backup), FRG-DB-004 (schema-version guard) | MIT | 2026-07-05: no relevant known anomalies at review date. |
| aiosqlite | `>=0.20` | PyPI | Async SQLite driver used by SQLAlchemy's async engine | FRG-DB-005 (WAL journal mode with busy timeout), FRG-DB-006 (single-writer discipline) | MIT | 2026-07-05: no relevant known anomalies at review date. |
| httpx | `>=0.27` | PyPI | Async HTTP client for all outbound integrations (ComicVine, Newznab indexers, SABnzbd API, built-in DDL fetches) | FRG-META-001..004 (ComicVine client), FRG-IDX-* (Newznab queries), FRG-DL-*, FRG-DDL-* (download clients) | BSD-3-Clause | 2026-07-05: no relevant known anomalies at review date. Pinned floor (0.27) postdates the historical httpx `Proxy-Authorization`/`Authorization` header leak on cross-origin redirect advisory (fixed well before the 0.23 line); project does not proxy credentials across hosts in its own httpx usage. |
| uvicorn | `>=0.30` | PyPI | ASGI server that runs the FastAPI application | FRG-DEP-007 (health endpoint), FRG-DEP-008 (graceful shutdown), all FRG-API-* endpoints at runtime | BSD-3-Clause | 2026-07-05: no relevant known anomalies at review date. |
| pyyaml | `>=6.0` | PyPI | YAML parsing/serialization of `/config/config.yaml` | FRG-DEP-003 (configuration via environment variables and config file) | MIT | 2026-07-05: no relevant known anomalies in the pinned 6.x line itself (the historical arbitrary-code-execution issues, e.g. CVE-2017-18342/CVE-2020-14343, were about unsafe `yaml.load()` usage with `Loader=None`/`FullLoader`, fixed upstream by making `SafeLoader` the effective default in 5.1+/6.0). Foragerr must continue to load `config.yaml` only via `yaml.safe_load` (or an explicit `SafeLoader`) — this is a usage discipline, not something the version pin alone guarantees, and is worth a periodic code-review check. |
| defusedxml | `>=0.7` | PyPI | Hardened XML parsing (guards against XXE, billion-laughs/entity-expansion, external-entity SSRF) for untrusted Newznab/RSS indexer responses | FRG-IDX-006 (Newznab response parsing and error mapping), FRG-SEC-* (untrusted-input handling), the STRIDE disposition in `docs/security/threat-model.md` for indexer response parsing | PSF-2.0 | 2026-07-05: no relevant known anomalies at review date. This dependency exists specifically because stdlib `xml.etree`/`xml.dom.minidom` are unsafe against XXE/entity-expansion on untrusted input; no CVE known against defusedxml itself at this floor. |

## Development/test tooling (backend)

| Name | Version constraint | Purpose |
|---|---|---|
| pytest | `>=8.2` | Test runner for the backend test suite (`backend/tests/`), including the `req(id)` marker used for requirement traceability (FRG-PROC-004) |
| pytest-asyncio | `>=0.23` | Enables `async def` tests and fixtures for the FastAPI/SQLAlchemy-async codebase (`asyncio_mode = "auto"` in `pyproject.toml`) |

## Runtime SOUP items (frontend)

| Name | Version constraint | Source | Intended purpose | Requirements/subsystems supported | License | Known-anomaly review |
|---|---|---|---|---|---|---|
| react | `^18.3.1` | npm | Core UI rendering library; the component-tree runtime underlying the entire SPA | FRG-UI-001 (SPA architecture) and all FRG-UI-* screens (M1: 003-009) | MIT | 2026-07-05: no relevant known anomalies at review date. No CVE known against the `react` core package for the 18.3.x line. |
| react-dom | `^18.3.1` | npm | DOM renderer that mounts the React component tree onto the browser DOM (`frontend/src/main.tsx`) | FRG-UI-001, and all FRG-UI-* screens that render into the DOM | MIT | 2026-07-05: no relevant known anomalies at review date. No CVE known against `react-dom` for the 18.3.x line. |
| react-router-dom | `^6.26.2` | npm | Client-side routing between the library, series detail, add-series, queue, and settings screens | FRG-UI-001 (SPA architecture), FRG-UI-003..009 (per-screen routes) | MIT | 2026-07-05: the reviewer is aware of April 2025 React Router advisories (GHSA-4342-x723-ch2f "pre-render data spoofing" and GHSA-cpj6-fhp6-mr6j "`Cache-Control` header cache poisoning", CVE-2025-31137 family) affecting React Router v7 framework-mode/SSR (`@react-router/*` server packages). These target server-rendered/self-hosted deployments; foragerr uses `react-router-dom` v6 purely client-side (SPA, no SSR, no v7 framework mode), so the reviewer assesses **not applicable** at this pin — flag for re-review if the project ever adopts React Router v7 or SSR. |
| @tanstack/react-query | `^5.59.0` | npm | Server-state fetching, caching, and invalidation layer for all REST API calls, paired with WebSocket-triggered cache invalidation | FRG-UI-001 (SPA architecture: server state via React Query + WS invalidation) | MIT | 2026-07-05: no relevant known anomalies at review date; none known to the reviewer for the 5.x line. |
| zustand | `^4.5.5` | npm | Local (non-server) UI state store — library view mode/sort, sidebar collapse, interactive-search overlay target | FRG-UI-001 (local UI state kept out of React Query), FRG-UI-004, FRG-UI-007 | MIT | 2026-07-05: no relevant known anomalies at review date; none known to the reviewer for the 4.5.x line. |

## Development/test tooling (frontend)

| Name | Version constraint | Purpose |
|---|---|---|
| @testing-library/dom | `^10.4.0` | DOM query/assertion primitives underlying `@testing-library/react`, used across the component test suite |
| @testing-library/jest-dom | `^6.5.0` | Custom vitest matchers (`toBeInTheDocument`, etc.) for readable component test assertions |
| @testing-library/react | `^16.0.1` | React component rendering/interaction harness used by the screen and component test suite |
| @testing-library/user-event | `^14.5.2` | Simulated realistic user interaction (click/type/etc.) in component tests |
| @types/react | `^18.3.11` | TypeScript type definitions for React, used by `tsc`/`tsconfig` type-checking |
| @types/react-dom | `^18.3.0` | TypeScript type definitions for react-dom |
| @vitejs/plugin-react | `^4.3.2` | Vite plugin providing React Fast Refresh and the JSX transform during dev/build |
| jsdom | `^25.0.1` | DOM environment vitest uses to run component tests in Node without a real browser |
| typescript | `^5.6.2` | TypeScript compiler/type-checker (`tsc -b`, `npm run typecheck`) |
| vite | `^5.4.8` | Dev server and production build tool for the SPA |
| vitest | `^2.1.2` | Test runner for the frontend test suite (`frontend/src/**/*.test.tsx`) |

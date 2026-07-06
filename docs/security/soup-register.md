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

**Anomaly-review methodology (deferred — 2026-07-06 housekeeping).** Systematic
known-anomaly/vulnerability review of register items is a **documented future
improvement**, not a per-item mandate of this register. The original backfill
carried per-item "no relevant known anomalies as of <date>" verdicts written from
the reviewing agent's training knowledge rather than a live advisory query; the
owner judged those audit-misleading (they fabricate review rigor that never
happened) and had them removed. Until the project has network-connected CI able to
run live advisory tooling (`pip-audit`, `npm audit`, GitHub Dependabot), the
anomaly column reads "Deferred — see methodology" and no knowledge-based verdict
may be recorded (FRG-PROC-012). What this register **does** keep: a complete,
current inventory of every direct dependency (name, version constraint, source,
purpose, supporting requirements, license), with presence and version constraints
verified mechanically against the manifests by `tools/soup_check.py` at every merge
gate; the descriptive columns are maintained by the same-change update rule.
When live tooling becomes available, anomaly review is introduced in its own change
(tooling, cadence, recording format) and this note is updated.

## Runtime SOUP items (backend)

| Name | Version constraint | Source | Intended purpose | Requirements/subsystems supported | License | Known-anomaly review |
|---|---|---|---|---|---|---|
| fastapi | `>=0.115` | PyPI | ASGI web framework; defines and serves the REST API (routing, request/response models, OpenAPI schema generation) | FRG-API-* (REST API layer) | MIT | Deferred — see methodology |
| pydantic | `>=2.7` | PyPI | Data validation and settings/model layer underlying API request/response schemas and internal domain models | FRG-API-*, FRG-DEP-003 (config validation), most typed domain models | MIT | Deferred — see methodology |
| pydantic-settings | `>=2.3` | PyPI | Environment-variable/config-file settings loading and precedence (`FORAGERR_*` env vars, `/config/config.yaml`) on top of pydantic models | FRG-DEP-003 (configuration via environment variables and config file), FRG-DEP-005 (secrets never in image/repo) | MIT | Deferred — see methodology |
| sqlalchemy | `>=2.0` | PyPI | ORM and SQL toolkit; all persistent-state access (series, issues, downloads, queue) goes through it | FRG-DB-* (single SQLite database, transactional multi-step operations, typed schema) | MIT | Deferred — see methodology |
| alembic | `>=1.13` | PyPI | Versioned schema migrations for the SQLite database | FRG-DB-002 (versioned schema migrations), FRG-DB-003 (pre-migration automatic backup), FRG-DB-004 (schema-version guard) | MIT | Deferred — see methodology |
| aiosqlite | `>=0.20` | PyPI | Async SQLite driver used by SQLAlchemy's async engine | FRG-DB-005 (WAL journal mode with busy timeout), FRG-DB-006 (single-writer discipline) | MIT | Deferred — see methodology |
| httpx | `>=0.27` | PyPI | Async HTTP client for all outbound integrations (ComicVine, Newznab indexers, SABnzbd API, built-in DDL fetches) | FRG-META-001..004 (ComicVine client), FRG-IDX-* (Newznab queries), FRG-DL-*, FRG-DDL-* (download clients) | BSD-3-Clause | Deferred — see methodology |
| uvicorn | `>=0.30` | PyPI | ASGI server that runs the FastAPI application | FRG-DEP-007 (health endpoint), FRG-DEP-008 (graceful shutdown), all FRG-API-* endpoints at runtime | BSD-3-Clause | Deferred — see methodology |
| pyyaml | `>=6.0` | PyPI | YAML parsing/serialization of `/config/config.yaml` | FRG-DEP-003 (configuration via environment variables and config file) | MIT | Deferred — see methodology |
| defusedxml | `>=0.7` | PyPI | Hardened XML parsing (guards against XXE, billion-laughs/entity-expansion, external-entity SSRF) for untrusted Newznab/RSS indexer responses | FRG-IDX-006 (Newznab response parsing and error mapping), FRG-SEC-* (untrusted-input handling), the STRIDE disposition in `docs/security/threat-model.md` for indexer response parsing | PSF-2.0 | Deferred — see methodology |

## Development/test tooling (backend)

| Name | Version constraint | Purpose |
|---|---|---|
| pytest | `>=8.2` | Test runner for the backend test suite (`backend/tests/`), including the `req(id)` marker used for requirement traceability (FRG-PROC-004) |
| pytest-asyncio | `>=0.23` | Enables `async def` tests and fixtures for the FastAPI/SQLAlchemy-async codebase (`asyncio_mode = "auto"` in `pyproject.toml`) |

## Runtime SOUP items (frontend)

| Name | Version constraint | Source | Intended purpose | Requirements/subsystems supported | License | Known-anomaly review |
|---|---|---|---|---|---|---|
| react | `^18.3.1` | npm | Core UI rendering library; the component-tree runtime underlying the entire SPA | FRG-UI-001 (SPA architecture) and all FRG-UI-* screens (M1: 003-009) | MIT | Deferred — see methodology |
| react-dom | `^18.3.1` | npm | DOM renderer that mounts the React component tree onto the browser DOM (`frontend/src/main.tsx`) | FRG-UI-001, and all FRG-UI-* screens that render into the DOM | MIT | Deferred — see methodology |
| react-router-dom | `^6.26.2` | npm | Client-side routing between the library, series detail, add-series, queue, and settings screens | FRG-UI-001 (SPA architecture), FRG-UI-003..009 (per-screen routes) | MIT | Deferred — see methodology |
| @tanstack/react-query | `^5.59.0` | npm | Server-state fetching, caching, and invalidation layer for all REST API calls, paired with WebSocket-triggered cache invalidation | FRG-UI-001 (SPA architecture: server state via React Query + WS invalidation) | MIT | Deferred — see methodology |
| zustand | `^4.5.5` | npm | Local (non-server) UI state store — library view mode/sort, sidebar collapse, interactive-search overlay target | FRG-UI-001 (local UI state kept out of React Query), FRG-UI-004, FRG-UI-007 | MIT | Deferred — see methodology |

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

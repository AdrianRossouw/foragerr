# ui Spec Delta

## ADDED Requirements

### Requirement: FRG-UI-022 — Collected-edition (trade) surfacing

The library and series-detail UI SHALL surface a series' collected-edition type
(FRG-SER-018): a **book-type badge** (TPB / GN / HC) on the series card in the library
grid — including within a franchise group (FRG-UI-021) — and on the series-detail hero,
so a collected edition is visually distinct from a single-issues run. The library SHALL
offer a **filter** to show only collected editions or only single-issues runs. The
surfacing SHALL be display-only: every per-series action, navigation, monitored state,
and the wanted machinery SHALL behave exactly as for an untyped series, and a series
with a null book-type SHALL show no badge.

#### Scenario: Collected-edition badge appears

- **WHEN** a series typed `tpb`/`gn`/`hc` is shown in the library grid or its detail page
- **THEN** a corresponding book-type badge is displayed, while a null-typed single-issues run shows no badge, and all per-series actions are unchanged

#### Scenario: Collected-editions filter

- **WHEN** the operator applies the collected-editions filter in the library
- **THEN** only collected-edition (or only single-issues) series are shown, without changing any series' identity, monitoring, or wanted state

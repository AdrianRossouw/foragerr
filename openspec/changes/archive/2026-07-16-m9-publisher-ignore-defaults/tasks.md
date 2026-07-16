# m9-publisher-ignore-defaults — tasks

## 1. Matching + default (FRG-META-007 MODIFIED, FRG-META-020)

- [x] 1.1 `config.py`: curated default list as the field default (single constant; description documents wildcard + fresh-install-only semantics)
- [x] 1.2 `metadata/comicvine.py`: wildcard-capable matcher (exact or `*`-substring, casefold); search_series counts ignored and supports include-ignored (candidates flagged); suggest path keeps exclusion using the same matcher
- [x] 1.3 Tests (FRG-META-020, FRG-META-007, pytest): fresh render seeds default; stored value (incl. empty string) survives load; wildcard matching; count + include-ignored envelope

## 2. Lookup API envelope

- [x] 2.1 `api/series.py` lookup: response carries hidden count; `includeIgnored` query param returns flagged candidates
- [x] 2.2 Test (FRG-META-007, pytest): envelope count + flagged include mode over the API

## 3. Settings UI (FRG-UI-031)

- [x] 3.1 GeneralConfig resource: expose value + source (env/file/default); PUT accepts the field; env-managed writes refused
- [x] 3.2 Settings → General screen: editable field w/ env read-only indication
- [x] 3.3 Tests (FRG-UI-031, pytest + vitest)

## 4. Add New UI (FRG-UI-032)

- [x] 4.1 AddSeries screen: hidden-count line + Show reveal (refetch includeIgnored, badge ignored candidates, Settings link); no line when count is 0
- [x] 4.2 Tests (FRG-UI-032, vitest): count renders + reveal flow; zero-count renders nothing

## 5. Docs, gate, merge

- [x] 5.1 Manual: configuration.md setting row (default list + upgrade note); user/search.md hidden-results UI
- [x] 5.2 Suites + tsc green; matrix regen; soup/risk checks exit 0
- [x] 5.3 Tiered gate (small/medium: 3 angles + Codex); registry flip; archive; merge --no-ff; /release v0.9.12

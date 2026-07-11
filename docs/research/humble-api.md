# Humble Bundle order API — findings from prior-art dissection

Mined 2026-07-11 from three open-source Humble clients cloned into `.reference/`
(gitignored, per repo convention): `xtream1101/humblebundle-downloader` (Python,
612★, last pushed 2024-08), `smbl64/humble-cli` (Go, 130★, **last pushed
2026-06-28** — the currency anchor: an actively maintained client proves these
endpoints still work), `Tokariew/hb_downloader` (Python, pushed 2025-09).
Supersedes the owner live-capture plan (owner direction 2026-07-11); final
validation happens at UAT against the operator's real account.

## Auth

Session cookie `_simpleauth_sess` on `www.humblebundle.com` requests — confirmed
in all three clients. No other credential involved; no login automation anywhere
in maintained prior art.

## Endpoints (all `https://www.humblebundle.com`)

| Endpoint | Purpose | Notes |
|---|---|---|
| `GET /api/v1/user/order` | list purchases | returns `[{"gamekey": "..."}]` |
| `GET /api/v1/order/{gamekey}?all_tpkds=true` | order detail | the workhorse; JSON accept headers |
| `GET /api/v1/orders?gamekeys=...` | bulk order detail | used by humble-cli (`apiBundlesURL`); candidate optimization, verify param shape at UAT |
| `POST /api/v1/user/download/sign` | **Trove only** | signs subscription-catalog downloads; NOT used for bundle orders — out of scope |

## Order JSON shape (from humble-cli's Go structs — effectively a schema)

```
Bundle (order):
  gamekey        string
  created        naive datetime "2021-04-05T20:01:30.481166" (µs, NO timezone)
  claimed        bool
  amount_spent   float | null
  currency       string | null
  product        { machine_name, human_name }          # the bundle itself
  tpkd_dict      { all_tpks: [...] }                   # game keys — irrelevant to us
  subproducts[]:                                       # the items
    machine_name string                                # stable per-item identity
    human_name   string
    url          string                                # product page
    downloads[]:                                       # LIST (bundle path)
      platform        string                           # "ebook" for comics/books
      download_struct[]:
        name       string                              # format label: "CBZ", "PDF", "EPUB", ...
        md5        string
        file_size  uint
        url        { web: string, bittorrent: string } # web = signed, time-limited
```

Implementation notes carried into the design:

- **Diff identity**: `gamekey` + subproduct `machine_name` (matches FRG-SRC-003's
  store-native key).
- **Comic classification**: `platform == "ebook"` narrows to books/comics; then
  `download_struct[].name` / `url.web` extension (CBZ/CBR/PDF) separates comics
  from prose ebooks (EPUB/MOBI-only items). Same item frequently ships CBZ *and*
  PDF twins → format preference decides the grab
  (interim rule: prefer CBZ; see format-preference direction).
- **Signed URL**: `download_struct.url.web` — authorization lives in its query
  string (signature + expiry); fetch fresh at grab time, never store. Expected
  host `dl.humble.com`; **confirm the egress allowlist at UAT** (clients don't
  hardcode hosts).
- **Robustness precedent**: humble-cli deliberately parses each subproduct
  independently and skips malformed ones — exactly FRG-SRC-003's
  skip-and-log-never-abort rule.
- **Datetime**: naive microsecond ISO format without timezone — parse
  accordingly, don't assume UTC suffix.
- **Trove/Humble Choice subscription catalog** is a different flow (different
  endpoints, signing step) — out of scope; a Choice-included comic still appears
  as a normal order once claimed.

## Fixture plan

Build test fixtures directly from this schema (synthetic values, realistic
structure: a comic bundle with CBZ+PDF twins, a collected edition, an EPUB-only
book, a game subproduct, one malformed subproduct). At UAT, the first real
connect + sync against the operator's account validates the schema; any drift
found there updates the client and these fixtures in the same commit.

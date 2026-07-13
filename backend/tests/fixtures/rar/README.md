# Vendored RAR test fixtures

These small RAR archives back the CBR (RAR-backed page-streaming) tests for
`FRG-OPDS-016`. RAR **creation** is impossible in the sandbox/CI (only RARLAB's
proprietary trial CLI writes the RAR format; there is no OSS RAR writer), so
these mechanics fixtures are vendored verbatim from the `rarfile` project's own
test corpus rather than generated at test time.

## Origin

Copied unmodified from the `rarfile` 4.3 source distribution
(`pip download rarfile==4.3 --no-binary :all:`), `test/files/`:

| file | what it exercises |
|------|-------------------|
| `rar3-subdirs.rar` | RAR4 listing / member enumeration (text members, nested dirs, unicode names) |
| `rar5-subdirs.rar` | RAR5 listing / member enumeration, single-member reads, limit ceilings |
| `rar5-hpsw.rar`    | header-encrypted RAR → non-listable degradation (no PSE, stream 404) |
| `rar5-symlink-unix.rar` | RAR with symlink members → rejected for security parity with ZIP |

All members inside these archives are tiny **text** files. They prove the RAR
backend *mechanics* (open, enumerate, natural ordering, single-member streaming
read, size/count-limit enforcement, symlink/encrypted refusal). They do **not**
contain image members, so the image-render half of the page-stream matrix is
covered instead by (a) a locally-generated ZIP-renamed-`.cbr` fixture with real
PNGs — proving the content-detection seam and the render path — and (b) a
`TODO(owner-fixture)` skipped stub awaiting comic-shaped image-bearing `.cbr`
archives the owner generates with RARLAB's macOS-arm trial CLI on his host
(recorded as an owner action item in the change).

## License

`rarfile` is distributed under the ISC license. The upstream `LICENSE` file is
vendored here verbatim as `LICENSE` and applies to these fixture archives.

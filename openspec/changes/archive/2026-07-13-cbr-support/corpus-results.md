# cbr-support — task 2.8 corpus run (2026-07-13)

Gated stream-check across the owner's real library (`sample-comics/`,
post-resync): every `.cbr` driven through the shipping archive layer
(`list_image_members` → `read_image_member` first+last → PIL decode of the
first page), once per candidate backend. 473 files, all true RAR by magic
(no zip-renamed impostors in this corpus).

| Backend | Pass | Fail | Elapsed | Verdict |
|---|---:|---:|---:|---|
| unrar-free 0.3.3 (GPL, Debian main — the deployment backend) | **473** | 0 | 14.1 s | **Accepted: 100% pass on real data.** |
| bsdtar / libarchive 3.8.5 | 4 | 469 | 3.8 s | **Refuted as a fallback**: `ArchiveMemberError: could not read member …` on single-member extraction — the exact operation page streaming performs. |

Consequences applied to the change docs: libarchive/bsdtar is removed as a
recommended fallback (design decision 1, SOUP container note); RARLAB's
proprietary `unrar` remains the sole documented compatibility alternative,
still gated on ever finding real archives `unrar-free` mishandles (none in
this corpus).

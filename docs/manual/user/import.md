# Import & renaming

**This chapter is a stub.**

The import pipeline — moving a completed, verified download into your library,
matching it to the right series/issue, and renaming it according to your naming
scheme — is being implemented under OpenSpec change `m1-import-pipeline`. That work is
not yet merged to `main`, so this chapter deliberately does not describe it: per
`FRG-PROC-011`, the manual only documents behavior that has actually shipped.

What foragerr can already do, described elsewhere in this guide:

- Parse comic filenames and release titles through a single shared parser (used for
  library scanning, indexer release-title evaluation, and search matching).
- Track a download from grab through completion and verification (`downloads.md`).
- Reconcile series/issue metadata against ComicVine (`metadata.md`).

What is still missing, and will be documented here once `m1-import-pipeline` merges:

- Moving a completed download's file(s) from download-client storage into the
  series' library folder.
- Matching an unresolved/ambiguous completed download to the right series and issue
  (manual import).
- Renaming files according to a configurable naming template.
- Handling files dropped directly into a series folder outside the download flow.

This chapter will be filled in at that change's merge gate.

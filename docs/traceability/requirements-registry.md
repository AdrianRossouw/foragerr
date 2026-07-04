# Requirements Registry

The authoritative allocation table for requirement IDs (**FRG-PROC-002**). An ID is
allocated here at the moment its requirement first appears in an OpenSpec change
proposal, and is never reused or renumbered — including for withdrawn requirements,
which are marked `withdrawn` but keep their row.

The commit-msg hook rejects any commit whose `Refs:` trailer cites an ID not listed here.

Status: `proposed` (in an open change) → `active` (change archived into specs/) →
`withdrawn` (kept for history).

| ID | Title | Spec | Status |
|----|-------|------|--------|
| FRG-PROC-001 | Commit traceability: Conventional Commits + Refs trailer | dev-process | active |
| FRG-PROC-002 | Stable, registered requirement identifiers | dev-process | active |
| FRG-PROC-003 | Spec before code (OpenSpec change workflow) | dev-process | active |
| FRG-PROC-004 | Every requirement verified by tagged automated tests | dev-process | active |
| FRG-PROC-005 | Maintained traceability matrix | dev-process | active |
| FRG-PROC-006 | Threat analysis and living risk register | dev-process | active |
| FRG-PROC-007 | Branch-based integration, green main | dev-process | active |
| FRG-PROC-008 | Worktree isolation for concurrent agents | dev-process | active |
| FRG-PROC-009 | Spec approval gate | dev-process | active |

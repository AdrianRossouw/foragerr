# logout-failure-handling — tasks

## 1. Client logout confirmation

- [x] 1.1 LogoutButton: split onSettled into onSuccess (clear auth state + navigate to /login) and onError (do NOT clear or navigate; set a retryable error state; keep the button enabled for retry)
- [x] 1.2 Surface the failure accessibly in the header actions region (role="alert" / aria-live), consistent with the app's existing error styling
- [x] 1.3 Test (FRG-AUTH-004, vitest): a confirmed (204) logout clears auth state and navigates to /login
- [x] 1.4 Test (FRG-AUTH-004, vitest): a failed logout (rejected mutation) does NOT clear auth state, does NOT navigate, and renders a retryable error; a subsequent success then clears + navigates

## 2. Docs, gate, merge

- [x] 2.1 Manual (FRG-PROC-011): docs/manual/user note that a failed logout keeps you signed in and to retry
- [x] 2.2 Frontend suite + tsc green; regenerate traceability matrix; soup_check + risk_register_check exit 0 (no dep/security-doc changes)
- [x] 2.3 Tiered review gate (small, auth-touching: 2-3 angles + a security angle + Codex); merge --no-ff; tag; delete branch

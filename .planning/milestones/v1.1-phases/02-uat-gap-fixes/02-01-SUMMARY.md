---
phase: 02-uat-gap-fixes
plan: 01
issue: I-3
status: complete
executed: 2026-04-19
---

# Plan 02-01 — Summary: Fix Vite Proxy Port (UAT I-3)

## Files Changed

- `viewer/vite.config.ts` — proxy target + inline auto-memory-rule comment

## Diff Snippet

```ts
// before
'/api': {
    target: 'http://localhost:8700',
    changeOrigin: true,
},

// after
'/api': {
    // API dev port — must match uvicorn port from bootup config (9925).
    // Per user auto-memory rule `feedback_api-client-proxy.md`: client code
    // (viewer/src/lib/api/client.ts) keeps API_BASE = '' and routes through
    // this proxy. Never hardcode a localhost port in client code — only
    // the proxy target names the backend port, and it lives here.
    target: 'http://localhost:9925',
    changeOrigin: true,
},
```

## Before/After

- **Before:** `/api/*` from viewer dev server (:9926) proxied to `http://localhost:8700` → 500 (no process)
- **After:** `/api/*` from viewer dev server (:9926) proxied to `http://localhost:9925` → matches uvicorn bootup port

## Acceptance Criteria

- `grep -c "localhost:8700" viewer/vite.config.ts` → `0` ✓
- `grep -c "localhost:9925" viewer/vite.config.ts` → `1` ✓
- `grep -c "feedback_api-client-proxy.md" viewer/vite.config.ts` → `1` ✓
- `viewer/src/lib/api/client.ts` not modified (diff confined to vite.config.ts) ✓

## Follow-Up

Runtime re-verification of UAT tests 24–28, 30, 33–36 belongs to the follow-up `/gsd-verify-work 2` pass — not this plan.

## Self-Check: PASSED

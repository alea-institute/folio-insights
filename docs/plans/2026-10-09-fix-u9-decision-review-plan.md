# U9 signed decision review fixes

Continue U9 / R16 / KTD11 from `2026-10-09-0650-feat-shards-axioms-drain-plan.md`.
The user offers all 13 existing dirty files for completion on `feat/drain-fix-u9`.
Base: `origin/master` (local reference only); publication belongs to the orchestrator.

1. Complete proposal ledger fixes: validate freshness against the stored commit time,
   consume nonces only for valid folded decisions, and distinguish registered signers
   from signatures that merely verify. Cover read-back, stale append rollback and nonce reuse.
2. Complete review API fixes: bind threshold approvals to the exact selected IDs;
   require signatures for task create/delete, hierarchy edits and contradiction resolution;
   preserve attribution on reads and clear it on unsigned replacements. Keep legacy and
   partly migrated databases readable without write side effects, and serialize migrations.
3. Add focused regression coverage, run bounded relevant suites and repository Ruff lint,
   inspect the complete diff for bugs, and make path-limited local commits.
4. Write `.codex-out/lane-result.md` with commit/test evidence and integration instructions.

Use generated test keys and synthetic data only. No network, credentials, destructive
operations, U8/U10 changes, or new product decisions are in scope. Record pre-existing
lint debt separately; changed code must pass lint.

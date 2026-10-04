# Handoff — /source security fix, book scrub, v2.0 GSD→CE migration (2026-09-27; refreshed 2026-10-04, late)

## Done (verified 2026-10-03)
- PR #2 merged on 2026-09-30: `/api/v1/source` confined to the output dir, the `test1` corpus untracked, build guard against untracked corpus files, Gate 5 runnable, Railway config removed, GSD v2.0 archived.
- Dev app redeployed. `/health` returns 200, `/api/v1/source?file=/nonexistent-probe` returns `found: false`, and `/api/v1/corpora` lists only `demo`.
- R18 disposition confirmed 2026-09-30 (folio-propositions); the PRD §6–§7 HOLD banner now points to the recorded disposition.
- The v2.0 candidate gates moved into the 2026-09-30 backlog-review decision sheet.

## Still open
1. **GitHub Support purge (Damien sends).** GitHub-owned `refs/pull/1`–`refs/pull/9` still reach the pre-scrub book commits.
2. **v2.0 phase gates (Damien decides).** These are on Decision Sheet `folio-insights-2026-10-04-1531-v2-next-phases`. Each recommendation below is agent-proposed, not yet answered:
   - **Phase 11 SHACL:** build it next.
   - **Phases 12 and 13.5:** build them after Phase 11.
   - **Phases 9 and 10:** plan only.
   - **Review UI (14/15):** re-scope it with mockups.
3. **Remaining follow-ups (mostly design choices):**
   - **PII coverage:** the PII patterns miss unseparated 10-digit numbers. A bare pattern would also flag 10-digit epoch timestamps, so it needs context rules.
   - **Signed decisions:** `decided_by` is self-asserted.
   - **API authentication:** the proposed-class routes are opt-in and loopback-only for now.
   - **U17 open questions:** subtype restructuring and span offsets.
   - **CORPUS-04:** needs Phase 11 and the real corpora.
   - **Old worktree:** the stale `~/worktrees/folio-insights-docker-git` worktree holds untracked agent notes. It needs Damien's OK to delete.

## Closed 2026-10-04 (later)
- **Governance pipeline:**
  - **U1+U2:** PR #15.
  - **U3+U4:** PR #16. It adds decisions, the approved-only export, B4–B9 and the exclusion scanner (`scripts/check_exclusions.py`, with an optional `--book` shingle gate).
- **Single approval surface:** PR #17. Proposed-class decisions go through the proposal ledger, and legacy review.db is imported only by an explicit `import-legacy`.
- **Long-term reproducible images:** PR #18. Every image input is pinned (uv digest, hashed locks, apk closure, build backends), and builds use a normalized HEAD context.
- **HermiT in the worker JRE:** PR #19, which also refreshes `requirements.dev.lock` and fixes the worker stage ordering.
- **Review status:** each PR passed an independent adversarial review with every finding fixed. The fast suite stands at 1620 passed.
- **Gate 5 cold reproducibility** (PR #21): unique build contexts per image (the cause was BuildKit caching contexts by basename), web stage ordering, and a green Dagger `_test`.
- **Process lesson:** a worker ran a box-wide `docker image prune`. Worker briefs now forbid broad Docker cleanup.

## Closed 2026-10-04
- **History scrub:** executed on Damien's go. The two `archive/*` branches were deleted, and `filter-repo` removed `output/test1/sources/` and `staging/ta_ch01*` from every branch and tag. All were force-pushed after a fresh verified mirror backup.
  - **Verification:** a fresh clone shows 0 book paths. The largest verbatim overlap with the book in any remaining file is 55 words.
- **U17 envelope migration to R18:** PR #10.
- **Phase 13 storage:** U1–U2 in PR #11, U3 in PR #12, U4 in PR #13.
  - **Review:** each PR passed an independent adversarial review, with every finding fixed.
  - **Governance signature format v2:** the signed payload now binds `signed_at` and the signer.
  - **Bulk load:** about 250K triples/sec.
  - **Operations guide:** `docs/storage-operations.md`.

## Closed 2026-10-03
- Gate 5 digest drift was fixed in PR #7. Images build with `docker buildx` and `rewrite-timestamp`, and cold rebuilds give the same digests. Rebuilds weeks apart can still drift, because `uv:latest` and `apk` versions are not pinned and the web dependency lock is incomplete.
- The blank source panel for CLI corpora (review P2) was fixed in PR #8. CLI inputs are copied into `output/<corpus>/sources/`, and the `/source` confinement is unchanged.
- The `upload.py` zip guard was already fixed. It uses `is_relative_to`, so that item was stale.
- From a worktree, tests need `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH` set to the real folio-enrich backend. Otherwise 8 bridge and ingestion tests fail because the relative `../folio-enrich` default does not resolve.

Lesson recorded: `docs/solutions/git-commit-pathspec-re-adds-untracked-files.md`.

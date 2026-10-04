# Handoff — /source security fix, book scrub, v2.0 GSD→CE migration (2026-09-27; refreshed 2026-10-04)

## Done (verified 2026-10-03)
- PR #2 merged on 2026-09-30: `/api/v1/source` confined to the output dir, the `test1` corpus untracked, build guard against untracked corpus files, Gate 5 runnable, Railway config removed, GSD v2.0 archived.
- Dev app redeployed. `/health` returns 200, `/api/v1/source?file=/nonexistent-probe` returns `found: false`, and `/api/v1/corpora` lists only `demo`.
- R18 disposition confirmed 2026-09-30 (folio-propositions); the PRD §6–§7 HOLD banner now points to the recorded disposition.
- The v2.0 candidate gates moved into the 2026-09-30 backlog-review decision sheet.

## Still open
1. **GitHub Support purge (Damien sends).** The history scrub is done, but GitHub-owned `refs/pull/1`–`refs/pull/9` still reach the old book commits. Only GitHub Support can remove them.
2. **Proposed-class governance pipeline is next.** Damien answered "Yes, after Phase 13" on 2026-09-30, and there is a plan at `docs/plans/2026-09-30-0914-feat-proposed-class-governance-plan.md`. Plan R7 says governance starts after storage "passes its exit criteria". Phase 13 met every criterion that synthetic data can reach. CORPUS-04 (the three real benchmark corpora plus SHACL) waits on Phase 11 and the real corpora.
3. **Phase 13 follow-ups:**
   - PII patterns miss unformatted 9- and 10-digit numbers.
   - The nightly dump has an entry point but no scheduler.
   - Full SHACL is deferred to Phase 11.
   - U17 left two open questions: restructuring the subtypes, and span offsets.

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

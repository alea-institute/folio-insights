# Handoff — /source security fix, book scrub, v2.0 GSD→CE migration (2026-09-27; refreshed 2026-10-03, second pass)

## Done (verified 2026-10-03)
- PR #2 merged on 2026-09-30: `/api/v1/source` confined to the output dir, the `test1` corpus untracked, build guard against untracked corpus files, Gate 5 runnable, Railway config removed, GSD v2.0 archived.
- Dev app redeployed. `/health` returns 200, `/api/v1/source?file=/nonexistent-probe` returns `found: false`, and `/api/v1/corpora` lists only `demo`.
- R18 disposition confirmed 2026-09-30 (folio-propositions); the PRD §6–§7 HOLD banner now points to the recorded disposition.
- The v2.0 candidate gates moved into the 2026-09-30 backlog-review decision sheet.

## Still open
1. **History scrub (needs Damien's explicit go).** The copyrighted book is still in public git history: `git log origin/master --name-only` shows 28 hits for `output/test1/sources` or the Ch01 manuscript paths. Removing them means a `git filter-repo --invert-paths` rewrite and a force-push. The 2026-09-30 standing rule says never force-push, which supersedes the 2026-09-27 approval, so an explicit go is needed. A verified pre-scrub mirror backup exists (machine-local). Refs that also carry the book: tag `v1.1`, `backup-pre-split-*`, `backup/pre-bench-strip-*`, `build/folio-resolve-0.4.0`, and the two `archive/*` branches (which also hold the Ch01 `.docx`). GitHub-owned PR refs need a GitHub Support purge request.
2. **Delete the two public `archive/*` branches**, which still hold the manuscript `.docx`. The agent's delete was blocked by the permission classifier.
3. **Next build is waiting on Damien's answer.** Phase 13 storage was answered "Yes, after R18" on 2026-09-30, and R18 is confirmed. Its plan (`docs/plans/2026-09-30-0913-feat-phase13-storage-plan.md`) first needs U17, the shard envelope migration. Items 1–3 are asked on the Decision Sheet `folio-insights-2026-10-03-2047-history-scrub-and-phase13`.

## Closed 2026-10-03
- Gate 5 digest drift was fixed in PR #7. Images build with `docker buildx` and `rewrite-timestamp`, and cold rebuilds give the same digests. Rebuilds weeks apart can still drift, because `uv:latest` and `apk` versions are not pinned and the web dependency lock is incomplete.
- The blank source panel for CLI corpora (review P2) was fixed in PR #8. CLI inputs are copied into `output/<corpus>/sources/`, and the `/source` confinement is unchanged.
- The `upload.py` zip guard was already fixed. It uses `is_relative_to`, so that item was stale.
- From a worktree, tests need `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH` set to the real folio-enrich backend. Otherwise 8 bridge and ingestion tests fail because the relative `../folio-enrich` default does not resolve.

Lesson recorded: `docs/solutions/git-commit-pathspec-re-adds-untracked-files.md`.

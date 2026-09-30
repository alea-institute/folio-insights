# Handoff — /source security fix, book scrub, v2.0 GSD→CE migration (2026-09-27)

## Where it stands
- PR #2 (branch `refactor/v2-gsd-to-ce-migration`) is reviewed and merge-ready: `/api/v1/source` confined to the output dir, the copyrighted `test1` corpus untracked, a build guard against shipping untracked corpus files, Gate 5 runnable, Railway config removed, GSD v2.0 archived.
- The public dev app is stopped until the patched code deploys. Do not restart the old container; its image has the file-read hole.
- Plan: `docs/plans/2026-09-27-1930-refactor-v2-gsd-to-ce-migration-plan.md`. Done: U1–U4, U15, U16. U5 drafted as folio-propositions PR #2, awaiting Damien. U6–U14 and U17 are gated candidates.

## Next, in order (each needs Damien's go; the agent's merge and force-push were blocked by permissions)
1. Merge PR #2.
2. Scrub `output/test1/sources/` (and the Ch01 manuscript paths) from `master` history with `git filter-repo --invert-paths`, then force-push. A verified mirror backup exists; the rehearsal kept all commits and removed every book path. Other refs that still carry the book: tag `v1.1`, the `backup*`, `build/folio-resolve-0.4.0`, and two `archive/*` branches. GitHub-owned PR refs need GitHub Support.
3. Redeploy on Coolify and verify: `/health` 200, `/api/v1/source?file=/etc/hostname` → `found: false`, no `test1` in `/api/v1/corpora`.
4. Answer the filed decision sheets: v2.0 candidate gates, and the R18 disposition confirmation.

## Follow-ups
- Gate 5 now reports real digest drift for web and worker: a reproducibility regression.
- The source panel is blank for CLI-extracted corpora whose inputs live outside the output dir (review P2, listed on PR #2).
- `tests/test_bridge.py::test_normalizer_import` fails because sibling folio-enrich now imports `folio_propositions`.
- `api/routes/upload.py`'s zip guard uses `str.startswith`; `is_relative_to` is the stronger check.
- Lesson recorded: `docs/solutions/git-commit-pathspec-re-adds-untracked-files.md`.

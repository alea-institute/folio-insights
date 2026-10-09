# U8 review completion

Scope: finish the inherited minting/rubric review fixes for drain U8 (R1–R5),
preserving its unpushed commits and merging fetched `origin/master` without rebasing.

1. Preserve the dirty minting work, merge master, and retain both CLI registrations.
2. Complete claim-support, IRI existence/branch, prompt-lineage and ExtractEvent
   reporting fixes. Cover these contracts with deterministic synthetic tests and
   the existing fake-provider minting suite; update stale expectations.
3. Run bounded Ruff and focused minting/rubric tests with the designated Python
   interpreter and `PYTHONPATH=src:.`. Record sandbox SQLite/TestClient timeouts
   as environment limitations; do not debug the sandbox.
4. Inspect the final diff for bugs, commit owned files atomically, and write
   `.codex-out/lane-result.md` with commits, verification and publication handoff.

Acceptance: master is an ancestor of the lane, owned changes are committed,
focused checks pass or have a documented environment exception, and the lane is
ready for the orchestrator's review/publication. No network operations in this lane.

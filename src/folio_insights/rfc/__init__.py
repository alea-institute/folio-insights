"""RFC lifecycle linter package (Phase 7, GOV-07).

D-22 spec: CI-runnable gate that walks each RFC file's full git history and
enforces the monotonic status DAG (`draft → discussion → {accepted, rejected}
→ implemented`).

D-02 scope: this phase ships `RFC-TEMPLATE.md` as the linter's golden fixture
ONLY. Contributor-facing prose (CONTRIBUTING.md / CODE_OF_CONDUCT.md /
GOVERNANCE.md) lives in Phase 18.

Stdlib-only discipline: no PyYAML, no python-frontmatter, no GitPython.
The frontmatter parser is a deliberate ≤30 LOC `re`-based reader; git
history is walked via `subprocess.run(["git", "log", ...])`. See
`.planning/phases/07-governance-model-3-1/07-RESEARCH.md` §"Don't Hand-Roll"
for the dep-rejection rationale.
"""

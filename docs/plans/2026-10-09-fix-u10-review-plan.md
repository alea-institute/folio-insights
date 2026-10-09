# U10 review-fix completion

Base: `origin/master`; lane: `feat/drain-fix-u10`.
Scope: finish U10/R12/R14 from the shards/axioms drain plan, preserving inherited work.

1. Merge the fetched master without rebasing; retain the dirty viewer changes.
2. Verify and commit bounded layout work, roving keyboard focus, prioritized edge styles,
   depth-zero selection, explicit truncation messages, and local font stacks.
3. Review graph API caps and canonical history replay. Add a regression for parallel
   fields consuming the reaching-edge budget; reserve one edge per reaching pair first.
4. Run bounded viewer tests/check/build, Python graph and related pure tests, Ruff,
   generated-shape and exclusion checks. Record known sandbox SQLite/TestClient hangs;
   do not investigate the sandbox issue. Leave browser acceptance to the orchestrator
   if no local browser runner is available.
5. Commit focused units and write `.codex-out/lane-result.md`; no network publication.

Acceptance: master is an ancestor; every in-scope change is committed; bounded checks
have truthful receipts and environment limitations; no secrets or unrelated changes.

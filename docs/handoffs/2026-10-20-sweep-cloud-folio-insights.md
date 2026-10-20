# Handoff: cloud sweep lane, folio-insights (cycle sweep-2026-10-20)

Lane: cloud orchestrator. Mandate: resume the v2 build-out (axiom build-out: minter, kernel, path IDs), then the Phase 9-11 plans; done when the next units are merged.

## State found (2026-10-20)

- **Drain plan done:** all units U1-U12 of `docs/plans/2026-10-09-0650-feat-shards-axioms-drain-plan.md` were already on master (U8 #37, U9 #36, U10 #38, the rest in #33-#35). Phase 10 U1-U6 and Phase 11 were also merged.
- **Phase 9 left:** only U6 (polysemy) and U8 (roll-up).
- **Master was red:** `tests/api/test_auth.py::test_every_mutating_route_has_the_operator_dependency` failed because the bridge routes (#35) landed without the U5 guard classification. Five more tests need the folio-enrich backend checked out (set `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH`).
- **No GitHub CI:** the repository has no GitHub Actions workflows, so the gate for every PR below was the local fast suite in a clean worktree, with the evidence posted on each PR.

## Merged this sweep

| PR | What | Evidence |
|---|---|---|
| #39 | Bridge routes classified in the operator-guard sweep. `/status` is a read; `/ingest` keeps its service token through `require_bridge_token`. | Fast suite green, together with #40 |
| #40 | Journal retries a locked `PRAGMA journal_mode = WAL` on concurrent first opens (the bridge lane's 2026-10-09 note). | Failing test first; 4/1,800 opens failed before, 0 after |
| #43 | The PII gate refuses a bare ten-digit US phone within 20 characters after a phone word; epoch timestamps still pass. | Fast suite 3,410 passed, 0 failed |
| #44 | **Phase 9 U6** polysemy productionization. It ships an honest FP gate and forks only after a human disposition. An independent review found 7 should-fix items, all fixed. | Fast suite 3,512 passed, 0 failed |
| #45 | Race fixed in the LLM cancellation test (it failed 4 of 5 runs on master). | 15/15 runs pass |
| #46 | **Phase 9 U8** roll-up across all seven principles on one synthetic corpus. Review fixes: the generator gives the same corpus on every call; P6 asserts the planted term reads `polysemy`. | Fast suite 3,516 passed, 0 failed |

**Mandate status:** done. Phase 9 is complete as code (U0-U8); R9 is not met (below).

## What the roll-up shows

- **Six principles met:** P1, P2, P3, P4, P5 and P7 meet their acceptance checks on one synthetic six-framework corpus. The roll-up takes about 12 s on 4 vCPU.
- **P6 (R9) not met.** The FP gate measures 12 false positives on 82 agent-written labeled cases. The Wilson 95% upper bound is 23.9% against a 10% ceiling, so the status is `fail`, and the gate cannot report `pass` without human certification.
- **Cause:** Rule 3 counts a large distance between meanings as evidence of polysemy. Unrelated meanings (homonyms) sit further apart than related ones, so all 12 false positives are homonyms.

## Open questions for Damien

1. **Who certifies the polysemy FP gate?** (`folio-insights-2026-10-05-0814-p9-build-and-calls` q2, still open)
   - **Recommendation:** keep the plan's recommendation. Agents write the cases and first-pass labels; you review every agent/LLM disagreement plus a 20% sample. The certification hook exists: a `certification` block bound to a SHA-256 of the cases, requiring at least 20% sampled and every label covered.
   - **Timing:** moot until Rule 3 is redesigned (question 2), because the gate fails even with certification.
   - **Setting:** quick-decision.
2. **May an agent redesign polysemy Rule 3?**
   - **Recommendation:** yes, as the next unit. Rule 3 should treat related, analogous senses (moderate distance, with shared structure) as polysemy, and send large-distance cases to the homonym check or the LLM.
   - **Evaluation:** on a held-out split of the labeled set, so the rule is not tuned to the cases it is scored on. Report the gate as measured.
   - **Setting:** quick-decision.
3. **`fi:proportionalRelation` type mismatch.**
   - **Problem:** the vocabulary declares it an ObjectProperty, but the PRD and every writer use a text literal.
   - **Recommendation:** re-declare it as a DatatypeProperty in the next vocabulary revision. Coordinate with folio-enrich, because a `VOCAB_VERSION` bump touches the shared TBox.
   - **Setting:** quick-decision.
4. **GitHub Actions CI.**
   - **Problem:** none exists, so merges rely on local runs.
   - **Recommendation:** add a workflow running the fast suite (`-m "not gate5 and not slow"`) with folio-enrich checked out. Actions minutes are org spend, so this needs your yes.
   - **Setting:** quick-decision.
5. **Bridge ingest auth.** `/api/bridge/v1/ingest` accepts only the bridge service token, not operator tokens.
   - **Recommendation:** keep it that way, since a service credential scoped to one route is narrower.
   - **Setting:** quick-decision; no action needed if you agree.

## Steps that need the home box or Damien

- **Bulk-load floor:** re-confirm the ≥200K triples/s floor (`test_bulk_load_meets_200k_triples_per_second`) on an idle box with SHACL on. This cloud container measured about 80K/s, and it fails the same way on clean master here.
- **Worker image:** rebuild the local `fi-worker:smoke` image; it predates the java.desktop fix (carried from the 2026-10-05 handoff).
- **CORPUS-04:** needs the real corpora. Also, `bench/corpus04.py` still reports cluster validation as unavailable; wire U1 into it (agent-doable).
- **Book overlap:** `check_exclusions --book` needs the book on the box; it last flagged 2 short quotations already on master (carried).
- **GitHub Support purge** of `refs/pull/1`-`9` (Damien; carried).
- **Old worktree:** decide whether to delete the stale `folio-insights-docker-git` worktree (Damien; carried).

## Next agent-doable units

1. **Polysemy Rule 3 redesign** (after question 2), evaluated on a held-out split.
2. **Signed polysemy dispositions:** reuse U9's decision-signing stack, so that `labeler: human` and the certification record stop being self-asserted.
3. **`fi:closedUnder` writer** so closed-world islands are written, not overlaid. The U8 roll-up uses an overlay today.
4. **Corpus-level signed-decision setting:** KTD11 named one; today the switch is server-wide.
5. **Remove bridge-ingest's open-retry workaround** now that #40 fixes the journal.
6. **Phase 10 U7 provider bake-off:** operator-run with your keys; it involves spend, so it is not agent-doable without a yes.
7. **Review UI (Phases 14-15):** waits on the look-and-workflow Decision Sheet (another lane, `2026-10-20-review-ui-rescope.md`).

## Notes for the next lane

- **Test environment:** `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH=<folio-enrich>/backend`, `FOLIO_INSIGHTS_CORPUS_ROOT=$(mktemp -d)`, `PYTHONPATH=<worktree>/src:<worktree>`. The roll-up and polysemy tests need the embedding model in the local Hugging Face cache.
- **Branches:** archive and backup branches were left untouched. The merged feature branches from this sweep remain on the remote.

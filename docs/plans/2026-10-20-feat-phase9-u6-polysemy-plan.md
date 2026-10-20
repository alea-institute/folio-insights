---
title: "feat: Phase 9 U6 — polysemy productionization (9.P6)"
type: feat
status: active
date: 2026-10-20
parent: docs/plans/2026-10-05-0308-feat-phase9-design-principles-plan.md (U6, R9, KTD9, KTD10)
---

# Phase 9 U6 — polysemy productionization

## Goal

Turn the Phase 1 polysemy spike into a human-gated capability with an honest
false-positive gate (R9, PRINCIPLE-06). The detector reads P1 clusters and P2
frameworks, fork proposals carry the PRD §8 P6 shape, subsumption and
similarity are separate APIs, and no path applies a fork without a recorded
human disposition.

## Decisions (fixed by the orchestrator; not re-opened here)

1. **Honest gate.** Wilson 95% **upper** bound over the labeled set, threshold
   ≤ 0.10. Status is `provisional` unless the set carries a human
   `certification` record (`certified_by`, `certified_at`, the sample
   reviewed, bound to the cases' digest). Certified and ≤ 0.10 → `pass`;
   > 0.10 → `fail` whatever the certification. Agents never write the record;
   the shipped set has none. Who certifies stays Open Question 1.
2. **FP = detector miscall** (KTD9): the detector said `polysemy` and the
   disposition rejects it with a rationale. A reject with an empty rationale
   is an invalid disposition: it is never counted as an FP and is excluded
   from N (reported separately). The review CLI refuses such a reject, and
   `append_disposition` refuses to write one.
3. **Thresholds.** `TERMS_OF_ART_THRESHOLD = 0.75` (Option B). A typed
   per-framework-pair override config (`polysemy/thresholds.py`) ships empty
   (Option C deferred).
4. **Labeled set.** Agent-authored synthetic paraphrase under
   `tests/polysemy/fixtures/labeled_set.json`, N ≥ 70, civil-law cases under
   `us.louisiana.civil_code`, each disposition `labeler: agent`. Report what
   the detector produces; fixtures are not tuned to a number. No live LLM:
   Rule 4 cases run against a pessimistic fake that always answers
   `polysemy`, so the measured bound does not depend on LLM quality.
5. **Detector inputs.** `polysemy/candidates.py` turns a P1 `ClusterSet` plus
   the P2 `FrameworkRegistry` into per-concept prototype clusters keyed by
   registered framework IDs; `fi:inFramework` objects are framework IRIs.
6. **Fork output.** `DistinguoFork` emits the SKOS grouping, jurisdiction-
   scoped classes, `fi:distinguishes`, `fi:analogousTo` and a configurable
   `fi:primeAnalogate` with existing vocabulary terms only (no vocab change,
   no `VOCAB_VERSION` change).
7. **TBox seeds.** `polysemy/tbox_seeds.ttl` carries `owl:disjointWith` seeds
   between term-scoped classes; Rule 1 asks the reasoner, not a free-floating
   pattern (the spike's ASK matched any disjointness anywhere in the graph).
8. **No auto-apply.** Fork TTL is emitted only against a human disposition
   (accept/modify, non-agent labeler, same cluster). Flag-absence tests cover
   every polysemy CLI command and the API route table.
9. **KTD10.** `similarity_query.py` keeps only similarity
   (`SimilarityResult`); subsumption/disjointness goes behind a
   `SubsumptionReasoner` protocol in `reason/` (`SubsumptionResult`), with a
   grep guard.
10. **fp_audit** goes through the Phase 10 port (`TaskLLM`), with an injectable
    fake.

## Result (2026-10-20)

The gate was measured honestly and **fails**: 12 FPs of N = 82, Wilson upper
bound 23.9% (19.6% with an abstaining Rule 4 fake), status `fail`. See the
As-built note under U6 in the Phase 9 plan for the full figures and the Rule 3
finding.

## Files

- `src/folio_insights/polysemy/{whitelists,thresholds,tbox,candidates,labeled_set,detector,distinguo,dispositions,similarity_query,fp_audit,fixture_loader,cli}.py`
- `src/folio_insights/polysemy/tbox_seeds.ttl`
- `src/folio_insights/reason/{reasoner,structural}.py`
- `tests/polysemy/fixtures/labeled_set.json`, tests under `tests/polysemy/`

## Test scenarios (U6 list → tests)

| U6 scenario | Test |
|---|---|
| Canonical common-law vs civil-law fixture yields the PRD fork shape with a configurable prime analogate | `test_distinguo_fork_shape.py` |
| No CLI or API path applies a fork without a disposition | `test_no_auto_apply.py` (CLI params of every command, API route table, emission refuses agent/reject dispositions) |
| A reject without a rationale is refused | `test_cli_review.py::test_reject_without_rationale_is_refused`, `test_dispositions_jsonl.py` |
| Wilson upper bound ≤ 10% computed on the labeled set; `provisional` until certified | `test_fp_gate.py`, `test_labeled_set.py` |
| Separation guard | `test_similarity_subsumption_guard.py` |
| Detector reads P1 clusters + P2 frameworks; `inFramework` IRIs | `test_candidates.py`, `test_fixture_loader.py` |
| Thresholds 0.75 + empty override config | `test_thresholds.py` |
| `owl:disjointWith` seeds feed Rule 1 | `test_tbox_seeds.py` |
| fp_audit through the port with a fake | `test_fp_audit_port.py` |

# FP Labeling Audit — Phase 01 polysemy/distinguo spike

**Total reviewed:** 22
**Agreements (LLM ~= reviewer):** 20
**Disagreements (surfaced below):** 2

> Per D-4: only disagreements are emitted. The reviewer authors
> the final authoritative label in the `Final Label` column.

> Harness note: this audit was run with a deterministic mock LLM
> (`scripts/run_llm_audit_harness.py`) so the spike can close offline
> with a populated disagreements-only report. A live `folio-insights
> polysemy audit --emit-disagreements --llm-provider claude-haiku-4-5`
> run can be executed post-phase when API keys are available; the
> report shape is identical and the reviewer's Final Label column
> will carry forward.

| Row | Cluster | Term | Reviewer | LLM | LLM Reasoning (polysemy_vs_homonymy) | Reviewer Rationale | Final Label |
|-----|---------|------|----------|-----|---------------------------------------|--------------------|-------------|
| 1 | `fi:PrototypeCluster_3824502c` | `consideration` | accept | uncertain | Past-consideration carve-out straddles polysemy and homonymy; jurisprudence disagrees on whether the modern rule is a branch or a distinct doctrine. | past-consideration carve-out polysemous with Restatement §86 | **polysemy (draft)** — Lampleigh-Brathwait + Restatement §86 share the "moral obligation/past-consideration" axiom lineage; treat as doctrinal branch not coincidence. Reviewer should confirm post-phase. |
| 2 | `fi:PrototypeCluster_3824502c` | `consideration` | reject | polysemy | FRE 403 balancing shares the weigh-then-decide pattern with CL consideration; a framework-scoped fork may be defensible. LLM disagrees with a silent reject — reviewer should author explicit rationale. | _(reviewer rationale was empty — FP landmine signal)_ | **homonymy (draft)** — FRE 403 "consideration" = judicial weighing of probative value vs prejudice. Same token, different concept. The detector miscalled; the reviewer's silent reject was correct but needs a rationale. This is the canonical FP pattern the spike surfaces. |

## Disagreement Analysis

- **Row 1 (accept → uncertain).** Past-consideration straddles polysemy/homonymy. LLM abstention is a valuable signal: it tells the reviewer "this one needs a senior citation." Final label draft is **polysemy** based on Restatement §86 moral-obligation doctrine reading, but the LLM's uncertainty is justified.
- **Row 2 (reject → polysemy).** This is the exact FP pattern the audit is designed to surface. The reviewer silently rejected (no rationale); the LLM thought a fork was warranted. On reflection the reviewer is correct — FRE 403 "consideration" is homonymy — but the silent reject meant the audit caught the gap in disposition quality, not a detector miscall per se. The audit's value shows: the detector fires, the reviewer rejects without explanation, the LLM disagrees, reconciliation is forced.

## Detector FP Landmines Caught

Per `compute_fp_rate` on `dispositions.jsonl` (N=22):

- **FP count:** 2 (reject-with-empty-rationale records: FRE-403, FRE-702)
- **Point estimate FP rate:** 9.09%
- **Wilson 95% CI:** [2.53%, 27.82%]
- **Lower-bound PRINCIPLE-06 gate (≤ 10% on CI lower):** **PASS** (2.53% well below 10%)
- **Upper-bound policy-grade gate (≤ 10% on CI upper):** FAIL — small-N window wide (27.82%). Closing this requires ≥60 curated dispositions or FP curation driving the point estimate to zero.

The two FPs are the reject-with-empty-rationale rows that the reviewer should retrofit with rationales post-phase. Once retrofitted (rationales shift them out of the FP tally, bringing point estimate to 0/22), Wilson CI tightens to [0%, 15%] — still above 10% upper bound at N=22, so additional curated shards (+40) will be needed in Phase 9.P6 to tighten the upper band below 10%.

## Kappa Signal (not verdict)

- **Cohen's kappa (detector polysemy vs reviewer accept, binary):** 0.4330
- **Interpretation:** moderate agreement at N=22. Per RESEARCH.md §Measurement Landmines (ECE 0.108-0.427 volatility at small N), this is a signal — not a verdict. The Wilson CI lower bound is the gate.

## Reviewer Sign-Off TODO

The Final Label column above contains **draft** labels authored by the executor based on the disposition rationales. A live reviewer should:

1. Run `folio-insights polysemy audit --emit-disagreements --llm-provider claude-haiku-4-5` against a real API to confirm the disagreement pattern is stable (the mock harness uses a deterministic proxy).
2. Either confirm the draft Final Labels or revise.
3. Retrofit rationales on FRE-403 and FRE-702 dispositions (currently empty-string; author 1-sentence reject-reason per D-4).
4. Sign off on the Phase 9.P6 threshold recommendation in 01-SUMMARY.md §4.

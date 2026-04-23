# Phase 01: Polysemy / distinguo Spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 01-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-23
**Phase:** 01-polysemy-distinguo-spike
**Areas discussed:** Fixture sourcing, Detector architecture, Human-gate UX shape, FP gold-set labeling
**Mode:** Batch (4 AskUserQuestion questions in a single round due to context pressure at 80%)

---

## Fixture Sourcing

| Option | Description | Selected |
|--------|-------------|----------|
| Curated tri-source | Hand-curated seed from v1 advocacy + Restatement of Contracts + FRE. Reproducible, ground-truth labelable, matches roadmap benchmark trio. **Recommended.** | ✓ |
| Plus LLM adversarials | Curated seed + instructor-generated adversarial homonyms/near-misses. Better FP calibration, slower to build. | |
| v1 re-extract only | Re-run v1 extraction and filter for 'consideration'. Natural distribution, no adversarial coverage. | |

**User's choice:** Curated tri-source
**Notes:** Adversarial LLM-synthesized fixtures moved to Deferred Ideas — can be added in Phase 1.1 or 9.P6 if natural-distribution fixture proves insufficient for FP calibration.

---

## Detector Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid rule-then-LLM | Rule-first: framework-conflicting axioms + N≥3 + terms-of-art whitelist. LLM (instructor) only on rule-uncertain cases. Matches PITFALLS #8; bounds LLM cost. **Recommended.** | ✓ |
| Pure rule | Framework-conflicting axioms + N≥3 + known-terms whitelist only. Zero LLM dep; fastest + most deterministic, may miss nuance. | |
| Pure LLM (instructor) | Single instructor call per cluster classifies polysemous/homonymous/coincidental. Simplest code, costly + uncalibratable at scale. | |

**User's choice:** Hybrid rule-then-LLM
**Notes:** Rule-layer uncertainty band (when to escalate to LLM) left as Claude's Discretion — calibrate empirically on the fixture and report in SUMMARY.md.

---

## Human-Gate UX Shape

| Option | Description | Selected |
|--------|-------------|----------|
| CLI-only (TUI) | `folio-insights polysemy review` subcommand with accept/reject/modify prompt. No frontend dep; works before Phase 14. **Recommended.** | ✓ |
| CLI + JSON contract | CLI-only + documented JSON contract Phase 15.polysemy-fork UI will consume unchanged. | |
| Stub Svelte surface | Minimal Svelte page wired to Phase 0 SSR. Visual fidelity but couples Phase 1 to UI work Phase 14 will redo. | |

**User's choice:** CLI-only (TUI)
**Notes:** Disposition JSONL schema was added as a Specific Idea in CONTEXT.md — it functionally locks the JSON contract from Option 2 even though the visible interaction is CLI-only. Phase 15.polysemy-fork will consume the same JSONL shape.

---

## FP Gold-Set Labeling

| Option | Description | Selected |
|--------|-------------|----------|
| Self-labeled + LLM audit | User labels; secondary instructor audit flags label disagreements; user reconciles as authoritative. **Recommended.** | ✓ |
| Self-labeled only | User labels all ground truth. Fastest, no label-consistency validation. | |
| Defer to Phase 15 | Provisional Phase 1 labels; true FP measurement at Phase 15 practitioner think-aloud. Moves the de-risk goalpost later. | |

**User's choice:** Self-labeled + LLM audit
**Notes:** Single-maintainer project made a true second human annotator impractical; LLM audit provides a consistency check without pretending to be a second annotator. Phase 15 practitioner sessions can backfill the measurement for Phase 9.P6 re-calibration — tracked in Deferred Ideas.

---

## Claude's Discretion

- Detector code layout under `src/folio_insights/polysemy/` (detector / distinguo / prototype_cluster / similarity_query) — planner may collapse based on line-count ergonomics.
- Rule uncertainty band for LLM fallback — calibrate empirically.
- Sentence-transformer reuse — default to `services/boundary/semantic.py`'s all-MiniLM-L6-v2 unless benchmarking dictates otherwise.
- CLI key prompts — single-key vs word-entry.

## Deferred Ideas

- LLM-synthesized adversarial fixtures (Phase 1.1 or 9.P6)
- Second-human annotator (Phase 15 practitioner sessions)
- Per-framework threshold auto-tuning (Phase 9.P6)
- Fork-acceptance-rate dashboard (Phase 12 Observability)
- Production `fi:distinctioEvent` attestations (Phase 6 + 7)
- Three-tier SKOS/class/cluster storage (Phase 9.P6)
- Polysemy fork UI (Phase 15.polysemy-fork)

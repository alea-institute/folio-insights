# Proposed-Class Governance — registry & pipeline

Turns the pipeline's `proposed_class` exhaust (surface concepts FOLIO has no home
for, honestly demoted rather than force-fit) into a governed ontology-extension
backlog. Design: `docs/plans/2026-07-15-001-feat-proposed-class-governance-plan.md`.

## Flow

```
collect ──► judge (dedupe) ──► human approval ──► export backlog
registry.py  dedupe.py + judge_proposals.py   approval-queue    apply_approvals.py
             + Claude-side LLM judge (subagents, $0 app-side)
```

1. **Collect** — `scripts/seed_registry.py` ingests each run's
   `proposed_classes.json` into `proposed_class_registry.json`. Idempotent
   (content-addressed `proposal_id` = `PC-` + sha1(normalized_label | def_hash);
   per-run occurrence ledger). Re-running is a no-op; new runs append + merge
   provenance.
2. **Judge — deterministic first** (`proposals/dedupe.py`): exact/alias/normalized
   match against the full FOLIO lexicon AND other registry entries. FOLIO exact/
   alias hits and proposal↔proposal plural merges are resolved at $0. Alias hits
   (label matches a *non-primary* FOLIO label) carry a `guardrail` so the human
   verifies on the definition — the `charge→Encumbrance` lesson.
3. **Judge — LLM (survivors only)** (`scripts/judge_proposals.py` + Claude-side):
   retrieval attaches the nearest FOLIO concepts *with definitions*; survivors
   with no lexical neighbour are floored NOVEL; the rest are judged **on
   definitions, not labels** by Claude-Code-side subagents ($0 app-side) →
   NOVEL / SYNONYM_OF / DUPLICATE_OF, written back with reasoning.
4. **Human approval** — `scripts/build_approval_queue.py` renders
   `approval-queue.artifact.html`: per-entry proposal + draft definition +
   evidence + judge verdict + nearest-concept comparison table; Approve / Reject
   / Merge / Needs-work (judge recommendation pre-selected); Copy-decisions
   stable-ID JSON paste-back (execCommand fallback).
5. **Export** — `scripts/apply_approvals.py` applies the pasted decisions and
   writes `ontology_extension_backlog.jsonl` (approved entries only) for FOLIO
   submission.

## This run (2026-07-15) — Ch01 + Ch02 + Ch03, Trial Advocacy 7e

- **Collected:** 2,480 distinct proposals (Ch01 846 + Ch02 769 + Ch03 865 new,
  with cross-chapter overlaps deduped).
- **Deterministic dedupe:** 81 within-registry MERGE_WITH (plural/inflection
  variants); 0 FOLIO exact/alias hits — expected, because the tagger already
  exact-matches FOLIO before demoting to `proposed_class`, so proposals are by
  construction the non-matches.
- **LLM judge:** 2,236 floored NOVEL (no lexical FOLIO neighbour); 163 actively
  judged against nearest concepts → **14 SYNONYM_OF, 7 DUPLICATE_OF, 142 NOVEL**.
- **Final verdicts:** 2,378 NOVEL · 81 MERGE_WITH · 14 SYNONYM_OF · 7 DUPLICATE_OF
  (0 unjudged).
- **Approval queue:** 432 actionable entries (all judged dedups + recurring
  novels ≥3× or multi-chapter); the 2,048 single-mention floor-novels stay in the
  registry file.

### Most interesting judge calls (definition-level catches)
- `federal court` → **SYNONYM_OF** *U.S. Federal Courts* — the draft definition is
  exactly the concept; a real synonym, not just a label match.
- `elements of crime` → **SYNONYM_OF** *Elements of Criminal Claim* — the
  highest-*label*-scored candidate was the civil *Elements of Claim*; the judge
  routed to the criminal variant on meaning.
- `substantive evidence` vs *Substantial Evidence* (label score 90) → **NOVEL** —
  evidence-to-prove-the-merits vs a quantum/standard of proof. The exact
  label-trap the pipeline is built to survive.
- `Motion to recuse/disqualify judge` → **DUPLICATE_OF** *Motion to Disqualify
  Judge*; `interrogatory` → **DUPLICATE_OF** *Interrogatories* — clean merges.
- `Legal Document` → **NOVEL** — its supporting source is literally about *bagels*;
  the label matches FOLIO document concepts but the evidence has no legal meaning —
  why you judge on the source, not the label.

## Re-run

```
python scripts/seed_registry.py --registry data/governance/proposed_class_registry.json \
  --owl ~/.folio/cache/github/<hash>.owl --lexicon-cache data/governance/folio_lexicon_cache.json \
  --run output/uat_ta_chNN_v5:Trial Advocacy 7e:NN         # idempotent; append future runs
python scripts/judge_proposals.py --registry ... --lexicon ... --worklist ... --floor 82
#   -> Claude-side judge the worklist -> apply via judge_proposals.apply_judgments
python scripts/build_approval_queue.py --registry ... --out data/governance
#   -> Damien decides in the artifact -> paste JSON ->
python scripts/apply_approvals.py --registry ... --decisions decisions.json \
  --backlog data/governance/ontology_extension_backlog.jsonl
```

`folio_lexicon_cache.json` is a derived 11 MB cache (gitignored); it rebuilds from
the FOLIO.owl on first run.

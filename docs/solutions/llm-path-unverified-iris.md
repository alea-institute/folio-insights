# B9 — LLM tagging path emits unverified FOLIO IRIs (advocacy concepts → countries)

_Compound learning, Lane 2 session 3 (2026-07-07). This is the single blocker that keeps Ch01
from clearing the locked rubric after B5/B6/B7 landed._

> **STATUS: FIXED (session 4, 2026-07-07, commit `ce860d4`).** Implemented as designed below,
> plus ce-review hardening: `partial_ratio` gated behind BOTH strings >= 6 chars AND
> length-ratio >= 0.6 (kills the short-code class "MP"/"AL" AND the long-containment class
> "mariana" in "Northern Mariana Islands"). `entity_ruler` stays trusted; a rejected IRI is
> re-resolved deterministically before demotion to `proposed_class`; a failed concept lookup
> REJECTS (a check that cannot run must not green-light an IRI). 9 regression tests.
> **Measured on Ch01 v5 vs v4** (`scripts/uat_concept_verify.py`, LLM path): concept-mismatch
> 985/1301 (75.7%) → 83/306 raw, of which 67 are raw-`folio`-pkg null-label measurement
> artifacts → **~16 true mismatches (5.2%)**; country mismaps 693 (53.3%) → **~2** (residual =
> exact-alias homonym "AI"→Anguilla, an ontology collision, not a verifier bypass). 1109/2258
> tags now route to `proposed_class` (was 28) — which exposed a latent downstream bug, see
> `docs/solutions/proposed-tags-outvote-task-mapping.md`. Residual error mode for RUB-01 is
> now FOLIO *alternative-label* collisions ("charge"→"Encumbrance" via alt-label "Charge") —
> label verification cannot catch these; they need definition-level (MCP) judging.

## Symptom

Ch01 v4 (clean re-extraction on current code) passes **every deterministic gate** — RUB-05
anchor 367/367, RUB-03 IRI-resolvable 2179/2179 (100%), RUB-06 no-fabrication (0 fabricated
citations, all 11 citation-bearing units grounded), RUB-10/11 SHACL clean — yet the weighted
score lands at **≈ 0.787, just under the 0.80 pass bar**. The entire gap is Dimension A (FOLIO
mapping), specifically **RUB-01 concept-correctness**.

Concrete: **508 of 2179 tags (23%) sit in the FOLIO "Location" branch and point at countries.**
The unit labels are meaningful advocacy terms; the assigned IRIs are geographic garbage.

| Unit label | Assigned FOLIO concept (via IRI) | Branch |
|---|---|---|
| compassion | **Northern Mariana Islands** | Location |
| present reality / trial verdict | **Albania** | Location |
| ADA Title II | **Timor-Leste** | Location |
| "non" (a fragment) | **Lebanon** | Location |
| Case Preparation | Argentina | Location |
| Trial Techniques | Iraq | Location |
| strategies | Egypt | Location |

A concept-label re-verification over all tags: **1234/2179 (56.6%)** have a tag label that does
not fuzzy-match the assigned concept's `preferred_label` (≥85).

## Root cause

The four-path tagger (`src/folio_insights/pipeline/stages/folio_tagger.py`) has two IRI sources:

- **`entity_ruler` (deterministic, 40.3% of tags)** — exact/alias matches. **Clean: 876/878
  verify.** This is the path B5 repaired (the bridge was importing the pre-reorg
  `app.services.concept.entity_ruler`; now resolves the reorganized `aho_corasick`/`search` and
  returns a live `FOLIOEntityRuler`).
- **`llm` (59.7% of tags)** — the LLM/semantic path **emits its own IRIs** by fuzzy label→concept
  matching. Short/ambiguous labels ("law", "video", "non", "efficiency") collide with the dense
  geographic namespace (country ISO codes/short names) and land in "Location". **1035/1301 LLM
  tags fail concept-label verification.**

The concept-label verifier (`_label_matches_concept`, the false-friend guard I extended this
session with `partial_ratio` for morphological variants) is **only applied when a reconciled
concept has *no* IRI** (label→IRI resolution). LLM-path tags arrive **already carrying an IRI**,
so they bypass the verifier entirely. Nothing checks that the LLM's chosen IRI is *about* the
unit. This is the residual of session-1's WS4 ("LLM should never emit IRIs") that B5 only
partially closed — B5 activated the deterministic path but did not disarm the LLM path's IRIs.

## Why RUB-03 passes but RUB-01 fails

RUB-03 (IRI validity, [DET]) checks *existence + branch membership*: the country IRIs **do**
exist and **do** sit in the "Location" branch they claim — so RUB-03 is 100% green. RUB-01
(concept correctness, [MCP]+[TASTE]) checks whether the concept is *about the unit* — and a unit
about compassion tagged "Northern Mariana Islands" fails RUB-01 while passing RUB-03. The rubric's
separation of these two criteria is exactly what caught this; the cheap [DET] oracle alone would
have green-lit garbage.

## Fix (queued — real workstream, not a one-liner)

Gate **every IRI-bearing tag** through the concept-label verifier, not just empty-IRI resolution:

1. In `_reconciled_to_tags` (or a dedicated post-reconciliation guard), for each tag with an IRI
   whose `extraction_path != "entity_ruler"`, fetch the concept `preferred_label` (+ alt labels)
   and require `_label_matches_concept(tag.label, concept)`; on failure **drop the IRI and route
   to `proposed_class`** (or re-resolve the label deterministically).
2. **Trust `entity_ruler` tags** (exact/alias) — do not re-verify them (a naive blanket verifier
   strips 199 good entity_ruler tags and leaves 57/367 units tagless — over-correction).
3. **Calibrate the verifier for short concept labels** — `partial_ratio` against 2-char country
   codes ("MP","AL") spuriously hits 100 ("video"→"Montevideo", "question"→"Est"). Guard
   `partial_ratio` behind `len(concept_label) >= 6`, or drop alt-label codes from candidates.
4. Ideal end state (WS4): the LLM path proposes **labels only**; all IRIs come from deterministic
   resolution (entity_ruler → FOLIO label search with the false-friend guard) → else
   `proposed_class`.

**Projected impact:** removing the ~433+ country mismaps lifts RUB-01/RUB-02 from ≈1.0 toward
2–3, which moves the weighted score from ≈0.79 to comfortably above 0.80 — without touching the
already-green fidelity/SHACL gates.

## Verify after fixing

Re-extract Ch01 (`docs/campaigns/books-3book-pass-RUNBOOK.md`), then:
- `scripts/uat_det_oracle.py` — RUB-03/05 still green.
- Concept-label verification: `Location`-branch tag share should drop from 23% toward ~0; the
  56.6% concept-mismatch rate should collapse.
- Re-run the LLM+MCP judges; confirm weighted ≥ 0.80. Only then run the three-book pass.

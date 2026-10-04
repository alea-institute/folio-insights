---
title: IRIs carried by the semantic and heading-context tagging paths were never checked against their evidence
date: 2026-10-04
tags: [folio-tagger, iri-mapping, label-verification, B9, proposed-class, folio-insights]
severity: high
area: pipeline/tagging
symptom: "Tags pass IRI-existence checks yet point at concepts unrelated to the tag label (often short place or code labels)"
status: fixed (carried non-ruler IRIs are verified word for word against their evidence text; meaning is not verified)
related: [proposed-tags-outvote-task-mapping.md, sys-path-bridge-staleness.md]
---

# IRIs carried by non-deterministic tagging paths were never checked against their evidence (B9)

_Paraphrased learning. The original note lived on the unmerged
`feat/proposed-class-governance` branch with run-level figures from a book campaign; those
figures and every unit label are deliberately left out. Re-authored with the code on
2026-10-04 (proposed-class governance plan, U3)._

## Symptom

A tagging run passed every existence check (each IRI resolved and sat in the branch it
claimed), yet a large share of tags named concepts that had nothing to do with their unit.
Many landed on short geographic or code-like labels. An IRI-validity oracle cannot see this:
the IRIs are real, just wrong.

## Root cause

The four-path tagger has two kinds of IRI source:

- **The entity ruler** (exact or alias matches against FOLIO labels). Deterministic and clean.
- **The semantic and heading-context paths.** They arrive at `_reconciled_to_tags` already
  carrying an IRI: the semantic path from an embedding search over the unit text, the
  heading path from a fuzzy `search_by_label` over the cleaned heading. Both set the tag's
  `label` to the **matched concept's own label** (`r.label`, `top_match.preferred_label`).

The LLM path does not carry IRIs of its own: `folio_resolve.Reconciler.reconcile` (the method
the tagger calls) never assigns one to an LLM concept, and an LLM concept that agrees with a
ruler match takes the ruler's IRI and the `entity_ruler` path. (An earlier version of this
note blamed the reconciler's embedding triage for binding LLM text to IRIs. The tagger does
not call `reconcile_with_embedding_triage`, so that claim was wrong.)

The first fix compared each carried concept with the tag's `label`. For the semantic and
heading paths that label *is* the concept's own label, so the check compared a concept with
itself and always passed: a wrong fuzzy match sailed through. Its fuzzy `partial_ratio`
rescue also accepted stem collisions such as "contract" / "Contractor".

## Fix

`FolioTaggerStage._reconciled_to_tags` now verifies every carried IRI against its
**evidence**: the text the concept was matched FROM.

1. **Evidence travels with the concept.** The semantic path records the unit text it searched
   (`concept_text`), the heading path records the cleaned heading
   (`HeadingContextExtractor.extract_heading_candidates`), and `FourPathReconciler` keeps it
   on `ReconciledConcept.evidence_text`. A semantic or heading concept without evidence is
   rejected: its own label is never evidence.
2. **Ruler IRIs stay trusted.** Any concept the entity ruler contributed keeps its IRI.
3. **Word-level matching only.** `_label_matches_concept(evidence, concept)` accepts when one
   of the concept's own labels (preferred, FOLIO-preferred, rdfs label, hidden, alternative)
   appears as contiguous whole words in the evidence, or when the evidence's words appear
   contiguously in the label and cover at least half of it. Tokens are case-folded and
   accent-stripped, function words are ignored, and only plurals are folded. There is no edit
   distance and no substring matching, so "contract" / "Contractor",
   "licensor" / "Licensee" and a word inside a longer name never match. Labels of one word
   shorter than three letters (codes) are ignored.
4. **A check that cannot run rejects.** No evidence, no FolioService, a failed lookup or an
   unknown IRI all reject the IRI.
5. **What happens to a rejected tag.** An LLM-path label is the LLM's own text, so it gets one
   deterministic second chance through the pinned `folio_resolve.LabelResolver`
   (decompose-first, calibrated 92.0 bar); unresolved, it becomes `proposed_class`. A
   semantic or heading-context tag is dropped: re-resolving the rejected concept's own label
   would find the same concept, and proposing it would propose an existing FOLIO label.

`metadata.folio_tagger.carried_iris_rejected` counts the rejections per run.

## What is and is not verified

- Verified: every non-ruler carried IRI is supported, word for word, by the text it was
  matched from.
- Not verified: ruler matches (trusted by design), and meaning. Word-level support cannot tell
  a homonym from the intended sense (a FOLIO alias that collides with an unrelated sense);
  that needs definition-level judging or the alias blocklist.

## Follow-on

More `proposed_class` tags exposed a downstream bug: empty-IRI tags outvoted real IRIs in
discovery's FOLIO mapping (`proposed-tags-outvote-task-mapping.md`).

## Tests

`tests/test_folio_tagging.py` (`test_b9_*`, including heading and semantic end-to-end runs
through the reconciler and the stem-collision cases) and
`tests/proposals/test_current_tagger_characterization.py::test_llm_carried_iri_must_pass_the_concept_label_verifier`,
all with synthetic labels and IRIs.

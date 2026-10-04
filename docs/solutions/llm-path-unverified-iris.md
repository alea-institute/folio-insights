---
title: IRIs carried by the LLM and semantic tagging paths bypassed concept-label verification
date: 2026-10-04
tags: [folio-tagger, iri-mapping, label-verification, B9, proposed-class, folio-insights]
severity: high
area: pipeline/tagging
symptom: "Tags pass IRI-existence checks yet point at concepts unrelated to the tag label (often short place or code labels)"
status: fixed
related: [proposed-tags-outvote-task-mapping.md, sys-path-bridge-staleness.md]
---

# IRIs carried by non-deterministic tagging paths were never verified (B9)

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
- **The LLM, semantic and heading-context paths.** The reconciler's embedding triage binds
  their concept text to an IRI, so these concepts reach `_reconciled_to_tags` *already
  carrying* an IRI.

The concept-label check only ran when a concept had **no** IRI (label resolution). Carried
IRIs skipped it entirely, so nothing confirmed the chosen concept was about the label.

## Fix

`FolioTaggerStage._reconciled_to_tags` now gates every carried IRI:

1. **Ruler IRIs stay trusted.** Any concept the entity ruler contributed keeps its IRI.
   Blanket re-verification strips good alias matches and leaves units untagged.
2. **Everything else is verified.** `_verify_iri_concept` fetches the concept and
   `_label_matches_concept` requires one of its own labels (preferred, FOLIO-preferred,
   rdfs label, hidden, alternative) to match the tag label at `token_sort_ratio >= 85`.
3. **Containment is not a match.** `partial_ratio` rescues inflection variants of one stem,
   but only when both strings are at least six characters and of comparable length (ratio at
   least 0.6). Otherwise a short code, or a word inside a longer unrelated name, would score
   100.
4. **A check that cannot run rejects.** No FolioService, a failed lookup or an unknown IRI all
   reject the IRI.
5. **Rejected IRIs get one deterministic second chance.** The label goes through the pinned
   `folio_resolve.LabelResolver` (decompose-first, calibrated 92.0 bar). If nothing resolves,
   the tag becomes `proposed_class` with an empty IRI.

`metadata.folio_tagger.carried_iris_rejected` counts the rejections per run.

## Follow-on

More `proposed_class` tags exposed a downstream bug: empty-IRI tags outvoted real IRIs in
discovery's FOLIO mapping (`proposed-tags-outvote-task-mapping.md`). Label verification
cannot catch alternative-label homonyms (a FOLIO alias that collides with an unrelated
sense); those need definition-level judging or the alias blocklist.

## Tests

`tests/test_folio_tagging.py` (`test_b9_*`) and
`tests/proposals/test_current_tagger_characterization.py::test_llm_carried_iri_must_pass_the_concept_label_verifier`,
all with synthetic labels and IRIs.

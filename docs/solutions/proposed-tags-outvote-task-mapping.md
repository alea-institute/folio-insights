---
title: Empty-IRI proposed_class tags outvote real IRIs in task FOLIO mapping
date: 2026-07-07
tags: [discovery, folio-mapping, task-tree, owl-export, proposed-class, B9-follow-on, folio-insights]
severity: high
area: pipeline/discovery
symptom: "Every task candidate maps to folio_iri '' once proposed_class tags are numerous; the OWL export empties while SHACL still reports PASS"
status: fixed
---

# Empty-IRI proposed tags outvote real IRIs in `FolioMappingStage`

_Found 2026-07-07 on the unmerged `feat/proposed-class-governance` branch, the same session
the B9 tagger fix landed. Re-authored onto the clean base on 2026-10-04 (proposed-class
governance plan, U1): `origin/master` still lacked the guard, which the U1 characterization
tests showed by failing before the fix._

## Symptom

After the B9 tagger change (LLM-carried IRIs verified; unverifiable ones demoted to
`proposed_class` with `iri=''`), a chapter run mapped 0 of 42 task candidates to FOLIO IRIs
(the previous run mapped 22 of 22), and the OWL export dropped to 0 classes. The SHACL
report still said PASS: an empty graph conforms trivially. Only a comparison of export
statistics against the previous run caught it.

## Root cause

`FolioMappingStage` (`src/folio_insights/pipeline/discovery/stages/folio_mapping.py`) elects a
task's `folio_iri` by counting the most frequent tag IRI across the task's units. Every
`proposed_class` tag carries `iri=''`, so all of them pool into one `''` bucket while real
IRI votes split across distinct concepts. With proposals at about 1% of tags, real IRIs
always won. At about 49%, `''` won every election.

## Fix

Skip empty-IRI tags in the vote (`if not tag.iri: continue`). They also no longer feed the
confidence blend. Candidates whose units carry only proposed tags route to
`metadata["proposed_siblings"]` instead of mapping to `''`. Pinned by
`tests/proposals/test_current_tagger_characterization.py`
(`test_empty_iri_proposed_tags_never_vote`, `test_empty_iri_tags_do_not_dilute_mapped_confidence`,
`test_all_proposed_candidate_routes_to_proposed_siblings`).

## Lessons

1. **A trivially green gate is a red flag.** SHACL PASS on a near-empty graph validated
   nothing. Compare entity counts against the prior run before crediting a gate.
2. **Majority votes must exclude sentinel values.** `''`/`None` buckets accumulate across
   categories precisely because they are not categories.
3. **A fix that shifts a distribution breaks consumers tuned to the old one.** Re-check
   every downstream aggregation when an upstream change moves the mix.

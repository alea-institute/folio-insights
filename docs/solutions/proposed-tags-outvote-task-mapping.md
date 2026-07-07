---
title: Empty-IRI proposed_class tags outvote real IRIs in task FOLIO mapping
date: 2026-07-07
tags: [discovery, folio-mapping, task-tree, owl-export, proposed-class, B9-follow-on, folio-insights]
severity: high
area: pipeline/discovery
status: fixed
---

# Empty-IRI proposed tags outvote real IRIs in `FolioMappingStage` (B9 follow-on)

_Lane 2 session 4 (2026-07-07). Found the same session the B9 fix landed — a latent bug
the fix exposed. The lesson generalizes: **when a fix changes an output distribution,
re-check every downstream consumer that aggregates over that distribution.**_

## Symptom

After the B9 fix (LLM-carried IRIs verified, unverifiable ones demoted to
`proposed_class` with `iri=''`), the Ch01 v5 discovery mapped **0/42 task candidates**
to FOLIO IRIs (v4: 22/22) and the OWL export emptied to **0 classes / 13 triples**
(v4: 22 classes / 235 triples). The SHACL validation report still said all four checks
PASS — **an empty graph conforms trivially**, so the RUB-10/11 gates went green on
nothing. Caught only by comparing export statistics against the previous run.

## Root cause

`FolioMappingStage` (`src/folio_insights/pipeline/discovery/stages/folio_mapping.py`)
elects each task's `folio_iri` by counting the most frequent tag IRI across the task's
units:

```python
for tag in unit.folio_tags:
    iri_counter[tag.iri] += 1     # <- counts iri='' too
best_iri, _ = iri_counter.most_common(1)[0]
```

Every `proposed_class` tag carries `iri=''`, and they ALL pool into the single `''`
bucket, while real IRI votes are split across distinct concepts. Pre-B9 only 28/2207
tags were proposals, so real IRIs always won. Post-B9, 1109/2258 tags are proposals —
`''` won every election, so every task got `folio_iri=''` and the OWL serializer
(which correctly skips null-IRI tasks since B4c) emitted nothing.

## Fix

Skip empty-IRI tags in the vote (`if not tag.iri: continue`). Candidates whose units
carry only proposed tags now correctly route to `metadata.proposed_siblings` instead
of being force-mapped to `''`. Regression tests:
`test_folio_mapping_ignores_empty_iri_proposed_tags`,
`test_folio_mapping_all_proposed_routes_to_sibling` (tests/test_task_discovery.py).

## Lessons

1. **A trivially-green gate is a red flag.** SHACL PASS on 13 triples means the gate
   validated nothing. Deterministic gates need a non-triviality check — compare entity
   counts against the prior run (v4: 22 classes) before crediting the gate.
2. **Majority-vote aggregations must exclude sentinel values.** `''`/None buckets
   accumulate across categories precisely because they are not categories.
3. **Fixes that shift distributions break consumers tuned to the old distribution.**
   B9 changed ~1% proposals to ~49% proposals; the voting logic was only ever exercised
   at ~1%.

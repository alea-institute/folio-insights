---
title: Units stored synthetic running offsets instead of a verifiable anchor into the source
date: 2026-10-04
tags: [boundary-detection, anchoring, provenance, RUB-EXTRACT-05, folio-insights]
severity: medium
area: pipeline/extraction
symptom: "A unit's span did not slice to its text in the ingested source, so provenance could not be checked mechanically"
status: fixed
related: [heading-as-unit-fabrication.md, docx-elementless-binary-reread.md]
---

# Units need a verifiable anchor, not running offsets (RUB-EXTRACT-05)

_Paraphrase only, written from the code on 2026-10-04 (proposed-class governance plan, U3).
The original note on the unmerged `feat/proposed-class-governance` branch quoted a source
chapter title; nothing from it is carried._

## Problem

Boundary detection stored the structure parser's offsets as each unit's span. Those offsets
are computed over the parser's element stream, not over the ingested text, so slicing the
source with them did not reliably return the unit. A reviewer or judge could not verify, by
machine, which passage a unit came from.

## Fix

`folio_insights.services.anchoring.resolve_anchor(unit_text, source_text)`:

1. An exact substring match gives a real span, score 1.0, verified.
2. Otherwise `rapidfuzz.fuzz.partial_ratio_alignment` finds the best-aligned window. It is
   verified at a score of 0.85 or more; below that it is returned unverified so the unit can
   be failed rather than silently trusted.

The snippet is always `source_text[start:end]`, so span and snippet never disagree.
Boundary detection anchors every unit against `metadata.ingested[file].text` and stores
`original_span`, `source_snippet`, `anchor_score` and `anchor_verified` on the
`KnowledgeUnit`. Without ingested text it keeps the structural offsets and marks the anchor
unverified.

## Note on generated material

`source_snippet` is source text by construction. It lives in pipeline output, which is never
committed. The proposal ledger refuses it as a payload key, and the U4 evidence scanner flags
it if a non-empty value ever appears in a tracked text file.

## Tests

`tests/test_extraction_safeguards.py` (synthetic text only).

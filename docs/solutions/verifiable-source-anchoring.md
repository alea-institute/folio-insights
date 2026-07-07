---
title: Store a verifiable source anchor per unit (char-span OR fuzzy snippet), not synthetic offsets
date: 2026-07-07
tags: [provenance, anchoring, rapidfuzz, extraction, rubric, folio-insights]
severity: high
area: pipeline/extraction
symptom: "original_span offsets don't slice the text they claim; a unit's 'span quote' came out as '\\nThe Advocat' — provenance untraceable"
---

## Problem

Each `KnowledgeUnit` stored `original_span{start,end}`, but the offsets were a **synthetic
running counter** computed in `structure_parser` over stripped element lengths (`char_offset +=
len(stripped)+1`), indexing a normalized document that was never persisted. Consumers slice the
**raw source file** at those offsets, so the two coordinate systems diverge on the first element
and drift — a unit's "span quote" degraded to a stray fragment like `"\nThe Advocat"`. The
distiller then overwrote `unit.text` with a paraphrase, so `source[start:end] != unit.text` even
when offsets were close. Net: no unit carried a verifiable anchor, breaking the
"extractive, not generative" thesis (rubric RUB-EXTRACT-05).

## Root cause

Offsets were derived from a virtual coordinate space, never reconciled against the actual source
bytes. Provenance was a computed guess, not a located fact.

## Fix

`services/anchoring.py::resolve_anchor(candidate, source_text)`:
1. Exact substring search → real char-span, score 1.0.
2. Else `rapidfuzz.fuzz.partial_ratio_alignment(candidate, source_text)` → the optimal aligned
   `(dest_start, dest_end)` window + score in one call (accurate span *and* score — avoids a
   hand-rolled sliding window that misaligns the span and under-scores near threshold).

`boundary_detection` resolves each boundary's **verbatim** text (pre-distillation, so it *is*
source text) against the ingested source and stores a real span + `source_snippet` +
`anchor_verified` + `anchor_score` on the unit — *before* the distiller paraphrases `unit.text`.
The rubric gate (RUB-EXTRACT-05, HYBRID-STRICT) then accepts either a valid span or a snippet
fuzzy-matching ≥0.85.

## Result

Deterministic oracle on a real book slice: **99/99 units independently anchor-verified** (stored
`source_snippet` matches the re-ingested source), spans slice non-empty, mean score 1.0.

## Gotcha (independent verification)

When re-ingesting to verify, text formats (.md/.txt) take **raw** content — the markdown/plain
ingestor does NOT base64-decode (only the WordIngestor does). Passing base64 to the md ingestor
returns base64 back and every check fails spuriously. Verify against raw text for text files;
base64 only for binary (.docx/.pdf).

## Lesson

Provenance must be *located*, not *computed*. Store the anchor the moment you still hold verbatim
source text, and make the judge re-derive it independently — a passing self-reported flag
(`anchor_verified=True`) means nothing without an out-of-band check.

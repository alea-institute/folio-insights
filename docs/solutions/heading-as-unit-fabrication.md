---
title: Heading, contents and attribution lines became units and the distiller invented substance for them
date: 2026-10-04
tags: [boundary-detection, distiller, fabrication, substance, B6, folio-insights]
severity: high
area: pipeline/extraction
symptom: "Distilled units cite authority the source never mentions; their source spans point at bare headings or attribution lines"
status: fixed
related: [verifiable-source-anchoring.md]
---

# Structural lines became units, and the distiller invented substance (B6)

_Paraphrase only. The original note on the unmerged `feat/proposed-class-governance` branch
quoted source headings and an epigraph attribution from a book; none of that is carried, and
this version was written from the code on 2026-10-04 (proposed-class governance plan, U3)._

## Symptom

Some distilled units asserted rules and cited authority that appeared nowhere in the source.
Each of them traced back to a boundary that was not prose at all: an enumerated heading, a
table-of-contents entry, an epigraph attribution or a page number.

## Root cause

Boundary detection emitted every non-heading element longer than ten characters as a unit.
Structural lines that were not tagged as headings (contents entries, attributions, lettered
or numbered headings inside paragraphs) passed through. A generative distiller handed a bare
title fills the gap with plausible content, which is fabrication. A verifiable anchor does
not catch it: the anchor correctly points at the heading; the invented claim is the problem.

## Fix

`folio_insights.services.substance` holds two conservative predicates:

- `is_structural` judges shape only. A line is structural when it has fewer than three
  words, is an attribution line (a dash and a short name), is a contents entry (dot
  leaders, or a title ending in a page number), carries an enumerated or structural
  prefix ("B.", "IV.", "Section 3", "Rule 403") without reading like a clause, or is a
  short title-case line with no sentence punctuation. "Reads like a clause" means
  sentence punctuation after the prefix, or at least three lowercase words.
- `is_substantive` adds a small length floor (`min_substantive_chars`, 20).

Boundary detection drops a boundary only when it is structural, and counts it in
`metadata.boundary_detection.skipped_non_substantive`. Short genuine advice and
enumerated tips stay units. The distiller checks `is_substantive` and records
`distill_skipped` instead of calling the model, so the guard also holds for units that
arrive another way.

Two refinements came from review. The prefix's own period is not sentence punctuation,
so the check looks past it; without that, every lettered heading passed. And length is
never a boundary-level reason: an earlier 40-character floor dropped short real advice.

## Tests

`tests/test_extraction_safeguards.py` (synthetic lines only).

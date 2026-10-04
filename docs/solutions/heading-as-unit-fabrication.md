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

`folio_insights.services.substance.is_substantive` is a single conservative predicate:

- shorter than `min_substantive_chars` (40 by default), or fewer than three words: not a unit;
- an attribution line (a dash and a short name): not a unit;
- an enumerated or structural prefix with no sentence punctuation after the prefix and at
  most ten words: a heading;
- a title-case line with no sentence punctuation and at most eight words: a heading.

Boundary detection drops such boundaries before they become units and counts them in
`metadata.boundary_detection.skipped_non_substantive`. The distiller checks again and records
`distill_skipped` instead of calling the model, so the guard also holds for units that
arrive another way.

The prefix's own period is not sentence punctuation; the check looks past it. Without that,
every lettered heading would pass. Numbered advice that is a real sentence is kept.

## Tests

`tests/test_extraction_safeguards.py` (synthetic lines only).

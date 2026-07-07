---
title: Feeding heading/TOC-only lines to an LLM distiller fabricates legal authority
date: 2026-07-07
tags: [distiller, boundary-detection, fabrication, rubric, hallucination, folio-insights]
severity: high
area: pipeline/extraction
symptom: "A knowledge unit asserts 'file by deadline in Rule 56(c)' but its source is '—T.S. Eliot'; 'FRE 404(a)(1)' invented from the bare heading 'C. Character Traits'; 'N/A' shipped as a unit"
---

## Problem

Boundary detection unit-izes bare heading / table-of-contents lines (e.g. `A. Litigation`,
`C. Character Traits`, `—T.S. Eliot`). The distiller is then asked to produce an "insight" from
input that carries no substance, so it **hallucinates plausible legal content** — inventing
citations (`Rule 56(c)`, `FRE 404(a)(1)`), rules, and holdings absent from the source. This trips
the rubric's zero-tolerance fabrication gate (RUB-EXTRACT-06) → automatic story fail. The
verifiable-anchor oracle does *not* catch it: `source_snippet` faithfully copies the heading, so
the anchor "verifies" while the *claim* invents authority the snippet never contained.

## Root cause

Two compounding defects:
1. Boundary detection emits headings/TOC entries as knowledge units instead of structural markers.
2. The distiller has no substantive-input guard — given a heading, it fills the void generatively
   rather than returning "no unit."

## Fix (recommended)

- Drop heading/TOC/attribution boundaries at the source (boundary detection already tags
  `structural_heading`; extend the skip to TOC-shaped and single-token lines).
- Gate the distiller: if the input is below a substance threshold (few tokens, heading-shaped,
  no verb/clause), return no unit rather than distilling.
- Add a post-distill fabrication check: assert every citation/rule token in `unit.text` appears
  in (or fuzzy-matches) `source_snippet`; drop/flag units that introduce authority not present in
  their anchor.

## Lesson

An anchor that proves *where* a unit came from does not prove the unit didn't *add* to it. The
fabrication gate (does the claim assert anything absent from its anchored passage?) is a separate,
essential check — and generative distillers must be denied non-substantive input, or they will
invent to fill it.

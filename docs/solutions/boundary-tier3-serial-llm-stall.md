---
title: Boundary detection stalled on serial per-paragraph LLM refinement, not a CPU quadratic
date: 2026-10-04
tags: [boundary-detection, performance, llm, async, concurrency, B7, folio-insights]
severity: high
area: pipeline/performance
symptom: "Boundary detection on a long document takes many minutes while a short slice takes seconds; it looks quadratic"
status: fixed
related: [docx-elementless-binary-reread.md]
---

# Boundary detection stalled on serial LLM refinement (B7)

_Paraphrased from the unmerged `feat/proposed-class-governance` branch and re-authored with
the code on 2026-10-04 (proposed-class governance plan, U3). Campaign measurements are left
out._

## Problem

Boundary detection on a full document ran for many minutes; a small slice of the same
document finished in seconds. The curve looked quadratic, but profiling showed almost all
the time was spent waiting on the network, not computing.

## Root cause

Every paragraph over 500 characters is "ambiguous". When the Tier-2 semantic split found no
topic shift, the paragraph fell through to Tier 3, one blocking LLM request per paragraph,
and the ambiguous paragraphs were processed one after another. A larger document meant more
long paragraphs, so more sequential round trips. (An ingestion bug that fed binary container
bytes in as giant paragraphs made it worse: `docx-elementless-binary-reread.md`.)

## Fix

- **Concurrency.** Ambiguous paragraphs are refined with `asyncio.gather` under a
  `Semaphore(boundary_tier_concurrency)` (8 by default). Output order is preserved.
- **LLM off the hot path.** `boundary_llm_refine` is off by default. A deterministic
  sentence-group split groups whole sentences up to `boundary_max_unit_chars` (600) and
  locates each group back in the parent text. No network, nothing dropped. Tier 3 stays
  available as an opt-in, still under the concurrency bound.
- **Size cap.** Any Tier-2 or Tier-3 segment still over the cap is split the same way.
  Sentence-group units are recorded with `method=sentence_group` in their lineage.

## Lesson

A quadratic wall-clock curve is not always a quadratic algorithm. When per-item work is a
blocking network call whose count grows with the input, a serial `await` in a loop produces
the same curve. Profile where the time goes (lock and poll waits mean I/O) before optimizing
computation, and keep flaky, expensive model calls off deterministic hot paths.

## Tests

`tests/test_extraction_safeguards.py`: the concurrency bound, opt-in Tier 3, and the
content-preserving split.

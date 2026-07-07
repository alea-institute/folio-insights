---
title: Boundary detection stalled >11 min on serial per-paragraph LLM refinement (not a CPU quadratic)
date: 2026-07-07
tags: [boundary-detection, performance, llm, async, concurrency, folio-insights, books-uat]
severity: high
area: pipeline/performance
symptom: "Full-chapter boundary detection runs >11 min; a 7k slice finishes in ~4.6s — looks quadratic but is serial blocking LLM I/O"
---

## Problem

`BoundaryDetectionStage` took >11 minutes on a 119k-char chapter but ~4.6s on a
7k slice — the classic quadratic signature. It is **not** a CPU quadratic.

Profiling (cProfile + manual timers on the real input) was unambiguous:
`_run_tier3` (LLM boundary refinement) consumed **145.0s of a 150s cap
(96.6%)**; cProfile tottime was `_thread.lock.acquire` 131s + `select.epoll.poll`
13.5s — pure network wait, not compute. `resolve_anchor`'s rapidfuzz call (a
genuine latent O(candidate × source)) was **never reached**. Tier-2 embeddings
were cheap (`model.encode` 66ms/call).

## Root cause

Two compounding issues:

1. **Every >500-char paragraph is "ambiguous"** and, when Tier-2 finds no
   semantic split, falls through to **Tier-3**, which fires **one blocking
   Google LLM request per paragraph** (~14.5s each with 503-retry backoff).
2. The ambiguous paragraphs were processed **serially** (`for amb in ambiguous:
   await …`). Bigger input → more ambiguous paragraphs → more serial ~14.5s
   round-trips. The "quadratic feel" was really: doc size ↑ ⇒ LLM-call count ↑,
   each blocking. (Amplified by an upstream bug that fed 13 giant *binary*
   paragraphs — see `docx-elementless-binary-reread.md`.)

## Fix (algorithmic, content-preserving — no band-aid timeout)

- **Concurrency:** refine ambiguous paragraphs with a bounded
  `asyncio.gather` + `Semaphore(boundary_tier_concurrency)` instead of serially.
- **Default the LLM off the hot path:** `boundary_llm_refine=False`. A
  **deterministic sentence-group split** (`_split_sentence_groups`) handles
  large coherent paragraphs — group whole sentences up to
  `boundary_max_unit_chars` (600), locate spans back into the parent text. No
  network, no content dropped. Tier-3 stays available (opt-in, still
  concurrency-capped) for callers who want LLM refinement.
- **Size cap:** any Tier-2/Tier-3 segment still over the cap is sentence-group
  split so no giant unit survives.

**Result:** full real chapter boundary detection **>11 min → 4.68s**, 373 units
all ≤ 599 chars, 373/373 anchor-verified, fully deterministic and independent of
Google availability.

## Lesson

A quadratic *wall-clock* signature is not always a quadratic *algorithm*. When
per-item work is a blocking network call whose count scales with input size,
serial `await` in a loop reproduces the O(n²)-looking curve. Profile tottime
(here: thread-lock/epoll = I/O wait) before optimizing CPU. And keep flaky,
expensive LLM calls off deterministic hot paths — a sentence-group split is
"good enough" for boundaries and infinitely more reliable than a 503-prone
round-trip per paragraph.

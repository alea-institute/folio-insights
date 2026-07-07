---
title: sys.path bridge to a sibling repo silently breaks when the sibling is reorganized
date: 2026-07-07
tags: [bridge, folio-enrich, imports, integration, entity_ruler, iri-mapping, folio-insights]
severity: high
area: integration/bridge
symptom: "ModuleNotFoundError: No module named 'app.services.concept.entity_ruler' (per-unit caught) → FOLIO IRI mapping silently degrades to LLM/semantic fallback → ~60% wrong-concept IRIs"
---

## Problem

folio-insights integrates folio-enrich as an **in-process `sys.path` bridge** (not a
versioned dependency): `folio_bridge.py` does `sys.path.insert(0, ../folio-enrich/backend)`
then `from app.services.concept.entity_ruler import AhoCorasickMatcher`. During the book-UAT
campaign the deterministic entity_ruler IRI path produced **zero** matches; the tagger fell
back to the LLM/semantic path, which mapped ~60% of tags to the **wrong** FOLIO concept
(6 of 18 sampled IRIs resolved to *countries* — Argentina, Germany, Russia — others to
currencies/industries). In discovery, `folio_mapping` mapped **0 candidates** → all tasks
null-IRI → empty OWL export.

## Root cause

folio-enrich was **reorganized** after the earlier de-risk run: `AhoCorasickMatcher` moved
from `app.services.concept.entity_ruler` to `app.services.matching.aho_corasick`, and its API
changed (`find_matches()` → `search()`, plus explicit `add_patterns()`/`build()` before use).
The bridge import is a bare string path with no version pin and no import-time failure surfaced
to the operator — the `ModuleNotFoundError` is caught per-unit and logged as a warning, so the
pipeline keeps running and silently emits degraded output. "245/245 IRIs resolve" stayed *true*
(the fallback still emits valid IRI strings) but hollow (wrong concepts).

## Why it's dangerous

A `sys.path` bridge couples two repos by **directory layout + internal API**, both of which the
sibling can change freely with no signal to the consumer. Combined with defensive per-item
`try/except`, a structural break degrades to *plausible-but-wrong* output instead of a loud
failure — the worst failure mode for a data pipeline.

## Fix (recommended — WS4 deterministic-IRI resolution)

1. Update the bridge to the new location/API (`app.services.matching.aho_corasick`,
   `search()`), and populate the matcher with FOLIO concept labels/aliases via
   `add_patterns()`/`build()` before searching.
2. **Fail loud at startup**: import the bridge symbols once at bridge-init and raise a clear
   error naming the expected folio-enrich path/commit if they're missing — don't let a broken
   deterministic path silently fall back.
3. Pin folio-enrich to a known-good commit/tag in the bridge config, or vendor the matcher.
4. Add a smoke test that asserts the entity_ruler path returns ≥1 match on a known concept
   string — a canary that trips the moment the sibling reorganizes.

## Lesson

Any in-process bridge to a repo you don't version-lock needs (a) a startup import canary that
fails loud, and (b) a smoke test on the happy path. Silent per-item fallback + an unpinned
sibling = wrong data that passes existence checks.

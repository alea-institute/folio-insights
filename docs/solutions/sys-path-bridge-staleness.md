---
title: A sys.path bridge to a sibling repository broke silently when the sibling was reorganized
date: 2026-10-04
tags: [bridge, folio-enrich, folio-resolve, entity-ruler, iri-mapping, B5, folio-insights]
severity: high
area: integration/bridge
symptom: "ModuleNotFoundError for the old matcher module, caught per unit; tagging silently fell back to LLM/semantic IRIs"
status: fixed
related: [llm-path-unverified-iris.md]
---

# A sys.path bridge broke silently when the sibling repository moved a module (B5)

_Paraphrased learning from the unmerged `feat/proposed-class-governance` branch, re-authored
on 2026-10-04 (proposed-class governance plan, U3). Campaign figures are left out._

## Problem

folio-insights imported folio-enrich's Aho-Corasick matcher through a `sys.path` bridge.
folio-enrich later moved that module and changed its API. The import error was caught per
unit and logged as a warning, so the deterministic entity-ruler path produced nothing and
every IRI came from the LLM and semantic paths. Output still looked valid: the IRIs existed,
they were just often the wrong concepts.

## Why it is dangerous

A `sys.path` bridge couples two repositories by directory layout and internal API, with no
version pin. Combined with defensive per-item `try/except`, a structural break degrades into
plausible but wrong output instead of a loud failure.

## Fix

- **Pinned matcher.** The ruler is now the pinned `folio_resolve.FOLIOEntityRuler`, a
  dependency-free port with the same `load_patterns` / `find_matches` interface. No sibling
  import and no spaCy are involved. (The historical branch fixed the import path and added
  spaCy instead; that route is superseded and spaCy is not a dependency.)
- **Loud by default.** `FolioTaggerStage._get_entity_ruler` raises when the ruler or its FOLIO
  labels are unavailable, unless `require_deterministic_iri` is turned off
  (`FOLIO_INSIGHTS_REQUIRE_DETERMINISTIC_IRI=false`). Either way the state is recorded in
  `metadata.folio_tagger` (`deterministic_iri_path: active | degraded`, plus a reason) and
  carried into the output summary.
- **Canary.** `folio_bridge.verify_deterministic_bridge()` imports and instantiates the
  ruler and raises `BridgeIntegrityError` on failure. `tests/test_bridge.py` loads the live
  FOLIO labels and asserts a plain legal term yields a real FOLIO IRI.

## Lesson

Any in-process bridge to an unpinned repository needs a startup canary that fails loud and a
happy-path smoke test. Silent per-item fallback plus an unpinned sibling produces wrong data
that passes existence checks.

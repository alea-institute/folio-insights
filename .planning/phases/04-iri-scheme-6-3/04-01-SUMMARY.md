---
phase: 04-iri-scheme-6-3
plan: 01
subsystem: testing
tags: [shards, iri, provenance-hash, sha256, hypothesis, canonicalization, pydantic]

# Dependency graph
requires:
  - phase: 02-shard-envelope
    provides: mint_shard_iri() pure-stdlib minting function + _IRI_HEX_LEN constant
  - phase: 03-shard-subtypes
    provides: GlossShard with _GLOSS_URN_RE IRI format validator
provides:
  - hex32 (128-bit) shard IRI body — collision-resistant minting (D-01)
  - internal CR/CRLF -> LF canonicalization in _normalize_span (D-08, SHARD-07)
  - 1000-run determinism property test at hex32 + internal-CRLF directed vector (D-09)
  - GlossShard IRI format validation widened to <32-hex>; old <16-hex> form rejected (D-05/D-01)
affects: [05-content-versioning, 13-triplestore-storage, iri-collision-registry]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Line-ending fold (CRLF/CR -> LF) precedes NFC in _normalize_span so combining-char sequences spanning a fold normalize consistently"
    - "Full 64-hex hash returned alongside hex32 IRI body — registry compares full hashes for collisions (D-02)"

key-files:
  created: []
  modified:
    - src/folio_insights/shards/minting.py
    - src/folio_insights/shards/subtypes.py
    - tests/shards/test_minting_determinism.py
    - tests/shards/test_subtype_gloss.py
    - tests/shards/conftest.py
    - tests/shards/test_subtype_properties.py

key-decisions:
  - "hex16 -> hex32 IRI body: 128-bit makes birthday collisions ~1e-29 at 1B shards; full 64-hex hash still returned (D-01/D-02)"
  - "Internal CRLF/CR -> LF folds BEFORE NFC + strip in _normalize_span (order load-bearing per SHARD-07)"
  - "1000-example hypothesis budget preserved unchanged — it IS the SHARD-07 exit-criterion-1 gate (D-09)"

patterns-established:
  - "Line-ending canonicalization: span.replace('\\r\\n','\\n').replace('\\r','\\n') before unicodedata.normalize('NFC', ...).strip()"

requirements-completed: [SHARD-07]

# Metrics
duration: 12min
completed: 2026-05-27
---

# Phase 04 Plan 01: hex32 IRI Width + CRLF Canonicalization Summary

**Widened the shard IRI body from hex16 to hex32 (128-bit, collision-resistant) and closed the SHARD-07 canonicalization gap by folding internal CR/CRLF to LF before NFC, proven deterministic across 1000 random runs.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-27T02:06Z (approx)
- **Completed:** 2026-05-27T02:18Z
- **Tasks:** 2 completed
- **Files modified:** 6

## Accomplishments

- hex32 minting: `_IRI_HEX_LEN = 16 -> 32` in `minting.py`; IRI body is now 32 hex chars while `mint_shard_iri` still returns the full 64-hex SHA-256 for downstream collision comparison (D-01/D-02).
- Internal line-ending canonicalization: `_normalize_span` folds `\r\n` and lone `\r` to `\n` BEFORE NFC + trim, so the same text with CRLF/CR/LF line endings hashes identically (D-08 — the last SHARD-07 gap).
- 1000-run determinism gate preserved at hex32; new directed vector `test_internal_crlf_normalized_to_lf` locks CRLF == CR == LF equivalence (D-09).
- GlossShard IRI format validation widened to `<32-hex>` and the old `<16-hex>` form is now explicitly rejected (D-05/D-01).

## Task Commits

Each task was committed atomically (TDD RED/GREEN gates for Task 1):

1. **Task 1 (RED): failing internal-CRLF determinism vector** - `fccc9a5` (test)
2. **Task 1 (GREEN): hex32 width + internal CR/CRLF -> LF fold** - `a084641` (feat)
3. **Task 2: GlossShard regex {32} + determinism/fixture suite migration** - `17fcbf7` (feat)

_TDD task 1 produced test -> feat commits; no refactor needed (implementation was minimal and clean)._

## Files Created/Modified

- `src/folio_insights/shards/minting.py` - `_IRI_HEX_LEN` 16->32; `_normalize_span` folds internal CR/CRLF to LF before NFC; docstrings synced to hex32.
- `src/folio_insights/shards/subtypes.py` - `_GLOSS_URN_RE` `[a-f0-9]{16}` -> `{32}`; comment block + validator `ValueError` message `<16-hex>` -> `<32-hex>`.
- `tests/shards/test_minting_determinism.py` - hex16 length assertions -> hex32; new `test_internal_crlf_normalized_to_lf` directed vector; module docstring updated.
- `tests/shards/test_subtype_gloss.py` - valid/invalid IRI parametrize tables migrated to hex32; added rejection case for the old 16-hex form (locks the must-have truth).
- `tests/shards/conftest.py` - `_SUBTYPE_DEFAULTS[GlossShard]["glosses"]` migrated to a hex32 IRI.
- `tests/shards/test_subtype_properties.py` - `hex_body` hypothesis strategy `min_size/max_size` 16 -> 32.

## Decisions Made

None beyond the plan — followed D-01/D-02/D-05/D-08/D-09 as specified.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated hex16 test fixtures to hex32 across the broader shards suite**
- **Found during:** Task 2 (after widening `_GLOSS_URN_RE` to `{32}`)
- **Issue:** The plan's task body named only `test_minting_determinism.py` edits, but widening the GlossShard regex invalidated hex16 IRI fixtures elsewhere in the shards suite — `test_subtype_gloss.py` valid/invalid tables, `conftest.py` default `glosses`, and the `test_subtype_properties.py` `hex_body` strategy all minted/asserted 16-hex bodies and began failing collection-time validation. The plan's own acceptance criterion ("`pytest -m shards -q` exits 0 — no regression in the broader shards suite from the hex32 re-mint") and PATTERNS.md ("hex16->hex32 fixture re-mint, migration consequence") anticipated this.
- **Fix:** Migrated each hex16 IRI literal/strategy to hex32. Added an explicit rejection case for the old 16-hex form in `test_subtype_gloss.py` to lock the must-have truth "GlossShard.glosses ... rejects the old <16-hex> form [D-01]".
- **Files modified:** `tests/shards/test_subtype_gloss.py`, `tests/shards/conftest.py`, `tests/shards/test_subtype_properties.py`
- **Verification:** `pytest tests/shards/ -m shards -q` — 132 passed.
- **Committed in:** `17fcbf7` (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1x Rule 3 — blocking migration consequence anticipated by the plan).
**Impact on plan:** Necessary to satisfy the plan's own `pytest -m shards -q` exit-0 acceptance criterion. No scope creep — all edits are mechanical hex16->hex32 fixture migrations forced by the regex widen.

## Issues Encountered

- **No venv / package import in worktree:** the worktree has no `.venv` and the editable install in the main repo resolves to the main-repo source. Ran tests with the main repo's `.venv/bin/python` and `PYTHONPATH=<worktree>/src` prepended so the worktree's source took precedence (verified `folio_insights.__file__` resolved to the worktree). No source changes required.
- **Out-of-scope collection errors:** `pytest -m shards` across the whole `tests/` tree hit `ModuleNotFoundError: No module named 'fastapi'` collection errors in unrelated API test modules (`test_*_api.py`). These are a pre-existing environment gap (fastapi not installed in this venv), NOT caused by this plan's changes. Scoped the marker run to `tests/shards/` (the actual acceptance target) — all 132 shards tests pass. Logged here rather than fixed (SCOPE BOUNDARY: unrelated pre-existing failures).

## TDD Gate Compliance

Plan task 1 was `tdd="true"`. Gate sequence verified in git log:
1. RED — `fccc9a5` `test(04-01): add failing internal-CRLF determinism vector` (confirmed failing before implementation).
2. GREEN — `a084641` `feat(04-01): widen shard IRI body to hex32 + fold internal CR/CRLF to LF` (test then passed).
3. REFACTOR — none needed (minimal implementation).

## Known Stubs

None — no placeholder values, mock data, or unwired data sources introduced.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- hex32 width and full canonicalization (NFC + LF + trim + RFC 3986) are landed and deterministic — the IRI collision registry (`shards/iri_registry.py`) and `verify-iris` CLI planned for the next plan in this phase can rely on a stable 32-hex body + full 64-hex hash contract.
- `mint_shard_iri` remains pure stdlib (no storage deps), so the registry can import it cleanly without leaking I/O into the determinism property test.
- No blockers.

---
*Phase: 04-iri-scheme-6-3*
*Completed: 2026-05-27*

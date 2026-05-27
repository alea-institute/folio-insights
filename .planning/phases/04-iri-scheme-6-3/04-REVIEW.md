---
phase: 04-iri-scheme-6-3
reviewed: 2026-05-26T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - src/folio_insights/cli.py
  - src/folio_insights/shards/__init__.py
  - src/folio_insights/shards/iri_registry.py
  - src/folio_insights/shards/minting.py
  - src/folio_insights/shards/subtypes.py
  - tests/shards/conftest.py
  - tests/shards/test_iri_collision.py
  - tests/shards/test_minting_determinism.py
  - tests/shards/test_subtype_gloss.py
  - tests/shards/test_subtype_properties.py
  - tests/shards/test_verify_iris_cli.py
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: resolved
resolved: 2026-05-26T00:00:00Z
resolution_note: >
  CR-01 (blocker), WR-01, and WR-02 fixed in commits following the review, each
  with a directed regression test (NFC/NFD URI vector, lost-race idempotency,
  empty-registry guard). Shards suite green at 142 + 1 slow. WR-03 (dead-code
  stderr ternary) and the 3 Info findings left as-is (cosmetic/test-only).
---

# Phase 04: Code Review Report

**Reviewed:** 2026-05-26
**Depth:** standard
**Files Reviewed:** 11
**Status:** resolved (CR-01, WR-01, WR-02 fixed with regression tests)

## Summary

Reviewed the Phase 04 IRI scheme implementation: hex16→hex32 body widening, internal CRLF/CR→LF span canonicalization, the global content-addressed SQLite collision registry (`iri_registry.py`), the fail-closed `ShardIRICollision` halt, and the write-free `verify-iris` CLI.

The fail-closed collision design is sound where it matters most: `register()` does SELECT-then-conditional-INSERT, never UPDATE/REPLACE, and the collision branch logs both hashes then raises without touching the existing row — verified at runtime that the seeded provenance row is preserved. All SQL is `?`-parametrized; no injection vectors. The `verify-iris` command is correctly read-only and exits non-zero on any mismatch.

However, there is one **BLOCKER**: a hash-determinism bug in `_normalize_uri`. The function percent-encodes the URI path **before** NFC normalization is applied (NFC runs only later in `mint_shard_iri`, by which point the path is already ASCII percent-encoding and NFC is a no-op). As a result, two `source_uri` values whose path differs only by Unicode normalization form (NFC vs NFD) mint **different** IRIs and store as **different** registry rows — directly violating the D-02 determinism guarantee and the registry's content-addressing contract. The 1000-example property test does not catch this because it uses an ASCII-only host alphabet and only asserts self-consistency (mint twice equals itself), never NFC/NFD equivalence for URIs.

Secondary findings concern a documented-but-unimplemented concurrency contract (`register()` does not catch the `IntegrityError` its own docstring relies on), and a dead/misleading stderr guard in the CLI test.

## Critical Issues

### CR-01: URI path NFC normalization happens after percent-encoding — breaks IRI determinism for non-ASCII paths

**File:** `src/folio_insights/shards/minting.py:31-40, 69`
**Issue:**
`_normalize_uri` calls `quote(parts.path, safe="/%:@")` on the raw path **before** any Unicode normalization. NFC is only applied afterward in `mint_shard_iri` (line 69, `unicodedata.normalize("NFC", _normalize_uri(source_uri))`), but by then the path component is already pure-ASCII percent-encoding, so the NFC pass is a no-op for it.

Consequence: a `source_uri` whose path contains the same characters in different Unicode normalization forms mints **different** IRIs. Verified at runtime:

```
mint_shard_iri("https://x.com/" + NFC("café"), "s")  -> urn:folio:shard/<A>
mint_shard_iri("https://x.com/" + NFD("café"), "s")  -> urn:folio:shard/<B>   # A != B
# _normalize_uri yields  https://x.com/caf%C3%A9  vs  https://x.com/cafe%CC%81
```

This contradicts the module's own stated recipe (`input = NFC(rfc3986_normalize(source_uri)) + ...`) and the D-02 determinism property ("same (uri, span) → same (iri, hash) across runs, platforms, and line-ending styles"). For the registry this is worse than a hash quirk: the same logical source resource stored twice under two normalization forms produces two distinct content-addressed rows, defeating idempotent re-mint and content-addressing (D-04). Note the span component is handled correctly (NFC precedes any encoding), and the query/fragment happen to be safe because `urlunsplit` leaves them un-quoted so the later NFC catches them — only the **path** is affected.

**Fix:** NFC-normalize each URI component *before* percent-encoding, inside `_normalize_uri`, and stop relying on the outer NFC in `mint_shard_iri` to cover the URI:

```python
def _normalize_uri(uri: str) -> str:
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    netloc = unicodedata.normalize("NFC", parts.netloc).lower()
    path = quote(unicodedata.normalize("NFC", parts.path), safe="/%:@")
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    query = unicodedata.normalize("NFC", parts.query)
    fragment = unicodedata.normalize("NFC", parts.fragment)
    return urlunsplit((scheme, netloc, path, query, fragment))
```

Then in `mint_shard_iri`, drop the redundant outer NFC on the URI (it is now handled per-component) or keep it as defense-in-depth (harmless once components are pre-normalized). Add a directed test asserting `mint_shard_iri(uri_with_NFC_path, span) == mint_shard_iri(uri_with_NFD_path, span)`, and widen the property test's `host`/`path` strategies to include non-ASCII + mixed normalization forms so this class of bug is caught generatively.

## Warnings

### WR-01: `register()` does not catch the IntegrityError its docstring relies on for concurrency safety

**File:** `src/folio_insights/shards/iri_registry.py:21-23 (docstring), 124-139`
**Issue:**
The module docstring states: "`iri_body TEXT NOT NULL UNIQUE` makes the insert atomic at the DB layer (T-04-06) — a racing duplicate-body insert fails the UNIQUE constraint rather than producing two rows." But `register()` performs SELECT-then-INSERT as two separate statements with no `try/except`. Two concurrent registrations of the same `(source_uri, source_span)` both observe `row is None`, both attempt the INSERT; the second raises an unhandled `sqlite3.IntegrityError` (UNIQUE violation) that propagates out as a crash rather than the documented idempotent return. The UNIQUE constraint does prevent the duplicate *row*, but the code does not translate the constraint failure into the contracted idempotent behavior — so the "atomic" claim is only half-true. Current single-connection `asyncio.run` usage makes the race unlikely today, but the docstring advertises concurrency safety the code does not deliver.

**Fix:** Either (a) wrap the INSERT and on `aiosqlite.IntegrityError` re-SELECT and apply the same idempotent-vs-collision branching, or (b) restructure as an upsert-guard: attempt the INSERT first, and on UNIQUE violation fall through to the existing-row comparison logic. Minimal version:

```python
if row is None:
    try:
        await db.execute(
            "INSERT INTO shard_iri_registry "
            "(iri_body, full_hash, source_uri, source_span) VALUES (?, ?, ?, ?)",
            (iri_body, full_hash, source_uri, source_span),
        )
        await db.commit()
        return iri
    except aiosqlite.IntegrityError:
        # Racing insert won; re-read and fall through to the comparison branch.
        cursor = await db.execute(
            "SELECT full_hash FROM shard_iri_registry WHERE iri_body = ?",
            (iri_body,),
        )
        row = await cursor.fetchone()
# ... then the existing same-hash / different-hash branching on `row`
```

Alternatively, downgrade the docstring claim to match reality if true concurrency is out of scope for this phase.

### WR-02: `verify-iris` treats an empty registry as a successful "all verified" pass

**File:** `src/folio_insights/cli.py:541-579`
**Issue:**
When the registry DB exists but contains zero rows, `records` is empty, the mismatch loop never runs, and the command prints `verify-iris: all 0 stored shard IRIs re-mint identically.` and exits 0. For a "standing nightly guard against source drift," reporting success on an empty/uninitialized registry can mask a real operational failure (e.g., the nightly job pointed at a freshly-created or truncated DB, or a wrong `--db` path that happens to resolve to a self-bootstrapped empty file — note `all_records()` calls `_bootstrap` which `CREATE TABLE IF NOT EXISTS`, so even a bogus path silently becomes a valid empty registry). The "no rows" case should be visibly distinguished from "rows verified."

**Fix:** Special-case the empty result with a distinct message and consider a distinct exit signal for nightly monitoring:

```python
if not records:
    click.echo("verify-iris: registry is empty — nothing to verify.", err=True)
    sys.exit(0)  # or a sentinel non-zero if "empty == suspicious" for the nightly job
```

At minimum, log the registry path that was opened so a misdirected `--db` is diagnosable.

### WR-03: CLI test's stderr guard is dead code — `result.stderr_bytes` is always None under default CliRunner

**File:** `tests/shards/test_verify_iris_cli.py:24-26, 47`
**Issue:**
The runner fixture uses `CliRunner()` with no arguments. In the installed Click 8.1.8, `CliRunner.__init__` defaults `mix_stderr=True`, which merges stderr into stdout. Verified at runtime: under `mix_stderr=True`, `result.stderr_bytes` is always `None` and accessing `result.stderr` raises `ValueError: stderr not separately captured`. Therefore the ternary on line 47:

```python
combined = result.output + (result.stderr if result.stderr_bytes else "")
```

always evaluates the `else ""` branch — the `result.stderr` access is unreachable. The assertion `assert wrong_body in combined` still passes only because the mismatch text was written to stderr and then folded into `result.output` by the mixed runner. The test passes for an incidental reason; the guard gives a false impression of validating separated stderr. A future maintainer setting `mix_stderr=False` to actually test stderr separation would find this branch silently mis-wired.

**Fix:** Make the intent explicit. Either assert against `result.output` directly (since stderr is mixed in):

```python
assert wrong_body in result.output  # mismatch IRI is surfaced
```

or construct the runner with `CliRunner(mix_stderr=False)` and assert against `result.stderr` deliberately, dropping the dead ternary.

## Info

### IN-01: `__all__` ordering differs between modules (cosmetic, not enforced)

**File:** `src/folio_insights/shards/iri_registry.py:206`
**Issue:** `__all__ = ["ShardIRICollision", "ShardIRIRegistry", "DEFAULT_REGISTRY_PATH"]` is unsorted while sibling modules (`subtypes.py:290`, `__init__.py:30`) keep `__all__` alphabetized. Minor consistency nit; no functional impact.
**Fix:** Sort for consistency: `["DEFAULT_REGISTRY_PATH", "ShardIRICollision", "ShardIRIRegistry"]`.

### IN-02: Docstring references stale hex16 width in test module header

**File:** `tests/shards/test_subtype_gloss.py:3-5`
**Issue:** The module docstring still says "glosses IRI format validation (urn:folio:shard/<16-hex> OR http(s)://...)". Phase 04 widened the body to hex32 and the actual regex (`subtypes.py:215`) and the test vectors (lines 39, 53-58) all use 32-hex. The 16-hex reference is stale and could mislead.
**Fix:** Update the docstring to `<32-hex>` to match the implemented width.

### IN-03: `_seed_row` is a test-only helper living in production module surface

**File:** `src/folio_insights/shards/iri_registry.py:180-203`
**Issue:** `_seed_row` exists solely "to construct collision scenarios deterministically" (per its docstring) and is exercised only by tests (`test_iri_collision.py:54`, `test_verify_iris_cli.py:41`). It bypasses minting and writes arbitrary `(iri_body, full_hash)` rows. The leading underscore signals private intent, but shipping a write-bypass on the production registry class is a mild footgun — a caller could seed a forged body/hash pair that later trips the collision halt or pollutes `verify-iris`. Acceptable for now given the underscore convention and the in-tree test scope, but worth a comment guarding against production use or relocating to a test fixture.
**Fix:** Either add an explicit `# pragma: test-only` / runtime guard, or move the seeding logic into the test layer (e.g., a conftest helper that opens the DB directly) so the production class exposes no write-bypass.

---

_Reviewed: 2026-05-26_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

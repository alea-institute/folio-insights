# JCS Golden Fixtures (RFC 8785 cross-implementation lock)

**Phase:** 6 (DID Substrate §6.5)
**Plan:** 06-01 Task 4 — F4 BLOCKING pitfall closure
**Vendored:** 2026-05-28

## Purpose

Cross-implementation golden test for our `_jcs_canonical_bytes` helper
(`src/folio_insights/revision/content_edit.py`). The test (`../../test_jcs_golden.py`)
asserts that our output equals the **RFC-8785 reference** canonical form on
a representative input set.

Pitfall F4 (06-RESEARCH §11 + research/PITFALLS.md) is BLOCKING: a drifting
canonical hash silently breaks every DID signature. The in-phase property
test (`test_canonical_jcs_properties.py`) proves INTERNAL consistency
(order-independence over 1000 random shards); this golden test proves
EXTERNAL correctness against the reference. Both gates are required.

## Provenance

Reference implementation:
- **cyberphone/json-canonicalization** — https://github.com/cyberphone/json-canonicalization
  - Anders Rundgren's RFC 8785 reference (Java, JavaScript, Python). The
    Python port is the `jcs` package on PyPI (`jcs==0.2.1` per
    `pyproject.toml`) — we pin to it and treat its output as canonical.

Input categories sampled (the F4 surface 06-RESEARCH §2 calls out):
1. **Unicode** — NBSP (U+00A0), em-dash (U+2014), combining accents (NFD vs
   NFC), emoji (multi-byte code points), curly quotes, surrogate-range escapes.
2. **Numbers** — `0`, `1`, `-0`, `1.0`, `1e-7`, `1e21`, large positive/negative
   integers, denormals, fractional precision boundaries.
3. **Structure** — nested objects, arrays of objects, empty containers,
   single-key objects.
4. **Null / boolean** — explicit `null` (KEEP policy locked at 06-RESEARCH §2
   OQ3), `true`, `false`, and arrays containing them.
5. **Key ordering** — multi-key objects where the input order differs from
   RFC-8785 sorted order.

## Fixture Layout

Each fixture is a single JSON file under this directory whose top-level
schema is:

```json
{
  "id": "<short-slug>",
  "description": "<what F4 surface this case exercises>",
  "category": "unicode | numbers | structure | nulls | key_ordering",
  "input": <arbitrary JSON value>
}
```

The expected canonical bytes are computed at test-load time by calling the
RFC-8785 reference (`jcs.canonicalize`) on `input`. The test then asserts
our `_jcs_canonical_bytes(_normalize_for_jcs_passthrough(input))` equals
that reference output for the cases where our pre-normalization is a
no-op (no NFD inputs, datetimes already-canonical), AND that NFD/NFC pairs
produce identical bytes after our pre-normalization (the F4 closure that
jcs alone does NOT do).

## Why we don't vendor literal expected-output files

Pinning expected-canonical-bytes files would require the cyberphone test
data with its own SHA-256 hash and update lock — a 6-month maintenance
burden for the same correctness signal. Instead we pin the reference
**library** (`jcs==0.2.1`) and let it produce the expected bytes from the
input at test time. If the reference library shifts, the pin breaks (and
the test will surface it). The pin is the integrity anchor.

If a future operator wants the literal-bytes form for an air-gapped CI,
generate them with:

```python
import json, pathlib, jcs
for f in pathlib.Path("tests/identity/fixtures/jcs_golden").glob("*.json"):
    if f.name == "README.md": continue
    payload = json.loads(f.read_text())
    expected = jcs.canonicalize(payload["input"])
    (f.with_suffix(".expected")).write_bytes(expected)
```

…and add an equality check against the `.expected` file in the test.

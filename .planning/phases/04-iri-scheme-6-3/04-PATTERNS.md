# Phase 4: IRI Scheme (§6.3) - Pattern Map

**Mapped:** 2026-05-24
**Files analyzed:** 6 (3 modify + 3 create)
**Analogs found:** 6 / 6

> No RESEARCH.md for this phase (research flag = no). File list extracted from
> `04-CONTEXT.md` `<domain>`, `<decisions>`, `<canonical_refs>`, `<code_context>`.
>
> **Correction vs. CONTEXT blast-radius note:** CONTEXT lists `envelope.py` as
> holding an `[a-f0-9]{16}` IRI regex. It does **not** — `envelope.py` has no IRI
> regex and no `_IRI_PREFIX`; `shard_iri` is a plain `str = Field(frozen=True)`
> (envelope.py:101). The only `{16}` IRI regex in `shards/` lives in
> `subtypes.py:215`. The minting constant `_IRI_HEX_LEN = 16` lives in
> `minting.py:25`. The `api/db/` path referenced in CONTEXT does not exist; the
> `iri_registry` schema lives inline in `tests/test_owl_export.py:112-128` and the
> async access layer in `services/iri_manager.py`. Planner should treat
> `envelope.py` as **no-change** unless a new hard-coded hex16 string surfaces.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/folio_insights/shards/minting.py` (MODIFY) | utility | transform | self (extend in place) | exact (self) |
| `src/folio_insights/shards/subtypes.py` (MODIFY) | model | transform | self (regex `{16}`→`{32}`) | exact (self) |
| `src/folio_insights/shards/envelope.py` (VERIFY only) | model | transform | self | n/a — no IRI regex present |
| `src/folio_insights/shards/iri_registry.py` (CREATE) | service | CRUD | `services/iri_manager.py` `IRIManager` | role-match (aiosqlite direct-SQL) |
| `verify-iris` Click command (CREATE — in `cli.py` or `shards/cli.py`) | route/cli | request-response | `cli.py` `export`/`discover`; `bench/cli.py` subgroup | exact (Click + lazy import) |
| `tests/shards/test_iri_collision.py` + determinism extension (CREATE) | test | batch | `tests/shards/test_minting_determinism.py`; `tests/test_cli.py` | exact (Hypothesis + CliRunner) |

## Pattern Assignments

### `src/folio_insights/shards/minting.py` (utility, transform) — MODIFY

**Analog:** self. Extend in place; do not rewrite. The full file is 68 lines.

**Width change (D-01/D-02)** — line 25:
```python
_IRI_HEX_LEN = 16  # first 16 of sha256's 64 hex chars (D-02)
```
Change to `32` (D-01). The construction at line 64 already reads the constant, so
no other minting.py edit is needed for the width:
```python
iri = f"{_IRI_PREFIX}{hash_hex[:_IRI_HEX_LEN]}"   # line 64 — unchanged
```
`mint_shard_iri()` already returns `(iri, hash_hex)` where `hash_hex` is the full
64-hex (line 65) — that full hash is exactly what the registry stores for
collision comparison (D-02). Signature unchanged:
```python
def mint_shard_iri(source_uri: str, source_span: str) -> tuple[str, str]:
```

**CRLF→LF canonicalization (D-08)** — `_normalize_span`, lines 40-46 (current):
```python
def _normalize_span(span: str) -> str:
    """NFC normalize + strip trailing whitespace (incl. CRLF)."""
    return unicodedata.normalize("NFC", span).strip()
```
Add **internal** CRLF→LF (and lone CR→LF) normalization *before* NFC + strip.
Order matters — match SHARD-07 "NFC + LF + trim + RFC 3986". Recommended:
```python
def _normalize_span(span: str) -> str:
    # D-08: internal CRLF/CR -> LF so line-ending variants hash identically.
    lf = span.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", lf).strip()
```
The existing `test_crlf_trimmed_from_span` (test_minting_determinism.py:63) only
covers *trailing* CRLF (caught by `.strip()`). D-08 adds the *internal* case —
needs a new directed vector (see test section).

**Docstring sync:** lines 4-6 and 55 hard-code `hash[:16]` / `<32-hex>` examples;
update the module docstring + `mint_shard_iri` docstring to hex32 to avoid drift.

---

### `src/folio_insights/shards/subtypes.py` (model, transform) — MODIFY

**Analog:** self. Single mechanical regex widen + message text.

**IRI regex (D-05 width amendment)** — line 215:
```python
_GLOSS_URN_RE = re.compile(r"^urn:folio:shard/[a-f0-9]{16}$")
```
Change `{16}` → `{32}`. The sibling `_GLOSS_HTTP_RE` (line 216, legacy
`^https?://[^\s]+$`) is **unaffected** (CONTEXT note). Update the comment block
at lines 202, 209-210 and the validator error message at lines 232-233:
```python
                f"GlossShard.glosses must match urn:folio:shard/<16-hex> "   # -> <32-hex>
```
Validator structure (lines 227-244) is unchanged — `@model_validator(mode="after")`
raising `ValueError`. Pattern to preserve:
```python
    @model_validator(mode="after")
    def _gloss_format(self) -> "GlossShard":
        if not (_GLOSS_URN_RE.match(self.glosses) or _GLOSS_HTTP_RE.match(self.glosses)):
            raise ValueError(...)
```

---

### `src/folio_insights/shards/envelope.py` (model, transform) — VERIFY ONLY

**No IRI regex or `_IRI_PREFIX` exists in this file.** `shard_iri` is declared as
`shard_iri: str = Field(frozen=True)` (line 101). No `{16}` literal present.
Planner action: confirm no hard-coded hex16 IRI string exists; otherwise no edit.
(The CONTEXT blast-radius entry for envelope.py is a false positive — flag it but
do not invent a regex.)

---

### `src/folio_insights/shards/iri_registry.py` (service, CRUD) — CREATE

**Analog:** `src/folio_insights/services/iri_manager.py` (`IRIManager`).
This is the **aiosqlite direct-SQL, no-ORM** pattern (CONTEXT "Established
Patterns"). The new store is for **shard** IRIs and is **global / corpus-independent**
(D-04) — copy the *access pattern*, NOT the FOLIO-entity schema/semantics.

**Imports + module constants** (iri_manager.py:8-18):
```python
from __future__ import annotations

import aiosqlite
# (the new shard registry needs hashlib only via mint_shard_iri import; no uuid/base64)
```

**Class + connection pattern** (iri_manager.py:52-72) — copy the
`__init__(self, db_path: Path)` + per-method `async with aiosqlite.connect(...)`
+ `db.row_factory = aiosqlite.Row`:
```python
class IRIManager:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def get_or_create_iri(self, entity_id, entity_type, corpus_name) -> str:
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT iri FROM iri_registry WHERE entity_id = ? AND deprecated_at IS NULL",
                (entity_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                return row["iri"]
            ...
            await db.execute(
                "INSERT INTO iri_registry (entity_id, entity_type, iri, corpus_name) VALUES (?, ?, ?, ?)",
                (entity_id, entity_type, iri, corpus_name),
            )
            await db.commit()
            return iri
```

**Idempotent-vs-collision logic (D-04) — adapt `get_or_create` to a `register`
method.** The shard registry keys on the **hex32 IRI body** and stores the
**full 64-hex hash** for comparison:
- lookup hex32 body → no row: insert `(iri_body, full_hash, source_uri, source_span)`, return minted IRI.
- row exists, `full_hash` matches: **idempotent**, return existing IRI.
- row exists, `full_hash` differs: **collision** → halt+flag (D-03): log the
  `(source_uri, source_span)` pair + both full hashes, refuse to mint (raise a
  dedicated error, e.g. `ShardIRICollision`).

**Schema to define** — the closest concrete schema analog is the inline
`CREATE TABLE` in `tests/test_owl_export.py:112-128` (this is where the
`iri_registry` DDL actually lives, since iri_manager.py assumes the table exists):
```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS iri_registry (
        entity_id TEXT NOT NULL UNIQUE,
        entity_type TEXT NOT NULL,
        iri TEXT NOT NULL UNIQUE,
        corpus_name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        deprecated_at TEXT,
        superseded_by TEXT
    )
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_iri_iri ON iri_registry(iri)")
```
**Adapt for shards** (D-04 global, content-addressed): drop `corpus_name`/
`deprecated_at`/`superseded_by` (FOLIO-entity-specific); add `full_hash`,
`source_uri`, `source_span`. Suggested `shard_iri_registry`:
```sql
CREATE TABLE IF NOT EXISTS shard_iri_registry (
    iri_body    TEXT NOT NULL UNIQUE,   -- the 32-hex body
    full_hash   TEXT NOT NULL,          -- 64-hex SHA-256 for collision compare
    source_uri  TEXT NOT NULL,
    source_span TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_shard_iri_body ON shard_iri_registry(iri_body);
```
**Discretion (D-04 / Claude's Discretion):** schema + storage location is the
planner's call ("global, not per-corpus" — a dedicated global SQLite file, NOT
the per-corpus `review.db`). The DDL above is a starting point. A `verify-iris`
re-hash (D-06) reads `source_uri` + `source_span` back out, so those columns are
required.

**Note on schema bootstrapping:** unlike `iri_manager.py` (which relies on an
externally-created table), the shard registry should create its own table
idempotently (`CREATE TABLE IF NOT EXISTS`) on first connect, since it owns a
dedicated global DB file.

---

### `verify-iris` Click command (route/cli, request-response) — CREATE

**Analogs:** `src/folio_insights/cli.py` (`export`/`discover` commands) for the
command body + sqlite read + exit-code pattern; `src/folio_insights/bench/cli.py`
for the **lazy-import subgroup registration** pattern.

**Lazy heavy-import discipline (CONTEXT "keep heavy deps off `--help`")** —
cli.py:118, 128, 528-536. Imports live *inside* the command body or at module
bottom, never at top:
```python
def extract(...):
    from folio_insights.config import Settings              # cli.py:118 — lazy
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator  # cli.py:128
```
Subgroup registration at module bottom (cli.py:525-536):
```python
# Import at module-bottom is intentional: avoids pulling <heavy dep> at
# `folio-insights --help` time for commands that don't need it.
from folio_insights.bench.cli import bench as _bench_group
cli.add_command(_bench_group)
```
For `verify-iris`: import the registry + `mint_shard_iri` *inside* the command
function, not at module top.

**Command decorator + options + exit-code pattern** — cli.py:280-341 (`export`):
```python
@cli.command("export")
@click.argument("corpus_name")
@click.option("--output", "-o", default="./output", show_default=True,
              type=click.Path(resolve_path=True), help="...")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable verbose (DEBUG) logging.")
def export(corpus_name: str, output: str, ..., verbose: bool) -> None:
    _setup_logging(verbose)
    ...
    if not db_path.exists():
        click.echo(f"Error: No review database found at {db_path}. ...", err=True)
        sys.exit(1)
```
For `verify-iris` (D-06/D-07): re-mint each stored shard IRI from its stored
`source_uri` + `source_span`, compare to stored IRI; **on any mismatch →
`sys.exit(<non-zero>)` + log/alert report** (D-07: do NOT auto-quarantine). Use
`click.echo(..., err=True)` for the report, mirroring export's error path. The
`_setup_logging(verbose)` helper (cli.py:22-29) and `--verbose` flag pattern apply.

**Sync sqlite read for a CLI command** — cli.py:343-347 (`export` uses sync
`sqlite3`, not aiosqlite, inside a CLI body). For `verify-iris` the registry is
aiosqlite; either reuse the async registry via `asyncio.run(...)` (cli.py:138,
256, 444 pattern) or open a sync read — planner's call. Existing async-in-CLI:
```python
job = asyncio.run(orchestrator.run(source_path, corpus_name=corpus, resume=resume))  # cli.py:138
```

**Registration placement:** either add `@cli.command("verify-iris")` directly in
`cli.py` (like `export`/`serve`) OR create a `shards/cli.py` subgroup and
`cli.add_command(...)` at cli.py bottom (like bench/polysemy, cli.py:528-536).
Since `verify-iris` is a single command, inlining in `cli.py` matches `export`.

---

### `tests/shards/test_iri_collision.py` + determinism extension (test, batch) — CREATE

**Analogs:** `tests/shards/test_minting_determinism.py` (Hypothesis property +
directed vectors); `tests/test_cli.py` (`CliRunner`); `tests/bench/conftest.py`
+ `tests/bench/test_generator_determinism.py` (large-N / subprocess CLI patterns).

**Hypothesis 1000-run property (D-09 — SHARD-07 exit criterion 1)** —
test_minting_determinism.py:20-47. The 1000-example settings + marker are the
exact pattern to copy:
```python
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from folio_insights.shards import mint_shard_iri

pytestmark = pytest.mark.shards   # registered marker (pyproject.toml:73)

@settings(max_examples=1000, deadline=None)   # 1000 runs; deadline=None avoids CI flakes
@given(
    scheme=st.sampled_from(["http", "https", "urn"]),
    host=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.", min_size=3, max_size=20)
        .filter(lambda s: not s.startswith(".") and not s.endswith(".")),
    path=st.text(min_size=0, max_size=50),
    span=st.text(min_size=0, max_size=200),
)
def test_mint_is_deterministic(scheme, host, path, span) -> None:
    uri = f"{scheme}://{host}/{path}" if scheme != "urn" else f"urn:{host}:{path}"
    iri_a, hash_a = mint_shard_iri(uri, span)
    iri_b, hash_b = mint_shard_iri(uri, span)
    assert iri_a == iri_b and hash_a == hash_b
    assert iri_a.startswith("urn:folio:shard/")
    assert len(iri_a) == len("urn:folio:shard/") + 16   # <-- D-01: change 16 -> 32
```
**Required edits to existing test_minting_determinism.py** (hex16→hex32 fixture
re-mint, migration consequence): every `+ 16` / `h[:16]` assertion must become
`32` — lines 45 (`+ 16`), 89 (`+ 16`), 90 (`h[:16]`). These are mechanical.

**New directed vector for D-08 internal CRLF→LF** (the existing
`test_crlf_trimmed_from_span`, line 63, only covers *trailing* CRLF):
```python
def test_internal_crlf_normalized_to_lf() -> None:
    """D-08: internal CRLF / lone CR fold to LF -> same IRI as the LF form."""
    iri_crlf, _ = mint_shard_iri("urn:x:1", "line one\r\nline two")
    iri_cr, _   = mint_shard_iri("urn:x:1", "line one\rline two")
    iri_lf, _   = mint_shard_iri("urn:x:1", "line one\nline two")
    assert iri_crlf == iri_lf == iri_cr
```

**100K-shard collision test (D-05 — SHARD-08 exit criterion)** — mark `slow`
(pyproject.toml:71) since it exceeds the 30s default timeout (pyproject.toml:64).
Generate 100K synthetic `(uri, span)` pairs, mint each, assert all hex32 bodies
are distinct (no collision) and registry register is idempotent on re-register.
Scale-invariance smoke pattern from bench (`SMOKE_TARGET = 10_000`,
test_generator_determinism.py:13) — use a small N for the fast suite + the full
100K behind `@pytest.mark.slow`:
```python
@pytest.mark.slow
@pytest.mark.shards
def test_no_collision_at_100k() -> None:
    seen: dict[str, str] = {}   # iri_body -> full_hash
    for i in range(100_000):
        iri, full = mint_shard_iri(f"urn:synthetic:{i}", f"span body {i}")
        body = iri.removeprefix("urn:folio:shard/")
        assert body not in seen or seen[body] == full, "hex32 collision!"
        seen[body] = full
    assert len(seen) == 100_000
```

**Registry collision-detection test (async)** — `asyncio_mode = "auto"`
(pyproject.toml:63) means `async def test_...` runs without a decorator. Use a
`tmp_path` SQLite DB (test_owl_export.py:107-131 `tmp_db` fixture pattern). Assert:
same body + same full_hash → idempotent (returns existing IRI); same body +
forced different full_hash → raises the collision error (D-03 halt+flag).

**CLI test for `verify-iris`** — test_cli.py:9-22 `CliRunner` fixture:
```python
from click.testing import CliRunner
from folio_insights.cli import cli

@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()

def test_verify_iris_mismatch_exits_nonzero(runner, tmp_path) -> None:
    # seed registry with a deliberately-wrong stored IRI, then:
    result = runner.invoke(cli, ["verify-iris", ...])
    assert result.exit_code != 0   # D-07: non-zero on mismatch
```

## Shared Patterns

### aiosqlite direct-SQL, no ORM
**Source:** `src/folio_insights/services/iri_manager.py:71-97` (connect + row_factory
+ parametrized `?` SQL + `await db.commit()`).
**Apply to:** the new `shard_iri_registry` store.
```python
async with aiosqlite.connect(str(self._db_path)) as db:
    db.row_factory = aiosqlite.Row
    cursor = await db.execute("SELECT ... WHERE col = ?", (val,))
    row = await cursor.fetchone()
    await db.execute("INSERT INTO ... VALUES (?, ?)", (a, b))
    await db.commit()
```

### Click lazy-import discipline (heavy deps off `--help`)
**Source:** `src/folio_insights/cli.py:118,128,528-536`; `bench/cli.py` subgroup.
**Apply to:** `verify-iris`. All heavy imports (registry, mint, sqlite) go inside
the command body or at module bottom — never at module top.

### Pytest markers + asyncio auto-mode
**Source:** `pyproject.toml:62-74` (`asyncio_mode = "auto"`, `timeout = 30`,
markers `shards` + `slow`). Existing usage: `pytestmark = pytest.mark.shards`
(test_minting_determinism.py:20).
**Apply to:** all new Phase 4 tests — module-level `pytestmark = pytest.mark.shards`;
the 100K test additionally `@pytest.mark.slow`; async tests need no decorator.

### Pure-stdlib minting (no storage deps in shards/minting.py)
**Source:** `minting.py:18-22` (only `hashlib`, `unicodedata`, `urllib.parse`).
**Apply to:** keep `minting.py` storage-free. The aiosqlite registry is a
**separate module** (`shards/iri_registry.py`) that *imports* `mint_shard_iri`,
so `mint_shard_iri` stays pure and the determinism property test never touches I/O.

## No Analog Found

None. Every file has a concrete in-repo analog.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All 6 files have analogs (see above). |

## Metadata

**Analog search scope:** `src/folio_insights/shards/`, `src/folio_insights/services/`,
`src/folio_insights/` (cli.py, bench/cli.py, polysemy/cli.py), `tests/shards/`,
`tests/` (test_cli.py, test_owl_export.py), `tests/bench/`, `pyproject.toml`.
**Files scanned:** ~14 (3 modify targets + iri_manager.py + 3 CLI modules +
4 test modules + pyproject.toml + shards/__init__.py).
**Pattern extraction date:** 2026-05-24

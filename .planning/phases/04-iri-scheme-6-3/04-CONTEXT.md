# Phase 4: IRI Scheme (§6.3) - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden the **already-built** provenance-hash *shard* IRI scheme (REQ SHARD-07, SHARD-08).
Phase 2's `mint_shard_iri()` already does the core minting (NFC + RFC 3986 + SHA-256 →
truncated hex body, `urn:folio:shard/<hex>`); this phase does NOT rebuild it. Phase 4 delivers:

1. Widen the IRI body to **hex32 (128-bit)** so collisions are practically impossible.
2. **Online collision detection** at mint via a global registry, with a halt+flag fallback.
3. A **nightly re-hash verification** CLI job (`verify-iris`).
4. Complete the canonicalization (add internal **CRLF→LF**) to match the SHARD-07 spec.

**NOT in scope:** FOLIO-*entity* IRIs (`services/iri_manager.py` / `generate_folio_iri`,
the OWL-concept `iri_registry`) are a separate, already-built system with their own collision
avoidance — do NOT conflate them with shard IRIs. Content versioning (SHARD-09/10) is Phase 5.
</domain>

<decisions>
## Implementation Decisions

### IRI Width & Collision Fallback
- **D-01:** Shard IRI body widens from `hex16` → **`hex32`** (first 32 hex chars of SHA-256 = 128-bit): `urn:folio:shard/<32-hex>`. This **amends** SHARD-07's documented `/shard/<hex16>` and **Phase 2 D-02** (`_IRI_HEX_LEN = 16`). Rationale: at 128-bit, birthday-collision odds are ~1e-29 even at 1 billion shards (vs ~3% for hex16 near 1B), so collisions become a never-expected safety-net case rather than a runtime concern. Operator chose "widest, then flag" over runtime hex-widening.
- **D-02:** `mint_shard_iri()` keeps returning the full 64-hex SHA-256 unchanged; only the IRI-body truncation length changes (16 → 32). The full hash is what the registry stores for collision comparison.
- **D-03:** Collision fallback = **halt + flag for manual review** (refuse to mint, log the (uri, span) pair + both IRIs). NOT a runtime widen-on-collision scheme — the fixed wide width makes this path effectively unreachable.

### Collision Detection
- **D-04:** **Online detection at mint** via a **global** `shard_iri_registry` (shard IRIs are content-addressed and corpus-independent — the registry is global, NOT a per-corpus `review.db`). At mint: look up the hex32 body; same body + same full hash → idempotent (return existing); same body + **different** full hash → collision → halt+flag (D-03).
- **D-05:** The detector must be exercised at **100K shards** (SHARD-08 exit criterion) via a synthetic test (not the real corpus).

### Re-hash Verification Job
- **D-06:** Ship a `folio-insights verify-iris` CLI command that re-mints each stored shard's IRI from its stored `source_uri` + `source_span` and compares to the stored IRI. A mismatch means source drift or a hash-logic regression.
- **D-07:** Wire it as a **nightly CI job**; on mismatch → **non-zero exit + log/alert report** (do NOT auto-quarantine — surface for human review). The CLI command is the Phase 4 deliverable; the CI/cron wiring is thin glue (heavier scheduling/alerting is Phase 12 Observability if needed).

### Canonicalization
- **D-08:** Extend the span canonicalization to add internal **CRLF→LF (and lone CR→LF)** normalization before NFC + trim, matching SHARD-07's "NFC + LF + trim + RFC 3986". Same text with differing line endings → same IRI. This re-hashes existing multi-line CRLF spans (few shards exist — acceptable now).
- **D-09:** The 1000-run determinism property test (SHARD-07 exit criterion 1) must cover the full pipeline: NFC + LF + trim + RFC 3986 ⇒ same (source, span) → same hex32 IRI across runs.

### Migration consequence (applies to D-01/D-08)
- Widening to hex32 + CRLF→LF re-mints existing shard IRIs. Mechanical updates required: `_IRI_HEX_LEN` in `minting.py`, the `[a-f0-9]{16}` regexes in `envelope.py` and `subtypes.py` (`{16}`→`{32}`), and any hex16 fixture IRIs. The planner enumerates the full blast radius.

### Claude's Discretion
- Exact `shard_iri_registry` schema + storage location (a dedicated global SQLite file vs. extending an existing store) — planner decides, honoring "global, not per-corpus."
- Sequencing of the hex16→hex32 fixture re-mint (mechanical).
- Whether `verify-iris` also opportunistically re-scans for body collisions (cheap defense-in-depth add-on).

### Folded Todos
None — no pending todos matched this phase (STATE pending-todos = none).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Shard IRI scheme & collisions (SHARD-07 / SHARD-08)
- `.planning/REQUIREMENTS.md` (rows SHARD-07, SHARD-08) — acceptance criteria (determinism property test; collision test @100K; nightly re-hash).
- `PRD-v2.0-draft-2.md` §6.3 — provenance-hash IRI minting (SHA-256 over source_uri + source_span; "decision #6").
- `PRD-v2.0-draft-2.md` §21.6 — IRI collision space + detector requirements (collision space > 2³²).
- `.planning/research/PITFALLS.md` — RISK-3 (canonicalization pitfall: NFC / line-endings / trim / RFC 3986). The authoritative pitfall write-up.

### Existing code to extend / reuse (Phase 2/3)
- `src/folio_insights/shards/minting.py` — `mint_shard_iri()` + `_IRI_HEX_LEN`, `_normalize_uri`, `_normalize_span`. EXTEND (width 16→32; add CRLF→LF); do not rewrite. Returns `(iri, full_64hex)`.
- `src/folio_insights/shards/envelope.py` — `_IRI_PREFIX` + the `[a-f0-9]{16}` IRI regex (update to `{32}`).
- `src/folio_insights/shards/subtypes.py` — GlossShard `glosses` IRI regex `^urn:folio:shard/[a-f0-9]{16}$` + IRI_HEX refs (update to `{32}`; legacy `^https?://` alias unaffected).
- `src/folio_insights/services/iri_manager.py` — **SEPARATE** FOLIO-entity IRI system. Reference only to avoid conflation; NOT modified by this phase.

### Prior decisions (carried forward / amended)
- `.planning/phases/02-shard-envelope/02-CONTEXT.md` — Phase 2 D-02 locked the `urn:folio:shard/` prefix + hex16 width (this phase's D-01 amends the width to hex32).
- `.planning/phases/03-shard-subtypes/03-CONTEXT.md` — scoped Phase 4 to "narrow to collision detection"; GlossShard format-only IRI validation (referential integrity deferred).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `mint_shard_iri(source_uri, source_span) -> (iri, full_hash)` (minting.py) — the canonical minter. Phase 4 extends it (truncation width + CRLF→LF) and routes it through the collision-aware registry. The full 64-hex return value is exactly what the registry needs for collision comparison.

### Established Patterns
- **aiosqlite direct-SQL, no ORM** (cf. `services/iri_manager.py` `iri_registry`, `api/db/`) — the new global `shard_iri_registry` follows this pattern.
- **Click CLI with lazy imports** (cf. `cli` serve/export/discover) — `verify-iris` follows this; keep heavy deps off `--help`.
- **Hypothesis property tests** (Phase 2 minting determinism) — extend for the SHARD-07 1000-run test over the full NFC+LF+trim+RFC3986 pipeline.

### Integration Points
- Shard creation/mint paths from Phase 2/3 call into the registry-aware mint (online collision check).
- CI workflow gains a nightly `verify-iris` job (wiring point: `ci/` or `.github/workflows`).
</code_context>

<specifics>
## Specific Ideas

- Operator's framing (adopted): "default to a higher hex size — which reduces collisions even more — and then in that astronomically low percentage, flag for manual review." → hex32 (128-bit) + online detect + halt/flag.
- Operator explicitly distinguished FOLIO-entity IRIs vs shard IRIs; CONTEXT keeps them separate so downstream agents don't conflate `iri_manager.py` with the shard scheme.
</specifics>

<deferred>
## Deferred Ideas

- **Runtime hex-widening on collision** (an alternative fallback) — rejected in favor of a fixed wide width; not needed at 128-bit.
- **Auto-quarantine on `verify-iris` mismatch** — deferred; log+alert for now. Quarantine could be a later hardening.
- **Richer nightly-job scheduling/alerting** beyond thin CI wiring — Phase 12 (Observability) territory.
- **FOLIO-entity IRI collision behavior** — separate existing system (`iri_manager.py`), out of scope here.
- **Referential integrity of IRI references** (does a cited shard IRI actually exist?) — already deferred by Phase 3; not reopened here.

### Reviewed Todos (not folded)
None — no pending todos to review.
</deferred>

---

*Phase: 4-IRI Scheme (§6.3)*
*Context gathered: 2026-05-24*

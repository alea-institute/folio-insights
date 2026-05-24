# Phase 4: IRI Scheme (§6.3) — Discussion Log

**Date:** 2026-05-24
**Mode:** discuss (default, batched per operator preference)

_Human-reference audit trail. Not consumed by downstream agents — see 04-CONTEXT.md for decisions._

## Framing established before questions
- Scouted code: Phase 2's `mint_shard_iri()` already mints provenance-hash IRIs (NFC + RFC 3986 + SHA-256 → hex body). Phase 3 CONTEXT pre-scoped Phase 4 to "narrow to collision detection." So Phase 4 = harden, not build.
- Distinguished shard IRIs (this phase) from FOLIO-entity IRIs (`iri_manager.py`, separate/existing).

## Gray areas selected
Operator selected all four: Collision fallback, Detection mechanism, Re-hash job, Canonicalization.

## Decisions

### Collision fallback + IRI width
- **Options presented:** registry-detect+widen-on-collision / halt+flag / append -N suffix.
- **Operator response:** asked to clarify FOLIO-vs-shard IRIs, then proposed "default to a higher hex size to reduce collisions even more, then flag the astronomically-low collision for manual review."
- **Follow-up (width):** hex24 / hex32 / keep hex16 presented with birthday-collision odds + the amend-spec/regex/re-hash ripple. Operator asked "will hex32 have any downside? if not, go hex32."
- **Resolved:** hex32 (128-bit) body; halt+flag fallback (never-expected at 128-bit). Amends SHARD-07 hex16 + Phase 2 D-02 + envelope/gloss regexes + re-hash fixtures.

### Detection mechanism
- **Options:** online registry check at mint / offline batch scan / both.
- **Selected:** online registry check at mint (global `shard_iri_registry`, content-addressed → not per-corpus).

### Re-hash verification job
- **Options:** CLI+CI+log/alert / CLI+fail-hard+quarantine / library-fn-only.
- **Selected:** `verify-iris` CLI, nightly CI, mismatch → non-zero exit + log/alert (no auto-quarantine).

### Canonicalization completeness
- **Options:** add internal CRLF→LF / keep trailing-strip only / you-decide.
- **Selected:** add internal CRLF→LF to match SHARD-07 "NFC + LF + trim + RFC 3986".

## Deferred ideas
Runtime hex-widening (rejected for fixed wide width); auto-quarantine on verify mismatch; richer scheduling (Phase 12); FOLIO-entity IRI collisions (separate system); referential integrity (already deferred by Phase 3).

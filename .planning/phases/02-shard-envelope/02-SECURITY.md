---
phase: 02
slug: shard-envelope
status: verified
threats_open: 0
threats_closed: 25
threats_mitigated: 15
threats_accepted: 10
asvs_level: 1
created: 2026-04-24
scope: Pure Python data-model package under src/folio_insights/shards/; no HTTP ingress; no multi-tenancy; no untrusted-input path in Phase 2
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> SECURED — all 25 threats have a documented disposition (15 mitigated in code, 10 accepted with named downstream-phase mitigations).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Python module boundary (`folio_insights.shards`) | Public API surface for downstream phases | Pydantic model classes + mint_shard_iri function + ContentEdit/add_edit helpers |
| Frozen identity fields ↔ mutable body fields (within `ShardEnvelope`) | 6 identity-origin fields are immutable after construction; 15+ mutable fields carry ContentEdit audit trail | N/A — in-process enforcement via Pydantic `Field(frozen=True)` |
| Source-text ingest ↔ provenance hash (in `mint_shard_iri`) | `source_uri` + `source_span` → NFC+RFC3986+LF-trim → SHA-256 | Cross-platform deterministic (hypothesis 1000-example verified) |
| `content_edits: list["ContentEdit"]` forward ref (envelope.py → audit.py) | Resolved via `ShardEnvelope.model_rebuild()` at audit.py module bottom | Pydantic schema-level; no runtime data crossing |
| Test-only fixtures (`tests/shards/conftest.py`) | Fixtures use real `mint_shard_iri()`-derived IRIs so tests exercise the minting contract end-to-end | Synthetic test data only |

**Out of Phase 2 scope (no boundary crossed yet):** HTTP ingress, DID signature verification, SPARQL query surface, multi-tenant corpus isolation, user-facing input validation. These appear in Phases 6 (DID), 10 (Stage 8 ingest), 13 (storage + PII gate), 16 (public SPARQL/write API), 19 (pre-release audit).

---

## Threat Register

### Wave 1 — 02-01 (envelope + subtypes + minting)

| Threat ID | Category | Component | Disposition | Mitigation / Control | Status |
|-----------|----------|-----------|-------------|----------------------|--------|
| T-02-01-01 | Tampering (frozen-field bypass) | `envelope.py` | mitigate | `envelope.py:101-106` — 6× `Field(frozen=True)` on shard_iri/provenance_hash/source_uri/source_span/extracted_at/first_extractor_did. Test `test_identity_fields_are_frozen` (test_envelope_roundtrip.py:281-289) parametrized over all 6 with `ValidationError(match="frozen")`. | closed |
| T-02-01-02 | Tampering (non-deterministic IRI minting) | `minting.py` | mitigate | `minting.py:46,60-64` — `unicodedata.normalize("NFC", ...)`, LF-only `"\n"` separator, `str.strip()`, RFC 3986 normalization (`urlsplit`/`urlunsplit`, lowercase scheme+host, trailing-slash strip). Hypothesis 1000-example property test `test_mint_is_deterministic` passes. | closed |
| T-02-01-03 | Information Disclosure (PII in frozen `source_span`) | `envelope.py` | accept | Envelope is content-agnostic in Phase 2; PII redaction is an ingest-time concern. Downstream: Phase 13 STORAGE-07. | closed |
| T-02-01-04 | Spoofing (`first_extractor_did` unverified) | `envelope.py` | accept | `AttestedSignature` is a permissive STUB (`ConfigDict(extra="allow")` at `envelope.py:60`). Phase 6 replaces with real ed25519 verification. | closed |
| T-02-01-05 | Elevation (`content_edits` / `signatures` un-gated append) | `envelope.py` + `audit.py` | accept | Forward-only SHACL gate lands in Phase 5. | closed |
| T-02-01-06 | DoS (unbounded `source_span` through SHA-256/NFC) | `minting.py` | accept | Phase 10 Stage 8 Shard Minter caps `source_span` at ingest (v1 baseline: 4 KB). | closed |
| T-02-01-07 | Tampering (Phase-13 dep leak into shards/) | all shards modules | mitigate | `grep -rE 'import (pyoxigraph\|rdflib\|oxrdflib\|owlready2)' src/folio_insights/shards/` returns zero matches. Automated guard `test_no_storage_import_in_phase2_shards` (test_dep_leak_guard.py:25-38) walks all shards `*.py`, asserts absence of `import {mod}` or `from {mod}` for all 4 modules. | closed |
| T-02-01-08 | Information Disclosure (userinfo in `source_uri` hashed) | `minting.py` | accept | Phase 10 Stage 8 strips `user:pass@` before minting. | closed |
| T-02-01-09 | Spoofing (16-hex IRI collision — birthday bound ~2^32 shards) | `minting.py` / `envelope.py` | accept | Full 64-hex SHA-256 stored on `ShardEnvelope.provenance_hash`. Phase 4 ships collision detection + nightly re-hash verification; escalation path extends IRI to 20 hex if collision observed. | closed |

### Wave 2 — 02-02 (audit + ContentEdit + hypothesis dep)

| Threat ID | Category | Component | Disposition | Mitigation / Control | Status |
|-----------|----------|-----------|-------------|----------------------|--------|
| T-02-02-01 | Tampering (ContentEdit record mutated post-construction) | `audit.py` | mitigate | `audit.py:47` — `model_config = ConfigDict(frozen=True, extra="forbid")`. Test `test_content_edit_is_frozen` (test_audit_log.py:483-490) asserts assignment raises `ValidationError`. | closed |
| T-02-02-02 | Tampering (`add_edit` swallows frozen-field raise silently) | `audit.py` | mitigate | `audit.py:86` — `setattr(shard, field_name, new_value)` with no try/except; raise propagates. Test `test_add_edit_on_frozen_field_raises` (test_audit_log.py:533-537) asserts `pytest.raises(ValidationError, match="frozen")` on `shard_iri`. Non-transactional behavior (ContentEdit appended before setattr) documented as Phase 5 hardening stub. | closed |
| T-02-02-03 | Information Disclosure (`old_value: Any` captures PII) | `audit.py` | accept | Phase 2 audit log is in-process only; Phase 5 adds per-field redaction policy; Phase 13 adds ingest-time PII gate. | closed |
| T-02-02-04 | Repudiation (ContentEdit lacks DID signature verification) | `audit.py` | accept | `editor_did: str` is unverified typed string. Phase 6 adds `AttestedSignature` over canonical ContentEdit hash. | closed |
| T-02-02-05 | Elevation (`add_edit` with unknown `field_name`) | `audit.py` | mitigate | `audit.py:76` — `getattr(shard, field_name)` raises `AttributeError` on unknown fields; propagates to caller. Phase 5 adds `validate_content_edit_shape()` preflight. | closed |
| T-02-02-06 | Tampering (forward-ref `list["ContentEdit"]` fails to resolve) | `envelope.py` + `audit.py` | mitigate | `audit.py:97` — `ShardEnvelope.model_rebuild()` at module bottom. Test `test_content_edits_survive_json_round_trip` (test_audit_log.py:540-547) asserts `isinstance(rehydrated.content_edits[0], ContentEdit)` after JSON round-trip — fails if rebuild didn't run. | closed |
| T-02-02-07 | DoS (unbounded `content_edits.append`) | `envelope.py` | accept | Phase 5 adds per-shard edit-count gate + SHACL shape. | closed |
| T-02-02-08 | Tampering (typo-squatted hypothesis package) | `pyproject.toml` | mitigate | Exact-string match `"hypothesis>=6.100"` in `pyproject.toml` `[project.optional-dependencies].dev`. Verified. | closed |

### Wave 3 — 02-03 (test suite)

| Threat ID | Category | Component | Disposition | Mitigation / Control | Status |
|-----------|----------|-----------|-------------|----------------------|--------|
| T-02-03-01 | Tampering (fixture `shard_iri` doesn't match real D-02 minted IRI) | `tests/shards/conftest.py` | mitigate | `conftest.py` derives fixture `shard_iri` + `provenance_hash` via real `mint_shard_iri("urn:x:fixture", "sample span")`. Tests exercise the minting contract, not a hand-written IRI. | closed |
| T-02-03-02 | Tampering (hypothesis finds platform-specific edge case) | `tests/shards/test_minting_determinism.py` | mitigate | `@settings(max_examples=1000, deadline=None)`. 1000/0/0 (passing/failing/invalid) per 02-03-SUMMARY.md. Hypothesis DB replays shrinking seeds across platforms. | closed |
| T-02-03-03 | Information Disclosure (hypothesis inputs leak to pytest stdout) | `tests/shards/test_minting_determinism.py` | accept | Inputs are synthetic (restricted alphabets); no PII possible. | closed |
| T-02-03-04 | Tampering (grep-guard tests silenced via `@pytest.mark.skip`) | `tests/shards/test_dep_leak_guard.py` | mitigate | `test_dep_leak_guard.py:25-38` contains no `@pytest.mark.skip` decorators. `/gsd-verify-work` reviewer gate is the procedural check against silent skips. | closed |
| T-02-03-05 | DoS (1000-example hypothesis run CI timeout) | `tests/shards/test_minting_determinism.py` | mitigate | `--timeout=120` + actual full-suite run was 0.69s. Comfortable headroom. | closed |
| T-02-03-06 | Repudiation (pydantic `"frozen"` substring could change across versions) | `tests/shards/test_*.py` | mitigate | `pytest.raises(ValidationError, match="frozen")` at test_envelope_roundtrip.py:288 and test_audit_log.py:536. Pydantic v2 `type="frozen_field"` reliably contains "frozen"; if Pydantic 3 rewords, test fails loudly with diagnostic — not a silent bypass. | closed |
| T-02-03-07 | Tampering (conftest import path breaks) | `tests/shards/conftest.py` + `pyproject.toml` | mitigate | `tests/__init__.py` present; `pyproject.toml` `[tool.pytest.ini_options].testpaths = ["tests"]`. 47 tests pass = import path live. | closed |
| T-02-03-08 | Elevation (future 6th subtype shadows 5-subtype parametrize table) | `envelope.py` (ShardType Literal) + `tests/shards/conftest.py` (_SUBTYPE_TABLE) | mitigate | `ShardType = Literal[5 values]` at envelope.py:40-46 is a schema change required before any 6th subtype. Phase 3 adds fields to existing subtypes, not new subtype classes. Conftest `_SUBTYPE_TABLE` has 5 entries matching Literal. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Deferred to | Accepted By | Date |
|---------|------------|-----------|-------------|-------------|------|
| AR-01 | T-02-01-03 | Envelope is content-agnostic; PII redaction is an ingest-time concern, not a data-model concern | Phase 13 (STORAGE-07 PII ingest gate) | Phase 02 maintainer | 2026-04-24 |
| AR-02 | T-02-01-04 | `AttestedSignature` ships as a permissive stub (`ConfigDict(extra="allow")`); DID substrate not yet built | Phase 6 (DID substrate — `AttestedSignature.verify()` + `did_doc_snapshot_at`) | Phase 02 maintainer | 2026-04-24 |
| AR-03 | T-02-01-05 | `content_edits` and `signatures` are un-gated appends in Phase 2; full SHACL shape + forward-only semantics require Phase 5 governance primitives | Phase 5 (forward-only SHACL gate + transactional `add_edit` wrapper) | Phase 02 maintainer | 2026-04-24 |
| AR-04 | T-02-01-06 | `source_span` unbounded through SHA-256/NFC; length-cap is an ingest policy, not envelope concern | Phase 10 Stage 8 Shard Minter (4 KB per-KnowledgeUnit baseline from v1) | Phase 02 maintainer | 2026-04-24 |
| AR-05 | T-02-01-08 | `user:pass@host` userinfo in `source_uri` gets hashed; ingest-time sanitization is Phase 10 Stage 8's job | Phase 10 Stage 8 (strip userinfo before minting) | Phase 02 maintainer | 2026-04-24 |
| AR-06 | T-02-01-09 | 16-hex IRI collision birthday bound ~2^32 shards; `provenance_hash` stores full 64 hex chars so Phase 4 can detect prefix collisions | Phase 4 (collision detection + nightly re-hash verification; escalation: 20-hex IRI if collision observed) | Phase 02 maintainer | 2026-04-24 |
| AR-07 | T-02-02-03 | Phase 2 audit log is in-process only; PII redaction requires both runtime policy (Phase 5) and ingest gate (Phase 13) | Phase 5 (per-field redaction policy) + Phase 13 (ingest-time PII gate) | Phase 02 maintainer | 2026-04-24 |
| AR-08 | T-02-02-04 | `editor_did: str` is unverified in Phase 2; real DID signature verification depends on Phase 6 substrate | Phase 6 (AttestedSignature over canonical ContentEdit hash) | Phase 02 maintainer | 2026-04-24 |
| AR-09 | T-02-02-07 | `content_edits` unbounded in Phase 2; per-shard edit-count gate is Phase 5's ContentEdit SHACL shape scope | Phase 5 (per-shard edit-count gate + SHACL shape) | Phase 02 maintainer | 2026-04-24 |
| AR-10 | T-02-03-03 | Hypothesis-generated inputs are synthetic with restricted alphabets; pytest stdout is developer-local; no PII/secret leakage path | No deferred work — inherent hypothesis-strategy property | Phase 02 maintainer | 2026-04-24 |

*Accepted risks do not resurface in future audit runs.*

---

## Unregistered Threat Flags from SUMMARY.md

None. Phase 2 SUMMARY.md files use a "known-stubs" table rather than a separate `## Threat Flags` section — all stubs map to registered accepted-risk threats (AR-02 / AR-03 / AR-07 / AR-08 / AR-09) whose downstream-phase plans are documented above.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-24 | 25 | 25 (15 mitigated + 10 accepted) | 0 | gsd-security-auditor (sonnet) via /gsd-secure-phase 02 |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log (AR-01 through AR-10)
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

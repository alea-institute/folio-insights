# FOLIO Insights

## What This Is

A knowledge extraction and ontology enrichment system that processes legal advocacy textbooks (pretrial, trial, and appellate) to extract structured advice, legal principles, case citations, procedural rules, and common pitfalls — then organizes them into a task hierarchy and serializes everything as a validated, FOLIO-compatible OWL module. The system includes a web UI for corpus management, pipeline processing, task review, and ontology export.

## Core Value

Every piece of actionable legal advocacy knowledge from these texts must be discoverable by task — so that any practitioner, AI system, or developer querying "how do I take an expert deposition" gets a structured, hierarchical set of techniques, principles, and warnings mapped to formal FOLIO concepts.

## Current State

**Shipped:** v1.1 Railway Dev Deploy + UAT Gap Closure (2026-04-20)
**Live URL:** https://folio-insights-production.up.railway.app
**Tests:** 203 passing (197 at v1.0 + 6 UAT regression tests from v1.1)
**Tech stack:** Python 3.11+, FastAPI, SvelteKit, SQLite (aiosqlite), rdflib, pyshacl, sentence-transformers; Dockerfile + railway.toml for Railway

**What v1.1 adds on top of v1.0:**
- Railway dev deploy: multi-stage Dockerfile (node:20-slim → python:3.11-slim), bundled viewer + API + 3.8 MB extraction dataset, `/health` healthcheck, non-root runtime, 120s healthcheck timeout
- `railway.toml` config-as-code + frontend relative-URL audit (zero hardcoded dev ports)
- **UAT I-1:** LLM-path FOLIO IRI resolution at 0.6 threshold + `proposed_class` routing (+4 tests)
- **UAT I-2:** Bundle export 422 → 404 parity (+2 tests)
- **UAT I-3:** Vite proxy 8700 → 9925 (unblocks viewer dev-mode UI)
- **UAT I-4:** Deterministic `output/demo/` approved-task fixture + idempotent seed script
- **UAT I-5:** `.dockerignore` excludes `output/.jobs/` — bundled corpora report `processing_status="completed"` on live Railway

**What v1.0 delivers (still core):**
- CLI batch pipeline: `folio-insights extract` → `discover` → `export`
- Web UI: Upload → Process → Discover Tasks → Review → Export (full end-to-end)
- 14-format document ingestion with tiered boundary detection
- 4-path FOLIO concept tagging against 27K+ labels with 5-stage confidence scoring
- Task hierarchy discovery with NLI contradiction detection
- SHACL-validated OWL output with Turtle, JSON-LD RAG chunks, browsable HTML, changelog

## Current Milestone: v2.0 shards-as-axioms

**Goal:** Refactor FOLIO Insights from enrichment pipeline into a federated, shard-based knowledge graph grounded in PHILOSOPHY.md — where every 15-field shard is a provenance-hashed micro-axiom queryable via SPARQL, reviewable by DID-signed attestations, and composable across a federated community.

**Target features:**
- Shard envelope (§6.1) with 5 subtypes (§6.2): SimpleAssertion, DisputedProposition, ConflictingAuthorities, Gloss, Hypothesis
- Provenance-hash IRI scheme (§6.3) + content versioning with append-only audit (§6.4) + DID-signed attestations (§6.5)
- New FOLIO v2 vocabulary + mini-BFO spine (§7)
- Seven design principles (§8.P1–P7): scholastic distinguo, polysemy forks, cluster validator, etc.
- LLM-provider-agnostic pipeline refactor via `instructor` (§9)
- SHACL hybrid validation — Pydantic-generated base + hand-written advanced shapes (§10)
- Oxigraph triplestore + named-graph storage (§11) with RDF-star
- Review UI redesign (§12) — polysemy forks, supersession timeline, SPARQL explorer, deep-link shard URLs
- Federated governance (§3.1 own phase) — PROV-O log, §21.10 downstream-weighs, open community
- Public SPARQL endpoint + DID-gated writes
- Community artifacts: CONTRIBUTING, CODE_OF_CONDUCT, GOVERNANCE, RFC process
- Pre-release security audit (crypto + OAuth + DID signing)
- WCAG 2.1 AA blocking gate; P95 SPARQL <500ms @ 1M triples

**Key context:**
- Greenfield on master — no `V1_COMPAT` flag, no v1 corpora to migrate
- Stack locked: Oxigraph (pyoxigraph) + rdflib bridge; owlready2 reasoner; Arq+Redis queue; `instructor` LLM abstraction; SvelteKit 5 + adapter-node (SSR); mkdocs-material docs
- CalVer (YYYY.MM) versioning; MIT license retained
- Honor-system `Warrant:` line in every commit citing §5 pattern + §21 decision
- Benchmark corpora: v1 advocacy (re-extracted) + FRE + Restatement of Contracts
- Decisions already captured in `.planning/v2.0-MILESTONE-BRIEF.md` (40+ Q&A resolved pre-milestone)

## Requirements

### Validated (v1.0)

- ✓ Ingest mixed MD source files of variable length — v1.0
- ✓ Detect advice unit boundaries using LLM-driven semantic segmentation — v1.0
- ✓ Tag all extracted knowledge units against full FOLIO ontology (~18,000 concepts) — v1.0
- ✓ Reuse folio-enrich's EntityRuler + LLM dual-path extraction and 5-stage confidence scoring — v1.0
- ✓ Produce enriched output that is both human-reviewable and machine-parseable — v1.0
- ✓ Discover top-level advocacy tasks from texts — v1.0
- ✓ Build hierarchical task trees with sub-tasks and best practices — v1.0
- ✓ Extract all knowledge types: advice, principles, citations, procedural rules, pitfalls — v1.0
- ✓ Map extracted advice into FOLIO OWL — v1.0
- ✓ Support multiple consumption modes: SPARQL/API, LLM RAG, UI browsing — v1.0
- ✓ Handle incremental corpus growth without reprocessing — v1.0
- ✓ Automated quality with confidence scoring — v1.0

### Active

See `.planning/REQUIREMENTS.md` for v2.0 scoped requirements (populated during milestone kickoff).

### Out of Scope

- User-facing legal advice UI — consumers build their own on top of the ontology
- Substantive legal analysis — we extract what books say, not evaluate legal merit
- Real-time / interactive processing — batch pipeline; quality over speed
- Source text rewriting — "ideas not expressions" means distill, not rewrite
- Multi-language support — English corpus; leverage FOLIO's multilingual labels passively

## Context

**Source Material:** Mixed MD files — chapter extracts from published advocacy textbooks and synthesized notes covering pretrial, trial, and appellate advocacy. Growing corpus.

**Dependencies:**
- `folio-enrich` (at `~/Coding Projects/folio-enrich`) — bridge adapter imports FolioService, EntityRuler, reconciler
- `folio-python` (at `~/Coding Projects/folio-python`) — IRI generation algorithm (UUID4 → base64 → alphanumeric)
- FOLIO ontology (alea-institute/FOLIO on GitHub) — ~18,000 legal concepts

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Extend folio-enrich via bridge adapter | Reuse proven extraction/scoring; avoid duplicating 13 export formats | ✓ Good — bridge imports 27K+ labels cleanly |
| Full FOLIO ontology (not subset) | Advocacy texts span procedural, evidentiary, and substantive law | ✓ Good — no missed connections |
| Discover task hierarchy from texts | More robust than predefined taxonomy | ✓ Good — discovered tasks user hadn't considered |
| Single OWL file with embedded SKOS/PROV-O annotations | Simpler than separate companion file; all metadata in one artifact | ✓ Good — superseded original companion-file plan |
| Advice as annotation properties on Task/Subtask classes | Simplest model — advice goes with the class | ✓ Good — clean OWL structure |
| Standalone IRI generation (reimplemented from folio-python) | Avoids 10s ontology download on every export | ✓ Good — fast, compatible |
| Standalone sentence-transformers for deduplication | FAISS index in folio_bridge sized for FOLIO concepts, not pairwise similarity | ✓ Good — documented design choice |
| SvelteKit adapter-static served by FastAPI | SPA mode for review viewer; FastAPI handles API + static files | ✓ Good — simple deployment |
| [Phase 01] Wilson 95% CI lower-bound as FP gate (not point estimate) | At N=22 point estimates overstate precision (pilot ECE 0.108–0.427) — CI lower bound is the only defensible gate | ✓ Good — 2.53% lower bound well below 10% gate; policy carries forward to Phase 9.P6 |
| [Phase 01] Cohen's kappa labeled "signal, not verdict" | Small-N kappa volatility documented in RESEARCH.md; prevents misread as a gate | ✓ Good — KAPPA_CAVEAT constant emitted from compute_fp_rate + in SUMMARY template |
| [Phase 01] Detector verdict stored as dict (not float confidence) | Pitfall A6: float-confidence regression reintroduces PRINCIPLE-06 auto-apply risk | ✓ Good — grep-guard regression tests enforce absence of `detector_confidence` in fp_audit.py |
| [Phase 01] Disagreements-only LLM audit report (D-4 lock) | Agreements add noise; only LLM-vs-reviewer disagreements need reviewer attention | ✓ Good — 2/22 disagreements surfaced; 20 agreements silently counted |
| [Phase 01] rich.prompt keystroke gate with no `default=` (PRINCIPLE-06) | Any default value lets review bypass the gate on empty input; re-prompt on invalid enforces human decision | ✓ Good — CliRunner test suite enumerates forbidden bypass flags; build fails if any are added |
| [Phase 01] Deterministic mock-LLM harness for offline phase close | Live Anthropic-API audit is reviewer sign-off work, not a phase gate; harness lets phase close without external cost | ✓ Good — `scripts/run_llm_audit_harness.py` produces committed fp-labeling-audit.md; same report shape as live run |
| [Phase 01] ed25519 reviewer DID stored at $HOME/.folio-insights/ (0600/0700) | Private key outside repo; Unix file perms match scope of single-maintainer spike; .gitignore belt-and-suspenders | ✓ Good — `reviewer.py:64/75/77` enforces perms; `.gitignore:43` excludes folder |
| [Phase 02] `ShardEnvelope` base class + 5 Literal-tagged subtypes + `Shard` discriminated-union (`Annotated[Union[...], Field(discriminator="shard_type")]`) | Pydantic-idiomatic; extension point is per-subtype class; invalid tag fails at validation time with useful error | ✓ Good — 47 tests green; round-trip and invalid-tag tests pass |
| [Phase 02] Per-field `Field(frozen=True)` on 6 identity-origin fields (shard_iri, provenance_hash, source_uri, source_span, extracted_at, first_extractor_did) | Declaration-local; Pydantic v2 raises `ValidationError(type="frozen_field")` on assignment | ✓ Good — parametrized test over all 6 fields passes |
| [Phase 02] Mint IRIs in Phase 2 (not deferred to Phase 4) | Makes round-trip tests real on day one; Phase 4 narrows to collision detection + nightly re-hash | ✓ Good — `mint_shard_iri()` shipped; hypothesis 1000/0/0 |
| [Phase 02] Provenance hash recipe: SHA-256(NFC(rfc3986_normalize(source_uri)) + "\n" + NFC(source_span).strip()); first 16 hex → `urn:folio:shard/` | Cross-platform deterministic; LF-only line endings; RFC 3986 URI normalization; Unicode NFC | ✓ Good — 1000 hypothesis examples verify determinism; overrides PRD's `https://` IRI form |
| [Phase 02] Bitemporal fields nullable (null = unbounded in SPARQL `--as-of`) | Legal-effective dates are rarely both-ended; null_start → −∞, null_end → +∞; simpler than sentinel dates | ✓ Good — test_bitemporal_null_unbounded_round_trip passes |
| [Phase 02] `transaction_time = Field(default_factory=lambda: datetime.now(UTC))` | tz-aware UTC always; default set at construction so Phase 2 round-trip tests don't need Phase 13 storage layer | ✓ Good — no Phase-13 dep leak; test_transaction_time_default_is_tz_aware_utc passes |
| [Phase 02] `shard_type` immutable; promotion = new shard with `supersedes = <old_iri>` | Preserves provenance; matches PRD §6.4 content-versioning and §7 supersession | ✓ Good — per-subtype `Literal[...]` class default locks the tag; Phase 7 governance adds the workflow |
| [Phase 02] `ContentEdit` frozen sub-model + `add_edit()` helper that mutates in place AND appends ContentEdit | In-place assignment keeps call-sites simple; audit trail is automatic; Phase 5 hardens with SHACL forward-only + transactional wrapper | ✓ Good — 7 audit-log tests green; frozen-field guard works |
| [Phase 02] `ShardEnvelope.model_rebuild()` at audit.py module bottom to resolve `list["ContentEdit"]` forward-string ref | Breaks the envelope.py ↔ audit.py circular import; `from __future__ import annotations` + deferred rebuild | ✓ Good — JSON round-trip with ContentEdit rehydrated as class instance confirms resolution |
| [Phase 02] Dep-leak grep-guard regression test parametrized over [pyoxigraph, rdflib, oxrdflib, owlready2] | Prevents Phase-13 storage deps from leaking into Phase 2 pure-data-model package | ✓ Good — test_dep_leak_guard.py walks all shards `*.py`; zero matches |
| [Phase 02] Pydantic v2 frozen-field tests assert on `ValidationError(type="frozen_field")` NOT v1's `FrozenFieldError` | Pydantic 2.13+ is the locked version; v1 exception name would silently pass if regex matched loosely | ✓ Good — PATTERNS.md flagged this; tests use `match="frozen"` substring check |
| [Phase 02] `hypothesis>=6.100` added to `[project.optional-dependencies].dev` (Phase 2 is first adopter) | Property-based testing for minting determinism; 1000 max_examples; `deadline=None` to tolerate CI variance | ✓ Good — installed as hypothesis 6.152.2; 1000-example run < 1s on dev box |
| [Phase 03] All 5 subtypes + 3 nested models (`Objection`, `Reply`, `AuthorityPosition`) live in single `subtypes.py` (no per-subtype-file split) | Subtype-specific fields are small (3-7 fields each); single-file keeps discriminated-union literal-tag locks visible together; matches Phase 02 footprint | ✓ Good — 268 LOC; 4 `@model_validator(mode='after')` blocks colocated with each subtype; `__all__` export-controlled |
| [Phase 03] D-03 substitution: `DisputedPropositionShard` validator narrows envelope to `{hypothesis, authority_only, contested, aporetic}` (4-subset) | PRD §6.2.2 specified `attested` but the envelope ships no `"attested"` Literal value — `"authority_only"` is the closest substitute; planner-resolved 2026-04-25 | ✓ Good — REQ SHARD-03 satisfied via substitution; `"attested"` absent from `subtypes.py` and test data |
| [Phase 03] D-04 lock: `ReconciliationStrategy` Literal is exactly 8 values, NO 9th `"custom"` escape hatch | Schema honesty — practitioners must use `reconciliation_note` for novel reasoning, not invent ad-hoc strategy values; matches PRD §6.2.3 enum closure | ✓ Good — Literal lock prevents drift; `test_each_reconciliation_strategy_constructs` parametrizes over all 8 |
| [Phase 03] D-05: `GlossShard` IRI validator is format-only (URI shape regex), defers referential integrity to Phase 5/13 | Phase 3 is pure-data-model; cross-shard IRI resolution belongs to triplestore (Phase 13) and SHACL hybrid (Phase 5) | ✓ Good — empty-string IRIs flagged in code review (WR-01) but accepted by spec; Phase 5/13 will harden |
| [Phase 03] D-06: `HypothesisShard` ships `citation_required: bool = True` field but enforces NO promotion gate in Phase 3 | Phase 7 governance owns the promotion-time gate end-to-end; Phase 3 only ships the field so Phase 7 can read it | ✓ Good — `test_citation_required_true_with_empty_deps_constructs` documents and asserts the deferred-gate behavior |
| [Phase 03] D-09 budget: 100/300/200/200/200 hypothesis examples across 5 subtypes (1000 total) | Per-subtype example counts roughly proportional to invariant complexity (DisputedProposition has 4 invariants → 300 examples) | ✓ Good — property-test runtime 0.54s, 3.7× under D-09 2s target |
| [Phase 03] `_SUBTYPE_DEFAULTS` extension to `tests/shards/conftest.py` carries Phase 02's `_sample_shard(cls)` builder forward | Per-subtype default-dict (objections=[], glosses=[], generation_method="manual_review", etc.) lets Phase 03 tests construct valid instances without callers passing every required field | ✓ Good — 129 tests construct via `_sample_shard(cls, **overrides)` cleanly; 47 Phase 02 tests still green |
| [Phase 05] All RDF/SHACL code lives in a new `src/folio_insights/revision/` package, NOT in `shards/` | `tests/shards/test_dep_leak_guard.py` forbids rdflib/pyshacl/pyoxigraph under `shards/`; the guard *forced* the layout (not a discretionary choice) — pattern-mapper surfaced it pre-planning | ✓ Good — dep-leak guard green; `revision/content_edit.py` + `shape_validation.py` + `content_edit_shape.ttl` carry the RDF; `shards/` stays pure-Pydantic |
| [Phase 05] D-07 two-layer forward-only enforcement: Pydantic `@model_validator` is authoritative; pyshacl `sh:sparql` shape is defense-in-depth | SHACL is stateless over one snapshot so it can only enforce monotonic-`edited_at` (the forward-only half); immutability-of-past-entries is carried by `frozen` + append-only list + `IMMUTABLE_FIELD_PATHS`. The "SHACL guard" (exit criterion 2) is read literally — a real shape ships now, not deferred to Phase 11 | ✓ Good — both-polarity test proves back-dated insert → conforms=False, ordered chain → conforms=True (live-spiked against pyshacl 0.31.0) |
| [Phase 05] D-05 `canonical_content_hash()` is a REAL deterministic content hash now, excluding `transaction_time`, `valid_time_start/end`, `content_edits`, `signatures` | A content hash must bind *content*, not storage timestamps or the audit/signature logs; code review (CR-02) caught `transaction_time` leaking in and breaking cross-instance determinism. Phase 6 swaps JCS into the single `json.dumps` line without touching the call site | ✓ Good — identical content built 10ms apart hashes identically; 218 tests green |
| [Phase 05] `edit_shard_content()` edits a deep `model_copy` and `validate_shard()`s it before `store.put()` | Code review (CR-01) found the in-memory store was corrupted in-place when post-edit validation raised (get() returns the stored reference); editing a copy makes the write transactional — the stored shard is byte-for-byte intact on any failure (mirrors the D-09 reverse-replay no-mutation rule) | ✓ Good — regression test: a post-set_field validation failure leaves the stored shard unmutated with zero new content_edits |
| [Phase 06] D-12 `canonical_content_hash()` now uses RFC-8785 JCS (`jcs.canonicalize`) over `model_dump(mode="json")` with NFC + canonical-RFC3339-UTC + explicit-None pre-normalization | Phase 5 left a SHA-256-of-`model_dump_json()` placeholder that Pitfall F4 would silently break under field-order shuffle; JCS is the only canonicalization with a reference test corpus we can re-import (cyberphone/json-canonicalization) | ✓ Good — 1000-example shuffle property test green, 50 cross-impl golden vectors green (exit 2 closed) |
| [Phase 06] D-13 `AttestedSignature` shape: `extra=forbid`, `signing_key_id` + `did_doc_snapshot_at` + `verified` + reserved empty `cosigners[]`, `action` Literal reconciled against PRD §3.1 (12 members; 8 governance-track for the preview) | The Phase-5 stub had a wide `extra=allow` shape that would have silently swallowed typos; Phase 6 locks the shape so the verifier can resolve the SIGNING-TIME key (not the current one) — key rotation must not invalidate historical attestations | ✓ Good — EC3 rotation-survival test green for did:key + did:web; 9 per-action shape tests green |
| [Phase 06] D-07 / DID-06 signing keys live CLIENT-SIDE in `~/.folio-insights/identity/` (0700 dir + 0600 keyfile), mirroring the Phase-1 polysemy keystore | A server-side keystore turns the signing surface into a phishing/breach honeypot — the substrate's whole point is that the practitioner's private key never leaves their machine; static AST contract test enforces zero `private_bytes()` calls outside `keys.py` | ✓ Good — EC4 no-server-keys AST walker green; `test_no_server_keys_contract.py` walks every `identity/*.py` |
| [Phase 06] D-08 PLC method is RESOLVE-ONLY (no genesis/rotation writes); did:plc historical `at` raises in the default resolver | The atproto PLC op-log is the cryptographic substrate — implementing genesis/rotation correctly is its own project; refusing historical `at` defaults to fail-closed for F2 silent-wrong-key (a malicious or careless caller can't accidentally get the CURRENT key when they asked for a HISTORICAL one) | ✓ Good — `_default_plc_resolve` raises `UnsupportedHistoricalResolve`; code review CR-02 caught the original silent-fall-through and the regression test asserts the raise |
| [Phase 06] D-11 `DidDocCache` is an in-memory `Protocol`/`ABC` keyed by `(did, signed_at)` mirroring Phase-5 `ShardStore` for Phase-13 persistence swap | The verifier resolves the SIGNING-TIME key, so the cache key MUST include `signed_at` not just `did`; an in-memory Protocol lets Phase 13 swap a persistent backend without retesting any caller. Code review WR-06 caught the verifier silently fetching the CURRENT did.json on a cold cache (which would mark every historical signature as "verified" against a key that might have rotated) — now fails closed | ✓ Good — `test_did_doc_cache.py` green; cold-cache fail-closed regression test green for both did:web and did:plc |
| [Phase 06] SEC-06 / F7 GitHub-takeover defense: `bind()` enforces (a) `signature.did == did_being_bound`, (b) `sha256(jcs(proof.model_dump(mode="json"))) == signature.over_content_hash`, (c) single-use 5-min server nonce, (d) ±2-min timestamp, (e) exact binding-endpoint URL, (f) `sub`-change forces re-bind, (g) idempotent second bind of same `(sub, DID)` | The original `bind()` skipped (a) and (b) entirely — code review CR-01 walked through an end-to-end attack where an adversary who knows a victim's OAuth `sub` mints their own did:key, signs an unrelated hash, and binds the sub. The verifier only checks "signature valid over signature.over_content_hash" — bind() is the only place where the signature is bound to a specific PAYLOAD, and it must also be bound to the DID being claimed | ✓ Good — 3 regression tests (`test_attacker_cannot_bind_victim_sub_with_own_did`, `test_bind_rejects_proof_hash_mismatch`, `test_bind_rejects_signature_did_mismatch`) document the pre-fix attack vector and the post-fix closure |
| [Phase 06] D-10 / DID-05 `folio-insights did` Click subgroup ships `generate / bind / sign / verify / preview`; the web OAuth flow + styled preview defer to a post-Phase-14 surface | Phase 14 owns the design contract — duplicating the binding/preview UI now would diverge from the design system before it exists; the CLI is the contract Phase 14 will render | ✓ Good — `folio-insights did --help` shows all 5 subcommands; `did generate` produces a real `did:key:z6Mk...`; root `folio-insights --help` lists `did` alongside bench/polysemy |

## Constraints

- **Ontology format**: Valid OWL compatible with FOLIO structure
- **Pipeline reuse**: Build on folio-enrich's architecture via bridge
- **Growing corpus**: Incremental additions without reprocessing
- **Multi-consumer**: Serve SPARQL queries, LLM retrieval, and human browsing

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-28 — Phase 06 (DID Substrate §6.5) complete; DID-01 through DID-07, SEC-05, SEC-06 validated (DID-08 hardware-key + DID-09 multi-sig deferred to v2.0 P2 sub-phases 6.2/6.3). New `src/folio_insights/identity/` package — 10 modules over ~1,400 LOC: `keys.py` (client-side `~/.folio-insights/identity/` ed25519 keystore, 0700/0600 enforced, D-07/DID-06), `cache.py` (in-memory `DidDocCache` Protocol keyed by `(did, signed_at)`, D-11), `resolver.py` (did:key z-base58 decode + did:web HTTPS+SSRF-defended fetch + did:plc resolve-only per D-08), `signer.py` (PyNaCl ed25519 over JCS hash with signing-time `signing_key_id` + `did_doc_snapshot_at` capture), `verifier.py` (resolves SIGNING-TIME key, fails-closed on cold cache for historical did:web/did:plc), `binding.py` (`BindingRecord` + `ProofPayload` + `NonceStore` seam + SEC-06 `bind()` enforcing signature.did/proof-hash/nonce/timestamp/endpoint/sub-change/idempotency), `preview.py` (DID-07 "what will I be signing?" renderer for all 12 SignedAction members), `cli.py` (Click `did` subgroup wired into root). `shards/envelope.py` `AttestedSignature` reshaped to real D-13 form (`extra=forbid`, `signing_key_id`, `did_doc_snapshot_at`, `verified`, reserved `cosigners[]`). `revision/content_edit.py` `canonical_content_hash` swapped to RFC-8785 JCS with NFC + canonical-RFC3339-UTC + explicit-None pre-normalization (D-12); 1000-shuffle property test + 50 cross-impl golden vectors against `cyberphone/json-canonicalization` close Pitfall F4 (exit 2). Code review caught 4 Critical + 9 Warning — including a real F7 GitHub-takeover bypass in `bind()` (CR-01: signature.did and proof-hash were unverified, letting an attacker who knows a victim's OAuth `sub` mint their own did:key and hijack the bind), F2 silent-wrong-key in default PLC resolve (CR-02), missing did:web fetch size limit + SSRF defense (CR-03), and CLI eager-imported into the identity hot path (CR-04). All 13 in-scope findings fixed across 13 atomic commits with 28 new regression tests (zero regressions). 394 identity+shards+revision tests passing; `folio-insights did --help` lists generate/bind/sign/verify/preview. Stubbed for later: hardware-key (Phase 6.2 — DID-08), multi-sig + co-signing (Phase 6.3 — DID-09), persistent `DidDocCache` (Phase 13), styled web OAuth flow + preview (post-Phase 14 — D-02), F7 sub-shape strengthening that may need real-OAuth-provider tuning (WR-03). v2.0 milestone now 7/24 phases (00–06) done.*

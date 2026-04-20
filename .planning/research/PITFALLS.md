# Pitfalls Research — v2.0 shards-as-axioms

**Domain:** Federated shard-based legal knowledge graph; DID-signed attestations; Oxigraph + rdflib bridge; SHACL pipeline; SvelteKit SSR; Arq/Redis; `instructor` LLM abstraction; refactor layered on top of existing v1.1 FastAPI/SvelteKit/aiosqlite app
**Researched:** 2026-04-20
**Confidence:** HIGH on pitfalls grounded in STACK.md RISK-1..4 + ARCHITECTURE.md anti-patterns + PRD §16 risks (all three cross-validate); MEDIUM on SPARQL-endpoint security surface (verified against IBM LQE CVEs + OWASP + SPARQL injection survey) and Oxigraph-specific RDF-star→RDF 1.2 breaking change (verified from Oxigraph CHANGELOG for 0.5.0-beta.1); MEDIUM-LOW on polysemy-UX failure modes and community-governance attack patterns (few direct precedents; extrapolated from Wikidata + DAO attack literature). Each pitfall below carries its own provenance trail in the source paragraphs.

**Severity key used throughout:**
- **BLOCKING** — ships wrong = v2.0 cannot release; fix is expensive post-GA
- **HIGH** — degrades core value proposition or surfaces as a category-defining bug
- **MEDIUM** — measurable quality/perf/security regression; fixable but embarrassing
- **LOW** — nuisance, clean-up debt, or edge-case

---

## Executive Summary — The Ten Pitfalls That Sink v2.0

Ordered by expected damage × likelihood. If the roadmap addresses only ten things, address these:

1. **Oxigraph 0.5.x dropped RDF-star in favor of RDF 1.2; `<<?s ?p ?o>>` in subject position breaks** (BLOCKING; Phase 0)
2. **Retraction cascade implemented as supersession (or vice versa) — the §21.9 collapse** (BLOCKING; Phase 9)
3. **Provenance-hash IRI non-determinism: whitespace/encoding drift between extractions** (BLOCKING; Phase 4)
4. **Public SPARQL endpoint permits `SERVICE` / `FROM NAMED` → SSRF + DoS** (BLOCKING; Phase 16+19)
5. **JCS canonicalization done on Pydantic `.model_dump()` instead of JCS-normalized JSON → signature non-determinism** (BLOCKING; Phase 6)
6. **DID key rotation breaks old signatures because verifier fetches current key not signing-time key** (HIGH; Phase 6+19)
7. **SHACL validation run on rdflib bridge at 1M triples → P95 SLO blown** (HIGH; Phase 0+11)
8. **Polysemy detector false positives on legal terms-of-art that SHOULD be polysemous** (HIGH; Phase 1+9)
9. **Arq migration leaves v1 disk-based jobs orphaned → corpora stuck in `processing` forever** (MEDIUM; Phase 10)
10. **`owlready2` HermiT JVM cold-start + OOM in worker container** (MEDIUM; Phase 0)

All ten are addressed in the dimension-keyed sections below.

---

## Critical Pitfalls — Dimension: DATA MODEL & SHARDS

### Pitfall D1: Oxigraph 0.5.x dropped RDF-star in favor of RDF 1.2 — `<<?s ?p ?o>>` in subject position breaks

**Severity:** BLOCKING
**Phase:** Phase 0 (spike gate) + Phase 13 (storage) + Phase 15 (RDF-star UI)

**What goes wrong:** `pyoxigraph` 0.5.0-beta.1 (now 0.5.7, our locked version) *dropped* `rdf-star` feature in favor of `rdf-12`. RDF 1.2 does **not** support triple terms in subject position. Any SPARQL-star query we write like `SELECT ?conf WHERE { <<:shardA :hasTriple :x>> :confidence ?conf }` (triple term as subject) returns empty/errors where it would have worked in 0.4.x. SvelteKit SPARQL explorer will silently produce wrong results when users type YASGUI RDF-star patterns learned from Wikidata docs.

**Why it happens:** STACK.md locked pyoxigraph 0.5.7 (released 2026-04-19) under the banner "supports RDF-star natively." The CHANGELOG quietly flipped this: rdf-star feature was removed. Team reads "RDF-star supported" from old tutorials; doesn't notice the 0.5 migration note. Existing `.trig`/`.nq` files from 0.4 may auto-migrate but Turtle-star serialization changed.

**How to avoid:**
- **Phase 0 spike must explicitly test:** annotation pattern (triple in object position: `:x :annotates <<:s :p :o>>`) AND reified-triple pattern (RDF 1.2 style with `rdf:Statement`) — determine which Oxigraph 0.5 accepts for our use cases (PRD §6.1 RDF-star confidence annotations, PRD §11 storage).
- **Pin pyoxigraph 0.5.7 exactly** (not `^0.5`) until Phase 13 has validated every query template against this specific version.
- **Rewrite every §20 PRD SPARQL example** to use RDF 1.2 triple-term-in-object-only syntax OR `rdf:Statement` reification; commit them as regression tests in `tests/sparql/test_rdf12_patterns.py`.
- **Document in `docs/sparql-cookbook.md`** that subject-position triple terms are NOT SUPPORTED and YASGUI users will see errors on Wikidata-style examples.
- **CI guard:** nightly test that runs every PRD §20 query and ships §15 templates against a 10K-shard fixture; fails on any RDF-star regression.

**Warning signs:**
- SPARQL queries returning 0 rows where expected to return data, without raising an error
- Turtle-star serialization output differs between `rdflib.Graph().serialize(format="ttls")` and `pyoxigraph.Store.dump(RdfFormat.TURTLE_STAR)`
- Shard `confidence` annotation reads back as `None` after round-trip
- User reports "my RDF-star query works on Wikidata Query Service but not on FOLIO Insights"

**Detection signals:**
- Phase 0 exit gate checklist should include: `test_rdf12_triple_term_object_position.py` PASS and `test_rdf12_triple_term_subject_position.py` documented-to-fail
- Prometheus counter: `sparql_query_empty_result_total{query_kind="rdf_star_subject"}` — should be 0 in normal operation; any uptick means the pattern is being used incorrectly
- Integration test in `tests/storage/test_oxigraph_rdflib_bridge_roundtrip.py` that asserts byte-exact Turtle-star round-trip equivalence

**Sources:** [Oxigraph CHANGELOG, 0.5.0-beta.1](https://github.com/oxigraph/oxigraph/blob/main/CHANGELOG.md) HIGH · STACK.md §Core Technologies (pyoxigraph 0.5.7 locked) HIGH · PRD §6.1 `signatures` and §11 RDF-star storage MEDIUM (assumes RDF-star works without specifying syntax)

---

### Pitfall D2: Provenance-hash IRI non-determinism — whitespace/encoding drift between extractions

**Severity:** BLOCKING
**Phase:** Phase 4 (IRI scheme)

**What goes wrong:** `mint_shard_iri(source_uri + "\n" + source_span)` produces *different* IRIs across re-extractions of the same source because:
- `source_span` is captured from the boundary detector once with Unix LF, later with Windows CRLF (v1's 14-format ingestion runs through multiple parsers)
- Unicode NFC vs NFD normalization drift (Restatement text uses §, ¶, — characters; smart quotes round-trip differently through JSON ↔ SQLite ↔ prompts)
- Trailing whitespace, leading BOM, NO-BREAK SPACE (U+00A0) introduced by PDF extraction
- `source_uri` has URL encoding differences (`%20` vs `+`) across ingestion paths

Result: re-extraction creates a *different* shard IRI for what should be the same shard. Decision #6 (idempotent re-runs) silently violated. Content edits land on the wrong shard. Signatures verify against content but IRIs don't match provenance claim. Permalinks in papers break.

**Why it happens:** PRD §6.3 specifies `SHA-256 of (source_uri + source_span)` but gives no canonicalization rule. The team assumes "we control the pipeline, it'll be deterministic" without testing cross-run deterministic identity.

**How to avoid:**
- **Define `canonicalize_source_span(text: str) -> str`** that: (1) NFC-normalizes Unicode, (2) strips leading/trailing whitespace, (3) converts all line endings to LF, (4) collapses runs of whitespace to single spaces OPTIONALLY per-corpus (Restatement preserves intra-span whitespace; advocacy texts don't) — record the normalization policy as corpus metadata.
- **Define `canonicalize_source_uri(uri: str) -> str`** using `rfc3986.normalize_uri` (schemes lowercased, percent-encoding uppercased, fragment stripped).
- **Property test** in `tests/shards/test_iri_determinism.py`: for 100 synthetic (uri, span) pairs, apply a random whitespace-adding noise transform; after canonicalization, IRIs must be identical.
- **Corpus-level re-extraction regression test**: re-extract the bundled v1 advocacy corpus TWICE under v2.0 pipeline, assert 100% IRI overlap.
- **CI smoke test**: check the Unicode-aware hash for the single canonical example `(sample_uri, "The formation of a contract requires a bargain.")` produces the IRI hex the PRD §18.A.1 fixture expects.

**Warning signs:**
- Re-extraction of an unchanged corpus produces a different `shards_written_total` count than the prior run
- User report "I re-ran extraction and my saved permalinks 404"
- Shard count climbing without new sources (shards being re-minted with different IRIs)

**Detection signals:**
- Metric: `shards_idempotent_reextract_ratio{corpus=...}` — should be 1.00 ± 0.001; deviation means non-determinism
- Nightly job `scripts/verify_iri_determinism.py` that re-hashes every shard's `source_span` and asserts hash matches stored `provenance_hash`
- SHACL shape that re-canonicalizes on read and raises a violation if hash drifts

**Sources:** PRD §6.3 + §21.6 HIGH · [FAIR Cookbook — Unique persistent identifiers](https://fairplus.github.io/the-fair-cookbook/content/recipes/findability/identifiers.html) MEDIUM · STACK.md jcs==0.2.1 pinned for content-hash canonicalization (analogous discipline needed for source canonicalization) HIGH

---

### Pitfall D3: Pydantic discriminated-union collapse on shard subtype deserialization

**Severity:** HIGH
**Phase:** Phase 3 (five subtypes)

**What goes wrong:** The 5 shard subtypes (§6.2) are modeled as Pydantic discriminated unions on `shard_type`. On deserialization from Turtle-star (where `shard_type` comes back as a string from SPARQL), Pydantic 2.13.3 tries to validate against every variant and picks the first that passes — if `DisputedPropositionShard.utrum` is `Optional[str]=None` to accommodate partial data, the validator coerces `ConflictingAuthoritiesShard` rows into `DisputedPropositionShard` silently. Downstream code treats conflicting-authorities as disputed propositions; reconciliation strategies go unused.

**Why it happens:** Pydantic discriminated unions require the discriminator field to be non-Optional on every variant AND every variant must declare its tag literally. Team adds new subtype-specific fields as `Optional` for dev convenience; discrimination collapses.

**How to avoid:**
- **Use Pydantic v2 `Annotated[Union[...], Field(discriminator='shard_type')]` with Literal typing** on the `shard_type` field of every variant. `shard_type: Literal["disputed_proposition"]` — not `str`.
- **Make every subtype-specific field required** (no `Optional`) — use `Field(default_factory=list)` for collections, not `None`.
- **Round-trip fixture** per subtype in `tests/shards/test_subtype_roundtrip.py`: JSON → Shard → Turtle-star → pyoxigraph → CONSTRUCT → rdflib → JSON; assert typed object matches original subtype class.
- **mypy strict mode** on `src/folio_insights/shards/` catches `Union[...]` without discriminator at typecheck time.

**Warning signs:**
- `type(shard)` in handlers is always the first variant in the Union (e.g., always `SimpleAssertionShard`)
- `isinstance(shard, DisputedPropositionShard)` returns False on known-disputed-proposition data
- SPARQL filter `FILTER(?shard_type = "conflicting_authorities")` returns shards that don't have `reconciliation_strategy`

**Detection signals:**
- Regression test: SELECT count by `shard_type` predicate matches `len(shards_by_pyclass)` Python-side
- Metric `shards_by_subtype_total{subtype=...}` should correlate 1:1 with SPARQL count by `fi:shardType`

**Sources:** Pydantic v2.13 discriminated unions docs HIGH · ARCHITECTURE.md Anti-Pattern 1 "Stringly-Typed Shard Subtypes" HIGH

---

### Pitfall D4: Shard IRI collision at 16-hex chars becomes non-trivial above ~2³² shards

**Severity:** MEDIUM
**Phase:** Phase 4 (IRI)

**What goes wrong:** PRD §21.6 flags this: 16 hex chars (64 bits) means birthday-paradox collision probability crosses 1% around 2³² = 4.3B shards. Brief's target is 1M-10M shards per corpus; federated deployment across many corpora + Llull combinatorial hypothesis generation could push a single Oxigraph store past this.

**Why it happens:** 16 hex looks like "enough entropy" intuitively; the birthday-paradox math is counter-intuitive.

**How to avoid:**
- **Collision detector at mint time** — every `mint_shard_iri()` call first checks `if iri in existing_shards_bloom_filter: escalate_length()` and extends to 20 hex chars for that corpus (per-corpus, not global, per PRD §21.6 tradeoff).
- **Store the full 64-char `provenance_hash`** (not just the IRI prefix) so verification can disambiguate collisions.
- **Corpus metadata** records current IRI length; never downgrades.
- **Collision alert** logs + Prometheus counter `shard_iri_collisions_total`.

**Warning signs:** Collision counter non-zero; new shards rejected as duplicates of semantically-different prior shards.

**Detection signals:** `shard_iri_collisions_total` > 0 → PagerDuty.

**Sources:** PRD §21.6 HIGH · birthday-paradox math (standard crypto result) HIGH

---

### Pitfall D5: Greenfield re-extraction regression — v1 JSON comparison tolerates too much drift

**Severity:** MEDIUM
**Phase:** Phase 10 (pipeline refactor) + Phase 17 (testing)

**What goes wrong:** ARCHITECTURE.md §4.3 says regression-compare v1 vs v2 via `scripts/compare_v1_v2_extraction.py` with targets "count ±10% to +30%, FOLIO tag Jaccard ≥0.85". These bands are wide enough that real extraction regressions slip through. The framework-detector + BFO-classifier + polysemy-detector all add new decision points; each can silently miscategorize hundreds of shards while the aggregate metric stays in-range.

**Why it happens:** Greenfield re-extraction with a richer model makes a perfect 1:1 comparison impossible; team accepts loose bands rather than designing shard-level regression.

**How to avoid:**
- **Layered regression harness**:
  - Tier 1 (aggregate): Jaccard on FOLIO tags ≥ 0.85 — *gates merge*
  - Tier 2 (per-document): for each source doc, shard count ±30%, FOLIO tag Jaccard ≥ 0.90 — *reports only*
  - Tier 3 (canonical sample): hand-curated 50-shard golden set from v1 advocacy corpus; v2 re-extract must produce shards covering 100% of golden source spans — *gates merge*
- **Tier 3 golden set is the real gate**; tiers 1-2 are diagnostics.
- **Per-subtype distribution check**: v2 subtype distribution must be within 20% of theoretical priors (SimpleAssertion ~60-80%, Disputed ~5-15%, etc.); skewed distributions mean classifier is broken.

**Warning signs:** Aggregate Jaccard passes but Tier 3 golden-set coverage <100%; some source spans silently un-extracted.

**Detection signals:** Golden-set coverage report; per-subtype distribution plot.

**Sources:** ARCHITECTURE.md §4.3 HIGH · PRD §17 success criterion 2 HIGH

---

## Critical Pitfalls — Dimension: FEDERATION & GOVERNANCE

### Pitfall F1: Retraction cascade collapse with supersession — the §21.9 distinction collapses in UX

**Severity:** BLOCKING
**Phase:** Phase 9 (P3 dependency graph) + Phase 15 (UI wizards)

**What goes wrong:** PRD §21.9 is the *philosophical crux*: supersession (valid-time boundary, both shards queryable) is NOT retraction (shard was wrong, cascade fires). In implementation, reviewers treat "I want this shard gone" as "retract" when they mean "supersede." Legal users watching the governance log see false retractions of their citations and interpret them as system-imposed censorship. Or inverse: reviewer means "overruled" (retract) but picks "supersede" because the UI is less scary; cascading dependents silently remain citing bad law.

**Why it happens:** The categorical distinction is hard. Git has no analog (git revert ≠ retraction). Wikidata's "deprecated rank" flattens both. UIs naturally want a single "delete" button; FEATURES.md anti-feature explicitly calls out "unified delete button across retract/supersede/contest" as dangerous.

**How to avoid:**
- **Disambiguation prompt** (FEATURES.md H table stakes): three-way modal on every "disagreement" action. Mandatory; no back-door bypass.
- **Three distinct CLI commands** — `folio-insights retract`, `supersede`, `contest` — each with different arguments and prompts.
- **Preview-before-commit** on retraction: show dependent count + aporetic-transition count + arbiter-escalation count before user confirms; users see the blast radius.
- **Prohibition: no shared codepath** for retract + supersede in storage. Retract appends `fi:retractionEvent` (triggers P3 cascade); supersede appends `fi:supersededBy` (does NOT cascade). Keeping them syntactically distinct at the SPARQL level makes confusion discoverable via audit.
- **UX copy test**: 10 legal-domain users tested on "this holding has been overruled" → pick correct button; measure confusion rate; iterate.
- **Public governance log** renders each event distinctly (red "retracted" vs amber "superseded" banner); false-retraction errors become visually obvious, encouraging reviewer correction.

**Warning signs:**
- Governance log shows high `contest_votes` count on events tagged `retract` (users trying to un-do retracts they meant as supersedes)
- User-submitted issues about "censored shards" / "disappearing case law" / "why did my citation vanish"
- Ratio of supersede:retract:contest events skews wildly from expected (supersede should dominate ~60-70%; retract <10%)

**Detection signals:**
- `governance_event_total{action_type="..."}` Prometheus label distribution
- Monthly governance log manual review for false-retractions of non-overruled case law
- Reviewer-DID-level event patterns: DID that does 90%+ retracts likely misunderstands the model

**Sources:** PRD §21.8 + §21.9 HIGH · FEATURES.md H table stakes + anti-features HIGH · [American Bar Association — Stare Decisis](https://www.americanbar.org/groups/public_education/publications/preview_home/understand-stare-decisis/) (distinguishes overruling from supersession) HIGH · [Judicature — Statutory Overrides](https://judicature.duke.edu/articles/how-courts-do-and-dont-respond-to-statutory-overrides/) — courts themselves confuse this; our reviewers will too MEDIUM

---

### Pitfall F2: DID key rotation breaks historical signatures — verifier fetches current key instead of signing-time key

**Severity:** HIGH
**Phase:** Phase 6 (DID attestations) + Phase 19 (security audit)

**What goes wrong:** Reviewer signs shard A with did:web key K1 in 2026. Reviewer rotates key to K2 (did:web document updated) in 2027. Verifier at 2028 fetches `https://example.com/.well-known/did.json` which now returns K2; signature over shard A's content hash was made by K1, but verifier checks against K2 → signature verification fails for a perfectly-valid historical attestation. Worse: did:plc rotation is first-class in AT Proto spec; every Bluesky-native reviewer rotates keys periodically.

**Why it happens:** Naive implementation treats "the DID's current key" as the verification key. Correct semantics requires fetching the key that was current at the signing timestamp — which for did:plc means querying the PLC operation log, for did:web means having cached historical did.json snapshots.

**How to avoid:**
- **Capture the verification key at signing time** — store `signing_key_id` (e.g., `did:plc:abc#key1` or `did:web:example.com#key-2026-04`) in the AttestedSignature; don't rely on "the DID's current key."
- **Resolve DID at signing time AND at verification time**, but store the key reference alongside the signature. Verification fetches the historical DID document if needed.
- **For did:plc**: use `atproto.IdResolver` with explicit revision pinning; the PLC directory exposes operation history — query the operation in effect at `signed_at`.
- **For did:web**: cache `did.json` snapshots at signing time in `attestation_cache` SQLite table (hash of did.json + first-seen-at + key fingerprints). Verifier looks up by signing timestamp.
- **Caching discipline**: cache headers respected; 24h TTL on current did.json fetches; no TTL on historical snapshots (immutable by design).
- **Phase 19 audit**: explicit test scenario — rotate a test did:web key, re-verify a prior signature, assert still verifies.
- **CI scenario**: `tests/did/test_signature_survives_key_rotation.py` — sign with K1, rotate DID doc to K2, re-verify signature; must pass.

**Warning signs:**
- Historical signatures transitioning from `verified=true` to `verified=false` without content edits
- did:web DID documents going 404 (domain lapsed; all historical signatures now unverifiable) — known failure mode per [did:web critique articles](https://agent.io/posts/risks-of-did-plc/)
- Spike in `attestation_verification_failures_total{reason="key_mismatch"}`

**Detection signals:**
- Metric: `attestation_verification_failures_total` labeled by `{reason: key_mismatch | did_not_found | signature_malformed}`
- Nightly job re-verifies a sampled N% of historical signatures; drift > 0.01% triggers investigation
- Alert on `did_document_resolve_failures_total > 0` for DIDs active in last 90 days

**Sources:** [did:plc Specification v0.1 — key rotation](https://web.plc.directory/spec/v0.1/did-plc) HIGH · [AT Proto Identity Guide — rotation](https://atproto.com/guides/identity) HIGH · [did:webvh Implementer Guide — valid keys](https://didwebvh.info/latest/implementers-guide/did-valid-keys/) HIGH · [Risks of did:plc](https://agent.io/posts/risks-of-did-plc/) MEDIUM

---

### Pitfall F3: OAuth + DID binding → token replay attack across OAuth-to-DID transition

**Severity:** HIGH
**Phase:** Phase 6 (DID) + Phase 14 (auth) + Phase 19 (audit)

**What goes wrong:** User logs in via GitHub OAuth → gets FastAPI session cookie → binds `did:key:z6Mk...` to their OAuth identity via a one-time signed-proof-of-control payload. Attacker steals the signed-proof-of-control payload (from server logs, network trace, or backup leak) — if payload has no nonce/timestamp or the binding endpoint accepts it indefinitely, attacker replays it with their own OAuth session and captures the DID binding as theirs. OAuth compromise then cascades to DID impersonation.

**Why it happens:** DID binding is novel; team designs it by analogy to OAuth flow without adding the freshness guarantees that OAuth PKCE + state + nonce provide. Salesloft-Drift 2025 breach precedent shows third-party token replay becomes enterprise-wide compromise.

**How to avoid:**
- **DID-binding proof MUST include:** (1) OAuth session ID, (2) server-issued nonce (single-use, 5-min TTL), (3) timestamp within ±2 min of server clock, (4) binding-endpoint URL.
- **Nonce store** in Redis with 5-min TTL, atomic GETDEL on use → replay returns "nonce already consumed".
- **Idempotency**: second binding attempt for same (OAuth, DID) pair is a no-op or explicit conflict; never an update.
- **PKCE + state + nonce** on OAuth itself (authlib supports; verify enabled).
- **DPoP token binding (RFC 9449)** on the DID-binding request so token-replay on OAuth side doesn't cascade — per [WorkOS 2025 token replay](https://workos.com/blog/token-replay-attacks) guidance.
- **Audit log of every binding event** in governance log; alerting on new DID-bindings from previously-unseen IPs + unusual geography.
- **Impossible-travel detection** per [Obsidian Security](https://www.obsidiansecurity.com/blog/token-replay-attacks-detection-prevention).
- **Phase 19 security audit** explicitly exercises replay: record a binding proof, replay 6 min later → must 401.

**Warning signs:**
- Same DID binding to two OAuth identities within 24h
- Binding events from IPs in different countries within minutes
- Unusual spike in binding failures with "nonce reused" error

**Detection signals:**
- `auth_binding_nonce_reuse_attempts_total` Prometheus counter
- Anomaly detection on binding-event IP geography
- Alert: any binding attempt where `signed_at` drifts > 5 min from server clock

**Sources:** [WorkOS — Token Replay Attacks](https://workos.com/blog/token-replay-attacks) HIGH · [OAuth 2.1 Security Pitfalls](https://identitymanagementinstitute.org/oauth-21-security-pitfalls/) HIGH · [Obsidian Security — Token Replay Detection](https://www.obsidiansecurity.com/blog/token-replay-attacks-detection-prevention) HIGH · PRD §16 R5 security audit requirement HIGH

---

### Pitfall F4: JCS canonicalization done on `Shard.model_dump()` instead of JCS-normalized JSON

**Severity:** BLOCKING
**Phase:** Phase 6 (DID attestations)

**What goes wrong:** `ARCHITECTURE.md Pattern 2` says: `canonical_content_hash(shard) = sha256(jcs.canonicalize(shard.model_dump(exclude={"signatures","content_edits"})))`. But Pydantic's `model_dump()` serialization is **non-canonical**: (1) datetime serializes as `"2026-04-19T14:23:11.000000+00:00"` or `"2026-04-19T14:23:11Z"` depending on version/settings — JCS then canonicalizes differently; (2) float fields (confidence scores) serialize at full precision but JCS requires IEEE 754 minimal representation; (3) Optional[str]=None becomes `null` but canonicalization may or may not include null fields; (4) Pydantic may reorder alias-mapped fields; (5) Unicode in `source_span` — Pydantic doesn't NFC-normalize; JCS does; hash differs between signing and verification if span contains smart quotes, em-dash, NBSP. Result: signer hashes one canonical form, verifier hashes a different one, signatures never verify.

**Why it happens:** JCS discipline (RFC 8785) is non-obvious: floats, dates, Unicode, null handling all have canonicalization rules that Pydantic doesn't know about. Team treats `jcs.canonicalize()` as a black box that handles everything.

**How to avoid:**
- **Single canonicalization function** `shard_canonical_json(shard: Shard) -> bytes`:
  1. Start with `shard.model_dump(mode="json", exclude={"signatures","content_edits"})` (not default mode — `mode="json"` ensures datetime → ISO string).
  2. NFC-normalize every string field (recursively walk).
  3. Round floats to 6 decimal places (confidence scores don't need more; documented per-corpus).
  4. Explicitly strip None values (JCS RFC 8785 handles but excluding avoids ambiguity).
  5. Force datetime serialization to `"YYYY-MM-DDTHH:MM:SS.ffffffZ"` fixed format (always 6 fractional seconds, always UTC, always Z suffix).
  6. Then apply `jcs.canonicalize()`.
- **Round-trip property test**: 1000 random shards → sign → serialize to Turtle-star → store → fetch → deserialize → verify signature. Must pass at 100%.
- **Cross-implementation test**: compare our Python canonicalizer output against a known-correct JCS implementation (reference implementation from [cyberphone/json-canonicalization](https://github.com/cyberphone/json-canonicalization)) on 50 golden inputs.
- **Never call `model_dump()` directly for signing** — always through `shard_canonical_json()`. Add a lint rule (`grep`-based, added to pre-commit) forbidding direct `.model_dump()` in `src/folio_insights/did/`.

**Warning signs:**
- Signatures verify on the signing host but fail on another host
- Signatures pass immediately after sign but fail after Turtle-star round-trip
- Floats in signed content display different precision in UI than in stored hash

**Detection signals:**
- Metric: `signatures_failed_verification_total{reason="hash_mismatch"}` — should be 0 for own-signed shards
- Property test in CI fails if canonicalization is non-deterministic
- Random-10% re-verification nightly job catches drift

**Sources:** [RFC 8785 JCS](https://www.rfc-editor.org/rfc/rfc8785) HIGH · [jcs PyPI](https://pypi.org/project/jcs/) HIGH · [Determinism in CBOR/JCS](https://cborbook.com/part_2/determinism.html) MEDIUM · ARCHITECTURE.md Pattern 2 (under-specified) MEDIUM

---

### Pitfall F5: Append-only governance log not actually append-only (SHACL enforced, storage forgot)

**Severity:** HIGH
**Phase:** Phase 7 (governance)

**What goes wrong:** PRD §3.1.5 "Governance log is append-only." SHACL shape forbids DELETE on governance log. But SHACL validates the RDF graph, not the underlying pyoxigraph RocksDB storage. A direct pyoxigraph call like `store.remove_graph(governance_graph_iri)` bypasses SHACL entirely. Or an admin uses pyoxigraph CLI/debug tool to delete. Or DELETE DATA SPARQL UPDATE on a (forgotten) write-enabled backdoor. Append-only invariant silently broken; audit log no longer tamper-evident.

**Why it happens:** SHACL enforces graph constraints; it doesn't enforce storage-level mutation policy. Team conflates "shape says no delete" with "storage can't delete."

**How to avoid:**
- **SQLite triggers** on any SQLite `governance_log_cache` table: `BEFORE UPDATE/DELETE → FAIL`.
- **pyoxigraph named-graph-level enforcement**: wrap the graph-writer so that `governance:*` named graphs refuse `delete_graph`/`remove_triples` operations at the application layer. Never expose raw Store to callers that might touch governance.
- **Cryptographic chain**: each governance event hash-chains over the prior event's hash (Merkle-like). Tampering breaks the chain; verification is deterministic. Detection doesn't depend on SHACL + storage integrity.
- **Nightly git commit** per brief: PROV-O dump + commit preserves history outside the store; rollback capability exists.
- **SPARQL endpoint gate**: explicitly reject any `DELETE` / `DROP GRAPH` / `CLEAR GRAPH` on governance graphs at the endpoint level, not just in SHACL.
- **Audit of Phase 19**: test that a user with `corpus_admin` role cannot delete governance log entries via any exposed API surface.

**Warning signs:**
- Governance log chain-hash verification fails on a random spot check
- Event count decreasing between snapshots (nightly git diff shows removals)
- `fi:priorEventHash` broken links in the chain

**Detection signals:**
- Metric: `governance_log_chain_integrity_violations_total` — should always be 0
- Nightly integrity verifier re-computes chain from genesis; first divergence is precise breakpoint
- Git log diff on `<corpus>/governance.ttl` shows only additions (ideally runs as a pre-receive hook or CI check on the nightly commit)

**Sources:** PRD §3.1.5 HIGH · [OWASP A09 Logging and Alerting Failures](https://owasp.org/Top10/2025/A09_2025-Security_Logging_and_Alerting_Failures/) HIGH · [Audit Logging Best Practices — Sonar](https://www.sonarsource.com/resources/library/audit-logging/) MEDIUM

---

### Pitfall F6: Role-assertion loop — corpus_admin revokes own role, corpus becomes unadministered

**Severity:** MEDIUM
**Phase:** Phase 7 (governance)

**What goes wrong:** Per §3.1.1, only corpus_admin can issue role assertions. corpus_admin accidentally (or under attack) signs a role-revocation for themselves. Now no DID has corpus_admin role; no one can issue new role assertions, no one can issue replacements; corpus is permanently stuck at current role state.

**Why it happens:** Self-referential authorization without a safety net.

**How to avoid:**
- **Refuse self-revocation** at the governance endpoint; must be signed by *another* corpus_admin (or the project-level admin DID).
- **At least two corpus_admins** per corpus enforced as an invariant; SHACL shape on corpus config.
- **Break-glass project-admin DID** that can restore role assertions if a corpus goes unadministered; clearly documented in GOVERNANCE.md.
- **Forked-recovery path**: if corpus goes unadministered, community can fork it (§3.1.1 allows this) and new corpus_admin issues role assertions on the fork.

**Warning signs:** Corpus has zero active corpus_admin bindings; governance log has orphan revocations.

**Detection signals:** Daily audit: for each corpus, count DIDs with active corpus_admin role. Alert if 0 or 1.

**Sources:** PRD §3.1.1 HIGH (gap — PRD doesn't specify self-revocation handling) · [DAO governance attack vectors — Olympix](https://olympixai.medium.com/governance-attack-vectors-in-daos-a-comprehensive-analysis-of-identification-and-prevention-e27c08d45ae4) MEDIUM

---

### Pitfall F7: Reviewer DID impersonation via GitHub username takeover

**Severity:** MEDIUM
**Phase:** Phase 14 (auth) + Phase 19

**What goes wrong:** Reviewer binds OAuth identity `github:alice` to `did:key:z6Mk...`. Reviewer later deletes their GitHub account. Another user registers the `alice` username. Now `github:alice` resolves to a different person, but the DID binding still associates this OAuth identity with the original DID. Subsequent OAuth logins from the new `alice` gain access to the original reviewer's bound DID.

**Why it happens:** GitHub (and similar providers) release usernames; email addresses can also be reassigned on enterprise SSO. DID binding naively uses `email` or `username` as the stable key.

**How to avoid:**
- **Bind to stable OAuth subject** (`sub` claim), not `email` or username. GitHub's `id` is immutable.
- **Detect email/username changes** on each OAuth callback; if subject changes, unbind old DID, require re-binding via fresh signed proof.
- **Warn user** if their OAuth provider identity has changed since last login: "Your GitHub username changed from `alice` to `alice-123`. If you did not make this change, your account may have been compromised."
- **Document in GOVERNANCE.md**: DIDs are the stable identity; OAuth is binding metadata. If OAuth is lost, DID remains under user's control via signing key.

**Warning signs:** OAuth `sub` changes between sessions; email changes; username changes.

**Detection signals:** Metric: `oauth_subject_change_detected_total`.

**Sources:** [GitHub — username-takeover analysis (general)](https://portswigger.net/web-security/oauth) MEDIUM · OAuth best-practices literature (multiple sources agree: use `sub` never `email`) HIGH

---

## Critical Pitfalls — Dimension: QUERY ENDPOINT & SPARQL

### Pitfall Q1: Public SPARQL endpoint exposes `SERVICE` / `FROM NAMED` → SSRF + DoS

**Severity:** BLOCKING
**Phase:** Phase 16 (endpoint) + Phase 19 (audit)

**What goes wrong:** SPARQL 1.1 `SERVICE <uri>` dereferences an external URL server-side; `FROM <uri>` and `FROM NAMED <uri>` same. Unrestricted, these allow an attacker to:
- SSRF to internal services (Redis, PostgreSQL, cloud-metadata endpoints `http://169.254.169.254/latest/meta-data/` — AWS credential theft)
- Turn our endpoint into a DoS amplifier against third parties
- Exfiltrate data from internal services that trust our server's IP
- Trigger dereference of extremely large remote TTL files → OOM

**Why it happens:** SPARQL engines ship with SERVICE enabled; team doesn't realize it dereferences URLs server-side; standard-compliance check-box gets checked; security review doesn't cover SPARQL semantics.

**How to avoid:**
- **Disable `SERVICE`** by default on public endpoint via pyoxigraph configuration (or pre-query parser-level rejection).
- **If `SERVICE` is needed** (federation is a stretch goal): allow-list of approved endpoints (Wikidata, DBpedia, FOLIO canonical). No free-form URIs.
- **Disable `FROM` / `FROM NAMED` with external URIs**; only allow named-graph IRIs within our namespace (`https://folio-insights.aleainstitute.ai/corpus/*`).
- **Pre-query parser**: parse SPARQL with rdflib/pyoxigraph parser before execution; reject if any `SERVICE` or external `FROM` found. (Parser-side enforcement is tamper-resistant vs. lexical scan.)
- **Network policy**: Docker container has egress firewall — can only connect to Redis, explicitly-allowed external services; blanket block on metadata endpoints, private IP ranges.
- **Query timeout 30s + row cap 10K + max-memory cap**: every SPARQL query runs under these limits; pyoxigraph `Store.query()` supports timeouts.
- **Rate limiting**: `fastapi-limiter` on `/sparql` by IP + by DID; 60 queries/min/IP typical.
- **Phase 19 audit**: run `sqlmap`-like tooling against our endpoint; verify SSRF blocked.

**Warning signs:**
- Egress traffic from the web container to unexpected IPs
- Queries with `SERVICE` keyword in the logs (should be zero after fix)
- Memory usage spike during SPARQL execution
- Request logs to `/sparql` with very long query bodies (> 50KB is suspicious)

**Detection signals:**
- `sparql_query_service_keyword_detected_total` — should be 0
- `container_egress_unexpected_ip_total` — Cilium/network-policy logs
- `sparql_query_duration_p99_seconds` — should be <30s; anomalies are attack signal
- AWS GuardDuty / equivalent for metadata-endpoint access attempts

**Sources:** [IBM Security Bulletin — CVE-2025-27550, CVE-2025-2134, CVE-2025-1823 Jazz Reporting SPARQL DoS](https://www.ibm.com/support/pages/node/7258083) HIGH · [TinySPARQL Security Considerations](https://tracker.api.gnome.org/security.html) HIGH · [SPARQL Security Considerations](https://sparql.dev/article/10_SPARQL_Query_Language_Security_and_Privacy_Considerations.html) HIGH · [Qualys Serverless SSRF 2026](https://blog.qualys.com/product-tech/2026/01/15/serverless-security-risks-identity-ssrf-rce) MEDIUM · FEATURES.md G anti-feature (SPARQL federation by default) HIGH

---

### Pitfall Q2: SPARQL UPDATE enabled on public endpoint (intentional or accidental)

**Severity:** BLOCKING
**Phase:** Phase 16

**What goes wrong:** Public endpoint configured to allow SPARQL UPDATE (INSERT/DELETE/DROP). Any anonymous user can write or destroy data. Or: read endpoint and write endpoint share URL but differ by HTTP method / header; misconfigured routing exposes write path anonymously.

**Why it happens:** SPARQL engines often default to both query and update; team sees `POST /sparql` working for queries and doesn't realize UPDATE comes with it.

**How to avoid:**
- **Two distinct URLs**: `/sparql` (GET + POST-form for query only) vs `/api/shards` (POST-JSON, DID-signed, NOT SPARQL UPDATE).
- **pyoxigraph read-only mode** on web-tier `Store` handle: open with explicit read-only flag; writes would require a different connection (only the worker tier holds the write-capable store).
- **Path-level method restrictions**: `/sparql` only accepts SELECT/ASK/CONSTRUCT/DESCRIBE queries; UPDATE keywords (INSERT, DELETE, DROP, CLEAR, LOAD, CREATE) rejected at parse time.
- **Parser-side enforcement**: every query goes through a SPARQL parser that rejects UPDATE-flavor operations; don't rely on URL-level routing alone.
- **Explicit CORS**: `/sparql` allows any origin (read public); `/api/shards` restricts to known origins + requires bearer.

**Warning signs:** Shards appearing without governance-log entries; TBox graph changing unexpectedly; `sparql_update_attempts_total > 0`.

**Detection signals:** Any `UPDATE` keyword pre-parser match on the read endpoint → alert + 400.

**Sources:** [IBM LQE SPARQL Exposure](https://www.ibm.com/support/pages/node/7258083) HIGH · FEATURES.md G anti-feature (SPARQL UPDATE on public endpoint) HIGH · ARCHITECTURE.md Anti-Pattern + Table 9 HIGH

---

### Pitfall Q3: SPARQL injection via shard-content concatenation in dynamic queries

**Severity:** HIGH
**Phase:** Phase 15 (UI queries) + Phase 16 (endpoint)

**What goes wrong:** FEATURES.md differentiator "historical query chip — as-of picker" dynamically builds SPARQL: `f"SELECT ... WHERE {{ ... FILTER(?valid_time <= '{user_date}') }}"`. Attacker supplies `user_date = "2023-01-01' . } SELECT ?s WHERE { ?s ?p ?o } #"` → SPARQL injection. Same pattern in polysemy fork UI, supersession timeline, any user-parameterized SPARQL.

**Why it happens:** SPARQL injection is less famous than SQL injection; developers don't reflexively parameterize.

**How to avoid:**
- **Parameterized queries via `initBindings`** — pyoxigraph supports bound variables; never string-concatenate user input into SPARQL.
- **Exception**: when users author ad-hoc queries in the SPARQL explorer, the whole query IS user input — parse it, reject UPDATE keywords, run with strict timeout + size cap; no sanitization possible.
- **SPARQL escape helper** for cases where parameterization can't be used: escape quotes, braces, angle brackets per SPARQL 1.1 grammar.
- **Type-check user input** before injection: `as_of` must parse as ISO-8601 date; `shard_iri` must match our IRI regex; anything else rejected at API boundary.
- **`ruff` rule** forbidding f-string / concat into `.query()` argument — flag every such call for review.

**Warning signs:**
- Queries with unexpected structure appearing in logs
- SPARQL errors with suspicious tokens (`"; DROP`, `'; DELETE`)
- Users reporting "my innocent input returned everything"

**Detection signals:**
- Static analysis: grep for `.query(f"...` patterns in our codebase; enforce review
- Structured query logging with original template + bound variables separately; template should be a closed set (from query registry)

**Sources:** [MORElab SPARQL/RDQL/SPARUL Injection](https://www.morelab.deusto.es/code_injection/) HIGH · [SPARQL Injection article](https://sparql.dev/article/10_SPARQL_Query_Language_Security_and_Privacy_Considerations.html) HIGH

---

### Pitfall Q4: Named-graph unaware queries return TBox + governance mixed with ABox

**Severity:** HIGH
**Phase:** Phase 13 (storage) + Phase 16

**What goes wrong:** Store has named graphs: `corpus:advocacy/abox`, `tbox`, `governance:advocacy`, etc. User writes `SELECT ?s ?p ?o WHERE { ?s ?p ?o }` in SPARQL explorer — returns **everything across all graphs**. Governance events show up mixed with shards. TBox vocabulary triples appear as if they were shards. Dashboards and counts are wrong. Users accustomed to Wikidata single-graph model produce junk queries by default.

**Why it happens:** SPARQL's default-graph semantics silently unions all graphs unless `FROM` / `GRAPH` is specified. No warning; no opinionated default from pyoxigraph.

**How to avoid:**
- **Pre-ship query templates** (FEATURES.md E differentiator) that ALWAYS include `FROM NAMED <corpus:X/abox>` + `GRAPH ?g { ... }` — users copy-paste correct patterns.
- **Default graph configured to empty or just TBox** — anything else must be named. pyoxigraph supports this via store configuration.
- **Linter in SPARQL explorer UI**: if query has no `GRAPH` or `FROM`, show warning "you are querying the default graph; you likely want `FROM NAMED <corpus:advocacy/abox>`".
- **Schema-aware autocomplete** (FEATURES.md E table stakes via sib-swiss/sparql-editor) surfaces the named-graph selector.
- **Docs page**: `docs/sparql-cookbook.md` leads with named-graph examples; never shows default-graph examples without context.
- **UI segmentation**: SPARQL explorer has a "scope" dropdown (ABox / TBox / Governance / Everything) that injects the right FROM clause automatically.

**Warning signs:**
- User reports of "count of shards shown on dashboard doesn't match my SPARQL query count"
- Governance events showing up in RAG chunks (a downstream consumer fed a naive query's output into their RAG index)
- TBox vocabulary IRIs appearing in "list of shards"

**Detection signals:**
- Metric: ratio `sparql_query_with_named_graph_total / sparql_query_total` — should be > 0.95; < 0.8 means users are querying wrong
- User-reported bug count mentioning "mixing" or "wrong graph"

**Sources:** ARCHITECTURE.md Pattern 3 "Named-Graph-per-Corpus" con HIGH · [Oxigraph named-graph behavior](https://pyoxigraph.readthedocs.io/) HIGH

---

### Pitfall Q5: `initBindings` semantics differ between rdflib and pyoxigraph

**Severity:** MEDIUM
**Phase:** Phase 13

**What goes wrong:** Team writes query with `initBindings={"shard": URIRef("...")}` expecting pre-query substitution (rdflib behavior). pyoxigraph joins `initBindings` *after* query evaluation (per oxrdflib docs). For queries with FILTERs or GROUP BY, results differ: rdflib prunes early; pyoxigraph returns all rows then joins. Performance regression + occasional semantic drift.

**Why it happens:** Documented behavior gap between rdflib and pyoxigraph; team assumes API equivalence.

**How to avoid:**
- **Don't use `initBindings` across the bridge** — substitute parameters into the query string (via parameterized-query helper with proper SPARQL escaping per Q3 prevention) before handing to pyoxigraph.
- **Test every bridged query** with a substitution + without to verify identical results on same fixture.
- **Migration regression suite**: any query that was using rdflib `initBindings` gets a dedicated test when moved to pyoxigraph path.

**Warning signs:** Queries returning "right data but slowly"; queries returning different counts on rdflib vs pyoxigraph for same inputs.

**Detection signals:** Integration test `tests/storage/test_rdflib_pyoxigraph_parity.py` compares result sets for fixture queries.

**Sources:** [oxrdflib docs — initBindings behavior](https://github.com/oxigraph/oxrdflib) HIGH

---

## Critical Pitfalls — Dimension: VALIDATION & PIPELINE

### Pitfall V1: SHACL validation on rdflib bridge at 1M triples blows P95 SLO

**Severity:** HIGH
**Phase:** Phase 0 (perf gate) + Phase 11 (SHACL)

**What goes wrong:** pyshacl runs on `rdflib.Graph` input. rdflib is ~5K triples/sec (per STACK.md). At 1M triples, loading the graph into rdflib for validation takes ~3 min; running SHACL-SPARQL constraints adds more. Per-write validation becomes O(entire-graph). P95 < 500ms SLO violated; writes back up; Arq queue grows.

**Why it happens:** SHACL validates against a "data graph"; naive impl uses the full store as data graph. Every write re-validates everything.

**How to avoid:**
- **Targeted validation**: only validate the *new* shard's triples + any triples it directly references (the "focus node" closure). pyshacl supports target-node restriction.
- **Incremental SHACL per 2025 research** (arxiv 2508.00137 — SHACL Validation Under Graph Updates): validate only the changed subgraph; maintain a cache of what's already validated.
- **Separate data graph for validation** — extract only the new shard's neighborhood (shard + referenced IRIs + their types) into a small rdflib.Graph; validate that; discard.
- **Hand-written shapes prefer SHACL Core over SHACL-SPARQL** where possible — Core is O(focus node) whereas SPARQL shapes can be O(data graph).
- **Phase 0 bench**: target 50ms median SHACL validation per shard at 1M-triple store; fail-gate else.
- **Async bulk validation** on mass ingest — validate in batches of 1000, not per-shard; results posted back as governance events.

**Warning signs:**
- `shacl_validation_duration_seconds{subtype=...}` p95 > 500ms
- Arq queue depth growing linearly with time (writes stuck waiting on validation)
- "Validation timeout" structlog warnings

**Detection signals:**
- Phase 0 benchmark scores
- Prometheus: `shacl_validation_duration_seconds` histogram
- Dashboard panel: validation-time-per-shard vs shard-count-in-corpus

**Sources:** [SHACL Validation Under Graph Updates (arxiv 2508.00137)](https://arxiv.org/abs/2508.00137) HIGH · [Efficient SHACL with Reasoning (VLDB 2024)](https://dl.acm.org/doi/10.14778/3681954.3682023) HIGH · [Re-SHACL approach](https://www.frontiersin.org/journals/bioinformatics/articles/10.3389/fbinf.2026.1756507/full) MEDIUM · STACK.md rdflib perf note HIGH

---

### Pitfall V2: Pydantic-to-SHACL generator produces shapes that don't match hand-written shapes' IRI scheme

**Severity:** MEDIUM
**Phase:** Phase 11

**What goes wrong:** RISK-2 in STACK.md: team writes ~150 LOC Pydantic→SHACL generator. Generator emits `sh:NodeShape` with IRIs like `<fi:ShardShape>`; hand-written shapes use `<fi:ShapeShard>` (English-wording drift). Or generator namespaces shapes differently. Shapes split into two namespaces; pyshacl can't correlate them; hand-written shapes' `sh:extends` broken. Validation silently incomplete.

**Why it happens:** Generator and hand-written shapes have different authors/times; convention drift.

**How to avoid:**
- **Single naming convention** documented in `docs/shapes-style-guide.md`: `{ClassName}Shape` (e.g., `ShardShape`, `AttestedSignatureShape`). Generator and hand-written shapes both obey.
- **Shape-level integration test**: load all shapes (generated + hand-written), assert shape-graph is connected (no dangling `sh:node` refs).
- **CI diff check**: generator is build-time (per ARCHITECTURE.md Open Q6); output `envelope.shacl.ttl` committed; CI re-runs generator and fails on diff.
- **Shape inheritance test**: hand-written shapes that `sh:extends ShardShape` must be satisfied by a minimal Shard fixture; broken inheritance fails this test.

**Warning signs:** SHACL validation passes for hand-written shape but not envelope shape (or vice versa) on same shard; unexpected `sh:property` violations.

**Detection signals:** Shape-graph connectedness test in CI.

**Sources:** STACK.md RISK-2 HIGH · ARCHITECTURE.md Open Q6 MEDIUM

---

### Pitfall V3: owlready2 HermiT JVM OOM in worker container on 50K+ axiom cluster

**Severity:** MEDIUM
**Phase:** Phase 0 + Phase 9 (P1 cluster validator)

**What goes wrong:** owlready2 shells out to HermiT Java process. HermiT allocates heap at startup (default 256 MB); scales to cluster-axiom-count. On a 50K+ axiom cluster (whole-corpus validation), HermiT OOMs; subprocess dies; owlready2 raises cryptic error. Arq worker fails; cluster validation silently broken.

**Why it happens:** JVM default heap is small; HermiT doesn't gracefully degrade.

**How to avoid:**
- **Set `JAVA_OPTS=-Xmx2g`** (or corpus-configurable) in worker Docker stage.
- **Cluster-size limits**: never run HermiT on > 10K shards at once. Partition clusters (per source doc, per Tractarian subtree) — ARCHITECTURE.md §8.1 already calls this out but doesn't set hard cap.
- **Rust `reasonable` fallback** (STACK.md RISK-1 mitigation option 2): if HermiT OOMs, fall back to OWL 2 RL reasoning on the whole cluster; flag results with lower confidence.
- **Phase 0 benchmark** specifically runs cluster validator on synthetic 10K and 50K axiom clusters; records OOM threshold; corpus config sets `cluster_validator_max_shards` per that finding.
- **Monitor JVM heap**: surface via OTel custom metric; alert on heap > 80%.

**Warning signs:** `cluster_validator_errors_total{reason="jvm_oom"} > 0`; corpus reports with "cluster validation skipped" noted.

**Detection signals:** JVM heap metric; subprocess exit-code monitoring.

**Sources:** STACK.md RISK-1 HIGH · [owlready2 HermiT Java docs](https://owlready2.readthedocs.io/en/latest/reasoning.html) HIGH · ARCHITECTURE.md §8.1 scaling note HIGH

---

### Pitfall V4: `instructor` retries stacked on top of tenacity retries produce exponential blow-up

**Severity:** MEDIUM
**Phase:** Phase 10

**What goes wrong:** `instructor` has built-in `max_retries=3` for validation failures. Team adds `@tenacity.retry(stop=stop_after_attempt(5))` around every instructor call for network failures. On a bad LLM day (rate limits, intermittent failures), effective retries = 3 × 5 = 15; OTel spans explode; costs balloon; user sees 10-minute apparent hang.

**Why it happens:** Each retry layer is individually reasonable; composition isn't considered. ARCHITECTURE.md Anti-Pattern 7 flags this.

**How to avoid:**
- **Single retry layer**: `instructor` handles validation retries (its domain); tenacity wraps only the top-level extraction task (network failures, rate limits).
- **Tenacity stop condition** uses combined time budget (`stop_after_delay(60)`), not attempt count, to cap total wait.
- **OTel instrumentation**: record both layers as span attributes so observability surfaces the retry composition; alert on `retry_count > 5`.
- **Cost governor**: on aggregate LLM spend > budget per corpus, pause extraction; prevents runaway retries amplifying cost.

**Warning signs:** Long span durations (> 30s) for single shard extraction; token budget exhausting on fewer shards than expected.

**Detection signals:** OTel histogram `llm_call_total_duration_seconds` p99 > 60s → alert; `llm_retry_count` attribute distribution.

**Sources:** ARCHITECTURE.md Anti-Pattern 7 HIGH · [Uptrace LLM Observability 2026](https://uptrace.dev/blog/opentelemetry-ai-systems) MEDIUM

---

### Pitfall V5: Polysemy detector false positives on terms-of-art that SHOULD be polysemous

**Severity:** HIGH
**Phase:** Phase 1 (polysemy spike) + Phase 9 (P6 detector)

**What goes wrong:** Detector flags every cross-framework occurrence of "consideration", "notice", "reasonable", "material", "person", "holding" as candidate distinguo forks. Most are NOT polysemous — they're deliberately context-dependent terms-of-art that gain meaning from framework scope (§P2). Reviewers swamped with false forks; real polysemy signals lost; distinguo workflow abandoned by reviewers; §16 Risk 2 class-explosion manifests as flag-explosion.

**Why it happens:** Polysemy detection (P6) uses cluster-validator (§P1) output flagging "framework-conflicting axioms." But a term having *different axioms in different frameworks* is the normal state for legal terms-of-art; that's why the framework field exists. Detection without a threshold calibrated to legal-language reality triggers on everything.

**How to avoid:**
- **Phase 1 spike** is canonically on "consideration" — the motivating example from PRD §2 failure 1. Calibrate threshold on this case; measure false-positive rate on hand-labeled gold set of 50 legal terms-of-art.
- **`distinguo_threshold = 0.6` default** (per PRD §16 Risk 2 mitigation) — but also require:
  - Framework-conflicting *axioms*, not just framework-conflicting *contexts* (same axiom in two frameworks is fine).
  - At least N=3 shards per framework before a fork is proposed (single-shard clusters are noise).
  - Prior probability check: if the term is in a "known terms-of-art" whitelist (consideration, notice, reasonable, person, holding, material, negligence, good faith, ...), require *higher* evidence threshold (0.8+) before proposing fork.
- **Human review gate** (PRD §16 R2 mitigation): detector proposes, reviewer disposes; never auto-apply. FEATURES.md B anti-feature explicit on this.
- **Dogfooding metric**: fork-acceptance-rate by reviewers; <20% acceptance means detector is over-proposing — raise threshold.
- **Prototype cluster visualization** (FEATURES.md B "What would this affect?" preview): reviewer sees cluster + axiom conflicts before deciding; informed rejection is better than fatigue-driven rejection.

**Warning signs:**
- Reviewer fork-queue growing faster than resolutions
- Reviewer fatigue surveys
- Fork-acceptance-rate < 30% (mostly rejections)
- "Consideration" fork proposed multiple times with near-identical evidence

**Detection signals:**
- Metric: `polysemy_fork_proposals_total{corpus=...,accepted|rejected}` — acceptance rate dashboard
- Queue depth: `reviewer_fork_queue_depth{reviewer_did=...}`
- Acceptance-rate by reviewer cohort; low-acceptance DIDs likely overwhelmed

**Sources:** PRD §16 Risk 2 HIGH · PRD §2 Failure 1 (consideration example) HIGH · FEATURES.md B anti-features HIGH · [Polysemy and the Law (Hemel, Vanderbilt Law Review)](https://scholarship.law.vanderbilt.edu/context/vlr/article/4881/viewcontent/Polysemy_and_the_Law.pdf) HIGH · [Polysemy in Legal English](https://www.ccjk.com/polysemy-in-legal-english/) MEDIUM

---

### Pitfall V6: Framework detector misclassifies source on ambiguous sources (multi-jurisdiction treatises)

**Severity:** MEDIUM
**Phase:** Phase 9 (P2)

**What goes wrong:** FRE (Federal Rules of Evidence) has clean framework = `us.federal.fre`. Restatement of Contracts is ALI-authored, intended as model law across state jurisdictions — does it belong to framework `us.ali.restatement_2d.contracts`, `us.model.contracts`, or split across 50 state frameworks? An advocacy treatise cites both federal and state law in the same chapter. Framework detector assigns one framework per shard; some shards have multiple legitimate frameworks.

**Why it happens:** §P2 assumes single framework per shard; real legal sources cross jurisdictions.

**How to avoid:**
- **Multi-framework shards**: extend `framework_id: str` to `framework_ids: list[str]` with a primary framework designator.
- **Source-metadata-first**: corpus config declares source's primary framework; fallback to LLM-inferred only if ambiguous.
- **Per-shard override**: reviewer can add frameworks via `fi:alsoAppliesTo` predicate.
- **Document per-corpus**: acceptable framework scopes (FRE corpus is single-framework; advocacy treatise is multi-framework).
- **Test cases**: Restatement fixture, FRE fixture, advocacy treatise fixture — each tests framework assignment semantics.

**Warning signs:** Reviewer-surface-side framework corrections are high; shards flagged as "framework mismatch" on manual audit.

**Detection signals:** `framework_correction_edits_total` — non-zero is normal; spike means detector is drifting.

**Sources:** PRD §P2 HIGH (acknowledges LLM fallback) · PRD §16 Risk 4 BFO-ambiguity analogy MEDIUM

---

### Pitfall V7: BFO classifier mis-categorizes abstract legal concepts (rights as continuant vs occurrent)

**Severity:** MEDIUM
**Phase:** Phase 9 (P7)

**What goes wrong:** PRD §16 Risk 4 flags this: "A right" — continuant-dependent. "A holding" — occurrent-event or continuant-dependent? BFO classifier LLM-path makes a call; downstream reasoning (which OWL 2 EL axioms apply) depends on it. Misclassification propagates through inference.

**Why it happens:** Legal abstractions don't map cleanly to BFO's physicalist top-level categories.

**How to avoid:**
- **Starter mapping table** (PRD §16 R4 mitigation): ship `bfo_mapping.ttl` with documented disclaimers on ambiguous cases.
- **speech_act field** (PRD §16 R4): "A holding-as-speech-act is an occurrent; a holding-as-binding-rule is a continuant-dependent" — `speech_act` helps BFO classifier choose.
- **Corpus-override**: per-corpus BFO mapping overrides for ontological disagreement.
- **`permissive` mode** (ARCHITECTURE.md §14): BFO classification is warn-only on ambiguous; reviewer can annotate.
- **Test cases**: hand-curated "ontologically hard" shards (right, duty, holding, doctrine) with accepted classifications; regression test.

**Warning signs:** Downstream OWL reasoning produces nonsensical inferences (rights entailed as physical processes).

**Detection signals:** HermiT inference-diff regression between BFO-classified and BFO-bypass runs.

**Sources:** PRD §16 R4 HIGH · ARCHITECTURE.md §14.1 + §P7 HIGH

---

## Critical Pitfalls — Dimension: INFRASTRUCTURE & OPS

### Pitfall I1: Arq migration leaves v1 disk-based jobs orphaned — corpora stuck in `processing` forever

**Severity:** MEDIUM
**Phase:** Phase 10 (pipeline/queue migration)

**What goes wrong:** ARCHITECTURE.md Open Q4 settled on side-by-side `FOLIO_JOB_BACKEND=arq|disk` flag. Cutover at Phase 12. During the transition window, some jobs land in disk-based `output/.jobs/` (v1), others in Redis (v2). Web UI shows status by reading disk files; Arq workers don't update disk files. Corpora entered before cutover stuck at "processing" because v1 job file was never completed; users re-submit; duplicate extraction. Or: after cutover, v1 disk files remain; `.dockerignore` fix from UAT I-5 doesn't cover them; status still reads `processing`.

**Why it happens:** Two job systems, single status surface; transition window without reconciliation.

**How to avoid:**
- **Single status-surface adapter** that unifies disk-based and Arq-based job state into one view.
- **Migration job** at cutover: scan `output/.jobs/` for in-progress jobs; either mark them failed (user re-submits) or replay them through Arq.
- **Post-cutover cleanup job** that removes `output/.jobs/` entirely; prevents resurrection.
- **Feature-flag test matrix**: Phase 10 CI runs both flag values; Phase 12 CI asserts `disk` path deleted.
- **Deploy-time migration script**: before Phase 12 deploy, reconcile in-flight jobs; before Arq worker starts, replay any orphaned disk state.
- **Integration test**: simulate a corpus starting extraction on v1, interrupted by cutover, assert it finishes under Arq without duplicate work.

**Warning signs:**
- Corpora stuck at "processing" > 1 hour
- Duplicate shard_iri insertion attempts
- `output/.jobs/` files present in post-cutover deploys

**Detection signals:**
- Metric: `job_backend_split{state=processing,backend=disk|arq}` — disk count should be 0 after cutover
- Integration test runs nightly; flags any `output/.jobs/` files or orphan Redis jobs
- UAT regression tests from v1.1 I-5 adapted to v2

**Sources:** ARCHITECTURE.md Open Q4 HIGH · [Arq docs on idempotency + at-least-once](https://arq-docs.helpmanual.io/) HIGH · v1.1 UAT I-5 retrospective (same class of issue) HIGH

---

### Pitfall I2: Redis as single point of failure (queue + rate-limit + idempotency + OAuth state) has no fallback

**Severity:** MEDIUM
**Phase:** Phase 10 + Phase 19

**What goes wrong:** Brief: "Redis 7.4 — Arq backend + rate-limiter + idempotency keys + OAuth state." Redis crash → all four subsystems fail simultaneously: extraction stops, rate limits stop (either fail-open or fail-closed, both bad), writes lose idempotency guarantees, users can't complete OAuth flow. Blast radius far exceeds single component.

**Why it happens:** "Redis is reliable" is the assumption; Railway Redis plugin outages have happened.

**How to avoid:**
- **Graceful degradation**: FastAPI middleware detects Redis unavailable; falls back to in-process rate limiting (per-pod counters, less strict) and rejects writes with 503 (preserve idempotency at the cost of availability).
- **OAuth state fallback**: signed JWT in session cookie as alternative to Redis state (authlib supports).
- **Idempotency key fallback**: if Redis unavailable, require client-side UUID on write and deduplicate on SQLite primary key (slower but safe).
- **Redis persistence**: AOF + RDB; replica for failover in production.
- **Chaos test in Phase 19**: simulate Redis down; assert graceful degradation per mode above.
- **Alert on Redis lag/outage**: short TTL Prometheus metric `redis_available{status="..."}` with PagerDuty.

**Warning signs:** Correlated failures across queue + auth + rate-limit; users reporting "everything broken."

**Detection signals:** Redis RTT metric; error-rate correlation across dependent services.

**Sources:** STACK.md (Redis as shared backend) HIGH · [Arq — job distribution and network latency](https://medium.com/@saber.solooki/solving-job-distribution-problems-in-arq-with-redis-streams-59eb4e4d3ec5) MEDIUM

---

### Pitfall I3: SvelteKit adapter-static → adapter-node migration breaks prerender hints silently

**Severity:** MEDIUM
**Phase:** Phase 0 (spike) + Phase 14

**What goes wrong:** v1.1 used `@sveltejs/adapter-static`. Some routes had `export const ssr = false` (SPA fallback) or relied on `prerender = true`. After adapter-node swap, SSR is now live; prerender hints are ignored or produce empty shells. Routes that used window/document at module top-level throw "ReferenceError: window is not defined" during SSR. User-facing: Friday night deploy, landing page blank for half of users.

**Why it happens:** Migrating between adapters changes runtime semantics; code written assuming adapter-static's constraints breaks under adapter-node's.

**How to avoid:**
- **Audit every `+page.ts` / `+page.svelte` / `+layout.ts`** for `ssr`, `prerender`, `csr` exports — document what each does; update for adapter-node.
- **Guard browser-only code**: use `onMount` or `browser` flag from `$app/environment`; no top-level window/document access.
- **Visual regression tests**: Playwright hits every route post-migration; asserts non-empty content.
- **Feature flag**: `VITE_ADAPTER=node|static` during Phase 14 transition; roll forward when tests green on node for 72h.
- **Spike in Phase 0**: one `stream-test` route under adapter-node proves streaming works; doesn't need full route rewrite.

**Warning signs:** Blank pages; hydration mismatch warnings in console; `window is not defined` 500s.

**Detection signals:** Playwright smoke tests per route; `sveltekit_hydration_mismatches_total` metric; production error rate.

**Sources:** [SvelteKit adapter-static issue 14471](https://github.com/sveltejs/kit/issues/14471) HIGH · [SvelteKit Troubleshooting SSR/Hydration](https://www.mindfulchase.com/explore/troubleshooting-tips/front-end-frameworks/advanced-troubleshooting-in-sveltekit-fixing-ssr,-routing,-and-hydration-challenges.html) HIGH · STACK.md RISK-4 HIGH

---

### Pitfall I4: OpenTelemetry span attribute bloat on LLM calls (full prompt stored → trace backend chokes)

**Severity:** MEDIUM
**Phase:** Phase 12 (observability)

**What goes wrong:** Instinct is to store full prompt + full response on OTel spans for debugging. At 10 shards/sec × 2KB prompt + 4KB response × 24h = ~5 GB/day trace data just for prompts. Honeycomb/Tempo cost explodes; 2026 OTel gen-ai conventions explicitly say "don't do this" — store in events with drop-at-collector capability.

**Why it happens:** Debugging friction; team wants full context in traces.

**How to avoid:**
- **Follow OTel gen-ai semantic conventions** (stable early 2026): prompts/responses go in span *events*, not attributes; collector drops events based on policy.
- **Hash prompts in spans**, store full prompt in separate artifact bucket keyed by hash; retrieve on demand.
- **Sampling**: tail-based sampler per Uptrace 2026 guidance — keep 100% error traces, 10% success.
- **Token-count attributes only** (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) in spans — not content.
- **Phase 12 design review** includes OTel retention policy + collector config.

**Warning signs:** Trace backend quota exhaustion; collector memory pressure; trace ingest latency increasing.

**Detection signals:** Trace-backend billing metric; span size p99 > 10KB triggers alert.

**Sources:** [OTel GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) HIGH · [Uptrace — OpenTelemetry for AI Systems 2026](https://uptrace.dev/blog/opentelemetry-ai-systems) HIGH · [OneUptime — GenAI Semantic Conventions for LLM Monitoring](https://oneuptime.com/blog/post/2026-02-06-genai-semantic-conventions-llm-monitoring/view) MEDIUM

---

### Pitfall I5: Aggregate LLM cost across chained instructor calls invisible (per-call spans, no parent rollup)

**Severity:** MEDIUM
**Phase:** Phase 12

**What goes wrong:** Single extraction → 8 instructor calls (framework detect, BFO classify, polysemy check, subtype route, per-field extraction, ...). OTel shows 8 individual spans; cost dashboard shows per-call cost but not per-shard aggregate. Team discovers bill only at month-end; $30 per shard instead of $3.

**Why it happens:** Individual spans don't roll up into parent-operation cost summary without explicit instrumentation.

**How to avoid:**
- **Per-shard root span** that wraps all LLM calls for a single shard extraction; sum token counts into root span attribute `shard.llm.total_cost_usd`.
- **Cost governor** (Phase 10): hard cap per corpus per day; alert at 50%, pause at 100%.
- **Model pricing metadata** kept in config (not hardcoded); LLM provider pricing changes frequently.
- **Nightly cost report** per corpus per provider in structlog.
- **Budget check before extraction**: estimated cost × shard count vs remaining budget; refuse if over.

**Warning signs:** End-of-month invoice surprise; per-shard cost variance high.

**Detection signals:** Metric `shard_extraction_total_cost_usd` histogram by corpus; dashboard with projected-vs-actual cost.

**Sources:** [Uptrace LLM Cost Monitoring](https://uptrace.dev/blog/llm-cost-monitoring) HIGH · [Uptrace OpenTelemetry for AI 2026](https://uptrace.dev/blog/opentelemetry-ai-systems) HIGH

---

### Pitfall I6: Two-stage Docker split unused — worker and web containers diverge on Python dep versions

**Severity:** MEDIUM
**Phase:** Phase 0 + Phase 12

**What goes wrong:** Phase 0 stands up two-stage Dockerfile. Over time, worker gets new deps (e.g., new SHACL shape dependency) that web doesn't get. pyproject.toml is one; requirements split between stages is via `pip install --group`. Drift happens invisibly. Web container runs with old shape-validator; worker runs with new; shapes disagree; validation passes in worker, fails in web (or vice versa).

**Why it happens:** Python dependency management under Docker is underspecified; two stages duplicate install logic.

**How to avoid:**
- **Shared base layer** (ARCHITECTURE.md Open Q1): single `python:3.11-slim + pyproject.toml` base; web/worker add differential layers only (JVM for worker).
- **Lock file commitment**: `uv.lock` or `poetry.lock` checked in; both stages use same lock.
- **CI smoke test** on both containers post-build: import every top-level module from both; catch missing deps early.
- **Dep-audit test**: `scripts/verify_dep_parity.py` runs `pip freeze` on both containers and diffs against expected allowed differences (JVM-layer only).

**Warning signs:** Web reports a validation success that worker rejects; "works on my machine" for different deploys.

**Detection signals:** Post-build parity check in CI.

**Sources:** ARCHITECTURE.md Open Q1 HIGH · STACK.md Docker guidance HIGH

---

## Critical Pitfalls — Dimension: UX

### Pitfall U1: Signature verification badge shown as simple checkmark — users don't distinguish "verified against current key" vs "verified against historical key"

**Severity:** MEDIUM
**Phase:** Phase 15 (UI)

**What goes wrong:** Shard UI shows green checkmark if signature verifies, red if not. But "signature made with rotated-out key" is a third state: the signature was valid when made, but the signing key is no longer the current key for the DID. Users see the same green checkmark for both "freshly verified by current key" and "archivally valid" — can't distinguish trust levels.

**Why it happens:** Binary UX obscures the three-state reality of DID-signed artifacts with key rotation.

**How to avoid:**
- **Tri-state badge**: (a) green ✓ "verified, current signing key"; (b) blue shield "archivally valid, signing key rotated"; (c) red ✗ "verification failed".
- **Tooltip** explains each state with "what does this mean for trust?"
- **Governance log surfaces** key rotation events; users can trace why a signature is archival.
- **Document in docs**: "what the checkmark means" with examples.

**Warning signs:** User reports "this signature is valid but also invalid?" confusion; increased support burden on verification semantics.

**Detection signals:** User survey; support ticket themes.

**Sources:** PRD §6.5 + §10 + §12 HIGH (under-specifies verification-badge UX) · [JWKS caching best practices](https://skycloak.io/blog/understanding-jwks-json-web-key-sets-explained/) MEDIUM

---

### Pitfall U2: WCAG 2.1 AA blocking gate treated as pass-once (axe-core) — regressions slip in

**Severity:** MEDIUM
**Phase:** Phase 14 + Phase 15 + Phase 17

**What goes wrong:** Brief: "WCAG 2.1 AA as blocking gate (axe-core in CI)." Team runs axe-core once per component; passes; doesn't re-run on every CI. Later PR changes component; accessibility regresses; no test catches; v2.0 release fails WCAG.

**Why it happens:** axe-core in CI is easy to conflate with axe-core on every PR.

**How to avoid:**
- **Every PR that touches `viewer/` runs Playwright + @axe-core/playwright suite against all modified routes + full homepage**.
- **CI job named `a11y` as blocking status check** — cannot merge without green.
- **New component template**: includes axe test as part of scaffolding (don't make a11y opt-in).
- **Release gate in Phase 17/19**: full-site a11y audit as pre-release check with human review of non-trivial violations.

**Warning signs:** axe-core violations growing over time; keyboard nav broken on new components; screen reader users reporting.

**Detection signals:** `a11y_violations_total{severity=serious}` counter; CI report per PR.

**Sources:** Brief quality bar "WCAG 2.1 AA blocking" HIGH · STACK.md Dev Tools section (@axe-core/playwright) HIGH

---

### Pitfall U3: Contest wizard allows reviewer to bypass arbiter resolution by proposing distinguo fork unilaterally

**Severity:** MEDIUM
**Phase:** Phase 15

**What goes wrong:** §3.1.3 resolution paths: arbiter decides OR distinguo fork OR aporetic acceptance. Distinguo fork is a "resolution" path. A reviewer who doesn't agree with an arbiter's pending resolution proposes a distinguo fork instead; by PRD, any reviewer can propose distinguo (with cluster-validator evidence). Contest gets "resolved" by fork without arbiter agreement; arbiter's role undermined.

**Why it happens:** Three parallel resolution paths without clear precedence.

**How to avoid:**
- **Sequence resolution paths**: in contest state, distinguo-fork proposal from non-arbiter DID requires arbiter co-sign OR cluster-validator must show high-confidence polysemy signal.
- **UI flow**: contest wizard shows three paths; arbiter path is "primary" (highlighted); distinguo requires justification text.
- **Governance log semantics**: contest resolution via fork requires arbiter attestation in addition to proposing-reviewer's.
- **Document in GOVERNANCE.md**: who can do what in contested states.

**Warning signs:** Arbiter resolutions overridden by post-hoc distinguo forks; arbiter burnout.

**Detection signals:** Governance log analysis — fork-resolution events without arbiter signature.

**Sources:** PRD §3.1.3 HIGH (under-specifies precedence) · FEATURES.md H "three resolution paths" HIGH

---

### Pitfall U4: SPARQL explorer ships without pre-shipped templates → users don't know what to ask

**Severity:** MEDIUM
**Phase:** Phase 15

**What goes wrong:** YASGUI is installed; queries work; users stare at blank editor. No idea what predicates exist, how to query polysemy forks, how to do as-of queries. SPARQL endpoint is "published" but unusable. Feature is technically shipped, practically a graveyard.

**Why it happens:** SPARQL tool adoption fails on discoverability; FEATURES.md E differentiator calls this out.

**How to avoid:**
- **Ship PRD §20 templates + polysemy + supersession + as-of templates** (FEATURES.md E differentiator); one-click paste.
- **Schema-aware autocomplete** (YASGUI + endpoint-metadata): users see available predicates as they type.
- **"SPARQL by example" page**: annotated queries with expected output and narrative.
- **Link from shard pages**: every shard has "query shards like this" button that opens explorer with a pre-filled query.

**Warning signs:** Low SPARQL endpoint traffic; users reporting "can't figure out how to use this."

**Detection signals:** `sparql_query_total` low relative to shard-page-view count; template-use ratio (queries starting from template vs blank).

**Sources:** FEATURES.md E table stakes + differentiator HIGH · [sib-swiss/sparql-editor](https://github.com/sib-swiss/sparql-editor) HIGH

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip `canonicalize_source_span` in Phase 4 "we control ingestion" | Fewer LOC; IRI minting looks done | Silent IRI drift on re-extract; permalinks break; D2 manifests in production | **Never** — this is a P0 invariant |
| Hand-write envelope shapes, skip Pydantic-to-SHACL generator | Ship Phase 11 faster | Shape-model drifts from Pydantic; V2 silent failures | Acceptable for v2.0 GA; generator is v2.1 polish ONLY IF diff-check in CI asserts hand-written shapes still cover every Pydantic field |
| Single-stage Docker (skip worker split) | Simpler deploy | Web-tier cold start with JVM; I6 drift invisible | Never — RISK-1 mandates split |
| String-concatenate user input into SPARQL for as-of filter | Fast to implement | Q3 SPARQL injection; CVSS 9+ | Never |
| No rate limiting on /sparql "internal use only" | Simpler | Q1 DoS; accidental-DDoS from LLM agents consuming endpoint | Acceptable during internal alpha; BLOCKING for Phase 16 release |
| Skip OAuth `state` + PKCE because authlib "handles it" | Fewer lines | F3 replay attack surface if authlib misconfigured | Never — always verify enabled + tested |
| rdflib full-graph SHACL validation at small scale | "Works fine at 10K" | V1 blown SLO at 1M; reintroducing targeting later is a refactor | Acceptable to ship Phase 11 with full-graph if Phase 0 bench shows OK at projected scale; re-architect at V1 detection |
| Single Redis instance, no replica | Simpler infra | I2 correlated failure; 4 subsystems down together | Acceptable for dev + alpha; persistence + replica for release |
| Accept `.model_dump()` for signing "close enough" | Ship Phase 6 faster | F4 signatures never verify across hosts | Never |
| UI has a "delete" button for simplicity | Cleaner menu | F1 supersession/retraction collapse; governance log corruption | Never — three distinct buttons |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **pyoxigraph ↔ rdflib bridge** | Share Python objects directly (Store and Graph) | Serialize through Turtle-star text; no object sharing |
| **authlib OAuth → DID binding** | Use `email` claim as stable key | Use OAuth `sub` claim (immutable); check for subject change each login |
| **atproto did:plc resolution** | Treat `IdResolver.did.resolve()` result as current | For historical signatures, query operation log at `signed_at` timestamp |
| **instructor + OpenTelemetry** | Manual span wrap every call | Use `opentelemetry-instrumentation-httpx` (instructor uses httpx); auto-captures; gen_ai semantic conventions apply |
| **Arq worker startup + Redis down** | Worker crashes on boot, loop | Worker waits with backoff for Redis; pod liveness allows restart; readiness gate on Redis connectivity |
| **pyshacl ← rdflib.Graph from pyoxigraph** | Pass pyoxigraph Store or Dataset | pyshacl expects rdflib.Graph; build a focused subgraph for validation (not the whole store) |
| **SvelteKit SSR + fetch in +page.server.ts** | `fetch('/api/...')` assumes running-in-dev proxy | Use absolute URL in SSR context; Vite proxy only works in client-side fetch |
| **owlready2 + Docker** | `ontology.reason()` fails with "java not found" | Worker stage adds `openjdk-17-jre-headless`; `owlready2.JAVA_EXE = "/usr/bin/java"` config |
| **FOLIO version pinning per shard** | "Latest FOLIO" everywhere; shard cites version at export time | Pin FOLIO version in corpus config; shard records FOLIO version at extraction time; tag immutable |
| **Railway multi-service deploy** | Single Dockerfile → single service | Define separate Railway services (`web`, `worker`, `redis`); each points at target in Dockerfile |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| **Full-store SHACL validation on every write** | Write latency p99 > 5s; Arq queue backing up | Focus-node-targeted validation; new-shard-only subgraph | > 100K triples |
| **rdflib-on-SQLite as storage** | Insert throughput 5K triples/sec; SPARQL p99 > 2s | pyoxigraph RocksDB as canonical store (STACK locked) | > 50K triples |
| **HermiT on whole corpus** | JVM OOM; cluster validator runs > 10 min | Cluster-axis partitioning; 10K shard soft cap per cluster | > 50K axioms in single cluster |
| **No pre-shipped SPARQL templates** | Users write N+1 queries; endpoint gets hammered | Pre-ship templates; cache CONSTRUCT results where idempotent | > 100 active users |
| **Per-call tenacity retry on instructor** | LLM cost 15x expected; OTel traces confusing | Single retry layer; tenacity only for top-level; `instructor` handles validation retries | Any LLM-provider bad day |
| **Full prompt in OTel span attribute** | Trace backend cost explosion; collector OOM | Token counts + hash in span; content in events (droppable) | > 10 shards/sec sustained |
| **Governance log without chain hash** | Tamper detection impossible after-the-fact | Hash-chain every event; nightly verifier | Any multi-admin corpus |
| **Single-graph SPARQL queries in explorer** | TBox triples in ABox results; wrong counts | Named-graph-aware templates; UI scope selector | Any multi-corpus deployment |
| **Synchronous DID document resolution on every request** | Request latency dominated by DID fetch | Cache did documents with appropriate TTL; historical-snapshot cache for rotated keys | Any user-facing flow |
| **No `shards_written_total` rate limit** | Bulk extraction starves web tier of DB locks | Arq concurrency config per corpus; SQLite WAL mode | > 10K shards/min |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Allow SPARQL `SERVICE` on public endpoint | SSRF to internal + cloud metadata; AWS credential theft | Parser-level reject `SERVICE` and external `FROM` |
| Allow SPARQL `UPDATE` on public endpoint | Anonymous writes; data destruction | Separate URL for query (read-only) vs write API (DID-signed); parser rejects UPDATE keywords on read URL |
| Server-held signing keys "for convenience" | Server compromise = total DID impersonation; §16 R5 audit fails | Client-side signing always; browser WebCrypto or CLI local key |
| DID binding proof without nonce + timestamp | Replay attack escalates OAuth compromise to DID impersonation (F3) | Signed proof must include server nonce (5 min TTL) + timestamp + binding URL |
| JCS canonicalization via `model_dump()` defaults | Signatures never verify across hosts; false negatives in verification (F4) | Explicit `shard_canonical_json()` helper; NFC + fixed datetime fmt + rounded floats |
| Trust current DID key for historical signature | Key rotation invalidates valid archival signatures (F2) | Store signing-key reference at signing time; resolve historical DID doc for verification |
| OAuth `email` as stable identity | Username/email takeover cascades to DID binding (F7) | Use `sub` claim; monitor for subject change |
| Redis persistence disabled | Queue loss on restart; idempotency keys lost; double-extraction | AOF + RDB; replica for production |
| No rate limiting on LLM-calling endpoints | Cost attack via API; budget blown | Per-DID + per-corpus cost governor; hard daily cap |
| Ed25519 "high-s" signature acceptance | Signature malleability allows forgery-like attack | Reject non-canonical signature encoding per [did:plc spec](https://web.plc.directory/spec/v0.1/did-plc) |
| SHACL shapes as only enforcement layer for append-only | Direct pyoxigraph API bypasses SHACL (F5) | Storage-level wrapping + chain hash + SQLite trigger defense-in-depth |
| Logging full user inputs including DID-signed payloads | Private key leakage if key material in logs; privacy issue | Structured logs redact signing-key fields; never log raw signatures (store hash ref only) |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Unified "disagree" button conflating retract / supersede / contest | F1 — false retractions read as censorship; silent cascades | Three distinct actions + disambiguation prompt + preview of blast radius |
| Binary signature badge (✓ / ✗) | U1 — users can't tell archivally-valid from currently-valid | Tri-state badge: current / archival / failed, with tooltip |
| Blank SPARQL explorer | U4 — feature ships but unusable | Pre-shipped templates + schema-aware autocomplete + "query this shard" deep links |
| Polysemy fork proposal without cluster-validator evidence visible | Reviewer fatigue; false-fork-rate explodes (V5) | Evidence panel mandatory; shows conflicting axioms with citations |
| Supersession timeline without "why superseded" rationale | Legal users can't cite; amendment history opaque | Rationale field required; amendment-effective-date picker explicit (no `now()` default) |
| No "undo" on distinguo fork within 15min | Fork mistakes permanent; reviewer hesitation rises | Time-bounded rollback per FEATURES.md B differentiator |
| Dependent cascade not previewed on retraction | Retractor unknowingly invalidates hundreds of downstream shards | Preview panel with dependent count + aporetic-transition count + affected shards |
| "Vote up / down" on shards | Creates false consensus; violates §21.10 downstream-weighs | Show signature counts (raw data); no aggregate score |
| Key management buried under "settings" | Reviewer never generates keys; federated contribution zero | First-login onboarding walks through key generation; CLI has `folio-insights did generate --onboarding` |
| No framework badge on shards | Cross-jurisdiction confusion; reviewer misreads Restatement vs UCC | Persistent framework chip on every shard view |

---

## "Looks Done But Isn't" Checklist

Verification checklist per v2.0 release candidate. Things that appear shipped but commonly miss critical pieces:

- [ ] **DID signing** — verify signature round-trips through serialization AND verifies with current key AND with historical key (rotated test)
- [ ] **Shard IRI minting** — re-extract bundled v1 corpus TWICE; 100% IRI overlap (determinism)
- [ ] **SPARQL endpoint security** — run automated SSRF probe (try `SERVICE <http://169.254.169.254/latest/meta-data/>`); must 400
- [ ] **SPARQL endpoint rate limits** — hammer 200 queries/min from one IP; rate limit must trigger; governance log shows no DoS shards
- [ ] **Content versioning** — edit a shard, assert audit log entry written AND `provenance_hash` unchanged AND `canonical_content_hash` changed AND old signatures still verify archivally
- [ ] **Retraction cascade** — retract a shard with 10 dependents; preview shows 10 affected; after commit, 10 marked aporetic OR re-derived
- [ ] **Supersession** — supersede FRE-702-2022 with FRE-702-2023; both queryable; `--as-of 2022-12-31` returns old; `--as-of 2024-01-01` returns new; no cascade fires
- [ ] **Polysemy detector** — inject "consideration" cross-framework cluster; detector proposes ONE fork; reviewer accepts; downstream shards re-scoped
- [ ] **Cluster validator** — runs under 30s on 10K-shard cluster; JVM heap stays under 2GB
- [ ] **SHACL validation** — targeted validation on new shard completes in <100ms at 1M-triple store
- [ ] **Arq + v1 job reconciliation** — simulate interrupted cutover; no jobs stuck, no duplicate extraction
- [ ] **OAuth + DID binding** — test binding-proof replay 6 min later; must 401 with "nonce already consumed"
- [ ] **WCAG 2.1 AA** — axe-core green on every route; keyboard-only smoke test; screen reader manual pass
- [ ] **RDF-star round-trip** — write, read, compare byte-exact; assert `<<?s ?p ?o>>` never in subject position (RDF 1.2 compat)
- [ ] **Two-stage Docker parity** — both web and worker containers pass smoke import test; shared deps version-pinned
- [ ] **Named-graph hygiene** — default-graph queries return governance-free results OR emit warning
- [ ] **Signature badge tri-state** — visual test covers current/archival/failed with clear differentiation
- [ ] **Governance log chain** — chain-hash verifier passes on mainline; tamper test detects
- [ ] **OTel span size** — LLM span attributes under 10KB; prompts in events only
- [ ] **Append-only enforcement** — try to DELETE on governance graph via every exposed API; all paths 403/400
- [ ] **Bundled extraction dataset freshness** — UAT I-5 equivalent: `output/.jobs/` not bundled; processing_status correct on fresh deploy
- [ ] **Framework detection** — Restatement vs FRE vs advocacy-treatise each produce expected framework; per-shard override works

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| D1 RDF-star syntax regression discovered post-launch | HIGH | Freeze releases; rewrite templates to RDF 1.2; migrate stored data; publish RDF-1.2 query cookbook; hotfix release |
| D2 IRI non-determinism discovered post-launch | HIGH | Mint `owl:sameAs` links from old (wrong) IRI to new (canonical) IRI; freeze new extractions; fix canonicalizer; re-run extraction corpus-by-corpus; retire wrong IRIs only after 90d dereferenceability window |
| F1 false retractions in the wild | HIGH | Arbiter review every retraction from last 30 days; reverse those that were supersessions; update documentation; UX disambiguation prompt immediate |
| F4 signature non-determinism | HIGH | Mass re-sign campaign; reviewers sign over canonical content with fixed canonicalizer; until then, verification-soft-fail shows "signature needs re-signing" state |
| F2 DID key rotation breaking signatures | MEDIUM | Historical DID document archive retrofit from PLC operation log / snapshot services; re-verify all in-corpus signatures with archival-mode; update badge UX |
| V1 SHACL SLO blown in production | MEDIUM | Degrade to async validation (writes accept, validation posts results as governance events); add result cache; revisit Phase 11 targeted validation |
| V5 polysemy detector over-flagging | MEDIUM | Raise threshold; add terms-of-art whitelist; bulk-reject pending forks older than 14 days; reviewer notification |
| I1 Arq/v1 job state split | LOW-MEDIUM | Operator script reconciles; one-time repair job; document lesson |
| Q1 SSRF in wild | HIGH | Emergency endpoint shutdown; parser-side reject; security advisory; post-mortem public |
| Q2 public UPDATE exploited | CRITICAL | Emergency shutdown; full audit of writes in the window; rollback from git TTL dumps; reviewer re-attestation of affected shards |

---

## Pitfall-to-Phase Mapping

How roadmap phases prevent each pitfall:

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| D1 RDF-star → RDF 1.2 breaking change | Phase 0 (spike gate) | Phase 0 exit: `test_rdf12_triple_term_object.py` PASS; PRD §20 queries rewritten as regression tests |
| D2 IRI non-determinism | Phase 4 | Re-extraction determinism property test + corpus regression test |
| D3 Pydantic discriminated-union collapse | Phase 3 | Round-trip fixture per subtype; mypy strict |
| D4 IRI hash collision | Phase 4 | Collision detector + Prometheus counter + escalate-length path |
| D5 v1→v2 extraction drift | Phase 10 + 17 | Tiered regression harness; golden set coverage gate |
| F1 supersession/retraction collapse | Phase 9 (P3) + Phase 15 | UX disambiguation prompt; three CLI commands; UX testing; governance log review |
| F2 DID key rotation breakage | Phase 6 + Phase 19 | `test_signature_survives_key_rotation.py`; archival-cache; audit scenario |
| F3 OAuth-DID replay attack | Phase 6 + 14 + 19 | Nonce-enforced binding proof; PKCE+state tests; audit replay test |
| F4 JCS canonicalization non-determinism | Phase 6 | `shard_canonical_json()` helper + property test + cross-impl golden test |
| F5 governance log tamper | Phase 7 | Hash-chain + storage-level write guards + SQLite triggers + git backup |
| F6 corpus_admin lockout | Phase 7 | SHACL invariant >=2 admins; break-glass documented; forked-recovery path |
| F7 OAuth username takeover | Phase 14 | Bind by `sub`; subject-change detection metric |
| Q1 SPARQL SSRF | Phase 16 + 19 | Parser-level reject SERVICE + external FROM; egress firewall; audit SSRF probe |
| Q2 SPARQL UPDATE public | Phase 16 | Two URLs; read-only mode; parser rejects UPDATE keywords |
| Q3 SPARQL injection | Phase 15 + 16 | Parameterized-query-only; lint rule; type-check inputs |
| Q4 named-graph unaware queries | Phase 13 + 16 | Pre-shipped templates; scope dropdown; default-graph config |
| Q5 rdflib/pyoxigraph initBindings drift | Phase 13 | Parameterized substitution + parity test suite |
| V1 SHACL SLO blown at scale | Phase 0 + 11 | Phase 0 bench gate; targeted validation pattern; incremental SHACL |
| V2 Pydantic-SHACL naming drift | Phase 11 | Shape-graph connectedness test; CI diff of generator output |
| V3 owlready2 JVM OOM | Phase 0 + 9 | Phase 0 bench with 10K/50K; JVM heap config; cluster-size cap; reasonable fallback documented |
| V4 retry stacking | Phase 10 | Single-retry-layer discipline; tenacity only at top-level; OTel retry attribute |
| V5 polysemy false positives | Phase 1 + 9 | Phase 1 spike calibration; threshold + terms-of-art whitelist; acceptance-rate metric |
| V6 framework misclassification | Phase 9 | Multi-framework shards; corpus-config primary; reviewer override |
| V7 BFO mis-categorization | Phase 9 | starter table + speech_act + permissive mode + override |
| I1 Arq migration orphans | Phase 10 + 12 | Unified status adapter; migration job; post-cutover cleanup; integration test |
| I2 Redis single point of failure | Phase 10 + 19 | Graceful degradation; JWT OAuth fallback; chaos test in audit |
| I3 adapter-static → adapter-node | Phase 0 + 14 | Phase 0 spike prove streaming; Phase 14 route audit; Playwright smoke |
| I4 OTel span bloat | Phase 12 | gen-ai semantic conventions; prompts in events; sampling policy |
| I5 invisible LLM aggregate cost | Phase 12 | Per-shard root span rollup; cost governor; budget alerts |
| I6 two-stage Docker dep drift | Phase 0 + 12 | Shared base layer; uv.lock committed; parity verify in CI |
| U1 signature badge binary | Phase 15 | Tri-state design; tooltip; user test |
| U2 WCAG pass-once | Phase 14 + 15 + 17 | Per-PR axe-core; `a11y` blocking check; release audit |
| U3 contest/distinguo bypass | Phase 15 | Resolution-path precedence; arbiter co-sign requirement; governance analysis |
| U4 SPARQL explorer unusable | Phase 15 | Pre-shipped templates; schema-aware autocomplete; deep-link "query this shard" |

---

## Legal-Domain-Specific Pitfalls (Deep-Dive)

### LD1: FOLIO vocabulary churn — ontology version updates invalidate in-flight shards

**Severity:** MEDIUM
**Phase:** Phase 8 (vocab) + Phase 13 (storage)

**What goes wrong:** FOLIO (alea-institute/FOLIO) ships ~quarterly updates per [their 2025 announcements](https://openlegalstandard.org/). A concept IRI we reference (`folio:Consideration`) gets renamed, split, or merged in FOLIO v0.3. Existing shards reference the old IRI; OWL reasoning breaks; HTML export shows broken links.

**Why it happens:** Downstream ontology dependency; version drift; no pinning.

**How to avoid:**
- **Per-corpus FOLIO version pin** (brief: "FOLIO version tracking: pin per shard"). Shard records `fi:folioVersion` predicate; pinned version respected across corpus lifetime.
- **Migration tooling**: when FOLIO updates, provide `folio-insights migrate-vocab --from v0.2 --to v0.3 --corpus advocacy` that walks the upgrade; reviewer attestation required.
- **Test upgrade paths**: before adopting a new FOLIO version, run regression against benchmark corpora.
- **Don't update FOLIO on a whim**: FOLIO adoption is a corpus-admin governance event (per §3.1.1).

**Warning signs:** `owl:imports` resolution failures; broken `folio:X` IRI dereferences; HTML export 404s.

**Detection signals:** Dereference health check on sampled FOLIO IRIs; nightly integrity job.

**Sources:** [FOLIO GitHub release cadence](https://github.com/alea-institute/FOLIO) HIGH · Brief FOLIO-pin decision HIGH

---

### LD2: Jurisdiction-specific shards leak across jurisdiction boundaries during cross-corpus queries

**Severity:** MEDIUM
**Phase:** Phase 13 (storage) + Phase 16 (endpoint)

**What goes wrong:** A shard from `corpus:nys-evidence` (New York) is legitimately scoped to NY; cross-corpus query from `corpus:federal-evidence` inadvertently unions them via a SPARQL SERVICE or FROM NAMED; user reads NY-specific rule as federal. Legal malpractice risk if reliance-based.

**Why it happens:** Named graphs separate shards, but cross-corpus SPARQL doesn't re-apply framework-scoping; user may not notice a jurisdictional mix.

**How to avoid:**
- **Every shard has `framework_id`** (§P2); cross-corpus queries filter by framework explicitly.
- **SPARQL templates for cross-corpus search** filter by framework by default.
- **UI shows framework chip prominently**; cross-corpus result panel groups by framework.
- **Document prominently**: "shards are framework-scoped; check the framework badge before citing."

**Warning signs:** User reports "I thought this was federal but it's NY."

**Detection signals:** User support themes; cross-corpus-no-framework-filter query count metric.

**Sources:** PRD §P2 HIGH · FEATURES.md differentiator "cross-corpus query" MEDIUM

---

### LD3: Supersession timeline doesn't handle retroactive amendments

**Severity:** MEDIUM
**Phase:** Phase 15

**What goes wrong:** Amendment passed in 2026 says "effective January 1, 2024." Our supersession model uses `valid_time_end` of old shard = `valid_time_start` of new; UI assumes monotonic timeline. Retroactive effective-date violates that; amendment's "start" predates supersession event. UI shows confusing timeline.

**Why it happens:** Bitemporal modeling captures transaction time vs valid time; UI typically only shows valid time.

**How to avoid:**
- **Bitemporal display**: transaction-time toggle shows "when we learned" vs "when legally effective."
- **Retroactive amendment explicit**: UI flags amendments with effective-date earlier than their event date; tooltip explains.
- **As-of query respects valid time**, not transaction time (default); power users can query by transaction time for audit purposes.
- **Test case**: 2023 amendment with 2021 effective date; UI renders coherently.

**Warning signs:** Retroactive amendments cause reviewer confusion; user reports.

**Detection signals:** Ratio of `valid_time_start < supersedes_event_time` shards; should be small but non-zero.

**Sources:** FEATURES.md C differentiator "transaction-time vs valid-time toggle" HIGH

---

### LD4: Circuit-split handling — `ConflictingAuthoritiesShard` without reconciliation_strategy

**Severity:** MEDIUM
**Phase:** Phase 3 + Phase 15

**What goes wrong:** Circuit splits are the canonical `ConflictingAuthoritiesShard` case. Without an explicit `reconciliation_strategy` (sense_distinction, contextual_limitation, subsequent_overruling, jurisdictional_scoping, unreconciled), downstream consumers can't know how the conflict is handled — or is unresolvable. Shards sit in limbo; UI shows "conflict" badge but no path forward.

**Why it happens:** Reconciliation is reviewer work; default of `unreconciled` is technically valid but practically useless.

**How to avoid:**
- **`unreconciled` is time-bounded**: after 180 days `unreconciled`, shard flagged for arbiter review.
- **UI nudges reconciliation**: dashboard surfaces high-value unreconciled circuit splits.
- **Clear reconciliation_strategy definitions** in docs with legal examples.
- **jurisdictional_scoping** is the usual resolution for circuit splits; pre-select this option with justification prompt.

**Warning signs:** Growing pool of `unreconciled` shards; reviewers avoiding the UI.

**Detection signals:** `shards_by_reconciliation_strategy{strategy="unreconciled"}` trend.

**Sources:** PRD §6.2 ConflictingAuthoritiesShard HIGH · FEATURES.md H reconciliation strategy HIGH

---

### LD5: §8.P1 polysemy detector triggering on legal homonyms that are truly different concepts (not polysemy)

**Severity:** MEDIUM
**Phase:** Phase 1 + 9

**What goes wrong:** "Bar" — the bar association, the bar in a courtroom, bar (to prevent). "Interest" — ownership interest, financial interest, interest in a case. Detector flags as polysemy; actually homonyms (different concepts happening to share a word). Distinguo forks pollute concept space.

**Why it happens:** Polysemy vs homonymy is a linguistic subtlety; LLM-based detection conflates.

**How to avoid:**
- **Cluster-validator evidence required**: distinguo requires shared `fi:Concept` IRI with framework-conflicting axioms, not just shared token string.
- **LLM prompt includes polysemy-vs-homonymy distinction**: "Are these uses of 'X' the *same concept applied differently* (polysemy, fork appropriate) OR *different concepts with same spelling* (homonymy, not a fork)?"
- **Known-homonym whitelist**: legal-English homonyms (bar, interest, execute, party, serve) flagged with "check homonymy" prompt before fork proposal.
- **Reviewer training docs**: polysemy-vs-homonymy distinction taught with examples.

**Warning signs:** Forks proposed on known homonyms; reviewer rejection rate on these very high.

**Detection signals:** Fork proposals on whitelist tokens counted separately; rejection ratio by token class.

**Sources:** [Polysemy and the Law (Hemel)](https://scholarship.law.vanderbilt.edu/context/vlr/article/4881/viewcontent/Polysemy_and_the_Law.pdf) HIGH · [Polysemy in Legal English](https://www.ccjk.com/polysemy-in-legal-english/) MEDIUM

---

### LD6: Benchmark corpus choice bias — FRE + Restatement + advocacy all US-federal-centric

**Severity:** LOW
**Phase:** Phase 0 + 17

**What goes wrong:** Brief's benchmark corpora (advocacy + FRE + Restatement of Contracts) are all US-federal-authority-centric. v2.0 claims "jurisdiction-agnostic framework model" but benchmark doesn't test EU civil law, state-specific variations, UK common law, international treaties. The first non-US corpus uncovers bugs in framework detector, BFO classifier, polysemy detector calibrated to US sources.

**Why it happens:** Accessible English-language benchmarks tend to be US federal.

**How to avoid:**
- **Flag explicitly in release notes**: v2.0 benchmarks are US-federal-centric; non-US corpora are expected to reveal calibration gaps.
- **Post-GA plan**: add one civil-law corpus (e.g., a published English translation of a German commercial code commentary) as v2.1 benchmark.
- **Framework registry** is schema-agnostic; non-US frameworks are first-class once registered.
- **Document the bias**: community contributors from non-US jurisdictions are explicitly invited.

**Warning signs:** Post-release issues from non-US users reporting framework/BFO/polysemy issues their US-reviewer counterparts didn't see.

**Detection signals:** Issue tracker thematic analysis post-release.

**Sources:** Brief "benchmark corpora" HIGH · PROJECT.md "English corpus" carried from v1 HIGH

---

## Sources

### Primary (internal)

- [`PRD-v2.0-draft-2.md`](/home/damienriehl/Coding Projects/folio-insights/PRD-v2.0-draft-2.md) §3.1, §6, §7, §8, §9, §10, §11, §12, §13, §16 (Risks 1-5), §17 (Success Criteria), §21 (all 10 resolved decisions) — HIGH
- [`.planning/v2.0-MILESTONE-BRIEF.md`](/home/damienriehl/Coding Projects/folio-insights/.planning/v2.0-MILESTONE-BRIEF.md) — HIGH
- [`.planning/research/STACK.md`](/home/damienriehl/Coding Projects/folio-insights/.planning/research/STACK.md) RISK-1..4 — HIGH
- [`.planning/research/FEATURES.md`](/home/damienriehl/Coding Projects/folio-insights/.planning/research/FEATURES.md) anti-features + "no-precedent" zones — HIGH
- [`.planning/research/ARCHITECTURE.md`](/home/damienriehl/Coding Projects/folio-insights/.planning/research/ARCHITECTURE.md) §3.3 critical path + §9 anti-patterns + §11 open Qs — HIGH
- [`2026-04-19_Philosophy.md`](/home/damienriehl/Coding Projects/folio-insights/2026-04-19_Philosophy.md) Part IV "ten anti-patterns" + Part V holist critique — HIGH

### Triplestore & SPARQL

- [Oxigraph CHANGELOG — 0.5.0-beta.1 RDF-star → RDF 1.2 migration](https://github.com/oxigraph/oxigraph/blob/main/CHANGELOG.md) — HIGH (source of D1)
- [pyoxigraph docs 0.5.x](https://pyoxigraph.readthedocs.io/) — HIGH
- [oxrdflib — initBindings semantics](https://github.com/oxigraph/oxrdflib) — HIGH
- [StarBench: Benchmarking RDF-star Triplestores](https://ceur-ws.org/Vol-3565/QuWeDa2023-paper4.pdf) — MEDIUM (Oxigraph vs GraphDB perf context)
- [IBM Security Bulletin — CVE-2025-27550, CVE-2025-2134, CVE-2025-1823 SPARQL DoS](https://www.ibm.com/support/pages/node/7258083) — HIGH
- [TinySPARQL Security Considerations](https://tracker.api.gnome.org/security.html) — HIGH
- [SPARQL Security and Privacy Considerations](https://sparql.dev/article/10_SPARQL_Query_Language_Security_and_Privacy_Considerations.html) — HIGH
- [MORElab SPARQL/RDQL/SPARUL Injection](https://www.morelab.deusto.es/code_injection/) — HIGH
- [Amazon Neptune — queryTimeout SPARQL hints](https://docs.aws.amazon.com/neptune/latest/userguide/sparql-query-hints-queryTimeout.html) — MEDIUM
- [Qualys Serverless SSRF 2026](https://blog.qualys.com/product-tech/2026/01/15/serverless-security-risks-identity-ssrf-rce) — MEDIUM

### SHACL at scale

- [SHACL Validation Under Graph Updates (arxiv 2508.00137, ISWC 2025)](https://arxiv.org/abs/2508.00137) — HIGH
- [Efficient Validation of SHACL Shapes with Reasoning (VLDB 2024)](https://dl.acm.org/doi/10.14778/3681954.3682023) — HIGH
- [xpSHACL — Explainable SHACL Validation (VLDB 2025 workshop)](https://arxiv.org/html/2507.08432v1) — MEDIUM
- [SHACLens — visualization for violation exploration (Frontiers Bioinformatics 2026)](https://www.frontiersin.org/journals/bioinformatics/articles/10.3389/fbinf.2026.1756507/full) — MEDIUM

### Identity & signing

- [did:plc Specification v0.1](https://web.plc.directory/spec/v0.1/did-plc) — HIGH
- [AT Proto Identity Guide](https://atproto.com/guides/identity) — HIGH
- [did:webvh Implementer Guide — valid keys](https://didwebvh.info/latest/implementers-guide/did-valid-keys/) — HIGH
- [Risks of did:plc (Agent.io)](https://agent.io/posts/risks-of-did-plc/) — MEDIUM
- [Relaxing DID:PLC Verification Constraints (Bluesky discussion 2025)](https://github.com/bluesky-social/atproto/discussions/3928) — MEDIUM
- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) — HIGH
- [JCS reference implementation (cyberphone/json-canonicalization)](https://github.com/cyberphone/json-canonicalization) — HIGH
- [JCS draft 17 (updated)](https://datatracker.ietf.org/doc/draft-rundgren-json-canonicalization-scheme/17/) — HIGH
- [Determinism in CBOR/JCS](https://cborbook.com/part_2/determinism.html) — MEDIUM

### OAuth & token security

- [WorkOS — Token Replay Attacks 2025](https://workos.com/blog/token-replay-attacks) — HIGH
- [Obsidian Security — Token Replay Detection](https://www.obsidiansecurity.com/blog/token-replay-attacks-detection-prevention) — HIGH
- [OAuth 2.1 Security Pitfalls](https://identitymanagementinstitute.org/oauth-21-security-pitfalls/) — HIGH
- [Clutch Events — OAuth Token Replay in Distributed Environments](https://www.clutchevents.co/resources/oauth-token-replay-attacks-how-to-detect-and-defend-in-distributed-cloud-environments) — MEDIUM
- [PortSwigger — OAuth 2.0 Authentication Vulnerabilities](https://portswigger.net/web-security/oauth) — HIGH
- [JWKS Caching Explained (Skycloak)](https://skycloak.io/blog/understanding-jwks-json-web-key-sets-explained/) — MEDIUM

### Observability (LLM + OTel)

- [OpenTelemetry GenAI Semantic Conventions (stable 2026)](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) — HIGH
- [Uptrace — OpenTelemetry for AI Systems 2026](https://uptrace.dev/blog/opentelemetry-ai-systems) — HIGH
- [Uptrace — LLM Cost Monitoring](https://uptrace.dev/blog/llm-cost-monitoring) — HIGH
- [OneUptime — GenAI Semantic Conventions for LLM Monitoring](https://oneuptime.com/blog/post/2026-02-06-genai-semantic-conventions-llm-monitoring/view) — MEDIUM
- [Datadog — LLM Observability + OTel GenAI](https://www.datadoghq.com/blog/llm-otel-semantic-convention/) — MEDIUM

### SvelteKit SSR

- [SvelteKit adapter-static docs](https://svelte.dev/docs/kit/adapter-static) — HIGH
- [SvelteKit adapter-static ssr/prerender issue (14471)](https://github.com/sveltejs/kit/issues/14471) — HIGH
- [SvelteKit Troubleshooting Advanced (Mindful Chase)](https://www.mindfulchase.com/explore/troubleshooting-tips/front-end-frameworks/advanced-troubleshooting-in-sveltekit-fixing-ssr,-routing,-and-hydration-challenges.html) — MEDIUM

### Job queue & ops

- [Arq docs — idempotency + DLQ patterns](https://arq-docs.helpmanual.io/) — HIGH
- [Arq with Redis Streams (Medium)](https://medium.com/@saber.solooki/solving-job-distribution-problems-in-arq-with-redis-streams-59eb4e4d3ec5) — MEDIUM
- [Safir — Arq dependency usage (Rubin Observatory)](https://safir.lsst.io/user-guide/arq.html) — MEDIUM

### Governance & audit

- [OWASP A09 2025 — Security Logging and Alerting Failures](https://owasp.org/Top10/2025/A09_2025-Security_Logging_and_Alerting_Failures/) — HIGH
- [Audit Logging Best Practices (Sonar)](https://www.sonarsource.com/resources/library/audit-logging/) — MEDIUM
- [DAO Governance Attack Vectors (Olympix)](https://olympixai.medium.com/governance-attack-vectors-in-daos-a-comprehensive-analysis-of-identification-and-prevention-e27c08d45ae4) — MEDIUM
- [Top 8 Web3 Attack Vectors 2025 (Cantina)](https://cantina.xyz/blog/top-8-attack-vectors-for-2025) — MEDIUM

### Legal ontology & polysemy

- [Polysemy and the Law (Hemel, Vanderbilt Law Review)](https://scholarship.law.vanderbilt.edu/context/vlr/article/4881/viewcontent/Polysemy_and_the_Law.pdf) — HIGH
- [Polysemy in Legal English (CCJK)](https://www.ccjk.com/polysemy-in-legal-english/) — MEDIUM
- [FOLIO — Federated Open Legal Information Ontology announcement](https://openlegalstandard.org/announcing-soli-open-legal-standard/) — HIGH
- [FOLIO GitHub](https://github.com/alea-institute/FOLIO) — HIGH
- [How Courts Respond to Statutory Overrides (Duke Judicature)](https://judicature.duke.edu/articles/how-courts-do-and-dont-respond-to-statutory-overrides/) — HIGH
- [American Bar Association — Stare Decisis](https://www.americanbar.org/groups/public_education/publications/preview_home/understand-stare-decisis/) — HIGH

### IRIs & stable identifiers

- [FAIR Cookbook — Unique Persistent Identifiers](https://fairplus.github.io/the-fair-cookbook/content/recipes/findability/identifiers.html) — HIGH
- [Recommended IRI Patterns for Ontologies (CEDAR)](https://more.metadatacenter.org/recommended-iri-patterns-ontologies-and-their-terms) — MEDIUM
- [Effective RDF Resource Identifiers (STIDS 2014)](https://stids.c4i.gmu.edu/papers/STIDSPapers/STIDS2014_T3_Emmons.pdf) — MEDIUM

---

*Pitfalls research for: FOLIO Insights v2.0 shards-as-axioms milestone — refactor layered on v1.1*
*Researched: 2026-04-20*
*File: `.planning/research/PITFALLS.md`*

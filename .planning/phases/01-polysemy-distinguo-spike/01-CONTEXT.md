# Phase 01: Polysemy / distinguo Spike - Context

**Gathered:** 2026-04-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate §16 Risk 2 (polysemy detector FP rate, human-gate design) via a canonical legal *consideration* fixture before committing Phase 9.P6 architecture. This is a **spike** — a de-risking experiment that produces a fixture set, a prototype detector, a documented human-gate pattern, and a per-framework threshold recommendation. It does **not** ship production detector code; Phase 9.P6 does that.

**In scope:**
- Curated *consideration* fixture (≥20 shards across 3+ frameworks)
- Prototype polysemy detector (hybrid rule-then-LLM)
- CLI-only human-gate interaction (accept / reject / modify)
- FP-rate measurement on hand-labeled gold set (≤10% target)
- Per-framework threshold recommendation document for Phase 9.P6

**Out of scope (→ other phases):**
- Production-grade detector wired into Stage 2 (Phase 10 §9.2 + Phase 9.P6)
- Polysemy fork UI (Phase 15.polysemy-fork)
- Phase 14 design contract styling
- SHACL shapes for `fi:distinguishes` / `fi:analogousTo` (Phase 8 + Phase 11)
- Signed `fi:distinctioEvent` attestations (Phase 6)

</domain>

<decisions>
## Implementation Decisions

### D-1 Fixture sourcing — **Curated tri-source**
- Hand-curated seed fixture: ≥20 *consideration* shards across **3+ frameworks** (v1 advocacy corpus re-extracted + Restatement of Contracts + FRE).
- **Why:** Reproducible, ground-truth labelable, aligns with the roadmap's benchmark trio (CORPUS-04). Natural distribution keeps the spike grounded in real legal text, not synthesized edge cases.
- **Follow-ons (for planner):**
  - Fixture lives at `.planning/phases/01-polysemy-distinguo-spike/fixtures/consideration/` (hand-edited JSON or TTL, one shard per file).
  - Each shard carries `framework` (CommonLaw | CivilLaw | Restatement | FRE | …), `source_doc`, `extracted_text`, and a placeholder for `fi:primeAnalogate` / `fi:proportionalRelation`.
  - Deferred adversarial coverage → captured in Deferred Ideas (see below).

### D-2 Detector architecture — **Hybrid rule-then-LLM**
- Rule-first pipeline:
  1. Framework-conflicting *axioms* check (not just framework-conflicting *contexts* — per PITFALLS #8).
  2. N ≥ 3 shards per framework gate (single-shard clusters rejected as noise).
  3. Known-terms-of-art whitelist check (`consideration`, `notice`, `reasonable`, `material`, `person`, `holding`, `negligence`, `good faith`, …) — whitelisted terms require **higher** evidence threshold (start 0.8) before fork proposal.
  4. Known-homonym whitelist check (`bar`, `interest`, `execute`, `party`, `serve`) — flag "check homonymy" before fork.
- LLM fallback: `instructor` call invoked **only** when rule-layer confidence lands in a calibrated uncertainty band. Prompt explicitly frames the polysemy-vs-homonymy distinction (per PITFALLS L1248).
- Default `distinguo_threshold = 0.6` per PRD §16 R2.
- **Why:** Keeps LLM cost bounded, preserves determinism for the majority of cases, and aligns directly with PITFALLS #8 mitigation bullets. Pure-rule was rejected as too brittle for semantic nuance; pure-LLM was rejected as uncalibratable at scale.

### D-3 Human-gate UX — **CLI-only (TUI)**
- Spike ships a `folio-insights polysemy review` CLI subcommand with an accept / reject / modify prompt per proposed fork.
- **No auto-apply path** — enforced by CLI-only design (§16 R2, FEATURES §B anti-feature).
- Each disposition emits a structured decision record (JSON: `{shard_cluster, proposed_fork, disposition, rationale, reviewer_did, ts}`) suitable for re-consumption by Phase 15.polysemy-fork UI without reshape.
- Output: append-only JSONL log at `.planning/phases/01-polysemy-distinguo-spike/dispositions.jsonl`.
- **Why:** Decouples Phase 1 from Phase 14 design work. Phase 15 can re-read the same decision records when the Svelte surface lands — no schema rework.

### D-4 FP gold-set labeling — **Self-labeled + LLM audit**
- The sole maintainer (damienriehl, acting as practitioner) hand-labels the ≤10% FP test set directly.
- A secondary `instructor` audit pass labels the same fixture independently and reports **disagreements only**. User reviews disagreements and reconciles (authoritative label = user after reconciliation).
- Inter-annotator signal recorded in `fp-labeling-audit.md` for Phase 9.P6 planner.
- **Why:** Single-maintainer project means no second human labeler available; LLM audit catches obvious labeling drift without pretending to be a true second annotator. Deferring to Phase 15 practitioner sessions (Option C) was rejected because Phase 9.P6 planning needs the threshold recommendation before Phase 15 opens.

### Claude's Discretion

- **Detector code location:** Prototype module layout — suggest `src/folio_insights/polysemy/` per PRD §8.P6 L1105 (`detector.py`, `distinguo.py`, `prototype_cluster.py`, `similarity_query.py`). Planner may collapse or split based on line-count ergonomics.
- **Rule uncertainty band for LLM fallback:** Calibrate empirically on the fixture (no pre-decided numeric band); report chosen band in SUMMARY.md.
- **Sentence-transformer reuse:** Reuse `services/boundary/semantic.py` (all-MiniLM-L6-v2) for prototype cluster embeddings unless benchmarking shows need for a domain-specific model.
- **CLI ergonomics:** Single-key prompt (`[a]ccept / [r]eject / [m]odify`) or word-entry — planner's call.

### Folded Todos

None — no pending todos matched Phase 1 scope at cross-reference time.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 definitional anchors
- `.planning/ROADMAP.md` §Phase 1 (L103-116) — goal, exit criteria, REQ-IDs
- `.planning/v2.0-MILESTONE-BRIEF.md` L45 — phase placement + "Blocking §8" flag
- `.planning/REQUIREMENTS.md` — PRINCIPLE-06 (L104), VOCAB-02 (L90)

### Philosophical and design specification
- `PHILOSOPHY.md` L108-141 — scholastic distinguo machinery, `folio:analogousTo` as canonical cross-domain relation, distinctio-forking operator
- `PHILOSOPHY.md` L395 — theory-ladenness metadata (framework field justification)
- `PHILOSOPHY.md` L1247-1252 — polysemy-vs-homonymy distinction + known-homonym whitelist
- `PRD-v2.0-draft-2.md` §8.P6 (L1090-1114) — family-resemblance handling, three-tier structure, acceptance test on *consideration*
- `PRD-v2.0-draft-2.md` §16 Risk 2 (L1465-1467) — class-explosion risk + 0.6 threshold default + mandatory human-review gate
- `PRD-v2.0-draft-2.md` §9.2 (L1162-1167) — Stage 2 polysemy detector hooks (for Phase 10 consumer)

### Pitfalls + mitigations (load-bearing for detector design)
- `.planning/research/PITFALLS.md` L643-656 — Pitfall 8 "False-fork explosion on legal terms-of-art"
  - framework-conflicting **axioms** (not contexts) as mandatory evidence
  - N ≥ 3 shards per framework before fork proposal
  - known-terms-of-art whitelist (higher 0.8+ threshold)
  - fork-acceptance-rate dogfooding (<20% means detector over-proposing)
- `.planning/research/PITFALLS.md` L1247-1252 — polysemy-vs-homonymy LLM prompt framing

### Prior phase decisions carried forward
- `.planning/phases/00-foundations-hard-gate/00-DECISION.md` — `keep=pyoxigraph` verdict; detector prototype runs against pyoxigraph-backed store
- `.planning/phases/00-foundations-hard-gate/00-CONTEXT.md` — Phase 0 decisions (pyoxigraph 0.5.7, owlready2 0.50, rdflib bridge pattern, `rdf:Statement` reification vs `<<...>>`)

### No SPEC.md for this phase
- Requirements live in ROADMAP + PRD §8.P6 + §16 R2 + PRINCIPLE-06/VOCAB-02. No separate SPEC.md artifact.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/folio_insights/services/task_clustering.py` — sentence-transformers-based clustering, centroid computation, cluster validation pattern. Phase 1 prototype cluster module can subclass or wrap.
- `src/folio_insights/services/boundary/semantic.py` — all-MiniLM-L6-v2 loader with lazy singleton + cosine similarity at 0.3 default. Reuse for prototype cluster embeddings.
- `src/folio_insights/pipeline/stages/folio_tagger.py` — 4-path FOLIO tagger with confidence scoring. Framework-tag extraction on each shard relies on this.
- `src/folio_insights/pipeline/discovery/orchestrator.py` — DiscoveryPipeline pattern. Phase 9.P6 consumer integration pattern demonstrated; Phase 1 stays out of this orchestrator but mirrors its DiscoveryStage ABC.
- `src/folio_insights/store/` — Phase 0 PyoxigraphStore wrapper (SEC-01 SSRF mitigation already in place). Fixture loads through this wrapper.
- `src/folio_insights/services/bridge/folio_bridge.py` — v1 FolioService singleton with `fi:` IRI resolution; Phase 1 uses it to look up canonical *consideration* IRIs per framework.

### Established Patterns
- **Lazy-singleton ML models** — sentence-transformers + HermiT both loaded on first use. Phase 1 detector inherits this.
- **Session-scoped pytest fixtures** — Phase 0 established `bench_store` pattern; Phase 1 adds `consideration_fixture_store` analog.
- **CLI subgroup registration** — `cli.py` module-bottom import keeps heavy deps off the hot path. Phase 1 adds `polysemy` subgroup the same way.
- **`instructor` for LLM calls** — v2.0-locked pattern (brief §Tech Stack). Phase 1 LLM-audit and fallback paths both use `instructor`.
- **Rule-first with LLM fallback** — mirrors v1's 4-path FOLIO tagger (regex + EntityRuler + embedding + LLM) — Phase 1 detector follows the same shape.

### Integration Points
- **Pyoxigraph store** — fixture loads go through `PyoxigraphStore` wrapper; queries use named graphs per corpus (`urn:folio:corpus/consideration-spike`).
- **CLI:** New `folio-insights polysemy` subgroup sibling to `bench`, `discover`, `export`, `extract`, `serve`.
- **Output artifacts** (in phase dir, not `src/`): `fixtures/consideration/*.json`, `dispositions.jsonl`, `fp-labeling-audit.md`, SUMMARY.md, recommendations for 9.P6.

</code_context>

<specifics>
## Specific Ideas

- **Default threshold:** 0.6 for non-whitelisted terms; 0.8 for known-terms-of-art (both configurable via `--distinguo-threshold` CLI flag).
- **Minimum cluster size:** N ≥ 3 shards per framework (per PITFALLS #8 mitigation). Below that, detector returns `insufficient-evidence` rather than proposing a fork.
- **Framework tags to recognize initially:** `CommonLaw`, `CivilLaw`, `Restatement`, `FRE`. Hand-curated fixture shards carry explicit framework tags — no framework-inference in Phase 1.
- **Prototype cluster IRI scheme:** `fi:PrototypeCluster_<hex8>` per PRD §8.P6 L1098 (not production IRI scheme — Phase 4 defines that).
- **Disposition JSONL schema (lock-in for Phase 15.polysemy-fork consumer):**
  ```json
  {"cluster_id": "...", "proposed_fork": {...}, "disposition": "accept|reject|modify", "rationale": "...", "reviewer_did": "did:key:...", "ts": "ISO-8601", "detector_confidence": 0.nn}
  ```
  Any schema change requires a follow-up spec; Phase 15 plans will bind to this shape.

</specifics>

<deferred>
## Deferred Ideas

- **LLM-synthesized adversarial fixtures** — instructor-generated homonym and near-miss cases to stress FP rate. Defer until post-Phase 1 calibration shows the natural-distribution fixture is insufficient. Tracked for a potential Phase 1.1 or for Phase 9.P6 planning.
- **Second-human annotator** — true inter-annotator agreement requires a second practitioner. Deferred to Phase 15 practitioner think-aloud sessions (QUALITY-05 gate) — where practitioner labels can backfill Phase 1's measurement for 9.P6 re-calibration.
- **Per-framework threshold auto-tuning** — Phase 1 proposes thresholds; automated tuning loop (grid-search + cross-validation) is Phase 9.P6 work.
- **Fork-acceptance-rate dashboard** — PITFALLS #8 dogfooding metric (<20% means over-proposing). Phase 12 Observability adds the Prometheus counter; Phase 1 captures the raw disposition JSONL.
- **Production `fi:distinctioEvent` attestations** — signing, PROV-O log entries, governance-tier authorization. All deferred to Phase 6 (DID substrate) + Phase 7 (governance model).
- **Three-tier storage (SKOS grouping + jurisdiction-scoped classes + prototype cluster)** — PRD §8.P6 L1094-1098 full structure. Phase 1 implements only the prototype cluster slice; Phase 9.P6 implements the SKOS grouping and jurisdiction classes.
- **Polysemy fork UI** — Svelte surface with "What would this fork affect?" preview, 15-min undo. Phase 15.polysemy-fork owns this; Phase 1 only emits the JSONL contract that UI will consume.

</deferred>

---

*Phase: 01-polysemy-distinguo-spike*
*Context gathered: 2026-04-23*

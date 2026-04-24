---
phase: 01-polysemy-distinguo-spike
plan: 03
subsystem: polysemy

tags: [pyoxigraph, sparql, owl-disjointwith, sentence-transformers, instructor, pydantic, literal-union, tdd, provider-agnostic-llm]

# Dependency graph
requires:
  - phase: 01-polysemy-distinguo-spike
    provides: "Plan 01-02 data-layer — ShardFixture + CONSIDERATION_NAMED_GRAPH + consideration_fixtures_to_ttl (fixture_loader.py), TERMS_OF_ART + HOMONYMS + thresholds (whitelists.py), and 20 hand-curated consideration shards"
  - phase: 00-foundations-hard-gate
    provides: "PyoxigraphStore wrapper with SEC-01 SERVICE preflight (query_rdf12), services/boundary/semantic.py::_get_model lazy singleton"
provides:
  - "src/folio_insights/polysemy/prototype_cluster.py — PrototypeCluster dataclass + build_prototype_cluster() + compute_cluster_centroids() + centroid_distance_signal() (evidence-score surface only)"
  - "src/folio_insights/polysemy/similarity_query.py — has_framework_conflicting_axiom() SPARQL ASK over owl:disjointWith via PyoxigraphStore.query_rdf12 (OQ-1 authoritative signal)"
  - "src/folio_insights/polysemy/detector.py — detect_polysemy() 4-rule gate + provider-agnostic instructor LLM fallback; RuleVerdict and LLMVerdict discriminated-union Pydantic models"
  - "LLMBridge.INSIGHTS_TASKS now includes 'polysemy_fallback' (env-var override path: LLM_POLYSEMY_FALLBACK_PROVIDER / _MODEL)"
  - "PyoxigraphStore.query_rdf12 now correctly handles ASK queries (returns QueryBoolean; SELECT/CONSTRUCT/DESCRIBE unchanged) — fixes latent bug that would have blocked any ASK caller"
affects: [01-04-distinguo-emission, 01-05-cli-review, 01-06-fp-audit, 15-polysemy-fork]

# Tech tracking
tech-stack:
  added: []  # all deps already declared in Plan 01-01 pyproject.toml
  patterns:
    - "Discriminated-union Pydantic verdicts: RuleVerdict(kind='rule') | LLMVerdict(kind='llm') — callers dispatch on .kind; decision is always Literal[polysemy|homonymy|coincidence|uncertain] (A6 discipline: no raw float confidence field)"
    - "Lazy-singleton embedding model reuse: compute_cluster_centroids() imports services.boundary.semantic._get_model inside the function body (A8 — no new model load beyond the one already warm in Phase 0.1)"
    - "SPARQL ASK routed via PyoxigraphStore.query_rdf12 (SEC-01 inherited); ASK callers use bool(result) on the QueryBoolean, SELECT callers receive list() as before"
    - "Provider-agnostic instructor: _resolve_provider_family maps 'claude-*'/'gpt-*'/'gemini-*'/'ollama/*' prefixes to instructor family strings; llm_provider is a single CLI-wired string, not a vendor-specific config object"
    - "Defensive LLM-fallback: all exceptions caught and converted to LLMVerdict(decision='uncertain', reasoning=f'{ExcType}: {msg}') so detect_polysemy NEVER raises from a rule run (T-01-09 DoS guard)"
    - "Rule-first, LLM-fallback-last gate ordering: R1 SPARQL → R2 N≥3 → R3 threshold → R4 HOMONYMS-LLM; short-circuits on first decisive rule"

key-files:
  created:
    - src/folio_insights/polysemy/prototype_cluster.py
    - src/folio_insights/polysemy/similarity_query.py
    - src/folio_insights/polysemy/detector.py
  modified:
    - src/folio_insights/services/bridge/llm_bridge.py
    - src/folio_insights/store/pyoxigraph_store.py
    - tests/polysemy/test_prototype_cluster.py
    - tests/polysemy/test_detector_rules.py
    - tests/polysemy/test_detector_llm_fallback.py

key-decisions:
  - "PyoxigraphStore.query_rdf12 fix applied in-place (not around the call-site) so every future ASK caller gets the correct behavior free; the wrapper is the project's SEC-01 trust boundary, so the fix belongs there and not in similarity_query.py"
  - "PolysemyVerdict (instructor response model) kept separate from LLMVerdict (detector output model) — decouples the LLM contract from the downstream disposition-record contract; LLMVerdict adds provider/matched_rules/evidence_score fields the LLM does not supply"
  - "threshold_override kwarg on detect_polysemy — lets Plan 01-06 FP-audit sweep thresholds without editing whitelists.py constants (CONTEXT.md revision discipline preserved for production thresholds; sweeps are exploratory)"
  - "Evidence score surfaces on every verdict (both RuleVerdict and LLMVerdict) — Plan 01-06 FP audit consumes evidence_score directly; 01-05 CLI displays it in the review loop; Plan 15 UI will show it but never treat it as a calibrated probability (A6)"

patterns-established:
  - "RED-GREEN TDD split with separate commits per file pair: each task does a RED commit (test rewrite → ModuleNotFoundError) and a GREEN commit (implementation). Wave-0 xfail placeholders are overwritten in RED, flipped to PASSED in GREEN."
  - "Test-side mock for upstream SPARQL: test_detector_rules.py patches folio_insights.polysemy.detector.has_framework_conflicting_axiom directly (not the inner pyoxigraph call) — cleanly isolates rule-layer tests from store wiring"
  - "Instructor fake client pattern: nested static-method class chat.completions.create(**kwargs) returns a canned Pydantic model; patch('instructor.from_provider', return_value=_FakeClient()) keeps LLM-fallback tests deterministic and offline"

requirements-completed: [PRINCIPLE-06]

# Metrics
duration: ~20min
completed: 2026-04-24
---

# Phase 01 Plan 03: Detector Core Summary

**Prototype-cluster embeddings (reusing the existing all-MiniLM-L6-v2 singleton over axiom_summary — Pitfall 1 guard), SPARQL owl:disjointWith via PyoxigraphStore.query_rdf12 (OQ-1 authoritative signal), and a 4-rule gate with provider-agnostic instructor LLM fallback returning a Literal-typed discriminated union (A6 guard, OQ-5 pluggability) — the detector core PRINCIPLE-06 scopes before Plan 01-06 measures false-positive rate.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-24T18:05:00Z (approx, post-worktree-base-reset)
- **Completed:** 2026-04-24T18:25:00Z
- **Tasks:** 2 (each TDD-split into RED + GREEN commits; plus 1 auto-fix commit for a blocking wrapper bug)
- **Files modified:** 8 (3 src created + 2 src modified + 3 tests rewritten)

## Accomplishments

- **Prototype cluster embedding** locked on axiom_summary (Pitfall 1 mitigation — NOT extracted_text). `compute_cluster_centroids()` imports `_get_model` lazily from `services.boundary.semantic` so no new model load is triggered (A8). `PrototypeCluster` dataclass ships a deterministic `fi:PrototypeCluster_<hex8>` cluster_id minted from `sha256("{term}|{sorted_frameworks}")[:8]`. Cross-framework pairwise cosine distance is computed and stored symmetrically in both `(a, b)` and `(b, a)` orderings so downstream lookup is ordering-free.
- **Rule 1 lands on SPARQL owl:disjointWith** (OQ-1 orchestrator lock). `has_framework_conflicting_axiom` issues an ASK over each ordered framework pair through `PyoxigraphStore.query_rdf12` — the SEC-01 SERVICE preflight is inherited, and raw `store.store.query()` access is forbidden by `grep -rn 'store.store' src/folio_insights/polysemy/` → 0 (T-01-10 PASS). At Phase 1 (empty TBox) the ASK always returns False → the detector short-circuits to `RuleVerdict(decision='coincidence', matched_rules=['R1-no-conflict'])`. This is the intended default; Phase 1 is scoping, not measurement.
- **Detector 4-rule gate** matches CONTEXT.md D-2 verbatim: R1 SPARQL owl:disjointWith → R2 N≥3 per framework → R3 evidence ≥ threshold (0.8 for TERMS_OF_ART, 0.6 default) → R4 HOMONYMS force LLM fallback. Short-circuits on first decisive result. `threshold_override` kwarg lets Plan 01-06 sweep thresholds without editing whitelists.py.
- **Discriminated-union verdict shape** locked: `RuleVerdict(kind='rule', decision: Literal[polysemy|homonymy|coincidence|uncertain], rule_confidence, matched_rules, evidence_score)` and `LLMVerdict(kind='llm', ...same decision Literal..., polysemy_vs_homonymy_reasoning, rationale, provider, matched_rules, evidence_score)`. **No `confidence_score` field anywhere** (A6 asserted via `assert not hasattr(verdict, 'confidence_score')` in test_detector_llm_fallback).
- **Provider-agnostic instructor fallback** (OQ-5): `_resolve_provider_family` maps `'claude-*'` → `anthropic`, `'gpt-*'` → `openai`, `'gemini-*'` → `google`, `'ollama/*'` → `ollama`; any other prefix falls back to `anthropic` (safe default, Phase 1 primary). `instructor.from_provider(f"{family}:{model}")` is called with the resolved family + model; `'ollama/llama3.2'` correctly strips to `'ollama:llama3.2'`. Four parametrized tests exercise all four provider families against a fake client and verify the captured spec string starts with the expected family prefix.
- **Defensive LLM fallback** — any exception (import error, network fault, provider auth rejection) is caught and converted to `LLMVerdict(decision='uncertain', reasoning='{ExcType}: {msg}', provider=family, ...)`. Verified by `test_llm_fallback_swallows_exceptions` (patches `instructor.from_provider` with `side_effect=RuntimeError('network')`, asserts `verdict.decision == 'uncertain'` and `'RuntimeError' in reasoning`). T-01-09 mitigation: detector cannot hang on network fault.
- **LLMBridge registration** — `INSIGHTS_TASKS += ('polysemy_fallback',)` registers the task for the per-task env-var override path (`LLM_POLYSEMY_FALLBACK_PROVIDER`, `LLM_POLYSEMY_FALLBACK_MODEL`) — 01-05 CLI review will consume this path when invoking the detector.
- **10 of 11 detector-layer xfails flipped to PASSED** — the polysemy suite is now 17 passed / 8 xfailed (was 7 passed / 14 xfailed after Plan 01-02). Remaining 8 xfails map to Plan 01-04 (distinguo emission, 3 tests), 01-05 (CLI review, 2 tests), and 01-06 (FP audit, 3 tests). The 10 flipped are 1 (test_prototype_cluster) + 4 (test_detector_rules) + 5 (test_detector_llm_fallback — 4 parametrized + 1 exception).

## Task Commits

Each task TDD-split into RED (failing test) + GREEN (implementation):

1. **Task 1 RED: test_prototype_cluster asserts centroid math + cluster id** — `5718ccf` (test)
2. **Task 1 GREEN: prototype_cluster + similarity_query (SPARQL owl:disjointWith)** — `5c90e20` (feat)
3. **Task 2 RED: detector 4-rule gate + LLM fallback assertion set** — `b18d11c` (test)
4. **Task 2 GREEN: detector 4-rule gate + provider-agnostic LLM fallback** — `c0fe871` (feat)
5. **Deviation auto-fix: PyoxigraphStore.query_rdf12 supports ASK (QueryBoolean return)** — `ee0cfeb` (fix)

_Metadata commit for this SUMMARY will be added after self-check. No REFACTOR commit needed — GREEN code landed clean._

## Files Created/Modified

**Created — source (3):**
- `src/folio_insights/polysemy/prototype_cluster.py` — `PrototypeCluster` dataclass, `build_prototype_cluster()`, `compute_cluster_centroids()`, `centroid_distance_signal()`, `_mint_cluster_id()`
- `src/folio_insights/polysemy/similarity_query.py` — `has_framework_conflicting_axiom()` (ASK over all ordered framework pairs via `query_rdf12`)
- `src/folio_insights/polysemy/detector.py` — `RuleVerdict`, `LLMVerdict`, `PolysemyVerdict`, `_resolve_provider_family()`, `_invoke_llm_fallback()`, `detect_polysemy()`

**Modified — source (2):**
- `src/folio_insights/services/bridge/llm_bridge.py` — appended `'polysemy_fallback'` to `INSIGHTS_TASKS` tuple
- `src/folio_insights/store/pyoxigraph_store.py` — `query_rdf12` now branches on `hasattr(raw, '__iter__')` to support ASK (QueryBoolean) returns; SELECT/CONSTRUCT/DESCRIBE unchanged (still materialized to list)

**Modified — tests (3) [xfail → real]:**
- `tests/polysemy/test_prototype_cluster.py` — `test_centroid_per_framework` exercises 9-shard cluster, asserts 3 centroids × (384,), symmetric distance, FRE-further-than-Restatement ordering, hex8 cluster IRI
- `tests/polysemy/test_detector_rules.py` — 4 tests (R1/R2/R3/R4) with synthetic `PrototypeCluster` + `patch('...has_framework_conflicting_axiom')` to isolate each rule
- `tests/polysemy/test_detector_llm_fallback.py` — parametrized over 4 providers (claude/gpt/gemini/ollama) + exception-swallowing test

## Measured Centroid Distances

### On the 9-shard test corpus (test_centroid_per_framework)

| Pair                        | Distance |
|-----------------------------|----------|
| CommonLaw ↔ Restatement     | 0.5770   |
| CommonLaw ↔ FRE             | 0.7396   |
| Restatement ↔ FRE           | 0.8052   |

FRE is correctly further from CommonLaw (0.740) than Restatement is (0.577) — the OQ-3 fixture authoring (FRE = evidentiary weighing vs. Restatement = contract formation) produces the expected signal direction.

### On the committed 20-shard fixture (end-to-end smoke)

| Pair                        | Distance |
|-----------------------------|----------|
| CommonLaw ↔ Restatement     | 0.5430   |
| CommonLaw ↔ FRE             | 0.6116   |
| CommonLaw ↔ UCC             | 0.6378   |
| Restatement ↔ FRE           | 0.5957   |
| Restatement ↔ UCC           | 0.6196   |
| FRE ↔ UCC                   | 0.6728   |

**Max cross-framework distance: 0.6728.** Range [0.543, 0.673] — below `TERMS_OF_ART_THRESHOLD=0.8` but above `DEFAULT_DISTINGUO_THRESHOLD=0.6` for 5 of 6 pairs. This is the empirical uncertainty-band input Plan 01-06 SUMMARY uses to recommend a Phase 9.P6 threshold: the 0.8 whitelist threshold would reject this cluster (consideration is TERMS_OF_ART) at Rule 3 even if Rule 1 passed; a relaxed 0.6 sweep would keep it on the polysemy path. Plan 01-06's FP-audit sweep will cover this band.

## Rule Firing Distribution on the 20-Shard Fixture

**1 cluster, 1 verdict → 100% R1-no-conflict.**

The TTL emitted by `consideration_fixtures_to_ttl()` carries only `fi:ShardFixture` instances with `fi:termOfArt`/`fi:inFramework` — no `owl:disjointWith` TBox assertions. This is by design (Plan 01-02 key-decision: "TTL helper emits minimal vocab; full distinguo vocabulary lands in 01-04"). At Phase 1, Rule 1 correctly short-circuits to `R1-no-conflict` for all clusters, producing `RuleVerdict(decision='coincidence', rule_confidence=0.9, evidence_score=0.6728)`.

This is the intended OQ-1 behavior: **absence of an explicit axiom-conflict assertion means we do NOT treat cosine distance (0.673) as enough evidence for polysemy.** Plan 01-04 emits `fi:distinctionKind` + `fi:analogousTo` triples (distinguo vocabulary) but does NOT emit `owl:disjointWith` — the latter is a TBox modeling choice the phase defers to Phase 2+ (post-spike).

**Implication for Plan 01-06 FP-audit:** running the detector on the 20-shard fixture as-is produces 0 proposed forks (all R1-no-conflict). The audit harness must either (a) add owl:disjointWith TBox assertions to a second named graph for the sweep, or (b) patch `has_framework_conflicting_axiom` in the harness to return True, then exercise R2/R3/R4 behavior. Plan 01-06 can choose.

## Provider Resolution Status (A1/A2 Carry)

At detector import time, **no provider is resolved** — `instructor.from_provider(...)` is called lazily inside `_invoke_llm_fallback` on a try/except. The four provider strings (`claude-haiku-4-5`, `gpt-4o-mini`, `gemini-1.5-flash`, `ollama/llama3.2`) are verified by the test suite to route to the correct family (`anthropic`, `openai`, `google`, `ollama`) but NO live provider SDK is probed.

At runtime, a missing provider library (e.g., `google-genai` not installed) will raise on the `instructor.from_provider` call and be caught → `LLMVerdict(decision='uncertain', reasoning='ImportError: ...')`. This is intentional: Phase 1 does not mandate that all four provider SDKs be installed; Plan 01-05 CLI surfaces the `--llm-provider` flag and the user picks a provider they have credentials for.

**A1 (anthropic) + A2 (openai) unresolved at import:** status preserved — both SDKs are installed (see Plan 01-01 pyproject.toml), but no auth probe is performed at import time. Plan 01-05 CLI will handle the first live call.

## Decisions Made

- **PyoxigraphStore.query_rdf12 fix applied in-place (not around the call-site).** Every future ASK caller now gets the correct behavior. The wrapper is the project's SEC-01 trust boundary so the fix belongs there and not in similarity_query.py. Tests for existing SELECT/CONSTRUCT callers remain green (`pytest tests/store/test_pyoxigraph_store.py` → 8 passed).
- **PolysemyVerdict (instructor response) kept separate from LLMVerdict (detector output).** Decouples the LLM contract from the downstream disposition-record contract; LLMVerdict adds `provider` + `matched_rules` + `evidence_score` fields the LLM does not supply. Phase 15 UI reads LLMVerdict; the LLM itself only produces PolysemyVerdict.
- **`threshold_override` kwarg on `detect_polysemy`** — lets 01-06 sweep thresholds without editing `whitelists.py` constants. The production thresholds (`TERMS_OF_ART_THRESHOLD=0.8`, `DEFAULT_DISTINGUO_THRESHOLD=0.6`) still require CONTEXT.md revision to change (Plan 01-02 discipline); sweeps are exploratory and do not mutate module-level state.
- **`evidence_score` surfaced on every verdict** (both RuleVerdict and LLMVerdict). 01-06 FP audit consumes it directly for sorting; 01-05 CLI displays it in review; Plan 15 UI shows it but never treats it as a calibrated probability (A6 discipline preserved).
- **Test-side cluster construction overrides `shard.term` when term != 'consideration'** — `_cluster(term='bar', ...)` mutates each shard's `.term` so the cluster is internally consistent. The detector reads `cluster.term` (not `shard.term`) so behavior is unaffected, but keeping them in sync avoids a latent gotcha for future test authors.
- **`_resolve_provider_family` safe default is `anthropic`** — if an unknown prefix arrives (e.g., a typo), we route to Claude (Phase 1 primary) rather than raising. The instructor call will then raise if the full model string is invalid, and the exception path converts it to `LLMVerdict(decision='uncertain')`. No silent miscategorization.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] PyoxigraphStore.query_rdf12 unconditionally wraps in list() — breaks ASK queries**

- **Found during:** Task 2 end-to-end smoke run (ran `detect_polysemy` against the live 20-shard fixture store).
- **Issue:** `query_rdf12()` unconditionally called `list(self._store.query(...))`, but pyoxigraph returns a non-iterable `QueryBoolean` for ASK queries, raising `TypeError("'pyoxigraph.QueryBoolean' object is not iterable")`. This would have blocked Rule 1 on any live fixture store. Existing Phase 0 callers (`gate2_harness.py`, `test_pyoxigraph_store.py`) all use SELECT and never hit the bug.
- **Fix:** Branch on `hasattr(raw, '__iter__')`:
  - iterable (SELECT / CONSTRUCT / DESCRIBE) → `list(raw)` (unchanged behavior)
  - non-iterable (ASK QueryBoolean) → return `raw` as-is; callers use `bool(result)`
  Return-type annotation relaxed from `list` to unannotated (union). Module + method docstrings now document the branching.
- **Scope:** Within the 01-03 scope boundary because `similarity_query.py` is the first ASK caller in the codebase and the bug is directly caused by this plan's introduction of ASK-via-query_rdf12.
- **Files modified:** `src/folio_insights/store/pyoxigraph_store.py`
- **Verification:** `pytest tests/store/test_pyoxigraph_store.py --timeout=30` → 8 passed, 0 failed. End-to-end detector smoke now produces `RuleVerdict(decision='coincidence', matched_rules=['R1-no-conflict'])` on the 20-shard fixture without raising.
- **Committed in:** `ee0cfeb` (separate fix commit, not part of a task)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking issue caused by this plan's first ASK caller)
**Impact on plan:** Fix was necessary to make Rule 1 functional at runtime; the unit tests all patched `has_framework_conflicting_axiom` so the bug did not surface in the test suite. No scope creep — the fix is precisely what's needed to make the authoritative Rule 1 SPARQL signal operate on a live store.

## Issues Encountered

- **Worktree had no `.venv`:** Same setup pattern as Plans 01-01 and 01-02. `uv venv .venv && uv pip install -e '.[dev]'` reconstructed the environment (98 packages including sentence-transformers 3.x, pyoxigraph 0.5.x, pydantic 2.x, instructor 1.15.1). Not a blocker — standard worktree behavior.
- **No MCP context7 used:** The plan explicitly cites pyoxigraph, instructor, and sentence-transformers APIs. All three have stable APIs at the versions locked by Plan 01-01 pyproject.toml and the plan's code snippets matched the installed versions (verified by running each test: the instructor `from_provider` signature, pyoxigraph `QueryBoolean` vs iterator return types, sentence-transformers `encode(..., normalize_embeddings=True)` kwarg all matched). No doc lookup needed.

## User Setup Required

None — no external service configuration required for Phase 1 scope.

**Note for 01-05 CLI review:** when the CLI first invokes `detect_polysemy` with an `--llm-provider` flag that maps to a live provider (e.g., `claude-haiku-4-5`), the provider's API key environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or Ollama's local HTTP endpoint) must be set. A missing key will surface as `LLMVerdict(decision='uncertain', reasoning='<AuthError>: ...')` — the detector never raises, so the CLI can continue and surface the error to the reviewer. Plan 01-05 is the natural place to document this more fully.

## Next Phase Readiness

- **Plan 01-04 (distinguo emission, Wave 2 — runs in parallel with this plan):**
  - Reads `ProposedFork.uses_analogousTo` (shipped in 01-02) to decide whether to emit `fi:analogousTo` triples alongside the distinguo TTL.
  - Does NOT depend on this plan's detector — Plan 01-04 emits distinguo TTL from a ProposedFork; it's the detector's downstream consumer (01-05 CLI) that chains the two together.
- **Plan 01-05 (CLI review, Wave 3):**
  - Calls `detect_polysemy(cluster, store, llm_provider=args.llm_provider)` for each term-cluster.
  - Dispatches on `verdict.kind`: RuleVerdict for display, LLMVerdict for display + LLM-provenance-tag.
  - Writes the full verdict into `DispositionRecord.detector_verdict = verdict.model_dump()` — the B6 canonical shape from Plan 01-02 (dict, not float) round-trips losslessly.
  - Uses `ensure_reviewer_did()` (Plan 01-02) for `DispositionRecord.reviewer_did` population.
- **Plan 01-06 (FP audit, Wave 4):**
  - Streams `DispositionRecord.detector_verdict` via `read_dispositions(path)` (Plan 01-02 iterator).
  - Sorts by `detector_verdict['evidence_score']` for sweep analysis.
  - Uses `threshold_override` kwarg on `detect_polysemy` to explore threshold sensitivity on the 20-shard fixture (plus any additional shards the audit harness adds). See "Implication for Plan 01-06" above re: Rule 1 short-circuiting on an empty TBox.
- **Phase 15 polysemy-fork UI (downstream phase):** discriminated-union verdict shape locked; UI will branch on `verdict.kind ∈ {'rule', 'llm'}`; `decision: Literal[polysemy|homonymy|coincidence|uncertain]` is the canonical UI-state enum. No calibrated-probability field anywhere — UI displays `rule_confidence` as a band label (e.g., "high"), not a percentage.

**Blockers for downstream:** None. Plan 01-05 CLI is gated on the merge of this plan's worktree + Plan 01-04's (they ship in parallel).

## Self-Check

- [x] `src/folio_insights/polysemy/prototype_cluster.py` exists with `compute_cluster_centroids`, `build_prototype_cluster`, `centroid_distance_signal`, `PrototypeCluster`
- [x] `src/folio_insights/polysemy/similarity_query.py` exists with `has_framework_conflicting_axiom` and `query_rdf12` grep hit
- [x] `src/folio_insights/polysemy/detector.py` exists with `detect_polysemy`, `_invoke_llm_fallback`, `instructor.from_provider`, `Literal[polysemy|homonymy|coincidence|uncertain]`
- [x] `R1-no-conflict`, `R2-insufficient-evidence`, `R3-below-threshold`, `R4-homonym-flag` — all present in detector.py (grep confirms 1 hit each)
- [x] `polysemy_fallback` in INSIGHTS_TASKS (grep confirms 1 hit)
- [x] `grep -rn 'store.store' src/folio_insights/polysemy/` → 0 hits (T-01-10 satisfied)
- [x] `pytest tests/polysemy/test_prototype_cluster.py tests/polysemy/test_detector_rules.py tests/polysemy/test_detector_llm_fallback.py --timeout=60` → 10 passed, 0 failed
- [x] `pytest tests/polysemy/` → 17 passed, 8 xfailed (was 7 passed / 14 xfailed — 10 Wave-0 xfails flipped)
- [x] `pytest tests/store/test_pyoxigraph_store.py --timeout=30` → 8 passed (wrapper fix did not regress existing callers)
- [x] `python -c 'from folio_insights.polysemy.detector import detect_polysemy'` → ok (no circular imports)
- [x] Commit `5718ccf` (Task 1 RED) present in git log
- [x] Commit `5c90e20` (Task 1 GREEN) present in git log
- [x] Commit `b18d11c` (Task 2 RED) present in git log
- [x] Commit `c0fe871` (Task 2 GREEN) present in git log
- [x] Commit `ee0cfeb` (auto-fix deviation) present in git log
- [x] No modifications to `src/folio_insights/polysemy/distinguo.py` (owned by 01-04) — file does not exist in this worktree
- [x] No modifications to `src/folio_insights/polysemy/dispositions.py`, `reviewer.py`, `__init__.py` (all owned by 01-02)
- [x] No modifications to STATE.md or ROADMAP.md (orchestrator owns those)

## Self-Check: PASSED

All 3 new source modules verified on disk with correct content, 2 modified source modules verified, all 3 test files green, all 5 task/deviation commits verified in git log, full polysemy suite clean at 17 passed / 8 xfailed (10 Wave-0 xfails flipped). `pytest tests/polysemy/test_prototype_cluster.py tests/polysemy/test_detector_rules.py tests/polysemy/test_detector_llm_fallback.py --timeout=60` exits 0.

---
*Phase: 01-polysemy-distinguo-spike*
*Completed: 2026-04-24*

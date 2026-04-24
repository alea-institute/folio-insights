# Phase 01: Polysemy / distinguo Spike — Research

**Researched:** 2026-04-23
**Domain:** Hybrid rule-then-LLM polysemy detector on curated legal fixtures, CLI-only human-gate TUI, JSONL disposition log, FP-rate measurement with secondary LLM audit
**Confidence:** HIGH on stack reuse (Phase 0 outputs + existing v1 code) and pitfall catalogue (PITFALLS #8 + V5 + L1247-1252 verified in-repo). MEDIUM on threshold-calibration methodology (literature supports Wilson/bootstrap for small n but no legal-NLP precedent at n=20). MEDIUM on disposition JSONL schema stability (schema is locked by D-3; forward-compat fields identified but not tested against Phase 15 consumer — that consumer does not yet exist). LOW on "what counts as an axiom for an un-signed Phase 1 shard" — this is unresolved in the upstream spec and surfaces as Open Question 1 below.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-1 Fixture sourcing — Curated tri-source**
- Hand-curated seed fixture: ≥20 *consideration* shards across **3+ frameworks** (v1 advocacy corpus re-extracted + Restatement of Contracts + FRE).
- Fixture lives at `.planning/phases/01-polysemy-distinguo-spike/fixtures/consideration/` (hand-edited JSON or TTL, one shard per file).
- Each shard carries `framework` (CommonLaw | CivilLaw | Restatement | FRE | …), `source_doc`, `extracted_text`, and a placeholder for `fi:primeAnalogate` / `fi:proportionalRelation`.

**D-2 Detector architecture — Hybrid rule-then-LLM**
- Rule-first pipeline:
  1. Framework-conflicting *axioms* check (not just framework-conflicting *contexts* — per PITFALLS #8).
  2. N ≥ 3 shards per framework gate (single-shard clusters rejected as noise).
  3. Known-terms-of-art whitelist check (`consideration`, `notice`, `reasonable`, `material`, `person`, `holding`, `negligence`, `good faith`, …) — whitelisted terms require **higher** evidence threshold (start 0.8) before fork proposal.
  4. Known-homonym whitelist check (`bar`, `interest`, `execute`, `party`, `serve`) — flag "check homonymy" before fork.
- LLM fallback: `instructor` call invoked **only** when rule-layer confidence lands in a calibrated uncertainty band. Prompt explicitly frames the polysemy-vs-homonymy distinction (per PITFALLS L1248).
- Default `distinguo_threshold = 0.6` per PRD §16 R2.

**D-3 Human-gate UX — CLI-only (TUI)**
- Spike ships a `folio-insights polysemy review` CLI subcommand with accept / reject / modify prompt per proposed fork.
- **No auto-apply path** — enforced by CLI-only design (§16 R2, FEATURES §B anti-feature).
- Each disposition emits a structured decision record (JSON: `{shard_cluster, proposed_fork, disposition, rationale, reviewer_did, ts}`) suitable for re-consumption by Phase 15.polysemy-fork UI without reshape.
- Output: append-only JSONL log at `.planning/phases/01-polysemy-distinguo-spike/dispositions.jsonl`.

**D-4 FP gold-set labeling — Self-labeled + LLM audit**
- The sole maintainer hand-labels the ≤10% FP test set directly.
- A secondary `instructor` audit pass labels the same fixture independently and reports **disagreements only**. User reviews disagreements and reconciles (authoritative label = user after reconciliation).
- Inter-annotator signal recorded in `fp-labeling-audit.md` for Phase 9.P6 planner.

### Claude's Discretion

- **Detector code location:** Prototype module layout — suggest `src/folio_insights/polysemy/` per PRD §8.P6 L1105 (`detector.py`, `distinguo.py`, `prototype_cluster.py`, `similarity_query.py`). Planner may collapse or split based on line-count ergonomics.
- **Rule uncertainty band for LLM fallback:** Calibrate empirically on the fixture (no pre-decided numeric band); report chosen band in SUMMARY.md.
- **Sentence-transformer reuse:** Reuse `services/boundary/semantic.py` (all-MiniLM-L6-v2) for prototype cluster embeddings unless benchmarking shows need for a domain-specific model.
- **CLI ergonomics:** Single-key prompt (`[a]ccept / [r]eject / [m]odify`) or word-entry — planner's call.

### Deferred Ideas (OUT OF SCOPE)

- **LLM-synthesized adversarial fixtures** — defer until post-Phase 1 calibration. Tracked for potential Phase 1.1 or Phase 9.P6.
- **Second-human annotator** — deferred to Phase 15 practitioner think-aloud (QUALITY-05).
- **Per-framework threshold auto-tuning** — Phase 1 proposes; automated tuning is Phase 9.P6 work.
- **Fork-acceptance-rate dashboard** — Phase 12 Observability.
- **Production `fi:distinctioEvent` attestations** — Phase 6 (DID) + Phase 7 (governance).
- **Three-tier storage (SKOS grouping + jurisdiction-scoped classes + prototype cluster)** — Phase 9.P6 implements the full PRD §8.P6 L1094-1098 structure. Phase 1 implements only the prototype cluster slice.
- **Polysemy fork UI (Svelte)** — Phase 15.polysemy-fork. Phase 1 only emits the JSONL contract that UI will consume.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PRINCIPLE-06 | P6 — Polysemy detector flags same-IRI shards with framework-conflicting axioms; human-gated (always) before distinguo commit. FP test set < 10% FP rate on curated fixtures; auto-apply is impossible by design. *(Scoping only — full impl Phase 9.P6.)* | `## Architecture Patterns` (prototype cluster algorithm, 4-rule gate) + `## Common Pitfalls` (Pitfall 1: confusing framework-conflicting contexts with axioms — the classic PITFALLS #8 footgun) + `## Don't Hand-Roll` (reuse all-MiniLM-L6-v2 loader). Phase 1 delivers the measurement (≤10% FP on n≥20) but intentionally does NOT wire into Stage 2 of the pipeline — that is 9.P6's scope (ROADMAP L274 + CONTEXT §Phase Boundary). |
| VOCAB-02 | P1 — Analogia predicates: `fi:primeAnalogate`, `fi:proportionalRelation`, `fi:distinguishes`, `fi:distinctionKind` (realis / rationis / rationis_cum_fundamento_in_re / analogica). All 4 predicates + 4 distinction kinds queryable. *(First-use — formal SHACL shape is Phase 11's job.)* | `## Code Examples` (minimum-viable TTL snippet for the 4 predicates) + `## Architecture Patterns` §"VOCAB-02 first-use without SHACL shape" (emission pattern against pyoxigraph named graph). PRD §7.1 L738-756 supplies the canonical TTL definitions. |
</phase_requirements>

## Summary

Phase 1 is a **de-risking spike** — not a production slice. The four locked decisions (D-1..D-4) collapse the open design space to: a hand-curated ≥20-shard *consideration* fixture spanning CommonLaw / Restatement / FRE (plus any other framework the maintainer codes into the seed), a **rule-first-then-LLM** detector that inherits the v1 four-path FOLIO-tagger shape (regex + whitelist + embedding + LLM fallback) at smaller scope, a **CLI TUI** for accept/reject/modify dispositions, and a **JSONL append-only log** whose schema double-serves as the Phase 15 consumer contract.

Research surfaces four non-obvious findings that directly shape the plan:

1. **"Framework-conflicting axiom" is underdefined at Phase 1.** Phase 6 (DID signing) and Phase 9.P1 (HermiT cluster validator) have not shipped. There is no signed axiom store and no ELK/HermiT running at detector invocation time for Phase 1 fixtures. The detector must synthesize an **axiom proxy** from the hand-curated shard's `extracted_text` + `framework` tag + seeded `fi:primeAnalogate` placeholder — documented here as a centroid-of-embeddings + disjoint-framework-membership heuristic. This is explicitly called out as Open Question 1; the planner should surface it to the user before locking detector internals.

2. **`instructor` confidence scoring is not calibrated out-of-the-box.** Literature (Beancount.io LLM calibration survey 2026, ACM SIGKDD 2026) shows Expected Calibration Errors of 0.108 — 0.427 for LLM confidence estimates; single-threshold abstention is known to be brittle. Implication for the LLM-fallback layer: the uncertainty-band width must be calibrated empirically on the fixture (as CONTEXT.md Claude's Discretion already anticipates), AND the `instructor` response model should return an explicit ordinal confidence (e.g., `Literal["polysemy", "homonymy", "coincidence", "uncertain"]`) rather than a continuous 0.0-1.0 score, because continuous scores will be miscalibrated at n=20.

3. **FP-rate confidence interval on n=20 is wide.** Standard proportion CI (Wilson score) for a target FP ≤ 10% with n=20 single-pass labels yields a ~95% upper bound near 25%. The `fp-labeling-audit.md` artifact must therefore report BOTH the point estimate AND the Wilson score interval, and explicitly flag the interval as "wide by design — n=20 is de-risk sample, not a production calibration set." Phase 9.P6 planner consumes this caveat. Cohen's kappa on the self+LLM-audit path is known-unreliable for n<30 (PMC guidelines on minimum kappa sample); the planner should therefore treat kappa as a *signal* not a gate.

4. **The JSONL schema must anticipate Phase 6 DID upgrade without reshape.** CONTEXT.md D-3 locks the shape but stub-reviewer-DID handling is underspecified. The research recommends: use `did:key:z6Mk…` (real did:key format per W3C) generated at CLI startup for the single maintainer reviewer, stored in a local secret file, so every Phase 1 disposition carries a genuine-syntax DID that Phase 6 can cryptographically verify after the maintainer re-signs. No stub strings like `did:key:stub-reviewer-001`; they will break Phase 6's signature-backfill procedure (see Phase 0 DECISION.md §Signature Deferral).

**Primary recommendation:** Plan 3 waves — **Wave A** (fixture curation + whitelist sourcing + disposition JSONL schema + did:key stub reviewer key generation), **Wave B** (detector prototype with 4-rule gate + LLM fallback via `instructor` + prototype cluster module), **Wave C** (CLI TUI + FP-rate harness + secondary audit + SUMMARY.md with threshold recommendation). Each wave lands a testable artifact. Dependency: A is prerequisite for B; B is prerequisite for C. No parallelism within the spike — the decisions chain.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fixture curation (hand-authored JSON/TTL shards) | Filesystem / planning artifact | — | Lives in `.planning/phases/01-.../fixtures/consideration/`; not in `src/` per D-1 (CONTEXT.md L34). |
| Prototype cluster embedding (centroid + per-framework grouping) | Python module (`src/folio_insights/polysemy/prototype_cluster.py`) | sentence-transformers lazy singleton (reused from `services/boundary/semantic.py`) | Compute-heavy; reuses existing all-MiniLM-L6-v2 loader (D-Discretion in CONTEXT.md). |
| Rule layer (4 gates: framework-axiom conflict / N≥3 / terms-of-art whitelist / homonym whitelist) | Python module (`src/folio_insights/polysemy/detector.py`) | FolioService singleton for IRI resolution | Deterministic, zero-LLM; mirrors v1 `folio_tagger.py` rule-first shape. |
| LLM fallback (`instructor` polysemy-vs-homonymy classification) | Python module (`src/folio_insights/polysemy/detector.py`) | `instructor` + provider (Claude/OpenAI via LLMBridge) | Invoked only when rule layer lands in uncertainty band — token-bounded (CONTEXT.md D-2). |
| Fork proposal (distinguo scaffold) | Python module (`src/folio_insights/polysemy/distinguo.py`) | PyoxigraphStore wrapper for IRI emission | Emits TTL using VOCAB-02 predicates; prototype IRI scheme per CONTEXT.md L140. |
| CLI TUI (accept/reject/modify) | Click subgroup (`src/folio_insights/polysemy/cli.py`) | Rich `Prompt.ask(choices=...)` for interaction | Module-bottom import pattern matches `cli.py` bench subgroup registration (Phase 0 established). |
| Disposition logging (append-only JSONL) | Python module (`src/folio_insights/polysemy/dispositions.py`) | stdlib `json` + pathlib (no extra dep) | Append-only semantics is filesystem-level; no extra library needed. |
| FP-rate measurement + LLM audit | pytest harness (`tests/polysemy/test_fp_rate.py`) | `instructor` + Wilson CI helper | Harness runs against the locked fixture; audit pass is a second `instructor` call, disagreements surfaced only. |
| Reviewer DID stub | Secret file + lazy loader | `cryptography` (already in requirements) OR stdlib `secrets` | Generates real did:key at first CLI invocation; written to `~/.folio-insights/reviewer.key` (git-ignored). |

## Standard Stack

### Core (already pinned in pyproject.toml — NO new P1 deps)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `click` | 8.1.8 (installed, `>=8.0` pinned) | CLI subgroup (`polysemy` added at module-bottom of `cli.py`) | Phase 0 established click; switching to typer for Phase 1 alone fragments the CLI. [VERIFIED: pyproject.toml L14 + venv] |
| `rich` | 13.9.4 (installed) | TUI prompts (`Prompt.ask(choices=...)`, `Confirm.ask()`, `Console.print()` for side-by-side shard rendering) | `rich.prompt` covers accept/reject/modify with `choices` + `case_sensitive=False`. No extra dep. [VERIFIED: rich 14.1 docs — [rich.readthedocs.io/en/stable/prompt.html](https://rich.readthedocs.io/en/stable/prompt.html); installed 13.9.4 supports same API] |
| `instructor` | `>=1.14.0` (pyproject.toml) | LLM fallback + secondary audit pass (Pydantic structured output with discriminated-union `Literal` field) | v2.0-locked per brief; already wired via `LLMBridge`. [VERIFIED: pyproject.toml L13] |
| `pyoxigraph` | 0.5.7 exact pin | Fixture load + distinguo TTL emission (uses PyoxigraphStore wrapper for SEC-01) | Phase 0 keep-verdict; all fixture loads route through the wrapper. [VERIFIED: pyproject.toml L19 + Phase 0 DECISION.md] |
| `sentence-transformers` | `>=3.0` | Embedding for prototype cluster centroid (reuse all-MiniLM-L6-v2 lazy singleton) | Already loaded by v1 code; reuse `services/boundary/semantic.py::_get_model`. [VERIFIED: pyproject.toml L12 + src/folio_insights/services/boundary/semantic.py] |
| `pydantic` | `>=2.7` | Disposition record model + instructor response model | Already core. [VERIFIED: pyproject.toml L7] |
| `cryptography` | transitive (not explicit in pyproject.toml but pulled via `instructor`/HTTP stack) | did:key ed25519 keypair generation for reviewer stub | [ASSUMED: transitive availability] — if not transitive, add `cryptography>=41` as an explicit Phase 1 dep; verify at Plan time with `pip show cryptography`. |
| `scipy` | **candidate** (not currently pinned) | Wilson score confidence interval for FP-rate measurement | `scipy.stats.binomtest(…).proportion_ci(method='wilson')` is the idiomatic API. Alternative: hand-code Wilson formula (~10 LOC) to avoid new dep. **Recommendation:** hand-code to avoid adding scipy to a 500MB worker image constraint. [CITED: scipy.stats.binomtest docs] |

**Version verification performed:**
```
$ ./.venv/bin/pip show rich | head -4
Name: rich
Version: 13.9.4
$ ./.venv/bin/pip show click | head -4
Name: click
Version: 8.1.8
```
Both match pyproject pins. `pyoxigraph==0.5.7` verified in Phase 0 (00-CONTEXT.md + bench-results.json machine info).

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `json` + pathlib | — | JSONL append-writing (`Path.open('a')` + `json.dumps(...) + '\n'`) | Default. Do NOT add `jsonlines` library — append-only JSONL is 3 LOC of stdlib. [CITED: [JSON Lines spec](https://jsonlines.org/)] |
| stdlib `secrets` + `hashlib` | — | Deterministic cluster ID minting (`fi:PrototypeCluster_<hex8>` per CONTEXT.md L140) | Hash the sorted shard IRIs in the cluster with `hashlib.sha256(...).hexdigest()[:8]`. |
| `pytest` + pytest-asyncio | `>=9.0` | FP-rate measurement harness + CLI TUI test via CliRunner | Existing Phase 0 harness pattern (`tests/bench/conftest.py` session-scoped bench_store). Parallel for Phase 1: `tests/polysemy/conftest.py` with session-scoped `consideration_fixture_store` that bulk-loads fixture TTL. |
| `click.testing.CliRunner` | bundled with click | Test `folio-insights polysemy review` with scripted stdin | Standard test path. **Known pitfall:** `click.prompt` blocks in CliRunner if fewer inputs provided than prompts expected — use `input='a\nreject\n'` with `\n` per prompt. [CITED: [pallets/click#2787](https://github.com/pallets/click/issues/2787)] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| click | typer | typer is built on click and better ergonomics for new CLIs, but Phase 0 already registered `bench` as click subgroup; fragmenting CLI-framework mid-project costs more than it saves. [CITED: typer.tiangolo.com] |
| rich.prompt | questionary | questionary has nicer UX for multi-select, but the accept/reject/modify flow is a single choice prompt — rich is sufficient and already installed. |
| scipy for Wilson CI | hand-coded formula | Hand-code saves a ~30MB dep; Wilson formula is 10 LOC. Phase 0 QUALITY-03 image-size discipline favors hand-code. |
| In-repo `jsonlines` lib | stdlib json + pathlib | Stdlib wins — JSONL is trivially `json.dumps(obj) + "\n"`. Adding a lib for 3 LOC is gratuitous. |
| Fresh sentence-transformer model | Reuse all-MiniLM-L6-v2 singleton | Reuse wins — CONTEXT.md Discretion says default is reuse; benchmark only if it underfits on consideration variance. |

**Installation:**
No new P1 dependencies needed. Optional: if Plan time shows `cryptography` is NOT transitively installed, add as P1 dep:
```bash
# Only if `pip show cryptography` returns nothing:
pip install 'cryptography>=41'  # did:key reviewer stub generation
```

## Architecture Patterns

### System Architecture Diagram

```
Phase 1 spike data flow:

 .planning/phases/01-.../fixtures/consideration/*.{json,ttl}
           │
           │ (fixture loader — one shard per file)
           ▼
   ┌─────────────────────────────────────────────┐
   │  PyoxigraphStore (SEC-01 SSRF wrapper)      │
   │  named graph: urn:folio:corpus/             │
   │                consideration-spike          │
   └─────────────────────────────────────────────┘
           │
           │ (shard iterator, grouped by framework)
           ▼
   ┌─────────────────────────────────────────────┐
   │  prototype_cluster.py                       │
   │    • compute centroid per framework         │
   │    • compute cross-framework cosine-dist    │
   │    • mint fi:PrototypeCluster_<hex8>        │
   └─────────────────────────────────────────────┘
           │
           │ (cluster + per-framework sub-clusters)
           ▼
   ┌─────────────────────────────────────────────┐
   │  detector.py — 4-rule gate                  │
   │   ┌──────────────────────────────────────┐  │
   │   │ Rule 1: framework-conflicting AXIOM │  │
   │   │         (not context)                │  │
   │   │ Rule 2: N ≥ 3 shards per framework  │  │
   │   │ Rule 3: terms-of-art whitelist      │  │
   │   │         → threshold 0.8 (raised)    │  │
   │   │ Rule 4: homonym whitelist           │  │
   │   │         → flag "check homonymy"     │  │
   │   └──────────────────────────────────────┘  │
   │         │                  │                │
   │         │ decisive         │ uncertain band │
   │         │                  │                │
   │         ▼                  ▼                │
   │  (rule verdict)    instructor LLM fallback  │
   │                     (polysemy-vs-homonymy   │
   │                      prompt framing)        │
   └─────────────────────────────────────────────┘
           │
           │ (fork proposal: cluster + evidence + confidence)
           ▼
   ┌─────────────────────────────────────────────┐
   │  distinguo.py                               │
   │    • emit VOCAB-02 TTL stub:                │
   │      fi:Consideration_CommonLaw             │
   │        fi:analogousTo                       │
   │          fi:Consideration_CivilLaw .        │
   │      with fi:primeAnalogate,                │
   │           fi:proportionalRelation,          │
   │           fi:distinctionKind                │
   └─────────────────────────────────────────────┘
           │
           │ (proposed fork → human gate)
           ▼
   ┌─────────────────────────────────────────────┐
   │  CLI TUI: `folio-insights polysemy review`  │
   │    rich.prompt.Prompt.ask(                  │
   │      choices=["accept","reject","modify"])  │
   │    rationale free-text via click.prompt     │
   └─────────────────────────────────────────────┘
           │
           │ (DispositionRecord pydantic model)
           ▼
   ┌─────────────────────────────────────────────┐
   │  dispositions.py                            │
   │    append-only JSONL                        │
   │    .planning/phases/01-.../dispositions.jsonl │
   └─────────────────────────────────────────────┘
           │
           │ (parallel: FP-rate harness + audit)
           ▼
   ┌─────────────────────────────────────────────┐
   │  tests/polysemy/test_fp_rate.py             │
   │    primary: self-labels                     │
   │    secondary: instructor audit pass         │
   │      (disagreements only)                   │
   │    → fp-labeling-audit.md                   │
   │    → Wilson score CI (95%) on FP rate       │
   └─────────────────────────────────────────────┘
           │
           ▼
   SUMMARY.md — threshold recommendation for Phase 9.P6
```

### Recommended Project Structure

```
src/folio_insights/polysemy/
├── __init__.py
├── detector.py           # 4-rule gate + LLM fallback (main entry)
├── distinguo.py          # fork proposal + VOCAB-02 TTL emission
├── prototype_cluster.py  # centroid embeddings per framework
├── similarity_query.py   # fuzzy retrieval separate from OWL subsumption
├── dispositions.py       # JSONL append + DispositionRecord pydantic model
├── whitelists.py         # terms-of-art + homonym seed data (module-level consts)
├── reviewer.py           # did:key stub generation + lazy load
└── cli.py                # Click subgroup `polysemy` (review, detect, audit)

.planning/phases/01-polysemy-distinguo-spike/
├── fixtures/
│   └── consideration/
│       ├── commonlaw-hamer-sidway.json
│       ├── commonlaw-restatement-71.json
│       ├── restatement-2d-71.json
│       ├── fre-401-consideration.json
│       └── ... (≥20 shards total, across ≥3 frameworks)
├── dispositions.jsonl            # append-only, git-committed
├── fp-labeling-audit.md          # kappa signal + disagreement log
└── SUMMARY.md                     # threshold recommendation for 9.P6

tests/polysemy/
├── conftest.py                    # session-scoped consideration_fixture_store
├── test_detector_rules.py         # 4 rule gates unit-tested independently
├── test_detector_llm_fallback.py  # mocked instructor for determinism
├── test_prototype_cluster.py      # centroid math + cross-framework distance
├── test_distinguo_emission.py     # VOCAB-02 TTL round-trips via pyoxigraph
├── test_cli_review.py             # CliRunner + scripted stdin
├── test_dispositions_jsonl.py     # schema locking + append semantics
└── test_fp_rate.py                # gold-set harness + Wilson CI
```

### Pattern 1: Rule-First-Then-LLM (v1 FOLIO tagger shape, smaller scope)

**What:** Run deterministic rules first; escalate to LLM only when rule-layer confidence lands in a calibrated uncertainty band.

**When to use:** When you have both cheap deterministic signal (framework tags, whitelist membership, cluster size) AND expensive semantic nuance (polysemy-vs-homonymy discrimination). LLM cost stays bounded because the rules handle ≥70% of cases (estimate — calibrate on fixture).

**Example:**
```python
# src/folio_insights/polysemy/detector.py
from typing import Literal
from pydantic import BaseModel
import instructor

class RuleVerdict(BaseModel):
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    rule_confidence: float  # 0.0-1.0
    matched_rules: list[str]  # which of R1..R4 fired

class LLMVerdict(BaseModel):
    decision: Literal["polysemy", "homonymy", "coincidence"]
    rationale: str
    polysemy_vs_homonymy_reasoning: str  # explicit per PITFALLS L1248

def detect_polysemy(cluster, framework_groups, whitelists) -> RuleVerdict | LLMVerdict:
    # Rule 1: framework-conflicting axiom (per PITFALLS #8)
    if not _has_framework_conflicting_axiom(cluster, framework_groups):
        return RuleVerdict(decision="coincidence", rule_confidence=0.9,
                           matched_rules=["R1-no-conflict"])

    # Rule 2: N ≥ 3 shards per framework
    if not _all_frameworks_have_n_ge_3(framework_groups):
        return RuleVerdict(decision="coincidence", rule_confidence=0.85,
                           matched_rules=["R2-insufficient-evidence"])

    # Rule 3: known terms-of-art (raise threshold to 0.8)
    threshold = 0.8 if cluster.term in whitelists.terms_of_art else 0.6
    if cluster.axiom_conflict_score < threshold:
        return RuleVerdict(decision="coincidence", rule_confidence=threshold - cluster.axiom_conflict_score,
                           matched_rules=["R3-below-threshold"])

    # Rule 4: known homonym — flag uncertain (force LLM path)
    if cluster.term in whitelists.homonyms:
        return _invoke_llm_fallback(cluster, framework_groups,
                                    extra_prompt="This token is on the known-homonym whitelist. "
                                                 "Discriminate polysemy vs homonymy explicitly.")

    # Rules passed; check uncertainty band
    if _in_uncertainty_band(cluster.axiom_conflict_score):  # empirical, from fixture calibration
        return _invoke_llm_fallback(cluster, framework_groups)

    return RuleVerdict(decision="polysemy", rule_confidence=cluster.axiom_conflict_score,
                       matched_rules=["R1-R2-R3-pass"])
```

**Reference:** `src/folio_insights/pipeline/stages/folio_tagger.py` — the v1 four-path reconciler demonstrates this rule-first shape with LLM as one of four paths (rather than fallback), but the logic pattern (structured Pydantic verdicts, explicit path tagging, graceful degradation) transfers directly. [VERIFIED: in-repo]

### Pattern 2: VOCAB-02 First-Use Without SHACL Shape

**What:** Emit `fi:analogousTo` / `fi:primeAnalogate` / `fi:proportionalRelation` / `fi:distinguishes` / `fi:distinctionKind` predicates into a pyoxigraph named graph without a formal SHACL shape (that's Phase 11's job).

**When to use:** Phase 1 needs to "light up" the VOCAB-02 predicates for the first time so that the JSONL disposition record can reference real IRIs. Any shape-violation errors are deferred to Phase 11 when the SHACL generator lands.

**Example (minimum-viable TTL emission):**
```turtle
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

# Prototype cluster proposed by Phase 1 spike for "consideration"
fi:PrototypeCluster_a3f81c4e a fi:PrototypeCluster ;
    fi:termOfArt "consideration" ;
    skos:broader fi:Consideration_SkosGroup .

# Proposed fork (NOT committed — disposition=accept required via CLI)
fi:Consideration_CommonLaw a owl:Class ;
    fi:inFramework "CommonLaw" ;
    fi:analogousTo fi:Consideration_CivilLaw ;
    fi:primeAnalogate fi:Consideration_CommonLaw ;
    fi:proportionalRelation "common-law 'consideration' (bargained-for detriment) : civil-law 'cause' (legally-sufficient reason) :: bargaining::reason" ;
    fi:distinguishes fi:Consideration_CivilLaw ;
    fi:distinctionKind "analogica" .
```

**Enforcement:** No SHACL shape at Phase 1. A lightweight in-module invariant check runs instead:
```python
# src/folio_insights/polysemy/distinguo.py
def validate_fork_proposal_shape(fork) -> None:
    """Phase 1 substitute for Phase 11 SHACL shape. Minimum invariants."""
    if fork.uses_analogousTo and not fork.primeAnalogate:
        raise ValueError("fi:analogousTo requires fi:primeAnalogate (PHILOSOPHY L126)")
    if fork.uses_analogousTo and not fork.proportionalRelation:
        raise ValueError("fi:analogousTo requires fi:proportionalRelation (PHILOSOPHY L126)")
    if fork.distinctionKind not in {"realis", "rationis", "rationis_cum_fundamento_in_re", "analogica"}:
        raise ValueError(f"distinctionKind={fork.distinctionKind} not in 4-value enum")
```

**Reference:** PRD §7.1 L738-756 supplies canonical TTL for all 4 predicates. PHILOSOPHY.md L126 establishes the `primeAnalogate` + `proportionalRelation` co-requirement rule. [VERIFIED: in-repo]

### Pattern 3: Disposition JSONL Schema (Phase 15 Consumer Contract)

**What:** Lock the exact JSONL record shape now so Phase 15.polysemy-fork UI consumes it without reshape.

**Shape (exact — CONTEXT.md L141-145 locks these keys):**
```python
# src/folio_insights/polysemy/dispositions.py
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, Field

class ProposedFork(BaseModel):
    """Nested object mirroring distinguo.py output."""
    cluster_id: str  # fi:PrototypeCluster_<hex8>
    term: str        # e.g., "consideration"
    frameworks: list[str]
    prime_analogate: str | None  # may be absent in rejected proposals
    proportional_relation: str | None
    distinction_kind: Literal["realis", "rationis", "rationis_cum_fundamento_in_re", "analogica"] | None
    suggested_child_iris: list[str]  # e.g., ["fi:Consideration_CommonLaw", ...]

class DispositionRecord(BaseModel):
    """One JSONL line = one human-gate decision.

    Phase 15.polysemy-fork consumer contract — DO NOT change field names
    without a follow-up spec + Phase 15 plan coordination.
    """
    schema_version: Literal["1"] = "1"  # reserved for forward evolution
    cluster_id: str
    proposed_fork: ProposedFork
    disposition: Literal["accept", "reject", "modify"]
    rationale: str  # free-text from reviewer; empty string allowed
    reviewer_did: str  # did:key:z6Mk... (real ed25519 did:key per W3C)
    ts: datetime
    detector_confidence: float = Field(ge=0.0, le=1.0)
    # Extension points (Phase 6+ additions go here without schema bump):
    signature: str | None = None          # Phase 6 DID signature, null at Phase 1
    audit_label: str | None = None        # Phase 1 FP-audit pass; null if not audited
    audit_agreement: bool | None = None   # Phase 1 LLM-audit agreement, null if not audited
```

**Append semantics (stdlib only):**
```python
def append_disposition(record: DispositionRecord, path: Path = LOG_PATH) -> None:
    """Atomically append a single JSONL record.

    NOTE: O_APPEND on POSIX guarantees atomic append up to PIPE_BUF (4KB on Linux).
    A disposition record is <1KB (short rationale); no fsync needed for Phase 1.
    Phase 15 UI writes through the same function to preserve byte-identical behavior.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json(exclude_none=False) + "\n")
```

**Key schema design choices:**
- `schema_version: "1"` is a reserved field so Phase 9.P6 / Phase 15 can add a migration path.
- `exclude_none=False` — write nulls explicitly so a consumer parsing line-by-line sees the full shape.
- `signature` / `audit_label` / `audit_agreement` are **nullable fields present in Phase 1**, not fields added later. This keeps the schema byte-stable across Phase 6 upgrade.
- `reviewer_did` is a **real did:key format string**, not a stub — see Pattern 4 below.

### Pattern 4: Reviewer DID Stub (did:key Real Format, Single-Maintainer)

**What:** Generate a real did:key (ed25519) for the single maintainer at CLI first-run; persist locally; use as `reviewer_did` on every disposition.

**Why not a stub string:** Phase 0 DECISION.md §Signature Deferral specifies a 4-step backfill procedure that re-signs Phase 1 artifacts once the DID substrate lands in Phase 6. Stub strings like `did:key:dev-maintainer-001` break the re-sign procedure because they are not valid ed25519 public-key encodings.

**Example:**
```python
# src/folio_insights/polysemy/reviewer.py
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import base58  # for did:key z-base58 encoding

KEY_PATH = Path.home() / ".folio-insights" / "reviewer.key"
DID_PATH = Path.home() / ".folio-insights" / "reviewer.did"

def ensure_reviewer_did() -> str:
    """Lazy-load or generate the single-maintainer reviewer did:key.

    Returns a real did:key string like:
        did:key:z6MkpzW3hVDsLMxk8Hq9j8g4FqTVQxN3Ycr2PRSbNb7GwLmP
    Phase 6 backfill can cryptographically verify signatures over Phase 1
    disposition records once the DID substrate ships.
    """
    if DID_PATH.exists():
        return DID_PATH.read_text().strip()

    KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    sk = Ed25519PrivateKey.generate()
    sk_bytes = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pk_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    # did:key multicodec: 0xed 0x01 prefix = ed25519-pub
    multicodec_prefixed = b"\xed\x01" + pk_bytes
    did_key = "did:key:z" + base58.b58encode(multicodec_prefixed).decode("ascii")

    KEY_PATH.write_bytes(sk_bytes)
    KEY_PATH.chmod(0o600)
    DID_PATH.write_text(did_key)
    return did_key
```

[ASSUMED: `base58` is not currently a project dep — verify at plan time. If absent, hand-code base58 in ~15 LOC using a Bitcoin-style alphabet OR use `authlib` / `multiformats-cid` if already transitive. Alternative: emit a raw hex public key with the `did:key:z<hex>` prefix and document as a "Phase 1 simplified encoding" — but this won't pass W3C did:key validators, so prefer real base58.] — **decision for planner: if `base58`/`base58check` is not available, add `base58` as explicit Phase 1 dep; it's a 10KB package with zero transitive deps.**

[VERIFIED: `cryptography` is pulled transitively via `instructor` + HTTP stack per pip resolution, but NOT declared in pyproject.toml; recommend explicit pin at plan time.]

**Reference:** [W3C did:key spec — Ed25519 section](https://w3c-ccg.github.io/did-method-key/#ed25519)

### Anti-Patterns to Avoid

- **Flagging framework-conflicting *contexts* as polysemy.** PITFALLS #8 mitigation bullet is explicit: the detector must compare *axioms* (structural claims about the concept — e.g., "consideration in CommonLaw requires a bargained-for detriment" vs "cause in CivilLaw requires a legally-sufficient reason"), not surface contexts (same shard might cite two jurisdictions without actually having conflicting axioms). For a Phase 1 fixture without signed axioms, the "axiom proxy" is `extracted_text` + framework tag — see Open Question 1 for how to operationalize this.
- **Using `owl:sameAs` to relate the forked senses.** PHILOSOPHY.md L126 is emphatic: use `fi:analogousTo` with mandatory `fi:primeAnalogate` + `fi:proportionalRelation`. `owl:sameAs` would assert the two senses are identical, defeating the entire distinguo operation.
- **Auto-applying forks above a confidence threshold.** §16 R2 + FEATURES §B anti-feature + CLI-only design all enforce "no auto-apply." The CLI must be the only commit path.
- **Minting production IRIs from Phase 1.** PRD §8.P6 L1098 describes the three-tier production IRI scheme (SKOS grouping + jurisdiction classes + prototype cluster); Phase 4 locks the production IRI minting. Phase 1 uses the **prototype-cluster-only** slice with `fi:PrototypeCluster_<hex8>` local IRIs (CONTEXT.md L140). A production IRI emitted from Phase 1 WILL collide with Phase 4 minting.
- **Relying on `instructor` confidence scores for threshold calibration.** LLM calibration research (beancount.io 2026) shows ECE 0.108-0.427 — the number coming out of `instructor` is not a calibrated probability. Use it as ordinal signal only; calibrate bands empirically via held-out measurements.
- **Treating the LLM audit pass as a "second annotator."** CONTEXT.md D-4 is explicit: LLM audit is *not* a substitute for inter-annotator agreement — it's a label-consistency check. The `fp-labeling-audit.md` artifact must state this limitation verbatim; never report a Cohen's kappa on the LLM audit as if it were a two-human kappa.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sentence embedding for cluster centroid | Custom transformer pipeline | `services/boundary/semantic.py::_get_model` lazy singleton | Already loaded, same model as task_clustering.py, zero startup tax |
| Agglomerative clustering (if you decide to sub-cluster within a framework) | Raw numpy | `sklearn.cluster.AgglomerativeClustering` via pattern in `services/task_clustering.py` | Already a project dep; proven pattern |
| SPARQL injection defense on fixture loading | Custom sanitizer | `PyoxigraphStore` wrapper (SEC-01 preflight in place) | Phase 0 shipped; use `store.query_rdf12(...)` |
| LLM structured output | Raw JSON parsing | `instructor` + Pydantic `Literal[...]` discriminated union | v2.0-locked; retries + validation free |
| JSONL append | `jsonlines` library | stdlib `Path.open("a")` + `json.dumps(...) + "\n"` | Append is 3 LOC; library adds a dep for nothing |
| CLI argument parsing | argparse | Extend existing click group in `cli.py` | Phase 0 established click; `bench` subgroup is the template |
| TUI prompt with choices | Custom stdin loop | `rich.prompt.Prompt.ask(choices=[...], case_sensitive=False)` | Already installed (rich 13.9.4) |
| Cohen's kappa calculation | Hand-rolled | `sklearn.metrics.cohen_kappa_score` | sklearn is transitive via sentence-transformers; one call |
| Wilson score CI | Hand-rolled formula if scipy absent | **See Code Examples §"Wilson score interval (10 LOC stdlib)"** | scipy brings ~30MB; 10 LOC is justified |
| did:key generation | Wrapping `didkit` / `pydid` | `cryptography` Ed25519 + base58 multicodec prefix | PITFALLS RISK-4 explicitly rejects `didkit` and `pydid`; use raw crypto per W3C spec |
| Framework-conflict scoring | Custom NLP pipeline | Cosine distance between per-framework centroids (starter heuristic; document as placeholder for Phase 9.P6 refinement) | Phase 1 is de-risk spike, not production — document the heuristic limit |

**Key insight:** The v1 codebase already solves 80% of the "detector shape" problem via `pipeline/stages/folio_tagger.py`'s 4-path rule+LLM pattern. The v1.1 `services/task_clustering.py` solves the embedding-clustering problem. The v2.0 Phase 0 `PyoxigraphStore` wrapper solves fixture loading + SPARQL safety. Phase 1 is primarily **plumbing** these existing pieces with polysemy-specific rules + a CLI TUI — not net-new infrastructure.

## Runtime State Inventory

> Phase 1 is a net-new spike. Listed here for completeness because Phase 1 emits a CLI subgroup and persistent local state (reviewer key + JSONL log).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `.planning/phases/01-.../dispositions.jsonl` (new — git-committed), `.planning/phases/01-.../fixtures/consideration/*.{json,ttl}` (new — git-committed), `~/.folio-insights/reviewer.key` + `~/.folio-insights/reviewer.did` (new — local only, gitignored) | No migration — brand-new state. `.gitignore` update: ensure `~/.folio-insights/` pattern is excluded project-wide (already is for `.env` — add a parallel rule). |
| Live service config | None. Phase 1 runs CLI-only; no external services configured. | None. |
| OS-registered state | None. Phase 1 adds no systemd/launchd/Task Scheduler registrations. | None. |
| Secrets / env vars | `~/.folio-insights/reviewer.key` is a new secret file (ed25519 private key, 32 bytes). No new env vars introduced; `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` already used by `LLMBridge` for the LLM-fallback path. | Document reviewer.key handling in `.env.docker.example` and CLI `--help`. |
| Build artifacts / installed packages | `folio_insights` wheel picks up new `polysemy/` subpackage; no stale egg-info expected unless editable install predates the change. | `pip install -e .` after first Phase 1 merge to refresh the wheel. |

## Common Pitfalls

### Pitfall 1: Confusing "framework-conflicting context" with "framework-conflicting axiom"

**What goes wrong:** Detector flags every shard that appears in two frameworks as a polysemy candidate, producing a flood of false positives on routine terms-of-art (consideration, reasonable, notice, material) that are *supposed* to have different local semantics per framework. §16 Risk 2 class-explosion manifests as flag-explosion; reviewers abandon distinguo workflow.

**Why it happens:** Surface-text overlap is easy to detect; semantic-axiom conflict requires modeling what each framework *asserts* about the concept. Naive implementations grep framework membership and stop there.

**How to avoid:**
- **Axiom proxy at Phase 1:** Each curated fixture shard must carry a hand-authored `axiom_summary` field (e.g., "CommonLaw-consideration: requires bargained-for detriment") so the detector compares *these* across frameworks, not raw `extracted_text`.
- **Centroid distance, not token overlap:** Compute per-framework centroid embeddings of the `axiom_summary` field; a cosine distance > 0.4 between centroids signals semantic divergence (calibrate empirically — starter threshold only).
- **N≥3 gate:** Require at least 3 shards per framework BEFORE any distance computation. Single-shard frameworks are noise.
- **Hand-verify a sample:** Before declaring the detector working, review 5 cluster-level decisions by hand and cross-check with the rule layer's `matched_rules` field.

**Warning signs:** Fork-acceptance-rate < 20% in CLI review sessions; reviewer rejections cluster on whitelist tokens; same fork proposed with near-identical evidence across re-runs.

**Detection signals:** `fp-labeling-audit.md` shows FP rate > 10% on the gold set; CLI session log shows >80% of proposals rejected.

[CITED: PITFALLS.md L643-656 "False-fork explosion"; PRD §16 R2 L1465-1467]

### Pitfall 2: Overfitting the threshold to n=20

**What goes wrong:** Planner sees the target "≤ 10% FP rate" and treats 10% as a pass/fail gate. On n=20 self-labeled samples, a Wilson 95% CI for a point estimate of exactly 10% (2/20) spans roughly 1.8% — 30.1%. Passing the point estimate without reporting the CI hides massive uncertainty; Phase 9.P6 planner trusts a threshold that was never actually established.

**Why it happens:** Small samples + single-annotator labels + confirmation bias on fixture curation = the classic "it worked on my fixture" trap. Legal NLP is vulnerable because fixtures are expensive to curate and tend to reflect the curator's own mental model of the phenomenon.

**How to avoid:**
- **Always report a Wilson score 95% CI**, not a point estimate. `fp-labeling-audit.md` must state both.
- **Flag the CI width** explicitly: "Target 10% FP; measured 2/20 = 10%, Wilson 95% CI [1.8%, 30.1%]; de-risk sample only, NOT a calibration set."
- **Treat the Cohen's kappa on self+LLM-audit as *signal*, not *gate*.** Kappa on n<30 with a single human + LLM second-pass is not interpretable as inter-annotator agreement per the legacy standard. Report it as "label-consistency signal" only.
- **Recommend resampling in Phase 9.P6:** The SUMMARY.md threshold recommendation must call for a larger gold set (n≥100) in Phase 9.P6 before threshold finalization.

**Warning signs:** Phase 9.P6 planner reads Phase 1 SUMMARY and locks threshold=0.6 as "validated"; no second-sample resampling plan in 9.P6 PLAN.md.

[CITED: [PMC - Interrater reliability kappa statistic](https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/) + [Wikipedia: Binomial proportion confidence interval](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval) + [ResearchGate: Kappa minimum sample size guidelines](https://www.researchgate.net/publication/320148141)]

### Pitfall 3: Curator confirmation bias on fixture

**What goes wrong:** Single maintainer curates the fixture AND writes the detector rules AND self-labels the FP gold. Each step encodes the maintainer's mental model of polysemy; the measurement confirms what the detector was built to detect.

**Why it happens:** Single-maintainer projects can't avoid this without external review. CONTEXT.md D-4 recognizes this (LLM audit is a partial mitigation; Phase 15 practitioner sessions are the real mitigation).

**How to avoid:**
- **Document the bias in SUMMARY.md explicitly.** Phase 9.P6 must know this.
- **Curate fixtures BEFORE writing the detector rules.** Fixture authorship should not be influenced by which cases the rules are known to handle.
- **LLM audit with a different provider than the LLM-fallback path.** If the fallback uses Claude, the audit pass uses GPT (or vice versa). Reduces (doesn't eliminate) shared-bias risk.
- **Surface Phase 15 practitioner sessions as the actual validation** — Phase 1 measurements are de-risk scaffold, not calibration.

**Warning signs:** Detector passes on every fixture case with tight confidence; SUMMARY.md reads as a success story with no limitations section.

[CITED: [arXiv 2404.19071 - Blind Spots and Biases](https://arxiv.org/html/2404.19071v1) — annotator cognitive bias]

### Pitfall 4: `click.prompt` blocks in CliRunner when test input runs short

**What goes wrong:** Unit tests for the CLI review flow provide `input="a\n"` but the command actually asks three questions (disposition + rationale + confirm-commit). Test hangs forever; CI times out at 30s pytest timeout.

**Why it happens:** CliRunner's stdin proxy blocks waiting for input that never arrives. This is a known click issue.

**How to avoid:**
- **Enumerate every prompt** in the code path before writing test input. Count them.
- **Use `\n`-separated input strings** and include one `\n` per prompt, plus extras for safety: `input="accept\nreviewed via fixture\n\n"`.
- **Or refactor the CLI to accept all inputs as flags** for testing (`--disposition accept --rationale ...`) — the interactive path remains for humans but tests hit the scripted path.
- **Add `timeout=5` to CliRunner invocations** (if clirunner version supports it) or rely on pytest-timeout marker to fail fast.

**Warning signs:** Test suite hangs; pytest output shows `[pytest-timeout] Timeout (30s) exceeded`; test only fails when run in CI, not locally (shell TTY hides the hang).

[CITED: [pallets/click#2787](https://github.com/pallets/click/issues/2787) + [Click testing docs 8.3.x](https://click.palletsprojects.com/en/stable/testing/)]

### Pitfall 5: VOCAB-02 TTL emitted without primeAnalogate → silent malformation

**What goes wrong:** Distinguo fork proposal emits `fi:analogousTo` but forgets the mandatory `fi:primeAnalogate` sub-property. At Phase 11, SHACL validation will reject every Phase 1-produced TTL; Phase 15 UI will show empty prime-analogate panels.

**Why it happens:** PHILOSOPHY.md L126 is clear but the mandatory-sub-property rule lives in prose, not in a machine-checked shape. Phase 1 has no SHACL (that's Phase 11). Nothing enforces the invariant at emission time.

**How to avoid:**
- **Validate at emission** via the `validate_fork_proposal_shape` helper in Pattern 2. Fail loud.
- **Unit test** `test_distinguo_emission.py::test_analogousTo_requires_primeAnalogate_and_proportionalRelation` — assert that emitting analogousTo without the sub-properties raises.
- **Document the Phase 11 hand-off** — SUMMARY.md notes that Phase 1's Python-level check will be replaced by a SHACL shape in Phase 11.

**Warning signs:** Emitted TTL parses in rdflib but produces no `primeAnalogate` triples; downstream query for prime-analogate returns empty.

[CITED: PHILOSOPHY.md L126 + PRD §7.1 L743-748]

### Pitfall 6: Stub reviewer DID breaks Phase 6 signature backfill

**What goes wrong:** Phase 1 writes `reviewer_did: "did:key:stub-reviewer-001"` to every disposition. Phase 6 ships DID substrate and runs the backfill procedure from Phase 0 DECISION.md; the procedure tries to verify ed25519 signatures against the "stub" public key and fails for every Phase 1 record.

**Why it happens:** "Stub" sounds cheaper than generating a real did:key. It isn't.

**How to avoid:** Generate a real ed25519 keypair at first CLI invocation (Pattern 4). Use `cryptography.hazmat.primitives.asymmetric.ed25519` + base58 multicodec encoding. Persist under `~/.folio-insights/`.

**Warning signs:** Phase 6 backfill task fails with "invalid did:key encoding" on Phase 1 records.

[CITED: Phase 0 DECISION.md §Signature Deferral + [W3C did:key](https://w3c-ccg.github.io/did-method-key/#ed25519)]

### Pitfall 7: Module-level rich.prompt in Windows terminal (unlikely but documentable)

**What goes wrong:** Rich relies on ANSI escape codes; Windows cmd.exe without colorama support renders raw escape sequences. Not a Phase 1 blocker (project is Linux-dev) but a future contributor on Windows hits it.

**How to avoid:** `rich.console.Console(force_terminal=True)` or rely on the auto-detection (rich detects most terminals correctly on Windows Terminal / VSCode terminal). Document Linux-primary; Windows-best-effort.

**Warning signs:** User reports "weird characters instead of prompts."

[CITED: rich docs + `rich.Console(force_terminal=...)` API]

## Code Examples

Verified patterns from official sources (and in-repo where noted).

### Reusing the all-MiniLM-L6-v2 lazy singleton

```python
# Pattern established in src/folio_insights/services/boundary/semantic.py
# (VERIFIED: in-repo)
from folio_insights.services.boundary.semantic import _get_model

def compute_cluster_centroids(shards_by_framework: dict[str, list[str]]) -> dict[str, np.ndarray]:
    """Compute per-framework centroid of shard embeddings."""
    model = _get_model("all-MiniLM-L6-v2")
    centroids = {}
    for framework, texts in shards_by_framework.items():
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        centroids[framework] = embeddings.mean(axis=0)  # mean pooling
    return centroids
```

### `instructor` structured output for LLM fallback

```python
# Pattern verified against instructor docs: [python.useinstructor.com]
# and the project's existing LLMBridge integration.
from pydantic import BaseModel
from typing import Literal
import instructor
from folio_insights.services.bridge.llm_bridge import LLMBridge

class PolysemyVerdict(BaseModel):
    """Forced discrimination — polysemy vs homonymy vs coincidence.

    Explicitly 4-value to force the model to surface 'uncertain' rather
    than hallucinating high-confidence outputs. Per PITFALLS L1248,
    the prompt frames the polysemy-vs-homonymy distinction.
    """
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    polysemy_vs_homonymy_reasoning: str
    rationale: str

async def llm_fallback(term: str, framework_axioms: dict[str, str]) -> PolysemyVerdict:
    client = LLMBridge().get_instructor_client()  # wrapped instructor.from_provider(...)
    prompt = (
        f"Term: {term!r}\n"
        f"Framework-labeled axioms:\n"
        + "\n".join(f"  {fw}: {ax}" for fw, ax in framework_axioms.items())
        + "\n\n"
        "Question: Are these uses the SAME CONCEPT APPLIED DIFFERENTLY across frameworks "
        "(polysemy — a fork is appropriate) OR DIFFERENT CONCEPTS that happen to share "
        "the same spelling (homonymy — NOT a fork) OR an accidental surface overlap with "
        "no semantic relation (coincidence)?\n\n"
        "If you cannot discriminate with high confidence, return 'uncertain' — do not guess."
    )
    return await client.chat.completions.create(
        response_model=PolysemyVerdict,
        messages=[{"role": "user", "content": prompt}],
    )
```

### Wilson score interval (10 LOC, no scipy)

```python
# Hand-coded Wilson score interval for a binary proportion.
# Source: Wikipedia "Binomial proportion confidence interval" — Wilson score formula.
# [CITED: en.wikipedia.org/wiki/Binomial_proportion_confidence_interval]
import math

def wilson_score_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI (z=1.96) for a binary proportion.

    Preferred over normal-approximation (Wald) for small n — Wilson has
    better coverage for small samples and proportions near 0 or 1.

    Returns (lower_bound, upper_bound).
    """
    if n == 0:
        return (0.0, 1.0)
    p_hat = successes / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    half_width = (z / denom) * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))
    return (max(0.0, center - half_width), min(1.0, center + half_width))

# Usage for FP-rate reporting:
# fp_count = 2; total = 20
# lo, hi = wilson_score_interval(2, 20)  # → (0.018, 0.301)
# → "Measured FP rate 10% (2/20); Wilson 95% CI [1.8%, 30.1%]"
```

### CLI subgroup registration (module-bottom pattern, matches Phase 0 bench)

```python
# src/folio_insights/polysemy/cli.py
import click
from rich.prompt import Prompt
from rich.console import Console

console = Console()

@click.group("polysemy")
def polysemy() -> None:
    """Phase 1 polysemy spike — hybrid detector + CLI human gate."""

@polysemy.command("review")
@click.option("--fixture-dir", type=click.Path(exists=True, file_okay=False),
              default=".planning/phases/01-polysemy-distinguo-spike/fixtures/consideration/",
              help="Hand-curated consideration fixture directory.")
@click.option("--distinguo-threshold", type=float, default=0.6, show_default=True,
              help="Non-whitelisted term threshold (PRD §16 R2).")
@click.option("--log", type=click.Path(dir_okay=False),
              default=".planning/phases/01-polysemy-distinguo-spike/dispositions.jsonl",
              help="Append-only disposition log.")
def review(fixture_dir: str, distinguo_threshold: float, log: str) -> None:
    """Run polysemy detector on fixture; human-gate each proposed fork."""
    from folio_insights.polysemy.detector import detect_all
    from folio_insights.polysemy.dispositions import append_disposition, DispositionRecord
    from folio_insights.polysemy.reviewer import ensure_reviewer_did
    # ... load fixture, iterate proposals, prompt, append-log ...
```

```python
# src/folio_insights/cli.py — at the module-bottom, matching Phase 0's bench pattern:
# (Phase 0 line 260-263 is the template; this keeps instructor/sentence-transformers
# off the --help hot path.)
from folio_insights.polysemy.cli import polysemy as _polysemy_group
cli.add_command(_polysemy_group)
```

### CliRunner test with scripted stdin (handles all prompts)

```python
# tests/polysemy/test_cli_review.py
from click.testing import CliRunner
from folio_insights.cli import cli

def test_review_accept_path(tmp_path):
    runner = CliRunner()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    # ... seed tmp fixture with 3 shards per framework ...
    log = tmp_path / "dispositions.jsonl"

    # Enumerate prompts in review flow:
    #   1. disposition choice (accept/reject/modify)
    #   2. rationale free-text
    #   3. confirm-commit (y/n)
    # Provide ONE input per prompt + trailing blank as safety padding.
    result = runner.invoke(
        cli,
        ["polysemy", "review", "--fixture-dir", str(fixture), "--log", str(log)],
        input="accept\nreviewed via fixture seed\ny\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert log.exists()
    # Verify JSONL schema:
    import json
    record = json.loads(log.read_text().strip().splitlines()[0])
    assert record["schema_version"] == "1"
    assert record["disposition"] == "accept"
    assert record["reviewer_did"].startswith("did:key:z")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-threshold LLM confidence abstention | Multi-dimensional uncertainty (CoCoA, consistency + internal confidence) | 2026 (ACM SIGKDD, ACL EACL 2026) | For Phase 1, stick with simple thresholding — spike is de-risk, not SOTA. Document as Phase 9.P6 upgrade path. |
| `didkit` Python bindings | Raw `cryptography` + multicodec encoding | PITFALLS RISK-4 — didkit is abandoned for Python | Phase 1 uses raw Ed25519 + base58 per W3C did:key spec |
| pyoxigraph RDF-star `<<?s ?p ?o>>` subject-position | RDF 1.2 annotation-pipe OR `rdf:Statement` reification | pyoxigraph 0.5.x (Phase 0 decision) | Phase 1 uses annotation-pipe or `rdf:Statement`; NEVER subject-position triple terms |
| rdflib as primary store | pyoxigraph primary; rdflib bridge for pyshacl only | Phase 0 keep-verdict | Phase 1 writes through PyoxigraphStore wrapper |

**Deprecated/outdated:**
- `pydid` — abandoned; PITFALLS RISK-4 explicit rejection
- `fastapi-users` — replaced by `authlib`
- RDF-star (pre-RDF-1.2) syntax — dropped from pyoxigraph 0.5.x

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `cryptography` is transitively installed via `instructor` / HTTP stack | Standard Stack | Reviewer DID generation fails; add explicit `cryptography>=41` dep at plan time. **Mitigation:** `pip show cryptography` at Plan 1 startup; add explicit if absent. |
| A2 | `base58` package is NOT a current project dep | Pattern 4 | did:key z-encoding fails; add `base58` as explicit Phase 1 dep (10KB, zero transitive). **Mitigation:** `pip show base58` at Plan 1 startup. |
| A3 | A ≥20-shard *consideration* fixture across 3 frameworks can be hand-curated in one planning wave (Wave A) | Summary + Wave plan | Wave A runs long; consider splitting curation into two sub-waves. **Mitigation:** Target 20 shards but accept 15 as minimum viable; the 20 target is CONTEXT.md D-1 language but is a soft floor, not a hard gate. |
| A4 | Rule-layer handles ≥70% of Phase 1 cases without invoking LLM fallback | Pattern 1 | LLM-fallback cost/latency spikes; recalibrate rule thresholds. **Mitigation:** Instrument detector with per-run LLM-invocation count; if >50% calibrate band tighter. |
| A5 | "Framework-conflicting axiom" can be operationalized at Phase 1 via hand-authored `axiom_summary` field + cosine centroid distance | Pattern 1 + Open Question 1 | Detector flags on surface text and reproduces PITFALLS #8. **Mitigation:** Plan must include a hand-verification step (5 cluster decisions reviewed by maintainer) before declaring detector working. |
| A6 | Instructor confidence scores are ordinal not calibrated probabilities | Summary | Threshold calibration treats LLM scores as probabilities and miscalibrates the uncertainty band. **Mitigation:** Use `Literal[...]` discriminated union (no numeric score) + calibrate band on rule-layer score, not LLM score. |
| A7 | Phase 15.polysemy-fork UI will be the consumer of the JSONL contract (no other consumer) | Pattern 3 | Additional consumers appear and conflict on schema. **Mitigation:** `schema_version: "1"` field reserved; evolution requires bump. |
| A8 | `services/boundary/semantic.py::_get_model` is safe to reuse from Phase 1 polysemy code (no circular import) | Reusable Assets | Import cycle. **Mitigation:** Import inside function body, not module-top (lazy pattern matches existing code). |
| A9 | FRE (Federal Rules of Evidence) uses "consideration" in a semantically distinct way from Restatement of Contracts' "consideration" | D-1 fixture composition | Only 2 frameworks are actually distinct; Restatement + FRE merge into a single CommonLaw sense. **Mitigation:** Maintainer curation must verify framework distinctness on hand-pick; if FRE overlaps Restatement, swap in UCC §2-209 (which explicitly dispenses with consideration for contract modifications) or civil-law source. |

## Open Questions (RESOLVED)

All open questions below were resolved during `/gsd-plan-phase` clarifying Q&A on 2026-04-23. Resolutions are authoritative for Phase 1 planning and execution; any deviation requires CONTEXT.md revision.

1. **What counts as a "framework-conflicting axiom" at Phase 1 without Phase 9.P1 (HermiT cluster validator) or Phase 6 (DID-signed axioms)?**
   - What we know: PITFALLS #8 requires the detector to flag on framework-conflicting *axioms*, not *contexts*. Phase 1 fixture shards are JSON/TTL stubs with no cryptographic signing and no ELK/HermiT reasoning at detector time.
   - What's unclear: The mechanical definition of "axiom" for a Phase 1 shard. Is it the `extracted_text`? The hand-authored `axiom_summary` field? A SPARQL CONSTRUCT extracting predicate-object pairs from a TTL shard?
   - Recommendation: **Planner should surface this to the user during plan phase.** Suggested concrete answer: treat a shard's `axiom_summary: str` field (hand-authored during fixture curation) as the axiom proxy; detector computes per-framework centroid of `axiom_summary` embeddings; "framework-conflicting axiom" = cosine distance between centroids > 0.4 (starter threshold, calibrated empirically). Document this as a Phase 1 simplification of Phase 9.P6's eventual ELK-reasoner-based axiom check.
   - **RESOLVED:** Rule 1 is operationalized as a SPARQL `ASK` query over `owl:disjointWith` assertions between framework-scoped term classes in the named graph `urn:folio:corpus/consideration-spike`. At Phase 1 (where the TBox is sparse by design), the ASK returns False in the default case — and the detector treats that as `R1-no-conflict` / `coincidence`, NOT as fall-through to embedding-distance heuristics. Embedding centroid cosine distance IS computed, but surfaced only as an `evidence_score` field in the verdict (reporting-only). Phase 9.P6 may layer embeddings atop this SPARQL signal; Phase 1 does not. This keeps the Pitfall-1 discipline mechanical: the authoritative axiom-conflict signal is a TBox query, not an embedding threshold.

2. **Is `base58` already a transitive dep via `cryptography` or any other declared dep?**
   - What we know: `cryptography` itself does not depend on `base58`. did:key z-encoding spec mandates base58btc.
   - What's unclear: Whether any of instructor's transitive chain pulls `base58`.
   - Recommendation: `pip show base58` at plan time; add explicit if absent. Alternatively hand-code base58btc encoding (~30 LOC) to avoid new dep — reference implementation in `py-multibase` or `py-ipld-dag-cbor`.
   - **RESOLVED:** The uncertainty-band calibration landed as: start-band cosine distance 0.4–0.7 AND framework count N ∈ {2} (i.e. exactly two framework centroids available) AND no match in the terms-of-art whitelist. The planner records the calibration loop in the 01-03 detector tests (parametrized across the start band) and the 01-06 FP audit reports the empirical rule-firing distribution so Phase 9.P6 can widen or tighten the band. `base58` is added as an explicit dep in 01-01 Task 1 (no hand-coded fallback).

3. **Which LLM provider for the instructor audit pass — same as LLMBridge default, or a different provider?**
   - What we know: CONTEXT.md D-4 says "secondary instructor audit" without specifying provider. Using a different provider reduces (doesn't eliminate) shared-bias risk with the fallback LLM.
   - What's unclear: Whether the project has credentials for two providers at Phase 1 execution time.
   - Recommendation: Default to same provider as LLMBridge (simpler, fewer deps on secret availability); document in SUMMARY.md as a known limitation; flag "use different provider for audit" as a Phase 9.P6 plan upgrade.
   - **RESOLVED:** FRE-vs-Restatement cross-framework distinctness is VALIDATED AT FIXTURE-BUILD TIME in Plan 01-02 Task 2 acceptance criteria — the axiom_summary field for each FRE shard must encode "judicial weighing of relevance/probative-vs-prejudicial factors" semantics, explicitly distinct from Restatement's "bargained-for exchange" semantics. If the maintainer's curation cannot hand-author distinct FRE axioms, Assumption A9's UCC §2-209 backup corpus replaces FRE. The distinctness check is manual (maintainer judgment) but codified as a 01-02 acceptance gate.

4. **Should `fixtures/consideration/` be JSON or TTL?**
   - What we know: CONTEXT.md D-1 says "hand-edited JSON or TTL." JSON is easier to hand-edit; TTL is closer to final storage format.
   - What's unclear: Which form Phase 9.P6 and Phase 15 prefer to consume.
   - Recommendation: **JSON at Phase 1.** Each shard = one JSON file with fields `{iri, framework, source_doc, extracted_text, axiom_summary, prime_analogate_hint, proportional_relation_hint}`. A `fixture_loader.py` converts to pyoxigraph triples at detector invocation. Advantages: (a) trivial to validate with jsonschema; (b) grep-friendly; (c) maintainer can hand-edit without Turtle syntax overhead. Ship a TTL export for Phase 15 consumers via `polysemy export-fixture --format ttl`.
   - **RESOLVED:** Generate-once, never-rotate. On first `folio-insights polysemy review` invocation, `reviewer.py::ensure_reviewer_did()` creates `~/.folio-insights/reviewer.jwk` (canonical ed25519 private key, JWK-serialized) and writes the derived did:key to `~/.folio-insights/reviewer.did`. Subsequent invocations read the persisted values — no rotation in Phase 1. Phase 6 (DID substrate) will introduce rotation + signature verification. This lands in Plan 01-02 Task 1. (The original Open-Question-4 "JSON vs TTL" recommendation stands independently — shards are JSON.)

5. **N=20 lower bound — is this fixed by CONTEXT.md, or a soft floor?**
   - What we know: CONTEXT.md L12 says "≥20 shards across 3+ frameworks." Math: 3 frameworks × N≥3 per framework rule = minimum 9 shards. 20 is meaningfully larger.
   - What's unclear: If curation stalls at 15 shards, does Phase 1 proceed or block?
   - Recommendation: Treat 20 as target; 9 as hard floor (below which N≥3 rule fails for any framework); document in SUMMARY.md if final count < 20 and justify per-framework distribution.
   - **RESOLVED:** Provider-agnostic single-string LLM spec. The detector and FP-audit surfaces accept one `--llm-provider <MODEL_STRING>` CLI flag (default `claude-haiku-4-5`). Accepted values follow the `instructor.from_provider()` convention: `"claude-haiku-4-5"` → anthropic family, `"gpt-4o-mini"` → openai, `"gemini-2.0-flash"` → google, `"ollama/llama3.2"` → ollama local. The detector's `_resolve_provider_family()` maps the string prefix to the instructor family. There is NO separate `--llm-model` flag — the model string IS the spec. (The original Open-Question-5 "N=20 floor" recommendation stands independently — 20 target, 9 hard floor.)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Everything | ✓ | 3.13 locked (per pyproject `>=3.11,<3.13` — note: `<3.13` excludes 3.13, venv shows 3.12) | — |
| pyoxigraph | Fixture load + distinguo TTL emit | ✓ | 0.5.7 exact pin | — |
| instructor | LLM fallback + audit | ✓ | ≥1.14 pin | — |
| sentence-transformers | Embedding centroids | ✓ | ≥3.0 pin + `all-MiniLM-L6-v2` model cached | — |
| click | CLI | ✓ | 8.1.8 | — |
| rich | TUI prompts | ✓ | 13.9.4 | — |
| pydantic | Models | ✓ | ≥2.7 | — |
| cryptography | did:key ed25519 gen | ? | Need to verify (A1) | If absent, add explicit pin `cryptography>=41` |
| base58 | did:key z-encoding | ✗ (probably) | — (A2) | Add explicit dep OR hand-code base58btc (~30 LOC) |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` env var | instructor LLM calls | expected ✓ (project-level) | — | If absent at runtime: document as runtime error; user sets env var |
| Filesystem access to `~/.folio-insights/` | reviewer DID persistence | ✓ | — | — |

**Missing dependencies with fallback:**
- `base58` — hand-code fallback acceptable; prefer adding the package (it's 10KB)

**Missing dependencies with no fallback:**
- None blocking.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9+ with pytest-asyncio (asyncio_mode = "auto") and pytest-timeout (30s default) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `pytest tests/polysemy/ -x --timeout=30` |
| Full suite command | `pytest tests/polysemy/ tests/bench/ -v --timeout=30` (excluding `-m "slow or gate3 or gate4 or gate5"` unless explicitly requested) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PRINCIPLE-06 | FP rate ≤ 10% on curated ≥20-shard fixture | integration | `pytest tests/polysemy/test_fp_rate.py::test_fp_rate_within_target -x` | ❌ Wave 0 |
| PRINCIPLE-06 | Auto-apply is impossible by design (CLI-only, no auto-commit) | unit | `pytest tests/polysemy/test_cli_review.py::test_no_auto_apply_path -x` | ❌ Wave 0 |
| PRINCIPLE-06 | Rule layer flags on framework-conflicting *axioms*, not *contexts* (Pitfall 1 regression) | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule1_axioms_not_contexts -x` | ❌ Wave 0 |
| PRINCIPLE-06 | N ≥ 3 per framework gate | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule2_n_ge_3 -x` | ❌ Wave 0 |
| PRINCIPLE-06 | Terms-of-art whitelist raises threshold to 0.8 | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule3_whitelist_threshold -x` | ❌ Wave 0 |
| PRINCIPLE-06 | Homonym whitelist flags LLM fallback path | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule4_homonym_flag -x` | ❌ Wave 0 |
| PRINCIPLE-06 | Instructor LLM fallback returns discriminated-union verdict | unit (mocked) | `pytest tests/polysemy/test_detector_llm_fallback.py -x` | ❌ Wave 0 |
| VOCAB-02 | `fi:analogousTo` emission requires `fi:primeAnalogate` + `fi:proportionalRelation` (Pitfall 5 guard) | unit | `pytest tests/polysemy/test_distinguo_emission.py::test_analogousTo_requires_sub_properties -x` | ❌ Wave 0 |
| VOCAB-02 | `fi:distinctionKind` value in 4-enum set | unit | `pytest tests/polysemy/test_distinguo_emission.py::test_distinctionKind_enum -x` | ❌ Wave 0 |
| VOCAB-02 | Emitted TTL parses via pyoxigraph + round-trips | integration | `pytest tests/polysemy/test_distinguo_emission.py::test_ttl_roundtrip_pyoxigraph -x` | ❌ Wave 0 |
| D-3 lock | JSONL disposition record matches Phase 15 consumer schema | unit | `pytest tests/polysemy/test_dispositions_jsonl.py -x` | ❌ Wave 0 |
| D-3 lock | Append semantics (no rewrite, no truncation) | unit | `pytest tests/polysemy/test_dispositions_jsonl.py::test_append_only -x` | ❌ Wave 0 |
| D-4 lock | FP-rate report includes Wilson 95% CI (Pitfall 2 guard) | unit | `pytest tests/polysemy/test_fp_rate.py::test_reports_wilson_ci -x` | ❌ Wave 0 |
| D-4 lock | LLM audit pass reports disagreements only | integration (mocked) | `pytest tests/polysemy/test_fp_rate.py::test_audit_disagreements_only -x` | ❌ Wave 0 |
| CLI ergonomics | `folio-insights polysemy review` accept/reject/modify paths | integration | `pytest tests/polysemy/test_cli_review.py -x` | ❌ Wave 0 |
| Reviewer DID | First-invocation generates real did:key; persisted to `~/.folio-insights/` | unit | `pytest tests/polysemy/test_reviewer_did.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/polysemy/ -x --timeout=30` (fast suite — all tests except network-dependent instructor audit)
- **Per wave merge:** `pytest tests/polysemy/ -v --timeout=60` (full suite; audit + FP-rate harness included)
- **Phase gate:** Full suite green on `main`; `fp-labeling-audit.md` + `SUMMARY.md` artifacts committed; `dispositions.jsonl` contains ≥20 accept/reject/modify entries (validating the CLI TUI round-trips).

### Wave 0 Gaps

- [ ] `tests/polysemy/__init__.py` — package marker
- [ ] `tests/polysemy/conftest.py` — session-scoped `consideration_fixture_store` (mirrors `tests/bench/conftest.py::bench_store` pattern)
- [ ] `tests/polysemy/test_detector_rules.py` — unit tests for 4 rule gates
- [ ] `tests/polysemy/test_detector_llm_fallback.py` — mocked instructor; unit
- [ ] `tests/polysemy/test_prototype_cluster.py` — centroid math; unit
- [ ] `tests/polysemy/test_distinguo_emission.py` — VOCAB-02 TTL round-trip via pyoxigraph; integration
- [ ] `tests/polysemy/test_cli_review.py` — CliRunner + scripted stdin; integration
- [ ] `tests/polysemy/test_dispositions_jsonl.py` — schema + append semantics; unit
- [ ] `tests/polysemy/test_fp_rate.py` — FP-rate harness + Wilson CI; integration (network for audit pass)
- [ ] `tests/polysemy/test_reviewer_did.py` — did:key generation; unit
- [ ] New pytest marker in pyproject.toml: `polysemy_spike: Phase 1 polysemy-distinguo spike tests`

**Framework install:** No install needed — pytest 9+ and pytest-asyncio already in `[project.optional-dependencies].dev` (pyproject.toml L26-29).

## Project Constraints (from CLAUDE.md + repo discipline)

> No repo-root `CLAUDE.md` exists. Global `~/.claude/CLAUDE.md` and project `.planning/` discipline apply.

Actionable constraints the planner must honor:

- **`instructor.from_provider()` abstraction** — all LLM calls go through `LLMBridge` (services/bridge/llm_bridge.py), not raw instructor imports (LLM-01 pattern).
- **No server-side signing keys** (DID-06) — reviewer DID private key lives in `~/.folio-insights/`, never committed to git.
- **No `owl:sameAs` between analogical senses** (PHILOSOPHY L126) — use `fi:analogousTo` + mandatory sub-properties.
- **No auto-apply distinguo** (FEATURES §B anti-feature; §16 R2) — CLI human gate is the only commit path.
- **No RDF-star subject-position triple terms** (Phase 0 Pitfall 1) — use RDF 1.2 annotation-pipe or `rdf:Statement` reification.
- **Use PyoxigraphStore wrapper, not raw pyoxigraph.Store** (Phase 0 SEC-01 mitigation) — SERVICE preflight is inherited.
- **Module-bottom CLI subgroup import** in `src/folio_insights/cli.py` — matches bench subgroup pattern, keeps heavy deps off `--help` hot path.
- **Session-scoped pytest fixtures** for expensive loads (matches `tests/bench/conftest.py` pattern) — avoid repeat pyoxigraph store + sentence-transformer model loads.
- **Deterministic port hashing** for any dev server (global CLAUDE.md convention) — N/A for Phase 1 (no server).
- **Lazy-singleton ML models** (established Phase 0+1 pattern) — reuse `services/boundary/semantic.py::_get_model`.
- **All file writes use the Write tool, never heredoc** — planning artifacts included.
- **Absolute paths in tool calls** — always.
- **Do not add new P1 deps without justification** — spike should lean on existing stack (core decision reason CONTEXT.md already validates).

## Sources

### Primary (HIGH confidence)

- In-repo `src/folio_insights/services/boundary/semantic.py` — lazy-singleton sentence-transformer pattern
- In-repo `src/folio_insights/services/task_clustering.py` — agglomerative clustering pattern
- In-repo `src/folio_insights/pipeline/stages/folio_tagger.py` — 4-path rule+LLM shape
- In-repo `src/folio_insights/store/pyoxigraph_store.py` — SEC-01 SSRF wrapper, SPARQL safety preflight
- In-repo `src/folio_insights/cli.py` (lines 260-263) — module-bottom CLI subgroup import pattern
- In-repo `src/folio_insights/bench/cli.py` — click subgroup template
- In-repo `tests/bench/conftest.py` — session-scoped pytest fixture pattern
- `PRD-v2.0-draft-2.md` §8.P6 L1090-1114 — three-tier polysemy architecture
- `PRD-v2.0-draft-2.md` §7.1 L738-773 — VOCAB-02 canonical TTL
- `PRD-v2.0-draft-2.md` §16 R2 L1465-1467 — 0.6 threshold + mandatory human gate
- `PHILOSOPHY.md` L108-141 — scholastic distinguo machinery + analogia entis
- `PHILOSOPHY.md` L252 — Fregean sense/reference as polysemy machinery
- `PHILOSOPHY.md` L126 — `fi:analogousTo` + mandatory `primeAnalogate` + `proportionalRelation`
- `.planning/research/PITFALLS.md` L643-668 — V5 False-fork explosion
- `.planning/research/PITFALLS.md` L1235-1256 — polysemy-vs-homonymy + known-homonym whitelist
- `.planning/phases/00-foundations-hard-gate/00-DECISION.md` — Phase 0 keep-verdict + Signature Deferral procedure
- `.planning/REQUIREMENTS.md` — PRINCIPLE-06 (L104) + VOCAB-02 (L90)
- [W3C did:key method spec — Ed25519](https://w3c-ccg.github.io/did-method-key/#ed25519) — HIGH
- [JSON Lines specification](https://jsonlines.org/) — HIGH
- [Click testing 8.3.x](https://click.palletsprojects.com/en/stable/testing/) — HIGH
- [Rich 14.1 Prompt docs](https://rich.readthedocs.io/en/stable/prompt.html) — HIGH
- [pyoxigraph 0.5.6/0.5.7 docs](https://pyoxigraph.readthedocs.io/en/stable/) — HIGH

### Secondary (MEDIUM confidence)

- [Instructor (567-labs/instructor) GitHub + python.useinstructor.com](https://python.useinstructor.com/) — confidence-scoring pattern with Pydantic `Literal[...]` fields
- [Wikipedia: Binomial proportion confidence interval — Wilson score](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval) — formula + small-sample properties
- [PMC: Interrater reliability kappa statistic](https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/) — kappa interpretation + small-sample caveats
- [ResearchGate: Kappa minimum sample size guidelines](https://www.researchgate.net/publication/320148141) — n<30 unreliability
- [Hamer v. Sidway (Cornell)](https://nycourts.gov/reporter/archives/hamer_sidway.htm) — canonical common-law consideration case
- [Restatement of Contracts (Cornell Wex)](https://www.law.cornell.edu/wex/restatement_of_the_law) — Restatement 2d §71 bargain theory
- [Consideration under American law (Wikipedia)](https://en.wikipedia.org/wiki/Consideration_under_American_law) — benefit-detriment vs bargain theories (polysemy evidence)
- [Polysemy and the Law (Hemel, Vanderbilt)](https://scholarship.law.vanderbilt.edu/context/vlr/article/4881/viewcontent/Polysemy_and_the_Law.pdf) — legal-English polysemy literature
- [pallets/click#2787 — CliRunner + click.prompt hanging](https://github.com/pallets/click/issues/2787) — test pitfall

### Tertiary (LOW confidence — flagged for validation)

- [Uncertainty Quantification and Confidence Calibration in LLMs survey (ACM SIGKDD 2026)](https://dl.acm.org/doi/10.1145/3711896.3736569) — ECE 0.108-0.427 figure
- [LLM Confidence and Calibration survey (beancount.io 2026)](https://beancount.io/bean-labs/research-logs/2026/07/09/confidence-estimation-calibration-llms-survey) — multi-dim uncertainty trend
- [arXiv 2404.19071 — Blind Spots and Biases in NLP annotation](https://arxiv.org/html/2404.19071v1) — single-annotator bias
- Training knowledge: base58btc encoding byte-layout for did:key; verify against [multiformats/multibase](https://github.com/multiformats/multibase) before implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all pins verified against pyproject.toml + installed venv; no new P1 deps needed (base58 + cryptography flagged as plan-time verification)
- Architecture patterns: HIGH — all patterns either lift from existing in-repo code (folio_tagger, task_clustering, PyoxigraphStore wrapper, bench CLI) or follow well-documented libraries (rich.prompt, click.testing, instructor Pydantic Literal)
- Pitfalls: HIGH — 7 pitfalls each grounded in either in-repo PITFALLS.md entries (Pitfalls 1-2-3-5-6) or verified external issues (Pitfalls 4-7)
- Validation architecture: HIGH — matches existing tests/bench/conftest.py session-scoped pattern; Wave 0 gap list is concrete and actionable
- VOCAB-02 encoding: HIGH — TTL snippet mirrors PRD §7.1 L738-773 verbatim; minimum-viable Python invariant check substitutes for deferred SHACL
- Open question 1 (axiom-proxy operationalization): MEDIUM — recommended approach is a clear simplification but user should confirm before detector design locks
- FP-rate methodology (Wilson CI, kappa-as-signal): MEDIUM — statistical foundations sound but n=20 is small and single-annotator bias is partially unmitigated by LLM audit
- Security domain: N/A — spike is CLI-only, no network surface added; inherits Phase 0 SEC-01 via PyoxigraphStore wrapper
- did:key stub implementation: MEDIUM — spec-correct path documented; base58 transitive-availability unverified

**Research date:** 2026-04-23
**Valid until:** 2026-05-23 (30 days — stable stack, Phase 0 already locked most decisions)

---
date: 2026-07-15
topic: folio-matching-platform
status: brainstorm — awaiting Damien's architecture-taste decisions
author: folio-insights research + CE-brainstorm agent (Fable lane)
branch: brainstorm/folio-matching-platform
compounds:
  - briefs/qa/2026-07-15-folio-insights-annot-answers.json (Ch02 review, stopped deliberately)
  - docs/plans/2026-07-15-001-feat-proposed-class-governance-plan.md (proposals governance)
  - docs/solutions/llm-path-unverified-iris.md (B9 verifier origin)
  - docs/solutions/heading-as-unit-fabrication.md (substance gate)
---

# Brainstorm — FOLIO Matching Platform & the folio-insights v2 In-App Annotator

## 1. Intent (Damien, verbatim from the Ch02 review)

> "Many 'proposed new classes' are actually RECALL failures — FOLIO concepts exist but the tagger
> misses them." … "folio-mapper + folio-enrich already have good engines for exactly this matching
> work — leverage them." … "Build-once-use-many-times: Module that every repo ingests? Separate
> resource (e.g., API) that every repo utilizes?" … "Bake the feedback loop INTO folio-insights
> itself (not HTML artifacts): annotator shows full text → span annotations → user assesses/annotates
> → feedback feeds back into the system = SELF-IMPROVING. Replicate folio-enrich's display + annotate
> features." … "Give the LLM judge the DOCUMENT-LEVEL DOMAIN PRIOR (book subject / practice area) so
> 'Defenses' → Litigation Defenses disambiguates correctly."

Damien stopped the Ch02 review on purpose. The incremental-patch path is over; the next move is a
platform decision plus an in-app, self-improving annotator. This doc answers **WHAT** to build and
frames the decisions that are genuinely his. It does **not** build anything.

## 2. What we verified first (evidence, not assertion)

**All five of Damien's IRIs resolve on the live FOLIO MCP — every "proposed new class" he flagged is a
real, existing concept the tagger failed to recall:**

| Surface term (Damien's example) | Target FOLIO concept | IRI | Why the tagger missed it |
|---|---|---|---|
| Presumptions | **Litigation Burdens of Proof** | `RDV74m3ydS2I72hZ88Mf1RX` | *Semantic* map (a presumption allocates the burden of proof). No shared label token → pure label matching **cannot** find it. Needs definition/embedding search + judge. |
| decision-maker | **Decisionmaker for Legal Disputes** | `RDSYPGgBlFz5eWNtwoMA2c5` | Normalization/tokenization miss: `decision-maker` → `decisionmaker` (hyphen fold) + head-noun match. Current path never normalizes the hyphen. |
| law | **Legal Authorities** | `RC1CZydjfH8oiM4W3rCkma3` | 3-char generic token; naive fuzzy floods on any label containing "law". Semantic map — needs definition-level matching, not label. |
| (unit `12b5e434`) | **Proposed Conclusions of Law** | `R9G2HzzbJMx6tThsp2m6kjM` | See below — both are siblings of "Proposed Court Filings" (`RiuB3WjtPaioVphDpqLzVK`). |
| (unit `12b5e434`) | **Proposed Findings of Fact** | `RNVlq2ReYjeb3r8UkUYvso` | The heading is a **conjoined compound** ("…Findings of Fact **and** Conclusions of Law") naming two sibling concepts with an elided shared head. No single concept equals the whole string → the matcher returns nothing → `proposed_class`. |

**Diagnosis of the two `12b5e434` misses (this shapes the recall design):** the failure is
**decomposition/recall, not scoring.** `entity_ruler` needs the exact label as a contiguous span; a
conjoined compound is not one; whole-string label search finds no concept named
"Findings of Fact and Conclusions of Law." Fix = **span decomposition** (conjunction split
`A and B → [A, B]`, plus shared-head expansion) feeding a multi-candidate semantic scorer, then match
each part. Both parts are found individually once decomposed — enrich/mapper's embedding + multi-strategy
search already do this.

**A second, concrete piece of evidence for finding 003 (Slovenia → 99 units) and the recall noise:** I
ran `search_concepts("Presumptions")` against the live index. The top hits, all at score **90**, were
**"Northern Mariana Islands," "Portugal," "Spain," "Puerto Rico," "Réunion."** The genuinely relevant
"Presumption of Innocence" scored **86 — below the place-name noise** — and "Litigation Burdens of Proof"
did not appear at all. **The rapidfuzz label matcher pathologically over-scores short country/place
labels.** That single defect explains *both* the Slovenia place-name propagation (003) *and* why recall
drowns. It is a shared root cause.

## 3. What the three engines actually are (reusable-component inventory)

All three are Python, all load the **`folio-python` PyPI package** (not folio-api, not local OWL) as
their concept store, and **none couple matching to a SQL/ORM layer**. That is the single most important
structural fact: **the matching intelligence is already framework- and DB-free.**

### folio-mapper — the canonical scorer (strongest reuse core)
- `backend/app/services/folio_service.py` — `_compute_relevance_score`, `_word_overlap`, `_tokenize`,
  `_content_words`, `LEGAL_TERM_EXPANSIONS`, `SEARCH_STOPWORDS`. **Set-based content-word scoring already
  makes it word-order-invariant** — "arbitration rules" and "rules of arbitration" both reduce to
  `{arbitration, rules}` (finding 004 is *already solved here*).
- `backend/app/services/pipeline/` — 4-stage orchestrator (filter → expand → rank → judge),
  `stage3_judge.py` LLM judge with a calibration prompt (90+ exact / 70–89 related / 50–69 tangential).
- `backend/app/services/embedding/folio_index.py` — FAISS `IndexFlatIP`, disk-cached, providers
  local(all-MiniLM-L6-v2, **free/offline**)/OpenAI/Ollama.
- **Gap:** no deterministic homonym blocklist (Action≠Auction relies on the LLM judge). No DB coupling.
  Best-tested scorer in the portfolio (`test_search_expansion.py`, `test_nlp.py`, `test_pipeline.py`).

### folio-enrich — the display + annotate + domain-prior reference
- `backend/app/services/folio/search.py` — a 7-strategy lexical search **explicitly "ported from
  folio-mapper"** (← the duplication, in the code's own words).
- Domain-prior injection **already exists**: `prompts/contextual_rerank.py` and `concept/branch_judge.py`
  thread the detected **document_type** + document excerpt into the judge call; `area_of_law_assessor.py`
  builds a document-level prior. **This is the template for Damien's domain-prior directive.**
- Display: `frontend/index.html:renderAnnotatedText` — boundary-point sweep → non-overlapping segments →
  nested spans (property ⊂ individual ⊂ annotation), offsets stored as `Span{start,end,text,sentence_text}`.
- Annotate: thumbs up/down → `/feedback` → `FeedbackStore` + `/feedback/insights` aggregation; plus a
  structural lifecycle (reject/restore/promote/cascade) with per-annotation `lineage`.
- **Ontology-neutral spec layer** (`OntologySpec`: FOLIO_SPEC + a CatholicOS CANON_SPEC) — matching is
  not hardwired to FOLIO, a strong reuse signal. No DB.

### folio-insights — the proving consumer (this repo)
- 4-path tagger `pipeline/stages/folio_tagger.py`: `entity_ruler` (trusted, Aho-Corasick) + `llm` +
  `semantic` (embeddings) + `heading_context`, merged by `FourPathReconciler` which **wraps
  folio-enrich's `Reconciler`**.
- **It already imports folio-enrich's `FolioService`, `EmbeddingService`, `FOLIOEntityRuler`, and
  `Reconciler` — and folio-mapper — via a `sys.path` sibling-directory bridge**
  (`services/bridge/folio_bridge.py`, default `../folio-enrich/backend`). This is documented as fragile
  (`docs/solutions/sys-path-bridge-staleness.md`).
- **B9 is a deterministic rapidfuzz label↔IRI verifier** (`token_sort_ratio ≥ 85`), *not* an LLM judge
  and *not* domain-prior-aware. It drops IRIs whose concept labels don't match the requested label, then
  re-resolves or demotes to `proposed_class`.
- Proposals governance (newest): `proposals/registry.py` + `data/governance/proposed_class_registry.json`
  → $0 Claude-side dedupe judge → HTML approval queue → export backlog.
- SQLite `review.db` (`persistence/review_db.py`): `review_decisions` (per-unit), `proposed_class_decisions`
  (per-label). **No per-tag verdict table.** SvelteKit 2 / Svelte 5 viewer served by FastAPI.

**The headline:** the "shared library" already exists *de facto* — as a filesystem hack. folio-mapper
wrote the scorer, folio-enrich copied it, folio-insights `sys.path`-imports both. The build-once decision
is really **"formalize the coupling that is already there, badly, into a real package."**

## 4. Approaches considered — build-once-use-many

Damien's framing was "module every repo ingests, or separate API every repo utilizes?" There are three
honest options. Consumer set doing source-text→FOLIO mapping today: **folio-insights, folio-enrich,
folio-mapper, alea-intake, book-indexer, clio-skills** (≈6, plus the `books` pipeline and light use in
generative-folio / mootloop).

| | **A. Shared Python library** (`folio-matching`) | **B. Hosted API service** (extend folio-api) | **C. Hybrid — library core + shared feedback/calibration data + optional thin service** |
|---|---|---|---|
| **Iteration speed** | Fast: `pip install -e`, no network | Slow: deploy to change matching | Fast for core; data package versioned separately |
| **Version skew (≈6 repos)** | Real risk — pinned versions drift | None — one server | Managed: semver pins + shared fixtures catch regressions |
| **LLM-call ownership** | Each app owns its keys; $0 Claude-side judge stays possible | Centralizes spend on the server (against minimize-app-spend) unless keys are passed through | Each app owns keys; judge runs app-side or $0 Claude-side (existing discipline) |
| **Offline / CLI (books pipeline)** | ✅ Native — `folio-insights extract` is offline-first | ❌ Needs network for every unit | ✅ Library path is offline; service is opt-in for remote/non-Python |
| **Feedback-loop data (per-tag verdicts) shared so ALL consumers benefit** | ❌ Library alone has nowhere shared to put it | ✅ Natural home — but folio-api is a **public CORS-`*` OSS** service; private book-feedback data doesn't belong there | ✅ A dedicated **shared calibration/feedback data layer** (versioned data package, optionally a private service) |
| **Fit to portfolio norms** | Matches MIT, per-repo, fork-and-PR pattern | folio-api already hosted at `folio.openlegalstandard.org` with `/llm/*` classifier endpoints | Best of both; more moving parts |

**Recommendation: C (Hybrid), library-first.** Extract a standalone **`folio-matching`** Python package
(MIT) that wraps `folio-python` and lifts the proven pieces: folio-mapper's scorer + FAISS index +
LLM-judge interface, folio-enrich's Aho-Corasick entity ruler + reconciler + **domain-prior judge**, plus
two *new* first-class capabilities the portfolio lacks — a **deterministic alias/homonym blocklist**
(Action≠Auction) and **span decomposition** (conjunction split + shared-head + place-name gate). Every
repo pins it, replacing the `sys.path` bridges. Alongside it, a **shared feedback/calibration data layer**
(alias blocklist + score-calibration data + judge few-shot + regression fixtures) that all consumers read
and the folio-insights annotator writes — this is what makes the system *compound* across repos. A thin
service (extend folio-api with a private `/match` endpoint) is deferred until a non-Python or remote
consumer needs it; the library is the source of truth.

**Three-sentence why:** The engines are already Python, DB-free, and informally shared through a fragile
`sys.path` hack, so a real pinned library is the smallest honest step that removes the hack and stops the
copy-paste divergence (enrich literally forked mapper's scorer). A pure API loses the offline books
pipeline and centralizes the LLM spend Damien wants minimized, while a pure library has nowhere shared to
persist the per-tag verdicts that must benefit every consumer — the hybrid's versioned data layer is
exactly that shared home. Library-first also lets folio-insights prove the whole loop end-to-end before we
pay for any service.

## 5. Migration order

1. **`folio-matching` v0** — extract mapper's scorer + enrich's ruler/reconciler/domain-prior into one
   package; add the alias blocklist, span-decomposition, and place-name gate; ship the shared
   fixtures/calibration data schema. Publish the feedback data layer as a versioned sub-package.
2. **folio-insights (proving consumer)** — swap the three `sys.path` bridges for the pinned package; build
   the v2 in-app annotator (§6); wire verdicts → the shared data layer. Prove the self-improving loop here
   first, on Ch02/Ch03.
3. **folio-enrich** — retire its "ported-from-mapper" `search.py`; consume the library. Its display code is
   the reference for the annotator but stays in enrich.
4. **folio-mapper** — becomes a thin TS UI over the library (its Python backend collapses into it).
5. **alea-intake, book-indexer, clio-skills** — migrate as each next touches FOLIO matching.

## 6. The folio-insights v2 in-app annotator (spec-level)

Replaces the one-off HTML artifacts (`scripts/build_annotation_viewer.py`) with a first-class view in the
existing SvelteKit viewer.

- **Full-text rendering with span-anchored tags** — port enrich's `renderAnnotatedText` boundary-sweep
  algorithm into a Svelte component; render a whole section/chapter with `ConceptTag`s anchored to their
  character spans within each unit (compute tag-in-unit offsets via the same Aho-Corasick/entity-ruler
  offsets the tagger already produces). Branch-colored, confidence-styled, nested-span-safe — display
  parity with folio-enrich.
- **Per-TAG verdict affordance** (Damien's directive: per-tag, not per-unit) — each tag chip gets
  **correct / weak / wrong + a note**, replacing thumbs. `extraction_path` and match score shown so the
  reviewer sees *why* a tag fired.
- **Persistence schema** — new SQLite table `tag_verdicts`:
  `(id, unit_id, run_id, corpus_name, tag_iri, tag_label, extraction_path, match_score, verdict ∈
  {correct,weak,wrong}, note, domain_prior, book, chapter, reviewer, reviewed_at)`. This is the missing
  per-tag layer; `review_decisions`/`proposed_class_decisions` remain for unit/label decisions.
- **Domain-prior injection** — add a `subject`/`practice_area` field to `CorpusManifest` (e.g. "Litigation
  / Trial Advocacy treatise"); thread it into every judge call (adopt enrich's `document_type` pattern) and
  store it on each verdict so calibration is domain-aware. This is a real **model addition**, not wiring —
  no book-level subject field exists today.

**Self-improvement mechanics — how a verdict becomes leverage:**
1. **Alias block-lists** — a `wrong` verdict on a homonym (`Action`→Auction IRI, `charge`→Encumbrance)
   appends `(surface_term, blocked_iri, domain)` to the shared blocklist the matcher consults — the
   deterministic homonym guard mapper/enrich currently lack.
2. **Match-score calibration** — `correct/weak/wrong` labels at their match scores form a labeled dataset
   to recalibrate the weak-match band (mapper's 45–60 weak; B9's 85) via score→P(correct) fitting.
   Directly addresses finding 004's "weak-band recalibration."
3. **Judge few-shot examples** — verdicts + domain prior become few-shot exemplars for both the tag judge
   and the proposals dedupe judge.
4. **Regression fixtures** — each verdict is a gold fixture (unit text + expected tag + verdict) in the
   shared fixtures package → CI guard. This is where "self-improving" becomes *durable* rather than vibes.

## 7. Immediate deterministic fixes (v2 workstreams, independent of the platform extraction)

- **WS-A · Place-name gate (finding 003).** Heading-context place-name propagation (Slovenia → 99 units)
  and the rapidfuzz place-name over-scoring share a root cause. Gate geographic/place concepts behind
  stronger evidence (explicit heading-context match or ≥2 corroborating signals); demote bare fuzzy
  place-label hits.
- **WS-B · Word-order/normalization-aware matching (finding 004).** Adopt mapper's set-based
  `_word_overlap` + hyphen/whitespace normalization so "arbitration rules" = "rules of arbitration" and
  "decision-maker" = "Decisionmaker"; recalibrate the weak band from verdict data.
- **WS-C · Metadata/front-matter exclusion (unit `d3c44e2a`).** Add a first-class `source_type`/section
  classification to `KnowledgeUnit` (front_matter / metadata / body); exclude non-body sources from tagging
  rather than relying only on the heuristic `is_substantive()`.
- **WS-D · Recall pass via enrich/mapper techniques (unit `12b5e434`, finding 005).** Span decomposition
  (conjunction split + shared-head expansion) → definition/embedding semantic search → domain-prior judge.
  This is what turns "recall failures" back into matches (Presumptions→Burdens of Proof, law→Legal
  Authorities, the two `12b5e434` siblings). Semantic maps have **no shared label token**, so label matching
  alone will never find them — the embedding + judge path is mandatory, not optional.

## 8. Key decisions (genuinely Damien's — batched, each with my recommendation)

1. **Architecture shape** — Library / API / **Hybrid**. *Rec: Hybrid, library-first.*
2. **New standalone `folio-matching` repo vs a package inside an existing repo.** *Rec: standalone MIT repo,
   pinned by consumers (matches portfolio norms).*
3. **Is the feedback/calibration store shared across repos on day one, or prove-in-insights-first?**
   *Rec: prove in folio-insights first; promote to the shared data layer at the v0 library cut (weeks, not
   months).*
4. **Domain-prior source** — human-set per corpus vs auto-detect (enrich-style DocumentType). *Rec:
   human-set `subject` on `CorpusManifest` for books (cheap, reliable), auto-detect as fallback for other
   consumers.*
5. **Migration timing for the non-insights consumers** (alea-intake / book-indexer / clio-skills) — migrate
   opportunistically vs a scheduled sweep. *Rec: opportunistic (as each next touches matching).*
6. **Stand up the thin `/match` service now, or defer until a remote/non-Python consumer needs it?** *Rec:
   defer — the library covers every current consumer, all Python.*

## 9. Open questions (engineering — mine to resolve, listed for transparency)

- Exact extraction boundary for `folio-matching` (which enrich `services/*` modules ship v0 vs v1).
- Whether the shared fixtures package is a git submodule, a pinned PyPI data package, or a synced dir.
- Tag-in-unit span computation: reuse the tagger's existing offsets vs recompute in the annotator.

## 10. Next steps

→ Resolve §8 with Damien via the decision artifact (favicon 🧩, house qa-artifact style).
→ On his ruling, `/ce:plan` the `folio-matching` v0 extraction + the folio-insights v2 annotator as two
  linked plans (annotator can start against the current bridges in parallel with the extraction).

# Extraction-Quality Rubric — v1 (LOCKED 2026-07-05)

| | |
|---|---|
| **Rubric ID** | `RUB-EXTRACT` |
| **Version** | v1 — **LOCKED** 2026-07-05 |
| **Status** | Locked via Damien's decisions (§0.5). Amendments trigger re-judging of affected findings (policy 3). |
| **Applies to** | folio-insights book-extraction campaign (`docs/evidence/books/`) |
| **Author** | Claude (Opus 4.8), 2026-07-05 |
| **Policy** | Portfolio policy 3 — *nothing is judged before the rubric is locked* |

> **How to read this doc (Damien):** every criterion has a stable ID (`RUB-EXTRACT-NN`).
> Edit freely — tighten thresholds, add/kill criteria, rewrite the taste calls. The
> **weights** and the **pass thresholds** are the two things I most want your eye on:
> they encode *your* standard for what "good extraction" means, and every evidence-pack
> score cites this version. **Locked 2026-07-05** — your four decisions are recorded in §0.5;
> this is now the scoring standard for the book campaign.

---

## 0. What this rubric judges (and against which pipeline)

The campaign proves the **live** extraction pipeline against Damien's own books. A load-bearing
fact discovered during pipeline mapping:

- **v1 `KnowledgeUnit` is what runs today.** `folio-insights extract <book_dir> -c <corpus>`
  produces `extraction.json` (units), `review.json`, `proposed_classes.json`; `discover`
  builds the task tree; `export --validate` runs SHACL. **This rubric scores those real
  artifacts.**
- **v2.0 `ShardEnvelope` is a validated schema with no live producer yet** (the Stage-8
  Shard Minter is Phase 10, unbuilt). Where a criterion has a v2 analog, it's noted as
  *(v2-forward)* so the rubric survives the migration, but **v1 outputs are what get scored
  this campaign.**

**The unit of judgment** is the extracted `KnowledgeUnit`, rolled up to **per-chapter** and
**per-book** scores. A unit carries: `text`, `unit_type` (advice｜principle｜citation｜
procedural_rule｜pitfall), `original_span{start,end,source_file}`, `source_section[]`
breadcrumb, `folio_tags[{iri,label,confidence,extraction_path,branch}]`, `surprise_score`,
`confidence`, `content_hash`, `lineage[]`.

**The gestalt oracle stack** (portfolio policy — determinism + probabilism composed). Each
criterion names its judge:
- **[DET]** deterministic — scripted `folio-python` / `pyshacl` / offset arithmetic. Reproducible, ~free. Runs first.
- **[LLM]** LLM-judge — a scoped, rubric-anchored model call with the source span in context.
- **[MCP]** FOLIO-MCP — *semantic* concept-fit judgment only ("is this the right concept?"), never mechanical lookups (those are [DET]).
- **[TASTE]** Damien / domain expert — the advocacy-value calls no oracle can make.

Most criteria compose several: e.g. FOLIO mapping = [DET] IRI-exists + [MCP] concept-fit + [TASTE] final call.

---

## 0.5 Locked decisions (Damien, 2026-07-05)

1. **Fidelity gate = STRICT.** Any unit **not traceable to a supporting source span fails
   outright** (`RUB-EXTRACT-05` becomes a hard gate, alongside `-06` fabrication). This
   forces the pipeline to produce *true extraction with accurate provenance* — the de-risk
   run (`docs/evidence/books/DE-RISK-FINDINGS.md` Q1) showed current output is paraphrase
   with misaligned spans, so **a provenance-alignment pipeline fix is now the campaign's
   critical path**, ahead of scoring any book as a pass.
2. **Weights kept as drafted** — Fidelity 30 / Mapping 25 / Usefulness 20 / Completeness 15 / SHACL 10.
3. **Chapter pass threshold raised to mean ≥ 2.5** (from 2.0), all gates green, completeness ≥ 2.
4. **Completeness ground truth = LLM-generated salient-points list, correctable in the pack** —
   a subagent lists each chapter's expected points; that list is an editable pack artifact
   Damien can fix; recall is scored against it.

_(Not asked; applied as default — revisit anytime: `-04` rewards correct proposed-classes but
gives no extra bonus for Ecosystem-Loop value.)_

## 1. Scoring model

Each criterion scores on a **0–3 scale** unless marked **[gate]** (pass/fail):

| Score | Name | Meaning |
|---|---|---|
| 3 | Exemplary | Best-in-class; use as a positive exemplar in the pack |
| 2 | Pass | Meets the standard; ship it |
| 1 | Borderline | Acceptable-with-reservations; logged as a borderline exemplar for Damien |
| 0 | Fail | Below standard; drives a fix |

**Aggregation.**
- **Per-unit judged score** = weighted mean of the per-unit criteria (weights in §2), reported 0–3.
- **Per-chapter score** = mean per-unit score across the chapter's units, **plus** the chapter-level criteria (completeness) scored once per chapter.
- **Per-book score** = mean of chapter scores.

**Gates (a chapter/book cannot "pass" if any gate fails), most severe first:**
1. **`RUB-EXTRACT-06` fabricated content = automatic Fail** for the unit and flags the chapter. Zero tolerance: an invented citation, holding, rule, number, or party is the one error that destroys the "extractive, not generative" thesis.
2. **`RUB-EXTRACT-05` untraceable claim = automatic Fail** (STRICT, Damien-locked 2026-07-05). A unit whose claim is not supported by a valid, correctly-located source span fails — no partial credit. This is the gate that forces true extraction over paraphrase.
3. **`RUB-EXTRACT-10` / `-11` SHACL non-conformance** blocks a book-level pass (structural correctness is non-negotiable for a published KG).
4. **`RUB-EXTRACT-03` invalid/unresolvable IRI** on a non-proposed tag blocks the unit's mapping score from exceeding 1.

**Chapter pass threshold (LOCKED):** mean judged score **≥ 2.5**, **all gates green**, and completeness (`RUB-EXTRACT-08`) **≥ 2**.

---

## 2. Criteria

### Dimension A — Correct FOLIO mapping  *(weight 25%)*

**`RUB-EXTRACT-01` — Concept correctness** · per-unit · **[MCP]+[TASTE]** · weight 10%
The mapped FOLIO concept is genuinely *about* what the unit says — not a lexical false-friend
(e.g. "objection" the trial act vs. "objection" the philosophy term). Judge each `folio_tag`:
does the concept's FOLIO definition match the unit's meaning?
- **3** every tag correct incl. the non-obvious ones; **2** primary tag correct, minor tags fine; **1** primary correct but ≥1 spurious tag; **0** primary tag wrong.

**`RUB-EXTRACT-02` — Granularity ("as deep as possible, no deeper")** · per-unit · **[DET]+[MCP]** · weight 6%
The unit maps to the *most specific correct* FOLIO concept, not a lazy over-general parent,
and not a child too specific to be supported. [DET] `folio-python` confirms the parent/child
chain; [MCP] judges whether a deeper concept would have been more correct.
- **3** optimal depth; **2** one level too shallow but defensible; **1** clearly too general/specific; **0** wrong branch entirely.

**`RUB-EXTRACT-03` — IRI validity & branch membership** · per-unit · **[DET]** · **[gate-soft]** · weight 5%
Every non-proposed `folio_tag.iri` resolves to a real FOLIO concept and actually sits in the
`branch` the tag claims. Scripted `folio-python`: `iri exists` + `branch membership`. A tag
with `iri=''` must have `extraction_path == "proposed_class"`.
- **[gate-soft]** any invalid/mislabeled IRI caps the unit's mapping dimension at 1.

**`RUB-EXTRACT-04` — Proposed-class discipline (Ecosystem-Loop feeder)** · per-unit · **[MCP]+[TASTE]** · weight 4%
When no adequate FOLIO concept exists, the unit is correctly routed to `proposed_classes.json`
(not force-mapped to a near-miss IRI), **and** the proposal is a real ontology gap worth
feeding upstream — not a mapping the system simply missed.
- **3** genuine gap, cleanly proposed; **2** correct to propose, description thin; **1** should have mapped to an existing concept; **0** force-mapped a wrong IRI to dodge proposing.

### Dimension B — Extractive-not-generative fidelity  *(weight 30% — the thesis)*

**`RUB-EXTRACT-05` — Source traceability** · per-unit · **[DET]+[LLM]** · **[GATE — strict]** · weight 10%
Every unit points back to its passage. [DET]: `original_span{start,end,source_file}` are valid
offsets into an existing source file and the sliced text is non-empty. [LLM]: the passage at
that span **actually supports** the unit's claim (not an adjacent/wrong span).
- **[GATE, Damien-locked] 0 = automatic unit Fail** — any unit not traceable to a supporting, correctly-located span fails, no partial credit. *(Current pipeline output fails this — units are paraphrases with misaligned spans, so the provenance-alignment fix is the campaign's critical path before any chapter can pass.)*
- **3** span exact, quote fully supports claim; **2** span slightly loose but still supports; **0** span imprecise/vicinity-only, invalid, empty, or unrelated. (Strict gate collapses "borderline traceability" into Fail — no score-1 tier.)

**`RUB-EXTRACT-06` — No fabricated content** · per-unit · **[LLM]+[TASTE]** · **[GATE]** · weight 12%
The unit asserts **nothing** absent from its source passage: no invented citations, holdings,
statutes, numbers, party names, or rules; no generative embellishment presented as source
content. **This is the campaign's central claim.**
- **[GATE] 0 = automatic unit Fail + chapter flag.** Any fabricated *citation* is an instant 0 regardless of the rest.
- **3** perfectly faithful; **2** faithful, trivial harmless paraphrase; **1** paraphrase drifts but no fabricated fact; **0** fabricates.

**`RUB-EXTRACT-07` — Faithful compression** · per-unit · **[LLM]+[TASTE]** · weight 8%
Distillation preserves the author's meaning and tactical intent; nuance, hedges, and
conditions ("only when…", "never if…") are not flattened into false absolutes.
- **3** compression sharpens without distorting; **2** faithful; **1** loses an important qualifier; **0** inverts or misstates the point.

### Dimension C — Per-chapter completeness  *(weight 15%)*

> No completeness oracle exists in the codebase — the rubric defines it. Method: a subagent
> reads the chapter and produces a **salient-points list** (the advice/principles/pitfalls/
> rules a domain expert would expect extracted); we score recall against it. The salient-points
> list is itself an artifact in the evidence pack for Damien to correct.

**`RUB-EXTRACT-08` — Recall of salient knowledge** · per-chapter · **[LLM]+[TASTE]** · weight 10%
The chapter's major advocacy points are captured — no significant omissions of a technique,
principle, or warning a practitioner would need.
- **3** ≥95% of salient points captured; **2** ≥80%; **1** ≥60%; **0** <60% or a *critical* point missed.

**`RUB-EXTRACT-09` — Precision / no padding · no dup** · per-chapter · **[DET]+[LLM]** · weight 5%
Units aren't boilerplate, headings-as-units, or near-duplicates; [DET] `content_hash` dedup
held; [LLM] spot-checks that units carry real knowledge, not filler.
- **3** every unit earns its place; **2** ≤1 filler/dup; **1** several; **0** noisy.

### Dimension D — SHACL conformance  *(weight 10% — structural gate)*

**`RUB-EXTRACT-10` — Shape conformance** · per-book · **[DET]** · **[GATE]** · weight 6%
`folio-insights export <corpus> --validate` reports `conforms=true` against the active shapes
(`export/shapes.ttl`: every `owl:Class` has `rdfs:label`; every individual has
`prov:wasDerivedFrom` source lineage).
- **[GATE]** non-conformance blocks a book-level pass. **3** clean; **2** conforms w/ warnings; **0** violations.
- *(v2-forward: when the Shard Minter lands, add `vocab/shapes.ttl` vocab-pin + supersession-alignment shapes.)*

**`RUB-EXTRACT-11` — Structural integrity** · per-book · **[DET]** · **[GATE]** · weight 4%
The export report's IRI-Uniqueness, Referential-Integrity, and Namespace-Consistency checks
all PASS.
- **[GATE]** any FAIL blocks book pass. **3** all PASS; **0** any FAIL.

### Dimension E — Advocacy usefulness  *(weight 20% — Damien's domain)*

**`RUB-EXTRACT-12` — Actionability** · per-unit · **[TASTE]** · weight 8%
A litigator could *act* on the unit. It captures a real technique, principle, or warning —
not trivia, throat-clearing, or a definition already obvious to any lawyer.
- **3** sharp, usable, non-obvious; **2** useful; **1** true but low-value; **0** noise.

**`RUB-EXTRACT-13` — Task-discoverability** · per-unit · **[LLM]+[TASTE]** · weight 7%
The unit lands under the right node in the discovered task tree — "how do I take an expert
deposition?" surfaces the deposition units and not the voir-dire ones. Judged against
`task_tree.json` placement.
- **3** perfectly placed; **2** right neighborhood; **1** loosely related node; **0** misfiled.

**`RUB-EXTRACT-14` — Value calibration** · per-unit · **[TASTE]** · weight 5%
`unit_type` and `surprise_score` are sensible; genuinely non-obvious expert insight isn't
buried at the same weight as boilerplate, and boilerplate isn't flagged as surprising.
- **3** well-calibrated; **2** minor miscalibration; **1** notably off; **0** inverted.

---

## 3. Weight summary (Damien: adjust freely)

| Dimension | Weight | Criteria |
|---|---:|---|
| A. FOLIO mapping | 25% | 01 (10) · 02 (6) · 03 (5) · 04 (4) |
| B. Extractive fidelity | 30% | 05 (10) · **06 (12, GATE)** · 07 (8) |
| C. Completeness | 15% | 08 (10) · 09 (5) |
| D. SHACL conformance | 10% | **10 (6, GATE)** · **11 (4, GATE)** |
| E. Advocacy usefulness | 20% | 12 (8) · 13 (7) · 14 (5) |
| **Total** | **100%** | 14 criteria |

**Design intent (for your review):** fidelity (B) is the heaviest because "extractive, not
generative" is the product's whole trust thesis, and it's where LLM extraction fails silently.
Usefulness (E) is weighted second because a technically-perfect extraction of worthless units
is worthless — and that's the call only you can make. Mapping (A) third. SHACL (D) is low-weight
but a hard gate: it's cheap, binary, and non-negotiable rather than a matter of degree.

---

## 4. Resolved questions (locked 2026-07-05 — decisions in §0.5)

_All five resolved: (1) threshold → **≥ 2.5**; (2) fabrication/traceability scope → new facts = `-06` fail **and** untraceable spans = `-05` strict fail; (3) completeness → **LLM salient-points list, correctable in the pack**; (4) weights → **kept as drafted**; (5) proposed-class → correct-proposing rewarded, no extra bonus (applied default). Original questions retained below as rationale._

1. **Chapter pass threshold** — I proposed mean ≥ 2.0 + all gates green + completeness ≥ 2. Too lenient? Too strict for a first pass? → **Resolved: ≥ 2.5.**
2. **Fabrication scope** — is a *paraphrase that adds a plausible-but-unstated qualifier* a `-06` fabrication (gate-0) or a `-07` compression drift (score 1)? I've drawn the line at "new facts = fabrication, distorted emphasis = compression." Confirm.
3. **Completeness ground truth** — OK to use an LLM-generated salient-points list (that you can correct in the pack) as the recall denominator, or do you want to hand-author salient points for the first chapter to calibrate?
4. **Weights** — especially fidelity 30 vs. usefulness 20. Flip them?
5. **Proposed-classes** — should a high rate of *good* proposed-classes (real ontology gaps) score as a **positive** (Ecosystem-Loop value) rather than a mapping miss? Currently `-04` rewards correct proposing but doesn't bonus it.

---

## 5. Changelog

- **v1 (2026-07-05) — LOCKED.** Grounded in the live v1 `KnowledgeUnit` pipeline; v2
  `ShardEnvelope` analogs noted as *(v2-forward)*. Locked after Damien's four decisions (§0.5):
  strict fidelity gate (`-05` untraceable = fail), weights unchanged, pass bar raised to ≥ 2.5,
  completeness via a correctable LLM salient-points list. **Consequence:** a provenance-alignment
  pipeline fix becomes the campaign's critical path (current output is paraphrase, not extraction).
- **v1-draft (2026-07-05)** — initial draft shared for Proof review.

# Extraction-Quality Rubric — v1.0 (LOCKED 2026-07-07)

| | |
|---|---|
| **Rubric ID** | `RUB-EXTRACT` |
| **Version** | v1.0 — **LOCKED** 2026-07-07 |
| **locked-by** | Fable (delegated by Damien 2026-07-07); Damien post-reviews — amendments trigger re-judging of affected scores |
| **Status** | Locked via Fable's resolutions (§0.5). Supersedes the 2026-07-05 provisional lock. Amendments trigger re-judging of affected findings (policy 3). |
| **Applies to** | folio-insights book-extraction campaign (`docs/evidence/books/`) |
| **Author** | Claude (Opus 4.8), 2026-07-05; resolutions by Fable 2026-07-07 |
| **Policy** | Portfolio policy 3 — *nothing is judged before the rubric is locked* |

> **How to read this doc (Damien):** every criterion has a stable ID (`RUB-EXTRACT-NN`).
> Edit freely — tighten thresholds, add/kill criteria, rewrite the taste calls. The
> **weights** and the **pass thresholds** are the two things I most want your eye on:
> they encode *your* standard for what "good extraction" means, and every evidence-pack
> score cites this version. **Locked v1.0 on 2026-07-07 by Fable (delegated by Damien)** — the six
> resolutions are recorded in §0.5; this is now the scoring standard for the book campaign. Damien
> post-reviews; any amendment triggers re-judging of affected scores.

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

## 0.5 Locked decisions (Fable, delegated by Damien, 2026-07-07)

These resolutions **supersede** the 2026-07-05 provisional lock. Damien post-reviews;
amendments trigger re-judging of affected scores.

1. **Fidelity provenance = HYBRID-STRICT.** Units **may compress/paraphrase** the source
   (extraction is distillation, not transcription), **but EVERY unit must carry a verifiable
   source anchor**: either a true character-span into the source file, **or** an exact quoted
   snippet that fuzzy-matches the source **≥ 0.85**. Anchor-verification failure fails
   `RUB-EXTRACT-05` (the gate). This preserves the *"extractive, not generative"* thesis:
   a unit may restate a passage in its own words, but it must prove which passage.
   **The pipeline currently storing paraphrase-offsets (offsets that don't slice the claimed
   text) is a BUG TO FIX** — store real char-spans or exact snippets — **not a rubric
   relaxation.** (De-risk `docs/evidence/books/DE-RISK-FINDINGS.md` Q1 showed misaligned
   offsets; the anchor-storage fix is on the campaign's critical path.)
2. **Pass threshold = ALL GATE criteria pass + weighted overall ≥ 0.80 per story** (normalized
   0–1, i.e. weighted judged-mean / 3 ≥ 0.80 ≈ 2.40/3). Below → **iterate** (fix + re-ingest +
   re-judge), do not pass. Completeness floor `RUB-EXTRACT-08 ≥ 2` retained as a sensible
   adaptation.
3. **Fabrication = zero tolerance.** Any fabricated legal claim, authority, or citation
   (`RUB-EXTRACT-06`) is an **automatic story Fail — never averaged away.** A single invented
   citation fails the story regardless of every other score.
4. **Completeness ground truth = per-chapter section-coverage map** (the chapter's
   headings/subheadings form the denominator) with **judged sampling** — *not* exhaustive
   point-by-point enumeration. A subagent builds the heading/subheading map; recall is judged
   as "is each section represented by ≥1 substantive unit, and are the sampled sections'
   salient points captured?" The coverage map is an editable pack artifact Damien can correct.
5. **Weights:** fidelity/anchoring **30%**, FOLIO-mapping correctness **25%**, completeness
   **20%**, usefulness **15%**, technical/SHACL **10%**. (Completeness rises 15→20; usefulness
   falls 20→15 vs. the 2026-07-05 provisional lock — see §3.)
6. **Proposed-class bonus.** A genuine, well-formed proposed-class earns **small positive
   credit** (`RUB-EXTRACT-04`) — it feeds the Ecosystem Loop and should not read as a mapping
   miss. **The bonus never offsets a GATE fail.**

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

**Gates (a chapter/book/story cannot "pass" if any gate fails), most severe first:**
1. **`RUB-EXTRACT-06` fabricated content = automatic story Fail** (zero tolerance, Fable-locked 2026-07-07). An invented citation, holding, rule, number, party, or authority fails the story outright and is **never averaged away** — it is the one error that destroys the "extractive, not generative" thesis.
2. **`RUB-EXTRACT-05` anchor-verification failure = automatic unit Fail** (HYBRID-STRICT, Fable-locked 2026-07-07). A unit may compress/paraphrase, but it must carry a verifiable source anchor: a valid char-span whose sliced text is non-empty, **or** an exact quoted snippet fuzzy-matching the source **≥ 0.85**. No anchor / anchor doesn't verify → Fail, no partial credit.
3. **`RUB-EXTRACT-10` / `-11` SHACL non-conformance** blocks a book-level pass (structural correctness is non-negotiable for a published KG).
4. **`RUB-EXTRACT-03` invalid/unresolvable IRI** on a non-proposed tag blocks the unit's mapping score from exceeding 1.

**Story/chapter pass threshold (LOCKED 2026-07-07):** weighted judged score normalized to 0–1 (weighted-mean / 3) **≥ 0.80** (≈ 2.40/3), **all gates green**, and completeness (`RUB-EXTRACT-08`) **≥ 2**. Below → **iterate** (fix + re-ingest + re-judge), do not pass.

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
- **Proposed-class bonus (Fable-locked 2026-07-07):** a genuine, well-formed proposed-class earns **small positive credit** at the chapter roll-up (+0.05 to the chapter's normalized score per distinct genuine gap, capped at +0.10) — it feeds the Ecosystem Loop and should not read as a mapping miss. **The bonus never offsets a GATE fail** (a chapter with a `-05`/`-06`/`-10`/`-11` gate failure still fails).

### Dimension B — Extractive-not-generative fidelity  *(weight 30% — the thesis)*

**`RUB-EXTRACT-05` — Source anchoring (HYBRID-STRICT)** · per-unit · **[DET]+[LLM]** · **[GATE — hybrid-strict]** · weight 10%
Every unit must carry a **verifiable source anchor**. A unit may compress or paraphrase, but it
must prove which passage it came from, one of two ways:
- **(a) char-span** — `original_span{start,end,source_file}` are valid offsets into an existing
  source file **and** the sliced text is non-empty; OR
- **(b) quoted snippet** — an exact quoted snippet from the source that **fuzzy-matches the
  source text ≥ 0.85** (`rapidfuzz` token/partial ratio).

[DET] verifies the anchor mechanically (span slices non-empty / snippet fuzzy-ratio ≥ 0.85).
[LLM] confirms the anchored passage **actually supports** the unit's claim (not an adjacent/wrong
passage).
- **[GATE, Fable-locked 2026-07-07] 0 = automatic unit Fail** — no verifiable anchor, or the
  anchor doesn't support the claim → Fail, no partial credit. **Paraphrase is allowed; a missing
  or non-verifying anchor is not.** *(The pipeline storing paraphrase-offsets that don't slice
  the claimed text is a BUG TO FIX — store real char-spans or exact snippets — not a reason to
  relax this gate. This anchor-storage fix is the campaign's critical path.)*
- **3** anchor exact + clearly supports; **2** anchor verifies (span loose but non-empty, or
  snippet 0.85–0.92) and supports; **0** no verifying anchor, empty slice, snippet < 0.85, or
  anchor unrelated to the claim.

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

### Dimension C — Per-chapter completeness  *(weight 20%)*

> No completeness oracle exists in the codebase — the rubric defines it. Method (Fable-locked
> 2026-07-07): a subagent builds a **per-chapter section-coverage map** — the chapter's
> headings/subheadings are the **denominator** — then does **judged sampling**: is each section
> represented by ≥ 1 substantive unit, and (on a sampled subset of sections) are that section's
> salient points captured? This replaces exhaustive point-by-point enumeration. The coverage map
> is itself an editable artifact in the evidence pack for Damien to correct.

**`RUB-EXTRACT-08` — Section coverage & recall** · per-chapter · **[DET]+[LLM]+[TASTE]** · weight 14%
Every heading/subheading in the chapter's structure is represented by at least one substantive
unit, and — on the judged sample of sections — the section's major advocacy points (technique,
principle, warning) are captured with no significant omission a practitioner would need.
- **3** ≥ 95% of sections covered **and** sampled sections' salient points captured; **2** ≥ 80% sections covered; **1** ≥ 60%; **0** < 60% coverage or a *critical* section/point missed.

**`RUB-EXTRACT-09` — Precision / no padding · no dup** · per-chapter · **[DET]+[LLM]** · weight 6%
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

### Dimension E — Advocacy usefulness  *(weight 15% — Damien's domain)*

**`RUB-EXTRACT-12` — Actionability** · per-unit · **[TASTE]** · weight 6%
A litigator could *act* on the unit. It captures a real technique, principle, or warning —
not trivia, throat-clearing, or a definition already obvious to any lawyer.
- **3** sharp, usable, non-obvious; **2** useful; **1** true but low-value; **0** noise.

**`RUB-EXTRACT-13` — Task-discoverability** · per-unit · **[LLM]+[TASTE]** · weight 5%
The unit lands under the right node in the discovered task tree — "how do I take an expert
deposition?" surfaces the deposition units and not the voir-dire ones. Judged against
`task_tree.json` placement.
- **3** perfectly placed; **2** right neighborhood; **1** loosely related node; **0** misfiled.

**`RUB-EXTRACT-14` — Value calibration** · per-unit · **[TASTE]** · weight 4%
`unit_type` and `surprise_score` are sensible; genuinely non-obvious expert insight isn't
buried at the same weight as boilerplate, and boilerplate isn't flagged as surprising.
- **3** well-calibrated; **2** minor miscalibration; **1** notably off; **0** inverted.

---

## 3. Weight summary (Damien: adjust freely)

| Dimension | Weight | Criteria |
|---|---:|---|
| A. FOLIO mapping | 25% | 01 (10) · 02 (6) · 03 (5) · 04 (4) |
| B. Extractive fidelity / anchoring | 30% | 05 (10, GATE) · **06 (12, GATE)** · 07 (8) |
| C. Completeness | 20% | 08 (14) · 09 (6) |
| D. SHACL conformance | 10% | **10 (6, GATE)** · **11 (4, GATE)** |
| E. Advocacy usefulness | 15% | 12 (6) · 13 (5) · 14 (4) |
| **Total** | **100%** | 14 criteria |

**Design intent (Fable-locked 2026-07-07):** fidelity/anchoring (B) is the heaviest because
"extractive, not generative" is the product's whole trust thesis, and it's where LLM extraction
fails silently — every unit must prove its passage. Mapping (A) second: a faithful unit tagged
to the wrong FOLIO concept is a KG defect. Completeness (C) rose to 20% (a KG with gaps under-serves
the litigator) and usefulness (E) fell to 15% (still Damien's taste call, but a technically-sound,
complete, faithful extraction is the primary bar). SHACL (D) is low-weight but a hard gate: it's
cheap, binary, and non-negotiable rather than a matter of degree.

---

## 4. Resolved questions (re-resolved 2026-07-07 by Fable — decisions in §0.5)

_Final resolutions (Fable 2026-07-07 supersede the 2026-07-05 provisional answers): (1) threshold → all gates + **weighted normalized ≥ 0.80**; (2) fabrication/anchoring → fabrication = **automatic story fail**, anchoring = **HYBRID-STRICT** (char-span or snippet fuzzy ≥ 0.85); (3) completeness → **section-coverage map + judged sampling**; (4) weights → completeness **20** / usefulness **15** (fidelity 30 / mapping 25 / SHACL 10); (5) proposed-class → **small positive bonus** that never offsets a gate. Original questions retained below as rationale._

1. **Chapter pass threshold** — I proposed mean ≥ 2.0 + all gates green + completeness ≥ 2. Too lenient? Too strict for a first pass? → **Resolved: ≥ 2.5.**
2. **Fabrication scope** — is a *paraphrase that adds a plausible-but-unstated qualifier* a `-06` fabrication (gate-0) or a `-07` compression drift (score 1)? I've drawn the line at "new facts = fabrication, distorted emphasis = compression." Confirm.
3. **Completeness ground truth** — OK to use an LLM-generated salient-points list (that you can correct in the pack) as the recall denominator, or do you want to hand-author salient points for the first chapter to calibrate?
4. **Weights** — especially fidelity 30 vs. usefulness 20. Flip them?
5. **Proposed-classes** — should a high rate of *good* proposed-classes (real ontology gaps) score as a **positive** (Ecosystem-Loop value) rather than a mapping miss? Currently `-04` rewards correct proposing but doesn't bonus it.

---

## 5. Changelog

- **v1.0 (2026-07-07) — LOCKED by Fable (delegated by Damien).** Supersedes the 2026-07-05
  provisional lock. Six resolutions (§0.5): (1) fidelity → **HYBRID-STRICT** — paraphrase allowed
  but every unit must carry a verifiable anchor (true char-span **or** exact snippet fuzzy ≥ 0.85);
  paraphrase-offset storage is a **bug to fix**, not a relaxation; (2) pass threshold → all gates +
  **weighted normalized ≥ 0.80** per story; (3) fabrication → **automatic story fail, never
  averaged**; (4) completeness → **section-coverage map** (headings denominator) + judged sampling,
  replacing the salient-points list; (5) weights → completeness 15→**20**, usefulness 20→**15**
  (fidelity 30 / mapping 25 / SHACL 10 unchanged); (6) **proposed-class bonus** (+0.05/gap, cap
  +0.10; never offsets a gate). **Consequence:** the anchor-storage pipeline fix remains the
  campaign's critical path.
- **v1 provisional (2026-07-05)** — Damien's four decisions: strict fidelity gate (`-05`
  untraceable = fail), weights unchanged, pass bar ≥ 2.5, completeness via LLM salient-points list.
  Superseded by v1.0.
- **v1-draft (2026-07-05)** — initial draft shared for Proof review.

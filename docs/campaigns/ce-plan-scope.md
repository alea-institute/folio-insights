# `/ce:plan` scope — folio-insights pipeline fixes (books-UAT)

_The authoritative input to the pipeline-fix `/ce:plan`. **Every evidence-pack `Fail` MUST appear
here as a plan acceptance item** (Damien's standing instruction, 2026-07-05 — "cover all Fails in
the CE:Plan stage; don't forget"). When `/ce:plan` runs, its plan doc must cite each EP-ID below
and its rubric refs, and its acceptance criteria must close each one._

## Damien's dispositions (from evidence-pack feedback, 2026-07-05)

| EP-ID | Item | Status | Damien | Rubric |
|---|---|---|---|---|
| EP-INSIGHTS-BOOKS-004 | B2 — `.docx` `<w:sdt>` ingestion broken | **fail** | "Keep in docs so /ce:plan can cover it." → **WS1** | RUB-EXTRACT-08 |
| EP-INSIGHTS-BOOKS-005 | B3 — OpenAI provider unusable | info | ✅ **APPROVED** — "use the cheap Gemini Flash model." No fix; config decision locked. | — |
| EP-INSIGHTS-BOOKS-006 | B4 — discovery→export chain broken | **fail** | "Let's fix this in CE." → **WS2** | RUB-EXTRACT-13 |
| EP-INSIGHTS-BOOKS-007 | Q1 — provenance spans don't trace | **fail** | Strict fidelity gate (locked) → **WS3** critical path | RUB-EXTRACT-05/06/07 |
| EP-INSIGHTS-BOOKS-009 | Daubert mapping | borderline | "Horrible mapping! Should be **Daubert Motion Practice** `RT7xQmfA7w5HT02clIpAe`. How improve?" → **WS4** + gold | RUB-EXTRACT-01/05/12 |
| EP-INSIGHTS-BOOKS-011 | Expert-testimony pitfall mapping (branch Location) | **fail** | (Q2 homonym) → **WS4** | RUB-EXTRACT-01/05 |
| EP-INSIGHTS-BOOKS-012 | Rule 26 mapping (branch Location) | **fail** | "Procedural Rule is correct. Why did you say Location?" → **WS4** | RUB-EXTRACT-01/05 |
| EP-INSIGHTS-BOOKS-008 | Q2 — homonym branch mis-mappings (systemic) | borderline | → **WS4** | RUB-EXTRACT-01/02 |

## The four workstreams the `/ce:plan` must cover

**WS1 — `.docx` ingestion (EP-004).** folio-enrich `WordIngestor` reads only `document.paragraphs`;
this book's prose is in `<w:sdt>` content-controls → 0 chars → raw ZIP bytes ingested. Options:
fix `WordIngestor` (traverse sdt/tables/textboxes) **or** a folio-insights docx→text preprocessor
(keeps the fix in-lane; folio-enrich is a separate workstream). Acceptance: all Trial Advocacy
`.docx` chapters ingest as clean prose.

**WS2 — discovery→export chain (EP-006).** `provider.generate()` → `complete`/`chat` (likely
[DIRECT] one-liner); `discover` must write `review.db`; OWL serializer must handle null `folio_iri`.
Acceptance: `discover`→`export --validate` runs clean end-to-end with no manual review.db seeding
and task-level FOLIO IRIs populated.

**WS3 — source-grounded extraction (EP-007) — CRITICAL PATH (strict gate).** Worse than
mis-spanned: the deep-dive found units are **fabricated** — not in the ingested source at all
('Rule 26' appears 0× in the *entire book*; Daubert content is in Ch10, not the ingested Ch01).
The pipeline generates from LLM training, not the book. Re-architect extraction so every unit is
**grounded in and traceable to** a real source passage (verbatim anchor / exact offsets), and
fabricated units are structurally impossible. Acceptance: sampled units quote text that exists in
the source and supports the claim; a `verify()`-style traceability check passes; fabrication rate
≈ 0. **No chapter can pass until this lands.**

**WS4 — FOLIO mapping via deterministic IRI resolution (EP-008/009/011/012).** Root cause is
deeper than "homonyms": in this run FOLIO tags came from the **LLM path ONLY** (`paths=['llm']`)
and the LLM **hallucinated IRIs** — valid FOLIO strings pointing at the wrong concept
('Rule 26(a)(1)'→'Russian Federation', 'Daubert/Frye Standard'→'Rye'). **~90% of 2,226 tags are
wrong; 45% land in implausible branches (Location = 31%).** Core fix: **the LLM must NEVER emit
IRIs** — it proposes a *label/concept*, then IRI resolution is **deterministic** (folio-python
exact/alias) → **FOLIO-MCP / embedding semantic rerank** → validate (the gestalt / deterministic-first
rule). Ensure the deterministic entity_ruler/semantic paths actually run (B1 had disabled them).
Seed the eval/gold set with Damien's corrections (`mapping-corrections.gold.json`; Daubert →
`RT7xQmfA7w5HT02clIpAe`). Acceptance: a concept-**match** oracle (not mere existence) passes on a
sample; implausible-branch rate below threshold; exemplars map to sensible legal concepts.

## CE triage note
WS1/WS2/WS3/WS4 all touch pipeline structure → **`/ce:plan` first** (per portfolio CE triage).
WS2's `.generate()` rename and WS4's gold-set wiring may land [DIRECT] *inside* the plan's work.
B3 (Google) needs no plan — it's a locked config decision. Compound each root-caused fix into
`docs/solutions/`.

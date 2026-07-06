# Books-UAT — Pipeline De-Risk Findings (pre-rubric-lock)

_One-chapter smoke run of the LIVE v1 pipeline on real book text (Trial Advocacy Ch01),_
_2026-07-05. These are FINDINGS, not rubric scores (rubric not yet locked — policy 3)._
_They seed the evidence pack and drive the pre-campaign fix list._

## ⚠️ CORRECTION (2026-07-05, post-review deep-dive)

The "produces good output / 529 valid IRIs / 15-of-15 IRI checks pass" framing below was
**too optimistic — the checks were too weak.** A concept-**match** deep-dive (resolve each IRI,
compare its real FOLIO concept to the stored label) found the pipeline is **generative, not
extractive, at two levels**: (1) the *units* are largely **fabricated** (not in the ingested
source — 'Rule 26' 0× in the whole book); (2) the FOLIO *IRIs* are **LLM-hallucinated** — valid
strings pointing at the wrong concept (**~90% of 2,226 tags wrong; 45% in implausible branches,
Location 31%**). "IRI exists" ≠ "IRI correct". The pack (`pack.html` / Artifact) carries the
corrected findings and Damien's dispositions; treat that + `ce-plan-scope.md` as current.

## Headline (original, superseded by the correction above)

The pipeline **runs end-to-end on real book text** — but only after clearing environment
blockers. On the working config it yielded **621 knowledge units** (mean confidence 0.87),
**529 distinct valid** (existent) **FOLIO IRIs**, and a **SHACL-conformant OWL export**. So the
*plumbing* works. But an at-scale campaign is **blocked** by the items below, and — per the
correction — the *content* fails the rubric wholesale.

## Deterministic oracle results (the parts that CAN run pre-lock)

| Oracle | Result |
|---|---|
| folio-python IRI existence + branch consistency (15-of-529 sample) | **15/15 PASS**, 0 mismatches (18,326 concepts loaded) |
| SHACL `export --validate` (conforms + 4 checks) | **conforms=TRUE**; Shapes / IRI-Uniqueness / Referential-Integrity / Namespace-Consistency all **PASS** (67 task classes, 440 triples) |
| `verify-iris` (shard provenance re-mint) | **N/A** — needs the DID/shard registry (`~/.folio-insights/shard_iri_registry.db`); extract/discover/export don't populate it (v2 substrate, not v1) |

## BLOCKERS to a clean at-scale run

| # | Blocker | Status | CE triage |
|---|---|---|---|
| B1 | **Bridge venv deps undeclared** — `python-docx`, `rapidfuzz`, `marisa-trie` imported via the folio-enrich sys.path bridge but not in folio-insights' manifest. Absence silently killed `.docx` ingestion + ALL FOLIO IRI matching. | ✅ **FIXED this session** (declared as core deps; compound doc updated) | [DIRECT] done |
| B2 | **`.docx` ingestion broken** — folio-enrich `WordIngestor` reads only `document.paragraphs`; this book's prose lives in `<w:sdt>` content-controls → 0 chars → pipeline ingests raw ZIP bytes as "units". All Trial Advocacy chapters are `.docx`. | ⛔ OPEN. Worked around via `<w:t>` XML extraction. | **[CE]** — touches ingestion pipeline structure AND is in sibling repo folio-enrich. Options: fix `WordIngestor` (traverse sdt/tables/textboxes) OR add a folio-insights docx→text preprocessor. `/ce:plan` first. |
| B3 | **OpenAI provider unusable** — folio-enrich's `OpenAICompatProvider` forces `response_format: json_object`, but extraction prompts lack the literal word "json" → 400 on every call (+ TPM 429s). | ⛔ OPEN (upstream folio-enrich bug). | **Campaign decision: run on Google.** `GOOGLE_API_KEY` is present + valid; default `google`/`gemini-2.5-flash-lite` works and is cheap. No folio-insights change needed. Upstream prompt/provider fix = folio-enrich scope (out of this lane). |
| B4 | **Discovery→Export chain broken** — discovery's LLM stages call non-existent `provider.generate()` (providers expose `complete`/`chat`) → silently fail → tasks get **no FOLIO IRIs**; CLI `discover` never writes `review.db`; OWL serializer crashes on null `folio_iri`. (SHACL pass above required manually seeding review.db + minting task IRIs.) | ⛔ OPEN. | **[CE]** — pipeline structure. `/ce:plan`. The `.generate()`→`complete/chat` part may be a [DIRECT] one-liner; the review.db-write + null-IRI handling are structural. |

## MATERIAL QUALITY DEFECTS (shape rubric scoring — flagged to Damien on the Proof doc)

**Q1 — Provenance spans do not trace to source (RUB-EXTRACT-05, and challenges the thesis).**
Units are **LLM-distilled paraphrases**; their `original_span{start,end}` offsets do **not**
point at the source text they summarize. Example: an advice unit's span quote was
`"\nThe Advocat"` — clearly not the passage the claim came from. This is a real traceability
defect and it bears directly on the "extractive, not generative" thesis: today the pipeline is
closer to *abstractive summarization with a broken back-pointer* than to extraction. **Damien
should decide how strict RUB-EXTRACT-05/06/07 are given this** — comment added to the Proof doc.

**Q2 — Semantically wrong FOLIO branch mappings (RUB-EXTRACT-01).**
IRIs are valid FOLIO nodes (deterministic check passes) but the *concept choice* is often a
homonym mis-match: "Expert testimony"→**Location**, "Rule 26(a)(1)"→**Location**,
"Daubert/Frye"→**Asset Type**. The four-path tagger picks lexically-plausible but semantically
wrong concepts. This is the strongest argument for the **FOLIO-MCP semantic gate** (gestalt
rule) in judging, and a likely pipeline-tuning target.

## Candidate exemplars (for the pack, once scored)

| type / conf | unit (≤2 lines) | span quote | top tag (label · branch) | flag |
|---|---|---|---|---|
| advice / 0.98 | Obtain full deposition re factual basis of expert opinions for Daubert/Frye motions | `"\nThe Advocat"` | Daubert/Frye Standard · **Asset Type** | Q1 span, Q2 branch |
| principle / 0.90 | Focus on the advocate's goal | `"vocate\n\nA.The Goal of the "` | advocate · Service | Q1 span (loose) |
| pitfall / 0.90 | Expert testimony limited to opinions in reports; no new bases at trial | `".Data Availability\n\nD.Q"` | Expert testimony · **Location** | Q1 span, Q2 branch |
| procedural_rule / 0.95 | During discovery, object to untimely witness/exhibit disclosures; ensure Rule 26 compliance | `".Data Availability\n\nD.Q"` | Rule 26(a)(1) · **Location** | Q1 span, Q2 branch |

## Spend (policy 5)

- Config: Google `gemini-2.5-flash-lite`. ~3,060 billable calls for this chapter; ~5.0M input + ~0.66M output tokens.
- **≈ $0.75 this chapter** (includes a wasted search-disabled tagger pass; clean ≈ $0.70).
- Extrapolation: **~$10/book → ~$30 for all 3 books** on flash-lite. Cost is **not** the constraint; correctness (B2/B4, Q1/Q2) is.
- No token logging in the pipeline — estimated from call counts. *(Improvement candidate: instrument spend.)*

## Artifacts

Left in place at `output/uat_ta_ch01/`: `extraction.json` (IRI-bearing), `review.json`,
`proposed_classes.json`, `discovery.json`, `task_tree.json`, `review.db` (seeded),
`folio-insights.owl`/`.ttl`, `validation-report.md`.

## Next-session fix order (before the S1–S7 judging loop)

1. Rubric lock (Damien) — gates all scoring.
2. B2 `.docx` ingestion [CE] and B4 discovery→export [CE] — `/ce:plan` each. B4's `.generate()` rename may land [DIRECT] inside the plan.
3. Re-run Ch01 clean on Google end-to-end (no manual seeding) → confirm B2/B4 closed.
4. Run S1–S7 loop across chapters; deterministic oracles first, FOLIO-MCP semantic gate for Q2.
5. Generate `docs/evidence/books/pack.html` from the template with rubric scores; auto-close.

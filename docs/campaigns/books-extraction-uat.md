# Book-Extraction UAT Campaign — Plan

_folio-insights' first UAT campaign. Prove the extraction pipeline against Damien's own books._
_Status: SETUP (rubric with Damien; ingest de-risking underway). Judging blocked until `extraction-quality-v1` locks (policy 3)._

## Corpus

| Book | Source (per-chapter) | Full-book markdown mirror |
|---|---|---|
| **Trial Advocacy** (7th) | `../folio-insights-sources/Originals/2024-02-xx BOOK - Trial Advocacy…/0NN_ChNN_*.docx` | `../books/Markdown/Trial_Advocacy_Full_Book.md` |
| **Pretrial Litigation** | `…/2025-02-xx BOOK - Pretrial Litigation…/ChNN_*.docx` (+ Front Matter.pdf) | `../books/Markdown/Pretrial_Litigation_Full_Book_New.md` |
| **Trialbook** (Sonsteng & Haydock) | `…/2025-10-28 BOOK Trialbook…/0NN_ChNN_* - RIEHL EDITS.docx` (+ full PDF) | `../books/Markdown/Trialbook_Full_Book.md` |

Ingestion accepts a **directory** of files (14 formats incl. `.docx`/`.pdf`/`.md`). Per-chapter `.docx` files = natural iteration slices (policy 5: iterate on ONE book/chapter, cheap model, scale to all three only for the final pass).

## Pipeline under test (LIVE = v1)

`extract <dir> -c <corpus> -o ./output` → `discover <corpus>` → `export <corpus> --validate` → `verify-iris`.
Output judged = `extraction.json` (`KnowledgeUnit[]`), `proposed_classes.json`, `task_tree.json`, and the SHACL validation report. (v2 `ShardEnvelope` has no live producer yet — Phase 10.)

## User stories → acceptance probes → book slice

Personas/goals distilled from `.planning/PROJECT.md` + `.planning/ROADMAP.md`; probes reuse `fixtures/gold_queries/*.sparql` (13 named) as per-story acceptance queries. Each story is judged by the rubric dimensions in the last column.

| # | Persona → goal | Acceptance probe(s) | Best book slice | Rubric focus |
|---|---|---|---|---|
| S1 | **Litigator** → "how do I take an expert deposition?" returns structured techniques mapped to FOLIO | `advocacy_with_provenance`, task-tree lookup | Pretrial Ch06 Depositions | A (mapping), E13 (task-discoverability), B (fidelity) |
| S2 | **Litigator** → find pitfalls/warnings before a task (avoid mistakes) | unit_type=`pitfall` recall | Trial Advocacy Ch04 Evidence & Objections | C8 (completeness), E12 (actionability) |
| S3 | **Legal educator** → the governing *principles* of a topic, not just steps | unit_type=`principle`; `seven_principles_conflict` | Trialbook Ch01 Planning to Win | E12, A1 (concept correctness) |
| S4 | **Practitioner** → every claim is *traceable* to the book (trust) | `advocacy_with_provenance`; span-validity | any chapter | **B5/B6/B7 (fidelity — the thesis)** |
| S5 | **Agent builder / developer** → query the KG for concept-filtered advice | `confidence_threshold`, `framework_filter`, `cross_corpus_traversal` | all 3 (final pass) | A3 (IRI validity), D (SHACL) |
| S6 | **Ontology steward** → surface concept GAPS the corpus needs (Ecosystem Loop) | `proposed_classes.json` review | any chapter | A4 (proposed-class discipline) |
| S7 | **Scholar** → correct citations, procedural rules extracted verbatim | unit_type=`citation`/`procedural_rule`; fabrication gate | Pretrial Ch03/Ch04 (citation-dense) | **B6 (no fabricated citations — GATE)** |

## The per-story loop (post-lock)

1. **Ingest** ONE book slice (subagent runs `extract`/`discover`/`export --validate`; cheap model; report spend).
2. **Deterministic oracles first** (gestalt — determinism before probabilism):
   - SHACL: `export --validate` → conforms? (RUB-EXTRACT-10/11, gates)
   - `verify-iris`: provenance re-mint integrity (RUB-EXTRACT-05a)
   - Scripted **folio-python** IRI-exists + branch-membership on all mapped tags (RUB-EXTRACT-03) — reproducible, ~free.
   - Span-validity arithmetic: offsets resolve, quote non-empty (RUB-EXTRACT-05a).
3. **Probabilistic judgment** (subagents return pass/fail per criterion + exemplar quotes; main loop makes the calls):
   - LLM-judge with source span in context: fidelity (B5b/B6/B7), completeness vs salient-points list (C8/C9), value (E12/E14).
   - **FOLIO-MCP only for semantic concept-fit** (A1 concept correctness, A2 granularity, E13 placement) — the gestalt rule.
4. **Fix** (root-cause pipeline problems get `/ce:compound` → `docs/solutions/`; architectural fixes get `/ce:plan` first per CE triage) → **re-ingest** → re-judge.
5. **Scale**: once one book iterates clean, run all three for the **final pass**.

## Evidence capture

Every mapping decision, borderline extraction, and per-chapter/-book rubric score → a section (`EP-INSIGHTS-BOOKS-NNN`) in the evidence pack (`docs/evidence/books/pack.html`, built from `docs/evidence/_template/`). Rubric-version banner + app-side spend line required. Auto-close; Damien iterates by EP-ID.

## Deferred v1 items closed here (brief step 4)

- 3 debug (already in `.planning/debug/resolved/`, awaiting_human_verify): `corpus-processing-no-extraction`, `create-corpus-silent-fail`, `llm-api-config` → **verified by a clean real-chapter run**.
- Phase 03 `03-HUMAN-UAT.md` (4 pending scenarios) → mapped onto S1–S7 probes.
- VERIFICATION.md `human_needed` (Phase 01, 01.1, 03) → the campaign's live run + oracles supply the evidence.

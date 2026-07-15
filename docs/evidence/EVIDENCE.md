# Evidence Packs — folio-insights

Index of ID-addressable review packs for this repo (house convention:
`tools/evidence-pack/README.md`). Each pack is self-contained HTML that Damien
reviews by EP-ID; agents ingest the sidecar `manifest.json`.

| Pack | EP prefix | Rubric | Date | What it covers |
|------|-----------|--------|------|----------------|
| [books/](books/pack.html) | `EP-INSIGHTS-BOOKS` | extraction-quality-v1.0 | 2026-07-07 | Ch01 v4/v5 judged score sheets (EP-024/025), de-risk findings, voting-bug post-mortem |
| [books-ch01-annotations/](books-ch01-annotations/pack.html) | `EP-INSIGHTS-BOOKS-ANNOT` | extraction-quality-v1.0 | 2026-07-15 | **Ch01 "The Advocate" annotation viewer** — all 372 v5 units against the book's source text, each with FOLIO concept + definition + provenance, and the 5 residual mapping issues flagged for troubleshooting |
| [books-ch02-annotations/](books-ch02-annotations/pack.html) | `EP-INSIGHTS-BOOKS-ANNOT` | extraction-quality-v1.0 | 2026-07-15 | **Ch02 "Planning and Preparation" annotation viewer** — 464 units, fresh current-pipeline run; surfaces the new `heading_context` path collision (Slovenia → 99 units) |
| [books-ch03-annotations/](books-ch03-annotations/pack.html) | `EP-INSIGHTS-BOOKS-ANNOT` | extraction-quality-v1.0 | 2026-07-15 | **Ch03 "Trial Procedures and Motions" annotation viewer** — 491 units, fresh current-pipeline run ($0.121 app-side); "Motions" node over-applied to 127 units |

## books-ch01-annotations — troubleshooting sample

Built at Damien's request (portfolio q1, 2026-07-15): before spending on a full
book, annotate ONE substantive chapter and let him **see** the annotations.

- **Chapter:** `014_Ch01_The_Advocate` (7th ed.), the first numbered doctrinal
  chapter (front-matter files are 001–013) — 119,584 chars, 86 headings, covering
  ADR, professional-responsibility duties, and witness-examination doctrine.
  Substantive, not an intro/overview or appendix.
- **Source:** existing `output/uat_ta_ch01_v5/` (weighted 0.827, all gates PASS).
  **App-side spend: $0** — no re-extraction.
- **Findings (5):** `EP-INSIGHTS-BOOKS-ANNOT-001..005`
  - 001 (fail) — abstract words → governmental-body entities (justice→U.S. DOJ, state→U.S. Dept. of State, arb→U.S. Bankruptcy Court)
  - 002 (fail) — FOLIO alt-label collisions (charge→Encumbrance, action→Auction, trial→Trial Practice)
  - 003 (borderline) — the 88-tag "Advocacy skills" catch-all node
  - 004 (borderline) — weak LLM label-match band (attorney→Lawyer scores low; correct and wrong both hide here)
  - 005 (info) — 42 proposed-class-only units (FOLIO coverage gap, honest demotions)
- **Artifact:** https://claude.ai/code/artifact/80b9d10a-7be3-4b22-934a-1a4c813ceb5e

## books-ch02-annotations & books-ch03-annotations — the two substantive chapters

Damien's ruling (2026-07-15): "The Chapter 1 is just the introduction. Can you do a
more substantive chapter — like Chapter 2 or Chapter 3? And provide both chapters as
actionable HTML artifacts?" Both chapters annotated with a **fresh current-pipeline
run** (post-B9 four-path tagging), built with the reusable
`scripts/build_annotation_viewer.py` on the Ch01 conventions.

- **Chapters:** `15_Ch02_Planning_and_Preparation` (464 units) and
  `16_Ch03_Trial_Procedures_and_Motions` (491 units) — the first two doctrinal
  chapters after the Ch01 intro.
- **App-side spend:** Ch03 **$0.121** measured (1,984 LLM calls, 689,681 tokens,
  gemini-2.5-flash-lite); Ch02 **~$0.115** derived from the identical-pipeline
  per-unit rate. **Total ≈ $0.24**, far under the $4 cap. (The extraction is the only
  phase needed for the viewer + registry; the Phase-2 discovery task-synthesis was not
  run — one Ch02 discovery call hung — so it is excluded.)
- **New finding vs Ch01:** the current pipeline's `heading_context` path (853–858 tags/
  chapter, absent from the Ch01-v5 output) propagates a heading's FOLIO concept to every
  unit beneath it. When a heading term collides with a place name this is systemic noise:
  **Ch02 "Slovenia" (Location) → 99 units**, plus Anambra / "Mary" / random State Courts.
  Flagged as the over-applied catch-all (finding 003).
- **Artifacts:**
  - Ch02: https://claude.ai/code/artifact/19c7bb2c-aaab-446c-833c-ced4cdec6079
  - Ch03: https://claude.ai/code/artifact/7468f062-4ab1-48fa-a78e-6907f6e14518

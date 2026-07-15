# Evidence Packs — folio-insights

Index of ID-addressable review packs for this repo (house convention:
`tools/evidence-pack/README.md`). Each pack is self-contained HTML that Damien
reviews by EP-ID; agents ingest the sidecar `manifest.json`.

| Pack | EP prefix | Rubric | Date | What it covers |
|------|-----------|--------|------|----------------|
| [books/](books/pack.html) | `EP-INSIGHTS-BOOKS` | extraction-quality-v1.0 | 2026-07-07 | Ch01 v4/v5 judged score sheets (EP-024/025), de-risk findings, voting-bug post-mortem |
| [books-ch01-annotations/](books-ch01-annotations/pack.html) | `EP-INSIGHTS-BOOKS-ANNOT` | extraction-quality-v1.0 | 2026-07-15 | **Ch01 "The Advocate" annotation viewer** — all 372 v5 units against the book's source text, each with FOLIO concept + definition + provenance, and the 5 residual mapping issues flagged for troubleshooting |

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

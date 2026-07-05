# Evidence-Pack Data Contract (`pack.json`)

This directory holds the **reusable evidence-pack template + generator** for the
folio-insights portfolio. Every campaign (books, contracts, …) produces a
`pack.json` in this shape, and the generator turns it into a self-contained,
offline HTML review pack plus two machine-readable sidecars.

| File | Role |
|---|---|
| `pack-template.html` | Self-contained shell (inline CSS + JS). Renders from a `const PACK_DATA = /*__PACK_DATA__*/ {};` placeholder. Built **once**; every campaign reuses it. |
| `build_pack.py` | Stdlib-only generator. Validates `pack.json`, injects it into the template, writes outputs. |
| `pack.schema.md` | This file — the data contract. |
| `sample-pack.json` | A 3-finding example for visual verification. |

---

## Running the generator

```bash
python docs/evidence/_template/build_pack.py <pack.json> <out_dir>
```

Example (produces the preview used to eyeball the template):

```bash
python docs/evidence/_template/build_pack.py \
  docs/evidence/_template/sample-pack.json \
  docs/evidence/_template/preview
```

### Outputs (into `<out_dir>/`)

| File | Contents |
|---|---|
| `pack.html` | The self-contained evidence pack — open directly in a browser, no server, no network. |
| `manifest.json` | Every `EP-ID` → `{title, kind, status, rubric_refs, book, chapter}` so agents resolve references programmatically. Also carries top-level `campaign`, `repo`, `rubric_version`, `generated_at`, `summary`. |
| `feedback.json` | Empty scaffold (`[]`). The pack's **Export all feedback** button downloads a populated version with the same shape: `[{id, title, rubric_refs, comment}]`. |

**Validation is enforced.** If `pack.json` violates the contract below, the
generator prints each problem to stderr and exits **non-zero** — no partial
output is written.

---

## The `pack.json` contract

```jsonc
{
  "campaign": "books",                    // REQUIRED · short slug; namespaces localStorage
  "repo": "INSIGHTS",                     // optional · shown in eyebrow + manifest
  "title": "folio-insights — Book Extraction Campaign",  // REQUIRED
  "subtitle": "one-line description",     // optional · masthead subline
  "generated_at": "2026-07-05T00:00:00Z", // REQUIRED · ISO-8601
  "rubric_version": "extraction-quality-v1 (locked 2026-07-05 or DRAFT)", // optional but recommended
  "spend": {                              // optional · app-side spend line
    "provider": "anthropic",
    "model": "claude-haiku-4-5",
    "usd": 0.42,                          // number
    "notes": "one-book iteration pass"
  },
  "summary": {                            // optional · stat row + verdict bar
    "books": 1, "chapters": 6, "units": 214,   // any non-negative-int keys render as stat cards
    "pass": 180, "borderline": 24, "fail": 10  // these three also drive the verdict bar + chips
  },
  "sections": [ /* REQUIRED · at least one · see below */ ]
}
```

### Section objects (`sections[]`)

```jsonc
{
  "id": "EP-INSIGHTS-BOOKS-001",          // REQUIRED · stable, UNIQUE; rendered as anchor (#id)
  "kind": "mapping_decision",             // REQUIRED · enum (below)
  "status": "pass",                       // REQUIRED · enum (below) · drives chip color
  "title": "Chapter 3 · deposition-sequencing unit",  // REQUIRED
  "rubric_refs": ["RUB-EXTRACT-01", "RUB-EXTRACT-05"],// optional · criterion IDs → ref chips
  "book": "Trial Advocacy",               // optional · powers book filter
  "chapter": "Ch 3 — Depositions",        // optional · powers chapter filter
  "body_md": "Markdown explanation…",     // optional · rendered to HTML (safe subset)
  "source_quote": "verbatim source passage",  // optional · collapsible provenance panel
  "extracted": "extracted unit / mapping output", // optional · collapsible mono panel
  "scores": [                             // optional · rubric score table
    { "criterion": "RUB-EXTRACT-01", "score": 2, "note": "concept correct" }
  ],
  "screenshot": null                      // optional · MUST be a "data:image/..." URI if present
}
```

### Enumerations

| Field | Allowed values |
|---|---|
| `kind` | `mapping_decision` · `borderline_extraction` · `rubric_score` · `finding` · `exemplar` |
| `status` | `pass` · `borderline` · `fail` · `info` |

### ID rule

`id` must match `^[A-Z0-9][A-Z0-9\-]*$` (uppercase letters, digits, hyphens) and
be **unique** within the pack — IDs are rendered as URL anchors and are the key
agents use to resolve feedback back to a finding. Convention:
`EP-<REPO>-<CAMPAIGN>-<NNN>`.

### Validation rules (enforced by `build_pack.py`)

- Top level must be an object; `campaign`, `title`, `generated_at` are required non-empty strings.
- `generated_at` must be ISO-8601 parseable.
- `sections` must be a non-empty array.
- Each section: `id` (valid + unique), `kind` (enum), `status` (enum), `title` are required.
- `rubric_refs` (if present) must be an array of non-empty strings.
- `scores[]` entries need `criterion` (string) and `score` (number); `note` optional.
- `screenshot` (if present) must be a `data:image/…` URI — **no external image references** (packs are offline).
- `summary` values must be non-negative integers; `spend.usd` must be a number.

Markdown rendered from `body_md` is HTML-escaped first, then a **safe subset** is
applied (headings, bold/italic, inline + fenced code, lists, blockquotes, links
limited to `http(s)`/`mailto`/anchors). Raw HTML in `body_md` is never injected.

---

## Feedback affordances the pack provides

The template implements review affordances no existing tool offers (portfolio
policy 2):

- **Rubric-version banner** (flags `DRAFT` vs `Locked`), **summary stat row**
  with pass/borderline/fail chips + proportional verdict bar, **app-side spend line**.
- Each section renders its **EP-ID as a clickable anchor**, a **status chip**,
  **rubric-ref chips**, and **collapsible** source-quote / extracted panels.
- **Per-section comment box** — persisted to `localStorage`
  (`folio-pack:<campaign>:<repo>:comment:<EP-ID>`), with a subtle "saved" indicator.
- **Per-section "Copy as prompt"** — copies a ready-to-paste implementation prompt
  (EP-ID + title + rubric refs + body/quote/extracted context + your note).
- **Floating "Export feedback"** (with a live count badge) — compiles every section
  that has a note into **one** structured markdown prompt, copies it to the clipboard,
  **and** downloads a `feedback.json` (`[{id, title, rubric_refs, comment}]`) agents ingest directly.
- **Filter/jump bar** — filter by status and by book/chapter, free-text search, plus
  a table-of-contents rail with scrollspy.
- **Light/dark theme-aware** (respects `prefers-color-scheme`, manual toggle persisted
  to `localStorage`), fully responsive, **zero external network requests**.

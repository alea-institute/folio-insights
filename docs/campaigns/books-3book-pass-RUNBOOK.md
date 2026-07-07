# Three-Book S1–S7 Pass — Ready-to-Run Runbook

_Queued 2026-07-07 (Lane 2 session 3). The full three-book extraction+judging pass, packaged
as a one-session start. **This is the next session's entry point** once the gate below is green._

> **Scope note (Damien, QA round-2 q6, 2026-07-07):** the three-book pass was deliberately
> **not run** in session 3. Session 3 verified fixes, re-extracted Ch01 cleanly, and judged it.
> Ch01 did **not** clear (see the ⛔ gate). This runbook is the mechanics for when it does.

---

## ⛔ DO NOT RUN UNTIL THIS GATE IS GREEN

The three-book pass costs ~$30 and takes hours. Running it before the pipeline can pass a
single chapter wastes both. **Precondition to start:**

1. **B9 fixed** — the LLM/semantic tagging path must stop emitting unverified FOLIO IRIs.
   Session-3 finding: 56.6% of Ch01 tags (1234/2179) fail concept-label verification;
   ~23% (508) map advocacy concepts to **countries** (the "Location" branch). Root cause +
   fix in `docs/solutions/llm-path-unverified-iris.md`. The deterministic `entity_ruler`
   path is clean (876/878) — the fix is to gate the **LLM-carried IRIs** through the same
   concept-label verifier that already guards empty-IRI resolution in
   `folio_tagger._reconciled_to_tags`, calibrated so it does not strip good `entity_ruler`
   tags.
2. **Ch01 re-judged clean** — re-extract Ch01 (below), re-run the oracle + LLM/MCP judges,
   confirm **all gates + weighted ≥ 0.80** (rubric `docs/rubrics/extraction-quality-v1.md`).

Only then proceed.

---

## Config (once per session)

```bash
cd "/home/damienriehl/Coding Projects/folio-insights"
VIRTUAL_ENV="$PWD/.venv" uv pip install -e '.[dev]'          # venv is uv-managed, no pip
export FOLIO_INSIGHTS_LLM_PROVIDER=google
export FOLIO_INSIGHTS_LLM_MODEL=gemini-2.5-flash-lite         # GOOGLE_API_KEY present in env
export PYTHONPATH="$PWD/src:$PWD/../folio-enrich/backend"     # oracle/verifier need enrich on path
```

- **Provider = Google** (OpenAI path is B3-broken; Google flash-lite is cheap + works).
- **No background waiters** — poll synchronously. Timings observed on Ch01 (119,594 chars):
  extract ≈ 9 min, discover ≈ 18 min, export < 5 s, oracle ≈ 7 s. Budget accordingly per chapter.
- **Retry/backoff on Google 503s** — the pipeline checkpoints each stage (`checkpoints/`,
  `discovery_checkpoints/`); re-run the same command with `--resume` (default) to continue.

## Corpus (per-chapter `.docx` = the natural slices)

| Book | Source dir |
|---|---|
| Trial Advocacy (7th) | `../folio-insights-sources/Originals/2024-02-xx BOOK - Trial Advocacy-*/` |
| Pretrial Litigation | `../folio-insights-sources/Originals/2025-02-xx BOOK - Pretrial Litigation-*/` |
| Trialbook (Sonsteng & Haydock) | `../folio-insights-sources/Originals/2025-10-28 BOOK Trialbook*/` |

Ingestion takes a **directory**. Point `extract` at either a whole book dir or a single
chapter `.docx` staged into a scratch dir (Ch01 used a single-file scratch dir so the
oracle re-ingests exactly one source).

## Per-slice commands (extract → discover → export → oracle)

```bash
CORPUS=uat_pl_ch06          # example: Pretrial Ch06 Depositions (S1 slice)
SRC="/abs/path/to/one-chapter-dir"    # dir containing the chapter .docx

.venv/bin/folio-insights extract "$SRC" -c "$CORPUS" -o ./output --no-resume
.venv/bin/folio-insights discover "$CORPUS" -o ./output
.venv/bin/folio-insights export  "$CORPUS" -o ./output -f owl,ttl --validate --all   # --all: headless (no reviewer UI)
.venv/bin/python scripts/uat_det_oracle.py output/$CORPUS/extraction.json "$SRC" --json
```

- `export` **needs `--all`** in headless mode (tasks are discovered-but-unreviewed; without a
  reviewer UI there are no "approved" tasks to export).
- The **oracle re-ingests via `IngestionBridge`** (session-3 fix) so the RUB-05 anchor gate is
  valid on `.docx`. Read `output/$CORPUS/validation-report.md` for the SHACL/structural gates
  (RUB-10/11).

## The judging loop (deterministic first, then probabilistic)

1. **Deterministic oracle** (`scripts/uat_det_oracle.py`) — RUB-05 anchor gate, RUB-03 IRI
   validity + branch membership. Plus `validation-report.md` → RUB-10/11 SHACL. All must PASS.
2. **RUB-01 concept-fit** — this is where the pipeline currently fails. Sample distinct tags,
   verify each concept via **FOLIO-MCP** (`mcp__folio__get_concept`) — is the concept genuinely
   *about* the unit, not a lexical false-friend / country mismap? Also runnable offline via the
   local `folio` package (`from folio import FOLIO; f[iri].preferred_label`).
3. **LLM judges** (subagents, source text in context) — RUB-06 fabrication GATE (grep citation
   tokens over the FULL corpus, account for spelled-out↔abbreviated grounding), RUB-05b anchor
   support, RUB-07 compression, RUB-08 completeness (build section-coverage map from the chapter
   TOC), RUB-09 precision, RUB-12/13/14 usefulness.
4. **Score** per story: weighted-mean/3 ≥ 0.80 **and** all gates green → pass; else iterate.

## Per-story matrix

The S1–S7 persona → probe → book-slice matrix is in
**`docs/campaigns/books-extraction-uat.md`** (§ "User stories → acceptance probes → book slice").
Judge each story against its rubric-focus dimensions; record per-story scores in the evidence
pack (`docs/evidence/books/`).

## Spend & scale

- ~$0.75–$1.00 / chapter (gemini-flash-lite), ~$10 / book, **~$30 for all three** — pre-approved.
- Cost is not the constraint; correctness (B9) is. Pipeline has **no token logging** — report
  app-side spend from provider dashboards (improvement candidate).

## One-command start (next session)

> "resume Lane 2 per `docs/campaigns/books-3book-pass-RUNBOOK.md`: fix B9, re-judge Ch01, then
> run the three-book S1–S7 pass."

Fix B9 → re-extract+re-judge Ch01 → if clean, loop the commands above over the S1–S7 slices
(subagents ingest/judge; main loop decides gates) → evidence pack → per-story score table.

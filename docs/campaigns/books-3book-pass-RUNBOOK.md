# Three-Book S1–S7 Pass — Ready-to-Run Runbook

_Queued 2026-07-07 (Lane 2 session 3). The full three-book extraction+judging pass, packaged
as a one-session start. **This is the next session's entry point** once the gate below is green._

> **Scope note (Damien, QA round-2 q6, 2026-07-07):** the three-book pass was deliberately
> **not run** in session 3. Session 3 verified fixes, re-extracted Ch01 cleanly, and judged it.
> Ch01 did **not** clear (see the ⛔ gate). This runbook is the mechanics for when it does.

---

## ✅ GATE GREEN (2026-07-07, session 4) — Ch01 CLEARED — pass ready on approval

**Both preconditions met; the pass itself stays QUEUED per Damien's round-2 q6 (spend ~$30
only on his go).**

1. **B9 FIXED** (`ce860d4`) — LLM-carried IRIs now gate through the concept-label verifier
   (`docs/solutions/llm-path-unverified-iris.md`, status FIXED). Measured on Ch01 v5 vs v4
   (LLM path): concept-mismatch 75.7% → ~5.2% true; country mismaps 693 → ~2. Follow-on
   discovery bug also fixed (`5ec1e23`, `docs/solutions/proposed-tags-outvote-task-mapping.md`)
   — empty-IRI proposed tags no longer outvote real IRIs in task mapping (v5: 22/22 tasks
   mapped, OWL 22 classes / 248 triples).
2. **Ch01 v5 JUDGED CLEAN — weighted 0.827 ≥ 0.80, ALL GATES PASS** (RUB-05 anchor 372/372 ·
   RUB-06 zero fabrication · RUB-10/11 SHACL non-trivial), completeness 3.0 ≥ 2. Full score
   sheet: evidence pack EP-INSIGHTS-BOOKS-024. New oracle for the concept-fit signal:
   `scripts/uat_concept_verify.py`.

On Damien's approval, proceed with the per-slice commands below. Run
`scripts/uat_concept_verify.py` per slice alongside the det oracle (non-ruler mismatch should
stay low; a spike = B9-class regression). **Also compare each slice's export statistics
(classes/triples) against expectations — an empty graph passes SHACL trivially.**

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

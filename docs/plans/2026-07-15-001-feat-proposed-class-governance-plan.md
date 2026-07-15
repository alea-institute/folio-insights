# Feat Plan — Proposed-Class Governance Pipeline

- **Plan ID:** 2026-07-15-001-feat-proposed-class-governance
- **Status:** approved-for-build (Damien ruling, 2026-07-15)
- **Author:** folio-insights execution agent (CE `/ce:plan` lane)
- **Branch:** `feat/proposed-class-governance`
- **Compounds:** `docs/campaigns/ce-plan-scope.md` (WS4 mapping residue), Ch01 finding EP-INSIGHTS-BOOKS-ANNOT-005 (42 proposed-only units), the `charge→Encumbrance` definition-level blind spot.

## 1. Intent (Damien, verbatim)

> "The system should collect 'Proposed new class' in a list, where (1) an LLM as judge cross-references
> other classes, to avoid duplication (e.g., synonyms), and then (2) a human in the loop (or human on
> the loop) can validate and approve, as necessary."

Every pipeline run already emits `proposed_class` tags — surface concepts the reconciler could not map
to any FOLIO IRI and honestly demoted rather than force-fit (the "honest demotion" behaviour landed in
B9). Today those proposals evaporate into `proposed_classes.json` per-run with no cross-run memory, no
de-duplication, and no path to becoming real FOLIO concepts. This plan turns that exhaust into a
**governed ontology-extension backlog**: collect → judge (dedupe) → human-approve → export.

## 2. Why this shape (design rationale)

**The core blind spot to respect.** WS4 taught us that *label-level* reasoning is what produced
`charge→Encumbrance` and `Rule 26→Russian Federation`: two concepts can share a label string yet be
semantically unrelated. A dedupe judge that only compares **labels** will repeat that mistake in reverse
— it will call a genuinely novel proposal a "duplicate" because its label collides with an unrelated
FOLIO concept, or miss a true synonym whose label differs. Therefore the LLM-judge stage MUST compare
**definitions**, not labels, when deciding NOVEL vs DUPLICATE vs SYNONYM.

**Deterministic-first, LLM-second (same rule as the tagger).** The tagger's winning architecture is
"deterministic exact/alias resolution first, LLM only for the residue." We mirror it: cheap, exact,
reproducible matching eliminates the obvious duplicates ($0, testable), and the LLM-judge only sees the
survivors. This keeps judging affordable and auditable.

**$0 app-side judging.** Per Damien's standing cost discipline and this task's explicit constraint, the
LLM-judge runs **Claude-Code-side** (this agent / its subagents), NOT as an app-side API call. The
pipeline records the judge's verdict + reasoning; it does not itself call an LLM to judge.

**Human-in / on-the-loop.** Approval is a rendered, round-trippable decision artifact in the house
style (execCommand copy-back, recommended pre-selects from the judge). "In the loop" = the human must
approve before export; "on the loop" = the judge's NOVEL verdicts can be batch-approved with the human
spot-checking. Both are supported by the same artifact.

## 3. Data model

### 3.1 Registry (`data/governance/proposed_class_registry.json`)
Persistent, idempotent, append-only-by-default. One entry per **distinct proposal**, keyed by a stable
`proposal_id = "PC-" + sha1(normalized_label + "|" + definition_hash)[:12]`.

```
ProposalEntry:
  proposal_id: str            # stable, content-addressed
  proposed_label: str         # canonical surface form (first-seen casing)
  normalized_label: str       # lower, punctuation-stripped, whitespace-collapsed
  draft_definition: str       # synthesized from supporting spans (Claude-side, $0)
  definition_hash: str        # sha1 of draft_definition, for idempotency
  occurrences: int            # total tag occurrences across all runs
  supporting_units: [         # provenance, capped at N per entry
    {unit_id, chapter, book, source_span, source_text_excerpt}
  ]
  provenance: {books:[...], chapters:[...], runs:[...]}
  first_seen_run: str
  last_seen_run: str
  judge: {                    # filled by the judge stage
    verdict: NOVEL|DUPLICATE_OF|SYNONYM_OF|MERGE_WITH|NEEDS_WORK
    target_iri: str|null      # for DUPLICATE_OF / SYNONYM_OF
    target_proposal_id: str|null   # for MERGE_WITH
    nearest: [{iri,label,definition,cosine_or_note}]  # comparison set
    reasoning: str
    judged_by: str            # "deterministic" | "claude-code:<model>"
    judged_at: iso8601
  } | null
  decision: {                 # filled by human approval import
    status: approved|rejected|merged|needs_work|pending
    note: str
    decided_at: iso8601
  }
```

### 3.2 Extension backlog (`data/governance/ontology_extension_backlog.jsonl`)
Machine-readable, one approved proposal per line, ready for FOLIO submission (label, draft definition,
suggested parent branch if the judge surfaced one, supporting evidence, provenance).

## 4. Stages

### Stage A — Collect (`registry.py: ingest_run`)
- Input: a run's `proposed_classes.json` (+ `discovery.json` for spans/chapter).
- Group by `normalized_label`; synthesize/refresh `draft_definition` from supporting `source_text`.
- Upsert into the registry: idempotent by `(normalized_label, definition_hash)`. Re-running the same
  run is a no-op; a new run appends new entries and increments `occurrences` / merges provenance.
- **Seed:** Ch01 v5 (`output/uat_ta_ch01_v5`) + Ch02 + Ch03 runs.

### Stage B — Judge / dedupe (two sub-stages)
**B1 deterministic (`dedupe.py`), $0, tested:**
- Normalize the label; match against (a) the full FOLIO lexicon (rdfs:label + skos:pref/alt/hidden
  labels from the cached OWL) and (b) other registry entries.
- Exact / alias / normalized-label hit ⇒ mark `DUPLICATE_OF <iri>` or `MERGE_WITH <proposal-id>`
  with `judged_by=deterministic`. These never reach the LLM.
- **Guardrail:** a deterministic label hit against FOLIO is recorded as a *candidate* duplicate but,
  because of the `charge→Encumbrance` lesson, the human artifact still shows the FOLIO concept's
  definition so a label-only collision can be overridden to NOVEL.

**B2 LLM-judge (Claude-Code-side), survivors only, $0 app-side:**
- For each survivor, assemble the nearest existing FOLIO concepts (definition-level: search the OWL
  lexicon + definitions) and the nearest other proposals.
- Verdict per entry: `NOVEL` / `DUPLICATE_OF <iri>` / `SYNONYM_OF <iri>` / `MERGE_WITH <proposal-id>`
  / `NEEDS_WORK`, with definition-grounded reasoning. Written back into the registry `judge` block.

### Stage C — Human approval queue (artifact)
- `scripts/build_approval_queue.py` renders `data/governance/approval-queue.artifact.html`.
- Per entry: proposal + draft definition + evidence spans + judge verdict + **nearest-concept
  comparison table** (label + definition side by side). Affordances: Approve / Reject / Merge /
  Needs-work + free-text note. Judge's recommendation is pre-selected. Copy-answers emits stable-ID
  JSON (execCommand fallback; navigator.clipboard blocked in artifact iframes).
- `scripts/apply_approvals.py` ingests the pasted JSON, writes `decision` blocks, and exports approved
  entries to `ontology_extension_backlog.jsonl`.

### Stage D — Wiring
- A thin hook so future pipeline runs call `ingest_run(output_dir)` after `discover` — idempotent, so
  re-runs are safe. (Manual CLI for now; auto-append documented for the orchestrator.)

## 5. Acceptance criteria
1. Registry seeded from Ch01+Ch02+Ch03; `N_raw` proposals → `N_dedup` after deterministic dedupe → judge
   verdict breakdown reported.
2. `ingest_run` is idempotent: running it twice on the same run leaves the registry byte-identical
   (test-enforced).
3. Deterministic dedupe correctly collapses exact/alias/normalized duplicates against FOLIO and against
   other proposals (test-enforced with fixtures incl. a `charge`-style label-collision override case).
4. LLM-judge verdicts are definition-grounded and recorded with reasoning + provenance.
5. Approval artifact is round-trippable (copy→paste) and its JSON re-imports to produce the backlog file.
6. No new pip dependencies; no app-side LLM calls added.

## 6. Test plan
- `tests/governance/test_proposed_class_registry.py` — idempotency, upsert/merge, occurrence counting,
  provenance union, stable IDs.
- `tests/governance/test_proposed_class_dedupe.py` — exact/alias/normalized FOLIO matches, proposal↔
  proposal merges, the label-collision-override guardrail, and a NOVEL passthrough.

## 7. Out of scope
- Actually submitting to the FOLIO GitHub repo (the backlog file is the hand-off boundary).
- App-side / automated LLM judging (explicitly Claude-side per constraint).
- Embedding-vector similarity infra (definition-level lexical + Claude judgment suffices at this scale).

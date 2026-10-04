# Governance branch inventory (U1, reconciled in U4)

- **Plan:** [`2026-09-30-0914-feat-proposed-class-governance-plan.md`](../2026-09-30-0914-feat-proposed-class-governance-plan.md), unit U1 (KTD1, KTD2).
- **Source:** the historical local branch `feat/proposed-class-governance`, compared with its merge base against `origin/master` commit `5013651`. The merge base is `6c32a7f`, and the branch has 15 commits after it.
- **Method:** `git diff --name-status 6c32a7f feat/proposed-class-governance` lists 80 changed paths. Each code path was read with `git show` or `git diff` only. The branch was never checked out, merged, cherry-picked, rebased or applied. No file under `data/governance/`, `docs/evidence/`, `output/` or `staging/` was opened. Those paths were classified by path and by the migration plan's KTD5 definition.
- **Re-authoring rule:** everything marked "transferred" is rewritten as new work (U1/U2 on `feat/governance-pipeline`, U3/U4 on `feat/governance-u3u4`), with synthetic fixtures only. No historical proposal label, definition or excerpt enters a fixture.

## Decisions

| Decision | Meaning |
|---|---|
| transferred (Un) | Behaviour re-authored in unit Un. Code is rewritten, never copied byte for byte. **Landed** names where it lives now and the commit. |
| transferred (Un, paraphrase) | A learning doc carried only as paraphrase: no quoted headings, excerpts, unit labels or campaign figures. |
| excluded | Not carried. The reason is given. |
| superseded | `origin/master` already holds the change or a better one, or the change is no longer needed. |

## Summary (reconciled in U4, 2026-10-04)

| Decision | U1 plan | Final |
|---|---|---|
| transferred | 47 | 46 |
| excluded | 30 | 30 |
| superseded | 3 | 4 |
| **total** | **80** | **80** |

The one change from the U1 plan: `pyproject.toml` (the spaCy dependency) moved from transfer to
superseded. The tagger's deterministic ruler is the pinned `folio_resolve.FOLIOEntityRuler`, which
needs no spaCy, so no dependency was added. Of the 46 transfers, 5 landed in U1, 8 in U2 and 33
in U3 (U1 `febabc4`; U2 `7b69536` and `8864072`; U3 `3857dc0`, `3ebec1f`, `8306f2d`, `1cf06ed`).
Four learning docs were carried as paraphrase only; two of them (`heading-as-unit-fabrication`,
`verifiable-source-anchoring`) were written from the code without opening the historical file.
The 30 exclusions are 13 paths under `docs/evidence/`, 10 under `data/governance/`, 3
book-campaign scripts, 1 campaign runbook and 3 legacy `.planning` notes. None of them was opened.

## Every changed path

### Governance pipeline (U1–U3)

| Status | Path | Decision | Notes |
|---|---|---|---|
| A | `src/folio_insights/proposals/__init__.py` | transferred (U2) | Rebuilt: re-exports registry, dedupe, lexicon and the storage-backed store. **Landed:** `src/folio_insights/proposals/__init__.py` (`7b69536`); U3 adds the decision and export exports (`3857dc0`). |
| A | `src/folio_insights/proposals/registry.py` | transferred (U2) | Rebuilt around the Phase 13 storage seam. Changes: the ID is keyed by corpus and normalized label, not by an excerpt-derived definition hash. Provenance holds unit IDs and spans, never source text. The draft definition no longer quotes source text. **Landed:** `src/folio_insights/proposals/registry.py` (`7b69536`, `8864072`); U3 adds the `decision` kind (`3857dc0`). |
| A | `src/folio_insights/proposals/dedupe.py` | transferred (U2) | Same verdicts (DUPLICATE_OF, MERGE_WITH, the alias guardrail). Human and model judgments are never overwritten. **Landed:** `src/folio_insights/proposals/dedupe.py` (`7b69536`). |
| A | `src/folio_insights/proposals/lexicon.py` | transferred (U2) | Same OWL regex scan, plus a `from_concepts` constructor for synthetic tests. **Landed:** `src/folio_insights/proposals/lexicon.py` (`7b69536`). |
| A | `scripts/judge_proposals.py` | transferred (U2) | Worklist generation only, offline. It reads and writes proposal state through storage. Worklist items carry no `supporting_excerpt`. `apply_judgments` moves to U3 with the approvals path. **Landed:** `scripts/judge_proposals.py` (`7b69536`); `apply_judgments` landed as the `judgments` subcommand over `ProposalStore.record_judgments` (`3857dc0`). |
| A | `scripts/seed_registry.py` | transferred (U2) | Folded into `scripts/judge_proposals.py collect`. The docstring's historical run and book names are not carried. **Landed:** `scripts/judge_proposals.py collect` (`7b69536`). |
| A | `scripts/folio_resolver.py` | superseded | Duplicates `proposals/lexicon.py` (same regex scan). The lexicon covers it. **Landed:** `src/folio_insights/proposals/lexicon.py`. |
| A | `scripts/build_approval_queue.py` | transferred (U3) | Regenerated from synthetic proposals only (KTD4). Its HTML outputs are never committed. **Landed:** `scripts/build_approval_queue.py` and `src/folio_insights/proposals/queue.py` (`3857dc0`). JSON plus a self-contained HTML page; nothing pre-selected; outputs refused inside git work trees and the corpus root. |
| A | `scripts/apply_approvals.py` | transferred (U3) | Fix in transfer: an invalid status must refuse, not silently become `pending`. Unknown IDs refuse (R4). Replays are idempotent. **Landed:** `scripts/apply_approvals.py` (`apply`, `export`), `src/folio_insights/proposals/decisions.py`, `proposals/export.py` and `ProposalStore.record_decisions` (`3857dc0`). Invalid statuses and unknown IDs refuse the whole batch. |
| A | `tests/proposals/__init__.py` | transferred (U1) | New package. **Landed:** `tests/proposals/__init__.py` (`febabc4`). |
| A | `tests/proposals/test_proposed_class_registry.py` | transferred (U2) | Scenarios rewritten. The historical fixture labels are not reused. **Landed:** `tests/proposals/test_proposal_registry.py` (`7b69536`). |
| A | `tests/proposals/test_proposed_class_dedupe.py` | transferred (U2) | Scenarios rewritten with a synthetic lexicon. **Landed:** `tests/proposals/test_proposal_dedupe.py` (`7b69536`). |
| A | `tests/proposals/test_apply_approvals.py` | transferred (U3) | Fixture strings must be re-authored synthetically. **Landed:** `tests/proposals/test_approvals_and_export.py` (`3857dc0`), synthetic fixtures; the old file was not used for fixtures. |
| A | `docs/plans/2026-07-15-001-feat-proposed-class-governance-plan.md` | transferred (U1) | Inspected: it holds Damien's intent quote and FOLIO labels only, no book text. Carried with a lineage header. **Landed:** Same path (`febabc4`). |

### B4–B9 pipeline fixes (U1 and U3)

| Status | Path | Decision | Notes |
|---|---|---|---|
| M | `src/folio_insights/pipeline/discovery/stages/folio_mapping.py` | transferred (U1) | Empty-IRI tags never vote (R3). Master lacked the guard, and the U1 characterization tests failed without it. **Landed:** Same path (`febabc4`). |
| M | `src/folio_insights/pipeline/stages/folio_tagger.py` | transferred (U3) | B5 branch resolution and label verification, plus B9's gating of LLM-carried IRIs. Known conflict: re-author against the folio-resolve 0.4.0 `LabelResolver`, never transplant. `test_llm_carried_iri_is_currently_trusted_characterization` pins today's behaviour and must change in the same commit. **Landed:** Same path (`3ebec1f`): B9 concept-label verifier on carried IRIs with re-resolution through `LabelResolver`, and B5 `_get_entity_ruler` (loud by default, degraded state in metadata). B5's label/branch enrichment of ruler tags is superseded by master's `_branch_for` / `_label_for`. The characterization test was replaced in the same commit. |
| M | `tests/test_folio_tagging.py` | transferred (U3) | Known conflict. Re-author the B9 regression cases with synthetic IRIs and labels. **Landed:** Same path, `test_b9_*` and `test_b5_*` (`3ebec1f`), synthetic only. |
| M | `tests/test_task_discovery.py` | transferred (U1) | Its two empty-IRI cases are now covered by `tests/proposals/test_current_tagger_characterization.py`. **Landed:** `tests/proposals/test_current_tagger_characterization.py` (`febabc4`). |
| M | `src/folio_insights/pipeline/discovery/orchestrator.py` | transferred (U3) | B4: write and refresh `review.db` after discovery so that `export` can read it. **Landed:** Same path (`1cf06ed`): review.db written after every run; FolioMapping moved after content clustering. |
| M | `src/folio_insights/cli.py` | transferred (U3) | B4: always pass `db_path`, and give a "discovered but unreviewed" export hint. **Landed:** Same path (`1cf06ed`). |
| A | `src/folio_insights/persistence/__init__.py` | transferred (U3) | New package that holds the review schema. **Landed:** Same path (`1cf06ed`). |
| A | `src/folio_insights/persistence/review_db.py` | transferred (U3) | Canonical review schema plus writer. Check it against the Phase 13 storage before choosing SQLite review.db or the corpus context. **Landed:** Same path (`1cf06ed`). Kept as per-corpus SQLite: it holds mutable reviewer state that the append-only Phase 13 journal is not designed for. `api/services/discovery_runner.py` now delegates to `persist_discovery`. |
| M | `api/db/models.py` | transferred (U3) | Becomes a re-export of `persistence.review_db.SCHEMA_SQL`. The −110 lines are the schema moving, not a deletion. **Landed:** Same path, re-export (`1cf06ed`). |
| M | `src/folio_insights/services/owl_serializer.py` | transferred (U3) | B4c: skip proposed classes (`folio_iri=None`) instead of crashing. **Landed:** Same path (`1cf06ed`); units of an IRI-less task are skipped too. |
| M | `tests/test_owl_export.py` | transferred (U3) | B4c regression, with synthetic fixtures. **Landed:** `tests/test_discovery_persistence.py::test_owl_serializer_skips_tasks_without_a_folio_iri` (`1cf06ed`), synthetic. |
| A | `src/folio_insights/services/anchoring.py` | transferred (U3) | Verifiable source anchors (RUB-05). **Landed:** Same path (`8306f2d`). |
| A | `tests/test_anchoring.py` | transferred (U3) | Fixture prose resembles trial-practice text. Re-author it with invented sentences. **Landed:** `tests/test_extraction_safeguards.py` (`8306f2d`), invented sentences; the old file was not used. |
| M | `src/folio_insights/models/knowledge_unit.py` | transferred (U3) | `source_snippet`, `anchor_verified` and `anchor_score` fields. **Landed:** Same path (`8306f2d`). `source_snippet` is also a forbidden proposal-ledger key. |
| M | `src/folio_insights/pipeline/stages/ingestion.py` | transferred (U3) | Anchoring and DOCX re-read fixes. **Landed:** Same path (`8306f2d`). The branch's change here was the binary re-read fix; anchoring happens in boundary detection. |
| M | `src/folio_insights/pipeline/stages/distiller.py` | transferred (U3) | Anchor attachment after distillation. **Landed:** Same path (`8306f2d`). The branch's change here was the B6 defence-in-depth skip. |
| A | `src/folio_insights/services/substance.py` | transferred (U3) | B6 substantive-input guard. **Landed:** Same path (`8306f2d`), synthetic docstring examples. Fixed in transfer: a heading prefix's own period no longer counts as sentence punctuation. |
| A | `tests/test_substance.py` | transferred (U3) | The fixture strings may come from the book (headings and maxims). Re-author them synthetically. **Landed:** `tests/test_extraction_safeguards.py` (`8306f2d`), synthetic lines; the old file was not used. |
| M | `src/folio_insights/pipeline/stages/boundary_detection.py` | transferred (U3) | B7: bounded concurrent Tier-3 and a deterministic sentence-group split. **Landed:** Same path (`8306f2d`). |
| M | `src/folio_insights/config.py` | transferred (U3) | `require_deterministic_iri`, `boundary_*` and `min_substantive_chars` settings. **Landed:** Same path: `require_deterministic_iri` (`3ebec1f`); `boundary_*` and `min_substantive_chars` (`8306f2d`). |
| M | `src/folio_insights/services/bridge/folio_bridge.py` | transferred (U3) | B5 `BridgeIntegrityError` and `get_entity_ruler`. Check them against the current folio-enrich layout first; master still imports the old `AhoCorasickMatcher` path. **Landed:** Same path (`3ebec1f`). `get_entity_ruler` returns the pinned `folio_resolve.FOLIOEntityRuler`; the branch's folio-enrich `app.services.entity_ruler.ruler` (spaCy) route is superseded. |
| M | `tests/test_bridge.py` | transferred (U3) | Bridge integrity regressions. **Landed:** Same path, a live-FOLIO canary (`3ebec1f`); integrity-error cases in `tests/test_folio_tagging.py`. |
| M | `src/folio_insights/quality/output_formatter.py` | transferred (U3) | Adds the `folio_tagger` degraded-mode provenance to the metadata. **Landed:** Same path (`3ebec1f`). |
| M | `src/folio_insights/pipeline/discovery/stages/content_clustering.py` | transferred (U3) | `llm.generate` becomes `llm.complete`. Confirm the provider API on master first. **Landed:** Same path (`1cf06ed`). Confirmed: folio-enrich providers expose `complete`, not `generate`. |
| M | `src/folio_insights/pipeline/discovery/stages/hierarchy_construction.py` | transferred (U3) | Same API rename. **Landed:** Same path (`1cf06ed`). |
| M | `src/folio_insights/services/contradiction_detector.py` | transferred (U3) | Same API rename. **Landed:** Same path (`1cf06ed`). |
| M | `pyproject.toml` | superseded | Adds `spacy>=3.7.0` for the bridge entity ruler. It must be pinned and logged in THIRD-PARTY.md, and only if U3 keeps the ruler path. **Landed:** Not carried. The tagger's deterministic ruler is the pinned `folio_resolve.FOLIOEntityRuler`, which needs no spaCy, and master's bridge does not use folio-enrich's spaCy ruler. No dependency was added, so THIRD-PARTY.md and the locks are unchanged. |
| M | `uv.lock` | superseded | Lockfile churn from the spacy addition. Regenerate it if U3 adds the dependency; never copy it. **Landed:** Not regenerated: no dependency was added (see `pyproject.toml`). |
| M | `.gitignore` | superseded | The branch added `staging/`, which master already ignores (with a stronger comment). **Landed:** Master already ignores `staging/`. |

### Learnings docs (U3, inspected)

| Status | Path | Decision | Notes |
|---|---|---|---|
| A | `docs/solutions/proposed-tags-outvote-task-mapping.md` | transferred (U1) | Inspected: code and run statistics only. Re-authored to point at the new tests. **Landed:** Same path (`febabc4`). |
| A | `docs/solutions/llm-path-unverified-iris.md` | transferred (U3, paraphrase) | Carries run-level metrics and FOLIO labels. Check for unit text before carrying, and carry it with the B9 tagger change. **Landed:** Same path (`3ebec1f`), re-authored: no run figures and no unit labels. |
| A | `docs/solutions/boundary-tier3-serial-llm-stall.md` | transferred (U3, paraphrase) | Performance learning. Check it for unit text. **Landed:** Same path (`8306f2d`), re-authored without campaign measurements. |
| A | `docs/solutions/docx-elementless-binary-reread.md` | transferred (U3) | Binary-reread learning, with no book text in its symptom line. Check the body. **Landed:** Same path (`8306f2d`), re-authored. |
| A | `docs/solutions/sys-path-bridge-staleness.md` | transferred (U3) | Bridge learning. The symptom line is a module error. **Landed:** Same path (`3ebec1f`), re-authored for the folio-resolve ruler. |
| A | `docs/solutions/heading-as-unit-fabrication.md` | transferred (U3, paraphrase) | Its symptom line quotes book-derived headings and an epigraph attribution. Carry only a paraphrase, and when unsure leave it out. **Landed:** Same path (`8306f2d`), written from the code; the historical file was not opened, and nothing from it is quoted. |
| A | `docs/solutions/verifiable-source-anchoring.md` | transferred (U3, paraphrase) | Its symptom line quotes a fragment of a book chapter title. Carry only a paraphrase. **Landed:** Same path (`8306f2d`), written from the code; the historical file was not opened, and nothing from it is quoted. |

### Book-derived evidence and generated data (exclude: KTD5 / R5)

| Status | Path | Decision | Reason |
|---|---|---|---|
| A | `data/governance/.gitignore` | excluded | Generated-data directory. The lexicon cache it ignores is regenerated outside the tree. |
| A | `data/governance/README.md` | excluded | Describes the excluded generated registry. Not opened. |
| A | `data/governance/approval-queue.artifact.html` | excluded | Generated approval queue that carries excerpts (KTD5). |
| A | `data/governance/approval-queue.html` | excluded | Same as above. |
| A | `data/governance/judge_verdicts.json` | excluded | Generated verdicts derived from book proposals. |
| A | `data/governance/judge_verdicts_ch03.json` | excluded | Same as above. |
| A | `data/governance/judge_worklist.json` | excluded | Worklist carrying `supporting_excerpt` book spans. |
| A | `data/governance/judge_worklist_ch03.json` | excluded | Same as above. |
| A | `data/governance/ontology_extension_backlog.jsonl` | excluded | Generated output (empty on the branch). |
| A | `data/governance/proposed_class_registry.json` | excluded | Generated registry carrying `source_text_excerpt` (178k lines). |
| A | `docs/evidence/EVIDENCE.md` | excluded | Evidence index for the book campaign. |
| A | `docs/evidence/books-ch01-annotations/manifest.json` | excluded | Book annotation evidence. |
| A | `docs/evidence/books-ch01-annotations/pack.artifact.html` | excluded | Same as above. |
| A | `docs/evidence/books-ch01-annotations/pack.html` | excluded | Same as above. |
| A | `docs/evidence/books-ch02-annotations/manifest.json` | excluded | Same as above. |
| A | `docs/evidence/books-ch02-annotations/pack.artifact.html` | excluded | Same as above. |
| A | `docs/evidence/books-ch02-annotations/pack.html` | excluded | Same as above. |
| A | `docs/evidence/books-ch03-annotations/manifest.json` | excluded | Same as above. |
| A | `docs/evidence/books-ch03-annotations/pack.artifact.html` | excluded | Same as above. |
| A | `docs/evidence/books-ch03-annotations/pack.html` | excluded | Same as above. |
| M | `docs/evidence/books/manifest.json` | excluded | Changed `docs/evidence/books/pack.*` (KTD5). |
| M | `docs/evidence/books/pack.html` | excluded | Same as above. |
| M | `docs/evidence/books/pack.json` | excluded | Same as above. |

### Book-campaign scripts and notes (exclude)

| Status | Path | Decision | Reason |
|---|---|---|---|
| A | `scripts/build_annotation_viewer.py` | excluded | Exists only to render the book annotation evidence packs. No reusable non-evidence logic, and the governance queue is rebuilt separately. |
| A | `scripts/uat_concept_verify.py` | excluded | Book-UAT measurement oracle that reads campaign run outputs. The verifier logic it measures lands in the tagger (U3). |
| A | `scripts/uat_det_oracle.py` | excluded | Book-UAT deterministic oracle tied to campaign runs. The anchor logic lands in `services/anchoring.py` (U3). |
| A | `docs/campaigns/books-3book-pass-RUNBOOK.md` | excluded | A runbook for one book campaign. It names book runs and scores, and holds no reusable procedure for this pipeline. |
| M | `.planning/debug/resolved/corpus-processing-no-extraction.md` | excluded | Legacy GSD debug note that records book-campaign status. GSD history is archived (migration plan U1). |
| M | `.planning/debug/resolved/create-corpus-silent-fail.md` | excluded | Same as above. |
| M | `.planning/debug/resolved/llm-api-config.md` | excluded | Same as above. It also names the source book. |

Coverage check: the path column of these tables, sorted, equals `git diff --name-only 6c32a7f feat/proposed-class-governance` sorted (80 paths, no difference).

## U1 characterization (KTD2)

`tests/proposals/test_current_tagger_characterization.py` pins `origin/master` before any transfer:

- **Matched tags.** A path-supplied IRI and a label that clears the folio-resolve bar both produce matched tags with non-empty IRIs.
- **Proposed tags.** A label that resolves to nothing becomes `proposed_class` with `iri == ''`. A mixed batch splits accordingly.
- **LLM-carried IRIs.** An IRI the LLM path carried was trusted as-is. U3's B9 transfer changed this deliberately (`3ebec1f`): the test is now `test_llm_carried_iri_must_pass_the_concept_label_verifier`.
- **`proposed_classes.json` shape.** Only empty-IRI tags appear, de-duplicated by exact label, so case variants survive. The registry normalizes them.
- **Discovery vote.** The most frequent matched IRI wins. Empty-IRI tags never vote and never dilute the confidence. A proposals-only candidate routes to `proposed_siblings`.

**Finding:** the three empty-IRI discovery tests FAILED on clean `origin/master`. The B9 follow-on guard had never merged. U1 re-authors the guard (`folio_mapping.py`), and all ten tests pass.

## U4 reconciliation and exclusion evidence

- **Every entry has a final decision.** The 80 rows above are each `transferred` (46),
  `excluded` (30) or `superseded` (4), and each transfer names where it landed.
- **Exclusion check.** `scripts/check_exclusions.py` (commit `72ecfc2`) audits the paths of every
  new commit against `data/governance/`, `docs/evidence/`, `output/` and `staging/`, and scans
  allowed text artifacts (at HEAD and in every blob a new commit added or modified) for non-empty
  excerpt values, derived definitions, book provenance and generated proposal artifacts. It prints
  metadata only. Its tests (`tests/proposals/test_exclusion_scanner.py`) prove detection of a
  synthetic non-empty excerpt and no false positives on field-name references in source code or
  prose.
- **Result.** See the plan's Execution Evidence (U3/U4) for the recorded runs.

# Governance branch inventory (U1)

- **Plan:** [`2026-09-30-0914-feat-proposed-class-governance-plan.md`](../2026-09-30-0914-feat-proposed-class-governance-plan.md), unit U1 (KTD1, KTD2).
- **Source:** the historical local branch `feat/proposed-class-governance`, compared with its merge base against `origin/master` commit `5013651`. The merge base is `6c32a7f`, and the branch has 15 commits after it.
- **Method:** `git diff --name-status 6c32a7f feat/proposed-class-governance` lists 80 changed paths. Each code path was read with `git show` or `git diff` only. The branch was never checked out, merged, cherry-picked, rebased or applied. No file under `data/governance/`, `docs/evidence/`, `output/` or `staging/` was opened. Those paths were classified by path and by the migration plan's KTD5 definition.
- **Re-authoring rule:** everything marked "transfer" is rewritten as new work on `feat/governance-pipeline`, with synthetic fixtures only. No historical proposal label, definition or excerpt enters a fixture.

## Decisions

| Decision | Meaning |
|---|---|
| transfer (Un) | Behaviour re-authored in unit Un. Code is rewritten, never copied byte for byte. |
| exclude | Not carried. The reason is given. |
| superseded | `origin/master` already holds the change or a better one. |

## Summary

| Decision | Count |
|---|---|
| transfer | 47 |
| exclude | 30 |
| superseded | 3 |
| **total** | **80** |

Of the 47 transfers, 5 land in U1, 8 in U2 and 34 in U3. Four U3 docs may only be carried paraphrased (marked "redact"). The 30 exclusions are 13 paths under `docs/evidence/`, 10 under `data/governance/`, 3 book-campaign scripts, 1 campaign runbook and 3 legacy `.planning` notes.

## Every changed path

### Governance pipeline (U1–U3)

| Status | Path | Decision | Notes |
|---|---|---|---|
| A | `src/folio_insights/proposals/__init__.py` | transfer (U2) | Rebuilt: re-exports registry, dedupe, lexicon and the storage-backed store. |
| A | `src/folio_insights/proposals/registry.py` | transfer (U2) | Rebuilt around the Phase 13 storage seam. Changes: the ID is keyed by corpus and normalized label, not by an excerpt-derived definition hash. Provenance holds unit IDs and spans, never source text. The draft definition no longer quotes source text. |
| A | `src/folio_insights/proposals/dedupe.py` | transfer (U2) | Same verdicts (DUPLICATE_OF, MERGE_WITH, the alias guardrail). Human and model judgments are never overwritten. |
| A | `src/folio_insights/proposals/lexicon.py` | transfer (U2) | Same OWL regex scan, plus a `from_concepts` constructor for synthetic tests. |
| A | `scripts/judge_proposals.py` | transfer (U2) | Worklist generation only, offline. It reads and writes proposal state through storage. Worklist items carry no `supporting_excerpt`. `apply_judgments` moves to U3 with the approvals path. |
| A | `scripts/seed_registry.py` | transfer (U2) | Folded into `scripts/judge_proposals.py collect`. The docstring's historical run and book names are not carried. |
| A | `scripts/folio_resolver.py` | superseded | Duplicates `proposals/lexicon.py` (same regex scan). The lexicon covers it. |
| A | `scripts/build_approval_queue.py` | transfer (U3) | Regenerated from synthetic proposals only (KTD4). Its HTML outputs are never committed. |
| A | `scripts/apply_approvals.py` | transfer (U3) | Fix in transfer: an invalid status must refuse, not silently become `pending`. Unknown IDs refuse (R4). Replays are idempotent. |
| A | `tests/proposals/__init__.py` | transfer (U1) | New package. |
| A | `tests/proposals/test_proposed_class_registry.py` | transfer (U2) | Scenarios rewritten. The historical fixture labels are not reused. |
| A | `tests/proposals/test_proposed_class_dedupe.py` | transfer (U2) | Scenarios rewritten with a synthetic lexicon. |
| A | `tests/proposals/test_apply_approvals.py` | transfer (U3) | Fixture strings must be re-authored synthetically. |
| A | `docs/plans/2026-07-15-001-feat-proposed-class-governance-plan.md` | transfer (U1) | Inspected: it holds Damien's intent quote and FOLIO labels only, no book text. Carried with a lineage header. |

### B4–B9 pipeline fixes (U1 and U3)

| Status | Path | Decision | Notes |
|---|---|---|---|
| M | `src/folio_insights/pipeline/discovery/stages/folio_mapping.py` | transfer (U1) | Empty-IRI tags never vote (R3). Master lacked the guard, and the U1 characterization tests failed without it. |
| M | `src/folio_insights/pipeline/stages/folio_tagger.py` | transfer (U3) | B5 branch resolution and label verification, plus B9's gating of LLM-carried IRIs. Known conflict: re-author against the folio-resolve 0.4.0 `LabelResolver`, never transplant. `test_llm_carried_iri_is_currently_trusted_characterization` pins today's behaviour and must change in the same commit. |
| M | `tests/test_folio_tagging.py` | transfer (U3) | Known conflict. Re-author the B9 regression cases with synthetic IRIs and labels. |
| M | `tests/test_task_discovery.py` | transfer (U1) | Its two empty-IRI cases are now covered by `tests/proposals/test_current_tagger_characterization.py`. |
| M | `src/folio_insights/pipeline/discovery/orchestrator.py` | transfer (U3) | B4: write and refresh `review.db` after discovery so that `export` can read it. |
| M | `src/folio_insights/cli.py` | transfer (U3) | B4: always pass `db_path`, and give a "discovered but unreviewed" export hint. |
| A | `src/folio_insights/persistence/__init__.py` | transfer (U3) | New package that holds the review schema. |
| A | `src/folio_insights/persistence/review_db.py` | transfer (U3) | Canonical review schema plus writer. Check it against the Phase 13 storage before choosing SQLite review.db or the corpus context. |
| M | `api/db/models.py` | transfer (U3) | Becomes a re-export of `persistence.review_db.SCHEMA_SQL`. The −110 lines are the schema moving, not a deletion. |
| M | `src/folio_insights/services/owl_serializer.py` | transfer (U3) | B4c: skip proposed classes (`folio_iri=None`) instead of crashing. |
| M | `tests/test_owl_export.py` | transfer (U3) | B4c regression, with synthetic fixtures. |
| A | `src/folio_insights/services/anchoring.py` | transfer (U3) | Verifiable source anchors (RUB-05). |
| A | `tests/test_anchoring.py` | transfer (U3) | Fixture prose resembles trial-practice text. Re-author it with invented sentences. |
| M | `src/folio_insights/models/knowledge_unit.py` | transfer (U3) | `source_snippet`, `anchor_verified` and `anchor_score` fields. |
| M | `src/folio_insights/pipeline/stages/ingestion.py` | transfer (U3) | Anchoring and DOCX re-read fixes. |
| M | `src/folio_insights/pipeline/stages/distiller.py` | transfer (U3) | Anchor attachment after distillation. |
| A | `src/folio_insights/services/substance.py` | transfer (U3) | B6 substantive-input guard. |
| A | `tests/test_substance.py` | transfer (U3) | The fixture strings may come from the book (headings and maxims). Re-author them synthetically. |
| M | `src/folio_insights/pipeline/stages/boundary_detection.py` | transfer (U3) | B7: bounded concurrent Tier-3 and a deterministic sentence-group split. |
| M | `src/folio_insights/config.py` | transfer (U3) | `require_deterministic_iri`, `boundary_*` and `min_substantive_chars` settings. |
| M | `src/folio_insights/services/bridge/folio_bridge.py` | transfer (U3) | B5 `BridgeIntegrityError` and `get_entity_ruler`. Check them against the current folio-enrich layout first; master still imports the old `AhoCorasickMatcher` path. |
| M | `tests/test_bridge.py` | transfer (U3) | Bridge integrity regressions. |
| M | `src/folio_insights/quality/output_formatter.py` | transfer (U3) | Adds the `folio_tagger` degraded-mode provenance to the metadata. |
| M | `src/folio_insights/pipeline/discovery/stages/content_clustering.py` | transfer (U3) | `llm.generate` becomes `llm.complete`. Confirm the provider API on master first. |
| M | `src/folio_insights/pipeline/discovery/stages/hierarchy_construction.py` | transfer (U3) | Same API rename. |
| M | `src/folio_insights/services/contradiction_detector.py` | transfer (U3) | Same API rename. |
| M | `pyproject.toml` | transfer (U3) | Adds `spacy>=3.7.0` for the bridge entity ruler. It must be pinned and logged in THIRD-PARTY.md, and only if U3 keeps the ruler path. |
| M | `uv.lock` | superseded | Lockfile churn from the spacy addition. Regenerate it if U3 adds the dependency; never copy it. |
| M | `.gitignore` | superseded | The branch added `staging/`, which master already ignores (with a stronger comment). |

### Learnings docs (U3, inspected)

| Status | Path | Decision | Notes |
|---|---|---|---|
| A | `docs/solutions/proposed-tags-outvote-task-mapping.md` | transfer (U1) | Inspected: code and run statistics only. Re-authored to point at the new tests. |
| A | `docs/solutions/llm-path-unverified-iris.md` | transfer (U3, redact) | Carries run-level metrics and FOLIO labels. Check for unit text before carrying, and carry it with the B9 tagger change. |
| A | `docs/solutions/boundary-tier3-serial-llm-stall.md` | transfer (U3, redact) | Performance learning. Check it for unit text. |
| A | `docs/solutions/docx-elementless-binary-reread.md` | transfer (U3) | Binary-reread learning, with no book text in its symptom line. Check the body. |
| A | `docs/solutions/sys-path-bridge-staleness.md` | transfer (U3) | Bridge learning. The symptom line is a module error. |
| A | `docs/solutions/heading-as-unit-fabrication.md` | transfer (U3, redact) | Its symptom line quotes book-derived headings and an epigraph attribution. Carry only a paraphrase, and when unsure leave it out. |
| A | `docs/solutions/verifiable-source-anchoring.md` | transfer (U3, redact) | Its symptom line quotes a fragment of a book chapter title. Carry only a paraphrase. |

### Book-derived evidence and generated data (exclude: KTD5 / R5)

| Status | Path | Decision | Reason |
|---|---|---|---|
| A | `data/governance/.gitignore` | exclude | Generated-data directory. The lexicon cache it ignores is regenerated outside the tree. |
| A | `data/governance/README.md` | exclude | Describes the excluded generated registry. Not opened. |
| A | `data/governance/approval-queue.artifact.html` | exclude | Generated approval queue that carries excerpts (KTD5). |
| A | `data/governance/approval-queue.html` | exclude | Same as above. |
| A | `data/governance/judge_verdicts.json` | exclude | Generated verdicts derived from book proposals. |
| A | `data/governance/judge_verdicts_ch03.json` | exclude | Same as above. |
| A | `data/governance/judge_worklist.json` | exclude | Worklist carrying `supporting_excerpt` book spans. |
| A | `data/governance/judge_worklist_ch03.json` | exclude | Same as above. |
| A | `data/governance/ontology_extension_backlog.jsonl` | exclude | Generated output (empty on the branch). |
| A | `data/governance/proposed_class_registry.json` | exclude | Generated registry carrying `source_text_excerpt` (178k lines). |
| A | `docs/evidence/EVIDENCE.md` | exclude | Evidence index for the book campaign. |
| A | `docs/evidence/books-ch01-annotations/manifest.json` | exclude | Book annotation evidence. |
| A | `docs/evidence/books-ch01-annotations/pack.artifact.html` | exclude | Same as above. |
| A | `docs/evidence/books-ch01-annotations/pack.html` | exclude | Same as above. |
| A | `docs/evidence/books-ch02-annotations/manifest.json` | exclude | Same as above. |
| A | `docs/evidence/books-ch02-annotations/pack.artifact.html` | exclude | Same as above. |
| A | `docs/evidence/books-ch02-annotations/pack.html` | exclude | Same as above. |
| A | `docs/evidence/books-ch03-annotations/manifest.json` | exclude | Same as above. |
| A | `docs/evidence/books-ch03-annotations/pack.artifact.html` | exclude | Same as above. |
| A | `docs/evidence/books-ch03-annotations/pack.html` | exclude | Same as above. |
| M | `docs/evidence/books/manifest.json` | exclude | Changed `docs/evidence/books/pack.*` (KTD5). |
| M | `docs/evidence/books/pack.html` | exclude | Same as above. |
| M | `docs/evidence/books/pack.json` | exclude | Same as above. |

### Book-campaign scripts and notes (exclude)

| Status | Path | Decision | Reason |
|---|---|---|---|
| A | `scripts/build_annotation_viewer.py` | exclude | Exists only to render the book annotation evidence packs. No reusable non-evidence logic, and the governance queue is rebuilt separately. |
| A | `scripts/uat_concept_verify.py` | exclude | Book-UAT measurement oracle that reads campaign run outputs. The verifier logic it measures lands in the tagger (U3). |
| A | `scripts/uat_det_oracle.py` | exclude | Book-UAT deterministic oracle tied to campaign runs. The anchor logic lands in `services/anchoring.py` (U3). |
| A | `docs/campaigns/books-3book-pass-RUNBOOK.md` | exclude | A runbook for one book campaign. It names book runs and scores, and holds no reusable procedure for this pipeline. |
| M | `.planning/debug/resolved/corpus-processing-no-extraction.md` | exclude | Legacy GSD debug note that records book-campaign status. GSD history is archived (migration plan U1). |
| M | `.planning/debug/resolved/create-corpus-silent-fail.md` | exclude | Same as above. |
| M | `.planning/debug/resolved/llm-api-config.md` | exclude | Same as above. It also names the source book. |

Coverage check: the path column of these tables, sorted, equals `git diff --name-only 6c32a7f feat/proposed-class-governance` sorted (80 paths, no difference).

## U1 characterization (KTD2)

`tests/proposals/test_current_tagger_characterization.py` pins `origin/master` before any transfer:

- **Matched tags.** A path-supplied IRI and a label that clears the folio-resolve bar both produce matched tags with non-empty IRIs.
- **Proposed tags.** A label that resolves to nothing becomes `proposed_class` with `iri == ''`. A mixed batch splits accordingly.
- **LLM-carried IRIs.** An IRI the LLM path carried is still trusted as-is. U3's B9 transfer changes this deliberately.
- **`proposed_classes.json` shape.** Only empty-IRI tags appear, de-duplicated by exact label, so case variants survive. The registry normalizes them.
- **Discovery vote.** The most frequent matched IRI wins. Empty-IRI tags never vote and never dilute the confidence. A proposals-only candidate routes to `proposed_siblings`.

**Finding:** the three empty-IRI discovery tests FAILED on clean `origin/master`. The B9 follow-on guard had never merged. U1 re-authors the guard (`folio_mapping.py`), and all ten tests pass.

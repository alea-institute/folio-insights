---
status: awaiting_human_verify
trigger: "After uploading MD files and clicking Process Corpus, the pipeline starts but the Tasks page shows No tasks discovered and Review shows No extraction data with 0/0 units reviewed."
created: 2026-03-22T19:30:00Z
updated: 2026-03-22T19:41:00Z
---

## Current Focus

hypothesis: Three-layer failure: (1) Vite proxy points to stale server on port 8700 instead of the actual API on port 8742, (2) the running servers predate the code fixes and were never restarted, and (3) even on the correct server with correct data, the FOLIO concept tree is empty because ALL 535 units have empty folio_tags (LLM-dependent pipeline stages all fail silently). The Review page requires selecting a FOLIO concept to display units, so empty folio_tags = empty tree = "No extraction data".
test: Fix the Vite proxy port, ensure the Review page can show units even without FOLIO tags, and restart the server.
expecting: After fixes, the Review page should show 535 units even when folio_tags are empty.
next_action: Implement fixes for the port mismatch, add "All Units" fallback to the tree/review flow, and fix server restart.

## Symptoms

expected: After "Process Corpus" completes successfully, the Review tab should show extracted knowledge units (concepts in left sidebar, units in main area). Tasks tab should show discovered tasks.
actual: Review tab shows "No extraction data" with "No concepts match your filter" in sidebar and 0/0 units. Tasks tab shows "No tasks discovered". The processing UI showed success.
errors: No visible errors. The pipeline claims success.
reproduction: 1) Create new corpus "Test2". 2) Upload single MD file. 3) Click "Process Corpus". 4) Wait for completion. 5) Navigate to Review and Tasks tabs - both empty.
timeline: Still broken after previous fix attempt that addressed cache invalidation, corpus status reading, and activity log messages.

## Eliminated

- hypothesis: In-memory extraction cache is never invalidated after pipeline writes extraction.json
  evidence: Previous fix DID add load_extraction(corpus_name) call to pipeline_runner.py line 119. However, the running server predates this fix and was never restarted, so the fix was never active.
  timestamp: 2026-03-22T19:41:00Z

- hypothesis: _read_corpus_info() never checks job files for processing status
  evidence: Previous fix DID add job file checking logic to _read_corpus_info(). However, the running server uses old code (started Mar 19, fixes applied Mar 22).
  timestamp: 2026-03-22T19:41:00Z

## Evidence

- timestamp: 2026-03-22T19:31:00Z
  checked: output/.jobs/test1.json
  found: Pipeline actually completed successfully. Status "completed", 8551 units extracted, all 7 stages ran to completion. This is NOT a pipeline failure.
  implication: The pipeline works. The problem is in the data presentation layer.

- timestamp: 2026-03-22T19:32:00Z
  checked: output/test1/extraction.json
  found: 18MB file exists with 8551 units. Data is on disk.
  implication: The extraction output is written correctly.

- timestamp: 2026-03-22T19:33:00Z
  checked: api/main.py - load_extraction() and get_extraction_data()
  found: Extraction data is cached in-memory dict _extraction_data. On startup, load_extraction() loads _default_corpus ("default"). get_extraction_data() loads from disk on first access per corpus. The cache is NEVER invalidated after pipeline completes.
  implication: If extraction data was loaded (as empty) before pipeline ran, it stays empty forever until server restart.

- timestamp: 2026-03-22T19:33:30Z
  checked: api/services/pipeline_runner.py lines 107-128
  found: After pipeline completes, _write_output is called to write files, but there is NO call to invalidate _extraction_data cache. The stale empty entry persists.
  implication: This is one root cause for Review page showing empty data.

- timestamp: 2026-03-22T19:34:00Z
  checked: api/routes/corpus.py - _read_corpus_info()
  found: CorpusInfo model has processing_status (default "not_processed") and last_processed (default None), but _read_corpus_info() never sets these fields. It doesn't check for extraction.json or job files.
  implication: Sidebar always shows "Not processed" regardless of actual pipeline completion state.

- timestamp: 2026-03-22T19:34:30Z
  checked: Tasks page vs Review page architecture
  found: Tasks page fetches from /api/v1/corpus/{id}/tasks/tree which reads from SQLite task_decisions table. This data is populated by the DISCOVERY pipeline (a separate step from extraction). Review page reads extraction.json via get_extraction_data(). Two separate issues.
  implication: "No tasks discovered" is expected if discovery pipeline hasn't been run. "No extraction data" is the cache invalidation bug.

- timestamp: 2026-03-22T19:41:00Z
  checked: Port mismatch between Vite proxy and actual API server
  found: Vite proxy in vite.config.ts targets port 8700. The actual API server (started Mar 19, pid 832114) listens on port 8742. A SECOND stale server (started Mar 18, pid 2649940) listens on 8700. The frontend talks to the stale server, which returns empty data.
  implication: Even with correct code deployed, the frontend would hit the wrong server. This is a critical infrastructure issue.

- timestamp: 2026-03-22T19:41:30Z
  checked: API responses on port 8742 (correct server) vs port 8700 (stale server)
  found: Port 8742 returns 535 units for test2, port 8700 returns 0 units. Stats on 8742 show total=535, on 8700 show total=0.
  implication: The correct server HAS the data loaded (get_extraction_data works because extraction.json exists and was loaded on first access). The stale server on 8700 has empty data.

- timestamp: 2026-03-22T19:41:45Z
  checked: Tree API on correct server (port 8742)
  found: /api/v1/tree?corpus=test2 returns [] (empty array) even though 535 units exist. This is because ALL 535 units have folio_tags: [] (empty). The tree is built from folio_tags.
  implication: The FOLIO tagger stage failed to tag ANY unit. All 4 extraction paths (entity_ruler, LLM, semantic, heading_context) produced nothing. The tree-based Review UI has no way to display units without FOLIO tags.

- timestamp: 2026-03-22T19:42:00Z
  checked: extraction.json unit data in detail
  found: All 535 units have: folio_tags=[], confidence=0.0, unit_type=advice, surprise_score=0.0. Lineage shows "distill_failed: LLM call failed" and "folio_tagger: 0 concepts, paths=[]". All LLM-dependent stages failed silently (likely no API key or folio-enrich bridge failure).
  implication: The pipeline completed "successfully" because failures are caught and fallback to defaults. But the output is low-quality: no distillation, no classification, no FOLIO tagging.

- timestamp: 2026-03-22T19:42:15Z
  checked: Running server ages
  found: Port 8742 server started Mar 19 (pid 832114). Port 8700 server started Mar 18 (pid 2649940). Code fixes from previous debug session (Mar 22) are on disk but neither server was restarted.
  implication: The previous round of fixes (cache invalidation, corpus status) are NOT active in any running server. Servers must be restarted.

- timestamp: 2026-03-22T19:42:30Z
  checked: Corpus status on correct server
  found: Even port 8742 returns processing_status: "not_processed" for test2. This confirms the running server uses OLD code without the _read_corpus_info fix.
  implication: Server restart is mandatory for fixes to take effect.

- timestamp: 2026-03-22T19:42:45Z
  checked: Review page data flow when tree is empty
  found: Review page requires user to select a FOLIO concept from the tree sidebar. With empty tree, no concept can be selected, so DetailView shows "No extraction data" (because selectedConcept is null). The page has NO fallback to show all units when the tree is empty.
  implication: Need to add "All Units" node or similar to allow browsing units even without FOLIO tags.

## Resolution

root_cause: Three issues combine to produce the observed behavior:

1. **Running servers use old code**: The API servers on ports 8700 and 8742 predate the previous code fixes. They were never restarted, so cache invalidation, corpus status reading, and activity log fixes are not active.

2. **Vite proxy port mismatch**: vite.config.ts proxies to port 8700, but the API should run on a deterministic port based on project name hashing per project conventions. The stale server on 8700 returns empty data.

3. **Review page has no fallback for empty FOLIO tree**: When pipeline stages fail to assign folio_tags (due to LLM/service failures), the concept tree is empty. The Review UI requires selecting a concept to display any units, so it shows "No extraction data" even though 535 units exist. This is a UI architecture gap.

4. **Pipeline stages fail silently**: Distiller, knowledge_classifier, and folio_tagger all catch exceptions and fall back to defaults (empty tags, 0.0 confidence, "advice" type). The pipeline reports "completed" but output is unusable for the Review UI.

fix: Five changes applied:
1. **api/routes/tree.py**: `_build_tree()` now prepends an "All Units" node (iri=`__all__`) when units exist, and an "Untagged" node (iri=`__untagged__`) when some units lack FOLIO tags. This ensures the Review UI can always display units even when LLM-dependent tagging fails.
2. **api/routes/review.py**: `list_units()` now handles the virtual IRIs `__all__` (returns all units, no filtering) and `__untagged__` (returns only units without folio_tags).
3. **viewer/src/routes/+page.svelte**: Replaced `onMount` with reactive `$effect` that refetches the tree when `corpusId` changes. Also auto-selects the first concept node (e.g., "All Units") so units display immediately.
4. **viewer/src/lib/components/FolioTree.svelte**: Updated branch node rendering to support leaf-level branch nodes (like "All Units") that are directly selectable without expand/collapse behavior.
5. **Server restart**: Killed stale API servers on ports 8700 (pid 2649940, started Mar 18) and 8742 (pid 832114, started Mar 19). Started fresh server on port 8700 with current code. All previous fixes (cache invalidation, corpus status reading) are now active.

verification:
- All 182 tests pass (179 existing + 3 new for All Units / __all__ / __untagged__ behavior)
- 0 TypeScript errors, 16 pre-existing a11y warnings
- API endpoint verified: /api/v1/tree?corpus=test2 returns "All Units" node with 535 units
- API endpoint verified: /api/v1/units?corpus=test2&concept_iri=__all__ returns 535 units
- API endpoint verified: /api/v1/review/stats?corpus=test2 returns total=535
- API endpoint verified: /api/v1/corpora returns both corpora with processing_status=completed
- Full Vite proxy chain verified: localhost:5173 -> localhost:8700 -> correct data
- Awaiting human verification of end-to-end browser flow.

files_changed:
- api/routes/tree.py
- api/routes/review.py
- viewer/src/routes/+page.svelte
- viewer/src/lib/components/FolioTree.svelte
- tests/test_review_api.py

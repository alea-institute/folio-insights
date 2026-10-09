# sys.path bridge retirement — 2026-10-09

folio-insights used to reach into sibling folio-enrich and folio-mapper checkouts. It did this by putting `settings.folio_enrich_path` on `sys.path`, or by loading files with `importlib`.
The deployed Dockerfiles do not ship those checkouts.
So in production `get_folio_service()` and `get_embedding_service()` raised, and their callers fell back to `None`.
The normalizer and the citation extractor also fell back silently, and `IngestionBridge` raised.

Rule (plan R20–R21): each seam is either replaced by an in-repo implementation with a parity test, or kept with a recorded reason.
A replacement ships only if its parity test passes.

Source of the vendored code: folio-enrich `origin/main` @ `510a652` (MIT, same author).
The local folio-enrich working tree used for the comparison is identical to that commit for every vendored path.

## Outcome per seam

| Seam | Outcome | Replacement module | Parity evidence | Remaining reason |
|---|---|---|---|---|
| `folio_bridge.get_normalizer` (enrich `normalization/normalizer.py`) | Retired | `folio_insights.services.text_normalization` | `test_normalizer_parity_with_enrich`: 9 texts (legal prose, "U.S.", "Fed. R. Civ. P.", lists, unicode, questions, a 9 KB multi-chunk text, messy whitespace, empty), split/whitespace/chunk (4 size settings)/normalize_and_chunk all equal. Golden: `test_normalizer_golden_*` | — |
| `folio_bridge.get_citation_extractor` (enrich `individual/citation_extractor.py`) | Retired | `folio_insights.services.citation_extraction` | `test_citation_extractor_parity_with_enrich[absent\|stub\|real]`: 5 texts, model dumps equal (minus random uuid). `real` passed against eyecite 2.7.8 + citeurl 12.0.4 installed in a throwaway path. In the normal suite it skips because eyecite is not installed. Golden: `test_citation_extractor_golden_with_stub_eyecite`, `..._without_libraries_returns_nothing` | — |
| `folio_bridge.get_folio_service` (enrich `folio/folio_service.py`) | Retired | `folio_insights.services.folio_ontology.FolioOntologyService` | `test_folio_label_index_parity`: 69,368 labels, identical keys and identical (IRI, label_type, matched_label) for every key. Concept and label counts are equal. `test_folio_search_and_lookup_parity`: 40 probe labels, top-5 and top-1 `search_by_label` give equal (IRI, score) and equal full concept dataclasses. `search_by_prefix` is equal, and `get_concept` is equal for every IRI seen plus 2 misses. `test_folio_service_feeds_deterministic_ruler`: B5 canary on the in-repo service | — |
| `folio_bridge.get_embedding_service` (enrich `embedding/service.py`) | Retired | `folio_insights.services.embedding.EmbeddingService` | `test_embedding_parity_with_enrich`: `similarity_batch` and `similarity` on 6 pairs within 1e-4. `index_size` is 0 in both. After indexing 5 labels, `search` returns equal order and metadata, with scores within 1e-4. Contract test with a stub model | — |
| `mapper_bridge.MapperBridge` (folio-mapper `file_parser.parse_file`) | Kept | — | `tests/test_mapper_bridge.py` (11 tests): CSV/TSV fallback, BOM, blank rows, `.xlsx`→no rows in the fallback, the mapper path through a stub `parse_file`, and the load-failure and parse-failure fallbacks | `parse_file` imports `openpyxl` (not a dependency) plus folio-mapper's `app.models.parse_models` and `app.services.hierarchy_detector`. Those files are outside this task's read scope, and none of them is importable here. In this environment the importlib load always fails (`ModuleNotFoundError: openpyxl`, verified), so the stdlib CSV fallback is the behavior that runs. `.xlsx` stays on the bridge |
| `ingestion_bridge.IngestionBridge` (enrich `ingestion/registry.py` + `models/document.py`) | Kept | — | Construction now raises `IngestionBridgeUnavailableError` (a `FileNotFoundError`), whose message names the fix | Needs enrich's whole multi-format registry (7 ingestors) and their format libraries: pypdf, beautifulsoup4, striprtf, olefile, python-docx. Of these, only python-docx is installed here. Vendoring it is a separate task |
| `llm_bridge`, `reconciliation_bridge`, entity ruler / B5 canary | Already off sys.path (earlier) | unchanged | `verify_deterministic_bridge` / `BridgeIntegrityError` semantics are unchanged (`tests/test_ktd7_failures_surface.py`, `tests/test_folio_tagging.py`) | — |

`folio_bridge.py` keeps its getter names and return contracts. None of the four retired getters touches `sys.path` any more; tests assert that `sys.path` is unchanged with the enrich path pointed at a missing directory.
`_ensure_folio_enrich_path` remains for `IngestionBridge` and for the integration parity tests.

## Behavior notes (unchanged from the bridge, now explicit)

- **Normalizer.** `split_sentences` uses NuPunkt when it is installed and a regex otherwise. NuPunkt is not a folio-insights dependency, so the regex runs, as it did through the bridge: the bridge ran enrich's code inside this venv. That regex splits inside "Fed. R. Civ. P." (see the golden values). Adding NuPunkt would improve those splits, but it is a behavior change, not part of this retirement.
- **Citations.** eyecite and citeurl are optional imports, exactly as in enrich. Neither is installed, so `knowledge_classifier._detect_citations` finds nothing today, with or without the bridge. The spec asked to declare eyecite. That was deliberately not done, because declaring it would start reclassifying every citation-bearing unit as `KnowledgeType.CITATION`, which is a product decision. See the report.
- **FOLIO lemma tier.** It uses the same logic and the same on-disk cache as enrich (`~/.folio-enrich/cache/lemmas/labels_<owl-hash>_v1.pkl`). A box that already holds enrich's lemma cache therefore indexes the same 968 lemma keys. Computing new lemmas needs spaCy plus `en_core_web_sm`, and neither is a folio-insights dependency. Without the cache, the lemma tier is empty. enrich degrades the same way when spaCy is missing.
- **Embeddings.** Like the `EmbeddingService.get_instance()` that insights received from enrich, the service starts with an empty label index. So `folio_tagger`'s semantic path stays gated off (`index_size == 0`), and only `similarity_batch` (reconciler triage) does work. The model is shared with the deduplicator and the boundary detector through `boundary.semantic._get_model`.
- **Production.** Deployed images now get a working FOLIO service, embedding service, normalizer and citation extractor where they previously got `None` or silent fallbacks. Ingestion of the formats that go through `IngestionBridge` still needs the folio-enrich checkout.

## Running the parity tests

The integration-marked parity tests skip when no folio-enrich checkout is found at `settings.folio_enrich_path`.
To run them from a worktree that has no sibling checkout:

```
FOLIO_INSIGHTS_FOLIO_ENRICH_PATH=<path-to>/folio-enrich/backend \
  .venv/bin/python -m pytest tests/test_bridge_retirement_parity.py -m integration
```

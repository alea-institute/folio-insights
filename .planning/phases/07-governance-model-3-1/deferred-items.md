# Phase 07 Deferred Items

Issues discovered during Phase 07 execution that are out of scope for the
current plan but tracked here for later phases / environment fixes.

## Pre-existing collection errors (Plan 07-01 discovery)

The following test files fail to import due to environment / dep issues that
predate Phase 07 and are unrelated to the governance substrate. They are NOT
caused by Plan 07-01 changes (the failures reproduce on master at commit
5d469c4 before any 07-01 edit).

### `fastapi` not installed

- `tests/test_corpus_api.py`
- `tests/test_discovery_api.py`
- `tests/test_export_api.py`
- `tests/test_processing_api.py`
- `tests/test_review_api.py`
- `tests/test_task_review_api.py`
- `tests/test_upload_api.py`

These import `from api import main as api_main`, which requires `fastapi`.
`fastapi` is not in `pyproject.toml` deps. Either add the dep, mark these
tests `@pytest.mark.integration`, or skip them when `fastapi` is missing.

### `folio-enrich` repository not on disk

- `tests/test_ingestion.py::test_ingest_directory`
- `tests/test_ingestion.py::test_preserve_structure`
- `tests/test_ingestion.py::test_variable_length`
- `tests/test_ingestion.py::test_skip_processed`
- `tests/test_ingestion.py::test_xml_ingestion`

These tests require `folio-enrich/backend/` cloned at a configured path. The
folio_bridge service raises `FileNotFoundError` when not present. They are
correctly marked elsewhere as `integration` tests in spirit; they should
either be marked `@pytest.mark.integration` or auto-skipped when the
folio-enrich path is unset.

## Plan 07-01 scope confirmation

Plan 07-01 in-scope tests (`tests/governance/`) all pass (15/15). The
601-passed / 5-failed result on the wider tests/ suite is unrelated to
governance and tracks the two pre-existing environment issues above.

---
title: Web-tier runtime deps (fastapi/uvicorn) undeclared in pyproject → API tests fail to collect
date: 2026-07-05
tags: [dependencies, pyproject, fastapi, testing, docker, ci, folio-insights]
severity: medium
area: build/packaging
symptom: "ModuleNotFoundError: No module named 'fastapi' — 7 api/ test files fail to collect locally/CI"
---

## Problem

Running the test suite locally (or in a fresh CI checkout) failed to collect the 7
`api/` test suites (`test_review_api.py`, `test_export_api.py`, `test_corpus_api.py`,
`test_discovery_api.py`, `test_task_review_api.py`, `test_upload_api.py`,
`test_processing_api.py`) with `ModuleNotFoundError: No module named 'fastapi'`.

The confusing part: **the app deploys and runs fine on Railway**, so "fastapi" clearly
worked *somewhere*.

## Root cause

The web tier (`api/main.py`) is a **FastAPI** app, but `fastapi`, `uvicorn[standard]`,
and `python-multipart` were **never declared in `pyproject.toml`**. They were installed
**ad-hoc inside `Dockerfile.web`** (L48-60):

```dockerfile
# requirements.lock is an INCOMPLETE Plan 05 draft — it omits fastapi/uvicorn/...
&& uv pip install --system --no-cache-dir fastapi "uvicorn[standard]" python-multipart
```

So the deployed image had them, but **any environment that installs from the manifest**
(`pip/uv install -e '.[dev]'` → local dev, CI) did not. The declared dependency graph
did not match shipped reality. Only `sse-starlette` (→ starlette) was declared, which is
not enough for `import fastapi`.

## Fix

Declare the web-tier runtime deps as **core** dependencies in `pyproject.toml`:

```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.30.0",
"python-multipart>=0.0.9",
```

Then reinstall. Note this repo's venv is **uv-managed and has no `pip` shim** — use:

```bash
VIRTUAL_ENV="$PWD/.venv" uv pip install -e '.[dev]'
```

Result: `import fastapi` works; all 1021 tests collect; `1002 passed` on the quick suite
(`-m "not slow and not gate3 and not gate4 and not gate5"`). Docker builds are unaffected
(they still install from `requirements.lock` + the same explicit packages).

Commit: `181b2b7`.

## Same bug, second surface: bridge-tier deps (books-UAT de-risk, 2026-07-05)

The identical failure mode recurred one layer down. folio-insights imports **folio-enrich's
code via a `sys.path` bridge** (`config.folio_enrich_path` → `../folio-enrich/backend`), so
folio-enrich's own runtime deps are **not pulled transitively** and were undeclared:

- `python-docx` — its absence made `.docx` ingestion silently read the raw ZIP archive as
  UTF-8 → "units" of PK-header binary. (All Trial Advocacy chapters are `.docx`.)
- `rapidfuzz` + `marisa-trie` — back folio-python's search index. Without them folio-python
  logs *"Disabling search functionality"* at import and **every** FOLIO tag degrades to an
  un-IRI'd `proposed_class` (looks like "the ontology is missing everything").

Fix: declared `python-docx>=1.1.0`, `rapidfuzz>=3.9.0`, `marisa-trie>=1.2.0` as core deps.
After: 607/621 units carried real FOLIO IRIs (529 distinct), 0 spurious proposed classes.

**The general rule this reinforces:** *any code your process imports — whether via a package,
a Dockerfile `RUN`, or a `sys.path` bridge to a sibling repo — its runtime deps must be in
YOUR manifest.* A bridge that imports `app.*` modules does not bring their `pip` deps with it.

## Prevention

- **A dependency your shipped code imports belongs in the manifest**, not only in a
  Dockerfile `RUN`. Ad-hoc Docker installs silently desync the manifest from reality and
  the gap only surfaces off the deployment path (local/CI).
- Follow-up (not yet done): regenerate `requirements.lock` / `requirements.dev.lock` so the
  pinned locks also include fastapi/uvicorn/python-multipart, then the Dockerfiles can drop
  the explicit `uv pip install fastapi …` line entirely and rely on the deps chain (the
  `Dockerfile` comment at L39-44 already anticipates this).
- Smell test when "it works deployed but not locally": diff what the Dockerfile installs
  against what `pyproject.toml` declares.

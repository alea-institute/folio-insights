# Phase 00 Deferred Items (out-of-scope discoveries)

## 00-04: tests/test_corpus_api.py — FastAPI ImportError

**Discovered during:** Plan 00-04 Task 3 final pytest run (2026-04-22).
**Symptom:**
```
tests/test_corpus_api.py:11: in <module>
    from api import main as api_main
api/main.py:11: in <module>
    from fastapi import FastAPI
E   ModuleNotFoundError: No module named 'fastapi'
```

**Scope assessment:** Pre-existing environmental issue. `fastapi` is a transitive
dependency (via `sse-starlette`) that is not directly declared in `pyproject.toml`
`[project.dependencies]`. The venv was bootstrapped before `sse-starlette` was
added, so the bare FastAPI import path is missing. The existing `Dockerfile`
worked around this with a belt-and-suspenders `uv pip install fastapi "uvicorn[standard]" python-multipart` (see Phase 01-01 decision in STATE.md),
and `Dockerfile.web` inherits that fallback. The local dev venv does not.

**Root cause:** `pyproject.toml` does not list `fastapi` / `uvicorn[standard]`
/ `python-multipart` as direct dependencies even though `api/main.py` imports
them unconditionally. Relies on transitive resolution that is fragile.

**Not fixed here because:**
- The adapter-static -> adapter-node swap in Plan 00-04 cannot possibly cause
  a Python FastAPI import error.
- Phase 0 tests (tests/bench/) all pass (5/5).
- A pyproject.toml dependency declaration change is a Phase 01-01 lineage
  concern, not a Phase 0 foundation-gate concern.

**Suggested fix (future plan):** Add `fastapi`, `uvicorn[standard]`,
`python-multipart` to `[project.dependencies]` in `pyproject.toml` and re-lock
`uv.lock`. Remove the belt-and-suspenders install from Dockerfile.web stage 2.

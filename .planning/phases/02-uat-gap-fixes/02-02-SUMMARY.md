---
phase: 02-uat-gap-fixes
plan: 02
issue: I-2
status: complete
executed: 2026-04-19
---

# Plan 02-02 — Summary: Bundle Export 422 → 404 Parity (UAT I-2)

## Files Changed

- `api/routes/export.py` — BundleRequest body optional + 404 parity in handler
- `tests/test_export_api.py` — strengthened existing 404 test + added 2 new regression tests

## Diff Highlights

```python
# api/routes/export.py — before
class BundleRequest(BaseModel):
    formats: list[str]

@router.post("/corpus/{corpus_id}/export/bundle")
async def export_bundle(corpus_id: str, body: BundleRequest) -> Response:
    ...

# api/routes/export.py — after
class BundleRequest(BaseModel):
    formats: list[str] = ["owl", "ttl"]

@router.post("/corpus/{corpus_id}/export/bundle")
async def export_bundle(
    corpus_id: str, body: BundleRequest | None = None
) -> Response:
    ...
    if not approved:
        raise HTTPException(status_code=404, detail="No approved tasks to export")
    if body is None:
        body = BundleRequest()
```

## Deviation From Plan

The plan prescribed "append three new test functions" but `test_export_bundle_404_no_approved`
already existed in the suite (checking status code only, not detail body). To avoid a duplicate
function name, the existing test was **strengthened** with the detail assertion, and only the
two truly new tests were appended:

- `test_export_bundle_404_no_approved` (strengthened — now asserts detail body)
- `test_export_bundle_404_no_approved_missing_body` (new — parity for missing body)
- `test_export_bundle_404_no_tasks_at_all` (new — parity for zero task_decisions rows)

Net: +2 tests, not +3. Baseline 197 → final 199 (plan target was 200).

## Before/After Curl Sketch

```
# before
$ curl -s -o /dev/null -w "%{http_code}" -X POST .../corpus/<empty>/export/bundle
422
$ curl -s .../corpus/<empty>/export/bundle
(empty body)

# after
$ curl -s -o /dev/null -w "%{http_code}" -X POST .../corpus/<empty>/export/bundle
404
$ curl -s .../corpus/<empty>/export/bundle
{"detail":"No approved tasks to export"}
```

## Acceptance Criteria

- 4 targeted tests pass: `test_export_bundle_404_no_approved`,
  `test_export_bundle_404_no_approved_missing_body`,
  `test_export_bundle_404_no_tasks_at_all`, `test_export_bundle_returns_zip` ✓
- Full pytest suite: `199 passed` (baseline 197 + 2 new) ✓
- `grep -c "No approved tasks to export" api/routes/export.py` → 5 (4 siblings + bundle) ✓
- `grep -c "body: BundleRequest | None = None" api/routes/export.py` → 1 ✓

## Self-Check: PASSED

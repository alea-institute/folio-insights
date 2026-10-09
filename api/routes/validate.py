"""``POST /validate``: SHACL validation of one candidate shard (Phase 11 SHACL-05).

Accepts a candidate shard as JSON and returns the pyshacl report against the
Phase 11 suite (the six hand-written shapes, the Pydantic-generated shapes and
the vocab shapes). Nothing is stored and nothing is logged.

* If the candidate passes the model (``shards.records.load_shard_record``,
  which also migrates legacy versions), the report covers the current-version
  record storage would persist.
* If it fails the model, the report covers the candidate as sent, so SHACL
  still names every field-level problem. ``model_valid`` is false, and
  ``model_errors`` lists the error locations and types, never the values.
* Only the local tier applies. Cross-shard rules (supersession alignment,
  reciprocity) need a corpus, so this endpoint does not check them.
  ``folio-insights storage validate`` covers them for a stored corpus.

Bounded by construction (review P1-2 / P2-3):

* **Input.** The body is capped at 1 MiB, by ``Content-Length`` and again while
  streaming. JSON nesting is capped at ``MAX_DEPTH``, every list at
  ``MAX_LIST_ITEMS`` and the whole document at ``MAX_JSON_VALUES``. The
  rendered graph is capped at ``MAX_TRIPLES``. All of this is checked before
  pyshacl runs: 413 for size, 422 for depth or malformed input. pyshacl also
  runs under a ``TIMEOUT_S`` deadline (503).
* **Output.** At most ``MAX_RESULTS`` results and ``MAX_MODEL_ERRORS`` model
  errors, each with a total count. No ``sh:value`` and no pyshacl text report
  is returned, so an input value (a reflected SSN, say) is never echoed back.

Valid and invalid candidates both return 200: the report is the answer.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

# Deliberately without api.auth.WRITE_GUARD (drain plan U5): POST /validate is a read. It
# validates the candidate in the request body and stores nothing, so it stays open like every
# other read. tests/api/test_auth.py lists it as the one read-only POST; a route added here
# that writes must declare Depends(require_operator) or that test fails.
router = APIRouter(tags=["validation"])

MAX_BODY_BYTES = 1 << 20
MAX_DEPTH = 32
MAX_LIST_ITEMS = 128
MAX_JSON_VALUES = 20_000
MAX_TRIPLES = 5_000
MAX_RESULTS = 200
MAX_MODEL_ERRORS = 50
TIMEOUT_S = 15.0


class _Refused(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_EXAMPLE = {
    "summary": "A minimal simple assertion",
    "value": {
        "shard_type": "simple_assertion",
        "shard_iri": "urn:folio:shard/0123456789abcdef0123456789abcdef",
        "provenance_hash": "0" * 64,
        "source_uri": "urn:x:source",
        "source_span": "synthetic span",
        "extracted_at": "2026-01-01T00:00:00Z",
        "first_extractor_did": "did:key:zExample",
        "triple": {"subject": "s", "predicate": "p", "object": "o"},
        "sense": "sense",
        "reference": "urn:folio:concept/x",
        "logical_form_imputed": "P(s, o)",
        "layer": "L1_definitional",
        "predication_mode": "per_se",
        "fork": "analytic",
        "epistemic_status": "authority_only",
        "verification_method": "textual_citation",
        "framework_id": "us.example",
        "speech_act": "holding",
        "extractor_version": "1.0",
        "extraction_prompt_hash": "0" * 64,
        "extractor_model": "example-model",
        "confidence": 0.9,
        "bfo_category": "continuant_independent",
    },
}


class ShaclResultOut(BaseModel):
    focus: str = Field(description="The focus node (shard IRI, or a blank node of a nested value).")
    path: str | None = Field(None, description="The property path, when the constraint has one.")
    component: str = Field(description="The SHACL constraint component, e.g. MinCountConstraintComponent.")
    severity: Literal["Violation", "Warning", "Info"]
    message: str = Field(description="The shape's fixed message (never contains input values).")
    source_shape: str | None = None


class ValidationReportOut(BaseModel):
    conforms: bool = Field(description="True when there is no Violation (Warnings do not count).")
    engine: Literal["pyshacl"] = "pyshacl"
    tier: Literal["local"] = "local"
    model_valid: bool = Field(description="Whether the candidate passes the Pydantic shard model.")
    model_errors: list[str] = Field(default_factory=list, description="Model error locations and types (no values), at most 50.")
    model_errors_total: int = 0
    source_schema_version: int | None = None
    suite_digest: str
    violations: int = Field(description="Total Violations (all of them, not only those listed).")
    warnings: int = Field(description="Total Warnings and Infos.")
    results: list[ShaclResultOut] = Field(description="At most 200 results, Violations first.")
    results_total: int
    results_truncated: bool
    note: str = (
        "Local tier only: cross-shard rules (supersession) need a corpus; "
        "run `folio-insights storage validate` on a stored corpus for those."
    )


def _check_structure(candidate: Any) -> None:
    """Iterative bounds walk (no recursion, so hostile nesting cannot crash it)."""
    stack: list[tuple[Any, int]] = [(candidate, 1)]
    seen = 0
    while stack:
        value, depth = stack.pop()
        seen += 1
        if seen > MAX_JSON_VALUES:
            raise _Refused(413, f"candidate has more than {MAX_JSON_VALUES} JSON values")
        if depth > MAX_DEPTH:
            raise _Refused(422, f"candidate nests deeper than {MAX_DEPTH} levels")
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            if len(value) > MAX_LIST_ITEMS:
                raise _Refused(413, f"a list in the candidate has more than {MAX_LIST_ITEMS} items")
            stack.extend((v, depth + 1) for v in value)


def _model_errors(exc: Exception) -> list[str]:
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['type']}"
            for err in exc.errors(include_url=False, include_input=False, include_context=False)
        ]
    return [type(exc).__name__]


def _validate(candidate: dict[str, Any]) -> ValidationReportOut:
    from pydantic import ValidationError

    from folio_insights.shapes import pyshacl_adapter
    from folio_insights.shapes.compiled import term_text
    from folio_insights.shapes.rendering import render_shard
    from folio_insights.shapes.suite import default_suite
    from folio_insights.shards import MalformedEnvelopeRecord, UnsupportedEnvelopeVersion
    from folio_insights.shards.records import dump_shard_record, load_shard_record

    suite = default_suite()
    data: dict[str, Any] = candidate
    model_valid, errors, version = True, [], None
    try:
        loaded = load_shard_record(candidate)
        data = json.loads(dump_shard_record(loaded.shard))
        version = loaded.source_schema_version
    except (ValidationError, UnsupportedEnvelopeVersion, MalformedEnvelopeRecord, TypeError) as exc:
        model_valid, errors = False, _model_errors(exc)
    graph, _node = render_shard(data)
    triples = sum(len(v) for props in graph.nodes.values() for v in props.values())
    if triples > MAX_TRIPLES:
        raise _Refused(413, f"candidate renders to {triples} triples (limit {MAX_TRIPLES})")
    report = pyshacl_adapter.validate(graph, suite.paths, local_only=True)
    results = []
    for r in report.results:
        severity = str(r["severity"]).rsplit("#", 1)[-1]
        results.append(
            ShaclResultOut(
                focus=term_text(r["focus"]) if r["focus"] else "",
                path=r["path"],
                component=str(r["component"]).rsplit("#", 1)[-1],
                severity=severity,  # type: ignore[arg-type]
                message=(r["message"] or [""])[0],
                source_shape=str(r["source_shape"]) if r["source_shape"] is not None else None,
            )
        )
    results.sort(key=lambda x: (x.severity != "Violation", x.path or "", x.component))
    violations = sum(1 for r in results if r.severity == "Violation")
    return ValidationReportOut(
        conforms=report.conforms,
        model_valid=model_valid,
        model_errors=errors[:MAX_MODEL_ERRORS],
        model_errors_total=len(errors),
        source_schema_version=version,
        suite_digest=suite.digest,
        violations=violations,
        warnings=len(results) - violations,
        results=results[:MAX_RESULTS],
        results_total=len(results),
        results_truncated=len(results) > MAX_RESULTS,
    )


@router.post(
    "/validate",
    response_model=ValidationReportOut,
    summary="Validate a candidate shard against the SHACL suite",
    responses={
        413: {"description": "Body over 1 MiB, or a list, document or rendered graph over its cap."},
        422: {"description": "Body is not a JSON object, or nests too deeply."},
        503: {"description": "Validation exceeded its time bound."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "description": (
                            "A candidate shard record (any of the five subtypes; "
                            "legacy schema_version 1 records are migrated first)."
                        ),
                        "additionalProperties": True,
                    },
                    "examples": {"simple_assertion": _EXAMPLE},
                }
            },
        }
    },
)
async def validate_shard(request: Request) -> ValidationReportOut:
    """Return the pyshacl report for one candidate shard (nothing is stored)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="candidate shard larger than 1 MiB")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="candidate shard larger than 1 MiB")
        chunks.append(chunk)
    try:
        candidate = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="body is not valid JSON") from None
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object (one shard)")
    try:
        _check_structure(candidate)
        return await asyncio.wait_for(asyncio.to_thread(_validate, candidate), timeout=TIMEOUT_S)
    except _Refused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.detail) from None
    except RecursionError:
        raise HTTPException(status_code=422, detail="candidate nests too deeply") from None
    except TimeoutError:
        raise HTTPException(status_code=503, detail="validation exceeded its time bound") from None


__all__ = ["router"]

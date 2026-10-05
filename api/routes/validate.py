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

Valid and invalid candidates both return 200: the report is the answer.
A body that is not a JSON object returns 422, and a body over 1 MiB 413.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["validation"])

MAX_BODY_BYTES = 1 << 20

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
    message: str
    value: str | None = Field(None, description="The offending value node, when there is one.")
    source_shape: str | None = None


class ValidationReportOut(BaseModel):
    conforms: bool = Field(description="True when there is no Violation (Warnings do not count).")
    engine: Literal["pyshacl"] = "pyshacl"
    tier: Literal["local"] = "local"
    model_valid: bool = Field(description="Whether the candidate passes the Pydantic shard model.")
    model_errors: list[str] = Field(default_factory=list, description="Model error locations and types (no values).")
    source_schema_version: int | None = None
    suite_digest: str
    violations: int
    warnings: int
    results: list[ShaclResultOut]
    report_text: str = Field(description="pyshacl's text report.")
    note: str = (
        "Local tier only: cross-shard rules (supersession) need a corpus; "
        "run `folio-insights storage validate` on a stored corpus for those."
    )


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
    except (ValidationError, UnsupportedEnvelopeVersion, MalformedEnvelopeRecord) as exc:
        model_valid, errors = False, _model_errors(exc)
    graph, _node = render_shard(data)
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
                value=term_text(r["value"]) if r["value"] else None,
                source_shape=str(r["source_shape"]) if r["source_shape"] is not None else None,
            )
        )
    results.sort(key=lambda x: (x.severity != "Violation", x.path or "", x.component))
    violations = sum(1 for r in results if r.severity == "Violation")
    return ValidationReportOut(
        conforms=report.conforms,
        model_valid=model_valid,
        model_errors=errors,
        source_schema_version=version,
        suite_digest=suite.digest,
        violations=violations,
        warnings=len(results) - violations,
        results=results,
        report_text=report.text,
    )


@router.post(
    "/validate",
    response_model=ValidationReportOut,
    summary="Validate a candidate shard against the SHACL suite",
    responses={
        413: {"description": "Body larger than 1 MiB."},
        422: {"description": "Body is not a JSON object."},
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
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="candidate shard larger than 1 MiB")
    try:
        candidate = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=422, detail="body is not valid JSON") from None
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object (one shard)")
    return await asyncio.to_thread(_validate, candidate)


__all__ = ["router"]

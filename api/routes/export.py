"""Multi-format export endpoints for task hierarchy.

GET /api/v1/corpus/{corpus_id}/export/markdown   -- Markdown outline
GET /api/v1/corpus/{corpus_id}/export/json       -- JSON tree
GET /api/v1/corpus/{corpus_id}/export/html       -- HTML report
GET /api/v1/corpus/{corpus_id}/export/owl        -- OWL RDF/XML
GET /api/v1/corpus/{corpus_id}/export/ttl        -- Turtle
GET /api/v1/corpus/{corpus_id}/export/jsonld     -- JSON-LD (JSONL)
GET /api/v1/corpus/{corpus_id}/export/validation -- SHACL validation report
POST /api/v1/corpus/{corpus_id}/export/bundle    -- ZIP bundle of selected formats
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["export"])


def _output_dir() -> Path:
    """Lazy import to avoid circular dependency with api.main."""
    from api.main import _output_dir

    return _output_dir


async def _load_export_data(corpus_id: str) -> tuple[list[dict], dict[str, list[dict]], list[dict], dict]:
    """Load task data from SQLite and extraction.json for export.

    Returns (tasks, units_by_task, contradictions, metadata).
    """
    from api.main import get_db_for_corpus, get_extraction_data

    db = await get_db_for_corpus(corpus_id)
    try:
        # Load tasks
        cursor = await db.execute(
            "SELECT * FROM task_decisions WHERE corpus_name = ? "
            "ORDER BY canonical_order, label",
            (corpus_id,),
        )
        task_rows = await cursor.fetchall()

        if not task_rows:
            raise HTTPException(status_code=404, detail="No discovered tasks found")

        tasks = [
            {
                "id": r["task_id"],
                "label": r["edited_label"] or r["label"],
                "folio_iri": r["folio_iri"],
                "parent_task_id": r["parent_task_id"],
                "is_procedural": bool(r["is_procedural"]),
                "canonical_order": r["canonical_order"],
                "is_manual": bool(r["is_manual"]),
                "status": r["status"],
            }
            for r in task_rows
        ]

        # Load unit links
        link_cursor = await db.execute(
            "SELECT task_id, unit_id FROM task_unit_links WHERE corpus_name = ?",
            (corpus_id,),
        )
        link_rows = await link_cursor.fetchall()

        task_unit_map: dict[str, list[str]] = {}
        for r in link_rows:
            task_unit_map.setdefault(r["task_id"], []).append(r["unit_id"])

        # Load extraction data for unit details
        data = get_extraction_data(corpus_id)
        all_units = {u["id"]: u for u in data.get("units", [])}

        units_by_task: dict[str, list[dict]] = {}
        for tid, uids in task_unit_map.items():
            units_by_task[tid] = [all_units[uid] for uid in uids if uid in all_units]

        # Load contradictions
        contra_cursor = await db.execute(
            "SELECT * FROM contradictions WHERE corpus_name = ?",
            (corpus_id,),
        )
        contra_rows = await contra_cursor.fetchall()
        contradictions = [
            {
                "task_id": r["task_id"],
                "unit_id_a": r["unit_id_a"],
                "unit_id_b": r["unit_id_b"],
                "nli_score": r["nli_score"],
                "contradiction_type": r["contradiction_type"],
                "resolution": r["resolution"],
            }
            for r in contra_rows
        ]

        metadata = {
            "corpus": corpus_id,
            "total_tasks": len(tasks),
            "total_units": len(all_units),
        }

        return tasks, units_by_task, contradictions, metadata

    finally:
        await db.close()


@router.get("/corpus/{corpus_id}/export/markdown")
async def export_markdown(corpus_id: str) -> PlainTextResponse:
    """Return task hierarchy as Markdown outline."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    exporter = TaskExporter()
    md = exporter.export_markdown(tasks, units_by_task)
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/corpus/{corpus_id}/export/json")
async def export_json(corpus_id: str) -> JSONResponse:
    """Return task hierarchy as structured JSON."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    exporter = TaskExporter()
    data = exporter.export_json(tasks, units_by_task, contradictions, metadata)
    return JSONResponse(content=data)


@router.get("/corpus/{corpus_id}/export/html")
async def export_html(corpus_id: str) -> HTMLResponse:
    """Return task hierarchy as HTML report."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    exporter = TaskExporter()
    html = exporter.export_html(tasks, units_by_task, contradictions, metadata)
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# OWL / Turtle / JSON-LD / Validation / Bundle endpoints
# ---------------------------------------------------------------------------


def _get_approved_tasks(tasks: list[dict]) -> list[dict]:
    """Filter to approved tasks only."""
    return [t for t in tasks if t.get("status") == "approved"]


@router.get("/corpus/{corpus_id}/export/owl")
async def export_owl(corpus_id: str) -> Response:
    """Return OWL ontology as RDF/XML."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    approved = _get_approved_tasks(tasks)
    if not approved:
        raise HTTPException(status_code=404, detail="No approved tasks to export")

    db_path = _output_dir() / corpus_id / "review.db"
    output_dir = _output_dir() / corpus_id

    exporter = TaskExporter()
    rdfxml, _turtle, _changelog = await exporter.export_owl(
        approved, units_by_task, contradictions, metadata, db_path, output_dir
    )
    return Response(
        content=rdfxml,
        media_type="application/rdf+xml",
        headers={
            "Content-Disposition": f'attachment; filename="folio-insights-{corpus_id}.owl"',
        },
    )


@router.get("/corpus/{corpus_id}/export/ttl")
async def export_ttl(corpus_id: str) -> Response:
    """Return OWL ontology as Turtle."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    approved = _get_approved_tasks(tasks)
    if not approved:
        raise HTTPException(status_code=404, detail="No approved tasks to export")

    db_path = _output_dir() / corpus_id / "review.db"
    output_dir = _output_dir() / corpus_id

    exporter = TaskExporter()
    _rdfxml, turtle, _changelog = await exporter.export_owl(
        approved, units_by_task, contradictions, metadata, db_path, output_dir
    )
    return Response(
        content=turtle,
        media_type="text/turtle",
        headers={
            "Content-Disposition": f'attachment; filename="folio-insights-{corpus_id}.ttl"',
        },
    )


@router.get("/corpus/{corpus_id}/export/jsonld")
async def export_jsonld(corpus_id: str) -> Response:
    """Return per-task JSON-LD chunks as JSONL."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, _contradictions, _metadata = await _load_export_data(corpus_id)
    approved = _get_approved_tasks(tasks)
    if not approved:
        raise HTTPException(status_code=404, detail="No approved tasks to export")

    db_path = _output_dir() / corpus_id / "review.db"
    output_dir = _output_dir() / corpus_id

    exporter = TaskExporter()
    jsonl = await exporter.export_jsonld(
        approved, units_by_task, db_path, output_dir
    )
    return Response(
        content=jsonl,
        media_type="application/jsonlines",
        headers={
            "Content-Disposition": f'attachment; filename="folio-insights-{corpus_id}.jsonld"',
        },
    )


@router.get("/corpus/{corpus_id}/export/validation")
async def export_validation(corpus_id: str) -> JSONResponse:
    """Return SHACL validation results as JSON."""
    from src.folio_insights.services.owl_serializer import OWLSerializer
    from src.folio_insights.services.shacl_validator import SHACLValidator
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    approved = _get_approved_tasks(tasks)
    if not approved:
        raise HTTPException(status_code=404, detail="No approved tasks to export")

    db_path = _output_dir() / corpus_id / "review.db"
    output_dir = _output_dir() / corpus_id

    # Build graph via export_owl (creates IRI map and serializes)
    exporter = TaskExporter()
    await exporter.export_owl(
        approved, units_by_task, contradictions, metadata, db_path, output_dir
    )

    # Now build graph for validation
    from src.folio_insights.services.iri_manager import IRIManager

    iri_manager = IRIManager(db_path)
    iri_map: dict[str, str] = {}
    corpus = metadata.get("corpus", corpus_id)
    for task in approved:
        if task.get("folio_iri"):
            iri_map[task["id"]] = task["folio_iri"]
        else:
            iri_map[task["id"]] = await iri_manager.get_or_create_iri(
                task["id"], "task", corpus
            )
    for task in approved:
        for unit in units_by_task.get(task["id"], []):
            iri_map[unit["id"]] = await iri_manager.get_or_create_iri(
                unit["id"], "unit", corpus
            )

    serializer = OWLSerializer()
    graph = serializer.build_graph(
        approved, units_by_task, iri_map, contradictions, metadata
    )

    validator = SHACLValidator()
    report = validator.generate_report(graph)

    return JSONResponse(content={
        "conforms": report.conforms,
        "checks": [
            {"name": c.name, "status": c.status, "details": c.details}
            for c in report.checks
        ],
        "markdown": report.markdown,
    })


class BundleRequest(BaseModel):
    """Request body for export bundle."""
    formats: list[str]


@router.post("/corpus/{corpus_id}/export/bundle")
async def export_bundle(corpus_id: str, body: BundleRequest) -> Response:
    """Generate and return a ZIP bundle of requested export formats."""
    from src.folio_insights.services.task_exporter import TaskExporter

    tasks, units_by_task, contradictions, metadata = await _load_export_data(corpus_id)
    approved = _get_approved_tasks(tasks)
    if not approved:
        raise HTTPException(status_code=404, detail="No approved tasks to export")

    db_path = _output_dir() / corpus_id / "review.db"
    output_dir = _output_dir() / corpus_id
    output_dir.mkdir(parents=True, exist_ok=True)

    exporter = TaskExporter()
    files_to_bundle: dict[str, str] = {}

    requested = {f.strip().lower() for f in body.formats}

    # OWL and Turtle
    if "owl" in requested or "ttl" in requested:
        rdfxml, turtle, changelog = await exporter.export_owl(
            approved, units_by_task, contradictions, metadata, db_path, output_dir
        )
        if "owl" in requested:
            files_to_bundle[f"folio-insights-{corpus_id}.owl"] = rdfxml
        if "ttl" in requested:
            files_to_bundle[f"folio-insights-{corpus_id}.ttl"] = turtle
        if changelog:
            files_to_bundle["CHANGELOG.md"] = changelog

    # JSON-LD
    if "jsonld" in requested:
        jsonl = await exporter.export_jsonld(
            approved, units_by_task, db_path, output_dir
        )
        files_to_bundle[f"folio-insights-{corpus_id}.jsonld"] = jsonl

    # HTML browsable
    if "html" in requested:
        html = exporter.export_browsable_html(
            approved, units_by_task, contradictions, metadata
        )
        files_to_bundle[f"folio-insights-{corpus_id}.html"] = html

    # Markdown
    if "md" in requested:
        md = exporter.export_markdown(approved, units_by_task)
        files_to_bundle[f"folio-insights-{corpus_id}.md"] = md

    # Validation report
    from src.folio_insights.services.owl_serializer import OWLSerializer
    from src.folio_insights.services.iri_manager import IRIManager

    iri_manager = IRIManager(db_path)
    iri_map: dict[str, str] = {}
    corpus = metadata.get("corpus", corpus_id)
    for task in approved:
        if task.get("folio_iri"):
            iri_map[task["id"]] = task["folio_iri"]
        else:
            iri_map[task["id"]] = await iri_manager.get_or_create_iri(
                task["id"], "task", corpus
            )
    for task in approved:
        for unit in units_by_task.get(task["id"], []):
            iri_map[unit["id"]] = await iri_manager.get_or_create_iri(
                unit["id"], "unit", corpus
            )

    serializer = OWLSerializer()
    graph = serializer.build_graph(
        approved, units_by_task, iri_map, contradictions, metadata
    )
    report_md = exporter.export_owl_validate(graph, output_dir)
    files_to_bundle["validation-report.md"] = report_md

    # Build ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files_to_bundle.items():
            zf.writestr(filename, content)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="folio-insights-{corpus_id}-export.zip"',
        },
    )

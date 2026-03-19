"""Multi-format export endpoints for task hierarchy.

GET /api/v1/corpus/{corpus_id}/export/markdown -- Markdown outline
GET /api/v1/corpus/{corpus_id}/export/json     -- JSON tree
GET /api/v1/corpus/{corpus_id}/export/html     -- HTML report
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse

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

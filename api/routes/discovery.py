"""Discovery trigger, SSE stream, task CRUD, review, contradiction,
hierarchy edit, source authority, and statistics endpoints.

POST /api/v1/corpus/{corpus_id}/discover         -- Start discovery pipeline
GET  /api/v1/corpus/{corpus_id}/discover/stream   -- SSE progress stream
GET  /api/v1/corpus/{corpus_id}/discover/job      -- Current discovery job
GET  /api/v1/corpus/{corpus_id}/discovery/diff    -- Latest discovery diff
GET  /api/v1/corpus/{corpus_id}/tasks/tree        -- Task hierarchy tree
GET  /api/v1/corpus/{corpus_id}/tasks/{task_id}   -- Single task detail
GET  /api/v1/corpus/{corpus_id}/tasks/{task_id}/units -- Units for a task
POST /api/v1/corpus/{corpus_id}/tasks/{task_id}/review -- Review a task
POST /api/v1/corpus/{corpus_id}/tasks/bulk-approve     -- Bulk approve tasks
POST /api/v1/corpus/{corpus_id}/tasks                  -- Create manual task
DELETE /api/v1/corpus/{corpus_id}/tasks/{task_id}       -- Delete a task
POST /api/v1/corpus/{corpus_id}/tasks/hierarchy-edit    -- Record hierarchy edit
GET  /api/v1/corpus/{corpus_id}/contradictions          -- List contradictions
GET  /api/v1/corpus/{corpus_id}/contradictions/{id}     -- Single contradiction
POST /api/v1/corpus/{corpus_id}/contradictions/{id}/resolve -- Resolve
GET  /api/v1/corpus/{corpus_id}/source-authority        -- List source authority
PUT  /api/v1/corpus/{corpus_id}/source-authority        -- Upsert source authority
GET  /api/v1/corpus/{corpus_id}/discovery/stats         -- Discovery statistics
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from sse_starlette.sse import EventSourceResponse

from api.models.discovery import (
    ContradictionResolveRequest,
    ContradictionResponse,
    DiscoveryDiffEntry,
    DiscoveryStats,
    HierarchyEditRequest,
    SourceAuthorityRequest,
    TaskBulkApproveRequest,
    TaskCreateRequest,
    TaskResponse,
    TaskReviewRequest,
    TaskTreeNode,
)
from api.models.processing import ProcessingJob, ProcessingStatus
from api.services.job_manager import JobManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["discovery"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _output_dir() -> Path:
    """Lazy import to avoid circular dependency with api.main."""
    from api.main import _output_dir

    return _output_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_discovery_job_manager: JobManager | None = None


def get_discovery_job_manager() -> JobManager:
    """Return the module-level JobManager for discovery jobs."""
    global _discovery_job_manager
    if _discovery_job_manager is None:
        jobs_dir = _output_dir() / ".jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        _discovery_job_manager = JobManager(jobs_dir)
    return _discovery_job_manager


def reset_discovery_job_manager() -> None:
    """Reset the singleton (used by tests)."""
    global _discovery_job_manager
    _discovery_job_manager = None


async def _get_db(corpus_id: str):
    """Get an aiosqlite connection for the corpus."""
    from api.main import get_db_for_corpus

    return await get_db_for_corpus(corpus_id)


def _corpus_dir(corpus_id: str) -> Path:
    return _output_dir() / corpus_id


# ---------------------------------------------------------------------------
# Discovery trigger and streaming
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/discover", status_code=202)
async def start_discovery(corpus_id: str) -> dict:
    """Trigger task discovery pipeline for a corpus.

    Returns 202 Accepted with the job id. Discovery runs in a
    background asyncio task. Connect to the SSE stream endpoint
    to follow progress in real time.
    """
    output = _output_dir()
    corpus_meta = output / corpus_id / "corpus-meta.json"
    if not corpus_meta.exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    # Require extraction output
    extraction = output / corpus_id / "extraction.json"
    if not extraction.exists():
        raise HTTPException(
            status_code=404,
            detail="Extraction output not found. Run extraction pipeline first.",
        )

    jm = get_discovery_job_manager()

    # Check for already-running discovery
    discovery_key = f"{corpus_id}_discovery"
    existing = await jm.load_by_corpus(discovery_key)
    if existing is not None and existing.status == ProcessingStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="Discovery already in progress")

    # Create new job
    now = _now_iso()
    job = ProcessingJob(
        corpus_id=discovery_key,
        status=ProcessingStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    await jm.save(job)

    # Launch background discovery task
    from api.services.discovery_runner import run_discovery_with_progress

    asyncio.create_task(
        run_discovery_with_progress(corpus_id, corpus_id, jm)
    )

    return {"job_id": str(job.id), "status": "pending"}


@router.get("/corpus/{corpus_id}/discover/stream")
async def stream_discovery_progress(corpus_id: str):
    """SSE event stream for real-time discovery progress."""
    return EventSourceResponse(_discovery_event_generator(corpus_id))


async def _discovery_event_generator(corpus_id: str):
    """Yield SSE events by polling the discovery job file on disk."""
    jm = get_discovery_job_manager()
    discovery_key = f"{corpus_id}_discovery"
    last_status = None
    last_activity_count = 0

    while True:
        job = await jm.load_by_corpus(discovery_key)

        if job is None:
            yield {
                "event": "error",
                "data": json.dumps({"error": "No discovery job found"}),
            }
            return

        # Emit status change
        if job.status != last_status:
            last_status = job.status
            yield {
                "event": "status",
                "data": json.dumps({
                    "job_id": str(job.id),
                    "status": job.status.value,
                    "stage": job.current_stage,
                    "progress": job.progress_pct,
                }),
            }

        # Emit new activity log entries
        if len(job.activity_log) > last_activity_count:
            for entry in job.activity_log[last_activity_count:]:
                yield {
                    "event": "activity",
                    "data": json.dumps({
                        "timestamp": entry.timestamp,
                        "stage": entry.stage,
                        "message": entry.message,
                    }),
                }
            last_activity_count = len(job.activity_log)

        # Terminal state: emit complete and exit
        if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED):
            yield {
                "event": "complete",
                "data": json.dumps({
                    "status": job.status.value,
                    "total_tasks": job.total_units,
                    "error": job.error,
                }),
            }
            return

        await asyncio.sleep(0.5)


@router.get("/corpus/{corpus_id}/discover/job")
async def get_discovery_job(corpus_id: str) -> dict:
    """Return the current discovery job for a corpus, or 404."""
    jm = get_discovery_job_manager()
    job = await jm.load_by_corpus(f"{corpus_id}_discovery")
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No discovery job found for corpus '{corpus_id}'",
        )
    return job.model_dump()


@router.get("/corpus/{corpus_id}/discovery/diff")
async def get_discovery_diff(corpus_id: str) -> list[DiscoveryDiffEntry]:
    """Return the latest discovery diff as a list of DiscoveryDiffEntry objects.

    Reads discovery_diff.json written by TaskDiscoveryOrchestrator._compute_diff().
    Returns [] if no diff file exists (first run).
    """
    diff_path = _corpus_dir(corpus_id) / "discovery_diff.json"
    if not diff_path.exists():
        return []
    data = json.loads(diff_path.read_text(encoding="utf-8"))
    return [DiscoveryDiffEntry(**entry) for entry in data]


# ---------------------------------------------------------------------------
# Task tree
# ---------------------------------------------------------------------------


@router.get("/corpus/{corpus_id}/tasks/tree")
async def get_task_tree(
    corpus_id: str,
    mode: str = Query("tasks_only", description="tasks_only or all_concepts"),
) -> list[dict]:
    """Return task hierarchy as nested tree.

    Loads from task_decisions table joined with task_unit_links for counts.
    """
    db = await _get_db(corpus_id)
    try:
        # Load tasks
        cursor = await db.execute(
            "SELECT * FROM task_decisions WHERE corpus_name = ? "
            "ORDER BY canonical_order, label",
            (corpus_id,),
        )
        rows = await cursor.fetchall()

        if not rows:
            return []

        # Load unit counts per task
        unit_cursor = await db.execute(
            "SELECT task_id, COUNT(*) as cnt FROM task_unit_links "
            "WHERE corpus_name = ? GROUP BY task_id",
            (corpus_id,),
        )
        unit_counts_rows = await unit_cursor.fetchall()
        unit_counts = {r["task_id"]: r["cnt"] for r in unit_counts_rows}

        # Check contradictions per task
        contra_cursor = await db.execute(
            "SELECT task_id, COUNT(*) as cnt FROM contradictions "
            "WHERE corpus_name = ? AND resolution IS NULL GROUP BY task_id",
            (corpus_id,),
        )
        contra_rows = await contra_cursor.fetchall()
        contra_counts = {r["task_id"]: r["cnt"] for r in contra_rows}

        # Build flat nodes
        nodes = {}
        for row in rows:
            tid = row["task_id"]
            nodes[tid] = {
                "id": tid,
                "label": row["edited_label"] or row["label"],
                "folio_iri": row["folio_iri"],
                "parent_id": row["parent_task_id"],
                "unit_count": unit_counts.get(tid, 0),
                "review_status": row["status"],
                "has_contradictions": contra_counts.get(tid, 0) > 0,
                "has_orphans": False,
                "is_jurisdiction_sensitive": False,
                "is_procedural": bool(row["is_procedural"]),
                "canonical_order": row["canonical_order"],
                "is_manual": bool(row["is_manual"]),
                "depth": 0,
                "children": [],
            }

        # Compute depth
        def _compute_depth(node_id: str, visited: set | None = None) -> int:
            if visited is None:
                visited = set()
            if node_id in visited:
                return 0
            visited.add(node_id)
            node = nodes.get(node_id)
            if not node or not node["parent_id"]:
                return 0
            return 1 + _compute_depth(node["parent_id"], visited)

        for tid in nodes:
            nodes[tid]["depth"] = _compute_depth(tid)

        # Build tree structure
        roots = []
        for tid, node in nodes.items():
            parent_id = node["parent_id"]
            if parent_id and parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            else:
                roots.append(node)

        return roots

    finally:
        await db.close()


@router.get("/corpus/{corpus_id}/tasks/{task_id}")
async def get_task(corpus_id: str, task_id: str) -> TaskResponse:
    """Return single task with full detail."""
    db = await _get_db(corpus_id)
    try:
        cursor = await db.execute(
            "SELECT * FROM task_decisions WHERE task_id = ? AND corpus_name = ?",
            (task_id, corpus_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        # Get unit type counts
        unit_cursor = await db.execute(
            "SELECT tul.unit_id FROM task_unit_links tul "
            "WHERE tul.task_id = ? AND tul.corpus_name = ?",
            (task_id, corpus_id),
        )
        unit_rows = await unit_cursor.fetchall()
        unit_ids = [r["unit_id"] for r in unit_rows]

        # Load extraction data for unit types
        from api.main import get_extraction_data

        data = get_extraction_data(corpus_id)
        units = data.get("units", [])
        unit_map = {u["id"]: u for u in units}

        type_counts: dict[str, int] = defaultdict(int)
        for uid in unit_ids:
            u = unit_map.get(uid)
            if u:
                type_counts[u.get("unit_type", "unknown")] += 1

        # Check contradictions
        contra_cursor = await db.execute(
            "SELECT COUNT(*) FROM contradictions "
            "WHERE task_id = ? AND corpus_name = ? AND resolution IS NULL",
            (task_id, corpus_id),
        )
        contra_row = await contra_cursor.fetchone()
        has_contradictions = (contra_row[0] or 0) > 0

        return TaskResponse(
            id=row["task_id"],
            label=row["edited_label"] or row["label"],
            folio_iri=row["folio_iri"],
            parent_task_id=row["parent_task_id"],
            is_procedural=bool(row["is_procedural"]),
            canonical_order=row["canonical_order"],
            is_manual=bool(row["is_manual"]),
            review_status=row["status"],
            unit_type_counts=dict(type_counts),
            has_contradictions=has_contradictions,
        )

    finally:
        await db.close()


@router.get("/corpus/{corpus_id}/tasks/{task_id}/units")
async def get_task_units(corpus_id: str, task_id: str) -> list[dict]:
    """Return knowledge units linked to this task, grouped by type."""
    db = await _get_db(corpus_id)
    try:
        cursor = await db.execute(
            "SELECT unit_id, is_canonical, confidence FROM task_unit_links "
            "WHERE task_id = ? AND corpus_name = ?",
            (task_id, corpus_id),
        )
        rows = await cursor.fetchall()
        unit_ids = {r["unit_id"]: r for r in rows}

        if not unit_ids:
            return []

        from api.main import get_extraction_data

        data = get_extraction_data(corpus_id)
        units = data.get("units", [])

        result = []
        for u in units:
            if u["id"] in unit_ids:
                link = unit_ids[u["id"]]
                result.append({
                    **u,
                    "is_canonical": bool(link["is_canonical"]),
                    "assignment_confidence": link["confidence"],
                })

        return result

    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Task review
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/tasks/{task_id}/review")
async def review_task(
    corpus_id: str,
    task_id: str,
    body: TaskReviewRequest,
) -> TaskResponse:
    """Submit a review decision for a task."""
    if body.status not in ("approved", "rejected", "edited"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    db = await _get_db(corpus_id)
    try:
        # Verify task exists
        cursor = await db.execute(
            "SELECT * FROM task_decisions WHERE task_id = ? AND corpus_name = ?",
            (task_id, corpus_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        now = _now_iso()
        await db.execute(
            """
            UPDATE task_decisions SET
                status = ?,
                edited_label = ?,
                reviewer_note = ?,
                reviewed_at = ?,
                updated_at = ?
            WHERE task_id = ? AND corpus_name = ?
            """,
            (
                body.status,
                body.edited_label,
                body.note or "",
                now,
                now,
                task_id,
                corpus_id,
            ),
        )
        await db.commit()

    finally:
        await db.close()

    # Return updated task
    return await get_task(corpus_id, task_id)


@router.post("/corpus/{corpus_id}/tasks/bulk-approve")
async def bulk_approve_tasks(
    corpus_id: str,
    body: TaskBulkApproveRequest,
) -> dict:
    """Approve all tasks matching criteria (specific IDs or confidence >= threshold)."""
    db = await _get_db(corpus_id)
    try:
        now = _now_iso()
        approved_ids: list[str] = []

        if body.task_ids:
            for tid in body.task_ids:
                await db.execute(
                    "UPDATE task_decisions SET status = 'approved', "
                    "reviewed_at = ?, updated_at = ? "
                    "WHERE task_id = ? AND corpus_name = ?",
                    (now, now, tid, corpus_id),
                )
                approved_ids.append(tid)
        elif body.confidence_min is not None:
            # Load task_tree.json for confidence data
            tree_path = _corpus_dir(corpus_id) / "task_tree.json"
            if tree_path.exists():
                tree_data = json.loads(tree_path.read_text(encoding="utf-8"))
                high_conf_ids = [
                    t["id"] for t in tree_data
                    if t.get("confidence", 0) >= body.confidence_min
                ]
                for tid in high_conf_ids:
                    await db.execute(
                        "UPDATE task_decisions SET status = 'approved', "
                        "reviewed_at = ?, updated_at = ? "
                        "WHERE task_id = ? AND corpus_name = ?",
                        (now, now, tid, corpus_id),
                    )
                    approved_ids.append(tid)
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide task_ids or confidence_min",
            )

        await db.commit()
        return {"approved_count": len(approved_ids), "task_ids": approved_ids}

    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/tasks", status_code=201)
async def create_task(corpus_id: str, body: TaskCreateRequest) -> TaskResponse:
    """Create a manually-created task (is_manual=1)."""
    db = await _get_db(corpus_id)
    try:
        task_id = str(uuid4())
        now = _now_iso()

        await db.execute(
            """
            INSERT INTO task_decisions
                (task_id, corpus_name, folio_iri, label, parent_task_id,
                 is_procedural, is_manual, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'unreviewed', ?, ?)
            """,
            (
                task_id,
                corpus_id,
                body.folio_iri,
                body.label,
                body.parent_task_id,
                int(body.is_procedural),
                now,
                now,
            ),
        )
        await db.commit()

    finally:
        await db.close()

    return await get_task(corpus_id, task_id)


@router.delete("/corpus/{corpus_id}/tasks/{task_id}", status_code=204)
async def delete_task(corpus_id: str, task_id: str) -> Response:
    """Delete a task and reassign linked units to orphan status."""
    db = await _get_db(corpus_id)
    try:
        # Verify task exists
        cursor = await db.execute(
            "SELECT task_id, label FROM task_decisions "
            "WHERE task_id = ? AND corpus_name = ?",
            (task_id, corpus_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        # Remove unit links (orphan the units)
        await db.execute(
            "DELETE FROM task_unit_links WHERE task_id = ? AND corpus_name = ?",
            (task_id, corpus_id),
        )

        # Record hierarchy edit
        await db.execute(
            "INSERT INTO hierarchy_edits (corpus_name, edit_type, source_task_id, detail) "
            "VALUES (?, 'delete', ?, ?)",
            (corpus_id, task_id, f"Deleted task: {row['label']}"),
        )

        # Delete the task
        await db.execute(
            "DELETE FROM task_decisions WHERE task_id = ? AND corpus_name = ?",
            (task_id, corpus_id),
        )

        await db.commit()

    finally:
        await db.close()

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Hierarchy edits
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/tasks/hierarchy-edit")
async def hierarchy_edit(corpus_id: str, body: HierarchyEditRequest) -> dict:
    """Record a hierarchy edit and apply structural changes."""
    db = await _get_db(corpus_id)
    try:
        now = _now_iso()

        # Record the edit
        await db.execute(
            "INSERT INTO hierarchy_edits "
            "(corpus_name, edit_type, source_task_id, target_task_id, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                corpus_id,
                body.edit_type,
                body.source_task_id,
                body.target_task_id,
                body.detail,
            ),
        )

        if body.edit_type == "move" and body.source_task_id and body.target_task_id:
            # Move: update parent_task_id
            await db.execute(
                "UPDATE task_decisions SET parent_task_id = ?, updated_at = ? "
                "WHERE task_id = ? AND corpus_name = ?",
                (body.target_task_id, now, body.source_task_id, corpus_id),
            )

        elif body.edit_type == "merge" and body.source_task_id and body.target_task_id:
            # Merge: move all unit links from source to target, then delete source
            await db.execute(
                """
                UPDATE OR IGNORE task_unit_links SET task_id = ?
                WHERE task_id = ? AND corpus_name = ?
                """,
                (body.target_task_id, body.source_task_id, corpus_id),
            )
            # Delete remaining links that conflicted (duplicates)
            await db.execute(
                "DELETE FROM task_unit_links WHERE task_id = ? AND corpus_name = ?",
                (body.source_task_id, corpus_id),
            )
            # Delete the merged task
            await db.execute(
                "DELETE FROM task_decisions WHERE task_id = ? AND corpus_name = ?",
                (body.source_task_id, corpus_id),
            )

        await db.commit()
        return {"status": "ok", "edit_type": body.edit_type}

    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Contradictions
# ---------------------------------------------------------------------------


@router.get("/corpus/{corpus_id}/contradictions")
async def list_contradictions(
    corpus_id: str,
    status: str | None = Query(None, description="Filter: 'unresolved' or 'resolved'"),
) -> list[ContradictionResponse]:
    """List all contradictions for the corpus."""
    db = await _get_db(corpus_id)
    try:
        if status == "unresolved":
            cursor = await db.execute(
                "SELECT * FROM contradictions "
                "WHERE corpus_name = ? AND resolution IS NULL "
                "ORDER BY id",
                (corpus_id,),
            )
        elif status == "resolved":
            cursor = await db.execute(
                "SELECT * FROM contradictions "
                "WHERE corpus_name = ? AND resolution IS NOT NULL "
                "ORDER BY id",
                (corpus_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM contradictions WHERE corpus_name = ? ORDER BY id",
                (corpus_id,),
            )

        rows = await cursor.fetchall()
        return [
            ContradictionResponse(
                id=r["id"],
                task_id=r["task_id"],
                unit_id_a=r["unit_id_a"],
                unit_id_b=r["unit_id_b"],
                nli_score=r["nli_score"],
                contradiction_type=r["contradiction_type"],
                resolution=r["resolution"],
                resolved_text=r["resolved_text"],
                resolver_note=r["resolver_note"],
            )
            for r in rows
        ]

    finally:
        await db.close()


@router.get("/corpus/{corpus_id}/contradictions/{contradiction_id}")
async def get_contradiction(
    corpus_id: str, contradiction_id: int
) -> ContradictionResponse:
    """Return a single contradiction with full detail."""
    db = await _get_db(corpus_id)
    try:
        cursor = await db.execute(
            "SELECT * FROM contradictions WHERE id = ? AND corpus_name = ?",
            (contradiction_id, corpus_id),
        )
        r = await cursor.fetchone()
        if r is None:
            raise HTTPException(
                status_code=404,
                detail=f"Contradiction {contradiction_id} not found",
            )

        return ContradictionResponse(
            id=r["id"],
            task_id=r["task_id"],
            unit_id_a=r["unit_id_a"],
            unit_id_b=r["unit_id_b"],
            nli_score=r["nli_score"],
            contradiction_type=r["contradiction_type"],
            resolution=r["resolution"],
            resolved_text=r["resolved_text"],
            resolver_note=r["resolver_note"],
        )

    finally:
        await db.close()


@router.post("/corpus/{corpus_id}/contradictions/{contradiction_id}/resolve")
async def resolve_contradiction(
    corpus_id: str,
    contradiction_id: int,
    body: ContradictionResolveRequest,
) -> ContradictionResponse:
    """Resolve a contradiction."""
    valid_resolutions = {"keep_both", "prefer_a", "prefer_b", "merge", "jurisdiction"}
    if body.resolution not in valid_resolutions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution. Must be one of: {valid_resolutions}",
        )

    db = await _get_db(corpus_id)
    try:
        now = _now_iso()
        await db.execute(
            """
            UPDATE contradictions SET
                resolution = ?,
                resolved_text = ?,
                resolver_note = ?,
                resolved_at = ?
            WHERE id = ? AND corpus_name = ?
            """,
            (
                body.resolution,
                body.resolved_text,
                body.note or "",
                now,
                contradiction_id,
                corpus_id,
            ),
        )
        await db.commit()

    finally:
        await db.close()

    return await get_contradiction(corpus_id, contradiction_id)


# ---------------------------------------------------------------------------
# Source authority
# ---------------------------------------------------------------------------


@router.get("/corpus/{corpus_id}/source-authority")
async def list_source_authority(corpus_id: str) -> list[dict]:
    """List source files with authority levels."""
    db = await _get_db(corpus_id)
    try:
        cursor = await db.execute(
            "SELECT * FROM source_authority WHERE corpus_name = ? ORDER BY authority_level DESC",
            (corpus_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "source_file": r["source_file"],
                "authority_level": r["authority_level"],
                "author": r["author"],
            }
            for r in rows
        ]

    finally:
        await db.close()


@router.put("/corpus/{corpus_id}/source-authority")
async def upsert_source_authority(
    corpus_id: str, body: SourceAuthorityRequest
) -> dict:
    """Upsert source authority for a file."""
    db = await _get_db(corpus_id)
    try:
        await db.execute(
            """
            INSERT INTO source_authority (corpus_name, source_file, authority_level, author)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(corpus_name, source_file) DO UPDATE SET
                authority_level = excluded.authority_level,
                author = excluded.author
            """,
            (corpus_id, body.source_file, body.authority_level, body.author),
        )
        await db.commit()
        return {
            "source_file": body.source_file,
            "authority_level": body.authority_level,
            "author": body.author,
        }

    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@router.get("/corpus/{corpus_id}/discovery/stats")
async def get_discovery_stats(corpus_id: str) -> DiscoveryStats:
    """Return discovery statistics for a corpus."""
    db = await _get_db(corpus_id)
    try:
        # Total tasks and subtasks
        task_cursor = await db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN parent_task_id IS NOT NULL THEN 1 ELSE 0 END) as subtasks "
            "FROM task_decisions WHERE corpus_name = ?",
            (corpus_id,),
        )
        task_row = await task_cursor.fetchone()
        total_tasks = task_row["total"] or 0
        total_subtasks = task_row["subtasks"] or 0

        # Total units assigned
        unit_cursor = await db.execute(
            "SELECT COUNT(DISTINCT unit_id) as cnt FROM task_unit_links "
            "WHERE corpus_name = ?",
            (corpus_id,),
        )
        unit_row = await unit_cursor.fetchone()
        total_units_assigned = unit_row["cnt"] or 0

        # Contradictions
        contra_cursor = await db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN resolution IS NOT NULL THEN 1 ELSE 0 END) as resolved "
            "FROM contradictions WHERE corpus_name = ?",
            (corpus_id,),
        )
        contra_row = await contra_cursor.fetchone()
        contradiction_count = contra_row["total"] or 0
        contradictions_resolved = contra_row["resolved"] or 0

        # Review progress
        review_cursor = await db.execute(
            "SELECT COUNT(*) as reviewed FROM task_decisions "
            "WHERE corpus_name = ? AND status IN ('approved', 'rejected', 'edited')",
            (corpus_id,),
        )
        review_row = await review_cursor.fetchone()
        reviewed = review_row["reviewed"] or 0
        review_pct = (reviewed / total_tasks * 100) if total_tasks > 0 else 0.0

        # Orphan count from extraction data
        from api.main import get_extraction_data

        data = get_extraction_data(corpus_id)
        all_units = data.get("units", [])
        all_unit_ids = {u["id"] for u in all_units}

        assigned_cursor = await db.execute(
            "SELECT DISTINCT unit_id FROM task_unit_links WHERE corpus_name = ?",
            (corpus_id,),
        )
        assigned_rows = await assigned_cursor.fetchall()
        assigned_ids = {r["unit_id"] for r in assigned_rows}
        orphan_count = len(all_unit_ids - assigned_ids)

        # By unit type
        by_unit_type: dict[str, int] = defaultdict(int)
        for u in all_units:
            if u["id"] in assigned_ids:
                by_unit_type[u.get("unit_type", "unknown")] += 1

        # Source coverage
        source_coverage: dict[str, int] = defaultdict(int)
        for u in all_units:
            if u["id"] in assigned_ids:
                source_coverage[u.get("source_file", "unknown")] += 1

        return DiscoveryStats(
            total_tasks=total_tasks,
            total_subtasks=total_subtasks,
            total_units_assigned=total_units_assigned,
            orphan_count=orphan_count,
            contradiction_count=contradiction_count,
            contradictions_resolved=contradictions_resolved,
            review_progress_pct=round(review_pct, 1),
            by_unit_type=dict(by_unit_type),
            source_coverage=dict(source_coverage),
        )

    finally:
        await db.close()

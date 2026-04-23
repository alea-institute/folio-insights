"""Timeline endpoints — Phase 0 stubs feeding the D-09 SSR prototype.

Contract mirrors ``api/routes/shard.py``: one critical-path payload + two
streamed payloads, all returning canned JSON.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/timeline", tags=["timeline-phase0"])


@router.get("/{timeline_id}/core")
async def get_timeline_core(timeline_id: str) -> dict[str, Any]:
    """Critical-path payload — blocks SSR initial paint."""
    return {
        "iri": f"https://folio.openlegalstandard.org/timeline/{timeline_id}",
        "label": f"Timeline {timeline_id}",
        "windowStart": "2022-01-01",
        "windowEnd": "2026-04-22",
        "eventCount": 5,
    }


@router.get("/{timeline_id}/events")
async def get_timeline_events(timeline_id: str) -> dict[str, Any]:
    """Event payload — streams behind {#await}."""
    return {
        "events": [
            {
                "id": f"{timeline_id}-evt-{i}",
                "at": f"202{i}-0{(i % 9) + 1}-01",
                "kind": "supersede" if i % 2 == 0 else "amend",
                "summary": f"Stub event {i}",
            }
            for i in range(5)
        ]
    }


@router.get("/{timeline_id}/supersession_chain")
async def get_supersession_chain(timeline_id: str) -> dict[str, Any]:
    """Supersession-chain payload — streams."""
    return {
        "supersession": [
            {
                "iri": f"https://folio.openlegalstandard.org/axioms/{timeline_id}-v{i}",
                "validFrom": f"202{i}-01-01",
            }
            for i in range(3)
        ]
    }

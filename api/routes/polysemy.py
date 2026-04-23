"""Polysemy endpoints — Phase 0 stubs feeding the D-09 SSR prototype.

Contract mirrors ``api/routes/shard.py``: one critical-path payload + two
streamed payloads, all returning canned JSON.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/polysemy", tags=["polysemy-phase0"])


@router.get("/{polysemy_id}/core")
async def get_polysemy_core(polysemy_id: str) -> dict[str, Any]:
    """Critical-path payload — blocks SSR initial paint."""
    return {
        "iri": f"https://folio.openlegalstandard.org/polysemy/{polysemy_id}",
        "label": f"Polysemy {polysemy_id}",
        "primarySense": "noun: a person or thing acting on behalf of another",
        "forkCount": 3,
    }


@router.get("/{polysemy_id}/siblings")
async def get_polysemy_siblings(polysemy_id: str) -> dict[str, Any]:
    """Sibling-sense payload — streams behind {#await}."""
    return {
        "siblings": [
            {
                "iri": f"https://folio.openlegalstandard.org/polysemy/{polysemy_id}/s{i}",
                "label": f"Sibling sense {i}",
            }
            for i in range(3)
        ]
    }


@router.get("/{polysemy_id}/disambiguations")
async def get_polysemy_disambiguations(polysemy_id: str) -> dict[str, Any]:
    """Disambiguation-signal payload — streams."""
    return {
        "disambiguations": [
            {
                "iri": f"https://folio.openlegalstandard.org/disambig/{polysemy_id}/d{i}",
                "label": f"Signal {i}",
                "signal": "statutory-context" if i % 2 == 0 else "common-law",
            }
            for i in range(4)
        ]
    }

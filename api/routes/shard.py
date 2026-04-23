"""Shard endpoints — Phase 0 stubs feeding the D-09 SSR prototype.

Plan 0's SSR surfaces test Gate 4 (cold-page P95). Real shard rendering is
Phase 15 (Review Viewer); Phase 0 stubs return MINIMAL canned JSON that
exercises the SSR critical-path contract:

    GET /api/shard/{id}/core      → critical-path (awaited)
    GET /api/shard/{id}/deps      → streamed behind {#await}
    GET /api/shard/{id}/attests   → streamed behind {#await}

Stubs intentionally return canned shapes so Gate 4 measures the SSR stack
overhead rather than pyoxigraph query cost (Phase 15 wires the real store).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/shard", tags=["shard-phase0"])


@router.get("/{shard_id}/core")
async def get_shard_core(shard_id: str) -> dict[str, Any]:
    """Critical-path payload — blocks SSR initial paint (Gate 4 budget <200ms)."""
    return {
        "iri": f"https://folio.openlegalstandard.org/shards/{shard_id}",
        "label": f"Shard {shard_id}",
        "confidence": 0.92,
        "corpus": "advocacy",
        "validFrom": "2022-01-01",
    }


@router.get("/{shard_id}/deps")
async def get_shard_deps(shard_id: str) -> dict[str, Any]:
    """Dependencies payload — streams behind {#await} in SvelteKit."""
    return {
        "dependsOnAxiom": [
            f"https://folio.openlegalstandard.org/axioms/A{i:04d}"
            for i in range(5)
        ],
        "dependsOnDefinition": [
            f"https://folio.openlegalstandard.org/definitions/D{i:04d}"
            for i in range(3)
        ],
    }


@router.get("/{shard_id}/attests")
async def get_shard_attests(shard_id: str) -> dict[str, Any]:
    """Attestations payload — streams."""
    return {
        "attestations": [
            {"signer": "did:example:abc", "validFrom": "2022-06-01"},
            {"signer": "did:example:def", "validFrom": "2023-01-01"},
        ],
    }

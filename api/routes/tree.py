"""FOLIO concept tree endpoints."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()


def _build_tree(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a concept tree from extraction data units.

    Groups units by their ``folio_tags`` IRIs and returns a flat-or-nested
    structure with unit counts per concept.  Concepts that share a ``branch``
    are grouped as children of a synthetic branch node.
    """
    # Collect concepts and counts
    concept_map: dict[str, dict[str, Any]] = {}
    concept_units: dict[str, int] = defaultdict(int)

    for unit in units:
        for tag in unit.get("folio_tags", []):
            iri = tag["iri"]
            concept_units[iri] += 1
            if iri not in concept_map:
                concept_map[iri] = {
                    "iri": iri,
                    "label": tag.get("label", ""),
                    "branch": tag.get("branch", ""),
                }

    # Group by branch -> children
    branches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for iri, info in concept_map.items():
        node = {
            "iri": iri,
            "label": info["label"],
            "branch": info["branch"],
            "unit_count": concept_units[iri],
            "children": [],
        }
        branch = info["branch"] or "Uncategorized"
        branches[branch].append(node)

    # Build top-level tree
    tree: list[dict[str, Any]] = []
    for branch_name in sorted(branches):
        children = sorted(branches[branch_name], key=lambda n: n["label"])
        tree.append(
            {
                "iri": "",
                "label": branch_name,
                "branch": branch_name,
                "unit_count": sum(c["unit_count"] for c in children),
                "children": children,
            }
        )

    return tree


@router.get("/tree")
async def get_tree(
    corpus: str = Query("default", description="Corpus name"),
) -> list[dict[str, Any]]:
    """Return FOLIO concept tree filtered to concepts with tagged units."""
    from api.main import get_extraction_data

    data = get_extraction_data(corpus)
    units = data.get("units", [])
    return _build_tree(units)


@router.get("/tree/flat")
async def get_tree_flat(
    corpus: str = Query("default", description="Corpus name"),
) -> list[dict[str, Any]]:
    """Return flat list of concepts with unit counts."""
    from api.main import get_extraction_data

    data = get_extraction_data(corpus)
    units = data.get("units", [])

    concept_counts: dict[str, dict[str, Any]] = {}
    for unit in units:
        for tag in unit.get("folio_tags", []):
            iri = tag["iri"]
            if iri not in concept_counts:
                concept_counts[iri] = {
                    "iri": iri,
                    "label": tag.get("label", ""),
                    "branch": tag.get("branch", ""),
                    "unit_count": 0,
                }
            concept_counts[iri]["unit_count"] += 1

    return sorted(concept_counts.values(), key=lambda c: c["label"])

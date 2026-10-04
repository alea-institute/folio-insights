"""Synthetic fixtures for the proposed-class governance tests.

Every label, definition, IRI and text here is invented for tests. None comes
from a historical registry, worklist or source document.
"""
from __future__ import annotations

from typing import Any

from folio_insights.proposals import FolioLexicon

IRI_TORT = "https://folio.test/SyntheticTortDoctrine"
IRI_REMEDY = "https://folio.test/SyntheticRemedyPrinciple"
IRI_FORUM = "https://folio.test/SyntheticAppellateForum"

CONCEPTS: list[dict[str, Any]] = [
    {
        "iri": IRI_TORT,
        "label": "Synthetic Tort Doctrine",
        "definition": "An invented doctrine used only by the governance tests.",
        "alt": ["Synthetic Wrong Rule"],
    },
    {
        "iri": IRI_REMEDY,
        "label": "Synthetic Remedy Principle",
        "definition": "An invented remedy principle used only by the governance tests.",
        "hidden": ["Synthetic Relief Marker"],
    },
    {
        "iri": IRI_FORUM,
        "label": "Synthetic Appellate Forum",
        "definition": "An invented forum used only by the governance tests.",
    },
]

# A sentinel that must never appear in persisted state or a worklist.
SOURCE_TEXT_SENTINEL = "SYNTHETIC-SOURCE-TEXT-SENTINEL"


def lexicon() -> FolioLexicon:
    return FolioLexicon.from_concepts(CONCEPTS)


def pc(label: str, unit_id: str, *, confidence: float = 0.6) -> dict[str, Any]:
    """One ``proposed_classes.json`` row with a synthetic source text."""
    return {
        "proposed_label": label,
        "extraction_path": "proposed_class",
        "confidence": confidence,
        "source_unit_id": unit_id,
        "source_text": f"{SOURCE_TEXT_SENTINEL} for {unit_id}.",
        "source_section": ["Synthetic Part"],
    }

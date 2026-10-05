"""FOLIO top-level branch -> mini-BFO spine table (Phase 9 U7, KTD11).

A hand-curated table over FOLIO's top-level branches (the ``folio-python``
``FOLIO_TYPE_IRIS`` set), checked against ``vocab/bfo_spine.ttl`` and
``vocab/bfo_mapping.ttl``. Each branch maps to

* the most specific nine-class spine class its members fall under, and
* the envelope's four-value ``bfo_category`` (KTD2: the envelope keeps its
  literal; the projection maps the category to a spine class with
  ``vocab._constants.BFO_CATEGORY_SPINE_CLASS``).

Curation notes (BFO 2020 readings):

* Information artifacts — documents, legal authorities, areas of law, data
  formats, languages, currencies, identifiers, narratives, engagement terms,
  objectives, standards, industry classifications — are generically dependent
  continuants (GDC: they depend on some bearer or other).
* Actors/players are roles borne by persons and organizations (SDC: Role).
* Communication modality and status are qualities of a communication or a
  matter (SDC: Quality).
* Legal entities, governmental bodies, forums/venues, locations and asset
  types are independent continuants.
* Events are processes (the Phase 8 D-06 fold; category ``occurrent_event``,
  reported as a sub-count of processes), services are processes.

``DEFAULT_CATEGORY_BY_SPEECH_ACT`` is the documented permissive-mode default
when neither a rule nor the LLM types a subject. Defaults are recorded as
``source="default"`` and never count toward coverage.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from folio_insights.vocab._constants import BFO_CATEGORY_SPINE_CLASS, FI_PREFIX

FOLIO_PREFIX = "https://folio.openlegalstandard.org/"

BfoCategory = Literal[
    "continuant_independent",
    "continuant_dependent",
    "occurrent_process",
    "occurrent_event",
]


@dataclass(frozen=True)
class BranchMapping:
    """One FOLIO top-level branch and its spine typing."""

    label: str
    iri: str
    spine_class: str  # full IRI of a bfo_spine.ttl class
    category: BfoCategory


def _b(label: str, local_id: str, spine: str, category: BfoCategory) -> BranchMapping:
    return BranchMapping(label, FOLIO_PREFIX + local_id, FI_PREFIX + spine, category)


_GDC = "GenericallyDependentContinuant"
_IC = "IndependentContinuant"

FOLIO_BRANCH_SPINE: tuple[BranchMapping, ...] = (
    _b("Actor / Player", "R8CdMpOM0RmyrgCCvbpiLS0", "Role", "continuant_dependent"),
    _b("Area of Law", "RSYBzf149Mi5KE0YtmpUmr", _GDC, "continuant_dependent"),
    _b("Asset Type", "RCIwc6WJi6IT7xePURxsi4T", _IC, "continuant_independent"),
    _b("Communication Modality", "R8qItBwG2pRMFhUq1HQEMnb", "Quality", "continuant_dependent"),
    _b("Currency", "R767niCLQVC5zIcO5WDQMSl", _GDC, "continuant_dependent"),
    _b("Data Format", "R79aItNTJQwHgR002wuX3iC", _GDC, "continuant_dependent"),
    _b("Document / Artifact", "RDt4vQCYDfY0R9fZ5FNnTbj", _GDC, "continuant_dependent"),
    _b("Engagement Terms", "R9kmGZf5FSmFdouXWQ1Nndm", _GDC, "continuant_dependent"),
    _b("Event", "R73hoH1RXYjBTYiGfolpsAF", "Process", "occurrent_event"),
    _b("Forums and Venues", "RBjHwNNG2ASVmasLFU42otk", _IC, "continuant_independent"),
    _b("Governmental Body", "RBQGborh1CfXanGZipDL0Qo", _IC, "continuant_independent"),
    _b("Industry", "RDIwFaFcH4KY0gwEY0QlMTp", _GDC, "continuant_dependent"),
    _b("Language", "RDOvAHsvY8TKJ1O1orXPM9o", _GDC, "continuant_dependent"),
    _b("FOLIO Type", "R8uI6AZ9vSgpAdKmfGZKfTZ", _GDC, "continuant_dependent"),
    _b("Legal Authorities", "RC1CZydjfH8oiM4W3rCkma3", _GDC, "continuant_dependent"),
    _b("Legal Entity", "R7L5eLIzH0CpOUE74uJvSjL", _IC, "continuant_independent"),
    _b("Location", "R9aSzp9cEiBCzObnP92jYFX", _IC, "continuant_independent"),
    _b("Matter Narrative", "R7ReDY2v13rer1U8AyOj55L", _GDC, "continuant_dependent"),
    _b("Matter Narrative Format", "R8ONVC8pLVJC5dD4eKqCiZL", _GDC, "continuant_dependent"),
    _b("Objectives", "RlNFgB3TQfMzV26V4V7u4E", _GDC, "continuant_dependent"),
    _b("Service", "RDK1QEdQg1T8B5HQqMK2pZN", "Process", "occurrent_process"),
    _b("Standards Compatibility", "RB4cFSLB4xvycDlKv73dOg6", _GDC, "continuant_dependent"),
    _b("Status", "Rx69EnEj3H3TpcgTfUSoYx", "Quality", "continuant_dependent"),
    _b("System Identifiers", "R8EoZh39tWmXCkmP2Xzjl6E", _GDC, "continuant_dependent"),
)

BRANCH_BY_IRI: Mapping[str, BranchMapping] = {b.iri: b for b in FOLIO_BRANCH_SPINE}
BRANCH_BY_LABEL: Mapping[str, BranchMapping] = {b.label.casefold(): b for b in FOLIO_BRANCH_SPINE}

# Permissive-mode default per speech act (documented; recorded as "default").
DEFAULT_CATEGORY_BY_SPEECH_ACT: Mapping[str, BfoCategory] = {
    "holding": "continuant_dependent",
    "dictum": "continuant_dependent",
    "statutory_text": "continuant_dependent",
    "statutory_definition": "continuant_dependent",
    "regulatory_text": "continuant_dependent",
    "pleading_argument": "continuant_dependent",
    "contract_term": "continuant_dependent",
    "treatise_statement": "continuant_dependent",
    "restatement_black_letter": "continuant_dependent",
    "practitioner_advice": "occurrent_process",
    "administrative_interpretation": "continuant_dependent",
}

# The spine class a bare category stands for (the projection's table).
CATEGORY_SPINE_CLASS: Mapping[str, str] = BFO_CATEGORY_SPINE_CLASS


def branch_for(value: str) -> BranchMapping | None:
    """The top-level branch named by an IRI or a label (case-insensitive)."""
    return BRANCH_BY_IRI.get(value) or BRANCH_BY_LABEL.get(value.strip().casefold())


__all__ = [
    "BRANCH_BY_IRI",
    "BRANCH_BY_LABEL",
    "BfoCategory",
    "BranchMapping",
    "CATEGORY_SPINE_CLASS",
    "DEFAULT_CATEGORY_BY_SPEECH_ACT",
    "FOLIO_BRANCH_SPINE",
    "FOLIO_PREFIX",
    "branch_for",
]

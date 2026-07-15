"""Proposed-class governance: collect → judge (dedupe) → human-approve → export.

Turns the pipeline's ``proposed_class`` exhaust (surface concepts with no FOLIO
IRI, honestly demoted rather than force-fit) into a governed ontology-extension
backlog. See docs/plans/2026-07-15-001-feat-proposed-class-governance-plan.md.

Deliberately a SEPARATE top-level module (not under ``governance/``, whose D-04
boundary forbids rdflib/OWL deps) because deterministic dedupe must read the
FOLIO lexicon.
"""
from folio_insights.proposals.registry import (  # noqa: F401
    ProposalRegistry,
    normalize_label,
    proposal_id,
)
from folio_insights.proposals.dedupe import DeterministicDeduper  # noqa: F401

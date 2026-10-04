"""Proposed-class governance: collect -> dedupe -> worklist -> approve -> export.

The pipeline's ``proposed_class`` tags are surface concepts with no FOLIO IRI,
honestly demoted rather than force-fit. This package turns them into a
governed, corpus-scoped ontology-extension backlog. State lives in the Phase 13
corpus storage context (``ctx.proposals``) as an append-only ledger. Nothing
here stores source text. See
``docs/plans/2026-09-30-0914-feat-proposed-class-governance-plan.md``.

This is a separate top-level package, not part of ``governance/``, because the
``governance/`` D-04 boundary forbids storage and RDF dependencies.
"""
from folio_insights.proposals.decisions import DecisionInvalid
from folio_insights.proposals.dedupe import DeterministicDeduper, survivors
from folio_insights.proposals.export import build_backlog, check_backlog
from folio_insights.proposals.lexicon import FolioLexicon
from folio_insights.proposals.registry import (
    Proposal,
    ProposalRegistry,
    collect_payload,
    normalize_label,
    proposal_id,
    stem_label,
)
from folio_insights.proposals.store import ProposalStore, load_run_proposals
from folio_insights.proposals.worklist import build_worklist

__all__ = [
    "DecisionInvalid",
    "DeterministicDeduper",
    "FolioLexicon",
    "Proposal",
    "ProposalRegistry",
    "ProposalStore",
    "build_backlog",
    "build_worklist",
    "check_backlog",
    "collect_payload",
    "load_run_proposals",
    "normalize_label",
    "proposal_id",
    "stem_label",
    "survivors",
]

"""Approved-only ontology-extension backlog (governance plan U3, R4).

``build_backlog`` turns a folded ``ProposalRegistry`` into the backlog of
proposals a human reviewer approved. It is a pure function of the ledger:

* **Approved only.** Only proposals whose current decision is ``approved``
  appear. Pending, rejected, merged and needs-work proposals never do, and a
  judgment (human or model) never stands in for a decision.
* **Deterministic.** Rows are sorted by proposal ID, keys are sorted, and every
  value comes from the ledger (the decision time is the ledger commit time), so
  the same ledger, before or after a restart, gives byte-identical output.
* **No source text.** Rows carry labels, run names, unit IDs and spans, the
  current judgment's verdict and targets, and the reviewer's decision. They
  carry no excerpt, source text or FOLIO definition.

``check_backlog`` runs the corpus PII gate and the ledger's forbidden-key
refusal over the finished backlog, so an export cannot carry what the ledger
itself would refuse.

The backlog is deliberately not one of the ``storage export`` formats or part
of the TTL dump: ledger rows are not in the RDF projection those formats
verify, and the dump commits to a git repository, where generated proposal
material must never go (R5). Snapshots copy and verify the ledger itself.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from folio_insights.proposals.decisions import STATUS_APPROVED
from folio_insights.proposals.registry import Proposal, ProposalRegistry
from folio_insights.storage.proposals import refuse_text_keys

if TYPE_CHECKING:
    from folio_insights.storage.pii import PiiGate

BACKLOG_SCHEMA = "proposed-class-backlog/v1"


def _judgment_summary(p: Proposal) -> dict[str, Any] | None:
    j = p.judgment
    if j is None:
        return None
    nearest = j.get("nearest") or []
    suggested_parent = None
    if j.get("verdict") == "NEEDS_WORK" and nearest:
        suggested_parent = nearest[0].get("iri")
    return {
        "verdict": j.get("verdict"),
        "judged_by": j.get("judged_by"),
        "target_iri": j.get("target_iri"),
        "target_proposal_id": j.get("target_proposal_id"),
        "suggested_parent": suggested_parent,
        "ledger_position": j.get("ledger_position"),
    }


def _row(p: Proposal) -> dict[str, Any]:
    d = p.decision
    return {
        "proposal_id": p.proposal_id,
        "label": p.proposed_label,
        "normalized_label": p.normalized_label,
        "label_variants": list(p.label_variants),
        "occurrences": p.occurrences,
        "runs": list(p.runs),
        "supporting_units": [
            {"run": s["run"], "unit_id": s["unit_id"], "source_span": s.get("source_span")}
            for s in p.supporting_units
        ],
        "judgment": _judgment_summary(p),
        "decision": {
            "status": d.get("status"),
            "reviewer_note": d.get("note", ""),
            "decided_by": d.get("decided_by"),
            "decided_at": d.get("decided_at"),
            "ledger_position": d.get("ledger_position"),
            "op_id": d.get("op_id"),
        },
        "decision_history_length": len(p.decision_history),
    }


def approved(registry: ProposalRegistry) -> list[Proposal]:
    return [p for p in registry.all() if p.decision.get("status") == STATUS_APPROVED]


def build_backlog(registry: ProposalRegistry) -> dict[str, Any]:
    rows = [_row(p) for p in approved(registry)]
    return {
        "schema": BACKLOG_SCHEMA,
        "corpus": registry.corpus,
        "ledger_head": registry.head,
        "count": len(rows),
        "proposals": rows,
    }


def check_backlog(backlog: dict[str, Any], pii_gate: PiiGate) -> None:
    """Refuse a backlog that carries a forbidden text key or a PII match.
    Raises ``ProposalPayloadRefused`` or ``PiiRejected``; neither names a value."""
    refuse_text_keys(backlog, "backlog", subject="approved-only backlog",
                     outcome="nothing was written")
    pii_gate.check(backlog)


__all__ = ["BACKLOG_SCHEMA", "approved", "build_backlog", "check_backlog"]

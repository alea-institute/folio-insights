"""Review decision validation (governance plan U3, R4).

A decision is the only way a proposal leaves ``pending``. It is recorded by a
named human reviewer through ``ProposalStore.record_decisions`` and folded by
``ProposalRegistry`` from ``decision`` ledger operations. A judgment, human or
model, never becomes a decision by itself (KTD4: no automatic promotion).

An input decision is ``{proposal_id, status, note?, merge_into?}``:

* ``status``: one of ``approve``, ``reject``, ``merge``, ``needs_work`` (the
  approval queue's paste-back verbs) or the stored form ``approved``,
  ``rejected``, ``merged``, ``needs_work``. Anything else is refused. It never
  silently becomes ``pending``.
* ``note``: optional reviewer text, at most ``MAX_NOTE_CHARS`` characters.
* ``merge_into``: the surviving proposal of a ``merge``. It must name another
  existing proposal of the same corpus. When it is missing, the current
  ``MERGE_WITH`` judgment's target is used; with neither, the merge is refused.

Any other key is refused. ``decided_by`` must name a human reviewer
(``human:<name>``). Errors name the item index and the rule, never a value.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_MERGED = "merged"
STATUS_NEEDS_WORK = "needs_work"

DECIDED_STATUSES = frozenset({
    STATUS_APPROVED, STATUS_REJECTED, STATUS_MERGED, STATUS_NEEDS_WORK,
})
INPUT_STATUSES: dict[str, str] = {
    "approve": STATUS_APPROVED,
    "reject": STATUS_REJECTED,
    "merge": STATUS_MERGED,
    "needs_work": STATUS_NEEDS_WORK,
    **{s: s for s in DECIDED_STATUSES},
}
DECISION_INPUT_KEYS = frozenset({"proposal_id", "status", "note", "merge_into"})
DECISION_CORE_KEYS = ("status", "note", "decided_by", "merge_into")
MAX_NOTE_CHARS = 500
MAX_DECIDED_BY_CHARS = 100
_HUMAN = re.compile(r"human:[^\s:][^\s]{0,90}")


class DecisionInvalid(ValueError):
    """A decision failed validation. The message names the item and rule only."""


def validate_decided_by(decided_by: Any) -> str:
    if (
        not isinstance(decided_by, str)
        or len(decided_by) > MAX_DECIDED_BY_CHARS
        or not _HUMAN.fullmatch(decided_by)
    ):
        raise DecisionInvalid(
            "decided_by must name a human reviewer as 'human:<name>' (no spaces); "
            "a model or deterministic judge cannot record a decision"
        )
    return decided_by


def validate_decision(
    item: Any,
    *,
    index: int,
    known: Mapping[str, Any],
    decided_by: str,
) -> dict[str, Any]:
    """The canonical stored form of one input decision, or ``DecisionInvalid``.

    ``known`` maps every proposal ID of the corpus to its folded ``Proposal``
    (used for the ``MERGE_WITH`` fallback target).
    """
    where = f"decision item {index}"
    if not isinstance(item, Mapping):
        raise DecisionInvalid(f"{where}: must be an object")
    extra = set(item) - DECISION_INPUT_KEYS
    if extra:
        raise DecisionInvalid(
            f"{where}: {len(extra)} key(s) outside {sorted(DECISION_INPUT_KEYS)} are not allowed"
        )
    pid = item.get("proposal_id")
    if not isinstance(pid, str) or pid not in known:
        raise DecisionInvalid(f"{where}: proposal_id is not a proposal of this corpus")
    raw_status = item.get("status")
    status = INPUT_STATUSES.get(raw_status) if isinstance(raw_status, str) else None
    if status is None:
        raise DecisionInvalid(
            f"{where}: status must be one of {sorted(INPUT_STATUSES)}; nothing was recorded"
        )
    note = item.get("note", "")
    if note is None:
        note = ""
    if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS:
        raise DecisionInvalid(f"{where}: note must be a string of at most {MAX_NOTE_CHARS} characters")
    merge_into = item.get("merge_into")
    if status == STATUS_MERGED:
        if merge_into is None:
            judgment = getattr(known[pid], "judgment", None) or {}
            if judgment.get("verdict") == "MERGE_WITH":
                merge_into = judgment.get("target_proposal_id")
        if not isinstance(merge_into, str) or merge_into not in known or merge_into == pid:
            raise DecisionInvalid(
                f"{where}: a merge needs merge_into naming another existing proposal "
                "(or a current MERGE_WITH judgment)"
            )
    elif merge_into is not None:
        raise DecisionInvalid(f"{where}: merge_into is only allowed with status 'merge'")
    return {
        "proposal_id": pid,
        "status": status,
        "note": note.strip(),
        "decided_by": decided_by,
        "merge_into": merge_into,
    }


def decision_core(decision: Mapping[str, Any] | None) -> dict[str, Any]:
    """The comparable part of a decision (no ledger bookkeeping)."""
    decision = decision or {}
    return {
        "status": decision.get("status", STATUS_PENDING),
        "note": decision.get("note", "") or "",
        "decided_by": decision.get("decided_by"),
        "merge_into": decision.get("merge_into"),
    }


__all__ = [
    "DECIDED_STATUSES",
    "DECISION_CORE_KEYS",
    "DECISION_INPUT_KEYS",
    "INPUT_STATUSES",
    "MAX_NOTE_CHARS",
    "STATUS_APPROVED",
    "STATUS_MERGED",
    "STATUS_NEEDS_WORK",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "DecisionInvalid",
    "decision_core",
    "validate_decided_by",
    "validate_decision",
]

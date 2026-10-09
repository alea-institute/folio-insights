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

A stored item may also carry ``provenance``: a small map of short scalar
fields recording where the decision came from (for instance, the original
row and timestamp of a decision imported from the legacy ``review.db``
table). It is set by ``ProposalStore.record_decisions(provenance=...)``,
never by an input decision, and it is not part of the decision's identity
(``decision_core``).

Signed decisions (drain plan U9, R16, ``signed_decisions``). An input item may also
carry ``signature``, a signed decision that ``ProposalStore.record_decisions``
verifies before anything is appended (``validate_decision`` never sees it). A stored
item then records ``signer_did``, ``signature_verified`` (``true`` only for a verified
signature; ``false`` for an unsigned decision), ``signer_registered`` (``true`` only when
the signers file listed the signer DID when it was recorded; a separate fact from a valid
signature) and ``signature`` (the signed decision itself), and ``operator`` names the authenticated API operator who submitted it (a
store records both: operator authentication is not decision authorship). The signer is
part of the decision's identity: the same verdict signed by another key (or signed at
all, after an unsigned one) is a new decision. ``decision_row_problem`` re-verifies a
stored signature, so a raw append cannot claim a signer.
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
DECISION_CORE_KEYS = ("status", "note", "decided_by", "merge_into", "signer_did")
SIGNATURE_INPUT_KEY = "signature"
SIGNATURE_RECORD_KEYS = (
    "signer_did", "signature_verified", "signer_registered", "signature", "operator",
)
MAX_NOTE_CHARS = 500
MAX_DECIDED_BY_CHARS = 100
MAX_PROVENANCE_KEYS = 8
MAX_PROVENANCE_VALUE_CHARS = 200
_PROVENANCE_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
# A reviewer handle: "human:" and 1-64 of [A-Za-z0-9._-], starting with a letter or digit. No
# e-mail addresses, DIDs, markup or invisible characters. The handle is self-asserted: nothing
# here proves a human made the decision (see docs/storage-operations.md).
_HUMAN = re.compile(r"human:[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class DecisionInvalid(ValueError):
    """A decision failed validation. The message names the item and rule only."""


def validate_decided_by(decided_by: Any) -> str:
    if (
        not isinstance(decided_by, str)
        or len(decided_by) > MAX_DECIDED_BY_CHARS
        or not _HUMAN.fullmatch(decided_by)
    ):
        raise DecisionInvalid(
            "decided_by must name a human reviewer as 'human:<handle>' (letters, digits, '.', "
            "'_' or '-'; no e-mail address); a model or deterministic judge cannot record a "
            "decision"
        )
    return decided_by


def validate_provenance(value: Any, *, where: str) -> dict[str, Any]:
    """The canonical form of one decision's ``provenance``, or ``DecisionInvalid``.

    At most ``MAX_PROVENANCE_KEYS`` snake_case keys; each value is ``None``, a
    bool, an int or a string of at most ``MAX_PROVENANCE_VALUE_CHARS``
    characters. Errors name the rule, never a value."""
    problem = provenance_problem(value)
    if problem is not None:
        raise DecisionInvalid(f"{where}: provenance {problem}")
    return {k: value[k] for k in sorted(value)}


def provenance_problem(value: Any) -> str | None:
    if not isinstance(value, Mapping) or not value or len(value) > MAX_PROVENANCE_KEYS:
        return f"must be an object of 1 to {MAX_PROVENANCE_KEYS} fields"
    for key, item in value.items():
        if not isinstance(key, str) or not _PROVENANCE_KEY.fullmatch(key):
            return "keys must be short snake_case names"
        if item is None or isinstance(item, (bool, int)):
            continue
        if not isinstance(item, str) or len(item) > MAX_PROVENANCE_VALUE_CHARS:
            return (
                "values must be null, a boolean, an integer or a string of at most "
                f"{MAX_PROVENANCE_VALUE_CHARS} characters"
            )
    return None


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
        "signer_did": decision.get("signer_did"),
    }


def expected_proposal_decision(item: Mapping[str, Any], corpus: str) -> Any:
    """The ``signed_decisions.ExpectedDecision`` a signature over this stored-form
    decision item must describe: kind ``proposed_class``, the corpus, the proposal ID as
    target, the stored status as verdict, the note as rationale and, for a merge,
    ``{"merge_into": <surviving proposal>}`` as detail."""
    from folio_insights.proposals.signed_decisions import (
        KIND_PROPOSED_CLASS,
        ExpectedDecision,
    )

    merge_into = item.get("merge_into")
    return ExpectedDecision(
        kind=KIND_PROPOSED_CLASS,
        corpus=corpus,
        target=item.get("proposal_id"),
        verdict=item.get("status"),
        rationale=item.get("note", "") or "",
        detail={"merge_into": merge_into} if merge_into is not None else {},
    )


def signature_record_problem(
    item: Mapping[str, Any], *, corpus: str | None, committed_at: str | None
) -> str | None:
    """Why the signature fields of a STORED decision item are invalid, or ``None``.

    An unsigned item has no ``signature``, no ``signer_did`` and ``signature_verified``
    absent or ``false``. A signed item has ``signature_verified: true``, and its stored
    signature must verify for ``signer_did`` and describe exactly this item (in
    ``corpus``, issued within the signing skew of ``committed_at``)."""
    from folio_insights.proposals.signed_decisions import (
        operator_record_problem,
        stored_signature_problem,
    )

    verified = item.get("signature_verified", False)
    if not isinstance(verified, bool):
        return "signature_verified is not a boolean"
    registered = item.get("signer_registered", False)
    if not isinstance(registered, bool):
        return "signer_registered is not a boolean"
    problem = operator_record_problem(item.get("operator"))
    if problem is not None:
        return problem
    signed = item.get("signature")
    if signed is None:
        if verified or registered or item.get("signer_did") is not None:
            return "signer_did, signature_verified or signer_registered without a signature"
        return None
    if verified is not True:
        return "a stored signature must be a verified one"
    expected = expected_proposal_decision(
        item, corpus if corpus is not None else _signed_corpus(signed)
    )
    return stored_signature_problem(
        signed, expected=expected, signer_did=item.get("signer_did"), committed_at=committed_at
    )


def _signed_corpus(signed: Any) -> str:
    body = signed.get("body") if isinstance(signed, Mapping) else None
    corpus = body.get("corpus") if isinstance(body, Mapping) else None
    return corpus if isinstance(corpus, str) else ""


__all__ = [
    "DECIDED_STATUSES",
    "DECISION_CORE_KEYS",
    "DECISION_INPUT_KEYS",
    "INPUT_STATUSES",
    "MAX_NOTE_CHARS",
    "SIGNATURE_INPUT_KEY",
    "SIGNATURE_RECORD_KEYS",
    "STATUS_APPROVED",
    "STATUS_MERGED",
    "STATUS_NEEDS_WORK",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "DecisionInvalid",
    "decision_core",
    "decision_row_problem",
    "expected_proposal_decision",
    "provenance_problem",
    "signature_record_problem",
    "validate_decided_by",
    "validate_decision",
    "validate_provenance",
]


def decision_row_problem(
    item: Any,
    proposals: Mapping[str, Any],
    *,
    corpus: str | None = None,
    committed_at: str | None = None,
) -> str | None:
    """Why a STORED decision item is invalid, or ``None``. The fold applies this to every
    ledger row, so a raw append that bypassed ``validate_decision`` cannot decide anything.
    ``corpus`` and ``committed_at`` (the ledger row's) bind a stored signature to this
    corpus and to the time it was committed (``signature_record_problem``)."""
    if not isinstance(item, Mapping):
        return "not an object"
    pid = item.get("proposal_id")
    if not isinstance(pid, str) or pid not in proposals:
        return "unknown proposal_id"
    if item.get("status") not in DECIDED_STATUSES:
        return "status is not a decided status"
    try:
        validate_decided_by(item.get("decided_by"))
    except DecisionInvalid:
        return "decided_by is not a human reviewer handle"
    note = item.get("note", "")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE_CHARS):
        return "note is not a string within the length cap"
    merge_into = item.get("merge_into")
    if item.get("status") == STATUS_MERGED:
        if not isinstance(merge_into, str) or merge_into not in proposals or merge_into == pid:
            return "merge without a valid merge_into"
    elif merge_into is not None:
        return "merge_into without status merged"
    if "provenance" in item and provenance_problem(item["provenance"]) is not None:
        return "provenance is not a small map of scalar fields"
    return signature_record_problem(item, corpus=corpus, committed_at=committed_at)

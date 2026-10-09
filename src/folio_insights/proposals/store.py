"""Proposal state on the Phase 13 corpus storage context (governance plan KTD3).

``ProposalStore`` turns registry operations into ledger appends on
``ctx.proposals``, and folds the ledger back into a ``ProposalRegistry``.
Use it inside ``async with`` on an open ``CorpusStorageContext``. One store
serves exactly the context's corpus.

Operation IDs are explicit and deterministic:

* ``collect_run``: ``proposals:collect:<run>``. Re-collecting the same run
  with the same input is a replay and adds nothing. The same run name with a
  different input raises ``OperationIdConflict``, because a run's output is
  immutable once collected.
* ``apply_dedupe``: ``proposals:dedupe:<ledger head>:<digest of the
  changes>``, appended only if the ledger is still at that head. Retrying the
  same computation is a replay. A concurrent writer makes it refuse
  (``JournalStateChanged``) rather than apply stale verdicts.
* ``record_judgments``: an op_id from the caller, who owns the judgment.
  Caller op_ids may not use the reserved ``proposals:`` prefix.
* ``record_decisions``: an op_id from the caller (same rule). The whole batch
  is validated before anything is appended; one unknown ID or invalid status
  refuses it all. Every batch is appended, even one whose decisions all equal
  the current ones, so retrying the same op_id always replays and returns the
  committed result with its original ``decided_at``, next to the current status
  (``superseded_since`` lists proposals decided again since). A new batch is
  appended only if the ledger is still at the head it was validated against.

Signed decisions (drain plan U9, R16, KTD11). A decision item may carry
``signature`` (a ``signed_decisions.SignedDecision``). ``record_decisions`` verifies
it before anything is appended: the signature must verify for its did:key, describe
exactly this decision (kind ``proposed_class``, this corpus, the proposal ID, the
verdict, the note and any merge target), be issued within the signing skew of server
time and carry a nonce this ledger has not consumed. The stored item records
``signer_did``, ``signature_verified: true`` and the signed decision; an unsigned item
reads as ``signature_verified: false``. With signatures required
(``FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1``) an unsigned item refuses the batch.
One refused item refuses the whole batch, and nothing is appended.

Every judgment, deterministic or recorded, passes ``judgments.validate_judgment``
before it is appended, and ``apply_dedupe`` refuses a lexicon smaller than
``MIN_LEXICON_CONCEPTS`` (an empty or wrong lexicon would otherwise clear every
deterministic verdict).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jcs

from folio_insights.proposals.decisions import (
    SIGNATURE_INPUT_KEY,
    DecisionInvalid,
    expected_proposal_decision,
    validate_decided_by,
    validate_decision,
    validate_provenance,
)
from folio_insights.proposals.signed_decisions import (
    DecisionReplayed,
    DecisionSignaturePolicy,
    DecisionSignatureRefused,
    load_policy,
    operator_record,
    verify_signed_decision,
)
from folio_insights.proposals.dedupe import DeterministicDeduper
from folio_insights.proposals.judgments import JudgmentInvalid, validate_judgment
from folio_insights.proposals.lexicon import FolioLexicon
from folio_insights.storage.errors import JournalStateChanged
from folio_insights.proposals.registry import (
    DETERMINISTIC,
    KIND_COLLECT,
    KIND_DECISION,
    KIND_JUDGMENT,
    ProposalRegistry,
    collect_payload,
)

if TYPE_CHECKING:
    from folio_insights.storage import CorpusStorageContext

RESERVED_OP_PREFIX = "proposals:"
MIN_LEXICON_CONCEPTS = 3


class ReviewerRequired(DecisionInvalid):
    """An unsigned decision (or one by a signer the signers file does not map to a
    handle) needs a ``decided_by`` reviewer, and none was given."""


#: Placeholder reviewer while an item is validated before its signer is known.
_PENDING_REVIEWER = "human:pending-signer"


def _item_refusal(exc: DecisionSignatureRefused, index: int) -> DecisionSignatureRefused:
    """``exc`` re-raised with the item index (same class, so callers map it the same)."""
    return type(exc)(f"decision item {index}: {exc}")


class LexiconTooSmall(ValueError):
    """The lexicon cannot be FOLIO: running dedupe with it would clear every
    deterministic verdict."""


def _digest(data: Any) -> str:
    return hashlib.sha256(jcs.canonicalize(data)).hexdigest()


def collect_op_id(run: str) -> str:
    return f"proposals:collect:{run}"


class ProposalStore:
    """Registry operations for the corpus of one open storage context."""

    def __init__(self, ctx: CorpusStorageContext) -> None:
        self._ctx = ctx

    @property
    def corpus(self) -> str:
        return self._ctx.corpus

    async def load(self) -> ProposalRegistry:
        return ProposalRegistry.fold(self.corpus, await self._ctx.proposals.entries())

    async def collect_run(
        self,
        run: str,
        proposed_classes: Iterable[Mapping[str, Any]],
        *,
        spans_by_unit: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Collect one run's proposed classes. Returns the counts and whether
        the operation was a replay of an earlier identical collect."""
        payload = collect_payload(
            self.corpus, run, proposed_classes, spans_by_unit=spans_by_unit
        )
        before = await self.load()
        entry, replayed = await self._ctx.proposals.append(
            KIND_COLLECT, payload, op_id=collect_op_id(run)
        )
        new = 0 if replayed else len(
            {o["proposal_id"] for o in payload["observations"]} - set(before.proposals)
        )
        return {
            "run": run,
            "position": entry.position,
            "replayed": replayed,
            "observations": len(payload["observations"]),
            "new": new,
            "dropped": dict(payload["dropped"]),
        }

    async def apply_dedupe(
        self, lexicon: FolioLexicon, *, min_concepts: int = MIN_LEXICON_CONCEPTS
    ) -> dict[str, Any]:
        """Run deterministic dedupe and append its changes (if any)."""
        if len(lexicon.by_iri) < min_concepts:
            raise LexiconTooSmall(
                f"lexicon has {len(lexicon.by_iri)} concept(s), fewer than {min_concepts}; "
                "refusing to dedupe (it would clear every deterministic verdict)"
            )
        registry = await self.load()
        changes = DeterministicDeduper(lexicon).changes(registry)
        known = set(registry.proposals)
        for index, c in enumerate(changes):
            if c["judgment"] is not None:
                c["judgment"] = validate_judgment(
                    c["judgment"], proposal_id=c["proposal_id"], known_ids=known,
                    where=f"dedupe change {index}",
                )
        summary: dict[str, Any] = {"changes": len(changes), "position": None, "replayed": False}
        counts: dict[str, int] = {}
        for c in changes:
            verdict = (c["judgment"] or {}).get("verdict", "CLEARED")
            counts[verdict] = counts.get(verdict, 0) + 1
        summary["verdicts"] = dict(sorted(counts.items()))
        if not changes:
            return summary
        op_id = f"proposals:dedupe:{registry.head}:{_digest(changes)[:32]}"
        entry, replayed = await self._ctx.proposals.append(
            KIND_JUDGMENT, {"judgments": changes}, op_id=op_id, expected_head=registry.head
        )
        summary.update(position=entry.position, replayed=replayed)
        return summary

    async def record_judgments(
        self, judgments: Iterable[Mapping[str, Any]], *, op_id: str
    ) -> dict[str, Any]:
        """Record human or model judgments ``{proposal_id, verdict, judged_by,
        ...}``. Every item is validated before anything is appended
        (``judgments.validate_judgment``); one invalid item refuses the whole
        batch. ``judged_by`` may not be ``deterministic``. Errors name the
        item index, never its values."""
        if not isinstance(op_id, str) or op_id.startswith(RESERVED_OP_PREFIX):
            raise ValueError(
                f"caller op_ids may not use the reserved {RESERVED_OP_PREFIX!r} prefix"
            )
        registry = await self.load()
        known = set(registry.proposals)
        items = []
        for index, j in enumerate(judgments):
            where = f"judgment item {index}"
            if not isinstance(j, Mapping):
                raise JudgmentInvalid(f"{where}: must be an object")
            pid = j.get("proposal_id")
            if not isinstance(pid, str) or pid not in known:
                raise JudgmentInvalid(
                    f"{where}: proposal_id is not a proposal of corpus {self.corpus!r}"
                )
            block = validate_judgment(
                {k: v for k, v in j.items() if k != "proposal_id"},
                proposal_id=pid, known_ids=known, where=where,
            )
            if block["judged_by"] == DETERMINISTIC:
                raise JudgmentInvalid(
                    f"{where}: judged_by must name a human or model judge "
                    "(for example 'human:<reviewer>' or 'model:<name>'), not 'deterministic'"
                )
            items.append({"proposal_id": pid, "judgment": block})
        if not items:
            return {"recorded": 0, "position": None, "replayed": False}
        entry, replayed = await self._ctx.proposals.append(
            KIND_JUDGMENT, {"judgments": items}, op_id=op_id
        )
        return {"recorded": len(items), "position": entry.position, "replayed": replayed}


    async def record_decisions(
        self,
        decisions: Iterable[Mapping[str, Any]],
        *,
        op_id: str,
        decided_by: str | None,
        provenance: Mapping[str, Mapping[str, Any]] | None = None,
        expected_head: int | None = None,
        operator: str | None = None,
        policy: DecisionSignaturePolicy | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record explicit review decisions ``{proposal_id, status, note?,
        merge_into?, signature?}`` by the human reviewer ``decided_by``
        (``human:<name>``).

        ``signature`` (optional, per item) is a signed decision, verified before
        anything is appended (module docstring). A verified item records its
        ``signer_did``; when the signers file maps that DID to a handle, the item is
        attributed to ``human:<handle>`` instead of ``decided_by``. ``decided_by`` may
        be ``None`` only when every item is signed by such a mapped signer
        (``ReviewerRequired`` otherwise). ``operator`` is the authenticated API
        operator who submitted the batch, recorded on every item next to (never
        instead of) its author. ``policy`` defaults to ``signed_decisions.load_policy()``
        (``DecisionPolicyMisconfigured`` when unusable); ``now`` is the server time the
        signatures' ``issued_at`` is checked against (default: the current time).
        Signature refusals raise a ``DecisionSignatureRefused`` subclass naming the
        item index and the rule.

        ``provenance`` optionally maps proposal IDs of this batch to a small
        map of scalar fields (``decisions.validate_provenance``) stored on that
        item, for instance the original row and time of an imported legacy
        decision. A key that names no decision of the batch refuses it all.

        ``expected_head`` (default ``None``: the head this call loads) makes a new
        batch conditional on the ledger head the CALLER computed its decisions
        against, for callers that decide from state they loaded earlier (the
        legacy import). A different head raises ``JournalStateChanged`` and
        appends nothing. A replay of a committed op_id is not affected.

        Returns ``{recorded, unchanged, position, replayed, results,
        superseded_since}``. ``results`` maps each proposal ID to its ``status``
        and ``decided_at`` as of this operation (the original outcome on a
        replay) and to its ``current_status`` / ``current_decided_at`` now.
        ``superseded_since`` lists the proposals whose decision changed after
        this operation. ``unchanged`` counts decisions that already were
        current. Errors name the item index, never values.
        """
        if not isinstance(op_id, str) or not op_id.strip() or op_id.startswith(RESERVED_OP_PREFIX):
            raise ValueError(
                "a decision batch needs an explicit op_id that does not use the reserved "
                f"{RESERVED_OP_PREFIX!r} prefix"
            )
        if decided_by is not None:
            decided_by = validate_decided_by(decided_by)
        registry = await self.load()
        if expected_head is not None and (
            isinstance(expected_head, bool) or not isinstance(expected_head, int)
        ):
            raise ValueError("expected_head must be a ledger position (an integer)")
        policy = policy if policy is not None else load_policy()
        committed = {e.op_id for e in await self._ctx.proposals.entries()}
        replaying = op_id in committed
        recorded_operator = operator_record(operator)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        nonces: set[tuple[str, str]] = set()
        for index, raw in enumerate(decisions):
            signed_raw = None
            if isinstance(raw, Mapping) and SIGNATURE_INPUT_KEY in raw:
                signed_raw = raw[SIGNATURE_INPUT_KEY]
                raw = {k: v for k, v in raw.items() if k != SIGNATURE_INPUT_KEY}
            item = validate_decision(
                raw, index=index, known=registry.proposals,
                decided_by=decided_by or _PENDING_REVIEWER,
            )
            if item["proposal_id"] in seen:
                raise DecisionInvalid(
                    f"decision item {index}: the batch names this proposal more than once"
                )
            seen.add(item["proposal_id"])
            author = decided_by
            if signed_raw is None:
                try:
                    policy.check_unsigned()
                except DecisionSignatureRefused as exc:
                    raise _item_refusal(exc, index) from None
            else:
                try:
                    verified = await verify_signed_decision(
                        signed_raw,
                        expected=expected_proposal_decision(item, self.corpus),
                        policy=policy,
                        now=now,
                        check_freshness=not replaying,
                    )
                except DecisionSignatureRefused as exc:
                    raise _item_refusal(exc, index) from None
                key = (verified.signer_did, verified.nonce)
                if key in nonces or (not replaying and key in registry.decision_nonces):
                    raise DecisionReplayed(
                        f"decision item {index}: this signed decision's nonce was already "
                        "used; a signed decision can be recorded once. Sign it again. "
                        "Nothing was recorded"
                    )
                nonces.add(key)
                author = verified.signer_handle or decided_by
                item["signer_did"] = verified.signer_did
                item["signature_verified"] = True
                item["signature"] = verified.signed.to_record()
            if author is None:
                raise ReviewerRequired(
                    f"decision item {index}: no reviewer to attribute this decision to "
                    "(give decided_by, or sign it with a key the signers file maps to a "
                    "handle); nothing was recorded"
                )
            item["decided_by"] = author
            if recorded_operator is not None:
                item["operator"] = recorded_operator
            items.append(item)
        if not items:
            raise DecisionInvalid("a decision batch must hold at least one decision")
        if provenance:
            if not isinstance(provenance, Mapping) or not set(provenance) <= seen:
                raise DecisionInvalid(
                    "provenance may only name proposals decided in this batch; nothing was "
                    "recorded"
                )
            for index, item in enumerate(items):
                if item["proposal_id"] in provenance:
                    item["provenance"] = validate_provenance(
                        provenance[item["proposal_id"]], where=f"decision item {index}"
                    )
        items.sort(key=lambda i: i["proposal_id"])
        if op_id not in committed and expected_head is not None and expected_head != registry.head:
            raise JournalStateChanged(expected=expected_head, actual=registry.head)
        # Every batch is appended, including one whose decisions all equal the current ones
        # (the fold ignores those items), so a retry under the same op_id always replays.
        # A committed op_id replays (or refuses a different request) before the head check;
        # a new batch must still be at the head it was validated against.
        entry, replayed = await self._ctx.proposals.append(
            KIND_DECISION,
            {"decisions": items},
            op_id=op_id,
            expected_head=None if op_id in committed else (
                registry.head if expected_head is None else expected_head
            ),
        )
        position = entry.position
        entries = await self._ctx.proposals.entries()
        # The result as of this operation (a replay returns the original outcome), and the
        # current state, which later decisions may have changed since.
        as_of = ProposalRegistry.fold(self.corpus, [e for e in entries if e.position <= position])
        current = ProposalRegistry.fold(self.corpus, entries)
        results: dict[str, dict[str, Any]] = {}
        recorded = 0
        stale: list[str] = []
        for i in items:
            pid = i["proposal_id"]
            then = as_of.proposals[pid].decision
            now = current.proposals[pid].decision
            results[pid] = {
                "status": then.get("status"),
                "decided_at": then.get("decided_at"),
                "current_status": now.get("status"),
                "current_decided_at": now.get("decided_at"),
            }
            if then.get("ledger_position") != now.get("ledger_position"):
                stale.append(pid)
            if then.get("ledger_position") == position:
                recorded += 1
        return {
            "recorded": recorded,
            "unchanged": len(items) - recorded,
            "position": position,
            "replayed": replayed,
            "results": results,
            # Proposals whose decision changed after this operation: the result above is
            # historical, not current.
            "superseded_since": sorted(stale),
        }


def load_run_proposals(run_dir: str | Path) -> tuple[list[dict[str, Any]], dict[str, list]]:
    """Read a run's ``proposed_classes.json`` and the unit spans from
    ``discovery.json`` (when present). The caller collects only labels, IDs
    and spans; ``source_text`` is read here and dropped by ``collect_payload``."""
    out = Path(run_dir)
    pcs = json.loads((out / "proposed_classes.json").read_text(encoding="utf-8"))
    spans: dict[str, list] = {}
    disc = out / "discovery.json"
    if disc.exists():
        for u in json.loads(disc.read_text(encoding="utf-8")).get("knowledge_units", []):
            sp = u.get("original_span") or {}
            if "id" in u:
                spans[u["id"]] = [sp.get("start"), sp.get("end")]
    return list(pcs.get("proposed_classes", [])), spans


__all__ = [
    "MIN_LEXICON_CONCEPTS",
    "RESERVED_OP_PREFIX",
    "LexiconTooSmall",
    "ReviewerRequired",
    "ProposalStore",
    "collect_op_id",
    "load_run_proposals",
]

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
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jcs

from folio_insights.proposals.dedupe import DeterministicDeduper
from folio_insights.proposals.lexicon import FolioLexicon
from folio_insights.proposals.registry import (
    DETERMINISTIC,
    KIND_COLLECT,
    KIND_JUDGMENT,
    ProposalRegistry,
    collect_payload,
)

if TYPE_CHECKING:
    from folio_insights.storage import CorpusStorageContext

_JUDGMENT_KEYS = {
    "verdict", "target_iri", "target_proposal_id", "nearest", "reasoning",
    "judged_by", "guardrail",
}
_VERDICTS = {
    "NOVEL", "DUPLICATE_OF", "SYNONYM_OF", "MERGE_WITH", "NEEDS_WORK", "ALIAS_CANDIDATE",
}


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
        }

    async def apply_dedupe(self, lexicon: FolioLexicon) -> dict[str, Any]:
        """Run deterministic dedupe and append its changes (if any)."""
        registry = await self.load()
        changes = DeterministicDeduper(lexicon).changes(registry)
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
        ...}``. Every item is validated before anything is appended. An
        unknown proposal ID, an unknown verdict or a ``deterministic``
        ``judged_by`` refuses the whole batch."""
        registry = await self.load()
        items = []
        for j in judgments:
            pid = j.get("proposal_id")
            if pid not in registry.proposals:
                raise ValueError(f"unknown proposal ID {pid!r} in corpus {self.corpus!r}")
            block = {k: j[k] for k in _JUDGMENT_KEYS if k in j}
            if block.get("verdict") not in _VERDICTS:
                raise ValueError(f"invalid verdict {block.get('verdict')!r} for {pid}")
            judged_by = block.get("judged_by")
            if not isinstance(judged_by, str) or not judged_by or judged_by == DETERMINISTIC:
                raise ValueError(
                    f"judgment for {pid} needs a non-deterministic judged_by "
                    "(for example 'human:<reviewer>' or 'model:<name>')"
                )
            block.setdefault("target_iri", None)
            block.setdefault("target_proposal_id", None)
            block.setdefault("nearest", [])
            block.setdefault("reasoning", "")
            items.append({"proposal_id": pid, "judgment": block})
        if not items:
            return {"recorded": 0, "position": None, "replayed": False}
        entry, replayed = await self._ctx.proposals.append(
            KIND_JUDGMENT, {"judgments": items}, op_id=op_id
        )
        return {"recorded": len(items), "position": entry.position, "replayed": replayed}


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


__all__ = ["ProposalStore", "collect_op_id", "load_run_proposals"]

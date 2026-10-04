"""Proposed-class registry: collect and fold (governance plan U2, Stage A).

The registry is a pure fold over one corpus's proposal ledger
(``ctx.proposals``). Nothing here touches storage. ``store.ProposalStore``
writes the ledger operations that this module builds and reads.

Identity. A proposal's ID is ``PC-`` plus 32 hex characters of
``sha256(corpus, normalized label)``, so it is deterministic and keyed by
corpus. The same label in two corpora gets two IDs. Case and punctuation
variants of one label share an ID: "Synthetic Tort Doctrine A" and
"synthetic-tort doctrine a" are one proposal with two label variants.
Plural and inflection variants keep their own IDs. Deterministic dedupe links
them with a ``MERGE_WITH`` judgment instead of collapsing them, so that
decision stays reviewable.

Provenance holds run names, unit IDs, spans and ledger positions, never source
text. ``proposed_classes.json`` carries each unit's full text, and it is
deliberately dropped at collection (R5: no excerpt-bearing state).

Ledger operation kinds folded here:

* ``collect``: one pipeline run's proposed-class observations. One operation
  per run, with op_id ``proposals:collect:<run>``.
* ``judgment``: judge blocks set or cleared per proposal. Deterministic dedupe
  writes them, and so do recorded human or model judgments. Every judgment
  is kept in ``judgment_history``. A later one supersedes the current one but
  never erases an earlier record.
* ``decision``: explicit human review decisions (U3). A proposal stays
  ``pending`` until one names it; a judgment never changes the decision. A
  decision whose status, note, reviewer and merge target equal the current
  one changes nothing (its original ``decided_at`` stands). A different one
  becomes current and is appended to ``decision_history``; nothing earlier is
  overwritten. ``decided_at`` is the ledger commit time of the operation.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from folio_insights.proposals.decisions import decision_core
from folio_insights.storage.proposals import ProposalLedgerEntry

KIND_COLLECT = "collect"
KIND_JUDGMENT = "judgment"
KIND_DECISION = "decision"
DETERMINISTIC = "deterministic"
SUPPORTING_UNIT_CAP = 8
MAX_LABEL_CHARS = 200

_NORM_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_label(label: str) -> str:
    """Unicode-aware normalization: NFKD, drop combining marks, casefold, and
    turn every run of non-word characters (and ``_``) into one space.

    "Société" and "societe" normalize alike; non-Latin labels keep their
    letters ("合同法" stays "合同法") instead of collapsing to nothing.
    """
    decomposed = unicodedata.normalize("NFKD", label or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NORM_RE.sub(" ", stripped.casefold()).strip()


def stem_label(normalized: str) -> str:
    """Light plural collapse for proposal-to-proposal merges.

    ``-ies`` -> ``-y``, and a trailing ``s`` is dropped, except after ``s``,
    ``u`` or ``i`` (doctrines -> doctrine; class, status, basis unchanged).
    """
    out = []
    for w in normalized.split():
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and w[-2] not in "siu":
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def proposal_id(corpus: str, normalized: str) -> str:
    """Deterministic proposal ID keyed by corpus and normalized label."""
    if not corpus or not normalized:
        raise ValueError("a proposal ID needs a corpus and a non-empty normalized label")
    digest = hashlib.sha256(f"{corpus}\x1f{normalized}".encode()).hexdigest()
    return "PC-" + digest[:32]


def collect_payload(
    corpus: str,
    run: str,
    proposed_classes: Iterable[Mapping[str, Any]],
    *,
    spans_by_unit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The ``collect`` ledger payload for one run, with no source text.

    ``proposed_classes`` rows have the ``proposed_classes.json`` shape. Only
    the label, unit ID, extraction path, confidence and the unit's span go
    into the payload. Observations are sorted, so the same input always gives
    the same bytes and therefore the same request digest.

    Rows that cannot become a proposal are counted in ``dropped`` instead of
    skipped silently: ``empty`` (nothing left after normalization) and
    ``too_long`` (a label over ``MAX_LABEL_CHARS``, which is a passage, not a
    class name).
    """
    if not run:
        raise ValueError("a collect operation needs a run name")
    spans_by_unit = spans_by_unit or {}
    observations = []
    dropped = {"empty": 0, "too_long": 0}
    for pc in proposed_classes:
        label = str(pc.get("proposed_label") or "").strip()
        if len(label) > MAX_LABEL_CHARS:
            dropped["too_long"] += 1
            continue
        norm = normalize_label(label)
        if not norm:
            dropped["empty"] += 1
            continue
        unit_id = str(pc.get("source_unit_id") or "")
        span = spans_by_unit.get(unit_id)
        observations.append({
            "proposal_id": proposal_id(corpus, norm),
            "proposed_label": label,
            "normalized_label": norm,
            "unit_id": unit_id,
            "source_span": list(span) if span is not None else None,
            "extraction_path": str(pc.get("extraction_path") or ""),
            "confidence": float(pc.get("confidence") or 0.0),
        })
    observations.sort(key=lambda o: (o["proposal_id"], o["unit_id"], o["proposed_label"]))
    return {"run": run, "observations": observations, "dropped": dropped}


@dataclass
class Proposal:
    """Folded state of one proposal.

    ``occurrences`` counts observations, not tags. ``proposed_classes.json``
    lists each exact label once per run (at its first unit), so a run
    contributes one observation per distinct exact-label variant of the
    proposal. ``run_occurrences`` holds that count per run, and
    ``occurrences`` is their sum.
    """

    proposal_id: str
    proposed_label: str
    normalized_label: str
    label_variants: list[str] = field(default_factory=list)
    occurrences: int = 0
    run_occurrences: dict[str, int] = field(default_factory=dict)
    supporting_units: list[dict[str, Any]] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    first_seen_run: str = ""
    last_seen_run: str = ""
    first_seen_position: int = -1
    judgment: dict[str, Any] | None = None
    judgment_history: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(
        default_factory=lambda: {"status": "pending", "note": "", "decided_at": None}
    )
    decision_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposed_label": self.proposed_label,
            "normalized_label": self.normalized_label,
            "label_variants": list(self.label_variants),
            "occurrences": self.occurrences,
            "run_occurrences": dict(self.run_occurrences),
            "supporting_units": [dict(s) for s in self.supporting_units],
            "provenance": {"runs": list(self.runs)},
            "first_seen_run": self.first_seen_run,
            "last_seen_run": self.last_seen_run,
            "first_seen_position": self.first_seen_position,
            "judgment": None if self.judgment is None else dict(self.judgment),
            "judgment_history": [dict(j) for j in self.judgment_history],
            "decision": dict(self.decision),
            "decision_history": [dict(d) for d in self.decision_history],
        }


@dataclass
class ProposalRegistry:
    """Folded registry of one corpus."""

    corpus: str
    proposals: dict[str, Proposal] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    head: int = -1

    @classmethod
    def fold(cls, corpus: str, entries: Iterable[ProposalLedgerEntry]) -> ProposalRegistry:
        reg = cls(corpus=corpus)
        for entry in entries:
            reg.apply(entry)
        return reg

    def apply(self, entry: ProposalLedgerEntry) -> None:
        if entry.position <= self.head:
            raise ValueError(
                f"ledger entry at position {entry.position} is not after head {self.head}"
            )
        self.head = entry.position
        if entry.kind == KIND_COLLECT:
            self._apply_collect(entry)
        elif entry.kind == KIND_JUDGMENT:
            self._apply_judgment(entry)
        elif entry.kind == KIND_DECISION:
            self._apply_decision(entry)
        # Unknown kinds (later units) are skipped by this fold, never misread.

    def _apply_collect(self, entry: ProposalLedgerEntry) -> None:
        run = entry.payload["run"]
        observations = entry.payload.get("observations", [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for obs in observations:
            grouped.setdefault(obs["proposal_id"], []).append(obs)
        new = 0
        for pid, group in grouped.items():
            p = self.proposals.get(pid)
            norms = {obs["normalized_label"] for obs in group}
            if len(norms) != 1 or (p is not None and p.normalized_label not in norms):
                raise ValueError(
                    f"proposal ID {pid} maps to more than one normalized label; the "
                    "ledger is inconsistent (an ID collision or a corrupted row)"
                )
            if p is None:
                p = Proposal(
                    proposal_id=pid,
                    proposed_label=group[0]["proposed_label"],
                    normalized_label=group[0]["normalized_label"],
                    first_seen_run=run,
                    first_seen_position=entry.position,
                )
                self.proposals[pid] = p
                new += 1
            for obs in group:
                if obs["proposed_label"] not in p.label_variants:
                    p.label_variants.append(obs["proposed_label"])
            p.run_occurrences[run] = len(group)
            p.occurrences = sum(p.run_occurrences.values())
            if run not in p.runs:
                p.runs.append(run)
            p.last_seen_run = run
            seen = {(s["run"], s["unit_id"]) for s in p.supporting_units}
            for obs in group:
                key = (run, obs["unit_id"])
                if key in seen or len(p.supporting_units) >= SUPPORTING_UNIT_CAP:
                    continue
                seen.add(key)
                p.supporting_units.append({
                    "run": run,
                    "unit_id": obs["unit_id"],
                    "source_span": obs.get("source_span"),
                    "extraction_path": obs.get("extraction_path", ""),
                    "ledger_position": entry.position,
                })
        self.runs[run] = {
            "position": entry.position,
            "op_id": entry.op_id,
            "committed_at": entry.committed_at,
            "observations": len(observations),
            "proposals": len(grouped),
            "new_proposals": new,
            "dropped": dict(entry.payload.get("dropped", {})),
        }

    def _apply_judgment(self, entry: ProposalLedgerEntry) -> None:
        for item in entry.payload.get("judgments", []):
            p = self.proposals.get(item["proposal_id"])
            if p is None:
                continue  # writers refuse unknown IDs; the fold stays defensive
            record = {
                "judgment": item.get("judgment"),
                "ledger_position": entry.position,
                "op_id": entry.op_id,
                "committed_at": entry.committed_at,
            }
            p.judgment_history.append(record)
            p.judgment = None if item.get("judgment") is None else {
                **item["judgment"],
                "ledger_position": entry.position,
                "committed_at": entry.committed_at,
            }

    def _apply_decision(self, entry: ProposalLedgerEntry) -> None:
        for item in entry.payload.get("decisions", []):
            p = self.proposals.get(item["proposal_id"])
            if p is None:
                continue  # writers refuse unknown IDs; the fold stays defensive
            core = decision_core(item)
            if core == decision_core(p.decision):
                continue  # an identical decision keeps its original decided_at
            record = {
                **core,
                "decided_at": entry.committed_at,
                "ledger_position": entry.position,
                "op_id": entry.op_id,
            }
            p.decision_history.append(dict(record))
            p.decision = record

    # ---- queries ------------------------------------------------------

    def get(self, pid: str) -> Proposal | None:
        return self.proposals.get(pid)

    def by_label(self, label: str) -> Proposal | None:
        norm = normalize_label(label)
        return self.proposals.get(proposal_id(self.corpus, norm)) if norm else None

    def all(self) -> list[Proposal]:
        return [self.proposals[k] for k in sorted(self.proposals)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "proposed-class-registry/v2",
            "corpus": self.corpus,
            "ledger_head": self.head,
            "runs": {k: dict(v) for k, v in sorted(self.runs.items())},
            "proposals": [p.to_dict() for p in self.all()],
        }


def judgment_core(judgment: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A judgment without its ledger bookkeeping, for equality checks."""
    if judgment is None:
        return None
    return {k: v for k, v in judgment.items() if k not in {"ledger_position", "committed_at"}}


__all__ = [
    "DETERMINISTIC",
    "KIND_COLLECT",
    "KIND_DECISION",
    "KIND_JUDGMENT",
    "SUPPORTING_UNIT_CAP",
    "Proposal",
    "ProposalRegistry",
    "collect_payload",
    "judgment_core",
    "normalize_label",
    "proposal_id",
    "stem_label",
]

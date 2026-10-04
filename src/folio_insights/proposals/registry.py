"""Proposed-class registry: collect and fold (governance plan U2, Stage A).

The registry is a pure fold over one corpus's proposal ledger
(``ctx.proposals``). Nothing here touches storage. ``store.ProposalStore``
writes the ledger operations that this module builds and reads.

Identity. A proposal's ID is ``PC-`` plus 16 hex characters of
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
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from folio_insights.storage.proposals import ProposalLedgerEntry

KIND_COLLECT = "collect"
KIND_JUDGMENT = "judgment"
DETERMINISTIC = "deterministic"
SUPPORTING_UNIT_CAP = 8

_NORM_RE = re.compile(r"[^a-z0-9]+")


def normalize_label(label: str) -> str:
    """Lower-case; every run of non-alphanumerics becomes one space."""
    return _NORM_RE.sub(" ", (label or "").lower()).strip()


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
    return "PC-" + digest[:16]


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
    """
    if not run:
        raise ValueError("a collect operation needs a run name")
    spans_by_unit = spans_by_unit or {}
    observations = []
    for pc in proposed_classes:
        label = str(pc.get("proposed_label") or "").strip()
        norm = normalize_label(label)
        if not norm:
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
    return {"run": run, "observations": observations}


@dataclass
class Proposal:
    """Folded state of one proposal."""

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

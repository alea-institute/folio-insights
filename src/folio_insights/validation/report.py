"""The cluster validation report (Phase 9 U1, R4): JSON and human-readable.

A ``ValidationReport`` lists the clusters it checked (with the checkers that
actually ran on each and why any fell back), the findings, and the proposed
reconciliations. It is data about the store, never a change to it:
``applied`` is the constant ``False`` (proposals are never applied) and the
report carries no write path.

Every finding names its ``checker``. A cluster that no checker could examine
reads ``unchecked``; the report never presents an unexamined cluster as
consistent.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Literal

import jcs
from pydantic import BaseModel, ConfigDict, Field

from folio_insights.validation.proposals import Proposal

REPORT_FORMAT = "folio-insights/cluster-validation/v1"

FindingKind = Literal[
    "contradiction",           # two (or more) shards that cannot all hold
    "unsatisfiable_class",     # a class the cluster's formal content makes empty
    "tbox_inconsistent",       # the TBox slice / seeds are inconsistent on their own
    "coverage_gap",            # a task-tree leaf without an authority shard
    "cross_framework_citation",  # a shard citing a shard in an incompatible framework
]
Checker = Literal["hermit", "nli", "coverage", "crossref"]
Severity = Literal["warning", "info"]
ConsistencyMode = Literal["formal+textual", "formal", "nli_fallback", "unchecked"]


def finding_id(kind: str, checker: str, shards: list[str], extra: Any = None) -> str:
    """A stable finding ID: the same finding on the same shards always gets
    the same ID, whichever cluster surfaced it."""
    body = {"kind": kind, "checker": checker, "shards": sorted(shards), "extra": extra}
    return hashlib.sha256(jcs.canonicalize(body)).hexdigest()[:16]


class Finding(BaseModel):
    """One problem the validator found."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: FindingKind
    checker: Checker
    severity: Severity = "warning"
    shards: list[str] = Field(default_factory=list)
    # Every cluster that holds all of ``shards`` (the cluster context).
    clusters: list[str] = Field(default_factory=list)
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    proposals: list[Proposal] = Field(default_factory=list)


class ClusterResult(BaseModel):
    """One cluster and how its consistency was checked."""

    model_config = ConfigDict(extra="forbid")

    id: str
    axis: str
    key: str
    size: int
    members: list[str]
    mode: ConsistencyMode = "unchecked"
    checkers: list[Checker] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    formal_axiom_count: int = 0
    finding_ids: list[str] = Field(default_factory=list)
    # Per-checker diagnostics (e.g. the NLI screen's pairs_scored and the
    # shards it excluded for empty text).
    detail: dict[str, Any] = Field(default_factory=dict)


class CheckerStatus(BaseModel):
    """Which checker backends were available for this run."""

    model_config = ConfigDict(extra="forbid")

    hermit: str = "not requested"
    nli: str = "not requested"
    coverage: str = "not requested"
    crossref: str = "not requested"


class ValidationReport(BaseModel):
    """The whole report. ``applied`` is always ``False``."""

    model_config = ConfigDict(extra="forbid")

    format: str = REPORT_FORMAT
    corpus: str = ""
    applied: Literal[False] = False
    shard_count: int = 0
    axes: list[str] = Field(default_factory=list)
    checkers: CheckerStatus = Field(default_factory=CheckerStatus)
    clusters: list[ClusterResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    # ── derived views ─────────────────────────────────────────────────────

    def findings_of(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    def cluster(self, cluster_id: str) -> ClusterResult | None:
        return next((c for c in self.clusters if c.id == cluster_id), None)

    def summary(self) -> dict[str, Any]:
        kinds = Counter(f.kind for f in self.findings)
        modes = Counter(c.mode for c in self.clusters)
        return {
            "shards": self.shard_count,
            "clusters": len(self.clusters),
            "findings": len(self.findings),
            "by_kind": dict(sorted(kinds.items())),
            "cluster_modes": dict(sorted(modes.items())),
        }

    # ── serializations ────────────────────────────────────────────────────

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["summary"] = self.summary()
        return data

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    def render_text(self) -> str:
        """A human-readable rendering for operators."""
        s = self.summary()
        lines = [
            f"Cluster validation — corpus {self.corpus or '(unnamed)'}",
            f"  shards {s['shards']}, clusters {s['clusters']}, findings {s['findings']}"
            " (report only; nothing was applied)",
            "  checkers: "
            + ", ".join(f"{k}={v}" for k, v in self.checkers.model_dump().items()),
        ]
        if s["cluster_modes"]:
            lines.append(
                "  cluster checks: "
                + ", ".join(f"{k} {v}" for k, v in s["cluster_modes"].items())
            )
        fallbacks = [c for c in self.clusters if c.mode in {"nli_fallback", "unchecked"}]
        for c in fallbacks:
            note = "; ".join(c.notes) if c.notes else ""
            lines.append(f"  - {c.id} ({c.size} shards): {c.mode}{' — ' + note if note else ''}")
        if not self.findings:
            lines.append("No findings.")
        for f in self.findings:
            lines.append("")
            lines.append(f"[{f.severity}] {f.kind} ({f.checker}) {f.id}")
            lines.append(f"  {f.summary}")
            for iri in f.shards:
                lines.append(f"  shard {iri}")
            if f.clusters:
                lines.append(f"  clusters: {', '.join(f.clusters)}")
            for p in f.proposals:
                lines.append(f"  {p.rank}. {p.strategy}: {p.rationale}")
        diag = {k: v for k, v in self.diagnostics.items() if v}
        if diag:
            lines.append("")
            lines.append("Diagnostics:")
            for k, v in diag.items():
                lines.append(f"  {k}: {json.dumps(v, sort_keys=True)}")
        return "\n".join(lines) + "\n"


__all__ = [
    "Checker",
    "CheckerStatus",
    "ClusterResult",
    "ConsistencyMode",
    "Finding",
    "FindingKind",
    "REPORT_FORMAT",
    "Severity",
    "ValidationReport",
    "finding_id",
]

"""Valid-time windows from supplied source metadata (Phase 9 U2, KTD12).

Frameworks are not versioned by year; a shard carries the window in which
its content held. Windows come ONLY from metadata the caller supplies —
statutory effective and amendment dates, case decision dates, publication
years — and every window records the evidence it rests on. Inference from
free text is deferred (plan scope).

* **statute / regulation / rules** — the version in force at ``version_date``
  (or the latest version when none is given): ``[effective or the latest
  amendment on or before version_date, the next amendment)``; a repeal date
  closes the last window.
* **case** — ``[decision_date, overruled_date)``.
* **restatement / treatise** — ``[1 January of publication_year, superseded_date)``.

All instants are tz-aware UTC midnights. Windows are half-open ``[start, end)``,
matching ``temporal.query_as_of``.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["statute", "regulation", "rules", "case", "restatement", "treatise", "other"]


class ValidTimeWindow(BaseModel):
    """A half-open valid-time window and the metadata it was derived from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime | None = None
    end: datetime | None = None
    evidence: tuple[str, ...] = ()

    def contains(self, at: datetime) -> bool:
        return (self.start is None or self.start <= at) and (self.end is None or at < self.end)


class SourceTimeMetadata(BaseModel):
    """Dates the caller knows about a source (never parsed from its text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SourceKind = "other"
    effective_date: date | None = None
    amendment_dates: tuple[date, ...] = ()
    repeal_date: date | None = None
    version_date: date | None = None
    decision_date: date | None = None
    overruled_date: date | None = None
    publication_year: int | None = Field(default=None, ge=1000, le=9999)
    superseded_date: date | None = None


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def statute_windows(meta: SourceTimeMetadata) -> list[ValidTimeWindow]:
    """Every consecutive version window of an enacted text, oldest first."""
    if meta.effective_date is None:
        return []
    starts = [("effective_date", meta.effective_date)] + [
        ("amendment_date", d) for d in sorted(set(meta.amendment_dates)) if d > meta.effective_date
    ]
    out: list[ValidTimeWindow] = []
    for i, (label, start) in enumerate(starts):
        evidence = [f"{label}={start.isoformat()}"]
        if i + 1 < len(starts):
            nxt = starts[i + 1][1]
            end: date | None = nxt
            evidence.append(f"next amendment_date={nxt.isoformat()}")
        elif meta.repeal_date is not None:
            end = meta.repeal_date
            evidence.append(f"repeal_date={meta.repeal_date.isoformat()}")
        else:
            end = None
        out.append(ValidTimeWindow(start=_utc(start), end=None if end is None else _utc(end),
                                   evidence=tuple(evidence)))
    return out


def infer_valid_time(meta: SourceTimeMetadata) -> ValidTimeWindow | None:
    """The window a shard extracted from this source holds in, or ``None``
    when the metadata supports none."""
    if meta.kind in ("statute", "regulation", "rules"):
        windows = statute_windows(meta)
        if not windows:
            return None
        if meta.version_date is None:
            chosen = windows[-1]
            return chosen.model_copy(
                update={"evidence": (*chosen.evidence, "no version_date: latest version")}
            )
        at = _utc(meta.version_date)
        for window in windows:
            if window.contains(at):
                return window.model_copy(
                    update={"evidence": (*window.evidence,
                                         f"version_date={meta.version_date.isoformat()}")}
                )
        return None  # the version date precedes the effective date
    if meta.kind == "case" and meta.decision_date is not None:
        evidence = [f"decision_date={meta.decision_date.isoformat()}"]
        end = None
        if meta.overruled_date is not None:
            end = _utc(meta.overruled_date)
            evidence.append(f"overruled_date={meta.overruled_date.isoformat()}")
        return ValidTimeWindow(start=_utc(meta.decision_date), end=end, evidence=tuple(evidence))
    if meta.kind in ("restatement", "treatise") and meta.publication_year is not None:
        evidence = [f"publication_year={meta.publication_year}"]
        end = None
        if meta.superseded_date is not None:
            end = _utc(meta.superseded_date)
            evidence.append(f"superseded_date={meta.superseded_date.isoformat()}")
        return ValidTimeWindow(
            start=datetime(meta.publication_year, 1, 1, tzinfo=UTC), end=end, evidence=tuple(evidence)
        )
    if meta.effective_date is not None:
        return ValidTimeWindow(
            start=_utc(meta.effective_date),
            evidence=(f"effective_date={meta.effective_date.isoformat()}",),
        )
    return None


__all__ = [
    "SourceKind",
    "SourceTimeMetadata",
    "ValidTimeWindow",
    "infer_valid_time",
    "statute_windows",
]

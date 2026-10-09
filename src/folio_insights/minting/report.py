"""The mint run report (drain U8, R1-R5).

``MintReport.as_dict()`` is the JSON ``folio-insights mint --report`` writes:

* ``run`` — run ID, target corpus, extraction file, declared source visibility,
  extractor DID, whether shards and ExtractEvents were signed, dry-run flag.
* ``units`` — one entry per unit in run order: ``minted`` (new shard IRI),
  ``already_present`` (its IRI was already in the corpus; nothing written),
  ``eligible`` (dry run: would be minted) or ``refused`` (primary ``code`` and
  ``detail`` plus every recorded reason). Each minted or present unit also says
  what happened to its ExtractEvent.
* ``counts`` — per status and per refusal code (primary codes only).
* ``framework_migration_warnings`` — the Phase 9 v1 framework-ID migration
  warnings the detector raised, de-duplicated.
* ``cost`` — the LLM run context's usage summary (calls, tokens, templates and,
  with a cost meter, spend). No credential data.
* ``rubric`` — RUB-EXTRACT's deterministic harness over the run's shards in the
  target corpus (``rubric.harness.score`` on ``rubric.adapters.ShardCorpus``,
  restricted to this run's shard IRIs; SHACL and structural evidence are
  corpus-wide). No judged scores are supplied, so ``publishable`` is always
  ``false`` here: Chief's p10 q4 bar (every gate green and RUB-EXTRACT >= 0.80)
  needs judged criteria this harness never computes.

The report never contains source text, unit text or any key material: details
are fixed phrases, counts and identifiers.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from folio_insights.minting.eligibility import Reason

MINTED = "minted"
ALREADY_PRESENT = "already_present"
ELIGIBLE = "eligible"
REFUSED = "refused"
REPORT_FORMAT = 1

# ExtractEvent outcomes.
EVENT_APPENDED = "appended"
EVENT_EXISTING = "existing"
EVENT_UNSIGNED_SKIPPED = "unsigned: skipped"


@dataclass
class UnitOutcome:
    unit_id: str
    status: str
    shard_iri: str | None = None
    code: str | None = None
    detail: str = ""
    reasons: tuple[Reason, ...] = ()
    extract_event: str | None = None
    extraction_prompt_hash: str | None = None
    anchor_method: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"unit_id": self.unit_id, "status": self.status}
        if self.shard_iri is not None:
            out["shard_iri"] = self.shard_iri
        if self.status == REFUSED:
            out["code"] = self.code
            out["detail"] = self.detail
            out["reasons"] = [r.as_dict() for r in self.reasons]
        if self.extract_event is not None:
            out["extract_event"] = self.extract_event
        if self.extraction_prompt_hash is not None:
            out["extraction_prompt_hash"] = self.extraction_prompt_hash
        if self.anchor_method is not None:
            out["anchor_method"] = self.anchor_method
        return out


@dataclass
class MintReport:
    run_id: str
    corpus: str
    extraction: str
    source_visibility: str
    extractor_did: str
    signed: bool
    dry_run: bool = False
    units: list[UnitOutcome] = field(default_factory=list)
    framework_migration_warnings: list[str] = field(default_factory=list)
    cost: dict[str, Any] | None = None
    rubric: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    # ── views ──

    def by_status(self, status: str) -> list[UnitOutcome]:
        return [u for u in self.units if u.status == status]

    @property
    def minted(self) -> list[UnitOutcome]:
        return self.by_status(MINTED)

    @property
    def refused(self) -> list[UnitOutcome]:
        return self.by_status(REFUSED)

    def outcome(self, unit_id: str) -> UnitOutcome:
        for entry in self.units:
            if entry.unit_id == unit_id:
                return entry
        raise KeyError(unit_id)

    def shard_iris(self) -> list[str]:
        """This run's shard IRIs (minted or already present), in run order."""
        return [u.shard_iri for u in self.units
                if u.shard_iri is not None and u.status in (MINTED, ALREADY_PRESENT)]

    def counts(self) -> dict[str, Any]:
        statuses = Counter(u.status for u in self.units)
        codes = Counter(u.code for u in self.units if u.status == REFUSED and u.code)
        events = Counter(u.extract_event for u in self.units if u.extract_event)
        return {
            "units": len(self.units),
            "by_status": dict(sorted(statuses.items())),
            "refused_by_code": dict(sorted(codes.items())),
            "extract_events": dict(sorted(events.items())),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": REPORT_FORMAT,
            "run": {
                "run_id": self.run_id,
                "corpus": self.corpus,
                "extraction": self.extraction,
                "source_visibility": self.source_visibility,
                "extractor_did": self.extractor_did,
                "signed": self.signed,
                "dry_run": self.dry_run,
            },
            "counts": self.counts(),
            "units": [u.as_dict() for u in self.units],
            "framework_migration_warnings": sorted(set(self.framework_migration_warnings)),
            "cost": self.cost,
            "rubric": self.rubric,
            "publishable": False,
            "notes": list(self.notes),
        }


async def rubric_section(
    root: Any,
    corpus: str,
    shard_iris: list[str],
    *,
    sources_dir: Any,
    oracle: Any = None,
) -> dict[str, Any]:
    """The deterministic RUB-EXTRACT report over this run's shards (module docstring)."""
    from dataclasses import replace

    from folio_insights.rubric.adapters import ShardCorpus
    from folio_insights.rubric.harness import score

    if not shard_iris:
        return {"computed": False, "reason": "the run has no shards in the corpus to score",
                "publishable": False}
    artifact = await ShardCorpus.load(root, corpus, sources_dir)
    wanted = set(shard_iris)
    artifact = replace(
        artifact,
        units=tuple(u for u in artifact.units if u.id in wanted),
        notes=(*artifact.notes,
               "units restricted to this mint run's shards; SHACL and structural "
               "checks cover the whole corpus"),
    )
    report = score(artifact, oracle).as_dict()
    # Never claim publishable from a run with no judged scores (KTD4, Chief p10 q4).
    report["publishable"] = False
    report["computed"] = True
    report["oracle"] = "none" if oracle is None else type(oracle).__name__
    return report


__all__ = [
    "ALREADY_PRESENT",
    "ELIGIBLE",
    "EVENT_APPENDED",
    "EVENT_EXISTING",
    "EVENT_UNSIGNED_SKIPPED",
    "MINTED",
    "REFUSED",
    "REPORT_FORMAT",
    "MintReport",
    "UnitOutcome",
    "rubric_section",
]

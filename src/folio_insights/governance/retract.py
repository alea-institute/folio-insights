"""Phase 7 retract module — D-16 standalone discipline (PRD §3.1.4, GOV-06).

The RETRACTION mechanism: a reviewer withdraws a shard from the corpus and
triggers a downstream cascade over its dependents. Retraction is DISTINCT
from contest (PRD §21.8 — a vote of disagreement on a single shard) and
DISTINCT from supersession (PRD §21.9 — a new shard replaces an old one
with valid-time semantics; the old shard stays in the audit trail). The
reviewer must pick the RIGHT mechanism for the philosophical situation —
D-16 software discipline refuses to let a unified ``disagree()`` helper
hide the distinction.

**D-16 boundary:** this module imports ONLY from:
  * ``folio_insights.governance.events`` (the shared event class umbrella),
  * ``folio_insights.revision.store`` (ShardStore — Phase 5 seam),
  * ``folio_insights.revision.content_edit`` (``canonical_content_hash``
    discipline — the JCS-canonical SHA-256 helper),
  * stdlib + Pydantic + Phase 6 identity primitives (signing).

It does NOT import from ``governance.contest`` or ``governance.supersede``.
The D-16 grep-guard regression test
(``tests/governance/test_grep_guard_three_way_disambiguation.py``) auto-
flips from skip-mode to full-triad enforcement the moment this module ships
— no edit needed in 07-05b.

D-04 boundary: stdlib + Pydantic + identity (no rdflib / pyshacl / aiosqlite
imports). The SHACL belt for RetractionEvent lives in
``governance/shape_validation.py::validate_retraction_shape`` — the lone
exempt module.

D-17 three-mode discipline (cascade preview):
  * default (interactive): build_cascade_preview -> rich.table.Table -> confirm.
  * ``--preview``: build_cascade_preview -> write JSON -> exit 0 without commit.
  * ``--apply <file>``: load preview JSON -> commit_cascade -> RE-RUNS
    build_cascade_preview and refuses with ``PreviewStale`` if
    ``underlying_state_hash`` differs.

D-18 dependents classifier (locked verbatim by RESEARCH lines 1338-1353):
  * ``auto_rederive``  — prefer_latest + supersession_available.
  * ``review_needed``  — any human-judgment marker (contested/aporetic status,
                         non-prefer_latest strategy, unresolved contest votes).
  * ``aporetic``       — fall-through.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import jcs
from pydantic import BaseModel, ConfigDict

from folio_insights.governance.events import RetractionEvent

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from folio_insights.governance.log import GovernanceLog
    from folio_insights.revision.store import ShardStore


# ── Exception type for the D-17 PreviewStale refusal ───────────────────────


class PreviewStale(ValueError):
    """Raised by ``commit_cascade`` when the underlying corpus state has
    changed between preview capture and commit (D-17).

    The error message MUST reference ``--preview`` so the operator knows
    the remediation: re-run ``governance retract <iri> --preview`` to
    capture a fresh cascade preview reflecting the new state.
    """


# ── CascadePreview Pydantic model (D-17 — immutable, hashable) ─────────────


class CascadePreview(BaseModel):
    """Immutable cascade-preview snapshot used by the ``--apply`` mode (D-17).

    The preview is captured at ``taken_at`` over the (ShardStore + GovernanceLog)
    state described by ``underlying_state_hash``. ``commit_cascade`` re-runs
    ``build_cascade_preview`` on the current state and refuses to commit if the
    hash differs (PreviewStale).

    Frozen + extra="forbid" so a preview round-tripped through JSON is
    structurally identical and any extra field at ``--apply`` time
    triggers a Pydantic ValidationError before the race-check runs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    retracted_shard_iri: str
    corpus: str
    taken_at: datetime
    underlying_state_hash: str
    auto_rederive: list[str]
    aporetic: list[str]
    review_needed: list[str]


# ── D-18 classifier (heuristic locked by RESEARCH lines 1338-1353) ─────────


def classify_dependent(
    dep_attrs: dict,
) -> Literal["auto_rederive", "aporetic", "review_needed"]:
    """Classify a single dependent into one of three buckets (D-18).

    Heuristic (verbatim from RESEARCH lines 1338-1353):

      1. ``review_needed`` wins on any human-judgment marker:
         * ``epistemic_status in {contested, aporetic}``;
         * ``unresolved_contest_count > 0``;
         * ``reconciliation_strategy`` is set AND not ``"prefer_latest"``.
      2. ``auto_rederive`` iff ``reconciliation_strategy == "prefer_latest"``
         AND ``supersession_available`` is True.
      3. Fall-through: ``aporetic``.

    The order of checks matters — a prefer_latest + supersession + contested
    case correctly routes to ``review_needed`` (the contested-status marker
    wins), not ``auto_rederive``.

    Args:
        dep_attrs: a dict that may contain any of the following keys; all
            missing keys default to "safe" values that route to ``aporetic``:
              * ``supersession_available: bool`` (default ``False``)
              * ``reconciliation_strategy: str | None`` (default ``None``)
              * ``epistemic_status: str | None`` (default ``None``)
              * ``unresolved_contest_count: int`` (default ``0``)
    """
    has_succ = bool(dep_attrs.get("supersession_available", False))
    strategy = dep_attrs.get("reconciliation_strategy")
    status = dep_attrs.get("epistemic_status")
    unresolved_votes = int(dep_attrs.get("unresolved_contest_count", 0) or 0)

    # review_needed wins (any human-judgment marker forces review).
    if status in {"contested", "aporetic"}:
        return "review_needed"
    if unresolved_votes > 0:
        return "review_needed"
    if strategy is not None and strategy != "prefer_latest":
        return "review_needed"

    # auto_rederive: prefer_latest + supersession available.
    if strategy == "prefer_latest" and has_succ:
        return "auto_rederive"

    # aporetic: nothing else to go on.
    return "aporetic"


# ── Cascade preview builder + commit (D-17) ────────────────────────────────


def _extract_dep_attrs(dep_shard: Any, retracted_shard: Any) -> dict:
    """Read the classifier-relevant attributes off a dependent shard.

    Phase 7 in-memory: duck-typed ``getattr`` walk over the shard envelope.
    Phase 13 will read these from the SPARQL CONSTRUCT result over the
    materialized graph (RESEARCH lines 1294-1333). The dict shape produced
    here matches the SPARQL CONSTRUCT's output 1:1 so the classifier is
    backend-independent.

    Key inputs:
      * ``supersession_available`` — derived from the RETRACTED shard's
        ``superseded_by`` (a successor exists for the retracted target,
        which is what the dependent would re-derive against).
      * ``reconciliation_strategy`` — read from the dependent's attribute
        if present (set out-of-band on simple shards; on
        ``ConflictingAuthoritiesShard`` it is a first-class field).
      * ``epistemic_status`` — the dependent's envelope status.
      * ``unresolved_contest_count`` — len(``contest_votes``) when the
        dependent is contested and the contest has not been resolved.
    """
    superseded_by = getattr(retracted_shard, "superseded_by", None)
    contested = bool(getattr(dep_shard, "contested", False))
    contest_votes = getattr(dep_shard, "contest_votes", {}) or {}
    unresolved_votes = len(contest_votes) if contested else 0
    return {
        "supersession_available": superseded_by is not None,
        "reconciliation_strategy": getattr(
            dep_shard, "reconciliation_strategy", None
        ),
        "epistemic_status": getattr(dep_shard, "epistemic_status", None),
        "unresolved_contest_count": unresolved_votes,
    }


def _iter_store_items(store: Any) -> list[tuple[str, Any]]:
    """Phase 7 helper: walk the InMemoryShardStore's underlying dict.

    Phase 13 will replace this with a SPARQL CONSTRUCT over the persistent
    backend. For Phase 7 we read the ``_d`` dict directly when available;
    a store without ``_d`` yields an empty walk (the cascade preview will
    contain zero dependents — the SHACL belt at the log layer still
    enforces ``cascade_preview_hash`` non-empty).
    """
    d = getattr(store, "_d", None)
    if d is None:
        return []
    return list(d.items())


def _depends_on(dep_shard: Any, retracted_iri: str) -> bool:
    """True iff the dependent's depends_on_* lists include ``retracted_iri``."""
    for attr in (
        "depends_on_precedents",
        "depends_on_definitions",
        "depends_on_shards",
        "depends_on_axioms",
    ):
        deps = getattr(dep_shard, attr, None) or []
        if retracted_iri in deps:
            return True
    return False


async def _hash_underlying_state(
    retracted_iri: str,
    classified_iris: dict[str, list[str]],
    store: "ShardStore",
    log: "GovernanceLog",
    corpus: str,
) -> str:
    """Deterministic SHA-256 over the cascade-relevant state (D-17, RESEARCH Q6).

    Hashes the set of (dep_iri, epistemic_status, reconciliation_strategy,
    valid_time_end, superseded_by, log_position_at_signing) tuples — these
    are the fields the classifier reads. JCS-canonical so the hash is
    byte-stable across Python runs.

    The log's latest position for the corpus is included so a new event
    appended between preview and commit (even one not affecting the
    classification) is detected.
    """
    # Walk the same set of dependents the builder collected (sort by IRI
    # for deterministic JCS).
    dep_iris = sorted(
        set(classified_iris["auto_rederive"])
        | set(classified_iris["aporetic"])
        | set(classified_iris["review_needed"])
    )
    items: list[dict[str, Any]] = []
    for dep_iri in dep_iris:
        shard = await store.get(dep_iri)
        if shard is None:
            # Shouldn't happen — the builder only adds IRIs it just got from
            # the store. But be defensive.
            continue
        valid_time_end = getattr(shard, "valid_time_end", None)
        items.append(
            {
                "dep_iri": dep_iri,
                "epistemic_status": getattr(shard, "epistemic_status", None),
                "reconciliation_strategy": getattr(
                    shard, "reconciliation_strategy", None
                ),
                "valid_time_end": (
                    valid_time_end.isoformat()
                    if isinstance(valid_time_end, datetime)
                    else None
                ),
                "superseded_by": getattr(shard, "superseded_by", None),
            }
        )

    # The retracted shard's superseded_by also participates (it drives the
    # supersession_available flag for the prefer_latest auto_rederive case).
    retracted = await store.get(retracted_iri)
    retracted_superseded_by = (
        getattr(retracted, "superseded_by", None) if retracted is not None else None
    )

    latest_pos = await log.latest_position(corpus)
    payload = {
        "retracted_iri": retracted_iri,
        "retracted_superseded_by": retracted_superseded_by,
        "corpus": corpus,
        "log_latest_position": latest_pos,
        "dependents": items,
    }
    canonical = jcs.canonicalize(payload)
    return hashlib.sha256(canonical).hexdigest()


async def build_cascade_preview(
    retracted_iri: str,
    corpus: str,
    *,
    store: "ShardStore",
    log: "GovernanceLog",
) -> CascadePreview:
    """Build the cascade preview for ``retracted_iri`` over the current state (D-17 / D-18).

    Phase 7 in-memory: walks the ShardStore looking for shards whose
    ``depends_on_*`` lists include ``retracted_iri``. For each dependent,
    extracts the classifier-relevant attributes via ``_extract_dep_attrs``
    and classifies via ``classify_dependent``.

    Phase 13 will replace the walk with the SPARQL CONSTRUCT in RESEARCH
    lines 1294-1333; the classifier + the CascadePreview shape stay the same.

    Returns an immutable ``CascadePreview`` with the three buckets sorted by
    IRI (deterministic for the JCS-canonical underlying_state_hash).
    """
    retracted_shard = await store.get(retracted_iri)

    classified: dict[str, list[str]] = {
        "auto_rederive": [],
        "aporetic": [],
        "review_needed": [],
    }

    for dep_iri, dep_shard in _iter_store_items(store):
        if dep_iri == retracted_iri:
            continue
        if not _depends_on(dep_shard, retracted_iri):
            continue
        attrs = _extract_dep_attrs(dep_shard, retracted_shard)
        bucket = classify_dependent(attrs)
        classified[bucket].append(dep_iri)

    # Sort each bucket for determinism (JCS canonical hash + reproducible
    # rich.table.Table rendering at the CLI).
    for key in classified:
        classified[key].sort()

    state_hash = await _hash_underlying_state(
        retracted_iri, classified, store, log, corpus
    )

    return CascadePreview(
        retracted_shard_iri=retracted_iri,
        corpus=corpus,
        taken_at=datetime.now(UTC),
        underlying_state_hash=state_hash,
        auto_rederive=classified["auto_rederive"],
        aporetic=classified["aporetic"],
        review_needed=classified["review_needed"],
    )


def _hash_preview(preview: CascadePreview) -> str:
    """Compute the cascade_preview_hash that gets committed in RetractionEvent.

    JCS-canonical SHA-256 over the preview's model_dump — binds the
    RetractionEvent to the specific preview the operator approved.
    """
    payload = preview.model_dump(mode="json")
    canonical = jcs.canonicalize(payload)
    return hashlib.sha256(canonical).hexdigest()


async def commit_cascade(
    preview: CascadePreview,
    *,
    store: "ShardStore",
    log: "GovernanceLog",
    signing_key: "Ed25519PrivateKey",
    did: str,
) -> RetractionEvent:
    """Commit a previously-built cascade preview (D-17).

    Order of operations:
      1. RE-RUN ``build_cascade_preview`` on the current store + log state.
      2. Compare ``current.underlying_state_hash`` to
         ``preview.underlying_state_hash``. If different, raise
         ``PreviewStale`` with a message referencing ``--preview`` so the
         operator knows the remediation.
      3. Build the ``RetractionEvent`` committing the preview hash, sign
         over the canonical payload, and append to the governance log.

    Returns the persisted RetractionEvent (with ``position`` assigned by
    ``log.append``).
    """
    current = await build_cascade_preview(
        preview.retracted_shard_iri, preview.corpus, store=store, log=log
    )
    if current.underlying_state_hash != preview.underlying_state_hash:
        raise PreviewStale(
            f"underlying state changed since preview taken at "
            f"{preview.taken_at.isoformat()}; re-run --preview"
        )

    # Build, sign, verify, append.
    #
    # CR-01: sign + verify-attestation round-trip via the shared CLI helper.
    # `governance/retract.py` is invoked from `cli/retract.py`, so the helper
    # in `cli/_signing.py` is the right seam (lazy import here so retract.py
    # remains importable when the CLI subpackage is absent — symmetry with
    # the existing `from folio_insights.identity.signer import sign_attestation`
    # late import pattern).
    from folio_insights.governance.cli._signing import sign_and_verify_event
    from folio_insights.governance.log import InvalidSignature
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.shards.envelope import AttestedSignature

    now = datetime.now(UTC)
    placeholder_sig = AttestedSignature(
        did=did,
        action="retract",
        signed_at=now,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
        did_doc_snapshot_at=None,
        verified=None,
    )
    event = RetractionEvent(
        corpus=preview.corpus,
        signature=placeholder_sig,
        shard_iri=preview.retracted_shard_iri,
        cascade_preview_hash=_hash_preview(preview),
    )
    validate_retraction(event)

    try:
        sig = await sign_and_verify_event(
            event,
            signing_key=signing_key,
            did=did,
            action="retract",
            signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            now=now,
            cache=InMemoryDidDocCache(),
        )
    except InvalidSignature:
        # Re-raise unchanged — the caller (cli/retract.py) reports via the
        # generic refusal path. The exception type is a ValueError subclass
        # so existing ValueError handlers still trigger.
        raise
    signed_event = event.model_copy(update={"signature": sig})
    persisted = await log.append(signed_event)
    return persisted


# ── Defense-in-depth field validator ───────────────────────────────────────


def validate_retraction(event: RetractionEvent) -> None:
    """Defense-in-depth check for ``RetractionEvent`` field invariants.

    Pydantic enforces type-level invariants; this validator is the cross-field
    runtime check that runs BEFORE the SHACL belt at the log layer.

    Raises ValueError if:
      * ``shard_iri`` is empty,
      * ``cascade_preview_hash`` is empty (a retraction must commit some
        preview the operator confirmed — D-17).
    """
    if not event.shard_iri:
        raise ValueError("RetractionEvent.shard_iri must be non-empty")
    if not event.cascade_preview_hash:
        raise ValueError(
            "RetractionEvent.cascade_preview_hash must be non-empty "
            "(D-17 — every retraction commits the preview the operator confirmed)"
        )


__all__ = [
    "CascadePreview",
    "PreviewStale",
    "RetractionEvent",
    "build_cascade_preview",
    "classify_dependent",
    "commit_cascade",
    "validate_retraction",
]

"""Cascade-preview fixture corpora (07-05b Task 1).

Helper factories that seed an ``InMemoryShardStore`` with a retraction-target
shard plus N dependents, one per D-18 classifier bucket:

  * ``auto_rederive``  — ``reconciliation_strategy="prefer_latest"`` AND
                         the retracted shard has a ``superseded_by`` set.
  * ``aporetic``       — no supersession, no reviewer marker, no contest
                         votes.
  * ``review_needed``  — any of: epistemic_status in {contested, aporetic},
                         reconciliation_strategy != prefer_latest,
                         unresolved contest votes on the dependent.

These factories are shared by:
  * ``tests/governance/test_cascade_preview_classification.py`` (D-18 table)
  * ``tests/governance/test_preview_stale_refusal.py`` (D-17 race test)
  * the human-verify checkpoint REPL one-liner (07-05b Task 3).

D-04 boundary: stdlib + Pydantic + the Phase 5 ShardStore seam only — no
rdflib / pyshacl imports here (fixtures are pure data wiring).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.revision.store import InMemoryShardStore
from folio_insights.shards import HypothesisShard, SimpleAssertionShard
from folio_insights.shards.envelope import Triple

# ── Module-level constants the tests can refer to ──────────────────────────
RETRACTED_IRI = "fi:shard:retracted"
AUTO_REDERIVE_IRIS = ("fi:shard:auto-1", "fi:shard:auto-2")
APORETIC_IRIS = ("fi:shard:aporetic-1",)
REVIEW_NEEDED_IRIS = ("fi:shard:review-1", "fi:shard:review-2")

CORPUS = "cascade-test-corpus"


def _base_shard_kwargs(shard_iri: str) -> dict[str, Any]:
    """Minimal required-field kwargs for a SimpleAssertionShard / HypothesisShard.

    Mirrors the ``tests/shards/conftest.py::_sample_shard`` discipline — every
    required envelope field gets a deterministic default. The defaults differ
    only by ``shard_iri`` + ``source_uri`` so each dependent has a distinct
    identity in the store.
    """
    return {
        "shard_iri": shard_iri,
        "provenance_hash": "0" * 64,
        "source_uri": f"urn:x:fixture:{shard_iri}",
        "source_span": "sample span",
        "extracted_at": datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC),
        "first_extractor_did": "did:key:zFixtureExtractor",
        "triple": Triple(subject="s", predicate="p", object="o"),
        "elaborates": [],
        "sense": "default sense",
        "reference": "urn:folio:concept/default",
        "logical_form_imputed": "DEFAULT(s, p, o)",
        "layer": "L3_jurisdictional",
        "predication_mode": "per_se",
        "fork": "analytic",
        "epistemic_status": "authority_only",
        "verification_method": "extractor_assertion",
        "depends_on_axioms": [],
        "depends_on_definitions": [],
        "depends_on_precedents": [],
        "depends_on_shards": [],
        "framework_id": "us.federal.fixture",
        "speech_act": "holding",
        "extractor_version": "0.1.0",
        "extraction_prompt_hash": "0" * 64,
        "extractor_model": "claude-opus-4-7",
        "signatures": [],
        "content_edits": [],
        "confidence": 0.9,
        "bfo_category": "continuant_independent",
    }


def _make_retracted_shard(*, superseded: bool) -> SimpleAssertionShard:
    """Build the retraction-target shard.

    ``superseded=True`` sets ``superseded_by`` to a non-None IRI — the
    D-18 classifier reads this as ``supersession_available=True`` and
    routes ``prefer_latest`` dependents to ``auto_rederive``.
    """
    kwargs = _base_shard_kwargs(RETRACTED_IRI)
    if superseded:
        kwargs["superseded_by"] = "fi:shard:successor"
    return SimpleAssertionShard(**kwargs)


def _make_auto_rederive_dependent(shard_iri: str) -> HypothesisShard:
    """A HypothesisShard with ``reconciliation_strategy="prefer_latest"``-style
    attribute attached.

    NOTE: ``reconciliation_strategy`` is NOT a core HypothesisShard field
    (it lives on ConflictingAuthoritiesShard with an 8-value Literal that
    does NOT include ``"prefer_latest"``). For the cascade preview's
    duck-typed ``getattr`` walk we attach the attribute imperatively after
    construction — this matches the Phase 7 simulation discipline (the
    Phase 13 SPARQL CONSTRUCT will read the attribute from the materialized
    graph; in-memory Phase 7 reads it via ``getattr``).
    """
    kwargs = _base_shard_kwargs(shard_iri)
    kwargs["depends_on_precedents"] = [RETRACTED_IRI]
    kwargs["generation_method"] = "combinatorial"
    shard = HypothesisShard(**kwargs)
    # Attach the duck-typed attribute the classifier looks for.
    object.__setattr__(shard, "reconciliation_strategy", "prefer_latest")
    return shard


def _make_aporetic_dependent(shard_iri: str) -> SimpleAssertionShard:
    """A simple dependent with no supersession + no reviewer marker.

    With ``epistemic_status="authority_only"`` (default) and NO
    ``reconciliation_strategy`` attribute and NO contest votes, this falls
    through to ``aporetic`` in the D-18 classifier.
    """
    kwargs = _base_shard_kwargs(shard_iri)
    kwargs["depends_on_definitions"] = [RETRACTED_IRI]
    return SimpleAssertionShard(**kwargs)


def _make_review_needed_dependent(
    shard_iri: str,
    *,
    via: str = "contested_status",
) -> SimpleAssertionShard:
    """A dependent routed to ``review_needed`` by the classifier.

    ``via`` selects the marker:
      * ``"contested_status"``  — epistemic_status = "contested"
      * ``"unresolved_votes"``  — contest_votes non-empty + contested=True
      * ``"strategy_mismatch"`` — reconciliation_strategy != "prefer_latest"
    """
    kwargs = _base_shard_kwargs(shard_iri)
    kwargs["depends_on_shards"] = [RETRACTED_IRI]
    if via == "contested_status":
        kwargs["epistemic_status"] = "contested"
    elif via == "unresolved_votes":
        kwargs["contested"] = True
        kwargs["contest_votes"] = {"did:fi:voter-1": "I disagree with the cited authority."}
    shard = SimpleAssertionShard(**kwargs)
    if via == "strategy_mismatch":
        # Non-prefer_latest strategy attached out-of-band — see _make_auto_rederive_dependent.
        object.__setattr__(shard, "reconciliation_strategy", "sense_distinction")
    return shard


async def seed_cascade_corpus(
    *,
    superseded: bool = True,
) -> tuple[InMemoryShardStore, InMemoryGovernanceLog]:
    """Seed and return a (store, log) pair populated for a cascade-preview test.

    Layout (matches the D-18 table):
      * 1 retracted target shard (``RETRACTED_IRI``);
      * 2 auto_rederive dependents (prefer_latest + supersession available);
      * 1 aporetic dependent (nothing to go on);
      * 2 review_needed dependents (contested status + unresolved votes).

    The governance log is empty by default — tests append role assertions
    or contest events as their scenarios require.
    """
    store = InMemoryShardStore()
    log = InMemoryGovernanceLog()

    await store.put(RETRACTED_IRI, _make_retracted_shard(superseded=superseded))

    for iri in AUTO_REDERIVE_IRIS:
        await store.put(iri, _make_auto_rederive_dependent(iri))
    for iri in APORETIC_IRIS:
        await store.put(iri, _make_aporetic_dependent(iri))
    await store.put(
        REVIEW_NEEDED_IRIS[0],
        _make_review_needed_dependent(REVIEW_NEEDED_IRIS[0], via="contested_status"),
    )
    await store.put(
        REVIEW_NEEDED_IRIS[1],
        _make_review_needed_dependent(REVIEW_NEEDED_IRIS[1], via="unresolved_votes"),
    )

    return store, log


async def add_new_dependent(
    store: InMemoryShardStore,
    *,
    iri: str = "fi:shard:racing-late",
) -> None:
    """Mutate the store by inserting a new dependent of the retracted shard.

    Used by ``test_preview_stale_refusal.py`` to simulate "another operator
    appended between preview and apply" — the cascade preview's
    ``underlying_state_hash`` must change as a result.
    """
    kwargs = _base_shard_kwargs(iri)
    kwargs["depends_on_precedents"] = [RETRACTED_IRI]
    shard = SimpleAssertionShard(**kwargs)
    await store.put(iri, shard)


__all__ = [
    "APORETIC_IRIS",
    "AUTO_REDERIVE_IRIS",
    "CORPUS",
    "RETRACTED_IRI",
    "REVIEW_NEEDED_IRIS",
    "add_new_dependent",
    "seed_cascade_corpus",
]

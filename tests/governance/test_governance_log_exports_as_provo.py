"""PROV-O round-trip seed test for GOV-02 (Phase 7).

Appends 3 ExtractEvents to ``InMemoryGovernanceLog``, iterates via
``iter_events``, and builds a minimal RDF graph IN THE TEST (NOT inside the
``governance/`` package — the D-04 boundary keeps rdflib out of every
governance module except ``shape_validation.py``).

Each event maps to a ``prov:Activity`` node with ``prov:wasAttributedTo``
pointing at the signer DID and an ``fi:position`` integer. The graph is
serialized to Turtle and round-trip-parsed; the test asserts ≥3
``prov:Activity`` triples survive.

This is a SEED — the CLI exporter ships in plan 07-05b. The test exists in
Phase 7-03 so the GOV-02 PROV-O contract is staked out from the start
(closes the "ship the contract before the consumer" discipline).

Boundary: rdflib lives in the TEST (outside the governance/ boundary).
The producer (``InMemoryGovernanceLog``) and the events themselves do NOT
touch rdflib. Tests are exempt from the D-04 boundary — only
``src/folio_insights/governance/`` modules are guarded.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from folio_insights.governance.events import ExtractEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


FI = Namespace("https://folio-insights.example/")
PROV = Namespace("http://www.w3.org/ns/prov#")


def _sig(signed_at: datetime, did: str) -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action="extract",
        signed_at=signed_at,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=signed_at,
        verified=None,
    )


async def _seed_log() -> InMemoryGovernanceLog:
    log = InMemoryGovernanceLog()
    for i, (did, day) in enumerate(
        [
            ("did:fi:alice", 1),
            ("did:fi:bob", 2),
            ("did:fi:carol", 3),
        ]
    ):
        await log.append(
            ExtractEvent(
                corpus="test-corpus",
                signature=_sig(datetime(2026, 1, day, tzinfo=UTC), did),
                shard_iri=f"fi:shard:s{i}",
            )
        )
    return log


def test_provo_round_trip_yields_three_activities() -> None:
    """Append 3 ExtractEvents → iter_events → assemble PROV-O graph in the
    test body → serialize to Turtle → round-trip parse → assert ≥3
    ``prov:Activity`` triples + ``prov:wasAttributedTo`` predicates pointing
    at signer DIDs survive.
    """

    async def _collect():
        log = await _seed_log()
        events = []
        async for ev in log.iter_events("test-corpus"):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    assert len(events) == 3

    # Assemble the PROV-O graph IN THE TEST (boundary: rdflib stays outside
    # governance/log.py; the CLI exporter — plan 07-05b — will do this work
    # inside an `export/` module).
    g = Graph()
    g.bind("fi", FI)
    g.bind("prov", PROV)
    for ev in events:
        activity = URIRef(f"urn:fi:event:{ev.corpus}:{ev.position}")
        signer = URIRef(ev.signature.did)
        g.add((activity, RDF.type, PROV.Activity))
        g.add((activity, PROV.wasAttributedTo, signer))
        g.add((activity, FI.position, Literal(ev.position, datatype=XSD.integer)))

    # Round-trip: serialize → parse → query.
    ttl = g.serialize(format="turtle")
    g2 = Graph()
    g2.parse(data=ttl, format="turtle")

    activities = list(g2.subjects(RDF.type, PROV.Activity))
    assert len(activities) >= 3, f"expected ≥3 prov:Activity nodes; got {len(activities)}"

    attributions = list(g2.predicate_objects())
    # At least 3 prov:wasAttributedTo predicates (one per event).
    attr_count = sum(1 for p, _ in attributions if p == PROV.wasAttributedTo)
    assert attr_count >= 3, f"expected ≥3 prov:wasAttributedTo; got {attr_count}"

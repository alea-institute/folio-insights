"""Synthetic SHACL fixtures: valid records and one case per invalid condition.

PRD §10 lists the invalid fixtures the suite must flag. Each ``Case`` below
builds a synthetic record (or a projection-shaped graph for the corpus tier)
and names the expected outcome: severity plus a substring of the shape
message. No book or production content is used.

The PRD cases this model cannot express are recorded in
``NOT_EXPRESSIBLE`` together with the code that enforces them instead.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from folio_insights.polysemy.distinguo import ForkProposal, emit_fork_ttl
from folio_insights.shapes.compiled import turtle_graph
from folio_insights.shapes.rendering import ValidationGraph, render_shard
from folio_insights.shards import (
    AttestedSignature,
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GlossShard,
    HypothesisShard,
    SimpleAssertionShard,
)
from tests.shards.conftest import _SUBTYPE_TABLE, _content_edit, _sample_shard

D = datetime(2026, 3, 1, tzinfo=UTC)
SIGNED = AttestedSignature(
    did="did:key:zSigner",
    action="extract",
    signed_at=D,
    signature="c2lnbmF0dXJlLWJ5dGVz",
    over_content_hash="b" * 64,
    signing_key_id="did:key:zSigner#zSigner",
)


def signed(cls: type = SimpleAssertionShard, **overrides: Any) -> Any:
    """A sample shard that carries one complete signature (no warnings)."""
    overrides.setdefault("signatures", [SIGNED])
    return _sample_shard(cls, **overrides)


def dumped(cls: type = SimpleAssertionShard, **overrides: Any) -> dict[str, Any]:
    return signed(cls, **overrides).model_dump(mode="json")


def mutate(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    out = dict(data)
    out.update(changes)
    return out


@dataclass(frozen=True)
class Case:
    name: str
    build: Callable[[], ValidationGraph]
    severity: str | None          # None: the record conforms with no results
    message: str = ""
    tier: str = "local"


def _g(data: Any) -> ValidationGraph:
    return render_shard(data)[0]


def _fork(**overrides: Any) -> str:
    fields: dict[str, Any] = {
        "term": "consideration",
        "cluster_id": "0a1b2c3d",
        "uses_analogousTo": True,
        "prime_analogate": "urn:folio:term/consideration#commonlaw",
        "proportional_relation": "as bargained-for exchange is to contract formation",
        "distinction_kind": "analogica",
        "source_frameworks": ("CommonLaw", "CivilLaw"),
        "reviewer_did": "did:key:zReviewer",
        "created_at_iso": "2026-03-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return emit_fork_ttl(ForkProposal(**fields))


_FORK_PREFIXES = (
    "@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
)


def _event_graph(**overrides: Any) -> ValidationGraph:
    """A governance event as storage/projection.py renders it."""
    from folio_insights.storage.projection import governance_triples

    event = {
        "corpus": "corpus-a",
        "position": 3,
        "action": "promote",
        "shard_iri": "urn:folio:shard/" + "1" * 32,
        "cited_iris": ["urn:x:a"],
        "signature": {
            "did": "did:key:zAdmin",
            "over_content_hash": "c" * 64,
            "signed_at": "2026-03-01T00:00:00Z",
        },
    }
    event.update(overrides)
    lines = "".join(
        f"{s} {p} {o} .\n" for s, p, o in governance_triples("corpus-a", event, journal_position=7)
    )
    return turtle_graph(lines, prefix="e")


VALID_CASES: list[Case] = [
    *[
        Case(f"valid_{tag}", (lambda c=cls: _g(signed(c))), None)
        for tag, cls in _SUBTYPE_TABLE
    ],
    Case("valid_bounded_interval", lambda: _g(signed(
        valid_time_start=datetime(2026, 1, 1, tzinfo=UTC),
        valid_time_end=datetime(2026, 6, 1, tzinfo=UTC),
    )), None),
    Case("valid_content_edit", lambda: _g(signed(
        content_edits=[_content_edit("sense", "a", "b", D)],
    )), None),
    Case("valid_contest_two_votes", lambda: _g(signed(
        contested=True, epistemic_status="contested",
        contest_votes={"did:key:zA": "for", "did:key:zB": "against"},
    )), None),
    Case("valid_fork_with_analogia", lambda: turtle_graph(_fork()), None),
    Case("valid_fork_without_analogia", lambda: turtle_graph(_fork(
        uses_analogousTo=False, prime_analogate=None, proportional_relation=None,
        distinction_kind="rationis",
    )), None),
    Case("valid_governance_event", lambda: _event_graph(), None),
]


INVALID_CASES: list[Case] = [
    # ── envelope ──
    Case("inverted_valid_time", lambda: _g(signed(
        valid_time_start=datetime(2027, 1, 1, tzinfo=UTC),
        valid_time_end=datetime(2026, 1, 1, tzinfo=UTC),
    )), "Violation", "must be earlier than fi:validTimeEnd"),
    Case("empty_valid_time", lambda: _g(signed(valid_time_start=D, valid_time_end=D)),
         "Violation", "must be earlier than fi:validTimeEnd"),
    Case("unminted_shard_iri", lambda: _g(signed(shard_iri="fi:shard:handmade")),
         "Warning", "minted urn:folio:shard"),
    Case("short_provenance_hash", lambda: _g(signed(provenance_hash="abc")),
         "Warning", "64-character lowercase SHA-256"),
    Case("non_did_extractor", lambda: _g(signed(first_extractor_did="mailto:x@example.org")),
         "Warning", "did:key, did:web or did:plc"),
    Case("unsigned_shard", lambda: _g(_sample_shard(SimpleAssertionShard)),
         "Warning", "at least one AttestedSignature"),
    Case("demonstrable_without_dependency", lambda: _g(signed(epistemic_status="demonstrable")),
         "Warning", "should name at least one dependency"),
    Case("vocab_pin_mismatch", lambda: _g(mutate(dumped(), vocab_version="1999.01.0")),
         "Violation", "VOCAB_VERSION"),
    # ── generated (model-level) ──
    Case("unknown_layer", lambda: _g(mutate(dumped(), layer="L9_imaginary")),
         "Violation", "one of L0_primitive"),
    Case("confidence_out_of_range", lambda: _g(mutate(dumped(), confidence=1.5)),
         "Violation", "in [0.0, 1.0]"),
    Case("missing_required_field", lambda: _g({k: v for k, v in dumped().items() if k != "sense"}),
         "Violation", "SimpleAssertionShard.sense must be required"),
    Case("unknown_field", lambda: _g(mutate(dumped(), smuggled="x")),
         "Violation", "is closed: undeclared field"),
    Case("unknown_shard_type", lambda: _g(mutate(dumped(), shard_type="rumour")),
         "Violation", "five ShardType values"),
    # ── subtypes ──
    Case("disputed_status_outside_subset",
         lambda: _g(mutate(dumped(DisputedPropositionShard), epistemic_status="demonstrable")),
         "Violation", "hypothesis, authority_only, contested or aporetic"),
    Case("disputed_without_objections",
         lambda: _g(mutate(dumped(DisputedPropositionShard), objections=[], replies=[])),
         "Violation", "at least one objection"),
    Case("conflicting_blank_note",
         lambda: _g(mutate(dumped(ConflictingAuthoritiesShard), reconciliation_note="   ")),
         "Violation", "fi:reconciliationNote must not be blank"),
    Case("conflicting_empty_sic",
         lambda: _g(mutate(dumped(ConflictingAuthoritiesShard), sic=[])),
         "Violation", "fi:sic needs at least one"),
    Case("self_gloss", lambda: _g(mutate(dumped(GlossShard), glosses=signed(GlossShard).shard_iri)),
         "Violation", "must not be the shard itself"),
    Case("gloss_bad_target", lambda: _g(mutate(dumped(GlossShard), glosses="ftp://example.org/x")),
         "Violation", "must not be the shard itself"),
    Case("hypothesis_zero_ttl", lambda: _g(mutate(dumped(HypothesisShard), ttl_days=0)),
         "Violation", "fi:ttlDays must be at least 1"),
    # ── governance ──
    Case("contested_one_vote", lambda: _g(signed(
        contested=True, epistemic_status="contested", contest_votes={"did:key:zA": "for"},
    )), "Warning", "at least two contest votes"),
    Case("contested_status_without_flag", lambda: _g(signed(
        epistemic_status="contested", contested=False,
    )), "Warning", "should come with fi:contested true"),
    Case("superseded_without_successor", lambda: _g(signed(epistemic_status="superseded")),
         "Warning", "should name its successor"),
    Case("content_edit_on_immutable_field", lambda: _g(signed(
        content_edits=[_content_edit("source_span", "a", "b", D)],
    )), "Violation", "names an immutable field"),
    Case("governance_event_unknown_action", lambda: _event_graph(action="frobnicate"),
         "Violation", "exactly one known fi:action"),
    Case("governance_event_non_did_signer",
         lambda: _event_graph(signature={"did": "admin", "over_content_hash": "c" * 64}),
         "Violation", "signed by exactly one DID"),
    # ── signatures ──
    Case("verified_without_signature", lambda: _g(signed(signatures=[AttestedSignature(
        did="did:key:zSpoof", action="extract", signed_at=D, verified=True,
    )])), "Violation", "an empty signature can never read as verified"),
    Case("signature_without_signer", lambda: _g(signed(signatures=[SIGNED.model_copy(update={"did": ""})])),
         "Violation", "must name its signer DID"),
    Case("signature_incomplete", lambda: _g(signed(signatures=[SIGNED.model_copy(update={"over_content_hash": ""})])),
         "Warning", "should carry a 64-hex fi:overContentHash"),
    Case("unknown_signed_action", lambda: _g(mutate(dumped(), signatures=[
        {**SIGNED.model_dump(mode="json"), "action": "frobnicate"},
    ])), "Violation", "13 SignedAction"),
    # ── distinguo ──
    Case("analogia_without_relation", lambda: turtle_graph(
        _FORK_PREFIXES
        + '<urn:folio:term/t#a> fi:analogousTo <urn:x:p> ; fi:primeAnalogate <urn:x:p> ;\n'
        '  fi:distinctionKind "analogica" ; fi:proposedBy <did:key:zR> ;\n'
        '  fi:proposedAt "2026-03-01T00:00:00Z"^^xsd:dateTime .\n'
    ), "Violation", "non-blank fi:proportionalRelation"),
    Case("analogia_mismatched_prime", lambda: turtle_graph(
        _FORK_PREFIXES
        + '<urn:folio:term/t#a> fi:analogousTo <urn:x:p> ; fi:primeAnalogate <urn:x:q> ;\n'
        '  fi:proportionalRelation "r" ; fi:distinctionKind "analogica" ;\n'
        '  fi:proposedBy <did:key:zR> ; fi:proposedAt "2026-03-01T00:00:00Z"^^xsd:dateTime .\n'
    ), "Violation", "must equal fi:primeAnalogate"),
    Case("fork_unknown_distinction_kind", lambda: turtle_graph(
        _FORK_PREFIXES
        + '<urn:folio:term/t#a> fi:distinctionKind "imaginaria" ; fi:proposedBy <did:key:zR> ;\n'
        '  fi:proposedAt "2026-03-01T00:00:00Z"^^xsd:dateTime .\n'
    ), "Violation", "4 Scotist values"),
]


# PRD §10 invalid fixtures that SHACL over this model cannot express, and
# what enforces them instead (stated, not silently dropped).
NOT_EXPRESSIBLE: dict[str, str] = {
    "signature verification failure": (
        "cryptographic; identity/verifier.py verify_attestation, run on every governance "
        "append (storage event_verifier). SHACL flags the claim side: verified=true "
        "without a signature value (verified_without_signature)."
    ),
    "promotion without reviewer role": (
        "time-indexed role policy; governance.authorize() re-run inside the storage write "
        "transaction (_authorize_in_transaction)."
    ),
    "arbiter action with reviewer DID": "same as above: governance.authorize().",
}


__all__ = ["INVALID_CASES", "NOT_EXPRESSIBLE", "VALID_CASES", "Case", "dumped", "mutate", "signed"]

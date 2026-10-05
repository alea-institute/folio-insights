"""Hypothesis strategies for every Pydantic-valid shard variant (Phase 11 SHACL-02).

``shards()`` draws an instance of any of the five subtypes, toggling every
optional envelope field (bounded or unbounded valid time, supersession
links, contest state, signatures with cosigners, content edits with
arbitrary JSON values, dependency lists) and every subtype-specific field.
It deliberately draws records that the model accepts but the hand-written
shapes may flag, such as an inverted valid-time interval. Those records
still conform to the generated shapes, which state only what the model
guarantees.

Synthetic text only; no book or production content.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import strategies as st

from folio_insights.shards import (
    AttestedSignature,
    AuthorityPosition,
    ConflictingAuthoritiesShard,
    ContentEdit,
    DisputedPropositionShard,
    GlossShard,
    HypothesisShard,
    Objection,
    Reply,
    SimpleAssertionShard,
    Triple,
    mint_shard_iri,
)
from folio_insights.shards.subtypes import DISPUTED_EPISTEMIC_STATUS_SUBSET

_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=16
)
_IRI = st.from_regex(r"\Aurn:x:[a-z0-9]{1,8}\Z")
_DID = st.from_regex(r"\Adid:key:z[1-9A-HJ-NP-Za-km-z]{4,12}\Z")
_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_TIMES = st.integers(min_value=0, max_value=10**7).map(lambda s: _T0 + timedelta(seconds=s))
# Review P2-1: valid-time bounds are drawn naive as well as aware (the model
# normalizes naive ones to UTC; the differential test then compares engines).
_MAYBE_NAIVE_TIMES = _TIMES | _TIMES.map(lambda d: d.replace(tzinfo=None))
_ACTIONS = st.sampled_from([
    "extract", "promote", "demote", "contest", "supersede", "retract", "distinguo",
    "role_assertion", "role_revocation", "resolve_contest", "content_edit",
    "reparent", "reconcile",
])
_JSON = st.recursive(
    st.none() | st.booleans() | st.integers(-1000, 1000) | _TEXT,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(_TEXT, inner, max_size=3),
    max_leaves=6,
)


@st.composite
def signatures(draw: Any, depth: int = 0) -> AttestedSignature:
    signed = draw(st.booleans())
    return AttestedSignature(
        did=draw(_DID | st.just("")),
        action=draw(_ACTIONS),
        signed_at=draw(st.none() | _TIMES),
        signature=draw(st.from_regex(r"\A[A-Za-z0-9_-]{8,16}\Z")) if signed else "",
        over_content_hash=draw(st.just("a" * 64) | st.just("")),
        signing_key_id=draw(st.just("") | _DID.map(lambda d: f"{d}#k")),
        did_doc_snapshot_at=draw(st.none() | _TIMES),
        verified=draw(st.sampled_from([None, False, True])) if signed else draw(st.sampled_from([None, False])),
        cosigners=draw(st.lists(signatures(depth + 1), max_size=1)) if depth == 0 else [],
    )


@st.composite
def content_edits(draw: Any) -> list[ContentEdit]:
    count = draw(st.integers(0, 2))
    t = draw(_TIMES)
    edits = []
    for _ in range(count):
        t = t + timedelta(seconds=draw(st.integers(0, 100)))
        edits.append(
            ContentEdit(
                field_path=draw(st.sampled_from(["sense", "reference", "confidence", "triple.object"])),
                old_value=draw(_JSON),
                new_value=draw(_JSON),
                edited_at=t,
                editor_did=draw(_DID),
                rationale=draw(_TEXT),
                signature=draw(signatures(1)),
            )
        )
    return edits


@st.composite
def envelope_fields(draw: Any, epistemic: Any) -> dict[str, Any]:
    uri, span = draw(_IRI), draw(_TEXT)
    shard_iri, prov = mint_shard_iri(uri, span)
    start = draw(st.none() | _MAYBE_NAIVE_TIMES)
    end = draw(st.none() | _MAYBE_NAIVE_TIMES)
    contested = draw(st.booleans())
    return {
        "shard_iri": shard_iri,
        "provenance_hash": prov,
        "source_uri": uri,
        "source_span": span,
        "extracted_at": draw(_TIMES),
        "first_extractor_did": draw(_DID),
        "triple": Triple(
            subject=draw(_TEXT), predicate=draw(_TEXT), object=draw(_TEXT),
            object_datatype=draw(st.none() | st.just("http://www.w3.org/2001/XMLSchema#date")),
        ),
        "elaborates": draw(st.lists(_IRI, max_size=2)),
        "sense": draw(_TEXT),
        "reference": draw(_TEXT),
        "logical_form_imputed": draw(_TEXT),
        "layer": draw(st.sampled_from(["L0_primitive", "L1_definitional", "L2_composed", "L3_jurisdictional"])),
        "predication_mode": draw(st.sampled_from(["per_se", "per_accidens"])),
        "fork": draw(st.sampled_from(["analytic", "synthetic_a_posteriori", "synthetic_a_priori"])),
        "epistemic_status": draw(epistemic),
        "verification_method": draw(st.sampled_from([
            "textual_citation", "definitional_derivation", "inferential_chain",
            "extractor_assertion", "reviewer_attested",
        ])),
        "depends_on_axioms": draw(st.lists(_IRI, max_size=2)),
        "depends_on_definitions": draw(st.lists(_IRI, max_size=1)),
        "depends_on_precedents": draw(st.lists(_IRI, max_size=1)),
        "depends_on_shards": draw(st.lists(_IRI, max_size=2)),
        "framework_id": draw(_TEXT),
        "speech_act": draw(st.sampled_from([
            "holding", "dictum", "statutory_text", "statutory_definition", "regulatory_text",
            "pleading_argument", "contract_term", "treatise_statement",
            "restatement_black_letter", "practitioner_advice", "administrative_interpretation",
        ])),
        "extractor_version": draw(_TEXT),
        "extraction_prompt_hash": draw(st.just("0" * 64) | _TEXT),
        "extractor_model": draw(_TEXT),
        "signatures": draw(st.lists(signatures(), max_size=2)),
        "content_edits": draw(content_edits()),
        "confidence": draw(st.floats(0.0, 1.0, allow_nan=False)),
        "bfo_category": draw(st.sampled_from([
            "continuant_independent", "continuant_dependent", "occurrent_process", "occurrent_event",
        ])),
        "valid_time_start": start,
        "valid_time_end": end,
        "transaction_time": draw(_TIMES),
        "supersedes": draw(st.none() | _IRI),
        "superseded_by": draw(st.none() | _IRI),
        "contested": contested,
        "contest_votes": draw(st.dictionaries(_DID, _TEXT, max_size=3)),
    }


_ALL_STATUS = st.sampled_from([
    "per_se_nota_quoad_se", "per_se_nota_quoad_nos", "demonstrable", "authority_only",
    "aporetic", "hypothesis", "contested", "superseded",
])
_OBJECTION = st.builds(Objection, cites=_IRI, argues=_TEXT, strength=st.floats(0.0, 1.0))
_POSITION = st.builds(
    AuthorityPosition, authority_iri=_IRI, position=_TEXT, jurisdiction=_TEXT,
    weight=st.sampled_from(["binding", "persuasive", "minority", "majority"]),
)


@st.composite
def simple_assertions(draw: Any) -> SimpleAssertionShard:
    return SimpleAssertionShard(**draw(envelope_fields(_ALL_STATUS)))


@st.composite
def disputed_propositions(draw: Any) -> DisputedPropositionShard:
    env = draw(envelope_fields(st.sampled_from(sorted(DISPUTED_EPISTEMIC_STATUS_SUBSET))))
    objections = draw(st.lists(_OBJECTION, min_size=1, max_size=3))
    replies = draw(st.lists(
        st.builds(
            Reply,
            objection_index=st.integers(0, len(objections) - 1),
            replies_via=st.sampled_from(["distinguo", "authority_supersession", "scope_limitation", "factual_distinction"]),
            argument=_TEXT,
        ),
        max_size=3,
    ))
    return DisputedPropositionShard(
        **env, utrum=draw(_TEXT), objections=objections, sed_contra=draw(_OBJECTION),
        respondeo=draw(_TEXT), uses_distinctions=draw(st.lists(_IRI, max_size=2)), replies=replies,
    )


_NON_BLANK = _TEXT.filter(lambda s: s.strip() != "")


@st.composite
def conflicting_authorities(draw: Any) -> ConflictingAuthoritiesShard:
    return ConflictingAuthoritiesShard(
        **draw(envelope_fields(_ALL_STATUS)),
        sic=draw(st.lists(_POSITION, min_size=1, max_size=2)),
        non=draw(st.lists(_POSITION, min_size=1, max_size=2)),
        reconciliation_strategy=draw(st.sampled_from([
            "sense_distinction", "contextual_limitation", "voice_attribution", "textual_correction",
            "retraction_later", "subsequent_overruling", "jurisdictional_scoping", "unreconciled",
        ])),
        reconciliation_note=draw(_NON_BLANK),
    )


@st.composite
def glosses(draw: Any) -> GlossShard:
    target = draw(st.from_regex(r"\Aurn:folio:shard/[a-f0-9]{32}\Z") | st.just("https://example.org/x"))
    env = draw(envelope_fields(_ALL_STATUS))
    if target == env["shard_iri"]:
        target = "https://example.org/other"
    return GlossShard(
        **env, glosses=target,
        gloss_kind=draw(st.sampled_from(["clarificatoria", "extensiva", "restrictiva", "dissentiens", "historica"])),
        gloss_text=draw(_NON_BLANK),
    )


@st.composite
def hypotheses(draw: Any) -> HypothesisShard:
    return HypothesisShard(
        **draw(envelope_fields(_ALL_STATUS)),
        generation_method=draw(st.sampled_from(["combinatorial", "inductive", "analogical"])),
        promotion_requirements=draw(st.lists(_TEXT, max_size=2)),
        ttl_days=draw(st.integers(1, 3650)),
        citation_required=draw(st.booleans()),
    )


SUBTYPE_STRATEGIES = {
    "simple_assertion": simple_assertions(),
    "disputed_proposition": disputed_propositions(),
    "conflicting_authorities": conflicting_authorities(),
    "gloss": glosses(),
    "hypothesis": hypotheses(),
}


def shards() -> Any:
    return st.one_of(*SUBTYPE_STRATEGIES.values())


__all__ = ["SUBTYPE_STRATEGIES", "shards"]

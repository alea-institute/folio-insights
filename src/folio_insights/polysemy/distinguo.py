"""VOCAB-02 distinguo fork emission layer.

Emits typed `fi:analogousTo` triples for reviewer-modified polysemy
verdicts. The atomic-triad invariant (Pitfall 5 / PHILOSOPHY.md L126) is
enforced at the pydantic model layer — a ForkProposal that claims
analogia MUST carry both the prime analogate and the proportional
relation in the same graph.

Consumer contracts locked by this module:

* `ForkProposal`            — the emission-layer model (superset of
  ``ProposedFork``). Frozen + extra='forbid' so schema drift at 01-05 /
  01-06 raises pydantic errors rather than silently mutating.
* `emit_fork_ttl(fork)`     — renders the canonical Pattern-2 Turtle
  (01-RESEARCH.md §Pattern 2, lines 334-373) used by 01-05 CLI `modify`.
* `validate_fork_proposal_shape(fork)` — defense-in-depth check for
  forks rehydrated via `.model_construct()` (bypasses validators).
* `DistinctionKind`         — the 4-enum Literal for ``fi:distinctionKind``.
* `FI_VOCAB`                — canonical namespace IRI (PRD §7.1).

The named-graph target for emitted triples is ``urn:folio:proposal/<cluster_id>``
so Phase 15 can ingest per-proposal provenance (D-3 lock).

Phase 9 U6 adds the PRD §8 P6 fork shape (R9):

* `DistinguoFork` / `build_distinguo_fork` — a term forked into
  jurisdiction-scoped classes (one per registered framework) under a shared
  SKOS grouping, with a configurable prime analogate (default: the common-law
  sense, per the PRD acceptance test).
* `emit_distinguo_fork_ttl(fork, disposition)` — renders it, and ONLY against a
  recorded human disposition (accept or modify, ``labeler == "human"``, same
  cluster, term and reviewer). Nothing in the package writes a fork into a
  TBox; this is the one path that produces TBox-bound fork triples, so no CLI
  or API path can release a fork without a human disposition (PRINCIPLE-06).

Output (existing vocabulary terms only; SKOS for the grouping)::

    <urn:folio:term/consideration> a skos:Concept ; skos:prefLabel "consideration" ;
        skos:narrower <...#us.common_law>, <...#us.louisiana.civil_code> ;
        fi:distinguishes <...#us.common_law>, <...#us.louisiana.civil_code> ;
        fi:distinctionKind "analogica" ; fi:proposedBy <did> ; fi:proposedAt "..." .
    <...#us.louisiana.civil_code> a owl:Class, skos:Concept ; rdfs:label "..." ;
        skos:broader <urn:folio:term/consideration> ;
        fi:framework <framework/us.louisiana.civil_code> ; fi:jurisdiction "us.louisiana" ;
        fi:analogousTo <...#us.common_law> ; fi:primeAnalogate <...#us.common_law> ;
        fi:proportionalRelation "..." .

The non-prime senses carry the analogia triad (Pitfall 5: all three or none),
which is what ``shapes/ttl/distinguo.shacl.ttl`` validates.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from folio_insights.polysemy.dispositions import (
    DispositionRecord,
    ProposedFork,
    check_disposition,
)

if TYPE_CHECKING:
    from folio_insights.models.framework import FrameworkRegistry

# Canonical folio-insights vocabulary IRI (PRD §7.1, VOCAB-02).
FI_VOCAB = "https://folio-insights.aleainstitute.ai/vocab/"

# VOCAB-02 4-enum lock — a 5th value raises pydantic ValidationError at
# ForkProposal construction time.
DistinctionKind = Literal[
    "realis",
    "rationis",
    "rationis_cum_fundamento_in_re",
    "analogica",
]


class ForkProposal(BaseModel):
    """Emission-layer fork — superset of ProposedFork with provenance fields.

    The @model_validator guarantees Pitfall 5 never ships: if
    ``uses_analogousTo`` is True, both ``prime_analogate`` and
    ``proportional_relation`` MUST be non-None / non-empty. This is the
    analogia-atomicity invariant from PHILOSOPHY.md L126.

    ``source_frameworks`` is a tuple (not a list) so the model stays
    hashable/frozen; the ``to_proposed_fork()`` projection converts it to
    the JSONL-embedded list shape the 01-02 ProposedFork expects.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str
    cluster_id: str                           # hex8, minted by 01-03 prototype_cluster
    uses_analogousTo: bool
    prime_analogate: str | None = None        # IRI string
    proportional_relation: str | None = None  # plain literal (prose allowed)
    distinction_kind: DistinctionKind
    source_frameworks: tuple[str, ...]        # e.g. ("CommonLaw", "Restatement2d")
    reviewer_did: str                         # from reviewer.ensure_reviewer_did()
    created_at_iso: str                       # ISO-8601 UTC

    @model_validator(mode="after")
    def _analogia_atomic_triad(self) -> "ForkProposal":
        """Pitfall 5: analogia is atomic — no sub-property may be omitted."""
        if self.uses_analogousTo:
            if not self.prime_analogate:
                raise ValueError(
                    "uses_analogousTo=True requires prime_analogate "
                    "(Pitfall 5: analogia is atomic — no sub-property may be omitted)"
                )
            if not self.proportional_relation:
                raise ValueError(
                    "uses_analogousTo=True requires proportional_relation "
                    "(Pitfall 5: analogia is atomic — no sub-property may be omitted)"
                )
        return self

    def to_proposed_fork(self) -> ProposedFork:
        """Project down to the JSONL-embedded shape used by 01-02 / 01-05."""
        return ProposedFork(
            cluster_id=self.cluster_id,
            term=self.term,
            frameworks=list(self.source_frameworks),
            uses_analogousTo=self.uses_analogousTo,
            prime_analogate=self.prime_analogate,
            proportional_relation=self.proportional_relation,
            distinction_kind=self.distinction_kind,
        )


def validate_fork_proposal_shape(fork: ForkProposal) -> None:
    """Defense-in-depth check.

    Model construction already guarantees the invariant, but call-sites
    that load forks via ``ForkProposal.model_construct(...)`` bypass the
    validator. Re-run the check explicitly before emit so no invalid fork
    is ever serialized to TTL.

    Raises:
        ValueError if the analogia atomic triad is violated OR if
        ``distinction_kind`` is not one of the 4 canonical values.
    """
    if fork.uses_analogousTo:
        if not fork.prime_analogate:
            raise ValueError(
                "ForkProposal uses_analogousTo=True but prime_analogate is empty "
                "(Pitfall 5 defense-in-depth — bypassed pydantic validator)"
            )
        if not fork.proportional_relation:
            raise ValueError(
                "ForkProposal uses_analogousTo=True but proportional_relation is empty "
                "(Pitfall 5 defense-in-depth — bypassed pydantic validator)"
            )
    allowed = {"realis", "rationis", "rationis_cum_fundamento_in_re", "analogica"}
    if fork.distinction_kind not in allowed:
        raise ValueError(
            f"distinction_kind must be one of {sorted(allowed)}, "
            f"got {fork.distinction_kind!r}"
        )


def _escape_turtle_literal(s: str) -> str:
    """Minimal Turtle literal escape: backslash, double-quote, newline, carriage-return.

    Rationale: ``proportional_relation`` is free-form prose supplied by the
    reviewer through the CLI `modify` path (01-05). The string is
    emitted inside a ``"..."`` literal in the Turtle output, so backslash +
    quote + newline require escaping per the Turtle 1.1 grammar
    (§2.5.2 ECHAR). pyoxigraph's parser rejects unescaped newlines in
    single-quoted literals — we escape rather than triple-quote to keep
    the emitted TTL short and grep-friendly.
    """
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\r", "\\r")
         .replace("\n", "\\n")
    )


def emit_fork_ttl(fork: ForkProposal) -> str:
    """Render a ForkProposal as Pattern-2 Turtle.

    Preconditions: fork passes ``validate_fork_proposal_shape()`` —
    called here defensively because a caller that used
    ``model_construct()`` bypasses the pydantic validator.

    Output: a self-contained Turtle string with ``fi:`` and ``xsd:``
    prefixes declared. The caller is responsible for loading the result
    into the correct named graph ``urn:folio:proposal/<cluster_id>``.
    """
    validate_fork_proposal_shape(fork)  # defense-in-depth (Pitfall 5)

    # Subject IRI = the term-sense node for the FIRST framework in
    # source_frameworks. This mirrors 01-RESEARCH.md §Pattern 2 line 335:
    # ``<urn:folio:term/consideration#commonlaw>``.
    subject_iri = (
        f"urn:folio:term/{fork.term}#{fork.source_frameworks[0].lower()}"
    )

    lines: list[str] = [
        f"@prefix fi: <{FI_VOCAB}> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<{subject_iri}>",
    ]

    if fork.uses_analogousTo:
        # ATOMIC TRIAD (PHILOSOPHY.md L126 / Pitfall 5): emit all three
        # together or none. validate_fork_proposal_shape() guarantees the
        # sub-properties are populated when we reach this branch.
        assert fork.prime_analogate is not None       # for type-checkers
        assert fork.proportional_relation is not None
        lines.extend([
            f"    fi:analogousTo             <{fork.prime_analogate}> ;",
            f"    fi:primeAnalogate          <{fork.prime_analogate}> ;",
            f'    fi:proportionalRelation    "{_escape_turtle_literal(fork.proportional_relation)}" ;',
        ])

    lines.extend([
        f'    fi:distinctionKind         "{fork.distinction_kind}" ;',
        f"    fi:proposedBy              <{fork.reviewer_did}> ;",
        f'    fi:proposedAt              "{fork.created_at_iso}"^^xsd:dateTime .',
    ])

    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# Phase 9 U6 — the PRD §8 P6 fork shape
# ──────────────────────────────────────────────────────────────────────────

SKOS = "http://www.w3.org/2004/02/skos/core#"
OWL = "http://www.w3.org/2002/07/owl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"

# PRD §8 P6 acceptance: "fi:primeAnalogate pointing to the common-law sense
# (configurable)". The first of these present in a fork is the default prime;
# a caller names another with ``prime_analogate=``.
DEFAULT_PRIME_ANALOGATE_PREFERENCE: tuple[str, ...] = ("us.common_law", "uk.england.common_law")


class ForkNotReleased(PermissionError):
    """A fork was asked for without a recorded human disposition releasing it."""


class SenseClass(BaseModel):
    """One jurisdiction-scoped class of a forked term."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iri: str
    framework_id: str
    framework_iri: str
    framework_label: str
    jurisdiction: str


class DistinguoFork(BaseModel):
    """A term forked into framework-scoped classes under a SKOS grouping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str = Field(min_length=1)
    cluster_id: str
    grouping_iri: str
    senses: tuple[SenseClass, ...]
    distinction_kind: DistinctionKind
    prime_analogate: str | None = None          # a sense's framework_id
    proportional_relation: str | None = None
    reviewer_did: str = Field(min_length=1)
    created_at_iso: str

    @model_validator(mode="after")
    def _shape(self) -> "DistinguoFork":
        frameworks = [s.framework_id for s in self.senses]
        if len(frameworks) < 2 or len(set(frameworks)) != len(frameworks):
            raise ValueError("a fork has at least two senses, one per distinct framework")
        has_prime = bool(self.prime_analogate)
        has_relation = bool(self.proportional_relation and self.proportional_relation.strip())
        if has_prime != has_relation:
            raise ValueError(
                "prime_analogate and proportional_relation come together "
                "(Pitfall 5: analogia is atomic — no sub-property may be omitted)"
            )
        if self.distinction_kind == "analogica" and not has_prime:
            raise ValueError("an analogica fork needs a prime analogate and a proportional relation")
        if has_prime and self.prime_analogate not in frameworks:
            raise ValueError(
                f"prime analogate {self.prime_analogate!r} is not one of the fork's frameworks"
            )
        return self

    def sense(self, framework_id: str) -> SenseClass:
        return next(s for s in self.senses if s.framework_id == framework_id)


def build_distinguo_fork(
    *,
    term: str,
    cluster_id: str,
    framework_ids: Iterable[str],
    registry: "FrameworkRegistry",
    reviewer_did: str,
    created_at_iso: str,
    distinction_kind: DistinctionKind = "analogica",
    proportional_relation: str | None = None,
    prime_analogate: str | None = None,
) -> DistinguoFork:
    """Fork ``term`` into one class per registered framework.

    Every framework must be registered (``UnregisteredFramework`` if not): the
    jurisdiction of each class comes from the registry. For an ``analogica``
    fork the prime analogate defaults to the first framework of
    ``DEFAULT_PRIME_ANALOGATE_PREFERENCE`` present; with none present the
    caller must name one.
    """
    from folio_insights.polysemy.tbox import term_class_iri, term_grouping_iri

    senses = []
    for framework_id in sorted(set(framework_ids)):
        framework = registry.resolve(framework_id)
        senses.append(SenseClass(
            iri=term_class_iri(term, framework.id),
            framework_id=framework.id,
            framework_iri=framework.iri,
            framework_label=framework.label,
            jurisdiction=framework.jurisdiction,
        ))
    if prime_analogate is None and distinction_kind == "analogica":
        present = {s.framework_id for s in senses}
        prime_analogate = next(
            (fw for fw in DEFAULT_PRIME_ANALOGATE_PREFERENCE if fw in present), None
        )
        if prime_analogate is None:
            raise ValueError(
                "no common-law sense in this fork; name the prime analogate explicitly"
            )
    return DistinguoFork(
        term=term,
        cluster_id=cluster_id,
        grouping_iri=term_grouping_iri(term),
        senses=tuple(senses),
        distinction_kind=distinction_kind,
        prime_analogate=prime_analogate,
        proportional_relation=proportional_relation,
        reviewer_did=reviewer_did,
        created_at_iso=created_at_iso,
    )


def check_fork_release(fork: DistinguoFork, disposition: DispositionRecord) -> None:
    """Raise ``ForkNotReleased`` unless ``disposition`` is a human accept/modify
    of this fork's cluster and term, by the fork's reviewer."""
    try:
        check_disposition(disposition)
    except ValueError as exc:
        raise ForkNotReleased(str(exc)) from exc
    problems = []
    if disposition.labeler != "human":
        problems.append(f"labeler is {disposition.labeler!r}, not 'human'")
    if disposition.decision not in ("accept", "modify"):
        problems.append(f"decision is {disposition.decision!r}")
    if disposition.cluster_id != fork.cluster_id:
        problems.append("disposition is for another cluster")
    if disposition.term != fork.term:
        problems.append("disposition is for another term")
    if disposition.reviewer_did != fork.reviewer_did:
        problems.append("disposition reviewer is not the fork's proposer")
    if problems:
        raise ForkNotReleased(
            "a fork is released only by a recorded human accept/modify disposition: "
            + "; ".join(problems)
        )


def distinguo_fork_triples(fork: DistinguoFork) -> list[tuple[str, str, object]]:
    """``(subject, predicate, object)``: IRIs as ``str``, literals as
    ``("literal", text)`` or ``("typed", text, datatype)``."""
    fi = FI_VOCAB
    g = fork.grouping_iri
    out: list[tuple[str, str, object]] = [
        (g, RDF_TYPE, f"{SKOS}Concept"),
        (g, f"{SKOS}prefLabel", ("literal", fork.term)),
        (g, f"{fi}distinctionKind", ("literal", fork.distinction_kind)),
        (g, f"{fi}proposedBy", fork.reviewer_did),
        (g, f"{fi}proposedAt", ("typed", fork.created_at_iso, XSD_DATETIME)),
    ]
    prime_iri = fork.sense(fork.prime_analogate).iri if fork.prime_analogate else None
    for sense in fork.senses:
        out += [
            (g, f"{SKOS}narrower", sense.iri),
            (g, f"{fi}distinguishes", sense.iri),
            (sense.iri, RDF_TYPE, f"{OWL}Class"),
            (sense.iri, RDF_TYPE, f"{SKOS}Concept"),
            (sense.iri, f"{RDFS}label", ("literal", f"{fork.term} ({sense.framework_label})")),
            (sense.iri, f"{SKOS}broader", g),
            (sense.iri, f"{fi}framework", sense.framework_iri),
            (sense.iri, f"{fi}jurisdiction", ("literal", sense.jurisdiction)),
        ]
        if prime_iri is not None and sense.iri != prime_iri:
            assert fork.proportional_relation is not None  # the model validator's triad
            out += [
                (sense.iri, f"{fi}analogousTo", prime_iri),
                (sense.iri, f"{fi}primeAnalogate", prime_iri),
                (sense.iri, f"{fi}proportionalRelation", ("literal", fork.proportional_relation)),
            ]
    return out


def emit_distinguo_fork_ttl(fork: DistinguoFork, disposition: DispositionRecord) -> str:
    """The fork as Turtle, released by a human ``disposition`` (``ForkNotReleased``
    otherwise). The caller loads it into ``urn:folio:proposal/<cluster_id>``;
    entering a TBox is a further governed step outside this package."""
    from pyoxigraph import Literal as OxLiteral
    from pyoxigraph import NamedNode, RdfFormat, Triple, serialize

    check_fork_release(fork, disposition)

    def term_of(o: object) -> NamedNode | OxLiteral:
        if isinstance(o, tuple) and o[0] == "literal":
            return OxLiteral(o[1])
        if isinstance(o, tuple) and o[0] == "typed":
            return OxLiteral(o[1], datatype=NamedNode(o[2]))
        return NamedNode(str(o))

    triples = [
        Triple(NamedNode(s), NamedNode(p), term_of(o)) for s, p, o in distinguo_fork_triples(fork)
    ]
    return serialize(
        triples,
        format=RdfFormat.TURTLE,
        prefixes={"fi": FI_VOCAB, "skos": SKOS, "owl": OWL, "rdfs": RDFS},
    ).decode("utf-8")


__all__ = [
    "DEFAULT_PRIME_ANALOGATE_PREFERENCE",
    "FI_VOCAB",
    "DistinctionKind",
    "DistinguoFork",
    "ForkNotReleased",
    "ForkProposal",
    "SenseClass",
    "build_distinguo_fork",
    "check_fork_release",
    "distinguo_fork_triples",
    "emit_distinguo_fork_ttl",
    "emit_fork_ttl",
    "validate_fork_proposal_shape",
]

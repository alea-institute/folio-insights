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
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from folio_insights.polysemy.dispositions import ProposedFork

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


__all__ = [
    "FI_VOCAB",
    "DistinctionKind",
    "ForkProposal",
    "emit_fork_ttl",
    "validate_fork_proposal_shape",
]

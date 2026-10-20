"""Term-scoped TBox classes and the Rule 1 axiom-conflict check (Phase 9 U6).

Rule 1 of the detector (OQ-1 lock) asks whether the TBox states a
framework-conflicting axiom for a term: an ``owl:disjointWith`` between the
term's framework-scoped classes. The Phase 1 spike asked that with a SPARQL
pattern whose disjointness triple was not joined to the term or the
frameworks, so any ``owl:disjointWith`` anywhere in the graph satisfied it, and
its fixture TBox was empty, so the rule never had anything real to read.

Here each (term, framework) pair names one class, ``term_class_iri``, and
Rule 1 asks a ``SubsumptionReasoner`` (KTD10: entailment questions go to a
reasoner, never to the similarity module) whether the two classes are
disjoint. The seeds in ``tbox_seeds.ttl`` state those disjointness axioms for
the starter frameworks; ``disjointness_seed_ttl`` renders further seeds (the
labeled set carries its own per case). Seeds load into the shared TBox graph,
the graph the storage projection keeps the vocabulary in.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from importlib.resources import files
from typing import TYPE_CHECKING
from urllib.parse import quote

from pyoxigraph import NamedNode, RdfFormat

from folio_insights.polysemy.fixture_loader import resolve_framework_id
from folio_insights.reason.reasoner import SubsumptionReasoner, SubsumptionResult
from folio_insights.reason.structural import StructuralReasoner

if TYPE_CHECKING:
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

# The shared TBox named graph (``storage.projection.TBOX_GRAPH``; a test pins
# the two together without importing storage here).
TBOX_GRAPH_IRI = "https://folio-insights.aleainstitute.ai/tbox"
TERM_NS = "urn:folio:term/"
SEEDS_RESOURCE = "tbox_seeds.ttl"


def term_grouping_iri(term: str) -> str:
    """The IRI of a term's cross-framework grouping (the SKOS concept)."""
    if not term:
        raise ValueError("an empty term has no grouping IRI")
    return TERM_NS + quote(term, safe="")


def term_class_iri(term: str, framework: str) -> str:
    """The IRI of ``term``'s class scoped to ``framework`` (a registered
    framework ID or a spike fixture label)."""
    return f"{term_grouping_iri(term)}#{resolve_framework_id(framework)}"


def seed_ttl() -> str:
    """The shipped disjointness seeds (``tbox_seeds.ttl``)."""
    return (files("folio_insights.polysemy") / SEEDS_RESOURCE).read_text("utf-8")


def disjointness_seed_ttl(term: str, pairs: Iterable[Sequence[str]]) -> str:
    """Turtle stating each framework pair's term-scoped classes disjoint."""
    lines = [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "",
    ]
    for pair in pairs:
        fw_a, fw_b = pair
        a, b = NamedNode(term_class_iri(term, fw_a)), NamedNode(term_class_iri(term, fw_b))
        lines.append(f"{a} a owl:Class .")
        lines.append(f"{b} a owl:Class .")
        lines.append(f"{a} owl:disjointWith {b} .")
    return "\n".join(lines) + "\n"


def load_tbox_seeds(
    store: PyoxigraphStore, ttl: str | None = None, *, graph: str = TBOX_GRAPH_IRI
) -> None:
    """Load disjointness seeds (default: the shipped ones) into ``graph``."""
    store.store.bulk_load(
        (seed_ttl() if ttl is None else ttl).encode("utf-8"),
        RdfFormat.TURTLE,
        to_graph=NamedNode(graph),
    )


def _reasoner(source: PyoxigraphStore | SubsumptionReasoner, graph: str) -> SubsumptionReasoner:
    if isinstance(source, SubsumptionReasoner):
        return source
    return StructuralReasoner(source, graph)


def framework_conflicts(
    source: PyoxigraphStore | SubsumptionReasoner,
    term: str,
    frameworks: Iterable[str],
    *,
    graph: str = TBOX_GRAPH_IRI,
) -> list[SubsumptionResult]:
    """Every framework pair whose ``term``-scoped classes the reasoner finds
    disjoint (pairs in sorted order; deterministic)."""
    reasoner = _reasoner(source, graph)
    ordered = sorted(set(frameworks))
    found: list[SubsumptionResult] = []
    for i, fw_a in enumerate(ordered):
        for fw_b in ordered[i + 1:]:
            result = reasoner.are_disjoint(term_class_iri(term, fw_a), term_class_iri(term, fw_b))
            if result.holds:
                found.append(result)
    return found


def has_framework_conflicting_axiom(
    source: PyoxigraphStore | SubsumptionReasoner,
    term: str,
    frameworks: list[str],
    *,
    graph: str = TBOX_GRAPH_IRI,
) -> bool:
    """Rule 1: True iff some framework pair's ``term``-scoped classes are disjoint.

    No stated conflict means False ('coincidence'), never 'maybe polysemous':
    embedding distance is not a fallback for this signal (OQ-1 lock).
    """
    return bool(framework_conflicts(source, term, frameworks, graph=graph))


__all__ = [
    "SEEDS_RESOURCE",
    "TBOX_GRAPH_IRI",
    "TERM_NS",
    "disjointness_seed_ttl",
    "framework_conflicts",
    "has_framework_conflicting_axiom",
    "load_tbox_seeds",
    "seed_ttl",
    "term_class_iri",
    "term_grouping_iri",
]

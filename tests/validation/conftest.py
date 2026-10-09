"""Phase 9 U1 cluster-validator fixtures: synthetic shards and fake backends.

Everything here is synthetic. Shards come from the storage builder
(``tests/storage/conftest.py::shard``), with framework IDs from the starter
registry; propositions are invented one-liners, never source text.

* ``FakeNli`` — a deterministic NLI scorer: two texts contradict when one is
  the other with a single ``not`` inserted. It records every pair it scored.
* ``FakeReasoner`` — a pure-Python stand-in for HermiT over the formal triples
  the validator emits: an individual typed into two disjoint classes (after
  ``rdfs:subClassOf`` closure) is an inconsistency; a class whose closure
  holds two disjoint classes is unsatisfiable. It counts its calls.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from folio_insights.models.framework import FrameworkRegistry
from folio_insights.shards import ShardEnvelope, Triple
from folio_insights.validation.formal import (
    OWL_DISJOINT_WITH,
    RDF_TYPE,
    RDFS_SUBCLASS_OF,
    FormalVerdict,
)

from tests.storage.conftest import shard as _storage_shard

FOLIO = "https://folio.openlegalstandard.org/"
OWL = "http://www.w3.org/2002/07/owl#"


def iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def folio(local: str) -> str:
    return FOLIO + local


def vshard(n: int, **overrides: Any) -> ShardEnvelope:
    """A synthetic shard with a registered framework (``us.common_law``) and a
    neutral, non-formal triple unless overridden."""
    defaults: dict[str, Any] = {
        "framework_id": "us.common_law",
        "source_uri": f"urn:x:source/{n}",
        "triple": Triple(subject="synthetic subject", predicate="synthetic predicate",
                         object="synthetic object"),
        "reference": f"urn:x:reference/{n}",
    }
    defaults.update(overrides)
    return _storage_shard(n, **defaults)


def type_triple(individual: str, cls: str) -> Triple:
    return Triple(subject=individual, predicate=RDF_TYPE, object=cls)


@pytest.fixture
def registry() -> FrameworkRegistry:
    return FrameworkRegistry.with_defaults()


class FakeNli:
    """Contradiction iff the texts differ by exactly one inserted ``not``."""

    name = "nli:fake"

    def __init__(self) -> None:
        self.scored: list[tuple[str, str]] = []

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(text.lower().replace(".", "").split())

    def contradiction_probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        out: list[float] = []
        for a, b in pairs:
            self.scored.append((a, b))
            na, nb = self._norm(a), self._norm(b)
            negated = na != nb and (
                na.replace(" not ", " ") == nb or nb.replace(" not ", " ") == na
            )
            out.append(0.95 if negated else 0.02)
        return out


class BrokenNli:
    name = "nli:broken"

    def contradiction_probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        raise RuntimeError("model weights unavailable")


class FakeReasoner:
    """Disjointness-and-subsumption reasoner over ground triples."""

    name = "fake-reasoner"

    def __init__(self) -> None:
        self.calls = 0

    def check(self, triples: Sequence[tuple[str, str, str]]) -> FormalVerdict:
        self.calls += 1
        supers: dict[str, set[str]] = {}
        disjoint: set[frozenset[str]] = set()
        types: dict[str, set[str]] = {}
        for s, p, o in triples:
            if p == RDFS_SUBCLASS_OF:
                supers.setdefault(s, set()).add(o)
            elif p == OWL_DISJOINT_WITH:
                disjoint.add(frozenset((s, o)))
            elif p == RDF_TYPE and not o.startswith(OWL):
                types.setdefault(s, set()).add(o)

        def closure(classes: set[str]) -> set[str]:
            seen = set(classes)
            stack = list(classes)
            while stack:
                for parent in supers.get(stack.pop(), ()):
                    if parent not in seen:
                        seen.add(parent)
                        stack.append(parent)
            return seen

        def clashes(classes: set[str]) -> bool:
            return any(pair <= classes for pair in disjoint if len(pair) == 2)

        for classes in types.values():
            if clashes(closure(classes)):
                return FormalVerdict(consistent=False)
        unsat = sorted(c for c in supers if clashes(closure({c})))
        return FormalVerdict(consistent=True, unsatisfiable=tuple(unsat))

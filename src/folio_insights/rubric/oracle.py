"""IRI oracles for RUB-EXTRACT-03 (IRI validity and branch membership).

RUB-EXTRACT-03 asks two mechanical questions of every non-proposed FOLIO tag: does the
IRI resolve to a real FOLIO concept, and does that concept sit in the branch the tag
claims? An ``IriOracle`` answers both. The criterion takes the oracle as a parameter, so
the same code runs against two sources of truth:

* ``FixtureOracle`` reads a frozen JSON file (CI and the books gold set use
  ``tests/rubric/fixtures/folio_oracle.json``). It knows exactly the concepts listed in
  the file and nothing else: an IRI that is absent does not exist.
* ``FolioResolveOracle`` asks the real FOLIO ontology through the pinned
  ``folio-resolve`` package (``FolioPythonProvider`` over ``folio-python``). It is
  imported lazily, because loading FOLIO needs the ontology cache or the network; CI
  never constructs one.

A concept's *branch* is the label of its top-level FOLIO class (a direct child of
``owl:Thing``), for example "Service", "Location" or "Document / Artifact", the same
names the folio tagger writes into ``ConceptTag.branch``. A concept with several parents
can sit in several branches, so ``branch_of`` returns every one of them.

"IRI exists" is not "IRI correct" (books UAT EP-INSIGHTS-BOOKS-002): an oracle can
prove an IRI is real and in the claimed branch, never that it is the right concept for
the unit. That judgment is RUB-EXTRACT-01's, which the deterministic harness never
scores.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
FOLIO_IRI_PREFIX = "https://folio.openlegalstandard.org/"
FIXTURE_FORMAT = 1
# A FOLIO class hierarchy is shallow (the deepest known chains are under 20 levels); the
# bound only stops a malformed provider from looping.
_MAX_DEPTH = 64


def normalize_branch(branch: str) -> str:
    """Compare branch names case-, space- and slash-spacing-insensitively."""
    return " ".join((branch or "").replace("/", " / ").split()).casefold()


@runtime_checkable
class IriOracle(Protocol):
    """What RUB-EXTRACT-03 needs to know about an IRI."""

    def exists(self, iri: str) -> bool:
        """True iff ``iri`` names a real concept of the ontology."""
        ...

    def branch_of(self, iri: str) -> tuple[str, ...]:
        """The top-level branch label(s) the concept sits in; empty when unknown."""
        ...


class OracleError(ValueError):
    """An oracle file is missing, malformed or of an unknown format."""


@dataclass(frozen=True)
class FixtureConcept:
    label: str
    branches: tuple[str, ...]


@dataclass(frozen=True)
class FixtureOracle:
    """A frozen oracle: exactly the concepts in a JSON file.

    File shape (``format`` 1)::

        {"format": 1,
         "source": "...how the entries were verified...",
         "concepts": {"<iri>": {"label": "...", "branches": ["Service"]}}}

    Only the IRIs a fixture set uses belong in the file. Real FOLIO IRIs must be
    recorded as the live ontology reports them; an invented IRI must say so in its
    label (``"SYNTHETIC ..."``) so it can never be mistaken for a real concept.
    """

    concepts: Mapping[str, FixtureConcept] = field(default_factory=dict)
    source: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> FixtureOracle:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise OracleError(f"oracle file not found: {path}") from exc
        except ValueError as exc:
            raise OracleError(f"oracle file is not valid JSON: {path}: {exc}") from exc
        return cls.from_dict(data, where=str(path))

    @classmethod
    def from_dict(cls, data: Any, *, where: str = "<dict>") -> FixtureOracle:
        if not isinstance(data, Mapping) or data.get("format") != FIXTURE_FORMAT:
            raise OracleError(f"{where}: expected an oracle object with format {FIXTURE_FORMAT}")
        raw = data.get("concepts")
        if not isinstance(raw, Mapping):
            raise OracleError(f"{where}: 'concepts' must be an object keyed by IRI")
        concepts: dict[str, FixtureConcept] = {}
        for iri, entry in raw.items():
            if not isinstance(iri, str) or not iri:
                raise OracleError(f"{where}: concept keys must be non-empty IRIs")
            if not isinstance(entry, Mapping):
                raise OracleError(f"{where}: concept {iri!r} must be an object")
            branches = entry.get("branches", [])
            if not isinstance(branches, list) or not all(isinstance(b, str) for b in branches):
                raise OracleError(f"{where}: concept {iri!r} 'branches' must be a list of strings")
            concepts[iri] = FixtureConcept(
                label=str(entry.get("label", "")), branches=tuple(branches)
            )
        return cls(concepts=concepts, source=str(data.get("source", "")))

    def exists(self, iri: str) -> bool:
        return iri in self.concepts

    def branch_of(self, iri: str) -> tuple[str, ...]:
        concept = self.concepts.get(iri)
        return concept.branches if concept is not None else ()


class FolioResolveOracle:
    """The live FOLIO ontology through the pinned ``folio-resolve`` provider.

    ``provider`` is anything with folio-resolve's ``get_concept(iri) -> Concept | None``
    (``FolioPythonProvider`` by default, built on first use). Answers are cached per
    instance. Never constructed in CI: loading FOLIO needs its cache or the network.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider
        self._exists: dict[str, bool] = {}
        self._branches: dict[str, tuple[str, ...]] = {}

    def _get_provider(self) -> Any:
        if self._provider is None:
            from folio_resolve import FolioPythonProvider  # lazy: loads FOLIO on first use

            self._provider = FolioPythonProvider()
        return self._provider

    def _concept(self, iri: str) -> Any | None:
        if not iri or iri == OWL_THING:
            return None
        return self._get_provider().get_concept(iri)

    def exists(self, iri: str) -> bool:
        if iri not in self._exists:
            self._exists[iri] = self._concept(iri) is not None
        return self._exists[iri]

    def branch_of(self, iri: str) -> tuple[str, ...]:
        if iri in self._branches:
            return self._branches[iri]
        branches: set[str] = set()
        seen: set[str] = set()
        frontier: list[tuple[str, int]] = [(iri, 0)]
        while frontier:
            current, depth = frontier.pop()
            if current in seen or depth > _MAX_DEPTH:
                continue
            seen.add(current)
            concept = self._concept(current)
            if concept is None:
                continue
            parents = [
                p for p in getattr(concept, "parent_iris", ()) or ()
                if p != OWL_THING and self._concept(p) is not None
            ]
            if not parents:
                # A top-level class (possibly the IRI itself): its rdfs:label is the branch
                # name the tagger records ("Location"; its preferred label can differ).
                label = getattr(concept, "label", "") or getattr(concept, "preferred_label", "")
                if label:
                    branches.add(label)
                continue
            frontier.extend((p, depth + 1) for p in parents)
        result = tuple(sorted(branches))
        self._branches[iri] = result
        return result


def load_oracle(spec: str | Path | None) -> IriOracle | None:
    """``None`` -> no oracle; ``"folio"`` -> the live ontology; else a fixture file."""
    if spec is None or spec == "":
        return None
    if str(spec) == "folio":
        return FolioResolveOracle()
    return FixtureOracle.from_file(spec)


__all__ = [
    "FIXTURE_FORMAT",
    "FOLIO_IRI_PREFIX",
    "OWL_THING",
    "FixtureConcept",
    "FixtureOracle",
    "FolioResolveOracle",
    "IriOracle",
    "OracleError",
    "load_oracle",
    "normalize_branch",
]

"""Offline gold loading and deterministic resolution against a pinned FOLIO slice.

The slice records named rdfs:subClassOf edges and their ancestor closure from one
local OWL snapshot. Its digest is independent of both gold and pipeline output.
It proves identity/ancestry, not semantic correctness or human adjudication.
Gold document validation checks exact support via span.source_slice(source.text);
callers use the same accessor to derive support without persisting source quotes.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from folio_insights.measurement.schema import (
    GoldSuite,
    MeasurementModel,
    Nonempty,
    Sha256,
)

DEFAULT_GOLD_DIR = Path("data/measurement/synthetic")


class GoldSetError(ValueError):
    """Missing, malformed or unresolvable measurement gold."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoldSetError(f"gold file not found: {path}") from exc
    except (ValueError, UnicodeError) as exc:
        raise GoldSetError(f"gold file is not valid JSON: {path}: {exc}") from exc


def concepts_digest(concepts: list[dict[str, Any]]) -> str:
    payload = json.dumps(concepts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OntologyConcept(MeasurementModel):
    iri: Nonempty
    label: Nonempty
    alternative_labels: tuple[Nonempty, ...] = ()
    parents: tuple[Nonempty, ...] = ()


class OntologySnapshot(MeasurementModel):
    format: Literal[1]
    source_url: Nonempty
    source_sha256: Sha256
    license: Nonempty
    concepts_sha256: Sha256
    concepts: tuple[OntologyConcept, ...] = Field(min_length=1)


@dataclass(frozen=True)
class ResolvedConcept:
    iri: str
    label: str
    branch_iri: str
    branch_label: str
    ancestor_path: tuple[str, ...]


class PinnedOntology:
    def __init__(self, snapshot: OntologySnapshot) -> None:
        self.source_sha256 = snapshot.source_sha256
        self.slice_sha256 = snapshot.concepts_sha256
        self.concepts = {c.iri: c for c in snapshot.concepts}
        if len(self.concepts) != len(snapshot.concepts):
            raise GoldSetError("duplicate ontology concept IRI")
        self._labels: dict[str, set[str]] = {}
        self._preferred: dict[str, set[str]] = {}
        for concept in snapshot.concepts:
            self._preferred.setdefault(concept.label.casefold(), set()).add(concept.iri)
            for label in (concept.label, *concept.alternative_labels):
                self._labels.setdefault(label.casefold(), set()).add(concept.iri)
            if any(parent not in self.concepts for parent in concept.parents):
                raise GoldSetError(f"ontology ancestor closure missing for {concept.iri}")

    def _identity(self, label: str) -> str:
        matches = (self._preferred.get(label.casefold())
                   or self._labels.get(label.casefold(), set()))
        if not matches:
            raise GoldSetError(f"unknown ontology label: {label}")
        if len(matches) != 1:
            raise GoldSetError(f"ambiguous ontology label: {label}")
        return next(iter(matches))

    def resolve(self, label: str, branch: str) -> ResolvedConcept:
        iri, branch_iri = self._identity(label), self._identity(branch)
        queue = deque([(iri,)])
        visited = {iri}
        while queue:
            path = queue.popleft()
            if path[-1] == branch_iri:
                return ResolvedConcept(iri, self.concepts[iri].label, branch_iri,
                                       self.concepts[branch_iri].label, path)
            for parent in sorted(self.concepts[path[-1]].parents):
                if parent not in visited:
                    visited.add(parent)
                    queue.append((*path, parent))
        raise GoldSetError(f"{branch} is not an ontology ancestor of {label}")


def load_ontology(path: Path | None = None) -> PinnedOntology:
    data = _load_json(path or repo_root() / DEFAULT_GOLD_DIR / "ontology.json")
    try:
        snapshot = OntologySnapshot.model_validate(data)
    except ValidationError as exc:
        raise GoldSetError(f"invalid ontology snapshot: {exc}") from exc
    if concepts_digest(data["concepts"]) != snapshot.concepts_sha256:
        raise GoldSetError("ontology slice digest does not match recorded concepts")
    return PinnedOntology(snapshot)


def validate_gold(suite: GoldSuite, ontology: PinnedOntology) -> None:
    if (suite.ontology_sha256 != ontology.source_sha256
            or suite.ontology_slice_sha256 != ontology.slice_sha256):
        raise GoldSetError("gold ontology digest does not match pinned ontology")
    for doc in suite.documents:
        for prop in doc.propositions:
            for tag in prop.tags:
                ontology.resolve(tag.label, tag.branch)


def load_gold(path: Path | None = None, *, ontology: PinnedOntology | None = None) -> GoldSuite:
    path = path or repo_root() / DEFAULT_GOLD_DIR / "readme.json"
    try:
        suite = GoldSuite.model_validate(_load_json(path))
    except ValidationError as exc:
        raise GoldSetError(f"invalid gold fixture {path}: {exc}") from exc
    validate_gold(suite, ontology or load_ontology())
    return suite

"""The Phase 11 SHACL suite: which files, its digest, and one-call validation.

Suite (plan KTD1):

* the six hand-written shapes, ``ttl/{envelope,subtypes,governance,
  supersession,distinguo,signatures}.shacl.ttl``;
* the Pydantic-generated shapes, ``generated/shard_models.shacl.ttl``;
* the Phase 8 vocab shapes, ``vocab/shapes.ttl`` (the vocab pin, the
  SignedAction, role and distinction-kind enumerations, and supersession
  valid-time alignment).

The governance-event shapes (``governance/shapes``), the content-edit chain
shape (``revision``) and the v1 OWL-export shapes keep their existing owners
and runners. They validate different graphs.

``suite_digest()`` (sha256 over the file names and bytes, in sorted order)
versions every recorded validation result: a changed shape makes earlier
results ``unvalidated`` rather than silently still "pass".
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from folio_insights.shapes.compiled import CompiledSuite, ShaclResult
from folio_insights.shapes.pydantic_to_shacl import GENERATED_PATH
from folio_insights.shapes.rendering import Term, ValidationGraph, render_shard

_HERE = Path(__file__).parent
HAND_WRITTEN = ("envelope", "subtypes", "governance", "supersession", "distinguo", "signatures")
HAND_WRITTEN_PATHS: tuple[Path, ...] = tuple(_HERE / "ttl" / f"{name}.shacl.ttl" for name in HAND_WRITTEN)
VOCAB_SHAPES_PATH = Path(str(files("folio_insights.vocab").joinpath("shapes.ttl")))
SUITE_PATHS: tuple[Path, ...] = (*HAND_WRITTEN_PATHS, GENERATED_PATH, VOCAB_SHAPES_PATH)


def suite_digest(paths: Iterable[Path] = SUITE_PATHS) -> str:
    h = hashlib.sha256()
    for path in sorted(Path(p) for p in paths):
        h.update(path.name.encode("utf-8") + b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


@dataclass(frozen=True)
class Report:
    """Local-tier result for one rendered record."""

    results: tuple[ShaclResult, ...]

    @property
    def violations(self) -> tuple[ShaclResult, ...]:
        return tuple(r for r in self.results if r.severity == "Violation")

    @property
    def warnings(self) -> tuple[ShaclResult, ...]:
        return tuple(r for r in self.results if r.severity != "Violation")

    @property
    def conforms(self) -> bool:
        return not self.violations


class ShaclSuite:
    """The compiled suite plus its identity. Build once per process."""

    def __init__(self, paths: Iterable[Path] = SUITE_PATHS) -> None:
        self.paths = tuple(Path(p) for p in paths)
        self.digest = suite_digest(self.paths)
        self.compiled = CompiledSuite(self.paths)

    @property
    def sparql(self):  # noqa: ANN201 - list[SparqlConstraint]
        return self.compiled.sparql

    def validate_graph(self, g: ValidationGraph, *, focus: Iterable[Term] | None = None) -> Report:
        return Report(tuple(self.compiled.validate(g, focus=focus)))

    def validate_shard(self, data: Mapping[str, Any] | BaseModel) -> Report:
        """Local tier for one shard (JSON mapping or model)."""
        g, _node = render_shard(data)
        return self.validate_graph(g)


@cache
def default_suite() -> ShaclSuite:
    """The process-wide compiled default suite (compiled on first use)."""
    return ShaclSuite()


__all__ = [
    "HAND_WRITTEN",
    "HAND_WRITTEN_PATHS",
    "SUITE_PATHS",
    "VOCAB_SHAPES_PATH",
    "Report",
    "ShaclSuite",
    "default_suite",
    "suite_digest",
]

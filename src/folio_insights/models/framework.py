"""First-class frameworks (Phase 9 U2, PRD §8 P2, KTD12).

A ``Framework`` is a registered, resolvable entity — ``id``, ``label``,
``jurisdiction`` and an optional ``parent`` — with NO time scope: frameworks
are not versioned by year (PRD decision #1); valid time lives on the shard.
Identifiers follow ``<jurisdiction>.<body>[.<sub>]`` (lowercase snake-case
segments, each starting with a letter), so a year suffix such as
``us.federal.frcp.2024`` is not a valid ID; ``migrate_v1_framework_id`` is the
pure v1 migration that strips it and says so.

``FrameworkRegistry`` is the in-memory CRUD + resolution surface with a SKOS
concept-scheme export. Per-corpus persistence and the signed admin
registration live in ``folio_insights.frameworks.registry``; the starter set
is the single data file ``frameworks/default_frameworks.json``.

Pure Pydantic + stdlib (the SKOS export imports pyoxigraph lazily).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from folio_insights.vocab._constants import FI_PREFIX, FRAMEWORK_NS, framework_iri

# ``<jurisdiction>.<body>[.<sub>...]``: 2-5 dot-separated segments.
FRAMEWORK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,4}$")
_YEAR_SUFFIX = re.compile(r"^(?P<base>.+?)(?:[._-](?P<year>1[6-9]\d\d|20\d\d|21\d\d))+$")

SKOS = "http://www.w3.org/2004/02/skos/core#"
# Outside the framework namespace, so no framework ID can mint the scheme IRI.
FRAMEWORK_SCHEME_IRI = "https://folio-insights.aleainstitute.ai/framework-scheme"


class MalformedFrameworkId(ValueError):
    """A framework ID does not match ``<jurisdiction>.<body>[.<sub>]``."""


class UnregisteredFramework(KeyError):
    """A framework ID is well-formed but not in the registry."""

    def __str__(self) -> str:  # KeyError quotes its argument; keep the message plain
        return str(self.args[0]) if self.args else "unregistered framework"


def check_framework_id(framework_id: object) -> str:
    """Return ``framework_id`` if it matches the ID pattern, else raise."""
    # fullmatch: ``$`` would also accept a trailing newline (review P2-2).
    if not isinstance(framework_id, str) or not FRAMEWORK_ID_PATTERN.fullmatch(framework_id):
        raise MalformedFrameworkId(
            f"framework id {framework_id!r} does not match <jurisdiction>.<body>[.<sub>] "
            "(lowercase snake-case segments, each starting with a letter; no year suffix)"
        )
    return framework_id


class Framework(BaseModel):
    """A linguistic/conceptual framework (Carnap). No time-scope field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str = Field(min_length=1)
    jurisdiction: str
    parent: str | None = None

    @field_validator("id", "parent")
    @classmethod
    def _pattern(cls, value: str | None) -> str | None:
        return None if value is None else check_framework_id(value)

    @field_validator("jurisdiction")
    @classmethod
    def _jurisdiction(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", value):
            raise ValueError(f"jurisdiction {value!r} must be dotted lowercase segments")
        return value

    @model_validator(mode="after")
    def _shape(self) -> Framework:
        if not self.id.startswith(self.jurisdiction + "."):
            raise ValueError(
                f"framework id {self.id!r} must start with its jurisdiction "
                f"{self.jurisdiction!r} followed by the body"
            )
        if self.parent == self.id:
            raise ValueError("a framework cannot be its own parent")
        return self

    @property
    def iri(self) -> str:
        return framework_iri(self.id)


@dataclass(frozen=True)
class V1FrameworkMigration:
    """Result of migrating a v1-style framework ID: the v2 ID and warnings."""

    framework_id: str
    original: str
    warnings: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.framework_id != self.original


def migrate_v1_framework_id(raw: str) -> V1FrameworkMigration:
    """Pure v1 -> v2 framework ID migration (PRD §8 P2; Phase 10's minter calls it).

    Lowercases, strips surrounding whitespace and removes any trailing year
    suffix (``us.federal.frcp.2024`` -> ``us.federal.frcp``), returning a
    warning for every change. Raises ``MalformedFrameworkId`` when the result
    is still not a valid ID: the migration never guesses one.
    """
    original = raw
    warnings: list[str] = []
    value = raw.strip()
    if value != value.lower():
        value = value.lower()
        warnings.append(f"framework id {original!r} lowercased")
    match = _YEAR_SUFFIX.match(value)
    if match:
        warnings.append(
            f"framework id {original!r}: year suffix stripped (frameworks are not "
            "versioned by year; the time window belongs on the shard's valid_time)"
        )
        value = match.group("base")
    check_framework_id(value)
    if value != original and not warnings:
        warnings.append(f"framework id {original!r} normalized to {value!r}")
    return V1FrameworkMigration(value, original, tuple(warnings))


def default_frameworks() -> list[Framework]:
    """The starter set every corpus registry ships with.

    PROVISIONAL (Decision Sheet folio-insights-2026-10-05-0814-p9-build-and-calls,
    q3 open): the one data file ``frameworks/default_frameworks.json`` holds it.
    """
    data = json.loads(
        (files("folio_insights.frameworks") / "default_frameworks.json").read_text("utf-8")
    )
    return [Framework.model_validate(item) for item in data["frameworks"]]


class FrameworkRegistry:
    """In-memory framework registry: CRUD, resolution, SKOS export."""

    def __init__(self, frameworks: Iterable[Framework] = ()) -> None:
        self._by_id: dict[str, Framework] = {}
        for framework in frameworks:
            self.register(framework)

    @classmethod
    def with_defaults(cls, extra: Iterable[Framework] = ()) -> FrameworkRegistry:
        return cls([*default_frameworks(), *extra])

    def register(self, framework: Framework) -> Framework:
        """Add ``framework``. Re-registering the identical definition is a
        no-op; a different definition under a known ID, or an unknown parent,
        raises ``ValueError``."""
        existing = self._by_id.get(framework.id)
        if existing is not None:
            if existing != framework:
                raise ValueError(
                    f"framework {framework.id!r} is already registered with a different definition"
                )
            return existing
        if framework.parent is not None and framework.parent not in self._by_id:
            raise ValueError(
                f"framework {framework.id!r} names unregistered parent {framework.parent!r}"
            )
        self._by_id[framework.id] = framework
        return framework

    def get(self, framework_id: str) -> Framework | None:
        return self._by_id.get(framework_id)

    def resolve(self, framework_id: str) -> Framework:
        """The registered framework, or ``MalformedFrameworkId`` /
        ``UnregisteredFramework``."""
        check_framework_id(framework_id)
        try:
            return self._by_id[framework_id]
        except KeyError:
            raise UnregisteredFramework(
                f"framework {framework_id!r} is not registered in this corpus"
            ) from None

    def __contains__(self, framework_id: object) -> bool:
        return framework_id in self._by_id

    def __iter__(self) -> Iterator[Framework]:
        return iter(self.frameworks())

    def __len__(self) -> int:
        return len(self._by_id)

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def frameworks(self) -> list[Framework]:
        return [self._by_id[i] for i in sorted(self._by_id)]

    def copy(self) -> FrameworkRegistry:
        clone = FrameworkRegistry()
        clone._by_id = dict(self._by_id)
        return clone

    # ── SKOS concept scheme export ───────────────────────────────────────

    def to_skos_triples(self) -> list[tuple[str, str, object]]:
        """``(subject, predicate, object)`` with IRIs as ``str`` and literal
        values as ``("literal", text)`` tuples."""
        rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        out: list[tuple[str, str, object]] = [
            (FRAMEWORK_SCHEME_IRI, rdf_type, f"{SKOS}ConceptScheme"),
            (FRAMEWORK_SCHEME_IRI, f"{SKOS}prefLabel", ("literal", "FOLIO Insights frameworks")),
        ]
        for fw in self.frameworks():
            out += [
                (fw.iri, rdf_type, f"{SKOS}Concept"),
                (fw.iri, rdf_type, f"{FI_PREFIX}Framework"),
                (fw.iri, f"{SKOS}inScheme", FRAMEWORK_SCHEME_IRI),
                (fw.iri, f"{SKOS}prefLabel", ("literal", fw.label)),
                (fw.iri, f"{SKOS}notation", ("literal", fw.id)),
                (fw.iri, f"{FI_PREFIX}frameworkId", ("literal", fw.id)),
                (fw.iri, f"{FI_PREFIX}jurisdiction", ("literal", fw.jurisdiction)),
            ]
            if fw.parent is None:
                out.append((FRAMEWORK_SCHEME_IRI, f"{SKOS}hasTopConcept", fw.iri))
                out.append((fw.iri, f"{SKOS}topConceptOf", FRAMEWORK_SCHEME_IRI))
            else:
                out.append((fw.iri, f"{SKOS}broader", framework_iri(fw.parent)))
        return out

    def to_skos_turtle(self) -> str:
        """The registry as a SKOS concept scheme in Turtle."""
        from pyoxigraph import Literal, NamedNode, RdfFormat, Triple, serialize

        triples = [
            Triple(
                NamedNode(s),
                NamedNode(p),
                Literal(o[1]) if isinstance(o, tuple) else NamedNode(o),  # type: ignore[index]
            )
            for s, p, o in self.to_skos_triples()
        ]
        return serialize(
            triples,
            format=RdfFormat.TURTLE,
            prefixes={"skos": SKOS, "fi": FI_PREFIX, "framework": FRAMEWORK_NS},
        ).decode("utf-8")


__all__ = [
    "FRAMEWORK_ID_PATTERN",
    "FRAMEWORK_SCHEME_IRI",
    "Framework",
    "FrameworkRegistry",
    "MalformedFrameworkId",
    "UnregisteredFramework",
    "V1FrameworkMigration",
    "check_framework_id",
    "default_frameworks",
    "migrate_v1_framework_id",
]

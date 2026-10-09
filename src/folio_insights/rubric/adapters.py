"""Rubric adapters: one normalized view over the two artifact kinds the harness scores.

The criteria in ``criteria.py`` are pure functions. They never open files or storage;
they read a ``RubricArtifact``, which an adapter builds once:

* ``UnitRun`` (v1): an ``extraction.json`` written by ``folio-insights extract``
  (``quality.output_formatter``: ``{"units": [KnowledgeUnit, ...], ...}``) plus an
  optional directory of source texts for the anchor checks. A unit's source is
  ``original_span.source_file`` (else ``source_file``), looked up inside that
  directory: first as a relative path, then by file name. Lookups are confined to the
  directory; a path that escapes it is treated as unresolvable. The texts must be the
  *ingested* plain text the pipeline anchored against (for ``.md`` / ``.txt`` sources
  that is the file itself).
* ``ShardCorpus`` (v2): a corpus in persistent storage, opened read-mostly through
  ``CorpusStorageContext``. Each current shard becomes one unit whose claimed anchor is
  its ``source_span`` (the verbatim source slice, plan KTD1). Its source text is
  resolved from ``source_uri``: a ``file:`` URI is read directly (inside
  ``sources_dir`` when one is given), any URI is also tried as a file name inside
  ``sources_dir``. Loading also runs the corpus's full SHACL validation
  (``validate_corpus``, which records its result in the corpus's SHACL status marker,
  the designed place for it) and the export structural checks, so RUB-EXTRACT-10/-11
  have their evidence without the criteria touching storage.

Nothing here scores anything; an adapter only records what the artifact claims and what
could be resolved, including *why* something could not be.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from folio_insights.rubric.oracle import FOLIO_IRI_PREFIX

ArtifactKind = Literal["unit_run", "shard_corpus"]

SHARD_IRI_PREFIX = "urn:folio:shard/"


class AdapterError(ValueError):
    """The artifact cannot be read (missing file, malformed JSON, unknown corpus)."""


@dataclass(frozen=True)
class TagRef:
    """One FOLIO concept reference carried by a unit."""

    iri: str
    label: str = ""
    branch: str = ""  # the branch the tag claims ("" when it claims none)
    extraction_path: str = ""


@dataclass(frozen=True)
class AnchorClaim:
    """What a unit claims about its source passage, plus the resolved source text.

    ``span`` is the claimed character span (v1 units only). ``snippet`` is the claimed
    exact source quote ("" when the unit carries none). ``text_as_quote`` is the
    unit's own text, used as a fallback quote for extractive v1 units that predate the
    snippet field. ``stored_score`` / ``stored_verified`` are the pipeline's recorded
    anchor result (``None`` when the artifact has none). ``source_text`` is ``None``
    when the source could not be resolved; ``source_error`` then says why.
    """

    source_key: str
    source_text: str | None
    source_error: str = ""
    span: tuple[int, int] | None = None
    snippet: str = ""
    text_as_quote: str = ""
    stored_score: float | None = None
    stored_verified: bool | None = None


@dataclass(frozen=True)
class RubricUnit:
    """One judged unit: a v1 KnowledgeUnit or a v2 shard."""

    id: str
    text: str
    chapter: str
    content_hash: str
    tags: tuple[TagRef, ...]
    anchor: AnchorClaim


@dataclass(frozen=True)
class StructuralCheck:
    """One export structural check (``services.shacl_validator.CheckResult`` shape)."""

    name: str
    status: str  # "PASS" | "WARN" | "FAIL"
    details: str
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShaclEvidence:
    """The corpus's full SHACL validation result (RUB-EXTRACT-10)."""

    conforms: bool
    violations: int
    warnings: int
    suite_digest: str
    shards: int
    events: int
    results: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RubricArtifact:
    """Everything the criteria may read."""

    kind: ArtifactKind
    ref: str
    units: tuple[RubricUnit, ...]
    sources_dir: str | None = None
    shacl: ShaclEvidence | None = None
    structural: tuple[StructuralCheck, ...] | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_sources(self) -> bool:
        return self.sources_dir is not None


# ── source resolution ─────────────────────────────────────────────────────


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


class SourceResolver:
    """Find and cache source texts inside one directory (or ``file:`` URIs)."""

    def __init__(self, sources_dir: str | Path | None) -> None:
        self.root = Path(sources_dir) if sources_dir is not None else None
        self._cache: dict[str, tuple[str | None, str]] = {}

    def _candidates(self, key: str) -> list[Path]:
        out: list[Path] = []
        if self.root is None:
            return out
        raw = Path(key)
        if not raw.is_absolute():
            out.append(self.root / raw)
        if raw.name:
            out.append(self.root / raw.name)
        return out

    def resolve_path(self, key: str) -> tuple[str | None, str]:
        """``(text, "")`` or ``(None, reason)`` for a v1 ``source_file`` value."""
        if key in self._cache:
            return self._cache[key]
        result: tuple[str | None, str]
        if self.root is None:
            result = (None, "no_sources_dir")
        elif not key:
            result = (None, "no_source_file")
        else:
            result = (None, "source_not_found")
            for candidate in self._candidates(key):
                if not _inside(candidate, self.root):
                    result = (None, "source_outside_sources_dir")
                    continue
                if candidate.is_file():
                    try:
                        result = (_read_text(candidate), "")
                    except (OSError, UnicodeDecodeError):
                        result = (None, "source_unreadable")
                    break
        self._cache[key] = result
        return result

    def resolve_uri(self, uri: str) -> tuple[str | None, str]:
        """``(text, "")`` or ``(None, reason)`` for a v2 ``source_uri``."""
        cache_key = f"uri:{uri}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        self._cache[cache_key] = result = self._resolve_uri(uri)
        return result

    def _resolve_uri(self, uri: str) -> tuple[str | None, str]:
        parts = urlsplit(uri)
        if parts.scheme == "file":
            path = Path(unquote(parts.path))
            if self.root is not None and not _inside(path, self.root):
                return None, "source_outside_sources_dir"
            if path.is_file():
                try:
                    return _read_text(path), ""
                except (OSError, UnicodeDecodeError):
                    return None, "source_unreadable"
            if self.root is None:
                return None, "source_not_found"
        elif self.root is None:
            return None, "no_sources_dir"
        # Any URI: its path (or opaque part, after the last ':') as a file in the directory.
        tail = unquote(parts.path or uri).lstrip("/").rsplit(":", 1)[-1]
        return self.resolve_path(tail) if tail else (None, "source_unresolvable")


# ── v1: UnitRun ───────────────────────────────────────────────────────────


def _unit_tags(raw_tags: Iterable[Any]) -> tuple[TagRef, ...]:
    tags: list[TagRef] = []
    for tag in raw_tags:
        tags.append(TagRef(
            iri=str(getattr(tag, "iri", "") or ""),
            label=str(getattr(tag, "label", "") or ""),
            branch=str(getattr(tag, "branch", "") or ""),
            extraction_path=str(getattr(tag, "extraction_path", "") or ""),
        ))
    return tuple(tags)


class UnitRun:
    """Adapter for a v1 ``extraction.json`` (and its source directory)."""

    @staticmethod
    def load(run: str | Path, sources_dir: str | Path | None = None) -> RubricArtifact:
        from pydantic import ValidationError

        from folio_insights.models.knowledge_unit import KnowledgeUnit

        path = Path(run)
        if path.is_dir():
            path = path / "extraction.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AdapterError(f"extraction file not found: {path}") from exc
        except ValueError as exc:
            raise AdapterError(f"extraction file is not valid JSON: {path}: {exc}") from exc
        raw_units = data.get("units") if isinstance(data, dict) else None
        if not isinstance(raw_units, list):
            raise AdapterError(f"{path}: expected an object with a 'units' list")
        if sources_dir is not None and not Path(sources_dir).is_dir():
            raise AdapterError(f"sources directory not found: {sources_dir}")

        resolver = SourceResolver(sources_dir)
        units: list[RubricUnit] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(raw_units):
            try:
                ku = KnowledgeUnit.model_validate(raw)
            except ValidationError as exc:
                raise AdapterError(f"{path}: unit {index} is not a KnowledgeUnit: {exc}") from exc
            if ku.id in seen_ids:
                raise AdapterError(f"{path}: duplicate unit id {ku.id!r}")
            seen_ids.add(ku.id)
            key = ku.original_span.source_file or ku.source_file
            text, error = resolver.resolve_path(key)
            has_stored = "anchor_score" in raw or "anchor_verified" in raw
            units.append(RubricUnit(
                id=ku.id,
                text=ku.text,
                chapter=ku.source_file or key,
                content_hash=ku.content_hash or hashlib.sha256(ku.text.encode("utf-8")).hexdigest(),
                tags=_unit_tags(ku.folio_tags),
                anchor=AnchorClaim(
                    source_key=key,
                    source_text=text,
                    source_error=error,
                    span=(ku.original_span.start, ku.original_span.end),
                    snippet=ku.source_snippet,
                    text_as_quote=ku.text,
                    stored_score=ku.anchor_score if has_stored else None,
                    stored_verified=ku.anchor_verified if has_stored else None,
                ),
            ))
        return RubricArtifact(
            kind="unit_run",
            ref=str(path),
            units=tuple(units),
            sources_dir=str(sources_dir) if sources_dir is not None else None,
        )


# ── v2: ShardCorpus ───────────────────────────────────────────────────────


def _folio_iris(values: Iterable[str]) -> tuple[TagRef, ...]:
    seen: list[str] = []
    for value in values:
        if isinstance(value, str) and value.startswith(FOLIO_IRI_PREFIX) and value not in seen:
            seen.append(value)
    return tuple(TagRef(iri=iri, extraction_path="shard") for iri in seen)


def shard_unit(shard: Any, resolver: SourceResolver) -> RubricUnit:
    """A shard as a rubric unit (no I/O beyond reading its source text)."""
    from folio_insights.revision.content_edit import canonical_content_hash

    text, error = resolver.resolve_uri(shard.source_uri)
    return RubricUnit(
        id=shard.shard_iri,
        text=shard.sense,
        chapter=shard.source_uri,
        content_hash=canonical_content_hash(shard),
        tags=_folio_iris(
            [shard.reference, shard.triple.subject, shard.triple.predicate, shard.triple.object]
        ),
        anchor=AnchorClaim(
            source_key=shard.source_uri,
            source_text=text,
            source_error=error,
            snippet=shard.source_span,
        ),
    )


def _edge_targets(shard: Any) -> list[str]:
    targets: list[str] = list(shard.elaborates)
    for name in ("depends_on_axioms", "depends_on_definitions",
                 "depends_on_precedents", "depends_on_shards"):
        targets.extend(getattr(shard, name))
    for name in ("supersedes", "superseded_by"):
        value = getattr(shard, name)
        if value:
            targets.append(value)
    return targets


def structural_checks(quads: Sequence[Any], shards: Sequence[Any]) -> tuple[StructuralCheck, ...]:
    """The export report's three structural checks over a shard corpus's dataset.

    Reuses ``services.shacl_validator.SHACLValidator`` (the v1 ``export --validate``
    checks) on an in-memory rdflib adapter graph of the exported quads, and adds the v2
    analogues the v1 checks cannot see:

    * **IRI Uniqueness:** no IRI is both ``owl:Class`` and ``owl:NamedIndividual``
      (v1 check), and no shard IRI carries more than one ``fi:contentHash`` or
      ``fi:shardType`` (two records collapsed onto one IRI).
    * **Referential Integrity:** the v1 dangling-reference check, plus every
      ``urn:folio:shard/`` target of a shard's ``elaborates``, ``depends_on_*``,
      ``supersedes`` or ``superseded_by`` is a current shard of the corpus.
    * **Namespace Consistency:** the v1 check for auto-generated prefixes, after binding
      the export's declared prefixes (``storage.exports.PREFIXES``).
    """
    import rdflib
    from pyoxigraph import RdfFormat, serialize

    from folio_insights.services.shacl_validator import SHACLValidator
    from folio_insights.storage.exports import PREFIXES, as_default_graph
    from folio_insights.storage.projection import fi

    data = serialize(as_default_graph(quads), format=RdfFormat.N_TRIPLES) or b""
    graph = rdflib.Graph()
    graph.parse(data=data.decode("utf-8"), format="nt")
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, rdflib.Namespace(namespace), override=True)
    validator = SHACLValidator()

    uniqueness = list(validator.check_iri_uniqueness(graph))
    for predicate in ("contentHash", "shardType"):
        counts: dict[str, int] = {}
        for subject, _p, _o in graph.triples((None, rdflib.URIRef(fi(predicate).value), None)):
            counts[str(subject)] = counts.get(str(subject), 0) + 1
        uniqueness.extend(
            f"Shard IRI carries {n} fi:{predicate} values: {iri}"
            for iri, n in sorted(counts.items()) if n > 1
        )

    current = {s.shard_iri for s in shards}
    dangling = list(validator.check_referential_integrity(graph))
    for s in shards:
        for target in _edge_targets(s):
            if target.startswith(SHARD_IRI_PREFIX) and target not in current:
                dangling.append(f"Dangling shard reference: {s.shard_iri} -> {target}")

    namespaces = list(validator.check_namespace_consistency(graph))

    def check(name: str, messages: list[str], fail_status: str, ok: str, bad: str) -> StructuralCheck:
        return StructuralCheck(
            name=name,
            status="PASS" if not messages else fail_status,
            details=ok if not messages else f"{len(messages)} {bad}",
            messages=tuple(messages),
        )

    return (
        check("IRI Uniqueness", uniqueness, "FAIL", "No duplicates", "duplicates"),
        check("Referential Integrity", dangling, "FAIL", "No dangling references", "dangling"),
        # The v1 report rates auto-generated prefixes a warning, never a failure.
        check("Namespace Consistency", namespaces, "WARN", "All namespaces bound",
              "auto-generated prefixes"),
    )


class ShardCorpus:
    """Adapter for a v2 shard corpus in persistent storage."""

    @staticmethod
    async def load(
        root: str | Path,
        corpus: str,
        sources_dir: str | Path | None = None,
    ) -> RubricArtifact:
        """Read every current shard, validate the corpus, run the structural checks.

        Never creates a corpus: an unknown corpus raises ``AdapterError``.
        """
        from folio_insights.storage import CorpusStorageContext
        from folio_insights.storage.exports import build_export_dataset
        from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

        root = Path(root)
        if corpus not in committed_corpora(root / JOURNAL_FILENAME):
            raise AdapterError(f"no corpus {corpus!r} under {root}")
        if sources_dir is not None and not Path(sources_dir).is_dir():
            raise AdapterError(f"sources directory not found: {sources_dir}")

        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            shards = [s async for s in ctx.shards.iter_shards()]
            validation = await ctx.validate_corpus()
            dataset = await build_export_dataset(ctx, include_tbox=True)
        finally:
            await ctx.close()

        resolver = SourceResolver(sources_dir)
        units = tuple(shard_unit(s, resolver) for s in sorted(shards, key=lambda s: s.shard_iri))
        return RubricArtifact(
            kind="shard_corpus",
            ref=f"{root}#{corpus}",
            units=units,
            sources_dir=str(sources_dir) if sources_dir is not None else None,
            shacl=ShaclEvidence(
                conforms=validation.conforms,
                violations=validation.violations,
                warnings=validation.warnings,
                suite_digest=validation.suite_digest,
                shards=validation.shards,
                events=validation.events,
                results=validation.results,
            ),
            structural=structural_checks(dataset.quads(), shards),
        )


__all__ = [
    "SHARD_IRI_PREFIX",
    "AdapterError",
    "AnchorClaim",
    "ArtifactKind",
    "RubricArtifact",
    "RubricUnit",
    "ShaclEvidence",
    "ShardCorpus",
    "SourceResolver",
    "StructuralCheck",
    "TagRef",
    "UnitRun",
    "shard_unit",
    "structural_checks",
]

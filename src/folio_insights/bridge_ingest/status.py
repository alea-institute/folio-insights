"""Corpus status for a batch of shard IRIs (the bridge read contract).

Sources, per field of ``StatusResult``:

* ``present``, ``shard_type``, ``epistemic_status``, ``contested``,
  ``supersedes``, ``superseded_by`` — the Oxigraph projection
  (``fi:shardType``, ``fi:epistemicStatus``, ``fi:contested``,
  ``fi:supersedes``, ``fi:supersededBy``), one batched SPARQL query with a
  ``VALUES`` clause.
* ``related`` ``depends_on`` / ``depended_on_by`` — the projection's four
  ``fi:dependsOn*`` predicates (the same edges ``shards.dependents_of``
  reads), both directions, batched.
* ``contesting`` ``superseded_by`` — the shard's own ``fi:supersededBy`` plus
  any shard that ``fi:supersedes`` it; ``contests`` — governance contest
  events (``fi:action "contest"``, ``fi:shardIri``) in the governance graph.
* ``related`` ``elaborates`` / ``elaborated_by`` / ``glosses`` /
  ``glossed_by`` and ``contesting`` ``conflicting_authority`` (a
  ``ConflictingAuthoritiesShard`` whose ``sic``/``non`` cites the IRI) and
  ``objection`` (a ``DisputedPropositionShard`` whose objections or sed
  contra cite it) — NOT projected (``storage/projection.py`` writes no
  triples for ``elaborates``, ``glosses``, ``sic``/``non`` or
  ``objections``), so they come from the shard records: one pass over
  ``ctx.shards.iter_shards()`` per journal head, cached per
  ``(storage root, corpus, journal head)``.
* ``enrich_sources`` — the bridge-ingest provenance manifest, read in a worker
  thread without taking the manifest lock.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from folio_insights.bridge_ingest.manifest import read_manifest_async
from folio_insights.storage.projection import DEPENDENCY_PREDICATES, corpus_graph, governance_graph
from folio_insights.vocab._constants import FI_PREFIX

SHARD_IRI_RE = re.compile(r"^urn:folio:shard/[0-9a-f]{32}$")
MAX_STATUS_IRIS = 500

RelatedRelation = Literal[
    "elaborates", "elaborated_by", "depends_on", "depended_on_by", "glosses", "glossed_by",
]
ContestingRelation = Literal["contests", "conflicting_authority", "superseded_by", "objection"]


class RelatedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iri: str
    relation: RelatedRelation


class ContestingRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iri: str
    relation: ContestingRelation


class EnrichSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    proposition_id: str
    proposition_type: str


class StatusResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iri: str
    present: bool
    shard_type: str | None = None
    epistemic_status: str | None = None
    contested: bool | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    related: list[RelatedRef] = Field(default_factory=list)
    contesting: list[ContestingRef] = Field(default_factory=list)
    enrich_sources: list[EnrichSource] = Field(default_factory=list)


def _v(term: Any) -> str | None:
    return None if term is None else str(term.value)


def _values(iris: list[str]) -> str:
    return " ".join(f"<{iri}>" for iri in iris)


def _core_query(iris: list[str], abox: str) -> str:
    return (
        f"PREFIX fi: <{FI_PREFIX}>\n"
        "SELECT ?s ?type ?status ?contested ?supersedes ?supersededBy WHERE {\n"
        f"  VALUES ?s {{ {_values(iris)} }}\n"
        f"  GRAPH {abox} {{\n"
        "    ?s fi:shardType ?type .\n"
        "    OPTIONAL { ?s fi:epistemicStatus ?status }\n"
        "    OPTIONAL { ?s fi:contested ?contested }\n"
        "    OPTIONAL { ?s fi:supersedes ?supersedes }\n"
        "    OPTIONAL { ?s fi:supersededBy ?supersededBy }\n"
        "  }\n}"
    )


def _edge_query(iris: list[str], abox: str, gov: str) -> str:
    deps = " ".join(f"fi:{p}" for p in DEPENDENCY_PREDICATES.values())
    return (
        f"PREFIX fi: <{FI_PREFIX}>\n"
        "SELECT ?s ?rel ?o WHERE {\n"
        f"  VALUES ?s {{ {_values(iris)} }}\n"
        "  {\n"
        f"    GRAPH {abox} {{ VALUES ?p {{ {deps} }} ?s ?p ?o }}\n"
        '    BIND("depends_on" AS ?rel)\n'
        "  } UNION {\n"
        f"    GRAPH {abox} {{ VALUES ?p {{ {deps} }} ?o ?p ?s }}\n"
        '    BIND("depended_on_by" AS ?rel)\n'
        "  } UNION {\n"
        f"    GRAPH {abox} {{ ?o fi:supersedes ?s }}\n"
        '    BIND("superseded_by" AS ?rel)\n'
        "  } UNION {\n"
        f'    GRAPH {gov} {{ ?o fi:action "contest" ; fi:shardIri ?s }}\n'
        '    BIND("contests" AS ?rel)\n'
        "  }\n}"
    )


# (root, corpus) -> (journal head, forward, inverse); a few corpora at most.
_RECORD_INDEX: OrderedDict[tuple[str, str], tuple[int, dict, dict]] = OrderedDict()
_RECORD_INDEX_MAX = 8


def _cache_put(cache: OrderedDict, key: Any, value: Any) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _RECORD_INDEX_MAX:
        cache.popitem(last=False)


async def _record_index(ctx: Any) -> tuple[dict[str, set[tuple[str, str]]], dict[str, set[tuple[str, str]]]]:
    """``(forward, inverse)``: iri -> {(other iri, relation)} from shard records."""
    key = (str(Path(ctx.root).resolve()), ctx.corpus)
    head = await ctx.journal_head()
    cached = _RECORD_INDEX.get(key)
    if cached is not None and cached[0] == head:
        return cached[1], cached[2]
    forward: dict[str, set[tuple[str, str]]] = {}
    inverse: dict[str, set[tuple[str, str]]] = {}
    async for shard in ctx.shards.iter_shards():
        iri = shard.shard_iri
        for target in shard.elaborates:
            forward.setdefault(iri, set()).add((target, "elaborates"))
            inverse.setdefault(target, set()).add((iri, "elaborated_by"))
        glosses = getattr(shard, "glosses", None)
        if isinstance(glosses, str):
            forward.setdefault(iri, set()).add((glosses, "glosses"))
            inverse.setdefault(glosses, set()).add((iri, "glossed_by"))
        for side in ("sic", "non"):
            for position in getattr(shard, side, None) or []:
                inverse.setdefault(position.authority_iri, set()).add(
                    (iri, "conflicting_authority")
                )
        objections = list(getattr(shard, "objections", None) or [])
        sed_contra = getattr(shard, "sed_contra", None)
        if sed_contra is not None:
            objections.append(sed_contra)
        for objection in objections:
            inverse.setdefault(objection.cites, set()).add((iri, "objection"))
    _cache_put(_RECORD_INDEX, key, (head, forward, inverse))
    return forward, inverse


def normalize_iris(iris: list[str]) -> list[str]:
    """Validate and dedupe (first occurrence wins, order preserved)."""
    out: list[str] = []
    seen: set[str] = set()
    for iri in iris:
        if not isinstance(iri, str) or not SHARD_IRI_RE.fullmatch(iri):
            raise ValueError(f"not a shard IRI (urn:folio:shard/<32 hex>): {iri!r}")
        if iri not in seen:
            seen.add(iri)
            out.append(iri)
    return out


async def shard_status(ctx: Any, iris: list[str]) -> list[StatusResult]:
    """Status of each IRI in ``ctx``'s corpus, in request order (deduped)."""
    wanted = normalize_iris(iris)
    if not wanted:
        return []
    abox = str(corpus_graph(ctx.corpus))
    gov = str(governance_graph(ctx.corpus))
    core = await ctx.query(_core_query(wanted, abox))
    results: dict[str, StatusResult] = {iri: StatusResult(iri=iri, present=False) for iri in wanted}
    for row in core:
        iri = _v(row["s"])
        if iri not in results:
            continue
        res = results[iri]
        res.present = True
        res.shard_type = _v(row["type"])
        res.epistemic_status = _v(row["status"])
        contested = _v(row["contested"])
        res.contested = None if contested is None else contested in {"true", "1"}
        res.supersedes = _v(row["supersedes"])
        res.superseded_by = _v(row["supersededBy"])

    present = [iri for iri in wanted if results[iri].present]
    related: dict[str, set[tuple[str, str]]] = {iri: set() for iri in present}
    contesting: dict[str, set[tuple[str, str]]] = {iri: set() for iri in present}
    if present:
        for row in await ctx.query(_edge_query(present, abox, gov)):
            iri, rel, other = _v(row["s"]), _v(row["rel"]), _v(row["o"])
            if iri not in related or other is None:
                continue
            if rel in {"depends_on", "depended_on_by"}:
                if other != iri:
                    related[iri].add((other, rel))
            else:
                contesting[iri].add((other, rel))
        forward, inverse = await _record_index(ctx)
        for iri in present:
            res = results[iri]
            if res.superseded_by:
                contesting[iri].add((res.superseded_by, "superseded_by"))
            for other, rel in forward.get(iri, ()):
                related[iri].add((other, rel))
            for other, rel in inverse.get(iri, ()):
                if other == iri:
                    continue
                if rel in {"conflicting_authority", "objection"}:
                    contesting[iri].add((other, rel))
                else:
                    related[iri].add((other, rel))
        manifest = await read_manifest_async(ctx.root, ctx.corpus)
        for iri in present:
            res = results[iri]
            res.related = [RelatedRef(iri=o, relation=r) for o, r in sorted(related[iri], key=lambda t: (t[1], t[0]))]  # type: ignore[arg-type]
            res.contesting = [ContestingRef(iri=o, relation=r) for o, r in sorted(contesting[iri], key=lambda t: (t[1], t[0]))]  # type: ignore[arg-type]
            seen: set[tuple[str, str]] = set()
            for line in manifest.get(iri, []):
                key = (str(line.get("document_id")), str(line.get("proposition_id")))
                if key in seen:
                    continue
                seen.add(key)
                res.enrich_sources.append(
                    EnrichSource(
                        document_id=key[0], proposition_id=key[1],
                        proposition_type=str(line.get("proposition_type")),
                    )
                )
    return [results[iri] for iri in wanted]


async def shard_count(ctx: Any) -> int:
    rows = await ctx.query(
        f"PREFIX fi: <{FI_PREFIX}>\n"
        f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ GRAPH {corpus_graph(ctx.corpus)} "
        "{ ?s a fi:Shard } }"
    )
    return int(rows[0]["n"].value) if rows else 0


__all__ = [
    "MAX_STATUS_IRIS",
    "SHARD_IRI_RE",
    "ContestingRef",
    "EnrichSource",
    "RelatedRef",
    "StatusResult",
    "normalize_iris",
    "shard_count",
    "shard_status",
]

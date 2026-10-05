"""Temporal framework queries over the corpus projection (Phase 9 U2, PRD §8 P2).

"What was FRE 702 at valid-time T?" — the shards linked to a framework by
``fi:framework`` (an IRI since adapter version 2) whose stored valid-time
window ``[fi:validTimeStart, fi:validTimeEnd)`` contains T. Every caller value
enters the query as a serialized RDF term (pyoxigraph), never as raw text.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from pyoxigraph import Literal, NamedNode

from folio_insights.models.framework import check_framework_id
from folio_insights.vocab._constants import FI_PREFIX, framework_iri

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext

_XSD_DT = NamedNode("http://www.w3.org/2001/XMLSchema#dateTime")


def _at(value: date | datetime) -> Literal:
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return Literal(value.isoformat(), datatype=_XSD_DT)


async def shards_in_framework_at(
    ctx: CorpusStorageContext,
    framework_id: str,
    at: date | datetime,
    *,
    reference: str | None = None,
) -> list[tuple[str, str]]:
    """``(shard IRI, sense)`` of the shards of ``framework_id`` valid at ``at``
    (optionally only those with ``reference``), ordered by IRI."""
    fw = NamedNode(framework_iri(check_framework_id(framework_id)))
    ref = f"?shard <{FI_PREFIX}reference> {Literal(reference)} ." if reference is not None else ""
    sparql = (
        f"SELECT ?shard ?sense WHERE {{ "
        f"?shard <{FI_PREFIX}framework> {fw} ; <{FI_PREFIX}sense> ?sense ; "
        f"<{FI_PREFIX}validTimeStart> ?vs . {ref} "
        f"OPTIONAL {{ ?shard <{FI_PREFIX}validTimeEnd> ?ve }} "
        f"FILTER(?vs <= {_at(at)} && (!BOUND(?ve) || {_at(at)} < ?ve)) }} ORDER BY ?shard"
    )
    rows = await ctx.query(sparql)
    return [(r["shard"].value, r["sense"].value) for r in rows]


__all__ = ["shards_in_framework_at"]

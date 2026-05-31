# Query a shard as of a past date (Phase 8 + Phase 11/12)

**Phase 8 D-10 / VOCAB-05 reference.** Per PRD §21.9, supersession ≠ retraction:
when a shard is superseded its old binding remains queryable forever. Every
shard carries `fi:validTimeStart` and (optionally) `fi:validTimeEnd` — a
half-open interval `[start, end)`. Successive shards in a supersession chain
share a boundary: when A `fi:supersedes` B, `B.fi:validTimeEnd ==
A.fi:validTimeStart`. To recover the binding of any predicate as it was on a
past date, filter on the interval that contains that date.

This document is the canonical SPARQL + Python pattern downstream phases copy
when they wire the user-facing surface. Phase 8 ships the predicates +
library helper + this template; the `--as-of <date>` CLI flag and the UI date
picker are deferred to Phase 11 (triplestore) and Phase 12 (UI) where they
have a real query surface — see "CLI / UI surface (deferred)" below.

## SPARQL pattern

Parameterized query. `?predicate` and `?at` are bound at execution time via
`initBindings` (PITFALLS Q3 / T-08-10 — never f-string-interpolated into the
query text):

```sparql
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

# initBindings supplies ?predicate (URIRef) and ?at (xsd:dateTime Literal).
# Half-open interval [validTimeStart, validTimeEnd) — t == end belongs to
# the NEXT link in the supersession chain, not the current one.
SELECT ?subject ?object WHERE {
    ?subject ?predicate ?object .
    ?subject fi:validTimeStart ?start .
    OPTIONAL { ?subject fi:validTimeEnd ?end . }
    FILTER (?start <= ?at && (!BOUND(?end) || ?at < ?end))
}
```

The chain walk is implicit: every shard carries its own
`fi:validTimeStart` / `fi:validTimeEnd`, so the FILTER selects the one whose
interval contains `?at` without a recursive Python walk. An open-ended
"current" shard (no `fi:validTimeEnd`) matches any `?at >= ?start` via the
`!BOUND(?end)` branch.

## Python helper

The Phase 8 `folio_insights.temporal.as_of.query_as_of` wraps the SPARQL
above behind a typed Python signature (rdflib only — D-10 dep-leak
discipline):

```python
from datetime import date
from rdflib import Graph, URIRef

from folio_insights.temporal.as_of import query_as_of

graph = Graph().parse("supersession_chain.ttl", format="turtle")
predicate = URIRef("https://folio-insights.aleainstitute.ai/vocab/exampleProperty")

# Binding as of mid-May 2026 — picks the link whose [start, end) contains
# 2026-05-15 (in the Plan 08-03 fixture, that's <urn:test:shard/v5>).
rows = query_as_of(graph, predicate, date(2026, 5, 15))
for subject, obj in rows:
    print(subject, obj)
# → urn:test:shard/v5 object5
```

The helper accepts a `datetime.date` (coerced to midnight UTC) or a
`datetime.datetime`. The half-open interval semantics mean `t == end`
belongs to the next link.

## CLI / UI surface (deferred)

Phase 8 ships predicates + library helper + this SPARQL template. The
`--as-of <date>` CLI flag and the UI date-picker land when their real query
surface exists:

- **Phase 11** — triplestore + CLI: `folio-insights query --as-of 2026-05-15
  <predicate>` reads the SPARQL above into the persistent pyoxigraph store.
- **Phase 12** — UI: a date-picker on the shard browser issues the same
  pattern against the SSR layer.

This deferral is recorded as Phase 8 decision D-11 (see
`.planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-CONTEXT.md`).

## SHACL guard

`fi:SupersessionAlignmentShape` (ships in
`src/folio_insights/vocab/shapes.ttl` — see the appended section) enforces
chain alignment at the storage / export boundary: when A `fi:supersedes` B,
the shape's `sh:sparql` constraint rejects the graph if `B.fi:validTimeEnd
!= A.fi:validTimeStart`. Polarity discipline: the SELECT matches the BAD
case, so a non-empty result yields `conforms=False`. The Pydantic envelope
cannot enforce cross-shard alignment (it sees one shard at a time); the
SHACL belt crosses the boundary and catches misaligned chains before they
poison the `query_as_of` result.

## See also

- `src/folio_insights/temporal/as_of.py` — the rdflib-native helper.
- `src/folio_insights/vocab/shapes.ttl` — `fi:SupersessionAlignmentShape`.
- `src/folio_insights/vocab/predicates.ttl` — `fi:supersedes` /
  `fi:supersededBy` (owl:inverseOf pair, D-10) + `fi:validTimeStart` /
  `fi:validTimeEnd`.
- `tests/temporal/fixtures/supersession_chain.ttl` — the 10-link test
  fixture downstream phases can reuse as a regression scaffold.
- PRD `PRD-v2.0-draft-2.md` §21.9 — supersession-vs-retraction +
  valid-time semantics.

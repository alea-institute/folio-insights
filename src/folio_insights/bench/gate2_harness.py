"""Gate 2 P95 SPARQL harness (QUALITY-01, D-05).

Stateless entrypoint used by:
  - ``pytest-benchmark`` via ``tests/bench/test_gate2_sparql.py``
  - Plan 08 verdict scripts (DECISION.md ingestion)

D-05 discipline: every call goes through the same code path so measurements
are comparable across the 6-pass tuning playbook (RESEARCH.md §Gate 2 lines
512-526).

Named-graph layout (authoritative, from fixtures/bench.nq Phase 0 generator):

- ``https://folio-insights.aleainstitute.ai/corpus/advocacy``   (50% of quads)
- ``https://folio-insights.aleainstitute.ai/corpus/fre``        (25% of quads)
- ``https://folio-insights.aleainstitute.ai/corpus/restatement``(25% of quads)

Phase 0 bench.nq emits only the three corpus graphs — ``tbox`` / ``governance``
graphs referenced in the plan template do not exist in the Phase 0 fixture
(Plan 02 P2-D1 / Plan 00-02-SUMMARY.md confirm). Any query whose semantics
span all corpora must pass ``named_graphs=None`` (full scan) rather than
fabricating a graph IRI that does not match.
"""
from __future__ import annotations

from pathlib import Path

from pyoxigraph import NamedNode

from folio_insights.store import PyoxigraphStore

# ---------------------------------------------------------------------------
# Per-query named-graph prune table (Gate 2 tuning step 3)
# IRIs MUST match fixtures/bench.nq — verified via
#   awk '{print $(NF-1)}' fixtures/bench.nq | sort -u
# Any mismatch silently returns zero rows (pyoxigraph restricts the dataset
# to exactly the supplied IRIs; unknown IRIs → empty dataset → zero rows).
# ---------------------------------------------------------------------------
_CORPUS = "https://folio-insights.aleainstitute.ai/corpus/"
ADVOCACY_G = NamedNode(f"{_CORPUS}advocacy")
FRE_G = NamedNode(f"{_CORPUS}fre")
REST_G = NamedNode(f"{_CORPUS}restatement")
ALL_CORPORA: list[NamedNode] = [ADVOCACY_G, FRE_G, REST_G]

GOLD_QUERY_NAMED_GRAPHS: dict[str, list[NamedNode] | None] = {
    # Key: gold query file stem (without .sparql). Value: named_graphs param.
    # None = full graph scan (Phase 0 has only three graphs so this is a
    # superset over ALL_CORPORA; callers that want to exercise the prune
    # codepath explicitly should pass ALL_CORPORA instead).
    #
    # Rationale for each entry is recorded in 00-06-TUNING-LOG.md Pass 1.
    "q01_confidence_threshold": [ADVOCACY_G],
    "q02_advocacy_with_provenance": [ADVOCACY_G],
    "q03_polysemy_siblings": ALL_CORPORA,  # cross-corpus clustering
    "q04_supersession_chain": None,  # supersession crosses graphs
    "q05_framework_filter": [FRE_G, REST_G],
    "q06_as_of_historical": None,  # bitemporal spans all corpora
    "q07_axiom_closure": None,  # transitive axiom dependency crosses graphs
    "q08_seven_principles_conflict": [ADVOCACY_G],  # DisputedProposition in advocacy
    "q09_author_cluster_by_framework": [ADVOCACY_G],
    "q10_governance_attestation": [ADVOCACY_G],  # reified confidence lives in advocacy
    "q11_cross_corpus_traversal": None,  # cross-corpus by definition
    "q12_deprecated_with_successor": None,  # supersession crosses graphs
    "q13_confidence_histogram": [ADVOCACY_G],
}


def load_store_optimized(corpus_path: Path) -> PyoxigraphStore:
    """Gate 2 steps 1+2: bulk_load then optimize. Returns fully-loaded store.

    This is the SLOW setup path — callers SHOULD cache the result across
    queries. Expected one-time cost on the 1M corpus: ~30s (RocksDB bulk
    ingest + index compaction; pyoxigraph 0.5.7 in-memory).
    """
    store = PyoxigraphStore(path=None)  # in-memory; Phase 13 migrates to path=
    store.bulk_load_nquads(corpus_path)
    store.optimize()
    return store


def load_and_query(
    corpus_path: Path,
    query_path: Path,
    named_graphs: list[NamedNode] | None | str = "auto",
) -> list:
    """Gate 2 measurement entrypoint — bulk_load → optimize → query.

    Args:
        corpus_path: Path to ``fixtures/bench.nq`` (or similar).
        query_path: Path to a ``.sparql`` file in ``fixtures/gold_queries/``.
        named_graphs:
            - ``"auto"`` (default): look up in ``GOLD_QUERY_NAMED_GRAPHS`` by
              file stem.
            - ``None``: force full graph scan (no pruning).
            - ``list[NamedNode]``: explicit prune list.

    Returns:
        List of query result rows.

    NOTE: This function rebuilds the store on every call. For pytest-benchmark
    pedantic mode with rounds=20, this means 20 bulk-loads. That is expensive
    but INTENTIONAL for the cold-path variant — D-05 measures end-to-end, NOT
    warm-store query time. For warm-cache P95 (the D-05 authoritative
    measurement) use ``load_store_optimized()`` once + ``query_only()`` in
    the benchmark closure.
    """
    store = load_store_optimized(corpus_path)

    if named_graphs == "auto":
        named_graphs = GOLD_QUERY_NAMED_GRAPHS.get(query_path.stem)

    sparql = query_path.read_text()
    return store.query_rdf12(sparql, named_graphs=named_graphs)


def query_only(
    store: PyoxigraphStore,
    query_path: Path,
    named_graphs: list[NamedNode] | None | str = "auto",
) -> list:
    """Warm-path variant — query against a pre-loaded store.

    This is the D-05 authoritative variant for Gate 2 P95 measurement (tuning
    step 4: warm cache). Use ``load_store_optimized()`` once per benchmark
    module and pass the resulting store in here for each measured round.
    """
    if named_graphs == "auto":
        named_graphs = GOLD_QUERY_NAMED_GRAPHS.get(query_path.stem)
    sparql = query_path.read_text()
    return store.query_rdf12(sparql, named_graphs=named_graphs)

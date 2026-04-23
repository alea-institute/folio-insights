"""Phase 0 benchmark harness — 1M-triple scaled-real generator (D-13..D-16) + Gate 2 harness."""
from folio_insights.bench.gate2_harness import (
    GOLD_QUERY_NAMED_GRAPHS,
    load_and_query,
    load_store_optimized,
    query_only,
)
from folio_insights.bench.generator import BenchGenerator

__all__ = [
    "BenchGenerator",
    "GOLD_QUERY_NAMED_GRAPHS",
    "load_and_query",
    "load_store_optimized",
    "query_only",
]

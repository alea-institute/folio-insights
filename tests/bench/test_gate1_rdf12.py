"""Gate 1 STRICT: every PRD §20 RDF-12 rewrite must execute non-empty on 1M corpus.

Implements D-04 (STRICT binary) + STORAGE-04 + SEC-01 (SSRF baseline).

Test surface:
- 13 gold queries × non-empty assertion (test_gold_query_returns_rows)
- 13 gold queries × file-discipline check (test_gold_query_uses_annotation_pipe_syntax)
- 5 adversarial queries × safe-behavior assertion (test_adversarial_query_behaves_safely)
- 1 SSRF-specific query × <2s timeout (test_service_ssrf_query_does_not_reach_network)

Any gold-query parametrization that yields zero rows on fixtures/bench.nq
surfaces a Gate 1 FAIL signal to Plan 00-08 DECISION.md. Do NOT weaken the
assertion; investigate the generator profile or the rewrite first
(RESEARCH.md Gate 1 Playbook).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pyoxigraph import Store

QUERIES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "gold_queries"
GOLD_QUERIES = sorted(QUERIES_DIR.glob("q*.sparql"))
ADVERSARIAL_QUERIES = sorted((QUERIES_DIR / "adversarial").glob("*.sparql"))


@pytest.mark.parametrize("query_file", GOLD_QUERIES, ids=lambda p: p.stem)
def test_gold_query_returns_rows(bench_store: Store, query_file: Path) -> None:
    """D-04 STRICT: zero rows = Fuseki pivot trigger.

    Every gold query MUST return at least one row on the 1M bench corpus.
    A zero-row result is the Gate 1 FAIL signal — Plan 00-08 reads this
    verdict into 00-DECISION.md per D-17.
    """
    query = query_file.read_text()
    rows = list(bench_store.query(query))
    assert rows, (
        f"{query_file.name}: zero rows on 1M corpus — "
        f"Gate 1 FAIL, check RDF-12 annotation-pipe rewrite (Pitfall 1)"
    )


@pytest.mark.parametrize("query_file", GOLD_QUERIES, ids=lambda p: p.stem)
def test_gold_query_uses_annotation_pipe_syntax(query_file: Path) -> None:
    """Pitfall 1 file-discipline guard.

    pyoxigraph 0.5.x rejected subject-position triple terms (the banned
    SPARQL-star double-angle-bracket syntax). Gold queries MUST use the
    RDF-12 annotation-pipe form `{|...|}` and MUST contain zero banned-byte
    sequences.
    """
    text = query_file.read_text()
    # No banned SPARQL-star subject-term bytes
    assert "<<" not in text and ">>" not in text, (
        f"{query_file.name} contains SPARQL-star triple-term syntax — "
        "pyoxigraph 0.5.x rejects subject-position triple terms (Pitfall 1)"
    )
    # Must contain at least one annotation-pipe clause
    assert "{|" in text, (
        f"{query_file.name} missing annotation-pipe `{{|`; "
        "not a valid RDF-12 rewrite per STORAGE-04"
    )


@pytest.mark.timeout(30)
@pytest.mark.parametrize(
    "query_file", ADVERSARIAL_QUERIES, ids=lambda p: p.stem
)
def test_adversarial_query_behaves_safely(
    bench_store: Store, query_file: Path
) -> None:
    """§21 risk matrix: each adversarial query returns empty OR raises a
    named exception — never crashes or hangs.

    Accepted outcomes:
    - empty list (query parses + executes + yields no rows)
    - exception whose str() mentions SERVICE / timeout / limit / unsupported
      (expected for SERVICE, SSRF, large-CONSTRUCT cases)

    Rejected: segfault, hang past 30s (pytest-timeout kill), or a generic
    exception class that signals a raw pyoxigraph crash.
    """
    query = query_file.read_text()
    try:
        list(bench_store.query(query))
    except Exception as exc:
        msg = str(exc).lower()
        assert any(
            tok in msg
            for tok in ("service", "timeout", "limit", "unsupported", "parser")
        ), (
            f"{query_file.name}: unexpected crash class "
            f"{type(exc).__name__}: {exc!r}"
        )


@pytest.mark.timeout(2)
def test_service_ssrf_query_does_not_reach_network() -> None:
    """SEC-01 SSRF baseline: SERVICE against AWS metadata must complete <2s.

    A real SSRF reaching 169.254.169.254 on AWS would block on metadata
    service timeout (~21s). Enforced via pytest-timeout(2). Uses a fresh
    empty Store so SERVICE is the only possible data source — no fixture
    dependency.
    """
    from pyoxigraph import Store

    query_file = QUERIES_DIR / "adversarial" / "service_ssrf.sparql"
    s = Store()
    try:
        list(s.query(query_file.read_text()))
    except Exception:
        pass  # any exception is acceptable; hang is not

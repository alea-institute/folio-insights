# Phase 0: Foundations / HARD GATE — Pattern Map

**Mapped:** 2026-04-22
**Files analyzed:** 23 concrete artifacts (across 7 plans P0-A..P0-G)
**Analogs found:** 18 / 23 (5 are pure greenfield, seeded by RESEARCH.md code examples)

Grouped by plan (P0-A..P0-G per RESEARCH.md § Phase 0 Plan Topology) so `gsd-planner` can drop each group into the corresponding plan's `<read_first>` and `<action>` blocks.

---

## File Classification Summary

| # | New/Modified File | Plan | Role | Data Flow | Closest Analog | Match Quality |
|---|-------------------|------|------|-----------|----------------|---------------|
| 1 | `pyproject.toml` | P0-B, P0-E | config (modify) | build-input | self (existing) | exact — dep-append only |
| 2 | `tests/bench/conftest.py` | P0-B | test-fixture (new) | session-scoped I/O | `tests/conftest.py` | exact-role |
| 3 | `tests/bench/test_gate1_rdf12.py` | P0-C | integration test (new) | SPARQL-exec + assert | `tests/test_owl_export.py` (rdflib Graph testing) | role-match |
| 4 | `tests/bench/test_gate2_sparql.py` | P0-F | benchmark test (new) | perf-harness | RESEARCH.md Example 4 | greenfield (seed from research) |
| 5 | `tests/bench/test_gate3_image.py` | P0-F | smoke test (new) | subprocess-assert | `tests/test_cli.py` (CliRunner subprocess pattern) | role-match |
| 6 | `tests/bench/test_gate4_ssr.py` | P0-F | perf test (new) | hyperfine-subprocess | — | greenfield |
| 7 | `tests/bench/test_gate5_digest.py` | P0-E | smoke test (new) | docker-inspect | — | greenfield |
| 8 | `src/folio_insights/bench/generator.py` | P0-B | service (new) | re-extract → N-Quads | `src/folio_insights/pipeline/orchestrator.py` + `pipeline/stages/ingestion.py` | role-match |
| 9 | `src/folio_insights/bench/cli.py` | P0-B | CLI (new) | Click subcommand | `src/folio_insights/cli.py` (same file, extend pattern) | exact-role |
| 10 | `src/folio_insights/store/pyoxigraph_store.py` | P0-B, P0-C | service wrapper (new) | Store + rdflib bridge | `src/folio_insights/services/owl_serializer.py` (rdflib Graph ops) | partial |
| 11 | `src/folio_insights/reason/hermit_harness.py` | P0-F | subprocess harness (new) | owlready2 → JVM subprocess | — | greenfield |
| 12 | `viewer/svelte.config.js` | P0-D, P0-F | config (modify) | build-input | self (existing) | exact — adapter swap only |
| 13 | `viewer/src/hooks.server.ts` | P0-F | SSR middleware (new) | request-response | — | greenfield (seed from SvelteKit docs) |
| 14 | `viewer/src/routes/shards/[id]/+page.server.ts` | P0-F | SSR server load (new) | streaming load() | RESEARCH.md Pattern 3 + `viewer/src/lib/api/client.ts` (relative-URL pattern) | greenfield (seed) |
| 15 | `viewer/src/routes/polysemy/[id]/+page.server.ts` | P0-F | SSR server load (new) | streaming load() | same as #14 | greenfield (copy from #14 once built) |
| 16 | `viewer/src/routes/timeline/[id]/+page.server.ts` | P0-F | SSR server load (new) | streaming load() | same as #14 | greenfield (copy from #14 once built) |
| 17 | `Dockerfile.web` | P0-D | infrastructure (new) | multi-stage build | `Dockerfile` (existing single-stage) | role-match (derive web-only subset) |
| 18 | `Dockerfile.worker` | P0-D | infrastructure (new) | multi-stage build + JVM | `Dockerfile` (existing) + RESEARCH.md Example 5 | role-match |
| 19 | `dagger/build.py` (+ `dagger/railway.py`) | P0-E | CI pipeline (new) | Python SDK orchestration | — | greenfield (seed from RESEARCH.md Pattern 4) |
| 20 | `railway.toml` | P0-D | config (modify) | build-input | self (existing) | exact — two-service rewrite |
| 21 | `PHILOSOPHY.md` (rename) | P0-A | docs (rename) | file-move | `2026-04-19_Philosophy.md` | exact — pure `git mv` |
| 22 | `.planning/phases/00-foundations-hard-gate/00-DECISION.md` | P0-G | artifact (new) | verdict-doc | `00-CONTEXT.md` (structured-markdown format) | role-match (markdown template) |
| 23 | `fuseki/config.ttl` (CONDITIONAL) | P0-G | infrastructure (conditional) | Fuseki TDB2 config | — | greenfield (seed from RESEARCH.md § Fuseki Pivot Scaffold) |

**Coverage:**
- Files with exact analog: 6 (pyproject.toml, conftest.py, cli.py, svelte.config.js, railway.toml, PHILOSOPHY.md rename)
- Files with role-match analog: 9
- Files with no analog (greenfield): 8 — each cites a RESEARCH.md seed (Pattern 3/4/5 or Example 4/5/6)

---

## Plan P0-A — PHILOSOPHY.md Rename

### 21. `PHILOSOPHY.md` (RENAME from `2026-04-19_Philosophy.md`)

**Role:** Rename (pure `git mv` — no content change per D-18).
**Data flow:** filesystem move, repo-root target.
**Analog:** The source file itself (`/home/damienriehl/Coding Projects/folio-insights/2026-04-19_Philosophy.md`).
**Pattern notes:**
- Use `git mv 2026-04-19_Philosophy.md PHILOSOPHY.md` (not `mv` + `git add` — preserves blame history).
- No content restructure — D-18 explicitly scopes to rename only. Restructure is Phase 18.
- Verify with `test -f PHILOSOPHY.md` smoke check per RESEARCH.md § Validation Architecture.

---

## Plan P0-B — 1M-Triple Load Generator

### 1. `pyproject.toml` (MODIFY — dep-append)

**Role:** config modify.
**Data flow:** build-input (uv/pip resolves these at image build time).
**Analog:** self (`/home/damienriehl/Coding Projects/folio-insights/pyproject.toml`).

**Current relevant section** (lines 6-19):
```toml
dependencies = [
    "pydantic>=2.7.0",
    "pydantic-settings>=2.7.0",
    "httpx>=0.28.0",
    "rdflib>=7.6.0",
    "lxml>=5.0",
    "sentence-transformers>=3.0.0",
    "instructor>=1.14.0",
    "click>=8.0.0",
    "aiosqlite>=0.20.0",
    "folio-python>=0.1.5",
    "sse-starlette>=3.3.0",
    "pyshacl>=0.31.0",
]
```

**Pattern to append (P0-B scope — generator deps):**
```toml
dependencies = [
    # ... existing entries preserved ...
    "pyoxigraph==0.5.7",      # locked — RDF 1.2 store (RISK-3)
    "oxrdflib",                # bridge (one-way, non-RDF-12 paths only)
    "owlready2==0.50",         # HermiT JVM wrapper (RISK-1)
]

[project.optional-dependencies]
dev = [
    "pytest>=9.0",             # upgrade from >=8.0 per RESEARCH.md § Validation Architecture
    "pytest-asyncio>=0.25.0",
    "pytest-timeout>=2.3",
    "pytest-benchmark>=5.1",   # NEW — Gate 2 perf harness
    "dagger-io",               # NEW — Phase 0 CI pipeline (P0-E only; safe in dev bucket)
]
```

**Deviations from analog:**
- Pin `requires-python = ">=3.11,<3.13"` per Pitfall 8 (instructor + pydantic structural-match regressions on 3.13).
- Version-exact for pyoxigraph (`==0.5.7`) — RDF 1.2 eval fix is 0.5.2+; stay pinned for Gate 5 reproducibility.

---

### 2. `tests/bench/conftest.py` (NEW)

**Role:** pytest fixture module.
**Data flow:** session-scoped — loads fixture `bench.nq` into pyoxigraph Store once per test session.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/tests/conftest.py`.

**Imports pattern to copy** (from `tests/conftest.py` lines 1-15):
```python
"""Shared fixtures for folio-insights bench tests."""

from __future__ import annotations

from pathlib import Path

import pytest
```

**Fixture pattern to copy** (from `tests/conftest.py` lines 18-56):
```python
@pytest.fixture
def sample_knowledge_unit() -> KnowledgeUnit:
    """Return a fully populated KnowledgeUnit instance."""
    return KnowledgeUnit(...)
```

**Bench-specific additions (from RESEARCH.md Example 4, lines 807-812):**
```python
from pyoxigraph import Store, RdfFormat

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

@pytest.fixture(scope="session")
def bench_1m_corpus() -> Path:
    """D-14 pytest fixture — deterministic 1M-triple corpus."""
    # Pre-generated via `folio-insights bench gen --seed 42 --target 1000000`
    path = FIXTURES / "bench.nq"
    assert path.exists(), "run: folio-insights bench gen --seed 42 --target 1000000"
    return path

@pytest.fixture(scope="session")
def bench_store(bench_1m_corpus: Path) -> Store:
    """pyoxigraph Store pre-loaded + optimized (Gate 2 tuning steps 1-2)."""
    store = Store(path=None)  # in-memory for tests
    with open(bench_1m_corpus, "rb") as f:
        store.bulk_load(f, format=RdfFormat.N_QUADS)
    store.optimize()
    return store

@pytest.fixture
def seeded_rng() -> "random.Random":
    """Per-test seeded RNG (D-15 determinism per Pitfall 7)."""
    import random
    return random.Random(42)
```

**Pattern notes:**
- `scope="session"` for the Store fixture: bulk_load at 1M is expensive; reuse across all Gate 2 assertions.
- Explicit `random.Random(42)` instance per Pitfall 7 — never module-level `random.choice()`.
- `FIXTURES / "bench.nq"` is committed artifact per D-15 (seeded regen = digest stability for Gate 5).

---

### 8. `src/folio_insights/bench/generator.py` (NEW)

**Role:** service — 1M-triple scaled-real corpus generator (D-13).
**Data flow:** v1 extraction output → re-extract under v2 → replay bitemporal variations → `fixtures/bench.nq` N-Quads.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/src/folio_insights/pipeline/orchestrator.py` (stage orchestration) + `pipeline/stages/ingestion.py` (file-walking pattern).

**Imports pattern to copy** (from `pipeline/orchestrator.py` lines 17-33):
```python
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from folio_insights.config import Settings
from folio_insights.models.corpus import CorpusManifest
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
)

logger = logging.getLogger(__name__)
```

**Checkpoint pattern to reuse** (from `pipeline/orchestrator.py` lines 36-66 — PipelineCheckpoint class):
```python
class PipelineCheckpoint:
    @staticmethod
    def save(stage_name: str, job: InsightsJob, output_dir: Path) -> Path:
        checkpoint_dir = Path(output_dir) / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{stage_name}.json"
        data = {
            "stage": stage_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "unit_count": len(job.units),
            "job": job.model_dump(),
        }
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return checkpoint_path
```

**Deterministic generator skeleton (greenfield — D-13/D-15 scaffold):**
```python
class BenchGenerator:
    """D-13: scaled-real 1M-triple corpus generator.

    Re-extracts v1 advocacy + FRE + Restatement under v2 pipeline,
    replays bitemporal edits/supersessions to reach --target.
    """
    def __init__(self, seed: int, profile: str = "phase-0-gate") -> None:
        import random
        self.rng = random.Random(seed)  # per Pitfall 7 — single explicit RNG
        self.profile = profile

    def generate(self, target_triples: int, output_path: Path) -> Path:
        # Stage 1: re-extract v1 corpus via existing PipelineOrchestrator
        # Stage 2: emit RDF 1.2 annotation-pipe N-Quads via pyoxigraph Store
        # Stage 3: replay bitemporal variations until count == target
        # Stage 4: store.dump(output_path, format=RdfFormat.N_QUADS)
        # Sort all collections before iterating (Pitfall 7)
        ...
```

**Pattern notes:**
- `from __future__ import annotations` + module-level `logger = logging.getLogger(__name__)` is the project idiom.
- Use existing `PipelineOrchestrator` (orchestrator.py) as a sub-component to re-extract v1 corpora per D-01 ("re-extract v1 under v2 pipeline").
- Phase-profile flags (D-16) as `--profile phase-13-storage` map to config subclasses.
- **Determinism discipline (Pitfall 7):** single `random.Random(seed)` instance; sort all collections before iteration; never `numpy.random` module-level; never multiprocessed.
- N-Quads output must use RDF 1.2 annotation pipes for `fi:confidence` / `fi:validFrom` — never SPARQL-star `<<>>` (Anti-pattern per RESEARCH.md § Anti-Patterns).

---

### 9. `src/folio_insights/bench/cli.py` (NEW)

**Role:** CLI subcommand (extends existing `folio-insights` group).
**Data flow:** argv → Click group → BenchGenerator.generate() → N-Quads file.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/src/folio_insights/cli.py` (exact pattern — same file, just add subgroup).

**Click group + command pattern to copy** (from `src/folio_insights/cli.py` lines 32-80):
```python
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

logger = logging.getLogger("folio_insights")

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

@click.group()
@click.version_option(package_name="folio-insights")
def cli() -> None:
    """folio-insights: Extract structured advocacy knowledge from legal texts."""
```

**Subcommand-option pattern to copy** (from `cli.py` lines 38-90):
```python
@cli.command("extract")
@click.argument("source_dir", type=click.Path(exists=False, file_okay=False, resolve_path=True))
@click.option("--corpus", "-c", default="default", show_default=True)
@click.option("--output", "-o", default="./output", show_default=True, type=click.Path(resolve_path=True))
@click.option("--verbose", "-v", is_flag=True, default=False)
def extract(source_dir: str, corpus: str, output: str, verbose: bool) -> None:
    """Extract knowledge units from source files in SOURCE_DIR."""
    _setup_logging(verbose)
    # ...
```

**Bench subgroup (D-14/D-15/D-16 new pattern):**
```python
# Add to src/folio_insights/cli.py OR new src/folio_insights/bench/cli.py registered as subgroup

@cli.group("bench")
def bench() -> None:
    """Phase 0 benchmark harness (1M-triple gen + gate measurement)."""

@bench.command("gen")
@click.option("--target", default=1_000_000, show_default=True, type=int,
              help="Target triple count (D-14).")
@click.option("--seed", default=42, show_default=True, type=int,
              help="RNG seed for deterministic output (D-15).")
@click.option("--profile", default="phase-0-gate", show_default=True,
              type=click.Choice(["phase-0-gate", "phase-13-storage", "phase-16-sparql-adversarial"]),
              help="Phase-profile flag (D-16).")
@click.option("--out", "-o", default="fixtures/bench.nq", show_default=True,
              type=click.Path(resolve_path=True),
              help="Output N-Quads path.")
@click.option("--verbose", "-v", is_flag=True, default=False)
def bench_gen(target: int, seed: int, profile: str, out: str, verbose: bool) -> None:
    """Generate deterministic 1M-triple benchmark corpus (D-13..D-16)."""
    _setup_logging(verbose)
    from folio_insights.bench.generator import BenchGenerator
    gen = BenchGenerator(seed=seed, profile=profile)
    output_path = gen.generate(target_triples=target, output_path=Path(out))
    click.echo(f"Generated {target:,} triples → {output_path}")
```

**Pattern notes:**
- Options follow project idiom: `-c/--corpus`, `-o/--output`, `-v/--verbose` flags.
- `click.Path(resolve_path=True)` for any filesystem arg (matches `cli.py` lines 40-42, 52).
- **Register in `[project.scripts]`:** already `folio-insights = "folio_insights.cli:cli"` in pyproject.toml line 29 — just ensure `bench_gen` is importable from the `cli` group (add to existing file, or register via `cli.add_command`).
- CLI+fixture dual surface (D-14): same `BenchGenerator` used by both `bench gen` command and `bench_1m_corpus` pytest fixture.

---

## Plan P0-C — Gate 1 RDF-12 Rewrite

### 3. `tests/bench/test_gate1_rdf12.py` (NEW)

**Role:** integration test — Gate 1 STRICT binary (D-04).
**Data flow:** load gold-query SPARQL file → execute against pre-loaded `bench_store` fixture → assert non-empty + semantic spot-check.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/tests/test_owl_export.py` (rdflib Graph + assertion style).

**Imports + fixture-driven pattern from `tests/test_owl_export.py` lines 1-48:**
```python
"""Tests for Gate 1 RDF-12 annotation-pipe rewrites (STORAGE-04, SEC-01)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DC, OWL, PROV, RDF, RDFS, XSD

SAMPLE_TASKS = [ ... ]  # test fixtures as module-level constants
```

**Parametrize pattern from RESEARCH.md Example 4 lines 813-825:**
```python
from pyoxigraph import Store

QUERIES_DIR = Path("fixtures/gold_queries")

@pytest.mark.parametrize("query_file", sorted(QUERIES_DIR.glob("q*.sparql")))
def test_prd_section_20_rewrites_execute(bench_store: Store, query_file: Path) -> None:
    """D-04 STRICT: every PRD §20 query must execute and return non-empty on 1M corpus."""
    query = query_file.read_text()
    results = list(bench_store.query(query))
    # Gate 1 pass criterion: non-empty + no parser/exec exception
    assert results, f"{query_file.name}: zero rows — check RDF-12 annotation-pipe rewrite (Pitfall 1)"

@pytest.mark.parametrize("query_file", sorted((QUERIES_DIR / "adversarial").glob("*.sparql")))
def test_adversarial_queries_behave_safely(bench_store: Store, query_file: Path) -> None:
    """SERVICE-blocked, deep-GRAPH, large-CONSTRUCT must not crash the store."""
    query = query_file.read_text()
    # Expect either: (a) clean empty result, (b) clean error — NOT a hard crash
    try:
        list(bench_store.query(query))
    except Exception as exc:
        # Categorize error; SERVICE-blocked should be SERVICE-related, not segfault
        assert "SERVICE" in str(exc) or "timeout" in str(exc).lower(), \
            f"{query_file.name}: unexpected crash {exc!r}"
```

**Pattern notes:**
- Module-level `SAMPLE_TASKS = [...]` as fixtures is project style (from `test_owl_export.py` lines 27-48) — use same for sample gold queries.
- `@pytest.mark.parametrize` over `sorted(QUERIES_DIR.glob(...))` so each query gets its own test ID (better CI output).
- **Gate 1 anti-pattern (Pitfall 1 BLOCKING):** parser may accept `<<?s ?p ?o>>` silently and return zero rows — assertion MUST be non-empty, not just "no exception."
- Store `fixtures/gold_queries/q*.sparql` and `fixtures/gold_queries/adversarial/*.sparql` as committed artifacts per RESEARCH.md § Recommended Project Structure lines 264-272.

---

### 10. `src/folio_insights/store/pyoxigraph_store.py` (NEW)

**Role:** service wrapper — pyoxigraph Store + rdflib bridge (for pyshacl paths).
**Data flow:** bulk_load → optimize → query (RDF-12) OR dump(Turtle) → rdflib parse (non-RDF-12 SHACL).
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/src/folio_insights/services/owl_serializer.py` (rdflib Graph + namespace binding) + `src/folio_insights/services/shacl_validator.py` (pyshacl consumer).

**Namespace-binding pattern to copy** (from `services/owl_serializer.py` lines 13-45):
```python
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DC, OWL, PROV, RDF, RDFS, SKOS, XSD

FOLIO = Namespace("https://folio.openlegalstandard.org/")
FOLIO_INSIGHTS = Namespace("https://folio.openlegalstandard.org/modules/folio-insights/")

# Inside class method:
g = Graph()
g.bind("folio", FOLIO)
g.bind("owl", OWL)
g.bind("rdf", RDF)
```

**pyshacl lazy-load pattern to copy** (from `services/shacl_validator.py` lines 64-69):
```python
def _load_shapes(self) -> Graph:
    """Lazy-load the SHACL shapes graph."""
    if self._shapes_graph is None:
        self._shapes_graph = Graph()
        self._shapes_graph.parse(str(self._shapes_path), format="turtle")
    return self._shapes_graph
```

**RDF-12 → rdflib bridge (RESEARCH.md Pattern 2 lines 309-334):**
```python
from pyoxigraph import Store, NamedNode, RdfFormat
from rdflib import Dataset
from pyshacl import validate

class PyoxigraphStore:
    """STORAGE-02 bridge: pyoxigraph canonical store + one-way rdflib adapter for pyshacl."""

    def __init__(self, path: str | None = None) -> None:
        self._store = Store(path=path)  # None = in-memory; str = RocksDB on disk

    def bulk_load_nquads(self, path: Path) -> None:
        """Gate 2 tuning step 1 — bulk_load over per-triple .add()."""
        with open(path, "rb") as f:
            self._store.bulk_load(f, format=RdfFormat.N_QUADS)
        self._store.optimize()  # Gate 2 step 2 — RocksDB compaction

    def query_rdf12(self, sparql: str, named_graphs: list[NamedNode] | None = None) -> list:
        """RDF 1.2 annotation-pipe query on pyoxigraph (Gate 2 step 3 — prune named_graphs)."""
        return list(self._store.query(sparql, named_graphs=named_graphs))

    def validate_shard_via_rdflib_bridge(self, shard_iri: NamedNode, shapes_path: Path) -> tuple[bool, str]:
        """STORAGE-02 + Pattern 2: serialize to Turtle, re-parse in rdflib, validate with pyshacl.

        WARNING: RDF 1.2 annotation triples are silently dropped by rdflib 7.6 (Pitfall 2).
        Use ONLY for plain-triple shards; for RDF-12-annotated shards, use SPARQL ASK shapes directly.
        """
        construct_query = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{ GRAPH ?g {{ ?s ?p ?o . FILTER(?s = <{shard_iri.value}>) }} }}
        """
        turtle_bytes = b"".join(self._store.query(construct_query).serialize(format=RdfFormat.TURTLE))
        data_graph = Dataset()
        data_graph.parse(data=turtle_bytes, format="turtle")
        conforms, _, report_text = validate(
            data_graph=data_graph,
            shacl_graph=str(shapes_path),
            inference="rdfs",
            serialize_report_graph=True,
        )
        return conforms, report_text
```

**Pattern notes:**
- **Critical anti-pattern to avoid** (RESEARCH.md § Anti-Patterns, Pitfall 2): never write to rdflib and expect pyoxigraph to see it — bridge is strictly one-way (pyoxigraph → Turtle → rdflib).
- Use `Store(path=None)` for in-memory test fixtures; `Store(path="/var/lib/folio/rocksdb")` for the worker tier in Phase 13.
- `named_graphs=[NamedNode(...)]` kwarg is Gate 2 tuning lever #3 (RESEARCH.md line 519).
- For RDF-12 annotations, prefer SPARQL ASK shapes (pyoxigraph-native) over pyshacl to avoid the silent annotation-drop (RESEARCH.md Pitfall 2).

---

## Plan P0-D — Two-Stage Dockerfile + Redis Sidecar

### 17. `Dockerfile.web` (NEW — JVM-free)

**Role:** infrastructure — web-tier image (FastAPI + SvelteKit adapter-node build output).
**Data flow:** source → `uv pip install` → Node build → slim Python runtime.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/Dockerfile` (existing single-stage becomes the seed — strip JVM concerns).

**Frontend-builder stage pattern to copy** (from `Dockerfile` lines 1-18):
```dockerfile
# syntax=docker/dockerfile:1.7

# =========================================================================
# Stage 1: Build the SvelteKit viewer (adapter-node now, not adapter-static)
# =========================================================================
FROM node:22-slim@sha256:<pin-before-use> AS frontend-builder

WORKDIR /app/viewer
COPY viewer/package.json viewer/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY viewer/ ./
RUN npm run build
```

**Python runtime pattern to copy** (from `Dockerfile` lines 23-59):
```dockerfile
# =========================================================================
# Stage 2: Python runtime — FastAPI + adapter-node build
# =========================================================================
FROM python:3.11-slim@sha256:<pin-before-use>

# Gate 5 reproducibility
ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Hash-pinned install (Gate 5 step 5)
COPY pyproject.toml requirements.lock ./
COPY src/ ./src/
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY api/ ./api/
COPY --from=frontend-builder /app/viewer/build/ ./viewer/build/

# Gate 5: fixed UID (not useradd -r)
RUN useradd -u 1001 -g 1001 -m appuser \
    && mkdir -p /home/appuser/.folio-insights \
    && chown -R appuser:appuser /app /home/appuser
USER 1001

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')"
CMD ["sh", "-c", "node viewer/build/index.js & uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

**Pattern notes — what CHANGES from baseline `Dockerfile`:**
- `FROM node:20-slim` → `FROM node:22-slim@sha256:<digest>` (LTS per RESEARCH.md § Gate 4 tuning step 5; pinned digest per Gate 5 step 1).
- `FROM python:3.11-slim` → `FROM python:3.11-slim@sha256:<digest>` (pinned — Anti-pattern "Tagged base images").
- `useradd -m -r appuser` → `useradd -u 1001 -g 1001 -m appuser` (Anti-pattern "useradd -r without fixed UID").
- `USER appuser` → `USER 1001` (deterministic UID reference).
- Add `ARG SOURCE_DATE_EPOCH` + `ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}` at top (Gate 5 step 2).
- Add `requirements.lock` install with `--require-hashes` (Gate 5 step 5).
- Remove `COPY output/ ./output/` per Pitfall 5 — bundle fixtures via `fixtures/` instead, or load from volume at runtime.
- Add adapter-node runtime: `node viewer/build/index.js` in CMD alongside uvicorn (or use a supervisor process).
- **No JVM, no HermiT, no owlready2** on this image — P0-D split rule.

---

### 18. `Dockerfile.worker` (NEW — JVM + HermiT via jlink)

**Role:** infrastructure — worker-tier image (JVM 17 custom JRE + HermiT + Python reasoning harness).
**Data flow:** jlink custom JRE builder → Alpine Python runtime → HermiT subprocess on demand.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/Dockerfile` (general structure) + RESEARCH.md Example 5 (jlink + pinned digests).

**Full seed pattern (copy from RESEARCH.md Example 5, lines 832-873):**
```dockerfile
# syntax=docker/dockerfile:1.7

# ---- jlink JRE builder stage (Pattern 5 — Gate 3 biggest single win) ----
FROM eclipse-temurin:17-jdk-alpine@sha256:<pin-before-use> AS jre-builder
RUN "$JAVA_HOME/bin/jlink" \
        --add-modules java.base,java.logging,java.xml,java.naming,java.sql,jdk.crypto.ec \
        --strip-debug \
        --no-man-pages \
        --no-header-files \
        --compress=2 \
        --output /opt/java-custom

# ---- Worker runtime stage ----
FROM python:3.11-alpine@sha256:<pin-before-use>

# Gate 5 reproducibility
ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Copy custom JRE (~60-80MB vs ~180MB full JRE)
COPY --from=jre-builder /opt/java-custom /opt/java-custom
ENV JAVA_HOME=/opt/java-custom PATH="/opt/java-custom/bin:${PATH}"

# Gate 5 fixed UID/GID (Alpine syntax)
RUN addgroup -g 1001 appuser && adduser -D -u 1001 -G appuser appuser

WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser api/ ./api/

USER 1001
CMD ["python", "-m", "folio_insights.worker"]
```

**Pattern notes:**
- `--add-modules` list per RESEARCH.md line 443 — start with these 6; expand iteratively if HermiT throws `ClassNotFoundException` (Assumption A4).
- Assumption A1 (musllinux wheel availability for pyoxigraph on Alpine): verify via `pip download pyoxigraph==0.5.7 --platform musllinux_1_2_x86_64` at P0-D start. If no wheel, fall back to `python:3.11-slim` (debian) and accept +75MB toward the 500MB ceiling.
- Worker runs `folio_insights.worker` entry point (Arq worker loop — Phase 10 cutover; Phase 0 scaffold only).
- HermiT invocation path: `owlready2.sync_reasoner_hermit()` finds `java` on PATH → `/opt/java-custom/bin/java` (RESEARCH.md Pattern 5).

---

### 20. `railway.toml` (MODIFY)

**Role:** deploy config — switch from single-service to two-service (web + worker).
**Data flow:** Railway reads → builds two services from two Dockerfiles.
**Analog:** self (`/home/damienriehl/Coding Projects/folio-insights/railway.toml`).

**Current pattern (lines 1-21):**
```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 120
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

**Pattern to adapt — two-service split:**
```toml
# Railway services block — one per service
[services.web]
[services.web.build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile.web"

[services.web.deploy]
healthcheckPath = "/health"
healthcheckTimeout = 120
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3

[services.worker]
[services.worker.build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile.worker"

[services.worker.deploy]
# No healthcheck — worker has no HTTP surface (Arq polls Redis)
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3

# Redis sidecar — provisioned by Dagger pipeline per CONTEXT.md line 110
# (or use Railway's managed Redis plugin; decide at P0-E)
```

**Pattern notes:**
- Verify Railway's `[services.*]` multi-service syntax vs top-level `[build]` — Railway config-as-code supports both; two-service requires `[services.*]` nesting.
- `REDIS_URL` env var added per CONTEXT.md line 112 (runtime state inventory).
- Worker has no `healthcheckPath` — it's a polling consumer, not HTTP.
- Dagger pipeline triggers Railway deploys via Railway CLI or API token (P0-E integrates).

---

## Plan P0-E — Dagger CI + Gate 5 Digest

### 19. `dagger/build.py` + `dagger/railway.py` (NEW)

**Role:** CI pipeline — Python SDK orchestration (build → test → lint → deploy → Railway trigger).
**Data flow:** `git ct` → SOURCE_DATE_EPOCH → BuildKit reproducible image → publish digest → Railway deploy.
**Analog:** None in v1 repo (GitHub Actions was never set up). **Greenfield.**
**Seed:** RESEARCH.md Pattern 4 (Python SDK build pipeline, lines 384-431) + RESEARCH.md § Example 6 + § Gate-Tuning Playbook Gate 5.

**Full seed pattern (copy from RESEARCH.md Pattern 4, lines 384-430):**
```python
# dagger/build.py
import anyio, dagger, os

# Pinned by digest — not by tag — for reproducibility (Gate 5 step 1)
PYTHON_DIGEST = "python:3.11-slim@sha256:<pinned>"
NODE_DIGEST = "node:22-slim@sha256:<pinned>"
TEMURIN_DIGEST = "eclipse-temurin:17-jre-alpine@sha256:<pinned>"

async def main():
    async with dagger.Connection() as client:
        # Git commit timestamp → SOURCE_DATE_EPOCH for deterministic mtimes
        source_date_epoch = os.popen("git log -1 --pretty=%ct").read().strip()

        # Exclude .git / output / .planning / node_modules (Gate 5 step 10)
        src = client.host().directory(".", exclude=[".git", "output", ".planning", "node_modules"])

        worker = (
            client.container()
            .from_(TEMURIN_DIGEST)
            .with_env_variable("SOURCE_DATE_EPOCH", source_date_epoch)
            .with_exec(["apk", "add", "--no-cache", "python3", "py3-pip"])
            .with_directory("/app", src)
            .with_workdir("/app")
            .with_exec(["pip", "install", "--no-cache-dir",
                        "--require-hashes", "-r", "requirements.lock"])
            .with_exec(["adduser", "-D", "-u", "1001", "appuser"])
            .with_user("1001")
        )

        # Web stage (JVM-free) — from python:3.11-slim
        web = (
            client.container()
            .from_(PYTHON_DIGEST)
            .with_env_variable("SOURCE_DATE_EPOCH", source_date_epoch)
            .with_directory("/app", src)
        )

        # Publish both; capture digests for Gate 5 comparison
        worker_digest = await worker.publish("ttl.sh/fi-worker:0.1")
        web_digest = await web.publish("ttl.sh/fi-web:0.1")
        print(f"Worker: {worker_digest}")
        print(f"Web: {web_digest}")

anyio.run(main)
```

**Pattern notes — critical Gate 5 discipline (RESEARCH.md Pitfall 4):**
- Dagger does NOT automatically emit SOURCE_DATE_EPOCH — pipe as build arg on EVERY container (`.with_env_variable` AND `.with_build_arg`).
- Pin base images by `sha256:...`; regenerate digests via `crane digest python:3.11-slim` quarterly.
- Use `client.host().directory(".", exclude=[...])` — NEVER `COPY . .` without exclusions (Gate 5 step 10; Pitfall 5).
- Stage ordering (Claude's discretion per CONTEXT.md line 64): build → test → lint → deploy. Group stages by parallelizability — build/lint can parallelize, test must follow build, deploy is serial after all pass.
- `dagger/railway.py`: wraps `railway up --service web` and `railway up --service worker` (CLI via subprocess) OR POSTs to Railway GraphQL API with `RAILWAY_TOKEN` env var.
- Verify Dagger version at P0-E start (RESEARCH.md line 588 caveat); pin in `[project.optional-dependencies] dev` bucket.

---

### 7. `tests/bench/test_gate5_digest.py` (NEW)

**Role:** smoke test — bit-identical digest between local Dagger and Railway deployed.
**Data flow:** `docker inspect --format '{{.Id}}'` on two images → string compare.
**Analog:** None. **Greenfield.**
**Seed:** RESEARCH.md § Gate-Tuning Gate 5 measurement (line 590).

**Seed pattern:**
```python
"""Gate 5 — bit-identical digest (OBS-04, D-08)."""
import subprocess
import pytest

def _inspect_digest(image_ref: str) -> str:
    """Run `docker inspect --format '{{.Id}}'` on an image."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", image_ref],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()

@pytest.mark.parametrize("image", ["ttl.sh/fi-web:0.1", "ttl.sh/fi-worker:0.1"])
def test_local_dagger_digest_matches_railway(image: str) -> None:
    """D-08: local Dagger build digest == Railway-deployed digest."""
    local_digest = _inspect_digest(image)
    railway_digest = _inspect_digest(f"registry.railway.app/{image}")  # Railway's pull-back
    assert local_digest == railway_digest, \
        f"Gate 5 FAIL: {image} drift\n  local:   {local_digest}\n  railway: {railway_digest}"
```

**Pattern notes:**
- Pytest subprocess style matches `tests/test_cli.py` (CliRunner subprocess pattern — see analog for #5).
- On Gate 5 failure, record the delta in `00-DECISION.md` — do NOT retry blindly; Pitfall 4 suggests pipe-through issue with Dagger version.

---

## Plan P0-F — Gates 2/3/4 Measurement + SSR Prototype

### 4. `tests/bench/test_gate2_sparql.py` (NEW)

**Role:** benchmark test — P95 SPARQL latency at 1M (QUALITY-01).
**Data flow:** `bench_store` fixture → pytest-benchmark pedantic rounds → assert P95 < 500ms (accept ≤800ms post-tune per D-05).
**Analog:** None (no existing timing tests in v1). **Greenfield.**
**Seed:** RESEARCH.md Example 4, lines 798-826.

**Full seed pattern (copy verbatim, adjust only paths):**
```python
# tests/bench/test_gate2_sparql.py
import json
from pathlib import Path
import pytest
from folio_insights.bench.gate1_harness import load_and_query

GATE2_BUDGET_MS = 500  # hard target per QUALITY-01
GATE2_SLO_CEILING_MS = 800  # D-05 post-tune accept threshold
QUERIES_DIR = Path("fixtures/gold_queries")

@pytest.mark.benchmark(group="gate2-sparql-p95")
@pytest.mark.parametrize("query_file", sorted(QUERIES_DIR.glob("q*.sparql")))
def test_gate2_p95_under_500ms(benchmark, bench_1m_corpus, query_file):
    """QUALITY-01: P95 < 500ms @ 1M triples."""
    result = benchmark.pedantic(
        load_and_query,
        args=(bench_1m_corpus, query_file),
        rounds=20,
        warmup_rounds=3,
    )
    stats = benchmark.stats
    p95_ms = stats["95th percentile"] * 1000
    assert p95_ms < GATE2_BUDGET_MS, \
        f"{query_file.name}: P95 {p95_ms:.1f}ms > {GATE2_BUDGET_MS}ms"
```

**Pattern notes:**
- Tune-first discipline per D-05 (RESEARCH.md Gate 2 playbook lines 516-522): 6 ordered passes (bulk_load → optimize → named_graphs prune → warm cache → query-plan rewrites → RocksDB tuning); re-measure after each.
- Use `pytest --benchmark-autosave --benchmark-json=bench-results.json` for trend tracking (RESEARCH.md line 934).
- P95 is the metric — stats["95th percentile"] is pytest-benchmark's field.

---

### 5. `tests/bench/test_gate3_image.py` (NEW)

**Role:** smoke test — worker image size (QUALITY-03, D-06).
**Data flow:** `docker image inspect --format '{{.Size}}'` → byte assertion.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/tests/test_cli.py` (subprocess pattern via CliRunner — but here raw subprocess).

**Subprocess pattern inspiration (from `tests/test_cli.py` lines 17-21):**
```python
@pytest.fixture
def runner() -> CliRunner:
    """Provide a Click CliRunner for testing CLI commands."""
    return CliRunner()
```

**Adapted for Docker subprocess (greenfield):**
```python
"""Gate 3 — worker image size (QUALITY-03)."""
import subprocess
import pytest

GATE3_BUDGET_BYTES = 500 * 1024 * 1024  # 500MB hard target
GATE3_SLO_CEILING_BYTES = 700 * 1024 * 1024  # D-06 post-tune accept

def test_worker_image_under_500mb() -> None:
    """QUALITY-03: worker image < 500MB (accept ≤700MB post-tune per D-06)."""
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Size}}", "ttl.sh/fi-worker:0.1"],
        capture_output=True, text=True, check=True,
    )
    size_bytes = int(result.stdout.strip())
    size_mb = size_bytes / 1024 / 1024
    assert size_bytes < GATE3_BUDGET_BYTES, \
        f"Gate 3: worker image {size_mb:.1f}MB > 500MB target (tune jlink modules, Alpine, dep strip)"
```

**Pattern notes:**
- Run AFTER P0-D Dockerfile.worker builds; depends on `ttl.sh/fi-worker:0.1` tag from Dagger pipeline (#19).
- If size in (500MB, 700MB], D-06 says "accept with SLO relaxation" — record actual in DECISION.md but do NOT fail build.

---

### 6. `tests/bench/test_gate4_ssr.py` (NEW — or `gate4_ssr_latency.sh` per RESEARCH.md line 962)

**Role:** perf test — SSR cold-page latency (QUALITY-04, D-07).
**Data flow:** `hyperfine` subprocess on `curl http://localhost:8000/shards/<id>` → P95 extraction → assert.
**Analog:** None. **Greenfield.**
**Seed:** RESEARCH.md Gate 4 playbook (line 568) — `hyperfine 'curl -s ...' --warmup 3 --runs 50`.

**Seed pattern (Python wrapper per RESEARCH.md § Validation Architecture line 944):**
```python
"""Gate 4 — SSR cold-page latency (QUALITY-04)."""
import json
import subprocess
import pytest

GATE4_BUDGET_MS = 200  # hard target
GATE4_SLO_CEILING_MS = 400  # D-07 post-tune accept

SAMPLE_SHARD_IDS = ["a1b2c3d4e5f60708", "deadbeefcafe0001", "0123456789abcdef"]  # 3 surfaces per D-09

@pytest.mark.parametrize("shard_id", SAMPLE_SHARD_IDS)
def test_cold_page_under_200ms(shard_id: str) -> None:
    """QUALITY-04 Gate 4: cold /shards/<id> SSR <200ms (accept ≤400ms post-tune per D-07)."""
    url = f"http://localhost:8000/shards/{shard_id}"
    result = subprocess.run(
        ["hyperfine", "--warmup", "3", "--runs", "50", "--export-json", "-",
         f"curl -s {url}"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    # hyperfine emits seconds; "p95" from --export-json extended stats
    p95_ms = data["results"][0]["mean"] * 1000  # or use p95 field if available
    assert p95_ms < GATE4_BUDGET_MS, \
        f"SSR /{shard_id}: P95 {p95_ms:.1f}ms > {GATE4_BUDGET_MS}ms"
```

**Pattern notes:**
- hyperfine must be installed on CI image (RESEARCH.md line 915 — `apt install hyperfine` or `cargo install`).
- 3 surfaces per D-09 (shard/polysemy/timeline) — parametrize.
- Alternative per RESEARCH.md: pure bash `tests/bench/gate4_ssr_latency.sh` runs hyperfine + greps JSON; simpler but less CI-integrated. Choose Python if planner wants unified pytest harness.

---

### 11. `src/folio_insights/reason/hermit_harness.py` (NEW)

**Role:** subprocess harness — owlready2/HermiT with `-Xmx` tuning (D-11 full 1M ABox reasoning).
**Data flow:** ontology file → owlready2 → `java -Xmx<N>M -jar HermiT.jar` subprocess → classification result.
**Analog:** None. **Greenfield.**
**Seed:** RESEARCH.md § Standard Stack line 118 (owlready2 subprocess pattern with `-Xmx%sM` heap flag) + § Don't Hand-Roll line 476 (don't invoke `java -jar` directly; use `owlready2.sync_reasoner_hermit()`).

**Seed pattern:**
```python
"""HermiT reasoning harness (D-11 full 1M ABox).

RISK-1 mitigation: runs in worker tier only (JVM bloat excluded from web).
Pitfall 3: first invocation costs 5-15s JVM cold-start — measure it.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import owlready2

logger = logging.getLogger(__name__)

class HermitHarness:
    """D-11 harness: full-corpus HermiT reasoning with Xmx tuning.

    Must NOT ship on web image (QUALITY-03 two-stage split — Anti-pattern 9).
    """
    def __init__(self, xmx_mb: int = 4096) -> None:
        self.xmx_mb = xmx_mb
        # owlready2 config per docs: `owlready2.JAVA_MEMORY = <MB>`
        owlready2.JAVA_MEMORY = xmx_mb

    def reason(self, ontology_path: Path) -> dict:
        """Load ontology, run HermiT, return classification + timing metadata."""
        onto = owlready2.get_ontology(str(ontology_path)).load()
        t0 = time.perf_counter()
        with onto:
            owlready2.sync_reasoner_hermit()  # subprocess java -jar HermiT.jar
        elapsed = time.perf_counter() - t0
        logger.info("HermiT reasoned %s in %.2fs (Xmx=%dMB)", ontology_path.name, elapsed, self.xmx_mb)
        return {
            "ontology": str(ontology_path),
            "xmx_mb": self.xmx_mb,
            "elapsed_s": elapsed,
            "consistent": list(onto.inconsistent_classes()) == [],
        }
```

**Pattern notes:**
- Assumption A11 — real JVM cost for 1M ABox unknown; measure at D-11 (MAX-FIDELITY full-corpus run, 1-2 days per run per CONTEXT.md line 43).
- `-Xmx` tuning happens after first measurement — do NOT pre-guess; let D-11 data drive.
- Pitfall 3 cold-start: first `sync_reasoner_hermit()` is 5-15s (JVM start + classpath + HermiT init). If gates run in CI, pre-warm a persistent JVM OR accept cold-start cost + mark async-only (PRINCIPLE-01).
- Anti-pattern: never shell out to `java -jar HermiT.jar` directly (RESEARCH.md § Don't Hand-Roll line 476) — owlready2 handles tempfile + classpath + error parsing.

---

### 12. `viewer/svelte.config.js` (MODIFY — adapter swap)

**Role:** config modify — adapter-static → adapter-node.
**Data flow:** svelte.config.js → kit build → adapter output (build/index.js server vs build/*.html static).
**Analog:** self (`/home/damienriehl/Coding Projects/folio-insights/viewer/svelte.config.js`).

**Current pattern (lines 1-16):**
```javascript
import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
    kit: {
        adapter: adapter({ fallback: 'index.html' }),
        paths: { base: '' }
    },
    vitePlugin: {
        dynamicCompileOptions: ({ filename }) =>
            filename.includes('node_modules') ? undefined : { runes: true }
    }
};

export default config;
```

**Pattern to replace — adapter-node swap:**
```javascript
import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
    kit: {
        adapter: adapter({
            out: 'build',
            precompress: false,  // use @polka/compression at runtime instead
            envPrefix: 'FOLIO_',
        }),
        paths: { base: '' }
    },
    vitePlugin: {
        dynamicCompileOptions: ({ filename }) =>
            filename.includes('node_modules') ? undefined : { runes: true }
    }
};

export default config;
```

**Pattern notes:**
- `viewer/package.json` dependency swap: remove `@sveltejs/adapter-static` (line 25), add `@sveltejs/adapter-node` (`^5.5.4` per RESEARCH.md Standard Stack line 120).
- Keep `vitePlugin.dynamicCompileOptions` (runes=true) — this is project-wide Svelte 5 config.
- **Anti-pattern (RESEARCH.md line 464):** do NOT install standard `compression` package — breaks streaming. Use `@polka/compression` when wrapping the adapter-node handler.
- Pitfall 6: audit every existing `load()` function — SvelteKit 2 removed auto-await for critical data; migrate to explicit `await` where data blocks initial paint.

---

### 13. `viewer/src/hooks.server.ts` (NEW)

**Role:** SSR middleware hook — wraps every SSR request (streaming, cache-control).
**Data flow:** request → hook.handle() → resolve(event) → response stream.
**Analog:** None in v1 (current repo has no hooks.server.ts). **Greenfield.**
**Seed:** RESEARCH.md Gate 4 playbook (line 564 — @polka/compression); SvelteKit docs for `handle` hook.

**Seed pattern:**
```typescript
// viewer/src/hooks.server.ts
import type { Handle } from '@sveltejs/kit';
import compression from '@polka/compression';  // NOT 'compression' — see Anti-pattern

const gzip = compression({ threshold: 1024 });

export const handle: Handle = async ({ event, resolve }) => {
    // Gate 4 tuning step 2: edge-cache for 60s
    const response = await resolve(event, {
        transformPageChunk: ({ html }) => html,
    });

    // Apply streaming-safe gzip (replaces standard `compression` which breaks streaming)
    // @polka/compression integration via raw-middleware adapter (see adapter-node docs)
    return response;
};
```

**Pattern notes:**
- Anti-pattern (RESEARCH.md line 464): `compression` package breaks streaming; always `@polka/compression`.
- For full `@polka/compression` + adapter-node integration, see adapter-node's custom-server pattern (not shown here — planner cites svelte.dev/docs/kit/adapter-node).

---

### 14/15/16. `viewer/src/routes/{shards,polysemy,timeline}/[id]/+page.server.ts` (NEW × 3)

**Role:** SSR server load — 3 Phase 15 surfaces prototyped per D-09 MAX-FIDELITY.
**Data flow:** `/shards/<id>` → `+page.server.ts load()` → `fetch('/api/shard/<id>/core')` (awaited) + streaming deps/attests (unawaited) → HTML stream.
**Analog:** `/home/damienriehl/Coding Projects/folio-insights/viewer/src/routes/tasks/+page.ts` (viewer route pattern — but that one is `export const ssr = false` to force SPA; we want the opposite).
**Analog pattern (relative-URL API client):** `/home/damienriehl/Coding Projects/folio-insights/viewer/src/lib/api/client.ts` lines 1-9 — keeps `API_BASE = ''` and routes through Vite proxy (MEMORY: `feedback_api-client-proxy.md`).

**Current v1 pattern — force client-only (tasks/+page.ts line 1):**
```typescript
export const ssr = false;
```
(This is what we're REPLACING — we want full SSR for Gate 4 prototype.)

**Relative-URL API pattern to KEEP (from `viewer/src/lib/api/client.ts` lines 1-9):**
```typescript
/**
 * API client for the folio-insights Review Viewer backend.
 * All /api requests use relative URLs. In dev mode, the Vite proxy forwards
 * them to the FastAPI backend (see viewer/vite.config.ts for the proxy target).
 */
const API_BASE = '';
```

**Full seed pattern (from RESEARCH.md Pattern 3, lines 343-361) — shard surface:**
```typescript
// viewer/src/routes/shards/[id]/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch, setHeaders }) => {
    // Critical path: blocks initial paint — must be <200ms (Gate 4)
    const shardCore = await fetch(`/api/shard/${params.id}/core`).then(r => r.json());

    // Gate 4 tuning step 2: edge-cache HTML 60s
    setHeaders({ 'cache-control': 'public, max-age=60, s-maxage=60' });

    return {
        shard: shardCore,                                                              // awaited — blocks
        dependencies: fetch(`/api/shard/${params.id}/deps`).then(r => r.json()),        // streams
        attestations: fetch(`/api/shard/${params.id}/attests`).then(r => r.json()),     // streams
    };
};
```

**Companion `+page.svelte` streaming render (from RESEARCH.md lines 362-376):**
```svelte
<!-- viewer/src/routes/shards/[id]/+page.svelte -->
<script>
  export let data;
</script>

<h1>{data.shard.iri}</h1>
<ShardCore shard={data.shard} />

{#await data.dependencies}
  <DependencySkeleton />
{:then deps}
  <DependencyGraph {deps} />
{/await}
```

**Pattern notes:**
- Files 15 (`polysemy/[id]/+page.server.ts`) and 16 (`timeline/[id]/+page.server.ts`) follow IDENTICAL structure — copy from shard, swap API endpoint (`/api/polysemy/<id>` vs `/api/timeline/<id>`) and stream-vs-block decisions per surface-specific needs.
- Use `fetch` from `event` (SvelteKit's internal fetch) — propagates headers and works on server.
- Keep relative URLs (`/api/...`) per MEMORY `feedback_api-client-proxy.md`; Vite proxy (vite.config.ts line 15) forwards to uvicorn.
- Pitfall 6 critical: explicit `await` only for data that MUST block initial paint; everything else returns as unawaited promise (SvelteKit 5 streams).
- No `export const ssr = false` — we want SSR ON (opposite of `viewer/src/routes/tasks/+page.ts`).

---

## Plan P0-G — DECISION.md + Fuseki Pivot Scaffold (CONDITIONAL)

### 22. `.planning/phases/00-foundations-hard-gate/00-DECISION.md` (NEW)

**Role:** phase artifact — structured binary verdict + measurement table (D-17).
**Data flow:** Gates 1-5 measurement outputs → synthesis → keep/pivot verdict.
**Analog:** `.planning/phases/00-foundations-hard-gate/00-CONTEXT.md` (structured-markdown format with `<tag>` sections).

**Structure pattern to copy from `00-CONTEXT.md` lines 1-151:**
- H1 title with phase prefix.
- Metadata block: `**Gathered:** DATE`, `**Status:** ...`
- `<domain>`, `<decisions>`, `<canonical_refs>`, `<code_context>`, etc. XML-style tag sections.
- Tables for tabular data (like D-01..D-18).
- Sign-off line at bottom: `*Phase: 00-foundations-hard-gate*`.

**DECISION.md seed (D-17 schema):**
```markdown
# Phase 0: Foundations / HARD GATE — DECISION

**Decided:** YYYY-MM-DD
**Status:** FINAL (blocks Phase 6/11/13/16 routing)

## Verdict

**keep=pyoxigraph** OR **pivot=fuseki**   ← binary; one of the two

## Per-Gate Measurement Table

| Gate | Req | Budget | SLO Ceiling | Measured | Pass/Fail | Notes |
|------|-----|--------|-------------|----------|-----------|-------|
| 1 | STORAGE-04 | 100% §20 rewrite | (strict — no SLO) | X/13 queries pass | pass/fail | ... |
| 2 | QUALITY-01 | P95 <500ms | ≤800ms (D-05) | NNN ms | pass/accept/pivot | tuning passes: 1,2,3 applied |
| 3 | QUALITY-03 | <500MB | ≤700MB (D-06) | NNN MB | pass/accept/microservice-split | jlink saved X MB |
| 4 | QUALITY-04 | SSR <200ms | ≤400ms (D-07) | NNN ms | pass/accept/deferred-hydration | streaming + cache applied |
| 5 | OBS-04 | bit-identical | (strict — no SLO) | digest-match Y/N | pass/fail | SOURCE_DATE_EPOCH applied |

## Tuning Passes Performed

(Per-gate breakdown of which tuning steps from RESEARCH.md playbooks were applied and their deltas.)

## Downstream Phase Branch Guidance

| Phase | On `keep` | On `pivot` |
|-------|-----------|------------|
| 6 DID | in-process pyoxigraph | HTTP PATCH to Fuseki |
| 11 SHACL | rdflib bridge | Fuseki native `fuseki:shacl` |
| 13 Storage | RocksDB | TDB2 |
| 16 Public SPARQL | FastAPI wrapping pyoxigraph | reverse-proxy to Fuseki |
| 10 Worker | bundled in worker | (same — HermiT unaffected) |

## Signatures

(Deferred — DID signing is Phase 6+ per D-17. Phase 0 artifact is unsigned; re-sign once DID substrate exists.)
```

**Pattern notes:**
- Follow `00-CONTEXT.md` idiom: structured tables + XML-tag sections; MUST be machine-parseable (downstream planner reads this to route Phase 6/11/13/16).
- "Downstream Phase Branch Guidance" table is mandatory per D-17 — planners for those phases consume this directly.
- NO DID signing in Phase 0 (chicken-and-egg per D-17) — sign later.

---

### 23. `fuseki/config.ttl` (CONDITIONAL — only if Gate 1 fails)

**Role:** infrastructure — Fuseki TDB2 config (SPARQL + SHACL endpoints).
**Data flow:** Fuseki reads at startup → serves `/folio/sparql` and `/folio/shacl`.
**Analog:** None. **Greenfield (conditional).**
**Seed:** RESEARCH.md § Fuseki Pivot Scaffold, lines 609-633.

**Full seed pattern (copy verbatim from RESEARCH.md lines 609-632):**
```turtle
# fuseki/config.ttl (Fuseki 5.x)
PREFIX fuseki:  <http://jena.apache.org/fuseki#>
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX tdb2:    <http://jena.apache.org/2016/tdb#>
PREFIX ja:      <http://jena.hpl.hp.com/2005/11/Assembler#>
PREFIX :        <#>

[] rdf:type fuseki:Server ;
   ja:context [ ja:cxtName "arq:queryTimeout" ; ja:cxtValue "30000" ] ;
   .

<#service> rdf:type fuseki:Service ;
    fuseki:name "folio" ;
    fuseki:endpoint [ fuseki:operation fuseki:query ; fuseki:name "sparql" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:shacl ; fuseki:name "shacl" ] ;
    fuseki:dataset <#dataset> .

<#dataset> rdf:type tdb2:DatasetTDB2 ;
    tdb2:location "/fuseki/databases/folio" ;
    tdb2:unionDefaultGraph false .
```

**Pattern notes:**
- CONDITIONAL — only create if Gate 1 fails (DECISION.md verdict = `pivot=fuseki`).
- `fuseki:operation fuseki:query` only — no `fuseki:update` per SPARQL-01 (read-only public endpoint; Phase 10/11 add write).
- `tdb2:unionDefaultGraph false` keeps corpora isolated (STORAGE-03).
- Pair with `docker run apache/jena-fuseki:5.1.0 --config=/fuseki/config.ttl` (RESEARCH.md lines 635-641).
- Assumption A10 — config is inference from docs; validated by a second mini-spike if pivot triggers.

---

## Shared Patterns (Apply Across Plans)

### Shared 1: RDF 1.2 anti-pattern avoidance

**Source:** RESEARCH.md § Anti-Patterns, lines 462-470 + § Common Pitfalls, Pitfall 1 (lines 667-672).
**Apply to:** Every file that writes SPARQL or serializes N-Quads/Turtle (generator.py, gold queries, test harnesses).

**Rule excerpt:**
```
- BAN `<<?s ?p ?o>>` subject-position quoted-triple patterns — INVALID in pyoxigraph 0.5.x.
- USE annotation-pipe `?s ?p ?o {| ?p2 ?o2 |}` per RDF 1.2 spec.
- Lint: grep for `<<` in .sparql files → test failure.
- Pitfall 1: silent zero rows — assertion MUST check non-empty, not just "no exception."
```

### Shared 2: Gate 5 reproducibility discipline

**Source:** RESEARCH.md § Gate-Tuning Gate 5, lines 576-587.
**Apply to:** Dockerfile.web, Dockerfile.worker, dagger/build.py, pyproject.toml.

**Ten required techniques:**
1. Pin base images `@sha256:...`, not tag.
2. `ARG SOURCE_DATE_EPOCH` + `ENV SOURCE_DATE_EPOCH` on every container.
3. BuildKit `--output type=image,rewrite-timestamp=true`.
4. Fixed UID/GID `1001` (useradd `-u 1001`, adduser `-D -u 1001`).
5. Hash-pinned pip: `uv pip compile --generate-hashes` → `requirements.lock` → `pip install --require-hashes -r requirements.lock`.
6. `apt-get --no-install-recommends <pkg>=<version>` + `rm -rf /var/lib/apt/lists/*`.
7. `PYTHONDONTWRITEBYTECODE=1`.
8. Ordered explicit COPY (not `COPY . .`).
9. Exclude `.git`, `output/`, `.planning/` via `.dockerignore`.
10. Dagger: pass SOURCE_DATE_EPOCH as both `with_env_variable` AND `with_build_arg` (Pitfall 4 — Dagger does NOT emit automatically).

### Shared 3: Determinism discipline for generator (Pitfall 7)

**Source:** RESEARCH.md § Common Pitfalls, Pitfall 7, lines 710-715.
**Apply to:** `src/folio_insights/bench/generator.py`, `conftest.py`, any file that samples/selects.

**Rules:**
```python
# RIGHT:
rng = random.Random(seed)  # explicit instance
items_sorted = sorted(collection, key=lambda x: x.id)  # sort before iterate
for item in items_sorted:
    choice = rng.choice(options)

# WRONG:
import random
random.choice(options)  # module-level state
import numpy.random  # separate seed state; breaks determinism
for item in collection:  # unsorted iteration
    ...
```

### Shared 4: Relative-URL API client pattern (carries to SSR)

**Source:** `/home/damienriehl/Coding Projects/folio-insights/viewer/src/lib/api/client.ts` lines 1-9 (verbatim) + MEMORY `feedback_api-client-proxy.md`.
**Apply to:** All viewer routes #14/15/16 (`+page.server.ts` files).

**Rule:** `API_BASE = ''`; never hardcode `http://localhost:9925`. Vite proxy (vite.config.ts line 15) handles forwarding. Same pattern must carry into SSR — use SvelteKit's `event.fetch` with relative `/api/...` paths.

### Shared 5: Python project idioms

**Source:** `/home/damienriehl/Coding Projects/folio-insights/src/folio_insights/pipeline/orchestrator.py` lines 17-33.
**Apply to:** All new Python modules under `src/folio_insights/` (generator.py, cli.py, pyoxigraph_store.py, hermit_harness.py).

**Rules:**
- `from __future__ import annotations` at top.
- Module-level `logger = logging.getLogger(__name__)`.
- Pydantic v2 models for job/state objects (see `pipeline/stages/base.py` lines 15-22 — `InsightsJob(BaseModel)`).
- `Path` from `pathlib` everywhere; never raw string paths in signatures.
- Explicit type hints on all public functions.

---

## No Analog Found (Greenfield — seeded by RESEARCH.md)

| File | Plan | Seed Source |
|------|------|-------------|
| `tests/bench/test_gate2_sparql.py` | P0-F | RESEARCH.md Example 4 (lines 798-826) |
| `tests/bench/test_gate4_ssr.py` | P0-F | RESEARCH.md § Gate 4 playbook (line 568 — hyperfine) |
| `tests/bench/test_gate5_digest.py` | P0-E | RESEARCH.md § Gate 5 playbook (line 590 — docker inspect diff) |
| `viewer/src/hooks.server.ts` | P0-F | RESEARCH.md Gate 4 tuning step 4 (@polka/compression) |
| `viewer/src/routes/shards/[id]/+page.server.ts` | P0-F | RESEARCH.md Pattern 3 (lines 343-376) |
| `viewer/src/routes/polysemy/[id]/+page.server.ts` | P0-F | Same as shards (copy+adapt) |
| `viewer/src/routes/timeline/[id]/+page.server.ts` | P0-F | Same as shards (copy+adapt) |
| `dagger/build.py` + `dagger/railway.py` | P0-E | RESEARCH.md Pattern 4 (lines 384-431) + Example 6 |
| `src/folio_insights/reason/hermit_harness.py` | P0-F | RESEARCH.md § Standard Stack owlready2 (line 118) + § Don't Hand-Roll (line 476) |
| `fuseki/config.ttl` (CONDITIONAL) | P0-G | RESEARCH.md § Fuseki Pivot Scaffold (lines 609-641) |

For each: the RESEARCH.md seed is the CANONICAL pattern — planner should cite it in the plan's `<read_first>` block and copy-paste the excerpt into `<action>`.

---

## Metadata

**Analog search scope:**
- `/home/damienriehl/Coding Projects/folio-insights/src/folio_insights/` (pipeline, services, cli, models)
- `/home/damienriehl/Coding Projects/folio-insights/tests/` (conftest, test_cli, test_owl_export, test_extraction)
- `/home/damienriehl/Coding Projects/folio-insights/viewer/src/` (routes, lib/api, svelte.config)
- `/home/damienriehl/Coding Projects/folio-insights/` (Dockerfile, railway.toml, pyproject.toml, api/main.py)

**Files scanned:** ~35 (Grep + Read combined).
**Pattern extraction date:** 2026-04-22.
**Pattern density:** Every "NEW" file cites either a codebase analog OR an explicit RESEARCH.md seed (Pattern 3/4/5 or Example 4/5/6). No abstract guidance without line numbers.

---

*Phase: 00-foundations-hard-gate*
*Patterns mapped: 2026-04-22*

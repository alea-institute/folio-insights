"""HermiT harness tests (D-11 + Pitfall 3).

Covers:
- Smoke-level consistency classification on tiny fixtures
- Xmx tuning knob writes ``owlready2.JAVA_MEMORY`` at instance init
- Cold- vs warm-call timing acknowledgement (Pitfall 3: JVM startup)
- Opt-in D-11 full-1M reasoning (FOLIO_RUN_D11=1)
"""
from __future__ import annotations

import os
from pathlib import Path

import owlready2
import pytest

from folio_insights.reason import HermitHarness


@pytest.fixture
def tiny_consistent_ontology(tmp_path: Path) -> Path:
    """Minimal consistent OWL ontology — 3 classes, 2 individuals."""
    path = tmp_path / "tiny.owl"
    path.write_text(
        """<?xml version=\"1.0\"?>
<rdf:RDF xmlns=\"http://test.org/tiny#\"
         xml:base=\"http://test.org/tiny\"
         xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\"
         xmlns:owl=\"http://www.w3.org/2002/07/owl#\"
         xmlns:rdfs=\"http://www.w3.org/2000/01/rdf-schema#\">
  <owl:Ontology rdf:about=\"http://test.org/tiny\"/>
  <owl:Class rdf:about=\"http://test.org/tiny#Animal\"/>
  <owl:Class rdf:about=\"http://test.org/tiny#Dog\">
    <rdfs:subClassOf rdf:resource=\"http://test.org/tiny#Animal\"/>
  </owl:Class>
  <owl:Class rdf:about=\"http://test.org/tiny#Cat\">
    <rdfs:subClassOf rdf:resource=\"http://test.org/tiny#Animal\"/>
  </owl:Class>
  <Dog rdf:about=\"http://test.org/tiny#Rex\"/>
  <Cat rdf:about=\"http://test.org/tiny#Whiskers\"/>
</rdf:RDF>
"""
    )
    return path


@pytest.fixture
def tiny_inconsistent_ontology(tmp_path: Path) -> Path:
    """Ontology with Dog and Cat disjoint + Rex typed as both → inconsistent."""
    path = tmp_path / "tiny-bad.owl"
    path.write_text(
        """<?xml version=\"1.0\"?>
<rdf:RDF xmlns=\"http://test.org/bad#\"
         xml:base=\"http://test.org/bad\"
         xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\"
         xmlns:owl=\"http://www.w3.org/2002/07/owl#\"
         xmlns:rdfs=\"http://www.w3.org/2000/01/rdf-schema#\">
  <owl:Ontology rdf:about=\"http://test.org/bad\"/>
  <owl:Class rdf:about=\"http://test.org/bad#Dog\">
    <owl:disjointWith rdf:resource=\"http://test.org/bad#Cat\"/>
  </owl:Class>
  <owl:Class rdf:about=\"http://test.org/bad#Cat\"/>
  <Dog rdf:about=\"http://test.org/bad#Rex\"/>
  <Cat rdf:about=\"http://test.org/bad#Rex\"/>
</rdf:RDF>
"""
    )
    return path


@pytest.mark.slow
def test_hermit_harness_on_consistent_ontology(tiny_consistent_ontology: Path) -> None:
    """Smoke: 3-class ontology reasons cleanly (consistent=True)."""
    harness = HermitHarness(xmx_mb=512)
    result = harness.reason(tiny_consistent_ontology)
    assert result.consistent is True
    assert result.elapsed_s > 0
    assert result.xmx_mb == 512


@pytest.mark.slow
def test_hermit_harness_detects_inconsistency(tiny_inconsistent_ontology: Path) -> None:
    """Smoke: disjoint-violation ontology is flagged inconsistent."""
    harness = HermitHarness(xmx_mb=512)
    result = harness.reason(tiny_inconsistent_ontology)
    assert result.consistent is False
    assert len(result.inconsistent_classes) > 0


def test_hermit_sets_java_memory() -> None:
    """Xmx tuning knob — HermitHarness.__init__ sets owlready2.JAVA_MEMORY."""
    HermitHarness(xmx_mb=8192)
    assert owlready2.JAVA_MEMORY == 8192
    # Reset to a sane default so other tests aren't influenced
    HermitHarness(xmx_mb=2048)
    assert owlready2.JAVA_MEMORY == 2048


@pytest.mark.slow
def test_hermit_cold_vs_warm_cost(tiny_consistent_ontology: Path) -> None:
    """Pitfall 3: first reason() should include JVM startup; second is fresh spawn too.

    owlready2 spawns a subprocess per sync_reasoner_hermit() call, so both timings
    pay JVM startup cost. We do NOT assert ordering — just log both for
    measurement logs.
    """
    harness = HermitHarness(xmx_mb=512)
    t_cold = harness.reason(tiny_consistent_ontology).elapsed_s
    t_warm = harness.reason(tiny_consistent_ontology).elapsed_s
    # Pitfall 3 acknowledgement — log for MEASUREMENTS.md. Do not assert.
    print(f"cold={t_cold:.3f}s warm={t_warm:.3f}s")
    assert t_cold > 0
    assert t_warm > 0


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("FOLIO_RUN_D11") != "1",
    reason="D-11 full-1M reasoning — opt in via FOLIO_RUN_D11=1 env (takes 10-60+ min)",
)
@pytest.mark.timeout(3600)  # 1hr hard ceiling
def test_hermit_full_1m_abox() -> None:
    """D-11: full 1M ABox reasoning. Opt-in via env var."""
    abox_path = Path("fixtures/bench-abox-1m.owl")
    if not abox_path.exists():
        pytest.skip(
            f"{abox_path} missing — generate via: "
            "`uv run folio-insights bench gen --seed 42 --target 1000000 "
            "--format owl --out fixtures/bench-abox-1m.owl`"
        )
    harness = HermitHarness(xmx_mb=int(os.environ.get("FOLIO_HERMIT_XMX", "4096")))
    result = harness.reason(abox_path)
    # D-11 measurement is the point — no strict pass threshold here.
    # Surface to 00-07-MEASUREMENTS.md: elapsed_s, xmx_mb, consistent
    print(f"D-11: {result.elapsed_s:.1f}s Xmx={result.xmx_mb}MB consistent={result.consistent}")
    assert result.elapsed_s < 3600, f"D-11 exceeded 1hr ceiling: {result.elapsed_s:.0f}s"

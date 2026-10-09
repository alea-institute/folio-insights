"""HermiT backend for cluster consistency (Phase 9 U1, KTD4). WORKER TIER ONLY.

HermiT runs through owlready2 and a JVM, which only the worker image carries
(``Dockerfile.worker``; RISK-1 keeps the JVM out of the web image). This
module reaches owlready2 only lazily, through ``reason.hermit_harness``, when
``HermitClusterReasoner.check`` runs; ``hermit_available`` answers whether it
could, without importing owlready2.

The reasoner takes one cluster's ground formal triples, renders them as an
OWL N-Triples document (``validation.formal.owl_ntriples``) and returns a
``FormalVerdict``: whether the ontology is consistent and which named classes
are unsatisfiable (by IRI).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
from collections.abc import Sequence

from folio_insights.validation.formal import FormalVerdict, Triple3, owl_ntriples

ONTOLOGY_IRI = "urn:folio-insights:validation:cluster"
_INCONSISTENT_SENTINEL = "<ontology-inconsistent>"


def hermit_available() -> tuple[bool, str]:
    """``(available, reason)``: owlready2 importable and a Java runtime on the
    path (or under ``JAVA_HOME``). Never imports owlready2."""
    if importlib.util.find_spec("owlready2") is None:
        return False, "owlready2 is not installed (worker image only)"
    java_home = os.environ.get("JAVA_HOME")
    if shutil.which("java") is None and not (
        java_home and os.path.exists(os.path.join(java_home, "bin", "java"))
    ):
        return False, "no Java runtime found for HermiT"
    return True, "available"


class HermitClusterReasoner:
    """HermiT over one cluster's formal content (``reason.HermitHarness``)."""

    name = "hermit"

    def __init__(self, xmx_mb: int = 1024) -> None:
        if xmx_mb <= 0:
            raise ValueError(f"xmx_mb must be > 0, got {xmx_mb}")
        self.xmx_mb = xmx_mb
        self.calls = 0

    def check(self, triples: Sequence[Triple3]) -> FormalVerdict:
        from folio_insights.reason.hermit_harness import HermitHarness  # worker tier only

        self.calls += 1
        document = owl_ntriples(triples, ontology_iri=ONTOLOGY_IRI)
        result = HermitHarness(xmx_mb=self.xmx_mb).reason_ntriples(document)
        if _INCONSISTENT_SENTINEL in result.inconsistent_classes:
            return FormalVerdict(consistent=False)
        return FormalVerdict(consistent=True, unsatisfiable=tuple(result.unsatisfiable_class_iris))


__all__ = [
    "HermitClusterReasoner",
    "ONTOLOGY_IRI",
    "hermit_available",
]

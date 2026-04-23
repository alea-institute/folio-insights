"""HermiT reasoning harness (D-11 full 1M ABox).

RISK-1 mitigation: runs in worker tier only (JVM bloat excluded from web per
REQ-QUALITY-03).

Pitfall 3 (RESEARCH.md §Common Pitfalls): first invocation costs 5–15s JVM
cold-start. owlready2 spawns a subprocess per ``sync_reasoner_hermit`` call,
so each call effectively pays a fresh JVM startup; ``elapsed_s`` captures the
total wall-clock including that spawn.

Architectural-responsibility note: this harness is a THIN WRAPPER around
``owlready2.sync_reasoner_hermit()``. Per RESEARCH.md §Don't Hand-Roll, we do
NOT shell out to ``java -jar HermiT.jar`` directly — owlready2 handles
tempfile, classpath, and error parsing for us.

Contract:

    >>> from folio_insights.reason import HermitHarness
    >>> harness = HermitHarness(xmx_mb=4096)
    >>> result = harness.reason(Path("fixtures/bench-abox-1m.owl"))
    >>> # result.elapsed_s, result.xmx_mb, result.consistent, result.inconsistent_classes
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import owlready2

logger = logging.getLogger(__name__)


@dataclass
class HermitResult:
    """Structured output of a single HermiT run."""

    ontology: str
    xmx_mb: int
    elapsed_s: float
    consistent: bool
    inconsistent_classes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize for MEASUREMENTS.md / DECISION.md ingestion."""
        return {
            "ontology": self.ontology,
            "xmx_mb": self.xmx_mb,
            "elapsed_s": self.elapsed_s,
            "consistent": self.consistent,
            "inconsistent_classes": self.inconsistent_classes,
        }


class HermitHarness:
    """D-11 harness: full-corpus HermiT reasoning with Xmx tuning.

    Instance-level state: the ``xmx_mb`` value passed to ``__init__`` is
    written to the module-global ``owlready2.JAVA_MEMORY`` so owlready2 picks
    it up when it spawns the HermiT subprocess. Constructing a new harness
    with a different ``xmx_mb`` updates the global.

    Usage:
        harness = HermitHarness(xmx_mb=4096)
        result = harness.reason(Path("fixtures/bench-abox-1m.owl"))
        print(f"HermiT: {result.elapsed_s:.1f}s, consistent={result.consistent}")
    """

    def __init__(self, xmx_mb: int = 4096) -> None:
        """Configure JVM heap for the HermiT subprocess.

        Args:
            xmx_mb: JVM max heap in MB. D-11 tuning target — start at 4096,
                measure elapsed + memory usage, retune per MEASUREMENTS.md.
        """
        if xmx_mb <= 0:
            raise ValueError(f"xmx_mb must be > 0, got {xmx_mb}")
        self.xmx_mb = xmx_mb
        # owlready2 reads this module-global at subprocess-spawn time.
        # Setting it on __init__ means any subsequent .reason() call picks
        # it up, regardless of which harness instance invokes it (process-
        # global, but that matches owlready2's own design).
        owlready2.JAVA_MEMORY = xmx_mb

    def reason(self, ontology_path: Path) -> HermitResult:
        """Load ontology → ``sync_reasoner_hermit()`` → capture timing + consistency.

        Uses a fresh ``owlready2.World()`` per call to prevent cross-test state
        leak (owlready2 has a process-global ``default_world`` that accumulates
        ontologies otherwise).
        """
        world = owlready2.World()
        onto = world.get_ontology(str(ontology_path)).load()

        t0 = time.perf_counter()
        inconsistent_classes: list[str] = []
        consistent = True
        try:
            with onto:
                owlready2.sync_reasoner_hermit(
                    x=[onto],
                    infer_property_values=True,
                )
        except owlready2.OwlReadyInconsistentOntologyError as exc:
            # HermiT returns exit code 1 with "Inconsistent ontology" — the
            # ontology itself is unsatisfiable (not a reasoner crash). This is
            # a valid D-11 result, not an error: capture it as consistent=False.
            elapsed = time.perf_counter() - t0
            consistent = False
            # owlready2 does not populate onto.inconsistent_classes() when the
            # WHOLE ontology is inconsistent — encode the verdict in a sentinel
            # that downstream consumers (MEASUREMENTS.md) can recognise.
            inconsistent_classes = ["<ontology-inconsistent>"]
            logger.info(
                "HermiT reported ontology-level inconsistency on %s after %.2fs: %s",
                ontology_path.name,
                elapsed,
                exc,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error("HermiT failed after %.2fs: %s", elapsed, exc)
            raise
        else:
            elapsed = time.perf_counter() - t0
            named_inconsistent = list(onto.inconsistent_classes())
            if named_inconsistent:
                consistent = False
                inconsistent_classes = [str(c) for c in named_inconsistent]

        result = HermitResult(
            ontology=str(ontology_path),
            xmx_mb=self.xmx_mb,
            elapsed_s=elapsed,
            consistent=consistent,
            inconsistent_classes=inconsistent_classes,
        )
        logger.info(
            "HermiT reasoned %s in %.2fs (Xmx=%dMB, consistent=%s)",
            ontology_path.name,
            elapsed,
            self.xmx_mb,
            result.consistent,
        )
        return result

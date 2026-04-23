"""OWL reasoning — HermiT via owlready2 (D-11, RISK-1).

Worker-tier only: RESEARCH.md §RISK-1 bans the JVM from the web image.
``HermitHarness`` is the canonical entrypoint; downstream code (Phase 10
worker, Phase 13 shape validation) MUST import from here rather than calling
``owlready2.sync_reasoner_hermit`` directly so the Xmx-tuning contract stays
one place.
"""
from folio_insights.reason.hermit_harness import HermitHarness, HermitResult

__all__ = ["HermitHarness", "HermitResult"]

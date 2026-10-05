"""OWL reasoning — HermiT via owlready2 (D-11, RISK-1), plus the OWL 2 EL profile check.

Worker-tier only for the reasoner: RESEARCH.md §RISK-1 bans the JVM from the
web image. ``HermitHarness`` is the canonical entrypoint; downstream code
(Phase 10 worker, Phase 13 shape validation) MUST import from here rather than
calling ``owlready2.sync_reasoner_hermit`` directly so the Xmx-tuning contract
stays one place.

Phase 9 U4: ``HermitHarness`` / ``HermitResult`` are resolved lazily (PEP 562),
so importing the pure-Python siblings — ``reason.el_profile`` (the OWL 2 EL
check the storage export runs) and ``reason.reasoner`` (the ``Reasoner``
protocol) — never imports owlready2 in the web tier.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from folio_insights.reason.hermit_harness import HermitHarness, HermitResult

__all__ = ["HermitHarness", "HermitResult"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from folio_insights.reason import hermit_harness

        return getattr(hermit_harness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

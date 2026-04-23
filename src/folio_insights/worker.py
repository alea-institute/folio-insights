"""Worker entrypoint stub (Phase 0 scaffold; Phase 10 Stage 8 wires Arq loop).

This module exists solely so that `Dockerfile.worker`'s CMD
(`python -m folio_insights.worker`) resolves to an importable target during
Phase 0 smoke builds. Phase 10 replaces this idle loop with the real Arq
consumer that drains Redis job queues for HermiT reasoning + ontology sync.

Deliberate scope (per plan 00-04 Task 2 Step 4):
- No real worker logic here — out of scope per RESEARCH.md Architectural
  Responsibility Map.
- Emits a startup log line so smoke tests can confirm the process actually
  starts inside the container before signalling.
"""

from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Phase 0 stub: log once, then idle. Phase 10 replaces with Arq loop."""
    logger.info(
        "folio-insights worker stub — Phase 0 scaffold. "
        "Idle loop; Phase 10 Stage 8 replaces with Arq consumer."
    )
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()

"""Process-local shared state for governance + corpus CLI subgroups (Phase 7).

The ``governance promote``, ``governance assert-role``, ``governance
revoke-role``, and ``corpus init`` CLI commands MUST share a single
``GovernanceLog`` instance so that within a Python process the genesis
bootstrap performed by ``corpus init`` is visible to subsequent ``governance``
calls (and a SECOND ``corpus init`` against the same corpus sees the existing
log row + returns ``corpus_already_initialized``).

Phase 13 (D-07) wires ``<corpus>/.governance.sqlite`` behind the
``GovernanceLog`` Protocol; this module's singleton becomes a thin
constructor lookup once that persistent backend lands. Phase 7 ships the
in-memory variant — adequate for the orig EC3 amended bar (CLI-only, no
cross-process persistence required).
"""
from __future__ import annotations

from folio_insights.governance.log import InMemoryGovernanceLog

# Module-level singleton shared between governance/cli/ and corpus/cli/. The
# InMemoryGovernanceLog reset is per-process — `CliRunner.invoke` in tests
# can reset it via a fixture if cross-test isolation is needed.
GOVERNANCE_LOG: InMemoryGovernanceLog = InMemoryGovernanceLog()


__all__ = ["GOVERNANCE_LOG"]

"""Phase 7 governance substrate (PRD §3.1, §6.5).

Hosts the 13-class GovernanceEvent discriminated union (``events.py`` — the
sole entry-point ``GovernanceLog.append`` consumes per D-06), the SHACL
validator skeleton (``shape_validation.py`` — populated by 07-03 / 07-04a /
07-04b / 07-05a / 07-05b), and (in later plans) the GovernanceLog Protocol,
RoleStore, and authorization decision module.

D-04 boundary: stdlib + Pydantic ONLY — NO aiosqlite/rdflib/pyoxigraph/oxrdflib
imports under governance/ (Phase 13 wires the persistent backend behind the
GovernanceLog Protocol). The lone exempt module is governance/shape_validation.py
(mirrors revision/shape_validation.py — pyshacl + rdflib are the validator's
necessary substrate; ``tests/governance/test_dep_leak_guard.py`` exempts it by
filename, mirroring the precedent that ``revision/shape_validation.py`` is
exempt from the ``shards/`` dep-leak boundary).

D-13 closes F6 by exposing ``RoleRevocationEvent`` as a structurally distinct
class from ``RoleAssertionEvent`` (different ``action`` Literal pin, different
field set) — revocation is NOT a flag.
"""
from __future__ import annotations

from folio_insights.governance.events import (
    ContestEvent,
    ContestResolutionEvent,
    ContestResolutionPath,
    ContentEditEvent,
    DemotionEvent,
    DistinguoEvent,
    ExtractEvent,
    GovernanceEvent,
    PromotionEvent,
    PromotionStatus,
    ReconcileEvent,
    ReparentEvent,
    RetractionEvent,
    RoleAssertionEvent,
    RoleName,
    RoleRevocationEvent,
    SupersessionEvent,
)

__all__ = [
    # events.py — the 13 event classes + the discriminated union + shared aliases
    "ContestEvent",
    "ContestResolutionEvent",
    "ContestResolutionPath",
    "ContentEditEvent",
    "DemotionEvent",
    "DistinguoEvent",
    "ExtractEvent",
    "GovernanceEvent",
    "PromotionEvent",
    "PromotionStatus",
    "ReconcileEvent",
    "ReparentEvent",
    "RetractionEvent",
    "RoleAssertionEvent",
    "RoleName",
    "RoleRevocationEvent",
    "SupersessionEvent",
]

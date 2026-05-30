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
from folio_insights.governance.authorize import (
    Allow,
    AuthorizeResult,
    Deny,
    authorize,
)
from folio_insights.governance.log import (
    GovernanceLog,
    InMemoryGovernanceLog,
    InvalidSignature,
    NotAuthorized,
    WouldLockoutCorpusAdmin,
)
from folio_insights.governance.roles import (
    active_roles_at,
    active_roles_for_did,
)
from folio_insights.governance.shape_validation import ValidationResult

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
    # log.py — Protocol seam + in-memory implementation (07-03)
    "GovernanceLog",
    "InMemoryGovernanceLog",
    # log.py — exceptions added in 07-04a
    "InvalidSignature",
    "NotAuthorized",
    "WouldLockoutCorpusAdmin",
    # roles.py — windowed active-roles query (07-04a; D-13 / F2 closure)
    "active_roles_at",
    "active_roles_for_did",
    # authorize.py — central authorize() gate (07-04a; D-19)
    "Allow",
    "AuthorizeResult",
    "Deny",
    "authorize",
    # shape_validation.py — SHACL result type (validator bodies land in later plans)
    "ValidationResult",
]

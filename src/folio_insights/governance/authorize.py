"""Phase 7 central authorize() — single fact-of-truth for role-based access (D-19).

Every CLI command calls ``authorize(did, action, corpus, *, log, admin_did=None)``
as the FIRST step after parsing. The function returns a typed Allow / Deny
result and NEVER raises — mirroring the ``identity/verifier.verify_attestation``
boolean discipline at the gate layer.

The D-10 genesis carve-out is STRUCTURAL INSIDE THIS MODULE (Issue #3 fix).
``action="corpus_init"`` is the bookkeeping action name used at the bootstrap
step; ``authorize()`` recognizes it, checks the log row count + the supplied
admin DID, and returns Allow only when:

  (a) ``await log.latest_position(corpus) == -1`` (zero existing rows), AND
  (b) ``admin_did is not None`` (the CLI bound the operator's DID), AND
  (c) ``did == admin_did`` (the caller's identity matches the bootstrap DID).

Any other combination at ``action="corpus_init"`` returns Deny with a
specific reason string. There is NO CLI-level exemption — the bootstrap CLI
command passes through this same ``authorize()`` gate; the carve-out lives
HERE, not at the CLI.

D-04 boundary: stdlib + Pydantic + a re-export of roles.active_roles_for_did
only. NO aiosqlite / rdflib / pyshacl imports here (the dep-leak guard
enforces). SHACL is the belt-and-suspenders second check at the log layer.

Action-permission table (PRD §3.1, PATTERNS.md L226-229):

  extractor    -> {extract, content_edit}
  reviewer     -> above + {promote, demote, contest, supersede, retract,
                          distinguo, content_edit, reparent, reconcile,
                          export, show}  (D-19 — read paths still gated)
  arbiter      -> above + {resolve_contest}
  corpus_admin -> above + {role_assertion, role_revocation}

D-19 read-path extension (07-05b): the bookkeeping actions ``export`` and
``show`` are NOT writes to the log, but every CLI command still passes
through ``authorize()`` as its first awaited step. Reviewers, arbiters,
and corpus_admins MAY ``export`` / ``show``; extractors MAY NOT (they
have no read-of-governance-log mandate in PRD §3.1).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Union

from pydantic import BaseModel, ConfigDict

from folio_insights.governance.roles import active_roles_for_did

if TYPE_CHECKING:
    from folio_insights.governance.log import GovernanceLog


# ── Result types ────────────────────────────────────────────────────────


class Allow(BaseModel):
    """Authorization granted. ``reason`` is informational (e.g. genesis bootstrap)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str | None = None


class Deny(BaseModel):
    """Authorization refused. ``reason`` is a stable identifier the CLI may
    surface to the operator. Reason strings used by this module:

      * ``"corpus_already_initialized"`` — corpus_init at rows > 0.
      * ``"genesis_mismatch"`` — corpus_init at rows == 0, did != admin_did.
      * ``"genesis_admin_did_required"`` — corpus_init with admin_did=None.
      * ``"no_active_role"`` — did has no active role at asof.
      * ``"role_lacks_action:<action>"`` — did has a role that does NOT carry
        the requested action.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str


AuthorizeResult = Union[Allow, Deny]


# ── Bookkeeping action name (Issue #3 — structural inside authorize()) ──
#
# The CLI in 07-04b imports this constant so the corpus_init action name
# lives in ONE place across the codebase.
_GENESIS_ACTION = "corpus_init"


# ── Action-permission table (D-19; PRD §3.1) ─────────────────────────────
#
# Each role is mapped to the SET of action strings it carries. Strings are
# the SignedAction Literal values (see shards/envelope.SignedAction). The
# bookkeeping ``corpus_init`` action is NOT in any role's set — it is
# recognized structurally INSIDE authorize() before the table lookup.

_EXTRACTOR_ACTIONS: frozenset[str] = frozenset(
    {
        "extract",
        "content_edit",
    }
)

_REVIEWER_ACTIONS: frozenset[str] = _EXTRACTOR_ACTIONS | frozenset(
    {
        "promote",
        "demote",
        "contest",
        "supersede",
        "retract",
        "distinguo",
        "reparent",
        "reconcile",
        # 07-05b read-path actions (D-19 reads still pass through authorize):
        "export",
        "show",
    }
)

_ARBITER_ACTIONS: frozenset[str] = _REVIEWER_ACTIONS | frozenset({"resolve_contest"})

_CORPUS_ADMIN_ACTIONS: frozenset[str] = _ARBITER_ACTIONS | frozenset(
    {
        "role_assertion",
        "role_revocation",
    }
)

_ACTION_PERMISSIONS: dict[str, frozenset[str]] = {
    "extractor": _EXTRACTOR_ACTIONS,
    "reviewer": _REVIEWER_ACTIONS,
    "arbiter": _ARBITER_ACTIONS,
    "corpus_admin": _CORPUS_ADMIN_ACTIONS,
}


# ── The central gate (D-19) ─────────────────────────────────────────────


async def authorize(
    did: str,
    action: str,
    corpus: str,
    *,
    log: "GovernanceLog",
    admin_did: str | None = None,
    asof: datetime | None = None,
) -> AuthorizeResult:
    """Central authorization decision (D-19).

    Returns ``Allow`` or ``Deny(reason)`` — NEVER raises. The typed result is
    the only failure mode the caller sees (mirrors verify_attestation's
    boolean discipline).

    The D-10 genesis carve-out is the FIRST check (Issue #3 fix). Standard
    role-based authorization is the fall-through.

    Args:
        did: the caller's DID (the CLI binds this from the --did flag /
            keystore default).
        action: a SignedAction Literal value OR the bookkeeping action
            ``"corpus_init"``. Unknown actions return Deny.
        corpus: the per-corpus governance log.
        log: the GovernanceLog instance (Phase 7 in-memory; Phase 13 persistent).
        admin_did: required when ``action == "corpus_init"``. The CLI binds
            this from the ``--admin-did`` flag at the genesis bootstrap step.
        asof: the wall-clock at which roles are resolved. Defaults to UTC now.
    """
    resolved_asof = asof if asof is not None else datetime.now(UTC)

    # ── Genesis carve-out FIRST (Issue #3 — structural inside authorize()) ──
    if action == _GENESIS_ACTION:
        current_pos = await log.latest_position(corpus)
        if current_pos >= 0:
            return Deny(reason="corpus_already_initialized")
        if admin_did is None:
            return Deny(reason="genesis_admin_did_required")
        if did != admin_did:
            return Deny(reason="genesis_mismatch")
        return Allow(
            reason="genesis bootstrap — position=0 self-signed corpus_admin assertion"
        )

    # ── Standard role-based authorization ──
    roles = await active_roles_for_did(corpus, did, resolved_asof, log=log)
    if not roles:
        return Deny(reason="no_active_role")
    for role in roles:
        permitted = _ACTION_PERMISSIONS.get(role, frozenset())
        if action in permitted:
            return Allow()
    return Deny(reason=f"role_lacks_action:{action}")


__all__ = [
    "Allow",
    "AuthorizeResult",
    "Deny",
    "authorize",
]

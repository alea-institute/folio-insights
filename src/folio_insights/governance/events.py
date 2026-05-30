"""Phase 7 GovernanceEvent discriminated union (D-06, D-13, D-16, GOV-01/GOV-02).

The 13-class Pydantic discriminated union that ``governance_log.append(event)``
will consume as its sole entry-point (D-06). Each event class pins its
``action`` discriminator to one of the 13 ``SignedAction`` Literal values
extended from Phase 6, and shares three universal slots via ``_BaseEvent``:

  * ``corpus: str``       — the per-corpus governance log this event belongs to.
  * ``position: int``     — append-position assigned by ``GovernanceLog.append``
                            (default ``-1`` means "unassigned"; Phase 13 wires
                            the persistent counter).
  * ``signature: AttestedSignature`` — the only shared primitive per D-16; every
                            event is DID-signed (or honestly unsigned with
                            ``verified=None``).

D-13 closes F6 by making ``RoleRevocationEvent`` a structurally distinct
Pydantic class from ``RoleAssertionEvent`` — different ``action`` Literal pin
and different field set (``revoked_role`` vs ``role``). NOT a flag.

D-04 boundary: this module imports **stdlib + Pydantic + the Phase 6
``AttestedSignature`` primitive only**. NO aiosqlite / rdflib / pyoxigraph /
oxrdflib imports here (or anywhere under ``governance/`` except the lone
exempt ``shape_validation.py``). The Phase 13 persistent backend will slot in
behind the ``GovernanceLog`` Protocol without touching this module.

The 13 event classes correspond 1:1 with the 13 ``SignedAction`` Literal
values: 12 Phase 6 inherited + ``role_revocation`` (the D-13 extension).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from folio_insights.shards.envelope import AttestedSignature


# ── Module-level Literal aliases for repeated role / status vocabularies ──
#
# The 4 role names appear in both RoleAssertionEvent and RoleRevocationEvent;
# the 3 promotion targets appear in PromotionEvent only; the contest-resolution
# paths are exhausted by GOV-05 (no majority-vote). Centralized here so adding a
# new role / status touches one line, not two.
RoleName = Literal["extractor", "reviewer", "arbiter", "corpus_admin"]
PromotionStatus = Literal[
    "per_se_nota_quoad_nos",
    "demonstrable",
    "authority_only",
]
ContestResolutionPath = Literal["arbiter", "distinguo", "aporetic"]


class _BaseEvent(BaseModel):
    """Universal slots every governance event carries (D-06, D-16).

    Three fields shared by every event in the union:

      * ``corpus`` — the per-corpus governance log this event lives in.
      * ``position`` — the append-position assigned by
        ``GovernanceLog.append`` (Phase 13). Default ``-1`` means "not yet
        appended"; tests construct events with the default and let the log
        assign positions.
      * ``signature`` — the AttestedSignature carrying ``action`` (which
        Pydantic's discriminated union ALSO matches against the per-class
        ``action`` Literal pin below — see GovernanceEvent definition).

    Subclasses override ``action: Literal["<value>"] = "<value>"`` to pin the
    discriminator and add their event-specific fields. ``extra="forbid"`` is
    inherited by every subclass.
    """
    model_config = ConfigDict(extra="forbid")

    corpus: str
    position: int = -1
    signature: AttestedSignature

    def signature_payload(self) -> bytes:
        """Return the JCS-canonical SHA-256 hash bytes of this event's content
        excluding the signature itself (07-04a — Phase 6 verify_attestation
        belt-and-suspenders gate for role events).

        Mirrors ``revision.content_edit.canonical_content_hash`` discipline:
        dump the model to a Python dict, drop the ``signature`` slot, JCS-
        canonicalize, SHA-256, return the digest hex string encoded as bytes.
        The returned bytes can be passed to ``sign_attestation`` /
        ``verify_attestation`` as the ``content_hash`` (those functions expect
        the hex string of the canonical hash).

        Note: ``position`` is INCLUDED in the payload because it is part of
        the event's identity (the append-only invariant) by the time the
        signature is constructed in production paths. Tests construct events
        with the post-append position before signing.
        """
        import hashlib

        import jcs

        # Pydantic dumps with .model_dump(mode="json") to get JSON-safe primitives
        # for JCS canonicalization (datetimes -> isoformat strings, etc.).
        data = self.model_dump(mode="json")
        data.pop("signature", None)
        canonical = jcs.canonicalize(data)
        digest = hashlib.sha256(canonical).hexdigest()
        return digest.encode("utf-8")


# ── The 13 event classes (1:1 with the 13 SignedAction Literal values) ──
#
# Order mirrors the SignedAction Literal in shards/envelope.py:
#   1. extract           → ExtractEvent
#   2. promote           → PromotionEvent
#   3. demote            → DemotionEvent
#   4. contest           → ContestEvent
#   5. supersede         → SupersessionEvent
#   6. retract           → RetractionEvent
#   7. distinguo         → DistinguoEvent
#   8. role_assertion    → RoleAssertionEvent
#   9. content_edit      → ContentEditEvent
#  10. reparent          → ReparentEvent
#  11. reconcile         → ReconcileEvent
#  12. resolve_contest   → ContestResolutionEvent
#  13. role_revocation   → RoleRevocationEvent (D-13 / F6 closure)


class RoleAssertionEvent(_BaseEvent):
    """Issue a role assertion to a subject DID (GOV-01; PRD §3.1 L105)."""
    action: Literal["role_assertion"] = "role_assertion"
    subject_did: str
    role: RoleName


class RoleRevocationEvent(_BaseEvent):
    """Revoke a previously-asserted role from a subject DID (D-13 / F6).

    Structurally distinct from ``RoleAssertionEvent`` — different ``action``
    pin and different field name (``revoked_role`` not ``role``) — so the
    discriminated union dispatches it to its own class and downstream consumers
    cannot confuse an assertion with a revocation.
    """
    action: Literal["role_revocation"] = "role_revocation"
    subject_did: str
    revoked_role: RoleName


class ExtractEvent(_BaseEvent):
    """First extraction of a shard from a source (GOV-02; PRD §3.1 'extractor')."""
    action: Literal["extract"] = "extract"
    shard_iri: str
    extractor_model: str | None = None


class PromotionEvent(_BaseEvent):
    """Promote a HypothesisShard to an attested status (PRD §3.1.2 L117).

    ``cited_iris`` enforces ``min_length=1`` per D-20: a promotion with zero
    citations is a contradiction in terms (you cannot promote without citing
    something).
    """
    action: Literal["promote"] = "promote"
    shard_iri: str
    new_status: PromotionStatus
    cited_iris: list[str] = Field(min_length=1)


class DemotionEvent(_BaseEvent):
    """Demote an attested shard to hypothesis (PRD §3.1.2).

    The ONLY valid demotion target is ``"hypothesis"`` — per PRD §3.1.2
    a demotion is always demote-to-hypothesis.
    """
    action: Literal["demote"] = "demote"
    shard_iri: str
    new_status: Literal["hypothesis"] = "hypothesis"


class ContestEvent(_BaseEvent):
    """Cast a contest vote against a shard (PRD §3.1.3 L123).

    NOTE: the position-text slot is named ``position_text`` rather than
    ``position`` because ``_BaseEvent.position`` already names the log row;
    avoiding the shadow keeps the discriminated-union round-trip clean.
    """
    action: Literal["contest"] = "contest"
    shard_iri: str
    voter_did: str
    position_text: str


class ContestResolutionEvent(_BaseEvent):
    """Governance-resolved a contested shard via arbiter / distinguo / aporetic
    (GOV-05 — no majority-vote path; PRD §3.1.3 L125).
    """
    action: Literal["resolve_contest"] = "resolve_contest"
    shard_iri: str
    resolution_path: ContestResolutionPath


class DistinguoEvent(_BaseEvent):
    """Propose / confirm a sense-fork (distinguo) over a polysemous shard
    (PRD §6.1 L225; Phase 1 polysemy precedent)."""
    action: Literal["distinguo"] = "distinguo"
    shard_iri: str
    prime_analogate_iri: str
    distinction_kind: str


class SupersessionEvent(_BaseEvent):
    """Assert that ``new_shard_iri`` supersedes ``old_shard_iri``
    (PRD §3.1 / §6.4 supersession chain)."""
    action: Literal["supersede"] = "supersede"
    old_shard_iri: str
    new_shard_iri: str


class RetractionEvent(_BaseEvent):
    """Retraction cascade (PRD §3.1.4 L131; DID-02).

    ``cascade_preview_hash`` commits the preview the operator confirmed at the
    CLI (D-17) — the hash binds this event to the specific preview the
    operator approved, so a retraction cannot be silently re-scoped between
    preview and signing.
    """
    action: Literal["retract"] = "retract"
    shard_iri: str
    cascade_preview_hash: str


class ContentEditEvent(_BaseEvent):
    """Reviewer edited a mutable content field (PRD §6.1 L223;
    Phase 5 ``add_edit`` / ``sign_attestation``)."""
    action: Literal["content_edit"] = "content_edit"
    shard_iri: str
    field_path: str
    rationale: str


class ReparentEvent(_BaseEvent):
    """Reviewer changed a shard's parent / elaboration edge (PRD §6.1 L224)."""
    action: Literal["reparent"] = "reparent"
    shard_iri: str
    new_parent_iri: str


class ReconcileEvent(_BaseEvent):
    """Reviewer set the reconciliation_strategy on a
    ConflictingAuthoritiesShard (PRD §6.1 L226)."""
    action: Literal["reconcile"] = "reconcile"
    shard_iri: str
    strategy: str


# ── The discriminated union (D-06) ──
#
# Pydantic dispatches on the ``action`` discriminator — the per-class Literal
# pin guarantees a payload with ``action="role_revocation"`` parses into a
# ``RoleRevocationEvent`` instance (NOT a ``RoleAssertionEvent``), closing F6
# structurally. Mirrors ``shards/subtypes.Shard`` (the ``shard_type``
# discriminator analog).
GovernanceEvent = Annotated[
    Union[
        RoleAssertionEvent,
        RoleRevocationEvent,
        ExtractEvent,
        PromotionEvent,
        DemotionEvent,
        ContestEvent,
        ContestResolutionEvent,
        DistinguoEvent,
        SupersessionEvent,
        RetractionEvent,
        ContentEditEvent,
        ReparentEvent,
        ReconcileEvent,
    ],
    Field(discriminator="action"),
]


__all__ = [
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

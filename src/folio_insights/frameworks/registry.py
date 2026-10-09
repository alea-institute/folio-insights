"""Per-corpus framework registry with signed admin registration (Phase 9 U2).

Every corpus registry is the starter set (``default_frameworks.json``) plus
the frameworks its corpus admins registered. A registration is:

* **DID-signed by a corpus admin** (PRD §8 P2: "new frameworks get minted per
  corpus and are DID-signed by the corpus admin"). The signer must hold
  ``corpus_admin`` in the corpus governance log at the ledger's commit time,
  checked inside the ledger write transaction (register) and again on load;
  the signing time must sit within ``SIGNING_SKEW`` of the commit time, so
  it cannot be backdated; the Ed25519
  signature covers the JCS-canonical registration (framework, corpus, signer,
  time) under a domain tag. did:key signers verify offline.
* **Persisted per corpus** as an append-only row of the corpus's ledger
  (``storage/proposals.py`` journal table, kind ``framework_register``), with
  an explicit operation ID, so a retried registration commits once. Loading
  re-verifies every signature and the signer's role, and skips (and
  reports) a row that fails, so one bad row cannot brick the registry.

Registration is NOT a governance-log event: adding a ``SignedAction`` value
would widen the shard envelope's ``AttestedSignature.action`` literal, an
envelope shape change Phase 9 rules out (KTD2/R2). The ledger row carries the
signature and is checked against the governance log's roles instead.

``FrameworkGuard`` is the write-time check (R5): installed as
``StorageConfig.shard_validator``, it refuses a shard whose ``framework_id``
is malformed or not registered, before the journal transaction.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jcs
from pydantic import BaseModel, ConfigDict

from folio_insights.governance.clock import SIGNING_SKEW
from folio_insights.models.framework import (
    Framework,
    FrameworkRegistry,
    MalformedFrameworkId,
    UnregisteredFramework,
    check_framework_id,
)

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from folio_insights.governance.log import GovernanceLog
    from folio_insights.shards import ShardEnvelope
    from folio_insights.storage.context import CorpusStorageContext, StorageConfig

LEDGER_KIND = "framework_register"
# How far a registration's signing time may sit from the moment it is
# authorized (register) or committed (load). The admin role is checked at the
# ledger-controlled time, never at a time the signer chose (review P1).
# Shared with governance appends (R17 / KTD12); defined in governance.clock
# and kept importable here.
REGISTRATION_FORMAT = "folio-insights/framework-registration/v1"
_log = logging.getLogger(__name__)
ADMIN_ROLE = "corpus_admin"


class FrameworkRegistrationRefused(PermissionError):
    """The signer is not a corpus admin, or the registration does not verify."""


class FrameworkRegistration(BaseModel):
    """A signed framework registration as the ledger stores it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: str = REGISTRATION_FORMAT
    corpus: str
    framework: Framework
    signer_did: str
    signed_at: datetime
    signature: str  # base64url (no padding) Ed25519 over ``signing_bytes``

    def signing_bytes(self) -> bytes:
        return registration_signing_bytes(
            self.corpus, self.framework, self.signer_did, self.signed_at
        )


def registration_signing_bytes(
    corpus: str, framework: Framework, signer_did: str, signed_at: datetime
) -> bytes:
    """SHA-256 (hex, UTF-8) of the JCS-canonical registration body."""
    body = {
        "format": REGISTRATION_FORMAT,
        "corpus": corpus,
        "framework": framework.model_dump(mode="json"),
        "signer_did": signer_did,
        "signed_at": signed_at.isoformat(),
    }
    return hashlib.sha256(jcs.canonicalize(body)).hexdigest().encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_registration(
    corpus: str,
    framework: Framework,
    *,
    signing_key: Ed25519PrivateKey,
    did: str,
    signed_at: datetime | None = None,
) -> FrameworkRegistration:
    when = signed_at or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    data = registration_signing_bytes(corpus, framework, did, when)
    return FrameworkRegistration(
        corpus=corpus,
        framework=framework,
        signer_did=did,
        signed_at=when,
        signature=_b64(signing_key.sign(data)),
    )


def verify_registration(registration: FrameworkRegistration) -> bool:
    """Offline Ed25519 check for a did:key signer (other DID methods: False)."""
    from cryptography.exceptions import InvalidSignature

    from folio_insights.identity.keys import public_key_from_did_key

    if registration.format != REGISTRATION_FORMAT:
        return False
    try:
        public = public_key_from_did_key(registration.signer_did)
        public.verify(_unb64(registration.signature), registration.signing_bytes())
    except (ValueError, InvalidSignature):
        return False
    return True


async def _is_admin(log: GovernanceLog, corpus: str, did: str, at: datetime) -> bool:
    from folio_insights.governance.roles import active_roles_for_did

    roles = await active_roles_for_did(corpus, did, at, log=log)
    return ADMIN_ROLE in roles


@dataclass(frozen=True)
class RefusedRegistration:
    """A framework-registration ledger row that load did not register."""

    position: int
    op_id: str
    reason: str


@dataclass(frozen=True)
class RegistryLoad:
    """``load_registry_report``'s result: the registry plus every ledger row
    it was built from (``accepted``) and every row it skipped (``refused``)."""

    registry: FrameworkRegistry
    accepted: tuple[FrameworkRegistration, ...]
    refused: tuple[RefusedRegistration, ...]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def load_registry_report(ctx: CorpusStorageContext) -> RegistryLoad:
    """The corpus registry with a diagnostic for every ledger row it skipped.

    A ledger row registers its framework only when it parses, is for this
    corpus, its signature verifies, its ``signed_at`` sits within
    ``SIGNING_SKEW`` of the row's ledger commit time, its signer held
    ``corpus_admin`` at that commit time (windowed by governance commit
    times), and its framework fits the registry (known parent, no
    conflicting definition). Any other row is skipped and listed in
    ``refused`` with the reason: it never takes effect, and one bad row
    (for example a registration that raced a revocation before
    registrations were authorized in-transaction) cannot make the corpus
    registry unloadable.
    """
    from pydantic import ValidationError

    registry = FrameworkRegistry.with_defaults()
    accepted: list[FrameworkRegistration] = []
    refused: list[RefusedRegistration] = []
    for entry in await ctx.proposals.entries():
        if entry.kind != LEDGER_KIND:
            continue

        def refuse(reason: str) -> None:
            refused.append(RefusedRegistration(entry.position, entry.op_id, reason))

        try:
            registration = FrameworkRegistration.model_validate(entry.payload)
        except ValidationError:
            refuse("the row is not a valid framework registration")
            continue
        if registration.corpus != ctx.corpus or not verify_registration(registration):
            refuse("framework registration does not verify for this corpus")
            continue
        committed = _as_utc(datetime.fromisoformat(entry.committed_at))
        if abs(registration.signed_at - committed) > SIGNING_SKEW:
            refuse(f"signed_at is not within {SIGNING_SKEW} of the ledger commit time")
            continue
        # The role is checked at the ledger's commit time, not the signer's clock.
        if not await _is_admin(ctx.governance, ctx.corpus, registration.signer_did, committed):
            refuse("signer was not a corpus admin when the registration was committed")
            continue
        try:
            registry.register(registration.framework)
        except ValueError as exc:
            refuse(f"framework does not fit the registry: {exc}")
            continue
        accepted.append(registration)
    return RegistryLoad(registry, tuple(accepted), tuple(refused))


async def load_registry(ctx: CorpusStorageContext) -> FrameworkRegistry:
    """The corpus registry: the starter set plus every verified registration.

    A ledger row that does not verify, or whose signer was not a corpus admin
    when it was committed, is skipped and reported (one ``WARNING`` per row on
    this module's logger; ``load_registry_report`` returns them) rather than
    raised: it never takes effect, and the registry is never quietly smaller
    than its ledger says.
    """
    load = await load_registry_report(ctx)
    for row in load.refused:
        _log.warning(
            "corpus %r: framework registration at ledger position %d (op %r) skipped: %s",
            ctx.corpus, row.position, row.op_id, row.reason,
        )
    return load.registry


async def register_framework(
    ctx: CorpusStorageContext,
    framework: Framework,
    *,
    signing_key: Ed25519PrivateKey,
    did: str,
    op_id: str | None = None,
) -> FrameworkRegistration:
    """Register ``framework`` in ``ctx``'s corpus, signed by a corpus admin.

    Refuses (nothing appended) when the signer is not a corpus admin at the
    ledger commit time, when the parent is unregistered, or when the ID is
    already registered with a different definition. Re-registering the
    identical framework returns the committed registration (``op_id``
    defaults to ``framework:<id>``).

    Time (R17 / KTD12): there is no caller-chosen time. The registration is
    signed at the current time; the authoritative admin check runs INSIDE the
    proposal-ledger write transaction, at the server commit time the row
    records, against governance history windowed by commit times, so a
    revocation committed after the pre-check still refuses the write.
    """
    # Advisory pre-check at the wall clock: a clear refusal before signing.
    # The in-transaction check below is the one that decides.
    if not await _is_admin(ctx.governance, ctx.corpus, did, datetime.now(UTC)):
        raise FrameworkRegistrationRefused(
            f"{did} does not hold {ADMIN_ROLE!r} in corpus {ctx.corpus!r}; "
            "only a corpus admin can register a framework"
        )
    load = await load_registry_report(ctx)
    existing = load.registry.get(framework.id)
    if existing is not None and existing != framework:
        raise ValueError(f"framework {framework.id!r} is already registered differently")
    if existing is not None:
        # Identical re-registration: return the committed row, append nothing.
        for accepted in load.accepted:
            if accepted.framework.id == framework.id:
                return accepted
        raise ValueError(f"framework {framework.id!r} is already in the starter set")
    load.registry.copy().register(framework)  # parent / conflict checks before signing
    registration = sign_registration(ctx.corpus, framework, signing_key=signing_key, did=did)
    if not verify_registration(registration):
        raise FrameworkRegistrationRefused("the registration signature does not verify")

    async def authorize(snapshot: GovernanceLog, server_time: datetime) -> None:
        if abs(registration.signed_at - server_time) > SIGNING_SKEW:
            raise FrameworkRegistrationRefused(
                f"registration signed at {registration.signed_at.isoformat()} is not "
                f"within {SIGNING_SKEW} of the ledger commit time "
                f"{server_time.isoformat()}; nothing was appended"
            )
        if not await _is_admin(snapshot, ctx.corpus, did, server_time):
            raise FrameworkRegistrationRefused(
                f"{did} does not hold {ADMIN_ROLE!r} in corpus {ctx.corpus!r} at the "
                f"ledger commit time {server_time.isoformat()}; nothing was appended"
            )

    entry, _replayed = await ctx.proposals._append_authorized(
        LEDGER_KIND,
        registration.model_dump(mode="json"),
        op_id=op_id or f"framework:{framework.id}",
        authorize=authorize,
    )
    return FrameworkRegistration.model_validate(entry.payload)


class FrameworkGuard:
    """Write-time framework check for ``StorageConfig.shard_validator`` (R5).

    Refuses a shard whose ``framework_id`` does not match the ID pattern
    (``MalformedFrameworkId``) or is not in ``registry``
    (``UnregisteredFramework``). The registry starts as the starter set and
    is replaced with the corpus registry by ``refresh``.
    """

    def __init__(self, registry: FrameworkRegistry | None = None) -> None:
        self.registry = registry if registry is not None else FrameworkRegistry.with_defaults()

    def __call__(self, shard: ShardEnvelope) -> None:
        framework_id = shard.framework_id
        check_framework_id(framework_id)
        if framework_id not in self.registry:
            raise UnregisteredFramework(
                f"shard {shard.shard_iri}: framework {framework_id!r} is not registered "
                "in this corpus; register it first (folio-insights framework register)"
            )

    async def refresh(self, ctx: CorpusStorageContext) -> FrameworkRegistry:
        self.registry = await load_registry(ctx)
        return self.registry


def guarded_config(
    guard: FrameworkGuard, base: StorageConfig | None = None, **overrides: Any
) -> StorageConfig:
    """A ``StorageConfig`` whose shard hook runs ``guard`` (after any hook
    ``base`` already had)."""
    from dataclasses import replace

    from folio_insights.storage.context import StorageConfig

    config = base or StorageConfig()
    previous = config.shard_validator

    def hook(shard: ShardEnvelope) -> None:
        if previous is not None:
            previous(shard)
        guard(shard)

    return replace(config, shard_validator=hook, **overrides)


async def open_framework_checked_context(
    root: Path | str,
    corpus: str,
    *,
    config: StorageConfig | None = None,
) -> tuple[CorpusStorageContext, FrameworkGuard]:
    """Open a corpus context whose every shard write checks ``framework_id``
    against the corpus registry (the context Phase 10's minter writes through)."""
    from folio_insights.storage import CorpusStorageContext

    guard = FrameworkGuard()
    ctx = await CorpusStorageContext.open(Path(root), corpus, config=guarded_config(guard, config))
    try:
        await guard.refresh(ctx)
    except BaseException:
        await ctx.close()
        raise
    return ctx, guard


def registration_summary(registration: FrameworkRegistration) -> Mapping[str, Any]:
    return {
        "framework": registration.framework.model_dump(mode="json"),
        "signer_did": registration.signer_did,
        "signed_at": registration.signed_at.isoformat(),
    }


__all__ = [
    "ADMIN_ROLE",
    "FrameworkGuard",
    "FrameworkRegistration",
    "FrameworkRegistrationRefused",
    "LEDGER_KIND",
    "MalformedFrameworkId",
    "RefusedRegistration",
    "RegistryLoad",
    "SIGNING_SKEW",
    "UnregisteredFramework",
    "guarded_config",
    "load_registry",
    "load_registry_report",
    "open_framework_checked_context",
    "register_framework",
    "registration_signing_bytes",
    "registration_summary",
    "sign_registration",
    "verify_registration",
]

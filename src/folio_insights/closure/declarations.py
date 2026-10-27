"""Corpus-admin closure declarations in the existing append-only metadata ledger.

A declaration replaces the whole prior contract for its scope. Its signed operation
ID prevents moving a superseded artifact to a fresh ledger position, and its main
journal digest prevents carrying completeness across a changed corpus. Historical
retries return their original record without making that declaration current again.
"""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import jcs
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from folio_insights.frameworks.registry import _is_admin
from folio_insights.governance.clock import SIGNING_SKEW, parse_committed_at
from folio_insights.proposals.signed_decisions import validate_corpus_id
from folio_insights.query.closed_world import ClosedWorldScope, _iri
from folio_insights.storage.errors import JournalStateChanged, ProjectionRecoveryPending
from folio_insights.storage.projection import (
    CHAIN_GENESIS, chain_over, chain_step, corpus_graph, governance_graph, row_triples,
)
from folio_insights.storage.proposals import MAX_OP_ID_CHARS, ProposalLedgerEntry

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from folio_insights.governance.log import GovernanceLog
    from folio_insights.storage.context import CorpusStorageContext

LEDGER_KIND = "closure_declare"
DECLARATION_FORMAT = "folio-insights/closure-declaration/v1"


class ClosureDeclarationRefused(ValueError):
    """The declaration is not valid, authorized or bound to this corpus."""


class ClosureDeclaration(BaseModel):
    """The signed, complete contract and membership for one corpus scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["folio-insights/closure-declaration/v1"] = DECLARATION_FORMAT
    op_id: str = Field(min_length=1, max_length=MAX_OP_ID_CHARS)
    corpus: str
    scope_iri: str
    closed_classes: tuple[str, ...] = ()
    closed_properties: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    main_head: StrictInt = Field(ge=-1)
    main_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    signer_did: str
    signed_at: datetime
    signature: str

    @field_validator("corpus")
    @classmethod
    def _corpus(cls, value: str) -> str:
        return validate_corpus_id(value)

    @field_validator("op_id")
    @classmethod
    def _op_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("op_id must not be blank")
        return value

    @field_validator("scope_iri")
    @classmethod
    def _scope_iri(cls, value: str) -> str:
        _iri(value)
        return value

    @field_validator("closed_classes", "closed_properties", "members")
    @classmethod
    def _iris(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _iri(value)
        if len(values) != len(set(values)):
            raise ValueError("declaration IRI lists must not contain duplicates")
        return values

    @field_validator("signed_at")
    @classmethod
    def _signed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("signed_at must carry a time zone")
        return value.astimezone(UTC)

    def signing_bytes(self) -> bytes:
        body = self.model_dump(mode="json", exclude={"signature"})
        return hashlib.sha256(jcs.canonicalize(body)).hexdigest().encode("utf-8")

    @property
    def scope(self) -> ClosedWorldScope:
        return ClosedWorldScope(self.scope_iri, frozenset(self.closed_classes),
                                frozenset(self.closed_properties))


def sign_declaration(
    corpus: str,
    scope: ClosedWorldScope,
    *,
    members: Iterable[str],
    main_head: int,
    main_digest: str,
    op_id: str,
    signing_key: Ed25519PrivateKey,
    did: str,
    signed_at: datetime | None = None,
) -> ClosureDeclaration:
    """Create an offline signed artifact; neither registers a key nor writes storage."""
    declaration = ClosureDeclaration(
        corpus=corpus, scope_iri=scope.scope_iri,
        closed_classes=tuple(sorted(scope.closed_classes)),
        closed_properties=tuple(sorted(scope.closed_properties)),
        members=tuple(sorted(set(members))), main_head=main_head, main_digest=main_digest,
        op_id=op_id, signer_did=did, signed_at=signed_at or datetime.now(UTC), signature="",
    )
    signature = base64.urlsafe_b64encode(signing_key.sign(declaration.signing_bytes()))
    return declaration.model_copy(update={"signature": signature.rstrip(b"=").decode("ascii")})


def verify_declaration(declaration: ClosureDeclaration) -> bool:
    """Offline did:key verification, including revalidation of bypassed model fields."""
    from cryptography.exceptions import InvalidSignature

    from folio_insights.identity.keys import public_key_from_did_key

    try:
        checked = ClosureDeclaration.model_validate(declaration.model_dump(mode="json"))
        signature = base64.urlsafe_b64decode(checked.signature + "=" * (-len(checked.signature) % 4))
        public_key_from_did_key(checked.signer_did).verify(signature, checked.signing_bytes())
    except (ValueError, TypeError, InvalidSignature):
        return False
    return True


async def capture_main_state(
    ctx: CorpusStorageContext, *, upto: int | None = None,
) -> tuple[int, str]:
    """Capture one immutable main-journal prefix, without touching the projection."""
    ctx._ensure_open()
    head = await ctx._journal.head(ctx.corpus) if upto is None else upto
    rows = await ctx._journal.chain_rows(ctx.corpus, after=-1, upto=head)
    if [row.position for row in rows] != list(range(head + 1)):
        raise ClosureDeclarationRefused("main journal prefix is not contiguous")
    return head, chain_over(CHAIN_GENESIS, rows)


@dataclass(frozen=True)
class RefusedDeclaration:
    position: int
    reason: str


@dataclass(frozen=True)
class DeclarationLoad:
    main_head: int
    main_digest: str
    ledger_head: int
    ledger_digest: str
    accepted: tuple[ClosureDeclaration, ...]
    active: tuple[ClosureDeclaration, ...]
    refused: tuple[RefusedDeclaration, ...]


async def _members_at(ctx: CorpusStorageContext, head: int) -> set[str]:
    """Subjects of the captured ABox/governance only; derived closure cannot bootstrap itself."""
    from pyoxigraph import NamedNode

    rows = await ctx._journal.latest_shards(ctx.corpus, upto=head)
    rows += await ctx._journal.governance_rows(ctx.corpus, upto=head)
    return {subject.value for row in rows for subject, _, _ in row_triples(ctx.corpus, row)[2]
            if isinstance(subject, NamedNode)}


async def load_declarations(
    ctx: CorpusStorageContext,
    *,
    main_head: int | None = None,
    main_digest: str | None = None,
    entries: Sequence[ProposalLedgerEntry] | None = None,
    known_members: Iterable[str] | None = None,
) -> DeclarationLoad:
    """Fold one captured ledger prefix against one bounded main-journal snapshot.

    Projection adapters pass their watermark/digest and captured entries. No read
    in the fold follows a moving governance head. A later declaration replaces the
    prior scope even when its snapshot is no longer active. ``known_members``, when
    supplied by that adapter, contains only ABox/governance subjects at this head.
    """
    from folio_insights.governance.log import InMemoryGovernanceLog
    from folio_insights.storage.context import _event_from_row

    head, digest = await capture_main_state(ctx, upto=main_head)
    if main_digest is not None and main_digest != digest:
        raise ClosureDeclarationRefused("captured main journal digest does not match")
    captured = tuple(await ctx.proposals.entries()) if entries is None else tuple(entries)
    if [entry.position for entry in captured] != list(range(len(captured))):
        raise ClosureDeclarationRefused("metadata ledger prefix is not contiguous")
    for entry in captured:
        if hashlib.sha256(jcs.canonicalize(entry.payload)).hexdigest() != entry.payload_sha256:
            raise ClosureDeclarationRefused("metadata ledger payload digest does not match")
    ledger_digest = hashlib.sha256(jcs.canonicalize([
        [entry.position, entry.op_id, entry.kind, entry.payload_sha256,
         entry.committed_at, entry.record_schema_version] for entry in captured
    ])).hexdigest()
    rows = await ctx._journal.governance_rows(ctx.corpus, upto=head)
    history = InMemoryGovernanceLog._from_history(
        ctx.corpus, [_event_from_row(row) for row in rows],
        committed_at=[parse_committed_at(row.committed_at) for row in rows],
    )
    accepted: list[ClosureDeclaration] = []
    refused: list[RefusedDeclaration] = []
    latest: dict[str, ClosureDeclaration | None] = {}
    chain_rows = await ctx._journal.chain_rows(ctx.corpus, after=-1, upto=head)
    prefixes = {-1: (CHAIN_GENESIS, datetime.min.replace(tzinfo=UTC))}
    chain, last_commit = prefixes[-1]
    for row in chain_rows:
        chain = chain_step(chain, row.position, row.op_id, row.payload_sha256, row.committed_at)
        last_commit = max(last_commit, parse_committed_at(row.committed_at))
        prefixes[row.position] = chain, last_commit
    if prefixes.get(head, (None,))[0] != digest:
        raise ClosureDeclarationRefused("main journal prefix changed during capture")
    member_sets = {} if known_members is None else {head: set(known_members)}
    for entry in captured:
        if entry.kind != LEDGER_KIND:
            continue
        declaration = None
        try:
            declaration = ClosureDeclaration.model_validate(entry.payload)
            if declaration.corpus == ctx.corpus:
                # A malformed replacement cannot silently reactivate an earlier,
                # broader contract for this scope.
                latest[declaration.scope_iri] = None
            if (declaration.corpus != ctx.corpus or declaration.op_id != entry.op_id
                    or not verify_declaration(declaration)):
                raise ClosureDeclarationRefused("declaration does not verify for this ledger row")
            committed = parse_committed_at(entry.committed_at)
            prefix = prefixes.get(declaration.main_head)
            if (prefix is None or prefix[0] != declaration.main_digest
                    or prefix[1] > committed):
                raise ClosureDeclarationRefused("declaration does not name a committed main prefix")
            await _authorize(declaration, history, committed)
            if declaration.main_head not in member_sets:
                member_sets[declaration.main_head] = await _members_at(ctx, declaration.main_head)
            if not set(declaration.members) <= member_sets[declaration.main_head]:
                raise ClosureDeclarationRefused("declaration members are absent from its main prefix")
        except (ValueError, TypeError):
            if declaration is None:
                # The damaged row's scope is unknown: retaining any earlier
                # contract could restore a completeness claim it withdrew.
                latest.clear()
            refused.append(RefusedDeclaration(entry.position, "invalid_or_unauthorized_declaration"))
            continue
        accepted.append(declaration)
        latest[declaration.scope_iri] = declaration
    active = tuple(declaration for _, declaration in sorted(latest.items())
                   if declaration is not None
                   and (declaration.main_head, declaration.main_digest) == (head, digest))
    return DeclarationLoad(head, digest, len(captured) - 1, ledger_digest,
                           tuple(accepted), active, tuple(refused))


async def _authorize(
    declaration: ClosureDeclaration, history: GovernanceLog, committed: datetime,
) -> None:
    if abs(declaration.signed_at - committed) > SIGNING_SKEW:
        raise ClosureDeclarationRefused("declaration signing time is outside the commit-time skew")
    if not await _is_admin(history, declaration.corpus, declaration.signer_did, committed):
        raise ClosureDeclarationRefused("declaration signer is not a corpus administrator")


async def submit_declaration(
    ctx: CorpusStorageContext, declaration: ClosureDeclaration, *, op_id: str | None = None,
) -> ProposalLedgerEntry:
    """Admit a signed declaration once, then recover its derived projection.

    Replays bypass freshness/current-state checks inside the ledger transaction,
    but never signature or signed-operation identity checks. Materialization failure
    uses the storage layer's committed/recovery-pending outcome.
    """
    if (op_id is not None and op_id != declaration.op_id
            or declaration.corpus != ctx.corpus or not verify_declaration(declaration)):
        raise ClosureDeclarationRefused("declaration signature, corpus or operation ID does not match")
    existing = next((entry for entry in await ctx.proposals.entries()
                     if entry.op_id == declaration.op_id), None)
    if existing is None:
        head, digest = await capture_main_state(ctx)
        if (head, digest) != (declaration.main_head, declaration.main_digest):
            raise JournalStateChanged(expected=declaration.main_head, actual=head)
        if declaration.members:
            values = " ".join(_iri(member) for member in declaration.members)
            graphs = f"{corpus_graph(ctx.corpus)} {governance_graph(ctx.corpus)}"
            rows = await ctx.query(
                f"SELECT DISTINCT ?member WHERE {{ VALUES ?member {{ {values} }} "
                f"VALUES ?graph {{ {graphs} }} GRAPH ?graph {{ ?member ?p ?o }} }}"
            )
            if {row["member"].value for row in rows} != set(declaration.members):
                raise ClosureDeclarationRefused("declaration includes members absent from this corpus")
    elif (existing.kind == LEDGER_KIND
          and existing.payload == declaration.model_dump(mode="json")
          and declaration not in (await load_declarations(ctx)).accepted):
        raise ClosureDeclarationRefused("stored declaration was not authorized at admission")

    async def authorize(history: GovernanceLog, committed: datetime) -> None:
        await _authorize(declaration, history, committed)

    entry, _replayed = await ctx.proposals._append_authorized(
        LEDGER_KIND, declaration.model_dump(mode="json"), op_id=declaration.op_id,
        authorize=authorize, expected_main_state=(declaration.main_head, declaration.main_digest),
    )
    try:
        await ctx._after_commit(entry.op_id, entry.position)
    except ProjectionRecoveryPending as exc:
        raise ProjectionRecoveryPending(
            "closure declaration committed to the metadata ledger; projection recovery pending. "
            "Reopen the corpus and retry the same signed artifact",
            op_id=entry.op_id, position=entry.position,
        ) from exc
    return entry


__all__ = [
    "DECLARATION_FORMAT", "LEDGER_KIND", "ClosureDeclaration", "ClosureDeclarationRefused",
    "DeclarationLoad", "RefusedDeclaration", "capture_main_state", "load_declarations",
    "sign_declaration", "submit_declaration", "verify_declaration",
]

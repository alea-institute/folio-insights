"""``governance supersede`` subcommand (D-15, D-16, D-19; PRD §21.9).

Supersede an old shard with a new shard. Order of operations (D-19):

  1. Parse CLI args + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "supersede", corpus, log=log)`` — D-19 first step.
  3. ``await validate_supersession(event, store=store)`` — D-16 standalone validator.
  4. Sign + ``log.append`` — SHACL belt at log layer.
  5. Emit the persisted event as JSON.

**D-16 boundary:** this module imports ONLY from ``governance.supersede``
(its own module's event class + validator) — NOT from contest.py or
resolve_contest.py.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.supersede import (
    SupersessionEvent,
    validate_supersession,
)
from folio_insights.identity.keys import KEY_PATH


@click.command(name="supersede")
@click.argument("old_shard_iri")
@click.argument("new_shard_iri")
@click.option(
    "--corpus",
    required=True,
    help="Per-corpus governance log to append into.",
)
@click.option(
    "--key-path",
    type=click.Path(path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help="Local ed25519 keystore JWK (DID-06).",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip the post-preview confirmation (scripted use).",
)
def supersede_cmd(
    old_shard_iri: str,
    new_shard_iri: str,
    corpus: str,
    key_path: Path,
    yes: bool,
) -> None:
    """Supersede an old shard with a new shard (PRD §21.9 — distinct from retraction; valid-time semantics)."""
    from folio_insights.governance.cli._signing import sign_and_verify_event
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.governance.log import InvalidSignature
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.revision.store import InMemoryShardStore
    from folio_insights.shards.envelope import AttestedSignature

    log = GOVERNANCE_LOG
    store = InMemoryShardStore()  # Phase 13 wires the persistent backend.

    try:
        sk = load_signing_key(key_path)
    except FileNotFoundError:
        click.echo(
            f"no signing key at {key_path}: run `folio-insights did generate` first.",
            err=True,
        )
        sys.exit(1)
    except Exception as exc:
        click.echo(f"no signing key (load failed): {exc}", err=True)
        sys.exit(1)
    signer_did = _derive_didkey_from_signing_key(sk)

    async def _run() -> None:
        # ── D-19 FIRST STEP ──
        decision = await authorize(signer_did, "supersede", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(f"unauthorized (denied: {decision.reason})", err=True)
            sys.exit(1)
        assert isinstance(decision, Allow)

        now = datetime.now(UTC)
        placeholder_sig = AttestedSignature(
            did=signer_did,
            action="supersede",
            signed_at=now,
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            verified=None,
        )
        event = SupersessionEvent(
            corpus=corpus,
            signature=placeholder_sig,
            old_shard_iri=old_shard_iri,
            new_shard_iri=new_shard_iri,
        )
        try:
            await validate_supersession(event, store=store)
        except ValueError as exc:
            click.echo(f"validate_supersession refused: {exc}", err=True)
            sys.exit(1)

        # CR-01: sign + verify-attestation round-trip via the shared helper.
        try:
            sig = await sign_and_verify_event(
                event,
                signing_key=sk,
                did=signer_did,
                action="supersede",
                signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
                did_doc_snapshot_at=None,
                now=now,
                cache=InMemoryDidDocCache(),
            )
        except InvalidSignature as exc:
            click.echo(f"verify_attestation refused: {exc}", err=True)
            sys.exit(1)
        signed_event = event.model_copy(update={"signature": sig})
        try:
            persisted = await log.append(signed_event)
        except Exception as exc:
            click.echo(f"log.append refused: {type(exc).__name__}: {exc}", err=True)
            sys.exit(1)
        click.echo(persisted.model_dump_json(indent=2))

    asyncio.run(_run())


__all__ = ["supersede_cmd"]

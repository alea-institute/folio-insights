"""``governance contest`` subcommand (D-15, D-16, D-19; PRD §21.8).

Record a contest on a shard. Order of operations (D-19):

  1. Parse CLI args + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "contest", corpus, log=log)`` — D-19 first step.
  3. ``validate_contest(event)`` — field-level defense-in-depth.
  4. Sign over the canonical payload + ``log.append`` — SHACL belt at log layer.
  5. Emit the persisted event as JSON.

**D-16 boundary:** this module imports ONLY from ``governance.contest`` (its
own module's event class + validator) — NOT from supersede.py or
resolve_contest.py. The D-16 grep-guard regression test fails CI if anyone
tries to share code across the three CLI commands.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.contest import ContestEvent, validate_contest
from folio_insights.identity.keys import KEY_PATH


@click.command(name="contest")
@click.argument("shard_iri")
@click.option(
    "--voter-did",
    required=False,
    default=None,
    help="The DID casting the contest. Defaults to the signer DID (self-vote).",
)
@click.option(
    "--position-text",
    required=True,
    help="The contesting position (PRD §21.8 — a contest carries a position).",
)
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
def contest_cmd(
    shard_iri: str,
    voter_did: str | None,
    position_text: str,
    corpus: str,
    key_path: Path,
    yes: bool,
) -> None:
    """Record a contest on a shard (PRD §21.8 — distinct from supersession and retraction)."""
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.identity.signer import sign_attestation
    from folio_insights.shards.envelope import AttestedSignature

    log = GOVERNANCE_LOG

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
    effective_voter = voter_did or signer_did

    async def _run() -> None:
        # ── D-19 FIRST STEP ──
        decision = await authorize(signer_did, "contest", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(f"unauthorized (denied: {decision.reason})", err=True)
            sys.exit(1)
        assert isinstance(decision, Allow)

        now = datetime.now(UTC)
        placeholder_sig = AttestedSignature(
            did=signer_did,
            action="contest",
            signed_at=now,
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            verified=None,
        )
        event = ContestEvent(
            corpus=corpus,
            signature=placeholder_sig,
            shard_iri=shard_iri,
            voter_did=effective_voter,
            position_text=position_text,
        )
        # Field-level defense-in-depth (D-16 — contest.py owns its validator).
        try:
            validate_contest(event)
        except ValueError as exc:
            click.echo(f"validate_contest refused: {exc}", err=True)
            sys.exit(1)

        payload_hash = event.signature_payload().decode("utf-8")
        sig = sign_attestation(
            content_hash=payload_hash,
            signing_key=sk,
            did=signer_did,
            action="contest",
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            now=now,
        )
        signed_event = event.model_copy(update={"signature": sig})
        try:
            persisted = await log.append(signed_event)
        except Exception as exc:
            click.echo(f"log.append refused: {type(exc).__name__}: {exc}", err=True)
            sys.exit(1)
        click.echo(persisted.model_dump_json(indent=2))

    asyncio.run(_run())


__all__ = ["contest_cmd"]

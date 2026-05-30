"""``governance revoke-role`` subcommand (D-11, D-13, D-15, D-19).

Revoke a previously-asserted role from a subject DID. Order (D-19):

  1. Parse + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "role_revocation", corpus, log=log)``.
  3. Build a ``RoleRevocationEvent``; sign over the canonical payload.
  4. ``await log.append(event)`` — log-layer D-11 lockout suspenders +
     SHACL belt. ``WouldLockoutCorpusAdmin`` surfaces verbatim to stderr.
  5. Emit the persisted event as JSON.

D-11 lockout refusal carries the verbatim error string locked by 07-04a:

    revocation would leave the corpus with 0 active corpus_admins;
    appoint a successor first

This CLI catches the exception and re-emits it to stderr unchanged so a
contestant cannot disguise the lockout refusal as a generic failure.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.events import RoleRevocationEvent
from folio_insights.governance.log import WouldLockoutCorpusAdmin
from folio_insights.identity.keys import KEY_PATH


@click.command(name="revoke-role")
@click.argument("subject_did")
@click.option(
    "--revoked-role",
    required=True,
    type=click.Choice(
        ["extractor", "reviewer", "arbiter", "corpus_admin"],
        case_sensitive=True,
    ),
    help="The role being revoked (D-13 — 4-Literal lock).",
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
def role_revoke_cmd(
    subject_did: str,
    revoked_role: str,
    corpus: str,
    key_path: Path,
    yes: bool,
) -> None:
    """Revoke a previously-asserted role (corpus_admin signs; D-11 lockout refused)."""
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

    async def _run() -> None:
        # ── D-19 FIRST STEP ──
        decision = await authorize(signer_did, "role_revocation", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(
                f"unauthorized (denied: {decision.reason})", err=True
            )
            sys.exit(1)
        assert isinstance(decision, Allow)

        now = datetime.now(UTC)
        placeholder_sig = AttestedSignature(
            did=signer_did,
            action="role_revocation",
            signed_at=now,
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            verified=None,
        )
        event = RoleRevocationEvent(
            corpus=corpus,
            signature=placeholder_sig,
            subject_did=subject_did,
            revoked_role=revoked_role,  # type: ignore[arg-type]
        )
        payload_hash = event.signature_payload().decode("utf-8")
        sig = sign_attestation(
            content_hash=payload_hash,
            signing_key=sk,
            did=signer_did,
            action="role_revocation",  # type: ignore[arg-type]  # 13th Literal added in Phase 7
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            now=now,
        )
        signed_event = event.model_copy(update={"signature": sig})
        try:
            persisted = await log.append(signed_event)
        except WouldLockoutCorpusAdmin as exc:
            # D-11 verbatim error string — re-emit unchanged so the contract
            # the test asserts character-for-character holds at the CLI layer.
            click.echo(str(exc), err=True)
            sys.exit(1)
        except Exception as exc:
            click.echo(
                f"log.append refused: {type(exc).__name__}: {exc}", err=True
            )
            sys.exit(1)
        click.echo(persisted.model_dump_json(indent=2))

    asyncio.run(_run())


__all__ = ["role_revoke_cmd"]

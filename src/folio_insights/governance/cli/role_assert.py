"""``governance assert-role`` subcommand (D-15, D-19).

Issue a role assertion to a subject DID. Order (D-19):

  1. Parse + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "role_assertion", corpus, log=log)``.
  3. Build a ``RoleAssertionEvent``; sign over the canonical payload.
  4. ``await log.append(event)`` — log-layer code suspenders + SHACL belt.
  5. Emit the persisted event as JSON.

Authorize will Deny unless the signer holds ``corpus_admin`` at the current
asof (the ``_ACTION_PERMISSIONS`` table grants ``role_assertion`` to
corpus_admin only). The genesis carve-out fires only for
``action="corpus_init"`` — this command uses ``action="role_assertion"`` and
is therefore subject to the standard role-based gate.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.identity.keys import KEY_PATH


@click.command(name="assert-role")
@click.argument("subject_did")
@click.option(
    "--role",
    required=True,
    type=click.Choice(
        ["extractor", "reviewer", "arbiter", "corpus_admin"],
        case_sensitive=True,
    ),
    help="The role to assert (D-13 — 4-Literal lock).",
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
def role_assert_cmd(
    subject_did: str,
    role: str,
    corpus: str,
    key_path: Path,
    yes: bool,
) -> None:
    """Issue a role assertion (corpus_admin signs)."""
    from folio_insights.governance.cli._signing import sign_and_verify_event
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.governance.log import InvalidSignature
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
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
        decision = await authorize(signer_did, "role_assertion", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(
                f"unauthorized (denied: {decision.reason})", err=True
            )
            sys.exit(1)
        assert isinstance(decision, Allow)

        now = datetime.now(UTC)
        placeholder_sig = AttestedSignature(
            did=signer_did,
            action="role_assertion",
            signed_at=now,
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            verified=None,
        )
        event = RoleAssertionEvent(
            corpus=corpus,
            signature=placeholder_sig,
            subject_did=subject_did,
            role=role,  # type: ignore[arg-type]
        )
        # CR-01: sign + verify-attestation round-trip via the shared helper.
        # InMemoryDidDocCache() is empty (did:key signers resolve locally
        # without a cache hit; verify_attestation falls through to the
        # default resolver which decodes the did:key public key inline).
        try:
            sig = await sign_and_verify_event(
                event,
                signing_key=sk,
                did=signer_did,
                action="role_assertion",
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
            click.echo(
                f"log.append refused: {type(exc).__name__}: {exc}", err=True
            )
            sys.exit(1)
        click.echo(persisted.model_dump_json(indent=2))

    asyncio.run(_run())


__all__ = ["role_assert_cmd"]

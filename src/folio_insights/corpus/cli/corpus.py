"""``corpus init`` subcommand (CORPUS-05, D-10, D-19; Issue #3 closure).

Bootstrap a corpus by writing genesis row 0: a self-signed corpus_admin
RoleAssertion bound to ``--admin-did``. Order (D-19 — no CLI exemption):

  1. Parse + load signing key + derive signer_did from the key.
  2. **Bind check (defense in depth)**: if ``signer_did != admin_did``, refuse
     at the CLI BEFORE calling authorize() — surfaces a clearer error than
     authorize()'s generic ``genesis_mismatch`` Deny.
  3. ``await authorize(signer_did, action="corpus_init", corpus, log=log,
     admin_did=admin_did)`` — the genesis carve-out is STRUCTURAL inside
     authorize() per 07-04a (Issue #3 closure). The carve-out Allows only
     when log is empty AND signer == admin_did.
  4. Build the genesis RoleAssertionEvent (position=0, subject=admin_did,
     role=corpus_admin); sign with sign_attestation over the canonical
     signature_payload(); attach the signature.
  5. ``await log.append(event)`` — log-layer carve-out recognizes the same
     (position=0 AND role=corpus_admin AND signer=subject) shape and skips
     the signer-must-be-admin gate (defense in depth — 07-04a).
  6. Emit the persisted event as JSON.

Phase 7 caveat: the governance log this CLI writes into is the process-local
``InMemoryGovernanceLog`` singleton at
``folio_insights.governance.cli._state.GOVERNANCE_LOG``. Phase 13 wires
``<corpus>/.governance.sqlite`` behind the GovernanceLog Protocol per D-07
without touching this command's source.
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


@click.command(name="init")
@click.argument("corpus_name")
@click.option(
    "--admin-did",
    required=True,
    help=(
        "DID to grant corpus_admin in the genesis row. REQUIRED — no default "
        "per RESEARCH Open Question 1 (refuse-to-default discipline)."
    ),
)
@click.option(
    "--key-path",
    type=click.Path(path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help="Local ed25519 keystore JWK (DID-06). MUST derive --admin-did.",
)
def corpus_init_cmd(
    corpus_name: str,
    admin_did: str,
    key_path: Path,
) -> None:
    """Bootstrap a corpus: write the genesis self-signed corpus_admin row 0."""
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

    # ── Defense-in-depth bind check ──
    # Surface a clearer error than authorize()'s generic ``genesis_mismatch``
    # when the operator passed a --admin-did that doesn't derive from the
    # --key-path. authorize() will ALSO refuse this case (07-04a); the CLI
    # check just makes the diagnostic friendlier.
    if signer_did != admin_did:
        click.echo(
            f"--admin-did ({admin_did!r}) does not match the DID derived from "
            f"--key-path ({signer_did!r}).",
            err=True,
        )
        sys.exit(1)

    async def _run() -> None:
        # ── D-19 FIRST STEP — Issue #3 closure: NO CLI exemption ──
        decision = await authorize(
            signer_did,
            action="corpus_init",
            corpus=corpus_name,
            log=log,
            admin_did=admin_did,
        )
        if isinstance(decision, Deny):
            click.echo(f"unauthorized (denied: {decision.reason})", err=True)
            sys.exit(1)
        assert isinstance(decision, Allow)

        now = datetime.now(UTC)
        # Build the genesis event with a placeholder signature so we can
        # compute the canonical payload hash, then re-sign + attach.
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
        genesis = RoleAssertionEvent(
            corpus=corpus_name,
            position=0,
            signature=placeholder_sig,
            subject_did=admin_did,
            role="corpus_admin",
        )
        payload_hash = genesis.signature_payload().decode("utf-8")
        real_sig = sign_attestation(
            content_hash=payload_hash,
            signing_key=sk,
            did=signer_did,
            action="role_assertion",
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            now=now,
        )
        signed_genesis = genesis.model_copy(update={"signature": real_sig})
        try:
            persisted = await log.append(signed_genesis)
        except Exception as exc:
            click.echo(
                f"log.append refused: {type(exc).__name__}: {exc}", err=True
            )
            sys.exit(1)
        click.echo(persisted.model_dump_json(indent=2))

    asyncio.run(_run())


__all__ = ["corpus_init_cmd"]

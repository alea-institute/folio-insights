"""``governance promote`` subcommand (D-15, D-19, D-20, D-21).

Promote a shard to an attested epistemic status. Order of operations (D-19):

  1. Parse CLI args + load the signing key + derive ``signer_did`` from it.
  2. ``await authorize(signer_did, "promote", corpus, log=log)`` — Deny exits non-zero.
  3. ``await validate_promotion(event, store=store)`` — D-20 + D-21 raise ValueError.
  4. ``sign_attestation`` over ``event.signature_payload()`` (Phase 6 seam).
  5. ``await log.append(event)`` — runs the SHACL belt for the promotion shape.
  6. Emit the persisted event as JSON.

The ShardStore is a process-local InMemoryShardStore for Phase 7; Phase 13
swaps an Oxigraph-backed store behind ``revision/store.py::ShardStore``.

Step 1 happens BEFORE the await over authorize() — Click's argument parsing
+ the ``load_signing_key`` call are synchronous setup. The D-19 invariant is
that the FIRST ``await`` in the command body is ``await authorize(...)``;
``test_authorize_called_first.py`` AST-walks the body to enforce.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.events import PromotionEvent
from folio_insights.governance.promote import validate_promotion
from folio_insights.identity.keys import KEY_PATH


@click.command(name="promote")
@click.argument("shard_iri")
@click.option(
    "--status",
    required=True,
    type=click.Choice(
        ["per_se_nota_quoad_nos", "demonstrable", "authority_only"],
        case_sensitive=True,
    ),
    help="The new epistemic status (D-21 — 3-Literal lock).",
)
@click.option(
    "--cite",
    "cited_iris",
    multiple=True,
    required=True,
    help=(
        "Cited shard IRI (repeat to cite multiple). D-20 requires ≥1; "
        "every IRI must resolve in the ShardStore and none may equal "
        "<shard_iri> (no self-citation)."
    ),
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
def promote_cmd(
    shard_iri: str,
    status: str,
    cited_iris: tuple[str, ...],
    corpus: str,
    key_path: Path,
    yes: bool,
) -> None:
    """Promote a HypothesisShard to an attested status (D-20 + D-21)."""
    from folio_insights.governance.cli._signing import sign_and_verify_event
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.governance.log import InvalidSignature
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.revision.store import InMemoryShardStore

    log = GOVERNANCE_LOG
    store = InMemoryShardStore()  # Phase 13 wires the persistent backend.

    # Load the signing key + derive the signer DID. Failures here are reported
    # as `no signing key` to the operator — never as a stacktrace.
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
        # ── D-19 FIRST STEP: central authorize() gate ──
        decision = await authorize(signer_did, "promote", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(
                f"unauthorized (denied: {decision.reason})", err=True
            )
            sys.exit(1)
        assert isinstance(decision, Allow)

        # ── D-20 + D-21 cross-shard validators ──
        now = datetime.now(UTC)
        # Build a placeholder signature so we can run the validator + then
        # produce the real signature over the canonical payload.
        from folio_insights.shards.envelope import AttestedSignature

        placeholder_sig = AttestedSignature(
            did=signer_did,
            action="promote",
            signed_at=now,
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{signer_did}#{signer_did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            verified=None,
        )
        event = PromotionEvent(
            corpus=corpus,
            signature=placeholder_sig,
            shard_iri=shard_iri,
            new_status=status,  # type: ignore[arg-type]
            cited_iris=list(cited_iris),
        )
        try:
            await validate_promotion(event, store=store)
        except ValueError as exc:
            click.echo(f"validate_promotion refused: {exc}", err=True)
            sys.exit(1)

        # ── Sign + verify + append (CR-01: shared helper round-trip) ──
        try:
            sig = await sign_and_verify_event(
                event,
                signing_key=sk,
                did=signer_did,
                action="promote",
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


__all__ = ["promote_cmd"]

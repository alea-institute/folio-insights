"""``folio-insights proposals``: client-side helpers for review decisions (drain plan U9).

``sign-decision`` signs a decision body with a local ed25519 key and prints the signed
decision (``signed_decisions.SignedDecision``) as JSON: send it as the ``signature``
object of a review API request, or give it to ``scripts/apply_approvals.py apply``.

The input body is ``{kind, corpus, target, verdict, rationale?, detail?}``; the signer
adds ``decided_by`` (the key's did:key), a fresh ``nonce`` and ``issued_at``. A server
accepts the result for ``frameworks.registry.SIGNING_SKEW`` after signing, once.

The key file is read with ``identity.keys.load_signing_key`` (a JWK, refused when
group- or world-accessible). The key never leaves this process and is never printed.
"""
from __future__ import annotations

import json
from pathlib import Path

import click


@click.group("proposals")
def proposals_group() -> None:
    """Review decisions: sign a decision for the review API or apply_approvals.py."""


@proposals_group.command("sign-decision")
@click.option(
    "--key", "key_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="ed25519 signing key (JWK, mode 600), e.g. from 'folio-insights did generate'.",
)
@click.option(
    "--body", "body_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="decision JSON: {kind, corpus, target, verdict, rationale?, detail?}.",
)
@click.option(
    "--out", "out_path", default=None, type=click.Path(dir_okay=False, path_type=Path),
    help="write the signed decision here instead of printing it.",
)
def sign_decision_cmd(key_path: Path, body_path: Path, out_path: Path | None) -> None:
    """Sign a review decision and print the signed decision JSON."""
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.proposals.signed_decisions import (
        DecisionSignatureRefused,
        sign_decision,
    )

    try:
        fields = json.loads(body_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise click.ClickException("the decision body is not a readable JSON file") from None
    if not isinstance(fields, dict):
        raise click.ClickException("the decision body must be a JSON object")
    try:
        signing_key = load_signing_key(key_path)
    except (PermissionError, FileNotFoundError, ValueError, KeyError) as exc:
        raise click.ClickException(f"cannot load the signing key: {type(exc).__name__}") from None
    try:
        signed = sign_decision(fields, signing_key=signing_key)
    except DecisionSignatureRefused as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        del signing_key
    text = json.dumps(signed.to_record(), sort_keys=True, indent=2) + "\n"
    if out_path is None:
        click.echo(text, nl=False)
    else:
        out_path.write_text(text, encoding="utf-8")
        click.echo(f"signed decision written to {out_path}", err=True)


__all__ = ["proposals_group", "sign_decision_cmd"]

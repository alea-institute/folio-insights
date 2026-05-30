"""``governance show`` subcommand (D-08 companion, D-19; PRD §3.1.5).

Paginated read of the governance log for a corpus — the human-readable
companion to ``governance export``. Renders one row per event with
``position | action | signer_did | signed_at | shard_iri (when present)``.

Order of operations (D-19 — applies even on read paths):
  1. Parse CLI args + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "show", corpus, log=log)`` — D-19 first.
  3. Collect events via ``log.iter_events(corpus)`` up to ``--limit``.
  4. Render via ``rich.table.Table``.

**D-04 boundary:** stdlib + click + rich only — no rdflib / pyshacl /
aiosqlite imports here.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.identity.keys import KEY_PATH


@click.command(name="show")
@click.option(
    "--corpus",
    required=True,
    help="Per-corpus governance log to show.",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of events to render.",
)
@click.option(
    "--key-path",
    type=click.Path(path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help="Local ed25519 keystore JWK (DID-06).",
)
def show_cmd(corpus: str, limit: int, key_path: Path) -> None:
    """Show recent governance events for a corpus (read-only, gated by authorize)."""
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key

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
        # ── D-19 FIRST STEP (applies even on read paths — 07-05b extension) ──
        decision = await authorize(signer_did, "show", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(f"unauthorized (denied: {decision.reason})", err=True)
            sys.exit(1)
        assert isinstance(decision, Allow)

        events = []
        async for ev in log.iter_events(corpus):
            events.append(ev)
            if len(events) >= limit:
                break

        console = Console()
        table = Table(
            title=f"Governance log: {corpus} (showing {len(events)} events)",
            show_lines=False,
        )
        table.add_column("position", justify="right")
        table.add_column("action")
        table.add_column("signer_did")
        table.add_column("signed_at")
        table.add_column("shard_iri")
        for ev in events:
            shard_iri = getattr(ev, "shard_iri", None) or ""
            signed_at = (
                ev.signature.signed_at.isoformat()
                if ev.signature.signed_at is not None
                else ""
            )
            table.add_row(
                str(ev.position),
                ev.action,
                ev.signature.did,
                signed_at,
                shard_iri,
            )
        console.print(table)

    asyncio.run(_run())


__all__ = ["show_cmd"]

"""``governance export`` subcommand (D-08, D-19; PRD §3.1.5).

On-demand Turtle export of a corpus's governance log (D-08). Phase 7 ships
the CLI + the actual Turtle writer for the in-memory backend; Phase 13
wires the persistent SQLite ledger behind the SAME ``GovernanceLog`` Protocol
without touching this command (D-05).

Order of operations (D-19 — applies even on read paths):
  1. Parse CLI args + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "export", corpus, log=log)`` — D-19 first.
  3. Collect events via ``log.iter_events(corpus)``.
  4. Hand the events to ``shape_validation.serialize_log_as_turtle`` — the
     lone rdflib-exempt module — and write the result to disk.

**D-04 boundary:** this module does NOT pull in the RDF stack directly.
The Turtle pipeline routes through
``shape_validation.serialize_log_as_turtle`` (the lone exempt module).
The boundary scan in
``tests/governance/test_governance_export_cli.py`` enforces.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.identity.keys import KEY_PATH


@click.command(name="export")
@click.argument("corpus_name")
@click.option(
    "--output",
    "-o",
    "output_path",
    default="./governance.ttl",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path, resolve_path=True),
    help="Output path for the exported Turtle.",
)
@click.option(
    "--key-path",
    type=click.Path(path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help="Local ed25519 keystore JWK (DID-06).",
)
def export_cmd(
    corpus_name: str,
    output_path: Path,
    key_path: Path,
) -> None:
    """Export the governance log for <corpus_name> as Turtle (D-08, on-demand).

    Every event becomes a prov:Activity attributed to the signer DID via
    PROV-O ``prov:wasAttributedTo``. The export is a read-only audit
    artifact — no log mutation occurs.
    """
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.governance.shape_validation import (
        serialize_log_as_turtle,
    )
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
        decision = await authorize(signer_did, "export", corpus_name, log=log)
        if isinstance(decision, Deny):
            click.echo(f"unauthorized (denied: {decision.reason})", err=True)
            sys.exit(1)
        assert isinstance(decision, Allow)

        events = []
        async for ev in log.iter_events(corpus_name):
            events.append(ev)

        # D-04 boundary: serialize_log_as_turtle lives in shape_validation.py
        # — the lone module under governance/ that owns the RDF substrate
        # dependency. This CLI never touches the RDF stack directly.
        turtle = serialize_log_as_turtle(events)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(turtle, encoding="utf-8")
        except Exception as exc:
            click.echo(
                f"failed to write Turtle to {output_path}: {exc}", err=True
            )
            sys.exit(1)

        click.echo(
            f"exported {len(events)} events from corpus {corpus_name!r} "
            f"to {output_path}"
        )

    asyncio.run(_run())


__all__ = ["export_cmd"]

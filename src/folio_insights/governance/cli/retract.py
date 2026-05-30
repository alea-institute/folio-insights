"""``governance retract`` subcommand (D-15, D-16, D-17, D-19; PRD §3.1.4, GOV-06).

Retract a shard with cascade preview. Three modes (D-17):

  * default (interactive): build_cascade_preview -> rich.table.Table render
    of the 3 D-18 buckets -> click.confirm -> on yes: commit_cascade.
  * ``--preview``: build_cascade_preview -> write JSON to a timestamped
    output path -> exit 0 WITHOUT committing.
  * ``--apply <file>``: load CascadePreview JSON -> commit_cascade — which
    re-runs build_cascade_preview and raises PreviewStale (with --preview
    in the message) on state-change race.

WR-03 Phase 7 limitation: ``--apply`` is DISABLED in Phase 7.

The CLI builds a fresh ``InMemoryShardStore()`` on every invocation
(see line ~135). With no persistent ShardStore yet wired (Phase 13,
D-07), ``--apply`` ALWAYS runs against an empty store. That means:

  * The ``underlying_state_hash`` re-computed by ``commit_cascade``'s
    PreviewStale check is the hash of an EMPTY store, never the hash
    of the seeded store the original ``--preview`` was taken against.
  * If a real (seeded) preview is fed to ``--apply``, PreviewStale
    fires immediately — the operator gets a hash-mismatch refusal
    that does NOT reflect a real race condition, just the empty
    in-memory store.
  * Conversely, if a fake/empty preview is fed in, the empty-store
    hash happens to match the preview, ``commit_cascade`` proceeds,
    and a RetractionEvent is appended that doesn't correspond to any
    real cascade — a SILENT FALSE-SUCCESS path.

Until Phase 13 wires a persistent ShardStore behind the same Protocol
(D-07), the safe behavior is to fail loudly. The ``--apply`` branch
raises ``NotImplementedError`` with a clear message pointing at the
Phase 13 wire-up; the operator runs the interactive (default) mode or
``--preview`` instead. The interactive + ``--preview`` modes work
correctly because they build the preview against the SAME in-memory
store the operator just constructed (so the hash check is trivially
consistent within a single process).

Order of operations (D-19):
  1. Parse CLI args + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "retract", corpus, log=log)`` — D-19 first.
  3. Branch on mode → build_cascade_preview → render OR commit_cascade.
  4. On commit: log.append handles SHACL belt; emit JSON.

**D-16 boundary:** this module imports ONLY from ``governance.retract``
(its own module's event class + builder + committer + PreviewStale) — NOT
from contest.py or supersede.py. The D-16 grep-guard regression test
flips from skip to PASS the moment this file ships.
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.retract import (
    PreviewStale,
    build_cascade_preview,
    commit_cascade,
)
from folio_insights.identity.keys import KEY_PATH


def _sanitize_iri_for_filename(iri: str) -> str:
    """Lowercase + replace non-[a-z0-9_-] with '_' so the IRI fits a filename.

    The cascade-preview JSON output path defaults to
    ``retract-preview-<sanitized_iri>-<ts>.json`` per D-17; the operator
    can override via ``--output``.
    """
    return re.sub(r"[^a-z0-9_-]+", "_", iri.lower())


@click.command(name="retract")
@click.argument("shard_iri")
@click.option(
    "--preview",
    "preview_only",
    is_flag=True,
    default=False,
    help=(
        "Build the cascade preview and write it to JSON; exit 0 without "
        "committing. The output file can later be passed to --apply."
    ),
)
@click.option(
    "--apply",
    "apply_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Re-run the preview, refuse with PreviewStale if the underlying "
        "state changed, and commit. Pass a JSON file produced by --preview."
    ),
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Output path for the --preview JSON. Default: "
        "retract-preview-<sanitized_iri>-<ts>.json in the current directory."
    ),
)
@click.option(
    "--corpus",
    required=True,
    help="Per-corpus governance log to retract within.",
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
    help="Skip the interactive confirmation (scripted use).",
)
def retract_cmd(
    shard_iri: str,
    preview_only: bool,
    apply_path: Path | None,
    output: Path | None,
    corpus: str,
    key_path: Path,
    yes: bool,
) -> None:
    """Retract a shard with cascade preview (PRD §3.1.4 / GOV-06).

    Three modes (D-17):
      - default: build_cascade_preview, render grouped table, prompt
        'Confirm? [y/N]', commit on y.
      - --preview: write timestamped JSON, exit 0 without committing.
      - --apply <file>: re-run preview, compare underlying_state_hash;
        raise PreviewStale if changed.
    """
    from folio_insights.governance.cli._state import GOVERNANCE_LOG
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.revision.store import InMemoryShardStore

    log = GOVERNANCE_LOG
    # Phase 13 will wire a persistent ShardStore behind the same Protocol;
    # Phase 7 uses a process-local InMemoryShardStore. The test fixture
    # ``tests/governance/fixtures/cascade_corpora.py`` seeds this for the
    # interactive-flow checkpoint REPL.
    store = InMemoryShardStore()

    # Mode mutual-exclusion (--preview + --apply is nonsense).
    if preview_only and apply_path is not None:
        click.echo(
            "--preview and --apply are mutually exclusive; pick one mode.",
            err=True,
        )
        sys.exit(1)

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
        decision = await authorize(signer_did, "retract", corpus, log=log)
        if isinstance(decision, Deny):
            click.echo(f"unauthorized (denied: {decision.reason})", err=True)
            sys.exit(1)
        assert isinstance(decision, Allow)

        # ── --apply mode ──
        # WR-03: --apply is DISABLED in Phase 7. The CLI builds a fresh
        # InMemoryShardStore() on every invocation (line ~135), so
        # commit_cascade's PreviewStale guard re-hashes an EMPTY store
        # state — never the seeded state the original --preview ran
        # against. That collapses into either (a) PreviewStale-always
        # (real preview vs empty store) or (b) silent false-success
        # (fake preview against empty store, commit proceeds). Both
        # close-the-door behaviors fail the operator's expectations.
        # Refuse loudly with NotImplementedError until Phase 13 (D-07)
        # wires a persistent ShardStore behind the same Protocol.
        if apply_path is not None:
            raise NotImplementedError(
                "--apply requires a persistent ShardStore that survives "
                "between the --preview run and the --apply run; Phase 7 "
                "only ships InMemoryShardStore (process-local, reset per "
                "CLI invocation). Phase 13 (D-07) wires "
                "<corpus>/governance.ttl + <corpus>/.governance.sqlite "
                "behind the same ShardStore Protocol, at which point "
                "--apply will work correctly. For now, use the default "
                "interactive mode or --preview within a single process."
            )

        # ── Build the cascade preview (shared D-17 builder) ──
        preview = await build_cascade_preview(
            shard_iri, corpus, store=store, log=log
        )

        # ── --preview mode (write JSON, exit 0 without commit) ──
        if preview_only:
            out_path = output
            if out_path is None:
                ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                sanitized = _sanitize_iri_for_filename(shard_iri)
                out_path = Path.cwd() / f"retract-preview-{sanitized}-{ts}.json"
            try:
                out_path.write_text(
                    preview.model_dump_json(indent=2), encoding="utf-8"
                )
            except Exception as exc:
                click.echo(
                    f"failed to write preview to {out_path}: {exc}", err=True
                )
                sys.exit(1)
            click.echo(
                f"cascade preview written to {out_path} "
                f"(auto_rederive: {len(preview.auto_rederive)}, "
                f"aporetic: {len(preview.aporetic)}, "
                f"review_needed: {len(preview.review_needed)})"
            )
            return

        # ── Default (interactive) mode ──
        console = Console()
        table = Table(
            title=f"Cascade preview for {shard_iri} in {corpus}",
            show_lines=True,
        )
        table.add_column("auto_rederive", style="green")
        table.add_column("aporetic", style="yellow")
        table.add_column("review_needed", style="red")
        # Pad the three buckets to equal length for row-wise rendering.
        max_rows = max(
            len(preview.auto_rederive),
            len(preview.aporetic),
            len(preview.review_needed),
            1,
        )
        for i in range(max_rows):
            row = [
                preview.auto_rederive[i] if i < len(preview.auto_rederive) else "",
                preview.aporetic[i] if i < len(preview.aporetic) else "",
                preview.review_needed[i] if i < len(preview.review_needed) else "",
            ]
            table.add_row(*row)
        console.print(table)

        total = (
            len(preview.auto_rederive)
            + len(preview.aporetic)
            + len(preview.review_needed)
        )
        prompt = (
            f"Confirm retraction of {total} shards "
            f"(auto_rederive: {len(preview.auto_rederive)}, "
            f"aporetic: {len(preview.aporetic)}, "
            f"review_needed: {len(preview.review_needed)})?"
        )
        if not yes:
            confirmed = click.confirm(prompt, default=False)
            if not confirmed:
                click.echo("retraction aborted (operator did not confirm).")
                return

        try:
            event = await commit_cascade(
                preview, store=store, log=log, signing_key=sk, did=signer_did
            )
        except PreviewStale as exc:
            click.echo(f"PreviewStale: {exc}", err=True)
            sys.exit(2)
        except Exception as exc:
            click.echo(
                f"commit_cascade refused: {type(exc).__name__}: {exc}",
                err=True,
            )
            sys.exit(1)
        click.echo(event.model_dump_json(indent=2))

    asyncio.run(_run())


__all__ = ["retract_cmd"]

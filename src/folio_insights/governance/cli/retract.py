"""``governance retract`` subcommand (D-15, D-16, D-17, D-19; PRD §3.1.4, GOV-06).

Retract a shard with cascade preview. Three modes (D-17):

  * default (interactive): build_cascade_preview -> rich.table.Table render
    of the 3 D-18 buckets -> click.confirm -> on yes: commit_cascade.
  * ``--preview``: build_cascade_preview -> write JSON to a timestamped
    output path -> exit 0 WITHOUT committing.
  * ``--apply <file>``: load the saved CascadePreview JSON -> commit_cascade,
    which re-runs build_cascade_preview and raises PreviewStale (with
    --preview in the message) on a state change.

Phase 13 (U3) lifts the Phase 7 WR-03 ``--apply`` refusal. Every mode opens
ONE persistent ``CorpusStorageContext`` for the corpus (``async with``), so a
preview saved by one process is applied by another against the same state:

  * The saved preview records an explicit ``op_id`` and the corpus journal
    head (``state_position``) it was built against. The head is read BEFORE
    the build, so a write that lands mid-build makes apply refuse.
  * ``--apply`` first looks the ``op_id`` up in the journal. If it already
    committed (a retry, or a retry after a projection-recovery error), the
    committed RetractionEvent is returned unchanged; nothing is re-signed.
  * Otherwise ``commit_cascade`` re-runs the shared builder (PreviewStale on a
    changed cascade; RetractionTargetMissing on an absent target), signs, and
    appends under ``op_id`` with ``expected_head=state_position``. The
    storage write transaction re-checks the head, so any shard revision or
    governance event committed since the preview refuses with PreviewStale
    (exit 2) and leaves the journal unchanged.
  * Retraction appends a RetractionEvent only. No shard is deleted or
    rewritten; effective state is derived from the event history.

Order of operations (D-19):
  1. Parse CLI args + load signing key + derive signer_did.
  2. ``await authorize(signer_did, "retract", corpus, log=log)`` — D-19 first.
  3. Branch on mode → build_cascade_preview → render OR commit_cascade.
  4. On commit: signature verify + log-layer SHACL belt; emit JSON.

**D-16 boundary:** this module imports ONLY from ``governance.retract``
(its own module's event class + builder + committer + PreviewStale) — NOT
from contest.py or supersede.py.
"""
from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.cli._state import corpus_root_option
from folio_insights.governance.retract import (
    CascadePreview,
    PreviewStale,
    RetractionTargetMissing,
    build_cascade_preview,
    cascade_preview_hash,
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
        "Commit a JSON file produced by --preview (in any later process). "
        "Refuses with PreviewStale if any shard or governance state changed "
        "since the preview; retrying an applied preview returns the "
        "committed event."
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
@corpus_root_option
def retract_cmd(
    shard_iri: str,
    preview_only: bool,
    apply_path: Path | None,
    output: Path | None,
    corpus: str,
    key_path: Path,
    yes: bool,
    corpus_root: Path | None,
) -> None:
    """Retract a shard with cascade preview (PRD §3.1.4 / GOV-06).

    Three modes (D-17):
      - default: build_cascade_preview, render grouped table, prompt
        'Confirm? [y/N]', commit on y.
      - --preview: write timestamped JSON, exit 0 without committing.
      - --apply <file>: commit a saved preview from any later process;
        PreviewStale if any shard or governance state changed since.
    """
    from folio_insights.governance.cli._state import corpus_storage, run_cli
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.storage import (
        JournalStateChanged,
        OperationIdConflict,
        StorageError,
    )

    # One DidDocCache for signing AND the storage append-time verifier.
    cache = InMemoryDidDocCache()

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

    saved: CascadePreview | None = None
    if apply_path is not None:
        try:
            saved = CascadePreview.model_validate_json(
                apply_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            click.echo(f"unreadable preview file {apply_path}: {exc}", err=True)
            sys.exit(1)
        if saved.retracted_shard_iri != shard_iri or saved.corpus != corpus:
            click.echo(
                f"preview file is for {saved.retracted_shard_iri!r} in corpus "
                f"{saved.corpus!r}, not {shard_iri!r} in {corpus!r}; refusing.",
                err=True,
            )
            sys.exit(1)
        if saved.op_id is None or saved.state_position is None:
            click.echo(
                "preview file carries no op_id/state_position (it was not "
                "saved from a persistent corpus); re-run --preview.",
                err=True,
            )
            sys.exit(1)

    async def _run() -> None:
        async with corpus_storage(corpus_root, corpus, cache=cache) as ctx:
            log = ctx.governance
            store = ctx.shards
            # ── D-19 FIRST STEP ──
            decision = await authorize(signer_did, "retract", corpus, log=log)
            if isinstance(decision, Deny):
                click.echo(f"unauthorized (denied: {decision.reason})", err=True)
                sys.exit(1)
            assert isinstance(decision, Allow)

            async def _committed(preview: CascadePreview):
                """The event already committed under this preview's op_id,
                or None. A different request under the same op_id refuses."""
                assert preview.op_id is not None
                try:
                    event = await ctx.committed_governance_op(preview.op_id)
                except OperationIdConflict as exc:
                    click.echo(f"retraction refused: {exc}", err=True)
                    sys.exit(1)
                if event is None:
                    return None
                if (
                    event.action != "retract"
                    or getattr(event, "shard_iri", None) != preview.retracted_shard_iri
                    or getattr(event, "cascade_preview_hash", None)
                    != cascade_preview_hash(preview)
                ):
                    click.echo(
                        f"operation {preview.op_id!r} was committed for a "
                        "different request; refusing.",
                        err=True,
                    )
                    sys.exit(1)
                if event.signature.did != signer_did:
                    click.echo(
                        f"retraction {preview.op_id!r} already committed by "
                        f"{event.signature.did} at governance position "
                        f"{event.position}; returning that event.",
                        err=True,
                    )
                return event

            async def _commit(preview: CascadePreview) -> None:
                try:
                    event = await commit_cascade(
                        preview,
                        store=store,
                        log=log,
                        signing_key=sk,
                        did=signer_did,
                        cache=cache,
                    )
                except StorageError as exc:
                    # e.g. ProjectionRecoveryPending: the commit is durable and
                    # the context is closed; re-running --apply with the same
                    # preview file returns the committed event.
                    click.echo(f"storage error: {type(exc).__name__}: {exc}", err=True)
                    sys.exit(1)
                except Exception as exc:
                    # A concurrent apply of the same preview may have won the
                    # race (its commit then reads as a state change or an
                    # op_id conflict here): its committed event is this
                    # request's result, so report it instead of refusing.
                    winner = await _committed(preview)
                    if winner is not None:
                        click.echo(winner.model_dump_json(indent=2))
                        return
                    if isinstance(exc, (PreviewStale, JournalStateChanged)):
                        click.echo(
                            f"PreviewStale: {exc}. Nothing was committed; "
                            "re-run --preview.",
                            err=True,
                        )
                        sys.exit(2)
                    if isinstance(exc, RetractionTargetMissing):
                        click.echo(f"retraction refused: {exc}", err=True)
                        sys.exit(1)
                    click.echo(
                        f"commit_cascade refused: {type(exc).__name__}: {exc}",
                        err=True,
                    )
                    sys.exit(1)
                click.echo(event.model_dump_json(indent=2))

            # ── --apply mode: replay a saved preview (any later process) ──
            if saved is not None:
                committed = await _committed(saved)
                if committed is not None:
                    # Retry of an applied preview: same result, no new event.
                    click.echo(committed.model_dump_json(indent=2))
                    return
                await _commit(saved)
                return

            # ── Build the cascade preview (shared D-17 builder) ──
            # Read the journal head FIRST: the preview records the state it
            # was built against, and a write landing mid-build only makes it
            # look older (apply then refuses rather than accepts).
            state_position = await ctx.journal_head()
            try:
                preview = await build_cascade_preview(
                    shard_iri,
                    corpus,
                    store=store,
                    log=log,
                    state_position=state_position,
                )
            except RetractionTargetMissing as exc:
                click.echo(f"retraction refused: {exc}", err=True)
                sys.exit(1)

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

            await _commit(preview)

    run_cli(_run())


__all__ = ["retract_cmd"]

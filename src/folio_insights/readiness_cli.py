"""Offline readiness command; CLI diagnostics obey the same content boundary."""
from __future__ import annotations

import json
from pathlib import Path

import click

from folio_insights.readiness import build_readiness_report


class _SafeUsageError(click.UsageError):
    def show(self, file=None) -> None:
        # Click normally echoes arbitrary option values and invocation paths.
        click.echo(f'Error: {self.message}', file=file, err=True)


class _ReadinessCommand(click.Command):
    def make_context(self, info_name, args, parent=None, **extra):
        try:
            return super().make_context(info_name, args, parent=parent, **extra)
        except click.UsageError:
            raise _SafeUsageError('readiness_invalid_usage') from None


def _text_fields(data: dict, prefix: str = ''):
    for key, value in sorted(data.items()):
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            yield from _text_fields(value, name)
        else:
            yield f'{name}: {json.dumps(value, allow_nan=False)}'


@click.command('readiness', cls=_ReadinessCommand)
@click.option('--extraction', type=click.Path(path_type=Path),
              help='Saved extraction JSON; only recorded aggregate coverage is reported.')
@click.option('--dispositions', type=click.Path(path_type=Path),
              help='Saved disposition JSONL; the current detector is never run.')
@click.option('--labeled-set', type=click.Path(path_type=Path),
              help='Optional labeled-set JSON paired with every disposition.')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']), default='text',
              show_default=True, help='Content-free report representation.')
@click.pass_context
def readiness_cmd(
    ctx: click.Context, extraction: Path | None, dispositions: Path | None,
    labeled_set: Path | None, output_format: str,
) -> None:
    """Inspect selected saved evidence without running or changing the pipeline.

    Exit 0 means usable selected artifacts, not a quality-gate pass. Exit 1
    preserves usable sections alongside fixed input diagnostics. Exit 2 is a
    usage error. Missing options leave the corresponding evidence unavailable.
    """
    if labeled_set is not None and dispositions is None:
        raise _SafeUsageError('labeled_set_requires_dispositions')
    report = build_readiness_report(extraction=extraction, dispositions=dispositions,
                                    labeled_set=labeled_set)
    data = report.as_dict()
    click.echo(json.dumps(data, indent=2, sort_keys=True, allow_nan=False)
               if output_format == 'json' else '\n'.join(_text_fields(data)))
    ctx.exit(report.exit_code)

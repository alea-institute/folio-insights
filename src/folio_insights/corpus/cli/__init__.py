"""``folio-insights corpus`` Click subgroup (CORPUS-05, D-10, D-19).

Phase 7 ships a single subcommand: ``corpus init <name> --admin-did <did>``.
The command writes a genesis row-0 ``RoleAssertionEvent`` granting
``corpus_admin`` to ``--admin-did`` (self-signed) via the same
``authorize()`` gate every other CLI command passes through (Issue #3
closure — NO CLI exemption).
"""
from __future__ import annotations

import click


@click.group(name="corpus")
def corpus_group() -> None:
    """Corpus lifecycle: init (Phase 7).

    Every command's first step is ``await authorize(...)`` per D-19. The
    genesis bootstrap carve-out lives inside ``authorize()`` via
    ``action="corpus_init"`` — there is no CLI-level exemption.
    """


from folio_insights.corpus.cli.corpus import corpus_init_cmd  # noqa: E402

corpus_group.add_command(corpus_init_cmd)


__all__ = ["corpus_group"]

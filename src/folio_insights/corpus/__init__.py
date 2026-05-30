"""Phase 7 corpus-init CLI substrate (CORPUS-05, D-10, D-19).

Houses the ``corpus init <name> --admin-did <did>`` genesis-bootstrap CLI
command. The library-layer carve-out lives inside
``governance/authorize.py`` (action ``"corpus_init"``); this package is the
CLI surface only.

Phase 13 (D-07) extends this package with cross-corpus listing / dump /
export commands; in Phase 7 the only subcommand is ``init``.
"""
from __future__ import annotations

__all__: list[str] = []

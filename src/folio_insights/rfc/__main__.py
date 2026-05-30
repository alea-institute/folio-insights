"""Module CLI entry: `python -m folio_insights.rfc.lint <dir>`.

This shim makes `python -m folio_insights.rfc` also work (defaulting to
`.planning/rfcs/` if no path is supplied) so contributors don't have to
remember the `.lint` submodule suffix.
"""
from __future__ import annotations

import sys
from pathlib import Path

from folio_insights.rfc.lint import main

if __name__ == "__main__":  # pragma: no cover
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".planning/rfcs/")
    sys.exit(main(target))

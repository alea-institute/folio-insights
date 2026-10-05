#!/usr/bin/env python3
"""Regenerate (or check) the Pydantic-generated SHACL shapes (Phase 11 SHACL-04).

    python scripts/generate_shapes.py           # rewrite the committed TTL
    python scripts/generate_shapes.py --check   # exit 1 if it would change

The Dagger shapes stage and ``tests/shapes/test_generator.py`` run ``--check``,
so a model change without a regenerated, committed TTL fails CI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from folio_insights.shapes.pydantic_to_shacl import (  # noqa: E402
    GENERATED_PATH,
    check_generated,
    write_generated,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed TTL is stale")
    args = parser.parse_args(argv)
    rel = GENERATED_PATH.relative_to(REPO_ROOT) if GENERATED_PATH.is_relative_to(REPO_ROOT) else GENERATED_PATH
    if args.check:
        if check_generated():
            print(f"OK: {rel} matches the Pydantic models")
            return 0
        print(f"STALE: {rel} differs from a fresh generation; run scripts/generate_shapes.py",
              file=sys.stderr)
        return 1
    changed = write_generated()
    print(f"{'wrote' if changed else 'unchanged'}: {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

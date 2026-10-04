"""Proposed-class governance CLI: collect, dedupe, worklist (governance plan U2).

All state lives in the Phase 13 corpus storage root (``--corpus-root``, else
``$FOLIO_INSIGHTS_CORPUS_ROOT``, else ``~/.folio-insights/corpora``), as the
append-only proposal ledger of one corpus. Every subcommand is offline: none of
them constructs a model client or opens a network connection.

  collect   Record one pipeline run's proposed classes (labels, unit IDs, spans;
            never source text). Re-collecting the same run is a no-op.
  dedupe    Deterministic dedupe against a FOLIO lexicon (.owl or JSON cache)
            and across proposals. Human and model judgments are never overwritten.
  worklist  Write the judgment worklist JSON for definition-level review.
            Writing a worklist records no judgment and approves nothing. The
            file must sit outside this repository and outside the corpus root,
            so generated review material is never committed.

Usage:
  python scripts/judge_proposals.py collect  --corpus C --run-dir OUT/C --run RUN
  python scripts/judge_proposals.py dedupe   --corpus C --lexicon FOLIO.owl
  python scripts/judge_proposals.py worklist --corpus C --lexicon FOLIO.owl \\
      --out /path/outside/repo/worklist.json [--floor 74 --k 4 --min-candidate 60]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from folio_insights.proposals import (  # noqa: E402
    FolioLexicon,
    ProposalStore,
    build_worklist,
    load_run_proposals,
)
from folio_insights.storage import CorpusStorageContext  # noqa: E402

CORPUS_ROOT_ENV = "FOLIO_INSIGHTS_CORPUS_ROOT"


def resolve_corpus_root(value: str | None) -> Path:
    """Explicit option, else the environment variable, else the default."""
    if value:
        return Path(value).expanduser()
    env = os.environ.get(CORPUS_ROOT_ENV)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".folio-insights" / "corpora"


def _inside(path: Path, other: Path) -> bool:
    path, other = path.resolve(), other.resolve()
    return path == other or other in path.parents


def check_worklist_destination(out: Path, corpus_root: Path) -> None:
    """Refuse a worklist path inside this repository or the storage root (R5)."""
    if _inside(out, REPO_ROOT):
        raise SystemExit(
            f"refusing to write a worklist inside the repository ({REPO_ROOT}); "
            "generated review material must never be committed"
        )
    if _inside(out, corpus_root):
        raise SystemExit("refusing to write a worklist inside the corpus storage root")


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_corpus_root(args.corpus_root)
    out_path: Path | None = None
    if args.command == "worklist":
        out_path = Path(args.out).expanduser()
        check_worklist_destination(out_path, root)
    lexicon = FolioLexicon.load(args.lexicon) if getattr(args, "lexicon", None) else None
    async with await CorpusStorageContext.open(root, args.corpus) as ctx:
        store = ProposalStore(ctx)
        if args.command == "collect":
            pcs, spans = load_run_proposals(args.run_dir)
            run = args.run or Path(args.run_dir).name
            return await store.collect_run(run, pcs, spans_by_unit=spans)
        if args.command == "dedupe":
            return await store.apply_dedupe(lexicon)
        registry = await store.load()
    worklist = build_worklist(
        registry, lexicon, floor=args.floor, k=args.k, min_candidate=args.min_candidate
    )
    assert out_path is not None
    _write_json_atomic(out_path, worklist)
    return {**worklist["counts"], "worklist": str(out_path), "ledger_head": registry.head}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--corpus", required=True)
        p.add_argument("--corpus-root", default=None)

    c = sub.add_parser("collect", help="record one run's proposed classes")
    common(c)
    c.add_argument("--run-dir", required=True, help="directory holding proposed_classes.json")
    c.add_argument("--run", default=None, help="run name (default: the run directory name)")

    d = sub.add_parser("dedupe", help="deterministic dedupe against FOLIO and proposals")
    common(d)
    d.add_argument("--lexicon", required=True, help="FOLIO .owl or lexicon JSON cache")

    w = sub.add_parser("worklist", help="write the offline judgment worklist")
    common(w)
    w.add_argument("--lexicon", required=True, help="FOLIO .owl or lexicon JSON cache")
    w.add_argument("--out", required=True)
    w.add_argument("--floor", type=float, default=74.0)
    w.add_argument("--k", type=int, default=4)
    w.add_argument("--min-candidate", type=float, default=60.0)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(_run(args))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

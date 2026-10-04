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
            file must sit outside every git work tree (this repository, its
            other worktrees and any other repository) and outside the corpus
            root, so generated review material is never committed.

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
import subprocess
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


def _nearest_existing_dir(path: Path) -> Path:
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    return probe if probe.is_dir() else probe.parent


def _git_claims(directory: Path) -> bool:
    """True if ``directory`` is inside any git work tree or git directory.

    Runs git with inherited ``GIT_*`` variables dropped and system/global
    config ignored. A git that cannot run fails closed (treated as a claim).
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--is-inside-work-tree",
             "--is-inside-git-dir"],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if result.returncode != 0:
        # "not a git repository" is the only acceptable failure.
        return "not a git repository" not in result.stderr
    return "true" in result.stdout.split()


def check_worklist_destination(out: Path, corpus_root: Path) -> Path:
    """Refuse a worklist path inside any git checkout (this repository, another
    worktree or clone of it, or any other repository) or inside the storage
    root (R5). Returns the resolved path, which is what gets written."""
    resolved = Path(out).expanduser().resolve()
    if _inside(resolved, REPO_ROOT):
        raise SystemExit(
            f"refusing to write a worklist inside the repository ({REPO_ROOT}); "
            "generated review material must never be committed"
        )
    if _inside(resolved, corpus_root):
        raise SystemExit("refusing to write a worklist inside the corpus storage root")
    if _git_claims(_nearest_existing_dir(resolved)):
        raise SystemExit(
            "refusing to write a worklist inside a git work tree or git directory; "
            "generated review material must never be committed"
        )
    return resolved


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
        out_path = check_worklist_destination(Path(args.out), root)
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

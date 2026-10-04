"""Proposed-class governance CLI: collect, dedupe, worklist, judgments (plan U2/U3).

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
  judgments Record human or model judgments from a JSON file (a list, or an
            object with a ``judgments`` list, of ``{proposal_id, verdict,
            judged_by, ...}``). The whole file is validated first; an unknown
            ID or an invalid judgment refuses it all. A judgment informs the
            reviewer and never approves anything: approval is a separate,
            explicit decision (``apply_approvals.py``). The operation ID
            defaults to a digest of the file's judgments, so re-recording the
            same file is a replay.

Usage:
  python scripts/judge_proposals.py collect  --corpus C --run-dir OUT/C --run RUN
  python scripts/judge_proposals.py dedupe   --corpus C --lexicon FOLIO.owl
  python scripts/judge_proposals.py worklist --corpus C --lexicon FOLIO.owl \\
      --out /path/outside/repo/worklist.json [--floor 74 --k 4 --min-candidate 60]
  python scripts/judge_proposals.py judgments --corpus C --verdicts FILE [--op-id ID]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import jcs

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from folio_insights.proposals import (  # noqa: E402
    FolioLexicon,
    ProposalStore,
    build_worklist,
    load_run_proposals,
)
from folio_insights.proposals.destinations import (  # noqa: E402
    check_generated_destination,
    write_json_atomic,
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


def check_worklist_destination(out: Path, corpus_root: Path) -> Path:
    """Refuse a worklist path inside any git checkout (this repository, another
    worktree or clone of it, or any other repository) or inside the storage
    root (R5). Returns the resolved path, which is what gets written."""
    return check_generated_destination(
        out, corpus_root, what="worklist", repo_root=REPO_ROOT
    )


def read_judgments(path: Path) -> list[dict[str, Any]]:
    """A judgments file: a JSON list, or an object with a ``judgments`` list."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items = payload.get("judgments") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        raise SystemExit("the judgments file must hold a non-empty list of judgments")
    return items


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
        if args.command == "judgments":
            items = read_judgments(Path(args.verdicts))
            op_id = args.op_id or "judgments:" + hashlib.sha256(
                jcs.canonicalize({"corpus": args.corpus, "judgments": items})
            ).hexdigest()[:32]
            return {**await store.record_judgments(items, op_id=op_id), "op_id": op_id}
        registry = await store.load()
    worklist = build_worklist(
        registry, lexicon, floor=args.floor, k=args.k, min_candidate=args.min_candidate
    )
    assert out_path is not None
    write_json_atomic(out_path, worklist)
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

    j = sub.add_parser("judgments", help="record human or model judgments from a file")
    common(j)
    j.add_argument("--verdicts", required=True, help="JSON list of judgments")
    j.add_argument("--op-id", default=None, help="explicit operation ID (default: digest)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(_run(args))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

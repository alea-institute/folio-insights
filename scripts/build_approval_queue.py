"""Build the human approval queue from the proposal ledger (governance plan U3, Stage C).

Reads one corpus's proposal ledger from the Phase 13 storage root and writes
the queue of proposals that still need a decision, as JSON (``--out``) and,
optionally, as a self-contained HTML page (``--html``). The page lets a
reviewer choose Approve / Reject / Merge / Needs work per card and copy a
``proposed-class-approvals/v1`` paste-back for ``apply_approvals.py apply``.
Nothing is pre-selected, and producing a queue records nothing.

Offline. The queue carries labels, provenance references (runs, unit IDs,
spans), the current judgment and, with ``--lexicon``, FOLIO definitions. It
never carries source text. Both output files must sit outside every git work
tree and outside the corpus root, so generated review material is never
committed.

Usage:
  python scripts/build_approval_queue.py --corpus C --out /outside/repo/queue.json \\
      [--html /outside/repo/queue.html] [--lexicon FOLIO.owl] [--min-occ 1] [--all]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from judge_proposals import resolve_corpus_root  # noqa: E402

from folio_insights.proposals import FolioLexicon, ProposalStore  # noqa: E402
from folio_insights.proposals.destinations import (  # noqa: E402
    check_generated_destination,
    write_json_atomic,
    write_text_atomic,
)
from folio_insights.proposals.queue import build_queue, render_html  # noqa: E402
from folio_insights.storage import CorpusStorageContext  # noqa: E402


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_corpus_root(args.corpus_root)
    out = check_generated_destination(Path(args.out), root, what="approval queue")
    page = (
        check_generated_destination(Path(args.html), root, what="approval queue page")
        if args.html else None
    )
    lexicon = FolioLexicon.load(args.lexicon) if args.lexicon else None
    async with await CorpusStorageContext.open(root, args.corpus) as ctx:
        registry = await ProposalStore(ctx).load()
    queue = build_queue(
        registry, lexicon, include_decided=args.all, min_occurrences=args.min_occ
    )
    write_json_atomic(out, queue)
    if page is not None:
        write_text_atomic(page, render_html(queue))
    return {**queue["counts"], "queue": str(out), "html": str(page) if page else None,
            "ledger_head": queue["ledger_head"]}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--corpus-root", default=None)
    ap.add_argument("--out", required=True, help="queue JSON (outside every git work tree)")
    ap.add_argument("--html", default=None, help="optional HTML page (same rule)")
    ap.add_argument("--lexicon", default=None, help="FOLIO .owl or lexicon JSON cache")
    ap.add_argument("--min-occ", type=int, default=1,
                    help="hide unjudged proposals seen fewer times than this")
    ap.add_argument("--all", action="store_true", help="include already-decided proposals")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(asyncio.run(_run(args)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

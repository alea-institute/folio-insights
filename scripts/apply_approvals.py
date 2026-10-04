"""Record review decisions and export the approved-only backlog (governance plan U3).

All state lives in the Phase 13 corpus storage root (``--corpus-root``, else
``$FOLIO_INSIGHTS_CORPUS_ROOT``, else ``~/.folio-insights/corpora``), as the
append-only proposal ledger of one corpus. Both subcommands are offline.

  apply   Record the decisions in a paste-back file from the approval queue
          (``build_approval_queue.py``). The whole file is validated first:
          one unknown proposal ID, invalid status or extra key refuses it all,
          and nothing is recorded. ``--decided-by`` names the human reviewer
          (``human:<name>``). The operation ID defaults to a digest of the
          corpus, reviewer, decisions and current ledger head: a retry of an
          apply that did not commit replays, and identical decisions keep their
          original decision time. When a replayed operation's decisions were
          changed later, a warning says so and ``current_status`` shows today's
          state. A decision body may not carry its own ``proposal_id``.
  export  Write the approved-only backlog: only proposals whose current
          decision is ``approved``. The same ledger always gives the same
          bytes. The output passes the PII gate and the forbidden-key check,
          and the file must sit outside every git work tree and outside the
          corpus root.

Decisions file (``proposed-class-approvals/v1``)::

  {"schema": "proposed-class-approvals/v1", "corpus": "C",
   "decisions": {"PC-...": {"status": "approve", "note": "..."},
                 "PC-...": {"status": "merge", "merge_into": "PC-..."}}}

Usage:
  python scripts/apply_approvals.py apply  --corpus C --decisions FILE \\
      --decided-by human:REVIEWER [--op-id ID]
  python scripts/apply_approvals.py export --corpus C --out /outside/repo/backlog.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import jcs

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from judge_proposals import resolve_corpus_root  # noqa: E402

from folio_insights.proposals import (  # noqa: E402
    ProposalStore,
    build_backlog,
    check_backlog,
)
from folio_insights.proposals.decisions import DecisionInvalid  # noqa: E402
from folio_insights.proposals.destinations import (  # noqa: E402
    check_generated_destination,
    write_json_atomic,
)
from folio_insights.storage import CorpusStorageContext  # noqa: E402

DECISIONS_SCHEMAS = frozenset({"proposed-class-approvals/v1"})


def read_decisions(path: Path, corpus: str) -> list[dict[str, Any]]:
    """Parse a paste-back file into decision items. Refuses a wrong schema,
    a file for another corpus or a malformed decisions map. Errors never
    echo values."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DecisionInvalid("the decisions file must be a JSON object")
    schema = payload.get("schema")
    if schema not in DECISIONS_SCHEMAS:
        raise DecisionInvalid(f"the decisions file schema must be one of {sorted(DECISIONS_SCHEMAS)}")
    if payload.get("corpus") not in (None, corpus):
        raise DecisionInvalid("the decisions file names a different corpus")
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict) or not decisions:
        raise DecisionInvalid("the decisions file needs a non-empty 'decisions' object")
    items = []
    for pid, body in sorted(decisions.items()):
        if not isinstance(body, dict):
            raise DecisionInvalid("every decision must be an object")
        if "proposal_id" in body:
            # The key names the proposal. A body that names one too could decide a
            # different proposal than the one the reviewer saw under that key.
            raise DecisionInvalid(
                "a decision body must not carry proposal_id; the decisions key names the proposal"
            )
        items.append({"proposal_id": pid, **body})
    return items


def default_op_id(
    corpus: str, decided_by: str, items: list[dict[str, Any]], ledger_head: int
) -> str:
    """A digest of the corpus, reviewer, decisions and the ledger head they were applied at.

    Retrying an apply that did not commit (same head) replays. Applying the same file again
    after the ledger moved is a new operation against the current state, not a replay of an
    old one whose outcome may since have been superseded."""
    digest = hashlib.sha256(jcs.canonicalize({
        "corpus": corpus, "decided_by": decided_by, "decisions": items,
        "ledger_head": ledger_head,
    })).hexdigest()
    return f"approvals:{digest[:32]}"


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_corpus_root(args.corpus_root)
    if args.command == "export":
        out_path = check_generated_destination(Path(args.out), root, what="backlog")
        async with await CorpusStorageContext.open(root, args.corpus) as ctx:
            registry = await ProposalStore(ctx).load()
            backlog = build_backlog(registry)
            check_backlog(backlog, ctx.config.pii_gate)
        write_json_atomic(out_path, backlog)
        return {"approved": backlog["count"], "backlog": str(out_path),
                "ledger_head": backlog["ledger_head"]}

    items = read_decisions(Path(args.decisions), args.corpus)
    async with await CorpusStorageContext.open(root, args.corpus) as ctx:
        op_id = args.op_id or default_op_id(
            args.corpus, args.decided_by, items, await ctx.proposals.head()
        )
        result = await ProposalStore(ctx).record_decisions(
            items, op_id=op_id, decided_by=args.decided_by
        )
    if result["superseded_since"]:
        print(
            f"WARNING: {len(result['superseded_since'])} decision(s) in this operation were "
            "changed by later decisions; 'status' is historical, 'current_status' is now.",
            file=sys.stderr,
        )
    return {**result, "op_id": op_id}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--corpus", required=True)
        p.add_argument("--corpus-root", default=None)

    a = sub.add_parser("apply", help="record the decisions of a paste-back file")
    common(a)
    a.add_argument("--decisions", required=True, help="proposed-class-approvals/v1 JSON")
    a.add_argument("--decided-by", required=True, help="the reviewer, as human:<name>")
    a.add_argument("--op-id", default=None, help="explicit operation ID (default: digest)")

    e = sub.add_parser("export", help="write the approved-only backlog")
    common(e)
    e.add_argument("--out", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except DecisionInvalid as exc:
        # The message names the item index and the rule (never a value); nothing was recorded.
        raise SystemExit(f"refused: {exc}") from None
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

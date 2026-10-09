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
          Signed input (drain plan U9): a decision body may carry ``signature``
          (a signed decision from ``folio-insights proposals sign-decision``),
          and the decisions file may instead be signed decisions themselves
          (see below). Every signature is verified before anything is recorded;
          ``--decided-by`` is then optional for decisions whose signer the
          signers file maps to a handle. With
          ``FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1`` an unsigned decision
          refuses the whole file.
  export  Write the approved-only backlog: only proposals whose current
          decision is ``approved``. The same ledger always gives the same
          bytes. The output passes the PII gate and the forbidden-key check,
          and the file must sit outside every git work tree and outside the
          corpus root.
  import-legacy
          Import the decided rows of the read-only legacy ``review.db`` table
          ``proposed_class_decisions`` into the ledger, as decisions by
          ``human:legacy-review-db`` with each row's original ``reviewed_at``
          in provenance. Explicit and idempotent: a second run imports nothing,
          and a proposal that already has a ledger decision is never overridden.
          Only each proposal's latest legacy row counts: when it is pending,
          invalid or PII-refused, the proposal is skipped.
          The database is opened read-only. ``--dry-run`` reports without
          writing. ``--seal`` then installs triggers that make the database
          refuse every write to the legacy table (the only write to review.db). Reports name legacy row IDs, never labels or notes.

Decisions file (``proposed-class-approvals/v1``)::

  {"schema": "proposed-class-approvals/v1", "corpus": "C",
   "decisions": {"PC-...": {"status": "approve", "note": "..."},
                 "PC-...": {"status": "merge", "merge_into": "PC-..."}}}

Signed decisions file: one signed decision (the ``sign-decision`` output), a JSON
list of them, or ``{"schema": "proposed-class-signed-decisions/v1", "corpus": "C",
"signed": [...]}``. Each must be kind ``proposed_class`` and name the proposal ID as
target; its verdict, rationale and ``detail.merge_into`` become the decision.

Usage:
  python scripts/apply_approvals.py apply  --corpus C --decisions FILE \\
      [--decided-by human:REVIEWER] [--op-id ID]
  python scripts/apply_approvals.py export --corpus C --out /outside/repo/backlog.json
  python scripts/apply_approvals.py import-legacy --corpus C \\
      --review-db OUTPUT/C/review.db [--legacy-corpus NAME] [--dry-run] [--seal]
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
from folio_insights.proposals.signed_decisions import (  # noqa: E402
    KIND_PROPOSED_CLASS,
    DecisionPolicyMisconfigured,
    DecisionSignatureRefused,
)
from folio_insights.persistence.review_db import (  # noqa: E402
    read_legacy_proposed_class_rows,
    seal_legacy_proposed_class_table,
)
from folio_insights.proposals.destinations import (  # noqa: E402
    check_generated_destination,
    write_json_atomic,
)
from folio_insights.proposals.legacy import (  # noqa: E402
    LegacyImportConflict,
    import_legacy_decisions,
)
from folio_insights.storage import CorpusStorageContext  # noqa: E402

DECISIONS_SCHEMAS = frozenset({"proposed-class-approvals/v1"})
SIGNED_DECISIONS_SCHEMA = "proposed-class-signed-decisions/v1"


def _is_signed_decision(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"body", "signature"}


def signed_items(signed: list[Any], corpus: str) -> list[dict[str, Any]]:
    """Decision items from signed decisions: the signed body names the proposal
    (``target``), the status (``verdict``), the note (``rationale``) and a merge's
    ``detail.merge_into``; the signature rides along and the store verifies it."""
    items = []
    for index, value in enumerate(signed):
        body = value.get("body") if _is_signed_decision(value) else None
        if not isinstance(body, dict):
            raise DecisionInvalid(f"signed decision {index}: must be an object with body and "
                                  "signature")
        if body.get("kind") != KIND_PROPOSED_CLASS:
            raise DecisionInvalid(f"signed decision {index}: kind must be {KIND_PROPOSED_CLASS!r}")
        if body.get("corpus") != corpus:
            raise DecisionInvalid(f"signed decision {index}: names a different corpus")
        detail = body.get("detail") or {}
        if not isinstance(detail, dict) or set(detail) - {"merge_into"}:
            raise DecisionInvalid(
                f"signed decision {index}: a proposed-class detail may only name merge_into"
            )
        item: dict[str, Any] = {
            "proposal_id": body.get("target"),
            "status": body.get("verdict"),
            "note": body.get("rationale", ""),
            "signature": value,
        }
        if detail.get("merge_into") is not None:
            item["merge_into"] = detail["merge_into"]
        items.append(item)
    if not items:
        raise DecisionInvalid("the signed decisions file holds no signed decision")
    return items


def read_decisions(path: Path, corpus: str) -> list[dict[str, Any]]:
    """Parse a paste-back file (or a signed decisions file) into decision items.
    Refuses a wrong schema, a file for another corpus or a malformed decisions map.
    Errors never echo values."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if _is_signed_decision(payload):
        return signed_items([payload], corpus)
    if isinstance(payload, list):
        return signed_items(payload, corpus)
    if isinstance(payload, dict) and payload.get("schema") == SIGNED_DECISIONS_SCHEMA:
        if payload.get("corpus") not in (None, corpus):
            raise DecisionInvalid("the decisions file names a different corpus")
        signed = payload.get("signed")
        if not isinstance(signed, list):
            raise DecisionInvalid("a signed decisions file needs a 'signed' list")
        return signed_items(signed, corpus)
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
    corpus: str, decided_by: str | None, items: list[dict[str, Any]], ledger_head: int
) -> str:
    """A digest of the corpus, reviewer, decisions and the ledger head they were applied at.

    Retrying an apply that did not commit (same head) replays. Applying the same file again
    after the ledger moved is a new operation against the current state, not a replay of an
    old one whose outcome may since have been superseded."""
    digest = hashlib.sha256(jcs.canonicalize({
        "corpus": corpus, "decided_by": decided_by or "signed", "decisions": items,
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

    if args.command == "import-legacy":
        rows = read_legacy_proposed_class_rows(Path(args.review_db))
        async with await CorpusStorageContext.open(root, args.corpus) as ctx:
            report = await import_legacy_decisions(
                ctx, rows, legacy_corpus=args.legacy_corpus, dry_run=args.dry_run
            )
        if args.seal and not args.dry_run:
            # Only after a successful import: the database then refuses legacy writes.
            report["sealed"] = seal_legacy_proposed_class_table(Path(args.review_db))
        return report

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
    a.add_argument(
        "--decided-by", default=None,
        help="the reviewer, as human:<name> (optional when every decision is signed by a "
        "signer the signers file maps to a handle)",
    )
    a.add_argument("--op-id", default=None, help="explicit operation ID (default: digest)")

    e = sub.add_parser("export", help="write the approved-only backlog")
    common(e)
    e.add_argument("--out", required=True)

    m = sub.add_parser(
        "import-legacy", help="import review.db proposed_class_decisions rows (idempotent)"
    )
    common(m)
    m.add_argument("--review-db", required=True, help="the legacy per-corpus review.db")
    m.add_argument(
        "--legacy-corpus", default=None,
        help="the review.db corpus_name to import (default: --corpus)",
    )
    m.add_argument("--dry-run", action="store_true", help="report without writing")
    m.add_argument(
        "--seal", action="store_true",
        help="after the import, install triggers that make review.db refuse legacy writes",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except (FileNotFoundError, LegacyImportConflict) as exc:
        raise SystemExit(f"refused: {exc}") from None
    except (DecisionInvalid, DecisionSignatureRefused) as exc:
        # The message names the item index and the rule (never a value); nothing was recorded.
        raise SystemExit(f"refused: {exc}") from None
    except DecisionPolicyMisconfigured as exc:
        raise SystemExit(f"refused: {exc}") from None
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Subprocess entry points for the cross-process proposal tests.

``python -m tests.proposals._proc write ROOT CORPUS`` collects two synthetic
runs, records a human judgment and runs deterministic dedupe in its own
process. ``... read ROOT CORPUS`` folds the ledger in a fresh process. Both
print the folded registry as one JSON line.

``... decide ROOT CORPUS`` records synthetic review decisions (U3) and prints
the approved-only backlog; ``... backlog ROOT CORPUS`` prints the backlog from
a fresh process. Both print canonical JSON, so a restart can be compared byte
for byte.
"""
from __future__ import annotations

import asyncio
import json
import sys

from folio_insights.proposals import ProposalStore, build_backlog
from folio_insights.proposals.destinations import canonical_json
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import lexicon, pc


async def _write(root: str, corpus: str) -> dict:
    async with await CorpusStorageContext.open(root, corpus) as ctx:
        store = ProposalStore(ctx)
        await store.collect_run(
            "run-1",
            [pc("Synthetic Tort Doctrine", "u1"), pc("Synthetic Filing Rituals", "u2"),
             pc("Synthetic Wrong Rule", "u3")],
            spans_by_unit={"u1": [0, 12], "u2": [13, 40]},
        )
        await store.collect_run(
            "run-2", [pc("Synthetic Filing Ritual", "u7"), pc("synthetic wrong-rule", "u8")]
        )
        pid = (await store.load()).by_label("Synthetic Wrong Rule").proposal_id
        await store.record_judgments(
            [{"proposal_id": pid, "verdict": "NOVEL", "judged_by": "human:synthetic-reviewer",
              "reasoning": "Synthetic: the alias concept's definition is unrelated."}],
            op_id="proc:judgment:1",
        )
        await store.apply_dedupe(lexicon())
        return (await store.load()).to_dict()


async def _read(root: str, corpus: str) -> dict:
    async with await CorpusStorageContext.open(root, corpus) as ctx:
        return (await ProposalStore(ctx).load()).to_dict()


async def _decide(root: str, corpus: str) -> str:
    await _write(root, corpus)
    async with await CorpusStorageContext.open(root, corpus) as ctx:
        store = ProposalStore(ctx)
        reg = await store.load()
        wrong = reg.by_label("Synthetic Wrong Rule").proposal_id
        ritual = reg.by_label("Synthetic Filing Rituals").proposal_id
        await store.record_decisions(
            [{"proposal_id": wrong, "status": "approve", "note": "Synthetic approval note."},
             {"proposal_id": ritual, "status": "reject"}],
            op_id="proc:decisions:1", decided_by="human:synthetic-reviewer",
        )
        return canonical_json(build_backlog(await store.load()))


async def _backlog(root: str, corpus: str) -> str:
    async with await CorpusStorageContext.open(root, corpus) as ctx:
        return canonical_json(build_backlog(await ProposalStore(ctx).load()))


def main() -> None:
    command, root, corpus = sys.argv[1:4]
    if command in {"decide", "backlog"}:
        fn = {"decide": _decide, "backlog": _backlog}[command]
        sys.stdout.write(asyncio.run(fn(root, corpus)))
        return
    fn = {"write": _write, "read": _read}[command]
    print(json.dumps(asyncio.run(fn(root, corpus)), sort_keys=True))


if __name__ == "__main__":
    main()

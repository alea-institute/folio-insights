"""Deterministic dedupe on stored proposals (U2). Synthetic data only.

Covers plural and primary-label dedupe, the unsafe-alias guardrail (an alias
hit stays a distinct proposal under review), judgments surviving dedupe and
later collection, idempotent re-runs, and validation of recorded judgments.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.proposals import FolioLexicon, ProposalStore, stem_label, survivors
from folio_insights.proposals.dedupe import ALIAS_GUARDRAIL
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import CONCEPTS, IRI_REMEDY, IRI_TORT, lexicon, pc

pytestmark = pytest.mark.storage


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


async def _collect(root: Path, run: str, labels: list[str], corpus: str = "corpus-a"):
    async with await CorpusStorageContext.open(root, corpus) as ctx:
        store = ProposalStore(ctx)
        await store.collect_run(run, [pc(label, f"{run}-u{i}") for i, label in enumerate(labels)])


async def _dedupe(root: Path, lex: FolioLexicon | None = None, corpus: str = "corpus-a",
                  min_concepts: int = 3):
    async with await CorpusStorageContext.open(root, corpus) as ctx:
        store = ProposalStore(ctx)
        summary = await store.apply_dedupe(lex or lexicon(), min_concepts=min_concepts)
        return summary, await store.load()


def test_stem_collapses_plurals_but_not_ss_us_is():
    assert stem_label("synthetic filing rituals") == "synthetic filing ritual"
    assert stem_label("synthetic remedies") == "synthetic remedy"
    assert stem_label("synthetic class status basis") == "synthetic class status basis"


async def test_primary_label_dedupe(storage_root: Path):
    await _collect(storage_root, "run-1", ["synthetic  TORT doctrine"])
    summary, reg = await _dedupe(storage_root)
    (p,) = reg.all()
    assert p.judgment["verdict"] == "DUPLICATE_OF"
    assert p.judgment["target_iri"] == IRI_TORT
    assert p.judgment["judged_by"] == "deterministic"
    assert "guardrail" not in p.judgment
    assert p.judgment["nearest"] == [{"iri": IRI_TORT, "label": "Synthetic Tort Doctrine",
                                      "match_form": "primary", "score": None}]
    assert summary["verdicts"] == {"DUPLICATE_OF": 1}
    assert survivors(reg) == []


async def test_plural_dedupe_merges_into_the_first_collected(storage_root: Path):
    await _collect(storage_root, "run-1", ["Synthetic Filing Rituals"])
    await _collect(storage_root, "run-2", ["Synthetic Filing Ritual"])
    _, reg = await _dedupe(storage_root)
    plural = reg.by_label("Synthetic Filing Rituals")
    singular = reg.by_label("Synthetic Filing Ritual")
    assert plural.proposal_id != singular.proposal_id  # two proposals, linked
    assert plural.judgment is None  # collected first: canonical survivor
    assert singular.judgment["verdict"] == "MERGE_WITH"
    assert singular.judgment["target_proposal_id"] == plural.proposal_id
    assert [p.proposal_id for p in survivors(reg)] == [plural.proposal_id]


async def test_unsafe_alias_match_stays_distinct(storage_root: Path):
    await _collect(storage_root, "run-1", ["Synthetic Wrong Rule", "Synthetic Relief Marker"])
    _, reg = await _dedupe(storage_root)
    alias = reg.by_label("Synthetic Wrong Rule")
    hidden = reg.by_label("Synthetic Relief Marker")
    for p, target in ((alias, IRI_TORT), (hidden, IRI_REMEDY)):
        assert p.judgment["verdict"] == "ALIAS_CANDIDATE"
        assert p.judgment["target_iri"] == target
        assert p.judgment["guardrail"] == ALIAS_GUARDRAIL
        assert p.decision["status"] == "pending"
    # Still two distinct proposals, both still awaiting a definition-level judgment.
    assert alias.proposal_id != hidden.proposal_id
    assert {p.proposal_id for p in survivors(reg)} == {alias.proposal_id, hidden.proposal_id}


async def test_existing_judgment_survives_dedupe_and_later_collection(storage_root: Path):
    await _collect(storage_root, "run-1", ["Synthetic Tort Doctrine"])
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        pid = (await store.load()).by_label("Synthetic Tort Doctrine").proposal_id
        await store.record_judgments(
            [{"proposal_id": pid, "verdict": "NOVEL", "judged_by": "human:synthetic-reviewer",
              "reasoning": "Synthetic reviewer: the definitions differ."}],
            op_id="test:judgment:1",
        )
    summary, reg = await _dedupe(storage_root)
    assert summary["changes"] == 0  # the primary-label hit does not overwrite it
    # A later run brings a case variant of the same label: same proposal, judgment kept.
    await _collect(storage_root, "run-2", ["SYNTHETIC tort doctrine"])
    summary, reg = await _dedupe(storage_root)
    p = reg.get(pid)
    assert summary["changes"] == 0
    assert p.judgment["verdict"] == "NOVEL"
    assert p.judgment["judged_by"] == "human:synthetic-reviewer"
    assert p.runs == ["run-1", "run-2"] and len(p.label_variants) == 2
    assert [h["op_id"] for h in p.judgment_history] == ["test:judgment:1"]


async def test_dedupe_is_idempotent(storage_root: Path):
    await _collect(storage_root, "run-1", ["Synthetic Tort Doctrine", "Synthetic Wrong Rule"])
    first, reg1 = await _dedupe(storage_root)
    second, reg2 = await _dedupe(storage_root)
    assert first["changes"] == 2 and second["changes"] == 0 and second["position"] is None
    assert reg1.to_dict() == reg2.to_dict()


async def test_stale_deterministic_judgment_is_cleared_with_history(storage_root: Path):
    await _collect(storage_root, "run-1", ["Synthetic Tort Doctrine"])
    await _dedupe(storage_root)
    smaller = FolioLexicon.from_concepts([c for c in CONCEPTS if c["iri"] != IRI_TORT])
    summary, reg = await _dedupe(storage_root, smaller, min_concepts=1)
    (p,) = reg.all()
    assert summary["verdicts"] == {"CLEARED": 1}
    assert p.judgment is None
    assert [h["judgment"]["verdict"] if h["judgment"] else None for h in p.judgment_history] == [
        "DUPLICATE_OF", None
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"proposal_id": "PC-0000000000000000", "verdict": "NOVEL", "judged_by": "human:x"},
        {"verdict": "APPROVED", "judged_by": "human:x"},
        {"verdict": "NOVEL", "judged_by": "deterministic"},
        {"verdict": "NOVEL"},
    ],
)
async def test_invalid_judgment_batch_records_nothing(storage_root: Path, bad: dict):
    await _collect(storage_root, "run-1", ["Synthetic Novel Rite"])
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        pid = (await store.load()).all()[0].proposal_id
        good = {"proposal_id": pid, "verdict": "NOVEL", "judged_by": "human:x"}
        with pytest.raises(ValueError):
            await store.record_judgments([good, {"proposal_id": pid, **bad}], op_id="t:bad")
        assert await ctx.proposals.head() == 0

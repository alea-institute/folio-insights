"""Registry: idempotency, upsert/merge, occurrences, provenance, stable IDs."""
from __future__ import annotations
import json

import pytest

from folio_insights.proposals.registry import (
    ProposalRegistry,
    normalize_label,
    proposal_id,
)


def _pc(label, uid, text="some supporting sentence about the concept"):
    return {
        "proposed_label": label,
        "extraction_path": "proposed_class",
        "confidence": 0.9,
        "source_unit_id": uid,
        "source_text": text,
        "source_section": [],
    }


@pytest.fixture
def reg(tmp_path):
    return ProposalRegistry.load(tmp_path / "registry.json")


def test_normalize_label():
    assert normalize_label("Case Preparation!") == "case preparation"
    assert normalize_label("  AI-driven  Legal  ") == "ai driven legal"
    assert normalize_label("Advocate’s Duty") == "advocate s duty"


def test_proposal_id_stable_and_content_addressed():
    a = proposal_id("case preparation", "def one")
    b = proposal_id("case preparation", "def one")
    c = proposal_id("case preparation", "def two")
    assert a == b and a != c and a.startswith("PC-")


def test_ingest_creates_entries(reg):
    stats = reg.ingest_run(
        [_pc("Impartiality", "u1"), _pc("Fairness", "u2")],
        run="r1", book="TA", chapter="1",
    )
    assert stats["new"] == 2
    assert len(reg.entries) == 2
    e = reg.by_normalized("impartiality")
    assert e["occurrences"] == 1
    assert e["provenance"] == {"books": ["TA"], "chapters": ["1"], "runs": ["r1"]}
    assert e["decision"]["status"] == "pending"


def test_same_label_multiple_units_aggregates(reg):
    reg.ingest_run(
        [_pc("Trial Strategy", "u1"), _pc("Trial Strategy", "u2"), _pc("Trial Strategy", "u3")],
        run="r1", book="TA", chapter="1",
    )
    e = reg.by_normalized("trial strategy")
    assert e["occurrences"] == 3
    assert len({s["unit_id"] for s in e["supporting_units"]}) == 3


def test_ingest_is_idempotent(reg, tmp_path):
    pcs = [_pc("Impartiality", "u1"), _pc("Case Preparation", "u2")]
    reg.ingest_run(pcs, run="r1", book="TA", chapter="1")
    reg.save()
    first = (tmp_path / "registry.json").read_text()

    # re-ingest identical run -> byte-identical state
    reg2 = ProposalRegistry.load(tmp_path / "registry.json")
    stats = reg2.ingest_run(pcs, run="r1", book="TA", chapter="1")
    reg2.save()
    second = (tmp_path / "registry.json").read_text()

    assert stats["new"] == 0
    assert stats["occurrences"] == 0
    assert first == second


def test_new_run_appends_and_merges_provenance(reg):
    reg.ingest_run([_pc("Impartiality", "u1")], run="r1", book="TA", chapter="1")
    reg.ingest_run([_pc("Impartiality", "u9")], run="r2", book="TA", chapter="2")
    e = reg.by_normalized("impartiality")
    assert set(e["provenance"]["chapters"]) == {"1", "2"}
    assert set(e["provenance"]["runs"]) == {"r1", "r2"}
    assert e["occurrences"] == 2
    assert e["first_seen_run"] == "r1" and e["last_seen_run"] == "r2"


def test_reload_roundtrip(reg, tmp_path):
    reg.ingest_run([_pc("Fairness", "u1")], run="r1", book="TA", chapter="1")
    reg.save()
    reloaded = ProposalRegistry.load(tmp_path / "registry.json")
    assert reloaded.by_normalized("fairness") is not None
    assert reloaded.by_normalized("fairness")["proposed_label"] == "Fairness"


def test_spans_attached_when_provided(reg):
    reg.ingest_run(
        [_pc("Voir Dire Plan", "u1")], run="r1", book="TA", chapter="1",
        spans_by_unit={"u1": {"span": [10, 42]}},
    )
    e = reg.by_normalized("voir dire plan")
    assert e["supporting_units"][0]["source_span"] == [10, 42]

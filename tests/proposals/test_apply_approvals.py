"""Approval round-trip: pasted decisions -> registry decision blocks -> backlog."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from apply_approvals import apply_decisions, export_backlog  # noqa: E402


def _registry():
    return {"schema": "proposed-class-registry/v1", "proposals": [
        {"proposal_id": "PC-a", "proposed_label": "Trial Strategy Memo",
         "draft_definition": "A memo laying out trial strategy.", "occurrences": 4,
         "provenance": {"books": ["TA"], "chapters": ["2"], "runs": ["r2"]},
         "supporting_units": [], "judge": {"verdict": "NOVEL", "nearest": []},
         "decision": {"status": "pending", "note": "", "decided_at": None}},
        {"proposal_id": "PC-b", "proposed_label": "witnesses",
         "draft_definition": "plural of witness", "occurrences": 9,
         "provenance": {"books": ["TA"], "chapters": ["1"], "runs": ["r1"]},
         "supporting_units": [], "judge": {"verdict": "DUPLICATE_OF", "target_iri": "IRI:w"},
         "decision": {"status": "pending", "note": "", "decided_at": None}},
    ]}


def test_apply_decisions_sets_status():
    reg = _registry()
    stats = apply_decisions(reg, {
        "PC-a": {"status": "approve", "note": "good gap"},
        "PC-b": {"status": "reject"},
    })
    assert stats == {"applied": 2, "skipped": 0}
    by = {e["proposal_id"]: e for e in reg["proposals"]}
    assert by["PC-a"]["decision"]["status"] == "approved"
    assert by["PC-a"]["decision"]["note"] == "good gap"
    assert by["PC-a"]["decision"]["decided_at"] is not None
    assert by["PC-b"]["decision"]["status"] == "rejected"


def test_unknown_id_skipped():
    reg = _registry()
    stats = apply_decisions(reg, {"PC-zzz": {"status": "approve"}})
    assert stats == {"applied": 0, "skipped": 1}


def test_export_backlog_only_approved():
    reg = _registry()
    apply_decisions(reg, {"PC-a": {"status": "approve"},
                          "PC-b": {"status": "reject"}})
    rows = export_backlog(reg)
    assert len(rows) == 1
    assert rows[0]["label"] == "Trial Strategy Memo"
    assert rows[0]["occurrences"] == 4
    assert rows[0]["judge_verdict"] == "NOVEL"


def test_approved_note_overrides_definition_in_backlog():
    reg = _registry()
    apply_decisions(reg, {"PC-a": {"status": "approve",
                                   "note": "Refined: a pre-trial strategic planning memo."}})
    rows = export_backlog(reg)
    assert rows[0]["draft_definition"].startswith("Refined:")


def test_invalid_status_becomes_pending():
    reg = _registry()
    apply_decisions(reg, {"PC-a": {"status": "banana"}})
    by = {e["proposal_id"]: e for e in reg["proposals"]}
    assert by["PC-a"]["decision"]["status"] == "pending"

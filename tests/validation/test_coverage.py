"""Phase 9 U1 (R4): coverage — task-tree leaves without authority shards."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.bfo.spine import ParentMapResolver
from folio_insights.models.task import DiscoveredTask, TaskHierarchy
from folio_insights.shards import Triple
from folio_insights.validation.coverage import (
    CoverageChecker,
    TaskNode,
    leaf_tasks,
    load_task_nodes,
    task_nodes_from_hierarchy,
)

from tests.validation.conftest import folio, iri, vshard

TASKS = [
    TaskNode("t-root", "Contract disputes", folio("ContractLaw")),
    TaskNode("t-formation", "Challenge formation", folio("ContractFormation"), "t-root"),
    TaskNode("t-consideration", "Argue lack of consideration", folio("Consideration"), "t-formation"),
    TaskNode("t-breach", "Plead breach", folio("BreachOfContract"), "t-root"),
    TaskNode("t-remedies", "Seek remedies", None, "t-root"),
]


def about(n: int, concept: str, speech_act: str = "holding", **kw):
    return vshard(n, triple=Triple(subject=concept, predicate="urn:x:p", object="urn:x:o"),
                  speech_act=speech_act, **kw)


def test_leaves_are_tasks_without_children() -> None:
    assert [t.id for t in leaf_tasks(TASKS)] == ["t-breach", "t-consideration", "t-remedies"]


def test_coverage_gap_is_reported_for_a_leaf_without_an_authority_shard() -> None:
    shards = [
        about(1, folio("BreachOfContract")),                          # authority: covers
        about(2, folio("Consideration"), speech_act="practitioner_advice"),  # not authority
    ]
    findings = CoverageChecker().check(TASKS, shards)
    by_task = {f.detail["task_id"]: f for f in findings}
    assert set(by_task) == {"t-consideration", "t-remedies"}
    gap = by_task["t-consideration"]
    assert gap.kind == "coverage_gap" and gap.checker == "coverage" and gap.severity == "warning"
    assert gap.detail["reason"] == "no_authority_shard"
    assert gap.detail["non_authority_shards"] == [iri(2)]
    assert gap.proposals == []
    unmapped = by_task["t-remedies"]
    assert unmapped.severity == "info" and unmapped.detail["reason"] == "unmapped_task"


def test_a_narrower_authority_covers_a_leaf_through_folio_ancestry() -> None:
    resolver = ParentMapResolver({folio("PromissoryEstoppel"): [folio("Consideration")]})
    shards = [about(1, folio("PromissoryEstoppel")), about(2, folio("BreachOfContract"))]
    covered = CoverageChecker(folio_resolver=resolver).check(TASKS, shards)
    assert {f.detail["task_id"] for f in covered} == {"t-remedies"}
    uncovered = CoverageChecker().check(TASKS, shards)
    assert {f.detail["task_id"] for f in uncovered} == {"t-consideration", "t-remedies"}


def test_superseded_authority_does_not_cover() -> None:
    shards = [about(1, folio("Consideration"), superseded_by=iri(9)), about(2, folio("BreachOfContract"))]
    found = {f.detail["task_id"] for f in CoverageChecker().check(TASKS, shards)}
    assert "t-consideration" in found


def test_task_nodes_from_hierarchy_and_both_discovery_file_shapes(tmp_path: Path) -> None:
    root = DiscoveredTask(id="r", label="Root", folio_iri=folio("ContractLaw"))
    leaf = DiscoveredTask(id="l", label="Leaf", folio_iri=folio("Consideration"), parent_task_id="r")
    nodes = task_nodes_from_hierarchy(TaskHierarchy(tasks=[root, leaf]))
    assert nodes == [TaskNode("r", "Root", folio("ContractLaw")),
                     TaskNode("l", "Leaf", folio("Consideration"), "r")]
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps({"task_hierarchy": TaskHierarchy(tasks=[root, leaf]).model_dump()}))
    assert load_task_nodes(discovery) == nodes
    tree = tmp_path / "task_tree.json"
    tree.write_text(json.dumps([
        {"id": "r", "parent_id": None, "label": "Root", "folio_iri": folio("ContractLaw")},
        {"id": "l", "parent_id": "r", "label": "Leaf", "folio_iri": folio("Consideration")},
    ]))
    assert load_task_nodes(tree) == nodes
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"something": 1}))
    with pytest.raises(ValueError, match="no task list"):
        load_task_nodes(bad)

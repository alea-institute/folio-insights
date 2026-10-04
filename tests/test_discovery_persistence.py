"""B4 discovery fixes transferred in governance plan U3 (synthetic data only).

* ``review.db`` has one schema of record (``folio_insights.persistence``) that the API
  re-exports, and one writer (``persist_discovery``) that both the CLI orchestrator and the
  API discovery runner use. Re-runs keep reviewer edits.
* The CLI discovery run writes ``review.db``, so ``export`` can read it, and ``export`` says
  when tasks exist but none is approved.
* FOLIO mapping runs after every candidate-creating stage.
* The OWL serializer skips proposed-class tasks (no FOLIO IRI) instead of crashing.
* Discovery's LLM calls use the provider API's ``complete`` (there is no ``generate``).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from folio_insights.config import Settings
from folio_insights.models.task import Contradiction, DiscoveredTask, TaskHierarchy
from folio_insights.persistence import SCHEMA_SQL, persist_discovery


def _hierarchy() -> TaskHierarchy:
    return TaskHierarchy(
        tasks=[
            DiscoveredTask(id="task-a", label="Synthetic Task A",
                           folio_iri="https://folio.test/SyntheticA"),
            DiscoveredTask(id="task-b", label="Synthetic Task B", folio_iri=None,
                           parent_task_id="task-a"),
        ],
        task_unit_links={"task-a": ["u1", "u2"], "task-b": ["u3"]},
    )


def _job(label_a: str = "Synthetic Task A"):
    hierarchy = _hierarchy()
    hierarchy.tasks[0].label = label_a
    return SimpleNamespace(
        task_hierarchy=hierarchy,
        contradictions=[Contradiction(task_id="task-a", unit_id_a="u1", unit_id_b="u2",
                                      nli_score=0.9)],
    )


def _rows(db: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def test_api_reexports_the_library_schema():
    from api.db.models import SCHEMA_SQL as api_schema

    assert api_schema is SCHEMA_SQL


async def test_persist_discovery_creates_and_upserts_without_clobbering_reviewers(tmp_path):
    db = tmp_path / "corpus" / "review.db"
    await persist_discovery(db, "synthetic", _job())
    assert _rows(db, "SELECT task_id, status, folio_iri FROM task_decisions ORDER BY task_id") == [
        ("task-a", "unreviewed", "https://folio.test/SyntheticA"),
        ("task-b", "unreviewed", None),
    ]
    assert len(_rows(db, "SELECT * FROM task_unit_links")) == 3
    assert len(_rows(db, "SELECT * FROM contradictions")) == 1

    with sqlite3.connect(db) as conn:  # a reviewer approves and edits task-a
        conn.execute("UPDATE task_decisions SET status='approved', edited_label='Edited' "
                     "WHERE task_id='task-a'")
    await persist_discovery(db, "synthetic", _job(label_a="Synthetic Task A v2"))
    assert _rows(db, "SELECT status, edited_label, label FROM task_decisions "
                     "WHERE task_id='task-a'") == [("approved", "Edited", "Synthetic Task A v2")]
    assert len(_rows(db, "SELECT * FROM task_unit_links")) == 3  # no duplicates
    assert len(_rows(db, "SELECT * FROM contradictions")) == 1


async def test_api_runner_writes_the_same_rows_as_the_library(tmp_path):
    from api.services.discovery_runner import _persist_discovery_to_sqlite

    await persist_discovery(tmp_path / "lib.db", "synthetic", _job())
    await _persist_discovery_to_sqlite(tmp_path / "api.db", "synthetic", _job())
    query = "SELECT task_id, corpus_name, folio_iri, label, parent_task_id FROM task_decisions"
    assert _rows(tmp_path / "lib.db", query) == _rows(tmp_path / "api.db", query)


def test_folio_mapping_runs_after_every_candidate_creating_stage():
    from folio_insights.pipeline.discovery.orchestrator import TaskDiscoveryOrchestrator

    names = [s.name for s in TaskDiscoveryOrchestrator(Settings())._stages]
    assert names.index("folio_mapping") > names.index("heading_analysis")
    assert names.index("folio_mapping") > names.index("content_clustering")
    assert names.index("folio_mapping") < names.index("hierarchy_construction")


class _StubStage:
    name = "stub_hierarchy"

    async def execute(self, job):
        job.task_hierarchy = _hierarchy()
        return job


async def test_orchestrator_run_writes_review_db(tmp_path):
    from folio_insights.pipeline.discovery.orchestrator import TaskDiscoveryOrchestrator

    corpus_dir = tmp_path / "synthetic"
    corpus_dir.mkdir()
    (corpus_dir / "extraction.json").write_text(json.dumps({"units": []}))
    orchestrator = TaskDiscoveryOrchestrator(Settings(output_dir=tmp_path))
    orchestrator._stages = [_StubStage()]
    await orchestrator.run("synthetic", resume=False)
    db = corpus_dir / "review.db"
    assert db.exists()
    assert {r[0] for r in _rows(db, "SELECT task_id FROM task_decisions")} == {"task-a", "task-b"}


def _seed_review_db(corpus_dir: Path, statuses: list[str]) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(corpus_dir / "review.db") as conn:
        conn.executescript(SCHEMA_SQL)
        for i, status in enumerate(statuses):
            conn.execute(
                "INSERT INTO task_decisions (task_id, corpus_name, label, status) "
                "VALUES (?, 'synthetic', ?, ?)",
                (f"task-{i}", f"Synthetic Task {i}", status),
            )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["unreviewed", "unreviewed"], "2 discovered but unreviewed"),
        ([], "No tasks found to export"),
    ],
)
def test_export_says_when_tasks_exist_but_none_is_approved(tmp_path, statuses, expected):
    from folio_insights.cli import cli

    _seed_review_db(tmp_path / "synthetic", statuses)
    result = CliRunner().invoke(cli, ["export", "synthetic", "--output", str(tmp_path)])
    assert result.exit_code == 1
    assert expected in result.output


# ---------- B4c: OWL export skips proposed classes ----------


def test_owl_serializer_skips_tasks_without_a_folio_iri():
    from rdflib import OWL, RDF, RDFS, URIRef

    from folio_insights.services.owl_serializer import OWLSerializer

    tasks = [
        {"id": "t1", "label": "Synthetic Mapped Task", "folio_iri": "https://folio.test/SynthA",
         "parent_task_id": None, "is_procedural": False, "canonical_order": 1,
         "is_manual": False, "status": "approved"},
        {"id": "t2", "label": "Synthetic Proposed Task", "folio_iri": None,
         "parent_task_id": "t1", "is_procedural": False, "canonical_order": 2,
         "is_manual": False, "status": "approved"},
        {"id": "t3", "label": "Synthetic Child Of Proposed", "folio_iri": "https://folio.test/SynthC",
         "parent_task_id": "t2", "is_procedural": False, "canonical_order": 3,
         "is_manual": False, "status": "approved"},
    ]
    units = {
        "t2": [{"id": "u-prop", "text": "A synthetic unit under a proposed task.",
                "unit_type": "advice", "confidence": 0.8, "source_file": "synthetic.md"}],
    }
    iri_map = {"u-prop": "https://folio.test/unit/u-prop"}
    g = OWLSerializer().build_graph(tasks, units, iri_map, [], {"corpus_name": "synthetic"})
    subjects = {str(s) for s, _, _ in g}
    assert (URIRef("https://folio.test/SynthA"), RDF.type, OWL.Class) in g
    assert (URIRef("https://folio.test/SynthC"), RDF.type, OWL.Class) in g
    assert "None" not in subjects and "" not in subjects
    assert "https://folio.test/unit/u-prop" not in subjects
    # A child of a proposed task gets no subClassOf to the missing parent.
    assert list(g.objects(URIRef("https://folio.test/SynthC"), RDFS.subClassOf)) == []


# ---------- discovery LLM calls use the provider's complete() ----------


class _CompleteOnly:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def complete(self, prompt: str, **kwargs) -> str:  # noqa: ARG002
        self.prompts.append(prompt)
        return json.dumps(self.payload)


async def test_content_clustering_labels_through_complete():
    from folio_insights.pipeline.discovery.stages.content_clustering import ContentClusteringStage

    llm = _CompleteOnly({"task_label": "Synthetic Label", "is_procedural": True,
                         "confidence": 0.7})
    label = await ContentClusteringStage(llm_bridge=llm)._label_cluster(["synthetic unit text"])
    assert label == ("Synthetic Label", True, 0.7) and llm.prompts


async def test_contradiction_analysis_uses_complete():
    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
    from folio_insights.services.contradiction_detector import ContradictionDetector

    def unit(uid: str, text: str) -> KnowledgeUnit:
        return KnowledgeUnit(id=uid, text=text, unit_type=KnowledgeType.ADVICE,
                             original_span=Span(start=0, end=len(text), source_file="s.md"),
                             source_file="s.md")

    llm = _CompleteOnly({"is_contradiction": True, "contradiction_type": "partial",
                         "explanation": "Synthetic explanation."})
    found = await ContradictionDetector(llm_bridge=llm).deep_analyze(
        unit("u1", "Always do the synthetic step."), unit("u2", "Never do the synthetic step.")
    )
    assert found is not None and found.contradiction_type == "partial" and llm.prompts


def test_no_discovery_module_calls_a_generate_method():
    root = Path(__file__).resolve().parents[1] / "src" / "folio_insights"
    for rel in ("pipeline/discovery/stages/content_clustering.py",
                "pipeline/discovery/stages/hierarchy_construction.py",
                "services/contradiction_detector.py"):
        source = (root / rel).read_text()
        assert "llm.generate(" not in source and "llm.complete(" in source

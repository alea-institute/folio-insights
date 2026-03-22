"""Tests for OWL export engine: IRI manager and OWL serializer.

Covers requirements: OWL-01, OWL-02, OWL-04, OWL-05, PIPE-01.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DC, OWL, PROV, RDF, RDFS, XSD

# --------------------------------------------------------------------------- #
# Shared fixtures and constants
# --------------------------------------------------------------------------- #

FOLIO_IRI_PATTERN = re.compile(
    r"^https://folio\.openlegalstandard\.org/[a-zA-Z0-9]+$"
)

SAMPLE_TASKS = [
    {
        "id": "task-1",
        "label": "Cross-Examination",
        "folio_iri": "https://folio.openlegalstandard.org/abc123",
        "parent_task_id": None,
        "is_procedural": True,
        "canonical_order": 1,
        "is_manual": False,
        "status": "approved",
    },
    {
        "id": "task-2",
        "label": "Impeachment Techniques",
        "folio_iri": "https://folio.openlegalstandard.org/def456",
        "parent_task_id": "task-1",
        "is_procedural": False,
        "canonical_order": 2,
        "is_manual": False,
        "status": "approved",
    },
]

SAMPLE_UNITS_BY_TASK = {
    "task-1": [
        {
            "id": "unit-1",
            "text": "Always control the witness with leading questions",
            "unit_type": "best_practice",
            "confidence": 0.92,
            "source_file": "trial-advocacy-ch5.md",
            "novelty_score": 0.3,
        },
        {
            "id": "unit-2",
            "text": "Never ask a question you don't know the answer to",
            "unit_type": "principle",
            "confidence": 0.88,
            "source_file": "trial-advocacy-ch5.md",
            "novelty_score": 0.1,
        },
        {
            "id": "unit-3",
            "text": "Asking open-ended questions loses control of testimony",
            "unit_type": "pitfall",
            "confidence": 0.75,
            "source_file": "trial-advocacy-ch5.md",
            "novelty_score": 0.5,
        },
    ],
    "task-2": [
        {
            "id": "unit-4",
            "text": "Use prior inconsistent statements to impeach credibility",
            "unit_type": "best_practice",
            "confidence": 0.95,
            "source_file": "trial-advocacy-ch6.md",
            "novelty_score": 0.2,
        },
    ],
}

SAMPLE_CONTRADICTIONS: list[dict] = []

SAMPLE_METADATA = {
    "corpus": "trial-advocacy",
    "total_tasks": 2,
    "total_units": 4,
}

SAMPLE_IRI_MAP = {
    "task-1": "https://folio.openlegalstandard.org/abc123",
    "task-2": "https://folio.openlegalstandard.org/def456",
    "unit-1": "https://folio.openlegalstandard.org/unit001",
    "unit-2": "https://folio.openlegalstandard.org/unit002",
    "unit-3": "https://folio.openlegalstandard.org/unit003",
    "unit-4": "https://folio.openlegalstandard.org/unit004",
}


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database with iri_registry schema."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS iri_registry (
            entity_id TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL,
            iri TEXT NOT NULL UNIQUE,
            corpus_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deprecated_at TEXT,
            superseded_by TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_iri_entity ON iri_registry(entity_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_iri_iri ON iri_registry(iri)"
    )
    conn.commit()
    conn.close()
    return db_path


# =========================================================================== #
# IRI Manager Tests
# =========================================================================== #


class TestGenerateFolioIRI:
    """Test standalone IRI generation (no DB)."""

    def test_iri_matches_folio_pattern(self) -> None:
        from folio_insights.services.iri_manager import generate_folio_iri

        iri = generate_folio_iri(set())
        assert FOLIO_IRI_PATTERN.match(iri), f"IRI does not match pattern: {iri}"

    def test_iri_rejects_collisions(self) -> None:
        from folio_insights.services.iri_manager import generate_folio_iri

        # Generate a first IRI, add to existing set, generate again -- should differ
        first = generate_folio_iri(set())
        second = generate_folio_iri({first})
        assert second != first
        assert FOLIO_IRI_PATTERN.match(second)

    def test_iri_uniqueness_batch(self) -> None:
        from folio_insights.services.iri_manager import generate_folio_iri

        iris = set()
        for _ in range(50):
            iri = generate_folio_iri(iris)
            assert iri not in iris, f"Duplicate IRI generated: {iri}"
            iris.add(iri)


class TestIRIManagerPersistence:
    """Test IRI persistence through IRIManager with SQLite."""

    @pytest.mark.asyncio
    async def test_get_or_create_returns_same_iri(self, tmp_db: Path) -> None:
        from folio_insights.services.iri_manager import IRIManager

        mgr = IRIManager(tmp_db)
        iri1 = await mgr.get_or_create_iri("ent-1", "task", "corpus-a")
        iri2 = await mgr.get_or_create_iri("ent-1", "task", "corpus-a")
        assert iri1 == iri2
        assert FOLIO_IRI_PATTERN.match(iri1)

    @pytest.mark.asyncio
    async def test_get_or_create_new_entity(self, tmp_db: Path) -> None:
        from folio_insights.services.iri_manager import IRIManager

        mgr = IRIManager(tmp_db)
        iri1 = await mgr.get_or_create_iri("ent-1", "task", "corpus-a")
        iri2 = await mgr.get_or_create_iri("ent-2", "unit", "corpus-a")
        assert iri1 != iri2
        assert FOLIO_IRI_PATTERN.match(iri2)

    @pytest.mark.asyncio
    async def test_deprecate_iri(self, tmp_db: Path) -> None:
        from folio_insights.services.iri_manager import IRIManager

        mgr = IRIManager(tmp_db)
        _old_iri = await mgr.get_or_create_iri("old-ent", "task", "corpus-a")
        _new_iri = await mgr.get_or_create_iri("new-ent", "task", "corpus-a")
        await mgr.deprecate_iri("old-ent", "new-ent")

        # Verify deprecated_at is set
        import aiosqlite

        async with aiosqlite.connect(str(tmp_db)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT deprecated_at, superseded_by FROM iri_registry WHERE entity_id = ?",
                ("old-ent",),
            )
            row = await cur.fetchone()
            assert row is not None
            assert row["deprecated_at"] is not None
            assert row["superseded_by"] == _new_iri

    @pytest.mark.asyncio
    async def test_load_all_iris(self, tmp_db: Path) -> None:
        from folio_insights.services.iri_manager import IRIManager

        mgr = IRIManager(tmp_db)
        iri1 = await mgr.get_or_create_iri("e1", "task", "corpus-a")
        iri2 = await mgr.get_or_create_iri("e2", "unit", "corpus-a")
        _other = await mgr.get_or_create_iri("e3", "task", "corpus-b")

        all_iris = await mgr.load_all_iris("corpus-a")
        assert iri1 in all_iris
        assert iri2 in all_iris
        assert len(all_iris) == 2


# =========================================================================== #
# OWL Serializer Tests
# =========================================================================== #


class TestOWLSerializer:
    """Test rdflib-based OWL graph construction."""

    def _build_graph(self) -> Graph:
        from folio_insights.services.owl_serializer import OWLSerializer

        ser = OWLSerializer()
        return ser.build_graph(
            SAMPLE_TASKS,
            SAMPLE_UNITS_BY_TASK,
            SAMPLE_IRI_MAP,
            SAMPLE_CONTRADICTIONS,
            SAMPLE_METADATA,
        )

    def test_ontology_declaration(self) -> None:
        g = self._build_graph()
        ont = URIRef("https://folio.openlegalstandard.org/modules/folio-insights")
        assert (ont, RDF.type, OWL.Ontology) in g

    def test_ontology_imports_folio_base(self) -> None:
        g = self._build_graph()
        ont = URIRef("https://folio.openlegalstandard.org/modules/folio-insights")
        assert (ont, OWL.imports, URIRef("https://folio.openlegalstandard.org/")) in g

    def test_task_classes_exist(self) -> None:
        g = self._build_graph()
        for task in SAMPLE_TASKS:
            task_iri = URIRef(task["folio_iri"])
            assert (task_iri, RDF.type, OWL.Class) in g

    def test_task_labels(self) -> None:
        g = self._build_graph()
        task1_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        assert (task1_iri, RDFS.label, Literal("Cross-Examination")) in g

    def test_task_subclass(self) -> None:
        g = self._build_graph()
        task2_iri = URIRef(SAMPLE_TASKS[1]["folio_iri"])
        parent_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        assert (task2_iri, RDFS.subClassOf, parent_iri) in g

    def test_procedural_annotation(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        task1_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        assert (
            task1_iri,
            FI.isProcedural,
            Literal(True, datatype=XSD.boolean),
        ) in g

    def test_unit_individuals(self) -> None:
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        assert (unit_iri, RDF.type, OWL.NamedIndividual) in g

    def test_unit_label(self) -> None:
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        labels = list(g.objects(unit_iri, RDFS.label))
        assert len(labels) == 1
        # Label truncated to 100 chars
        assert len(str(labels[0])) <= 100

    def test_unit_provenance(self) -> None:
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        prov_vals = list(g.objects(unit_iri, PROV.wasDerivedFrom))
        assert len(prov_vals) >= 1

    def test_unit_source(self) -> None:
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        sources = list(g.objects(unit_iri, DC.source))
        assert len(sources) == 1
        assert str(sources[0]) == "trial-advocacy-ch5.md"

    def test_unit_confidence(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        confs = list(g.objects(unit_iri, FI.confidence))
        assert len(confs) == 1

    def test_unit_novelty(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        novelties = list(g.objects(unit_iri, FI.noveltyScore))
        assert len(novelties) == 1

    def test_advice_text_annotation_best_practice(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        task1_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        bps = list(g.objects(task1_iri, FI.bestPractice))
        assert len(bps) >= 1

    def test_advice_text_annotation_principle(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        task1_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        principles = list(g.objects(task1_iri, FI.principle))
        assert len(principles) >= 1

    def test_advice_text_annotation_pitfall(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        task1_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        pitfalls = list(g.objects(task1_iri, FI.pitfall))
        assert len(pitfalls) >= 1

    def test_custom_annotation_property_declarations(self) -> None:
        from rdflib import Namespace

        FI = Namespace(
            "https://folio.openlegalstandard.org/modules/folio-insights/"
        )
        g = self._build_graph()
        for prop_name in [
            "bestPractice",
            "principle",
            "pitfall",
            "confidence",
            "noveltyScore",
            "unitType",
            "isProcedural",
            "sourceFile",
            "contradictionNote",
        ]:
            prop_iri = FI[prop_name]
            assert (prop_iri, RDF.type, OWL.AnnotationProperty) in g, (
                f"{prop_name} not declared as AnnotationProperty"
            )

    def test_serialize_rdfxml(self) -> None:
        from folio_insights.services.owl_serializer import OWLSerializer

        g = self._build_graph()
        ser = OWLSerializer()
        xml = ser.serialize_rdfxml(g)
        assert "<owl:Ontology" in xml

    def test_serialize_turtle(self) -> None:
        from folio_insights.services.owl_serializer import OWLSerializer

        g = self._build_graph()
        ser = OWLSerializer()
        ttl = ser.serialize_turtle(g)
        assert "@prefix folio:" in ttl or "folio:" in ttl

    def test_unit_typed_to_parent_task_class(self) -> None:
        g = self._build_graph()
        unit_iri = URIRef(SAMPLE_IRI_MAP["unit-1"])
        task1_iri = URIRef(SAMPLE_TASKS[0]["folio_iri"])
        assert (unit_iri, RDF.type, task1_iri) in g

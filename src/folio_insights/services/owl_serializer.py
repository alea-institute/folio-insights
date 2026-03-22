"""OWL ontology graph construction from approved review data.

Builds an rdflib Graph representing a FOLIO-compatible OWL module containing
task classes with annotation properties and knowledge unit individuals with
full metadata (confidence, provenance, source, novelty scores).

Uses SKOS/PROV-O/Dublin Core as annotation properties within a single OWL file,
per the CONTEXT.md decision: "everything in one OWL file."
"""

from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DC, OWL, PROV, RDF, RDFS, SKOS, XSD

# Namespaces
FOLIO = Namespace("https://folio.openlegalstandard.org/")
FOLIO_INSIGHTS = Namespace(
    "https://folio.openlegalstandard.org/modules/folio-insights/"
)

# Module IRI (no trailing slash -- this is the ontology identifier)
ONTOLOGY_IRI = URIRef(
    "https://folio.openlegalstandard.org/modules/folio-insights"
)

# Custom annotation properties defined by folio-insights
_CUSTOM_ANNOTATION_PROPERTIES = [
    "bestPractice",
    "principle",
    "pitfall",
    "confidence",
    "noveltyScore",
    "unitType",
    "isProcedural",
    "sourceFile",
    "contradictionNote",
]

# Map unit_type values to their corresponding FI annotation property
_UNIT_TYPE_TO_ANNOTATION = {
    "best_practice": "bestPractice",
    "principle": "principle",
    "pitfall": "pitfall",
}


class OWLSerializer:
    """Build and serialize OWL ontology graphs from review data.

    Constructs a complete rdflib Graph from approved task/unit data
    and serializes to RDF/XML or Turtle format.
    """

    def build_graph(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        iri_map: dict[str, str],
        contradictions: list[dict],
        metadata: dict,
    ) -> Graph:
        """Build a complete OWL graph from approved review data.

        Args:
            tasks: List of approved task dicts with id, label, folio_iri, etc.
            units_by_task: Dict mapping task_id to lists of unit dicts.
            iri_map: Dict mapping entity_id to IRI string for units.
            contradictions: List of contradiction dicts.
            metadata: Export metadata (corpus name, counts, etc.).

        Returns:
            An rdflib Graph containing the complete OWL ontology.
        """
        g = Graph()

        # Bind ALL namespaces before adding any triples (prevents ns1: artifacts)
        g.bind("folio", FOLIO)
        g.bind("owl", OWL)
        g.bind("rdf", RDF)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)
        g.bind("skos", SKOS)
        g.bind("dc", DC)
        g.bind("prov", PROV)
        g.bind("fi", FOLIO_INSIGHTS)

        # 1. Ontology declaration
        self._add_ontology_declaration(g, metadata)

        # 2. Declare custom annotation properties
        self._declare_annotation_properties(g)

        # 3. Build task-id -> IRI lookup for parent resolution
        task_iri_lookup = {t["id"]: t["folio_iri"] for t in tasks}

        # 4. Add task classes
        for task in tasks:
            self._add_task_class(g, task, task_iri_lookup, units_by_task)

        # 5. Add knowledge unit individuals
        for task in tasks:
            task_units = units_by_task.get(task["id"], [])
            for unit in task_units:
                self._add_unit_individual(g, unit, iri_map, task)

        # 6. Add contradiction annotations
        for contradiction in contradictions:
            self._add_contradiction(g, contradiction, task_iri_lookup)

        return g

    def serialize_rdfxml(self, graph: Graph) -> str:
        """Serialize the graph as RDF/XML."""
        return graph.serialize(format="xml")

    def serialize_turtle(self, graph: Graph) -> str:
        """Serialize the graph as Turtle."""
        return graph.serialize(format="turtle")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _add_ontology_declaration(g: Graph, metadata: dict) -> None:
        """Add the owl:Ontology declaration with imports and metadata."""
        g.add((ONTOLOGY_IRI, RDF.type, OWL.Ontology))
        g.add(
            (
                ONTOLOGY_IRI,
                OWL.imports,
                URIRef("https://folio.openlegalstandard.org/"),
            )
        )
        g.add(
            (ONTOLOGY_IRI, RDFS.label, Literal("FOLIO Insights Module"))
        )
        g.add(
            (
                ONTOLOGY_IRI,
                DC.description,
                Literal(
                    "Legal advocacy knowledge extracted and structured "
                    "by folio-insights"
                ),
            )
        )

    @staticmethod
    def _declare_annotation_properties(g: Graph) -> None:
        """Declare all custom annotation properties as owl:AnnotationProperty."""
        for prop_name in _CUSTOM_ANNOTATION_PROPERTIES:
            prop_iri = FOLIO_INSIGHTS[prop_name]
            g.add((prop_iri, RDF.type, OWL.AnnotationProperty))

    @staticmethod
    def _add_task_class(
        g: Graph,
        task: dict,
        task_iri_lookup: dict[str, str],
        units_by_task: dict[str, list[dict]],
    ) -> None:
        """Add a task as an owl:Class with label, subclass, and annotations."""
        task_iri = URIRef(task["folio_iri"])

        # Class declaration
        g.add((task_iri, RDF.type, OWL.Class))

        # Label (prefer edited_label if present)
        label = task.get("edited_label") or task["label"]
        g.add((task_iri, RDFS.label, Literal(label)))

        # Subclass relationship
        parent_id = task.get("parent_task_id")
        if parent_id and parent_id in task_iri_lookup:
            parent_iri = URIRef(task_iri_lookup[parent_id])
            g.add((task_iri, RDFS.subClassOf, parent_iri))

        # Procedural annotation
        if task.get("is_procedural"):
            g.add(
                (
                    task_iri,
                    FOLIO_INSIGHTS.isProcedural,
                    Literal(True, datatype=XSD.boolean),
                )
            )

        # Aggregate advice text annotations by unit type on the task class
        task_units = units_by_task.get(task["id"], [])
        for unit in task_units:
            unit_type = unit.get("unit_type", "")
            annotation_prop = _UNIT_TYPE_TO_ANNOTATION.get(unit_type)
            if annotation_prop:
                g.add(
                    (
                        task_iri,
                        FOLIO_INSIGHTS[annotation_prop],
                        Literal(unit.get("text", "")),
                    )
                )

    @staticmethod
    def _add_unit_individual(
        g: Graph,
        unit: dict,
        iri_map: dict[str, str],
        task: dict,
    ) -> None:
        """Add a knowledge unit as an owl:NamedIndividual with metadata."""
        unit_id = unit["id"]
        iri_str = iri_map.get(unit_id)
        if not iri_str:
            return  # Skip units without an IRI mapping

        unit_iri = URIRef(iri_str)

        # Individual declaration
        g.add((unit_iri, RDF.type, OWL.NamedIndividual))

        # Type link to parent task class
        task_iri = URIRef(task["folio_iri"])
        g.add((unit_iri, RDF.type, task_iri))

        # Label (truncated to 100 chars)
        text = unit.get("text", "")
        g.add((unit_iri, RDFS.label, Literal(text[:100])))

        # Full text as SKOS note
        g.add((unit_iri, SKOS.note, Literal(text)))

        # Unit type
        g.add(
            (
                unit_iri,
                FOLIO_INSIGHTS.unitType,
                Literal(unit.get("unit_type", "unknown")),
            )
        )

        # Confidence
        confidence = unit.get("confidence", 0)
        g.add(
            (
                unit_iri,
                FOLIO_INSIGHTS.confidence,
                Literal(float(confidence), datatype=XSD.float),
            )
        )

        # Novelty score (if present)
        novelty = unit.get("novelty_score")
        if novelty is not None:
            g.add(
                (
                    unit_iri,
                    FOLIO_INSIGHTS.noveltyScore,
                    Literal(float(novelty), datatype=XSD.float),
                )
            )

        # Provenance -- source lineage
        source_file = unit.get("source_file", "")
        lineage = unit.get("lineage", source_file)
        g.add((unit_iri, PROV.wasDerivedFrom, Literal(str(lineage))))

        # Source file
        g.add((unit_iri, DC.source, Literal(source_file)))

    @staticmethod
    def _add_contradiction(
        g: Graph,
        contradiction: dict,
        task_iri_lookup: dict[str, str],
    ) -> None:
        """Add a contradiction annotation to the relevant task class."""
        task_id = contradiction.get("task_id")
        if not task_id or task_id not in task_iri_lookup:
            return

        task_iri = URIRef(task_iri_lookup[task_id])
        note = (
            f"Contradiction between {contradiction.get('unit_id_a', '?')} "
            f"and {contradiction.get('unit_id_b', '?')} "
            f"(type: {contradiction.get('contradiction_type', 'unknown')}, "
            f"resolution: {contradiction.get('resolution', 'unresolved')})"
        )
        g.add((task_iri, FOLIO_INSIGHTS.contradictionNote, Literal(note)))

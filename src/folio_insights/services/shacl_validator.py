"""SHACL validation and report generation for OWL export graphs.

Validates generated OWL ontologies against structural shapes (shapes.ttl)
and performs additional checks for IRI uniqueness, referential integrity,
and namespace consistency. Produces a markdown validation report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pyshacl
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF

# Namespace for folio-insights custom terms
FOLIO_INSIGHTS = Namespace(
    "https://folio.openlegalstandard.org/modules/folio-insights/"
)

# Path to the SHACL shapes file
_SHAPES_PATH = Path(__file__).parent.parent / "export" / "shapes.ttl"


@dataclass
class ValidationResult:
    """Result of SHACL validation."""

    conforms: bool
    violations: list[str]
    results_text: str


@dataclass
class CheckResult:
    """Result of a single validation check."""

    name: str
    status: str  # "PASS", "WARN", or "FAIL"
    details: str


@dataclass
class ValidationReport:
    """Complete validation report with all checks."""

    conforms: bool
    markdown: str
    checks: list[CheckResult] = field(default_factory=list)


class SHACLValidator:
    """Validate OWL graphs against SHACL shapes and structural checks.

    Loads shapes from shapes.ttl and runs pyshacl validation plus additional
    checks for IRI uniqueness, referential integrity, and namespace consistency.
    """

    def __init__(self, shapes_path: Path | None = None) -> None:
        self._shapes_path = shapes_path or _SHAPES_PATH
        self._shapes_graph: Graph | None = None

    def _load_shapes(self) -> Graph:
        """Lazy-load the SHACL shapes graph."""
        if self._shapes_graph is None:
            self._shapes_graph = Graph()
            self._shapes_graph.parse(str(self._shapes_path), format="turtle")
        return self._shapes_graph

    def validate(self, data_graph: Graph) -> ValidationResult:
        """Run SHACL validation against the shapes graph.

        Args:
            data_graph: The rdflib Graph to validate.

        Returns:
            ValidationResult with conformance status and any violations.
        """
        shapes = self._load_shapes()
        conforms, _results_graph, results_text = pyshacl.validate(
            data_graph,
            shacl_graph=shapes,
            inference="none",
            abort_on_first=False,
        )

        violations: list[str] = []
        if not conforms:
            # Parse violation messages from results text
            for line in results_text.splitlines():
                line = line.strip()
                if line.startswith("Message:"):
                    violations.append(line.replace("Message:", "").strip())
                elif line.startswith("Constraint Violation"):
                    violations.append(line)

            # Ensure at least one violation is reported
            if not violations and not conforms:
                violations.append(results_text.strip())

        return ValidationResult(
            conforms=conforms,
            violations=violations,
            results_text=results_text,
        )

    def check_iri_uniqueness(self, graph: Graph) -> list[str]:
        """Check for duplicate IRIs in the graph.

        Examines all subjects to find any IRI used as subject for
        multiple distinct rdf:type declarations of the same type.

        Returns:
            List of violation messages for duplicate IRIs.
        """
        seen_subjects: dict[str, int] = {}
        violations: list[str] = []

        for s in graph.subjects():
            if isinstance(s, URIRef):
                iri = str(s)
                seen_subjects[iri] = seen_subjects.get(iri, 0) + 1

        # All subjects naturally appear multiple times (once per triple).
        # What we check is whether multiple resources share the same IRI
        # as both a Class and NamedIndividual (actual collision).
        class_iris = {
            str(s) for s in graph.subjects(RDF.type, OWL.Class)
        }
        individual_iris = {
            str(s) for s in graph.subjects(RDF.type, OWL.NamedIndividual)
        }
        overlap = class_iris & individual_iris
        for iri in overlap:
            violations.append(
                f"IRI used as both owl:Class and owl:NamedIndividual: {iri}"
            )

        return violations

    def check_referential_integrity(self, graph: Graph) -> list[str]:
        """Check for dangling references within the FOLIO_INSIGHTS namespace.

        For each object that is a URIRef within the FOLIO_INSIGHTS namespace,
        verify it exists as a subject in the graph.

        Returns:
            List of violation messages for dangling references.
        """
        fi_ns = str(FOLIO_INSIGHTS)
        all_subjects = {str(s) for s in graph.subjects() if isinstance(s, URIRef)}
        violations: list[str] = []

        for _s, _p, o in graph:
            if isinstance(o, URIRef):
                o_str = str(o)
                if o_str.startswith(fi_ns) and o_str not in all_subjects:
                    # Exclude annotation property declarations (they reference
                    # the namespace but don't need to be defined as subjects)
                    if not o_str.endswith("/"):
                        violations.append(f"Dangling reference: {o_str}")

        return violations

    def check_namespace_consistency(self, graph: Graph) -> list[str]:
        """Check for auto-generated namespace prefixes (ns1:, ns2:, etc.).

        Returns:
            List of warnings about namespace issues.
        """
        violations: list[str] = []
        ttl = graph.serialize(format="turtle")
        for i in range(1, 20):
            prefix = f"ns{i}:"
            if prefix in ttl:
                violations.append(
                    f"Auto-generated namespace prefix found: {prefix}"
                )
        return violations

    def generate_report(self, graph: Graph) -> ValidationReport:
        """Run all validation checks and produce a markdown report.

        Args:
            graph: The rdflib Graph to validate.

        Returns:
            ValidationReport with full markdown and individual check results.
        """
        checks: list[CheckResult] = []

        # 1. SHACL shapes
        shacl_result = self.validate(graph)
        checks.append(
            CheckResult(
                name="SHACL Shapes",
                status="PASS" if shacl_result.conforms else "FAIL",
                details=(
                    "No violations"
                    if shacl_result.conforms
                    else f"{len(shacl_result.violations)} violations"
                ),
            )
        )

        # 2. IRI uniqueness
        iri_violations = self.check_iri_uniqueness(graph)
        checks.append(
            CheckResult(
                name="IRI Uniqueness",
                status="PASS" if not iri_violations else "FAIL",
                details=(
                    "No duplicates"
                    if not iri_violations
                    else f"{len(iri_violations)} duplicates"
                ),
            )
        )

        # 3. Referential integrity
        ref_violations = self.check_referential_integrity(graph)
        checks.append(
            CheckResult(
                name="Referential Integrity",
                status="PASS" if not ref_violations else "FAIL",
                details=(
                    "No dangling references"
                    if not ref_violations
                    else f"{len(ref_violations)} dangling"
                ),
            )
        )

        # 4. Namespace consistency
        ns_violations = self.check_namespace_consistency(graph)
        checks.append(
            CheckResult(
                name="Namespace Consistency",
                status="PASS" if not ns_violations else "WARN",
                details=(
                    "All namespaces bound"
                    if not ns_violations
                    else f"{len(ns_violations)} auto-generated prefixes"
                ),
            )
        )

        # Statistics
        num_classes = len(list(graph.subjects(RDF.type, OWL.Class)))
        num_individuals = len(
            list(graph.subjects(RDF.type, OWL.NamedIndividual))
        )
        num_triples = len(graph)

        # Build overall conformance
        overall = all(c.status != "FAIL" for c in checks)

        # Build markdown
        lines = [
            "# Validation Report",
            "",
            "## Summary",
            "| Check | Status | Details |",
            "|-------|--------|---------|",
        ]
        for c in checks:
            lines.append(f"| {c.name} | {c.status} | {c.details} |")

        # SHACL violations detail
        if not shacl_result.conforms:
            lines.extend(["", "## SHACL Violations"])
            for v in shacl_result.violations:
                lines.append(f"- {v}")

        # IRI violations detail
        if iri_violations:
            lines.extend(["", "## IRI Uniqueness Issues"])
            for v in iri_violations:
                lines.append(f"- {v}")

        # Referential integrity detail
        if ref_violations:
            lines.extend(["", "## Referential Integrity Issues"])
            for v in ref_violations:
                lines.append(f"- {v}")

        # Namespace detail
        if ns_violations:
            lines.extend(["", "## Namespace Issues"])
            for v in ns_violations:
                lines.append(f"- {v}")

        # Statistics
        lines.extend(
            [
                "",
                "## Statistics",
                f"- Classes: {num_classes}",
                f"- Individuals: {num_individuals}",
                f"- Triples: {num_triples}",
            ]
        )

        md = "\n".join(lines) + "\n"

        return ValidationReport(conforms=overall, markdown=md, checks=checks)

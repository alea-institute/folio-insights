"""Diff computation and CHANGELOG.md generation for OWL exports.

Compares new and previous OWL graphs at the entity level (task classes and
knowledge unit individuals) to produce a structured changelog showing
what was added, removed, changed, and unchanged between exports.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS


class ChangelogGenerator:
    """Generate structured changelogs from OWL graph diffs."""

    def generate(
        self,
        new_graph: Graph,
        prev_graph: Graph | None,
        corpus_name: str,
    ) -> str:
        """Generate a CHANGELOG.md from current and previous graphs.

        Args:
            new_graph: The newly generated OWL graph.
            prev_graph: The previous export's graph, or None for first export.
            corpus_name: Name of the corpus being exported.

        Returns:
            Markdown string containing the changelog.
        """
        iso_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if prev_graph is None:
            return self._first_export_changelog(new_graph, corpus_name, iso_date)

        return self._diff_changelog(new_graph, prev_graph, corpus_name, iso_date)

    def load_previous_graph(self, owl_path: Path) -> Graph | None:
        """Load the previous export's graph from the .owl.prev file.

        Args:
            owl_path: Path to the current OWL file.

        Returns:
            Parsed Graph if .owl.prev exists, else None.
        """
        prev_path = owl_path.with_suffix(".owl.prev")
        if not prev_path.exists():
            return None
        g = Graph()
        g.parse(str(prev_path), format="xml")
        return g

    def archive_current(self, owl_path: Path) -> None:
        """Archive the current OWL file as .owl.prev for future diffs.

        Args:
            owl_path: Path to the current OWL file.
        """
        if owl_path.exists():
            prev_path = owl_path.with_suffix(".owl.prev")
            shutil.copy2(str(owl_path), str(prev_path))

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_classes(graph: Graph) -> dict[str, str]:
        """Extract task class IRIs and their labels from a graph.

        Returns dict mapping IRI string to label string.
        """
        classes: dict[str, str] = {}
        for s in graph.subjects(RDF.type, OWL.Class):
            if isinstance(s, URIRef):
                iri = str(s)
                labels = list(graph.objects(s, RDFS.label))
                label = str(labels[0]) if labels else iri
                classes[iri] = label
        return classes

    @staticmethod
    def _extract_individuals(graph: Graph) -> dict[str, str]:
        """Extract individual IRIs and their labels from a graph.

        Returns dict mapping IRI string to label string.
        """
        individuals: dict[str, str] = {}
        for s in graph.subjects(RDF.type, OWL.NamedIndividual):
            if isinstance(s, URIRef):
                iri = str(s)
                labels = list(graph.objects(s, RDFS.label))
                label = str(labels[0]) if labels else iri
                individuals[iri] = label
        return individuals

    def _first_export_changelog(
        self, graph: Graph, corpus_name: str, iso_date: str
    ) -> str:
        """Generate changelog for a first-time export (no previous graph)."""
        classes = self._extract_classes(graph)
        individuals = self._extract_individuals(graph)

        lines = [
            "# CHANGELOG",
            "",
            "## Export Summary",
            f"- Corpus: {corpus_name}",
            f"- Date: {iso_date}",
            "- Previous export: no",
            "- First export",
            "",
            "## Statistics",
            "| Category | Count |",
            "|----------|-------|",
            f"| Task classes | {len(classes)} |",
            f"| Individuals | {len(individuals)} |",
            f"| Total triples | {len(graph)} |",
        ]

        if classes:
            lines.extend(["", "## Task Classes"])
            for iri, label in sorted(classes.items(), key=lambda x: x[1]):
                lines.append(f"- {label} (`{iri}`)")

        if individuals:
            lines.extend(
                ["", "## Knowledge Units", f"- {len(individuals)} knowledge units"]
            )

        return "\n".join(lines) + "\n"

    def _diff_changelog(
        self,
        new_graph: Graph,
        prev_graph: Graph,
        corpus_name: str,
        iso_date: str,
    ) -> str:
        """Generate changelog by diffing two graphs."""
        new_classes = self._extract_classes(new_graph)
        prev_classes = self._extract_classes(prev_graph)
        new_individuals = self._extract_individuals(new_graph)
        prev_individuals = self._extract_individuals(prev_graph)

        # Set operations on IRI keys
        added_class_iris = set(new_classes) - set(prev_classes)
        removed_class_iris = set(prev_classes) - set(new_classes)
        common_class_iris = set(new_classes) & set(prev_classes)

        added_ind_iris = set(new_individuals) - set(prev_individuals)
        removed_ind_iris = set(prev_individuals) - set(new_individuals)
        common_ind_iris = set(new_individuals) & set(prev_individuals)

        # Detect label changes in common classes
        changed_classes: dict[str, tuple[str, str]] = {}
        for iri in common_class_iris:
            old_label = prev_classes[iri]
            new_label = new_classes[iri]
            if old_label != new_label:
                changed_classes[iri] = (old_label, new_label)

        unchanged_classes = len(common_class_iris) - len(changed_classes)

        # Detect label changes in common individuals
        changed_inds: dict[str, tuple[str, str]] = {}
        for iri in common_ind_iris:
            old_label = prev_individuals[iri]
            new_label = new_individuals[iri]
            if old_label != new_label:
                changed_inds[iri] = (old_label, new_label)

        unchanged_inds = len(common_ind_iris) - len(changed_inds)

        lines = [
            "# CHANGELOG",
            "",
            "## Export Summary",
            f"- Corpus: {corpus_name}",
            f"- Date: {iso_date}",
            "- Previous export: yes",
            "",
            "## Statistics",
            "| Category | Added | Removed | Changed | Unchanged |",
            "|----------|-------|---------|---------|-----------|",
            f"| Task classes | {len(added_class_iris)} | {len(removed_class_iris)} "
            f"| {len(changed_classes)} | {unchanged_classes} |",
            f"| Individuals | {len(added_ind_iris)} | {len(removed_ind_iris)} "
            f"| {len(changed_inds)} | {unchanged_inds} |",
        ]

        # New task classes
        if added_class_iris:
            lines.extend(["", "## New Task Classes"])
            for iri in sorted(added_class_iris):
                label = new_classes[iri]
                lines.append(f"- {label} (`{iri}`)")

        # Removed task classes
        if removed_class_iris:
            lines.extend(["", "## Removed Task Classes"])
            for iri in sorted(removed_class_iris):
                label = prev_classes[iri]
                lines.append(f"- {label} (`{iri}`)")

        # Changed tasks
        if changed_classes:
            lines.extend(["", "## Changed Tasks"])
            for iri, (old_label, new_label) in sorted(changed_classes.items()):
                lines.append(f'- {new_label}: label changed from "{old_label}"')

        # New individuals
        if added_ind_iris:
            lines.extend(
                [
                    "",
                    "## New Individuals",
                    f"- {len(added_ind_iris)} new knowledge units added",
                ]
            )

        # Removed individuals
        if removed_ind_iris:
            lines.extend(
                [
                    "",
                    "## Removed Individuals",
                    f"- {len(removed_ind_iris)} knowledge units removed",
                ]
            )

        return "\n".join(lines) + "\n"

"""Per-task JSON-LD chunk builder for RAG retrieval.

Generates compact JSON-LD objects per task class with all knowledge units,
subtasks, and metadata inlined. Outputs JSONL format (one JSON object per line)
for easy ingestion into vector databases and streaming processors.

Uses a custom compact form (not rdflib's expanded JSON-LD) to keep chunks
small (~500-2000 tokens per task) and human-readable.
"""

from __future__ import annotations

import json
from pathlib import Path


class JSONLDBuilder:
    """Build per-task JSON-LD chunks for RAG consumption."""

    def build_task_chunk(
        self,
        task: dict,
        units: list[dict],
        subtasks: list[dict],
        iri_map: dict[str, str],
    ) -> dict:
        """Build a compact JSON-LD chunk for a single task.

        Args:
            task: Task dict with id, label, folio_iri, is_procedural, etc.
            units: List of unit dicts linked to this task.
            subtasks: List of child task dicts.
            iri_map: Mapping from entity_id to IRI string.

        Returns:
            A compact JSON-LD dict ready for serialization.
        """
        chunk: dict = {
            "@context": "./context.jsonld",
            "@id": task.get("folio_iri", iri_map.get(task["id"], "")),
            "@type": "owl:Class",
            "rdfs:label": task.get("label", ""),
            "fi:isProcedural": task.get("is_procedural", False),
        }

        # Subclass reference to parent
        parent_id = task.get("parent_task_id")
        if parent_id and parent_id in iri_map:
            chunk["rdfs:subClassOf"] = {"@id": iri_map[parent_id]}

        # Subtasks
        if subtasks:
            chunk["fi:subtasks"] = [
                {
                    "@id": st.get("folio_iri", iri_map.get(st["id"], "")),
                    "rdfs:label": st.get("label", ""),
                }
                for st in subtasks
            ]

        # Units
        chunk["fi:units"] = [
            {
                "@id": iri_map.get(u["id"], ""),
                "@type": "owl:NamedIndividual",
                "rdfs:label": u.get("text", "")[:100],
                "skos:note": u.get("text", ""),
                "fi:unitType": u.get("unit_type", "unknown"),
                "fi:confidence": u.get("confidence", 0),
                "dc:source": u.get("source_file", ""),
            }
            for u in units
        ]

        return chunk

    def write_jsonl(self, chunks: list[dict], output_path: Path) -> None:
        """Write JSON-LD chunks as JSONL (one JSON object per line).

        Args:
            chunks: List of JSON-LD dicts.
            output_path: Path to write the JSONL file.
        """
        with open(output_path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, separators=(",", ":")) + "\n")

    def build_all_chunks(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        iri_map: dict[str, str],
    ) -> list[dict]:
        """Build JSON-LD chunks for all root tasks with subtasks inlined.

        Only root tasks (no parent_task_id) become top-level chunks.
        Child tasks are inlined as subtasks within their parent chunk.

        Args:
            tasks: Full list of task dicts.
            units_by_task: Dict mapping task_id to lists of unit dicts.
            iri_map: Mapping from entity_id to IRI string.

        Returns:
            List of JSON-LD dicts, one per root task.
        """
        # Build parent -> children map
        children_map: dict[str | None, list[dict]] = {}
        for t in tasks:
            parent = t.get("parent_task_id")
            children_map.setdefault(parent, []).append(t)

        root_tasks = children_map.get(None, [])
        chunks: list[dict] = []

        for root in root_tasks:
            subtasks = children_map.get(root["id"], [])
            units = units_by_task.get(root["id"], [])
            chunk = self.build_task_chunk(root, units, subtasks, iri_map)
            chunks.append(chunk)

        return chunks

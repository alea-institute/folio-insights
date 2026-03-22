"""Multi-format task hierarchy exporter.

Produces Markdown, JSON, HTML, OWL, Turtle, JSON-LD, and browsable HTML
exports of discovered task hierarchies with their linked knowledge units
grouped by type.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any


# Knowledge unit type display order and labels
_TYPE_DISPLAY_ORDER = [
    ("best_practice", "Best Practices"),
    ("principle", "Principles"),
    ("pitfall", "Pitfalls"),
    ("procedural_rule", "Procedural Rules"),
    ("citation", "Citations"),
    ("advice", "Advice"),
    ("unknown", "Other"),
]


def group_units_by_type(units: list[dict]) -> dict[str, list[dict]]:
    """Group knowledge units by their unit_type field.

    Returns a dict mapping type names to lists of unit dicts,
    in the display order defined by _TYPE_DISPLAY_ORDER.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        utype = u.get("unit_type", "unknown")
        groups[utype].append(u)

    # Return in display order, only including non-empty groups
    ordered: dict[str, list[dict]] = {}
    for type_key, _label in _TYPE_DISPLAY_ORDER:
        if type_key in groups:
            ordered[type_key] = groups[type_key]

    # Add any types not in the display order
    for type_key, unit_list in groups.items():
        if type_key not in ordered:
            ordered[type_key] = unit_list

    return ordered


def _type_label(type_key: str) -> str:
    """Get the display label for a unit type key."""
    for key, label in _TYPE_DISPLAY_ORDER:
        if key == type_key:
            return label
    return type_key.replace("_", " ").title()


class TaskExporter:
    """Export discovered task hierarchies in multiple formats."""

    def export_markdown(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
    ) -> str:
        """Export task hierarchy as a Markdown outline.

        Tasks are indented by depth, with labels bolded.
        Units are listed by type group under each task.
        Procedural tasks are annotated with "(procedural -- ordered steps)".
        """
        # Build parent-child map
        children_map: dict[str | None, list[dict]] = defaultdict(list)
        for t in tasks:
            children_map[t.get("parent_task_id")].append(t)

        lines: list[str] = ["# Task Hierarchy\n"]

        def _render_task(task: dict, depth: int) -> None:
            indent = "  " * depth
            label = task["label"]
            suffix = ""
            if task.get("is_procedural"):
                suffix = " (procedural -- ordered steps)"
            lines.append(f"{indent}- **{label}**{suffix}")

            # Units for this task
            task_units = units_by_task.get(task["id"], [])
            if task_units:
                grouped = group_units_by_type(task_units)
                for type_key, unit_list in grouped.items():
                    type_name = _type_label(type_key)
                    lines.append(f"{indent}  - *{type_name}*:")
                    for u in unit_list:
                        text = u.get("text", "").strip()
                        conf = u.get("confidence", 0)
                        lines.append(
                            f"{indent}    - {text} (confidence: {conf:.2f})"
                        )

            # Render children
            for child in children_map.get(task["id"], []):
                _render_task(child, depth + 1)

        # Render root tasks (no parent)
        for task in children_map.get(None, []):
            _render_task(task, 0)

        return "\n".join(lines) + "\n"

    def export_json(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        contradictions: list[dict],
        metadata: dict,
    ) -> dict:
        """Export task hierarchy as structured JSON.

        Returns a dict with task tree, unit assignments, contradictions, metadata.
        """
        # Build tree structure
        children_map: dict[str | None, list[dict]] = defaultdict(list)
        for t in tasks:
            children_map[t.get("parent_task_id")].append(t)

        def _build_node(task: dict) -> dict:
            task_units = units_by_task.get(task["id"], [])
            grouped = group_units_by_type(task_units)

            return {
                "id": task["id"],
                "label": task["label"],
                "folio_iri": task.get("folio_iri"),
                "is_procedural": task.get("is_procedural", False),
                "canonical_order": task.get("canonical_order"),
                "is_manual": task.get("is_manual", False),
                "status": task.get("status", "unreviewed"),
                "units": {
                    _type_label(k): [
                        {
                            "id": u["id"],
                            "text": u.get("text", ""),
                            "confidence": u.get("confidence", 0),
                            "source_file": u.get("source_file", ""),
                        }
                        for u in v
                    ]
                    for k, v in grouped.items()
                },
                "unit_count": len(task_units),
                "children": [
                    _build_node(c) for c in children_map.get(task["id"], [])
                ],
            }

        tree = [_build_node(t) for t in children_map.get(None, [])]

        return {
            "metadata": metadata,
            "task_tree": tree,
            "contradictions": contradictions,
        }

    def export_html(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        contradictions: list[dict],
        metadata: dict,
    ) -> str:
        """Export task hierarchy as HTML report with inline dark-theme CSS.

        Produces collapsible sections per task, unit tables, contradiction highlights.
        """
        # Build tree
        children_map: dict[str | None, list[dict]] = defaultdict(list)
        for t in tasks:
            children_map[t.get("parent_task_id")].append(t)

        task_count = len(tasks)
        contra_count = len(contradictions)
        corpus = escape(metadata.get("corpus", ""))

        def _render_task_html(task: dict, depth: int) -> str:
            label = escape(task["label"])
            suffix = ""
            if task.get("is_procedural"):
                suffix = ' <span class="badge procedural">procedural</span>'
            if task.get("is_manual"):
                suffix += ' <span class="badge manual">manual</span>'

            parts = [
                f'<details class="task depth-{depth}" open>',
                f"<summary><strong>{label}</strong>{suffix}</summary>",
                '<div class="task-content">',
            ]

            # Units
            task_units = units_by_task.get(task["id"], [])
            if task_units:
                grouped = group_units_by_type(task_units)
                for type_key, unit_list in grouped.items():
                    type_name = escape(_type_label(type_key))
                    parts.append(f'<h4 class="unit-type">{type_name}</h4>')
                    parts.append("<ul>")
                    for u in unit_list:
                        text = escape(u.get("text", "").strip())
                        conf = u.get("confidence", 0)
                        source = escape(u.get("source_file", ""))
                        parts.append(
                            f'<li>{text} '
                            f'<span class="meta">({conf:.0%} | {source})</span></li>'
                        )
                    parts.append("</ul>")

            # Children
            for child in children_map.get(task["id"], []):
                parts.append(_render_task_html(child, depth + 1))

            parts.append("</div></details>")
            return "\n".join(parts)

        body_parts = []
        for task in children_map.get(None, []):
            body_parts.append(_render_task_html(task, 0))

        # Contradictions section
        contra_html = ""
        if contradictions:
            contra_items = []
            for c in contradictions:
                status = "resolved" if c.get("resolution") else "unresolved"
                contra_items.append(
                    f'<tr class="{status}">'
                    f'<td>{escape(str(c.get("task_id", "")))}</td>'
                    f'<td>{escape(str(c.get("unit_id_a", "")))}</td>'
                    f'<td>{escape(str(c.get("unit_id_b", "")))}</td>'
                    f'<td>{escape(str(c.get("contradiction_type", "")))}</td>'
                    f'<td>{escape(str(c.get("resolution", "unresolved")))}</td>'
                    f"</tr>"
                )
            contra_html = (
                '<section class="contradictions">'
                "<h2>Contradictions</h2>"
                "<table><thead><tr>"
                "<th>Task</th><th>Unit A</th><th>Unit B</th>"
                "<th>Type</th><th>Resolution</th>"
                "</tr></thead><tbody>"
                + "\n".join(contra_items)
                + "</tbody></table></section>"
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Task Hierarchy Report -- {corpus}</title>
<style>
:root {{
    --bg: #1a1a2e;
    --surface: #16213e;
    --text: #e0e0e0;
    --text-dim: #8a8a9a;
    --accent: #64ffda;
    --border: #2a2a4e;
    --badge-proc: #ff9800;
    --badge-manual: #03a9f4;
    --warning: #ff5252;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    padding: 2rem;
    line-height: 1.6;
}}
h1 {{ color: var(--accent); margin-bottom: 0.5rem; font-size: 1.5rem; }}
.summary {{ color: var(--text-dim); margin-bottom: 2rem; font-size: 0.9rem; }}
details {{ margin: 0.25rem 0; padding-left: 1rem; border-left: 2px solid var(--border); }}
details[open] > summary {{ margin-bottom: 0.5rem; }}
summary {{
    cursor: pointer;
    padding: 0.25rem 0;
    list-style: none;
}}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{ content: '+ '; color: var(--accent); }}
details[open] > summary::before {{ content: '- '; }}
.badge {{
    font-size: 0.7rem;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
    color: #000;
    font-weight: 600;
}}
.procedural {{ background: var(--badge-proc); }}
.manual {{ background: var(--badge-manual); }}
.unit-type {{ color: var(--accent); font-size: 0.85rem; margin: 0.5rem 0 0.25rem; }}
ul {{ list-style: disc; padding-left: 1.5rem; }}
li {{ margin: 0.15rem 0; font-size: 0.85rem; }}
.meta {{ color: var(--text-dim); font-size: 0.75rem; }}
.task-content {{ padding: 0.25rem 0; }}
.contradictions {{ margin-top: 2rem; }}
.contradictions h2 {{ color: var(--warning); font-size: 1.2rem; margin-bottom: 0.5rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
th, td {{ padding: 0.4rem 0.8rem; border: 1px solid var(--border); text-align: left; }}
th {{ background: var(--surface); color: var(--accent); }}
tr.unresolved {{ background: rgba(255, 82, 82, 0.1); }}
tr.resolved {{ background: rgba(100, 255, 218, 0.05); }}
</style>
</head>
<body>
<h1>Task Hierarchy Report</h1>
<p class="summary">Corpus: {corpus} | Tasks: {task_count} | Contradictions: {contra_count}</p>
{"".join(body_parts)}
{contra_html}
</body>
</html>"""

    # ------------------------------------------------------------------ #
    # OWL / Turtle / JSON-LD / Browsable HTML exports
    # ------------------------------------------------------------------ #

    async def export_owl(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        contradictions: list[dict],
        metadata: dict,
        db_path: Path,
        output_dir: Path,
    ) -> tuple[str, str, str | None]:
        """Export OWL (RDF/XML) and Turtle, generate changelog.

        Returns (rdfxml_content, turtle_content, changelog_content).
        """
        from folio_insights.services.changelog_generator import ChangelogGenerator
        from folio_insights.services.iri_manager import IRIManager
        from folio_insights.services.owl_serializer import OWLSerializer

        output_dir.mkdir(parents=True, exist_ok=True)

        # Build IRI map
        iri_manager = IRIManager(db_path)
        iri_map: dict[str, str] = {}
        corpus = metadata.get("corpus", "default")
        for task in tasks:
            # Tasks already have folio_iri from discovery; persist if needed
            if task.get("folio_iri"):
                iri_map[task["id"]] = task["folio_iri"]
            else:
                iri_map[task["id"]] = await iri_manager.get_or_create_iri(
                    task["id"], "task", corpus
                )
        for task in tasks:
            for unit in units_by_task.get(task["id"], []):
                iri_map[unit["id"]] = await iri_manager.get_or_create_iri(
                    unit["id"], "unit", corpus
                )

        # Build graph
        serializer = OWLSerializer()
        graph = serializer.build_graph(
            tasks, units_by_task, iri_map, contradictions, metadata
        )

        # Serialize
        rdfxml = serializer.serialize_rdfxml(graph)
        turtle = serializer.serialize_turtle(graph)

        owl_path = output_dir / "folio-insights.owl"
        ttl_path = output_dir / "folio-insights.ttl"

        # Changelog: archive previous, generate diff
        changelog_gen = ChangelogGenerator()
        prev_graph = changelog_gen.load_previous_graph(owl_path)
        changelog_gen.archive_current(owl_path)
        changelog = changelog_gen.generate(graph, prev_graph, corpus)

        owl_path.write_text(rdfxml, encoding="utf-8")
        ttl_path.write_text(turtle, encoding="utf-8")
        (output_dir / "CHANGELOG.md").write_text(changelog, encoding="utf-8")

        return rdfxml, turtle, changelog

    def export_owl_validate(
        self,
        graph: "Graph",  # noqa: F821 -- rdflib.Graph
        output_dir: Path,
    ) -> str:
        """Run SHACL validation and write report.

        Returns the validation report as markdown.
        """
        from folio_insights.services.shacl_validator import SHACLValidator

        output_dir.mkdir(parents=True, exist_ok=True)
        validator = SHACLValidator()
        report = validator.generate_report(graph)
        (output_dir / "validation-report.md").write_text(
            report.markdown, encoding="utf-8"
        )
        return report.markdown

    async def export_jsonld(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        db_path: Path,
        output_dir: Path,
    ) -> str:
        """Export per-task JSON-LD chunks as JSONL.

        Returns the JSONL content string.
        """
        from folio_insights.services.iri_manager import IRIManager
        from folio_insights.services.jsonld_builder import JSONLDBuilder

        output_dir.mkdir(parents=True, exist_ok=True)

        # Build IRI map
        iri_manager = IRIManager(db_path)
        iri_map: dict[str, str] = {}
        corpus = "default"
        for task in tasks:
            if task.get("folio_iri"):
                iri_map[task["id"]] = task["folio_iri"]
            else:
                iri_map[task["id"]] = await iri_manager.get_or_create_iri(
                    task["id"], "task", corpus
                )
        for task in tasks:
            for unit in units_by_task.get(task["id"], []):
                iri_map[unit["id"]] = await iri_manager.get_or_create_iri(
                    unit["id"], "unit", corpus
                )

        builder = JSONLDBuilder()
        chunks = builder.build_all_chunks(tasks, units_by_task, iri_map)

        # Copy context.jsonld to output dir
        context_src = Path(__file__).parent.parent / "export" / "context.jsonld"
        if context_src.exists():
            shutil.copy2(str(context_src), str(output_dir / "context.jsonld"))

        jsonl_path = output_dir / "folio-insights.jsonld"
        builder.write_jsonl(chunks, jsonl_path)
        return jsonl_path.read_text(encoding="utf-8")

    def export_browsable_html(
        self,
        tasks: list[dict],
        units_by_task: dict[str, list[dict]],
        contradictions: list[dict],
        metadata: dict,
    ) -> str:
        """Generate a static browsable HTML site with sidebar navigation.

        Returns the complete HTML string for index.html.
        """
        # Build parent-child map
        children_map: dict[str | None, list[dict]] = defaultdict(list)
        for t in tasks:
            children_map[t.get("parent_task_id")].append(t)

        corpus = escape(metadata.get("corpus", ""))
        task_count = len(tasks)

        # Build sidebar navigation links
        def _nav_item(task: dict, depth: int) -> str:
            tid = escape(task["id"])
            label = escape(task["label"])
            indent = f"padding-left: {12 + depth * 16}px"
            parts = [f'<li><a href="#{tid}" style="{indent}">{label}</a>']
            kids = children_map.get(task["id"], [])
            if kids:
                parts.append("<ul>")
                for child in kids:
                    parts.append(_nav_item(child, depth + 1))
                parts.append("</ul>")
            parts.append("</li>")
            return "\n".join(parts)

        nav_items: list[str] = []
        for root in children_map.get(None, []):
            nav_items.append(_nav_item(root, 0))

        # Build main content sections
        def _task_section(task: dict, depth: int) -> str:
            tid = escape(task["id"])
            label = escape(task["label"])
            heading_tag = f"h{min(depth + 2, 6)}"
            parts = [
                f'<details class="task-section" id="{tid}" open>',
                f"<summary><{heading_tag}>{label}</{heading_tag}></summary>",
                '<div class="task-body">',
            ]

            task_units = units_by_task.get(task["id"], [])
            if task_units:
                grouped = group_units_by_type(task_units)
                for type_key, unit_list in grouped.items():
                    type_name = escape(_type_label(type_key))
                    parts.append(f'<h4 class="unit-group-label">{type_name}</h4>')
                    for u in unit_list:
                        text = escape(u.get("text", "").strip())
                        conf = u.get("confidence", 0)
                        source = escape(u.get("source_file", ""))
                        conf_level = (
                            "high" if conf >= 0.8
                            else "medium" if conf >= 0.5
                            else "low"
                        )
                        parts.append('<div class="unit-card">')
                        parts.append(f'<p class="unit-text">{text}</p>')
                        parts.append('<div class="unit-meta">')
                        parts.append(
                            f'<span class="confidence-badge {conf_level}">'
                            f"{conf:.0%}</span>"
                        )
                        parts.append(
                            f'<span class="source-ref">{source}</span>'
                        )
                        parts.append("</div></div>")

            for child in children_map.get(task["id"], []):
                parts.append(_task_section(child, depth + 1))

            parts.append("</div></details>")
            return "\n".join(parts)

        content_parts: list[str] = []
        for root in children_map.get(None, []):
            content_parts.append(_task_section(root, 0))

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FOLIO Insights -- {corpus}</title>
<style>
:root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242736;
    --text: #e4e6f0;
    --text-dim: #8b8fa3;
    --accent: #6c8cff;
    --accent-dim: rgba(108, 140, 255, 0.25);
    --border: #2e3348;
    --green: #4caf7c;
    --orange: #e8a54c;
    --red: #e05555;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
    min-height: 100vh;
}}
.sidebar {{
    width: 240px;
    min-width: 240px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 24px 0;
    overflow-y: auto;
    position: sticky;
    top: 0;
    height: 100vh;
}}
.sidebar h2 {{
    font-size: 14px;
    font-weight: 600;
    color: var(--accent);
    padding: 0 16px 12px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 8px;
}}
.sidebar ul {{
    list-style: none;
}}
.sidebar a {{
    display: block;
    color: var(--text-dim);
    text-decoration: none;
    font-size: 13px;
    padding: 6px 16px;
    transition: background 150ms, color 150ms;
}}
.sidebar a:hover {{
    background: var(--surface2);
    color: var(--text);
}}
.main {{
    flex: 1;
    max-width: 960px;
    margin: 0 auto;
    padding: 32px 24px;
}}
.main > header {{
    margin-bottom: 32px;
}}
.main > header h1 {{
    font-size: 24px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 4px;
}}
.main > header p {{
    font-size: 13px;
    color: var(--text-dim);
}}
.task-section {{
    margin-bottom: 16px;
}}
.task-section > summary {{
    cursor: pointer;
    list-style: none;
    padding: 8px 0;
}}
.task-section > summary::-webkit-details-marker {{ display: none; }}
.task-section > summary h2,
.task-section > summary h3,
.task-section > summary h4,
.task-section > summary h5,
.task-section > summary h6 {{
    font-weight: 600;
    color: var(--text);
    display: inline;
}}
.task-body {{
    padding-left: 16px;
    border-left: 2px solid var(--border);
    margin-top: 8px;
}}
.unit-group-label {{
    font-size: 12px;
    font-weight: 600;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 16px 0 8px;
}}
.unit-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 24px;
    margin-bottom: 8px;
}}
.unit-text {{
    font-size: 14px;
    line-height: 1.6;
    color: var(--text);
    margin-bottom: 8px;
}}
.unit-meta {{
    display: flex;
    align-items: center;
    gap: 8px;
}}
.confidence-badge {{
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 9999px;
}}
.confidence-badge.high {{
    background: rgba(76, 175, 124, 0.15);
    color: var(--green);
}}
.confidence-badge.medium {{
    background: rgba(232, 165, 76, 0.15);
    color: var(--orange);
}}
.confidence-badge.low {{
    background: rgba(224, 85, 85, 0.15);
    color: var(--red);
}}
.source-ref {{
    font-size: 11px;
    color: var(--text-dim);
}}
</style>
</head>
<body>
<nav class="sidebar">
<h2>Task Hierarchy</h2>
<ul>
{"".join(nav_items)}
</ul>
</nav>
<div class="main">
<header>
<h1>FOLIO Insights</h1>
<p>Corpus: {corpus} | {task_count} tasks</p>
</header>
{"".join(content_parts)}
</div>
</body>
</html>"""

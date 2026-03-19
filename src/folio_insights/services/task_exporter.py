"""Multi-format task hierarchy exporter.

Produces Markdown, JSON, and HTML exports of discovered task hierarchies
with their linked knowledge units grouped by type.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape
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

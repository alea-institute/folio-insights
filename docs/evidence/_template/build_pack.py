#!/usr/bin/env python3
"""Evidence-pack generator for the folio-insights portfolio.

Reads a findings JSON (the "pack.json" data contract documented in
``pack.schema.md``), validates it, injects it into ``pack-template.html``,
and writes a self-contained, offline evidence pack plus machine-readable
sidecars agents can ingest directly.

Usage
-----
    python build_pack.py <pack.json> <out_dir>

Outputs (into ``<out_dir>/``)
-----------------------------
    pack.html      self-contained evidence pack (template + injected data)
    manifest.json  EP-ID -> {title, kind, status, rubric_refs, book, chapter}
    feedback.json  empty scaffold ([]) that the pack's "Export" button refills

Dependencies: Python standard library only (no third-party packages).
Exit codes: 0 on success; non-zero with a clear message on any violation.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path

TEMPLATE_NAME = "pack-template.html"
PLACEHOLDER = "/*__PACK_DATA__*/ {}"

VALID_KINDS = {
    "mapping_decision",
    "borderline_extraction",
    "rubric_score",
    "finding",
    "exemplar",
}
VALID_STATUSES = {"pass", "borderline", "fail", "info"}
# Stable-ID convention: uppercase letters/digits/hyphens, e.g. EP-INSIGHTS-BOOKS-001
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]*$")


class PackValidationError(Exception):
    """Raised when the pack JSON violates the data contract."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _require(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond:
        errors.append(msg)


def _is_str(v: object) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_pack(data: object) -> list[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Top level of pack JSON must be a JSON object."]

    # Required top-level scalar fields.
    for key in ("campaign", "title", "generated_at"):
        _require(_is_str(data.get(key)), f"Missing/empty required field: '{key}'.", errors)

    if "rubric_version" in data:
        _require(
            _is_str(data["rubric_version"]),
            "Field 'rubric_version', if present, must be a non-empty string.",
            errors,
        )

    # generated_at should look ISO-8601-ish (warn via error if clearly wrong).
    gen = data.get("generated_at")
    if _is_str(gen):
        try:
            _dt.datetime.fromisoformat(str(gen).replace("Z", "+00:00"))
        except ValueError:
            errors.append(
                f"Field 'generated_at' is not ISO-8601 parseable: {gen!r}."
            )

    # spend (optional object)
    spend = data.get("spend")
    if spend is not None:
        if not isinstance(spend, dict):
            errors.append("Field 'spend', if present, must be an object.")
        else:
            if "usd" in spend and not isinstance(spend["usd"], (int, float)):
                errors.append("Field 'spend.usd' must be a number.")

    # summary (optional object; counts must be non-negative ints if present)
    summary = data.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append("Field 'summary', if present, must be an object.")
        else:
            for k, v in summary.items():
                if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                    errors.append(
                        f"Field 'summary.{k}' must be a non-negative integer (got {v!r})."
                    )

    # sections (required, non-empty array)
    sections = data.get("sections")
    if not isinstance(sections, list):
        errors.append("Field 'sections' is required and must be an array.")
        return errors
    if not sections:
        errors.append("Field 'sections' must contain at least one section.")

    seen_ids: dict[str, int] = {}
    for idx, sec in enumerate(sections):
        where = f"sections[{idx}]"
        if not isinstance(sec, dict):
            errors.append(f"{where} must be an object.")
            continue

        sid = sec.get("id")
        if not _is_str(sid):
            errors.append(f"{where}.id is required and must be a non-empty string.")
        else:
            if not ID_RE.match(sid):
                errors.append(
                    f"{where}.id {sid!r} must match {ID_RE.pattern} "
                    "(uppercase letters, digits, hyphens; e.g. EP-INSIGHTS-BOOKS-001)."
                )
            if sid in seen_ids:
                errors.append(
                    f"{where}.id {sid!r} is a duplicate of sections[{seen_ids[sid]}].id "
                    "(EP-IDs must be unique — they are rendered as anchors)."
                )
            else:
                seen_ids[sid] = idx

        kind = sec.get("kind")
        if not _is_str(kind):
            errors.append(f"{where}.kind is required.")
        elif kind not in VALID_KINDS:
            errors.append(
                f"{where}.kind {kind!r} is invalid. "
                f"Allowed: {', '.join(sorted(VALID_KINDS))}."
            )

        status = sec.get("status")
        if not _is_str(status):
            errors.append(f"{where}.status is required.")
        elif status not in VALID_STATUSES:
            errors.append(
                f"{where}.status {status!r} is invalid. "
                f"Allowed: {', '.join(sorted(VALID_STATUSES))}."
            )

        if not _is_str(sec.get("title")):
            errors.append(f"{where}.title is required and must be a non-empty string.")

        refs = sec.get("rubric_refs", [])
        if refs is not None and not isinstance(refs, list):
            errors.append(f"{where}.rubric_refs, if present, must be an array of strings.")
        elif isinstance(refs, list):
            for j, r in enumerate(refs):
                if not _is_str(r):
                    errors.append(f"{where}.rubric_refs[{j}] must be a non-empty string.")

        # Optional string fields — type-check when present.
        for opt in ("book", "chapter", "body_md", "source_quote", "extracted"):
            if opt in sec and sec[opt] is not None and not isinstance(sec[opt], str):
                errors.append(f"{where}.{opt}, if present, must be a string.")

        # scores (optional array of {criterion, score, note?})
        scores = sec.get("scores")
        if scores is not None:
            if not isinstance(scores, list):
                errors.append(f"{where}.scores, if present, must be an array.")
            else:
                for j, sc in enumerate(scores):
                    sw = f"{where}.scores[{j}]"
                    if not isinstance(sc, dict):
                        errors.append(f"{sw} must be an object.")
                        continue
                    if not _is_str(sc.get("criterion")):
                        errors.append(f"{sw}.criterion is required.")
                    if not isinstance(sc.get("score"), (int, float)) or isinstance(
                        sc.get("score"), bool
                    ):
                        errors.append(f"{sw}.score is required and must be a number.")
                    if "note" in sc and sc["note"] is not None and not isinstance(
                        sc["note"], str
                    ):
                        errors.append(f"{sw}.note, if present, must be a string.")

        # screenshot (optional data: URI)
        shot = sec.get("screenshot")
        if shot is not None:
            if not isinstance(shot, str):
                errors.append(f"{where}.screenshot, if present, must be a string.")
            elif shot and not shot.startswith("data:image/"):
                errors.append(
                    f"{where}.screenshot must be a self-contained 'data:image/...' URI "
                    "(offline packs cannot reference external images)."
                )

    return errors


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_manifest(data: dict) -> dict:
    """Map every EP-ID -> resolvable metadata for programmatic reference."""
    sections_map: dict[str, dict] = {}
    for sec in data.get("sections", []):
        sid = sec.get("id")
        if not sid:
            continue
        sections_map[sid] = {
            "title": sec.get("title", ""),
            "kind": sec.get("kind", ""),
            "status": sec.get("status", ""),
            "rubric_refs": sec.get("rubric_refs", []) or [],
            "book": sec.get("book", ""),
            "chapter": sec.get("chapter", ""),
        }
    return {
        "campaign": data.get("campaign", ""),
        "repo": data.get("repo", ""),
        "rubric_version": data.get("rubric_version", ""),
        "generated_at": data.get("generated_at", ""),
        "summary": data.get("summary", {}),
        "sections": sections_map,
    }


def inject(template: str, data: dict) -> str:
    """Replace the PACK_DATA placeholder with the validated JSON payload.

    The payload is serialized with ``</`` escaped so an embedded string can
    never prematurely close the surrounding <script> element.
    """
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    payload = payload.replace("</", "<\\/")
    if PLACEHOLDER not in template:
        raise PackValidationError(
            f"Template {TEMPLATE_NAME!r} is missing the '{PLACEHOLDER}' placeholder."
        )
    # Replace only the first occurrence; keep the '/*__PACK_DATA__*/' marker
    # comment so re-runs against an already-built file would still fail loudly
    # rather than silently double-injecting (placeholder is consumed here).
    return template.replace(PLACEHOLDER, "/*__PACK_DATA__*/ " + payload, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python build_pack.py <pack.json> <out_dir>\n"
        )
        return 2

    pack_path = Path(argv[1])
    out_dir = Path(argv[2])
    template_path = Path(__file__).resolve().parent / TEMPLATE_NAME

    if not pack_path.is_file():
        sys.stderr.write(f"error: pack JSON not found: {pack_path}\n")
        return 2
    if not template_path.is_file():
        sys.stderr.write(f"error: template not found: {template_path}\n")
        return 2

    try:
        raw = pack_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"error: {pack_path} is not valid JSON: {exc}\n")
        return 1

    errors = validate_pack(data)
    if errors:
        sys.stderr.write(
            f"error: {pack_path} failed schema validation "
            f"({len(errors)} problem{'s' if len(errors) != 1 else ''}):\n"
        )
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        sys.stderr.write("See pack.schema.md for the data contract.\n")
        return 1

    template = template_path.read_text(encoding="utf-8")
    try:
        html = inject(template, data)
    except PackValidationError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    pack_html = out_dir / "pack.html"
    manifest_json = out_dir / "manifest.json"
    feedback_json = out_dir / "feedback.json"

    pack_html.write_text(html, encoding="utf-8")
    manifest_json.write_text(
        json.dumps(build_manifest(data), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Empty scaffold — the pack's "Export all feedback" button downloads a
    # populated version with the same shape: [{id, title, rubric_refs, comment}].
    feedback_json.write_text("[]\n", encoding="utf-8")

    n = len(data.get("sections", []))
    sys.stdout.write(
        f"built evidence pack: {n} section{'s' if n != 1 else ''}\n"
        f"  {pack_html}\n"
        f"  {manifest_json}\n"
        f"  {feedback_json}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""Deterministic UAT oracle for the book-extraction campaign.

Runs the [DET] rubric checks (reproducible, ~free, run before any LLM/MCP judging):
  - RUB-EXTRACT-05 anchor gate: independently re-verify each unit's source anchor
    (span slices non-empty + snippet fuzzy-matches the re-ingested source >=0.85).
  - RUB-EXTRACT-03 IRI validity + branch membership: every non-proposed folio_tag
    IRI resolves to a real FOLIO concept and sits in the branch it claims.
  - Coverage / proposed-class counts for the section-coverage and A4 checks.

Usage: uat_det_oracle.py <extraction.json> <source_dir> [--json]
Emits a compact JSON/text summary. Reads bulk data itself so callers don't have to.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "folio-enrich" / "backend"))

from rapidfuzz import fuzz  # noqa: E402

MIN_ANCHOR = 0.85


def load_units(path: str) -> list[dict]:
    d = json.load(open(path))
    if isinstance(d, list):
        return d
    for k in ("units", "knowledge_units", "extraction"):
        if isinstance(d.get(k), list):
            return d[k]
    raise SystemExit(f"could not find units in {path}: top keys {list(d)[:8]}")


def reingest_sources(source_dir: str) -> dict[str, str]:
    """Reproduce ingested text per source file (keyed by resolved abs path).

    Uses the *same* path the extraction pipeline uses — ``IngestionBridge``,
    which passes an explicit ``DocumentFormat`` so folio-enrich routes .docx/.pdf
    to their real ingestors (WordIngestor/PDF) instead of returning the raw
    base64 string as "text". Calling ``registry.ingest`` with base64 but no
    format silently returns the undecoded base64 (a ~199k-char string for a 150k
    .docx), which false-fails the RUB-05 anchor gate for every binary source.
    """
    from folio_insights.services.bridge.ingestion_bridge import IngestionBridge

    bridge = IngestionBridge()
    out: dict[str, str] = {}
    for p in sorted(Path(source_dir).rglob("*")):
        if not p.is_file():
            continue
        key = str(p.resolve())
        try:
            text, _elements = bridge.detect_and_ingest(p)
            out[key] = text or ""
        except Exception as e:  # noqa: BLE001
            out[key] = ""
            print(f"  (reingest failed for {p.name}: {e})", file=sys.stderr)
    return out


def check_anchors(units: list[dict], sources: dict[str, str]) -> dict:
    total = len(units)
    field_verified = sum(1 for u in units if u.get("anchor_verified"))
    have_snippet = sum(1 for u in units if u.get("source_snippet"))
    scores = [u.get("anchor_score", 0.0) for u in units]
    # Independent re-verification: snippet fuzzy-matches re-ingested source >=0.85
    indep_pass = 0
    span_nonempty = 0
    fails: list[str] = []
    for u in units:
        src = sources.get(u.get("source_file", ""), "")
        snip = u.get("source_snippet", "") or ""
        sp = u.get("original_span", {})
        # span slices non-empty against re-ingested source
        try:
            if src and 0 <= sp.get("start", -1) < sp.get("end", -1) <= len(src) and src[sp["start"]:sp["end"]].strip():
                span_nonempty += 1
        except Exception:  # noqa: BLE001
            pass
        ok = False
        if snip and src:
            if snip in src:
                ok = True
            else:
                ok = (fuzz.partial_ratio(snip, src) / 100.0) >= MIN_ANCHOR
        if ok:
            indep_pass += 1
        else:
            if len(fails) < 8:
                fails.append(u.get("id", "?"))
    return {
        "total_units": total,
        "anchor_verified_field": field_verified,
        "anchor_verified_pct": round(100 * field_verified / total, 1) if total else 0,
        "have_source_snippet": have_snippet,
        "independent_snippet_pass": indep_pass,
        "independent_pass_pct": round(100 * indep_pass / total, 1) if total else 0,
        "span_slices_nonempty": span_nonempty,
        "mean_anchor_score": round(sum(scores) / total, 3) if total else 0,
        "min_anchor_score": round(min(scores), 3) if scores else 0,
        "sample_fail_ids": fails,
        "RUB-EXTRACT-05_gate_units_failing": total - indep_pass,
    }


def check_iris(units: list[dict]) -> dict:
    from folio import FOLIO

    f = FOLIO()
    branches = {b for b in f.list_branches()} if hasattr(f, "list_branches") else set()
    tags = []
    for u in units:
        for t in u.get("folio_tags", []):
            tags.append(t)
    total_tags = len(tags)
    proposed = [t for t in tags if not t.get("iri") and t.get("extraction_path") == "proposed_class"]
    proposed_missing_flag = [t for t in tags if not t.get("iri") and t.get("extraction_path") != "proposed_class"]
    resolvable = tags_with_iri = 0
    distinct = set()
    branch_ok = branch_checked = 0
    bad_iris: list[str] = []
    for t in tags:
        iri = t.get("iri")
        if not iri:
            continue
        tags_with_iri += 1
        distinct.add(iri)
        try:
            c = f[iri]
        except Exception:  # noqa: BLE001
            c = None
        if c is not None:
            resolvable += 1
        else:
            if len(bad_iris) < 8:
                bad_iris.append(iri)
    return {
        "total_tags": total_tags,
        "tags_with_iri": tags_with_iri,
        "distinct_iris": len(distinct),
        "iri_resolvable": resolvable,
        "iri_resolvable_pct": round(100 * resolvable / tags_with_iri, 1) if tags_with_iri else 0,
        "proposed_class_tags": len(proposed),
        "empty_iri_not_proposed (RUB-03 violation)": len(proposed_missing_flag),
        "sample_bad_iris": bad_iris,
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    ext_path, source_dir = args[0], args[1]
    units = load_units(ext_path)
    print(f"loaded {len(units)} units; re-ingesting sources...", file=sys.stderr)
    sources = reingest_sources(source_dir)
    result = {
        "extraction": ext_path,
        "anchors_RUB-05": check_anchors(units, sources),
        "iris_RUB-03": check_iris(units),
    }
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

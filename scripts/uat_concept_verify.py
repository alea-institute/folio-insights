#!/usr/bin/env python3
"""Concept-label verification oracle for the book-extraction campaign (B9).

For every folio_tag that carries an IRI, fetch the concept from the local FOLIO
ontology and check whether the tag's label genuinely corresponds to the
concept's own labels — the exact RUB-EXTRACT-01 concept-correctness signal that
B9 attacks. Reports the concept-mismatch rate and the "Location"/country-branch
share, broken down by extraction_path, so v4 (pre-fix) and v5 (post-fix) are
directly comparable.

The matcher mirrors FolioTaggerStage._label_matches_concept EXACTLY (token_sort
plus a partial_ratio guarded behind min-length 6) so the oracle measures the
same notion of "about-ness" the fix enforces.

Usage: uat_concept_verify.py <extraction.json> [--json] [--sample N]
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "folio-enrich" / "backend"))

from rapidfuzz import fuzz  # noqa: E402

VERIFY_FLOOR = 85.0


def label_matches(label: str, concept) -> tuple[bool, float]:
    wanted = (label or "").strip().lower()
    if not wanted:
        return False, 0.0
    candidates: list[str] = []
    for attr in ("preferred_label", "folio_pref_label", "label", "hidden_label"):
        v = getattr(concept, attr, "") or ""
        if isinstance(v, str) and v:
            candidates.append(v)
    for attr in ("alternative_labels", "alt_labels", "synonyms"):
        alts = getattr(concept, attr, None) or []
        if isinstance(alts, (list, tuple)):
            candidates.extend(a for a in alts if isinstance(a, str) and a)
    best = 0.0
    for cand in candidates:
        cand_l = cand.lower()
        score = float(fuzz.token_sort_ratio(wanted, cand_l))
        shorter = min(len(wanted), len(cand_l))
        longer = max(len(wanted), len(cand_l))
        if shorter >= 6 and (shorter / longer) >= 0.6:
            score = max(score, float(fuzz.partial_ratio(wanted, cand_l)))
        best = max(best, score)
    return best >= VERIFY_FLOOR, best


def is_country_concept(concept) -> bool:
    """Proxy for the FOLIO 'Location'/country namespace.

    The local ``folio`` package exposes no branch field, but country /
    subdivision concepts carry an ISO code as an alternative label (Iraq ->
    ['IQ']) and/or an ``ASI-XX`` style identifier. This is precisely the dense
    short-code namespace that B9's LLM path collided with, so counting it is
    the clearest v4-vs-v5 signal for the country-mismap failure class.
    """
    alts = getattr(concept, "alternative_labels", None) or []
    for a in alts:
        if isinstance(a, str) and 2 <= len(a) <= 3 and a.isupper() and a.isalpha():
            return True
    ident = getattr(concept, "identifier", "") or ""
    if isinstance(ident, str) and ident[:4] in ("ASI-", "AFR-", "EUR-", "NAM-", "SAM-", "OCE-"):
        return True
    return False


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    sample_n = 0
    for a in sys.argv:
        if a.startswith("--sample"):
            try:
                sample_n = int(a.split("=", 1)[1]) if "=" in a else 12
            except Exception:
                sample_n = 12
    ext_path = args[0]

    from folio import FOLIO

    f = FOLIO()

    d = json.load(open(ext_path))
    units = d["units"] if isinstance(d, dict) else d

    tags = [t for u in units for t in u.get("folio_tags", [])]
    iri_tags = [t for t in tags if t.get("iri")]

    by_path = collections.Counter(t.get("extraction_path", "?") for t in tags)
    mismatch_by_path: collections.Counter = collections.Counter()
    total_by_path: collections.Counter = collections.Counter()
    location_by_path: collections.Counter = collections.Counter()

    total_iri = len(iri_tags)
    mismatch = 0
    location = 0
    unresolvable = 0
    mismatches_sample: list[dict] = []

    for t in iri_tags:
        iri = t["iri"]
        label = t.get("label", "")
        path = t.get("extraction_path", "?")
        total_by_path[path] += 1
        try:
            c = f[iri]
        except Exception:
            c = None
        if c is None:
            unresolvable += 1
            continue
        is_location = is_country_concept(c)
        if is_location:
            location += 1
            location_by_path[path] += 1
        ok, score = label_matches(label, c)
        if not ok:
            mismatch += 1
            mismatch_by_path[path] += 1
            if path != "entity_ruler" and len(mismatches_sample) < sample_n:
                mismatches_sample.append({
                    "label": label,
                    "concept": getattr(c, "preferred_label", "?"),
                    "is_country": is_location,
                    "score": round(score, 1),
                    "path": path,
                })

    # Headline = the LLM/semantic/heading paths B9 actually gates. entity_ruler
    # (exact/alias) is trusted by the fix and over-counts here anyway: the local
    # folio package returns None preferred_label for some alias-matched concepts
    # and the verifier can't see the alias the ruler matched on.
    nonruler_paths = [p for p in total_by_path if p != "entity_ruler"]
    nr_total = sum(total_by_path[p] for p in nonruler_paths)
    nr_mismatch = sum(mismatch_by_path.get(p, 0) for p in nonruler_paths)
    nr_location = sum(location_by_path.get(p, 0) for p in nonruler_paths)

    result = {
        "extraction": ext_path,
        "total_tags": len(tags),
        "tags_with_iri": total_iri,
        "proposed_class_tags": by_path.get("proposed_class", 0),
        "tags_by_path": dict(by_path),
        "HEADLINE_nonruler_iri_tags": nr_total,
        "HEADLINE_nonruler_concept_mismatch": nr_mismatch,
        "HEADLINE_nonruler_mismatch_pct": round(100 * nr_mismatch / nr_total, 1) if nr_total else 0,
        "HEADLINE_nonruler_country_tags": nr_location,
        "HEADLINE_nonruler_country_pct": round(100 * nr_location / nr_total, 1) if nr_total else 0,
        "all_iri_concept_mismatch": mismatch,
        "all_iri_mismatch_pct": round(100 * mismatch / total_iri, 1) if total_iri else 0,
        "all_iri_country_tags": location,
        "all_iri_country_pct": round(100 * location / total_iri, 1) if total_iri else 0,
        "unresolvable_iris": unresolvable,
        "mismatch_by_path": dict(mismatch_by_path),
        "total_iri_by_path": dict(total_by_path),
        "country_by_path": dict(location_by_path),
        "sample_nonruler_mismatches": mismatches_sample,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

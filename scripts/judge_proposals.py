"""LLM-judge scaffolding — Stage B2 retrieval + floor (Claude-Code-side, $0 app-side).

For every deterministic survivor this:
  1. Retrieves the top-K lexically-nearest FOLIO concepts (token_sort_ratio over
     primary labels) and attaches them WITH DEFINITIONS as the comparison set —
     because the verdict must be judged on definitions, not labels (the
     charge→Encumbrance lesson).
  2. Applies a retrieval FLOOR: survivors with no FOLIO concept within lexical
     range (best < --floor) are recorded NOVEL (judged_by=retrieval-floor) with
     the nearest concepts attached for reference.
  3. Writes the remaining band (a genuine near-candidate exists) to a judge
     worklist JSON for definition-level Claude judgment (main agent or subagents).

This adds NO app-side LLM calls. The actual NOVEL/SYNONYM/DUPLICATE verdicts for
the worklist are produced Claude-Code-side and applied with apply_judgments().

Usage:
  python scripts/judge_proposals.py \
    --registry data/governance/proposed_class_registry.json \
    --lexicon <folio_lexicon.json> --owl <FOLIO.owl> \
    --worklist data/governance/judge_worklist.json --floor 74 --k 4
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from rapidfuzz import fuzz, process


def build_choices(lexicon: dict):
    prim = {}
    for norm, hits in lexicon["by_norm"].items():
        for iri, label, form in hits:
            if form == "primary":
                prim.setdefault(norm, (iri, label))
    return prim, list(prim.keys())


def nearest(norm: str, prim: dict, choices: list, by_iri: dict, k: int, min_score: int):
    matches = process.extract(norm, choices, scorer=fuzz.token_sort_ratio, limit=k)
    out = []
    for norm_key, score, _ in matches:
        if score < min_score:
            continue
        iri, label = prim[norm_key]
        out.append({"iri": iri, "label": label,
                    "definition": by_iri.get(iri, {}).get("definition", ""),
                    "score": round(score, 1)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--worklist", required=True)
    ap.add_argument("--floor", type=int, default=74)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--min-candidate", type=int, default=60)
    args = ap.parse_args()

    lexicon = json.loads(Path(args.lexicon).read_text())
    prim, choices = build_choices(lexicon)
    by_iri = lexicon["by_iri"]

    registry = json.loads(Path(args.registry).read_text())
    entries = registry["proposals"]

    floored = 0
    worklist = []
    for e in entries:
        if e.get("judge") is not None:
            continue  # deterministic dup/merge or already judged
        cands = nearest(e["normalized_label"], prim, choices, by_iri, args.k, args.min_candidate)
        best = cands[0]["score"] if cands else 0
        if best < args.floor:
            e["judge"] = {
                "verdict": "NOVEL", "target_iri": None, "target_proposal_id": None,
                "nearest": cands,
                "reasoning": (f"No FOLIO concept within lexical retrieval range "
                              f"(best={best} for “{e['proposed_label']}”). Recorded NOVEL; "
                              f"definitions of the nearest concepts are attached for reference."),
                "judged_by": "claude-code:retrieval-floor",
            }
            floored += 1
        else:
            worklist.append({
                "proposal_id": e["proposal_id"],
                "proposed_label": e["proposed_label"],
                "draft_definition": e["draft_definition"],
                "supporting_excerpt": (e["supporting_units"][0]["source_text_excerpt"]
                                       if e.get("supporting_units") else ""),
                "candidates": cands,
            })

    Path(args.registry).write_text(json.dumps(registry, indent=2, ensure_ascii=False))
    Path(args.worklist).write_text(json.dumps(
        {"floor": args.floor, "count": len(worklist), "items": worklist}, indent=2, ensure_ascii=False))
    print(json.dumps({"floored_novel": floored, "worklist": len(worklist),
                      "worklist_path": args.worklist}))


def apply_judgments(registry_path: str, judgments: list[dict]) -> dict:
    """Apply Claude-produced verdicts to the registry. judgments: list of
    {proposal_id, verdict, target_iri?, target_proposal_id?, reasoning, nearest?}."""
    registry = json.loads(Path(registry_path).read_text())
    by_id = {e["proposal_id"]: e for e in registry["proposals"]}
    applied = 0
    for j in judgments:
        e = by_id.get(j["proposal_id"])
        if not e:
            continue
        block = {
            "verdict": j["verdict"],
            "target_iri": j.get("target_iri"),
            "target_proposal_id": j.get("target_proposal_id"),
            "nearest": j.get("nearest", (e.get("judge") or {}).get("nearest", [])),
            "reasoning": j.get("reasoning", ""),
            "judged_by": j.get("judged_by", "claude-code:opus"),
        }
        e["judge"] = block
        applied += 1
    Path(registry_path).write_text(json.dumps(registry, indent=2, ensure_ascii=False))
    return {"applied": applied}


if __name__ == "__main__":
    main()

"""Apply pasted approval decisions to the registry and export the backlog.

Ingests the JSON emitted by the approval-queue artifact's "Copy decisions"
button (schema proposed-class-approvals/v1), writes each entry's ``decision``
block back into the registry, and exports every approved proposal to a machine-
readable ontology-extension backlog (JSONL) ready for FOLIO submission.

Usage:
  python scripts/apply_approvals.py \
    --registry data/governance/proposed_class_registry.json \
    --decisions decisions.json \
    --backlog data/governance/ontology_extension_backlog.jsonl
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path

_VALID = {"approve", "reject", "merge", "needs_work"}
_STATUS = {"approve": "approved", "reject": "rejected", "merge": "merged",
           "needs_work": "needs_work"}


def apply_decisions(registry: dict, decisions: dict) -> dict:
    by_id = {e["proposal_id"]: e for e in registry["proposals"]}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    applied = skipped = 0
    for pid, d in decisions.items():
        e = by_id.get(pid)
        if not e:
            skipped += 1
            continue
        raw = d.get("status")
        status = _STATUS.get(raw, "pending") if raw in _VALID else "pending"
        e["decision"] = {"status": status, "note": d.get("note", ""), "decided_at": now}
        applied += 1
    return {"applied": applied, "skipped": skipped}


def export_backlog(registry: dict) -> list[dict]:
    rows = []
    for e in registry["proposals"]:
        if e.get("decision", {}).get("status") != "approved":
            continue
        j = e.get("judge") or {}
        rows.append({
            "proposal_id": e["proposal_id"],
            "label": e["proposed_label"],
            "draft_definition": e.get("decision", {}).get("note") or e.get("draft_definition", ""),
            "suggested_parent": next((n.get("iri") for n in (j.get("nearest") or [])
                                      if j.get("verdict") == "NEEDS_WORK"), None),
            "occurrences": e.get("occurrences", 0),
            "provenance": e.get("provenance", {}),
            "supporting_units": e.get("supporting_units", []),
            "judge_verdict": j.get("verdict"),
            "approved_note": e.get("decision", {}).get("note", ""),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--backlog", required=True)
    args = ap.parse_args()

    registry = json.loads(Path(args.registry).read_text())
    payload = json.loads(Path(args.decisions).read_text())
    decisions = payload.get("decisions", payload)

    stats = apply_decisions(registry, decisions)
    Path(args.registry).write_text(json.dumps(registry, indent=2, ensure_ascii=False))

    rows = export_backlog(registry)
    with open(args.backlog, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(json.dumps({**stats, "backlog_rows": len(rows), "backlog": args.backlog}))


if __name__ == "__main__":
    main()
